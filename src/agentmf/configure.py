"""`agentmf configure` — show / edit which compile backends are active.

Mirrors the GNU autotools `./configure` step in the four-step AgentMakefile
build pipeline (autoconf → configure → make → make install). Reads
`compile.targets` from the AgentMakefile source and either reports the
current selection (status / list / validate) or rewrites it in place
(add / remove).

Runtime per-request routing (`agentmf select` / `agentmf prompt`) is a
separate axis — this command only touches the build-time backend set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

from agentmf.backends import DEFAULT_BACKENDS, SUPPORTED_BACKENDS
from agentmf.diagnostics import Diagnostics
from agentmf.loader import load_source_with_diagnostics

CONFIGURE_ACTIONS = ("status", "list", "validate", "add", "remove")


@dataclass
class ConfigureResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


# Where each backend writes by default when the AgentMakefile doesn't
# override via `artifacts.<backend>.path`. Mirrors the constants
# embedded in each Backend.emit() in backends.py — kept here as a
# user-facing description so `configure` doesn't have to instantiate
# the full IR just to print paths.
_BACKEND_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    "claude-md": {
        "description": "Markdown guidance file for Claude Code.",
        "default_output": "CLAUDE.md",
    },
    "agents-md": {
        "description": "Markdown guidance file for generic coding agents.",
        "default_output": "AGENTS.md",
    },
    "cursor-rule": {
        "description": "Cursor rules file with frontmatter (always-apply support).",
        "default_output": ".cursor/rules/agentmakefile-generated.mdc",
    },
    "claude-skill": {
        "description": "Per-skill packages for Claude Code's skill loader.",
        "default_output": ".claude/skills/<skill>/SKILL.md",
    },
    "codex-skill": {
        "description": "Per-skill packages for OpenAI Codex's skill loader.",
        "default_output": ".codex/skills/<skill>/SKILL.md",
    },
    "skills-index": {
        "description": "Aggregate skill index for tools that read a flat catalog.",
        "default_output": "skills/index.md",
    },
    "claude-code": {
        "description": "Claude Code settings.json + hook scripts (hard permissions).",
        "default_output": ".claude/settings.json (+ hooks under .claude/hooks/)",
    },
    "opencode": {
        "description": "OpenCode config (agents + permissions, hard enforcement).",
        "default_output": "opencode.json",
    },
    "memory-md": {
        "description": "Typed memory corpus compiled to one MEMORY.md, rendered per kind.",
        "default_output": "MEMORY.md",
    },
    "agents-fragments": {
        "description": "Per-target Markdown fragments for generic agents (runtime injection).",
        "default_output": ".agentmf/fragments/agents/<target>.md",
    },
    "claude-fragments": {
        "description": "Per-target Markdown fragments for Claude (runtime injection).",
        "default_output": ".agentmf/fragments/claude/<target>.md",
    },
}


def _backend_describe(name: str) -> Dict[str, str]:
    info = _BACKEND_DESCRIPTIONS.get(name)
    if info is not None:
        return dict(info)
    return {"description": f"Backend {name!r}.", "default_output": "(unknown)"}


def _resolve_output_path(name: str, artifact_path: Optional[str]) -> str:
    if artifact_path:
        return artifact_path
    return _backend_describe(name).get("default_output", "(unknown)")


def _active_backend_entries(source_targets: List[str], artifacts: Dict[str, Any]) -> List[Dict[str, str]]:
    entries: List[Dict[str, str]] = []
    for name in source_targets:
        artifact_path = None
        artifact = artifacts.get(name) if isinstance(artifacts, dict) else None
        if isinstance(artifact, dict):
            artifact_path = artifact.get("path")
        else:
            artifact_path = getattr(artifact, "path", None)
        entries.append({
            "backend": name,
            "path": _resolve_output_path(name, artifact_path),
            "description": _backend_describe(name)["description"],
        })
    return entries


def create_configure_payload(
    *,
    path: Union[Path, str] = "AgentMakefile",
    action: str = "status",
    backend: Optional[str] = None,
    write: bool = False,
) -> ConfigureResult:
    diagnostics = Diagnostics()
    if action not in CONFIGURE_ACTIONS:
        diagnostics.error(
            "AMF230",
            f"unsupported configure action: {action}",
            "configure.action",
            f"use one of: {', '.join(CONFIGURE_ACTIONS)}",
        )
        return ConfigureResult(diagnostics)

    source_path = Path(path)
    source, source_diagnostics = load_source_with_diagnostics(source_path)
    diagnostics.extend(source_diagnostics.items)
    if source is None:
        return ConfigureResult(diagnostics)

    configured_targets = list(source.compile.targets)
    is_default = not configured_targets
    effective_targets = configured_targets if configured_targets else list(DEFAULT_BACKENDS)
    artifacts = source.artifacts

    if action == "list":
        backends_payload = [
            {"backend": name, **_backend_describe(name)}
            for name in sorted(SUPPORTED_BACKENDS)
        ]
        return ConfigureResult(
            diagnostics,
            {
                "mode": "configure",
                "action": "list",
                "file": str(source_path),
                "backends": backends_payload,
            },
        )

    active = _active_backend_entries(effective_targets, artifacts)
    available = sorted(name for name in SUPPORTED_BACKENDS if name not in effective_targets)

    if action == "status":
        return ConfigureResult(
            diagnostics,
            {
                "mode": "configure",
                "action": "status",
                "file": str(source_path),
                "is_default": is_default,
                "compile_targets": list(effective_targets),
                "active_backends": active,
                "available_backends": available,
            },
        )

    if action == "validate":
        for name in effective_targets:
            if name not in SUPPORTED_BACKENDS:
                diagnostics.error(
                    "AMF103",
                    f"unknown backend target {name}",
                    "compile.targets",
                )
        return ConfigureResult(
            diagnostics,
            {
                "mode": "configure",
                "action": "validate",
                "file": str(source_path),
                "is_default": is_default,
                "compile_targets": list(effective_targets),
            },
        )

    # add / remove: mutate compile.targets and (optionally) write back to disk.
    if backend is None:
        diagnostics.error(
            "AMF231",
            f"configure --{action} requires a backend name",
            f"configure.{action}",
        )
        return ConfigureResult(diagnostics)
    if action == "add" and backend not in SUPPORTED_BACKENDS:
        diagnostics.error(
            "AMF103",
            f"unknown backend target {backend}",
            "compile.targets",
            f"available: {', '.join(sorted(SUPPORTED_BACKENDS))}",
        )
        return ConfigureResult(diagnostics)

    # Re-read raw yaml so we can write back a minimal mutation. We don't go
    # through the pydantic IR because IR drops sections we don't model
    # (and we want the round-trip to keep unmodeled keys intact). Comments
    # ARE lost on rewrite; the README's "configure" section documents that.
    raw_text = source_path.read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(raw_text) or {}
    except yaml.YAMLError as exc:
        diagnostics.error("AMF232", f"could not parse AgentMakefile: {exc}", str(source_path))
        return ConfigureResult(diagnostics)
    if not isinstance(raw, dict):
        diagnostics.error("AMF232", "AgentMakefile root must be a mapping", str(source_path))
        return ConfigureResult(diagnostics)

    compile_section = raw.get("compile")
    if not isinstance(compile_section, dict):
        compile_section = {}
        raw["compile"] = compile_section
    current_targets = compile_section.get("targets")
    if not isinstance(current_targets, list):
        current_targets = []

    next_targets = list(current_targets)
    wrote = False
    if action == "add":
        if backend not in next_targets:
            next_targets.append(backend)
            wrote = True
    elif action == "remove":
        if backend in next_targets:
            next_targets = [t for t in next_targets if t != backend]
            wrote = True

    if wrote and write:
        compile_section["targets"] = next_targets
        raw["compile"] = compile_section
        new_text = yaml.safe_dump(raw, sort_keys=False, default_flow_style=False)
        source_path.write_text(new_text, encoding="utf-8")
    elif wrote and not write:
        # Caller wants the proposed result but didn't ask for a write —
        # surface the would-be value without touching disk.
        wrote = False

    return ConfigureResult(
        diagnostics,
        {
            "mode": "configure",
            "action": action,
            "file": str(source_path),
            "backend": backend,
            "wrote": wrote,
            "compile_targets": next_targets,
        },
    )
