from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Optional

import yaml

from agentmf.backends import render_skill_markdown, skill_output_path
from agentmf.compiler import BEGIN_MARKER, END_MARKER, compile_agentmakefile
from agentmf.cli import main
from agentmf.ir import normalize
from agentmf.loader import load_source, load_source_with_diagnostics
from agentmf.diagnostics import Diagnostics
from agentmf.runtime import create_run_plan
from agentmf.selector import create_link_plan


FIXTURE_DIR = Path(__file__).parent / "fixtures"
SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
README = Path(__file__).parents[1] / "README.md"
MODULE_DIR = Path(__file__).parents[1] / "modules"
DEMO_DIR = Path(__file__).parents[1] / "demos"
CI_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "test.yml"
KARPATHY_FIXTURE = FIXTURE_DIR / "karpathy" / "AgentMakefile"
SUPERPOWERS_FIXTURE = FIXTURE_DIR / "superpowers_minimal" / "AgentMakefile"
OH_MY_OPENAGENT_FIXTURE = FIXTURE_DIR / "oh_my_openagent" / "AgentMakefile"
UNKNOWN_REPO_SECURITY_FIXTURE = FIXTURE_DIR / "unknown_repo_security" / "AgentMakefile"
TARGET_COMPOSITION_FIXTURE = FIXTURE_DIR / "target_composition" / "AgentMakefile"
KARPATHY_DEMO = DEMO_DIR / "karpathy" / "AgentMakefile"
SUPERPOWERS_DEMO = DEMO_DIR / "superpowers" / "AgentMakefile"
OH_MY_OPENAGENT_DEMO = DEMO_DIR / "oh-my-openagent" / "AgentMakefile"
LOCAL_COMPOSITION_DEMO = DEMO_DIR / "local-composition" / "AgentMakefile"
UNKNOWN_REPO_SECURITY_DEMO = DEMO_DIR / "unknown-repo-security" / "AgentMakefile"
KARPATHY_MODULE = MODULE_DIR / "karpathy" / "AgentMakefile"
SUPERPOWERS_MODULE = MODULE_DIR / "superpowers" / "AgentMakefile"
OH_MY_OPENAGENT_MODULE = MODULE_DIR / "oh-my-openagent" / "AgentMakefile"
UNKNOWN_REPO_SECURITY_MODULE = MODULE_DIR / "unknown-repo-security" / "AgentMakefile"
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


def assert_matches_snapshot(content: str, name: str) -> None:
    assert content == (SNAPSHOT_DIR / name).read_text()


