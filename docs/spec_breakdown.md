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

Known gaps:

- `--trace` now produces text and JSON compile trace output.
- MVP 1 skill backends are not implemented.
- The Karpathy module is reusable, and the Karpathy demo composes it. The demo default `compile.targets` includes MVP 1 backends, so it currently requires explicit MVP 0 targets.
- Backend capability warnings are not implemented.
- Permission output is included as guidance, but not yet emitted as a formal soft permission table with downgrade warnings.
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

Implementation:

- Validate priority type and range.
- Validate `deps` references point to known targets when used as target dependencies.
- Report dependency cycles.
- Keep compiler-only mode from executing dependency selection.

Acceptance:

- Unknown dependency emits a stable diagnostic.
- Cyclic dependency emits a stable diagnostic.
- Existing fixtures remain valid.

### AMF-P0-004 Add CI

Goal: make repository health visible on push.

Implementation:

- Add `.github/workflows/test.yml`.
- Run tests on Python 3.9 and a current Python version.
- Run `python -m compileall -q src`.

Acceptance:

- GitHub Actions runs on push and PR.
- Local test command remains `PYTHONPATH=src python3 -m pytest -q`.

### AMF-P0-005 Improve Developer Documentation

Goal: make the prototype runnable by someone opening the repo fresh.

Implementation:

- Expand README with install, editable install, test, and demo commands.
- Document why the Karpathy demo needs explicit MVP 0 targets until MVP 1 lands.
- Link this breakdown from README.

Acceptance:

- README contains a short path from clone to successful demo compile.

### AMF-P0-006 Convert Current Assertions Into Snapshot Fixtures

Goal: make generated Markdown changes deliberate.

Implementation:

- Add snapshot files for `claude-md`, `agents-md`, and `cursor-rule`.
- Compare full generated content instead of selected substrings.
- Keep snapshots deterministic.

Acceptance:

- Snapshot tests fail on meaningful generated content changes.

## MVP 1: Skill Compiler and Soft Permissions

### AMF-M1-001 Introduce Backend Capability Warnings

Goal: warn when a backend cannot enforce a requested rail.

Implementation:

- Use `BackendCapabilities` for each backend.
- Add diagnostics for permission/hook downgrades.
- Keep warnings non-fatal for Markdown and skill backends.

Acceptance:

- Cursor and Markdown backends warn when permissions are emitted as soft instructions.
- Tests cover warning text and diagnostic structure.

### AMF-M1-002 Add Shared Skill Rendering

Goal: create one renderer for Claude and Codex skill packages.

Implementation:

- Render skill name, description, when-to-use, guards, procedure, and output requirements.
- Slugify skill names deterministically.
- Preserve namespaces in content but use filesystem-safe paths.

Acceptance:

- A `skills.systematic-debugging` entry renders a complete `SKILL.md`.
- Output paths are deterministic.

### AMF-M1-003 Implement `claude-skill` Backend

Goal: generate Claude skill packages.

Implementation:

- Add backend name `claude-skill`.
- Emit `.claude/skills/<slug>/SKILL.md`.
- Generate one file per skill entry.

Acceptance:

- Karpathy and Superpowers minimal fixtures compile with `--target claude-skill`.
- `test_compile_claude_skill_snapshot.py` passes.

### AMF-M1-004 Implement `codex-skill` Backend

Goal: generate Codex skill packages.

Implementation:

- Add backend name `codex-skill`.
- Emit `.codex/skills/<slug>/SKILL.md`.
- Reuse shared skill rendering with Codex-neutral wording.

Acceptance:

- Karpathy and Superpowers minimal fixtures compile with `--target codex-skill`.
- `test_compile_codex_skill_snapshot.py` passes.

### AMF-M1-005 Emit Formal Soft Permission Tables

Goal: make permission guidance predictable in generated Markdown and skills.

Implementation:

- Render permission defaults and rules as tables.
- Include action values `allow`, `ask`, and `deny`.
- Emit backend downgrade warning when enforcement is soft.

Acceptance:

- `test_permissions_soft_warning.py` passes.
- Unknown repo security fixture visibly renders denied install commands.

### AMF-M1-006 Make Karpathy Default Compile Pass

Goal: remove the need for explicit MVP 0 targets in the Karpathy demo.

Implementation:

- After `claude-skill` and `codex-skill` are implemented, run `agentmf compile --file demos/karpathy/AgentMakefile`.

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

Next:

1. AMF-P0-004 CI.
2. AMF-P0-005 README.
3. AMF-M1-002 shared skill rendering.
4. AMF-M1-003 `claude-skill`.
5. AMF-M1-004 `codex-skill`.
6. AMF-M1-005 soft permission tables.
7. AMF-M1-006 Karpathy default compile.
8. AMF-M2-001 namespaced includes.

This order keeps the compiler usable while moving from the current MVP 0 prototype to the MVP 1 success criterion.
