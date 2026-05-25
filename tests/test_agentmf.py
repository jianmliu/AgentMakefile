from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from agentmf.compiler import BEGIN_MARKER, compile_agentmakefile
from agentmf.cli import main
from agentmf.ir import normalize
from agentmf.loader import load_source, load_source_with_diagnostics
from agentmf.diagnostics import Diagnostics


FIXTURE_DIR = Path(__file__).parent / "fixtures"
MODULE_DIR = Path(__file__).parents[1] / "modules"
DEMO_DIR = Path(__file__).parents[1] / "demos"
KARPATHY_FIXTURE = FIXTURE_DIR / "karpathy" / "AgentMakefile"
SUPERPOWERS_FIXTURE = FIXTURE_DIR / "superpowers_minimal" / "AgentMakefile"
OH_MY_OPENAGENT_FIXTURE = FIXTURE_DIR / "oh_my_openagent" / "AgentMakefile"
UNKNOWN_REPO_SECURITY_FIXTURE = FIXTURE_DIR / "unknown_repo_security" / "AgentMakefile"
KARPATHY_DEMO = DEMO_DIR / "karpathy" / "AgentMakefile"
SUPERPOWERS_DEMO = DEMO_DIR / "superpowers" / "AgentMakefile"
OH_MY_OPENAGENT_DEMO = DEMO_DIR / "oh-my-openagent" / "AgentMakefile"
KARPATHY_MODULE = MODULE_DIR / "karpathy" / "AgentMakefile"
SUPERPOWERS_MODULE = MODULE_DIR / "superpowers" / "AgentMakefile"
OH_MY_OPENAGENT_MODULE = MODULE_DIR / "oh-my-openagent" / "AgentMakefile"
SUPERPOWERS_SKILLS = {
    "brainstorming",
    "dispatching-parallel-agents",
    "executing-plans",
    "finishing-a-development-branch",
    "receiving-code-review",
    "requesting-code-review",
    "subagent-driven-development",
    "systematic-debugging",
    "test-driven-development",
    "using-git-worktrees",
    "using-superpowers",
    "verification-before-completion",
    "writing-plans",
    "writing-skills",
}

SIMPLE_AGENTMAKEFILE = """\
version: "0.1"

metadata:
  name: superpowers-methodology
  description: A minimal standalone AgentMakefile used by temp-file tests.

compile:
  targets:
    - claude-md
    - agents-md
    - cursor-rule

artifacts:
  cursor-rule:
    path: .cursor/rules/agentmakefile-generated.mdc
    frontmatter:
      description: Superpowers methodology bootstrap rules.
      alwaysApply: true

policies:
  always_use_relevant_skill:
    description: Before acting, identify whether a specialized skill applies and use it.
    guards:
      - inspect_task_for_skill_match

skills:
  systematic-debugging:
    namespace: superpowers
    description: Debug methodically.
    steps:
      - reproduce_failure

targets:
  code.task:
    phony: true
    priority: 70
    match:
      user_intent:
        - write code
        - fix bug
    policies:
      - always_use_relevant_skill
    skills:
      - superpowers:systematic-debugging
    steps:
      - action: inspect_relevant_context
      - action: verify_or_explain_gap
    output_format:
      - verification_result

permissions:
  bash:
    "git status": allow
    "npm install*": ask
"""


def write_agentmakefile(tmp_path: Path, content: Optional[str] = None, name: str = "AgentMakefile") -> Path:
    path = tmp_path / name
    if content is None:
        content = SIMPLE_AGENTMAKEFILE
    path.write_text(content)
    return path


def test_validate_valid_files() -> None:
    for path in [
        KARPATHY_MODULE,
        SUPERPOWERS_MODULE,
        OH_MY_OPENAGENT_MODULE,
        KARPATHY_FIXTURE,
        SUPERPOWERS_FIXTURE,
        OH_MY_OPENAGENT_FIXTURE,
        UNKNOWN_REPO_SECURITY_FIXTURE,
        KARPATHY_DEMO,
        SUPERPOWERS_DEMO,
        OH_MY_OPENAGENT_DEMO,
    ]:
        source, diagnostics = load_source_with_diagnostics(path)

        assert source is not None, path
        assert not diagnostics.has_errors, diagnostics.format()


