from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Union

from agentmf.diagnostics import Diagnostics
from agentmf.models import (
    AgentMakefileSource,
    AgentRuleIR,
    IRModel,
    IRPermission,
    IRPolicy,
    IRSkill,
    IRTarget,
    PermissionSpec,
    TargetSpec,
)

CONTEXT_OPERATION_TYPES = {"select_context"}
PROMPT_OPERATION_TYPES = {"link_prompt", "prompt", "use_skill", "apply_policy"}
GUARD_OPERATION_TYPES = {"check_guard"}
PERMISSION_OPERATION_TYPES = {"check_permission"}
FALLBACK_OPERATION_TYPES = {"fallback"}
OUTPUT_OPERATION_TYPES = {"validate_output"}


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
        models=[IRModel(name=name, **model.model_dump()) for name, model in source.models.items()],
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
    composed_targets: Dict[str, TargetSpec] = {}
    for name in sorted(source.targets):
        target = _compose_target(name, source.targets, diagnostics, set())
        if target is not None:
            composed_targets[name] = target

    _validate_target_dependencies(composed_targets, diagnostics)

    targets = []
    for name in sorted(composed_targets):
        target = composed_targets[name]
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
                pipeline=_target_pipeline(name, target, resolved_policies, resolved_skills),
            )
        )
    return targets


def _target_pipeline(
    name: str,
    target: TargetSpec,
    policies: List[IRPolicy],
    skills: List[IRSkill],
) -> Dict[str, Any]:
    context_ops: List[Dict[str, Any]] = []
    prompt_ops: List[Dict[str, Any]] = []
    action_ops: List[Dict[str, Any]] = []
    guard_ops: List[Dict[str, Any]] = []
    permission_ops: List[Dict[str, Any]] = []
    fallback_ops: List[Dict[str, Any]] = []
    output_validation_ops: List[Dict[str, Any]] = []
    operations: List[Dict[str, Any]] = []
    for policy in policies:
        _append_step_ops(
            policy.steps,
            source="policy",
            context_ops=context_ops,
            prompt_ops=prompt_ops,
            action_ops=action_ops,
            guard_ops=guard_ops,
            permission_ops=permission_ops,
            fallback_ops=fallback_ops,
            output_validation_ops=output_validation_ops,
            operations=operations,
            policy=policy.name,
        )
    _append_step_ops(
        target.steps,
        source="target",
        context_ops=context_ops,
        prompt_ops=prompt_ops,
        action_ops=action_ops,
        guard_ops=guard_ops,
        permission_ops=permission_ops,
        fallback_ops=fallback_ops,
        output_validation_ops=output_validation_ops,
        operations=operations,
    )
    implicit_guard_ops = _guard_ops(target, policies)
    guard_ops.extend(implicit_guard_ops)
    operations.extend(implicit_guard_ops)
    implicit_fallback_ops = _fallback_ops(target)
    fallback_ops.extend(implicit_fallback_ops)
    operations.extend(implicit_fallback_ops)
    return {
        "target": name,
        "deps": list(target.deps),
        "skills": [skill.qualified_name for skill in skills],
        "policies": [policy.name for policy in policies],
        "operations": operations,
        "context_ops": context_ops,
        "prompt_ops": prompt_ops,
        "action_ops": action_ops,
        "guard_ops": guard_ops,
        "permission_ops": permission_ops,
        "fallback_ops": fallback_ops,
        "output_contracts": {
            "format": _output_contract_format(target, policies, output_validation_ops),
            "schema": dict(target.output_schema),
        },
    }


def _append_step_ops(
    steps: List[Union[str, Dict[str, Any]]],
    *,
    source: str,
    context_ops: List[Dict[str, Any]],
    prompt_ops: List[Dict[str, Any]],
    action_ops: List[Dict[str, Any]],
    guard_ops: List[Dict[str, Any]],
    permission_ops: List[Dict[str, Any]],
    fallback_ops: List[Dict[str, Any]],
    output_validation_ops: List[Dict[str, Any]],
    operations: List[Dict[str, Any]],
    policy: Optional[str] = None,
) -> None:
    for step in steps:
        operation = _step_operation(step, source=source, policy=policy)
        operations.append(operation)
        if operation["type"] in CONTEXT_OPERATION_TYPES:
            context_ops.append(operation)
        elif operation["type"] in PROMPT_OPERATION_TYPES:
            prompt_ops.append(operation)
        elif operation["type"] in GUARD_OPERATION_TYPES:
            guard_ops.append(operation)
        elif operation["type"] in PERMISSION_OPERATION_TYPES:
            permission_ops.append(operation)
        elif operation["type"] in FALLBACK_OPERATION_TYPES:
            fallback_ops.append(operation)
        elif operation["type"] in OUTPUT_OPERATION_TYPES:
            output_validation_ops.append(operation)
        else:
            action_ops.append(operation)


