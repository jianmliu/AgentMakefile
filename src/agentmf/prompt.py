from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Union

from agentmf.diagnostics import Diagnostics
from agentmf.runtime import create_run_plan

SECRET_CONTEXT_NAMES = {".env", ".npmrc", ".pypirc"}


@dataclass
class PromptPayloadResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_prompt_payload(
    path: Union[Path, str],
    request: Optional[str] = None,
    target_names: Optional[List[str]] = None,
    backend: str = "agents-fragments",
    plan_path: Optional[Union[Path, str]] = None,
    context_files: Optional[List[Union[Path, str]]] = None,
    include_git_status: bool = False,
    include_git_diff: bool = False,
) -> PromptPayloadResult:
    diagnostics = Diagnostics()
    agentmakefile_path = Path(path)
    plan = _read_plan(plan_path, diagnostics)
    context_file_records = _read_context_files(context_files, diagnostics)
    git_status = (
        _collect_git_context(agentmakefile_path.parent, "status", diagnostics)
        if include_git_status
        else None
    )
    git_diff = (
        _collect_git_context(agentmakefile_path.parent, "diff", diagnostics)
        if include_git_diff
        else None
    )
    if diagnostics.has_errors:
        return PromptPayloadResult(diagnostics)

    run_result = create_run_plan(
        path=path,
        request=request,
        target_names=target_names,
        backend=backend,
        dry_run=True,
    )
    diagnostics.extend(run_result.diagnostics.items)
    if diagnostics.has_errors:
        return PromptPayloadResult(diagnostics)

    prefix = run_result.plan["prompt_prefix"]
    stable_content = prefix["content"]
    link_plan = run_result.plan["link_plan"]
    routing_summary = _routing_summary(link_plan)
    volatile_context = {
        "request": request,
        "plan": plan,
        "git_status": git_status,
        "git_diff": git_diff,
        "context_files": context_file_records,
    }
    final_content = _compose_final_prompt(stable_content, volatile_context, routing_summary)
    payload = {
        "version": 1,
        "mode": "prompt",
        "request": request,
        "selected_targets": list(link_plan["selected_targets"]),
        "stable_prefix": {
            "backend": backend,
            "content": stable_content,
            **_content_metrics(stable_content),
        },
        "volatile_context": volatile_context,
        "routing_summary": routing_summary,
        "final_prompt": {
            "content": final_content,
            **_content_metrics(final_content),
        },
        "trace": {
            "target_closure": list(link_plan["target_closure"]),
            "linked_fragments": [fragment["path"] for fragment in prefix["fragments"]],
            "comparison": prefix["comparison"],
            "guard_evaluation": run_result.plan["guard_evaluation"],
            "permission_contract": run_result.plan["permission_contract"],
        },
        "diagnostics": diagnostics.to_list(),
    }
    return PromptPayloadResult(diagnostics, payload)


def _routing_summary(link_plan: Dict[str, Any]) -> Dict[str, Any]:
    """Produce an LLM-friendly summary of routing causality:
    - primary selected target
    - closure of auto-loaded deps, each annotated with which other
      closure target pulled it in (Makefile-style provenance)
    - declared and matcher-scored alternatives
    """
    selected = list(link_plan.get("selected_targets") or [])
    primary_name = selected[0] if selected else None
    closure = list(link_plan.get("target_closure") or [])
    pipelines = link_plan.get("target_pipelines") or []
    deps_by_target: Dict[str, List[str]] = {}
    for pipeline in pipelines:
        target = pipeline.get("target")
        if isinstance(target, str):
            deps_by_target[target] = list(pipeline.get("deps") or [])

    closure_entries: List[Dict[str, Any]] = []
    for target_name in closure:
        sponsor = None if target_name == primary_name else _closure_sponsor(target_name, closure, deps_by_target)
        closure_entries.append({"target": target_name, "depended_on_by": sponsor})

    selected_match: Optional[Dict[str, Any]] = None
    trace = link_plan.get("selection_trace") or {}
    selected_trace = trace.get("selected") if isinstance(trace, dict) else None
    if isinstance(selected_trace, dict):
        selected_match = {
            "target": selected_trace.get("target") or primary_name,
            "matched_terms": list(selected_trace.get("matched_terms") or []),
            "match_score": selected_trace.get("match_score"),
        }
    elif primary_name is not None:
        selected_match = {"target": primary_name, "matched_terms": [], "match_score": None}

    alternatives = list(link_plan.get("alternatives") or [])
    return {
        "primary": selected_match,
        "closure": closure_entries,
        "alternatives": alternatives,
    }


