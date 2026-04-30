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


class ExportThermalSweepReportCLITest(unittest.TestCase):
    def test_exports_csv_and_markdown_from_summary_json(self) -> None:
        script = Path(__file__).with_name("export_thermal_sweep_report.py")
        if not script.exists():
            self.fail(f"missing script: {script}")

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            summary_json = td_path / "thermal_sweep_overview.json"
            out_dir = td_path / "report"
            _write_json(
                summary_json,
                {
                    "analysis_dir": "/tmp/analysis",
                    "run_count": 2,
                    "sweep_summary_contract_version": "v2",
                    "hotspot_model_type_counts": {"block": 1, "grid": 1},
                    "layer_stack_validation_overview": {
                        "source": "layer_stack_validation_all_runs_csv",
                        "total_rows": 2,
                        "with_validation_count": 1,
                        "without_validation_count": 1,
                        "passed_count": 1,
                        "failed_count": 0,
                        "unknown_count": 0,
                        "config_matched_count": 1,
                        "config_mismatched_count": 0,
                        "run_groups_with_validation": ["hotspot_3d"],
                        "run_groups_without_validation": ["hotspot_2d"],
                    },
                    "layer_stack_validation_all_runs": [
                        {
                            "run_dir": "/tmp/run3d",
                            "run_group": "hotspot_3d",
                            "run_label": "20260320-120000",
                            "hotspot_model_type": "grid",
                            "has_validation": True,
                            "status": "passed",
                            "passed": True,
                            "layer_count_checked": 3,
                            "mismatch_count": 0,
                            "failed_layer_count": 0,
                            "mismatch_reasons": [],
                            "config_matches": True,
                            "config_mismatch_reasons": [],
                        },
                        {
                            "run_dir": "/tmp/run2d",
                            "run_group": "hotspot_2d",
                            "run_label": "20260320-120100",
                            "hotspot_model_type": "block",
                            "has_validation": False,
                            "status": "",
                            "passed": None,
                            "layer_count_checked": None,
                            "mismatch_count": None,
                            "failed_layer_count": None,
                            "mismatch_reasons": [],
                            "config_matches": None,
                            "config_mismatch_reasons": [],
                        },
                    ],
                },
            )

            proc = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--summary-json",
                    str(summary_json),
                    "--out-dir",
                    str(out_dir),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["sweep_summary_contract_version"], "v2")

            csv_path = out_dir / "thermal_sweep_report.csv"
            md_path = out_dir / "thermal_sweep_report.md"
            self.assertTrue(csv_path.is_file())
            self.assertTrue(md_path.is_file())

            with csv_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 2)
            rows_by_group = {row["run_group"]: row for row in rows}
            self.assertEqual(rows_by_group["hotspot_3d"]["hotspot_model_type"], "grid")
            self.assertEqual(rows_by_group["hotspot_3d"]["has_validation"], "1")
            self.assertEqual(rows_by_group["hotspot_3d"]["validation_status"], "passed")
            self.assertEqual(rows_by_group["hotspot_2d"]["hotspot_model_type"], "block")
            self.assertEqual(rows_by_group["hotspot_2d"]["has_validation"], "0")
            self.assertEqual(rows_by_group["hotspot_2d"]["validation_status"], "")

            md_text = md_path.read_text(encoding="utf-8")
            self.assertIn("# Thermal Sweep Report", md_text)
            self.assertIn("Summary contract version: v2", md_text)
            self.assertIn("Run count: 2", md_text)
            self.assertIn("layer_stack_validation_all_runs_csv", md_text)
            self.assertIn("| hotspot_3d | grid | yes | passed | yes | 3 | 0 | yes |", md_text)
            self.assertIn("| hotspot_2d | block | no |  | unknown |  |  | unknown |", md_text)


if __name__ == "__main__":
    unittest.main()
