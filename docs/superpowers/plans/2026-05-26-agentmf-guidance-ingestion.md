# AgentMakefile Guidance Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize reverse import from `SKILL.md` directories to a multi-source guidance ingestion path that can read `SKILL.md`, `AGENTS.md`, and `CLAUDE.md` into a generated AgentMakefile routing module.

**Architecture:** Add a new `agentmf.guidance_scanner` facade that dispatches source readers by type and reuses the existing `skill_scanner` for `skill-dir` inputs. Keep `agentmf skills scan` as a compatibility wrapper, add `agentmf guidance scan` as the general command, and extend `agentmf plugin install` so plugin bootstrap can import either skill roots or broader guidance sources.

**Tech Stack:** Python standard library, PyYAML, existing `agentmf.skill_scanner`, existing argparse CLI, pytest.

---

## File Structure

- Create `src/agentmf/guidance_scanner.py`: source type detection, guidance unit model, Markdown guidance reader, generated AgentMakefile renderer.
- Modify `src/agentmf/skill_scanner.py`: keep public compatibility functions and delegate shared rendering where useful.
- Modify `src/agentmf/plugin_install.py`: accept generalized guidance sources while preserving `--skills-dir`.
- Modify `src/agentmf/cli.py`: add `agentmf guidance scan` and `plugin install --source`.
- Modify `src/agentmf/__init__.py`: export guidance scanner result types if needed by tests.
- Modify `tests/test_agentmf.py`: add TDD coverage for `skill-dir`, standalone `SKILL.md`, `AGENTS.md`, `CLAUDE.md`, CLI scan, and plugin install source input.
- Modify `README.md`, `docs/spec_breakdown.md`, and `docs/agentmf_step_by_step_demo.md`: document guidance ingestion as the generalized reverse-import path.

## Task 1: Add Guidance Scanner Facade for Existing Skill Directories

**Files:**
- Create: `src/agentmf/guidance_scanner.py`
- Test: `tests/test_agentmf.py`

- [ ] **Step 1: Write the failing compatibility test**

Append this test near the existing skill scanner tests in `tests/test_agentmf.py`:

```python
def test_guidance_scan_skill_dir_matches_existing_skill_scan(tmp_path: Path) -> None:
    skill_root = tmp_path / "skills"
    skill = skill_root / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        """\
---
name: review
description: Use when reviewing code.
---

# Review

## When to Use

- review code
""",
        encoding="utf-8",
    )

    from agentmf.guidance_scanner import render_agentmakefile_from_guidance_sources

    content = render_agentmakefile_from_guidance_sources(
        [skill_root],
        source_type="skill-dir",
        namespace="imported",
        package_name="imported-guidance",
    )
    data = yaml.safe_load(content)

    assert data["metadata"]["module_type"] == "guidance-index"
    assert data["skills"]["review"]["namespace"] == "imported"
    assert data["skills"]["review"]["implementation"]["source"] == str(skill)
    assert data["targets"]["skill.review"]["skills"] == ["imported:review"]
```

- [ ] **Step 2: Run the test to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_guidance_scan_skill_dir_matches_existing_skill_scan -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agentmf.guidance_scanner'`.

- [ ] **Step 3: Create the facade**

