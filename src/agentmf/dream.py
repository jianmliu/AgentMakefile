"""Dream Mode dry-run detectors + OpenClaw review-only proposers (AMF-EVO-005/006).

Extracted from evolution.py. One-directional dependency: dream imports stable
primitives from evolution; nothing in evolution imports from dream.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from aigg_memory import Domain as _AmDomain
from aigg_memory import run_dream as _am_run_dream
from agentmf.diagnostics import Diagnostics
from agentmf.evolution import (
    DREAM_CATEGORY_RESPLIT_THRESHOLD,
    SUPPORTED_PATCH_TYPES,
    _category_clusters,
    _load_evidence_records,
    _modules_from_openclaw_evidence,
    _sha256_text,
    create_openclaw_curator_payload,
    create_skill_workshop_proposal_payload,
)


@dataclass
class DreamModeResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


DREAM_RECURRING_FAILURE_THRESHOLD = 2


def create_dream_mode_payload(
    *,
    evidence_dir: Union[Path, str] = Path(".agentmf/evolution/evidence"),
    out_dir: Union[Path, str] = Path(".agentmf/evolution/candidates"),
    timestamp: Optional[str] = None,
    write: bool = False,
) -> DreamModeResult:
    diagnostics = Diagnostics()
    evidence_root = Path(evidence_dir)
    evidence_files = sorted(evidence_root.glob("**/*.jsonl"))

    # The dream detectors share a uniform signature and are run in a fixed order,
    # concatenating their proposals — exactly the aigg_memory kernel's run_dream
    # dispatch. Each detector is bound as a kernel detector over the evidence
    # files; the dict shapes and order are preserved byte-for-byte.
    detectors = [
        lambda files: _dream_openclaw_duplicates(files, out_dir, timestamp, write, diagnostics),
        lambda files: _dream_recurring_routing_gaps(files, out_dir, timestamp, write, diagnostics),
        lambda files: _dream_missing_match_terms(files, out_dir, timestamp, write, diagnostics),
        lambda files: _dream_drifted_permissions(files, out_dir, timestamp, write, diagnostics),
        lambda files: _dream_trust_annotation(files, out_dir, timestamp, write, diagnostics),
        lambda files: _dream_heavy_tool_warning(files, out_dir, timestamp, write, diagnostics),
        lambda files: _dream_benchmark_case_suggester(files, out_dir, timestamp, write, diagnostics),
        lambda files: _dream_category_resplit(files, out_dir, timestamp, write, diagnostics),
        lambda files: _dream_low_signal_terms(files, out_dir, timestamp, write, diagnostics),
        lambda files: _dream_corpus_wide_low_signal_terms(files, out_dir, timestamp, write, diagnostics),
    ]
    proposals = _am_run_dream(_AmDomain(name="agentmakefile-dream", detectors=detectors), evidence_files)

    if diagnostics.has_errors:
        return DreamModeResult(diagnostics)
    return DreamModeResult(
        diagnostics,
        {
            "version": 1,
            "mode": "dream_mode_dry_run",
            "evidence_dir": str(evidence_root),
            "proposal_count": len(proposals),
            "proposals": proposals,
        },
    )


def _dream_openclaw_duplicates(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    proposals: list[Dict[str, Any]] = []
    for evidence_file in evidence_files:
        curator = create_openclaw_curator_payload(
            evidence_file=evidence_file,
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(curator.diagnostics.items)
        if curator.payload.get("proposal"):
            wrapper = curator.payload["proposal"]
            proposals.append(
                {
                    **wrapper,
                    "patch_status": _dream_patch_status(wrapper),
                }
            )
    return proposals


def _dream_recurring_routing_gaps(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Surface request fingerprints that have >=N failed plugin selections
    (selected_target is null) as investigate_recurring_routing_gap proposals.
    """
    failure_records: Dict[str, list[Dict[str, Any]]] = {}
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "plugin_payload":
                continue
            if record.get("selected_target"):
                continue
            fingerprint = record.get("request_fingerprint")
            if not isinstance(fingerprint, str) or not fingerprint:
                continue
            failure_records.setdefault(fingerprint, []).append(record)

    proposals: list[Dict[str, Any]] = []
    for fingerprint in sorted(failure_records):
        records = failure_records[fingerprint]
        if len(records) < DREAM_RECURRING_FAILURE_THRESHOLD:
            continue
        sample_event_ids = sorted(str(record.get("event_id", "")) for record in records)
        change = {
            "type": "investigate_recurring_routing_gap",
            "request_fingerprint": fingerprint,
            "failure_count": len(records),
            "sample_event_ids": sample_event_ids[:5],
        }
        result = create_skill_workshop_proposal_payload(
            title=f"Investigate recurring routing gap: {fingerprint[-12:]}",
            evidence_records=records,
            scope={"modules": [], "targets": []},
            changes=[change],
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append(
                {
                    **result.payload,
                    "patch_status": _dream_patch_status(result.payload),
                }
            )
    return proposals


def _dream_missing_match_terms(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Read user_feedback evidence (requests that should have routed elsewhere)
    and emit a combined proposal per (intended_module, intended_target):

    - update_match_terms adds the request texts (or user-supplied
      corrective_terms) to the intended target's match.user_intent so
      the corrective phrase is visible to the matcher.
    - prune_match_terms (when feedback names an actual_target) removes
      overly-broad single-word triggers from the actual_target that
      caused the false positive in the first place.

    The two changes ship in one proposal so the patch generator applies
    them atomically.
    """
    by_target: Dict[tuple[str, str], list[Dict[str, Any]]] = {}
    terms_by_target: Dict[tuple[str, str], list[str]] = {}
    # Map (intended_module, intended_target) -> {actual_target: [(actual_module, request_text), ...]}
    # The actual_module may differ from intended_module when the wrongly-
    # winning target lives in a sibling module (cross-module routing
    # gap). Falls back to the intended module when the feedback caller
    # didn't supply actual_module.
    actuals_by_target: Dict[
        tuple[str, str], Dict[str, list[tuple[str, str]]]
    ] = {}
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "user_feedback":
                continue
            summary = record.get("summary")
            if not isinstance(summary, dict):
                continue
            intended_module = summary.get("intended_module")
            intended_target = summary.get("intended_target")
            request_text = summary.get("request")
            if not intended_module or not intended_target or not request_text:
                continue
            key = (str(intended_module), str(intended_target))
            corrective = summary.get("corrective_terms") or []
            candidate_terms = [str(term) for term in corrective if isinstance(term, str)]
            if not candidate_terms:
                candidate_terms = [str(request_text)]
            by_target.setdefault(key, []).append(record)
            bucket = terms_by_target.setdefault(key, [])
            for term in candidate_terms:
                if term and term not in bucket:
                    bucket.append(term)
            actual_target = summary.get("actual_target")
            if isinstance(actual_target, str) and actual_target:
                actual_module = summary.get("actual_module")
                actual_module_path = (
                    str(actual_module) if isinstance(actual_module, str) and actual_module
                    else str(intended_module)
                )
                actuals_by_target.setdefault(key, {}).setdefault(actual_target, []).append(
                    (actual_module_path, str(request_text))
                )

    proposals: list[Dict[str, Any]] = []
    for key in sorted(by_target):
        module_path, target_name = key
        records = by_target[key]
        terms = terms_by_target[key]
        changes: list[Dict[str, Any]] = [
            {
                "type": "update_match_terms",
                "module": module_path,
                "target": target_name,
                "add_terms": terms,
            }
        ]
        # Generate prune proposals for each actual_target that wrongly won.
        # The lookup MUST run against the module that owns the actual
        # target, which may be a different file than `module_path` (the
        # intended module) when the routing gap crossed modules.
        extra_scope_modules: list[str] = []
        for actual_target, hits in sorted(actuals_by_target.get(key, {}).items()):
            # Group by actual_module so each (target, module) pair gets
            # its own prune change with the correct file pointer.
            by_actual_module: Dict[str, list[str]] = {}
            for actual_module_path, request_text in hits:
                by_actual_module.setdefault(actual_module_path, []).append(request_text)
            for actual_module_path, requests in sorted(by_actual_module.items()):
                broad_terms = _broad_match_terms_to_prune(
                    Path(actual_module_path), actual_target, requests
                )
                if broad_terms:
                    changes.append(
                        {
                            "type": "prune_match_terms",
                            "module": actual_module_path,
                            "target": actual_target,
                            "remove_terms": broad_terms,
                        }
                    )
                    if actual_module_path != module_path and actual_module_path not in extra_scope_modules:
                        extra_scope_modules.append(actual_module_path)

        scope_modules = [module_path, *extra_scope_modules]
        result = create_skill_workshop_proposal_payload(
            title=f"Add match terms to {target_name}",
            evidence_records=records,
            scope={"modules": scope_modules, "targets": [target_name]},
            changes=changes,
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append(
                {
                    **result.payload,
                    "patch_status": _dream_patch_status(result.payload),
                }
            )
    return proposals


def _broad_match_terms_to_prune(
    module_path: Path, target_name: str, requests: list[str]
) -> list[str]:
    """Identify single-word, short user_intent terms on `target_name` that
    substring-match one or more of `requests`. These are the broad
    triggers most likely to cause false positives — multi-word or longer
    phrases are left alone (they're presumed intentional).
    """
    try:
        data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
    except OSError:
        return []
    if not isinstance(data, dict):
        return []
    targets = data.get("targets")
    if not isinstance(targets, dict):
        return []
    target = targets.get(target_name)
    if not isinstance(target, dict):
        return []
    match = target.get("match")
    if not isinstance(match, dict):
        return []
    user_intent = match.get("user_intent")
    if isinstance(user_intent, str):
        user_intent = [user_intent]
    if not isinstance(user_intent, list):
        return []
    from agentmf.matcher import build_request_profile, match_term

    profiles = [build_request_profile(req) for req in requests]
    broad: list[str] = []
    for term in user_intent:
        term_text = str(term).strip()
        if not term_text:
            continue
        # Pruning criterion: short, single-word triggers ("Create",
        # "Edit", "Files") are the broad ones. Multi-word phrases stay.
        if " " in term_text or len(term_text) > 12:
            continue
        for profile in profiles:
            detail = match_term(profile, term_text)
            if detail and detail.get("score", 0) >= 95:
                if term_text not in broad:
                    broad.append(term_text)
                break
    return broad


DREAM_PERMISSION_DRIFT_THRESHOLD = 2


def _dream_drifted_permissions(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Surface recurring `denied_tool_calls` from benchmark evidence as
    `investigate_permission_drift` proposals — one per
    (target, tool, pattern) triple that appears in >=N records.

    Like recurring_routing_gap this detector flags evidence for human
    review rather than auto-patching: deciding to flip a deny to allow
    or update the permission guard is a security-sensitive choice, so
    the proposal stays "candidate + requires_review" and the patch
    class (`update_permission_guard`) is intentionally separate.
    """
    denials_by_triple: Dict[tuple[str, str, str], list[Dict[str, Any]]] = {}
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "benchmark":
                continue
            summary = record.get("summary")
            if not isinstance(summary, dict):
                continue
            denied = summary.get("denied_tool_calls")
            if not isinstance(denied, list):
                continue
            for entry in denied:
                if not isinstance(entry, dict):
                    continue
                target = entry.get("target")
                tool = entry.get("tool")
                pattern = entry.get("pattern")
                if not isinstance(target, str) or not isinstance(tool, str) or not isinstance(pattern, str):
                    continue
                key = (target, tool, pattern)
                denials_by_triple.setdefault(key, []).append(record)

    proposals: list[Dict[str, Any]] = []
    for key in sorted(denials_by_triple):
        records = denials_by_triple[key]
        if len(records) < DREAM_PERMISSION_DRIFT_THRESHOLD:
            continue
        target, tool, pattern = key
        sample_event_ids = sorted(str(record.get("event_id", "")) for record in records)
        change = {
            "type": "investigate_permission_drift",
            "target": target,
            "tool": tool,
            "pattern": pattern,
            "denial_count": len(records),
            "sample_event_ids": sample_event_ids[:5],
        }
        result = create_skill_workshop_proposal_payload(
            title=f"Investigate permission drift: {target} / {tool} / {pattern}",
            evidence_records=records,
            scope={"modules": [], "targets": [target]},
            changes=[change],
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append(
                {
                    **result.payload,
                    "patch_status": _dream_patch_status(result.payload),
                }
            )
    return proposals


CACHE_PATH_HINTS = ("/cache/", ".tmp/")


HEAVY_TOOL_KEYWORDS = ("sudo ", "rm -rf", "docker ", "kubectl ", "ssh ", "scp ", "curl http", "wget http")


DREAM_BENCHMARK_CASE_THRESHOLD = 3


def _dream_trust_annotation(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """For every module referenced by openclaw_import evidence, emit one
    proposal with `add_registry_metadata` changes annotating any skill
    whose `relative_source` lives under a cache or scratch path. Existing
    `registry_metadata.cache_derived` annotations are left alone so reruns
    are idempotent.
    """
    proposals: list[Dict[str, Any]] = []
    module_paths = _modules_from_openclaw_evidence(evidence_files, diagnostics)
    for module_path in module_paths:
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if not isinstance(data, dict):
            continue
        skills = data.get("skills") or {}
        if not isinstance(skills, dict):
            continue
        changes: list[Dict[str, Any]] = []
        for skill_name, skill in skills.items():
            if not isinstance(skill, dict):
                continue
            impl = skill.get("implementation") or {}
            if not isinstance(impl, dict):
                continue
            rel = impl.get("relative_source")
            if not isinstance(rel, str):
                continue
            if not any(hint in rel for hint in CACHE_PATH_HINTS):
                continue
            existing = impl.get("registry_metadata") if isinstance(impl.get("registry_metadata"), dict) else {}
            if existing.get("cache_derived"):
                continue
            changes.append(
                {
                    "type": "add_registry_metadata",
                    "module": str(module_path),
                    "skill": skill_name,
                    "metadata": {
                        "cache_derived": True,
                        "source_path": rel,
                        "annotated_by": "dream.trust_annotation",
                    },
                }
            )
        if not changes:
            continue
        result = create_skill_workshop_proposal_payload(
            title=f"Annotate cache-derived skills in {module_path.name}",
            evidence_records=[],
            scope={"modules": [str(module_path)], "targets": []},
            changes=changes,
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append({**result.payload, "patch_status": _dream_patch_status(result.payload)})
    return proposals


def _dream_heavy_tool_warning(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Scan skills in modules referenced by openclaw_import evidence for
    description or match.user_intent containing risky-tool keywords (sudo,
    rm -rf, docker, kubectl, ssh, scp, curl http*, wget http*). Each
    flagged skill becomes its own investigate_heavy_tool_usage proposal —
    intentionally not a patch, since deciding to gate or rewrite is a
    security-sensitive call best left to a reviewer.
    """
    proposals: list[Dict[str, Any]] = []
    module_paths = _modules_from_openclaw_evidence(evidence_files, diagnostics)
    for module_path in module_paths:
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if not isinstance(data, dict):
            continue
        skills = data.get("skills") or {}
        if not isinstance(skills, dict):
            continue
        for skill_name, skill in skills.items():
            if not isinstance(skill, dict):
                continue
            tokens: list[str] = []
            blob_parts: list[str] = []
            description = skill.get("description")
            if isinstance(description, str):
                blob_parts.append(description)
            match = skill.get("match")
            if isinstance(match, dict):
                user_intent = match.get("user_intent")
                if isinstance(user_intent, list):
                    blob_parts.extend(str(term) for term in user_intent)
                elif isinstance(user_intent, str):
                    blob_parts.append(user_intent)
            haystack = " ".join(blob_parts).lower()
            for keyword in HEAVY_TOOL_KEYWORDS:
                if keyword in haystack:
                    tokens.append(keyword.strip())
            if not tokens:
                continue
            change = {
                "type": "investigate_heavy_tool_usage",
                "module": str(module_path),
                "skill": skill_name,
                "matched_tokens": sorted(set(tokens)),
            }
            result = create_skill_workshop_proposal_payload(
                title=f"Heavy tool usage in {skill_name}",
                evidence_records=[],
                scope={"modules": [str(module_path)], "targets": []},
                changes=[change],
                evaluation_commands=[],
                out_dir=out_dir,
                timestamp=timestamp,
                write=write,
            )
            diagnostics.extend(result.diagnostics.items)
            if result.payload:
                proposals.append({**result.payload, "patch_status": _dream_patch_status(result.payload)})
    return proposals


def _dream_benchmark_case_suggester(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """For each `selected_target` that the plugin_payload evidence shows
    >=N times, propose an add_benchmark_case change so the route gets a
    permanent regression test. The target's module is resolved by
    scanning modules referenced in any openclaw_import evidence in the
    same evidence set; targets we can't locate are skipped.
    """
    selections_by_target: Dict[str, list[Dict[str, Any]]] = {}
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "plugin_payload":
                continue
            target = record.get("selected_target")
            if not isinstance(target, str) or not target:
                continue
            selections_by_target.setdefault(target, []).append(record)

    if not selections_by_target:
        return []

    target_to_module: Dict[str, Path] = {}
    for module_path in _modules_from_openclaw_evidence(evidence_files, diagnostics):
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        targets = data.get("targets") if isinstance(data.get("targets"), dict) else {}
        for target_name in targets:
            if target_name not in target_to_module:
                target_to_module[target_name] = module_path

    proposals: list[Dict[str, Any]] = []
    for target in sorted(selections_by_target):
        records = selections_by_target[target]
        if len(records) < DREAM_BENCHMARK_CASE_THRESHOLD:
            continue
        module_path = target_to_module.get(target)
        if module_path is None:
            continue
        # Most-frequent request for the case instruction.
        request_counts: Dict[str, int] = {}
        for record in records:
            summary = record.get("summary") or {}
            request = None
            if isinstance(summary, dict):
                request = summary.get("request")
            if not isinstance(request, str):
                # _summary_for_source("plugin_payload") doesn't store
                # request; fall back to record-level fingerprint hash
                # so we still produce a stable case id.
                request = record.get("request_fingerprint") or ""
            request_counts[request] = request_counts.get(request, 0) + 1
        best_request, _ = max(request_counts.items(), key=lambda kv: kv[1])
        change = {
            "type": "add_benchmark_case",
            "module": str(module_path),
            "target": target,
            "case": {
                "id": f"popular-{_sha256_text(target)[7:19]}",
                "instruction": best_request,
                "expected_target": target,
            },
        }
        result = create_skill_workshop_proposal_payload(
            title=f"Add benchmark case for popular route {target}",
            evidence_records=records,
            scope={"modules": [str(module_path)], "targets": [target]},
            changes=[change],
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append({**result.payload, "patch_status": _dream_patch_status(result.payload)})
    return proposals


_OPENCLAW_BUCKET_SUFFIXES = (".tmp", "plugins", "skills", "vendor_imports", "uncategorized")


_LOW_SIGNAL_BOILERPLATE_SUBSTRINGS = (
    "you must use this",
    "use this skill when",
    "use this when",
    "mandatory prerequisite",
    "never call",
    "you need to",
)


def _dream_low_signal_terms(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Proactive noise detector. Scans modules listed in `openclaw_import`
    evidence and emits `prune_match_terms` proposals for entries that
    are clearly low-signal:

      - bucket-suffix artifacts from auto-import (e.g. 'brainstorming
        .tmp', 'slack uncategorized')
      - common boilerplate / instruction phrases (e.g. 'You MUST use
        this', 'Use this skill when ...')

    Multi-word genuine user intents are preserved. One proposal is
    produced per module that has any pruneable terms; per-skill prune
    changes are grouped under that proposal so the patch generator can
    apply them atomically. Skill `match.user_intent` AND its matching
    `skill.<name>` target are both cleaned.
    """
    module_paths_seen: set[Path] = set()
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "openclaw_import":
                continue
            refs = record.get("artifact_refs") or {}
            root = refs.get("root_agentmakefile")
            module_relpaths = refs.get("module_paths") or []
            if not isinstance(root, str) or not isinstance(module_relpaths, list):
                continue
            root_dir = Path(root).parent
            for rel in module_relpaths:
                if not isinstance(rel, str):
                    continue
                module_paths_seen.add((root_dir / rel).resolve())

    proposals: list[Dict[str, Any]] = []
    for module_path in sorted(module_paths_seen, key=lambda p: str(p)):
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        prune_changes = _low_signal_prune_changes_for_module(module_path, data)
        if not prune_changes:
            continue
        title = f"Prune low-signal match terms in {module_path.name}"
        result = create_skill_workshop_proposal_payload(
            title=title,
            evidence_records=[],
            scope={"modules": [str(module_path)], "targets": []},
            changes=prune_changes,
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append(
                {
                    **result.payload,
                    "patch_status": _dream_patch_status(result.payload),
                }
            )
    return proposals


def _low_signal_prune_changes_for_module(
    module_path: Path, data: Dict[str, Any]
) -> list[Dict[str, Any]]:
    """For each skill in `data` collect its low-signal user_intent terms
    (bucket-suffix + boilerplate). When a skill has any, emit one
    `prune_match_terms` change against the matching `skill.<name>`
    target (the selector matches at the target level — pruning only
    the skill entry would leave the noise active for routing).
    """
    skills = data.get("skills")
    targets = data.get("targets")
    if not isinstance(skills, dict) or not isinstance(targets, dict):
        return []
    changes: list[Dict[str, Any]] = []
    for skill_name in sorted(skills):
        skill_body = skills.get(skill_name)
        if not isinstance(skill_body, dict):
            continue
        target_name = f"skill.{skill_name}"
        target_body = targets.get(target_name)
        if not isinstance(target_body, dict):
            continue
        terms = ((target_body.get("match") or {}).get("user_intent")) or []
        if not isinstance(terms, list):
            continue
        low_signal = _select_low_signal_terms(terms)
        if not low_signal:
            continue
        changes.append(
            {
                "type": "prune_match_terms",
                "module": str(module_path),
                "target": target_name,
                "remove_terms": low_signal,
            }
        )
    return changes


def _select_low_signal_terms(terms: list[Any]) -> list[str]:
    selected: list[str] = []
    for term in terms:
        text = str(term).strip()
        if not text:
            continue
        if _is_bucket_suffix_term(text) or _has_boilerplate_substring(text):
            if text not in selected:
                selected.append(text)
    return selected


def _is_bucket_suffix_term(text: str) -> bool:
    """True for terms that end with ` <bucket>` where <bucket> is one of
    the OpenClaw category names. Tokenises on whitespace so we don't
    accidentally match a genuine intent that happens to contain the
    word `plugins` mid-sentence.
    """
    tokens = text.split()
    if len(tokens) < 2:
        return False
    return tokens[-1] in _OPENCLAW_BUCKET_SUFFIXES


def _has_boilerplate_substring(text: str) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in _LOW_SIGNAL_BOILERPLATE_SUBSTRINGS)


DREAM_CORPUS_WIDE_TARGET_THRESHOLD = 3


def _dream_corpus_wide_low_signal_terms(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Second-round noise detector. Scans modules listed in
    openclaw_import evidence and emits `prune_match_terms` proposals
    for user_intent entries that fail a corpus-wide test of utility:

      - Cross-target frequency: a term that appears in
        DREAM_CORPUS_WIDE_TARGET_THRESHOLD+ different targets of the
        same module is broad by definition — pruning it from every
        target it appears on is safe (no routing decision was riding
        on it anyway).

    Includes a **name-preservation guard**: if all of a target's
    `match.user_intent` entries are pruning candidates AND none of the
    survivors would still contain a token from the target's name, the
    guard keeps the most name-bearing candidate. This avoids the
    "brainstorming target with 0 name-bearing terms after cleanup"
    regression observed after step #1 pruning.
    """
    module_paths_seen: set[Path] = set()
    for evidence_file in evidence_files:
        for record in _load_evidence_records([evidence_file], diagnostics):
            if record.get("source") != "openclaw_import":
                continue
            refs = record.get("artifact_refs") or {}
            root = refs.get("root_agentmakefile")
            module_relpaths = refs.get("module_paths") or []
            if not isinstance(root, str) or not isinstance(module_relpaths, list):
                continue
            root_dir = Path(root).parent
            for rel in module_relpaths:
                if not isinstance(rel, str):
                    continue
                module_paths_seen.add((root_dir / rel).resolve())

    proposals: list[Dict[str, Any]] = []
    for module_path in sorted(module_paths_seen, key=lambda p: str(p)):
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        changes = _corpus_wide_prune_changes(module_path, data)
        if not changes:
            continue
        result = create_skill_workshop_proposal_payload(
            title=f"Prune corpus-wide low-signal terms in {module_path.name}",
            evidence_records=[],
            scope={"modules": [str(module_path)], "targets": []},
            changes=changes,
            evaluation_commands=[],
            out_dir=out_dir,
            timestamp=timestamp,
            write=write,
        )
        diagnostics.extend(result.diagnostics.items)
        if result.payload:
            proposals.append(
                {
                    **result.payload,
                    "patch_status": _dream_patch_status(result.payload),
                }
            )
    return proposals


def _corpus_wide_prune_changes(
    module_path: Path, data: Dict[str, Any]
) -> list[Dict[str, Any]]:
    targets = data.get("targets")
    if not isinstance(targets, dict):
        return []

    # Pass 1: count cross-target term frequency.
    freq: Dict[str, int] = {}
    target_terms: Dict[str, list[str]] = {}
    for target_name, target_body in targets.items():
        if not isinstance(target_body, dict):
            continue
        match = target_body.get("match") if isinstance(target_body.get("match"), dict) else None
        if match is None:
            continue
        user_intent = match.get("user_intent")
        if isinstance(user_intent, str):
            user_intent = [user_intent]
        if not isinstance(user_intent, list):
            continue
        seen_in_this_target: set[str] = set()
        for term in user_intent:
            text = str(term).strip()
            if not text:
                continue
            seen_in_this_target.add(text)
        target_terms[target_name] = list(user_intent)
        for term in seen_in_this_target:
            freq[term] = freq.get(term, 0) + 1

    broad_terms = {
        term for term, count in freq.items()
        if count >= DREAM_CORPUS_WIDE_TARGET_THRESHOLD
    }
    if not broad_terms:
        return []

    # Pass 2: per-target prune list, with preservation guard.
    changes: list[Dict[str, Any]] = []
    for target_name in sorted(target_terms):
        terms = target_terms[target_name]
        candidate_removes = [
            str(term) for term in terms if str(term).strip() in broad_terms
        ]
        if not candidate_removes:
            continue
        preserved = _apply_name_preservation_guard(target_name, terms, candidate_removes)
        if not preserved:
            continue
        changes.append(
            {
                "type": "prune_match_terms",
                "module": str(module_path),
                "target": target_name,
                "remove_terms": preserved,
            }
        )
    return changes


def _name_tokens_for_target(target_name: str) -> set[str]:
    """Extract a set of lowercased name tokens from the target name.
    For openclaw-style `skill.<bucket>.<skill-name>` targets, this
    yields `{bucket, skill, name, components}` so the preservation
    guard can detect "this term carries the skill's identifier".
    """
    base = target_name
    if base.startswith("skill."):
        base = base[len("skill."):]
    raw = base.replace(".", " ").replace("-", " ").replace("_", " ").lower()
    return {token for token in raw.split() if token}


def _term_carries_name(term: str, name_tokens: set[str]) -> bool:
    """True when `term` contains a word that shares a 4+ char common
    prefix with a name token (or matches exactly for shorter
    acronyms). Catches morphological variants like plan/planning,
    brainstorm/brainstorming without pulling in an external stemmer.
    """
    if not name_tokens:
        return False
    words = [
        word.lower()
        for word in str(term).replace("-", " ").replace(".", " ").split()
        if len(word) >= 3
    ]
    for word in words:
        for token in name_tokens:
            if len(token) < 3:
                continue
            if word == token:
                return True
            common = 0
            for a, b in zip(word, token):
                if a == b:
                    common += 1
                else:
                    break
            if common >= 4:
                return True
    return False


def _apply_name_preservation_guard(
    target_name: str,
    all_terms: list[str],
    candidate_removes: list[str],
) -> list[str]:
    """If applying `candidate_removes` would strip every name-bearing
    term from `all_terms`, keep the single most name-bearing candidate
    (longest such term) so the target stays routable on its own name.

    Returns the final remove list (possibly shorter than the input).
    """
    if not candidate_removes:
        return []
    name_tokens = _name_tokens_for_target(target_name)
    if not name_tokens:
        return list(candidate_removes)
    remove_set = set(candidate_removes)
    surviving = [t for t in all_terms if str(t) not in remove_set]
    has_name_in_survivors = any(_term_carries_name(str(t), name_tokens) for t in surviving)
    if has_name_in_survivors:
        return list(candidate_removes)
    name_bearing_candidates = sorted(
        (term for term in candidate_removes if _term_carries_name(term, name_tokens)),
        key=lambda term: (-len(term), term),
    )
    if not name_bearing_candidates:
        # Nothing in the prune list carries a name token either — pull
        # back the longest candidate as a generic survivor so the target
        # is never left with an empty user_intent.
        longest = max(candidate_removes, key=len)
        return [term for term in candidate_removes if term != longest]
    keep = name_bearing_candidates[0]
    return [term for term in candidate_removes if term != keep]


def _dream_category_resplit(
    evidence_files: list[Path],
    out_dir: Union[Path, str],
    timestamp: Optional[str],
    write: bool,
    diagnostics: Diagnostics,
) -> list[Dict[str, Any]]:
    """Suggest splitting an already-imported module when many of its
    skills cluster under a common second-level path segment in their
    `implementation.relative_source`. Each sub-category that breaches the
    threshold becomes one `investigate_category_resplit` proposal — a
    flag for human review, not an automatic patch (the importer's
    scan-time category split runs first; this detector fires on the
    re-split case where the imported tree itself contains rich sub-
    structure).
    """
    proposals: list[Dict[str, Any]] = []
    for module_path in _modules_from_openclaw_evidence(evidence_files, diagnostics):
        if not module_path.exists():
            continue
        try:
            data = yaml.safe_load(module_path.read_text(encoding="utf-8")) or {}
        except OSError:
            continue
        if not isinstance(data, dict):
            continue
        groups = _category_clusters(data)
        for sub_category in sorted(groups):
            members = groups[sub_category]
            if len(members) < DREAM_CATEGORY_RESPLIT_THRESHOLD:
                continue
            change = {
                "type": "investigate_category_resplit",
                "module": str(module_path),
                "sub_category": sub_category,
                "skill_count": len(members),
                "sample_skills": sorted(members)[:5],
            }
            result = create_skill_workshop_proposal_payload(
                title=f"Investigate re-splitting {module_path.name} into sub-module {sub_category}",
                evidence_records=[],
                scope={"modules": [str(module_path)], "targets": []},
                changes=[change],
                evaluation_commands=[],
                out_dir=out_dir,
                timestamp=timestamp,
                write=write,
            )
            diagnostics.extend(result.diagnostics.items)
            if result.payload:
                proposals.append({**result.payload, "patch_status": _dream_patch_status(result.payload)})
    return proposals


def _dream_patch_status(wrapper: Dict[str, Any]) -> str:
    """Classify whether a dream-emitted proposal would generate a patch.

    `wrapper` is the SkillWorkshopProposalResult.payload dict, which holds
    the actual proposal core under "proposal". Returns "would_generate_patch"
    if any change type is in SUPPORTED_PATCH_TYPES, otherwise
    "skipped_unsupported_change".
    """
    proposal = wrapper.get("proposal")
    if not isinstance(proposal, dict):
        return "skipped_unsupported_change"
    changes = proposal.get("changes")
    if not isinstance(changes, list):
        return "skipped_unsupported_change"
    for change in changes:
        if isinstance(change, dict) and change.get("type") in SUPPORTED_PATCH_TYPES:
            return "would_generate_patch"
    return "skipped_unsupported_change"
