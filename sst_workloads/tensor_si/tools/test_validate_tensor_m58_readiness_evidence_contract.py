#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m58_readiness_evidence_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m58_readiness_evidence_contract.py"


class ValidateTensorM58ReadinessEvidenceContractTest(unittest.TestCase):
    def _summary(self, *, score: float, factor: float, confidence: str, flags: list[str]) -> dict:
        return {
            "schema_version": 1,
            "npu_tpu_readiness": {
                "capability_profile": "readiness_evidence_v2",
                "capability_score_total": score,
                "evidence_factor": factor,
                "calibration_confidence": confidence,
                "regression_drift_flags": flags,
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "cfg.json"
            rich = root / "rich.json"
            cfg.write_text(
                json.dumps(self._summary(score=40.0, factor=0.80, confidence="unverified", flags=["missing_mem_read_latency_samples"])),
                encoding="utf-8",
            )
            rich.write_text(
                json.dumps(self._summary(score=62.0, factor=0.95, confidence="high", flags=[])),
                encoding="utf-8",
            )
            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--config-only",
                    str(cfg),
                    "--evidence-rich",
                    str(rich),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_empty_config_flags(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / "cfg.json"
            rich = root / "rich.json"
            cfg.write_text(json.dumps(self._summary(score=40.0, factor=0.80, confidence="unverified", flags=[])), encoding="utf-8")
            rich.write_text(json.dumps(self._summary(score=62.0, factor=0.95, confidence="high", flags=[])), encoding="utf-8")
            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--config-only",
                    str(cfg),
                    "--evidence-rich",
                    str(rich),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("drift flags non-empty", out.stderr)


if __name__ == "__main__":
    unittest.main()
