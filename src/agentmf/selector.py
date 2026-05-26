from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.ir import normalize
from agentmf.loader import load_source_with_diagnostics
from agentmf.matcher import RequestProfile, build_request_profile, match_term
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
    selection_trace: Dict[str, Any]
    if requested_targets:
        selected_targets = _explicit_targets(requested_targets, targets_by_name, diagnostics)
        selection_mode = "explicit_target"
        selection_trace = _explicit_selection_trace(selected_targets, requested_targets)
    elif request:
        selected_targets, selection_trace = _targets_for_request(request, ir.targets, diagnostics)
        selection_mode = "request"
    else:
        diagnostics.error("AMF116", "select requires a request or at least one explicit target", "select")
        return LinkPlanResult(diagnostics)

    if diagnostics.has_errors:
        return LinkPlanResult(diagnostics)

    closure = _target_closure(selected_targets, targets_by_name)
    selection_trace = _with_dependency_closure(selection_trace, selected_targets, closure)
    target_pipelines = [target.pipeline for target in closure]
    fragment_dir = FRAGMENT_BACKEND_DIRS[backend]
    plan = {
        "version": 1,
        "backend": backend,
        "selection": {
            "mode": selection_mode,
            "request": request if selection_mode == "request" else None,
            "targets": requested_targets,
        },
        "selection_trace": selection_trace,
        "selected_targets": [target.name for target in selected_targets],
        "target_closure": [target.name for target in closure],
        "target_pipelines": target_pipelines,
        "pipeline_trace": _pipeline_trace(selected_targets, closure),
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


def _targets_for_request(
    request: str,
    targets: List[IRTarget],
    diagnostics: Diagnostics,
) -> tuple[List[IRTarget], Dict[str, Any]]:
    profile = build_request_profile(request)
    matches = []
    for target in targets:
        match_details = _match_details(target, profile)
        if match_details:
            matches.append(
                (
                    _candidate_source_rank(match_details),
                    target.priority,
                    _match_score(match_details),
                    target.name,
                    target,
                    match_details,
                )
            )
    if not matches:
        diagnostics.error("AMF118", "no target matched request", "request")
        return [], {}
    matches.sort(key=lambda item: (item[0], -item[1], -item[2], item[3]))
    selected_target = matches[0][4]
    selected_name = selected_target.name
    candidates = [
        {
            "rank": index,
            "target": target.name,
            "priority": priority,
            "matched_terms": [detail["term"] for detail in match_details],
            "match_details": match_details,
            "match_score": score,
            "selected": target.name == selected_name,
            "reason": _reason(match_details),
        }
        for index, (_source_rank, priority, score, _name, target, match_details) in enumerate(matches, start=1)
    ]
    trace = {
        "mode": "request",
        "algorithm": "normalize_translate_semantic_priority_score_name",
        "request": request,
        "normalized_request": profile.normalized,
        "expanded_request_terms": profile.expanded_terms,
        "requested_targets": [],
        "selected": {
            "target": selected_target.name,
            "priority": selected_target.priority,
            "matched_terms": [detail["term"] for detail in matches[0][5]],
            "match_details": matches[0][5],
            "match_score": matches[0][2],
            "dependency_closure": [],
        },
        "candidates": candidates,
    }
    return [selected_target], trace


def _target_matches_request(target: IRTarget, request: str) -> bool:
    return bool(_match_details(target, build_request_profile(request)))


def _match_details(target: IRTarget, profile: RequestProfile) -> List[dict]:
    details = []
    seen = set()
    _append_match_details(
        details,
        seen,
        target.match.values(),
        profile,
        source=None,
    )
    for skill in target.skills:
        _append_match_details(
            details,
            seen,
            skill.match.values(),
            profile,
            source=f"skill:{skill.qualified_name}",
        )
    details.sort(key=lambda item: (-item["score"], _detail_source_rank(item), item["term"]))
    return details


def _append_match_details(
    details: List[dict],
    seen: set,
    candidates: Iterable[Any],
    profile: RequestProfile,
    *,
    source: Optional[str],
) -> None:
    for candidate in _match_strings(candidates):
        detail = match_term(profile, candidate)
        if detail is None:
            continue
        key = (detail["term"], detail["method"])
        if key in seen:
            continue
        seen.add(key)
        if source is not None:
            detail = dict(detail)
            detail["source"] = source
        details.append(detail)


def _match_score(match_details: List[dict]) -> int:
    if not match_details:
        return 0
    return max(detail["score"] for detail in match_details)


def _detail_source_rank(detail: dict) -> int:
    return 1 if "source" in detail else 0


def _candidate_source_rank(match_details: List[dict]) -> int:
    return min(_detail_source_rank(detail) for detail in match_details)


def _reason(match_details: List[dict]) -> str:
    if not match_details:
        return "no match"
    method = match_details[0]["method"]
    if method == "substring":
        return "matched request substring(s)"
    if method == "normalized_substring":
        return "matched normalized request term(s)"
    if method == "translated_substring":
        return "matched translated request term(s)"
    return "matched semantic token overlap"


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


def _explicit_selection_trace(selected_targets: List[IRTarget], requested_targets: List[str]) -> Dict[str, Any]:
    candidates = [
        {
            "rank": index,
            "target": target.name,
            "priority": target.priority,
            "matched_terms": [],
            "selected": True,
            "reason": "explicit target",
        }
        for index, target in enumerate(selected_targets, start=1)
    ]
    return {
        "mode": "explicit_target",
        "algorithm": "explicit_target_order",
        "request": None,
        "requested_targets": requested_targets,
        "selected": {
            "target": selected_targets[0].name if selected_targets else None,
            "targets": [target.name for target in selected_targets],
            "dependency_closure": [],
        },
        "candidates": candidates,
    }


def _with_dependency_closure(
    selection_trace: Dict[str, Any],
    selected_targets: List[IRTarget],
    closure: List[IRTarget],
) -> Dict[str, Any]:
    if not selection_trace:
        return selection_trace
    trace = dict(selection_trace)
    selected = dict(trace.get("selected") or {})
    selected["dependency_closure"] = [target.name for target in closure]
    if selected_targets and "target" not in selected:
        selected["target"] = selected_targets[0].name
    trace["selected"] = selected
    return trace


def _pipeline_trace(selected_targets: List[IRTarget], closure: List[IRTarget]) -> Dict[str, Any]:
    return {
        "selected_target": selected_targets[0].name if selected_targets else None,
        "target_closure": [target.name for target in closure],
        "operation_counts": _aggregate_operation_counts(target.pipeline for target in closure),
        "targets": [
            {
                "target": target.name,
                "operation_counts": _operation_counts(target.pipeline),
            }
            for target in closure
        ],
    }


def _aggregate_operation_counts(pipelines: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts = _empty_operation_counts()
    for pipeline in pipelines:
        target_counts = _operation_counts(pipeline)
        for key, value in target_counts.items():
            counts[key] += value
    return counts


def _operation_counts(pipeline: Dict[str, Any]) -> Dict[str, int]:
    return {
        "operations": len(pipeline.get("operations", [])),
        "context_ops": len(pipeline.get("context_ops", [])),
        "prompt_ops": len(pipeline.get("prompt_ops", [])),
        "action_ops": len(pipeline.get("action_ops", [])),
        "guard_ops": len(pipeline.get("guard_ops", [])),
        "permission_ops": len(pipeline.get("permission_ops", [])),
        "fallback_ops": len(pipeline.get("fallback_ops", [])),
    }


def _empty_operation_counts() -> Dict[str, int]:
    return {
        "operations": 0,
        "context_ops": 0,
        "prompt_ops": 0,
        "action_ops": 0,
        "guard_ops": 0,
        "permission_ops": 0,
        "fallback_ops": 0,
    }


def _fragment_file_name(target_name: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in target_name)
