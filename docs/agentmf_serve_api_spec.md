# `agentmf serve` — Local Engine API (contract)

Status: design. Date: 2026-06-04.

## Purpose

A long-running local JSON API so non-Python consumers — a desktop GUI (e.g. a
cc-switch-style shell), a host adapter, a future MCP server — can drive
AgentMakefile **without shelling out per command and without reimplementing any
logic**. The endpoints are thin HTTP wrappers over the existing payload
builders; the wire shapes are the SAME structures `--format json` already emits.

> Strategic intent: AgentMakefile stays the **engine**; the GUI/adapter is a
> thin consumer. One `serve` surface serves all three consumers (GUI, host
> adapter, MCP) — not a GUI-specific API.

## Server

```
agentmf serve --root DIR [--port 8787] [--token SECRET]
```

- `--root` — a project directory containing an `AgentMakefile` (the source of
  truth). The server is rooted at one project; `path` is therefore server
  config, not a per-request field.
- Stateless: every request is independent (the payload builders are pure
  `path + params -> payload`). No session state, safe to restart.
- Localhost-only by default; optional `--token` bearer for defense in depth.

## Response envelope

Every response (success or failure) uses one envelope so a GUI can render
diagnostics uniformly:

```json
{
  "ok": true,
  "diagnostics": [
    { "code": "AMF118", "message": "...", "location": "select.request" }
  ],
  "data": { /* endpoint-specific payload, see below */ }
}
```

`ok=false` ⇒ `data` may be partial/absent; `diagnostics` carries the AgentMakefile
diagnostic codes (same as the CLI). HTTP status mirrors `ok` (200 / 4xx).

## Endpoints

### Introspection (GET) — what a GUI lists

| Method · Path | Returns (`data`) | Backed by |
| --- | --- | --- |
| `GET /healthz` | `{version, root, agentmakefile_present}` | — |
| `GET /targets` | `[{name, priority, match, skills, cost}]` — routable targets | loader/IR |
| `GET /backends` | `["claude-md","claude-code","claude-skill","codex-skill","skills-index","opencode","cursor-rule","claude-fragments"]` | backend registry |
| `GET /matchers` | `["keyword","embedding","hybrid"]` | `SUPPORTED_MATCHERS` |
| `GET /models` | `[{name, family, cost, capabilities, priority, default}]` | IR `models:` |

### Core operations (POST) — 1:1 over the payload builders

Each POST body is a JSON object; omitted fields use the function defaults.

| Method · Path | Body (key fields) | Returns (`data`) | Wraps |
| --- | --- | --- | --- |
| `POST /select` | `{request?, targets?, backend?, matcher?, n_best?, budget?}` | **link_plan**: `{version, backend, selected_targets, targets, selection_trace, recommended_model, budget:{limit,dropped_over_budget}}` | `create_link_plan` |
| `POST /plugin/payload` | `{host?, request?, targets?, context_files?, include_git_status?, include_git_diff?, token_budget?, max_output_per_call?}` | **plugin_payload**: `{version, skills, selected_target, selection_trace, recommended_model, token_budget:{per_call_ceiling,fits_first_call,halt_policy,…}}` | `create_plugin_payload` |
| `POST /ask` | plugin fields + `{provider?, model?, temperature?, max_output_tokens?, token_budget?}` | **ask_payload**: final prompt + provider one-shot result + `token_budget` view | `create_ask_payload` |
| `POST /exec` | `{request?, targets?, tool_calls?, apply?, cwd?, sandbox_profile?, token_budget?, max_per_call_tokens?, max_per_call_usd?}` | **exec_payload**: gated tool-loop result; statuses `executed` / `halted_over_budget` (B) / `oversized_call` (C) | `create_exec_payload` |
| `POST /compile` | `{backend?, targets?, write?}` | compiled artifacts (one structured source → N platform-native files); `write=false` previews | `compile_agentmakefile` |
| `POST /validate` | `{}` | validation diagnostics for the root source | loader validation |
| `POST /guidance/scan` | `{files:[paths]}` | scanned SKILL.md / AGENTS.md / CLAUDE.md / markdown → importable guidance | `scan_guidance_files` |

### Pricing & budget

`pricing_table` (path) and the budget knobs (`budget`, `token_budget`,
`max_output_per_call`, `max_per_call_{tokens,usd}`) are accepted on the relevant
POSTs exactly as the CLI flags. The `token_budget` block in `/plugin/payload`,
`/ask`, `/exec` responses is the cost contract a host enforces (per_call_ceiling,
fits_first_call, halt_policy) — the same A/B/C model the AIGG gateway enforces
server-side in Go.

## Design notes

- **Thin by construction.** Each POST = `json.dumps(create_*_payload(root, **body).payload)` + the envelope. No new domain logic; the server is ~one file. Diagnostics already flow through every builder.
- **Same contract as `--format json`.** A consumer can prototype against the CLI (`agentmf select --format json`) and move to `serve` with no shape changes.
- **Import-first adoption.** `POST /guidance/scan` is the cold-start killer: point it at an existing setup → get an importable source-of-truth, instead of authoring YAML from scratch (the cc-switch "bidirectional / meet users where they are" lesson).
- **MCP-ready.** The same endpoints map cleanly onto MCP tools later (one tool per POST); the budget block is the candidate `budget` extension payload (tracked in project memory). `serve` is the inbound channel that exists today; MCP is the standardized one later.
- **Not a runtime.** `serve` emits plans/contracts/artifacts; enforcement of token/tool budgets stays with the host (or the AIGG gateway). This keeps AgentMakefile a compiler + contract-emitter, not a competing runtime.

## Web UI (MVP)

`GET /`, `/ui`, `/index.html` serve a single self-contained HTML page (vanilla
JS, no build step, no dependencies — embedded in `serve.py`). It is a thin
*consumer* of the JSON API, proving the engine/consumer split:

- On load it calls `GET /healthz /matchers /backends /targets /models` to
  populate the project status, the matcher/backend selectors, and the
  target/model lists.
- The request box + **Select** button issue `POST /select` and render the link
  plan (selected targets, selection trace, recommended model, budget).
- When a budget is entered it also calls `POST /plugin/payload` and renders the
  host-enforceable **A/B/C token-budget contract** as a cost bar: a grey
  `stable_prefix_tokens` segment + a blue `per_call_ceiling` segment over the
  `total` track, turning red when `fits_first_call` is false, with
  `headroom_after_first_call` and `halt_policy` shown alongside. This is the
  same contract the AIGG gateway enforces server-side and the candidate payload
  for the MCP budget extension.
- An optional bearer-token field is sent as `Authorization` so the page works
  whether or not the server was started with `--token`. The page itself loads
  ungated; only the JSON API enforces the token.

This is the cc-switch-style shell reduced to its smallest honest form: no
client framework, no server-side rendering, no new domain logic.

## Out of scope (deliberately)

- Auth beyond a localhost bearer; multi-tenant; remote hosting.
- Streaming (`/ask`, `/exec` are request/response; streaming is a later slice).
- Persisted state / sessions (the builders are pure; a GUI owns its own state).
