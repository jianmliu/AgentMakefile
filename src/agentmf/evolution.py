from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union

from agentmf.diagnostics import Diagnostics


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
