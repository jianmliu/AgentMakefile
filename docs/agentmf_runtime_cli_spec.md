# AgentMakefile Runtime CLI Spec

Status: proposed.

Date: 2026-05-25.

## Summary

AgentMakefile can eventually grow from a compiler into a prompt-aware
coding-agent shell.
The compiler remains responsible for parsing, validating, normalizing,
compiling, selecting, and linking AgentMakefile rules. The runtime CLI adds a
thin execution layer that turns a user request plus optional plan into a
dynamic, module-aware prompt prefix before calling a model or running an agent
tool loop.

The preferred near-term path is plugin-first, not full-runtime-first. The
generic plugin adapter is specified in
[agentmf_plugin_adapter_spec.md](agentmf_plugin_adapter_spec.md). Existing agent
CLIs should remain responsible for model calls, streaming, tool loops,
approvals, and sandboxing while AgentMakefile produces the selected prompt
payload.

The key idea is:

```text
user request + optional plan + repo state
  -> AgentMakefile target selection
  -> target fragment linking
  -> stable prompt prefix
  -> volatile task context suffix
  -> model call or tool loop
```

`AgentMakefile` is the source of stable agent behavior. The plan is task
context, not part of the stable prefix.

There is also a reverse-input mode for existing skill ecosystems:

```text
existing SKILL.md packages
  -> agentmf plugin install
  -> generated AgentMakefile skill-index module
  -> agentmf plugin payload
  -> selected skills + selection_trace + stable prefix
  -> host-owned model/tool runtime
```

This mode makes skill selection optimization a first-class runtime use case.
Instead of loading an all-in-one skill index, a host can ask AgentMakefile which
skill-backed targets match the current request, inspect the explanation, and
load only the relevant native skill artifacts. `agentmf skills scan` remains
the lower-level import primitive; `agentmf plugin install` wraps it with
install-time model instructions for plugin hosts.

## Goals

- Let users and host agents invoke AgentMakefile as a prompt assembly layer, not
  only as a compiler.
- Let hosts import existing `SKILL.md` package trees into generated
  AgentMakefile skill-index modules.
- Select relevant modules, targets, policies, skills, guards, and permissions
  from the current user request.
- Return explainable skill selection data so hosts can debug and optimize
  request-specific skill loading.
- Match requests through deterministic normalization, built-in translation or
  alias expansion, and lightweight semantic token overlap before falling back
  to a no-match diagnostic.
- Link only the prompt fragments needed for the selected target closure.
- Keep stable prompt-prefix material deterministic and cache-friendly.
- Keep volatile inputs such as the user request, implementation plan, active
  files, diffs, and tool observations outside the stable prefix.
- Provide dry-run visibility before any model call or tool execution.
- Make prompt assembly testable without requiring a live model provider.
- Keep hard enforcement incremental: plan first, then guards, then permission
  checks, then tool interception.

## Non-Goals

- Replacing every existing coding-agent CLI in the first runtime milestone.
- Owning model provider auth, streaming, terminal UI, or tool approval UX before
  the plugin adapter path is proven.
- Building a full terminal UI before prompt assembly is proven.
- Treating plans as generated AgentMakefile modules.
- Loading all modules or all generated Markdown files for every request.
- Executing untrusted repository code without explicit permission policy support.

## Plugin-First Runtime Path

The runtime CLI concepts should be introduced through a plugin adapter first:

```text
Codex CLI / Claude Code / Cursor / OpenCode
  -> agentmf plugin payload
  -> selected prompt prefix + volatile context + trace
  -> host-owned model/tool runtime
```

This keeps AgentMakefile focused on its strongest early value: cross-platform
target selection, prompt linking, module reuse, and traceable prompt-size
savings. Commands such as `agentmf ask`, `agentmf chat`, and `agentmf exec` are
later conveniences built on the same payload assembly path.

## Concepts

### User Request

The natural-language task from the user. It is used for target selection and is
included in volatile context.

### Plan

An optional implementation plan, usually a Markdown file or inline text. The
plan describes the concrete work for this session. It should influence target
selection and execution, but it should not be compiled into stable prompt
fragments.

