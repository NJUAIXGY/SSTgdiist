#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m87_scaleout_v2_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m87_scaleout_v2_contract.py"


class ValidateTensorM87ScaleoutV2ContractTest(unittest.TestCase):
    def _summary(self, *, coll: int, pkt: int, scale: float, noc_stall: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_collective_bytes_sent_total": coll,
                "tensor_pkt_bytes_sent_total": pkt,
                "tensor_stall_noc_budget_cycles_total": noc_stall,
                "tensor_collective_backpressure_stall_cycles_total": 0,
            },
            "npu_tpu_readiness": {
                "capability_score_breakdown": {
                    "scalability": scale,
                }
            },
        }

    def _cfg(self, mesh_size: int) -> dict:
        return {"mesh_cfg": {"mesh_size": mesh_size}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            s_d = root / "single"
            m_d = root / "multi"
            s_d.mkdir(parents=True, exist_ok=True)
            m_d.mkdir(parents=True, exist_ok=True)
            (s_d / "s.json").write_text(json.dumps(self._summary(coll=100, pkt=200, scale=55.0, noc_stall=10)), encoding="utf-8")
            (m_d / "s.json").write_text(json.dumps(self._summary(coll=300, pkt=500, scale=60.0, noc_stall=100)), encoding="utf-8")
            (s_d / "effective_config.json").write_text(json.dumps(self._cfg(mesh_size=1)), encoding="utf-8")
            (m_d / "effective_config.json").write_text(json.dumps(self._cfg(mesh_size=4)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--single", str(s_d / "s.json"), "--multi", str(m_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_noc_stall(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            s_d = root / "single"
            m_d = root / "multi"
            s_d.mkdir(parents=True, exist_ok=True)
            m_d.mkdir(parents=True, exist_ok=True)
            (s_d / "s.json").write_text(json.dumps(self._summary(coll=100, pkt=200, scale=55.0, noc_stall=200)), encoding="utf-8")
            (m_d / "s.json").write_text(json.dumps(self._summary(coll=300, pkt=500, scale=60.0, noc_stall=100)), encoding="utf-8")
            (s_d / "effective_config.json").write_text(json.dumps(self._cfg(mesh_size=1)), encoding="utf-8")
            (m_d / "effective_config.json").write_text(json.dumps(self._cfg(mesh_size=4)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--single", str(s_d / "s.json"), "--multi", str(m_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("noc_stall_proxy", out.stderr)


if __name__ == "__main__":
    unittest.main()
