from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.plugin import create_plugin_payload


@dataclass
class ClawBenchHarnessExportResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_clawbench_harness_export(
    path: Union[Path, str],
    *,
    task_id: str,
    instruction: str,
    host: str = "generic",
    model: Optional[str] = None,
    backend: str = "agents-fragments",
    include_git_status: bool = False,
    include_git_diff: bool = False,
    context_files: Optional[List[Union[Path, str]]] = None,
) -> ClawBenchHarnessExportResult:
    plugin_result = create_plugin_payload(
        path=path,
        host=host,
        request=instruction,
        backend=backend,
        include_git_status=include_git_status,
        include_git_diff=include_git_diff,
        context_files=context_files,
    )
    diagnostics = Diagnostics()
    diagnostics.extend(plugin_result.diagnostics.items)
    if diagnostics.has_errors:
        return ClawBenchHarnessExportResult(diagnostics)

    payload = _export_payload(
        task_id=task_id,
        instruction=instruction,
        host=host,
        model=model,
        plugin_payload=plugin_result.payload,
    )
    return ClawBenchHarnessExportResult(diagnostics, payload)


def create_clawbench_jsonl_export(
    path: Union[Path, str],
    *,
    tasks_file: Union[Path, str],
    host: str = "generic",
    model: Optional[str] = None,
    backend: str = "agents-fragments",
    include_git_status: bool = False,
    include_git_diff: bool = False,
    context_files: Optional[List[Union[Path, str]]] = None,
) -> ClawBenchHarnessExportResult:
    diagnostics = Diagnostics()
    tasks = _read_tasks_file(Path(tasks_file), diagnostics)
    if diagnostics.has_errors:
        return ClawBenchHarnessExportResult(diagnostics)

    records = []
    for task in tasks:
        export_result = create_clawbench_harness_export(
            path=path,
            task_id=task["id"],
            instruction=task["instruction"],
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
        return ClawBenchHarnessExportResult(diagnostics)

    jsonl = "\n".join(_json_line(record) for record in records)
    if jsonl:
        jsonl += "\n"
    return ClawBenchHarnessExportResult(
        diagnostics,
        {
            "version": 1,
            "mode": "clawbench_harness_export_jsonl",
            "benchmark": "clawbench",
            "task_count": len(records),
            "records": records,
            "jsonl": jsonl,
        },
    )


def create_clawbench_host_adapter_contract(*, host: str = "generic") -> ClawBenchHarnessExportResult:
    diagnostics = Diagnostics()
    return ClawBenchHarnessExportResult(
        diagnostics,
        {
            "version": 1,
            "mode": "clawbench_host_adapter_contract",
            "benchmark": "clawbench",
            "adapter": {
                "host": host,
                "execution": "external",
                "agentmakefile_role": "harness_selection_layer",
            },
            "input_contract": {
                "format": "jsonl",
                "record_mode": "clawbench_harness_export",
                "required_fields": [
                    "task.id",
                    "task.instruction",
                    "agentmf.selected_targets",
                    "agentmf.selected_pipeline",
                    "prompt.stable_prefix.content",
                    "trace_bundle.stable_prefix_hash",
                ],
                "optional_fields": [
                    "run.model",
                    "prompt.volatile_context",
                    "agentmf.selected_skills",
                    "agentmf.selection_trace",
                    "trace_bundle.guard_ops",
                    "trace_bundle.permission_ops",
                    "trace_bundle.fallback_ops",
                    "trace_bundle.output_contracts",
                ],
            },
            "output_contract": {
                "format": "jsonl",
                "record_mode": "clawbench_external_runner_result",
                "required_fields": [
                    "task_id",
                    "pass",
                ],
                "optional_fields": [
                    "reward_lenient",
                    "reward_strict",
                    "cost_usd",
                    "wall_time_ms",
                    "prompt_tokens",
                    "completion_tokens",
                    "tool_calls",
                    "denied_tool_calls",
                    "trace_path",
                    "agentmf.stable_prefix_hash",
                ],
            },
        },
    )


def create_clawbench_result_summary(*, results_file: Union[Path, str]) -> ClawBenchHarnessExportResult:
    diagnostics = Diagnostics()
    raw_results = _read_results_file(Path(results_file), diagnostics)
    if diagnostics.has_errors:
        return ClawBenchHarnessExportResult(diagnostics)

    results = []
    for line_number, item in raw_results:
        result = _normalize_runner_result(item, line_number, diagnostics)
        if result is not None:
            results.append(result)
    if diagnostics.has_errors:
        return ClawBenchHarnessExportResult(diagnostics)
    if not results:
        diagnostics.error(
            "AMF190",
            f"ClawBench results file contained no results: {results_file}",
            "clawbench.results_file",
        )
        return ClawBenchHarnessExportResult(diagnostics)

    summary = _summarize_runner_results(results)
    return ClawBenchHarnessExportResult(
        diagnostics,
        {
            "version": 1,
            "mode": "clawbench_external_runner_results",
            "benchmark": "clawbench",
            "results_file": str(results_file),
            "summary": summary,
            "results": results,
        },
    )


def _read_tasks_file(path: Path, diagnostics: Diagnostics) -> List[Dict[str, str]]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error(
            "AMF180",
            f"could not read ClawBench tasks file: {path}",
            "clawbench.tasks_file",
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
                "AMF181",
                f"invalid JSONL task at line {line_number}: {exc.msg}",
                f"clawbench.tasks_file:{line_number}",
            )
            continue
        if not isinstance(item, dict):
            diagnostics.error(
                "AMF182",
                f"ClawBench task line {line_number} must be a JSON object",
                f"clawbench.tasks_file:{line_number}",
            )
            continue
        task_id = item.get("id") or item.get("task_id")
        instruction = item.get("instruction") or item.get("prompt")
        if not isinstance(task_id, str) or not task_id:
            diagnostics.error(
                "AMF183",
                f"ClawBench task line {line_number} requires string id or task_id",
                f"clawbench.tasks_file:{line_number}",
            )
            continue
        if not isinstance(instruction, str) or not instruction:
            diagnostics.error(
                "AMF184",
                f"ClawBench task line {line_number} requires string instruction or prompt",
                f"clawbench.tasks_file:{line_number}",
            )
            continue
        tasks.append({"id": task_id, "instruction": instruction})
    if not tasks and not diagnostics.has_errors:
        diagnostics.error(
            "AMF185",
            f"ClawBench tasks file contained no tasks: {path}",
            "clawbench.tasks_file",
        )
    return tasks


def _read_results_file(path: Path, diagnostics: Diagnostics) -> List[tuple[int, Dict[str, Any]]]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error(
            "AMF186",
            f"could not read ClawBench results file: {path}",
            "clawbench.results_file",
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
                "AMF187",
                f"invalid JSONL result at line {line_number}: {exc.msg}",
                f"clawbench.results_file:{line_number}",
            )
            continue
        if not isinstance(item, dict):
            diagnostics.error(
                "AMF188",
                f"ClawBench result line {line_number} must be a JSON object",
                f"clawbench.results_file:{line_number}",
            )
            continue
        results.append((line_number, item))
    return results


def _json_line(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _normalize_runner_result(
    item: Dict[str, Any],
    line_number: int,
    diagnostics: Diagnostics,
) -> Optional[Dict[str, Any]]:
    task_id = item.get("task_id") or item.get("id")
    task = item.get("task")
    if task_id is None and isinstance(task, dict):
        task_id = task.get("id") or task.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        diagnostics.error(
            "AMF189",
            f"ClawBench result line {line_number} requires task_id or task.id",
            f"clawbench.results_file:{line_number}",
        )
        return None

    execution = item.get("execution")
    if not isinstance(execution, dict) or "pass" not in execution:
        execution = item
    if "pass" not in execution:
        diagnostics.error(
            "AMF191",
            f"ClawBench result line {line_number} requires pass",
            f"clawbench.results_file:{line_number}",
        )
        return None

    prompt_tokens = int(_number(execution.get("prompt_tokens")))
    completion_tokens = int(_number(execution.get("completion_tokens")))
    stable_prefix_hash = _stable_prefix_hash(item)
    normalized = {
        "task_id": task_id,
        "pass": bool(execution.get("pass")),
        "reward_lenient": _optional_number(execution.get("reward_lenient")),
        "reward_strict": _optional_number(execution.get("reward_strict")),
        "cost_usd": _number(execution.get("cost_usd")),
        "wall_time_ms": _number(execution.get("wall_time_ms")),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "tool_calls": int(_number(execution.get("tool_calls"))),
        "denied_tool_calls": int(_number(execution.get("denied_tool_calls"))),
        "stable_prefix_hash": stable_prefix_hash,
    }
    return normalized


def _summarize_runner_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    count = len(results)
    pass_count = sum(1 for result in results if result["pass"])
    stable_prefix_hashes = []
    for result in results:
        stable_prefix_hash = result.get("stable_prefix_hash")
        if stable_prefix_hash and stable_prefix_hash not in stable_prefix_hashes:
            stable_prefix_hashes.append(stable_prefix_hash)
    return {
        "result_count": count,
        "pass_count": pass_count,
        "pass_rate": round(pass_count / count, 4) if count else 0.0,
        "average_cost_usd": _average(results, "cost_usd"),
        "average_wall_time_ms": _average(results, "wall_time_ms"),
        "average_total_tokens": _average(results, "total_tokens"),
        "tool_calls": sum(int(result["tool_calls"]) for result in results),
        "denied_tool_calls": sum(int(result["denied_tool_calls"]) for result in results),
        "stable_prefix_hashes": stable_prefix_hashes,
    }


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


def _optional_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    return _number(value)


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


def _export_payload(
    *,
    task_id: str,
    instruction: str,
    host: str,
    model: Optional[str],
    plugin_payload: Dict[str, Any],
) -> Dict[str, Any]:
    selected_pipeline = plugin_payload["selected_pipeline"]
    stable_prefix = plugin_payload["stable_prefix"]
    return {
        "version": 1,
        "mode": "clawbench_harness_export",
        "benchmark": "clawbench",
        "task": {
            "id": task_id,
            "instruction": instruction,
        },
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
