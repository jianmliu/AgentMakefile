from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.plugin import create_plugin_payload


@dataclass
class HarnessBenchmarkResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_harness_benchmark_payload(
    path: Union[Path, str],
    cases: List[str],
    *,
    host: str = "generic",
    backend: str = "agents-fragments",
) -> HarnessBenchmarkResult:
    diagnostics = Diagnostics()
    if not cases:
        diagnostics.error("AMF150", "at least one benchmark case is required", "benchmark.cases")
        return HarnessBenchmarkResult(diagnostics)

    case_payloads = []
    for index, request in enumerate(cases, start=1):
        plugin_result = create_plugin_payload(
            path=path,
            host=host,
            request=request,
            backend=backend,
        )
        diagnostics.extend(plugin_result.diagnostics.items)
        if not plugin_result.ok:
            continue
        case_payloads.append(_case_payload(f"case-{index}", request, plugin_result.payload))

    payload = {
        "version": 1,
        "mode": "harness_benchmark",
        "host": host,
        "backend": backend,
        "summary": {
            "case_count": len(case_payloads),
            "total_selected_pipeline_size": sum(
                case["pipeline_metrics"]["selected_pipeline_size"]
                for case in case_payloads
            ),
            "stable_prefix_hashes": sorted(
                {case["stable_prefix_hash"] for case in case_payloads}
            ),
        },
        "cases": case_payloads,
    }
    return HarnessBenchmarkResult(diagnostics, payload)


def render_harness_benchmark_markdown(payload: Dict[str, Any]) -> str:
    lines = [
        "# AgentMakefile Harness Benchmark",
        "",
        f"- Cases: {payload.get('summary', {}).get('case_count', 0)}",
        f"- Backend: {payload.get('backend', '')}",
        "",
        "| Case | Selected Targets | Pipeline Ops | Prompt Ops | Context Ops | Guard Ops | Permission Ops |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in payload.get("cases", []):
        metrics = case["pipeline_metrics"]
        lines.append(
            "| {case_id} | {targets} | {pipeline} | {prompt} | {context} | {guards} | {permissions} |".format(
                case_id=case["id"],
                targets=", ".join(case["selected_targets"]),
                pipeline=metrics["selected_pipeline_size"],
                prompt=metrics["prompt_ops"],
                context=metrics["context_ops"],
                guards=metrics["guard_ops"],
                permissions=metrics["permission_ops"],
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _case_payload(case_id: str, request: str, plugin_payload: Dict[str, Any]) -> Dict[str, Any]:
    selected_pipeline = plugin_payload["selected_pipeline"]
    comparison = plugin_payload["trace"]["comparison"]
    return {
        "id": case_id,
        "request": request,
        "selected_targets": list(plugin_payload["selected_targets"]),
        "selected_skills": list(plugin_payload["selected_skills"]),
        "pipeline_metrics": {
            "selected_pipeline_size": len(selected_pipeline.get("operations", [])),
            "prompt_ops": len(selected_pipeline.get("stable_prompt_ops", [])),
            "context_ops": len(selected_pipeline.get("volatile_context_ops", [])),
            "guard_ops": len(selected_pipeline.get("guard_ops", [])),
            "permission_ops": len(selected_pipeline.get("permission_ops", [])),
            "fallback_ops": len(selected_pipeline.get("fallback_ops", [])),
        },
        "stable_prefix_hash": plugin_payload["stable_prefix"]["hash"],
        "all_in_one_baseline_savings": dict(comparison["savings"]),
        "guard_permission_coverage": {
            "guard_ops": len(selected_pipeline.get("guard_ops", [])),
            "permission_ops": len(selected_pipeline.get("permission_ops", [])),
        },
        "selection_trace_quality": _selection_trace_quality(plugin_payload.get("selection_trace", {})),
    }


def _selection_trace_quality(selection_trace: Dict[str, Any]) -> Dict[str, Any]:
    selected = selection_trace.get("selected") or {}
    return {
        "has_selected_target": bool(selected.get("target")),
        "candidate_count": len(selection_trace.get("candidates", [])),
        "has_match_details": bool(selected.get("match_details")),
    }
