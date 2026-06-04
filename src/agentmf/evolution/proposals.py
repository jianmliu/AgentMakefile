"""Evolution proposals (split from evolution.py — in-tree package, same public API)."""
from __future__ import annotations

from agentmf.diagnostics import Diagnostics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union
import json
from agentmf.evolution.evidence import _evidence_ref, _load_evidence_records, _sha256_json, _utc_now


PROMOTION_STATUSES = {"candidate", "rejected", "accepted", "superseded"}


@dataclass
class SkillWorkshopProposalResult:
    diagnostics: Diagnostics
    payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.diagnostics.has_errors


def create_skill_workshop_proposal_payload(
    *,
    title: str,
    evidence_files: Optional[list[Union[Path, str]]] = None,
    evidence_records: Optional[list[Dict[str, Any]]] = None,
    scope: Dict[str, Any],
    changes: list[Dict[str, Any]],
    evaluation_commands: list[str],
    out_dir: Union[Path, str] = Path(".agentmf/evolution/candidates"),
    timestamp: Optional[str] = None,
    promotion_status: str = "candidate",
    write: bool = False,
) -> SkillWorkshopProposalResult:
    diagnostics = Diagnostics()
    if promotion_status not in PROMOTION_STATUSES:
        diagnostics.error(
            "AMF222",
            f"unsupported proposal promotion status: {promotion_status}",
            "evo.proposal.promotion_status",
            f"use one of: {', '.join(sorted(PROMOTION_STATUSES))}",
        )
        return SkillWorkshopProposalResult(diagnostics)

    if evidence_records is None:
        evidence_records = _load_evidence_records(evidence_files or [], diagnostics)
        if diagnostics.has_errors:
            return SkillWorkshopProposalResult(diagnostics)

    evidence_refs = [_evidence_ref(record) for record in evidence_records]
    created_at = timestamp or _utc_now()
    proposal_core = {
        "title": title,
        "scope": _normalize_scope(scope),
        "evidence": evidence_refs,
        "changes": changes,
        "evaluation": {
            "commands": evaluation_commands,
            "status": "not_run",
        },
        "promotion": {
            "status": promotion_status,
            "requires_review": promotion_status == "candidate",
        },
    }
    proposal_id = "amf-evo-" + _sha256_json(proposal_core).split(":", 1)[1][:12]
    proposal = {
        "version": 1,
        "proposal_id": proposal_id,
        "created_at": created_at,
        **proposal_core,
    }
    markdown = render_skill_workshop_proposal_markdown(proposal)

    destination = Path(out_dir)
    proposal_path = destination / f"{proposal_id}.proposal.json"
    report_path = destination / f"{proposal_id}.md"
    if write:
        try:
            destination.mkdir(parents=True, exist_ok=True)
            proposal_path.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            report_path.write_text(markdown, encoding="utf-8")
        except OSError as exc:
            diagnostics.error(
                "AMF224",
                f"could not write Skill Workshop proposal under {destination}",
                "evo.proposal.out_dir",
                str(exc),
            )
            return SkillWorkshopProposalResult(diagnostics)

    return SkillWorkshopProposalResult(
        diagnostics,
        {
            "version": 1,
            "mode": "skill_workshop_proposal",
            "wrote": write,
            "proposal": proposal,
            "markdown": None if write else markdown,
            "paths": {
                "proposal_json": str(proposal_path),
                "markdown_report": str(report_path),
            },
        },
    )


def render_skill_workshop_proposal_markdown(proposal: Dict[str, Any]) -> str:
    lines = [
        f"# {proposal['title']}",
        "",
        f"- Proposal ID: `{proposal['proposal_id']}`",
        f"- Status: `{proposal['promotion']['status']}`",
        f"- Requires review: `{str(proposal['promotion']['requires_review']).lower()}`",
        f"- Created: `{proposal['created_at']}`",
        "",
        "## Scope",
        "",
    ]
    modules = proposal["scope"].get("modules", [])
    targets = proposal["scope"].get("targets", [])
    if modules:
        lines.extend(f"- Module: `{module}`" for module in modules)
    if targets:
        lines.extend(f"- Target: `{target}`" for target in targets)
    if not modules and not targets:
        lines.append("- Scope: unspecified")

    lines.extend(["", "## Evidence", ""])
    if proposal["evidence"]:
        for evidence in proposal["evidence"]:
            lines.append(
                f"- `{evidence['event_id']}` from `{evidence.get('source', 'unknown')}`: "
                f"{evidence['reason']}"
            )
    else:
        lines.append("- No evidence records attached.")

    lines.extend(["", "## Changes", ""])
    if proposal["changes"]:
        for change in proposal["changes"]:
            lines.append("```json")
            lines.append(json.dumps(change, indent=2, sort_keys=True))
            lines.append("```")
    else:
        lines.append("- No changes declared.")

    lines.extend(["", "## Evaluation", ""])
    commands = proposal["evaluation"]["commands"]
    if commands:
        lines.extend(f"- [ ] `{command}`" for command in commands)
    else:
        lines.append("- No evaluation commands declared.")
    lines.append(f"- Status: `{proposal['evaluation']['status']}`")
    lines.extend(["", "## Promotion", ""])
    lines.append(f"- Status: `{proposal['promotion']['status']}`")
    lines.append(f"- Requires review: `{str(proposal['promotion']['requires_review']).lower()}`")
    return "\n".join(lines) + "\n"


def _normalize_scope(scope: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "modules": [str(module) for module in scope.get("modules", [])],
        "targets": [str(target) for target in scope.get("targets", [])],
    }


def _load_proposal(proposal_file: Union[Path, str], diagnostics: Diagnostics) -> Optional[Dict[str, Any]]:
    path = Path(proposal_file)
    try:
        proposal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        diagnostics.error("AMF225", f"could not read proposal file: {path}", "evo.proposal_file", str(exc))
        return None
    if not isinstance(proposal, dict):
        diagnostics.error("AMF225", f"proposal file must contain a JSON object: {path}", "evo.proposal_file")
        return None
    return proposal
