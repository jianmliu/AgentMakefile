# AgentMakefile Harness Benchmark Suite Spec

Status: proposed.

Date: 2026-05-26.

## Summary

AgentMakefile should be benchmarked like an agent harness, not only like a
prompt compiler. The benchmark suite should compare how different harness
layouts affect request routing, prompt size, cache stability, guard coverage,
tool permissions, and eventually real task success.

The comparison is deliberately host-relative:

```text
same model + same host + different harness organization
```

This keeps AgentMakefile's claim precise. AgentMakefile is not a model and does
not need to beat a model directly. It should prove that structured harness
management gives the same host agent a smaller, more explainable, more
portable, and more reliable instruction surface than scattered skills or
all-in-one Markdown guidance.

## Product Claim

AgentMakefile can compete in harness benchmarks by showing that it:

- imports scattered `SKILL.md`, `AGENTS.md`, `CLAUDE.md`, framework modules,
  and host-specific guidance into a common harness graph;
- selects a request-specific target, skill closure, and pipeline instead of
  loading every available instruction;
- compiles the same structured harness source into native Codex, Claude Code,
  Cursor, OpenCode, and generic Markdown artifacts;
- provides selection traces, stable prefix hashes, guard and permission
  coverage, and output contracts as measurable benchmark artifacts;
- can later run the same benchmark tasks through host adapters to compare pass
  rate, cost, latency, and retry behavior.

## Benchmark Layers

### Layer 1: Harness Management Benchmark

This layer is deterministic and does not call a model. It is the current
`agentmf benchmark harness` direction.

It measures whether AgentMakefile can organize and select harness content better
than broad baseline loading.

Inputs:

- AgentMakefile module
- scanned skill-index module
- imported guidance module
- benchmark case requests
- optional expected target and skill labels
- baseline sources such as `AGENTS.md`, `CLAUDE.md`, `skills/index.md`, all
  installed `SKILL.md` files, or a caller-provided file

Outputs:

- selected target
- dependency closure
- selected skills
- selected pipeline operations
- stable prefix size and hash
- baseline size and hash
- approximate token savings
- selection trace quality
- guard and permission coverage
- native skill artifact paths

This layer proves harness structure, selection, and cacheability.

### Layer 2: Harness Execution Benchmark

This layer runs real tasks through one or more host adapters.

It should compare AgentMakefile-managed harnesses against native or scattered
baselines while keeping the model, host, task, repository, and tool permission
profile fixed.

Example comparison:

```text
codex + all installed skills
codex + all-in-one AGENTS.md
codex + AgentMakefile selected pipeline
claude-code + native skills
claude-code + AgentMakefile compiled skills + selected payload
```

Outputs:

- pass/fail
- verifier result
- model/tool token usage when available
- wall time
- number of tool calls
- number of denied tool calls
- retries
- generated diff size
- final answer schema validity
- guard and permission violations
- selected pipeline and stable prefix hash

This layer proves whether harness organization improves execution quality or
operational cost.

The first execution smoke run is recorded in
`benchmarks/swebench-lite-codex-mini-10-report.md`. It used Codex CLI to generate
patches for 10 SymPy-only SWE-bench Lite instances and scored them with the
official evaluator. The result, 7/10 resolved with 0 evaluator errors, validates
the bridge but remains a pilot signal. The next execution benchmark should be a
cross-repository A/B subset comparing a plain host prompt against an
AgentMakefile-selected harness prompt on the same tasks.

### Layer 3: External Harness Compatibility Benchmark

This layer lets AgentMakefile compare against external harness systems such as
OMO-style orchestration, custom team harnesses, or native host workflows.

AgentMakefile should not assume those harnesses use the same internal concepts.
Instead, external adapters should normalize results into a common output schema:

- harness name
- host
- model
- task id
- pass/fail
- cost and latency metrics when available
- instruction or prompt size when available
- execution trace summary
- verifier output

This layer is optional and should remain adapter-driven.

## Suite File Format

A benchmark suite file should describe tasks, baselines, adapters, and scoring
rules.

