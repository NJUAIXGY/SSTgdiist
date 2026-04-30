#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m52_evidence_calibration.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
FIT_SCRIPT = THIS_DIR / "fit_tensor_calibration_from_evidence.py"
SCRIPT = THIS_DIR / "validate_tensor_m52_evidence_calibration.py"


class ValidateTensorM52EvidenceCalibrationTest(unittest.TestCase):
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

    def test_validate_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            baseline = root / "baseline.json"
            target = root / "target.json"
            ref = root / "ref.json"
            profile = root / "profile.json"

            baseline.write_text(json.dumps(self._summary(200, 10, 100)), encoding="utf-8")
            target.write_text(json.dumps(self._summary(400, 10, 200)), encoding="utf-8")
            ref.write_text(json.dumps(self._ref()), encoding="utf-8")

            proc_fit = subprocess.run(
                [
                    "python3",
                    str(FIT_SCRIPT),
                    "--baseline",
                    str(baseline),
                    "--target",
                    str(target),
                    "--reference",
                    str(ref),
                    "--out",
                    str(profile),
                    "--tag",
                    "x",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc_fit.returncode, 0, msg=proc_fit.stderr)

            proc = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--profile",
                    str(profile),
                    "--baseline",
                    str(baseline),
                    "--target",
                    str(target),
                    "--reference",
                    str(ref),
                    "--expect-pass",
                    "1",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)


if __name__ == "__main__":
    unittest.main()