def test_github_actions_workflow_runs_supported_python_matrix() -> None:
    assert CI_WORKFLOW.exists()
    workflow = yaml.safe_load(CI_WORKFLOW.read_text())

    assert set(workflow["on"]) == {"push", "pull_request"}
    assert workflow["permissions"] == {"contents": "read"}

    job = workflow["jobs"]["test"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["strategy"]["fail-fast"] is False
    assert job["strategy"]["matrix"]["python-version"] == ["3.9", "3.14"]

    steps = job["steps"]
    assert any(step.get("uses") == "actions/checkout@v6" for step in steps)
    assert any(step.get("uses") == "actions/setup-python@v6" for step in steps)

    run_commands = "\n".join(step.get("run", "") for step in steps)
    assert 'python -m pip install -e ".[test]"' in run_commands
    assert "PYTHONPATH=src python -m pytest -q" in run_commands
    assert "python -m compileall -q src" in run_commands


def test_readme_documents_quickstart_and_default_demo_path() -> None:
    readme = README.read_text()

    assert "## Quickstart" in readme
    assert "python3 -m venv .venv" in readme
    assert "python -m pip install -e ." in readme
    assert 'python -m pip install -e ".[test]"' in readme
    assert "PYTHONPATH=src python3 -m pytest -q" in readme
    assert "python3 -m compileall -q src" in readme

    assert "docs/spec_breakdown.md" in readme
    assert "agentmf validate --file demos/karpathy/AgentMakefile" in readme
    assert "agentmf compile --file demos/karpathy/AgentMakefile" in readme
    assert ".claude/skills/karpathy-guidelines/SKILL.md" in readme
    assert "claude-skill" in readme
    assert "codex-skill" in readme


def test_karpathy_demo_default_compile_emits_all_configured_outputs() -> None:
    result = compile_agentmakefile(KARPATHY_DEMO)

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == [
        "CLAUDE.md",
        ".claude/skills/karpathy-guidelines/SKILL.md",
        ".cursor/rules/karpathy-guidelines.mdc",
        "AGENTS.md",
        ".codex/skills/karpathy-guidelines/SKILL.md",
    ]

    claude_skill = next(file for file in result.files if file.path.startswith(".claude/skills/"))
    codex_skill = next(file for file in result.files if file.path.startswith(".codex/skills/"))
    for skill_file in [claude_skill, codex_skill]:
        assert "name: karpathy-guidelines" in skill_file.content
        assert "think_before_coding" in skill_file.content
        assert "surgical_changes" in skill_file.content
        assert "verify_or_explain_verification_gap" in skill_file.content


def test_shared_skill_renderer_emits_complete_skill_markdown(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  systematic-debugging:
    namespace: superpowers
    description: Debug failures by reproducing them and finding root cause before fixing.
    match:
      user_intent:
        - debug
        - failing test
    guards:
      - no_fix_before_reproduction
    steps:
      - reproduce_failure
      - inspect_recent_changes
      - identify_root_cause
      - add_regression_test
    output_format:
      - reproduction
      - root_cause
      - verification_result
""",
    )
    source = load_source(path)
    ir = normalize(source, Diagnostics())
    skill = ir.skills[0]

    content = render_skill_markdown(skill)

    assert content == """\
---
name: superpowers:systematic-debugging
description: Debug failures by reproducing them and finding root cause before fixing.
---

# superpowers:systematic-debugging

## Overview

Debug failures by reproducing them and finding root cause before fixing.

## When To Use

- `user_intent`: debug, failing test

## Guards

- no_fix_before_reproduction

## Procedure

- reproduce_failure
- inspect_recent_changes
- identify_root_cause
- add_regression_test

## Output Requirements

- reproduction
- root_cause
- verification_result
"""


def test_skill_output_path_slugifies_namespace_for_filesystem_paths(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  "Review Skill":
    namespace: "Super Powers"
    description: Review carefully.
""",
    )
    source = load_source(path)
    ir = normalize(source, Diagnostics())
    skill = ir.skills[0]

    assert skill_output_path(".claude/skills", skill) == ".claude/skills/super-powers-review-skill/SKILL.md"
    assert skill_output_path(".codex/skills", skill) == ".codex/skills/super-powers-review-skill/SKILL.md"
    assert "Super Powers:Review Skill" in render_skill_markdown(skill)


def test_validate_valid_files() -> None:
    for path in [
        KARPATHY_MODULE,
        SUPERPOWERS_MODULE,
        OH_MY_OPENAGENT_MODULE,
        UNKNOWN_REPO_SECURITY_MODULE,
        KARPATHY_FIXTURE,
        SUPERPOWERS_FIXTURE,
        OH_MY_OPENAGENT_FIXTURE,
        UNKNOWN_REPO_SECURITY_FIXTURE,
        TARGET_COMPOSITION_FIXTURE,
        KARPATHY_DEMO,
        SUPERPOWERS_DEMO,
        OH_MY_OPENAGENT_DEMO,
        LOCAL_COMPOSITION_DEMO,
        UNKNOWN_REPO_SECURITY_DEMO,
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


def test_local_composition_demo_compiles_mvp2_outputs() -> None:
    result = compile_agentmakefile(
        LOCAL_COMPOSITION_DEMO,
        targets=["claude-md", "agents-md", "cursor-rule"],
    )

    assert result.ok, result.diagnostics.format()
    assert [file.backend for file in result.files] == ["claude-md", "agents-md", "cursor-rule"]
    assert [file.path for file in result.files] == [
        "CLAUDE.md",
        "AGENTS.md",
        ".cursor/rules/local-composition-security-review.mdc",
    ]
    for file in result.files:
        assert "karpathy.code.task" in file.content
        assert "security.no_untrusted_execution" in file.content
        assert "repo.secure_code_review" in file.content


def test_unknown_repo_hard_rails_demo_compiles_soft_and_native_outputs() -> None:
    result = compile_agentmakefile(
        UNKNOWN_REPO_SECURITY_DEMO,
        targets=["claude-md", "agents-md", "cursor-rule", "claude-code", "opencode"],
    )

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == [
        "CLAUDE.md",
        "AGENTS.md",
        ".cursor/rules/unknown-repo-security.mdc",
        ".claude/settings.json",
        ".claude/hooks/before_tool_call/block_untrusted_installs.sh",
        "opencode.json",
    ]
    claude_md = next(file for file in result.files if file.path == "CLAUDE.md")
    assert "repo.unknown_repo_hard_rails" in claude_md.content
    assert "security.no_untrusted_execution" in claude_md.content
    assert "soft_fallback_guidance" in claude_md.content

    settings = json.loads(next(file for file in result.files if file.path == ".claude/settings.json").content)
    assert "Bash(npm install*)" in settings["permissions"]["deny"]
    assert settings["hooks"]["before_tool_call"] == [
        {
            "name": "block_untrusted_installs",
            "command": ".claude/hooks/before_tool_call/block_untrusted_installs.sh",
        }
    ]
    hook = next(file for file in result.files if file.path.endswith("block_untrusted_installs.sh"))
    assert "Blocked: inspect package scripts before installing dependencies." in hook.content
    assert "exit 2" in hook.content

    opencode = json.loads(next(file for file in result.files if file.path == "opencode.json").content)
    assert opencode["permission"]["bash"]["npm install*"] == "deny"
    assert "repo-unknown-repo-hard-rails" in opencode["agent"]


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


def test_locked_policy_cannot_remove_guard_from_include(tmp_path: Path) -> None:
    (tmp_path / "security.yml").write_text(
        """\
version: "0.1"
policies:
  security_policy:
    locked: true
    guards:
      - require_approval
      - block_secret_exfiltration
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: security.yml
policies:
  security_policy:
    locked: true
    guards:
      - require_approval
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.code, item.message, item.location, item.hint)
        for item in result.diagnostics.items
        if item.code == "AMF114"
    ] == [
        (
            "AMF114",
            "locked policy security_policy cannot remove guard: block_secret_exfiltration",
            "policies.security_policy.guards",
            "keep the locked policy requirements or add a stricter policy under a new name",
        )
    ]


def test_locked_policy_can_add_stricter_guards(tmp_path: Path) -> None:
    (tmp_path / "security.yml").write_text(
        """\
version: "0.1"
policies:
  security_policy:
    locked: true
    guards:
      - require_approval
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: security.yml
policies:
  security_policy:
    locked: true
    guards:
      - require_approval
      - block_secret_exfiltration
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert result.ok, result.diagnostics.format()
    assert not any(item.code == "AMF114" for item in result.diagnostics.items)
    assert "block_secret_exfiltration" in result.files[0].content


def test_locked_policy_keeps_locked_metadata_when_overlay_adds_requirements(tmp_path: Path) -> None:
    (tmp_path / "security.yml").write_text(
        """\
version: "0.1"
policies:
  security_policy:
    locked: true
    guards:
      - require_approval
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: security.yml
policies:
  security_policy:
    guards:
      - require_approval
      - block_secret_exfiltration
""",
    )

    source, diagnostics = load_source_with_diagnostics(path)

    assert source is not None
    assert not diagnostics.has_errors, diagnostics.format()
    assert source.policies["security_policy"].locked is True
    assert source.policies["security_policy"].guards == ["require_approval", "block_secret_exfiltration"]


def test_nested_include_policy_overlay_omitted_locked_does_not_report_unlock(tmp_path: Path) -> None:
    (tmp_path / "base.yml").write_text(
        """\
version: "0.1"
policies:
  security_policy:
    locked: true
    guards:
      - require_approval
"""
    )
    (tmp_path / "unrelated.yml").write_text(
        """\
version: "0.1"
metadata:
  package: unrelated
"""
    )
    (tmp_path / "overlay.yml").write_text(
        """\
version: "0.1"
include:
  - path: unrelated.yml
policies:
  security_policy:
    guards:
      - require_approval
      - block_secret_exfiltration
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: base.yml
  - path: overlay.yml
""",
    )

    _, diagnostics = load_source_with_diagnostics(path)

    assert any(item.code == "AMF113" for item in diagnostics.items)
    assert not any(item.code == "AMF114" for item in diagnostics.items), diagnostics.format()


def test_locked_policy_cannot_remove_steps_output_format_or_locked_metadata(tmp_path: Path) -> None:
    (tmp_path / "review.yml").write_text(
        """\
version: "0.1"
policies:
  review_policy:
    locked: true
    steps:
      - inspect_diff
      - run_tests
    output_format:
      - findings
      - verification_result
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: review.yml
policies:
  review_policy:
    locked: false
    steps:
      - inspect_diff
    output_format:
      - findings
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.message, item.location)
        for item in result.diagnostics.items
        if item.code == "AMF114"
    ] == [
        ("locked policy review_policy cannot be unlocked", "policies.review_policy.locked"),
        ("locked policy review_policy cannot remove step: run_tests", "policies.review_policy.steps"),
        (
            "locked policy review_policy cannot remove output format: verification_result",
            "policies.review_policy.output_format",
        ),
    ]


def test_target_composition_preserves_explicit_empty_overrides() -> None:
    source = load_source(TARGET_COMPOSITION_FIXTURE)
    diagnostics = Diagnostics()

    ir = normalize(source, diagnostics)

    assert ir is not None, diagnostics.format()
    child = next(target for target in ir.targets if target.name == "child.task")
    assert child.phony is False
    assert child.priority == 0
    assert child.description == "Child task."
    assert child.match == {}
    assert [policy.name for policy in child.policies] == ["child_policy"]
    assert child.steps == ["child_step"]
    assert child.output_format == ["child_output"]
    assert child.fallback == {}


def test_target_composition_fixture_matches_agents_md_snapshot() -> None:
    result = compile_agentmakefile(TARGET_COMPOSITION_FIXTURE, targets=["agents-md"])

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == ["AGENTS.md"]
    assert_matches_snapshot(result.files[0].content, "target-composition.agents.md")


def test_target_composition_reports_circular_extends(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  alpha.task:
    extends: beta.task
  beta.task:
    extends: alpha.task
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.code, item.message, item.location)
        for item in result.diagnostics.items
        if item.code == "AMF108"
    ] == [
        ("AMF108", "circular target extension involving alpha.task", "targets.alpha.task.extends"),
        ("AMF108", "circular target extension involving beta.task", "targets.beta.task.extends"),
    ]


def test_target_priority_rejects_string_numbers(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.task:
    priority: "90"
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.code, item.location)
        for item in result.diagnostics.items
        if item.code == "AMF102"
    ] == [("AMF102", f"{path}:targets.code.task.priority")]
    assert "integer" in result.diagnostics.items[0].message


def test_target_priority_rejects_values_outside_supported_range(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.task:
    priority: 101
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.code, item.location)
        for item in result.diagnostics.items
        if item.code == "AMF102"
    ] == [("AMF102", f"{path}:targets.code.task.priority")]
    assert "less than or equal to 100" in result.diagnostics.items[0].message


def test_target_dependencies_report_unknown_targets(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    deps:
      - missing.task
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.code, item.message, item.location)
        for item in result.diagnostics.items
        if item.code == "AMF122"
    ] == [
        (
            "AMF122",
            "target review.task depends on unknown target missing.task",
            "targets.review.task.deps",
        )
    ]


def test_target_dependencies_report_cycles(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  alpha.task:
    deps:
      - beta.task
  beta.task:
    deps:
      - alpha.task
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.code, item.message, item.location)
        for item in result.diagnostics.items
        if item.code == "AMF123"
    ] == [
        (
            "AMF123",
            "circular target dependency: alpha.task -> beta.task -> alpha.task",
            "targets.alpha.task.deps",
        )
    ]


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


def test_permission_rule_conflict_uses_most_restrictive_action(tmp_path: Path) -> None:
    (tmp_path / "base.yml").write_text(
        """\
version: "0.1"
permissions:
  bash:
    "npm install*": deny
    "git push*": allow
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: base.yml
permissions:
  bash:
    "npm install*": allow
    "git push*": ask
""",
    )

    source = load_source(path)
    ir = normalize(source, Diagnostics())

    assert ir is not None
    assert {(item.tool, item.pattern, item.action) for item in ir.permissions} == {
        ("bash", "git push*", "ask"),
        ("bash", "npm install*", "deny"),
    }


def test_permission_default_conflict_uses_most_restrictive_action(tmp_path: Path) -> None:
    (tmp_path / "base.yml").write_text(
        """\
version: "0.1"
permissions:
  defaults:
    bash: deny
    file_read: allow
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: base.yml
permissions:
  defaults:
    bash: allow
    file_read: ask
""",
    )

    source = load_source(path)
    ir = normalize(source, Diagnostics())

    assert ir is not None
    assert ir.permission_defaults == {
        "bash": "deny",
        "file_read": "ask",
    }


def test_invalid_permission_glob_pattern_emits_stable_diagnostic(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
permissions:
  bash:
    "[unterminated": deny
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.code, item.message, item.location, item.hint)
        for item in result.diagnostics.items
        if item.code == "AMF119"
    ] == [
        (
            "AMF119",
            "invalid permission glob pattern: [unterminated",
            "permissions.bash.[unterminated",
            "close '[' character classes with ']' or remove the character class",
        )
    ]


def test_invalid_permission_tool_name_emits_stable_diagnostic(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
permissions:
  "bad tool":
    "*": deny
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.code, item.message, item.location, item.hint)
        for item in result.diagnostics.items
        if item.code == "AMF120"
    ] == [
        (
            "AMF120",
            "invalid permission tool name: bad tool",
            "permissions.bad tool",
            "use a non-empty tool name without whitespace",
        )
    ]


def test_empty_permission_glob_pattern_emits_stable_diagnostic(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
permissions:
  bash:
    "": deny
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.code, item.message, item.location, item.hint)
        for item in result.diagnostics.items
        if item.code == "AMF119"
    ] == [
        (
            "AMF119",
            "invalid permission glob pattern: ",
            "permissions.bash.",
            "use a non-empty glob pattern",
        )
    ]


def test_empty_permission_tool_name_emits_stable_diagnostic(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
permissions:
  "":
    "*": deny
""",
    )

    result = compile_agentmakefile(path, targets=["agents-md"])

    assert not result.ok
    assert [
        (item.code, item.message, item.location, item.hint)
        for item in result.diagnostics.items
        if item.code == "AMF120"
    ] == [
        (
            "AMF120",
            "invalid permission tool name: ",
            "permissions.",
            "use a non-empty tool name without whitespace",
        )
    ]


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


def test_compile_claude_md_snapshot() -> None:
    result = compile_agentmakefile(KARPATHY_FIXTURE, targets=["claude-md"])

    assert result.ok, result.diagnostics.format()
    assert result.files[0].path == "CLAUDE.md"
    assert_matches_snapshot(result.files[0].content, "karpathy.claude.md")


def test_compile_claude_code_emits_native_permission_settings() -> None:
    result = compile_agentmakefile(UNKNOWN_REPO_SECURITY_FIXTURE, targets=["claude-code"])

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == [".claude/settings.json"]
    assert json.loads(result.files[0].content) == {
        "permissions": {
            "allow": ["Bash(git status)"],
            "ask": [],
            "deny": [
                "Bash(npm install*)",
                "Bash(pnpm install*)",
                "Bash(yarn install*)",
            ],
        }
    }


def test_soft_permission_backends_emit_downgrade_warnings() -> None:
    result = compile_agentmakefile(UNKNOWN_REPO_SECURITY_FIXTURE, targets=["agents-md", "cursor-rule", "claude-skill"])

    assert result.ok, result.diagnostics.format()
    assert [
        (item.severity, item.code, item.message, item.location)
        for item in result.diagnostics.items
        if item.code == "AMF121"
    ] == [
        (
            "warning",
            "AMF121",
            "permissions were compiled as soft instructions because backend agents-md does not support hard enforcement",
            "compile.targets.agents-md",
        ),
        (
            "warning",
            "AMF121",
            "permissions were compiled as soft instructions because backend cursor-rule does not support hard enforcement",
            "compile.targets.cursor-rule",
        ),
        (
            "warning",
            "AMF121",
            "permissions were compiled as soft instructions because backend claude-skill does not support hard enforcement",
            "compile.targets.claude-skill",
        ),
    ]


def test_hook_unsupported_backends_emit_downgrade_warnings(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
hooks:
  before_tool_call:
    - name: block_installs
      run: echo blocked
targets:
  review.task:
    steps:
      - inspect_context
""",
    )

    result = compile_agentmakefile(path, targets=["claude-md", "cursor-rule", "claude-code"])

    assert result.ok, result.diagnostics.format()
    assert [
        (item.severity, item.code, item.message, item.location)
        for item in result.diagnostics.items
        if item.code == "AMF124"
    ] == [
        (
            "warning",
            "AMF124",
            "hooks were compiled as soft instructions because backend claude-md does not support native hooks",
            "compile.targets.claude-md",
        ),
        (
            "warning",
            "AMF124",
            "hooks were compiled as soft instructions because backend cursor-rule does not support native hooks",
            "compile.targets.cursor-rule",
        ),
    ]


def test_markdown_permission_guidance_uses_formal_tables() -> None:
    result = compile_agentmakefile(UNKNOWN_REPO_SECURITY_FIXTURE, targets=["agents-md"])

    assert result.ok, result.diagnostics.format()
    content = result.files[0].content
    assert "| --- | --- |" in content
    assert "### Rules" in content
    assert "| Tool | Pattern | Action |" in content
    assert "| bash | npm install* | deny |" in content
    assert "| bash | pnpm install* | deny |" in content
    assert "| bash | yarn install* | deny |" in content
    assert "- `bash` `npm install*`: deny" not in content


def test_skill_permission_guidance_uses_formal_tables(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  secure-review:
    description: Review safely.
    steps:
      - inspect_manifests
permissions:
  defaults:
    bash: ask
  rules:
    bash:
      "npm install*": deny
      "git status": allow
""",
    )

    result = compile_agentmakefile(path, targets=["claude-skill"])

    assert result.ok, result.diagnostics.format()
    content = result.files[0].content
    assert "## Permission Guidance" in content
    assert "### Defaults" in content
    assert "| Tool | Action |" in content
    assert "| bash | ask |" in content
    assert "| Tool | Pattern | Action |" in content
    assert "| bash | npm install* | deny |" in content
    assert "| bash | git status | allow |" in content


def test_compile_claude_code_emits_hook_files_and_settings_references(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
hooks:
  before_tool_call:
    - name: block_install
      when:
        tool: bash
        command_matches:
          - "npm install*"
      action: deny
      message: "Blocked install command."
""",
    )

    result = compile_agentmakefile(path, targets=["claude-code"])

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == [
        ".claude/settings.json",
        ".claude/hooks/before_tool_call/block_install.sh",
    ]
    assert json.loads(result.files[0].content) == {
        "hooks": {
            "before_tool_call": [
                {
                    "name": "block_install",
                    "command": ".claude/hooks/before_tool_call/block_install.sh",
                }
            ]
        }
    }
    assert result.files[1].backend == "claude-code"
    assert result.files[1].managed_block is False
    assert 'echo "Blocked install command." >&2' in result.files[1].content
    assert "exit 2" in result.files[1].content


def test_compile_opencode_emits_config_with_permissions_and_agents() -> None:
    result = compile_agentmakefile(UNKNOWN_REPO_SECURITY_FIXTURE, targets=["opencode"])

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == ["opencode.json"]
    config = json.loads(result.files[0].content)
    assert config["$schema"] == "https://opencode.ai/config.json"
    assert config["permission"] == {
        "bash": {
            "git status": "allow",
            "npm install*": "deny",
            "pnpm install*": "deny",
            "yarn install*": "deny",
        }
    }
    assert config["agent"]["repo-security-review"]["description"] == "Review an unknown repository without executing untrusted code."
    assert config["agent"]["repo-security-review"]["mode"] == "subagent"
    assert config["agent"]["repo-security-review"]["permission"] == config["permission"]
    prompt = config["agent"]["repo-security-review"]["prompt"]
    assert "repo.security_review" in prompt
    assert "no_untrusted_execution" in prompt
    assert "inspect_dependency_manifests" in prompt
    assert "safe_next_steps" in prompt


def test_compile_claude_skill_emits_one_skill_file_per_skill_entry(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  systematic-debugging:
    namespace: superpowers
    description: Debug methodically.
    match:
      user_intent:
        - debug
    steps:
      - reproduce_failure
    output_format:
      - root_cause
  local-review:
    description: Review local changes.
    guards:
      - inspect_diff_first
    steps:
      - report_findings
""",
    )

    result = compile_agentmakefile(path, targets=["claude-skill"])

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == [
        ".claude/skills/local-review/SKILL.md",
        ".claude/skills/superpowers-systematic-debugging/SKILL.md",
    ]
    assert [file.backend for file in result.files] == ["claude-skill", "claude-skill"]
    assert all(file.managed_block is False for file in result.files)
    assert all(file.overwrite is False for file in result.files)

    systematic = next(file for file in result.files if "superpowers-systematic-debugging" in file.path)
    assert "name: superpowers:systematic-debugging" in systematic.content
    assert "## When To Use" in systematic.content
    assert "- `user_intent`: debug" in systematic.content
    assert "## Procedure" in systematic.content
    assert "- reproduce_failure" in systematic.content
    assert "## Output Requirements" in systematic.content
    assert "- root_cause" in systematic.content


def test_compile_claude_skill_fixtures_are_supported() -> None:
    karpathy = compile_agentmakefile(KARPATHY_FIXTURE, targets=["claude-skill"])
    superpowers = compile_agentmakefile(SUPERPOWERS_FIXTURE, targets=["claude-skill"])

    assert karpathy.ok, karpathy.diagnostics.format()
    assert [file.path for file in karpathy.files] == [".claude/skills/karpathy-guidelines/SKILL.md"]
    assert_matches_snapshot(karpathy.files[0].content, "karpathy.claude-skill.md")
    assert superpowers.ok, superpowers.diagnostics.format()
    assert ".claude/skills/superpowers-systematic-debugging/SKILL.md" in [
        file.path for file in superpowers.files
    ]


def test_compile_codex_skill_emits_one_skill_file_per_skill_entry(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  systematic-debugging:
    namespace: superpowers
    description: Debug methodically.
    match:
      user_intent:
        - debug
    steps:
      - reproduce_failure
    output_format:
      - root_cause
  local-review:
    description: Review local changes.
    guards:
      - inspect_diff_first
    steps:
      - report_findings
""",
    )

    result = compile_agentmakefile(path, targets=["codex-skill"])

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == [
        ".codex/skills/local-review/SKILL.md",
        ".codex/skills/superpowers-systematic-debugging/SKILL.md",
    ]
    assert [file.backend for file in result.files] == ["codex-skill", "codex-skill"]
    assert all(file.managed_block is False for file in result.files)
    assert all(file.overwrite is False for file in result.files)

    systematic = next(file for file in result.files if "superpowers-systematic-debugging" in file.path)
    assert "name: superpowers:systematic-debugging" in systematic.content
    assert "## When To Use" in systematic.content
    assert "- `user_intent`: debug" in systematic.content
    assert "## Procedure" in systematic.content
    assert "- reproduce_failure" in systematic.content
    assert "## Output Requirements" in systematic.content
    assert "- root_cause" in systematic.content


def test_compile_codex_skill_fixtures_are_supported() -> None:
    karpathy = compile_agentmakefile(KARPATHY_FIXTURE, targets=["codex-skill"])
    superpowers = compile_agentmakefile(SUPERPOWERS_FIXTURE, targets=["codex-skill"])

    assert karpathy.ok, karpathy.diagnostics.format()
    assert [file.path for file in karpathy.files] == [".codex/skills/karpathy-guidelines/SKILL.md"]
    assert_matches_snapshot(karpathy.files[0].content, "karpathy.codex-skill.md")
    assert superpowers.ok, superpowers.diagnostics.format()
    assert ".codex/skills/superpowers-systematic-debugging/SKILL.md" in [
        file.path for file in superpowers.files
    ]


def test_compile_agents_md_snapshot() -> None:
    result = compile_agentmakefile(KARPATHY_FIXTURE, targets=["agents-md"])

    assert result.ok, result.diagnostics.format()
    assert result.files[0].path == "AGENTS.md"
    assert_matches_snapshot(result.files[0].content, "karpathy.agents.md")


def test_compile_agents_fragments_emits_target_fragments_with_dependency_closure(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"

metadata:
  name: fragment-fixture

policies:
  shared_policy:
    description: Shared dependency policy.
    steps:
      - action: inspect_shared_state
  review_policy:
    description: Review-only policy.
    steps:
      - action: inspect_review_diff
  unrelated_policy:
    description: Unrelated target-only policy.
    steps:
      - action: run_unrelated_flow

skills:
  review-skill:
    namespace: superpowers
    description: Review-only skill.
    steps:
      - evaluate_findings
  unrelated-skill:
    namespace: superpowers
    description: Unrelated target-only skill.
    steps:
      - unrelated_skill_step

targets:
  base.task:
    policies:
      - shared_policy
    steps:
      - action: inspect_base
  review.task:
    deps:
      - base.task
    policies:
      - review_policy
    skills:
      - superpowers:review-skill
    steps:
      - action: review_code
    output_format:
      - findings
  unrelated.task:
    policies:
      - unrelated_policy
    skills:
      - superpowers:unrelated-skill
    steps:
      - action: unrelated_only
""",
    )

    result = compile_agentmakefile(path, targets=["agents-fragments"])

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == [
        ".agentmf/fragments/agents/base.task.md",
        ".agentmf/fragments/agents/review.task.md",
        ".agentmf/fragments/agents/unrelated.task.md",
        ".agentmf/fragments/manifest.json",
    ]
    review_fragment = next(file for file in result.files if file.path.endswith("review.task.md"))
    assert review_fragment.backend == "agents-fragments"
    assert "### base.task" in review_fragment.content
    assert "### review.task" in review_fragment.content
    assert "shared_policy" in review_fragment.content
    assert "review_policy" in review_fragment.content
    assert "superpowers:review-skill" in review_fragment.content
    assert "review_code" in review_fragment.content
    assert "findings" in review_fragment.content
    assert "unrelated.task" not in review_fragment.content
    assert "unrelated_policy" not in review_fragment.content
    assert "superpowers:unrelated-skill" not in review_fragment.content
    assert "unrelated_only" not in review_fragment.content


def test_compile_claude_fragments_uses_claude_fragment_directory() -> None:
    result = compile_agentmakefile(KARPATHY_FIXTURE, targets=["claude-fragments"])

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == [
        ".agentmf/fragments/claude/code.quick_fix.md",
        ".agentmf/fragments/claude/code.task.md",
        ".agentmf/fragments/manifest.json",
    ]
    code_task = next(file for file in result.files if file.path.endswith("code.task.md"))
    assert code_task.backend == "claude-fragments"
    assert "# code.task - Claude Code Target Fragment" in code_task.content


def test_compile_agents_fragments_emits_deterministic_manifest_with_hashes(tmp_path: Path) -> None:
    (tmp_path / "shared.yml").write_text(
        """\
version: "0.1"
policies:
  shared_policy:
    description: Shared policy.
    steps:
      - inspect_shared
targets:
  base.task:
    policies:
      - shared_policy
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: shared.yml
metadata:
  name: manifest-fixture
policies:
  review_policy:
    description: Review policy.
skills:
  review-skill:
    namespace: superpowers
    description: Review skill.
targets:
  review.task:
    deps:
      - base.task
    policies:
      - review_policy
    skills:
      - superpowers:review-skill
    output_format:
      - findings
""",
    )

    result = compile_agentmakefile(path, targets=["agents-fragments"])

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == [
        ".agentmf/fragments/agents/base.task.md",
        ".agentmf/fragments/agents/review.task.md",
        ".agentmf/fragments/manifest.json",
    ]
    manifest_file = next(file for file in result.files if file.path == ".agentmf/fragments/manifest.json")
    manifest = json.loads(manifest_file.content)
    assert_matches_snapshot(manifest_file.content, "fragment-manifest.agents.json")
    assert manifest["version"] == 1
    assert manifest["compiler_version"] == "0.1.0"
    assert [entry["path"] for entry in manifest["fragments"]] == [
        ".agentmf/fragments/agents/base.task.md",
        ".agentmf/fragments/agents/review.task.md",
    ]
    review_fragment = next(file for file in result.files if file.path.endswith("review.task.md"))
    review_entry = next(entry for entry in manifest["fragments"] if entry["target"] == "review.task")
    assert review_entry == {
        "backend": "agents-fragments",
        "target": "review.task",
        "path": ".agentmf/fragments/agents/review.task.md",
        "target_closure": ["base.task", "review.task"],
        "inputs": ["AgentMakefile", "shared.yml"],
        "policies": ["shared_policy", "review_policy"],
        "skills": ["superpowers:review-skill"],
        "hash": f"sha256:{hashlib.sha256(review_fragment.content.encode()).hexdigest()}",
    }


def test_write_fragments_reports_unchanged_outputs_on_second_run(tmp_path: Path) -> None:
    path = write_agentmakefile(tmp_path)
    out = tmp_path / "out"

    first = compile_agentmakefile(path, out_dir=out, targets=["agents-fragments"], write=True)
    second = compile_agentmakefile(path, out_dir=out, targets=["agents-fragments"], write=True)

    assert first.ok, first.diagnostics.format()
    assert second.ok, second.diagnostics.format()
    assert [path.relative_to(out).as_posix() for path in first.wrote] == [
        ".agentmf/fragments/agents/code.task.md",
        ".agentmf/fragments/manifest.json",
    ]
    assert second.wrote == []
    assert [path.relative_to(out).as_posix() for path in second.unchanged] == [
        ".agentmf/fragments/agents/code.task.md",
        ".agentmf/fragments/manifest.json",
    ]


def test_changing_unrelated_module_does_not_rewrite_unaffected_fragment(tmp_path: Path) -> None:
    (tmp_path / "alpha.yml").write_text(
        """\
version: "0.1"
policies:
  policy:
    description: Alpha policy.
targets:
  task:
    policies:
      - policy
"""
    )
    (tmp_path / "beta.yml").write_text(
        """\
version: "0.1"
policies:
  policy:
    description: Beta policy.
targets:
  task:
    policies:
      - policy
"""
    )
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
include:
  - path: alpha.yml
    as: alpha
  - path: beta.yml
    as: beta
""",
    )
    out = tmp_path / "out"

    first = compile_agentmakefile(path, out_dir=out, targets=["agents-fragments"], write=True)
    (tmp_path / "beta.yml").write_text(
        """\
version: "0.1"
policies:
  policy:
    description: Updated beta policy.
targets:
  task:
    policies:
      - policy
"""
    )
    second = compile_agentmakefile(path, out_dir=out, targets=["agents-fragments"], write=True)

    assert first.ok, first.diagnostics.format()
    assert second.ok, second.diagnostics.format()
    assert [path.relative_to(out).as_posix() for path in second.wrote] == [
        ".agentmf/fragments/agents/beta.task.md",
        ".agentmf/fragments/manifest.json",
    ]
    assert [path.relative_to(out).as_posix() for path in second.unchanged] == [
        ".agentmf/fragments/agents/alpha.task.md",
    ]


def test_link_plan_for_explicit_target_returns_dependency_order(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  base.task:
    steps:
      - action: inspect_base
  review.task:
    deps:
      - base.task
    steps:
      - action: inspect_review
""",
    )

    result = create_link_plan(path, target_names=["review.task"], backend="agents-fragments")

    assert result.ok, result.diagnostics.format()
    assert result.plan == {
        "version": 1,
        "backend": "agents-fragments",
        "selection": {
            "mode": "explicit_target",
            "request": None,
            "targets": ["review.task"],
        },
        "selected_targets": ["review.task"],
        "target_closure": ["base.task", "review.task"],
        "fragments": [
            {
                "backend": "agents-fragments",
                "target": "base.task",
                "path": ".agentmf/fragments/agents/base.task.md",
            },
            {
                "backend": "agents-fragments",
                "target": "review.task",
                "path": ".agentmf/fragments/agents/review.task.md",
            },
        ],
    }


def test_link_plan_for_request_selects_highest_priority_matching_target(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.change:
    priority: 50
    match:
      user_intent:
        - implement code
  methodology.review:
    priority: 80
    match:
      user_intent:
        - review code
  review.task:
    priority: 90
    deps:
      - methodology.review
    match:
      user_intent:
        - review code
        - find findings
""",
    )

    result = create_link_plan(path, request="please review code and find findings", backend="claude-fragments")

    assert result.ok, result.diagnostics.format()
    assert result.plan["selection"] == {
        "mode": "request",
        "request": "please review code and find findings",
        "targets": [],
    }
    assert result.plan["selected_targets"] == ["review.task"]
    assert result.plan["target_closure"] == ["methodology.review", "review.task"]
    assert result.plan["fragments"] == [
        {
            "backend": "claude-fragments",
            "target": "methodology.review",
            "path": ".agentmf/fragments/claude/methodology.review.md",
        },
        {
            "backend": "claude-fragments",
            "target": "review.task",
            "path": ".agentmf/fragments/claude/review.task.md",
        },
    ]


def test_cli_select_outputs_stable_json_link_plan(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  base.task:
    steps:
      - action: inspect_base
  review.task:
    deps:
      - base.task
    match:
      user_intent:
        - review code
""",
    )

    exit_code = main(
        [
            "select",
            "--file",
            str(path),
            "--target",
            "review.task",
            "--backend",
            "agents-fragments",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert_matches_snapshot(captured.out, "link-plan.select.json")
    assert payload["ok"] is True
    assert payload["link_plan"]["target_closure"] == ["base.task", "review.task"]
    assert payload["link_plan"]["fragments"] == [
        {
            "backend": "agents-fragments",
            "target": "base.task",
            "path": ".agentmf/fragments/agents/base.task.md",
        },
        {
            "backend": "agents-fragments",
            "target": "review.task",
            "path": ".agentmf/fragments/agents/review.task.md",
        },
    ]


def test_runtime_dry_run_plan_summarizes_selected_runtime_contracts(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
policies:
  review_policy:
    guards:
      - policy_guard
    steps:
      - policy_step
targets:
  base.task:
    steps:
      - action: inspect_base
  review.task:
    deps:
      - base.task
    match:
      user_intent:
        - review code
    policies:
      - review_policy
    guards:
      - target_guard
    steps:
      - action: review_code
    output_format:
      - findings
    fallback:
      blocked:
        - summarize_blocker
permissions:
  defaults:
    bash: ask
  rules:
    bash:
      "git status": allow
""",
    )

    result = create_run_plan(path, request="please review code", backend="agents-fragments", dry_run=True)

    assert result.ok, result.diagnostics.format()
    assert result.plan["mode"] == "dry_run"
    assert result.plan["execution"]["enabled"] is False
    assert result.plan["link_plan"]["target_closure"] == ["base.task", "review.task"]
    assert result.plan["runtime_phases"] == [
        {"name": "target_selection", "status": "resolved"},
        {"name": "dependency_graph_resolution", "status": "resolved"},
        {"name": "prompt_fragment_linking", "status": "linked"},
        {"name": "guard_evaluation", "status": "evaluated_dry_run"},
        {"name": "permission_enforcement", "status": "not_executed"},
        {"name": "step_execution", "status": "not_executed"},
        {"name": "output_validation", "status": "not_executed"},
        {"name": "fallback_handling", "status": "not_executed"},
        {"name": "trace_logging", "status": "planned"},
    ]
    assert result.plan["target_contracts"] == [
        {
            "name": "base.task",
            "deps": [],
            "policies": [],
            "skills": [],
            "guards": [],
            "steps": [{"action": "inspect_base"}],
            "output_format": [],
            "fallback": {},
        },
        {
            "name": "review.task",
            "deps": ["base.task"],
            "policies": ["review_policy"],
            "skills": [],
            "guards": ["target_guard"],
            "steps": [{"action": "review_code"}],
            "output_format": ["findings"],
            "fallback": {"blocked": ["summarize_blocker"]},
        },
    ]
    assert result.plan["policy_contracts"] == [
        {
            "name": "review_policy",
            "guards": ["policy_guard"],
            "steps": ["policy_step"],
            "output_format": [],
        }
    ]
    assert result.plan["guard_evaluation"] == {
        "mode": "dry_run",
        "executed": False,
        "guards": [
            {
                "source": "policy",
                "target": "review.task",
                "policy": "review_policy",
                "guard": "policy_guard",
                "status": "planned",
            },
            {
                "source": "target",
                "target": "review.task",
                "guard": "target_guard",
                "status": "planned",
            },
        ],
    }
    assert result.plan["permission_contract"] == {
        "defaults": {"bash": "ask"},
        "rules": [{"tool": "bash", "pattern": "git status", "action": "allow"}],
    }


def test_runtime_permission_dry_run_evaluates_proposed_tool_calls(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    steps:
      - action: review_code
permissions:
  defaults:
    bash: ask
  rules:
    bash:
      "git status": allow
      "npm install*": deny
""",
    )

    result = create_run_plan(
        path,
        target_names=["review.task"],
        backend="agents-fragments",
        dry_run=True,
        proposed_tool_calls=[
            {"tool": "bash", "input": "git status"},
            {"tool": "bash", "input": "npm install lodash"},
            {"tool": "file_write", "input": "README.md"},
        ],
    )

    assert result.ok, result.diagnostics.format()
    assert result.plan["runtime_phases"][4] == {
        "name": "permission_enforcement",
        "status": "evaluated_dry_run",
    }
    assert result.plan["permission_evaluation"] == {
        "mode": "dry_run",
        "executed": False,
        "default_action": "ask",
        "tool_calls": [
            {
                "tool": "bash",
                "input": "git status",
                "action": "allow",
                "source": "rule",
                "matched_rules": [
                    {"tool": "bash", "pattern": "git status", "action": "allow"}
                ],
            },
            {
                "tool": "bash",
                "input": "npm install lodash",
                "action": "deny",
                "source": "rule",
                "matched_rules": [
                    {"tool": "bash", "pattern": "npm install*", "action": "deny"}
                ],
            },
            {
                "tool": "file_write",
                "input": "README.md",
                "action": "ask",
                "source": "implicit_default",
                "matched_rules": [],
            },
        ],
    }


def test_runtime_permission_dry_run_uses_most_restrictive_matching_rule(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    steps:
      - action: review_code
permissions:
  defaults:
    bash: allow
  rules:
    bash:
      "git *": allow
      "git push*": ask
      "git push --force*": deny
""",
    )

    result = create_run_plan(
        path,
        target_names=["review.task"],
        dry_run=True,
        proposed_tool_calls=[
            {"tool": "bash", "input": "git push --force origin main"},
        ],
    )

    assert result.ok, result.diagnostics.format()
    assert result.plan["permission_evaluation"]["tool_calls"] == [
        {
            "tool": "bash",
            "input": "git push --force origin main",
            "action": "deny",
            "source": "rule",
            "matched_rules": [
                {"tool": "bash", "pattern": "git *", "action": "allow"},
                {"tool": "bash", "pattern": "git push --force*", "action": "deny"},
                {"tool": "bash", "pattern": "git push*", "action": "ask"},
            ],
        }
    ]


def test_runtime_execution_without_dry_run_is_rejected(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    steps:
      - action: review_code
""",
    )

    result = create_run_plan(path, target_names=["review.task"], dry_run=False)

    assert not result.ok
    assert [
        (item.code, item.message, item.location, item.hint)
        for item in result.diagnostics.items
    ] == [
        (
            "AMF125",
            "runtime execution is not implemented; use --dry-run to inspect the runtime plan",
            "run",
            "runtime mode currently supports dry-run planning and prompt linking only",
        )
    ]


def test_runtime_dry_run_links_prompt_prefix_and_reports_size_comparison(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
metadata:
  name: runtime-link-fixture
targets:
  base.task:
    steps:
      - action: inspect_base
  review.task:
    deps:
      - base.task
    match:
      user_intent:
        - review code
    steps:
      - action: review_code
  unrelated.task:
    steps:
      - action: unrelated_only
""",
    )

    result = create_run_plan(path, request="please review code", backend="agents-fragments", dry_run=True)

    assert result.ok, result.diagnostics.format()
    prompt_prefix = result.plan["prompt_prefix"]
    assert prompt_prefix["backend"] == "agents-fragments"
    assert [fragment["path"] for fragment in prompt_prefix["fragments"]] == [
        ".agentmf/fragments/agents/review.task.md",
    ]
    assert "# review.task - Generic Coding Agents Target Fragment" in prompt_prefix["content"]
    assert "### base.task" in prompt_prefix["content"]
    assert "### review.task" in prompt_prefix["content"]
    assert "inspect_base" in prompt_prefix["content"]
    assert "review_code" in prompt_prefix["content"]
    assert "unrelated_only" not in prompt_prefix["content"]
    comparison = prompt_prefix["comparison"]
    assert comparison["linked"]["chars"] == len(prompt_prefix["content"])
    assert comparison["linked"]["approx_tokens"] == (len(prompt_prefix["content"]) + 3) // 4
    assert comparison["all_in_one"]["backend"] == "agents-md"
    assert comparison["all_in_one"]["path"] == "AGENTS.md"
    assert comparison["all_in_one"]["chars"] > comparison["linked"]["chars"]
    assert comparison["savings"]["chars"] == comparison["all_in_one"]["chars"] - comparison["linked"]["chars"]
    assert comparison["savings"]["approx_tokens"] == (
        comparison["all_in_one"]["approx_tokens"] - comparison["linked"]["approx_tokens"]
    )


def test_cli_run_dry_run_outputs_runtime_plan_json(tmp_path: Path, capsys) -> None:
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
            "run",
            "--file",
            str(path),
            "--request",
            "please review code",
            "--dry-run",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["runtime_plan"]["mode"] == "dry_run"
    assert payload["runtime_plan"]["link_plan"]["selected_targets"] == ["review.task"]
    assert payload["runtime_plan"]["target_contracts"][0]["steps"] == [{"action": "review_code"}]
    assert payload["runtime_plan"]["prompt_prefix"]["content"].startswith(
        "# review.task - Generic Coding Agents Target Fragment"
    )
    assert payload["runtime_plan"]["prompt_prefix"]["comparison"]["all_in_one"]["path"] == "AGENTS.md"
    assert payload["diagnostics"] == []


def test_cli_run_dry_run_accepts_permission_checks(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    steps:
      - action: review_code
permissions:
  defaults:
    bash: ask
  rules:
    bash:
      "git status": allow
""",
    )

    exit_code = main(
        [
            "run",
            "--file",
            str(path),
            "--target",
            "review.task",
            "--dry-run",
            "--permission-check",
            "bash:git status",
            "--permission-check",
            "bash:npm install",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["runtime_plan"]["permission_evaluation"]["tool_calls"] == [
        {
            "tool": "bash",
            "input": "git status",
            "action": "allow",
            "source": "rule",
            "matched_rules": [
                {"tool": "bash", "pattern": "git status", "action": "allow"}
            ],
        },
        {
            "tool": "bash",
            "input": "npm install",
            "action": "ask",
            "source": "default",
            "matched_rules": [],
        },
    ]


def test_exec_payload_requires_apply_before_tool_execution(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    steps:
      - action: review_code
permissions:
  rules:
    bash:
      "printf *": allow
""",
    )

    from agentmf.tool_loop import create_exec_payload

    result = create_exec_payload(
        path=path,
        target_names=["review.task"],
        tool_calls=[{"tool": "bash", "input": "printf hello"}],
        apply=False,
    )

    assert not result.ok
    assert result.payload == {}
    assert [
        (item.code, item.message, item.location, item.hint)
        for item in result.diagnostics.items
    ] == [
        (
            "AMF142",
            "tool execution requires --apply",
            "exec.apply",
            "rerun with --apply after reviewing the selected target, guards, and permission decisions",
        )
    ]


def test_exec_payload_runs_allowed_bash_and_blocks_non_allowed_calls(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    steps:
      - action: review_code
permissions:
  defaults:
    bash: ask
  rules:
    bash:
      "printf *": allow
      "rm -rf *": deny
""",
    )

    from agentmf.tool_loop import create_exec_payload

    result = create_exec_payload(
        path=path,
        target_names=["review.task"],
        tool_calls=[
            {"tool": "bash", "input": "printf hello"},
            {"tool": "bash", "input": "rm -rf /tmp/agentmf-demo"},
            {"tool": "bash", "input": "python3 -V"},
        ],
        apply=True,
        cwd=tmp_path,
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["version"] == 1
    assert result.payload["mode"] == "exec"
    assert result.payload["execution"] == {
        "enabled": True,
        "applied": True,
        "tool_loop": "prototype",
        "supported_tools": ["bash"],
    }
    assert result.payload["runtime_plan"]["permission_evaluation"]["tool_calls"] == [
        {
            "tool": "bash",
            "input": "printf hello",
            "action": "allow",
            "source": "rule",
            "matched_rules": [
                {"tool": "bash", "pattern": "printf *", "action": "allow"}
            ],
        },
        {
            "tool": "bash",
            "input": "rm -rf /tmp/agentmf-demo",
            "action": "deny",
            "source": "rule",
            "matched_rules": [
                {"tool": "bash", "pattern": "rm -rf *", "action": "deny"}
            ],
        },
        {
            "tool": "bash",
            "input": "python3 -V",
            "action": "ask",
            "source": "default",
            "matched_rules": [],
        },
    ]
    assert result.payload["tool_results"] == [
        {
            "tool": "bash",
            "input": "printf hello",
            "status": "executed",
            "exit_code": 0,
            "stdout": "hello",
            "stderr": "",
        },
        {
            "tool": "bash",
            "input": "rm -rf /tmp/agentmf-demo",
            "status": "blocked",
            "reason": "permission_deny",
            "permission_action": "deny",
        },
        {
            "tool": "bash",
            "input": "python3 -V",
            "status": "blocked",
            "reason": "permission_ask",
            "permission_action": "ask",
        },
    ]


def test_cli_exec_json_runs_allowed_tool_call(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    steps:
      - action: review_code
permissions:
  rules:
    bash:
      "printf *": allow
""",
    )

    exit_code = main(
        [
            "exec",
            "--file",
            str(path),
            "--target",
            "review.task",
            "--tool-call",
            "bash:printf cli-ok",
            "--apply",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["exec_payload"]["tool_results"] == [
        {
            "tool": "bash",
            "input": "printf cli-ok",
            "status": "executed",
            "exit_code": 0,
            "stdout": "cli-ok",
            "stderr": "",
        }
    ]


def test_cli_run_dry_run_text_reports_guard_evaluation(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    match:
      user_intent:
        - review code
    guards:
      - target_guard
    steps:
      - action: review_code
""",
    )

    exit_code = main(
        [
            "run",
            "--file",
            str(path),
            "--request",
            "please review code",
            "--dry-run",
            "--format",
            "text",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "guard evaluation: 1 planned, executed=False" in captured.out
    assert "guard: target review.task: target_guard" in captured.out


def test_prompt_payload_generates_final_prompt_from_stable_prefix_and_request(tmp_path: Path) -> None:
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

    from agentmf.prompt import create_prompt_payload

    result = create_prompt_payload(
        path=path,
        request="please review code",
        backend="agents-fragments",
    )

    assert result.ok, result.diagnostics.format()
    payload = result.payload
    assert payload["version"] == 1
    assert payload["mode"] == "prompt"
    assert payload["request"] == "please review code"
    assert payload["selected_targets"] == ["review.task"]
    assert payload["stable_prefix"]["backend"] == "agents-fragments"
    assert payload["stable_prefix"]["content"].startswith(
        "# review.task - Generic Coding Agents Target Fragment"
    )
    assert payload["volatile_context"] == {
        "request": "please review code",
        "plan": None,
        "git_status": None,
        "git_diff": None,
        "context_files": [],
    }
    assert payload["final_prompt"]["content"].startswith(payload["stable_prefix"]["content"])
    assert "## Volatile Task Context" in payload["final_prompt"]["content"]
    assert "### User Request" in payload["final_prompt"]["content"]
    assert "please review code" in payload["final_prompt"]["content"]
    assert payload["final_prompt"]["chars"] == len(payload["final_prompt"]["content"])
    assert payload["final_prompt"]["approx_tokens"] == (
        len(payload["final_prompt"]["content"]) + 3
    ) // 4
    assert payload["final_prompt"]["hash"] == (
        "sha256:" + hashlib.sha256(payload["final_prompt"]["content"].encode("utf-8")).hexdigest()
    )
    assert payload["trace"]["target_closure"] == ["review.task"]


def test_prompt_payload_stable_prefix_hash_ignores_request_text(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    steps:
      - action: review_code
""",
    )

    from agentmf.prompt import create_prompt_payload

    first = create_prompt_payload(path=path, target_names=["review.task"], request="first request")
    second = create_prompt_payload(path=path, target_names=["review.task"], request="second request")

    assert first.ok, first.diagnostics.format()
    assert second.ok, second.diagnostics.format()
    assert first.payload["stable_prefix"]["hash"] == second.payload["stable_prefix"]["hash"]
    assert first.payload["final_prompt"]["hash"] != second.payload["final_prompt"]["hash"]


def test_prompt_payload_includes_plan_as_volatile_context(tmp_path: Path) -> None:
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
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n\n- Add tests\n- Implement code\n", encoding="utf-8")

    from agentmf.prompt import create_prompt_payload

    result = create_prompt_payload(
        path=path,
        request="implement feature",
        plan_path=plan,
    )

    assert result.ok, result.diagnostics.format()
    payload = result.payload
    assert payload["volatile_context"]["plan"] == {
        "path": str(plan),
        "content": "# Plan\n\n- Add tests\n- Implement code\n",
    }
    assert "### Plan" in payload["final_prompt"]["content"]
    assert f"Source: `{plan}`" in payload["final_prompt"]["content"]
    assert "- Add tests" in payload["final_prompt"]["content"]


def test_prompt_payload_stable_prefix_hash_ignores_plan_text(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.change:
    steps:
      - action: edit_code
""",
    )
    plan_a = tmp_path / "plan-a.md"
    plan_b = tmp_path / "plan-b.md"
    plan_a.write_text("# Plan A\n\n- Add tests first\n", encoding="utf-8")
    plan_b.write_text("# Plan B\n\n- Add docs first\n", encoding="utf-8")

    from agentmf.prompt import create_prompt_payload

    first = create_prompt_payload(path=path, target_names=["code.change"], plan_path=plan_a)
    second = create_prompt_payload(path=path, target_names=["code.change"], plan_path=plan_b)

    assert first.ok, first.diagnostics.format()
    assert second.ok, second.diagnostics.format()
    assert first.payload["stable_prefix"]["hash"] == second.payload["stable_prefix"]["hash"]
    assert first.payload["final_prompt"]["hash"] != second.payload["final_prompt"]["hash"]


def test_prompt_payload_reads_context_file_as_volatile_context(tmp_path: Path) -> None:
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

    from agentmf.prompt import create_prompt_payload

    result = create_prompt_payload(
        path=path,
        target_names=["docs.task"],
        context_files=[context],
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["volatile_context"]["context_files"] == [
        {"path": str(context), "content": "Important context\n"}
    ]
    assert "### Context File" in result.payload["final_prompt"]["content"]
    assert f"Source: `{context}`" in result.payload["final_prompt"]["content"]
    assert "Important context" in result.payload["final_prompt"]["content"]


def test_prompt_payload_rejects_secret_context_file(tmp_path: Path) -> None:
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

    from agentmf.prompt import create_prompt_payload

    result = create_prompt_payload(
        path=path,
        target_names=["docs.task"],
        context_files=[secret],
    )

    assert not result.ok
    assert result.diagnostics.items[0].code == "AMF137"


def test_prompt_payload_collects_requested_git_context(tmp_path: Path) -> None:
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
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=AgentMakefile Tests",
            "-c",
            "user.email=agentmf-tests@example.com",
            "commit",
            "-m",
            "seed",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    tracked.write_text("after\n", encoding="utf-8")

    from agentmf.prompt import create_prompt_payload

    result = create_prompt_payload(
        path=path,
        target_names=["docs.task"],
        include_git_status=True,
        include_git_diff=True,
    )

    assert result.ok, result.diagnostics.format()
    assert " M tracked.txt" in result.payload["volatile_context"]["git_status"]
    assert "-before" in result.payload["volatile_context"]["git_diff"]
    assert "+after" in result.payload["volatile_context"]["git_diff"]
    assert "### Git Status" in result.payload["final_prompt"]["content"]
    assert "### Git Diff" in result.payload["final_prompt"]["content"]


def test_cli_prompt_outputs_json_payload(tmp_path: Path, capsys) -> None:
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
            "prompt",
            "--file",
            str(path),
            "please review code",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["prompt_payload"]["mode"] == "prompt"
    assert payload["prompt_payload"]["request"] == "please review code"
    assert payload["prompt_payload"]["selected_targets"] == ["review.task"]
    assert payload["prompt_payload"]["final_prompt"]["content"].startswith(
        "# review.task - Generic Coding Agents Target Fragment"
    )
    assert payload["diagnostics"] == []


def test_cli_prompt_accepts_plan_file(tmp_path: Path, capsys) -> None:
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
    plan = tmp_path / "plan.md"
    plan.write_text("# Plan\n\n- Add tests\n", encoding="utf-8")

    exit_code = main(
        [
            "prompt",
            "--file",
            str(path),
            "--request",
            "implement feature",
            "--plan",
            str(plan),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["prompt_payload"]["volatile_context"]["plan"] == {
        "path": str(plan),
        "content": "# Plan\n\n- Add tests\n",
    }
    assert "### Plan" in payload["prompt_payload"]["final_prompt"]["content"]


def test_cli_prompt_accepts_context_file(tmp_path: Path, capsys) -> None:
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

    exit_code = main(
        [
            "prompt",
            "--file",
            str(path),
            "--target",
            "docs.task",
            "--context-file",
            str(context),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["prompt_payload"]["volatile_context"]["context_files"] == [
        {"path": str(context), "content": "Important context\n"}
    ]


def test_cli_prompt_text_outputs_final_prompt(tmp_path: Path, capsys) -> None:
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
            "prompt",
            "--file",
            str(path),
            "--request",
            "please review code",
            "--format",
            "text",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.startswith("# review.task - Generic Coding Agents Target Fragment")
    assert "## Volatile Task Context" in captured.out
    assert "please review code" in captured.out


def test_cli_prompt_rejects_positional_and_flag_request(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    steps:
      - action: review_code
""",
    )

    exit_code = main(
        [
            "prompt",
            "--file",
            str(path),
            "positional request",
            "--request",
            "flag request",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "provide request either positionally or with --request, not both" in captured.err


def test_ask_payload_uses_echo_provider_with_prompt_payload(tmp_path: Path) -> None:
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

    from agentmf.ask import create_ask_payload

    result = create_ask_payload(
        path=path,
        request="please review code",
        provider="echo",
    )

    assert result.ok, result.diagnostics.format()
    payload = result.payload
    assert payload["version"] == 1
    assert payload["mode"] == "ask"
    assert payload["provider"] == "echo"
    assert payload["model"] == "echo-v1"
    assert payload["prompt_payload"]["selected_targets"] == ["review.task"]
    assert payload["prompt_payload"]["final_prompt"]["content"].startswith(
        "# review.task - Generic Coding Agents Target Fragment"
    )
    assert payload["response"]["provider"] == "echo"
    assert payload["response"]["model"] == "echo-v1"
    assert "Selected targets:" in payload["response"]["content"]
    assert "- review.task" in payload["response"]["content"]
    assert payload["prompt_payload"]["final_prompt"]["hash"] in payload["response"]["content"]


def test_ask_payload_rejects_unsupported_provider(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    steps:
      - action: review_code
""",
    )

    from agentmf.ask import create_ask_payload

    result = create_ask_payload(
        path=path,
        target_names=["review.task"],
        provider="openai",
    )

    assert not result.ok
    assert result.diagnostics.items[0].code == "AMF141"


def test_cli_ask_outputs_json_response(tmp_path: Path, capsys) -> None:
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
            "ask",
            "--file",
            str(path),
            "please review code",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["ask_payload"]["provider"] == "echo"
    assert payload["ask_payload"]["model"] == "echo-v1"
    assert payload["ask_payload"]["prompt_payload"]["selected_targets"] == ["review.task"]
    assert "- review.task" in payload["ask_payload"]["response"]["content"]


def test_cli_ask_text_prints_provider_response(tmp_path: Path, capsys) -> None:
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
            "ask",
            "--file",
            str(path),
            "--request",
            "please review code",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.startswith("Echo provider response")
    assert "- review.task" in captured.out


def test_cli_ask_reuses_prompt_context_options(tmp_path: Path, capsys) -> None:
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
    plan = tmp_path / "plan.md"
    context = tmp_path / "notes.md"
    plan.write_text("# Plan\n\n- Inspect docs\n", encoding="utf-8")
    context.write_text("Important context\n", encoding="utf-8")

    exit_code = main(
        [
            "ask",
            "--file",
            str(path),
            "--target",
            "docs.task",
            "--plan",
            str(plan),
            "--context-file",
            str(context),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    volatile_context = payload["ask_payload"]["prompt_payload"]["volatile_context"]
    assert volatile_context["plan"] == {
        "path": str(plan),
        "content": "# Plan\n\n- Inspect docs\n",
    }
    assert volatile_context["context_files"] == [
        {"path": str(context), "content": "Important context\n"}
    ]


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


def test_plugin_payload_collects_requested_git_context(tmp_path: Path) -> None:
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
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=AgentMakefile Tests",
            "-c",
            "user.email=agentmf-tests@example.com",
            "commit",
            "-m",
            "seed",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    tracked.write_text("after\n", encoding="utf-8")

    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=path,
        host="generic",
        target_names=["docs.task"],
        include_git_status=True,
        include_git_diff=True,
    )

    assert result.ok, result.diagnostics.format()
    assert " M tracked.txt" in result.payload["volatile_context"]["git_status"]
    assert "-before" in result.payload["volatile_context"]["git_diff"]
    assert "+after" in result.payload["volatile_context"]["git_diff"]


def test_cli_plugin_payload_accepts_plan_and_context_file(tmp_path: Path, capsys) -> None:
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
    plan = tmp_path / "plan.md"
    context = tmp_path / "notes.md"
    plan.write_text("# Plan\n\n- Inspect docs\n", encoding="utf-8")
    context.write_text("Important context\n", encoding="utf-8")

    exit_code = main(
        [
            "plugin",
            "payload",
            "--file",
            str(path),
            "--target",
            "docs.task",
            "--plan",
            str(plan),
            "--context-file",
            str(context),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["plugin_payload"]["volatile_context"]["plan"] == {
        "path": str(plan),
        "content": "# Plan\n\n- Inspect docs\n",
    }
    assert payload["plugin_payload"]["volatile_context"]["context_files"] == [
        {"path": str(context), "content": "Important context\n"}
    ]


def test_plugin_payload_uses_host_specific_instruction_profiles(tmp_path: Path) -> None:
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

    from agentmf.plugin import create_plugin_payload

    expected = {
        "generic": {
            "profile": "generic",
            "permissions_mode": "soft_guidance",
            "instruction_surface": "generic_prompt_payload",
            "native_artifacts": [],
        },
        "codex": {
            "profile": "codex",
            "permissions_mode": "host_enforced_when_supported",
            "instruction_surface": "AGENTS.md_or_plugin_payload",
            "native_artifacts": [],
        },
        "claude-code": {
            "profile": "claude-code",
            "permissions_mode": "host_enforced_when_supported",
            "instruction_surface": "CLAUDE.md_or_claude_code_hooks",
            "native_artifacts": [".claude/settings.json", ".claude/hooks/*"],
        },
        "cursor": {
            "profile": "cursor",
            "permissions_mode": "soft_guidance",
            "instruction_surface": ".cursor/rules_or_plugin_payload",
            "native_artifacts": [],
        },
        "opencode": {
            "profile": "opencode",
            "permissions_mode": "host_enforced_when_supported",
            "instruction_surface": "opencode.json_or_plugin_payload",
            "native_artifacts": ["opencode.json"],
        },
    }

    for host, expected_profile in expected.items():
        result = create_plugin_payload(path=path, host=host, target_names=["docs.task"])

        assert result.ok, result.diagnostics.format()
        host_instructions = result.payload["host_instructions"]
        assert host_instructions["injection"] == "prepend_stable_prefix_append_volatile_context"
        assert host_instructions["preferred_cache_boundary"] == "after_stable_prefix"
        for key, value in expected_profile.items():
            assert host_instructions[key] == value


def test_compile_cursor_rule_snapshot() -> None:
    result = compile_agentmakefile(KARPATHY_FIXTURE, targets=["cursor-rule"])

    assert result.ok, result.diagnostics.format()
    assert result.files[0].path == ".cursor/rules/karpathy-guidelines.mdc"
    assert_matches_snapshot(result.files[0].content, "karpathy.cursor.mdc")


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


def test_existing_unmanaged_shared_outputs_fail_without_force(tmp_path: Path) -> None:
    path = write_agentmakefile(tmp_path)
    out = tmp_path / "out"
    claude = out / "CLAUDE.md"
    agents = out / "AGENTS.md"
    out.mkdir()
    claude.write_text("human claude guidance\n")
    agents.write_text("human agents guidance\n")

    result = compile_agentmakefile(path, out_dir=out, targets=["claude-md", "agents-md"], write=True)

    assert not result.ok
    assert [item.code for item in result.diagnostics.items if item.severity == "error"] == ["AMF111", "AMF111"]
    assert claude.read_text() == "human claude guidance\n"
    assert agents.read_text() == "human agents guidance\n"
    assert result.wrote == []


def test_duplicate_managed_block_markers_are_rejected(tmp_path: Path) -> None:
    path = write_agentmakefile(tmp_path)
    out = tmp_path / "out"
    agents = out / "AGENTS.md"
    agents.parent.mkdir()
    original = (
        f"{BEGIN_MARKER}\nold one\n{END_MARKER}\n"
        f"{BEGIN_MARKER}\nold two\n{END_MARKER}\n"
    )
    agents.write_text(original)

    result = compile_agentmakefile(path, out_dir=out, targets=["agents-md"], write=True)

    assert not result.ok
    assert [item.code for item in result.diagnostics.items if item.severity == "error"] == ["AMF112"]
    assert agents.read_text() == original
    assert result.wrote == []


def test_cursor_rule_existing_file_requires_force(tmp_path: Path) -> None:
    path = write_agentmakefile(tmp_path)
    out = tmp_path / "out"
    cursor = out / ".cursor/rules/agentmakefile-generated.mdc"
    cursor.parent.mkdir(parents=True)
    cursor.write_text("human cursor rule\n")

    result = compile_agentmakefile(path, out_dir=out, targets=["cursor-rule"], write=True)

    assert not result.ok
    assert [item.code for item in result.diagnostics.items if item.severity == "error"] == ["AMF110"]
    assert cursor.read_text() == "human cursor rule\n"


def test_cursor_rule_existing_file_can_be_overwritten_with_force(tmp_path: Path) -> None:
    path = write_agentmakefile(tmp_path)
    out = tmp_path / "out"
    cursor = out / ".cursor/rules/agentmakefile-generated.mdc"
    cursor.parent.mkdir(parents=True)
    cursor.write_text("human cursor rule\n")

    result = compile_agentmakefile(path, out_dir=out, targets=["cursor-rule"], write=True, force=True)

    assert result.ok
    assert result.wrote == [cursor]
    assert "human cursor rule" not in cursor.read_text()
    assert "code.task" in cursor.read_text()


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
