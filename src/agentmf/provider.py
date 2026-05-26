from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from agentmf.diagnostics import Diagnostics


ProviderRunner = Callable[[Dict[str, Any], str], Dict[str, Any]]


@dataclass(frozen=True)
class ProviderAdapter:
    name: str
    default_model: str
    run: ProviderRunner


def run_provider(
    provider: str,
    model: Optional[str],
    prompt_payload: Dict[str, Any],
    diagnostics: Diagnostics,
) -> Dict[str, Any]:
    adapter = PROVIDER_ADAPTERS.get(provider)
    if adapter is None:
        diagnostics.error(
            "AMF141",
            f"unsupported provider: {provider}",
            "ask.provider",
            "use one of: echo",
        )
        return {}
    resolved_model = model or adapter.default_model
    return adapter.run(prompt_payload, resolved_model)


def _echo_provider(prompt_payload: Dict[str, Any], model: str) -> Dict[str, Any]:
    selected_targets = prompt_payload["selected_targets"]
    target_lines = "\n".join(f"- {target}" for target in selected_targets)
    final_prompt = prompt_payload["final_prompt"]
    stable_prefix = prompt_payload["stable_prefix"]
    content = (
        "Echo provider response\n\n"
        "Selected targets:\n"
        f"{target_lines}\n\n"
        f"Stable prefix hash: {stable_prefix['hash']}\n"
        f"Final prompt hash: {final_prompt['hash']}\n"
        f"Final prompt chars: {final_prompt['chars']}\n"
    )
    return {
        "provider": "echo",
        "model": model,
        "content": content,
        "finish_reason": "stop",
    }


PROVIDER_ADAPTERS = {
    "echo": ProviderAdapter(name="echo", default_model="echo-v1", run=_echo_provider),
}
