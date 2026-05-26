# AgentMakefile Agent Harness Architecture

Status: proposed.

Date: 2026-05-26.

## Summary

AgentMakefile's near-term product direction is **Option A**:

> AgentMakefile is a portable agent harness specification, compiler, and host
> adapter layer.

It should not initially compete with Codex, Claude Code, Cursor, OpenCode, or
other coding agents as a full standalone runtime. Those hosts should continue
to own model calls, streaming, terminal UI, tool loops, approvals, and platform
sandbox behavior. AgentMakefile should provide the structured harness layer
around them: guidance ingestion, normalized behavior IR, dependency-aware
selection, prompt-prefix assembly, guard and permission contracts, host payloads,
and benchmark evidence.

The standalone runtime path remains valid, but it is a later optional path built
on the same harness interfaces.

## Definition

An **agent harness** is the layer that turns user intent, stable guidance,
runtime context, and host capabilities into a controlled agent execution plan.
For AgentMakefile, the harness owns the reusable behavior graph and the
request-time selection payload. The host agent owns the actual model/tool
session.

AgentMakefile's harness boundary:

- **Owns:** guidance ingestion, AgentMakefile parsing, normalized IR, target and
  skill dependency graph, prompt object compilation, request matching, prompt
  linking, guard contracts, permission contracts, output schemas, fallback
  plans, host adapter payloads, benchmark reporting.
- **Does not own in the near term:** hosted model auth, streaming UI, terminal
  multiplexing, human approval UX, native sandbox enforcement, long-running
  interactive tool loops.
- **May own later:** a standalone `agentmf chat` or `agentmf exec` runtime that
  consumes the same payloads and contracts directly.

## Target Pipeline Model

Each AgentMakefile target defines a **compilable agent harness pipeline**. It is
not a traditional Makefile shell recipe and it is not only a free-text prompt.

A target pipeline can include:

- dependency closure
- selected skills
- policies
- prompt fragments
- context selection rules
- guards
- permission contracts
- tool-call constraints
- fallback behavior
- output contracts

The useful Makefile analogy is the graph and build semantics:

```text
make target
  -> dependencies
  -> shell recipe
  -> file artifact

agent target
  -> dependency closure
  -> skills / policies / context
  -> prompt operations
  -> host execution contract
```

The harness compiler can lower that pipeline into different outputs: Markdown
instructions, native skill packages, prompt fragments, plugin payloads, or
future runtime execution plans. This is why `steps` should be treated as
structured harness operations, not arbitrary shell commands.

## Architecture Layers

### 1. Guidance Sources

Inputs include hand-authored AgentMakefile modules and existing native guidance:

- `AgentMakefile`
- `SKILL.md`
- `AGENTS.md`
- `CLAUDE.md`
- `skills/index.md`
- Cursor rules
- OpenCode configs
- framework Markdown such as Superpowers or Oh My OpenAgent

### 2. Guidance Ingestion

`agentmf guidance scan` converts existing guidance files into a generated
AgentMakefile guidance-index module. `agentmf skills scan` remains the
compatibility path for `*/SKILL.md` directories.

### 3. Harness IR

The normalized IR represents:

- skills
- targets
- dependencies
- policies
- permissions
- guards
- hooks
- fallback behavior
- output schemas
- source provenance

This IR is the main harness data model.

### 4. Compilation Outputs

The compiler emits host-native compatibility artifacts:

- `AGENTS.md`
- `CLAUDE.md`
- `.codex/skills/*/SKILL.md`
- `.claude/skills/*/SKILL.md`
- `skills/index.md`
- Cursor rules
- Claude Code settings/hooks
- OpenCode config
- target fragments under `.agentmf/fragments/`

These files are build artifacts, not the core runtime boundary.

### 5. Request-Time Selection

The selector consumes user request, optional plan, and context signals. It
returns selected targets, dependency closure, selected skills, matched terms,
match scores, and `selection_trace`.

