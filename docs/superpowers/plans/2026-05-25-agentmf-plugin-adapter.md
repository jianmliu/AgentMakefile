# AgentMakefile Plugin Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first plugin-first AgentMakefile integration path by emitting a structured prompt payload for existing coding-agent hosts.

**Architecture:** Add a small `agentmf.plugin` module that wraps `create_run_plan(..., dry_run=True)`, separates stable prefix from volatile context, and returns host-oriented JSON. Expose it through `agentmf plugin payload` while keeping provider calls and tool execution out of scope.

**Tech Stack:** Python standard library, existing `agentmf.runtime`, existing argparse CLI, pytest.

---

## File Structure

- Create `src/agentmf/plugin.py`: plugin payload builder, volatile context collection, stable prefix hashing, host instruction profiles.
- Modify `src/agentmf/__init__.py`: export `PluginPayloadResult` and `create_plugin_payload`.
- Modify `src/agentmf/cli.py`: add `agentmf plugin payload`.
- Modify `tests/test_agentmf.py`: add focused tests for the builder and CLI.
- Modify `README.md`: add a short plugin command example after runtime dry-run examples.
- Modify `docs/spec_breakdown.md`: mark implementation tasks as completed as they land.

## Task 1: Add Plugin Payload Builder Skeleton

**Files:**
- Create: `src/agentmf/plugin.py`
- Modify: `src/agentmf/__init__.py`
- Test: `tests/test_agentmf.py`

- [x] **Step 1: Write the failing builder test**

Append this test near the runtime tests in `tests/test_agentmf.py`:

```python
def test_plugin_payload_wraps_runtime_prompt_prefix(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    match:
      user_intent:
        - review code
    steps:
      - action: review_code
""",
    )

    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=path,
        host="codex",
        request="please review code",
        backend="agents-fragments",
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["version"] == 1
    assert result.payload["host"] == "codex"
    assert result.payload["mode"] == "prompt_payload"
    assert result.payload["request"] == "please review code"
    assert result.payload["selected_targets"] == ["review.task"]
    assert result.payload["stable_prefix"]["backend"] == "agents-fragments"
    assert result.payload["stable_prefix"]["content"].startswith(
        "# review.task - Generic Coding Agents Target Fragment"
    )
    assert result.payload["volatile_context"] == {
        "plan": None,
        "git_status": None,
        "git_diff": None,
        "context_files": [],
    }
    assert result.payload["host_instructions"]["injection"] == (
        "prepend_stable_prefix_append_volatile_context"
    )
    assert result.payload["trace"]["target_closure"] == ["review.task"]
```

- [x] **Step 2: Run the test to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_plugin_payload_wraps_runtime_prompt_prefix -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmf.plugin'`.

- [x] **Step 3: Create the minimal plugin module**

Create `src/agentmf/plugin.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.runtime import create_run_plan


HOSTS = {"generic", "codex", "claude-code", "cursor", "opencode"}


@dataclass
class PluginPayloadResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_plugin_payload(
    path: Union[Path, str],
    host: str = "generic",
    request: Optional[str] = None,
    target_names: Optional[List[str]] = None,
    backend: str = "agents-fragments",
) -> PluginPayloadResult:
    diagnostics = Diagnostics()
    if host not in HOSTS:
        diagnostics.error(
            "AMF130",
            f"unsupported plugin host: {host}",
            "plugin.host",
            "use one of: claude-code, codex, cursor, generic, opencode",
        )
        return PluginPayloadResult(diagnostics)

    run_result = create_run_plan(
        path=path,
        request=request,
        target_names=target_names,
        backend=backend,
        dry_run=True,
    )
    diagnostics.extend(run_result.diagnostics.items)
    if diagnostics.has_errors:
        return PluginPayloadResult(diagnostics)

    prefix = run_result.plan["prompt_prefix"]
    content = prefix["content"]
    payload = {
        "version": 1,
        "host": host,
        "mode": "prompt_payload",
        "request": request,
        "selected_targets": list(run_result.plan["link_plan"]["selected_targets"]),
        "stable_prefix": {
            "backend": backend,
            "content": content,
            "chars": len(content),
            "approx_tokens": (len(content) + 3) // 4,
            "hash": f"sha256:{sha256(content.encode('utf-8')).hexdigest()}",
        },
        "volatile_context": {
            "plan": None,
            "git_status": None,
            "git_diff": None,
            "context_files": [],
        },
        "host_instructions": {
            "injection": "prepend_stable_prefix_append_volatile_context",
            "preferred_cache_boundary": "after_stable_prefix",
            "permissions_mode": "host_enforced_when_supported",
        },
        "trace": {
            "target_closure": list(run_result.plan["link_plan"]["target_closure"]),
            "linked_fragments": [
                fragment["path"] for fragment in prefix["fragments"]
            ],
            "comparison": prefix["comparison"],
        },
        "diagnostics": diagnostics.to_list(),
    }
    return PluginPayloadResult(diagnostics, payload)
```

