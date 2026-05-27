# AgentMakefile Evolution and Skill Workshop Spec

## Purpose

AgentMakefile should support a controlled self-evolution loop for skills,
targets, match rules, prompt fragments, dependencies, permissions, and benchmark
profiles. The goal is not autonomous mutation of the active project rules. The
goal is an evidence-driven workflow that proposes reviewable AgentMakefile
changes, compiles them, evaluates them, and promotes them only after explicit
review.

This feature line complements large skill ecosystem ingestion. A registry such
as OpenClaw can provide thousands of skills, but scale creates routing,
deduplication, trust, and maintenance problems. The Evolution and Skill
Workshop loop turns traces and benchmark evidence into smaller, auditable
AgentMakefile module improvements.

## Principles

- Evidence-driven: every proposed change must cite traces, benchmark results,
  user feedback, failed selections, duplicate detection, or source metadata.
- Reproducible: the same evidence bundle and compiler version should produce
  the same proposal payload.
- Reviewable: changes are emitted as candidate patches, not silently applied.
- Reversible: accepted changes remain normal source diffs that can be reverted.
- Bounded: proposal generation runs with explicit size, scope, and trust limits.
- Dry-run first: dream mode emits reports and patch candidates before any write
  to canonical AgentMakefile sources.

## Modes

### Skill Workshop

Skill Workshop is the interactive review mode. It presents candidate changes to
the user or maintainer and waits for approval before modifying canonical module
sources.

Typical proposals:

- Add a new target for a recurring request pattern.
- Improve `match.user_intent` terms for a skill or target.
- Add a dependency from a specialized skill to a bootstrap or safety skill.
- Split a large imported module into category modules.
- Merge duplicate or near-duplicate skill targets.
- Mark a skill as low-trust, deprecated, overlapping, or unsafe.
- Add benchmark coverage for a skill selection edge case.

### Dream Mode

Dream Mode is the offline candidate generator. It inspects evidence and writes
candidate artifacts under `.agentmf/evolution/`. It must not directly edit
`AgentMakefile`, `modules/**/AgentMakefile`, `AGENTS.md`, `CLAUDE.md`, or
installed host skill directories.

Default output layout:

```text
.agentmf/evolution/
  evidence/
    traces/*.jsonl
    benchmarks/*.json
    feedback/*.jsonl
  candidates/
    YYYY-MM-DD-HHMMSS-<slug>.patch
    YYYY-MM-DD-HHMMSS-<slug>.proposal.json
  reports/
    YYYY-MM-DD-HHMMSS-<slug>.md
```

## Evolution Loop

```text
observe
  -> collect selection traces, benchmark reports, usage outcomes, user fixes
extract
  -> identify repeated failures, missing routes, duplicate skills, stale rules
propose
  -> render candidate AgentMakefile patch and machine-readable proposal
compile
  -> compile candidate sources into target artifacts in an isolated output dir
evaluate
  -> run validation, deterministic selection tests, and configured benchmarks
promote
  -> present patch, evidence, and evaluation results for explicit approval
```

## Evidence Store

The evidence store is append-only by default. It stores enough information to
explain why a proposal exists without storing secrets, raw private prompts, or
unbounded logs.

Evidence record fields:

```json
{
  "version": 1,
  "event_id": "sha256:...",
  "timestamp": "2026-05-27T00:00:00Z",
  "source": "plugin_payload|benchmark|user_feedback|registry_scan|openclaw_import",
  "request_fingerprint": "sha256:...",
  "selected_target": "code.change",
  "selected_skills": ["superpowers:test-driven-development"],
  "selection_trace_hash": "sha256:...",
  "outcome": {
    "status": "resolved|unresolved|blocked|manual_correction",
    "metric": "swebench.resolved",
    "value": true
  },
  "artifact_refs": {
    "payload": ".agentmf/evolution/evidence/traces/...",
    "report": "benchmarks/..."
  },
  "summary": {},
  "payload_hash": "sha256:..."
}
```

Raw evidence should be redacted or summarized before it enters the store.
Secrets, access tokens, `.env` contents, private keys, and full proprietary
prompts must not be persisted by the evolution workflow.

First implemented CLI slice:

