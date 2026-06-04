"""Domain-agnostic utilities: hashing, fingerprinting, redaction, time.

No agentmf imports. No external dependencies.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from typing import Any

_MASK = "«redacted»"
_SECRET_KEY = re.compile(r"(secret|token|api[_-]?key|password|passwd|authorization|bearer|private[_-]?key)", re.I)
_TOKEN_VALUE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+)")


def utc_now() -> str:
    """ISO-8601 UTC timestamp (seconds precision)."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_json(obj: Any) -> str:
    """Stable hash of any JSON-able object."""
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(obj: Any) -> str:
    """A short, stable identifier for a logical object (e.g. an observation)."""
    return sha256_json(obj)


def redact_secrets(value: Any) -> Any:
    """Deep-copy a structure, masking secret-looking keys and token-looking
    string values. Ordinary values are preserved."""
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(key, str) and _SECRET_KEY.search(key):
                out[key] = _MASK
            else:
                out[key] = redact_secrets(item)
        return out
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    if isinstance(value, str):
        return _TOKEN_VALUE.sub(_MASK, value)
    return value
