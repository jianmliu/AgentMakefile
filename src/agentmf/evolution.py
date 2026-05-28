from __future__ import annotations

import hashlib
import json
import re
import difflib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from agentmf.diagnostics import Diagnostics
from agentmf.loader import load_source_with_diagnostics


EVIDENCE_SOURCES = {
    "plugin_payload",
    "benchmark",
    "user_feedback",
    "registry_scan",
    "openclaw_import",
}

_SOURCE_DIRS = {
    "plugin_payload": "traces",
    "benchmark": "benchmarks",
    "user_feedback": "feedback",
    "registry_scan": "registry",
    "openclaw_import": "registry",
}

PROMOTION_STATUSES = {"candidate", "rejected", "accepted", "superseded"}

SUPPORTED_PATCH_TYPES = {
    "update_match_terms",
    "merge_duplicate_targets",
    "prune_match_terms",
    "add_target",
    "add_dependency",
    "deprecate_skill",
    "add_registry_metadata",
    "add_benchmark_case",
    "update_permission_guard",
    "split_module",
}


@dataclass
class EvolutionEvidenceResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_evolution_evidence_payload(
    *,
    source: str,
    payload: Dict[str, Any],
    out_dir: Union[Path, str] = Path(".agentmf/evolution/evidence"),
    timestamp: Optional[str] = None,
    write: bool = False,
    outcome: Optional[Dict[str, Any]] = None,
    artifact_refs: Optional[Dict[str, Any]] = None,
) -> EvolutionEvidenceResult:
    diagnostics = Diagnostics()
    if source not in EVIDENCE_SOURCES:
        diagnostics.error(
            "AMF220",
            f"unsupported evolution evidence source: {source}",
            "evo.evidence.source",
            f"use one of: {', '.join(sorted(EVIDENCE_SOURCES))}",
        )
        return EvolutionEvidenceResult(diagnostics)

    source_payload = _unwrap_source_payload(source, payload)
    redacted_payload = _redact_secrets(source_payload)
    summary = _summary_for_source(source, redacted_payload)
    refs = {
        **_artifact_refs_for_source(source, redacted_payload),
        **(artifact_refs or {}),
    }
    record = {
        "version": 1,
        "timestamp": timestamp or _utc_now(),
        "source": source,
        "request_fingerprint": _request_fingerprint(redacted_payload),
        "selected_target": _selected_target(redacted_payload),
        "selected_skills": _selected_skills(redacted_payload),
        "selection_trace_hash": _selection_trace_hash(redacted_payload),
        "outcome": outcome or {},
        "artifact_refs": refs,
        "summary": summary,
        "payload_hash": _sha256_json(redacted_payload),
    }
    record["event_id"] = _sha256_json(record)

    output_path = Path(out_dir) / _SOURCE_DIRS[source] / f"{_safe_name(source)}.jsonl"
    if write:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with output_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        except OSError as exc:
            diagnostics.error(
                "AMF221",
                f"could not append evolution evidence record: {output_path}",
                "evo.evidence.out_dir",
                str(exc),
            )
            return EvolutionEvidenceResult(diagnostics)

    return EvolutionEvidenceResult(
        diagnostics,
        {
            "version": 1,
            "mode": "evolution_evidence_add",
            "path": str(output_path),
            "wrote": write,
            "record": record,
        },
    )


@dataclass
class SkillWorkshopProposalResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_skill_workshop_proposal_payload(
    *,
    title: str,
    evidence_files: Optional[list[Union[Path, str]]] = None,
    evidence_records: Optional[list[Dict[str, Any]]] = None,
    scope: Dict[str, Any],
    changes: list[Dict[str, Any]],
    evaluation_commands: list[str],
    out_dir: Union[Path, str] = Path(".agentmf/evolution/candidates"),
    timestamp: Optional[str] = None,
    promotion_status: str = "candidate",
    write: bool = False,
) -> SkillWorkshopProposalResult:
    diagnostics = Diagnostics()
    if promotion_status not in PROMOTION_STATUSES:
        diagnostics.error(
            "AMF222",
            f"unsupported proposal promotion status: {promotion_status}",
            "evo.proposal.promotion_status",
            f"use one of: {', '.join(sorted(PROMOTION_STATUSES))}",
        )
        return SkillWorkshopProposalResult(diagnostics)

    if evidence_records is None:
        evidence_records = _load_evidence_records(evidence_files or [], diagnostics)
        if diagnostics.has_errors:
            return SkillWorkshopProposalResult(diagnostics)

    evidence_refs = [_evidence_ref(record) for record in evidence_records]
    created_at = timestamp or _utc_now()
    proposal_core = {
        "title": title,
        "scope": _normalize_scope(scope),
        "evidence": evidence_refs,
        "changes": changes,
        "evaluation": {
            "commands": evaluation_commands,
            "status": "not_run",
        },
        "promotion": {
            "status": promotion_status,
            "requires_review": promotion_status == "candidate",
        },
    }
    proposal_id = "amf-evo-" + _sha256_json(proposal_core).split(":", 1)[1][:12]
    proposal = {
        "version": 1,
        "proposal_id": proposal_id,
        "created_at": created_at,
        **proposal_core,
    }
    markdown = render_skill_workshop_proposal_markdown(proposal)

    destination = Path(out_dir)
    proposal_path = destination / f"{proposal_id}.proposal.json"
    report_path = destination / f"{proposal_id}.md"
    if write:
        try:
            destination.mkdir(parents=True, exist_ok=True)
            proposal_path.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            report_path.write_text(markdown, encoding="utf-8")
        except OSError as exc:
            diagnostics.error(
                "AMF224",
                f"could not write Skill Workshop proposal under {destination}",
                "evo.proposal.out_dir",
                str(exc),
            )
            return SkillWorkshopProposalResult(diagnostics)

    return SkillWorkshopProposalResult(
        diagnostics,
        {
            "version": 1,
            "mode": "skill_workshop_proposal",
            "wrote": write,
            "proposal": proposal,
            "markdown": None if write else markdown,
            "paths": {
                "proposal_json": str(proposal_path),
                "markdown_report": str(report_path),
            },
        },
    )


def render_skill_workshop_proposal_markdown(proposal: Dict[str, Any]) -> str:
    lines = [
        f"# {proposal['title']}",
        "",
        f"- Proposal ID: `{proposal['proposal_id']}`",
        f"- Status: `{proposal['promotion']['status']}`",
        f"- Requires review: `{str(proposal['promotion']['requires_review']).lower()}`",
        f"- Created: `{proposal['created_at']}`",
        "",
        "## Scope",
        "",
    ]
    modules = proposal["scope"].get("modules", [])
    targets = proposal["scope"].get("targets", [])
    if modules:
        lines.extend(f"- Module: `{module}`" for module in modules)
    if targets:
        lines.extend(f"- Target: `{target}`" for target in targets)
    if not modules and not targets:
        lines.append("- Scope: unspecified")

    lines.extend(["", "## Evidence", ""])
    if proposal["evidence"]:
        for evidence in proposal["evidence"]:
            lines.append(
                f"- `{evidence['event_id']}` from `{evidence.get('source', 'unknown')}`: "
                f"{evidence['reason']}"
            )
    else:
        lines.append("- No evidence records attached.")

    lines.extend(["", "## Changes", ""])
    if proposal["changes"]:
        for change in proposal["changes"]:
            lines.append("```json")
            lines.append(json.dumps(change, indent=2, sort_keys=True))
            lines.append("```")
    else:
        lines.append("- No changes declared.")

    lines.extend(["", "## Evaluation", ""])
    commands = proposal["evaluation"]["commands"]
    if commands:
        lines.extend(f"- [ ] `{command}`" for command in commands)
    else:
        lines.append("- No evaluation commands declared.")
    lines.append(f"- Status: `{proposal['evaluation']['status']}`")
    lines.extend(["", "## Promotion", ""])
    lines.append(f"- Status: `{proposal['promotion']['status']}`")
    lines.append(f"- Requires review: `{str(proposal['promotion']['requires_review']).lower()}`")
    return "\n".join(lines) + "\n"


