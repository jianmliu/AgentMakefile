"""The agent-memory loop: dream -> patch -> evaluate -> promote.

The kernel operates on an in-memory document string and dispatches to the
domain's plugins. It does not know markdown from YAML. No agentmf imports.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import List, Union

from agentmemory.models import Diagnostics, Domain, GateResult, Patch, Proposal


def run_dream(domain: Domain, records: List) -> List[Proposal]:
    """Offline consolidation: run every detector over the evidence, collect
    proposals. The kernel does not judge or dedupe — that is the domain's job."""
    proposals: List[Proposal] = []
    for detector in domain.detectors:
        result = detector(records)
        if result:
            proposals.extend(result)
    return proposals


def generate_patch(domain: Domain, proposal: Proposal, document: str) -> Patch:
    """Apply a proposal's changes to a document by dispatching each change to its
    registered applier. Unknown change types are warnings, not crashes."""
    diagnostics = Diagnostics()
    text = document
    applied: List[str] = []
    for change in proposal.changes:
        change_type = change.get("type")
        applier = domain.appliers.get(change_type)
        if applier is None:
            diagnostics.warning(
                "AM_UNSUPPORTED_CHANGE",
                f"no applier registered for change type {change_type!r}",
                location=proposal.proposal_id,
            )
            continue
        try:
            text = applier(text, change)
            applied.append(change_type)
        except Exception as exc:  # an applier bug must not abort the whole patch
            diagnostics.error(
                "AM_APPLY_FAILED",
                f"applier for {change_type!r} raised {type(exc).__name__}: {exc}",
                location=proposal.proposal_id,
            )
    diff = "".join(
        difflib.unified_diff(
            document.splitlines(keepends=True),
            text.splitlines(keepends=True),
            fromfile="before",
            tofile="after",
        )
    )
    return Patch(new_text=text, diff=diff, applied=applied, diagnostics=diagnostics)


def evaluate(domain: Domain, before: str, after: str, proposal: Proposal) -> List[GateResult]:
    """Run every gate over the before/after documents."""
    return [gate(before, after, proposal) for gate in domain.gates]


def promote(path: Union[str, Path], text: str) -> Path:
    """Commit the consolidated document to the store."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target
