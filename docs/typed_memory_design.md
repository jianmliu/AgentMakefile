# Typed Long-Term Memory — one substrate; skills are procedural memory

Status: design (for review). Date: 2026-06-04.
Supersedes the earlier "memory-as-skills" framing (this file's history).

## The unifying idea

A **skill is a kind of memory.** In cognitive terms a long-term memory system has
distinct kinds, and they map cleanly onto what we already have:

| kind | answers | examples | content shape |
| --- | --- | --- | --- |
| **procedural** | *how to do X* | skills, workflows | structured & executable (steps, guards, `match`) |
| **semantic** | *what is true* | facts, preferences, decision rationale | informational body |
| **episodic** | *what happened* | events, decisions, sessions | narrative body |
| *(working)* | *current scratch* | task scratchpad | ephemeral, TTL'd |

All four are durable (except working), self-describing, retrieved by relevance, and
consolidated from experience. So this is **one typed substrate**, not "memory
bolted onto skills":

- `aigg-memory` is **the long-term-memory kernel**.
- AgentMakefile's existing **skill corpus is the `procedural` slice** of it.
- Memory notes are the `semantic` / `episodic` slices.

### The closed loop

`aigg-memory`'s `evidence → consolidate → promote` loop is *exactly* what
AgentMakefile's **evolution / dream** subsystem already does to skills. So the
evolution subsystem was always a **procedural-memory consolidation system**; we
extracted it as the kernel. The same loop now consolidates *every* kind — only the
policies differ. Evolution and memory-keeping are the same operation on different
kinds.

## Decisions (recorded)

1. **Everything-is-memory, typed.** One unit format with a `kind`; skills are
   `kind: procedural`. Same frontmatter, matcher, compile, and consolidation loop
   across kinds — differentiated by `kind`.
2. **Index/route is kind-agnostic; consume and consolidate are kind-aware.**
3. **Memory units ride on AgentMakefile skills** for the read side (scan / matcher
   / compile); `aigg-memory` owns the write/consolidation side.
4. **Spec first**, then implement.

## Where the kinds genuinely differ (not all identical)

| dimension | procedural (skill) | semantic / episodic (note) |
| --- | --- | --- |
| **authoring** | curated, high-investment, shared, stable | accreted, cheap, personal, noisy |
| **consolidation gate** | promotion needs review (human or strong evidence) | auto-consolidate at high confidence; `obsolete` archives |
| **content** | executable/structured — the runtime *acts on* steps/guards | informational — the body is *read*, not executed |
| **compile rendering** | actionable instruction (claude-skill, codex-skill, …) | a context line / fact / provenance note |

These are **per-kind policies over one substrate**, mirroring what the evolution
subsystem already does (skills get a review gate; notes get lighter gates).

## Unit format (SKILL.md-shaped, + `kind`)

`memory/<slug>/SKILL.md`:

```markdown
---
# --- read by AgentMakefile's skill scanner today ---
name: budget_protocol
description: token_budget pre-call contract landed in SKILL.md frontmatter
# --- the type of memory ---
kind: semantic                      # procedural | semantic | episodic | working
# --- routing (see "scanner enhancement") ---
match:
  user_intent: [token budget, cost contract, mcp budget extension]
# --- managed by aigg-memory (carried through; ignored by the scanner today) ---
id: budget_protocol
tags: [mcp, cost, protocol]
confidence: high                    # high | medium | low
observations: 3                     # times seen in evidence
source_events: [sha256:e1, sha256:e2]   # provenance → aigg-memory evidence store
created: 2026-05-27
updated: 2026-06-04
supersedes: []                      # lifecycle
status: active                      # active | stale | archived
---

token_budget pre-call contract landed in SKILL.md frontmatter (metadata.cost.tokens);
MCP metadata extension is the future inbound channel… (the durable note body)
```

A **procedural** unit is just the same file with `kind: procedural` and a body that
carries steps/guards — i.e. exactly today's SKILL.md. The metadata schema
(`confidence`, `observations`, `source_events`, `supersedes`, `status`) **subsumes
the evolution subsystem's promotion metadata**: a skill can be low-confidence,
observed-useful-N-times, superseded, or archived.

### Scanner enhancement (one small change)

`scan_skill_dirs` derives `match_terms` from name/description/body only. Teach
`_read_skill` to (a) **merge an explicit `match.user_intent`** from frontmatter and
(b) **carry `kind`** through to the IR. Additive; benefits real skills too.

## Division of responsibility

| path | owner | mechanism | kind-aware? |
| --- | --- | --- | --- |
| **write / consolidate** | `aigg-memory` | evidence store + memory domain (appliers/detectors/gates) | yes — per-kind gates/policies |
| **index** | AgentMakefile | `agentmf skills scan memory/ → MemoryMakefile` (`module_type: skill-index`) | no |
| **route / select** | AgentMakefile | matcher (keyword / embedding / hybrid) over `match` | no — relevance, any kind |
| **compile** | AgentMakefile | one source → N forms | yes — per-kind rendering |

`aigg-memory` stays zero-`agentmf`; AgentMakefile depends on `aigg-memory` (the
existing edge). The two meet at the `memory/*/SKILL.md` files — a file contract, not
an import.

## Read path (AgentMakefile, all kinds)

- `agentmf skills scan memory/` → `MemoryMakefile` whose `skills:` entries are the
  memory units (of any kind).
- `agentmf select --request "<task>"` (or `serve POST /select`) → the **task-scoped
  set of relevant memories**, ranked by the matcher, regardless of kind. Cold-start
  killer: load only what matters for the task.
- `agentmf compile` → **kind-aware rendering**: `procedural` → an actionable skill
  file; `semantic`/`episodic` → a flat `MEMORY.md` line / context bundle; plus an
  embedding index. One source → N forms, now also "per-kind form".

## Write path (`aigg-memory`, the memory domain)

A `memory` domain (kind-aware) whose **changes operate on multiple files** (the unit
dir + the manifest), unlike the Phase-3 single-document markdown domain:

- **appliers**: `add_unit`, `update_unit` (body / bump `updated` / merge
  `source_events`), `merge_units` (union `match`, keep richest body, set
  `supersedes`), `archive_unit` (`status: archived`).
- **detectors** (evidence → proposals): promote a fact observed ≥N times → `add_unit`;
  `correction` → `update_unit`; `obsolete` → `archive_unit`; cross-unit duplicates →
  `merge_units`. Procedural proposals carry a **review gate**; semantic ones may
  auto-promote at high confidence.
- **gates**: frontmatter parses; `name`/`description`/`kind` present; body non-empty;
  unique `id`; ≥1 `match.user_intent` term; **kind-specific**: procedural units pass
  a stricter "needs-review / structured-body" gate.

### Kernel evolution required: a `Workspace` abstraction

The Phase-3 kernel patches a single in-memory **document string**. Memory units are
**multi-file** — the same shape that kept AMF's patch dispatch AMF-side at the
Phase 2c boundary. Generalize the patch model:

```
document: str             →   workspace: dict[path -> content]
applier(doc, change)->doc →   applier(workspace, change) -> workspace
generate_patch(..., document) →  generate_patch(..., workspace)   # per-file diffs
```

A single-document is a one-entry workspace, so Phase 3 stays backward-compatible.
This same abstraction later lets AMF's YAML patch appliers flow through the kernel —
closing the deep unification deferred at Phase 2c.

## Provenance & lifecycle

- `source_events` link each unit (any kind) back to the `aigg-memory` evidence store
  — every remembered thing is traceable to the observations that produced it.
- Consolidation maintains `confidence` (rises with corroboration, falls when
  contradicted), `updated`, `supersedes`, `status`. `obsolete` → `status: archived`
  rather than hard-delete (auditable). Procedural units additionally track a
  promotion/review state (the evolution subsystem's existing concept, now a `kind`
  policy).

## Staged plan

| phase | scope |
| --- | --- |
| **M1** | `Workspace` abstraction in the kernel (generalize `generate_patch`/`evaluate`; one-entry = today). Backward-compatible; Phase-3 tests stay green. |
| **M2** | `memory` domain: frontmatter (+`kind`) parse/render, multi-file appliers, kind-aware gates, evidence detectors. TDD end-to-end on a `memory/` corpus with both `procedural` and `semantic` units. |
| **M3** | Scanner enhancement: honor explicit `match.user_intent` + carry `kind`. Wire `agentmf skills scan memory/` → route → **kind-aware compile** to `MEMORY.md` / skill files. |
| **M4** | `aigg-memory consolidate` writes typed units; `select` returns task-scoped, kind-filtered memory bundles. |
| **(later)** | Re-route AMF's own skill evolution through the same `memory` domain — the closed loop made literal (procedural memory). |

## Open questions

- **Unit granularity**: one fact per unit, or a unit per topic? (Skill-shaped favors
  one coherent note per unit.)
- **Manifest source of truth**: units are the source; `MemoryMakefile` and `MEMORY.md`
  are both compiled artifacts (lean: yes).
- **Working memory**: is `kind: working` (ephemeral, TTL'd scratch) in scope, or a
  later addition?
- **Embedding routing**: reuse AgentMakefile's `embedding`/`hybrid` matcher for recall
  — same cost-aware build-time/run-time split as the skill corpus.

## Out of scope (this spec)

- Cross-device sync / multi-user memory.
- Automatic contradiction detection beyond explicit `correction`/`obsolete`.
- Lifting `aigg-memory` to its own repo (the separate Phase 4 task).