- [x] **Step 4: Export the plugin API**

Modify `src/agentmf/__init__.py`:

```python
from agentmf.plugin import PluginPayloadResult, create_plugin_payload
```

Add the names to `__all__`:

```python
"PluginPayloadResult",
"create_plugin_payload",
```

- [x] **Step 5: Run the test to confirm green**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_plugin_payload_wraps_runtime_prompt_prefix -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agentmf/plugin.py src/agentmf/__init__.py tests/test_agentmf.py
git commit -m "Add plugin payload builder"
```

## Task 2: Add Plan Input and Stable Prefix Hash Invariance

**Files:**
- Modify: `src/agentmf/plugin.py`
- Test: `tests/test_agentmf.py`

- [x] **Step 1: Write the failing plan context test**

Append:

```python
def test_plugin_payload_keeps_plan_out_of_stable_prefix_hash(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.change:
    match:
      user_intent:
        - implement feature
    steps:
      - action: edit_code
""",
    )
    plan_a = tmp_path / "plan-a.md"
    plan_b = tmp_path / "plan-b.md"
    plan_a.write_text("# Plan A\n\n- Add tests first\n", encoding="utf-8")
    plan_b.write_text("# Plan B\n\n- Add docs first\n", encoding="utf-8")

    from agentmf.plugin import create_plugin_payload

    result_a = create_plugin_payload(
        path=path,
        host="codex",
        request="implement feature",
        plan_path=plan_a,
    )
    result_b = create_plugin_payload(
        path=path,
        host="codex",
        request="implement feature",
        plan_path=plan_b,
    )

    assert result_a.ok, result_a.diagnostics.format()
    assert result_b.ok, result_b.diagnostics.format()
    assert result_a.payload["stable_prefix"]["hash"] == result_b.payload["stable_prefix"]["hash"]
    assert result_a.payload["volatile_context"]["plan"] == {
        "path": str(plan_a),
        "content": "# Plan A\n\n- Add tests first\n",
    }
    assert result_b.payload["volatile_context"]["plan"] == {
        "path": str(plan_b),
        "content": "# Plan B\n\n- Add docs first\n",
    }
```

- [x] **Step 2: Run the test to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_plugin_payload_keeps_plan_out_of_stable_prefix_hash -q
```

Expected: FAIL with `TypeError` because `plan_path` is not accepted.

- [x] **Step 3: Add plan loading**

Modify the signature in `src/agentmf/plugin.py`:

```python
def create_plugin_payload(
    path: Union[Path, str],
    host: str = "generic",
    request: Optional[str] = None,
    target_names: Optional[List[str]] = None,
    backend: str = "agents-fragments",
    plan_path: Optional[Union[Path, str]] = None,
) -> PluginPayloadResult:
```

Add this helper:

```python
def _read_plan(plan_path: Optional[Union[Path, str]], diagnostics: Diagnostics) -> Optional[Dict[str, str]]:
    if plan_path is None:
        return None
    path = Path(plan_path)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error(
            "AMF131",
            f"could not read plan file: {path}",
            "plugin.plan",
            str(exc),
        )
        return None
    return {"path": str(path), "content": content}
```

Call it after host validation:

```python
plan = _read_plan(plan_path, diagnostics)
if diagnostics.has_errors:
    return PluginPayloadResult(diagnostics)
```

Set volatile context:

```python
"plan": plan,
```

- [x] **Step 4: Run both plugin builder tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_plugin_payload_wraps_runtime_prompt_prefix tests/test_agentmf.py::test_plugin_payload_keeps_plan_out_of_stable_prefix_hash -q
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/agentmf/plugin.py tests/test_agentmf.py
git commit -m "Add plugin plan context"
```

## Task 3: Add `agentmf plugin payload`

**Files:**
- Modify: `src/agentmf/cli.py`
- Test: `tests/test_agentmf.py`

- [x] **Step 1: Write the failing CLI test**

Append:

```python
def test_cli_plugin_payload_outputs_json(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    match:
      user_intent:
        - review code
    steps:
      - action: review_code
""",
    )

    exit_code = main(
        [
            "plugin",
            "payload",
            "--file",
            str(path),
            "--host",
            "codex",
            "--request",
            "please review code",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["plugin_payload"]["host"] == "codex"
    assert payload["plugin_payload"]["selected_targets"] == ["review.task"]
    assert payload["plugin_payload"]["stable_prefix"]["content"].startswith(
        "# review.task - Generic Coding Agents Target Fragment"
    )
```

- [x] **Step 2: Run the test to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_cli_plugin_payload_outputs_json -q
```

Expected: FAIL because the `plugin` command is not defined.

- [x] **Step 3: Add nested plugin command parsing**

In `src/agentmf/cli.py`, import:

```python
from agentmf.plugin import create_plugin_payload
```

Add parser setup after `run_cmd`:

```python
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
    plugin_payload_cmd.add_argument("--format", choices=["text", "json"], default="json")
```

Dispatch:

```python
    if args.command == "plugin":
        return _plugin(args)
```

Add:

```python
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
```

- [x] **Step 4: Run the CLI test**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_cli_plugin_payload_outputs_json -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentmf/cli.py tests/test_agentmf.py
git commit -m "Add plugin payload command"
```

## Task 4: Add Git and Context File Collection

**Files:**
- Modify: `src/agentmf/plugin.py`
- Modify: `src/agentmf/cli.py`
- Test: `tests/test_agentmf.py`

- [x] **Step 1: Write failing tests for context flags**

Append:

```python
def test_plugin_payload_reads_context_file(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  docs.task:
    steps:
      - action: inspect_docs
""",
    )
    context = tmp_path / "notes.md"
    context.write_text("Important context\n", encoding="utf-8")

    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=path,
        host="generic",
        target_names=["docs.task"],
        context_files=[context],
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["volatile_context"]["context_files"] == [
        {"path": str(context), "content": "Important context\n"}
    ]
```

Append:

```python
def test_plugin_payload_rejects_secret_context_file(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  docs.task:
    steps:
      - action: inspect_docs
""",
    )
    secret = tmp_path / ".env"
    secret.write_text("TOKEN=secret\n", encoding="utf-8")

    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=path,
        host="generic",
        target_names=["docs.task"],
        context_files=[secret],
    )

    assert not result.ok
    assert result.diagnostics.items[0].code == "AMF132"
```

- [x] **Step 2: Run the tests to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_plugin_payload_reads_context_file tests/test_agentmf.py::test_plugin_payload_rejects_secret_context_file -q
```

Expected: FAIL because `context_files` is not accepted.

- [x] **Step 3: Add context file support**

Modify `create_plugin_payload` signature:

```python
    context_files: Optional[List[Union[Path, str]]] = None,
```

Add helpers:

```python
SECRET_NAMES = {".env", ".npmrc", ".pypirc"}


def _read_context_files(
    context_files: Optional[List[Union[Path, str]]],
    diagnostics: Diagnostics,
) -> List[Dict[str, str]]:
    records = []
    for raw_path in context_files or []:
        path = Path(raw_path)
        if path.name in SECRET_NAMES or "secret" in path.name.lower():
            diagnostics.error(
                "AMF132",
                f"refusing to read secret-looking context file: {path}",
                "plugin.context",
                "pass only non-secret context files",
            )
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            diagnostics.error(
                "AMF133",
                f"could not read context file: {path}",
                "plugin.context",
                str(exc),
            )
            continue
        records.append({"path": str(path), "content": content})
    return records
```

Call it before building the payload:

```python
context_file_records = _read_context_files(context_files, diagnostics)
if diagnostics.has_errors:
    return PluginPayloadResult(diagnostics)
```

Set:

```python
"context_files": context_file_records,
```

- [x] **Step 4: Add CLI context file option**

In `src/agentmf/cli.py`, add:

```python
plugin_payload_cmd.add_argument("--context-file", action="append", dest="context_files")
```

Pass:

```python
context_files=[Path(path) for path in args.context_files or []],
```

- [x] **Step 5: Run context tests and CLI test**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_plugin_payload_reads_context_file tests/test_agentmf.py::test_plugin_payload_rejects_secret_context_file tests/test_agentmf.py::test_cli_plugin_payload_outputs_json -q
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/agentmf/plugin.py src/agentmf/cli.py tests/test_agentmf.py
git commit -m "Add plugin context files"
```

## Task 5: Add Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/spec_breakdown.md`

- [x] **Step 1: Update README command examples**

Add this command after the current `agentmf run` example:

```bash
agentmf plugin payload --host codex --request "review code" --format json
```

Add this sentence near the runtime paragraph:

```markdown
The plugin payload command is the preferred first integration path for existing agent CLIs: it returns stable prefix content, volatile context, host instructions, and trace data without owning the model or tool loop.
```

- [x] **Step 2: Update roadmap completion status**

In `docs/spec_breakdown.md`, mark the implemented plugin tasks as completed:

```markdown
- AMF-PAD-002 plugin payload builder.
- AMF-PAD-003 `agentmf plugin payload` command.
- AMF-PAD-004 plan and context inputs.
```

Set the next item to:

```markdown
1. AMF-PAD-005 host profiles.
2. AMF-M4-003 guard evaluation dry-run.
```

- [x] **Step 3: Run full verification**

Run:

```bash
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall -q src
PYTHONPATH=src python3 -m agentmf.cli validate --file AgentMakefile
PYTHONPATH=src python3 -m agentmf.cli plugin payload --host codex --request "review code" --format json
git diff --check
```

Expected:

```text
pytest reports all tests passed
compileall exits 0
validate prints "AgentMakefile is valid."
plugin payload JSON has "ok": true
git diff --check exits 0
```

- [ ] **Step 4: Commit**

```bash
git add README.md docs/spec_breakdown.md
git commit -m "Document plugin payload command"
```

## Task 6: Add Host Profiles

**Files:**
- Modify: `src/agentmf/plugin.py`
- Modify: `tests/test_agentmf.py`
- Modify: `docs/agentmf_plugin_adapter_spec.md`
- Modify: `docs/spec_breakdown.md`

- [x] **Step 1: Write the failing host profile test**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_plugin_payload_uses_host_specific_instruction_profiles -q
```

Expected: FAIL with `KeyError: 'profile'`.

- [x] **Step 2: Add host profile mapping**

Add `HOST_PROFILES` in `src/agentmf/plugin.py` for `generic`, `codex`,
`claude-code`, `cursor`, and `opencode`.

- [x] **Step 3: Use host profile data in payloads**

Set `host_instructions` from the selected profile while preserving common
`injection` and `preferred_cache_boundary` fields.

- [x] **Step 4: Update docs and roadmap**

Document host profile fields and mark AMF-PAD-005 implemented.

- [x] **Step 5: Run targeted host profile tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_plugin_payload_uses_host_specific_instruction_profiles -q
```

Expected: PASS.

## Task 7: Add Example Adapter Docs

**Files:**
- Create: `docs/agentmf_plugin_adapter_examples.md`
- Modify: `README.md`
- Modify: `docs/agentmf_plugin_adapter_spec.md`
- Modify: `docs/spec_breakdown.md`

- [x] **Step 1: Write example adapter documentation**

Create `docs/agentmf_plugin_adapter_examples.md` with command-adapter,
Python-wrapper, plan-aware, context-file, host-specific, error-handling, and
security-boundary examples.

- [x] **Step 2: Link examples from top-level docs**

Add links from `README.md` and `docs/agentmf_plugin_adapter_spec.md`.

- [x] **Step 3: Mark AMF-PAD-006 implemented**

Update `docs/spec_breakdown.md` and set the next runtime task back to
AMF-M4-003.

- [x] **Step 4: Verify documentation**

Run placeholder, diff, validation, and test checks before claiming completion.

## Self-Review Checklist

- Spec coverage: implements generic plugin payload protocol, stable prefix separation, plan-as-volatile-context, host instructions, trace, and diagnostics.
- Placeholder scan: the plan contains no placeholder implementation steps.
- Type consistency: `PluginPayloadResult`, `create_plugin_payload`, `plugin_payload`, `stable_prefix`, `volatile_context`, `host_instructions`, and `trace` names are consistent across tasks.
- Scope: provider calls, streaming, tool loop, and host-native adapters remain out of this first implementation plan.
