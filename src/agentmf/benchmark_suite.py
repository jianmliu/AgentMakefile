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

import json
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import yaml

from agentmf.diagnostics import Diagnostics

KNOWN_TOP_LEVEL_KEYS = {"version", "suite", "tasks", "baselines", "adapters", "scoring", "agentmakefile"}
KNOWN_TASK_KEYS = {"id", "request", "repo", "expected_targets", "expected_skills", "verifier", "tags"}
SUPPORTED_ADAPTERS = {"deterministic-selection", "subprocess-execution", "embedding-selection"}
SUBPROCESS_RUNNER_TIMEOUT_SECONDS = 60


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
    runner_command: Optional[str] = None,
    embedder_choice: str = "auto",
    embedder_model: Optional[str] = None,
    embedder_dim: int = 384,
    embedder_top_k: int = 5,
    embedder_cache: Optional[Union[Path, str]] = None,
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

    adapter_extra: Dict[str, Any] = {}
    if adapter == "deterministic-selection":
        task_records = _run_deterministic(suite, target_agentmakefile)
    elif adapter == "subprocess-execution":
        if not runner_command:
            diagnostics.error(
                "AMF253",
                "subprocess-execution adapter requires --runner-command",
                "benchmark.suite.runner_command",
            )
            return SuiteRunResult(diagnostics)
        task_records = _run_subprocess(suite, target_agentmakefile, runner_command, diagnostics)
    elif adapter == "embedding-selection":
        task_records, adapter_extra = _run_embedding(
            suite,
            target_agentmakefile,
            embedder_choice=embedder_choice,
            embedder_model=embedder_model,
            embedder_dim=embedder_dim,
            top_k=embedder_top_k,
            cache_path=Path(embedder_cache) if embedder_cache else None,
            diagnostics=diagnostics,
        )
        if diagnostics.has_errors:
            return SuiteRunResult(diagnostics)
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
    if adapter_extra:
        payload.update(adapter_extra)
    return SuiteRunResult(diagnostics, payload)


def _run_deterministic(suite: SuiteSpec, agentmakefile: Path) -> List[Dict[str, Any]]:
    from agentmf.selector import create_link_plan

    records: List[Dict[str, Any]] = []
    for task in suite.tasks:
        plan_result = create_link_plan(agentmakefile, request=task.request)
        plan_dict = plan_result.plan or {}
        actual_targets = list(plan_dict.get("selected_targets") or [])
        actual_skills = _selected_skills_from_plan(plan_dict, actual_targets)

        target_pass = (
            not task.expected_targets
            or (bool(actual_targets) and actual_targets[0] in task.expected_targets)
        )
        skill_pass = (
            not task.expected_skills
            or any(skill in task.expected_skills for skill in actual_skills)
        )

        if not task.expected_targets and not task.expected_skills:
            status = "skipped"
        elif target_pass and skill_pass:
            status = "passed"
        else:
            status = "failed"

        records.append(
            {
                "task_id": task.task_id,
                "request": task.request,
                "expected_targets": list(task.expected_targets),
                "actual_targets": actual_targets,
                "expected_skills": list(task.expected_skills),
                "actual_skills": actual_skills,
                "status": status,
                "diagnostics": plan_result.diagnostics.to_list(),
            }
        )
    return records


