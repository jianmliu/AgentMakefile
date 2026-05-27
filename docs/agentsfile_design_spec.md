# AgentMakefile Design Spec

## 1. Overview

**AgentMakefile** is a portable agent harness specification, compiler, and host adapter layer. It defines reusable skills, policies, targets, permissions, hooks, output contracts, validation rules, and fallback behavior once, then compiles them into platform-native artifacts or request-time harness payloads for Claude Code, OpenCode, Codex, Cursor, and future agent runtimes.

At runtime, most platform-native instruction artifacts ultimately become part of a prompt prefix. `AGENTS.md`, `CLAUDE.md`, `.cursor/rules/*.mdc`, `SKILL.md`, and runtime-specific rule files are different packaging formats for stable agent guidance that is prepended to task-specific context. AgentMakefile treats those prompt prefixes as build artifacts produced from structured inputs.

Static generated files are the compatibility layer. The deeper integration point is harness-driven prompt-prefix assembly from AgentMakefile IR: a host adapter or runtime can select the current task target, resolve dependencies, choose the required policies and skills, reuse stable prefix chunks, and append volatile task context immediately before the model call.

The near-term goal is **not** to build another coding agent runtime. Instead, AgentMakefile acts as a **single portable harness source of truth** for agent skills and rails, similar to how an API specification can act as the source for generated SDKs, CLIs, documentation, or MCP servers. A standalone `agentmf` runtime remains a later optional path built on the same harness IR and payload contracts.

AgentMakefile supports two complementary source-of-truth modes:

* **Forward compilation**: teams maintain AgentMakefile directly, then compile
  it into platform-native instructions and skill packages.
* **Reverse guidance import**: a plugin or host scans existing prompt guidance
  such as `SKILL.md`, `AGENTS.md`, `CLAUDE.md`, `skills/index.md`, Cursor rules,
  or similar host-native instruction files into a generated AgentMakefile
  guidance-index module. AgentMakefile target selection, dependency closure,
  and `selection_trace` can then optimize which skills or instruction fragments
  are loaded for a request.

The reverse import path is a major feature, not only a migration helper. It lets
existing skill and instruction ecosystems keep their current package layout
while gaining a structured dependency graph, deterministic prompt fragments,
explainable selection, and cross-platform outputs.

For large skill ecosystems such as OpenClaw, reverse import should be modular
from the start. A local importer can scan `**/SKILL.md`, preserve category and
source metadata, generate one AgentMakefile per category, generate a root
AgentMakefile index, and export curator evidence such as duplicate original
skill names. This keeps thousands of skills reviewable and selectable without
forcing a flat all-in-one index.

AgentMakefile also supports a future evidence-driven evolution loop for large
skill ecosystems. Selection traces, benchmark reports, registry metadata, and
user corrections can be collected as evidence, turned into reviewable
AgentMakefile candidate patches, compiled in isolation, evaluated, and promoted
only after explicit review. This Skill Workshop / Dream Mode direction is
specified in [agentmf_evolution_skill_workshop_spec.md](agentmf_evolution_skill_workshop_spec.md).

In the same way that a `Makefile` tells a build system how to produce targets from dependencies, an `AgentMakefile` tells agent harnesses how to assemble task-specific behavior and enforce project-specific guardrails. Each target defines a **compilable agent harness pipeline**: dependency closure, selected skills, policies, prompt operations, context rules, guards, permissions, fallbacks, and output contracts. It is not a traditional shell recipe. This also gives AgentMakefile a path to avoid unnecessary recompilation: unchanged modules, targets, skills, and backend settings should be reusable across builds, while only affected prompt-prefix artifacts are regenerated.

The top-level harness architecture is specified in [agentmf_agent_harness_architecture.md](agentmf_agent_harness_architecture.md).

Concise positioning:

> **AgentMakefile is a portable agent harness specification and compiler.**

Expanded positioning:

> **AgentMakefile brings the SDK-generation model to agent behavior: define reusable skills, policies, permissions, hooks, and output contracts once, then compile them into cache-friendly prompt prefixes and each agent platform's native format.**

Short slogans:

> **Write agent skills once. Compile everywhere.**

> **Source once. Skill everywhere.**

---

## 1.1 Terminology

* **AgentMakefile**: the cross-platform source format and default project rule file.
* **Agent harness**: the layer that turns stable guidance, user intent,
  runtime context, and host capabilities into a selected prompt payload and
  execution contract for an agent host.
* **agentmf**: the CLI compiler and validator for AgentMakefile.
* **Agent Rule IR**: the normalized intermediate representation produced from AgentMakefile before backend emission.
* **Backend**: a platform-specific emitter that generates native artifacts for Claude Code, Codex, Cursor, OpenCode, or another agent runtime.
* **Generated artifact**: a platform-native output such as `CLAUDE.md`, `AGENTS.md`, `.cursor/rules/*.mdc`, `SKILL.md`, `.claude/settings.json`, hooks, or OpenCode configuration.
* **Prompt prefix artifact**: generated guidance that is expected to appear before volatile task context in a model request, either directly as prompt text or indirectly through a platform-native file such as `AGENTS.md`, `CLAUDE.md`, Cursor rules, or `SKILL.md`.
* **Target pipeline**: the structured harness pipeline defined by a target:
  dependency closure, selected skills, policies, prompt operations, context
  selection, guards, permission contracts, fallback behavior, and output
  contracts.
* **Target fragment**: a small, target-specific prompt prefix artifact generated from one target's dependency closure. A target fragment is analogous to a compiled object file: it can be regenerated independently, cached by hash, and linked with other fragments at request time.
* **Prompt object**: a compiled fragment of stable prompt-prefix material. Prompt objects may represent targets, policies, skills, permissions, output contracts, or reusable modules.
* **Prompt link step**: the runtime or compiler phase that selects prompt objects for a request and concatenates them into the final prompt prefix before volatile task context is appended.
* **artifacts**: backend-specific generated artifact configuration, such as output paths, frontmatter, or managed-block behavior.
* **output_format**: a response or skill output contract, such as required sections or final answer shape.
* **Soft rail**: a rule compiled into instructions, checklists, or generated guidance. It relies on the target agent to follow it.
* **Hard rail**: a rule enforced by a runtime, permission system, hook, sandbox, or tool-call interceptor.

---

## 2. Motivation

Current coding-agent rule systems are fragmented across multiple files and platforms:

* `CLAUDE.md`
* `AGENTS.md`
* `.cursor/rules`
* OpenCode agent configs
* permission settings
* lifecycle hooks
* skill directories
* project-specific markdown instructions

Most of these systems are based on natural-language instructions such as:

> When the user asks for X, do Y.

This works for simple tasks but becomes fragile when tasks require:

* Multiple ordered steps
* Skill composition
* Dependency resolution
* Tool routing
* Command permissions
* Lifecycle hooks
* Quality checks
* Safety checks
* Output schema enforcement
* Fallback behavior
* Incremental execution
* Project-specific overrides
* Cross-agent portability

Makefile provides a useful abstraction because it separates:

* **What needs to be done**: target
* **What must exist first**: dependencies
* **How to do it**: commands
* **When to skip or rerun**: timestamps / cache
* **How to organize reusable workflows**: phony targets, variables, includes, pattern rules

AgentMakefile adapts these ideas for AI agents and adds a compiler layer so the same source file can generate native skills, rules, instructions, permissions, hooks, and rails for multiple agent ecosystems.

For prompt construction, the useful build-system split is:

* **Stable prefix inputs**: AgentMakefile sources, included modules, skill definitions, policy packs, permission rules, backend settings, and compiler version.
* **Stable prefix outputs**: deterministic prompt-prefix artifacts such as `AGENTS.md`, `CLAUDE.md`, `SKILL.md`, Cursor rules, or runtime-native instruction payloads.
* **Volatile suffix inputs**: the current user request, active files, current diff, tool observations, and runtime state.

Keeping the stable prefix deterministic and ahead of volatile task context improves prompt-cache hit rates and lets runtimes avoid reloading unrelated rules.

The intermediate representation can also be lowered into **target fragments**: small Markdown or runtime-native prompt objects such as:

```text
.agentmf/fragments/agents/code.review.md
.agentmf/fragments/agents/code.change.md
.agentmf/fragments/agents/repo.security_review.md
.agentmf/fragments/claude/code.review.md
```

These fragments are not the final all-in-one `AGENTS.md` or `CLAUDE.md`. They are compiled prompt objects. Each one should contain only the target's resolved dependency closure: the target, inherited fields, relevant policies, relevant skills, permission guidance, guards, steps, and output contracts. A runtime can then load only the fragments needed for the current request.

A useful analogy is the API tooling model: an OpenAPI-like source can generate SDKs, CLIs, documentation, or MCP servers. AgentMakefile applies a similar source-to-artifact model to agent behavior:

```text
API spec
  ↓
SDK / CLI / MCP server / docs

AgentMakefile
  ↓
Claude SKILL.md / Codex skill / AGENTS.md / CLAUDE.md / Cursor rules / OpenCode config

Existing SKILL.md tree
  ↓
Generated AgentMakefile skill-index module
  ↓
Explainable plugin payload / selected skills / cross-platform skill artifacts
```

In this analogy, AgentMakefile is not the runtime. It is the source format and compiler toolchain for portable agent skills and rails.

---

## 3. Design Goals

### 3.1 Declarative

Rules should describe desired behavior and execution structure without hardcoding all implementation details.

### 3.2 Composable

Small skills should be reusable and combinable into larger workflows.

### 3.3 Auditable

The rule graph should make it clear why an agent chose a specific path, tool, permission, hook, or output format.

### 3.4 Deterministic Where Possible

For repeatable tasks, the agent should follow the same dependency graph and validation sequence.

### 3.5 Flexible Where Needed

The agent can still use reasoning, tool selection, and language generation inside controlled rule boundaries.

### 3.6 Human-readable

The file should be easy to understand for engineers, prompt designers, and domain experts.

### 3.7 Tool-agnostic

AgentMakefile should not depend on a single agent framework. It should be usable with Claude Code, OpenCode, Codex, Cursor, local agents, LangGraph-based systems, MCP-based systems, or custom orchestration systems.

### 3.8 Portable Compilation

AgentMakefile should compile into existing agent-native rule formats instead of requiring users to abandon their current tools.

Examples:

* `CLAUDE.md`
* Claude Code settings, permissions, hooks, and skills
* OpenCode agent and permission configs
* Codex `AGENTS.md` and skills
* Cursor rules
* Generic markdown rule files

### 3.9 Single Source of Truth

Project teams should be able to define agent rails once and generate platform-specific rule files from the same source.

### 3.10 Runtime Optional

AgentMakefile should be useful even without a dedicated runtime. The MVP can work as a validator and compiler. A future runtime can enforce hard rails through tool interception, sandboxing, and approval gates.

---

## 4. Non-goals

AgentMakefile is not intended to be:

* A full programming language
* A replacement for Claude Code, OpenCode, Codex, Cursor, or other coding agents
* A replacement for LangGraph or workflow engines
* A replacement for safety policy systems such as OPA
* A replacement for code execution pipelines such as Dagger
* A prompt-only instruction file
* A fixed standard for all agent behavior

Instead, it is a lightweight orchestration, rails, and compiler layer for agent skills and project-specific agent behavior.

---

## 5. Core Concepts

### 5.0 Concept Hierarchy

AgentMakefile uses a few related but distinct concepts:

```text
Target
  uses Policies
  references Skills
  defines Steps, Guards, Outputs, and Fallbacks

Policy
  groups reusable behavior rules
  may contain Steps and Guards

Skill
  is a reusable procedural unit
  may compile into SKILL.md or platform-native skill packages

Guard
  constrains behavior before, during, or after execution

Permission
  controls tool/action access using allow / ask / deny

Hook
  attaches behavior to lifecycle events such as before_tool_call or after_file_edit

Validation
  checks generated responses, files, or artifacts against output contracts

Backend
  lowers the normalized IR into platform-native artifacts
```

This hierarchy prevents overlap between high-level behavior rules and enforcement mechanisms. For example, a policy may say `do_not_run_untrusted_code`, a permission may deny `npm install*`, and a hook may block the tool call before execution.

### 5.1 Target

A **target** represents a user-facing goal, internal workflow, or compilable
agent behavior unit. In harness terms, a target is a compiled pipeline boundary:
it packages the dependency closure, selected skills, policies, prompt
operations, context selection, guards, permissions, fallback behavior, and
output contracts needed for one task class.

Examples:

* `rubric.review`
* `email.polish`
* `repo.security_review`
* `code.review`
* `research.summarize`
* `document.generate`

A target can be concrete or phony.

A concrete target produces an artifact or durable output.

A phony target represents a workflow or behavior, similar to `.PHONY` in Makefile.

---

### 5.2 Match

The **match** block defines when a target applies.

In **compiler-only mode**, `match` is descriptive metadata used to generate skill triggers, documentation, rule descriptions, and platform-native instructions. The compiler does not need to understand natural-language intent at compile time.

In **runtime mode**, `match` can be used by a target selector to route a live user request to the most relevant target or skill.

The initial selector should remain deterministic and explainable. It may use
layered matching before reporting no match:

