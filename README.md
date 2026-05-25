# AgentMakefile

Prototype implementation for the AgentMakefile design spec.

Design details live in [docs/agentsfile_design_spec.md](docs/agentsfile_design_spec.md).
The staged implementation backlog lives in [docs/spec_breakdown.md](docs/spec_breakdown.md).
This repository is self-hosted by the root [AgentMakefile](AgentMakefile), which compiles project development guidance into `AGENTS.md`, `CLAUDE.md`, and Cursor rules.

Reusable rule modules live under [modules/](modules/). For example, the Karpathy / Andrej guidelines are represented as [modules/karpathy/AgentMakefile](modules/karpathy/AgentMakefile), Superpowers is represented as [modules/superpowers/AgentMakefile](modules/superpowers/AgentMakefile), and Oh My OpenAgent is represented as [modules/oh-my-openagent/AgentMakefile](modules/oh-my-openagent/AgentMakefile). Demo files under [demos/](demos/) compose these modules and choose output backends.

MVP 0 supports deterministic compilation from a YAML `AgentMakefile` into:

- `CLAUDE.md`
- `AGENTS.md`
- `.cursor/rules/agentmakefile-generated.mdc`

The CLI defaults to dry-run mode:

```bash
agentmf validate --file AgentMakefile
agentmf compile --file AgentMakefile --target claude-md --target agents-md --target cursor-rule
agentmf compile --file AgentMakefile --write
```
