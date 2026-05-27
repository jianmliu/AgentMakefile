# SWE-bench Cross-Repo A/B Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a reproducible SWE-bench Lite mini benchmark that compares a plain Codex baseline against an AgentMakefile-selected harness on the same cross-repository task subset.

**Architecture:** Keep AgentMakefile responsible for task packaging, selected harness payloads, predictions export, official command dry-run, and report import. Keep patch generation external through the host CLI so the same dataset can later run through Codex, Claude Code, OMO, or another harness adapter.

**Tech Stack:** Python 3.11 SWE-bench environment under `/tmp/agentmf-swebench-smoke`, Docker Desktop, Codex CLI, `agentmf swebench` commands, official `swebench.harness.run_evaluation`.

---

## Experiment Design

Compare:

- `plain-codex`: prompt contains only the SWE-bench task metadata, problem statement, and minimal execution constraints.
- `agentmf-codex`: prompt contains the same task metadata plus an AgentMakefile-selected harness prefix and selected pipeline summary.

Hold constant:

- same model and provider;
- same Codex CLI version;
- same task list;
- same checkout base commits;
- same local dependency setup;
- same official SWE-bench evaluator;
- same Docker images;
- same max-workers and cleanup policy.

Primary metrics:

- official resolved rate;
- completed rate;
- error rate;
- total reported Codex tokens;
- patch apply and empty patch failures;
- per-instance resolved/unresolved deltas between arms.

Secondary metrics:

- prompt size;
- stable prefix hash;
- selected target;
- selected skills;
- selected pipeline operations;
- generation wall time;
- generated patch line count.

## Task 1: Create a Stratified SWE-bench Lite Subset

**Files:**
- Create: `benchmarks/swebench-lite-cross-repo-20.jsonl`
- Create: `/tmp/agentmf-swebench-ab/cross-repo-20-manifest.json`

- [ ] **Step 1: Select 20 tasks across repositories**

Use the official SWE-bench Lite `test` split and select 20 tasks with repository diversity:

```bash
/tmp/agentmf-swebench-smoke/.venv/bin/python - <<'PY'
import json
from collections import defaultdict
from pathlib import Path
from datasets import load_dataset

out = Path("benchmarks/swebench-lite-cross-repo-20.jsonl")
manifest = Path("/tmp/agentmf-swebench-ab/cross-repo-20-manifest.json")
manifest.parent.mkdir(parents=True, exist_ok=True)

dataset = load_dataset("princeton-nlp/SWE-bench_Lite", split="test")
by_repo = defaultdict(list)
for row in dataset:
    by_repo[row["repo"]].append(row)

selected = []
for repo in sorted(by_repo):
    if len(selected) >= 20:
        break
    selected.append(by_repo[repo][0])

if len(selected) < 20:
    seen = {row["instance_id"] for row in selected}
    for row in dataset:
        if row["instance_id"] not in seen:
            selected.append(row)
            seen.add(row["instance_id"])
        if len(selected) == 20:
            break

records = []
for row in selected:
    records.append({
        "instance_id": row["instance_id"],
        "repo": row["repo"],
        "base_commit": row["base_commit"],
        "problem_statement": row["problem_statement"],
    })

out.write_text("".join(json.dumps(record, sort_keys=True) + "\n" for record in records), encoding="utf-8")
manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
print(out)
for record in records:
    print(record["instance_id"], record["repo"])
PY
```

Expected: `benchmarks/swebench-lite-cross-repo-20.jsonl` contains 20 records and more than one repository.

- [ ] **Step 2: Verify AgentMakefile can package the subset**

Run:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench export-jsonl \
  --file AgentMakefile \
  --tasks-file benchmarks/swebench-lite-cross-repo-20.jsonl \
  --host codex \
  --model gpt-5.5 \
  --limit 20 \
  --out /tmp/agentmf-swebench-ab/agentmf-cross-repo-20-harnesses.jsonl \
  --write
