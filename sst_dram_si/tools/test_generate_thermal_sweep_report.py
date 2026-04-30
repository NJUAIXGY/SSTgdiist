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


class GenerateThermalSweepReportCLITest(unittest.TestCase):
    def test_generates_summary_csv_and_markdown_in_one_shot(self) -> None:
        script = Path(__file__).with_name("generate_thermal_sweep_report.py")
        if not script.exists():
            self.fail(f"missing script: {script}")

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            analysis_dir = td_path / "thermal_analysis"
            out_dir = td_path / "report"
            all_runs_csv = analysis_dir / "layer_stack_validation_all_runs.csv"

            _write_csv(
                all_runs_csv,
                [
                    {
                        "run_dir": "/tmp/run3d",
                        "run_group": "hotspot_3d",
                        "run_label": "20260320-120000",
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
                [
                    "python3",
                    str(script),
                    "--analysis-dir",
                    str(analysis_dir),
                    "--out-dir",
                    str(out_dir),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            payload = json.loads(proc.stdout)
            self.assertEqual(payload["analysis_dir"], str(analysis_dir.resolve()))
            self.assertEqual(payload["run_count"], 2)
            self.assertEqual(payload["sweep_summary_contract_version"], "v2")
            self.assertEqual(payload["hotspot_model_type_counts"], {"block": 1, "grid": 1})

            summary_json = out_dir / "thermal_sweep_overview.json"
            csv_path = out_dir / "thermal_sweep_report.csv"
            md_path = out_dir / "thermal_sweep_report.md"
            self.assertEqual(payload["summary_json"], str(summary_json.resolve()))
            self.assertEqual(payload["csv_path"], str(csv_path.resolve()))
            self.assertEqual(payload["markdown_path"], str(md_path.resolve()))

            self.assertTrue(summary_json.is_file())
            self.assertTrue(csv_path.is_file())
            self.assertTrue(md_path.is_file())

            summary_payload = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(summary_payload["sweep_summary_contract_version"], "v2")
            run_rows = {row["run_group"]: row for row in summary_payload["layer_stack_validation_all_runs"]}
            self.assertEqual(run_rows["hotspot_3d"]["hotspot_model_type"], "grid")
            self.assertEqual(run_rows["hotspot_2d"]["hotspot_model_type"], "block")

            with csv_path.open("r", encoding="utf-8", newline="") as f:
                report_rows = list(csv.DictReader(f))
            report_rows_by_group = {row["run_group"]: row for row in report_rows}
            self.assertEqual(report_rows_by_group["hotspot_3d"]["hotspot_model_type"], "grid")
            self.assertEqual(report_rows_by_group["hotspot_2d"]["hotspot_model_type"], "block")

            md_text = md_path.read_text(encoding="utf-8")
            self.assertIn("| hotspot_3d | grid | yes | passed | yes | 3 | 0 | yes |", md_text)
            self.assertIn("| hotspot_2d | block | no |  | unknown |  |  | unknown |", md_text)


if __name__ == "__main__":
    unittest.main()
