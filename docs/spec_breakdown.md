# AgentMakefile Spec Breakdown

This document breaks the design spec into implementation tasks using a Superpowers-style workflow:

1. Define the goal.
2. Inspect current context.
3. Set success criteria.
4. Split work into ordered, testable steps.
5. Track risks and verification for each milestone.

## Goal

Build AgentMakefile from the current MVP 0 prototype into the portable agent
harness specification, compiler, and host adapter layer described in
`docs/agentsfile_design_spec.md` and
`docs/agentmf_agent_harness_architecture.md`.

The next implementation work should be incremental: each task should add a narrow behavior, include fixture-driven tests, and keep the CLI usable after every merge.

## Product Boundary

The selected product direction is Option A:

- AgentMakefile is a harness specification, compiler, and host adapter layer.
- Existing coding-agent hosts own model calls, streaming, tool loops, approval
  UX, terminal/editor UI, and native sandbox execution.
- AgentMakefile owns guidance ingestion, normalized IR, deterministic
  selection, prompt-prefix assembly, guard and permission contracts, native
  artifact generation, host payloads, and benchmark evidence.
- Each target defines a compilable agent harness pipeline: dependency closure,
  selected skills, policies, prompt operations, context rules, guards,
  permissions, fallback behavior, and output contracts.

Option B remains future work:

- A standalone `agentmf` agent runtime can be built later on the same harness
  IR, payloads, permission contracts, and prompt objects.

## Current Context

Implemented:

- Python package and `agentmf` CLI.
- `validate` and `compile`.
- YAML loading and Pydantic source schema.
- Basic local include loading and merge.
- Source to IR normalization.
- `claude-md`, `agents-md`, and `cursor-rule` backends.
- Dry-run output and `--write`.
- Managed block writes for shared Markdown files.
- Fixtures for Karpathy, Superpowers minimal, and unknown repo security.
- Demo for the Karpathy / Andrej case.
- Reusable module layout under `modules/`, with Karpathy represented as `modules/karpathy/AgentMakefile`.
- Superpowers and Oh My OpenAgent represented as separate reusable framework modules under `modules/`.
- The Superpowers module covers all currently installed project Superpowers skills as AgentMakefile skill entries.
- Include namespacing with `as` for local file includes, covering policy, target, skill, dependency, `extends`, `add_policies`, and validation target keys.
- Duplicate policy, skill, and target names across multiple included files are reported with stable diagnostics.
- Locked policies cannot be weakened by later overlays that remove guards, steps, output formats, or locked metadata.
- Target composition preserves explicit overrides and detects circular `extends`.
- The local composition demo combines Karpathy and unknown-repository security modules with namespaced includes.
- The design spec now frames generated agent guidance as cache-friendly prompt-prefix build artifacts.
- The design spec distinguishes static compatibility artifacts from runtime-native dynamic prompt-prefix assembly.
- The design spec defines target fragments as compiled prompt objects.
- Target fragments, fragment manifest hashes, unchanged-write skipping, and JSON link plans are implemented.
- Permission conflicts are normalized with `deny > ask > allow`.
- Permission tool names and simple glob syntax are validated during IR normalization.
- Generated file ownership tests cover unmanaged shared outputs, malformed managed blocks, Cursor rule overwrite protection, and atomic preflight writes.
- Target priority validation rejects non-integer priorities and values outside 0..100, and target dependency validation rejects unknown or cyclic `deps`.
- Snapshot fixtures cover full generated `claude-md`, `agents-md`, and `cursor-rule` content for the Karpathy fixture.
- GitHub Actions CI runs tests and compile checks on Python 3.9 and 3.14.
- README quickstart documents install, editable development setup, tests, and the default Karpathy demo compile path.
- Shared `SKILL.md` rendering covers namespaced skill content and deterministic filesystem-safe skill paths.
- The `claude-skill` backend emits one Claude `SKILL.md` package per unique skill entry.
- The `codex-skill` backend emits one Codex `SKILL.md` package per unique skill entry.
- The `skills-index` backend emits a generated `skills/index.md` compatibility catalog from the same normalized skill entries.
- Backend capability warnings cover permission hard-to-soft downgrades and unsupported native hooks.
- Soft permission guidance is rendered as Markdown tables, and soft backends emit `AMF121` downgrade warnings.
- The Karpathy module exposes a `karpathy-guidelines` skill, so the Karpathy demo default compile emits Markdown, Cursor, Claude skill, and Codex skill outputs.
- `agentmf openclaw scan` imports local OpenClaw-style `**/SKILL.md` trees into category-split AgentMakefile modules with a root index and curator evidence.

Known gaps:

- `--trace` now produces text and JSON compile trace output.
- MVP 1 skill backends are implemented for explicit skill entries, but target-to-skill package generation remains future-facing.
- Dependency-aware invalidation is implemented only as content-based unchanged write skipping, not as a separate build graph scheduler.

## P0: Stabilize MVP 0

### AMF-P0-001 Add Compile Trace Output

Goal: make `--trace` useful.

Status: implemented.

Implementation:

- Add a trace model to `compiler.py`.
- Record source loading, validation, normalization, backend selection, emitted files, and write decisions.
- Print text trace when `--trace` is used.
- Include structured trace in `--format json`.

Acceptance:

- `agentmf compile --trace --file demos/karpathy/AgentMakefile --target agents-md` prints each compiler phase.
- JSON output includes `trace`.
- Tests cover text and JSON trace paths.

### AMF-P0-002 Strengthen Generated File Ownership Tests

Goal: make overwrite safety hard to regress.

Status: implemented.

Implementation:

- Add tests for existing unmanaged `CLAUDE.md` / `AGENTS.md` without `--force`.
- Add tests for malformed managed blocks.
- Add tests for existing `.cursor/rules/*.mdc` without and with `--force`.

Implemented scope:

- Existing unmanaged `CLAUDE.md` and `AGENTS.md` fail with `AMF111` and remain unchanged.
- Duplicate or otherwise malformed managed block markers fail with `AMF112`.
- Existing Cursor rule files fail with `AMF110` unless `--force` is provided.
- Write preflight prevents earlier generated files from being updated when a later artifact is blocked.

Acceptance:

- Existing shared files without managed blocks fail without `--force`.
- Malformed managed blocks fail with `AMF112`.
- Cursor rule overwrite requires `--force`.

### AMF-P0-003 Validate Target Metadata and Dependency References

Goal: enforce the MVP 0 validation surface.

Status: implemented.

Implementation:

- Validate priority type and range.
- Validate `deps` references point to known targets when used as target dependencies.
- Report dependency cycles.
- Keep compiler-only mode from executing dependency selection.

Implemented scope:

- Target priority schema validation requires a strict integer in the inclusive range 0..100.
- Target dependency validation emits `AMF122` for unknown `deps`.
- Target dependency validation emits `AMF123` for circular `deps` with a stable cycle path.
- Compiler-only mode still only validates and renders target metadata; it does not execute dependency selection.

Acceptance:

- Unknown dependency emits a stable diagnostic.
- Cyclic dependency emits a stable diagnostic.
- Existing fixtures remain valid.

### AMF-P0-004 Add CI

Goal: make repository health visible on push.

Status: implemented.

Implementation:

- Add `.github/workflows/test.yml`.
- Run tests on Python 3.9 and a current Python version.
- Run `python -m compileall -q src`.

Implemented scope:

- The workflow runs on push and pull request events.
- The matrix covers Python 3.9 and Python 3.14.
- Each matrix entry installs the package with test extras, runs `PYTHONPATH=src python -m pytest -q`, and runs `python -m compileall -q src`.
- Tests assert the workflow keeps the expected triggers, version matrix, and verification commands.

Acceptance:

- GitHub Actions runs on push and PR.
- Local test command remains `PYTHONPATH=src python3 -m pytest -q`.

### AMF-P0-005 Improve Developer Documentation

Goal: make the prototype runnable by someone opening the repo fresh.

Status: implemented.

Implementation:

- Expand README with install, editable install, test, and demo commands.
- Document the Karpathy demo default compile path.
- Link this breakdown from README.

Implemented scope:

- README includes a fresh-checkout quickstart with virtualenv setup, editable install, root validation, and default demo compile commands.
- README includes development commands for test extras, `PYTHONPATH=src python3 -m pytest -q`, and `python3 -m compileall -q src`.
- README documents the Karpathy demo validate/compile path and lists the Markdown, Cursor, Claude skill, and Codex skill outputs.
- Tests assert the README keeps the required quickstart and demo guidance.

Acceptance:

- README contains a short path from clone to successful demo compile.

### AMF-P0-006 Convert Current Assertions Into Snapshot Fixtures

Goal: make generated Markdown changes deliberate.

Status: implemented.

Implementation:

- Add snapshot files for `claude-md`, `agents-md`, and `cursor-rule`.
- Compare full generated content instead of selected substrings.
- Keep snapshots deterministic.

Implemented scope:

- Added full-content snapshots under `tests/snapshots/` for the Karpathy fixture's `claude-md`, `agents-md`, and `cursor-rule` outputs.
- Replaced selected substring assertions with exact snapshot comparisons.
- Snapshot tests fail when generated Markdown or Cursor rule content changes.

Acceptance:

- Snapshot tests fail on meaningful generated content changes.

## MVP 1: Skill Compiler and Soft Permissions

### AMF-M1-001 Introduce Backend Capability Warnings

Goal: warn when a backend cannot enforce a requested rail.

Status: implemented.

Implementation:

- Use `BackendCapabilities` for each backend.
- Add diagnostics for permission/hook downgrades.
- Keep warnings non-fatal for Markdown and skill backends.

Implemented scope:

- Backends declare capabilities for Markdown, skills, permissions, hooks, and hard enforcement.
- Permission hard-to-soft downgrades emit warning diagnostic `AMF121`.
- Hook downgrades emit warning diagnostic `AMF124` when hooks are compiled for a backend without native hook support.
- Native hard-rail backends such as `claude-code` and `opencode` do not emit permission or hook downgrade warnings for supported capabilities.

Acceptance:

- Cursor and Markdown backends warn when permissions are emitted as soft instructions.
- Tests cover warning text and diagnostic structure.

### AMF-M1-002 Add Shared Skill Rendering

Goal: create one renderer for Claude and Codex skill packages.

Status: implemented.

Implementation:

- Render skill name, description, when-to-use, guards, procedure, and output requirements.
- Slugify skill names deterministically.
- Preserve namespaces in content but use filesystem-safe paths.

Implemented scope:

- `render_skill_markdown` emits a complete `SKILL.md` body from an `IRSkill`.
- The renderer preserves qualified skill names such as `superpowers:systematic-debugging` in frontmatter and content.
- `skill_output_path` and deterministic slugging convert namespaced skill names into filesystem-safe paths such as `.claude/skills/superpowers-systematic-debugging/SKILL.md`.
- Tests cover complete rendering and namespace-safe output paths.

Acceptance:

- A `skills.systematic-debugging` entry renders a complete `SKILL.md`.
- Output paths are deterministic.

### AMF-M1-003 Implement `claude-skill` Backend

Goal: generate Claude skill packages.

Status: implemented.

Implementation:

- Add backend name `claude-skill`.
- Emit `.claude/skills/<slug>/SKILL.md`.
- Generate one file per skill entry.

