#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for fit_tensor_calibration_from_evidence.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "fit_tensor_calibration_from_evidence.py"


class FitTensorCalibrationFromEvidenceTest(unittest.TestCase):
    def _summary(self, lat_total: int, lat_samples: int, dma_busy: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_read_latency_cycles_total": lat_total,
                "tensor_mem_read_latency_samples_total": lat_samples,
                "tensor_program_dma_busy_cycles_total": dma_busy,
            },
        }

    def _ref(self) -> dict:
        return {
            "schema_version": 1,
            "reference_id": "r1",
            "metrics": {
                "tensor_mem_read_latency_cycles_avg": {
                    "source": "target",
                    "expected_min": 10,
                    "expected_max": 2000,
                    "weight": 0.6,
                },
                "tensor_program_dma_busy_cycles_total": {
                    "source": "target",
                    "expected_min": 1,
                    "expected_max": 100000,
                    "weight": 0.4,
                },
            },
            "confidence_rules": {
                "high_max_error": 0.2,
                "medium_max_error": 0.5,
            },
        }

    def test_fit_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            baseline = root / "baseline.json"
            target = root / "target.json"
            ref = root / "ref.json"
            out = root / "profile.json"

            baseline.write_text(json.dumps(self._summary(200, 10, 100)), encoding="utf-8")
            target.write_text(json.dumps(self._summary(400, 10, 200)), encoding="utf-8")
            ref.write_text(json.dumps(self._ref()), encoding="utf-8")

            proc = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline",
                    str(baseline),
                    "--target",
                    str(target),
                    "--reference",
                    str(ref),
                    "--out",
                    str(out),
                    "--tag",
                    "x",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 1)
            self.assertIn("factors", payload)
            self.assertIn("evidence", payload)


if __name__ == "__main__":
    unittest.main()
