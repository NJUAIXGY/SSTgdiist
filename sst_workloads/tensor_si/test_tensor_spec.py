#!/usr/bin/env python3

import sys
from pathlib import Path
import unittest

# Ensure `tensor_template/*` can be imported when running from repo root.
THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from tensor_template.spec import SpecError
from tensor_template.spec import resolve_spec


class TensorSpecResolveTests(unittest.TestCase):
    def test_resolve_spec_overrides(self) -> None:
        raw = {
            "schema_version": 1,
            "platform": {"mesh_size": 2, "node_limit": 3, "stop": {"simulation_time": "5us"}},
            "noc": {"params": {"link_bw": "80GiB/s", "buffer_size": "16KiB", "num_vns": 4}},
            "memory": {"params": {"core_mem_region_bytes": 2048, "mem_access_time": "50ns"}},
            "pe": {"num_cores_per_pe": 2, "neurons_per_core": 8},
            "workload": {"tensor": {"params": {"tensor_m": 128, "tensor_dataflow": "ws"}}},
        }

        resolved = resolve_spec(raw)

        self.assertEqual(resolved["runtime"]["mesh_size"], 2)
        self.assertEqual(resolved["runtime"]["node_limit"], 3)
        self.assertEqual(resolved["runtime"]["simulation_time"], "5us")
        self.assertEqual(resolved["mesh_cfg"]["total_nodes"], 4)
        self.assertEqual(resolved["mesh_cfg"]["num_cores_per_pe"], 2)
        self.assertEqual(resolved["mesh_cfg"]["neurons_per_core"], 8)
        self.assertEqual(resolved["mesh_cfg"]["neurons_per_pe"], 16)
        self.assertEqual(resolved["mesh_cfg"]["network_bandwidth"], "80GiB/s")
        self.assertEqual(resolved["mesh_cfg"]["buffer_size"], "16KiB")
        self.assertEqual(resolved["mesh_cfg"]["network_num_vns"], 4)
        self.assertEqual(resolved["mesh_cfg"]["core_mem_region_bytes"], 2048)
        self.assertEqual(resolved["mesh_cfg"]["pe_mem_region_bytes"], 4096)
        self.assertEqual(resolved["mesh_cfg"]["mem_access_time"], "50ns")
        self.assertEqual(resolved["tensor_cfg"]["tensor_m"], 128)
        self.assertEqual(resolved["tensor_cfg"]["tensor_dataflow"], "ws")
        self.assertEqual(resolved["tensor_cfg"]["tensor_n"], 256)
        self.assertEqual(resolved["tensor_cfg"]["tensor_mem_region_bytes"], 2048)

    def test_resolve_spec_v3_unified_workload_params(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "platform": {"mesh_size": 2, "node_limit": 3, "stop": {"mode": "time", "simulation_time": "5us"}},
            "noc": {"type": "merlin_mesh", "params": {"link_bw": "80GiB/s", "buffer_size": "16KiB", "num_vns": 4}},
            "memory": {
                "type": "memHierarchy",
                "backend": {"type": "simple"},
                "params": {"core_mem_region_bytes": 2048, "mem_access_time": "50ns"},
            },
            "pe": {"cores_per_pe": 2, "neurons_per_core": 8},
            "workload": {"type": "tensor", "params": {"tensor_m": 128, "tensor_dataflow": "ws"}},
            "components": {"router": {"debug": 1}},
            "overrides": [{"match": {"role": "router"}, "params": {"debug": 2}}],
        }
        resolved = resolve_spec(raw)
        self.assertEqual(resolved["runtime"]["mesh_size"], 2)
        self.assertEqual(resolved["runtime"]["node_limit"], 3)
        self.assertEqual(resolved["runtime"]["simulation_time"], "5us")
        self.assertEqual(resolved["mesh_cfg"]["num_cores_per_pe"], 2)
        self.assertEqual(resolved["tensor_cfg"]["tensor_m"], 128)
        # overrides: components should be lower priority than explicit overrides
        overrides = list(resolved.get("overrides") or [])
        self.assertGreaterEqual(len(overrides), 2)
        self.assertEqual(overrides[0]["match"], {"role": "router"})
        self.assertEqual(overrides[0]["params"], {"debug": 1})
        self.assertEqual(overrides[1]["match"], {"role": "router"})
        self.assertEqual(overrides[1]["params"], {"debug": 2})

    def test_ramulator2_cfg_infers_hbm_channels_and_interleave_when_missing(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "platform": {"mesh_size": 1, "stop": {"mode": "time", "simulation_time": "5us"}},
            "noc": {"type": "merlin_mesh", "params": {"link_bw": "40GiB/s", "buffer_size": "8KiB", "num_vns": 2}},
            "memory": {
                "type": "shared",
                "backend": {"type": "ramulator2", "params": {"configFile": "sst_dram_si/configs/ramulator2_hbm2.cfg"}},
                "params": {"core_mem_region_bytes": 1048576, "mem_access_time": "10ns"},
            },
            "pe": {"cores_per_pe": 1, "neurons_per_core": 1},
            "workload": {
                "type": "tensor",
                "stats_modules": "tensor",
                "params": {
                    "tensor_exec_mode": "program",
                    "tensor_iterations": 1,
                    "tensor_mem_enable": 1,
                    "tensor_mem_req_bytes": 256,
                    "tensor_mem_max_outstanding": 256,
                    # Intentionally omit:
                    # - tensor_dma_hbm_channels
                    # - tensor_dma_hbm_channel_interleave_bytes
                    "tensor_program_issue_width": 4,
                },
                "program": {
                    "loop": False,
                    "ops": [
                        {"op_type": "dma_read", "bytes": 8192, "reset": True},
                        {"op_type": "fence"},
                        {"op_type": "gemm_ub", "cycles": 1, "ub_read_bytes": 0, "ub_write_bytes": 0},
                        {"op_type": "fence"},
                    ],
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(int(cfg.get("tensor_dma_hbm_channels", 0)), 4)
        self.assertEqual(int(cfg.get("tensor_dma_hbm_channel_interleave_bytes", 0)), 256)

    def test_noc_shape_parsing_and_validation(self) -> None:
        raw_ok = {
            "schema_version": 3,
            "model": "tensor",
            "platform": {"mesh_size": 4, "stop": {"mode": "time", "simulation_time": "5us"}},
            "noc": {"type": "merlin_torus", "params": {"shape": "2x8"}},
            "workload": {"type": "tensor"},
        }
        resolved = resolve_spec(raw_ok)
        self.assertEqual(resolved["mesh_cfg"]["noc_shape"], "2x8")
        self.assertEqual(resolved["mesh_cfg"]["noc_width"], "1x1")
        self.assertEqual(int(resolved["mesh_cfg"]["noc_local_ports"]), 1)

        raw_bad = {
            "schema_version": 3,
            "model": "tensor",
            "platform": {"mesh_size": 4, "stop": {"mode": "time", "simulation_time": "5us"}},
            "noc": {"type": "merlin_torus", "params": {"shape": "3x3"}},
            "workload": {"type": "tensor"},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw_bad)

        raw_bad_width = {
            "schema_version": 3,
            "model": "tensor",
            "platform": {"mesh_size": 2, "stop": {"mode": "time", "simulation_time": "5us"}},
            "noc": {"type": "merlin_mesh", "params": {"width": "2x1"}},
            "workload": {"type": "tensor"},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw_bad_width)

        raw_bad_ports = {
            "schema_version": 3,
            "model": "tensor",
            "platform": {"mesh_size": 2, "stop": {"mode": "time", "simulation_time": "5us"}},
            "noc": {"type": "merlin_mesh", "params": {"local_ports": 2}},
            "workload": {"type": "tensor"},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw_bad_ports)

    def test_collective_algo_torus_2d_requires_torus_and_sets_dims(self) -> None:
        raw_bad = {
            "schema_version": 3,
            "model": "tensor",
            "platform": {"mesh_size": 2, "stop": {"mode": "time", "simulation_time": "5us"}},
            "noc": {"type": "merlin_mesh"},
            "workload": {"type": "tensor", "params": {"tensor_collective_algo": "torus_2d_rs_ag"}},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw_bad)

        raw_ok = {
            "schema_version": 3,
            "model": "tensor",
            "platform": {"mesh_size": 4, "stop": {"mode": "time", "simulation_time": "5us"}},
            "noc": {"type": "merlin_torus", "params": {"shape": "2x8"}},
            "workload": {"type": "tensor", "params": {"tensor_collective_algo": "torus_2d_rs_ag"}},
        }
        resolved = resolve_spec(raw_ok)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(cfg["tensor_collective_algo"], "torus_2d_rs_ag")
        self.assertEqual(int(cfg["tensor_collective_2d_dim_x"]), 2)
        self.assertEqual(int(cfg["tensor_collective_2d_dim_y"]), 8)
        self.assertEqual(int(cfg["tensor_collective_2d_row_major"]), 1)

    def test_unknown_top_level_fields_rejected(self) -> None:
        with self.assertRaises(SpecError):
            resolve_spec({"schema_version": 3, "model": "tensor", "bad": 1})

    def test_unknown_tensor_params_rejected(self) -> None:
        raw = {"workload": {"tensor": {"params": {"unknown_key": 1}}}}
        with self.assertRaises(SpecError):
            resolve_spec(raw)

    def test_allow_unknown_fields(self) -> None:
        raw = {
            "validate": {"allow_unknown_fields": True},
            "workload": {"tensor": {"params": {"unknown_key": 1}}},
        }
        resolved = resolve_spec(raw)
        self.assertEqual(resolved["tensor_cfg"]["unknown_key"], 1)

    def test_compute_precision_profile_params(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {
                    "tensor_compute_precision": "fp32",
                    "tensor_compute_profile_override_enable": 1,
                    "tensor_compute_throughput_scale": 0.6,
                    "tensor_compute_pipeline_latency_cycles": 3,
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(cfg["tensor_compute_precision"], "fp32")
        self.assertEqual(cfg["tensor_compute_profile_override_enable"], 1)
        self.assertAlmostEqual(float(cfg["tensor_compute_throughput_scale"]), 0.6, places=6)
        self.assertEqual(int(cfg["tensor_compute_pipeline_latency_cycles"]), 3)

    def test_capability_and_scheduler_profile_params(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {
                    "tensor_capability_profile": "baseline_npu_like_v1",
                    "tensor_scheduler_model": "greedy_dual_issue",
                    "tensor_memory_hierarchy_profile": "server",
                    "tensor_calibration_tag": "m41_calib_v1",
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(cfg["tensor_capability_profile"], "baseline_npu_like_v1")
        self.assertEqual(cfg["tensor_scheduler_model"], "greedy_dual_issue")
        self.assertEqual(cfg["tensor_memory_hierarchy_profile"], "server")
        self.assertEqual(cfg["tensor_calibration_tag"], "m41_calib_v1")

    def test_invalid_compute_precision_rejected(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {"type": "tensor", "params": {"tensor_compute_precision": "bad_precision"}},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw)

    def test_noc_budget_and_collective_overlap_params(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {
                    "tensor_noc_bandwidth_bytes_per_cycle": 128,
                    "tensor_collective_overlap_with_compute": 0,
                    "tensor_collective_issue_priority": "control_first",
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(int(cfg["tensor_noc_bandwidth_bytes_per_cycle"]), 128)
        self.assertEqual(int(cfg["tensor_collective_overlap_with_compute"]), 0)
        self.assertEqual(str(cfg["tensor_collective_issue_priority"]), "control_first")

    def test_invalid_collective_issue_priority_rejected(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {"type": "tensor", "params": {"tensor_collective_issue_priority": "invalid_priority"}},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw)

    def test_m3_onchip_and_collective_params(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {
                    "tensor_onchip_model_enable": 1,
                    "tensor_ub_bank_bytes": 32768,
                    "tensor_ub_read_ports": 2,
                    "tensor_ub_write_ports": 1,
                    "tensor_acc_bank_bytes": 32768,
                    "tensor_acc_read_ports": 1,
                    "tensor_acc_write_ports": 1,
                    "tensor_spill_enable": 1,
                    "tensor_spill_packet_bytes": 128,
                    "tensor_spill_share_noc_budget": 0,
                    "tensor_collective_algo": "ring_chunked",
                    "tensor_collective_chunk_bytes": 2048,
                    "tensor_collective_reduce_overhead_cycles": 3,
                    "tensor_collective_max_inflight_chunks": 2,
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(int(cfg["tensor_onchip_model_enable"]), 1)
        self.assertEqual(int(cfg["tensor_ub_bank_bytes"]), 32768)
        self.assertEqual(int(cfg["tensor_acc_bank_bytes"]), 32768)
        self.assertEqual(int(cfg["tensor_spill_enable"]), 1)
        self.assertEqual(int(cfg["tensor_spill_packet_bytes"]), 128)
        self.assertEqual(int(cfg["tensor_spill_share_noc_budget"]), 0)
        self.assertEqual(str(cfg["tensor_collective_algo"]), "ring_chunked")
        self.assertEqual(int(cfg["tensor_collective_chunk_bytes"]), 2048)
        self.assertEqual(int(cfg["tensor_collective_reduce_overhead_cycles"]), 3)
        self.assertEqual(int(cfg["tensor_collective_max_inflight_chunks"]), 2)

    def test_invalid_collective_algo_rejected(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {"type": "tensor", "params": {"tensor_collective_algo": "bad_algo"}},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw)

    def test_m4_bank_and_collective_credit_params(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {
                    "tensor_onchip_bank_model_enable": 1,
                    "tensor_ub_bank_count": 4,
                    "tensor_ub_bank_select_policy": "rr",
                    "tensor_ub_bank_conflict_mode": "queue",
                    "tensor_acc_bank_count": 4,
                    "tensor_acc_bank_select_policy": "hash",
                    "tensor_acc_bank_conflict_mode": "block",
                    "tensor_bank_queue_depth": 32,
                    "tensor_collective_credit_enable": 1,
                    "tensor_collective_credit_window_chunks": 2,
                    "tensor_collective_credit_return_mode": "event_on_recv",
                    "tensor_collective_backpressure_mode": "soft",
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(int(cfg["tensor_onchip_bank_model_enable"]), 1)
        self.assertEqual(int(cfg["tensor_ub_bank_count"]), 4)
        self.assertEqual(str(cfg["tensor_ub_bank_select_policy"]), "rr")
        self.assertEqual(str(cfg["tensor_ub_bank_conflict_mode"]), "queue")
        self.assertEqual(int(cfg["tensor_acc_bank_count"]), 4)
        self.assertEqual(str(cfg["tensor_acc_bank_select_policy"]), "hash")
        self.assertEqual(str(cfg["tensor_acc_bank_conflict_mode"]), "block")
        self.assertEqual(int(cfg["tensor_bank_queue_depth"]), 32)
        self.assertEqual(int(cfg["tensor_collective_credit_enable"]), 1)
        self.assertEqual(int(cfg["tensor_collective_credit_window_chunks"]), 2)
        self.assertEqual(str(cfg["tensor_collective_credit_return_mode"]), "event_on_recv")
        self.assertEqual(str(cfg["tensor_collective_backpressure_mode"]), "soft")

    def test_m10_collective_credit_alias_pkts(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {
                    # canonical keys (should be overridden by *_pkts aliases below)
                    "tensor_collective_max_inflight_chunks": 1,
                    "tensor_collective_credit_window_chunks": 2,
                    # aliases
                    "tensor_collective_max_inflight_pkts": 3,
                    "tensor_collective_credit_window_pkts": 5,
                    "tensor_collective_credit_enable": 1,
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(int(cfg["tensor_collective_max_inflight_chunks"]), 3)
        self.assertEqual(int(cfg["tensor_collective_credit_window_chunks"]), 5)
        self.assertNotIn("tensor_collective_max_inflight_pkts", cfg)
        self.assertNotIn("tensor_collective_credit_window_pkts", cfg)

    def test_invalid_m4_bank_policy_rejected(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {"type": "tensor", "params": {"tensor_ub_bank_select_policy": "bad_policy"}},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw)

    def test_invalid_m4_collective_backpressure_mode_rejected(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {"type": "tensor", "params": {"tensor_collective_backpressure_mode": "invalid"}},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw)

    def test_invalid_collective_credit_return_mode_rejected(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {"type": "tensor", "params": {"tensor_collective_credit_return_mode": "bad_mode"}},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw)

    def test_resolve_spec_v3_program_compiled_to_dsl(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {"tensor_exec_mode": "tile"},
                "program": {
                    "loop": False,
                    "ops": [
                        {"op_type": "gemm"},
                        {"op_type": "allreduce", "bytes": 1024, "blocking": False},
                        {"op_type": "softmax", "elems": 256},
                    ],
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(str(cfg["tensor_exec_mode"]), "program")
        self.assertEqual(int(cfg["tensor_program_loop"]), 0)
        self.assertIn("gemm", str(cfg["tensor_program_dsl"]))
        self.assertIn("allreduce", str(cfg["tensor_program_dsl"]))
        self.assertIn("softmax", str(cfg["tensor_program_dsl"]))
        # convenience: program allreduce should default collective_type if not set.
        self.assertEqual(str(cfg["tensor_collective_type"]), "allreduce")

    def test_program_softmax_missing_elems_rejected(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "program": {"loop": False, "ops": [{"op_type": "softmax"}]},
            },
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw)

    def test_exec_mode_program_requires_dsl(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {"type": "tensor", "params": {"tensor_exec_mode": "program"}},
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw)

    def test_resolve_spec_v3_program_dma_and_fence_compiled_to_dsl(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {
                    "tensor_exec_mode": "program",
                    "tensor_program_issue_width": 4,
                },
                "program": {
                    "loop": False,
                    "ops": [
                        {"op_type": "dma_read", "bytes": 1024},
                        {
                            "op_type": "gemm_ub",
                            "cycles": 10,
                            "ub_read_bytes": 256,
                            "ub_write_bytes": 128,
                        },
                        {"op_type": "fence"},
                        {"op_type": "dma_write", "bytes": 128},
                    ],
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(str(cfg["tensor_exec_mode"]), "program")
        self.assertEqual(int(cfg["tensor_program_loop"]), 0)
        dsl = str(cfg["tensor_program_dsl"])
        self.assertIn("dma_read", dsl)
        self.assertIn("gemm_ub", dsl)
        self.assertIn("fence", dsl)
        self.assertIn("dma_write", dsl)

    def test_resolve_spec_v3_program_supports_ub_buf_and_reset_consume(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {
                    "tensor_exec_mode": "program",
                    "tensor_program_issue_width": 4,
                    "tensor_program_ub_buffers": 2,
                },
                "program": {
                    "loop": False,
                    "ops": [
                        {"op_type": "dma_read", "bytes": 128, "buf": 1, "reset": True},
                        {
                            "op_type": "gemm_ub",
                            "cycles": 10,
                            "ub_read_bytes": 128,
                            "ub_write_bytes": 64,
                            "buf": 1,
                        },
                        {"op_type": "dma_write", "bytes": 64, "buf": 1, "consume": True},
                        {"op_type": "fence"},
                    ],
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(str(cfg["tensor_exec_mode"]), "program")
        self.assertEqual(int(cfg["tensor_program_loop"]), 0)
        self.assertEqual(int(cfg["tensor_program_ub_buffers"]), 2)
        dsl = str(cfg["tensor_program_dsl"])
        self.assertIn("dma_read:bytes=128,buf=1,reset=1", dsl)
        self.assertIn("gemm_ub:cycles=10,ub_read=128,ub_write=64,buf=1", dsl)
        self.assertIn("dma_write:bytes=64,buf=1,consume=1", dsl)

    def test_resolve_spec_v3_program_supports_ub_addr_and_gemm_shape_for_auto_cycles(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {
                    "tensor_exec_mode": "program",
                    "tensor_program_issue_width": 4,
                    "tensor_program_ub_buffers": 1,
                    "tensor_ub_bytes": 1024,
                },
                "program": {
                    "loop": False,
                    "ops": [
                        {"op_type": "dma_read", "bytes": 128, "ub_addr": 0, "reset": True},
                        {
                            "op_type": "gemm_ub",
                            "cycles": 0,
                            "m": 8,
                            "n": 8,
                            "k": 8,
                            "ub_read_bytes": 128,
                            "ub_write_bytes": 64,
                            "ub_read_addr": 0,
                            "ub_write_addr": 256,
                        },
                        {"op_type": "dma_write", "bytes": 64, "ub_addr": 256, "consume": True},
                        {"op_type": "fence"},
                    ],
                },
            },
        }
        resolved = resolve_spec(raw)
        cfg = resolved["tensor_cfg"]
        self.assertEqual(str(cfg["tensor_exec_mode"]), "program")
        dsl = str(cfg["tensor_program_dsl"])
        self.assertIn("dma_read:bytes=128", dsl)
        self.assertIn("ub_addr=0", dsl)
        self.assertIn("gemm_ub:cycles=0", dsl)
        self.assertIn("m=8", dsl)
        self.assertIn("n=8", dsl)
        self.assertIn("k=8", dsl)
        self.assertIn("ub_read_addr=0", dsl)
        self.assertIn("ub_write_addr=256", dsl)
        self.assertIn("dma_write:bytes=64", dsl)
        self.assertIn("ub_addr=256", dsl)

    def test_program_gemm_ub_cycles_zero_requires_shape(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "params": {
                    "tensor_exec_mode": "program",
                    "tensor_program_issue_width": 4,
                },
                "program": {
                    "loop": False,
                    "ops": [
                        {
                            "op_type": "gemm_ub",
                            "cycles": 0,
                            "ub_read_bytes": 128,
                            "ub_write_bytes": 64,
                        },
                    ],
                },
            },
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw)

    def test_program_disallow_mixing_legacy_gemm_with_dma_ops(self) -> None:
        raw = {
            "schema_version": 3,
            "model": "tensor",
            "workload": {
                "type": "tensor",
                "program": {
                    "loop": False,
                    "ops": [
                        {"op_type": "dma_read", "bytes": 64},
                        {"op_type": "gemm"},
                    ],
                },
            },
        }
        with self.assertRaises(SpecError):
            resolve_spec(raw)


if __name__ == "__main__":
    unittest.main()
