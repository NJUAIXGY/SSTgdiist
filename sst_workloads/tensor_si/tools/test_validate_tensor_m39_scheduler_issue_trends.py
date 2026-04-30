#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m39_scheduler_issue_trends.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m39_scheduler_issue_trends.py"


class ValidateTensorM39SchedulerIssueTrendsTest(unittest.TestCase):
    def _mk_summary(self, dma_busy: int, any_busy: int) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_mem_bytes_read_total": 8192,
                "tensor_program_dma_busy_cycles_total": dma_busy,
                "tensor_program_any_busy_cycles_total": any_busy,
            },
        }

    def _mk_cfg(self, model: str, issue_width: int) -> dict:
        return {"tensor_cfg": {"tensor_scheduler_model": model, "tensor_program_issue_width": issue_width}}

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            aggr_d = root / "aggr"
            cons_d = root / "cons"
            aggr_d.mkdir(parents=True, exist_ok=True)
            cons_d.mkdir(parents=True, exist_ok=True)
            aggr_p = aggr_d / "summary.json"
            cons_p = cons_d / "summary.json"
            aggr_p.write_text(json.dumps(self._mk_summary(dma_busy=80, any_busy=120)), encoding="utf-8")
            cons_p.write_text(json.dumps(self._mk_summary(dma_busy=120, any_busy=180)), encoding="utf-8")
            (aggr_d / "effective_config.json").write_text(json.dumps(self._mk_cfg("greedy_dual_issue", 4)), encoding="utf-8")
            (cons_d / "effective_config.json").write_text(json.dumps(self._mk_cfg("serial_issue", 1)), encoding="utf-8")

            cmd = [
                "python3",
                str(SCRIPT),
                "--aggressive",
                str(aggr_p),
                "--conservative",
                str(cons_p),
                "--label",
                "x",
            ]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m39:x]", out.stdout)

    def test_fail_when_scheduler_models_same(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            aggr_d = root / "aggr"
            cons_d = root / "cons"
            aggr_d.mkdir(parents=True, exist_ok=True)
            cons_d.mkdir(parents=True, exist_ok=True)
            aggr_p = aggr_d / "summary.json"
            cons_p = cons_d / "summary.json"
            aggr_p.write_text(json.dumps(self._mk_summary(dma_busy=80, any_busy=120)), encoding="utf-8")
            cons_p.write_text(json.dumps(self._mk_summary(dma_busy=120, any_busy=180)), encoding="utf-8")
            (aggr_d / "effective_config.json").write_text(json.dumps(self._mk_cfg("same", 4)), encoding="utf-8")
            (cons_d / "effective_config.json").write_text(json.dumps(self._mk_cfg("same", 1)), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--aggressive", str(aggr_p), "--conservative", str(cons_p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("expected distinct scheduler models", out.stderr)


if __name__ == "__main__":
    unittest.main()
