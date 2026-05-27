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
| `bundled-1password` | _no match_ | `skill..tmp.openai-platform-api-key` | `skill.plugins.documents` | _no match_ | `skill.uncategorized.songsee` | _no match_ |
| `bundled-apple-notes` | _no match_ | `skill..tmp.hubspot` | `skill.plugins.documents` | `skill.skills.imagegen` | `skill.uncategorized.bear-notes` | `skill.vendor_imports.jupyter-notebook` |
| `plugins-presentations` | _no match_ | `skill..tmp.hubspot` | `skill.plugins.presentations` | _no match_ | `skill.uncategorized.bear-notes` | _no match_ |
| `plugins-spreadsheet` | _no match_ | `skill..tmp.finishing-a-development-branch` | _no match_ | _no match_ | `skill.uncategorized.himalaya` | _no match_ |
| `vendor-aspnet` | _no match_ | `skill..tmp.openai-api-troubleshooting` | `skill.plugins.m5-onboard` | _no match_ | _no match_ | `skill.vendor_imports.jupyter-notebook` |
| `vendor-stripe` | `omo.plan` | `skill..tmp.uml-and-software-architecture-visualization` | `skill.plugins.build-mcpb` | _no match_ | _no match_ | `skill.vendor_imports.figma-create-design-system-rules` |

## N-best alternatives (top-2 below selected)

Auxiliary signal — what other targets the selector considered.
A downstream agent can use this to recover when the top-1 is
wrong but the correct skill ranks #2 or #3.

| Task | root | curated/.tmp | curated/plugins | curated/skills | curated/uncategorized | curated/vendor_imports |
| --- | --- | --- | --- | --- | --- | --- |
| `methodology-review` | `review.task`, `methodology.request_review` | `skill..tmp.finishing-a-development-branch`, `skill..tmp.gh-address-comments` | _none_ | _none_ | _none_ | _none_ |
| `methodology-plan` | `methodology.plan`, `code.change` | `skill..tmp.subagent-driven-development`, `skill..tmp.using-git-worktrees` | _none_ | _none_ | `skill.uncategorized.apple-reminders` | _none_ |
| `methodology-debug` | `code.change` | `skill..tmp.browser`, `skill..tmp.chunk` | _none_ | _none_ | _none_ | _none_ |
| `methodology-finish` | `methodology.default`, `methodology.bootstrap` | `skill..tmp.finding-discovery`, `skill..tmp.fix-finding` | _none_ | _none_ | _none_ | _none_ |
| `bundled-1password` | _none_ | `skill..tmp.circleci-cli` | _none_ | _none_ | _none_ | _none_ |
| `bundled-apple-notes` | _none_ | `skill..tmp.twilio-content-template-builder`, `skill..tmp.twilio-whatsapp-manage-senders` | `skill.plugins.cardputer-buddy` | _none_ | `skill.uncategorized.skill-creator`, `skill.uncategorized.apple-notes` | `skill.vendor_imports.winui-app` |
| `plugins-presentations` | _none_ | `skill..tmp.twilio-content-template-builder`, `skill..tmp.twilio-whatsapp-manage-senders` | `skill.plugins.documents` | _none_ | _none_ | _none_ |
| `plugins-spreadsheet` | _none_ | `skill..tmp.twilio-customer-support-architect`, `skill..tmp.twilio-sendgrid-webhooks` | _none_ | _none_ | _none_ | _none_ |
| `vendor-aspnet` | _none_ | `skill..tmp.finishing-a-development-branch`, `skill..tmp.build-chatgpt-app` | _none_ | _none_ | _none_ | `skill.vendor_imports.chatgpt-apps`, `skill.vendor_imports.aspnet-core` |
| `vendor-stripe` | `spec.breakdown`, `methodology.plan` | `skill..tmp.twilio-marketing-promotions-advisor`, `skill..tmp.expo-tailwind-setup` | `skill.plugins.claude-automation-recommender`, `skill.plugins.configure` | _none_ | _none_ | `skill.vendor_imports.cloudflare-deploy` |

## Aggregate

| Source | Tasks matched (top-1) | Tasks unmatched |
| --- | ---: | ---: |
| `root` | 5 | 5 |
| `curated/.tmp` | 10 | 0 |
| `curated/plugins` | 8 | 2 |
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

Three commits attempt to improve OpenClaw routing precision; each
commit's contribution is measured against the previous baseline on
the 6 OpenClaw-domain tasks (the 4 methodology tasks always route
correctly via the root AgentMakefile).

| Stage | Top-1 correct | N-best (top-3) contains correct |
| --- | ---: | ---: |
| Initial promote (curator only) | 0 / 6 | n/a |
| + tie-break by matched-term length (`3064c96`) | 1 / 6 | n/a |
| + N-best alternatives surfaced (`7b642a4`) | 1 / 6 | 2 / 6 |

Concrete movers under each commit:

- `3064c96` flipped `plugins-presentations` from `plugins.documents`
  to `plugins.presentations` by breaking score ties on matched-term
  length — the new `update_match_terms` proposal's long phrase
  finally beats the neighbour's stray single word `Create`.
- `7b642a4` surfaces `vendor_imports.aspnet-core` as an alternative
  on `vendor-aspnet` even though top-1 still points elsewhere; a
  downstream LLM agent can recover from the wrong top-1 because the
  right skill is visible at rank #2/#3.

Outstanding gap (still 4/6 OpenClaw tasks routing wrong):

- `bundled-1password`, `bundled-apple-notes`, `plugins-spreadsheet`,
  `vendor-stripe` — these all have very generic neighbour skills with
  overly-broad `match.user_intent` terms (`Create`, single-word
  triggers). Curing them needs either user-feedback evidence that
  drives the `missing_match_terms` dream detector to attach
  distinguishing terms to the correct skill, or a follow-up patch
  class that prunes overly-broad terms from the neighbour skills.
