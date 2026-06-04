"""A markdown notebook memory domain over the kernel.

Models the MEMORY.md index format used by Claude-style auto-memory:

    - [Title](slug.md) — one-line summary

and the consolidate-memory operations: promote repeated observations into new
entries, merge duplicate entries, fix stale summaries, prune obsolete entries.
Everything runs on the kernel (run_dream / generate_patch / evaluate). No
agentmf import.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from functools import partial
from typing import List, Optional

from agentmemory._util import fingerprint
from agentmemory.kernel import evaluate, generate_patch, run_dream
from agentmemory.models import Diagnostics, Domain, GateResult, Patch, Proposal

_ENTRY_RE = re.compile(r"^- \[(?P<title>.+?)\]\((?P<slug>[^)]+)\)\s*[—:-]\s*(?P<summary>.*)$")


@dataclass(frozen=True)
class MemoryEntry:
    title: str
    slug: str
    summary: str


def parse_entry(line: str) -> Optional[MemoryEntry]:
    match = _ENTRY_RE.match(line.rstrip())
    if not match:
        return None
    return MemoryEntry(match["title"].strip(), match["slug"].strip(), match["summary"].strip())


def render_entry(entry: MemoryEntry) -> str:
    return f"- [{entry.title}]({entry.slug}) — {entry.summary}"


def parse_entries(document: str) -> List[MemoryEntry]:
    out = []
    for line in document.splitlines():
        entry = parse_entry(line)
        if entry is not None:
            out.append(entry)
    return out


def _preserve_trailing_newline(document: str, lines: List[str]) -> str:
    text = "\n".join(lines)
    if document.endswith("\n"):
        text += "\n"
    return text


# --- appliers (document string -> document string) -----------------------

def _apply_add_entry(document: str, change: dict) -> str:
    slug = change["slug"]
    if any(e.slug == slug for e in parse_entries(document)):
        return document  # idempotent
    entry = render_entry(MemoryEntry(change["title"], slug, change["summary"].strip()))
    return document.rstrip("\n") + "\n" + entry + "\n"


def _apply_prune_entry(document: str, change: dict) -> str:
    slug = change["slug"]
    lines = [ln for ln in document.splitlines() if not (parse_entry(ln) and parse_entry(ln).slug == slug)]
    return _preserve_trailing_newline(document, lines)


def _apply_update_summary(document: str, change: dict) -> str:
    slug = change["slug"]
    new_summary = change["summary"].strip()
    lines = []
    for ln in document.splitlines():
        entry = parse_entry(ln)
        if entry and entry.slug == slug:
            lines.append(render_entry(MemoryEntry(entry.title, entry.slug, new_summary)))
        else:
            lines.append(ln)
    return _preserve_trailing_newline(document, lines)


def _apply_merge_entries(document: str, change: dict) -> str:
    slugs = set(change["slugs"])
    into = change["into"]
    merged = render_entry(MemoryEntry(into["title"], into["slug"], into["summary"].strip()))
    lines = []
    inserted = False
    for ln in document.splitlines():
        entry = parse_entry(ln)
        if entry and entry.slug in slugs:
            if not inserted:
                lines.append(merged)
                inserted = True
            continue
        lines.append(ln)
    if not inserted:
        lines.append(merged)
    return _preserve_trailing_newline(document, lines)


# --- detectors (evidence records -> proposals) ---------------------------

def _detect_promote_repeated(records: List, min_count: int = 2) -> List[Proposal]:
    groups: dict = {}
    for record in records:
        if record.source != "observation" or record.outcome:
            continue
        summary = record.summary or {}
        slug, title = summary.get("slug"), summary.get("title")
        if not slug or not title:
            continue
        group = groups.setdefault(slug, {"title": title, "slug": slug, "summary": summary.get("summary", ""), "n": 0})
        group["n"] += 1
        if summary.get("summary"):
            group["summary"] = summary["summary"]  # keep the latest seen summary
    proposals = []
    for slug, group in sorted(groups.items()):
        if group["n"] >= min_count:
            proposals.append(Proposal(
                proposal_id=fingerprint(("add", slug))[:12],
                title=f"remember: {group['title']}",
                changes=[{"type": "add_entry", "title": group["title"], "slug": slug, "summary": group["summary"]}],
                scope={"document": "MEMORY.md"},
            ))
    return proposals


def _detect_corrections(records: List) -> List[Proposal]:
    proposals = []
    for record in records:
        if record.source == "observation" and record.outcome == "correction":
            summary = record.summary or {}
            slug = summary.get("slug")
            if slug and summary.get("summary"):
                proposals.append(Proposal(
                    proposal_id=fingerprint(("update", slug, summary["summary"]))[:12],
                    title=f"update: {slug}",
                    changes=[{"type": "update_summary", "slug": slug, "summary": summary["summary"]}],
                    scope={"document": "MEMORY.md"},
                ))
    return proposals


def _detect_obsolete(records: List) -> List[Proposal]:
    proposals = []
    for record in records:
        if record.source == "observation" and record.outcome == "obsolete":
            slug = (record.summary or {}).get("slug")
            if slug:
                proposals.append(Proposal(
                    proposal_id=fingerprint(("prune", slug))[:12],
                    title=f"prune: {slug}",
                    changes=[{"type": "prune_entry", "slug": slug}],
                    scope={"document": "MEMORY.md"},
                ))
    return proposals


def index_dedup_proposals(document: str) -> List[Proposal]:
    """Document-driven: merge index entries that share a slug, keeping the
    richest summary. (The kernel detectors are evidence-driven; this looks at the
    current memory state.)"""
    by_slug: dict = {}
    for entry in parse_entries(document):
        by_slug.setdefault(entry.slug, []).append(entry)
    proposals = []
    for slug, group in by_slug.items():
        if len(group) > 1:
            best = max(group, key=lambda e: len(e.summary))
            proposals.append(Proposal(
                proposal_id=fingerprint(("merge", slug))[:12],
                title=f"merge duplicates: {slug}",
                changes=[{"type": "merge_entries", "slugs": [slug],
                          "into": {"title": best.title, "slug": slug, "summary": best.summary}}],
                scope={"document": "MEMORY.md"},
            ))
    return proposals


# --- gates ----------------------------------------------------------------

def _gate_unique_slugs(before: str, after: str, proposal: Proposal) -> GateResult:
    slugs = [e.slug for e in parse_entries(after)]
    dupes = len(slugs) - len(set(slugs))
    return GateResult("unique_slugs", dupes == 0, detail=f"{dupes} duplicate slug(s)")


def _gate_well_formed(before: str, after: str, proposal: Proposal) -> GateResult:
    bad = [ln for ln in after.splitlines() if ln.strip().startswith("- ") and parse_entry(ln) is None]
    return GateResult("well_formed_index", len(bad) == 0, detail=f"{len(bad)} malformed bullet(s)")


def markdown_memory_domain(min_promote_count: int = 2) -> Domain:
    return Domain(
        name="markdown-memory",
        summarizers={"observation": lambda payload: {
            k: payload.get(k) for k in ("title", "slug", "summary") if payload.get(k) is not None
        }},
        appliers={
            "add_entry": _apply_add_entry,
            "prune_entry": _apply_prune_entry,
            "update_summary": _apply_update_summary,
            "merge_entries": _apply_merge_entries,
        },
        gates=[_gate_unique_slugs, _gate_well_formed],
        detectors=[partial(_detect_promote_repeated, min_count=min_promote_count), _detect_corrections, _detect_obsolete],
    )


# --- high-level orchestrator ---------------------------------------------

@dataclass
class ConsolidationResult:
    proposals: List[Proposal]
    patch: Patch
    gates: List[GateResult]
    new_text: str

    @property
    def gates_ok(self) -> bool:
        return all(g.passed for g in self.gates)


def consolidate(memory_text: str, records: List, domain: Optional[Domain] = None) -> ConsolidationResult:
    """Run the full loop: evidence-driven proposals (run_dream) + document-driven
    dedup, applied to the index via the kernel, then gated. Pure: no file IO."""
    domain = domain or markdown_memory_domain()
    proposals = run_dream(domain, records) + index_dedup_proposals(memory_text)
    all_changes = [change for proposal in proposals for change in proposal.changes]
    combined = Proposal("consolidation", "memory consolidation", all_changes, scope={"document": "MEMORY.md"})
    patch = generate_patch(domain, combined, memory_text)
    gates = evaluate(domain, memory_text, patch.new_text, combined)
    return ConsolidationResult(proposals=proposals, patch=patch, gates=gates, new_text=patch.new_text)
