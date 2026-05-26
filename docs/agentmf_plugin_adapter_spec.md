# AgentMakefile Plugin Adapter Spec

Status: proposed.

Date: 2026-05-25.

## Summary

AgentMakefile should first integrate with existing coding-agent CLIs as a
plugin-style prompt assembly layer. Existing tools such as Codex CLI, Claude
Code, Cursor, and OpenCode already provide model access, streaming, tool loops,
approval UX, sandboxing, and editor integration. AgentMakefile should not
duplicate that surface at the start.

The plugin adapter layer lets a host agent ask AgentMakefile for a
request-specific prompt payload:

```text
host agent user input
  -> AgentMakefile plugin adapter
  -> target selection
  -> prompt fragment linking
  -> stable prefix + volatile context + trace
  -> host agent model/tool runtime
```

The near-term product is a cross-platform prompt assembly plugin. A standalone
AgentMakefile CLI runtime can remain a later option.

## Goals

- Integrate AgentMakefile with existing agent CLIs before building a full
  runtime.
- Let hosts load only the target fragments relevant to the current request.
- Keep stable prompt-prefix material deterministic for cache reuse.
- Keep volatile task context separate from stable prompt fragments.
- Provide a small JSON protocol that any host adapter can consume.
- Support dry-run and trace output for target selection and prompt-size
  debugging.
- Avoid depending on any one host agent's plugin API in the core compiler.

## Non-Goals

- Replacing Codex CLI, Claude Code, Cursor, or OpenCode.
- Owning model provider auth, streaming, terminal UI, or editor UI.
- Running shell commands or editing files from the plugin adapter.
- Enforcing hard permissions before a host-side enforcement hook exists.
- Supporting remote module registries in the first plugin milestone.

## Architecture

```text
Agent host
  Codex CLI / Claude Code / Cursor / OpenCode
        |
        | invokes
        v
AgentMakefile plugin adapter command or library API
        |
        | uses
        v
agentmf runtime planner
  load -> normalize -> select -> link -> describe contracts
        |
        | emits
        v
Plugin prompt payload JSON
  stable_prefix
  volatile_context
  host_instructions
  trace
  diagnostics
```

The core adapter should expose both:

- a Python API for embedded integrations
- a CLI command for host tools that can execute local commands

## Host Responsibilities

The host agent remains responsible for:

- model provider selection and authentication
- streaming output
- conversation memory
- file reads and writes
- shell execution
- tool approval UI
- sandboxing
- applying patches
- displaying traces or diagnostics

The plugin adapter is responsible only for producing structured prompt payloads
and explaining how they were built.

## Major Feature: Skill Import and Selection Optimization

The plugin adapter is also the bridge from existing skill ecosystems into
AgentMakefile. In the forward direction, an AgentMakefile source compiles into
Claude/Codex `SKILL.md` packages and `skills/index.md`. In the reverse
direction, a host can scan an existing `SKILL.md` tree into a generated
AgentMakefile skill-index module, then call `agentmf plugin payload` for each
user request.

For plugin installation, the adapter should run `agentmf plugin install` over
the host's configured skill roots. That command writes or returns the generated
AgentMakefile and emits model-facing instructions that tell the host to call
`agentmf plugin payload` before choosing skills for each user request.

This makes AgentMakefile useful even before a team has hand-authored modules:

- existing skills remain usable as native platform artifacts
- generated AgentMakefile targets encode skill match terms
- bootstrap skills become explicit dependency edges
- `selected_skills` tells the host which native skill packages to load
- `selection_trace` explains the matched terms, candidate ranking, priority,
  and dependency closure
- request matching is deterministic but layered: raw substring, normalized
  substring, built-in translation/alias expansion, then semantic token overlap

The goal is not to replace native skill packages. The goal is to provide a
structured, explainable routing layer above them.

## Plugin Payload

The adapter emits one JSON object:

