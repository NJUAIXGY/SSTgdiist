#!/usr/bin/env python3

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple


class _FakeComponent:
    def __init__(self, name: str, component_type: str) -> None:
        self.name = str(name)
        self.component_type = str(component_type)
        self.params: Dict[str, Any] = {}
        self.subcomponents: Dict[str, "_FakeComponent"] = {}

    def addParams(self, params: Dict[str, Any]) -> None:
        self.params.update(dict(params))

    def setSubComponent(self, slot: str, component_type: str) -> "_FakeComponent":
        sub = _FakeComponent(f"{self.name}.{slot}", component_type)
        self.subcomponents[str(slot)] = sub
        return sub

    def enableAllStatistics(self, _params: Dict[str, Any]) -> None:
        return

    def enableStatistics(self, _stats: List[str]) -> None:
        return


class _FakeLink:
    def __init__(self, name: str) -> None:
        self.name = str(name)
        self.connections: List[Tuple[Any, Any]] = []

    def connect(self, a: Any, b: Any) -> None:
        self.connections.append((a, b))


class _FakeSST:
    def __init__(self) -> None:
        self.components: Dict[str, _FakeComponent] = {}
        self.links: List[_FakeLink] = []

    def Component(self, name: str, component_type: str) -> _FakeComponent:
        comp = _FakeComponent(name, component_type)
        self.components[str(name)] = comp
        return comp

    def Link(self, name: str) -> _FakeLink:
        link = _FakeLink(name)
        self.links.append(link)
        return link


# Ensure `import tensor_template...` works when running from repo root.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

# Inject fake `sst` module before importing tensor_template.build.
_fake = _FakeSST()
sys.modules["sst"] = types.SimpleNamespace(Component=_fake.Component, Link=_fake.Link)


from tensor_template.build import build_tensor_mesh_4x4  # noqa: E402


class TensorOverridesApplyTest(unittest.TestCase):
    def test_overrides_applied_to_pe_and_nic(self) -> None:
        mesh_cfg = {
            "pe_mem_region_bytes": 1024,
            "network_bandwidth": "40GiB/s",
            "buffer_size": "8KiB",
            "network_num_vns": 2,
            "noc_type": "merlin_mesh",
            "num_cores_per_pe": 1,
            "neurons_per_core": 4,
            "neurons_per_pe": 4,
            "total_nodes": 1,
            "core_mem_region_bytes": 256,
            "mem_access_time": "100ns",
            "workload_stats_modules": "tensor",
        }
        tensor_cfg = {"tensor_m": 256, "tensor_n": 256, "tensor_k": 256}
        overrides = [
            {"match": {"role": "pe"}, "params": {"verbose": 7}},
            {"match": {"role": "pe.nic", "tags": {"pe": 0}}, "params": {"verbose": 5}},
        ]

        built = build_tensor_mesh_4x4(
            run_output_dir="/tmp/out",
            node_limit=1,
            mesh_size=1,
            mesh_cfg=mesh_cfg,
            tensor_cfg=tensor_cfg,
            overrides=overrides,
        )

        nodes = list(built["nodes"])
        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].name, "pe_0")
        self.assertEqual(nodes[0].params["verbose"], 7)
        nic = nodes[0].subcomponents["network_interface"]
        self.assertEqual(nic.params["verbose"], 5)


if __name__ == "__main__":
    unittest.main()
