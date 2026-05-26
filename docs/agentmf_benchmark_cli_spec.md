# AgentMakefile Benchmark CLI Spec

Status: proposed.

Date: 2026-05-26.

## Summary

`agentmf benchmark skills` should make AgentMakefile's value measurable. It
compares request-specific AgentMakefile skill selection against scattered or
all-in-one skill loading patterns, then reports token savings, cache stability,
selection quality, and explainability.

The benchmark is deterministic. It should not call a model, execute tools, or
use an LLM judge in the first version. It measures the artifacts AgentMakefile
already owns:

- selected targets
- selected skills
- dependency closure
- stable prefix size and hash
- all-in-one baseline size
- selected native skill artifact paths
- selection trace and match evidence
- expected-vs-actual skill selection when benchmark cases provide labels

## Product Claim

AgentMakefile is better than scattered `SKILL.md`, `AGENTS.md`, `CLAUDE.md`,
and hand-maintained skill indexes when it can prove these outcomes:

- It loads fewer stable prompt tokens for the same request.
- It keeps stable prompt chunks deterministic and cache-friendly.
- It selects the expected skill closure for common requests.
- It explains why each skill was selected.
- It compiles and syncs the same skill source across hosts.

`agentmf benchmark skills` is the command that produces this evidence.

## Goals

- Compare AgentMakefile request routing against all-in-one prompt or skill
  baselines.
- Quantify stable prompt size and approximate token savings.
- Show stable prefix hashes so cache reuse can be inspected across cases.
- Validate `selected_skills` against optional expected labels.
- Report selection trace evidence in a compact human-readable form.
- Support benchmark cases for authored modules, scanned skill-index modules,
  and guidance-index modules generated from `AGENTS.md`, `CLAUDE.md`, or
  standalone `SKILL.md` inputs.
- Emit JSON for CI and Markdown for demos, docs, and README examples.

## Non-Goals

- Judging final answer quality with an LLM.
- Running model providers or agent tool loops.
- Timing hosted model latency.
- Installing or syncing skills as part of the benchmark.
- Mutating generated artifacts unless `--write` is explicitly used for report
  output.
- Replacing lower-level commands such as `agentmf plugin payload`,
  `agentmf prompt`, `agentmf compile`, or `agentmf skills sync`.

## Command Surface

### Minimal Invocation

```bash
agentmf benchmark skills \
  --file modules/superpowers/AgentMakefile \
  --case "write an implementation plan" \
  --case "implement this feature" \
  --format markdown
```

### Labeled Cases

```bash
agentmf benchmark skills \
  --file modules/oh-my-openagent/AgentMakefile \
  --cases-file benchmarks/omo.skill-routing.yaml \
  --host codex \
  --format json
```

### Compare Against Existing Skill Roots

```bash
agentmf benchmark skills \
  --file /tmp/scanned-superpowers.AgentMakefile \
  --baseline-skills-dir ~/.codex/skills \
  --case "debug failing test" \
  --format markdown
```

## Options

```text
--file AgentMakefile              # source AgentMakefile, skill-index, or guidance-index module
--host codex|claude-code|generic  # controls plugin payload host profile
--case TEXT                       # repeatable inline benchmark request
--cases-file PATH                 # YAML or JSON benchmark cases
--target NAME                     # optional explicit target baseline case
--backend agents-fragments|claude-fragments
--baseline agents-md|claude-md|skills-index|all-skills|none
--baseline-file PATH              # explicit all-in-one baseline file
--baseline-skills-dir PATH        # repeatable SKILL.md root for all-skills baseline
--fail-on-mismatch                # nonzero exit if expected labels do not match
--out PATH                        # report output path
--write                           # write report to --out
--format json|markdown|text
```

Default values:

- `--host generic`
- `--backend agents-fragments`
- `--baseline agents-md`
- `--format markdown`
- `--write false`

## Cases File Format

YAML:

```yaml
version: 1
cases:
  - id: write-plan
    request: write an implementation plan
    expected_targets:
      - methodology.plan
    expected_skills:
      - superpowers:using-superpowers
      - superpowers:verification-before-completion
      - superpowers:writing-plans

  - id: autonomous-implementation
    request: autonomous implementation
    expected_targets:
      - omo.ultrawork
    expected_skills:
      - omo:ultrawork
      - omo:category-routing
```

Rules:

- `id` is optional for inline `--case` values and required in files.
- `request` is required.
- `expected_targets` is optional.
- `expected_skills` is optional.
- Case order is preserved in output.
- Unknown keys are errors, not ignored, so benchmark data stays clean.

## Metrics

Each case should report:

- `request`
- `selected_targets`
- `target_closure`
- `selected_skills`
- `skill_artifacts`
- `stable_prefix_chars`
- `stable_prefix_approx_tokens`
- `stable_prefix_hash`
- `baseline_chars`
- `baseline_approx_tokens`
- `savings_chars`
- `savings_approx_tokens`
- `savings_percent`
- `selection_match`
- `matched_terms`
- `match_details`
- `expected_targets_match`
- `expected_skills_match`

Suite-level summary should report:

- `case_count`
- `matched_target_cases`
- `matched_skill_cases`
- `average_savings_tokens`
- `median_savings_tokens`
- `average_savings_percent`
- `unique_stable_prefix_hashes`
- `diagnostics`

