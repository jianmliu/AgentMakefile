# Demos

Runnable AgentMakefile examples.

## Karpathy / Andrej Case

The full case includes MVP 1 skill backends in `compile.targets`, so MVP 0 should be run with explicit supported targets:

```bash
agentmf validate --file demos/karpathy/AgentMakefile
agentmf compile --file demos/karpathy/AgentMakefile --target claude-md --target agents-md --target cursor-rule
```
