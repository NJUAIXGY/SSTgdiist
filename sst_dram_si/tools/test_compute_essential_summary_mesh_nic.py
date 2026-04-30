#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI-level regression tests for compute_essential_summary_mesh.py NIC/STORM aggregation.
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
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class ComputeEssentialSummaryMeshNicCLITest(unittest.TestCase):
    def _run_compute(self, run_dir: Path) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("compute_essential_summary_mesh.py")
        cmd = ["python3", str(script), "--run-dir", str(run_dir)]
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_nic_spikes_and_packets_are_aggregated_separately(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            stats_path = run_dir / "mesh_stats.csv"
            _write_csv(
                stats_path,
                [
                    {"ComponentName": "multicore_pe_0:network_interface", "StatisticName": "spikes_sent", "Sum.u64": "10", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0:network_interface", "StatisticName": "packets_sent", "Sum.u64": "10", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0:network_interface", "StatisticName": "spikes_received", "Sum.u64": "7", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0:network_interface", "StatisticName": "packets_received", "Sum.u64": "7", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1:network_interface", "StatisticName": "spikes_sent", "Sum.u64": "20", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1:network_interface", "StatisticName": "packets_sent", "Sum.u64": "20", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1:network_interface", "StatisticName": "spikes_received", "Sum.u64": "11", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1:network_interface", "StatisticName": "packets_received", "Sum.u64": "11", "SimTime": "0"},
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            nic = summary.get("nic") or {}
            self.assertEqual(int(nic.get("spikes_sent", -1)), 30, msg=json.dumps(nic, indent=2))
            self.assertEqual(int(nic.get("packets_sent", -1)), 30, msg=json.dumps(nic, indent=2))
            self.assertEqual(int(nic.get("spikes_recv", -1)), 18, msg=json.dumps(nic, indent=2))
            self.assertEqual(int(nic.get("packets_recv", -1)), 18, msg=json.dumps(nic, indent=2))

    def test_storm_cohort_counters_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            stats_path = run_dir / "mesh_stats.csv"
            _write_csv(
                stats_path,
                [
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_tx_spikekey_packets_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_tx_cohort_packets_total", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_tx_cohort_pres_total", "Sum.u64": "9", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_tx_cohort_bandcolor_switch_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "snn_tx_spiketilekey_packets_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "snn_tx_cohort_packets_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "snn_tx_cohort_pres_total", "Sum.u64": "5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "snn_tx_cohort_bandcolor_switch_total", "Sum.u64": "1", "SimTime": "0"},
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            storm = summary.get("storm") or {}
            self.assertEqual(int(storm.get("cohort_packets_total", -1)), 5, msg=json.dumps(storm, indent=2))
            self.assertEqual(int(storm.get("cohort_pres_total", -1)), 14, msg=json.dumps(storm, indent=2))
            self.assertEqual(int(storm.get("cohort_bandcolor_switch_total", -1)), 5, msg=json.dumps(storm, indent=2))
            self.assertAlmostEqual(float(storm.get("avg_pres_per_cohort_pkt", -1.0)), 14.0 / 5.0, places=6, msg=json.dumps(storm, indent=2))

    def test_transport_packet_counters_are_exported_to_snn_tx_and_snn_rx_sections(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            stats_path = run_dir / "mesh_stats.csv"
            _write_csv(
                stats_path,
                [
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_tx_spike_packets_total", "Sum.u64": "11", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_tx_spikekey_packets_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "snn_tx_spiketilekey_packets_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_spike_packets_total", "Sum.u64": "7", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_spikekey_total", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_spiketilekey_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_fastpath_packets_total", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_fallback_packets_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "snn_rx_decode_fail_total", "Sum.u64": "2", "SimTime": "0"},
                ],
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            snn_tx = summary.get("snn_tx") or {}
            snn_rx = summary.get("snn_rx") or {}

            self.assertEqual(int(snn_tx.get("spike_packets_total", -1)), 11, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(snn_tx.get("spikekey_packets_total", -1)), 2, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(snn_tx.get("spiketilekey_packets_total", -1)), 1, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(snn_rx.get("spike_packets_total", -1)), 7, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(snn_rx.get("spikekey_packets_total", -1)), 3, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(snn_rx.get("spiketilekey_packets_total", -1)), 1, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(snn_rx.get("fastpath_packets_total", -1)), 3, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(snn_rx.get("fallback_packets_total", -1)), 4, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(snn_rx.get("decode_fail_total", -1)), 2, msg=json.dumps(summary, indent=2))

    def test_atlas_activation_census_exports_machine_chain_for_requested_effective_constructed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            stats_path = run_dir / "mesh_stats.csv"
            _write_csv(
                stats_path,
                [
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_workload_pure_snn_datapath_eligible", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_local_storage_enable", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_pulse_requested", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_pulse_effective", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_pulse_fabric_constructed", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_pulse_osa_requested", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_pulse_osa_effective", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_shared_weight_owner_requested", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_shared_weight_owner_effective", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_shared_weight_actual_owner_requested", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_shared_weight_actual_owner_effective", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_shared_weight_plane_constructed", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_pe_internal_pod_requested", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_enable_state_local_storage_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_enable_state_pe_internal_pod_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_enable_state_pulse_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_enable_state_pulse_osa_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_enable_state_pulse_osa_shared_weight_owner_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_enable_state_pulse_osa_shared_weight_actual_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_control_runtime_state_fabric_absent_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_shared_weight_census_state_absent_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_shared_weight_census_absent_reason_local_storage_gate_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_workload_pure_snn_datapath_eligible", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_local_storage_enable", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_pulse_requested", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_pulse_effective", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_pulse_fabric_constructed", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_pulse_osa_requested", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_pulse_osa_effective", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_shared_weight_owner_requested", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_shared_weight_owner_effective", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_shared_weight_actual_owner_requested", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_shared_weight_actual_owner_effective", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_shared_weight_plane_constructed", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_activation_gate_pe_internal_pod_requested", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_enable_state_local_storage_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_enable_state_pe_internal_pod_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_enable_state_pulse_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_enable_state_pulse_osa_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_enable_state_pulse_osa_shared_weight_owner_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_enable_state_pulse_osa_shared_weight_actual_effective_total", "Sum.u64": "0", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_control_runtime_state_fabric_absent_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_shared_weight_census_state_absent_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_1", "StatisticName": "atlas_shared_weight_census_absent_reason_local_storage_gate_total", "Sum.u64": "1", "SimTime": "0"},
                ],
            )
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "local_storage_enable": 0,
                        "pe_internal_pod_enable": 0,
                        "pulse": {
                            "enable": 0,
                            "osa_enable": 0,
                            "osa_shared_weight_owner_enable": 0,
                            "osa_shared_weight_owner_actual_enable": 0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            census = summary.get("atlas_activation_census") or {}
            chain = census.get("machine_chain") or {}
            surface_state = chain.get("surface_state") or {}
            mismatch = summary.get("atlas_contract_mismatch") or {}
            self.assertTrue(chain, msg=json.dumps(summary, indent=2))
            self.assertTrue(mismatch, msg=json.dumps(summary, indent=2))
            self.assertTrue(surface_state, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(chain["build_effective"]["local_storage"]), 0, msg=json.dumps(census, indent=2))
            self.assertEqual(int(chain["build_effective"]["pulse"]), 0, msg=json.dumps(census, indent=2))
            self.assertEqual(int(chain["build_effective"]["pulse_osa"]), 0, msg=json.dumps(census, indent=2))
            self.assertEqual(int(chain["build_effective"]["shared_weight_owner"]), 0, msg=json.dumps(census, indent=2))
            self.assertEqual(int(chain["runtime_requested"]["pulse"]["total"]), 0, msg=json.dumps(census, indent=2))
            self.assertEqual(int(chain["runtime_effective"]["local_storage"]["total"]), 0, msg=json.dumps(census, indent=2))
            self.assertEqual(int(chain["runtime_constructed"]["pulse_fabric"]["total"]), 0, msg=json.dumps(census, indent=2))
            self.assertEqual(int(chain["runtime_constructed"]["shared_weight_plane"]["total"]), 0, msg=json.dumps(census, indent=2))
            self.assertEqual(str(chain["dominant_break"]["label"]), "local_storage", msg=json.dumps(census, indent=2))
            self.assertEqual(str(chain["dominant_break"]["stage"]), "build_effective", msg=json.dumps(census, indent=2))
            self.assertIn("local_storage_gate", str(chain["dominant_break"]["reason"]), msg=json.dumps(census, indent=2))
            self.assertEqual(str(surface_state["vocabulary"]), "atlas_contract_mismatch_v1", msg=json.dumps(census, indent=2))
            self.assertEqual(str(surface_state["surfaces"]["local_storage"]["machine_state"]), "build_off", msg=json.dumps(census, indent=2))
            self.assertEqual(str(surface_state["surfaces"]["shared_weight_authority"]["machine_state"]), "gated_by_local_storage", msg=json.dumps(census, indent=2))
            self.assertEqual(str(surface_state["surfaces"]["control_runtime"]["machine_state"]), "fabric_absent", msg=json.dumps(census, indent=2))
            self.assertEqual(str(mismatch["dominant"]["label"]), "local_storage", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(mismatch["phase"]["local_storage"]["state"]), "build_off", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(mismatch["phase"]["pulse"]["state"]), "build_off", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(mismatch["phase"]["pulse_osa"]["state"]), "build_off", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(mismatch["phase"]["shared_weight_owner"]["state"]), "build_off", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(mismatch["phase"]["pod_service"]["state"]), "build_off", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(mismatch["storage_authority"]["shared_weight"]["state"]), "gated_by_local_storage", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(mismatch["control_runtime"]["state"]), "fabric_absent", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(mismatch["sync"]["state"]), "clean", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(census["shared_weight"]["dominant_absent_reason"]["label"]), "local_storage_gate", msg=json.dumps(census, indent=2))

    def test_atlas_machine_chain_prefers_pe_overrides_over_zero_toplevel_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_workload_pure_snn_datapath_eligible", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_enable_state_local_storage_effective_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_pe_internal_pod_requested", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_enable_state_pe_internal_pod_effective_total", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_pod_metadata_plane_constructed", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_pod_owner_table_constructed", "Sum.u64": "1", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_activation_gate_service_table_constructed", "Sum.u64": "1", "SimTime": "0"},
                ],
            )
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "workload_impl": "snn",
                        "local_storage_enable": 0,
                        "pe_internal_pod_enable": 0,
                        "pe_internal_pod_metadata_enable": 0,
                        "pe_internal_pod_owner_enable": 0,
                        "pulse": {
                            "enable": 0,
                            "osa_enable": 0,
                        },
                        "overrides": [
                            {
                                "match": {"role": "pe"},
                                "params": {
                                    "local_storage_enable": 1,
                                    "pe_internal_pod_enable": 1,
                                    "pe_internal_pod_metadata_enable": 1,
                                    "pe_internal_pod_owner_enable": 1,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            census = summary.get("atlas_activation_census") or {}
            chain = census.get("machine_chain") or {}
            mismatch = summary.get("atlas_contract_mismatch") or {}
            resolution = summary.get("atlas_config_resolution") or {}
            self.assertEqual(int(chain["build_effective"]["local_storage"]), 1, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(chain["build_effective"]["pe_internal_pod"]), 1, msg=json.dumps(summary, indent=2))
            self.assertEqual(str(mismatch["phase"]["local_storage"]["state"]), "aligned_active", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(mismatch["phase"]["pod_service"]["state"]), "aligned_active", msg=json.dumps(summary, indent=2))
            self.assertEqual(int(resolution["local_storage"]["top_level"]), 0, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(resolution["local_storage"]["override"]), 1, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(resolution["local_storage"]["resolved"]), 1, msg=json.dumps(summary, indent=2))
            self.assertIs(resolution["local_storage"]["conflict"], True, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(resolution["pe_internal_pod"]["top_level"]), 0, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(resolution["pe_internal_pod"]["override"]), 1, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(resolution["pe_internal_pod"]["resolved"]), 1, msg=json.dumps(summary, indent=2))

    def test_atlas_surface_ledger_unifies_resolution_chain_contract_and_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_census_rowindex_service_events_total", "Sum.u64": "6", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_pod_metadata_observe_total", "Sum.u64": "5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_pod_metadata_unique_object_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_pod_owner_owner_alloc_total", "Sum.u64": "3", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_pod_owner_join_grant_total", "Sum.u64": "2", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_pod_owner_rowindex_join_request_total", "Sum.u64": "7", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_service_atlas_obj_materialize_total", "Sum.u64": "8", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_service_atlas_obj_owner_form_total", "Sum.u64": "4", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_service_atlas_obj_ready_total", "Sum.u64": "5", "SimTime": "0"},
                    {"ComponentName": "multicore_pe_0", "StatisticName": "atlas_service_atlas_obj_release_total", "Sum.u64": "3", "SimTime": "0"},
                ],
            )
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "workload_impl": "snn",
                        "local_storage_enable": 0,
                        "pe_internal_pod_enable": 0,
                        "pe_internal_pod_metadata_enable": 0,
                        "pe_internal_pod_owner_enable": 0,
                        "pulse": {
                            "enable": 0,
                            "observe_only": 1,
                            "osa_enable": 0,
                        },
                        "overrides": [
                            {
                                "match": {"role": "pe"},
                                "params": {
                                    "local_storage_enable": 1,
                                    "pe_internal_pod_enable": 1,
                                    "pe_internal_pod_metadata_enable": 1,
                                    "pe_internal_pod_owner_enable": 1,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            proc = self._run_compute(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
            ledger = (summary.get("atlas_surface_ledger") or {}).get("entries") or {}
            self.assertEqual(str(summary["atlas_surface_ledger"]["vocabulary"]), "atlas_surface_ledger_v1", msg=json.dumps(summary, indent=2))
            self.assertIs(ledger["local_storage"]["resolution"]["conflict"], True, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(ledger["local_storage"]["resolution"]["resolved"]), 1, msg=json.dumps(summary, indent=2))
            self.assertEqual(str(ledger["local_storage"]["surface_state"]["machine_state"]), "configured_not_effective", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(ledger["local_storage"]["contract"]["phase"]["state"]), "configured_not_effective", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(ledger["local_storage"]["visibility"]["gap_state"]), "build_on_object_visible_runtime_dark", msg=json.dumps(summary, indent=2))
            self.assertEqual(int(ledger["pod_service"]["chain"]["build_effective"]), 1, msg=json.dumps(summary, indent=2))
            self.assertEqual(int(ledger["pod_service"]["chain"]["runtime_requested_total"]), 0, msg=json.dumps(summary, indent=2))
            self.assertEqual(str(ledger["pod_service"]["contract"]["phase"]["state"]), "runtime_not_requested", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(ledger["pod_service"]["visibility"]["gap_state"]), "build_on_object_visible_runtime_dark", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(ledger["rowindex_object"]["visibility"]["objects"]["states"]["rowindex"]), "shadow-only", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(ledger["shared_weight"]["contract"]["phase"]["state"]), "build_off", msg=json.dumps(summary, indent=2))
            self.assertEqual(str(ledger["shared_weight"]["visibility"]["gap_state"]), "build_off_both_planes_dark", msg=json.dumps(summary, indent=2))

if __name__ == "__main__":
    unittest.main()
