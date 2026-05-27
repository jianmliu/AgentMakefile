# AgentMakefile Harness Benchmark CLI Spec

Status: proposed; first `agentmf benchmark harness` slice implemented.

Date: 2026-05-26.

## Summary

`agentmf benchmark harness` should make AgentMakefile's harness-management
value measurable. AgentMakefile's main claim is that scattered agent harnesses
can be imported, normalized into structured pipelines, compiled back to native
host artifacts, and selected per request more efficiently than loading broad
Markdown or skill indexes.

The benchmark compares request-specific AgentMakefile pipeline selection
against scattered or all-in-one guidance loading patterns, then reports token
savings, cache stability, operation coverage, selection quality, source
coverage, and explainability.

The benchmark is deterministic. It should not call a model, execute tools, or
use an LLM judge in the first version. It measures the artifacts AgentMakefile
already owns:

- selected targets
- selected skills
- dependency closure
- selected pipeline size
- prompt/context/guard/permission/fallback operation counts
- stable prefix size and hash
- baseline kind, sources, size, and hash
- selected native skill artifact paths
- selection trace and match evidence
- expected-vs-actual skill selection when benchmark cases provide labels

## Product Claim

AgentMakefile is useful as a structured agent-harness entry point when it can
prove these outcomes:

- It can ingest scattered harness inputs such as `SKILL.md`, `AGENTS.md`,
  `CLAUDE.md`, and framework-specific modules into a common routing graph.
- It loads fewer stable prompt tokens for the same request than all-in-one
  guidance or all-skills loading.
- It keeps stable prompt chunks deterministic, hashable, and cache-friendly.
- It selects the expected target, skill closure, and pipeline operations for
  common requests.
- It explains why each target or skill was selected.
- It compiles and syncs the same structured harness source across hosts.
- It preserves host-native compatibility while providing a better control
  plane for selection and prompt-prefix assembly.

`agentmf benchmark harness` is the primary command that produces this evidence.
A narrower `agentmf benchmark skills` command remains a possible compatibility
view focused only on native skill selection.

The broader competition-style suite design lives in
[agentmf_harness_benchmark_suite_spec.md](agentmf_harness_benchmark_suite_spec.md).
That suite extends this command from deterministic harness-management metrics
to optional execution benchmarks with host adapters, verifiers, cost, latency,
and pass-rate metrics.

## Goals

- Compare AgentMakefile request routing against all-in-one prompt, harness, or
  skill baselines.
- Compare authored AgentMakefile modules and imported guidance modules using
  the same benchmark payload shape.
- Quantify stable prompt size and approximate token savings.
- Report baseline kind, source files, content hash, and approximate tokens.
- Show stable prefix hashes so cache reuse can be inspected across cases.
- Report selected pipeline size and operation group counts.
- Report guard/permission coverage for selected pipelines.
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
agentmf benchmark harness \
  --file modules/superpowers/AgentMakefile \
  --case "write an implementation plan" \
  --case "implement this feature" \
  --format markdown
```

### Labeled Cases

```bash
agentmf benchmark harness \
  --file modules/oh-my-openagent/AgentMakefile \
  --cases-file benchmarks/omo.skill-routing.yaml \
  --host codex \
  --format json
```

### Compare Against Existing Skill Roots

```bash
agentmf benchmark harness \
  --file /tmp/scanned-superpowers.AgentMakefile \
  --baseline all-skills \
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
--baseline agents-md|claude-md|skills-index|baseline-file|all-skills|none
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
- `selected_pipeline_size`
- `prompt_ops`
- `context_ops`
- `guard_ops`
- `permission_ops`
- `fallback_ops`
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

Baselines represent what a host or user would have loaded without structured
AgentMakefile routing. Each baseline records its kind, source paths, content
size, approximate tokens, and hash so benchmark output can distinguish
"smaller because selected" from "different because measured against a smaller
source."

### `agents-md`

Compile or render the all-in-one generic `AGENTS.md` backend and compare the
selected stable prefix against that output.

### `claude-md`

