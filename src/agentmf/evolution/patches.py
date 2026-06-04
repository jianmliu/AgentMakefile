"""Evolution patches (split from evolution.py — in-tree package, same public API)."""
from __future__ import annotations

from agentmf.diagnostics import Diagnostics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union
import difflib
import yaml
from agentmf.evolution.evidence import _sha256_json
from agentmf.evolution.proposals import _load_proposal


SUPPORTED_PATCH_TYPES = {
    "update_match_terms",
    "merge_duplicate_targets",
    "prune_match_terms",
    "add_target",
    "add_dependency",
    "deprecate_skill",
    "add_registry_metadata",
    "add_benchmark_case",
    "update_permission_guard",
    "split_module",
}


@dataclass
class CandidatePatchResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_candidate_patch_payload(
    *,
    proposal_file: Union[Path, str],
    out_dir: Union[Path, str] = Path(".agentmf/evolution/candidates"),
    write: bool = False,
) -> CandidatePatchResult:
    diagnostics = Diagnostics()
    proposal = _load_proposal(proposal_file, diagnostics)
    if proposal is None or diagnostics.has_errors:
        return CandidatePatchResult(diagnostics)

    candidate_files, unsupported = _candidate_source_files_for_proposal(proposal, diagnostics)
    if diagnostics.has_errors:
        return CandidatePatchResult(diagnostics)

    proposal_id = str(proposal.get("proposal_id", _sha256_json(proposal)))
    patch = _render_unified_patch(candidate_files)
    patch_status = "generated" if candidate_files else "skipped_unsupported_change"
    destination = Path(out_dir)
    patch_path = destination / f"{proposal_id}.patch"
    if write and patch_status == "generated":
        try:
            destination.mkdir(parents=True, exist_ok=True)
            patch_path.write_text(patch, encoding="utf-8")
        except OSError as exc:
            diagnostics.error("AMF228", f"could not write candidate patch: {patch_path}", "evo.patch.out_dir", str(exc))
            return CandidatePatchResult(diagnostics)

    return CandidatePatchResult(
        diagnostics,
        {
            "version": 1,
            "mode": "candidate_patch",
            "proposal_id": proposal_id,
            "patch_status": patch_status,
            "unsupported_changes": unsupported,
            "patch": None if write else patch,
            "paths": {"patch": str(patch_path)},
            "touched_files": [str(file["source_path"]) for file in candidate_files],
        },
    )


def _candidate_source_files_for_proposal(
    proposal: Dict[str, Any],
    diagnostics: Diagnostics,
) -> tuple[list[Dict[str, Any]], list[Dict[str, Any]]]:
    source_map: Dict[Path, Dict[str, Any]] = {}
    unsupported = []
    for change in proposal.get("changes", []):
        if not isinstance(change, dict):
            unsupported.append({"type": "unknown", "reason": "change is not an object"})
            continue
        change_type = change.get("type")
        if change_type not in SUPPORTED_PATCH_TYPES:
            unsupported.append({"type": change_type or "unknown", "reason": "patch class is not implemented yet"})
            continue
        if change_type == "update_match_terms":
            _apply_update_match_terms_change(change, proposal, source_map, diagnostics)
        elif change_type == "merge_duplicate_targets":
            _apply_merge_duplicate_targets_change(change, proposal, source_map, diagnostics)
        elif change_type == "prune_match_terms":
            _apply_prune_match_terms_change(change, proposal, source_map, diagnostics)
        elif change_type == "add_target":
            _apply_add_target_change(change, proposal, source_map, diagnostics)
        elif change_type == "add_dependency":
            _apply_add_dependency_change(change, proposal, source_map, diagnostics)
        elif change_type == "deprecate_skill":
            _apply_deprecate_skill_change(change, proposal, source_map, diagnostics)
        elif change_type == "add_registry_metadata":
            _apply_add_registry_metadata_change(change, proposal, source_map, diagnostics)
        elif change_type == "add_benchmark_case":
            _apply_add_benchmark_case_change(change, proposal, source_map, diagnostics)
        elif change_type == "update_permission_guard":
            _apply_update_permission_guard_change(change, proposal, source_map, diagnostics)
        elif change_type == "split_module":
            _apply_split_module_change(change, proposal, source_map, diagnostics)

    candidate_files = []
    for source_path, record in source_map.items():
        candidate_content = yaml.safe_dump(record["data"], sort_keys=False)
        candidate_files.append(
            {
                "source_path": source_path,
                "original_content": record["original_content"],
                "candidate_content": candidate_content,
            }
        )
    return candidate_files, unsupported


