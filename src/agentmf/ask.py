from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.prompt import create_prompt_payload
from agentmf.provider import run_provider


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
    )
    diagnostics.extend(prompt_result.diagnostics.items)
    if diagnostics.has_errors:
        return AskPayloadResult(diagnostics)

    response = run_provider(provider, model, prompt_result.payload, diagnostics)
    if diagnostics.has_errors:
        return AskPayloadResult(diagnostics)

    payload = {
        "version": 1,
        "mode": "ask",
        "provider": response["provider"],
        "model": response["model"],
        "provider_options": {
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        },
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
