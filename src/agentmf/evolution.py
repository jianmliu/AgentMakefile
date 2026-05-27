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
    evidence_files: list[Union[Path, str]],
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

    evidence_records = _load_evidence_records(evidence_files, diagnostics)
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
    if write:
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            for candidate in candidate_files:
                destination = _workspace_destination(workspace, candidate["source_path"])
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
                    "path": str(_workspace_destination(workspace, candidate["source_path"])),
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

    status = "passed"
    if unsupported and not candidate_records:
        status = "skipped_unsupported_change"
    if any(result["status"] == "failed" for result in validation_results):
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
                "commands": proposal.get("evaluation", {}).get("commands", []),
                "unsupported_changes": unsupported,
            },
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


def create_dream_mode_payload(
    *,
    evidence_dir: Union[Path, str] = Path(".agentmf/evolution/evidence"),
    out_dir: Union[Path, str] = Path(".agentmf/evolution/candidates"),
    timestamp: Optional[str] = None,
    write: bool = False,
) -> DreamModeResult:
    diagnostics = Diagnostics()
    evidence_root = Path(evidence_dir)
    proposals = []
    for evidence_file in sorted(evidence_root.glob("**/*.jsonl")):
        curator = create_openclaw_curator_payload(
            evidence_file=evidence_file,
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(curator.diagnostics.items)
        if curator.payload.get("proposal"):
            proposals.append(
                {
                    **curator.payload["proposal"],
                    "patch_status": "skipped_unsupported_change",
                }
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
        if change_type == "update_match_terms":
            _apply_update_match_terms_change(change, proposal, source_map, diagnostics)
        elif change_type == "merge_duplicate_targets":
            _apply_merge_duplicate_targets_change(change, proposal, source_map, diagnostics)
        else:
            unsupported.append({"type": change_type or "unknown", "reason": "patch class is not implemented yet"})
            continue

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

    for raw_path in module_paths:
        source_path = Path(str(raw_path))
        record = _load_module_record(source_path, source_map, diagnostics)
        if record is None:
            continue
        _merge_duplicates_in_module(record["data"], duplicate_names)


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


def _merge_duplicates_in_module(data: Dict[str, Any], duplicate_names: Dict[str, Any]) -> None:
    skills = data.get("skills")
    if not isinstance(skills, dict) or not skills:
        return
    targets = data.get("targets") if isinstance(data.get("targets"), dict) else {}

    relative_to_skill: Dict[str, str] = {}
    for skill_name, skill in skills.items():
        if not isinstance(skill, dict):
            continue
        impl = skill.get("implementation")
        if isinstance(impl, dict):
            rel = impl.get("relative_source")
            if isinstance(rel, str):
                relative_to_skill[rel] = skill_name

    removed = 0
    for original_name, paths in duplicate_names.items():
        if not isinstance(paths, list) or len(paths) < 2:
            continue
        primary_path = str(paths[0])
        primary_name = relative_to_skill.get(primary_path)
        if primary_name is None or primary_name not in skills:
            continue
        primary_skill = skills[primary_name]
        if not isinstance(primary_skill, dict):
            continue
        primary_target_name = f"skill.{primary_name}"
        primary_target = targets.get(primary_target_name) if isinstance(targets.get(primary_target_name), dict) else None

        for duplicate_path in paths[1:]:
            duplicate_name = relative_to_skill.get(str(duplicate_path))
            if duplicate_name is None or duplicate_name == primary_name or duplicate_name not in skills:
                continue
            duplicate_skill = skills[duplicate_name]
            if not isinstance(duplicate_skill, dict):
                continue
            _merge_user_intent(primary_skill, duplicate_skill)
            duplicate_target_name = f"skill.{duplicate_name}"
            duplicate_target = targets.get(duplicate_target_name) if isinstance(targets.get(duplicate_target_name), dict) else None
            if primary_target is not None and duplicate_target is not None:
                _merge_user_intent(primary_target, duplicate_target)
            _record_merged_duplicate(primary_skill, duplicate_name, duplicate_skill, str(original_name))
            del skills[duplicate_name]
            if duplicate_target_name in targets:
                del targets[duplicate_target_name]
            removed += 1

    if removed:
        metadata = data.get("metadata")
        if isinstance(metadata, dict):
            count = metadata.get("skill_count")
            if isinstance(count, int):
                metadata["skill_count"] = max(0, count - removed)


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


def _workspace_destination(workspace: Path, source_path: Path) -> Path:
    if source_path.is_absolute():
        return workspace / source_path.name
    return workspace / source_path


def _module_refs_from_openclaw_record(record: Dict[str, Any]) -> list[str]:
    summary = record.get("summary", {})
    module_paths = summary.get("module_paths", []) if isinstance(summary, dict) else []
    root_agentmakefile = record.get("artifact_refs", {}).get("root_agentmakefile")
    if not root_agentmakefile:
        return [str(path) for path in module_paths]
    root_parent = Path(str(root_agentmakefile)).parent
    return [str(root_parent / str(path)) for path in module_paths]
