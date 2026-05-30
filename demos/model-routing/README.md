# Model routing demo

Advisory per-request **model** routing, alongside skill/target routing. A
`models:` block makes a model a first-class routable resource: it is matched the
same way targets and skills are, and the selector emits a `recommended_model`.
The host still owns the actual model call — this is advisory, not enforcement.

## Try it

```bash
agentmf validate --file demos/model-routing/AgentMakefile

# recommended_model rides along with the link plan
agentmf select --file demos/model-routing/AgentMakefile \
  --request "debug a hard problem in the parser" --format json

# and in the host plugin payload
agentmf plugin payload --host codex --file demos/model-routing/AgentMakefile \
  --request "implement a feature in the api" --format json
```

## What you'll see

| Request | selected target | recommended_model | why |
| --- | --- | --- | --- |
| implement a feature in the api | `code.task` | `sonnet-balanced` (medium) | coding work |
| debug a hard problem in the parser | `code.task` | `opus-deep` (high) | hard reasoning |
| quick lookup of a value | `research.task` | `haiku-fast` (low) | cheap/fast |
| analyze a screenshot of the ui | `research.task` | `gemini-vision` (medium) | vision capability |

Note the **same target** (`code.task`) pairs with **different models** depending
on difficulty (`sonnet` to implement, `opus` to debug). Model routing is an
orthogonal axis, not a property of the target.

## Two axes, decoupled

- **Target/skill routing**: request → which skill/workflow to load.
- **Model routing**: request → which model should run it.

They share the same deterministic matcher but are independent. Model routing even
survives a target no-match (the recommendation is still emitted), and is callable
on its own:

```python
from agentmf import recommend_model
recommend_model("demos/model-routing/AgentMakefile", request="quick lookup").recommendation
# {'model': 'haiku-fast', 'cost': 'low', 'reason': 'matched', ...}
```

## The cost lever

This is the runtime half of the build-vs-runtime cost split: route easy/cheap
intents to a low-cost model by default (`default: true`), and escalate hard
intents to a high-cost model via their `match` terms. The big model is reserved
for the fraction that needs it.

See [docs/agentmf_model_routing_spec.md](../../docs/agentmf_model_routing_spec.md).
