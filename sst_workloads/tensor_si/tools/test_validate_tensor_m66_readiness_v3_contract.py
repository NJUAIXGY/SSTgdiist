#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m66_readiness_v3_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m66_readiness_v3_contract.py"


class ValidateTensorM66ReadinessV3ContractTest(unittest.TestCase):
    def _report(self) -> dict:
        return {
            "schema_version": 1,
            "scenario_count": 2,
            "scenarios": [{"summary": "a"}, {"summary": "b"}],
            "capability_score_total_avg": 64.0,
            "distance_to_target_avg": 21.0,
            "readiness_level": "L1",
            "dominant_layer_distribution": {"memory": 1, "noc": 1},
            "top_bottlenecks_union": ["memory", "noc"],
            "suggested_interventions_ranked": [{"parameter": "x", "count": 2}],
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "r.json"
            p.write_text(json.dumps(self._report()), encoding="utf-8")
            out = subprocess.run(["python3", str(SCRIPT), "--report", str(p)], text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_missing_interventions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            payload = self._report()
            payload["suggested_interventions_ranked"] = []
            p = Path(td) / "r.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            out = subprocess.run(["python3", str(SCRIPT), "--report", str(p)], text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("suggested_interventions_ranked", out.stderr)


if __name__ == "__main__":
    unittest.main()
