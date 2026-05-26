from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.runtime import create_run_plan

SUPPORTED_TOOLS = ["bash"]
TOOL_TIMEOUT_SECONDS = 30


@dataclass
class ExecPayloadResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_exec_payload(
    path: Union[Path, str],
    request: Optional[str] = None,
    target_names: Optional[List[str]] = None,
    backend: str = "agents-fragments",
    tool_calls: Optional[List[Dict[str, str]]] = None,
    apply: bool = False,
    cwd: Optional[Union[Path, str]] = None,
) -> ExecPayloadResult:
    diagnostics = Diagnostics()
    normalized_tool_calls = _normalize_tool_calls(tool_calls or [])
    if not apply:
        diagnostics.error(
            "AMF142",
            "tool execution requires --apply",
            "exec.apply",
            "rerun with --apply after reviewing the selected target, guards, and permission decisions",
        )
        return ExecPayloadResult(diagnostics)

    run_result = create_run_plan(
        path=path,
        request=request,
        target_names=target_names,
        backend=backend,
        dry_run=True,
        proposed_tool_calls=normalized_tool_calls,
    )
    diagnostics.extend(run_result.diagnostics.items)
    if diagnostics.has_errors:
        return ExecPayloadResult(diagnostics)

    permission_decisions = run_result.plan["permission_evaluation"]["tool_calls"]
    payload = {
        "version": 1,
        "mode": "exec",
        "execution": {
            "enabled": True,
            "applied": True,
            "tool_loop": "prototype",
            "supported_tools": list(SUPPORTED_TOOLS),
        },
        "runtime_plan": run_result.plan,
        "tool_results": [
            _run_tool_call(permission_decision, cwd=Path(cwd) if cwd is not None else Path(path).parent)
            for permission_decision in permission_decisions
        ],
        "diagnostics": diagnostics.to_list(),
    }
    return ExecPayloadResult(diagnostics, payload)


def _normalize_tool_calls(tool_calls: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return [
        {
            "tool": tool_call["tool"],
            "input": tool_call.get("input", ""),
        }
        for tool_call in tool_calls
    ]


def _run_tool_call(permission_decision: Dict[str, Any], cwd: Path) -> Dict[str, Any]:
    tool = permission_decision["tool"]
    input_text = permission_decision["input"]
    permission_action = permission_decision["action"]
    if permission_action != "allow":
        return {
            "tool": tool,
            "input": input_text,
            "status": "blocked",
            "reason": f"permission_{permission_action}",
            "permission_action": permission_action,
        }
    if tool not in SUPPORTED_TOOLS:
        return {
            "tool": tool,
            "input": input_text,
            "status": "blocked",
            "reason": "unsupported_tool",
            "permission_action": permission_action,
        }
    return _run_bash(input_text, cwd)


def _run_bash(command: str, cwd: Path) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ["bash", "-lc", command],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=TOOL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "tool": "bash",
            "input": command,
            "status": "timeout",
            "timeout_seconds": TOOL_TIMEOUT_SECONDS,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    return {
        "tool": "bash",
        "input": command,
        "status": "executed" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
