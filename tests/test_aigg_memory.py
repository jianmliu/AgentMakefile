"""Tests for the domain-agnostic agent-memory kernel (aigg_memory).

The kernel must hold an agent-memory loop (evidence -> dream -> patch -> evaluate
-> promote) with ZERO dependency on agentmf. We prove it with a minimal markdown
notebook domain (a MEMORY.md-style store), which doubles as the canonical
"agent memory" use of the extracted machinery.
"""
from collections import Counter
from pathlib import Path

import aigg_memory as am


def _markdown_memory_domain() -> "am.Domain":
    """A minimal agent-memory domain: facts are markdown bullets in a document."""

    def add_fact(document: str, change: dict) -> str:
        fact = change["fact"].strip()
        bullets = {ln.strip() for ln in document.splitlines()}
        if f"- {fact}" in bullets:
            return document  # idempotent
        return document.rstrip("\n") + f"\n- {fact}\n"

    def dedupe(document: str, change: dict) -> str:
        seen: set = set()
        out = []
        for ln in document.splitlines():
            key = ln.strip()
            if key.startswith("- "):
                if key in seen:
                    continue
                seen.add(key)
            out.append(ln)
        return "\n".join(out) + "\n"

    def promote_repeated(records) -> list:
        counts = Counter(
            r.summary.get("fact")
            for r in records
            if r.source == "observation" and r.summary.get("fact")
        )
        proposals = []
        for fact, n in sorted(counts.items()):
            if n >= 2:
                proposals.append(
                    am.Proposal(
                        proposal_id=am.fingerprint(fact)[:12],
                        title=f"remember: {fact}",
                        changes=[{"type": "add_fact", "fact": fact}],
                        evidence_refs=[],
                        scope={"document": "MEMORY.md"},
                        created_at="t",
                    )
                )
        return proposals

    def no_duplicate_facts(before: str, after: str, proposal) -> "am.GateResult":
        bullets = [l.strip() for l in after.splitlines() if l.strip().startswith("- ")]
        return am.GateResult(name="no_duplicate_facts", passed=len(bullets) == len(set(bullets)))

    return am.Domain(
        name="markdown-memory",
        summarizers={"observation": lambda p: {"fact": p.get("fact")}},
        appliers={"add_fact": add_fact, "dedupe": dedupe},
        gates=[no_duplicate_facts],
        detectors=[promote_repeated],
    )


def test_kernel_has_zero_agentmf_dependency() -> None:
    """The isolation invariant: no aigg_memory source file may import agentmf."""
    pkg_dir = Path(am.__file__).parent
    offenders = []
    for path in pkg_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import agentmf" in text or "from agentmf" in text:
            offenders.append(path.name)
    assert not offenders, f"aigg_memory must not import agentmf, found in: {offenders}"


def test_markdown_memory_consolidation_loop(tmp_path: Path) -> None:
    domain = _markdown_memory_domain()
    store = am.EvidenceStore(tmp_path / "evidence.jsonl", domain=domain)

    # observe the same fact twice (+ a secret-bearing payload), and a one-off
    store.record("observation", {"fact": "user prefers Chinese + English", "api_key": "sk-supersecret-value"}, timestamp="t1")
    store.record("observation", {"fact": "user prefers Chinese + English"}, timestamp="t2")
    store.record("observation", {"fact": "a one-off detail"}, timestamp="t3")

    records = store.load()
    assert len(records) == 3
    assert all(isinstance(r, am.EvidenceRecord) for r in records)

    # the store persists summary + hashes, never the raw secret
    raw = (tmp_path / "evidence.jsonl").read_text()
    assert "sk-supersecret-value" not in raw

    # Dream: only the fact observed >= 2 times is promoted
    proposals = am.run_dream(domain, records)
    titles = [p.title for p in proposals]
    assert any("user prefers Chinese + English" in t for t in titles)
    assert not any("one-off" in t for t in titles)

    # Patch: apply the proposal to an empty memory document
    memory = "# MEMORY\n"
    prop = proposals[0]
    patch = am.generate_patch(domain, prop, memory)
    assert not patch.diagnostics.has_errors
    assert patch.applied == ["add_fact"]
    assert "user prefers Chinese + English" in patch.new_text
    assert patch.diff  # a unified diff was rendered

    # Evaluate: the gate passes
    gates = am.evaluate(domain, memory, patch.new_text, prop)
    assert gates and all(g.passed for g in gates)

    # Promote: commit to the store
    target = tmp_path / "MEMORY.md"
    am.promote(target, patch.new_text)
    assert "user prefers Chinese + English" in target.read_text()

    # Idempotent: re-applying does not duplicate the fact
    patch2 = am.generate_patch(domain, prop, patch.new_text)
    assert patch2.new_text.count("user prefers Chinese + English") == 1


def test_unknown_change_type_warns_without_crashing() -> None:
    domain = am.Domain(name="empty")
    prop = am.Proposal(
        proposal_id="x", title="t", changes=[{"type": "nonexistent"}],
        evidence_refs=[], scope={}, created_at="t",
    )
    patch = am.generate_patch(domain, prop, "some document")
    assert patch.applied == []
    assert patch.new_text == "some document"  # untouched
    assert patch.diagnostics.has_errors is False  # a warning, not a hard error
    codes = [d["code"] for d in patch.diagnostics.to_list()]
    assert "AM_UNSUPPORTED_CHANGE" in codes


