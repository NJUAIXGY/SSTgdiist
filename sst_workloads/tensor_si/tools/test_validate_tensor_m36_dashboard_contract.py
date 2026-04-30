#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for validate_tensor_m36_dashboard_contract.py.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m36_dashboard_contract.py"


def _mk_summary(tensor: dict) -> dict:
    return {"schema_version": 1, "run_dir": "/tmp/x", "sim_time_ns": 1, "tensor": tensor, "artifacts": {"mesh_stats_csv": "/tmp/x.csv"}}


class ValidateTensorM36DashboardContractTest(unittest.TestCase):
    def test_happy_path_samples_zero_is_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tensor = {
                "tensor_compute_cycles_total": 256,
                "tensor_compute_math_cycles_total": 64,
                "tensor_compute_pipeline_cycles_total": 128,
                "tensor_dma_cycles_total": 0,
                "tensor_dma_stall_cycles_total": 0,
                "tensor_mem_reads_issued_total": 10,
                "tensor_mem_bytes_read_total": 640,
                "tensor_mem_writes_issued_total": 0,
                "tensor_mem_bytes_write_total": 0,
                "tensor_mem_read_latency_cycles_total": 0,
                "tensor_mem_read_latency_cycles_max": 0,
                "tensor_mem_read_latency_samples_total": 0,
                "tensor_mem_read_latency_cycles_avg": 0.0,
                "tensor_mem_write_latency_cycles_total": 0,
                "tensor_mem_write_latency_cycles_max": 0,
                "tensor_mem_write_latency_samples_total": 0,
                "tensor_mem_write_latency_cycles_avg": 0.0,
                "tensor_program_any_busy_cycles_total": 256,
                "tensor_program_dma_busy_cycles_total": 0,
                "tensor_program_mxu_busy_cycles_total": 256,
                "tensor_program_vec_busy_cycles_total": 0,
                "tensor_program_coll_busy_cycles_total": 0,
                "tensor_vector_cycles_total": 0,
                "tensor_collective_cycles_total": 0,
                "tensor_pkt_sent_total": 0,
                "tensor_pkt_recv_total": 0,
                "tensor_pkt_bytes_sent_total": 0,
                "tensor_pkt_bytes_recv_total": 0,
                "tensor_mxu_io_busy_cycles_total": 0,
                "tensor_stall_onchip_port_cycles_total": 0,
                "tensor_stall_onchip_bank_conflict_cycles_total": 0,
            }
            p = root / "s.json"
            p.write_text(json.dumps(_mk_summary(tensor)), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--summary", str(p), "--label", "x"]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("[m36:x]", out.stdout)

    def test_fails_when_avg_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            tensor = {
                "tensor_compute_cycles_total": 10,
                "tensor_compute_math_cycles_total": 1,
                "tensor_compute_pipeline_cycles_total": 1,
                "tensor_dma_cycles_total": 0,
                "tensor_dma_stall_cycles_total": 0,
                "tensor_mem_reads_issued_total": 2,
                "tensor_mem_bytes_read_total": 128,
                "tensor_mem_writes_issued_total": 0,
                "tensor_mem_bytes_write_total": 0,
                "tensor_mem_read_latency_cycles_total": 10,
                "tensor_mem_read_latency_cycles_max": 7,
                "tensor_mem_read_latency_samples_total": 2,
                "tensor_mem_read_latency_cycles_avg": 9.0,  # wrong (should be 5.0)
                "tensor_mem_write_latency_cycles_total": 0,
                "tensor_mem_write_latency_cycles_max": 0,
                "tensor_mem_write_latency_samples_total": 0,
                "tensor_mem_write_latency_cycles_avg": 0.0,
                "tensor_program_any_busy_cycles_total": 1,
                "tensor_program_dma_busy_cycles_total": 0,
                "tensor_program_mxu_busy_cycles_total": 1,
                "tensor_program_vec_busy_cycles_total": 0,
                "tensor_program_coll_busy_cycles_total": 0,
                "tensor_vector_cycles_total": 0,
                "tensor_collective_cycles_total": 0,
                "tensor_pkt_sent_total": 0,
                "tensor_pkt_recv_total": 0,
                "tensor_pkt_bytes_sent_total": 0,
                "tensor_pkt_bytes_recv_total": 0,
                "tensor_mxu_io_busy_cycles_total": 0,
                "tensor_stall_onchip_port_cycles_total": 0,
                "tensor_stall_onchip_bank_conflict_cycles_total": 0,
            }
            p = root / "s.json"
            p.write_text(json.dumps(_mk_summary(tensor)), encoding="utf-8")

            cmd = ["python3", str(SCRIPT), "--summary", str(p)]
            out = subprocess.run(cmd, text=True, capture_output=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("avg mismatch", out.stderr)


if __name__ == "__main__":
    unittest.main()
