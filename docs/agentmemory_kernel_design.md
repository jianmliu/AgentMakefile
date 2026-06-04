# `agentmemory` — a domain-agnostic agent-memory kernel

Status: design + Phase 1 landed. Date: 2026-06-04.

## Why

AgentMakefile's `evolution` + `dream` subsystems are, structurally, an
**agent-memory loop**:

```
evidence (observations)  →  proposal (candidate memory)  →  patch (memory edit)
        →  evaluate (validation gate)  →  promote (commit to the store)
        and  Dream = offline consolidation (replay evidence, merge, prune, detect)
```

Today that loop is welded to AgentMakefile specifics (YAML targets, `match.user_intent`
terms, the compiler, the selector). The coupling is small and concentrated —
`evidence/proposals/patches/curator` depend only on `Diagnostics` + each other;
`pipeline` depends on `loader/compiler/selector`; `dream` uses `matcher` in one
detector. The AgentMakefile-specific parts are the **patch appliers** and the
**dream detectors**.

`agentmemory` extracts the loop into a kernel with **zero `agentmf` dependency**,
where the domain-specific pieces are *plugins*. AgentMakefile becomes one domain
(routing-config memory); a markdown notebook (`MEMORY.md`-style) is another.

## Decisions (this extraction)

1. **Pluggable kernel.** The kernel owns the loop, the data model, the JSONL
   evidence store, hashing/redaction, and patch/gate/detector *dispatch*. A
   `Domain` supplies the behavior: `summarizers`, `appliers`, `gates`,
   `detectors`.
2. **AgentMakefile keeps working.** Its `evolution`/`dream` public API and tests
   stay green; it is migrated onto the kernel as a domain in a later phase (it
   becomes a *consumer*, not a fork).
3. **In-tree isolated package.** `src/agentmemory/` imports nothing from
   `agentmf`. Enforced by a test that scans the package source. Liftable to its
   own repo once stable.

## Kernel contract

The kernel deliberately operates on an **in-memory document string**, not files —
it does not know markdown from YAML. The caller maps documents ↔ files.

### Data model (`agentmemory.models`)

- `Diagnostic(severity, code, message, location?, hint?)` · `.to_dict()`
- `Diagnostics` — `.error()/.warning()`, `.has_errors`, `.to_list()`, `.extend()`
- `EvidenceRecord(version, timestamp, source, fingerprint, summary, outcome,
  payload_hash, event_id, refs)` · `.to_dict()/from_dict()`
- `Proposal(proposal_id, title, changes: list[dict], evidence_refs, scope, created_at)`
- `Change` is a plain dict with a `"type"` key (opaque to the kernel)
- `GateResult(name, passed, detail)`
- `Patch(new_text, diff, applied: list[str], diagnostics)`
- `Domain(name, summarizers={}, appliers={}, gates=[], detectors=[])`

### Plugin signatures (what a `Domain` provides)

| Slot | Signature | Role |
| --- | --- | --- |
| `summarizers[source]` | `(payload: dict) -> dict` | extract the durable summary stored in evidence |
| `appliers[change_type]` | `(document: str, change: dict) -> str` | apply one memory edit, return the new document |
| `gates[i]` | `(before: str, after: str, proposal) -> GateResult` | validation gate that can block promotion |
| `detectors[i]` | `(records: list[EvidenceRecord]) -> list[Proposal]` | offline consolidation (the "dream") |

### Loop API (`agentmemory`)

- `EvidenceStore(path, domain=None)` · `.record(source, payload, outcome=None,
  fingerprint=None, refs=None, timestamp=None) -> EvidenceRecord` · `.load() -> list`
  — append-only JSONL; stores **summary + hashes, never the raw payload**; runs
  redaction before hashing.
- `run_dream(domain, records) -> list[Proposal]` — runs every detector.
- `generate_patch(domain, proposal, document) -> Patch` — dispatches each change
  to its applier; unknown change types become **warnings, not crashes**; renders
  a unified diff.
- `evaluate(domain, before, after, proposal) -> list[GateResult]`.
- `promote(path, text) -> Path` — commit the consolidated document.
- helpers: `fingerprint(obj)`, `sha256_json(obj)`, `sha256_text(s)`, `redact_secrets(v)`.

## Mapping back to AgentMakefile (later phase)

| kernel slot | AgentMakefile domain plugin |
| --- | --- |
| `summarizers` | the 5 `EVIDENCE_SOURCES` summaries (`plugin_payload`, `benchmark`, …) |
| `appliers` | the 10 `SUPPORTED_PATCH_TYPES` (operating on YAML text) |
| `gates` | validate (`loader`) + compile (`compiler`) + selector-test (`selector`) |
| `detectors` | the 9 Dream detectors (routing gaps, term pruning, …) |

The existing `create_*_payload` functions become thin adapters that build the
AgentMakefile `Domain` and call the kernel — so the 16 evolution/dream tests and
the `evo` CLI keep passing unchanged.

## Out of scope (Phase 1)

- Migrating AgentMakefile onto the kernel (Phase 2).
- Embedding-based evidence retrieval; the kernel takes a flat record list today.
- A standalone repo / pyproject; that is the final lift, after the API settles.
