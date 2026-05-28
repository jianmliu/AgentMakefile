from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from jsonschema import Draft202012Validator

from agentmf.compiler import compile_agentmakefile
from agentmf.diagnostics import Diagnostics
from agentmf.ir import normalize
from agentmf.loader import load_source_with_diagnostics
from agentmf.models import AgentRuleIR, IRPermission, IRPolicy, IRTarget, PermissionAction
from agentmf.selector import create_link_plan


BASELINE_BACKENDS = {
    "agents-fragments": ("agents-md", "AGENTS.md"),
    "claude-fragments": ("claude-md", "CLAUDE.md"),
}

RUNTIME_PHASES = [
    {"name": "target_selection", "status": "resolved"},
    {"name": "dependency_graph_resolution", "status": "resolved"},
    {"name": "prompt_fragment_linking", "status": "linked"},
    {"name": "guard_evaluation", "status": "evaluated_dry_run"},
    {"name": "permission_enforcement", "status": "not_executed"},
    {"name": "step_execution", "status": "not_executed"},
    {"name": "output_validation", "status": "not_executed"},
    {"name": "fallback_handling", "status": "not_executed"},
    {"name": "trace_logging", "status": "planned"},
]

PERMISSION_ACTION_RANK = {"allow": 0, "ask": 1, "deny": 2}
IMPLICIT_PERMISSION_ACTION: PermissionAction = "ask"


@dataclass
class RunPlanResult:
    diagnostics: Diagnostics
    plan: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_run_plan(
    path: Union[Path, str],
    request: Optional[str] = None,
    target_names: Optional[List[str]] = None,
    backend: str = "agents-fragments",
    dry_run: bool = False,
    proposed_tool_calls: Optional[List[Dict[str, str]]] = None,
    proposed_output: Optional[Dict[str, Any]] = None,
    *,
    matcher: str = "keyword",
    embedder: Optional[Any] = None,
    embedder_cache_path: Optional[Union[Path, str]] = None,
    embedder_top_k: int = 10,
) -> RunPlanResult:
    diagnostics = Diagnostics()
    if not dry_run:
        diagnostics.error(
            "AMF125",
            "runtime execution is not implemented; use --dry-run to inspect the runtime plan",
            "run",
            "runtime mode currently supports dry-run planning and prompt linking only",
        )
        return RunPlanResult(diagnostics)

    link_result = create_link_plan(
        path, request=request, target_names=target_names, backend=backend,
        matcher=matcher, embedder=embedder,
        embedder_cache_path=embedder_cache_path, embedder_top_k=embedder_top_k,
    )
    diagnostics.extend(link_result.diagnostics.items)
    if diagnostics.has_errors:
        return RunPlanResult(diagnostics)

    source, load_diagnostics = load_source_with_diagnostics(Path(path))
    diagnostics.extend(load_diagnostics.items)
    if source is None or diagnostics.has_errors:
        return RunPlanResult(diagnostics)

    ir = normalize(source, diagnostics)
    if ir is None or diagnostics.has_errors:
        return RunPlanResult(diagnostics)

    prompt_prefix = _link_prompt_prefix(Path(path), link_result.plan, backend, diagnostics)
    if diagnostics.has_errors:
        return RunPlanResult(diagnostics)

    targets_by_name = {target.name: target for target in ir.targets}
    target_closure = [targets_by_name[name] for name in link_result.plan["target_closure"]]
    target_pipelines = [target.pipeline for target in target_closure]
    guard_evaluation = _guard_evaluation(target_closure)
    permission_evaluation = _permission_evaluation(ir, proposed_tool_calls or [])
    output_validation = _output_validation(target_closure, proposed_output)
    plan = {
        "version": 1,
        "mode": "dry_run",
        "backend": backend,
        "execution": {
            "enabled": False,
            "reason": "AMF-M4-001 plans runtime execution but does not execute steps or intercept tools.",
        },
        "link_plan": link_result.plan,
        "prompt_prefix": prompt_prefix,
        "runtime_phases": _runtime_phases(proposed_tool_calls or [], proposed_output),
        "target_contracts": [_target_contract(target) for target in target_closure],
        "target_pipelines": target_pipelines,
        "pipeline_execution_plan": _pipeline_execution_plan(
            link_result.plan,
            target_pipelines,
            prompt_prefix,
            output_validation,
        ),
        "policy_contracts": _policy_contracts(target_closure),
        "guard_evaluation": guard_evaluation,
        "permission_contract": _permission_contract(ir),
        "permission_evaluation": permission_evaluation,
        "output_validation": output_validation,
    }
    return RunPlanResult(diagnostics, plan)


