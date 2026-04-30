#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path


class WeightL0ExplicitCachePlumbingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo = Path(__file__).resolve().parents[2]
        self.header = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h"
        self.source = self.repo / "sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc"

    def test_weight_l0_uses_explicit_cache_object(self) -> None:
        header_text = self.header.read_text(encoding="utf-8")
        source_text = self.source.read_text(encoding="utf-8")

        self.assertIn('"WeightCacheOps.h"', header_text)
        self.assertIn('WeightCacheOps experimental_idx2_ingress_l0_cache_', header_text)
        self.assertNotIn('experimental_idx2_ingress_value_cache_', header_text)
        self.assertNotIn('experimental_idx2_ingress_value_cache_lru_', header_text)
        self.assertIn('experimental_idx2_ingress_l0_cache_.tryGet', source_text)
        self.assertIn('experimental_idx2_ingress_l0_cache_.store', source_text)
        self.assertIn('experimental_idx2_ingress_l0_cache_entries_', header_text)
        self.assertIn('experimental_idx2_ingress_l0_resident_bytes_', header_text)


if __name__ == "__main__":
    unittest.main()
