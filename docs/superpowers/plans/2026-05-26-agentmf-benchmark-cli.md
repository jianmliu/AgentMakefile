# AgentMakefile Benchmark CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic `agentmf benchmark skills` command that measures request-specific skill routing, prompt prefix size, stable hash reuse, and savings against the generated `AGENTS.md` baseline.

**Architecture:** Add a focused benchmark module that loops over benchmark cases and reuses `create_plugin_payload(...)` for routing, trace evidence, selected skills, stable prefix hashes, and existing prompt-size comparison. Expose the module through an argparse subcommand and render either JSON for CI or Markdown for demos and documentation.

**Tech Stack:** Python standard library, existing `agentmf.plugin`, existing `agentmf.runtime` comparison data, argparse CLI, pytest.

---

## File Structure

- Create `src/agentmf/benchmark.py`: benchmark case model, benchmark payload builder, mismatch evaluation, summary metrics, Markdown renderer.
- Modify `src/agentmf/__init__.py`: export `SkillBenchmarkCase`, `SkillBenchmarkResult`, `create_skill_benchmark_payload`, and `render_skill_benchmark_markdown`.
- Modify `src/agentmf/cli.py`: add `agentmf benchmark skills` with inline `--case`, `--host`, `--backend`, `--baseline agents-md`, `--format`, `--out`, `--write`, and `--fail-on-mismatch`.
- Modify `tests/test_agentmf.py`: add tests for benchmark payload generation, mismatch handling, Markdown rendering, and CLI output/write behavior.
- Modify `README.md`: add a benchmark command example to the command surface and link it to the benchmark spec.
- Modify `docs/agentmf_step_by_step_demo.md`: add a short benchmark walkthrough using `modules/superpowers/AgentMakefile`.
- Modify `docs/spec_breakdown.md`: record the first benchmark CLI slice as completed when the feature lands.

## Scope

This plan implements the first benchmark CLI slice from `docs/agentmf_benchmark_cli_spec.md`:

- `agentmf benchmark skills`
- `--file`
- repeatable inline `--case`
- `--host generic|codex|claude-code`
- `--backend agents-fragments|claude-fragments`
- `--baseline agents-md`
- `--format json|markdown|text`
- `--out`
- `--write`
- `--fail-on-mismatch`

This plan does not add `--cases-file`, `--baseline-file`, `--baseline-skills-dir`, `claude-md`, `skills-index`, or `all-skills`. Those surfaces stay documented in the spec and should be added after the first deterministic loop is verified.

This benchmark plan assumes the `--file` input is already an AgentMakefile,
including a generated guidance-index module. Multi-source ingestion from
`AGENTS.md`, `CLAUDE.md`, and standalone `SKILL.md` is tracked separately in
`docs/superpowers/plans/2026-05-26-agentmf-guidance-ingestion.md`; benchmark
support should work for those generated modules once ingestion lands.

## Task 1: Add Skill Benchmark Payload Builder

**Files:**
- Create: `src/agentmf/benchmark.py`
- Modify: `src/agentmf/__init__.py`
- Test: `tests/test_agentmf.py`

- [ ] **Step 1: Write the failing payload test**

Append this test near the existing plugin payload tests in `tests/test_agentmf.py`:

```python
def test_skill_benchmark_payload_reports_token_savings_for_inline_cases() -> None:
    from agentmf.benchmark import create_skill_benchmark_payload

    result = create_skill_benchmark_payload(
        path=SUPERPOWERS_MODULE,
        cases=[
            "write an implementation plan",
            "debug failing test",
        ],
        host="codex",
        backend="agents-fragments",
        baseline="agents-md",
    )

    assert result.ok, result.diagnostics.format()
    payload = result.payload
    assert payload["version"] == 1
    assert payload["agentmakefile_path"] == str(SUPERPOWERS_MODULE)
    assert payload["host"] == "codex"
    assert payload["backend"] == "agents-fragments"
    assert payload["baseline"]["kind"] == "agents-md"
    assert payload["summary"]["case_count"] == 2
    assert payload["summary"]["average_savings_tokens"] > 0
    assert payload["summary"]["median_savings_tokens"] > 0
    assert payload["summary"]["unique_stable_prefix_hashes"] >= 1
    assert [case["id"] for case in payload["cases"]] == ["case-1", "case-2"]
    assert payload["cases"][0]["request"] == "write an implementation plan"
    assert payload["cases"][0]["selected_targets"]
    assert payload["cases"][0]["selected_skills"]
    assert payload["cases"][0]["stable_prefix"]["hash"].startswith("sha256:")
    assert payload["cases"][0]["baseline"]["approx_tokens"] > payload["cases"][0]["stable_prefix"]["approx_tokens"]
    assert payload["cases"][0]["savings"]["approx_tokens"] > 0
    assert payload["cases"][0]["selection_match"]["targets"] is None
    assert payload["cases"][0]["selection_match"]["skills"] is None
    assert payload["diagnostics"] == []
```