def _runtime_phases(
    proposed_tool_calls: List[Dict[str, str]],
    proposed_output: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    phases = [dict(phase) for phase in RUNTIME_PHASES]
    if proposed_tool_calls:
        phases[4] = {"name": "permission_enforcement", "status": "evaluated_dry_run"}
    if proposed_output is not None:
        phases[6] = {"name": "output_validation", "status": "evaluated_dry_run"}
    return phases


def _link_prompt_prefix(
    path: Path,
    link_plan: Dict[str, Any],
    backend: str,
    diagnostics: Diagnostics,
) -> Dict[str, Any]:
    baseline_backend, baseline_path = BASELINE_BACKENDS[backend]
    compile_result = compile_agentmakefile(path, targets=[backend, baseline_backend])
    diagnostics.extend(compile_result.diagnostics.items)
    if diagnostics.has_errors:
        return {}

    files_by_path = {file.path: file for file in compile_result.files}
    linked_fragments = []
    contents = []
    selected_targets = set(link_plan["selected_targets"])
    for fragment in link_plan["fragments"]:
        if fragment["target"] not in selected_targets:
            continue
        file = files_by_path.get(fragment["path"])
        if file is None:
            diagnostics.error(
                "AMF126",
                f"selected fragment was not emitted: {fragment['path']}",
                "run.prompt_prefix",
                "compile the selected fragment backend before linking the runtime prompt",
            )
            continue
        contents.append(file.content.rstrip())
        linked_fragments.append(
            {
                "backend": file.backend,
                "target": fragment["target"],
                "path": file.path,
                **_size_metrics(file.content),
            }
        )

    baseline = files_by_path.get(baseline_path)
    if baseline is None:
        diagnostics.error(
            "AMF127",
            f"baseline prompt artifact was not emitted: {baseline_path}",
            "run.prompt_prefix",
            f"compile backend {baseline_backend} before comparing linked prompt size",
        )
        return {}

    content = "\n\n".join(contents)
    if content:
        content += "\n"
    linked_size = _size_metrics(content)
    baseline_size = _size_metrics(baseline.content)
    return {
        "backend": backend,
        "content": content,
        "fragments": linked_fragments,
        "comparison": {
            "token_estimator": "ceil(chars / 4)",
            "linked": linked_size,
            "all_in_one": {
                "backend": baseline_backend,
                "path": baseline.path,
                **baseline_size,
            },
            "savings": {
                "chars": baseline_size["chars"] - linked_size["chars"],
                "approx_tokens": baseline_size["approx_tokens"] - linked_size["approx_tokens"],
            },
        },
    }


def _size_metrics(content: str) -> Dict[str, int]:
    return {
        "chars": len(content),
        "approx_tokens": (len(content) + 3) // 4,
    }


def _pipeline_execution_plan(
    link_plan: Dict[str, Any],
    target_pipelines: List[Dict[str, Any]],
    prompt_prefix: Dict[str, Any],
    output_validation: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "selected_target": link_plan["selected_targets"][0] if link_plan["selected_targets"] else None,
        "resolved_deps": list(link_plan["target_closure"]),
        "pipeline_operations": _flatten_pipeline_ops(target_pipelines, "operations"),
        "stable_prefix_objects": list(prompt_prefix.get("fragments", [])),
        "volatile_context_inputs": _flatten_pipeline_ops(target_pipelines, "context_ops"),
        "guards_evaluated": _flatten_pipeline_ops(target_pipelines, "guard_ops"),
        "permissions_checked": _flatten_pipeline_ops(target_pipelines, "permission_ops"),
        "output_schema_validation": output_validation,
        "fallback_plan": _flatten_pipeline_ops(target_pipelines, "fallback_ops"),
    }


def _flatten_pipeline_ops(target_pipelines: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    operations: List[Dict[str, Any]] = []
    for pipeline in target_pipelines:
        for operation in pipeline.get(key, []):
            operations.append({"target": pipeline.get("target"), **operation})
    return operations


def _target_contract(target: IRTarget) -> Dict[str, Any]:
    return {
        "name": target.name,
        "deps": list(target.deps),
        "policies": [policy.name for policy in target.policies],
        "skills": [skill.qualified_name for skill in target.skills],
        "guards": list(target.guards),
        "steps": list(target.steps),
        "output_format": list(target.output_format),
        "fallback": target.fallback,
    }


def _policy_contracts(targets: List[IRTarget]) -> List[Dict[str, Any]]:
    contracts = []
    seen = set()
    for target in targets:
        for policy in target.policies:
            if policy.name in seen:
                continue
            seen.add(policy.name)
            contracts.append(_policy_contract(policy))
    return contracts


def _policy_contract(policy: IRPolicy) -> Dict[str, Any]:
    return {
        "name": policy.name,
        "guards": list(policy.guards),
        "steps": list(policy.steps),
        "output_format": list(policy.output_format),
    }


def _guard_evaluation(targets: List[IRTarget]) -> Dict[str, Any]:
    guards = []
    for target in targets:
        for policy in target.policies:
            for guard in policy.guards:
                guards.append(
                    {
                        "source": "policy",
                        "target": target.name,
                        "policy": policy.name,
                        "guard": guard,
                        "status": "planned",
                    }
                )
        for guard in target.guards:
            guards.append(
                {
                    "source": "target",
                    "target": target.name,
                    "guard": guard,
                    "status": "planned",
                }
            )
    return {"mode": "dry_run", "executed": False, "guards": guards}


def _permission_contract(ir: AgentRuleIR) -> Dict[str, Any]:
    return {
        "defaults": {tool: ir.permission_defaults[tool] for tool in sorted(ir.permission_defaults)},
        "rules": [
            {"tool": permission.tool, "pattern": permission.pattern, "action": permission.action}
            for permission in sorted(ir.permissions, key=lambda item: (item.tool, item.pattern))
        ],
    }


def _permission_evaluation(
    ir: AgentRuleIR,
    proposed_tool_calls: List[Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "mode": "dry_run",
        "executed": False,
        "default_action": IMPLICIT_PERMISSION_ACTION,
        "tool_calls": [
            _evaluate_tool_call(ir, tool_call)
            for tool_call in proposed_tool_calls
        ],
    }


def _evaluate_tool_call(ir: AgentRuleIR, tool_call: Dict[str, str]) -> Dict[str, Any]:
    tool = tool_call["tool"]
    input_text = tool_call["input"]
    matches = [
        permission
        for permission in sorted(ir.permissions, key=lambda item: (item.tool, item.pattern))
        if permission.tool == tool and fnmatchcase(input_text, permission.pattern)
    ]
    if matches:
        action = _most_restrictive_action([permission.action for permission in matches])
        source = "rule"
    elif tool in ir.permission_defaults:
        action = ir.permission_defaults[tool]
        source = "default"
    else:
        action = IMPLICIT_PERMISSION_ACTION
        source = "implicit_default"
    result = {
        "tool": tool,
        "input": input_text,
        "action": action,
        "source": source,
        "matched_rules": [_permission_record(permission) for permission in matches],
    }
    if "id" in tool_call:
        result["id"] = tool_call["id"]
    return result


def _most_restrictive_action(actions: List[PermissionAction]) -> PermissionAction:
    return max(actions, key=lambda action: PERMISSION_ACTION_RANK[action])


def _permission_record(permission: IRPermission) -> Dict[str, str]:
    return {
        "tool": permission.tool,
        "pattern": permission.pattern,
        "action": permission.action,
    }


def _output_validation(
    targets: List[IRTarget],
    proposed_output: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    target_records = [
        _target_output_validation(target, proposed_output)
        for target in targets
    ]
    if proposed_output is None:
        status = "not_evaluated"
    elif any(record["status"] == "invalid" for record in target_records):
        status = "invalid"
    else:
        status = "valid"
    return {
        "mode": "dry_run",
        "executed": False,
        "provided": proposed_output is not None,
        "status": status,
        "targets": target_records,
    }


def _target_output_validation(
    target: IRTarget,
    proposed_output: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    required_fields = _target_required_output_fields(target)
    present_fields = sorted(proposed_output) if proposed_output is not None else []
    missing_fields = [
        field
        for field in required_fields
        if proposed_output is not None and field not in proposed_output
    ]
    type_errors = _schema_type_errors(target, proposed_output)
    schema_errors = _schema_validation_errors(target, proposed_output)
    if proposed_output is None:
        status = "planned"
    elif missing_fields or type_errors or schema_errors:
        status = "invalid"
    else:
        status = "valid"
    record = {
        "target": target.name,
        "required_fields": required_fields,
        "present_fields": present_fields,
        "missing_fields": missing_fields,
        "type_errors": type_errors,
        "status": status,
    }
    if schema_errors:
        record["schema_errors"] = schema_errors
    return record


def _target_required_output_fields(target: IRTarget) -> List[str]:
    fields: List[str] = []
    for policy in target.policies:
        fields.extend(policy.output_format)
        fields.extend(_schema_required_fields(policy.output_schema))
    fields.extend(target.output_format)
    fields.extend(_schema_required_fields(target.output_schema))
    return _unique_preserving_order(fields)


def _schema_required_fields(output_schema: Dict[str, Any]) -> List[str]:
    required = output_schema.get("required", [])
    if not isinstance(required, list):
        return []
    return [field for field in required if isinstance(field, str)]


def _schema_type_errors(target: IRTarget, proposed_output: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    if proposed_output is None:
        return []
    errors = []
    schema_properties: Dict[str, Any] = {}
    for policy in target.policies:
        schema_properties.update(_schema_properties(policy.output_schema))
    schema_properties.update(_schema_properties(target.output_schema))
    for field in sorted(schema_properties):
        if field not in proposed_output:
            continue
        expected_type = _schema_property_type(schema_properties[field])
        if expected_type is None:
            continue
        if not _matches_json_schema_type(proposed_output[field], expected_type):
            errors.append(
                {
                    "field": field,
                    "expected": expected_type,
                    "actual": _json_value_type(proposed_output[field]),
                }
            )
    return errors


def _schema_validation_errors(
    target: IRTarget,
    proposed_output: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if proposed_output is None:
        return []
    errors = []
    for source, schema in _output_schema_sources(target):
        validator = Draft202012Validator(schema)
        for error in sorted(validator.iter_errors(proposed_output), key=_jsonschema_error_sort_key):
            if error.validator == "required" and not error.path:
                continue
            if error.validator == "type" and len(error.path) == 1:
                continue
            errors.append(
                {
                    "source": source,
                    "path": list(error.path),
                    "validator": str(error.validator),
                    "message": error.message,
                }
            )
    return errors


def _output_schema_sources(target: IRTarget) -> List[tuple[str, Dict[str, Any]]]:
    sources: List[tuple[str, Dict[str, Any]]] = []
    for policy in target.policies:
        if policy.output_schema:
            sources.append(("policy", policy.output_schema))
    if target.output_schema:
        sources.append(("target", target.output_schema))
    return sources


def _jsonschema_error_sort_key(error: Any) -> tuple[str, str, str]:
    path = ".".join(str(part) for part in error.path)
    schema_path = ".".join(str(part) for part in error.schema_path)
    return (path, str(error.validator), schema_path)


def _schema_properties(output_schema: Dict[str, Any]) -> Dict[str, Any]:
    properties = output_schema.get("properties", {})
    if not isinstance(properties, dict):
        return {}
    return properties


def _schema_property_type(property_schema: Any) -> Optional[str]:
    if not isinstance(property_schema, dict):
        return None
    schema_type = property_schema.get("type")
    if not isinstance(schema_type, str):
        return None
    return schema_type


def _matches_json_schema_type(value: Any, schema_type: str) -> bool:
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "null":
        return value is None
    return True


def _json_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _unique_preserving_order(values: List[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
