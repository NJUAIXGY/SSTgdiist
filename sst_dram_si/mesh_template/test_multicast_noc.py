#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))


class _FakeComponent:
    def __init__(self, name: str, component_type: str) -> None:
        self.name = name
        self.component_type = component_type
        self.params = {}

    def addParams(self, params):
        self.params.update(dict(params))


class _FakeLink:
    def __init__(self, name: str) -> None:
        self.name = name
        self.connections = []

    def connect(self, left, right):
        self.connections.append((left, right))


class _FakeSST(types.SimpleNamespace):
    def __init__(self) -> None:
        super().__init__()
        self.links = []

    def Component(self, name: str, component_type: str):
        return _FakeComponent(name, component_type)

    def Link(self, name: str):
        link = _FakeLink(name)
        self.links.append(link)
        return link


sys.modules.setdefault("sst", _FakeSST())

build = importlib.import_module("sst_dram_si.mesh_template.build")
from mesh_template.config import apply_local_run_config_overrides
from mesh_template.legacy_defaults import make_default_state
from mesh_template import spec as mesh_spec  # type: ignore


class _FakeMulticastBackend:
    def __init__(self) -> None:
        self.calls = []

    def build_routers(self, node_limit, mesh_size, network_bandwidth, noc_type, **kwargs):
        self.calls.append((
            "build_routers",
            {
                "node_limit": node_limit,
                "mesh_size": mesh_size,
                "network_bandwidth": network_bandwidth,
                "noc_type": noc_type,
                **dict(kwargs),
            },
        ))
        return ["router0", "router1"]

    def connect_mesh_router_links(self, routers, mesh_size, noc_type, link_latency, **kwargs):
        self.calls.append((
            "connect_mesh_router_links",
            {
                "routers": list(routers),
                "mesh_size": mesh_size,
                "noc_type": noc_type,
                "link_latency": link_latency,
                **dict(kwargs),
            },
        ))
        return 2

    def connect_nics_to_routers(self, nics, routers, link_latency, noc_type, **kwargs):
        self.calls.append((
            "connect_nics_to_routers",
            {
                "nics": list(nics),
                "routers": list(routers),
                "link_latency": link_latency,
                "noc_type": noc_type,
                **dict(kwargs),
            },
        ))
        return 2


class MulticastMeshSpecTests(unittest.TestCase):
    def test_spec_accepts_multicast_mesh_and_storm_knobs(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "mesh",
            "platform": {"stop": {"mode": "step_limited", "max_steps": 1}},
            "noc": {
                "type": "multicast_mesh",
                "params": {
                    "link_bw": "40GiB/s",
                    "multicast_enable": True,
                    "multicast_block_w": 2,
                    "multicast_block_h": 2,
                    "multicast_ingress_policy": "top_left",
                    "multicast_inter_policy": "xy",
                    "multicast_intra_policy": "manhattan_x_first",
                    "local_endpoint_multicast_enable": True,
                },
            },
        }
        resolved = mesh_spec.resolve_spec(raw, defaults_state=make_default_state())
        state = resolved["state"]
        self.assertEqual(state["SPEC_NOC_TYPE"], "multicast_mesh")
        self.assertEqual(state["SPEC_MULTICAST_ENABLE"], True)
        self.assertEqual(int(state["SPEC_MULTICAST_BLOCK_W"]), 2)
        self.assertEqual(int(state["SPEC_MULTICAST_BLOCK_H"]), 2)
        self.assertEqual(state["SPEC_MULTICAST_INGRESS_POLICY"], "top_left")
        self.assertEqual(state["SPEC_MULTICAST_INTER_POLICY"], "xy")
        self.assertEqual(state["SPEC_MULTICAST_INTRA_POLICY"], "manhattan_x_first")
        self.assertEqual(state["SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE"], True)


