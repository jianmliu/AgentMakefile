from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

import yaml

from agentmf.diagnostics import Diagnostics
from agentmf.skill_scanner import (
    ScannedSkill,
    build_agentmakefile_data,
    _match_terms,
    _split_frontmatter,
    _split_skill_name,
)


@dataclass(frozen=True)
class OpenClawSkillRecord:
    original_name: str
    generated_name: str
    namespace: Optional[str]
    description: str
    category: str
    tags: List[str]
    path: Path
    relative_path: str
    match_terms: List[str]

    @property
    def generated_skill(self) -> ScannedSkill:
        return ScannedSkill(
            name=self.generated_name,
            namespace=self.namespace,
            description=self.description,
            path=self.path,
            match_terms=self.match_terms,
        )


@dataclass
class OpenClawImportResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_openclaw_import_payload(
    skill_dirs: Sequence[Union[Path, str]],
    *,
    out_dir: Union[Path, str],
    namespace: Optional[str] = "openclaw",
    package_name: str = "openclaw-skills",
    package_description: Optional[str] = None,
    write: bool = False,
) -> OpenClawImportResult:
    diagnostics = Diagnostics()
    roots = [Path(path) for path in skill_dirs]
    records = _scan_openclaw_skills(roots, namespace=namespace, diagnostics=diagnostics)
    if diagnostics.has_errors:
        return OpenClawImportResult(diagnostics)
    records = _dedupe_generated_names(records)

    output_dir = Path(out_dir)
    modules = _render_category_modules(
        records,
        package_name=package_name,
        package_description=package_description,
    )
    root_content = _render_root_index(
        records,
        modules,
        package_name=package_name,
        package_description=package_description,
    )
    if write:
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "AgentMakefile").write_text(root_content, encoding="utf-8")
            for relative_path, content in modules.items():
                destination = output_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(content, encoding="utf-8")
        except OSError as exc:
            diagnostics.error(
                "AMF210",
                f"could not write OpenClaw AgentMakefile modules under {output_dir}",
                "openclaw.out",
                str(exc),
            )
            return OpenClawImportResult(diagnostics)

    evidence = _curator_evidence(records, modules)
    payload = {
        "version": 1,
        "mode": "openclaw_import",
        "skills_dirs": [str(path) for path in roots],
        "root_path": str(output_dir / "AgentMakefile"),
        "wrote": write,
        "skill_count": len(records),
        "category_count": len(modules),
        "categories": [
            {
                "name": category,
                "skill_count": sum(1 for record in records if record.category == category),
                "path": f"{category}/AgentMakefile",
            }
            for category in sorted({record.category for record in records})
        ],
        "root_agentmakefile": None if write else root_content,
        "modules": {} if write else modules,
        "curator_evidence": evidence,
    }
    return OpenClawImportResult(diagnostics, payload)


def _scan_openclaw_skills(
    roots: Sequence[Path],
    *,
    namespace: Optional[str],
    diagnostics: Diagnostics,
) -> List[OpenClawSkillRecord]:
    records: List[OpenClawSkillRecord] = []
    for root in roots:
        if not root.exists():
            diagnostics.error("AMF211", f"OpenClaw skills directory does not exist: {root}", "openclaw.skills_dir")
            continue
        for path in sorted(root.glob("**/SKILL.md")):
            records.append(_read_openclaw_skill(path, root=root, namespace=namespace))
    if not records and not diagnostics.has_errors:
        paths = ", ".join(str(path) for path in roots)
        diagnostics.error("AMF212", f"no SKILL.md files found under: {paths}", "openclaw.skills_dir")
    return records


def _read_openclaw_skill(path: Path, *, root: Path, namespace: Optional[str]) -> OpenClawSkillRecord:
    text = path.read_text(encoding="utf-8")
    metadata, body = _split_frontmatter(text)
    raw_name = str(metadata.get("name") or path.parent.name)
    skill_namespace, original_name = _split_skill_name(raw_name, namespace)
    category = _category(metadata, path=path, root=root)
    generated_name = f"{category}.{_safe_name(original_name)}"
    description = str(metadata.get("description") or f"OpenClaw skill {original_name}.")
    tags = _tags(metadata.get("tags"))
    return OpenClawSkillRecord(
        original_name=original_name,
        generated_name=generated_name,
        namespace=skill_namespace,
        description=description,
        category=category,
        tags=tags,
        path=path,
        relative_path=path.relative_to(root).as_posix(),
        match_terms=_match_terms(" ".join([original_name, category, *tags]), description, body),
    )


