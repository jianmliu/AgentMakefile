"""Tests for the /memory/* serve endpoints (typed agent-memory over aigg_memory.memory).

The tests use dispatch() directly (pure, no sockets) — the same pattern used
by existing serve tests in test_agentmf.py. All file I/O goes through tmp_path.

Endpoint contract verified:
  POST /memory/observe       — record one observation → evidence JSONL
  POST /memory/consolidate   — Dream consolidation → typed units (dry-run + write)
  POST /memory/select        — keyword retrieval over corpus units
  POST /memory/units         — list all units in a corpus
"""
from pathlib import Path

import pytest

from agentmf.serve import dispatch


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _observe(root: Path, evidence: str, payload: dict, outcome=None):
    body = {"evidence": evidence, "payload": payload}
    if outcome:
        body["outcome"] = outcome
    return dispatch("POST", "/memory/observe", body, root)


def _consolidate(root: Path, evidence: str, corpus: str = "memory", write: bool = False):
    return dispatch("POST", "/memory/consolidate",
                    {"evidence": evidence, "corpus": corpus, "write": write}, root)


def _select(root: Path, request: str, corpus: str = "memory", **kwargs):
    body = {"request": request, "corpus": corpus, **kwargs}
    return dispatch("POST", "/memory/select", body, root)


def _units(root: Path, corpus: str = "memory"):
    return dispatch("POST", "/memory/units", {"corpus": corpus}, root)


def _npc_payload(slug, name, kind="episodic", desc="", match=None, body=""):
    return {"slug": slug, "name": name, "kind": kind, "description": desc,
            "match": match or [slug], "body": body or desc}


# ---------------------------------------------------------------------------
# observe
# ---------------------------------------------------------------------------