Implemented scope:

- `claude-skill` is a supported backend target.
- It reuses the shared skill renderer and emits one `.claude/skills/<slug>/SKILL.md` file per unique normalized skill.
- Skill outputs are deterministic by sorted qualified skill name.
- Karpathy and Superpowers minimal fixtures compile with explicit `--target claude-skill`.

Acceptance:

- Karpathy and Superpowers minimal fixtures compile with `--target claude-skill`.
- `test_compile_claude_skill_snapshot.py` passes.

### AMF-M1-004 Implement `codex-skill` Backend

Goal: generate Codex skill packages.

Status: implemented.

Implementation:

- Add backend name `codex-skill`.
- Emit `.codex/skills/<slug>/SKILL.md`.
- Reuse shared skill rendering with Codex-neutral wording.

Implemented scope:

- `codex-skill` is a supported backend target.
- It reuses the shared skill renderer and emits one `.codex/skills/<slug>/SKILL.md` file per unique normalized skill.
- Skill outputs are deterministic by sorted qualified skill name.
- Karpathy and Superpowers minimal fixtures compile with explicit `--target codex-skill`.

Acceptance:

- Karpathy and Superpowers minimal fixtures compile with `--target codex-skill`.
- `test_compile_codex_skill_snapshot.py` passes.

### AMF-M1-004A Add `skills-index` Backend

Goal: generate a compatibility skill catalog from AgentMakefile so
`skills/index.md` can become a build artifact instead of a hand-maintained
source of truth.

Status: implemented.

Implementation:

- Add backend name `skills-index`.
- Emit `skills/index.md` by default.
- Honor `artifacts.skills-index.path` for custom catalog locations.
- List each normalized skill entry with description, match rules, guards,
  steps, output requirements, and deterministic Claude/Codex skill package
  paths.
- Include the shared soft permission table when the source defines permission
  defaults or rules.

Implemented scope:

- `skills-index` is a supported backend target.
- The runtime walkthrough demo includes `skills-index` in its default compile
  target list.
- The generated catalog is a managed shared output, matching the existing
  Markdown managed-block write semantics.

Acceptance:

- A multi-skill AgentMakefile compiles with `--target skills-index`.
- The generated catalog includes `.claude/skills/<slug>/SKILL.md` and
  `.codex/skills/<slug>/SKILL.md` references for each skill.
- `artifacts.skills-index.path` overrides the default output path.

### AMF-M1-005 Emit Formal Soft Permission Tables

Goal: make permission guidance predictable in generated Markdown and skills.

Status: implemented.

Implementation:

- Render permission defaults and rules as tables.
- Include action values `allow`, `ask`, and `deny`.
- Emit backend downgrade warning when enforcement is soft.

Implemented scope:

- Markdown outputs render permission defaults and rules as tables instead of ad hoc bullets.
- Skill package outputs include the same formal permission table when the source has permissions.
- Soft permission backends emit warning diagnostic `AMF121` when permissions are lowered to soft instructions.
- Native hard-rail backends such as `claude-code` and `opencode` continue to emit native permission config without soft downgrade warnings.

Acceptance:

- `test_permissions_soft_warning.py` passes.
- Unknown repo security fixture visibly renders denied install commands.

### AMF-M1-006 Make Karpathy Default Compile Pass

Goal: remove the need for explicit MVP 0 targets in the Karpathy demo.

Status: implemented.

Implementation:

- After `claude-skill` and `codex-skill` are implemented, run `agentmf compile --file demos/karpathy/AgentMakefile`.

Implemented scope:

- `modules/karpathy/AgentMakefile` defines a `karpathy-guidelines` skill that packages the existing Karpathy-style policies for skill backends.
- Karpathy coding targets reference the `karpathy-guidelines` skill.
- The Karpathy demo default compile emits `CLAUDE.md`, `.claude/skills/karpathy-guidelines/SKILL.md`, `.cursor/rules/karpathy-guidelines.mdc`, `AGENTS.md`, and `.codex/skills/karpathy-guidelines/SKILL.md`.

Acceptance:

- The Karpathy demo default compile succeeds.
- It emits `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/karpathy-guidelines.mdc`, `.claude/skills/...`, and `.codex/skills/...`.

## MVP 2: Composition and Local Rule Packages

### AMF-M2-000 Complete Superpowers Module Coverage

Goal: represent the installed Superpowers methodology pack as a reusable AgentMakefile module.

Status: implemented.

Implementation:

- Add one `skills` entry for each installed Superpowers skill.
- Preserve `namespace: superpowers` for every skill entry.
- Add workflow targets for bootstrap, parallel dispatch, plan execution, branch finishing, review requests, worktree setup, and skill authoring.

Acceptance:

- `modules/superpowers/AgentMakefile` includes all installed Superpowers skill names.
- `demos/superpowers/AgentMakefile` compiles with MVP 0 backends.

### AMF-M2-001 Implement Namespaced Includes

Goal: support `include.as`.

Status: implemented for local file includes.

Implementation:

- Prefix included policy, target, and skill names with the alias.
- Rewrite internal references in the included file to namespaced names.
- Keep unaliased local names unchanged.

Implemented scope:

- Namespaces included policy, target, and skill map keys using `<alias>.<name>`.
- Rewrites references inside the included source before merging, including target `policies`, `add_policies`, `skills`, `deps`, `extends`, and validation keys.
- Leaves the including/local source unchanged so it can reference included targets with the namespaced names.

Acceptance:

- A local AgentMakefile can include Karpathy as `karpathy` and reference `karpathy.code.task`.

### AMF-M2-002 Add Deterministic Merge Diagnostics

Goal: report include conflicts clearly.

Status: implemented for duplicate policy, skill, and target names across multiple included files.

Implementation:

- Detect duplicate target, policy, and skill names after include merge.
- Allow explicit override paths only where the spec allows them.
- Include stable YAML-style object paths in diagnostics.

Implemented scope:

- Multiple included files defining the same policy, skill, or target emit `AMF113`.
- Diagnostics are emitted in deterministic policy, skill, target order with stable `policies.<name>`, `skills.<name>`, and `targets.<name>` locations.
- The local AgentMakefile overlay remains allowed to override included definitions according to the current precedence model.

Acceptance:

- Duplicate target after include merge emits a stable diagnostic.

### AMF-M2-003 Enforce Locked Policy Rules

Goal: prevent included locked policies from being weakened silently.

Status: implemented for guards, steps, output formats, and locked metadata.

Implementation:

- Define weakening for guards, steps, output_format requirements, and locked metadata.
- Validate overlay changes against locked policies.
- Emit an actionable diagnostic for rejected changes.

Implemented scope:

- A policy with `locked: true` cannot be overlaid with `locked: false`.
- A locked policy overlay must retain all existing `guards`, `steps`, and `output_format` entries.
- Adding stricter `guards`, `steps`, or `output_format` entries remains allowed.
- A stricter overlay that omits `locked` inherits the locked status instead of weakening it.
- Violations emit `AMF114` with stable policy field locations.

Acceptance:

- Attempting to remove a guard from a locked policy fails.
- Adding stricter guards remains allowed.

### AMF-M2-004 Complete Target Composition

Goal: make `extends`, `add_policies`, `add_steps`, `add_output_format`, and `override` robust.

Status: implemented for parent/child composition, additive fields, explicit empty overrides, and circular `extends` diagnostics.

Implementation:

- Add tests for parent and child target composition.
- Detect circular target extension.
- Preserve explicit false, zero, empty list, and empty mapping overrides.

Implemented scope:

- Child targets inherit parent fields unless the child explicitly sets a replacement.
- `add_policies`, `add_steps`, and `add_output_format` append to the composed target after explicit replacements.
- Explicit `false`, `0`, `[]`, and `{}` values are preserved as overrides.
- Circular target extension emits stable `AMF108` diagnostics.

Acceptance:

- Target composition is deterministic and fixture-backed.

### AMF-M2-005 Add Local Composition Demo

Goal: prove MVP 2 behavior with a realistic project example.

Status: implemented with `demos/local-composition/AgentMakefile` and `modules/unknown-repo-security/AgentMakefile`.

Implementation:

- Add `demos/local-composition/`.
- Include Karpathy and unknown repo security packs.
- Compile into Claude, Codex-compatible `AGENTS.md`, and Cursor outputs.

Implemented scope:

- `modules/unknown-repo-security/AgentMakefile` provides reusable unknown-repository review rails.
- `demos/local-composition/AgentMakefile` composes Karpathy and security modules using `include.as`.
- The demo validates and compiles with `claude-md`, `agents-md`, and `cursor-rule`.

Acceptance:

- Demo validates and compiles with supported MVP 2 targets.

## MVP 2.5: Prompt Fragment Objects

MVP 2.5 bridges static Markdown artifacts and runtime-native prompt assembly. It treats each target-specific prompt prefix as a compiled prompt object that can be regenerated independently, cached by hash, and loaded selectively.

### AMF-M2.5-001 Add Target Fragment Backend

Status: implemented.

Goal: compile per-target prompt fragments instead of only all-in-one `AGENTS.md` / `CLAUDE.md` files.

Implementation:

- Add `agents-fragments` and `claude-fragments` backends.
- Emit one Markdown fragment per normalized target under `.agentmf/fragments/<backend>/<target>.md`.
- Render only each target's dependency closure: inherited target fields, policies, skills, deps, guards, steps, permissions, and output format.
- Keep fragment ordering deterministic and paths stable.

Acceptance:

- `agentmf compile --target agents-fragments` emits one fragment per target.
- A `code.review` fragment includes review-related policies but excludes unrelated target-only guidance.
- The fragment backend does not replace existing all-in-one backends.

### AMF-M2.5-002 Add Fragment Manifest and Hashes

Status: implemented.

Goal: make prompt fragments incrementally rebuildable.

Implementation:

- Emit `.agentmf/fragments/manifest.json` or `.agentmf/fragments/manifest.yml`.
- Record fragment path, backend, target, dependency closure, source file inputs, compiler version, and content hash.
- Compute fragment hashes from normalized IR content rather than raw file timestamps.
- Use the manifest to skip rewriting unchanged fragments.

Acceptance:

- Re-running fragment compilation without source changes reports unchanged fragments.
- Changing an unrelated module does not rewrite unaffected target fragments.
- Manifest entries are deterministic and snapshot-tested.

### AMF-M2.5-003 Add Fragment Selection and Link Plan

Status: implemented.

Goal: select which prompt objects should be loaded for a user request.

Implementation:

- Add a dry-run selector that matches user intent against target `match` rules.
- Output a link plan listing selected fragments and their dependency order.
- Support explicit target selection for deterministic testing.
- Do not require runtime-native prompt assembly yet.

Acceptance:

- Given a review-like request, the selector returns the review target fragment and required deps.
- Given an explicit target, the selector returns that target's fragment closure.
- Link plan output is stable JSON for integration by future runtimes.

## MVP 3: Hard Rails Compiler Targets

### AMF-M3-001 Implement Permission Conflict Resolution

Status: implemented.

Goal: normalize permission conflicts according to `deny > ask > allow`.

Implementation:

- Resolve conflicts during IR normalization.
- Track source locations for conflict diagnostics or trace.

Acceptance:

- Deny wins over ask and allow.
- Ask wins over allow.