def test_append_and_read_jsonl_with_injectable_serializer(tmp_path: Path) -> None:
    """The persistence primitives: append_jsonl + read_jsonl, with a serializer
    knob so a consumer (AgentMakefile) can reproduce a legacy line format."""
    import json

    path = tmp_path / "evidence.jsonl"
    records = [{"z": 3, "a": 1, "u": "汉字"}, {"event_id": "sha256:x", "n": 2}]
    compact = lambda r: json.dumps(r, sort_keys=True, separators=(",", ":"))
    for record in records:
        am.append_jsonl(path, record, serialize=compact)

    # the serializer is honored verbatim (compact + sorted, no spaces)
    first_line = path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line == compact(records[0])
    assert ", " not in first_line and '": ' not in first_line  # compact separators
    # round-trips back to the same dicts
    assert am.read_jsonl(path) == records
    # missing file -> empty, not an error
    assert am.read_jsonl(tmp_path / "absent.jsonl") == []


def test_redact_secrets_masks_keys_and_token_values() -> None:
    cleaned = am.redact_secrets({"token": "abc", "note": "bearer sk-deadbeefdeadbeef end", "n": 3})
    assert cleaned["token"] != "abc"           # secret-looking key masked
    assert "sk-deadbeefdeadbeef" not in cleaned["note"]  # token-looking value masked
    assert cleaned["n"] == 3                    # ordinary values preserved


# --- M1: the Workspace abstraction (multi-file patches) -------------------

def _file_domain() -> "am.Domain":
    """A minimal multi-file domain: changes create/edit/delete files in a
    workspace (path -> content)."""

    def write_file(workspace, change):
        ws = dict(workspace)
        ws[change["path"]] = change["content"]
        return ws

    def append_line(workspace, change):
        ws = dict(workspace)
        ws[change["path"]] = ws.get(change["path"], "") + change["line"] + "\n"
        return ws

    def delete_file(workspace, change):
        ws = dict(workspace)
        ws.pop(change["path"], None)
        return ws

    def no_empty_files(before, after, proposal):
        empties = [p for p, c in after.items() if c == ""]
        return am.GateResult("no_empty_files", len(empties) == 0)

    return am.Domain(
        name="files",
        appliers={"write_file": write_file, "append_line": append_line, "delete_file": delete_file},
        gates=[no_empty_files],
    )


def test_workspace_patch_multifile() -> None:
    domain = _file_domain()
    ws0 = {"a.md": "hello\n"}
    proposal = am.Proposal("p", "multi-file", [
        {"type": "write_file", "path": "b.md", "content": "new\n"},
        {"type": "append_line", "path": "a.md", "line": "world"},
        {"type": "delete_file", "path": "gone.md"},  # absent -> no-op (still 'applied')
    ])
    patch = am.generate_workspace_patch(domain, proposal, ws0)

    assert not patch.diagnostics.has_errors
    assert patch.applied == ["write_file", "append_line", "delete_file"]
    assert patch.new_workspace["b.md"] == "new\n"           # created
    assert patch.new_workspace["a.md"] == "hello\nworld\n"   # edited
    # per-file diffs only for files that actually changed, git-style headers
    assert set(patch.diffs) == {"a.md", "b.md"}
    assert "b/b.md" in patch.diffs["b.md"]
    # the caller's workspace is not mutated
    assert ws0 == {"a.md": "hello\n"}

    gates = am.evaluate_workspace(domain, ws0, patch.new_workspace, proposal)
    assert gates and all(g.passed for g in gates)


def test_workspace_diff_marks_created_and_deleted_files() -> None:
    domain = _file_domain()
    before = {"keep.md": "x\n", "drop.md": "bye\n"}
    proposal = am.Proposal("p", "t", [
        {"type": "write_file", "path": "fresh.md", "content": "hi\n"},
        {"type": "delete_file", "path": "drop.md"},
    ])
    patch = am.generate_workspace_patch(domain, proposal, before)
    assert "fresh.md" not in before and patch.new_workspace["fresh.md"] == "hi\n"
    assert "drop.md" not in patch.new_workspace
    assert set(patch.diffs) == {"fresh.md", "drop.md"}      # keep.md unchanged -> no diff


def test_single_document_is_a_one_entry_workspace() -> None:
    """Backward-compat: a single-document applier lifted into a one-entry
    workspace reproduces generate_patch's content — document == 1-entry workspace."""
    def add_line(document, change):
        return document.rstrip("\n") + "\n- " + change["text"] + "\n"

    proposal = am.Proposal("p", "t", [{"type": "add", "text": "x"}])
    p_doc = am.generate_patch(am.Domain(name="d", appliers={"add": add_line}), proposal, "# Doc\n")

    ws_domain = am.Domain(name="d", appliers={"add": am.lift_document_applier("DOC", add_line)})
    p_ws = am.generate_workspace_patch(ws_domain, proposal, {"DOC": "# Doc\n"})

    assert p_ws.new_workspace["DOC"] == p_doc.new_text   # identical content
    assert p_ws.applied == p_doc.applied


def test_workspace_unknown_change_warns_without_crashing() -> None:
    patch = am.generate_workspace_patch(am.Domain(name="empty"), am.Proposal("x", "t", [{"type": "nope"}]), {"a": "1"})
    assert patch.applied == []
    assert patch.new_workspace == {"a": "1"}               # untouched
    assert patch.diagnostics.has_errors is False           # warning, not error
    assert "AM_UNSUPPORTED_CHANGE" in [d["code"] for d in patch.diagnostics.to_list()]
