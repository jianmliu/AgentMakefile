"""Token-only cost metering — the EVM-gas analog for the bounded dimension.

Scope: tokens only (LLM API). Tool / local-compute / external-spend are a
separate, deferred dimension (a token budget cannot see them). Within tokens,
everything is either countable (input) or cappable (output / total), so the
worst case is known up front and surprise bills cannot happen.

`TokenBudget` is a runtime meter, like an EVM `gasLimit`:
  - pre-call: a worst-case ceiling = input_tokens + max_output_per_call.
  - it accumulates spend across turns (context grows each turn).
  - it HARD-STOPS (halts) before a call it cannot afford, and when the total
    budget is exhausted — so a multi-turn agent loop terminates within budget.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple


def _litellm_cost_per_token(model: str, prompt_tokens: int, completion_tokens: int
                            ) -> Optional[Tuple[float, float]]:
    """Optional integration point: defer to LiteLLM's maintained price table when
    available. Returns (input_usd, output_usd) or None if unavailable.

    LiteLLM ships a comprehensive, kept-current pricing table for hundreds of
    provider models. If the user has it installed and gives us a `model`, we
    use it — no need to reimplement the table or learn it ourselves.
    Inline / external `pricing` always wins (see `resolved_pricing()`); this is
    the fallback when the user hasn't authored prices for that model.
    """
    try:
        import litellm  # optional dependency
        return litellm.cost_per_token(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
    except Exception:
        return None


def estimate_tokens(text: str) -> int:
    """Cheap deterministic token estimate (~chars/4), no dependency.

    Swap in a real tokenizer where exactness matters; the meter logic is the same.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass
