"""
SnnDL python-side builders used by `sst_dram_si/mesh_template/build.py`.

`mesh_template` expects the package to expose two submodules:
  - `snndl_system.noc_merlin`
  - `snndl_system.mem_memhierarchy`

Those submodules provide the small set of functions that build Merlin NoC
routers/links and memHierarchy MemController/Bus plumbing.
"""

from . import mem_memhierarchy  # re-export module for build.py (attribute presence)
from . import noc_merlin  # re-export module for build.py (attribute presence)
from . import noc_multicast  # re-export module for build.py (attribute presence)

from .noc_merlin import (
    build_routers,
    connect_mesh_router_links,
    connect_nics_to_routers,
)

__all__ = [
    "mem_memhierarchy",
    "noc_merlin",
    "noc_multicast",
    "build_routers",
    "connect_mesh_router_links",
    "connect_nics_to_routers",
]