def _apply_update_match_terms_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    module_path = _change_module_path(change, proposal)
    target_name = change.get("target") or _first(proposal.get("scope", {}).get("targets", []))
    terms = change.get("add_terms") or change.get("terms") or []
    if not module_path or not target_name or not isinstance(terms, list):
        diagnostics.error(
            "AMF226",
            "update_match_terms requires module, target, and add_terms",
            "evo.patch.changes",
        )
        return
    source_path = Path(str(module_path))
    record = _load_module_record(source_path, source_map, diagnostics)
    if record is None:
        return

    data = record["data"]
    targets = data.setdefault("targets", {})
    if target_name not in targets:
        diagnostics.error("AMF227", f"proposal target not found: {target_name}", "evo.patch.target")
        return
    target = targets[target_name]
    match = target.setdefault("match", {})
    user_intent = match.setdefault("user_intent", [])
    if isinstance(user_intent, str):
        user_intent = [user_intent]
    if not isinstance(user_intent, list):
        diagnostics.error("AMF226", f"target match.user_intent must be a list: {target_name}", "evo.patch.target")
        return
    for term in terms:
        term_text = str(term)
        if term_text and term_text not in user_intent:
            user_intent.append(term_text)
    match["user_intent"] = user_intent


def _apply_prune_match_terms_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Mirror of update_match_terms: remove specified terms from a target's
    match.user_intent. Used when an overly-broad term (e.g. a stray single
    word) is causing false-positive routing.
    """
    module_path = _change_module_path(change, proposal)
    target_name = change.get("target") or _first(proposal.get("scope", {}).get("targets", []))
    terms = change.get("remove_terms") or change.get("terms") or []
    if not module_path or not target_name or not isinstance(terms, list):
        diagnostics.error(
            "AMF226",
            "prune_match_terms requires module, target, and remove_terms",
            "evo.patch.changes",
        )
        return
    source_path = Path(str(module_path))
    record = _load_module_record(source_path, source_map, diagnostics)
    if record is None:
        return

    data = record["data"]
    targets = data.get("targets") or {}
    if target_name not in targets:
        diagnostics.error("AMF227", f"proposal target not found: {target_name}", "evo.patch.target")
        return
    target = targets[target_name]
    match = target.get("match") if isinstance(target.get("match"), dict) else None
    if match is None:
        return
    user_intent = match.get("user_intent")
    if isinstance(user_intent, str):
        user_intent = [user_intent]
    if not isinstance(user_intent, list):
        diagnostics.error("AMF226", f"target match.user_intent must be a list: {target_name}", "evo.patch.target")
        return
    remove_set = {str(term) for term in terms}
    match["user_intent"] = [term for term in user_intent if str(term) not in remove_set]
    # OpenClaw-style imports keep a parallel `skills.<name>.match.user_intent`
    # alongside each `skill.<name>` target. The selector matches against
    # BOTH lists at runtime, so pruning only the target side leaves the
    # noise active. When the target is named `skill.<X>` and a mirror
    # `skills.<X>` entry exists, scrub the same terms there too.
    if target_name.startswith("skill."):
        mirror_skill_name = target_name[len("skill."):]
        skills = data.get("skills")
        if isinstance(skills, dict):
            mirror = skills.get(mirror_skill_name)
            if isinstance(mirror, dict):
                mirror_match = mirror.get("match") if isinstance(mirror.get("match"), dict) else None
                if mirror_match is not None:
                    mirror_intent = mirror_match.get("user_intent")
                    if isinstance(mirror_intent, str):
                        mirror_intent = [mirror_intent]
                    if isinstance(mirror_intent, list):
                        mirror_match["user_intent"] = [
                            term for term in mirror_intent if str(term) not in remove_set
                        ]


def _apply_add_target_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Insert a brand-new target into a module's targets dict."""
    module_path = _change_module_path(change, proposal)
    target_name = change.get("target") or change.get("name")
    definition = change.get("definition")
    if not module_path or not target_name or not isinstance(definition, dict):
        diagnostics.error(
            "AMF226",
            "add_target requires module, target, and definition",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    data = record["data"]
    targets = data.setdefault("targets", {})
    if target_name in targets:
        diagnostics.error(
            "AMF233",
            f"add_target refuses to overwrite existing target: {target_name}",
            "evo.patch.target",
        )
        return
    targets[target_name] = dict(definition)


def _apply_add_dependency_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Append dep edges to an existing target's `deps` list."""
    module_path = _change_module_path(change, proposal)
    target_name = change.get("target") or _first(proposal.get("scope", {}).get("targets", []))
    add_deps = change.get("add_deps") or change.get("deps") or []
    if not module_path or not target_name or not isinstance(add_deps, list):
        diagnostics.error(
            "AMF226",
            "add_dependency requires module, target, and add_deps",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    targets = record["data"].setdefault("targets", {})
    if target_name not in targets:
        diagnostics.error("AMF227", f"proposal target not found: {target_name}", "evo.patch.target")
        return
    target = targets[target_name]
    deps = target.setdefault("deps", [])
    if not isinstance(deps, list):
        diagnostics.error("AMF226", f"target deps must be a list: {target_name}", "evo.patch.target")
        return
    for dep in add_deps:
        dep_text = str(dep)
        if dep_text and dep_text not in deps:
            deps.append(dep_text)


def _apply_deprecate_skill_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Annotate a skill as deprecated (implementation.deprecated=true plus
    optional reason). Does not delete; preserves auditability.
    """
    module_path = _change_module_path(change, proposal)
    skill_name = change.get("skill")
    reason = change.get("reason")
    replaced_by = change.get("replaced_by")
    if not module_path or not skill_name:
        diagnostics.error(
            "AMF226",
            "deprecate_skill requires module and skill",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    skills = record["data"].get("skills") or {}
    if not isinstance(skills, dict) or skill_name not in skills:
        diagnostics.error("AMF227", f"proposal skill not found: {skill_name}", "evo.patch.skill")
        return
    skill = skills[skill_name]
    impl = skill.setdefault("implementation", {})
    if not isinstance(impl, dict):
        diagnostics.error("AMF226", f"skill implementation must be a mapping: {skill_name}", "evo.patch.skill")
        return
    impl["deprecated"] = True
    if reason:
        impl["deprecation_reason"] = str(reason)
    if replaced_by:
        impl["replaced_by"] = str(replaced_by)


def _apply_add_registry_metadata_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Attach registry-source metadata (origin, version, signed-by, …) to a
    skill so downstream tools can audit provenance.
    """
    module_path = _change_module_path(change, proposal)
    skill_name = change.get("skill")
    metadata = change.get("metadata")
    if not module_path or not skill_name or not isinstance(metadata, dict):
        diagnostics.error(
            "AMF226",
            "add_registry_metadata requires module, skill, and metadata",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    skills = record["data"].get("skills") or {}
    if not isinstance(skills, dict) or skill_name not in skills:
        diagnostics.error("AMF227", f"proposal skill not found: {skill_name}", "evo.patch.skill")
        return
    skill = skills[skill_name]
    impl = skill.setdefault("implementation", {})
    if not isinstance(impl, dict):
        diagnostics.error("AMF226", f"skill implementation must be a mapping: {skill_name}", "evo.patch.skill")
        return
    registry = impl.setdefault("registry_metadata", {})
    if not isinstance(registry, dict):
        diagnostics.error("AMF226", f"skill registry_metadata must be a mapping: {skill_name}", "evo.patch.skill")
        return
    registry.update(metadata)


def _apply_add_benchmark_case_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Append a benchmark case to a target's output_schema.benchmark_cases
    list (kept inside the free-form output_schema dict so we don't need
    a strict-model expansion).
    """
    module_path = _change_module_path(change, proposal)
    target_name = change.get("target") or _first(proposal.get("scope", {}).get("targets", []))
    case = change.get("case")
    if not module_path or not target_name or not isinstance(case, dict):
        diagnostics.error(
            "AMF226",
            "add_benchmark_case requires module, target, and case",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    targets = record["data"].setdefault("targets", {})
    if target_name not in targets:
        diagnostics.error("AMF227", f"proposal target not found: {target_name}", "evo.patch.target")
        return
    target = targets[target_name]
    output_schema = target.setdefault("output_schema", {})
    if not isinstance(output_schema, dict):
        diagnostics.error("AMF226", f"target output_schema must be a mapping: {target_name}", "evo.patch.target")
        return
    cases = output_schema.setdefault("benchmark_cases", [])
    if not isinstance(cases, list):
        diagnostics.error("AMF226", f"benchmark_cases must be a list: {target_name}", "evo.patch.target")
        return
    if case not in cases:
        cases.append(dict(case))


def _apply_update_permission_guard_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Set permissions[tool][pattern] = action (allow / ask / deny)."""
    module_path = _change_module_path(change, proposal)
    tool = change.get("tool")
    pattern = change.get("pattern")
    action = change.get("action")
    if not module_path or not tool or not pattern or action not in {"allow", "ask", "deny"}:
        diagnostics.error(
            "AMF226",
            "update_permission_guard requires module, tool, pattern, and action (allow|ask|deny)",
            "evo.patch.changes",
        )
        return
    record = _load_module_record(Path(str(module_path)), source_map, diagnostics)
    if record is None:
        return
    data = record["data"]
    permissions = data.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        diagnostics.error("AMF226", "module permissions must be a mapping", "evo.patch.module")
        return
    # Support both flat (`permissions.<tool>.<pattern>`) and nested
    # (`permissions.rules.<tool>.<pattern>`) layouts. Prefer the layout
    # already present in the file; default to flat for new entries.
    rules = permissions.get("rules") if isinstance(permissions.get("rules"), dict) else None
    bucket = rules if rules is not None else permissions
    tool_rules = bucket.setdefault(tool, {})
    if not isinstance(tool_rules, dict):
        diagnostics.error("AMF226", f"permissions for tool must be a mapping: {tool}", "evo.patch.permissions")
        return
    tool_rules[pattern] = action


def _apply_split_module_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    """Move named skills + targets from a source module into a new module
    file. The new module's record is added to source_map with empty
    original_content so the candidate-patch / evaluate steps treat it
    as a fresh file write.
    """
    source_module = change.get("source_module")
    target_module = change.get("target_module")
    move_skills = change.get("skills") or []
    move_targets = change.get("targets") or []
    if not source_module or not target_module or not isinstance(move_skills, list) or not isinstance(move_targets, list):
        diagnostics.error(
            "AMF226",
            "split_module requires source_module, target_module, skills, and targets",
            "evo.patch.changes",
        )
        return
    if not move_skills and not move_targets:
        diagnostics.error(
            "AMF226",
            "split_module requires at least one skill or target to move",
            "evo.patch.changes",
        )
        return
    source_path = Path(str(source_module))
    target_path = Path(str(target_module))
    if source_path == target_path:
        diagnostics.error(
            "AMF226",
            "split_module source and target must differ",
            "evo.patch.changes",
        )
        return

    source_record = _load_module_record(source_path, source_map, diagnostics)
    if source_record is None:
        return

    target_record = source_map.get(target_path)
    if target_record is None:
        if target_path.exists():
            target_record = _load_module_record(target_path, source_map, diagnostics)
            if target_record is None:
                return
        else:
            target_record = {
                "original_content": "",
                "data": {"version": source_record["data"].get("version", "0.1"), "skills": {}, "targets": {}},
            }
            source_map[target_path] = target_record

    source_skills = source_record["data"].get("skills") or {}
    source_targets = source_record["data"].get("targets") or {}
    new_skills = target_record["data"].setdefault("skills", {})
    new_targets = target_record["data"].setdefault("targets", {})

    for skill_name in move_skills:
        if skill_name not in source_skills:
            continue
        new_skills[skill_name] = source_skills[skill_name]
        del source_skills[skill_name]
    for target_name in move_targets:
        if target_name not in source_targets:
            continue
        new_targets[target_name] = source_targets[target_name]
        del source_targets[target_name]


def _apply_merge_duplicate_targets_change(
    change: Dict[str, Any],
    proposal: Dict[str, Any],
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> None:
    duplicate_names = change.get("duplicate_original_names")
    if not isinstance(duplicate_names, dict) or not duplicate_names:
        diagnostics.error(
            "AMF226",
            "merge_duplicate_targets requires duplicate_original_names mapping",
            "evo.patch.changes",
        )
        return

    module_paths = change.get("modules") or proposal.get("scope", {}).get("modules", [])
    if change.get("module"):
        module_paths = [change["module"]]
    if not module_paths:
        diagnostics.error(
            "AMF226",
            "merge_duplicate_targets requires at least one module in scope or change",
            "evo.patch.changes",
        )
        return

    records = []
    for raw_path in module_paths:
        source_path = Path(str(raw_path))
        record = _load_module_record(source_path, source_map, diagnostics)
        if record is not None:
            records.append(record)
    _merge_duplicates_across_modules(records, duplicate_names)


def _load_module_record(
    source_path: Path,
    source_map: Dict[Path, Dict[str, Any]],
    diagnostics: Diagnostics,
) -> Optional[Dict[str, Any]]:
    record = source_map.get(source_path)
    if record is not None:
        return record
    try:
        original_content = source_path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error(
            "AMF226",
            f"could not read AgentMakefile source: {source_path}",
            "evo.patch.module",
            str(exc),
        )
        return None
    data = yaml.safe_load(original_content) or {}
    if not isinstance(data, dict):
        diagnostics.error("AMF226", f"AgentMakefile source must be a mapping: {source_path}", "evo.patch.module")
        return None
    record = {"original_content": original_content, "data": data}
    source_map[source_path] = record
    return record


def _merge_duplicates_across_modules(
    records: List[Dict[str, Any]],
    duplicate_names: Dict[str, Any],
) -> None:
    """Build a global relative_source -> (module_data, skill_name) map across
    every loaded module in scope, then merge each duplicate into its primary.

    Handles same-module and cross-module dup groups uniformly: the primary's
    `match.user_intent` and `merged_duplicates` are appended in whichever
    module holds the primary, and the duplicate is removed (with its
    `skill.<name>` target and `metadata.skill_count`) from whichever module
    holds it.
    """
    rel_to_entry: Dict[str, tuple[Dict[str, Any], str]] = {}
    for record in records:
        data = record["data"]
        skills = data.get("skills")
        if not isinstance(skills, dict):
            continue
        for skill_name, skill in skills.items():
            if not isinstance(skill, dict):
                continue
            impl = skill.get("implementation")
            if not isinstance(impl, dict):
                continue
            rel = impl.get("relative_source")
            if isinstance(rel, str):
                rel_to_entry[rel] = (data, skill_name)

    for original_name, paths in duplicate_names.items():
        if not isinstance(paths, list) or len(paths) < 2:
            continue
        # Pick the canonical primary deterministically rather than trusting
        # input order: .tmp/ extraction caches and plugins/cache/ paths
        # are version-pinned and GC'd, so keeping them as primary risks
        # routing dead symlinks. Prefer clean install locations (~/.codex/
        # skills, .system, direct marketplace plugins).
        ranked_paths = sorted(paths, key=_canonical_path_rank)
        primary_path = ranked_paths[0]
        primary_entry = rel_to_entry.get(str(primary_path))
        if primary_entry is None:
            continue
        # Duplicate-merge logic below expects everything past the primary
        # to be a "duplicate to drop", and the order must match the
        # ranked list (not the input paths list).
        rest_paths = ranked_paths[1:]
        primary_data, primary_skill_name = primary_entry
        primary_skills = primary_data.get("skills") if isinstance(primary_data.get("skills"), dict) else {}
        primary_skill = primary_skills.get(primary_skill_name)
        if not isinstance(primary_skill, dict):
            continue
        primary_targets = primary_data.get("targets") if isinstance(primary_data.get("targets"), dict) else {}
        primary_target_name = f"skill.{primary_skill_name}"
        primary_target = primary_targets.get(primary_target_name) if isinstance(primary_targets.get(primary_target_name), dict) else None

        for duplicate_path in rest_paths:
            duplicate_entry = rel_to_entry.get(str(duplicate_path))
            if duplicate_entry is None:
                continue
            duplicate_data, duplicate_skill_name = duplicate_entry
            if duplicate_data is primary_data and duplicate_skill_name == primary_skill_name:
                continue
            duplicate_skills = duplicate_data.get("skills") if isinstance(duplicate_data.get("skills"), dict) else {}
            duplicate_skill = duplicate_skills.get(duplicate_skill_name)
            if not isinstance(duplicate_skill, dict):
                continue
            _merge_user_intent(primary_skill, duplicate_skill)
            duplicate_targets = duplicate_data.get("targets") if isinstance(duplicate_data.get("targets"), dict) else {}
            duplicate_target_name = f"skill.{duplicate_skill_name}"
            duplicate_target = duplicate_targets.get(duplicate_target_name) if isinstance(duplicate_targets.get(duplicate_target_name), dict) else None
            if primary_target is not None and duplicate_target is not None:
                _merge_user_intent(primary_target, duplicate_target)
            _record_merged_duplicate(primary_skill, duplicate_skill_name, duplicate_skill, str(original_name))
            del duplicate_skills[duplicate_skill_name]
            if duplicate_target_name in duplicate_targets:
                del duplicate_targets[duplicate_target_name]
            duplicate_metadata = duplicate_data.get("metadata")
            if isinstance(duplicate_metadata, dict):
                count = duplicate_metadata.get("skill_count")
                if isinstance(count, int):
                    duplicate_metadata["skill_count"] = max(0, count - 1)


def _canonical_path_rank(rel_path: str) -> tuple:
    """Sort key for picking a canonical copy when several `SKILL.md` paths
    name the same `original_name`. Lower rank = preferred as primary.

    Penalises paths that are known to be ephemeral / mirror copies:
      - `.tmp/...` (plugin extraction cache, GC'd between runs)
      - segments containing `cache` (plugins/cache/<plugin>/<version>/...)
      - segments containing `marketplaces` (mirror; the direct plugin
        install dir is more canonical)
    Rewards canonical install locations:
      - `.system/` (built-in Codex/Claude skills)
      - `vendor_imports/` (publisher-curated catalog)

    Tiebreaks by path length (shorter == cleaner) then lex order so the
    selection is fully deterministic regardless of input list order.
    """
    text = str(rel_path)
    parts = [part.lower() for part in text.split("/") if part]
    penalty = 0
    for part in parts:
        if part == ".tmp" or part.startswith(".tmp"):
            penalty += 1000
            break
    for part in parts:
        if "cache" in part:
            penalty += 100
            break
    if any(part == "marketplaces" for part in parts):
        penalty += 10
    if any(part == ".system" for part in parts):
        penalty -= 5
    if any(part == "vendor_imports" for part in parts):
        penalty -= 2
    return (penalty, len(text), text)


def _merge_user_intent(primary: Dict[str, Any], duplicate: Dict[str, Any]) -> None:
    duplicate_match = duplicate.get("match")
    if not isinstance(duplicate_match, dict):
        return
    duplicate_intent = duplicate_match.get("user_intent")
    if isinstance(duplicate_intent, str):
        duplicate_intent = [duplicate_intent]
    if not isinstance(duplicate_intent, list):
        return
    primary_match = primary.setdefault("match", {})
    if not isinstance(primary_match, dict):
        return
    primary_intent = primary_match.get("user_intent")
    if isinstance(primary_intent, str):
        primary_intent = [primary_intent]
    if not isinstance(primary_intent, list):
        primary_intent = []
    for term in duplicate_intent:
        term_text = str(term)
        if term_text and term_text not in primary_intent:
            primary_intent.append(term_text)
    primary_match["user_intent"] = primary_intent


def _record_merged_duplicate(
    primary_skill: Dict[str, Any],
    duplicate_name: str,
    duplicate_skill: Dict[str, Any],
    original_name: str,
) -> None:
    impl = primary_skill.setdefault("implementation", {})
    if not isinstance(impl, dict):
        return
    merged = impl.setdefault("merged_duplicates", [])
    if not isinstance(merged, list):
        return
    dup_impl = duplicate_skill.get("implementation") if isinstance(duplicate_skill.get("implementation"), dict) else {}
    merged.append(
        {
            "skill": duplicate_name,
            "source": dup_impl.get("source"),
            "relative_source": dup_impl.get("relative_source"),
            "original_name": dup_impl.get("original_name") or original_name,
        }
    )


def _change_module_path(change: Dict[str, Any], proposal: Dict[str, Any]) -> Optional[str]:
    module = change.get("module")
    if module:
        return str(module)
    return _first(proposal.get("scope", {}).get("modules", []))


def _first(values: Any) -> Optional[str]:
    if isinstance(values, list) and values:
        return str(values[0])
    return None


def _render_unified_patch(candidate_files: list[Dict[str, Any]]) -> str:
    chunks = []
    for candidate in candidate_files:
        source = str(candidate["source_path"])
        diff = difflib.unified_diff(
            candidate["original_content"].splitlines(),
            candidate["candidate_content"].splitlines(),
            fromfile=source,
            tofile=f"{source} (candidate)",
            lineterm="",
        )
        chunks.extend(diff)
    return "\n".join(chunks) + ("\n" if chunks else "")


def _workspace_destination(workspace: Path, source_path: Path, used: Optional[set] = None) -> Path:
    if source_path.is_absolute():
        parts = source_path.parts
        base = Path(*parts[-2:]) if len(parts) >= 2 else Path(parts[-1])
    else:
        base = source_path
    candidate = workspace / base
    if used is None or candidate not in used:
        return candidate
    stem = candidate.stem or candidate.name
    suffix = candidate.suffix
    parent = candidate.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}-{counter}{suffix}"
        if candidate not in used:
            return candidate
        counter += 1
