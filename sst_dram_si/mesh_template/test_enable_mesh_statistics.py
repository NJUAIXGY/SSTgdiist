#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
import types
import unittest


class _FakeStatsTarget:
    def __init__(self) -> None:
        self.enabled_calls = []
        self.named_calls = []

    def enableAllStatistics(self, cfg):
        self.enabled_calls.append(cfg)

    def enableStatistics(self, names):
        self.named_calls.append(list(names))


class EnableMeshStatisticsTest(unittest.TestCase):
    def _load_build(self):
        sys.modules.setdefault("sst", types.SimpleNamespace())
        mod = importlib.import_module("sst_dram_si.mesh_template.build")
        return importlib.reload(mod)

    def test_enable_accumulator_statistics_uses_accumulator_backend(self) -> None:
        build = self._load_build()
        target = _FakeStatsTarget()

        build.enable_accumulator_statistics(target)

        self.assertEqual(target.enabled_calls, [{"type": "sst.AccumulatorStatistic"}])

    def test_enable_mesh_statistics_keeps_node_and_router_behavior(self) -> None:
        build = self._load_build()
        node = _FakeStatsTarget()
        router = _FakeStatsTarget()

        build.enable_mesh_statistics(nodes=[node], routers=[router])

        self.assertEqual(node.enabled_calls, [{"type": "sst.AccumulatorStatistic"}])
        self.assertEqual(router.named_calls, [["router.packet_count", "router.network_load"]])


if __name__ == "__main__":
    unittest.main()
