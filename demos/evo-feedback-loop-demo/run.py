"""End-to-end evidence-driven evolution loop against a real curated corpus.

Pipeline:
  1. For each task in benchmarks/clawbench-routing-tasks.jsonl, run the
     selector against each modules/openclaw-curated/<category>/AgentMakefile
     and capture:
       - plugin_payload evidence (what the selector actually picked)
       - user_feedback evidence (what it SHOULD have picked, when the
         hand-curated GROUND_TRUTH names a correct skill)
  2. Run dream → emits update_match_terms + prune_match_terms proposals
     per (intended_module, intended_target).
  3. For each emitted proposal:
       - patch generate
       - evaluate (workspace + validate)
       - promote into modules/openclaw-curated/ (mutates the local copy)
  4. Re-run the routing selector and report the before/after delta.

Mutates `modules/openclaw-curated/` — that directory is .gitignored, so
re-runs need a fresh promote from the OpenClaw tier runner if the user
wants a clean baseline.
"""

from __future__ import annotations

import json
import sys
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agentmf.evolution import (
    create_candidate_patch_payload,
    create_compile_evaluate_payload,
    create_dream_mode_payload,
    create_evolution_evidence_payload,
    create_promotion_payload,
)
from agentmf.selector import create_link_plan

TASKS_FILE = REPO_ROOT / "benchmarks" / "clawbench-routing-tasks.jsonl"
CURATED_ROOT = REPO_ROOT / "modules" / "openclaw-curated"

# Hand-curated ground truth: which curated module hosts the *correct* skill
# for each OpenClaw-domain task. The methodology-* tasks route correctly via
# the root AgentMakefile and are intentionally absent here.
GROUND_TRUTH: Dict[str, Dict[str, str]] = {
    "bundled-1password": {
        "module": str(CURATED_ROOT / "uncategorized" / "AgentMakefile"),
        "target": "skill.uncategorized.1password",
    },
    "bundled-apple-notes": {
        "module": str(CURATED_ROOT / "uncategorized" / "AgentMakefile"),
        "target": "skill.uncategorized.apple-notes",
    },
    "plugins-presentations": {
        "module": str(CURATED_ROOT / "plugins" / "AgentMakefile"),
        "target": "skill.plugins.presentations",
    },
    "plugins-spreadsheet": {
        "module": str(CURATED_ROOT / "plugins" / "AgentMakefile"),
        "target": "skill.plugins.spreadsheets",
    },
    "vendor-aspnet": {
        "module": str(CURATED_ROOT / "vendor_imports" / "AgentMakefile"),
        "target": "skill.vendor_imports.aspnet-core",
    },
    "vendor-stripe": {
        "module": str(CURATED_ROOT / "plugins" / "AgentMakefile"),
        "target": "skill.plugins.stripe-projects",
    },
}


def load_tasks() -> List[Dict[str, str]]:
    return [json.loads(line) for line in TASKS_FILE.read_text().splitlines() if line.strip()]


def route_one(module: Path, request: str) -> Optional[str]:
    plan = create_link_plan(module, request=request, n_best=3).plan
    targets = plan.get("selected_targets") or []
    return targets[0] if targets else None


def routing_snapshot(tasks: List[Dict[str, str]]) -> Dict[str, Dict[str, Optional[str]]]:
    """{task_id: {module_label: selected_target_or_None}}."""
    snap: Dict[str, Dict[str, Optional[str]]] = {}
    for task in tasks:
        per_module: Dict[str, Optional[str]] = {}
        for module_dir in sorted(p for p in CURATED_ROOT.iterdir() if p.is_dir()):
            label = f"curated/{module_dir.name}"
            per_module[label] = route_one(module_dir / "AgentMakefile", task["instruction"])
        snap[task["id"]] = per_module
    return snap


def emit_evidence(tasks: List[Dict[str, str]], before: Dict[str, Dict[str, Optional[str]]], evidence_dir: Path) -> int:
    """Produce one plugin_payload record per (task, module) route observation,
    and one user_feedback record per task that has GROUND_TRUTH and was
    routed wrongly in the relevant module.
    """
    feedback_count = 0
    for task in tasks:
        task_id = task["id"]
        ground = GROUND_TRUTH.get(task_id)
        for module_label, selected in before[task_id].items():
            create_evolution_evidence_payload(
                source="plugin_payload",
                payload={
                    "request": task["instruction"],
                    "selected_target": selected,
                    "selected_targets": [selected] if selected else [],
                    "selected_skills": [],
                },
                out_dir=evidence_dir,
                write=True,
            )
        if ground is None:
            continue
        # Module that hosts the correct skill — the wrong-route signal we
        # care about is whichever module's actual route was wrong vs ground.
        intended_module = ground["module"]
        intended_target = ground["target"]
        # The module's selector pick for this task — that's the actual_target.
        intended_label = f"curated/{Path(intended_module).parent.name}"
        actual_target = before[task_id].get(intended_label)
        if actual_target == intended_target:
            continue  # already correct; no feedback needed
        create_evolution_evidence_payload(
            source="user_feedback",
            payload={
                "request": task["instruction"],
                "intended_module": intended_module,
                "intended_target": intended_target,
                "actual_target": actual_target,
            },
            out_dir=evidence_dir,
            write=True,
        )
        feedback_count += 1
    return feedback_count


