# AgentMakefile

Prototype implementation for the AgentMakefile design spec.

AgentMakefile is a Makefile-style build system for agent prompt prefixes. It treats reusable rules, skills, policies, dependencies, permissions, and output contracts as structured inputs, then compiles them into stable prompt-prefix artifacts for each agent platform. Generated files such as `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/*.mdc`, and future `SKILL.md` outputs are build artifacts, not the source of truth.

Static files are the compatibility path for existing agents. The deeper integration path is runtime prompt-prefix assembly: an agent runtime consumes AgentMakefile IR directly, selects the relevant target and dependency graph for the current request, reuses stable prefix chunks, and appends volatile task context only at the end.

The near-term runtime direction is plugin-first: existing agent CLIs keep owning model calls and tool loops, while AgentMakefile provides `agentmf plugin payload`-style prompt assembly for each user request and optional implementation plan. A standalone `agentmf prompt` / `agentmf ask` / `agentmf exec` runtime can build on the same payload path later.

Design details live in [docs/agentsfile_design_spec.md](docs/agentsfile_design_spec.md).
The proposed runtime CLI design lives in [docs/agentmf_runtime_cli_spec.md](docs/agentmf_runtime_cli_spec.md).
The plugin-first adapter design lives in [docs/agentmf_plugin_adapter_spec.md](docs/agentmf_plugin_adapter_spec.md).
Example host adapter flows live in [docs/agentmf_plugin_adapter_examples.md](docs/agentmf_plugin_adapter_examples.md).
The staged implementation backlog lives in [docs/spec_breakdown.md](docs/spec_breakdown.md).
This repository is self-hosted by the root [AgentMakefile](AgentMakefile), which compiles project development guidance into `AGENTS.md`, `CLAUDE.md`, and Cursor rules.

Reusable rule modules live under [modules/](modules/). For example, the Karpathy / Andrej guidelines are represented as [modules/karpathy/AgentMakefile](modules/karpathy/AgentMakefile), unknown repository security rails are represented as [modules/unknown-repo-security/AgentMakefile](modules/unknown-repo-security/AgentMakefile), Superpowers is represented as [modules/superpowers/AgentMakefile](modules/superpowers/AgentMakefile), and Oh My OpenAgent is represented as [modules/oh-my-openagent/AgentMakefile](modules/oh-my-openagent/AgentMakefile). Demo files under [demos/](demos/) compose these modules and choose output backends.

The [unknown repository security demo](demos/unknown-repo-security/AgentMakefile) proves the hard-rails path end to end by compiling soft Markdown guidance, Cursor rules, Claude Code settings and hooks, and OpenCode configuration from one AgentMakefile.

This structure is intended to support target selection, dependency-aware rebuilds, and cache-friendly prompt layout: stable compiled guidance can stay byte-for-byte deterministic, while volatile task context such as the current user request, active files, and diffs can be appended later by the runtime.

MVP 0 supports deterministic compilation from a YAML `AgentMakefile` into:

- `CLAUDE.md`
- `AGENTS.md`
- `.cursor/rules/agentmakefile-generated.mdc`

MVP 2.5 has started the bridge toward runtime-native prompt assembly with target fragment backends:

- `agents-fragments` emits one target-specific Markdown prompt object per normalized target under `.agentmf/fragments/agents/`.
- `claude-fragments` emits the same target-specific prompt objects for Claude-oriented prompt prefixes under `.agentmf/fragments/claude/`.
- `.agentmf/fragments/manifest.json` records each fragment's backend, target, dependency closure, source inputs, compiler version, and content hash. Re-running `--write` skips unchanged fragment outputs.
- `agentmf select` emits a stable JSON link plan that selects fragment paths either from an explicit target or from a request matched against target `match` rules.
- `agentmf run --dry-run` emits the first runtime-facing plan: selected targets, dependency closure, linked prompt prefix, fragment paths, size/token comparison against the all-in-one baseline, dry-run guard evaluation records, steps, permissions, output contracts, and fallback metadata without executing the workflow.
- `agentmf run --dry-run --permission-check TOOL:INPUT` evaluates proposed tool calls against AgentMakefile permission rules without executing them.
- `agentmf prompt` emits a deterministic final prompt payload by combining the selected stable prefix with volatile request, plan, context-file, and git context, without calling a model or running tools.
- `agentmf ask` reuses the same prompt payload path and runs a one-shot provider call; the first provider is the deterministic local `echo` adapter.
- `agentmf exec --apply --tool-call TOOL:INPUT` is the first gated tool-loop prototype: it evaluates guards and permissions, then runs only explicitly allowed tool calls.
- `claude-code` emits native Claude Code settings and hook artifacts under `.claude/` where feasible.
- `opencode` emits `opencode.json` with permission configuration and target-derived agent definitions.

The CLI defaults to dry-run mode:

```bash
agentmf validate --file AgentMakefile
agentmf compile --file AgentMakefile --target claude-md --target agents-md --target cursor-rule
agentmf compile --file AgentMakefile --target agents-fragments
agentmf compile --file AgentMakefile --target claude-code
agentmf compile --file AgentMakefile --target opencode
agentmf select --file AgentMakefile --request "review code" --backend agents-fragments
agentmf run --file AgentMakefile --request "review code" --dry-run --format json
agentmf run --file AgentMakefile --target project.default --dry-run --permission-check "bash:git status" --format json
agentmf prompt --file AgentMakefile --request "review code" --plan docs/superpowers/plans/2026-05-25-agentmf-plugin-adapter.md --include-git-status --format json
agentmf ask --file AgentMakefile --request "review code" --provider echo --format json
agentmf exec --file modules/unknown-repo-security/AgentMakefile --target repo.security_review --tool-call "bash:git status" --apply --format json
agentmf plugin payload --host codex --request "review code" --format json
agentmf plugin payload --host codex --target project.default --plan docs/superpowers/plans/2026-05-25-agentmf-plugin-adapter.md --include-git-status --format json
agentmf compile --file AgentMakefile --write
```

## Quickstart

From a fresh checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
agentmf validate --file AgentMakefile
agentmf compile --file AgentMakefile --target claude-md --target agents-md --target cursor-rule
```

For development and tests:

```bash
python -m pip install -e ".[test]"
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall -q src
```

The staged roadmap and acceptance criteria are tracked in [docs/spec_breakdown.md](docs/spec_breakdown.md).

## Demo Compile

The Karpathy / Andrej demo is the smallest useful end-to-end compile path:

```bash
agentmf validate --file demos/karpathy/AgentMakefile
agentmf compile --file demos/karpathy/AgentMakefile
```

The default compile target list emits `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/karpathy-guidelines.mdc`, `.claude/skills/karpathy-guidelines/SKILL.md`, and `.codex/skills/karpathy-guidelines/SKILL.md`. The `claude-skill` and `codex-skill` outputs are soft prompt-package artifacts; hard runtime enforcement remains backend-specific.