* raw substring matching against `match` terms
* normalized matching for case, punctuation, underscores, and hyphenation
* built-in translation or alias expansion for common development intents
* lightweight semantic token overlap with canonicalized terms

Every non-exact match should be reflected in `selection_trace` so a host can
see whether a target was selected by `substring`, `normalized_substring`,
`translated_substring`, or `semantic_token_overlap`.

A target selector may also derive target candidates from the `match` blocks of
skills referenced by a target. This lets reusable framework modules compile
multiple native skills and still route a request to the target that packages the
matching skill set. Skill-derived trace entries should identify their source
skill, and direct target matches should win over skill-derived matches before
priority and score are used to rank candidates within each group.

Matching may use:

* User intent
* Keywords
* Input type
* File type
* Domain
* Tool availability
* Project context
* Explicit command

Example:

```yaml
match:
  user_intent:
    - check rubric
    - validate rubric
    - count true false
  input_type:
    - text
```

---

### 5.3 Inputs

The **inputs** block defines what context is required or optional.

Example:

```yaml
inputs:
  required:
    - rubric_text
  optional:
    - prompt_text
    - model_response
    - project_rules
```

If required inputs are missing, the target may:

* Ask a clarification question
* Infer from context
* Fall back to partial execution
* Report that the task is blocked

---

### 5.4 Dependencies

The **deps** block defines prerequisite skills, checks, or context-gathering steps.

In compiler-only mode, dependencies are advisory metadata that can be rendered into generated procedures or documentation. In runtime mode, dependencies can become executable prerequisite checks or target graph edges.

Example:

```yaml
deps:
  - rubric.parse
  - rubric.schema_check
  - rubric.human_rating_count
```

Dependencies can be:

* Skill targets
* Tool calls
* Validation checks
* Context retrieval steps
* File parsing steps
* Safety checks

---

### 5.5 Steps

The **steps** block defines ordered harness operations. Steps can be rendered as
natural-language instructions, compiled into skill procedures, mapped to
workflow nodes, converted into prompt operations, or implemented as runtime
actions.

Example:

```yaml
steps:
  - name: parse
    action: parse_json
  - name: validate_schema
    action: check_required_keys
  - name: count_ratings
    action: count_human_rating
  - name: report
    action: produce_summary
```

Steps are similar to Makefile commands only at the graph level: they are the
ordered operations attached to a target. They are not shell recipes. In
AgentMakefile, a step should describe a harness operation such as selecting
context, linking a prompt fragment, invoking a skill, checking a guard,
declaring a permission, running an allowed tool, applying a fallback, or
validating an output contract.

---

### 5.6 Guards

**Guards** are constraints applied before, during, or after execution. Guards may be soft or hard.

* **Soft guards** compile into instructions, checklists, output requirements, or skill procedures.
* **Hard guards** require runtime enforcement through permissions, hooks, tool-call interception, sandboxing, or human approval gates.

Examples:

```yaml
guards:
  - preserve_user_format
  - do_not_invent_missing_fields
  - validate_output_before_response
```

Example with hard enforcement:

```yaml
guards:
  - name: block_untrusted_install
    enforcement: hard
    when:
      tool: bash
      command_matches:
        - "npm install*"
        - "pnpm install*"
        - "yarn install*"
    action: deny
```

---

### 5.7 Permissions

Permissions define allow / ask / deny behavior for tools, commands, file access, network access, browser actions, or other runtime capabilities.

Preferred syntax:

```yaml
permissions:
  defaults:
    bash: ask
    file_read: ask
    file_write: ask
    browser: ask
  rules:
    bash:
      "git status": allow
      "npm install*": deny
      "rm -rf *": deny
    file_read:
      ".env": deny
```

The source schema should also accept the shorter form where tools appear directly under `permissions`. The compiler normalizes this syntactic sugar into explicit defaults and rules in the IR.

Permission patterns use shell-style glob matching by default. If multiple patterns match the same action, the most restrictive action wins:

```text
deny > ask > allow
```

If no rule matches, the default action is `ask` unless the tool has an explicit default.

This deterministic rule avoids backend-specific ambiguity such as first-match-wins behavior.

Short-form example:

```yaml
permissions:
  bash:
    "git status": allow
    "git diff*": allow
    "npm install*": deny
    "npm run*": ask
    "curl *": ask
    "rm -rf *": deny
    "*": ask

  file_read:
    ".env": deny
    "~/.ssh/**": deny
    "**/*secret*": deny

  browser:
    "connect_wallet": deny
    "sign_message": deny
    "approve_transaction": deny
```

Permissions are declarative. They can compile into Claude Code permissions, OpenCode permission settings, hooks, generated warnings, or custom runtime interceptors.

---

### 5.8 Hooks

Hooks define lifecycle-triggered behavior. They can run before or after tool calls, edits, tests, commits, or final responses.

Example:

```yaml
hooks:
  before_tool_call:
    - name: require_approval_for_network
      when:
        tool: bash
        command_matches:
          - "curl *"
          - "wget *"
      action: ask

  after_file_edit:
    - name: run_formatter
      action: run
      command: "npm run format"
      on_error: report
```

Hooks can compile into native hook systems where available, or into generated policy instructions where unavailable.

---

### 5.9 Output Contract

The **output_format** block defines the required final response or skill output structure.

Do not confuse `output_format` with `artifacts`:

* `output_format` describes what the agent should return or include.
* `artifacts` describes where generated platform files should be emitted.

Example:

```yaml
output_format:
  - schema_status
  - issue_list
  - true_false_count
```

For strict tasks, this can include JSON schemas.

Example:

```yaml
output_schema:
  type: object
  required:
    - valid
    - errors
    - summary
```

---

### 5.10 Fallback

The **fallback** block defines what happens when a step fails.

Example:

```yaml
fallback:
  on_parse_error:
    - report_json_error
    - do_not_guess_structure
  on_missing_input:
    - proceed_with_partial_analysis
    - state_limitation
```

Fallback behavior is important because agent tasks often involve incomplete, ambiguous, or malformed inputs.

---

### 5.11 Variables

Variables define reusable values.

Example:

```yaml
vars:
  RUBRIC_REQUIRED_KEYS:
    - description
    - sources
    - justification
    - weight
    - human_rating
    - criterion_type
    - dependent_criteria
    - gemini_as_autorater_rating
    - gpt_as_autorater_rating
```

Variables can be referenced inside rules.

Example:

```yaml
steps:
  - action: check_required_keys
    using: ${RUBRIC_REQUIRED_KEYS}
```

---

### 5.12 Includes and Composition

Includes allow modular rule files, similar to Makefile `include`. They should support more than simple file splitting: included files can provide reusable policy packs, skill packs, permission packs, targets, variables, hooks, output contracts, and compiler hints.

Example:

```yaml
include:
  - skills/email.yml
  - skills/rubric.yml
  - skills/hardware.yml
  - policies/safety.yml
  - policies/tool_use.yml
```

This enables project-level, team-level, and organization-level reuse.

### Include Types

AgentMakefile should support multiple include scopes:

```yaml
include:
  - path: policies/karpathy.yml
    as: karpathy

  - path: policies/security.yml
    as: security

  - path: skills/rubric.yml
    as: rubric
```

The optional `as` field provides a namespace to avoid name collisions.

Example after namespacing:

```yaml
targets:
  code.task:
    policies:
      - karpathy.think_before_coding
      - karpathy.simplicity_first
      - security.no_secret_exfiltration
```

### Include Precedence

AgentMakefile should define deterministic merge order.

Recommended precedence from lowest to highest:

1. Built-in defaults
2. Organization-level includes
3. Team-level includes
4. Project-level includes
5. Local `AgentMakefile`
6. Explicit CLI overrides
7. Explicit user instruction at runtime

Later layers may override earlier layers unless a rule is marked as locked.
Runtime user instructions may tighten behavior or request a temporary override, but they must not silently weaken locked safety or organization policies. Any permitted weakening of a locked rule should require explicit approval and trace output.

Example:

```yaml
policies:
  security.no_secret_exfiltration:
    locked: true
```

A locked policy cannot be weakened by a lower-trust local include, local project rule, CLI override, or ordinary runtime instruction.

### Merge Semantics

Different objects should merge differently:

| Object type      | Default merge behavior                                         |
| ---------------- | -------------------------------------------------------------- |
| `vars`           | shallow merge; later values override earlier values            |
| `targets`        | merge by target name; local definitions can extend or override |
| `policies`       | merge by policy name; locked policies cannot be weakened       |
| `permissions`    | most restrictive rule wins by default                          |
| `hooks`          | append in deterministic order unless explicitly replaced       |
| `output_format`  | append or override depending on target-level setting           |
| `compiler_hints` | backend-specific override                                      |

Example:

```yaml
targets:
  code.task:
    extends: karpathy.code.task
    add_policies:
      - security.no_secret_exfiltration
    override:
      priority: 80
```

### Rule Packages

Reusable includes can be published as rule packages.

Example package structure:

```text
agentmake-packages/
  karpathy-guidelines/
    AgentMakefile.yml
    README.md
  crypto-security/
    AgentMakefile.yml
    hooks/
      block-wallet-signing.sh
  python-project/
    AgentMakefile.yml
```

Future package syntax:

```yaml
include:
  - package: karpathy-guidelines
    version: ^0.1
  - package: crypto-security
    version: ^0.2
```

Remote package support should be optional and disabled by default for security-sensitive environments.
The initial compiler should reject `package` includes until provenance, lockfiles, checksums, and trusted registries are defined.

### Composition Patterns

AgentMakefile should support a few common composition patterns.

#### 1. Extending a Target

```yaml
targets:
  code.review:
    extends: karpathy.code.task
    add_steps:
      - action: inspect_security_sensitive_files
    add_output_format:
      - security_risks
```

#### 2. Composing Multiple Policies

```yaml
targets:
  repo.security_review:
    policies:
      - karpathy.surgical_changes
      - security.no_secret_exfiltration
      - security.no_untrusted_install
      - crypto.no_wallet_signing
```

#### 3. Permission Overlay

```yaml
include:
  - path: policies/default-permissions.yml
  - path: policies/crypto-hardening.yml

permissions:
  bash:
    "npm install*": deny
```

The local rule tightens the default permission model.

#### 4. Backend-Specific Overrides

```yaml
compiler_hints:
  claude-code:
    emit_hooks: true
  cursor:
    alwaysApply: true
  codex:
    emit_skills: true
```

### Include Graph Validation

The compiler should validate the include graph and detect:

* Missing include files
* Circular includes
* Duplicate target names without explicit merge behavior
* Conflicting permission rules
* Attempts to weaken locked policies
* Remote includes without approval

This makes AgentMakefile closer to Makefile's compositional model while retaining safety properties required for agent rails.

---

### 5.13 Pattern Rules

Pattern rules define generalized behavior for a class of tasks.

Pattern rules are an advanced feature and are **not required for MVP 0 or MVP 1**. They should be treated as future-facing until the core source-to-artifact compiler is stable.

Example:

```yaml
patterns:
  "*.rubric.review":
    match:
      contains:
        - criterion
        - human_rating
    deps:
      - parse_json
      - validate_schema
    output_format:
      - summary
      - errors
      - rating_count
```

This is similar to Makefile pattern rules such as:

```makefile
%.o: %.c
	gcc -c $<
```

---

### 5.14 Compiler Backend

A compiler backend transforms AgentMakefile rules into a target agent runtime format.

Examples:

```yaml
compile:
  targets:
    - claude-md
    - agents-md
    - cursor-rule
    - claude-skill
    - codex-skill
    - skills-index
```

Each backend decides how to lower targets, guards, permissions, hooks, skills, and output contracts into platform-native files.

---

## 6. File Structure

Recommended project structure:

```text
.agentmake/
  AgentMakefile.yml
  skills/
    email.yml
    rubric.yml
    coding.yml
    research.yml
    document.yml
  policies/
    safety.yml
    style.yml
    tool_use.yml
    citation.yml
  schemas/
    rubric.schema.json
    output.schema.json
  cache/
    index.json
```

The main file may be named:

* `AgentMakefile`
* `AgentMakefile.yml`
* `AgentMakefile.yaml`
* `.agentmake/AgentMakefile.yml`

Recommended default:

```text
AgentMakefile
```

Recommended file lookup order:

```text
./AgentMakefile
./AgentMakefile.yml
./AgentMakefile.yaml
./.agentmake/AgentMakefile
./.agentmake/AgentMakefile.yml
```

---

## 7. Syntax Overview

A minimal target:

```yaml
targets:
  email.polish:
    match:
      user_intent:
        - polish email
        - rewrite email
    inputs:
      required:
        - draft_text
    steps:
      - action: preserve_intent
      - action: improve_fluency
      - action: produce_ready_to_send_email
```

A full target:

```yaml
targets:
  rubric.review:
    phony: true
    description: Review a rubric for syntax, schema, alignment, and human_rating counts.
    match:
      user_intent:
        - check rubric
        - validate rubric
        - count true false
    inputs:
      required:
        - rubric_text
      optional:
        - prompt_text
        - model_response
    deps:
      - rubric.parse
      - rubric.schema_check
      - rubric.rating_count
    steps:
      - name: parse
        action: parse_json
        on_error: report_parse_error
      - name: schema_check
        action: check_required_keys
        using: ${RUBRIC_REQUIRED_KEYS}
      - name: type_check
        action: check_allowed_values
        field: criterion_type
        using: ${RUBRIC_ALLOWED_TYPES}
      - name: count
        action: count_human_rating
      - name: report
        action: produce_review_summary
    guards:
      - do_not_modify_rubric_unless_requested
      - do_not_invent_missing_fields
    output_format:
      - json_validity
      - schema_errors
      - true_count
      - false_count
      - null_count
    fallback:
      on_parse_error:
        - explain_invalid_json
        - point_to_first_error_if_available
```

