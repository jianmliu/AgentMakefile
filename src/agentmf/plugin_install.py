from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from shlex import quote
from typing import Any, Dict, Optional, Sequence, Union

from agentmf.diagnostics import Diagnostics
from agentmf.guidance_scanner import render_agentmakefile_from_guidance_files
from agentmf.plugin import HOSTS
from agentmf.skill_scanner import render_agentmakefile_from_skill_dirs


DEFAULT_PLUGIN_AGENTMAKEFILE = Path(".agentmf/plugin/AgentMakefile")


@dataclass
class PluginInstallPayloadResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_plugin_install_payload(
    skill_dirs: Sequence[Union[Path, str]] = (),
    *,
    sources: Sequence[Union[Path, str]] = (),
    host: str = "generic",
    namespace: Optional[str] = None,
    package_name: str = "scanned-skills",
    package_description: Optional[str] = None,
    bootstrap_skill: Optional[str] = None,
    out_path: Union[Path, str] = DEFAULT_PLUGIN_AGENTMAKEFILE,
    write: bool = False,
) -> PluginInstallPayloadResult:
    """Generate a plugin AgentMakefile from one of:

    - `skill_dirs`: directory trees of SKILL.md files (existing behaviour;
      uses `render_agentmakefile_from_skill_dirs`)
    - `sources`: single guidance files (SKILL.md / AGENTS.md / CLAUDE.md /
      markdown; uses `render_agentmakefile_from_guidance_files`)

    Exactly one mode wins per call. When both are passed, skill_dirs takes
    precedence (preserves legacy callers) and sources is reported but
    unused; a diagnostic flags the conflict.
    """
    diagnostics = Diagnostics()
    if host not in HOSTS:
        diagnostics.error(
            "AMF136",
            f"unsupported plugin host: {host}",
            "plugin.install.host",
            "use one of: claude-code, codex, cursor, generic, opencode",
        )
        return PluginInstallPayloadResult(diagnostics)

    skill_dir_paths = [Path(path) for path in skill_dirs]
    source_paths = [Path(path) for path in sources]
    if not skill_dir_paths and not source_paths:
        diagnostics.error(
            "AMF139",
            "plugin install requires at least one --skills-dir or --source",
            "plugin.install.sources",
        )
        return PluginInstallPayloadResult(diagnostics)
    if skill_dir_paths and source_paths:
        diagnostics.warning(
            "AMF139",
            "both --skills-dir and --source provided; using --skills-dir and ignoring --source",
            "plugin.install.sources",
        )

    try:
        if skill_dir_paths:
            content = render_agentmakefile_from_skill_dirs(
                skill_dir_paths,
                namespace=namespace,
                package_name=package_name,
                package_description=package_description,
                bootstrap_skill=bootstrap_skill,
            )
            effective_sources: list = []
        else:
            content = render_agentmakefile_from_guidance_files(
                source_paths,
                package_name=package_name,
                package_description=package_description,
            )
            effective_sources = source_paths
    except ValueError as exc:
        diagnostics.error(
            "AMF137",
            "could not scan inputs for plugin install",
            "plugin.install.sources",
            str(exc),
        )
        return PluginInstallPayloadResult(diagnostics)

    destination = Path(out_path)
    if write:
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        except OSError as exc:
            diagnostics.error(
                "AMF138",
                f"could not write generated AgentMakefile: {destination}",
                "plugin.install.out",
                str(exc),
            )
            return PluginInstallPayloadResult(diagnostics)

    next_payload_command = _next_payload_command(destination, host)
    payload = {
        "version": 1,
        "host": host,
        "mode": "plugin_install",
        "skills_dirs": [str(path) for path in skill_dir_paths],
        "sources": [str(path) for path in effective_sources],
        "agentmakefile": {
            "path": str(destination),
            "wrote": write,
            "content": None if write else content,
        },
        "next_payload_command": next_payload_command,
        "model_instructions": _model_instructions(
            host=host,
            agentmakefile_path=destination,
            next_payload_command=next_payload_command,
        ),
        "diagnostics": diagnostics.to_list(),
    }
    return PluginInstallPayloadResult(diagnostics, payload)


def _next_payload_command(agentmakefile_path: Path, host: str) -> str:
    return (
        "agentmf plugin payload "
        f"--file {quote(str(agentmakefile_path))} "
        f"--host {host} "
        '--request "$USER_REQUEST" '
        "--format json"
    )


def _model_instructions(
    *,
    host: str,
    agentmakefile_path: Path,
    next_payload_command: str,
) -> str:
    return "\n".join(
        [
            "Use AgentMakefile as the skill-selection index for this plugin.",
            f"The generated skill index is {agentmakefile_path}.",
            "Before choosing or loading skills for each user request, call:",
            next_payload_command,
            "Read selected_skills to decide which native skill files to load.",
            "Read skill_artifacts for Codex/Claude-compatible SKILL.md paths when the host supports native skills.",
            "Read selection_trace to understand and explain why those skills were selected.",
            "Inject stable_prefix.content as the stable prompt prefix and keep volatile_context request data outside that prefix.",
            f"Host profile: {host}.",
        ]
    )
