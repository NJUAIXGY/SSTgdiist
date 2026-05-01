import json
import subprocess
import tempfile
import unittest
from pathlib import Path


EXPERIMENT_DIR = Path(__file__).resolve().parent
SCRIPT_PATH = EXPERIMENT_DIR / "make_snapshot.py"


class MakeSnapshotTest(unittest.TestCase):
    def test_generates_compare_tsv_with_ready_join_dedup_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline_run = root / "baseline_run"
            dedup_run = root / "dedup_run"
            baseline_run.mkdir()
            dedup_run.mkdir()

            self._write_summary(
                baseline_run,
                sim_time_actual_ns=224813.0,
                memory_requests=150907.0,
                memory_bytes=9658048.0,
                memctrl_req_total=150907.0,
                apply_ns_avg=210210.75,
                gather_ns_avg=547.0,
                scatter_ns_avg=1.0,
                memctrl_payload_utilization=1.0,
                neurons_fired_total=1939.0,
                total_spikes_processed=1206784.0,
                snn_edge_record={
                    "attempt_total": 240,
                    "commit_total": 120,
                    "skip_gate_total": 12,
                    "skip_stage_total": 48,
                    "skip_capacity_total": 60,
                    "skip_reject_total": 6,
                    "fastpath_handler_entry_total": 96,
                    "fastpath_wms_missing_total": 3,
                    "fastpath_backend_not_ready_total": 6,
                    "fastpath_stage_block_total": 24,
                    "process_local_handler_entry_total": 72,
                    "process_local_wms_missing_total": 4,
                    "process_local_backend_not_ready_total": 8,
                    "process_local_stage_block_total": 12,
                    "deliver_window_handler_entry_total": 36,
                    "deliver_window_wms_missing_total": 1,
                    "deliver_window_backend_not_ready_total": 2,
                    "deliver_window_stage_block_total": 12,
                },
                snn_wms_frontier={
                    "record_prerank_entry_total": 128,
                    "record_prerank_premphf_mode_total": 128,
                    "record_prerank_existing_rank_total": 64,
                    "record_prerank_new_rank_total": 64,
                    "record_prerank_total": 192,
                    "collect_entry_total": 96,
                    "lookup_attempt_total": 64,
                    "collect_line_notes_total": 48,
                },
                pulse={
                    "pulse_shared_service_hits_total": 613100,
                    "pulse_shared_service_misses_total": 150500,
                    "pulse_ready_fanout_total": 764000,
                    "pulse_actual_gate_taken_total": 763700,
                    "pulse_mfb_gather_owner_first_rate": 0.9841269841269841,
                    "pulse_mfb_gather_record_prerank_entry_total": 128,
                    "pulse_mfb_gather_record_prerank_premphf_mode_total": 128,
                    "pulse_mfb_gather_record_prerank_existing_rank_total": 64,
                    "pulse_mfb_gather_record_prerank_new_rank_total": 64,
                    "pulse_mfb_gather_record_prerank_total": 192,
                    "pulse_mfb_gather_gate_reject_total": 0,
                    "pulse_mfb_gather_collect_entry_total": 96,
                    "pulse_mfb_gather_lookup_attempt_total": 192,
                    "pulse_mfb_gather_lookup_hit_total": 96,
                    "pulse_mfb_gather_lookup_miss_total": 96,
                    "pulse_mfb_gather_prerank_oob_total": 12,
                    "pulse_mfb_gather_collect_line_notes_total": 96,
                    "pulse_mfb_gather_collected_bands_total": 48,
                    "pulse_mfb_gather_barrier_input_bands_total": 12,
                    "pulse_mfb_gather_barrier_replay_bands_total": 6,
                    "pulse_mfb_gather_register_trigger_total": 24,
                    "pulse_rowdescriptor_ready_transition_total": 18,
                    "pulse_rowdescriptor_join_ready_total": 9,
                    "pulse_mfb_gather_preband_enable": 1,
                    "pulse_rowdescriptor_ready_join_shortcut_candidates_total": 0,
                    "pulse_rowdescriptor_ready_join_shortcut_taken_total": 0,
                    "pulse_rowdescriptor_ready_join_shortcut_blocked_not_ready_total": 0,
                    "pulse_rowdescriptor_ready_join_shortcut_release_deferred_total": 0,
                    "pulse_rowdescriptor_ready_join_shortcut_apply_complete_total": 0,
                    "pulse_rowdescriptor_ready_join_shortcut_release_forwarded_total": 0,
                    "pulse_rowdescriptor_ready_join_shortcut_release_missing_total": 0,
                    "pulse_rowdescriptor_ready_join_descriptor_elide_total": 0,
                    "pulse_rowdescriptor_ready_join_lines_elide_total": 0,
                    "pulse_pod_rowdescriptor_owner_first_issue_deferred_total": 1153,
                    "pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total": 1153,
                    "pulse_pod_rowdescriptor_owner_first_service_elide_total": 189,
                },
            )
            self._write_summary(
                dedup_run,
                sim_time_actual_ns=223950.0,
                memory_requests=150500.0,
                memory_bytes=9632000.0,
                memctrl_req_total=150500.0,
                apply_ns_avg=209950.0,
                gather_ns_avg=547.0,
                scatter_ns_avg=1.0,
                memctrl_payload_utilization=1.0,
                neurons_fired_total=1939.0,
                total_spikes_processed=1206784.0,
                snn_edge_record={
                    "attempt_total": 300,
                    "commit_total": 210,
                    "skip_gate_total": 6,
                    "skip_stage_total": 18,
                    "skip_capacity_total": 54,
                    "skip_reject_total": 12,
                    "fastpath_handler_entry_total": 144,
                    "fastpath_wms_missing_total": 0,
                    "fastpath_backend_not_ready_total": 3,
                    "fastpath_stage_block_total": 9,
                    "process_local_handler_entry_total": 96,
                    "process_local_wms_missing_total": 2,
                    "process_local_backend_not_ready_total": 4,
                    "process_local_stage_block_total": 6,
                    "deliver_window_handler_entry_total": 60,
                    "deliver_window_wms_missing_total": 0,
                    "deliver_window_backend_not_ready_total": 1,
                    "deliver_window_stage_block_total": 3,
                },
                snn_wms_frontier={
                    "record_prerank_entry_total": 192,
                    "record_prerank_premphf_mode_total": 192,
                    "record_prerank_existing_rank_total": 72,
                    "record_prerank_new_rank_total": 120,
                    "record_prerank_total": 288,
                    "collect_entry_total": 144,
                    "lookup_attempt_total": 96,
                    "collect_line_notes_total": 72,
                },
                pulse={
                    "pulse_shared_service_hits_total": 613100,
                    "pulse_shared_service_misses_total": 150500,
                    "pulse_ready_fanout_total": 764200,
                    "pulse_actual_gate_taken_total": 763700,
                    "pulse_mfb_gather_owner_first_rate": 0.9841269841269841,
                    "pulse_mfb_gather_record_prerank_entry_total": 192,
                    "pulse_mfb_gather_record_prerank_premphf_mode_total": 192,
                    "pulse_mfb_gather_record_prerank_existing_rank_total": 72,
                    "pulse_mfb_gather_record_prerank_new_rank_total": 120,
                    "pulse_mfb_gather_record_prerank_total": 288,
                    "pulse_mfb_gather_gate_reject_total": 0,
                    "pulse_mfb_gather_collect_entry_total": 144,
                    "pulse_mfb_gather_lookup_attempt_total": 288,
                    "pulse_mfb_gather_lookup_hit_total": 144,
                    "pulse_mfb_gather_lookup_miss_total": 144,
                    "pulse_mfb_gather_prerank_oob_total": 24,
                    "pulse_mfb_gather_collect_line_notes_total": 144,
                    "pulse_mfb_gather_collected_bands_total": 72,
                    "pulse_mfb_gather_barrier_input_bands_total": 24,
                    "pulse_mfb_gather_barrier_replay_bands_total": 12,
                    "pulse_mfb_gather_register_trigger_total": 36,
                    "pulse_rowdescriptor_ready_transition_total": 27,
                    "pulse_rowdescriptor_join_ready_total": 18,
                    "pulse_mfb_gather_preband_enable": 1,
                    "pulse_rowdescriptor_ready_join_shortcut_candidates_total": 72,
                    "pulse_rowdescriptor_ready_join_shortcut_taken_total": 72,
                    "pulse_rowdescriptor_ready_join_shortcut_blocked_not_ready_total": 0,
                    "pulse_rowdescriptor_ready_join_shortcut_release_deferred_total": 72,
                    "pulse_rowdescriptor_ready_join_shortcut_apply_complete_total": 72,
                    "pulse_rowdescriptor_ready_join_shortcut_release_forwarded_total": 72,
                    "pulse_rowdescriptor_ready_join_shortcut_release_missing_total": 0,
                    "pulse_rowdescriptor_ready_join_descriptor_elide_total": 72,
                    "pulse_rowdescriptor_ready_join_lines_elide_total": 96,
                    "pulse_pod_rowdescriptor_owner_first_issue_deferred_total": 1153,
                    "pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total": 1153,
                    "pulse_pod_rowdescriptor_owner_first_service_elide_total": 189,
                },
            )

            for run_dir in (baseline_run, dedup_run):
                (run_dir / "validation.log").write_text(
                    "[val] SUMMARY run_dir=/tmp/run fail=0 warn=0 strict=0\n",
                    encoding="utf-8",
                )

            cases_path = root / "cases.json"
            cases_path.write_text(
                json.dumps(
                    {
                        "experiment_id": "pulse_rowdescriptor_ready_join_dedup_test",
                        "baseline_case": "dedup_off",
                        "cases": [
                            {"id": "dedup_off", "label": "dedup_off", "run_dir": str(baseline_run)},
                            {"id": "dedup_on", "label": "dedup_on", "run_dir": str(dedup_run)},
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
                rows["model.sim_time_actual_ns"],
                ["224813.0", "223950.0", "-863.0"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_join_shortcut_candidates_total"],
                ["0", "72", "72"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_collect_line_notes_total"],
                ["96", "144", "48"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_record_prerank_total"],
                ["192", "288", "96"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_record_prerank_entry_total"],
                ["128", "192", "64"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_record_prerank_premphf_mode_total"],
                ["128", "192", "64"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_record_prerank_existing_rank_total"],
                ["64", "72", "8"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_record_prerank_new_rank_total"],
                ["64", "120", "56"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_gate_reject_total"],
                ["0", "0", "0"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_collect_entry_total"],
                ["96", "144", "48"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_lookup_attempt_total"],
                ["192", "288", "96"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_lookup_hit_total"],
                ["96", "144", "48"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_lookup_miss_total"],
                ["96", "144", "48"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_prerank_oob_total"],
                ["12", "24", "12"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_collected_bands_total"],
                ["48", "72", "24"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_barrier_input_bands_total"],
                ["12", "24", "12"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_barrier_replay_bands_total"],
                ["6", "12", "6"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_register_trigger_total"],
                ["24", "36", "12"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_transition_total"],
                ["18", "27", "9"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_join_ready_total"],
                ["9", "18", "9"],
            )
            self.assertEqual(
                rows["snn_edge_record.attempt_total"],
                ["240", "300", "60"],
            )
            self.assertEqual(
                rows["snn_edge_record.skip_stage_total"],
                ["48", "18", "-30"],
            )
            self.assertEqual(
                rows["snn_edge_record.fastpath_handler_entry_total"],
                ["96", "144", "48"],
            )
            self.assertEqual(
                rows["snn_edge_record.fastpath_backend_not_ready_total"],
                ["6", "3", "-3"],
            )
            self.assertEqual(
                rows["snn_edge_record.process_local_wms_missing_total"],
                ["4", "2", "-2"],
            )
            self.assertEqual(
                rows["snn_edge_record.deliver_window_stage_block_total"],
                ["12", "3", "-9"],
            )
            self.assertEqual(
                rows["snn_wms_frontier.record_prerank_entry_total"],
                ["128", "192", "64"],
            )
            self.assertEqual(
                rows["snn_wms_frontier.record_prerank_premphf_mode_total"],
                ["128", "192", "64"],
            )
            self.assertEqual(
                rows["snn_wms_frontier.record_prerank_existing_rank_total"],
                ["64", "72", "8"],
            )
            self.assertEqual(
                rows["snn_wms_frontier.record_prerank_new_rank_total"],
                ["64", "120", "56"],
            )
            self.assertEqual(
                rows["snn_wms_frontier.record_prerank_total"],
                ["192", "288", "96"],
            )
            self.assertEqual(
                rows["snn_wms_frontier.collect_entry_total"],
                ["96", "144", "48"],
            )
            self.assertEqual(
                rows["snn_wms_frontier.lookup_attempt_total"],
                ["64", "96", "32"],
            )
            self.assertEqual(
                rows["snn_wms_frontier.collect_line_notes_total"],
                ["48", "72", "24"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_join_shortcut_taken_total"],
                ["0", "72", "72"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_join_shortcut_blocked_not_ready_total"],
                ["0", "0", "0"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_join_shortcut_release_deferred_total"],
                ["0", "72", "72"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_join_shortcut_apply_complete_total"],
                ["0", "72", "72"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_join_shortcut_release_forwarded_total"],
                ["0", "72", "72"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_join_shortcut_release_missing_total"],
                ["0", "0", "0"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_join_descriptor_elide_total"],
                ["0", "72", "72"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_join_lines_elide_total"],
                ["0", "96", "96"],
            )
            self.assertEqual(
                rows["pulse_rowdescriptor_ready_join_lines_per_descriptor_elide_avg"],
                ["0", str(96.0 / 72.0), str(96.0 / 72.0)],
            )
            self.assertEqual(
                rows["pulse_pod_rowdescriptor_owner_first_issue_deferred_total"],
                ["1153", "1153", "0"],
            )
            self.assertEqual(
                rows["pulse_pod_rowdescriptor_owner_first_private_issue_avoided_total"],
                ["1153", "1153", "0"],
            )
            self.assertEqual(
                rows["pulse_pod_rowdescriptor_owner_first_service_elide_total"],
                ["189", "189", "0"],
            )
            self.assertEqual(
                rows["pulse_mfb_gather_owner_first_rate"],
                ["0.9841269841269841", "0.9841269841269841", "0.0"],
            )

    def _write_summary(
        self,
        run_dir,
        *,
        sim_time_actual_ns,
        memory_requests,
        memory_bytes,
        memctrl_req_total,
        apply_ns_avg,
        gather_ns_avg,
        scatter_ns_avg,
        memctrl_payload_utilization,
        neurons_fired_total,
        total_spikes_processed,
        snn_edge_record,
        snn_wms_frontier,
        pulse,
    ):
        payload = {
            "model": {"sim_time_actual_ns": sim_time_actual_ns},
            "memory": {
                "memory_requests": memory_requests,
                "memory_bytes": memory_bytes,
            },
            "memhierarchy": {"memctrl": {"req_total": memctrl_req_total}},
            "gas": {
                "apply_ns_avg": apply_ns_avg,
                "gather_ns_avg": gather_ns_avg,
                "scatter_ns_avg": scatter_ns_avg,
                "memctrl_payload_utilization": memctrl_payload_utilization,
            },
            "spike_activity": {
                "neurons_fired_total": neurons_fired_total,
                "total_spikes_processed": total_spikes_processed,
            },
            "snn_edge_record": snn_edge_record,
            "snn_wms_frontier": snn_wms_frontier,
            "pulse": pulse,
        }
        (run_dir / "essential_summary_mesh.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )

    def _read_tsv(self, path):
        rows = {}
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if cols[0] == "metric":
                    continue
                rows[cols[0]] = cols[1:]
        return rows


if __name__ == "__main__":
    unittest.main()
