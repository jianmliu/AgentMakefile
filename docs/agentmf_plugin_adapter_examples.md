# AgentMakefile Plugin Adapter Examples

Status: proposed.

Date: 2026-05-25.

## Purpose

This document shows how an existing coding-agent host can call
`agentmf plugin payload`, consume the returned prompt payload, and inject the
stable prompt prefix before the host performs its own model call or tool loop.

The host remains responsible for model access, streaming, approvals, tool
execution, sandboxing, and UI. AgentMakefile provides request routing, stable
prompt-prefix linking, volatile context packaging, and trace data.

## Minimal Command Adapter

A plugin can bootstrap from already-installed skills at install time:

```bash
agentmf plugin install \
  --skills-dir ~/.codex/skills \
  --host codex \
  --namespace superpowers \
  --bootstrap-skill using-superpowers \
  --out .agentmf/plugin/AgentMakefile \
  --write \
  --format json
```

The returned `model_instructions` should be added to the host/plugin bootstrap
guidance. It tells the model to call `agentmf plugin payload` against the
generated AgentMakefile before selecting or loading native skills.

A host that can run a local command can request a payload with JSON output:

```bash
agentmf plugin payload \
  --file .agentmf/plugin/AgentMakefile \
  --host codex \
  --request "review code" \
  --format json
```

The important response fields are:

```json
{
  "ok": true,
  "plugin_payload": {
    "stable_prefix": {
      "content": "...",
      "hash": "sha256:..."
    },
    "volatile_context": {
      "plan": null,
      "git_status": null,
      "git_diff": null,
      "context_files": []
    },
    "host_instructions": {
      "injection": "prepend_stable_prefix_append_volatile_context",
      "preferred_cache_boundary": "after_stable_prefix"
    },
    "trace": {
      "target_closure": ["review.task"],
      "linked_fragments": [".agentmf/fragments/agents/review.task.md"]
    }
  }
}
```

If `ok` is false, the host should display diagnostics and avoid injecting a
partial prompt payload.

## Prompt Assembly

Hosts should preserve this order:

```text
stable_prefix.content

<cache boundary when supported>

user request
plan content
git status
git diff
context files
host-provided observations
```

The stable prefix can be cached by `stable_prefix.hash`. Volatile context should
not affect that hash.

## Python Host Wrapper

```python
import json
import subprocess


def load_agentmf_payload(request: str) -> dict:
    completed = subprocess.run(
        [
            "agentmf",
            "plugin",
            "payload",
            "--host",
            "codex",
            "--request",
            request,
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    envelope = json.loads(completed.stdout)
    if not envelope["ok"]:
        raise RuntimeError(envelope["diagnostics"])
    return envelope["plugin_payload"]


def build_prompt(request: str) -> str:
    payload = load_agentmf_payload(request)
    volatile = payload["volatile_context"]
    sections = [
        payload["stable_prefix"]["content"],
        f"User request:\n{request}",
    ]
    if volatile["plan"]:
        sections.append(f"Plan:\n{volatile['plan']['content']}")
    if volatile["git_status"]:
        sections.append(f"Git status:\n{volatile['git_status']}")
    if volatile["git_diff"]:
        sections.append(f"Git diff:\n{volatile['git_diff']}")
    for context_file in volatile["context_files"]:
        sections.append(
            f"Context file: {context_file['path']}\n{context_file['content']}"
        )
    return "\n\n".join(sections)
```

## Plan-Aware Invocation

Plan input is volatile context. It should not become part of the stable prefix:

```bash
agentmf plugin payload \
  --host codex \
  --target project.default \
  --plan docs/superpowers/plans/2026-05-25-agentmf-plugin-adapter.md \
  --include-git-status \
  --format json
```

The host should use `volatile_context.plan.content` as task-specific context
after the stable prefix. Changing the plan should not change
`stable_prefix.hash`.

## Context File Invocation

Explicit context files are opt-in:

```bash
agentmf plugin payload \
  --host generic \
  --request "summarize this design" \
  --context-file docs/agentmf_plugin_adapter_spec.md \
  --format json
```

The adapter rejects `.env`, `.npmrc`, `.pypirc`, and secret-looking filenames.
Hosts should still apply their own secret filtering before displaying or sending
context to a model.

## Host-Specific Notes

### Generic

Use `--host generic` when the caller has no native prompt or permission
integration.

```bash
agentmf plugin payload --host generic --request "review code" --format json
```

The payload advertises `permissions_mode: soft_guidance`.

### Codex

Use `--host codex` when injecting the prefix into Codex-style project
instructions or a Codex plugin hook.

```bash
agentmf plugin payload --host codex --request "fix tests" --format json
```

The host can map `stable_prefix.content` to project instructions and append
volatile context as the user message or additional context block.

### Claude Code

Use `--host claude-code` when integrating with Claude Code project instructions
or hook-aware workflows.

```bash
agentmf plugin payload --host claude-code --target project.default --format json
```

The payload advertises `.claude/settings.json` and `.claude/hooks/*` as native
artifact surfaces. The plugin payload itself does not create or execute hooks.

### Cursor

Use `--host cursor` when the host injects the stable prefix into Cursor rules or
a Cursor-side extension.

```bash
agentmf plugin payload --host cursor --request "review docs" --format json
```

The payload advertises `permissions_mode: soft_guidance` because Cursor rules
are prompt guidance, not hard permission enforcement.

### OpenCode

Use `--host opencode` when the host can map AgentMakefile contracts into
OpenCode configuration or an OpenCode-side adapter.

```bash
agentmf plugin payload --host opencode --request "audit repo" --format json
```

The payload advertises `opencode.json` as the native artifact surface.

## Error Handling

Hosts should treat any nonzero exit code or payload with `ok: false` as a
failed prompt assembly. Recommended behavior:

1. Display `diagnostics`.
2. Do not inject `plugin_payload` when it is empty.
3. Fall back to host-native instructions only if that fallback is explicit.
4. Preserve the failed command and diagnostics in host logs.

## Security Boundary

The plugin payload is prompt assembly data, not permission enforcement. Hosts
must continue to enforce their own file, shell, network, and approval policies.

Hosts should treat these fields as untrusted task context:

- `request`
- `volatile_context.plan.content`
- `volatile_context.git_status`
- `volatile_context.git_diff`
- `volatile_context.context_files[*].content`

Hosts can treat these fields as stable AgentMakefile build outputs:

- `stable_prefix.content`
- `stable_prefix.hash`
- `selected_skills`
- `skill_artifacts`
- `selection_trace`
- `host_instructions`
- `trace.target_closure`
- `trace.linked_fragments`

`selection_trace` is the adapter-facing explanation layer: it contains the
selection mode, matcher algorithm, normalized request, expanded request terms,
matched request terms, ranked candidates, selected target, and dependency
closure. Match details show whether a candidate was selected by raw substring,
normalized substring, translated substring, or semantic token overlap. Hosts
should log it alongside prompt hashes when debugging unexpected skill or target
choices.