class TestMemoryObserve:
    def test_observe_creates_evidence_jsonl(self, tmp_path):
        status, env = _observe(tmp_path, "evidence.jsonl",
                               _npc_payload("youxia", "游侠", desc="visitor who asked about swords"))
        assert status == 200 and env["ok"]
        rec = env["data"]
        assert rec["source"] == "observation"
        assert rec["event_id"]
        ev_file = tmp_path / "evidence.jsonl"
        assert ev_file.exists()
        lines = [l for l in ev_file.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_observe_multiple_appends(self, tmp_path):
        for _ in range(3):
            _observe(tmp_path, "ev.jsonl", _npc_payload("visitor", "过客", desc="curious traveller"))
        lines = [l for l in (tmp_path / "ev.jsonl").read_text().splitlines() if l.strip()]
        assert len(lines) == 3

    def test_observe_with_outcome_correction(self, tmp_path):
        status, env = _observe(tmp_path, "ev.jsonl",
                               _npc_payload("youxia", "游侠", desc="corrected summary"),
                               outcome="correction")
        assert status == 200
        assert env["data"]["outcome"] == "correction"

    def test_observe_missing_evidence_returns_400(self, tmp_path):
        status, env = dispatch("POST", "/memory/observe", {"payload": {}}, tmp_path)
        assert status == 400 and not env["ok"]

    def test_observe_missing_payload_returns_400(self, tmp_path):
        status, env = dispatch("POST", "/memory/observe", {"evidence": "ev.jsonl"}, tmp_path)
        assert status == 400 and not env["ok"]


# ---------------------------------------------------------------------------
# consolidate (dry-run + write)
# ---------------------------------------------------------------------------

class TestMemoryConsolidate:
    def _seed(self, tmp_path, n: int = 2):
        """Record n identical observations → should trigger promote detector."""
        for _ in range(n):
            _observe(tmp_path, "ev.jsonl",
                     _npc_payload("jiujianxian", "酒剑仙",
                                  kind="semantic",
                                  desc="嗜酒如命的剑道高人，醉中悟出绝世剑意",
                                  match=["swordsmanship", "sword spirit", "酒剑"]))

    def test_consolidate_dry_run_proposes_without_writing(self, tmp_path):
        self._seed(tmp_path)
        status, env = _consolidate(tmp_path, "ev.jsonl", write=False)
        assert status == 200 and env["ok"]
        data = env["data"]
        assert data["proposals"]  # at least one proposal
        assert not data["written"]
        # unit not on disk yet (dry-run)
        assert not (tmp_path / "memory" / "jiujianxian" / "SKILL.md").exists()

    def test_consolidate_write_creates_unit_file(self, tmp_path):
        self._seed(tmp_path)
        status, env = _consolidate(tmp_path, "ev.jsonl", write=True)
        assert status == 200 and env["ok"]
        data = env["data"]
        assert data["written"]
        unit_file = tmp_path / "memory" / "jiujianxian" / "SKILL.md"
        assert unit_file.exists()
        content = unit_file.read_text()
        assert "酒剑仙" in content
        assert "kind:" in content  # frontmatter present

    def test_consolidate_gates_ok_after_valid_promote(self, tmp_path):
        self._seed(tmp_path)
        _, env = _consolidate(tmp_path, "ev.jsonl", write=True)
        assert env["data"]["gates_ok"]
        gates = env["data"]["gates"]
        assert all(g["passed"] for g in gates)

    def test_consolidate_units_after_reflects_new_unit(self, tmp_path):
        self._seed(tmp_path)
        _, env = _consolidate(tmp_path, "ev.jsonl", write=True)
        summaries = env["data"]["units_after"]
        names = [u["name"] for u in summaries]
        assert "酒剑仙" in names

    def test_consolidate_single_observation_no_proposal(self, tmp_path):
        """One observation is below the min_count=2 threshold — no promotion."""
        _observe(tmp_path, "ev.jsonl",
                 _npc_payload("lonely", "孤客", kind="semantic", desc="only once"))
        _, env = _consolidate(tmp_path, "ev.jsonl", write=True)
        assert not env["data"]["proposals"]
        assert not (tmp_path / "memory" / "lonely" / "SKILL.md").exists()

    def test_consolidate_archives_on_obsolete_outcome(self, tmp_path):
        # First: write the unit (2 observations to promote)
        self._seed(tmp_path)
        _consolidate(tmp_path, "ev.jsonl", write=True)
        # Now mark it obsolete
        _observe(tmp_path, "ev.jsonl",
                 {"slug": "jiujianxian"}, outcome="obsolete")
        _, env = _consolidate(tmp_path, "ev.jsonl", write=True)
        units = env["data"]["units_after"]
        unit = next((u for u in units if u["name"] == "酒剑仙"), None)
        assert unit is not None
        assert unit["status"] == "archived"

    def test_consolidate_missing_evidence_returns_400(self, tmp_path):
        status, env = dispatch("POST", "/memory/consolidate", {"corpus": "memory"}, tmp_path)
        assert status == 400 and not env["ok"]

    def test_consolidate_idempotent(self, tmp_path):
        """Running consolidate twice produces no new proposals the second time."""
        self._seed(tmp_path)
        _consolidate(tmp_path, "ev.jsonl", write=True)
        _, env2 = _consolidate(tmp_path, "ev.jsonl", write=True)
        assert not env2["data"]["written"]  # second run: nothing changed


# ---------------------------------------------------------------------------
# select
# ---------------------------------------------------------------------------

class TestMemorySelect:
    def _plant_unit(self, tmp_path, slug, name, kind, desc, match_terms, body_text):
        """Write a unit file directly (bypassing consolidation) for fast fixtures."""
        import yaml
        fm = {"name": name, "description": desc, "kind": kind,
              "match": {"user_intent": match_terms},
              "id": slug, "status": "active", "confidence": "high", "observations": 3}
        fm_text = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).rstrip("\n")
        content = f"---\n{fm_text}\n---\n\n{body_text}\n"
        path = tmp_path / "memory" / slug / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_select_returns_matching_units(self, tmp_path):
        self._plant_unit(tmp_path, "jiujianxian", "酒剑仙", "semantic",
                         "swordsmanship master", ["swordsmanship", "sword"],
                         "醉中悟剑意")
        self._plant_unit(tmp_path, "tavern", "酒馆背景", "episodic",
                         "the tavern setting", ["tavern", "inn"],
                         "A bustling tavern on the west road.")
        status, env = _select(tmp_path, "teach me swordsmanship")
        assert status == 200 and env["ok"]
        units = env["data"]["units"]
        assert len(units) == 1
        assert units[0]["name"] == "酒剑仙"

    def test_select_bundle_rendered(self, tmp_path):
        self._plant_unit(tmp_path, "facts", "剑道事实", "semantic",
                         "sword wisdom", ["sword", "wisdom"], "Wisdom comes from practice.")
        _, env = _select(tmp_path, "sword wisdom")
        bundle = env["data"]["bundle"]
        assert "## Facts" in bundle or "Wisdom" in bundle  # kind-aware rendering

    def test_select_empty_corpus_returns_empty(self, tmp_path):
        status, env = _select(tmp_path, "anything")
        assert status == 200
        assert env["data"]["units"] == []

    def test_select_no_match_returns_empty(self, tmp_path):
        self._plant_unit(tmp_path, "jiujianxian", "酒剑仙", "semantic",
                         "master", ["swordsmanship"], "body")
        _, env = _select(tmp_path, "completely unrelated request about cooking")
        assert env["data"]["units"] == []

    def test_select_archived_units_excluded(self, tmp_path):
        import yaml
        fm = {"name": "老剑客", "description": "retired", "kind": "semantic",
              "match": {"user_intent": ["sword"]}, "id": "old", "status": "archived",
              "confidence": "low", "observations": 1}
        content = f"---\n{yaml.safe_dump(fm, allow_unicode=True)}---\n\nretired swordsman\n"
        p = tmp_path / "memory" / "old" / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        _, env = _select(tmp_path, "sword")
        assert env["data"]["units"] == []  # archived units not returned

    def test_select_kind_filter(self, tmp_path):
        self._plant_unit(tmp_path, "proc", "剑技", "procedural",
                         "sword technique", ["sword"], "Step 1: grip.")
        self._plant_unit(tmp_path, "fact", "剑理", "semantic",
                         "sword theory", ["sword"], "Theory of the blade.")
        _, env = _select(tmp_path, "sword", kinds=["semantic"])
        assert all(u["kind"] == "semantic" for u in env["data"]["units"])

    def test_select_n_best_limits_results(self, tmp_path):
        for i in range(5):
            self._plant_unit(tmp_path, f"unit{i}", f"Unit{i}", "semantic",
                             f"desc {i}", ["target"], f"body {i}")
        _, env = _select(tmp_path, "target", n_best=2)
        assert len(env["data"]["units"]) <= 2


