from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from agentmf.ask import create_ask_payload
from agentmf.benchmark import create_harness_benchmark_payload, render_harness_benchmark_markdown
from agentmf.clawbench import (
    create_clawbench_harness_export,
    create_clawbench_host_adapter_contract,
    create_clawbench_jsonl_export,
    create_clawbench_result_summary,
)
from agentmf.compiler import compile_agentmakefile
from agentmf.evolution import EVIDENCE_SOURCES, create_evolution_evidence_payload
from agentmf.loader import load_source_with_diagnostics
from agentmf.openclaw import create_openclaw_import_payload
from agentmf.plugin import create_plugin_payload
from agentmf.plugin_install import DEFAULT_PLUGIN_AGENTMAKEFILE, create_plugin_install_payload
from agentmf.prompt import create_prompt_payload
from agentmf.runtime import create_run_plan
from agentmf.selector import create_link_plan
from agentmf.skill_scanner import render_agentmakefile_from_skill_dirs
from agentmf.skill_sync import HOST_SKILL_PROFILES, create_skill_sync_payload
from agentmf.swebench import (
    SWE_BENCH_PROFILES,
    create_swebench_comparison_report,
    create_swebench_execution_adapter_contract,
    create_swebench_jsonl_export,
    create_swebench_official_adapter_plan,
    create_swebench_official_report_summary,
    create_swebench_official_run_command,
    create_swebench_pass_rate_report,
    create_swebench_predictions_export,
    create_swebench_result_summary,
    render_swebench_comparison_markdown,
    render_swebench_pass_rate_markdown,
)
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
    plugin_install_cmd = plugin_subcommands.add_parser(
        "install",
        help="scan skills into a plugin AgentMakefile and emit model instructions",
    )
    plugin_install_cmd.add_argument("--skills-dir", action="append", dest="skills_dirs", required=True)
    plugin_install_cmd.add_argument("--host", choices=["generic", "codex", "claude-code", "cursor", "opencode"], default="generic")
    plugin_install_cmd.add_argument("--namespace")
    plugin_install_cmd.add_argument("--package-name", default="scanned-skills")
    plugin_install_cmd.add_argument("--package-description")
    plugin_install_cmd.add_argument("--bootstrap-skill")
    plugin_install_cmd.add_argument("--out", default=str(DEFAULT_PLUGIN_AGENTMAKEFILE))
    plugin_install_cmd.add_argument("--write", action="store_true")
    plugin_install_cmd.add_argument("--format", choices=["text", "json"], default="json")

    skills_cmd = subparsers.add_parser("skills", help="skill index commands")
    skills_subcommands = skills_cmd.add_subparsers(dest="skills_command", required=True)
    skills_scan_cmd = skills_subcommands.add_parser("scan", help="scan SKILL.md directories into an AgentMakefile")
    skills_scan_cmd.add_argument("--skills-dir", action="append", dest="skills_dirs", required=True)
    skills_scan_cmd.add_argument("--namespace")
    skills_scan_cmd.add_argument("--package-name", default="scanned-skills")
    skills_scan_cmd.add_argument("--package-description")
    skills_scan_cmd.add_argument("--bootstrap-skill")
    skills_scan_cmd.add_argument("--out")
    skills_scan_cmd.add_argument("--write", action="store_true")
    skills_sync_cmd = skills_subcommands.add_parser(
        "sync",
        help="sync AgentMakefile-generated skills into a host skill root",
    )
    skills_sync_cmd.add_argument("--file", default="AgentMakefile")
    skills_sync_cmd.add_argument("--host", choices=sorted(HOST_SKILL_PROFILES), required=True)
    skills_sync_cmd.add_argument("--out-dir")
    skills_sync_cmd.add_argument("--write", action="store_true")
    skills_sync_cmd.add_argument("--force", action="store_true")
    skills_sync_cmd.add_argument("--format", choices=["text", "json"], default="json")

    openclaw_cmd = subparsers.add_parser("openclaw", help="OpenClaw skill ecosystem import commands")
    openclaw_subcommands = openclaw_cmd.add_subparsers(dest="openclaw_command", required=True)
    openclaw_scan_cmd = openclaw_subcommands.add_parser(
        "scan",
        help="scan local OpenClaw SKILL.md trees into modular AgentMakefiles",
    )
    openclaw_scan_cmd.add_argument("--skills-dir", action="append", dest="skills_dirs", required=True)
    openclaw_scan_cmd.add_argument("--namespace", default="openclaw")
    openclaw_scan_cmd.add_argument("--package-name", default="openclaw-skills")
    openclaw_scan_cmd.add_argument("--package-description")
    openclaw_scan_cmd.add_argument("--out", required=True)
    openclaw_scan_cmd.add_argument("--write", action="store_true")
    openclaw_scan_cmd.add_argument("--format", choices=["text", "json"], default="json")

    evo_cmd = subparsers.add_parser("evo", help="evidence-driven evolution commands")
    evo_subcommands = evo_cmd.add_subparsers(dest="evo_command", required=True)
    evo_evidence_cmd = evo_subcommands.add_parser("evidence", help="evolution evidence store commands")
    evo_evidence_subcommands = evo_evidence_cmd.add_subparsers(dest="evo_evidence_command", required=True)
    evo_evidence_add_cmd = evo_evidence_subcommands.add_parser(
        "add",
        help="append a redacted evidence record to the evolution store",
    )
    evo_evidence_add_cmd.add_argument("--source", choices=sorted(EVIDENCE_SOURCES), required=True)
    evo_evidence_add_cmd.add_argument("--payload-file", required=True)
    evo_evidence_add_cmd.add_argument("--out-dir", default=".agentmf/evolution/evidence")
    evo_evidence_add_cmd.add_argument("--timestamp")
    evo_evidence_add_cmd.add_argument("--write", action="store_true")
    evo_evidence_add_cmd.add_argument("--format", choices=["text", "json"], default="json")

    benchmark_cmd = subparsers.add_parser("benchmark", help="benchmark AgentMakefile harness behavior")
    benchmark_subcommands = benchmark_cmd.add_subparsers(dest="benchmark_command", required=True)
    benchmark_harness_cmd = benchmark_subcommands.add_parser(
        "harness",
        help="benchmark pipeline selection, prompt size, and harness coverage",
    )
    benchmark_harness_cmd.add_argument("--file", default="AgentMakefile")
    benchmark_harness_cmd.add_argument("--host", choices=["generic", "codex", "claude-code", "cursor", "opencode"], default="generic")
    benchmark_harness_cmd.add_argument("--case", action="append", dest="cases", required=True)
    benchmark_harness_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    benchmark_harness_cmd.add_argument(
        "--baseline",
        choices=["agents-md", "claude-md", "skills-index", "all-skills", "baseline-file", "none"],
        default="agents-md",
    )
    benchmark_harness_cmd.add_argument("--baseline-file")
    benchmark_harness_cmd.add_argument("--baseline-skills-dir", action="append", dest="baseline_skills_dirs")
    benchmark_harness_cmd.add_argument("--format", choices=["text", "json", "markdown"], default="markdown")

    clawbench_cmd = subparsers.add_parser("clawbench", help="ClawBench compatibility commands")
    clawbench_subcommands = clawbench_cmd.add_subparsers(dest="clawbench_command", required=True)
    clawbench_export_cmd = clawbench_subcommands.add_parser(
        "export",
        help="export a ClawBench-compatible AgentMakefile harness bundle",
    )
    clawbench_export_cmd.add_argument("--file", default="AgentMakefile")
    clawbench_export_cmd.add_argument("--task-id", required=True)
    clawbench_export_cmd.add_argument("--instruction", required=True)
    clawbench_export_cmd.add_argument("--host", choices=["generic", "codex", "claude-code", "cursor", "opencode"], default="generic")
    clawbench_export_cmd.add_argument("--model")
    clawbench_export_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    clawbench_export_cmd.add_argument("--include-git-status", action="store_true")
    clawbench_export_cmd.add_argument("--include-git-diff", action="store_true")
    clawbench_export_cmd.add_argument("--context-file", action="append", dest="context_files")
    clawbench_export_cmd.add_argument("--format", choices=["text", "json"], default="json")
    clawbench_export_jsonl_cmd = clawbench_subcommands.add_parser(
        "export-jsonl",
        help="export a JSONL file of ClawBench-compatible AgentMakefile harness bundles",
    )
    clawbench_export_jsonl_cmd.add_argument("--file", default="AgentMakefile")
    clawbench_export_jsonl_cmd.add_argument("--tasks-file", required=True)
    clawbench_export_jsonl_cmd.add_argument("--host", choices=["generic", "codex", "claude-code", "cursor", "opencode"], default="generic")
    clawbench_export_jsonl_cmd.add_argument("--model")
    clawbench_export_jsonl_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    clawbench_export_jsonl_cmd.add_argument("--include-git-status", action="store_true")
    clawbench_export_jsonl_cmd.add_argument("--include-git-diff", action="store_true")
    clawbench_export_jsonl_cmd.add_argument("--context-file", action="append", dest="context_files")
    clawbench_export_jsonl_cmd.add_argument("--out")
    clawbench_export_jsonl_cmd.add_argument("--write", action="store_true")
    clawbench_adapter_cmd = clawbench_subcommands.add_parser(
        "adapter-contract",
        help="emit the external runner contract for ClawBench host adapters",
    )
    clawbench_adapter_cmd.add_argument("--host", choices=["generic", "codex", "claude-code", "cursor", "opencode"], default="generic")
    clawbench_adapter_cmd.add_argument("--format", choices=["text", "json"], default="json")
    clawbench_import_cmd = clawbench_subcommands.add_parser(
        "import-results",
        help="import external ClawBench runner results and summarize scores",
    )
    clawbench_import_cmd.add_argument("--results-file", required=True)
    clawbench_import_cmd.add_argument("--format", choices=["text", "json"], default="json")

    swebench_cmd = subparsers.add_parser("swebench", help="SWE-bench compatibility commands")
    swebench_subcommands = swebench_cmd.add_subparsers(dest="swebench_command", required=True)
    swebench_export_jsonl_cmd = swebench_subcommands.add_parser(
        "export-jsonl",
        help="export a JSONL file of SWE-bench-compatible AgentMakefile harness bundles",
    )
    swebench_export_jsonl_cmd.add_argument("--file", default="AgentMakefile")
    swebench_export_jsonl_cmd.add_argument("--tasks-file", required=True)
    swebench_export_jsonl_cmd.add_argument("--host", choices=["generic", "codex", "claude-code", "cursor", "opencode"], default="generic")
    swebench_export_jsonl_cmd.add_argument("--model")
    swebench_export_jsonl_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    swebench_export_jsonl_cmd.add_argument("--limit", type=int)
    swebench_export_jsonl_cmd.add_argument("--include-git-status", action="store_true")
    swebench_export_jsonl_cmd.add_argument("--include-git-diff", action="store_true")
    swebench_export_jsonl_cmd.add_argument("--context-file", action="append", dest="context_files")
    swebench_export_jsonl_cmd.add_argument("--out")
    swebench_export_jsonl_cmd.add_argument("--write", action="store_true")
    swebench_compare_cmd = swebench_subcommands.add_parser(
        "compare",
        help="render a deterministic SWE-bench Lite harness comparison report",
    )
    swebench_compare_cmd.add_argument("--file", default="AgentMakefile")
    swebench_compare_cmd.add_argument("--tasks-file", required=True)
    swebench_compare_cmd.add_argument("--host", choices=["generic", "codex", "claude-code", "cursor", "opencode"], default="generic")
    swebench_compare_cmd.add_argument("--model")
    swebench_compare_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    swebench_compare_cmd.add_argument("--limit", type=int)
    swebench_compare_cmd.add_argument(
        "--baseline",
        action="append",
        dest="baselines",
        choices=["agents-md", "claude-md", "skills-index", "baseline-file", "none"],
    )
    swebench_compare_cmd.add_argument("--baseline-file")
    swebench_compare_cmd.add_argument("--out")
    swebench_compare_cmd.add_argument("--write", action="store_true")
    swebench_compare_cmd.add_argument("--format", choices=["json", "markdown"], default="markdown")
    swebench_adapter_cmd = swebench_subcommands.add_parser(
        "adapter-contract",
        help="emit the external runner contract for SWE-bench execution adapters",
    )
    swebench_adapter_cmd.add_argument("--host", choices=["generic", "codex", "claude-code", "cursor", "opencode"], default="generic")
    swebench_adapter_cmd.add_argument("--format", choices=["text", "json"], default="json")
    swebench_import_cmd = swebench_subcommands.add_parser(
        "import-results",
        help="import external SWE-bench execution results and summarize pass-rate metrics",
    )
    swebench_import_cmd.add_argument("--results-file", required=True)
    swebench_import_cmd.add_argument("--format", choices=["text", "json"], default="json")
    swebench_pass_report_cmd = swebench_subcommands.add_parser(
        "pass-report",
        help="render a SWE-bench pass-rate report from imported execution results",
    )
    swebench_pass_report_cmd.add_argument("--results-file", required=True)
    swebench_pass_report_cmd.add_argument("--baseline-report")
    swebench_pass_report_cmd.add_argument("--out")
    swebench_pass_report_cmd.add_argument("--write", action="store_true")
    swebench_pass_report_cmd.add_argument("--format", choices=["json", "markdown"], default="markdown")
    swebench_predictions_cmd = swebench_subcommands.add_parser(
        "predictions",
        help="export official SWE-bench predictions JSONL from external execution results",
    )
    swebench_predictions_cmd.add_argument("--results-file", required=True)
    swebench_predictions_cmd.add_argument("--model-name", required=True)
    swebench_predictions_cmd.add_argument("--dataset", choices=sorted(SWE_BENCH_PROFILES), default="lite")
    swebench_predictions_cmd.add_argument("--out")
    swebench_predictions_cmd.add_argument("--write", action="store_true")
    swebench_predictions_cmd.add_argument("--format", choices=["json", "jsonl"], default="jsonl")
    swebench_official_command_cmd = swebench_subcommands.add_parser(
        "official-command",
        help="emit the official SWE-bench run_evaluation command for a dataset profile",
    )
    swebench_official_command_cmd.add_argument("--dataset", choices=sorted(SWE_BENCH_PROFILES), default="lite")
    swebench_official_command_cmd.add_argument("--predictions-path", required=True)
    swebench_official_command_cmd.add_argument("--run-id", required=True)
    swebench_official_command_cmd.add_argument("--max-workers", type=int, default=4)
    swebench_official_command_cmd.add_argument("--split")
    swebench_official_command_cmd.add_argument("--instance-id", action="append", dest="instance_ids")
    swebench_official_command_cmd.add_argument("--format", choices=["text", "json"], default="text")
    swebench_official_report_cmd = swebench_subcommands.add_parser(
        "import-official-report",
        help="import an official SWE-bench run report JSON file",
    )
    swebench_official_report_cmd.add_argument("--report-file", required=True)
    swebench_official_report_cmd.add_argument("--format", choices=["text", "json"], default="json")
    swebench_official_dry_run_cmd = swebench_subcommands.add_parser(
        "official-dry-run",
        help="validate predictions and emit a side-effect-free official SWE-bench adapter plan",
    )
    swebench_official_dry_run_cmd.add_argument("--dataset", choices=sorted(SWE_BENCH_PROFILES), default="lite")
    swebench_official_dry_run_cmd.add_argument("--predictions-path", required=True)
    swebench_official_dry_run_cmd.add_argument("--run-id", required=True)
    swebench_official_dry_run_cmd.add_argument("--max-workers", type=int, default=4)
    swebench_official_dry_run_cmd.add_argument("--smoke-limit", type=int, default=5)
    swebench_official_dry_run_cmd.add_argument("--split")
    swebench_official_dry_run_cmd.add_argument("--format", choices=["text", "json"], default="json")

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
    if args.command == "skills":
        return _skills(args)
    if args.command == "openclaw":
        return _openclaw(args)
    if args.command == "evo":
        return _evo(args)
    if args.command == "benchmark":
        return _benchmark(args)
    if args.command == "clawbench":
        return _clawbench(args)
    if args.command == "swebench":
        return _swebench(args)
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
    if args.plugin_command == "install":
        return _plugin_install(args)
    return 2


