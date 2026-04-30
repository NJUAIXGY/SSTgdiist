#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path


class SramPeAggregationPlumbingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[2]
        self.ipath = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/api/IPeAggregation.h"
        self.pe_h = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h"
        self.pe_cc = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc"

    def test_new_sram_stats_are_plumbed_through_pe_aggregation(self) -> None:
        stats = [
            "weight_idx_sram_bank_peak_accesses_per_tick",
            "weight_idx_sram_energy_read_pj_total",
            "weight_idx_sram_energy_write_pj_total",
            "weight_l0_sram_bank_peak_accesses_per_tick",
            "weight_l0_sram_energy_read_pj_total",
            "weight_l0_sram_energy_write_pj_total",
            "weight_sram_enforced_stall_cycles_total",
            "core_state_sram_bank_peak_accesses_per_tick",
            "core_state_sram_energy_read_pj_total",
            "core_state_sram_energy_write_pj_total",
            "core_state_sram_stall_cycles_total",
        ]
        ipath_text = self.ipath.read_text(encoding="utf-8")
        pe_h_text = self.pe_h.read_text(encoding="utf-8")
        pe_cc_text = self.pe_cc.read_text(encoding="utf-8")

        for stat in stats:
            self.assertIn(stat, ipath_text, msg=f"{stat} missing from IPeAggregation.h")
            self.assertIn(stat, pe_h_text, msg=f"{stat} missing from MultiCorePE.h")
            self.assertIn(stat, pe_cc_text, msg=f"{stat} missing from MultiCorePE.cc")


if __name__ == "__main__":
    unittest.main()