# ---------------------------------------------------------------------------
# units list
# ---------------------------------------------------------------------------

class TestMemoryUnits:
    def test_units_empty_corpus(self, tmp_path):
        status, env = _units(tmp_path)
        assert status == 200 and env["ok"]
        assert env["data"]["units"] == []
        assert env["data"]["total"] == 0

    def test_units_lists_all_after_consolidation(self, tmp_path):
        # plant two units
        for slug, name in [("npc_a", "角色甲"), ("npc_b", "角色乙")]:
            for _ in range(2):
                _observe(tmp_path, "ev.jsonl",
                         _npc_payload(slug, name, kind="semantic",
                                      desc=f"{name} background",
                                      match=[slug, "character"]))
        _consolidate(tmp_path, "ev.jsonl", write=True)
        _, env = _units(tmp_path)
        names = {u["name"] for u in env["data"]["units"]}
        assert "角色甲" in names and "角色乙" in names
        assert env["data"]["total"] == 2

    def test_units_custom_corpus(self, tmp_path):
        """Custom corpus path is respected."""
        import yaml
        fm = {"name": "世界事实", "description": "world fact", "kind": "semantic",
              "match": {"user_intent": ["world"]}, "id": "world_fact",
              "status": "active", "confidence": "high", "observations": 2}
        p = tmp_path / "npcs" / "world_memory" / "world_fact" / "SKILL.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"---\n{yaml.safe_dump(fm, allow_unicode=True)}---\n\nworld body\n")
        _, env = _units(tmp_path, corpus="npcs/world_memory")
        assert any(u["name"] == "世界事实" for u in env["data"]["units"])


# ---------------------------------------------------------------------------
# end-to-end: observe → consolidate → select
# ---------------------------------------------------------------------------

class TestMemoryEndToEnd:
    def test_npc_memory_loop(self, tmp_path):
        """A visitor talks to an NPC twice → consolidated into a semantic unit
        → retrieved by a relevant request — the full online→offline→online cycle."""
        npc_corpus = "npcs/jiujianxian/memory"
        evidence = "npcs/jiujianxian/evidence.jsonl"
        payload = _npc_payload(
            "youxia_relation", "游侠好感",
            kind="semantic",
            desc="游侠对酒剑仙的好感度和互动历史",
            match=["游侠", "swordsmanship", "affinity", "relationship"],
            body="游侠初见面时好奇剑法，好感+8；再次对话论剑，好感+16。",
        )
        # online: two conversations recorded as evidence
        _observe(tmp_path, evidence, payload)
        _observe(tmp_path, evidence, payload)

        # offline: Dream consolidation → new typed unit written to corpus
        s, env = _consolidate(tmp_path, evidence, corpus=npc_corpus, write=True)
        assert env["data"]["written"], "consolidation should write the unit"
        assert (tmp_path / npc_corpus / "youxia_relation" / "SKILL.md").exists()

        # online: select relevant memory for the next conversation context
        s, env = _select(tmp_path, "游侠 swordsmanship", corpus=npc_corpus)
        assert env["ok"]
        units = env["data"]["units"]
        assert any(u["name"] == "游侠好感" for u in units), \
            f"retrieved units: {[u['name'] for u in units]}"
        # bundle contains the memory body
        assert "好感" in env["data"]["bundle"]
