from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from agentmf.compiler import compile_agentmakefile
from agentmf.loader import load_source_with_diagnostics


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

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args)
    if args.command == "compile":
        return _compile(args)
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
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "files": [file.path for file in result.files],
                    "wrote": [str(path) for path in result.wrote],
                    "diagnostics": result.diagnostics.to_list(),
                },
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
            if not args.write:
                print("\nRun with --write to write files.")
    return 1 if not result.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
