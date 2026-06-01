# Budget-aware skill selection demo

Token-only cost guardrail in two parts:

1. **Selection time** — `agentmf select --budget N` (and the same param on `ask`
   / `plugin payload` as `--token-budget`) drops targets whose loading `cost`
   exceeds the budget *before* matching. So a cheaper relevant skill is picked,
   or selection abstains — never load a skill you can't afford.
2. **Run time** — `agentmf.token_budget.TokenBudget` is an EVM-`gasLimit`-style
   meter: pre-call worst-case ceiling (input + output cap), refusal before any
   call that wouldn't fit, post-call charge across multi-turn, **hard-stop**
   when the budget is spent or the next call's ceiling exceeds remaining.

## Try it (selection half)

```bash
agentmf validate --file demos/budget-aware/AgentMakefile

# no budget -> highest-ranked target wins
agentmf select --file demos/budget-aware/AgentMakefile --request "answer a question" --format json

# tight budget -> the heavy skill is dropped, the cheap one is selected
agentmf select --file demos/budget-aware/AgentMakefile --request "answer a question" --budget 200 --format json

# budget below every target -> AMF118 (abstain, surface-bill safe)
agentmf select --file demos/budget-aware/AgentMakefile --request "answer a question" --budget 10 --format json

# Same flag flows into plugin payload + ask:
agentmf plugin payload --host codex --file demos/budget-aware/AgentMakefile \
  --request "answer a question" --token-budget 200 --max-output-per-call 1024 --format json
```

## What you'll see

| budget | selected | dropped_over_budget | reason |
| --- | --- | --- | --- |
| (none) | `deep.analysis` | — | highest priority, cost ignored |
| 200 | `quick.answer` | `deep.analysis` | heavy skill (cost 4000) doesn't fit |
| 10 | — (AMF118) | both | abstain rather than overspend |

Plugin payload + ask additionally emit a `token_budget` block:

```json
{
  "total": 200,
  "max_output_per_call": 1024,
  "stable_prefix_tokens": 87,
  "per_call_ceiling": 1111,
  "fits_first_call": false,
  "headroom_after_first_call": 0,
  "dropped_over_budget": ["deep.analysis"],
  "halt_policy": "host should refuse next call if per_call_ceiling > remaining; charge actual usage after each call"
}
```

`per_call_ceiling = stable_prefix_tokens + max_output_per_call`. If
`fits_first_call: false`, the host knows up front that one call won't fit and
should either raise the budget, shrink the prefix, or abstain.

## Run time (multi-turn hard-stop)

```python
from agentmf.token_budget import TokenBudget

b = TokenBudget(total=400, max_output_per_call=50)
ctx = "system prompt..."
while b.check_or_halt(ctx):   # refuses next call if worst case > remaining
    out = call_model(ctx, max_output=b.max_output_per_call)
    b.charge(ctx, out)        # deduct actual; halts when total spent
    ctx += out                # context grows -> next ceiling grows too
# b.halted == True; b.spent <= b.total — surprise bill in token dimension impossible
```

## Honest scope

**Token-only.** Tool calls / local compute / external paid APIs spend in
dimensions a token meter cannot see (a SCIP solver burns wall-clock not tokens; a
paid API spends real dollars). Those are a separate, deferred dimension. The
token half is what closes cleanly here: input is countable, output is cappable,
total is gated, multi-turn hard-stops — so surprise *token* bills are impossible.
See `docs/agentmf_budget_aware_spec.md`.
