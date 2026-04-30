#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for summarize_tensor_npu_readiness_v3.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "summarize_tensor_npu_readiness_v3.py"


class SummarizeTensorNpuReadinessV3Test(unittest.TestCase):
    def _summary(self, *, score: float, distance: float, dominant: str, bottlenecks: list[str], param: str) -> dict:
        return {
            "schema_version": 1,
            "npu_tpu_readiness": {
                "capability_score_total": score,
                "distance_to_target": distance,
                "cross_layer_attribution": {
                    "dominant_layer": dominant,
                    "layer_share": {"compute": 0.3, "memory": 0.4, "noc": 0.3},
                },
                "top_bottlenecks": bottlenecks,
                "suggested_interventions": [
                    {"parameter": param, "direction": "increase", "expected_effect": "x"}
                ],
            },
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            s1 = root / "s1.json"
            s2 = root / "s2.json"
            out_p = root / "r.json"
            s1.write_text(json.dumps(self._summary(score=60.0, distance=25.0, dominant="memory", bottlenecks=["memory"], param="tensor_dma_hbm_channels")), encoding="utf-8")
            s2.write_text(json.dumps(self._summary(score=70.0, distance=15.0, dominant="noc", bottlenecks=["noc"], param="tensor_noc_bandwidth_bytes_per_cycle")), encoding="utf-8")

            proc = subprocess.run(
                ["python3", str(SCRIPT), "--summary", str(s1), "--summary", str(s2), "--out", str(out_p)],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            payload = json.loads(out_p.read_text(encoding="utf-8"))
            self.assertEqual(payload["scenario_count"], 2)
            self.assertIn("dominant_layer_distribution", payload)


if __name__ == "__main__":
    unittest.main()
