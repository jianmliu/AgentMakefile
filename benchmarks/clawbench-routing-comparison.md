# ClawBench Routing-Only Comparison

Routing-only comparison: which target(s) the selector picks for each
task under different AgentMakefile sources. No external agent runner
is invoked, so the table measures routing precision only — not
downstream pass rate.

- Tasks: `benchmarks/clawbench-routing-tasks.jsonl` (37 entries)
- Driver: `benchmarks/clawbench-routing-compare.py`
- Curated modules are per-machine (`.gitignore`'d under
  `modules/openclaw-curated/`); regenerate with
  `agentmf evo promote --target-dir modules/openclaw-curated --write`.

## Selected targets per task

| Task | root | curated/.tmp | curated/plugins | curated/skills | curated/uncategorized | curated/vendor_imports |
| --- | --- | --- | --- | --- | --- | --- |
| `methodology-review` | `methodology.review` | `skill..tmp.figma-generate-design` | _no match_ | _no match_ | _no match_ | _no match_ |
| `methodology-plan` | `methodology.execute_plan` | `skill..tmp.executing-plans` | `skill.plugins.documents` | _no match_ | `skill.uncategorized.himalaya` | _no match_ |
| `methodology-debug` | `methodology.debug` | `skill..tmp.web-perf` | `skill.plugins.m5-onboard` | _no match_ | `skill.uncategorized.mcporter` | _no match_ |
| `methodology-finish` | `methodology.finish` | `skill..tmp.attack-path-analysis` | `skill.plugins.stripe-projects` | _no match_ | `skill.uncategorized.apple-reminders` | _no match_ |
| `methodology-skill-authoring` | `methodology.review` | `skill..tmp.figma-generate-design` | `skill.plugins.example-skill` | _no match_ | `skill.uncategorized.himalaya` | `skill.vendor_imports.security-threat-model` |
| `methodology-parallel` | `methodology.parallel` | `skill..tmp.ai-sdk` | _no match_ | _no match_ | _no match_ | `skill.vendor_imports.migrate-to-codex` |
| `methodology-worktree` | `methodology.worktree` | `skill..tmp.test-driven-development` | _no match_ | _no match_ | _no match_ | _no match_ |
| `methodology-request-review` | `methodology.review` | `skill..tmp.figma-generate-design` | `skill.plugins.agent-development` | _no match_ | _no match_ | `skill.vendor_imports.security-threat-model` |
| `plugins-presentations` | _no match_ | `skill..tmp.hubspot` | `skill.plugins.presentations` | _no match_ | `skill.uncategorized.bear-notes` | _no match_ |
| `plugins-spreadsheet` | _no match_ | `skill..tmp.finishing-a-development-branch` | `skill.plugins.spreadsheets` | _no match_ | `skill.uncategorized.himalaya` | _no match_ |
| `plugins-stripe` | `omo.plan` | `skill..tmp.uml-and-software-architecture-visualization` | `skill.plugins.stripe-projects` | _no match_ | _no match_ | `skill.vendor_imports.figma-create-design-system-rules` |
| `plugins-documents` | _no match_ | `skill..tmp.teams-messages` | `skill.plugins.documents` | _no match_ | _no match_ | _no match_ |
| `plugins-build-mcp-server` | _no match_ | `skill..tmp.openai-platform-api-key` | `skill.plugins.build-mcp-server` | `skill.skills.imagegen` | `skill.uncategorized.skill-creator` | `skill.vendor_imports.cli-creator` |
| `plugins-build-mcp-app` | _no match_ | `skill..tmp.uml-and-software-architecture-visualization` | `skill.plugins.build-mcp-app` | _no match_ | _no match_ | _no match_ |
| `plugins-claude-md-improver` | _no match_ | `skill..tmp.openai-api-troubleshooting` | `skill.plugins.claude-md-improver` | _no match_ | _no match_ | _no match_ |
| `plugins-frontend-design` | `methodology.default` | `skill..tmp.twilio-webhook-architecture` | `skill.plugins.frontend-design` | _no match_ | _no match_ | _no match_ |
| `plugins-agent-development` | `methodology.review` | `skill..tmp.figma-generate-design` | `skill.plugins.agent-development` | _no match_ | _no match_ | `skill.vendor_imports.security-threat-model` |
| `plugins-skill-development` | _no match_ | `skill..tmp.figma-create-new-file` | `skill.plugins.skill-development` | _no match_ | `skill.uncategorized.coding-agent` | _no match_ |
| `skills-imagegen` | _no match_ | `skill..tmp.figma-generate-diagram` | _no match_ | `skill.skills.imagegen` | `skill.uncategorized.nano-banana-pro` | _no match_ |
| `skills-openai-docs` | _no match_ | `skill..tmp.supabase` | _no match_ | `skill.skills.openai-docs` | `skill.uncategorized.openai-whisper-api` | `skill.vendor_imports.speech` |
| `skills-skill-installer` | _no match_ | `skill..tmp.twilio-webhook-architecture` | `skill.plugins.stripe-projects` | `skill.skills.skill-installer` | `skill.uncategorized.skill-creator` | `skill.vendor_imports.hatch-pet` |
| `bundled-1password` | _no match_ | `skill..tmp.openai-platform-api-key` | `skill.plugins.documents` | _no match_ | `skill.uncategorized.1password` | _no match_ |
| `bundled-apple-notes` | _no match_ | `skill..tmp.hubspot` | `skill.plugins.build-mcp-server` | `skill.skills.imagegen` | `skill.uncategorized.apple-notes` | `skill.vendor_imports.jupyter-notebook` |
| `bundled-apple-reminders` | _no match_ | `skill..tmp.google-calendar-daily-brief` | _no match_ | _no match_ | `skill.uncategorized.apple-reminders` | _no match_ |
| `bundled-bear-notes` | _no match_ | `skill..tmp.openai-api-troubleshooting` | _no match_ | _no match_ | `skill.uncategorized.bear-notes` | `skill.vendor_imports.figma-create-design-system-rules` |
| `bundled-discord` | _no match_ | `skill..tmp.chat-sdk` | `skill.plugins.access` | _no match_ | `skill.uncategorized.discord` | _no match_ |
| `bundled-slack` | _no match_ | `skill..tmp.google-calendar` | `skill.plugins.claude-md-improver` | _no match_ | `skill.uncategorized.slack` | _no match_ |
| `bundled-github` | `methodology.debug` | `skill..tmp.chat-sdk` | _no match_ | _no match_ | `skill.uncategorized.github` | _no match_ |
| `bundled-spotify` | _no match_ | `skill..tmp.netlify-frameworks` | _no match_ | _no match_ | `skill.uncategorized.spotify-player` | _no match_ |
| `bundled-weather` | _no match_ | `skill..tmp.google-calendar-daily-brief` | _no match_ | _no match_ | `skill.uncategorized.weather` | _no match_ |
| `bundled-notion` | _no match_ | `skill..tmp.google-slides` | `skill.plugins.documents` | _no match_ | `skill.uncategorized.notion` | _no match_ |
| `vendor-aspnet` | _no match_ | `skill..tmp.openai-api-troubleshooting` | `skill.plugins.m5-onboard` | _no match_ | _no match_ | `skill.vendor_imports.aspnet-core` |
| `vendor-chatgpt-apps` | _no match_ | `skill..tmp.twilio-conversations-classic-api` | `skill.plugins.build-mcp-app` | _no match_ | _no match_ | `skill.vendor_imports.chatgpt-apps` |
| `vendor-figma` | `methodology.default` | `skill..tmp.browser` | `skill.plugins.mcp-integration` | _no match_ | _no match_ | `skill.vendor_imports.figma` |
| `vendor-cloudflare-deploy` | _no match_ | `skill..tmp.durable-objects` | _no match_ | _no match_ | _no match_ | `skill.vendor_imports.cloudflare-deploy` |
| `vendor-vercel-deploy` | _no match_ | `skill..tmp.netlify-frameworks` | _no match_ | _no match_ | _no match_ | `skill.vendor_imports.vercel-deploy` |
| `vendor-playwright` | _no match_ | `skill..tmp.browser` | _no match_ | _no match_ | `skill.uncategorized.himalaya` | `skill.vendor_imports.playwright` |

