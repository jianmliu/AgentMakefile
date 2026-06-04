"""The typed `memory` domain — SKILL.md-shaped units over the Workspace.

A memory unit is `memory/<slug>/SKILL.md` with YAML frontmatter (name, description,
kind, match, provenance/lifecycle metadata) + a markdown body. A unit's `kind`
(procedural | semantic | episodic) makes consolidation kind-aware: procedural
units land as `candidate` (needs review), declarative ones auto-activate.

Multi-file by nature, so it runs on the kernel's Workspace API
(`generate_workspace_patch` / `evaluate_workspace`). No agentmf import; depends on
PyYAML for frontmatter (a memory store reading SKILL.md legitimately needs YAML).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml

from aigg_memory._util import fingerprint
from aigg_memory.kernel import evaluate_workspace, generate_workspace_patch, run_dream
from aigg_memory.models import Domain, GateResult, Proposal, WorkspacePatch

VALID_KINDS = {"procedural", "semantic", "episodic", "working"}
_UNIT_SUFFIX = "/SKILL.md"


@dataclass
class MemoryUnit:
    frontmatter: Dict
    body: str

    @property
    def name(self) -> Optional[str]:
        return self.frontmatter.get("name")

    @property
    def kind(self) -> Optional[str]:
        return self.frontmatter.get("kind")

    @property
    def match_terms(self) -> List[str]:
        return list((self.frontmatter.get("match") or {}).get("user_intent") or [])

    def to_text(self) -> str:
        fm = yaml.safe_dump(self.frontmatter, sort_keys=False, allow_unicode=True).rstrip("\n")
        return f"---\n{fm}\n---\n\n{self.body.rstrip(chr(10))}\n"

    @classmethod
    def from_text(cls, text: str) -> "MemoryUnit":
        lines = text.splitlines()
        if lines and lines[0].strip() == "---":
            for index in range(1, len(lines)):
                if lines[index].strip() == "---":
                    fm = yaml.safe_load("\n".join(lines[1:index])) or {}
                    body = "\n".join(lines[index + 1:]).lstrip("\n")
                    return cls(fm if isinstance(fm, dict) else {}, body)
        return cls({}, text)


def unit_path(slug: str) -> str:
    return f"memory/{slug}{_UNIT_SUFFIX}"


def _is_unit(path: str) -> bool:
    return path.endswith(_UNIT_SUFFIX)


# --- appliers (workspace -> workspace) ------------------------------------

def _apply_add_unit(workspace: Dict[str, str], change: dict) -> Dict[str, str]:
    slug = change["slug"]
    path = unit_path(slug)
    if path in workspace:
        return workspace  # idempotent
    frontmatter = {
        "name": change.get("name", slug),
        "description": change.get("description", ""),
        "kind": change.get("kind", "semantic"),
        "match": {"user_intent": list(change.get("match", []))},
        "id": slug,
        "confidence": change.get("confidence", "medium"),
        "observations": change.get("observations", 1),
        "source_events": sorted(set(change.get("source_events", []))),
        "status": change.get("status", "active"),
    }
    ws = dict(workspace)
    ws[path] = MemoryUnit(frontmatter, change.get("body") or change.get("description", "")).to_text()
    return ws


def _apply_update_unit(workspace: Dict[str, str], change: dict) -> Dict[str, str]:
    path = unit_path(change["slug"])
    if path not in workspace:
        return workspace
    unit = MemoryUnit.from_text(workspace[path])
    if change.get("body") is not None:
        unit.body = change["body"]
    if change.get("description"):
        unit.frontmatter["description"] = change["description"]
    if change.get("source_events"):
        merged = set(unit.frontmatter.get("source_events") or []) | set(change["source_events"])
        unit.frontmatter["source_events"] = sorted(merged)
    if change.get("updated"):
        unit.frontmatter["updated"] = change["updated"]
    ws = dict(workspace)
    ws[path] = unit.to_text()
    return ws


def _apply_archive_unit(workspace: Dict[str, str], change: dict) -> Dict[str, str]:
    path = unit_path(change["slug"])
    if path not in workspace:
        return workspace
    unit = MemoryUnit.from_text(workspace[path])
    unit.frontmatter["status"] = "archived"
    ws = dict(workspace)
    ws[path] = unit.to_text()
    return ws


def _apply_merge_units(workspace: Dict[str, str], change: dict) -> Dict[str, str]:
    into = change["into"]
    ws = dict(workspace)
    for slug in change["slugs"]:
        ws.pop(unit_path(slug), None)
    frontmatter = {
        "name": into.get("name", into["slug"]),
        "description": into.get("description", ""),
        "kind": into.get("kind", "semantic"),
        "match": {"user_intent": list(into.get("match", []))},
        "id": into["slug"],
        "supersedes": list(into.get("supersedes", [])),
        "status": into.get("status", "active"),
    }
    ws[unit_path(into["slug"])] = MemoryUnit(frontmatter, into.get("body", "")).to_text()
    return ws


# --- detectors (evidence -> proposals), kind-aware ------------------------

def _detect_promote_repeated(records: List, min_count: int = 2) -> List[Proposal]:
    groups: dict = {}
    for record in records:
        if record.source != "observation" or record.outcome:
            continue
        summary = record.summary or {}
        slug = summary.get("slug")
        if not slug:
            continue
        group = groups.setdefault(slug, {
            "slug": slug, "name": summary.get("name") or slug,
            "description": summary.get("description", ""), "kind": summary.get("kind", "semantic"),
            "match": summary.get("match", []), "body": summary.get("body", ""), "events": [], "n": 0,
        })
        group["n"] += 1
        group["events"].append(record.event_id)
        for field in ("description", "body", "match", "name"):
            if summary.get(field):
                group[field] = summary[field]
    proposals = []
    for slug, group in sorted(groups.items()):
        if group["n"] >= min_count:
            # kind-aware policy: procedural memory needs review; declarative auto-activates.
            status = "candidate" if group["kind"] == "procedural" else "active"
            proposals.append(Proposal(
                proposal_id=fingerprint(("add", slug))[:12],
                title=f"remember: {group['name']}",
                changes=[{
                    "type": "add_unit", "slug": slug, "name": group["name"],
                    "description": group["description"], "kind": group["kind"], "match": group["match"],
                    "body": group["body"] or group["description"], "source_events": group["events"],
                    "observations": group["n"], "confidence": "high", "status": status,
                }],
                scope={"corpus": "memory/"},
            ))
    return proposals


def _detect_corrections(records: List) -> List[Proposal]:
    proposals = []
    for record in records:
        if record.source == "observation" and record.outcome == "correction":
            summary = record.summary or {}
            slug = summary.get("slug")
            if slug and (summary.get("description") or summary.get("body")):
                proposals.append(Proposal(
                    proposal_id=fingerprint(("update", slug, record.event_id))[:12],
                    title=f"update: {slug}",
                    changes=[{
                        "type": "update_unit", "slug": slug,
                        "description": summary.get("description"), "body": summary.get("body"),
                        "source_events": [record.event_id], "updated": record.timestamp,
                    }],
                    scope={"corpus": "memory/"},
                ))
    return proposals


def _detect_obsolete(records: List) -> List[Proposal]:
    proposals = []
    for record in records:
        if record.source == "observation" and record.outcome == "obsolete":
            slug = (record.summary or {}).get("slug")
            if slug:
                proposals.append(Proposal(
                    proposal_id=fingerprint(("archive", slug))[:12],
                    title=f"archive: {slug}",
                    changes=[{"type": "archive_unit", "slug": slug}],
                    scope={"corpus": "memory/"},
                ))
    return proposals


# --- gates (workspace) ----------------------------------------------------

def _units(workspace: Dict[str, str]):
    for path, content in workspace.items():
        if _is_unit(path):
            yield path, MemoryUnit.from_text(content)


def _gate_units_parse(before, after, proposal) -> GateResult:
    bad = [p for p, u in _units(after) if not (u.name and u.frontmatter.get("description") and u.kind)]
    return GateResult("units_parse", len(bad) == 0, detail=f"{len(bad)} malformed unit(s)")


def _gate_unique_ids(before, after, proposal) -> GateResult:
    ids = [u.frontmatter.get("id") for _p, u in _units(after)]
    return GateResult("unique_ids", len(ids) == len(set(ids)), detail=f"{len(ids) - len(set(ids))} duplicate id(s)")


def _gate_has_match(before, after, proposal) -> GateResult:
    missing = [p for p, u in _units(after) if not u.match_terms]
    return GateResult("has_match_terms", len(missing) == 0, detail=f"{len(missing)} unit(s) without match terms")


def _gate_kind_valid(before, after, proposal) -> GateResult:
    bad = [p for p, u in _units(after) if u.kind not in VALID_KINDS]
    return GateResult("kind_valid", len(bad) == 0, detail=f"{len(bad)} unit(s) with invalid kind")


def memory_domain(min_promote_count: int = 2) -> Domain:
    return Domain(
        name="memory",
        summarizers={"observation": lambda p: {
            k: p.get(k) for k in ("name", "slug", "kind", "description", "match", "body") if p.get(k) is not None
        }},
        appliers={
            "add_unit": _apply_add_unit,
            "update_unit": _apply_update_unit,
            "merge_units": _apply_merge_units,
            "archive_unit": _apply_archive_unit,
        },
        gates=[_gate_units_parse, _gate_unique_ids, _gate_has_match, _gate_kind_valid],
        detectors=[partial(_detect_promote_repeated, min_count=min_promote_count), _detect_corrections, _detect_obsolete],
    )


# --- orchestrator ---------------------------------------------------------

@dataclass
class MemoryConsolidationResult:
    proposals: List[Proposal]
    patch: WorkspacePatch
    gates: List[GateResult]
    new_workspace: Dict[str, str]

    @property
    def gates_ok(self) -> bool:
        return all(g.passed for g in self.gates)


def consolidate(workspace: Dict[str, str], records: List, domain: Optional[Domain] = None) -> MemoryConsolidationResult:
    """Run the full loop over a memory corpus (workspace of unit files): evidence
    -> proposals (run_dream) -> multi-file patch -> gates. Pure: no file IO."""
    domain = domain or memory_domain()
    proposals = run_dream(domain, records)
    all_changes = [change for proposal in proposals for change in proposal.changes]
    combined = Proposal("consolidation", "memory consolidation", all_changes, scope={"corpus": "memory/"})
    patch = generate_workspace_patch(domain, combined, workspace)
    gates = evaluate_workspace(domain, workspace, patch.new_workspace, combined)
    return MemoryConsolidationResult(proposals=proposals, patch=patch, gates=gates, new_workspace=patch.new_workspace)


# --- file-backed corpus (the on-disk memory/ directory) -------------------

def _disk_path(root: Path, corpus: str, key: str) -> Path:
    """A workspace key is always domain-normalised (`memory/<slug>/SKILL.md`); on
    disk the unit lives under `root/<corpus>/<slug>/SKILL.md`."""
    slug = Path(key).parent.name
    return root / corpus / slug / "SKILL.md"


def load_corpus(root: Union[str, Path], corpus: str = "memory") -> Dict[str, str]:
    """Read all `<corpus>/<slug>/SKILL.md` under `root` into a workspace keyed by
    the domain path convention (`memory/<slug>/SKILL.md`), regardless of the
    on-disk corpus directory."""
    root = Path(root)
    workspace: Dict[str, str] = {}
    for path in sorted((root / corpus).glob("*/SKILL.md")):
        workspace[unit_path(path.parent.name)] = path.read_text(encoding="utf-8")
    return workspace


def write_corpus(root: Union[str, Path], workspace: Dict[str, str], corpus: str = "memory",
                 only: Optional[List[str]] = None) -> List[str]:
    root = Path(root)
    written: List[str] = []
    for key in (only if only is not None else list(workspace)):
        disk = _disk_path(root, corpus, key)
        disk.parent.mkdir(parents=True, exist_ok=True)
        disk.write_text(workspace[key], encoding="utf-8")
        written.append(key)
    return written


@dataclass
class CorpusConsolidationResult:
    consolidation: MemoryConsolidationResult
    written: List[str]
    removed: List[str]

    @property
    def gates_ok(self) -> bool:
        return self.consolidation.gates_ok


def consolidate_corpus(root: Union[str, Path], records: List, write: bool = False,
                       corpus: str = "memory", domain: Optional[Domain] = None) -> CorpusConsolidationResult:
    """Load the on-disk `<corpus>/` corpus, consolidate from evidence, and (when
    `write` and every gate passes) write changed unit files back, deleting any
    merged-away units. Returns the changed/removed paths."""
    root = Path(root)
    before = load_corpus(root, corpus)
    result = consolidate(before, records, domain=domain)
    written: List[str] = []
    removed: List[str] = []
    if write and result.gates_ok:
        after = result.new_workspace
        changed = sorted(key for key, content in after.items() if before.get(key) != content)
        written = write_corpus(root, after, corpus=corpus, only=changed)
        removed = sorted(key for key in before if key not in after)
        for key in removed:
            _disk_path(root, corpus, key).unlink(missing_ok=True)
    return CorpusConsolidationResult(consolidation=result, written=written, removed=removed)