```yaml
version: 1
suite:
  id: agentmf-self-hosting
  title: AgentMakefile self-hosting harness benchmark
  description: Compare scattered guidance against AgentMakefile-selected pipelines.

tasks:
  - id: implement-code-change
    request: Add a small compiler behavior change using TDD.
    repo: .
    expected_targets:
      - code.change
    expected_skills:
      - superpowers:test-driven-development
      - superpowers:verification-before-completion
    verifier:
      command: PYTHONPATH=src python3 -m pytest tests/test_agentmf.py -q

baselines:
  - id: agents-md
    kind: agents-md
  - id: all-skills
    kind: all-skills
    skills_dirs:
      - ~/.codex/skills
  - id: agentmf-selected
    kind: agentmf-plugin-payload
    backend: agents-fragments

adapters:
  - id: deterministic-selection
    kind: agentmf-management
  - id: codex-native
    kind: host
    host: codex
    harness: agents-md
  - id: codex-agentmf
    kind: host
    host: codex
    harness: agentmf-plugin-payload

scoring:
  primary:
    - pass_rate
    - token_savings
    - stable_prefix_reuse
  secondary:
    - wall_time
    - tool_calls
    - denied_tool_calls
    - selection_trace_quality
```

## Runner Model

The suite runner should be split into deterministic and execution adapters.

Deterministic adapters:

- call `agentmf plugin payload`
- call `agentmf benchmark harness`
- compile selected baselines
- compare expected targets and skills
- do not invoke model providers
- do not execute tools

Execution adapters:

- run a task through a host agent or external harness
- collect trace and metric artifacts
- run task verifiers
- normalize results into the benchmark schema
- require explicit opt-in because execution can mutate repositories and spend
  model tokens

The initial runner should only implement deterministic adapters.

## Command Shape

The existing command remains the deterministic single-module benchmark:

```bash
agentmf benchmark harness \
  --file modules/superpowers/AgentMakefile \
  --case "implement this feature" \
  --baseline all-skills \
  --baseline-skills-dir ~/.codex/skills \
  --format markdown
```

The suite-level command is a later extension:

```bash
agentmf benchmark suite \
  --suite benchmarks/agentmf-self-hosting.yaml \
  --adapter deterministic-selection \
  --format markdown
```

The first ClawBench-compatible command exports an AgentMakefile harness bundle
without running the downstream host:

```bash
agentmf clawbench export \
  --file AgentMakefile \
  --task-id clawbench-demo-1 \
  --instruction "implement this feature" \
  --host codex \
  --model claude-opus-4-7 \
  --format json
```

For a task set, AgentMakefile can emit one harness bundle per line for an
external runner:

```bash
agentmf clawbench export-jsonl \
  --file AgentMakefile \
  --tasks-file benchmarks/clawbench-tasks.jsonl \
  --host codex \
  --model claude-opus-4-7 \
  > /tmp/agentmf-clawbench-harnesses.jsonl
```

The external host adapter can discover the JSONL contract directly:

```bash
agentmf clawbench adapter-contract \
  --host codex \
  --format json
```

After an external runner executes the exported harness bundles, AgentMakefile
can import the runner's result JSONL and summarize score-facing metrics:

```bash
agentmf clawbench import-results \
  --results-file /tmp/clawbench-results.jsonl \
  --format json
```

Execution mode must be explicit:

```bash
agentmf benchmark suite \
  --suite benchmarks/agentmf-self-hosting.yaml \
  --adapter codex-agentmf \
  --execute \
  --format json
```

## Result Schema

```json
{
  "version": 1,
  "suite": {
    "id": "agentmf-self-hosting",
    "title": "AgentMakefile self-hosting harness benchmark"
  },
  "run": {
    "adapter": "deterministic-selection",
    "host": "generic",
    "model": null,
    "execution": false
  },
  "summary": {
    "task_count": 1,
    "selected_target_matches": 1,
    "selected_skill_matches": 1,
    "average_token_savings": 26767,
    "stable_prefix_hashes": ["sha256:..."]
  },
  "tasks": [
    {
      "id": "implement-code-change",
      "request": "Add a small compiler behavior change using TDD.",
      "baseline": {
        "kind": "all-skills",
        "approx_tokens": 28505,
        "hash": "sha256:..."
      },
      "agentmf": {
        "selected_targets": ["code.change"],
        "selected_skills": [
          "superpowers:test-driven-development",
          "superpowers:verification-before-completion"
        ],
        "selected_pipeline_size": 23,
        "stable_prefix_approx_tokens": 1738,
        "stable_prefix_hash": "sha256:...",
        "token_savings": 26767
      },
      "execution": null,
      "verification": null
    }
  ]
}
```

## ClawBench Harness Export Schema

`agentmf clawbench export` emits the pre-execution harness layer that a
ClawBench runner or external host adapter can inject before model execution.
It does not run the model, execute tools, or claim task success.

