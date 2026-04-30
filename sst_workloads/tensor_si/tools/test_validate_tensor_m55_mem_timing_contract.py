#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m55_mem_timing_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m55_mem_timing_contract.py"


class ValidateTensorM55MemTimingContractTest(unittest.TestCase):
    def _summary(
        self,
        *,
        mem_bytes: int,
        compute: int,
        mac: int,
        read_lat_total: int,
        read_lat_samples: int,
        row_hit: int,
        row_miss: int,
        row_conflict: int,
        queue_wait: int,
        proxy_delay: int,
        refresh_block: int,
        sched_fifo: int = 0,
        sched_frfcfs: int = 0,
    ) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_bytes_read_total": mem_bytes,
                "tensor_compute_cycles_total": compute,
                "tensor_mac_ops_total": mac,
                "tensor_mem_read_latency_cycles_total": read_lat_total,
                "tensor_mem_read_latency_samples_total": read_lat_samples,
                "tensor_mem_row_hit_total": row_hit,
                "tensor_mem_row_miss_total": row_miss,
                "tensor_mem_row_conflict_total": row_conflict,
                "tensor_mem_bank_queue_wait_cycles_total": queue_wait,
                "tensor_mem_proxy_delay_cycles_total": proxy_delay,
                "tensor_mem_refresh_block_cycles_total": refresh_block,
                "tensor_mem_sched_fifo_pick_total": sched_fifo,
                "tensor_mem_sched_frfcfs_pick_total": sched_frfcfs,
            },
        }

    def _cfg(self, issue_width: int, timing_model: str = "proxy_v2") -> dict:
        return {
            "tensor_cfg": {
                "tensor_program_issue_width": issue_width,
                "tensor_mem_timing_model": timing_model,
            }
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            loc_d = root / "locality"
            con_d = root / "conflict"
            par_d = root / "parallel"
            loc_d.mkdir(parents=True, exist_ok=True)
            con_d.mkdir(parents=True, exist_ok=True)
            par_d.mkdir(parents=True, exist_ok=True)

            loc = loc_d / "summary.json"
            con = con_d / "summary.json"
            par = par_d / "summary.json"

            loc.write_text(
                json.dumps(
                    self._summary(
                        mem_bytes=262144,
                        compute=320,
                        mac=327680,
                        read_lat_total=86000,
                        read_lat_samples=2048,
                        row_hit=1800,
                        row_miss=200,
                        row_conflict=48,
                        queue_wait=30000,
                        proxy_delay=120000,
                        refresh_block=0,
                        sched_fifo=0,
                        sched_frfcfs=2048,
                    )
                ),
                encoding="utf-8",
            )
            con.write_text(
                json.dumps(
                    self._summary(
                        mem_bytes=262144,
                        compute=320,
                        mac=327680,
                        read_lat_total=32000,
                        read_lat_samples=2048,
                        row_hit=900,
                        row_miss=200,
                        row_conflict=948,
                        queue_wait=18000,
                        proxy_delay=52000,
                        refresh_block=800,
                        sched_fifo=2048,
                        sched_frfcfs=0,
                    )
                ),
                encoding="utf-8",
            )
            par.write_text(
                json.dumps(
                    self._summary(
                        mem_bytes=262144,
                        compute=320,
                        mac=327680,
                        read_lat_total=36000,
                        read_lat_samples=2048,
                        row_hit=1700,
                        row_miss=220,
                        row_conflict=128,
                        queue_wait=2200,
                        proxy_delay=10000,
                        refresh_block=0,
                        sched_fifo=0,
                        sched_frfcfs=1024,
                    )
                ),
                encoding="utf-8",
            )

            (loc_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")
            (con_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")
            (par_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")

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
                    "--label",
                    "x",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m55:x]", out.stdout)

    def test_fail_on_timing_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            loc_d = root / "locality"
            con_d = root / "conflict"
            par_d = root / "parallel"
            loc_d.mkdir(parents=True, exist_ok=True)
            con_d.mkdir(parents=True, exist_ok=True)
            par_d.mkdir(parents=True, exist_ok=True)

            payload = self._summary(
                mem_bytes=262144,
                compute=320,
                mac=327680,
                read_lat_total=16000,
                read_lat_samples=2048,
                row_hit=1800,
                row_miss=200,
                row_conflict=48,
                queue_wait=3000,
                proxy_delay=12000,
                refresh_block=0,
            )
            loc = loc_d / "summary.json"
            con = con_d / "summary.json"
            par = par_d / "summary.json"
            loc.write_text(json.dumps(payload), encoding="utf-8")
            con.write_text(json.dumps(payload), encoding="utf-8")
            par.write_text(json.dumps(payload), encoding="utf-8")

            (loc_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4, timing_model="off")), encoding="utf-8")
            (con_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")
            (par_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")

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
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected tensor_mem_timing_model=proxy_v2", out.stderr)


if __name__ == "__main__":
    unittest.main()