@dataclass
class CandidatePatchResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_candidate_patch_payload(
    *,
    proposal_file: Union[Path, str],
    out_dir: Union[Path, str] = Path(".agentmf/evolution/candidates"),
    write: bool = False,
) -> CandidatePatchResult:
    diagnostics = Diagnostics()
    proposal = _load_proposal(proposal_file, diagnostics)
    if proposal is None or diagnostics.has_errors:
        return CandidatePatchResult(diagnostics)

    candidate_files, unsupported = _candidate_source_files_for_proposal(proposal, diagnostics)
    if diagnostics.has_errors:
        return CandidatePatchResult(diagnostics)

    proposal_id = str(proposal.get("proposal_id", _sha256_json(proposal)))
    patch = _render_unified_patch(candidate_files)
    patch_status = "generated" if candidate_files else "skipped_unsupported_change"
    destination = Path(out_dir)
    patch_path = destination / f"{proposal_id}.patch"
    if write and patch_status == "generated":
        try:
            destination.mkdir(parents=True, exist_ok=True)
            patch_path.write_text(patch, encoding="utf-8")
        except OSError as exc:
            diagnostics.error("AMF228", f"could not write candidate patch: {patch_path}", "evo.patch.out_dir", str(exc))
            return CandidatePatchResult(diagnostics)

    return CandidatePatchResult(
        diagnostics,
        {
            "version": 1,
            "mode": "candidate_patch",
            "proposal_id": proposal_id,
            "patch_status": patch_status,
            "unsupported_changes": unsupported,
            "patch": None if write else patch,
            "paths": {"patch": str(patch_path)},
            "touched_files": [str(file["source_path"]) for file in candidate_files],
        },
    )


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


@dataclass
class OpenClawCuratorResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_openclaw_curator_payload(
    *,
    evidence_file: Union[Path, str],
    out_dir: Union[Path, str] = Path(".agentmf/evolution/candidates"),
    timestamp: Optional[str] = None,
    write: bool = False,
) -> OpenClawCuratorResult:
    diagnostics = Diagnostics()
    records = _load_evidence_records([evidence_file], diagnostics)
    if diagnostics.has_errors:
        return OpenClawCuratorResult(diagnostics)

    duplicate_records = [
        record
        for record in records
        if record.get("source") == "openclaw_import"
        and isinstance(record.get("summary"), dict)
        and record["summary"].get("duplicate_original_names")
    ]
    if not duplicate_records:
        return OpenClawCuratorResult(
            diagnostics,
            {"version": 1, "mode": "openclaw_curator", "proposal_count": 0, "proposal": None},
        )

    duplicate_original_names: Dict[str, Any] = {}
    modules = []
    for record in duplicate_records:
        summary = record["summary"]
        duplicate_original_names.update(summary.get("duplicate_original_names", {}))
        modules.extend(_module_refs_from_openclaw_record(record))

    proposal = create_skill_workshop_proposal_payload(
        title="Curate duplicate OpenClaw skills",
        evidence_files=[evidence_file],
        scope={"modules": sorted(set(modules)), "targets": []},
        changes=[
            {
                "type": "merge_duplicate_targets",
                "duplicate_original_names": duplicate_original_names,
                "reason": "OpenClaw import evidence reported duplicate original skill names.",
            }
        ],
        evaluation_commands=[
            "agentmf validate --file modules/openclaw/AgentMakefile",
            "agentmf benchmark harness --file modules/openclaw/AgentMakefile --case \"review code\"",
        ],
        out_dir=out_dir,
        timestamp=timestamp,
        write=write,
    )
    diagnostics.extend(proposal.diagnostics.items)
    return OpenClawCuratorResult(
        diagnostics,
        {
            "version": 1,
            "mode": "openclaw_curator",
            "proposal_count": 1 if proposal.payload else 0,
            "proposal": proposal.payload,
        },
    )


@dataclass
class DreamModeResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


DREAM_RECURRING_FAILURE_THRESHOLD = 2


def create_dream_mode_payload(
    *,
    evidence_dir: Union[Path, str] = Path(".agentmf/evolution/evidence"),
    out_dir: Union[Path, str] = Path(".agentmf/evolution/candidates"),
    timestamp: Optional[str] = None,
    write: bool = False,
) -> DreamModeResult:
    diagnostics = Diagnostics()
    evidence_root = Path(evidence_dir)
    evidence_files = sorted(evidence_root.glob("**/*.jsonl"))
    proposals = []
    proposals.extend(
        _dream_openclaw_duplicates(evidence_files, out_dir, timestamp, write, diagnostics)
    )
    proposals.extend(
        _dream_recurring_routing_gaps(evidence_files, out_dir, timestamp, write, diagnostics)
    )
    proposals.extend(
        _dream_missing_match_terms(evidence_files, out_dir, timestamp, write, diagnostics)
    )
    proposals.extend(
        _dream_drifted_permissions(evidence_files, out_dir, timestamp, write, diagnostics)
    )
    proposals.extend(
        _dream_trust_annotation(evidence_files, out_dir, timestamp, write, diagnostics)
    )
    proposals.extend(
        _dream_heavy_tool_warning(evidence_files, out_dir, timestamp, write, diagnostics)
    )
    proposals.extend(
        _dream_benchmark_case_suggester(evidence_files, out_dir, timestamp, write, diagnostics)
    )
    proposals.extend(
        _dream_category_resplit(evidence_files, out_dir, timestamp, write, diagnostics)
    )
    if diagnostics.has_errors:
        return DreamModeResult(diagnostics)
    return DreamModeResult(
        diagnostics,
        {
            "version": 1,
            "mode": "dream_mode_dry_run",
            "evidence_dir": str(evidence_root),
            "proposal_count": len(proposals),
            "proposals": proposals,
        },
    )