- [ ] **Step 2: Run the test to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_skill_benchmark_payload_reports_token_savings_for_inline_cases -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmf.benchmark'`.

- [ ] **Step 3: Create the benchmark module**

Create `src/agentmf/benchmark.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Union

from agentmf.diagnostics import Diagnostics
from agentmf.plugin import create_plugin_payload


SUPPORTED_BASELINES = {"agents-md"}


@dataclass(frozen=True)
class SkillBenchmarkCase:
    request: str
    id: Optional[str] = None
    expected_targets: List[str] = field(default_factory=list)
    expected_skills: List[str] = field(default_factory=list)


@dataclass
class SkillBenchmarkResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_skill_benchmark_payload(
    path: Union[Path, str],
    *,
    cases: Sequence[Union[str, SkillBenchmarkCase]],
    host: str = "generic",
    backend: str = "agents-fragments",
    baseline: str = "agents-md",
    fail_on_mismatch: bool = False,
) -> SkillBenchmarkResult:
    diagnostics = Diagnostics()
    agentmakefile_path = Path(path)
    if baseline not in SUPPORTED_BASELINES:
        diagnostics.error(
            "AMF143",
            f"unsupported benchmark baseline: {baseline}",
            "benchmark.baseline",
            "first benchmark slice supports agents-md",
        )
        return SkillBenchmarkResult(diagnostics)
    if not cases:
        diagnostics.error(
            "AMF142",
            "at least one benchmark case is required",
            "benchmark.cases",
            "pass one or more --case values",
        )
        return SkillBenchmarkResult(diagnostics)

    normalized_cases = _normalize_cases(cases)
    case_payloads: List[Dict[str, Any]] = []
    baseline_summary: Optional[Dict[str, Any]] = None
    for benchmark_case in normalized_cases:
        plugin_result = create_plugin_payload(
            path=agentmakefile_path,
            host=host,
            request=benchmark_case.request,
            backend=backend,
        )
        diagnostics.extend(plugin_result.diagnostics.items)
        if plugin_result.diagnostics.has_errors:
            continue
        plugin_payload = plugin_result.payload
        comparison = plugin_payload["trace"]["comparison"]
        baseline_summary = comparison["all_in_one"]
        target_match = _matches_expected(
            plugin_payload["selected_targets"],
            benchmark_case.expected_targets,
        )
        skill_match = _matches_expected(
            plugin_payload["selected_skills"],
            benchmark_case.expected_skills,
        )
        savings = _savings_with_percent(comparison)
        case_payloads.append(
            {
                "id": benchmark_case.id,
                "request": benchmark_case.request,
                "selected_targets": plugin_payload["selected_targets"],
                "target_closure": plugin_payload["trace"]["target_closure"],
                "selected_skills": plugin_payload["selected_skills"],
                "skill_artifacts": plugin_payload["skill_artifacts"],
                "stable_prefix": {
                    "chars": plugin_payload["stable_prefix"]["chars"],
                    "approx_tokens": plugin_payload["stable_prefix"]["approx_tokens"],
                    "hash": plugin_payload["stable_prefix"]["hash"],
                },
                "baseline": comparison["all_in_one"],
                "savings": savings,
                "selection_match": {
                    "targets": target_match,
                    "skills": skill_match,
                },
                "expected_targets": list(benchmark_case.expected_targets),
                "expected_skills": list(benchmark_case.expected_skills),
                "matched_terms": plugin_payload["selection_trace"].get("selected", {}).get("matched_terms", []),
                "match_details": plugin_payload["selection_trace"].get("selected", {}).get("match_details", []),
                "selection_trace": plugin_payload["selection_trace"],
            }
        )

    if diagnostics.has_errors:
        return SkillBenchmarkResult(diagnostics)

    payload = {
        "ok": True,
        "version": 1,
        "agentmakefile_path": str(agentmakefile_path),
        "host": host,
        "backend": backend,
        "baseline": {
            "kind": baseline,
            "chars": baseline_summary["chars"] if baseline_summary else 0,
            "approx_tokens": baseline_summary["approx_tokens"] if baseline_summary else 0,
        },
        "summary": _summarize_cases(case_payloads),
        "cases": case_payloads,
        "diagnostics": diagnostics.to_list(),
    }
    return SkillBenchmarkResult(diagnostics, payload)


def _normalize_cases(cases: Sequence[Union[str, SkillBenchmarkCase]]) -> List[SkillBenchmarkCase]:
    normalized = []
    for index, case in enumerate(cases, start=1):
        if isinstance(case, SkillBenchmarkCase):
            case_id = case.id or f"case-{index}"
            normalized.append(
                SkillBenchmarkCase(
                    id=case_id,
                    request=case.request,
                    expected_targets=list(case.expected_targets),
                    expected_skills=list(case.expected_skills),
                )
            )
        else:
            normalized.append(SkillBenchmarkCase(id=f"case-{index}", request=case))
    return normalized


def _matches_expected(actual: Sequence[str], expected: Sequence[str]) -> Optional[bool]:
    if not expected:
        return None
    return list(actual) == list(expected)


def _savings_with_percent(comparison: Dict[str, Any]) -> Dict[str, Any]:
    baseline_tokens = comparison["all_in_one"]["approx_tokens"]
    savings = dict(comparison["savings"])
    savings["percent"] = round((savings["approx_tokens"] / baseline_tokens) * 100, 1) if baseline_tokens else 0.0
    return savings


def _summarize_cases(cases: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    savings_tokens = [case["savings"]["approx_tokens"] for case in cases]
    savings_percent = [case["savings"].get("percent", 0.0) for case in cases]
    return {
        "case_count": len(cases),
        "matched_target_cases": sum(1 for case in cases if case["selection_match"]["targets"] is True),
        "matched_skill_cases": sum(1 for case in cases if case["selection_match"]["skills"] is True),
        "average_savings_tokens": round(sum(savings_tokens) / len(savings_tokens)) if savings_tokens else 0,
        "median_savings_tokens": round(median(savings_tokens)) if savings_tokens else 0,
        "average_savings_percent": round(sum(savings_percent) / len(savings_percent), 1) if savings_percent else 0.0,
        "unique_stable_prefix_hashes": len({case["stable_prefix"]["hash"] for case in cases}),
    }
```

