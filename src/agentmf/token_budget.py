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
from typing import Optional


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
    max_output_per_call: int        # output cap per model call
    pricing: Optional[dict] = None  # {input_per_mtok, output_per_mtok}
    spent: int = 0
    spent_input: int = 0
    spent_output: int = 0
    turns: int = 0
    halted: bool = False

    def remaining(self) -> int:
        return max(0, self.total - self.spent)

    def per_call_ceiling(self, input_text: str) -> int:
        """Worst-case tokens for one call = input (countable) + output cap."""
        return estimate_tokens(input_text) + self.max_output_per_call

    def can_afford(self, input_text: str) -> bool:
        """Would the WORST CASE of the next call still fit the remaining budget?"""
        return not self.halted and self.per_call_ceiling(input_text) <= self.remaining()

    def check_or_halt(self, input_text: str) -> bool:
        """Pre-call gate: if the next call's worst case won't fit, halt and refuse.

        Returns True if the caller may make the call, False if it must stop.
        Refusing *before* an unaffordable call is what bounds the bill.
        """
        if not self.can_afford(input_text):
            self.halted = True
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
        """USD worst-case for the next call = input × in_rate + output_cap × out_rate.

        Like EVM gasLimit × gasPrice but split per-direction (LLM API charges
        input and output at different rates). Returns None if pricing not set.
        """
        if not self.pricing:
            return None
        ip = self.pricing.get("input_per_mtok", 0.0)
        op = self.pricing.get("output_per_mtok", 0.0)
        return (estimate_tokens(input_text) * ip + self.max_output_per_call * op) / 1_000_000

    def estimated_usd_spent(self) -> Optional[float]:
        """USD spent so far, from per-direction token tallies × pricing."""
        if not self.pricing:
            return None
        ip = self.pricing.get("input_per_mtok", 0.0)
        op = self.pricing.get("output_per_mtok", 0.0)
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
            "halted": self.halted,
        }
        if self.pricing:
            view["pricing"] = dict(self.pricing)
            view["estimated_usd_spent"] = self.estimated_usd_spent()
        return view
