"""The markdown notebook domain — a real, usable agent-memory tool over the
kernel, matching the MEMORY.md index format and the consolidate-memory
operations (promote, merge duplicates, fix stale, prune). Zero agentmf import.
"""
from pathlib import Path

import agentmemory as am
from agentmemory import markdown as md

SAMPLE = """# Memory

- [Project name decision](project_name_decision.md) — AgentMakefile kept after a rename review.
- [Skill corpus](skill_corpus.md) — tiered SKILL.md corpus on the T7 drive.
"""


def _store(tmp_path, records):
    store = am.EvidenceStore(tmp_path / "evidence.jsonl", domain=md.markdown_memory_domain())
    for source, payload, outcome in records:
        store.record(source, payload, outcome=outcome)
    return store


def test_parse_and_render_roundtrip() -> None:
    entries = md.parse_entries(SAMPLE)
    assert [e.slug for e in entries] == ["project_name_decision.md", "skill_corpus.md"]
    assert entries[0].title == "Project name decision"
    assert "rename review" in entries[0].summary
    # render is the inverse for a parsed entry
    assert md.parse_entry(md.render_entry(entries[0])) == entries[0]


def test_consolidate_promotes_repeated_observation() -> None:
    domain = md.markdown_memory_domain()
    obs = {"title": "Budget protocol", "slug": "budget_protocol.md", "summary": "token_budget header contract landed."}
    records = [
        am.EvidenceRecord(1, "t1", "observation", "f", obs, None, "h", "e1"),
        am.EvidenceRecord(1, "t2", "observation", "f", obs, None, "h", "e2"),
        am.EvidenceRecord(1, "t3", "observation", "f", {"title": "One off", "slug": "one_off.md", "summary": "seen once"}, None, "h", "e3"),
    ]
    result = md.consolidate(SAMPLE, records, domain=domain)
    assert "budget_protocol.md" in result.new_text          # seen >= 2 -> promoted
    assert "one_off.md" not in result.new_text               # seen once -> not promoted
    assert all(g.passed for g in result.gates)
    # the new entry is well-formed and parseable
    slugs = [e.slug for e in md.parse_entries(result.new_text)]
    assert slugs.count("budget_protocol.md") == 1


def test_consolidate_merges_duplicate_index_entries() -> None:
    dupes = SAMPLE + "- [Skill corpus dup](skill_corpus.md) — a fuller note about the tiered corpus and its security gate.\n"
    pre = [e.slug for e in md.parse_entries(dupes)]
    assert pre.count("skill_corpus.md") == 2                  # duplicate slug present
    result = md.consolidate(dupes, [], domain=md.markdown_memory_domain())
    post = [e.slug for e in md.parse_entries(result.new_text)]
    assert post.count("skill_corpus.md") == 1                 # merged to one
    # merge keeps the richer (longer) summary
    merged = next(e for e in md.parse_entries(result.new_text) if e.slug == "skill_corpus.md")
    assert "security gate" in merged.summary
    assert all(g.passed for g in result.gates)


def test_consolidate_updates_stale_summary() -> None:
    correction = {"slug": "project_name_decision.md", "summary": "Renamed to AgentMakefile-NG on 2026-06."}
    records = [am.EvidenceRecord(1, "t", "observation", "f", correction, "correction", "h", "e1")]
    result = md.consolidate(SAMPLE, records, domain=md.markdown_memory_domain())
    entry = next(e for e in md.parse_entries(result.new_text) if e.slug == "project_name_decision.md")
    assert "AgentMakefile-NG" in entry.summary                # stale fact updated
    assert [e.slug for e in md.parse_entries(result.new_text)].count("project_name_decision.md") == 1


def test_consolidate_prunes_obsolete_entry() -> None:
    records = [am.EvidenceRecord(1, "t", "observation", "f", {"slug": "skill_corpus.md"}, "obsolete", "h", "e1")]
    result = md.consolidate(SAMPLE, records, domain=md.markdown_memory_domain())
    assert "skill_corpus.md" not in result.new_text           # obsolete entry removed
    assert "project_name_decision.md" in result.new_text      # the other survives


def test_gate_flags_malformed_bullet() -> None:
    domain = md.markdown_memory_domain()
    bad = SAMPLE + "- this is a stray bullet with no link\n"
    gates = am.evaluate(domain, SAMPLE, bad, am.Proposal("x", "x", [], [], {}, ""))
    well_formed = next(g for g in gates if g.name == "well_formed_index")
    assert well_formed.passed is False


def test_cli_consolidate_writes_when_gates_pass(tmp_path: Path) -> None:
    from agentmemory import cli

    memory = tmp_path / "MEMORY.md"
    memory.write_text(SAMPLE, encoding="utf-8")
    store = _store(tmp_path, [
        ("observation", {"title": "Budget protocol", "slug": "budget_protocol.md", "summary": "landed"}, None),
        ("observation", {"title": "Budget protocol", "slug": "budget_protocol.md", "summary": "landed"}, None),
    ])
    out = cli.consolidate_command(str(memory), str(store.path), write=True)
    assert out["gates_ok"] is True
    assert out["written"] is True
    assert "budget_protocol.md" in memory.read_text()         # persisted to disk

    # dry-run (no write) leaves the file untouched
    memory.write_text(SAMPLE, encoding="utf-8")
    out2 = cli.consolidate_command(str(memory), str(store.path), write=False)
    assert out2["written"] is False
    assert "budget_protocol.md" not in memory.read_text()
    assert "budget_protocol.md" in out2["new_text"]           # but the proposal is shown
