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
ROOT_AGENTMAKEFILE = Path(__file__).parents[1] / "AgentMakefile"
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
RUNTIME_WALKTHROUGH_DEMO = DEMO_DIR / "runtime-walkthrough" / "AgentMakefile"
RUNTIME_WALKTHROUGH_VALID_OUTPUT = DEMO_DIR / "runtime-walkthrough" / "expected-output.valid.json"
RUNTIME_WALKTHROUGH_INVALID_OUTPUT = DEMO_DIR / "runtime-walkthrough" / "expected-output.invalid.json"
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
    assert "skills-index" in readme


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
        RUNTIME_WALKTHROUGH_DEMO,
    ]:
        source, diagnostics = load_source_with_diagnostics(path)

        assert source is not None, path
        assert not diagnostics.has_errors, diagnostics.format()


def test_superpowers_module_covers_installed_superpowers_skills() -> None:
    source = load_source(SUPERPOWERS_MODULE)

    assert set(source.skills) == SUPERPOWERS_SKILLS
    assert {skill.namespace for skill in source.skills.values()} == {"superpowers"}


def test_superpowers_module_routes_skill_intents_through_bootstrap() -> None:
    cases = [
        ("write an implementation plan", "methodology.plan"),
        ("implement this feature", "methodology.code_change"),
        ("debug a failing test", "methodology.debug"),
        ("review this change", "methodology.review"),
        ("execute this written plan", "methodology.execute_plan"),
        ("create a skill", "methodology.skill_authoring"),
    ]

    for request, expected_target in cases:
        result = create_link_plan(SUPERPOWERS_MODULE, request=request)

        assert result.ok, result.diagnostics.format()
        assert result.plan["selected_targets"] == [expected_target]
        assert result.plan["target_closure"][0] == "methodology.bootstrap"


def test_link_plan_explains_request_selection_candidates(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.task:
    priority: 90
    match:
      user_intent:
        - implement feature
    steps:
      - action: write_code
  docs.task:
    priority: 80
    match:
      user_intent:
        - feature
    steps:
      - action: inspect_docs
  generic.task:
    priority: 50
    match:
      user_intent:
        - implement
    steps:
      - action: generic_work
""",
    )

    result = create_link_plan(path, request="please implement feature")

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["code.task"]
    assert result.plan["selection_trace"] == {
        "mode": "request",
        "algorithm": "normalize_translate_semantic_priority_score_term-length_name",
        "request": "please implement feature",
        "normalized_request": "please implement feature",
        "expanded_request_terms": ["please", "implement", "feature", "implement this feature"],
        "requested_targets": [],
        "selected": {
            "target": "code.task",
            "priority": 90,
            "matched_terms": ["implement feature"],
            "match_details": [
                {
                    "term": "implement feature",
                    "method": "substring",
                    "score": 100,
                    "evidence": "implement feature",
                }
            ],
            "match_score": 100,
            "dependency_closure": ["code.task"],
        },
        "candidates": [
            {
                "rank": 1,
                "target": "code.task",
                "priority": 90,
                "matched_terms": ["implement feature"],
                "match_details": [
                    {
                        "term": "implement feature",
                        "method": "substring",
                        "score": 100,
                        "evidence": "implement feature",
                    }
                ],
                "match_score": 100,
                "selected": True,
                "reason": "matched request substring(s)",
            },
            {
                "rank": 2,
                "target": "docs.task",
                "priority": 80,
                "matched_terms": ["feature"],
                "match_details": [
                    {
                        "term": "feature",
                        "method": "substring",
                        "score": 100,
                        "evidence": "feature",
                    }
                ],
                "match_score": 100,
                "selected": False,
                "reason": "matched request substring(s)",
            },
            {
                "rank": 3,
                "target": "generic.task",
                "priority": 50,
                "matched_terms": ["implement"],
                "match_details": [
                    {
                        "term": "implement",
                        "method": "substring",
                        "score": 100,
                        "evidence": "implement",
                    }
                ],
                "match_score": 100,
                "selected": False,
                "reason": "matched request substring(s)",
            },
        ],
    }


def test_link_plan_matches_normalized_hyphenated_terms(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.test-driven-development:
    priority: 70
    match:
      user_intent:
        - test-driven-development
    steps:
      - action: use_tdd
""",
    )

    result = create_link_plan(path, request="use test driven development")

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["skill.test-driven-development"]
    assert result.plan["selection_trace"]["selected"]["match_details"] == [
        {
            "term": "test-driven-development",
            "method": "normalized_substring",
            "score": 95,
            "evidence": "test driven development",
        }
    ]


def test_link_plan_ignores_single_character_match_terms(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.security-scan:
    priority: 80
    match:
      user_intent:
        - security scan
    steps:
      - action: scan
  skill.figma:
    priority: 90
    match:
      user_intent:
        - g
    steps:
      - action: design
  skill.runner:
    priority: 90
    match:
      user_intent:
        - run
    steps:
      - action: run
""",
    )

    result = create_link_plan(path, request="run a full security scan and validate findings")

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["skill.security-scan"]
    candidate_targets = [
        candidate["target"] for candidate in result.plan["selection_trace"]["candidates"]
    ]
    assert "skill.figma" not in candidate_targets
    assert "skill.runner" not in candidate_targets


def test_link_plan_translates_chinese_request_to_skill_intent(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.using-superpowers:
    priority: 95
    match:
      user_intent:
        - use superpowers
    steps:
      - action: bootstrap
  skill.test-driven-development:
    priority: 70
    deps:
      - skill.using-superpowers
    match:
      user_intent:
        - implement this feature
    steps:
      - action: use_tdd
  skill.skill-installer:
    priority: 70
    deps:
      - skill.using-superpowers
    match:
      user_intent:
        - install a curated skill
    steps:
      - action: install_skill
""",
    )

    implement_result = create_link_plan(path, request="请实现这个功能")
    install_result = create_link_plan(path, request="安装一个技能")

    assert implement_result.ok, implement_result.diagnostics.format()
    assert implement_result.plan["selected_targets"] == ["skill.test-driven-development"]
    assert implement_result.plan["target_closure"] == [
        "skill.using-superpowers",
        "skill.test-driven-development",
    ]
    assert implement_result.plan["selection_trace"]["selected"]["match_details"] == [
        {
            "term": "implement this feature",
            "method": "translated_substring",
            "score": 90,
            "evidence": "implement this feature",
        }
    ]

    assert install_result.ok, install_result.diagnostics.format()
    assert install_result.plan["selected_targets"] == ["skill.skill-installer"]
    assert install_result.plan["selection_trace"]["selected"]["match_details"] == [
        {
            "term": "install a curated skill",
            "method": "semantic_token_overlap",
            "score": 60,
            "evidence": "install skill",
        }
    ]


def test_link_plan_semantically_matches_related_english_terms(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.verification-before-completion:
    priority: 70
    match:
      user_intent:
        - about to claim work is complete
    steps:
      - action: verify
""",
    )

    result = create_link_plan(path, request="finish task")

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["skill.verification-before-completion"]
    assert result.plan["selection_trace"]["selected"]["match_details"] == [
        {
            "term": "about to claim work is complete",
            "method": "semantic_token_overlap",
            "score": 60,
            "evidence": "complete task",
        }
    ]


def test_link_plan_alternatives_prefer_dep_proximity_on_score_ties(tmp_path: Path) -> None:
    """When two matcher-scored alternative targets tie on score, the one
    that depends on the selected target (i.e. would extend the selected
    pipeline rather than replace it) ranks ahead. This pulls Makefile-style
    causal adjacency into routing-relevance signal.
    """
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.foundation:
    match:
      user_intent:
        - foo handler request
    steps:
      - inspect
  skill.afar:
    match:
      user_intent:
        - request
    steps:
      - inspect
  skill.zextends:
    match:
      user_intent:
        - request
    deps:
      - skill.foundation
    steps:
      - inspect
""",
    )

    result = create_link_plan(path, request="foo handler request", n_best=3)

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["skill.foundation"]
    alt_targets = [entry["target"] for entry in result.plan["alternatives"]]
    # afar and zextends both match "request" at score 100. Without proximity
    # boosting, alphabetical (afar < zextends) puts afar first. With
    # proximity boosting, zextends wins because skill.foundation appears in
    # its deps — zextends is causally adjacent to the selected target.
    assert alt_targets == ["skill.zextends", "skill.afar"]


def test_link_plan_prepends_declared_fallback_targets_to_alternatives(tmp_path: Path) -> None:
    """Targets declared via `target.fallback` are author-curated alternatives
    and should appear in `plan.alternatives` BEFORE matcher-scored ones,
    because they encode intent (Makefile-style dep info) rather than
    surface-text scoring. Existing matcher-scored candidates that name the
    same target are deduped — declared entry wins."""
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.alpha:
    match:
      user_intent:
        - foo handler request
    fallback:
      runtime:
        - skill.beta
    steps:
      - inspect
  skill.beta:
    match:
      user_intent:
        - foo
    steps:
      - inspect
  skill.gamma:
    match:
      user_intent:
        - request
    steps:
      - inspect
""",
    )

    result = create_link_plan(path, request="foo handler request", n_best=3)

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["skill.alpha"]
    alternatives = result.plan["alternatives"]
    alt_targets = [entry["target"] for entry in alternatives]
    # Declared fallback (beta) takes slot 0 even though gamma scores higher
    # on the matcher; matcher-scored candidate fills slot 1.
    assert alt_targets[:2] == ["skill.beta", "skill.gamma"]
    assert alternatives[0]["source"] == "declared_fallback"
    assert alternatives[0]["condition"] == "runtime"
    assert alternatives[1]["source"] == "matcher_score"


def test_link_plan_dedupes_when_fallback_target_also_scored(tmp_path: Path) -> None:
    """A target that's both declared as fallback AND ranked by the matcher
    appears once in alternatives, sourced as `declared_fallback`."""
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.alpha:
    match:
      user_intent:
        - foo handler request
    fallback:
      runtime:
        - skill.beta
    steps:
      - inspect
  skill.beta:
    match:
      user_intent:
        - foo
    steps:
      - inspect
""",
    )

    result = create_link_plan(path, request="foo handler request", n_best=3)

    assert result.ok, result.diagnostics.format()
    alt_targets = [entry["target"] for entry in result.plan["alternatives"]]
    # beta is the only alternative; appears once, attributed to fallback.
    assert alt_targets == ["skill.beta"]
    assert result.plan["alternatives"][0]["source"] == "declared_fallback"


def test_link_plan_exposes_n_best_alternatives(tmp_path: Path) -> None:
    """The selector exposes the non-selected ranked candidates as a compact
    `alternatives` field, so downstream agents/prompts can see what else
    could have routed without changing the deterministic selected_targets.
    """
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.alpha:
    priority: 70
    match:
      user_intent:
        - create a presentation about Q4 results
    steps:
      - action: handle_alpha
  skill.beta:
    priority: 70
    match:
      user_intent:
        - presentation
    steps:
      - action: handle_beta
  skill.gamma:
    priority: 70
    match:
      user_intent:
        - Q4
    steps:
      - action: handle_gamma
""",
    )

    result = create_link_plan(path, request="create a presentation about Q4 results", n_best=3)

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["skill.alpha"]
    alternatives = result.plan["alternatives"]
    # n_best=3 means top-3 overall; with the selected (alpha) removed,
    # alternatives must include the next 2 candidates ranked by score
    # then term-length then name.
    alt_names = [entry["target"] for entry in alternatives]
    assert alt_names == ["skill.beta", "skill.gamma"]
    # Each alternative must carry rank, target, source, score and the term
    # that hit. rank is the position within the alternatives list (1-based);
    # the selected target is not in this list and does not consume a rank.
    assert {"rank", "target", "source", "match_score", "matched_terms", "reason"} <= set(alternatives[0].keys())
    assert alternatives[0]["rank"] == 1
    assert alternatives[1]["rank"] == 2
    assert alternatives[0]["source"] == "matcher_score"


def test_link_plan_alternatives_default_to_top_three(tmp_path: Path) -> None:
    """Default n_best=3 truncates the alternatives list even when more
    candidates match (we surface the top 2 alternatives beneath the
    selected one — total 3 visible candidates)."""
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.a1:
    match: {user_intent: [create]}
    steps:
      - inspect
  skill.a2:
    match: {user_intent: [create]}
    steps:
      - inspect
  skill.a3:
    match: {user_intent: [create]}
    steps:
      - inspect
  skill.a4:
    match: {user_intent: [create]}
    steps:
      - inspect
  skill.a5:
    match: {user_intent: [create]}
    steps:
      - inspect
""",
    )

    result = create_link_plan(path, request="create something")

    assert result.ok, result.diagnostics.format()
    # 5 targets all match identically; default n_best=3 keeps 2 alternatives
    # below the top-1 selected.
    assert len(result.plan["alternatives"]) == 2


def test_link_plan_breaks_score_ties_by_longer_matched_term(tmp_path: Path) -> None:
    """When two targets match a request at the same max score, the target
    whose matched term is longer wins. Without this rule, a single broad
    word like `Create` always beats a specific phrase like `create a
    presentation about Q4 results` because both produce substring score
    100 and name-alphabetical (`broad` < `specific`) breaks the tie the
    wrong way — which is the exact failure mode the missing_match_terms
    detector's add_terms cannot fix on its own.
    """
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.docs.broad:
    priority: 70
    match:
      user_intent:
        - Create
    steps:
      - action: handle_docs
  skill.docs.specific:
    priority: 70
    match:
      user_intent:
        - create a presentation about Q4 results
    steps:
      - action: handle_presentation
""",
    )

    result = create_link_plan(path, request="create a presentation about Q4 results")

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["skill.docs.specific"]


def test_link_plan_prefers_verification_for_completion_reports(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.finishing-a-development-branch:
    priority: 70
    match:
      user_intent:
        - finish a development branch
        - implementation is complete
    steps:
      - action: finish_branch
  skill.verification-before-completion:
    priority: 70
    match:
      user_intent:
        - about to claim work is complete
    steps:
      - action: verify
""",
    )

    result = create_link_plan(path, request="finish task and report completion")

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["skill.verification-before-completion"]
    assert result.plan["selection_trace"]["selected"]["match_details"][0] == {
        "term": "about to claim work is complete",
        "method": "translated_substring",
        "score": 90,
        "evidence": "about to claim work is complete",
    }


def test_superpowers_plugin_payload_selects_bootstrap_and_workflow_skills() -> None:
    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=SUPERPOWERS_MODULE,
        host="codex",
        request="implement this feature",
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["selected_targets"] == ["methodology.code_change"]
    assert result.payload["selected_skills"] == [
        "superpowers:using-superpowers",
        "superpowers:verification-before-completion",
        "superpowers:test-driven-development",
    ]
    selected = result.payload["selection_trace"]["selected"]
    assert selected["target"] == "methodology.code_change"
    assert selected["priority"] == 90
    assert selected["matched_terms"][0] == "implement this feature"
    assert selected["match_details"][0] == {
        "term": "implement this feature",
        "method": "substring",
        "score": 100,
        "evidence": "implement this feature",
    }
    assert selected["dependency_closure"] == ["methodology.bootstrap", "methodology.code_change"]


def test_root_agentmakefile_absorbs_superpowers_and_omo_routing() -> None:
    from agentmf.plugin import create_plugin_payload

    superpowers_result = create_plugin_payload(
        path=ROOT_AGENTMAKEFILE,
        host="codex",
        request="implement this feature",
    )
    omo_result = create_plugin_payload(
        path=ROOT_AGENTMAKEFILE,
        host="codex",
        request="autonomous implementation",
    )
    spec_breakdown_result = create_plugin_payload(
        path=ROOT_AGENTMAKEFILE,
        host="codex",
        request="break down the spec into tasks",
    )

    assert superpowers_result.ok, superpowers_result.diagnostics.format()
    assert omo_result.ok, omo_result.diagnostics.format()
    assert spec_breakdown_result.ok, spec_breakdown_result.diagnostics.format()
    assert superpowers_result.payload["selected_targets"] == ["methodology.code_change"]
    assert "superpowers:test-driven-development" in superpowers_result.payload["selected_skills"]
    assert omo_result.payload["selected_targets"] == ["omo.ultrawork"]
    assert omo_result.payload["selected_skills"] == [
        "omo:ultrawork",
        "omo:category-routing",
    ]
    assert spec_breakdown_result.payload["selected_targets"] == ["spec.breakdown"]


def test_link_plan_derives_target_match_from_referenced_skill_match() -> None:
    result = create_link_plan(
        OH_MY_OPENAGENT_MODULE,
        request="autonomous implementation",
    )

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["omo.ultrawork"]
    selected = result.plan["selection_trace"]["selected"]
    assert selected["matched_terms"] == ["autonomous implementation"]
    assert selected["match_details"] == [
        {
            "term": "autonomous implementation",
            "method": "substring",
            "score": 100,
            "evidence": "autonomous implementation",
            "source": "skill:omo:ultrawork",
        }
    ]


def test_plugin_payload_uses_skill_match_derived_target_routing() -> None:
    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=OH_MY_OPENAGENT_MODULE,
        host="codex",
        request="autonomous implementation",
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["selected_targets"] == ["omo.ultrawork"]
    assert result.payload["selected_skills"] == [
        "omo:ultrawork",
        "omo:category-routing",
    ]
    assert result.payload["selection_trace"]["selected"]["match_details"][0]["source"] == (
        "skill:omo:ultrawork"
    )


def test_omo_module_routes_consultation_and_category_requests_to_specific_targets() -> None:
    cases = [
        ("architecture review", "omo.research"),
        ("choose category model matching", "omo.category_routing"),
    ]

    for request, expected_target in cases:
        result = create_link_plan(OH_MY_OPENAGENT_MODULE, request=request)

        assert result.ok, result.diagnostics.format()
        assert result.plan["selected_targets"] == [expected_target]