class TokenBudget:
    """A per-task token budget meter (gasLimit for tokens).

    Optional `pricing` ({"input_per_mtok": float, "output_per_mtok": float})
    enables a derived USD view via `estimated_usd_*`. Pricing is advisory: real
    bills include caching tiers, retries, thinking tokens — apply a +20-30%
    buffer when treating these numbers as a hard cost cap.
    """

    total: int                      # total token budget for the task
    max_output_per_call: int        # output cap per model call (clamped, see below)
    pricing: Optional[dict] = None  # {input_per_mtok, output_per_mtok} — explicit
    model: Optional[str] = None     # used for LiteLLM cost_per_token fallback
    # Anti-DoS clamp (per LiteLLM): a caller asking for max_output=999_999_999
    # would pin the budget at remaining headroom. Cap the effective output at
    # min(caller_requested, model_max_output_tokens). None = no model ceiling.
    model_max_output_tokens: Optional[int] = None
    # Per-call ABSOLUTE caps (the "C" dimension). Independent of total budget:
    # rejects a single call whose worst case exceeds these, even when the total
    # budget would still fit it. Defends against accidental oversized prompts
    # (e.g. 1MB file pasted in) and reverse-DoS where any one call is too
    # expensive to be sane. Distinct from total-budget refuse: rejecting on
    # per-call cap does NOT halt the session — only THIS call is refused, the
    # next normal-sized call still goes through.
    max_per_call_tokens: Optional[int] = None
    max_per_call_usd: Optional[float] = None
    spent: int = 0
    spent_input: int = 0
    spent_output: int = 0
    turns: int = 0
    halted: bool = False

    @property
    def effective_max_output(self) -> int:
        """Clamped per-call output cap. Per LiteLLM's _estimate_output_tokens:
        a model can only physically emit up to its model ceiling, so reserving
        more is wasteful and a DoS surface."""
        if self.model_max_output_tokens is None:
            return self.max_output_per_call
        return min(self.max_output_per_call, self.model_max_output_tokens)

    def _resolved_pricing(self, prompt_tokens: int = 0, completion_tokens: int = 0
                          ) -> Optional[Tuple[float, float]]:
        """Returns per-direction $/M-token tuple. Resolution order:
        explicit `pricing` > LiteLLM `cost_per_token` (if `model` set and lib
        installed) > None. This matches AgentMakefile's selector convention.

        Returned as ($/M input, $/M output) for symmetry, not the per-call
        absolute amounts.
        """
        if self.pricing:
            return (self.pricing.get("input_per_mtok", 0.0),
                    self.pricing.get("output_per_mtok", 0.0))
        if self.model:
            # Probe with 1M tokens so the returned per-direction $ equals the
            # per-million rate (the LiteLLM API takes token counts, returns USD).
            result = _litellm_cost_per_token(self.model, 1_000_000, 1_000_000)
            if result is not None:
                in_usd, out_usd = result
                return (in_usd, out_usd)
        return None

    def remaining(self) -> int:
        return max(0, self.total - self.spent)

    def per_call_ceiling(self, input_text: str) -> int:
        """Worst-case tokens for one call = input (countable) + clamped output cap.

        The output term uses `effective_max_output`, i.e. min(caller_max,
        model_ceiling) — same anti-DoS clamp as LiteLLM's _estimate_output_tokens.
        """
        return estimate_tokens(input_text) + self.effective_max_output

    def can_afford(self, input_text: str) -> bool:
        """Would the WORST CASE of the next call still fit the remaining budget?"""
        return not self.halted and self.per_call_ceiling(input_text) <= self.remaining()

    def check_or_halt(self, input_text: str) -> bool:
        """Pre-call gate. Three independent reasons to refuse the next call:

          (1) Session halted from a previous refusal/exhaustion.
          (2) Total-budget refusal — worst case > remaining → halt the session.
          (3) Per-call absolute cap — worst case > max_per_call_{tokens,usd} →
              refuse THIS call only; session continues (next normal-sized call
              still allowed).

        Returns True iff the caller may make the call. Refusing before an
        unaffordable call is what bounds the bill.
        """
        if self.halted:
            return False
        ceiling = self.per_call_ceiling(input_text)
        # (2) total-budget refusal — halts the session
        if ceiling > self.remaining():
            self.halted = True
            return False
        # (3) per-call absolute caps — refuse this call, do NOT halt the session
        if self.max_per_call_tokens is not None and ceiling > self.max_per_call_tokens:
            return False
        if self.max_per_call_usd is not None:
            usd = self.estimated_usd_ceiling(input_text)
            if usd is not None and usd > self.max_per_call_usd:
                return False
        return True

    def charge(self, input_text: str, output_text: str) -> int:
        """Post-call: deduct actual tokens, accumulate across turns, halt if spent."""
        in_tok = estimate_tokens(input_text)
        out_tok = estimate_tokens(output_text)
        used = in_tok + out_tok
        self.spent += used
        self.spent_input += in_tok
        self.spent_output += out_tok
        self.turns += 1
        if self.spent >= self.total:
            self.halted = True
        return used

    def estimated_usd_ceiling(self, input_text: str) -> Optional[float]:
        """USD worst-case for the next call. Pricing resolution order:
        explicit `pricing` > LiteLLM `cost_per_token` for `model` > None.

        Output term uses the CLAMPED max (effective_max_output), so a caller
        with max_output=999_999_999 can't inflate the ceiling.
        """
        rates = self._resolved_pricing()
        if rates is None:
            return None
        ip, op = rates
        return (estimate_tokens(input_text) * ip + self.effective_max_output * op) / 1_000_000

    def estimated_usd_spent(self) -> Optional[float]:
        """USD spent so far, from per-direction token tallies × resolved rates."""
        rates = self._resolved_pricing()
        if rates is None:
            return None
        ip, op = rates
        return (self.spent_input * ip + self.spent_output * op) / 1_000_000

    def trace(self) -> dict:
        view = {
            "total": self.total,
            "spent": self.spent,
            "spent_input": self.spent_input,
            "spent_output": self.spent_output,
            "remaining": self.remaining(),
            "turns": self.turns,
            "max_output_per_call": self.max_output_per_call,
            "max_per_call_tokens": self.max_per_call_tokens,
            "max_per_call_usd": self.max_per_call_usd,
            "halted": self.halted,
        }
        if self.pricing:
            view["pricing"] = dict(self.pricing)
            view["estimated_usd_spent"] = self.estimated_usd_spent()
        return view
