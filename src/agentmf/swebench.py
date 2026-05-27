from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import shlex
from typing import Any, Dict, List, Optional, Sequence, Union

from agentmf.compiler import compile_agentmakefile
from agentmf.diagnostics import Diagnostics
from agentmf.plugin import create_plugin_payload

COMPILED_BASELINES = {"agents-md", "claude-md", "skills-index"}
BASELINES = COMPILED_BASELINES | {"baseline-file", "none"}
SWE_BENCH_PROFILES = {
    "lite": {
        "id": "lite",
        "benchmark": "swebench-lite",
        "dataset_name": "princeton-nlp/SWE-bench_Lite",
        "split": "test",
        "official_instance_count": 300,
        "description": "Official SWE-bench Lite evaluation profile.",
    },
    "verified": {
        "id": "verified",
        "benchmark": "swebench-verified",
        "dataset_name": "princeton-nlp/SWE-bench_Verified",
        "split": "test",
        "official_instance_count": 500,
        "description": "Official SWE-bench Verified evaluation profile.",
    },
}


@dataclass
class SWEBenchHarnessExportResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_swebench_harness_export(
    path: Union[Path, str],
    *,
    task: Dict[str, Any],
    host: str = "generic",
    model: Optional[str] = None,
    backend: str = "agents-fragments",
    include_git_status: bool = False,
    include_git_diff: bool = False,
    context_files: Optional[List[Union[Path, str]]] = None,
) -> SWEBenchHarnessExportResult:
    diagnostics = Diagnostics()
    normalized_task = _normalize_task(task, line_number=None, diagnostics=diagnostics)
    if diagnostics.has_errors or normalized_task is None:
        return SWEBenchHarnessExportResult(diagnostics)

    plugin_result = create_plugin_payload(
        path=path,
        host=host,
        request=_routing_request(normalized_task),
        backend=backend,
        include_git_status=include_git_status,
        include_git_diff=include_git_diff,
        context_files=context_files,
    )
    diagnostics.extend(plugin_result.diagnostics.items)
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)

    return SWEBenchHarnessExportResult(
        diagnostics,
        _export_payload(
            task=normalized_task,
            host=host,
            model=model,
            plugin_payload=plugin_result.payload,
        ),
    )


def create_swebench_jsonl_export(
    path: Union[Path, str],
    *,
    tasks_file: Union[Path, str],
    host: str = "generic",
    model: Optional[str] = None,
    backend: str = "agents-fragments",
    limit: Optional[int] = None,
    include_git_status: bool = False,
    include_git_diff: bool = False,
    context_files: Optional[List[Union[Path, str]]] = None,
) -> SWEBenchHarnessExportResult:
    diagnostics = Diagnostics()
    tasks = _read_tasks_file(Path(tasks_file), diagnostics)
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)
    if limit is not None:
        if limit < 1:
            diagnostics.error("AMF205", "SWE-bench export limit must be at least 1", "swebench.limit")
            return SWEBenchHarnessExportResult(diagnostics)
        tasks = tasks[:limit]

    records = []
    for task in tasks:
        export_result = create_swebench_harness_export(
            path=path,
            task=task,
            host=host,
            model=model,
            backend=backend,
            include_git_status=include_git_status,
            include_git_diff=include_git_diff,
            context_files=context_files,
        )
        diagnostics.extend(export_result.diagnostics.items)
        if export_result.ok:
            records.append(export_result.payload)
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)

    jsonl = "\n".join(_json_line(record) for record in records)
    if jsonl:
        jsonl += "\n"
    return SWEBenchHarnessExportResult(
        diagnostics,
        {
            "version": 1,
            "mode": "swebench_harness_export_jsonl",
            "benchmark": "swebench-lite",
            "task_count": len(records),
            "records": records,
            "jsonl": jsonl,
        },
    )


