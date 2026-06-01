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


## Adopting LiteLLM best practices (light)

`TokenBudget` borrows two practices from LiteLLM's mature proxy budget code
(`litellm/proxy/spend_tracking/budget_reservation.py`):

1. **Anti-DoS output clamp.** When `model_max_output_tokens` is set, the
   per-call ceiling uses `min(caller_max_output, model_ceiling)`. This prevents
   a caller from inflating the worst case (and pinning the budget) by
   requesting `max_output_tokens=999_999_999` for a model that can only emit
   a few thousand tokens anyway.
2. **LiteLLM as optional pricing source.** When `model` is set and `litellm`
   is installed but no explicit `pricing` was given, the USD methods defer to
   `litellm.cost_per_token` — leveraging the maintained, multi-provider price
   table without reimplementing it. Resolution: explicit `pricing` > LiteLLM
   > none. `litellm` stays an *optional* dependency; without it, behavior is
   unchanged.

What we deliberately did NOT adopt: the proxy reservation/reconcile model
(atomic concurrent admission). It's the right design for a multi-tenant proxy;
AgentMakefile's in-process meter doesn't have concurrent admission and is
better served by the simpler `check_or_halt → charge` cycle.


## Cost metadata in generated SKILL.md (option (b), reachable today)

Compiled `SKILL.md` files now embed the skill's loading cost in YAML
frontmatter under `metadata.cost.tokens`:

```yaml
---
name: karpathy-guidelines
description: Apply Karpathy-style coding guidelines...
metadata:
  cost:
    tokens: 366
---
```

Position chosen to be **non-conflicting**: the
[agentskills.io spec](https://agentskills.io/specification) treats
frontmatter `metadata` as an open namespace for arbitrary keys (author,
version, etc.) — `metadata.cost.tokens` is a clean extension, not a new
top-level field.

**What this enables today**: any SKILL.md reader (custom agent loop,
future host that adds budget-awareness) can see the loading cost without
loading the body. Current production hosts (Claude Code / Codex CLI /
Cursor) are OTel *emitters*, not *readers* — they will not consume this
field automatically. The field is a forward-compatible breadcrumb, not a
live integration.

**Why not `gen_ai.budget.*` (OpenTelemetry namespace)**: OpenTelemetry
GenAI semantic conventions are post-call telemetry emitted *by* the host
to a backend, not metadata read *by* the host from an upstream module.
There is no current inbound contract for budget metadata in any agent
host; the right inbound channels are SKILL.md frontmatter (this) and a
future MCP metadata extension (tracked, see project memory).


## Three independent cost-control dimensions (A/B/C)

Cost control has THREE orthogonal axes that are commonly conflated:

| | What it bounds | TokenBudget field | Refusal effect |
| --- | --- | --- | --- |
| A | Long-term cumulative quota (per key / month / team) | *external* (gateway-layer; LiteLLM/sub2api/new-api) | depends |
| B | Total-budget worst-case check (cumulative + this call's ceiling) | `total` + per-call ceiling vs `remaining` | **session halts** (`halted=True`) |
| **C** | Per-call ABSOLUTE cap (independent of total) | `max_per_call_tokens`, `max_per_call_usd` | **refuse THIS call only; session continues** |

**Why C is its own dimension**: A and B both protect against *running out*
of budget. C protects against an *individual* call being unreasonably
expensive even when the budget is fine — defense against accidental
oversized prompts (1 MB file pasted in), mis-set `max_tokens=999_999`,
or sanity-bounded session policies ("no single call may cost >$0.50").
LiteLLM does not provide a built-in C cap; they expose `async_pre_call_hook`
as a generic extension point. We make it a first-class field.

**exec status codes**: `executed` (ran), `halted_over_budget` (B fired, session halted, all subsequent calls also refused), `oversized_call` (C fired, only this call refused, session continues).


## Dynamic adjustment of per-call caps (C only)

C-dimension caps can be tightened or relaxed mid-session via
`TokenBudget.adjust_per_call_cap(tokens=..., usd=..., reason=...)`.
Use cases:

- start conservatively (small cap), relax temporarily for a known-large
  call (user approved a big doc; aggregation step needs more headroom);
- tighten an over-permissive cap after an unsafe trend;
- lift a cap explicitly with `tokens=None` (axis disabled).

Every adjustment is appended to `per_call_cap_adjustments` (audit
trail) with `at_turn` and an optional `reason`. **Only C is dynamic.**
B (total budget) is fixed for the meter's lifetime: raising the total
mid-run would authorize more spend and should require an explicit
policy decision (rebuild the meter, not flip a flag). Invalid values
(<=0) raise `ValueError` to avoid silent footguns.

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
