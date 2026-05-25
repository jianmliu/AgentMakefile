from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from agentmf.diagnostics import Diagnostics
from agentmf.models import (
    AgentMakefileSource,
    AgentRuleIR,
    IRPermission,
    IRPolicy,
    IRSkill,
    IRTarget,
    PermissionSpec,
    TargetSpec,
)


def normalize(source: AgentMakefileSource, diagnostics: Diagnostics) -> Optional[AgentRuleIR]:
    policies = _normalize_policies(source)
    skills = _normalize_skills(source)
    targets = _normalize_targets(source, policies, skills, diagnostics)
    permissions = _permission_spec(source)
    _validate_permissions(permissions, diagnostics)
    if diagnostics.has_errors:
        return None

    return AgentRuleIR(
        version=source.version,
        metadata=source.metadata,
        vars=source.vars,
        targets=targets,
        policies=list(policies.values()),
        skills=list(skills.values()),
        permission_defaults=permissions.defaults,
        permissions=_flatten_permissions(permissions),
        hooks=source.hooks,
        validation=source.validation,
        artifacts={**source.outputs, **source.artifacts},
        patterns=source.patterns,
        cache=source.cache,
        tool_rules=source.tool_rules,
        compiler_hints=source.compiler_hints,
    )


def _normalize_policies(source: AgentMakefileSource) -> Dict[str, IRPolicy]:
    return {
        name: IRPolicy(name=name, **policy.model_dump())
        for name, policy in source.policies.items()
    }


def _normalize_skills(source: AgentMakefileSource) -> Dict[str, IRSkill]:
    skills: Dict[str, IRSkill] = {}
    for name, skill in source.skills.items():
        qualified_name = f"{skill.namespace}:{name}" if skill.namespace else name
        ir_skill = IRSkill(name=name, qualified_name=qualified_name, **skill.model_dump())
        skills[name] = ir_skill
        skills[qualified_name] = ir_skill
    return skills


def _normalize_targets(
    source: AgentMakefileSource,
    policies: Dict[str, IRPolicy],
    skills: Dict[str, IRSkill],
    diagnostics: Diagnostics,
) -> List[IRTarget]:
    targets = []
    for name in sorted(source.targets):
        target = _compose_target(name, source.targets, diagnostics, set())
        if target is None:
            continue
        resolved_policies = []
        for policy_name in target.policies:
            policy = policies.get(policy_name)
            if policy is None:
                diagnostics.error(
                    "AMF105",
                    f"target {name} references unknown policy {policy_name}",
                    f"targets.{name}.policies",
                )
                continue
            resolved_policies.append(policy)

        resolved_skills = []
        for skill_name in target.skills:
            skill = skills.get(skill_name)
            if skill is None:
                diagnostics.error(
                    "AMF106",
                    f"target {name} references unknown skill {skill_name}",
                    f"targets.{name}.skills",
                )
                continue
            resolved_skills.append(skill)

        targets.append(
            IRTarget(
                name=name,
                phony=target.phony,
                priority=target.priority,
                compile_to=target.compile_to,
                description=target.description,
                inputs=target.inputs,
                match=target.match,
                policies=resolved_policies,
                skills=resolved_skills,
                deps=target.deps,
                steps=target.steps,
                guards=target.guards,
                output_format=target.output_format,
                output_schema=target.output_schema,
                fallback=target.fallback,
            )
        )
    return targets


def _compose_target(
    name: str,
    targets: Dict[str, TargetSpec],
    diagnostics: Diagnostics,
    seen: Set[str],
) -> Optional[TargetSpec]:
    target = targets[name]
    if target.extends is None:
        return target
    if target.extends not in targets:
        diagnostics.error("AMF107", f"target {name} extends unknown target {target.extends}", f"targets.{name}.extends")
        return None
    if name in seen:
        diagnostics.error("AMF108", f"circular target extension involving {name}", f"targets.{name}.extends")
        return None

    parent = _compose_target(target.extends, targets, diagnostics, seen | {name})
    if parent is None:
        return None

    data = parent.model_dump()
    child_data = target.model_dump()
    explicitly_set = target.model_fields_set
    for key, value in child_data.items():
        if key in {"extends", "add_policies", "add_steps", "add_output_format", "override"}:
            continue
        if key in explicitly_set:
            data[key] = value

    data["policies"] = list(data["policies"]) + list(target.add_policies)
    data["steps"] = list(data["steps"]) + list(target.add_steps)
    data["output_format"] = list(data["output_format"]) + list(target.add_output_format)
    data.update(target.override)
    data["extends"] = None
    data["add_policies"] = []
    data["add_steps"] = []
    data["add_output_format"] = []
    data["override"] = {}
    return TargetSpec.model_validate(data)


def _permission_spec(source: AgentMakefileSource) -> PermissionSpec:
    if isinstance(source.permissions, PermissionSpec):
        return source.permissions
    if "defaults" in source.permissions or "rules" in source.permissions:
        return PermissionSpec.model_validate(source.permissions)
    return PermissionSpec(rules=source.permissions)


def _flatten_permissions(permissions: PermissionSpec) -> List[IRPermission]:
    flattened = []
    for tool in sorted(permissions.rules):
        for pattern in sorted(permissions.rules[tool]):
            flattened.append(IRPermission(tool=tool, pattern=pattern, action=permissions.rules[tool][pattern]))
    return flattened


def _validate_permissions(permissions: PermissionSpec, diagnostics: Diagnostics) -> None:
    for tool in sorted(set(permissions.defaults).union(permissions.rules)):
        if not _valid_permission_tool(tool):
            diagnostics.error(
                "AMF120",
                f"invalid permission tool name: {tool}",
                f"permissions.{tool}",
                "use a non-empty tool name without whitespace",
            )
    for tool in sorted(permissions.rules):
        for pattern in sorted(permissions.rules[tool]):
            hint = _permission_pattern_error_hint(pattern)
            if hint:
                diagnostics.error(
                    "AMF119",
                    f"invalid permission glob pattern: {pattern}",
                    f"permissions.{tool}.{pattern}",
                    hint,
                )


def _valid_permission_tool(tool: str) -> bool:
    return bool(tool) and re.search(r"\s", tool) is None


def _permission_pattern_error_hint(pattern: str) -> Optional[str]:
    if not pattern:
        return "use a non-empty glob pattern"
    open_class = False
    for character in pattern:
        if character == "[" and not open_class:
            open_class = True
        elif character == "]" and open_class:
            open_class = False
    if open_class:
        return "close '[' character classes with ']' or remove the character class"
    return None
