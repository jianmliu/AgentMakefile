from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agentmf.compiler import compile_agentmakefile
from agentmf.diagnostics import Diagnostics
from agentmf.ir import normalize
from agentmf.loader import load_source_with_diagnostics
from agentmf.models import AgentRuleIR, IRPolicy, IRTarget
from agentmf.selector import create_link_plan


BASELINE_BACKENDS = {
    "agents-fragments": ("agents-md", "AGENTS.md"),
    "claude-fragments": ("claude-md", "CLAUDE.md"),
}

RUNTIME_PHASES = [
    {"name": "target_selection", "status": "resolved"},
    {"name": "dependency_graph_resolution", "status": "resolved"},
    {"name": "prompt_fragment_linking", "status": "linked"},
    {"name": "guard_evaluation", "status": "not_executed"},
    {"name": "permission_enforcement", "status": "not_executed"},
    {"name": "step_execution", "status": "not_executed"},
    {"name": "output_validation", "status": "not_executed"},
    {"name": "fallback_handling", "status": "not_executed"},
    {"name": "trace_logging", "status": "planned"},
]


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

    link_result = create_link_plan(path, request=request, target_names=target_names, backend=backend)
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
        "runtime_phases": list(RUNTIME_PHASES),
        "target_contracts": [_target_contract(target) for target in target_closure],
        "policy_contracts": _policy_contracts(target_closure),
        "permission_contract": _permission_contract(ir),
    }
    return RunPlanResult(diagnostics, plan)


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


def _permission_contract(ir: AgentRuleIR) -> Dict[str, Any]:
    return {
        "defaults": {tool: ir.permission_defaults[tool] for tool in sorted(ir.permission_defaults)},
        "rules": [
            {"tool": permission.tool, "pattern": permission.pattern, "action": permission.action}
            for permission in sorted(ir.permissions, key=lambda item: (item.tool, item.pattern))
        ],
    }