def _skills(args: argparse.Namespace) -> int:
    if args.skills_command == "scan":
        return _skills_scan(args)
    if args.skills_command == "sync":
        return _skills_sync(args)
    return 2


def _openclaw(args: argparse.Namespace) -> int:
    if args.openclaw_command == "scan":
        return _openclaw_scan(args)
    return 2


def _evo(args: argparse.Namespace) -> int:
    if args.evo_command == "evidence" and args.evo_evidence_command == "add":
        return _evo_evidence_add(args)
    return 2


def _benchmark(args: argparse.Namespace) -> int:
    if args.benchmark_command == "harness":
        return _benchmark_harness(args)
    return 2


def _clawbench(args: argparse.Namespace) -> int:
    if args.clawbench_command == "export":
        return _clawbench_export(args)
    if args.clawbench_command == "export-jsonl":
        return _clawbench_export_jsonl(args)
    if args.clawbench_command == "adapter-contract":
        return _clawbench_adapter_contract(args)
    if args.clawbench_command == "import-results":
        return _clawbench_import_results(args)
    return 2


def _swebench(args: argparse.Namespace) -> int:
    if args.swebench_command == "export-jsonl":
        return _swebench_export_jsonl(args)
    if args.swebench_command == "compare":
        return _swebench_compare(args)
    if args.swebench_command == "adapter-contract":
        return _swebench_adapter_contract(args)
    if args.swebench_command == "import-results":
        return _swebench_import_results(args)
    if args.swebench_command == "pass-report":
        return _swebench_pass_report(args)
    if args.swebench_command == "predictions":
        return _swebench_predictions(args)
    if args.swebench_command == "official-command":
        return _swebench_official_command(args)
    if args.swebench_command == "import-official-report":
        return _swebench_import_official_report(args)
    if args.swebench_command == "official-dry-run":
        return _swebench_official_dry_run(args)
    return 2