### AMF-M3-002 Validate Permission Glob Patterns

Status: implemented for empty tool names, whitespace in tool names, empty patterns, and unterminated glob character classes.

Goal: catch invalid or unsupported permission patterns before emission.

Implementation:

- Validate tool names and glob syntax.
- Report unsupported patterns by backend capability.

Acceptance:

- Invalid permission pattern emits a stable diagnostic.

### AMF-M3-003 Implement `claude-code` Backend

Status: implemented for `.claude/settings.json` permission emission and generated shell hook files.

Goal: generate platform-native Claude Code settings and hook artifacts where feasible.

Implementation:

- Emit `.claude/settings.json`.
- Emit hook files for supported hook events.
- Warn when a hard rail cannot be represented.

Acceptance:

- Unknown repo security fixture generates native permission or hook artifacts where supported.

### AMF-M3-004 Implement `opencode` Backend

Status: implemented for `opencode.json` permission configuration and target-derived agent definitions.

Goal: generate OpenCode configuration.

Implementation:

- Emit `opencode.json`.
- Lower targets, policies, and permissions according to OpenCode support.

Acceptance:

- Unknown repo security fixture compiles to `opencode.json`.

### AMF-M3-005 Add Unknown Repo Hard Rails Demo

Status: implemented with `demos/unknown-repo-security/AgentMakefile`.

Goal: prove MVP 3 end to end.

Implementation:

- Add `demos/unknown-repo-security/`.
- Include permissions, hooks, and soft fallback guidance.

Acceptance:

- Demo compiles into soft Markdown plus native hard rail artifacts.

## MVP 4: Runtime Planning Skeleton

### AMF-M4-001 Add Runtime Dry-Run Skeleton

Status: implemented.

Goal: establish a runtime-facing architecture without executing agent workflows yet.

Implementation:

- Add `agentmf.runtime.create_run_plan`.
- Add `agentmf run --dry-run`.
- Reuse the existing fragment selector and link plan.
- Return selected targets, dependency closure, fragment paths, target contracts, policy contracts, and permission contracts.
- Mark execution-only phases as `not_executed` so the skeleton cannot be mistaken for a full runtime.

Acceptance:

- `agentmf run --dry-run --request ... --format json` emits a stable runtime plan.
- Dry-run output includes selected target fragments plus guards, steps, permissions, output formats, and fallback contracts.
- Runtime execution remains unavailable outside dry-run mode.

### AMF-M4-002 Add Prompt Link Step

Status: implemented.

Goal: assemble the selected target prompt fragments into a runtime prompt prefix without executing the workflow.

Implementation:

- Compile the selected fragment backend in memory during `agentmf run --dry-run`.
- Link only selected target fragments because each target fragment already contains its dependency closure.
- Return the linked prompt prefix content in the runtime plan.
- Compare linked prefix size against the matching all-in-one backend (`agents-md` or `claude-md`).
- Report character counts, approximate token counts, and estimated savings.

Acceptance:

- `agentmf run --dry-run --format json` includes `prompt_prefix.content`.
- Linked prompt content excludes unrelated target-only guidance.
- Runtime output reports linked-vs-all-in-one size and approximate token deltas.

### AMF-M4-003 Add Guard Evaluation Dry-Run

Status: implemented.

Goal: make runtime plans show which guards would be evaluated before any
workflow execution or tool interception exists.

Implementation:

- Add `guard_evaluation` to the runtime dry-run plan.
- Resolve policy guards and target guards from the selected target closure.
- Preserve guard provenance by reporting source, target, policy when
  applicable, guard name, and planned status.
- Mark the guard evaluation runtime phase as `evaluated_dry_run`.
- Show guard evaluation counts and guard records in
  `agentmf run --dry-run --format text`.

Acceptance:

- JSON dry-run output includes target and policy guard evaluation records.
- Text dry-run output summarizes planned guards.
- Guard records are never executed during dry-run.

### AMF-M4-004 Add Deterministic Prompt Command

Status: implemented.

Goal: generate a final prompt payload from selected AgentMakefile fragments
without invoking a model or running tools.

Implementation:

- Add `agentmf.prompt.create_prompt_payload`.
- Add `agentmf prompt`.
- Reuse the runtime prompt-link path for target selection and stable prefix
  assembly.
- Compose the stable prefix with volatile request context into
  `final_prompt`.
- Emit JSON with `stable_prefix`, `volatile_context`, `final_prompt`, and
  trace metadata.
- Emit the final prompt content directly in text mode.

Acceptance:

- `agentmf prompt --request ... --format json` returns a deterministic prompt
  payload.
- Text mode prints the final prompt content without model calls.
- Changing request text changes the final prompt hash but not the stable prefix
  hash for the same selected target.

### AMF-M4-005 Add Plan Input to Runtime Prompt Generation

Status: implemented.

Goal: let `agentmf prompt` include implementation plans as volatile task
context without changing stable prompt-prefix artifacts.

Implementation:

- Add `plan_path` to `agentmf.prompt.create_prompt_payload`.
- Add `--plan` to `agentmf prompt`.
- Read the plan file as UTF-8 text.
- Store plan path and content under `volatile_context.plan`.
- Append the plan after the stable prefix in the final prompt's volatile task
  context section.
- Keep plan content out of `stable_prefix.hash`.

Acceptance:

- `agentmf prompt --plan ... --format json` includes plan path and content
  under `volatile_context.plan`.
- Text and JSON final prompts include a `### Plan` section when a plan is
  provided.
- Changing only plan content changes the final prompt hash but not the stable
  prefix hash.

### AMF-M4-006 Add Context Collection to Runtime Prompt Generation

Status: implemented.

Goal: let `agentmf prompt` include explicit context files and git context as
volatile task context without changing stable prompt-prefix artifacts.

Implementation:

- Add `context_files`, `include_git_status`, and `include_git_diff` to
  `agentmf.prompt.create_prompt_payload`.
- Add `--context-file`, `--include-git-status`, and `--include-git-diff` to
  `agentmf prompt`.
- Read explicit context files as UTF-8 text.
- Reject secret-looking context files such as `.env`, `.npmrc`, `.pypirc`, and
  names containing `secret`.
- Collect git status and git diff only when requested.
- Append context files, git status, and git diff after the stable prefix in the
  final prompt's volatile task context section.
- Keep context content out of `stable_prefix.hash`.

Acceptance:

- `agentmf prompt --context-file ... --format json` includes context file path
  and content under `volatile_context.context_files`.
- `agentmf prompt --include-git-status --include-git-diff --format json`
  includes git status and git diff under volatile context.
- Final prompts include `### Context File`, `### Git Status`, and `### Git Diff`
  sections only when those inputs are requested.
- Secret-looking context files are rejected before prompt generation.

### AMF-M4-007 Add Provider Adapter for One-Shot Ask

Status: implemented.

Goal: let `agentmf ask` run a one-shot provider adapter using the deterministic
prompt payload path, without introducing a tool loop or external provider
dependency.

Implementation:

- Add `agentmf.provider.ProviderAdapter`.
- Add a deterministic local `echo` provider.
- Add `agentmf.ask.create_ask_payload`.
- Add `agentmf ask`.
- Reuse `create_prompt_payload` for request, plan, context file, and git
  context assembly.
- Return provider response content, selected target trace, stable prefix hash,
  and final prompt hash.
- Accept provider options (`--provider`, `--model`, `--temperature`, and
  `--max-output-tokens`) while the initial `echo` provider only uses
  `--provider` and `--model`.

Acceptance:

- `agentmf ask --provider echo --format json` returns a structured ask payload
  with prompt payload and provider response.
- Text mode prints the provider response content.
- Unsupported providers fail with a stable diagnostic.
- Plan, context-file, git status, and git diff options flow through the prompt
  payload reused by `agentmf ask`.

### AMF-M4-008 Add Permission Dry-Run

Status: implemented.

Goal: evaluate proposed tool calls against AgentMakefile permission rules
without executing those calls.

Implementation:

- Add `proposed_tool_calls` to `agentmf.runtime.create_run_plan`.
- Add `permission_evaluation` to runtime dry-run output.
- Add `agentmf run --permission-check TOOL:INPUT`.
- Match rules with shell-style glob semantics.
- Resolve multiple matching rules with the existing most-restrictive order:
  `deny > ask > allow`.
- Use configured tool defaults when no rule matches, and the implicit
  conservative default `ask` when neither a rule nor a tool default exists.
- Mark the permission runtime phase as `evaluated_dry_run` only when proposed
  tool calls are supplied.

Acceptance:

- JSON dry-run output includes each proposed tool call, matched rules, source,
  and final action.
- Text dry-run output summarizes proposed permission checks.
- Dry-run permission evaluation never executes tool calls.

### AMF-M4-009 Add Gated Tool Loop Prototype

Status: implemented.

Goal: introduce the first execution surface while keeping tool execution
explicit, permission-gated, and traceable.

Implementation:

- Add `agentmf.tool_loop.create_exec_payload`.
- Add `agentmf exec`.
- Require `--apply` before any tool execution.
- Accept explicit proposed tool calls with `--tool-call TOOL:INPUT`.
- Reuse runtime target selection, prompt linking, guard dry-run, and permission
  dry-run before execution.
- Execute only tool calls whose permission action is `allow`.
- Block `ask` and `deny` tool calls with structured tool result records.
- Support only the local `bash` tool in the first prototype.
- Return stdout, stderr, exit code, blocked reasons, runtime plan, and
  diagnostics in JSON mode.

Acceptance:

- `agentmf exec` without `--apply` fails before executing tools.
- `agentmf exec --apply --tool-call ... --format json` returns structured tool
  results.
- Allowed bash calls execute and capture stdout/stderr.
- `ask` and `deny` calls are blocked and not executed.

### AMF-M4-010 Add Output Validation Dry-Run

Status: implemented.

Goal: evaluate proposed runtime outputs against selected target output
contracts without executing workflow steps.

Implementation:

- Add `proposed_output` to `agentmf.runtime.create_run_plan`.
- Add `agentmf run --output-json JSON`.
- Add `output_validation` to runtime dry-run output.
- Validate selected target and policy `output_format` entries as required
  fields.
- Validate `output_schema.required` entries as required fields.
- Mark the output validation runtime phase as `evaluated_dry_run` when a
  proposed output object is supplied.

Acceptance:

- JSON dry-run output reports required fields, present fields, missing fields,
  and valid/invalid status.
- Complete proposed outputs are marked valid.
- Missing output contract fields are marked invalid.
- Output validation dry-run never executes workflow steps.

### AMF-M4-011 Add Fallback Handling for Blocked Tool Calls

Status: implemented.

Goal: make blocked tool calls produce a traceable fallback plan without
executing fallback actions automatically.

Implementation:

- Add `fallback_handling` to `agentmf exec` payloads.
- Detect blocked tool results from permission `ask`, permission `deny`, and
  unsupported tools.
- Map blocked tool calls to selected target `fallback.blocked` actions.
- Report planned fallback actions with target, trigger, and status.
- Report `not_planned` when a call is blocked and no selected target defines a
  matching fallback.

Acceptance:

- Blocked tool calls include planned fallback actions when the target defines
  `fallback.blocked`.
- Blocked tool calls without fallback contracts are reported as `not_planned`.
- Fallback handling is dry-run only and does not execute fallback actions.

