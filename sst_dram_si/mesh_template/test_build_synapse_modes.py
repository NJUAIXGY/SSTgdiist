import importlib
import re
import sys
import types
import unittest
from pathlib import Path


class _FakeSST(types.SimpleNamespace):
    pass


sys.modules.setdefault("sst", _FakeSST())

build = importlib.import_module("sst_dram_si.mesh_template.build")


class BuildSynapseModeTests(unittest.TestCase):
    def test_ports_per_pe_current_mainline_modes(self):
        self.assertEqual(build.compute_ports_per_pe_for_synapse_mode(20, "bcsr_gas"), 21)
        self.assertEqual(build.compute_ports_per_pe_for_synapse_mode(20, "gcss_valueonly_dstcore_vlf_premphf_plp"), 21)
        self.assertEqual(build.compute_ports_per_pe_for_synapse_mode(20, "gscc_valueonly_dstcore_vlf_premphf_plp"), 21)

    def test_normalize_rejects_removed_legacy_modes(self):
        self.assertEqual(
            build._normalize_synapse_weight_mode("legacy_removed_mode_v1"),
            "bcsr_gas",
        )
        self.assertEqual(
            build._normalize_synapse_weight_mode("legacy_removed_mode_v2"),
            "bcsr_gas",
        )

    def test_extracts_riscv_snn_node_params(self):
        params = build._extract_workload_node_params(
            {
                "workload_impl": "riscv_snn",
                "workload_params": {
                    "firmware_elf": "/tmp/riscv_snn_p0.elf",
                    "backend_name": "runtime_bridge",
                    "hart_isa": "rv64im_zicsr",
                    "local_mem_bytes": 131072,
                    "cmd_queue_entries": 64,
                    "cmp_queue_entries": 32,
                    "rx_debug_queue_entries": 8,
                    "boot_addr": 4096,
                },
            }
        )
        self.assertEqual(params["riscv_snn_firmware_elf"], "/tmp/riscv_snn_p0.elf")
        self.assertEqual(params["riscv_snn_backend_name"], "runtime_bridge")
        self.assertEqual(params["riscv_snn_hart_isa"], "rv64im_zicsr")
        self.assertEqual(params["riscv_snn_local_mem_bytes"], 131072)
        self.assertEqual(params["riscv_snn_cmd_queue_entries"], 64)
        self.assertEqual(params["riscv_snn_cmp_queue_entries"], 32)
        self.assertEqual(params["riscv_snn_rx_debug_queue_entries"], 8)
        self.assertEqual(params["riscv_snn_boot_addr"], 4096)

    def test_apply_workload_params_to_component_params_copies_riscv_snn_surface(self):
        component_params = {"core_id": 0}
        workload_node_params = {
            "riscv_snn_firmware_elf": "/tmp/riscv_snn_p0.elf",
            "riscv_snn_backend_name": "runtime_bridge",
            "riscv_snn_local_mem_bytes": 131072,
        }

        build._apply_workload_params_to_component_params(
            component_params,
            workload_impl="riscv_snn",
            workload_stats_modules="",
            workload_node_params=workload_node_params,
        )

        self.assertEqual(component_params["workload_impl"], "riscv_snn")
        self.assertEqual(component_params["riscv_snn_firmware_elf"], "/tmp/riscv_snn_p0.elf")
        self.assertEqual(component_params["riscv_snn_backend_name"], "runtime_bridge")
        self.assertEqual(component_params["riscv_snn_local_mem_bytes"], 131072)

    def test_build_mesh_contract_applies_workload_surface_to_core_params(self):
        source = Path(build.__file__).read_text(encoding="utf-8")
        self.assertRegex(
            source,
            re.compile(r"_apply_workload_params_to_component_params\(\s*core_params,"),
        )


if __name__ == "__main__":
    unittest.main()