def _step_operation(
    step: Union[str, Dict[str, Any]],
    *,
    source: str,
    policy: Optional[str] = None,
) -> Dict[str, Any]:
    if isinstance(step, str):
        operation = {
            "type": "action",
            "source": source,
            "payload": {"name": step},
            "raw": step,
        }
    else:
        operation_type, value = _single_step_entry(step)
        payload = _operation_payload(operation_type, value)
        operation = {
            "type": operation_type,
            "source": source,
            "payload": payload,
            "raw": step,
        }
        if operation_type == "fallback":
            operation["condition"] = str(payload.get("condition") or "runtime")
    if policy is not None:
        operation["policy"] = policy
    return operation


def _single_step_entry(step: Dict[str, Any]) -> tuple[str, Any]:
    if "action" in step:
        return "action", step["action"]
    if len(step) == 1:
        key = next(iter(step))
        return key, step[key]
    return "action", step


def _payload(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {"name": value}


def _operation_payload(operation_type: str, value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if operation_type == "action":
        return {"name": value}
    if operation_type == "use_skill":
        return {"skill": value}
    if operation_type == "check_guard":
        return {"guard": value}
    if operation_type == "validate_output":
        return {"format": value}
    if operation_type == "fallback":
        return {"name": value}
    if operation_type == "apply_policy":
        return {"policy": value}
    return _payload(value)


def _output_contract_format(
    target: TargetSpec,
    policies: List[IRPolicy],
    output_validation_ops: List[Dict[str, Any]],
) -> List[str]:
    values: List[str] = []
    for policy in policies:
        values.extend(policy.output_format)
    values.extend(target.output_format)
    for operation in output_validation_ops:
        payload = operation.get("payload", {})
        value = payload.get("format") or payload.get("name")
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return _unique_preserving_order(values)


def _guard_ops(target: TargetSpec, policies: List[IRPolicy]) -> List[Dict[str, Any]]:
    operations: List[Dict[str, Any]] = []
    for policy in policies:
        for guard in policy.guards:
            operations.append(
                {
                    "type": "check_guard",
                    "source": "policy",
                    "policy": policy.name,
                    "payload": {"guard": guard},
                    "raw": guard,
                }
            )
    for guard in target.guards:
        operations.append(
            {
                "type": "check_guard",
                "source": "target",
                "payload": {"guard": guard},
                "raw": guard,
            }
        )
    return operations


def _fallback_ops(target: TargetSpec) -> List[Dict[str, Any]]:
    operations: List[Dict[str, Any]] = []
    for condition in sorted(target.fallback):
        for fallback in target.fallback[condition]:
            operations.append(_fallback_operation(condition, fallback))
    return operations


def _fallback_operation(condition: str, fallback: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(fallback, str):
        payload = {"name": fallback}
    elif "fallback" in fallback and isinstance(fallback["fallback"], str):
        payload = {"name": fallback["fallback"]}
    else:
        payload = dict(fallback)
    return {
        "type": "fallback",
        "source": "target",
        "condition": condition,
        "payload": payload,
        "raw": fallback,
    }


def _unique_preserving_order(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _validate_target_dependencies(targets: Dict[str, TargetSpec], diagnostics: Diagnostics) -> None:
    for name in sorted(targets):
        seen_deps: Set[str] = set()
        for dep_name in targets[name].deps:
            if dep_name in seen_deps:
                continue
            seen_deps.add(dep_name)
            if dep_name not in targets:
                diagnostics.error(
                    "AMF122",
                    f"target {name} depends on unknown target {dep_name}",
                    f"targets.{name}.deps",
                )

    _validate_target_dependency_cycles(targets, diagnostics)


def _validate_target_dependency_cycles(targets: Dict[str, TargetSpec], diagnostics: Diagnostics) -> None:
    state: Dict[str, str] = {}
    reported_cycles: Set[tuple[str, ...]] = set()

    def visit(name: str, path: List[str]) -> None:
        state[name] = "visiting"
        path.append(name)
        for dep_name in targets[name].deps:
            if dep_name not in targets:
                continue
            dep_state = state.get(dep_name)
            if dep_state == "visiting":
                cycle = path[path.index(dep_name) :] + [dep_name]
                cycle_key = tuple(cycle)
                if cycle_key not in reported_cycles:
                    reported_cycles.add(cycle_key)
                    diagnostics.error(
                        "AMF123",
                        f"circular target dependency: {' -> '.join(cycle)}",
                        f"targets.{cycle[0]}.deps",
                    )
                continue
            if dep_state == "visited":
                continue
            visit(dep_name, path)
        path.pop()
        state[name] = "visited"

    for name in sorted(targets):
        if name not in state:
            visit(name, [])


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
