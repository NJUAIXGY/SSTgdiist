#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for offline DRAM cmd-cost model derivation.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
sys.path.insert(0, str(THIS_DIR.parent))


from mesh_template.gas_cmd_cost_offline_model import (  # type: ignore
    derive_dram_cmd_cost_from_ramulator2_cfg,
)


class GasCmdCostOfflineModelTest(unittest.TestCase):
    def test_derives_cmd_cost_for_ddr5(self) -> None:
        cfg = REPO_ROOT / "sst_dram_si" / "configs" / "ramulator2_ddr5.cfg"
        out = derive_dram_cmd_cost_from_ramulator2_cfg(
            ramulator2_cfg_file=str(cfg),
            line_bytes=64,
        )
        self.assertIn("derived_cmd_cost", out)
        dc = out["derived_cmd_cost"]
        self.assertIn("t_row_hit_ns", dc)
        self.assertIn("t_row_miss_ns", dc)
        self.assertGreaterEqual(int(dc["t_row_hit_ns"]), 1)
        self.assertGreaterEqual(int(dc["t_row_miss_ns"]), int(dc["t_row_hit_ns"]))


if __name__ == "__main__":
    unittest.main()
