"""Append-only JSONL evidence store. No agentmf imports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from aigg_memory._util import fingerprint as _fingerprint
from aigg_memory._util import redact_secrets, sha256_json, utc_now
from aigg_memory.models import Domain, EvidenceRecord

Serializer = Callable[[Dict[str, Any]], str]


def _default_serialize(record: Dict[str, Any]) -> str:
    return json.dumps(record, ensure_ascii=False, sort_keys=True)


def append_jsonl(path: Union[str, Path], record: Dict[str, Any], *, serialize: Optional[Serializer] = None) -> None:
    """Append one record as a JSONL line. ``serialize`` lets a consumer reproduce
    a byte-identical legacy line format (e.g. compact separators, ensure_ascii)."""
    serialize = serialize or _default_serialize
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as stream:
        stream.write(serialize(record) + "\n")


def read_jsonl(path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Parse a JSONL file into a list of dicts, skipping blank lines. Raises on
    malformed JSON — callers wanting per-line diagnostics should parse themselves."""
    target = Path(path)
    if not target.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def _default_summary(payload: Any) -> Dict[str, Any]:
    """Fallback summary when the domain registers no summarizer for a source:
    keep scalar fields, truncate strings, drop nested structures."""
    if isinstance(payload, dict):
        out: Dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                out[key] = value[:200] if isinstance(value, str) else value
        return out
    return {"value": str(payload)[:200]}


class EvidenceStore:
    """Persists evidence as JSONL. Stores a summary + hashes, NEVER the raw
    payload — redaction runs before hashing so secrets never touch disk."""

    def __init__(self, path: Union[str, Path], domain: Optional[Domain] = None) -> None:
        self.path = Path(path)
        self.domain = domain

    def record(
        self,
        source: str,
        payload: Dict[str, Any],
        outcome: Optional[str] = None,
        fingerprint: Optional[str] = None,
        refs: Optional[List[str]] = None,
        timestamp: Optional[str] = None,
    ) -> EvidenceRecord:
        summarizer = self.domain.summarizers.get(source) if self.domain else None
        summary = summarizer(payload) if summarizer else _default_summary(payload)
        redacted = redact_secrets(payload)
        payload_hash = sha256_json(redacted)
        ts = timestamp or utc_now()
        fp = fingerprint or _fingerprint(summary)
        event_id = sha256_json([ts, source, payload_hash])[:16]
        record = EvidenceRecord(
            version=1,
            timestamp=ts,
            source=source,
            fingerprint=fp,
            summary=summary,
            outcome=outcome,
            payload_hash=payload_hash,
            event_id=event_id,
            refs=list(refs or []),
        )
        append_jsonl(self.path, record.to_dict())
        return record

    def load(self) -> List[EvidenceRecord]:
        return [EvidenceRecord.from_dict(d) for d in read_jsonl(self.path)]
