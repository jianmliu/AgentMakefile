# Memory-as-Skills — structured memory units routed by AgentMakefile

Status: design (for review). Date: 2026-06-04.

## Decisions (recorded)

1. **Memory units ride on AgentMakefile skills.** A memory note is a SKILL.md-shaped
   unit; AgentMakefile's `skills scan` / matcher / compile do the **routing and
   compilation** for free. `aigg-memory` owns only the **write/consolidation**
   path (evidence → which unit to add/update/merge/archive).
2. **Spec first**, then implement.

## Vision

Today `MEMORY.md` is a flat bullet index. We replace it with a **corpus of
self-describing memory units**, each shaped like a SKILL.md:

```
memory/
  budget_protocol/SKILL.md
  skill_corpus/SKILL.md
  project_name_decision/SKILL.md
MemoryMakefile          # generated: `agentmf skills scan memory/`
MEMORY.md               # generated: a compiled flat index (for Claude auto-memory)
```

A memory unit is "a skill that describes a durable fact/experience instead of a
procedure." Because it is SKILL.md-shaped, AgentMakefile already knows how to
index it, route it by relevance, and compile it into N consumable forms.

## Division of responsibility

| path | owner | mechanism |
| --- | --- | --- |
| **write / consolidate** | `aigg-memory` | evidence store + `skill_memory` domain (appliers/detectors/gates) → create/update/merge/archive units |
| **index** | AgentMakefile | `agentmf skills scan memory/ → MemoryMakefile` (`module_type: skill-index`) |
| **route / select** | AgentMakefile | matcher (keyword / embedding / hybrid) over `match` terms → task-scoped memory set |
| **compile** | AgentMakefile | one source → flat `MEMORY.md`, a task-scoped context bundle, an embedding index |

`aigg-memory` stays zero-`agentmf`; AgentMakefile depends on `aigg-memory` (the
existing edge), not the reverse. The two meet at the `memory/*/SKILL.md` files on
disk — a file contract, not an import.

## Memory unit format (SKILL.md-shaped)

`memory/<slug>/SKILL.md`:

```markdown
---
# --- read by AgentMakefile's skill scanner today ---
name: budget_protocol
description: token_budget pre-call contract landed in SKILL.md frontmatter
# --- routing (see "scanner enhancement" below) ---
match:
  user_intent: [token budget, cost contract, mcp budget extension]
# --- managed by aigg-memory (carried through; ignored by the scanner today) ---
id: budget_protocol
tags: [mcp, cost, protocol]
confidence: high            # high | medium | low
observations: 3             # times seen in evidence
source_events: [sha256:e1, sha256:e2]   # provenance → aigg-memory evidence store
created: 2026-05-27
updated: 2026-06-04
supersedes: []              # lifecycle
status: active              # active | stale | archived
---

token_budget pre-call contract landed in SKILL.md frontmatter (metadata.cost.tokens);
MCP metadata extension is the future inbound channel… (the durable note body)
```

Field mapping:

| SKILL.md (today) | memory unit | role |
| --- | --- | --- |
| `name` | `name` / `id` | identity |
| `description` | `description` | the one-line summary (what `MEMORY.md` shows today) |
| body | body | the durable fact/experience |
| *(derived)* `match_terms` | `match.user_intent` | **when to recall this memory** |
| — | `confidence`, `observations`, `source_events` | consolidation metadata |
| — | `supersedes`, `status` | lifecycle |

### Scanner enhancement (one small change)

`scan_skill_dirs` currently derives `match_terms` from name/description/body only;
it does not read an explicit `match.user_intent`. For precise memory routing,
teach `_read_skill` to **merge an explicit `match.user_intent` from frontmatter**
(when present) into the derived terms. This is additive and benefits real skills
too. Everything else (the skills-index module, matcher, compile) works unchanged.

## Read path (AgentMakefile, reused as-is)

- `agentmf skills scan memory/` → `MemoryMakefile` (a `skill-index` module whose
  `skills:` entries are the memory units).
