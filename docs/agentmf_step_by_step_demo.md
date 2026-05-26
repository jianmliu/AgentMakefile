# AgentMakefile Step-by-Step Demo

This walkthrough uses [demos/runtime-walkthrough/AgentMakefile](../demos/runtime-walkthrough/AgentMakefile)
to exercise the current AgentMakefile runtime surface end to end.

The demo composes:

- `modules/superpowers/AgentMakefile` for methodology targets.
- `modules/unknown-repo-security/AgentMakefile` for security-review rails.
- A local `demo.runtime_walkthrough` target with JSON Schema output validation,
  fallback handling, and explicit tool permissions.

Run the commands from the repository root.

## 0. Import Skills and Optimize Selection

This is now a primary AgentMakefile flow. The original flow starts from an
AgentMakefile source and compiles platform-native skills. This flow starts from
an existing `SKILL.md` tree, imports it into a generated AgentMakefile
skill-index module, and lets the plugin payload optimize which skills should be
loaded for a specific request.

```bash
agentmf plugin install \
  --skills-dir ~/.codex/skills \
  --host codex \
  --namespace superpowers \
  --bootstrap-skill using-superpowers \
  --package-name scanned-superpowers \
  --out /tmp/superpowers.AgentMakefile \
  --write \
  --format json
```

The generated AgentMakefile contains one `skills:` entry and one `skill.*`
target per scanned skill. When `--bootstrap-skill` is provided, every
non-bootstrap skill target depends on that bootstrap target. This converts
bootstrap rules such as `using-superpowers` into explicit dependency edges.
The install payload also includes `model_instructions` and
`next_payload_command`, which tell the host/model to run the request-time
payload command before loading skills. A host can then use the same runtime
selection path:

```bash
agentmf plugin payload \
  --file /tmp/superpowers.AgentMakefile \
  --host codex \
  --request "implement this feature" \
  --format json
```

The payload returns `selected_skills`, `skill_artifacts`, and
`selection_trace`. That gives a host enough structure to load only the relevant
skills, explain why they were selected, and keep using native `SKILL.md`
packages as compatibility artifacts. In this mode AgentMakefile behaves like a
SkillMakefile index with dependency-aware routing.

The same optimization also applies to hand-authored modules. If a target does
not define its own `match` terms, `agentmf plugin payload` can derive target
candidates from the `match` terms of the skills referenced by that target. This
is useful for modules such as Oh My OpenAgent, where targets package several
skills into an orchestration mode.

Request matching is deterministic and layered. It first checks raw substrings,
then normalized text such as hyphen-insensitive skill names, then built-in
translation aliases for common development intents, and finally lightweight
semantic token overlap. For example, a Chinese request such as `请实现这个功能`
can route to a target whose English match term is `implement this feature`.

## 1. Validate the Demo

```bash
agentmf validate --file demos/runtime-walkthrough/AgentMakefile
```

Expected result: the file is valid.

Use JSON output when an adapter needs machine-readable diagnostics:

```bash
agentmf validate --file demos/runtime-walkthrough/AgentMakefile --format json
```

## 2. Compile Prompt Artifacts

Compile static Markdown, target fragments, and host skill packages without
writing files:

```bash
agentmf compile \
  --file demos/runtime-walkthrough/AgentMakefile \
  --target agents-md \
  --target claude-md \
  --target agents-fragments \
  --target claude-fragments \
  --target claude-skill \
  --target codex-skill \
  --target skills-index
```

Write artifacts only when you want to inspect generated files:

```bash
agentmf compile --file demos/runtime-walkthrough/AgentMakefile --write
```

The fragment backends emit target-specific prompt objects under
`.agentmf/fragments/...` and a manifest with content hashes. The skill backends
emit host-native prompt packages such as:

- `.claude/skills/superpowers-using-superpowers/SKILL.md`
- `.codex/skills/superpowers-using-superpowers/SKILL.md`

The current skill backends package each normalized `skills:` entry. Target
fragments remain the target-scoped prompt objects used for dynamic runtime
selection. The `skills-index` backend emits `skills/index.md` as a generated
compatibility catalog, so existing skill-index workflows can browse the same
source of truth. Re-running the same compile skips unchanged files.

To install generated skills into a host skill root, use `skills sync`. It is a
dry-run unless `--write` is present:

```bash
agentmf skills sync \
  --file modules/oh-my-openagent/AgentMakefile \
  --host codex \
  --write \
  --format json
```

For tests or local previews, pass `--out-dir /tmp/agentmf-codex-skills` instead
of writing to the default host skill root.

## 3. Select the Runtime Target

Ask AgentMakefile which target matches a request:

```bash
agentmf select \
  --file demos/runtime-walkthrough/AgentMakefile \
  --request "show agentmakefile runtime" \
  --backend agents-fragments \
  --format json
```

Expected selection:

- `demo.runtime_walkthrough`
- a target fragment that includes the local walkthrough target, the inherited
  security-review target, and the selected Superpowers skill

Use `--target demo.runtime_walkthrough` when a host already knows the target and
does not want request matching.

## 4. Inspect the Runtime Plan

Generate a dry-run plan:

```bash
agentmf run \
  --file demos/runtime-walkthrough/AgentMakefile \
  --request "show agentmakefile runtime" \
  --dry-run \
  --format json
```

