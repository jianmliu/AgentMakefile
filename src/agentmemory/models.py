"""Data model for the agent-memory kernel. No agentmf imports."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Diagnostic:
    severity: str
    code: str
    message: str
    location: Optional[str] = None
    hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.location:
            d["location"] = self.location
        if self.hint:
            d["hint"] = self.hint
        return d


class Diagnostics:
    """A minimal, API-compatible diagnostics collector (severity-aware)."""

    def __init__(self) -> None:
        self._items: List[Diagnostic] = []

    def error(self, code: str, message: str, location: Optional[str] = None, hint: Optional[str] = None) -> None:
        self._items.append(Diagnostic("error", code, message, location, hint))

    def warning(self, code: str, message: str, location: Optional[str] = None, hint: Optional[str] = None) -> None:
        self._items.append(Diagnostic("warning", code, message, location, hint))

    def extend(self, other: "Diagnostics") -> None:
        self._items.extend(other._items)

    @property
    def has_errors(self) -> bool:
        return any(d.severity == "error" for d in self._items)

    def to_list(self) -> List[Dict[str, Any]]:
        return [d.to_dict() for d in self._items]

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)


@dataclass
class EvidenceRecord:
    """One immutable observation. Stores a summary + hashes, never the raw payload."""

    version: int
    timestamp: str
    source: str
    fingerprint: str
    summary: Dict[str, Any]
    outcome: Optional[str]
    payload_hash: str
    event_id: str
    refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "timestamp": self.timestamp,
            "source": self.source,
            "fingerprint": self.fingerprint,
            "summary": self.summary,
            "outcome": self.outcome,
            "payload_hash": self.payload_hash,
            "event_id": self.event_id,
            "refs": self.refs,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "EvidenceRecord":
        return cls(
            version=d.get("version", 1),
            timestamp=d.get("timestamp", ""),
            source=d.get("source", ""),
            fingerprint=d.get("fingerprint", ""),
            summary=d.get("summary", {}),
            outcome=d.get("outcome"),
            payload_hash=d.get("payload_hash", ""),
            event_id=d.get("event_id", ""),
            refs=d.get("refs", []),
        )


@dataclass
class Proposal:
    """A candidate memory change synthesized from evidence."""

    proposal_id: str
    title: str
    changes: List[Dict[str, Any]]
    evidence_refs: List[str] = field(default_factory=list)
    scope: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "title": self.title,
            "changes": self.changes,
            "evidence_refs": self.evidence_refs,
            "scope": self.scope,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Proposal":
        return cls(
            proposal_id=d.get("proposal_id", ""),
            title=d.get("title", ""),
            changes=d.get("changes", []),
            evidence_refs=d.get("evidence_refs", []),
            scope=d.get("scope", {}),
            created_at=d.get("created_at", ""),
        )


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Patch:
    new_text: str
    diff: str
    applied: List[str]
    diagnostics: Diagnostics


# Plugin callable signatures (documentation aliases)
Summarizer = Callable[[Dict[str, Any]], Dict[str, Any]]
Applier = Callable[[str, Dict[str, Any]], str]
Gate = Callable[[str, str, Proposal], GateResult]
Detector = Callable[[List[EvidenceRecord]], List[Proposal]]


@dataclass
class Domain:
    """A pluggable memory domain. The kernel owns the loop; the domain supplies
    behavior. AgentMakefile routing-config and a markdown notebook are two
    different domains over the same kernel."""

    name: str
    summarizers: Dict[str, Summarizer] = field(default_factory=dict)
    appliers: Dict[str, Applier] = field(default_factory=dict)
    gates: List[Gate] = field(default_factory=list)
    detectors: List[Detector] = field(default_factory=list)