### Stable Prompt Prefix

The deterministic prompt material generated from selected AgentMakefile
targets, dependencies, policies, skills, permissions, output contracts, and
fallback behavior.

### Volatile Task Context

Request-specific material appended after the stable prefix:

- current user request
- selected plan content
- active files
- git status and diff
- recent test output
- runtime trace snippets
- tool observations

### Runtime Plan

The structured execution plan produced by `agentmf run --dry-run`. It includes
selected targets, target closure, linked prompt fragments, guard contracts,
permission contracts, output contracts, and trace metadata.

### Provider Adapter

A small interface for model calls. The first implementation may support only
prompt generation without a live provider. Later adapters can call OpenAI,
Anthropic, local models, or an existing agent runtime.

## Command Surface

### `agentmf prompt`

Generate the final prompt payload without calling a model.

```bash
agentmf prompt "fix failing tests" --format text
agentmf prompt --request "review this repo" --plan docs/plans/review.md --format json
agentmf prompt --request "fix failing tests" --include-git-status --include-git-diff --format json
```

Responsibilities:

- load AgentMakefile
- select target from request and explicit targets
- link selected prompt fragments
- collect request-specific volatile context, including optional plan content
- emit the final prompt payload and trace

This is the first user-facing runtime command because it is deterministic and
testable.

### `agentmf ask`

Run a one-shot provider call with the generated prompt, without a tool loop.

```bash
agentmf ask "summarize the next task" --provider echo
```

Responsibilities:

- reuse the prompt assembly path
- send one provider request
- print the response
- write a trace when requested

The first provider adapter is `echo`, a deterministic local adapter for testing
prompt assembly and response plumbing without external network calls. OpenAI,
Anthropic, local model, and host-runtime adapters can be added behind the same
provider interface later.

### `agentmf chat`

Start an interactive session that regenerates or reuses the stable prefix as
the conversation evolves.

```bash
agentmf chat
```

Responsibilities:

- keep stable prefix chunks reusable across turns
- append per-turn volatile context
- expose selected target and prompt-size diagnostics

### `agentmf exec`

Run a coding-agent tool loop.

```bash
agentmf exec --target project.default --tool-call "bash:pytest -q" --apply
```

Responsibilities:

- evaluate guards
- enforce permissions before tool calls
- run allowed tools
- collect observations
- validate output contracts
- execute fallback behavior when blocked

`exec` should remain out of scope until prompt assembly, guard dry-run, and
permission dry-run are stable.
The initial prototype accepts explicit `--tool-call TOOL:INPUT` values and
requires `--apply`; autonomous model-driven tool selection remains future work.

## Shared Options

```text
--file AgentMakefile
--request TEXT
--plan PATH
--target NAME
--backend agents-fragments|claude-fragments
--tool-call TOOL:INPUT
--output-json JSON
--sandbox-profile none|read-only|workspace-write
--execute-fallbacks
--format text|json
--trace PATH
--dry-run
```

Provider-backed commands add:

```text
--provider NAME
--model NAME
--temperature FLOAT
--max-output-tokens INT
```

Context options may add:

```text
--include-active-files
--include-git-diff
--include-git-status
--context-file PATH
```

## Runtime Data Flow

1. Load the root `AgentMakefile`.
2. Resolve includes and normalize the merged IR.
3. Read optional plan input.
4. Select target from explicit `--target`, request matching, and optional plan
   signals.
5. Resolve target dependency closure.
6. Compile or reuse prompt fragments.
7. Link selected fragments into a stable prompt prefix.
8. Collect volatile task context.
9. Build final prompt payload.
10. Optionally call a provider.
11. Optionally run a guarded tool loop.
12. Emit trace output.

## Prompt Layout

The final prompt should be laid out to maximize cache reuse:

```text
[stable prefix]
AgentMakefile target fragment closure
selected policies
selected skills
permission guidance
output contracts
fallback behavior

[volatile suffix]
user request
plan content
active file summaries
git status
git diff
recent command output
runtime trace
```