def _swebench_official_dry_run(args: argparse.Namespace) -> int:
    result = create_swebench_official_adapter_plan(
        dataset_profile=args.dataset,
        predictions_path=Path(args.predictions_path),
        run_id=args.run_id,
        max_workers=args.max_workers,
        smoke_limit=args.smoke_limit,
        split=args.split,
    )
    if not result.ok:
        print(result.diagnostics.format(), file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps({"ok": True, "swebench_official_dry_run": result.payload}, indent=2))
    else:
        print("SWE-bench official dry-run adapter plan:")
        print(f"  profile: {result.payload['profile']['id']}")
        print(f"  predictions: {result.payload['prediction_summary']['prediction_count']}")
        print(f"  smoke command: {result.payload['commands']['smoke']['command_text']}")
        print(f"  full command: {result.payload['commands']['full']['command_text']}")
    return 0


def _swebench_predictions(args: argparse.Namespace) -> int:
    result = create_swebench_predictions_export(
        results_file=Path(args.results_file),
        model_name_or_path=args.model_name,
        dataset_profile=args.dataset,
    )
    if not result.ok:
        print(result.diagnostics.format(), file=sys.stderr)
        return 1
    if args.format == "json":
        content = json.dumps({"ok": True, "swebench_predictions": result.payload}, indent=2) + "\n"
    else:
        content = result.payload["jsonl"]
    if args.out:
        out_path = Path(args.out)
        if args.write:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        else:
            print(f"would write {out_path}")
            print(content, end="")
    else:
        print(content, end="")
    for item in result.diagnostics.items:
        if item.severity != "error":
            print(item.format(), file=sys.stderr)
    return 0