---

## 8. Execution and Compilation Model

AgentMakefile supports two related modes:

1. **Compiler mode**: generate platform-native rule files.
2. **Runtime mode**: directly enforce rules through a wrapper, tool interceptor, or sandbox.

The initial product should focus on compiler mode. Runtime mode is optional and future-facing.

Compiler mode sequence:

```text
AgentMakefile
  ↓
Parser
  ↓
Schema validation
  ↓
Agent Rule IR
  ↓
Backend compiler
  ↓
Generated native files
```

Runtime mode sequence:

```text
User request
  ↓
Load AgentMakefile rules
  ↓
Intent matching
  ↓
Target selection
  ↓
Dependency resolution
  ↓
Input validation
  ↓
Guard pre-checks
  ↓
Tool-call interception
  ↓
Step execution
  ↓
Output validation
  ↓
Fallback handling if needed
  ↓
Final response
```

---

## 8.1 Compile Targets, Outputs, and CLI Selection

`compile.targets` defines the default backend list when the user runs `agentmf compile`.

`agentmf compile --all` ignores `compile.targets` and compiles every backend supported by the installed `agentmf` version. This is mainly useful for compatibility testing.

`--all` and `--target` are mutually exclusive. Passing both should be a validation error.

`artifacts.<backend>` defines optional backend-specific output configuration such as file path, frontmatter, or managed-block behavior.

For backward compatibility during early drafts, `outputs.<backend>` may be treated as an alias for `artifacts.<backend>`, but `artifacts` is the preferred name because it avoids confusion with `output_format`.

If the same backend key appears in both `artifacts` and deprecated `outputs`, the compiler should report a validation error rather than choosing one silently.

Explicit CLI selection overrides the default backend list.

Recommended semantics:

```bash
agentmf compile
# compile the backends listed in compile.targets

agentmf compile --all
# compile every backend supported by the installed agentmf version, ignoring compile.targets

agentmf compile --target claude-md
# compile only claude-md, regardless of compile.targets

agentmf compile --target claude-md --target cursor-rule
# compile only the explicitly selected targets
```

If `artifacts.<backend>` is absent, the backend should use its default output path. If no safe default exists, the compiler should report an error.

If `compile.targets` is absent, the MVP 0 default backend set is:

```text
claude-md
agents-md
cursor-rule
```

This makes a minimal AgentMakefile useful without requiring explicit backend configuration.

---

## 8.2 Generated File Ownership

Generated artifacts must be safe to regenerate without destroying user-authored content.

Default behavior:

* `agentmf compile` performs a dry run and prints the files it would generate.
* `--write` is required to write files.
* Existing files are not overwritten unless they are fully managed by `agentmf` or `--force` is provided.
* For shared files such as `CLAUDE.md` and `AGENTS.md`, the compiler should use managed blocks or generate separate files.

Recommended managed block format:

```markdown
<!-- BEGIN GENERATED BY agentmf -->
...
<!-- END GENERATED BY agentmf -->
```

Recommended safe output behavior:

| Output type                 | Default behavior                                             |
| --------------------------- | ------------------------------------------------------------ |
| `CLAUDE.md`                 | update managed block only, or generate `CLAUDE.generated.md` |
| `AGENTS.md`                 | update managed block only, or generate `AGENTS.generated.md` |
| `.cursor/rules/*.mdc`       | generate dedicated file                                      |
| `.claude/skills/*/SKILL.md` | generate dedicated skill directory                           |
| `.codex/skills/*/SKILL.md`  | generate dedicated skill directory                           |
| hooks                       | generate dedicated hook files, require `--write` and warning |
| settings files              | patch managed section only, or require explicit confirmation |

This ownership model is necessary because many target platforms already use human-authored project instruction files.

---

## 9. Agent Rule IR

AgentMakefile should compile into an intermediate representation before targeting specific platforms.

The IR avoids binding the source format to any one agent system.

Core IR objects:

```yaml
ir:
  targets:
    - name
    - match
    - deps
    - policies
    - skills
    - steps
    - guards
    - output_format
    - output_schema

  permissions:
    - tool
    - pattern
    - action: allow | ask | deny

  hooks:
    - event
    - condition
    - action

  skills:
    - name
    - qualified_name
    - namespace
    - description
    - implementation
    - match
    - steps
    - guards
    - output_format
    - output_schema

  policies:
    - name
    - applies_to
    - guards
    - steps
    - output_format
    - output_schema
```

Compilation path:

```text
AgentMakefile → Agent Rule IR → Claude Code / OpenCode / Codex / Cursor / Generic Markdown
```

---

## 10. Target Selection

In compiler-only mode, target priority is metadata. The compiler should validate that priorities are strict integers in the inclusive range `0..100` and render them into generated guidance when useful, but it does not perform live target selection.

In runtime mode, when multiple targets match a live user request, the target selector should resolve conflicts using priority.

Example:

```yaml
targets:
  email.polish:
    priority: 50

  email.reply:
    priority: 70

  user.explicit_format:
    priority: 100
```

Recommended priority order:

Locked safety and compliance policies are not ordinary target-selection candidates and should not be overridden by priority. They apply before normal target routing.

| Priority | Rule Type                         |
| -------: | --------------------------------- |
|      100 | Explicit user instruction         |
|       90 | Non-locked safety / compliance    |
|       80 | Tool-specific hard requirement    |
|       70 | Project-specific workflow         |
|       60 | Domain-specific skill             |
|       50 | Generic task skill                |
|       10 | Default style preference          |

---

## 11. Dependency Resolution

Dependencies should form a directed acyclic graph unless loops are explicitly allowed.

Example:

```yaml
targets:
  cuj.from_image:
    deps:
      - image.extract_text
      - cuj.normalize_prompt
      - cuj.validate_atomicity
```

The compiler/runtime should detect:

* Missing dependencies
* Circular dependencies
* Unavailable tools
* Failed prerequisite checks

---

## 12. Caching and Incremental Execution

AgentMakefile can support Makefile-like incremental behavior.

Caching is future-facing and is not required for MVP 0–2.

The main cache target is the compiled prompt prefix. AgentMakefile should be able to avoid rebuilding or reinjecting prefix content when its structured inputs have not changed. This is especially important because agent-native files such as `AGENTS.md`, `CLAUDE.md`, Cursor rules, and `SKILL.md` normally become prompt-prefix material before a model call.

Prompt-prefix caching should separate stable and volatile inputs:

```text
stable prefix:
  AgentMakefile
  included modules
  selected targets
  selected skills and policies
  permission and output contracts
  backend emitter version

volatile suffix:
  user request
  active file contents
  current diff
  tool outputs
  runtime observations
```

If only volatile inputs change, the compiler should not need to rebuild the stable prefix. If a module changes, only targets depending on that module should be invalidated. If the selected task target changes, unrelated target prefixes should remain reusable.

### 12.1 Prompt Fragment Object Model

AgentMakefile should treat target-specific prompt fragments like compiled object files.

At compile time:

```text
AgentMakefile source
  -> normalized Agent Rule IR
  -> target dependency closure
  -> prompt object fragments
  -> fragment manifest
```

At request time:

```text
user request
  -> target selection
  -> prompt object selection
  -> prompt link step
  -> final prompt prefix
  -> volatile task context
```

Each target fragment should be deterministic and content-addressed:

```text
fragment_hash = hash(
  compiler_version,
  backend_name,
  target_name,
  target_closure,
  selected_policy_hashes,
  selected_skill_hashes,
  permission_hashes,
  output_contract_hashes
)
```

If the fragment hash is unchanged, the compiler can skip regeneration. If a source module changes, only fragments whose dependency closure includes that module should be invalidated.

The fragment manifest should record enough dependency information for incremental rebuilds and runtime selection:

```yaml
fragments:
  agents/code.review.md:
    backend: agents
    target: code.review
    inputs:
      - AgentMakefile
      - modules/karpathy/AgentMakefile
      - modules/superpowers/AgentMakefile
    policies:
      - review_feedback_rigorously
      - verify_before_completion
    skills:
      - superpowers:receiving-code-review
    deps:
      - methodology.bootstrap
    hash: sha256:...
```

The all-in-one `AGENTS.md` and `CLAUDE.md` outputs remain useful compatibility artifacts. Target fragments are a lower-level build product that can reduce prompt size before full runtime-native AgentMakefile support exists.

The initial fragment backends are:

* `agents-fragments`: emits Markdown prompt objects under `.agentmf/fragments/agents/`.
* `claude-fragments`: emits Markdown prompt objects under `.agentmf/fragments/claude/`.

Each emitted fragment should be scoped to one normalized target and that target's dependency closure. Manifest generation, content-addressed skip decisions, and runtime link plans are separate layers built on top of these fragment outputs.

The initial manifest artifact is `.agentmf/fragments/manifest.json`. It records fragment path, backend, selected target, target dependency closure, source input paths, selected policy and skill names, compiler version, and a `sha256:` content hash. When writing artifacts, unchanged fragment files and unchanged manifests should be reported as unchanged and left untouched on disk.

The initial request-time bridge is a dry-run selector exposed as `agentmf select`. It can select fragments from explicit targets for deterministic integration tests or match a request against target `match` rules, choose the highest-priority matching target, resolve its dependency closure, and emit a stable JSON link plan. The selector does not assemble the final runtime prompt or execute any agent workflow; it only describes which compiled prompt objects a runtime should link.

Example:

```yaml
cache:
  rubric.schema_check:
    key:
      - hash(rubric_text)
      - version(RUBRIC_REQUIRED_KEYS)
    skip_if:
      - cache_hit
    invalidate_if:
      - rubric_text_changed
      - schema_version_changed
```

Use cases:

* Prompt-prefix reuse across repeated agent turns
* Target-specific rule loading to reduce token volume
* Backend-specific artifact reuse when only unrelated modules change
* Repeated rubric review
* Repeated file summarization
* Codebase analysis
* Long document drafting
* Research workflows

---

## 13. Skill Definition

A skill is a reusable unit of behavior.

Example:

```yaml
skills:
  rubric.schema_check:
    description: Validate rubric JSON object shape and required fields.
    inputs:
      required:
        - rubric_json
    steps:
      - action: check_top_level_object
      - action: check_criterion_keys
      - action: check_required_fields
      - action: check_allowed_values
    output_format:
      - is_valid
      - errors
```

A skill may be implemented by:

* Natural-language agent reasoning
* Tool call
* Script
* Function
* Workflow graph
* External API

Example with implementation:

```yaml
skills:
  json.parse:
    implementation:
      type: python
      entrypoint: scripts/parse_json.py
```

---

## 14. Tool Routing

Tool use can be declared inside steps.

Tool routing is advisory in compiler-only mode and enforceable only in runtime mode or in backends that support native tool routing.

Example:

```yaml
steps:
  - name: search_web
    action: tool.web_search
    when:
      - current_information_required
  - name: read_file
    action: tool.file_search
    when:
      - uploaded_file_referenced
```

Tool rules can also be centralized:

```yaml
tool_rules:
  web_search:
    required_when:
      - up_to_date_fact_needed
      - price_or_schedule_needed
      - current_law_or_policy_needed

  file_search:
    required_when:
      - user_references_uploaded_file
```

---

## 15. Output Validation

Targets may define validation requirements.

Example:

```yaml
validation:
  final_answer:
    must_include:
      - changed_files
      - test_result
      - risk_summary
    must_not_include:
      - unverified_claims
      - hidden_assumptions
```

For structured output:

```yaml
validation:
  json_output:
    schema: schemas/rubric_review_output.schema.json
```

---

## 16. Example: Rubric Review Rule

```yaml
version: 0.1

vars:
  RUBRIC_REQUIRED_KEYS:
    - description
    - sources
    - justification
    - weight
    - human_rating
    - criterion_type
    - dependent_criteria
    - gemini_as_autorater_rating
    - gpt_as_autorater_rating

  RUBRIC_ALLOWED_TYPES:
    - Reasoning
    - Extraction (recall)
    - Instruction Following
    - Safety
    - Multimodal Output
    - Pedagogy

  RUBRIC_ALLOWED_WEIGHTS:
    - Primary objective(s)
    - Not primary objective

targets:
  rubric.review:
    phony: true
    priority: 70
    match:
      user_intent:
        - check rubric
        - validate rubric
        - report true false
        - sync error
    inputs:
      required:
        - rubric_text
      optional:
        - prompt_text
        - model_response
    steps:
      - name: parse_json
        action: parse_json
        on_error: report_json_error
      - name: check_schema
        action: check_required_keys
        using: ${RUBRIC_REQUIRED_KEYS}
      - name: check_allowed_types
        action: check_allowed_values
        field: criterion_type
        using: ${RUBRIC_ALLOWED_TYPES}
      - name: check_allowed_weights
        action: check_allowed_values
        field: weight
        using: ${RUBRIC_ALLOWED_WEIGHTS}
      - name: count_human_rating
        action: count_values
        field: human_rating
        values:
          - true
          - false
          - null
      - name: report
        action: produce_summary
    guards:
      - do_not_change_rubric
      - do_not_invent_prompt_context
    output_format:
      - concise_summary
      - schema_issues_if_any
      - true_false_null_count
```

