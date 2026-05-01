import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_object_machine_snapshot.py"


def _load_module():
    if not SCRIPT_PATH.exists():
        raise AssertionError(f"missing script: {SCRIPT_PATH}")
    module_spec = importlib.util.spec_from_file_location(
        "pe_object_machine_snapshot",
        SCRIPT_PATH,
    )
    if module_spec is None or module_spec.loader is None:
        raise AssertionError(f"failed to load module spec from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


class MakeObjectMachineSnapshotTest(unittest.TestCase):
    def test_script_exists(self):
        self.assertTrue(SCRIPT_PATH.exists(), f"missing script: {SCRIPT_PATH}")

    def test_main_refreshes_case_before_snapshot_when_requested(self):
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            experiment_dir = root / "exp"
            run_dir = experiment_dir / "runs" / "case_a" / "20260416-000000"
            latest = run_dir.parent / "latest"
            run_dir.mkdir(parents=True)
            latest.symlink_to(run_dir, target_is_directory=True)
            self._write_case_artifacts(run_dir)

            cases_path = experiment_dir / "cases.json"
            cases_path.parent.mkdir(parents=True, exist_ok=True)
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "pe_object_machine_qualification_v1",
                        "baseline_case": "case_a",
                        "cases": [
                            {
                                "id": "case_a",
                                "label": "Case A",
                                "run_dir": "runs/case_a/latest",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = experiment_dir / "snapshot" / "case_a.object_machine_snapshot.json"
            refresh_calls = []

            def _fake_refresh(target_run_dir: Path, project_root: Path) -> None:
                refresh_calls.append((target_run_dir, project_root))

            with mock.patch.object(
                module,
                "_refresh_run_artifacts",
                side_effect=_fake_refresh,
                create=True,
            ):
                rc = module.main(
                    [
                        "--cases",
                        str(cases_path),
                        "--case-id",
                        "case_a",
                        "--out",
                        str(out_path),
                        "--refresh-runs",
                    ]
                )

            self.assertEqual(rc, 0)
            self.assertTrue(out_path.exists())
            self.assertEqual(
                refresh_calls,
                [
                    (run_dir.resolve(), SCRIPT_PATH.resolve().parents[3]),
                ],
            )

    def test_builds_snapshot_from_trace_views_and_derives_machine_summary(self):
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            experiment_dir = root / "exp"
            run_dir = experiment_dir / "runs" / "case_a" / "20260416-000000"
            latest = run_dir.parent / "latest"
            run_dir.mkdir(parents=True)
            latest.symlink_to(run_dir, target_is_directory=True)
            self._write_case_artifacts(
                run_dir,
                trace_overrides={
                    "object_kind_census": {
                        "matrix_version": 2,
                        "objects": {
                            "shared_weight_residency": {
                                "scope": "P-scope",
                                "state": "active",
                                "reason": "trace-preferred",
                            }
                        },
                        "summary": {"active_count": 1},
                    }
                },
                summary_overrides={
                    "atlas_object_kind_census": {
                        "matrix_version": 2,
                        "objects": {
                            "shared_weight_residency": {
                                "scope": "P-scope",
                                "state": "missing",
                                "reason": "summary-should-not-win",
                            }
                        },
                        "summary": {"active_count": 0},
                    }
                },
            )

            cases_path = experiment_dir / "cases.json"
            cases_path.parent.mkdir(parents=True, exist_ok=True)
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "pe_object_machine_qualification_v1",
                        "baseline_case": "case_a",
                        "cases": [
                            {
                                "id": "case_a",
                                "label": "Case A",
                                "run_dir": "runs/case_a/latest",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = experiment_dir / "snapshot" / "case_a.object_machine_snapshot.json"
            rc = module.main(
                [
                    "--cases",
                    str(cases_path),
                    "--case-id",
                    "case_a",
                    "--out",
                    str(out_path),
                ]
            )

            self.assertEqual(rc, 0)
            snapshot = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(snapshot["experiment_id"], "pe_object_machine_qualification_v1")
            self.assertEqual(snapshot["case"]["id"], "case_a")
            self.assertEqual(snapshot["validation"]["warn"], 1)
            self.assertEqual(snapshot["config"]["noc_type"], "multicast_mesh")
            self.assertEqual(snapshot["config"]["pulse"]["osa_shared_weight_owner_enable"], 1)
            self.assertEqual(snapshot["views"]["source_map"]["object_kind_census"], "trace")
            self.assertEqual(
                snapshot["views"]["object_kind_census"]["objects"]["shared_weight_residency"]["reason"],
                "trace-preferred",
            )
            self.assertEqual(
                snapshot["compact_objects"]["rowindex_object"]["contract_phase_state"],
                "aligned_active",
            )
            self.assertEqual(
                snapshot["compact_objects"]["shared_weight_residency"]["formalization_state"],
                "semantic_overlay_unresolved",
            )
            self.assertEqual(
                snapshot["compact_objects"]["sync_barrier"]["formalization_state"],
                "sync_gate_visible",
            )
            self.assertEqual(snapshot["derived"]["unresolved_binding_entries"], 1)
            self.assertEqual(snapshot["derived"]["unresolved_binding_edges_total"], 3)
            self.assertIn(
                "shared weight remains overlay-only",
                snapshot["derived"]["machine_blockers"],
            )
            self.assertEqual(
                snapshot["derived"]["schema_vocabularies"]["object_closure"],
                "atlas_object_closure_v1",
            )

    @staticmethod
    def _write_case_artifacts(
        run_dir: Path,
        *,
        trace_overrides: dict | None = None,
        summary_overrides: dict | None = None,
    ) -> None:
        effective_config = {
            "noc_type": "multicast_mesh",
            "local_storage_enable": 1,
            "pe_internal_pod_enable": 1,
            "pe_internal_pod_metadata_enable": 1,
            "pe_internal_pod_owner_enable": 1,
            "pulse": {
                "enable": 1,
                "osa_enable": 1,
                "osa_shared_weight_owner_enable": 1,
                "osa_shared_weight_owner_actual_enable": 0,
            },
        }
        essential_summary = {
            "atlas_object_kind_census": {
                "matrix_version": 2,
                "objects": {
                    "shared_weight_residency": {
                        "scope": "P-scope",
                        "state": "active",
                        "reason": "summary-default",
                    }
                },
                "summary": {"active_count": 1},
            },
            "atlas_wms_storage_binding_map": {
                "version": 2,
                "vocabulary": "atlas_wms_storage_binding_map_v2",
                "entries": {
                    "shared_weight_residency": {
                        "authority_state": "actual_owner",
                        "binding_state": "semantic_overlay_only",
                        "formalization_state": "semantic_overlay_unresolved",
                        "machine_break_stage": "control_runtime",
                        "machine_break_label": "fabric_absent",
                        "runtime_owner": "PulseSeededLineResidency",
                    },
                    "weight_idx_store": {
                        "authority_state": "shared_active",
                        "binding_state": "pe_named_per_core_runtime",
                        "formalization_state": "scope_widened_private_runtime",
                        "runtime_owner": "WeightMemorySubsystem",
                    },
                    "weight_value_store": {
                        "authority_state": "shared_active",
                        "binding_state": "split_binding_object",
                        "formalization_state": "split_binding_unresolved",
                        "runtime_owner": "WeightMemorySubsystem",
                    },
                },
                "summary": {},
            },
            "atlas_binding_unresolved_ledger": {
                "version": 1,
                "vocabulary": "atlas_binding_unresolved_ledger_v1",
                "entries": {
                    "shared_weight_residency": {
                        "formalization_state": "semantic_overlay_unresolved",
                        "reason": "shared weight remains overlay-only",
                        "unresolved_edges": [
                            "release_owner_unresolved",
                            "evict_owner_unresolved",
                            "no_formal_local_storage_contract",
                        ],
                        "unresolved_edges_count": 3,
                    }
                },
                "summary": {"semantic_overlay_unresolved": 1},
            },
            "atlas_control_binding_map": {
                "version": 1,
                "vocabulary": "atlas_control_binding_map_v1",
                "entries": {
                    "activation_ingress_store": {
                        "formalization_state": "ingress_runtime_dark",
                        "lifecycle_contract": "ingress_enqueue_dispatch",
                        "commit_relation": "feeds_control_runtime",
                        "runtime_owner": "PulseIngressFabric",
                    },
                    "rowdescriptor": {
                        "formalization_state": "proxy_descriptor_dark",
                        "lifecycle_contract": "producer_to_descriptor_proxy",
                        "commit_relation": "indirect_message_only",
                        "runtime_owner": "PulseDescriptorProxy",
                    },
                    "sync_barrier": {
                        "formalization_state": "sync_gate_visible",
                        "lifecycle_contract": "ready_to_commit_gate",
                        "commit_relation": "service_ready_commit_blocked",
                        "runtime_owner": "RetireSyncPath",
                    },
                },
                "summary": {"sync_gate_visible": 1},
            },
            "atlas_object_closure": {
                "version": 1,
                "vocabulary": "atlas_object_closure_v1",
                "entries": {
                    "rowindex_object": {
                        "authority_state": "absent",
                        "coverage_status": "build_on_both_planes_dark",
                        "contract_phase_state": "aligned_active",
                        "machine_reason": "rowindex object plane remains dark",
                        "formal_object_ref": "rowindex",
                    },
                    "idx2_object": {
                        "authority_state": "absent",
                        "coverage_status": "runtime_visible_object_dark",
                        "contract_phase_state": "aligned_active",
                        "machine_reason": "idx2 object plane remains dark",
                        "formal_object_ref": "idx2row",
                    },
                    "preband_object": {
                        "authority_state": "absent",
                        "coverage_status": "runtime_visible_object_dark",
                        "contract_phase_state": "aligned_active",
                        "machine_reason": "preband object plane remains dark",
                        "formal_object_ref": "premphf_band",
                    },
                },
            },
            "atlas_schema_registry": {
                "version": 1,
                "vocabulary": "atlas_schema_registry_v1",
                "views": {
                    "object_kind_census": {
                        "vocabulary": "atlas_object_kind_census_v2",
                        "version": 2,
                    },
                    "wms_storage_binding_map": {
                        "vocabulary": "atlas_wms_storage_binding_map_v2",
                        "version": 2,
                    },
                    "binding_unresolved_ledger": {
                        "vocabulary": "atlas_binding_unresolved_ledger_v1",
                        "version": 1,
                    },
                    "control_binding_map": {
                        "vocabulary": "atlas_control_binding_map_v1",
                        "version": 1,
                    },
                    "object_closure": {
                        "vocabulary": "atlas_object_closure_v1",
                        "version": 1,
                    },
                },
            },
            "atlas_contract_mismatch": {
                "phase": {"local_storage": {"state": "configured_not_effective"}}
            },
        }
        atlas_trace = {
            "schema_version": 1,
            "object_kind_census": essential_summary["atlas_object_kind_census"],
            "wms_storage_binding_map": essential_summary["atlas_wms_storage_binding_map"],
            "binding_unresolved_ledger": essential_summary["atlas_binding_unresolved_ledger"],
            "control_binding_map": essential_summary["atlas_control_binding_map"],
            "object_closure": essential_summary["atlas_object_closure"],
            "schema_registry": essential_summary["atlas_schema_registry"],
            "contract_mismatch": {
                "phase": {"local_storage": {"state": "configured_not_effective"}}
            },
        }

        if summary_overrides:
            essential_summary.update(summary_overrides)
        if trace_overrides:
            atlas_trace.update(trace_overrides)

        (run_dir / "effective_config.json").write_text(
            json.dumps(effective_config),
            encoding="utf-8",
        )
        (run_dir / "essential_summary_mesh.json").write_text(
            json.dumps(essential_summary),
            encoding="utf-8",
        )
        (run_dir / "atlas_activation_trace.json").write_text(
            json.dumps(atlas_trace),
            encoding="utf-8",
        )
        (run_dir / "validation.log").write_text(
            "[val] SUMMARY run_dir=/tmp/case fail=0 warn=1 strict=0\n",
            encoding="utf-8",
        )
