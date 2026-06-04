"""aigg_memory — a domain-agnostic agent-memory kernel.

The evidence -> proposal -> patch -> evaluate -> promote loop (plus Dream-style
offline consolidation), extracted from AgentMakefile's evolution/dream subsystems
with ZERO agentmf dependency. Domains plug in summarizers, appliers, gates, and
detectors; the kernel owns the loop, the data model, and the evidence store.

See docs/aigg_memory_kernel_design.md.
"""
from aigg_memory._util import (
    fingerprint,
    redact_secrets,
    sha256_json,
    sha256_text,
    utc_now,
)
from aigg_memory.kernel import evaluate, generate_patch, promote, run_dream
from aigg_memory.models import (
    Diagnostic,
    Diagnostics,
    Domain,
    EvidenceRecord,
    GateResult,
    Patch,
    Proposal,
)
from aigg_memory.store import EvidenceStore, append_jsonl, read_jsonl

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
