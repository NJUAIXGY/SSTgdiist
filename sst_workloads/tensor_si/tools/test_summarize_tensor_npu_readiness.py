#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for summarize_tensor_npu_readiness.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "summarize_tensor_npu_readiness.py"


class SummarizeTensorNpuReadinessTest(unittest.TestCase):
    def _mk_summary(self, score: float, gap: float, conf: str) -> dict:
        return {
            "schema_version": 1,
            "tensor": {"tensor_capability_score_total": score},
            "npu_tpu_readiness": {
                "capability_score_total": score,
                "distance_to_target": max(0.0, 85.0 - score),
                "capability_score_breakdown": {
                    "scheduler": score,
                    "dataflow": score - 1,
                    "memory": score + 1,
                    "parallelism": score,
                    "scalability": score,
                },
                "gap_rank_topk": [{"dimension": "memory", "gap": gap}],
                "calibration_confidence": conf,
                "regression_drift_flags": ["x"],
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            s1 = root / "s1.json"
            s2 = root / "s2.json"
            s3 = root / "s3.json"
            out_p = root / "report.json"
            s1.write_text(json.dumps(self._mk_summary(60.0, 20.0, "low")), encoding="utf-8")
            s2.write_text(json.dumps(self._mk_summary(70.0, 15.0, "medium")), encoding="utf-8")
            s3.write_text(json.dumps(self._mk_summary(80.0, 10.0, "high")), encoding="utf-8")

            cmd = [
                "python3",
                str(SCRIPT),
                "--summary",
                str(s1),
                "--summary",
                str(s2),
                "--summary",
                str(s3),
                "--out",
                str(out_p),
            ]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            report = json.loads(out_p.read_text(encoding="utf-8"))
            self.assertEqual(report["scenario_count"], 3)
            self.assertIn("capability_score_total_avg", report)


if __name__ == "__main__":
    unittest.main()