```json
{
  "version": 1,
  "host": "codex",
  "mode": "prompt_payload",
  "request": "review this repo",
  "selected_targets": ["repo.security_review"],
  "selected_skills": [
    "superpowers:verification-before-completion",
    "superpowers:receiving-code-review"
  ],
  "selection_trace": {
    "mode": "request",
    "algorithm": "normalize_translate_semantic_priority_score_name",
    "request": "review this repo",
    "normalized_request": "review this repo",
    "expanded_request_terms": ["review", "this", "repo"],
    "requested_targets": [],
    "selected": {
      "target": "repo.security_review",
      "priority": 90,
      "matched_terms": ["review this repo"],
      "match_details": [
        {
          "term": "review this repo",
          "method": "substring",
          "score": 100,
          "evidence": "review this repo"
        }
      ],
      "match_score": 100,
      "dependency_closure": ["repo.inspect", "repo.security_review"]
    },
    "candidates": [
      {
        "rank": 1,
        "target": "repo.security_review",
        "priority": 90,
        "matched_terms": ["review this repo"],
        "match_details": [
          {
            "term": "review this repo",
            "method": "substring",
            "score": 100,
            "evidence": "review this repo"
          }
        ],
        "match_score": 100,
        "selected": true,
        "reason": "matched request substring(s)"
      }
    ]
  },
  "skill_artifacts": {
    "skills_index": "skills/index.md",
    "codex": [
      ".codex/skills/superpowers-verification-before-completion/SKILL.md",
      ".codex/skills/superpowers-receiving-code-review/SKILL.md"
    ],
    "claude": [
      ".claude/skills/superpowers-verification-before-completion/SKILL.md",
      ".claude/skills/superpowers-receiving-code-review/SKILL.md"
    ]
  },
  "stable_prefix": {
    "backend": "agents-fragments",
    "content": "# repo.security_review - Generic Coding Agents Target Fragment\n...",
    "chars": 4200,
    "approx_tokens": 1050,
    "hash": "sha256:..."
  },
  "volatile_context": {
    "plan": {
      "path": "docs/plans/review.md",
      "content": "..."
    },
    "git_status": "...",
    "git_diff": "...",
    "context_files": []
  },
  "host_instructions": {
    "injection": "prepend_stable_prefix_append_volatile_context",
    "preferred_cache_boundary": "after_stable_prefix",
    "permissions_mode": "host_enforced_when_supported"
  },
  "trace": {
    "target_closure": ["repo.inspect", "repo.security_review"],
    "selection": {
      "mode": "request",
      "algorithm": "normalize_translate_semantic_priority_score_name"
    },
    "linked_fragments": [".agentmf/fragments/agents/repo.security_review.md"],
    "comparison": {
      "linked": {"chars": 4200, "approx_tokens": 1050},
      "all_in_one": {"chars": 17000, "approx_tokens": 4250},
      "savings": {"chars": 12800, "approx_tokens": 3200}
    }
  },
  "diagnostics": []
}
```

The host can either concatenate `stable_prefix.content` and volatile fields into
its own prompt format or use the fields directly if it has native cache-control
or prompt-section support.

`selected_skills` and `skill_artifacts` make skill routing explicit for hosts
that can load generated `SKILL.md` files. Hosts that cannot load native skills
can still rely on `stable_prefix.content`, which already includes the selected
skill guidance.

`selection_trace` explains why a target was selected. For request-based
selection it records the normalized request, expanded request terms, matched
`match.user_intent` terms, match details, candidate ranking, priority values,
the selected target, and dependency closure. A target can match directly through
its own `match` fields or indirectly through the `match` fields of the skills it
references; skill-derived match details include a `source` value such as
`skill:omo:ultrawork`. Direct target matches rank ahead of skill-derived
matches, then priority and match score decide within each group. Match detail
methods are:

- `substring`: the raw request contains the match term
- `normalized_substring`: punctuation, case, or hyphenation normalization made
  the term match
- `translated_substring`: built-in request alias or Chinese-to-English
  development-intent translation made the term match
- `semantic_token_overlap`: canonical token overlap matched related terms

For explicit target selection it records the requested target names and their
closure. Hosts can log this field to debug unexpected skill selection without
parsing the rendered prompt text.

## Stable Prefix

The stable prefix is generated from AgentMakefile IR and selected target
fragments. It includes:

- selected target closure
- target-specific policies
- selected skills
- guards as instructions or contracts
- permission guidance
- output contracts
- fallback behavior

The stable prefix must not include the current user request, implementation
plan, git diff, active files, command output, or other volatile runtime state.

## Volatile Context

Volatile context is request-specific material appended after the stable prefix:

- user request
- optional implementation plan
- active file paths or summaries
- git status
- git diff
- explicit context files
- recent command output passed by the host

The adapter should include only explicitly requested volatile context. Hosts can
also choose to provide their own context after consuming the stable prefix.

## Host Adapter Modes

Concrete host integration examples are documented in
[agentmf_plugin_adapter_examples.md](agentmf_plugin_adapter_examples.md).

### Command Adapter

Hosts that can execute local commands call:

```bash
agentmf plugin payload \
  --host codex \
  --request "review this repo" \
  --plan docs/plans/review.md \
  --include-git-status \
  --include-git-diff \
  --format json
```

This is the lowest-friction first integration because it requires no host SDK.

### Library Adapter

Hosts or plugins written in Python call:

```python
from agentmf.plugin import create_plugin_payload

payload = create_plugin_payload(
    path="AgentMakefile",
    host="codex",
    request="review this repo",
    plan_path="docs/plans/review.md",
    include_git_status=True,
    include_git_diff=True,
)
```

The library API should return structured diagnostics rather than exiting.

### Native Host Adapter

A later host-specific adapter can translate the generic payload into native
configuration:

- Codex: generated project instructions or plugin hook payload
- Claude Code: skill or hook payload
- Cursor: rules and context injection
- OpenCode: runtime configuration and permission mapping

Native adapters should be thin translators over the generic payload protocol.

## CLI Surface

Initial plugin commands:

```bash
agentmf plugin install
agentmf plugin payload [REQUEST]
```

Options:

```text
--file AgentMakefile
--host codex|claude-code|cursor|opencode|generic
--request TEXT
--plan PATH
--target NAME
--backend agents-fragments|claude-fragments
--include-git-status
--include-git-diff
--context-file PATH
--format json|text
```

