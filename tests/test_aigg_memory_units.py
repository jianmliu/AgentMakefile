"""The typed `memory` domain — SKILL.md-shaped units over the Workspace
abstraction. Units carry a `kind`; consolidation is kind-aware (procedural needs
review, semantic auto-activates). Zero agentmf import.
"""
import aigg_memory as am
from aigg_memory import memory as mem


def _obs(slug, name, kind, desc, match, body, event):
    return am.EvidenceRecord(
        1, "t", "observation", "f",
        {"slug": slug, "name": name, "kind": kind, "description": desc, "match": match, "body": body},
        None, "h", event,
    )


def test_unit_parse_render_roundtrip() -> None:
    unit = mem.MemoryUnit(
        {"name": "Budget protocol", "description": "token_budget 合约落地", "kind": "semantic",
         "match": {"user_intent": ["token budget", "cost contract"]}, "id": "budget_protocol",
         "confidence": "high", "status": "active"},
        "token_budget 预调用合约落地于 SKILL.md frontmatter。",
    )
    text = unit.to_text()
    assert text.startswith("---\n") and "\n---\n" in text
    back = mem.MemoryUnit.from_text(text)
    assert back.frontmatter == unit.frontmatter
    assert back.body == unit.body
    assert back.name == "Budget protocol" and back.kind == "semantic"
    assert back.match_terms == ["token budget", "cost contract"]
    assert "预调用合约" in text  # unicode preserved, not escaped


def test_consolidate_promotes_with_kind_aware_policy() -> None:
    records = [
        _obs("budget_protocol", "Budget protocol", "semantic", "token_budget contract landed",
             ["token budget", "cost contract"], "the durable note", "e1"),
        _obs("budget_protocol", "Budget protocol", "semantic", "token_budget contract landed",
             ["token budget", "cost contract"], "the durable note", "e2"),
        _obs("tdd_flow", "TDD flow", "procedural", "red-green-refactor",
             ["tdd", "test first"], "1. write failing test …", "e3"),
        _obs("tdd_flow", "TDD flow", "procedural", "red-green-refactor",
             ["tdd", "test first"], "1. write failing test …", "e4"),
        _obs("seen_once", "One off", "semantic", "only observed once", ["misc"], "x", "e5"),
    ]
    result = mem.consolidate({}, records)
    assert result.gates_ok
    ws = result.new_workspace

    assert "memory/budget_protocol/SKILL.md" in ws
    assert "memory/tdd_flow/SKILL.md" in ws
    assert "memory/seen_once/SKILL.md" not in ws          # observed once -> not promoted

    bp = mem.MemoryUnit.from_text(ws["memory/budget_protocol/SKILL.md"])
    assert bp.kind == "semantic" and bp.frontmatter["status"] == "active"   # semantic auto-activates
    assert set(bp.frontmatter["source_events"]) == {"e1", "e2"}             # provenance

    tdd = mem.MemoryUnit.from_text(ws["memory/tdd_flow/SKILL.md"])
    assert tdd.kind == "procedural" and tdd.frontmatter["status"] == "candidate"  # procedural needs review

    # multi-file patch: a per-file diff for each created unit
    assert set(result.patch.diffs) == {"memory/budget_protocol/SKILL.md", "memory/tdd_flow/SKILL.md"}


def test_consolidate_updates_and_archives_existing_units() -> None:
    existing = mem.MemoryUnit(
        {"name": "Skill corpus", "description": "tiered corpus on T7", "kind": "semantic",
         "match": {"user_intent": ["skill corpus"]}, "id": "skill_corpus",
         "source_events": ["e0"], "status": "active"},
        "old body",
    )
    other = mem.MemoryUnit(
        {"name": "Project name", "description": "kept AgentMakefile", "kind": "episodic",
         "match": {"user_intent": ["project name"]}, "id": "project_name", "status": "active"},
        "decision note",
    )
    ws0 = {
        "memory/skill_corpus/SKILL.md": existing.to_text(),
        "memory/project_name/SKILL.md": other.to_text(),
    }
    records = [
        am.EvidenceRecord(1, "t9", "observation", "f",
                          {"slug": "skill_corpus", "description": "248 skills, tier3 gated", "body": "new body"},
                          "correction", "h", "e9"),
        am.EvidenceRecord(1, "t10", "observation", "f", {"slug": "project_name"}, "obsolete", "h", "e10"),
    ]
    result = mem.consolidate(ws0, records)
    assert result.gates_ok

    updated = mem.MemoryUnit.from_text(result.new_workspace["memory/skill_corpus/SKILL.md"])
    assert "248 skills" in updated.frontmatter["description"]
    assert updated.body == "new body"
    assert set(updated.frontmatter["source_events"]) == {"e0", "e9"}        # merged provenance

    archived = mem.MemoryUnit.from_text(result.new_workspace["memory/project_name/SKILL.md"])
    assert archived.frontmatter["status"] == "archived"                      # obsolete -> archived (not deleted)
    assert set(result.patch.diffs) == {"memory/skill_corpus/SKILL.md", "memory/project_name/SKILL.md"}


def test_merge_units_applier_folds_duplicates() -> None:
    domain = mem.memory_domain()
    a = mem.MemoryUnit({"name": "A", "description": "short", "kind": "semantic",
                        "match": {"user_intent": ["x"]}, "id": "a", "status": "active"}, "short body")
    b = mem.MemoryUnit({"name": "B", "description": "fuller note", "kind": "semantic",
                        "match": {"user_intent": ["y"]}, "id": "b", "status": "active"}, "fuller body here")
    ws0 = {"memory/a/SKILL.md": a.to_text(), "memory/b/SKILL.md": b.to_text()}
    proposal = am.Proposal("p", "merge", [{
        "type": "merge_units",
        "slugs": ["a", "b"],
        "into": {"slug": "ab", "name": "AB", "description": "merged", "kind": "semantic",
                 "match": ["x", "y"], "body": "merged body", "supersedes": ["a", "b"]},
    }])
    patch = am.generate_workspace_patch(domain, proposal, ws0)
    assert "memory/a/SKILL.md" not in patch.new_workspace
    assert "memory/b/SKILL.md" not in patch.new_workspace
    merged = mem.MemoryUnit.from_text(patch.new_workspace["memory/ab/SKILL.md"])
    assert merged.match_terms == ["x", "y"] and merged.frontmatter["supersedes"] == ["a", "b"]


def test_gates_flag_bad_kind_and_missing_match() -> None:
    domain = mem.memory_domain()
    good = mem.MemoryUnit({"name": "G", "description": "d", "kind": "semantic",
                           "match": {"user_intent": ["t"]}, "id": "g"}, "body").to_text()
    bad_kind = mem.MemoryUnit({"name": "B", "description": "d", "kind": "nonsense",
                               "match": {"user_intent": ["t"]}, "id": "b"}, "body").to_text()
    no_match = mem.MemoryUnit({"name": "N", "description": "d", "kind": "semantic",
                               "match": {"user_intent": []}, "id": "n"}, "body").to_text()
    after = {"memory/g/SKILL.md": good, "memory/b/SKILL.md": bad_kind, "memory/n/SKILL.md": no_match}
    gates = {g.name: g for g in am.evaluate_workspace(domain, {}, after, am.Proposal("x", "x", []))}
    assert gates["kind_valid"].passed is False
    assert gates["has_match_terms"].passed is False
