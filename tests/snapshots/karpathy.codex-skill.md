---
name: karpathy-guidelines
description: Apply Karpathy-style coding guidelines for writing, reviewing, debugging, refactoring, testing, or discussing code.
metadata:
  cost:
    tokens: 366
---

# karpathy-guidelines

## Overview

Apply Karpathy-style coding guidelines for writing, reviewing, debugging, refactoring, testing, or discussing code.

## When To Use

- `user_intent`: write code, fix bug, debug code, refactor code, review code, discuss architecture, write tests

## Guards

- state_assumptions_explicitly
- avoid_unrequested_features
- preserve_existing_style
- do_not_rewrite_unrelated_code

## Procedure

- apply think_before_coding
- apply simplicity_first
- apply surgical_changes
- apply goal_driven_execution
- clarify_task_if_needed
- inspect_relevant_context
- make_minimal_change_or_recommendation
- verify_or_explain_verification_gap

## Output Requirements

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