### AMF-M4-012 Add Sandbox Profile Metadata for Exec

Status: implemented.

Goal: make `agentmf exec` expose requested sandbox posture in structured
payloads.

Implementation:

- Add `sandbox_profile` to `agentmf.tool_loop.create_exec_payload`.
- Add `agentmf exec --sandbox-profile none|read-only|workspace-write`.
- Include `sandbox` metadata in exec payloads with profile, filesystem,
  network, supported profiles, mode, and enforcement status.
- Include the selected sandbox profile in `execution.sandbox_profile`.
- Reject unknown sandbox profiles with stable diagnostic `AMF143`.

Acceptance:

- Exec payloads include sandbox metadata for the requested profile.
- CLI `agentmf exec --sandbox-profile ...` passes the selected profile through
  to the payload.
- Unknown sandbox profiles are rejected before runtime planning or tool
  execution.
- Sandbox profile payloads make the current enforcement mode explicit.

### AMF-M4-013 Add Richer Output Schema Validation

Status: implemented.

Goal: validate basic JSON schema property types in addition to required output
fields.

Implementation:

- Extend runtime output validation to inspect `output_schema.properties`.
- Support simple JSON-schema `type` values: `string`, `array`, `object`,
  `boolean`, `integer`, `number`, and `null`.
- Report type mismatches as `type_errors` with field, expected type, and actual
  type.
- Keep unsupported schema keywords ignored until a full JSON Schema validator
  milestone.

Acceptance:

- Output validation reports type errors for mismatched schema property types.
- Valid proposed outputs with matching property types remain valid.
- Missing-field and type-error results are reported together in the same
  dry-run payload.

### AMF-M4-014 Add Sandbox Enforcement Integration

Status: implemented.

Goal: make `agentmf exec` apply the requested sandbox profile before running
local tool calls.

Implementation:

- Mark `read-only` and `workspace-write` sandbox profiles as prototype
  preflight-enforced in exec payloads.
- Block obvious write-like bash commands and write redirections under the
  `read-only` profile even when permissions allow the command.
- Allow workspace-local write-like commands under `workspace-write`.
- Block simple absolute-path or parent-directory write operands under
  `workspace-write`.
- Report sandbox blocks as structured blocked tool results with a stable
  reason and selected sandbox profile.

Acceptance:

- `read-only` blocks allowed write-like bash calls before subprocess execution.
- `workspace-write` allows allowed workspace-local write calls.
- Sandbox-blocked calls include `reason`, `permission_action`, and
  `sandbox_profile` in the tool result.

### AMF-M4-015 Add Fallback Execution Prototype

Status: implemented.

Goal: let hosts opt into executing selected target fallback actions for blocked
tool calls without granting fallback actions external tool authority.

Implementation:

- Add `execute_fallbacks` to `create_exec_payload`.
- Add `agentmf exec --execute-fallbacks`.
- Keep default fallback behavior as dry-run planning.
- When enabled, record each configured `fallback.blocked` action as an
  executed internal no-op result.
- Report fallback execution status in JSON payloads and text output.

Acceptance:

- `agentmf exec` defaults to planned fallback actions only.
- `agentmf exec --execute-fallbacks` records executed fallback results for
  blocked calls with configured fallback actions.
- Fallback execution uses `internal_noop` and does not run additional external
  tools.

### AMF-M4-016 Add Provider-Backed Tool-Call Interception Contract

Status: implemented.

Goal: define the host/runtime boundary for provider-requested tool calls before
introducing an autonomous provider-driven loop.

Implementation:

- Add `provider` to `create_exec_payload`.
- Add `agentmf exec --provider`.
- Preserve optional provider tool-call ids through permission evaluation and
  tool results.
- Add `tool_interception` to exec payloads with provider identity, event flow,
  host boundary responsibilities, per-call permission action, sandbox profile,
  final interception decision, block reason, and result status.
- Keep execution deterministic; the provider is not called from `agentmf exec`
  in this milestone.

Acceptance:

- API callers can provide provider tool-call ids and see them in the
  interception contract.
- CLI callers can set `agentmf exec --provider`.
- Interception records tie each provider tool-call request to permission,
  sandbox, and host-result decisions.

### AMF-M4-017 Add Full JSON Schema Validator Integration

Status: implemented.

Goal: replace the simple output property type checker with JSON Schema
validation while keeping the previous output validation fields stable.

Implementation:

- Add `jsonschema` as a runtime dependency.
- Validate policy and target `output_schema` contracts with
  `Draft202012Validator`.
- Preserve `required_fields`, `missing_fields`, and `type_errors` output for
  compatibility.
- Add `schema_errors` for full JSON Schema failures not already represented by
  `missing_fields` or `type_errors`.
- Report deterministic source, path, validator, and message fields for each
  schema error.

Acceptance:

- Output validation reports nested JSON Schema failures such as `enum`,
  `minItems`, `items`, and `additionalProperties`.
- Existing missing-field and type-error contracts remain available.
- Full-schema failures mark output validation invalid.

### AMF-M4-CLI-000 Specify Prompt-Aware Runtime CLI

Status: documented.

Goal: define how AgentMakefile can become a Claude Code / Codex CLI-style
agent shell that automatically builds a request-specific prompt prefix before
model invocation.

Design:

- See [agentmf_runtime_cli_spec.md](agentmf_runtime_cli_spec.md).
- Treat AgentMakefile modules as stable behavior source.
- Treat implementation plans as volatile runtime task context.
- Add a staged command surface: `agentmf prompt`, `agentmf ask`,
  `agentmf chat`, and gated `agentmf exec`.
- Keep prompt generation testable before provider calls or tool loops exist.

Acceptance:

- Runtime CLI spec explains request and plan input semantics.
- Runtime CLI spec separates stable prompt prefix from volatile task context.
- Runtime CLI spec defines milestones from prompt generation through tool-loop
  execution.
- Main README and design spec link to the runtime CLI spec.

### AMF-PAD-001 Specify Plugin Adapter Protocol

Status: documented.

Goal: define the lightweight plugin-first path where existing agent CLIs call
AgentMakefile for prompt assembly instead of AgentMakefile replacing the host
runtime.

Design:

- See [agentmf_plugin_adapter_spec.md](agentmf_plugin_adapter_spec.md).
- Existing agent CLIs own model calls, streaming, tool loops, approval UX, and
  sandboxing.
- AgentMakefile owns target selection, prompt fragment linking, stable prefix
  generation, volatile context packaging, and trace output.
- The stable JSON protocol is `agentmf plugin payload`.

Acceptance:

- Plugin spec defines host responsibilities and AgentMakefile responsibilities.
- Plugin spec defines stable prefix, volatile context, host instructions, trace,
  and diagnostics fields.
- Plugin spec defines command, library, and native host adapter modes.
- Plugin spec keeps full standalone runtime work as a later path.

### AMF-PAD-002 Add Plugin Payload Builder

Status: implemented.

Goal: expose a library API that wraps the runtime dry-run plan into a
host-oriented prompt payload for plugin adapters.

Implementation:

- Add `agentmf.plugin.create_plugin_payload`.
- Add `PluginPayloadResult`.
- Reuse `create_run_plan(..., dry_run=True)` for target selection and prompt
  linking.
- Return stable prefix content, stable prefix size, stable prefix hash,
  host instructions, volatile context placeholders, and trace metadata.
- Export the plugin payload builder from `agentmf`.

Acceptance:

- A caller can build a plugin payload without invoking a model or tool loop.
- The payload reports selected targets and stable prefix content.
- Volatile context placeholders are separate from stable prefix content.
- Runtime trace includes target closure, linked fragments, and size comparison.

### AMF-PAD-003 Add Plugin Payload CLI Command

Status: implemented.

Goal: expose the plugin payload builder through the command line so host agents
can shell out for prompt payload JSON.

Implementation:

- Add `agentmf plugin payload`.
- Support `--host`, `--request`, positional request, `--target`, `--backend`,
  and `--format`.
- Emit stable JSON with `ok`, `plugin_payload`, and `diagnostics`.
- Keep plan and context file flags for AMF-PAD-004.

Acceptance:

- `agentmf plugin payload --host codex --request ... --format json` returns a
  selected plugin payload.
- Positional request and `--request` are mutually exclusive.
- Text mode summarizes host, selected targets, stable prefix size, and stable
  prefix hash.

### AMF-PAD-004 Add Plan and Context Inputs

Status: implemented.

Goal: let plugin payloads carry request-specific task context without changing
the stable prompt prefix.

Implementation:

- Add `plan_path` to `create_plugin_payload`.
- Add context file inputs with secret-looking file rejection.
- Add opt-in git status and git diff collection.
- Add `--plan`, `--context-file`, `--include-git-status`, and
  `--include-git-diff` to `agentmf plugin payload`.
- Keep plan, context files, git status, and git diff under `volatile_context`.

Acceptance:

- Plan content appears only in `volatile_context.plan`.
- Changing only plan content does not change `stable_prefix.hash`.
- Context files appear under `volatile_context.context_files`.
- `.env`, `.npmrc`, `.pypirc`, and secret-looking context file names are
  rejected.
- Git status and git diff are collected only when explicitly requested.

### AMF-PAD-005 Add Host Profiles

Status: implemented.

Goal: make plugin payload host instructions explicit per supported host without
depending on host-specific SDKs.

Implementation:

- Add host profiles for `generic`, `codex`, `claude-code`, `cursor`, and
  `opencode`.
- Include `profile`, `instruction_surface`, `permissions_mode`, and
  `native_artifacts` in `host_instructions`.
- Keep common injection and cache boundary fields stable across hosts.
- Document host profile semantics in the plugin adapter spec.

Acceptance:

- Each supported host returns a distinct `host_instructions.profile`.
- Hosts with native hard-rail surfaces advertise
  `host_enforced_when_supported`.
- Hosts without native enforcement advertise `soft_guidance`.
- Host profiles remain payload metadata only; they do not call host SDKs.

### AMF-PAD-006 Add Example Adapter Docs

Status: implemented.

Goal: show host authors how to call `agentmf plugin payload` and inject the
returned prompt payload into existing agent runtimes.

Implementation:

- Add [agentmf_plugin_adapter_examples.md](agentmf_plugin_adapter_examples.md).
- Document command-adapter usage.
- Document Python wrapper usage.
- Document plan-aware and context-file invocations.
- Document host-specific notes for `generic`, `codex`, `claude-code`,
  `cursor`, and `opencode`.
- Document error handling and the host security boundary.

Acceptance:

- Docs show how to consume `stable_prefix.content`.
- Docs show volatile context appended after the stable prefix.
- Docs explain that the host still owns model calls, tool loops, approvals, and
  sandboxing.

### AMF-PAD-007 Add Selected Skills to Plugin Payload

Status: implemented.

Goal: make plugin payloads usable as a skill-routing layer for hosts that can
load generated Codex or Claude skill packages.

Implementation:

- Add `selected_skills` to `agentmf plugin payload`.
- Preserve dependency-closure order and deduplicate repeated skill references.
- Add `skill_artifacts` with `skills_index`, Codex `SKILL.md`, and Claude
  `SKILL.md` paths for each selected skill.
- Keep `stable_prefix.content` as the fallback for hosts that cannot load
  native skill files.

