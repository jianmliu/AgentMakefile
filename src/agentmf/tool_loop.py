from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shlex
import subprocess
from typing import Any, Dict, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.runtime import create_run_plan
from agentmf.token_budget import TokenBudget, estimate_tokens

SUPPORTED_TOOLS = ["bash"]
TOOL_TIMEOUT_SECONDS = 30
SANDBOX_PROFILES = {
    "none": {
        "mode": "disabled",
        "enforced": False,
        "filesystem": "unrestricted_requested",
        "network": "not_configured",
    },
    "read-only": {
        "mode": "prototype_preflight",
        "enforced": True,
        "filesystem": "read_only_preflight",
        "network": "not_configured",
    },
    "workspace-write": {
        "mode": "prototype_preflight",
        "enforced": True,
        "filesystem": "workspace_write_preflight",
        "network": "not_configured",
    },
}
WRITE_LIKE_BASH_COMMANDS = {
    "chmod",
    "chown",
    "cp",
    "install",
    "ln",
    "mkdir",
    "mv",
    "rm",
    "rmdir",
    "sed",
    "tee",
    "touch",
    "truncate",
}
WRITE_REDIRECTION_MARKERS = (">", ">>", ">|", "1>", "2>", "&>")


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
    sandbox_profile: str = "workspace-write",
    execute_fallbacks: bool = False,
    provider: str = "host",
    token_budget: Optional[int] = None,
    max_output_per_call: int = 1024,
    max_per_call_tokens: Optional[int] = None,
    max_per_call_usd: Optional[float] = None,
    pricing_table: Optional[Union[Path, str]] = None,
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
    sandbox = _sandbox_metadata(sandbox_profile, diagnostics)
    if diagnostics.has_errors:
        return ExecPayloadResult(diagnostics)

    run_result = create_run_plan(
        path=path,
        request=request,
        target_names=target_names,
        backend=backend,
        dry_run=True,
        proposed_tool_calls=normalized_tool_calls,
        pricing_table=pricing_table,
    )
    diagnostics.extend(run_result.diagnostics.items)
    if diagnostics.has_errors:
        return ExecPayloadResult(diagnostics)

    permission_decisions = run_result.plan["permission_evaluation"]["tool_calls"]
    execution_cwd = Path(cwd) if cwd is not None else Path(path).parent

    # Token-budget meter: when set, the meter HARD-STOPS the tool loop before a
    # call whose worst case wouldn't fit the remaining budget. This makes
    # "surprise bills in the token dimension" impossible for calls running
    # THROUGH agentmf exec — host-driven calls still rely on the contract.
    # Enable the meter if EITHER a total budget OR per-call caps are configured.
    # Per-call caps (C-dimension) are useful even without a total cap: they
    # defend against an accidentally oversized prompt regardless of total spend.
    meter: Optional[TokenBudget] = None
    if token_budget is not None or max_per_call_tokens is not None or max_per_call_usd is not None:
        meter = TokenBudget(
            total=token_budget if token_budget is not None else 10**12,  # effectively unbounded
            max_output_per_call=max_output_per_call,
            max_per_call_tokens=max_per_call_tokens,
            max_per_call_usd=max_per_call_usd,
        )
    tool_results: List[Dict[str, Any]] = []
    for permission_decision in permission_decisions:
        if meter is not None:
            input_text = permission_decision.get("input", "") or ""
            if not meter.check_or_halt(input_text):
                # Distinguish C (per-call cap → this call only) from B (total
                # cap exhausted → session halted). meter.halted is the signal.
                if meter.halted:
                    status, why = "halted_over_budget", (
                        f"token budget exhausted or next call's worst-case ceiling "
                        f"({meter.per_call_ceiling(input_text)}) > remaining ({meter.remaining()})"
                    )
                else:
                    status, why = "oversized_call", (
                        f"single-call worst case "
                        f"({meter.per_call_ceiling(input_text)} tokens) exceeds "
                        f"per-call cap (max_per_call_tokens={max_per_call_tokens}, "
                        f"max_per_call_usd={max_per_call_usd}); session continues"
                    )
                tool_results.append({
                    **_tool_result_base(permission_decision),
                    "status": status,
                    "reason": why,
                })
                continue
        result = _run_tool_call(permission_decision, cwd=execution_cwd, sandbox=sandbox)
        if meter is not None and result.get("status") == "executed":
            stdout = (result.get("stdout") or "") + (result.get("stderr") or "")
            meter.charge(permission_decision.get("input", "") or "", stdout)
        tool_results.append(result)
    payload = {
        "version": 1,
        "mode": "exec",
        "execution": {
            "enabled": True,
            "applied": True,
            "tool_loop": "prototype",
            "supported_tools": list(SUPPORTED_TOOLS),
            "sandbox_profile": sandbox_profile,
        },
        "sandbox": sandbox,
        "runtime_plan": run_result.plan,
        "tool_results": tool_results,
        "token_budget": (meter.trace() if meter is not None else None),
        "tool_interception": _tool_interception_contract(
            provider=provider,
            permission_decisions=permission_decisions,
            tool_results=tool_results,
            sandbox=sandbox,
        ),
        "fallback_handling": _fallback_handling(
            run_result.plan,
            tool_results,
            execute_fallbacks=execute_fallbacks,
        ),
        "diagnostics": diagnostics.to_list(),
    }
    return ExecPayloadResult(diagnostics, payload)


