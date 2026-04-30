#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Spec-first resolver tests for mesh_template.

These tests are intentionally pure-Python (no SST runtime required) so they can
run quickly as a unit-test gate.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
# Allow `from mesh_template ...` imports when running from repo root.
sys.path.insert(0, str(THIS_DIR.parent))


from mesh_template.legacy_defaults import make_default_state

# Feature under development (Spec-first). This import is expected to fail until
# the spec module is implemented.
from mesh_template import spec as mesh_spec  # type: ignore


class MeshSpecResolverTest(unittest.TestCase):
    def test_allows_model_field(self) -> None:
        raw = {"schema_version": 1, "model": "mesh"}
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        self.assertIn("state", resolved)

    def test_plp_requires_gcssplp_dir(self) -> None:
        raw = {"schema_version": 1, "synapse_weight_mode": "gcss_valueonly_dstcore_vlf_premphf_plp"}
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_plp_accepts_gcssplp_dir(self) -> None:
        raw = {
            "schema_version": 1,
            "synapse_weight_mode": "gcss_valueonly_dstcore_vlf_premphf_plp",
            "gcssplp_dir": "weights/gcssplp",
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]
        self.assertEqual(state["SYNAPSE_WEIGHT_MODE"], "gcss_valueonly_dstcore_vlf_premphf_plp")
        self.assertEqual(state["GCSSPLP_DIR"], "weights/gcssplp")


    def test_v3_accepts_unified_workload_type_and_components(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "mesh",
            "platform": {"mesh_size": 4, "stop": {"mode": "step_limited", "max_steps": 2}},
            "workload": {"type": "snn", "stats_modules": "tensor"},
            "components": {"router": {"debug": 1}},
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]
        self.assertEqual(state["SPEC_WORKLOAD_IMPL"], "snn")
        self.assertEqual(state["SPEC_WORKLOAD_STATS_MODULES"], "tensor")
        overrides = list(resolved.get("overrides") or [])
        self.assertGreaterEqual(len(overrides), 1)
        self.assertEqual(overrides[0]["match"], {"role": "router"})
        self.assertEqual(overrides[0]["params"], {"debug": 1})

    def test_v3_mirrors_pe_component_runtime_knobs_into_state(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "mesh",
            "platform": {"stop": {"mode": "step_limited", "max_steps": 1}},
            "components": {
                "pe": {
                    "local_storage_enable": 1,
                    "pe_internal_cpe_enable": 1,
                    "pe_internal_pod_enable": 1,
                    "pe_internal_pod_count": 1,
                    "pe_internal_pod_metadata_enable": 1,
                    "pe_internal_pod_owner_enable": 1,
                    "pe_internal_pod_join_enable": 1,
                    "pe_internal_pod_ready_enable": 1,
                    "pe_internal_pod_owner_entries": 256,
                    "pe_internal_pod_join_entries": 256,
                    "pe_internal_pod_ready_entries": 256,
                }
            },
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]
        overrides = list(resolved.get("overrides") or [])

        self.assertEqual(int(state["LOCAL_STORAGE_ENABLE"]), 1)
        self.assertEqual(int(state["PE_INTERNAL_CPE_ENABLE"]), 1)
        self.assertEqual(int(state["PE_INTERNAL_POD_ENABLE"]), 1)
        self.assertEqual(int(state["PE_INTERNAL_POD_COUNT"]), 1)
        self.assertEqual(int(state["PE_INTERNAL_POD_METADATA_ENABLE"]), 1)
        self.assertEqual(int(state["PE_INTERNAL_POD_OWNER_ENABLE"]), 1)
        self.assertEqual(int(state["PE_INTERNAL_POD_JOIN_ENABLE"]), 1)
        self.assertEqual(int(state["PE_INTERNAL_POD_READY_ENABLE"]), 1)
        self.assertEqual(int(state["PE_INTERNAL_POD_OWNER_ENTRIES"]), 256)
        self.assertEqual(int(state["PE_INTERNAL_POD_JOIN_ENTRIES"]), 256)
        self.assertEqual(int(state["PE_INTERNAL_POD_READY_ENTRIES"]), 256)
        self.assertGreaterEqual(len(overrides), 1)
        self.assertEqual(overrides[0]["match"], {"role": "pe"})
        self.assertEqual(int(overrides[0]["params"]["local_storage_enable"]), 1)

    def test_v3_applies_workload_params_to_state(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "mesh",
            "platform": {"stop": {"mode": "step_limited", "max_steps": 1}},
            "workload": {
                "type": "snn",
                "params": {
                    "tau_mem": 12.5,
                    "t_ref": 3,
                    "init_default_weight": 0.25,
                    "class_freqs": [10, 20, 30, 40],
                    "thresholds": {"input": 0.1, "output": 0.2},
                },
            },
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]
        self.assertAlmostEqual(float(state["CORE_TAU_MEM"]), 12.5, places=6)
        self.assertEqual(int(state["CORE_T_REF"]), 3)
        self.assertAlmostEqual(float(state["CORE_INIT_DEFAULT_WEIGHT"]), 0.25, places=9)
        self.assertEqual(state["SPEC_CLASS_FREQS"], [10, 20, 30, 40])
        self.assertEqual(state["THRESHOLDS"], {"input": 0.1, "output": 0.2})

    def test_v3_applies_riscv_snn_workload_params_to_state(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "mesh",
            "platform": {"stop": {"mode": "step_limited", "max_steps": 1}},
            "workload": {
                "type": "riscv_snn",
                "params": {
                    "firmware_elf": "sst_dram_si/fw/riscv_snn_p0.elf",
                    "backend_name": "runtime_bridge",
                    "hart_isa": "rv64im_zicsr",
                    "local_mem_bytes": 131072,
                    "cmd_queue_entries": 64,
                    "cmp_queue_entries": 64,
                    "rx_debug_queue_entries": 16,
                    "boot_addr": 4096,
                },
            },
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]
        self.assertEqual(state["SPEC_WORKLOAD_IMPL"], "riscv_snn")
        self.assertEqual(state["SPEC_RISCV_SNN_FIRMWARE_ELF"], "sst_dram_si/fw/riscv_snn_p0.elf")
        self.assertEqual(state["SPEC_RISCV_SNN_BACKEND_NAME"], "runtime_bridge")
        self.assertEqual(state["SPEC_RISCV_SNN_HART_ISA"], "rv64im_zicsr")
        self.assertEqual(int(state["SPEC_RISCV_SNN_LOCAL_MEM_BYTES"]), 131072)
        self.assertEqual(int(state["SPEC_RISCV_SNN_CMD_QUEUE_ENTRIES"]), 64)
        self.assertEqual(int(state["SPEC_RISCV_SNN_CMP_QUEUE_ENTRIES"]), 64)
        self.assertEqual(int(state["SPEC_RISCV_SNN_RX_DEBUG_QUEUE_ENTRIES"]), 16)
        self.assertEqual(int(state["SPEC_RISCV_SNN_BOOT_ADDR"]), 4096)

    def test_v3_applies_common_flags_and_layout_fields_to_state(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "mesh",
            "platform": {
                "stop": {"mode": "step_limited", "max_steps": 1},
                "flags": {
                    "disable_network": True,
                    "export_spike_csv": True,
                    "enable_node_summary": True,
                    "enable_test_traffic": True,
                    "record_edge_apply_enable": False,
                    "record_edge_idle_enable": True,
                    "record_edge_scatter_enable": False,
                },
            },
            "pe": {
                "state_layout": {"use_soa": True, "aosoa_block_rows": 32},
                "core": {"memory_warmup_cycles": 123, "loader_barrier_cycles": 7},
            },
            "routing": {"verify_enable": True},
            "workload": {"type": "snn", "spike_source": {"enable": True}},
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]

        self.assertEqual(state["DISABLE_NETWORK"], True)
        self.assertEqual(state["EXPORT_SPIKE_CSV"], True)
        self.assertEqual(state["ENABLE_NODE_SUMMARY"], True)
        self.assertEqual(state["ENABLE_TEST_TRAFFIC"], True)
        self.assertEqual(int(state["RECORD_EDGE_APPLY_ENABLE"]), 0)
        self.assertEqual(int(state["RECORD_EDGE_IDLE_ENABLE"]), 1)
        self.assertEqual(int(state["RECORD_EDGE_SCATTER_ENABLE"]), 0)

        self.assertEqual(int(state["USE_SOA_STATE"]), 1)
        self.assertEqual(int(state["USE_AOSOA_STATE"]), 0)
        self.assertEqual(int(state["AOSOA_BLOCK_ROWS"]), 32)

        self.assertEqual(int(state["CORE_MEMORY_WARMUP_CYCLES"]), 123)
        self.assertEqual(int(state["CORE_LOADER_BARRIER_CYCLES"]), 7)

        self.assertEqual(int(state["VERIFY_ROUTING"]), 1)
        self.assertEqual(state["ENABLE_SPIKE_SOURCE_FLAG"], True)

    def test_v3_applies_top_level_pulse_fields_to_state(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "mesh",
            "platform": {"stop": {"mode": "step_limited", "max_steps": 1}},
            "pulse": {
                "enable": 1,
                "observe_only": 0,
                "ingress_enable": 1,
                "agenda_observe_only": 1,
                "osa_enable": 1,
                "osa_shared_weight_owner_enable": 1,
                "osa_shared_weight_owner_actual_enable": 1,
                "osa_metadata_txn_enable": 1,
                "osa_metadata_ready_lease_enable": 1,
                "osa_metadata_ready_lease_ttl": 64,
                "osa_metadata_object_mask": "rowidx,rowdescriptor",
                "ingress_entries": 32,
                "core_queue_entries": 16,
                "descriptor_packet_min": 4,
                "bypass_high_watermark_pct": 75,
                "bypass_mode": "high_watermark",
            },
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]

        self.assertEqual(int(state["PULSE_ENABLE"]), 1)
        self.assertEqual(int(state["PULSE_OBSERVE_ONLY"]), 0)
        self.assertEqual(int(state["PULSE_INGRESS_ENABLE"]), 1)
        self.assertEqual(int(state["PULSE_AGENDA_OBSERVE_ONLY"]), 1)
        self.assertEqual(int(state["PULSE_OSA_ENABLE"]), 1)
        self.assertEqual(int(state["PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE"]), 1)
        self.assertEqual(int(state["PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE"]), 1)
        self.assertEqual(int(state["PULSE_OSA_METADATA_TXN_ENABLE"]), 1)
        self.assertEqual(int(state["PULSE_OSA_METADATA_READY_LEASE_ENABLE"]), 1)
        self.assertEqual(int(state["PULSE_OSA_METADATA_READY_LEASE_TTL"]), 64)
        self.assertEqual(str(state["PULSE_OSA_METADATA_OBJECT_MASK"]), "rowidx,rowdescriptor")
        self.assertEqual(int(state["PULSE_INGRESS_ENTRIES"]), 32)
        self.assertEqual(int(state["PULSE_CORE_QUEUE_ENTRIES"]), 16)
        self.assertEqual(int(state["PULSE_DESCRIPTOR_PACKET_MIN"]), 4)
        self.assertEqual(int(state["PULSE_BYPASS_HIGH_WATERMARK_PCT"]), 75)
        self.assertEqual(str(state["PULSE_BYPASS_MODE"]), "high_watermark")

    def test_v3_rejects_state_layout_conflict(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "mesh",
            "platform": {"stop": {"mode": "step_limited", "max_steps": 1}},
            "pe": {"state_layout": {"use_soa": True, "use_aosoa": True}},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_applies_core_fields_to_state(self) -> None:
        raw = {
            "schema_version": 1,
            "platform": {
                "mesh_size": 8,
                "node_limit": 16,
                "exec_mode": "gas",
                "stop": {
                    "mode": "step_limited",
                    "max_steps": 4,
                    "simulation_time": "123us",
                },
            },
            "noc": {
                "type": "merlin_mesh",
                "params": {"link_bw": "1GiB/s", "buffer_size": "4KiB", "num_vns": 3},
            },
            "memory": {
                "type": "memHierarchy",
                "backend": {"type": "simple", "access_time": "10ns"},
            },
            "pe": {
                "cores_per_pe": 2,
                "neurons_per_core": 3,
                "l1": {"enable": True, "size": "32KiB", "assoc": 4, "line_bytes": 64},
            },
            "workload": {
                "impl": "snn",
                "stats_modules": "tensor,stream",
            },
            "control": {
                "global_step_sync_enable": False,
                "global_step_ctrl": {"verbose": 7, "require_all_ready": 0, "strict_seq_check": 1},
            },
            "validate": {"profile": "paper"},
            "overrides": [],
        }

        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]

        self.assertEqual(state["MESH_SIZE"], 8)
        self.assertEqual(state["NUM_CORES_PER_PE"], 2)
        self.assertEqual(state["NEURONS_PER_CORE"], 3)

        self.assertEqual(state["NETWORK_BANDWIDTH"], "1GiB/s")
        self.assertEqual(state["BUFFER_SIZE"], "4KiB")
        self.assertEqual(state["SPEC_NETWORK_NUM_VNS"], 3)

        self.assertEqual(state["MEM_BACKEND"], "simple")
        self.assertEqual(state["SIMPLEMEM_ACCESS_TIME"], "10ns")

        self.assertEqual(state["L1_ENABLE"], True)
        self.assertEqual(state["L1_SIZE_STR"], "32KiB")
        self.assertEqual(state["L1_ASSOC"], 4)
        self.assertEqual(state["L1_LINE_BYTES_STR"], "64")
        self.assertEqual(state["SUBCOMP_LINE_BYTES"], 64)

        self.assertEqual(state["GLOBAL_STEP_SYNC_ENABLE"], False)
        self.assertEqual(state["GLOBAL_STEP_CTRL_VERBOSE"], 7)
        self.assertEqual(state["SPEC_GLOBAL_STEP_REQUIRE_ALL_READY"], 0)
        self.assertEqual(state["SPEC_GLOBAL_STEP_STRICT_SEQ_CHECK"], 1)

        self.assertEqual(state["SPEC_EXEC_MODE"], "gas")
        self.assertEqual(state["SPEC_MAX_STEPS"], 4)
        self.assertEqual(state["SIMULATION_TIME"], "123us")

        self.assertEqual(state["SPEC_WORKLOAD_IMPL"], "snn")
        self.assertEqual(state["SPEC_WORKLOAD_STATS_MODULES"], "tensor,stream")

    def test_ramulator2_requires_config_file(self) -> None:
        raw = {
            "schema_version": 1,
            "memory": {"type": "memHierarchy", "backend": {"type": "ramulator2", "config_file": ""}},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_applies_extended_fields_to_state(self) -> None:
        raw = {
            "schema_version": 1,
            "control": {
                "gas_step_seq_gate_enable": True,
                "global_step_ready_delay_cycles": 123,
                "global_step_done": {
                    "policy": "fixed",
                    "drain_min_cycles": 111,
                    "quiescent_min_cycles": 222,
                    "fixed_cycles": 999,
                },
            },
            "gas": {
                "merge_policy": "row",
                "gap_k_bytes": 128,
                "lmax_bytes": 4096,
                "max_inflight": 777,
                "row_window_bytes": 65536,
                "row_window_timeout_ns": 9999,
                "window_cycles": {"gather": 10, "apply": 20, "scatter": 30},
                "gather_quiesce_cycles": 44,
                "gather_min_cycles": 5,
                "dense_strict_cacheline": False,
                "force_defer": True,
            },
            "step": {
                "random_activation_enable": 0,
                "activation_period_cycles": 7,
                "activation_fraction": 0.123,
                "activation_fanout": 42,
                "activation_seed": 1234,
                "activation_event_weight": 0.5,
                "activation_trigger_core": 2,
                "activation_use_bcsr_routes": False,
                "activation_template": "/tmp/core{core:02d}.bcsr.bin",
                "reset_mem_each_step": 1,
                "seed_only_mode": 1,
                "bcsr": {
                    "weight_epsilon": 0.01,
                    "rowptr_offset": 1,
                    "colidx_offset": 2,
                    "blockdata_offset": 3,
                    "blockids_offset": 4,
                    "br": 8,
                    "bc": 16,
                    "idx_bytes": 2,
                    "val_bytes": 4,
                },
            },
            "routing": {"mode": "weight_driven", "epsilon": 0.9, "topk_per_pe": 5, "topk": 10},
            "loader": {
                "verbose": 2,
                "chunk_bytes": 256,
                "timed_seed_enable": True,
                "timed_seed_allow_cache": True,
                "verify_readback": True,
                "verify_bytes": 32,
                "verify_mode": "dense_rowcol_v1",
                "verify_samples": 9,
                "verify_seed": 7,
                "verify_colidx_start": 555,
                "diag_timed_read": True,
                "diag_timed_read_colidx_start": 666,
                "write_pattern_mode": "dense_rowcol_v1",
                "write_pattern_row_scale": 2048,
            },
            "debug": {
                "sentinel_enable": True,
                "progress_log_interval_ns": 1000,
                "progress_log_node": 3,
                "window_read_debug": True,
                "window_read_debug_all_cores": True,
                "debug_target_pe": 1,
                "debug_target_core": 2,
                "node_verbose": 9,
                "core_verbose": 8,
                "diag_fire_log": True,
                "bcsr_merge_read_verify_enable": True,
                "bcsr_merge_read_verify_sample_bytes": 12,
                "bcsr_merge_read_verify_max_resps": 13,
                "bcsr_merge_read_verify_target_pe": 14,
                "bcsr_merge_read_verify_target_core": 15,
            },
            "overrides": [],
        }

        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]

        self.assertEqual(state["SPEC_GAS_STEP_SEQ_GATE_ENABLE"], True)
        self.assertEqual(state["SPEC_GLOBAL_STEP_READY_DELAY_CYCLES"], 123)
        self.assertEqual(state["SPEC_GLOBAL_STEP_DONE_POLICY"], "fixed")
        self.assertEqual(state["SPEC_GLOBAL_STEP_DRAIN_MIN_CYCLES"], 111)
        self.assertEqual(state["SPEC_GLOBAL_STEP_QUIESCENT_MIN_CYCLES"], 222)
        self.assertEqual(state["SPEC_GLOBAL_STEP_FIXED_CYCLES"], 999)

        self.assertEqual(state["_GAS_MERGE_POLICY"], "row")
        self.assertEqual(state["_GAS_GAP_K_BYTES"], 128)
        self.assertEqual(state["_GAS_LMAX_BYTES"], 4096)
        self.assertEqual(state["_GAS_MAX_INFLIGHT"], 777)
        self.assertEqual(state["_GAS_ROW_WINDOW_BYTES"], 65536)
        self.assertEqual(state["_GAS_ROW_WINDOW_TIMEOUT_NS"], 9999)
        self.assertEqual(state["_GAS_WINDOW_CYCLES"]["gather"], 10)
        self.assertEqual(state["_GAS_WINDOW_CYCLES"]["apply"], 20)
        self.assertEqual(state["_GAS_WINDOW_CYCLES"]["scatter"], 30)
        self.assertEqual(state["SPEC_GAS_GATHER_QUIESCE_CYCLES"], 44)
        self.assertEqual(state["SPEC_GAS_GATHER_MIN_CYCLES"], 5)
        self.assertEqual(state["SPEC_GAS_DENSE_STRICT_CACHELINE"], False)
        self.assertEqual(state["SPEC_GAS_FORCE_DEFER"], True)

        self.assertEqual(state["STEP_RANDOM_ACT_ENABLE"], 0)
        self.assertEqual(state["STEP_ACTIVATION_PERIOD_CYCLES"], 7)
        self.assertAlmostEqual(float(state["STEP_ACTIVATION_FRACTION"]), 0.123, places=6)
        self.assertEqual(state["STEP_ACTIVATION_FANOUT"], 42)
        self.assertEqual(state["STEP_ACTIVATION_SEED"], 1234)
        self.assertAlmostEqual(float(state["STEP_ACTIVATION_EVENT_WEIGHT"]), 0.5, places=6)
        self.assertEqual(state["STEP_ACTIVATION_TRIGGER_CORE"], 2)
        self.assertEqual(state["STEP_ACTIVATION_USE_BCSR_ROUTES"], False)
        self.assertEqual(state["STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE"], "/tmp/core{core:02d}.bcsr.bin")
        self.assertEqual(state["STEP_RESET_MEM_EACH_STEP"], 1)
        self.assertEqual(state["STEP_SEED_ONLY_MODE"], 1)
        self.assertAlmostEqual(float(state["STEP_ACTIVATION_BCSR_WEIGHT_EPS"]), 0.01, places=6)
        self.assertEqual(state["STEP_ACTIVATION_BCSR_ROWPTR_OFFSET"], 1)
        self.assertEqual(state["STEP_ACTIVATION_BCSR_COLIDX_OFFSET"], 2)
        self.assertEqual(state["STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET"], 3)
        self.assertEqual(state["STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET"], 4)

    def test_v2_components_are_lower_priority_than_overrides(self) -> None:
        raw = {
            "schema_version": 2,
            "components": {
                "router": {"debug": 1},
                "pe": {"verbose": 3},
            },
            "overrides": [
                {"match": {"role": "router"}, "params": {"debug": 2}},
            ],
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        rules = list(resolved.get("overrides") or [])

        # components -> generated overrides, then user overrides
        self.assertGreaterEqual(len(rules), 3)
        self.assertEqual(rules[0]["match"], {"role": "pe"})
        self.assertEqual(rules[0]["params"], {"verbose": 3})
        self.assertEqual(rules[1]["match"], {"role": "router"})
        self.assertEqual(rules[1]["params"], {"debug": 1})
        self.assertEqual(rules[2]["match"], {"role": "router"})
        self.assertEqual(rules[2]["params"], {"debug": 2})

    def test_v3_rejects_pe_scoped_params_under_pe_core_role(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "mesh",
            "platform": {"stop": {"mode": "step_limited", "max_steps": 1}},
            "components": {
                "pe.core": {
                    "local_storage_enable": 1,
                    "pe_internal_pod_enable": 1,
                }
            },
        }
        defaults = make_default_state()
        with self.assertRaisesRegex(ValueError, "PE-scoped params"):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_rejects_unknown_top_level_fields_by_default(self) -> None:
        raw = {
            "schema_version": 1,
            "unknown_key": 123,
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_allows_unknown_fields_when_requested(self) -> None:
        raw = {
            "schema_version": 1,
            "unknown_key": 123,
            "validate": {"allow_unknown_fields": True},
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        self.assertIn("state", resolved)

    def test_rejects_partial_step_bcsr_offsets(self) -> None:
        raw = {
            "schema_version": 1,
            "step": {"bcsr": {"rowptr_offset": 1}},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_rejects_invalid_global_step_done_policy(self) -> None:
        raw = {
            "schema_version": 1,
            "control": {"global_step_done": {"policy": "???bad???"}},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_rejects_invalid_platform_exec_mode(self) -> None:
        raw = {
            "schema_version": 1,
            "platform": {"exec_mode": "???bad???"},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_rejects_step_limited_without_positive_max_steps(self) -> None:
        raw = {
            "schema_version": 1,
            "platform": {"stop": {"mode": "step_limited", "max_steps": 0}},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_rejects_invalid_gas_merge_policy(self) -> None:
        raw = {
            "schema_version": 1,
            "gas": {"merge_policy": "???bad???"},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_rejects_invalid_routing_mode(self) -> None:
        raw = {
            "schema_version": 1,
            "routing": {"mode": "round_robin"},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_rejects_invalid_loader_verify_mode(self) -> None:
        raw = {
            "schema_version": 1,
            "loader": {"verify_mode": "raw_bcsr_v1"},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_rejects_invalid_noc_type(self) -> None:
        raw = {
            "schema_version": 1,
            "noc": {"type": "bad_noc"},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_rejects_invalid_memory_type(self) -> None:
        raw = {
            "schema_version": 1,
            "memory": {"type": "bad_memory"},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)

    def test_normalizes_noc_and_memory_types(self) -> None:
        raw = {
            "schema_version": 1,
            "noc": {"type": "torus", "params": {"nic_buffer_size": "16KiB", "router_buffer_size": "4KiB"}},
            "memory": {"type": "shared"},
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]
        self.assertEqual(state["SPEC_NOC_TYPE"], "merlin_torus")
        self.assertEqual(state["BUFFER_SIZE"], "16KiB")
        self.assertEqual(state["ROUTER_BUFFER_SIZE"], "4KiB")
        self.assertEqual(state["SPEC_MEMORY_SYSTEM"], "memhierarchy_shared")

    def test_applies_env_migrated_fields_to_state(self) -> None:
        raw = {
            "schema_version": 1,
            "pe": {
                "minimal_core_params": True,
                "readonly_freeze": {"enable": True, "v_thresh": 123.0, "tau_mem": 0.01},
                "core": {
                    "apply_dense_acc_enable": False,
                    "acc_shadow_verify_enable": True,
                },
            },
            "routing": {"mapping_mode": "pre"},
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]
        self.assertEqual(state["SPEC_MINIMAL_CORE_PARAMS"], True)
        self.assertEqual(state["SPEC_READONLY_FREEZE_ENABLE"], True)
        self.assertAlmostEqual(float(state["SPEC_READONLY_V_THRESH"]), 123.0, places=6)
        self.assertAlmostEqual(float(state["SPEC_READONLY_TAU_MEM"]), 0.01, places=9)
        self.assertEqual(state["SPEC_MAPPING_MODE"], "pre")
        self.assertEqual(state["SPEC_APPLY_DENSE_ACC_ENABLE"], False)
        self.assertEqual(state["SPEC_ACC_SHADOW_VERIFY_ENABLE"], True)

    def test_applies_thermal_fields_to_state(self) -> None:
        raw = {
            "schema_version": 1,
            "thermal": {
                "enable": True,
                "backend": "3d-ice",
                "window_ns": 2500,
                "window_trace_enable": True,
                "window_trace_max_rows": 64,
                "include_memctrl": True,
                "out_dir": "thermal_spec",
                "hotspot_bin": "/tmp/hotspot",
                "generate_floorplan": False,
                "tile_width_um": 2000,
                "tile_height_um": 1500,
                "tile_gap_um": 75,
                "comp_frac": 0.5,
                "sram_frac": 0.3,
                "noc_frac": 0.2,
            },
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]
        self.assertEqual(int(state["THERMAL_ENABLE"]), 1)
        self.assertEqual(state["THERMAL_BACKEND"], "3dice")
        self.assertEqual(int(state["THERMAL_WINDOW_NS"]), 2500)
        self.assertEqual(int(state["THERMAL_WINDOW_TRACE_ENABLE"]), 1)
        self.assertEqual(int(state["THERMAL_WINDOW_TRACE_MAX_ROWS"]), 64)
        self.assertEqual(int(state["THERMAL_INCLUDE_MEMCTRL"]), 1)
        self.assertEqual(state["THERMAL_OUT_DIR"], "thermal_spec")
        self.assertEqual(state["THERMAL_HOTSPOT_BIN"], "/tmp/hotspot")
        self.assertEqual(int(state["THERMAL_GENERATE_FLOORPLAN"]), 0)
        self.assertEqual(int(state["THERMAL_TILE_WIDTH_UM"]), 2000)
        self.assertEqual(int(state["THERMAL_TILE_HEIGHT_UM"]), 1500)
        self.assertEqual(int(state["THERMAL_TILE_GAP_UM"]), 75)
        self.assertAlmostEqual(float(state["THERMAL_COMP_FRAC"]), 0.5, places=9)
        self.assertAlmostEqual(float(state["THERMAL_SRAM_FRAC"]), 0.3, places=9)
        self.assertAlmostEqual(float(state["THERMAL_NOC_FRAC"]), 0.2, places=9)

    def test_applies_thermal_3d_grid_fields_to_state(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "mesh",
            "thermal": {
                "enable": True,
                "backend": "hotspot",
                "model_type": "grid",
                "grid_rows": 64,
                "grid_cols": 48,
                "grid_map_mode": "center",
                "detailed_3d": True,
                "layers": [
                    {
                        "name": "compute_top",
                        "kind": "mesh_active",
                        "z_um": 0,
                        "thickness_um": 150,
                        "power_source": {
                            "type": "stats_prefix",
                            "component_prefixes": ["multicore_pe_"],
                            "statistic_prefixes": ["sim_cycles_total", "compute_active_cycles_total"],
                        },
                    },
                    {
                        "name": "tim_mid",
                        "kind": "tim",
                        "z_um": 150,
                        "thickness_um": 20,
                        "power_source": {"type": "none"},
                    },
                    {
                        "name": "compute_bottom",
                        "kind": "mesh_active",
                        "z_um": 170,
                        "thickness_um": 150,
                        "power_scale": 0.5,
                        "power_source": {
                            "type": "csv",
                            "csv_path": "tools/specs/thermal_csv_profiles/mesh_hotspot_csv_layer_profile_v1.csv",
                        },
                    },
                ],
            },
        }
        defaults = make_default_state()
        resolved = mesh_spec.resolve_spec(raw, defaults_state=defaults)
        state = resolved["state"]
        self.assertEqual(state["THERMAL_MODEL_TYPE"], "grid")
        self.assertEqual(int(state["THERMAL_GRID_ROWS"]), 64)
        self.assertEqual(int(state["THERMAL_GRID_COLS"]), 48)
        self.assertEqual(state["THERMAL_GRID_MAP_MODE"], "center")
        self.assertEqual(int(state["THERMAL_DETAILED_3D"]), 1)
        layers = list(state.get("THERMAL_LAYERS") or [])
        self.assertEqual(len(layers), 3)
        self.assertEqual(layers[0]["name"], "compute_top")
        self.assertEqual(layers[0]["kind"], "mesh_active")
        self.assertEqual(layers[0]["power_source"]["type"], "stats_prefix")
        self.assertEqual(layers[0]["power_source"]["component_prefixes"], ["multicore_pe_"])
        self.assertEqual(
            layers[0]["power_source"]["statistic_prefixes"],
            ["sim_cycles_total", "compute_active_cycles_total"],
        )
        self.assertEqual(int(layers[1]["z_um"]), 150)
        self.assertEqual(layers[1]["power_source"]["type"], "none")
        self.assertAlmostEqual(float(layers[2]["power_scale"]), 0.5, places=9)
        self.assertEqual(layers[2]["power_source"]["type"], "csv")
        self.assertEqual(
            layers[2]["power_source"]["csv_path"],
            "tools/specs/thermal_csv_profiles/mesh_hotspot_csv_layer_profile_v1.csv",
        )

    def test_rejects_invalid_thermal_backend(self) -> None:
        raw = {
            "schema_version": 1,
            "thermal": {"backend": "bad_backend"},
        }
        defaults = make_default_state()
        with self.assertRaises(ValueError):
            mesh_spec.resolve_spec(raw, defaults_state=defaults)


if __name__ == "__main__":
    unittest.main()
