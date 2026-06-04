"""The typed `memory` domain — SKILL.md-shaped units over the Workspace
abstraction. Units carry a `kind`; consolidation is kind-aware (procedural needs
review, semantic auto-activates). Zero agentmf import.
"""
from pathlib import Path

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


# --- M4: file-backed consolidation -----------------------------------------

def _two_obs(slug, kind, desc, match):
    return [
        _obs(slug, slug, kind, desc, match, "the body", "e1"),
        _obs(slug, slug, kind, desc, match, "the body", "e2"),
    ]


def test_consolidate_corpus_writes_units_to_disk(tmp_path: Path) -> None:
    records = _two_obs("budget_protocol", "semantic", "token_budget contract", ["token budget"])

    # dry-run writes nothing
    dry = mem.consolidate_corpus(tmp_path, records, write=False)
    assert dry.gates_ok and dry.written == []
    assert not (tmp_path / "memory" / "budget_protocol" / "SKILL.md").exists()

    # write persists the unit
    result = mem.consolidate_corpus(tmp_path, records, write=True)
    assert result.gates_ok
    assert result.written == ["memory/budget_protocol/SKILL.md"]
    unit_file = tmp_path / "memory" / "budget_protocol" / "SKILL.md"
    assert unit_file.exists()
    unit = mem.MemoryUnit.from_text(unit_file.read_text(encoding="utf-8"))
    assert unit.kind == "semantic" and unit.frontmatter["status"] == "active"


def test_consolidate_corpus_is_idempotent(tmp_path: Path) -> None:
    records = _two_obs("tdd_flow", "procedural", "red green refactor", ["tdd"])
    first = mem.consolidate_corpus(tmp_path, records, write=True)
    assert first.written == ["memory/tdd_flow/SKILL.md"]
    # the unit already exists -> add_unit is a no-op -> nothing rewritten
    again = mem.consolidate_corpus(tmp_path, records, write=True)
    assert again.written == [] and again.gates_ok


def test_consolidate_corpus_updates_existing_unit_on_disk(tmp_path: Path) -> None:
    mem.consolidate_corpus(tmp_path, _two_obs("skill_corpus", "semantic", "old", ["skill corpus"]), write=True)
    correction = [am.EvidenceRecord(1, "t9", "observation", "f",
                                    {"slug": "skill_corpus", "description": "248 skills tier3 gated", "body": "new body"},
                                    "correction", "h", "e9")]
    result = mem.consolidate_corpus(tmp_path, correction, write=True)
    assert result.written == ["memory/skill_corpus/SKILL.md"]
    unit = mem.MemoryUnit.from_text((tmp_path / "memory" / "skill_corpus" / "SKILL.md").read_text(encoding="utf-8"))
    assert "248 skills" in unit.frontmatter["description"] and unit.body == "new body"


def test_consolidation_status_tracks_pending_vs_absorbed(tmp_path: Path) -> None:
    """The readiness signal: evidence whose event_id is not yet folded into a
    unit's source_events is 'pending'. The engine reports; the app decides."""
    records = _two_obs("sage", "semantic", "wisdom of the blade", ["wise"])  # e1, e2

    st = mem.consolidation_status(tmp_path, records)
    assert st.total_evidence == 2 and st.consolidated_events == 0
    assert st.pending == 2 and st.recommended is True
    assert st.oldest_pending_timestamp == "t"

    # after consolidation those events are absorbed -> nothing pending
    mem.consolidate_corpus(tmp_path, records, write=True)
    done = mem.consolidation_status(tmp_path, records)
    assert done.pending == 0 and done.consolidated_events == 2 and done.recommended is False

    # a fresh observation is pending again
    records3 = records + [_obs("sage", "sage", "semantic", "wisdom of the blade", ["wise"], "body", "e3")]
    more = mem.consolidation_status(tmp_path, records3)
    assert more.pending == 1 and more.oldest_pending_timestamp == "t"
    # threshold is the app's policy knob; the engine only reports `recommended`
    assert mem.consolidation_status(tmp_path, records3, min_new=2).recommended is False


def test_obsolete_event_is_absorbed_into_source_events(tmp_path: Path) -> None:
    """An obsolete signal that archives a unit counts as consolidated (its
    event_id joins the unit's source_events), so it does not linger as pending."""
    mem.consolidate_corpus(tmp_path, _two_obs("relic", "semantic", "old relic", ["relic"]), write=True)
    obsolete = [am.EvidenceRecord(1, "t2", "observation", "f", {"slug": "relic"}, "obsolete", "h", "e9")]
    mem.consolidate_corpus(tmp_path, obsolete, write=True)
    unit = mem.MemoryUnit.from_text((tmp_path / "memory" / "relic" / "SKILL.md").read_text(encoding="utf-8"))
    assert unit.frontmatter["status"] == "archived"
    assert "e9" in unit.frontmatter["source_events"]
    assert mem.consolidation_status(tmp_path, obsolete).pending == 0


def test_cli_remember_and_consolidate_corpus(tmp_path: Path) -> None:
    from aigg_memory import cli

    evidence = tmp_path / "ev.jsonl"
    payload = {"slug": "budget_protocol", "name": "budget_protocol", "kind": "semantic",
               "description": "token_budget contract", "match": ["token budget"], "body": "note"}
    cli.remember_command(str(evidence), payload)
    cli.remember_command(str(evidence), payload)

    out = cli.consolidate_corpus_command(str(tmp_path), str(evidence), write=True)
    assert out["gates_ok"] is True
    assert "memory/budget_protocol/SKILL.md" in out["written"]
    assert (tmp_path / "memory" / "budget_protocol" / "SKILL.md").exists()
