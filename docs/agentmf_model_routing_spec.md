# AgentMakefile Model Routing

Status: prototype (advisory). Date: 2026-05-29.

## Summary

Model routing makes "which model should handle this request" a first-class,
declarative, routable concern — the same way AgentMakefile already routes a
request to a skill/target. A `models:` block declares the available models with
`match` terms, capabilities, cost, and priority; the selector emits a
`recommended_model` for each request.

This is a **separate axis** from target/skill routing and from the compile
pipeline. It is **advisory**: AgentMakefile recommends a model; the host still
owns the actual model call (the Option A boundary in
[agentmf_agent_harness_architecture.md](agentmf_agent_harness_architecture.md)).

## Why it belongs here

Model selection is the runtime half of the project's core cost split:

- **Build time** (amortized, once): use a big model to label, tune, and audit —
  baked into cheap artifacts (embeddings, match terms, cached verdicts).
- **Run time** (per request, hot path): use a cheap/fast model by default, and
  **escalate to a high-cost model only when warranted**.

Model routing is that escalation lever expressed declaratively: a `default: true`
cheap model handles the bulk; hard intents carry `match` terms that route them to
a high-cost model. The same deterministic matcher that picks skills picks models,
so the routing is explainable and free at request time.

## Schema

```yaml
models:
  haiku-fast:
    family: claude          # model family / vendor (free-form label)
    cost: low               # cost tier (free-form: low | medium | high | ...)
    capabilities: [fast, retrieval]   # hard requirements a host can filter on
    default: true           # fallback when no model's match terms hit
    priority: 50            # 0..100, tie-break like targets
    match:                  # same shape as target/skill match
      user_intent:
        - quick lookup
        - summarize
  opus-deep:
    family: claude
    cost: high
    capabilities: [deep-reasoning, tool-use]
    priority: 70
    match:
      user_intent:
        - debug a hard problem
        - design a complex system
```

All fields are optional except an implicit name (the map key). A module with no
`models:` block is unaffected — `recommended_model` is then `null`.

## Selection semantics

1. Build the request profile (same normalization/translation/semantic-token
   pipeline as target routing).
2. For each model, match the request against its `match` terms.
3. Rank matched models by `(source_rank, -priority, -score)` and pick the top.
   Reason = `matched`.
4. If no model matches, fall back to the `default: true` model (or, if none is
   marked default, the highest-priority model). Reason = `default`.

Output shape:

```json
{
  "model": "opus-deep",
  "family": "claude",
  "cost": "high",
  "capabilities": ["deep-reasoning", "tool-use"],
  "priority": 70,
  "reason": "matched",
  "matched_terms": ["debug a hard problem"],
  "match_score": 100
}
```

## Orthogonality

Model routing does **not** depend on target routing succeeding:

- `agentmf select` / `plugin payload` include `recommended_model` even when no
  target matches (target routing reports its own `AMF118`; the model
  recommendation is still emitted).
- A standalone entry point computes it with zero target involvement:

```python
from agentmf import recommend_model
recommend_model("AgentMakefile", request="quick lookup").recommendation
```

The same target can therefore pair with different models across requests (e.g. a
`code.task` routed to `sonnet` to implement but `opus` to debug).

## Surfaces

- `agentmf select … --format json` → `link_plan.recommended_model`
- `agentmf plugin payload … --format json` → `plugin_payload.recommended_model`
- `from agentmf import recommend_model` → `ModelRoutingResult.recommendation`

## Scope and follow-ups

- **v1 uses the deterministic keyword matcher.** The model set is small and
  benefits from explainability; embedding/hybrid model routing can come later.
- **Capability rules** (`vision`, `long-context`) are deterministic and reliable
  and should be preferred; **work-style** heuristics (claude-like vs gpt-like)
  are fuzzier and should stay advisory and benchmark-calibrated.
- Not yet: hard `require:`/`deny:` model constraints, confidence-thresholded
  escalation wired to the cosine score, and `compile`-time emission of model
  guidance into host configs. These are natural next steps.

See the runnable [demos/model-routing](../demos/model-routing/) module.
