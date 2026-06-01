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

from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    """Cheap deterministic token estimate (~chars/4), no dependency.

    Swap in a real tokenizer where exactness matters; the meter logic is the same.
    """
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


@dataclass
class TokenBudget:
    """A per-task token budget meter (gasLimit for tokens)."""

    total: int                      # total token budget for the task
    max_output_per_call: int        # output cap per model call
    spent: int = 0
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
        used = estimate_tokens(input_text) + estimate_tokens(output_text)
        self.spent += used
        self.turns += 1
        if self.spent >= self.total:
            self.halted = True
        return used

    def trace(self) -> dict:
        return {
            "total": self.total,
            "spent": self.spent,
            "remaining": self.remaining(),
            "turns": self.turns,
            "max_output_per_call": self.max_output_per_call,
            "halted": self.halted,
        }