def _closure_sponsor(
    candidate: str,
    closure: List[str],
    deps_by_target: Dict[str, List[str]],
) -> Optional[str]:
    """Return the first closure target whose deps include `candidate`.

    Closure order matches selector's dependency-first traversal, so the
    first sponsor we find is the one that actually pulled `candidate` in.
    """
    for sponsor in closure:
        if sponsor == candidate:
            continue
        if candidate in deps_by_target.get(sponsor, []):
            return sponsor
    return None


def _compose_final_prompt(
    stable_prefix: str,
    volatile_context: Dict[str, Any],
    routing_summary: Optional[Dict[str, Any]] = None,
) -> str:
    has_routing_signal = _has_routing_signal(routing_summary)
    if not _has_volatile_context(volatile_context) and not has_routing_signal:
        return stable_prefix
    content = stable_prefix
    if content and not content.endswith("\n"):
        content += "\n"
    if has_routing_signal:
        content += "\n## Routing Decision\n\n"
        content += _render_routing_summary(routing_summary)
    if _has_volatile_context(volatile_context):
        content += "\n## Volatile Task Context\n"
        request = volatile_context["request"]
        if request is not None:
            content += f"\n### User Request\n\n{request.rstrip()}\n"
        plan = volatile_context["plan"]
        if plan is not None:
            content += f"\n### Plan\n\nSource: `{plan['path']}`\n\n{plan['content'].rstrip()}\n"
        for context_file in volatile_context["context_files"]:
            content += (
                "\n### Context File\n\n"
                f"Source: `{context_file['path']}`\n\n{context_file['content'].rstrip()}\n"
            )
        if volatile_context["git_status"] is not None:
            content += f"\n### Git Status\n\n```text\n{volatile_context['git_status'].rstrip()}\n```\n"
        if volatile_context["git_diff"] is not None:
            content += f"\n### Git Diff\n\n```diff\n{volatile_context['git_diff'].rstrip()}\n```\n"
    return content


def _has_volatile_context(volatile_context: Dict[str, Any]) -> bool:
    return any(
        [
            volatile_context["request"] is not None,
            volatile_context["plan"] is not None,
            volatile_context["git_status"] is not None,
            volatile_context["git_diff"] is not None,
            bool(volatile_context["context_files"]),
        ]
    )


def _has_routing_signal(routing_summary: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(routing_summary, dict):
        return False
    closure = routing_summary.get("closure") or []
    alternatives = routing_summary.get("alternatives") or []
    # We render the section only when there's something useful to say:
    # a closure beyond the primary itself, or any alternative.
    return len(closure) > 1 or len(alternatives) > 0


def _render_routing_summary(routing_summary: Dict[str, Any]) -> str:
    lines: List[str] = []
    primary = routing_summary.get("primary") or {}
    primary_name = primary.get("target")
    if primary_name:
        matched = ", ".join(f"`{term}`" for term in primary.get("matched_terms") or []) or "(no matched terms)"
        lines.append(f"- Primary target: `{primary_name}` (matched: {matched})")
    closure = routing_summary.get("closure") or []
    deps = [entry for entry in closure if entry.get("depended_on_by")]
    if deps:
        lines.append("- Dependency closure (auto-loaded):")
        for entry in deps:
            lines.append(
                f"  - `{entry['target']}` depended on by `{entry['depended_on_by']}`"
            )
    alternatives = routing_summary.get("alternatives") or []
    if alternatives:
        lines.append("- Alternatives the selector considered:")
        for alt in alternatives:
            if alt.get("source") == "declared_fallback":
                lines.append(
                    f"  - `{alt['target']}` (declared fallback for `{primary_name}` "
                    f"under condition `{alt.get('condition', 'runtime')}`)"
                )
            else:
                score = alt.get("match_score")
                score_str = f" score={score}" if score is not None else ""
                lines.append(f"  - `{alt['target']}` (matcher{score_str}; {alt.get('reason') or 'no reason'})")
    return "\n".join(lines) + "\n"


def _content_metrics(content: str) -> Dict[str, Any]:
    return {
        "chars": len(content),
        "approx_tokens": (len(content) + 3) // 4,
        "hash": f"sha256:{sha256(content.encode('utf-8')).hexdigest()}",
    }


def _read_plan(plan_path: Optional[Union[Path, str]], diagnostics: Diagnostics) -> Optional[Dict[str, str]]:
    if plan_path is None:
        return None
    path = Path(plan_path)
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        diagnostics.error(
            "AMF136",
            f"could not read plan file: {path}",
            "prompt.plan",
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
                "AMF137",
                f"refusing to read secret-looking context file: {path}",
                "prompt.context",
                "pass only non-secret context files",
            )
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            diagnostics.error(
                "AMF138",
                f"could not read context file: {path}",
                "prompt.context",
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
            "AMF139" if kind == "status" else "AMF140",
            f"could not collect git {kind}",
            f"prompt.git_{kind}",
            result.stderr.strip() or "git command failed",
        )
        return None
    return result.stdout