Acceptance:

- A target with dependency skills returns all selected skills in closure order.
- Duplicate skill references appear only once.
- Codex and Claude artifact paths use the same deterministic slugging as the
  skill backends.
- Docs link from README and the plugin adapter spec.

### AMF-PAD-007A Add Selection Trace to Plugin Payload

Status: implemented.

Goal: make plugin payload skill routing explainable enough for host adapters to
debug and log unexpected target or skill choices.

Implementation:

- Add `selection_trace` to link plans and plugin payloads.
- Record the selection mode and algorithm.
- For request matching, record matched `match.user_intent` terms, ranked
  candidates, target priority, selected target, and dependency closure.
- For explicit target selection, record requested target names and selected
  dependency closure.
- Mirror the selection trace under `trace.selection` for host trace consumers.

Acceptance:

- Request-based selection exposes the matched terms that caused the chosen
  target to win.
- Candidate ranking shows priority/name tie-break behavior.
- Plugin payloads include the same selection rationale without requiring hosts
  to parse rendered prompt text.

### AMF-PAD-008 Encode Superpowers Skill Routing Graph

Status: implemented.

Goal: make the Superpowers module usable as a structured replacement for the
`using-superpowers` skill-selection index.

Implementation:

- Analyze the installed Superpowers skill set and keep every installed skill in
  `modules/superpowers/AgentMakefile`.
- Add request `match` rules to methodology targets so `agentmf select` can
  choose workflows without relying only on model-side semantic judgment.
- Add `methodology.bootstrap` as the explicit dependency root for each
  non-bootstrap methodology target.
- Preserve `using-superpowers` as the bootstrap skill while making its role a
  graph edge instead of only prompt text.

Acceptance:

- Common Superpowers requests route to the expected methodology target.
- Each routed methodology target has `methodology.bootstrap` first in its
  target closure.
- Plugin payloads include `superpowers:using-superpowers` before the selected
  workflow skills.

### AMF-PAD-009 Skill Import and Selection Optimization

Status: implemented.

Goal: make AgentMakefile usable as the structured routing and optimization
layer for existing `SKILL.md` ecosystems. This is the reverse of the original
compile path: instead of only treating AgentMakefile as the source of truth for
generated skills, a plugin can import existing skills into a generated
AgentMakefile and then use target selection to choose the right skill closure
per request.

Implementation:

- Add `agentmf skills scan`.
- Scan one or more `--skills-dir` roots for `*/SKILL.md`.
- Parse YAML frontmatter `name` and `description`.
- Infer request `match.user_intent` terms from skill names, descriptions, and
  `## When to Use` bullets.
- Emit a generated AgentMakefile with one `skills:` entry and one `skill.*`
  target per scanned skill.
- Support `--bootstrap-skill` so a bootstrap skill such as
  `using-superpowers` becomes an explicit dependency for every other skill
  target.
- Use `agentmf plugin payload` on the generated AgentMakefile to return
  `selected_skills`, native skill artifact paths, and `selection_trace`.

Acceptance:

- A scanned skill tree can be loaded by `agentmf validate`.
- A request can route through the generated `skill.*` target.
- Plugin payloads expose selected skills in bootstrap-first dependency order.
- Plugin payloads explain why those skills were selected.
- The scanner is usable as a self-hosting smoke path for installed Superpowers
  skills.

### AMF-PAD-010 Request Normalization and Semantic Matching

Status: implemented.

Goal: improve plugin skill selection for imported skill indexes when the user
request does not exactly contain the English `match.user_intent` phrase.

Implementation:

- Add deterministic request normalization for case, punctuation, underscores,
  and hyphenation.
- Add a built-in translation/alias layer for common Chinese and English
  development intents.
- Add lightweight semantic token-overlap matching with canonicalized terms.
- Record `normalized_request`, `expanded_request_terms`, `match_details`, and
  `match_score` in `selection_trace`.
- Preserve deterministic ranking by priority, match score, and target name.

Acceptance:

- Hyphenated skill names can match space-separated user requests.
- A Chinese request such as `请实现这个功能` can match `implement this feature`.
- Related English requests such as completion reporting can match verification
  skills through semantic token overlap.
- Selection traces show which matching layer caused each candidate to match.

### AMF-PAD-011 Plugin Install Skill Index Bootstrap

Status: implemented.

Goal: make plugin installation bootstrap the skill-selection graph from the
host's existing native skills, then tell the model to use AgentMakefile payloads
for request-time skill selection.

Implementation:

- Add `agentmf plugin install`.
- Scan one or more `--skills-dir` roots through the existing skill scanner.
- Optionally write the generated skill-index AgentMakefile to
  `.agentmf/plugin/AgentMakefile` or a caller-provided `--out` path.
- Return `model_instructions` telling the host/model to call
  `agentmf plugin payload --file <generated AgentMakefile>` before choosing
  skills for each request.
- Include `next_payload_command` so plugin installers can copy or invoke the
  request-time command directly.

Acceptance:

- A plugin install call can scan an existing `SKILL.md` tree and write a valid
  AgentMakefile.
- The generated AgentMakefile works with `agentmf plugin payload`.
- The install payload explicitly names `selected_skills` and
  `selection_trace` as the request-time fields the model should inspect.

### AMF-PAD-012 Skill-Match-Derived Target Routing

Status: implemented.

Goal: let reusable AgentMakefile modules compile into multiple native skills
and still optimize skill selection even when a target does not duplicate every
referenced skill's `match.user_intent` terms.

Implementation:

- Extend request-based target selection to inspect each target's referenced
  skills.
- Treat a skill `match` hit as a candidate match for the target that packages
  that skill.
- Preserve direct target `match` priority over skill-derived target matches,
  then use target priority and match score within each group.
- Add `source: skill:<qualified-name>` to skill-derived match details in
  `selection_trace`.

Acceptance:

- `modules/oh-my-openagent/AgentMakefile` can route
  `autonomous implementation` to `omo.ultrawork` without an explicit target
  match.
- Plugin payloads for the routed target expose the OMO selected skills.
- Selection trace explains which skill supplied the matched term.

### AMF-PAD-013 System Skill Sync and Host Integration Instructions

Status: implemented.

Goal: provide the forward installation path for hand-authored AgentMakefile
modules: compile them into native host skills and sync those skills into a
host skill root while keeping request-time selection delegated to plugin
payloads.

Implementation:

- Add `agentmf skills sync`.
- Support `--host codex` by compiling `codex-skill` and mapping generated
  `.codex/skills/*/SKILL.md` files into the Codex skill root.
- Support `--host claude-code` by compiling `claude-skill` and mapping
  generated `.claude/skills/*/SKILL.md` files into the Claude Code skill root.
- Keep sync dry-run by default; write only with `--write`.
- Refuse to overwrite changed installed skills unless `--force` is set.
- Return `host_integration_instructions` that tell hosts to call
  `agentmf plugin payload` and inspect `selected_skills`, `skill_artifacts`,
  and `selection_trace`.

Acceptance:

- A module can be planned for system skill installation without writing files.
- A module can be written to a caller-provided skill root in tests.
- Existing modified installed skills are protected unless `--force` is set.
- CLI JSON exposes the planned files and host integration instructions.

### AMF-PAD-014 Multi-Source Guidance Ingestion

Status: planned.

Goal: generalize reverse import from existing `SKILL.md` package directories to
broader guidance corpora such as `AGENTS.md`, `CLAUDE.md`, standalone
`SKILL.md`, `skills/index.md`, Cursor rules, and framework Markdown guidance.

Implementation:

- Add `agentmf guidance scan`.
- Add a `guidance_scanner` facade that can dispatch to source readers by
  source type.
- Preserve the existing `agentmf skills scan` path by treating it as the
  `skill-dir` source reader.
- Support first-slice readers for `skill-dir`, `skill-md`, `agents-md`, and
  `claude-md`.
- Emit a generated AgentMakefile with `metadata.module_type: guidance-index`.
- Represent imported Markdown files as guidance-backed targets with
  `implementation.source` and `implementation.source_type`.
- Preserve native `selected_skills` behavior for real skill package inputs.
- Extend `agentmf plugin install` with planned `--source` / `--source-type`
  options while keeping `--skills-dir` compatibility.

Acceptance:

- A `SKILL.md` directory scan still produces the same selectable skill targets.
- A standalone `SKILL.md` can be imported into a generated AgentMakefile.
- A project `AGENTS.md` can be imported as a routeable guidance target.
- A project `CLAUDE.md` can be imported as a routeable guidance target.
- `agentmf plugin payload` can select imported guidance targets and return
  `selection_trace`.
- Existing `agentmf skills scan` and `agentmf plugin install --skills-dir`
  commands remain compatible.

Plan: `docs/superpowers/plans/2026-05-26-agentmf-guidance-ingestion.md`.

## OpenClaw Importer Tasks

The OpenClaw importer line is specified in
[agentmf_openclaw_importer_spec.md](agentmf_openclaw_importer_spec.md). It
turns a local large skill ecosystem into modular AgentMakefile sources before
curation and evolution. This keeps the first path local-only and reviewable:
scan, render, select-smoke, and export evidence.

### AMF-OPENCLAW-001 Local Skill Scanner

Status: implemented.

Goal: recursively scan local OpenClaw-style `SKILL.md` trees into normalized
records without contacting a remote registry.

Implementation:

- Add `agentmf.openclaw.create_openclaw_import_payload`.
- Recursively scan `**/SKILL.md` under each input skills directory.
- Parse frontmatter `name`, `description`, `category`, and `tags`.
- Infer category from the first path segment when frontmatter does not provide
  one.
- Prefix generated skill names with the category so duplicate original names can
  coexist.
- Add stable numeric suffixes for duplicate generated names inside one category.

Acceptance:

- Nested local skill paths are detected.
- Duplicate original names do not fail the scan.
- Duplicate generated names inside one category do not overwrite each other.
- Generated records keep original source paths and relative paths.

### AMF-OPENCLAW-002 Modular AgentMakefile Renderer

Status: implemented.

Goal: render one category-level AgentMakefile per imported category.

Implementation:

- Group scanned skills by category.
- Render each group through the existing skill-index data model.
- Mark category modules with `metadata.module_type:
  openclaw-skill-category`.
- Preserve category, tags, original name, and relative source path in each skill
  implementation block.

Acceptance:

- Category modules validate through the existing loader.
- Category-prefixed generated skills are routeable by existing selectors.

### AMF-OPENCLAW-003 Category Split + Root Index

Status: implemented.

Goal: avoid a flat thousands-skill index by generating a root index that
includes category modules.

Implementation:

- Write `<out>/AgentMakefile` as the root index.
- Write `<out>/<category>/AgentMakefile` for each category.
- Store summary metadata for skill count, category count, source, and category
  names.

Acceptance:

- The root index loads all category modules.
- Selection can run against the root index.

### AMF-OPENCLAW-004 Selection Smoke Test

Status: implemented.

Goal: prove imported OpenClaw modules participate in normal AgentMakefile
target selection.

Implementation:

- Add a fixture test with a local coding skill and research skill.
- Run `create_link_plan` against the generated root AgentMakefile.
- Assert a category-prefixed `skill.*` target is selected.

Acceptance:

- A request such as `review code` selects the generated coding review target.