def _swebench_official_command(args: argparse.Namespace) -> int:
    result = create_swebench_official_run_command(
        dataset_profile=args.dataset,
        predictions_path=Path(args.predictions_path),
        run_id=args.run_id,
        max_workers=args.max_workers,
        split=args.split,
        instance_ids=args.instance_ids,
    )
    if not result.ok:
        print(result.diagnostics.format(), file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps({"ok": True, "swebench_official_command": result.payload}, indent=2))
    else:
        print(result.payload["command_text"])
    return 0


def _swebench_import_official_report(args: argparse.Namespace) -> int:
    result = create_swebench_official_report_summary(report_file=Path(args.report_file))
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "swebench_official_report": result.payload,
                    "diagnostics": result.diagnostics.to_list(),
                },
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            print(result.diagnostics.format(), file=sys.stderr if result.diagnostics.has_errors else sys.stdout)
        if result.payload:
            summary = result.payload["summary"]
            print("SWE-bench official report:")
            print(f"  submitted: {summary['submitted_instances']}")
            print(f"  completed: {summary['completed_instances']}")
            print(f"  resolved rate: {summary['resolved_rate']}")
    return 1 if not result.ok else 0


def _swebench_adapter_contract(args: argparse.Namespace) -> int:
    result = create_swebench_execution_adapter_contract(host=args.host)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "swebench_adapter_contract": result.payload,
                    "diagnostics": result.diagnostics.to_list(),
                },
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            print(result.diagnostics.format(), file=sys.stderr if result.diagnostics.has_errors else sys.stdout)
        if result.payload:
            print("SWE-bench execution adapter contract:")
            print(f"  host: {result.payload['adapter']['host']}")
            print(f"  input: {result.payload['input_contract']['format']} {result.payload['input_contract']['record_mode']}")
            print(f"  output: {result.payload['output_contract']['format']} {result.payload['output_contract']['record_mode']}")
    return 1 if not result.ok else 0