def test_superpowers_module_covers_installed_superpowers_skills() -> None:
    source = load_source(SUPERPOWERS_MODULE)

    assert set(source.skills) == SUPERPOWERS_SKILLS
    assert {skill.namespace for skill in source.skills.values()} == {"superpowers"}


def test_validate_numeric_version_is_normalized(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: 0.1
targets:
  code.task:
    steps:
      - inspect
""",
    )

    source = load_source(path)

    assert source.version == "0.1"


def test_validate_unknown_policy(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.task:
    policies:
      - missing_policy
""",
    )

    result = compile_agentmakefile(path)

    assert not result.ok
    assert any(item.code == "AMF105" for item in result.diagnostics.items)


def test_validate_include_path(tmp_path: Path) -> None:
    (tmp_path / "policies.yml").write_text(
        """\
version: "0.1"
policies:
  included_policy:
    guards:
      - included_guard
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: policies.yml
targets:
  code.task:
    policies:
      - included_policy
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert result.ok
    assert "included_policy" in result.files[0].content


def test_include_as_prefixes_included_names_and_internal_references(tmp_path: Path) -> None:
    (tmp_path / "framework.yml").write_text(
        """\
version: "0.1"
policies:
  base_policy:
    guards:
      - base_guard
skills:
  helper_skill:
    description: Included helper skill.
targets:
  helper.task:
    policies:
      - base_policy
    skills:
      - helper_skill
  code.task:
    policies:
      - base_policy
    skills:
      - helper_skill
    deps:
      - helper.task
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: framework.yml
    as: framework
policies:
  local_policy:
    guards:
      - local_guard
targets:
  local.code:
    extends: framework.code.task
    add_policies:
      - local_policy
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert result.ok, result.diagnostics.format()
    content = result.files[0].content
    assert "### framework.base_policy" in content
    assert "### framework.helper_skill" in content
    assert "### framework.code.task" in content
    assert "- framework.base_policy" in content
    assert "- framework.helper_skill" in content
    assert "- framework.helper.task" in content
    assert "### local.code" in content
    assert "- local_policy" in content


def test_include_as_allows_local_target_to_extend_namespaced_karpathy_module(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        f"""\
version: "0.1"
include:
  - path: {KARPATHY_MODULE}
    as: karpathy
policies:
  local_policy:
    guards:
      - local_guard
targets:
  local.code.task:
    extends: karpathy.code.task
    add_policies:
      - local_policy
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert result.ok, result.diagnostics.format()
    content = result.files[0].content
    assert "### karpathy.code.task" in content
    assert "### local.code.task" in content
    assert "- karpathy.think_before_coding" in content
    assert "- karpathy.simplicity_first" in content
    assert "- local_policy" in content


def test_duplicate_names_after_include_merge_report_stable_diagnostics(tmp_path: Path) -> None:
    (tmp_path / "first.yml").write_text(
        """\
version: "0.1"
policies:
  repeated_policy:
    guards:
      - first_guard
skills:
  repeated_skill:
    description: First skill.
targets:
  repeated.task:
    steps:
      - first_step
"""
    )
    (tmp_path / "second.yml").write_text(
        """\
version: "0.1"
policies:
  repeated_policy:
    guards:
      - second_guard
skills:
  repeated_skill:
    description: Second skill.
targets:
  repeated.task:
    steps:
      - second_step
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: first.yml
  - path: second.yml
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    duplicates = [item for item in result.diagnostics.items if item.code == "AMF113"]
    assert [(item.message, item.location) for item in duplicates] == [
        ("duplicate policy after include merge: repeated_policy", "policies.repeated_policy"),
        ("duplicate skill after include merge: repeated_skill", "skills.repeated_skill"),
        ("duplicate target after include merge: repeated.task", "targets.repeated.task"),
    ]
    assert all(item.hint == "rename one definition or include a reusable module with an alias using include.as" for item in duplicates)


def test_local_agentmakefile_overlay_can_override_included_names(tmp_path: Path) -> None:
    (tmp_path / "base.yml").write_text(
        """\
version: "0.1"
policies:
  overridable_policy:
    guards:
      - base_guard
skills:
  overridable_skill:
    description: Base skill.
targets:
  overridable.task:
    policies:
      - overridable_policy
    skills:
      - overridable_skill
    steps:
      - base_step
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: base.yml
policies:
  overridable_policy:
    guards:
      - local_guard
skills:
  overridable_skill:
    description: Local skill.
targets:
  overridable.task:
    policies:
      - overridable_policy
    skills:
      - overridable_skill
    steps:
      - local_step
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert result.ok, result.diagnostics.format()
    assert not any(item.code == "AMF113" for item in result.diagnostics.items)
    content = result.files[0].content
    assert "local_guard" in content
    assert "Local skill." in content
    assert "local_step" in content
    assert "base_guard" not in content
    assert "Base skill." not in content
    assert "base_step" not in content


def test_validate_package_include_disabled(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - package: karpathy-guidelines
    version: ^0.1
""",
    )

    source, diagnostics = load_source_with_diagnostics(path)

    assert source is None
    assert diagnostics.has_errors
    assert "package includes are future-facing" in diagnostics.format()


def test_validate_artifacts_outputs_conflict(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
artifacts:
  agents-md:
    path: AGENTS.md
outputs:
  agents-md:
    path: AGENTS.generated.md
""",
    )

    source, diagnostics = load_source_with_diagnostics(path)

    assert source is None
    assert diagnostics.has_errors
    assert "backend keys cannot appear in both artifacts and outputs" in diagnostics.format()


def test_validate_all_target_conflict(tmp_path: Path) -> None:
    path = write_agentmakefile(tmp_path)

    result = compile_agentmakefile(path, targets=["agents-md"], all_backends=True)

    assert not result.ok
    assert any(item.code == "AMF109" for item in result.diagnostics.items)


def test_validate_short_form_permissions(tmp_path: Path) -> None:
    path = write_agentmakefile(tmp_path)
    source = load_source(path)
    ir = normalize(source, Diagnostics())

    assert ir is not None
    assert {(item.tool, item.pattern, item.action) for item in ir.permissions} == {
        ("bash", "git status", "allow"),
        ("bash", "npm install*", "ask"),
    }


def test_parse_preserve_future_sections(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
patterns:
  "*.review":
    output_format:
      - summary
cache:
  key:
    - package-lock.json
tool_rules:
  web_search:
    required_when:
      - current_info
""",
    )

    source = load_source(path)
    ir = normalize(source, Diagnostics())

    assert ir is not None
    assert "*.review" in ir.patterns
    assert "key" in ir.cache
    assert "web_search" in ir.tool_rules


def test_compile_claude_md_snapshot(tmp_path: Path) -> None:
    result = compile_agentmakefile(KARPATHY_FIXTURE, targets=["claude-md"])

    assert result.ok
    assert result.files[0].path == "CLAUDE.md"
    assert "# karpathy-coding-guidelines - Claude Code" in result.files[0].content
    assert "think_before_coding" in result.files[0].content


def test_compile_agents_md_snapshot(tmp_path: Path) -> None:
    result = compile_agentmakefile(KARPATHY_FIXTURE, targets=["agents-md"])

    assert result.ok
    assert result.files[0].path == "AGENTS.md"
    assert "# karpathy-coding-guidelines - Generic Coding Agents" in result.files[0].content
    assert "code.task" in result.files[0].content


def test_compile_cursor_rule_snapshot(tmp_path: Path) -> None:
    result = compile_agentmakefile(KARPATHY_FIXTURE, targets=["cursor-rule"])

    assert result.ok
    assert result.files[0].path == ".cursor/rules/karpathy-guidelines.mdc"
    assert result.files[0].content.startswith("---\nalwaysApply: true\n")
    assert "Behavioral guidelines" in result.files[0].content


def test_karpathy_demo_compiles_with_mvp0_targets() -> None:
    result = compile_agentmakefile(KARPATHY_DEMO, targets=["claude-md", "agents-md", "cursor-rule"])

    assert result.ok
    assert [file.path for file in result.files] == [
        "CLAUDE.md",
        "AGENTS.md",
        ".cursor/rules/karpathy-guidelines.mdc",
    ]


def test_framework_module_demos_compile_with_mvp0_targets() -> None:
    for path, cursor_output in [
        (SUPERPOWERS_DEMO, ".cursor/rules/superpowers-methodology.mdc"),
        (OH_MY_OPENAGENT_DEMO, ".cursor/rules/oh-my-openagent-framework.mdc"),
    ]:
        result = compile_agentmakefile(path, targets=["claude-md", "agents-md", "cursor-rule"])

        assert result.ok, result.diagnostics.format()
        assert [file.path for file in result.files] == ["CLAUDE.md", "AGENTS.md", cursor_output]


def test_compile_trace_records_phases() -> None:
    result = compile_agentmakefile(KARPATHY_DEMO, targets=["agents-md"], trace=True)

    assert result.ok, result.diagnostics.format()
    assert [event.phase for event in result.trace] == [
        "start",
        "load_source",
        "select_targets",
        "normalize_ir",
        "emit_backend",
        "finish",
    ]
    assert result.trace[4].data["backend"] == "agents-md"
    assert result.trace[4].data["files"] == ["AGENTS.md"]


def test_cli_compile_trace_text(capsys) -> None:
    exit_code = main(["compile", "--file", str(KARPATHY_DEMO), "--target", "agents-md", "--trace"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Trace:" in captured.out
    assert "  start: compile started" in captured.out
    assert "  load_source: source loaded" in captured.out
    assert "  emit_backend: emitted backend agents-md" in captured.out


def test_cli_compile_trace_json(capsys) -> None:
    exit_code = main(
        [
            "compile",
            "--file",
            str(KARPATHY_DEMO),
            "--target",
            "agents-md",
            "--trace",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert [event["phase"] for event in payload["trace"]] == [
        "start",
        "load_source",
        "select_targets",
        "normalize_ir",
        "emit_backend",
        "finish",
    ]


def test_managed_block_insert(tmp_path: Path) -> None:
    path = write_agentmakefile(tmp_path)
    out = tmp_path / "out"

    result = compile_agentmakefile(path, out_dir=out, targets=["agents-md"], write=True)

    assert result.ok
    written = out / "AGENTS.md"
    assert written.exists()
    assert written.read_text().startswith(BEGIN_MARKER)


def test_managed_block_update(tmp_path: Path) -> None:
    path = write_agentmakefile(tmp_path)
    out = tmp_path / "out"
    existing = out / "AGENTS.md"
    existing.parent.mkdir()
    existing.write_text(f"human text\n{BEGIN_MARKER}\nold\n<!-- END GENERATED BY agentmf -->\nfooter\n")

    result = compile_agentmakefile(path, out_dir=out, targets=["agents-md"], write=True)

    assert result.ok
    updated = existing.read_text()
    assert "human text" in updated
    assert "footer" in updated
    assert "old" not in updated
    assert "code.task" in updated


def test_write_preflight_prevents_partial_writes_when_later_artifact_is_blocked(tmp_path: Path) -> None:
    path = write_agentmakefile(tmp_path)
    out = tmp_path / "out"
    agents = out / "AGENTS.md"
    cursor = out / ".cursor/rules/agentmakefile-generated.mdc"
    agents.parent.mkdir(parents=True)
    cursor.parent.mkdir(parents=True)
    agents.write_text(f"{BEGIN_MARKER}\nold agents\n<!-- END GENERATED BY agentmf -->\n")
    cursor.write_text("human cursor rule\n")

    result = compile_agentmakefile(path, out_dir=out, targets=["agents-md", "cursor-rule"], write=True)

    assert not result.ok
    assert any(item.code == "AMF110" for item in result.diagnostics.items)
    assert agents.read_text() == f"{BEGIN_MARKER}\nold agents\n<!-- END GENERATED BY agentmf -->\n"
    assert cursor.read_text() == "human cursor rule\n"