---

## 17. Example: Email Polish Rule

```yaml
targets:
  email.polish:
    phony: true
    priority: 50
    match:
      user_intent:
        - polish email
        - rewrite email
        - improve email
    inputs:
      required:
        - draft_text
    steps:
      - action: identify_intent
      - action: preserve_factual_content
      - action: improve_grammar
      - action: improve_tone
      - action: produce_ready_to_send_version
    guards:
      - do_not_add_unprovided_facts
      - do_not_over_expand
    output_format:
      - polished_email
```

---

## 18. Example: Unknown Repo Security Review

This example addresses a common attack pattern where a stranger asks a developer to clone a repository, run package install commands, share the full screen, connect a wallet, or sign messages.

```yaml
version: 0.1

targets:
  repo.security_review:
    match:
      user_intent:
        - review unknown repo
        - run external demo
        - inspect crypto project
    steps:
      - action: inspect_package_scripts
      - action: inspect_install_hooks
      - action: inspect_env_access
      - action: inspect_wallet_or_key_access
      - action: summarize_risks
    guards:
      - do_not_run_untrusted_code
      - do_not_connect_wallet
      - do_not_expose_env
      - do_not_share_full_screen
    output_format:
      - risk_summary
      - suspicious_files
      - blocked_actions
      - safe_next_steps

permissions:
  bash:
    "cat package.json": allow
    "grep *": allow
    "git diff*": allow
    "npm install*": deny
    "pnpm install*": deny
    "yarn install*": deny
    "npm run*": ask
    "node *": ask
    "curl *": ask
    "wget *": ask
    "rm -rf *": deny
    "*": ask

  browser:
    "connect_wallet": deny
    "sign_message": deny
    "approve_transaction": deny

  file_read:
    ".env": deny
    "~/.ssh/**": deny
    "**/*secret*": deny
    "**/*private*": deny

hooks:
  before_tool_call:
    - name: block_npm_install
      when:
        tool: bash
        command_matches:
          - "npm install*"
          - "pnpm install*"
          - "yarn install*"
      action: deny
      message: "Blocked: installing dependencies from an untrusted repo can execute lifecycle scripts."

    - name: block_wallet_connection
      when:
        tool: browser
        action_matches:
          - "connect_wallet"
          - "sign_message"
          - "approve_transaction"
      action: deny
      message: "Blocked: wallet connection or signing is not allowed during untrusted demo review."
```

---

## 19. Example: Research Rule

```yaml
targets:
  research.current_topic:
    phony: true
    priority: 60
    match:
      user_intent:
        - research
        - latest
        - current status
    inputs:
      required:
        - topic
    steps:
      - action: identify_freshness_requirement
      - action: search_authoritative_sources
      - action: compare_sources
      - action: summarize_findings
      - action: cite_sources
    guards:
      - use_current_sources
      - cite_load_bearing_claims
      - distinguish_fact_from_inference
    output_format:
      - direct_answer
      - cited_summary
      - uncertainty_if_any
```

---

## 20. Prior Art: Source-to-Artifact Tooling and Skill Packages

### 20.1 Stainless-Style Source-to-Artifact Tooling

AgentMakefile follows the same broad infrastructure pattern as modern API tooling systems such as Stainless: maintain one canonical source of truth, then generate platform-specific artifacts from it.

The analogy is:

| Stainless-style API tooling                   | AgentMakefile                                                                                    |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| API spec is the source                        | AgentMakefile is the skill / rails source                                                        |
| SDKs are generated outputs                    | Platform-native skills, rules, and prompt prefixes are generated outputs                         |
| CLI / MCP server / docs can be generated      | `CLAUDE.md`, `AGENTS.md`, `SKILL.md`, Cursor rules, hooks, and OpenCode configs can be generated |
| Solves API integration fragmentation          | Solves agent skill / rule fragmentation                                                          |
| Targets programming languages and API clients | Targets agent platforms and coding-agent runtimes                                                |

This framing is important because AgentMakefile is not merely a better prompt file. It is a **source format plus compiler toolchain**.

It is also not limited to file generation. The same normalized source can generate in-memory prompt prefixes for runtimes that assemble requests directly. File backends are compatibility artifacts for platforms whose prompt-prefix layer is configured through project files.

The design supports two integration modes:

* **Static compatibility mode**: compile `AgentMakefile` into files such as `AGENTS.md`, `CLAUDE.md`, Cursor rules, and `SKILL.md`.
* **Runtime-native mode**: load AgentMakefile IR inside the agent runtime and assemble the prompt prefix dynamically for each request.

The intended pattern is:

```text
AgentMakefile source
  ↓
agentmf compiler
  ↓
Generated platform-native artifacts
  ├── CLAUDE.md
  ├── AGENTS.md
  ├── .claude/skills/*/SKILL.md
  ├── .codex/skills/*/SKILL.md
  ├── .cursor/rules/*.mdc
  ├── .claude/settings.json
  ├── .claude/hooks/*
  └── opencode.json

Runtime prompt layout
  ├── linked stable prompt objects
  └── volatile task context
```

This makes AgentMakefile closer to an SDK generator for agent behavior than to a conventional configuration file, by analogy rather than by implementation domain.

---

### 20.2 Existing Skill and Rule Packages

This section records existing projects that validate AgentMakefile's core thesis: useful agent behavior is increasingly packaged as reusable skills, rules, plugins, and methodology packs, but these packages are still fragmented across agent-specific formats.

#### 20.2.1 Superpowers Skill Framework

The `obra/superpowers` repository is an important prior-art reference for AgentMakefile.

Superpowers describes itself as a complete software development methodology for coding agents, built from composable skills and initial instructions that ensure the agent uses those skills. It supports multiple agent environments, including Claude Code, Codex CLI, Codex App, Factory Droid, Gemini CLI, OpenCode, Cursor, and GitHub Copilot CLI.

This makes Superpowers especially relevant because it is not merely a single prompt or guideline file. It is closer to a reusable **agent methodology package**.

Key design properties:

* **Composable skills**: software-engineering workflows are broken into reusable skills.
* **Bootstrap instruction layer**: the agent is instructed to discover and use the relevant skill when applicable.
* **Cross-agent distribution**: the same skill methodology is intended to work across several coding-agent environments.
* **Namespaced skills**: the Superpowers ecosystem uses namespaced skill references such as `superpowers:systematic-debugging` and `superpowers:subagent-driven-development`.
* **Methodology over isolated prompts**: skills encode repeatable engineering practices such as systematic debugging, test-driven development, receiving code review, writing plans, and subagent-driven development.

From AgentMakefile's perspective, Superpowers demonstrates the need for two things:

1. A structured way to describe a reusable skill package.
2. A compiler or adapter layer that can install or emit the package into different agent-native formats.

### AgentMakefile Representation of a Superpowers-Style Package

A simplified AgentMakefile representation of a Superpowers-style methodology pack could look like this:

```yaml
version: 0.1

metadata:
  name: superpowers-methodology
  description: A composable software-development methodology pack for coding agents.
  package_type: methodology-pack
  namespace: superpowers

compile:
  targets:
    - claude-md
    - claude-skill
    - agents-md
    - codex-skill
    - cursor-rule
    - opencode

artifacts:
  claude-md:
    path: CLAUDE.md
  agents-md:
    path: AGENTS.md
  cursor-rule:
    path: .cursor/rules/superpowers.mdc
    frontmatter:
      description: Superpowers methodology bootstrap rules.
      alwaysApply: true

policies:
  always_use_relevant_skill:
    description: Before acting, identify whether a specialized skill applies and use it.
    guards:
      - inspect_task_for_skill_match
      - prefer_specialized_skill_over_ad_hoc_reasoning
      - state_which_skill_is_being_used_when_relevant

  systematic_execution:
    description: Use structured software-engineering workflows rather than improvising.
    guards:
      - do_not_guess_randomly
      - follow_skill_procedure_step_by_step
      - verify_before_claiming_completion

skills:
  systematic-debugging:
    namespace: superpowers
    description: Use for bugs, failing tests, regressions, or unexplained behavior.
    match:
      user_intent:
        - debug
        - failing test
        - regression
        - unexpected behavior
    steps:
      - reproduce_or_characterize_failure
      - inspect_recent_changes_and_relevant_context
      - form_hypotheses
      - test_hypotheses_one_at_a_time
      - identify_root_cause
      - implement_minimal_fix
      - verify_fix
    output_format:
      - observed_failure
      - root_cause
      - fix_summary
      - verification_result

  test-driven-development:
    namespace: superpowers
    description: Use when implementing behavior that can be specified by tests.
    match:
      user_intent:
        - implement feature
        - fix bug with test
        - add behavior
    steps:
      - define_expected_behavior
      - write_failing_test
      - implement_minimal_code_to_pass
      - run_test
      - refactor_if_needed
    guards:
      - do_not_skip_red_step_when_testable
      - implement_only_enough_to_pass
      - keep_refactor_separate_from_behavior_change
    output_format:
      - failing_test_added
      - implementation_summary
      - test_result

  receiving-code-review:
    namespace: superpowers
    description: Use when receiving code review feedback before implementing suggestions.
    match:
      user_intent:
        - address code review
        - respond to review feedback
        - implement review comments
    steps:
      - read_feedback_completely
      - restate_requirement_or_ask
      - verify_against_codebase_reality
      - evaluate_technical_correctness
      - respond_with_agreement_or_reasoned_pushback
      - implement_one_item_at_a_time
      - test_each_change
    guards:
      - do_not_blindly_accept_questionable_feedback
      - technical_correctness_over_social_comfort
      - ask_when_feedback_is_ambiguous
    output_format:
      - feedback_interpretation
      - technical_evaluation
      - implemented_changes
      - verification_result

  writing-plans:
    namespace: superpowers
    description: Use when planning non-trivial implementation work.
    match:
      user_intent:
        - write plan
        - plan implementation
        - break down project
    steps:
      - identify_goal
      - inspect_relevant_context
      - define_success_criteria
      - break_work_into_ordered_steps
      - identify_risks_and_open_questions
    output_format:
      - goal
      - context_summary
      - plan
      - risks
      - success_criteria

targets:
  code.methodology:
    phony: true
    priority: 75
    policies:
      - always_use_relevant_skill
      - systematic_execution
    skills:
      - superpowers:systematic-debugging
      - superpowers:test-driven-development
      - superpowers:receiving-code-review
      - superpowers:writing-plans
    output_format:
      - selected_skill_if_any
      - task_progress
      - verification_result

compiler_hints:
  skill:
    namespace: superpowers
    emit_each_skill_as_package: true
  markdown:
    include_skill_selection_table: true
  cursor:
    alwaysApply: true
```

### Why Superpowers Matters for AgentMakefile

Superpowers suggests that AgentMakefile should support **methodology packs**, not only individual task rules.

This has several implications:

1. **Namespace support is essential.** Skills such as `superpowers:systematic-debugging` should be distinguishable from local project skills with the same base name.
2. **Skill discovery should be first-class.** A policy can instruct an agent to select the relevant skill before acting.
3. **Rule packages should support many skills.** A package may contain dozens of related skills, not just one target.
4. **Compiler backends should emit installable skill directories.** For example, `.claude/skills/*/SKILL.md` or `.codex/skills/*/SKILL.md`.
5. **AgentMakefile should distinguish bootstrap instructions from individual skills.** The bootstrap layer tells the agent when and how to use the skills; the skill files contain the detailed procedures.
6. **Security scanning matters.** Reusable skill packages can include behavior-shaping instructions and sometimes scripts or hooks, so package provenance and review are important.

Superpowers is therefore a strong reference for the future AgentMakefile package ecosystem:

```text
Methodology pack
  ↓
Namespaced skills
  ↓
Bootstrap instructions
  ↓
Cross-agent installation
  ↓
Platform-native generated files
```

AgentMakefile can generalize this into:

```text
AgentMakefile package
  ↓
Agent Rule IR
  ↓
Backend emitters
  ├── Claude Code skills
  ├── Codex skills
  ├── Cursor rules
  ├── AGENTS.md
  ├── CLAUDE.md
  └── OpenCode config
```

---

#### 20.2.2 Karpathy-Inspired Skills

The `multica-ai/andrej-karpathy-skills` repository is a useful reference implementation pattern for AgentMakefile.

It packages the same behavioral guidelines into multiple agent-native forms:

* `CLAUDE.md` for Claude Code project instructions
* `skills/karpathy-guidelines/SKILL.md` for Claude-style skill packaging
* `.cursor/rules/karpathy-guidelines.mdc` for Cursor project rules
* `CURSOR.md` and examples for platform-specific usage

The core guidelines are organized around four high-level behavioral principles:

