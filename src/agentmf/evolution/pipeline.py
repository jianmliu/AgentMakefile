"""Evolution pipeline (split from evolution.py — in-tree package, same public API)."""
from __future__ import annotations

from agentmf.diagnostics import Diagnostics
from agentmf.loader import load_source_with_diagnostics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union
import json
from agentmf.evolution.patches import _candidate_source_files_for_proposal, _workspace_destination
from agentmf.evolution.proposals import _load_proposal


@dataclass
class CompileEvaluateResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_compile_evaluate_payload(
    *,
    proposal_file: Union[Path, str],
    workspace_dir: Union[Path, str] = Path(".agentmf/evolution/worktrees"),
    write: bool = False,
) -> CompileEvaluateResult:
    diagnostics = Diagnostics()
    proposal = _load_proposal(proposal_file, diagnostics)
    if proposal is None or diagnostics.has_errors:
        return CompileEvaluateResult(diagnostics)

    candidate_files, unsupported = _candidate_source_files_for_proposal(proposal, diagnostics)
    if diagnostics.has_errors:
        return CompileEvaluateResult(diagnostics)

    workspace = Path(workspace_dir)
    candidate_records = []
    used_destinations: set[Path] = set()

    def reserve_destination(source_path: Path) -> Path:
        destination = _workspace_destination(workspace, source_path, used_destinations)
        used_destinations.add(destination)
        return destination

    if write:
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            for candidate in candidate_files:
                destination = reserve_destination(candidate["source_path"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(candidate["candidate_content"], encoding="utf-8")
                candidate_records.append({"source": str(candidate["source_path"]), "path": str(destination)})
        except OSError as exc:
            diagnostics.error(
                "AMF229",
                f"could not write candidate workspace under {workspace}",
                "evo.evaluate.workspace_dir",
                str(exc),
            )
            return CompileEvaluateResult(diagnostics)
    else:
        for candidate in candidate_files:
            candidate_records.append(
                {
                    "source": str(candidate["source_path"]),
                    "path": str(reserve_destination(candidate["source_path"])),
                }
            )

    validation_results = []
    for candidate_record in candidate_records:
        path = Path(candidate_record["path"])
        if not path.exists():
            validation_results.append({"path": str(path), "status": "not_run", "diagnostics": []})
            continue
        source, load_diagnostics = load_source_with_diagnostics(path)
        validation_results.append(
            {
                "path": str(path),
                "status": "passed" if source is not None and not load_diagnostics.has_errors else "failed",
                "diagnostics": load_diagnostics.to_list(),
            }
        )

    compile_results = _evaluate_compile_gate(candidate_records, workspace) if write else []
    selector_test_results = _evaluate_selector_test_gate(candidate_records, proposal) if write else []
    benchmark_smoke_results = (
        _evaluate_benchmark_smoke_gate(candidate_records, proposal, diagnostics) if write else _empty_smoke_results()
    )

    status = "passed"
    if unsupported and not candidate_records:
        status = "skipped_unsupported_change"
    if any(result["status"] == "failed" for result in validation_results):
        status = "failed"
    if any(result["status"] == "failed" for result in compile_results):
        status = "failed"
    if any(result["status"] == "failed" for result in selector_test_results):
        status = "failed"
    if benchmark_smoke_results["summary"]["failed"] > 0:
        status = "failed"
    return CompileEvaluateResult(
        diagnostics,
        {
            "version": 1,
            "mode": "compile_evaluate",
            "workspace_dir": str(workspace),
            "candidate_files": candidate_records,
            "promotion_report": {
                "proposal_id": proposal.get("proposal_id"),
                "status": status,
                "requires_review": True,
                "validations": validation_results,
                "compile_results": compile_results,
                "selector_test_results": selector_test_results,
                "benchmark_smoke_results": benchmark_smoke_results,
                "commands": proposal.get("evaluation", {}).get("commands", []),
                "unsupported_changes": unsupported,
            },
        },
    )


def _empty_smoke_results() -> Dict[str, Any]:
    return {
        "tasks_file": None,
        "tasks": [],
        "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
    }


def _evaluate_benchmark_smoke_gate(
    candidate_records: list[Dict[str, str]],
    proposal: Dict[str, Any],
    diagnostics: Diagnostics,
) -> Dict[str, Any]:
    """Route every task in `evaluation.benchmark_smoke.tasks_file` against
    the candidate AgentMakefile(s) and check the resulting target against
    `evaluation.benchmark_smoke.expected_routes`. A task with no entry in
    expected_routes is skipped (still reported). A task whose expected
    target doesn't match its actual route on any candidate fails.
    """
    evaluation = proposal.get("evaluation") if isinstance(proposal.get("evaluation"), dict) else {}
    smoke = evaluation.get("benchmark_smoke") if isinstance(evaluation.get("benchmark_smoke"), dict) else None
    if smoke is None:
        return _empty_smoke_results()

    tasks_file_ref = smoke.get("tasks_file")
    expected = smoke.get("expected_routes") or {}
    if not isinstance(tasks_file_ref, str) or not isinstance(expected, dict):
        return _empty_smoke_results()

    tasks_file = Path(tasks_file_ref)
    try:
        lines = tasks_file.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        diagnostics.error(
            "AMF234",
            f"could not read benchmark_smoke tasks_file: {tasks_file}",
            "evo.evaluate.benchmark_smoke",
            str(exc),
        )
        return {
            "tasks_file": str(tasks_file),
            "tasks": [],
            "summary": {"total": 0, "passed": 0, "failed": 0, "skipped": 0},
        }

    from agentmf.selector import create_link_plan

    candidate_paths = [Path(record["path"]) for record in candidate_records if Path(record["path"]).exists()]
    task_records: list[Dict[str, Any]] = []
    passed = failed = skipped = 0
    for line_number, raw in enumerate(lines, start=1):
        if not raw.strip():
            continue
        try:
            task = json.loads(raw)
        except json.JSONDecodeError as exc:
            diagnostics.error(
                "AMF234",
                f"invalid benchmark_smoke task at {tasks_file}:{line_number}",
                "evo.evaluate.benchmark_smoke",
                str(exc),
            )
            continue
        task_id = task.get("id")
        instruction = task.get("instruction")
        if not isinstance(task_id, str) or not isinstance(instruction, str):
            continue
        actual: Optional[str] = None
        for path in candidate_paths:
            plan = create_link_plan(path, request=instruction)
            if plan.diagnostics.has_errors:
                continue
            selected = (plan.plan or {}).get("selected_targets") or []
            if selected:
                actual = selected[0]
                break
        expected_target = expected.get(task_id)
        if expected_target is None:
            status = "skipped"
            skipped += 1
        elif actual == expected_target:
            status = "passed"
            passed += 1
        else:
            status = "failed"
            failed += 1
        task_records.append(
            {
                "task_id": task_id,
                "instruction": instruction,
                "expected_target": expected_target,
                "actual_target": actual,
                "status": status,
            }
        )

    return {
        "tasks_file": str(tasks_file),
        "tasks": task_records,
        "summary": {"total": len(task_records), "passed": passed, "failed": failed, "skipped": skipped},
    }


def _evaluate_compile_gate(
    candidate_records: list[Dict[str, str]],
    workspace: Path,
) -> list[Dict[str, Any]]:
    """Compile each candidate AgentMakefile to the lightweight
    `agents-fragments` backend. The candidate is written to the workspace
    already; we just need to drive the compiler and capture diagnostics.
    """
    from agentmf.compiler import compile_agentmakefile

    results: list[Dict[str, Any]] = []
    for record in candidate_records:
        path = Path(record["path"])
        if not path.exists():
            results.append({"path": str(path), "status": "not_run", "diagnostics": []})
            continue
        # Compile into a per-candidate scratch dir so different candidates
        # don't fight over output filenames; we only care about pass/fail.
        out_dir = workspace / "_compile" / path.stem
        try:
            compile_result = compile_agentmakefile(
                path=path,
                out_dir=out_dir,
                targets=["agents-fragments"],
                write=False,
            )
        except Exception as exc:  # defensive: surface unexpected compiler crash
            results.append({"path": str(path), "status": "failed", "diagnostics": [{"reason": str(exc)}]})
            continue
        results.append(
            {
                "path": str(path),
                "status": "passed" if compile_result.ok else "failed",
                "diagnostics": compile_result.diagnostics.to_list(),
            }
        )
    return results


def _evaluate_selector_test_gate(
    candidate_records: list[Dict[str, str]],
    proposal: Dict[str, Any],
) -> list[Dict[str, Any]]:
    """Run any (request, expected_target) pairs declared at
    proposal.evaluation.selector_tests against the candidate files. The
    test passes if any candidate routes the request to expected_target.
    """
    evaluation = proposal.get("evaluation")
    if not isinstance(evaluation, dict):
        return []
    selector_tests = evaluation.get("selector_tests") or []
    if not isinstance(selector_tests, list) or not selector_tests:
        return []

    from agentmf.selector import create_link_plan

    candidate_paths = [Path(record["path"]) for record in candidate_records if Path(record["path"]).exists()]
    results: list[Dict[str, Any]] = []
    for entry in selector_tests:
        if not isinstance(entry, dict):
            continue
        request_text = entry.get("request")
        expected = entry.get("expected_target")
        if not isinstance(request_text, str) or not isinstance(expected, str):
            continue
        actual_target: Optional[str] = None
        diagnostics_records: list[Dict[str, Any]] = []
        for path in candidate_paths:
            plan_result = create_link_plan(path, request=request_text)
            if plan_result.diagnostics.has_errors:
                diagnostics_records.extend(plan_result.diagnostics.to_list())
                continue
            selected = (plan_result.plan or {}).get("selected_targets") or []
            if selected:
                actual_target = selected[0]
                if actual_target == expected:
                    break
        results.append(
            {
                "request": request_text,
                "expected_target": expected,
                "actual_target": actual_target,
                "status": "passed" if actual_target == expected else "failed",
                "diagnostics": diagnostics_records,
            }
        )
    return results


@dataclass
class PromotionResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_promotion_payload(
    *,
    proposal_file: Union[Path, str],
    target_dir: Union[Path, str],
    write: bool = False,
) -> PromotionResult:
    """Promote a reviewed proposal: copy candidate AgentMakefile contents to
    target_dir (preserving the workspace's category subdir layout) and flip
    the proposal's promotion.status from "candidate" to "accepted".

    Canonical source files are never mutated. If any candidate fails to
    re-parse under load_source the promotion is refused.
    """
    diagnostics = Diagnostics()
    proposal_path = Path(proposal_file)
    proposal = _load_proposal(proposal_path, diagnostics)
    if proposal is None or diagnostics.has_errors:
        return PromotionResult(diagnostics)

    candidate_files, unsupported = _candidate_source_files_for_proposal(proposal, diagnostics)
    if diagnostics.has_errors:
        return PromotionResult(diagnostics)

    target_root = Path(target_dir)
    used_destinations: set[Path] = set()
    plan: list[Dict[str, str]] = []
    for candidate in candidate_files:
        destination = _workspace_destination(target_root, candidate["source_path"], used_destinations)
        used_destinations.add(destination)
        plan.append(
            {
                "source": str(candidate["source_path"]),
                "target": str(destination),
                "candidate_content": candidate["candidate_content"],
            }
        )

    promoted_records: list[Dict[str, Any]] = []
    if write:
        try:
            target_root.mkdir(parents=True, exist_ok=True)
            for entry in plan:
                destination = Path(entry["target"])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(entry["candidate_content"], encoding="utf-8")
        except OSError as exc:
            diagnostics.error(
                "AMF230",
                f"could not write promoted candidate under {target_root}",
                "evo.promote.target_dir",
                str(exc),
            )
            return PromotionResult(diagnostics)

        for entry in plan:
            destination = Path(entry["target"])
            source_obj, load_diag = load_source_with_diagnostics(destination)
            status = "passed" if source_obj is not None and not load_diag.has_errors else "failed"
            promoted_records.append(
                {
                    "source": entry["source"],
                    "target": entry["target"],
                    "status": status,
                    "diagnostics": load_diag.to_list(),
                }
            )

        if any(record["status"] == "failed" for record in promoted_records):
            diagnostics.error(
                "AMF231",
                "promoted candidate failed to re-parse; refusing to mark proposal accepted",
                "evo.promote.target_dir",
            )
            return PromotionResult(diagnostics)

        promotion = proposal.setdefault("promotion", {})
        if isinstance(promotion, dict):
            promotion["status"] = "accepted"
            promotion["requires_review"] = False
        try:
            proposal_path.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError as exc:
            diagnostics.error(
                "AMF232",
                f"could not update proposal promotion status: {proposal_path}",
                "evo.promote.proposal_file",
                str(exc),
            )
            return PromotionResult(diagnostics)
    else:
        for entry in plan:
            promoted_records.append(
                {
                    "source": entry["source"],
                    "target": entry["target"],
                    "status": "not_run",
                    "diagnostics": [],
                }
            )

    status = "promoted" if write and plan else ("planned" if plan else "skipped_unsupported_change")
    return PromotionResult(
        diagnostics,
        {
            "version": 1,
            "mode": "evo_promote",
            "proposal_id": proposal.get("proposal_id"),
            "target_dir": str(target_root),
            "status": status,
            "promoted_files": promoted_records,
            "unsupported_changes": unsupported,
        },
    )