## N-best alternatives (top-2 below selected)

Auxiliary signal — what other targets the selector considered.
A downstream agent can use this to recover when the top-1 is
wrong but the correct skill ranks #2 or #3.

| Task | root | curated/.tmp | curated/plugins | curated/skills | curated/uncategorized | curated/vendor_imports |
| --- | --- | --- | --- | --- | --- | --- |
| `methodology-review` | `methodology.request_review`, `review.task` | `skill..tmp.finishing-a-development-branch`, `skill..tmp.gh-address-comments` | _none_ | _none_ | _none_ | _none_ |
| `methodology-plan` | `methodology.plan`, `code.change` | `skill..tmp.subagent-driven-development`, `skill..tmp.using-git-worktrees` | _none_ | _none_ | `skill.uncategorized.apple-reminders` | _none_ |
| `methodology-debug` | `code.change` | `skill..tmp.browser`, `skill..tmp.chunk` | _none_ | _none_ | _none_ | _none_ |
| `methodology-finish` | `code.change`, `methodology.bootstrap` | `skill..tmp.finding-discovery`, `skill..tmp.fix-finding` | _none_ | _none_ | _none_ | _none_ |
| `methodology-skill-authoring` | `methodology.request_review`, `review.task` | `skill..tmp.browser`, `skill..tmp.figma-create-new-file` | `skill.plugins.skill-development`, `skill.plugins.agent-development` | _none_ | `skill.uncategorized.skill-creator`, `skill.uncategorized.clawhub` | `skill.vendor_imports.security-best-practices` |
| `methodology-parallel` | `code.change`, `methodology.code_change` | `skill..tmp.attack-path-analysis`, `skill..tmp.finding-discovery` | _none_ | _none_ | _none_ | _none_ |
| `methodology-worktree` | _none_ | `skill..tmp.using-git-worktrees` | _none_ | _none_ | _none_ | _none_ |
| `methodology-request-review` | `methodology.request_review`, `review.task` | `skill..tmp.security-scan`, `skill..tmp.subagent-driven-development` | _none_ | _none_ | _none_ | `skill.vendor_imports.security-best-practices` |
| `plugins-presentations` | _none_ | `skill..tmp.twilio-content-template-builder`, `skill..tmp.twilio-whatsapp-manage-senders` | `skill.plugins.documents` | _none_ | _none_ | _none_ |
| `plugins-spreadsheet` | _none_ | `skill..tmp.twilio-customer-support-architect`, `skill..tmp.twilio-sendgrid-webhooks` | _none_ | _none_ | _none_ | _none_ |
| `plugins-stripe` | `methodology.default`, `methodology.plan` | `skill..tmp.twilio-marketing-promotions-advisor`, `skill..tmp.expo-tailwind-setup` | `skill.plugins.build-mcpb`, `skill.plugins.claude-automation-recommender` | _none_ | _none_ | `skill.vendor_imports.cloudflare-deploy` |
| `plugins-documents` | _none_ | `skill..tmp.sharepoint-word-docs` | _none_ | _none_ | _none_ | _none_ |
| `plugins-build-mcp-server` | _none_ | `skill..tmp.triage-issue`, `skill..tmp.figma-create-new-file` | `skill.plugins.mcp-integration`, `skill.plugins.build-mcpb` | _none_ | `skill.uncategorized.apple-notes` | `skill.vendor_imports.figma`, `skill.vendor_imports.jupyter-notebook` |
| `plugins-build-mcp-app` | _none_ | `skill..tmp.twilio-verify-send-otp`, `skill..tmp.twilio-isv-sms-best-practices` | `skill.plugins.mcp-integration`, `skill.plugins.build-mcp-server` | _none_ | _none_ | _none_ |
| `plugins-claude-md-improver` | _none_ | `skill..tmp.finishing-a-development-branch`, `skill..tmp.browser` | `skill.plugins.mcp-integration`, `skill.plugins.hook-development` | _none_ | _none_ | _none_ |
| `plugins-frontend-design` | _none_ | `skill..tmp.gantt-chart-visualization`, `skill..tmp.twilio-email-deliverability-advisor` | _none_ | _none_ | _none_ | _none_ |
| `plugins-agent-development` | `methodology.request_review`, `review.task` | `skill..tmp.twilio-cli-reference`, `skill..tmp.security-scan` | `skill.plugins.stripe-projects`, `skill.plugins.skill-development` | _none_ | _none_ | `skill.vendor_imports.security-best-practices` |
| `plugins-skill-development` | _none_ | `skill..tmp.requesting-code-review`, `skill..tmp.receiving-code-review` | `skill.plugins.stripe-projects`, `skill.plugins.mcp-integration` | _none_ | `skill.uncategorized.skill-creator`, `skill.uncategorized.clawhub` | _none_ |
| `skills-imagegen` | _none_ | `skill..tmp.geospatial-and-cartographic-visualization`, `skill..tmp.visualization-strategy-and-critique` | _none_ | _none_ | _none_ | _none_ |
| `skills-openai-docs` | _none_ | `skill..tmp.uml-and-software-architecture-visualization`, `skill..tmp.openai-platform-api-key` | _none_ | _none_ | `skill.uncategorized.openai-image-gen` | _none_ |
| `skills-skill-installer` | _none_ | `skill..tmp.twilio-enterprise-knowledge`, `skill..tmp.figma-create-new-file` | `skill.plugins.skill-development` | _none_ | `skill.uncategorized.clawhub` | `skill.vendor_imports.jupyter-notebook` |
| `bundled-1password` | _none_ | `skill..tmp.circleci-cli` | _none_ | _none_ | `skill.uncategorized.songsee` | _none_ |
| `bundled-apple-notes` | _none_ | `skill..tmp.twilio-content-template-builder`, `skill..tmp.twilio-whatsapp-manage-senders` | `skill.plugins.documents`, `skill.plugins.cardputer-buddy` | _none_ | `skill.uncategorized.bear-notes`, `skill.uncategorized.skill-creator` | `skill.vendor_imports.winui-app` |
| `bundled-apple-reminders` | _none_ | `skill..tmp.outlook-calendar-daily-brief`, `skill..tmp.twilio-agent-augmentation-architect` | _none_ | _none_ | _none_ | _none_ |
| `bundled-bear-notes` | _none_ | `skill..tmp.finishing-a-development-branch` | _none_ | _none_ | `skill.uncategorized.himalaya`, `skill.uncategorized.apple-notes` | `skill.vendor_imports.vercel-deploy` |
| `bundled-discord` | _none_ | `skill..tmp.gmail`, `skill..tmp.twilio-messaging-webhooks` | _none_ | _none_ | _none_ | _none_ |
| `bundled-slack` | _none_ | `skill..tmp.heygen-video`, `skill..tmp.hubspot` | _none_ | _none_ | `skill.uncategorized.bluebubbles` | _none_ |
| `bundled-github` | `code.change` | `skill..tmp.uml-and-software-architecture-visualization`, `skill..tmp.gh-address-comments` | _none_ | _none_ | _none_ | _none_ |
| `bundled-spotify` | _none_ | `skill..tmp.react-and-nextjs-data-visualization`, `skill..tmp.react-best-practices` | _none_ | _none_ | _none_ | _none_ |
| `bundled-weather` | _none_ | `skill..tmp.outlook-calendar-daily-brief` | _none_ | _none_ | _none_ | _none_ |
| `bundled-notion` | _none_ | `skill..tmp.hubspot`, `skill..tmp.twilio-content-template-builder` | _none_ | _none_ | `skill.uncategorized.bear-notes` | _none_ |
| `vendor-aspnet` | _none_ | `skill..tmp.finishing-a-development-branch`, `skill..tmp.build-chatgpt-app` | _none_ | _none_ | _none_ | `skill.vendor_imports.jupyter-notebook`, `skill.vendor_imports.chatgpt-apps` |
| `vendor-chatgpt-apps` | _none_ | `skill..tmp.openai-platform-api-key`, `skill..tmp.frontend-testing-debugging` | `skill.plugins.cardputer-buddy` | _none_ | _none_ | `skill.vendor_imports.winui-app` |
| `vendor-figma` | _none_ | `skill..tmp.twilio-webhook-architecture`, `skill..tmp.figma-code-connect` | _none_ | _none_ | _none_ | `skill.vendor_imports.figma-create-design-system-rules`, `skill.vendor_imports.figma-implement-design` |
| `vendor-cloudflare-deploy` | _none_ | `skill..tmp.building-mcp-server-on-cloudflare` | _none_ | _none_ | _none_ | _none_ |
| `vendor-vercel-deploy` | _none_ | `skill..tmp.react-and-nextjs-data-visualization`, `skill..tmp.react-best-practices` | _none_ | _none_ | _none_ | _none_ |
| `vendor-playwright` | _none_ | `skill..tmp.twilio-voice-twiml` | _none_ | _none_ | _none_ | _none_ |

