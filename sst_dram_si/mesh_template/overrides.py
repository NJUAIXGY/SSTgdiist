from __future__ import annotations

"""
Compatibility wrapper: mesh_template overrides engine.

The canonical implementation lives in `snndl_spec.overrides` to keep the
selector/override contract consistent across workloads (mesh/tensor/...).
"""

from snndl_spec.overrides import OverrideEngine
from snndl_spec.overrides import OverrideHit

__all__ = [
    "OverrideEngine",
    "OverrideHit",
]