def _swebench_import_results(args: argparse.Namespace) -> int:
    result = create_swebench_result_summary(results_file=Path(args.results_file))
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "swebench_results": result.payload,
                    "diagnostics": result.diagnostics.to_list(),
                },
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            print(result.diagnostics.format(), file=sys.stderr if result.diagnostics.has_errors else sys.stdout)
        if result.payload:
            summary = result.payload["summary"]
            print("SWE-bench execution results:")
            print(f"  results: {summary['result_count']}")
            print(f"  resolved rate: {summary['resolved_rate']}")
            print(f"  tests passed rate: {summary['tests_passed_rate']}")
    return 1 if not result.ok else 0


def _swebench_pass_report(args: argparse.Namespace) -> int:
    result = create_swebench_pass_rate_report(
        results_file=Path(args.results_file),
        baseline_report=Path(args.baseline_report) if args.baseline_report else None,
    )
    if not result.ok:
        print(result.diagnostics.format(), file=sys.stderr)
        return 1
    if args.format == "json":
        content = json.dumps({"ok": True, "swebench_pass_report": result.payload}, indent=2) + "\n"
    else:
        content = render_swebench_pass_rate_markdown(result.payload)
    if args.out:
        out_path = Path(args.out)
        if args.write:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        else:
            print(f"would write {out_path}")
            print(content, end="")
    else:
        print(content, end="")
    for item in result.diagnostics.items:
        if item.severity != "error":
            print(item.format(), file=sys.stderr)
    return 0