The plan includes:

- selected target closure
- linked prompt prefix and token estimate
- guard evaluation records
- permission contracts
- output contracts
- fallback metadata

No workflow steps or tools are executed by `agentmf run`.

## 5. Check Tool Permissions Without Executing Tools

Evaluate safe and unsafe tool calls:

```bash
agentmf run \
  --file demos/runtime-walkthrough/AgentMakefile \
  --target demo.runtime_walkthrough \
  --dry-run \
  --permission-check "bash:git status" \
  --permission-check "bash:npm install" \
  --permission-check "bash:printf safe" \
  --format json
```

Expected decisions:

- `git status` is allowed by the included security module.
- `npm install` is denied by the included security module.
- `printf safe` is allowed by the demo file.

## 6. Validate Structured Output

The demo target defines a full JSON Schema contract. Validate an invalid sample:

```bash
agentmf run \
  --file demos/runtime-walkthrough/AgentMakefile \
  --target demo.runtime_walkthrough \
  --dry-run \
  --output-json "$(cat demos/runtime-walkthrough/expected-output.invalid.json)" \
  --format json
```

Expected result: `output_validation.status` is `invalid`, with structured
`schema_errors` for constraints such as `enum`, `minLength`,
`additionalProperties`, and `minItems`.

Validate a passing sample:

```bash
agentmf run \
  --file demos/runtime-walkthrough/AgentMakefile \
  --target demo.runtime_walkthrough \
  --dry-run \
  --output-json "$(cat demos/runtime-walkthrough/expected-output.valid.json)" \
  --format json
```

Expected result: `output_validation.status` is `valid`.

## 7. Build a Final Prompt Payload

Add volatile task context after the stable prefix:

```bash
agentmf prompt \
  --file demos/runtime-walkthrough/AgentMakefile \
  --request "show agentmakefile runtime" \
  --plan demos/runtime-walkthrough/plan.md \
  --context-file demos/runtime-walkthrough/context/repo_notes.md \
  --format json
```

The payload separates:

- `stable_prefix`: cache-friendly target fragment content.
- `volatile_context`: request, plan, context files, and optional git context.
- `final_prompt`: the assembled prompt that a host can send to a model.

## 8. Generate a Plugin Payload

For existing agent hosts, use the plugin adapter path:

```bash
agentmf plugin payload \
  --file demos/runtime-walkthrough/AgentMakefile \
  --host codex \
  --request "show agentmakefile runtime" \
  --plan demos/runtime-walkthrough/plan.md \
  --context-file demos/runtime-walkthrough/context/repo_notes.md \
  --format json
```

The host keeps responsibility for model calls, streaming, tool execution,
approvals, and sandboxing. AgentMakefile supplies the selected prompt payload
and trace. The payload also exposes `selected_skills` and `skill_artifacts`, so
a Codex or Claude adapter can see which generated `SKILL.md` files correspond to
the selected target closure. `selection_trace` explains why the target was
selected, including matched request terms, ranked candidates, selected priority,
and the resolved dependency closure.

## 9. Run the Echo Provider

Use the deterministic local provider:

```bash
agentmf ask \
  --file demos/runtime-walkthrough/AgentMakefile \
  --request "show agentmakefile runtime" \
  --provider echo \
  --format json
```

The `echo` provider is a smoke-test adapter. It reports selected targets and
prompt hashes without calling an external model.

## 10. Run the Gated Exec Prototype

Allowed read-only command:

```bash
agentmf exec \
  --file demos/runtime-walkthrough/AgentMakefile \
  --target demo.runtime_walkthrough \
  --provider echo \
  --tool-call "bash:git status" \
  --sandbox-profile read-only \
  --apply \
  --format json
```

The exec payload includes:

- `runtime_plan`
- `sandbox`
- `tool_interception`
- `tool_results`
- `fallback_handling`

Blocked command with fallback execution:

```bash
agentmf exec \
  --file demos/runtime-walkthrough/AgentMakefile \
  --target demo.runtime_walkthrough \
  --provider echo \
  --tool-call "bash:npm install" \
  --sandbox-profile read-only \
  --execute-fallbacks \
  --apply \
  --format json
```

Expected result:

- permission decision: `deny`
- tool result: `blocked`
- fallback status: `executed`
- fallback execution mode: `internal_noop`

Sandbox-blocked command:

```bash
agentmf exec \
  --file demos/runtime-walkthrough/AgentMakefile \
  --target demo.runtime_walkthrough \
  --provider echo \
  --tool-call "bash:touch should-not-exist.txt" \
  --sandbox-profile read-only \
  --execute-fallbacks \
  --apply \
  --format json
```

Expected result:

- permission decision: `allow`
- sandbox decision: `sandbox_read_only`
- tool result: `blocked`
- provider interception decision: `block`

## What This Demonstrates

This demo shows the current AgentMakefile value proposition:

- Stable target fragments can be selected and linked per request.
- Volatile task context stays outside stable prompt objects.
- Permission and output contracts can be dry-run before execution.
- JSON Schema output validation provides structured failure details.
- The plugin adapter can feed existing agent runtimes.
- The exec prototype records provider tool-call interception, sandbox preflight,
  tool results, and fallback routing in one payload.