The stable prefix must be deterministic for a given AgentMakefile IR, backend,
target selection, and compiler version. Volatile suffix content may change on
every request.

## Plan Input Semantics

Plans are not AgentMakefile source code. A plan should be treated as runtime
task context with two uses:

- selection signal: terms in the plan can help pick a target such as
  `code.change`, `methodology.debug`, or `review.task`
- execution context: selected steps can refer to the plan while implementing or
  reviewing code

The plan should not be embedded into target fragments or fragment hashes. This
keeps prompt objects cacheable across tasks.

## Module Role

Modules are reusable behavior libraries. The runtime CLI should not know
Superpowers, Karpathy, OMO, or security workflows directly. It should consume
whatever the root AgentMakefile imports:

```text
modules/superpowers/AgentMakefile
modules/karpathy/AgentMakefile
modules/unknown-repo-security/AgentMakefile
modules/oh-my-openagent/AgentMakefile
```

The runtime then selects from the normalized target graph.

## Trace Output

Runtime commands should be able to emit trace records:

```json
{
  "request": "review this repo",
  "plan": "docs/plans/review.md",
  "selected_targets": ["repo.security_review"],
  "target_closure": ["repo.inspect", "repo.security_review"],
  "linked_fragments": [".agentmf/fragments/agents/repo.security_review.md"],
  "stable_prefix_hash": "sha256:...",
  "stable_prefix_chars": 4200,
  "volatile_context_chars": 3100,
  "guards": [{"name": "do_not_run_untrusted_code", "status": "planned"}],
  "permissions": [{"tool": "bash", "pattern": "npm install*", "action": "deny"}]
}
```

Trace output is required for debugging target selection, prompt-size savings,
guard decisions, and permission enforcement.

## Security Model

Runtime CLI execution should be conservative by default:

- `prompt` never calls a model or runs tools.
- `ask` calls a model but never runs tools.
- `chat` calls a model but should not run tools unless explicitly enabled.
- `exec` may run tools only after permission and guard evaluation.
- Repository-local AgentMakefile input is trusted configuration, but remote
  modules and includes require provenance checks before default execution.
- Destructive commands, broad filesystem writes, network operations, and
  credential access should require explicit allow rules or user approval.

## Milestones

### AMF-M4-003 Guard Evaluation Dry-Run

Status: implemented.

Evaluate target and policy guards as structured runtime contracts without
executing workflow steps. Dry-run output records the guard source, target,
policy when applicable, guard name, and planned status.

### AMF-M4-004 `agentmf prompt`

Status: implemented.

Add deterministic final prompt generation from request, linked stable prefix,
and volatile request context.

### AMF-M4-005 Plan Input

Status: implemented.

Add `--plan` to runtime commands and include plan content only in volatile
context.

### AMF-M4-006 Context Collection

Status: implemented.

Add configurable collection for git status, git diff, and explicit context
files. Active editor files are represented by explicit `--context-file` inputs
until host adapters can provide active-file metadata directly.

### AMF-M4-007 Provider Adapter

Status: implemented.

Add a provider abstraction and the first one-shot `agentmf ask` implementation.
The first provider is the deterministic local `echo` adapter; external model
providers remain future work.

### AMF-M4-008 Permission Dry-Run

Status: implemented.

Evaluate permission decisions for proposed tool calls without executing them.
`agentmf run --dry-run --permission-check TOOL:INPUT` records the matched
permission rules, the default or implicit default used when no rule matches,
and the final `allow` / `ask` / `deny` action. When multiple rules match the
same proposed call, the most restrictive action wins.

### AMF-M4-009 Tool Loop Prototype

Status: implemented.

Introduce `agentmf exec` behind an explicit opt-in flag after guards,
permissions, and traces are testable.
The first prototype requires `--apply`, accepts explicit `--tool-call`
arguments, supports the local `bash` tool, and blocks any call whose permission
decision is `ask` or `deny`.

### AMF-M4-010 Output Validation Dry-Run

Status: implemented.

