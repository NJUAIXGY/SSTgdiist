from __future__ import annotations

import unittest
from pathlib import Path

from sst_dram_si.mesh_template.config import resolve_input_path_under_project


class RuntimeInputPathResolutionTests(unittest.TestCase):
    def test_repo_relative_sst_dram_si_prefix_resolves_under_project(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        script_dir = repo_root / "sst_dram_si"
        raw = "sst_dram_si/weights/gcss_valueonly_dstcore_idx2_rowmphf_fanout256_10k_v2_j32"
        resolved = resolve_input_path_under_project(raw, script_dir=str(script_dir))
        self.assertEqual(
            resolved,
            str(script_dir / "weights/gcss_valueonly_dstcore_idx2_rowmphf_fanout256_10k_v2_j32"),
        )


if __name__ == "__main__":
    unittest.main()
