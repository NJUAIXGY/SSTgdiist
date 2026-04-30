#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path


class StateSramLayoutTimingPlumbingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[2]
        self.header = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/compute/SnnComputeCore.h"
        self.source = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/compute/SnnComputeCore.cc"

    def test_state_path_uses_layout_aware_reads_and_writes(self) -> None:
        header_text = self.header.read_text(encoding="utf-8")
        source_text = self.source.read_text(encoding="utf-8")

        self.assertNotIn('noteBulkUniform(', source_text)
        self.assertIn('state_sram_layout_.stateVmemAddr', source_text)
        self.assertIn('state_sram_layout_.stateRefracAddr', source_text)
        self.assertIn('state_sram_layout_.stateLastSpikeAddr', source_text)
        self.assertIn('void noteStateSramRead_', header_text)
        self.assertIn('void noteStateSramWrite_', header_text)
        self.assertIn('state_sram_model_.noteRead', source_text)
        self.assertIn('state_sram_model_.noteWrite', source_text)


if __name__ == "__main__":
    unittest.main()
