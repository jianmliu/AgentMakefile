from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from shlex import quote
from typing import Any, Dict, Optional, Sequence, Union

from agentmf.diagnostics import Diagnostics
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
    skill_dirs: Sequence[Union[Path, str]],
    *,
    host: str = "generic",
    namespace: Optional[str] = None,
    package_name: str = "scanned-skills",
    package_description: Optional[str] = None,
    bootstrap_skill: Optional[str] = None,
    out_path: Union[Path, str] = DEFAULT_PLUGIN_AGENTMAKEFILE,
    write: bool = False,
) -> PluginInstallPayloadResult:
    diagnostics = Diagnostics()
    if host not in HOSTS:
        diagnostics.error(
            "AMF136",
            f"unsupported plugin host: {host}",
            "plugin.install.host",
            "use one of: claude-code, codex, cursor, generic, opencode",
        )
        return PluginInstallPayloadResult(diagnostics)

    paths = [Path(path) for path in skill_dirs]
    try:
        content = render_agentmakefile_from_skill_dirs(
            paths,
            namespace=namespace,
            package_name=package_name,
            package_description=package_description,
            bootstrap_skill=bootstrap_skill,
        )
    except ValueError as exc:
        diagnostics.error(
            "AMF137",
            "could not scan skills for plugin install",
            "plugin.install.skills",
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
        "skills_dirs": [str(path) for path in paths],
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
