#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class ComputeEssentialSummaryMeshSramCLITest(unittest.TestCase):
    def _run_compute(self, run_dir: Path) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("compute_essential_summary_mesh.py")
        return subprocess.run(["python3", str(script), "--run-dir", str(run_dir)], text=True, capture_output=True)

    def test_summary_exports_sram_derived_fields_and_noc_sram_knobs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "noc_type": "multicast_mesh",
                        "noc_multicast": {
                            "enable": 1,
                            "block_w": 2,
                            "block_h": 2,
                            "local_endpoint_multicast_enable": 1,
                        },
                        "sram_effective_pe_core": {
                            "model_enable": 1,
                            "state_enable": 1,
                            "weight_idx_enable": 0,
                            "weight_l0_enable": 0,
                            "state_capacity_bytes": 262144,
                            "state_banks": 16,
                            "state_ports_per_bank": 1,
                            "state_bank_interleave_bytes": 4,
                            "state_t_read_cycles": 2,
                            "state_t_write_cycles": 2,
                            "state_sample_log2": 0,
                            "weight_idx_capacity_bytes": 131072,
                            "weight_idx_banks": 16,
                            "weight_l0_capacity_bytes": 65536,
                            "weight_l0_banks": 8,
                            "weight_ports_per_bank": 1,
                            "weight_bank_interleave_bytes": 4,
                            "weight_t_read_cycles": 2,
                            "weight_t_write_cycles": 2,
                            "weight_sample_log2": 0,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_idx_sram_reads_total", "Sum.u64": "11", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_idx_sram_writes_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_idx_sram_bytes_read_total", "Sum.u64": "110", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_idx_sram_bytes_write_total", "Sum.u64": "22", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_idx_sram_bank_conflict_ticks_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_idx_sram_predicted_extra_cycles_total", "Sum.u64": "8", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_idx_sram_bank_peak_accesses_per_tick", "Sum.u64": "5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_idx_sram_energy_read_pj_total", "Sum.f64": "1.5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_l0_sram_reads_total", "Sum.u64": "7", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_l0_sram_writes_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_l0_sram_bytes_read_total", "Sum.u64": "70", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_l0_sram_bytes_write_total", "Sum.u64": "10", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_l0_sram_bank_conflict_ticks_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_l0_sram_predicted_extra_cycles_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_l0_sram_bank_peak_accesses_per_tick", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_l0_sram_energy_write_pj_total", "Sum.f64": "2.5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "weight_sram_enforced_stall_cycles_total", "Sum.u64": "13", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "core_state_sram_reads_total", "Sum.u64": "17", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "core_state_sram_writes_total", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "core_state_sram_bytes_read_total", "Sum.u64": "170", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "core_state_sram_bytes_write_total", "Sum.u64": "30", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "core_state_sram_bank_conflict_ticks_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "core_state_sram_predicted_extra_cycles_total", "Sum.u64": "10", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "core_state_sram_bank_peak_accesses_per_tick", "Sum.u64": "9", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "core_state_sram_energy_read_pj_total", "Sum.f64": "3.5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "core_state_sram_energy_write_pj_total", "Sum.f64": "4.5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "core_state_sram_stall_cycles_total", "Sum.u64": "19", "SimTime": "0"},
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            model = summary.get("model") or {}
            self.assertEqual(model.get("noc_type"), "multicast_mesh")
            self.assertEqual(int(model.get("noc_multicast_enable") or 0), 1)
            self.assertEqual(int(model.get("noc_multicast_block_w") or 0), 2)
            self.assertEqual(int(model.get("noc_multicast_block_h") or 0), 2)
            self.assertEqual(int(model.get("noc_multicast_local_endpoint_multicast_enable") or 0), 1)
            self.assertEqual(int(model.get("sram_model_enable") or 0), 1)
            self.assertEqual(int(model.get("sram_state_enable") or 0), 1)
            self.assertEqual(int(model.get("sram_state_capacity_bytes") or 0), 262144)
            self.assertEqual(int(model.get("sram_state_banks") or 0), 16)
            self.assertEqual(int(model.get("sram_state_ports_per_bank") or 0), 1)
            sram = summary.get("sram") or {}
            self.assertEqual(int(sram["weight_idx"]["bank_peak_accesses_per_tick"]), 5)
            self.assertEqual(float(sram["weight_idx"]["energy_read_pj_total"]), 1.5)
            self.assertEqual(int(sram["weight_idx"]["accesses_total"]), 13)
            self.assertAlmostEqual(float(sram["weight_idx"]["predicted_extra_cycles_per_access"]), 8.0 / 13.0)
            self.assertAlmostEqual(float(sram["weight_idx"]["predicted_extra_cycles_per_conflict_tick"]), 8.0 / 4.0)
            self.assertEqual(int(sram["weight_l0"]["bank_peak_accesses_per_tick"]), 3)
            self.assertEqual(float(sram["weight_l0"]["energy_write_pj_total"]), 2.5)
            self.assertEqual(int(sram["weight_l0"]["accesses_total"]), 8)
            self.assertAlmostEqual(float(sram["weight_l0"]["predicted_extra_cycles_per_access"]), 4.0 / 8.0)
            self.assertEqual(int(sram["weight"]["enforced_stall_cycles_total"]), 13)
            self.assertEqual(int(sram["weight"]["predicted_extra_cycles_total"]), 12)
            self.assertEqual(int(sram["weight"]["bank_conflict_ticks_total"]), 6)
            self.assertEqual(int(sram["weight"]["accesses_total"]), 21)
            self.assertAlmostEqual(float(sram["weight"]["predicted_extra_cycles_per_access"]), 12.0 / 21.0)
            self.assertAlmostEqual(float(sram["weight"]["enforced_stall_cycles_per_access"]), 13.0 / 21.0)
            self.assertEqual(int(sram["state"]["bank_peak_accesses_per_tick"]), 9)
            self.assertEqual(float(sram["state"]["energy_read_pj_total"]), 3.5)
            self.assertEqual(float(sram["state"]["energy_write_pj_total"]), 4.5)
            self.assertEqual(int(sram["state"]["enforced_stall_cycles_total"]), 19)
            self.assertEqual(int(sram["state"]["accesses_total"]), 20)
            self.assertAlmostEqual(float(sram["state"]["predicted_extra_cycles_per_conflict_tick"]), 10.0 / 2.0)
            self.assertAlmostEqual(float(sram["state"]["enforced_stall_cycles_per_conflict_tick"]), 19.0 / 2.0)


if __name__ == "__main__":
    unittest.main()