### AMF-OPENCLAW-005 Curator Evidence Export

Status: implemented.

Goal: emit small deterministic evidence for later curation and evolution work.

Implementation:

- Include `curator_evidence` in the scan payload.
- Report skill count, category count, per-category counts, duplicate original
  names, and generated module paths.
- Keep evidence independent of write mode.

Acceptance:

- Evidence exposes duplicate original skill names without failing the import.
- Evolution tasks can consume the evidence without rescanning source files.

### AMF-HARNESS-001 Target Pipeline IR

Status: implemented.

Goal: make each target a compilable agent harness pipeline instead of only a
Markdown instruction block or legacy action list.

Implementation:

- Add `pipeline` to normalized `IRTarget`.
- Normalize legacy `steps: [{action: ...}]` into `action_ops`.
- Normalize typed `select_context` steps into `context_ops`.
- Normalize typed `link_prompt`, `prompt`, `use_skill`, and `apply_policy`
  steps into `prompt_ops`.
- Normalize typed `check_guard`, `check_permission`, `validate_output`, and
  `fallback` steps into guard, permission, output-contract, and fallback
  operation groups.
- Preserve ordered `operations` for each target pipeline so adapters can
  replay or explain the intended harness flow.
- Include policy steps, policy guards, target guards, fallback behavior, skills,
  policies, deps, and output contracts in the target pipeline.
- Preserve existing `steps` and `target_contracts` for compatibility.
- Expose selected `target_pipelines` in selection and runtime dry-run plans.

Acceptance:

- A target with typed steps produces a structured pipeline in the normalized IR.
- Legacy `action` steps remain valid and appear as action operations.
- `agentmf run --dry-run` exposes selected target pipelines alongside existing
  contracts.
- `agentmf select` exposes `target_pipelines` and a compact `pipeline_trace`.

### AMF-HARNESS-002 Selected Pipeline in Plugin Payload

Status: implemented.

Goal: let host adapters inspect the selected harness pipeline, not only the
selected target and skill names.

Implementation:

- Add `selected_pipeline` to `agentmf plugin payload`.
- Include the selected `target_closure`.
- Include the runtime `target_pipelines` generated for that closure.
- Include flat operation groups for stable prompt operations, volatile context
  operations, guards, permissions, fallbacks, and output contracts.

Acceptance:

- Plugin payload JSON includes `selected_pipeline.target_closure`.
- Plugin payload JSON includes structured target pipeline operations.
- Plugin payload JSON includes `stable_prompt_ops`, `volatile_context_ops`,
  `guard_ops`, `permission_ops`, and `fallback_ops`.
- Existing `selected_skills`, `skill_artifacts`, and `selection_trace` remain
  unchanged.

### AMF-HARNESS-003 Pipeline-Aware Fragment Backend

Status: implemented.

Goal: make target fragments compile as readable harness pipeline objects, not
only raw target text.

Implementation:

- Render a `Harness Pipeline` section in `agents-fragments` and
  `claude-fragments`.
- Render the target closure's prompt operations, context operations, action
  operations, guards, permission checks, fallback behavior, and output contract.

Acceptance:

- A selected target fragment includes its dependency pipeline closure.
- Typed operations are visible in deterministic Markdown output.

### AMF-HARNESS-004 Pipeline Dry-Run Trace

Status: implemented.

Goal: let `agentmf run --dry-run` explain how a selected harness would be
assembled before any host model or tool loop runs.

Implementation:

- Add `pipeline_execution_plan` to runtime dry-run output.
- Report selected target, resolved deps, ordered pipeline operations, stable
  prefix objects, volatile context inputs, guard ops, permission ops, output
  validation, and fallback plan.

Acceptance:

- Dry-run JSON shows the pipeline execution plan without executing tools.
- Proposed output and proposed tool calls are evaluated against the selected
  pipeline contracts.

### AMF-PAD-015 Benchmark CLI First Slice

Status: partially implemented.

Goal: make AgentMakefile's prompt-size, cache-stability, pipeline-selection,
and skill-selection benefits measurable through deterministic benchmark
commands.

Implementation:

- Add the first implemented `agentmf benchmark harness` slice.
- Reuse plugin payload selected pipelines, selection traces, selected skills,
  stable prefix hashes, prompt-size comparison data, and guard/permission
  coverage.
- Support multiple baseline types: `agents-md`, `claude-md`, `skills-index`,
  `baseline-file`, `all-skills`, and `none`.
- Keep `agentmf benchmark skills` as a future compatibility-focused extension.
- Support inline cases, JSON output, Markdown output, report writing, and
  fail-on-mismatch diagnostics for expected labels in later slices.

Acceptance:

- A benchmark case can report selected targets, selected skills, selected
  pipeline size, stable prefix hash, baseline size, baseline hash, baseline
  sources, and savings.
- A benchmark case can report prompt/context/guard/permission operation counts.
- Markdown output is suitable for demos and README examples.
- JSON output is suitable for CI and future benchmark suites.

Plan: `docs/superpowers/plans/2026-05-26-agentmf-benchmark-cli.md`.

### AMF-BENCH-001 Harness Benchmark Suite Spec

Status: implemented.

Goal: define the competition-style benchmark path for AgentMakefile as an
agent harness management system, not just a prompt-size CLI.

Implementation:

- Add `docs/agentmf_harness_benchmark_suite_spec.md`.
- Define deterministic harness-management benchmark layers and later
  execution benchmark layers.
- Define suite file schema, adapter model, result schema, scoring dimensions,
  fairness rules, safety rules, and self-hosting demo cases.
- Link the suite spec from README and the benchmark CLI spec.

Acceptance:

- The benchmark roadmap distinguishes deterministic harness selection metrics
  from opt-in execution/pass-rate metrics.
- The suite spec can guide implementation of `agentmf benchmark suite` without
  changing the existing `agentmf benchmark harness` first slice.

### AMF-BENCH-008 ClawBench Harness Export

Status: implemented.

Goal: make AgentMakefile usable as a ClawBench-compatible harness selection
layer before any model execution adapter exists.

Implementation:

- Add `agentmf clawbench export`.
- Add `agentmf.clawbench.create_clawbench_harness_export`.
- Reuse `agentmf plugin payload` to select targets, skills, pipeline
  operations, stable prefix content/hash, volatile context, and host injection
  metadata for a benchmark task instruction.
- Emit a ClawBench-oriented trace bundle with target closure, linked fragments,
  selected pipeline operations, guard ops, permission ops, fallback ops, output
  contracts, diagnostics, and explicit `not_executed` downstream metadata.

Acceptance:

- A ClawBench task id and instruction can be exported as a stable AgentMakefile
  harness bundle.
- The export does not execute a model or tools.
- The JSON shape can be consumed by an external ClawBench runner or host
  execution adapter.

### AMF-BENCH-009 ClawBench Task/Corpus Reader

Status: implemented.

Goal: read real ClawBench-style task corpora as newline-delimited JSON so the
AgentMakefile harness layer can operate on a task set instead of only a single
instruction.

Implementation:

- Read newline-delimited JSON task files where each task has `id`/`task_id`
  and `instruction`/`prompt`.
- Report structured diagnostics for unreadable files, invalid JSON lines,
  non-object lines, missing task ids, missing instructions, and empty corpora.

Acceptance:

- A task JSONL file can be parsed into normalized task ids and instructions.
- Invalid task corpora fail before any harness export is emitted.

### AMF-BENCH-010 ClawBench JSONL Harness Export

Status: implemented.

Goal: let external ClawBench-style runners consume AgentMakefile-selected
harness bundles one task at a time.

Implementation:

- Add `agentmf clawbench export-jsonl`.
- Add `agentmf.clawbench.create_clawbench_jsonl_export`.
- Reuse the ClawBench task/corpus reader from AMF-BENCH-009.
- Emit one compact `clawbench_harness_export` object per output line.
- Support stdout by default and `--out --write` for file output.

Acceptance:

- A task JSONL file can be converted into a JSONL stream of AgentMakefile
  harness bundles.
- Each output line is independently parseable by an external runner.
- Export remains model/tool execution free.

### AMF-BENCH-011 Host Execution Adapter Contract

Status: implemented.

Goal: define the JSONL boundary between AgentMakefile's harness-selection layer
and a host runner that executes ClawBench tasks.

Implementation:

- Add `agentmf clawbench adapter-contract`.
- Add `agentmf.clawbench.create_clawbench_host_adapter_contract`.
- Define required input fields for `clawbench_harness_export` records.
- Define required and optional output fields for
  `clawbench_external_runner_result` records.
- Keep the contract execution-free; it describes external runner IO only.

Acceptance:

- A host adapter can discover required ClawBench input and result fields from
  the CLI.
- The contract explicitly separates AgentMakefile harness selection from model
  execution, tool execution, browser/runtime instrumentation, and scoring.

### AMF-BENCH-012 External Runner Integration

Status: implemented.

Goal: import real external runner result JSONL so AgentMakefile can summarize
score-facing ClawBench metrics after a host adapter executes tasks.

Implementation:

- Add `agentmf clawbench import-results`.
- Add `agentmf.clawbench.create_clawbench_result_summary`.
- Accept both flat result records (`task_id`, `pass`, metrics) and nested
  result records (`task.id`, `execution.pass`, metrics).
- Summarize result count, pass count, pass rate, average cost, average wall
  time, average total tokens, tool calls, denied tool calls, and stable prefix
  hashes.

Acceptance:

- External runner JSONL can be imported without re-running tasks.
- Score summaries are machine-readable JSON for benchmark comparison scripts.
- Invalid result files fail with structured diagnostics.

### AMF-BENCH-013 SWE-bench Task/Corpus Reader

Status: implemented.

Goal: read local SWE-bench Lite-style task subsets as newline-delimited JSON so
AgentMakefile can benchmark coding-harness selection against repository issue
tasks without requiring a full dataset download in the first slice.

Implementation:

- Read newline-delimited JSON task files where each task has `instance_id`,
  `repo`, `base_commit`, and `problem_statement`.
- Preserve optional SWE-bench fields such as `patch`, `test_patch`,
  `hints_text`, `version`, `FAIL_TO_PASS`, and `PASS_TO_PASS` when present.
- Report structured diagnostics for unreadable files, invalid JSON lines,
  non-object lines, missing required task fields, empty corpora, and invalid
  subset limits.

Acceptance:

- A SWE-bench Lite subset JSONL file can be parsed into normalized coding task
  records.
- Invalid task corpora fail before any harness export is emitted.

### AMF-BENCH-014 SWE-bench Lite Subset JSONL Harness Export

Status: implemented.

Goal: let external SWE-bench-style runners consume AgentMakefile-selected
coding harness bundles one instance at a time.

Implementation:

- Add `agentmf swebench export-jsonl`.
- Add `agentmf.swebench.create_swebench_jsonl_export`.
- Reuse `agentmf plugin payload` with each instance `problem_statement` as the
  routing request.
- Emit one compact `swebench_harness_export` object per output line.
- Support stdout by default, `--out --write` for file output, and `--limit` for
  small SWE-bench Lite smoke subsets.

Acceptance:

- A local SWE-bench Lite-style task JSONL file can be converted into a JSONL
  stream of AgentMakefile harness bundles.
