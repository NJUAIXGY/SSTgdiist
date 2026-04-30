import csv
import tempfile
import unittest
from pathlib import Path

from sst_dram_si.tools import compute_essential_summary_mesh as cesm


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("rows must be non-empty")
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


class ComputeEssentialSummaryMeshPulseTest(unittest.TestCase):
    def test_patch_rowindex_fields_loads_source_breakdown_from_mesh_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "mesh_stats.csv").write_text(
                "\n".join(
                    [
                        "ComponentName,StatisticName,StatisticSubId,StatisticType,SimTime,Rank,Sum.u64,SumSQ.u64,Count.u64,Min.u64,Max.u64,Sum.f64,SumSQ.f64,Min.f64,Max.f64",
                        "multicore_pe_0,exp_noc_rowidx_ready_signal_rowindex_response_inflight_waiters_total,,Accumulator,0,0,7,0,1,7,7,0,0,0,0",
                        "multicore_pe_0,exp_noc_rowidx_ready_transition_rowindex_response_inflight_waiters_total,,Accumulator,0,0,3,0,1,3,3,0,0,0,0",
                        "multicore_pe_0,exp_noc_rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total,,Accumulator,0,0,5,0,1,5,5,0,0,0,0",
                    ]
                ),
                encoding="utf-8",
            )
            summary = {
                "run_dir": str(run_dir),
                "noc_mem_joint": {
                    "rowidx_ready_signal_rowindex_response_total": 9.0,
                    "rowidx_ready_transition_rowindex_response_total": 4.0,
                    "rowidx_ready_signal_prefetch_response_total": 6.0,
                    "rowidx_ready_transition_prefetch_response_total": 2.0,
                },
            }

            cesm._patch_rowindex_fields(summary)

            joint = summary["noc_mem_joint"]
            self.assertEqual(
                joint["rowidx_ready_signal_rowindex_response_inflight_waiters_total"], 7.0
            )
            self.assertEqual(
                joint["rowidx_ready_transition_rowindex_response_inflight_waiters_total"], 3.0
            )
            self.assertEqual(
                joint["rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total"], 5.0
            )
            shadow = summary["atlas_shadow"]["rowindex"]
            self.assertEqual(
                shadow["runtime_rowidx_ready_signal_rowindex_response_inflight_waiters_total"], 7.0
            )
            self.assertEqual(
                shadow["runtime_rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total"], 5.0
            )

    def test_compute_summary_exports_atlas_object_kind_census_v2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_premphf_base_frontier_events_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_idx2row_gate_events_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_rowindex_service_events_total",
                        "Sum.u64": "6",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_rowdescriptor_producer_events_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_observe_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_unique_object_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_overlap_hit_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_owner_alloc_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_join_grant_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_rowindex_join_request_total",
                        "Sum.u64": "7",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_rowindex_owner_reject_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_materialize_total",
                        "Sum.u64": "8",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_owner_form_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_ready_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_release_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_private_only_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_shared_weight_census_state_mirror_only_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                ],
            )

            summary = cesm.compute_summary(run_dir)
            census = summary["atlas_object_kind_census"]
            objects = census["objects"]

            self.assertEqual(census["matrix_version"], 2)
            self.assertEqual(
                census["state_taxonomy"],
                ["active", "registered-but-proxied", "shadow-only", "missing"],
            )
            self.assertEqual(objects["premphf_base"]["state"], "registered-but-proxied")
            self.assertEqual(objects["premphf_band"]["state"], "missing")
            self.assertEqual(objects["idx2row"]["state"], "registered-but-proxied")
            self.assertEqual(objects["rowindex"]["state"], "shadow-only")
            self.assertEqual(objects["rowdescriptor"]["state"], "registered-but-proxied")
            self.assertEqual(objects["pod_metadata_object"]["state"], "shadow-only")
            self.assertEqual(objects["pod_owner_entry"]["state"], "active")
            self.assertEqual(objects["pe_local_service_object"]["state"], "active")
            self.assertEqual(objects["shared_weight_residency"]["state"], "active")
            self.assertEqual(census["summary"]["object_count"], 9)
            self.assertEqual(census["summary"]["active_count"], 3)
            self.assertEqual(census["summary"]["registered_but_proxied_count"], 3)
            self.assertEqual(census["summary"]["shadow_only_count"], 2)
            self.assertEqual(census["summary"]["missing_count"], 1)
            self.assertEqual(census["summary"]["non_missing_count"], 8)

    def test_compute_summary_exports_cross_plane_visibility_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_rowindex_service_events_total",
                        "Sum.u64": "6",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_observe_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_unique_object_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_owner_alloc_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_join_grant_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_rowindex_join_request_total",
                        "Sum.u64": "7",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_materialize_total",
                        "Sum.u64": "8",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_owner_form_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_ready_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_release_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                ],
            )
            (run_dir / "effective_config.json").write_text(
                __import__("json").dumps(
                    {
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
                    }
                ),
                encoding="utf-8",
            )

            summary = cesm.compute_summary(run_dir)
            gap = summary["atlas_cross_plane_visibility"]["entries"]

            self.assertEqual(
                gap["local_storage_vs_objects"]["gap_state"],
                "build_on_object_visible_runtime_dark",
            )
            self.assertEqual(
                gap["pod_runtime_vs_objects"]["gap_state"],
                "build_on_object_visible_runtime_dark",
            )
            self.assertEqual(
                gap["rowindex_object_vs_pod_runtime"]["gap_state"],
                "build_on_object_visible_runtime_dark",
            )
            self.assertEqual(
                gap["pod_runtime_vs_objects"]["objects"]["active_count"],
                2,
            )
            self.assertEqual(
                gap["pod_runtime_vs_objects"]["objects"]["shadow_only_count"],
                1,
            )
            self.assertEqual(
                gap["rowindex_object_vs_pod_runtime"]["objects"]["states"]["rowindex"],
                "shadow-only",
            )

    def test_compute_summary_exports_surface_ledger_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_rowindex_service_events_total",
                        "Sum.u64": "6",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_observe_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_unique_object_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_owner_alloc_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_join_grant_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_rowindex_join_request_total",
                        "Sum.u64": "7",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_materialize_total",
                        "Sum.u64": "8",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_owner_form_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_ready_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_release_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                ],
            )
            (run_dir / "effective_config.json").write_text(
                __import__("json").dumps(
                    {
                        "workload_impl": "snn",
                        "local_storage_enable": 0,
                        "pe_internal_pod_enable": 0,
                        "pe_internal_pod_metadata_enable": 0,
                        "pe_internal_pod_owner_enable": 0,
                        "pulse": {
                            "enable": 0,
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
                    }
                ),
                encoding="utf-8",
            )

            summary = cesm.compute_summary(run_dir)
            ledger = summary["atlas_surface_ledger"]

            self.assertEqual(ledger["version"], 1)
            self.assertEqual(ledger["surface_vocabulary"], "atlas_surface_ledger_v1")
            self.assertEqual(
                ledger["entries"]["local_storage"]["config_resolution"]["local_storage"]["resolved"],
                1,
            )
            self.assertIs(
                ledger["entries"]["local_storage"]["config_resolution"]["local_storage"]["conflict"],
                True,
            )
            self.assertEqual(
                ledger["entries"]["local_storage"]["runtime"]["build_effective"],
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
                ledger["entries"]["pod_service"]["config_resolution"]["pe_internal_pod"]["resolved"],
                1,
            )
            self.assertEqual(
                ledger["entries"]["pod_service"]["contract_phase"]["state"],
                "runtime_not_requested",
            )
            self.assertEqual(
                ledger["entries"]["rowindex_object"]["visibility"]["gap_state"],
                "build_on_object_visible_runtime_dark",
            )
            self.assertEqual(
                ledger["entries"]["shared_weight"]["config_resolution"]["shared_weight_owner"]["resolved"],
                0,
            )
            self.assertEqual(
                ledger["entries"]["shared_weight"]["storage_authority"]["state"],
                "absent",
            )

    def test_compute_summary_exports_surface_coverage_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_rowindex_service_events_total",
                        "Sum.u64": "6",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_observe_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_unique_object_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_owner_alloc_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_join_grant_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_rowindex_join_request_total",
                        "Sum.u64": "7",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_materialize_total",
                        "Sum.u64": "8",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_owner_form_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_ready_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_release_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                ],
            )
            (run_dir / "effective_config.json").write_text(
                __import__("json").dumps(
                    {
                        "workload_impl": "snn",
                        "local_storage_enable": 0,
                        "pe_internal_pod_enable": 0,
                        "pe_internal_pod_metadata_enable": 0,
                        "pe_internal_pod_owner_enable": 0,
                        "pulse": {
                            "enable": 0,
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
                    }
                ),
                encoding="utf-8",
            )

            summary = cesm.compute_summary(run_dir)
            coverage = summary["atlas_surface_coverage"]

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
                coverage["entries"]["local_storage"]["plane_status"]["object"],
                "visible",
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
                coverage["entries"]["shared_weight"]["plane_status"]["storage_authority"],
                "dark",
            )
            self.assertEqual(
                coverage["entries"]["shared_weight"]["coverage_status"],
                "build_off",
            )

    def test_compute_summary_exports_surface_probe_ledger_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_rowindex_service_events_total",
                        "Sum.u64": "6",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_observe_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_unique_object_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_owner_alloc_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_join_grant_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_rowindex_join_request_total",
                        "Sum.u64": "7",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_materialize_total",
                        "Sum.u64": "8",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_owner_form_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_ready_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_release_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                ],
            )
            (run_dir / "effective_config.json").write_text(
                __import__("json").dumps(
                    {
                        "workload_impl": "snn",
                        "local_storage_enable": 0,
                        "pe_internal_pod_enable": 0,
                        "pe_internal_pod_metadata_enable": 0,
                        "pe_internal_pod_owner_enable": 0,
                        "pulse": {
                            "enable": 0,
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
                    }
                ),
                encoding="utf-8",
            )

            summary = cesm.compute_summary(run_dir)
            probe = summary["atlas_surface_probe_ledger"]

            self.assertEqual(probe["version"], 1)
            self.assertEqual(probe["vocabulary"], "atlas_surface_probe_ledger_v1")
            self.assertIn(
                "activation_gate.local_storage_enable",
                probe["entries"]["local_storage"]["expected_probe"],
            )
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
                "activation_gate.local_storage_enable",
                probe["entries"]["local_storage"]["observed_zero_probe"],
            )
            self.assertEqual(
                probe["entries"]["local_storage"]["missing_probe"],
                [],
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
            self.assertIn(
                "activation_gate.pe_internal_pod_requested",
                probe["entries"]["rowindex_object"]["observed_zero_probe"],
            )
            self.assertEqual(
                probe["entries"]["shared_weight"]["probe_status"],
                "build_off",
            )
            backlog = summary["atlas_surface_probe_backlog"]
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
            self.assertIn(
                "activation_gate.rowindex_requested",
                backlog["entries"]["rowindex_object"]["target_probe"],
            )
            self.assertEqual(
                backlog["entries"]["local_storage"]["action"],
                "investigate_zero_probes",
            )
            self.assertEqual(
                backlog["entries"]["local_storage"]["priority"],
                "p1",
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
            self.assertEqual(
                backlog["summary"]["p3_defer_build_off"],
                3,
            )

    def test_rowindex_effective_gap_is_classified_as_p1_with_gate_cause(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_rowindex_requested",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_rowindex_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pe_internal_pod_requested",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pod_metadata_plane_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pod_owner_table_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_service_table_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_pulse_osa_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_metadata_txn_total",
                        "Sum.u64": "0",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_metadata_mask_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_pod_enable_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_pod_metadata_enable_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_pod_owner_enable_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_service_table_present_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                ],
            )
            (run_dir / "effective_config.json").write_text(
                __import__("json").dumps(
                    {
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
                    }
                ),
                encoding="utf-8",
            )

            summary = cesm.compute_summary(run_dir)
            probe = summary["atlas_surface_probe_ledger"]["entries"]["rowindex_object"]
            backlog = summary["atlas_surface_probe_backlog"]["entries"]["rowindex_object"]

            self.assertEqual(probe["probe_status"], "observed_some_nonzero")
            self.assertTrue(probe["effective_gap"])
            self.assertEqual(
                probe["effective_gap_cause"],
                "enable_state.rowindex_gate_metadata_txn",
            )
            self.assertIn(
                "enable_state.rowindex_gate_metadata_txn",
                probe["effective_gap_blocked_gates"],
            )
            self.assertEqual(backlog["action"], "investigate_effective_gap")
            self.assertEqual(backlog["priority"], "p1")
            self.assertIn(
                "enable_state.rowindex_gate_metadata_txn",
                backlog["target_probe"],
            )

    def test_compute_summary_exports_rowindex_object_closure_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_rowindex_requested",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_rowindex_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pe_internal_pod_requested",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pod_metadata_plane_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pod_owner_table_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_service_table_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_pulse_osa_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_metadata_txn_total",
                        "Sum.u64": "0",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_metadata_mask_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_pod_enable_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_pod_metadata_enable_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_pod_owner_enable_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_rowindex_gate_service_table_present_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_observe_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_unique_object_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_rowindex_service_events_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                ],
            )
            (run_dir / "effective_config.json").write_text(
                __import__("json").dumps(
                    {
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
                    }
                ),
                encoding="utf-8",
            )

            summary = cesm.compute_summary(run_dir)
            closure = summary["atlas_object_closure"]["entries"]["rowindex_object"]

            self.assertEqual(summary["atlas_object_closure"]["version"], 1)
            self.assertEqual(
                summary["atlas_object_closure"]["vocabulary"],
                "atlas_object_closure_v1",
            )
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
            self.assertEqual(
                closure["config_resolution"]["pulse_osa"]["resolved"],
                1,
            )

    def test_rowindex_object_closure_uses_rowindex_specific_totals_not_pod_totals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pe_internal_pod_requested",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pod_metadata_plane_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pod_owner_table_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_service_table_constructed",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                ],
            )
            (run_dir / "effective_config.json").write_text(
                __import__("json").dumps(
                    {
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
                    }
                ),
                encoding="utf-8",
            )

            summary = cesm.compute_summary(run_dir)
            closure = summary["atlas_object_closure"]["entries"]["rowindex_object"]

            self.assertEqual(closure["requested"]["total"], 0)
            self.assertEqual(closure["constructed"]["total"], 0)
            self.assertEqual(closure["effective"]["total"], 0)

    def test_compute_summary_exports_idx2_and_preband_object_closure_templates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_local_storage_enable",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_local_storage_effective_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_idx2row_gate_events_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_premphf_band_frontier_events_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_premphf_band_observe_total",
                        "Sum.u64": "7",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_premphf_band_owner_alloc_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_premphf_band_join_grant_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                ],
            )
            (run_dir / "effective_config.json").write_text(
                __import__("json").dumps(
                    {
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
                    }
                ),
                encoding="utf-8",
            )

            summary = cesm.compute_summary(run_dir)
            idx2 = summary["atlas_object_closure"]["entries"]["idx2_object"]
            preband = summary["atlas_object_closure"]["entries"]["preband_object"]

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

    def test_compute_summary_exports_storage_authority_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "weight_idx_sram_reads_total",
                        "Sum.u64": "10",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "weight_l0_sram_reads_total",
                        "Sum.u64": "20",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_storage_map_weight_idx_shared_authority_active_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_storage_map_weight_value_shared_mirror_only_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_observe_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_owner_alloc_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_join_grant_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_owner_form_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_ready_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_service_atlas_obj_release_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_idx2row_gate_events_total",
                        "Sum.u64": "3",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_proxy_idx2row_owner_form_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_proxy_idx2row_ready_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_proxy_idx2row_release_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_premphf_band_frontier_events_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_metadata_premphf_band_observe_total",
                        "Sum.u64": "7",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_premphf_band_owner_alloc_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_pod_owner_premphf_band_join_grant_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                ],
            )

            summary = cesm.compute_summary(run_dir)
            authority = summary["atlas_storage_authority_map"]

            self.assertEqual(authority["version"], 1)
            self.assertEqual(authority["entries"]["weight_idx_store"]["authority_state"], "shared_active")
            self.assertEqual(authority["entries"]["weight_value_store"]["authority_state"], "mirror_only")
            self.assertEqual(authority["entries"]["shared_weight_residency"]["authority_state"], "mirror_only")
            self.assertEqual(authority["entries"]["shared_weight_residency"]["lifecycle_stage"], "mirror_only")
            self.assertEqual(authority["entries"]["shared_weight_residency"]["formal_object_ref"], "shared_weight_residency")
            self.assertEqual(authority["entries"]["pod_metadata_plane"]["authority_state"], "observed")
            self.assertEqual(authority["entries"]["pod_owner_table"]["authority_state"], "join_visible")
            self.assertEqual(authority["entries"]["pe_local_service_table"]["authority_state"], "release_visible")
            self.assertEqual(authority["entries"]["idx2_object"]["authority_state"], "release_visible")
            self.assertEqual(authority["entries"]["preband_object"]["authority_state"], "join_visible")
            self.assertEqual(authority["entries"]["weight_idx_store"]["lifecycle_stage"], "shared_active")
            self.assertEqual(authority["entries"]["pod_metadata_plane"]["lifecycle_stage"], "observe")
            self.assertEqual(authority["entries"]["idx2_object"]["lifecycle_stage"], "release")
            self.assertEqual(authority["entries"]["idx2_object"]["formal_object_ref"], "idx2row")
            self.assertEqual(authority["entries"]["idx2_object"]["closure_ref"], "idx2_object")
            self.assertGreater(authority["entries"]["idx2_object"]["evidence_total"], 0.0)

    def test_compute_summary_exports_control_commit_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_control_runtime_state_consumed_active_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_control_runtime_consumed_any_nonzero_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "gas_retire_ready_but_blocked_edges_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "retire_wait_cycles_total",
                        "Sum.u64": "9",
                        "SimTime": "0",
                    },
                ],
            )

            summary = cesm.compute_summary(run_dir)
            view = summary["atlas_control_commit_view"]

            self.assertEqual(view["state"], "ready_visible_commit_blocked")
            self.assertEqual(view["vocabulary"], "atlas_control_commit_view_v1")
            self.assertEqual(view["contract_state"], "service_ready_commit_blocked")
            self.assertEqual(view["control_state"], "aligned_active")
            self.assertEqual(view["ready_state"], "visible")
            self.assertEqual(view["commit_state"], "blocked")
            self.assertEqual(view["sync_state"], "ready_visible_but_commit_blocked")
            self.assertEqual(view["ready_visible_but_commit_blocked_edges_total"], 4)

    def test_compute_summary_freezes_control_commit_dual_axis_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_control_runtime_state_fabric_absent_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_control_runtime_all_zero_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "gas_retire_ready_but_blocked_edges_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                ],
            )

            summary = cesm.compute_summary(run_dir)
            view = summary["atlas_control_commit_view"]

            self.assertEqual(view["control_state"], "fabric_absent")
            self.assertEqual(view["sync_state"], "ready_visible_but_commit_blocked")
            self.assertEqual(view["contract_state"], "service_ready_commit_blocked")
            self.assertEqual(view["control_contract_state"], "fabric_absent")
            self.assertEqual(view["sync_contract_state"], "service_ready_commit_blocked")

    def test_compute_summary_exports_control_binding_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_rowdescriptor_producer_events_total",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "pulse_descriptor_total",
                        "Sum.u64": "5",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "pulse_ingress_packets_total",
                        "Sum.u64": "11",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "pulse_control_messages_enqueued_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "pulse_control_entries_peak",
                        "Sum.u64": "2",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "pulse_control_backlog_cycles_total",
                        "Sum.u64": "7",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_control_runtime_state_consumed_active_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_control_runtime_consumed_any_nonzero_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "gas_retire_ready_but_blocked_edges_total",
                        "Sum.u64": "4",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "retire_wait_cycles_total",
                        "Sum.u64": "9",
                        "SimTime": "0",
                    },
                ],
            )

            summary = cesm.compute_summary(run_dir)
            binding = summary["atlas_control_binding_map"]

            self.assertEqual(binding["version"], 1)
            self.assertEqual(binding["vocabulary"], "atlas_control_binding_map_v1")
            self.assertEqual(binding["entries"]["rowdescriptor"]["plane"], "message_plane")
            self.assertEqual(
                binding["entries"]["rowdescriptor"]["object_role"],
                "proxy_backed_descriptor",
            )
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

    def test_compute_summary_exports_wms_storage_binding_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "weight_idx_sram_reads_total",
                        "Sum.u64": "10",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "weight_l0_sram_reads_total",
                        "Sum.u64": "20",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "weight_l0_fill_total",
                        "Sum.u64": "6",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_storage_map_weight_idx_shared_authority_active_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_storage_map_weight_value_shared_mirror_only_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                ],
            )

            summary = cesm.compute_summary(run_dir)
            binding = summary["atlas_wms_storage_binding_map"]

            self.assertEqual(binding["version"], 2)
            self.assertEqual(binding["vocabulary"], "atlas_wms_storage_binding_map_v2")
            self.assertEqual(
                binding["entries"]["weight_idx_store"]["runtime_owner"],
                "WeightMemorySubsystem",
            )
            self.assertEqual(
                binding["entries"]["weight_idx_store"]["binding_state"],
                "pe_named_per_core_runtime",
            )
            self.assertEqual(
                binding["entries"]["weight_value_store"]["binding_state"],
                "split_binding_object",
            )
            self.assertEqual(
                binding["entries"]["weight_idx_store"]["namespace_scope"],
                "per_pe_object_name",
            )
            self.assertEqual(
                binding["entries"]["weight_idx_store"]["physical_scope"],
                "per_core_private_sram",
            )
            self.assertEqual(
                binding["entries"]["weight_idx_store"]["formalization_state"],
                "scope_widened_private_runtime",
            )
            self.assertEqual(
                binding["entries"]["weight_value_store"]["semantic_overlay_owner"],
                "PulseSeededLineResidency",
            )
            self.assertEqual(
                binding["entries"]["weight_value_store"]["release_owner"],
                "unresolved_split_binding",
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
                binding["entries"]["weight_value_store"]["authority_ref"],
                "weight_value_store",
            )
            self.assertEqual(
                binding["entries"]["shared_weight_residency"]["runtime_owner"],
                "PulseSeededLineResidency",
            )
            self.assertEqual(
                binding["entries"]["shared_weight_residency"]["binding_state"],
                "semantic_overlay_only",
            )
            self.assertEqual(
                binding["entries"]["shared_weight_residency"]["physical_scope"],
                "no_formal_local_storage_contract",
            )
            self.assertEqual(
                binding["entries"]["shared_weight_residency"]["evict_owner"],
                "unresolved_non_formal_owner",
            )
            self.assertEqual(
                binding["entries"]["shared_weight_residency"]["evict_contract_state"],
                "non_formal_overlay_unresolved",
            )
            self.assertEqual(
                binding["entries"]["shared_weight_residency"]["formalization_state"],
                "semantic_overlay_unresolved",
            )

    def test_compute_summary_exports_schema_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_census_idx2row_gate_events_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_storage_map_weight_value_shared_mirror_only_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                ],
            )

            summary = cesm.compute_summary(run_dir)
            registry = summary["atlas_schema_registry"]

            self.assertEqual(registry["version"], 1)
            self.assertEqual(registry["vocabulary"], "atlas_schema_registry_v1")
            self.assertEqual(
                registry["views"]["atlas_object_closure"]["vocabulary"],
                "atlas_object_closure_v1",
            )
            self.assertEqual(
                registry["views"]["atlas_storage_authority_map"]["vocabulary"],
                "atlas_storage_authority_map_v1",
            )
            self.assertEqual(
                registry["views"]["atlas_wms_storage_binding_map"]["vocabulary"],
                "atlas_wms_storage_binding_map_v2",
            )
            self.assertEqual(
                registry["views"]["atlas_binding_unresolved_ledger"]["vocabulary"],
                "atlas_binding_unresolved_ledger_v1",
            )
            self.assertEqual(
                registry["views"]["atlas_control_binding_map"]["vocabulary"],
                "atlas_control_binding_map_v1",
            )

    def test_compute_summary_exports_binding_unresolved_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "weight_idx_sram_reads_total",
                        "Sum.u64": "10",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "weight_l0_sram_reads_total",
                        "Sum.u64": "20",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "weight_l0_fill_total",
                        "Sum.u64": "6",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_storage_map_weight_value_shared_mirror_only_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                ],
            )

            summary = cesm.compute_summary(run_dir)
            ledger = summary["atlas_binding_unresolved_ledger"]

            self.assertEqual(ledger["version"], 1)
            self.assertEqual(ledger["vocabulary"], "atlas_binding_unresolved_ledger_v1")
            self.assertEqual(
                ledger["entries"]["weight_idx_store"]["formalization_state"],
                "scope_widened_private_runtime",
            )
            self.assertIn(
                "scope_widening_without_shared_arbitration",
                ledger["entries"]["weight_idx_store"]["unresolved_edges"],
            )
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
                "no_formal_local_storage_contract",
                ledger["entries"]["shared_weight_residency"]["unresolved_edges"],
            )

    def test_compute_summary_exports_shared_weight_request_mapping_in_binding_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "effective_config.json").write_text(
                """{
  "workload_impl": "snn",
  "local_storage_enable": 1,
  "pulse": {
    "enable": 1,
    "osa_enable": 1
  }
}
""",
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pulse_requested",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_pulse_osa_requested",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_shared_weight_owner_requested",
                        "Sum.u64": "0",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_activation_gate_shared_weight_actual_owner_requested",
                        "Sum.u64": "0",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_pulse_effective_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_enable_state_pulse_osa_effective_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "atlas_shared_weight_census_absent_reason_owner_request_gate_total",
                        "Sum.u64": "1",
                        "SimTime": "0",
                    },
                ],
            )

            summary = cesm.compute_summary(run_dir)
            binding = summary["atlas_wms_storage_binding_map"]["entries"][
                "shared_weight_residency"
            ]
            ledger = summary["atlas_binding_unresolved_ledger"]["entries"][
                "shared_weight_residency"
            ]

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
