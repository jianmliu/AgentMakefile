# Demos

Runnable AgentMakefile examples.

## Karpathy / Andrej Case

The Karpathy rules are a reusable module at `modules/karpathy/AgentMakefile`.
The demo file at `demos/karpathy/AgentMakefile` includes that module and only declares demo-level backend outputs.

The full case includes MVP 1 skill backends in `compile.targets`, so MVP 0 should be run with explicit supported targets:

```bash
agentmf validate --file demos/karpathy/AgentMakefile
agentmf compile --file demos/karpathy/AgentMakefile --target claude-md --target agents-md --target cursor-rule
```

## Superpowers Methodology

The Superpowers rules are a reusable module at `modules/superpowers/AgentMakefile`.

```bash
agentmf validate --file demos/superpowers/AgentMakefile
agentmf compile --file demos/superpowers/AgentMakefile
```

## Oh My OpenAgent Orchestration

The Oh My OpenAgent rules are a reusable module at `modules/oh-my-openagent/AgentMakefile`.

```bash
agentmf validate --file demos/oh-my-openagent/AgentMakefile
agentmf compile --file demos/oh-my-openagent/AgentMakefile
```

## Local Composition

The local composition demo combines `modules/karpathy/AgentMakefile` with `modules/unknown-repo-security/AgentMakefile` using namespaced includes.

```bash
agentmf validate --file demos/local-composition/AgentMakefile
agentmf compile --file demos/local-composition/AgentMakefile
```

## Unknown Repository Hard Rails

The unknown repository security demo composes `modules/unknown-repo-security/AgentMakefile` and adds native hard rails for risky install commands.

```bash
agentmf validate --file demos/unknown-repo-security/AgentMakefile
agentmf compile --file demos/unknown-repo-security/AgentMakefile
```
