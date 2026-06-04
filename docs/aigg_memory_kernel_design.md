# `aigg-memory` — a domain-agnostic agent-memory kernel

> Distribution / repo name: **`aigg-memory`**. Python import package:
> **`aigg_memory`** (a hyphen is not a valid module identifier).

Status: Phase 1 (kernel) + Phase 3 (markdown domain) + Phase 2a/2b/2c (AMF
primitive + persistence + dream-dispatch delegation) landed. Date: 2026-06-04.

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

`aigg_memory` extracts the loop into a kernel with **zero `agentmf` dependency**,
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
3. **In-tree isolated package.** `src/aigg_memory/` imports nothing from
   `agentmf`. Enforced by a test that scans the package source. **Phase 4
   (done):** extracted to a standalone `aigg-memory` repo — installs in a clean
   venv with only PyYAML, all tests pass, no `agentmf`. Publishing + the
   AgentMakefile cutover (depend on the package, drop the in-tree copy) are the
   remaining owner steps; until then the in-tree copy is the working source.

## Kernel contract

The kernel deliberately operates on an **in-memory document string**, not files —
it does not know markdown from YAML. The caller maps documents ↔ files.

### Data model (`aigg_memory.models`)

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

### Loop API (`aigg_memory`)

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
- **multi-file (Workspace) generalization** — a single document is the one-entry case:
  - `generate_workspace_patch(domain, proposal, workspace) -> WorkspacePatch` —
    appliers are `(workspace, change) -> workspace`; returns the new workspace +
    **per-file diffs** (only for changed files); same warn/error policy as
    `generate_patch`; the caller's workspace is not mutated.
  - `evaluate_workspace(domain, before_ws, after_ws, proposal) -> list[GateResult]`.
  - `lift_document_applier(path, applier)` — adapt a `(str, change) -> str` applier
    into a workspace applier editing one file (single document ≡ one-entry workspace).
- helpers: `fingerprint(obj)`, `sha256_json(obj)`, `sha256_text(s)`, `redact_secrets(v)`,
  `append_jsonl(path, record, *, serialize)`, `read_jsonl(path)`.

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

## Markdown notebook domain (Phase 3 — landed)

`aigg_memory.markdown` is a real, usable agent-memory tool over the kernel,
modelling the MEMORY.md index format (`- [Title](slug.md) — summary`) and the
consolidate-memory operations:

| operation | driven by | change type |
| --- | --- | --- |
| promote a repeatedly-observed fact into a new entry | evidence (≥N observations) | `add_entry` |
| fix a stale summary | evidence (`outcome=correction`) | `update_summary` |
| prune an obsolete entry | evidence (`outcome=obsolete`) | `prune_entry` |
| merge duplicate index entries (keep richest summary) | the document itself | `merge_entries` |

Gates: `unique_slugs`, `well_formed_index`. The orchestrator
`markdown.consolidate(memory_text, records) -> ConsolidationResult` runs the
whole loop purely (no file IO); the CLI adds the IO:

```
python -m aigg_memory observe     --evidence E.jsonl --json '{"title":..,"slug":..,"summary":..}' [--outcome correction|obsolete]
python -m aigg_memory consolidate --memory MEMORY.md --evidence E.jsonl [--write]   # writes back only when all gates pass
```

This is the cold-start-free path: point `observe` at things the agent learns,
`consolidate` folds them into MEMORY.md with validation, never overwriting on a
failed gate.

## AgentMakefile as a consumer (Phase 2 — staged)

Decision ② is "AgentMakefile keeps working, depends on the kernel". Executing it
revealed a hard constraint: AMF's evolution output is **byte-locked by 16 tests**
(`event_id` is `sha256:<hex>` of a compact, `ensure_ascii=True` JSON encoding;
the redaction mask is `[REDACTED]` with AMF's own secret predicates). The kernel
serializes differently by default. So migration must be **byte-identical, verified
green**, not a rewrite — otherwise it breaks AMF's tests.

**Phase 2a (landed).** The kernel primitives became *injectable* (a pluggable
kernel should be — decision ①):

- `sha256_json(obj, *, prefix, separators, ensure_ascii)`
- `sha256_text(text, *, prefix)`
- `redact_secrets(value, *, mask, secret_key, secret_value)`

`agentmf.evolution.evidence` now delegates `_sha256_json` / `_sha256_text` /
`_redact_secrets` to the kernel with AMF's policy injected — byte-identical
(proven across non-ASCII + secrets + the `hash(redact(payload))` chain, pinned by
`test_evolution_primitives_delegate_to_aigg_memory_kernel`). The whole evolution
package + dream route their hashing/redaction through these, so the dependency
edge `agentmf → aigg_memory` is real and the duplicated crypto/redaction layer is
gone. 347 tests pass.

**Phase 2b (landed).** The JSONL **persistence** primitives moved into the kernel:

- `append_jsonl(path, record, *, serialize=None)` — one record per line; the
  `serialize` knob reproduces a legacy line format byte-for-byte.
- `read_jsonl(path) -> list[dict]` — parse, skipping blanks.

The kernel's own `EvidenceStore` now persists through these, and
`agentmf.evolution.evidence` appends evidence through `append_jsonl` with its
compact `separators=(",", ":")` serializer — proven byte-identical to the legacy
write. AMF's *load* stays AMF-side on purpose: it emits per-line `AMF223`
diagnostics (file + line context) that are domain-specific error reporting, not
generic parsing. 348 tests pass.

**Phase 2c (landed) — dream dispatch.** AMF's 10 dream detectors share a uniform
signature and run in a fixed order, concatenating proposals — exactly the kernel's
`run_dream`. They are now bound as kernel detectors over the evidence files and
dispatched through `run_dream`; the dict shapes and order are preserved
byte-for-byte (the 14 dream tests, which assert exact proposals/order, all pass).
`run_dream` concatenates whatever its detectors return, so AMF's dict-shaped
proposals flow through unchanged — the kernel's dispatch did not need to know
AMF's proposal schema.

**Boundary: the patch dispatch stays AMF-side (by design, not as a TODO).**
AMF's patch appliers are multi-file YAML workspace mutations rendering per-file
diffs; the kernel's `generate_patch` is single in-memory-document → one diff.
Delegating would force the kernel to absorb AMF's YAML/multi-file/diff model —
architecturally backwards — or rewrite AMF's appliers and break the byte-locked
tests. This is the correct seam: **shared mechanism** (primitives, persistence,
dispatch loops) lives in the kernel; **domain semantics** (how a patch edits a
YAML target, what a diff looks like) stay in the domain. The kernel's
`generate_patch` is already exercised by the markdown domain (Phase 3), proving
the patch dispatch works for domains shaped to it.

Decision ② is therefore satisfied at the right boundary: AgentMakefile depends on
the kernel for hashing, redaction, persistence, and dream dispatch, while keeping
its byte-locked domain semantics.

## Out of scope (Phase 1)

- Migrating AgentMakefile onto the kernel (Phase 2).
- Embedding-based evidence retrieval; the kernel takes a flat record list today.
- A standalone repo / pyproject; that is the final lift, after the API settles.
