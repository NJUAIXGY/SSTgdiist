#!/usr/bin/env python3

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sst_dram_si.runtime_paths as runtime_paths


class RuntimePathsTests(unittest.TestCase):
    def test_resolve_singlepe_ramulator2_config_prefers_repo_local_memhierarchy_cfg(self) -> None:
        script_dir = Path("/home/xgy/remote/sst_dram_si")
        resolved = Path(runtime_paths.resolve_singlepe_ramulator2_config(str(script_dir)))
        expected = Path("/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/memHierarchy/tests/ramulator2-ddr4.cfg")
        self.assertEqual(resolved, expected)
        self.assertTrue(resolved.is_file())

    def test_resolve_singlepe_ramulator2_config_falls_back_to_local_cfg_when_repo_memhierarchy_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td) / "repo"
            script_dir = repo_root / "sst_dram_si"
            local_cfg = script_dir / "configs" / "ramulator2_ddr4_openrow.cfg"
            local_cfg.parent.mkdir(parents=True, exist_ok=True)
            local_cfg.write_text("cfg", encoding="utf-8")

            resolved = Path(runtime_paths.resolve_singlepe_ramulator2_config(str(script_dir)))
            self.assertEqual(resolved, local_cfg)

    def test_resolve_singlepe_mc_mem_size_exposes_helper_and_expands_when_weight_footprint_overflows(self) -> None:
        resolver = getattr(runtime_paths, "resolve_singlepe_mc_mem_size", None)
        self.assertIsNotNone(resolver)
        if resolver is None:
            return

        effective_text, effective_bytes = resolver(
            configured_mem_size="64MiB",
            weight_stride_bytes=20_054_016,
            num_cores=20,
            base_addr_start=0,
        )

        self.assertEqual(effective_text, "383MiB")
        self.assertEqual(effective_bytes, 383 * 1024 * 1024)

    def test_resolve_singlepe_mc_mem_size_keeps_user_mem_size_when_already_sufficient(self) -> None:
        resolver = getattr(runtime_paths, "resolve_singlepe_mc_mem_size", None)
        self.assertIsNotNone(resolver)
        if resolver is None:
            return

        effective_text, effective_bytes = resolver(
            configured_mem_size="512MiB",
            weight_stride_bytes=20_054_016,
            num_cores=20,
            base_addr_start=0,
        )

        self.assertEqual(effective_text, "512MiB")
        self.assertEqual(effective_bytes, 512 * 1024 * 1024)

    def test_resolve_singlepe_spike_dataset_prefers_github_submission_layout_when_repo_root_layout_missing(self) -> None:
        resolver = getattr(runtime_paths, "resolve_singlepe_spike_dataset", None)
        self.assertIsNotNone(resolver)
        if resolver is None:
            return

        resolved = Path(resolver("/home/xgy/remote/sst_dram_si"))
        expected = Path("/home/xgy/remote/github_submission/SnnDL_Basic/spike_data/complex_input_pe_0_class_A.txt")
        self.assertEqual(resolved, expected)
        self.assertTrue(resolved.is_file())

    def test_resolve_singlepe_spike_dataset_respects_relative_override(self) -> None:
        resolver = getattr(runtime_paths, "resolve_singlepe_spike_dataset", None)
        self.assertIsNotNone(resolver)
        if resolver is None:
            return

        resolved = Path(resolver("/tmp/demo/sst_dram_si", "datasets/demo.txt"))
        expected = Path("/tmp/demo/sst_dram_si/datasets/demo.txt")
        self.assertEqual(resolved, expected)


if __name__ == "__main__":
    unittest.main()
