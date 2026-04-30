#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class SummarizeThermalAnalysisCLITest(unittest.TestCase):
    def test_prefers_layer_stack_validation_all_runs_csv_when_present(self) -> None:
        script = Path(__file__).with_name("summarize_thermal_analysis.py")
        if not script.exists():
            self.fail(f"missing script: {script}")

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            analysis_dir = td_path / "thermal_analysis"
            all_runs_csv = analysis_dir / "layer_stack_validation_all_runs.csv"
            _write_csv(
                all_runs_csv,
                [
                    {
                        "run_dir": "/tmp/run3d",
                        "run_group": "hotspot_3d",
                        "run_label": "20260320-120000",
                        "window_power_sample_count": "2",
                        "window_power_block_count": "6",
                        "window_power_trace_sources": "csv_constant,window_metrics",
                        "has_validation": "1",
                        "status": "passed",
                        "passed": "1",
                        "layer_count_checked": "3",
                        "mismatch_count": "0",
                        "failed_layer_count": "0",
                        "mismatch_reasons": "",
                        "config_matches": "1",
                        "config_mismatch_reasons": "",
                    },
                    {
                        "run_dir": "/tmp/run2d",
                        "run_group": "hotspot_2d",
                        "run_label": "20260320-120100",
                        "window_power_sample_count": "1",
                        "window_power_block_count": "3",
                        "window_power_trace_sources": "average_power",
                        "has_validation": "0",
                        "status": "",
                        "passed": "",
                        "layer_count_checked": "",
                        "mismatch_count": "",
                        "failed_layer_count": "",
                        "mismatch_reasons": "",
                        "config_matches": "",
                        "config_mismatch_reasons": "",
                    },
                ],
            )
            _write_json(
                analysis_dir / "thermal_analysis.json",
                {
                    "run_count": 2,
                    "artifacts": {
                        "layer_stack_validation_all_runs_csv": str(all_runs_csv.resolve()),
                    },
                    "runs": [
                        {"run_group": "hotspot_3d", "hotspot_model_type": "grid"},
                        {"run_group": "hotspot_2d", "hotspot_model_type": "block"},
                    ],
                },
            )

            proc = subprocess.run(
                ["python3", str(script), "--analysis-dir", str(analysis_dir)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["run_count"], 2)
            self.assertEqual(payload["sweep_summary_contract_version"], "v2")
            provenance = dict(payload.get("artifact_provenance") or {})
            self.assertEqual(provenance.get("tool"), "sst_dram_si.tools.summarize_thermal_analysis")
            self.assertEqual(provenance.get("artifact_kind"), "thermal_sweep_summary")
            self.assertEqual(provenance.get("contract_version"), "v2")
            self.assertEqual(provenance.get("source_kind"), "analysis_dir")
            self.assertEqual(provenance.get("analysis_dir"), str(analysis_dir.resolve()))
            self.assertTrue(str(provenance.get("generated_at_utc") or "").endswith("Z"))
            self.assertEqual(
                dict(provenance.get("source_paths") or {}).get("thermal_analysis_json"),
                str((analysis_dir / "thermal_analysis.json").resolve()),
            )
            self.assertEqual(
                dict(provenance.get("source_paths") or {}).get("layer_stack_validation_all_runs_csv"),
                str(all_runs_csv.resolve()),
            )
            self.assertEqual(payload["hotspot_model_type_counts"]["grid"], 1)
            self.assertEqual(payload["hotspot_model_type_counts"]["block"], 1)
            overview = payload["layer_stack_validation_overview"]
            self.assertEqual(overview["source"], "layer_stack_validation_all_runs_csv")
            self.assertEqual(overview["total_rows"], 2)
            self.assertEqual(overview["with_validation_count"], 1)
            self.assertEqual(overview["without_validation_count"], 1)
            self.assertEqual(overview["passed_count"], 1)
            self.assertEqual(overview["failed_count"], 0)
            self.assertEqual(overview["run_groups_with_validation"], ["hotspot_3d"])
            self.assertEqual(overview["run_groups_without_validation"], ["hotspot_2d"])
            run_rows = {row["run_group"]: row for row in payload["layer_stack_validation_all_runs"]}
            self.assertEqual(run_rows["hotspot_3d"]["hotspot_model_type"], "grid")
            self.assertEqual(run_rows["hotspot_2d"]["hotspot_model_type"], "block")
            self.assertEqual(run_rows["hotspot_3d"]["window_power_sample_count"], 2)
            self.assertEqual(run_rows["hotspot_2d"]["window_power_sample_count"], 1)
            self.assertEqual(payload["window_power_trace_source_counts"], {"average_power": 1, "csv_constant": 1, "window_metrics": 1})

    def test_reconstructs_all_runs_view_from_thermal_analysis_runs_when_csv_missing(self) -> None:
        script = Path(__file__).with_name("summarize_thermal_analysis.py")
        if not script.exists():
            self.fail(f"missing script: {script}")

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            analysis_dir = td_path / "thermal_analysis"
            _write_json(
                analysis_dir / "thermal_analysis.json",
                {
                    "run_count": 2,
                    "runs": [
                        {
                            "run_dir": "/tmp/run_failed",
                            "run_group": "hotspot_failed",
                            "run_label": "20260320-130000",
                            "hotspot_model_type": "grid",
                            "window_power_sample_count": 3,
                            "window_power_block_count": 9,
                            "window_power_trace_sources": ["window_metrics", "csv_constant"],
                            "layer_stack_validation": {
                                "status": "failed",
                                "passed": False,
                                "layer_count_checked": 3,
                                "mismatch_count": 2,
                                "failed_layer_count": 1,
                                "mismatch_reasons": ["thickness"],
                                "config_matches": False,
                                "config_mismatch_reasons": ["grid_rows"],
                            },
                        },
                        {
                            "run_dir": "/tmp/run_plain",
                            "run_group": "hotspot_plain",
                            "run_label": "20260320-130100",
                            "hotspot_model_type": "block",
                            "window_power_sample_count": 1,
                            "window_power_block_count": 3,
                            "window_power_trace_sources": ["average_power"],
                            "layer_stack_validation": {},
                        },
                    ],
                },
            )

            proc = subprocess.run(
                ["python3", str(script), "--analysis-dir", str(analysis_dir)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["sweep_summary_contract_version"], "v2")
            overview = payload["layer_stack_validation_overview"]
            self.assertEqual(overview["source"], "reconstructed_from_thermal_analysis_runs")
            self.assertEqual(overview["total_rows"], 2)
            self.assertEqual(overview["with_validation_count"], 1)
            self.assertEqual(overview["without_validation_count"], 1)
            self.assertEqual(overview["passed_count"], 0)
            self.assertEqual(overview["failed_count"], 1)
            self.assertEqual(overview["unknown_count"], 0)
            self.assertEqual(overview["config_mismatched_count"], 1)
            self.assertEqual(overview["run_groups_with_validation"], ["hotspot_failed"])
            self.assertEqual(overview["run_groups_without_validation"], ["hotspot_plain"])
            run_rows = {row["run_group"]: row for row in payload["layer_stack_validation_all_runs"]}
            self.assertEqual(run_rows["hotspot_failed"]["hotspot_model_type"], "grid")
            self.assertEqual(run_rows["hotspot_plain"]["hotspot_model_type"], "block")
            self.assertEqual(run_rows["hotspot_failed"]["window_power_sample_count"], 3)
            self.assertEqual(run_rows["hotspot_plain"]["window_power_sample_count"], 1)
            self.assertEqual(payload["window_power_trace_source_counts"], {"average_power": 1, "csv_constant": 1, "window_metrics": 1})


if __name__ == "__main__":
    unittest.main()