Compile or render the all-in-one `CLAUDE.md` backend and compare the selected
stable prefix against that output.

### `skills-index`

Compile or render `skills/index.md` and compare selected skills against the
complete generated skill catalog.

This is the compatibility baseline for systems that already rely on a skill
index but do not have a structured dependency and pipeline selector.

### `all-skills`

Read every `*/SKILL.md` under `--baseline-skills-dir` roots, concatenate them
in deterministic path order, and compare selected stable prefix size against
loading all installed skills.

This is the clearest baseline for showing the value of request-time harness
selection: AgentMakefile should select the relevant target and skill closure
instead of asking the model to inspect every installed skill.

### `baseline-file`

Read a caller-provided file and use it as the baseline. This is useful for
comparing against an existing hand-written `AGENTS.md`, `CLAUDE.md`, or
`skills/index.md`.

### `none`

Disable baseline comparison while still reporting selected targets, selected
skills, pipeline metrics, stable prefix hash, guard coverage, permission
coverage, and selection trace quality.

## JSON Output Shape

```json
{
  "ok": true,
  "harness_benchmark": {
    "version": 1,
    "mode": "harness_benchmark",
    "host": "codex",
    "backend": "agents-fragments",
    "baseline": "all-skills",
    "summary": {
      "case_count": 1,
      "total_selected_pipeline_size": 23,
      "stable_prefix_hashes": ["sha256:..."]
    },
    "cases": [
      {
        "id": "case-1",
        "request": "implement this feature",
        "selected_targets": ["methodology.code_change"],
        "selected_skills": [
          "superpowers:using-superpowers",
          "superpowers:verification-before-completion",
          "superpowers:test-driven-development"
        ],
        "pipeline_metrics": {
          "selected_pipeline_size": 23,
          "prompt_ops": 2,
          "context_ops": 1,
          "guard_ops": 19,
          "permission_ops": 0,
          "fallback_ops": 0
        },
        "stable_prefix_hash": "sha256:...",
        "baseline": {
          "kind": "all-skills",
          "path": "<all-skills>",
          "sources": ["/home/user/.codex/skills/tdd/SKILL.md"],
          "chars": 114020,
          "approx_tokens": 28505,
          "hash": "sha256:..."
        },
        "baseline_savings": {
          "chars": 107068,
          "approx_tokens": 26767
        },
        "guard_permission_coverage": {
          "guard_ops": 19,
          "permission_ops": 0
        },
        "selection_trace_quality": {
          "has_selected_target": true,
          "candidate_count": 4,
          "has_match_details": true
        }
      }
    ]
  },
  "diagnostics": []
}
```

## Markdown Output Shape

```markdown
# AgentMakefile Harness Benchmark

- Cases: 1
- Backend: agents-fragments
- Baseline: all-skills

| Case | Selected Targets | Baseline | Savings Tokens | Pipeline Ops | Prompt Ops | Context Ops | Guard Ops | Permission Ops |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| case-1 | methodology.code_change | all-skills | 26767 | 23 | 2 | 1 | 19 | 0 |
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
agentmf benchmark harness \
  --file modules/superpowers/AgentMakefile \
  --case "write an implementation plan" \
  --case "implement this feature" \
  --format markdown

agentmf benchmark harness \
  --file modules/oh-my-openagent/AgentMakefile \
  --case "autonomous implementation" \
  --format json
```

## First Implementation Slice

The first implementation should be intentionally small:

1. Add `agentmf benchmark harness`.
2. Support `--file`, `--case`, `--host`, `--backend`, `--format json|markdown`,
   and baseline choices `agents-md`, `claude-md`, `skills-index`,
   `baseline-file`, `all-skills`, and `none`.
3. Use `create_plugin_payload` for each case.
4. Use the payload's existing `trace.comparison` for baseline and savings.
5. Report selected pipeline size, operation counts, stable prefix hash,
   guard/permission coverage, and compact selection-trace quality.
6. Add cases files, report writing, and mismatch handling in later slices.

This keeps the first benchmark useful for demos while avoiding a large cases
file parser in the first pass.
