# AgentMakefile Spec Breakdown

This document breaks the design spec into implementation tasks using a Superpowers-style workflow:

1. Define the goal.
2. Inspect current context.
3. Set success criteria.
4. Split work into ordered, testable steps.
5. Track risks and verification for each milestone.

## Goal

Build AgentMakefile from the current MVP 0 prototype into the staged compiler described in `docs/agentsfile_design_spec.md`.

The next implementation work should be incremental: each task should add a narrow behavior, include fixture-driven tests, and keep the CLI usable after every merge.

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
- Backend capability warnings cover permission hard-to-soft downgrades and unsupported native hooks.
- Soft permission guidance is rendered as Markdown tables, and soft backends emit `AMF121` downgrade warnings.
- The Karpathy module exposes a `karpathy-guidelines` skill, so the Karpathy demo default compile emits Markdown, Cursor, Claude skill, and Codex skill outputs.

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
- Docs link from README and the plugin adapter spec.

## Post-MVP Runtime Work

These tasks should not block compiler milestones:

- Host-level tool-call interception.
- Sandbox integration.
- Output validation.
- Fallback execution.

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
- AMF-M4-CLI-000 prompt-aware runtime CLI spec.
- AMF-PAD-001 plugin adapter protocol spec.
- AMF-PAD-002 plugin payload builder.
- AMF-PAD-003 `agentmf plugin payload` command.
- AMF-PAD-004 plan and context inputs.
- AMF-PAD-005 host profiles.
- AMF-PAD-006 example adapter docs.

Next:

1. AMF-M4-010 output validation dry-run.
2. AMF-M4-011 fallback handling for blocked tool calls.

This order has reconciled the implemented compiler roadmap tasks and introduced the first runtime planning/linking tasks. The next runtime work should validate outputs and blocked-call fallback behavior now that prompt assembly, guard dry-run, permission dry-run, provider adapter seams, and a gated tool-loop prototype exist.