1. **Think Before Coding**: surface assumptions, ambiguity, tradeoffs, and confusion before implementing.
2. **Simplicity First**: prefer the minimum code that solves the problem and avoid speculative abstractions.
3. **Surgical Changes**: touch only what the task requires, avoid drive-by refactors, and ensure every changed line traces to the user request.
4. **Goal-Driven Execution**: define success criteria, write or use tests where appropriate, and loop until verified.

This repository demonstrates an important design pattern:

```text
Single behavioral rule source
  ↓
Multiple agent-native outputs
  ├── CLAUDE.md
  ├── SKILL.md
  └── Cursor .mdc rule
```

AgentMakefile generalizes this pattern by making the source layer structured, declarative, and compilable:

```text
AgentMakefile
  ↓
Agent Rule IR
  ↓
Compiler backends
  ├── CLAUDE.md
  ├── .claude/skills/*/SKILL.md
  ├── .cursor/rules/*.mdc
  ├── AGENTS.md
  ├── .codex/skills/*/SKILL.md
  └── opencode.json
```

The key difference is that the Karpathy-style repository is mainly a manually maintained cross-platform guideline package, while AgentMakefile aims to be a structured source format that can generate these outputs automatically.

### AgentMakefile Representation of Karpathy-Style Guidelines

The same behavioral principles can be represented in AgentMakefile as reusable policy rules:

```yaml
version: 0.1

policies:
  think_before_coding:
    description: Surface assumptions, ambiguity, and tradeoffs before implementing.
    applies_to:
      - code.write
      - code.review
      - code.refactor
    guards:
      - state_assumptions
      - ask_when_uncertain
      - present_interpretations_when_ambiguous
      - push_back_when_simpler_option_exists

  simplicity_first:
    description: Prefer the minimum code that solves the task.
    applies_to:
      - code.write
      - code.refactor
    guards:
      - no_unrequested_features
      - no_single_use_abstractions
      - no_speculative_configurability
      - simplify_if_overengineered

  surgical_changes:
    description: Touch only what is required by the user request.
    applies_to:
      - code.edit
      - code.refactor
      - code.fix_bug
    guards:
      - no_drive_by_refactors
      - preserve_existing_style
      - do_not_delete_preexisting_dead_code_unless_asked
      - every_changed_line_traces_to_request

  goal_driven_execution:
    description: Convert implementation requests into verifiable goals.
    applies_to:
      - code.write
      - code.fix_bug
      - code.refactor
    steps:
      - define_success_criteria
      - identify_verification_method
      - implement_minimal_change
      - run_or_explain_verification
    output_format:
      - plan_with_verification
      - changed_files
      - verification_result
```

### Compiler Implications

A compiler backend can lower these policies into platform-specific files:

| AgentMakefile object           | Claude Code                       | Cursor                | Codex                 | OpenCode                  |
| ------------------------------ | --------------------------------- | --------------------- | --------------------- | ------------------------- |
| `policies.think_before_coding` | `CLAUDE.md` section or `SKILL.md` | `.cursor/rules/*.mdc` | `AGENTS.md` or skill  | agent prompt              |
| `guards.surgical_changes`      | instruction checklist             | always-applied rule   | instruction checklist | agent prompt / validation |
| `goal_driven_execution.steps`  | skill procedure                   | rule body             | skill procedure       | workflow instructions     |
| `output_format`                | response format guidance          | rule body             | `AGENTS.md` section   | agent output contract     |

This should be a first-class MVP use case: compile a structured AgentMakefile policy pack into Claude Code, Cursor, and Codex-compatible guideline files.

### Minimal AgentMakefile Example: Karpathy-Inspired Coding Guidelines

The following example shows how the Karpathy-inspired guideline package can be represented as a single `AgentMakefile` source. This source can then compile into `CLAUDE.md`, Cursor `.mdc` rules, Codex `AGENTS.md`, and skill packages.

```yaml
# AgentMakefile
version: 0.1

metadata:
  name: karpathy-coding-guidelines
  description: Makefile-style agent rules to reduce common LLM coding mistakes.
  source_style: karpathy-inspired
  default_apply: true

compile:
  targets:
    - claude-md
    - claude-skill
    - cursor-rule
    - agents-md
    - codex-skill

artifacts:
  claude-md:
    path: CLAUDE.md

  claude-skill:
    path: .claude/skills/karpathy-guidelines/SKILL.md

  cursor-rule:
    path: .cursor/rules/karpathy-guidelines.mdc
    frontmatter:
      description: Behavioral guidelines to reduce common LLM coding mistakes.
      alwaysApply: true

  agents-md:
    path: AGENTS.md

  codex-skill:
    path: .codex/skills/karpathy-guidelines/SKILL.md

policies:
  think_before_coding:
    description: Do not assume or hide uncertainty. Surface assumptions, ambiguity, and tradeoffs before coding.
    applies_to:
      - code.write
      - code.review
      - code.debug
      - code.refactor
      - architecture.discuss
    guards:
      - state_assumptions_explicitly
      - ask_when_uncertain
      - present_multiple_interpretations_when_ambiguous
      - identify_simpler_options
      - push_back_when_request_is_overcomplicated

  simplicity_first:
    description: Prefer the minimum code that solves the actual problem.
    applies_to:
      - code.write
      - code.refactor
      - code.fix_bug
    guards:
      - avoid_unrequested_features
      - avoid_speculative_abstractions
      - avoid_single_use_abstractions
      - prefer_clear_code_over_clever_code
      - remove_unnecessary_complexity

  surgical_changes:
    description: Touch only what the task requires.
    applies_to:
      - code.edit
      - code.fix_bug
      - code.refactor
      - code.review
    guards:
      - avoid_drive_by_refactors
      - preserve_existing_style
      - do_not_rewrite_unrelated_code
      - do_not_delete_dead_code_unless_asked
      - ensure_every_changed_line_traces_to_user_request

  goal_driven_execution:
    description: Convert coding work into verifiable goals and close the loop with testing or explicit verification.
    applies_to:
      - code.write
      - code.fix_bug
      - code.refactor
      - code.review
    steps:
      - define_success_criteria
      - identify_verification_method
      - implement_minimal_change
      - run_tests_or_explain_why_not
      - summarize_result_against_success_criteria

targets:
  code.task:
    phony: true
    priority: 70
    match:
      user_intent:
        - write code
        - fix bug
        - debug code
        - refactor code
        - review code
        - discuss architecture
        - write tests
    policies:
      - think_before_coding
      - simplicity_first
      - surgical_changes
      - goal_driven_execution
    steps:
      - action: clarify_task_if_needed
      - action: state_assumptions_and_success_criteria
      - action: inspect_relevant_context
      - action: make_minimal_change_or_recommendation
      - action: verify_or_explain_verification_gap
      - action: summarize_changes_and_risks
    output_format:
      - assumptions_or_clarifications
      - plan_or_success_criteria
      - minimal_solution
      - verification_result
      - changed_files_if_applicable

  code.quick_fix:
    phony: true
    priority: 80
    match:
      user_intent:
        - typo fix
        - one line fix
        - small obvious fix
    policies:
      - surgical_changes
      - simplicity_first
    guards:
      - skip_full_rigor_for_trivial_tasks
      - do_not_over_explain
      - make_smallest_safe_change
    output_format:
      - concise_fix
      - verification_if_relevant

permissions:
  bash:
    "git status": allow
    "git diff*": allow
    "npm test": ask
    "npm run test*": ask
    "npm install*": ask
    "pnpm install*": ask
    "yarn install*": ask
    "rm -rf *": deny
    "*": ask

  file_write:
    "src/**": allow
    "tests/**": allow
    "package.json": ask
    "package-lock.json": ask
    ".env": deny
    "**/*secret*": deny

validation:
  code.task:
    must_include_when_nontrivial:
      - assumptions_or_clarifications
      - success_criteria
      - verification_result
    must_not_include:
      - unrelated_refactors
      - unrequested_features
      - silent_assumptions
      - speculative_abstractions

compiler_hints:
  markdown:
    title: Karpathy-Inspired Coding Guidelines
    include_tradeoff_note: true
    tradeoff_note: These rules bias toward caution over speed. For trivial tasks, use judgment and avoid unnecessary ceremony.

  skill:
    trigger: Use this skill whenever writing, reviewing, debugging, refactoring, testing, or discussing code.

  cursor:
    alwaysApply: true
```

This example captures the main design thesis of AgentMakefile:

```text
One structured rule source
  ↓
Multiple generated agent-native rule files
  ├── CLAUDE.md
  ├── .claude/skills/*/SKILL.md
  ├── .cursor/rules/*.mdc
  ├── AGENTS.md
  └── .codex/skills/*/SKILL.md
```

It also clarifies the difference between policy-level guidance and runtime enforcement. The coding principles are mostly soft rails that compile into instructions and skills, while the permission block can compile into hard rails where the target agent runtime supports permission enforcement.

---

## 21. Compiler Backends

AgentMakefile is designed to sit above or beside existing agent systems as a portable rules source and compiler layer.

### 21.1 Claude Code Backend

AgentMakefile can compile into Claude Code project instructions, settings, permissions, hooks, and skills.

Potential outputs:

```text
CLAUDE.md
.claude/settings.json
.claude/hooks/*
.claude/skills/*/SKILL.md
```

Example mapping:

| AgentMakefile concept | Claude Code output                       |
| --------------------- | ---------------------------------------- |
| `targets`             | `CLAUDE.md` sections or skills           |
| `steps`               | `SKILL.md` procedures                    |
| `permissions`         | settings permissions / hooks             |
| `hooks`               | `.claude/hooks/*`                        |
| `guards`              | instructions, permissions, or hooks      |
| `output_format`       | response instructions or skill checklist |

Initial implementation scope: the `claude-code` backend emits `.claude/settings.json` with native permission entries grouped by `allow`, `ask`, and `deny`. It also emits generated shell hook files under `.claude/hooks/<event>/` and references them from settings. Claude Code skill directory generation remains a separate backend milestone.

---

### 21.2 OpenCode Backend

AgentMakefile can compile targets into OpenCode agent definitions and permissions.

Potential outputs may include:

```text
opencode configuration files
agent definitions
permission configuration where supported
```

The exact OpenCode artifact layout should be backend-version-specific and should not be assumed stable in the core spec.

Example mapping:

| AgentMakefile concept | OpenCode output                       |
| --------------------- | ------------------------------------- |
| `targets`             | specialized agents                    |
| `steps`               | agent prompt / workflow instructions  |
| `permissions`         | tool permission config                |
| `guards`              | permission rules / prompt constraints |
| `hooks`               | runtime hooks where supported         |

Initial implementation scope: the `opencode` backend emits `opencode.json` with the OpenCode schema URL, a `permission` section lowered from normalized AgentMakefile permissions, and an `agent` section derived from normalized targets. Each target becomes a subagent with a deterministic name, description, prompt, and permission configuration.

---

### 21.3 Codex Backend

AgentMakefile can compile into Codex-compatible `AGENTS.md` instructions and skill packages.

Potential outputs:

```text
AGENTS.md
.codex/skills/*/SKILL.md
```

Example mapping:

| AgentMakefile concept | Codex output                                |
| --------------------- | ------------------------------------------- |
| `targets`             | `AGENTS.md` task sections or skills         |
| `steps`               | `SKILL.md` procedures                       |
| `guards`              | instruction rails                           |
| `output_format`       | response format requirements                |
| `permissions`         | generated warnings or runtime adapter rules |

---

### 21.4 Cursor / Windsurf / Generic Coding Agents

AgentMakefile can compile into `.cursor/rules`, Windsurf rules, or generic project instruction files.

Potential outputs:

```text
.cursor/rules/*
AGENTS.md
RULES.md
```

---

### 21.5 LangGraph Backend

AgentMakefile can compile workflow targets into LangGraph-style nodes and conditional edges.

Example:

```yaml
targets:
  research.current_topic:
    compile_to: langgraph
```

---

### 21.6 OpenAI Agents SDK Backend

AgentMakefile can configure guardrails, tools, handoffs, and output schemas for OpenAI Agents SDK-style runtimes.

Example:

```yaml
guards:
  - output_schema_validation
  - tool_call_review
```

---

### 21.7 Dagger / CI Backend

AgentMakefile steps can call reproducible Dagger functions.

Example:

```yaml
steps:
  - action: dagger.call
    function: test
```

---

### 21.8 Backend Capability Matrix

Different backends support different levels of enforcement. The compiler should know each backend's capabilities and emit warnings when hard rails must be lowered into soft instructions.

| Backend        | Markdown |         Skills |       Permissions |             Hooks |  Hard enforcement |
| -------------- | -------: | -------------: | ----------------: | ----------------: | ----------------: |
| `claude-md`    |      Yes |             No |         Soft only |                No |                No |
| `agents-md`    |      Yes |             No |         Soft only |                No |                No |
| `cursor-rule`  |      Yes |             No |         Soft only |           Limited |                No |
| `claude-skill` |      Yes |            Yes |         Soft only |                No |                No |
| `codex-skill`  |      Yes |            Yes |         Soft only |                No |                No |
| `skills-index` |      Yes |        Catalog |         Soft only |                No |                No |
| `claude-code`  |      Yes |            Yes |               Yes |               Yes |           Partial |
| `opencode`     |      Yes |   Agent config |               Yes | Runtime-dependent |           Partial |
| `langgraph`    |       No | Workflow nodes | Runtime-dependent | Runtime-dependent | Runtime-dependent |