def _run_embedding(
    suite: SuiteSpec,
    agentmakefile: Path,
    *,
    embedder_choice: str,
    embedder_model: Optional[str],
    embedder_dim: int,
    top_k: int,
    cache_path: Optional[Path],
    diagnostics: Diagnostics,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Embedding-selection adapter (step #3 of the keyword→embedding
    migration). Builds (or loads from `cache_path`) a `SkillIndex`
    once per suite, then issues a top-K cosine query per task and
    treats rank-1 as the routed target. Pass/fail uses the same
    expected_targets / expected_skills comparison the deterministic
    adapter does.

    The full top-K is preserved under `record["alternatives"]` so
    routing-quality reports can show "how close did we come" when the
    rank-1 misses but the expected target is at rank-2 / rank-3.
    """
    try:
        from agentmf.embedder import HashEmbedder, SentenceTransformerEmbedder, get_default_embedder
        from agentmf.skill_index import SkillIndex
    except ImportError as exc:  # pragma: no cover - numpy is a hard dep now
        diagnostics.error(
            "AMF254",
            f"embedding-selection adapter dependencies missing: {exc}",
            "benchmark.suite.adapter",
        )
        return [], {}

    if embedder_choice == "hash":
        embedder = HashEmbedder(dim=embedder_dim)
    elif embedder_choice == "sentence-transformer":
        embedder = SentenceTransformerEmbedder(model=embedder_model)
    else:
        embedder = get_default_embedder(dim=embedder_dim)

    index: Optional[SkillIndex] = None
    cache_status = "skipped"
    if cache_path is not None and cache_path.exists():
        try:
            index = SkillIndex.load(cache_path, embedder=embedder)
            cache_status = "hit"
        except ValueError as exc:
            cache_status = f"miss ({exc})"
            index = None
    if index is None:
        try:
            index = SkillIndex.from_path(agentmakefile, embedder=embedder)
            cache_status = "miss" if cache_path is not None else "skipped"
        except ValueError as exc:
            diagnostics.error(
                "AMF255",
                f"could not build SkillIndex for {agentmakefile}: {exc}",
                "benchmark.suite.embedding",
            )
            return [], {}

    records: List[Dict[str, Any]] = []
    for task in suite.tasks:
        matches = index.query(task.request, top_k=max(int(top_k), 1))
        actual_targets = [matches[0].target_name] if matches else []
        actual_skills = [matches[0].skill_name] if matches else []

        target_pass = (
            not task.expected_targets
            or (bool(actual_targets) and actual_targets[0] in task.expected_targets)
        )
        skill_pass = (
            not task.expected_skills
            or any(skill in task.expected_skills for skill in actual_skills)
        )

        if not task.expected_targets and not task.expected_skills:
            status = "skipped"
        elif target_pass and skill_pass:
            status = "passed"
        else:
            status = "failed"

        records.append(
            {
                "task_id": task.task_id,
                "request": task.request,
                "expected_targets": list(task.expected_targets),
                "actual_targets": actual_targets,
                "expected_skills": list(task.expected_skills),
                "actual_skills": actual_skills,
                "status": status,
                "alternatives": [
                    {"rank": m.rank, "target": m.target_name, "skill": m.skill_name, "score": m.score}
                    for m in matches
                ],
                "score": matches[0].score if matches else 0.0,
                "diagnostics": [],
            }
        )

    extra = {
        "embedder": {
            "name": embedder.name,
            "dim": embedder.dim,
            "cache_path": str(cache_path) if cache_path else None,
            "cache_status": cache_status,
            "top_k": int(top_k),
        }
    }
    return records, extra


def _run_subprocess(
    suite: SuiteSpec,
    agentmakefile: Path,
    runner_command: str,
    diagnostics: Diagnostics,
) -> List[Dict[str, Any]]:
    """BENCH-007 first host execution adapter.

    For each task, send a one-line JSON record to the runner's stdin and
    parse a one-line JSON record from its stdout. The runner is opaque to
    AgentMakefile: it can be a script that shells out to Codex, a local
    `agentmf ask --provider echo` invocation, or anything else that
    speaks the BENCH-006 host_execution_adapter_contract.
    """
    try:
        argv = shlex.split(runner_command)
    except ValueError as exc:
        diagnostics.error(
            "AMF253",
            f"could not parse runner command: {runner_command}",
            "benchmark.suite.runner_command",
            str(exc),
        )
        return []
    if not argv:
        diagnostics.error("AMF253", "runner command must be non-empty", "benchmark.suite.runner_command")
        return []

    records: List[Dict[str, Any]] = []
    for task in suite.tasks:
        input_record = {
            "task_id": task.task_id,
            "request": task.request,
            "expected_targets": list(task.expected_targets),
            "expected_skills": list(task.expected_skills),
            "agentmakefile": str(agentmakefile),
        }
        try:
            proc = subprocess.run(
                argv,
                input=json.dumps(input_record),
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_RUNNER_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            records.append(
                {
                    "task_id": task.task_id,
                    "request": task.request,
                    "expected_targets": list(task.expected_targets),
                    "expected_skills": list(task.expected_skills),
                    "actual_target": None,
                    "status": "failed",
                    "fail_reason": f"runner invocation error: {exc}",
                }
            )
            continue
        if proc.returncode != 0:
            records.append(
                {
                    "task_id": task.task_id,
                    "request": task.request,
                    "expected_targets": list(task.expected_targets),
                    "expected_skills": list(task.expected_skills),
                    "actual_target": None,
                    "status": "failed",
                    "fail_reason": f"runner exit {proc.returncode}: {proc.stderr.strip()}",
                }
            )
            continue
        try:
            output = json.loads(proc.stdout.strip().splitlines()[-1]) if proc.stdout.strip() else {}
        except (json.JSONDecodeError, IndexError) as exc:
            records.append(
                {
                    "task_id": task.task_id,
                    "request": task.request,
                    "expected_targets": list(task.expected_targets),
                    "expected_skills": list(task.expected_skills),
                    "actual_target": None,
                    "status": "failed",
                    "fail_reason": f"could not parse runner stdout: {exc}",
                }
            )
            continue
        passed = bool(output.get("pass"))
        records.append(
            {
                "task_id": task.task_id,
                "request": task.request,
                "expected_targets": list(task.expected_targets),
                "expected_skills": list(task.expected_skills),
                "actual_target": output.get("actual_target"),
                "status": "passed" if passed else "failed",
                "fail_reason": output.get("fail_reason") if not passed else None,
                "cost_usd": output.get("cost_usd"),
                "wall_time_ms": output.get("wall_time_ms"),
                "prompt_tokens": output.get("prompt_tokens"),
                "completion_tokens": output.get("completion_tokens"),
            }
        )
    return records


def _selected_skills_from_plan(plan: Dict[str, Any], selected_targets: List[str]) -> List[str]:
    """Return the union of qualified skill names bound by the selected
    target's pipeline, in pipeline order, preserving deterministic
    de-duplication."""
    pipelines = plan.get("target_pipelines") or []
    selected_set = set(selected_targets)
    skills: List[str] = []
    for pipeline in pipelines:
        if not isinstance(pipeline, dict):
            continue
        if pipeline.get("target") not in selected_set:
            continue
        for skill in pipeline.get("skills") or []:
            if isinstance(skill, str) and skill not in skills:
                skills.append(skill)
    return skills


def create_host_execution_adapter_contract() -> Dict[str, Any]:
    """BENCH-006: emit a documentation-only contract describing the schema
    a hosted-agent execution adapter must accept (one harness bundle per
    task) and emit (one result record per task). The contract is
    intentionally provider-agnostic: real LLM execution stays opt-in and
    out of this module (BENCH-007+).

    Mirrors the shape of `clawbench.create_clawbench_host_adapter_contract`
    but scoped to generic benchmark suites rather than ClawBench.
    """
    return {
        "version": 1,
        "mode": "host_execution_adapter_contract",
        "benchmark": "agentmf-suite",
        "adapter": {
            "kind": "host-execution",
            "execution": "external",
            "agentmakefile_role": "harness_selection_layer",
            "opt_in": True,
        },
        "input_contract": {
            "format": "jsonl",
            "record_mode": "agentmf_harness_export",
            "required_fields": [
                "task.id",
                "task.request",
                "agentmf.selected_targets",
                "agentmf.selected_pipeline",
                "prompt.stable_prefix.content",
                "trace_bundle.stable_prefix_hash",
            ],
            "optional_fields": [
                "task.expected_targets",
                "task.expected_skills",
                "task.tags",
                "run.model",
                "run.host",
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
            "record_mode": "agentmf_external_runner_result",
            "required_fields": [
                "task_id",
                "pass",
            ],
            "optional_fields": [
                "fail_reason",
                "reward_lenient",
                "reward_strict",
                "cost_usd",
                "wall_time_ms",
                "prompt_tokens",
                "completion_tokens",
                "tool_calls",
                "denied_tool_calls",
                "selected_target_actual",
                "trace_path",
                "agentmf.stable_prefix_hash",
            ],
        },
        "safety": {
            "destructive_tools": "must default to deny",
            "verifier_commands": "must be explicit in the suite file",
            "artifact_retention": "include enough trace data for post-run audit",
        },
    }


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
    show_skills = any(task.get("expected_skills") for task in payload.get("tasks", []))
    if show_skills:
        lines.append("| Task | Status | Expected | Actual | Skills |")
        lines.append("| --- | --- | --- | --- | --- |")
    else:
        lines.append("| Task | Status | Expected | Actual |")
        lines.append("| --- | --- | --- | --- |")
    for task in payload.get("tasks", []):
        expected = ", ".join(f"`{t}`" for t in task.get("expected_targets") or []) or "—"
        actual = ", ".join(f"`{t}`" for t in task.get("actual_targets") or []) or "—"
        if show_skills:
            expected_skills = task.get("expected_skills") or []
            actual_skills = task.get("actual_skills") or []
            if expected_skills:
                skills_cell = (
                    "expected="
                    + ", ".join(f"`{s}`" for s in expected_skills)
                    + " actual="
                    + (", ".join(f"`{s}`" for s in actual_skills) or "—")
                )
            else:
                skills_cell = "(no expectation; actual=" + (", ".join(f"`{s}`" for s in actual_skills) or "—") + ")"
            lines.append(f"| `{task.get('task_id', '?')}` | {task.get('status', '?')} | {expected} | {actual} | {skills_cell} |")
        else:
            lines.append(f"| `{task.get('task_id', '?')}` | {task.get('status', '?')} | {expected} | {actual} |")
    return "\n".join(lines) + "\n"