def _dedupe_generated_names(records: Sequence[OpenClawSkillRecord]) -> List[OpenClawSkillRecord]:
    counts: Dict[str, int] = {}
    deduped: List[OpenClawSkillRecord] = []
    for record in records:
        count = counts.get(record.generated_name, 0) + 1
        counts[record.generated_name] = count
        if count == 1:
            deduped.append(record)
            continue
        deduped.append(replace(record, generated_name=f"{record.generated_name}-{count}"))
    return deduped


def _render_category_modules(
    records: Sequence[OpenClawSkillRecord],
    *,
    package_name: str,
    package_description: Optional[str],
) -> Dict[str, str]:
    modules: Dict[str, str] = {}
    for category in sorted({record.category for record in records}):
        category_records = [record for record in records if record.category == category]
        data = build_agentmakefile_data(
            [record.generated_skill for record in category_records],
            package_name=f"{package_name}-{category}",
            package_description=package_description
            or f"OpenClaw {category} skills imported as AgentMakefile targets.",
        )
        data["metadata"].update(
            {
                "module_type": "openclaw-skill-category",
                "category": category,
                "source": "openclaw-local-scan",
                "skill_count": len(category_records),
            }
        )
        for record in category_records:
            skill_data = data["skills"][record.generated_name]
            skill_data.setdefault("implementation", {})
            skill_data["implementation"].update(
                {
                    "category": record.category,
                    "tags": record.tags,
                    "original_name": record.original_name,
                    "relative_source": record.relative_path,
                }
            )
        modules[f"{category}/AgentMakefile"] = yaml.safe_dump(data, sort_keys=False)
    return modules


def _render_root_index(
    records: Sequence[OpenClawSkillRecord],
    modules: Dict[str, str],
    *,
    package_name: str,
    package_description: Optional[str],
) -> str:
    data = {
        "version": "0.1",
        "metadata": {
            "name": package_name,
            "description": package_description
            or f"Root AgentMakefile index for {len(records)} imported OpenClaw skills.",
            "module_type": "openclaw-skill-root",
            "source": "openclaw-local-scan",
            "skill_count": len(records),
            "category_count": len(modules),
            "categories": sorted({record.category for record in records}),
        },
        "include": sorted(modules),
        "compile": {
            "targets": [
                "skills-index",
                "agents-fragments",
                "claude-fragments",
            ]
        },
    }
    return yaml.safe_dump(data, sort_keys=False)


def _curator_evidence(
    records: Sequence[OpenClawSkillRecord],
    modules: Dict[str, str],
) -> Dict[str, Any]:
    duplicates: Dict[str, List[str]] = {}
    for record in records:
        duplicates.setdefault(record.original_name, []).append(record.relative_path)
    duplicate_original_names = {
        name: paths
        for name, paths in sorted(duplicates.items())
        if len(paths) > 1
    }
    categories = {
        category: sum(1 for record in records if record.category == category)
        for category in sorted({record.category for record in records})
    }
    return {
        "version": 1,
        "source": "openclaw-local-scan",
        "skill_count": len(records),
        "category_count": len(categories),
        "categories": categories,
        "duplicate_original_names": duplicate_original_names,
        "module_paths": sorted(modules),
    }


def _category(metadata: Dict[str, Any], *, path: Path, root: Path) -> str:
    raw_category = metadata.get("category") or metadata.get("group")
    if raw_category:
        return _safe_name(str(raw_category))
    relative_parts = path.relative_to(root).parts
    if len(relative_parts) > 2:
        return _safe_name(relative_parts[0])
    return "uncategorized"


def _tags(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "unnamed"
