from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from shlex import quote
from typing import Any, Dict, Optional, Union

from agentmf.compiler import compile_agentmakefile
from agentmf.diagnostics import Diagnostics


HOST_SKILL_PROFILES = {
    "codex": {
        "backend": "codex-skill",
        "generated_root": ".codex/skills",
        "default_root": Path.home() / ".codex" / "skills",
    },
    "claude-code": {
        "backend": "claude-skill",
        "generated_root": ".claude/skills",
        "default_root": Path.home() / ".claude" / "skills",
    },
}


@dataclass
class SkillSyncPayloadResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_skill_sync_payload(
    path: Union[Path, str],
    *,
    host: str,
    out_dir: Optional[Union[Path, str]] = None,
    write: bool = False,
    force: bool = False,
) -> SkillSyncPayloadResult:
    diagnostics = Diagnostics()
    if host not in HOST_SKILL_PROFILES:
        diagnostics.error(
            "AMF139",
            f"unsupported skill sync host: {host}",
            "skills.sync.host",
            "use one of: claude-code, codex",
        )
        return SkillSyncPayloadResult(diagnostics)

    profile = HOST_SKILL_PROFILES[host]
    source_path = Path(path)
    backend = str(profile["backend"])
    generated_root = str(profile["generated_root"])
    skill_root = Path(out_dir).expanduser() if out_dir else Path(profile["default_root"])

    compile_result = compile_agentmakefile(source_path, targets=[backend])
    diagnostics.extend(compile_result.diagnostics.items)
    if diagnostics.has_errors:
        return SkillSyncPayloadResult(diagnostics)

    file_records = []
    write_plan = []
    for generated in compile_result.files:
        relative_path = _relative_skill_path(generated.path, generated_root, diagnostics)
        if relative_path is None:
            continue
        destination = skill_root / relative_path
        record = {
            "source_path": generated.path,
            "destination": str(destination),
            "status": "planned",
        }
        file_records.append(record)
        if not write:
            continue
        write_plan.append((destination, generated.content, record))
        if destination.exists() and destination.read_text(encoding="utf-8") != generated.content and not force:
            diagnostics.error(
                "AMF140",
                "refusing to overwrite existing installed skill without --force",
                str(destination),
                "pass --force or choose a different --out-dir",
            )

    if diagnostics.has_errors:
        return SkillSyncPayloadResult(diagnostics, _payload(source_path, host, backend, skill_root, write, force, file_records))

    if write:
        for destination, content, record in write_plan:
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and destination.read_text(encoding="utf-8") == content:
                record["status"] = "unchanged"
                continue
            destination.write_text(content, encoding="utf-8")
            record["status"] = "wrote"

    return SkillSyncPayloadResult(
        diagnostics,
        _payload(source_path, host, backend, skill_root, write, force, file_records),
    )


def _relative_skill_path(path: str, generated_root: str, diagnostics: Diagnostics) -> Optional[Path]:
    prefix = f"{generated_root.rstrip('/')}/"
    if not path.startswith(prefix):
        diagnostics.error(
            "AMF141",
            f"compiled skill path is outside expected host skill root: {path}",
            "skills.sync.files",
            f"expected generated path under {generated_root}",
        )
        return None
    return Path(path[len(prefix) :])


def _payload(
    source_path: Path,
    host: str,
    backend: str,
    skill_root: Path,
    write: bool,
    force: bool,
    file_records: list[Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "version": 1,
        "host": host,
        "mode": "skill_sync",
        "agentmakefile_path": str(source_path),
        "backend": backend,
        "skill_root": str(skill_root),
        "write": write,
        "force": force,
        "files": file_records,
        "next_payload_command": _next_payload_command(source_path, host),
        "host_integration_instructions": _host_integration_instructions(source_path, host, skill_root),
    }


def _next_payload_command(source_path: Path, host: str) -> str:
    return (
        "agentmf plugin payload "
        f"--file {quote(str(source_path))} "
        f"--host {host} "
        '--request "$USER_REQUEST" '
        "--format json"
    )


def _host_integration_instructions(source_path: Path, host: str, skill_root: Path) -> str:
    return "\n".join(
        [
            "Sync installs AgentMakefile-generated native skills into the host skill root.",
            f"Host: {host}.",
            f"Skill root: {skill_root}.",
            "Before each user request, call:",
            _next_payload_command(source_path, host),
            "Read selected_skills to decide which installed skills to load.",
            "Read skill_artifacts to map selected skills to native SKILL.md package paths.",
            "Read selection_trace to explain why those skills were selected.",
        ]
    )