Example warning:

```text
Warning: permissions were compiled as soft instructions because backend cursor-rule does not support hard enforcement.
```

Backends should declare capabilities explicitly so users know whether a generated artifact is advisory or enforceable.

---

## 22. Implementation References

AgentMakefile should borrow from Makefile, but it should not try to become GNU Make-compatible. A better implementation philosophy is closer to modern task runners such as `just`, combined with a compiler-style IR and backend emitter architecture.

### 22.1 Why `just` Is a Good Reference

`just` is a command runner inspired by Make, but it intentionally avoids much of Make's historical complexity. This makes it a strong reference for AgentMakefile.

AgentMakefile should borrow the following ideas from `just`:

* **Explicit recipes over implicit magic**: rules should be easy to read and should not depend on hidden implicit rule search.
* **Human-friendly error messages**: validation errors should point to the exact target, policy, permission, or include that caused the problem.
* **Simple command surface**: commands such as `agentmf validate`, `agentmf compile`, `agentmf graph`, and `agentmf trace` should be predictable.
* **Project-local rule file**: similar to a `justfile`, the default `AgentMakefile` should live in the project root and describe project-specific behavior.
* **Useful defaults with explicit overrides**: local rules can extend or override included rule packs, but the merge behavior must be deterministic.
* **No unnecessary build-system semantics**: AgentMakefile should not inherit timestamp-based rebuild semantics, shell-first execution, or GNU Make's implicit rule machinery unless explicitly needed later.

### 22.2 What to Borrow From Make

AgentMakefile should borrow Make's mental model, not its full syntax.

Useful concepts:

* target / dependency graph
* phony targets
* pattern rules
* includes
* variable substitution
* override precedence
* incremental/cache-inspired thinking

Concepts to avoid in the MVP:

* full GNU Make syntax compatibility
* recursive variable expansion semantics
* automatic variables such as `$@`, `$<`, and `$^`
* implicit rule search
* shell-centric recipe execution
* timestamp-only rebuild logic

### 22.3 What to Borrow From Taskfile

Taskfile is a good reference for YAML-based task composition.

Useful concepts:

* YAML-native structure
* namespaced includes
* reusable task files
* project-local and shared task packs
* clear directory resolution rules for included files

AgentMakefile's include model should be closer to Taskfile's namespaced include model than GNU Make's raw textual include model.

Example:

```yaml
include:
  - path: policies/karpathy.yml
    as: karpathy
  - path: policies/security.yml
    as: security
```

### 22.4 What to Borrow From Ninja

Ninja is useful as an architectural reference because it separates a human-friendly frontend from a lower-level generated build graph.

AgentMakefile should follow a similar layered design:

```text
AgentMakefile source
  ↓
Agent Rule IR
  ↓
Backend emitters
  ↓
Generated agent-native rule files
```

The key lesson is that the compiler should normalize the source into a stable IR before generating platform-specific outputs.

### 22.5 What to Borrow From Bazel-like Systems

Bazel-style systems are useful as long-term references for separating analysis from execution.

AgentMakefile should distinguish:

1. **Load phase**: read files, resolve includes, namespace packages.
2. **Analysis phase**: validate schema, resolve targets, merge policies, normalize permissions.
3. **Emission phase**: generate `CLAUDE.md`, `AGENTS.md`, `.cursor/rules`, `SKILL.md`, `opencode.json`, or other backend files.
4. **Runtime phase**: optional future phase for direct enforcement through wrappers and tool interception.

The MVP should implement the first three phases only.

### 22.6 Recommended MVP Philosophy

AgentMakefile should start closer to `just` than to GNU Make:

```text
simple, explicit, deterministic, good errors, no hidden magic
```

The compiler should be deterministic:

```text
AgentMakefile in → predictable generated files out
```

LLM-based optimization can be added later as optional tooling, but the core `compile` command should not depend on LLM reasoning.

---

## 23. Compiler and Runtime Requirements

AgentMakefile should support two modes:

1. **Compiler mode**: validate and compile AgentMakefile into native agent rule files.
2. **Runtime mode**: directly enforce rules through a wrapper, tool interceptor, or sandbox.

### 23.1 MVP 0 Compiler Requirements

An MVP 0 AgentMakefile compiler should provide:

1. Rule loading
2. Schema validation
3. Target metadata validation
4. IR generation
5. Backend-specific compilation
6. Generated-file ownership checks
7. Dry-run planning
8. Generated-file trace output

### 23.1.1 Full Compiler Requirements

A full AgentMakefile compiler should additionally provide:

1. Include resolution
2. Priority conflict detection
3. Dependency graph validation
4. Permission rule validation
5. Hook validation
6. Backend capability downgrade warnings
7. Managed-block updates
8. Package provenance checks

### 23.2 Optional Runtime Requirements

An AgentMakefile runtime should provide:

1. Target selection
2. Dependency graph resolution
3. Step execution
4. Guard evaluation
5. Tool-call interception
6. Permission enforcement
7. Sandbox integration
8. Output validation
9. Fallback handling
10. Trace logging

---

## 24. Traceability

The compiler or runtime should optionally produce a trace.

Example:

```json
{
  "selected_target": "repo.security_review",
  "matched_rules": ["repo.security_review", "generic.security"],
  "priority_resolution": "repo.security_review selected because priority 70 > 50",
  "compiled_outputs": [
    "CLAUDE.md",
    ".claude/settings.json",
    ".claude/hooks/pre_tool_use.sh"
  ],
  "guards_applied": [
    "do_not_run_untrusted_code",
    "do_not_connect_wallet"
  ],
  "permissions_generated": [
    "deny npm install*",
    "deny wallet signing",
    "ask curl *"
  ]
}
```

This is useful for debugging agent behavior and generated rails.

---

## 25. Versioning

AgentMakefile should include a version field.

```yaml
version: 0.1
```

Future versions may add:

* Stronger schema validation
* Conditional dependencies
* Loop support
* Human approval gates
* Typed outputs
* Remote skill registry
* Sandboxed script execution
* Backend capability negotiation
* Cross-agent compatibility matrix

---

## 26. Security Considerations

AgentMakefile may influence tool calls, generated rules, permissions, hooks, and execution behavior, so it should be treated as trusted project configuration.

Risks include:

* Prompt injection through rule files
* Unsafe tool routing
* Overly broad permissions
* Hidden destructive actions
* Misleading output contracts
* Untrusted includes
* Generated hooks that execute unsafe commands
* Rules that silently weaken platform-native protections

Recommended mitigations:

* Only load AgentMakefile from trusted repositories
* Require approval for destructive tool actions
* Restrict remote includes by default
* Log selected targets and executed steps
* Separate policy rules from task rules
* Validate schema before execution
* Print generated files before applying them
* Provide a dry-run mode
* Make permission broadening explicit

---

## 27. Open Questions

1. Should AgentMakefile use YAML, TOML, JSON, or Makefile-like syntax?
2. Should steps be purely declarative, or allow shell/script commands?
3. Should rule matching be deterministic or LLM-assisted in runtime mode?
4. Should dependencies support loops and retries?
5. How strict should output validation be?
6. How should conflicts between user instructions and project rules be resolved?
7. Should there be a public skill registry?
8. Should AgentMakefile compile to LangGraph, OpenAI Agents SDK, or another runtime?
9. How should cached results be stored and invalidated?
10. How much execution trace should be visible to the user?
11. What is the minimum common permission model across Claude Code, OpenCode, Codex, Cursor, and custom runtimes?
12. Should hard rails be represented even when a backend can only compile them into soft instructions?
13. Should generated rule files be committed to the repository or regenerated on demand?
14. What should the exact merge semantics be for included rule packages?
15. Should package includes support semantic version ranges, lockfiles, or checksums?
16. How should locked organization policies be represented so local projects cannot weaken them?
17. How closely should AgentMakefile follow `just` syntax and CLI conventions?
18. Should AgentMakefile remain YAML-only, or support a more `justfile`-like concise syntax later?
19. Should future package support use an `AgentMakefile.lock` file with checksums and trusted registries?
20. Should generated native artifacts be committed, regenerated on demand, or both?
21. Should `graph` and `trace` be required commands or optional debugging tools?

---

## 28. Suggested MVP

The first MVP should be a validator and compiler, not a full coding-agent runtime.

### MVP 0: Deterministic Markdown Compiler

Commands:

```bash
agentmf validate
agentmf compile --target agents-md
agentmf compile --target claude-md
agentmf compile --target cursor-rule
```

Supported features:

* Single `AgentMakefile` only
* YAML format
* `metadata`
* `policies`
* `targets`
* `steps`
* `guards`
* `output_format`
* `compiler_hints`
* Basic schema validation
* Deterministic IR generation
* Compilation to `AGENTS.md`, `CLAUDE.md`, and `.cursor/rules/*.mdc`
* Dry-run by default
* `--write` required to write files
* Managed block support for shared files

Out of scope for MVP 0:

* Includes
* Namespaces
* Remote packages
* Hard permissions
* Hooks
* Runtime target selection

### MVP 1: Skill Compiler and Soft Permissions

Commands:

```bash
agentmf compile --target codex-skill
agentmf compile --target claude-skill
```

Supported outputs:

```text
.codex/skills/*/SKILL.md
.claude/skills/*/SKILL.md
```

Targets become reusable skill packages.

Additional supported features:

* Compile targets into `.claude/skills/*/SKILL.md`
* Compile targets into `.codex/skills/*/SKILL.md`
* Emit permissions as soft instruction tables
* Backend capability warnings

### MVP 2: Composition and Local Rule Packages

Supported features:

* Local includes
* Namespaced rule packages
* `extends`
* Merge semantics
* Local-only rule packages
* Include graph validation

Remote package registries remain out of scope until package provenance and security scanning are defined.

### MVP 3: Hard Rails Compiler

Commands:

```bash
agentmf compile --target claude-code
agentmf compile --target opencode
```

Supported outputs:

```text
.claude/settings.json
.claude/hooks/*
opencode.json
```

Permissions and hooks become platform-native enforcement rules where supported.

### MVP 4: Optional Runtime Wrapper

Command:

```bash
agentmf run
```

The first runtime milestone can be a non-executing dry run:

```bash
agentmf run --dry-run --request "review code" --format json
```

This skeleton should reuse target selection and fragment link planning, then report the selected target closure, fragment paths, guards, steps, permissions, output contracts, and fallback metadata without executing workflow steps or intercepting tools. Current dry-run guard evaluation resolves policy and target guards into structured planned records while keeping execution disabled. Permission dry-run evaluates proposed tool calls against normalized AgentMakefile permission rules and reports matched rules, defaults, and final actions without running those calls. Output validation dry-run checks proposed output objects against selected target output contracts, required fields, and full JSON Schema constraints. The prompt-link milestone assembles the selected target fragments into a deterministic prompt prefix and compares its size against the matching all-in-one prompt artifact so users can see the token/cache benefit directly. The `agentmf prompt` command builds on that path by emitting a deterministic final prompt payload that separates stable prefix material from volatile request, plan, context-file, and git context. The `agentmf ask` command reuses the same prompt payload path for one-shot provider calls; the first provider is a deterministic local `echo` adapter. The initial `agentmf exec` prototype requires `--apply`, accepts explicit tool calls, records the provider tool-call interception contract, applies prototype sandbox preflight checks for local bash calls, executes only permission-allowed and sandbox-allowed calls, and emits planned or opt-in internal fallback results for blocked tool calls.

The near-term runtime direction is plugin-first and is specified in [agentmf_plugin_adapter_spec.md](agentmf_plugin_adapter_spec.md). Existing agent CLIs can keep owning model calls, tool loops, approvals, and sandboxing while AgentMakefile produces a selected prompt payload from the current request and optional implementation plan. The longer standalone runtime CLI direction is specified in [agentmf_runtime_cli_spec.md](agentmf_runtime_cli_spec.md). In both models, the plan is runtime task context and selection signal; it is not compiled into stable prompt fragments.

The runtime can enforce hard rails directly through:

* Tool-call interception
* Bash command approval
* File read/write restrictions
* Network restrictions
* Browser/wallet action restrictions
* Execution tracing

---

## 29. Positioning

AgentMakefile can be positioned as:

> A cross-platform source format and compiler for AI agent skills and rails.

Or in Makefile terms:

> AgentMakefile is a build system for agent prompt prefixes.

Or more formally:

> AgentMakefile is a declarative source format that defines reusable agent skills, task targets, dependencies, tool permissions, hooks, guardrails, output contracts, and fallback behavior, then compiles them into native skill and rule formats for Claude Code, OpenCode, Codex, Cursor, and other agent runtimes.

Short versions:

> Cross-platform source files for agent skills.

> Write agent skills once. Compile everywhere.

> Agent behavior as generated artifacts.

> Prompt prefixes as build artifacts.

> One source file for Claude Code, OpenCode, Codex, and future agents.

---

## 30. Summary

AgentMakefile brings Makefile-style structure to agent skill and rails systems.

It introduces:

* Targets
* Dependencies
* Steps
* Guards
* Permissions
* Hooks
* Variables
* Includes and composable rule packages
* Pattern rules
* Output contracts
* Fallbacks
* Caching
* Traceability
* Compiler backends

