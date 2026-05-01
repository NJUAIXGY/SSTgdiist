from __future__ import annotations

import unittest
from typing import Any, Dict, List, Tuple

from snndl_system import mem_memhierarchy
from snndl_system import noc_merlin


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


class _FakeLink:
    def __init__(self, name: str) -> None:
        self.name = str(name)
        self.connections: List[Tuple[Any, Any]] = []

    def connect(self, a: Any, b: Any) -> None:
        self.connections.append((a, b))


class _FakeSST:
    def __init__(self) -> None:
        self.components: List[_FakeComponent] = []
        self.links: List[_FakeLink] = []

    def Component(self, name: str, component_type: str) -> _FakeComponent:
        comp = _FakeComponent(name, component_type)
        self.components.append(comp)
        return comp

    def Link(self, name: str) -> _FakeLink:
        link = _FakeLink(name)
        self.links.append(link)
        return link


class _OverrideEngineStub:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def apply(
        self,
        *,
        role: str,
        component_type: str,
        name: str,
        tags: Dict[str, Any],
        base_params: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        self.calls.append(
            {
                "role": str(role),
                "component_type": str(component_type),
                "name": str(name),
                "tags": dict(tags),
                "base_params": dict(base_params),
            }
        )
        final_params = dict(base_params)
        hits: List[Dict[str, Any]] = []
        if role == "router" and tags.get("node") == 0:
            final_params["debug"] = 7
            hits.append({"rule": "router_debug_node0"})
        if role == "router.topology" and component_type == "merlin.mesh":
            final_params["local_ports"] = "2"
            hits.append({"rule": "topo_local_ports"})
        if role == "pe_mem_controller" and tags.get("pe") == 0:
            final_params["clock"] = "2GHz"
            hits.append({"rule": "memctrl_clock"})
        if role == "pe_mem_controller.backend" and tags.get("pe") == 0:
            final_params["access_time"] = "50ns"
            hits.append({"rule": "backend_access_time"})
        return final_params, hits


class MerlinNoCBuilderTest(unittest.TestCase):
    def test_build_merlin_routers_creates_topology(self) -> None:
        fake = _FakeSST()
        routers = noc_merlin.build_merlin_routers(
            node_limit=4,
            mesh_size=2,
            network_bandwidth="40GiB/s",
            noc_type="merlin_mesh",
            sst_module=fake,
        )
        self.assertEqual(len(routers), 4)
        self.assertEqual(routers[0].component_type, "merlin.hr_router")
        self.assertEqual(routers[0].params["id"], 0)
        self.assertIn("topology", routers[0].subcomponents)
        self.assertEqual(routers[0].subcomponents["topology"].component_type, "merlin.mesh")
        self.assertEqual(routers[0].subcomponents["topology"].params["shape"], "2x2")

    def test_build_routers_applies_overrides_and_reports(self) -> None:
        fake = _FakeSST()
        override = _OverrideEngineStub()
        report: List[Dict[str, Any]] = []
        routers = noc_merlin.build_routers(
            node_limit=4,
            mesh_size=2,
            network_bandwidth="40GiB/s",
            noc_type="merlin_mesh",
            topo_type="merlin.mesh",
            router_params={
                "num_ports": 5,
                "link_bw": "40GiB/s",
                "flit_size": "32B",
                "xbar_bw": "40GiB/s",
                "input_latency": "10ns",
                "output_latency": "10ns",
                "input_buf_size": "4KiB",
                "output_buf_size": "4KiB",
                "num_vns": 1,
                "xbar_arb": "merlin.xbar_arb_lru",
                "debug": 0,
                "verbose": 0,
                "network_inspectors": "",
            },
            topology_params={"shape": "2x2", "width": "1x1", "local_ports": "1"},
            override_engine=override,
            override_report=report,
            sst_module=fake,
        )
        self.assertEqual(routers[0].params["debug"], 7)
        self.assertEqual(routers[0].subcomponents["topology"].params["local_ports"], "2")
        self.assertTrue(any(e.get("role") == "router" for e in report))
        self.assertTrue(any(e.get("role") == "router.topology" for e in report))

    def test_connect_mesh_router_links_counts_mesh(self) -> None:
        fake = _FakeSST()
        routers = noc_merlin.build_merlin_routers(
            node_limit=4,
            mesh_size=2,
            network_bandwidth="40GiB/s",
            noc_type="merlin_mesh",
            sst_module=fake,
        )
        count = noc_merlin.connect_mesh_router_links(
            routers=routers,
            mesh_size=2,
            noc_type="merlin_mesh",
            sst_module=fake,
        )
        self.assertEqual(count, 4)
        self.assertEqual(len(fake.links), 4)

    def test_connect_mesh_router_links_counts_torus(self) -> None:
        fake = _FakeSST()
        routers = noc_merlin.build_merlin_routers(
            node_limit=4,
            mesh_size=2,
            network_bandwidth="40GiB/s",
            noc_type="merlin_torus",
            sst_module=fake,
        )
        count = noc_merlin.connect_mesh_router_links(
            routers=routers,
            mesh_size=2,
            noc_type="merlin_torus",
            sst_module=fake,
        )
        self.assertEqual(count, 8)
        self.assertEqual(len(fake.links), 8)

    def test_connect_mesh_router_links_counts_rectangular_shape(self) -> None:
        fake = _FakeSST()
        routers = [fake.Component(f"router_{i}", "merlin.hr_router") for i in range(16)]

        count_mesh = noc_merlin.connect_mesh_router_links(
            routers=routers,
            mesh_size=4,
            noc_type="merlin_mesh",
            shape="2x8",
            sst_module=fake,
        )
        self.assertEqual(count_mesh, 22)
        self.assertEqual(len(fake.links), 22)

        # reset links for the torus case
        fake.links = []
        count_torus = noc_merlin.connect_mesh_router_links(
            routers=routers,
            mesh_size=4,
            noc_type="merlin_torus",
            shape="2x8",
            sst_module=fake,
        )
        self.assertEqual(count_torus, 32)
        self.assertEqual(len(fake.links), 32)

    def test_connect_nics_to_routers_counts(self) -> None:
        fake = _FakeSST()
        routers = [fake.Component(f"router_{i}", "merlin.hr_router") for i in range(4)]
        nics = [fake.Component(f"nic_{i}", "SnnDL.SnnNIC") for i in range(3)]
        count = noc_merlin.connect_nics_to_routers(
            nics=nics,
            routers=routers,
            link_latency="5ns",
            sst_module=fake,
        )
        self.assertEqual(count, 3)
        self.assertEqual(len(fake.links), 3)


class MemHierarchyBuilderTest(unittest.TestCase):
    def test_build_pe_memory_systems_simple(self) -> None:
        fake = _FakeSST()
        controllers, buses = mem_memhierarchy.build_pe_memory_systems(
            node_limit=2,
            pe_mem_region_bytes=1024,
            mem_access_time="100ns",
            sst_module=fake,
        )
        self.assertEqual(len(controllers), 2)
        self.assertEqual(len(buses), 2)
        self.assertEqual(controllers[0].component_type, "memHierarchy.MemController")
        self.assertEqual(controllers[0].params["addr_range_start"], "0")
        self.assertEqual(controllers[1].params["addr_range_start"], str(1024))
        self.assertIn("backend", controllers[0].subcomponents)
        self.assertEqual(controllers[0].subcomponents["backend"].component_type, "memHierarchy.simpleMem")
        self.assertEqual(controllers[0].subcomponents["backend"].params["mem_size"], "1024B")
        self.assertEqual(len(fake.links), 2)

    def test_build_pe_memory_systems_multi_channel(self) -> None:
        fake = _FakeSST()
        controllers, buses = mem_memhierarchy.build_pe_memory_systems(
            node_limit=1,
            pe_mem_region_bytes=1024,
            mem_access_time="100ns",
            num_mem_channels=4,
            sst_module=fake,
        )
        self.assertEqual(len(buses), 1)
        self.assertEqual(len(controllers), 4)
        self.assertEqual(controllers[0].params["addr_range_start"], "0")
        self.assertEqual(controllers[1].params["addr_range_start"], str(256))
        self.assertEqual(controllers[2].params["addr_range_start"], str(512))
        self.assertEqual(controllers[3].params["addr_range_start"], str(768))
        self.assertEqual(controllers[0].subcomponents["backend"].params["mem_size"], "256B")
        self.assertEqual(len(fake.links), 4)

    def test_build_pe_memory_systems_applies_overrides(self) -> None:
        fake = _FakeSST()
        override = _OverrideEngineStub()
        report: List[Dict[str, Any]] = []
        controllers, _buses = mem_memhierarchy.build_pe_memory_systems(
            node_limit=1,
            pe_mem_region_bytes=1024,
            mem_access_time="100ns",
            override_engine=override,
            override_report=report,
            sst_module=fake,
        )
        self.assertEqual(controllers[0].params["clock"], "2GHz")
        backend = controllers[0].subcomponents["backend"]
        self.assertEqual(backend.params["access_time"], "50ns")
        self.assertTrue(any(e.get("role") == "pe_mem_controller" for e in report))


if __name__ == "__main__":
    unittest.main()
