#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m54_compute_micro_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m54_compute_micro_contract.py"


class ValidateTensorM54ComputeMicroContractTest(unittest.TestCase):
    def _summary(
        self,
        *,
        mem_bytes: int,
        compute: int,
        mac: int,
        any_busy: int,
        ub_stall: int,
        mem_stall: int,
        port_stall: int,
        bank_stall: int,
        bank_q: int,
    ) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_bytes_read_total": mem_bytes,
                "tensor_compute_cycles_total": compute,
                "tensor_mac_ops_total": mac,
                "tensor_program_any_busy_cycles_total": any_busy,
                "tensor_program_ub_stall_cycles_total": ub_stall,
                "tensor_program_mem_stall_cycles_total": mem_stall,
                "tensor_stall_onchip_port_cycles_total": port_stall,
                "tensor_stall_onchip_bank_conflict_cycles_total": bank_stall,
                "tensor_bank_queue_occupancy_max": bank_q,
            },
        }

    def _cfg(self, issue_width: int) -> dict:
        return {"tensor_cfg": {"tensor_program_issue_width": issue_width}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_d = root / "base"
            structural_d = root / "structural"
            dep_d = root / "dependency"
            base_d.mkdir(parents=True, exist_ok=True)
            structural_d.mkdir(parents=True, exist_ok=True)
            dep_d.mkdir(parents=True, exist_ok=True)

            base = base_d / "summary.json"
            structural = structural_d / "summary.json"
            dep = dep_d / "summary.json"

            base.write_text(
                json.dumps(
                    self._summary(
                        mem_bytes=24576,
                        compute=320,
                        mac=327680,
                        any_busy=587,
                        ub_stall=171,
                        mem_stall=107,
                        port_stall=0,
                        bank_stall=0,
                        bank_q=0,
                    )
                ),
                encoding="utf-8",
            )
            structural.write_text(
                json.dumps(
                    self._summary(
                        mem_bytes=24576,
                        compute=320,
                        mac=327680,
                        any_busy=798,
                        ub_stall=171,
                        mem_stall=107,
                        port_stall=0,
                        bank_stall=479,
                        bank_q=4,
                    )
                ),
                encoding="utf-8",
            )
            dep.write_text(
                json.dumps(
                    self._summary(
                        mem_bytes=24576,
                        compute=320,
                        mac=327680,
                        any_busy=880,
                        ub_stall=2690,
                        mem_stall=11320,
                        port_stall=0,
                        bank_stall=0,
                        bank_q=0,
                    )
                ),
                encoding="utf-8",
            )

            (base_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")
            (structural_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")
            (dep_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline",
                    str(base),
                    "--structural",
                    str(structural),
                    "--dependency",
                    str(dep),
                    "--label",
                    "x",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m54:x]", out.stdout)

    def test_fail_on_structural_stall(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            base_d = root / "base"
            structural_d = root / "structural"
            dep_d = root / "dependency"
            base_d.mkdir(parents=True, exist_ok=True)
            structural_d.mkdir(parents=True, exist_ok=True)
            dep_d.mkdir(parents=True, exist_ok=True)

            base = base_d / "summary.json"
            structural = structural_d / "summary.json"
            dep = dep_d / "summary.json"

            base.write_text(
                json.dumps(
                    self._summary(
                        mem_bytes=24576,
                        compute=320,
                        mac=327680,
                        any_busy=587,
                        ub_stall=171,
                        mem_stall=107,
                        port_stall=0,
                        bank_stall=20,
                        bank_q=1,
                    )
                ),
                encoding="utf-8",
            )
            structural.write_text(
                json.dumps(
                    self._summary(
                        mem_bytes=24576,
                        compute=320,
                        mac=327680,
                        any_busy=600,
                        ub_stall=171,
                        mem_stall=107,
                        port_stall=0,
                        bank_stall=20,
                        bank_q=1,
                    )
                ),
                encoding="utf-8",
            )
            dep.write_text(
                json.dumps(
                    self._summary(
                        mem_bytes=24576,
                        compute=320,
                        mac=327680,
                        any_busy=800,
                        ub_stall=2690,
                        mem_stall=11320,
                        port_stall=0,
                        bank_stall=0,
                        bank_q=0,
                    )
                ),
                encoding="utf-8",
            )

            (base_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")
            (structural_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")
            (dep_d / "effective_config.json").write_text(json.dumps(self._cfg(issue_width=4)), encoding="utf-8")

            out = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--baseline",
                    str(base),
                    "--structural",
                    str(structural),
                    "--dependency",
                    str(dep),
                ],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected structural stall increase", out.stderr)


if __name__ == "__main__":
    unittest.main()