def _swebench_compare(args: argparse.Namespace) -> int:
    result = create_swebench_comparison_report(
        path=Path(args.file),
        tasks_file=Path(args.tasks_file),
        host=args.host,
        model=args.model,
        backend=args.backend,
        limit=args.limit,
        baselines=args.baselines,
        baseline_file=Path(args.baseline_file) if args.baseline_file else None,
    )
    if not result.ok:
        print(result.diagnostics.format(), file=sys.stderr)
        return 1
    if args.format == "json":
        content = json.dumps({"ok": True, "swebench_comparison": result.payload}, indent=2) + "\n"
    else:
        content = render_swebench_comparison_markdown(result.payload)
    if args.out:
        out_path = Path(args.out)
        if args.write:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")
        else:
            print(f"would write {out_path}")
            print(content, end="")
    else:
        print(content, end="")
    for item in result.diagnostics.items:
        if item.severity != "error":
            print(item.format(), file=sys.stderr)
    return 0


def _swebench_export_jsonl(args: argparse.Namespace) -> int:
    result = create_swebench_jsonl_export(
        path=Path(args.file),
        tasks_file=Path(args.tasks_file),
        host=args.host,
        model=args.model,
        backend=args.backend,
        limit=args.limit,
        include_git_status=args.include_git_status,
        include_git_diff=args.include_git_diff,
        context_files=[Path(item) for item in args.context_files] if args.context_files else None,
    )
    if not result.ok:
        print(result.diagnostics.format(), file=sys.stderr)
        return 1
    if args.out:
        out_path = Path(args.out)
        if args.write:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(result.payload["jsonl"], encoding="utf-8")
        else:
            print(f"would write {out_path}")
            print(result.payload["jsonl"], end="")
    else:
        print(result.payload["jsonl"], end="")
    for item in result.diagnostics.items:
        if item.severity != "error":
            print(item.format(), file=sys.stderr)
    return 0


