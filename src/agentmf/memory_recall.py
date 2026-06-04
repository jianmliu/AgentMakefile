"""Kind-aware memory recall — the read side of typed memory.

Routes a request against a scanned memory corpus (a MemoryMakefile) with the
existing matcher, optionally filters the selected units by `kind`, and renders a
kind-aware bundle: procedural units become actionable "apply" lines; semantic /
episodic units become context lines. Reuses the selector — no backend changes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from agentmf.loader import load_source_with_diagnostics
from agentmf.selector import DEFAULT_N_BEST, create_link_plan

_KIND_ORDER = ["procedural", "semantic", "episodic", "working"]
_KIND_LABELS = {
    "procedural": "## Procedures (apply)",
    "semantic": "## Facts",
    "episodic": "## History",
    "working": "## Scratch",
}


def recall_memory(
    path: Union[str, Path],
    request: str,
    *,
    kinds: Optional[Sequence[str]] = None,
    matcher: str = "keyword",
    n_best: int = DEFAULT_N_BEST,
) -> Dict[str, Any]:
    """Return `{units, bundle, diagnostics}` for a request. `units` is the
    task-scoped, kind-filtered set of memory units (name, kind, description);
    `bundle` is their kind-aware rendering."""
    source, diagnostics = load_source_with_diagnostics(Path(path))
    if source is None:
        return {"units": [], "bundle": "", "diagnostics": diagnostics.to_list()}

    plan = create_link_plan(Path(path), request=request, matcher=matcher, n_best=n_best)
    kind_filter = set(kinds) if kinds else None

    units: List[Dict[str, Any]] = []
    seen: set = set()
    for target_name in plan.plan.get("selected_targets", []) if plan.plan else []:
        target = source.targets.get(target_name)
        if target is None:
            continue
        for skill_ref in target.skills:
            name = skill_ref.split(":")[-1]
            skill = source.skills.get(name) or source.skills.get(skill_ref)
            if skill is None or name in seen:
                continue
            seen.add(name)
            kind = skill.kind or "semantic"
            if kind_filter is not None and kind not in kind_filter:
                continue
            units.append({"name": name, "kind": kind, "description": skill.description or ""})

    return {"units": units, "bundle": _render_bundle(units), "diagnostics": plan.diagnostics.to_list()}


def _render_bundle(units: List[Dict[str, Any]]) -> str:
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for unit in units:
        by_kind.setdefault(unit["kind"], []).append(unit)

    lines: List[str] = []
    for kind in _KIND_ORDER:
        group = by_kind.get(kind)
        if not group:
            continue
        lines.append(_KIND_LABELS.get(kind, f"## {kind.title()}"))
        for unit in group:
            if kind == "procedural":
                lines.append(f"- apply `{unit['name']}` — {unit['description']}")
            else:
                lines.append(f"- {unit['description']}")
        lines.append("")
    return ("\n".join(lines).rstrip() + "\n") if lines else ""
