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
        self.assertAlmostEqual(float(state["STEP_ACTIVATION_BCSR_WEIGHT_EPS"]), 0.01, places=6)
        self.assertEqual(state["STEP_ACTIVATION_BCSR_ROWPTR_OFFSET"], 1)
        self.assertEqual(state["STEP_ACTIVATION_BCSR_COLIDX_OFFSET"], 2)
        self.assertEqual(state["STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET"], 3)
        self.assertEqual(state["STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET"], 4)
        self.assertEqual(state["STEP_ACTIVATION_BCSR_BR"], 8)

        self.assertEqual(state["ROUTING_MODE"], "weight_driven")
        self.assertAlmostEqual(float(state["ROUT_EPS"]), 0.9, places=6)
        self.assertEqual(state["ROUT_TOPK_PER_PE"], 5)
        self.assertEqual(state["ROUT_TOPK"], 10)

        self.assertEqual(state["LOADER_VERBOSE"], 2)
        self.assertEqual(state["LOADER_CHUNK_BYTES"], 256)
        self.assertEqual(state["LOADER_TIMED_SEED_ENABLE"], 1)
        self.assertEqual(state["LOADER_TIMED_SEED_ALLOW_CACHE"], 1)
        self.assertEqual(state["LOADER_VERIFY_READBACK"], 1)
        self.assertEqual(state["LOADER_VERIFY_BYTES"], 32)
        self.assertEqual(state["LOADER_VERIFY_MODE"], "dense_rowcol_v1")
        self.assertEqual(state["LOADER_VERIFY_SAMPLES"], 9)
        self.assertEqual(state["LOADER_VERIFY_SEED"], 7)
        self.assertEqual(state["LOADER_VERIFY_COLIDX_START"], 555)
        self.assertEqual(state["LOADER_DIAG_TIMED_READ"], 1)
        self.assertEqual(state["LOADER_DIAG_TIMED_READ_COLIDX_START"], 666)
        self.assertEqual(state["LOADER_WRITE_PATTERN_MODE"], "dense_rowcol_v1")
        self.assertEqual(state["LOADER_WRITE_PATTERN_ROW_SCALE"], 2048)

        self.assertEqual(state["SENTINEL_ENABLE"], True)
        self.assertEqual(state["PROGRESS_LOG_INTERVAL_NS"], 1000)
        self.assertEqual(state["PROGRESS_LOG_NODE"], 3)
        self.assertEqual(state["WINDOW_READ_DEBUG"], True)
        self.assertEqual(state["WINDOW_READ_DEBUG_ALL"], True)
        self.assertEqual(state["DEBUG_TARGET_PE"], 1)
        self.assertEqual(state["DEBUG_TARGET_CORE"], 2)
        self.assertEqual(state["NODE_VERBOSE"], 9)
        self.assertEqual(state["CORE_VERBOSE"], 8)
        self.assertEqual(state["DIAG_FIRE_LOG"], True)
        self.assertEqual(state["BCSR_MERGE_READ_VERIFY_ENABLE"], True)
        self.assertEqual(state["BCSR_MERGE_READ_VERIFY_SAMPLE_BYTES"], 12)
        self.assertEqual(state["BCSR_MERGE_READ_VERIFY_MAX_RESPS"], 13)
        self.assertEqual(state["BCSR_MERGE_READ_VERIFY_TARGET_PE"], 14)
        self.assertEqual(state["BCSR_MERGE_READ_VERIFY_TARGET_CORE"], 15)

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


if __name__ == "__main__":
    unittest.main()