- [ ] **Step 4: Export the benchmark API**

Modify `src/agentmf/__init__.py` imports:

```python
from agentmf.benchmark import SkillBenchmarkCase, SkillBenchmarkResult, create_skill_benchmark_payload
```

Add these names to `__all__`:

```python
"SkillBenchmarkCase",
"SkillBenchmarkResult",
"create_skill_benchmark_payload",
```

- [ ] **Step 5: Run the payload test to confirm green**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_skill_benchmark_payload_reports_token_savings_for_inline_cases -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agentmf/benchmark.py src/agentmf/__init__.py tests/test_agentmf.py
git commit -m "Add skill benchmark payload builder"
```

## Task 2: Add Expected Selection Mismatch Handling

**Files:**
- Modify: `src/agentmf/benchmark.py`
- Test: `tests/test_agentmf.py`

- [ ] **Step 1: Write the failing mismatch test**

Append this test near the benchmark payload test:

```python
def test_skill_benchmark_payload_fails_on_expected_skill_mismatch() -> None:
    from agentmf.benchmark import SkillBenchmarkCase, create_skill_benchmark_payload

    result = create_skill_benchmark_payload(
        path=SUPERPOWERS_MODULE,
        cases=[
            SkillBenchmarkCase(
                id="bad-expectation",
                request="write an implementation plan",
                expected_targets=["methodology.debug"],
                expected_skills=["superpowers:systematic-debugging"],
            )
        ],
        fail_on_mismatch=True,
    )

    assert not result.ok
    codes = [item.code for item in result.diagnostics.items]
    assert "AMF144" in codes
    assert "AMF145" in codes
