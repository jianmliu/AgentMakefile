from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

import yaml
from pydantic import ValidationError

from agentmf.diagnostics import Diagnostic, Diagnostics
from agentmf.models import AgentMakefileSource, IncludeSpec, PermissionSpec


class AgentMakefileError(Exception):
    def __init__(self, diagnostics: Diagnostics) -> None:
        super().__init__(diagnostics.format())
        self.diagnostics = diagnostics


def load_source(path: Union[Path, str]) -> AgentMakefileSource:
    diagnostics = Diagnostics()
    source = _load_source(Path(path), diagnostics, set())
    if diagnostics.has_errors or source is None:
        raise AgentMakefileError(diagnostics)
    return source


def load_source_with_diagnostics(path: Union[Path, str]) -> Tuple[Optional[AgentMakefileSource], Diagnostics]:
    diagnostics = Diagnostics()
    source = _load_source(Path(path), diagnostics, set())
    return source, diagnostics


def _load_source(path: Path, diagnostics: Diagnostics, stack: Set[Path]) -> Optional[AgentMakefileSource]:
    resolved = path.resolve()
    if resolved in stack:
        diagnostics.error("AMF104", "circular include detected", str(path))
        return None
    if not resolved.exists():
        diagnostics.error("AMF101", "AgentMakefile does not exist", str(path))
        return None

    raw = _read_yaml(resolved, diagnostics)
    if raw is None:
        return None

    source = _validate_raw(raw, diagnostics, str(resolved))
    if source is None:
        return None

    if not source.include:
        return source

    stack.add(resolved)
    merged: Optional[AgentMakefileSource] = None
    for include in source.include:
        include_path = _include_path(include)
        child_path = (resolved.parent / include_path).resolve()
        child_source = _load_source(child_path, diagnostics, stack)
        if child_source is None:
            continue
        merged = child_source if merged is None else _merge_sources(merged, child_source)
    stack.remove(resolved)

    local_without_includes = source.model_copy(update={"include": []})
    if merged is None:
        return local_without_includes
    return _merge_sources(merged, local_without_includes)


def _read_yaml(path: Path, diagnostics: Diagnostics) -> Optional[Dict[str, Any]]:
    try:
        loaded = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as error:
        diagnostics.error("AMF100", f"invalid YAML: {error}", str(path))
        return None
    if not isinstance(loaded, dict):
        diagnostics.error("AMF100", "AgentMakefile must contain a YAML mapping at the top level", str(path))
        return None
    return loaded


def _validate_raw(raw: Dict[str, Any], diagnostics: Diagnostics, location: str) -> Optional[AgentMakefileSource]:
    try:
        return AgentMakefileSource.model_validate(raw)
    except ValidationError as error:
        diagnostics.extend(_diagnostics_from_validation_error(error, location))
        return None


def _diagnostics_from_validation_error(error: ValidationError, location: str) -> Iterable[Diagnostic]:
    for issue in error.errors():
        loc = ".".join(str(part) for part in issue.get("loc", ()))
        suffix = f":{loc}" if loc else ""
        yield Diagnostic(
            "error",
            "AMF102",
            issue.get("msg", "schema validation error"),
            f"{location}{suffix}",
        )


def _include_path(include: Union[str, IncludeSpec]) -> str:
    if isinstance(include, str):
        return include
    assert include.path is not None
    return include.path


def _merge_sources(base: AgentMakefileSource, overlay: AgentMakefileSource) -> AgentMakefileSource:
    base_permissions = _permission_spec(base)
    overlay_permissions = _permission_spec(overlay)
    permissions = PermissionSpec(
        defaults={**base_permissions.defaults, **overlay_permissions.defaults},
        rules=_merge_nested_permission_rules(base_permissions.rules, overlay_permissions.rules),
    )

    data = {
        "version": overlay.version or base.version,
        "metadata": {**base.metadata, **overlay.metadata},
        "include": [],
        "vars": {**base.vars, **overlay.vars},
        "compile": {"targets": overlay.compile.targets or base.compile.targets},
        "artifacts": {**base.artifacts, **base.outputs, **overlay.artifacts, **overlay.outputs},
        "outputs": {},
        "policies": {**base.policies, **overlay.policies},
        "skills": {**base.skills, **overlay.skills},
        "targets": {**base.targets, **overlay.targets},
        "permissions": permissions,
        "hooks": _merge_hooks(base.hooks, overlay.hooks),
        "validation": {**base.validation, **overlay.validation},
        "patterns": {**base.patterns, **overlay.patterns},
        "cache": {**base.cache, **overlay.cache},
        "tool_rules": {**base.tool_rules, **overlay.tool_rules},
        "compiler_hints": {**base.compiler_hints, **overlay.compiler_hints},
    }
    return AgentMakefileSource.model_validate(data)


def _permission_spec(source: AgentMakefileSource) -> PermissionSpec:
    permissions = source.permissions
    if isinstance(permissions, PermissionSpec):
        return permissions
    return PermissionSpec(rules=permissions)


def _merge_nested_permission_rules(
    base: Dict[str, Dict[str, str]],
    overlay: Dict[str, Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    merged = {tool: dict(rules) for tool, rules in base.items()}
    for tool, rules in overlay.items():
        merged.setdefault(tool, {}).update(rules)
    return merged


def _merge_hooks(
    base: Dict[str, List[Dict[str, Any]]],
    overlay: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, List[Dict[str, Any]]]:
    merged = {event: list(items) for event, items in base.items()}
    for event, items in overlay.items():
        merged.setdefault(event, []).extend(items)
    return merged
