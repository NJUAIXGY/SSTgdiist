#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m57_mem_cmd_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m57_mem_cmd_contract.py"


class ValidateTensorM57MemCmdContractTest(unittest.TestCase):
    def _summary(self, *, hit: int, miss: int, conflict: int, row_service: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_read_latency_samples_total": hit + miss + conflict,
                "tensor_mem_row_hit_total": hit,
                "tensor_mem_row_miss_total": miss,
                "tensor_mem_row_conflict_total": conflict,
                "tensor_mem_cmd_act_total": miss + conflict,
                "tensor_mem_cmd_pre_total": conflict,
                "tensor_mem_cmd_rdwr_total": hit + miss + conflict,
                "tensor_mem_row_service_cycles_total": row_service,
                "tensor_mem_row_service_avg_cycles": float(row_service) / float(max(1, hit + miss + conflict)),
            },
        }

    def _cfg(self) -> dict:
        return {"tensor_cfg": {"tensor_mem_timing_model": "proxy_v2"}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            loc_d = root / "loc"
            con_d = root / "con"
            par_d = root / "par"
            loc_d.mkdir(parents=True, exist_ok=True)
            con_d.mkdir(parents=True, exist_ok=True)
            par_d.mkdir(parents=True, exist_ok=True)

            loc = loc_d / "s.json"
            con = con_d / "s.json"
            par = par_d / "s.json"

            loc.write_text(json.dumps(self._summary(hit=1800, miss=200, conflict=48, row_service=18000)), encoding="utf-8")
            con.write_text(json.dumps(self._summary(hit=900, miss=200, conflict=948, row_service=82000)), encoding="utf-8")
            par.write_text(json.dumps(self._summary(hit=1700, miss=220, conflict=128, row_service=30000)), encoding="utf-8")

            (loc_d / "effective_config.json").write_text(json.dumps(self._cfg()), encoding="utf-8")
            (con_d / "effective_config.json").write_text(json.dumps(self._cfg()), encoding="utf-8")
            (par_d / "effective_config.json").write_text(json.dumps(self._cfg()), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--locality",
                    str(loc),
                    "--conflict",
                    str(con),
                    "--parallel",
                    str(par),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_identity(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            loc_d = root / "loc"
            con_d = root / "con"
            par_d = root / "par"
            loc_d.mkdir(parents=True, exist_ok=True)
            con_d.mkdir(parents=True, exist_ok=True)
            par_d.mkdir(parents=True, exist_ok=True)

            bad = self._summary(hit=10, miss=5, conflict=2, row_service=100)
            bad["tensor"]["tensor_mem_cmd_rdwr_total"] = 1
            (loc_d / "s.json").write_text(json.dumps(bad), encoding="utf-8")
            (con_d / "s.json").write_text(json.dumps(self._summary(hit=20, miss=5, conflict=10, row_service=500)), encoding="utf-8")
            (par_d / "s.json").write_text(json.dumps(self._summary(hit=18, miss=5, conflict=4, row_service=220)), encoding="utf-8")

            (loc_d / "effective_config.json").write_text(json.dumps(self._cfg()), encoding="utf-8")
            (con_d / "effective_config.json").write_text(json.dumps(self._cfg()), encoding="utf-8")
            (par_d / "effective_config.json").write_text(json.dumps(self._cfg()), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--locality",
                    str(loc_d / "s.json"),
                    "--conflict",
                    str(con_d / "s.json"),
                    "--parallel",
                    str(par_d / "s.json"),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected cmd_rdwr == row_total", out.stderr)


if __name__ == "__main__":
    unittest.main()