```

- [ ] **Step 2: Run the test to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_skill_benchmark_payload_fails_on_expected_skill_mismatch -q
```

Expected: FAIL because `create_skill_benchmark_payload(...)` accepts `fail_on_mismatch` but still returns `ok` for mismatched expected labels.

- [ ] **Step 3: Confirm mismatch diagnostics are emitted before returning**

Modify `create_skill_benchmark_payload(...)` so the mismatch block runs immediately after `target_match` and `skill_match` are computed:

```python
        if fail_on_mismatch and target_match is False:
            diagnostics.error(
                "AMF144",
                f"benchmark case {benchmark_case.id} selected unexpected targets",
                "benchmark.expected_targets",
                "inspect selection_trace for matched terms and target scores",
            )
        if fail_on_mismatch and skill_match is False:
            diagnostics.error(
                "AMF145",
                f"benchmark case {benchmark_case.id} selected unexpected skills",
                "benchmark.expected_skills",
                "inspect selected_skills and target skill declarations",
            )
```

- [ ] **Step 4: Run the mismatch test to confirm green**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_skill_benchmark_payload_fails_on_expected_skill_mismatch -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentmf/benchmark.py tests/test_agentmf.py
git commit -m "Validate benchmark expected skill selection"
```

## Task 3: Add Markdown Renderer

**Files:**
- Modify: `src/agentmf/benchmark.py`
- Modify: `src/agentmf/__init__.py`
- Test: `tests/test_agentmf.py`

- [ ] **Step 1: Write the failing Markdown renderer test**

Append this test near the benchmark tests:

```python
def test_skill_benchmark_markdown_contains_summary_table() -> None:
    from agentmf.benchmark import create_skill_benchmark_payload, render_skill_benchmark_markdown

    result = create_skill_benchmark_payload(
        path=SUPERPOWERS_MODULE,
        cases=["write an implementation plan"],
        host="codex",
    )

    assert result.ok, result.diagnostics.format()
    markdown = render_skill_benchmark_markdown(result.payload)

    assert markdown.startswith("# AgentMakefile Skill Benchmark\n")
    assert f"Source: `{SUPERPOWERS_MODULE}`" in markdown
    assert "Baseline: `agents-md`" in markdown
    assert "| case-1 |" in markdown
    assert "write an implementation plan" in markdown
    assert "sha256:" in markdown
    assert "Selected Skills" in markdown
```

- [ ] **Step 2: Run the test to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_skill_benchmark_markdown_contains_summary_table -q
```

Expected: FAIL with `ImportError` or `AttributeError` for `render_skill_benchmark_markdown`.

- [ ] **Step 3: Add the renderer**

Append this function to `src/agentmf/benchmark.py`:

