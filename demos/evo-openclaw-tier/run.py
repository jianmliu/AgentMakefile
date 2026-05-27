"""Tier runner for the agentmf evo OpenClaw pipeline.

Reproduces the 10-stage evolution flow against a real OpenClaw-style SKILL.md
corpus (defaults: ~/.codex and ~/.claude, i.e. the local Codex/Claude skill
installs). Parameterised by `--tier` (smoke|200|full).

Stages:
  1. full scan       -> modules/openclaw + openclaw-import.json
  2. build subset    -> skills-subset/  (skipped when tier=full)
  3. scan subset     -> subset-modules + subset-openclaw-import.json
  4. overlap variant -> skills-subset-with-overlap + subset-overlap-* (200/smoke)
  5. dup variant     -> skills-subset-duplicate-evidence + dup-subset-* (200/smoke)
  6. evidence add    -> evidence-add.json + evidence/registry/openclaw_import.jsonl
  7. curate          -> curate.json + candidates/
  8. dream           -> dream.json + dream-candidates/
  9. evaluate        -> evaluate.json + eval-workspace/
 10. validate root   -> validate-root.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable


def agentmf(args: List[str], cwd: Path, capture: Optional[Path] = None) -> dict:
    cmd = [PY, "-m", "agentmf.cli"] + args
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + (
        os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
    )
    print(f"\n$ (cwd={cwd}) PYTHONPATH=src python -m agentmf.cli {' '.join(args)}")
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False, env=env)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        raise RuntimeError(f"agentmf failed (rc={proc.returncode}): {' '.join(args)}")
    if capture is not None:
        capture.write_text(proc.stdout)
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        return {}


def _read_frontmatter_name(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return path.parent.name
    for line in m.group(1).splitlines():
        stripped = line.strip()
        if stripped.startswith("name:"):
            return stripped.split(":", 1)[1].strip().strip('"').strip("'") or path.parent.name
    return path.parent.name


def discover_skills(skill_roots: List[Path]) -> List[Tuple[str, Path]]:
    records: List[Tuple[str, Path]] = []
    for root in skill_roots:
        for path in sorted(root.rglob("SKILL.md")):
            records.append((_read_frontmatter_name(path), path))
    return records


def select_unique_subset(records: List[Tuple[str, Path]], n: int) -> List[Tuple[str, Path]]:
    seen: Dict[str, Path] = {}
    for name, path in sorted(records, key=lambda r: (r[0].lower(), str(r[1]))):
        if name not in seen:
            seen[name] = path
    sorted_names = sorted(seen.keys(), key=lambda s: s.lower())
    return [(name, seen[name]) for name in sorted_names[:n]]


def _slug(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip().lower())
    safe = re.sub(r"-+", "-", safe).strip("-")
    return safe or "unnamed"


def materialize_subset(picks: List[Tuple[str, Path]], dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for index, (name, src) in enumerate(picks, start=1):
        sub = dest / f"{index:03d}-{_slug(name)}"
        sub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, sub / "SKILL.md")


def materialize_overlap(
    picks: List[Tuple[str, Path]],
    all_records: List[Tuple[str, Path]],
    dest: Path,
    k: int,
) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    by_name: Dict[str, List[Path]] = {}
    for name, path in all_records:
        by_name.setdefault(name, []).append(path)
    name_set = {n for n, _ in picks}
    overlap_candidates = [name for name in sorted(name_set) if len(by_name.get(name, [])) >= 2][:k]

    for index, (name, src) in enumerate(picks, start=1):
        sub = dest / f"{index:03d}-{_slug(name)}"
        sub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, sub / "SKILL.md")
    for offset, dup_name in enumerate(overlap_candidates):
        alt_src = by_name[dup_name][-1]
        target_idx = len(picks) - offset
        sub = dest / f"{target_idx:03d}-{_slug(dup_name)}-dup"
        sub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(alt_src, sub / "SKILL.md")


def materialize_dup(
    picks: List[Tuple[str, Path]],
    all_records: List[Tuple[str, Path]],
    dest: Path,
    k: int,
) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    by_name: Dict[str, List[Path]] = {}
    for name, path in all_records:
        by_name.setdefault(name, []).append(path)
    dup_names = [n for n in sorted({nm for nm, _ in picks}) if len(by_name.get(n, [])) >= 2][:k]

    for index, (name, src) in enumerate(picks, start=1):
        sub = dest / f"{index:03d}-{_slug(name)}"
        sub.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, sub / "SKILL.md")
    extra_index = len(picks) + 1
    for name in dup_names:
        for path in by_name[name][1:]:
            sub = dest / f"{extra_index:03d}-{_slug(name)}"
            sub.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, sub / "SKILL.md")
            extra_index += 1


def _find_first_proposal(candidates_dir: Path) -> Path:
    proposals = sorted(candidates_dir.glob("*.proposal.json"))
    if not proposals:
        raise FileNotFoundError(f"no *.proposal.json in {candidates_dir}")
    return proposals[0]


def pipeline(tier: str, skill_roots: List[Path], out_dir: Path, count: Optional[int]) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {
        "tier": tier,
        "out_dir": str(out_dir),
        "skill_roots": [str(p) for p in skill_roots],
        "stages": {},
    }

    full_out = out_dir / "modules" / "openclaw"
    full_args: List[str] = []
    for root in skill_roots:
        full_args += ["--skills-dir", str(root)]
    agentmf(
        ["openclaw", "scan", *full_args, "--out", str(full_out), "--write", "--format", "json"],
        cwd=out_dir,
        capture=out_dir / "openclaw-import.json",
    )
    import_payload = json.loads((out_dir / "openclaw-import.json").read_text())["openclaw_import"]
    summary["stages"]["full_scan"] = {
        "skill_count": import_payload["skill_count"],
        "category_count": import_payload["category_count"],
        "duplicate_groups": len(import_payload["curator_evidence"]["duplicate_original_names"]),
    }

    if tier != "full":
        assert count is not None
        records = discover_skills(skill_roots)
        picks = select_unique_subset(records, count)
        summary["stages"]["subset_pick"] = {
            "requested": count,
            "available": len({n for n, _ in records}),
            "selected": len(picks),
        }

        subset_dir = out_dir / "skills-subset"
        materialize_subset(picks, subset_dir)
        agentmf(
            [
                "openclaw", "scan",
                "--skills-dir", str(subset_dir),
                "--out", str(out_dir / "subset-modules" / "openclaw"),
                "--write", "--format", "json",
            ],
            cwd=out_dir,
            capture=out_dir / "subset-openclaw-import.json",
        )

        overlap_dir = out_dir / "skills-subset-with-overlap"
        materialize_overlap(picks, records, overlap_dir, k=max(5, count // 20))
        agentmf(
            [
                "openclaw", "scan",
                "--skills-dir", str(overlap_dir),
                "--out", str(out_dir / "subset-overlap-modules" / "openclaw"),
                "--write", "--format", "json",
            ],
            cwd=out_dir,
            capture=out_dir / "subset-overlap-openclaw-import.json",
        )

        dup_dir = out_dir / "skills-subset-duplicate-evidence"
        materialize_dup(picks, records, dup_dir, k=max(10, count // 5))
        agentmf(
            [
                "openclaw", "scan",
                "--skills-dir", str(dup_dir),
                "--out", str(out_dir / "dup-subset-modules" / "openclaw"),
                "--write", "--format", "json",
            ],
            cwd=out_dir,
            capture=out_dir / "dup-subset-openclaw-import.json",
        )
        evidence_payload_file = out_dir / "dup-subset-openclaw-import.json"
    else:
        evidence_payload_file = out_dir / "openclaw-import.json"

    agentmf(
        [
            "evo", "evidence", "add",
            "--source", "openclaw_import",
            "--payload-file", str(evidence_payload_file),
            "--out-dir", str(out_dir / "evidence"),
            "--write", "--format", "json",
        ],
        cwd=out_dir,
        capture=out_dir / "evidence-add.json",
    )
    evidence_jsonl = out_dir / "evidence" / "registry" / "openclaw_import.jsonl"

    agentmf(
        [
            "evo", "openclaw", "curate",
            "--evidence-file", str(evidence_jsonl),
            "--out-dir", str(out_dir / "candidates"),
            "--write", "--format", "json",
        ],
        cwd=out_dir,
        capture=out_dir / "curate.json",
    )

    agentmf(
        [
            "evo", "dream", "run",
            "--evidence-dir", str(out_dir / "evidence"),
            "--out-dir", str(out_dir / "dream-candidates"),
            "--write", "--format", "json",
        ],
        cwd=out_dir,
        capture=out_dir / "dream.json",
    )

    try:
        proposal = _find_first_proposal(out_dir / "candidates")
        agentmf(
            [
                "evo", "evaluate",
                "--proposal-file", str(proposal),
                "--workspace-dir", str(out_dir / "eval-workspace"),
                "--write", "--format", "json",
            ],
            cwd=out_dir,
            capture=out_dir / "evaluate.json",
        )
    except FileNotFoundError:
        summary["stages"]["evaluate"] = {"skipped": "no proposal produced by curate"}

    root_agentmakefile = out_dir / "modules" / "openclaw" / "AgentMakefile"
    if root_agentmakefile.exists():
        agentmf(
            ["validate", "--file", str(root_agentmakefile), "--format", "json"],
            cwd=out_dir,
            capture=out_dir / "validate-root.json",
        )

    curate_data = json.loads((out_dir / "curate.json").read_text())
    summary["stages"]["curate"] = {
        "proposal_count": curate_data.get("openclaw_curator", {}).get("proposal_count", 0),
    }
    evaluate_path = out_dir / "evaluate.json"
    if evaluate_path.exists():
        eval_data = json.loads(evaluate_path.read_text())
        summary["stages"]["evaluate"] = {
            "ok": eval_data.get("ok"),
            "result": list((eval_data.get("compile_evaluate") or {}).keys()),
        }
    (out_dir / "tier-summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> int:
    global REPO_ROOT
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", choices=["smoke", "200", "full"], required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument(
        "--skill-dir",
        action="append",
        default=[],
        help="defaults to ~/.codex and ~/.claude when omitted",
    )
    ap.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="repo root used to set PYTHONPATH for python -m agentmf.cli",
    )
    ap.add_argument(
        "--count",
        type=int,
        help="subset size (default smoke=100, 200=200; full ignores)",
    )
    args = ap.parse_args()

    REPO_ROOT = Path(args.repo_root)

    if not args.skill_dir:
        skill_roots = [
            Path("/opt/homebrew/lib/node_modules/openclaw/skills"),
            Path.home() / ".codex",
            Path.home() / ".claude",
        ]
    else:
        skill_roots = [Path(p).expanduser() for p in args.skill_dir]
    skill_roots = [p for p in skill_roots if p.exists()]
    if not skill_roots:
        print("no skill roots exist", file=sys.stderr)
        return 2

    counts = {"smoke": 100, "200": 200, "full": None}
    count = args.count if args.count is not None else counts[args.tier]

    summary = pipeline(args.tier, skill_roots, Path(args.out_dir), count)
    print("\n=== summary ===")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
