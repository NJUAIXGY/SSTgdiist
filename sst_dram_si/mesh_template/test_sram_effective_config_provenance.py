import importlib
import sys
import types
import unittest

from sst_dram_si.mesh_template.spec import resolve_spec


class _FakeSST(types.SimpleNamespace):
    pass


sys.modules.setdefault("sst", _FakeSST())

build = importlib.import_module("sst_dram_si.mesh_template.build")


class SramEffectiveConfigProvenanceTests(unittest.TestCase):
    def test_resolve_spec_accepts_top_level_sram_and_maps_state(self):
        defaults_state = {}
        resolved = resolve_spec(
            {
                "schema_version": 3,
                "platform": {"mesh_size": 4},
                "sram": {
                    "model_enable": 1,
                    "weight": {
                        "idx_enable": 1,
                        "l0_enable": 0,
                        "idx_capacity_bytes": 4096,
                        "idx_banks": 8,
                    },
                    "state": {
                        "enable": 1,
                        "capacity_bytes": 8192,
                        "banks": 4,
                    },
                },
            },
            defaults_state=defaults_state,
        )

        state = resolved["state"]
        self.assertEqual(state["SRAM_MODEL_ENABLE"], 1)
        self.assertEqual(state["SRAM_WEIGHT_IDX_ENABLE"], 1)
        self.assertEqual(state["SRAM_WEIGHT_L0_ENABLE"], 0)
        self.assertEqual(state["SRAM_WEIGHT_IDX_CAPACITY_BYTES"], 4096)
        self.assertEqual(state["SRAM_WEIGHT_IDX_BANKS"], 8)
        self.assertEqual(state["SRAM_STATE_ENABLE"], 1)
        self.assertEqual(state["SRAM_STATE_CAPACITY_BYTES"], 8192)
        self.assertEqual(state["SRAM_STATE_BANKS"], 4)

    def test_effective_sram_provenance_prefers_final_pe_core_snapshot(self):
        mesh = {
            "sram": {
                "model_enable": 1,
                "weight": {
                    "idx_enable": 0,
                    "l0_enable": 0,
                    "idx_capacity_bytes": 1024,
                    "l0_capacity_bytes": 2048,
                    "idx_banks": 2,
                    "l0_banks": 2,
                    "ports_per_bank": 1,
                    "bank_interleave_bytes": 4,
                    "t_read_cycles": 1,
                    "t_write_cycles": 1,
                    "sample_log2": 0,
                    "idx_base": 0x100000000,
                    "l0_base": 0x200000000,
                    "l0_slots": 128,
                },
                "state": {
                    "enable": 0,
                    "capacity_bytes": 4096,
                    "banks": 4,
                    "ports_per_bank": 1,
                    "bank_interleave_bytes": 4,
                    "t_read_cycles": 1,
                    "t_write_cycles": 1,
                    "sample_log2": 0,
                    "vmem_base": 0x300000000,
                    "refrac_base": 0x400000000,
                    "last_spike_base": 0x500000000,
                },
                "calib_meta": {"source": "mesh-default"},
            }
        }
        final_pe_core = {
            "weight_sram_model_enable": 1,
            "weight_idx_sram_enable": 1,
            "weight_l0_sram_enable": 1,
            "weight_idx_sram_capacity_bytes": 16384,
            "weight_l0_sram_capacity_bytes": 32768,
            "weight_idx_sram_banks": 16,
            "weight_l0_sram_banks": 8,
            "weight_sram_ports_per_bank": 2,
            "weight_sram_bank_interleave_bytes": 32,
            "weight_sram_t_read_cycles": 3,
            "weight_sram_t_write_cycles": 5,
            "weight_sram_sample_log2": 1,
            "weight_idx_sram_base": 0x111100000,
            "weight_l0_sram_base": 0x222200000,
            "weight_l0_sram_slots": 512,
            "state_sram_enable": 1,
            "state_sram_capacity_bytes": 65536,
            "state_sram_banks": 12,
            "state_sram_ports_per_bank": 2,
            "state_sram_bank_interleave_bytes": 64,
            "state_sram_t_read_cycles": 7,
            "state_sram_t_write_cycles": 9,
            "state_sram_sample_log2": 2,
            "state_sram_vmem_base": 0x333300000,
            "state_sram_refrac_base": 0x444400000,
            "state_sram_last_spike_base": 0x555500000,
        }

        summary = build.make_effective_sram_provenance(mesh=mesh, final_pe_core_params=final_pe_core)

        self.assertEqual(summary["structured"]["weight_idx_enable"], 0)
        self.assertEqual(summary["structured"]["state_enable"], 0)
        self.assertEqual(summary["effective"]["weight_idx_enable"], 1)
        self.assertEqual(summary["effective"]["weight_l0_enable"], 1)
        self.assertEqual(summary["effective"]["state_enable"], 1)
        self.assertEqual(summary["effective"]["weight_idx_capacity_bytes"], 16384)
        self.assertEqual(summary["effective"]["state_banks"], 12)
        self.assertEqual(summary["effective"]["state_last_spike_base"], 0x555500000)
        self.assertEqual(summary["calib_meta"], {"source": "mesh-default"})

    def test_mainline_pulse_cleanup_preserves_osa_metadata_txn_surface(self):
        cleaned = build.apply_mainline_pulse_cleanup(
            {
                "domain_retire_enable": 1,
                "domain_retire_observe_only": 0,
                "domain_retire_mode": "cohort",
                "domain_retire_release_budget": 8,
                "metadata_frontier_observe_enable": 1,
                "metadata_frontier_top_items": 64,
                "metadata_frontier_band_slots": 256,
                "metadata_seed_enable": 1,
                "metadata_seed_top_bases": 128,
                "metadata_seed_window_budget": 16,
                "mfb_preband_seed_enable": 1,
                "mfb_preband_top_bands": 64,
                "mfb_preband_lines_per_band": 8,
                "mfb_preband_band_slots": 128,
                "mfb_preband_window_budget": 4,
                "mfb_gather_preband_enable": 1,
                "mfb_gather_barrier_enable": 1,
                "mfb_gather_top_bands": 64,
                "mfb_gather_lines_per_band": 8,
                "mfb_gather_min_consumers": 4,
                "mfb_gather_window_budget": 6,
                "osa_metadata_txn_enable": 1,
                "osa_metadata_ready_lease_enable": 1,
                "osa_metadata_ready_lease_ttl": 32,
                "osa_metadata_object_mask": "rowidx,rowdescriptor",
            }
        )

        self.assertEqual(cleaned["domain_retire_enable"], 0)
        self.assertEqual(cleaned["domain_retire_observe_only"], 1)
        self.assertEqual(cleaned["domain_retire_mode"], "per_post")
        self.assertEqual(cleaned["domain_retire_release_budget"], 0)
        self.assertEqual(cleaned["metadata_frontier_observe_enable"], 0)
        self.assertEqual(cleaned["metadata_seed_enable"], 0)
        self.assertEqual(cleaned["mfb_preband_seed_enable"], 0)
        self.assertEqual(cleaned["mfb_gather_preband_enable"], 0)
        self.assertEqual(cleaned["osa_metadata_txn_enable"], 1)
        self.assertEqual(cleaned["osa_metadata_ready_lease_enable"], 1)
        self.assertEqual(cleaned["osa_metadata_ready_lease_ttl"], 32)
        self.assertEqual(cleaned["osa_metadata_object_mask"], "rowidx,rowdescriptor")


if __name__ == "__main__":
    unittest.main()
