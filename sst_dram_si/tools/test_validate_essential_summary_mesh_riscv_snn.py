#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


class ValidateEssentialSummaryMeshRiscvSnnCLITest(unittest.TestCase):
    def _run_validate(self, run_dir: Path) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("validate_essential_summary_mesh.py")
        return subprocess.run(["python3", str(script), "--run-dir", str(run_dir)], text=True, capture_output=True)

    def test_riscv_snn_gas_run_does_not_require_step_activation_invocations_to_match_windows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_json(
                run_dir / "meta.json",
                {
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "neurons_total": 96,
                        "exec_mode": "gas",
                        "workload_impl": "riscv_snn",
                        "sim_time": "1us",
                    }
                },
            )
            _write_json(run_dir / "effective_config.json", {"global_step_sync_enable": 0})
            (run_dir / "mesh_run.log").write_text("Simulation is complete, simulated time: 1 us\n", encoding="utf-8")
            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "neurons_total": 96,
                        "exec_mode": "gas",
                        "workload_impl": "riscv_snn",
                        "sim_time": "1us",
                        "step_activation_fraction": 0.5,
                        "step_activation_fanout": 2,
                    },
                    "gas": {
                        "windows": 32,
                        "windows_done": 32,
                        "windows_incomplete": 0,
                        "synapse_ops_step_total": 192.0,
                        "cycle_cost": 100000,
                        "gsops_step": 192.0 / 100000.0,
                    },
                    "step_activation": {
                        "invocations": 31.0,
                        "pre_selected_total": 96.0,
                        "firing_total": 96.0,
                        "fanout_config": 2.0,
                        "fanout_effective": 2.0,
                        "spike_attempts_total": 192.0,
                        "spikes_injected_total": 192.0,
                        "route_hits_total": 192.0,
                        "route_misses_total": 0.0,
                        "local_drops_total": 0.0,
                        "firing_rate_per_neuron_per_us": 1.0,
                    },
                    "spike_activity": {
                        "neurons_fired_total": 0.0,
                        "gas_scatter_spikes_emitted_total": 0.0,
                        "total_spikes_processed": 192.0,
                    },
                    "memory": {"memory_requests": 1.0, "memory_bytes": 64.0},
                    "memhierarchy": {
                        "line_size_bytes": 64,
                        "memctrl": {
                            "req_GetS": 1.0,
                            "req_GetX": 0.0,
                            "req_GetSX": 0.0,
                            "req_Write": 0.0,
                            "req_PutM": 0.0,
                            "req_total": 1.0,
                            "bytes_est_total": 64.0,
                        },
                        "l1": {
                            "req_GetS": 0.0,
                            "req_GetX": 0.0,
                            "req_GetSX": 0.0,
                            "req_Write": 0.0,
                            "req_PutM": 0.0,
                            "req_total": 0.0,
                            "bytes_est_total": 0.0,
                        },
                    },
                    "nic": {"packets_sent": 1, "packets_recv": 1},
                },
            )

            proc = self._run_validate(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("step_activation.invocations_vs_windows", proc.stdout)
            self.assertIn("SKIP", proc.stdout)

    def test_naive_raw_run_skips_gas_only_gatherbuf_contract_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_json(
                run_dir / "meta.json",
                {
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 20,
                        "neurons_per_core": 500,
                        "neurons_per_pe": 10000,
                        "neurons_total": 160000,
                        "exec_mode": "naive_raw",
                        "workload_impl": "snn",
                        "sim_time": "200us",
                        "max_steps": 1,
                    }
                },
            )
            _write_json(run_dir / "effective_config.json", {"global_step_sync_enable": 1})
            (run_dir / "mesh_run.log").write_text(
                "Simulation is complete, simulated time: 66.887 us\n",
                encoding="utf-8",
            )
            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 20,
                        "neurons_per_core": 500,
                        "neurons_per_pe": 10000,
                        "neurons_total": 160000,
                        "exec_mode": "naive_raw",
                        "workload_impl": "snn",
                        "sim_time": "200us",
                    },
                    "contracts": {
                        "apply_issue_policy": None,
                        "experimental_gcss_phase_breakdown_enable": False,
                        "experimental_gcss_vlf_fair_band_size": None,
                        "experimental_gcss_vlf_queue_policy": None,
                        "experimental_retire_policy": "unknown",
                        "experimental_retire_shadow_per_post_enable": False,
                        "gas_semantic_drain_before_scatter": True,
                        "gas_semantic_exactly_once_commit": True,
                        "gas_semantic_ready_before_commit": True,
                        "retire_policy_scope": "unknown",
                        "strict_repro_global_total_order_required": False,
                        "strict_repro_same_post_deterministic": True,
                    },
                    "gas": {
                        "windows": 16,
                        "windows_done": 16,
                        "windows_incomplete": 0,
                    },
                    "memory": {"memory_requests": 11524.0, "memory_bytes": 737536.0},
                    "memhierarchy": {
                        "line_size_bytes": 64,
                    },
                    "nic": {"packets_sent": 63124, "packets_recv": 1280},
                },
            )

            proc = self._run_validate(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn(
                "contracts.experimental_retire_policy_matches_effective_config: effective_config.gatherbuf.experimental_retire_policy missing",
                proc.stdout,
            )
            self.assertIn(
                "contracts.experimental_gcss_vlf_queue_policy_matches_effective_config: effective_config.gatherbuf.experimental_gcss_vlf_queue_policy missing",
                proc.stdout,
            )
            self.assertIn(
                "contracts.experimental_gcss_vlf_fair_band_size_matches_effective_config: effective_config.gatherbuf.experimental_gcss_vlf_fair_band_size missing",
                proc.stdout,
            )
            self.assertIn("SKIP", proc.stdout)
            self.assertIn("PASS memory.nonzero", proc.stdout)

    def test_partial_mesh_spec_first_run_accepts_node_limit_for_num_pes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            inputs_dir = run_dir / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            _write_json(
                inputs_dir / "spec.json",
                {
                    "schema_version": 3,
                    "platform": {
                        "mesh_size": 4,
                        "node_limit": 1,
                    },
                },
            )
            _write_json(
                run_dir / "meta.json",
                {
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 1,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "neurons_total": 6,
                        "exec_mode": "gas",
                        "workload_impl": "snn",
                        "sim_time": "1us",
                    }
                },
            )
            _write_json(run_dir / "effective_config.json", {"global_step_sync_enable": 1})
            (run_dir / "mesh_run.log").write_text("Simulation is complete, simulated time: 1 us\n", encoding="utf-8")
            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 1,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "neurons_total": 6,
                        "exec_mode": "gas",
                        "workload_impl": "snn",
                        "sim_time": "1us",
                        "step_activation_fraction": 0.5,
                        "step_activation_fanout": 2,
                    },
                    "gas": {
                        "windows": 1,
                        "windows_done": 1,
                        "windows_incomplete": 0,
                        "global_steps_done": 1,
                        "synapse_ops_step_total": 6.0,
                        "cycle_cost": 1000,
                        "gsops_step": 6.0 / 1000.0,
                    },
                    "step_activation": {
                        "invocations": 1.0,
                        "pre_selected_total": 3.0,
                        "firing_total": 3.0,
                        "fanout_config": 2.0,
                        "fanout_effective": 2.0,
                        "spike_attempts_total": 6.0,
                        "spikes_injected_total": 6.0,
                        "route_hits_total": 6.0,
                        "route_misses_total": 0.0,
                        "local_drops_total": 0.0,
                        "firing_rate_per_neuron_per_us": 0.5,
                    },
                    "spike_activity": {
                        "neurons_fired_total": 1.0,
                        "gas_scatter_spikes_emitted_total": 1.0,
                        "total_spikes_processed": 6.0,
                    },
                    "memory": {"memory_requests": 1.0, "memory_bytes": 64.0},
                    "memhierarchy": {
                        "line_size_bytes": 64,
                        "memctrl": {
                            "req_GetS": 1.0,
                            "req_GetX": 0.0,
                            "req_GetSX": 0.0,
                            "req_Write": 0.0,
                            "req_PutM": 0.0,
                            "req_total": 1.0,
                            "bytes_est_total": 64.0,
                            "req_GetS_minus_loader_est": 0.0,
                        },
                        "l1": {
                            "req_GetS": 0.0,
                            "req_GetX": 0.0,
                            "req_GetSX": 0.0,
                            "req_Write": 0.0,
                            "req_PutM": 0.0,
                            "req_total": 0.0,
                            "bytes_est_total": 0.0,
                        },
                    },
                    "nic": {"packets_sent": 1, "packets_recv": 1},
                },
            )

            proc = self._run_validate(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("model.num_pes", proc.stdout)
            self.assertIn("node_limit=1", proc.stdout)

    def test_riscv_snn_summary_passes_when_meta_memory_and_phase_breakdown_are_exported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_json(
                run_dir / "meta.json",
                {
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 4,
                        "neurons_per_core": 4,
                        "neurons_per_pe": 16,
                        "exec_mode": "gas",
                        "workload_impl": "riscv_snn",
                        "sim_time": "1us",
                        "line_size_bytes": 64,
                    }
                },
            )
            _write_json(
                run_dir / "effective_config.json",
                {
                    "line_size_bytes": 64,
                    "per_core": [
                        {
                            "gatherbuf": {
                                "apply_issue_policy": "order",
                                "experimental_retire_policy": "global_inorder",
                                "experimental_retire_shadow_per_post_enable": 0,
                                "experimental_gcss_phase_breakdown_enable": 0,
                                "experimental_gcss_vlf_queue_policy": "locality_first",
                                "experimental_gcss_vlf_fair_band_size": 256,
                            }
                        }
                    ],
                },
            )
            (run_dir / "mesh_run.log").write_text("Simulation is complete, simulated time: 1 us\n", encoding="utf-8")
            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 4,
                        "neurons_per_core": 4,
                        "neurons_per_pe": 16,
                        "exec_mode": "gas",
                        "workload_impl": "riscv_snn",
                        "sim_time": "1us",
                        "line_size_bytes": 64,
                    },
                    "contracts": {
                        "apply_issue_policy": "order",
                        "experimental_retire_policy": "global_inorder",
                        "experimental_retire_shadow_per_post_enable": False,
                        "experimental_gcss_phase_breakdown_enable": False,
                        "experimental_gcss_vlf_queue_policy": "locality_first",
                        "experimental_gcss_vlf_fair_band_size": 256,
                        "retire_policy_scope": "global_total_order",
                        "strict_repro_same_post_deterministic": True,
                        "strict_repro_global_total_order_required": False,
                        "gas_semantic_ready_before_commit": True,
                        "gas_semantic_drain_before_scatter": True,
                    },
                    "gas": {
                        "windows": 16,
                        "windows_done": 16,
                        "windows_incomplete": 0,
                    },
                    "memory": {"memory_requests": 5.0, "memory_bytes": 320.0},
                    "memhierarchy": {
                        "line_size_bytes": 64,
                        "memctrl": {
                            "req_total": 5.0,
                            "req_GetS": 5.0,
                            "req_GetX": 0.0,
                            "req_GetSX": 0.0,
                            "req_Write": 0.0,
                            "req_PutM": 0.0,
                            "bytes_est_total": 320.0,
                            "req_GetS_minus_loader_est": 0.0,
                        },
                        "l1": {
                            "req_total": 0.0,
                            "req_GetS": 0.0,
                            "req_GetX": 0.0,
                            "req_GetSX": 0.0,
                            "req_Write": 0.0,
                            "req_PutM": 0.0,
                            "bytes_est_total": 0.0,
                        },
                    },
                    "nic": {"packets_sent": 1, "packets_recv": 1},
                },
            )

            proc = self._run_validate(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("contracts.experimental_gcss_phase_breakdown_enable_matches_effective_config", proc.stdout)
            self.assertIn("memory.nonzero", proc.stdout)
            self.assertIn("memhierarchy.line_size_bytes_nonzero", proc.stdout)
            self.assertNotIn(" FAIL contracts.experimental_gcss_phase_breakdown_enable_matches_effective_config", proc.stdout)
            self.assertNotIn(" FAIL memory.nonzero", proc.stdout)
            self.assertNotIn(" FAIL memhierarchy.line_size_bytes_nonzero", proc.stdout)

    def test_riscv_snn_validate_accepts_transport_visibility_when_summary_exports_tx_and_rx_spike_packets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_json(
                run_dir / "meta.json",
                {
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 4,
                        "neurons_per_core": 4,
                        "neurons_per_pe": 16,
                        "exec_mode": "gas",
                        "workload_impl": "riscv_snn",
                        "sim_time": "1us",
                        "line_size_bytes": 64,
                    }
                },
            )
            _write_json(
                run_dir / "effective_config.json",
                {
                    "line_size_bytes": 64,
                    "per_core": [
                        {
                            "gatherbuf": {
                                "apply_issue_policy": "order",
                                "experimental_retire_policy": "global_inorder",
                                "experimental_retire_shadow_per_post_enable": 0,
                                "experimental_gcss_phase_breakdown_enable": 0,
                                "experimental_gcss_vlf_queue_policy": "locality_first",
                                "experimental_gcss_vlf_fair_band_size": 256,
                            }
                        }
                    ],
                },
            )
            (run_dir / "mesh_run.log").write_text("Simulation is complete, simulated time: 1 us\n", encoding="utf-8")
            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "exec_mode": "gas",
                        "workload_impl": "riscv_snn",
                        "line_size_bytes": 64,
                    },
                    "contracts": {
                        "apply_issue_policy": "order",
                        "experimental_retire_policy": "global_inorder",
                        "experimental_retire_shadow_per_post_enable": False,
                        "experimental_gcss_phase_breakdown_enable": False,
                        "experimental_gcss_vlf_queue_policy": "locality_first",
                        "experimental_gcss_vlf_fair_band_size": 256,
                        "retire_policy_scope": "global_total_order",
                        "strict_repro_same_post_deterministic": True,
                        "strict_repro_global_total_order_required": False,
                        "gas_semantic_ready_before_commit": True,
                        "gas_semantic_drain_before_scatter": True,
                    },
                    "gas": {
                        "windows": 1.0,
                        "windows_done": 1.0,
                        "windows_incomplete": 0.0,
                    },
                    "step": {
                        "global_steps_done": 1.0,
                    },
                    "spike_activity": {
                        "neurons_fired_total": 1.0,
                        "gas_scatter_spikes_emitted_total": 1.0,
                    },
                    "memory": {
                        "memory_requests": 5.0,
                        "memory_bytes": 320.0,
                    },
                    "memhierarchy": {
                        "line_size_bytes": 64,
                        "memctrl": {"req_total": 5.0},
                    },
                    "snn_tx": {
                        "spike_packets_total": 11.0,
                        "spikekey_packets_total": 2.0,
                        "spiketilekey_packets_total": 1.0,
                    },
                    "snn_rx": {
                        "spike_packets_total": 7.0,
                        "spikekey_packets_total": 3.0,
                        "spiketilekey_packets_total": 1.0,
                        "fastpath_packets_total": 3.0,
                        "fallback_packets_total": 1.0,
                        "decode_fail_total": 0.0,
                    },
                },
            )

            proc = self._run_validate(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("PASS snn_rx.packet_accounting", proc.stdout, msg=proc.stdout)
            self.assertIn("PASS snn_tx.nonzero", proc.stdout, msg=proc.stdout)
            self.assertNotIn("SKIP snn_rx.packet_accounting", proc.stdout, msg=proc.stdout)
            self.assertNotIn("SKIP snn_tx.nonzero", proc.stdout, msg=proc.stdout)


if __name__ == "__main__":
    unittest.main()
