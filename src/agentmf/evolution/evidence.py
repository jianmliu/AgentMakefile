"""Evolution evidence (split from evolution.py — in-tree package, same public API)."""
from __future__ import annotations

from agentmf.diagnostics import Diagnostics
from aigg_memory import append_jsonl as _am_append_jsonl
from aigg_memory import redact_secrets as _am_redact_secrets
from aigg_memory import sha256_json as _am_sha256_json
from aigg_memory import sha256_text as _am_sha256_text
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union
import json
import re


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
            # Persist via the aigg_memory kernel; the serializer reproduces the
            # legacy compact line format byte-for-byte.
            _am_append_jsonl(
                output_path,
                record,
                serialize=lambda r: json.dumps(r, sort_keys=True, separators=(",", ":")),
            )
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
        diff = payload.get("diff")
        diff_list = diff if isinstance(diff, list) else []
        diff_paths: list[str] = []
        additions_total = 0
        deletions_total = 0
        for entry in diff_list:
            if not isinstance(entry, dict):
                continue
            file_path = entry.get("file")
            if isinstance(file_path, str) and file_path:
                diff_paths.append(file_path)
            additions = entry.get("additions")
            if isinstance(additions, int):
                additions_total += additions
            deletions = entry.get("deletions")
            if isinstance(deletions, int):
                deletions_total += deletions
        summary: Dict[str, Any] = {
            "selected_targets": payload.get("selected_targets", []),
            "selected_skills": payload.get("selected_skills", []),
            "selected_pipeline": payload.get("selected_pipeline", {}),
            # Diff metadata for the dream loop. Full before/after content
            # stays in payload_hash; we only surface file paths + counts
            # here so records remain compact and don't leak source text.
            "diff_files": payload.get("diff_files", len(diff_paths)),
            "diff_source": payload.get("diff_source"),
            "diff_paths": diff_paths,
            "diff_additions": additions_total,
            "diff_deletions": deletions_total,
        }
        event_type = payload.get("event_type")
        if isinstance(event_type, str) and event_type:
            summary["event_type"] = event_type
        captured_at = payload.get("captured_at")
        if isinstance(captured_at, str) and captured_at:
            summary["captured_at"] = captured_at
        return summary
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
            "actual_module": payload.get("actual_module"),
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
    # Delegates to the aigg_memory kernel with AgentMakefile's policy injected,
    # so the redaction is byte-identical to the legacy implementation.
    return _am_redact_secrets(value, mask="[REDACTED]", secret_key=_secret_key, secret_value=_secret_value)


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
    # Delegates to the aigg_memory kernel; the knobs reproduce the legacy bytes.
    return _am_sha256_json(value, prefix="sha256:", separators=(",", ":"), ensure_ascii=True)


def _sha256_text(value: str) -> str:
    return _am_sha256_text(value, prefix="sha256:")


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
