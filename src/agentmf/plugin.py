from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Union

from agentmf.backends import skill_slug
from agentmf.diagnostics import Diagnostics
from agentmf.runtime import create_run_plan


HOST_PROFILES = {
    "generic": {
        "profile": "generic",
        "injection": "prepend_stable_prefix_append_volatile_context",
        "preferred_cache_boundary": "after_stable_prefix",
        "permissions_mode": "soft_guidance",
        "instruction_surface": "generic_prompt_payload",
        "native_artifacts": [],
    },
    "codex": {
        "profile": "codex",
        "injection": "prepend_stable_prefix_append_volatile_context",
        "preferred_cache_boundary": "after_stable_prefix",
        "permissions_mode": "host_enforced_when_supported",
        "instruction_surface": "AGENTS.md_or_plugin_payload",
        "native_artifacts": [],
    },
    "claude-code": {
        "profile": "claude-code",
        "injection": "prepend_stable_prefix_append_volatile_context",
        "preferred_cache_boundary": "after_stable_prefix",
        "permissions_mode": "host_enforced_when_supported",
        "instruction_surface": "CLAUDE.md_or_claude_code_hooks",
        "native_artifacts": [".claude/settings.json", ".claude/hooks/*"],
    },
    "cursor": {
        "profile": "cursor",
        "injection": "prepend_stable_prefix_append_volatile_context",
        "preferred_cache_boundary": "after_stable_prefix",
        "permissions_mode": "soft_guidance",
        "instruction_surface": ".cursor/rules_or_plugin_payload",
        "native_artifacts": [],
    },
    "opencode": {
        "profile": "opencode",
        "injection": "prepend_stable_prefix_append_volatile_context",
        "preferred_cache_boundary": "after_stable_prefix",
        "permissions_mode": "host_enforced_when_supported",
        "instruction_surface": "opencode.json_or_plugin_payload",
        "native_artifacts": ["opencode.json"],
    },
}
HOSTS = set(HOST_PROFILES)
SECRET_CONTEXT_NAMES = {".env", ".npmrc", ".pypirc"}


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
    plan_path: Optional[Union[Path, str]] = None,
    context_files: Optional[List[Union[Path, str]]] = None,
    include_git_status: bool = False,
    include_git_diff: bool = False,
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

    agentmakefile_path = Path(path)
    plan = _read_plan(plan_path, diagnostics)
    context_file_records = _read_context_files(context_files, diagnostics)
    git_status = _collect_git_context(agentmakefile_path.parent, "status", diagnostics) if include_git_status else None
    git_diff = _collect_git_context(agentmakefile_path.parent, "diff", diagnostics) if include_git_diff else None
    if diagnostics.has_errors:
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
    selected_skills = _selected_skills(run_result.plan)
    payload = {
        "version": 1,
        "host": host,
        "mode": "prompt_payload",
        "request": request,
        "selected_targets": list(run_result.plan["link_plan"]["selected_targets"]),
        "selected_skills": selected_skills,
        "selected_pipeline": {
            "target_closure": list(run_result.plan["link_plan"]["target_closure"]),
            "targets": list(run_result.plan.get("target_pipelines", [])),
        },
        "skill_artifacts": _skill_artifacts(selected_skills),
        "selection_trace": run_result.plan["link_plan"].get("selection_trace", {}),
        "stable_prefix": {
            "backend": backend,
            "content": content,
            "chars": len(content),
            "approx_tokens": (len(content) + 3) // 4,
            "hash": f"sha256:{sha256(content.encode('utf-8')).hexdigest()}",
        },
        "volatile_context": {
            "plan": plan,
            "git_status": git_status,
            "git_diff": git_diff,
            "context_files": context_file_records,
        },
        "host_instructions": _host_instructions(host),
        "trace": {
            "target_closure": list(run_result.plan["link_plan"]["target_closure"]),
            "selection": run_result.plan["link_plan"].get("selection_trace", {}),
            "linked_fragments": [fragment["path"] for fragment in prefix["fragments"]],
            "comparison": prefix["comparison"],
        },
        "diagnostics": diagnostics.to_list(),
    }
    return PluginPayloadResult(diagnostics, payload)


def _selected_skills(run_plan: Dict[str, Any]) -> List[str]:
    selected = []
    seen = set()
    for target_contract in run_plan.get("target_contracts", []):
        for skill in target_contract.get("skills", []):
            if skill in seen:
                continue
            seen.add(skill)
            selected.append(skill)
    return selected


def _skill_artifacts(selected_skills: List[str]) -> Dict[str, Any]:
    return {
        "skills_index": "skills/index.md",
        "codex": [_skill_artifact_path(".codex/skills", skill) for skill in selected_skills],
        "claude": [_skill_artifact_path(".claude/skills", skill) for skill in selected_skills],
    }


def _skill_artifact_path(base_dir: str, skill: str) -> str:
    return f"{base_dir}/{skill_slug(skill)}/SKILL.md"


def _host_instructions(host: str) -> Dict[str, Any]:
    profile = HOST_PROFILES[host]
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in profile.items()
    }


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


def _read_context_files(
    context_files: Optional[List[Union[Path, str]]],
    diagnostics: Diagnostics,
) -> List[Dict[str, str]]:
    records = []
    for raw_path in context_files or []:
        path = Path(raw_path)
        if path.name in SECRET_CONTEXT_NAMES or "secret" in path.name.lower():
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


def _collect_git_context(repo_dir: Path, kind: str, diagnostics: Diagnostics) -> Optional[str]:
    commands = {
        "status": ["git", "-C", str(repo_dir), "status", "--short"],
        "diff": ["git", "-C", str(repo_dir), "diff", "--"],
    }
    result = subprocess.run(commands[kind], capture_output=True, text=True)
    if result.returncode != 0:
        diagnostics.error(
            "AMF134" if kind == "status" else "AMF135",
            f"could not collect git {kind}",
            f"plugin.git_{kind}",
            result.stderr.strip() or "git command failed",
        )
        return None
    return result.stdout
