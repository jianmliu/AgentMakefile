from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from agentmf.models import AgentRuleIR, IRPolicy, IRSkill, IRTarget


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    content: str
    backend: str
    managed_block: bool = True
    overwrite: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


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
    capabilities = BackendCapabilities(markdown=True, permissions="soft")

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        artifact = ir.artifacts.get(self.name)
        path = artifact.path if artifact and artifact.path else "CLAUDE.md"
        managed_block = artifact.managed_block if artifact else True
        return [GeneratedFile(path=path, content=render_markdown(ir, "Claude Code"), backend=self.name, managed_block=managed_block)]


class AgentsMarkdownBackend(Backend):
    name = "agents-md"
    capabilities = BackendCapabilities(markdown=True, permissions="soft")

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        artifact = ir.artifacts.get(self.name)
        path = artifact.path if artifact and artifact.path else "AGENTS.md"
        managed_block = artifact.managed_block if artifact else True
        return [GeneratedFile(path=path, content=render_markdown(ir, "Generic Coding Agents"), backend=self.name, managed_block=managed_block)]


class CursorRuleBackend(Backend):
    name = "cursor-rule"
    capabilities = BackendCapabilities(markdown=True, permissions="soft")

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        artifact = ir.artifacts.get(self.name)
        path = artifact.path if artifact and artifact.path else ".cursor/rules/agentmakefile-generated.mdc"
        frontmatter = artifact.frontmatter if artifact else {}
        content = render_cursor_rule(ir, frontmatter)
        return [GeneratedFile(path=path, content=content, backend=self.name, managed_block=False)]


class ClaudeSkillBackend(Backend):
    name = "claude-skill"
    capabilities = BackendCapabilities(markdown=True, skills=True, permissions="soft")

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        return [
            GeneratedFile(
                path=skill_output_path(".claude/skills", skill),
                content=render_skill_markdown(skill, ir),
                backend=self.name,
                managed_block=False,
            )
            for skill in _unique_skills(ir.skills)
        ]


class CodexSkillBackend(Backend):
    name = "codex-skill"
    capabilities = BackendCapabilities(markdown=True, skills=True, permissions="soft")

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        return [
            GeneratedFile(
                path=skill_output_path(".codex/skills", skill),
                content=render_skill_markdown(skill, ir),
                backend=self.name,
                managed_block=False,
            )
            for skill in _unique_skills(ir.skills)
        ]


class ClaudeCodeBackend(Backend):
    name = "claude-code"
    capabilities = BackendCapabilities(markdown=True, skills=True, permissions="hard", hooks=True, hard_enforcement=True)

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        hook_files = _claude_hook_files(ir)
        settings = _claude_settings(ir, hook_files)
        files = [
            GeneratedFile(
                path=".claude/settings.json",
                content=json.dumps(settings, indent=2, sort_keys=True) + "\n",
                backend=self.name,
                managed_block=False,
                overwrite=True,
            )
        ]
        files.extend(hook_files)
        return files


class OpenCodeBackend(Backend):
    name = "opencode"
    capabilities = BackendCapabilities(markdown=True, skills=True, permissions="hard", hooks=True, hard_enforcement=True)

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        config = _opencode_config(ir)
        return [
            GeneratedFile(
                path="opencode.json",
                content=json.dumps(config, indent=2, sort_keys=True) + "\n",
                backend=self.name,
                managed_block=False,
                overwrite=True,
            )
        ]


class TargetFragmentBackend(Backend):
    capabilities = BackendCapabilities(markdown=True, permissions="soft")

    def __init__(self, name: str, fragment_dir: str, title_suffix: str) -> None:
        self.name = name
        self.fragment_dir = fragment_dir
        self.title_suffix = title_suffix

    def emit(self, ir: AgentRuleIR) -> List[GeneratedFile]:
        files = []
        targets_by_name = {target.name: target for target in ir.targets}
        for target in ir.targets:
            closure = _target_dependency_closure(target, targets_by_name)
            policies = _policies_for_targets(closure)
            skills = _skills_for_targets(closure)
            path = f".agentmf/fragments/{self.fragment_dir}/{_fragment_file_name(target.name)}.md"
            content = render_target_fragment(ir, target, closure, self.title_suffix)
            files.append(
                GeneratedFile(
                    path=path,
                    content=content,
                    backend=self.name,
                    metadata={
                        "kind": "target-fragment",
                        "target": target.name,
                        "target_closure": [item.name for item in closure],
                        "policies": [policy.name for policy in policies],
                        "skills": [skill.qualified_name for skill in skills],
                    },
                )
            )
        return files


