"""BENCH-002 .. BENCH-005: benchmark suite parser, deterministic runner, and
report writer.

A suite YAML file batches benchmark cases together with adapter +
scoring metadata. The first slice ships a single adapter — the
deterministic-selection adapter — which drives every task through
`agentmf.selector.create_link_plan` and reports whether the resulting
`selected_targets[0]` matches the task's declared `expected_targets`.

Public surface:

    parse_suite_file(path) -> SuiteParseResult
    create_suite_payload(suite_file, agentmakefile, adapter) -> SuiteRunResult
    render_suite_markdown(payload) -> str
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import yaml

from agentmf.diagnostics import Diagnostics

KNOWN_TOP_LEVEL_KEYS = {"version", "suite", "tasks", "baselines", "adapters", "scoring", "agentmakefile"}
KNOWN_TASK_KEYS = {"id", "request", "repo", "expected_targets", "expected_skills", "verifier", "tags"}
SUPPORTED_ADAPTERS = {"deterministic-selection"}


@dataclass(frozen=True)
class SuiteTaskSpec:
    task_id: str
    request: str
    expected_targets: List[str] = field(default_factory=list)
    expected_skills: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class SuiteSpec:
    suite_id: str
    title: str
    description: str
    agentmakefile: Optional[str]
    tasks: List[SuiteTaskSpec]
    baselines: List[Dict[str, Any]]
    adapters: List[Dict[str, Any]]
    scoring: Dict[str, Any]


@dataclass
class SuiteParseResult:
    diagnostics: Diagnostics
    suite: Optional[SuiteSpec] = None

    @property
    def ok(self) -> bool:
        return self.suite is not None and not self.diagnostics.has_errors


@dataclass
class SuiteRunResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def parse_suite_file(path: Union[Path, str]) -> SuiteParseResult:
    """Strict-ish parser. Unknown top-level / task keys produce diagnostics
    (warning) but don't fail; missing required fields are errors.
    """
    diagnostics = Diagnostics()
    suite_path = Path(path)
    try:
        text = suite_path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error("AMF250", f"could not read suite file: {suite_path}", "benchmark.suite", str(exc))
        return SuiteParseResult(diagnostics)

    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        diagnostics.error("AMF250", f"could not parse suite YAML: {suite_path}", "benchmark.suite", str(exc))
        return SuiteParseResult(diagnostics)
    if not isinstance(data, dict):
        diagnostics.error("AMF250", "suite root must be a mapping", "benchmark.suite")
        return SuiteParseResult(diagnostics)

    for key in data:
        if key not in KNOWN_TOP_LEVEL_KEYS:
            diagnostics.warning("AMF250", f"unknown suite key: {key}", f"benchmark.suite.{key}")

    suite_meta = data.get("suite") or {}
    if not isinstance(suite_meta, dict):
        diagnostics.error("AMF250", "suite metadata must be a mapping", "benchmark.suite.suite")
        return SuiteParseResult(diagnostics)
    suite_id = str(suite_meta.get("id") or "").strip()
    if not suite_id:
        diagnostics.error("AMF250", "suite.id is required", "benchmark.suite.suite.id")

    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        diagnostics.error("AMF250", "tasks must be a non-empty list", "benchmark.suite.tasks")
        return SuiteParseResult(diagnostics)

    tasks: List[SuiteTaskSpec] = []
    for index, entry in enumerate(raw_tasks):
        if not isinstance(entry, dict):
            diagnostics.error("AMF250", f"task #{index + 1} must be a mapping", "benchmark.suite.tasks")
            continue
        for key in entry:
            if key not in KNOWN_TASK_KEYS:
                diagnostics.warning("AMF250", f"unknown task key: {key}", f"benchmark.suite.tasks[{index}].{key}")
        task_id = str(entry.get("id") or "").strip()
        request = str(entry.get("request") or "").strip()
        if not task_id:
            diagnostics.error("AMF250", f"task #{index + 1} missing id", "benchmark.suite.tasks")
            continue
        if not request:
            diagnostics.error("AMF250", f"task {task_id} missing request", f"benchmark.suite.tasks[{index}]")
            continue
        expected_targets = [str(value) for value in (entry.get("expected_targets") or []) if isinstance(value, str)]
        expected_skills = [str(value) for value in (entry.get("expected_skills") or []) if isinstance(value, str)]
        tags = [str(value) for value in (entry.get("tags") or []) if isinstance(value, str)]
        tasks.append(SuiteTaskSpec(task_id=task_id, request=request,
                                   expected_targets=expected_targets,
                                   expected_skills=expected_skills, tags=tags))

    if diagnostics.has_errors:
        return SuiteParseResult(diagnostics)

    suite = SuiteSpec(
        suite_id=suite_id,
        title=str(suite_meta.get("title") or suite_id),
        description=str(suite_meta.get("description") or ""),
        agentmakefile=str(data["agentmakefile"]) if data.get("agentmakefile") else None,
        tasks=tasks,
        baselines=[dict(item) for item in (data.get("baselines") or []) if isinstance(item, dict)],
        adapters=[dict(item) for item in (data.get("adapters") or []) if isinstance(item, dict)],
        scoring=dict(data.get("scoring") or {}),
    )
    return SuiteParseResult(diagnostics, suite)


def create_suite_payload(
    *,
    suite_file: Union[Path, str],
    agentmakefile: Optional[Union[Path, str]] = None,
    adapter: str = "deterministic-selection",
) -> SuiteRunResult:
    diagnostics = Diagnostics()
    if adapter not in SUPPORTED_ADAPTERS:
        diagnostics.error(
            "AMF251",
            f"unsupported benchmark suite adapter: {adapter}",
            "benchmark.suite.adapter",
            f"choose from: {', '.join(sorted(SUPPORTED_ADAPTERS))}",
        )
        return SuiteRunResult(diagnostics)

    parse_result = parse_suite_file(suite_file)
    diagnostics.extend(parse_result.diagnostics.items)
    if not parse_result.ok or parse_result.suite is None:
        return SuiteRunResult(diagnostics)
    suite = parse_result.suite

    target_agentmakefile = Path(agentmakefile) if agentmakefile else (Path(suite.agentmakefile) if suite.agentmakefile else None)
    if target_agentmakefile is None:
        diagnostics.error(
            "AMF252",
            "no AgentMakefile path provided: pass --file or set suite.agentmakefile",
            "benchmark.suite.agentmakefile",
        )
        return SuiteRunResult(diagnostics)
    if not target_agentmakefile.exists():
        diagnostics.error(
            "AMF252",
            f"AgentMakefile path not found: {target_agentmakefile}",
            "benchmark.suite.agentmakefile",
        )
        return SuiteRunResult(diagnostics)

    if adapter == "deterministic-selection":
        task_records = _run_deterministic(suite, target_agentmakefile)
    else:  # pragma: no cover - guarded above
        task_records = []

    summary = {"total": len(task_records), "passed": 0, "failed": 0, "skipped": 0}
    for record in task_records:
        summary[record["status"]] = summary.get(record["status"], 0) + 1

    payload = {
        "version": 1,
        "mode": "benchmark_suite",
        "suite": {
            "id": suite.suite_id,
            "title": suite.title,
            "description": suite.description,
            "agentmakefile": str(target_agentmakefile),
            "task_count": len(suite.tasks),
            "baselines": suite.baselines,
            "adapters": suite.adapters,
            "scoring": suite.scoring,
        },
        "adapter": adapter,
        "tasks": task_records,
        "summary": summary,
    }
    return SuiteRunResult(diagnostics, payload)


def _run_deterministic(suite: SuiteSpec, agentmakefile: Path) -> List[Dict[str, Any]]:
    from agentmf.selector import create_link_plan

    records: List[Dict[str, Any]] = []
    for task in suite.tasks:
        plan = create_link_plan(agentmakefile, request=task.request)
        actual_targets = list((plan.plan or {}).get("selected_targets") or []) if plan.plan else []
        if task.expected_targets:
            status = "passed" if actual_targets and actual_targets[0] in task.expected_targets else "failed"
        else:
            status = "skipped"
        records.append(
            {
                "task_id": task.task_id,
                "request": task.request,
                "expected_targets": list(task.expected_targets),
                "actual_targets": actual_targets,
                "status": status,
                "diagnostics": plan.diagnostics.to_list(),
            }
        )
    return records


def render_suite_markdown(payload: Dict[str, Any]) -> str:
    suite = payload.get("suite", {})
    summary = payload.get("summary", {})
    lines: List[str] = [
        f"# {suite.get('title') or suite.get('id') or 'benchmark suite'}",
        "",
    ]
    if suite.get("description"):
        lines.append(suite["description"])
        lines.append("")
    lines.append(
        f"- Suite: `{suite.get('id', '-')}`"
    )
    lines.append(f"- AgentMakefile: `{suite.get('agentmakefile', '-')}`")
    lines.append(f"- Adapter: `{payload.get('adapter', '-')}`")
    lines.append(
        f"- Summary: total={summary.get('total', 0)} "
        f"passed={summary.get('passed', 0)} "
        f"failed={summary.get('failed', 0)} "
        f"skipped={summary.get('skipped', 0)}"
    )
    lines.append("")
    lines.append("## Tasks")
    lines.append("")
    lines.append("| Task | Status | Expected | Actual |")
    lines.append("| --- | --- | --- | --- |")
    for task in payload.get("tasks", []):
        expected = ", ".join(f"`{t}`" for t in task.get("expected_targets") or []) or "—"
        actual = ", ".join(f"`{t}`" for t in task.get("actual_targets") or []) or "—"
        lines.append(f"| `{task.get('task_id', '?')}` | {task.get('status', '?')} | {expected} | {actual} |")
    return "\n".join(lines) + "\n"
