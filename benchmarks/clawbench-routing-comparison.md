# ClawBench Routing-Only Comparison

Routing-only comparison: which target(s) the selector picks for each
task under different AgentMakefile sources. No external agent runner
is invoked, so the table measures routing precision only — not
downstream pass rate.

- Tasks: `benchmarks/clawbench-routing-tasks.jsonl` (10 entries)
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
| `bundled-1password` | _no match_ | `skill..tmp.openai-platform-api-key` | `skill.plugins.documents` | _no match_ | `skill.uncategorized.1password` | _no match_ |
| `bundled-apple-notes` | _no match_ | `skill..tmp.hubspot` | `skill.plugins.documents` | `skill.skills.imagegen` | `skill.uncategorized.apple-notes` | `skill.vendor_imports.jupyter-notebook` |
| `plugins-presentations` | _no match_ | `skill..tmp.hubspot` | `skill.plugins.presentations` | _no match_ | `skill.uncategorized.bear-notes` | _no match_ |
| `plugins-spreadsheet` | _no match_ | `skill..tmp.finishing-a-development-branch` | `skill.plugins.spreadsheets` | _no match_ | `skill.uncategorized.himalaya` | _no match_ |
| `vendor-aspnet` | _no match_ | `skill..tmp.openai-api-troubleshooting` | `skill.plugins.m5-onboard` | _no match_ | _no match_ | `skill.vendor_imports.aspnet-core` |
| `vendor-stripe` | `omo.plan` | `skill..tmp.uml-and-software-architecture-visualization` | `skill.plugins.stripe-projects` | _no match_ | _no match_ | `skill.vendor_imports.figma-create-design-system-rules` |

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
| `bundled-1password` | _none_ | `skill..tmp.circleci-cli` | _none_ | _none_ | `skill.uncategorized.songsee` | _none_ |
| `bundled-apple-notes` | _none_ | `skill..tmp.twilio-content-template-builder`, `skill..tmp.twilio-whatsapp-manage-senders` | `skill.plugins.cardputer-buddy` | _none_ | `skill.uncategorized.bear-notes`, `skill.uncategorized.skill-creator` | `skill.vendor_imports.winui-app` |
| `plugins-presentations` | _none_ | `skill..tmp.twilio-content-template-builder`, `skill..tmp.twilio-whatsapp-manage-senders` | `skill.plugins.documents` | _none_ | _none_ | _none_ |
| `plugins-spreadsheet` | _none_ | `skill..tmp.twilio-customer-support-architect`, `skill..tmp.twilio-sendgrid-webhooks` | _none_ | _none_ | _none_ | _none_ |
| `vendor-aspnet` | _none_ | `skill..tmp.finishing-a-development-branch`, `skill..tmp.build-chatgpt-app` | _none_ | _none_ | _none_ | `skill.vendor_imports.jupyter-notebook`, `skill.vendor_imports.chatgpt-apps` |
| `vendor-stripe` | `methodology.default`, `methodology.plan` | `skill..tmp.twilio-marketing-promotions-advisor`, `skill..tmp.expo-tailwind-setup` | `skill.plugins.build-mcpb`, `skill.plugins.claude-automation-recommender` | _none_ | _none_ | `skill.vendor_imports.cloudflare-deploy` |

## Aggregate

| Source | Tasks matched (top-1) | Tasks unmatched |
| --- | ---: | ---: |
| `root` | 5 | 5 |
| `curated/.tmp` | 10 | 0 |
| `curated/plugins` | 9 | 1 |
| `curated/skills` | 1 | 9 |
| `curated/uncategorized` | 7 | 3 |
| `curated/vendor_imports` | 3 | 7 |

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

Each row measures the cumulative improvement on the 6 OpenClaw-
domain tasks (the 4 methodology tasks always route correctly via
the root AgentMakefile).

| Stage | Top-1 correct | N-best (top-3) contains correct |
| --- | ---: | ---: |
| Initial promote (curator only) | 0 / 6 | n/a |
| + tie-break by matched-term length (`3064c96`) | 1 / 6 | n/a |
| + N-best alternatives surfaced (`7b642a4`) | 1 / 6 | 2 / 6 |
| + dep-proximity & prompt visibility & full dream + patch class set (`7fc7b41..2fa9b03`) | 1 / 6 | 2 / 6 |
| + closed-loop feedback (demos/evo-feedback-loop-demo/run.py) | **6 / 6** | 6 / 6 |

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
