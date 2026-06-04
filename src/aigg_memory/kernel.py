"""The agent-memory loop: dream -> patch -> evaluate -> promote.

The kernel dispatches to the domain's plugins over either a single in-memory
document string or a multi-file Workspace (path -> content). A single document is
the one-entry case of a workspace. It does not know markdown from YAML. No
agentmf imports.
"""
from __future__ import annotations

import difflib
from pathlib import Path
from typing import Callable, Dict, List, Union

from aigg_memory.models import Diagnostics, Domain, GateResult, Patch, Proposal, WorkspacePatch


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


# --- Workspace (multi-file) generalization --------------------------------

def _workspace_diffs(before: Dict[str, str], after: Dict[str, str]) -> Dict[str, str]:
    """Per-file unified diffs, only for files that actually changed (created,
    edited, or deleted)."""
    diffs: Dict[str, str] = {}
    for path in sorted(set(before) | set(after)):
        old, new = before.get(path, ""), after.get(path, "")
        if old == new:
            continue
        diffs[path] = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
    return diffs


def generate_workspace_patch(domain: Domain, proposal: Proposal, workspace: Dict[str, str]) -> WorkspacePatch:
    """Apply a proposal's changes to a multi-file workspace (path -> content),
    dispatching each change to its registered applier `(workspace, change) ->
    workspace`. The caller's workspace is not mutated. Unknown change types are
    warnings, not crashes; an applier that raises is an error but does not abort
    the rest of the patch."""
    diagnostics = Diagnostics()
    current = dict(workspace)
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
            current = dict(applier(current, change))
            applied.append(change_type)
        except Exception as exc:
            diagnostics.error(
                "AM_APPLY_FAILED",
                f"applier for {change_type!r} raised {type(exc).__name__}: {exc}",
                location=proposal.proposal_id,
            )
    return WorkspacePatch(
        new_workspace=current,
        diffs=_workspace_diffs(workspace, current),
        applied=applied,
        diagnostics=diagnostics,
    )


def evaluate_workspace(domain: Domain, before: Dict[str, str], after: Dict[str, str], proposal: Proposal) -> List[GateResult]:
    """Run every gate over the before/after workspaces."""
    return [gate(before, after, proposal) for gate in domain.gates]


def lift_document_applier(path: str, applier: Callable[[str, dict], str]) -> Callable[[Dict[str, str], dict], Dict[str, str]]:
    """Adapt a single-document applier `(str, change) -> str` into a workspace
    applier that edits one file — making a single document the one-entry case of
    a workspace."""
    def workspace_applier(workspace: Dict[str, str], change: dict) -> Dict[str, str]:
        updated = dict(workspace)
        updated[path] = applier(updated.get(path, ""), change)
        return updated

    return workspace_applier


def promote(path: Union[str, Path], text: str) -> Path:
    """Commit the consolidated document to the store."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target