Selection must remain deterministic first: normalization, alias/translation
expansion, and semantic token overlap are preferred before any LLM-assisted
classifier is considered.

### 6. Prompt Assembly

The prompt link step selects stable prompt objects and assembles a cache-friendly
prefix. Volatile context is appended after the stable prefix:

- user request
- plan
- active files
- git diff/status
- tool observations
- runtime trace snippets

This split is central to the token and cache story.

### 7. Guard and Permission Contracts

AgentMakefile can evaluate or emit contracts for:

- guard dry-runs
- command permission checks
- file write permission checks
- sandbox profile metadata
- provider-requested tool-call interception
- output schema validation
- fallback plans for blocked actions

Host adapters can enforce these contracts where the host supports it. The
standalone runtime may enforce them directly later.

### 8. Host Adapter Payload

`agentmf plugin payload` is the near-term harness API. It returns:

- `selected_targets`
- `selected_skills`
- `selected_pipeline`
- `skill_artifacts`
- `selection_trace`
- stable prompt prefix and hash
- volatile context
- permission and guard metadata where available
- host integration instructions

Codex, Claude Code, Cursor, OpenCode, or plugin wrappers can use this payload
before deciding which native skills or instruction fragments to load.

### 9. Observability and Benchmarking

`agentmf benchmark skills` should prove the harness value with deterministic
measurements:

- selected skill closure
- token savings against all-in-one baselines
- stable prefix hashes
- cache stability
- selection match rate against labeled cases
- explainability through match traces

## Data Flows

### Forward Authoring Flow

```text
AgentMakefile module
  -> normalize to harness IR
  -> compile native artifacts and prompt objects
  -> optionally sync generated skills to host
  -> plugin payload selects relevant objects per request
```

### Reverse Import Flow

```text
existing guidance corpus
  -> guidance scan / plugin install
  -> generated guidance-index AgentMakefile
  -> plugin payload selects relevant objects per request
```

### Host Runtime Flow

```text
user request + optional plan + context
  -> agentmf plugin payload
  -> host loads selected skills/fragments
  -> host owns model call, tools, approvals, and UI
```

## Product Boundary

The current product should optimize for:

- structured management of skills and guidance
- deterministic selection and prompt assembly
- cross-platform compilation and sync
- plugin-first host integration
- benchmarkable evidence of better skill loading

The product should not block on:

- building a full agent terminal
- owning provider auth and streaming
- replacing Codex or Claude Code tool loops
- implementing every host's sandbox natively

## Milestones

1. **Harness compiler foundation:** validation, IR, native backends, skill
   outputs, prompt fragments.
2. **Guidance ingestion:** import `SKILL.md`, `AGENTS.md`, `CLAUDE.md`, and
   related guidance into guidance-index modules.
3. **Request-time harness payload:** plugin payload, selected skills, prompt
   link step, volatile context, host profiles.
4. **Host installation and sync:** install-time bootstrap, skill sync, host
   integration instructions.
5. **Benchmark evidence:** token savings, cache stability, selection quality,
   and trace explainability.
6. **Optional standalone runtime:** only after the host-adapter path proves the
   harness APIs.

## Success Criteria

AgentMakefile is succeeding as an agent harness when:

- a project can import existing guidance without rewriting it by hand
- a reusable module can compile into Codex and Claude skill packages
- a host can request a payload and load fewer prompt tokens than an all-in-one
  `AGENTS.md` or `CLAUDE.md`
- selection traces explain why skills or fragments were chosen
- stable prefix hashes stay deterministic across volatile request context
- benchmark reports make the improvement visible

## Design Decision

Choose Option A now:

> Build AgentMakefile as a harness specification, compiler, and host adapter
> layer first.

Keep Option B as future work:

> A standalone `agentmf` agent runtime may be built later, using the same
> harness IR, payloads, permission contracts, and prompt objects.
