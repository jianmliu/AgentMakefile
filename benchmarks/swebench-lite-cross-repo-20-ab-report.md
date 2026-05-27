# SWE-bench Lite Cross-Repo 20 A/B Report

Date: 2026-05-26

This run compares plain Codex prompting against AgentMakefile-selected harness prompting on the same 20-instance, cross-repository SWE-bench Lite subset.

## Setup

- Dataset: `princeton-nlp/SWE-bench_Lite`, split `test`
- Subset: 20 instances across 12 repositories
- Model used by Codex CLI: `gpt-5.5`
- Arms:
  - `plain-codex-gpt-5.5`: direct SWE-bench task prompt
  - `agentmf-codex-gpt-5.5`: AgentMakefile-selected `code.change` harness prefix plus the same task prompt
- Official evaluator:
  - `python -m swebench.harness.run_evaluation`
  - `--max_workers 2`
  - `--cache_level env`
  - `--clean false`

Note: this run used `--cache_level env`, which keeps environment-level cache but
does not reliably preserve every large instance image needed for fast
cross-repository reruns. Future repeated local runs should use
`--cache_level instance --clean false` and avoid Docker prune commands until the
benchmark series is finished.

## Official Result

| Arm | Submitted | Completed | Resolved | Unresolved | Empty patches | Errors | Pass rate |
|---|---:|---:|---:|---:|---:|---:|---:|
| Plain Codex | 20 | 20 | 12 | 8 | 0 | 0 | 60.0% |
| AgentMakefile Codex | 20 | 20 | 12 | 8 | 0 | 0 | 60.0% |

The aggregate pass rate is tied on this subset. The resolved set is not identical:

- Plain-only pass: `mwaskom__seaborn-2848`
- AgentMakefile-only pass: `django__django-10924`

## Generation Cost

| Arm | Patch generation tokens | Delta vs plain |
|---|---:|---:|
| Plain Codex | 1,084,697 | baseline |
| AgentMakefile Codex | 1,016,563 | -68,134 (-6.3%) |

AgentMakefile used a larger explicit prompt bundle for each task, but the generated interaction consumed fewer total Codex CLI tokens on this run. The stable harness prefix was identical across the 20 cases, with stable prefix hash `sha256:62342c08614ccdc8fde3d1aa77df866bc4d40716f0aaa7653cf36c10c48244b0`.

Prompt bundle size before model execution:

| Arm | Total approximate prompt tokens |
|---|---:|
| Plain prompt files | 11,244 |
| AgentMakefile prompt files | 57,408 |

## Per-Instance Result

| # | Instance | Repo | Plain | AgentMF | Plain tokens | AgentMF tokens | Delta |
|---:|---|---|---|---|---:|---:|---:|
| 1 | `astropy__astropy-12907` | `astropy/astropy` | pass | pass | 53,935 | 39,712 | -14,223 |
| 2 | `django__django-10914` | `django/django` | pass | pass | 31,934 | 25,665 | -6,269 |
| 3 | `matplotlib__matplotlib-18869` | `matplotlib/matplotlib` | fail | fail | 52,807 | 48,622 | -4,185 |
| 4 | `mwaskom__seaborn-2848` | `mwaskom/seaborn` | pass | fail | 66,625 | 50,355 | -16,270 |
| 5 | `pallets__flask-4045` | `pallets/flask` | fail | fail | 68,559 | 40,207 | -28,352 |
| 6 | `psf__requests-1963` | `psf/requests` | pass | pass | 70,717 | 51,489 | -19,228 |
| 7 | `pydata__xarray-3364` | `pydata/xarray` | fail | fail | 87,675 | 57,692 | -29,983 |
| 8 | `pylint-dev__pylint-5859` | `pylint-dev/pylint` | pass | pass | 37,061 | 51,417 | +14,356 |
| 9 | `pytest-dev__pytest-11143` | `pytest-dev/pytest` | pass | pass | 57,611 | 58,111 | +500 |
| 10 | `scikit-learn__scikit-learn-10297` | `scikit-learn/scikit-learn` | pass | pass | 31,222 | 28,866 | -2,356 |
| 11 | `sphinx-doc__sphinx-10325` | `sphinx-doc/sphinx` | pass | pass | 75,377 | 39,150 | -36,227 |
| 12 | `sympy__sympy-11400` | `sympy/sympy` | fail | fail | 39,576 | 53,352 | +13,776 |
| 13 | `astropy__astropy-14182` | `astropy/astropy` | pass | pass | 39,263 | 90,789 | +51,526 |
| 14 | `astropy__astropy-14365` | `astropy/astropy` | fail | fail | 34,436 | 79,489 | +45,053 |
| 15 | `astropy__astropy-14995` | `astropy/astropy` | pass | pass | 45,925 | 70,029 | +24,104 |
| 16 | `astropy__astropy-6938` | `astropy/astropy` | pass | pass | 47,866 | 32,834 | -15,032 |
| 17 | `astropy__astropy-7746` | `astropy/astropy` | fail | fail | 31,283 | 54,345 | +23,062 |
| 18 | `django__django-10924` | `django/django` | fail | pass | 100,077 | 38,195 | -61,882 |
| 19 | `django__django-11001` | `django/django` | pass | pass | 37,054 | 43,307 | +6,253 |
| 20 | `django__django-11019` | `django/django` | fail | fail | 75,694 | 62,937 | -12,757 |

## Artifacts

- Subset manifest: `/tmp/agentmf-swebench-ab/cross-repo-20-manifest.json`
- Subset JSONL: `benchmarks/swebench-lite-cross-repo-20.jsonl`
- AgentMakefile harness export: `/tmp/agentmf-swebench-ab/agentmf-cross-repo-20-harnesses.jsonl`
- Plain predictions: `/tmp/agentmf-swebench-ab/plain-predictions.jsonl`
- AgentMakefile predictions: `/tmp/agentmf-swebench-ab/agentmf-predictions.jsonl`
- Plain official report: `/tmp/agentmf-swebench-ab/plain-codex-gpt-5.5.plain-cross-repo-20.json`
- AgentMakefile official report: `/tmp/agentmf-swebench-ab/agentmf-codex-gpt-5.5.agentmf-cross-repo-20.json`

## Interpretation

This run does not show a pass-rate win for AgentMakefile on the 20-instance subset; it shows parity in official pass rate with a different resolved set and lower total generation tokens. That is useful but not sufficient evidence for quality improvement.

The strongest supported claims from this run are:

- AgentMakefile can export and execute a real cross-repository SWE-bench Lite harness bundle end to end.
- The selected harness did not reduce official pass rate on this subset.
- The selected harness changed behavior enough to swap one resolved instance.
- Despite a larger explicit prompt prefix, total Codex CLI token usage was lower in this run.

The next useful benchmark step is a larger paired run, ideally 50+ stratified instances, with repeated seeds or multiple generation attempts if the host supports deterministic sampling controls.
