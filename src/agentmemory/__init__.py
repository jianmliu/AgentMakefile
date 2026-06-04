"""agentmemory — a domain-agnostic agent-memory kernel.

The evidence -> proposal -> patch -> evaluate -> promote loop (plus Dream-style
offline consolidation), extracted from AgentMakefile's evolution/dream subsystems
with ZERO agentmf dependency. Domains plug in summarizers, appliers, gates, and
detectors; the kernel owns the loop, the data model, and the evidence store.

See docs/agentmemory_kernel_design.md.
"""
from agentmemory._util import (
    fingerprint,
    redact_secrets,
    sha256_json,
    sha256_text,
    utc_now,
)
from agentmemory.kernel import evaluate, generate_patch, promote, run_dream
from agentmemory.models import (
    Diagnostic,
    Diagnostics,
    Domain,
    EvidenceRecord,
    GateResult,
    Patch,
    Proposal,
)
from agentmemory.store import EvidenceStore, append_jsonl, read_jsonl

__all__ = [
    # data model
    "Diagnostic",
    "Diagnostics",
    "EvidenceRecord",
    "Proposal",
    "GateResult",
    "Patch",
    "Domain",
    # store
    "EvidenceStore",
    "append_jsonl",
    "read_jsonl",
    # loop
    "run_dream",
    "generate_patch",
    "evaluate",
    "promote",
    # utilities
    "fingerprint",
    "sha256_json",
    "sha256_text",
    "redact_secrets",
    "utc_now",
]
