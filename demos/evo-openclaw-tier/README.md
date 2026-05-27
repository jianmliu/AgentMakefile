# evo OpenClaw tier runner

Reproducible pipeline for `agentmf evo` against a real OpenClaw-style SKILL.md
corpus.

Default skill roots (any that exist are scanned; missing ones are skipped):

| Path | Origin |
| ---- | ------ |
| `/opt/homebrew/lib/node_modules/openclaw/skills` | `openclaw` CLI's bundled skills (most authentic OpenClaw set) |
| `~/.codex` | Codex install (OpenClaw upstream + openai/anthropic plugin marketplaces) |
| `~/.claude` | Claude install (Anthropic skills) |

Why local paths and not the official OpenClaw GitHub repo:
`github.com/openclaw/skills` is not a public repo (HTTP 404), and
`VoltAgent/awesome-openclaw-skills` plus `clawskills.sh` are discovery
indexes without machine-readable SKILL.md endpoints. The `openclaw` CLI and
`clawhub` CLI install skills to the local paths above, which is the
intended distribution mechanism.

## Tiers

| `--tier` | Subset rule | Drives curator with |
| -------- | ----------- | ------------------- |
| `smoke`  | 100 unique-by-name, alphabetical | `dup-subset` (~120 entries after dup injection) |
| `200`    | 200 unique-by-name, alphabetical | `dup-subset` (~236 entries after dup injection) |
| `full`   | none — uses the full scan as-is  | `openclaw-import.json` directly (573 entries, 58 dup groups) |

## Stages (10)

`run.py` executes the pipeline below per tier. Each stage's JSON is captured
into the tier output directory.

| # | Command | Output |
| - | ------- | ------ |
| 1 | `openclaw scan --skills-dir <root>...` | `openclaw-import.json` + `modules/openclaw/` |
| 2 | (Python) materialise N unique-by-name SKILL.md | `skills-subset/NNN-{slug}/SKILL.md` |
| 3 | `openclaw scan --skills-dir skills-subset` | `subset-modules/`, `subset-openclaw-import.json` |
| 4 | overlap variant | `skills-subset-with-overlap/`, `subset-overlap-modules/`, `subset-overlap-openclaw-import.json` |
| 5 | duplicate-injection variant | `skills-subset-duplicate-evidence/`, `dup-subset-modules/`, `dup-subset-openclaw-import.json` |
| 6 | `evo evidence add --source openclaw_import --payload-file <import>` | `evidence-add.json`, `evidence/registry/openclaw_import.jsonl` |
| 7 | `evo openclaw curate --evidence-file …` | `curate.json`, `candidates/amf-evo-*.{md,proposal.json}` |
| 8 | `evo dream run --evidence-dir evidence` | `dream.json`, `dream-candidates/` |
| 9 | `evo evaluate --proposal-file candidates/…proposal.json` | `evaluate.json`, `eval-workspace/` |
| 10 | `validate --file modules/openclaw/AgentMakefile` | `validate-root.json` |

For `--tier full`, stages 2–5 are skipped: the full corpus's own duplicate
groups feed the curator directly.

## Usage

```bash
python3 demos/evo-openclaw-tier/run.py \
  --tier smoke \
  --out-dir "$(mktemp -d /tmp/agentmf-evo-smoke.XXXXXX)"

python3 demos/evo-openclaw-tier/run.py \
  --tier 200 \
  --out-dir "$(mktemp -d /tmp/agentmf-evo-200.XXXXXX)"

python3 demos/evo-openclaw-tier/run.py \
  --tier full \
  --out-dir "$(mktemp -d /tmp/agentmf-evo-full.XXXXXX)"
```

Optional flags:

- `--skill-dir PATH` (repeatable). Defaults to `~/.codex` and `~/.claude`.
- `--count N`. Overrides the tier's default subset size.
- `--repo-root PATH`. Defaults to the repo root containing this script; used
  to set `PYTHONPATH` so the run hits the in-tree `agentmf` package rather
  than whatever is installed globally.

Tier output is written under `--out-dir` and a top-level `tier-summary.json`
records the stage metrics (skill count, dup groups, curate proposal count,
evaluate ok).