```python
def render_skill_benchmark_markdown(payload: Dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# AgentMakefile Skill Benchmark",
        "",
        f"Source: `{payload['agentmakefile_path']}`",
        f"Host: `{payload['host']}`",
        f"Backend: `{payload['backend']}`",
        f"Baseline: `{payload['baseline']['kind']}` "
        f"({payload['baseline']['chars']} chars, ~{payload['baseline']['approx_tokens']} tokens)",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Cases | {summary['case_count']} |",
        f"| Matched target cases | {summary['matched_target_cases']} |",
        f"| Matched skill cases | {summary['matched_skill_cases']} |",
        f"| Average savings | ~{summary['average_savings_tokens']} tokens |",
        f"| Median savings | ~{summary['median_savings_tokens']} tokens |",
        f"| Average savings percent | {summary['average_savings_percent']}% |",
        f"| Unique stable prefix hashes | {summary['unique_stable_prefix_hashes']} |",
        "",
        "## Cases",
        "",
        "| Case | Request | Targets | Skills | Stable Prefix | Savings | Hash |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for case in payload["cases"]:
        targets = ", ".join(case["selected_targets"]) or "-"
        skills = ", ".join(case["selected_skills"]) or "-"
        stable_tokens = case["stable_prefix"]["approx_tokens"]
        savings_tokens = case["savings"]["approx_tokens"]
        prefix_hash = case["stable_prefix"]["hash"]
        lines.append(
            f"| {case['id']} | {_escape_table_cell(case['request'])} | "
            f"{_escape_table_cell(targets)} | {_escape_table_cell(skills)} | "
            f"~{stable_tokens} tokens | ~{savings_tokens} tokens | `{prefix_hash}` |"
        )
    lines.extend(["", "## Selected Skills", ""])
    for case in payload["cases"]:
        lines.append(f"### {case['id']}")
        lines.append("")
        if case["selected_skills"]:
            for skill in case["selected_skills"]:
                lines.append(f"- `{skill}`")
        else:
            lines.append("- None")
        if case["matched_terms"]:
            lines.append("")
            lines.append("Matched terms:")
            for term in case["matched_terms"]:
                lines.append(f"- `{term}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _escape_table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")
```

- [ ] **Step 4: Export the renderer**

Modify `src/agentmf/__init__.py` so the import and `__all__` additions from Task 1 are active:

```python
from agentmf.benchmark import (
    SkillBenchmarkCase,
    SkillBenchmarkResult,
    create_skill_benchmark_payload,
    render_skill_benchmark_markdown,
)
```

```python
"SkillBenchmarkCase",
"SkillBenchmarkResult",
"create_skill_benchmark_payload",
"render_skill_benchmark_markdown",
```

- [ ] **Step 5: Run the renderer test to confirm green**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_skill_benchmark_markdown_contains_summary_table -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agentmf/benchmark.py src/agentmf/__init__.py tests/test_agentmf.py
git commit -m "Render skill benchmark reports"
```

## Task 4: Add `agentmf benchmark skills` CLI

**Files:**
- Modify: `src/agentmf/cli.py`
- Test: `tests/test_agentmf.py`

- [ ] **Step 1: Write the failing JSON CLI test**

Append this test near the plugin CLI tests:

```python
def test_cli_benchmark_skills_outputs_json(capsys) -> None:
    exit_code = main(
        [
            "benchmark",
            "skills",
            "--file",
            str(SUPERPOWERS_MODULE),
            "--host",
            "codex",
            "--case",
            "write an implementation plan",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["skill_benchmark_payload"]["summary"]["case_count"] == 1
    assert payload["skill_benchmark_payload"]["cases"][0]["id"] == "case-1"
    assert payload["skill_benchmark_payload"]["cases"][0]["selected_skills"]
    assert payload["diagnostics"] == []
```

- [ ] **Step 2: Run the JSON CLI test to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_cli_benchmark_skills_outputs_json -q
```

Expected: FAIL because argparse does not know the `benchmark` command.

- [ ] **Step 3: Add imports**

Modify imports at the top of `src/agentmf/cli.py`:

```python
from agentmf.benchmark import create_skill_benchmark_payload, render_skill_benchmark_markdown
```

- [ ] **Step 4: Add benchmark subparsers**

Add this parser block after the `skills` subparser block in `main(...)`:

```python
    benchmark_cmd = subparsers.add_parser("benchmark", help="benchmark AgentMakefile behavior")
    benchmark_subcommands = benchmark_cmd.add_subparsers(dest="benchmark_command", required=True)
    benchmark_skills_cmd = benchmark_subcommands.add_parser(
        "skills",
        help="benchmark skill routing and prompt prefix savings",
    )
    benchmark_skills_cmd.add_argument("--file", default="AgentMakefile")
    benchmark_skills_cmd.add_argument("--host", choices=["generic", "codex", "claude-code"], default="generic")
    benchmark_skills_cmd.add_argument("--case", action="append", dest="cases", required=True)
    benchmark_skills_cmd.add_argument("--backend", choices=["agents-fragments", "claude-fragments"], default="agents-fragments")
    benchmark_skills_cmd.add_argument("--baseline", choices=["agents-md"], default="agents-md")
    benchmark_skills_cmd.add_argument("--fail-on-mismatch", action="store_true")
    benchmark_skills_cmd.add_argument("--out")
    benchmark_skills_cmd.add_argument("--write", action="store_true")
    benchmark_skills_cmd.add_argument("--format", choices=["json", "markdown", "text"], default="markdown")