def _dream_openclaw_duplicates(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    proposals: list[Dict[str, Any]] = []
    for evidence_file in evidence_files:
        curator = create_openclaw_curator_payload(
            evidence_file=evidence_file,
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(curator.diagnostics.items)
        if curator.payload.get("proposal"):
            wrapper = curator.payload["proposal"]
            proposals.append(
                {
                    **wrapper,
                    "patch_status": _dream_patch_status(wrapper),
                }
            )
    return proposals


def _dream_recurring_routing_gaps(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Surface request fingerprints that have >=N failed plugin selections
    (selected_target is null) as investigate_recurring_routing_gap proposals.
    """
    failure_records: Dict[str, list[Dict[str, Any]]] = {}
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "plugin_payload":
                continue
            if record.get("selected_target"):
                continue
            fingerprint = record.get("request_fingerprint")
            if not isinstance(fingerprint, str) or not fingerprint:
                continue
            failure_records.setdefault(fingerprint, []).append(record)

    proposals: list[Dict[str, Any]] = []
    for fingerprint in sorted(failure_records):
        records = failure_records[fingerprint]
        if len(records) < DREAM_RECURRING_FAILURE_THRESHOLD:
            continue
        sample_event_ids = sorted(str(record.get("event_id", "")) for record in records)
        change = {
            "type": "investigate_recurring_routing_gap",
            "request_fingerprint": fingerprint,
            "failure_count": len(records),
            "sample_event_ids": sample_event_ids[:5],
        }
        result = create_skill_workshop_proposal_payload(
            title=f"Investigate recurring routing gap: {fingerprint[-12:]}",
            evidence_records=records,
            scope={"modules": [], "targets": []},
            changes=[change],
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append(
                {
                    **result.payload,
                    "patch_status": _dream_patch_status(result.payload),
                }
            )
    return proposals


def _dream_missing_match_terms(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Read user_feedback evidence (requests that should have routed elsewhere)
    and emit a combined proposal per (intended_module, intended_target):

    - update_match_terms adds the request texts (or user-supplied
      corrective_terms) to the intended target's match.user_intent so
      the corrective phrase is visible to the matcher.
    - prune_match_terms (when feedback names an actual_target) removes
      overly-broad single-word triggers from the actual_target that
      caused the false positive in the first place.

    The two changes ship in one proposal so the patch generator applies
    them atomically.
    """
    by_target: Dict[tuple[str, str], list[Dict[str, Any]]] = {}
    terms_by_target: Dict[tuple[str, str], list[str]] = {}
    actuals_by_target: Dict[tuple[str, str], Dict[str, list[str]]] = {}
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "user_feedback":
                continue
            summary = record.get("summary")
            if not isinstance(summary, dict):
                continue
            intended_module = summary.get("intended_module")
            intended_target = summary.get("intended_target")
            request_text = summary.get("request")
            if not intended_module or not intended_target or not request_text:
                continue
            key = (str(intended_module), str(intended_target))
            corrective = summary.get("corrective_terms") or []
            candidate_terms = [str(term) for term in corrective if isinstance(term, str)]
            if not candidate_terms:
                candidate_terms = [str(request_text)]
            by_target.setdefault(key, []).append(record)
            bucket = terms_by_target.setdefault(key, [])
            for term in candidate_terms:
                if term and term not in bucket:
                    bucket.append(term)
            actual_target = summary.get("actual_target")
            if isinstance(actual_target, str) and actual_target:
                actuals_by_target.setdefault(key, {}).setdefault(actual_target, []).append(str(request_text))

    proposals: list[Dict[str, Any]] = []
    for key in sorted(by_target):
        module_path, target_name = key
        records = by_target[key]
        terms = terms_by_target[key]
        changes: list[Dict[str, Any]] = [
            {
                "type": "update_match_terms",
                "module": module_path,
                "target": target_name,
                "add_terms": terms,
            }
        ]
        # Generate prune proposals for each actual_target that wrongly won.
        for actual_target, requests in sorted(actuals_by_target.get(key, {}).items()):
            broad_terms = _broad_match_terms_to_prune(Path(module_path), actual_target, requests)
            if broad_terms:
                changes.append(
                    {
                        "type": "prune_match_terms",
                        "module": module_path,
                        "target": actual_target,
                        "remove_terms": broad_terms,
                    }
                )

        result = create_skill_workshop_proposal_payload(
            title=f"Add match terms to {target_name}",
            evidence_records=records,
            scope={"modules": [module_path], "targets": [target_name]},
            changes=changes,
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append(
                {
                    **result.payload,
                    "patch_status": _dream_patch_status(result.payload),
                }
            )
    return proposals


def _broad_match_terms_to_prune(
    module_path: Path, target_name: str, requests: list[str]
) -> list[str]:
    """Identify single-word, short user_intent terms on `target_name` that
    substring-match one or more of `requests`. These are the broad
    triggers most likely to cause false positives — multi-word or longer
    phrases are left alone (they're presumed intentional).
    """
    try:
        data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
    except OSError:
        return []
    if not isinstance(data, dict):
        return []
    targets = data.get("targets")
    if not isinstance(targets, dict):
        return []
    target = targets.get(target_name)
    if not isinstance(target, dict):
        return []
    match = target.get("match")
    if not isinstance(match, dict):
        return []
    user_intent = match.get("user_intent")
    if isinstance(user_intent, str):
        user_intent = [user_intent]
    if not isinstance(user_intent, list):
        return []
    from agentmf.matcher import build_request_profile, match_term

    profiles = [build_request_profile(req) for req in requests]
    broad: list[str] = []
    for term in user_intent:
        term_text = str(term).strip()
        if not term_text:
            continue
        # Pruning criterion: short, single-word triggers ("Create",
        # "Edit", "Files") are the broad ones. Multi-word phrases stay.
        if " " in term_text or len(term_text) > 12:
            continue
        for profile in profiles:
            detail = match_term(profile, term_text)
            if detail and detail.get("score", 0) >= 95:
                if term_text not in broad:
                    broad.append(term_text)
                break
    return broad


DREAM_PERMISSION_DRIFT_THRESHOLD = 2


def _dream_drifted_permissions(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Surface recurring `denied_tool_calls` from benchmark evidence as
    `investigate_permission_drift` proposals — one per
    (target, tool, pattern) triple that appears in >=N records.

    Like recurring_routing_gap this detector flags evidence for human
    review rather than auto-patching: deciding to flip a deny to allow
    or update the permission guard is a security-sensitive choice, so
    the proposal stays "candidate + requires_review" and the patch
    class (`update_permission_guard`) is intentionally separate.
    """
    denials_by_triple: Dict[tuple[str, str, str], list[Dict[str, Any]]] = {}
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "benchmark":
                continue
            summary = record.get("summary")
            if not isinstance(summary, dict):
                continue
            denied = summary.get("denied_tool_calls")
            if not isinstance(denied, list):
                continue
            for entry in denied:
                if not isinstance(entry, dict):
                    continue
                target = entry.get("target")
                tool = entry.get("tool")
                pattern = entry.get("pattern")
                if not isinstance(target, str) or not isinstance(tool, str) or not isinstance(pattern, str):
                    continue
                key = (target, tool, pattern)
                denials_by_triple.setdefault(key, []).append(record)

    proposals: list[Dict[str, Any]] = []
    for key in sorted(denials_by_triple):
        records = denials_by_triple[key]
        if len(records) < DREAM_PERMISSION_DRIFT_THRESHOLD:
            continue
        target, tool, pattern = key
        sample_event_ids = sorted(str(record.get("event_id", "")) for record in records)
        change = {
            "type": "investigate_permission_drift",
            "target": target,
            "tool": tool,
            "pattern": pattern,
            "denial_count": len(records),
            "sample_event_ids": sample_event_ids[:5],
        }
        result = create_skill_workshop_proposal_payload(
            title=f"Investigate permission drift: {target} / {tool} / {pattern}",
            evidence_records=records,
            scope={"modules": [], "targets": [target]},
            changes=[change],
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append(
                {
                    **result.payload,
                    "patch_status": _dream_patch_status(result.payload),
                }
            )
    return proposals


CACHE_PATH_HINTS = ("/cache/", ".tmp/")
HEAVY_TOOL_KEYWORDS = ("sudo ", "rm -rf", "docker ", "kubectl ", "ssh ", "scp ", "curl http", "wget http")
DREAM_BENCHMARK_CASE_THRESHOLD = 3


def _modules_from_openclaw_evidence(evidence_files: list[Path], diagnostics: Diagnostics) -> list[Path]:
    """Collect unique module paths referenced by openclaw_import records."""
    seen: list[Path] = []
    seen_set: set[str] = set()
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "openclaw_import":
                continue
            summary = record.get("summary") or {}
            module_paths = summary.get("module_paths") if isinstance(summary, dict) else None
            if not isinstance(module_paths, list):
                continue
            for ref in module_paths:
                if not isinstance(ref, str) or ref in seen_set:
                    continue
                seen_set.add(ref)
                seen.append(Path(ref))
    return seen


def _dream_trust_annotation(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """For every module referenced by openclaw_import evidence, emit one
    proposal with `add_registry_metadata` changes annotating any skill
    whose `relative_source` lives under a cache or scratch path. Existing
    `registry_metadata.cache_derived` annotations are left alone so reruns
    are idempotent.
    """
    proposals: list[Dict[str, Any]] = []
    module_paths = _modules_from_openclaw_evidence(evidence_files, diagnostics)
    for module_path in module_paths:
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if not isinstance(data, dict):
            continue
        skills = data.get("skills") or {}
        if not isinstance(skills, dict):
            continue
        changes: list[Dict[str, Any]] = []
        for skill_name, skill in skills.items():
            if not isinstance(skill, dict):
                continue
            impl = skill.get("implementation") or {}
            if not isinstance(impl, dict):
                continue
            rel = impl.get("relative_source")
            if not isinstance(rel, str):
                continue
            if not any(hint in rel for hint in CACHE_PATH_HINTS):
                continue
            existing = impl.get("registry_metadata") if isinstance(impl.get("registry_metadata"), dict) else {}
            if existing.get("cache_derived"):
                continue
            changes.append(
                {
                    "type": "add_registry_metadata",
                    "module": str(module_path),
                    "skill": skill_name,
                    "metadata": {
                        "cache_derived": True,
                        "source_path": rel,
                        "annotated_by": "dream.trust_annotation",
                    },
                }
            )
        if not changes:
            continue
        result = create_skill_workshop_proposal_payload(
            title=f"Annotate cache-derived skills in {module_path.name}",
            evidence_records=[],
            scope={"modules": [str(module_path)], "targets": []},
            changes=changes,
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append({**result.payload, "patch_status": _dream_patch_status(result.payload)})
    return proposals


def _dream_heavy_tool_warning(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Scan skills in modules referenced by openclaw_import evidence for
    description or match.user_intent containing risky-tool keywords (sudo,
    rm -rf, docker, kubectl, ssh, scp, curl http*, wget http*). Each
    flagged skill becomes its own investigate_heavy_tool_usage proposal —
    intentionally not a patch, since deciding to gate or rewrite is a
    security-sensitive call best left to a reviewer.
    """
    proposals: list[Dict[str, Any]] = []
    module_paths = _modules_from_openclaw_evidence(evidence_files, diagnostics)
    for module_path in module_paths:
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if not isinstance(data, dict):
            continue
        skills = data.get("skills") or {}
        if not isinstance(skills, dict):
            continue
        for skill_name, skill in skills.items():
            if not isinstance(skill, dict):
                continue
            tokens: list[str] = []
            blob_parts: list[str] = []
            description = skill.get("description")
            if isinstance(description, str):
                blob_parts.append(description)
            match = skill.get("match")
            if isinstance(match, dict):
                user_intent = match.get("user_intent")
                if isinstance(user_intent, list):
                    blob_parts.extend(str(term) for term in user_intent)
                elif isinstance(user_intent, str):
                    blob_parts.append(user_intent)
            haystack = " ".join(blob_parts).lower()
            for keyword in HEAVY_TOOL_KEYWORDS:
                if keyword in haystack:
                    tokens.append(keyword.strip())
            if not tokens:
                continue
            change = {
                "type": "investigate_heavy_tool_usage",
                "module": str(module_path),
                "skill": skill_name,
                "matched_tokens": sorted(set(tokens)),
            }
            result = create_skill_workshop_proposal_payload(
                title=f"Heavy tool usage in {skill_name}",
                evidence_records=[],
                scope={"modules": [str(module_path)], "targets": []},
                changes=[change],
                evaluation_commands=[],
                out_dir=out_dir,
                timestamp=timestamp,
                write=write,
            )
            diagnostics.extend(result.diagnostics.items)
            if result.payload:
                proposals.append({**result.payload, "patch_status": _dream_patch_status(result.payload)})
    return proposals


def _dream_benchmark_case_suggester(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """For each `selected_target` that the plugin_payload evidence shows
    >=N times, propose an add_benchmark_case change so the route gets a
    permanent regression test. The target's module is resolved by
    scanning modules referenced in any openclaw_import evidence in the
    same evidence set; targets we can't locate are skipped.
    """
    selections_by_target: Dict[str, list[Dict[str, Any]]] = {}
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "plugin_payload":
                continue
            target = record.get("selected_target")
            if not isinstance(target, str) or not target:
                continue
            selections_by_target.setdefault(target, []).append(record)

    if not selections_by_target:
        return []

    target_to_module: Dict[str, Path] = {}
    for module_path in _modules_from_openclaw_evidence(evidence_files, diagnostics):
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        targets = data.get("targets") if isinstance(data.get("targets"), dict) else {}
        for target_name in targets:
            if target_name not in target_to_module:
                target_to_module[target_name] = module_path

    proposals: list[Dict[str, Any]] = []
    for target in sorted(selections_by_target):
        records = selections_by_target[target]
        if len(records) < DREAM_BENCHMARK_CASE_THRESHOLD:
            continue
        module_path = target_to_module.get(target)
        if module_path is None:
            continue
        # Most-frequent request for the case instruction.
        request_counts: Dict[str, int] = {}
        for record in records:
            summary = record.get("summary") or {}
            request = None
            if isinstance(summary, dict):
                request = summary.get("request")
            if not isinstance(request, str):
                # _summary_for_source("plugin_payload") doesn't store
                # request; fall back to record-level fingerprint hash
                # so we still produce a stable case id.
                request = record.get("request_fingerprint") or ""
            request_counts[request] = request_counts.get(request, 0) + 1
        best_request, _ = max(request_counts.items(), key=lambda kv: kv[1])
        change = {
            "type": "add_benchmark_case",
            "module": str(module_path),
            "target": target,
            "case": {
                "id": f"popular-{_sha256_text(target)[7:19]}",
                "instruction": best_request,
                "expected_target": target,
            },
        }
        result = create_skill_workshop_proposal_payload(
            title=f"Add benchmark case for popular route {target}",
            evidence_records=records,
            scope={"modules": [str(module_path)], "targets": [target]},
            changes=[change],
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append({**result.payload, "patch_status": _dream_patch_status(result.payload)})
    return proposals


DREAM_CATEGORY_RESPLIT_THRESHOLD = 10


def _dream_category_resplit(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Suggest splitting an already-imported module when many of its
    skills cluster under a common second-level path segment in their
    `implementation.relative_source`. Each sub-category that breaches the
    threshold becomes one `investigate_category_resplit` proposal — a
    flag for human review, not an automatic patch (the importer's
    scan-time category split runs first; this detector fires on the
    re-split case where the imported tree itself contains rich sub-
    structure).
    """
    proposals: list[Dict[str, Any]] = []
    for module_path in _modules_from_openclaw_evidence(evidence_files, diagnostics):
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if not isinstance(data, dict):
            continue
        skills = data.get("skills") or {}
        if not isinstance(skills, dict):
            continue
        groups: Dict[str, list[str]] = {}
        for skill_name, skill in skills.items():
            if not isinstance(skill, dict):
                continue
            impl = skill.get("implementation") or {}
            rel = impl.get("relative_source") if isinstance(impl, dict) else None
            if not isinstance(rel, str):
                continue
            segments = [segment for segment in rel.split("/") if segment]
            # Need at least <category>/<sub-category>/... to split.
            if len(segments) < 3:
                continue
            sub_category = segments[1]
            if not sub_category:
                continue
            groups.setdefault(sub_category, []).append(skill_name)
        for sub_category in sorted(groups):
            members = groups[sub_category]
            if len(members) < DREAM_CATEGORY_RESPLIT_THRESHOLD:
                continue
            change = {
                "type": "investigate_category_resplit",
                "module": str(module_path),
                "sub_category": sub_category,
                "skill_count": len(members),
                "sample_skills": sorted(members)[:5],
            }
            result = create_skill_workshop_proposal_payload(
                title=f"Investigate re-splitting {module_path.name} into sub-module {sub_category}",
                evidence_records=[],
                scope={"modules": [str(module_path)], "targets": []},
                changes=[change],
                evaluation_commands=[],
                out_dir=out_dir,
                timestamp=timestamp,
                write=write,
            )
            diagnostics.extend(result.diagnostics.items)
            if result.payload:
                proposals.append({**result.payload, "patch_status": _dream_patch_status(result.payload)})
    return proposals


def _dream_patch_status(wrapper: Dict[str, Any]) -> str:
    """Classify whether a dream-emitted proposal would generate a patch.

    `wrapper` is the SkillWorkshopProposalResult.payload dict, which holds
    the actual proposal core under "proposal". Returns "would_generate_patch"
    if any change type is in SUPPORTED_PATCH_TYPES, otherwise
    "skipped_unsupported_change".
    """
    proposal = wrapper.get("proposal")
    if not isinstance(proposal, dict):
        return "skipped_unsupported_change"
    changes = proposal.get("changes")
    if not isinstance(changes, list):
        return "skipped_unsupported_change"
    for change in changes:
        if isinstance(change, dict) and change.get("type") in SUPPORTED_PATCH_TYPES:
            return "would_generate_patch"
    return "skipped_unsupported_change"


def _unwrap_source_payload(source: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if source == "openclaw_import" and isinstance(payload.get("openclaw_import"), dict):
        return payload["openclaw_import"]
    if source == "plugin_payload" and isinstance(payload.get("plugin_payload"), dict):
        return payload["plugin_payload"]
    return payload


def _summary_for_source(source: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if source == "openclaw_import":
        evidence = payload.get("curator_evidence")
        if isinstance(evidence, dict):
            return {
                "skill_count": evidence.get("skill_count", 0),
                "category_count": evidence.get("category_count", 0),
                "categories": evidence.get("categories", {}),
                "duplicate_original_names": evidence.get("duplicate_original_names", {}),
                "module_paths": evidence.get("module_paths", []),
            }
    if source == "plugin_payload":
        return {
            "selected_targets": payload.get("selected_targets", []),
            "selected_skills": payload.get("selected_skills", []),
            "selected_pipeline": payload.get("selected_pipeline", {}),
        }
    if source == "benchmark":
        return {
            "cases": payload.get("cases", []),
            "summary": payload.get("summary", payload.get("report", {})),
        }
    if source == "user_feedback":
        return {
            "request": payload.get("request"),
            "intended_module": payload.get("intended_module"),
            "intended_target": payload.get("intended_target"),
            "intended_skill": payload.get("intended_skill"),
            "actual_target": payload.get("actual_target"),
            "corrective_terms": list(payload.get("corrective_terms") or []),
            "comment": payload.get("comment"),
        }
    return {"payload": payload}


def _artifact_refs_for_source(source: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if source == "openclaw_import":
        refs: Dict[str, Any] = {}
        root_path = payload.get("root_path")
        if root_path:
            refs["root_agentmakefile"] = str(root_path)
        evidence = payload.get("curator_evidence")
        if isinstance(evidence, dict) and evidence.get("module_paths"):
            refs["module_paths"] = evidence["module_paths"]
        return refs
    if source == "user_feedback":
        refs = {}
        if payload.get("intended_module"):
            refs["intended_module"] = str(payload["intended_module"])
        if payload.get("intended_target"):
            refs["intended_target"] = str(payload["intended_target"])
        return refs
    return {}


def _request_fingerprint(payload: Dict[str, Any]) -> Optional[str]:
    request = payload.get("request")
    if request is None:
        selection = payload.get("selection")
        if isinstance(selection, dict):
            request = selection.get("request")
    if request is None:
        return None
    return _sha256_text(str(request))


def _selected_target(payload: Dict[str, Any]) -> Optional[str]:
    targets = payload.get("selected_targets")
    if isinstance(targets, list) and targets:
        return str(targets[0])
    selected = payload.get("selected_target")
    if selected is not None:
        return str(selected)
    return None


def _selected_skills(payload: Dict[str, Any]) -> list[str]:
    skills = payload.get("selected_skills")
    if not isinstance(skills, list):
        return []
    return [str(skill) for skill in skills]


def _selection_trace_hash(payload: Dict[str, Any]) -> Optional[str]:
    trace = payload.get("selection_trace")
    if trace is None:
        return None
    return _sha256_json(trace)


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key)
            if _secret_key(key_text):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    if isinstance(value, str) and _secret_value(value):
        return "[REDACTED]"
    return value


def _secret_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(
        marker in lowered
        for marker in [
            "api_key",
            "apikey",
            "authorization",
            "password",
            "private_key",
            "secret",
            "token",
        ]
    )


def _secret_value(value: str) -> bool:
    if value.startswith("sk-"):
        return True
    if re.search(r"(?i)\bbearer\s+[A-Za-z0-9._-]+", value):
        return True
    if "-----BEGIN" in value and "PRIVATE KEY-----" in value:
        return True
    return False


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "evidence"


def _load_evidence_records(
    evidence_files: list[Union[Path, str]],
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    records: list[Dict[str, Any]] = []
    for evidence_file in evidence_files:
        path = Path(evidence_file)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            diagnostics.error("AMF223", f"could not read evidence file: {path}", "evo.proposal.evidence_file", str(exc))
            continue
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                diagnostics.error(
                    "AMF223",
                    f"invalid evidence JSONL record in {path}:{line_number}",
                    "evo.proposal.evidence_file",
                    str(exc),
                )
                continue
            if not isinstance(record, dict):
                diagnostics.error(
                    "AMF223",
                    f"evidence JSONL record must be an object in {path}:{line_number}",
                    "evo.proposal.evidence_file",
                )
                continue
            records.append(record)
    return records


def _evidence_ref(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "event_id": str(record.get("event_id", _sha256_json(record))),
        "source": str(record.get("source", "unknown")),
        "reason": _evidence_reason(record),
    }


def _evidence_reason(record: Dict[str, Any]) -> str:
    source = str(record.get("source", "unknown"))
    summary = record.get("summary")
    if source == "openclaw_import" and isinstance(summary, dict):
        return (
            "OpenClaw import evidence with "
            f"{summary.get('skill_count', 0)} skills across "
            f"{len(summary.get('categories', {}))} categories"
        )
    if source == "plugin_payload" and isinstance(summary, dict):
        targets = summary.get("selected_targets", [])
        skills = summary.get("selected_skills", [])
        return f"plugin selected {len(targets)} targets and {len(skills)} skills"
    return f"{source} evidence record"


def _normalize_scope(scope: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "modules": [str(module) for module in scope.get("modules", [])],
        "targets": [str(target) for target in scope.get("targets", [])],
    }


def _load_proposal(proposal_file: Union[Path, str], diagnostics: Diagnostics) -> Optional[Dict[str, Any]]:
    path = Path(proposal_file)
    try:
        proposal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        diagnostics.error("AMF225", f"could not read proposal file: {path}", "evo.proposal_file", str(exc))
        return None
    if not isinstance(proposal, dict):
        diagnostics.error("AMF225", f"proposal file must contain a JSON object: {path}", "evo.proposal_file")
        return None
    return proposal


def _candidate_source_files_for_proposal(
    proposal: Dict[str, Any],
    diagnostics: Diagnostics,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    source_map: Dict[Path, Dict[str, Any]] = {}
    unsupported = []
    for change in proposal.get("changes", []):
        if not isinstance(change, dict):
            unsupported.append({"type": "unknown", "reason": "change is not an object"})
            continue
        change_type = change.get("type")
        if change_type not in SUPPORTED_PATCH_TYPES:
            unsupported.append({"type": change_type or "unknown", "reason": "patch class is not implemented yet"})
            continue
        if change_type == "update_match_terms":
            _apply_update_match_terms_change(change, proposal, source_map, diagnostics)
        elif change_type == "merge_duplicate_targets":
            _apply_merge_duplicate_targets_change(change, proposal, source_map, diagnostics)
        elif change_type == "prune_match_terms":
            _apply_prune_match_terms_change(change, proposal, source_map, diagnostics)
        elif change_type == "add_target":
            _apply_add_target_change(change, proposal, source_map, diagnostics)
        elif change_type == "add_dependency":
            _apply_add_dependency_change(change, proposal, source_map, diagnostics)
        elif change_type == "deprecate_skill":
            _apply_deprecate_skill_change(change, proposal, source_map, diagnostics)
        elif change_type == "add_registry_metadata":
            _apply_add_registry_metadata_change(change, proposal, source_map, diagnostics)
        elif change_type == "add_benchmark_case":
            _apply_add_benchmark_case_change(change, proposal, source_map, diagnostics)
        elif change_type == "update_permission_guard":
            _apply_update_permission_guard_change(change, proposal, source_map, diagnostics)
        elif change_type == "split_module":
            _apply_split_module_change(change, proposal, source_map, diagnostics)

    candidate_files = []
    for source_path, record in source_map.items():
        candidate_content = yaml.safe_dump(record["data"], sort_keys=False)
        candidate_files.append(
            {
                "source_path": source_path,
                "original_content": record["original_content"],
                "candidate_content": candidate_content,
            }
        )
    return candidate_files, unsupported


def _apply_update_match_terms_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    module_path = _change_module_path(change, proposal)
    target_name = change.get("target") or _first(proposal.get("scope", {}).get("targets", []))
    terms = change.get("add_terms") or change.get("terms") or []
    if not module_path or not target_name or not isinstance(terms, list):
        diagnostics.error(
            "AMF226",
            "update_match_terms requires module, target, and add_terms",
            "evo.patch.changes",
        )
        return
    source_path = Path(str(module_path))
    record = _load_module_record(source_path, source_map, diagnostics)
    if record is None:
        return

    data = record["data"]
    targets = data.setdefault("targets", {})
    if target_name not in targets:
        diagnostics.error("AMF227", f"proposal target not found: {target_name}", "evo.patch.target")
        return
    target = targets[target_name]
    match = target.setdefault("match", {})
    user_intent = match.setdefault("user_intent", [])
    if isinstance(user_intent, str):
        user_intent = [user_intent]
    if not isinstance(user_intent, list):
        diagnostics.error("AMF226", f"target match.user_intent must be a list: {target_name}", "evo.patch.target")
        return
    for term in terms:
        term_text = str(term)
        if term_text and term_text not in user_intent:
            user_intent.append(term_text)
    match["user_intent"] = user_intent


def _apply_prune_match_terms_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Mirror of update_match_terms: remove specified terms from a target's
    match.user_intent. Used when an overly-broad term (e.g. a stray single
    word) is causing false-positive routing.
    """
    module_path = _change_module_path(change, proposal)
    target_name = change.get("target") or _first(proposal.get("scope", {}).get("targets", []))
    terms = change.get("remove_terms") or change.get("terms") or []
    if not module_path or not target_name or not isinstance(terms, list):
        diagnostics.error(
            "AMF226",
            "prune_match_terms requires module, target, and remove_terms",
            "evo.patch.changes",
        )
        return
    source_path = Path(str(module_path))
    record = _load_module_record(source_path, source_map, diagnostics)
    if record is None:
        return

    data = record["data"]
    targets = data.get("targets") or {}
    if target_name not in targets:
        diagnostics.error("AMF227", f"proposal target not found: {target_name}", "evo.patch.target")
        return
    target = targets[target_name]
    match = target.get("match") if isinstance(target.get("match"), dict) else None
    if match is None:
        return
    user_intent = match.get("user_intent")
    if isinstance(user_intent, str):
        user_intent = [user_intent]
    if not isinstance(user_intent, list):
        diagnostics.error("AMF226", f"target match.user_intent must be a list: {target_name}", "evo.patch.target")
        return
    remove_set = {str(term) for term in terms}
    match["user_intent"] = [term for term in user_intent if str(term) not in remove_set]


def _apply_add_target_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Insert a brand-new target into a module's targets dict."""
    module_path = _change_module_path(change, proposal)
    target_name = change.get("target") or change.get("name")
    definition = change.get("definition")
    if not module_path or not target_name or not isinstance(definition, dict):
        diagnostics.error(
            "AMF226",
            "add_target requires module, target, and definition",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    data = record["data"]
    targets = data.setdefault("targets", {})
    if target_name in targets:
        diagnostics.error(
            "AMF233",
            f"add_target refuses to overwrite existing target: {target_name}",
            "evo.patch.target",
        )
        return
    targets[target_name] = dict(definition)


def _apply_add_dependency_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Append dep edges to an existing target's `deps` list."""
    module_path = _change_module_path(change, proposal)
    target_name = change.get("target") or _first(proposal.get("scope", {}).get("targets", []))
    add_deps = change.get("add_deps") or change.get("deps") or []
    if not module_path or not target_name or not isinstance(add_deps, list):
        diagnostics.error(
            "AMF226",
            "add_dependency requires module, target, and add_deps",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    targets = record["data"].setdefault("targets", {})
    if target_name not in targets:
        diagnostics.error("AMF227", f"proposal target not found: {target_name}", "evo.patch.target")
        return
    target = targets[target_name]
    deps = target.setdefault("deps", [])
    if not isinstance(deps, list):
        diagnostics.error("AMF226", f"target deps must be a list: {target_name}", "evo.patch.target")
        return
    for dep in add_deps:
        dep_text = str(dep)
        if dep_text and dep_text not in deps:
            deps.append(dep_text)


def _apply_deprecate_skill_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Annotate a skill as deprecated (implementation.deprecated=true plus
    optional reason). Does not delete; preserves auditability.
    """
    module_path = _change_module_path(change, proposal)
    skill_name = change.get("skill")
    reason = change.get("reason")
    replaced_by = change.get("replaced_by")
    if not module_path or not skill_name:
        diagnostics.error(
            "AMF226",
            "deprecate_skill requires module and skill",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    skills = record["data"].get("skills") or {}
    if not isinstance(skills, dict) or skill_name not in skills:
        diagnostics.error("AMF227", f"proposal skill not found: {skill_name}", "evo.patch.skill")
        return
    skill = skills[skill_name]
    impl = skill.setdefault("implementation", {})
    if not isinstance(impl, dict):
        diagnostics.error("AMF226", f"skill implementation must be a mapping: {skill_name}", "evo.patch.skill")
        return
    impl["deprecated"] = True
    if reason:
        impl["deprecation_reason"] = str(reason)
    if replaced_by:
        impl["replaced_by"] = str(replaced_by)


def _apply_add_registry_metadata_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Attach registry-source metadata (origin, version, signed-by, …) to a
    skill so downstream tools can audit provenance.
    """
    module_path = _change_module_path(change, proposal)
    skill_name = change.get("skill")
    metadata = change.get("metadata")
    if not module_path or not skill_name or not isinstance(metadata, dict):
        diagnostics.error(
            "AMF226",
            "add_registry_metadata requires module, skill, and metadata",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    skills = record["data"].get("skills") or {}
    if not isinstance(skills, dict) or skill_name not in skills:
        diagnostics.error("AMF227", f"proposal skill not found: {skill_name}", "evo.patch.skill")
        return
    skill = skills[skill_name]
    impl = skill.setdefault("implementation", {})
    if not isinstance(impl, dict):
        diagnostics.error("AMF226", f"skill implementation must be a mapping: {skill_name}", "evo.patch.skill")
        return
    registry = impl.setdefault("registry_metadata", {})
    if not isinstance(registry, dict):
        diagnostics.error("AMF226", f"skill registry_metadata must be a mapping: {skill_name}", "evo.patch.skill")
        return
    registry.update(metadata)


def _apply_add_benchmark_case_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Append a benchmark case to a target's output_schema.benchmark_cases
    list (kept inside the free-form output_schema dict so we don't need
    a strict-model expansion).
    """
    module_path = _change_module_path(change, proposal)
    target_name = change.get("target") or _first(proposal.get("scope", {}).get("targets", []))
    case = change.get("case")
    if not module_path or not target_name or not isinstance(case, dict):
        diagnostics.error(
            "AMF226",
            "add_benchmark_case requires module, target, and case",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    targets = record["data"].setdefault("targets", {})
    if target_name not in targets:
        diagnostics.error("AMF227", f"proposal target not found: {target_name}", "evo.patch.target")
        return
    target = targets[target_name]
    output_schema = target.setdefault("output_schema", {})
    if not isinstance(output_schema, dict):
        diagnostics.error("AMF226", f"target output_schema must be a mapping: {target_name}", "evo.patch.target")
        return
    cases = output_schema.setdefault("benchmark_cases", [])
    if not isinstance(cases, list):
        diagnostics.error("AMF226", f"benchmark_cases must be a list: {target_name}", "evo.patch.target")
        return
    if case not in cases:
        cases.append(dict(case))


def _apply_update_permission_guard_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Set permissions[tool][pattern] = action (allow / ask / deny)."""
    module_path = _change_module_path(change, proposal)
    tool = change.get("tool")
    pattern = change.get("pattern")
    action = change.get("action")
    if not module_path or not tool or not pattern or action not in {"allow", "ask", "deny"}:
        diagnostics.error(
            "AMF226",
            "update_permission_guard requires module, tool, pattern, and action (allow|ask|deny)",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    data = record["data"]
    permissions = data.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        diagnostics.error("AMF226", "module permissions must be a mapping", "evo.patch.module")
        return
    # Support both flat (`permissions.<tool>.<pattern>`) and nested
    # (`permissions.rules.<tool>.<pattern>`) layouts. Prefer the layout
    # already present in the file; default to flat for new entries.
    rules = permissions.get("rules") if isinstance(permissions.get("rules"), dict) else None
    bucket = rules if rules is not None else permissions
    tool_rules = bucket.setdefault(tool, {})
    if not isinstance(tool_rules, dict):
        diagnostics.error("AMF226", f"permissions for tool must be a mapping: {tool}", "evo.patch.permissions")
        return
    tool_rules[pattern] = action


def _apply_split_module_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Move named skills + targets from a source module into a new module
    file. The new module's record is added to source_map with empty
    original_content so the candidate-patch / evaluate steps treat it
    as a fresh file write.
    """
    source_module = change.get("source_module")
    target_module = change.get("target_module")
    move_skills = change.get("skills") or []
    move_targets = change.get("targets") or []
    if not source_module or not target_module or not isinstance(move_skills, list) or not isinstance(move_targets, list):
        diagnostics.error(
            "AMF226",
            "split_module requires source_module, target_module, skills, and targets",
            "evo.patch.changes",
        )
        return
    if not move_skills and not move_targets:
        diagnostics.error(
            "AMF226",
            "split_module requires at least one skill or target to move",
            "evo.patch.changes",
        )
        return
    source_path = Path(str(source_module))
    target_path = Path(str(target_module))
    if source_path == target_path:
        diagnostics.error(
            "AMF226",
            "split_module source and target must differ",
            "evo.patch.changes",
        )
        return

    source_record = _load_module_record(source_path, source_map, diagnostics)
    if source_record is None:
        return

    target_record = source_map.get(target_path)
    if target_record is None:
        if target_path.exists():
            target_record = _load_module_record(target_path, source_map, diagnostics)
            if target_record is None:
                return
        else:
            target_record = {
                "original_content": "",
                "data": {"version": source_record["data"].get("version", "0.1"), "skills": {}, "targets": {}},
            }
            source_map[target_path] = target_record

    source_skills = source_record["data"].get("skills") or {}
    source_targets = source_record["data"].get("targets") or {}
    new_skills = target_record["data"].setdefault("skills", {})
    new_targets = target_record["data"].setdefault("targets", {})

    for skill_name in move_skills:
        if skill_name not in source_skills:
            continue
        new_skills[skill_name] = source_skills[skill_name]
        del source_skills[skill_name]
    for target_name in move_targets:
        if target_name not in source_targets:
            continue
        new_targets[target_name] = source_targets[target_name]
        del source_targets[target_name]


def _apply_merge_duplicate_targets_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    duplicate_names = change.get("duplicate_original_names")
    if not isinstance(duplicate_names, dict) or not duplicate_names:
        diagnostics.error(
            "AMF226",
            "merge_duplicate_targets requires duplicate_original_names mapping",
            "evo.patch.changes",
        )
        return

    module_paths = change.get("modules") or proposal.get("scope", {}).get("modules", [])
    if change.get("module"):
        module_paths = [change["module"]]
    if not module_paths:
        diagnostics.error(
            "AMF226",
            "merge_duplicate_targets requires at least one module in scope or change",
            "evo.patch.changes",
        )
        return

    records = []
    for raw_path in module_paths:
        source_path = Path(str(raw_path))
        record = _load_module_record(source_path, source_map, diagnostics)
        if record is not None:
            records.append(record)
    _merge_duplicates_across_modules(records, duplicate_names)


def _load_module_record(
    source_path: Path,
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> Optional[Dict[str, Any]]:
    record = source_map.get(source_path)
    if record is not None:
        return record
    try:
        original_content = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error(
            "AMF226",
            f"could not read AgentMakefile source: {source_path}",
            "evo.patch.module",
            str(exc),
        )
        return None
    data = yaml.safe_load(original_content) or {}
    if not isinstance(data, dict):
        diagnostics.error("AMF226", f"AgentMakefile source must be a mapping: {source_path}", "evo.patch.module")
        return None
    record = {"original_content": original_content, "data": data}
    source_map[source_path] = record
    return record


def _merge_duplicates_across_modules(
    records: List[Dict[str, Any]],
    duplicate_names: Dict[str, Any],
) -> None:
    """Build a global relative_source -> (module_data, skill_name) map across
    every loaded module in scope, then merge each duplicate into its primary.

    Handles same-module and cross-module dup groups uniformly: the primary's
    `match.user_intent` and `merged_duplicates` are appended in whichever
    module holds the primary, and the duplicate is removed (with its
    `skill.<name>` target and `metadata.skill_count`) from whichever module
    holds it.
    """
    rel_to_entry: Dict[str, tuple[Dict[str, Any], str]] = {}
    for record in records:
        data = record["data"]
        skills = data.get("skills")
        if not isinstance(skills, dict):
            continue
        for skill_name, skill in skills.items():
            if not isinstance(skill, dict):
                continue
            impl = skill.get("implementation")
            if not isinstance(impl, dict):
                continue
            rel = impl.get("relative_source")
            if isinstance(rel, str):
                rel_to_entry[rel] = (data, skill_name)

    for original_name, paths in duplicate_names.items():
        if not isinstance(paths, list) or len(paths) < 2:
            continue
        primary_entry = rel_to_entry.get(str(paths[0]))
        if primary_entry is None:
            continue
        primary_data, primary_skill_name = primary_entry
        primary_skills = primary_data.get("skills") if isinstance(primary_data.get("skills"), dict) else {}
        primary_skill = primary_skills.get(primary_skill_name)
        if not isinstance(primary_skill, dict):
            continue
        primary_targets = primary_data.get("targets") if isinstance(primary_data.get("targets"), dict) else {}
        primary_target_name = f"skill.{primary_skill_name}"
        primary_target = primary_targets.get(primary_target_name) if isinstance(primary_targets.get(primary_target_name), dict) else None

        for duplicate_path in paths[1:]:
            duplicate_entry = rel_to_entry.get(str(duplicate_path))
            if duplicate_entry is None:
                continue
            duplicate_data, duplicate_skill_name = duplicate_entry
            if duplicate_data is primary_data and duplicate_skill_name == primary_skill_name:
                continue
            duplicate_skills = duplicate_data.get("skills") if isinstance(duplicate_data.get("skills"), dict) else {}
            duplicate_skill = duplicate_skills.get(duplicate_skill_name)
            if not isinstance(duplicate_skill, dict):
                continue
            _merge_user_intent(primary_skill, duplicate_skill)
            duplicate_targets = duplicate_data.get("targets") if isinstance(duplicate_data.get("targets"), dict) else {}
            duplicate_target_name = f"skill.{duplicate_skill_name}"
            duplicate_target = duplicate_targets.get(duplicate_target_name) if isinstance(duplicate_targets.get(duplicate_target_name), dict) else None
            if primary_target is not None and duplicate_target is not None:
                _merge_user_intent(primary_target, duplicate_target)
            _record_merged_duplicate(primary_skill, duplicate_skill_name, duplicate_skill, str(original_name))
            del duplicate_skills[duplicate_skill_name]
            if duplicate_target_name in duplicate_targets:
                del duplicate_targets[duplicate_target_name]
            duplicate_metadata = duplicate_data.get("metadata")
            if isinstance(duplicate_metadata, dict):
                count = duplicate_metadata.get("skill_count")
                if isinstance(count, int):
                    duplicate_metadata["skill_count"] = max(0, count - 1)


def _merge_user_intent(primary: Dict[str, Any], duplicate: Dict[str, Any]) -> None:
    duplicate_match = duplicate.get("match")
    if not isinstance(duplicate_match, dict):
        return
    duplicate_intent = duplicate_match.get("user_intent")
    if isinstance(duplicate_intent, str):
        duplicate_intent = [duplicate_intent]
    if not isinstance(duplicate_intent, list):
        return
    primary_match = primary.setdefault("match", {})
    if not isinstance(primary_match, dict):
        return
    primary_intent = primary_match.get("user_intent")
    if isinstance(primary_intent, str):
        primary_intent = [primary_intent]
    if not isinstance(primary_intent, list):
        primary_intent = []
    for term in duplicate_intent:
        term_text = str(term)
        if term_text and term_text not in primary_intent:
            primary_intent.append(term_text)
    primary_match["user_intent"] = primary_intent


def _record_merged_duplicate(
    primary_skill: Dict[str, Any],
    duplicate_name: str,
    duplicate_skill: Dict[str, Any],
    original_name: str,
) -> None:
    impl = primary_skill.setdefault("implementation", {})
    if not isinstance(impl, dict):
        return
    merged = impl.setdefault("merged_duplicates", [])
    if not isinstance(merged, list):
        return
    dup_impl = duplicate_skill.get("implementation") if isinstance(duplicate_skill.get("implementation"), dict) else {}
    merged.append(
        {
            "skill": duplicate_name,
            "source": dup_impl.get("source"),
            "relative_source": dup_impl.get("relative_source"),
            "original_name": dup_impl.get("original_name") or original_name,
        }
    )


def _change_module_path(change: Dict[str, Any], proposal: Dict[str, Any]) -> Optional[str]:
    module = change.get("module")
    if module:
        return str(module)
    return _first(proposal.get("scope", {}).get("modules", []))


def _first(values: Any) -> Optional[str]:
    if isinstance(values, list) and values:
        return str(values[0])
    return None


def _render_unified_patch(candidate_files: list[Dict[str, Any]]) -> str:
    chunks = []
    for candidate in candidate_files:
        source = str(candidate["source_path"])
        diff = difflib.unified_diff(
            candidate["original_content"].splitlines(),
            candidate["candidate_content"].splitlines(),
            fromfile=source,
            tofile=f"{source} (candidate)",
            lineterm="",
        )
        chunks.extend(diff)
    return "\n".join(chunks) + ("\n" if chunks else "")


def _workspace_destination(workspace: Path, source_path: Path, used: Optional[set] = None) -> Path:
    if source_path.is_absolute():
        parts = source_path.parts
        base = Path(*parts[-2:]) if len(parts) >= 2 else Path(parts[-1])
    else:
        base = source_path
    candidate = workspace / base
    if used is None or candidate not in used:
        return candidate
    stem = candidate.stem or candidate.name
    suffix = candidate.suffix
    parent = candidate.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if candidate not in used:
            return candidate
        counter += 1


def _module_refs_from_openclaw_record(record: Dict[str, Any]) -> list[str]:
    summary = record.get("summary", {})
    module_paths = summary.get("module_paths", []) if isinstance(summary, dict) else []
    root_agentmakefile = record.get("artifact_refs", {}).get("root_agentmakefile")
    if not root_agentmakefile:
        return [str(path) for path in module_paths]
    root_parent = Path(str(root_agentmakefile)).parent
    return [str(root_parent / str(path)) for path in module_paths]
