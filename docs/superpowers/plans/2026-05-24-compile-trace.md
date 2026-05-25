# Compile Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `agentmf compile --trace` so compiler phases and generated file decisions are visible in text and JSON output.

**Architecture:** Add a small trace event model to `compiler.py`, record events during compile phases, and expose them through `CompileResult`. The CLI decides whether to print trace output based on `--trace`; the compiler can stay deterministic and testable without depending on stdout.

**Tech Stack:** Python 3.9, dataclasses, argparse, pytest.

---

### Task 1: Compiler Trace Model

**Files:**
- Modify: `src/agentmf/compiler.py`
- Test: `tests/test_agentmf.py`

- [x] **Step 1: Write failing test**

Add a test that calls:

```python
compile_agentmakefile(KARPATHY_DEMO, targets=["agents-md"], trace=True)
```

Expected trace phases:

```text
start
load_source
select_targets
normalize_ir
emit_backend
finish
```

- [x] **Step 2: Run targeted test and confirm failure**

Run:

```bash
PYTHONPATH=src python3 -m pytest tests/test_agentmf.py::test_compile_trace_records_phases -q
```

Expected: fail because `trace` is not yet accepted or populated.

- [x] **Step 3: Implement minimal trace model**

Add:

```python
@dataclass
class TraceEvent:
    phase: str
    message: str
    data: dict[str, object] = field(default_factory=dict)
```

Add `trace: list[TraceEvent]` to `CompileResult`.

- [x] **Step 4: Record compiler phases**

Record load, target selection, normalization, backend emission, write decisions, and finish.

- [x] **Step 5: Run targeted test and confirm pass**

Run the targeted test again.

### Task 2: CLI Text Trace Output

**Files:**
- Modify: `src/agentmf/cli.py`
- Test: `tests/test_agentmf.py`

- [x] **Step 1: Write failing test**

Call:

```python
main(["compile", "--file", str(KARPATHY_DEMO), "--target", "agents-md", "--trace"])
```

Assert stdout contains:

```text
Trace:
  start
  load_source
  emit_backend
```

- [x] **Step 2: Implement text trace formatting**

Only print trace when `--trace` is present.

- [x] **Step 3: Verify targeted test passes**

### Task 3: CLI JSON Trace Output

**Files:**
- Modify: `src/agentmf/cli.py`
- Test: `tests/test_agentmf.py`

- [x] **Step 1: Write failing test**

Call:

```python
main(["compile", "--file", str(KARPATHY_DEMO), "--target", "agents-md", "--trace", "--format", "json"])
```

Assert JSON includes a `trace` array with structured events.

- [x] **Step 2: Implement JSON trace output**

Include trace only when `--trace` is set.

- [x] **Step 3: Verify targeted test passes**

### Task 4: Full Verification

**Files:**
- No production changes unless failures reveal gaps.

- [x] Run:

```bash
PYTHONPATH=src python3 -m pytest -q
python3 -m compileall -q src
zsh -lc 'agentmf compile --file demos/karpathy/AgentMakefile --target agents-md --trace'
```

- [x] Update README or docs only if user-facing behavior needs clarification.