Create `src/agentmf/guidance_scanner.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import yaml

from agentmf.skill_scanner import scan_skill_dirs


SUPPORTED_SOURCE_TYPES = {"auto", "skill-dir", "skill-md", "agents-md", "claude-md"}


def render_agentmakefile_from_guidance_sources(
    sources: Sequence[Path],
    *,
    source_type: str = "auto",
    namespace: Optional[str] = None,
    package_name: str = "imported-guidance",
    package_description: Optional[str] = None,
    bootstrap_skill: Optional[str] = None,
) -> str:
    data = build_agentmakefile_data_from_guidance_sources(
        sources,
        source_type=source_type,
        namespace=namespace,
        package_name=package_name,
        package_description=package_description,
        bootstrap_skill=bootstrap_skill,
    )
    return yaml.safe_dump(data, sort_keys=False)


def build_agentmakefile_data_from_guidance_sources(
    sources: Sequence[Path],
    *,
    source_type: str = "auto",
    namespace: Optional[str] = None,
    package_name: str,
    package_description: Optional[str] = None,
    bootstrap_skill: Optional[str] = None,
) -> Dict[str, Any]:
    if source_type not in SUPPORTED_SOURCE_TYPES:
        raise ValueError(f"unsupported guidance source type: {source_type}")
    resolved_type = _resolve_source_type(sources, source_type)
    if resolved_type == "skill-dir":
        from agentmf.skill_scanner import build_agentmakefile_data

        data = build_agentmakefile_data(
            scan_skill_dirs(sources, namespace=namespace),
            package_name=package_name,
            package_description=package_description,
            bootstrap_skill=bootstrap_skill,
        )
        data["metadata"]["module_type"] = "guidance-index"
        return data
    raise ValueError(f"unsupported guidance source type in first task: {resolved_type}")


def _resolve_source_type(sources: Sequence[Path], source_type: str) -> str:
    if source_type != "auto":
        return source_type
    if all(Path(source).is_dir() for source in sources):
        return "skill-dir"
    raise ValueError("could not infer guidance source type")
```

- [ ] **Step 4: Run the compatibility test to confirm green**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_guidance_scan_skill_dir_matches_existing_skill_scan -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentmf/guidance_scanner.py tests/test_agentmf.py
git commit -m "Add guidance scanner facade"
```

## Task 2: Import Standalone `SKILL.md`, `AGENTS.md`, and `CLAUDE.md`

**Files:**
- Modify: `src/agentmf/guidance_scanner.py`
- Test: `tests/test_agentmf.py`

- [ ] **Step 1: Write failing Markdown import tests**

Append these tests near the guidance scanner compatibility test:

```python
def test_guidance_scan_imports_agents_md_as_guidance_target(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        """\
# Project Agents

## Review

Use careful code review before merging.
""",
        encoding="utf-8",
    )

    from agentmf.guidance_scanner import render_agentmakefile_from_guidance_sources

    content = render_agentmakefile_from_guidance_sources(
        [agents],
        source_type="agents-md",
        package_name="project-guidance",
    )
    data = yaml.safe_load(content)

    target = data["targets"]["guidance.agents"]
    assert data["metadata"]["module_type"] == "guidance-index"
    assert target["implementation"] == {"source": str(agents), "source_type": "agents-md"}
    assert "Project Agents" in target["match"]["user_intent"]
    assert "Review" in target["match"]["user_intent"]


def test_guidance_scan_imports_claude_md_as_guidance_target(tmp_path: Path) -> None:
    claude = tmp_path / "CLAUDE.md"
    claude.write_text("# Claude Rules\n\n## Test\n\nRun tests before completion.\n", encoding="utf-8")

    from agentmf.guidance_scanner import render_agentmakefile_from_guidance_sources

    content = render_agentmakefile_from_guidance_sources(
        [claude],
        source_type="claude-md",
        package_name="project-guidance",
    )
    data = yaml.safe_load(content)

    assert data["targets"]["guidance.claude"]["implementation"]["source_type"] == "claude-md"
    assert "Test" in data["targets"]["guidance.claude"]["match"]["user_intent"]


def test_guidance_scan_imports_single_skill_md(tmp_path: Path) -> None:
    skill = tmp_path / "SKILL.md"
    skill.write_text(
        """\
---
name: local-review
description: Use when reviewing local changes.
---

## When to Use

- review local changes
""",
        encoding="utf-8",
    )

    from agentmf.guidance_scanner import render_agentmakefile_from_guidance_sources

    content = render_agentmakefile_from_guidance_sources(
        [skill],
        source_type="skill-md",
        namespace="local",
        package_name="project-guidance",
    )
    data = yaml.safe_load(content)

    assert data["skills"]["local-review"]["namespace"] == "local"
    assert data["targets"]["skill.local-review"]["skills"] == ["local:local-review"]
