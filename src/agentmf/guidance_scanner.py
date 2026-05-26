from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml


@dataclass(frozen=True)
class ScannedGuidance:
    name: str
    source_type: str
    source_ref: str
    description: str
    match_terms: List[str]

    @property
    def target_name(self) -> str:
        return f"guidance.{self.source_type}.{_slug(self.name)}"


def render_agentmakefile_from_guidance_files(
    guidance_files: Sequence[Path],
    *,
    package_name: str = "imported-guidance",
    package_description: Optional[str] = None,
) -> str:
    guidance = scan_guidance_files(guidance_files)
    data = build_agentmakefile_data(
        guidance,
        package_name=package_name,
        package_description=package_description,
    )
    return yaml.safe_dump(data, sort_keys=False)


def scan_guidance_files(guidance_files: Sequence[Path]) -> List[ScannedGuidance]:
    records: List[ScannedGuidance] = []
    for path in guidance_files:
        records.extend(_scan_guidance_file(Path(path)))
    if not records:
        paths = ", ".join(str(path) for path in guidance_files)
        raise ValueError(f"no guidance sections found under: {paths}")
    return records


def build_agentmakefile_data(
    guidance: Sequence[ScannedGuidance],
    *,
    package_name: str,
    package_description: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "version": "0.1",
        "metadata": {
            "name": package_name,
            "description": package_description
            or f"AgentMakefile generated from {len(guidance)} imported guidance sections.",
            "module_type": "guidance-index",
        },
        "compile": {
            "targets": [
                "agents-fragments",
                "claude-fragments",
            ]
        },
        "targets": {
            record.target_name: {
                "phony": True,
                "priority": 65,
                "description": record.description,
                "match": {"user_intent": record.match_terms},
                "steps": [
                    {"link_prompt": {"source": record.source_ref}},
                    {"apply_policy": {"source": "imported"}},
                ],
            }
            for record in guidance
        },
    }


def _scan_guidance_file(path: Path) -> List[ScannedGuidance]:
    text = path.read_text(encoding="utf-8")
    source_type = _source_type(path)
    sections = _markdown_sections(text)
    if not sections:
        name = path.stem
        return [
            ScannedGuidance(
                name=name,
                source_type=source_type,
                source_ref=str(path),
                description=f"Imported guidance from {path.name}.",
                match_terms=_match_terms(name, text),
            )
        ]
    return [
        ScannedGuidance(
            name=title,
            source_type=source_type,
            source_ref=f"{path}#{title}",
            description=f"Imported guidance section {title} from {path.name}.",
            match_terms=_match_terms(title, body),
        )
        for title, body in sections
    ]


def _markdown_sections(text: str) -> List[tuple[str, str]]:
    sections: List[tuple[str, List[str]]] = []
    current_title: Optional[str] = None
    current_body: List[str] = []
    for line in text.splitlines():
        match = re.match(r"^(#{2,6})\s+(.+?)\s*$", line)
        if match:
            if current_title is not None:
                sections.append((current_title, current_body))
            current_title = _clean(match.group(2))
            current_body = []
            continue
        if current_title is not None:
            current_body.append(line)
    if current_title is not None:
        sections.append((current_title, current_body))
    return [(title, "\n".join(body)) for title, body in sections if title]


def _source_type(path: Path) -> str:
    name = path.name.lower()
    if name == "agents.md":
        return "agents"
    if name == "claude.md":
        return "claude"
    if name == "skill.md":
        return "skill"
    return "markdown"


def _match_terms(title: str, body: str) -> List[str]:
    terms = [_clean(title), _clean(title).replace("-", " ")]
    cleaned_body = _clean(body)
    if cleaned_body:
        terms.append(cleaned_body)
        words = cleaned_body.split()
        for index in range(0, max(0, len(words) - 1)):
            terms.append(" ".join(words[index : index + 2]))
    return _unique([term for term in terms if term])


def _clean(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"\*([^*]+)\*", r"\1", value)
    value = re.sub(r"[^A-Za-z0-9_.:/# -]+", " ", value)
    return re.sub(r"\s+", " ", value).strip(" .:-")


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug or "default"


def _unique(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