def _clawbench_adapter_contract(args: argparse.Namespace) -> int:
    result = create_clawbench_host_adapter_contract(host=args.host)
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "clawbench_adapter_contract": result.payload,
                    "diagnostics": result.diagnostics.to_list(),
                },
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            print(result.diagnostics.format(), file=sys.stderr if result.diagnostics.has_errors else sys.stdout)
        if result.payload:
            print("ClawBench host adapter contract:")
            print(f"  host: {result.payload['adapter']['host']}")
            print(f"  input: {result.payload['input_contract']['format']} {result.payload['input_contract']['record_mode']}")
            print(f"  output: {result.payload['output_contract']['format']} {result.payload['output_contract']['record_mode']}")
    return 1 if not result.ok else 0


def _clawbench_import_results(args: argparse.Namespace) -> int:
    result = create_clawbench_result_summary(results_file=Path(args.results_file))
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "clawbench_results": result.payload,
                    "diagnostics": result.diagnostics.to_list(),
                },
                indent=2,
            )
        )
    else:
        if result.diagnostics.items:
            print(result.diagnostics.format(), file=sys.stderr if result.diagnostics.has_errors else sys.stdout)
        if result.payload:
            summary = result.payload["summary"]
            print("ClawBench external runner results:")
            print(f"  results: {summary['result_count']}")
            print(f"  pass rate: {summary['pass_rate']}")
            print(f"  average total tokens: {summary['average_total_tokens']}")
            print(f"  average cost usd: {summary['average_cost_usd']}")
            print(f"  denied tool calls: {summary['denied_tool_calls']}")
    return 1 if not result.ok else 0


def _clawbench_export_jsonl(args: argparse.Namespace) -> int:
    result = create_clawbench_jsonl_export(
        path=Path(args.file),
        tasks_file=Path(args.tasks_file),
        host=args.host,
        model=args.model,
        backend=args.backend,
        include_git_status=args.include_git_status,
        include_git_diff=args.include_git_diff,
        context_files=[Path(path) for path in args.context_files or []],
    )
    if result.diagnostics.items:
        print(result.diagnostics.format(), file=sys.stderr)
    if not result.ok:
        return 1
    if args.write:
        if not args.out:
            print("error: --write requires --out", file=sys.stderr)
            return 2
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(result.payload["jsonl"], encoding="utf-8")
        print(f"Wrote {out}")
    else:
        print(result.payload["jsonl"], end="")
    return 0


