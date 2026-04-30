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
    if not rows:
        raise ValueError("rows must be non-empty")
    path.parent.mkdir(parents=True, exist_ok=True)
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


class ComputeEssentialSummaryMeshP0P1CLITest(unittest.TestCase):
    def _run_compute(self, run_dir: Path) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("compute_essential_summary_mesh.py")
        return subprocess.run(["python3", str(script), "--run-dir", str(run_dir)], text=True, capture_output=True)

    def _run_validate(self, run_dir: Path) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("validate_essential_summary_mesh.py")
        return subprocess.run(["python3", str(script), "--run-dir", str(run_dir)], text=True, capture_output=True)

    def test_p0_summary_exposes_apply_retire_and_barrier_breakdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {
                                "pe": 0,
                                "core": 0,
                                "gatherbuf": {
                                    "apply_issue_policy": "order",
                                    "experimental_retire_policy": "global_inorder",
                                    "experimental_gcss_vlf_queue_policy": "locality_first",
                                    "experimental_gcss_vlf_fair_band_size": 256,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "pe_0_memory_controller", "StatisticName": "requests_received_GetS", "Sum.u64": "8", "SimTime": "0"},
                    {"ComponentName": "core_0", "StatisticName": "memory_requests", "Sum.u64": "8", "SimTime": "0"},
                    {"ComponentName": "core_0", "StatisticName": "mem_req_size_bytes", "Sum.u64": "512", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_global_hol_cycles_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_ready_but_blocked_edges_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_per_post_progress_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_samepost_blocked_edges_total", "Sum.u64": "7", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_crosspost_blocked_edges_total", "Sum.u64": "13", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_cycles_total", "Sum.u64": "5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_edges_total", "Sum.u64": "11", "SimTime": "0"},
                ],
            )
            _write_csv(
                run_dir / "pe_stage_events_db.csv",
                [
                    {
                        "seq": "1",
                        "bg_ns": "100",
                        "ga_ns": "200",
                        "ea_ns": "260",
                        "bs_ns": "320",
                        "es_ns": "400",
                        "gather_ns": "100",
                        "apply_ns": "120",
                        "scatter_ns": "80",
                        "total_ns": "300",
                    }
                ],
            )
            _write_csv(
                run_dir / "pe_step_perf_db.csv",
                [
                    {
                        "seq": "1",
                        "apply_issue_attempt_total": "10",
                        "apply_issue_success_total": "3",
                        "apply_issue_block_no_ready_total": "4",
                        "apply_issue_block_inflight_cap_total": "2",
                        "apply_issue_block_bank_credit_total": "1",
                        "apply_issue_block_downstream_busy_total": "0",
                        "apply_issue_block_retire_guard_total": "1",
                        "apply_ready_queue_peak": "6",
                        "apply_ready_queue_nonempty_cycles_total": "7",
                        "apply_first_issue_delay_ns": "30",
                        "apply_first_down_resp_delay_ns": "90",
                        "apply_first_granule_done_delay_ns": "110",
                        "apply_first_up_resp_delay_ns": "140",
                        "apply_down_resp_total": "5",
                        "apply_completed_granules_total": "3",
                        "apply_emitted_subreads_total": "15",
                        "retire_wait_cycles_total": "50",
                        "retire_wait_cycles_due_to_hol_total": "20",
                        "retire_wait_cycles_due_to_barrier_total": "10",
                        "retire_wait_cycles_due_to_not_ready_total": "20",
                        "retire_samepost_blocked_edges_total": "7",
                        "retire_crosspost_blocked_edges_total": "13",
                        "retire_policy_loss_cycles_total": "5",
                        "retire_policy_loss_edges_total": "11",
                        "retire_ready_queue_peak": "8",
                        "retire_unblock_events_total": "4",
                        "step_barrier_wait_ns": "2000",
                    }
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            gas = summary.get("gas") or {}
            pipeline = summary.get("pipeline") or {}
            critical_path = summary.get("critical_path") or {}
            contracts = summary.get("contracts") or {}
            step = summary.get("step") or {}
            per_step = step.get("per_step") or []

            self.assertEqual(int(gas.get("apply_issue_block_bank_credit_total", -1)), 1, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("apply_issue_block_downstream_busy_total", -1)), 0, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_wait_cycles_total", -1)), 50, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_wait_cycles_due_to_hol_total", -1)), 20, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_wait_cycles_due_to_barrier_total", -1)), 10, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_wait_cycles_due_to_not_ready_total", -1)), 20, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_samepost_blocked_edges_total", -1)), 7, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_crosspost_blocked_edges_total", -1)), 13, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_policy_loss_cycles_total", -1)), 5, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_policy_loss_edges_total", -1)), 11, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_ready_queue_peak_max", -1)), 8, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_unblock_events_total", -1)), 4, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("step_barrier_wait_ns_total", -1)), 2000, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("step_barrier_wait_ns_avg", -1)), 2000, msg=json.dumps(gas, indent=2))
            self.assertEqual(contracts.get("apply_issue_policy"), "order", msg=json.dumps(contracts, indent=2))
            self.assertEqual(contracts.get("experimental_retire_policy"), "global_inorder", msg=json.dumps(contracts, indent=2))
            self.assertEqual(contracts.get("experimental_gcss_vlf_queue_policy"), "locality_first", msg=json.dumps(contracts, indent=2))
            self.assertEqual(int(contracts.get("experimental_gcss_vlf_fair_band_size", -1)), 256, msg=json.dumps(contracts, indent=2))
            self.assertEqual(contracts.get("retire_policy_scope"), "global_total_order", msg=json.dumps(contracts, indent=2))
            self.assertIs(contracts.get("strict_repro_same_post_deterministic"), True, msg=json.dumps(contracts, indent=2))
            self.assertIs(contracts.get("strict_repro_global_total_order_required"), False, msg=json.dumps(contracts, indent=2))
            self.assertIs(contracts.get("gas_semantic_ready_before_commit"), True, msg=json.dumps(contracts, indent=2))
            self.assertIs(contracts.get("gas_semantic_drain_before_scatter"), True, msg=json.dumps(contracts, indent=2))
            self.assertAlmostEqual(float(pipeline.get("first_issue_to_first_resp_ratio", -1.0)), 3.0, places=6, msg=json.dumps(pipeline, indent=2))
            self.assertEqual(critical_path.get("stage"), "barrier_wait", msg=json.dumps(critical_path, indent=2))
            self.assertEqual(len(per_step), 1)
            self.assertEqual(int(per_step[0].get("step_barrier_wait_ns", -1)), 2000)
            self.assertEqual(int(per_step[0].get("retire_samepost_blocked_edges_total", -1)), 7)
            self.assertEqual(int(per_step[0].get("retire_crosspost_blocked_edges_total", -1)), 13)
            self.assertEqual(int(per_step[0].get("retire_policy_loss_cycles_total", -1)), 5)
            self.assertEqual(int(per_step[0].get("retire_policy_loss_edges_total", -1)), 11)

            proc_val = self._run_validate(run_dir)
            self.assertEqual(proc_val.returncode, 0, msg=proc_val.stdout + proc_val.stderr)

    def test_p1_summary_exposes_rx_stage_distribution_and_frontend_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "pe_0_memory_controller", "StatisticName": "requests_received_GetS", "Sum.u64": "6", "SimTime": "0"},
                ],
            )
            _write_csv(
                run_dir / "pe_stage_events_db.csv",
                [
                    {"seq": "1", "bg_ns": "100", "ga_ns": "200", "ea_ns": "220", "bs_ns": "240", "es_ns": "260", "gather_ns": "100", "apply_ns": "40", "scatter_ns": "20", "total_ns": "160"},
                    {"seq": "2", "bg_ns": "300", "ga_ns": "360", "ea_ns": "390", "bs_ns": "420", "es_ns": "450", "gather_ns": "60", "apply_ns": "60", "scatter_ns": "30", "total_ns": "150"},
                    {"seq": "3", "bg_ns": "500", "ga_ns": "560", "ea_ns": "590", "bs_ns": "620", "es_ns": "650", "gather_ns": "60", "apply_ns": "60", "scatter_ns": "30", "total_ns": "150"},
                ],
            )
            _write_csv(
                run_dir / "pe_step_perf_db.csv",
                [
                    {
                        "seq": "1",
                        "rx_packets_total": "4",
                        "rx_packets_before_bg_total": "2",
                        "rx_packets_during_gather_total": "1",
                        "rx_packets_during_apply_total": "1",
                        "rx_packets_during_scatter_total": "0",
                        "rx_gate_pending_peak": "2",
                        "frontend_staged_reads": "0",
                        "frontend_staged_line_touches": "0",
                        "frontend_granules_built": "0",
                        "unique_line_count": "0",
                    },
                    {
                        "seq": "2",
                        "rx_packets_total": "6",
                        "rx_packets_before_bg_total": "1",
                        "rx_packets_during_gather_total": "2",
                        "rx_packets_during_apply_total": "2",
                        "rx_packets_during_scatter_total": "1",
                        "rx_gate_pending_peak": "1",
                        "frontend_staged_reads": "20",
                        "frontend_staged_line_touches": "10",
                        "frontend_granules_built": "4",
                        "unique_line_count": "5",
                    },
                    {
                        "seq": "3",
                        "rx_packets_total": "5",
                        "rx_packets_before_bg_total": "1",
                        "rx_packets_during_gather_total": "1",
                        "rx_packets_during_apply_total": "2",
                        "rx_packets_during_scatter_total": "1",
                        "rx_gate_pending_peak": "1",
                        "frontend_staged_reads": "20",
                        "frontend_staged_line_touches": "10",
                        "frontend_granules_built": "4",
                        "unique_line_count": "5",
                    },
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            gas = summary.get("gas") or {}
            snn_rx = summary.get("snn_rx") or {}

            self.assertEqual(int(gas.get("frontend_nonempty_windows_total", -1)), 2, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("frontend_empty_windows_total", -1)), 1, msg=json.dumps(gas, indent=2))
            self.assertAlmostEqual(float(gas.get("frontend_reads_per_nonempty_window_avg", -1.0)), 20.0, places=6, msg=json.dumps(gas, indent=2))
            self.assertAlmostEqual(float(gas.get("frontend_unique_lines_per_nonempty_window_avg", -1.0)), 5.0, places=6, msg=json.dumps(gas, indent=2))
            self.assertAlmostEqual(float(gas.get("frontend_granules_per_nonempty_window_avg", -1.0)), 4.0, places=6, msg=json.dumps(gas, indent=2))
            self.assertAlmostEqual(float(gas.get("frontend_line_touch_reuse_p50", -1.0)), 0.5, places=6, msg=json.dumps(gas, indent=2))
            self.assertAlmostEqual(float(gas.get("frontend_line_touch_reuse_p95", -1.0)), 0.5, places=6, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(snn_rx.get("packets_during_gather_total", -1)), 4, msg=json.dumps(snn_rx, indent=2))
            self.assertEqual(int(snn_rx.get("packets_during_apply_total", -1)), 5, msg=json.dumps(snn_rx, indent=2))
            self.assertEqual(int(snn_rx.get("packets_during_scatter_total", -1)), 2, msg=json.dumps(snn_rx, indent=2))
            self.assertEqual(int(snn_rx.get("gate_pending_peak_max", -1)), 2, msg=json.dumps(snn_rx, indent=2))

    def test_p2_summary_exposes_retire_hol_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "pe_0_memory_controller", "StatisticName": "requests_received_GetS", "Sum.u64": "6", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_ready_but_blocked_edges_total", "Sum.u64": "340", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_samepost_blocked_edges_total", "Sum.u64": "40", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_crosspost_blocked_edges_total", "Sum.u64": "300", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_cycles_total", "Sum.u64": "30", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_edges_total", "Sum.u64": "300", "SimTime": "0"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "pe_stage_events_db.csv",
                [
                    {"seq": "1", "bg_ns": "0", "ga_ns": "10", "ea_ns": "60", "bs_ns": "61", "es_ns": "80", "gather_ns": "10", "apply_ns": "50", "scatter_ns": "19", "total_ns": "80"},
                    {"seq": "2", "bg_ns": "80", "ga_ns": "90", "ea_ns": "150", "bs_ns": "151", "es_ns": "170", "gather_ns": "10", "apply_ns": "60", "scatter_ns": "19", "total_ns": "90"},
                ],
            )
            _write_csv(
                run_dir / "pe01" / "pe_stage_events_db.csv",
                [
                    {"seq": "1", "bg_ns": "0", "ga_ns": "20", "ea_ns": "60", "bs_ns": "61", "es_ns": "70", "gather_ns": "20", "apply_ns": "40", "scatter_ns": "9", "total_ns": "70"},
                    {"seq": "2", "bg_ns": "80", "ga_ns": "100", "ea_ns": "200", "bs_ns": "201", "es_ns": "220", "gather_ns": "20", "apply_ns": "100", "scatter_ns": "19", "total_ns": "140"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "pe_step_perf_db.csv",
                [
                    {
                        "seq": "1",
                        "retire_ready_but_blocked_edges_total": "100",
                        "retire_samepost_blocked_edges_total": "10",
                        "retire_crosspost_blocked_edges_total": "90",
                        "retire_policy_loss_cycles_total": "9",
                        "retire_policy_loss_edges_total": "90",
                        "retire_wait_cycles_due_to_hol_total": "9",
                    },
                    {
                        "seq": "2",
                        "retire_ready_but_blocked_edges_total": "50",
                        "retire_samepost_blocked_edges_total": "10",
                        "retire_crosspost_blocked_edges_total": "40",
                        "retire_policy_loss_cycles_total": "4",
                        "retire_policy_loss_edges_total": "40",
                        "retire_wait_cycles_due_to_hol_total": "4",
                    },
                ],
            )
            _write_csv(
                run_dir / "pe01" / "pe_step_perf_db.csv",
                [
                    {
                        "seq": "1",
                        "retire_ready_but_blocked_edges_total": "30",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "30",
                        "retire_policy_loss_cycles_total": "3",
                        "retire_policy_loss_edges_total": "30",
                        "retire_wait_cycles_due_to_hol_total": "3",
                    },
                    {
                        "seq": "2",
                        "retire_ready_but_blocked_edges_total": "160",
                        "retire_samepost_blocked_edges_total": "20",
                        "retire_crosspost_blocked_edges_total": "140",
                        "retire_policy_loss_cycles_total": "14",
                        "retire_policy_loss_edges_total": "140",
                        "retire_wait_cycles_due_to_hol_total": "14",
                    },
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            attr = summary.get("retire_hol_attribution") or {}

            self.assertTrue(attr, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(attr.get("step_count", -1)), 2, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("window_count", -1)), 4, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("pe_count", -1)), 2, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("crosspost_blocked_edges_total", -1)), 300, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("samepost_blocked_edges_total", -1)), 40, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_steps_by_crosspost_blocked_edges")[0].get("seq", -1)), 2, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_steps_by_crosspost_blocked_edges")[0].get("retire_crosspost_blocked_edges_total", -1)), 180, msg=json.dumps(attr, indent=2))
            self.assertAlmostEqual(float(attr.get("top_steps_by_crosspost_blocked_edges")[0].get("crosspost_share_global", -1.0)), 0.6, places=6, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_windows_by_crosspost_blocked_edges")[0].get("pe", -1)), 1, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_windows_by_crosspost_blocked_edges")[0].get("seq", -1)), 2, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_windows_by_crosspost_blocked_edges")[0].get("retire_crosspost_blocked_edges_total", -1)), 140, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_windows_by_crosspost_blocked_edges")[0].get("apply_ns", -1)), 100, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_pes_by_crosspost_blocked_edges_total")[0].get("pe", -1)), 1, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_pes_by_crosspost_blocked_edges_total")[0].get("retire_crosspost_blocked_edges_total", -1)), 170, msg=json.dumps(attr, indent=2))
            self.assertAlmostEqual(float((attr.get("concentration") or {}).get("top1_step_crosspost_share", -1.0)), 0.6, places=6, msg=json.dumps(attr, indent=2))
            self.assertAlmostEqual(float((attr.get("concentration") or {}).get("top4_windows_crosspost_share", -1.0)), 1.0, places=6, msg=json.dumps(attr, indent=2))
            self.assertAlmostEqual(float((attr.get("concentration") or {}).get("top2_pes_crosspost_share", -1.0)), 1.0, places=6, msg=json.dumps(attr, indent=2))
            self.assertEqual(str((attr.get("shape") or {}).get("temporal_shape")), "single_seq_dominant", msg=json.dumps(attr, indent=2))
            self.assertEqual(str((attr.get("shape") or {}).get("spatial_window_shape")), "localized_windows", msg=json.dumps(attr, indent=2))
            self.assertEqual(str((attr.get("shape") or {}).get("spatial_pe_shape")), "localized_pes", msg=json.dumps(attr, indent=2))
            self.assertEqual(str((attr.get("shape") or {}).get("overall_shape")), "localized_hotspot_dominant", msg=json.dumps(attr, indent=2))

    def test_p3_summary_exposes_core_level_retire_hol_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "pe_0_memory_controller", "StatisticName": "requests_received_GetS", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_ready_but_blocked_edges_total", "Sum.u64": "140", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_samepost_blocked_edges_total", "Sum.u64": "10", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_crosspost_blocked_edges_total", "Sum.u64": "130", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_cycles_total", "Sum.u64": "13", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_edges_total", "Sum.u64": "130", "SimTime": "0"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_stage_events_db.csv",
                [
                    {"seq": "1", "core": "0", "bg_ns": "0", "ga_ns": "10", "ea_ns": "40", "bs_ns": "60", "es_ns": "80", "gather_ns": "10", "apply_ns": "50", "scatter_ns": "20", "total_ns": "80"},
                    {"seq": "2", "core": "0", "bg_ns": "80", "ga_ns": "100", "ea_ns": "140", "bs_ns": "170", "es_ns": "200", "gather_ns": "20", "apply_ns": "70", "scatter_ns": "30", "total_ns": "120"},
                    {"seq": "1", "core": "1", "bg_ns": "0", "ga_ns": "12", "ea_ns": "32", "bs_ns": "42", "es_ns": "60", "gather_ns": "12", "apply_ns": "30", "scatter_ns": "18", "total_ns": "60"},
                    {"seq": "2", "core": "1", "bg_ns": "80", "ga_ns": "95", "ea_ns": "110", "bs_ns": "120", "es_ns": "140", "gather_ns": "15", "apply_ns": "25", "scatter_ns": "20", "total_ns": "60"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_step_perf_db.csv",
                [
                    {
                        "seq": "1",
                        "core": "0",
                        "retire_ready_but_blocked_edges_total": "40",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "40",
                        "retire_policy_loss_cycles_total": "4",
                        "retire_policy_loss_edges_total": "40",
                        "retire_wait_cycles_due_to_hol_total": "4",
                    },
                    {
                        "seq": "2",
                        "core": "0",
                        "retire_ready_but_blocked_edges_total": "110",
                        "retire_samepost_blocked_edges_total": "10",
                        "retire_crosspost_blocked_edges_total": "100",
                        "retire_policy_loss_cycles_total": "10",
                        "retire_policy_loss_edges_total": "100",
                        "retire_wait_cycles_due_to_hol_total": "10",
                    },
                    {
                        "seq": "1",
                        "core": "1",
                        "retire_ready_but_blocked_edges_total": "20",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "20",
                        "retire_policy_loss_cycles_total": "2",
                        "retire_policy_loss_edges_total": "20",
                        "retire_wait_cycles_due_to_hol_total": "2",
                    },
                    {
                        "seq": "2",
                        "core": "1",
                        "retire_ready_but_blocked_edges_total": "30",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "30",
                        "retire_policy_loss_cycles_total": "3",
                        "retire_policy_loss_edges_total": "30",
                        "retire_wait_cycles_due_to_hol_total": "3",
                    },
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            attr = summary.get("retire_hol_attribution_core") or {}

            self.assertTrue(attr, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(attr.get("core_count", -1)), 2, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("core_window_count", -1)), 4, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("crosspost_blocked_edges_total", -1)), 130, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("samepost_blocked_edges_total", -1)), 10, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_cores_by_crosspost_blocked_edges_total")[0].get("core", -1)), 0, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_cores_by_crosspost_blocked_edges_total")[0].get("retire_crosspost_blocked_edges_total", -1)), 100, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_core_windows_by_crosspost_blocked_edges")[0].get("core", -1)), 0, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_core_windows_by_crosspost_blocked_edges")[0].get("seq", -1)), 2, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_core_windows_by_crosspost_blocked_edges")[0].get("retire_crosspost_blocked_edges_total", -1)), 60, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(attr.get("top_core_windows_by_crosspost_blocked_edges")[0].get("apply_ns", -1)), 70, msg=json.dumps(attr, indent=2))
            self.assertAlmostEqual(
                float((attr.get("concentration") or {}).get("top1_core_crosspost_share", -1.0)),
                100.0 / 130.0,
                places=6,
                msg=json.dumps(attr, indent=2),
            )
            self.assertEqual(
                str((attr.get("shape") or {}).get("spatial_core_shape")),
                "localized_cores",
                msg=json.dumps(attr, indent=2),
            )

    def test_p4_core_retire_hol_summary_exposes_head_source_mix(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "pe_0_memory_controller", "StatisticName": "requests_received_GetS", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_ready_but_blocked_edges_total", "Sum.u64": "40", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_samepost_blocked_edges_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_crosspost_blocked_edges_total", "Sum.u64": "40", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_cycles_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_edges_total", "Sum.u64": "40", "SimTime": "0"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_stage_events_db.csv",
                [
                    {"seq": "1", "core": "0", "bg_ns": "0", "ga_ns": "10", "ea_ns": "20", "bs_ns": "30", "es_ns": "40", "gather_ns": "10", "apply_ns": "20", "scatter_ns": "10", "total_ns": "40"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_step_perf_db.csv",
                [
                    {
                        "seq": "1",
                        "core": "0",
                        "retire_ready_but_blocked_edges_total": "40",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "40",
                        "retire_policy_loss_cycles_total": "4",
                        "retire_policy_loss_edges_total": "40",
                        "retire_wait_cycles_due_to_hol_total": "4",
                        "retire_head_hol_cycles_gcss_total": "3",
                        "retire_head_hol_cycles_miss_total": "1",
                        "retire_head_blocked_edges_gcss_total": "30",
                        "retire_head_blocked_edges_miss_total": "10",
                        "retire_gcss_head_queued_not_issued_cycles_total": "1",
                        "retire_gcss_head_queued_not_issued_blocked_edges_total": "10",
                        "retire_gcss_head_issued_wait_resp_cycles_total": "2",
                        "retire_gcss_head_issued_wait_resp_blocked_edges_total": "20",
                        "retire_gcss_resp_ready_but_hol_cycles_total": "3",
                        "retire_gcss_resp_ready_but_hol_blocked_edges_total": "24",
                        "retire_gcss_qni_loader_not_ready_cycles_total": "1",
                        "retire_gcss_qni_loader_not_ready_blocked_edges_total": "10",
                        "retire_gcss_qni_weight_sram_stall_cycles_total": "2",
                        "retire_gcss_qni_weight_sram_stall_blocked_edges_total": "20",
                        "retire_gcss_qni_vlf_younger_ahead_cycles_total": "7",
                        "retire_gcss_qni_vlf_younger_ahead_blocked_edges_total": "70",
                        "retire_gcss_qni_vlf_front_inflight_full_cycles_total": "3",
                        "retire_gcss_qni_vlf_front_inflight_full_blocked_edges_total": "30",
                        "retire_gcss_qni_vlf_front_waiting_issue_cycles_total": "4",
                        "retire_gcss_qni_vlf_front_waiting_issue_blocked_edges_total": "40",
                        "retire_gcss_qni_pending_younger_ahead_cycles_total": "6",
                        "retire_gcss_qni_pending_younger_ahead_blocked_edges_total": "60",
                        "retire_gcss_qni_pending_front_inflight_full_cycles_total": "5",
                        "retire_gcss_qni_pending_front_inflight_full_blocked_edges_total": "50",
                        "retire_gcss_qni_pending_front_waiting_tick_cycles_total": "8",
                        "retire_gcss_qni_pending_front_waiting_tick_blocked_edges_total": "80",
                        "retire_gcss_qni_unknown_cycles_total": "0",
                        "retire_gcss_qni_unknown_blocked_edges_total": "0",
                    },
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            attr = summary.get("retire_hol_attribution_core") or {}
            mix = attr.get("head_source_mix") or {}
            gcss_phase = attr.get("gcss_phase_mix") or {}
            qni_reason = attr.get("gcss_queued_reason_mix") or {}

            self.assertTrue(mix, msg=json.dumps(summary, indent=2))
            self.assertTrue(gcss_phase, msg=json.dumps(summary, indent=2))
            self.assertTrue(qni_reason, msg=json.dumps(summary, indent=2))
            self.assertEqual(int((mix.get("hol_cycles_by_src") or {}).get("gcss", -1)), 3, msg=json.dumps(mix, indent=2))
            self.assertEqual(int((mix.get("hol_cycles_by_src") or {}).get("miss", -1)), 1, msg=json.dumps(mix, indent=2))
            self.assertEqual(int((mix.get("blocked_edges_by_src") or {}).get("gcss", -1)), 30, msg=json.dumps(mix, indent=2))
            self.assertEqual(int((mix.get("blocked_edges_by_src") or {}).get("miss", -1)), 10, msg=json.dumps(mix, indent=2))
            self.assertEqual(str(mix.get("dominant_src_by_hol_cycles")), "gcss", msg=json.dumps(mix, indent=2))
            self.assertEqual(str(mix.get("dominant_src_by_blocked_edges")), "gcss", msg=json.dumps(mix, indent=2))
            self.assertAlmostEqual(float(mix.get("gcss_blocked_edges_share", -1.0)), 0.75, places=6, msg=json.dumps(mix, indent=2))
            self.assertEqual(int((gcss_phase.get("hol_cycles_by_phase") or {}).get("queued_not_issued", -1)), 1, msg=json.dumps(gcss_phase, indent=2))
            self.assertEqual(int((gcss_phase.get("hol_cycles_by_phase") or {}).get("issued_wait_resp", -1)), 2, msg=json.dumps(gcss_phase, indent=2))
            self.assertEqual(int((gcss_phase.get("hol_cycles_by_phase") or {}).get("resp_ready_but_hol", -1)), 3, msg=json.dumps(gcss_phase, indent=2))
            self.assertEqual(int((gcss_phase.get("blocked_edges_by_phase") or {}).get("queued_not_issued", -1)), 10, msg=json.dumps(gcss_phase, indent=2))
            self.assertEqual(int((gcss_phase.get("blocked_edges_by_phase") or {}).get("issued_wait_resp", -1)), 20, msg=json.dumps(gcss_phase, indent=2))
            self.assertEqual(int((gcss_phase.get("blocked_edges_by_phase") or {}).get("resp_ready_but_hol", -1)), 24, msg=json.dumps(gcss_phase, indent=2))
            self.assertEqual(str(gcss_phase.get("dominant_phase_by_hol_cycles")), "resp_ready_but_hol", msg=json.dumps(gcss_phase, indent=2))
            self.assertEqual(str(gcss_phase.get("dominant_phase_by_blocked_edges")), "resp_ready_but_hol", msg=json.dumps(gcss_phase, indent=2))
            self.assertEqual(int((qni_reason.get("hol_cycles_by_reason") or {}).get("loader_not_ready", -1)), 1, msg=json.dumps(qni_reason, indent=2))
            self.assertEqual(int((qni_reason.get("hol_cycles_by_reason") or {}).get("vlf_younger_ahead", -1)), 7, msg=json.dumps(qni_reason, indent=2))
            self.assertEqual(int((qni_reason.get("hol_cycles_by_reason") or {}).get("pending_front_waiting_tick", -1)), 8, msg=json.dumps(qni_reason, indent=2))
            self.assertEqual(int((qni_reason.get("blocked_edges_by_reason") or {}).get("vlf_younger_ahead", -1)), 70, msg=json.dumps(qni_reason, indent=2))
            self.assertEqual(int((qni_reason.get("blocked_edges_by_reason") or {}).get("pending_front_waiting_tick", -1)), 80, msg=json.dumps(qni_reason, indent=2))
            self.assertEqual(str(qni_reason.get("dominant_reason_by_hol_cycles")), "pending_front_waiting_tick", msg=json.dumps(qni_reason, indent=2))
            self.assertEqual(str(qni_reason.get("dominant_reason_by_blocked_edges")), "pending_front_waiting_tick", msg=json.dumps(qni_reason, indent=2))
            self.assertEqual(
                int((attr.get("top_core_windows_by_crosspost_blocked_edges") or [])[0].get("retire_head_blocked_edges_gcss_total", -1)),
                30,
                msg=json.dumps(attr, indent=2),
            )
            self.assertEqual(
                int((attr.get("top_core_windows_by_crosspost_blocked_edges") or [])[0].get("retire_gcss_head_issued_wait_resp_blocked_edges_total", -1)),
                20,
                msg=json.dumps(attr, indent=2),
            )
            self.assertEqual(
                int((attr.get("top_core_windows_by_crosspost_blocked_edges") or [])[0].get("retire_gcss_qni_vlf_younger_ahead_cycles_total", -1)),
                7,
                msg=json.dumps(attr, indent=2),
            )

    def test_p5_core_retire_hol_summary_exposes_shadow_per_post_attribution(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {
                                "pe": 0,
                                "core": 0,
                                "gatherbuf": {
                                    "apply_issue_policy": "order",
                                    "experimental_retire_policy": "global_inorder",
                                    "experimental_retire_shadow_per_post_enable": 1,
                                },
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "pe_0_memory_controller", "StatisticName": "requests_received_GetS", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_ready_but_blocked_edges_total", "Sum.u64": "40", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_samepost_blocked_edges_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_crosspost_blocked_edges_total", "Sum.u64": "36", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_cycles_total", "Sum.u64": "5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_edges_total", "Sum.u64": "17", "SimTime": "0"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_stage_events_db.csv",
                [
                    {"seq": "1", "core": "0", "bg_ns": "0", "ga_ns": "10", "ea_ns": "20", "bs_ns": "30", "es_ns": "40", "gather_ns": "10", "apply_ns": "20", "scatter_ns": "10", "total_ns": "40"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_step_perf_db.csv",
                [
                    {
                        "seq": "1",
                        "core": "0",
                        "retire_ready_but_blocked_edges_total": "40",
                        "retire_samepost_blocked_edges_total": "4",
                        "retire_crosspost_blocked_edges_total": "36",
                        "retire_policy_loss_cycles_total": "5",
                        "retire_policy_loss_edges_total": "17",
                        "retire_wait_cycles_due_to_hol_total": "5",
                        "retire_shadow_per_post_recoverable_cycles_total": "5",
                        "retire_shadow_per_post_recoverable_edges_total": "17",
                        "retire_shadow_per_post_ready_posts_peak": "3",
                        "retire_shadow_per_post_committable_edges_peak": "4",
                    },
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            gas = summary.get("gas") or {}
            contracts = summary.get("contracts") or {}
            attr = summary.get("retire_hol_attribution_core") or {}
            shadow = attr.get("shadow_per_post") or {}
            top_windows = attr.get("top_core_windows_by_crosspost_blocked_edges") or []

            self.assertEqual(int(gas.get("retire_shadow_per_post_recoverable_cycles_total", -1)), 5, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_shadow_per_post_recoverable_edges_total", -1)), 17, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_shadow_per_post_ready_posts_peak_max", -1)), 3, msg=json.dumps(gas, indent=2))
            self.assertEqual(int(gas.get("retire_shadow_per_post_committable_edges_peak_max", -1)), 4, msg=json.dumps(gas, indent=2))
            self.assertIs(contracts.get("experimental_retire_shadow_per_post_enable"), True, msg=json.dumps(contracts, indent=2))
            self.assertEqual(int(shadow.get("recoverable_cycles_total", -1)), 5, msg=json.dumps(shadow, indent=2))
            self.assertEqual(int(shadow.get("recoverable_edges_total", -1)), 17, msg=json.dumps(shadow, indent=2))
            self.assertEqual(int(shadow.get("ready_posts_peak_max", -1)), 3, msg=json.dumps(shadow, indent=2))
            self.assertEqual(int(shadow.get("committable_edges_peak_max", -1)), 4, msg=json.dumps(shadow, indent=2))
            self.assertAlmostEqual(float(shadow.get("recoverable_edges_per_cycle_avg", -1.0)), 17.0 / 5.0, places=6, msg=json.dumps(shadow, indent=2))
            self.assertAlmostEqual(float(shadow.get("recoverable_edges_share_of_policy_loss", -1.0)), 1.0, places=6, msg=json.dumps(shadow, indent=2))
            self.assertEqual(int(top_windows[0].get("retire_shadow_per_post_recoverable_cycles_total", -1)), 5, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(top_windows[0].get("retire_shadow_per_post_recoverable_edges_total", -1)), 17, msg=json.dumps(attr, indent=2))

    def test_p6_core_retire_hol_summary_exposes_frontend_ordering_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "pe_0_memory_controller", "StatisticName": "requests_received_GetS", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_ready_but_blocked_edges_total", "Sum.u64": "40", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_samepost_blocked_edges_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_crosspost_blocked_edges_total", "Sum.u64": "40", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_cycles_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_edges_total", "Sum.u64": "40", "SimTime": "0"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_stage_events_db.csv",
                [
                    {"seq": "1", "core": "0", "bg_ns": "0", "ga_ns": "10", "ea_ns": "30", "bs_ns": "40", "es_ns": "50", "gather_ns": "10", "apply_ns": "30", "scatter_ns": "10", "total_ns": "50"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_step_perf_db.csv",
                [
                    {
                        "seq": "1",
                        "core": "0",
                        "retire_ready_but_blocked_edges_total": "40",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "40",
                        "retire_policy_loss_cycles_total": "4",
                        "retire_policy_loss_edges_total": "40",
                        "retire_wait_cycles_due_to_hol_total": "4",
                        "retire_head_hol_cycles_gcss_total": "4",
                        "retire_head_blocked_edges_gcss_total": "40",
                        "retire_gcss_head_queued_not_issued_cycles_total": "4",
                        "retire_gcss_head_queued_not_issued_blocked_edges_total": "40",
                        "retire_gcss_qni_vlf_younger_ahead_cycles_total": "4",
                        "retire_gcss_qni_vlf_younger_ahead_blocked_edges_total": "40",
                        "retire_gcss_qni_head_wait_episodes_total": "2",
                        "retire_gcss_qni_head_wait_cycles_max": "3",
                        "retire_gcss_qni_vlf_younger_ahead_depth_total": "6",
                        "retire_gcss_qni_vlf_younger_ahead_depth_samples_total": "3",
                        "retire_gcss_qni_vlf_younger_ahead_depth_max": "4",
                        "retire_gcss_qni_issue_deferred_total": "5",
                        "retire_gcss_qni_pending_direct_queue_residency_cycles_total": "8",
                        "retire_gcss_qni_pending_direct_queue_residency_samples_total": "2",
                        "retire_gcss_qni_pending_direct_queue_residency_cycles_max": "6",
                    },
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            attr = summary.get("retire_hol_attribution_core") or {}
            frontend = attr.get("frontend_ordering") or {}
            older = frontend.get("older_head_wait") or {}
            depth = frontend.get("younger_ahead_depth") or {}
            residency = frontend.get("pending_direct_queue_residency") or {}

            self.assertTrue(frontend, msg=json.dumps(attr, indent=2))
            self.assertEqual(int(older.get("hol_cycles_total", -1)), 4, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(older.get("episodes_total", -1)), 2, msg=json.dumps(frontend, indent=2))
            self.assertAlmostEqual(float(older.get("wait_cycles_avg", -1.0)), 2.0, places=6, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(older.get("wait_cycles_max", -1)), 3, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(depth.get("depth_total", -1)), 6, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(depth.get("samples_total", -1)), 3, msg=json.dumps(frontend, indent=2))
            self.assertAlmostEqual(float(depth.get("depth_avg", -1.0)), 2.0, places=6, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(depth.get("depth_max", -1)), 4, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(frontend.get("issue_deferred_total", -1)), 5, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(residency.get("cycles_total", -1)), 8, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(residency.get("samples_total", -1)), 2, msg=json.dumps(frontend, indent=2))
            self.assertAlmostEqual(float(residency.get("cycles_avg", -1.0)), 4.0, places=6, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(residency.get("cycles_max", -1)), 6, msg=json.dumps(frontend, indent=2))
            self.assertEqual(
                int((attr.get("top_core_windows_by_crosspost_blocked_edges") or [])[0].get("retire_gcss_qni_head_wait_episodes_total", -1)),
                2,
                msg=json.dumps(attr, indent=2),
            )
            self.assertEqual(
                int((attr.get("top_core_windows_by_crosspost_blocked_edges") or [])[0].get("retire_gcss_qni_pending_direct_queue_residency_cycles_total", -1)),
                8,
                msg=json.dumps(attr, indent=2),
            )

    def test_p7_core_retire_hol_summary_exposes_queue_shape_issue_gate_and_completion_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "pe_0_memory_controller", "StatisticName": "requests_received_GetS", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_ready_but_blocked_edges_total", "Sum.u64": "40", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_samepost_blocked_edges_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_crosspost_blocked_edges_total", "Sum.u64": "40", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_cycles_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_edges_total", "Sum.u64": "40", "SimTime": "0"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_stage_events_db.csv",
                [
                    {"seq": "1", "core": "0", "bg_ns": "0", "ga_ns": "10", "ea_ns": "30", "bs_ns": "40", "es_ns": "50", "gather_ns": "10", "apply_ns": "30", "scatter_ns": "10", "total_ns": "50"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_step_perf_db.csv",
                [
                    {
                        "seq": "1",
                        "core": "0",
                        "retire_ready_but_blocked_edges_total": "40",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "40",
                        "retire_policy_loss_cycles_total": "4",
                        "retire_policy_loss_edges_total": "40",
                        "retire_wait_cycles_due_to_hol_total": "4",
                        "retire_head_hol_cycles_gcss_total": "4",
                        "retire_head_blocked_edges_gcss_total": "40",
                        "retire_gcss_head_queued_not_issued_cycles_total": "4",
                        "retire_gcss_head_queued_not_issued_blocked_edges_total": "40",
                        "retire_gcss_qni_loader_not_ready_cycles_total": "1",
                        "retire_gcss_qni_vlf_front_inflight_full_cycles_total": "2",
                        "retire_gcss_qni_vlf_front_waiting_issue_cycles_total": "3",
                        "retire_gcss_qni_pending_front_inflight_full_cycles_total": "4",
                        "retire_gcss_qni_pending_front_waiting_tick_cycles_total": "5",
                        "retire_gcss_qni_issue_deferred_total": "5",
                        "retire_begin_apply_windows_total": "1",
                        "retire_begin_apply_prev_edges_total": "16",
                        "retire_begin_apply_outstanding_carryin_total": "6",
                        "retire_begin_apply_outstanding_carryin_windows_total": "1",
                        "retire_begin_apply_loader_not_ready_windows_total": "1",
                        "retire_edge_retire_registered_total": "14",
                        "retire_edge_retire_retired_total": "12",
                        "retire_end_scatter_gcss_vlf_issue_queue_residual_total": "1",
                        "retire_end_scatter_pending_direct_reads_residual_total": "2",
                        "retire_end_scatter_outstanding_residual_total": "3",
                        "retire_end_scatter_residual_work_windows_total": "1",
                        "retire_gcss_vlf_issue_prepare_total": "1",
                        "retire_gcss_vlf_issue_edges_total": "10",
                        "retire_gcss_vlf_issue_reorder_trigger_total": "1",
                        "retire_gcss_vlf_issue_line_groups_total": "4",
                    },
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            attr = summary.get("retire_hol_attribution_core") or {}
            frontend = attr.get("frontend_ordering") or {}
            queue_shape = frontend.get("queue_shape") or {}
            issue_gate = frontend.get("issue_gate") or {}
            completion = frontend.get("completion_state") or {}

            self.assertTrue(queue_shape, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(queue_shape.get("prepare_total", -1)), 1, msg=json.dumps(queue_shape, indent=2))
            self.assertEqual(int(queue_shape.get("queued_edges_total", -1)), 10, msg=json.dumps(queue_shape, indent=2))
            self.assertEqual(int(queue_shape.get("reorder_trigger_total", -1)), 1, msg=json.dumps(queue_shape, indent=2))
            self.assertEqual(int(queue_shape.get("line_groups_total", -1)), 4, msg=json.dumps(queue_shape, indent=2))
            self.assertAlmostEqual(float(queue_shape.get("edges_per_prepare_avg", -1.0)), 10.0, places=6, msg=json.dumps(queue_shape, indent=2))
            self.assertAlmostEqual(float(queue_shape.get("line_groups_per_prepare_avg", -1.0)), 4.0, places=6, msg=json.dumps(queue_shape, indent=2))
            self.assertAlmostEqual(float(queue_shape.get("edges_per_line_group_avg", -1.0)), 2.5, places=6, msg=json.dumps(queue_shape, indent=2))

            self.assertTrue(issue_gate, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(issue_gate.get("loader_not_ready_cycles_total", -1)), 1, msg=json.dumps(issue_gate, indent=2))
            self.assertEqual(int(issue_gate.get("vlf_front_inflight_full_cycles_total", -1)), 2, msg=json.dumps(issue_gate, indent=2))
            self.assertEqual(int(issue_gate.get("vlf_front_waiting_issue_cycles_total", -1)), 3, msg=json.dumps(issue_gate, indent=2))
            self.assertEqual(int(issue_gate.get("pending_front_inflight_full_cycles_total", -1)), 4, msg=json.dumps(issue_gate, indent=2))
            self.assertEqual(int(issue_gate.get("pending_front_waiting_tick_cycles_total", -1)), 5, msg=json.dumps(issue_gate, indent=2))
            self.assertEqual(int(issue_gate.get("inflight_gate_cycles_total", -1)), 6, msg=json.dumps(issue_gate, indent=2))
            self.assertEqual(int(issue_gate.get("front_wait_cycles_total", -1)), 8, msg=json.dumps(issue_gate, indent=2))
            self.assertEqual(int(issue_gate.get("issue_deferred_total", -1)), 5, msg=json.dumps(issue_gate, indent=2))
            self.assertEqual(int(issue_gate.get("begin_apply_outstanding_carryin_total", -1)), 6, msg=json.dumps(issue_gate, indent=2))
            self.assertEqual(int(issue_gate.get("begin_apply_outstanding_carryin_windows_total", -1)), 1, msg=json.dumps(issue_gate, indent=2))
            self.assertAlmostEqual(float(issue_gate.get("begin_apply_outstanding_carryin_avg", -1.0)), 6.0, places=6, msg=json.dumps(issue_gate, indent=2))

            self.assertTrue(completion, msg=json.dumps(frontend, indent=2))
            self.assertEqual(int(completion.get("begin_apply_windows_total", -1)), 1, msg=json.dumps(completion, indent=2))
            self.assertEqual(int(completion.get("begin_apply_prev_edges_total", -1)), 16, msg=json.dumps(completion, indent=2))
            self.assertEqual(int(completion.get("begin_apply_loader_not_ready_windows_total", -1)), 1, msg=json.dumps(completion, indent=2))
            self.assertEqual(int(completion.get("materialized_edges_total", -1)), 14, msg=json.dumps(completion, indent=2))
            self.assertEqual(int(completion.get("retired_edges_total", -1)), 12, msg=json.dumps(completion, indent=2))
            self.assertEqual(int(completion.get("unretired_edges_total", -1)), 2, msg=json.dumps(completion, indent=2))
            self.assertEqual(int(completion.get("residual_issue_queue_total", -1)), 1, msg=json.dumps(completion, indent=2))
            self.assertEqual(int(completion.get("residual_pending_direct_reads_total", -1)), 2, msg=json.dumps(completion, indent=2))
            self.assertEqual(int(completion.get("residual_outstanding_total", -1)), 3, msg=json.dumps(completion, indent=2))
            self.assertEqual(int(completion.get("residual_work_windows_total", -1)), 1, msg=json.dumps(completion, indent=2))
            self.assertAlmostEqual(float(completion.get("materialization_ratio", -1.0)), 14.0 / 16.0, places=6, msg=json.dumps(completion, indent=2))
            self.assertAlmostEqual(float(completion.get("retire_drain_ratio", -1.0)), 12.0 / 14.0, places=6, msg=json.dumps(completion, indent=2))

    def test_p8_core_retire_hol_summary_exposes_tail_distribution_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "pe_0_memory_controller", "StatisticName": "requests_received_GetS", "Sum.u64": "8", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_ready_but_blocked_edges_total", "Sum.u64": "160", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_samepost_blocked_edges_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_crosspost_blocked_edges_total", "Sum.u64": "160", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_cycles_total", "Sum.u64": "16", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "gas_retire_policy_loss_edges_total", "Sum.u64": "160", "SimTime": "0"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_stage_events_db.csv",
                [
                    {"seq": "1", "core": "0", "bg_ns": "0", "ga_ns": "10", "ea_ns": "30", "bs_ns": "40", "es_ns": "50", "gather_ns": "10", "apply_ns": "30", "scatter_ns": "10", "total_ns": "50"},
                    {"seq": "2", "core": "0", "bg_ns": "0", "ga_ns": "10", "ea_ns": "30", "bs_ns": "40", "es_ns": "50", "gather_ns": "10", "apply_ns": "30", "scatter_ns": "10", "total_ns": "50"},
                    {"seq": "3", "core": "0", "bg_ns": "0", "ga_ns": "10", "ea_ns": "30", "bs_ns": "40", "es_ns": "50", "gather_ns": "10", "apply_ns": "30", "scatter_ns": "10", "total_ns": "50"},
                    {"seq": "4", "core": "0", "bg_ns": "0", "ga_ns": "10", "ea_ns": "30", "bs_ns": "40", "es_ns": "50", "gather_ns": "10", "apply_ns": "30", "scatter_ns": "10", "total_ns": "50"},
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core_step_perf_db.csv",
                [
                    {
                        "seq": "1",
                        "core": "0",
                        "retire_ready_but_blocked_edges_total": "40",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "40",
                        "retire_policy_loss_cycles_total": "4",
                        "retire_policy_loss_edges_total": "40",
                        "retire_wait_cycles_due_to_hol_total": "10",
                        "retire_head_hol_cycles_gcss_total": "10",
                        "retire_head_blocked_edges_gcss_total": "40",
                        "retire_gcss_head_queued_not_issued_cycles_total": "10",
                        "retire_gcss_head_queued_not_issued_blocked_edges_total": "40",
                        "retire_gcss_qni_vlf_younger_ahead_cycles_total": "10",
                        "retire_gcss_qni_vlf_younger_ahead_blocked_edges_total": "40",
                        "retire_gcss_qni_head_wait_episodes_total": "1",
                        "retire_gcss_qni_head_wait_cycles_max": "10",
                        "retire_gcss_qni_vlf_younger_ahead_depth_total": "2",
                        "retire_gcss_qni_vlf_younger_ahead_depth_samples_total": "1",
                        "retire_gcss_qni_vlf_younger_ahead_depth_max": "3",
                        "retire_gcss_vlf_issue_prepare_total": "1",
                        "retire_gcss_vlf_issue_edges_total": "6",
                        "retire_gcss_vlf_issue_line_groups_total": "2",
                    },
                    {
                        "seq": "2",
                        "core": "0",
                        "retire_ready_but_blocked_edges_total": "40",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "40",
                        "retire_policy_loss_cycles_total": "4",
                        "retire_policy_loss_edges_total": "40",
                        "retire_wait_cycles_due_to_hol_total": "24",
                        "retire_head_hol_cycles_gcss_total": "24",
                        "retire_head_blocked_edges_gcss_total": "40",
                        "retire_gcss_head_queued_not_issued_cycles_total": "24",
                        "retire_gcss_head_queued_not_issued_blocked_edges_total": "40",
                        "retire_gcss_qni_vlf_younger_ahead_cycles_total": "24",
                        "retire_gcss_qni_vlf_younger_ahead_blocked_edges_total": "40",
                        "retire_gcss_qni_head_wait_episodes_total": "2",
                        "retire_gcss_qni_head_wait_cycles_max": "20",
                        "retire_gcss_qni_vlf_younger_ahead_depth_total": "8",
                        "retire_gcss_qni_vlf_younger_ahead_depth_samples_total": "2",
                        "retire_gcss_qni_vlf_younger_ahead_depth_max": "5",
                        "retire_gcss_vlf_issue_prepare_total": "1",
                        "retire_gcss_vlf_issue_edges_total": "16",
                        "retire_gcss_vlf_issue_line_groups_total": "4",
                    },
                    {
                        "seq": "3",
                        "core": "0",
                        "retire_ready_but_blocked_edges_total": "40",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "40",
                        "retire_policy_loss_cycles_total": "4",
                        "retire_policy_loss_edges_total": "40",
                        "retire_wait_cycles_due_to_hol_total": "42",
                        "retire_head_hol_cycles_gcss_total": "42",
                        "retire_head_blocked_edges_gcss_total": "40",
                        "retire_gcss_head_queued_not_issued_cycles_total": "42",
                        "retire_gcss_head_queued_not_issued_blocked_edges_total": "40",
                        "retire_gcss_qni_vlf_younger_ahead_cycles_total": "42",
                        "retire_gcss_qni_vlf_younger_ahead_blocked_edges_total": "40",
                        "retire_gcss_qni_head_wait_episodes_total": "3",
                        "retire_gcss_qni_head_wait_cycles_max": "30",
                        "retire_gcss_qni_vlf_younger_ahead_depth_total": "18",
                        "retire_gcss_qni_vlf_younger_ahead_depth_samples_total": "3",
                        "retire_gcss_qni_vlf_younger_ahead_depth_max": "7",
                        "retire_gcss_vlf_issue_prepare_total": "1",
                        "retire_gcss_vlf_issue_edges_total": "30",
                        "retire_gcss_vlf_issue_line_groups_total": "6",
                    },
                    {
                        "seq": "4",
                        "core": "0",
                        "retire_ready_but_blocked_edges_total": "40",
                        "retire_samepost_blocked_edges_total": "0",
                        "retire_crosspost_blocked_edges_total": "40",
                        "retire_policy_loss_cycles_total": "4",
                        "retire_policy_loss_edges_total": "40",
                        "retire_wait_cycles_due_to_hol_total": "64",
                        "retire_head_hol_cycles_gcss_total": "64",
                        "retire_head_blocked_edges_gcss_total": "40",
                        "retire_gcss_head_queued_not_issued_cycles_total": "64",
                        "retire_gcss_head_queued_not_issued_blocked_edges_total": "40",
                        "retire_gcss_qni_vlf_younger_ahead_cycles_total": "64",
                        "retire_gcss_qni_vlf_younger_ahead_blocked_edges_total": "40",
                        "retire_gcss_qni_head_wait_episodes_total": "4",
                        "retire_gcss_qni_head_wait_cycles_max": "40",
                        "retire_gcss_qni_vlf_younger_ahead_depth_total": "32",
                        "retire_gcss_qni_vlf_younger_ahead_depth_samples_total": "4",
                        "retire_gcss_qni_vlf_younger_ahead_depth_max": "9",
                        "retire_gcss_vlf_issue_prepare_total": "1",
                        "retire_gcss_vlf_issue_edges_total": "48",
                        "retire_gcss_vlf_issue_line_groups_total": "8",
                    },
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            attr = summary.get("retire_hol_attribution_core") or {}
            frontend = attr.get("frontend_ordering") or {}
            older = frontend.get("older_head_wait") or {}
            depth = frontend.get("younger_ahead_depth") or {}
            queue_shape = frontend.get("queue_shape") or {}

            self.assertEqual(int(older.get("windows_with_episodes_total", -1)), 4, msg=json.dumps(frontend, indent=2))
            self.assertAlmostEqual(float(older.get("window_episodes_p50", -1.0)), 2.5, places=6, msg=json.dumps(older, indent=2))
            self.assertAlmostEqual(float(older.get("window_episodes_p95", -1.0)), 3.85, places=6, msg=json.dumps(older, indent=2))
            self.assertAlmostEqual(float(older.get("window_wait_cycles_avg_p50", -1.0)), 13.0, places=6, msg=json.dumps(older, indent=2))
            self.assertAlmostEqual(float(older.get("window_wait_cycles_avg_p95", -1.0)), 15.7, places=6, msg=json.dumps(older, indent=2))
            self.assertAlmostEqual(float(older.get("window_wait_cycles_max_p99", -1.0)), 39.7, places=6, msg=json.dumps(older, indent=2))
            self.assertEqual(int(older.get("window_wait_cycles_max_max", -1)), 40, msg=json.dumps(older, indent=2))

            self.assertEqual(int(depth.get("windows_with_samples_total", -1)), 4, msg=json.dumps(frontend, indent=2))
            self.assertAlmostEqual(float(depth.get("window_depth_avg_p50", -1.0)), 5.0, places=6, msg=json.dumps(depth, indent=2))
            self.assertAlmostEqual(float(depth.get("window_depth_avg_p95", -1.0)), 7.7, places=6, msg=json.dumps(depth, indent=2))
            self.assertAlmostEqual(float(depth.get("window_depth_max_p99", -1.0)), 8.94, places=6, msg=json.dumps(depth, indent=2))
            self.assertEqual(int(depth.get("window_depth_max_max", -1)), 9, msg=json.dumps(depth, indent=2))

            self.assertEqual(int(queue_shape.get("windows_with_prepare_total", -1)), 4, msg=json.dumps(queue_shape, indent=2))
            self.assertAlmostEqual(float(queue_shape.get("window_line_groups_per_prepare_p50", -1.0)), 5.0, places=6, msg=json.dumps(queue_shape, indent=2))
            self.assertAlmostEqual(float(queue_shape.get("window_line_groups_per_prepare_p95", -1.0)), 7.7, places=6, msg=json.dumps(queue_shape, indent=2))
            self.assertAlmostEqual(float(queue_shape.get("window_edges_per_line_group_p50", -1.0)), 4.5, places=6, msg=json.dumps(queue_shape, indent=2))
            self.assertAlmostEqual(float(queue_shape.get("window_edges_per_line_group_p99", -1.0)), 5.97, places=6, msg=json.dumps(queue_shape, indent=2))
            self.assertEqual(int(queue_shape.get("window_edges_per_line_group_max", -1)), 6, msg=json.dumps(queue_shape, indent=2))

    def test_noc_mem_joint_idx2_summary_exposes_usefulness_and_pressure_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "pe_0_memory_controller", "StatisticName": "requests_received_GetS", "Sum.u64": "10", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_touch_events_total", "Sum.u64": "10", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_lookup_miss_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_enqueued_total", "Sum.u64": "6", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_dedup_pending_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_dedup_inflight_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_dedup_cache_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_prefetch_issued_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_prefetch_bytes_total", "Sum.u64": "16", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_prefetch_deferred_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_prefetch_failed_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_prefetch_resp_ok_total", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_prefetch_resp_short_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_prefetch_resp_drop_tail_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_prefetch_complete_inflight_miss_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_prefetch_complete_zero_waiters_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_prefetch_complete_waiters_total", "Sum.u64": "5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_owner_useful_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_owner_dead_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_owner_join_before_ready_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_owner_ready_before_demand_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_demand_hit_total", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_demand_join_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_demand_join_cb_nonnull_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_demand_join_cb_null_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_demand_fallback_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_waiters_served_total", "Sum.u64": "5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_cache_fill_total", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_cache_evict_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_cache_entries_final", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_budget_ticks_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_budget_effective_total", "Sum.u64": "7", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "exp_noc_idx2_ingress_budget_adapt_ticks_total", "Sum.u64": "2", "SimTime": "0"},
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            joint = summary.get("noc_mem_joint") or {}

            self.assertEqual(int(joint.get("idx2_prefetch_resp_ok_total", -1)), 3, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_prefetch_resp_short_total", -1)), 1, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_prefetch_resp_drop_tail_total", -1)), 1, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_prefetch_complete_inflight_miss_total", -1)), 1, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_prefetch_complete_zero_waiters_total", -1)), 1, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_prefetch_complete_waiters_total", -1)), 5, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_owner_useful_total", -1)), 2, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_owner_dead_total", -1)), 1, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_owner_total", -1)), 3, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_owner_join_before_ready_total", -1)), 1, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_owner_ready_before_demand_total", -1)), 2, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_demand_join_cb_nonnull_total", -1)), 2, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_demand_join_cb_null_total", -1)), 0, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_demand_join_before_ready_total", -1)), 2, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_demand_ready_before_demand_total", -1)), 3, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_budget_ticks_total", -1)), 4, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_budget_effective_total", -1)), 7, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_budget_adapt_ticks_total", -1)), 2, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_prefetch_resp_ok_ratio", -1.0)), 3.0 / 4.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_prefetch_tail_drop_ratio", -1.0)), 1.0 / 3.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_owner_useful_ratio", -1.0)), 2.0 / 3.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_owner_dead_ratio", -1.0)), 1.0 / 3.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_owner_join_before_ready_ratio", -1.0)), 1.0 / 3.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_owner_ready_before_demand_ratio", -1.0)), 2.0 / 3.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_demand_join_cb_nonnull_ratio", -1.0)), 1.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_demand_join_before_ready_ratio", -1.0)), 2.0 / 5.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_demand_ready_before_demand_ratio", -1.0)), 3.0 / 5.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_waiters_per_join_cb_avg", -1.0)), 2.5, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_budget_effective_per_tick", -1.0)), 7.0 / 4.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_budget_adapt_tick_rate", -1.0)), 0.5, places=6, msg=json.dumps(joint, indent=2))

    def test_noc_mem_joint_idx2_log_fallback_parses_owner_usefulness_shape(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "meta.json").write_text(json.dumps({"exec_mode": "gas"}), encoding="utf-8")
            (run_dir / "mesh_run.log").write_text(
                "\n".join(
                    [
                        "SnnPESubComponent[finish:2483]: [exp-idx2-prefetch] core=0 touch_events=12 lookup_miss=1 "
                        "enqueued=8 dedup_pending=2 dedup_inflight=1 dedup_cache=1 prefetch_issued=6 prefetch_bytes=24 "
                        "prefetch_deferred=1 prefetch_failed=0 prefetch_resp_ok=6 prefetch_resp_short=0 "
                        "prefetch_resp_drop_tail=2 prefetch_inflight_miss=0 prefetch_zero_waiters=2 prefetch_waiters_total=3 "
                        "owner_useful=3 owner_dead=1 owner_join_before_ready=1 owner_ready_before_demand=3 "
                        "demand_hit=5 demand_join=3 demand_join_cb_nonnull=3 demand_join_cb_null=0 demand_fallback=0 "
                        "waiters_served=3 cache_fill=4 cache_evict=1 cache_entries=3 budget_ticks=2 budget_eff=6 budget_adapt_ticks=1",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            joint = summary.get("noc_mem_joint") or {}

            self.assertEqual(int(joint.get("idx2_owner_useful_total", -1)), 3, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_owner_dead_total", -1)), 1, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_owner_total", -1)), 4, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_owner_join_before_ready_total", -1)), 1, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_owner_ready_before_demand_total", -1)), 3, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_demand_join_before_ready_total", -1)), 3, msg=json.dumps(joint, indent=2))
            self.assertEqual(int(joint.get("idx2_demand_ready_before_demand_total", -1)), 5, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_owner_useful_ratio", -1.0)), 3.0 / 4.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_owner_dead_ratio", -1.0)), 1.0 / 4.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_demand_join_before_ready_ratio", -1.0)), 3.0 / 8.0, places=6, msg=json.dumps(joint, indent=2))
            self.assertAlmostEqual(float(joint.get("idx2_demand_ready_before_demand_ratio", -1.0)), 5.0 / 8.0, places=6, msg=json.dumps(joint, indent=2))


    def test_model_and_contract_exports_include_mesh_and_phase_breakdown(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            meta = {
                "exec_mode": "gas",
                "workload_impl": "snn_example",
                "mesh_size": 4,
                "num_pes": 16,
                "line_size_bytes": 64,
            }
            effective = {
                "exec_mode": "gas",
                "workload_impl": "snn_example",
                "line_size_bytes": 64,
                "per_core": [
                    {"gatherbuf": {"apply_issue_policy": "order", "experimental_gcss_phase_breakdown_enable": 1}},
                ],
            }
            (run_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
            (run_dir / "effective_config.json").write_text(json.dumps(effective), encoding="utf-8")

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            model = summary.get("model") or {}
            contracts = summary.get("contracts") or {}

            self.assertEqual(int(model.get("mesh_size", -1)), 4, msg=json.dumps(model, indent=2))
            self.assertEqual(int(model.get("num_pes", -1)), 16, msg=json.dumps(model, indent=2))
            self.assertEqual(int(model.get("line_size_bytes", -1)), 64, msg=json.dumps(model, indent=2))
            self.assertEqual(model.get("workload_impl"), "snn_example", msg=json.dumps(model, indent=2))
            self.assertEqual(model.get("exec_mode"), "gas", msg=json.dumps(model, indent=2))
            self.assertTrue(contracts.get("experimental_gcss_phase_breakdown_enable"), msg=json.dumps(contracts, indent=2))


if __name__ == "__main__":
    unittest.main()
