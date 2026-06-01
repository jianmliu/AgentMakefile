from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.prompt import create_prompt_payload
from agentmf.provider import run_provider
from agentmf.token_budget import estimate_tokens


@dataclass
class AskPayloadResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_ask_payload(
    path: Union[Path, str],
    request: Optional[str] = None,
    target_names: Optional[List[str]] = None,
    backend: str = "agents-fragments",
    plan_path: Optional[Union[Path, str]] = None,
    context_files: Optional[List[Union[Path, str]]] = None,
    include_git_status: bool = False,
    include_git_diff: bool = False,
    provider: str = "echo",
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    token_budget: Optional[int] = None,
    max_output_per_call: Optional[int] = None,
) -> AskPayloadResult:
    diagnostics = Diagnostics()
    prompt_result = create_prompt_payload(
        path=path,
        request=request,
        target_names=target_names,
        backend=backend,
        plan_path=plan_path,
        context_files=context_files,
        include_git_status=include_git_status,
        include_git_diff=include_git_diff,
        budget=float(token_budget) if token_budget is not None else None,
    )
    diagnostics.extend(prompt_result.diagnostics.items)
    if diagnostics.has_errors:
        return AskPayloadResult(diagnostics)

    response = run_provider(provider, model, prompt_result.payload, diagnostics)
    if diagnostics.has_errors:
        return AskPayloadResult(diagnostics)

    effective_max_out = max_output_per_call if max_output_per_call is not None else (max_output_tokens or 1024)
    stable = prompt_result.payload["stable_prefix"]["content"]
    stable_tokens = estimate_tokens(stable)
    link_budget = prompt_result.payload.get("budget") or {}
    token_budget_block: Optional[Dict[str, Any]] = None
    if token_budget is not None or max_output_per_call is not None:
        token_budget_block = {
            "total": token_budget,
            "max_output_per_call": effective_max_out,
            "stable_prefix_tokens": stable_tokens,
            "per_call_ceiling": stable_tokens + effective_max_out,
            "dropped_over_budget": list(link_budget.get("dropped_over_budget") or []),
            "halt_policy": "host should refuse next call if per_call_ceiling > remaining; charge actual usage after each call",
        }
        if token_budget is not None:
            token_budget_block["fits_first_call"] = token_budget_block["per_call_ceiling"] <= token_budget
            token_budget_block["headroom_after_first_call"] = max(0, token_budget - token_budget_block["per_call_ceiling"])

    payload = {
        "version": 1,
        "mode": "ask",
        "provider": response["provider"],
        "model": response["model"],
        "provider_options": {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        },
        "token_budget": token_budget_block,
        "prompt_payload": prompt_result.payload,
        "response": response,
        "trace": {
            "provider": response["provider"],
            "model": response["model"],
            "selected_targets": list(prompt_result.payload["selected_targets"]),
            "stable_prefix_hash": prompt_result.payload["stable_prefix"]["hash"],
            "final_prompt_hash": prompt_result.payload["final_prompt"]["hash"],
        },
        "diagnostics": diagnostics.to_list(),
    }
    return AskPayloadResult(diagnostics, payload)
