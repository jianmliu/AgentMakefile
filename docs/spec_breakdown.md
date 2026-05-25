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

## Post-MVP Runtime Work

These tasks should not block compiler milestones:

- Runtime target selection.
- Dependency graph execution.
- Step execution.
- Guard evaluation.
- Tool-call interception.
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

Next:

1. No unreconciled implemented roadmap tasks remain in this breakdown.

This order has reconciled the implemented compiler roadmap tasks currently listed in this breakdown.
