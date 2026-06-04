"""Append-only JSONL evidence store. No agentmf imports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agentmemory._util import fingerprint as _fingerprint
from agentmemory._util import redact_secrets, sha256_json, utc_now
from agentmemory.models import Domain, EvidenceRecord


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
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def load(self) -> List[EvidenceRecord]:
        if not self.path.exists():
            return []
        records: List[EvidenceRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(EvidenceRecord.from_dict(json.loads(line)))
        return records