- Each output line includes SWE-bench instance metadata, selected targets,
  selected skills, selected pipeline operations, stable prefix hash, guards,
  permissions, fallbacks, and output contracts.
- Export remains model/tool execution free.

### AMF-BENCH-015 SWE-bench Deterministic Comparison Report

Status: implemented.

Goal: make AgentMakefile's harness-management advantage visible before running
an expensive SWE-bench execution adapter.

Implementation:

- Add `agentmf swebench compare`.
- Add `agentmf.swebench.create_swebench_comparison_report`.
- Compare selected SWE-bench task harness bundles against deterministic
  baselines: `agents-md`, `claude-md`, `skills-index`, `baseline-file`, and
  `none`.
- Report selected targets, stable prefix hashes, stable prefix hash reuse,
  average selected stable-prefix tokens, baseline token sizes, and average
  savings against each baseline.
- Render JSON or Markdown reports.

Acceptance:

- A local SWE-bench Lite subset can produce an execution-free comparison report.
- The report shows whether selected AgentMakefile stable prefixes are smaller
  than all-in-one or index-style baselines.
- The report records cache-friendly stable prefix reuse across tasks.

### AMF-BENCH-016 SWE-bench Execution Adapter Contract

Status: implemented.

Goal: define the JSONL boundary between AgentMakefile's harness-selection layer
and an external SWE-bench runner that performs model execution, repository
checkout, patch application, and verification.

Implementation:

- Add `agentmf swebench adapter-contract`.
- Add `agentmf.swebench.create_swebench_execution_adapter_contract`.
- Define required input fields for `swebench_harness_export` records.
- Define required and optional output fields for `swebench_execution_result`
  records.
- Keep the command execution-free; it describes external runner IO only.

Acceptance:

- A SWE-bench adapter can discover required harness input and result fields
  from the CLI.
- The contract explicitly separates AgentMakefile harness selection from model
  calls, tool execution, repository mutation, test execution, and scoring.

### AMF-BENCH-017 SWE-bench Result Importer

Status: implemented.

Goal: import external SWE-bench execution result JSONL so AgentMakefile can
summarize pass-rate-facing metrics after a runner executes tasks.

Implementation:

- Add `agentmf swebench import-results`.
- Add `agentmf.swebench.create_swebench_result_summary`.
- Accept both flat result records (`instance_id`, `resolved`, metrics) and
  nested result records (`task.instance_id`, `execution.resolved`, metrics).
- Summarize result count, resolved count/rate, patch applied count/rate, tests
  passed count/rate, average cost, average wall time, average total tokens,
  cost per resolved task, tool calls, denied tool calls, and stable prefix
  hashes.

Acceptance:

- External runner JSONL can be imported without re-running tasks.
- Invalid result files fail with structured diagnostics.
- The summary exposes pass-rate and cost metrics for later benchmark reports.

### AMF-BENCH-018 SWE-bench Pass-Rate Report

Status: implemented.

Goal: render an execution-layer report that pairs external SWE-bench results
with AgentMakefile's deterministic harness comparison artifacts.

Implementation:

- Add `agentmf swebench pass-report`.
- Add `agentmf.swebench.create_swebench_pass_rate_report`.
- Render JSON or Markdown pass-rate reports.
- Include optional baseline comparison report path for provenance.

Acceptance:

- Imported SWE-bench execution results can produce a human-readable pass-rate
  report.
- The report includes resolved rate, tests-passed rate, patch-applied rate,
  cost per resolved task, per-instance result rows, and stable-prefix evidence.

### AMF-BENCH-019 Official SWE-bench Predictions JSONL Exporter

Status: implemented.

Goal: convert external AgentMakefile-host execution results into the official
SWE-bench predictions JSONL format consumed by upstream `run_evaluation`.

Implementation:

- Add `agentmf swebench predictions`.
- Add `agentmf.swebench.create_swebench_predictions_export`.
- Emit one JSONL record per result with `instance_id`,
  `model_name_or_path`, and `model_patch`.
- Accept patches from inline `model_patch`, inline `patch`, or `patch_path`.
- Keep output execution-free; this command only prepares official evaluator
  input.

Acceptance:

- External result streams can be converted into upstream-compatible
  predictions JSONL.
- Missing instance ids, model names, and patches fail with structured
  diagnostics.

### AMF-BENCH-020 Official SWE-bench Run Command Generator

Status: implemented.

Goal: produce a reproducible command line for the official SWE-bench evaluator
without running Docker, spending tokens, or mutating repositories.

Implementation:

- Add `agentmf swebench official-command`.
- Add `agentmf.swebench.create_swebench_official_run_command`.
- Emit the command array and shell-quoted command text for
  `python -m swebench.harness.run_evaluation`.
- Support dataset profile, predictions path, run id, split, max workers, and
  optional instance ids.

Acceptance:

- Users can copy or script the official evaluator command for AgentMakefile
  predictions.
- Command generation remains side-effect free.

### AMF-BENCH-021 Official SWE-bench Report Importer

Status: implemented.

Goal: import the official SWE-bench schema-v2 run report so AgentMakefile can
compare pass-rate evidence with deterministic harness-management metrics.

Implementation:

- Add `agentmf swebench import-official-report`.
- Add `agentmf.swebench.create_swebench_official_report_summary`.
- Parse report fields such as `submitted_instances`, `completed_instances`,
  `resolved_instances`, `empty_patch_instances`, and `error_instances`.
- Report resolved, completion, and error rates over submitted instances.
- Preserve submitted, completed, resolved, unresolved, empty-patch, and error
  id lists.

Acceptance:

- Official SWE-bench report JSON can be imported after an external evaluator
  run.
- Invalid or incomplete report files fail with structured diagnostics.

### AMF-BENCH-022 Lite/Verified Benchmark Profiles

Status: implemented.

Goal: make official Lite and Verified dataset selection explicit and reusable
across predictions export and command generation.

Implementation:

- Add `SWE_BENCH_PROFILES` with `lite` and `verified` entries.
- Map `lite` to `princeton-nlp/SWE-bench_Lite`.
- Map `verified` to `princeton-nlp/SWE-bench_Verified`.
- Use the selected profile in predictions metadata and official command
  generation.

Acceptance:

- CLI commands expose `--dataset lite|verified`.
- JSON payloads include the selected profile and official dataset name.

### AMF-BENCH-023 Official SWE-bench Dry-Run Adapter Plan

Status: implemented.

Goal: make official Lite/Verified evaluation a deliberate external step by
adding a dry-run adapter plan before any full 300/500-task run.

Implementation:

- Add `agentmf swebench official-dry-run`.
- Add `agentmf.swebench.create_swebench_official_adapter_plan`.
- Read and validate official predictions JSONL records with `instance_id`,
  `model_name_or_path`, and `model_patch`.
- Report submitted prediction count, model names, first instance ids, selected
  profile, and official profile size.
- Emit a smoke command limited to the first `--smoke-limit` prediction ids.
- Emit a full command preview without executing it.
- Mark the payload and both commands as execution-disabled.

Acceptance:

- Users can inspect exactly what would run before invoking the official
  evaluator.
- The first recommended path is a smoke subset, not a full Lite or Verified
  run.
- No Docker, repository checkout, model call, or test execution happens inside
  AgentMakefile.

## Evolution and Skill Workshop Tasks

The evolution line is specified in
[agentmf_evolution_skill_workshop_spec.md](agentmf_evolution_skill_workshop_spec.md).
It turns selection traces, benchmark reports, registry metadata, and user
corrections into reviewable AgentMakefile candidate patches. The workflow must
remain evidence-driven, reproducible, reviewable, and reversible.

### AMF-EVO-001 Evolution Evidence Store

Status: implemented.

Goal: add an append-only evidence store for selection traces, benchmark
outcomes, user corrections, registry scans, and plugin payload summaries.

Implementation:

- Add a JSONL evidence record schema with event id, timestamp, source, request
  fingerprint, selected target, selected skills, outcome summary, and artifact
  references.
- Add redaction rules so secrets, tokens, private keys, `.env` contents, and
  raw proprietary prompts are not persisted.
- Add a write path under `.agentmf/evolution/evidence/`.
- Add `agentmf evo evidence add`.
- Support `openclaw_import` as the first concrete source, turning importer
  curator evidence into registry evidence records.
- Add diagnostics for invalid source type and write failures.

Acceptance:

- Evidence can be recorded from an OpenClaw importer payload without modifying
  canonical AgentMakefile sources.
- Evidence records are deterministic after redaction.
- Secret-looking fields are redacted before write.

### AMF-EVO-002 Skill Workshop Proposal Format

Status: implemented.

Goal: define a machine-readable proposal format for human-reviewable
AgentMakefile improvements.

Implementation:

- Add a proposal JSON schema with proposal id, title, scope, evidence refs,
  change list, evaluation commands, and promotion state.
- Add a markdown report renderer for workshop proposals.
- Support proposal status values such as `candidate`, `rejected`, `accepted`,
  and `superseded`.
- Add `agentmf evo proposal create`.
- Load evidence records from JSONL evidence files.
- Write `.proposal.json` and `.md` report files under
  `.agentmf/evolution/candidates/` only when `--write` is set.
- Keep patch generation and source mutation out of this milestone.

Acceptance:

- A candidate proposal can explain what would change, why it was proposed, and
  which evidence supports it.
- Proposal files can be reviewed without reading raw traces.
- Invalid promotion statuses are rejected with stable diagnostics.

### AMF-EVO-003 AgentMakefile Candidate Patch Generator

Status: implemented (all spec patch classes plus `prune_match_terms`).

Goal: generate minimal unified diffs against AgentMakefile module sources from
validated proposals.

Implementation:

- Support patch classes: `add_target`, `update_match_terms`, `add_dependency`,
  `split_module`, `merge_duplicate_targets`, `deprecate_skill`,
  `add_registry_metadata`, `add_benchmark_case`, `update_permission_guard`,
  and `prune_match_terms`.
- Emit candidate patches under `.agentmf/evolution/candidates/`.
- Preserve local module formatting as much as possible.
- Refuse to rewrite all generated modules unless the proposal explicitly
  declares a module split or normalization operation.
- Add `agentmf evo patch generate`.

Implemented scope:

- All ten supported patch classes ship with focused tests covering
  candidate-only mutation (canonical sources stay untouched).
- `merge_duplicate_targets` runs across modules via a global
  relative_source map (cross-module duplicates).
- `prune_match_terms` is the additional dual to `update_match_terms` —
  retire overly-broad triggers that cause false positives.

Acceptance:

- Candidate patches are small, reviewable, and tied to a proposal id.
- Patch generation is deterministic for a fixed evidence bundle and compiler
  version.
- Canonical AgentMakefile sources are not modified by patch generation.

### AMF-EVO-004 Compile/Evaluate/Promote Loop

Status: implemented (all five spec gates wired into `agentmf evo evaluate`
plus `agentmf evo promote`).

Goal: compile and evaluate candidate patches before promotion.

Implementation:

- Apply candidate patches in an isolated evolution worktree or temporary source
  directory.
- Run `agentmf validate` on touched AgentMakefile sources.
- Compile at least one prompt backend and one skill backend when affected.
- Run deterministic selector tests for changed request examples.
- Run configured benchmark smoke tests when routing behavior changes.
- Emit a promotion report with commands, results, artifact hashes, and residual
  risks.
