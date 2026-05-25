from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from agentmf.models import AgentRuleIR, IRPolicy, IRSkill, IRTarget


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    content: str
    backend: str
    managed_block: bool = True


@dataclass(frozen=True)
class BackendCapabilities:
    markdown: bool = True
    skills: bool = False
    permissions: str = "none"
    hooks: bool = False
    hard_enforcement: bool = False


class Backend:
    name = ""
    capabilities = BackendCapabilities()

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        raise NotImplementedError


class ClaudeMarkdownBackend(Backend):
    name = "claude-md"

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        artifact = ir.artifacts.get(self.name)
        path = artifact.path if artifact and artifact.path else "CLAUDE.md"
        managed_block = artifact.managed_block if artifact else True
        return [GeneratedFile(path=path, content=render_markdown(ir, "Claude Code"), backend=self.name, managed_block=managed_block)]


class AgentsMarkdownBackend(Backend):
    name = "agents-md"

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        artifact = ir.artifacts.get(self.name)
        path = artifact.path if artifact and artifact.path else "AGENTS.md"
        managed_block = artifact.managed_block if artifact else True
        return [GeneratedFile(path=path, content=render_markdown(ir, "Generic Coding Agents"), backend=self.name, managed_block=managed_block)]


class CursorRuleBackend(Backend):
    name = "cursor-rule"

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        artifact = ir.artifacts.get(self.name)
        path = artifact.path if artifact and artifact.path else ".cursor/rules/agentmakefile-generated.mdc"
        frontmatter = artifact.frontmatter if artifact else {}
        content = render_cursor_rule(ir, frontmatter)
        return [GeneratedFile(path=path, content=content, backend=self.name, managed_block=False)]


SUPPORTED_BACKENDS: Dict[str, Backend] = {
    "claude-md": ClaudeMarkdownBackend(),
    "agents-md": AgentsMarkdownBackend(),
    "cursor-rule": CursorRuleBackend(),
}

DEFAULT_BACKENDS = ["claude-md", "agents-md", "cursor-rule"]


def render_markdown(ir: AgentRuleIR, title_suffix: str) -> str:
    title = _title(ir, title_suffix)
    lines = [
        f"# {title}",
        "",
        "Generated from AgentMakefile. Keep project-specific edits outside this managed block.",
        "",
    ]
    description = ir.metadata.get("description")
    if description:
        lines.extend(["## Package", "", str(description), ""])
    _append_policy_section(lines, ir.policies)
    _append_skill_section(lines, ir.skills)
    _append_target_section(lines, ir.targets)
    _append_permission_section(lines, ir)
    return "\n".join(lines).rstrip() + "\n"


def render_cursor_rule(ir: AgentRuleIR, frontmatter: Dict[str, Any]) -> str:
    fm = {
        "description": frontmatter.get("description", _title(ir, "AgentMakefile rules")),
        "alwaysApply": frontmatter.get("alwaysApply", True),
    }
    lines = ["---"]
    for key in sorted(fm):
        value = fm[key]
        rendered = "true" if value is True else "false" if value is False else str(value)
        lines.append(f"{key}: {rendered}")
    lines.extend(["---", "", render_markdown(ir, "Cursor")])
    return "\n".join(lines).rstrip() + "\n"


def _title(ir: AgentRuleIR, suffix: str) -> str:
    name = ir.metadata.get("name", "AgentMakefile")
    return f"{name} - {suffix}"


def _append_policy_section(lines: List[str], policies: List[IRPolicy]) -> None:
    if not policies:
        return
    lines.extend(["## Policies", ""])
    for policy in policies:
        lines.extend([f"### {policy.name}", ""])
        if policy.description:
            lines.extend([policy.description, ""])
        _append_list(lines, "Applies to", policy.applies_to)
        _append_list(lines, "Guards", policy.guards)
        _append_list(lines, "Steps", policy.steps)
        _append_list(lines, "Output format", policy.output_format)


def _append_skill_section(lines: List[str], skills: List[IRSkill]) -> None:
    unique = []
    seen = set()
    for skill in skills:
        if skill.qualified_name in seen:
            continue
        seen.add(skill.qualified_name)
        unique.append(skill)
    if not unique:
        return
    lines.extend(["## Skills", ""])
    for skill in unique:
        lines.extend([f"### {skill.qualified_name}", ""])
        if skill.description:
            lines.extend([skill.description, ""])
        _append_mapping(lines, "Match", skill.match)
        _append_list(lines, "Guards", skill.guards)
        _append_list(lines, "Steps", skill.steps)
        _append_list(lines, "Output format", skill.output_format)


def _append_target_section(lines: List[str], targets: List[IRTarget]) -> None:
    if not targets:
        return
    lines.extend(["## Targets", ""])
    for target in targets:
        lines.extend([f"### {target.name}", ""])
        if target.description:
            lines.extend([target.description, ""])
        lines.extend([f"- Priority: {target.priority}", f"- Phony: {str(target.phony).lower()}"])
        if target.compile_to:
            lines.append(f"- Compile to: {target.compile_to}")
        lines.append("")
        _append_mapping(lines, "Match", target.match)
        _append_list(lines, "Policies", [policy.name for policy in target.policies])
        _append_list(lines, "Skills", [skill.qualified_name for skill in target.skills])
        _append_list(lines, "Dependencies", target.deps)
        _append_list(lines, "Guards", target.guards)
        _append_list(lines, "Steps", target.steps)
        _append_list(lines, "Output format", target.output_format)


def _append_permission_section(lines: List[str], ir: AgentRuleIR) -> None:
    if not ir.permission_defaults and not ir.permissions:
        return
    lines.extend(["## Permission Guidance", ""])
    if ir.permission_defaults:
        lines.extend(["### Defaults", ""])
        for tool in sorted(ir.permission_defaults):
            lines.append(f"- `{tool}`: {ir.permission_defaults[tool]}")
        lines.append("")
    if ir.permissions:
        lines.extend(["### Rules", ""])
        for permission in ir.permissions:
            lines.append(f"- `{permission.tool}` `{permission.pattern}`: {permission.action}")
        lines.append("")


def _append_list(lines: List[str], title: str, items: List[Any]) -> None:
    if not items:
        return
    lines.extend([f"#### {title}", ""])
    for item in items:
        lines.append(f"- {_format_value(item)}")
    lines.append("")


def _append_mapping(lines: List[str], title: str, mapping: Dict[str, Any]) -> None:
    if not mapping:
        return
    lines.extend([f"#### {title}", ""])
    for key in sorted(mapping):
        lines.append(f"- `{key}`: {_format_value(mapping[key])}")
    lines.append("")


def _format_value(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}={_format_value(value[key])}" for key in sorted(value))
    if isinstance(value, list):
        return ", ".join(_format_value(item) for item in value)
    return str(value)
