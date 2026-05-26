# karpathy-coding-guidelines - Generic Coding Agents

Generated from AgentMakefile. Keep project-specific edits outside this managed block.

## Package

Test fixture that compiles the reusable Karpathy-style rule module.

## Policies

### think_before_coding

Do not assume or hide uncertainty. Surface assumptions, ambiguity, and tradeoffs before coding.

#### Applies to

- code.write
- code.review
- code.debug
- code.refactor
- architecture.discuss

#### Guards

- state_assumptions_explicitly
- ask_when_uncertain
- present_multiple_interpretations_when_ambiguous
- identify_simpler_options
- push_back_when_request_is_overcomplicated

### simplicity_first

Prefer the minimum code that solves the actual problem.

#### Applies to

- code.write
- code.refactor
- code.fix_bug

#### Guards

- avoid_unrequested_features
- avoid_speculative_abstractions
- avoid_single_use_abstractions
- prefer_clear_code_over_clever_code
- remove_unnecessary_complexity

### surgical_changes

Touch only what the task requires.

#### Applies to

- code.edit
- code.fix_bug
- code.refactor
- code.review

#### Guards

- avoid_drive_by_refactors
- preserve_existing_style
- do_not_rewrite_unrelated_code
- do_not_delete_dead_code_unless_asked
- ensure_every_changed_line_traces_to_user_request

### goal_driven_execution

Convert coding work into verifiable goals and close the loop with testing or explicit verification.

#### Applies to

- code.write
- code.fix_bug
- code.refactor
- code.review

#### Steps

- define_success_criteria
- identify_verification_method
- implement_minimal_change
- run_tests_or_explain_why_not
- summarize_result_against_success_criteria

## Skills

### karpathy-guidelines

Apply Karpathy-style coding guidelines for writing, reviewing, debugging, refactoring, testing, or discussing code.

#### Match

- `user_intent`: write code, fix bug, debug code, refactor code, review code, discuss architecture, write tests

#### Guards

- state_assumptions_explicitly
- avoid_unrequested_features
- preserve_existing_style
- do_not_rewrite_unrelated_code

#### Steps

- apply think_before_coding
- apply simplicity_first
- apply surgical_changes
- apply goal_driven_execution
- clarify_task_if_needed
- inspect_relevant_context
- make_minimal_change_or_recommendation
- verify_or_explain_verification_gap

#### Output format

- assumptions_or_clarifications
- plan_or_success_criteria
- minimal_solution
- verification_result
- changed_files_if_applicable

## Targets

### code.quick_fix

- Priority: 80
- Phony: true

#### Match

- `user_intent`: typo fix, one line fix, small obvious fix

#### Policies

- surgical_changes
- simplicity_first

#### Skills

- karpathy-guidelines

#### Guards

- skip_full_rigor_for_trivial_tasks
- do_not_over_explain
- make_smallest_safe_change

#### Steps

- use_skill=karpathy-guidelines
- select_context=include=active_file
- action=make_smallest_safe_change
- validate_output=concise_fix

#### Output format

- concise_fix
- verification_if_relevant

### code.task

- Priority: 70
- Phony: true

#### Match

- `user_intent`: write code, fix bug, debug code, refactor code, review code, discuss architecture, write tests

#### Policies

- think_before_coding
- simplicity_first
- surgical_changes
- goal_driven_execution

#### Skills

- karpathy-guidelines

#### Steps

- use_skill=karpathy-guidelines
- select_context=include=active_file, git.diff
- link_prompt=fragment=karpathy.guidelines
- action=clarify_task_if_needed
- action=state_assumptions_and_success_criteria
- action=inspect_relevant_context
- action=make_minimal_change_or_recommendation
- validate_output=verification_result
- action=verify_or_explain_verification_gap
- action=summarize_changes_and_risks

#### Output format

- assumptions_or_clarifications
- plan_or_success_criteria
- minimal_solution
- verification_result
- changed_files_if_applicable

## Permission Guidance

These permissions are soft instructions unless the selected backend supports native enforcement.

### Rules

| Tool | Pattern | Action |
| --- | --- | --- |
| bash | * | ask |
| bash | git diff* | allow |
| bash | git status | allow |
| bash | npm install* | ask |
| bash | npm run test* | ask |
| bash | npm test | ask |
| bash | pnpm install* | ask |
| bash | rm -rf * | deny |
| bash | yarn install* | ask |
| file_write | **/*secret* | deny |
| file_write | .env | deny |
| file_write | package-lock.json | ask |
| file_write | package.json | ask |
| file_write | src/** | allow |
| file_write | tests/** | allow |
