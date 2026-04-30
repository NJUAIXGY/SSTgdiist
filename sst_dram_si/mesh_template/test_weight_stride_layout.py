import tempfile
import unittest
from pathlib import Path

from sst_dram_si.mesh_template import bcsr
from sst_dram_si.mesh_template.utils import align_up


class WeightStrideLayoutTests(unittest.TestCase):
    def test_stride_uses_bcsr_core_size_for_mainline_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pe_dir = root / "pe00"
            pe_dir.mkdir(parents=True, exist_ok=True)
            (pe_dir / "core00.gcssnt.bin").write_bytes(b"a" * 100)
            (pe_dir / "core01.gcssnt.bin").write_bytes(b"b" * 200)

            stride_info = bcsr.resolve_weight_layout_for_mode(
                synapse_weight_mode="gcss_valueonly_dstcore_vlf_premphf",
                gcssnt_dir=str(root),
                bcsr_core_file_size=64,
                num_cores_per_pe=20,
                row_align_bytes=8192,
                base_addr_shift_env_key="MESH_BASE_ADDR_SHIFT",
            )

            self.assertEqual(stride_info["layout_source"], "bcsr")
            self.assertEqual(stride_info["core_file_size"], 64)
            self.assertEqual(stride_info["per_core_weight_stride"], align_up(64, 8192))
            self.assertEqual(stride_info["pe_weight_region_stride"], align_up(64, 8192) * 20)


if __name__ == "__main__":
    unittest.main()
