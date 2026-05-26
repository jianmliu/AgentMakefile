# Runtime Walkthrough Plan

Goal: demonstrate how AgentMakefile turns structured module rules into a
request-specific prompt prefix and runtime contract.

Steps:

1. Validate the demo AgentMakefile.
2. Compile static and fragment outputs without writing files.
3. Select the runtime walkthrough target from a request.
4. Inspect permission decisions for safe and unsafe commands.
5. Validate both invalid and valid structured output.
6. Build a final prompt with this plan and an explicit context file.
7. Generate plugin and provider payloads.
8. Run the gated exec prototype for an allowed command and a blocked command.

Expected result: the stable prompt prefix is deterministic, volatile context is
separate, unsafe tool calls are blocked or routed through fallback handling, and
JSON output validation reports schema failures precisely.