The key design decision is that AgentMakefile should not initially compete with existing coding agents. Instead, it should become a portable source format that compiles into their native skill and rule formats, which in most systems are eventually loaded as prompt-prefix material.

Static artifacts are therefore compatibility outputs. AgentMakefile's deeper runtime role is to provide the structured IR needed for dynamic, dependency-aware prompt-prefix assembly.

Between those two layers, AgentMakefile can emit target fragments as compiled prompt objects. This gives existing file-based agents a practical bridge: they can read a small target-specific fragment instead of loading an all-in-one `AGENTS.md` or `CLAUDE.md`, while future runtimes can skip the Markdown artifact and link equivalent prompt objects directly from IR.

This creates a middle layer between simple instruction files such as `AGENTS.md` / `CLAUDE.md` and heavy workflow frameworks such as LangGraph.

The result is a lightweight, composable, auditable, and portable rule system for practical agent behavior.

The implementation philosophy should be closer to `just` than to GNU Make: simple, explicit, deterministic, and easy to debug.

Core slogan:

> **Write agent skills once. Compile everywhere.**

---

## 31. agentmf Implementation Plan

This section defines an implementation plan for `agentmf`, the compiler and validator for AgentMakefile.

The first implementation should be a deterministic compiler, not an agent runtime.

Primary goal:

```text
AgentMakefile source
  ↓
agentmf validate / compile
  ↓
Generated platform-native artifacts
  ├── CLAUDE.md
  ├── AGENTS.md
  ├── .cursor/rules/*.mdc
  ├── .claude/skills/*/SKILL.md
  └── .codex/skills/*/SKILL.md
```

---

### 31.1 Implementation Philosophy

`agentmf` should start closer to `just` than to GNU Make:

```text
simple, explicit, deterministic, good errors, no hidden magic
```

The compiler should be deterministic:

```text
same AgentMakefile + same compiler version → same generated files
```

The MVP should avoid LLM reasoning in the core compiler. LLM-assisted commands such as `agentmf optimize`, `agentmf explain`, or `agentmf migrate` can be added later, but `agentmf compile` should remain deterministic.

---

### 31.2 Recommended Tech Stack

Recommended initial stack:

```text
Language: Python 3.11+
CLI: Typer
Schema models: Pydantic
YAML parser: ruamel.yaml or PyYAML
Templates: Jinja2
Console output: Rich
Testing: pytest
Packaging: uv or hatch
```

Reasoning:

* Python is fast for prototyping compiler tooling.
* Pydantic gives clear schema validation and useful error messages.
* Jinja2 is sufficient for deterministic Markdown and skill generation.
* Typer provides a clean CLI surface.

A future implementation could be rewritten in Rust or Go if startup speed and standalone binary distribution become important.

---

### 31.3 Repository Structure

Recommended repository layout:

```text
agentmf/
  pyproject.toml
  README.md
  AgentMakefile.example

  src/agentmf/
    __init__.py
    cli.py

    loader/
      __init__.py
      discover.py        # find AgentMakefile
      load.py            # read YAML
      include.py         # future: include resolution
      merge.py           # future: merge semantics

    model/
      __init__.py
      source.py          # AgentMakefile source schema
      ir.py              # normalized Agent Rule IR
      diagnostics.py     # errors, warnings, source locations
      capabilities.py    # backend capability model

    compiler/
      __init__.py
      pipeline.py        # load → validate → IR → emit
      normalize.py       # source → IR
      validate.py        # schema and semantic checks
      ownership.py       # managed block / overwrite rules
      trace.py           # compile trace

    backends/
      __init__.py
      base.py
      claude_md.py
      agents_md.py
      cursor_rule.py
      claude_skill.py
      codex_skill.py
      # future:
      claude_code.py
      opencode.py

    templates/
      claude_md.j2
      agents_md.j2
      cursor_rule.mdc.j2
      skill_md.j2

    utils/
      fs.py
      slug.py
      globmatch.py
      markdown.py

  tests/
    fixtures/
      karpathy/AgentMakefile
      superpowers_minimal/AgentMakefile
    test_validate.py
    test_compile_claude_md.py
    test_compile_agents_md.py
    test_compile_cursor_rule.py
    test_compile_skills.py
    test_managed_blocks.py
```

---

### 31.4 Compiler Pipeline

The main compiler pipeline should be:

```text
1. Discover AgentMakefile
2. Load YAML
3. Validate source schema
4. Normalize source into Agent Rule IR
5. Validate IR
6. Select backend targets
7. Emit generated files
8. Apply generated-file ownership policy
9. Print diagnostics and trace
10. Write files only when --write is provided
```

Pseudo-code:

The following pseudo-code uses placeholder helper types such as `Diagnostics`, `YamlError`, and `diagnostics_from_exception`; concrete implementations should map them to the chosen YAML parser and diagnostic model.

```python
def compile_agentmakefile(path, targets, out_dir, write=False, force=False, all_backends=False):
    diagnostics = Diagnostics()

    try:
        raw = load_yaml(path)
        source = AgentMakefileSource.model_validate(raw)
    except (YamlError, ValidationError) as error:
        diagnostics.extend(diagnostics_from_exception(error))
        return CompileResult.failed(diagnostics)

    diagnostics.extend(validate_source(source))
    if all_backends and targets:
        diagnostics.add_error("--all cannot be combined with --target")
    if diagnostics.has_errors():
        return CompileResult.failed(diagnostics)

    ir = normalize_to_ir(source)

    diagnostics.extend(validate_ir(ir))
    if diagnostics.has_errors():
        return CompileResult.failed(diagnostics)

    selected_backends = resolve_backend_targets(source, targets, all_backends=all_backends)

    generated = []
    for backend_name in selected_backends:
        backend = get_backend(backend_name)
        generated.extend(backend.emit(ir))
        diagnostics.extend(check_backend_capabilities(backend, ir))

    plan = apply_ownership_policy(generated, out_dir, write=write, force=force)

    if write:
        write_generated_files(plan)

    return CompileResult(ir=ir, files=generated, diagnostics=diagnostics, plan=plan)
```

---

### 31.5 CLI Surface

Initial CLI commands:

```bash
agentmf validate
agentmf compile
agentmf compile --target claude-md
agentmf compile --target agents-md
agentmf compile --target cursor-rule
agentmf compile --target claude-skill
agentmf compile --target codex-skill
agentmf compile --target skills-index
agentmf plugin install --skills-dir <dir> --out .agentmf/plugin/AgentMakefile --write
agentmf plugin payload --file .agentmf/plugin/AgentMakefile --request <text>
agentmf skills scan --skills-dir <dir> --out AgentMakefile
agentmf skills sync --file AgentMakefile --host codex --write
agentmf compile --all
```

Optional debugging commands:

```bash
agentmf trace
agentmf graph
```

Recommended options:

```bash
--file AgentMakefile      # explicit source file
--out .                   # output directory
--target <backend>        # backend target, repeatable
--all                     # compile every backend supported by this agentmf version
--write                   # actually write files
--force                   # overwrite managed or existing outputs
--dry-run                 # default behavior
--format text|json        # diagnostics output
--trace                   # print compile trace
```

Default behavior:

```text
agentmf compile
```

If `compile.targets` is present, it uses those targets. If `compile.targets` is absent, MVP 0 defaults to `claude-md`, `agents-md`, and `cursor-rule`.

It should perform a dry run and print:

```text
Would generate:
  CLAUDE.md
  AGENTS.md
  .cursor/rules/agentmakefile-generated.mdc

Warnings:
  none

Run with --write to write files.
```

---

### 31.6 MVP 0 Scope

MVP 0 should implement a deterministic Markdown compiler.

Supported:

* Single `AgentMakefile`
* YAML parsing
* `metadata`
* `compile.targets`
* `artifacts`
* `policies`
* `targets`
* `steps`
* `guards`
* `output_format`
* `compiler_hints`
* source schema validation
* source → IR normalization
* `claude-md` backend
* `agents-md` backend
* `cursor-rule` backend
* dry-run by default
* `--write` required to write files
* managed block support for `CLAUDE.md` and `AGENTS.md`

Out of scope:

* includes
* namespaces
* remote packages
* hard permissions
* hooks
* runtime target selection
* OpenCode backend
* Claude Code settings backend

MVP 0 success criterion:

```text
The Karpathy-inspired AgentMakefile example can compile with explicit MVP 0 targets:

  agentmf compile --target claude-md --target agents-md --target cursor-rule

and generate:

  CLAUDE.md
  AGENTS.md
  .cursor/rules/agentmakefile-generated.mdc
```

---

### 31.7 MVP 1 Scope

MVP 1 adds skill generation and soft permission output.

Supported:

* `skills` source section
* `claude-skill` backend
* `codex-skill` backend
* targets → skill packages
* policies → skill instructions
* steps → skill procedures
* output_format → skill output requirements
* permissions emitted as soft Markdown tables
* backend capability warnings

Example soft-permission warning:

```text
Warning: permissions will be emitted as soft instructions for cursor-rule.
```

Generated outputs:

```text
.claude/skills/<skill-name>/SKILL.md
.codex/skills/<skill-name>/SKILL.md
```

MVP 1 success criterion:

```text
The Karpathy and Superpowers minimal examples can compile into Claude/Codex skill directories.
```

---

### 31.8 MVP 2 Scope

MVP 2 adds local composition.

Supported:

* local `include`
* namespaced includes with `as`
* `extends`
* `add_policies`
* `add_steps`
* `add_output_format`
* deterministic merge semantics
* include graph validation
* circular include detection
* locked policy validation

Out of scope:

* remote packages
* public registry
* semantic version ranges
* package lockfiles

MVP 2 success criterion:

```text
A local project AgentMakefile can include a Karpathy-style policy pack and a security policy pack, then compile the merged result into Claude/Codex/Cursor outputs.
```

---

### 31.9 MVP 3 Scope

MVP 3 adds hard rails compiler targets.

Supported:

* `permissions` normalized into IR
* permission conflict resolution: `deny > ask > allow`
* glob matching validation
* backend capability warnings
* `claude-code` backend for settings and hooks where feasible
* `opencode` backend where feasible

Generated outputs may include:

```text
.claude/settings.json
.claude/hooks/*
opencode.json
```

MVP 3 success criterion:

```text
The unknown-repo security review example can compile into soft instructions plus platform-native permission or hook artifacts where the backend supports them.
```

---

#### 31.10 Source Schema: Initial Pydantic Models

Initial source model sketch:

```python
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

PermissionAction = Literal["allow", "ask", "deny"]

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

class CompileSpec(StrictModel):
    targets: list[str] = Field(default_factory=list)

class ArtifactSpec(StrictModel):
    path: str | None = None
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    managed_block: bool = True

class IncludeSpec(StrictModel):
    path: str | None = None
    package: str | None = None
    version: str | None = None
    as_: str | None = Field(default=None, alias="as")

    @model_validator(mode="after")
    def validate_include(self):
        if bool(self.path) == bool(self.package):
            raise ValueError("include must specify exactly one of path or package")
        if self.package is not None:
            raise ValueError("package includes are future-facing and disabled in the initial compiler")
        if self.version is not None and self.package is None:
            raise ValueError("version is only valid for package includes")
        return self

# Backward-compatible alias during early drafts.
OutputSpec = ArtifactSpec

class InputSpec(StrictModel):
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)

class PermissionSpec(StrictModel):
    defaults: dict[str, PermissionAction] = Field(default_factory=dict)
    rules: dict[str, dict[str, PermissionAction]] = Field(default_factory=dict)

# The source loader should accept both preferred and short-form permissions.
# Short form:
#   permissions:
#     bash:
#       "git status": allow
# Preferred normalized form:
#   permissions:
#     defaults:
#       bash: ask
#     rules:
#       bash:
#         "git status": allow
PermissionSource = PermissionSpec | dict[str, dict[str, PermissionAction]]

class PolicySpec(StrictModel):
    description: str | None = None
    applies_to: list[str] = Field(default_factory=list)
    guards: list[str | dict[str, Any]] = Field(default_factory=list)
    steps: list[str | dict[str, Any]] = Field(default_factory=list)
    output_format: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    locked: bool = False

class SkillSpec(StrictModel):
    namespace: str | None = None
    description: str | None = None
    implementation: dict[str, Any] = Field(default_factory=dict)
    inputs: InputSpec = Field(default_factory=InputSpec)
    match: dict[str, Any] = Field(default_factory=dict)
    steps: list[str | dict[str, Any]] = Field(default_factory=list)
    guards: list[str | dict[str, Any]] = Field(default_factory=list)
    output_format: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)

class TargetSpec(StrictModel):
    phony: bool = True
    priority: int = Field(default=50, ge=0, le=100)
    description: str | None = None
    inputs: InputSpec = Field(default_factory=InputSpec)
    match: dict[str, Any] = Field(default_factory=dict)
    policies: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    deps: list[str] = Field(default_factory=list)
    compile_to: str | None = None
    extends: str | None = None
    add_policies: list[str] = Field(default_factory=list)
    add_steps: list[str | dict[str, Any]] = Field(default_factory=list)
    add_output_format: list[str] = Field(default_factory=list)
    override: dict[str, Any] = Field(default_factory=dict)
    steps: list[str | dict[str, Any]] = Field(default_factory=list)
    guards: list[str | dict[str, Any]] = Field(default_factory=list)
    output_format: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    fallback: dict[str, list[str | dict[str, Any]]] = Field(default_factory=dict)

class AgentMakefileSource(StrictModel):
    version: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    include: list[str | IncludeSpec] = Field(default_factory=list)
    vars: dict[str, Any] = Field(default_factory=dict)
    compile: CompileSpec = Field(default_factory=CompileSpec)
    artifacts: dict[str, ArtifactSpec] = Field(default_factory=dict)
    outputs: dict[str, OutputSpec] = Field(default_factory=dict)  # deprecated alias for artifacts
    policies: dict[str, PolicySpec] = Field(default_factory=dict)
    skills: dict[str, SkillSpec] = Field(default_factory=dict)
    targets: dict[str, TargetSpec] = Field(default_factory=dict)
    permissions: PermissionSource = Field(default_factory=PermissionSpec)
    hooks: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    validation: dict[str, dict[str, Any]] = Field(default_factory=dict)
    patterns: dict[str, Any] = Field(default_factory=dict)  # future-facing, parse-preserve only
    cache: dict[str, Any] = Field(default_factory=dict)  # future-facing, parse-preserve only
    tool_rules: dict[str, Any] = Field(default_factory=dict)  # future-facing, parse-preserve only
    compiler_hints: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_artifact_alias_conflicts(self):
        duplicate_backends = set(self.artifacts).intersection(self.outputs)
        if duplicate_backends:
            names = ", ".join(sorted(duplicate_backends))
            raise ValueError(f"backend keys cannot appear in both artifacts and outputs: {names}")
        return self
```

