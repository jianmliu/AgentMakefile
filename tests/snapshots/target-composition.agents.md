# target-composition-fixture - Generic Coding Agents

Generated from AgentMakefile. Keep project-specific edits outside this managed block.

## Package

Fixture covering target inheritance, additive fields, and explicit empty overrides.

## Policies

### parent_policy

#### Guards

- parent_guard

### child_policy

#### Guards

- child_guard

## Targets

### child.task

Child task.

- Priority: 0
- Phony: false

#### Policies

- child_policy

#### Steps

- child_step

#### Output format

- child_output

### parent.task

Parent task.

- Priority: 90
- Phony: true

#### Match

- `user_intent`: parent

#### Policies

- parent_policy

#### Steps

- parent_step

#### Output format

- parent_output
