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
| `methodology-plan` | `methodology.execute_plan` | `skill..tmp.brainstorming` | `skill.plugins.documents` | _no match_ | `skill.uncategorized.apple-reminders` | _no match_ |
| `methodology-debug` | `methodology.debug` | `skill..tmp.browser` | `skill.plugins.m5-onboard` | _no match_ | `skill.uncategorized.mcporter` | _no match_ |
| `methodology-finish` | `methodology.finish` | `skill..tmp.attack-path-analysis` | `skill.plugins.stripe-projects` | _no match_ | `skill.uncategorized.apple-reminders` | _no match_ |
| `bundled-1password` | _no match_ | `skill..tmp.circleci-cli` | `skill.plugins.documents` | _no match_ | `skill.uncategorized.songsee` | _no match_ |
| `bundled-apple-notes` | _no match_ | `skill..tmp.hubspot` | `skill.plugins.documents` | `skill.skills.imagegen` | `skill.uncategorized.bear-notes` | `skill.vendor_imports.jupyter-notebook` |
| `plugins-presentations` | _no match_ | `skill..tmp.finishing-a-development-branch` | `skill.plugins.documents` | _no match_ | `skill.uncategorized.bear-notes` | _no match_ |
| `plugins-spreadsheet` | _no match_ | `skill..tmp.finishing-a-development-branch` | _no match_ | _no match_ | `skill.uncategorized.himalaya` | _no match_ |
| `vendor-aspnet` | _no match_ | `skill..tmp.finishing-a-development-branch` | `skill.plugins.m5-onboard` | _no match_ | _no match_ | `skill.vendor_imports.jupyter-notebook` |
| `vendor-stripe` | `omo.plan` | `skill..tmp.uml-and-software-architecture-visualization` | `skill.plugins.build-mcpb` | _no match_ | _no match_ | `skill.vendor_imports.cloudflare-deploy` |

## Aggregate

| Source | Tasks matched | Tasks unmatched |
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

## Precision verdict (hand judged)

For each OpenClaw-flavoured task the corresponding correct skill DOES
exist in one of the curated modules. The table below records whether
the selector picked the right skill, a related-but-wrong skill, an
unrelated skill, or nothing.

| Task | Ground-truth skill present? | Best curated match | Verdict |
| --- | --- | --- | --- |
| `methodology-review` | n/a (methodology, not OpenClaw) | `methodology.review` (root) | ✓ correct via root |
| `methodology-plan` | n/a | `methodology.execute_plan` (root) | ✓ correct via root |
| `methodology-debug` | n/a | `methodology.debug` (root) | ✓ correct via root |
| `methodology-finish` | n/a | `methodology.finish` (root) | ✓ correct via root |
| `bundled-1password` | yes — `uncategorized.1password` | `uncategorized.songsee` | ✗ unrelated false positive |
| `bundled-apple-notes` | yes — `uncategorized.apple-notes` | `uncategorized.bear-notes` | ⚠ wrong app, related domain |
| `plugins-presentations` | yes — `plugins.presentations` | `plugins.documents` | ⚠ wrong skill, related domain |
| `plugins-spreadsheet` | yes — `plugins.spreadsheets` | _no match_ | ✗ missed (correct skill exists, not picked) |
| `vendor-aspnet` | yes — `vendor_imports.aspnet-core` | `vendor_imports.jupyter-notebook` | ✗ unrelated false positive |
| `vendor-stripe` | yes — `plugins.stripe-projects` | `plugins.build-mcpb` (and root's `omo.plan` false-positive) | ✗ unrelated false positive |

Headline:

- **4 of 4** methodology tasks routed correctly via the root AgentMakefile.
- **0 of 6** OpenClaw-domain tasks routed to the right skill, even though
  the right skill is present in the curated index for every one of them.
- Promote increased skill coverage from 4/10 to 10/10 raw matches, but
  precision went from 4/4 to 4/10. Net useful routings stayed at 4.

Why: each curated skill's `match.user_intent` is derived from its
description, which often shares broad vocabulary (`documents`,
`create`, `setup`, `notes`) with neighbouring skills. The selector
picks the first matching candidate by score, and when many skills
score similarly on common tokens the choice is effectively arbitrary.

What would close the gap: the `missing_match_terms` dream-mode
detector (spec EVO-005 third bullet, not yet implemented) is the
right place to add the corrective signal — feed it `plugin_payload`
evidence plus user-feedback records that say "this request should
have routed to skill X" and have it emit `update_match_terms`
proposals adding the request's distinctive tokens to skill X's
`match.user_intent`. Without that loop, adding more skills to the
index will keep diluting precision rather than improving it.
