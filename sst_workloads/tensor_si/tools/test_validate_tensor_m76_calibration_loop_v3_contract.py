#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m76_calibration_loop_v3_contract.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from fit_tensor_calibration_from_evidence import build_profile  # noqa: E402

SCRIPT = THIS_DIR / "validate_tensor_m76_calibration_loop_v3_contract.py"


class ValidateTensorM76CalibrationLoopV3ContractTest(unittest.TestCase):
    def _summary(self, *, read_total: int, read_samples: int, dma_busy: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_read_latency_cycles_total": read_total,
                "tensor_mem_read_latency_samples_total": read_samples,
                "tensor_program_dma_busy_cycles_total": dma_busy,
            },
        }

    def _reference(self) -> dict:
        return {
            "schema_version": 1,
            "reference_id": "x",
            "metrics": {
                "tensor_mem_read_latency_cycles_avg": {
                    "source": "target",
                    "expected_min": 10.0,
                    "expected_max": 1000.0,
                    "weight": 0.6,
                },
                "tensor_program_dma_busy_cycles_total": {
                    "source": "target",
                    "expected_min": 1.0,
                    "expected_max": 100000.0,
                    "weight": 0.4,
                },
            },
            "confidence_rules": {"high_max_error": 0.2, "medium_max_error": 0.5},
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "base.json"
            target = root / "target.json"
            ref = root / "ref.json"
            profile = root / "profile.json"

            base.write_text(json.dumps(self._summary(read_total=1000, read_samples=100, dma_busy=1000)), encoding="utf-8")
            target.write_text(json.dumps(self._summary(read_total=4000, read_samples=100, dma_busy=2000)), encoding="utf-8")
            ref.write_text(json.dumps(self._reference()), encoding="utf-8")
            profile.write_text(
                json.dumps(build_profile(baseline=base, target=target, reference=ref, tag="m76")),
                encoding="utf-8",
            )

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--profile",
                    str(profile),
                    "--baseline",
                    str(base),
                    "--target",
                    str(target),
                    "--reference",
                    str(ref),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base = root / "base.json"
            target = root / "target.json"
            ref = root / "ref.json"
            profile = root / "profile.json"

            base.write_text(json.dumps(self._summary(read_total=1000, read_samples=100, dma_busy=1000)), encoding="utf-8")
            target.write_text(json.dumps(self._summary(read_total=4000, read_samples=100, dma_busy=2000)), encoding="utf-8")
            ref.write_text(json.dumps(self._reference()), encoding="utf-8")
            payload = build_profile(baseline=base, target=target, reference=ref, tag="m76")
            payload["confidence"] = "low"
            profile.write_text(json.dumps(payload), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--profile",
                    str(profile),
                    "--baseline",
                    str(base),
                    "--target",
                    str(target),
                    "--reference",
                    str(ref),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("confidence", out.stderr)


if __name__ == "__main__":
    unittest.main()
