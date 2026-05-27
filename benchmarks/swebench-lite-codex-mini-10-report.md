# SWE-bench Lite Codex Mini-10 Report

Date: 2026-05-26

## Summary

This report records the first non-gold SWE-bench Lite mini execution run wired
through the AgentMakefile official SWE-bench bridge.

The run used Codex CLI to generate patches for 10 SWE-bench Lite SymPy tasks,
converted the generated patches into official predictions JSONL with
`agentmf swebench predictions`, executed the official upstream
`swebench.harness.run_evaluation` runner, and imported the official report with
`agentmf swebench import-official-report`.

This is a pilot execution result. It is not a full SWE-bench Lite leaderboard
submission and should not be presented as representative cross-repository
performance.

## Result

| Metric | Value |
| --- | ---: |
| Benchmark profile | SWE-bench Lite |
| Repository subset | `sympy/sympy` only |
| Instances submitted | 10 |
| Instances completed | 10 |
| Instances resolved | 7 |
| Instances unresolved | 3 |
| Instances with errors | 0 |
| Resolved rate | 70% |
| Codex token total reported by CLI | 560,683 |

## Resolved Instances

- `sympy__sympy-20590`
- `sympy__sympy-21055`
- `sympy__sympy-21379`
- `sympy__sympy-21612`
- `sympy__sympy-21614`
- `sympy__sympy-21847`
- `sympy__sympy-22005`

## Unresolved Instances

- `sympy__sympy-20639`
- `sympy__sympy-21171`
- `sympy__sympy-21627`

## Local Artifacts

The run artifacts were kept outside the repository under
`/tmp/agentmf-swebench-mini-run`:

- Execution results JSONL:
  `/tmp/agentmf-swebench-mini-run/codex-mini-results-10.jsonl`
- Official predictions JSONL:
  `/tmp/agentmf-swebench-mini-run/codex-mini-predictions-10.jsonl`
- Official SWE-bench report:
  `/tmp/agentmf-swebench-mini-run/codex-gpt-5.5-mini.codex-mini-10.json`
- Generated patches:
  `/tmp/agentmf-swebench-mini-run/patches/`
- Codex execution logs:
  `/tmp/agentmf-swebench-mini-run/logs/`

## Commands

Generate official predictions from external execution results:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench predictions \
  --results-file /tmp/agentmf-swebench-mini-run/codex-mini-results-10.jsonl \
  --model-name codex-gpt-5.5-mini \
  --dataset lite \
  --out /tmp/agentmf-swebench-mini-run/codex-mini-predictions-10.jsonl \
  --write \
  --format jsonl
```

Validate the official adapter plan before execution:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench official-dry-run \
  --dataset lite \
  --predictions-path /tmp/agentmf-swebench-mini-run/codex-mini-predictions-10.jsonl \
  --run-id codex-mini-10 \
  --smoke-limit 10 \
  --format json
```

Run the official upstream evaluator:

```bash
/tmp/agentmf-swebench-smoke/.venv/bin/python -m swebench.harness.run_evaluation \
  --dataset_name princeton-nlp/SWE-bench_Lite \
  --split test \
  --instance_ids \
    sympy__sympy-20590 \
    sympy__sympy-20639 \
    sympy__sympy-21055 \
    sympy__sympy-21171 \
    sympy__sympy-21379 \
    sympy__sympy-21612 \
    sympy__sympy-21614 \
    sympy__sympy-21627 \
    sympy__sympy-21847 \
    sympy__sympy-22005 \
  --predictions_path /tmp/agentmf-swebench-mini-run/codex-mini-predictions-10.jsonl \
  --max_workers 1 \
  --run_id codex-mini-10 \
  --cache_level env \
  --clean false \
  --report_dir /tmp/agentmf-swebench-mini-run/reports
```

Import the official report:

```bash
PYTHONPATH=src python3 -m agentmf.cli swebench import-official-report \
  --report-file /tmp/agentmf-swebench-mini-run/codex-gpt-5.5-mini.codex-mini-10.json \
  --format json
```

## Interpretation

The run proves that AgentMakefile can bridge real generated patches into the
official SWE-bench scoring flow:

1. A host agent generates patches.
2. AgentMakefile exports upstream-compatible predictions.
3. The official evaluator scores the predictions.
4. AgentMakefile imports the schema-v2 report as benchmark evidence.

The 70% resolved rate is encouraging as a smoke result, but the sample is small
and single-repository. The next benchmark must use a cross-repository,
stratified subset and an A/B comparison between a plain host prompt and an
AgentMakefile-selected harness prompt.
