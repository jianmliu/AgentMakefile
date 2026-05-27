# AgentMakefile OpenClaw Importer Spec

## Goal

Import a large local OpenClaw-style skill ecosystem into modular
AgentMakefile sources without flattening thousands of `SKILL.md` files into one
prompt index.

The importer is a bridge, not a remote registry client. It reads local skill
trees, preserves source paths and category metadata, renders category-specific
AgentMakefile modules, and emits curator evidence that later evolution tasks
can use to propose reviewable improvements.

## Scope

In scope:

- Recursively scan local `**/SKILL.md` files.
- Parse frontmatter fields such as `name`, `description`, `category`, and
  `tags`.
- Infer a category from the first path segment when frontmatter does not
  provide one.
- Prefix generated skill names with their category, for example
  `coding.code-review`, so duplicate original skill names can coexist.
- Add stable numeric suffixes when duplicate names also collide inside one
  category, for example `coding.review` and `coding.review-2`.
- Render one `AgentMakefile` per category.
- Render a root `AgentMakefile` that includes category modules.
- Export deterministic curator evidence with counts, duplicate original names,
  and module paths.
- Keep write mode explicit with `--write`.

Out of scope for the first importer slice:

- Remote OpenClaw registry fetching.
- Installing or modifying host-native skills.
- Semantic deduplication beyond exact duplicate original names.
- Automatic promotion of curated modules.
- Full evidence-driven evolution proposals.

## CLI

```bash
agentmf openclaw scan \
  --skills-dir /path/to/openclaw/skills \
  --namespace openclaw \
  --package-name openclaw-skills \
  --out modules/openclaw \
  --write \
  --format json
```

Without `--write`, the command returns the root and category module content in
JSON but does not touch the filesystem.

The importer output can be recorded as EVO evidence:

```bash
agentmf evo evidence add \
  --source openclaw_import \
  --payload-file /tmp/openclaw-import.json \
  --out-dir .agentmf/evolution/evidence \
  --write \
  --format json
```

## Generated Layout

```text
modules/openclaw/
  AgentMakefile
  coding/AgentMakefile
  research/AgentMakefile
  docs/AgentMakefile
```

The root module is an index:

```yaml
metadata:
  module_type: openclaw-skill-root
include:
  - coding/AgentMakefile
  - research/AgentMakefile
```

Each category module contains generated skill entries and routeable targets:

```yaml
metadata:
  module_type: openclaw-skill-category
  category: coding
skills:
  coding.code-review:
    namespace: openclaw
targets:
  skill.coding.code-review:
    skills:
      - openclaw:coding.code-review
```

## Curator Evidence

The importer emits a `curator_evidence` object:

```json
{
  "source": "openclaw-local-scan",
  "skill_count": 2,
  "category_count": 2,
  "categories": {"coding": 1, "docs": 1},
  "duplicate_original_names": {
    "review": ["coding/review/SKILL.md", "docs/review/SKILL.md"]
  },
  "module_paths": ["coding/AgentMakefile", "docs/AgentMakefile"]
}
```

This evidence is intentionally small and deterministic. Later evolution tasks
can turn it into candidate patches for category splits, duplicate merges,
match-term improvements, trust annotations, and benchmark cases.

## Task Breakdown

### AMF-OPENCLAW-001 Local Skill Scanner

Status: implemented.

Recursively scan local skill trees and produce normalized skill records with
original name, generated category-prefixed name, namespace, category, tags,
source path, relative path, description, and inferred match terms. Duplicate
generated names within one category receive stable numeric suffixes.

### AMF-OPENCLAW-002 Modular AgentMakefile Renderer

Status: implemented.

Render category-level AgentMakefile modules from scanned records. Generated
skills preserve original source metadata in `implementation`.

### AMF-OPENCLAW-003 Category Split + Root Index

Status: implemented.

Render a root index AgentMakefile that includes each category module and stores
summary metadata for category and skill counts.

### AMF-OPENCLAW-004 Selection Smoke Test

Status: implemented.

Generated root modules can be loaded by the existing AgentMakefile loader and
selected by the existing request matcher.

### AMF-OPENCLAW-005 Curator Evidence Export

Status: implemented.

The scan payload includes deterministic curator evidence for counts, categories,
duplicates, and module paths.
