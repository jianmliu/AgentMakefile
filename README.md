# AgentMakefile

> A declarative compiler for agent harnesses, plus an evidence-driven
> dream loop that proposes patches to the makefile from real session
> traces. Think of it as the **autoconf / configure / make / make
> install** pattern applied to AI agent guidance: the `AgentMakefile`
> stays the human-readable single source of truth, and tooling around
> it follows the familiar four-step lineage.
>
> | GNU Autotools | AgentMakefile |
> | --- | --- |
> | `autoconf` (regenerate the makefile from observed project facts) | **Dream loop** — `agentmf evo dream run` proposes patches to the AgentMakefile from accumulated session traces. |
> | `./configure` (decide which platform formats / features compile in) | **Backend selection** — the AgentMakefile's `compile.targets` list (and `agentmf compile --target …`) picks which skill formats to emit: `claude-skill`, `codex-skill`, `cursor-rule`, `agents-md`, `claude-md`, `opencode`, target fragments, etc. |
> | `make` (build artefacts from the configured set) | **`agentmf compile`** — actually emits the selected skill packages and host configs (`AGENTS.md`, `CLAUDE.md`, `.cursor/rules/`, `.codex/skills/…`, `.claude/skills/…`, `opencode.json`, fragments). |
> | `make install` (copy artefacts into the host's install locations) | **`agentmf skills sync`** — install generated skills into `~/.codex/skills/`, `~/.claude/skills/`, and other platform-specific roots with a dry-run-first workflow. |
>
> One declarative source, many host-native install targets, and a
> review-gated feedback loop that improves the source over time.
>
> Runtime per-request routing (`agentmf select` / `agentmf prompt` /
> the OpenCode plugin's `chat.message` hook) is a **separate axis**
> from this build pipeline — it's closer to feature detection at
> *runtime* than to `configure` at build time. The same compiled
> install set still gets filtered down to the smallest useful target
> closure on every chat turn.
>
> **Routing matcher (MVP path):** `agentmf select`/`prompt` default to
> `--matcher embedding` — semantic SkillIndex cosine via
> [sentence-transformers](https://www.sbert.net/) when installed via
> `pip install agentmf[embedding]`, with a deterministic HashEmbedder
> fallback. On the openclaw-skills benchmark (8 cases) embedding
> routes 7/8 correctly vs 1/8 for the substring-keyword baseline.
> `--matcher keyword` keeps the historical deterministic substring
> path for modules where you want `matched_terms` explainability or
> can't take an ML dependency. `--matcher hybrid` blends both signals
> (α=0.85 cosine + 0.15 keyword) and ties pure embedding on the
> bench; it's available for experimentation but not the default.

AgentMakefile is a build system and routing layer for agent harnesses. It
turns scattered `SKILL.md`, `AGENTS.md`, `CLAUDE.md`, framework rules, policies,
permissions, and workflow targets into a structured, dependency-aware harness
graph that can be compiled, synced, selected, explained, and handed to existing
coding-agent hosts.

The goal is not to replace Codex, Claude Code, Cursor, OpenCode, Superpowers,
Oh My OpenAgent, or project-specific Markdown guidance. The goal is to organize
those harnesses systematically: import their guidance, normalize it into typed
targets and pipelines, compile it back to host-native artifacts, and select the
smallest useful harness for each request.

The core value is harness infrastructure:

- **Structured harness graph**: represent reusable skills, rules, policies, permissions, dependencies, output contracts, fallback behavior, and pipeline steps as typed AgentMakefile source instead of hand-maintaining scattered Markdown files.
- **Harness consolidation**: scan installed skills, project `AGENTS.md`, `CLAUDE.md`, standalone `SKILL.md`, and framework-specific rules into a common routing module.
- **Large skill ecosystem import**: turn local OpenClaw-style `**/SKILL.md` trees into category-split AgentMakefile modules, a root index, and curator evidence instead of one flat prompt index.
- **Cross-platform skill compilation**: compile the same module into Codex skills, Claude Code skills, `skills/index.md`, `AGENTS.md`, `CLAUDE.md`, Cursor rules, OpenCode config, and Claude Code settings/hooks where supported.
- **System skill sync**: sync generated Codex or Claude Code skill packages into a host skill root with a dry-run-first `agentmf skills sync` workflow.
- **Request-time routing optimization**: use `agentmf plugin payload` to choose only the relevant targets, skills, prompt fragments, guards, permissions, and output contracts for the current request.
- **Pipeline-aware harness compilation**: normalize each target into ordered operations such as `use_skill`, `select_context`, `link_prompt`, `check_guard`, `check_permission`, `validate_output`, and `fallback`, while preserving legacy `action` steps.
- **Harness payload assembly**: return stable prompt prefixes, volatile context, guard/permission metadata, output contracts, and host-specific instructions without taking over the host's model or tool runtime.
- **Explainable selection**: every request-time choice can return `selected_targets`, `selected_skills`, `selected_pipeline`, dependency closure, native skill artifact paths, and `selection_trace` rationale.
- **Measurable advantage**: benchmark structured harness selection against all-in-one `AGENTS.md`, `CLAUDE.md`, generated `skills/index.md`, explicit baseline files, or all installed `SKILL.md` files.

Generated files such as `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/*.mdc`, `skills/index.md`, `.codex/skills/*/SKILL.md`, and `.claude/skills/*/SKILL.md` are build artifacts. AgentMakefile modules are the source of truth.

AgentMakefile now supports two complementary directions:

- **AgentMakefile modules -> native skills**: write or maintain an AgentMakefile module, compile it into platform-native skills, and optionally sync those skills into Codex or Claude Code.
- **Existing native guidance -> AgentMakefile routing graph**: scan installed `SKILL.md` packages, project `AGENTS.md` / `CLAUDE.md`, or other guidance files into a generated AgentMakefile module, then optimize request-time skill and instruction selection with `agentmf plugin payload`.

Static files are the compatibility path for existing agents. The deeper integration path is harness-driven prompt-prefix assembly: an agent runtime or host adapter consumes AgentMakefile IR, selects the relevant target and dependency graph for the current request, reuses stable prefix chunks, and appends volatile task context only at the end.

The near-term direction is plugin-first: existing agent CLIs keep owning model calls, streaming, tool loops, approvals, and UI, while AgentMakefile provides `agentmf plugin payload`-style harness assembly for each user request and optional implementation plan. A standalone `agentmf prompt` / `agentmf ask` / `agentmf exec` runtime is a later optional path built on the same harness interfaces.

Design details live in [docs/agentsfile_design_spec.md](docs/agentsfile_design_spec.md).
The agent harness architecture lives in [docs/agentmf_agent_harness_architecture.md](docs/agentmf_agent_harness_architecture.md).
The proposed runtime CLI design lives in [docs/agentmf_runtime_cli_spec.md](docs/agentmf_runtime_cli_spec.md).
The guidance ingestion design lives in [docs/agentmf_guidance_ingestion_spec.md](docs/agentmf_guidance_ingestion_spec.md).
The OpenClaw importer design lives in [docs/agentmf_openclaw_importer_spec.md](docs/agentmf_openclaw_importer_spec.md).
The benchmark CLI design lives in [docs/agentmf_benchmark_cli_spec.md](docs/agentmf_benchmark_cli_spec.md).
The harness benchmark suite design lives in [docs/agentmf_harness_benchmark_suite_spec.md](docs/agentmf_harness_benchmark_suite_spec.md).
The plugin-first adapter design lives in [docs/agentmf_plugin_adapter_spec.md](docs/agentmf_plugin_adapter_spec.md).
Example host adapter flows live in [docs/agentmf_plugin_adapter_examples.md](docs/agentmf_plugin_adapter_examples.md).
The advisory model-routing design lives in [docs/agentmf_model_routing_spec.md](docs/agentmf_model_routing_spec.md), with a runnable [demos/model-routing](demos/model-routing/) module.
The current runtime walkthrough lives in [docs/agentmf_step_by_step_demo.md](docs/agentmf_step_by_step_demo.md).
The staged implementation backlog lives in [docs/spec_breakdown.md](docs/spec_breakdown.md).
This repository is self-hosted by the root [AgentMakefile](AgentMakefile), which compiles project development guidance into `AGENTS.md`, `CLAUDE.md`, and Cursor rules.

Reusable rule modules live under [modules/](modules/). For example, the Karpathy / Andrej guidelines are represented as [modules/karpathy/AgentMakefile](modules/karpathy/AgentMakefile), unknown repository security rails are represented as [modules/unknown-repo-security/AgentMakefile](modules/unknown-repo-security/AgentMakefile), Superpowers is represented as [modules/superpowers/AgentMakefile](modules/superpowers/AgentMakefile), and Oh My OpenAgent is represented as [modules/oh-my-openagent/AgentMakefile](modules/oh-my-openagent/AgentMakefile). Demo files under [demos/](demos/) compose these modules and choose output backends.

The [unknown repository security demo](demos/unknown-repo-security/AgentMakefile) proves the hard-rails path end to end by compiling soft Markdown guidance, Cursor rules, Claude Code settings and hooks, and OpenCode configuration from one AgentMakefile. The [runtime walkthrough demo](demos/runtime-walkthrough/AgentMakefile) exercises prompt fragments, a generated `skills/index.md` catalog, Claude/Codex skill-package outputs, runtime dry-run planning, JSON Schema output validation, plugin payloads, provider echo, tool interception, sandbox preflight, and fallback handling. The same runtime path can also start from imported guidance: today's `agentmf skills scan` turns existing `SKILL.md` packages into an AgentMakefile routing graph, and the planned guidance importer extends that bridge to `AGENTS.md`, `CLAUDE.md`, single `SKILL.md` files, and other host-native instruction files.

This structure is intended to support target selection, dependency-aware rebuilds, and cache-friendly prompt layout: stable compiled guidance can stay byte-for-byte deterministic, while volatile task context such as the current user request, active files, and diffs can be appended later by the runtime.

In AgentMakefile, a target is a **compilable agent harness pipeline**, not a
shell recipe. A target can combine dependencies, skills, policies, prompt
fragments, context rules, guards, permissions, fallback behavior, and output
contracts, then lower that pipeline into native Markdown guidance, skill
packages, prompt fragments, plugin payloads, or future runtime plans.

MVP 0 supports deterministic compilation from a YAML `AgentMakefile` into:

- `CLAUDE.md`
- `AGENTS.md`
- `.cursor/rules/agentmakefile-generated.mdc`

MVP 2.5 has started the bridge toward runtime-native prompt assembly with target fragment backends:

- `agents-fragments` emits one target-specific Markdown prompt object per normalized target under `.agentmf/fragments/agents/`.
- `claude-fragments` emits the same target-specific prompt objects for Claude-oriented prompt prefixes under `.agentmf/fragments/claude/`.
- `.agentmf/fragments/manifest.json` records each fragment's backend, target, dependency closure, source inputs, compiler version, and content hash. Re-running `--write` skips unchanged fragment outputs.
- `agentmf select` emits a stable JSON link plan that selects fragment paths either from an explicit target or from a request matched against target `match` rules, and includes `target_pipelines` plus `pipeline_trace` operation counts for explainability.
- `agentmf run --dry-run` emits the first runtime-facing plan: selected targets, dependency closure, linked prompt prefix, fragment paths, size/token comparison against the all-in-one baseline, dry-run guard evaluation records, typed pipeline operations, permissions, output contracts, fallback metadata, and `pipeline_execution_plan` without executing the workflow.
- `agentmf run --dry-run --permission-check TOOL:INPUT` evaluates proposed tool calls against AgentMakefile permission rules without executing them.
- `agentmf run --dry-run --output-json JSON` validates proposed output objects against selected target output contracts with JSON Schema support, without executing the workflow.
- `agentmf prompt` emits a deterministic final prompt payload by combining the selected stable prefix with volatile request, plan, context-file, and git context, without calling a model or running tools.
- `agentmf ask` reuses the same prompt payload path and runs a one-shot provider call; the first provider is the deterministic local `echo` adapter.
- `agentmf exec --apply --tool-call TOOL:INPUT` is the first gated tool-loop prototype: it evaluates guards and permissions, applies prototype sandbox preflight checks, records the provider tool-call interception contract, runs only explicitly allowed tool calls, and plans or optionally executes internal fallback actions for blocked calls.
- `agentmf plugin install` scans existing skills, writes a plugin-local AgentMakefile when requested, and emits model instructions telling hosts to call `agentmf plugin payload` before loading skills. The planned generalized importer will let the same install path read `AGENTS.md`, `CLAUDE.md`, standalone `SKILL.md`, and related guidance sources.
- `agentmf plugin payload` exposes `selected_skills`, `selected_pipeline`, flat operation groups (`stable_prompt_ops`, `volatile_context_ops`, `guard_ops`, `permission_ops`, `fallback_ops`), generated Codex/Claude skill artifact paths, and `selection_trace` rationale so host adapters can use AgentMakefile as an explainable harness-routing layer. Request routing can match either explicit target `match` terms or the `match` terms of skills referenced by a target.
- `agentmf skills scan` imports existing `SKILL.md` directories into a generated AgentMakefile skill-index module, with an optional bootstrap skill represented as an explicit target dependency. Scanned skill targets now emit pipeline steps that `use_skill` and `link_prompt` to the source `SKILL.md`.
- `agentmf openclaw scan` imports local OpenClaw-style recursive skill trees into category-split AgentMakefile modules, writes a root index when requested, and returns curator evidence for duplicate original names, category counts, and generated module paths.
- `agentmf evo evidence add` appends redacted, hash-addressed evidence records under `.agentmf/evolution/evidence/`; the first concrete source is `openclaw_import`, which turns importer curator evidence into input for later Skill Workshop proposals.
- `agentmf evo proposal create` turns evidence JSONL records into reviewable Skill Workshop candidate files: one machine-readable `.proposal.json` and one Markdown report. It does not generate or apply patches.
- `agentmf evo patch generate` creates reviewable unified diffs from supported proposal changes. The first patch class is `update_match_terms`.
- `agentmf evo evaluate` writes candidate AgentMakefile sources into an isolated workspace and validates them without mutating canonical sources.
- `agentmf evo dream run` consumes stored evidence and emits candidate proposals; the first detector handles OpenClaw duplicate skill evidence.
- `agentmf evo openclaw curate` turns OpenClaw `duplicate_original_names` evidence into a `merge_duplicate_targets` Skill Workshop proposal.
- `agentmf skills sync` compiles an AgentMakefile module into host-native Codex or Claude Code skill packages and syncs them to a host skill root only when `--write` is set.
- `agentmf benchmark harness` reports selected targets, selected skills, selected pipeline size, stable prefix hashes, guard/permission coverage, selection-trace quality, and baseline comparisons against `agents-md`, `claude-md`, `skills-index`, explicit files, or all scanned `SKILL.md` files without calling a model.
- `agentmf clawbench export` emits a ClawBench-compatible harness trace bundle for one task instruction: selected AgentMakefile targets, skills, pipeline operations, stable prefix content/hash, volatile context, guard/permission/fallback ops, output contracts, and downstream execution metadata with execution disabled.
- `agentmf clawbench export-jsonl` converts a JSONL task file into one harness trace bundle per line so an external ClawBench-style runner can consume AgentMakefile-selected harnesses task by task.
- `agentmf clawbench adapter-contract` emits the JSONL input/output contract expected by a host adapter that will execute exported ClawBench harness bundles.
- `agentmf clawbench import-results` reads external runner result JSONL and summarizes pass rate, cost, latency, tokens, tool-call counts, denied tool calls, and stable prefix hash reuse.
- `agentmf swebench export-jsonl` converts a local SWE-bench Lite-style JSONL subset into one AgentMakefile-selected coding harness bundle per instance, with `--limit` for small smoke subsets.
- `agentmf swebench compare` renders a deterministic SWE-bench Lite harness comparison report across selected AgentMakefile pipelines and compiled baselines such as `AGENTS.md`, `CLAUDE.md`, and `skills/index.md`.
- `agentmf swebench adapter-contract` defines the JSONL boundary for external SWE-bench execution adapters, while `agentmf swebench import-results` and `agentmf swebench pass-report` summarize resolved/pass-rate metrics after an external runner executes tasks.
- `agentmf swebench predictions` converts external execution results into official SWE-bench predictions JSONL with `instance_id`, `model_name_or_path`, and `model_patch`.
- `agentmf swebench official-command` emits the official `swebench.harness.run_evaluation` command for Lite or Verified profiles without executing it, and `agentmf swebench import-official-report` imports the official schema-v2 report JSON after the runner finishes.
- `agentmf swebench official-dry-run` validates an official predictions JSONL file and emits an adapter plan with smoke-subset and full-profile command previews, keeping execution disabled so Lite/Verified runs are explicit external steps.
- Request selection normalizes punctuation and hyphenation, expands common Chinese/English development intents, and falls back to deterministic token-overlap matching before returning `AMF118`.
- `skills-index` emits a generated `skills/index.md` compatibility catalog for all normalized skill entries, with links to the Claude and Codex skill package paths.
- `claude-code` emits native Claude Code settings and hook artifacts under `.claude/` where feasible.
- `opencode` emits `opencode.json` with permission configuration and target-derived agent definitions.

The CLI defaults to dry-run mode:

```bash
agentmf validate --file AgentMakefile
agentmf compile --file AgentMakefile --target claude-md --target agents-md --target cursor-rule
agentmf compile --file AgentMakefile --target agents-fragments
agentmf compile --file AgentMakefile --target claude-code
agentmf compile --file AgentMakefile --target opencode
agentmf compile --file AgentMakefile --target claude-skill --target codex-skill --target skills-index
agentmf select --file AgentMakefile --request "review code" --backend agents-fragments
agentmf run --file AgentMakefile --request "review code" --dry-run --format json
agentmf run --file AgentMakefile --target project.default --dry-run --permission-check "bash:git status" --format json
agentmf run --file AgentMakefile --target project.default --dry-run --output-json '{"goal":"ship runtime","changed_files":[],"verification_result":"dry-run"}' --format json
agentmf prompt --file AgentMakefile --request "review code" --plan docs/superpowers/plans/2026-05-25-agentmf-plugin-adapter.md --include-git-status --format json
agentmf ask --file AgentMakefile --request "review code" --provider echo --format json
agentmf exec --file modules/unknown-repo-security/AgentMakefile --target repo.security_review --provider echo --tool-call "bash:git status" --sandbox-profile read-only --execute-fallbacks --apply --format json
agentmf plugin install --skills-dir ~/.codex/skills --namespace superpowers --bootstrap-skill using-superpowers --out .agentmf/plugin/AgentMakefile --write --format json
agentmf plugin payload --host codex --request "review code" --format json
agentmf plugin payload --host codex --target project.default --plan docs/superpowers/plans/2026-05-25-agentmf-plugin-adapter.md --include-git-status --format json
agentmf skills scan --skills-dir ~/.codex/skills --namespace superpowers --bootstrap-skill using-superpowers --out /tmp/superpowers.AgentMakefile --write
agentmf openclaw scan --skills-dir /path/to/openclaw/skills --namespace openclaw --out modules/openclaw --write --format json
agentmf evo evidence add --source openclaw_import --payload-file /tmp/openclaw-import.json --out-dir .agentmf/evolution/evidence --write --format json
agentmf evo proposal create --title "Curate duplicate OpenClaw review skills" --evidence-file .agentmf/evolution/evidence/registry/openclaw_import.jsonl --module modules/openclaw/coding/AgentMakefile --target skill.coding.review --change-json '{"type":"merge_duplicate_targets","target":"skill.coding.review"}' --evaluation-command "agentmf validate --file modules/openclaw/coding/AgentMakefile" --write --format json
agentmf evo patch generate --proposal-file .agentmf/evolution/candidates/amf-evo-example.proposal.json --write --format json
agentmf evo evaluate --proposal-file .agentmf/evolution/candidates/amf-evo-example.proposal.json --workspace-dir .agentmf/evolution/worktrees/amf-evo-example --write --format json
agentmf evo dream run --evidence-dir .agentmf/evolution/evidence --out-dir .agentmf/evolution/candidates --write --format json
agentmf evo openclaw curate --evidence-file .agentmf/evolution/evidence/registry/openclaw_import.jsonl --out-dir .agentmf/evolution/candidates --write --format json
agentmf skills sync --file modules/oh-my-openagent/AgentMakefile --host codex --write --format json
agentmf benchmark harness --file modules/superpowers/AgentMakefile --case "implement this feature" --baseline agents-md --format json
agentmf benchmark harness --file modules/superpowers/AgentMakefile --case "implement this feature" --baseline all-skills --baseline-skills-dir ~/.codex/skills --format json
agentmf clawbench export --file AgentMakefile --task-id clawbench-demo-1 --instruction "implement this feature" --host codex --model claude-opus-4-7 --format json
agentmf clawbench export-jsonl --file AgentMakefile --tasks-file benchmarks/clawbench-tasks.jsonl --host codex --model claude-opus-4-7 > /tmp/agentmf-clawbench-harnesses.jsonl
agentmf clawbench adapter-contract --host codex --format json
agentmf clawbench import-results --results-file /tmp/clawbench-results.jsonl --format json
agentmf swebench export-jsonl --file AgentMakefile --tasks-file benchmarks/swebench-lite-subset.jsonl --host codex --model gpt-5.4 --limit 5 > /tmp/agentmf-swebench-harnesses.jsonl
agentmf swebench compare --file AgentMakefile --tasks-file benchmarks/swebench-lite-subset.jsonl --baseline agents-md --baseline claude-md --baseline skills-index --format markdown
agentmf swebench adapter-contract --host codex --format json
agentmf swebench import-results --results-file benchmarks/swebench-lite-results.example.jsonl --format json
agentmf swebench pass-report --results-file benchmarks/swebench-lite-results.example.jsonl --baseline-report benchmarks/swebench-lite-comparison.md --format markdown
agentmf swebench predictions --results-file /tmp/swebench-results-with-patches.jsonl --model-name agentmf-gpt-5.4 --dataset lite > /tmp/swebench-predictions.jsonl
agentmf swebench official-dry-run --dataset lite --predictions-path /tmp/swebench-predictions.jsonl --run-id agentmf-lite --smoke-limit 5 --format json
agentmf swebench official-command --dataset lite --predictions-path /tmp/swebench-predictions.jsonl --run-id agentmf-lite --max-workers 4
agentmf swebench official-command --dataset verified --predictions-path /tmp/swebench-verified-predictions.jsonl --run-id agentmf-verified --max-workers 4
agentmf swebench import-official-report --report-file agentmf-gpt-5.4.agentmf-lite.json --format json
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
