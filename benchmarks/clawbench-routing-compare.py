"""Routing-only ClawBench comparison driver.

Reads benchmarks/clawbench-routing-tasks.jsonl and exports the harness for
each task against multiple AgentMakefile sources (root + per-category
modules under modules/openclaw-curated/). Aggregates selected_targets and
emits a markdown comparison report.

Does NOT run any external agent runner — this isolates the routing
contribution of each module so we can measure whether promoting OpenClaw
curated skills changes which targets the selector picks.

Usage:
  python3 benchmarks/clawbench-routing-compare.py [--out benchmarks/clawbench-routing-comparison.md]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = REPO_ROOT / "benchmarks" / "clawbench-routing-tasks.jsonl"
DEFAULT_REPORT = REPO_ROOT / "benchmarks" / "clawbench-routing-comparison.md"

# Run the in-tree agentmf package rather than the globally-installed one.
sys.path.insert(0, str(REPO_ROOT / "src"))
from agentmf.selector import create_link_plan  # noqa: E402


def discover_sources() -> List[tuple[str, Path]]:
    """Return ordered (label, agentmakefile_path) pairs to compare."""
    sources: List[tuple[str, Path]] = [("root", REPO_ROOT / "AgentMakefile")]
    curated_root = REPO_ROOT / "modules" / "openclaw-curated"
    if curated_root.exists():
        for category in sorted(p for p in curated_root.iterdir() if p.is_dir()):
            sources.append((f"curated/{category.name}", category / "AgentMakefile"))
    return [(label, path) for label, path in sources if path.exists()]


def export_routing(source_path: Path, tasks: List[Dict[str, str]]) -> Dict[str, Dict[str, Optional[list]]]:
    """Resolve each task's selected_targets/selected_skills via the in-tree
    selector. Unlike `clawbench export-jsonl`, missing-match cases here
    produce empty target lists rather than aborting the batch.
    """
    result: Dict[str, Dict[str, Optional[list]]] = {}
    for task in tasks:
        plan_result = create_link_plan(source_path, request=task["instruction"])
        plan = plan_result.plan or {}
        result[task["id"]] = {
            "targets": plan.get("selected_targets") or [],
            "skills": plan.get("selected_skills") or [],
        }
    return result


def load_tasks() -> List[Dict[str, str]]:
    tasks: List[Dict[str, str]] = []
    for line in TASKS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        tasks.append(json.loads(line))
    return tasks


def render_markdown(tasks: List[Dict[str, str]], rows: Dict[str, Dict[str, Dict]]) -> str:
    lines = [
        "# ClawBench Routing-Only Comparison",
        "",
        "Routing-only comparison: which target(s) the selector picks for each",
        "task under different AgentMakefile sources. No external agent runner",
        "is invoked, so the table measures routing precision only — not",
        "downstream pass rate.",
        "",
        f"- Tasks: `benchmarks/clawbench-routing-tasks.jsonl` ({len(tasks)} entries)",
        "- Driver: `benchmarks/clawbench-routing-compare.py`",
        "- Curated modules are per-machine (`.gitignore`'d under",
        "  `modules/openclaw-curated/`); regenerate with",
        "  `agentmf evo promote --target-dir modules/openclaw-curated --write`.",
        "",
    ]
    labels = list(rows.keys())
    # Per-task table
    lines.append("## Selected targets per task")
    lines.append("")
    header = "| Task | " + " | ".join(labels) + " |"
    sep = "| --- | " + " | ".join("---" for _ in labels) + " |"
    lines.append(header)
    lines.append(sep)
    for task in tasks:
        task_id = task["id"]
        cells = []
        for label in labels:
            entry = rows[label].get(task_id, {})
            targets = entry.get("targets") or []
            cell = ", ".join(f"`{t}`" for t in targets) if targets else "_no match_"
            cells.append(cell)
        lines.append(f"| `{task_id}` | " + " | ".join(cells) + " |")
    lines.append("")

    # Aggregate hit / miss counts
    lines.append("## Aggregate")
    lines.append("")
    lines.append("| Source | Tasks matched | Tasks unmatched |")
    lines.append("| --- | ---: | ---: |")
    for label in labels:
        hit = 0
        miss = 0
        for task in tasks:
            entry = rows[label].get(task["id"], {})
            if entry.get("targets"):
                hit += 1
            else:
                miss += 1
        lines.append(f"| `{label}` | {hit} | {miss} |")
    lines.append("")
    lines.append("Caveats:")
    lines.append("")
    lines.append("- Matched ≠ correct. A match may be a false positive (e.g. requests")
    lines.append("  containing common words like `documents` routing to the OpenClaw")
    lines.append("  `documents` skill regardless of intent).")
    lines.append("- The root AgentMakefile encodes methodology workflows; OpenClaw")
    lines.append("  curated modules encode application-domain skills. They cover")
    lines.append("  different task spaces — improvements aren't additive.")
    lines.append("- The curator-generated modules carry absolute `implementation.source`")
    lines.append("  paths pointing at the local Codex/Claude install, so this report's")
    lines.append("  results are reproducible only on the machine that produced them.")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_REPORT))
    args = ap.parse_args()

    tasks = load_tasks()
    sources = discover_sources()
    rows: Dict[str, Dict[str, Dict]] = {}
    for label, path in sources:
        print(f"-- routing through {label} ({path})")
        rows[label] = export_routing(path, tasks)

    report = render_markdown(tasks, rows)
    Path(args.out).write_text(report, encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
