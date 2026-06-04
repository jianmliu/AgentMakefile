from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import yaml


@dataclass(frozen=True)
class ScannedSkill:
    name: str
    namespace: Optional[str]
    description: str
    path: Path
    match_terms: List[str]
    kind: Optional[str] = None

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}:{self.name}" if self.namespace else self.name

    @property
    def target_name(self) -> str:
        return f"skill.{_safe_target_part(self.name)}"


def render_agentmakefile_from_skill_dirs(
    skill_dirs: Sequence[Path],
    *,
    namespace: Optional[str] = None,
    package_name: str = "scanned-skills",
    package_description: Optional[str] = None,
    bootstrap_skill: Optional[str] = None,
) -> str:
    skills = scan_skill_dirs(skill_dirs, namespace=namespace)
    data = build_agentmakefile_data(
        skills,
        package_name=package_name,
        package_description=package_description,
        bootstrap_skill=bootstrap_skill,
    )
    return yaml.safe_dump(data, sort_keys=False)


def scan_skill_dirs(skill_dirs: Sequence[Path], *, namespace: Optional[str] = None) -> List[ScannedSkill]:
    skills: List[ScannedSkill] = []
    seen: Dict[str, Path] = {}
    seen_local_names: Dict[str, Path] = {}
    for skill_dir in skill_dirs:
        for path in sorted(Path(skill_dir).glob("*/SKILL.md")):
            skill = _read_skill(path, namespace=namespace)
            previous_path = seen.get(skill.qualified_name)
            if previous_path is not None:
                raise ValueError(
                    f"duplicate skill {skill.qualified_name}: {previous_path} and {path}"
                )
            previous_local_path = seen_local_names.get(skill.name)
            if previous_local_path is not None:
                raise ValueError(
                    f"duplicate skill name {skill.name}: {previous_local_path} and {path}"
                )
            seen[skill.qualified_name] = path
            seen_local_names[skill.name] = path
            skills.append(skill)
    if not skills:
        paths = ", ".join(str(path) for path in skill_dirs)
        raise ValueError(f"no SKILL.md files found under: {paths}")
    return skills


def build_agentmakefile_data(
    skills: Sequence[ScannedSkill],
    *,
    package_name: str,
    package_description: Optional[str] = None,
    bootstrap_skill: Optional[str] = None,
) -> Dict[str, Any]:
    bootstrap = _resolve_bootstrap(skills, bootstrap_skill)
    skill_entries = {
        skill.name: {
            **({"namespace": skill.namespace} if skill.namespace else {}),
            "description": skill.description,
            **({"kind": skill.kind} if skill.kind else {}),
            "implementation": {"source": str(skill.path)},
            "match": {"user_intent": skill.match_terms},
        }
        for skill in skills
    }
    target_entries = {}
    for skill in skills:
        target = {
            "phony": True,
            "priority": 95 if bootstrap and skill.qualified_name == bootstrap.qualified_name else 70,
            "description": f"Use {skill.qualified_name}.",
            "match": {"user_intent": skill.match_terms},
            "skills": [skill.qualified_name],
            "steps": [
                {"use_skill": skill.qualified_name},
                {"link_prompt": {"source": str(skill.path)}},
            ],
        }
        if bootstrap and skill.qualified_name != bootstrap.qualified_name:
            target["deps"] = [bootstrap.target_name]
        target_entries[skill.target_name] = target

    return {
        "version": "0.1",
        "metadata": {
            "name": package_name,
            "description": package_description
            or f"AgentMakefile generated from {len(skills)} scanned skills.",
            "module_type": "skill-index",
        },
        "compile": {
            "targets": [
                "skills-index",
                "codex-skill",
                "claude-skill",
                "agents-fragments",
                "claude-fragments",
            ]
        },
        "skills": skill_entries,
        "targets": target_entries,
    }


def _read_skill(path: Path, *, namespace: Optional[str]) -> ScannedSkill:
    text = path.read_text()
    metadata, body = _split_frontmatter(text)
    raw_name = str(metadata.get("name") or path.parent.name)
    skill_namespace, name = _split_skill_name(raw_name, namespace)
    description = str(metadata.get("description") or f"Skill {raw_name}.")
    kind = metadata.get("kind")
    return ScannedSkill(
        name=name,
        namespace=skill_namespace,
        description=description,
        path=path,
        match_terms=_merge_explicit_match(_explicit_match_terms(metadata), _match_terms(name, description, body)),
        kind=str(kind) if kind else None,
    )


def _explicit_match_terms(metadata: Dict[str, Any]) -> List[str]:
    """An author-declared `match.user_intent` in the frontmatter — authoritative
    routing terms (used by typed memory units; benefits real skills too)."""
    match = metadata.get("match")
    if not isinstance(match, dict):
        return []
    user_intent = match.get("user_intent")
    if not isinstance(user_intent, list):
        return []
    return [str(term).strip() for term in user_intent if str(term).strip()]


def _merge_explicit_match(explicit: List[str], derived: List[str]) -> List[str]:
    """Explicit terms first (authoritative), then derived terms; de-duplicated."""
    merged: List[str] = []
    for term in [*explicit, *derived]:
        if term and term not in merged:
            merged.append(term)
    return merged


