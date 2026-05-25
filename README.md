# AgentMakefile

Prototype implementation for the AgentMakefile design spec.

Design details live in [docs/agentsfile_design_spec.md](docs/agentsfile_design_spec.md).

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
