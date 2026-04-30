#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m61_mem_cmd_v3_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m61_mem_cmd_v3_contract.py"


class ValidateTensorM61MemCmdV3ContractTest(unittest.TestCase):
    def _summary(self, *, hit: int, miss: int, conflict: int, bus_wait: int, qmax: int, qavg: float, proxy_avg: float) -> dict:
        cmd_rdwr = hit + miss + conflict
        cmd_act = miss + conflict
        cmd_pre = conflict
        cmd_issue = cmd_rdwr + cmd_act + cmd_pre
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_read_latency_samples_total": cmd_rdwr,
                "tensor_mem_row_hit_total": hit,
                "tensor_mem_row_miss_total": miss,
                "tensor_mem_row_conflict_total": conflict,
                "tensor_mem_cmd_rdwr_total": cmd_rdwr,
                "tensor_mem_cmd_act_total": cmd_act,
                "tensor_mem_cmd_pre_total": cmd_pre,
                "tensor_mem_cmd_issue_total": cmd_issue,
                "tensor_mem_cmd_bus_wait_cycles_total": bus_wait,
                "tensor_mem_cmd_queue_depth_max": qmax,
                "tensor_mem_cmd_queue_slots_avg": qavg,
                "tensor_mem_proxy_delay_avg_cycles": proxy_avg,
            },
        }

    def _cfg(self) -> dict:
        return {"tensor_cfg": {"tensor_mem_timing_model": "proxy_v3"}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            loc_d = root / "loc"
            con_d = root / "con"
            par_d = root / "par"
            loc_d.mkdir(parents=True, exist_ok=True)
            con_d.mkdir(parents=True, exist_ok=True)
            par_d.mkdir(parents=True, exist_ok=True)

            (loc_d / "s.json").write_text(json.dumps(self._summary(hit=100, miss=10, conflict=4, bus_wait=120, qmax=2, qavg=0.4, proxy_avg=18.0)), encoding="utf-8")
            (con_d / "s.json").write_text(json.dumps(self._summary(hit=40, miss=20, conflict=24, bus_wait=420, qmax=5, qavg=1.2, proxy_avg=31.0)), encoding="utf-8")
            (par_d / "s.json").write_text(json.dumps(self._summary(hit=90, miss=12, conflict=8, bus_wait=150, qmax=3, qavg=0.6, proxy_avg=19.0)), encoding="utf-8")

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
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_mode(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            loc_d = root / "loc"
            con_d = root / "con"
            par_d = root / "par"
            loc_d.mkdir(parents=True, exist_ok=True)
            con_d.mkdir(parents=True, exist_ok=True)
            par_d.mkdir(parents=True, exist_ok=True)

            summary = self._summary(hit=100, miss=10, conflict=4, bus_wait=120, qmax=2, qavg=0.4, proxy_avg=18.0)
            (loc_d / "s.json").write_text(json.dumps(summary), encoding="utf-8")
            (con_d / "s.json").write_text(json.dumps(summary), encoding="utf-8")
            (par_d / "s.json").write_text(json.dumps(summary), encoding="utf-8")

            (loc_d / "effective_config.json").write_text(json.dumps({"tensor_cfg": {"tensor_mem_timing_model": "proxy_v2"}}), encoding="utf-8")
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
            self.assertIn("tensor_mem_timing_model=proxy_v3", out.stderr)

    def test_accepts_conflict_with_lower_depth_but_higher_fill(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            loc_d = root / "loc"
            con_d = root / "con"
            par_d = root / "par"
            loc_d.mkdir(parents=True, exist_ok=True)
            con_d.mkdir(parents=True, exist_ok=True)
            par_d.mkdir(parents=True, exist_ok=True)

            (loc_d / "s.json").write_text(
                json.dumps(self._summary(hit=500, miss=80, conflict=20, bus_wait=1000, qmax=7, qavg=6.9, proxy_avg=20.0)),
                encoding="utf-8",
            )
            (con_d / "s.json").write_text(
                json.dumps(self._summary(hit=520, miss=120, conflict=60, bus_wait=5000, qmax=1, qavg=0.99, proxy_avg=80.0)),
                encoding="utf-8",
            )
            (par_d / "s.json").write_text(
                json.dumps(self._summary(hit=540, miss=70, conflict=10, bus_wait=900, qmax=7, qavg=6.2, proxy_avg=15.0)),
                encoding="utf-8",
            )

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
            self.assertEqual(out.returncode, 0, msg=out.stderr)


if __name__ == "__main__":
    unittest.main()
