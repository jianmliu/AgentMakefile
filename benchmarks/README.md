# Benchmark Fixtures

This directory contains small, local smoke fixtures for AgentMakefile harness
exports. These files are intended to verify harness selection, prompt-prefix
stability, and adapter payload shape. They are not a substitute for running an
official external benchmark runner.

## SWE-bench Lite Smoke Subset

`swebench-lite-subset.jsonl` contains two SWE-bench Lite-style Astropy tasks
with the core fields consumed by `agentmf swebench export-jsonl`:

- `instance_id`
- `repo`
- `base_commit`
- `problem_statement`

Generate AgentMakefile-selected harness bundles with:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench export-jsonl \
  --file AgentMakefile \
  --tasks-file benchmarks/swebench-lite-subset.jsonl \
  --host codex \
  --model gpt-5.4 \
  --limit 2 \
  --out benchmarks/swebench-lite-agentmf-harnesses.jsonl \
  --write
```

The generated `swebench-lite-agentmf-harnesses.jsonl` file is an export artifact
for external runner experiments. It is useful for checking selected targets,
selected skills, stable prefix hashes, and trace metadata before wiring a real
SWE-bench execution adapter.

Generate a deterministic comparison report with:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench compare \
  --file AgentMakefile \
  --tasks-file benchmarks/swebench-lite-subset.jsonl \
  --host codex \
  --model gpt-5.4 \
  --limit 2 \
  --baseline agents-md \
  --baseline claude-md \
  --baseline skills-index \
  --baseline none \
  --out benchmarks/swebench-lite-comparison.md \
  --write \
  --format markdown
```

The comparison report is deterministic and execution-free. It compares selected
AgentMakefile stable-prefix size against compiled all-in-one or index-style
baselines and records stable prefix hash reuse across tasks.

## SWE-bench Mini Execution Results

External SWE-bench runners should emit JSONL records that follow:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench adapter-contract \
  --host codex \
  --format json
```

This repository includes `swebench-lite-results.example.jsonl` as a tiny
example result stream for report development. Import it with:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench import-results \
  --results-file benchmarks/swebench-lite-results.example.jsonl \
  --format json
```

Render a pass-rate report with:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench pass-report \
  --results-file benchmarks/swebench-lite-results.example.jsonl \
  --baseline-report benchmarks/swebench-lite-comparison.md \
  --out benchmarks/swebench-lite-pass-report.md \
  --write \
  --format markdown
```

The example result file is synthetic. It verifies report shape and metrics; it
does not claim real SWE-bench task performance.

## SWE-bench Lite Codex Mini-10 Pilot

`swebench-lite-codex-mini-10-report.md` records the first non-gold patch
generation smoke run through the official SWE-bench bridge. The run used Codex
CLI to generate patches for 10 SymPy-only SWE-bench Lite instances, exported
official predictions with AgentMakefile, ran the upstream evaluator, and
imported the official schema-v2 report.

Result: 7/10 resolved, 10/10 completed, 0 evaluator errors.

This is useful as proof that the AgentMakefile bridge can carry real generated
patches into official SWE-bench scoring. It is not a representative leaderboard
claim because the sample is small and single-repository.

## SWE-bench Lite Cross-Repo 20 A/B Run

`swebench-lite-cross-repo-20-ab-report.md` records a paired run over 20
SWE-bench Lite instances across 12 repositories. The run compared direct Codex
task prompting against AgentMakefile-selected `code.change` harness prompting,
then scored both prediction files with the upstream evaluator.

Result: both arms resolved 12/20 instances with 20/20 completed and 0 evaluator
errors. AgentMakefile used 68,134 fewer Codex CLI generation tokens on this run
while producing a different resolved set.

This is the first cross-repository A/B signal. It shows end-to-end benchmark
compatibility and cost parity/improvement, but not yet a pass-rate win.

## Official SWE-bench Bridge

Official SWE-bench evaluation still happens in the upstream runner. AgentMakefile
only prepares the predictions file, emits the reproducible command, and imports
the final report for comparison with harness-selection metrics.

For repeated local benchmark runs, keep Docker images and build cache in place.
Do not run `docker system prune`, `docker image prune`, or similar cleanup
commands between runs. Prefer upstream evaluator commands with:

```bash
--cache_level instance \
--clean false
```

The `instance` cache level is larger on disk, but it avoids repeatedly pulling
or rebuilding expensive SWE-bench instance images.

External execution results that contain either `model_patch`, `patch`, or
`patch_path` can be converted into official predictions JSONL:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench predictions \
  --results-file /tmp/swebench-results-with-patches.jsonl \
  --model-name agentmf-gpt-5.4 \
  --dataset lite \
  > /tmp/swebench-predictions.jsonl
```

Emit the official runner command for Lite or Verified without executing it:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench official-dry-run \
  --dataset lite \
  --predictions-path /tmp/swebench-predictions.jsonl \
  --run-id agentmf-lite \
  --smoke-limit 5 \
  --format json

PYTHONPATH=src python3 -m agentmf.cli swebench official-command \
  --dataset lite \
  --predictions-path /tmp/swebench-predictions.jsonl \
  --run-id agentmf-lite \
  --max-workers 4

PYTHONPATH=src python3 -m agentmf.cli swebench official-command \
  --dataset verified \
  --predictions-path /tmp/swebench-verified-predictions.jsonl \
  --run-id agentmf-verified \
  --max-workers 4
```

The dry-run command reads the predictions file, reports the selected Lite or
Verified profile, and emits two command previews: a smoke command restricted to
the first `--smoke-limit` prediction ids, and a full-profile command. It never
runs the upstream evaluator, Docker, or repository tests.

After the official runner writes its schema-v2 report JSON, import it with:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench import-official-report \
  --report-file agentmf-gpt-5.4.agentmf-lite.json \
  --format json
```