def create_swebench_comparison_report(
    path: Union[Path, str],
    *,
    tasks_file: Union[Path, str],
    host: str = "generic",
    model: Optional[str] = None,
    backend: str = "agents-fragments",
    limit: Optional[int] = None,
    baselines: Optional[Sequence[str]] = None,
    baseline_file: Optional[Union[Path, str]] = None,
) -> SWEBenchHarnessExportResult:
    diagnostics = Diagnostics()
    baseline_names = list(baselines or ["agents-md"])
    for baseline in baseline_names:
        if baseline not in BASELINES:
            diagnostics.error(
                "AMF206",
                f"unsupported SWE-bench comparison baseline: {baseline}",
                "swebench.baseline",
                f"choose one of: {', '.join(sorted(BASELINES))}",
            )
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)

    export_result = create_swebench_jsonl_export(
        path=path,
        tasks_file=tasks_file,
        host=host,
        model=model,
        backend=backend,
        limit=limit,
    )
    diagnostics.extend(export_result.diagnostics.items)
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)

    baseline_records = [
        _baseline_record(
            path=Path(path),
            baseline=baseline,
            diagnostics=diagnostics,
            baseline_file=Path(baseline_file) if baseline_file is not None else None,
        )
        for baseline in baseline_names
    ]
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)

    records = export_result.payload["records"]
    case_payloads = [_comparison_case(record) for record in records]
    stable_prefix_hashes = sorted({case["stable_prefix_hash"] for case in case_payloads})
    baseline_comparison = [
        _baseline_comparison(record, case_payloads)
        for record in baseline_records
    ]
    selected_targets = sorted(
        {
            target
            for case in case_payloads
            for target in case["selected_targets"]
        }
    )
    payload = {
        "version": 1,
        "mode": "swebench_deterministic_comparison",
        "benchmark": "swebench-lite",
        "host": host,
        "model": model,
        "backend": backend,
        "tasks_file": str(tasks_file),
        "summary": {
            "task_count": len(case_payloads),
            "selected_targets": selected_targets,
            "stable_prefix_hashes": stable_prefix_hashes,
            "stable_prefix_hash_reuse": _hash_reuse(case_payloads),
            "average_stable_prefix_approx_tokens": _average_int(case_payloads, "stable_prefix_approx_tokens"),
        },
        "baseline_comparison": baseline_comparison,
        "cases": case_payloads,
    }
    return SWEBenchHarnessExportResult(diagnostics, payload)


def create_swebench_execution_adapter_contract(*, host: str = "generic") -> SWEBenchHarnessExportResult:
    diagnostics = Diagnostics()
    return SWEBenchHarnessExportResult(
        diagnostics,
        {
            "version": 1,
            "mode": "swebench_execution_adapter_contract",
            "benchmark": "swebench-lite",
            "adapter": {
                "host": host,
                "execution": "external",
                "agentmakefile_role": "harness_selection_layer",
            },
            "input_contract": {
                "format": "jsonl",
                "record_mode": "swebench_harness_export",
                "required_fields": [
                    "task.instance_id",
                    "task.repo",
                    "task.base_commit",
                    "task.problem_statement",
                    "agentmf.selected_targets",
                    "agentmf.selected_pipeline",
                    "prompt.stable_prefix.content",
                    "trace_bundle.stable_prefix_hash",
                ],
                "optional_fields": [
                    "task.test_patch",
                    "task.FAIL_TO_PASS",
                    "task.PASS_TO_PASS",
                    "run.model",
                    "agentmf.selected_skills",
                    "agentmf.selection_trace",
                    "trace_bundle.guard_ops",
                    "trace_bundle.permission_ops",
                    "trace_bundle.output_contracts",
                ],
            },
            "output_contract": {
                "format": "jsonl",
                "record_mode": "swebench_execution_result",
                "required_fields": [
                    "instance_id",
                    "resolved",
                ],
                "optional_fields": [
                    "patch_applied",
                    "tests_passed",
                    "cost_usd",
                    "wall_time_ms",
                    "prompt_tokens",
                    "completion_tokens",
                    "tool_calls",
                    "denied_tool_calls",
                    "patch_path",
                    "trace_path",
                    "agentmf.stable_prefix_hash",
                    "verification.command",
                    "verification.exit_code",
                ],
            },
        },
    )


def create_swebench_result_summary(*, results_file: Union[Path, str]) -> SWEBenchHarnessExportResult:
    diagnostics = Diagnostics()
    raw_results = _read_results_file(Path(results_file), diagnostics)
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)

    results = []
    for line_number, item in raw_results:
        result = _normalize_execution_result(item, line_number, diagnostics)
        if result is not None:
            results.append(result)
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)
    if not results:
        diagnostics.error(
            "AMF214",
            f"SWE-bench results file contained no results: {results_file}",
            "swebench.results_file",
        )
        return SWEBenchHarnessExportResult(diagnostics)

    return SWEBenchHarnessExportResult(
        diagnostics,
        {
            "version": 1,
            "mode": "swebench_execution_results",
            "benchmark": "swebench-lite",
            "results_file": str(results_file),
            "summary": _summarize_execution_results(results),
            "results": results,
        },
    )


def create_swebench_pass_rate_report(
    *,
    results_file: Union[Path, str],
    baseline_report: Optional[Union[Path, str]] = None,
) -> SWEBenchHarnessExportResult:
    result = create_swebench_result_summary(results_file=results_file)
    if not result.ok:
        return result
    payload = {
        "version": 1,
        "mode": "swebench_pass_rate_report",
        "benchmark": "swebench-lite",
        "results_file": str(results_file),
        "baseline_report": str(baseline_report) if baseline_report is not None else None,
        "summary": dict(result.payload["summary"]),
        "results": list(result.payload["results"]),
    }
    return SWEBenchHarnessExportResult(result.diagnostics, payload)