def apply_proposals(proposals_dir: Path, eval_dir: Path) -> Tuple[int, int]:
    """For each *.proposal.json under proposals_dir, patch+evaluate+promote.
    Returns (applied, skipped)."""
    applied = 0
    skipped = 0
    for proposal_path in sorted(proposals_dir.glob("*.proposal.json")):
        proposal = json.loads(proposal_path.read_text())
        # Only promote proposals whose changes are all in SUPPORTED_PATCH_TYPES.
        change_types = {c.get("type") for c in proposal.get("changes", [])}
        if not change_types - {
            "update_match_terms",
            "merge_duplicate_targets",
            "prune_match_terms",
            "add_target",
            "add_dependency",
            "deprecate_skill",
            "add_registry_metadata",
            "add_benchmark_case",
            "update_permission_guard",
            "split_module",
        }:
            patch = create_candidate_patch_payload(
                proposal_file=proposal_path, out_dir=eval_dir / "patches", write=True
            )
            if not patch.ok or patch.payload.get("patch_status") != "generated":
                skipped += 1
                continue
            evaluate = create_compile_evaluate_payload(
                proposal_file=proposal_path, workspace_dir=eval_dir / "ws", write=True
            )
            if not evaluate.ok or evaluate.payload["promotion_report"]["status"] != "passed":
                skipped += 1
                continue
            promote = create_promotion_payload(
                proposal_file=proposal_path, target_dir=CURATED_ROOT, write=True
            )
            if promote.ok and promote.payload.get("status") == "promoted":
                applied += 1
            else:
                skipped += 1
        else:
            skipped += 1
    return applied, skipped


def render_delta(before: Dict[str, Dict[str, Optional[str]]], after: Dict[str, Dict[str, Optional[str]]]) -> str:
    lines = ["task_id, module, before, after, ground_truth, flipped_to_correct?"]
    flips = 0
    for task_id in sorted(before):
        ground = GROUND_TRUTH.get(task_id)
        for module_label in sorted(before[task_id]):
            b = before[task_id][module_label]
            a = after[task_id][module_label]
            if b == a:
                continue
            module_dir = Path(module_label.split("/", 1)[1])
            target_for_module = (
                ground["target"]
                if ground and Path(ground["module"]).parent.name == module_dir.name
                else None
            )
            flipped_correct = (target_for_module is not None and a == target_for_module)
            if flipped_correct:
                flips += 1
            lines.append(f"{task_id}, {module_label}, {b}, {a}, {target_for_module or '-'}, {flipped_correct}")
    lines.append("")
    lines.append(f"Total flips toward ground truth: {flips}")
    return "\n".join(lines)


def main() -> int:
    print(f"Repo root: {REPO_ROOT}")
    print(f"Curated corpus: {CURATED_ROOT}")
    print()

    tasks = load_tasks()
    print(f"Loaded {len(tasks)} tasks")

    print("\n=== Step 1: routing snapshot (before) ===")
    before = routing_snapshot(tasks)
    for task_id, per_module in before.items():
        ground = GROUND_TRUTH.get(task_id)
        gt = ground["target"] if ground else "—"
        print(f"  {task_id}: ground={gt}")
        for label, sel in per_module.items():
            mark = "✓" if ground and Path(ground["module"]).parent.name == label.split("/", 1)[1] and sel == ground["target"] else (
                "·" if sel else "—"
            )
            print(f"    {mark} {label}: {sel}")

    work_dir = Path(tempfile.mkdtemp(prefix="agentmf-feedback-loop."))
    evidence_dir = work_dir / "evidence"
    candidates_dir = work_dir / "candidates"
    print(f"\nWork dir: {work_dir}")

    print("\n=== Step 2: emit plugin_payload + user_feedback evidence ===")
    feedback_count = emit_evidence(tasks, before, evidence_dir)
    print(f"  Wrote {feedback_count} user_feedback records (one per failing task with ground truth)")

    print("\n=== Step 3: dream run ===")
    dream = create_dream_mode_payload(
        evidence_dir=evidence_dir, out_dir=candidates_dir, write=True
    )
    proposals = dream.payload.get("proposals", []) if dream.ok else []
    print(f"  dream emitted {len(proposals)} proposals (across all detectors)")
    for proposal in proposals:
        change_types = [c["type"] for c in proposal["proposal"]["changes"]]
        print(f"    - {proposal['proposal']['proposal_id']}: {change_types}")

    print("\n=== Step 4: patch + evaluate + promote each proposal ===")
    applied, skipped = apply_proposals(candidates_dir, work_dir)
    print(f"  applied={applied}  skipped={skipped}")

    print("\n=== Step 5: routing snapshot (after) ===")
    after = routing_snapshot(tasks)

    print("\n=== Delta ===")
    delta = render_delta(before, after)
    print(delta)

    # Persist for the routing-comparison.md updater
    (work_dir / "loop-result.txt").write_text(delta)
    print(f"\nFull delta saved at {work_dir / 'loop-result.txt'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