```json
{
  "version": 1,
  "mode": "clawbench_harness_export",
  "benchmark": "clawbench",
  "task": {
    "id": "clawbench-demo-1",
    "instruction": "implement this feature"
  },
  "run": {
    "host": "codex",
    "model": "claude-opus-4-7",
    "execution": false,
    "harness": "agentmf-plugin-payload"
  },
  "harness": {
    "name": "AgentMakefile",
    "role": "harness_selection_layer",
    "injection": "prepend_stable_prefix_append_volatile_context",
    "preferred_cache_boundary": "after_stable_prefix",
    "permissions_mode": "host_enforced_when_supported"
  },
  "agentmf": {
    "selected_targets": ["methodology.code_change"],
    "selected_skills": [
      "superpowers:using-superpowers",
      "superpowers:verification-before-completion",
      "superpowers:test-driven-development"
    ],
    "selected_pipeline": {},
    "stable_prefix_hash": "sha256:..."
  },
  "trace_bundle": {
    "target_closure": ["methodology.bootstrap", "methodology.code_change"],
    "linked_fragments": [".agentmf/fragments/agents/methodology.code_change.md"],
    "stable_prefix_hash": "sha256:...",
    "stable_prefix_chars": 6952,
    "stable_prefix_approx_tokens": 1738,
    "pipeline_operations": [],
    "guard_ops": [],
    "permission_ops": [],
    "fallback_ops": [],
    "output_contracts": []
  },
  "downstream_execution": {
    "status": "not_executed",
    "reason": "export_only_harness_layer"
  }
}
```

This export is the compatibility bridge from AgentMakefile to a ClawBench-style
runner. The runner can treat AgentMakefile as the harness-selection layer while
keeping task execution, browser/tool interception, cost accounting, and pass
rate scoring outside AgentMakefile.

### JSONL Task Input

`agentmf clawbench export-jsonl` reads newline-delimited JSON task records. Each
line must be a JSON object with either `id` or `task_id`, and either
`instruction` or `prompt`.

```jsonl
{"id":"task-1","instruction":"implement this feature"}
{"task_id":"task-2","prompt":"review this change"}
```

The command writes one compact `clawbench_harness_export` object per output
line. It does not wrap the stream in a JSON envelope, so external runners can
process the file incrementally.

### Host Adapter Contract

`agentmf clawbench adapter-contract` defines the boundary between AgentMakefile
and an external ClawBench runner. AgentMakefile owns harness selection and
prompt/pipeline export. The host adapter owns model calls, tool execution,
browser/runtime instrumentation, and benchmark scoring evidence.

The input stream is JSONL where each record is a `clawbench_harness_export`.
Required fields include:

- `task.id`
- `task.instruction`
- `agentmf.selected_targets`
- `agentmf.selected_pipeline`
- `prompt.stable_prefix.content`
- `trace_bundle.stable_prefix_hash`

The output stream is JSONL where each record is a
`clawbench_external_runner_result`. Required fields are:

- `task_id`
- `pass`

Optional score-facing fields include `reward_lenient`, `reward_strict`,
`cost_usd`, `wall_time_ms`, `prompt_tokens`, `completion_tokens`,
`tool_calls`, `denied_tool_calls`, `trace_path`, and
`agentmf.stable_prefix_hash`.

Execution adapters should fill result records like:

```json
{
  "task_id": "clawbench-demo-1",
  "pass": true,
  "wall_time_ms": 120000,
  "prompt_tokens": 18000,
  "completion_tokens": 4000,
  "tool_calls": 14,
  "denied_tool_calls": 0,
  "cost_usd": 1.23,
  "agentmf": {
    "stable_prefix_hash": "sha256:..."
  },
  "verification": {
    "command": "PYTHONPATH=src python3 -m pytest tests/test_agentmf.py -q",
    "exit_code": 0,
    "summary": "161 passed"
  }
}
```

`agentmf clawbench import-results` also accepts a nested runner shape where
`task.id` identifies the task and execution metrics live under `execution`.
The imported summary reports result count, pass count, pass rate, average cost,
average wall time, average total tokens, aggregate tool calls, aggregate denied
tool calls, and unique stable prefix hashes.

## SWE-bench Lite Subset Export Schema

`agentmf swebench export-jsonl` emits pre-execution harness bundles for local
SWE-bench Lite-style JSONL subsets. This is the coding-benchmark bridge for
AgentMakefile's current Superpowers/OMO-style development harness, and is a
better first execution target than browser-commerce tasks.

Each input line must include the core SWE-bench fields:

```json
{
  "instance_id": "django__django-11099",
  "repo": "django/django",
  "base_commit": "abc123",
  "problem_statement": "Fix the failing regression."
}
```

