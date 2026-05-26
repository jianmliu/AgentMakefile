from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from agentmf.ask import create_ask_payload
from agentmf.compiler import compile_agentmakefile
from agentmf.loader import load_source_with_diagnostics
from agentmf.plugin import create_plugin_payload
from agentmf.prompt import create_prompt_payload
from agentmf.runtime import create_run_plan
from agentmf.selector import create_link_plan
from agentmf.tool_loop import create_exec_payload


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

    run_cmd = subparsers.add_parser("run", help="dry-run an AgentMakefile runtime plan")
    run_cmd.add_argument("--file", default="AgentMakefile")
    run_cmd.add_argument("--request")
    run_cmd.add_argument("--target", action="append", dest="targets")
    run_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    run_cmd.add_argument("--dry-run", action="store_true")
    run_cmd.add_argument("--permission-check", action="append", dest="permission_checks")
    run_cmd.add_argument("--output-json")
    run_cmd.add_argument("--format", choices=["text", "json"], default="text")

    prompt_cmd = subparsers.add_parser("prompt", help="emit a deterministic prompt payload")
    prompt_cmd.add_argument("request_positional", nargs="?")
    prompt_cmd.add_argument("--file", default="AgentMakefile")
    prompt_cmd.add_argument("--request")
    prompt_cmd.add_argument("--target", action="append", dest="targets")
    prompt_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    prompt_cmd.add_argument("--plan")
    prompt_cmd.add_argument("--include-git-status", action="store_true")
    prompt_cmd.add_argument("--include-git-diff", action="store_true")
    prompt_cmd.add_argument("--context-file", action="append", dest="context_files")
    prompt_cmd.add_argument("--format", choices=["text", "json"], default="text")

    ask_cmd = subparsers.add_parser("ask", help="run a one-shot provider call")
    ask_cmd.add_argument("request_positional", nargs="?")
    ask_cmd.add_argument("--file", default="AgentMakefile")
    ask_cmd.add_argument("--request")
    ask_cmd.add_argument("--target", action="append", dest="targets")
    ask_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    ask_cmd.add_argument("--plan")
    ask_cmd.add_argument("--include-git-status", action="store_true")
    ask_cmd.add_argument("--include-git-diff", action="store_true")
    ask_cmd.add_argument("--context-file", action="append", dest="context_files")
    ask_cmd.add_argument("--provider", default="echo")
    ask_cmd.add_argument("--model")
    ask_cmd.add_argument("--temperature", type=float)
    ask_cmd.add_argument("--max-output-tokens", type=int)
    ask_cmd.add_argument("--format", choices=["text", "json"], default="text")

    exec_cmd = subparsers.add_parser("exec", help="run a gated tool-loop prototype")
    exec_cmd.add_argument("request_positional", nargs="?")
    exec_cmd.add_argument("--file", default="AgentMakefile")
    exec_cmd.add_argument("--request")
    exec_cmd.add_argument("--target", action="append", dest="targets")
    exec_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    exec_cmd.add_argument("--tool-call", action="append", dest="tool_calls")
    exec_cmd.add_argument("--provider", default="host")
    exec_cmd.add_argument("--sandbox-profile", choices=["none", "read-only", "workspace-write"], default="workspace-write")
    exec_cmd.add_argument("--execute-fallbacks", action="store_true")
    exec_cmd.add_argument("--apply", action="store_true")
    exec_cmd.add_argument("--format", choices=["text", "json"], default="text")

    plugin_cmd = subparsers.add_parser("plugin", help="plugin adapter commands")
    plugin_subcommands = plugin_cmd.add_subparsers(dest="plugin_command", required=True)
    plugin_payload_cmd = plugin_subcommands.add_parser("payload", help="emit a plugin prompt payload")
    plugin_payload_cmd.add_argument("request_positional", nargs="?")
    plugin_payload_cmd.add_argument("--file", default="AgentMakefile")
    plugin_payload_cmd.add_argument("--host", choices=["generic", "codex", "claude-code", "cursor", "opencode"], default="generic")
    plugin_payload_cmd.add_argument("--request")
    plugin_payload_cmd.add_argument("--target", action="append", dest="targets")
    plugin_payload_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    plugin_payload_cmd.add_argument("--plan")
    plugin_payload_cmd.add_argument("--include-git-status", action="store_true")
    plugin_payload_cmd.add_argument("--include-git-diff", action="store_true")
    plugin_payload_cmd.add_argument("--context-file", action="append", dest="context_files")
    plugin_payload_cmd.add_argument("--format", choices=["text", "json"], default="json")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args)
    if args.command == "compile":
        return _compile(args)
    if args.command == "select":
        return _select(args)
    if args.command == "run":
        return _run(args)
    if args.command == "prompt":
        return _prompt(args)
    if args.command == "ask":
        return _ask(args)
    if args.command == "exec":
        return _exec(args)
    if args.command == "plugin":
        return _plugin(args)
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