def _split_frontmatter(text: str) -> tuple[Dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            raw_metadata = "\n".join(lines[1:index])
            try:
                metadata = yaml.safe_load(raw_metadata) or {}
            except yaml.YAMLError:
                metadata = _recover_frontmatter(raw_metadata)
            if not isinstance(metadata, dict):
                metadata = {}
            return metadata, "\n".join(lines[index + 1 :])
    return {}, text


def _recover_frontmatter(raw_metadata: str) -> Dict[str, Any]:
    """Best-effort regex extraction when YAML parsing fails.

    OpenClaw bundled SKILL.md files sometimes embed colons in unquoted
    description values, which `yaml.safe_load` rejects. Pull the leading
    `key: value` pairs we actually use (`name`, `description`, `category`,
    `tags`) so the importer can still index those skills.
    """
    recovered: Dict[str, Any] = {}
    for line in raw_metadata.splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*)$", line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key not in {"name", "description", "category", "tags"}:
            continue
        if key == "tags" and value.startswith("[") and value.endswith("]"):
            recovered[key] = [item.strip().strip("'\"") for item in value[1:-1].split(",") if item.strip()]
        else:
            recovered[key] = value
    return recovered


def _split_skill_name(raw_name: str, namespace: Optional[str]) -> tuple[Optional[str], str]:
    if ":" not in raw_name:
        return namespace, raw_name
    embedded_namespace, name = raw_name.split(":", 1)
    return namespace or embedded_namespace, name


def _match_terms(name: str, description: str, body: str) -> List[str]:
    terms: List[str] = []
    _append_term(terms, name)
    _append_term(terms, name.replace("-", " "))
    _append_term(terms, _gerund_alias(name.replace("-", " ")))
    for term in _description_terms(description):
        _append_term(terms, term)
    for term in _when_to_use_terms(body):
        _append_term(terms, term)
        _append_term(terms, _singularize(term))
        _append_term(terms, _bugfix_alias(term))
    return terms


def _description_terms(description: str) -> Iterable[str]:
    normalized = _clean_text(description)
    use_when = re.search(r"\buse when\b(.+)", normalized, flags=re.IGNORECASE)
    if use_when:
        normalized = use_when.group(1)
    for part in re.split(r"[,.;]|\bbefore\b|\bafter\b", normalized):
        part = part.strip()
        if part:
            yield part
            yield from _description_aliases(part)


def _description_aliases(term: str) -> Iterable[str]:
    lower = term.lower()
    if "implementing" in lower and ("any feature" in lower or "bugfix" in lower or "bug fix" in lower):
        yield "implement feature"
        yield "implement this feature"
        yield "feature"
    if "bugfix" in lower or "bug fix" in lower:
        yield "bugfix"
        yield "fix bug"
    if "multi-step" in lower or "implementation plan" in lower or "write plan" in lower:
        yield "implementation plan"
        yield "write plan"


def _when_to_use_terms(body: str) -> Iterable[str]:
    in_section = False
    for raw_line in body.splitlines():
        line = raw_line.rstrip()
        if line.startswith("## "):
            heading = line.lstrip("#").strip().lower()
            in_section = heading in {"when to use", "when to use this skill"}
            continue
        if not in_section:
            continue
        if line.strip().lower().startswith(("**exceptions", "exceptions")):
            in_section = False
            continue
        match = re.match(r"\s*[-*]\s+(.+)", line)
        if match:
            yield _clean_text(match.group(1))


def _append_term(terms: List[str], term: Optional[str]) -> None:
    if not term:
        return
    cleaned = _clean_text(term)
    if cleaned.lower() in {"and", "or", "the", "a", "an", "to"}:
        return
    if cleaned and cleaned not in terms:
        terms.append(cleaned)


def _clean_text(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    value = re.sub(r"\s+", " ", value).strip(" .:-")
    return value


def _singularize(term: str) -> Optional[str]:
    words = term.split()
    if not words:
        return None
    last = words[-1]
    if len(last) <= 3 or not last.endswith("s"):
        return None
    if last.endswith("ies"):
        words[-1] = f"{last[:-3]}y"
    elif last.endswith("xes"):
        words[-1] = last[:-2]
    else:
        words[-1] = last[:-1]
    return " ".join(words)


def _bugfix_alias(term: str) -> Optional[str]:
    lower = term.lower()
    if lower in {"bug fixes", "bug fix", "bugfixes", "bugfix"}:
        return "fix bug"
    return None


def _gerund_alias(term: str) -> Optional[str]:
    gerunds = {
        "brainstorming": "brainstorm",
        "debugging": "debug",
        "dispatching": "dispatch",
        "executing": "execute",
        "finishing": "finish",
        "receiving": "receive",
        "requesting": "request",
        "using": "use",
        "writing": "write",
    }
    words = term.split()
    if not words:
        return None
    replacement = gerunds.get(words[0])
    if replacement is None:
        return None
    words[0] = replacement
    return " ".join(words)


def _resolve_bootstrap(skills: Sequence[ScannedSkill], bootstrap_skill: Optional[str]) -> Optional[ScannedSkill]:
    if bootstrap_skill is None:
        return None
    for skill in skills:
        if bootstrap_skill in {skill.name, skill.qualified_name}:
            return skill
    raise ValueError(f"bootstrap skill not found: {bootstrap_skill}")


def _safe_target_part(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "." for character in value)
