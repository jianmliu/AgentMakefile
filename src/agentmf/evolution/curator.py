"""Evolution curator (split from evolution.py — in-tree package, same public API)."""
from __future__ import annotations

from agentmf.diagnostics import Diagnostics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union
import yaml
from agentmf.evolution.evidence import _load_evidence_records
from agentmf.evolution.proposals import create_skill_workshop_proposal_payload


@dataclass
class OpenClawCuratorResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def _category_clusters(data: Dict[str, Any]) -> Dict[str, list[str]]:
    """Group a module's skills by the second path segment of their
    `implementation.relative_source` (the sub-category), for skills nested at
    least `<category>/<sub-category>/...` deep. Shared by the OpenClaw curator
    (which turns over-threshold clusters into promotable `split_module`
    proposals) and the dream-mode re-split detector (which flags them)."""
    groups: Dict[str, list[str]] = {}
    skills = data.get("skills") or {}
    if not isinstance(skills, dict):
        return groups
    for skill_name, skill in skills.items():
        if not isinstance(skill, dict):
            continue
        impl = skill.get("implementation") or {}
        rel = impl.get("relative_source") if isinstance(impl, dict) else None
        if not isinstance(rel, str):
            continue
        segments = [segment for segment in rel.split("/") if segment]
        if len(segments) < 3:
            continue
        sub_category = segments[1]
        if not sub_category:
            continue
        groups.setdefault(sub_category, []).append(skill_name)
    return groups


def _openclaw_category_split_changes(module_refs: list[str]) -> list[Dict[str, Any]]:
    """Emit one promotable `split_module` change per sub-category whose skill
    cluster in a referenced module reaches DREAM_CATEGORY_RESPLIT_THRESHOLD.

    The apply step (`_apply_split_module_change`) moves those skills into a new
    `<module-dir>/<sub-category>/<module-name>` category sub-module — this is
    the AMF-EVO-006 "category module suggestion" deliverable, distinct from the
    dream detector's review-only `investigate_category_resplit` flag.
    """
    changes: list[Dict[str, Any]] = []
    seen: set[str] = set()
    for ref in module_refs:
        if ref in seen:
            continue
        seen.add(ref)
        module_path = Path(ref)
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if not isinstance(data, dict):
            continue
        for sub_category in sorted(_category_clusters(data)):
            members = _category_clusters(data)[sub_category]
            if len(members) < DREAM_CATEGORY_RESPLIT_THRESHOLD:
                continue
            target_module = module_path.parent / sub_category / module_path.name
            changes.append(
                {
                    "type": "split_module",
                    "source_module": str(module_path),
                    "target_module": str(target_module),
                    "skills": sorted(members),
                    "targets": [],
                    "reason": f"{len(members)} skills cluster under sub-category '{sub_category}'.",
                }
            )
    return changes


def create_openclaw_curator_payload(
    *,
    evidence_file: Union[Path, str],
    out_dir: Union[Path, str] = Path(".agentmf/evolution/candidates"),
    timestamp: Optional[str] = None,
    write: bool = False,
) -> OpenClawCuratorResult:
    diagnostics = Diagnostics()
    records = _load_evidence_records([evidence_file], diagnostics)
    if diagnostics.has_errors:
        return OpenClawCuratorResult(diagnostics)

    openclaw_records = [
        record
        for record in records
        if record.get("source") == "openclaw_import" and isinstance(record.get("summary"), dict)
    ]

    duplicate_original_names: Dict[str, Any] = {}
    modules: list[str] = []
    for record in openclaw_records:
        names = record["summary"].get("duplicate_original_names")
        if names:
            duplicate_original_names.update(names)
            modules.extend(_module_refs_from_openclaw_record(record))

    all_module_refs: list[str] = []
    for record in openclaw_records:
        all_module_refs.extend(_module_refs_from_openclaw_record(record))

    changes: list[Dict[str, Any]] = []
    if duplicate_original_names:
        changes.append(
            {
                "type": "merge_duplicate_targets",
                "duplicate_original_names": duplicate_original_names,
                "reason": "OpenClaw import evidence reported duplicate original skill names.",
            }
        )
    split_changes = _openclaw_category_split_changes(all_module_refs)
    changes.extend(split_changes)
    modules.extend(change["source_module"] for change in split_changes)

    if not changes:
        return OpenClawCuratorResult(
            diagnostics,
            {"version": 1, "mode": "openclaw_curator", "proposal_count": 0, "proposal": None},
        )

    title = (
        "Curate duplicate OpenClaw skills"
        if duplicate_original_names
        else "Curate OpenClaw skill categories"
    )
    proposal = create_skill_workshop_proposal_payload(
        title=title,
        evidence_files=[evidence_file],
        scope={"modules": sorted(set(modules)), "targets": []},
        changes=changes,
        evaluation_commands=[
            "agentmf validate --file modules/openclaw/AgentMakefile",
            "agentmf benchmark harness --file modules/openclaw/AgentMakefile --case \"review code\"",
        ],
        out_dir=out_dir,
        timestamp=timestamp,
        write=write,
    )
    diagnostics.extend(proposal.diagnostics.items)
    return OpenClawCuratorResult(
        diagnostics,
        {
            "version": 1,
            "mode": "openclaw_curator",
            "proposal_count": 1 if proposal.payload else 0,
            "proposal": proposal.payload,
        },
    )


def _modules_from_openclaw_evidence(evidence_files: list[Path], diagnostics: Diagnostics) -> list[Path]:
    """Collect unique module paths referenced by openclaw_import records."""
    seen: list[Path] = []
    seen_set: set[str] = set()
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "openclaw_import":
                continue
            summary = record.get("summary") or {}
            module_paths = summary.get("module_paths") if isinstance(summary, dict) else None
            if not isinstance(module_paths, list):
                continue
            for ref in module_paths:
                if not isinstance(ref, str) or ref in seen_set:
                    continue
                seen_set.add(ref)
                seen.append(Path(ref))
    return seen


DREAM_CATEGORY_RESPLIT_THRESHOLD = 10


def _module_refs_from_openclaw_record(record: Dict[str, Any]) -> list[str]:
    summary = record.get("summary", {})
    module_paths = summary.get("module_paths", []) if isinstance(summary, dict) else []
    root_agentmakefile = record.get("artifact_refs", {}).get("root_agentmakefile")
    if not root_agentmakefile:
        return [str(path) for path in module_paths]
    root_parent = Path(str(root_agentmakefile)).parent
    return [str(root_parent / str(path)) for path in module_paths]
