# Typed Long-Term Memory — one substrate, one process cycle

A complete memory system, not just a store: **typed storage** (skills are procedural
memory; notes are semantic / episodic) plus the **process cycle** (encode → store →
consolidate → retrieve → forget), where **Dream is the consolidation process**.

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
| *(working)* — *deferred* | *current scratch* | task scratchpad | ephemeral, TTL'd |

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

## Memory is processes, not just storage

A complete memory system is not a store — it is a *cycle of processes*. The typed
substrate above is only the "storage" box. Named properly:

| memory process | component | request hot path? |
| --- | --- | --- |
| **encoding** | `EvidenceStore.record` (observation → evidence) | online |
| **working memory** | the current task context (`kind: working`, ephemeral) | online |
| **storage** | the typed units (procedural / semantic / episodic) | — |
| **consolidation = Dream** | `run_dream`: replay evidence, promote, merge, prune, generalize | **offline / batch** |
| **retrieval** | matcher / `select` (relevance recall) | online |
| **forgetting** | prune / archive detectors | offline |

### Dream is the consolidation process — and the transformer between kinds

In neuroscience, memory consolidation happens during sleep/dreaming (hippocampal
replay → neocortical storage). "Dream Mode" is named for this literally: it is the
**offline consolidation phase**, not a tool that operates on memory from outside.

Systems consolidation = turning **episodic** experience into **semantic /
procedural** knowledge. That is exactly what Dream does: many episodic routing
events → a generalized procedural `match` rule, or a new skill. So the kinds are not
static silos — Dream is the engine of the flow between them:

```
episodic experience  ──(Dream consolidation)──▶  semantic facts / procedural skills
```

`confidence` / `observations` are therefore the **degree of consolidation**:
observed once = weak / episodic; promoted across many observations = strong /
semantic.

### Already structurally true

Phase 2c routed AMF's dream through the kernel's `run_dream`; Phase 3's markdown
domain consolidation runs through `run_dream` too. So **`run_dream` is already the
unified consolidation engine across kinds** — AMF dream (procedural consolidation)
and the markdown detectors (semantic / episodic consolidation) are the same process,
different kind. The Phase 2c merge unified the consolidation *process*; this section
gives it the right name.

### Two speeds = the cost principle

- **online**: retrieval (matcher) — cheap, in the hot path.
- **offline**: consolidation (Dream) — expensive, batch.

This is the project's cost principle (a big model at build time producing cheap
artifacts; cheap consumption at run time): Dream is the expensive offline thinking
that yields units cheap to recall at run time.

### Boundary preserved

AMF's Dream is dry-run, review-only — it *proposes*; promotion *commits*. In memory
terms: consolidation proposes, waking commits, and the commit still passes the
per-kind gate (procedural needs review; semantic may auto-promote at high
confidence). Naming Dream "a memory process" does not weaken the gate.

### The Dream trigger is application policy, not an engine schedule

*When* consolidation fires is not the engine's call — it is application-specific.
Different applications have different natural "sleep" moments:

| application | `observe` (online encoding) fires on | Dream (offline consolidation) fires on |
| --- | --- | --- |
| MUD / game (NPC memory) | each player↔NPC interaction | the NPC **sleeping** (night tick), a player leaving the area, a scene/quest ending |
| onchainpal (calls AIGG inference) | each inference call / a session | a budget-epoch close, a settlement event, session end |
| coding agent (AMF skill evolution) | each task / tool call | a work session ending, a PR merge, an idle window |

In a MUD "sleep = consolidation" is literal: each NPC is its own corpus
(`npcs/<id>/memory`), its daytime interactions are recorded as episodic evidence,
and when it sleeps that corpus consolidates — episodic interactions become semantic
facts (a relationship score) or even procedural habits. Per-entity corpora give
each entity its **own Dream rhythm**.

So the engine deliberately ships **no scheduler**. It owns the *mechanism*
(`observe` / `consolidate`); the application owns the *trigger*, instrumented in its
own events. The only engine-side affordance is a cheap **readiness signal** —
`consolidation_status(root, records, corpus) -> {pending, oldest_pending_timestamp,
recommended}` (a record is *pending* until its `event_id` is folded into a unit's
`source_events`) — that an app can poll to decide *whether* to fire, while the
*when* (the threshold, the sleep hook, the epoch) stays the app's policy. Typical
loop: `status → if the app's own rule says go → consolidate`. Exposed as the CLI
`consolidation-status` and `POST /memory/consolidation-status`.

## Decisions (recorded)

1. **Everything-is-memory, typed.** One unit format with a `kind`; skills are
   `kind: procedural`. Same frontmatter, matcher, compile, and consolidation loop
   across kinds — differentiated by `kind`.
2. **Index/route is kind-agnostic; consume and consolidate are kind-aware.**
3. **Memory units ride on AgentMakefile skills** for the read side (scan / matcher
   / compile); `aigg-memory` owns the write/consolidation side.