SUPPORTED_BACKENDS: Dict[str, Backend] = {
    "claude-md": ClaudeMarkdownBackend(),
    "agents-md": AgentsMarkdownBackend(),
    "cursor-rule": CursorRuleBackend(),
    "claude-skill": ClaudeSkillBackend(),
    "codex-skill": CodexSkillBackend(),
    "claude-code": ClaudeCodeBackend(),
    "opencode": OpenCodeBackend(),
    "agents-fragments": TargetFragmentBackend("agents-fragments", "agents", "Generic Coding Agents"),
    "claude-fragments": TargetFragmentBackend("claude-fragments", "claude", "Claude Code"),
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


def render_skill_markdown(skill: IRSkill, ir: Optional[AgentRuleIR] = None) -> str:
    description = skill.description or f"AgentMakefile skill {skill.qualified_name}."
    lines = [
        "---",
        f"name: {skill.qualified_name}",
        f"description: {description}",
        "---",
        "",
        f"# {skill.qualified_name}",
        "",
        "## Overview",
        "",
        description,
        "",
    ]
    _append_skill_mapping(lines, "When To Use", skill.match)
    _append_skill_list(lines, "Guards", skill.guards)
    _append_skill_list(lines, "Procedure", skill.steps)
    _append_skill_list(lines, "Output Requirements", skill.output_format)
    if ir is not None:
        _append_permission_section(lines, ir)
    return "\n".join(lines).rstrip() + "\n"


def skill_output_path(base_dir: str, skill: IRSkill) -> str:
    return f"{base_dir.rstrip('/')}/{skill_slug(skill.qualified_name)}/SKILL.md"


def skill_slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "skill"


def _claude_settings(ir: AgentRuleIR, hook_files: List[GeneratedFile]) -> Dict[str, Any]:
    settings: Dict[str, Any] = {}
    permissions = _claude_permissions(ir)
    if permissions:
        settings["permissions"] = permissions
    hooks = _claude_hook_settings(hook_files)
    if hooks:
        settings["hooks"] = hooks
    return settings


def _claude_permissions(ir: AgentRuleIR) -> Dict[str, List[str]]:
    if not ir.permissions:
        return {}
    permissions = {"allow": [], "ask": [], "deny": []}
    for permission in ir.permissions:
        permissions[permission.action].append(_claude_permission_pattern(permission.tool, permission.pattern))
    return permissions


def _claude_permission_pattern(tool: str, pattern: str) -> str:
    tool_names = {
        "bash": "Bash",
        "file_read": "Read",
        "file_write": "Write",
        "browser": "Browser",
    }
    return f"{tool_names.get(tool, tool)}({pattern})"


def _claude_hook_files(ir: AgentRuleIR) -> List[GeneratedFile]:
    files = []
    for event in sorted(ir.hooks):
        for index, hook in enumerate(ir.hooks[event], start=1):
            name = _hook_name(hook, index)
            path = f".claude/hooks/{_safe_file_component(event)}/{_safe_file_component(name)}.sh"
            files.append(
                GeneratedFile(
                    path=path,
                    content=_render_claude_hook_script(event, hook),
                    backend="claude-code",
                    managed_block=False,
                    overwrite=True,
                    metadata={"kind": "claude-hook", "event": event, "name": name},
                )
            )
    return files


def _claude_hook_settings(hook_files: List[GeneratedFile]) -> Dict[str, List[Dict[str, str]]]:
    hooks: Dict[str, List[Dict[str, str]]] = {}
    for file in hook_files:
        event = file.metadata["event"]
        hooks.setdefault(event, []).append({"name": file.metadata["name"], "command": file.path})
    return hooks


def _render_claude_hook_script(event: str, hook: Dict[str, Any]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"# Generated from AgentMakefile hook: {event}/{_hook_name(hook, 1)}",
    ]
    message = hook.get("message")
    if message:
        lines.append(f"echo {_shell_double_quoted(str(message))} >&2")
    command = hook.get("command")
    if command:
        lines.append(str(command))
    action = hook.get("action")
    if action == "deny":
        lines.append("exit 2")
    else:
        lines.append("exit 0")
    return "\n".join(lines) + "\n"


def _hook_name(hook: Dict[str, Any], index: int) -> str:
    return str(hook.get("name") or f"hook_{index}")


def _safe_file_component(value: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in value)


def _shell_double_quoted(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'


def _opencode_config(ir: AgentRuleIR) -> Dict[str, Any]:
    config: Dict[str, Any] = {"$schema": "https://opencode.ai/config.json"}
    permission = _opencode_permission(ir)
    if permission:
        config["permission"] = permission
    if ir.targets:
        config["agent"] = {
            _opencode_agent_name(target.name): _opencode_agent(target, ir, permission)
            for target in ir.targets
        }
    return config


def _opencode_permission(ir: AgentRuleIR) -> Dict[str, Any]:
    permissions: Dict[str, Any] = {}
    for tool in sorted(ir.permission_defaults):
        permissions[_opencode_tool_name(tool)] = ir.permission_defaults[tool]
    for permission in ir.permissions:
        tool = _opencode_tool_name(permission.tool)
        existing = permissions.get(tool)
        if not isinstance(existing, dict):
            existing = {}
            permissions[tool] = existing
        existing[permission.pattern] = permission.action
    return permissions


def _opencode_agent(target: IRTarget, ir: AgentRuleIR, permission: Dict[str, Any]) -> Dict[str, Any]:
    agent: Dict[str, Any] = {
        "description": target.description or str(ir.metadata.get("description") or f"AgentMakefile target {target.name}"),
        "mode": "subagent",
        "prompt": _opencode_agent_prompt(target),
    }
    if permission:
        agent["permission"] = permission
    return agent


def _opencode_agent_prompt(target: IRTarget) -> str:
    lines = [f"# {target.name}", ""]
    if target.description:
        lines.extend([target.description, ""])
    _append_mapping(lines, "Match", target.match)
    _append_list(lines, "Policies", [policy.name for policy in target.policies])
    _append_list(lines, "Skills", [skill.qualified_name for skill in target.skills])
    _append_list(lines, "Dependencies", target.deps)
    _append_list(lines, "Guards", target.guards)
    _append_list(lines, "Steps", target.steps)
    _append_list(lines, "Output format", target.output_format)
    return "\n".join(lines).rstrip() + "\n"


def _opencode_tool_name(tool: str) -> str:
    return {
        "file_read": "read",
        "file_write": "edit",
        "web_search": "websearch",
        "web_fetch": "webfetch",
    }.get(tool, tool)


def _opencode_agent_name(target_name: str) -> str:
    safe = []
    previous_separator = False
    for character in target_name.lower():
        if character.isalnum():
            safe.append(character)
            previous_separator = False
        elif not previous_separator:
            safe.append("-")
            previous_separator = True
    return "".join(safe).strip("-") or "agent"


def render_target_fragment(
    ir: AgentRuleIR,
    target: IRTarget,
    target_closure: List[IRTarget],
    title_suffix: str,
) -> str:
    lines = [
        f"# {target.name} - {title_suffix} Target Fragment",
        "",
        "Generated from AgentMakefile. Keep project-specific edits outside this managed block.",
        "",
        f"Target dependency closure for `{target.name}`.",
        "",
    ]
    _append_policy_section(lines, _policies_for_targets(target_closure))
    _append_skill_section(lines, _skills_for_targets(target_closure))
    _append_target_section(lines, target_closure)
    _append_permission_section(lines, ir)
    return "\n".join(lines).rstrip() + "\n"


def _title(ir: AgentRuleIR, suffix: str) -> str:
    name = ir.metadata.get("name", "AgentMakefile")
    return f"{name} - {suffix}"


def _target_dependency_closure(target: IRTarget, targets_by_name: Dict[str, IRTarget]) -> List[IRTarget]:
    closure: List[IRTarget] = []
    visited = set()

    def visit(current: IRTarget) -> None:
        if current.name in visited:
            return
        visited.add(current.name)
        for dep_name in current.deps:
            dep = targets_by_name.get(dep_name)
            if dep is not None:
                visit(dep)
        closure.append(current)

    visit(target)
    return closure


def _policies_for_targets(targets: List[IRTarget]) -> List[IRPolicy]:
    policies = []
    seen = set()
    for target in targets:
        for policy in target.policies:
            if policy.name in seen:
                continue
            seen.add(policy.name)
            policies.append(policy)
    return policies


def _skills_for_targets(targets: List[IRTarget]) -> List[IRSkill]:
    skills = []
    seen = set()
    for target in targets:
        for skill in target.skills:
            if skill.qualified_name in seen:
                continue
            seen.add(skill.qualified_name)
            skills.append(skill)
    return skills


def _unique_skills(skills: List[IRSkill]) -> List[IRSkill]:
    unique: Dict[str, IRSkill] = {}
    for skill in skills:
        unique.setdefault(skill.qualified_name, skill)
    return [unique[name] for name in sorted(unique)]


def _fragment_file_name(target_name: str) -> str:
    return "".join(character if character.isalnum() or character in "._-" else "_" for character in target_name)


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
    lines.extend(["These permissions are soft instructions unless the selected backend supports native enforcement.", ""])
    if ir.permission_defaults:
        lines.extend(["### Defaults", ""])
        lines.extend(["| Tool | Action |", "| --- | --- |"])
        for tool in sorted(ir.permission_defaults):
            lines.append(f"| {_table_cell(tool)} | {_table_cell(ir.permission_defaults[tool])} |")
        lines.append("")
    if ir.permissions:
        lines.extend(["### Rules", ""])
        lines.extend(["| Tool | Pattern | Action |", "| --- | --- | --- |"])
        for permission in ir.permissions:
            lines.append(
                f"| {_table_cell(permission.tool)} | {_table_cell(permission.pattern)} | {_table_cell(permission.action)} |"
            )
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


def _append_skill_list(lines: List[str], title: str, items: List[Any]) -> None:
    if not items:
        return
    lines.extend([f"## {title}", ""])
    for item in items:
        lines.append(f"- {_format_value(item)}")
    lines.append("")


def _append_skill_mapping(lines: List[str], title: str, mapping: Dict[str, Any]) -> None:
    if not mapping:
        return
    lines.extend([f"## {title}", ""])
    for key in sorted(mapping):
        lines.append(f"- `{key}`: {_format_value(mapping[key])}")
    lines.append("")


def _format_value(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}={_format_value(value[key])}" for key in sorted(value))
    if isinstance(value, list):
        return ", ".join(_format_value(item) for item in value)
    return str(value)


def _table_cell(value: Any) -> str:
    return str(value).replace("|", "\\|")
