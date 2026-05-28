"""Drive the official SWE-bench evaluator on each predictions JSONL
produced by run.py, and emit a 3-way resolved-rate comparison.

Prerequisites (verified by --check):
  - `pip install swebench` (Python package, brings the harness module)
  - Docker daemon running (the harness spawns per-task containers)
  - ~30-50GB free disk for cached repo images
  - benchmarks/swebench-lite-haiku-30.jsonl present
  - benchmarks/swebench-haiku-3way/out/<condition>/predictions-*.jsonl
    files present (from run.py)

For each condition the script invokes:

    python -m swebench.harness.run_evaluation \
      --dataset_name princeton-nlp/SWE-bench_Lite \
      --predictions_path predictions-<condition>.jsonl \
      --max_workers 4 \
      --run_id agentmf-haiku-30-<condition>

then reads the official report JSON the harness drops alongside the
predictions, and aggregates a Markdown comparison table.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = REPO_ROOT / "benchmarks" / "swebench-haiku-3way" / "out"
DATASET = "princeton-nlp/SWE-bench_Lite"


def preflight(out_dir: Path) -> List[str]:
    problems: List[str] = []
    try:
        import swebench  # noqa: F401
    except Exception:
        problems.append("missing `swebench` package — `pip install swebench`")
    if shutil.which("docker") is None:
        problems.append("missing `docker` binary on PATH")
    if not (REPO_ROOT / "benchmarks" / "swebench-lite-haiku-30.jsonl").exists():
        problems.append("missing benchmarks/swebench-lite-haiku-30.jsonl")
    for condition in ("none", "baseline-agentmf", "curated-agentmf"):
        if not (out_dir / condition / f"predictions-{condition}.jsonl").exists():
            problems.append(f"missing predictions for {condition}; run.py first")
    return problems


def run_evaluator(condition: str, out_dir: Path, max_workers: int) -> Path:
    predictions = out_dir / condition / f"predictions-{condition}.jsonl"
    run_id = f"agentmf-haiku-30-{condition}"
    cmd = [
        sys.executable, "-m", "swebench.harness.run_evaluation",
        "--dataset_name", DATASET,
        "--predictions_path", str(predictions),
        "--max_workers", str(max_workers),
        "--run_id", run_id,
        # Keep per-instance images on disk after the run so subsequent re-
        # runs reuse them; the previous codex-gpt-5.5 cross-repo-20 run
        # used `--cache_level env` and lost the instance images, so we
        # had to re-pull. Combined with `--clean false`, evaluator
        # workspaces and images survive for re-execution / inspection.
        "--cache_level", "instance",
        "--clean", "false",
    ]
    print(f"\n--- evaluator: {condition} ---")
    print("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        print(f"  evaluator exited rc={proc.returncode} (continuing to aggregate what's there)")
    # The harness writes "<model_name>.<run_id>.json" alongside predictions.
    candidates = sorted(predictions.parent.glob(f"*.{run_id}.json"))
    if not candidates:
        return predictions.parent / "MISSING_REPORT.json"
    return candidates[-1]


def aggregate(out_dir: Path, condition_reports: Dict[str, Path]) -> str:
    lines = [
        "# SWE-bench-Lite haiku-4-5 3-way comparison",
        "",
        f"- Tasks: 30 from `{DATASET}`",
        "- Model: claude-haiku-4-5",
        "- Evaluator: SWE-bench official `swebench.harness.run_evaluation`",
        "",
        "## Resolved-rate by condition",
        "",
        "| Condition | Submitted | Completed | Resolved | Resolved rate |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    summary: Dict[str, Any] = {}
    for condition in ("none", "baseline-agentmf", "curated-agentmf"):
        report_path = condition_reports.get(condition)
        if report_path is None or not report_path.exists():
            lines.append(f"| `{condition}` | — | — | — | _report missing_ |")
            continue
        data = json.loads(report_path.read_text())
        submitted = len(data.get("submitted_instances", []))
        completed = len(data.get("completed_instances", []))
        resolved = len(data.get("resolved_instances", []))
        rate = (resolved / submitted) if submitted else 0.0
        lines.append(
            f"| `{condition}` | {submitted} | {completed} | {resolved} | {rate * 100:.1f}% |"
        )
        summary[condition] = {
            "submitted": submitted,
            "completed": completed,
            "resolved": resolved,
            "resolved_rate": rate,
            "report_path": str(report_path),
        }
    (out_dir / "evaluator-summary.json").write_text(json.dumps(summary, indent=2))
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--max-workers", type=int, default=4)
    ap.add_argument("--check", action="store_true", help="preflight only")
    ap.add_argument(
        "--conditions",
        default="none,baseline-agentmf,curated-agentmf",
    )
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    problems = preflight(out_dir)
    if problems:
        print("preflight problems:")
        for problem in problems:
            print(f"  - {problem}")
        if args.check:
            return 1
        print("\nfix the above and re-run; or run with --check to suppress execution.")
        return 1
    if args.check:
        print("preflight ok — evaluator can run.")
        return 0

    reports: Dict[str, Path] = {}
    for condition in (c.strip() for c in args.conditions.split(",") if c.strip()):
        reports[condition] = run_evaluator(condition, out_dir, args.max_workers)

    md = aggregate(out_dir, reports)
    report_path = out_dir / "REPORT.md"
    report_path.write_text(md)
    print(f"\n=== wrote {report_path} ===")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