def create_swebench_predictions_export(
    *,
    results_file: Union[Path, str],
    model_name_or_path: str,
    dataset_profile: str = "lite",
) -> SWEBenchHarnessExportResult:
    diagnostics = Diagnostics()
    profile = _profile_or_error(dataset_profile, diagnostics)
    if not isinstance(model_name_or_path, str) or not model_name_or_path:
        diagnostics.error(
            "AMF216",
            "SWE-bench official predictions require model_name_or_path",
            "swebench.model_name_or_path",
        )
    raw_results = _read_results_file(Path(results_file), diagnostics)
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)

    predictions = []
    for line_number, item in raw_results:
        prediction = _normalize_prediction(
            item,
            line_number=line_number,
            model_name_or_path=model_name_or_path,
            diagnostics=diagnostics,
        )
        if prediction is not None:
            predictions.append(prediction)
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)
    if not predictions:
        diagnostics.error(
            "AMF217",
            f"SWE-bench results file contained no predictions: {results_file}",
            "swebench.results_file",
        )
        return SWEBenchHarnessExportResult(diagnostics)

    jsonl = "\n".join(_json_line(prediction) for prediction in predictions) + "\n"
    return SWEBenchHarnessExportResult(
        diagnostics,
        {
            "version": 1,
            "mode": "swebench_official_predictions_export",
            "benchmark": profile["benchmark"],
            "profile": dict(profile),
            "results_file": str(results_file),
            "prediction_count": len(predictions),
            "predictions": predictions,
            "jsonl": jsonl,
        },
    )


def create_swebench_official_run_command(
    *,
    dataset_profile: str = "lite",
    predictions_path: Union[Path, str],
    run_id: str,
    max_workers: int = 4,
    split: Optional[str] = None,
    instance_ids: Optional[Sequence[str]] = None,
) -> SWEBenchHarnessExportResult:
    diagnostics = Diagnostics()
    profile = _profile_or_error(dataset_profile, diagnostics)
    if not isinstance(run_id, str) or not run_id:
        diagnostics.error("AMF221", "SWE-bench official run command requires run_id", "swebench.run_id")
    if max_workers < 1:
        diagnostics.error("AMF222", "SWE-bench official max_workers must be at least 1", "swebench.max_workers")
    predictions_path_str = str(predictions_path)
    if not predictions_path_str:
        diagnostics.error(
            "AMF223",
            "SWE-bench official run command requires predictions_path",
            "swebench.predictions_path",
        )
    selected_split = split or str(profile["split"])
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)

    command = [
        "python",
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        str(profile["dataset_name"]),
        "--split",
        selected_split,
        "--predictions_path",
        predictions_path_str,
        "--max_workers",
        str(max_workers),
        "--run_id",
        run_id,
    ]
    normalized_instance_ids = [item for item in (instance_ids or []) if item]
    if normalized_instance_ids:
        command.append("--instance_ids")
        command.extend(normalized_instance_ids)
    return SWEBenchHarnessExportResult(
        diagnostics,
        {
            "version": 1,
            "mode": "swebench_official_run_command",
            "benchmark": profile["benchmark"],
            "profile": dict(profile),
            "predictions_path": predictions_path_str,
            "run_id": run_id,
            "split": selected_split,
            "max_workers": max_workers,
            "instance_ids": normalized_instance_ids,
            "command": command,
            "command_text": shlex.join(command),
            "execution": False,
        },
    )


def create_swebench_official_adapter_plan(
    *,
    dataset_profile: str = "lite",
    predictions_path: Union[Path, str],
    run_id: str,
    max_workers: int = 4,
    smoke_limit: int = 5,
    split: Optional[str] = None,
) -> SWEBenchHarnessExportResult:
    diagnostics = Diagnostics()
    profile = _profile_or_error(dataset_profile, diagnostics)
    predictions = _read_official_predictions_file(Path(predictions_path), diagnostics)
    if smoke_limit < 1:
        diagnostics.error("AMF232", "SWE-bench official smoke_limit must be at least 1", "swebench.smoke_limit")
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)

    instance_ids = [prediction["instance_id"] for prediction in predictions]
    smoke_instance_ids = instance_ids[:smoke_limit]
    smoke_command = create_swebench_official_run_command(
        dataset_profile=dataset_profile,
        predictions_path=predictions_path,
        run_id=f"{run_id}-smoke",
        max_workers=max_workers,
        split=split,
        instance_ids=smoke_instance_ids,
    )
    full_command = create_swebench_official_run_command(
        dataset_profile=dataset_profile,
        predictions_path=predictions_path,
        run_id=run_id,
        max_workers=max_workers,
        split=split,
    )
    diagnostics.extend(smoke_command.diagnostics.items)
    diagnostics.extend(full_command.diagnostics.items)
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)

    return SWEBenchHarnessExportResult(
        diagnostics,
        {
            "version": 1,
            "mode": "swebench_official_adapter_dry_run",
            "benchmark": profile["benchmark"],
            "profile": dict(profile),
            "adapter": {
                "name": "official-swebench-run-evaluation",
                "execution": "external_manual",
                "agentmakefile_role": "dry_run_planning_and_payload_validation",
            },
            "execution": False,
            "predictions_path": str(predictions_path),
            "prediction_summary": {
                "prediction_count": len(predictions),
                "model_names": sorted({prediction["model_name_or_path"] for prediction in predictions}),
                "first_instance_ids": instance_ids[: min(10, len(instance_ids))],
            },
            "smoke_subset": {
                "limit": smoke_limit,
                "instance_ids": smoke_instance_ids,
            },
            "commands": {
                "smoke": _command_payload(smoke_command.payload),
                "full": _command_payload(full_command.payload),
            },
            "safety": {
                "full_profile_execution_requires_external_confirmation": True,
                "official_instance_count": profile["official_instance_count"],
                "submitted_prediction_count": len(predictions),
                "recommended_first_step": "run_smoke_command_before_full_profile",
            },
        },
    )


