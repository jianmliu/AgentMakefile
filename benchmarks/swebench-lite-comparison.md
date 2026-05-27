# AgentMakefile SWE-bench Deterministic Comparison

- Tasks: 2
- Backend: agents-fragments
- Selected targets: code.change
- Stable prefix hashes: 1

## Baselines

| Baseline | Approx Tokens | Avg Savings Tokens | Sources |
| --- | ---: | ---: | --- |
| agents-md | 6738 | 5010 | AGENTS.md |
| claude-md | 6735 | 5007 | CLAUDE.md |
| skills-index | 3127 | 1399 | skills/index.md |
| none | 0 | -1728 | - |

## Cases

| Instance | Selected Targets | Stable Prefix Tokens | Stable Prefix Hash |
| --- | --- | ---: | --- |
| astropy__astropy-12907 | code.change | 1728 | sha256:62342c08614ccdc8fde3d1aa77df866bc4d40716f0aaa7653cf36c10c48244b0 |
| astropy__astropy-14182 | code.change | 1728 | sha256:62342c08614ccdc8fde3d1aa77df866bc4d40716f0aaa7653cf36c10c48244b0 |