Optional fields such as `patch`, `test_patch`, `hints_text`, `version`,
`FAIL_TO_PASS`, and `PASS_TO_PASS` are preserved in the exported task object.

The command emits one `swebench_harness_export` record per output line:

```json
{
  "version": 1,
  "mode": "swebench_harness_export",
  "benchmark": "swebench-lite",
  "task": {
    "instance_id": "django__django-11099",
    "repo": "django/django",
    "base_commit": "abc123",
    "problem_statement": "Fix the failing regression."
  },
  "run": {
    "host": "codex",
    "model": "gpt-5.4",
    "execution": false,
    "harness": "agentmf-plugin-payload"
  },
  "agentmf": {
    "selected_targets": ["code.change"],
    "selected_skills": ["superpowers:test-driven-development"],
    "selected_pipeline": {},
    "stable_prefix_hash": "sha256:..."
  },
  "downstream_execution": {
    "status": "not_executed",
    "reason": "export_only_harness_layer"
  }
}
```

`--limit N` supports small local smoke subsets before running a larger external
SWE-bench harness. AgentMakefile still owns only harness selection and prompt
assembly; checkout setup, patch application, test execution, and scoring remain
external runner responsibilities.

## Official SWE-bench Lite / Verified Bridge

Official SWE-bench execution remains delegated to the upstream evaluator. The
AgentMakefile layer prepares and explains the harness used to produce patches,
then provides three bridge commands around the official runner:

```bash
agentmf swebench predictions \
  --results-file /tmp/swebench-results-with-patches.jsonl \
  --model-name agentmf-gpt-5.4 \
  --dataset lite \
  > /tmp/swebench-predictions.jsonl

agentmf swebench official-dry-run \
  --dataset lite \
  --predictions-path /tmp/swebench-predictions.jsonl \
  --run-id agentmf-lite \
  --smoke-limit 5 \
  --format json

agentmf swebench official-command \
  --dataset lite \
  --predictions-path /tmp/swebench-predictions.jsonl \
  --run-id agentmf-lite \
  --max-workers 4

agentmf swebench import-official-report \
  --report-file agentmf-gpt-5.4.agentmf-lite.json \
  --format json
```

The predictions export emits the upstream JSONL shape:

```json
{
  "instance_id": "astropy__astropy-12907",
  "model_name_or_path": "agentmf-gpt-5.4",
  "model_patch": "diff --git ..."
}
```

The command generator supports two benchmark profiles:

| Profile | Official dataset | Split |
| --- | --- | --- |
| `lite` | `princeton-nlp/SWE-bench_Lite` | `test` |
| `verified` | `princeton-nlp/SWE-bench_Verified` | `test` |

The dry-run adapter plan validates the predictions file, records the submitted
prediction count and model names, emits a smoke command limited to the first
`--smoke-limit` instance ids, and emits a full command preview. Both commands
are marked `execution: false`; running either remains an explicit external
choice.

The official report importer consumes the schema-v2 report JSON written by the
upstream evaluator and normalizes submitted, completed, resolved, unresolved,
empty-patch, and error counts into resolved, completion, and error rates. This
keeps AgentMakefile's benchmark claim anchored to official SWE-bench scoring
while preserving the separation of responsibilities: AgentMakefile selects and
exports harnesses; the official evaluator applies patches and grades results.

## Scoring

Layer 1 scoring:

- target match rate
- skill match rate
- average token savings
- median token savings
- stable prefix hash reuse count
- average selected pipeline size
- guard coverage
- permission coverage
- selection trace completeness

Layer 2 scoring:

- pass rate
- verifier pass rate
- average wall time
- average prompt tokens
- average total tokens
- average tool calls
- denied tool call rate
- retry rate
- cost per passing task

The benchmark should report raw metrics first. Composite scores are optional and
should be derived from explicit weights in the suite file.

## Demo Cases

The first suite should use AgentMakefile's own repo because it exercises the
self-hosting claim.

Suggested deterministic cases:

- "implement this feature" -> `code.change`
- "review this change" -> `review.task`
- "break down the spec into tasks" -> `spec.breakdown`
- "debug failing tests" -> `methodology.debug`
- "write a skill" -> `methodology.skill_authoring`

Suggested execution cases for later:

- add a tiny backend fixture with TDD
- update docs and generated guidance
- fix a deliberately seeded validation diagnostic
- run a review-only task and report findings

The first execution suite should use small tasks with deterministic verifiers so
differences in harness organization are easier to attribute.

