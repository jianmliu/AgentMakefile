"""Declarative model routing — extracted from selector.py to break the
selector<->model-routing coupling. Depends only on the shared matcher core."""
from __future__ import annotations

from agentmf.diagnostics import Diagnostics
from agentmf.ir import normalize
from agentmf.loader import load_source_with_diagnostics
from agentmf.models import IRModel
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from agentmf.matcher import _append_match_details, _candidate_source_rank, _match_score, build_request_profile


@dataclass
class ModelRoutingResult:
    diagnostics: Diagnostics
    recommendation: Optional[Dict[str, Any]] = None

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def recommend_model(
    path: Union[Path, str],
    request: Optional[str] = None,
) -> ModelRoutingResult:
    """Standalone, orthogonal model routing — independent of target selection.

    Loads the module, normalizes, and recommends a model purely from the request
    and the `models:` block. Never depends on (or fails because of) target
    routing. Returns recommendation=None when no `models:` block is defined.
    """
    diagnostics = Diagnostics()
    source, load_diagnostics = load_source_with_diagnostics(path)
    diagnostics.extend(load_diagnostics.items)
    if source is None or diagnostics.has_errors:
        return ModelRoutingResult(diagnostics)
    ir = normalize(source, diagnostics)
    if ir is None or diagnostics.has_errors:
        return ModelRoutingResult(diagnostics)
    return ModelRoutingResult(diagnostics, _recommend_model(ir.models, request))


def _recommend_model(models: List[IRModel], request: Optional[str]) -> Optional[Dict[str, Any]]:
    """Advisory model routing: pick the best-matching model for the request.

    Reuses the same keyword match machinery as target routing (a model is just
    another selectable resource with `match` terms + priority). When no model's
    match terms hit the request, fall back to the `default: true` model (or the
    highest-priority one). Returns None when no `models:` block is defined, so
    existing modules are unaffected. This is advisory only — the host still owns
    the actual model call.
    """
    if not models:
        return None

    def pack(model: IRModel, reason: str, details: List[dict]) -> Dict[str, Any]:
        return {
            "model": model.name,
            "family": model.family,
            "cost": model.cost,
            "capabilities": list(model.capabilities),
            "priority": model.priority,
            "reason": reason,
            "matched_terms": [detail["term"] for detail in details],
            "match_score": _match_score(details),
            "pricing": dict(model.pricing) if model.pricing else None,
        }

    matches = []
    if request:
        profile = build_request_profile(request)
        for model in models:
            details: List[dict] = []
            seen: set = set()
            _append_match_details(details, seen, model.match.values(), profile, source=None)
            if details:
                matches.append(
                    (_candidate_source_rank(details), model.priority, _match_score(details), model.name, model, details)
                )
    if matches:
        matches.sort(key=lambda item: (item[0], -item[1], -item[2], item[3]))
        *_, model, details = matches[0]
        return pack(model, "matched", details)

    pool = [model for model in models if model.default] or list(models)
    pool.sort(key=lambda model: (-model.priority, model.name))
    return pack(pool[0], "default", [])