- `agentmf select --request "<task>"` (or `serve POST /select`) → the **task-scoped
  set of relevant memories**, ranked by the matcher. This is the cold-start killer:
  load only the memories that matter for the current task instead of the whole file.
- `agentmf compile` → emit the consumable forms: a flat `MEMORY.md` (claude-md /
  claude-skill backends), per-host skill files, or an embedding index.

## Write path (`aigg-memory`, new `skill_memory` domain)

A new domain whose **changes operate on multiple files** (the unit dir + the
manifest), unlike the Phase-3 single-document markdown domain:

- **appliers**: `add_unit` (write `memory/<slug>/SKILL.md` with frontmatter+body),
  `update_unit` (edit body / bump `updated` / merge `source_events`),
  `merge_units` (fold duplicates, union `match`, keep richest body, set
  `supersedes`), `archive_unit` (`status: archived`, optionally move out).
- **detectors** (evidence → proposals): promote a fact observed ≥N times into a new
  unit; `correction` → `update_unit`; `obsolete` → `archive_unit`; duplicate
  detection across units → `merge_units`.
- **gates**: frontmatter parses; `name`/`description` present; body non-empty;
  unique `id` across the corpus; at least one `match.user_intent` term.

### Kernel evolution required: a `Workspace` abstraction

The Phase-3 kernel patches a single in-memory **document string**. Memory units are
**multi-file** (manifest + N unit files) — the same shape that kept AMF's patch
dispatch AMF-side at the Phase 2c boundary. To let multi-file memory flow through
the kernel, generalize the patch model:

```
document: str            →   workspace: dict[path -> content]
applier(doc, change)->doc →  applier(workspace, change) -> workspace
generate_patch(... , document)  →  generate_patch(..., workspace)  # per-file diffs
```

`generate_patch`/`evaluate` operate over the workspace; a single-document is just a
one-entry workspace, so Phase 3 stays backward-compatible. This same abstraction
would later let AMF's YAML patch appliers flow through the kernel too — the deep
unification deferred at Phase 2c.

## Provenance & lifecycle loop

- `source_events` link each unit back to the `aigg-memory` evidence store
  (`sha256:` event ids) — every remembered fact is traceable to the observations
  that produced it.
- Consolidation (the "dream") maintains `confidence` (rises with `observations`,
  falls when contradicted), `updated`, `supersedes`, and `status`. A `correction`
  bumps the body + `updated`; repeated corroboration raises `confidence`; an
  `obsolete` signal flips `status: archived` rather than hard-deleting (auditable).

## Staged plan

| phase | scope |
| --- | --- |
| **M1** | `Workspace` abstraction in the kernel (generalize `generate_patch`/`evaluate`; one-entry = today). Backward-compatible; Phase-3 tests stay green. |
| **M2** | `skill_memory` domain: frontmatter parse/render, multi-file appliers, gates, evidence detectors. TDD end-to-end on a `memory/` corpus. |
| **M3** | Scanner enhancement: honor explicit `match.user_intent`. Wire `agentmf skills scan memory/` → route → compile to `MEMORY.md`. |
| **M4** | `aigg-memory consolidate` writes units (not just the flat index); `select` returns task-scoped memory bundles. |

## Open questions

- **Unit granularity**: one fact per unit, or a unit per topic with multiple facts?
  (Skill-shaped favors one coherent note per unit.)
- **Manifest source of truth**: is `MemoryMakefile` generated (scan) or hand-authored
  and `MEMORY.md` generated from it? (Lean: units are the source; both manifest and
  `MEMORY.md` are compiled artifacts.)
- **Embedding routing**: reuse AgentMakefile's `embedding`/`hybrid` matcher for
  memory recall — same cost-aware build-time/run-time split as the skill corpus.

## Out of scope (this spec)

- Cross-device sync / multi-user memory.
- Automatic contradiction detection beyond explicit `correction`/`obsolete` signals.
- Lifting `aigg-memory` to its own repo (the separate Phase 4 task).