- Add `agentmf evo evaluate` and `agentmf evo promote`.

Implemented scope:

- `agentmf evo evaluate` writes candidate AgentMakefile files into an isolated
  workspace whose `<parent>/<basename>` layout disambiguates absolute paths
  sharing the same basename (e.g. multiple category modules named
  `AgentMakefile`).
- Each candidate file is re-parsed via `load_source_with_diagnostics`; failures
  flip `promotion_report.status` to `failed`.
- The compile gate drives each candidate through `compile_agentmakefile`
  with the `agents-fragments` backend; compile errors flip the status.
- The selector-test gate runs `evaluation.selector_tests` (inline
  request/expected_target pairs) against each candidate; misses flip the
  status.
- The benchmark-smoke gate loads
  `evaluation.benchmark_smoke.tasks_file` (JSONL), routes every task
  through the candidates, and checks each task's selected target against
  `evaluation.benchmark_smoke.expected_routes`. Tasks without an entry in
  expected_routes are reported as skipped; a single failing entry flips
  the status.
- `agentmf evo promote` lifts a reviewed proposal's candidate into a target
  tree (preserving the workspace layout) and flips the proposal's
  `promotion.status` to `accepted` once every written file passes re-parse.

Acceptance:

- A candidate can be evaluated without mutating canonical sources.
- Promotion requires explicit user or maintainer approval.

### AMF-EVO-005 Dream Mode Dry-Run

Status: implemented (4/4 spec detectors).

Goal: add an offline mode that proposes improvements from evidence without
editing canonical AgentMakefile files.

Implementation:

- Add a dry-run command that reads `.agentmf/evolution/evidence/`.
- Detect recurring failed selections, duplicate skills, missing match terms,
  and drifted permissions.
- Emit proposal JSON, markdown report, and optional patch candidate.
- Mark all output as `candidate` and `requires_review`.
- Add `agentmf evo dream run`.

Implemented scope:

- Detector 1 — `_dream_openclaw_duplicates`: per-evidence-file curator
  invocation producing `merge_duplicate_targets`.
- Detector 2 — `_dream_recurring_routing_gaps`: groups `plugin_payload`
  failures by `request_fingerprint` and emits
  `investigate_recurring_routing_gap` once a threshold of >=2 is hit.
- Detector 3 — `_dream_missing_match_terms`: consumes `user_feedback`
  evidence, emits combined `update_match_terms` + (when an
  `actual_target` is reported and carries broad single-word triggers)
  `prune_match_terms`.
- Detector 4 — `_dream_drifted_permissions`: groups benchmark
  `denied_tool_calls` by (target, tool, pattern) and emits
  `investigate_permission_drift` at >=2 occurrences.

Acceptance:

- Dream mode can run unattended but only writes under `.agentmf/evolution/`.
- No installed skills, generated guidance files, or canonical AgentMakefile
  modules are modified.

### AMF-EVO-006 OpenClaw Large Skill Ecosystem Curator

Status: implemented for the duplicate + missing-term path; trust /
heavy-tool / benchmark-case suggester detectors pending (see Implemented
scope).

Goal: use the evolution loop to curate large imported skill ecosystems such as
OpenClaw instead of loading thousands of skills as a flat index.

Implementation:

- Analyze imported skill modules by category, source, trust metadata, tool
  requirements, match terms, and content hash.
- Detect duplicate or overlapping skills.
- Propose category splits, target merges, match-rule improvements, trust
  annotations, and benchmark cases.
- Preserve source registry metadata where available.
- Add `agentmf evo openclaw curate`.

Implemented scope:

- `agentmf evo openclaw curate` produces `merge_duplicate_targets`
  proposals from OpenClaw `duplicate_original_names` evidence; flows
  end-to-end through evaluate + promote so a real corpus is curated on
  disk (per-machine, gitignored under `modules/openclaw-curated/`).
- The dream `missing_match_terms` detector closes the routing-precision
  half: it raises the routing baseline from 13/29 to 29/29 ground-truth
  correct on the 37-task probe set (`demos/evo-feedback-loop-demo/run.py`).
- The patch class set covers trust/provenance annotation
  (`add_registry_metadata`) and benchmark cases (`add_benchmark_case`),
  but no detector yet emits these — they're available for hand-authored
  proposals only.
- Heavy or unsafe tool requirement warnings are not yet detected.
- Category module suggestions remain a future task (OpenClaw importer
  already splits modules per category at scan time).

## Post-MVP Runtime Work

These tasks should not block compiler milestones:

- Provider-backed tool-call interception beyond the current contract.
- Host OS sandbox integration beyond prototype preflight checks.
- External fallback actions beyond internal no-op execution.

## Recommended Execution Order

Completed:

- AMF-P0-001 trace output.
- AMF-P0-002 generated file ownership tests.
- AMF-P0-003 target metadata and dependency validation.
- AMF-P0-004 CI.
- AMF-P0-005 developer documentation.
- AMF-P0-006 snapshot fixtures.
- AMF-M1-001 backend capability warnings.
- AMF-M1-002 shared skill rendering.
- AMF-M1-003 `claude-skill` backend.
- AMF-M1-004 `codex-skill` backend.
- AMF-M1-004A `skills-index` backend.
- AMF-M1-005 soft permission tables.
- AMF-M1-006 Karpathy default compile.
- AMF-M2-000 Superpowers module coverage.
- AMF-M2-001 namespaced includes.
- AMF-M2-002 deterministic merge diagnostics.
- AMF-M2-003 locked policy rules.
- AMF-M2-004 target composition.
- AMF-M2-005 local composition demo.
- AMF-M2.5-001 target fragment backend.
- AMF-M2.5-002 fragment manifest and hashes.
- AMF-M2.5-003 fragment selection and link plan.
- AMF-M3-001 permission conflict resolution.
- AMF-M3-002 permission glob pattern validation.
- AMF-M3-003 `claude-code` backend.
- AMF-M3-004 `opencode` backend.
- AMF-M3-005 unknown repo hard rails demo.
- AMF-M4-001 runtime dry-run skeleton.
- AMF-M4-002 prompt link step.
- AMF-M4-003 guard evaluation dry-run.
- AMF-M4-004 deterministic final prompt generation with `agentmf prompt`.
- AMF-M4-005 plan input for runtime prompt generation.
- AMF-M4-006 context collection for runtime prompt generation.
- AMF-M4-007 provider adapter for one-shot `agentmf ask`.
- AMF-M4-008 permission dry-run for proposed tool calls.
- AMF-M4-009 gated tool loop prototype.
- AMF-M4-010 output validation dry-run.
- AMF-M4-011 fallback handling for blocked tool calls.
- AMF-M4-012 sandbox profile metadata for exec.
- AMF-M4-013 richer output schema validation.
- AMF-M4-014 sandbox enforcement integration.
- AMF-M4-015 fallback execution prototype.
- AMF-M4-016 provider-backed tool-call interception contract.
- AMF-M4-017 full JSON Schema validator integration.
- AMF-M4-CLI-000 prompt-aware runtime CLI spec.
- AMF-PAD-001 plugin adapter protocol spec.
- AMF-PAD-002 plugin payload builder.
- AMF-PAD-003 `agentmf plugin payload` command.
- AMF-PAD-004 plan and context inputs.
- AMF-PAD-005 host profiles.
- AMF-PAD-006 example adapter docs.
- AMF-PAD-007 selected skills in plugin payload.
- AMF-PAD-007A selection trace in plugin payload.
- AMF-PAD-008 Superpowers skill routing graph.
- AMF-PAD-009 skill import and selection optimization.
- AMF-PAD-010 request normalization and semantic matching.
- AMF-PAD-011 plugin install skill index bootstrap.
- AMF-PAD-012 skill-match-derived target routing.
- AMF-PAD-013 system skill sync and host integration instructions.
- AMF-HARNESS-001 target pipeline IR.
- AMF-HARNESS-002 selected pipeline in plugin payload.
- AMF-BENCH-001 Harness Benchmark Suite Spec.
- AMF-BENCH-008 ClawBench Harness Export.
- AMF-BENCH-009 ClawBench Task/Corpus Reader.
- AMF-BENCH-010 ClawBench JSONL Harness Export.
- AMF-BENCH-011 Host Execution Adapter Contract.
- AMF-BENCH-012 External Runner Integration.
- AMF-BENCH-013 SWE-bench Task/Corpus Reader.
- AMF-BENCH-014 SWE-bench Lite Subset JSONL Harness Export.
- AMF-BENCH-015 SWE-bench Deterministic Comparison Report.
- AMF-BENCH-016 SWE-bench Execution Adapter Contract.
- AMF-BENCH-017 SWE-bench Result Importer.
- AMF-BENCH-018 SWE-bench Pass-Rate Report.
- AMF-BENCH-019 Official SWE-bench Predictions JSONL Exporter.
- AMF-BENCH-020 Official SWE-bench Run Command Generator.
- AMF-BENCH-021 Official SWE-bench Report Importer.
- AMF-BENCH-022 Lite/Verified Benchmark Profiles.
- AMF-BENCH-023 Official SWE-bench Dry-Run Adapter Plan.
- AMF-OPENCLAW-001 Local Skill Scanner.
- AMF-OPENCLAW-002 Modular AgentMakefile Renderer.
- AMF-OPENCLAW-003 Category Split + Root Index.
- AMF-OPENCLAW-004 Selection Smoke Test.
- AMF-OPENCLAW-005 Curator Evidence Export.
- AMF-EVO-001 Evolution Evidence Store.
- AMF-EVO-002 Skill Workshop Proposal Format.
- AMF-EVO-003 AgentMakefile Candidate Patch Generator (all spec classes + `prune_match_terms`).
- AMF-EVO-003B Additional Patch Classes (folded into AMF-EVO-003 above).
- AMF-EVO-004 Compile/Evaluate/Promote Loop (all five spec gates wired into `agentmf evo evaluate` + `agentmf evo promote`).
- AMF-EVO-004B Compile and Benchmark Candidate Gates (folded into AMF-EVO-004 above).
- AMF-EVO-005 Dream Mode Dry-Run (4/4 detectors: openclaw duplicates, recurring routing gaps, missing match terms, drifted permissions).
- AMF-EVO-005B Additional Dream Mode Detectors (folded into AMF-EVO-005 above).
- AMF-EVO-006 OpenClaw Large Skill Ecosystem Curator (duplicate + missing-term path closed end-to-end; routing baseline 13/29 -> 29/29 via the closed-loop demo).

Next:

- AMF-PAD-014 Multi-Source Guidance Ingestion (CLI wiring + four source readers; library facade `guidance_scanner` already shipped).
- AMF-EVO-006B OpenClaw Trust and Overlap Analysis (detector emitting `add_registry_metadata`; heavy/unsafe-tool warning; category-split suggester; benchmark-case suggester emitting `add_benchmark_case`).
- AMF-BENCH-002 Suite File Parser.
- AMF-BENCH-003 Deterministic Suite Runner.
- AMF-BENCH-004 Report Writer.
- AMF-BENCH-005 Demo Suite.

This order has reconciled the implemented compiler roadmap tasks and introduced the first runtime planning/linking tasks through the current `agentmf exec` contract. The next step should be a new milestone decision: either deepen provider-backed execution, package host adapters, or prepare the project for release.