`agentmf plugin install` options:

```text
--skills-dir PATH      # repeatable, scans PATH/*/SKILL.md
--host codex|claude-code|cursor|opencode|generic
--namespace NAME
--package-name NAME
--package-description TEXT
--bootstrap-skill NAME
--out .agentmf/plugin/AgentMakefile
--write
--format json|text
```

Rules:

- `plugin install` is the install-time bootstrap path: scan native skill
  packages, generate the AgentMakefile skill index, and emit model instructions
  to use `plugin payload` at request time.
- Positional `REQUEST` and `--request` are mutually exclusive.
- `--target` bypasses request matching.
- `--plan` is loaded into volatile context only.
- `--include-git-diff` and `--include-git-status` are opt-in.
- JSON mode is the stable protocol. Text mode is diagnostic only.

## Data Flow

1. Read CLI arguments or library parameters.
2. Load optional plan content.
3. Call `create_run_plan(..., dry_run=True)`.
4. Extract `prompt_prefix` from the runtime plan.
5. Compute a stable prefix hash.
6. Collect requested volatile context.
7. Build host instructions for the selected host.
8. Return plugin payload JSON and diagnostics.

## Permission and Guard Semantics

The first plugin milestone does not enforce permissions. It exposes permission
and guard contracts to the host:

- `permissions_mode`: `soft_guidance` when the host cannot enforce rules
- `permissions_mode`: `host_enforced_when_supported` when the host can map them
- guard entries remain planned or advisory until guard evaluation exists

Later milestones can add host-specific enforcement hooks, but core prompt
payload generation must stay useful without them.

## Host Profiles

Host profiles describe how a host should inject the stable prefix and whether
AgentMakefile permissions can map to a host-native enforcement surface. They do
not load host SDKs or execute host-specific code.

| Host | Instruction surface | Permission mode | Native artifacts |
| --- | --- | --- | --- |
| `generic` | `generic_prompt_payload` | `soft_guidance` | none |
| `codex` | `AGENTS.md_or_plugin_payload` | `host_enforced_when_supported` | none |
| `claude-code` | `CLAUDE.md_or_claude_code_hooks` | `host_enforced_when_supported` | `.claude/settings.json`, `.claude/hooks/*` |
| `cursor` | `.cursor/rules_or_plugin_payload` | `soft_guidance` | none |
| `opencode` | `opencode.json_or_plugin_payload` | `host_enforced_when_supported` | `opencode.json` |

Each payload's `host_instructions` object should include:

- `profile`
- `injection`
- `preferred_cache_boundary`
- `permissions_mode`
- `instruction_surface`
- `native_artifacts`

## Error Handling

The adapter should fail closed:

- invalid AgentMakefile returns diagnostics and no prompt payload
- unknown target returns diagnostics and no prompt payload
- missing plan path returns diagnostics and no prompt payload
- git context collection failure returns diagnostics unless the context was
  optional and explicitly allowed to be skipped
- unsupported host falls back to `generic` only when the caller asks for it

## Tracing

Every payload should include enough trace data to explain:

- selected targets
- dependency closure
- selected fragments
- stable prefix hash
- linked-vs-all-in-one size comparison
- volatile context sources
- permission mode
- guard status

This trace is essential for proving token savings and debugging routing.

## Security Considerations

- Do not execute repository commands except read-only git inspection commands
  requested by flags.
- Do not include `.env`, secret-looking files, or credential material as
  context files.
- Treat AgentMakefile and included modules as trusted project configuration.
- Treat user request, plan content, git diff, and context files as untrusted
  task context.
- Keep stable behavior source separate from volatile input to reduce prompt
  injection surface.
- Let the host agent make final decisions about tool execution and approval.

## Milestones

### AMF-PAD-001 Plugin Payload Spec

Document the generic plugin adapter protocol and payload shape.

### AMF-PAD-002 Plugin Payload Builder

Add `agentmf.plugin.create_plugin_payload` that wraps `create_run_plan` and
returns stable prefix, volatile context, host instructions, trace, and
diagnostics.

### AMF-PAD-003 CLI Command

Add `agentmf plugin payload` with JSON output.

### AMF-PAD-004 Plan and Context Inputs

Add `--plan`, `--include-git-status`, `--include-git-diff`, and
`--context-file` handling.

### AMF-PAD-005 Host Profiles

Add `generic`, `codex`, `claude-code`, `cursor`, and `opencode` host instruction
profiles.

### AMF-PAD-006 Example Adapter Docs

Documented in
[agentmf_plugin_adapter_examples.md](agentmf_plugin_adapter_examples.md). It
shows how existing agent CLIs or plugins invoke `agentmf plugin payload`, inject
the returned stable prefix, append volatile context, and handle failures.

## Acceptance Criteria

- A host can request a prompt payload without calling a model.
- Payload JSON separates stable prefix from volatile context.
- Plan content appears only in volatile context.
- Stable prefix hash is unchanged when only plan content changes.
- Payload trace reports selected targets, fragments, prompt-size comparison, and
  context sources.
- Unknown or invalid inputs return structured diagnostics.
- The core adapter has no dependency on a host-specific SDK.