## Aggregate

| Source | Tasks matched (top-1) | Tasks unmatched |
| --- | ---: | ---: |
| `root` | 13 | 24 |
| `curated/.tmp` | 37 | 0 |
| `curated/plugins` | 24 | 13 |
| `curated/skills` | 5 | 32 |
| `curated/uncategorized` | 22 | 15 |
| `curated/vendor_imports` | 16 | 21 |

Caveats:

- Matched ≠ correct. A match may be a false positive (e.g. requests
  containing common words like `documents` routing to the OpenClaw
  `documents` skill regardless of intent).
- The root AgentMakefile encodes methodology workflows; OpenClaw
  curated modules encode application-domain skills. They cover
  different task spaces — improvements aren't additive.
- The curator-generated modules carry absolute `implementation.source`
  paths pointing at the local Codex/Claude install, so this report's
  results are reproducible only on the machine that produced them.

## Routing-precision history (hand judged)

Two task sets are measured. The first ten-task probe (initial commits)
revealed the failure mode; the expanded 37-task baseline below covers
29 OpenClaw-domain tasks with hand-curated ground truth (the remaining
8 are methodology tasks that route via the root AgentMakefile).

### 37-task baseline (current, `benchmarks/clawbench-routing-tasks.jsonl`)

| Stage | Top-1 routed to ground-truth target |
| --- | ---: |
| Clean baseline (curator-promoted, no feedback) | 13 / 29 |
| + closed-loop feedback (one iteration) | **29 / 29** |

