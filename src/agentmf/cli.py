from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from agentmf.compiler import compile_agentmakefile
from agentmf.loader import load_source_with_diagnostics
from agentmf.selector import create_link_plan


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="agentmf")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate an AgentMakefile")
    validate.add_argument("--file", default="AgentMakefile")
    validate.add_argument("--format", choices=["text", "json"], default="text")

    compile_cmd = subparsers.add_parser("compile", help="compile an AgentMakefile")
    compile_cmd.add_argument("--file", default="AgentMakefile")
    compile_cmd.add_argument("--out", default=".")
    compile_cmd.add_argument("--target", action="append", dest="targets")
    compile_cmd.add_argument("--all", action="store_true", dest="all_backends")
    compile_cmd.add_argument("--write", action="store_true")
    compile_cmd.add_argument("--force", action="store_true")
    compile_cmd.add_argument("--dry-run", action="store_true")
    compile_cmd.add_argument("--format", choices=["text", "json"], default="text")
    compile_cmd.add_argument("--trace", action="store_true")

    select_cmd = subparsers.add_parser("select", help="select AgentMakefile prompt fragments for a request")
    select_cmd.add_argument("--file", default="AgentMakefile")
    select_cmd.add_argument("--request")
    select_cmd.add_argument("--target", action="append", dest="targets")
    select_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    select_cmd.add_argument("--format", choices=["text", "json"], default="json")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args)
    if args.command == "compile":
        return _compile(args)
    if args.command == "select":
        return _select(args)
    return 2


def _validate(args: argparse.Namespace) -> int:
    source, diagnostics = load_source_with_diagnostics(Path(args.file))
    if args.format == "json":
        print(json.dumps({"ok": source is not None and not diagnostics.has_errors, "diagnostics": diagnostics.to_list()}, indent=2))
    else:
        if source is not None and not diagnostics.has_errors:
            print("AgentMakefile is valid.")
        else:
            print(diagnostics.format(), file=sys.stderr)
    return 1 if diagnostics.has_errors or source is None else 0


def _compile(args: argparse.Namespace) -> int:
    result = compile_agentmakefile(
        path=Path(args.file),
        out_dir=Path(args.out),
        targets=args.targets,
        all_backends=args.all_backends,
        write=args.write,
        force=args.force,
        trace=args.trace,
    )
    if args.format == "json":
        payload = {
            "ok": result.ok,
            "files": [file.path for file in result.files],
            "wrote": [str(path) for path in result.wrote],
            "unchanged": [str(path) for path in result.unchanged],
            "diagnostics": result.diagnostics.to_list(),
        }
        if args.trace:
            payload["trace"] = [event.to_dict() for event in result.trace]
        print(
            json.dumps(
                payload,
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            stream = sys.stderr if result.diagnostics.has_errors else sys.stdout
            print(result.diagnostics.format(), file=stream)
        if result.files:
            header = "Generated:" if args.write else "Would generate:"
            print(header)
            for file in result.files:
                print(f"  {file.path}")
            if args.write and result.unchanged:
                print("\nUnchanged:")
                for path in result.unchanged:
                    print(f"  {path}")
            if not args.write:
                print("\nRun with --write to write files.")
        if args.trace:
            print("\nTrace:")
            for event in result.trace:
                print(f"  {event.format()}")
    return 1 if not result.ok else 0


def _select(args: argparse.Namespace) -> int:
    result = create_link_plan(
        path=Path(args.file),
        request=args.request,
        target_names=args.targets,
        backend=args.backend,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "link_plan": result.plan,
                    "diagnostics": result.diagnostics.to_list(),
                },
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            stream = sys.stderr if result.diagnostics.has_errors else sys.stdout
            print(result.diagnostics.format(), file=stream)
        if result.plan:
            print("Selected fragments:")
            for fragment in result.plan["fragments"]:
                print(f"  {fragment['path']}")
    return 1 if not result.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
