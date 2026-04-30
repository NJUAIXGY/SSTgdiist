#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class RefreshMeshCompareSurfacesTest(unittest.TestCase):
    def _run_refresh(self, repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        script = repo_root / "sst_dram_si" / "tools" / "refresh_mesh_compare_surfaces.py"
        return subprocess.run(
            ["python3", str(script), *args],
            text=True,
            capture_output=True,
            cwd=str(repo_root),
        )

    def test_refresh_writes_stable_report_history_and_current_status(self) -> None:
        source_script = Path(__file__).with_name("refresh_mesh_compare_surfaces.py")
        if not source_script.exists():
            self.fail(f"missing script: {source_script}")

        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td) / "repo"
            script_path = repo_root / "sst_dram_si" / "tools" / "refresh_mesh_compare_surfaces.py"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")

            summary_path = (
                repo_root
                / "sst_dram_si"
                / "outputs_large"
                / "paper2"
                / "dram_mesh_4x4_exec_mode_compare"
                / "matrix"
                / "20260407-114554"
                / "summary.json"
            )
            _write_json(
                summary_path,
                {
                    "matrix_run_id": "20260407-114554",
                    "created_utc": "2026-04-07T03:48:04+00:00",
                    "cases": [
                        {
                            "label": "gas",
                            "run_dir": "/tmp/gas",
                            "requested_exec_mode": "gas",
                            "effective_exec_mode": "gas",
                            "compare_role": "smoke",
                            "bounded_validation": True,
                            "validator": {"fail": 0, "warn": 0, "strict": 0},
                            "memory": {"memory_requests": 5954.0, "memory_bytes": 381056.0, "nonzero": True},
                        },
                        {
                            "label": "naive_raw",
                            "run_dir": "/tmp/naive_raw",
                            "requested_exec_mode": "naive_raw",
                            "effective_exec_mode": "naive_raw",
                            "compare_role": "smoke",
                            "bounded_validation": True,
                            "validator": {"fail": 0, "warn": 0, "strict": 0},
                            "memory": {"memory_requests": 11524.0, "memory_bytes": 737536.0, "nonzero": True},
                        },
                        {
                            "label": "naive_opt",
                            "run_dir": "/tmp/naive_opt",
                            "requested_exec_mode": "naive_opt",
                            "effective_exec_mode": "naive_raw",
                            "compare_role": "smoke",
                            "bounded_validation": True,
                            "validator": {"fail": 0, "warn": 0, "strict": 0},
                            "memory": {"memory_requests": 11524.0, "memory_bytes": 737536.0, "nonzero": True},
                        },
                    ],
                },
            )

            proc = self._run_refresh(repo_root)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            references_root = repo_root / "sst_dram_si" / "references"
            report_path = references_root / "mesh-compare-sidecar-report.json"
            history_path = references_root / "mesh-compare-history.json"
            status_path = references_root / "mesh-compare-current-mainline-status.md"
            summary_md_path = references_root / "mesh-compare-sidecar-summary.md"

            self.assertTrue(report_path.is_file(), msg=proc.stdout + proc.stderr)
            self.assertTrue(history_path.is_file(), msg=proc.stdout + proc.stderr)
            self.assertTrue(status_path.is_file(), msg=proc.stdout + proc.stderr)
            self.assertTrue(summary_md_path.is_file(), msg=proc.stdout + proc.stderr)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report.get("artifact_role"), "stable_compare_sidecar_report")
            self.assertTrue(report.get("gate_ok"))
            self.assertEqual(report.get("current_mainline_status_path"), str(status_path))
            self.assertEqual(report.get("history_path"), str(history_path))
            self.assertEqual(report.get("summary_md_path"), str(summary_md_path))
            self.assertEqual(report.get("source_matrix_summary_path"), str(summary_path))
            self.assertEqual(report.get("freshness", {}).get("freshness_mode"), "latest_only")
            self.assertFalse(report.get("freshness", {}).get("stale"))

            cases = report.get("cases") or {}
            self.assertTrue(cases.get("gas", {}).get("gate_ok"))
            self.assertTrue(cases.get("naive_raw", {}).get("gate_ok"))
            self.assertTrue(cases.get("naive_opt", {}).get("gate_ok"))
            self.assertEqual(cases.get("naive_opt", {}).get("effective_exec_mode"), "naive_raw")

            history = json.loads(history_path.read_text(encoding="utf-8"))
            self.assertEqual(history.get("entry_count"), 1)
            self.assertTrue(history.get("latest_all_green"))
            self.assertEqual(history.get("latest_summary_path"), str(summary_path))

            status_text = status_path.read_text(encoding="utf-8")
            self.assertIn("mesh compare current mainline status", status_text.lower())
            self.assertIn("`gate_ok = True`", status_text)
            self.assertIn("`naive_opt.effective_exec_mode = naive_raw`", status_text)

    def test_refresh_marks_report_stale_when_latest_summary_exceeds_ttl(self) -> None:
        source_script = Path(__file__).with_name("refresh_mesh_compare_surfaces.py")
        if not source_script.exists():
            self.fail(f"missing script: {source_script}")

        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td) / "repo"
            script_path = repo_root / "sst_dram_si" / "tools" / "refresh_mesh_compare_surfaces.py"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")

            summary_path = repo_root / "old-summary.json"
            _write_json(
                summary_path,
                {
                    "matrix_run_id": "20260401-010101",
                    "created_utc": "2026-04-01T01:01:01+00:00",
                    "cases": [
                        {
                            "label": "gas",
                            "run_dir": "/tmp/gas",
                            "requested_exec_mode": "gas",
                            "effective_exec_mode": "gas",
                            "compare_role": "smoke",
                            "bounded_validation": True,
                            "validator": {"fail": 0, "warn": 0, "strict": 0},
                            "memory": {"memory_requests": 1.0, "memory_bytes": 64.0, "nonzero": True},
                        },
                        {
                            "label": "naive_raw",
                            "run_dir": "/tmp/naive_raw",
                            "requested_exec_mode": "naive_raw",
                            "effective_exec_mode": "naive_raw",
                            "compare_role": "smoke",
                            "bounded_validation": True,
                            "validator": {"fail": 0, "warn": 0, "strict": 0},
                            "memory": {"memory_requests": 1.0, "memory_bytes": 64.0, "nonzero": True},
                        },
                        {
                            "label": "naive_opt",
                            "run_dir": "/tmp/naive_opt",
                            "requested_exec_mode": "naive_opt",
                            "effective_exec_mode": "naive_raw",
                            "compare_role": "smoke",
                            "bounded_validation": True,
                            "validator": {"fail": 0, "warn": 0, "strict": 0},
                            "memory": {"memory_requests": 1.0, "memory_bytes": 64.0, "nonzero": True},
                        },
                    ],
                },
            )

            proc = self._run_refresh(
                repo_root,
                "--summary",
                str(summary_path),
                "--stale-after-hours",
                "1",
                "--now-utc",
                "2026-04-07T00:00:00+00:00",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            report_path = repo_root / "sst_dram_si" / "references" / "mesh-compare-sidecar-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertFalse(report.get("gate_ok"))
            self.assertTrue(report.get("freshness", {}).get("stale"))
            self.assertIn("stale_latest_summary", report.get("gate_reasons") or [])


if __name__ == "__main__":
    unittest.main()
