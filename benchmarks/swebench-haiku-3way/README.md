# SWE-bench-Lite haiku-4-5 3-way experiment

Tests whether AgentMakefile guidance — both **baseline** (flat
`AGENTS.md` dump) and **curated** (selectively-routed via
`agentmf prompt`) — moves SWE-bench-Lite resolved rate vs a **bare**
control.

## Conditions

| | Prompt content |
| --- | --- |
| `none` | bare `problem_statement` + minimal task framing. No project guidance whatsoever. |
| `baseline-agentmf` | repo's `AGENTS.md` (the compiled superpowers + methodology + permission guidance) prepended ahead of the task. |
| `curated-agentmf` | output of `agentmf prompt --request <problem_statement>`, including the `## Routing Decision` section + selectively bound skill content. |

Same 30 tasks, same model (`claude-haiku-4-5`), same evaluator (official
SWE-bench harness) — the only variable is the prompt prefix.

## Task set

30 instances sampled from
`princeton-nlp/SWE-bench_Lite` with up-to-5-per-repo balance:

  - astropy/astropy: 5
  - django/django: 5
  - matplotlib/matplotlib: 5
  - mwaskom/seaborn: 4
  - pallets/flask: 3
  - psf/requests: 5
  - pydata/xarray: 3

Stored at `benchmarks/swebench-lite-haiku-30.jsonl`.

## Cost / time

Phase 1 (prediction with haiku-4-5 list prices):

| Condition | Prompt chars / task | Tokens in / task (rough) | Tokens out (rough) | Total per-task | 30-task est. |
| --- | ---: | ---: | ---: | ---: | ---: |
| `none` | ~2K | ~500 | ~5000 | ~$0.02 | ~$0.70 |
| `baseline-agentmf` | ~29K | ~7000 | ~5000 | ~$0.03 | ~$0.80 |
| `curated-agentmf` | ~2-12K | ~500-3000 | ~5000 | ~$0.02 | ~$0.70 |

Phase 2 (official SWE-bench evaluator on Docker):

  - 30 tasks × 3 conditions × ~2-5 min/task = 3-7 hours wall clock
  - ~5-10 GB of cached repo Docker images on first run

## Running

### Phase 1 — generate predictions

```bash
export ANTHROPIC_API_KEY=...

# Always dry-run first to verify wiring without spending tokens.
python3 benchmarks/swebench-haiku-3way/run.py --dry-run

# Single-task pilot (3 conditions × 1 task ≈ $0.10).
python3 benchmarks/swebench-haiku-3way/run.py --limit 1

# Full 30 × 3.
python3 benchmarks/swebench-haiku-3way/run.py
```

Outputs land under `benchmarks/swebench-haiku-3way/out/<condition>/`:

  - `predictions-<condition>.jsonl` (official SWE-bench predictions
    format; pipe into the evaluator)
  - `results.jsonl` (per-task metadata: token counts, wall time, stop
    reason)
  - `<instance_id>.txt` (raw model output for debugging)

### Phase 2 — official SWE-bench evaluator

```bash
pip install swebench  # one-time
# Docker daemon must be running

python3 benchmarks/swebench-haiku-3way/evaluate.py --check
python3 benchmarks/swebench-haiku-3way/evaluate.py
```

`evaluate.py` invokes `python -m swebench.harness.run_evaluation`
sequentially per condition, then writes a 3-way Markdown comparison to
`out/REPORT.md`.

## Guard-rails

- `ANTHROPIC_API_KEY` must be set before any real run; otherwise the
  script exits non-zero before touching tokens.
- `--dry-run` constructs prompts and writes empty `predictions-*.jsonl`
  files but never calls the API. Use it to verify prompt sizing.
- `--limit N` runs the first N tasks per condition; use for pilots.
- Per-task metadata (token counts, wall time, stop reason) goes into
  `results.jsonl` so cost is auditable after the run.
- Output directory is `.gitignore`'d so model outputs / predictions are
  not committed unless you explicitly stage them.