def _run(args: argparse.Namespace) -> int:
    proposed_tool_calls = _parse_permission_checks(args.permission_checks)
    proposed_output = _parse_output_json(args.output_json)
    if proposed_output is _INVALID_OUTPUT_JSON:
        return 2
    result = create_run_plan(
        path=Path(args.file),
        request=args.request,
        target_names=args.targets,
        backend=args.backend,
        dry_run=args.dry_run,
        proposed_tool_calls=proposed_tool_calls,
        proposed_output=proposed_output,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "runtime_plan": result.plan,
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
            print("Runtime dry run:")
            print(f"  mode: {result.plan['mode']}")
            for target in result.plan["link_plan"]["selected_targets"]:
                print(f"  selected target: {target}")
            for fragment in result.plan["prompt_prefix"]["fragments"]:
                print(f"  fragment: {fragment['path']}")
            comparison = result.plan["prompt_prefix"]["comparison"]
            print(
                "  linked prompt: "
                f"{comparison['linked']['chars']} chars, ~{comparison['linked']['approx_tokens']} tokens"
            )
            print(
                "  all-in-one baseline: "
                f"{comparison['all_in_one']['chars']} chars, ~{comparison['all_in_one']['approx_tokens']} tokens"
            )
            print(
                "  estimated savings: "
                f"{comparison['savings']['chars']} chars, ~{comparison['savings']['approx_tokens']} tokens"
            )
            guard_evaluation = result.plan["guard_evaluation"]
            guards = guard_evaluation["guards"]
            print(
                "  guard evaluation: "
                f"{len(guards)} planned, executed={guard_evaluation['executed']}"
            )
            for guard in guards:
                if guard["source"] == "policy":
                    print(
                        "  guard: "
                        f"policy {guard['policy']} -> {guard['target']}: {guard['guard']}"
                    )
                else:
                    print(f"  guard: target {guard['target']}: {guard['guard']}")
            permission_evaluation = result.plan["permission_evaluation"]
            tool_calls = permission_evaluation["tool_calls"]
            print(
                "  permission evaluation: "
                f"{len(tool_calls)} planned, executed={permission_evaluation['executed']}"
            )
            for tool_call in tool_calls:
                print(
                    "  permission: "
                    f"{tool_call['tool']} {tool_call['input']} -> {tool_call['action']}"
                )
            output_validation = result.plan["output_validation"]
            print(
                "  output validation: "
                f"{output_validation['status']}, provided={output_validation['provided']}"
            )
            print("  execution: not performed")
    return 1 if not result.ok else 0


_INVALID_OUTPUT_JSON = object()


def _parse_output_json(output_json: Optional[str]) -> Optional[dict]:
    if output_json is None:
        return None
    try:
        payload = json.loads(output_json)
    except json.JSONDecodeError as exc:
        print(f"error: invalid --output-json: {exc}", file=sys.stderr)
        return _INVALID_OUTPUT_JSON
    if not isinstance(payload, dict):
        print("error: --output-json must decode to a JSON object", file=sys.stderr)
        return _INVALID_OUTPUT_JSON
    return payload


def _parse_permission_checks(permission_checks: Optional[List[str]]) -> List[dict]:
    return _parse_tool_call_specs(permission_checks)


def _parse_tool_call_specs(tool_call_specs: Optional[List[str]]) -> List[dict]:
    tool_calls = []
    for raw_spec in tool_call_specs or []:
        if ":" not in raw_spec:
            tool_calls.append({"tool": raw_spec, "input": ""})
            continue
        tool, input_text = raw_spec.split(":", 1)
        tool_calls.append({"tool": tool, "input": input_text})
    return tool_calls


def _prompt(args: argparse.Namespace) -> int:
    if args.request and args.request_positional:
        print("error: provide request either positionally or with --request, not both", file=sys.stderr)
        return 2
    request = args.request if args.request is not None else args.request_positional
    result = create_prompt_payload(
        path=Path(args.file),
        request=request,
        target_names=args.targets,
        backend=args.backend,
        plan_path=Path(args.plan) if args.plan else None,
        context_files=[Path(path) for path in args.context_files or []],
        include_git_status=args.include_git_status,
        include_git_diff=args.include_git_diff,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "prompt_payload": result.payload,
                    "diagnostics": result.diagnostics.to_list(),
                },
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            stream = sys.stderr if result.diagnostics.has_errors else sys.stdout
            print(result.diagnostics.format(), file=stream)
        if result.payload:
            print(result.payload["final_prompt"]["content"], end="")
    return 1 if not result.ok else 0


def _ask(args: argparse.Namespace) -> int:
    if args.request and args.request_positional:
        print("error: provide request either positionally or with --request, not both", file=sys.stderr)
        return 2
    request = args.request if args.request is not None else args.request_positional
    result = create_ask_payload(
        path=Path(args.file),
        request=request,
        target_names=args.targets,
        backend=args.backend,
        plan_path=Path(args.plan) if args.plan else None,
        context_files=[Path(path) for path in args.context_files or []],
        include_git_status=args.include_git_status,
        include_git_diff=args.include_git_diff,
        provider=args.provider,
        model=args.model,
        temperature=args.temperature,
        max_output_tokens=args.max_output_tokens,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "ask_payload": result.payload,
                    "diagnostics": result.diagnostics.to_list(),
                },
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            stream = sys.stderr if result.diagnostics.has_errors else sys.stdout
            print(result.diagnostics.format(), file=stream)
        if result.payload:
            print(result.payload["response"]["content"], end="")
    return 1 if not result.ok else 0


def _exec(args: argparse.Namespace) -> int:
    if args.request and args.request_positional:
        print("error: provide request either positionally or with --request, not both", file=sys.stderr)
        return 2
    request = args.request if args.request is not None else args.request_positional
    result = create_exec_payload(
        path=Path(args.file),
        request=request,
        target_names=args.targets,
        backend=args.backend,
        tool_calls=_parse_tool_call_specs(args.tool_calls),
        provider=args.provider,
        apply=args.apply,
        sandbox_profile=args.sandbox_profile,
        execute_fallbacks=args.execute_fallbacks,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "exec_payload": result.payload,
                    "diagnostics": result.diagnostics.to_list(),
                },
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            stream = sys.stderr if result.diagnostics.has_errors else sys.stdout
            print(result.diagnostics.format(), file=stream)
        if result.payload:
            print("Tool loop prototype:")
            for tool_result in result.payload["tool_results"]:
                if tool_result["status"] == "executed":
                    print(
                        "  executed: "
                        f"{tool_result['tool']} {tool_result['input']} -> exit {tool_result['exit_code']}"
                    )
                elif tool_result["status"] == "failed":
                    print(
                        "  failed: "
                        f"{tool_result['tool']} {tool_result['input']} -> exit {tool_result['exit_code']}"
                    )
                else:
                    print(
                        "  blocked: "
                        f"{tool_result['tool']} {tool_result['input']} ({tool_result['reason']})"
                    )
            fallback_handling = result.payload["fallback_handling"]
            print(
                "  fallback handling: "
                f"{fallback_handling['status']}, executed={fallback_handling['executed']}"
            )
    return 1 if not result.ok else 0


def _plugin(args: argparse.Namespace) -> int:
    if args.plugin_command == "payload":
        return _plugin_payload(args)
    return 2


def _plugin_payload(args: argparse.Namespace) -> int:
    if args.request and args.request_positional:
        print("error: provide request either positionally or with --request, not both", file=sys.stderr)
        return 2
    request = args.request if args.request is not None else args.request_positional
    result = create_plugin_payload(
        path=Path(args.file),
        host=args.host,
        request=request,
        target_names=args.targets,
        backend=args.backend,
        plan_path=Path(args.plan) if args.plan else None,
        context_files=[Path(path) for path in args.context_files or []],
        include_git_status=args.include_git_status,
        include_git_diff=args.include_git_diff,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "plugin_payload": result.payload,
                    "diagnostics": result.diagnostics.to_list(),
                },
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            stream = sys.stderr if result.diagnostics.has_errors else sys.stdout
            print(result.diagnostics.format(), file=stream)
        if result.payload:
            print("Plugin payload:")
            print(f"  host: {result.payload['host']}")
            for target in result.payload["selected_targets"]:
                print(f"  selected target: {target}")
            prefix = result.payload["stable_prefix"]
            print(f"  stable prefix: {prefix['chars']} chars, ~{prefix['approx_tokens']} tokens")
            print(f"  stable prefix hash: {prefix['hash']}")
    return 1 if not result.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