## Fairness Rules

- Use the same model for every adapter in one execution comparison.
- Use the same repository snapshot for every task run.
- Use the same tool permission profile unless permission behavior is the tested
  variable.
- Record all prompt or guidance sources used by each adapter.
- Record whether a task saw all skills, all Markdown, selected fragments, or
  selected native skills.
- Do not compare AgentMakefile-selected pipelines against an external harness
  unless the task, model, host, timeout, and verifier are identical.

## Safety

Execution benchmark runs can mutate repositories, spend tokens, call network
tools, and trigger host-specific approval flows. Therefore:

- deterministic benchmark mode is the default;
- execution mode requires `--execute`;
- repository work should happen in a temporary copy or worktree;
- destructive tool permissions should be denied by default;
- verifier commands must be explicit in the suite file;
- output artifacts should include enough trace data for post-run audit.

## Implementation Plan

### AMF-BENCH-001 Suite Spec and Docs

Add this spec, link it from README, and define the suite/result schema.

### AMF-BENCH-002 Suite File Parser

Add a strict YAML/JSON suite parser with diagnostics for unknown keys, missing
task ids, missing requests, invalid baselines, and invalid adapters.

### AMF-BENCH-003 Deterministic Suite Runner

Implement `agentmf benchmark suite --adapter deterministic-selection` by
reusing `create_harness_benchmark_payload`.

### AMF-BENCH-004 Report Writer

Emit suite-level JSON and Markdown reports with baseline metrics, selected
pipeline metrics, and selection match summaries.

### AMF-BENCH-005 Demo Suite

Add `benchmarks/agentmf-self-hosting.yaml` with deterministic self-hosting cases
for code change, review, spec breakdown, debugging, and skill authoring.

### AMF-BENCH-006 Execution Adapter Contract

Define the adapter interface for hosted agent execution without implementing a
provider-specific runner.

### AMF-BENCH-007 First Host Execution Adapter

Add one opt-in local adapter only after deterministic suite reports are stable.

### AMF-BENCH-008 ClawBench Harness Export

Add an export-only compatibility command that converts a ClawBench task
instruction into an AgentMakefile selected harness bundle with trace metadata.
This is the first bridge to ClawBench-style evaluation and deliberately does
not execute downstream host agents.

### AMF-BENCH-009 ClawBench JSONL Harness Export

Add batch export for task files so external ClawBench-style runners can consume
one AgentMakefile-selected harness bundle per task. The first input format is
newline-delimited JSON with `id`/`task_id` and `instruction`/`prompt`.

### AMF-BENCH-013 SWE-bench Task/Corpus Reader

Add a local JSONL reader for SWE-bench Lite-style subsets with required
`instance_id`, `repo`, `base_commit`, and `problem_statement` fields.

### AMF-BENCH-014 SWE-bench Lite Subset JSONL Harness Export

Add `agentmf swebench export-jsonl` so external SWE-bench-style runners can
consume one AgentMakefile-selected coding harness bundle per instance. Keep the
first slice export-only and support `--limit` for small smoke subsets.

### AMF-BENCH-019 Official SWE-bench Predictions JSONL Exporter

Add `agentmf swebench predictions` so external execution adapters can convert
patch-bearing result records into upstream-compatible predictions JSONL.

### AMF-BENCH-020 Official SWE-bench Run Command Generator

Add `agentmf swebench official-command` so Lite and Verified runs can be
launched through the official evaluator with a reproducible, execution-free
command preview.

### AMF-BENCH-021 Official SWE-bench Report Importer

Add `agentmf swebench import-official-report` so official schema-v2 report JSON
can be normalized back into AgentMakefile benchmark evidence.

### AMF-BENCH-022 Lite/Verified Benchmark Profiles

Add shared profile metadata for `princeton-nlp/SWE-bench_Lite` and
`princeton-nlp/SWE-bench_Verified`.

### AMF-BENCH-023 Official SWE-bench Dry-Run Adapter Plan

Add `agentmf swebench official-dry-run` so users can validate predictions and
inspect smoke/full official evaluator commands before deciding to run Lite or
Verified externally.

## Open Questions

- Should execution adapters call host CLIs directly, or should they emit payloads
  for an external runner to execute?
- Should suite reports include raw prompt text, or only hashes and paths by
  default?
- Should composite scores be part of AgentMakefile, or should AgentMakefile only
  emit raw metrics for external leaderboard tooling?
- Which external task suite is small, deterministic, and fair enough for the
  first public comparison?