### Original 10-task probe (history)

| Stage | Top-1 correct | N-best (top-3) contains correct |
| --- | ---: | ---: |
| Initial promote (curator only) | 0 / 6 | n/a |
| + tie-break by matched-term length (`3064c96`) | 1 / 6 | n/a |
| + N-best alternatives surfaced (`7b642a4`) | 1 / 6 | 2 / 6 |
| + dep-proximity & prompt visibility & full dream + patch class set (`7fc7b41..2fa9b03`) | 1 / 6 | 2 / 6 |
| + closed-loop feedback (`bff0182`) | 6 / 6 | 6 / 6 |

Concrete movers per commit:

- `3064c96` flipped `plugins-presentations` from `plugins.documents`
  to `plugins.presentations` by breaking score ties on matched-term
  length.
- `7b642a4` surfaces `vendor_imports.aspnet-core` as an alternative
  on `vendor-aspnet` so a downstream LLM agent can recover from a
  wrong top-1.
- `7fc7b41` re-ranks alternatives so dep-adjacent targets bubble up
  ahead of unrelated score-ties (no movement on this task set, but
  active on any AgentMakefile that uses `target.deps`).
- `7a20cec` injects a `## Routing Decision` section into the prompt
  prefix so the LLM literally sees primary + dep closure + N-best
  alternatives. Doesn't move routing numbers; expands the LLM's
  recovery surface at inference time.
- `22b57b1` / `0c32c59` / `93e0d9f` / `32c3edc` ship the full dream
  detector set (openclaw duplicates, recurring routing gaps, missing
  match terms, drifted permissions). They produce candidate patches
  but don't fire until matching evidence is fed in.
- `8a1c583` / `2fa9b03` complete the patch-class surface (10/10
  classes including add_target, deprecate_skill, update_permission_
  guard, split_module, …). Mechanism only — actual routing changes
  arrive when the curator/dream emit proposals using them.

Closed-loop demonstration:

- `demos/evo-feedback-loop-demo/run.py` runs the missing piece end-
  to-end: capture plugin_payload evidence from a routing sweep,
  attach user_feedback for the 5 tasks where ground truth is
  known, then dream → patch (update_match_terms + prune_match_
  terms) → evaluate → promote. The mutation lands in the local
  modules/openclaw-curated/ (per-machine, gitignored) so the next
  routing sweep picks it up. Result: all 6 OpenClaw-domain tasks
  route to the correct skill in their respective category module
  on top-1. To reset and re-run, regenerate the corpus with the
  tier runner then re-promote, or run the demo again (idempotent
  on already-applied patches).