4. **Memory is processes, not just storage.** Dream *is* the consolidation process
   (offline), not an external tool; `run_dream` is the unified consolidation engine
   across kinds. The system is the full cycle: encode → store → consolidate →
   retrieve → forget.
5. **The Dream trigger is application policy.** The engine ships no scheduler — it
   owns the mechanism (`observe`/`consolidate`) and offers a readiness signal; the
   app owns *when* to fire (NPC sleep, session/epoch end, idle window).
6. **Spec first**, then implement.

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
| **M1 — landed** | `Workspace` abstraction in the kernel: `generate_workspace_patch` / `evaluate_workspace` over `dict[path→content]` + per-file diffs, plus `lift_document_applier` bridging a single-document applier into the one-entry case. Additive — the single-document API is untouched, so Phase-3 stays green; a test proves one-entry-workspace ≡ document. |
| **M2 — landed** | `memory` domain (`aigg_memory.memory`): `MemoryUnit` frontmatter (+`kind`) parse/render (PyYAML, unicode-safe), multi-file appliers (`add_unit` / `update_unit` / `merge_units` / `archive_unit`) on the Workspace, kind-aware gates (`units_parse` / `unique_ids` / `has_match_terms` / `kind_valid`), evidence detectors with the **kind-aware policy** (procedural → `candidate` / needs-review; declarative → `active`), and a `consolidate(workspace, records)` orchestrator. The kernel core stays dependency-free; the `memory` domain adds PyYAML (a memory store reading SKILL.md legitimately needs YAML). TDD end-to-end on a corpus with procedural + semantic units. |
| **M3 — landed** | Scanner enhancement: `_read_skill` merges an explicit `match.user_intent` (authoritative routing terms) and carries `kind`; `kind` is now a first-class field on `SkillSpec` + `IRSkill` (additive, default `None`). End-to-end proven: `aigg-memory consolidate` writes typed units → `agentmf skills scan memory/` → a **valid, routable** `MemoryMakefile` (`kind` survives into the IR; the keyword matcher routes a unit by its explicit terms). Per-kind compile *rendering* is M4. |
| **M4 — landed (write side)** | `consolidate_corpus(root, records, write)` + CLI (`remember` records a typed observation; `consolidate-corpus` loads `memory/` → consolidates → writes changed unit files back, gated; idempotent; deletes merged-away units). Proven end-to-end on disk: `remember ×N` → `consolidate-corpus --write` → real `memory/<slug>/SKILL.md` with kind-aware status. Plus `consolidation_status` (CLI `consolidation-status`, `POST /memory/consolidation-status`): the app-owned-trigger readiness signal. The full `/memory/*` HTTP surface (observe/consolidate/status/select/units) + a web-UI recall panel ship over the same domain. |
| **M5 — landed (read side)** | Two kind-aware read surfaces: (1) **request-scoped** — `agentmf.memory_recall.recall_memory(path, request, kinds=…)` routes via the existing matcher, **filters selected units by `kind`**, and renders a kind-aware bundle; (2) **corpus-wide compile** — a new **`memory-md` backend** compiles the whole typed corpus into one `MEMORY.md`, rendered per kind: procedural → `apply <name> — …` (actionable, under "## Procedures (apply)"); semantic → "## Facts"; episodic → "## History". Additive (new backend + reuses the selector) — zero change to existing backends, no compile-test risk. With this, nothing in the pipeline treats memory as "pure skill": `kind` drives scan, recall, and compile rendering. |
| **(later)** | embedding / hybrid recall; `kind: working` (ephemeral, TTL'd); re-route AMF's own skill evolution through the same `memory` domain — the closed loop made literal (procedural memory). |

## Resolved decisions

- **Unit granularity — one coherent topic per unit.** A unit ≈ a SKILL.md: one
  routable subject, whose body may hold several related facts. Not one sentence per
  unit (fragments routing), nor a catch-all file. Matches today's `MEMORY.md`
  entries (`project_name_decision`, `skill_corpus`, `budget_protocol`).
- **`kind: working` — deferred (not M1–M4).** Working memory is ephemeral, TTL'd,
  not consolidated, and excluded from compile — a different lifecycle that does not
  share the consolidation loop. First phase ships the three durable kinds
  (procedural / semantic / episodic). The `kind` enum reserves `working`; its
  semantics come later.
- **Routing — keyword first, embedding / hybrid later.** The matcher already supports
  all three; memory starts on keyword (zero build-time cost, deterministic,
  testable). Add embedding / hybrid when the corpus is large enough to need semantic
  recall — the cost principle (the embedding index is a build-time investment, paid
  when it earns its keep).
- **Manifest source of truth — the units.** `memory/*/SKILL.md` are the source;
  `MemoryMakefile` and `MEMORY.md` are both compiled artifacts, never hand-edited.

## Out of scope (this spec)

- Cross-device sync / multi-user memory.
- Automatic contradiction detection beyond explicit `correction`/`obsolete`.
- Lifting `aigg-memory` to its own repo (the separate Phase 4 task).
