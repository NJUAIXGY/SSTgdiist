import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_qualification_index.py"


def _load_module():
    if not SCRIPT_PATH.exists():
        raise AssertionError(f"missing script: {SCRIPT_PATH}")
    module_spec = importlib.util.spec_from_file_location(
        "pe_object_machine_qualification_index",
        SCRIPT_PATH,
    )
    if module_spec is None or module_spec.loader is None:
        raise AssertionError(f"failed to load module spec from {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


class MakeQualificationIndexTest(unittest.TestCase):
    def test_script_exists(self):
        self.assertTrue(SCRIPT_PATH.exists(), f"missing script: {SCRIPT_PATH}")

    def test_builds_index_and_writes_per_case_snapshots(self):
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            experiment_dir = root / "exp"
            cases_path = experiment_dir / "cases.json"
            cases_path.parent.mkdir(parents=True, exist_ok=True)

            case_a = experiment_dir / "runs" / "case_a" / "20260416-000000"
            case_b = experiment_dir / "runs" / "case_b" / "20260416-000000"
            case_a.mkdir(parents=True)
            case_b.mkdir(parents=True)
            (case_a.parent / "latest").symlink_to(case_a, target_is_directory=True)
            (case_b.parent / "latest").symlink_to(case_b, target_is_directory=True)
            self._write_case_artifacts(
                case_a,
                warn=0,
                unresolved_edges_count=0,
                unresolved_reason="none",
                shared_weight_formalization_state="runtime_owner_exact",
            )
            self._write_case_artifacts(
                case_b,
                warn=1,
                unresolved_edges_count=3,
                unresolved_reason="shared weight remains overlay-only",
                shared_weight_formalization_state="semantic_overlay_unresolved",
            )

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
                            },
                            {
                                "id": "case_b",
                                "label": "Case B",
                                "run_dir": "runs/case_b/latest",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = experiment_dir / "snapshot" / "qualification_index.json"
            snapshot_dir = experiment_dir / "snapshot" / "cases"
            rc = module.main(
                [
                    "--cases",
                    str(cases_path),
                    "--out",
                    str(out_path),
                    "--snapshot-dir",
                    str(snapshot_dir),
                ]
            )

            self.assertEqual(rc, 0)
            self.assertTrue(out_path.exists())
            self.assertTrue((snapshot_dir / "case_a.object_machine_snapshot.json").exists())
            self.assertTrue((snapshot_dir / "case_b.object_machine_snapshot.json").exists())

            index = json.loads(out_path.read_text(encoding="utf-8"))
            self.assertEqual(index["experiment_id"], "pe_object_machine_qualification_v1")
            self.assertEqual(index["baseline_case"], "case_a")
            self.assertEqual(index["summary"]["case_count"], 2)
            self.assertEqual(index["summary"]["gate_status_counts"]["clean"], 1)
            self.assertEqual(index["summary"]["gate_status_counts"]["warn"], 1)
            self.assertEqual(index["summary"]["unresolved_binding_edges_total"], 3)

            by_case = {entry["id"]: entry for entry in index["cases"]}
            self.assertEqual(by_case["case_a"]["gate"]["status"], "clean")
            self.assertEqual(by_case["case_b"]["gate"]["status"], "warn")
            self.assertEqual(
                by_case["case_b"]["closure"]["rowindex_object"]["contract_phase_state"],
                "aligned_active",
            )
            self.assertEqual(
                by_case["case_b"]["storage"]["shared_weight_residency"]["formalization_state"],
                "semantic_overlay_unresolved",
            )
            self.assertEqual(by_case["case_b"]["unresolved_binding_edges_total"], 3)
            self.assertIn(
                "shared weight remains overlay-only",
                by_case["case_b"]["gate"]["blockers"],
            )

    @staticmethod
    def _write_case_artifacts(
        run_dir: Path,
        *,
        warn: int,
        unresolved_edges_count: int,
        unresolved_reason: str,
        shared_weight_formalization_state: str,
    ) -> None:
        effective_config = {
            "noc_type": "multicast_mesh",
            "local_storage_enable": 1,
            "pulse": {
                "enable": 1,
                "osa_enable": 1,
                "osa_shared_weight_owner_enable": 1,
                "osa_shared_weight_owner_actual_enable": 1
                if shared_weight_formalization_state == "runtime_owner_exact"
                else 0,
            },
        }
        atlas_trace = {
            "schema_version": 1,
            "object_kind_census": {
                "matrix_version": 2,
                "objects": {
                    "shared_weight_residency": {
                        "scope": "P-scope",
                        "state": "active",
                    }
                },
                "summary": {"active_count": 1},
            },
            "wms_storage_binding_map": {
                "version": 2,
                "vocabulary": "atlas_wms_storage_binding_map_v2",
                "entries": {
                    "shared_weight_residency": {
                        "authority_state": "actual_owner",
                        "binding_state": "semantic_overlay_only"
                        if unresolved_edges_count
                        else "runtime_owner_exact",
                        "formalization_state": shared_weight_formalization_state,
                        "runtime_owner": "PulseSeededLineResidency",
                    }
                },
                "summary": {},
            },
            "binding_unresolved_ledger": {
                "version": 1,
                "vocabulary": "atlas_binding_unresolved_ledger_v1",
                "entries": {}
                if not unresolved_edges_count
                else {
                    "shared_weight_residency": {
                        "formalization_state": shared_weight_formalization_state,
                        "reason": unresolved_reason,
                        "unresolved_edges": ["edge"] * unresolved_edges_count,
                        "unresolved_edges_count": unresolved_edges_count,
                    }
                },
                "summary": {},
            },
            "control_binding_map": {
                "version": 1,
                "vocabulary": "atlas_control_binding_map_v1",
                "entries": {
                    "sync_barrier": {
                        "formalization_state": "sync_gate_visible",
                        "lifecycle_contract": "ready_to_commit_gate",
                        "commit_relation": "service_ready_commit_blocked",
                        "runtime_owner": "RetireSyncPath",
                    }
                },
                "summary": {},
            },
            "object_closure": {
                "version": 1,
                "vocabulary": "atlas_object_closure_v1",
                "entries": {
                    "rowindex_object": {
                        "authority_state": "absent",
                        "coverage_status": "build_on_both_planes_dark",
                        "contract_phase_state": "aligned_active",
                        "machine_reason": "rowindex object plane remains dark",
                    },
                    "idx2_object": {
                        "authority_state": "absent",
                        "coverage_status": "runtime_visible_object_dark",
                        "contract_phase_state": "aligned_active",
                        "machine_reason": "idx2 object plane remains dark",
                    },
                    "preband_object": {
                        "authority_state": "absent",
                        "coverage_status": "runtime_visible_object_dark",
                        "contract_phase_state": "aligned_active",
                        "machine_reason": "preband object plane remains dark",
                    },
                },
            },
            "schema_registry": {
                "version": 1,
                "vocabulary": "atlas_schema_registry_v1",
                "views": {
                    "object_closure": {
                        "vocabulary": "atlas_object_closure_v1",
                        "version": 1,
                    },
                    "wms_storage_binding_map": {
                        "vocabulary": "atlas_wms_storage_binding_map_v2",
                        "version": 2,
                    },
                    "binding_unresolved_ledger": {
                        "vocabulary": "atlas_binding_unresolved_ledger_v1",
                        "version": 1,
                    },
                },
            },
        }

        (run_dir / "effective_config.json").write_text(
            json.dumps(effective_config),
            encoding="utf-8",
        )
        (run_dir / "essential_summary_mesh.json").write_text(
            json.dumps({}),
            encoding="utf-8",
        )
        (run_dir / "atlas_activation_trace.json").write_text(
            json.dumps(atlas_trace),
            encoding="utf-8",
        )
        (run_dir / "validation.log").write_text(
            f"[val] SUMMARY run_dir=/tmp/case fail=0 warn={warn} strict=0\n",
            encoding="utf-8",
        )