def test_scan_skills_directory_generates_agentmakefile_with_bootstrap_dependency(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _write_skill(
        skills_dir,
        "using-superpowers",
        "Use when starting any development task and choosing the relevant skill.",
        "## When to Use\n\n- Any development task\n- Choose workflow\n",
    )
    _write_skill(
        skills_dir,
        "test-driven-development",
        "Use when implementing any feature or bugfix, before writing implementation code.",
        "## When to Use\n\n- New features\n- Bug fixes\n- Refactoring\n- Behavior changes\n",
    )

    from agentmf.skill_scanner import render_agentmakefile_from_skill_dirs

    content = render_agentmakefile_from_skill_dirs(
        [skills_dir],
        namespace="superpowers",
        package_name="scanned-superpowers",
        package_description="Scanned Superpowers skills.",
        bootstrap_skill="using-superpowers",
    )
    agentmakefile = tmp_path / "AgentMakefile"
    agentmakefile.write_text(content)

    source = load_source(agentmakefile)
    result = create_link_plan(agentmakefile, request="implement this feature")

    assert set(source.skills) == {"using-superpowers", "test-driven-development"}
    assert {skill.namespace for skill in source.skills.values()} == {"superpowers"}
    assert source.targets["skill.test-driven-development"].deps == ["skill.using-superpowers"]
    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["skill.test-driven-development"]
    assert result.plan["target_closure"] == [
        "skill.using-superpowers",
        "skill.test-driven-development",
    ]
    scanned_target = source.targets["skill.test-driven-development"]
    assert scanned_target.steps == [
        {"use_skill": "superpowers:test-driven-development"},
        {"link_prompt": {"source": str(skills_dir / "test-driven-development" / "SKILL.md")}},
    ]


def test_guidance_scan_generates_pipeline_targets_from_markdown_sections(tmp_path: Path) -> None:
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(
        """\
# Project Guidance

## Review

Review code carefully and report findings first.
""",
    )

    from agentmf.guidance_scanner import render_agentmakefile_from_guidance_files

    content = render_agentmakefile_from_guidance_files(
        [agents_md],
        package_name="imported-guidance",
    )
    agentmakefile = tmp_path / "ImportedAgentMakefile"
    agentmakefile.write_text(content)
    source = load_source(agentmakefile)
    result = create_link_plan(agentmakefile, request="review code")

    assert source.metadata["module_type"] == "guidance-index"
    assert "guidance.agents.review" in source.targets
    target = source.targets["guidance.agents.review"]
    assert target.steps == [
        {"link_prompt": {"source": f"{agents_md}#Review"}},
        {"apply_policy": {"source": "imported"}},
    ]
    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["guidance.agents.review"]
    pipeline = result.plan["target_pipelines"][0]
    assert pipeline["prompt_ops"] == [
        {
            "type": "link_prompt",
            "source": "target",
            "payload": {"source": f"{agents_md}#Review"},
            "raw": {"link_prompt": {"source": f"{agents_md}#Review"}},
        },
        {
            "type": "apply_policy",
            "source": "target",
            "payload": {"source": "imported"},
            "raw": {"apply_policy": {"source": "imported"}},
        },
    ]


def test_cli_skills_scan_writes_valid_agentmakefile_for_plugin_skill_selection(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _write_skill(
        skills_dir,
        "using-superpowers",
        "Use when starting any development task and choosing the relevant skill.",
        "## When to Use\n\n- Any development task\n- Choose workflow\n",
    )
    _write_skill(
        skills_dir,
        "writing-plans",
        "Use when you have a spec or requirements for a multi-step task, before touching code.",
        "## When to Use\n\n- Implementation plans\n- Break down specs\n",
    )
    agentmakefile = tmp_path / "GeneratedAgentMakefile"

    exit_code = main(
        [
            "skills",
            "scan",
            "--skills-dir",
            str(skills_dir),
            "--namespace",
            "superpowers",
            "--package-name",
            "scanned-superpowers",
            "--bootstrap-skill",
            "using-superpowers",
            "--out",
            str(agentmakefile),
            "--write",
        ]
    )

    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=agentmakefile,
        host="codex",
        request="write an implementation plan",
    )

    assert exit_code == 0
    assert result.ok, result.diagnostics.format()
    assert result.payload["selected_targets"] == ["skill.writing-plans"]
    assert result.payload["selected_skills"] == [
        "superpowers:using-superpowers",
        "superpowers:writing-plans",
    ]


def test_plugin_install_scans_skills_and_instructs_model_to_use_payload(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _write_skill(
        skills_dir,
        "using-superpowers",
        "Use when starting any development task and choosing the relevant skill.",
        "## When to Use\n\n- Any development task\n- Choose workflow\n",
    )
    _write_skill(
        skills_dir,
        "test-driven-development",
        "Use when implementing any feature or bugfix, before writing implementation code.",
        "## When to Use\n\n- New features\n- Bug fixes\n",
    )
    agentmakefile = tmp_path / ".agentmf" / "plugin" / "AgentMakefile"

    from agentmf.plugin import create_plugin_payload
    from agentmf.plugin_install import create_plugin_install_payload

    install = create_plugin_install_payload(
        skill_dirs=[skills_dir],
        host="codex",
        namespace="superpowers",
        package_name="scanned-superpowers",
        bootstrap_skill="using-superpowers",
        out_path=agentmakefile,
        write=True,
    )

    assert install.ok, install.diagnostics.format()
    assert agentmakefile.exists()
    assert install.payload["agentmakefile"]["path"] == str(agentmakefile)
    assert install.payload["agentmakefile"]["wrote"] is True
    assert "agentmf plugin payload" in install.payload["model_instructions"]
    assert "--file" in install.payload["next_payload_command"]
    assert str(agentmakefile) in install.payload["next_payload_command"]

    selected = create_plugin_payload(
        path=agentmakefile,
        host="codex",
        request="implement this feature",
    )

    assert selected.ok, selected.diagnostics.format()
    assert selected.payload["selected_targets"] == ["skill.test-driven-development"]
    assert selected.payload["selected_skills"] == [
        "superpowers:using-superpowers",
        "superpowers:test-driven-development",
    ]


def test_cli_plugin_install_outputs_json_model_instruction(tmp_path: Path, capsys) -> None:
    skills_dir = tmp_path / "skills"
    _write_skill(
        skills_dir,
        "using-superpowers",
        "Use when starting any development task and choosing the relevant skill.",
        "## When to Use\n\n- Any development task\n",
    )
    _write_skill(
        skills_dir,
        "writing-plans",
        "Use when you have a spec or requirements for a multi-step task, before touching code.",
        "## When to Use\n\n- Implementation plans\n- Break down specs\n",
    )
    agentmakefile = tmp_path / "PluginAgentMakefile"

    exit_code = main(
        [
            "plugin",
            "install",
            "--skills-dir",
            str(skills_dir),
            "--host",
            "codex",
            "--namespace",
            "superpowers",
            "--package-name",
            "scanned-superpowers",
            "--bootstrap-skill",
            "using-superpowers",
            "--out",
            str(agentmakefile),
            "--write",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    install_payload = payload["plugin_install_payload"]

    assert exit_code == 0
    assert payload["ok"] is True
    assert agentmakefile.exists()
    assert install_payload["host"] == "codex"
    assert install_payload["agentmakefile"]["path"] == str(agentmakefile)
    assert "agentmf plugin payload" in install_payload["model_instructions"]
    assert "selected_skills" in install_payload["model_instructions"]
    assert "selection_trace" in install_payload["model_instructions"]


def test_skill_sync_plans_codex_skill_install_without_writing(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  local-review:
    description: Review local changes.
    match:
      user_intent:
        - review
""",
    )
    skill_root = tmp_path / "codex-skills"

    from agentmf.skill_sync import create_skill_sync_payload

    result = create_skill_sync_payload(
        path=path,
        host="codex",
        out_dir=skill_root,
        write=False,
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["host"] == "codex"
    assert result.payload["backend"] == "codex-skill"
    assert result.payload["skill_root"] == str(skill_root)
    assert result.payload["files"] == [
        {
            "source_path": ".codex/skills/local-review/SKILL.md",
            "destination": str(skill_root / "local-review" / "SKILL.md"),
            "status": "planned",
        }
    ]
    assert "agentmf plugin payload" in result.payload["host_integration_instructions"]
    assert not (skill_root / "local-review" / "SKILL.md").exists()


def test_skill_sync_writes_and_refuses_overwrite_without_force(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  local-review:
    description: Review local changes.
""",
    )
    skill_root = tmp_path / "codex-skills"

    from agentmf.skill_sync import create_skill_sync_payload

    first = create_skill_sync_payload(
        path=path,
        host="codex",
        out_dir=skill_root,
        write=True,
    )

    installed = skill_root / "local-review" / "SKILL.md"
    assert first.ok, first.diagnostics.format()
    assert installed.exists()
    assert first.payload["files"][0]["status"] == "wrote"

    installed.write_text("manual edit\n", encoding="utf-8")
    blocked = create_skill_sync_payload(
        path=path,
        host="codex",
        out_dir=skill_root,
        write=True,
    )

    assert not blocked.ok
    assert blocked.diagnostics.to_list()[0]["code"] == "AMF140"
    assert installed.read_text(encoding="utf-8") == "manual edit\n"

    forced = create_skill_sync_payload(
        path=path,
        host="codex",
        out_dir=skill_root,
        write=True,
        force=True,
    )

    assert forced.ok, forced.diagnostics.format()
    assert forced.payload["files"][0]["status"] == "wrote"
    assert "manual edit" not in installed.read_text(encoding="utf-8")


def test_cli_skills_sync_outputs_json_host_integration_instructions(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  local-review:
    description: Review local changes.
""",
    )
    skill_root = tmp_path / "claude-skills"

    exit_code = main(
        [
            "skills",
            "sync",
            "--file",
            str(path),
            "--host",
            "claude-code",
            "--out-dir",
            str(skill_root),
            "--write",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    sync_payload = payload["skill_sync_payload"]

    assert exit_code == 0
    assert payload["ok"] is True
    assert sync_payload["backend"] == "claude-skill"
    assert sync_payload["files"][0]["destination"] == str(skill_root / "local-review" / "SKILL.md")
    assert "selected_skills" in sync_payload["host_integration_instructions"]
    assert (skill_root / "local-review" / "SKILL.md").exists()


def test_skill_scan_keeps_feature_implementation_from_routing_to_review_skill(tmp_path: Path) -> None:
    skills_dir = tmp_path / "skills"
    _write_skill(
        skills_dir,
        "using-superpowers",
        "Use when starting any development task and choosing the relevant skill.",
        "## When to Use\n\n- Any development task\n",
    )
    _write_skill(
        skills_dir,
        "test-driven-development",
        "Use when implementing any feature or bugfix, before writing implementation code.",
        "## When to Use\n\n- New features\n- Bug fixes\n",
    )
    _write_skill(
        skills_dir,
        "requesting-code-review",
        "Use when completing tasks, implementing major features, or before merging to verify work meets requirements.",
        "## When to Use\n\n- Request review\n- Code review\n",
    )

    from agentmf.skill_scanner import render_agentmakefile_from_skill_dirs

    agentmakefile = tmp_path / "AgentMakefile"
    agentmakefile.write_text(
        render_agentmakefile_from_skill_dirs(
            [skills_dir],
            namespace="superpowers",
            package_name="scanned-superpowers",
            bootstrap_skill="using-superpowers",
        )
    )

    result = create_link_plan(agentmakefile, request="implement this feature")

    assert result.ok, result.diagnostics.format()
    assert result.plan["selected_targets"] == ["skill.test-driven-development"]


def test_openclaw_import_writes_category_modules_and_root_index(tmp_path: Path) -> None:
    skills_dir = tmp_path / "openclaw-skills"
    _write_openclaw_skill(
        skills_dir,
        "coding/code-review",
        "code-review",
        "Use when reviewing code and patches.",
        "coding",
        ["review", "code"],
        "## When to Use\n\n- Review code\n- Inspect patches\n",
    )
    _write_openclaw_skill(
        skills_dir,
        "research/web-research",
        "web-research",
        "Use when researching external context.",
        "research",
        ["research"],
        "## When to Use\n\n- Research topic\n- External context\n",
    )
    out_dir = tmp_path / "modules" / "openclaw"

    from agentmf.openclaw import create_openclaw_import_payload

    result = create_openclaw_import_payload(
        skill_dirs=[skills_dir],
        out_dir=out_dir,
        namespace="openclaw",
        package_name="openclaw-skills",
        write=True,
    )

    root_path = out_dir / "AgentMakefile"
    coding_path = out_dir / "coding" / "AgentMakefile"
    research_path = out_dir / "research" / "AgentMakefile"
    root_data = yaml.safe_load(root_path.read_text())
    coding_source = load_source(coding_path)
    link_result = create_link_plan(root_path, request="review code")

    assert result.ok, result.diagnostics.format()
    assert root_path.exists()
    assert coding_path.exists()
    assert research_path.exists()
    assert root_data["metadata"]["module_type"] == "openclaw-skill-root"
    assert root_data["include"] == ["coding/AgentMakefile", "research/AgentMakefile"]
    assert coding_source.metadata["module_type"] == "openclaw-skill-category"
    assert coding_source.metadata["category"] == "coding"
    assert "coding.code-review" in coding_source.skills
    assert link_result.ok, link_result.diagnostics.format()
    assert link_result.plan["selected_targets"] == ["skill.coding.code-review"]


def test_openclaw_import_exports_curator_evidence_for_duplicates(tmp_path: Path) -> None:
    skills_dir = tmp_path / "openclaw-skills"
    _write_openclaw_skill(
        skills_dir,
        "coding/review",
        "review",
        "Use when reviewing code.",
        "coding",
        ["review"],
        "## When to Use\n\n- Review code\n",
    )
    _write_openclaw_skill(
        skills_dir,
        "docs/review",
        "review",
        "Use when reviewing docs.",
        "docs",
        ["review", "docs"],
        "## When to Use\n\n- Review docs\n",
    )
    _write_openclaw_skill(
        skills_dir,
        "coding/review-alt",
        "review",
        "Use when reviewing alternate code paths.",
        "coding",
        ["review", "code"],
        "## When to Use\n\n- Review code paths\n",
    )

    from agentmf.openclaw import create_openclaw_import_payload

    result = create_openclaw_import_payload(
        skill_dirs=[skills_dir],
        out_dir=tmp_path / "modules" / "openclaw",
        namespace="openclaw",
        package_name="openclaw-skills",
        write=False,
    )

    evidence = result.payload["curator_evidence"]

    assert result.ok, result.diagnostics.format()
    coding_data = yaml.safe_load(result.payload["modules"]["coding/AgentMakefile"])

    assert evidence["skill_count"] == 3
    assert evidence["category_count"] == 2
    assert evidence["categories"] == {"coding": 2, "docs": 1}
    assert evidence["duplicate_original_names"]["review"] == [
        "coding/review/SKILL.md",
        "coding/review-alt/SKILL.md",
        "docs/review/SKILL.md",
    ]
    assert set(coding_data["skills"]) == {"coding.review", "coding.review-2"}
    assert "coding/AgentMakefile" in evidence["module_paths"]
    assert "docs/AgentMakefile" in evidence["module_paths"]


def test_openclaw_import_tolerates_invalid_yaml_frontmatter(tmp_path: Path) -> None:
    skills_dir = tmp_path / "openclaw-skills"
    bad_dir = skills_dir / "discord"
    bad_dir.mkdir(parents=True)
    (bad_dir / "SKILL.md").write_text(
        "---\n"
        "name: discord\n"
        "description: Use when controlling Discord: send messages, react, post or pin.\n"
        "---\n\n"
        "# Discord\n\nbody\n"
    )

    from agentmf.openclaw import create_openclaw_import_payload

    result = create_openclaw_import_payload(
        skill_dirs=[skills_dir],
        out_dir=tmp_path / "modules" / "openclaw",
        namespace="openclaw",
        package_name="openclaw-skills",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["skill_count"] == 1
    category = result.payload["categories"][0]["name"]
    assert category == "uncategorized"


def test_cli_openclaw_scan_writes_modular_agentmakefiles_and_json_payload(
    tmp_path: Path, capsys
) -> None:
    skills_dir = tmp_path / "openclaw-skills"
    _write_openclaw_skill(
        skills_dir,
        "coding/test-first",
        "test-first",
        "Use when implementing with tests first.",
        "coding",
        ["tdd", "implementation"],
        "## When to Use\n\n- Implement feature\n- Bug fixes\n",
    )
    out_dir = tmp_path / "modules" / "openclaw"

    exit_code = main(
        [
            "openclaw",
            "scan",
            "--skills-dir",
            str(skills_dir),
            "--namespace",
            "openclaw",
            "--package-name",
            "openclaw-skills",
            "--out",
            str(out_dir),
            "--write",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    link_result = create_link_plan(out_dir / "AgentMakefile", request="implement feature")

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["openclaw_import"]["wrote"] is True
    assert payload["openclaw_import"]["root_path"] == str(out_dir / "AgentMakefile")
    assert (out_dir / "coding" / "AgentMakefile").exists()
    assert link_result.ok, link_result.diagnostics.format()
    assert link_result.plan["selected_targets"] == ["skill.coding.test-first"]


def test_evolution_evidence_store_appends_openclaw_import_summary(tmp_path: Path) -> None:
    skills_dir = tmp_path / "openclaw-skills"
    _write_openclaw_skill(
        skills_dir,
        "coding/review",
        "review",
        "Use when reviewing code.",
        "coding",
        ["review"],
        "## When to Use\n\n- Review code\n",
    )

    from agentmf.evolution import create_evolution_evidence_payload
    from agentmf.openclaw import create_openclaw_import_payload

    openclaw = create_openclaw_import_payload(
        skill_dirs=[skills_dir],
        out_dir=tmp_path / "modules" / "openclaw",
        namespace="openclaw",
        package_name="openclaw-skills",
        write=False,
    )
    evidence_dir = tmp_path / ".agentmf" / "evolution" / "evidence"

    first = create_evolution_evidence_payload(
        source="openclaw_import",
        payload=openclaw.payload,
        out_dir=evidence_dir,
        timestamp="2026-05-27T00:00:00Z",
        write=True,
    )
    second = create_evolution_evidence_payload(
        source="openclaw_import",
        payload=openclaw.payload,
        out_dir=evidence_dir,
        timestamp="2026-05-27T00:00:01Z",
        write=True,
    )

    path = evidence_dir / "registry" / "openclaw_import.jsonl"
    lines = path.read_text().splitlines()
    record = json.loads(lines[0])

    assert first.ok, first.diagnostics.format()
    assert second.ok, second.diagnostics.format()
    assert first.payload["wrote"] is True
    assert first.payload["path"] == str(path)
    assert len(lines) == 2
    assert record["source"] == "openclaw_import"
    assert record["event_id"].startswith("sha256:")
    assert record["timestamp"] == "2026-05-27T00:00:00Z"
    assert record["summary"]["skill_count"] == 1
    assert record["summary"]["categories"] == {"coding": 1}
    assert record["artifact_refs"]["root_agentmakefile"].endswith("modules/openclaw/AgentMakefile")


def test_evolution_evidence_store_redacts_secret_like_payload_values(tmp_path: Path) -> None:
    from agentmf.evolution import create_evolution_evidence_payload

    # registry_scan has no source-specific summary handler so the full
    # payload is preserved (after redaction) in summary.payload; this is
    # the path that exercises the generic secret-redaction code.
    result = create_evolution_evidence_payload(
        source="registry_scan",
        payload={
            "message": "improve route",
            "OPENAI_API_KEY": "sk-test-secret-value",
            "nested": {"token": "secret-token-value"},
        },
        out_dir=tmp_path / ".agentmf" / "evolution" / "evidence",
        timestamp="2026-05-27T00:00:00Z",
        write=False,
    )

    serialized = json.dumps(result.payload["record"], sort_keys=True)

    assert result.ok, result.diagnostics.format()
    assert result.payload["wrote"] is False
    assert result.payload["record"]["summary"]["payload"]["OPENAI_API_KEY"] == "[REDACTED]"
    assert result.payload["record"]["summary"]["payload"]["nested"]["token"] == "[REDACTED]"
    assert "sk-test-secret-value" not in serialized
    assert "secret-token-value" not in serialized


def test_user_feedback_evidence_drops_unrelated_payload_fields(tmp_path: Path) -> None:
    """user_feedback has a structured summary — fields outside the schema
    (e.g. stray API keys the caller accidentally included) are dropped
    entirely, which is stronger than redaction.
    """
    from agentmf.evolution import create_evolution_evidence_payload

    result = create_evolution_evidence_payload(
        source="user_feedback",
        payload={
            "request": "create a presentation",
            "intended_module": "modules/openclaw-curated/plugins/AgentMakefile",
            "intended_target": "skill.plugins.presentations",
            "OPENAI_API_KEY": "sk-test-secret-value",
            "nested": {"token": "secret-token-value"},
        },
        out_dir=tmp_path / ".agentmf" / "evolution" / "evidence",
        timestamp="2026-05-27T00:00:00Z",
        write=False,
    )

    record = result.payload["record"]
    summary = record["summary"]
    serialized = json.dumps(record, sort_keys=True)

    assert result.ok, result.diagnostics.format()
    assert summary["request"] == "create a presentation"
    assert summary["intended_target"] == "skill.plugins.presentations"
    assert summary["intended_module"].endswith("plugins/AgentMakefile")
    assert "OPENAI_API_KEY" not in summary
    assert "nested" not in summary
    assert "sk-test-secret-value" not in serialized
    assert "secret-token-value" not in serialized


def test_plugin_payload_evidence_surfaces_diff_metadata(tmp_path: Path) -> None:
    """The OpenCode plugin attaches a `diff: [{file, additions, deletions,
    before, after}]` array plus `diff_files`/`diff_source` to its payload.
    The dream loop needs file-level metadata (paths + add/del counts) in
    the surface record so it can filter "this routing actually produced
    changes" without rehydrating the full payload. Full diff content
    stays inside payload_hash to keep records compact.
    """
    from agentmf.evolution import create_evolution_evidence_payload

    plugin_payload = {
        "plugin": "@agentmf/opencode-plugin",
        "event_type": "session.idle",
        "session_id": "ses_smoketest",
        "captured_at": "2026-05-28T00:00:00Z",
        "selected_targets": ["code.change"],
        "selected_skills": ["superpowers:test-driven-development"],
        "diff_files": 2,
        "diff_source": "git diff",
        "diff": [
            {
                "file": "src/foo.py",
                "additions": 3,
                "deletions": 1,
                "before": "def foo(): pass\n",
                "after": "def foo():\n    return 1\n",
            },
            {
                "file": "tests/test_foo.py",
                "additions": 5,
                "deletions": 0,
                "before": "",
                "after": "def test_foo():\n    assert foo() == 1\n",
            },
        ],
    }

    result = create_evolution_evidence_payload(
        source="plugin_payload",
        payload=plugin_payload,
        out_dir=tmp_path / ".agentmf" / "evolution" / "evidence",
        timestamp="2026-05-28T00:00:00Z",
        write=False,
    )

    assert result.ok, result.diagnostics.format()
    record = result.payload["record"]
    summary = record["summary"]

    # Existing surface fields keep working.
    assert summary["selected_targets"] == ["code.change"]
    assert summary["selected_skills"] == ["superpowers:test-driven-development"]
    assert record["selected_target"] == "code.change"

    # New surface fields the dream loop can filter / cluster on.
    assert summary["diff_files"] == 2
    assert summary["diff_source"] == "git diff"
    assert summary["diff_paths"] == ["src/foo.py", "tests/test_foo.py"]
    assert summary["diff_additions"] == 8
    assert summary["diff_deletions"] == 1
    assert summary["event_type"] == "session.idle"
    assert summary["captured_at"] == "2026-05-28T00:00:00Z"

    # Full before/after content stays out of the surface record (it's
    # hashed into payload_hash for deterministic comparison instead).
    serialized = json.dumps(record, sort_keys=True)
    assert "def foo(): pass" not in serialized
    assert "assert foo() == 1" not in serialized


def test_plugin_payload_evidence_handles_empty_diff(tmp_path: Path) -> None:
    """Plugin sessions that didn't touch any files still get a record —
    the diff_files field is 0, diff_paths is empty, and counts are 0.
    Important so the dream loop can distinguish "session ran but no
    files changed" from "evidence missing entirely."
    """
    from agentmf.evolution import create_evolution_evidence_payload

    result = create_evolution_evidence_payload(
        source="plugin_payload",
        payload={
            "plugin": "@agentmf/opencode-plugin",
            "event_type": "session.idle",
            "session_id": "ses_noop",
            "selected_targets": [],
            "selected_skills": [],
            "diff_files": 0,
            "diff_source": "session.diff bucket",
            "diff": [],
        },
        out_dir=tmp_path / ".agentmf" / "evolution" / "evidence",
        timestamp="2026-05-28T00:00:00Z",
        write=False,
    )

    assert result.ok, result.diagnostics.format()
    summary = result.payload["record"]["summary"]
    assert summary["diff_files"] == 0
    assert summary["diff_paths"] == []
    assert summary["diff_additions"] == 0
    assert summary["diff_deletions"] == 0


def test_cli_evo_evidence_add_writes_openclaw_import_record(tmp_path: Path, capsys) -> None:
    payload_file = tmp_path / "openclaw-import.json"
    payload_file.write_text(
        json.dumps(
            {
                "ok": True,
                "openclaw_import": {
                    "root_path": "modules/openclaw/AgentMakefile",
                    "curator_evidence": {
                        "skill_count": 2,
                        "category_count": 1,
                        "categories": {"coding": 2},
                        "duplicate_original_names": {},
                        "module_paths": ["coding/AgentMakefile"],
                    },
                },
            }
        )
    )
    evidence_dir = tmp_path / ".agentmf" / "evolution" / "evidence"

    exit_code = main(
        [
            "evo",
            "evidence",
            "add",
            "--source",
            "openclaw_import",
            "--payload-file",
            str(payload_file),
            "--out-dir",
            str(evidence_dir),
            "--timestamp",
            "2026-05-27T00:00:00Z",
            "--write",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    path = evidence_dir / "registry" / "openclaw_import.jsonl"

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["evolution_evidence"]["path"] == str(path)
    assert path.exists()
    assert json.loads(path.read_text())["summary"]["skill_count"] == 2


def test_skill_workshop_proposal_writes_json_and_markdown_report(tmp_path: Path) -> None:
    from agentmf.evolution import (
        create_evolution_evidence_payload,
        create_skill_workshop_proposal_payload,
    )

    evidence_dir = tmp_path / ".agentmf" / "evolution" / "evidence"
    evidence = create_evolution_evidence_payload(
        source="openclaw_import",
        payload={
            "root_path": "modules/openclaw/AgentMakefile",
            "curator_evidence": {
                "skill_count": 3,
                "category_count": 1,
                "categories": {"coding": 3},
                "duplicate_original_names": {
                    "review": ["coding/review/SKILL.md", "coding/review-alt/SKILL.md"]
                },
                "module_paths": ["coding/AgentMakefile"],
            },
        },
        out_dir=evidence_dir,
        timestamp="2026-05-27T00:00:00Z",
        write=True,
    )
    assert evidence.ok, evidence.diagnostics.format()
    evidence_file = evidence_dir / "registry" / "openclaw_import.jsonl"
    out_dir = tmp_path / ".agentmf" / "evolution" / "candidates"

    result = create_skill_workshop_proposal_payload(
        title="Curate duplicate OpenClaw review skills",
        evidence_files=[evidence_file],
        scope={
            "modules": ["modules/openclaw/coding/AgentMakefile"],
            "targets": ["skill.coding.review"],
        },
        changes=[
            {
                "type": "merge_duplicate_targets",
                "target": "skill.coding.review",
                "reason": "duplicate original skill names in OpenClaw import",
            }
        ],
        evaluation_commands=[
            "agentmf validate --file modules/openclaw/coding/AgentMakefile",
            "agentmf benchmark harness --file modules/openclaw/AgentMakefile --case \"review code\"",
        ],
        out_dir=out_dir,
        timestamp="2026-05-27T00:00:01Z",
        write=True,
    )

    proposal = result.payload["proposal"]
    proposal_path = Path(result.payload["paths"]["proposal_json"])
    report_path = Path(result.payload["paths"]["markdown_report"])
    report = report_path.read_text()

    assert result.ok, result.diagnostics.format()
    assert proposal["proposal_id"].startswith("amf-evo-")
    assert proposal["title"] == "Curate duplicate OpenClaw review skills"
    assert proposal["scope"]["modules"] == ["modules/openclaw/coding/AgentMakefile"]
    assert proposal["evidence"][0]["event_id"] == evidence.payload["record"]["event_id"]
    assert proposal["changes"][0]["type"] == "merge_duplicate_targets"
    assert proposal["evaluation"]["status"] == "not_run"
    assert proposal["promotion"] == {"status": "candidate", "requires_review": True}
    assert proposal_path.exists()
    assert report_path.exists()
    assert "# Curate duplicate OpenClaw review skills" in report
    assert "merge_duplicate_targets" in report
    assert "agentmf validate --file modules/openclaw/coding/AgentMakefile" in report


def test_skill_workshop_proposal_rejects_unknown_promotion_status(tmp_path: Path) -> None:
    from agentmf.evolution import create_skill_workshop_proposal_payload

    result = create_skill_workshop_proposal_payload(
        title="Invalid status proposal",
        evidence_files=[],
        scope={},
        changes=[],
        evaluation_commands=[],
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        promotion_status="ready",
        write=False,
    )

    assert not result.ok
    assert result.diagnostics.items[0].code == "AMF222"


def test_cli_evo_proposal_create_writes_candidate_files(tmp_path: Path, capsys) -> None:
    evidence_dir = tmp_path / ".agentmf" / "evolution" / "evidence" / "registry"
    evidence_dir.mkdir(parents=True)
    evidence_file = evidence_dir / "openclaw_import.jsonl"
    evidence_file.write_text(
        json.dumps(
            {
                "version": 1,
                "event_id": "sha256:evidence",
                "timestamp": "2026-05-27T00:00:00Z",
                "source": "openclaw_import",
                "summary": {"skill_count": 2, "categories": {"coding": 2}},
                "artifact_refs": {"root_agentmakefile": "modules/openclaw/AgentMakefile"},
            }
        )
        + "\n"
    )
    out_dir = tmp_path / ".agentmf" / "evolution" / "candidates"

    exit_code = main(
        [
            "evo",
            "proposal",
            "create",
            "--title",
            "Improve OpenClaw coding skill routing",
            "--evidence-file",
            str(evidence_file),
            "--module",
            "modules/openclaw/coding/AgentMakefile",
            "--target",
            "skill.coding.review",
            "--change-json",
            json.dumps(
                {
                    "type": "match_rule_update",
                    "target": "skill.coding.review",
                    "reason": "OpenClaw evidence showed duplicate review skills",
                }
            ),
            "--evaluation-command",
            "agentmf validate --file modules/openclaw/coding/AgentMakefile",
            "--out-dir",
            str(out_dir),
            "--timestamp",
            "2026-05-27T00:00:01Z",
            "--write",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    proposal_path = Path(payload["skill_workshop_proposal"]["paths"]["proposal_json"])
    report_path = Path(payload["skill_workshop_proposal"]["paths"]["markdown_report"])

    assert exit_code == 0
    assert payload["ok"] is True
    assert proposal_path.exists()
    assert report_path.exists()
    assert json.loads(proposal_path.read_text())["title"] == "Improve OpenClaw coding skill routing"
    assert "Improve OpenClaw coding skill routing" in report_path.read_text()


def test_candidate_patch_generator_writes_patch_without_mutating_source(tmp_path: Path) -> None:
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.coding.review:
    match:
      user_intent:
        - review
    steps:
      - action: inspect
""",
    )
    proposal_path = tmp_path / "candidate.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "amf-evo-testpatch",
                "title": "Improve review routing",
                "scope": {"modules": [str(module_path)], "targets": ["skill.coding.review"]},
                "evidence": [{"event_id": "sha256:evidence", "reason": "duplicate review skills"}],
                "changes": [
                    {
                        "type": "update_match_terms",
                        "module": str(module_path),
                        "target": "skill.coding.review",
                        "add_terms": ["review code", "inspect patch"],
                    }
                ],
                "evaluation": {"commands": [], "status": "not_run"},
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_candidate_patch_payload

    original_content = module_path.read_text()
    result = create_candidate_patch_payload(
        proposal_file=proposal_path,
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        write=True,
    )

    patch_path = Path(result.payload["paths"]["patch"])
    patch = patch_path.read_text()

    assert result.ok, result.diagnostics.format()
    assert patch_path.exists()
    assert module_path.read_text() == original_content
    assert result.payload["patch_status"] == "generated"
    assert "amf-evo-testpatch" in result.payload["proposal_id"]
    assert "+      - review code" in patch
    assert "+      - inspect patch" in patch


def test_candidate_patch_generator_merges_duplicate_openclaw_targets(tmp_path: Path) -> None:
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
metadata:
  skill_count: 3
skills:
  coding.review:
    namespace: smoke
    description: Review primary.
    implementation:
      source: skills/review/SKILL.md
      original_name: review
      relative_source: coding/review/SKILL.md
    match:
      user_intent:
        - review
  coding.review-2:
    namespace: smoke
    description: Review alternate.
    implementation:
      source: skills/review-alt/SKILL.md
      original_name: review
      relative_source: coding/review-alt/SKILL.md
    match:
      user_intent:
        - inspect patch
  coding.debug:
    namespace: smoke
    description: Debug.
    implementation:
      source: skills/debug/SKILL.md
      original_name: debug
      relative_source: coding/debug/SKILL.md
    match:
      user_intent:
        - debug
targets:
  skill.coding.review:
    match:
      user_intent:
        - review
    skills:
      - smoke:coding.review
    steps:
      - use_skill: smoke:coding.review
      - link_prompt:
          source: skills/review/SKILL.md
  skill.coding.review-2:
    match:
      user_intent:
        - inspect patch
    skills:
      - smoke:coding.review-2
    steps:
      - use_skill: smoke:coding.review-2
      - link_prompt:
          source: skills/review-alt/SKILL.md
  skill.coding.debug:
    match:
      user_intent:
        - debug
    skills:
      - smoke:coding.debug
    steps:
      - use_skill: smoke:coding.debug
""",
    )
    proposal_path = tmp_path / "duplicate.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "amf-evo-merge",
                "title": "Merge duplicate review targets",
                "scope": {"modules": [str(module_path)], "targets": []},
                "evidence": [{"event_id": "sha256:evidence", "reason": "duplicate review skills"}],
                "changes": [
                    {
                        "type": "merge_duplicate_targets",
                        "duplicate_original_names": {
                            "review": [
                                "coding/review/SKILL.md",
                                "coding/review-alt/SKILL.md",
                            ]
                        },
                    }
                ],
                "evaluation": {"commands": [], "status": "not_run"},
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_candidate_patch_payload, create_compile_evaluate_payload

    patch_result = create_candidate_patch_payload(
        proposal_file=proposal_path,
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        write=False,
    )
    eval_result = create_compile_evaluate_payload(
        proposal_file=proposal_path,
        workspace_dir=tmp_path / ".agentmf" / "evolution" / "worktrees",
        write=True,
    )
    candidate_source = load_source(Path(eval_result.payload["candidate_files"][0]["path"]))

    assert patch_result.ok, patch_result.diagnostics.format()
    assert patch_result.payload["patch_status"] == "generated"
    assert patch_result.payload["unsupported_changes"] == []
    assert "-  coding.review-2:" in patch_result.payload["patch"]
    assert "-  skill.coding.review-2:" in patch_result.payload["patch"]
    assert eval_result.ok, eval_result.diagnostics.format()
    assert eval_result.payload["promotion_report"]["status"] == "passed"
    assert "coding.review-2" not in candidate_source.skills
    assert "skill.coding.review-2" not in candidate_source.targets
    assert candidate_source.skills["coding.review"].match["user_intent"] == [
        "review",
        "inspect patch",
    ]
    assert candidate_source.targets["skill.coding.review"].match["user_intent"] == [
        "review",
        "inspect patch",
    ]
    assert candidate_source.skills["coding.review"].implementation["merged_duplicates"] == [
        {
            "skill": "coding.review-2",
            "source": "skills/review-alt/SKILL.md",
            "relative_source": "coding/review-alt/SKILL.md",
            "original_name": "review",
        }
    ]
    assert candidate_source.metadata["skill_count"] == 2
    assert load_source(module_path).skills["coding.review-2"].description == "Review alternate."


def test_compile_evaluate_runs_compile_and_selector_gates(tmp_path: Path) -> None:
    """When proposal.evaluation declares selector_tests, evaluate must run
    each candidate AgentMakefile through `compile_agentmakefile` and through
    `create_link_plan` against the declared (request, expected_target)
    pairs. promotion_report carries the results and gates promotion status.
    """
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.review:
    priority: 70
    match:
      user_intent:
        - existing review trigger
    steps:
      - action: inspect
""",
    )
    proposal_path = tmp_path / "gated.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "gated-passing",
                "title": "Add reviewing-diff trigger",
                "scope": {"modules": [str(module_path)], "targets": ["skill.review"]},
                "evidence": [{"event_id": "sha256:gate", "reason": "test"}],
                "changes": [
                    {
                        "type": "update_match_terms",
                        "module": str(module_path),
                        "target": "skill.review",
                        "add_terms": ["please review this diff"],
                    }
                ],
                "evaluation": {
                    "commands": [],
                    "status": "not_run",
                    "selector_tests": [
                        {"request": "please review this diff", "expected_target": "skill.review"}
                    ],
                },
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_compile_evaluate_payload

    result = create_compile_evaluate_payload(
        proposal_file=proposal_path,
        workspace_dir=tmp_path / "ws",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    report = result.payload["promotion_report"]
    assert report["status"] == "passed"
    assert len(report["compile_results"]) == 1
    assert report["compile_results"][0]["status"] == "passed"
    assert len(report["selector_test_results"]) == 1
    selector = report["selector_test_results"][0]
    assert selector["status"] == "passed"
    assert selector["request"] == "please review this diff"
    assert selector["expected_target"] == "skill.review"
    assert selector["actual_target"] == "skill.review"


def test_compile_evaluate_selector_gate_fails_when_actual_target_differs(tmp_path: Path) -> None:
    """A selector_test whose expected_target doesn't match the actual route
    flips promotion_report.status to 'failed' even when validate and
    compile both pass."""
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.review:
    priority: 70
    match:
      user_intent:
        - existing review trigger
    steps:
      - action: inspect
""",
    )
    proposal_path = tmp_path / "gated-fail.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "gated-failing",
                "title": "Selector gate sanity",
                "scope": {"modules": [str(module_path)], "targets": ["skill.review"]},
                "evidence": [{"event_id": "sha256:gate-fail", "reason": "test"}],
                "changes": [
                    {
                        "type": "update_match_terms",
                        "module": str(module_path),
                        "target": "skill.review",
                        "add_terms": ["unrelated phrase"],
                    }
                ],
                "evaluation": {
                    "commands": [],
                    "status": "not_run",
                    "selector_tests": [
                        # The patch adds a phrase but expects routing of a
                        # totally unrelated request to land on skill.review —
                        # there's no matching term so the gate must fail.
                        {"request": "totally unrelated quokka inquiry", "expected_target": "skill.review"}
                    ],
                },
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_compile_evaluate_payload

    result = create_compile_evaluate_payload(
        proposal_file=proposal_path,
        workspace_dir=tmp_path / "ws",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    report = result.payload["promotion_report"]
    assert report["status"] == "failed"
    selector = report["selector_test_results"][0]
    assert selector["status"] == "failed"
    assert selector["actual_target"] is None or selector["actual_target"] != "skill.review"


def test_compile_evaluate_benchmark_smoke_passes_when_expected_routes_match(tmp_path: Path) -> None:
    """A proposal can declare evaluation.benchmark_smoke = {tasks_file,
    expected_routes}; evaluate must load the JSONL tasks, route each
    against the candidate, and pass when every (task_id -> target) in
    expected_routes is met.
    """
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.review:
    priority: 70
    match:
      user_intent:
        - review the diff
    steps:
      - action: inspect
  skill.plan:
    priority: 70
    match:
      user_intent:
        - draft an implementation plan
    steps:
      - action: plan
""",
    )
    tasks_file = tmp_path / "smoke-tasks.jsonl"
    tasks_file.write_text(
        json.dumps({"id": "t-review", "instruction": "review the diff"}) + "\n"
        + json.dumps({"id": "t-plan", "instruction": "draft an implementation plan"}) + "\n"
    )
    proposal_path = tmp_path / "smoke.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "smoke-pass",
                "title": "Smoke gate ok",
                "scope": {"modules": [str(module_path)], "targets": ["skill.review"]},
                "evidence": [{"event_id": "sha256:smoke", "reason": "test"}],
                "changes": [
                    {
                        "type": "update_match_terms",
                        "module": str(module_path),
                        "target": "skill.review",
                        "add_terms": ["look at the patch"],
                    }
                ],
                "evaluation": {
                    "commands": [],
                    "status": "not_run",
                    "benchmark_smoke": {
                        "tasks_file": str(tasks_file),
                        "expected_routes": {
                            "t-review": "skill.review",
                            "t-plan": "skill.plan",
                        },
                    },
                },
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_compile_evaluate_payload

    result = create_compile_evaluate_payload(
        proposal_file=proposal_path,
        workspace_dir=tmp_path / "ws",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    report = result.payload["promotion_report"]
    assert report["status"] == "passed"
    smoke = report["benchmark_smoke_results"]
    assert smoke["summary"] == {"total": 2, "passed": 2, "failed": 0, "skipped": 0}
    statuses = {task["task_id"]: task["status"] for task in smoke["tasks"]}
    assert statuses == {"t-review": "passed", "t-plan": "passed"}


def test_compile_evaluate_benchmark_smoke_fails_on_regression(tmp_path: Path) -> None:
    """When at least one expected route doesn't match the candidate's
    selection, the smoke gate fails and promotion_report.status is
    'failed'.
    """
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.review:
    priority: 70
    match:
      user_intent:
        - review the diff
    steps:
      - action: inspect
""",
    )
    tasks_file = tmp_path / "smoke-tasks.jsonl"
    tasks_file.write_text(
        json.dumps({"id": "t-review", "instruction": "review the diff"}) + "\n"
        + json.dumps({"id": "t-orphan", "instruction": "totally unrelated orchid request"}) + "\n"
    )
    proposal_path = tmp_path / "smoke-fail.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "smoke-fail",
                "title": "Smoke gate fail",
                "scope": {"modules": [str(module_path)], "targets": ["skill.review"]},
                "evidence": [{"event_id": "sha256:smoke-fail", "reason": "test"}],
                "changes": [
                    {
                        "type": "update_match_terms",
                        "module": str(module_path),
                        "target": "skill.review",
                        "add_terms": ["look at the patch"],
                    }
                ],
                "evaluation": {
                    "commands": [],
                    "status": "not_run",
                    "benchmark_smoke": {
                        "tasks_file": str(tasks_file),
                        "expected_routes": {
                            "t-review": "skill.review",
                            "t-orphan": "skill.orphan_does_not_exist",
                        },
                    },
                },
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_compile_evaluate_payload

    result = create_compile_evaluate_payload(
        proposal_file=proposal_path,
        workspace_dir=tmp_path / "ws",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    report = result.payload["promotion_report"]
    assert report["status"] == "failed"
    smoke = report["benchmark_smoke_results"]
    assert smoke["summary"]["passed"] == 1
    assert smoke["summary"]["failed"] == 1
    failing = [task for task in smoke["tasks"] if task["status"] == "failed"]
    assert len(failing) == 1
    assert failing[0]["task_id"] == "t-orphan"


def test_compile_evaluate_loop_validates_candidate_in_isolated_workspace(tmp_path: Path) -> None:
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.coding.review:
    match:
      user_intent:
        - review
    steps:
      - action: inspect
""",
    )
    proposal_path = tmp_path / "candidate.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "amf-evo-evaluate",
                "title": "Evaluate review routing patch",
                "scope": {"modules": [str(module_path)], "targets": ["skill.coding.review"]},
                "evidence": [{"event_id": "sha256:evidence", "reason": "routing gap"}],
                "changes": [
                    {
                        "type": "update_match_terms",
                        "module": str(module_path),
                        "target": "skill.coding.review",
                        "add_terms": ["review code"],
                    }
                ],
                "evaluation": {
                    "commands": ["agentmf validate --file AgentMakefile"],
                    "status": "not_run",
                },
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_compile_evaluate_payload

    workspace_dir = tmp_path / ".agentmf" / "evolution" / "worktrees" / "amf-evo-evaluate"
    result = create_compile_evaluate_payload(
        proposal_file=proposal_path,
        workspace_dir=workspace_dir,
        write=True,
    )

    candidate_path = Path(result.payload["candidate_files"][0]["path"])
    candidate_source = load_source(candidate_path)

    assert result.ok, result.diagnostics.format()
    assert result.payload["promotion_report"]["status"] == "passed"
    assert result.payload["promotion_report"]["requires_review"] is True
    assert candidate_path.exists()
    assert candidate_path != module_path
    assert candidate_source.targets["skill.coding.review"].match["user_intent"] == [
        "review",
        "review code",
    ]
    assert load_source(module_path).targets["skill.coding.review"].match["user_intent"] == ["review"]


def test_candidate_patch_merges_duplicate_targets_across_modules(tmp_path: Path) -> None:
    """Cross-module dup: primary in module A, duplicate in module B.

    The merger must locate both via relative_source, drop the duplicate
    from module B (skill + matching target + skill_count), and append a
    merged_duplicates entry on the primary in module A.
    """
    module_a = tmp_path / "cat-a" / "AgentMakefile"
    module_b = tmp_path / "cat-b" / "AgentMakefile"
    module_a.parent.mkdir(parents=True)
    module_b.parent.mkdir(parents=True)
    module_a.write_text(
        """\
version: "0.1"
metadata:
  skill_count: 1
skills:
  cat-a.shared:
    namespace: smoke
    description: primary copy.
    implementation:
      source: skills/shared-a/SKILL.md
      relative_source: cat-a/shared/SKILL.md
      original_name: shared
    match:
      user_intent:
        - run shared from a
targets:
  skill.cat-a.shared:
    match:
      user_intent:
        - run shared from a
    skills:
      - smoke:cat-a.shared
    steps:
      - use_skill: smoke:cat-a.shared
"""
    )
    module_b.write_text(
        """\
version: "0.1"
metadata:
  skill_count: 1
skills:
  cat-b.shared:
    namespace: smoke
    description: duplicate copy.
    implementation:
      source: skills/shared-b/SKILL.md
      relative_source: cat-b/shared/SKILL.md
      original_name: shared
    match:
      user_intent:
        - run shared from b
targets:
  skill.cat-b.shared:
    match:
      user_intent:
        - run shared from b
    skills:
      - smoke:cat-b.shared
    steps:
      - use_skill: smoke:cat-b.shared
"""
    )
    proposal_path = tmp_path / "cross.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "amf-evo-cross",
                "title": "Merge duplicate across category modules",
                "scope": {"modules": [str(module_a), str(module_b)], "targets": []},
                "evidence": [{"event_id": "sha256:cross", "reason": "cross-module duplicate"}],
                "changes": [
                    {
                        "type": "merge_duplicate_targets",
                        "duplicate_original_names": {
                            "shared": [
                                "cat-a/shared/SKILL.md",
                                "cat-b/shared/SKILL.md",
                            ]
                        },
                    }
                ],
                "evaluation": {"commands": [], "status": "not_run"},
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_candidate_patch_payload, create_compile_evaluate_payload

    patch_result = create_candidate_patch_payload(
        proposal_file=proposal_path,
        out_dir=tmp_path / "candidates",
        write=False,
    )
    eval_result = create_compile_evaluate_payload(
        proposal_file=proposal_path,
        workspace_dir=tmp_path / "ws",
        write=True,
    )

    assert patch_result.ok, patch_result.diagnostics.format()
    assert patch_result.payload["patch_status"] == "generated"
    assert patch_result.payload["unsupported_changes"] == []
    assert {str(module_a), str(module_b)} == set(patch_result.payload["touched_files"])
    assert eval_result.ok, eval_result.diagnostics.format()
    assert eval_result.payload["promotion_report"]["status"] == "passed"

    candidate_paths = {Path(entry["source"]): Path(entry["path"]) for entry in eval_result.payload["candidate_files"]}
    candidate_a = load_source(candidate_paths[module_a])
    candidate_b = load_source(candidate_paths[module_b])

    assert "cat-a.shared" in candidate_a.skills
    assert candidate_a.skills["cat-a.shared"].implementation["merged_duplicates"] == [
        {
            "skill": "cat-b.shared",
            "source": "skills/shared-b/SKILL.md",
            "relative_source": "cat-b/shared/SKILL.md",
            "original_name": "shared",
        }
    ]
    assert candidate_a.skills["cat-a.shared"].match["user_intent"] == [
        "run shared from a",
        "run shared from b",
    ]
    assert candidate_a.targets["skill.cat-a.shared"].match["user_intent"] == [
        "run shared from a",
        "run shared from b",
    ]
    assert "cat-b.shared" not in candidate_b.skills
    assert "skill.cat-b.shared" not in candidate_b.targets
    assert candidate_b.metadata["skill_count"] == 0
    assert load_source(module_a).skills["cat-a.shared"].implementation.get("merged_duplicates") is None
    assert "cat-b.shared" in load_source(module_b).skills


def test_evo_promote_copies_candidates_and_accepts_proposal(tmp_path: Path) -> None:
    """Promote a cross-module merge proposal: candidate modules land under
    target_dir mirroring their parent dirs, the proposal flips to
    `accepted`, and original sources stay untouched.
    """
    module_a = tmp_path / "cat-a" / "AgentMakefile"
    module_b = tmp_path / "cat-b" / "AgentMakefile"
    module_a.parent.mkdir(parents=True)
    module_b.parent.mkdir(parents=True)
    module_a.write_text(
        """\
version: "0.1"
metadata:
  skill_count: 1
skills:
  cat-a.shared:
    namespace: smoke
    description: primary copy.
    implementation:
      source: skills/shared-a/SKILL.md
      relative_source: cat-a/shared/SKILL.md
      original_name: shared
    match:
      user_intent:
        - alpha
targets:
  skill.cat-a.shared:
    match:
      user_intent:
        - alpha
    skills:
      - smoke:cat-a.shared
    steps:
      - use_skill: smoke:cat-a.shared
"""
    )
    module_b.write_text(
        """\
version: "0.1"
metadata:
  skill_count: 1
skills:
  cat-b.shared:
    namespace: smoke
    description: duplicate copy.
    implementation:
      source: skills/shared-b/SKILL.md
      relative_source: cat-b/shared/SKILL.md
      original_name: shared
    match:
      user_intent:
        - beta
targets:
  skill.cat-b.shared:
    match:
      user_intent:
        - beta
    skills:
      - smoke:cat-b.shared
    steps:
      - use_skill: smoke:cat-b.shared
"""
    )
    proposal_path = tmp_path / "promote.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "amf-evo-promote",
                "title": "Promote cross-module merge",
                "scope": {"modules": [str(module_a), str(module_b)], "targets": []},
                "evidence": [{"event_id": "sha256:promote", "reason": "cross-module duplicate"}],
                "changes": [
                    {
                        "type": "merge_duplicate_targets",
                        "duplicate_original_names": {
                            "shared": [
                                "cat-a/shared/SKILL.md",
                                "cat-b/shared/SKILL.md",
                            ]
                        },
                    }
                ],
                "evaluation": {"commands": [], "status": "not_run"},
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_promotion_payload

    target_root = tmp_path / "promoted"
    result = create_promotion_payload(
        proposal_file=proposal_path,
        target_dir=target_root,
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["status"] == "promoted"
    promoted_files = result.payload["promoted_files"]
    assert len(promoted_files) == 2
    assert all(entry["status"] == "passed" for entry in promoted_files)

    promoted_a = target_root / "cat-a" / "AgentMakefile"
    promoted_b = target_root / "cat-b" / "AgentMakefile"
    assert promoted_a.exists()
    assert promoted_b.exists()

    promoted_source_a = load_source(promoted_a)
    promoted_source_b = load_source(promoted_b)
    assert "cat-a.shared" in promoted_source_a.skills
    assert promoted_source_a.skills["cat-a.shared"].implementation["merged_duplicates"] == [
        {
            "skill": "cat-b.shared",
            "source": "skills/shared-b/SKILL.md",
            "relative_source": "cat-b/shared/SKILL.md",
            "original_name": "shared",
        }
    ]
    assert "cat-b.shared" not in promoted_source_b.skills

    # Canonical source modules untouched.
    assert "cat-b.shared" in load_source(module_b).skills
    assert load_source(module_a).skills["cat-a.shared"].implementation.get("merged_duplicates") is None

    # Proposal file flipped to accepted.
    updated_proposal = json.loads(proposal_path.read_text())
    assert updated_proposal["promotion"] == {"status": "accepted", "requires_review": False}


def test_evo_promote_dry_run_plans_without_writing(tmp_path: Path) -> None:
    """write=False emits a target plan but does not copy files or mutate the proposal."""
    module_a = tmp_path / "cat-a" / "AgentMakefile"
    module_a.parent.mkdir(parents=True)
    module_a.write_text(
        """\
version: "0.1"
skills:
  coding.review:
    description: keep me.
    implementation:
      source: skills/review/SKILL.md
      relative_source: cat-a/review/SKILL.md
    match:
      user_intent:
        - review
targets:
  skill.coding.review:
    match:
      user_intent:
        - review
    skills:
      - coding.review
    steps:
      - use_skill: coding.review
"""
    )
    proposal_path = tmp_path / "dry.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "amf-evo-promote-dry",
                "title": "Dry-run promote",
                "scope": {"modules": [str(module_a)], "targets": ["skill.coding.review"]},
                "evidence": [{"event_id": "sha256:dry", "reason": "extend routing"}],
                "changes": [
                    {
                        "type": "update_match_terms",
                        "module": str(module_a),
                        "target": "skill.coding.review",
                        "add_terms": ["review code"],
                    }
                ],
                "evaluation": {"commands": [], "status": "not_run"},
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_promotion_payload

    target_root = tmp_path / "promoted"
    result = create_promotion_payload(
        proposal_file=proposal_path,
        target_dir=target_root,
        write=False,
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["status"] == "planned"
    assert not target_root.exists()
    proposal_after = json.loads(proposal_path.read_text())
    assert proposal_after["promotion"] == {"status": "candidate", "requires_review": True}


def test_compile_evaluate_workspace_disambiguates_modules_sharing_basename(tmp_path: Path) -> None:
    cat_a = tmp_path / "cat-a"
    cat_b = tmp_path / "cat-b"
    cat_a.mkdir()
    cat_b.mkdir()

    def _write(module_dir: Path, primary_name: str, duplicate_name: str, primary_rel: str, duplicate_rel: str) -> Path:
        path = module_dir / "AgentMakefile"
        path.write_text(
            "version: \"0.1\"\n"
            "metadata:\n"
            "  skill_count: 2\n"
            "skills:\n"
            f"  {primary_name}:\n"
            "    namespace: smoke\n"
            "    description: primary.\n"
            "    implementation:\n"
            f"      source: skills/{primary_rel}\n"
            f"      relative_source: {primary_rel}\n"
            "      original_name: shared\n"
            "    match:\n"
            "      user_intent:\n"
            "        - alpha\n"
            f"  {duplicate_name}:\n"
            "    namespace: smoke\n"
            "    description: duplicate.\n"
            "    implementation:\n"
            f"      source: skills/{duplicate_rel}\n"
            f"      relative_source: {duplicate_rel}\n"
            "      original_name: shared\n"
            "    match:\n"
            "      user_intent:\n"
            "        - beta\n"
            "targets:\n"
            f"  skill.{primary_name}:\n"
            "    match:\n"
            "      user_intent:\n"
            "        - alpha\n"
            "    skills:\n"
            f"      - smoke:{primary_name}\n"
            "    steps:\n"
            f"      - use_skill: smoke:{primary_name}\n"
            f"  skill.{duplicate_name}:\n"
            "    match:\n"
            "      user_intent:\n"
            "        - beta\n"
            "    skills:\n"
            f"      - smoke:{duplicate_name}\n"
            "    steps:\n"
            f"      - use_skill: smoke:{duplicate_name}\n"
        )
        return path

    module_a = _write(cat_a, "cat_a.primary", "cat_a.duplicate", "cat-a/primary/SKILL.md", "cat-a/duplicate/SKILL.md")
    module_b = _write(cat_b, "cat_b.primary", "cat_b.duplicate", "cat-b/primary/SKILL.md", "cat-b/duplicate/SKILL.md")
    proposal_path = tmp_path / "multi.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "amf-evo-multi",
                "title": "Merge across modules sharing basename",
                "scope": {"modules": [str(module_a), str(module_b)], "targets": []},
                "evidence": [{"event_id": "sha256:evidence", "reason": "two modules"}],
                "changes": [
                    {
                        "type": "merge_duplicate_targets",
                        "module": str(module_a),
                        "duplicate_original_names": {
                            "shared": ["cat-a/primary/SKILL.md", "cat-a/duplicate/SKILL.md"]
                        },
                    },
                    {
                        "type": "merge_duplicate_targets",
                        "module": str(module_b),
                        "duplicate_original_names": {
                            "shared": ["cat-b/primary/SKILL.md", "cat-b/duplicate/SKILL.md"]
                        },
                    },
                ],
                "evaluation": {"commands": [], "status": "not_run"},
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_compile_evaluate_payload

    result = create_compile_evaluate_payload(
        proposal_file=proposal_path,
        workspace_dir=tmp_path / "ws",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    candidate_files = result.payload["candidate_files"]
    assert len(candidate_files) == 2
    workspace_paths = [Path(entry["path"]) for entry in candidate_files]
    assert len({p for p in workspace_paths}) == 2, f"workspace paths collided: {workspace_paths}"
    for path in workspace_paths:
        assert path.exists(), f"workspace file missing: {path}"
    sources = [load_source(path) for path in workspace_paths]
    skill_names = {name for source in sources for name in source.skills}
    assert "cat_a.duplicate" not in skill_names
    assert "cat_b.duplicate" not in skill_names
    assert {"cat_a.primary", "cat_b.primary"} <= skill_names


def test_dream_mode_dry_run_creates_openclaw_duplicate_proposal(tmp_path: Path) -> None:
    evidence_dir = tmp_path / ".agentmf" / "evolution" / "evidence" / "registry"
    evidence_dir.mkdir(parents=True)
    evidence_file = evidence_dir / "openclaw_import.jsonl"
    evidence_file.write_text(
        json.dumps(
            {
                "version": 1,
                "event_id": "sha256:openclaw",
                "timestamp": "2026-05-27T00:00:00Z",
                "source": "openclaw_import",
                "summary": {
                    "skill_count": 3,
                    "categories": {"coding": 3},
                    "duplicate_original_names": {
                        "review": ["coding/review/SKILL.md", "coding/review-alt/SKILL.md"]
                    },
                    "module_paths": ["coding/AgentMakefile"],
                },
                "artifact_refs": {"root_agentmakefile": "modules/openclaw/AgentMakefile"},
            }
        )
        + "\n"
    )

    from agentmf.evolution import create_dream_mode_payload

    result = create_dream_mode_payload(
        evidence_dir=tmp_path / ".agentmf" / "evolution" / "evidence",
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        timestamp="2026-05-27T00:00:01Z",
        write=True,
    )

    proposal_path = Path(result.payload["proposals"][0]["paths"]["proposal_json"])
    proposal = json.loads(proposal_path.read_text())

    assert result.ok, result.diagnostics.format()
    assert result.payload["mode"] == "dream_mode_dry_run"
    assert result.payload["proposal_count"] == 1
    assert result.payload["proposals"][0]["patch_status"] == "would_generate_patch"
    assert proposal["changes"][0]["type"] == "merge_duplicate_targets"
    assert proposal["promotion"] == {"status": "candidate", "requires_review": True}


def test_dream_mode_dry_run_detects_recurring_routing_gaps(tmp_path: Path) -> None:
    """Recurring failed selections (selected_target=null, same fingerprint, N>=2)
    must surface as investigate_recurring_routing_gap proposals; single failures
    and successful selections must not."""
    evidence_root = tmp_path / ".agentmf" / "evolution" / "evidence" / "traces"
    evidence_root.mkdir(parents=True)
    evidence_file = evidence_root / "plugin_payload.jsonl"
    fp_recurring = "sha256:" + "a" * 64
    fp_single = "sha256:" + "b" * 64
    fp_recovered = "sha256:" + "c" * 64
    records = [
        {
            "version": 1,
            "event_id": "sha256:e1",
            "timestamp": "2026-05-27T00:00:00Z",
            "source": "plugin_payload",
            "request_fingerprint": fp_recurring,
            "selected_target": None,
            "selected_skills": [],
            "summary": {"selected_targets": [], "selected_skills": []},
        },
        {
            "version": 1,
            "event_id": "sha256:e2",
            "timestamp": "2026-05-27T00:00:01Z",
            "source": "plugin_payload",
            "request_fingerprint": fp_recurring,
            "selected_target": None,
            "selected_skills": [],
            "summary": {"selected_targets": [], "selected_skills": []},
        },
        {
            "version": 1,
            "event_id": "sha256:e3",
            "timestamp": "2026-05-27T00:00:02Z",
            "source": "plugin_payload",
            "request_fingerprint": fp_recurring,
            "selected_target": None,
            "selected_skills": [],
            "summary": {"selected_targets": [], "selected_skills": []},
        },
        {
            "version": 1,
            "event_id": "sha256:e4",
            "timestamp": "2026-05-27T00:00:03Z",
            "source": "plugin_payload",
            "request_fingerprint": fp_single,
            "selected_target": None,
            "selected_skills": [],
            "summary": {"selected_targets": [], "selected_skills": []},
        },
        {
            "version": 1,
            "event_id": "sha256:e5",
            "timestamp": "2026-05-27T00:00:04Z",
            "source": "plugin_payload",
            "request_fingerprint": fp_recovered,
            "selected_target": "skill.coding.review",
            "selected_skills": ["smoke:coding.review"],
            "summary": {"selected_targets": ["skill.coding.review"], "selected_skills": ["smoke:coding.review"]},
        },
    ]
    evidence_file.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    from agentmf.evolution import create_dream_mode_payload

    result = create_dream_mode_payload(
        evidence_dir=tmp_path / ".agentmf" / "evolution" / "evidence",
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        timestamp="2026-05-27T01:00:00Z",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    routing_gaps = [
        p for p in result.payload["proposals"]
        if p["proposal"]["changes"][0]["type"] == "investigate_recurring_routing_gap"
    ]
    assert len(routing_gaps) == 1, [p["proposal"]["changes"][0] for p in result.payload["proposals"]]
    assert routing_gaps[0]["patch_status"] == "skipped_unsupported_change"
    proposal = routing_gaps[0]["proposal"]
    change = proposal["changes"][0]
    assert change["request_fingerprint"] == fp_recurring
    assert change["failure_count"] == 3
    assert sorted(change["sample_event_ids"]) == ["sha256:e1", "sha256:e2", "sha256:e3"]
    assert proposal["promotion"] == {"status": "candidate", "requires_review": True}
    # Evidence on the proposal must NOT include the successful or the
    # single-failure records, only the 3 recurring failures.
    evidence_ids = {ref["event_id"] for ref in proposal["evidence"]}
    assert evidence_ids == {"sha256:e1", "sha256:e2", "sha256:e3"}
    # Proposal JSON file landed on disk.
    proposal_path = Path(routing_gaps[0]["paths"]["proposal_json"])
    assert proposal_path.exists()


def _write_proposal(path: Path, *, proposal_id: str, module: Path, changes: list, targets: list = None) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": proposal_id,
                "title": proposal_id,
                "scope": {"modules": [str(module)], "targets": targets or []},
                "evidence": [{"event_id": f"sha256:{proposal_id}", "reason": "test"}],
                "changes": changes,
                "evaluation": {"commands": [], "status": "not_run"},
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )


def test_candidate_patch_class_add_target_inserts_new_target(tmp_path: Path) -> None:
    module = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  existing.task:
    steps:
      - inspect
""",
    )
    proposal_path = tmp_path / "add_target.proposal.json"
    _write_proposal(
        proposal_path,
        proposal_id="add-target",
        module=module,
        changes=[
            {
                "type": "add_target",
                "module": str(module),
                "target": "new.task",
                "definition": {
                    "match": {"user_intent": ["do new thing"]},
                    "steps": [{"action": "do_new"}],
                },
            }
        ],
    )
    from agentmf.evolution import create_candidate_patch_payload

    result = create_candidate_patch_payload(proposal_file=proposal_path, out_dir=tmp_path / "cands", write=False)
    assert result.ok, result.diagnostics.format()
    assert result.payload["patch_status"] == "generated"
    assert "+  new.task:" in result.payload["patch"]


def test_candidate_patch_class_add_dependency_appends_dep_edge(tmp_path: Path) -> None:
    module = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  child.task:
    steps:
      - inspect
  parent.task:
    steps:
      - inspect
""",
    )
    proposal_path = tmp_path / "add_dep.proposal.json"
    _write_proposal(
        proposal_path,
        proposal_id="add-dep",
        module=module,
        changes=[
            {
                "type": "add_dependency",
                "module": str(module),
                "target": "child.task",
                "add_deps": ["parent.task"],
            }
        ],
    )
    from agentmf.evolution import create_candidate_patch_payload, create_compile_evaluate_payload

    patch = create_candidate_patch_payload(proposal_file=proposal_path, out_dir=tmp_path / "cands", write=False)
    eval_ = create_compile_evaluate_payload(proposal_file=proposal_path, workspace_dir=tmp_path / "ws", write=True)
    assert patch.ok and eval_.ok, (patch.diagnostics.format(), eval_.diagnostics.format())
    candidate = load_source(Path(eval_.payload["candidate_files"][0]["path"]))
    assert "parent.task" in candidate.targets["child.task"].deps


def test_candidate_patch_class_deprecate_skill_annotates_implementation(tmp_path: Path) -> None:
    module = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  legacy.foo:
    description: legacy.
    implementation:
      source: skills/foo.md
    match:
      user_intent:
        - foo
""",
    )
    proposal_path = tmp_path / "deprecate.proposal.json"
    _write_proposal(
        proposal_path,
        proposal_id="deprecate",
        module=module,
        changes=[
            {
                "type": "deprecate_skill",
                "module": str(module),
                "skill": "legacy.foo",
                "reason": "superseded by core.foo",
                "replaced_by": "core.foo",
            }
        ],
    )
    from agentmf.evolution import create_candidate_patch_payload, create_compile_evaluate_payload

    patch = create_candidate_patch_payload(proposal_file=proposal_path, out_dir=tmp_path / "cands", write=False)
    eval_ = create_compile_evaluate_payload(proposal_file=proposal_path, workspace_dir=tmp_path / "ws", write=True)
    assert patch.ok and eval_.ok, (patch.diagnostics.format(), eval_.diagnostics.format())
    candidate = load_source(Path(eval_.payload["candidate_files"][0]["path"]))
    impl = candidate.skills["legacy.foo"].implementation
    assert impl["deprecated"] is True
    assert impl["deprecation_reason"] == "superseded by core.foo"
    assert impl["replaced_by"] == "core.foo"


def test_candidate_patch_class_add_registry_metadata_attaches_provenance(tmp_path: Path) -> None:
    module = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  plugins.docs:
    description: docs.
    implementation:
      source: skills/docs.md
    match:
      user_intent:
        - docs
""",
    )
    proposal_path = tmp_path / "registry.proposal.json"
    _write_proposal(
        proposal_path,
        proposal_id="registry",
        module=module,
        changes=[
            {
                "type": "add_registry_metadata",
                "module": str(module),
                "skill": "plugins.docs",
                "metadata": {"origin": "openclaw", "version": "1.2.3", "signed_by": "registry@openclaw"},
            }
        ],
    )
    from agentmf.evolution import create_candidate_patch_payload, create_compile_evaluate_payload

    patch = create_candidate_patch_payload(proposal_file=proposal_path, out_dir=tmp_path / "cands", write=False)
    eval_ = create_compile_evaluate_payload(proposal_file=proposal_path, workspace_dir=tmp_path / "ws", write=True)
    assert patch.ok and eval_.ok, (patch.diagnostics.format(), eval_.diagnostics.format())
    candidate = load_source(Path(eval_.payload["candidate_files"][0]["path"]))
    registry = candidate.skills["plugins.docs"].implementation["registry_metadata"]
    assert registry["origin"] == "openclaw"
    assert registry["version"] == "1.2.3"


def test_candidate_patch_class_add_benchmark_case_appends_case(tmp_path: Path) -> None:
    module = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.review:
    steps:
      - inspect
""",
    )
    proposal_path = tmp_path / "benchmark.proposal.json"
    _write_proposal(
        proposal_path,
        proposal_id="benchmark",
        module=module,
        changes=[
            {
                "type": "add_benchmark_case",
                "module": str(module),
                "target": "skill.review",
                "case": {"id": "review-1", "instruction": "review the diff", "expected_target": "skill.review"},
            }
        ],
    )
    from agentmf.evolution import create_candidate_patch_payload, create_compile_evaluate_payload

    patch = create_candidate_patch_payload(proposal_file=proposal_path, out_dir=tmp_path / "cands", write=False)
    eval_ = create_compile_evaluate_payload(proposal_file=proposal_path, workspace_dir=tmp_path / "ws", write=True)
    assert patch.ok and eval_.ok, (patch.diagnostics.format(), eval_.diagnostics.format())
    candidate = load_source(Path(eval_.payload["candidate_files"][0]["path"]))
    cases = candidate.targets["skill.review"].output_schema["benchmark_cases"]
    assert any(c["id"] == "review-1" for c in cases)


def test_candidate_patch_class_update_permission_guard_sets_rule(tmp_path: Path) -> None:
    module = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.foo:
    steps:
      - inspect
permissions:
  bash:
    'ls *': allow
""",
    )
    proposal_path = tmp_path / "perm.proposal.json"
    _write_proposal(
        proposal_path,
        proposal_id="perm",
        module=module,
        changes=[
            {
                "type": "update_permission_guard",
                "module": str(module),
                "tool": "bash",
                "pattern": "npm install*",
                "action": "ask",
            }
        ],
    )
    from agentmf.evolution import create_candidate_patch_payload, create_compile_evaluate_payload

    patch = create_candidate_patch_payload(proposal_file=proposal_path, out_dir=tmp_path / "cands", write=False)
    eval_ = create_compile_evaluate_payload(proposal_file=proposal_path, workspace_dir=tmp_path / "ws", write=True)
    assert patch.ok and eval_.ok, (patch.diagnostics.format(), eval_.diagnostics.format())
    candidate_text = Path(eval_.payload["candidate_files"][0]["path"]).read_text()
    assert "npm install*: ask" in candidate_text


def test_candidate_patch_class_split_module_moves_skills_and_targets(tmp_path: Path) -> None:
    source_module = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  keep.me:
    description: stay.
    implementation:
      source: skills/keep.md
  move.me:
    description: move.
    implementation:
      source: skills/move.md
targets:
  keep.task:
    steps:
      - inspect
  move.task:
    steps:
      - inspect
""",
    )
    target_module = tmp_path / "moved" / "AgentMakefile"
    proposal_path = tmp_path / "split.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "split",
                "title": "split",
                "scope": {"modules": [str(source_module), str(target_module)], "targets": []},
                "evidence": [{"event_id": "sha256:split", "reason": "test"}],
                "changes": [
                    {
                        "type": "split_module",
                        "source_module": str(source_module),
                        "target_module": str(target_module),
                        "skills": ["move.me"],
                        "targets": ["move.task"],
                    }
                ],
                "evaluation": {"commands": [], "status": "not_run"},
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )
    from agentmf.evolution import create_compile_evaluate_payload

    eval_ = create_compile_evaluate_payload(proposal_file=proposal_path, workspace_dir=tmp_path / "ws", write=True)
    assert eval_.ok, eval_.diagnostics.format()
    candidates = {entry["source"]: Path(entry["path"]) for entry in eval_.payload["candidate_files"]}
    new_source = load_source(candidates[str(source_module)])
    new_target = load_source(candidates[str(target_module)])
    assert "move.me" not in new_source.skills
    assert "move.task" not in new_source.targets
    assert "keep.me" in new_source.skills
    assert "move.me" in new_target.skills
    assert "move.task" in new_target.targets


def test_candidate_patch_generator_prunes_match_terms(tmp_path: Path) -> None:
    """Mirror of update_match_terms: prune_match_terms removes specified
    entries from a target's match.user_intent so overly-broad triggers
    that cause false positives can be retired. Canonical source stays
    untouched; only the candidate workspace gets the trimmed module.
    """
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.plugins.documents:
    match:
      user_intent:
        - Create
        - edit Word documents
        - render docx PDFs
    steps:
      - action: handle_documents
""",
    )
    proposal_path = tmp_path / "prune.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "amf-evo-prune",
                "title": "Prune broad match terms from plugins.documents",
                "scope": {"modules": [str(module_path)], "targets": ["skill.plugins.documents"]},
                "evidence": [{"event_id": "sha256:prune", "reason": "broad single-word matcher"}],
                "changes": [
                    {
                        "type": "prune_match_terms",
                        "module": str(module_path),
                        "target": "skill.plugins.documents",
                        "remove_terms": ["Create"],
                    }
                ],
                "evaluation": {"commands": [], "status": "not_run"},
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )

    from agentmf.evolution import create_candidate_patch_payload, create_compile_evaluate_payload

    patch_result = create_candidate_patch_payload(
        proposal_file=proposal_path,
        out_dir=tmp_path / "candidates",
        write=False,
    )
    eval_result = create_compile_evaluate_payload(
        proposal_file=proposal_path,
        workspace_dir=tmp_path / "ws",
        write=True,
    )

    assert patch_result.ok, patch_result.diagnostics.format()
    assert patch_result.payload["patch_status"] == "generated"
    assert patch_result.payload["unsupported_changes"] == []
    assert "-        - Create" in patch_result.payload["patch"]
    assert eval_result.ok, eval_result.diagnostics.format()

    candidate_path = Path(eval_result.payload["candidate_files"][0]["path"])
    candidate_source = load_source(candidate_path)
    assert candidate_source.targets["skill.plugins.documents"].match["user_intent"] == [
        "edit Word documents",
        "render docx PDFs",
    ]
    # Canonical source untouched.
    assert "Create" in load_source(module_path).targets["skill.plugins.documents"].match["user_intent"]


def test_dream_mode_drifted_permissions_proposes_review_for_recurring_denials(tmp_path: Path) -> None:
    """Benchmark evidence reporting recurring denied_tool_calls on the same
    (target, tool, pattern) triple should surface as an
    investigate_permission_drift proposal. Single denials don't qualify
    as "drift" yet — threshold mirrors the recurring_routing_gap detector.
    """
    evidence_root = tmp_path / ".agentmf" / "evolution" / "evidence" / "benchmarks"
    evidence_root.mkdir(parents=True)
    evidence_file = evidence_root / "benchmark.jsonl"
    records = [
        {
            "version": 1,
            "event_id": "sha256:b1",
            "timestamp": "2026-05-27T00:00:00Z",
            "source": "benchmark",
            "request_fingerprint": "sha256:r1",
            "selected_target": "skill.coding.review",
            "summary": {
                "denied_tool_calls": [{"target": "skill.coding.review", "tool": "bash", "pattern": "npm install*"}],
            },
        },
        {
            "version": 1,
            "event_id": "sha256:b2",
            "timestamp": "2026-05-27T00:00:01Z",
            "source": "benchmark",
            "request_fingerprint": "sha256:r2",
            "selected_target": "skill.coding.review",
            "summary": {
                "denied_tool_calls": [{"target": "skill.coding.review", "tool": "bash", "pattern": "npm install*"}],
            },
        },
        {
            "version": 1,
            "event_id": "sha256:b3",
            "timestamp": "2026-05-27T00:00:02Z",
            "source": "benchmark",
            "request_fingerprint": "sha256:r3",
            "selected_target": "skill.coding.review",
            "summary": {
                # Single occurrence; below the recurring threshold.
                "denied_tool_calls": [{"target": "skill.coding.review", "tool": "bash", "pattern": "rm -rf*"}],
            },
        },
    ]
    evidence_file.write_text("\n".join(json.dumps(r) for r in records) + "\n")

    from agentmf.evolution import create_dream_mode_payload

    result = create_dream_mode_payload(
        evidence_dir=tmp_path / ".agentmf" / "evolution" / "evidence",
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        timestamp="2026-05-27T01:00:00Z",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    drift_proposals = [
        p
        for p in result.payload["proposals"]
        if p["proposal"]["changes"][0]["type"] == "investigate_permission_drift"
    ]
    # Only the npm install pattern recurred (2 denials); rm -rf occurred once
    # and is below threshold.
    assert len(drift_proposals) == 1
    change = drift_proposals[0]["proposal"]["changes"][0]
    assert change["target"] == "skill.coding.review"
    assert change["tool"] == "bash"
    assert change["pattern"] == "npm install*"
    assert change["denial_count"] == 2
    assert sorted(change["sample_event_ids"]) == ["sha256:b1", "sha256:b2"]
    # Not a fix yet — patch generator can't act on this class.
    assert drift_proposals[0]["patch_status"] == "skipped_unsupported_change"


def test_dream_mode_missing_match_terms_proposes_update_for_user_feedback(tmp_path: Path) -> None:
    """user_feedback evidence saying "request X should have routed to target Y"
    must surface as an update_match_terms proposal that adds the request to
    Y's match.user_intent. The proposal must be patch-generatable end-to-end.
    """
    module_path = tmp_path / "plugins" / "AgentMakefile"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        """\
version: "0.1"
skills:
  plugins.presentations:
    namespace: smoke
    description: Build slide decks.
    implementation:
      source: skills/presentations/SKILL.md
      relative_source: plugins/presentations/SKILL.md
    match:
      user_intent:
        - build slides
targets:
  skill.plugins.presentations:
    match:
      user_intent:
        - build slides
    skills:
      - smoke:plugins.presentations
    steps:
      - use_skill: smoke:plugins.presentations
"""
    )
    evidence_root = tmp_path / ".agentmf" / "evolution" / "evidence"

    from agentmf.evolution import (
        create_candidate_patch_payload,
        create_dream_mode_payload,
        create_evolution_evidence_payload,
    )

    create_evolution_evidence_payload(
        source="user_feedback",
        payload={
            "request": "create a presentation about Q4 results",
            "intended_module": str(module_path),
            "intended_target": "skill.plugins.presentations",
            "actual_target": "skill.plugins.documents",
        },
        out_dir=evidence_root,
        write=True,
    )
    create_evolution_evidence_payload(
        source="user_feedback",
        payload={
            "request": "draft Q4 board slides",
            "intended_module": str(module_path),
            "intended_target": "skill.plugins.presentations",
            "actual_target": None,
        },
        out_dir=evidence_root,
        write=True,
    )

    result = create_dream_mode_payload(
        evidence_dir=evidence_root,
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        timestamp="2026-05-27T00:00:00Z",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    match_proposals = [
        p
        for p in result.payload["proposals"]
        if p["proposal"]["changes"][0]["type"] == "update_match_terms"
    ]
    assert len(match_proposals) == 1, [p["proposal"]["changes"][0] for p in result.payload["proposals"]]
    proposal_wrapper = match_proposals[0]
    proposal = proposal_wrapper["proposal"]
    change = proposal["changes"][0]
    assert change["module"] == str(module_path)
    assert change["target"] == "skill.plugins.presentations"
    assert "create a presentation about Q4 results" in change["add_terms"]
    assert "draft Q4 board slides" in change["add_terms"]
    assert proposal_wrapper["patch_status"] == "would_generate_patch"
    # Both feedback records are attached as evidence.
    evidence_ids = {ref["event_id"] for ref in proposal["evidence"]}
    assert len(evidence_ids) == 2

    # End-to-end: the dream-emitted proposal really is patch-generatable.
    proposal_path = Path(proposal_wrapper["paths"]["proposal_json"])
    patch_result = create_candidate_patch_payload(
        proposal_file=proposal_path,
        out_dir=tmp_path / "patch",
        write=True,
    )
    assert patch_result.ok, patch_result.diagnostics.format()
    assert patch_result.payload["patch_status"] == "generated"


def test_dream_mode_category_resplit_suggests_sub_module_split(tmp_path: Path) -> None:
    """When an already-imported module hosts many skills sharing a common
    second-level path segment in their `relative_source`, the detector
    suggests splitting them into a sub-module. Sub-categories below the
    threshold are not flagged.
    """
    module_path = tmp_path / "modules" / "openclaw" / ".tmp" / "AgentMakefile"
    module_path.parent.mkdir(parents=True)
    # Build a synthetic module: 12 skills under `.tmp/bundled-marketplaces/`,
    # 4 skills under `.tmp/plugins/`, both nested under the same module.
    skills_yaml_lines = ["version: \"0.1\"", "skills:"]
    for index in range(12):
        skills_yaml_lines.extend(
            [
                f"  .tmp.bundled-{index:02d}:",
                "    description: bundled marketplace skill.",
                "    implementation:",
                f"      relative_source: .tmp/bundled-marketplaces/marketplace-{index}/skills/skill-{index}/SKILL.md",
                "    match:",
                "      user_intent:",
                f"        - bundled {index}",
            ]
        )
    for index in range(4):
        skills_yaml_lines.extend(
            [
                f"  .tmp.plugin-{index:02d}:",
                "    description: cached plugin skill.",
                "    implementation:",
                f"      relative_source: .tmp/plugins/plugin-{index}/SKILL.md",
                "    match:",
                "      user_intent:",
                f"        - plugin {index}",
            ]
        )
    module_path.write_text("\n".join(skills_yaml_lines) + "\n")

    evidence_dir = tmp_path / ".agentmf" / "evolution" / "evidence"

    from agentmf.evolution import create_dream_mode_payload, create_evolution_evidence_payload

    create_evolution_evidence_payload(
        source="openclaw_import",
        payload={
            "openclaw_import": {
                "root_path": str(tmp_path / "modules" / "openclaw" / "AgentMakefile"),
                "skill_count": 16,
                "category_count": 1,
                "categories": [{"name": ".tmp", "skill_count": 16}],
                "curator_evidence": {
                    "skill_count": 16,
                    "category_count": 1,
                    "categories": {".tmp": 16},
                    "duplicate_original_names": {},
                    "module_paths": [str(module_path)],
                },
            }
        },
        out_dir=evidence_dir,
        write=True,
    )

    result = create_dream_mode_payload(
        evidence_dir=evidence_dir,
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        timestamp="2026-05-28T00:00:00Z",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    resplits = [
        p
        for p in result.payload["proposals"]
        if p["proposal"]["changes"][0]["type"] == "investigate_category_resplit"
    ]
    # Only the 12-skill bundled-marketplaces group hits the >=10 threshold.
    assert len(resplits) == 1
    change = resplits[0]["proposal"]["changes"][0]
    assert change["module"] == str(module_path)
    assert change["sub_category"] == "bundled-marketplaces"
    assert change["skill_count"] == 12
    assert isinstance(change["sample_skills"], list) and 1 <= len(change["sample_skills"]) <= 5
    # Non-patch class.
    assert resplits[0]["patch_status"] == "skipped_unsupported_change"


def test_dream_mode_trust_annotation_flags_cache_derived_skills(tmp_path: Path) -> None:
    """Skills whose implementation.relative_source comes from ephemeral
    cache paths (`.tmp/` or `/cache/`) should be tagged with
    registry_metadata so downstream tools know the source isn't
    canonical. The detector emits an add_registry_metadata change per
    such skill, bundled per module.
    """
    module_path = tmp_path / "uncategorized" / "AgentMakefile"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        """\
version: "0.1"
skills:
  uncategorized.canonical:
    description: canonical skill.
    implementation:
      source: /some/canonical/skills/foo/SKILL.md
      relative_source: uncategorized/canonical/SKILL.md
    match:
      user_intent:
        - foo
  uncategorized.from-tmp:
    description: cached scratch skill.
    implementation:
      source: /Users/x/.codex/.tmp/scratch/SKILL.md
      relative_source: .tmp/scratch/SKILL.md
    match:
      user_intent:
        - scratch
  uncategorized.from-plugin-cache:
    description: cached marketplace skill.
    implementation:
      source: /Users/x/.codex/plugins/cache/openclaw-bundled/foo/SKILL.md
      relative_source: plugins/cache/openclaw-bundled/foo/SKILL.md
    match:
      user_intent:
        - plugin
"""
    )
    evidence_dir = tmp_path / ".agentmf" / "evolution" / "evidence"

    from agentmf.evolution import create_dream_mode_payload, create_evolution_evidence_payload

    create_evolution_evidence_payload(
        source="openclaw_import",
        payload={
            "openclaw_import": {
                "root_path": str(tmp_path / "modules" / "openclaw" / "AgentMakefile"),
                "skill_count": 3,
                "category_count": 1,
                "categories": [{"name": "uncategorized", "skill_count": 3}],
                "curator_evidence": {
                    "skill_count": 3,
                    "category_count": 1,
                    "categories": {"uncategorized": 3},
                    "duplicate_original_names": {},
                    "module_paths": [str(module_path)],
                },
            }
        },
        out_dir=evidence_dir,
        write=True,
    )

    result = create_dream_mode_payload(
        evidence_dir=evidence_dir,
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        timestamp="2026-05-27T00:00:00Z",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    trust_proposals = [
        p
        for p in result.payload["proposals"]
        if any(c["type"] == "add_registry_metadata" for c in p["proposal"]["changes"])
    ]
    assert len(trust_proposals) == 1
    proposal = trust_proposals[0]["proposal"]
    flagged_skills = {c["skill"] for c in proposal["changes"] if c["type"] == "add_registry_metadata"}
    assert flagged_skills == {"uncategorized.from-tmp", "uncategorized.from-plugin-cache"}
    assert "uncategorized.canonical" not in flagged_skills
    # Patch class is supported, so dream marks it accordingly.
    assert trust_proposals[0]["patch_status"] == "would_generate_patch"


def test_dream_mode_heavy_tool_warning_flags_risky_skills(tmp_path: Path) -> None:
    """Skills whose description or match.user_intent mentions risky shell
    tools (sudo, rm -rf, docker, kubectl, ssh) surface as
    investigate_heavy_tool_usage proposals so a reviewer can decide
    whether the skill should be gated by stricter permission rules.
    """
    module_path = tmp_path / "plugins" / "AgentMakefile"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        """\
version: "0.1"
skills:
  plugins.safe-tool:
    description: simple text formatter.
    implementation:
      source: skills/safe-tool/SKILL.md
      relative_source: plugins/safe-tool/SKILL.md
    match:
      user_intent:
        - format text
  plugins.devops-helper:
    description: Use to run docker compose stacks and kubectl rollouts.
    implementation:
      source: skills/devops/SKILL.md
      relative_source: plugins/devops/SKILL.md
    match:
      user_intent:
        - manage clusters
  plugins.cleaner:
    description: Removes temp dirs.
    implementation:
      source: skills/cleaner/SKILL.md
      relative_source: plugins/cleaner/SKILL.md
    match:
      user_intent:
        - run rm -rf on the tmp dir
"""
    )
    evidence_dir = tmp_path / ".agentmf" / "evolution" / "evidence"

    from agentmf.evolution import create_dream_mode_payload, create_evolution_evidence_payload

    create_evolution_evidence_payload(
        source="openclaw_import",
        payload={
            "openclaw_import": {
                "root_path": str(tmp_path / "modules" / "openclaw" / "AgentMakefile"),
                "skill_count": 3,
                "category_count": 1,
                "categories": [{"name": "plugins", "skill_count": 3}],
                "curator_evidence": {
                    "skill_count": 3,
                    "category_count": 1,
                    "categories": {"plugins": 3},
                    "duplicate_original_names": {},
                    "module_paths": [str(module_path)],
                },
            }
        },
        out_dir=evidence_dir,
        write=True,
    )

    result = create_dream_mode_payload(
        evidence_dir=evidence_dir,
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        timestamp="2026-05-27T00:00:00Z",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    heavy = [
        p
        for p in result.payload["proposals"]
        if p["proposal"]["changes"][0]["type"] == "investigate_heavy_tool_usage"
    ]
    flagged = {p["proposal"]["changes"][0]["skill"] for p in heavy}
    assert "plugins.devops-helper" in flagged
    assert "plugins.cleaner" in flagged
    assert "plugins.safe-tool" not in flagged
    # investigate_* is not a supported patch class, so dream marks as skipped.
    for proposal in heavy:
        assert proposal["patch_status"] == "skipped_unsupported_change"
        change = proposal["proposal"]["changes"][0]
        assert isinstance(change["matched_tokens"], list) and change["matched_tokens"]


def test_dream_mode_benchmark_case_suggester_for_popular_targets(tmp_path: Path) -> None:
    """When plugin_payload evidence shows the same selected_target
    chosen >=3 times, the suggester proposes adding a benchmark case to
    cement the target as a regression-tested route. The target's module
    is resolved by scanning modules referenced in any openclaw_import
    evidence in the same evidence set.
    """
    module_path = tmp_path / "plugins" / "AgentMakefile"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        """\
version: "0.1"
targets:
  skill.plugins.docs:
    match:
      user_intent:
        - write the document
    skills: []
    steps:
      - inspect
"""
    )
    evidence_dir = tmp_path / ".agentmf" / "evolution" / "evidence"

    from agentmf.evolution import create_dream_mode_payload, create_evolution_evidence_payload

    # OpenClaw import evidence so the suggester can resolve target -> module.
    create_evolution_evidence_payload(
        source="openclaw_import",
        payload={
            "openclaw_import": {
                "root_path": str(tmp_path / "modules" / "openclaw" / "AgentMakefile"),
                "skill_count": 0,
                "category_count": 1,
                "categories": [{"name": "plugins", "skill_count": 0}],
                "curator_evidence": {
                    "skill_count": 0,
                    "category_count": 1,
                    "categories": {"plugins": 0},
                    "duplicate_original_names": {},
                    "module_paths": [str(module_path)],
                },
            }
        },
        out_dir=evidence_dir,
        write=True,
    )

    # Three plugin_payload records picking the same target.
    for index in range(3):
        create_evolution_evidence_payload(
            source="plugin_payload",
            payload={
                "request": f"write the document about quarter {index}",
                "selected_target": "skill.plugins.docs",
                "selected_targets": ["skill.plugins.docs"],
                "selected_skills": [],
            },
            out_dir=evidence_dir,
            write=True,
        )

    result = create_dream_mode_payload(
        evidence_dir=evidence_dir,
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        timestamp="2026-05-27T00:00:00Z",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    suggestions = [
        p
        for p in result.payload["proposals"]
        if p["proposal"]["changes"][0]["type"] == "add_benchmark_case"
    ]
    assert len(suggestions) == 1
    change = suggestions[0]["proposal"]["changes"][0]
    assert change["target"] == "skill.plugins.docs"
    assert change["module"] == str(module_path)
    assert change["case"]["expected_target"] == "skill.plugins.docs"
    assert change["case"]["instruction"]  # non-empty representative request
    assert suggestions[0]["patch_status"] == "would_generate_patch"


def test_dream_mode_proposes_pruning_broad_terms_from_actual_target(tmp_path: Path) -> None:
    """When user_feedback says request X mis-routed to actual_target Y instead
    of intended Z, dream must (a) add distinguishing terms to Z AND (b) propose
    pruning the broad, short single-word term on Y that caused the false
    positive. Output is one combined proposal with both change types so the
    patch generator applies them atomically.
    """
    module_path = tmp_path / "plugins" / "AgentMakefile"
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        """\
version: "0.1"
targets:
  skill.plugins.documents:
    match:
      user_intent:
        - Create
        - edit Word documents
    steps:
      - action: handle_documents
  skill.plugins.presentations:
    match:
      user_intent:
        - build slides
    steps:
      - action: handle_presentations
"""
    )
    evidence_root = tmp_path / ".agentmf" / "evolution" / "evidence"

    from agentmf.evolution import (
        create_candidate_patch_payload,
        create_dream_mode_payload,
        create_evolution_evidence_payload,
    )

    create_evolution_evidence_payload(
        source="user_feedback",
        payload={
            "request": "create a presentation about Q4 results",
            "intended_module": str(module_path),
            "intended_target": "skill.plugins.presentations",
            "actual_target": "skill.plugins.documents",
        },
        out_dir=evidence_root,
        write=True,
    )

    result = create_dream_mode_payload(
        evidence_dir=evidence_root,
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        timestamp="2026-05-27T00:00:00Z",
        write=True,
    )

    assert result.ok, result.diagnostics.format()
    match_proposals = [
        p
        for p in result.payload["proposals"]
        if any(c["type"] in {"update_match_terms", "prune_match_terms"} for c in p["proposal"]["changes"])
    ]
    assert len(match_proposals) == 1
    proposal = match_proposals[0]["proposal"]
    change_types = [c["type"] for c in proposal["changes"]]
    assert "update_match_terms" in change_types
    assert "prune_match_terms" in change_types

    prune_change = next(c for c in proposal["changes"] if c["type"] == "prune_match_terms")
    assert prune_change["target"] == "skill.plugins.documents"
    assert "Create" in prune_change["remove_terms"]
    # Multi-word legitimate terms ("edit Word documents") must NOT be pruned —
    # only the broad single-word distractor goes.
    assert "edit Word documents" not in prune_change["remove_terms"]

    # End-to-end: the combined proposal generates a patch covering both classes.
    proposal_path = Path(match_proposals[0]["paths"]["proposal_json"])
    patch_result = create_candidate_patch_payload(
        proposal_file=proposal_path,
        out_dir=tmp_path / "patch",
        write=True,
    )
    assert patch_result.ok, patch_result.diagnostics.format()
    assert patch_result.payload["patch_status"] == "generated"


def test_cli_plugin_install_accepts_source_for_guidance_md(tmp_path: Path, capsys) -> None:
    """PAD-014 follow-up: `agentmf plugin install --source <markdown>` should
    route through `guidance_scanner` and emit a guidance-index AgentMakefile,
    parallel to the existing `--skills-dir` path. `--skills-dir` stays
    optional when `--source` is provided.
    """
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text(
        "# Project Agents\n\n"
        "## Routing Guidance\n\n"
        "Use when deciding which agent target to invoke.\n"
    )
    out_path = tmp_path / "plugin" / "AgentMakefile"

    exit_code = main(
        [
            "plugin",
            "install",
            "--source",
            str(agents_path),
            "--host",
            "generic",
            "--out",
            str(out_path),
            "--write",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    install = payload["plugin_install_payload"]
    assert install["agentmakefile"]["wrote"] is True
    assert install["sources"] == [str(agents_path)]
    assert install["skills_dirs"] == []
    written = out_path.read_text()
    data = yaml.safe_load(written)
    assert data["metadata"]["module_type"] == "guidance-index"
    assert any("routing-guidance" in name for name in data["targets"])


def test_cli_guidance_scan_imports_agents_and_claude_md(tmp_path: Path, capsys) -> None:
    """`agentmf guidance scan` reads heterogeneous guidance Markdown
    (AGENTS.md, CLAUDE.md, standalone SKILL.md, plain markdown) and
    emits one AgentMakefile with `module_type: guidance-index` and one
    target per parsed section.
    """
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text(
        "# Project Agents\n\n"
        "## Review Workflow\n\n"
        "Use this section when reviewing code.\n"
    )
    claude_path = tmp_path / "CLAUDE.md"
    claude_path.write_text(
        "# Project Claude\n\n"
        "## Planning Guidance\n\n"
        "Use this section when planning multi-step work.\n"
    )
    out_path = tmp_path / "modules" / "imported" / "AgentMakefile"

    exit_code = main(
        [
            "guidance",
            "scan",
            "--source",
            str(agents_path),
            "--source",
            str(claude_path),
            "--out",
            str(out_path),
            "--write",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["guidance_scan"]["wrote"] is True
    assert payload["guidance_scan"]["section_count"] == 2

    written = out_path.read_text()
    data = yaml.safe_load(written)
    assert data["metadata"]["module_type"] == "guidance-index"
    target_names = sorted(data["targets"])
    assert any("review-workflow" in name for name in target_names)
    assert any("planning-guidance" in name for name in target_names)


def test_benchmark_suite_parses_valid_yaml(tmp_path: Path) -> None:
    """BENCH-002: parse a suite YAML with required top-level fields and
    surface diagnostics for missing/invalid task ids."""
    suite_path = tmp_path / "ok.yaml"
    suite_path.write_text(
        """\
version: 1
suite:
  id: example
  title: Example deterministic suite
  description: Self-hosting routing checks.
tasks:
  - id: implement-feature
    request: please implement this feature
    expected_targets:
      - methodology.code_change
  - id: write-plan
    request: write an implementation plan
    expected_targets:
      - methodology.plan
"""
    )

    from agentmf.benchmark_suite import parse_suite_file

    result = parse_suite_file(suite_path)

    assert result.ok, result.diagnostics.format()
    assert result.suite.suite_id == "example"
    assert result.suite.title == "Example deterministic suite"
    assert [task.task_id for task in result.suite.tasks] == ["implement-feature", "write-plan"]
    assert result.suite.tasks[0].expected_targets == ["methodology.code_change"]


def test_benchmark_suite_parser_diagnoses_missing_fields(tmp_path: Path) -> None:
    suite_path = tmp_path / "bad.yaml"
    suite_path.write_text(
        """\
version: 1
suite:
  id: bad
tasks:
  - request: missing task id here
  - id: ok
    request: ok task
    expected_targets:
      - target.ok
"""
    )

    from agentmf.benchmark_suite import parse_suite_file

    result = parse_suite_file(suite_path)

    assert not result.ok
    codes = [item.code for item in result.diagnostics.items]
    assert "AMF250" in codes  # missing task id


def test_benchmark_suite_run_deterministic_pass_and_fail(tmp_path: Path) -> None:
    """BENCH-003 + BENCH-004: deterministic-selection adapter routes each
    task through the AgentMakefile and reports pass/fail per task."""
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.review:
    priority: 70
    match:
      user_intent:
        - review this diff
    steps:
      - action: inspect
""",
    )
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        f"""\
version: 1
suite:
  id: routing
  title: routing
agentmakefile: {module_path}
tasks:
  - id: t-hits
    request: review this diff carefully
    expected_targets:
      - skill.review
  - id: t-miss
    request: totally unrelated zebra request
    expected_targets:
      - skill.review
"""
    )

    from agentmf.benchmark_suite import create_suite_payload

    result = create_suite_payload(suite_file=suite_path, agentmakefile=None, adapter="deterministic-selection")

    assert result.ok, result.diagnostics.format()
    payload = result.payload
    assert payload["summary"] == {"total": 2, "passed": 1, "failed": 1, "skipped": 0}
    by_id = {task["task_id"]: task for task in payload["tasks"]}
    assert by_id["t-hits"]["status"] == "passed"
    assert by_id["t-hits"]["actual_targets"] == ["skill.review"]
    assert by_id["t-miss"]["status"] == "failed"


def test_benchmark_suite_markdown_report_renders_summary(tmp_path: Path) -> None:
    """BENCH-004 markdown emitter includes title + summary + per-task table."""
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.x:
    priority: 70
    match:
      user_intent:
        - alpha
    steps:
      - action: a
""",
    )
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        f"""\
version: 1
suite:
  id: small
  title: Small suite
agentmakefile: {module_path}
tasks:
  - id: a
    request: alpha please
    expected_targets:
      - skill.x
"""
    )

    from agentmf.benchmark_suite import create_suite_payload, render_suite_markdown

    result = create_suite_payload(suite_file=suite_path, agentmakefile=None, adapter="deterministic-selection")
    md = render_suite_markdown(result.payload)

    assert "# Small suite" in md
    assert "passed=1" in md
    assert "skill.x" in md


def test_benchmark_suite_validates_expected_skills(tmp_path: Path) -> None:
    """The deterministic runner must compare each task's `expected_skills`
    against the skills bound by the selected target's pipeline. A
    matching skill keeps `passed`; a wrong/non-existent expected skill
    flips status to `failed` even when expected_targets matches.
    """
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  coding.review:
    namespace: smoke
    description: review skill.
    implementation:
      source: skills/review/SKILL.md
    match:
      user_intent:
        - review
targets:
  skill.review:
    priority: 70
    match:
      user_intent:
        - review the diff
    skills:
      - smoke:coding.review
    steps:
      - use_skill: smoke:coding.review
""",
    )
    suite_path = tmp_path / "skills.yaml"
    suite_path.write_text(
        f"""\
version: 1
suite:
  id: skills-check
  title: Skill hit-rate check
agentmakefile: {module_path}
tasks:
  - id: t-skill-hit
    request: review the diff carefully
    expected_targets:
      - skill.review
    expected_skills:
      - smoke:coding.review
  - id: t-skill-miss
    request: review the diff carefully
    expected_targets:
      - skill.review
    expected_skills:
      - smoke:nonexistent.skill
  - id: t-target-only
    request: review the diff carefully
    expected_targets:
      - skill.review
"""
    )

    from agentmf.benchmark_suite import create_suite_payload

    result = create_suite_payload(suite_file=suite_path, agentmakefile=None, adapter="deterministic-selection")

    assert result.ok, result.diagnostics.format()
    by_id = {task["task_id"]: task for task in result.payload["tasks"]}
    assert by_id["t-skill-hit"]["status"] == "passed"
    assert by_id["t-skill-hit"]["actual_skills"] == ["smoke:coding.review"]
    assert by_id["t-skill-hit"]["expected_skills"] == ["smoke:coding.review"]
    assert by_id["t-skill-miss"]["status"] == "failed"
    assert by_id["t-skill-miss"]["actual_skills"] == ["smoke:coding.review"]
    # A task without expected_skills still passes purely on target match.
    assert by_id["t-target-only"]["status"] == "passed"
    assert by_id["t-target-only"]["expected_skills"] == []
    # The aggregate summary reflects the skill check.
    assert result.payload["summary"] == {"total": 3, "passed": 2, "failed": 1, "skipped": 0}


def test_benchmark_suite_markdown_includes_skills_column_when_used(tmp_path: Path) -> None:
    """Markdown report grows a Skills column only when at least one task
    declares expected_skills. Suites without skill expectations keep the
    compact 4-column layout."""
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  coding.review:
    namespace: smoke
    description: review.
    implementation:
      source: skills/review/SKILL.md
    match:
      user_intent:
        - review
targets:
  skill.review:
    priority: 70
    match:
      user_intent:
        - review the diff
    skills:
      - smoke:coding.review
    steps:
      - use_skill: smoke:coding.review
""",
    )
    suite_path = tmp_path / "with-skills.yaml"
    suite_path.write_text(
        f"""\
version: 1
suite:
  id: with-skills
  title: with skills
agentmakefile: {module_path}
tasks:
  - id: a
    request: review the diff
    expected_targets:
      - skill.review
    expected_skills:
      - smoke:coding.review
"""
    )

    from agentmf.benchmark_suite import create_suite_payload, render_suite_markdown

    result = create_suite_payload(suite_file=suite_path, agentmakefile=None, adapter="deterministic-selection")
    md = render_suite_markdown(result.payload)

    assert "| Skills |" in md
    assert "smoke:coding.review" in md


def test_benchmark_suite_demo_file_parses(tmp_path: Path) -> None:
    """BENCH-005 demo suite file exists in benchmarks/ and parses."""
    from agentmf.benchmark_suite import parse_suite_file

    demo_path = Path(__file__).resolve().parent.parent / "benchmarks" / "agentmf-self-hosting.yaml"
    assert demo_path.exists(), f"demo suite missing: {demo_path}"
    result = parse_suite_file(demo_path)
    assert result.ok, result.diagnostics.format()
    assert len(result.suite.tasks) >= 3


def test_cli_benchmark_suite_fail_on_mismatch_returns_nonzero(tmp_path: Path, capsys) -> None:
    """`--fail-on-mismatch` flips exit code to 1 when any task fails so CI
    can gate promotion / merge on suite results."""
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.x:
    priority: 70
    match:
      user_intent:
        - alpha
    steps:
      - action: a
""",
    )
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        f"""\
version: 1
suite:
  id: fail-on-mismatch
  title: fail check
agentmakefile: {module_path}
tasks:
  - id: t-ok
    request: alpha please
    expected_targets:
      - skill.x
  - id: t-bad
    request: unrelated zebra request
    expected_targets:
      - skill.x
"""
    )

    # Without --fail-on-mismatch the CLI still returns 0 (parse/run ok).
    exit_clean = main(
        [
            "benchmark", "suite",
            "--suite", str(suite_path),
            "--adapter", "deterministic-selection",
            "--format", "json",
        ]
    )
    capsys.readouterr()
    assert exit_clean == 0

    # With the flag, a failing task flips exit to 1.
    exit_strict = main(
        [
            "benchmark", "suite",
            "--suite", str(suite_path),
            "--adapter", "deterministic-selection",
            "--format", "json",
            "--fail-on-mismatch",
        ]
    )
    capsys.readouterr()
    assert exit_strict == 1


def test_cli_benchmark_adapter_contract_emits_host_execution_schema(capsys) -> None:
    """BENCH-006: `agentmf benchmark adapter-contract --kind host-execution`
    emits a JSON contract describing the input + output schema a hosted
    agent runner must produce — without invoking a provider."""
    exit_code = main(
        [
            "benchmark", "adapter-contract",
            "--kind", "host-execution",
            "--format", "json",
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    contract = payload["benchmark_adapter_contract"]

    assert exit_code == 0
    assert contract["mode"] == "host_execution_adapter_contract"
    assert contract["adapter"]["kind"] == "host-execution"
    assert "input_contract" in contract and "output_contract" in contract
    # Selection-layer assumptions cross the boundary.
    assert "agentmf.selected_targets" in contract["input_contract"]["required_fields"]
    assert "prompt.stable_prefix.content" in contract["input_contract"]["required_fields"]
    # Output must at minimum tell us whether the task passed.
    assert "task_id" in contract["output_contract"]["required_fields"]
    assert "pass" in contract["output_contract"]["required_fields"]
    # Optional cost/wall-time fields available for budgeting.
    assert "cost_usd" in contract["output_contract"]["optional_fields"]
    assert "wall_time_ms" in contract["output_contract"]["optional_fields"]


def test_benchmark_suite_subprocess_adapter_runs_external_runner(tmp_path: Path) -> None:
    """BENCH-007 first host execution adapter: a `subprocess-execution`
    adapter pipes one JSON record per task into a configured external
    runner and reads back a JSON pass/fail record. Verifies the contract
    works end-to-end with a tiny Python runner script — no provider
    credentials required.
    """
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.review:
    priority: 70
    match:
      user_intent:
        - review the diff
    steps:
      - action: inspect
""",
    )
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        f"""\
version: 1
suite:
  id: subprocess-adapter
  title: subprocess adapter check
agentmakefile: {module_path}
tasks:
  - id: t-pass
    request: review the diff carefully
    expected_targets:
      - skill.review
  - id: t-fail
    request: review the diff carefully
    expected_targets:
      - skill.review
"""
    )
    runner_script = tmp_path / "runner.py"
    runner_script.write_text(
        "import sys, json\n"
        "record = json.loads(sys.stdin.read())\n"
        "result = {\n"
        "    'task_id': record['task_id'],\n"
        "    'pass': record['task_id'] == 't-pass',\n"
        "    'actual_target': 'skill.review',\n"
        "}\n"
        "sys.stdout.write(json.dumps(result))\n"
    )

    from agentmf.benchmark_suite import create_suite_payload

    import sys as _sys

    result = create_suite_payload(
        suite_file=suite_path,
        agentmakefile=None,
        adapter="subprocess-execution",
        runner_command=f"{_sys.executable} {runner_script}",
    )

    assert result.ok, result.diagnostics.format()
    summary = result.payload["summary"]
    assert summary == {"total": 2, "passed": 1, "failed": 1, "skipped": 0}
    by_id = {task["task_id"]: task for task in result.payload["tasks"]}
    assert by_id["t-pass"]["status"] == "passed"
    assert by_id["t-pass"]["actual_target"] == "skill.review"
    assert by_id["t-fail"]["status"] == "failed"


def test_benchmark_suite_subprocess_adapter_requires_runner_command(tmp_path: Path) -> None:
    """When --adapter subprocess-execution is requested without a runner
    command the suite returns a structured diagnostic and refuses to
    fabricate results."""
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.x:
    priority: 70
    match:
      user_intent:
        - alpha
    steps:
      - action: a
""",
    )
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        f"""\
version: 1
suite:
  id: no-runner
  title: no runner
agentmakefile: {module_path}
tasks:
  - id: a
    request: alpha please
    expected_targets:
      - skill.x
"""
    )

    from agentmf.benchmark_suite import create_suite_payload

    result = create_suite_payload(
        suite_file=suite_path,
        agentmakefile=None,
        adapter="subprocess-execution",
        runner_command=None,
    )

    assert not result.ok
    codes = [item.code for item in result.diagnostics.items]
    assert "AMF253" in codes


def test_cli_benchmark_suite_runs_and_emits_json(tmp_path: Path, capsys) -> None:
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.x:
    priority: 70
    match:
      user_intent:
        - alpha
    steps:
      - action: a
""",
    )
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        f"""\
version: 1
suite:
  id: cli
  title: cli
agentmakefile: {module_path}
tasks:
  - id: a
    request: alpha please
    expected_targets:
      - skill.x
"""
    )

    exit_code = main(
        [
            "benchmark",
            "suite",
            "--suite",
            str(suite_path),
            "--adapter",
            "deterministic-selection",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["benchmark_suite"]["summary"]["passed"] == 1


def test_openclaw_curator_creates_duplicate_skill_proposal(tmp_path: Path) -> None:
    evidence_file = tmp_path / "openclaw_import.jsonl"
    evidence_file.write_text(
        json.dumps(
            {
                "version": 1,
                "event_id": "sha256:openclaw",
                "timestamp": "2026-05-27T00:00:00Z",
                "source": "openclaw_import",
                "summary": {
                    "skill_count": 3,
                    "categories": {"coding": 3},
                    "duplicate_original_names": {
                        "review": ["coding/review/SKILL.md", "coding/review-alt/SKILL.md"]
                    },
                    "module_paths": ["coding/AgentMakefile"],
                },
                "artifact_refs": {"root_agentmakefile": "modules/openclaw/AgentMakefile"},
            }
        )
        + "\n"
    )

    from agentmf.evolution import create_openclaw_curator_payload

    result = create_openclaw_curator_payload(
        evidence_file=evidence_file,
        out_dir=tmp_path / ".agentmf" / "evolution" / "candidates",
        timestamp="2026-05-27T00:00:01Z",
        write=True,
    )

    proposal = result.payload["proposal"]["proposal"]

    assert result.ok, result.diagnostics.format()
    assert result.payload["mode"] == "openclaw_curator"
    assert proposal["title"] == "Curate duplicate OpenClaw skills"
    assert proposal["changes"][0]["type"] == "merge_duplicate_targets"
    assert proposal["changes"][0]["duplicate_original_names"] == {
        "review": ["coding/review/SKILL.md", "coding/review-alt/SKILL.md"]
    }


def test_cli_evo_patch_generate_and_evaluate_candidate(tmp_path: Path, capsys) -> None:
    module_path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.coding.review:
    match:
      user_intent:
        - review
    steps:
      - action: inspect
""",
    )
    proposal_path = tmp_path / "candidate.proposal.json"
    proposal_path.write_text(
        json.dumps(
            {
                "version": 1,
                "proposal_id": "amf-evo-cli",
                "title": "CLI patch and evaluate",
                "scope": {"modules": [str(module_path)], "targets": ["skill.coding.review"]},
                "evidence": [{"event_id": "sha256:evidence", "reason": "routing gap"}],
                "changes": [
                    {
                        "type": "update_match_terms",
                        "module": str(module_path),
                        "target": "skill.coding.review",
                        "add_terms": ["review code"],
                    }
                ],
                "evaluation": {"commands": [], "status": "not_run"},
                "promotion": {"status": "candidate", "requires_review": True},
            }
        )
    )
    patch_dir = tmp_path / ".agentmf" / "evolution" / "candidates"

    patch_exit = main(
        [
            "evo",
            "patch",
            "generate",
            "--proposal-file",
            str(proposal_path),
            "--out-dir",
            str(patch_dir),
            "--write",
            "--format",
            "json",
        ]
    )
    patch_payload = json.loads(capsys.readouterr().out)
    eval_exit = main(
        [
            "evo",
            "evaluate",
            "--proposal-file",
            str(proposal_path),
            "--workspace-dir",
            str(tmp_path / ".agentmf" / "evolution" / "worktrees" / "amf-evo-cli"),
            "--write",
            "--format",
            "json",
        ]
    )
    eval_payload = json.loads(capsys.readouterr().out)

    assert patch_exit == 0
    assert patch_payload["ok"] is True
    assert Path(patch_payload["candidate_patch"]["paths"]["patch"]).exists()
    assert eval_exit == 0
    assert eval_payload["ok"] is True
    assert eval_payload["compile_evaluate"]["promotion_report"]["status"] == "passed"


def test_cli_evo_dream_run_and_openclaw_curate(tmp_path: Path, capsys) -> None:
    evidence_dir = tmp_path / ".agentmf" / "evolution" / "evidence" / "registry"
    evidence_dir.mkdir(parents=True)
    evidence_file = evidence_dir / "openclaw_import.jsonl"
    evidence_file.write_text(
        json.dumps(
            {
                "version": 1,
                "event_id": "sha256:openclaw",
                "timestamp": "2026-05-27T00:00:00Z",
                "source": "openclaw_import",
                "summary": {
                    "skill_count": 3,
                    "categories": {"coding": 3},
                    "duplicate_original_names": {
                        "review": ["coding/review/SKILL.md", "coding/review-alt/SKILL.md"]
                    },
                    "module_paths": ["coding/AgentMakefile"],
                },
                "artifact_refs": {"root_agentmakefile": "modules/openclaw/AgentMakefile"},
            }
        )
        + "\n"
    )
    out_dir = tmp_path / ".agentmf" / "evolution" / "candidates"

    curate_exit = main(
        [
            "evo",
            "openclaw",
            "curate",
            "--evidence-file",
            str(evidence_file),
            "--out-dir",
            str(out_dir),
            "--write",
            "--format",
            "json",
        ]
    )
    curate_payload = json.loads(capsys.readouterr().out)
    dream_exit = main(
        [
            "evo",
            "dream",
            "run",
            "--evidence-dir",
            str(tmp_path / ".agentmf" / "evolution" / "evidence"),
            "--out-dir",
            str(out_dir),
            "--write",
            "--format",
            "json",
        ]
    )
    dream_payload = json.loads(capsys.readouterr().out)

    assert curate_exit == 0
    assert curate_payload["ok"] is True
    assert curate_payload["openclaw_curator"]["proposal_count"] == 1
    assert dream_exit == 0
    assert dream_payload["ok"] is True
    assert dream_payload["dream_mode"]["proposal_count"] == 1


def _write_skill(skills_dir: Path, name: str, description: str, body: str) -> Path:
    skill_dir = skills_dir / name
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n\n{body}\n"
    )
    return path


def _write_openclaw_skill(
    skills_dir: Path,
    relative_dir: str,
    name: str,
    description: str,
    category: str,
    tags: list[str],
    body: str,
) -> Path:
    skill_dir = skills_dir / relative_dir
    skill_dir.mkdir(parents=True)
    path = skill_dir / "SKILL.md"
    path.write_text(
        "---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"category: {category}\n"
        f"tags: {tags}\n"
        "---\n\n"
        f"# {name}\n\n"
        f"{body}\n"
    )
    return path


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


def test_runtime_walkthrough_demo_exercises_runtime_features(tmp_path: Path) -> None:
    invalid_output = json.loads(RUNTIME_WALKTHROUGH_INVALID_OUTPUT.read_text())
    valid_output = json.loads(RUNTIME_WALKTHROUGH_VALID_OUTPUT.read_text())

    invalid_plan = create_run_plan(
        RUNTIME_WALKTHROUGH_DEMO,
        request="show agentmakefile runtime",
        dry_run=True,
        proposed_tool_calls=[
            {"tool": "bash", "input": "git status"},
            {"tool": "bash", "input": "npm install"},
            {"tool": "bash", "input": "printf safe"},
        ],
        proposed_output=invalid_output,
    )

    assert invalid_plan.ok, invalid_plan.diagnostics.format()
    assert invalid_plan.plan["link_plan"]["selected_targets"] == ["demo.runtime_walkthrough"]
    assert invalid_plan.plan["link_plan"]["target_closure"] == ["demo.runtime_walkthrough"]
    assert invalid_plan.plan["target_contracts"][0]["skills"] == ["superpowers:using-superpowers"]
    assert invalid_plan.plan["permission_evaluation"]["tool_calls"] == [
        {
            "tool": "bash",
            "input": "git status",
            "action": "allow",
            "source": "rule",
            "matched_rules": [{"tool": "bash", "pattern": "git status", "action": "allow"}],
        },
        {
            "tool": "bash",
            "input": "npm install",
            "action": "deny",
            "source": "rule",
            "matched_rules": [{"tool": "bash", "pattern": "npm install*", "action": "deny"}],
        },
        {
            "tool": "bash",
            "input": "printf safe",
            "action": "allow",
            "source": "rule",
            "matched_rules": [{"tool": "bash", "pattern": "printf *", "action": "allow"}],
        },
    ]
    assert invalid_plan.plan["output_validation"]["status"] == "invalid"
    demo_validation = next(
        target
        for target in invalid_plan.plan["output_validation"]["targets"]
        if target["target"] == "demo.runtime_walkthrough"
    )
    assert demo_validation["missing_fields"] == [
        "risky_scripts",
        "dependency_risks",
        "tool_interception",
        "validation_status",
    ]
    schema_errors = demo_validation["schema_errors"]
    assert [error["validator"] for error in schema_errors] == [
        "additionalProperties",
        "minLength",
        "enum",
        "minItems",
        "minLength",
    ]

    valid_plan = create_run_plan(
        RUNTIME_WALKTHROUGH_DEMO,
        target_names=["demo.runtime_walkthrough"],
        dry_run=True,
        proposed_output=valid_output,
    )

    assert valid_plan.ok, valid_plan.diagnostics.format()
    assert valid_plan.plan["output_validation"]["status"] == "valid"

    from agentmf.tool_loop import create_exec_payload

    exec_result = create_exec_payload(
        path=RUNTIME_WALKTHROUGH_DEMO,
        target_names=["demo.runtime_walkthrough"],
        provider="echo",
        tool_calls=[
            {"id": "sandbox_block", "tool": "bash", "input": "touch should-not-exist.txt"},
        ],
        apply=True,
        cwd=tmp_path,
        sandbox_profile="read-only",
        execute_fallbacks=True,
    )

    assert exec_result.ok, exec_result.diagnostics.format()
    assert not (tmp_path / "should-not-exist.txt").exists()
    assert exec_result.payload["tool_results"][0]["reason"] == "sandbox_read_only"
    assert exec_result.payload["tool_interception"]["provider"] == "echo"
    assert exec_result.payload["tool_interception"]["tool_calls"][0] == {
        "id": "sandbox_block",
        "tool": "bash",
        "input": "touch should-not-exist.txt",
        "permission_action": "allow",
        "sandbox_profile": "read-only",
        "interception_decision": "block",
        "block_reason": "sandbox_read_only",
        "result_status": "blocked",
    }
    assert exec_result.payload["fallback_handling"]["status"] == "executed"


def test_runtime_walkthrough_demo_default_compile_emits_skill_outputs() -> None:
    result = compile_agentmakefile(RUNTIME_WALKTHROUGH_DEMO)

    assert result.ok, result.diagnostics.format()
    paths = [file.path for file in result.files]
    assert "skills/index.md" in paths
    assert ".claude/skills/superpowers-using-superpowers/SKILL.md" in paths
    assert ".codex/skills/superpowers-using-superpowers/SKILL.md" in paths
    assert ".claude/skills/superpowers-test-driven-development/SKILL.md" in paths
    assert ".codex/skills/superpowers-test-driven-development/SKILL.md" in paths


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


def test_compile_skills_index_emits_catalog_for_all_skills(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
metadata:
  name: skill-catalog-fixture
  description: Skill catalog fixture.
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
permissions:
  rules:
    bash:
      "npm install*": deny
""",
    )

    result = compile_agentmakefile(path, targets=["skills-index"])

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == ["skills/index.md"]
    assert result.files[0].backend == "skills-index"
    assert result.files[0].managed_block is True
    content = result.files[0].content
    assert "# skill-catalog-fixture - Skill Index" in content
    assert "Generated from AgentMakefile. Treat this file as a compatibility catalog" in content
    assert "Skill catalog fixture." in content
    assert "### local-review" in content
    assert "### superpowers:systematic-debugging" in content
    assert "- Slug: `local-review`" in content
    assert "- Claude skill: `.claude/skills/local-review/SKILL.md`" in content
    assert "- Codex skill: `.codex/skills/superpowers-systematic-debugging/SKILL.md`" in content
    assert "#### Match" in content
    assert "- `user_intent`: debug" in content
    assert "#### Steps" in content
    assert "- reproduce_failure" in content
    assert "#### Output format" in content
    assert "- root_cause" in content
    assert "## Permission Guidance" in content
    assert "| bash | npm install* | deny |" in content


def test_compile_skills_index_honors_artifact_path(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
compile:
  targets:
    - skills-index
artifacts:
  skills-index:
    path: docs/generated-skills.md
skills:
  local-review:
    description: Review local changes.
""",
    )

    result = compile_agentmakefile(path)

    assert result.ok, result.diagnostics.format()
    assert [file.path for file in result.files] == ["docs/generated-skills.md"]
    assert "### local-review" in result.files[0].content


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


def test_compile_agents_fragments_renders_harness_pipeline_closure(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  base.task:
    steps:
      - use_skill: superpowers:using-superpowers
  review.task:
    deps:
      - base.task
    steps:
      - select_context:
          include:
            - git.diff
      - link_prompt:
          fragment: review.instructions
      - check_guard: tests_required
      - check_permission:
          tool: bash
          input: "pytest*"
      - validate_output: findings
      - fallback: ask_for_clarification
      - action: review_code
""",
    )

    result = compile_agentmakefile(path, targets=["agents-fragments"])

    assert result.ok, result.diagnostics.format()
    review_fragment = next(file for file in result.files if file.path.endswith("review.task.md"))
    assert "## Harness Pipeline" in review_fragment.content
    assert "### Pipeline: base.task" in review_fragment.content
    assert "### Pipeline: review.task" in review_fragment.content
    assert "#### Prompt Operations" in review_fragment.content
    assert "`use_skill`" in review_fragment.content
    assert "`link_prompt`" in review_fragment.content
    assert "review.instructions" in review_fragment.content
    assert "#### Context Operations" in review_fragment.content
    assert "`select_context`" in review_fragment.content
    assert "git.diff" in review_fragment.content
    assert "#### Guard Operations" in review_fragment.content
    assert "`check_guard`" in review_fragment.content
    assert "tests_required" in review_fragment.content
    assert "#### Permission Operations" in review_fragment.content
    assert "`check_permission`" in review_fragment.content
    assert "pytest*" in review_fragment.content
    assert "#### Fallback Operations" in review_fragment.content
    assert "ask_for_clarification" in review_fragment.content
    assert "#### Output Contract" in review_fragment.content
    assert "findings" in review_fragment.content


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
    assert result.plan["selection"] == {
        "mode": "explicit_target",
        "request": None,
        "targets": ["review.task"],
    }
    assert result.plan["selection_trace"]["selected"]["dependency_closure"] == [
        "base.task",
        "review.task",
    ]
    assert result.plan["selected_targets"] == ["review.task"]
    assert result.plan["target_closure"] == ["base.task", "review.task"]
    assert [pipeline["target"] for pipeline in result.plan["target_pipelines"]] == [
        "base.task",
        "review.task",
    ]
    assert result.plan["pipeline_trace"]["operation_counts"]["action_ops"] == 2
    assert result.plan["fragments"] == [
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


def test_link_plan_exposes_pipeline_trace_for_selected_closure(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  base.task:
    steps:
      - use_skill: superpowers:using-superpowers
  review.task:
    deps:
      - base.task
    steps:
      - select_context:
          include:
            - git.diff
      - action: review_code
""",
    )

    result = create_link_plan(path, target_names=["review.task"], backend="agents-fragments")

    assert result.ok, result.diagnostics.format()
    assert [pipeline["target"] for pipeline in result.plan["target_pipelines"]] == [
        "base.task",
        "review.task",
    ]
    assert result.plan["pipeline_trace"] == {
        "selected_target": "review.task",
        "target_closure": ["base.task", "review.task"],
        "operation_counts": {
            "operations": 3,
            "context_ops": 1,
            "prompt_ops": 1,
            "action_ops": 1,
            "guard_ops": 0,
            "permission_ops": 0,
            "fallback_ops": 0,
        },
        "targets": [
            {
                "target": "base.task",
                "operation_counts": {
                    "operations": 1,
                    "context_ops": 0,
                    "prompt_ops": 1,
                    "action_ops": 0,
                    "guard_ops": 0,
                    "permission_ops": 0,
                    "fallback_ops": 0,
                },
            },
            {
                "target": "review.task",
                "operation_counts": {
                    "operations": 2,
                    "context_ops": 1,
                    "prompt_ops": 0,
                    "action_ops": 1,
                    "guard_ops": 0,
                    "permission_ops": 0,
                    "fallback_ops": 0,
                },
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


def test_normalize_builds_target_pipeline_from_typed_steps(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
policies:
  verify_policy:
    guards:
      - policy_guard
    steps:
      - action: policy_step
skills:
  tdd:
    namespace: superpowers
    description: Test-driven development.
targets:
  code.change:
    policies:
      - verify_policy
    skills:
      - superpowers:tdd
    guards:
      - tests_required
    steps:
      - select_context:
          include:
            - git.diff
            - active_file
      - link_prompt:
          fragment: tdd.instructions
      - action: legacy_step
    output_format:
      - implementation_summary
    fallback:
      blocked:
        - fallback: ask_for_clarification
""",
    )

    source = load_source(path)
    diagnostics = Diagnostics()
    ir = normalize(source, diagnostics)

    assert ir is not None
    assert not diagnostics.has_errors, diagnostics.format()
    target = next(target for target in ir.targets if target.name == "code.change")
    pipeline = dict(target.pipeline)
    assert [operation["type"] for operation in pipeline.pop("operations")] == [
        "action",
        "select_context",
        "link_prompt",
        "action",
        "check_guard",
        "check_guard",
        "fallback",
    ]
    assert pipeline == {
        "target": "code.change",
        "deps": [],
        "skills": ["superpowers:tdd"],
        "policies": ["verify_policy"],
        "context_ops": [
            {
                "type": "select_context",
                "source": "target",
                "payload": {"include": ["git.diff", "active_file"]},
                "raw": {"select_context": {"include": ["git.diff", "active_file"]}},
            }
        ],
        "prompt_ops": [
            {
                "type": "link_prompt",
                "source": "target",
                "payload": {"fragment": "tdd.instructions"},
                "raw": {"link_prompt": {"fragment": "tdd.instructions"}},
            }
        ],
        "action_ops": [
            {
                "type": "action",
                "source": "policy",
                "policy": "verify_policy",
                "payload": {"name": "policy_step"},
                "raw": {"action": "policy_step"},
            },
            {
                "type": "action",
                "source": "target",
                "payload": {"name": "legacy_step"},
                "raw": {"action": "legacy_step"},
            }
        ],
        "guard_ops": [
            {
                "type": "check_guard",
                "source": "policy",
                "policy": "verify_policy",
                "payload": {"guard": "policy_guard"},
                "raw": "policy_guard",
            },
            {
                "type": "check_guard",
                "source": "target",
                "payload": {"guard": "tests_required"},
                "raw": "tests_required",
            },
        ],
        "permission_ops": [],
        "fallback_ops": [
            {
                "type": "fallback",
                "source": "target",
                "condition": "blocked",
                "payload": {"name": "ask_for_clarification"},
                "raw": {"fallback": "ask_for_clarification"},
            }
        ],
        "output_contracts": {
            "format": ["implementation_summary"],
            "schema": {},
        },
    }


def test_normalize_builds_target_pipeline_from_full_operation_schema(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.change:
    steps:
      - use_skill: superpowers:test-driven-development
      - select_context:
          include:
            - git.diff
            - active_file
      - link_prompt:
          fragment: tdd.instructions
      - apply_policy:
          source: imported
      - check_guard: tests_required
      - check_permission:
          tool: bash
          input: "pytest*"
      - validate_output: implementation_summary
      - fallback: ask_for_clarification
      - action: legacy_step
""",
    )

    source = load_source(path)
    diagnostics = Diagnostics()
    ir = normalize(source, diagnostics)

    assert ir is not None
    assert not diagnostics.has_errors, diagnostics.format()
    target = next(target for target in ir.targets if target.name == "code.change")
    assert [operation["type"] for operation in target.pipeline["operations"]] == [
        "use_skill",
        "select_context",
        "link_prompt",
        "apply_policy",
        "check_guard",
        "check_permission",
        "validate_output",
        "fallback",
        "action",
    ]
    assert target.pipeline["prompt_ops"] == [
        {
            "type": "use_skill",
            "source": "target",
            "payload": {"skill": "superpowers:test-driven-development"},
            "raw": {"use_skill": "superpowers:test-driven-development"},
        },
        {
            "type": "link_prompt",
            "source": "target",
            "payload": {"fragment": "tdd.instructions"},
            "raw": {"link_prompt": {"fragment": "tdd.instructions"}},
        },
        {
            "type": "apply_policy",
            "source": "target",
            "payload": {"source": "imported"},
            "raw": {"apply_policy": {"source": "imported"}},
        },
    ]
    assert target.pipeline["context_ops"][0]["payload"] == {"include": ["git.diff", "active_file"]}
    assert target.pipeline["guard_ops"] == [
        {
            "type": "check_guard",
            "source": "target",
            "payload": {"guard": "tests_required"},
            "raw": {"check_guard": "tests_required"},
        }
    ]
    assert target.pipeline["permission_ops"] == [
        {
            "type": "check_permission",
            "source": "target",
            "payload": {"tool": "bash", "input": "pytest*"},
            "raw": {"check_permission": {"tool": "bash", "input": "pytest*"}},
        }
    ]
    assert target.pipeline["fallback_ops"] == [
        {
            "type": "fallback",
            "source": "target",
            "condition": "runtime",
            "payload": {"name": "ask_for_clarification"},
            "raw": {"fallback": "ask_for_clarification"},
        }
    ]
    assert target.pipeline["output_contracts"]["format"] == ["implementation_summary"]


def test_runtime_dry_run_exposes_target_pipelines(tmp_path: Path) -> None:
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
      - select_context:
          include:
            - git.diff
      - action: review_code
""",
    )

    result = create_run_plan(path, request="please review code", backend="agents-fragments", dry_run=True)

    assert result.ok, result.diagnostics.format()
    pipelines = [dict(pipeline) for pipeline in result.plan["target_pipelines"]]
    assert [operation["type"] for operation in pipelines[0].pop("operations")] == [
        "select_context",
        "action",
    ]
    assert pipelines == [
        {
            "target": "review.task",
            "deps": [],
            "skills": [],
            "policies": [],
            "context_ops": [
                {
                    "type": "select_context",
                    "source": "target",
                    "payload": {"include": ["git.diff"]},
                    "raw": {"select_context": {"include": ["git.diff"]}},
                }
            ],
            "prompt_ops": [],
            "action_ops": [
                {
                    "type": "action",
                    "source": "target",
                    "payload": {"name": "review_code"},
                    "raw": {"action": "review_code"},
                }
            ],
            "guard_ops": [],
            "permission_ops": [],
            "fallback_ops": [],
            "output_contracts": {"format": [], "schema": {}},
        }
    ]


def test_runtime_dry_run_exposes_pipeline_execution_plan(tmp_path: Path) -> None:
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
      - select_context:
          include:
            - git.diff
      - link_prompt:
          fragment: review.instructions
      - check_guard: tests_required
      - check_permission:
          tool: bash
          input: "pytest*"
      - validate_output: findings
      - fallback: ask_for_clarification
      - action: review_code
""",
    )

    result = create_run_plan(
        path,
        request="please review code",
        backend="agents-fragments",
        dry_run=True,
        proposed_tool_calls=[{"tool": "bash", "input": "pytest tests/test_agentmf.py"}],
        proposed_output={"findings": []},
    )

    assert result.ok, result.diagnostics.format()
    execution_plan = result.plan["pipeline_execution_plan"]
    assert execution_plan["selected_target"] == "review.task"
    assert execution_plan["resolved_deps"] == ["review.task"]
    assert [operation["type"] for operation in execution_plan["pipeline_operations"]] == [
        "select_context",
        "link_prompt",
        "check_guard",
        "check_permission",
        "validate_output",
        "fallback",
        "action",
    ]
    assert execution_plan["stable_prefix_objects"][0]["path"] == ".agentmf/fragments/agents/review.task.md"
    assert execution_plan["volatile_context_inputs"][0]["payload"] == {"include": ["git.diff"]}
    assert execution_plan["guards_evaluated"][0]["payload"] == {"guard": "tests_required"}
    assert execution_plan["permissions_checked"][0]["payload"] == {"tool": "bash", "input": "pytest*"}
    assert execution_plan["output_schema_validation"]["status"] == "valid"
    assert execution_plan["fallback_plan"][0]["payload"] == {"name": "ask_for_clarification"}


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


def test_runtime_output_validation_dry_run_reports_missing_fields(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    output_format:
      - findings
      - verification_result
    output_schema:
      required:
        - changed_files
        - risk_summary
    steps:
      - action: review_code
""",
    )

    result = create_run_plan(
        path,
        target_names=["review.task"],
        dry_run=True,
        proposed_output={
            "findings": [],
            "changed_files": ["src/example.py"],
        },
    )

    assert result.ok, result.diagnostics.format()
    assert result.plan["runtime_phases"][6] == {
        "name": "output_validation",
        "status": "evaluated_dry_run",
    }
    assert result.plan["output_validation"] == {
        "mode": "dry_run",
        "executed": False,
        "provided": True,
        "status": "invalid",
        "targets": [
            {
                "target": "review.task",
                "required_fields": [
                    "findings",
                    "verification_result",
                    "changed_files",
                    "risk_summary",
                ],
                "present_fields": ["changed_files", "findings"],
                "missing_fields": ["verification_result", "risk_summary"],
                "type_errors": [],
                "status": "invalid",
            }
        ],
    }


def test_runtime_output_validation_dry_run_accepts_complete_output(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
policies:
  verify_policy:
    output_format:
      - risk_summary
targets:
  review.task:
    policies:
      - verify_policy
    output_format:
      - findings
    output_schema:
      required:
        - changed_files
    steps:
      - action: review_code
""",
    )

    result = create_run_plan(
        path,
        target_names=["review.task"],
        dry_run=True,
        proposed_output={
            "findings": [],
            "risk_summary": "low",
            "changed_files": ["src/example.py"],
        },
    )

    assert result.ok, result.diagnostics.format()
    assert result.plan["output_validation"]["status"] == "valid"
    assert result.plan["output_validation"]["targets"] == [
        {
            "target": "review.task",
            "required_fields": ["risk_summary", "findings", "changed_files"],
            "present_fields": ["changed_files", "findings", "risk_summary"],
            "missing_fields": [],
            "type_errors": [],
            "status": "valid",
        }
    ]


def test_runtime_output_validation_dry_run_reports_schema_type_errors(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    output_schema:
      type: object
      required:
        - summary
        - changed_files
        - risk_score
        - approved
      properties:
        summary:
          type: string
        changed_files:
          type: array
        risk_score:
          type: number
        approved:
          type: boolean
    steps:
      - action: review_code
""",
    )

    result = create_run_plan(
        path,
        target_names=["review.task"],
        dry_run=True,
        proposed_output={
            "summary": 42,
            "changed_files": "src/example.py",
            "risk_score": "high",
            "approved": "yes",
        },
    )

    assert result.ok, result.diagnostics.format()
    assert result.plan["output_validation"]["status"] == "invalid"
    assert result.plan["output_validation"]["targets"] == [
        {
            "target": "review.task",
            "required_fields": ["summary", "changed_files", "risk_score", "approved"],
            "present_fields": ["approved", "changed_files", "risk_score", "summary"],
            "missing_fields": [],
            "type_errors": [
                {"field": "approved", "expected": "boolean", "actual": "string"},
                {"field": "changed_files", "expected": "array", "actual": "string"},
                {"field": "risk_score", "expected": "number", "actual": "string"},
                {"field": "summary", "expected": "string", "actual": "integer"},
            ],
            "status": "invalid",
        }
    ]


def test_runtime_output_validation_dry_run_accepts_schema_types(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    output_schema:
      type: object
      required:
        - summary
        - changed_files
        - risk_score
        - approved
      properties:
        summary:
          type: string
        changed_files:
          type: array
        risk_score:
          type: number
        approved:
          type: boolean
    steps:
      - action: review_code
""",
    )

    result = create_run_plan(
        path,
        target_names=["review.task"],
        dry_run=True,
        proposed_output={
            "summary": "ok",
            "changed_files": ["src/example.py"],
            "risk_score": 0.5,
            "approved": True,
        },
    )

    assert result.ok, result.diagnostics.format()
    assert result.plan["output_validation"]["status"] == "valid"
    assert result.plan["output_validation"]["targets"] == [
        {
            "target": "review.task",
            "required_fields": ["summary", "changed_files", "risk_score", "approved"],
            "present_fields": ["approved", "changed_files", "risk_score", "summary"],
            "missing_fields": [],
            "type_errors": [],
            "status": "valid",
        }
    ]


def test_runtime_output_validation_dry_run_reports_json_schema_errors(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    output_schema:
      type: object
      required:
        - findings
      properties:
        findings:
          type: array
          minItems: 2
          items:
            type: object
            required:
              - severity
            properties:
              severity:
                type: string
                enum:
                  - low
                  - medium
                  - high
            additionalProperties: false
      additionalProperties: false
    steps:
      - action: review_code
""",
    )

    result = create_run_plan(
        path,
        target_names=["review.task"],
        dry_run=True,
        proposed_output={
            "findings": [
                {
                    "severity": "critical",
                    "extra": True,
                }
            ],
            "unexpected": "field",
        },
    )

    assert result.ok, result.diagnostics.format()
    target = result.plan["output_validation"]["targets"][0]
    assert result.plan["output_validation"]["status"] == "invalid"
    assert target["status"] == "invalid"
    assert target["missing_fields"] == []
    assert [
        (error["source"], error["path"], error["validator"])
        for error in target["schema_errors"]
    ] == [
        ("target", [], "additionalProperties"),
        ("target", ["findings"], "minItems"),
        ("target", ["findings", 0], "additionalProperties"),
        ("target", ["findings", 0, "severity"], "enum"),
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
    assert isinstance(comparison["all_in_one"]["chars"], int)
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


def test_cli_run_dry_run_accepts_output_json_validation(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    output_format:
      - findings
      - verification_result
    steps:
      - action: review_code
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
            "--output-json",
            '{"findings": []}',
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["runtime_plan"]["output_validation"]["status"] == "invalid"
    assert payload["runtime_plan"]["output_validation"]["targets"][0]["missing_fields"] == [
        "verification_result"
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
        "sandbox_profile": "workspace-write",
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


def test_exec_payload_plans_fallback_for_blocked_tool_calls(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    fallback:
      blocked:
        - summarize_blocker
        - ask_for_permission
    steps:
      - action: review_code
permissions:
  rules:
    bash:
      "npm install*": deny
""",
    )

    from agentmf.tool_loop import create_exec_payload

    result = create_exec_payload(
        path=path,
        target_names=["review.task"],
        tool_calls=[
            {"tool": "bash", "input": "npm install"},
        ],
        apply=True,
        cwd=tmp_path,
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["tool_results"] == [
        {
            "tool": "bash",
            "input": "npm install",
            "status": "blocked",
            "reason": "permission_deny",
            "permission_action": "deny",
        }
    ]
    assert result.payload["fallback_handling"] == {
        "mode": "dry_run",
        "executed": False,
        "status": "planned",
        "blocked_tool_calls": [
            {
                "tool": "bash",
                "input": "npm install",
                "reason": "permission_deny",
                "permission_action": "deny",
                "fallbacks": [
                    {
                        "target": "review.task",
                        "trigger": "blocked",
                        "actions": ["summarize_blocker", "ask_for_permission"],
                        "status": "planned",
                    }
                ],
            }
        ],
    }


def test_exec_payload_reports_no_fallback_for_blocked_tool_calls_without_contract(tmp_path: Path) -> None:
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
""",
    )

    from agentmf.tool_loop import create_exec_payload

    result = create_exec_payload(
        path=path,
        target_names=["review.task"],
        tool_calls=[
            {"tool": "bash", "input": "python3 -V"},
        ],
        apply=True,
        cwd=tmp_path,
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["fallback_handling"] == {
        "mode": "dry_run",
        "executed": False,
        "status": "not_planned",
        "blocked_tool_calls": [
            {
                "tool": "bash",
                "input": "python3 -V",
                "reason": "permission_ask",
                "permission_action": "ask",
                "fallbacks": [],
            }
        ],
    }


def test_exec_payload_includes_sandbox_profile_metadata(tmp_path: Path) -> None:
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
        tool_calls=[
            {"tool": "bash", "input": "printf sandbox"},
        ],
        apply=True,
        cwd=tmp_path,
        sandbox_profile="read-only",
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["sandbox"] == {
        "profile": "read-only",
        "mode": "prototype_preflight",
        "enforced": True,
        "filesystem": "read_only_preflight",
        "network": "not_configured",
        "supported_profiles": ["none", "read-only", "workspace-write"],
    }
    assert result.payload["execution"]["sandbox_profile"] == "read-only"


def test_exec_payload_rejects_unknown_sandbox_profile(tmp_path: Path) -> None:
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

    from agentmf.tool_loop import create_exec_payload

    result = create_exec_payload(
        path=path,
        target_names=["review.task"],
        tool_calls=[],
        apply=True,
        sandbox_profile="root",
    )

    assert not result.ok
    assert result.payload == {}
    assert [
        (item.code, item.message, item.location, item.hint)
        for item in result.diagnostics.items
    ] == [
        (
            "AMF143",
            "unsupported sandbox profile: root",
            "exec.sandbox_profile",
            "use one of: none, read-only, workspace-write",
        )
    ]


def test_exec_payload_read_only_sandbox_blocks_write_like_bash(tmp_path: Path) -> None:
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
      "touch *": allow
""",
    )

    from agentmf.tool_loop import create_exec_payload

    result = create_exec_payload(
        path=path,
        target_names=["review.task"],
        tool_calls=[
            {"tool": "bash", "input": "touch created.txt"},
        ],
        apply=True,
        cwd=tmp_path,
        sandbox_profile="read-only",
    )

    assert result.ok, result.diagnostics.format()
    assert not (tmp_path / "created.txt").exists()
    assert result.payload["sandbox"]["enforced"] is True
    assert result.payload["tool_results"] == [
        {
            "tool": "bash",
            "input": "touch created.txt",
            "status": "blocked",
            "reason": "sandbox_read_only",
            "permission_action": "allow",
            "sandbox_profile": "read-only",
        }
    ]


def test_exec_payload_workspace_write_sandbox_allows_write_like_bash(tmp_path: Path) -> None:
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
      "touch *": allow
""",
    )

    from agentmf.tool_loop import create_exec_payload

    result = create_exec_payload(
        path=path,
        target_names=["review.task"],
        tool_calls=[
            {"tool": "bash", "input": "touch created.txt"},
        ],
        apply=True,
        cwd=tmp_path,
        sandbox_profile="workspace-write",
    )

    assert result.ok, result.diagnostics.format()
    assert (tmp_path / "created.txt").exists()
    assert result.payload["sandbox"]["enforced"] is True
    assert result.payload["tool_results"][0]["status"] == "executed"


def test_exec_payload_emits_provider_tool_interception_contract(tmp_path: Path) -> None:
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
      "touch *": allow
""",
    )

    from agentmf.tool_loop import create_exec_payload

    result = create_exec_payload(
        path=path,
        target_names=["review.task"],
        provider="echo",
        tool_calls=[
            {"id": "call_allowed", "tool": "bash", "input": "printf provider-ok"},
            {"id": "call_blocked", "tool": "bash", "input": "touch created.txt"},
        ],
        apply=True,
        cwd=tmp_path,
        sandbox_profile="read-only",
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["tool_interception"] == {
        "version": 1,
        "mode": "provider_tool_call_interception",
        "provider": "echo",
        "status": "evaluated",
        "events": [
            "provider_tool_call_requested",
            "agentmf_permission_evaluated",
            "agentmf_sandbox_evaluated",
            "host_tool_result_returned",
        ],
        "host_boundary": {
            "provider_requests_tool_call": True,
            "agentmf_evaluates_permissions": True,
            "agentmf_evaluates_sandbox": True,
            "host_executes_allowed_call": True,
            "host_returns_tool_result_to_provider": True,
        },
        "tool_calls": [
            {
                "id": "call_allowed",
                "tool": "bash",
                "input": "printf provider-ok",
                "permission_action": "allow",
                "sandbox_profile": "read-only",
                "interception_decision": "allow",
                "result_status": "executed",
            },
            {
                "id": "call_blocked",
                "tool": "bash",
                "input": "touch created.txt",
                "permission_action": "allow",
                "sandbox_profile": "read-only",
                "interception_decision": "block",
                "block_reason": "sandbox_read_only",
                "result_status": "blocked",
            },
        ],
    }


def test_exec_payload_execute_fallbacks_runs_internal_fallback_actions(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    fallback:
      blocked:
        - summarize_blocker
        - ask_for_permission
    steps:
      - action: review_code
permissions:
  rules:
    bash:
      "npm install*": deny
""",
    )

    from agentmf.tool_loop import create_exec_payload

    result = create_exec_payload(
        path=path,
        target_names=["review.task"],
        tool_calls=[
            {"tool": "bash", "input": "npm install"},
        ],
        apply=True,
        cwd=tmp_path,
        execute_fallbacks=True,
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["fallback_handling"] == {
        "mode": "prototype",
        "executed": True,
        "status": "executed",
        "blocked_tool_calls": [
            {
                "tool": "bash",
                "input": "npm install",
                "reason": "permission_deny",
                "permission_action": "deny",
                "fallbacks": [
                    {
                        "target": "review.task",
                        "trigger": "blocked",
                        "actions": ["summarize_blocker", "ask_for_permission"],
                        "status": "executed",
                        "results": [
                            {
                                "action": "summarize_blocker",
                                "status": "executed",
                                "execution": "internal_noop",
                            },
                            {
                                "action": "ask_for_permission",
                                "status": "executed",
                                "execution": "internal_noop",
                            },
                        ],
                    }
                ],
            }
        ],
    }


def test_cli_exec_execute_fallbacks_outputs_executed_fallbacks(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  review.task:
    fallback:
      blocked:
        - summarize_blocker
    steps:
      - action: review_code
permissions:
  rules:
    bash:
      "npm install*": deny
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
            "bash:npm install",
            "--execute-fallbacks",
            "--apply",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["exec_payload"]["fallback_handling"]["status"] == "executed"
    assert payload["exec_payload"]["fallback_handling"]["blocked_tool_calls"][0]["fallbacks"][0]["results"] == [
        {
            "action": "summarize_blocker",
            "status": "executed",
            "execution": "internal_noop",
        }
    ]


def test_cli_exec_provider_flag_outputs_tool_interception_contract(tmp_path: Path, capsys) -> None:
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
            "--provider",
            "echo",
            "--tool-call",
            "bash:printf cli-provider",
            "--apply",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["exec_payload"]["tool_interception"]["provider"] == "echo"
    assert payload["exec_payload"]["tool_interception"]["tool_calls"] == [
        {
            "id": "tool_call_0",
            "tool": "bash",
            "input": "printf cli-provider",
            "permission_action": "allow",
            "sandbox_profile": "workspace-write",
            "interception_decision": "allow",
            "result_status": "executed",
        }
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
            "--sandbox-profile",
            "workspace-write",
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
    assert payload["exec_payload"]["sandbox"]["profile"] == "workspace-write"


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


def test_prompt_payload_surfaces_routing_summary_with_closure_provenance_and_alternatives(tmp_path: Path) -> None:
    """The prompt payload must expose a routing_summary that the LLM can
    use to understand which target was selected, what got auto-loaded
    via Makefile-style deps, and which alternatives the selector
    considered. The final composed prompt content must render a
    '## Routing Decision' section so the LLM literally sees this signal.
    """
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  skill.foundation:
    match:
      user_intent:
        - assemble foundation widget
    deps:
      - skill.utility
    fallback:
      runtime:
        - skill.alt
    steps:
      - action: build_foundation
  skill.utility:
    steps:
      - action: utility_step
  skill.alt:
    steps:
      - action: alt_step
""",
    )

    from agentmf.prompt import create_prompt_payload

    result = create_prompt_payload(path=path, request="assemble foundation widget")

    assert result.ok, result.diagnostics.format()
    summary = result.payload["routing_summary"]
    assert summary["primary"]["target"] == "skill.foundation"
    closure_by_target = {entry["target"]: entry for entry in summary["closure"]}
    # The primary itself is also in closure, but with no "depended_on_by".
    assert closure_by_target["skill.foundation"]["depended_on_by"] is None
    # skill.utility was pulled in because skill.foundation depends on it.
    assert closure_by_target["skill.utility"]["depended_on_by"] == "skill.foundation"
    # Alternatives include the declared fallback.
    alt_targets = [a["target"] for a in summary["alternatives"]]
    assert "skill.alt" in alt_targets

    content = result.payload["final_prompt"]["content"]
    assert "## Routing Decision" in content
    # closure target and alternative target both visible in rendered prompt
    assert "skill.utility" in content
    assert "skill.alt" in content


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


def test_plugin_payload_exposes_selected_skills_and_artifact_paths(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  receiving-code-review:
    namespace: superpowers
    description: Review feedback rigorously.
  verification-before-completion:
    namespace: superpowers
    description: Verify before claiming completion.
targets:
  base.verify:
    skills:
      - superpowers:verification-before-completion
  review.task:
    deps:
      - base.verify
    match:
      user_intent:
        - review code
    skills:
      - superpowers:receiving-code-review
      - superpowers:verification-before-completion
    steps:
      - action: review_code
""",
    )

    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=path,
        host="codex",
        request="please review code",
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["selected_targets"] == ["review.task"]
    assert result.payload["selected_skills"] == [
        "superpowers:verification-before-completion",
        "superpowers:receiving-code-review",
    ]
    assert result.payload["skill_artifacts"] == {
        "skills_index": "skills/index.md",
        "codex": [
            ".codex/skills/superpowers-verification-before-completion/SKILL.md",
            ".codex/skills/superpowers-receiving-code-review/SKILL.md",
        ],
        "claude": [
            ".claude/skills/superpowers-verification-before-completion/SKILL.md",
            ".claude/skills/superpowers-receiving-code-review/SKILL.md",
        ],
    }


def test_plugin_payload_exposes_selected_pipeline(tmp_path: Path) -> None:
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
      - select_context:
          include:
            - git.diff
      - link_prompt:
          fragment: review.instructions
      - action: review_code
""",
    )

    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=path,
        host="codex",
        request="please review code",
    )

    assert result.ok, result.diagnostics.format()
    selected_pipeline = result.payload["selected_pipeline"]
    assert selected_pipeline["target"] == "review.task"
    assert selected_pipeline["target_closure"] == ["review.task"]
    assert [operation["type"] for operation in selected_pipeline["operations"]] == [
        "select_context",
        "link_prompt",
        "action",
    ]
    target_pipeline = dict(selected_pipeline["targets"][0])
    assert [operation["type"] for operation in target_pipeline.pop("operations")] == [
        "select_context",
        "link_prompt",
        "action",
    ]
    assert target_pipeline == {
        "target": "review.task",
        "deps": [],
        "skills": [],
        "policies": [],
        "context_ops": [
            {
                "type": "select_context",
                "source": "target",
                "payload": {"include": ["git.diff"]},
                "raw": {"select_context": {"include": ["git.diff"]}},
            }
        ],
        "prompt_ops": [
            {
                "type": "link_prompt",
                "source": "target",
                "payload": {"fragment": "review.instructions"},
                "raw": {"link_prompt": {"fragment": "review.instructions"}},
            }
        ],
        "action_ops": [
            {
                "type": "action",
                "source": "target",
                "payload": {"name": "review_code"},
                "raw": {"action": "review_code"},
            }
        ],
        "guard_ops": [],
        "permission_ops": [],
        "fallback_ops": [],
        "output_contracts": {"format": [], "schema": {}},
    }


def test_plugin_payload_exposes_flat_pipeline_operation_groups(tmp_path: Path) -> None:
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
      - select_context:
          include:
            - git.diff
      - link_prompt:
          fragment: review.instructions
      - check_guard: tests_required
      - check_permission:
          tool: bash
          input: "pytest*"
      - validate_output: findings
      - fallback: ask_for_clarification
      - action: review_code
""",
    )

    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=path,
        host="codex",
        request="please review code",
    )

    assert result.ok, result.diagnostics.format()
    selected_pipeline = result.payload["selected_pipeline"]
    assert selected_pipeline["target"] == "review.task"
    assert [operation["type"] for operation in selected_pipeline["operations"]] == [
        "select_context",
        "link_prompt",
        "check_guard",
        "check_permission",
        "validate_output",
        "fallback",
        "action",
    ]
    assert selected_pipeline["stable_prompt_ops"][0]["payload"] == {"fragment": "review.instructions"}
    assert selected_pipeline["volatile_context_ops"][0]["payload"] == {"include": ["git.diff"]}
    assert selected_pipeline["guard_ops"][0]["payload"] == {"guard": "tests_required"}
    assert selected_pipeline["permission_ops"][0]["payload"] == {"tool": "bash", "input": "pytest*"}
    assert selected_pipeline["fallback_ops"][0]["payload"] == {"name": "ask_for_clarification"}
    assert selected_pipeline["output_contracts"] == [
        {"target": "review.task", "format": ["findings"], "schema": {}}
    ]


def test_plugin_payload_includes_use_skill_operations_in_selected_skills(tmp_path: Path) -> None:
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
      - use_skill: superpowers:receiving-code-review
      - action: review_code
""",
    )

    from agentmf.plugin import create_plugin_payload

    result = create_plugin_payload(
        path=path,
        host="codex",
        request="please review code",
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["selected_skills"] == ["superpowers:receiving-code-review"]


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


def test_clawbench_harness_export_wraps_agentmf_payload(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  browser.task:
    match:
      user_intent:
        - buy a book
    steps:
      - select_context:
          include:
            - user_request
      - link_prompt:
          fragment: browser.instructions
      - check_permission:
          tool: browser
          input: "click*"
      - validate_output: task_result
""",
    )

    from agentmf.clawbench import create_clawbench_harness_export

    result = create_clawbench_harness_export(
        path=path,
        task_id="clawbench-v2-001",
        instruction="buy a book",
        host="codex",
        model="claude-opus-4-7",
    )

    assert result.ok, result.diagnostics.format()
    payload = result.payload
    assert payload["version"] == 1
    assert payload["mode"] == "clawbench_harness_export"
    assert payload["benchmark"] == "clawbench"
    assert payload["task"] == {
        "id": "clawbench-v2-001",
        "instruction": "buy a book",
    }
    assert payload["run"] == {
        "host": "codex",
        "model": "claude-opus-4-7",
        "execution": False,
        "harness": "agentmf-plugin-payload",
    }
    assert payload["agentmf"]["selected_targets"] == ["browser.task"]
    assert payload["agentmf"]["selected_pipeline"]["target"] == "browser.task"
    assert payload["prompt"]["stable_prefix"]["hash"].startswith("sha256:")
    assert payload["trace_bundle"]["permission_ops"][0]["payload"] == {
        "tool": "browser",
        "input": "click*",
    }
    assert payload["downstream_execution"] == {
        "status": "not_executed",
        "reason": "export_only_harness_layer",
    }


def test_cli_clawbench_export_outputs_json(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  browser.task:
    match:
      user_intent:
        - buy a book
    steps:
      - link_prompt:
          fragment: browser.instructions
""",
    )

    exit_code = main(
        [
            "clawbench",
            "export",
            "--file",
            str(path),
            "--task-id",
            "task-1",
            "--instruction",
            "buy a book",
            "--host",
            "codex",
            "--model",
            "claude-opus-4-7",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["clawbench_harness"]["task"]["id"] == "task-1"
    assert payload["clawbench_harness"]["agentmf"]["selected_targets"] == ["browser.task"]


def test_clawbench_jsonl_export_converts_task_file(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.task:
    match:
      user_intent:
        - implement feature
    steps:
      - link_prompt:
          fragment: code.instructions
  review.task:
    match:
      user_intent:
        - review change
    steps:
      - link_prompt:
          fragment: review.instructions
""",
    )
    tasks_file = tmp_path / "clawbench-tasks.jsonl"
    tasks_file.write_text(
        "\n".join(
            [
                json.dumps({"id": "task-1", "instruction": "implement feature"}),
                json.dumps({"task_id": "task-2", "prompt": "review change"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from agentmf.clawbench import create_clawbench_jsonl_export

    result = create_clawbench_jsonl_export(
        path=path,
        tasks_file=tasks_file,
        host="codex",
        model="claude-opus-4-7",
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["mode"] == "clawbench_harness_export_jsonl"
    assert result.payload["task_count"] == 2
    lines = result.payload["jsonl"].splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert [record["task"]["id"] for record in records] == ["task-1", "task-2"]
    assert records[0]["agentmf"]["selected_targets"] == ["code.task"]
    assert records[1]["agentmf"]["selected_targets"] == ["review.task"]
    assert records[0]["downstream_execution"]["status"] == "not_executed"


def test_cli_clawbench_export_jsonl_outputs_json_lines(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.task:
    match:
      user_intent:
        - implement feature
    steps:
      - link_prompt:
          fragment: code.instructions
  review.task:
    match:
      user_intent:
        - review change
    steps:
      - link_prompt:
          fragment: review.instructions
""",
    )
    tasks_file = tmp_path / "clawbench-tasks.jsonl"
    tasks_file.write_text(
        "\n".join(
            [
                json.dumps({"id": "task-1", "instruction": "implement feature"}),
                json.dumps({"id": "task-2", "instruction": "review change"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "clawbench",
            "export-jsonl",
            "--file",
            str(path),
            "--tasks-file",
            str(tasks_file),
            "--host",
            "codex",
            "--model",
            "claude-opus-4-7",
        ]
    )

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert exit_code == 0
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert records[0]["task"]["id"] == "task-1"
    assert records[1]["task"]["id"] == "task-2"
    assert records[0]["agentmf"]["selected_targets"] == ["code.task"]
    assert records[1]["agentmf"]["selected_targets"] == ["review.task"]


def test_cli_clawbench_export_jsonl_keeps_stdout_parseable_with_warnings(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.task:
    match:
      user_intent:
        - implement feature
    steps:
      - link_prompt:
          fragment: code.instructions
permissions:
  bash:
    "git status*": allow
""",
    )
    tasks_file = tmp_path / "clawbench-tasks.jsonl"
    tasks_file.write_text(
        json.dumps({"id": "task-1", "instruction": "implement feature"}) + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "clawbench",
            "export-jsonl",
            "--file",
            str(path),
            "--tasks-file",
            str(tasks_file),
            "--host",
            "codex",
        ]
    )

    captured = capsys.readouterr()
    records = [json.loads(line) for line in captured.out.splitlines()]
    assert exit_code == 0
    assert len(records) == 1
    assert records[0]["task"]["id"] == "task-1"
    assert "warning[AMF121]" in captured.err


def test_clawbench_host_adapter_contract_defines_external_runner_io() -> None:
    from agentmf.clawbench import create_clawbench_host_adapter_contract

    result = create_clawbench_host_adapter_contract(host="codex")

    assert result.ok, result.diagnostics.format()
    assert result.payload["mode"] == "clawbench_host_adapter_contract"
    assert result.payload["adapter"]["host"] == "codex"
    assert result.payload["input_contract"]["format"] == "jsonl"
    assert result.payload["input_contract"]["record_mode"] == "clawbench_harness_export"
    assert "task.id" in result.payload["input_contract"]["required_fields"]
    assert "agentmf.selected_pipeline" in result.payload["input_contract"]["required_fields"]
    assert result.payload["output_contract"]["format"] == "jsonl"
    assert "task_id" in result.payload["output_contract"]["required_fields"]
    assert "pass" in result.payload["output_contract"]["required_fields"]
    assert "cost_usd" in result.payload["output_contract"]["optional_fields"]


def test_clawbench_result_import_summarizes_external_runner_jsonl(tmp_path: Path) -> None:
    results_file = tmp_path / "clawbench-results.jsonl"
    results_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "task_id": "task-1",
                        "pass": True,
                        "reward_lenient": 1.0,
                        "reward_strict": 0.5,
                        "cost_usd": 0.20,
                        "wall_time_ms": 1000,
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "tool_calls": 4,
                        "denied_tool_calls": 0,
                        "agentmf": {"stable_prefix_hash": "sha256:aaa"},
                    }
                ),
                json.dumps(
                    {
                        "task": {"id": "task-2"},
                        "execution": {
                            "pass": False,
                            "cost_usd": 0.40,
                            "wall_time_ms": 3000,
                            "prompt_tokens": 200,
                            "completion_tokens": 80,
                            "tool_calls": 6,
                            "denied_tool_calls": 1,
                        },
                        "agentmf": {"stable_prefix_hash": "sha256:bbb"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from agentmf.clawbench import create_clawbench_result_summary

    result = create_clawbench_result_summary(results_file=results_file)

    assert result.ok, result.diagnostics.format()
    assert result.payload["mode"] == "clawbench_external_runner_results"
    assert result.payload["summary"] == {
        "result_count": 2,
        "pass_count": 1,
        "pass_rate": 0.5,
        "average_cost_usd": 0.3,
        "average_wall_time_ms": 2000.0,
        "average_total_tokens": 200.0,
        "tool_calls": 10,
        "denied_tool_calls": 1,
        "stable_prefix_hashes": ["sha256:aaa", "sha256:bbb"],
    }
    assert result.payload["results"][0]["task_id"] == "task-1"
    assert result.payload["results"][0]["pass"] is True
    assert result.payload["results"][1]["task_id"] == "task-2"
    assert result.payload["results"][1]["pass"] is False


def test_clawbench_result_import_accepts_flat_result_with_execution_metadata(tmp_path: Path) -> None:
    results_file = tmp_path / "clawbench-results.jsonl"
    results_file.write_text(
        json.dumps(
            {
                "task_id": "task-1",
                "pass": False,
                "cost_usd": 0,
                "wall_time_ms": 2489000,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "tool_calls": 174,
                "denied_tool_calls": 0,
                "execution": {
                    "stop_reason": "agent_idle",
                    "intercepted": False,
                    "result_category": "model_not_intercepted",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    from agentmf.clawbench import create_clawbench_result_summary

    result = create_clawbench_result_summary(results_file=results_file)

    assert result.ok, result.diagnostics.format()
    assert result.payload["summary"]["result_count"] == 1
    assert result.payload["summary"]["pass_rate"] == 0.0
    assert result.payload["summary"]["tool_calls"] == 174


def test_cli_clawbench_import_results_outputs_json(tmp_path: Path, capsys) -> None:
    results_file = tmp_path / "clawbench-results.jsonl"
    results_file.write_text(
        json.dumps(
            {
                "task_id": "task-1",
                "pass": True,
                "cost_usd": 0.2,
                "wall_time_ms": 1000,
                "prompt_tokens": 100,
                "completion_tokens": 20,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "clawbench",
            "import-results",
            "--results-file",
            str(results_file),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["clawbench_results"]["summary"]["result_count"] == 1
    assert payload["clawbench_results"]["summary"]["pass_rate"] == 1.0


def test_swebench_jsonl_export_converts_lite_subset(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.change:
    match:
      user_intent:
        - failing regression in Django
        - implement code fix
    steps:
      - select_context:
          include:
            - repo.checkout
            - problem_statement
      - link_prompt:
          fragment: code.instructions
      - check_permission:
          tool: bash
          input: "pytest*"
      - validate_output: patch
""",
    )
    tasks_file = tmp_path / "swebench-lite-subset.jsonl"
    tasks_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "instance_id": "django__django-11099",
                        "repo": "django/django",
                        "base_commit": "abc123",
                        "problem_statement": "Fix failing regression in Django.",
                        "test_patch": "diff --git a/tests.py b/tests.py",
                    }
                ),
                json.dumps(
                    {
                        "instance_id": "sympy__sympy-20590",
                        "repo": "sympy/sympy",
                        "base_commit": "def456",
                        "problem_statement": "Please support header rows in text table output.",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from agentmf.swebench import create_swebench_jsonl_export

    result = create_swebench_jsonl_export(
        path=path,
        tasks_file=tasks_file,
        host="codex",
        model="gpt-5.4",
        limit=2,
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["mode"] == "swebench_harness_export_jsonl"
    assert result.payload["benchmark"] == "swebench-lite"
    assert result.payload["task_count"] == 2
    lines = result.payload["jsonl"].splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    record = records[0]
    assert record["mode"] == "swebench_harness_export"
    assert record["benchmark"] == "swebench-lite"
    assert record["task"] == {
        "instance_id": "django__django-11099",
        "repo": "django/django",
        "base_commit": "abc123",
        "problem_statement": "Fix failing regression in Django.",
        "test_patch": "diff --git a/tests.py b/tests.py",
    }
    assert record["run"] == {
        "host": "codex",
        "model": "gpt-5.4",
        "execution": False,
        "harness": "agentmf-plugin-payload",
    }
    assert record["agentmf"]["selected_targets"] == ["code.change"]
    assert records[1]["task"]["instance_id"] == "sympy__sympy-20590"
    assert records[1]["agentmf"]["selected_targets"] == ["code.change"]
    assert record["trace_bundle"]["permission_ops"][0]["payload"] == {
        "tool": "bash",
        "input": "pytest*",
    }
    assert record["downstream_execution"] == {
        "status": "not_executed",
        "reason": "export_only_harness_layer",
    }


def test_cli_swebench_export_jsonl_outputs_json_lines(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.change:
    match:
      user_intent:
        - regression
    steps:
      - link_prompt:
          fragment: code.instructions
""",
    )
    tasks_file = tmp_path / "swebench-lite-subset.jsonl"
    tasks_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "instance_id": "django__django-11099",
                        "repo": "django/django",
                        "base_commit": "abc123",
                        "problem_statement": "Fix regression.",
                    }
                ),
                json.dumps(
                    {
                        "instance_id": "sympy__sympy-20590",
                        "repo": "sympy/sympy",
                        "base_commit": "def456",
                        "problem_statement": "Fix another regression.",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "swebench",
            "export-jsonl",
            "--file",
            str(path),
            "--tasks-file",
            str(tasks_file),
            "--host",
            "codex",
            "--model",
            "gpt-5.4",
            "--limit",
            "1",
        ]
    )

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    assert exit_code == 0
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["task"]["instance_id"] == "django__django-11099"
    assert record["agentmf"]["selected_targets"] == ["code.change"]


def test_swebench_comparison_report_summarizes_baselines_and_cache_reuse(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.change:
    match:
      user_intent:
        - implement code fix
    steps:
      - select_context:
          include:
            - repo.checkout
            - problem_statement
      - link_prompt:
          fragment: code.instructions
      - check_permission:
          tool: bash
          input: "pytest*"
      - validate_output: patch
""",
    )
    tasks_file = tmp_path / "swebench-lite-subset.jsonl"
    tasks_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "instance_id": "django__django-11099",
                        "repo": "django/django",
                        "base_commit": "abc123",
                        "problem_statement": "Please support header rows in text table output.",
                    }
                ),
                json.dumps(
                    {
                        "instance_id": "sympy__sympy-20590",
                        "repo": "sympy/sympy",
                        "base_commit": "def456",
                        "problem_statement": "Please improve equation rendering output.",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    baseline_file = tmp_path / "AGENTS_BASELINE.md"
    baseline_file.write_text("large all-in-one guidance\n" * 200, encoding="utf-8")

    from agentmf.swebench import create_swebench_comparison_report

    result = create_swebench_comparison_report(
        path=path,
        tasks_file=tasks_file,
        host="codex",
        model="gpt-5.4",
        limit=2,
        baselines=["baseline-file", "none"],
        baseline_file=baseline_file,
    )

    assert result.ok, result.diagnostics.format()
    payload = result.payload
    assert payload["mode"] == "swebench_deterministic_comparison"
    assert payload["summary"]["task_count"] == 2
    assert payload["summary"]["selected_targets"] == ["code.change"]
    assert payload["summary"]["stable_prefix_hash_reuse"] == {
        payload["summary"]["stable_prefix_hashes"][0]: 2,
    }
    assert payload["baseline_comparison"][0]["kind"] == "baseline-file"
    assert payload["baseline_comparison"][0]["average_savings_approx_tokens"] > 0
    assert payload["baseline_comparison"][1]["kind"] == "none"
    assert payload["cases"][0]["instance_id"] == "django__django-11099"
    assert payload["cases"][0]["selected_targets"] == ["code.change"]
    assert payload["cases"][0]["stable_prefix_approx_tokens"] > 0


def test_cli_swebench_compare_outputs_markdown(tmp_path: Path, capsys) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
targets:
  code.change:
    match:
      user_intent:
        - implement code fix
    steps:
      - link_prompt:
          fragment: code.instructions
""",
    )
    tasks_file = tmp_path / "swebench-lite-subset.jsonl"
    tasks_file.write_text(
        json.dumps(
            {
                "instance_id": "django__django-11099",
                "repo": "django/django",
                "base_commit": "abc123",
                "problem_statement": "Please support header rows in text table output.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "swebench",
            "compare",
            "--file",
            str(path),
            "--tasks-file",
            str(tasks_file),
            "--baseline",
            "none",
            "--format",
            "markdown",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "# AgentMakefile SWE-bench Deterministic Comparison" in captured.out
    assert "| django__django-11099 | code.change |" in captured.out


def test_swebench_execution_adapter_contract_defines_runner_io() -> None:
    from agentmf.swebench import create_swebench_execution_adapter_contract

    result = create_swebench_execution_adapter_contract(host="codex")

    assert result.ok, result.diagnostics.format()
    payload = result.payload
    assert payload["mode"] == "swebench_execution_adapter_contract"
    assert payload["benchmark"] == "swebench-lite"
    assert payload["adapter"]["host"] == "codex"
    assert payload["adapter"]["execution"] == "external"
    assert payload["input_contract"]["record_mode"] == "swebench_harness_export"
    assert "task.instance_id" in payload["input_contract"]["required_fields"]
    assert "prompt.stable_prefix.content" in payload["input_contract"]["required_fields"]
    assert payload["output_contract"]["record_mode"] == "swebench_execution_result"
    assert "instance_id" in payload["output_contract"]["required_fields"]
    assert "resolved" in payload["output_contract"]["required_fields"]
    assert "agentmf.stable_prefix_hash" in payload["output_contract"]["optional_fields"]


def test_swebench_result_import_summarizes_external_runner_jsonl(tmp_path: Path) -> None:
    results_file = tmp_path / "swebench-results.jsonl"
    results_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "instance_id": "astropy__astropy-12907",
                        "resolved": True,
                        "patch_applied": True,
                        "tests_passed": True,
                        "cost_usd": 1.5,
                        "wall_time_ms": 300000,
                        "prompt_tokens": 18000,
                        "completion_tokens": 2000,
                        "tool_calls": 22,
                        "denied_tool_calls": 0,
                        "agentmf": {"stable_prefix_hash": "sha256:aaa"},
                    }
                ),
                json.dumps(
                    {
                        "task": {"instance_id": "astropy__astropy-14182"},
                        "execution": {
                            "resolved": False,
                            "patch_applied": True,
                            "tests_passed": False,
                            "cost_usd": 2.5,
                            "wall_time_ms": 500000,
                            "prompt_tokens": 20000,
                            "completion_tokens": 4000,
                            "tool_calls": 30,
                            "denied_tool_calls": 1,
                        },
                        "agentmf": {"stable_prefix_hash": "sha256:aaa"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from agentmf.swebench import create_swebench_result_summary

    result = create_swebench_result_summary(results_file=results_file)

    assert result.ok, result.diagnostics.format()
    assert result.payload["mode"] == "swebench_execution_results"
    assert result.payload["summary"] == {
        "result_count": 2,
        "resolved_count": 1,
        "resolved_rate": 0.5,
        "patch_applied_count": 2,
        "patch_applied_rate": 1.0,
        "tests_passed_count": 1,
        "tests_passed_rate": 0.5,
        "average_cost_usd": 2.0,
        "average_wall_time_ms": 400000.0,
        "average_total_tokens": 22000.0,
        "cost_per_resolved": 4.0,
        "tool_calls": 52,
        "denied_tool_calls": 1,
        "stable_prefix_hashes": ["sha256:aaa"],
    }
    assert result.payload["results"][0]["instance_id"] == "astropy__astropy-12907"
    assert result.payload["results"][0]["resolved"] is True
    assert result.payload["results"][1]["instance_id"] == "astropy__astropy-14182"
    assert result.payload["results"][1]["resolved"] is False


def test_cli_swebench_import_results_outputs_json(tmp_path: Path, capsys) -> None:
    results_file = tmp_path / "swebench-results.jsonl"
    results_file.write_text(
        json.dumps(
            {
                "instance_id": "astropy__astropy-12907",
                "resolved": True,
                "patch_applied": True,
                "tests_passed": True,
                "cost_usd": 1.5,
                "prompt_tokens": 100,
                "completion_tokens": 20,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "swebench",
            "import-results",
            "--results-file",
            str(results_file),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["swebench_results"]["summary"]["result_count"] == 1
    assert payload["swebench_results"]["summary"]["resolved_rate"] == 1.0


def test_cli_swebench_pass_report_outputs_markdown(tmp_path: Path, capsys) -> None:
    results_file = tmp_path / "swebench-results.jsonl"
    baseline_report = tmp_path / "swebench-lite-comparison.md"
    baseline_report.write_text("# baseline report\n", encoding="utf-8")
    results_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "instance_id": "astropy__astropy-12907",
                        "resolved": True,
                        "patch_applied": True,
                        "tests_passed": True,
                        "cost_usd": 1.5,
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "agentmf": {"stable_prefix_hash": "sha256:aaa"},
                    }
                ),
                json.dumps(
                    {
                        "instance_id": "astropy__astropy-14182",
                        "resolved": False,
                        "patch_applied": True,
                        "tests_passed": False,
                        "cost_usd": 2.5,
                        "prompt_tokens": 200,
                        "completion_tokens": 40,
                        "agentmf": {"stable_prefix_hash": "sha256:aaa"},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "swebench",
            "pass-report",
            "--results-file",
            str(results_file),
            "--baseline-report",
            str(baseline_report),
            "--format",
            "markdown",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "# AgentMakefile SWE-bench Pass-Rate Report" in captured.out
    assert "- Resolved rate: 0.5" in captured.out
    assert "| astropy__astropy-12907 | yes | yes | yes |" in captured.out


def test_swebench_predictions_export_emits_official_jsonl(tmp_path: Path) -> None:
    patch_file = tmp_path / "astropy-14182.patch"
    patch_file.write_text("diff --git a/file.py b/file.py\n+fixed\n", encoding="utf-8")
    results_file = tmp_path / "swebench-results.jsonl"
    results_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "instance_id": "astropy__astropy-12907",
                        "model_patch": "diff --git a/a.py b/a.py\n+change\n",
                    }
                ),
                json.dumps(
                    {
                        "task": {"instance_id": "astropy__astropy-14182"},
                        "execution": {"patch_path": str(patch_file)},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from agentmf.swebench import create_swebench_predictions_export

    result = create_swebench_predictions_export(
        results_file=results_file,
        model_name_or_path="agentmf-gpt-5.4",
        dataset_profile="lite",
    )

    assert result.ok, result.diagnostics.format()
    assert result.payload["mode"] == "swebench_official_predictions_export"
    assert result.payload["profile"]["id"] == "lite"
    assert result.payload["profile"]["dataset_name"] == "princeton-nlp/SWE-bench_Lite"
    assert result.payload["prediction_count"] == 2
    lines = result.payload["jsonl"].splitlines()
    assert [json.loads(line) for line in lines] == [
        {
            "instance_id": "astropy__astropy-12907",
            "model_name_or_path": "agentmf-gpt-5.4",
            "model_patch": "diff --git a/a.py b/a.py\n+change\n",
        },
        {
            "instance_id": "astropy__astropy-14182",
            "model_name_or_path": "agentmf-gpt-5.4",
            "model_patch": "diff --git a/file.py b/file.py\n+fixed\n",
        },
    ]


def test_cli_swebench_predictions_outputs_official_jsonl(tmp_path: Path, capsys) -> None:
    results_file = tmp_path / "swebench-results.jsonl"
    results_file.write_text(
        json.dumps(
            {
                "instance_id": "astropy__astropy-12907",
                "patch": "diff --git a/a.py b/a.py\n+change\n",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "swebench",
            "predictions",
            "--results-file",
            str(results_file),
            "--model-name",
            "agentmf-gpt-5.4",
            "--dataset",
            "lite",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert [json.loads(line) for line in captured.out.splitlines()] == [
        {
            "instance_id": "astropy__astropy-12907",
            "model_name_or_path": "agentmf-gpt-5.4",
            "model_patch": "diff --git a/a.py b/a.py\n+change\n",
        }
    ]


def test_swebench_official_run_command_uses_verified_profile() -> None:
    from agentmf.swebench import create_swebench_official_run_command

    result = create_swebench_official_run_command(
        dataset_profile="verified",
        predictions_path=Path("predictions.jsonl"),
        run_id="agentmf-verified",
        max_workers=2,
        instance_ids=["astropy__astropy-12907"],
    )

    assert result.ok, result.diagnostics.format()
    payload = result.payload
    assert payload["mode"] == "swebench_official_run_command"
    assert payload["profile"]["id"] == "verified"
    assert payload["profile"]["dataset_name"] == "princeton-nlp/SWE-bench_Verified"
    assert payload["command"] == [
        "python",
        "-m",
        "swebench.harness.run_evaluation",
        "--dataset_name",
        "princeton-nlp/SWE-bench_Verified",
        "--split",
        "test",
        "--predictions_path",
        "predictions.jsonl",
        "--max_workers",
        "2",
        "--run_id",
        "agentmf-verified",
        "--instance_ids",
        "astropy__astropy-12907",
    ]
    assert "princeton-nlp/SWE-bench_Verified" in payload["command_text"]


def test_cli_swebench_official_command_outputs_text(capsys) -> None:
    exit_code = main(
        [
            "swebench",
            "official-command",
            "--dataset",
            "lite",
            "--predictions-path",
            "/tmp/predictions.jsonl",
            "--run-id",
            "agentmf-lite",
            "--max-workers",
            "1",
            "--format",
            "text",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "python -m swebench.harness.run_evaluation" in captured.out
    assert "--dataset_name princeton-nlp/SWE-bench_Lite" in captured.out


def test_swebench_official_dry_run_adapter_plan_limits_to_smoke_subset(tmp_path: Path) -> None:
    predictions_file = tmp_path / "predictions.jsonl"
    predictions_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "instance_id": "astropy__astropy-12907",
                        "model_name_or_path": "agentmf-gpt-5.4",
                        "model_patch": "diff --git a/a.py b/a.py\n+one\n",
                    }
                ),
                json.dumps(
                    {
                        "instance_id": "astropy__astropy-14182",
                        "model_name_or_path": "agentmf-gpt-5.4",
                        "model_patch": "diff --git a/b.py b/b.py\n+two\n",
                    }
                ),
                json.dumps(
                    {
                        "instance_id": "sympy__sympy-20590",
                        "model_name_or_path": "agentmf-gpt-5.4",
                        "model_patch": "diff --git a/c.py b/c.py\n+three\n",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    from agentmf.swebench import create_swebench_official_adapter_plan

    result = create_swebench_official_adapter_plan(
        dataset_profile="lite",
        predictions_path=predictions_file,
        run_id="agentmf-lite",
        max_workers=4,
        smoke_limit=2,
    )

    assert result.ok, result.diagnostics.format()
    payload = result.payload
    assert payload["mode"] == "swebench_official_adapter_dry_run"
    assert payload["execution"] is False
    assert payload["profile"]["id"] == "lite"
    assert payload["profile"]["official_instance_count"] == 300
    assert payload["prediction_summary"] == {
        "prediction_count": 3,
        "model_names": ["agentmf-gpt-5.4"],
        "first_instance_ids": [
            "astropy__astropy-12907",
            "astropy__astropy-14182",
            "sympy__sympy-20590",
        ],
    }
    assert payload["smoke_subset"] == {
        "limit": 2,
        "instance_ids": ["astropy__astropy-12907", "astropy__astropy-14182"],
    }
    assert payload["commands"]["smoke"]["execution"] is False
    assert payload["commands"]["smoke"]["command"][-3:] == [
        "--instance_ids",
        "astropy__astropy-12907",
        "astropy__astropy-14182",
    ]
    assert "--instance_ids" not in payload["commands"]["full"]["command"]
    assert payload["safety"]["full_profile_execution_requires_external_confirmation"] is True


def test_cli_swebench_official_dry_run_outputs_adapter_plan_json(tmp_path: Path, capsys) -> None:
    predictions_file = tmp_path / "predictions.jsonl"
    predictions_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "instance_id": "astropy__astropy-12907",
                        "model_name_or_path": "agentmf-gpt-5.4",
                        "model_patch": "diff --git a/a.py b/a.py\n+one\n",
                    }
                ),
                json.dumps(
                    {
                        "instance_id": "astropy__astropy-14182",
                        "model_name_or_path": "agentmf-gpt-5.4",
                        "model_patch": "diff --git a/b.py b/b.py\n+two\n",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "swebench",
            "official-dry-run",
            "--dataset",
            "verified",
            "--predictions-path",
            str(predictions_file),
            "--run-id",
            "agentmf-verified",
            "--smoke-limit",
            "1",
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    dry_run = payload["swebench_official_dry_run"]
    assert dry_run["profile"]["dataset_name"] == "princeton-nlp/SWE-bench_Verified"
    assert dry_run["profile"]["official_instance_count"] == 500
    assert dry_run["smoke_subset"]["instance_ids"] == ["astropy__astropy-12907"]
    assert dry_run["execution"] is False


def test_swebench_official_report_import_summarizes_schema_v2_report(tmp_path: Path) -> None:
    report_file = tmp_path / "agentmf-gpt-5.4.agentmf-lite.json"
    report_file.write_text(
        json.dumps(
            {
                "total_instances": 3,
                "submitted_instances": 2,
                "completed_instances": 2,
                "resolved_instances": 1,
                "unresolved_instances": 1,
                "empty_patch_instances": 0,
                "error_instances": 0,
                "completed_ids": ["astropy__astropy-12907", "astropy__astropy-14182"],
                "submitted_ids": ["astropy__astropy-12907", "astropy__astropy-14182"],
                "resolved_ids": ["astropy__astropy-12907"],
                "unresolved_ids": ["astropy__astropy-14182"],
                "error_ids": [],
                "empty_patch_ids": [],
                "schema_version": 2,
            }
        ),
        encoding="utf-8",
    )

    from agentmf.swebench import create_swebench_official_report_summary

    result = create_swebench_official_report_summary(report_file=report_file)

    assert result.ok, result.diagnostics.format()
    assert result.payload["mode"] == "swebench_official_report"
    assert result.payload["summary"] == {
        "schema_version": 2,
        "total_instances": 3,
        "submitted_instances": 2,
        "completed_instances": 2,
        "resolved_instances": 1,
        "unresolved_instances": 1,
        "empty_patch_instances": 0,
        "error_instances": 0,
        "resolved_rate": 0.5,
        "completion_rate": 1.0,
        "error_rate": 0.0,
    }
    assert result.payload["resolved_ids"] == ["astropy__astropy-12907"]


def test_cli_swebench_import_official_report_outputs_json(tmp_path: Path, capsys) -> None:
    report_file = tmp_path / "agentmf-gpt-5.4.agentmf-lite.json"
    report_file.write_text(
        json.dumps(
            {
                "total_instances": 1,
                "submitted_instances": 1,
                "completed_instances": 1,
                "resolved_instances": 1,
                "unresolved_instances": 0,
                "empty_patch_instances": 0,
                "error_instances": 0,
                "completed_ids": ["astropy__astropy-12907"],
                "submitted_ids": ["astropy__astropy-12907"],
                "resolved_ids": ["astropy__astropy-12907"],
                "unresolved_ids": [],
                "error_ids": [],
                "empty_patch_ids": [],
                "schema_version": 2,
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "swebench",
            "import-official-report",
            "--report-file",
            str(report_file),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["swebench_official_report"]["summary"]["resolved_rate"] == 1.0


def test_swebench_profiles_include_lite_and_verified_dataset_names() -> None:
    from agentmf.swebench import SWE_BENCH_PROFILES

    assert SWE_BENCH_PROFILES["lite"]["dataset_name"] == "princeton-nlp/SWE-bench_Lite"
    assert SWE_BENCH_PROFILES["verified"]["dataset_name"] == "princeton-nlp/SWE-bench_Verified"


def test_harness_benchmark_payload_reports_pipeline_metrics(tmp_path: Path) -> None:
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
      - select_context:
          include:
            - git.diff
      - link_prompt:
          fragment: review.instructions
      - check_guard: tests_required
      - check_permission:
          tool: bash
          input: "pytest*"
      - action: review_code
""",
    )

    from agentmf.benchmark import create_harness_benchmark_payload

    result = create_harness_benchmark_payload(
        path=path,
        cases=["please review code"],
        host="codex",
        backend="agents-fragments",
    )

    assert result.ok, result.diagnostics.format()
    case = result.payload["cases"][0]
    assert case["selected_targets"] == ["review.task"]
    assert case["baseline"]["kind"] == "agents-md"
    assert case["baseline"]["path"] == "AGENTS.md"
    assert case["pipeline_metrics"] == {
        "selected_pipeline_size": 5,
        "prompt_ops": 1,
        "context_ops": 1,
        "guard_ops": 1,
        "permission_ops": 1,
        "fallback_ops": 0,
    }
    assert case["stable_prefix_hash"].startswith("sha256:")
    assert case["baseline"]["hash"].startswith("sha256:")
    assert isinstance(case["baseline_savings"]["approx_tokens"], int)
    assert isinstance(case["all_in_one_baseline_savings"]["approx_tokens"], int)
    assert case["guard_permission_coverage"] == {
        "guard_ops": 1,
        "permission_ops": 1,
    }
    assert case["selection_trace_quality"]["has_selected_target"] is True


def test_harness_benchmark_payload_supports_compiled_baselines(tmp_path: Path) -> None:
    path = write_agentmakefile(
        tmp_path,
        """\
version: "0.1"
skills:
  review-skill:
    namespace: demo
    description: Review code.
targets:
  review.task:
    match:
      user_intent:
        - review code
    skills:
      - demo:review-skill
    steps:
      - action: review_code
""",
    )

    from agentmf.benchmark import create_harness_benchmark_payload

    claude_result = create_harness_benchmark_payload(
        path=path,
        cases=["please review code"],
        baseline="claude-md",
    )
    skills_index_result = create_harness_benchmark_payload(
        path=path,
        cases=["please review code"],
        baseline="skills-index",
    )

    assert claude_result.ok, claude_result.diagnostics.format()
    assert claude_result.payload["baseline"] == "claude-md"
    assert claude_result.payload["cases"][0]["baseline"]["kind"] == "claude-md"
    assert claude_result.payload["cases"][0]["baseline"]["path"] == "CLAUDE.md"
    assert claude_result.payload["cases"][0]["baseline"]["chars"] > 0

    assert skills_index_result.ok, skills_index_result.diagnostics.format()
    assert skills_index_result.payload["baseline"] == "skills-index"
    assert skills_index_result.payload["cases"][0]["baseline"]["kind"] == "skills-index"
    assert skills_index_result.payload["cases"][0]["baseline"]["path"] == "skills/index.md"
    assert skills_index_result.payload["cases"][0]["baseline"]["chars"] > 0


def test_harness_benchmark_payload_supports_file_and_all_skills_baselines(tmp_path: Path) -> None:
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
    baseline_file = tmp_path / "BASELINE.md"
    baseline_content = "large hand-written guidance\n"
    baseline_file.write_text(baseline_content)
    skills_dir = tmp_path / "skills"
    _write_skill(skills_dir, "alpha", "Alpha skill.", "Alpha body.")
    _write_skill(skills_dir, "beta", "Beta skill.", "Beta body.")

    from agentmf.benchmark import create_harness_benchmark_payload

    file_result = create_harness_benchmark_payload(
        path=path,
        cases=["please review code"],
        baseline="baseline-file",
        baseline_file=baseline_file,
    )
    all_skills_result = create_harness_benchmark_payload(
        path=path,
        cases=["please review code"],
        baseline="all-skills",
        baseline_skills_dirs=[skills_dir],
    )

    assert file_result.ok, file_result.diagnostics.format()
    assert file_result.payload["cases"][0]["baseline"] == {
        "kind": "baseline-file",
        "path": str(baseline_file),
        "sources": [str(baseline_file)],
        "chars": len(baseline_content),
        "approx_tokens": (len(baseline_content) + 3) // 4,
        "hash": f"sha256:{hashlib.sha256(baseline_content.encode()).hexdigest()}",
    }

    assert all_skills_result.ok, all_skills_result.diagnostics.format()
    baseline = all_skills_result.payload["cases"][0]["baseline"]
    assert baseline["kind"] == "all-skills"
    assert baseline["path"] == "<all-skills>"
    assert baseline["sources"] == [
        str(skills_dir / "alpha" / "SKILL.md"),
        str(skills_dir / "beta" / "SKILL.md"),
    ]
    assert baseline["chars"] > 0
    assert baseline["hash"].startswith("sha256:")


def test_cli_benchmark_harness_outputs_json(tmp_path: Path, capsys) -> None:
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
    baseline_file = tmp_path / "baseline.md"
    baseline_file.write_text("baseline guidance\n")

    exit_code = main(
        [
            "benchmark",
            "harness",
            "--file",
            str(path),
            "--host",
            "codex",
            "--case",
            "please review code",
            "--baseline",
            "baseline-file",
            "--baseline-file",
            str(baseline_file),
            "--format",
            "json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["harness_benchmark"]["summary"]["case_count"] == 1
    assert payload["harness_benchmark"]["cases"][0]["selected_targets"] == ["review.task"]
    assert payload["harness_benchmark"]["cases"][0]["baseline"]["kind"] == "baseline-file"


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
