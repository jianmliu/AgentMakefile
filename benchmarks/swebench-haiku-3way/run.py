"""3-way SWE-bench-Lite experiment driver: same 30 tasks × 3 prompt
conditions × claude-haiku-4-5 + SWE-bench official evaluator.

Conditions (per user direction):
  - none:               bare `problem_statement` (no AgentMakefile, no
                        superpowers, no AGENTS.md). The control.
  - baseline-agentmf:   the project's compiled `AGENTS.md` prepended
                        (flat guidance dump, no routing decision).
  - curated-agentmf:    `agentmf prompt --request <problem>` output
                        (selectively-routed prompt prefix including
                        the `## Routing Decision` section).

Phase 1 (this script): construct prompts, call claude-haiku-4-5, parse
patches, write predictions JSONL per condition.
Phase 2 (separate run):  feed each predictions JSONL into the official
SWE-bench evaluator and aggregate resolved-rate comparison.

`--dry-run` constructs prompts WITHOUT calling the API so wiring can be
verified before spending tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
TASKS_FILE = REPO_ROOT / "benchmarks" / "swebench-lite-haiku-30.jsonl"
MODEL_DEFAULT = "claude-haiku-4-5"
MAX_TOKENS = 8192


SYSTEM_PROMPT = (
    "You are solving a SWE-bench-style task. Read the problem statement and "
    "respond with a single unified diff patch that resolves the issue. Output "
    "ONLY the patch wrapped in ```diff fenced code blocks; no extra prose. "
    "Stick to minimal changes that fix the failing tests; do not add unrelated "
    "modifications."
)


def load_tasks() -> List[Dict[str, Any]]:
    tasks = []
    for line in TASKS_FILE.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        tasks.append(json.loads(line))
    return tasks


def build_prompt(condition: str, task: Dict[str, Any]) -> str:
    """Return the user-message text for `task` under `condition`."""
    body = (
        f"## Task\n\n"
        f"- Repository: `{task['repo']}`\n"
        f"- Instance ID: `{task['instance_id']}`\n"
        f"- Base commit: `{task['base_commit']}`\n\n"
        f"## Problem Statement\n\n{task['problem_statement']}\n\n"
        f"## Required Output\n\n"
        f"A single unified diff patch (one or more files) that applies cleanly to "
        f"the base commit and makes the listed failing tests pass without breaking "
        f"the passing ones. Wrap it in a ```diff code fence."
    )
    if condition == "none":
        return body
    if condition == "baseline-agentmf":
        agents_md = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
        return (
            f"## Project Guidance (flat AGENTS.md dump)\n\n"
            f"{agents_md.strip()}\n\n"
            f"---\n\n"
            f"{body}"
        )
    if condition == "curated-agentmf":
        prefix = _agentmf_prompt_prefix(task["problem_statement"])
        return (
            f"## Project Guidance (AgentMakefile-routed for this request)\n\n"
            f"{prefix.strip()}\n\n"
            f"---\n\n"
            f"{body}"
        )
    raise ValueError(f"unknown condition: {condition}")


def _agentmf_prompt_prefix(request: str) -> str:
    """Call `agentmf prompt --request <request>` against the root
    AgentMakefile and return the rendered prompt content (stable prefix
    + Routing Decision)."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    cmd = [
        sys.executable, "-m", "agentmf.cli",
        "prompt", "--request", request, "--format", "text",
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        # If selector finds no match, fall back to the bare stable prefix from
        # the agents-fragments backend. We don't fabricate guidance.
        return "(no AgentMakefile prefix produced — selector miss)"
    return proc.stdout


def call_haiku(prompt: str, model: str) -> Dict[str, Any]:
    """Single Anthropic Messages API call. Returns dict with text + token counts."""
    import anthropic  # local import — only required for real runs

    client = anthropic.Anthropic()
    start = time.time()
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed_ms = int((time.time() - start) * 1000)
    text_parts = []
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text_parts.append(block.text)
    return {
        "text": "".join(text_parts),
        "prompt_tokens": response.usage.input_tokens,
        "completion_tokens": response.usage.output_tokens,
        "wall_time_ms": elapsed_ms,
        "stop_reason": response.stop_reason,
    }