def _normalize_tool_calls(tool_calls: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized_tool_calls = []
    for tool_call in tool_calls:
        normalized = {
            "tool": tool_call["tool"],
            "input": tool_call.get("input", ""),
        }
        if "id" in tool_call:
            normalized["id"] = tool_call["id"]
        normalized_tool_calls.append(normalized)
    return normalized_tool_calls


def _sandbox_metadata(sandbox_profile: str, diagnostics: Diagnostics) -> Dict[str, Any]:
    profile = SANDBOX_PROFILES.get(sandbox_profile)
    if profile is None:
        diagnostics.error(
            "AMF143",
            f"unsupported sandbox profile: {sandbox_profile}",
            "exec.sandbox_profile",
            f"use one of: {', '.join(SANDBOX_PROFILES)}",
        )
        return {}
    return {
        "profile": sandbox_profile,
        **profile,
        "supported_profiles": list(SANDBOX_PROFILES),
    }


def _run_tool_call(
    permission_decision: Dict[str, Any],
    cwd: Path,
    sandbox: Dict[str, Any],
) -> Dict[str, Any]:
    tool = permission_decision["tool"]
    input_text = permission_decision["input"]
    permission_action = permission_decision["action"]
    result_base = _tool_result_base(permission_decision)
    if permission_action != "allow":
        return {
            **result_base,
            "status": "blocked",
            "reason": f"permission_{permission_action}",
            "permission_action": permission_action,
        }
    if tool not in SUPPORTED_TOOLS:
        return {
            **result_base,
            "status": "blocked",
            "reason": "unsupported_tool",
            "permission_action": permission_action,
        }
    sandbox_block = _sandbox_block(tool, input_text, sandbox)
    if sandbox_block is not None:
        return {
            **result_base,
            "status": "blocked",
            "reason": sandbox_block,
            "permission_action": permission_action,
            "sandbox_profile": sandbox["profile"],
        }
    result = _run_bash(input_text, cwd)
    if "id" in permission_decision:
        result["id"] = permission_decision["id"]
    return result


def _tool_result_base(permission_decision: Dict[str, Any]) -> Dict[str, Any]:
    result = {
        "tool": permission_decision["tool"],
        "input": permission_decision["input"],
    }
    if "id" in permission_decision:
        result["id"] = permission_decision["id"]
    return result


def _sandbox_block(tool: str, input_text: str, sandbox: Dict[str, Any]) -> Optional[str]:
    if not sandbox.get("enforced") or tool != "bash":
        return None
    if sandbox["profile"] == "read-only" and _bash_command_may_write(input_text):
        return "sandbox_read_only"
    if sandbox["profile"] == "workspace-write" and _bash_command_may_write_outside_workspace(input_text):
        return "sandbox_workspace_write"
    return None


def _bash_command_may_write(command: str) -> bool:
    words = _split_bash_words(command)
    if not words:
        return False
    if _has_write_redirection(words):
        return True
    command_name = Path(words[0]).name
    if command_name == "sed":
        return any(word == "-i" or word.startswith("-i") for word in words[1:])
    return command_name in WRITE_LIKE_BASH_COMMANDS


def _bash_command_may_write_outside_workspace(command: str) -> bool:
    words = _split_bash_words(command)
    if not words:
        return False
    command_name = Path(words[0]).name
    if command_name not in WRITE_LIKE_BASH_COMMANDS and not _has_write_redirection(words):
        return False
    return any(_looks_outside_workspace_operand(word) for word in words[1:])


def _split_bash_words(command: str) -> List[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _has_write_redirection(words: List[str]) -> bool:
    return any(
        word in WRITE_REDIRECTION_MARKERS
        or word.startswith(">")
        or word.startswith("1>")
        or word.startswith("2>")
        or word.startswith("&>")
        for word in words
    )


def _looks_outside_workspace_operand(word: str) -> bool:
    if word.startswith("-"):
        return False
    operand = _strip_redirection_prefix(word)
    return operand.startswith("/") or operand == ".." or operand.startswith("../") or "/../" in operand


def _strip_redirection_prefix(word: str) -> str:
    for prefix in ("1>", "2>", "&>", ">>", ">|", ">"):
        if word.startswith(prefix):
            return word[len(prefix):]
    return word


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


def _tool_interception_contract(
    provider: str,
    permission_decisions: List[Dict[str, Any]],
    tool_results: List[Dict[str, Any]],
    sandbox: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "version": 1,
        "mode": "provider_tool_call_interception",
        "provider": provider,
        "status": "evaluated",
        "events": [
            "provider_tool_call_requested",
            "agentmf_permission_evaluated",
            "agentmf_sandbox_evaluated",
            "host_tool_result_returned",
        ],
        "host_boundary": {
            "provider_requests_tool_call": True,
            "agentmf_evaluates_permissions": True,
            "agentmf_evaluates_sandbox": True,
            "host_executes_allowed_call": True,
            "host_returns_tool_result_to_provider": True,
        },
        "tool_calls": [
            _tool_interception_record(index, decision, result, sandbox)
            for index, (decision, result) in enumerate(zip(permission_decisions, tool_results))
        ],
    }


def _tool_interception_record(
    index: int,
    permission_decision: Dict[str, Any],
    tool_result: Dict[str, Any],
    sandbox: Dict[str, Any],
) -> Dict[str, Any]:
    record = {
        "id": permission_decision.get("id", f"tool_call_{index}"),
        "tool": permission_decision["tool"],
        "input": permission_decision["input"],
        "permission_action": permission_decision["action"],
        "sandbox_profile": sandbox["profile"],
        "interception_decision": "block" if tool_result["status"] == "blocked" else "allow",
        "result_status": tool_result["status"],
    }
    if tool_result["status"] == "blocked":
        record["block_reason"] = tool_result["reason"]
    return record


def _fallback_handling(
    runtime_plan: Dict[str, Any],
    tool_results: List[Dict[str, Any]],
    execute_fallbacks: bool = False,
) -> Dict[str, Any]:
    blocked_results = [tool_result for tool_result in tool_results if tool_result["status"] == "blocked"]
    blocked_tool_calls = [
        _blocked_tool_call_fallback(runtime_plan, tool_result, execute_fallbacks=execute_fallbacks)
        for tool_result in blocked_results
    ]
    if not blocked_tool_calls:
        status = "not_needed"
    elif execute_fallbacks and any(blocked_tool_call["fallbacks"] for blocked_tool_call in blocked_tool_calls):
        status = "executed"
    elif any(blocked_tool_call["fallbacks"] for blocked_tool_call in blocked_tool_calls):
        status = "planned"
    else:
        status = "not_planned"
    return {
        "mode": "prototype" if execute_fallbacks else "dry_run",
        "executed": execute_fallbacks and status == "executed",
        "status": status,
        "blocked_tool_calls": blocked_tool_calls,
    }


def _blocked_tool_call_fallback(
    runtime_plan: Dict[str, Any],
    tool_result: Dict[str, Any],
    execute_fallbacks: bool = False,
) -> Dict[str, Any]:
    return {
        "tool": tool_result["tool"],
        "input": tool_result["input"],
        "reason": tool_result["reason"],
        "permission_action": tool_result["permission_action"],
        "fallbacks": _blocked_fallbacks(runtime_plan, execute_fallbacks=execute_fallbacks),
    }


def _blocked_fallbacks(
    runtime_plan: Dict[str, Any],
    execute_fallbacks: bool = False,
) -> List[Dict[str, Any]]:
    fallbacks = []
    for target in runtime_plan["target_contracts"]:
        actions = target["fallback"].get("blocked", [])
        if not actions:
            continue
        fallback = {
            "target": target["name"],
            "trigger": "blocked",
            "actions": list(actions),
            "status": "executed" if execute_fallbacks else "planned",
        }
        if execute_fallbacks:
            fallback["results"] = [_execute_fallback_action(action) for action in actions]
        fallbacks.append(fallback)
    return fallbacks


def _execute_fallback_action(action: str) -> Dict[str, str]:
    return {
        "action": action,
        "status": "executed",
        "execution": "internal_noop",
    }
