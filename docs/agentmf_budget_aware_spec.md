# AgentMakefile Budget-Aware Selection + Token Budget Meter

Status: prototype (token-only). Date: 2026-06-01.

## Summary

Cost-aware skill selection and a runtime cost meter, scoped to the **token**
dimension. Two parts:

1. **Selection time**: a target's `cost` (token units) is compared to a per-task
   budget; over-budget targets are dropped before matching, so a cheaper relevant
   skill is selected, or selection abstains (AMF118). Advisory; the host owns
   execution.
2. **Run time**: `TokenBudget` is an EVM-`gasLimit` analog for tokens —
   pre-computes the per-call worst-case ceiling (input + `max_output_per_call`),
   **refuses** unaffordable calls up front, **charges** actual usage after each
   call, accumulates across multi-turn, and **hard-stops** when the budget is
   spent or the next call cannot fit.

The motivating finding is the *skill-value band* (see the skill-corpus repo):
heavy-method skills (e.g. one that prescribes a SCIP solver) help only **above a
budget threshold** and **hurt below it** — they burn the budget producing
nothing and displace a working cheap heuristic. Budget-aware selection encodes
that finding as a production rail.

## Scope: token-only by design

Tokens are the dimension where *everything is countable or cappable*: input is
counted from the prompt, output is bounded by `max_tokens`, total is gated, the
multi-turn meter hard-stops. So **surprise bills in the token dimension are
impossible**. Non-token dimensions — tool calls, local compute (CPU/GPU
wall-clock), external paid APIs, on-chain spend — pay in units the token meter
*cannot see* and are a deferred dimension (see `PROPOSAL §10` of the
skill-corpus). A token cap does **not** bound those.

## Schema

```yaml
targets:
  cheap.skill:
    cost: 80           # token units; loading cost (description + body)
    match: { user_intent: [quick answer] }
    steps: [{action: short_answer}]
  heavy.skill:
    priority: 90
    cost: 4000         # methodology-heavy skill
    match: { user_intent: [exhaustive comparison] }
    steps: [{action: gather_evidence}, {action: synthesize}]
```

- `cost: float >= 0`, default `0.0`. **Default 0 means cost-unaware** — selection
  behaves exactly as before when no budget is given.
- When `cost` is omitted (or 0), and a budget is given, cost is **derived from
  the target's token size** (description + steps + guards + skill names). No
  authored number = use the real loading footprint.

## Selection semantics

```
budget given       -> drop {t : t.cost > budget}; match against the rest
budget not given   -> normal selection (no filtering)
all targets dropped-> AMF118 no-match (abstain — preferred to overspending)
```

Output: the link plan includes
```json
"budget": {"limit": 200, "dropped_over_budget": ["heavy.skill"]}
```

## Run-time meter

`TokenBudget(total, max_output_per_call)`:

| method | role | EVM analog |
| --- | --- | --- |
| `per_call_ceiling(input)` | worst-case tokens of next call = input + output cap | `eth_estimateGas` (input deterministic; output bounded) |
| `check_or_halt(input)` | refuse next call if ceiling > remaining; sets `halted` | OOG pre-check |
| `charge(input, output)` | deduct actual; halt when total spent | gas consumption after execution |
| `remaining()` / `trace()` | introspection | — |

The meter is what makes the bill bounded: refuse-before-spending caps the worst
case at `total`, regardless of how randomly the model behaves within turns.

## Surfaces

| surface | parameter | output field |
| --- | --- | --- |
| `agentmf select --budget N` | `budget: float` | `link_plan.budget` |
| `agentmf plugin payload --token-budget N --max-output-per-call M` | `token_budget: int`, `max_output_per_call: int` | `plugin_payload.token_budget` (full meter view incl. `fits_first_call`) |
| `agentmf ask --token-budget N --max-output-per-call M` | same | `ask_payload.token_budget` |
| `from agentmf.token_budget import TokenBudget` | constructor | `.trace()` |

The meter view fields:

```json
{
  "total": 200, "max_output_per_call": 1024,
  "stable_prefix_tokens": 87,
  "per_call_ceiling": 1111,
  "fits_first_call": false,
  "headroom_after_first_call": 0,
  "dropped_over_budget": ["heavy.skill"],
  "halt_policy": "host should refuse next call if per_call_ceiling > remaining; charge actual usage after each call"
}
```

`fits_first_call=false` is the **early-warning signal**: the host can see, before
making any call, that the budget can't even cover the stable prefix plus one
output. Raise the budget, shrink the prefix, or abstain.

## Tie-in with other rails

- **Model routing** (`recommended_model.cost`): the cost dimension at the model
  level (which model to use). Composes with budget-aware selection (which skill
  to load): the cheap model + cheap skill cell is the production-default cascade.
- **Permissions / guards**: enforce expensive or dangerous tool calls at runtime
  (the non-token cost dimension). Complementary to the token meter; together
  they bound both dimensions.


## External pricing table

Pricing changes; rates should live outside an AgentMakefile module.
Pass `--pricing-table FILE` (or `pricing_table=` to `create_link_plan` /
`create_plugin_payload` / `create_ask_payload` / `create_exec_payload`)
to fill in missing `models[*].pricing` from a small YAML/JSON file.
Resolution: inline > external table > none. See
`config/pricing.example.yaml` for the format.

## Limitations & roadmap

- Token-only. Wall-clock / tool-call / external-spend caps are future work and
  are layered, not folded, into the budget concept (a single cap leaks because
  the dimensions are independent).
- `estimate_tokens` is a deterministic `chars/4` proxy. Swap in a real
  tokenizer per provider for tighter ceilings; the meter logic is the same.
- Selection currently drops by hard threshold (`cost > budget`). A future
  refinement: rank by `(priority, match-score, -cost)` so that within budget,
  ties prefer cheaper skills.
- A *cascade* arm (cheap default → escalate on low confidence) is described in
  the skill-corpus proposal and is the natural next layer atop these primitives.

See [`demos/budget-aware`](../demos/budget-aware/) for a runnable example.
