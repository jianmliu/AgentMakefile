# OpenClaw Skills Routing: keyword vs embedding (8-case A/B)

Per-request routing precision for `benchmarks/routing/openclaw-skills.yaml`
against `modules/openclaw-curated/skills/AgentMakefile` (19 skills). This is the
committed result behind the README claim that embedding routing beats the
substring-keyword baseline on this suite.

## What this measures (and what it does not)

- **Selection-only, deterministic, execution-free.** No model is called and no
  SWE-bench-style task is run. Each case asserts which skill target the selector
  picks for a request.
- **Matched ≠ downstream success.** A correct route here does not by itself prove
  better task outcomes; it only measures whether the right skill is selected.
- This is the cheap, fast counterpart to the (pending) execution benchmarks. It
  answers "does the matcher discriminate?", not "does routing improve results?".

## How to reproduce

```bash
# keyword baseline
agentmf benchmark suite \
  --suite benchmarks/routing/openclaw-skills.yaml \
  --adapter deterministic-selection --format text

# MiniLM embedding (sentence-transformers)
agentmf benchmark suite \
  --suite benchmarks/routing/openclaw-skills.yaml \
  --adapter embedding-selection \
  --embedder sentence-transformer --format text
```

Environment for the run below: `agentmf 0.1.0`, `sentence-transformers 5.1.2`,
model `sentence-transformers/all-MiniLM-L6-v2`, macOS / Python 3.9. Embedding run
wall time ~5.3s (model load dominates; the keyword run is sub-second). The
embedding result was identical across two consecutive runs.

## Headline

| Adapter | Matcher | Passed |
| --- | --- | ---: |
| `deterministic-selection` | substring keyword | **1 / 8** |
| `embedding-selection` | MiniLM cosine | **7 / 8** |

## Per-case detail

| Case | Request | Expected | Keyword → | Embedding → (score) |
| --- | --- | --- | --- | --- |
| `tdd-direct` | test driven development | `test-driven-development` | ✗ `plugin-creator` | ✓ (0.43) |
| `brainstorming-session` | brainstorming session | `brainstorming` | ✗ *(no match)* | ✓ (0.44) |
| `subagent-driven` | subagent driven implementation | `subagent-driven-development` | ✓ | ✓ (0.51) |
| `slack-out-of-corpus` | send a slack message | `using-superpowers` | ✗ *(no match)* | ✓ (0.19) |
| `github-comments` | review github comments | `receiving-code-review` | ✗ *(no match)* | ✓ (0.36) |
| `pr-feedback` | address pr feedback | `receiving-code-review` | ✗ `finishing-a-development-branch` | ✓ (0.36) |
| `failing-test-first` | write a failing test first | `test-driven-development` | ✗ `dispatching-parallel-agents` | ✗ `systematic-debugging` (0.35) |
| `ship-code-review` | ship a code review | `receiving-code-review` | ✗ `subagent-driven-development` | ✓ (0.49) |

(Target names abbreviated; full names are `skill.skills.<name>`.)

## Reading the results

- **Keyword fails in two distinct ways.** On 3 cases it returns *no match* at all
  (`brainstorming`, `github-comments`, `slack`), and on 4 cases it confidently
  picks the *wrong* skill via incidental token overlap (e.g. "test driven
  development" → `plugin-creator`, "ship a code review" → `subagent-driven`).
  Substring overlap is both low-recall and, when it fires, low-precision on this
  corpus.
- **Embedding's one miss is a near-neighbour.** `failing-test-first` routes to
  `systematic-debugging` (0.35) instead of `test-driven-development` — semantically
  adjacent ("failing test" reads as a debugging cue). It is a soft miss, not a
  category error.
- **Out-of-corpus behaves as intended.** `slack-out-of-corpus` has no Slack skill
  in this module; embedding falls back to the generic `using-superpowers`
  bootstrap with a deliberately low score (0.19, vs 0.35–0.51 for confident
  routes). The score band separates confident routes from the generic fallback.

## Caveats (do not over-read this)

1. **Small N.** 8 cases, and 1 (`slack-out-of-corpus`) is an intentional
   out-of-corpus probe — effectively 7 in-corpus routing decisions. This is
   enough to show keyword is unusable on this corpus and embedding is materially
   better; it is **not** a precision estimate. Do not quote "87.5%" as an accuracy
   number.
2. **Single corpus, hand-labelled.** Expected targets are author-assigned to the
   semantically closest skill. The labels encode one reasonable intent reading,
   not ground truth.
3. **Reproducible only on the authoring machine — currently.**
   `modules/openclaw-curated/` is `.gitignore`d (it contains ~69 absolute paths
   to a local Codex/Claude skill install). Selection does not read those source
   files — only the module's match terms and descriptions — so the routes are
   inert to the absolute paths, but a third party cannot re-run this suite
   without first regenerating that module locally. A portable, committed fixture
   is needed before this counts as independently reproducible evidence. See the
   recommendation below.
4. **Matched ≠ correct downstream.** This says nothing about whether loading the
   selected skill improves task success. That requires the execution benchmarks
   (`swebench-haiku-3way`, larger cross-repo A/B), which remain pending.

## Recommendation

To make this an independently reproducible artifact, commit a small portable
routing fixture: a sanitized copy of `skills/AgentMakefile` (absolute
`implementation.source` paths stripped or relativised — they are unused by
selection) under a tracked path such as `benchmarks/routing/fixtures/`, and point
the suite's `agentmakefile:` at it. The numbers above should then reproduce on any
machine with `pip install agentmf[embedding]`.
