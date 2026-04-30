#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal CLI-level tests for validate_essential_summary_mesh.py "paper" profile.

We intentionally test the command line entrypoint to ensure argument parsing,
exit codes, and human-readable diagnostics remain stable.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


class ValidatePaperProfileCLITest(unittest.TestCase):
    def _run_validate(self, run_dir: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("validate_essential_summary_mesh.py")
        cmd = ["python3", str(script), "--run-dir", str(run_dir), *extra_args]
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_paper_profile_requires_meta_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            # Only summary is present; meta.json is intentionally missing.
            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "run_dir": str(run_dir),
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "neurons_total": 96,
                        "sim_time": "100us",
                        "exec_mode": "gas",
                        "workload_impl": "snn",
                        "step_activation_fraction": 0.5,
                        "step_activation_fanout": 2,
                    },
                    "gas": {
                        "windows": 16,
                        "windows_done": 16,
                        "windows_incomplete": 0,
                        "global_steps_done": 1,
                        "synapse_ops_step_total": 96.0,
                        "cycle_cost": 100000,
                        "gsops_step": 96.0 / 100000.0,
                    },
                    "step_activation": {
                        "invocations": 16.0,
                        "pre_selected_total": 48.0,
                        "firing_total": 48.0,
                        "fanout_config": 2.0,
                        "fanout_effective": 2.0,
                        "spike_attempts_total": 96.0,
                        "spikes_injected_total": 96.0,
                        "route_hits_total": 96.0,
                        "route_misses_total": 0.0,
                        "local_drops_total": 0.0,
                    },
                    "spike_activity": {
                        "neurons_fired_total": 1.0,
                        "gas_scatter_spikes_emitted_total": 1.0,
                        "total_spikes_processed": 96.0,
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

            proc = self._run_validate(run_dir, "--profile", "paper")
            self.assertNotEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            combined = (proc.stdout + proc.stderr).lower()
            self.assertIn("meta.json", combined, msg=proc.stdout + proc.stderr)

    def test_paper_profile_passes_with_valid_meta_and_config_hash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            inputs_dir = run_dir / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)

            # Create local_run_config.json and compute its hash (paper requires this provenance).
            cfg = {
                "sim_time": "100us",
                "num_cores_per_pe": 2,
                "neurons_per_core": 3,
                "global_step_sync_enable": 1,
                "step_activation_fraction": 0.5,
                "step_activation_fanout": 2,
                "step_activation_use_bcsr_routes": 0,
            }
            cfg_path = inputs_dir / "local_run_config.json"
            _write_json(cfg_path, cfg)
            cfg_sha = _sha256_file(cfg_path)

            # Summary must be consistent with cfg-derived model invariants.
            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "run_dir": str(run_dir),
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "neurons_total": 96,
                        "sim_time": "100us",
                        "exec_mode": "gas",
                        "workload_impl": "snn",
                        "step_activation_fraction": 0.5,
                        "step_activation_fanout": 2,
                    },
                    "step": {
                        "global_steps_done": 2,
                    },
                    "gas": {
                        "windows": 32,
                        "windows_done": 32,
                        "windows_incomplete": 0,
                        "global_steps_done": 2,
                        "synapse_ops_step_total": 192.0,
                        "cycle_cost": 100000,
                        "gsops_step": 192.0 / 100000.0,
                    },
                    "step_activation": {
                        "invocations": 32.0,
                        "pre_selected_total": 96.0,
                        "firing_total": 96.0,
                        "fanout_config": 2.0,
                        "fanout_effective": 2.0,
                        "spike_attempts_total": 192.0,
                        "spikes_injected_total": 192.0,
                        "route_hits_total": 192.0,
                        "route_misses_total": 0.0,
                        "local_drops_total": 0.0,
                    },
                    "spike_activity": {
                        "neurons_fired_total": 1.0,
                        "gas_scatter_spikes_emitted_total": 1.0,
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

            meta = {
                "schema_version": 1,
                "versions": {"sst_version": "SST-Core Version (15.0.0)", "python_version": "3.x"},
                "environment": {
                    "SNNDL_WORKLOAD_IMPL": "snn",
                    "MESH_EXEC_MODE": "gas",
                    "MESH_SIM_TIME": "",
                    "MESH_BCSR_DIR": "",
                    "SST_INSTALL_PREFIX": "",
                    "MESH_MAX_STEPS": "2",
                },
                "inputs": {
                    "local_run_config": {
                        "path": "inputs/local_run_config.json",
                        "sha256": cfg_sha,
                        "bytes": cfg_path.stat().st_size,
                    }
                },
                "model": {
                    "mesh_size": 4,
                    "num_pes": 16,
                    "num_cores_per_pe": 2,
                    "neurons_per_core": 3,
                    "neurons_per_pe": 6,
                    "sim_time": "100us",
                    "exec_mode": "gas",
                    "workload_impl": "snn",
                    "max_steps": 2,
                },
            }
            _write_json(run_dir / "meta.json", meta)

            # Paper profile requires a run log to exist; keep it minimal and non-emergency.
            (run_dir / "mesh_run.log").write_text("Simulation is complete, simulated time: 1 us\n", encoding="utf-8")

            proc = self._run_validate(run_dir, "--profile", "paper")
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

    def test_paper_profile_requires_qni_reason_mix_when_phase_breakdown_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            inputs_dir = run_dir / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)

            cfg = {
                "sim_time": "100us",
                "num_cores_per_pe": 2,
                "neurons_per_core": 3,
                "global_step_sync_enable": 1,
                "step_activation_fraction": 0.5,
                "step_activation_fanout": 2,
                "step_activation_use_bcsr_routes": 0,
            }
            cfg_path = inputs_dir / "local_run_config.json"
            _write_json(cfg_path, cfg)
            cfg_sha = _sha256_file(cfg_path)

            _write_json(
                run_dir / "effective_config.json",
                {
                    "per_core": [
                        {
                            "pe": 0,
                            "core": 0,
                            "gatherbuf": {
                                "apply_issue_policy": "order",
                                "experimental_retire_policy": "global_inorder",
                                "experimental_gcss_phase_breakdown_enable": 1,
                            },
                        }
                    ]
                },
            )

            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "run_dir": str(run_dir),
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "neurons_total": 96,
                        "sim_time": "100us",
                        "exec_mode": "gas",
                        "workload_impl": "snn",
                        "step_activation_fraction": 0.5,
                        "step_activation_fanout": 2,
                    },
                    "step": {
                        "global_steps_done": 2,
                    },
                    "gas": {
                        "windows": 32,
                        "windows_done": 32,
                        "windows_incomplete": 0,
                        "global_steps_done": 2,
                        "synapse_ops_step_total": 192.0,
                        "cycle_cost": 100000,
                        "gsops_step": 192.0 / 100000.0,
                    },
                    "contracts": {
                        "apply_issue_policy": "order",
                        "experimental_retire_policy": "global_inorder",
                        "experimental_gcss_phase_breakdown_enable": True,
                        "retire_policy_scope": "global_total_order",
                        "strict_repro_same_post_deterministic": True,
                        "strict_repro_global_total_order_required": False,
                        "gas_semantic_ready_before_commit": True,
                        "gas_semantic_drain_before_scatter": True,
                        "gas_semantic_exactly_once_commit": True,
                    },
                    "retire_hol_attribution_core": {
                        "head_source_mix": {
                            "hol_cycles_by_src": {"gcss": 3},
                            "blocked_edges_by_src": {"gcss": 30},
                            "dominant_src_by_hol_cycles": "gcss",
                            "dominant_src_by_blocked_edges": "gcss",
                        },
                        "gcss_phase_mix": {
                            "hol_cycles_by_phase": {
                                "queued_not_issued": 1,
                                "issued_wait_resp": 2,
                                "resp_ready_but_hol": 3,
                            },
                            "blocked_edges_by_phase": {
                                "queued_not_issued": 10,
                                "issued_wait_resp": 20,
                                "resp_ready_but_hol": 24,
                            },
                            "dominant_phase_by_hol_cycles": "resp_ready_but_hol",
                            "dominant_phase_by_blocked_edges": "resp_ready_but_hol",
                        },
                    },
                    "step_activation": {
                        "invocations": 32.0,
                        "pre_selected_total": 96.0,
                        "firing_total": 96.0,
                        "fanout_config": 2.0,
                        "fanout_effective": 2.0,
                        "spike_attempts_total": 192.0,
                        "spikes_injected_total": 192.0,
                        "route_hits_total": 192.0,
                        "route_misses_total": 0.0,
                        "local_drops_total": 0.0,
                    },
                    "spike_activity": {
                        "neurons_fired_total": 1.0,
                        "gas_scatter_spikes_emitted_total": 1.0,
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

            meta = {
                "schema_version": 1,
                "versions": {"sst_version": "SST-Core Version (15.0.0)", "python_version": "3.x"},
                "environment": {
                    "SNNDL_WORKLOAD_IMPL": "snn",
                    "MESH_EXEC_MODE": "gas",
                    "MESH_SIM_TIME": "",
                    "MESH_BCSR_DIR": "",
                    "SST_INSTALL_PREFIX": "",
                    "MESH_MAX_STEPS": "2",
                },
                "inputs": {
                    "local_run_config": {
                        "path": "inputs/local_run_config.json",
                        "sha256": cfg_sha,
                        "bytes": cfg_path.stat().st_size,
                    }
                },
                "model": {
                    "mesh_size": 4,
                    "num_pes": 16,
                    "num_cores_per_pe": 2,
                    "neurons_per_core": 3,
                    "neurons_per_pe": 6,
                    "sim_time": "100us",
                    "exec_mode": "gas",
                    "workload_impl": "snn",
                    "max_steps": 2,
                },
            }
            _write_json(run_dir / "meta.json", meta)
            (run_dir / "mesh_run.log").write_text("Simulation is complete, simulated time: 1 us\n", encoding="utf-8")

            proc = self._run_validate(run_dir, "--profile", "paper")
            self.assertNotEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("gcss_queued_reason_mix", proc.stdout + proc.stderr)

    def test_bcsr_merge_read_inconclusive_is_skip_in_step1_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            inputs_dir = run_dir / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)

            # Enable merge-read marker validation; we simulate a step-limited smoke run (max_steps=1)
            # where the run stops before any relevant read responses were verified.
            cfg = {
                "sim_time": "100us",
                "num_cores_per_pe": 2,
                "neurons_per_core": 3,
                "global_step_sync_enable": 1,
                "step_activation_fraction": 0.5,
                "step_activation_fanout": 2,
                "step_activation_use_bcsr_routes": 0,
                "bcsr_merge_read_verify_enable": 1,
            }
            cfg_path = inputs_dir / "local_run_config.json"
            _write_json(cfg_path, cfg)
            cfg_sha = _sha256_file(cfg_path)

            # Provide a real path for bcsr_meta_path_exists check.
            bcsr_meta = inputs_dir / "core00.bcsr.bin.meta.json"
            _write_json(bcsr_meta, {"rows": 3, "cols": 3, "format": "bcsr"})

            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "run_dir": str(run_dir),
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "neurons_total": 96,
                        "sim_time": "100us",
                        "exec_mode": "gas",
                        "workload_impl": "snn",
                        "step_activation_fraction": 0.5,
                        "step_activation_fanout": 2,
                        "bcsr_meta_path": str(bcsr_meta),
                    },
                    "step": {
                        "global_steps_done": 1,
                    },
                    "gas": {
                        "windows": 16,
                        "windows_done": 16,
                        "windows_incomplete": 0,
                        "global_steps_done": 1,
                        "synapse_ops_step_total": 96.0,
                        "cycle_cost": 100000,
                        "gsops_step": 96.0 / 100000.0,
                    },
                    "step_activation": {
                        "invocations": 16.0,
                        "pre_selected_total": 48.0,
                        "firing_total": 48.0,
                        "fanout_config": 2.0,
                        "fanout_effective": 2.0,
                        "spike_attempts_total": 96.0,
                        "spikes_injected_total": 96.0,
                        "route_hits_total": 96.0,
                        "route_misses_total": 0.0,
                        "local_drops_total": 0.0,
                    },
                    "spike_activity": {
                        "neurons_fired_total": 1.0,
                        "gas_scatter_spikes_emitted_total": 1.0,
                        "total_spikes_processed": 96.0,
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

            meta = {
                "schema_version": 1,
                "versions": {"sst_version": "SST-Core Version (15.0.0)", "python_version": "3.x"},
                "environment": {
                    "SNNDL_WORKLOAD_IMPL": "snn",
                    "MESH_EXEC_MODE": "gas",
                    "MESH_SIM_TIME": "",
                    "MESH_BCSR_DIR": "",
                    "SST_INSTALL_PREFIX": "",
                    "MESH_MAX_STEPS": "1",
                },
                "inputs": {
                    "local_run_config": {
                        "path": "inputs/local_run_config.json",
                        "sha256": cfg_sha,
                        "bytes": cfg_path.stat().st_size,
                    }
                },
                "model": {
                    "mesh_size": 4,
                    "num_pes": 16,
                    "num_cores_per_pe": 2,
                    "neurons_per_core": 3,
                    "neurons_per_pe": 6,
                    "sim_time": "100us",
                    "exec_mode": "gas",
                    "workload_impl": "snn",
                    "max_steps": 1,
                    "bcsr_meta_path": str(bcsr_meta),
                },
            }
            _write_json(run_dir / "meta.json", meta)

            # Marker present but explicitly inconclusive due to no verified responses.
            (run_dir / "mesh_run.log").write_text(
                "GatherBufferIF[finishByteExact_:0]: "
                "BCSR_MERGE_READ_VERIFY: WARN INCONCLUSIVE mode=raw_bcsr_v1 node=0 core=0 "
                "verified_resps=0 reason=no_verified_resps\n"
                "WeightMemorySubsystem[emitBcsrSemanticVerifyMarker_:0]: "
                "BCSR_SEMANTIC_VERIFY: PASS node=0 core=0 where=finish seq=0 verified_edges=8 sample_edges=8\n",
                encoding="utf-8",
            )

            proc = self._run_validate(run_dir, "--profile", "paper")
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("SKIP byte_exact.gas_merge_read.pass_marker", proc.stdout, msg=proc.stdout + proc.stderr)
            self.assertNotIn("WARN byte_exact.gas_merge_read.pass_marker", proc.stdout, msg=proc.stdout + proc.stderr)

    def test_paper_profile_requires_step_limited_mode(self) -> None:
        """Paper mode requires step-limited runs (MESH_MAX_STEPS>0) for reproducibility."""
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            inputs_dir = run_dir / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)

            cfg = {
                "sim_time": "100us",
                "num_cores_per_pe": 2,
                "neurons_per_core": 3,
                "global_step_sync_enable": 1,
                "step_activation_fraction": 0.5,
                "step_activation_fanout": 2,
                "step_activation_use_bcsr_routes": 0,
            }
            cfg_path = inputs_dir / "local_run_config.json"
            _write_json(cfg_path, cfg)
            cfg_sha = _sha256_file(cfg_path)

            # Simulate a run where 2 windows/PE were observed, but only 1 global step was
            # globally completed (typical stop-at truncation with drain-based done policy).
            inv = 32.0  # == gas.windows (legacy per-window injection)
            pre = 96.0  # inv * neurons_per_pe(6) * frac(0.5)
            attempts = pre * 2.0
            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "run_dir": str(run_dir),
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "neurons_total": 96,
                        "sim_time": "100us",
                        "exec_mode": "gas",
                        "workload_impl": "snn",
                        "step_activation_fraction": 0.5,
                        "step_activation_fanout": 2,
                    },
                    "gas": {
                        "windows": 32,
                        "windows_done": 32,
                        "windows_incomplete": 0,
                        "global_steps_done": 1,
                        "synapse_ops_step_total": float(attempts),
                        "cycle_cost": 100000,
                        "gsops_step": float(attempts) / 100000.0,
                    },
                    "step_activation": {
                        "invocations": inv,
                        "pre_selected_total": pre,
                        "firing_total": pre,
                        "fanout_config": 2.0,
                        "fanout_effective": 2.0,
                        "spike_attempts_total": float(attempts),
                        "spikes_injected_total": float(attempts),
                        "route_hits_total": float(attempts),
                        "route_misses_total": 0.0,
                        "local_drops_total": 0.0,
                    },
                    "spike_activity": {
                        "neurons_fired_total": 1.0,
                        "gas_scatter_spikes_emitted_total": 1.0,
                        "total_spikes_processed": 1.0,
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

            meta = {
                "schema_version": 1,
                "versions": {"sst_version": "SST-Core Version (15.0.0)", "python_version": "3.x"},
                "environment": {
                    "SNNDL_WORKLOAD_IMPL": "snn",
                    "MESH_EXEC_MODE": "gas",
                    "MESH_SIM_TIME": "",
                    "MESH_BCSR_DIR": "",
                    "SST_INSTALL_PREFIX": "",
                    "MESH_MAX_STEPS": "0",
                },
                "inputs": {
                    "local_run_config": {
                        "path": "inputs/local_run_config.json",
                        "sha256": cfg_sha,
                        "bytes": cfg_path.stat().st_size,
                    }
                },
                "model": {
                    "mesh_size": 4,
                    "num_pes": 16,
                    "num_cores_per_pe": 2,
                    "neurons_per_core": 3,
                    "neurons_per_pe": 6,
                    "sim_time": "100us",
                    "exec_mode": "gas",
                    "workload_impl": "snn",
                    "max_steps": 0,
                },
            }
            _write_json(run_dir / "meta.json", meta)

            proc = self._run_validate(run_dir, "--profile", "paper")
            self.assertNotEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

    def test_packet_accounting_accepts_fastpath_and_fallback_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_json(
                run_dir / "essential_summary_mesh.json",
                {
                    "run_dir": str(run_dir),
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "neurons_total": 96,
                        "sim_time": "100us",
                        "exec_mode": "gas",
                        "workload_impl": "snn",
                        "max_steps": 1,
                    },
                    "gas": {
                        "windows": 16,
                        "windows_done": 16,
                        "windows_incomplete": 0,
                        "global_steps_done": 1,
                    },
                    "step_activation": {
                        "invocations": 16.0,
                        "pre_selected_total": 48.0,
                        "firing_total": 48.0,
                        "spike_attempts_total": 96.0,
                        "spikes_injected_total": 96.0,
                        "route_hits_total": 96.0,
                        "route_misses_total": 0.0,
                        "local_drops_total": 0.0,
                    },
                    "spike_activity": {
                        "neurons_fired_total": 1.0,
                        "gas_scatter_spikes_emitted_total": 1.0,
                        "total_spikes_processed": 96.0,
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
                    "snn_rx": {
                        "spike_packets_total": 0.0,
                        "spikekey_packets_total": 9.0,
                        "spiketilekey_packets_total": 0.0,
                        "fastpath_packets_total": 4.0,
                        "fallback_packets_total": 5.0,
                        "decode_fail_total": 0.0,
                    },
                },
            )
            _write_json(
                run_dir / "meta.json",
                {
                    "schema_version": 1,
                    "versions": {"sst_version": "SST-Core Version (15.0.0)", "python_version": "3.x"},
                    "environment": {
                        "SNNDL_WORKLOAD_IMPL": "snn",
                        "MESH_EXEC_MODE": "gas",
                        "MESH_MAX_STEPS": "1",
                    },
                    "inputs": {},
                    "model": {
                        "mesh_size": 4,
                        "num_pes": 16,
                        "num_cores_per_pe": 2,
                        "neurons_per_core": 3,
                        "neurons_per_pe": 6,
                        "sim_time": "100us",
                        "exec_mode": "gas",
                        "workload_impl": "snn",
                        "max_steps": 1,
                    },
                },
            )

            proc = self._run_validate(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("PASS snn_rx.packet_accounting", proc.stdout, msg=proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