MVP accepts string-based `steps` and `guards` for authoring convenience. Future versions should introduce typed step and guard objects while preserving compatibility.

`patterns`, `cache`, and `tool_rules` are parsed and preserved by the initial schema so documented future-facing examples do not fail validation, but MVP 0–2 backends should ignore them unless explicitly implemented.

---

### 31.11 IR Schema: Initial Models

Initial IR model sketch:

```python
class IRPolicy(StrictModel):
    name: str
    description: str | None = None
    applies_to: list[str] = Field(default_factory=list)
    guards: list[str | dict[str, Any]] = Field(default_factory=list)
    steps: list[str | dict[str, Any]] = Field(default_factory=list)
    output_format: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    locked: bool = False

class IRSkill(StrictModel):
    name: str
    qualified_name: str
    namespace: str | None = None
    description: str | None = None
    implementation: dict[str, Any] = Field(default_factory=dict)
    inputs: InputSpec = Field(default_factory=InputSpec)
    match: dict[str, Any] = Field(default_factory=dict)
    steps: list[str | dict[str, Any]] = Field(default_factory=list)
    guards: list[str | dict[str, Any]] = Field(default_factory=list)
    output_format: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)

class IRTarget(StrictModel):
    name: str
    phony: bool
    priority: int
    compile_to: str | None = None
    description: str | None = None
    inputs: InputSpec = Field(default_factory=InputSpec)
    match: dict[str, Any]
    policies: list[IRPolicy] = Field(default_factory=list)
    skills: list[IRSkill] = Field(default_factory=list)
    deps: list[str] = Field(default_factory=list)
    steps: list[str | dict[str, Any]] = Field(default_factory=list)
    guards: list[str | dict[str, Any]] = Field(default_factory=list)
    output_format: list[str] = Field(default_factory=list)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    fallback: dict[str, list[str | dict[str, Any]]] = Field(default_factory=dict)

class IRPermission(StrictModel):
    tool: str
    pattern: str
    action: PermissionAction

class AgentRuleIR(StrictModel):
    version: str
    metadata: dict[str, Any]
    vars: dict[str, Any]
    targets: list[IRTarget]
    policies: list[IRPolicy]
    skills: list[IRSkill]
    permission_defaults: dict[str, PermissionAction]
    permissions: list[IRPermission]
    hooks: dict[str, list[dict[str, Any]]]
    validation: dict[str, dict[str, Any]]
    artifacts: dict[str, ArtifactSpec]
    patterns: dict[str, Any]
    cache: dict[str, Any]
    tool_rules: dict[str, Any]
    compiler_hints: dict[str, Any]
```

Normalization should:

* turn dictionary keys into object names
* resolve local includes and merge included sources before normalizing targets, policies, skills, and permissions
* preserve `vars` and resolve `${...}` references in fields that support substitution
* apply target composition fields such as `extends`, `add_policies`, `add_steps`, `add_output_format`, and `override` before IR emission
* preserve target metadata such as `phony`, `priority`, `compile_to`, `description`, and `match`
* preserve policy applicability metadata such as `applies_to`
* resolve target policy references
* resolve target skill references
* qualify skill names with namespaces
* normalize `outputs` into `artifacts` when the deprecated alias is used, after validating that no backend key appears in both maps
* flatten permission rules into `(tool, pattern, action)` objects
* preserve future-facing `patterns`, `cache`, and `tool_rules` for diagnostics and later compiler phases
* preserve permission defaults in `permission_defaults` for backend emission
* preserve validation contracts
* preserve enough metadata for useful diagnostics

---

### 31.12 Backend Interface

All backends should implement the same interface.

```python
from dataclasses import dataclass
from abc import ABC, abstractmethod

@dataclass
class GeneratedFile:
    path: str
    content: str
    managed: bool = True
    backend: str | None = None

@dataclass
class BackendCapabilities:
    markdown: bool = True
    skills: bool = False
    permissions: str = "none"  # none | soft | hard
    hooks: bool = False
    hard_enforcement: bool = False

class Backend(ABC):
    name: str
    capabilities: BackendCapabilities

    @abstractmethod
    def emit(self, ir: AgentRuleIR) -> list[GeneratedFile]:
        ...
```

MVP 0 backends:

```text
claude-md
agents-md
cursor-rule
```

MVP 1 backends:

```text
claude-skill
codex-skill
skills-index
```

Future backends:

```text
claude-code
opencode
langgraph
openai-agents-sdk
dagger
```

---

### 31.13 Backend Output Rules

#### claude-md

Default output:

```text
CLAUDE.md
```

Behavior:

* generate managed block
* include global policies
* include target summaries
* include soft permission table if present (MVP 1+)
* warn when hard rails are lowered to soft rails (MVP 1+)

#### agents-md

Default output:

```text
AGENTS.md
```

Behavior:

* similar to `claude-md`
* wording should target generic coding agents
* avoid Claude-specific assumptions

#### cursor-rule

Default output:

```text
.cursor/rules/agentmakefile-generated.mdc
```

Behavior:

* emit Cursor frontmatter
* support `alwaysApply`
* include policies, targets, and skill-selection guidance

#### claude-skill

Default output:

```text
.claude/skills/<slug>/SKILL.md
```

Behavior:

* emit one skill per `skills` entry when present
* optionally emit one skill per target
* include when-to-use, procedure, guards, output format

#### codex-skill

Default output:

```text
.codex/skills/<slug>/SKILL.md
```

Behavior:

* same logical content as `claude-skill`
* avoid platform-specific wording unless needed

#### skills-index

Default output:

```text
skills/index.md
```

Behavior:

* emit one generated compatibility catalog for all normalized `skills` entries
* list descriptions, match rules, guards, steps, and output requirements
* include deterministic links to `.claude/skills/<slug>/SKILL.md` and
  `.codex/skills/<slug>/SKILL.md`
* include soft permission guidance when permissions are present
* treat the file as generated output; AgentMakefile remains the source of truth

#### skills scan

Input:

```text
<skills-dir>/*/SKILL.md
```

Behavior:

* parse existing skill package frontmatter, especially `name` and
  `description`
* infer `match.user_intent` terms from skill names, descriptions, and
  `## When to Use` bullets
* emit one AgentMakefile `skills` entry per scanned skill
* emit one `skill.*` target per scanned skill so runtime selection can route
  directly to a skill-backed target
* when a bootstrap skill is configured, emit that bootstrap target as a
  dependency of all other generated skill targets
* keep generated AgentMakefile output as an import/bridge path; curated modules
  can still replace it as the long-term source of truth

#### openclaw scan

Input:

```text
<openclaw-skills-dir>/**/SKILL.md
```

Behavior:

* recursively scan a local large skill ecosystem
* parse `name`, `description`, `category`, and `tags` frontmatter
* infer category from the first source path segment when frontmatter omits it
* generate category-prefixed skill names such as `coding.code-review` so
  duplicate original skill names can coexist
* append stable numeric suffixes when duplicate original names collide inside
  one category
* render one AgentMakefile per category and a root AgentMakefile index that
  includes those category modules
* emit deterministic curator evidence with skill counts, category counts,
  duplicate original names, and generated module paths
* keep remote registry fetching, semantic deduplication, promotion, and host
  skill installation outside the first importer slice

#### guidance scan

Input:

```text
AGENTS.md
CLAUDE.md
SKILL.md
<skills-dir>/*/SKILL.md
.cursor/rules/*.mdc
```

Behavior:

* generalize `skills scan` from native skill packages to broader prompt-prefix
  guidance sources
* treat `skills scan` as the `skill-dir` reader for compatibility
* import standalone `SKILL.md` files as real skill entries
* import `AGENTS.md` and `CLAUDE.md` as guidance-backed targets in the first
  slice, with section-level splitting deferred until provenance is stable
* store `implementation.source` and `implementation.source_type` for every
  imported unit
* infer `match.user_intent` terms from filenames, frontmatter, descriptions,
  headings, and "when to use" style sections
* emit `metadata.module_type: guidance-index` so downstream tools know the
  module was generated from existing host guidance

#### plugin install

Input:

```text
<skills-dir>/*/SKILL.md
AGENTS.md
CLAUDE.md
SKILL.md
```

Behavior:

* wrap `skills scan` and `guidance scan` for plugin installation
* optionally write the generated skill-index AgentMakefile to
  `.agentmf/plugin/AgentMakefile` or the caller's `--out` path
* return `model_instructions` telling the host/model to call
  `agentmf plugin payload` before selecting skills for each user request
* return `next_payload_command` so adapters can invoke the request-time
  selection path directly
* keep request-specific selection in `plugin payload`, not in the install step

#### skills sync

Input:

```text
AgentMakefile
```

Behavior:

* compile AgentMakefile skills into the selected host's native skill backend
* map `.codex/skills/<slug>/SKILL.md` to the Codex skill root for `codex`
* map `.claude/skills/<slug>/SKILL.md` to the Claude Code skill root for
  `claude-code`
* default to dry-run planning; only write installed skill files when `--write`
  is set
* refuse to overwrite existing changed installed skill files unless `--force`
  is set
* return host integration instructions that tell adapters to use
  `agentmf plugin payload` at request time for `selected_skills`,
  `skill_artifacts`, and `selection_trace`

---

### 31.14 Diagnostics and Error Quality

Diagnostics should be structured and human-readable.

Each diagnostic should include:

```text
severity: error | warning | info
code: stable machine-readable code
message: human-readable explanation
location: file path + YAML path if available
hint: suggested fix if available
```

Example:

```text
error[AMF102]: target code.task references unknown policy simplicity_first
  at AgentMakefile:targets.code.task.policies[1]
  hint: define policies.simplicity_first or remove it from the target.
```

Important diagnostic classes:

* invalid YAML
* schema validation error
* invalid include form or unsupported package include
* unknown backend target
* unknown policy reference
* unknown skill reference
* duplicate target after include merge
* circular include
* conflicting `artifacts` and deprecated `outputs` entries for the same backend
* conflicting CLI backend selection, such as `--all` combined with `--target`
* unsupported hard rail for backend
* unsafe overwrite without `--force`
* managed block missing or malformed

---

### 31.15 Testing Plan

Testing should be fixture-driven.

Core fixtures:

```text
tests/fixtures/karpathy/AgentMakefile
tests/fixtures/superpowers_minimal/AgentMakefile
tests/fixtures/unknown_repo_security/AgentMakefile
```

Core tests:

```text
test_validate_valid_files.py
test_validate_unknown_policy.py
test_validate_include_path.py
test_validate_package_include_disabled.py
test_validate_artifacts_outputs_conflict.py
test_validate_all_target_conflict.py
test_validate_short_form_permissions.py
test_parse_preserve_future_sections.py
test_compile_claude_md_snapshot.py
test_compile_agents_md_snapshot.py
test_compile_cursor_rule_snapshot.py
test_compile_claude_skill_snapshot.py
test_compile_codex_skill_snapshot.py
test_permissions_soft_warning.py
test_managed_block_insert.py
test_managed_block_update.py
```

Snapshot tests are appropriate for generated Markdown artifacts.

---

### 31.16 First Prototype Milestone

The first useful prototype should be able to run:

```bash
agentmf validate --file AgentMakefile
agentmf compile --file AgentMakefile --target claude-md --target agents-md --target cursor-rule --write
```

For the Karpathy-inspired example, it should generate:

```text
CLAUDE.md
AGENTS.md
.cursor/rules/agentmakefile-generated.mdc
```

The generated files should contain:

* project metadata
* policies
* target summaries
* steps
* guards
* output formats
* soft permission warnings if applicable
* managed block markers for shared files

This milestone proves the core value proposition:

```text
one structured skill source → multiple platform-native rule files
```