## Baselines

### `agents-md`

Compile or render the all-in-one generic `AGENTS.md` backend and compare the
selected stable prefix against that output.

### `claude-md`

Compile or render the all-in-one `CLAUDE.md` backend and compare the selected
stable prefix against that output.

### `skills-index`

Compile or render `skills/index.md` and compare selected skills against the
complete generated skill catalog.

### `all-skills`

Read every `*/SKILL.md` under `--baseline-skills-dir` roots, concatenate them
in deterministic path order, and compare selected stable prefix size against
loading all installed skills.

### `baseline-file`

Read a caller-provided file and use it as the baseline. This is useful for
comparing against an existing hand-written `AGENTS.md`, `CLAUDE.md`, or
`skills/index.md`.

## JSON Output Shape

```json
{
  "ok": true,
  "version": 1,
  "agentmakefile_path": "modules/superpowers/AgentMakefile",
  "host": "codex",
  "backend": "agents-fragments",
  "baseline": {
    "kind": "agents-md",
    "chars": 14110,
    "approx_tokens": 3528
  },
  "summary": {
    "case_count": 2,
    "matched_target_cases": 2,
    "matched_skill_cases": 2,
    "average_savings_tokens": 2400,
    "median_savings_tokens": 2400,
    "average_savings_percent": 68.1,
    "unique_stable_prefix_hashes": 2
  },
  "cases": [
    {
      "id": "write-plan",
      "request": "write an implementation plan",
      "selected_targets": ["methodology.plan"],
      "target_closure": ["methodology.bootstrap", "methodology.plan"],
      "selected_skills": [
        "superpowers:using-superpowers",
        "superpowers:verification-before-completion",
        "superpowers:writing-plans"
      ],
      "expected_targets_match": true,
      "expected_skills_match": true,
      "stable_prefix": {
        "chars": 3131,
        "approx_tokens": 783,
        "hash": "sha256:..."
      },
      "savings": {
        "chars": 10979,
        "approx_tokens": 2745,
        "percent": 77.8
      },
      "selection": {
        "target": "methodology.plan",
        "matched_terms": ["implementation plan"],
        "match_details": [
          {
            "term": "implementation plan",
            "method": "substring",
            "score": 100,
            "evidence": "implementation plan"
          }
        ]
      }
    }
  ],
  "diagnostics": []
}
```

## Markdown Output Shape

```markdown
# AgentMakefile Skill Benchmark

Source: `modules/superpowers/AgentMakefile`
Host: `codex`
Baseline: `agents-md`, ~3528 tokens

| Case | Selected Target | Selected Skills | Prefix Tokens | Savings | Match |
|---|---:|---:|---:|---:|---|
| write-plan | methodology.plan | 3 | 783 | 2745 tokens / 77.8% | pass |

## write-plan

Request: `write an implementation plan`

Selected skills:
- `superpowers:using-superpowers`
- `superpowers:verification-before-completion`
- `superpowers:writing-plans`

Selection evidence:
- `implementation plan` matched by `substring`, score 100

Stable prefix:
- chars: 3131
- approx tokens: 783
- hash: `sha256:...`
```

## Exit Codes

- `0`: benchmark completed and all labeled expectations matched.
- `1`: benchmark completed but one or more expectations mismatched when
  `--fail-on-mismatch` is set.
- `2`: invalid CLI arguments or invalid cases file.
- `3`: AgentMakefile load, compile, or selection diagnostics contained errors.

Without `--fail-on-mismatch`, expectation mismatches should be reported but
should not cause a nonzero exit.

## Implementation Notes

The benchmark should reuse existing runtime primitives:

- `create_plugin_payload` for request-time selection, stable prefix content,
  selected skills, artifacts, and selection trace.
- `compile_agentmakefile` for `agents-md`, `claude-md`, and `skills-index`
  baselines.
- The existing approximate token estimator `ceil(chars / 4)` for consistency
  with prompt and plugin payloads.
- The existing diagnostics system.

No new selector should be introduced. Benchmarking must measure the same
selection behavior used by `agentmf plugin payload`.

## Validation Strategy

Unit tests should cover:

- inline `--case` values
- YAML cases files with expected targets and expected skills
- invalid cases files with unknown keys
- `agents-md` baseline comparison
- `all-skills` baseline comparison using a temporary `SKILL.md` tree
- JSON output shape
- Markdown output table
- `--fail-on-mismatch` exit behavior

Smoke tests should cover:

```bash
agentmf benchmark skills \
  --file modules/superpowers/AgentMakefile \
  --case "write an implementation plan" \
  --case "implement this feature" \
  --format markdown

agentmf benchmark skills \
  --file modules/oh-my-openagent/AgentMakefile \
  --case "autonomous implementation" \
  --format json
```

## First Implementation Slice

The first implementation should be intentionally small:

1. Add `agentmf benchmark skills`.
2. Support `--file`, `--case`, `--host`, `--backend`, `--baseline agents-md`,
   `--format json|markdown`, and `--fail-on-mismatch`.
3. Use `create_plugin_payload` for each case.
4. Use the payload's existing `trace.comparison` for baseline and savings.
5. Add optional expected target and skill labels only through a cases file in
   the second slice.

This keeps the first benchmark useful for demos while avoiding a large cases
file parser in the first pass.