```

Expected: command exits 0 and emits 20 `swebench_harness_export` records.

## Task 2: Prepare Plain and AgentMakefile Prompt Files

**Files:**
- Create: `/tmp/agentmf-swebench-ab/plain-prompts/*.md`
- Create: `/tmp/agentmf-swebench-ab/agentmf-prompts/*.md`

- [ ] **Step 1: Generate plain prompts**

Each plain prompt must contain:

- repository;
- base commit;
- instance id;
- problem statement;
- constraints not to read the gold patch;
- constraints not to edit tests or docs;
- focused verification command hint.

- [ ] **Step 2: Generate AgentMakefile prompts**

Each AgentMakefile prompt must include all plain prompt content plus:

- selected target;
- selected skills;
- stable prefix hash;
- selected pipeline operations;
- permission and output guidance extracted from the harness export record.

- [ ] **Step 3: Confirm prompt-size deltas**

Run a small script that prints per-instance byte and approximate token sizes for both prompt arms.

Expected: every task has exactly one plain prompt and one AgentMakefile prompt; AgentMakefile prompt size is recorded for later reporting.

## Task 3: Run Patch Generation

**Files:**
- Create: `/tmp/agentmf-swebench-ab/plain-results.jsonl`
- Create: `/tmp/agentmf-swebench-ab/agentmf-results.jsonl`
- Create: `/tmp/agentmf-swebench-ab/plain-patches/*.patch`
- Create: `/tmp/agentmf-swebench-ab/agentmf-patches/*.patch`

- [ ] **Step 1: Prepare repositories**

Clone each repository at its base commit under:

```text
/tmp/agentmf-swebench-ab/repos/<arm>/<instance_id>
```

Use local bare mirrors where possible to avoid repeated network clones.

- [ ] **Step 2: Run plain Codex arm**

For each task:

```bash
codex exec --ephemeral --ignore-rules -s workspace-write \
  -C /tmp/agentmf-swebench-ab/repos/plain/<instance_id> \
  --output-last-message /tmp/agentmf-swebench-ab/plain-logs/<instance_id>.final.txt \
  - < /tmp/agentmf-swebench-ab/plain-prompts/<instance_id>.md \
  > /tmp/agentmf-swebench-ab/plain-logs/<instance_id>.codex.log 2>&1
```

Capture `git diff --binary` to `/tmp/agentmf-swebench-ab/plain-patches/<instance_id>.patch`.

- [ ] **Step 3: Run AgentMakefile Codex arm**

Use the same command shape against `/tmp/agentmf-swebench-ab/repos/agentmf/<instance_id>` and `/tmp/agentmf-swebench-ab/agentmf-prompts/<instance_id>.md`.

- [ ] **Step 4: Build execution-result JSONL files**

Each JSONL line must include:

```json
{
  "instance_id": "repo__project-12345",
  "patch_path": "/tmp/agentmf-swebench-ab/plain-patches/repo__project-12345.patch",
  "execution": {
    "resolved": false,
    "patch_applied": false,
    "tests_passed": false,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "tool_calls": 0,
    "denied_tool_calls": 0,
    "trace_path": "/tmp/agentmf-swebench-ab/plain-logs/repo__project-12345.codex.log"
  }
}
```

Expected: both results files contain 20 lines.

## Task 4: Export Predictions and Run Official Evaluator

**Files:**
- Create: `/tmp/agentmf-swebench-ab/plain-predictions.jsonl`
- Create: `/tmp/agentmf-swebench-ab/agentmf-predictions.jsonl`
- Create: `/tmp/agentmf-swebench-ab/plain-official-report.json`
- Create: `/tmp/agentmf-swebench-ab/agentmf-official-report.json`

- [ ] **Step 1: Export official predictions**

Run:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench predictions \
  --results-file /tmp/agentmf-swebench-ab/plain-results.jsonl \
  --model-name plain-codex-gpt-5.5 \
  --dataset lite \
  --out /tmp/agentmf-swebench-ab/plain-predictions.jsonl \
  --write \
  --format jsonl

PYTHONPATH=src python3 -m agentmf.cli swebench predictions \
  --results-file /tmp/agentmf-swebench-ab/agentmf-results.jsonl \
  --model-name agentmf-codex-gpt-5.5 \
  --dataset lite \
  --out /tmp/agentmf-swebench-ab/agentmf-predictions.jsonl \
  --write \
  --format jsonl
```

- [ ] **Step 2: Dry-run both official plans**

Run:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench official-dry-run \
  --dataset lite \
  --predictions-path /tmp/agentmf-swebench-ab/plain-predictions.jsonl \
  --run-id plain-cross-repo-20 \
  --smoke-limit 20 \
  --format json

PYTHONPATH=src python3 -m agentmf.cli swebench official-dry-run \
  --dataset lite \
  --predictions-path /tmp/agentmf-swebench-ab/agentmf-predictions.jsonl \
  --run-id agentmf-cross-repo-20 \
  --smoke-limit 20 \
  --format json
```

Expected: both dry-runs report 20 submitted predictions and no diagnostics.

- [ ] **Step 3: Run official evaluator for each arm**

Run the official `swebench.harness.run_evaluation` command with the same `--instance_ids` list for both arms.

Use:

```bash
--max_workers 1
--cache_level instance
--clean false
```

Use `--cache_level instance --clean false` for repeated local benchmark work so
the expensive SWE-bench instance images remain available between runs. Avoid
`docker system prune`, `docker image prune`, and equivalent cleanup commands
until the benchmark series is complete.

Expected: both runs complete with 20 submitted instances and 0 evaluator errors.

## Task 5: Render A/B Report

**Files:**
- Create: `benchmarks/swebench-lite-cross-repo-20-ab-report.md`

- [ ] **Step 1: Import official reports**

Run:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench import-official-report \
  --report-file /tmp/agentmf-swebench-ab/plain-codex-gpt-5.5.plain-cross-repo-20.json \
  --format json

PYTHONPATH=src python3 -m agentmf.cli swebench import-official-report \
  --report-file /tmp/agentmf-swebench-ab/agentmf-codex-gpt-5.5.agentmf-cross-repo-20.json \
  --format json
```

- [ ] **Step 2: Write the report**

The report must include:

- sample selection;
- arm definitions;
- official resolved/completed/error rates;
- per-instance plain vs AgentMakefile deltas;
- token totals;
- prompt size totals;
- artifact paths;
- caveats and next recommended full-run threshold.

Expected: `benchmarks/swebench-lite-cross-repo-20-ab-report.md` gives enough detail to reproduce the run.

## Stop Conditions

Stop the run and report partial results if any of the following happens:

- the first 3 tasks in either arm have official evaluator errors;
- Codex CLI cannot produce patches for 3 consecutive tasks;
- Docker leaves running containers after an evaluator run;
- total reported Codex tokens exceed 3,000,000 before both arms finish.

## Notes

The previous single-repository pilot result is recorded in
`benchmarks/swebench-lite-codex-mini-10-report.md`. It should be treated as a
smoke test, not a leaderboard claim.
