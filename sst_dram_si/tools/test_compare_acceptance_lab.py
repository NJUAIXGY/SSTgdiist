#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).with_name("compare_acceptance_lab.py")
    spec = importlib.util.spec_from_file_location("compare_acceptance_lab", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lab = _load_module()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class CompareAcceptanceLabTests(unittest.TestCase):
    def _write_authority(self, root: Path) -> Path:
        authority = {
            "schema_version": 1,
            "gate_name": "mesh_exec_mode_compare_acceptance",
            "gate_version": "1.0",
            "artifact_role": "stable_top_level_gate",
            "authority_scope": "experimental_gate_authority",
            "required_cases": ["gas", "naive_raw", "naive_opt"],
            "case_contract": {
                "compare_role": "smoke",
                "bounded_validation": True,
                "validator_fail_max": 0,
                "memory_nonzero_required": True,
            },
            "freshness": {
                "max_age_days": 2,
                "multi_date_freshness_mode": "since_latest_recovery",
            },
            "paths": {
                "matrix_root": "outputs_large/paper2/dram_mesh_4x4_exec_mode_compare/matrix",
                "history_path": "references/compare-smoke-history.json",
                "report_path": "references/compare-nightly-report.json",
                "observer_summary_path": "references/compare-nightly-observer-summary.json",
                "summary_md_path": "references/compare-nightly-summary.md",
                "current_mainline_status_path": "references/compare-current-status.md",
            },
        }
        authority_path = root / "spec_authority" / "compare_acceptance_gate_v1.json"
        _write_json(authority_path, authority)
        return authority_path

    def _write_matrix_summary(self, root: Path, run_id: str, *, gas_fail: int = 0) -> None:
        summary = {
            "matrix_run_id": run_id,
            "created_utc": f"{run_id[:4]}-{run_id[4:6]}-{run_id[6:8]}T00:00:00+00:00",
            "cases": [
                {
                    "label": "gas",
                    "run_dir": f"/tmp/{run_id}/gas",
                    "requested_exec_mode": "gas",
                    "effective_exec_mode": "gas",
                    "compare_role": "smoke",
                    "bounded_validation": True,
                    "validator": {"fail": gas_fail, "warn": 0, "strict": 0},
                    "memory": {"nonzero": True, "memory_requests": 1, "memory_bytes": 64},
                },
                {
                    "label": "naive_raw",
                    "run_dir": f"/tmp/{run_id}/naive_raw",
                    "requested_exec_mode": "naive_raw",
                    "effective_exec_mode": "naive_raw",
                    "compare_role": "smoke",
                    "bounded_validation": True,
                    "validator": {"fail": 0, "warn": 0, "strict": 0},
                    "memory": {"nonzero": True, "memory_requests": 2, "memory_bytes": 128},
                },
                {
                    "label": "naive_opt",
                    "run_dir": f"/tmp/{run_id}/naive_opt",
                    "requested_exec_mode": "naive_opt",
                    "effective_exec_mode": "naive_raw",
                    "compare_role": "smoke",
                    "bounded_validation": True,
                    "validator": {"fail": 0, "warn": 0, "strict": 0},
                    "memory": {"nonzero": True, "memory_requests": 2, "memory_bytes": 128},
                },
            ],
        }
        _write_json(
            root / "outputs_large" / "paper2" / "dram_mesh_4x4_exec_mode_compare" / "matrix" / run_id / "summary.json",
            summary,
        )

    def test_refresh_writes_stable_outputs_and_current_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            authority_path = self._write_authority(root)
            self._write_matrix_summary(root, "20260407-114554")

            payload = lab.refresh(
                project_root=root,
                authority_path=authority_path,
                now_utc=lab.dt.datetime(2026, 4, 7, 12, 0, tzinfo=lab.dt.timezone.utc),
            )

            self.assertTrue(payload["gate_ok"])
            report = json.loads((root / "references" / "compare-nightly-report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["gate_ok"])
            self.assertEqual(report["latest_matrix"]["date"], "2026-04-07")
            self.assertEqual(report["latest_case_rollups"]["naive_opt"]["effective_exec_mode"], "naive_raw")
            self.assertEqual(
                report["stable_surfaces"]["current_mainline_status_path"],
                str((root / "references" / "compare-current-status.md").resolve()),
            )

            current_status = (root / "references" / "compare-current-status.md").read_text(encoding="utf-8")
            self.assertIn("compare current mainline status", current_status)
            self.assertIn("`naive_opt.effective_exec_mode = naive_raw`", current_status)

            summary_md = (root / "references" / "compare-nightly-summary.md").read_text(encoding="utf-8")
            self.assertIn("current_mainline_status_path", summary_md)
            self.assertIn("compare-nightly-report.json", summary_md)

    def test_since_latest_recovery_freshness_window_can_be_green_with_older_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            authority_path = self._write_authority(root)
            self._write_matrix_summary(root, "20260407-114554")
            self._write_matrix_summary(root, "20260406-090000", gas_fail=1)

            payload = lab.refresh(
                project_root=root,
                authority_path=authority_path,
                now_utc=lab.dt.datetime(2026, 4, 7, 12, 0, tzinfo=lab.dt.timezone.utc),
            )

            self.assertTrue(payload["gate_ok"])
            history = json.loads((root / "references" / "compare-smoke-history.json").read_text(encoding="utf-8"))
            self.assertFalse(history["all_dates_ok"])
            self.assertEqual(history["latest_recovered_date"], "2026-04-07")
            self.assertTrue(history["effective_all_dates_ok"])

            observer = json.loads((root / "references" / "compare-nightly-observer-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(observer["history_rollup"]["freshness_mode"], "since_latest_recovery")
            self.assertTrue(observer["history_rollup"]["effective_all_dates_ok"])

    def test_report_marks_latest_matrix_stale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            authority_path = self._write_authority(root)
            self._write_matrix_summary(root, "20260401-100000")

            payload = lab.refresh(
                project_root=root,
                authority_path=authority_path,
                now_utc=lab.dt.datetime(2026, 4, 7, 12, 0, tzinfo=lab.dt.timezone.utc),
            )

            self.assertFalse(payload["gate_ok"])
            report = json.loads((root / "references" / "compare-nightly-report.json").read_text(encoding="utf-8"))
            self.assertIn("stale_latest_matrix", report["gate_reasons"])
            self.assertTrue(report["history"]["stale"])
            self.assertEqual(report["history"]["latest_age_days"], 6)


if __name__ == "__main__":
    unittest.main()
