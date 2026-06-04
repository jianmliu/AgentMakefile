"""Domain-agnostic utilities: hashing, fingerprinting, redaction, time.

No agentmf imports. No external dependencies.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from typing import Any, Callable, Optional

_MASK = "«redacted»"
_SECRET_KEY = re.compile(r"(secret|token|api[_-]?key|password|passwd|authorization|bearer|private[_-]?key)", re.I)
_TOKEN_VALUE = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+)")


def utc_now() -> str:
    """ISO-8601 UTC timestamp (seconds precision)."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_json(obj: Any, *, prefix: str = "", separators=None, ensure_ascii: bool = False) -> str:
    """Stable hash of any JSON-able object. The serialization knobs let a
    consumer (e.g. AgentMakefile) reproduce a byte-identical legacy format:
    ``sha256_json(v, prefix="sha256:", separators=(",", ":"), ensure_ascii=True)``."""
    encoded = json.dumps(obj, sort_keys=True, separators=separators, default=str, ensure_ascii=ensure_ascii)
    return prefix + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sha256_text(text: str, *, prefix: str = "") -> str:
    return prefix + hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(obj: Any) -> str:
    """A short, stable identifier for a logical object (e.g. an observation)."""
    return sha256_json(obj)


def _default_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY.search(key))


def _default_secret_value(value: str) -> bool:
    return bool(_TOKEN_VALUE.search(value))


def redact_secrets(
    value: Any,
    *,
    mask: str = _MASK,
    secret_key: Optional[Callable[[str], bool]] = None,
    secret_value: Optional[Callable[[str], bool]] = None,
) -> Any:
    """Deep-copy a structure, masking secret-looking dict keys and secret-looking
    string values (whole-value replacement). Predicates and mask are injectable so
    a consumer can reproduce a legacy redaction policy byte-for-byte."""
    key_pred = secret_key or _default_secret_key
    value_pred = secret_value or _default_secret_value

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {}
            for key, item in node.items():
                key_text = str(key)
                out[key_text] = mask if key_pred(key_text) else walk(item)
            return out
        if isinstance(node, list):
            return [walk(item) for item in node]
        if isinstance(node, str):
            return mask if value_pred(node) else node
        return node

    return walk(value)