```

- [ ] **Step 2: Run tests to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py -q -k "guidance_scan_imports"
```

Expected: FAIL because `skill-md`, `agents-md`, and `claude-md` are not implemented.

- [ ] **Step 3: Add source readers**

Extend `src/agentmf/guidance_scanner.py` with Markdown readers. The implementation should:

- use existing `skill_scanner.scan_skill_dirs` for `skill-dir`
- create a temporary synthetic skill directory for `skill-md`, or share `_read_skill` after making it public as `read_skill_file`
- import `AGENTS.md` and `CLAUDE.md` as `guidance.<stem>` targets
- infer terms from Markdown headings with `^#+\s+(.+)$`
- store `implementation.source` and `implementation.source_type`

The target shape for `AGENTS.md` must be:

```python
{
    "phony": True,
    "priority": 60,
    "description": "Imported AGENTS.md guidance.",
    "match": {"user_intent": terms},
    "steps": [{"action": "read_imported_guidance"}],
    "implementation": {"source": str(path), "source_type": "agents-md"},
}
```

- [ ] **Step 4: Run tests to confirm green**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py -q -k "guidance_scan_imports"
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentmf/guidance_scanner.py src/agentmf/skill_scanner.py tests/test_agentmf.py
git commit -m "Import markdown guidance sources"
```

## Task 3: Add `agentmf guidance scan`

**Files:**
- Modify: `src/agentmf/cli.py`
- Test: `tests/test_agentmf.py`

- [ ] **Step 1: Write failing CLI test**

Append this test near scanner CLI tests:

```python
def test_cli_guidance_scan_imports_agents_md(tmp_path: Path, capsys) -> None:
    agents = tmp_path / "AGENTS.md"
    output = tmp_path / "AgentMakefile"
    agents.write_text("# Project Agents\n\n## Review\n\nReview code carefully.\n", encoding="utf-8")

    exit_code = main(
        [
            "guidance",
            "scan",
            "--source",
            str(agents),
            "--source-type",
            "agents-md",
            "--package-name",
            "project-guidance",
            "--out",
            str(output),
            "--write",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Wrote AgentMakefile" in captured.out
    assert output.exists()
    data = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert data["targets"]["guidance.agents"]["implementation"]["source"] == str(agents)
```

- [ ] **Step 2: Run the test to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_cli_guidance_scan_imports_agents_md -q
```

Expected: FAIL because argparse does not know the `guidance` command.

- [ ] **Step 3: Add CLI parser and handler**

Add a top-level `guidance` parser in `src/agentmf/cli.py`:

```python
guidance_cmd = subparsers.add_parser("guidance", help="guidance ingestion commands")
guidance_subcommands = guidance_cmd.add_subparsers(dest="guidance_command", required=True)
guidance_scan_cmd = guidance_subcommands.add_parser("scan", help="scan guidance files into an AgentMakefile")
guidance_scan_cmd.add_argument("--source", action="append", dest="sources", required=True)
guidance_scan_cmd.add_argument("--source-type", default="auto")
guidance_scan_cmd.add_argument("--namespace")
guidance_scan_cmd.add_argument("--package-name", default="imported-guidance")
guidance_scan_cmd.add_argument("--package-description")
guidance_scan_cmd.add_argument("--bootstrap-skill")
guidance_scan_cmd.add_argument("--out")
guidance_scan_cmd.add_argument("--write", action="store_true")
guidance_scan_cmd.add_argument("--format", choices=["text", "json"], default="text")
```

The handler should call `render_agentmakefile_from_guidance_sources(...)`, write
only when `--write` is set, print the generated content otherwise, and return
nonzero on `ValueError`.

- [ ] **Step 4: Run the CLI test to confirm green**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_cli_guidance_scan_imports_agents_md -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agentmf/cli.py tests/test_agentmf.py
git commit -m "Add guidance scan CLI"
```

## Task 4: Extend Plugin Install to Use Guidance Sources

**Files:**
- Modify: `src/agentmf/plugin_install.py`
- Modify: `src/agentmf/cli.py`
- Test: `tests/test_agentmf.py`

- [ ] **Step 1: Write failing plugin install source test**

Append this test near plugin install tests:

```python
def test_plugin_install_accepts_guidance_source_agents_md(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    out = tmp_path / "AgentMakefile"
    agents.write_text("# Project Agents\n\n## Review\n\nReview code carefully.\n", encoding="utf-8")

    from agentmf.plugin_install import create_plugin_install_payload

    result = create_plugin_install_payload(
        guidance_sources=[agents],
        source_type="agents-md",
        host="codex",
        package_name="project-guidance",
        out_path=out,
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    assert out.exists()
    assert result.payload["agentmakefile"]["path"] == str(out)
    assert "plugin payload" in result.payload["model_instructions"]
```

- [ ] **Step 2: Run the test to confirm red**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_plugin_install_accepts_guidance_source_agents_md -q
```

Expected: FAIL because `create_plugin_install_payload` does not accept `guidance_sources`.

- [ ] **Step 3: Update plugin install builder**

Modify `create_plugin_install_payload(...)` so it accepts:

```python
guidance_sources: Optional[Sequence[Union[Path, str]]] = None,
source_type: str = "auto",
```

Behavior:

- if `guidance_sources` is provided, call `render_agentmakefile_from_guidance_sources`
- else preserve the current `skill_dirs` path
- if both are provided, combine them by treating `skill_dirs` as `skill-dir` sources in a later slice; for this task, return diagnostic `AMF146` telling callers to use one import style at a time

- [ ] **Step 4: Add CLI options**

Extend `agentmf plugin install` parser:

```python
plugin_install_cmd.add_argument("--source", action="append", dest="sources")
plugin_install_cmd.add_argument("--source-type", default="auto")
```

Make `--skills-dir` optional if `--source` is present. The handler should pass
`guidance_sources=[Path(path) for path in args.sources or []] or None`.

- [ ] **Step 5: Run plugin install source test**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_plugin_install_accepts_guidance_source_agents_md -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agentmf/plugin_install.py src/agentmf/cli.py tests/test_agentmf.py
git commit -m "Allow plugin install from guidance sources"
```

## Task 5: Docs and Final Verification

**Files:**
- Modify: `README.md`
- Modify: `docs/spec_breakdown.md`
- Modify: `docs/agentmf_step_by_step_demo.md`

- [ ] **Step 1: Update docs**

Document these commands:

```bash
agentmf guidance scan --source AGENTS.md --source-type agents-md --out .agentmf/imported/AgentMakefile --write
agentmf guidance scan --source CLAUDE.md --source-type claude-md --out .agentmf/imported/AgentMakefile --write
agentmf plugin install --source AGENTS.md --source-type agents-md --host codex --out .agentmf/plugin/AgentMakefile --write --format json
```

- [ ] **Step 2: Run targeted tests**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py -q -k "guidance_scan or plugin_install"
```

Expected: all selected tests PASS.

- [ ] **Step 3: Run full verification**

Run:

```bash
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall -q src
PYTHONPATH=src python3 -m agentmf.cli validate --file AgentMakefile
git diff --check
```

Expected: tests pass, compileall exits 0, validation prints `AgentMakefile is valid.`, and `git diff --check` exits 0.

- [ ] **Step 4: Commit**

```bash
git add src tests README.md docs
git commit -m "Add multi-source guidance ingestion"
```

## Self-Review

- Spec coverage: this plan implements the first slice from `docs/agentmf_guidance_ingestion_spec.md`: `skill-dir`, `skill-md`, `agents-md`, `claude-md`, `agentmf guidance scan`, and plugin install source support.
- Compatibility: existing `agentmf skills scan` and `agentmf plugin install --skills-dir` remain valid.
- Boundary: section-level splitting, `skills/index.md`, Cursor rules, and source hashing are deferred to future slices.