_DIFF_FENCE = re.compile(r"```diff\s*\n(.*?)```", re.DOTALL)


def extract_patch(text: str) -> Optional[str]:
    """Pull the first ```diff fenced block. Returns None when absent — the
    evaluator treats missing patches as empty-patch failures."""
    match = _DIFF_FENCE.search(text)
    if not match:
        return None
    return match.group(1).rstrip() + "\n"


def write_predictions(condition: str, model: str, results: List[Dict[str, Any]], out_dir: Path) -> Path:
    """Write a SWE-bench-official predictions JSONL for `condition`."""
    out_path = out_dir / f"predictions-{condition}.jsonl"
    with out_path.open("w") as f:
        for record in results:
            prediction = {
                "instance_id": record["instance_id"],
                "model_name_or_path": model,
                "model_patch": record["patch"] or "",
            }
            f.write(json.dumps(prediction) + "\n")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "benchmarks" / "swebench-haiku-3way" / "out"))
    ap.add_argument("--conditions", default="none,baseline-agentmf,curated-agentmf",
                    help="comma-separated condition list")
    ap.add_argument("--limit", type=int, default=None, help="cap tasks per condition for pilot")
    ap.add_argument("--model", default=MODEL_DEFAULT)
    ap.add_argument("--dry-run", action="store_true",
                    help="construct prompts and print sizes; do NOT call the API")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks = load_tasks()
    if args.limit is not None:
        tasks = tasks[: args.limit]
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]

    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        print("error: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2

    summary: Dict[str, Dict[str, Any]] = {}
    for condition in conditions:
        print(f"\n=== condition: {condition} ===")
        results: List[Dict[str, Any]] = []
        totals = {"tasks": 0, "prompt_chars": 0, "prompt_tokens": 0, "completion_tokens": 0, "wall_time_ms": 0}
        for task in tasks:
            prompt = build_prompt(condition, task)
            totals["tasks"] += 1
            totals["prompt_chars"] += len(prompt)
            entry: Dict[str, Any] = {
                "instance_id": task["instance_id"],
                "repo": task["repo"],
                "prompt_chars": len(prompt),
            }
            if args.dry_run:
                entry["patch"] = None
                entry["dry_run"] = True
                print(f"  [dry] {task['instance_id']}: prompt={len(prompt)} chars")
            else:
                api = call_haiku(prompt, args.model)
                patch = extract_patch(api["text"])
                entry.update(
                    {
                        "patch": patch,
                        "raw_text": api["text"],
                        "prompt_tokens": api["prompt_tokens"],
                        "completion_tokens": api["completion_tokens"],
                        "wall_time_ms": api["wall_time_ms"],
                        "stop_reason": api["stop_reason"],
                    }
                )
                totals["prompt_tokens"] += api["prompt_tokens"]
                totals["completion_tokens"] += api["completion_tokens"]
                totals["wall_time_ms"] += api["wall_time_ms"]
                marker = "  " if patch else "✗ "
                print(f"  {marker}{task['instance_id']}: in={api['prompt_tokens']} out={api['completion_tokens']} t={api['wall_time_ms']}ms")
            results.append(entry)

        per_condition_dir = out_dir / condition
        per_condition_dir.mkdir(parents=True, exist_ok=True)
        (per_condition_dir / "results.jsonl").write_text(
            "\n".join(json.dumps({k: v for k, v in r.items() if k != "raw_text"}) for r in results) + "\n"
        )
        for record in results:
            if record.get("raw_text"):
                (per_condition_dir / f"{record['instance_id']}.txt").write_text(record["raw_text"])
        predictions_path = write_predictions(condition, args.model, results, per_condition_dir)
        summary[condition] = {
            "totals": totals,
            "predictions_path": str(predictions_path),
            "results_path": str(per_condition_dir / "results.jsonl"),
        }
        print(f"  -> predictions: {predictions_path}")
        if totals["prompt_tokens"]:
            est_cost = totals["prompt_tokens"] / 1_000_000 * 0.80 + totals["completion_tokens"] / 1_000_000 * 4.00
            print(f"  -> est. cost (haiku-4-5 list prices): ${est_cost:.4f}")

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwrote {out_dir}/summary.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
