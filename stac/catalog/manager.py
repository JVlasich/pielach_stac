"""load/merge/write, extents, summaries, idempotency gate"""

from pathlib import Path

import yaml


def load_sidecar(path) -> dict:
    """Read a per-campaign sidecar YAML into a dict (collection / patterns / labels blocks)."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}

# Pipeline glue (when wiring discovery per campaign):
#   from ..core.registry import merge_overrides
#   sc = load_sidecar(p)
#   sp, lb = merge_overrides(sc.get("patterns"), sc.get("labels"))
#   discover(folder, policy, sp, lb)