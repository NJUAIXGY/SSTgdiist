#!/usr/bin/env python3

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sst_dram_si.tools import summarize_atlas_activation_trace as saat


_CSV_HEADER = (
    "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,"
    "Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64"
)


def _write_run_artifacts(
    run_dir: Path,
    *,
    effective_config: dict,
    mesh_rows: list[tuple[str, str, int]],
) -> None:
    (run_dir / "effective_config.json").write_text(
        json.dumps(effective_config), encoding="utf-8"
    )
    rows = [_CSV_HEADER]
    for component, stat_name, value in mesh_rows:
        rows.append(
            f"{component},{stat_name},,Accumulator,0,0,{value},0,1,{value},{value},0,0,0,0"
        )
    (run_dir / "mesh_stats.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


class SummarizeAtlasActivationTraceTest(unittest.TestCase):
    def test_compute_trace_reports_uniform_fabric_absent_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
                    "workload_impl": "snn",
                    "local_storage_enable": 0,
                    "pe_internal_pod_enable": 0,
                    "pe_internal_pod_metadata_enable": 0,
                    "pe_internal_pod_owner_enable": 0,
                    "pulse": {
                        "enable": 0,
                        "observe_only": 1,
                        "harbor_enable": 0,
                        "descriptor_enable": 0,
                        "descriptor_actual_enable": 0,
                        "osa_enable": 0,
                    },
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_activation_gate_workload_pure_snn_datapath_eligible", 1),
                    ("multicore_pe_1", "atlas_activation_gate_workload_pure_snn_datapath_eligible", 1),
                    ("multicore_pe_0", "atlas_control_runtime_all_zero_total", 1),
                    ("multicore_pe_1", "atlas_control_runtime_all_zero_total", 1),
                    ("multicore_pe_0", "atlas_control_runtime_state_fabric_absent_total", 1),
                    ("multicore_pe_1", "atlas_control_runtime_state_fabric_absent_total", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)

            self.assertEqual(trace["config_requested"]["workload_impl"], "snn")
            self.assertEqual(trace["config_requested"]["pulse"]["enable"], 0)
            self.assertEqual(trace["census"]["pe_count"], 2)
            self.assertEqual(
                trace["census"]["activation_gate"]["workload_pure_snn"]["total"], 2
            )
            self.assertEqual(
                trace["census"]["control_runtime"]["dominant_state"]["label"],
                "fabric_absent",
            )
            self.assertEqual(trace["verdict"]["branch"], "fabric_absent")
            self.assertTrue(trace["verdict"]["is_uniform"])
            self.assertEqual(trace["verdict"]["active_labels"], ["fabric_absent"])
            diff = trace["activation_diff"]
            mismatch = trace["contract_mismatch"]
            self.assertEqual(diff["state_vocabulary"], "atlas_contract_mismatch_v1")
            self.assertEqual(diff["requested"]["local_storage"], 0)
            self.assertEqual(diff["requested"]["pulse"], 0)
            self.assertEqual(diff["requested"]["pulse_osa"], 0)
            self.assertEqual(diff["effective"]["local_storage"]["total"], 0)
            self.assertEqual(diff["effective"]["pulse"]["total"], 0)
            self.assertEqual(diff["effective"]["pulse_osa"]["total"], 0)
            self.assertEqual(diff["constructed"]["pulse_fabric"]["total"], 0)
            self.assertEqual(diff["constructed"]["service_table"]["total"], 0)
            self.assertEqual(diff["constructed"]["shared_weight_plane"]["total"], 0)
            self.assertEqual(diff["constructed"]["pod_metadata_plane"]["total"], 0)
            self.assertEqual(diff["constructed"]["pod_owner_table"]["total"], 0)
            self.assertEqual(diff["surfaces"]["local_storage"]["state"], "disabled")
            self.assertEqual(diff["surfaces"]["local_storage"]["machine_state"], "build_off")
            self.assertEqual(diff["surfaces"]["pulse"]["state"], "not_requested")
            self.assertEqual(diff["surfaces"]["pulse"]["machine_state"], "build_off")
            self.assertEqual(diff["surfaces"]["pulse_osa"]["state"], "not_requested")
            self.assertEqual(diff["surfaces"]["shared_weight"]["state"], "not_constructed")
            self.assertEqual(diff["surfaces"]["shared_weight"]["machine_state"], "absent")
            self.assertEqual(diff["surfaces"]["pod_service"]["state"], "not_constructed")
            self.assertEqual(mismatch["dominant"]["label"], "fabric_absent")
            self.assertEqual(mismatch["phase"]["local_storage"]["state"], "build_off")
            self.assertEqual(mismatch["phase"]["pulse"]["state"], "build_off")
            self.assertEqual(mismatch["phase"]["pulse_osa"]["state"], "build_off")
            self.assertEqual(mismatch["phase"]["pod_service"]["state"], "build_off")
            self.assertEqual(
                mismatch["storage_authority"]["shared_weight"]["state"],
                "absent",
            )
            self.assertEqual(mismatch["control_runtime"]["state"], "fabric_absent")
            self.assertEqual(mismatch["sync"]["state"], "clean")

    def test_compute_trace_reports_mixed_branch_when_runtime_states_diverge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
                    "workload_impl": "snn",
                    "local_storage_enable": 1,
                    "pe_internal_pod_enable": 1,
                    "pe_internal_pod_metadata_enable": 1,
                    "pe_internal_pod_owner_enable": 1,
                    "pulse": {
                        "enable": 1,
                        "observe_only": 0,
                        "harbor_enable": 1,
                        "descriptor_enable": 1,
                        "descriptor_actual_enable": 1,
                        "osa_enable": 1,
                    },
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_activation_gate_workload_pure_snn_datapath_eligible", 1),
                    ("multicore_pe_1", "atlas_activation_gate_workload_pure_snn_datapath_eligible", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pulse_fabric_constructed", 1),
                    ("multicore_pe_1", "atlas_activation_gate_pulse_fabric_constructed", 1),
                    ("multicore_pe_0", "atlas_control_runtime_state_fabric_present_idle_total", 1),
                    ("multicore_pe_1", "atlas_control_runtime_state_consumed_active_total", 1),
                    ("multicore_pe_0", "atlas_control_runtime_all_zero_total", 1),
                    ("multicore_pe_1", "atlas_control_runtime_consumed_any_nonzero_total", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)

            self.assertEqual(trace["census"]["pe_count"], 2)
            self.assertEqual(trace["verdict"]["branch"], "mixed")
            self.assertFalse(trace["verdict"]["is_uniform"])
            self.assertEqual(
                trace["verdict"]["active_labels"],
                ["fabric_present_idle", "consumed_active"],
            )
            diff = trace["activation_diff"]
            mismatch = trace["contract_mismatch"]
            self.assertEqual(diff["state_vocabulary"], "atlas_contract_mismatch_v1")
            self.assertEqual(diff["requested"]["local_storage"], 1)
            self.assertEqual(diff["requested"]["pulse"], 1)
            self.assertEqual(diff["requested"]["pulse_osa"], 1)
            self.assertEqual(diff["effective"]["local_storage"]["total"], 0)
            self.assertEqual(diff["effective"]["pulse"]["total"], 0)
            self.assertEqual(diff["effective"]["pulse_osa"]["total"], 0)
            self.assertEqual(diff["constructed"]["pulse_fabric"]["total"], 2)
            self.assertEqual(diff["constructed"]["service_table"]["total"], 0)
            self.assertEqual(diff["constructed"]["shared_weight_plane"]["total"], 0)
            self.assertEqual(diff["constructed"]["pod_metadata_plane"]["total"], 0)
            self.assertEqual(diff["constructed"]["pod_owner_table"]["total"], 0)
            self.assertEqual(diff["surfaces"]["local_storage"]["state"], "requested_but_not_effective")
            self.assertEqual(diff["surfaces"]["local_storage"]["machine_state"], "configured_not_effective")
            self.assertEqual(diff["surfaces"]["pulse"]["state"], "constructed_without_effective")
            self.assertEqual(diff["surfaces"]["pulse"]["machine_state"], "constructed_without_effective")
            self.assertEqual(diff["surfaces"]["pulse_osa"]["state"], "requested_but_not_effective")
            self.assertEqual(diff["surfaces"]["pulse_osa"]["machine_state"], "runtime_not_requested")
            self.assertEqual(diff["surfaces"]["shared_weight"]["state"], "not_constructed")
            self.assertEqual(diff["surfaces"]["shared_weight"]["machine_state"], "absent")
            self.assertEqual(diff["surfaces"]["pod_service"]["state"], "not_constructed")
            self.assertEqual(mismatch["phase"]["local_storage"]["state"], "configured_not_effective")
            self.assertEqual(mismatch["phase"]["pulse"]["state"], "constructed_without_effective")
            self.assertEqual(mismatch["phase"]["pulse_osa"]["state"], "runtime_not_requested")
            self.assertEqual(mismatch["storage_authority"]["shared_weight"]["state"], "absent")
            self.assertEqual(mismatch["sync"]["state"], "clean")

    def test_compute_trace_exports_object_kind_census(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={"workload_impl": "snn"},
                mesh_rows=[
                    ("multicore_pe_0", "atlas_census_premphf_base_frontier_events_total", 4),
                    ("multicore_pe_0", "atlas_census_idx2row_gate_events_total", 3),
                    ("multicore_pe_0", "atlas_census_rowindex_service_events_total", 6),
                    ("multicore_pe_0", "atlas_census_rowdescriptor_producer_events_total", 2),
                    ("multicore_pe_0", "atlas_pod_metadata_observe_total", 5),
                    ("multicore_pe_0", "atlas_pod_metadata_unique_object_total", 4),
                    ("multicore_pe_0", "atlas_pod_metadata_overlap_hit_total", 2),
                    ("multicore_pe_0", "atlas_pod_owner_owner_alloc_total", 3),
                    ("multicore_pe_0", "atlas_pod_owner_join_grant_total", 2),
                    ("multicore_pe_0", "atlas_pod_owner_rowindex_join_request_total", 7),
                    ("multicore_pe_0", "atlas_pod_owner_rowindex_owner_reject_total", 1),
                    ("multicore_pe_0", "atlas_service_atlas_obj_materialize_total", 8),
                    ("multicore_pe_0", "atlas_service_atlas_obj_owner_form_total", 4),
                    ("multicore_pe_0", "atlas_service_atlas_obj_ready_total", 5),
                    ("multicore_pe_0", "atlas_service_atlas_obj_release_total", 3),
                    ("multicore_pe_0", "atlas_service_atlas_obj_private_only_total", 1),
                    ("multicore_pe_0", "atlas_shared_weight_census_state_mirror_only_total", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)

            census = trace["object_kind_census"]
            objects = census["objects"]
            self.assertEqual(census["matrix_version"], 2)
            self.assertEqual(objects["premphf_base"]["state"], "registered-but-proxied")
            self.assertEqual(objects["premphf_band"]["state"], "missing")
            self.assertEqual(objects["idx2row"]["state"], "registered-but-proxied")
            self.assertEqual(objects["rowindex"]["state"], "shadow-only")
            self.assertEqual(objects["rowdescriptor"]["state"], "registered-but-proxied")
            self.assertEqual(objects["pod_metadata_object"]["state"], "shadow-only")
            self.assertEqual(objects["pod_owner_entry"]["state"], "active")
            self.assertEqual(objects["pe_local_service_object"]["state"], "active")
            self.assertEqual(objects["shared_weight_residency"]["state"], "active")
            self.assertEqual(census["summary"]["active_count"], 3)
            self.assertEqual(census["summary"]["registered_but_proxied_count"], 3)
            self.assertEqual(census["summary"]["shadow_only_count"], 2)
            self.assertEqual(census["summary"]["missing_count"], 1)

    def test_compute_trace_prefers_pe_overrides_for_requested_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
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
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_activation_gate_workload_pure_snn_datapath_eligible", 1),
                    ("multicore_pe_0", "atlas_enable_state_local_storage_effective_total", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pe_internal_pod_requested", 1),
                    ("multicore_pe_0", "atlas_enable_state_pe_internal_pod_effective_total", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pod_metadata_plane_constructed", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pod_owner_table_constructed", 1),
                    ("multicore_pe_0", "atlas_activation_gate_service_table_constructed", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)

            self.assertEqual(trace["config_requested"]["local_storage_enable"], 1)
            self.assertEqual(trace["config_requested"]["pe_internal_pod_enable"], 1)
            self.assertEqual(trace["config_requested"]["pe_internal_pod_metadata_enable"], 1)
            self.assertEqual(trace["config_requested"]["pe_internal_pod_owner_enable"], 1)
            self.assertEqual(int(trace["config_resolution"]["local_storage"]["top_level"]), 0)
            self.assertEqual(int(trace["config_resolution"]["local_storage"]["override"]), 1)
            self.assertEqual(int(trace["config_resolution"]["local_storage"]["resolved"]), 1)
            self.assertIs(trace["config_resolution"]["local_storage"]["conflict"], True)
            self.assertEqual(int(trace["config_resolution"]["pe_internal_pod"]["top_level"]), 0)
            self.assertEqual(int(trace["config_resolution"]["pe_internal_pod"]["override"]), 1)
            self.assertEqual(int(trace["config_resolution"]["pe_internal_pod"]["resolved"]), 1)
            diff = trace["activation_diff"]
            mismatch = trace["contract_mismatch"]
            self.assertEqual(diff["requested"]["local_storage"], 1)
            self.assertEqual(diff["requested"]["pod_enable"], 1)
            self.assertEqual(diff["surfaces"]["local_storage"]["machine_state"], "aligned_active")
            self.assertEqual(diff["surfaces"]["pod_service"]["machine_state"], "aligned_active")
            self.assertEqual(mismatch["phase"]["local_storage"]["state"], "aligned_active")
            self.assertEqual(mismatch["phase"]["pod_service"]["state"], "aligned_active")

    def test_compute_trace_exports_cross_plane_visibility_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
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
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_census_rowindex_service_events_total", 6),
                    ("multicore_pe_0", "atlas_pod_metadata_observe_total", 5),
                    ("multicore_pe_0", "atlas_pod_metadata_unique_object_total", 4),
                    ("multicore_pe_0", "atlas_pod_owner_owner_alloc_total", 3),
                    ("multicore_pe_0", "atlas_pod_owner_join_grant_total", 2),
                    ("multicore_pe_0", "atlas_pod_owner_rowindex_join_request_total", 7),
                    ("multicore_pe_0", "atlas_service_atlas_obj_materialize_total", 8),
                    ("multicore_pe_0", "atlas_service_atlas_obj_owner_form_total", 4),
                    ("multicore_pe_0", "atlas_service_atlas_obj_ready_total", 5),
                    ("multicore_pe_0", "atlas_service_atlas_obj_release_total", 3),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)

            gap = trace["cross_plane_visibility"]["entries"]
            self.assertEqual(
                gap["local_storage_vs_objects"]["gap_state"],
                "build_on_object_visible_runtime_dark",
            )
            self.assertEqual(
                gap["pod_runtime_vs_objects"]["gap_state"],
                "build_on_object_visible_runtime_dark",
            )
            self.assertEqual(
                gap["rowindex_object_vs_pod_runtime"]["objects"]["states"]["rowindex"],
                "shadow-only",
            )
            self.assertEqual(
                gap["pod_runtime_vs_objects"]["objects"]["active_count"],
                2,
            )

    def test_compute_trace_exports_surface_ledger_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
                    "workload_impl": "snn",
                    "local_storage_enable": 0,
                    "pe_internal_pod_enable": 0,
                    "pe_internal_pod_metadata_enable": 0,
                    "pe_internal_pod_owner_enable": 0,
                    "pulse": {
                        "enable": 0,
                        "observe_only": 1,
                        "osa_enable": 0,
                        "osa_shared_weight_owner_enable": 0,
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
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_census_rowindex_service_events_total", 6),
                    ("multicore_pe_0", "atlas_pod_metadata_observe_total", 5),
                    ("multicore_pe_0", "atlas_pod_metadata_unique_object_total", 4),
                    ("multicore_pe_0", "atlas_pod_owner_owner_alloc_total", 3),
                    ("multicore_pe_0", "atlas_pod_owner_join_grant_total", 2),
                    ("multicore_pe_0", "atlas_pod_owner_rowindex_join_request_total", 7),
                    ("multicore_pe_0", "atlas_service_atlas_obj_materialize_total", 8),
                    ("multicore_pe_0", "atlas_service_atlas_obj_owner_form_total", 4),
                    ("multicore_pe_0", "atlas_service_atlas_obj_ready_total", 5),
                    ("multicore_pe_0", "atlas_service_atlas_obj_release_total", 3),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            ledger = trace["surface_ledger"]

            self.assertEqual(ledger["version"], 1)
            self.assertEqual(ledger["vocabulary"], "atlas_surface_ledger_v1")
            self.assertEqual(
                ledger["entries"]["local_storage"]["resolution"]["resolved"],
                1,
            )
            self.assertEqual(
                ledger["entries"]["local_storage"]["surface_state"]["machine_state"],
                "configured_not_effective",
            )
            self.assertEqual(
                ledger["entries"]["local_storage"]["visibility"]["gap_state"],
                "build_on_object_visible_runtime_dark",
            )
            self.assertEqual(
                ledger["entries"]["pod_service"]["contract"]["phase"]["state"],
                "runtime_not_requested",
            )
            self.assertEqual(
                ledger["entries"]["rowindex_object"]["visibility"]["gap_state"],
                "build_on_object_visible_runtime_dark",
            )
            self.assertEqual(
                ledger["entries"]["shared_weight"]["contract"]["phase"]["state"],
                "build_off",
            )
            self.assertEqual(
                ledger["entries"]["shared_weight"]["contract"]["storage_authority"]["state"],
                "absent",
            )

    def test_compute_trace_exports_surface_coverage_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
                    "workload_impl": "snn",
                    "local_storage_enable": 0,
                    "pe_internal_pod_enable": 0,
                    "pe_internal_pod_metadata_enable": 0,
                    "pe_internal_pod_owner_enable": 0,
                    "pulse": {
                        "enable": 0,
                        "observe_only": 1,
                        "osa_enable": 0,
                        "osa_shared_weight_owner_enable": 0,
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
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_census_rowindex_service_events_total", 6),
                    ("multicore_pe_0", "atlas_pod_metadata_observe_total", 5),
                    ("multicore_pe_0", "atlas_pod_metadata_unique_object_total", 4),
                    ("multicore_pe_0", "atlas_pod_owner_owner_alloc_total", 3),
                    ("multicore_pe_0", "atlas_pod_owner_join_grant_total", 2),
                    ("multicore_pe_0", "atlas_pod_owner_rowindex_join_request_total", 7),
                    ("multicore_pe_0", "atlas_service_atlas_obj_materialize_total", 8),
                    ("multicore_pe_0", "atlas_service_atlas_obj_owner_form_total", 4),
                    ("multicore_pe_0", "atlas_service_atlas_obj_ready_total", 5),
                    ("multicore_pe_0", "atlas_service_atlas_obj_release_total", 3),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            coverage = trace["surface_coverage"]

            self.assertEqual(coverage["version"], 1)
            self.assertEqual(coverage["vocabulary"], "atlas_surface_coverage_v1")
            self.assertEqual(
                coverage["entries"]["local_storage"]["plane_status"]["config"],
                "resolved_on_conflict",
            )
            self.assertEqual(
                coverage["entries"]["local_storage"]["plane_status"]["runtime"],
                "dark",
            )
            self.assertEqual(
                coverage["entries"]["local_storage"]["coverage_status"],
                "object_visible_runtime_dark",
            )
            self.assertEqual(
                coverage["entries"]["pod_service"]["coverage_status"],
                "object_visible_runtime_dark",
            )
            self.assertEqual(
                coverage["entries"]["rowindex_object"]["plane_status"]["object"],
                "visible",
            )
            self.assertEqual(
                coverage["entries"]["shared_weight"]["plane_status"]["config"],
                "resolved_off",
            )
            self.assertEqual(
                coverage["entries"]["shared_weight"]["coverage_status"],
                "build_off",
            )

    def test_compute_trace_exports_surface_probe_ledger_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
                    "workload_impl": "snn",
                    "local_storage_enable": 0,
                    "pe_internal_pod_enable": 0,
                    "pe_internal_pod_metadata_enable": 0,
                    "pe_internal_pod_owner_enable": 0,
                    "pulse": {
                        "enable": 0,
                        "observe_only": 1,
                        "osa_enable": 0,
                        "osa_shared_weight_owner_enable": 0,
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
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_census_rowindex_service_events_total", 6),
                    ("multicore_pe_0", "atlas_pod_metadata_observe_total", 5),
                    ("multicore_pe_0", "atlas_pod_metadata_unique_object_total", 4),
                    ("multicore_pe_0", "atlas_pod_owner_owner_alloc_total", 3),
                    ("multicore_pe_0", "atlas_pod_owner_join_grant_total", 2),
                    ("multicore_pe_0", "atlas_pod_owner_rowindex_join_request_total", 7),
                    ("multicore_pe_0", "atlas_service_atlas_obj_materialize_total", 8),
                    ("multicore_pe_0", "atlas_service_atlas_obj_owner_form_total", 4),
                    ("multicore_pe_0", "atlas_service_atlas_obj_ready_total", 5),
                    ("multicore_pe_0", "atlas_service_atlas_obj_release_total", 3),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            probe = trace["surface_probe_ledger"]

            self.assertEqual(probe["version"], 1)
            self.assertEqual(probe["vocabulary"], "atlas_surface_probe_ledger_v1")
            self.assertEqual(
                probe["entries"]["local_storage"]["probe_status"],
                "observed_all_zero",
            )
            self.assertEqual(
                probe["entries"]["local_storage"]["contract_phase_state"],
                "configured_not_effective",
            )
            self.assertEqual(
                probe["entries"]["local_storage"]["zero_probe_cause"],
                "configured_not_effective",
            )
            self.assertIn(
                "enable_state.local_storage",
                probe["entries"]["local_storage"]["observed_zero_probe"],
            )
            self.assertEqual(
                probe["entries"]["rowindex_object"]["probe_status"],
                "observed_all_zero",
            )
            self.assertEqual(
                probe["entries"]["rowindex_object"]["contract_phase_state"],
                "runtime_not_requested",
            )
            self.assertEqual(
                probe["entries"]["rowindex_object"]["zero_probe_cause"],
                "runtime_not_requested",
            )
            self.assertEqual(
                probe["entries"]["rowindex_object"]["missing_probe"],
                [],
            )
            self.assertIn(
                "activation_gate.rowindex_requested",
                probe["entries"]["rowindex_object"]["observed_zero_probe"],
            )
            self.assertEqual(
                probe["entries"]["shared_weight"]["probe_status"],
                "build_off",
            )
            backlog = trace["surface_probe_backlog"]
            self.assertEqual(backlog["version"], 1)
            self.assertEqual(backlog["vocabulary"], "atlas_surface_probe_backlog_v1")
            self.assertEqual(
                backlog["entries"]["rowindex_object"]["action"],
                "investigate_zero_probes",
            )
            self.assertEqual(
                backlog["entries"]["rowindex_object"]["priority"],
                "p1",
            )
            self.assertEqual(
                backlog["entries"]["local_storage"]["action"],
                "investigate_zero_probes",
            )
            self.assertEqual(
                backlog["entries"]["pod_service"]["action"],
                "investigate_zero_probes",
            )
            self.assertEqual(
                backlog["entries"]["pod_service"]["zero_probe_cause"],
                "runtime_not_requested",
            )
            self.assertEqual(
                backlog["entries"]["shared_weight"]["action"],
                "defer_build_off",
            )
            self.assertEqual(
                backlog["summary"]["p1_investigate_zero_probes"],
                3,
            )

    def test_compute_trace_rowindex_effective_gap_backlog_p1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
                    "workload_impl": "snn",
                    "local_storage_enable": 0,
                    "pe_internal_pod_enable": 0,
                    "pe_internal_pod_metadata_enable": 0,
                    "pe_internal_pod_owner_enable": 0,
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
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_activation_gate_rowindex_requested", 1),
                    ("multicore_pe_0", "atlas_activation_gate_rowindex_constructed", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pe_internal_pod_requested", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pod_metadata_plane_constructed", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pod_owner_table_constructed", 1),
                    ("multicore_pe_0", "atlas_activation_gate_service_table_constructed", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_pulse_osa_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_metadata_txn_total", 0),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_metadata_mask_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_pod_enable_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_pod_metadata_enable_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_pod_owner_enable_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_service_table_present_total", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            probe = trace["surface_probe_ledger"]["entries"]["rowindex_object"]
            backlog = trace["surface_probe_backlog"]["entries"]["rowindex_object"]

            self.assertEqual(probe["probe_status"], "observed_some_nonzero")
            self.assertTrue(probe["effective_gap"])
            self.assertEqual(
                probe["effective_gap_cause"],
                "enable_state.rowindex_gate_metadata_txn",
            )
            self.assertEqual(backlog["action"], "investigate_effective_gap")
            self.assertEqual(backlog["priority"], "p1")
            self.assertIn(
                "enable_state.rowindex_gate_metadata_txn",
                backlog["target_probe"],
            )

    def test_compute_trace_exports_rowindex_object_closure_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
                    "workload_impl": "snn",
                    "local_storage_enable": 0,
                    "pe_internal_pod_enable": 0,
                    "pe_internal_pod_metadata_enable": 0,
                    "pe_internal_pod_owner_enable": 0,
                    "pulse": {
                        "enable": 1,
                        "osa_enable": 1,
                        "osa_metadata_txn_enable": 1,
                        "osa_metadata_object_mask": "rowidx,rowdescriptor",
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
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_activation_gate_rowindex_requested", 1),
                    ("multicore_pe_0", "atlas_activation_gate_rowindex_constructed", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pe_internal_pod_requested", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pod_metadata_plane_constructed", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pod_owner_table_constructed", 1),
                    ("multicore_pe_0", "atlas_activation_gate_service_table_constructed", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_pulse_osa_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_metadata_txn_total", 0),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_metadata_mask_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_pod_enable_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_pod_metadata_enable_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_pod_owner_enable_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_rowindex_gate_service_table_present_total", 1),
                    ("multicore_pe_0", "atlas_pod_metadata_observe_total", 5),
                    ("multicore_pe_0", "atlas_pod_metadata_unique_object_total", 4),
                    ("multicore_pe_0", "atlas_census_rowindex_service_events_total", 3),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            closure = trace["object_closure"]["entries"]["rowindex_object"]

            self.assertEqual(trace["object_closure"]["version"], 1)
            self.assertEqual(trace["object_closure"]["vocabulary"], "atlas_object_closure_v1")
            self.assertEqual(closure["requested"]["total"], 1)
            self.assertEqual(closure["constructed"]["total"], 1)
            self.assertEqual(closure["effective"]["total"], 0)
            self.assertEqual(closure["coverage_status"], "object_and_runtime_visible")
            self.assertEqual(closure["effective_gap"], True)
            self.assertEqual(
                closure["effective_gap_cause"],
                "enable_state.rowindex_gate_metadata_txn",
            )
            self.assertIn(
                "enable_state.rowindex_gate_metadata_txn",
                closure["blocked_gates"],
            )

    def test_compute_trace_rowindex_object_closure_uses_rowindex_specific_totals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
                    "workload_impl": "snn",
                    "local_storage_enable": 0,
                    "pe_internal_pod_enable": 0,
                    "pe_internal_pod_metadata_enable": 0,
                    "pe_internal_pod_owner_enable": 0,
                    "pulse": {"enable": 0, "osa_enable": 0},
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
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_activation_gate_pe_internal_pod_requested", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pod_metadata_plane_constructed", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pod_owner_table_constructed", 1),
                    ("multicore_pe_0", "atlas_activation_gate_service_table_constructed", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            closure = trace["object_closure"]["entries"]["rowindex_object"]

            self.assertEqual(closure["requested"]["total"], 0)
            self.assertEqual(closure["constructed"]["total"], 0)
            self.assertEqual(closure["effective"]["total"], 0)

    def test_compute_trace_exports_idx2_and_preband_object_closure_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
                    "workload_impl": "snn",
                    "local_storage_enable": 0,
                    "pe_internal_pod_enable": 0,
                    "pe_internal_pod_metadata_enable": 0,
                    "pe_internal_pod_owner_enable": 0,
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
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_activation_gate_local_storage_enable", 1),
                    ("multicore_pe_0", "atlas_enable_state_local_storage_effective_total", 1),
                    ("multicore_pe_0", "atlas_census_idx2row_gate_events_total", 5),
                    ("multicore_pe_0", "atlas_census_premphf_band_frontier_events_total", 4),
                    ("multicore_pe_0", "atlas_pod_metadata_premphf_band_observe_total", 7),
                    ("multicore_pe_0", "atlas_pod_owner_premphf_band_owner_alloc_total", 4),
                    ("multicore_pe_0", "atlas_pod_owner_premphf_band_join_grant_total", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            idx2 = trace["object_closure"]["entries"]["idx2_object"]
            preband = trace["object_closure"]["entries"]["preband_object"]

            self.assertEqual(idx2["requested"]["total"], 1)
            self.assertEqual(idx2["constructed"]["total"], 0)
            self.assertEqual(idx2["effective"]["total"], 1)
            self.assertEqual(idx2["coverage_status"], "object_and_runtime_visible")
            self.assertEqual(idx2["authority_ref"], "idx2_object")
            self.assertEqual(idx2["formal_object_ref"], "idx2row")
            self.assertEqual(preband["requested"]["total"], 1)
            self.assertEqual(preband["constructed"]["total"], 0)
            self.assertEqual(preband["effective"]["total"], 1)
            self.assertEqual(preband["coverage_status"], "object_and_runtime_visible")
            self.assertEqual(preband["authority_ref"], "preband_object")
            self.assertEqual(preband["formal_object_ref"], "premphf_band")

    def test_compute_trace_exports_storage_authority_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={"workload_impl": "snn"},
                mesh_rows=[
                    ("multicore_pe_0", "weight_idx_sram_reads_total", 10),
                    ("multicore_pe_0", "weight_l0_sram_reads_total", 20),
                    ("multicore_pe_0", "atlas_storage_map_weight_idx_shared_authority_active_total", 1),
                    ("multicore_pe_0", "atlas_storage_map_weight_value_shared_mirror_only_total", 1),
                    ("multicore_pe_0", "atlas_pod_metadata_observe_total", 5),
                    ("multicore_pe_0", "atlas_pod_owner_owner_alloc_total", 4),
                    ("multicore_pe_0", "atlas_pod_owner_join_grant_total", 2),
                    ("multicore_pe_0", "atlas_service_atlas_obj_owner_form_total", 3),
                    ("multicore_pe_0", "atlas_service_atlas_obj_ready_total", 2),
                    ("multicore_pe_0", "atlas_service_atlas_obj_release_total", 1),
                    ("multicore_pe_0", "atlas_census_idx2row_gate_events_total", 3),
                    ("multicore_pe_0", "atlas_proxy_idx2row_owner_form_total", 2),
                    ("multicore_pe_0", "atlas_proxy_idx2row_ready_total", 1),
                    ("multicore_pe_0", "atlas_proxy_idx2row_release_total", 1),
                    ("multicore_pe_0", "atlas_census_premphf_band_frontier_events_total", 4),
                    ("multicore_pe_0", "atlas_pod_metadata_premphf_band_observe_total", 7),
                    ("multicore_pe_0", "atlas_pod_owner_premphf_band_owner_alloc_total", 4),
                    ("multicore_pe_0", "atlas_pod_owner_premphf_band_join_grant_total", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            authority = trace["storage_authority_map"]

            self.assertEqual(authority["entries"]["weight_idx_store"]["authority_state"], "shared_active")
            self.assertEqual(authority["entries"]["weight_value_store"]["authority_state"], "mirror_only")
            self.assertEqual(authority["entries"]["shared_weight_residency"]["authority_state"], "mirror_only")
            self.assertEqual(authority["entries"]["preband_object"]["authority_state"], "join_visible")
            self.assertEqual(authority["entries"]["preband_object"]["lifecycle_stage"], "join")
            self.assertEqual(authority["entries"]["preband_object"]["formal_object_ref"], "premphf_band")
            self.assertEqual(authority["entries"]["preband_object"]["closure_ref"], "preband_object")

    def test_compute_trace_exports_control_commit_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={"workload_impl": "snn"},
                mesh_rows=[
                    ("multicore_pe_0", "atlas_control_runtime_state_consumed_active_total", 1),
                    ("multicore_pe_0", "atlas_control_runtime_consumed_any_nonzero_total", 1),
                    ("multicore_pe_0", "gas_retire_ready_but_blocked_edges_total", 4),
                    ("multicore_pe_0", "retire_wait_cycles_total", 9),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            view = trace["control_commit_view"]

            self.assertEqual(view["state"], "ready_visible_commit_blocked")
            self.assertEqual(view["vocabulary"], "atlas_control_commit_view_v1")
            self.assertEqual(view["contract_state"], "service_ready_commit_blocked")
            self.assertEqual(view["ready_state"], "visible")
            self.assertEqual(view["commit_state"], "blocked")
            self.assertEqual(view["sync_state"], "ready_visible_but_commit_blocked")
            self.assertEqual(view["ready_visible_but_commit_blocked_edges_total"], 4)

    def test_compute_trace_exports_control_commit_dual_axis_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={"workload_impl": "snn"},
                mesh_rows=[
                    ("multicore_pe_0", "atlas_control_runtime_state_fabric_absent_total", 1),
                    ("multicore_pe_0", "atlas_control_runtime_all_zero_total", 1),
                    ("multicore_pe_0", "gas_retire_ready_but_blocked_edges_total", 4),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            view = trace["control_commit_view"]

            self.assertEqual(view["control_state"], "fabric_absent")
            self.assertEqual(view["sync_state"], "ready_visible_but_commit_blocked")
            self.assertEqual(view["contract_state"], "service_ready_commit_blocked")
            self.assertEqual(view["control_contract_state"], "fabric_absent")
            self.assertEqual(view["sync_contract_state"], "service_ready_commit_blocked")

    def test_compute_trace_exports_control_binding_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={"workload_impl": "snn"},
                mesh_rows=[
                    ("multicore_pe_0", "atlas_census_rowdescriptor_producer_events_total", 2),
                    ("multicore_pe_0", "pulse_descriptor_total", 5),
                    ("multicore_pe_0", "pulse_ingress_packets_total", 11),
                    ("multicore_pe_0", "pulse_control_messages_enqueued_total", 4),
                    ("multicore_pe_0", "pulse_control_entries_peak", 2),
                    ("multicore_pe_0", "pulse_control_backlog_cycles_total", 7),
                    ("multicore_pe_0", "atlas_control_runtime_state_consumed_active_total", 1),
                    ("multicore_pe_0", "atlas_control_runtime_consumed_any_nonzero_total", 1),
                    ("multicore_pe_0", "gas_retire_ready_but_blocked_edges_total", 4),
                    ("multicore_pe_0", "retire_wait_cycles_total", 9),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            binding = trace["control_binding_map"]

            self.assertEqual(binding["version"], 1)
            self.assertEqual(binding["vocabulary"], "atlas_control_binding_map_v1")
            self.assertEqual(binding["entries"]["rowdescriptor"]["plane"], "message_plane")
            self.assertEqual(
                binding["entries"]["rowdescriptor"]["formalization_state"],
                "proxy_descriptor_visible",
            )
            self.assertEqual(
                binding["entries"]["activation_ingress_store"]["runtime_owner"],
                "PulseIngressFabric",
            )
            self.assertEqual(
                binding["entries"]["activation_ingress_store"]["formalization_state"],
                "ingress_runtime_visible",
            )
            self.assertEqual(
                binding["entries"]["sync_barrier"]["commit_relation"],
                "service_ready_commit_blocked",
            )
            self.assertEqual(
                binding["entries"]["sync_barrier"]["formalization_state"],
                "sync_gate_visible",
            )

    def test_compute_trace_exports_wms_storage_binding_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={"workload_impl": "snn"},
                mesh_rows=[
                    ("multicore_pe_0", "weight_idx_sram_reads_total", 10),
                    ("multicore_pe_0", "weight_l0_sram_reads_total", 20),
                    ("multicore_pe_0", "weight_l0_fill_total", 6),
                    ("multicore_pe_0", "atlas_storage_map_weight_idx_shared_authority_active_total", 1),
                    ("multicore_pe_0", "atlas_storage_map_weight_value_shared_mirror_only_total", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            binding = trace["wms_storage_binding_map"]

            self.assertEqual(binding["version"], 2)
            self.assertEqual(binding["vocabulary"], "atlas_wms_storage_binding_map_v2")
            self.assertEqual(
                binding["entries"]["weight_idx_store"]["binding_state"],
                "pe_named_per_core_runtime",
            )
            self.assertEqual(
                binding["entries"]["weight_idx_store"]["formalization_state"],
                "scope_widened_private_runtime",
            )
            self.assertEqual(
                binding["entries"]["weight_value_store"]["binding_state"],
                "split_binding_object",
            )
            self.assertEqual(
                binding["entries"]["weight_value_store"]["semantic_overlay_owner"],
                "PulseSeededLineResidency",
            )
            self.assertEqual(
                binding["entries"]["weight_value_store"]["release_contract_state"],
                "split_runtime_unresolved",
            )
            self.assertEqual(
                binding["entries"]["weight_value_store"]["formalization_state"],
                "split_binding_unresolved",
            )
            self.assertEqual(
                binding["entries"]["shared_weight_residency"]["binding_state"],
                "semantic_overlay_only",
            )
            self.assertEqual(
                binding["entries"]["shared_weight_residency"]["evict_contract_state"],
                "non_formal_overlay_unresolved",
            )
            self.assertEqual(
                binding["entries"]["shared_weight_residency"]["formalization_state"],
                "semantic_overlay_unresolved",
            )

    def test_compute_trace_exports_schema_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={"workload_impl": "snn"},
                mesh_rows=[
                    ("multicore_pe_0", "atlas_census_idx2row_gate_events_total", 1),
                    ("multicore_pe_0", "atlas_storage_map_weight_value_shared_mirror_only_total", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            registry = trace["schema_registry"]

            self.assertEqual(registry["version"], 1)
            self.assertEqual(registry["vocabulary"], "atlas_schema_registry_v1")
            self.assertEqual(
                registry["views"]["object_closure"]["vocabulary"],
                "atlas_object_closure_v1",
            )
            self.assertEqual(
                registry["views"]["storage_authority_map"]["vocabulary"],
                "atlas_storage_authority_map_v1",
            )
            self.assertEqual(
                registry["views"]["wms_storage_binding_map"]["vocabulary"],
                "atlas_wms_storage_binding_map_v2",
            )
            self.assertEqual(
                registry["views"]["binding_unresolved_ledger"]["vocabulary"],
                "atlas_binding_unresolved_ledger_v1",
            )
            self.assertEqual(
                registry["views"]["control_binding_map"]["vocabulary"],
                "atlas_control_binding_map_v1",
            )

    def test_compute_trace_exports_binding_unresolved_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={"workload_impl": "snn"},
                mesh_rows=[
                    ("multicore_pe_0", "weight_idx_sram_reads_total", 10),
                    ("multicore_pe_0", "weight_l0_sram_reads_total", 20),
                    ("multicore_pe_0", "weight_l0_fill_total", 6),
                    ("multicore_pe_0", "atlas_storage_map_weight_value_shared_mirror_only_total", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            ledger = trace["binding_unresolved_ledger"]

            self.assertEqual(ledger["version"], 1)
            self.assertEqual(ledger["vocabulary"], "atlas_binding_unresolved_ledger_v1")
            self.assertEqual(
                ledger["entries"]["weight_value_store"]["formalization_state"],
                "split_binding_unresolved",
            )
            self.assertIn(
                "release_owner_unresolved",
                ledger["entries"]["weight_value_store"]["unresolved_edges"],
            )
            self.assertEqual(
                ledger["entries"]["shared_weight_residency"]["formalization_state"],
                "semantic_overlay_unresolved",
            )
            self.assertIn(
                "evict_owner_unresolved",
                ledger["entries"]["shared_weight_residency"]["unresolved_edges"],
            )

    def test_compute_trace_exports_shared_weight_request_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_run_artifacts(
                run_dir,
                effective_config={
                    "workload_impl": "snn",
                    "local_storage_enable": 1,
                    "pulse": {
                        "enable": 1,
                        "osa_enable": 1,
                    },
                },
                mesh_rows=[
                    ("multicore_pe_0", "atlas_activation_gate_pulse_requested", 1),
                    ("multicore_pe_0", "atlas_activation_gate_pulse_osa_requested", 1),
                    ("multicore_pe_0", "atlas_activation_gate_shared_weight_owner_requested", 0),
                    ("multicore_pe_0", "atlas_activation_gate_shared_weight_actual_owner_requested", 0),
                    ("multicore_pe_0", "atlas_enable_state_pulse_effective_total", 1),
                    ("multicore_pe_0", "atlas_enable_state_pulse_osa_effective_total", 1),
                    ("multicore_pe_0", "atlas_shared_weight_census_absent_reason_owner_request_gate_total", 1),
                ],
            )

            trace = saat.compute_atlas_activation_trace(run_dir)
            binding = trace["wms_storage_binding_map"]["entries"]["shared_weight_residency"]
            ledger = trace["binding_unresolved_ledger"]["entries"]["shared_weight_residency"]

            self.assertEqual(binding["binding_state"], "absent")
            self.assertEqual(binding["absent_reason"], "owner_request_gate")
            self.assertEqual(binding["owner_request_state"], "not_requested")
            self.assertEqual(binding["actual_request_state"], "not_requested")
            self.assertEqual(binding["machine_break_label"], "shared_weight_owner")
            self.assertEqual(binding["machine_break_stage"], "runtime_requested")
            self.assertEqual(ledger["absent_reason"], "owner_request_gate")
            self.assertEqual(ledger["owner_request_state"], "not_requested")
            self.assertEqual(ledger["machine_break_stage"], "runtime_requested")


if __name__ == "__main__":
    unittest.main()
