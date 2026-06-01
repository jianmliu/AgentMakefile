"""External pricing-table loader (token → USD bridge, externally configurable).

Pricing changes; hard-coding rates in an AgentMakefile module is wrong. This
module loads a small YAML/JSON pricing table keyed by model name, and resolves
a model's pricing dict for use by TokenBudget and the selector.

Resolution order (so projects can override at any layer):
    inline `models.<name>.pricing`  >  external pricing table  >  none

Table format:

    version: 1
    source: "anthropic public list, 2026-Q2"      # provenance, optional
    note: "advisory; +20-30% buffer; cache tiers not modeled"
    models:
      haiku-fast: {input_per_mtok: 1.0, output_per_mtok: 5.0}
      opus-deep:  {input_per_mtok: 15.0, output_per_mtok: 75.0}
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml


def load_pricing_table(path: Union[Path, str]) -> Dict[str, Any]:
    """Load a pricing-table YAML/JSON file. Returns {} when the file is missing."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    return loaded


def resolve_pricing(table: Dict[str, Any], model_name: str) -> Optional[Dict[str, float]]:
    """Look up pricing for `model_name`; return None if not present."""
    if not table:
        return None
    models = table.get("models") or {}
    entry = models.get(model_name)
    if not isinstance(entry, dict):
        return None
    out: Dict[str, float] = {}
    for k in ("input_per_mtok", "output_per_mtok"):
        v = entry.get(k)
        if isinstance(v, (int, float)):
            out[k] = float(v)
    return out or None
