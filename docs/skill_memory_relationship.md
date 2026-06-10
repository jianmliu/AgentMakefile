# Skill ⇄ Memory: Build-time Curation vs. Runtime Learning, Gated by Verification

**Status:** design north-star (one page). Frames how AgentMakefile's skills and aigg-memory's learned
units relate. The mechanisms live elsewhere: curated side → `agentmf_evolution_skill_workshop_spec.md`;
learned side → `aigg_memory_kernel_design.md` / `typed_memory_design.md`. This doc fixes the *shape*
those two must agree on.

## §0 The unifying frame: one graph, two write-paths, one selector

The north star: **SkillMakefile and aigg-memory's MemoryMakefile are the same data structure** — a
dependency graph of small, typed `SKILL.md` units. AgentMakefile and aigg-memory are not two systems;
they are **two write-paths into one graph**, plus **one shared selector** that reads it.

This is already AgentMakefile's design, not a proposed change. The spec is explicit
(`agentsfile_design_spec.md`): "Static generated files are the **compatibility layer**" (§ "deeper
integration"); compiled fragments "are **not** the final all-in-one `CLAUDE.md` … each should contain
**only the target's resolved dependency closure** … a runtime can **load only the fragments needed for
the current request**." So SkillMakefile was always small-and-focused; the monolithic `CLAUDE.md` is a
**flatten for runtimes that can only eat one prefix file**, not the model.

**The Makefile semantics are load-bearing** — `make`'s three pillars map onto skills:

| Makefile | SkillMakefile / MemoryMakefile |
|---|---|
| prerequisites (`deps`) | the skills a skill needs — aigg-memory's `deps` edges |
| build a target | resolve its **dependency closure** and load it (`dependency_closure` + `select`) — exactly SkillsBench #3's "2–3 focused modules", not everything |
| **incremental rebuild** | **stale-propagation**: a skill's grounding changes → dependents go `stale` → pending re-verify (`mark_stale_dependents` is the "out-of-date" test) |
| recipe (how to build) | **`verify`** (OpenSkill stage 3): run the candidate skill's check; promote on pass |
| `make <goal>` | intent → target → closure → load the needed fragments (routing) |

**Selection is the same operation on both sides** — the flat `CLAUDE.md` is just the dumb-runtime backend:

| AgentMakefile (spec §10/§11) | aigg-memory |
|---|---|
| select task **target** | `select(request)` matches units |
| **resolve dependency closure** → fragments | `dependency_closure` → recall units + deps |
| big `CLAUDE.md` | a compatibility backend for flat runtimes — *not* the model |

So build-time fragments (authored) and runtime units (learned-then-verified) live in one graph and are
assembled into the prompt by **one closure resolver**. Incremental skill maintenance — change one
grounding, re-verify only its dependents — comes free from the same stale-propagation aigg-memory
already has. The rest of this doc is what that frame implies once you separate *trust* (`kind` +
`status`) from *structure* (the shared graph).

## The evidence we are designing against

Two 2026 results bound the design:

- **SkillsBench** (arXiv:2602.12670): across 86 tasks / 11 domains, **curated skills add +16.2pp on
  average** (domain-dependent: +4.5 SWE … +51.9 Healthcare), but **self-generated skills give no
  average benefit** — models cannot reliably author the procedural knowledge they need. Also: **focused
  skills (2–3 modules) beat comprehensive documentation**; and a small model + skills ≈ a large model
  without.
- **OpenSkill** (arXiv:2606.06741): self-evolution *can* work, but only with **grounding** (open-world
  docs/repos) **plus a verification/refinement loop** against self-constructed checks. Skills so learned
  transfer across models.

Read together: **curated knowledge is where the value is; learned knowledge is worthless until
verified; and the right size is small and focused.**

## Two axes, one substrate

Skills and memory are the same artifact — a typed `SKILL.md` unit — separated only by *how they earned
trust*:

| | **Build-time (curated)** | **Runtime (learned)** |
|---|---|---|
| author | human + big model, compiled by AgentMakefile | the agent, via aigg-memory `reflect`/`ingest` |
| confidence | high (the SkillsBench +16pp end) | low until verified (the "no benefit" end) |
| kind | `procedural` (curated), targets, policies | `episodic`/`semantic`/`belief`, then maybe `procedural` |
| cost model | expensive once, at build | cheap, continuous, gated |
| status | active | `needs_review` until it passes the gate |

This matches the project's standing cost principle: **big model at build time produces cheap, audited
artifacts; cheap model at runtime escalates only under confidence-gating.** AgentMakefile owns the
build-time end; aigg-memory owns the runtime end; the **seam is the unit `kind` + its `status`.**

## The rule that keeps us out of the SkillsBench trap

**A learned unit may inform decisions immediately, but may not become an invokable skill until verified.**

Two clarifications this forces:

1. **belief ≠ skill.** aigg-memory's `reflect` produces **beliefs** (declarative, for *decisions* — "pump
   is a trap"). Used as discernment (read by provenance, not text) they are already useful and are *not*
   what SkillsBench warns about. The dangerous move is promoting a belief/experience into an **invokable
   procedural skill** — that is a self-generated skill, and it must be gated.
2. **The gate has landed (kernel side).** aigg-memory now implements it for the belief case:
   `memory.verify_belief()` — a deterministic tally of outcome-tagged episodes (no LLM) with three
   statistical/adversarial guards (derivation evidence is the *prior*, never a test; scope vocabulary
   comes from the cited evidence, not just the belief's wording; only self/host-trusted witnesses
   count, so the verification axis cannot bypass the provenance axis). It runs in the Dream deep pass
   after `reflect`, is exposed as `/memory/verify`, and feeds decisions via
   `believes/discernment(min_confidence=θ)` — *relevant AND confidence ≥ θ*. What remains for the
   *skill* tier is the procedural signal (task/replay success) — OpenSkill's stage 3 for `kind=procedural`.

## The pipeline (kind = seam, gate = OpenSkill's stage 3)

```
open-world docs/repos ──ingest──▶ episodic/semantic units            (grounded, low trust)
authored AgentMakefile ──compile─▶ procedural units / targets         (CURATED, high trust)
episodes ──reflect──▶ belief                                          (decision-only; NOT a skill)
belief / repeated experience ──VERIFY (new)──▶ pass ? promote to procedural skill : keep needs_review
runtime skills ──curate + SkillsBench-style marginal-benefit test──▶ no benefit ? prune (archive)
```

- **`verify`** is the third mirror beside `reflect` (backward) and `plan` (forward): take a candidate
  procedural unit, construct/run a check (self-built virtual task, à la OpenSkill; or a deterministic
  probe from the eval harness), and **promote only on pass**, else leave it `needs_review`.
- **Promotion is the only path from learned → curated-grade trust**, and it is reviewable, mirroring
  `agentmf_evolution_skill_workshop_spec.md` (evidence-driven, candidate-patch, promote-after-review).
  The Skill Workshop *is* the human-in-the-loop instance of this gate.

## Verify is a kernel-level trust axis, not just a skill gate

The gate above is the *skill-promotion* face of something more general. Because a skill is just a
`procedural` memory unit (§0), the verification it demands generalizes to **every learned unit**.
aigg-memory grounds trust four ways — **provenance** (who/from-what), **repetition** (the
consolidation gate), **valid-time** (when), and now **verification** (does it pay off) — the last
being precisely the axis SkillsBench/OpenSkill show matters most for self-generated knowledge.
`verify` is the **evaluative complement** to the generative `reflect`/`plan`, its signal kind-specific
— a skill by task/replay success, a belief by the decision outcomes it predicts, a fact by
corroboration — and **graded and optional** (a one-off episode cannot be re-verified; those fall back
to provenance + repetition).

**Skill is simply the highest-trust tier on that axis.** A learned belief may be used for decisions on
weak verification; promotion to an *invokable curated-grade skill* demands the strongest. This is the
symmetry to track: the aigg-memory kernel paper develops `verify` as a kernel trust axis (paper §11;
implemented for beliefs as a deterministic outcome tally with Laplace confidence); this doc consumes
the same axis as the build-time/runtime promotion gate. One axis, two faces.

## Skill ⊂ memory: four layers, one circulation

The content-level settlement of "what is a skill, relative to memory":

1. **Taxonomy (settled a century ago).** Cognitive science divides memory into *declarative*
   (knowing-that: semantic facts + episodic events) and *procedural* (knowing-how) — and procedural
   memory **is** skill (Ryle's knowing-how/knowing-that; Squire's taxonomy). `VALID_KINDS` encodes
   this literally: a skill is a `kind=procedural` unit. Skill is not beside memory; it is a kind of it.
2. **Dynamics: memory is the skill factory.** Anderson's *knowledge compilation* (ACT-R, 1982):
   skills are acquired by compiling declarative knowledge into procedures through **practice**. Our
   pipeline is its engineering form — `episodes → reflect → belief → verify(outcomes = practice) →
   promote to procedural` — with the compilation step made **explicit and auditable** (the verify
   gate), because LLM self-generation can't be trusted to compile implicitly (SkillsBench).
3. **Runtime: memory is read, skill is run.** Declarative units inform decisions
   (`believes`/`discernment`); procedural units are *enacted* (the host executes their `apply`). An
   unverified belief misleads a judgment; an unverified skill mis-acts directly — which is *why* skill
   sits at the top of the trust axis.
4. **Two acquisition routes, one loop.** *Taught*: AgentMakefile-compiled curated skills (instruction
   — fast, born procedural, high trust). *Practiced*: the aigg-memory pipeline (experience — slow,
   verify-gated). And it loops: an enacted skill produces outcome-tagged episodes, which feed reflect
   and verify — memory is the skill's origin, skill is memory's output, execution feeds the output
   back into the origin.

**The payoff is practical, not philosophical.** Treating skills as memory gives skill management the
kernel's machinery for free — and the rows below are exactly the "routing, deduplication, trust, and
maintenance problems" `agentmf_evolution_skill_workshop_spec.md` names for large skill ecosystems:

| skill-management problem | = an existing memory operation |
|---|---|
| where did this skill come from; is it trustworthy | provenance + verify |
| deprecate / retire a skill | `valid_to` / temporal supersede |
| its grounding (docs) changed — re-review | **stale-propagation (incremental rebuild)** |
| thousands of skills, near-duplicates | compact |
| two skills conflict | reconcile |
| which skills to load for this task | select + dependency closure |

> **A skill is memory that has earned the right to act.** Memory answers "what is true"; skill answers
> "what to do"; verification is where truth buys the right to direct action. One graph, one unit
> format — the differences are kind (read vs run) and trust (how far up the axis it has climbed).

## Concrete consequences for AgentMakefile

1. **Prefer the fragment / dependency-closure path; keep flat `CLAUDE.md` as a compatibility backend**
   (SkillsBench #3 *validates*, not critiques, AgentMakefile here — §0). The model is already focused
   units loaded by closure; the work is to route through that path (= aigg-memory `select`) wherever the
   runtime allows, and treat the monolithic block as the degraded fallback for runtimes that can only
   eat one prefix file — not the default.
2. **Add a `verify` gate before any learned unit is treated as a skill** (SkillsBench #2 + OpenSkill).
   It reuses the two-tier eval as the verifier.
3. **Measure marginal benefit per domain and prune** (SkillsBench #1 + the existing `curate` op). A skill
   that does not help in evaluation is archived — curation gets a *criterion*, not just a heuristic.
4. **Treat curated (AgentMakefile) skills as the high-value default and learned skills as candidates**
   that must climb the gate to reach the same trust — never the reverse.

## Open questions (for the next pass)

- What is a good cheap, deterministic-ish **verifier** for a candidate skill? (self-built virtual task
  vs. replay of past traces vs. the manifest eval harness.)
- Where does the **marginal-benefit benchmark** live — `agentmf_harness_benchmark_suite_spec.md`, and
  does it adopt the SkillsBench no-skill / curated / self-generated three-arm design?
- How is **per-domain variance** (SkillsBench #1) surfaced so routing knows where skills pay off?
- Cross-model transfer (OpenSkill): a verified unit is model-agnostic markdown — do we record which
  model authored/verified it for audit, and re-verify on model change?

## See also

`agentmf_evolution_skill_workshop_spec.md` · `aigg_memory_kernel_design.md` · `typed_memory_design.md`
· `agentmf_guidance_ingestion_spec.md` · the aigg-memory kernel paper `docs/paper_memory_kernel.md`
and the ecosystem-manager spec `docs/aigg_skill_design.md` (both in the aigg-memory repo).