def create_swebench_official_report_summary(
    *,
    report_file: Union[Path, str],
) -> SWEBenchHarnessExportResult:
    diagnostics = Diagnostics()
    report_path = Path(report_file)
    try:
        content = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error(
            "AMF224",
            f"could not read SWE-bench official report file: {report_path}",
            "swebench.report_file",
            str(exc),
        )
        return SWEBenchHarnessExportResult(diagnostics)
    try:
        report = json.loads(content)
    except json.JSONDecodeError as exc:
        diagnostics.error(
            "AMF225",
            f"invalid SWE-bench official report JSON: {exc.msg}",
            "swebench.report_file",
        )
        return SWEBenchHarnessExportResult(diagnostics)
    if not isinstance(report, dict):
        diagnostics.error(
            "AMF226",
            "SWE-bench official report must be a JSON object",
            "swebench.report_file",
        )
        return SWEBenchHarnessExportResult(diagnostics)

    summary = _summarize_official_report(report, diagnostics)
    if diagnostics.has_errors:
        return SWEBenchHarnessExportResult(diagnostics)
    return SWEBenchHarnessExportResult(
        diagnostics,
        {
            "version": 1,
            "mode": "swebench_official_report",
            "report_file": str(report_file),
            "summary": summary,
            "completed_ids": _string_list(report.get("completed_ids")),
            "submitted_ids": _string_list(report.get("submitted_ids")),
            "resolved_ids": _string_list(report.get("resolved_ids")),
            "unresolved_ids": _string_list(report.get("unresolved_ids")),
            "empty_patch_ids": _string_list(report.get("empty_patch_ids")),
            "error_ids": _string_list(report.get("error_ids")),
        },
    )


