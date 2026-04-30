#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for the overrides rule engine (pure Python).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))


from mesh_template import overrides as ov  # type: ignore


class OverridesEngineTest(unittest.TestCase):
    def test_applies_rules_in_order(self) -> None:
        rules = [
            {"match": {"role": "router"}, "params": {"debug": 1}},
            {"match": {"type": "memHierarchy.MemController"}, "params": {"clock": "2GHz"}},
            {"match": {"name": "router_0"}, "params": {"id": 999}},
        ]
        eng = ov.OverrideEngine(rules)

        final_params, hits = eng.apply(
            role="router",
            component_type="merlin.hr_router",
            name="router_0",
            tags={"node": 0},
            base_params={"id": 0, "debug": 0, "foo": "bar"},
        )

        self.assertEqual(final_params["debug"], 1)
        self.assertEqual(final_params["id"], 999)
        self.assertEqual(final_params["foo"], "bar")
        self.assertGreaterEqual(len(hits), 2)

    def test_strict_unmatched_rule_fails_finalize(self) -> None:
        rules = [
            {"match": {"role": "router"}, "params": {"debug": 1}},
            {"match": {"role": "pe", "name": "must_hit"}, "params": {"verbose": 1}, "strict": True},
        ]
        eng = ov.OverrideEngine(rules)
        _params, _hits = eng.apply(
            role="router",
            component_type="merlin.hr_router",
            name="router_0",
            tags={},
            base_params={"id": 0},
        )
        with self.assertRaises(ValueError):
            eng.finalize()


if __name__ == "__main__":
    unittest.main()