class MulticastMeshConfigOverrideTests(unittest.TestCase):
    def test_local_run_config_accepts_multicast_knobs(self) -> None:
        state = make_default_state()
        cfg = {
            "noc_type": "multicast_mesh",
            "multicast_enable": True,
            "multicast_block_w": 2,
            "multicast_block_h": 2,
            "multicast_ingress_policy": "top_left",
            "multicast_inter_policy": "xy",
            "multicast_intra_policy": "manhattan_x_first",
            "local_endpoint_multicast_enable": True,
        }
        apply_local_run_config_overrides(
            cfg,
            state=state,
            script_dir=str(THIS_DIR.parent),
            default_stats_level=4,
            gas_merge_env_present=False,
            gas_inflight_env_present=False,
        )
        self.assertEqual(state["SPEC_NOC_TYPE"], "multicast_mesh")
        self.assertEqual(state["SPEC_MULTICAST_ENABLE"], True)
        self.assertEqual(int(state["SPEC_MULTICAST_BLOCK_W"]), 2)
        self.assertEqual(int(state["SPEC_MULTICAST_BLOCK_H"]), 2)
        self.assertEqual(state["SPEC_MULTICAST_INGRESS_POLICY"], "top_left")
        self.assertEqual(state["SPEC_MULTICAST_INTER_POLICY"], "xy")
        self.assertEqual(state["SPEC_MULTICAST_INTRA_POLICY"], "manhattan_x_first")
        self.assertEqual(state["SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE"], True)

    def test_env_override_accepts_multicast_knobs(self) -> None:
        state = make_default_state()
        with mock.patch.dict(
            "os.environ",
            {
                "MESH_NOC_TYPE": "multicast_mesh",
                "MESH_MULTICAST_ENABLE": "1",
                "MESH_MULTICAST_BLOCK_W": "2",
                "MESH_MULTICAST_BLOCK_H": "2",
                "MESH_MULTICAST_INGRESS_POLICY": "top_left",
                "MESH_MULTICAST_INTER_POLICY": "xy",
                "MESH_MULTICAST_INTRA_POLICY": "manhattan_x_first",
                "MESH_LOCAL_ENDPOINT_MULTICAST_ENABLE": "1",
            },
            clear=False,
        ):
            apply_local_run_config_overrides(
                {},
                state=state,
                script_dir=str(THIS_DIR.parent),
                default_stats_level=4,
                gas_merge_env_present=False,
                gas_inflight_env_present=False,
            )
        self.assertEqual(state["SPEC_NOC_TYPE"], "multicast_mesh")
        self.assertEqual(state["SPEC_MULTICAST_ENABLE"], True)
        self.assertEqual(int(state["SPEC_MULTICAST_BLOCK_W"]), 2)
        self.assertEqual(int(state["SPEC_MULTICAST_BLOCK_H"]), 2)
        self.assertEqual(state["SPEC_MULTICAST_INGRESS_POLICY"], "top_left")
        self.assertEqual(state["SPEC_MULTICAST_INTER_POLICY"], "xy")
        self.assertEqual(state["SPEC_MULTICAST_INTRA_POLICY"], "manhattan_x_first")
        self.assertEqual(state["SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE"], True)


class MulticastMeshBuildDispatchTests(unittest.TestCase):
    def test_build_mesh_routers_dispatches_to_multicast_backend(self) -> None:
        backend = _FakeMulticastBackend()
        with mock.patch.object(build.snndl_system, "noc_multicast", backend, create=True):
            routers = build.build_mesh_routers(
                node_limit=2,
                mesh_size=2,
                network_bandwidth="40GiB/s",
                noc_type="multicast_mesh",
            )
        self.assertEqual(routers, ["router0", "router1"])
        self.assertEqual(backend.calls[0][0], "build_routers")
        self.assertEqual(backend.calls[0][1]["noc_type"], "multicast_mesh")

    def test_connect_helpers_dispatch_to_multicast_backend(self) -> None:
        backend = _FakeMulticastBackend()
        with mock.patch.object(build.snndl_system, "noc_multicast", backend, create=True):
            router_links = build.connect_mesh_router_links(
                routers=["router0", "router1"],
                mesh_size=2,
                noc_type="multicast_mesh",
                link_latency="5ns",
            )
            nic_links = build.connect_nics_to_routers(
                nics=["nic0", "nic1"],
                routers=["router0", "router1"],
                disable_network=False,
                link_latency="5ns",
                noc_type="multicast_mesh",
            )
        self.assertEqual(router_links, 2)
        self.assertEqual(nic_links, 2)
        self.assertEqual([c[0] for c in backend.calls], [
            "connect_mesh_router_links",
            "connect_nics_to_routers",
        ])


if __name__ == "__main__":
    unittest.main()