```

- [ ] **Step 5: Route the benchmark command**

Add this command dispatch after the `skills` dispatch:

```python
    if args.command == "benchmark":
        return _benchmark(args)
```

Add these helper functions near `_skills(...)`:

```python
def _benchmark(args: argparse.Namespace) -> int:
    if args.benchmark_command == "skills":
        return _benchmark_skills(args)
    return 2


def _benchmark_skills(args: argparse.Namespace) -> int:
    result = create_skill_benchmark_payload(
        path=Path(args.file),
        cases=args.cases,
        host=args.host,
        backend=args.backend,
        baseline=args.baseline,
        fail_on_mismatch=args.fail_on_mismatch,
    )
    if args.format == "json":
        output = json.dumps(
            {
                "ok": result.ok,
                "skill_benchmark_payload": result.payload,
                "diagnostics": result.diagnostics.to_list(),
            },
            indent=2,
        )
    else:
        output = render_skill_benchmark_markdown(result.payload) if result.payload else result.diagnostics.format()

    if args.write:
        if not args.out:
            print("error: --write requires --out", file=sys.stderr)
            return 2
        Path(args.out).write_text(output, encoding="utf-8")
    else:
        stream = sys.stderr if result.diagnostics.has_errors and not result.payload else sys.stdout
        print(output, file=stream, end="" if output.endswith("\n") else "\n")
    return 1 if not result.ok else 0
```

- [ ] **Step 6: Run the JSON CLI test to confirm green**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_cli_benchmark_skills_outputs_json -q
```

Expected: PASS.

- [ ] **Step 7: Write the failing Markdown write test**

Append this test near `test_cli_benchmark_skills_outputs_json`:

```python
def test_cli_benchmark_skills_writes_markdown_report(tmp_path: Path, capsys) -> None:
    report = tmp_path / "benchmark.md"

    exit_code = main(
        [
            "benchmark",
            "skills",
            "--file",
            str(SUPERPOWERS_MODULE),
            "--case",
            "write an implementation plan",
            "--format",
            "markdown",
            "--out",
            str(report),
            "--write",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == ""
    content = report.read_text(encoding="utf-8")
    assert content.startswith("# AgentMakefile Skill Benchmark\n")
    assert "write an implementation plan" in content
    assert "Selected Skills" in content
```

- [ ] **Step 8: Run the Markdown write test**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_cli_benchmark_skills_writes_markdown_report -q
```

Expected: PASS after Step 5.

- [ ] **Step 9: Run all benchmark tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py -q -k benchmark
```

Expected: all benchmark tests PASS.

- [ ] **Step 10: Commit**

```bash
git add src/agentmf/cli.py tests/test_agentmf.py
git commit -m "Add skill benchmark CLI"
```

## Task 5: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/agentmf_step_by_step_demo.md`
- Modify: `docs/spec_breakdown.md`
- Test: `tests/test_agentmf.py`

- [ ] **Step 1: Update README command examples**

Add this command block near the existing CLI examples in `README.md`:

````markdown
Benchmark request-specific skill selection and prompt-prefix savings:

```bash
agentmf benchmark skills \
  --file modules/superpowers/AgentMakefile \
  --case "write an implementation plan" \
  --case "debug failing test" \
  --host codex \
  --format markdown
```
````

If the README has a docs list, keep the existing link to `docs/agentmf_benchmark_cli_spec.md`.

- [ ] **Step 2: Update the step-by-step demo**

Add this section to `docs/agentmf_step_by_step_demo.md` after the plugin payload or skill-routing walkthrough:

````markdown
## Benchmark skill selection

Run a deterministic benchmark without calling a model:

```bash
PYTHONPATH=src python3 -m agentmf.cli benchmark skills \
  --file modules/superpowers/AgentMakefile \
  --case "write an implementation plan" \
  --case "debug failing test" \
  --host codex \
  --format markdown
```

The report shows selected targets, selected skills, stable prefix hashes, and
the token savings compared with the generated `AGENTS.md` baseline. This is the
first measurable proof that AgentMakefile can load only the skill prompt objects
needed for a request instead of injecting the whole skill catalog.
````

- [ ] **Step 3: Update the roadmap breakdown**

Add a completed item to `docs/spec_breakdown.md` under the runtime/plugin adapter section:

```markdown
### AMF-PAD-014 Benchmark CLI First Slice - Completed

- Added `agentmf benchmark skills` for deterministic skill-selection benchmark reports.
- Reused plugin payload selection traces, selected skills, stable prefix hashes, and prompt-size comparison data.
- Supported inline cases, JSON output, Markdown output, report writing, and fail-on-mismatch diagnostics for expected labels.
```

- [ ] **Step 4: Run documentation-related tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py -q -k readme
```

Expected: PASS.

- [ ] **Step 5: Run the benchmark smoke command**

Run:

```bash
PYTHONPATH=src python3 -m agentmf.cli benchmark skills \
  --file modules/superpowers/AgentMakefile \
  --case "write an implementation plan" \
  --case "debug failing test" \
  --host codex \
  --format markdown
```

Expected: exit code 0 and Markdown beginning with `# AgentMakefile Skill Benchmark`.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/agentmf_step_by_step_demo.md docs/spec_breakdown.md
git commit -m "Document skill benchmark workflow"
```

## Task 6: Final Verification

**Files:**
- No source edits unless verification exposes a failure.

- [ ] **Step 1: Run benchmark-focused tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py -q -k benchmark
```

Expected: all benchmark tests PASS.

- [ ] **Step 2: Run the full test suite**

Run:

```bash
PYTHONPATH=src python3 -m pytest -q
```

Expected: all tests PASS.

- [ ] **Step 3: Run compile smoke verification**

Run:

```bash
python3 -m compileall -q src
```

Expected: exit code 0 with no output.

- [ ] **Step 4: Validate the root AgentMakefile**

Run:

```bash
PYTHONPATH=src python3 -m agentmf.cli validate --file AgentMakefile
```

Expected: `AgentMakefile is valid.`

- [ ] **Step 5: Check whitespace**

Run:

```bash
git diff --check
```

Expected: exit code 0 with no output.

- [ ] **Step 6: Commit any verification fixes**

If verification required code or docs fixes, commit them:

```bash
git add src tests README.md docs
git commit -m "Stabilize skill benchmark CLI"
```

If no files changed during verification, skip this commit.

## Follow-On Benchmark Slices

These are intentionally outside the first implementation plan and should each get a short TDD plan before coding:

- Add `--cases-file` with JSON/YAML parsing, unknown-key errors, and expected labels from files.
- Add `--baseline-file` for comparing against existing hand-authored `AGENTS.md`, `CLAUDE.md`, or `skills/index.md`.
- Add `--baseline-skills-dir` and `all-skills` to compare against loading every discovered `SKILL.md`.
- Add `claude-md` and `skills-index` baselines.
- Add benchmark fixtures under `benchmarks/` after the case file parser exists.
- Add benchmark cases for guidance-index modules generated from `AGENTS.md`,
  `CLAUDE.md`, standalone `SKILL.md`, and `skill-dir` inputs.

## Self-Review

- Spec coverage: this plan covers the first implementation slice listed in `docs/agentmf_benchmark_cli_spec.md`, including command shape, inline cases, `agents-md` baseline, JSON/Markdown output, mismatch diagnostics, and report writing.
- Placeholder scan: the plan contains concrete file paths, function names, diagnostic codes, test bodies, commands, and expected outcomes.
- Type consistency: `SkillBenchmarkCase`, `SkillBenchmarkResult`, `create_skill_benchmark_payload`, and `render_skill_benchmark_markdown` are introduced before they are used by CLI and tests.