def render_swebench_comparison_markdown(payload: Dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    lines = [
        "# AgentMakefile SWE-bench Deterministic Comparison",
        "",
        f"- Tasks: {summary.get('task_count', 0)}",
        f"- Backend: {payload.get('backend', '')}",
        f"- Selected targets: {', '.join(summary.get('selected_targets', []))}",
        f"- Stable prefix hashes: {len(summary.get('stable_prefix_hashes', []))}",
        "",
        "## Baselines",
        "",
        "| Baseline | Approx Tokens | Avg Savings Tokens | Sources |",
        "| --- | ---: | ---: | --- |",
    ]
    for baseline in payload.get("baseline_comparison", []):
        lines.append(
            "| {kind} | {tokens} | {savings} | {sources} |".format(
                kind=baseline["kind"],
                tokens=baseline["approx_tokens"],
                savings=baseline["average_savings_approx_tokens"],
                sources=", ".join(baseline["sources"]) or "-",
            )
        )
    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Instance | Selected Targets | Stable Prefix Tokens | Stable Prefix Hash |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for case in payload.get("cases", []):
        lines.append(
            "| {instance} | {targets} | {tokens} | {hash} |".format(
                instance=case["instance_id"],
                targets=", ".join(case["selected_targets"]),
                tokens=case["stable_prefix_approx_tokens"],
                hash=case["stable_prefix_hash"],
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def render_swebench_pass_rate_markdown(payload: Dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    lines = [
        "# AgentMakefile SWE-bench Pass-Rate Report",
        "",
        f"- Results: {summary.get('result_count', 0)}",
        f"- Resolved rate: {summary.get('resolved_rate', 0.0)}",
        f"- Tests passed rate: {summary.get('tests_passed_rate', 0.0)}",
        f"- Patch applied rate: {summary.get('patch_applied_rate', 0.0)}",
        f"- Cost per resolved: {summary.get('cost_per_resolved', 0.0)}",
    ]
    baseline_report = payload.get("baseline_report")
    if baseline_report:
        lines.append(f"- Baseline report: {baseline_report}")
    lines.extend(
        [
            "",
            "| Instance | Resolved | Patch Applied | Tests Passed | Cost USD | Total Tokens |",
            "| --- | --- | --- | --- | ---: | ---: |",
        ]
    )
    for result in payload.get("results", []):
        lines.append(
            "| {instance} | {resolved} | {patch} | {tests} | {cost} | {tokens} |".format(
                instance=result["instance_id"],
                resolved=_yes_no(result["resolved"]),
                patch=_yes_no(result["patch_applied"]),
                tests=_yes_no(result["tests_passed"]),
                cost=result["cost_usd"],
                tokens=result["total_tokens"],
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def _profile_or_error(profile_id: str, diagnostics: Diagnostics) -> Dict[str, Any]:
    profile = SWE_BENCH_PROFILES.get(profile_id)
    if profile is None:
        diagnostics.error(
            "AMF220",
            f"unsupported SWE-bench profile: {profile_id}",
            "swebench.dataset_profile",
            f"choose one of: {', '.join(sorted(SWE_BENCH_PROFILES))}",
        )
        return {}
    return profile


def _read_tasks_file(path: Path, diagnostics: Diagnostics) -> List[Dict[str, Any]]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error(
            "AMF200",
            f"could not read SWE-bench tasks file: {path}",
            "swebench.tasks_file",
            str(exc),
        )
        return []

    tasks = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            diagnostics.error(
                "AMF201",
                f"invalid JSONL SWE-bench task at line {line_number}: {exc.msg}",
                f"swebench.tasks_file:{line_number}",
            )
            continue
        if not isinstance(item, dict):
            diagnostics.error(
                "AMF202",
                f"SWE-bench task line {line_number} must be a JSON object",
                f"swebench.tasks_file:{line_number}",
            )
            continue
        normalized = _normalize_task(item, line_number=line_number, diagnostics=diagnostics)
        if normalized is not None:
            tasks.append(normalized)
    if not tasks and not diagnostics.has_errors:
        diagnostics.error(
            "AMF204",
            f"SWE-bench tasks file contained no tasks: {path}",
            "swebench.tasks_file",
        )
    return tasks


def _normalize_task(
    item: Dict[str, Any],
    *,
    line_number: Optional[int],
    diagnostics: Diagnostics,
) -> Optional[Dict[str, Any]]:
    location = "swebench.task" if line_number is None else f"swebench.tasks_file:{line_number}"
    normalized: Dict[str, Any] = {}
    for field_name in ("instance_id", "repo", "base_commit", "problem_statement"):
        value = item.get(field_name)
        if not isinstance(value, str) or not value:
            diagnostics.error(
                "AMF203",
                f"SWE-bench task requires string {field_name}",
                location,
            )
            return None
        normalized[field_name] = value

    for field_name in (
        "patch",
        "test_patch",
        "hints_text",
        "version",
        "created_at",
        "FAIL_TO_PASS",
        "PASS_TO_PASS",
        "fail_to_pass",
        "pass_to_pass",
    ):
        if field_name in item:
            normalized[field_name] = item[field_name]
    return normalized


def _json_line(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _routing_request(task: Dict[str, Any]) -> str:
    return (
        "implement code fix for SWE-bench issue "
        f"{task['instance_id']} in {task['repo']}: {task['problem_statement']}"
    )


def _export_payload(
    *,
    task: Dict[str, Any],
    host: str,
    model: Optional[str],
    plugin_payload: Dict[str, Any],
) -> Dict[str, Any]:
    selected_pipeline = plugin_payload["selected_pipeline"]
    stable_prefix = plugin_payload["stable_prefix"]
    return {
        "version": 1,
        "mode": "swebench_harness_export",
        "benchmark": "swebench-lite",
        "task": dict(task),
        "run": {
            "host": host,
            "model": model,
            "execution": False,
            "harness": "agentmf-plugin-payload",
        },
        "harness": {
            "name": "AgentMakefile",
            "role": "harness_selection_layer",
            "injection": plugin_payload["host_instructions"]["injection"],
            "preferred_cache_boundary": plugin_payload["host_instructions"]["preferred_cache_boundary"],
            "permissions_mode": plugin_payload["host_instructions"]["permissions_mode"],
        },
        "prompt": {
            "stable_prefix": dict(stable_prefix),
            "volatile_context": dict(plugin_payload["volatile_context"]),
        },
        "agentmf": {
            "selected_targets": list(plugin_payload["selected_targets"]),
            "selected_skills": list(plugin_payload["selected_skills"]),
            "selected_pipeline": selected_pipeline,
            "skill_artifacts": dict(plugin_payload["skill_artifacts"]),
            "selection_trace": plugin_payload.get("selection_trace", {}),
            "stable_prefix_hash": stable_prefix["hash"],
        },
        "trace_bundle": {
            "target_closure": list(plugin_payload["trace"]["target_closure"]),
            "linked_fragments": list(plugin_payload["trace"]["linked_fragments"]),
            "stable_prefix_hash": stable_prefix["hash"],
            "stable_prefix_chars": stable_prefix["chars"],
            "stable_prefix_approx_tokens": stable_prefix["approx_tokens"],
            "selection_trace": plugin_payload.get("selection_trace", {}),
            "pipeline_operations": list(selected_pipeline.get("operations", [])),
            "guard_ops": list(selected_pipeline.get("guard_ops", [])),
            "permission_ops": list(selected_pipeline.get("permission_ops", [])),
            "fallback_ops": list(selected_pipeline.get("fallback_ops", [])),
            "output_contracts": list(selected_pipeline.get("output_contracts", [])),
            "diagnostics": list(plugin_payload.get("diagnostics", [])),
        },
        "downstream_execution": {
            "status": "not_executed",
            "reason": "export_only_harness_layer",
        },
    }


def _comparison_case(record: Dict[str, Any]) -> Dict[str, Any]:
    task = record["task"]
    trace_bundle = record["trace_bundle"]
    selected_pipeline = record["agentmf"]["selected_pipeline"]
    return {
        "instance_id": task["instance_id"],
        "repo": task["repo"],
        "base_commit": task["base_commit"],
        "problem_statement_chars": len(task["problem_statement"]),
        "problem_statement_approx_tokens": (len(task["problem_statement"]) + 3) // 4,
        "selected_targets": list(record["agentmf"]["selected_targets"]),
        "selected_skills": list(record["agentmf"]["selected_skills"]),
        "stable_prefix_hash": trace_bundle["stable_prefix_hash"],
        "stable_prefix_chars": trace_bundle["stable_prefix_chars"],
        "stable_prefix_approx_tokens": trace_bundle["stable_prefix_approx_tokens"],
        "pipeline_metrics": {
            "selected_pipeline_size": len(selected_pipeline.get("operations", [])),
            "prompt_ops": len(selected_pipeline.get("stable_prompt_ops", [])),
            "context_ops": len(selected_pipeline.get("volatile_context_ops", [])),
            "guard_ops": len(selected_pipeline.get("guard_ops", [])),
            "permission_ops": len(selected_pipeline.get("permission_ops", [])),
            "fallback_ops": len(selected_pipeline.get("fallback_ops", [])),
        },
    }


def _baseline_record(
    *,
    path: Path,
    baseline: str,
    diagnostics: Diagnostics,
    baseline_file: Optional[Path],
) -> Dict[str, Any]:
    if baseline in COMPILED_BASELINES:
        compile_result = compile_agentmakefile(path, targets=[baseline])
        diagnostics.extend(compile_result.diagnostics.items)
        if diagnostics.has_errors:
            return {}
        file = next((file for file in compile_result.files if file.backend == baseline), None)
        if file is None:
            diagnostics.error(
                "AMF207",
                f"compiled SWE-bench comparison baseline artifact was not emitted: {baseline}",
                "swebench.baseline",
            )
            return {}
        return _content_record(kind=baseline, path=file.path, sources=[file.path], content=file.content)
    if baseline == "baseline-file":
        if baseline_file is None:
            diagnostics.error(
                "AMF208",
                "--baseline baseline-file requires --baseline-file",
                "swebench.baseline_file",
            )
            return {}
        try:
            content = baseline_file.read_text(encoding="utf-8")
        except OSError as exc:
            diagnostics.error(
                "AMF209",
                f"could not read SWE-bench comparison baseline file: {baseline_file}",
                "swebench.baseline_file",
                str(exc),
            )
            return {}
        return _content_record(kind="baseline-file", path=str(baseline_file), sources=[str(baseline_file)], content=content)
    return {
        "kind": "none",
        "path": "<none>",
        "sources": [],
        "chars": 0,
        "approx_tokens": 0,
        "hash": None,
    }


def _content_record(kind: str, path: str, sources: List[str], content: str) -> Dict[str, Any]:
    return {
        "kind": kind,
        "path": path,
        "sources": sources,
        "chars": len(content),
        "approx_tokens": (len(content) + 3) // 4,
        "hash": f"sha256:{sha256(content.encode('utf-8')).hexdigest()}",
    }


def _baseline_comparison(baseline: Dict[str, Any], cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    average_stable_tokens = _average_int(cases, "stable_prefix_approx_tokens")
    return {
        "kind": baseline["kind"],
        "path": baseline["path"],
        "sources": list(baseline["sources"]),
        "chars": baseline["chars"],
        "approx_tokens": baseline["approx_tokens"],
        "hash": baseline["hash"],
        "average_savings_approx_tokens": baseline["approx_tokens"] - average_stable_tokens,
    }


def _hash_reuse(cases: List[Dict[str, Any]]) -> Dict[str, int]:
    reuse: Dict[str, int] = {}
    for case in cases:
        stable_hash = case["stable_prefix_hash"]
        reuse[stable_hash] = reuse.get(stable_hash, 0) + 1
    return dict(sorted(reuse.items()))


def _average_int(cases: List[Dict[str, Any]], key: str) -> int:
    if not cases:
        return 0
    return round(sum(int(case[key]) for case in cases) / len(cases))


def _read_results_file(path: Path, diagnostics: Diagnostics) -> List[tuple[int, Dict[str, Any]]]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error(
            "AMF210",
            f"could not read SWE-bench results file: {path}",
            "swebench.results_file",
            str(exc),
        )
        return []

    results = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            diagnostics.error(
                "AMF211",
                f"invalid JSONL SWE-bench result at line {line_number}: {exc.msg}",
                f"swebench.results_file:{line_number}",
            )
            continue
        if not isinstance(item, dict):
            diagnostics.error(
                "AMF212",
                f"SWE-bench result line {line_number} must be a JSON object",
                f"swebench.results_file:{line_number}",
            )
            continue
        results.append((line_number, item))
    return results


def _normalize_prediction(
    item: Dict[str, Any],
    *,
    line_number: int,
    model_name_or_path: str,
    diagnostics: Diagnostics,
) -> Optional[Dict[str, str]]:
    instance_id = _instance_id_from_record(item)
    if instance_id is None:
        diagnostics.error(
            "AMF218",
            f"SWE-bench prediction line {line_number} requires instance_id or task.instance_id",
            f"swebench.results_file:{line_number}",
        )
        return None
    model_patch = _model_patch_from_record(item, line_number, diagnostics)
    if model_patch is None:
        diagnostics.error(
            "AMF219",
            f"SWE-bench prediction line {line_number} requires model_patch, patch, or patch_path",
            f"swebench.results_file:{line_number}",
        )
        return None
    return {
        "instance_id": instance_id,
        "model_name_or_path": model_name_or_path,
        "model_patch": model_patch,
    }


def _read_official_predictions_file(path: Path, diagnostics: Diagnostics) -> List[Dict[str, str]]:
    raw_predictions = _read_results_file(path, diagnostics)
    if diagnostics.has_errors:
        return []
    predictions = []
    for line_number, item in raw_predictions:
        prediction = _normalize_official_prediction(item, line_number, diagnostics)
        if prediction is not None:
            predictions.append(prediction)
    if not predictions and not diagnostics.has_errors:
        diagnostics.error(
            "AMF229",
            f"SWE-bench official predictions file contained no predictions: {path}",
            "swebench.predictions_path",
        )
    return predictions


def _normalize_official_prediction(
    item: Dict[str, Any],
    line_number: int,
    diagnostics: Diagnostics,
) -> Optional[Dict[str, str]]:
    instance_id = item.get("instance_id")
    model_name_or_path = item.get("model_name_or_path")
    model_patch = item.get("model_patch")
    location = f"swebench.predictions_path:{line_number}"
    if not isinstance(instance_id, str) or not instance_id:
        diagnostics.error("AMF230", f"SWE-bench official prediction line {line_number} requires instance_id", location)
        return None
    if not isinstance(model_name_or_path, str) or not model_name_or_path:
        diagnostics.error(
            "AMF230",
            f"SWE-bench official prediction line {line_number} requires model_name_or_path",
            location,
        )
        return None
    if not isinstance(model_patch, str):
        diagnostics.error(
            "AMF230",
            f"SWE-bench official prediction line {line_number} requires model_patch",
            location,
        )
        return None
    return {
        "instance_id": instance_id,
        "model_name_or_path": model_name_or_path,
        "model_patch": model_patch,
    }


def _command_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "execution": False,
        "command": list(payload["command"]),
        "command_text": payload["command_text"],
        "run_id": payload["run_id"],
    }


def _instance_id_from_record(item: Dict[str, Any]) -> Optional[str]:
    instance_id = item.get("instance_id")
    if isinstance(instance_id, str) and instance_id:
        return instance_id
    task = item.get("task")
    if isinstance(task, dict):
        instance_id = task.get("instance_id")
        if isinstance(instance_id, str) and instance_id:
            return instance_id
    return None


def _model_patch_from_record(
    item: Dict[str, Any],
    line_number: int,
    diagnostics: Diagnostics,
) -> Optional[str]:
    for source in (item, item.get("execution")):
        if not isinstance(source, dict):
            continue
        for field_name in ("model_patch", "patch"):
            value = source.get(field_name)
            if isinstance(value, str):
                return value
        patch_path = source.get("patch_path")
        if isinstance(patch_path, str) and patch_path:
            try:
                return Path(patch_path).read_text(encoding="utf-8")
            except OSError as exc:
                diagnostics.error(
                    "AMF227",
                    f"could not read SWE-bench patch file at line {line_number}: {patch_path}",
                    f"swebench.results_file:{line_number}",
                    str(exc),
                )
                return None
    return None


def _normalize_execution_result(
    item: Dict[str, Any],
    line_number: int,
    diagnostics: Diagnostics,
) -> Optional[Dict[str, Any]]:
    instance_id = item.get("instance_id")
    task = item.get("task")
    if instance_id is None and isinstance(task, dict):
        instance_id = task.get("instance_id")
    if not isinstance(instance_id, str) or not instance_id:
        diagnostics.error(
            "AMF213",
            f"SWE-bench result line {line_number} requires instance_id or task.instance_id",
            f"swebench.results_file:{line_number}",
        )
        return None

    execution = item.get("execution")
    if not isinstance(execution, dict) or "resolved" not in execution:
        execution = item
    if "resolved" not in execution:
        diagnostics.error(
            "AMF215",
            f"SWE-bench result line {line_number} requires resolved",
            f"swebench.results_file:{line_number}",
        )
        return None

    prompt_tokens = int(_number(execution.get("prompt_tokens")))
    completion_tokens = int(_number(execution.get("completion_tokens")))
    return {
        "instance_id": instance_id,
        "resolved": _bool(execution.get("resolved")),
        "patch_applied": _bool(execution.get("patch_applied")),
        "tests_passed": _bool(execution.get("tests_passed")),
        "cost_usd": _number(execution.get("cost_usd")),
        "wall_time_ms": _number(execution.get("wall_time_ms")),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "tool_calls": int(_number(execution.get("tool_calls"))),
        "denied_tool_calls": int(_number(execution.get("denied_tool_calls"))),
        "stable_prefix_hash": _stable_prefix_hash(item),
        "patch_path": _optional_str(execution.get("patch_path")),
        "trace_path": _optional_str(execution.get("trace_path")),
        "verification": dict(item.get("verification")) if isinstance(item.get("verification"), dict) else {},
    }


def _summarize_execution_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    count = len(results)
    resolved_count = sum(1 for result in results if result["resolved"])
    patch_applied_count = sum(1 for result in results if result["patch_applied"])
    tests_passed_count = sum(1 for result in results if result["tests_passed"])
    total_cost = sum(float(result["cost_usd"]) for result in results)
    stable_prefix_hashes = []
    for result in results:
        stable_prefix_hash = result.get("stable_prefix_hash")
        if stable_prefix_hash and stable_prefix_hash not in stable_prefix_hashes:
            stable_prefix_hashes.append(stable_prefix_hash)
    return {
        "result_count": count,
        "resolved_count": resolved_count,
        "resolved_rate": round(resolved_count / count, 4) if count else 0.0,
        "patch_applied_count": patch_applied_count,
        "patch_applied_rate": round(patch_applied_count / count, 4) if count else 0.0,
        "tests_passed_count": tests_passed_count,
        "tests_passed_rate": round(tests_passed_count / count, 4) if count else 0.0,
        "average_cost_usd": _average(results, "cost_usd"),
        "average_wall_time_ms": _average(results, "wall_time_ms"),
        "average_total_tokens": _average(results, "total_tokens"),
        "cost_per_resolved": round(total_cost / resolved_count, 4) if resolved_count else 0.0,
        "tool_calls": sum(int(result["tool_calls"]) for result in results),
        "denied_tool_calls": sum(int(result["denied_tool_calls"]) for result in results),
        "stable_prefix_hashes": stable_prefix_hashes,
    }


def _summarize_official_report(report: Dict[str, Any], diagnostics: Diagnostics) -> Dict[str, Any]:
    fields = [
        "total_instances",
        "submitted_instances",
        "completed_instances",
        "resolved_instances",
        "unresolved_instances",
        "empty_patch_instances",
        "error_instances",
    ]
    values = {field_name: _int_report_field(report, field_name, diagnostics) for field_name in fields}
    if diagnostics.has_errors:
        return {}
    submitted_instances = values["submitted_instances"]
    return {
        "schema_version": int(_number(report.get("schema_version"))),
        **values,
        "resolved_rate": _rate(values["resolved_instances"], submitted_instances),
        "completion_rate": _rate(values["completed_instances"], submitted_instances),
        "error_rate": _rate(values["error_instances"], submitted_instances),
    }


def _int_report_field(report: Dict[str, Any], field_name: str, diagnostics: Diagnostics) -> int:
    value = report.get(field_name)
    if isinstance(value, bool):
        diagnostics.error(
            "AMF228",
            f"SWE-bench official report field must be an integer: {field_name}",
            f"swebench.report_file.{field_name}",
        )
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    diagnostics.error(
        "AMF228",
        f"SWE-bench official report field must be an integer: {field_name}",
        f"swebench.report_file.{field_name}",
    )
    return 0


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _stable_prefix_hash(item: Dict[str, Any]) -> Optional[str]:
    agentmf = item.get("agentmf")
    if isinstance(agentmf, dict):
        stable_prefix_hash = agentmf.get("stable_prefix_hash")
        if isinstance(stable_prefix_hash, str):
            return stable_prefix_hash
    trace_bundle = item.get("trace_bundle")
    if isinstance(trace_bundle, dict):
        stable_prefix_hash = trace_bundle.get("stable_prefix_hash")
        if isinstance(stable_prefix_hash, str):
            return stable_prefix_hash
    return None


def _average(results: List[Dict[str, Any]], key: str) -> float:
    if not results:
        return 0.0
    return round(sum(float(result[key]) for result in results) / len(results), 4)


def _number(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "pass", "passed", "resolved"}
    return False


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _optional_str(value: Any) -> Optional[str]:
    return value if isinstance(value, str) else None