Evaluate proposed output objects against selected target output contracts
without executing workflow steps. `agentmf run --dry-run --output-json JSON`
checks selected target and policy `output_format` entries plus
`output_schema.required` fields, then reports missing fields and valid/invalid
status in `output_validation`.

### AMF-M4-011 Fallback Handling for Blocked Tool Calls

Status: implemented.

When `agentmf exec` blocks a tool call because its permission action is `ask` or
`deny`, the prototype now emits a dry-run `fallback_handling` plan. It maps the
blocked call to selected target `fallback.blocked` actions when available and
does not execute fallback actions automatically.

### AMF-M4-012 Sandbox Profile Metadata

Status: implemented.

Add `agentmf exec --sandbox-profile` metadata for `none`, `read-only`, and
`workspace-write`. The first implementation records requested sandbox posture
in the exec payload; AMF-M4-014 extends this from metadata into prototype
preflight enforcement for supported local tool calls.

### AMF-M4-013 Richer Output Schema Validation

Status: implemented.

Extend output validation beyond required-field checks by evaluating simple
JSON-schema `properties.<field>.type` constraints. The current validator
supports `string`, `array`, `object`, `boolean`, `integer`, `number`, and
`null`, and reports type errors alongside missing fields.

### AMF-M4-014 Sandbox Enforcement Integration

Status: implemented.

Apply sandbox profile decisions inside `agentmf exec` before local tool
execution. The prototype enforces `read-only` by blocking obvious write-like
bash commands such as `touch`, `rm`, `mv`, `cp`, `mkdir`, `tee`, and shell
write redirections even when permission rules would otherwise allow the call.
The `workspace-write` profile allows normal workspace-local writes while
blocking simple write operands that target absolute paths or parent-directory
escapes. This is a local preflight integration layer, not a replacement for a
host OS sandbox.

### AMF-M4-015 Fallback Execution Prototype

Status: implemented.

Add `agentmf exec --execute-fallbacks` to opt into running selected target
`fallback.blocked` actions after a tool call is blocked. The current execution
engine is intentionally internal-only: each fallback action records an
`internal_noop` result so hosts can verify fallback routing and payload shape
without granting fallback actions their own external tool authority.

### AMF-M4-016 Provider-Backed Tool-Call Interception Contract

Status: implemented.

Add a structured `tool_interception` contract to `agentmf exec` payloads. The
contract records the provider identity, the expected host/provider event flow,
each provider tool-call id, the permission and sandbox decisions applied by
AgentMakefile, and the result status that the host would return to the
provider. This keeps the current prototype deterministic while defining the
boundary a real provider-backed loop must honor before executing tools.

### AMF-M4-017 Full JSON Schema Validator Integration

Status: implemented.

Replace the handwritten output-schema type checker with `jsonschema`-backed
validation while preserving the existing `missing_fields` and `type_errors`
compatibility fields. Runtime output validation now also reports
`schema_errors` for full JSON Schema constraints such as `enum`, `minItems`,
`additionalProperties`, and nested `items` schemas.

## Acceptance Criteria

- Users can generate a final prompt from a request without a model call.
- Prompt output separates stable prefix from volatile context in JSON mode.
- The same AgentMakefile target selection produces byte-stable prefix content.
- Plan content changes do not change fragment hashes.
- Runtime trace explains selected targets, fragments, prompt sizes, guards, and
  permissions.
- Provider-backed commands reuse the same prompt assembly path as dry-run
  commands.
- Permission dry-run explains proposed tool-call decisions without executing
  tools.
- Tool execution is available only through the explicitly gated `agentmf exec`
  prototype.
- Output validation dry-run explains missing output contract fields.
- Blocked tool calls report planned fallback actions when configured.
- Exec payloads apply prototype sandbox preflight checks for supported local
  tool calls.
- Output validation reports simple schema type mismatches.
- `agentmf exec --execute-fallbacks` records executed internal fallback results
  for blocked tool calls with configured fallback actions.
- Exec payloads expose a provider tool-call interception contract tying
  provider requests to permission, sandbox, and host result decisions.
- Output validation reports full JSON Schema constraint failures as structured
  schema errors.