def _clawbench_export(args: argparse.Namespace) -> int:
    result = create_clawbench_harness_export(
        path=Path(args.file),
        task_id=args.task_id,
        instruction=args.instruction,
        host=args.host,
        model=args.model,
        backend=args.backend,
        include_git_status=args.include_git_status,
        include_git_diff=args.include_git_diff,
        context_files=[Path(path) for path in args.context_files or []],
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "clawbench_harness": result.payload,
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
            print("ClawBench harness export:")
            print(f"  task: {result.payload['task']['id']}")
            print(f"  host: {result.payload['run']['host']}")
            print(f"  model: {result.payload['run']['model']}")
            print(f"  selected targets: {', '.join(result.payload['agentmf']['selected_targets'])}")
            print(f"  stable prefix: {result.payload['agentmf']['stable_prefix_hash']}")
            print("  execution: not performed")
    return 1 if not result.ok else 0


def _benchmark_harness(args: argparse.Namespace) -> int:
    result = create_harness_benchmark_payload(
        path=Path(args.file),
        cases=args.cases,
        host=args.host,
        backend=args.backend,
        baseline=args.baseline,
        baseline_file=Path(args.baseline_file) if args.baseline_file else None,
        baseline_skills_dirs=[Path(path) for path in args.baseline_skills_dirs or []],
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "harness_benchmark": result.payload,
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
            print(render_harness_benchmark_markdown(result.payload), end="")
    return 1 if not result.ok else 0


def _skills_scan(args: argparse.Namespace) -> int:
    try:
        content = render_agentmakefile_from_skill_dirs(
            [Path(path) for path in args.skills_dirs],
            namespace=args.namespace,
            package_name=args.package_name,
            package_description=args.package_description,
            bootstrap_skill=args.bootstrap_skill,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.write:
        if not args.out:
            print("error: --write requires --out", file=sys.stderr)
            return 2
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content)
        print(f"Wrote {out_path}")
    else:
        print(content, end="")
    return 0


def _openclaw_scan(args: argparse.Namespace) -> int:
    result = create_openclaw_import_payload(
        skill_dirs=[Path(path) for path in args.skills_dirs],
        out_dir=Path(args.out),
        namespace=args.namespace,
        package_name=args.package_name,
        package_description=args.package_description,
        write=args.write,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "openclaw_import": result.payload,
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
            action = "Wrote" if args.write else "Would write"
            print(f"{action} OpenClaw AgentMakefile modules:")
            print(f"  root: {result.payload['root_path']}")
            print(f"  skills: {result.payload['skill_count']}")
            print(f"  categories: {result.payload['category_count']}")
            for category in result.payload["categories"]:
                print(f"  - {category['name']}: {category['skill_count']} skills")
    return 1 if not result.ok else 0


def _evo_evidence_add(args: argparse.Namespace) -> int:
    try:
        payload = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: could not read payload file: {exc}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict):
        print("error: payload file must contain a JSON object", file=sys.stderr)
        return 1

    result = create_evolution_evidence_payload(
        source=args.source,
        payload=payload,
        out_dir=Path(args.out_dir),
        timestamp=args.timestamp,
        write=args.write,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "evolution_evidence": result.payload,
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
            action = "Appended" if args.write else "Would append"
            print(f"{action} evolution evidence:")
            print(f"  source: {result.payload['record']['source']}")
            print(f"  path: {result.payload['path']}")
            print(f"  event: {result.payload['record']['event_id']}")
    return 1 if not result.ok else 0


def _skills_sync(args: argparse.Namespace) -> int:
    result = create_skill_sync_payload(
        path=Path(args.file),
        host=args.host,
        out_dir=Path(args.out_dir) if args.out_dir else None,
        write=args.write,
        force=args.force,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "skill_sync_payload": result.payload,
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
            action = "Synced" if args.write else "Would sync"
            print(f"{action} skills for {result.payload['host']}:")
            print(f"  source: {result.payload['agentmakefile_path']}")
            print(f"  skill root: {result.payload['skill_root']}")
            for file in result.payload["files"]:
                print(f"  {file['status']}: {file['destination']}")
            print("\nHost integration:")
            print(result.payload["host_integration_instructions"])
    return 1 if not result.ok else 0


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
            for skill in result.payload["selected_skills"]:
                print(f"  selected skill: {skill}")
            selected = result.payload["selection_trace"].get("selected", {})
            if selected.get("target"):
                print(f"  selection reason: {selected['target']}")
                matched_terms = selected.get("matched_terms") or []
                if matched_terms:
                    print(f"  matched terms: {', '.join(matched_terms)}")
            prefix = result.payload["stable_prefix"]
            print(f"  stable prefix: {prefix['chars']} chars, ~{prefix['approx_tokens']} tokens")
            print(f"  stable prefix hash: {prefix['hash']}")
    return 1 if not result.ok else 0


def _plugin_install(args: argparse.Namespace) -> int:
    result = create_plugin_install_payload(
        skill_dirs=[Path(path) for path in args.skills_dirs],
        host=args.host,
        namespace=args.namespace,
        package_name=args.package_name,
        package_description=args.package_description,
        bootstrap_skill=args.bootstrap_skill,
        out_path=Path(args.out),
        write=args.write,
    )
    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "plugin_install_payload": result.payload,
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
            print("Plugin install payload:")
            print(f"  host: {result.payload['host']}")
            print(f"  AgentMakefile: {result.payload['agentmakefile']['path']}")
            print(f"  wrote: {result.payload['agentmakefile']['wrote']}")
            print(f"  next payload command: {result.payload['next_payload_command']}")
            print("\nModel instructions:")
            print(result.payload["model_instructions"])
    return 1 if not result.ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
