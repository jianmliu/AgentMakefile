# @agentmf/opencode-plugin

A thin adapter that lets [OpenCode](https://opencode.ai) call into the local
`agentmf` CLI on every chat turn. AgentMakefile stays the routing/curation
brain; the plugin is ~260 lines of glue.

> Status: **v0.0.3 — minimal proof, all three wires end-to-end verified.**
> Loaded into a real `opencode run` session: routed guidance lands in
> `output.system`; `/agentmf <args>` shells out via
> `command.execute.before`; `session.diff` events are accumulated and
> shipped (with redaction) alongside the `session.idle` evidence
> record. Not yet published to npm.

## What it does

| Hook                                       | Status | Behavior |
| ------------------------------------------ | :---:  | --- |
| `chat.message`                             | ✅     | Reads the user's text from `output.parts`, calls `agentmf prompt --request <text> --format json` from the project directory, caches the routed `stable_prefix` keyed by `sessionID`. |
| `experimental.chat.system.transform`       | ✅     | Pushes the cached routed prefix into `output.system` as a fresh entry tagged `## Routed Guidance (AgentMakefile)`. Idempotent within a session (won't double-inject across turns). |
| `command.execute.before` (`/agentmf`)      | ✅     | Intercepts `/agentmf <subcommand …>` (configurable via `AGENTMF_SLASH_COMMAND`), shells `spawnSync` to `agentmf <args>` from the project directory, emits stdout (or stderr on failure) as a single text part. Requires a stub command entry in `opencode.json` so OpenCode is willing to dispatch the slash command (see Install). |
| `event` → `session.diff`                   | ✅     | Accumulates `FileDiff[]` per session, deduped by file path. |
| `event` → `session.idle` / `completed`     | ✅     | Drains the per-session diff bucket and ships it alongside metadata via `agentmf evo evidence add --source plugin_payload --write`. The agentmf subprocess is spawned **detached + unref'd** because `opencode run` exits before the event hook's promise resolves and would otherwise SIGTERM the in-flight child. |

> **Note on `chat.params`.** The natural-sounding hook for "modify the
> request" is `chat.params`, but in OpenCode 1.15 that hook only exposes
> `temperature/topP/topK/maxOutputTokens/options` — not the message
> list. The right combo for prefix injection is
> `chat.message` (capture text) + `experimental.chat.system.transform`
> (push into the system-prompt list).

All logic lives in `agentmf` itself — the plugin shells out and forwards
JSON. That means upgrades to the routing brain (selector, dream
detectors, patch classes) ship automatically without re-publishing the
plugin.

## Install

OpenCode resolves plugin references via npm by default, so a local
dev install requires the `file:` URI form in `opencode.json`. The
`/agentmf` slash command also needs an entry in the `command` section
so OpenCode is willing to dispatch it — the template is a placeholder;
the plugin short-circuits with its own output:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["file:/absolute/path/to/AgentMakefile/plugins/opencode"],
  "command": {
    "agentmf": {
      "template": "(intercepted by @agentmf/opencode-plugin)",
      "description": "Run the agentmf CLI inside this session"
    }
  }
}
```

Once published you can drop `file:` for the package name. The `command`
stub stays — that's how OpenCode learns the slash command exists at all.

Prerequisites:

- `agentmf` on PATH (or set `AGENTMF_BIN=/path/to/agentmf`).
- An `AgentMakefile` at the project root so `agentmf prompt --request …`
  produces a non-empty `stable_prefix`. If `agentmf` returns `ok: false`
  (no AgentMakefile, no matching target), the plugin no-ops gracefully.

Optional env knobs:

- `AGENTMF_BIN` — override the binary (default `agentmf`).
- `AGENTMF_TIMEOUT_MS` — kill `agentmf` if it stalls; default `5000`.
- `AGENTMF_SLASH_COMMAND` — rename the slash command (default `agentmf`).
- `AGENTMF_MAX_DIFF_BYTES` — per-file cap on `before+after` bytes kept in
  evidence; over the cap the file is recorded as `*_truncated` with byte
  counts only. Default `16384`.
- `AGENTMF_PLUGIN_DEBUG=1` — emit `[agentmf-plugin] …` lines to stderr
  on every hook firing. Useful for confirming the integration during
  setup; off by default.

## Slash command examples

Once the stub is in `opencode.json`, the following invocations are
handled directly by the plugin:

```
/agentmf validate              # validate the project's AgentMakefile
/agentmf select --request "fix flaky test in selector"
/agentmf evo dream run         # dry-run dream-mode detectors
/agentmf evo evidence add …    # manually push evidence
```

Output is wrapped in a fenced code block and added as a single text
part to the session. Failure paths surface the agentmf stderr instead
of crashing the session.

**Invocation modes:**
- **TUI** — type `/agentmf <args>` in the prompt and submit.
- **Headless** — `opencode run --command agentmf "<args>"`. The
  `<args>` string is whitespace-split and passed to the CLI. Using
  `opencode run "/agentmf validate"` (no `--command`) sends it as a
  plain message to the LLM, which is *not* what you want — the
  command hook only fires when OpenCode dispatches via the command
  surface.

## Diff capture

Two-tier strategy because OpenCode's `session.diff` events
sometimes arrive empty (notifications, not data carriers):

1. **Primary** — accumulate `FileDiff[]` from `session.diff` events
   per `sessionID`, deduped by file path. Works reliably for git
   repos; OpenCode populates `properties.diff` when the project has
   a git baseline.
2. **Fallback** — at `session.idle`, if the bucket is empty, run
   `git diff --numstat` + `git diff` synchronously in `projectCwd`
   and attach the result. Works in any git project even when
   `session.diff` events stay empty (e.g. some `opencode run`
   shapes).

Each captured `FileDiff` keeps `{file, additions, deletions}` plus
truncation-aware `before`/`after` content (capped at
`AGENTMF_MAX_DIFF_BYTES` bytes per file, default 16 KiB).

### What the evidence record looks like

`agentmf evo evidence add` hashes the full payload (including the
unredacted diff content) into `record.payload_hash` and surfaces a
compact projection for the dream loop:

```jsonc
{
  "source": "plugin_payload",
  "selected_target": "code.change",       // dream loop counts target hits
  "request_fingerprint": "sha256:a919…",  // clusters routing-gap repeats
  "selected_skills": [],
  "summary": {
    "selected_targets": ["code.change"],
    "diff_files": 1,
    "diff_source": "session.diff bucket", // or "git diff"
    "diff_paths": ["hello.py"],
    "diff_additions": 2,
    "diff_deletions": 0,
    "event_type": "session.idle",
    "captured_at": "2026-05-28T05:36:17.236Z"
  },
  "payload_hash": "sha256:…"              // full diff content lives in here
}
```

That's enough surface area for the existing dream-loop detectors:
`_benchmark_case_suggester` counts records by `selected_target` and
suggests an `add_benchmark_case` change when a target keeps recurring;
`_recurring_failure_proposals` clusters routing gaps by
`request_fingerprint`; future detectors can filter
`summary.diff_files > 0` to ignore no-op sessions.

## Smoke tests

### Without OpenCode

```bash
cd plugins/opencode
node tests/smoke.mjs
```

Covers all three wires: `chat.message → system.transform` injection
(with idempotence), `session.diff` accumulation + drain on
`session.idle`, `command.execute.before` intercept (and pass-through
for non-`agentmf` commands), and the module export shape
(`AgentmfPlugin`, `server`, `default.server`).

### With OpenCode (end-to-end)

```bash
# 1. Stand up a sandbox project.
mkdir -p /tmp/agentmf-oc-smoke && cd /tmp/agentmf-oc-smoke
cp /path/to/AgentMakefile/AgentMakefile .
ln -s /path/to/AgentMakefile/modules ./modules

# 2. Point opencode.json at the local plugin + register the stub command.
cat > opencode.json <<EOF
{ "\$schema": "https://opencode.ai/config.json",
  "plugin": ["file:/path/to/AgentMakefile/plugins/opencode"],
  "command": { "agentmf": { "template": "(intercepted)", "description": "agentmf CLI" } } }
EOF

# 3. Run a session with debug logging on.
AGENTMF_PLUGIN_DEBUG=1 opencode run --print-logs --log-level INFO \
  -m opencode/big-pickle "fix a bug in the selector module"
```

Expected stderr (verified on opencode 1.15.10):

```
[agentmf-plugin] init directory=/tmp/agentmf-oc-smoke bin=agentmf slash=/agentmf
[agentmf-plugin] chat.message: calling agentmf sessionID=ses_… chars=58
[agentmf-plugin] chat.message: cached prefix target=code.change bytes=6993
[agentmf-plugin] system.transform: injected bytes=6993 system_count=2
[agentmf-plugin] event: captured diff sessionID=ses_… files_in_event=1 total_files=1
[agentmf-plugin] event: shipping evidence type=session.idle diff_files=1
[agentmf-plugin] event: ship spawn returned type=session.idle
```

After the session, evidence lands at
`<project>/.agentmf/evolution/evidence/traces/plugin_payload.jsonl`
(the same file `agentmf evo dream run` consumes). The payload now
includes a `diff: [{file, before, after, additions, deletions}]` array
(or `*_truncated` markers when files exceed the byte cap).

## Why this shape

1. **Single source of truth.** Routing precision (29/29 on the
   ClawBench-routing baseline), dream detectors, evidence schema —
   all of it stays in `agentmf`. The plugin can never drift.
2. **Portable pattern.** The same combo (capture user text → call
   routing CLI → push into system prompt → ship trace with diff) maps
   to Claude Code (skills + session hooks) and Codex (session
   middleware) with ~50 lines of glue each. Plugin = one runtime;
   CLI = N runtimes.
3. **Cheap to verify.** A subprocess boundary makes the integration
   trivially testable from either side — `agentmf prompt --format json`
   is a pure function of `--request`, and the plugin is a pure function
   of that JSON.

## Roadmap

- [ ] Prefer `agentmf select --format json` over `prompt` per turn —
      skips the full stable_prefix render when only the routing
      decision is needed, halves the per-turn payload.
- [ ] `command.execute.before` for `/agentmf evo …` could stream
      progress instead of buffering until completion (current code
      uses `spawnSync` for predictability).
- [ ] Publish to npm once OpenCode plugin spec stabilizes.
