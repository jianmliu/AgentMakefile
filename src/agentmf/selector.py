from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.ir import normalize
from agentmf.loader import load_source_with_diagnostics
from agentmf.models import IRTarget

FRAGMENT_BACKEND_DIRS = {
    "agents-fragments": "agents",
    "claude-fragments": "claude",
}


@dataclass
class LinkPlanResult:
    diagnostics: Diagnostics
    plan: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_link_plan(
    path: Union[Path, str],
    request: Optional[str] = None,
    target_names: Optional[List[str]] = None,
    backend: str = "agents-fragments",
) -> LinkPlanResult:
    diagnostics = Diagnostics()
    if backend not in FRAGMENT_BACKEND_DIRS:
        diagnostics.error(
            "AMF115",
            f"unsupported fragment backend {backend}",
            "backend",
            f"choose one of: {', '.join(sorted(FRAGMENT_BACKEND_DIRS))}",
        )
        return LinkPlanResult(diagnostics)

    source, load_diagnostics = load_source_with_diagnostics(path)
    diagnostics.extend(load_diagnostics.items)
    if source is None or diagnostics.has_errors:
        return LinkPlanResult(diagnostics)

    ir = normalize(source, diagnostics)
    if ir is None or diagnostics.has_errors:
        return LinkPlanResult(diagnostics)

    targets_by_name = {target.name: target for target in ir.targets}
    requested_targets = list(target_names or [])
    if requested_targets:
        selected_targets = _explicit_targets(requested_targets, targets_by_name, diagnostics)
        selection_mode = "explicit_target"
    elif request:
        selected_targets = _targets_for_request(request, ir.targets, diagnostics)
        selection_mode = "request"
    else:
        diagnostics.error("AMF116", "select requires a request or at least one explicit target", "select")
        return LinkPlanResult(diagnostics)

    if diagnostics.has_errors:
        return LinkPlanResult(diagnostics)

    closure = _target_closure(selected_targets, targets_by_name)
    fragment_dir = FRAGMENT_BACKEND_DIRS[backend]
    plan = {
        "version": 1,
        "backend": backend,
        "selection": {
            "mode": selection_mode,
            "request": request if selection_mode == "request" else None,
            "targets": requested_targets,
        },
        "selected_targets": [target.name for target in selected_targets],
        "target_closure": [target.name for target in closure],
        "fragments": [
            {
                "backend": backend,
                "target": target.name,
                "path": f".agentmf/fragments/{fragment_dir}/{_fragment_file_name(target.name)}.md",
            }
            for target in closure
        ],
    }
    return LinkPlanResult(diagnostics, plan)


def _explicit_targets(
    target_names: List[str],
    targets_by_name: Dict[str, IRTarget],
    diagnostics: Diagnostics,
) -> List[IRTarget]:
    selected = []
    for name in target_names:
        target = targets_by_name.get(name)
        if target is None:
            diagnostics.error("AMF117", f"unknown target {name}", "target")
            continue
        selected.append(target)
    return selected


def _targets_for_request(request: str, targets: List[IRTarget], diagnostics: Diagnostics) -> List[IRTarget]:
    matches = [
        (target.priority, target.name, target)
        for target in targets
        if _target_matches_request(target, request)
    ]
    if not matches:
        diagnostics.error("AMF118", "no target matched request", "request")
        return []
    matches.sort(key=lambda item: (-item[0], item[1]))
    return [matches[0][2]]


def _target_matches_request(target: IRTarget, request: str) -> bool:
    request_text = request.lower()
    for candidate in _match_strings(target.match.values()):
        candidate_text = candidate.lower()
        if candidate_text and candidate_text in request_text:
            return True
    return False


def _match_strings(values: Iterable[Any]) -> Iterable[str]:
    for value in values:
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            yield from _match_strings(value)
        elif isinstance(value, dict):
            yield from _match_strings(value.values())


def _target_closure(selected_targets: List[IRTarget], targets_by_name: Dict[str, IRTarget]) -> List[IRTarget]:
    closure: List[IRTarget] = []
    visited = set()

    def visit(target: IRTarget) -> None:
        if target.name in visited:
            return
        visited.add(target.name)
        for dep_name in target.deps:
            dep = targets_by_name.get(dep_name)
            if dep is not None:
                visit(dep)
        closure.append(target)

    for target in selected_targets:
        visit(target)
    return closure


def _fragment_file_name(target_name: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in target_name)
