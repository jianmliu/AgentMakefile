from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from agentmf.compiler import compile_agentmakefile
from agentmf.diagnostics import Diagnostics
from agentmf.plugin import create_plugin_payload

COMPILED_BASELINES = {"agents-md", "claude-md", "skills-index"}
BASELINES = COMPILED_BASELINES | {"baseline-file", "all-skills", "none"}


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
    baseline: str = "agents-md",
    baseline_file: Optional[Union[Path, str]] = None,
    baseline_skills_dirs: Optional[Sequence[Union[Path, str]]] = None,
) -> HarnessBenchmarkResult:
    diagnostics = Diagnostics()
    if not cases:
        diagnostics.error("AMF150", "at least one benchmark case is required", "benchmark.cases")
        return HarnessBenchmarkResult(diagnostics)
    if baseline not in BASELINES:
        diagnostics.error(
            "AMF151",
            f"unsupported benchmark baseline: {baseline}",
            "benchmark.baseline",
            f"choose one of: {', '.join(sorted(BASELINES))}",
        )
        return HarnessBenchmarkResult(diagnostics)

    baseline_record = _baseline_record(
        path=Path(path),
        baseline=baseline,
        diagnostics=diagnostics,
        baseline_file=Path(baseline_file) if baseline_file is not None else None,
        baseline_skills_dirs=[Path(item) for item in baseline_skills_dirs or []],
    )
    if diagnostics.has_errors:
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
        case_payloads.append(_case_payload(f"case-{index}", request, plugin_result.payload, baseline_record))

    payload = {
        "version": 1,
        "mode": "harness_benchmark",
        "host": host,
        "backend": backend,
        "baseline": baseline,
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
        f"- Baseline: {payload.get('baseline', '')}",
        "",
        "| Case | Selected Targets | Baseline | Savings Tokens | Pipeline Ops | Prompt Ops | Context Ops | Guard Ops | Permission Ops |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in payload.get("cases", []):
        metrics = case["pipeline_metrics"]
        baseline = case["baseline"]
        savings = case["baseline_savings"]
        lines.append(
            "| {case_id} | {targets} | {baseline} | {savings} | {pipeline} | {prompt} | {context} | {guards} | {permissions} |".format(
                case_id=case["id"],
                targets=", ".join(case["selected_targets"]),
                baseline=baseline["kind"],
                savings=savings["approx_tokens"],
                pipeline=metrics["selected_pipeline_size"],
                prompt=metrics["prompt_ops"],
                context=metrics["context_ops"],
                guards=metrics["guard_ops"],
                permissions=metrics["permission_ops"],
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _case_payload(
    case_id: str,
    request: str,
    plugin_payload: Dict[str, Any],
    baseline_record: Dict[str, Any],
) -> Dict[str, Any]:
    selected_pipeline = plugin_payload["selected_pipeline"]
    comparison = plugin_payload["trace"]["comparison"]
    stable_prefix = plugin_payload["stable_prefix"]
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
        "baseline": dict(baseline_record),
        "baseline_savings": _savings(baseline_record, stable_prefix),
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


def _baseline_record(
    *,
    path: Path,
    baseline: str,
    diagnostics: Diagnostics,
    baseline_file: Optional[Path],
    baseline_skills_dirs: List[Path],
) -> Dict[str, Any]:
    if baseline in COMPILED_BASELINES:
        compile_result = compile_agentmakefile(path, targets=[baseline])
        diagnostics.extend(compile_result.diagnostics.items)
        if diagnostics.has_errors:
            return {}
        file = next((file for file in compile_result.files if file.backend == baseline), None)
        if file is None:
            diagnostics.error(
                "AMF152",
                f"compiled baseline artifact was not emitted: {baseline}",
                "benchmark.baseline",
            )
            return {}
        return _content_record(kind=baseline, path=file.path, sources=[file.path], content=file.content)
    if baseline == "baseline-file":
        if baseline_file is None:
            diagnostics.error(
                "AMF153",
                "--baseline baseline-file requires --baseline-file",
                "benchmark.baseline_file",
            )
            return {}
        return _read_file_baseline(baseline_file, diagnostics)
    if baseline == "all-skills":
        if not baseline_skills_dirs:
            diagnostics.error(
                "AMF154",
                "--baseline all-skills requires at least one --baseline-skills-dir",
                "benchmark.baseline_skills_dir",
            )
            return {}
        return _read_all_skills_baseline(baseline_skills_dirs, diagnostics)
    return {
        "kind": "none",
        "path": "<none>",
        "sources": [],
        "chars": 0,
        "approx_tokens": 0,
        "hash": None,
    }


def _read_file_baseline(path: Path, diagnostics: Diagnostics) -> Dict[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error(
            "AMF155",
            f"could not read baseline file: {path}",
            "benchmark.baseline_file",
            str(exc),
        )
        return {}
    return _content_record(kind="baseline-file", path=str(path), sources=[str(path)], content=content)


def _read_all_skills_baseline(skill_dirs: List[Path], diagnostics: Diagnostics) -> Dict[str, Any]:
    skill_files = []
    for skill_dir in skill_dirs:
        skill_files.extend(sorted(skill_dir.glob("*/SKILL.md")))
    if not skill_files:
        paths = ", ".join(str(path) for path in skill_dirs)
        diagnostics.error(
            "AMF156",
            f"no SKILL.md files found under baseline skill dirs: {paths}",
            "benchmark.baseline_skills_dir",
        )
        return {}
    contents = []
    sources = []
    for path in sorted(skill_files):
        sources.append(str(path))
        try:
            contents.append(path.read_text(encoding="utf-8").rstrip())
        except OSError as exc:
            diagnostics.error(
                "AMF157",
                f"could not read baseline skill file: {path}",
                "benchmark.baseline_skills_dir",
                str(exc),
            )
            return {}
    content = "\n\n".join(contents)
    if content:
        content += "\n"
    return _content_record(kind="all-skills", path="<all-skills>", sources=sources, content=content)


def _content_record(kind: str, path: str, sources: List[str], content: str) -> Dict[str, Any]:
    return {
        "kind": kind,
        "path": path,
        "sources": sources,
        "chars": len(content),
        "approx_tokens": (len(content) + 3) // 4,
        "hash": f"sha256:{sha256(content.encode('utf-8')).hexdigest()}",
    }


def _savings(baseline_record: Dict[str, Any], stable_prefix: Dict[str, Any]) -> Dict[str, int]:
    return {
        "chars": baseline_record["chars"] - stable_prefix["chars"],
        "approx_tokens": baseline_record["approx_tokens"] - stable_prefix["approx_tokens"],
    }
