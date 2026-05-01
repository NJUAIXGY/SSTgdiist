import json
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_snapshot.py"
_MODULE_SPEC = importlib.util.spec_from_file_location(
    "atlas_service_rowindex_make_snapshot",
    SCRIPT_PATH,
)
if _MODULE_SPEC is None or _MODULE_SPEC.loader is None:
    raise RuntimeError(f"failed to load module spec from {SCRIPT_PATH}")
MAKE_SNAPSHOT = importlib.util.module_from_spec(_MODULE_SPEC)
_MODULE_SPEC.loader.exec_module(MAKE_SNAPSHOT)


class MakeSnapshotTest(unittest.TestCase):
    def test_main_refreshes_runs_before_snapshot_when_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 0.0},
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 0.0},
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            refresh_calls: list[tuple[Path, Path]] = []

            def _fake_refresh(run_dir: Path, project_root: Path) -> None:
                refresh_calls.append((run_dir, project_root))

            with mock.patch.object(
                MAKE_SNAPSHOT,
                "_refresh_run_artifacts",
                side_effect=_fake_refresh,
                create=True,
            ):
                rc = MAKE_SNAPSHOT.main(
                    [
                        "--cases",
                        str(cases_path),
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
                    (baseline_run.resolve(), SCRIPT_PATH.resolve().parents[3]),
                    (object_run.resolve(), SCRIPT_PATH.resolve().parents[3]),
                ],
            )

    def test_refresh_run_artifacts_rebuilds_summary_trace_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            run_dir.mkdir()
            project_root = root / "project"
            tools_dir = project_root / "sst_dram_si" / "tools"
            tools_dir.mkdir(parents=True)

            commands: list[list[str]] = []

            def _fake_run(
                cmd: list[str],
                *,
                check: bool = False,
                capture_output: bool = False,
                text: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                commands.append(cmd)
                if cmd[1].endswith("validate_essential_summary_mesh.py"):
                    self.assertFalse(check)
                    self.assertTrue(capture_output)
                    self.assertTrue(text)
                    return subprocess.CompletedProcess(
                        cmd,
                        0,
                        stdout="[val] SUMMARY run_dir=/tmp/run fail=0 warn=1 strict=0\n",
                        stderr="",
                    )
                self.assertTrue(check)
                self.assertFalse(capture_output)
                return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

            with mock.patch("subprocess.run", side_effect=_fake_run):
                MAKE_SNAPSHOT._refresh_run_artifacts(run_dir.resolve(), project_root.resolve())

            self.assertEqual(
                commands,
                [
                    [
                        "python3",
                        str(tools_dir / "compute_essential_summary_mesh.py"),
                        "--run-dir",
                        str(run_dir.resolve()),
                    ],
                    [
                        "python3",
                        str(tools_dir / "summarize_atlas_activation_trace.py"),
                        "--run-dir",
                        str(run_dir.resolve()),
                    ],
                    [
                        "python3",
                        str(tools_dir / "validate_essential_summary_mesh.py"),
                        "--run-dir",
                        str(run_dir.resolve()),
                    ],
                ],
            )
            self.assertEqual(
                (run_dir / "validation.log").read_text(encoding="utf-8"),
                "[val] SUMMARY run_dir=/tmp/run fail=0 warn=1 strict=0\n",
            )

    def test_generates_compare_tsv_with_atlas_service_and_rowindex_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={
                    "rowidx_touch_rows_total": 12.0,
                    "rowidx_prefetch_rows_total": 8.0,
                    "rowidx_prefetch_coverage": 2.0 / 3.0,
                    "rowidx_ready_signal_rowindex_response_total": 2.0,
                    "rowidx_ready_transition_rowindex_response_total": 2.0,
                    "rowidx_ready_signal_prefetch_response_total": 1.0,
                    "rowidx_ready_transition_prefetch_response_total": 1.0,
                    "rowidx_ready_signal_rowindex_response_inflight_waiters_total": 1.0,
                    "rowidx_ready_transition_rowindex_response_inflight_waiters_total": 1.0,
                    "rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total": 1.0,
                    "rowidx_ready_transition_rowindex_response_inflight_zero_waiters_total": 1.0,
                    "rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total": 0.0,
                    "rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total": 0.0,
                    "rowidx_ready_signal_prefetch_response_inflight_waiters_total": 1.0,
                    "rowidx_ready_transition_prefetch_response_inflight_waiters_total": 1.0,
                    "rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total": 0.0,
                    "rowidx_ready_transition_prefetch_response_inflight_zero_waiters_total": 0.0,
                    "rowidx_ready_signal_prefetch_response_noninflight_prefetch_only_total": 0.0,
                    "rowidx_ready_transition_prefetch_response_noninflight_prefetch_only_total": 0.0,
                    "rowidx_ready_signal_generic_coalesced_response_total": 1.0,
                    "rowidx_ready_transition_generic_coalesced_response_total": 1.0,
                    "rowidx_bulk_fill_total": 4.0,
                    "rowidx_bulk_rows_cached_total": 3.0,
                    "rowidx_bulk_waiters_resolved_total": 2.0,
                    "rowidx_close_attempt_already_pending_total": 2.0,
                },
                atlas_service={
                    "atlas_service_enabled": 1.0,
                    "atlas_service_owner_form_total": 2.0,
                    "atlas_service_join_live_total": 1.0,
                    "atlas_service_ready_transition_total": 0.0,
                    "atlas_service_released_total": 0.0,
                    "atlas_service_atlas_obj_ready_total": 0.0,
                    "atlas_service_atlas_obj_release_total": 0.0,
                    "atlas_service_private_only_share": 0.0,
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={
                    "rowidx_touch_rows_total": 12.0,
                    "rowidx_prefetch_rows_total": 8.0,
                    "rowidx_prefetch_coverage": 2.0 / 3.0,
                    "rowidx_ready_signal_rowindex_response_total": 5.0,
                    "rowidx_ready_transition_rowindex_response_total": 4.0,
                    "rowidx_ready_signal_prefetch_response_total": 2.0,
                    "rowidx_ready_transition_prefetch_response_total": 3.0,
                    "rowidx_ready_signal_rowindex_response_inflight_waiters_total": 2.0,
                    "rowidx_ready_transition_rowindex_response_inflight_waiters_total": 1.0,
                    "rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total": 2.0,
                    "rowidx_ready_transition_rowindex_response_inflight_zero_waiters_total": 2.0,
                    "rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total": 1.0,
                    "rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total": 1.0,
                    "rowidx_ready_signal_prefetch_response_inflight_waiters_total": 1.0,
                    "rowidx_ready_transition_prefetch_response_inflight_waiters_total": 1.0,
                    "rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total": 1.0,
                    "rowidx_ready_transition_prefetch_response_inflight_zero_waiters_total": 2.0,
                    "rowidx_ready_signal_prefetch_response_noninflight_prefetch_only_total": 0.0,
                    "rowidx_ready_transition_prefetch_response_noninflight_prefetch_only_total": 0.0,
                    "rowidx_ready_signal_generic_coalesced_response_total": 3.0,
                    "rowidx_ready_transition_generic_coalesced_response_total": 1.0,
                    "rowidx_bulk_fill_total": 10.0,
                    "rowidx_bulk_rows_cached_total": 8.0,
                    "rowidx_bulk_waiters_resolved_total": 6.0,
                    "rowidx_close_attempt_already_pending_total": 5.0,
                },
                atlas_service={
                    "atlas_service_enabled": 1.0,
                    "atlas_service_owner_form_total": 2.0,
                    "atlas_service_join_live_total": 1.0,
                    "atlas_service_ready_transition_total": 1.0,
                    "atlas_service_released_total": 1.0,
                    "atlas_service_atlas_obj_ready_total": 1.0,
                    "atlas_service_atlas_obj_release_total": 1.0,
                    "atlas_service_private_only_share": 0.0,
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertTrue(out_path.exists())

            rows = self._read_tsv(out_path)
            self.assertEqual(
                rows["atlas_service.atlas_service_ready_transition_total"],
                ["0.0", "1.0", "1.0"],
            )
            self.assertEqual(
                rows["atlas_service.atlas_service_released_total"],
                ["0.0", "1.0", "1.0"],
            )
            self.assertEqual(
                rows["atlas_service.atlas_service_atlas_obj_ready_total"],
                ["0.0", "1.0", "1.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_prefetch_rows_total"],
                ["8.0", "8.0", "0.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_signal_rowindex_response_total"],
                ["2.0", "5.0", "3.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_transition_rowindex_response_total"],
                ["2.0", "4.0", "2.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_transition_prefetch_response_total"],
                ["1.0", "3.0", "2.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_signal_rowindex_response_inflight_waiters_total"],
                ["1.0", "2.0", "1.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_transition_rowindex_response_inflight_waiters_total"],
                ["1.0", "1.0", "0.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total"],
                ["1.0", "2.0", "1.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_transition_rowindex_response_inflight_zero_waiters_total"],
                ["1.0", "2.0", "1.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total"],
                ["0.0", "1.0", "1.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total"],
                ["0.0", "1.0", "1.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_signal_prefetch_response_inflight_waiters_total"],
                ["1.0", "1.0", "0.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_transition_prefetch_response_inflight_zero_waiters_total"],
                ["0.0", "2.0", "2.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_signal_generic_coalesced_response_total"],
                ["1.0", "3.0", "2.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_ready_transition_generic_coalesced_response_total"],
                ["1.0", "1.0", "0.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_bulk_fill_total"],
                ["4.0", "10.0", "6.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_bulk_rows_cached_total"],
                ["3.0", "8.0", "5.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_bulk_waiters_resolved_total"],
                ["2.0", "6.0", "4.0"],
            )
            self.assertEqual(
                rows["noc_mem_joint.rowidx_close_attempt_already_pending_total"],
                ["2.0", "5.0", "3.0"],
            )

    def test_generates_compare_tsv_with_proxy_shadow_derived_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={
                    "rowidx_touch_rows_total": 4.0,
                    "rowidx_prefetch_rows_total": 3.0,
                },
                atlas_service={
                    "atlas_service_enabled": 1.0,
                    "atlas_service_atlas_obj_materialize_total": 0.0,
                    "atlas_service_atlas_obj_ready_total": 0.0,
                    "atlas_service_atlas_obj_release_total": 0.0,
                },
                pulse={
                    "pulse_prebase_lookup_owner_fill_total": 2.0,
                    "pulse_prebase_lookup_shared_hits_total": 3.0,
                    "pulse_descriptor_total": 3.0,
                    "pulse_shared_service_hits_total": 1.0,
                    "pulse_shared_service_misses_total": 2.0,
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={
                    "rowidx_touch_rows_total": 12.0,
                    "rowidx_prefetch_rows_total": 5.0,
                },
                atlas_service={
                    "atlas_service_enabled": 1.0,
                    "atlas_service_atlas_obj_materialize_total": 1.0,
                    "atlas_service_atlas_obj_ready_total": 1.0,
                    "atlas_service_atlas_obj_release_total": 1.0,
                },
                pulse={
                    "pulse_prebase_lookup_owner_fill_total": 6.0,
                    "pulse_prebase_lookup_shared_hits_total": 9.0,
                    "pulse_descriptor_total": 9.0,
                    "pulse_shared_service_hits_total": 5.0,
                    "pulse_shared_service_misses_total": 4.0,
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["pulse.pulse_prebase_lookup_owner_fill_total"],
                ["2.0", "6.0", "4.0"],
            )
            self.assertEqual(
                rows["pulse.pulse_shared_service_hits_total"],
                ["1.0", "5.0", "4.0"],
            )
            self.assertEqual(
                rows["derived.proxy_shadow.prebase_proxy_activity_total"],
                ["5.0", "15.0", "10.0"],
            )
            self.assertEqual(
                rows["derived.proxy_shadow.rowindex_shadow_activity_total"],
                ["4.0", "12.0", "8.0"],
            )
            self.assertEqual(
                rows["derived.proxy_shadow.descriptor_proxy_activity_total"],
                ["3.0", "9.0", "6.0"],
            )
            self.assertEqual(
                rows["derived.proxy_shadow.prebase_proxy_to_materialize_gap"],
                ["5.0", "14.0", "9.0"],
            )
            self.assertEqual(
                rows["derived.proxy_shadow.rowindex_shadow_to_materialize_gap"],
                ["4.0", "11.0", "7.0"],
            )
    def test_generates_compare_tsv_with_atlas_object_lifecycle_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_object_lifecycle={
                    "metadata_unique_object_total": 10.0,
                    "owner_alloc_total": 5.0,
                    "service_owner_form_total": 1.0,
                    "service_ready_total": 3.0,
                    "service_release_total": 2.0,
                    "unique_to_owner_gap_total": 0.5,
                    "owner_to_service_gap_total": 0.75,
                    "service_to_ready_gap_total": 0.25,
                    "ready_to_release_gap_total": 0.1,
                    "premphf_band": {
                        "metadata_duplicate_consumer_total": 7.0,
                        "owner_reject_total": 1.0,
                    },
                    "rowindex": {
                        "join_request_total": 4.0,
                        "join_request_to_grant_gap_total": 0.2,
                        "owner_active_entries_peak_total": 10.0,
                    },
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_object_lifecycle={
                    "metadata_unique_object_total": 20.0,
                    "owner_alloc_total": 10.0,
                    "service_owner_form_total": 2.0,
                    "service_ready_total": 4.0,
                    "service_release_total": 3.0,
                    "unique_to_owner_gap_total": 1.0,
                    "owner_to_service_gap_total": 1.25,
                    "service_to_ready_gap_total": 0.75,
                    "ready_to_release_gap_total": 0.2,
                    "premphf_band": {
                        "metadata_duplicate_consumer_total": 14.0,
                        "owner_reject_total": 2.0,
                    },
                    "rowindex": {
                        "join_request_total": 8.0,
                        "join_request_to_grant_gap_total": 0.4,
                        "owner_active_entries_peak_total": 15.0,
                    },
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_object_lifecycle.metadata_unique_object_total"],
                ["10.0", "20.0", "10.0"],
            )
            self.assertEqual(
                rows["atlas_object_lifecycle.owner_alloc_total"],
                ["5.0", "10.0", "5.0"],
            )
            self.assertEqual(
                rows["atlas_object_lifecycle.unique_to_owner_gap_total"],
                ["0.5", "1.0", "0.5"],
            )
            self.assertEqual(
                rows["atlas_object_lifecycle.owner_to_service_gap_total"],
                ["0.75", "1.25", "0.5"],
            )
            self.assertEqual(
                rows["atlas_object_lifecycle.service_to_ready_gap_total"],
                ["0.25", "0.75", "0.5"],
            )
            self.assertEqual(
                rows["atlas_object_lifecycle.ready_to_release_gap_total"],
                ["0.1", "0.2", "0.1"],
            )
            self.assertEqual(
                rows["atlas_object_lifecycle.premphf_band.metadata_duplicate_consumer_total"],
                ["7.0", "14.0", "7.0"],
            )
            self.assertEqual(
                rows["atlas_object_lifecycle.premphf_band.owner_reject_total"],
                ["1.0", "2.0", "1.0"],
            )
            self.assertEqual(
                rows["atlas_object_lifecycle.rowindex.join_request_total"],
                ["4.0", "8.0", "4.0"],
            )
            self.assertEqual(
                rows["atlas_object_lifecycle.rowindex.join_request_to_grant_gap_total"],
                ["0.2", "0.4", "0.2"],
            )
            self.assertEqual(
                rows["atlas_object_lifecycle.rowindex.owner_active_entries_peak_total"],
                ["10.0", "15.0", "5.0"],
            )

    def test_generates_compare_tsv_with_atlas_machine_facet_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_proxy={
                    "idx2row": {"materialize_total": 0.0},
                    "premphf_base": {"shared_hit_total": 0.0},
                    "rowindex": {"materialize_total": 4.0},
                },
                atlas_fabric={
                    "ingress_packets_total": 20.0,
                    "control_messages_enqueued_total": 5.0,
                },
                atlas_storage={
                    "idx_reads_total": 12.0,
                    "idx_bank_conflict_ticks_total": 3.0,
                    "l0_reads_total": 8.0,
                    "l0_fill_total": 4.0,
                },
                atlas_sync={
                    "retire_ready_but_blocked_edges_total": 6.0,
                    "retire_wait_cycles_total": 12.0,
                    "retire_wait_cycles_due_to_barrier_total": 3.0,
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9800.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_proxy={
                    "idx2row": {"materialize_total": 3.0},
                    "premphf_base": {"shared_hit_total": 6.0},
                    "rowindex": {"materialize_total": 7.0},
                },
                atlas_fabric={
                    "ingress_packets_total": 24.0,
                    "control_messages_enqueued_total": 12.0,
                },
                atlas_storage={
                    "idx_reads_total": 18.0,
                    "idx_bank_conflict_ticks_total": 9.0,
                    "l0_reads_total": 10.0,
                    "l0_fill_total": 7.0,
                },
                atlas_sync={
                    "retire_ready_but_blocked_edges_total": 10.0,
                    "retire_wait_cycles_total": 20.0,
                    "retire_wait_cycles_due_to_barrier_total": 8.0,
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_proxy.idx2row.materialize_total"],
                ["0.0", "3.0", "3.0"],
            )
            self.assertEqual(
                rows["atlas_proxy.premphf_base.shared_hit_total"],
                ["0.0", "6.0", "6.0"],
            )
            self.assertEqual(
                rows["atlas_fabric.control_messages_enqueued_total"],
                ["5.0", "12.0", "7.0"],
            )
            self.assertEqual(
                rows["atlas_storage.idx_bank_conflict_ticks_total"],
                ["3.0", "9.0", "6.0"],
            )
            self.assertEqual(
                rows["atlas_sync.retire_wait_cycles_due_to_barrier_total"],
                ["3.0", "8.0", "5.0"],
            )
            self.assertEqual(
                rows["derived.machine.proxy_activity_total"],
                ["4.0", "16.0", "12.0"],
            )
            self.assertEqual(
                rows["derived.machine.fabric_control_per_ingress"],
                ["0.25", "0.5", "0.25"],
            )
            self.assertEqual(
                rows["derived.machine.storage_conflict_per_read"],
                ["0.15", "0.32142857142857145", "0.17142857142857146"],
            )
            self.assertEqual(
                rows["derived.machine.sync_barrier_wait_share"],
                ["0.25", "0.4", "0.15000000000000002"],
            )

    def test_generates_compare_tsv_with_new_machine_model_planes_and_gap_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_proxy={
                    "idx2row": {
                        "materialize_total": 0.0,
                        "ready_total": 0.0,
                        "release_total": 0.0,
                    },
                },
                atlas_fabric={
                    "ingress_packets_total": 20.0,
                },
                atlas_storage={
                    "idx_reads_total": 12.0,
                    "idx_bank_conflict_ticks_total": 3.0,
                    "l0_reads_total": 8.0,
                },
                atlas_sync={
                    "retire_wait_cycles_total": 12.0,
                    "retire_wait_cycles_due_to_barrier_total": 3.0,
                },
                atlas_lookup={
                    "premphf_base": {
                        "runtime_owner_fill_total": 2.0,
                        "runtime_shared_hit_total": 3.0,
                        "runtime_activity_total": 5.0,
                        "runtime_to_lookup_ready_gap_total": 5.0,
                        "runtime_to_materialize_gap_total": 5.0,
                    },
                },
                atlas_shadow={
                    "rowindex": {
                        "runtime_touch_rows_total": 4.0,
                        "runtime_prefetch_rows_total": 3.0,
                        "runtime_prefetch_rows_deferred_total": 1.0,
                        "runtime_prefetch_rows_failed_total": 0.0,
                        "runtime_ready_signal_generic_coalesced_response_total": 2.0,
                        "runtime_ready_transition_generic_coalesced_response_total": 1.0,
                        "runtime_bulk_fill_total": 5.0,
                        "runtime_bulk_rows_cached_total": 4.0,
                        "runtime_bulk_waiters_resolved_total": 3.0,
                        "runtime_cache_hits_total": 2.0,
                        "runtime_cache_misses_total": 2.0,
                        "runtime_cache_fills_total": 1.0,
                        "runtime_cache_full_drop_total": 0.0,
                        "runtime_shadow_activity_total": 4.0,
                        "runtime_shadow_to_materialize_gap_total": 4.0,
                        "runtime_prefetch_coverage": 0.75,
                        "runtime_cache_hit_rate": 0.5,
                    },
                },
                atlas_control={
                    "messages_enqueued_total": 5.0,
                    "ready_fanout_total": 1.0,
                    "entries_peak": 2.0,
                    "backlog_cycles_total": 9.0,
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9800.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_proxy={
                    "idx2row": {
                        "materialize_total": 3.0,
                        "ready_total": 1.0,
                        "release_total": 1.0,
                    },
                },
                atlas_fabric={
                    "ingress_packets_total": 24.0,
                },
                atlas_storage={
                    "idx_reads_total": 18.0,
                    "idx_bank_conflict_ticks_total": 9.0,
                    "l0_reads_total": 10.0,
                },
                atlas_sync={
                    "retire_wait_cycles_total": 20.0,
                    "retire_wait_cycles_due_to_barrier_total": 8.0,
                },
                atlas_lookup={
                    "premphf_base": {
                        "runtime_owner_fill_total": 6.0,
                        "runtime_shared_hit_total": 9.0,
                        "runtime_activity_total": 15.0,
                        "runtime_to_lookup_ready_gap_total": 13.0,
                        "runtime_to_materialize_gap_total": 9.0,
                    },
                },
                atlas_shadow={
                    "rowindex": {
                        "runtime_touch_rows_total": 12.0,
                        "runtime_prefetch_rows_total": 5.0,
                        "runtime_prefetch_rows_deferred_total": 2.0,
                        "runtime_prefetch_rows_failed_total": 1.0,
                        "runtime_ready_signal_generic_coalesced_response_total": 7.0,
                        "runtime_ready_transition_generic_coalesced_response_total": 3.0,
                        "runtime_bulk_fill_total": 12.0,
                        "runtime_bulk_rows_cached_total": 10.0,
                        "runtime_bulk_waiters_resolved_total": 8.0,
                        "runtime_cache_hits_total": 7.0,
                        "runtime_cache_misses_total": 5.0,
                        "runtime_cache_fills_total": 3.0,
                        "runtime_cache_full_drop_total": 1.0,
                        "runtime_shadow_activity_total": 12.0,
                        "runtime_shadow_to_materialize_gap_total": 5.0,
                        "runtime_prefetch_coverage": 5.0 / 12.0,
                        "runtime_cache_hit_rate": 7.0 / 12.0,
                    },
                },
                atlas_control={
                    "messages_enqueued_total": 12.0,
                    "ready_fanout_total": 3.0,
                    "entries_peak": 6.0,
                    "backlog_cycles_total": 14.0,
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_lookup.premphf_base.runtime_activity_total"],
                ["5.0", "15.0", "10.0"],
            )
            self.assertEqual(
                rows["atlas_lookup.premphf_base.runtime_to_lookup_ready_gap_total"],
                ["5.0", "13.0", "8.0"],
            )
            self.assertEqual(
                rows["atlas_lookup.premphf_base.runtime_to_materialize_gap_total"],
                ["5.0", "9.0", "4.0"],
            )
            self.assertEqual(
                rows["atlas_shadow.rowindex.runtime_shadow_activity_total"],
                ["4.0", "12.0", "8.0"],
            )
            self.assertEqual(
                rows["atlas_shadow.rowindex.runtime_prefetch_rows_deferred_total"],
                ["1.0", "2.0", "1.0"],
            )
            self.assertEqual(
                rows["atlas_shadow.rowindex.runtime_cache_hits_total"],
                ["2.0", "7.0", "5.0"],
            )
            self.assertEqual(
                rows["atlas_shadow.rowindex.runtime_ready_signal_generic_coalesced_response_total"],
                ["2.0", "7.0", "5.0"],
            )
            self.assertEqual(
                rows["atlas_shadow.rowindex.runtime_ready_transition_generic_coalesced_response_total"],
                ["1.0", "3.0", "2.0"],
            )
            self.assertEqual(
                rows["atlas_shadow.rowindex.runtime_bulk_fill_total"],
                ["5.0", "12.0", "7.0"],
            )
            self.assertEqual(
                rows["atlas_shadow.rowindex.runtime_bulk_rows_cached_total"],
                ["4.0", "10.0", "6.0"],
            )
            self.assertEqual(
                rows["atlas_shadow.rowindex.runtime_bulk_waiters_resolved_total"],
                ["3.0", "8.0", "5.0"],
            )
            self.assertEqual(
                rows["atlas_shadow.rowindex.runtime_shadow_to_materialize_gap_total"],
                ["4.0", "5.0", "1.0"],
            )
            self.assertEqual(
                rows["atlas_control.messages_enqueued_total"],
                ["5.0", "12.0", "7.0"],
            )
            self.assertEqual(
                rows["atlas_control.entries_peak"],
                ["2.0", "6.0", "4.0"],
            )
            self.assertEqual(
                rows["atlas_control.backlog_cycles_total"],
                ["9.0", "14.0", "5.0"],
            )
            self.assertEqual(
                rows["derived.machine.lookup_activity_total"],
                ["5.0", "15.0", "10.0"],
            )
            self.assertEqual(
                rows["derived.machine.shadow_activity_total"],
                ["4.0", "12.0", "8.0"],
            )
            self.assertEqual(
                rows["derived.machine.control_activity_total"],
                ["5.0", "12.0", "7.0"],
            )
            self.assertEqual(
                rows["derived.machine.proxy_lifecycle_total"],
                ["0.0", "5.0", "5.0"],
            )
            self.assertEqual(
                rows["derived.machine.activity_plane_gap_total"],
                ["9.0", "22.0", "13.0"],
            )
            self.assertEqual(
                rows["derived.machine.lookup_materialize_gap_total"],
                ["5.0", "9.0", "4.0"],
            )
            self.assertEqual(
                rows["derived.machine.shadow_materialize_gap_total"],
                ["4.0", "5.0", "1.0"],
            )

    def test_generates_compare_tsv_with_atlas_storage_object_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_storage={
                    "pod_metadata_observe_total": 10.0,
                    "pod_metadata_overlap_hit_total": 3.0,
                    "pod_metadata": {
                        "premphf_base": {"observe_total": 5.0},
                        "premphf_band": {"observe_total": 1.0},
                        "rowindex": {"observe_total": 2.0},
                    },
                    "pod_owner_owner_alloc_total": 7.0,
                    "pod_owner_join_grant_total": 9.0,
                    "pod_owner": {
                        "premphf_band": {"owner_alloc_total": 4.0},
                        "rowindex": {"join_grant_total": 3.0},
                    },
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9800.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_storage={
                    "pod_metadata_observe_total": 15.0,
                    "pod_metadata_overlap_hit_total": 5.0,
                    "pod_metadata": {
                        "premphf_base": {"observe_total": 8.0},
                        "premphf_band": {"observe_total": 3.0},
                        "rowindex": {"observe_total": 4.0},
                    },
                    "pod_owner_owner_alloc_total": 11.0,
                    "pod_owner_join_grant_total": 13.0,
                    "pod_owner": {
                        "premphf_band": {"owner_alloc_total": 6.0},
                        "rowindex": {"join_grant_total": 5.0},
                    },
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_storage.pod_metadata_observe_total"],
                ["10.0", "15.0", "5.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_metadata_overlap_hit_total"],
                ["3.0", "5.0", "2.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_metadata.premphf_base.observe_total"],
                ["5.0", "8.0", "3.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_metadata.premphf_band.observe_total"],
                ["1.0", "3.0", "2.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_metadata.rowindex.observe_total"],
                ["2.0", "4.0", "2.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_owner_owner_alloc_total"],
                ["7.0", "11.0", "4.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_owner_join_grant_total"],
                ["9.0", "13.0", "4.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_owner.premphf_band.owner_alloc_total"],
                ["4.0", "6.0", "2.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_owner.rowindex.join_grant_total"],
                ["3.0", "5.0", "2.0"],
            )

    def test_generates_compare_tsv_with_atlas_storage_object_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_storage={
                    "pod_metadata_observe_total": 10.0,
                    "pod_metadata_overlap_hit_total": 3.0,
                    "pod_metadata": {
                        "premphf_base": {"observe_total": 5.0},
                        "premphf_band": {"observe_total": 1.0},
                        "rowindex": {"observe_total": 2.0},
                    },
                    "pod_owner_owner_alloc_total": 7.0,
                    "pod_owner_join_grant_total": 9.0,
                    "pod_owner": {
                        "premphf_band": {"owner_alloc_total": 4.0},
                        "rowindex": {"join_grant_total": 3.0},
                    },
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9800.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_storage={
                    "pod_metadata_observe_total": 15.0,
                    "pod_metadata_overlap_hit_total": 5.0,
                    "pod_metadata": {
                        "premphf_base": {"observe_total": 8.0},
                        "premphf_band": {"observe_total": 3.0},
                        "rowindex": {"observe_total": 4.0},
                    },
                    "pod_owner_owner_alloc_total": 11.0,
                    "pod_owner_join_grant_total": 13.0,
                    "pod_owner": {
                        "premphf_band": {"owner_alloc_total": 6.0},
                        "rowindex": {"join_grant_total": 5.0},
                    },
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_storage.pod_metadata_observe_total"],
                ["10.0", "15.0", "5.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_metadata_overlap_hit_total"],
                ["3.0", "5.0", "2.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_metadata.premphf_base.observe_total"],
                ["5.0", "8.0", "3.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_metadata.premphf_band.observe_total"],
                ["1.0", "3.0", "2.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_metadata.rowindex.observe_total"],
                ["2.0", "4.0", "2.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_owner_owner_alloc_total"],
                ["7.0", "11.0", "4.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_owner_join_grant_total"],
                ["9.0", "13.0", "4.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_owner.premphf_band.owner_alloc_total"],
                ["4.0", "6.0", "2.0"],
            )
            self.assertEqual(
                rows["atlas_storage.pod_owner.rowindex.join_grant_total"],
                ["3.0", "5.0", "2.0"],
            )

    def test_generates_compare_tsv_with_rowindex_object_closure_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_object_closure={
                    "entries": {
                        "rowindex_object": {
                            "requested": {"total": 0},
                            "constructed": {"total": 0},
                            "effective": {"total": 0},
                            "coverage_status": "runtime_visible_object_dark",
                            "effective_gap": False,
                            "effective_gap_cause": None,
                            "blocked_gates": [],
                        }
                    }
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_object_closure={
                    "entries": {
                        "rowindex_object": {
                            "requested": {"total": 1},
                            "constructed": {"total": 1},
                            "effective": {"total": 0},
                            "coverage_status": "object_and_runtime_visible",
                            "effective_gap": True,
                            "effective_gap_cause": "enable_state.rowindex_gate_metadata_txn",
                            "blocked_gates": [
                                "enable_state.rowindex_gate_metadata_txn"
                            ],
                        }
                    }
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_object_closure.entries.rowindex_object.requested.total"],
                ["0", "1", "1"],
            )
            self.assertEqual(
                rows["atlas_object_closure.entries.rowindex_object.constructed.total"],
                ["0", "1", "1"],
            )
            self.assertEqual(
                rows["atlas_object_closure.entries.rowindex_object.coverage_status"],
                ["runtime_visible_object_dark", "object_and_runtime_visible", "na"],
            )
            self.assertEqual(
                rows["atlas_object_closure.entries.rowindex_object.effective_gap"],
                ["0", "1", "1"],
            )
            self.assertEqual(
                rows["atlas_object_closure.entries.rowindex_object.effective_gap_cause"],
                ["0", "enable_state.rowindex_gate_metadata_txn", "na"],
            )
            self.assertEqual(
                rows["atlas_object_closure.entries.rowindex_object.blocked_gates_count"],
                ["0", "1", "1"],
            )

    def test_generates_compare_tsv_with_idx2_and_preband_object_closure_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_object_closure={
                    "entries": {
                        "idx2_object": {
                            "requested": {"total": 0},
                            "constructed": {"total": 0},
                            "effective": {"total": 0},
                            "coverage_status": "build_on_both_planes_dark",
                            "contract_phase_state": "configured_not_effective",
                            "probe_status": "observed_all_zero",
                            "blocked_gates": [],
                        },
                        "preband_object": {
                            "requested": {"total": 0},
                            "constructed": {"total": 0},
                            "effective": {"total": 0},
                            "coverage_status": "build_on_both_planes_dark",
                            "contract_phase_state": "configured_not_effective",
                            "probe_status": "observed_all_zero",
                            "blocked_gates": [],
                        },
                    }
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_object_closure={
                    "entries": {
                        "idx2_object": {
                            "requested": {"total": 1},
                            "constructed": {"total": 0},
                            "effective": {"total": 1},
                            "coverage_status": "object_and_runtime_visible",
                            "contract_phase_state": "configured_not_effective",
                            "probe_status": "observed_some_nonzero",
                            "blocked_gates": [],
                        },
                        "preband_object": {
                            "requested": {"total": 1},
                            "constructed": {"total": 0},
                            "effective": {"total": 1},
                            "coverage_status": "object_and_runtime_visible",
                            "contract_phase_state": "configured_not_effective",
                            "probe_status": "observed_some_nonzero",
                            "blocked_gates": [],
                        },
                    }
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_object_closure.entries.idx2_object.requested.total"],
                ["0", "1", "1"],
            )
            self.assertEqual(
                rows["atlas_object_closure.entries.idx2_object.effective.total"],
                ["0", "1", "1"],
            )
            self.assertEqual(
                rows["atlas_object_closure.entries.preband_object.coverage_status"],
                ["build_on_both_planes_dark", "object_and_runtime_visible", "na"],
            )
            self.assertEqual(
                rows["atlas_object_closure.entries.preband_object.probe_status"],
                ["observed_all_zero", "observed_some_nonzero", "na"],
            )

    def test_generates_compare_tsv_with_wms_binding_and_shared_weight_authority_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_storage_authority_map={
                    "entries": {
                        "shared_weight_residency": {
                            "authority_state": "absent",
                            "lifecycle_stage": "absent",
                            "formal_object_ref": "shared_weight_residency",
                        }
                    }
                },
                atlas_wms_storage_binding_map={
                    "version": 2,
                    "vocabulary": "atlas_wms_storage_binding_map_v2",
                    "entries": {
                        "weight_idx_store": {
                            "formalization_state": "scope_widened_private_runtime",
                        },
                        "shared_weight_residency": {
                            "binding_state": "absent",
                            "runtime_owner": "none",
                            "physical_scope": "no_formal_local_storage_contract",
                            "evict_contract_state": "absent",
                            "formalization_state": "absent",
                        },
                        "weight_value_store": {
                            "binding_state": "pe_named_per_core_runtime",
                            "semantic_overlay_owner": "none",
                            "release_contract_state": "runtime_owner_exact",
                            "formalization_state": "scope_widened_private_runtime",
                        },
                    }
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_storage_authority_map={
                    "entries": {
                        "shared_weight_residency": {
                            "authority_state": "mirror_only",
                            "lifecycle_stage": "mirror_only",
                            "formal_object_ref": "shared_weight_residency",
                        }
                    }
                },
                atlas_wms_storage_binding_map={
                    "version": 2,
                    "vocabulary": "atlas_wms_storage_binding_map_v2",
                    "entries": {
                        "weight_idx_store": {
                            "formalization_state": "scope_widened_private_runtime",
                        },
                        "shared_weight_residency": {
                            "binding_state": "semantic_overlay_only",
                            "runtime_owner": "PulseSeededLineResidency",
                            "physical_scope": "no_formal_local_storage_contract",
                            "evict_contract_state": "non_formal_overlay_unresolved",
                            "formalization_state": "semantic_overlay_unresolved",
                        },
                        "weight_value_store": {
                            "binding_state": "split_binding_object",
                            "semantic_overlay_owner": "PulseSeededLineResidency",
                            "release_contract_state": "split_runtime_unresolved",
                            "formalization_state": "split_binding_unresolved",
                        },
                    }
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_storage_authority_map.entries.shared_weight_residency.authority_state"],
                ["absent", "mirror_only", "na"],
            )
            self.assertEqual(
                rows["atlas_wms_storage_binding_map.entries.shared_weight_residency.binding_state"],
                ["absent", "semantic_overlay_only", "na"],
            )
            self.assertEqual(
                rows["atlas_wms_storage_binding_map.entries.weight_value_store.binding_state"],
                ["pe_named_per_core_runtime", "split_binding_object", "na"],
            )
            self.assertEqual(
                rows["atlas_wms_storage_binding_map.entries.weight_idx_store.formalization_state"],
                ["scope_widened_private_runtime", "scope_widened_private_runtime", "na"],
            )
            self.assertEqual(
                rows["atlas_wms_storage_binding_map.entries.weight_value_store.release_contract_state"],
                ["runtime_owner_exact", "split_runtime_unresolved", "na"],
            )
            self.assertEqual(
                rows["atlas_wms_storage_binding_map.entries.shared_weight_residency.physical_scope"],
                ["no_formal_local_storage_contract", "no_formal_local_storage_contract", "na"],
            )
            self.assertEqual(
                rows["atlas_wms_storage_binding_map.entries.shared_weight_residency.evict_contract_state"],
                ["absent", "non_formal_overlay_unresolved", "na"],
            )

    def test_generates_compare_tsv_with_schema_registry_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_schema_registry={
                    "version": 1,
                    "vocabulary": "atlas_schema_registry_v1",
                    "views": {
                        "atlas_object_closure": {"vocabulary": "atlas_object_closure_v1"},
                        "atlas_wms_storage_binding_map": {
                            "vocabulary": "atlas_wms_storage_binding_map_v2"
                        },
                    },
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_schema_registry={
                    "version": 1,
                    "vocabulary": "atlas_schema_registry_v1",
                    "views": {
                        "atlas_object_closure": {"vocabulary": "atlas_object_closure_v1"},
                        "atlas_wms_storage_binding_map": {
                            "vocabulary": "atlas_wms_storage_binding_map_v2"
                        },
                    },
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_schema_registry.version"],
                ["1", "1", "0"],
            )
            self.assertEqual(
                rows["atlas_schema_registry.vocabulary"],
                ["atlas_schema_registry_v1", "atlas_schema_registry_v1", "na"],
            )
            self.assertEqual(
                rows["atlas_schema_registry.views.atlas_object_closure.vocabulary"],
                ["atlas_object_closure_v1", "atlas_object_closure_v1", "na"],
            )
            self.assertEqual(
                rows["atlas_schema_registry.views.atlas_wms_storage_binding_map.vocabulary"],
                ["atlas_wms_storage_binding_map_v2", "atlas_wms_storage_binding_map_v2", "na"],
            )

    def test_generates_compare_tsv_with_binding_unresolved_ledger_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_binding_unresolved_ledger={
                    "entries": {
                        "weight_value_store": {
                            "formalization_state": "scope_widened_private_runtime",
                            "unresolved_edges_count": 1,
                        },
                        "shared_weight_residency": {
                            "formalization_state": "absent",
                            "unresolved_edges_count": 0,
                        },
                    }
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_binding_unresolved_ledger={
                    "entries": {
                        "weight_value_store": {
                            "formalization_state": "split_binding_unresolved",
                            "unresolved_edges_count": 3,
                        },
                        "shared_weight_residency": {
                            "formalization_state": "semantic_overlay_unresolved",
                            "unresolved_edges_count": 3,
                        },
                    }
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_binding_unresolved_ledger.entries.weight_value_store.formalization_state"],
                ["scope_widened_private_runtime", "split_binding_unresolved", "na"],
            )
            self.assertEqual(
                rows["atlas_binding_unresolved_ledger.entries.weight_value_store.unresolved_edges_count"],
                ["1", "3", "2"],
            )
            self.assertEqual(
                rows["atlas_binding_unresolved_ledger.entries.shared_weight_residency.formalization_state"],
                ["absent", "semantic_overlay_unresolved", "na"],
            )
            self.assertEqual(
                rows["atlas_binding_unresolved_ledger.entries.shared_weight_residency.unresolved_edges_count"],
                ["0", "3", "3"],
            )

    def test_generates_compare_tsv_with_control_binding_map_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_control_binding_map={
                    "entries": {
                        "rowdescriptor": {
                            "formalization_state": "proxy_descriptor_dark",
                            "object_role": "proxy_backed_descriptor",
                        },
                        "activation_ingress_store": {
                            "runtime_owner": "PulseIngressFabric",
                            "formalization_state": "ingress_runtime_dark",
                        },
                        "sync_barrier": {
                            "commit_relation": "fabric_absent",
                            "formalization_state": "sync_gate_dark",
                        },
                    }
                },
                atlas_schema_registry={
                    "version": 1,
                    "vocabulary": "atlas_schema_registry_v1",
                    "views": {
                        "atlas_control_binding_map": {
                            "vocabulary": "atlas_control_binding_map_v1"
                        },
                    },
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_control_binding_map={
                    "entries": {
                        "rowdescriptor": {
                            "formalization_state": "proxy_descriptor_visible",
                            "object_role": "proxy_backed_descriptor",
                        },
                        "activation_ingress_store": {
                            "runtime_owner": "PulseIngressFabric",
                            "formalization_state": "ingress_runtime_visible",
                        },
                        "sync_barrier": {
                            "commit_relation": "service_ready_commit_blocked",
                            "formalization_state": "sync_gate_visible",
                        },
                    }
                },
                atlas_schema_registry={
                    "version": 1,
                    "vocabulary": "atlas_schema_registry_v1",
                    "views": {
                        "atlas_control_binding_map": {
                            "vocabulary": "atlas_control_binding_map_v1"
                        },
                    },
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            rows = self._read_tsv(out_path)

            self.assertEqual(
                rows["atlas_control_binding_map.entries.rowdescriptor.formalization_state"],
                ["proxy_descriptor_dark", "proxy_descriptor_visible", "na"],
            )
            self.assertEqual(
                rows["atlas_control_binding_map.entries.rowdescriptor.object_role"],
                ["proxy_backed_descriptor", "proxy_backed_descriptor", "na"],
            )
            self.assertEqual(
                rows["atlas_control_binding_map.entries.activation_ingress_store.runtime_owner"],
                ["PulseIngressFabric", "PulseIngressFabric", "na"],
            )
            self.assertEqual(
                rows["atlas_control_binding_map.entries.activation_ingress_store.formalization_state"],
                ["ingress_runtime_dark", "ingress_runtime_visible", "na"],
            )
            self.assertEqual(
                rows["atlas_control_binding_map.entries.sync_barrier.commit_relation"],
                ["fabric_absent", "service_ready_commit_blocked", "na"],
            )
            self.assertEqual(
                rows["atlas_control_binding_map.entries.sync_barrier.formalization_state"],
                ["sync_gate_dark", "sync_gate_visible", "na"],
            )
            self.assertEqual(
                rows["atlas_schema_registry.views.atlas_control_binding_map.vocabulary"],
                ["atlas_control_binding_map_v1", "atlas_control_binding_map_v1", "na"],
            )

    def test_generates_canonical_gate_suite_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            required_views = {
                "atlas_object_closure": {"vocabulary": "atlas_object_closure_v1"},
                "atlas_storage_authority_map": {
                    "vocabulary": "atlas_storage_authority_map_v1"
                },
                "atlas_wms_storage_binding_map": {
                    "vocabulary": "atlas_wms_storage_binding_map_v2"
                },
                "atlas_binding_unresolved_ledger": {
                    "vocabulary": "atlas_binding_unresolved_ledger_v1"
                },
                "atlas_control_binding_map": {
                    "vocabulary": "atlas_control_binding_map_v1"
                },
            }

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_activation_census={
                    "activation_gate": {
                        "pulse_fabric_constructed": {"total": 0},
                        "service_table_constructed": {"total": 0},
                        "pod_metadata_plane_constructed": {"total": 0},
                        "pod_owner_table_constructed": {"total": 0},
                        "shared_weight_plane_constructed": {"total": 0},
                    }
                },
                atlas_object_closure={
                    "entries": {
                        "rowindex_object": {
                            "coverage_status": "build_off",
                            "constructed": {"total": 0},
                            "effective": {"total": 0},
                        }
                    }
                },
                atlas_control_commit_view={
                    "contract_state": "fabric_absent",
                },
                atlas_wms_storage_binding_map={
                    "entries": {
                        "shared_weight_residency": {
                            "binding_state": "absent",
                        }
                    }
                },
                atlas_binding_unresolved_ledger={
                    "entries": {
                        "weight_value_store": {
                            "formalization_state": "aligned_or_absent",
                            "unresolved_edges_count": 0,
                        },
                        "shared_weight_residency": {
                            "formalization_state": "absent",
                            "unresolved_edges_count": 0,
                        },
                    }
                },
                atlas_control_binding_map={
                    "entries": {
                        "rowdescriptor": {
                            "formalization_state": "proxy_descriptor_dark",
                        },
                        "activation_ingress_store": {
                            "formalization_state": "ingress_runtime_dark",
                        },
                        "sync_barrier": {
                            "formalization_state": "sync_gate_dark",
                        },
                    }
                },
                atlas_schema_registry={
                    "version": 1,
                    "vocabulary": "atlas_schema_registry_v1",
                    "views": required_views,
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_activation_census={
                    "activation_gate": {
                        "pulse_fabric_constructed": {"total": 1},
                        "service_table_constructed": {"total": 1},
                        "pod_metadata_plane_constructed": {"total": 1},
                        "pod_owner_table_constructed": {"total": 1},
                        "shared_weight_plane_constructed": {"total": 1},
                    }
                },
                atlas_object_closure={
                    "entries": {
                        "rowindex_object": {
                            "coverage_status": "object_and_runtime_visible",
                            "constructed": {"total": 1},
                            "effective": {"total": 1},
                        }
                    }
                },
                atlas_control_commit_view={
                    "contract_state": "service_ready_commit_blocked",
                },
                atlas_wms_storage_binding_map={
                    "entries": {
                        "shared_weight_residency": {
                            "binding_state": "semantic_overlay_only",
                        }
                    }
                },
                atlas_binding_unresolved_ledger={
                    "entries": {
                        "weight_value_store": {
                            "formalization_state": "split_binding_unresolved",
                            "unresolved_edges_count": 3,
                        },
                        "shared_weight_residency": {
                            "formalization_state": "semantic_overlay_unresolved",
                            "unresolved_edges_count": 3,
                        },
                    }
                },
                atlas_control_binding_map={
                    "entries": {
                        "rowdescriptor": {
                            "formalization_state": "proxy_descriptor_visible",
                        },
                        "activation_ingress_store": {
                            "formalization_state": "ingress_runtime_visible",
                        },
                        "sync_barrier": {
                            "formalization_state": "sync_gate_visible",
                        },
                    }
                },
                atlas_schema_registry={
                    "version": 1,
                    "vocabulary": "atlas_schema_registry_v1",
                    "views": required_views,
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            rows = self._read_tsv(out_path)
            self.assertEqual(
                rows["derived.gate.primary_gate"],
                ["fabric_absent", "rowindex_object_template_branch", "na"],
            )
            self.assertEqual(
                rows["derived.gate.m2c_entry_ready"],
                ["0", "0", "0"],
            )
            self.assertEqual(
                rows["derived.gate.m2c_blockers_count"],
                ["1", "1", "0"],
            )
            self.assertEqual(
                rows["derived.gate.unresolved_binding_objects_count"],
                ["0", "2", "2"],
            )

            gate_tsv = root / "snapshot" / "gate_summary.tsv"
            gate_json = root / "snapshot" / "gate_summary.json"
            self.assertTrue(gate_tsv.exists())
            self.assertTrue(gate_json.exists())

            gate_rows = self._read_gate_tsv(gate_tsv)
            self.assertEqual(
                gate_rows["rowindex_object_off"]["primary_gate"],
                "fabric_absent",
            )
            self.assertEqual(
                gate_rows["rowindex_object_on"]["primary_gate"],
                "rowindex_object_template_branch",
            )
            self.assertEqual(
                gate_rows["rowindex_object_on"]["m2c_entry_ready"],
                "0",
            )
            self.assertEqual(
                gate_rows["rowindex_object_off"]["m2c_blockers"],
                "fabric_absent",
            )
            self.assertEqual(
                gate_rows["rowindex_object_on"]["m2c_blockers"],
                "binding_unresolved_present",
            )

            gate_payload = json.loads(gate_json.read_text(encoding="utf-8"))
            self.assertEqual(
                gate_payload["cases"][0]["primary_gate"],
                "fabric_absent",
            )
            self.assertIn(
                "shared_weight_semantic_overlay_only",
                gate_payload["cases"][1]["gate_tags"],
            )
            self.assertIn(
                "binding_unresolved_present",
                gate_payload["cases"][1]["gate_tags"],
            )

    def test_canonical_gate_suite_surfaces_control_and_shared_weight_root_causes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            object_run = root / "rowindex_object_run"
            baseline_run.mkdir()
            object_run.mkdir()

            required_views = {
                "atlas_object_closure": {"vocabulary": "atlas_object_closure_v1"},
                "atlas_storage_authority_map": {
                    "vocabulary": "atlas_storage_authority_map_v1"
                },
                "atlas_wms_storage_binding_map": {
                    "vocabulary": "atlas_wms_storage_binding_map_v2"
                },
                "atlas_binding_unresolved_ledger": {
                    "vocabulary": "atlas_binding_unresolved_ledger_v1"
                },
                "atlas_control_binding_map": {
                    "vocabulary": "atlas_control_binding_map_v1"
                },
            }

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=10000.0,
                memory_requests=128.0,
                memctrl_req_total=128.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_activation_census={
                    "shared_weight": {
                        "dominant_absent_reason": {"label": "pulse_osa_gate"}
                    },
                    "machine_chain": {
                        "dominant_break": {
                            "label": "pulse_osa",
                            "stage": "build_effective",
                        }
                    },
                },
                atlas_object_closure={
                    "entries": {
                        "rowindex_object": {
                            "coverage_status": "build_off",
                            "constructed": {"total": 0},
                            "effective": {"total": 0},
                        }
                    }
                },
                atlas_control_commit_view={
                    "contract_state": "service_ready_commit_blocked",
                    "control_state": "fabric_absent",
                    "sync_state": "ready_visible_but_commit_blocked",
                },
                atlas_wms_storage_binding_map={
                    "entries": {
                        "shared_weight_residency": {
                            "binding_state": "absent",
                        }
                    }
                },
                atlas_binding_unresolved_ledger={
                    "entries": {
                        "weight_idx_store": {
                            "formalization_state": "scope_widened_private_runtime",
                            "unresolved_edges_count": 1,
                        },
                        "weight_value_store": {
                            "formalization_state": "scope_widened_private_runtime",
                            "unresolved_edges_count": 1,
                        },
                    }
                },
                atlas_control_binding_map={
                    "entries": {
                        "rowdescriptor": {
                            "formalization_state": "proxy_descriptor_dark",
                        },
                        "activation_ingress_store": {
                            "formalization_state": "ingress_runtime_dark",
                        },
                        "sync_barrier": {
                            "formalization_state": "sync_gate_visible",
                        },
                    }
                },
                atlas_schema_registry={
                    "version": 1,
                    "vocabulary": "atlas_schema_registry_v1",
                    "views": required_views,
                },
            )
            self._write_summary(
                object_run,
                sim_time_actual_ns=9950.0,
                memory_requests=120.0,
                memctrl_req_total=120.0,
                noc_mem_joint={},
                atlas_service={"atlas_service_enabled": 1.0},
                atlas_activation_census={
                    "shared_weight": {
                        "dominant_absent_reason": {"label": "owner_request_gate"}
                    },
                    "machine_chain": {
                        "dominant_break": {
                            "label": "shared_weight_owner",
                            "stage": "runtime_requested",
                        }
                    },
                },
                atlas_object_closure={
                    "entries": {
                        "rowindex_object": {
                            "coverage_status": "object_and_runtime_visible",
                            "constructed": {"total": 1},
                            "effective": {"total": 1},
                        }
                    }
                },
                atlas_control_commit_view={
                    "contract_state": "service_ready_commit_blocked",
                    "control_state": "queued_without_consume",
                    "sync_state": "ready_visible_but_commit_blocked",
                },
                atlas_wms_storage_binding_map={
                    "entries": {
                        "shared_weight_residency": {
                            "binding_state": "absent",
                        }
                    }
                },
                atlas_binding_unresolved_ledger={
                    "entries": {
                        "weight_idx_store": {
                            "formalization_state": "scope_widened_private_runtime",
                            "unresolved_edges_count": 1,
                        },
                        "weight_value_store": {
                            "formalization_state": "scope_widened_private_runtime",
                            "unresolved_edges_count": 1,
                        },
                    }
                },
                atlas_control_binding_map={
                    "entries": {
                        "rowdescriptor": {
                            "formalization_state": "proxy_descriptor_dark",
                        },
                        "activation_ingress_store": {
                            "formalization_state": "ingress_runtime_visible",
                        },
                        "sync_barrier": {
                            "formalization_state": "sync_gate_visible",
                        },
                    }
                },
                atlas_schema_registry={
                    "version": 1,
                    "vocabulary": "atlas_schema_registry_v1",
                    "views": required_views,
                },
            )

            for run_dir in (baseline_run, object_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "atlas_service_rowindex_object_ab_v1",
                        "baseline_case": "rowindex_object_off",
                        "cases": [
                            {
                                "id": "rowindex_object_off",
                                "label": "rowindex_object_off",
                                "run_dir": str(baseline_run),
                            },
                            {
                                "id": "rowindex_object_on",
                                "label": "rowindex_object_on",
                                "run_dir": str(object_run),
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            out_path = root / "snapshot" / "compare.tsv"
            proc = subprocess.run(
                ["python3", str(SCRIPT_PATH), "--cases", str(cases_path), "--out", str(out_path)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            rows = self._read_tsv(out_path)
            self.assertEqual(
                rows["derived.gate.primary_gate"],
                ["fabric_absent", "rowindex_object_template_branch", "na"],
            )
            self.assertEqual(
                rows["derived.gate.control_state"],
                ["fabric_absent", "queued_without_consume", "na"],
            )
            self.assertEqual(
                rows["derived.gate.shared_weight_absent_reason"],
                ["pulse_osa_gate", "owner_request_gate", "na"],
            )
            self.assertEqual(
                rows["derived.gate.machine_break_stage"],
                ["build_effective", "runtime_requested", "na"],
            )

            gate_rows = self._read_gate_tsv(root / "snapshot" / "gate_summary.tsv")
            self.assertEqual(gate_rows["rowindex_object_off"]["primary_gate"], "fabric_absent")
            self.assertIn(
                "shared_weight_absent_owner_request_gate",
                gate_rows["rowindex_object_on"]["gate_tags"],
            )
            self.assertEqual(gate_rows["rowindex_object_off"]["m2c_entry_ready"], "0")
            self.assertEqual(gate_rows["rowindex_object_on"]["m2c_entry_ready"], "0")
            self.assertIn(
                "fabric_absent",
                gate_rows["rowindex_object_off"]["m2c_blockers"].split(","),
            )
            self.assertIn(
                "sync_state_ready_visible_but_commit_blocked",
                gate_rows["rowindex_object_off"]["m2c_blockers"].split(","),
            )
            self.assertIn(
                "binding_unresolved_present",
                gate_rows["rowindex_object_on"]["m2c_blockers"].split(","),
            )
            self.assertIn(
                "shared_weight_absent_owner_request_gate",
                gate_rows["rowindex_object_on"]["m2c_blockers"].split(","),
            )
            self.assertIn(
                "control_state_queued_without_consume",
                gate_rows["rowindex_object_on"]["m2c_blockers"].split(","),
            )
            self.assertIn(
                "sync_state_ready_visible_but_commit_blocked",
                gate_rows["rowindex_object_on"]["m2c_blockers"].split(","),
            )
            self.assertEqual(
                gate_rows["rowindex_object_on"]["shared_weight_absent_reason"],
                "owner_request_gate",
            )
            self.assertEqual(
                gate_rows["rowindex_object_off"]["control_state"],
                "fabric_absent",
            )

    def _write_summary(
        self,
        run_dir: Path,
        *,
        sim_time_actual_ns: float,
        memory_requests: float,
        memctrl_req_total: float,
        noc_mem_joint: dict[str, float],
        atlas_service: dict[str, float],
        atlas_proxy: dict[str, dict[str, float]] | None = None,
        atlas_fabric: dict[str, float] | None = None,
        atlas_storage: dict[str, float] | None = None,
        atlas_sync: dict[str, float] | None = None,
        atlas_lookup: dict[str, dict[str, float]] | None = None,
        atlas_shadow: dict[str, dict[str, float]] | None = None,
        atlas_control: dict[str, float] | None = None,
        atlas_object_lifecycle: dict[str, Any] | None = None,
        atlas_activation_census: dict[str, Any] | None = None,
        atlas_object_closure: dict[str, Any] | None = None,
        atlas_storage_authority_map: dict[str, Any] | None = None,
        atlas_wms_storage_binding_map: dict[str, Any] | None = None,
        atlas_control_binding_map: dict[str, Any] | None = None,
        atlas_control_commit_view: dict[str, Any] | None = None,
        atlas_schema_registry: dict[str, Any] | None = None,
        atlas_binding_unresolved_ledger: dict[str, Any] | None = None,
        pulse: dict[str, float] | None = None,
    ) -> None:
        payload = {
            "model": {
                "sim_time_actual_ns": sim_time_actual_ns,
            },
            "memory": {
                "memory_requests": memory_requests,
            },
            "memhierarchy": {
                "memctrl": {
                    "req_total": memctrl_req_total,
                }
            },
            "noc_mem_joint": noc_mem_joint,
            "atlas_service": atlas_service,
            "atlas_proxy": {} if atlas_proxy is None else atlas_proxy,
            "atlas_fabric": {} if atlas_fabric is None else atlas_fabric,
            "atlas_storage": {} if atlas_storage is None else atlas_storage,
            "atlas_sync": {} if atlas_sync is None else atlas_sync,
            "atlas_lookup": {} if atlas_lookup is None else atlas_lookup,
            "atlas_shadow": {} if atlas_shadow is None else atlas_shadow,
            "atlas_control": {} if atlas_control is None else atlas_control,
            "atlas_object_lifecycle": {} if atlas_object_lifecycle is None else atlas_object_lifecycle,
            "atlas_activation_census": {} if atlas_activation_census is None else atlas_activation_census,
            "atlas_object_closure": {} if atlas_object_closure is None else atlas_object_closure,
            "atlas_storage_authority_map": {} if atlas_storage_authority_map is None else atlas_storage_authority_map,
            "atlas_wms_storage_binding_map": {} if atlas_wms_storage_binding_map is None else atlas_wms_storage_binding_map,
            "atlas_control_binding_map": {} if atlas_control_binding_map is None else atlas_control_binding_map,
            "atlas_control_commit_view": {} if atlas_control_commit_view is None else atlas_control_commit_view,
            "atlas_schema_registry": {} if atlas_schema_registry is None else atlas_schema_registry,
            "atlas_binding_unresolved_ledger": {} if atlas_binding_unresolved_ledger is None else atlas_binding_unresolved_ledger,
            "pulse": {} if pulse is None else pulse,
        }
        (run_dir / "essential_summary_mesh.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def _read_tsv(self, path: Path) -> dict[str, list[str]]:
        rows: dict[str, list[str]] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if cols[0] == "metric":
                continue
            rows[cols[0]] = cols[1:]
        return rows

    def _read_gate_tsv(self, path: Path) -> dict[str, dict[str, str]]:
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")
        ]
        header = lines[0].split("\t")
        rows: dict[str, dict[str, str]] = {}
        for line in lines[1:]:
            cols = line.split("\t")
            row = {header[idx]: cols[idx] for idx in range(len(header))}
            rows[row["case_id"]] = row
        return rows


if __name__ == "__main__":
    unittest.main()
