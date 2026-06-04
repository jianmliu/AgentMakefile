"""A thin CLI for the markdown memory tool: observe + consolidate.

    python -m aigg_memory observe   --evidence E.jsonl --source observation --json '{...}' [--outcome correction]
    python -m aigg_memory consolidate --memory MEMORY.md --evidence E.jsonl [--write] [--format text|json]

No agentmf import.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from aigg_memory.markdown import consolidate, markdown_memory_domain
from aigg_memory.store import EvidenceStore

DEFAULT_MEMORY = "# Memory\n"


def _load_records(evidence_path: str) -> List:
    return EvidenceStore(evidence_path, domain=markdown_memory_domain()).load()


def consolidate_command(memory_path: str, evidence_path: str, write: bool = False) -> Dict[str, Any]:
    """Run consolidation; optionally write back when every gate passes.
    Returns a structured result (the testable core of the CLI)."""
    path = Path(memory_path)
    memory_text = path.read_text(encoding="utf-8") if path.exists() else DEFAULT_MEMORY
    result = consolidate(memory_text, _load_records(evidence_path))
    written = False
    if write and result.gates_ok and result.new_text != memory_text:
        path.write_text(result.new_text, encoding="utf-8")
        written = True
    return {
        "proposals": [p.to_dict() for p in result.proposals],
        "diff": result.patch.diff,
        "gates": [{"name": g.name, "passed": g.passed, "detail": g.detail} for g in result.gates],
        "gates_ok": result.gates_ok,
        "diagnostics": result.patch.diagnostics.to_list(),
        "new_text": result.new_text,
        "written": written,
    }


def observe_command(evidence_path: str, source: str, payload: Dict[str, Any], outcome: Optional[str] = None) -> Dict[str, Any]:
    store = EvidenceStore(evidence_path, domain=markdown_memory_domain())
    record = store.record(source, payload, outcome=outcome)
    return record.to_dict()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="aigg_memory", description="markdown agent-memory consolidation")
    sub = parser.add_subparsers(dest="command", required=True)

    observe = sub.add_parser("observe", help="append an observation to the evidence store")
    observe.add_argument("--evidence", required=True)
    observe.add_argument("--source", default="observation")
    observe.add_argument("--json", required=True, dest="payload_json", help="observation payload as JSON")
    observe.add_argument("--outcome", choices=["correction", "obsolete"], default=None)

    cons = sub.add_parser("consolidate", help="consolidate evidence into the memory index")
    cons.add_argument("--memory", required=True)
    cons.add_argument("--evidence", required=True)
    cons.add_argument("--write", action="store_true", help="write back when all gates pass")
    cons.add_argument("--format", choices=["text", "json"], default="text")

    args = parser.parse_args(argv)

    if args.command == "observe":
        record = observe_command(args.evidence, args.source, json.loads(args.payload_json), args.outcome)
        print(json.dumps(record, ensure_ascii=False, indent=2))
        return 0

    if args.command == "consolidate":
        out = consolidate_command(args.memory, args.evidence, write=args.write)
        if args.format == "json":
            print(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            print(f"proposals: {len(out['proposals'])}")
            for proposal in out["proposals"]:
                print(f"  - {proposal['title']}")
            print(out["diff"] or "(no change)")
            for gate in out["gates"]:
                print(f"  gate {gate['name']}: {'PASS' if gate['passed'] else 'FAIL'} {gate['detail']}")
            print("written" if out["written"] else ("dry-run (use --write)" if out["gates_ok"] else "blocked: gate failed"))
        return 0 if out["gates_ok"] else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
