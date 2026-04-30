#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI-level regression tests for compute_essential_summary_mesh.py GAS byte accounting.

This test protects against a misleading summary where:
  - overfetch_bytes_total is clamped to 0 when unique_bytes_total < payload_bytes_total
  - the "net savings" (payload reuse) signal is therefore lost

We keep the legacy overfetch semantics for back-compat, but also require:
  - gas.net_unique_minus_payload_bytes_total (can be negative)
  - gas.payload_reuse_bytes_total (>=0)
"""

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("rows must be non-empty")
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


class ComputeEssentialSummaryMeshGasBytesCLITest(unittest.TestCase):
    def _run_compute(self, run_dir: Path) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("compute_essential_summary_mesh.py")
        cmd = ["python3", str(script), "--run-dir", str(run_dir)]
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_gas_net_negative_exposes_payload_reuse(self) -> None:
        # unique < payload => net negative (savings). Legacy overfetch stays 0,
        # but new fields must expose the negative net and reuse bytes.
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    # total unique = 900, payload = 1000 => net=-100
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_unique_bytes_total", "Sum.u64": "400", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_total_payload_bytes", "Sum.u64": "700", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "gas_unique_bytes_total", "Sum.u64": "500", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "gas_total_payload_bytes", "Sum.u64": "300", "SimTime": "0"},
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            gas = summary.get("gas") or {}

            self.assertEqual(int(gas.get("unique_bytes_total", -1)), 900)
            self.assertEqual(int(gas.get("payload_bytes_total", -1)), 1000)

            # Legacy field: clamp negative to 0 (kept for back-compat).
            self.assertEqual(int(gas.get("overfetch_bytes_total", -1)), 0)

            # New fields: must expose net negative and reuse.
            self.assertEqual(int(gas.get("net_unique_minus_payload_bytes_total", 0)), -100, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("payload_reuse_bytes_total", -1)), 100, msg=json.dumps(gas, indent=2))

    def test_gas_net_positive_exposes_overfetch(self) -> None:
        # unique > payload => net positive (overfetch). Reuse should be 0.
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    # total unique = 1100, payload = 1000 => net=+100
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_unique_bytes_total", "Sum.u64": "600", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_total_payload_bytes", "Sum.u64": "500", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "gas_unique_bytes_total", "Sum.u64": "500", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "gas_total_payload_bytes", "Sum.u64": "500", "SimTime": "0"},
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            gas = summary.get("gas") or {}

            self.assertEqual(int(gas.get("unique_bytes_total", -1)), 1100)
            self.assertEqual(int(gas.get("payload_bytes_total", -1)), 1000)

            self.assertEqual(int(gas.get("net_unique_minus_payload_bytes_total", 0)), 100, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("overfetch_bytes_total", -1)), 100, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("payload_reuse_bytes_total", -1)), 0, msg=json.dumps(gas, indent=2))

    def test_model_and_contracts_recover_meta_and_effective_fields(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "mesh_stats.csv").write_text(
                "ComponentName,StatisticName,Sum.u64,SimTime\n",
                encoding="utf-8",
            )
            (run_dir / "mesh_run.log").write_text("Simulation is complete, simulated time: 1 us\n", encoding="utf-8")
            (run_dir / "meta.json").write_text(
                json.dumps(
                    {
                        "model": {
                            "mesh_size": 4,
                            "num_pes": 16,
                            "workload_impl": "riscv_snn",
                            "exec_mode": "gas",
                            "line_size_bytes": 64,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "line_size_bytes": 64,
                        "per_core": [
                            {
                                "gatherbuf": {
                                    "apply_issue_policy": "order",
                                    "experimental_retire_policy": "global_inorder",
                                    "experimental_retire_shadow_per_post_enable": 0,
                                    "experimental_gcss_phase_breakdown_enable": 1,
                                    "experimental_gcss_vlf_queue_policy": "locality_first",
                                    "experimental_gcss_vlf_fair_band_size": 256,
                                }
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["model"]["mesh_size"], 4, msg=json.dumps(summary["model"], indent=2))
            self.assertEqual(summary["model"]["num_pes"], 16, msg=json.dumps(summary["model"], indent=2))
            self.assertEqual(summary["model"]["workload_impl"], "riscv_snn", msg=json.dumps(summary["model"], indent=2))
            self.assertEqual(summary["model"]["exec_mode"], "gas", msg=json.dumps(summary["model"], indent=2))
            self.assertEqual(summary["model"]["line_size_bytes"], 64, msg=json.dumps(summary["model"], indent=2))
            self.assertEqual(
                summary["contracts"]["experimental_gcss_phase_breakdown_enable"],
                True,
                msg=json.dumps(summary["contracts"], indent=2),
            )

    def test_memory_section_derives_from_memctrl_when_core_memory_stats_absent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "node0_memory_controller",
                        "StatisticName": "requests_received_GetS",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                ],
            )
            (run_dir / "mesh_run.log").write_text("Simulation is complete, simulated time: 1 us\n", encoding="utf-8")
            (run_dir / "meta.json").write_text(
                json.dumps({"model": {"mesh_size": 4, "num_pes": 16, "line_size_bytes": 64}}),
                encoding="utf-8",
            )
            (run_dir / "effective_config.json").write_text(json.dumps({"line_size_bytes": 64}), encoding="utf-8")

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["memory"]["memory_requests"], 5.0, msg=json.dumps(summary, indent=2))
            self.assertEqual(summary["memory"]["memory_bytes"], 320.0, msg=json.dumps(summary, indent=2))
            self.assertEqual(summary["memhierarchy"]["line_size_bytes"], 64, msg=json.dumps(summary, indent=2))

    def test_transport_sections_export_snn_tx_and_snn_rx_spike_packet_totals(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_tx_spike_packets_total", "Sum.u64": "11", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_tx_spikekey_packets_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_tx_spiketilekey_packets_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_spike_packets_total", "Sum.u64": "7", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_spikekey_total", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_spiketilekey_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_fastpath_packets_total", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_fallback_packets_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_decode_fail_total", "Sum.u64": "0", "SimTime": "0"},
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["snn_tx"]["spike_packets_total"], 11.0, msg=json.dumps(summary, indent=2))
            self.assertEqual(summary["snn_tx"]["spikekey_packets_total"], 2.0, msg=json.dumps(summary, indent=2))
            self.assertEqual(summary["snn_tx"]["spiketilekey_packets_total"], 1.0, msg=json.dumps(summary, indent=2))
            self.assertEqual(summary["snn_rx"]["spike_packets_total"], 7.0, msg=json.dumps(summary, indent=2))
            self.assertEqual(summary["snn_rx"]["spikekey_packets_total"], 3.0, msg=json.dumps(summary, indent=2))
            self.assertEqual(summary["snn_rx"]["spiketilekey_packets_total"], 1.0, msg=json.dumps(summary, indent=2))
            self.assertEqual(summary["snn_rx"]["fastpath_packets_total"], 3.0, msg=json.dumps(summary, indent=2))
            self.assertEqual(summary["snn_rx"]["fallback_packets_total"], 1.0, msg=json.dumps(summary, indent=2))


if __name__ == "__main__":
    unittest.main()