```bash
agentmf evo evidence add \
  --source openclaw_import \
  --payload-file /tmp/openclaw-import.json \
  --out-dir .agentmf/evolution/evidence \
  --write \
  --format json
```

For OpenClaw imports, the evidence record stores the importer curator evidence
summary and artifact references to the generated root index and category module
paths. It does not persist the full generated module content.

## Proposal Format

Each candidate proposal has a machine-readable summary:

```json
{
  "version": 1,
  "proposal_id": "amf-evo-...",
  "title": "Improve Django upload permission routing",
  "scope": {
    "modules": ["modules/openclaw/django/AgentMakefile"],
    "targets": ["skill.django-upload-permissions"]
  },
  "evidence": [
    {
      "event_id": "sha256:...",
      "reason": "agentmf harness resolved a task that plain baseline missed"
    }
  ],
  "changes": [
    {
      "type": "match_rule_update",
      "target": "skill.django-upload-permissions",
      "before_hash": "sha256:...",
      "after_hash": "sha256:..."
    }
  ],
  "evaluation": {
    "commands": [
      "agentmf validate modules/openclaw/django/AgentMakefile",
      "agentmf benchmark harness --suite benchmarks/agentmf-self-hosting.yaml"
    ],
    "status": "not_run|passed|failed"
  },
  "promotion": {
    "status": "candidate",
    "requires_review": true
  }
}
```

## Candidate Patch Generator

The generator should produce minimal patches against AgentMakefile sources. It
must avoid rewriting entire imported modules unless a module split or
normalization operation explicitly requires it.

Patch classes:

- `add_target`
- `update_match_terms`
- `add_dependency`
- `split_module`
- `merge_duplicate_targets`
- `deprecate_skill`
- `add_registry_metadata`
- `add_benchmark_case`
- `update_permission_guard`

Each patch must include:

- A proposal JSON file.
- A markdown explanation.
- The unified diff.
- The commands needed to validate it.

## Compile/Evaluate/Promote Loop

Candidate evaluation should run in an isolated output directory:

```text
.agentmf/evolution/worktrees/<proposal_id>/
.agentmf/evolution/out/<proposal_id>/
```

Minimum gates:

- `agentmf validate` on touched AgentMakefile files.
- Compile to at least one prompt backend.
- Compile to at least one skill backend when skill outputs are affected.
- Run deterministic selector tests for affected request examples.
- Run configured benchmark smoke tests when the proposal changes routing.

Promotion is explicit. The workflow can print a suggested command, open a PR, or
stage a patch, but it must not silently merge.

## OpenClaw Large Skill Ecosystem Curator

For large ecosystems, the evolution loop should operate on generated modules
instead of a single all-in-one index.

OpenClaw import and curation flow:

```text
OpenClaw skills
  -> registry/local scan
  -> category modules
  -> selection trace evidence
  -> duplicate and trust analysis
  -> workshop proposals
  -> reviewed module updates
```

Curator outputs:

- Category module suggestions.
- Duplicate or overlapping skill clusters.
- Missing match term proposals.
- Trust and provenance annotations.
- Heavy or unsafe tool requirement warnings.
- Candidate benchmark cases for high-value skills.

## Relation to Registry Standards

Registry standards such as ERC-8239 can provide skill identity, manifest,
provenance, installation metadata, and usage attestations. AgentMakefile should
treat that registry data as source metadata and compile it into skills, targets,
policies, and selection evidence.

AgentMakefile remains the compiler and harness layer. A registry remains the
identity, distribution, and provenance layer.

## Non-Goals

- No autonomous direct edits to canonical module sources in dream mode.
- No unreviewed installation of remote skills.
- No secret-bearing evidence persistence.
- No claim that generated proposals are correct without compile and benchmark
  evidence.
- No replacement for human review on high-impact policy, permission, or
  security changes.

## Initial Milestones

- AMF-EVO-001 Evolution Evidence Store.
- AMF-EVO-002 Skill Workshop Proposal Format.
- AMF-EVO-003 AgentMakefile Candidate Patch Generator.
- AMF-EVO-004 Compile/Evaluate/Promote Loop.
- AMF-EVO-005 Dream Mode Dry-Run.
- AMF-EVO-006 OpenClaw Large Skill Ecosystem Curator.
