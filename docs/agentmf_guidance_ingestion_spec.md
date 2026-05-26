# AgentMakefile Guidance Ingestion Spec

Status: proposed.

Date: 2026-05-26.

## Summary

AgentMakefile should not only generate native guidance artifacts. It should also
read existing guidance artifacts and convert them into a structured
AgentMakefile routing graph.

The first reverse-import path scanned `*/SKILL.md` directories. That is useful
but incomplete. Real agent setups often mix:

- `AGENTS.md`
- `CLAUDE.md`
- standalone `SKILL.md`
- directories of `*/SKILL.md`
- `skills/index.md`
- Cursor rules
- plugin or framework Markdown guides

The generalized feature is **guidance ingestion**: scan a guidance corpus,
produce a generated AgentMakefile guidance-index module, and let
`agentmf plugin payload` optimize which skills or instruction fragments should
be loaded for a given request.

## Product Role

Guidance ingestion is the reverse side of cross-platform compilation:

```text
existing guidance corpus
  -> agentmf guidance scan
  -> generated AgentMakefile guidance-index module
  -> agentmf plugin payload
  -> selected skills / fragments + selection_trace
```

This makes AgentMakefile a structured management entry point for existing agent
guidance, not only for new hand-authored AgentMakefile modules.

## Goals

- Import existing `SKILL.md`, `AGENTS.md`, `CLAUDE.md`, and related prompt
  guidance into generated AgentMakefile modules.
- Preserve source provenance for every imported entry.
- Infer deterministic match terms from names, descriptions, headings, and
  "when to use" style sections.
- Represent each imported unit as a selectable target.
- Preserve native skill identity where the source is a real skill package.
- Let plugin payloads expose selection rationale through existing
  `selected_targets`, `selected_skills`, `skill_artifacts`, and
  `selection_trace` fields.
- Keep generated AgentMakefile output as a bridge artifact; curated modules can
  replace it over time.

## Non-Goals

- Perfectly understanding arbitrary Markdown semantics in the first slice.
- Rewriting human-authored guidance.
- Mutating `AGENTS.md`, `CLAUDE.md`, or `SKILL.md` inputs during scan.
- Calling a model to summarize or classify guidance.
- Replacing native host skill loaders.

## Command Surface

### Lower-Level Scanner

```bash
agentmf guidance scan \
  --source AGENTS.md \
  --source CLAUDE.md \
  --source ~/.codex/skills \
  --namespace imported \
  --package-name imported-guidance \
  --out .agentmf/imported/AgentMakefile \
  --write
```

Options:

```text
--source PATH          # repeatable file or directory
--source-type TYPE     # auto|skill-dir|skill-md|agents-md|claude-md|skills-index|cursor-rule
--namespace NAME
--package-name NAME
--package-description TEXT
--bootstrap-skill NAME
--out PATH
--write
--format json|text
```

### Plugin Install Wrapper

`agentmf plugin install` should keep `--skills-dir` for compatibility, but it
should also accept the same generalized `--source` / `--source-type` options.
When both are present, `--skills-dir` is treated as `--source-type skill-dir`.

## Source Readers

### `skill-dir`

Input:

```text
<dir>/*/SKILL.md
```

This is the current implemented scanner. It remains the highest-fidelity import
format because it usually has structured frontmatter and package identity.

### `skill-md`

Input:

```text
path/to/SKILL.md
```

Read one standalone skill file. Use frontmatter `name` and `description` when
present. If missing, derive the name from the parent directory or filename.

### `agents-md`

Input:

```text
AGENTS.md
```

First slice behavior:

- Import the file as one guidance-backed target.
- Derive the target name from the filename and parent directory.
- Infer match terms from top-level headings, short bold labels, and imperative
  phrases.
- Store `implementation.source` as the original file path.
- Do not create `selected_skills` unless the file contains discoverable skill
  references.

Later behavior can split large files into section-level targets when headings
are stable enough to preserve provenance.

### `claude-md`

Input:

```text
CLAUDE.md
```

Same first-slice behavior as `agents-md`, but mark the imported unit with a
Claude source type so future backends can preserve host-specific context.

### `skills-index`

Input:

```text
skills/index.md
```

Parse linked skill paths when present. If linked `SKILL.md` files are available,
delegate to `skill-md`; otherwise import the index as one guidance target.

### `cursor-rule`

Input:

```text
.cursor/rules/*.mdc
```

Parse frontmatter when present and import each rule file as one target. Use the
frontmatter description plus headings/body terms for matching.

## Generated AgentMakefile Shape

Imported guidance should produce a module like:

```yaml
version: "0.1"
metadata:
  name: imported-guidance
  module_type: guidance-index
compile:
  targets:
    - agents-fragments
    - claude-fragments
    - skills-index
targets:
  guidance.agents:
    phony: true
    priority: 60
    description: Imported AGENTS.md guidance.
    match:
      user_intent:
        - review code
        - implement feature
    steps:
      - action: read_imported_guidance
    implementation:
      source: AGENTS.md
      source_type: agents-md
```

Skill package inputs should still emit `skills:` entries and `selected_skills`;
plain Markdown guidance inputs may only emit `targets:` until a future parser
can identify reusable skills inside the Markdown.

## First Implementation Slice

1. Add a `guidance_scanner` module with source reader dispatch.
2. Move the current skill directory scanning path behind the generalized
   scanner without breaking `agentmf skills scan`.
3. Support `skill-dir`, `skill-md`, `agents-md`, and `claude-md`.
4. Add `agentmf guidance scan`.
5. Let `agentmf plugin install` accept `--source` in addition to `--skills-dir`.
6. Add tests showing an imported `AGENTS.md` can be validated and routed through
   `agentmf plugin payload`.

## Future Slices

- Split `AGENTS.md` / `CLAUDE.md` by stable headings into multiple targets.
- Parse `skills/index.md` links and import referenced skills.
- Import Cursor rules.
- Add source hashing so unchanged imported guidance can skip regeneration.
- Add benchmark cases comparing imported all-in-one Markdown against selected
  prompt fragments.
