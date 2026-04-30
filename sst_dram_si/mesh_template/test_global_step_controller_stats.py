#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
import types
import unittest


class _FakeComponent:
    def __init__(self, name: str, comp_type: str) -> None:
        self.name = name
        self.comp_type = comp_type
        self.params = []
        self.enable_calls = []

    def addParams(self, params):
        self.params.append(dict(params))

    def enableAllStatistics(self, cfg):
        self.enable_calls.append(dict(cfg))


class _FakeSstModule:
    def __init__(self) -> None:
        self.components = []

    def Component(self, name, comp_type):
        c = _FakeComponent(name, comp_type)
        self.components.append(c)
        return c


class GlobalStepControllerStatsTest(unittest.TestCase):
    def _load_build(self, fake_sst):
        sys.modules["sst"] = fake_sst
        mod = importlib.import_module("sst_dram_si.mesh_template.build")
        return importlib.reload(mod)

    def test_build_global_gas_step_controller_enables_stats(self) -> None:
        fake_sst = _FakeSstModule()
        build = self._load_build(fake_sst)

        ctrl = build.build_global_gas_step_controller(enabled=True, verbose=0)

        self.assertIsNotNone(ctrl)
        self.assertEqual(ctrl.enable_calls, [{"type": "sst.AccumulatorStatistic"}])


if __name__ == "__main__":
    unittest.main()
