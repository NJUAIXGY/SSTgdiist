#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for validate_tensor_m91_readiness_mapping_contract.py."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
SCRIPT = THIS_DIR / "validate_tensor_m91_readiness_mapping_contract.py"


class ValidateTensorM91ReadinessMappingContractTest(unittest.TestCase):
    def _summary(self, *, score: float, evidence: float, conf: str) -> dict:
        return {
            "schema_version": 1,
            "tensor": {
                "tensor_program_any_busy_cycles_total": 10,
                "tensor_compute_cycles_total": 20,
                "tensor_mem_read_latency_samples_total": 8,
                "tensor_mem_cmd_rdwr_total": 8,
                "tensor_mac_ops_total": 1024,
                "tensor_program_iters_total": 1,
                "tensor_dma_cycles_total": 6,
                "tensor_effective_mac_per_cycle": 1.2,
            },
            "npu_tpu_readiness": {
                "capability_profile": "readiness_mapping_v4",
                "capability_score_total": score,
                "evidence_factor": evidence,
                "calibration_confidence": conf,
                "capability_score_breakdown": {
                    "scheduler": 50.0,
                    "dataflow": 50.0,
                    "memory": 50.0,
                    "parallelism": 50.0,
                    "scalability": 50.0,
                },
            },
        }

    def _cfg(self, mesh_size: int) -> dict:
        return {
            "mesh_cfg": {"mesh_size": mesh_size, "network_num_vns": 2},
            "tensor_cfg": {"tensor_dma_hbm_channels": 2},
        }

    def test_happy_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            c_d = root / "cfg"
            r_d = root / "rich"
            c_d.mkdir(parents=True, exist_ok=True)
            r_d.mkdir(parents=True, exist_ok=True)
            (c_d / "s.json").write_text(json.dumps(self._summary(score=50.0, evidence=0.7, conf="low")), encoding="utf-8")
            (r_d / "s.json").write_text(json.dumps(self._summary(score=60.0, evidence=0.9, conf="high")), encoding="utf-8")
            (c_d / "effective_config.json").write_text(json.dumps(self._cfg(mesh_size=2)), encoding="utf-8")
            (r_d / "effective_config.json").write_text(json.dumps(self._cfg(mesh_size=4)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--config-only", str(c_d / "s.json"), "--evidence-rich", str(r_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertEqual(out.returncode, 0, msg=out.stderr)

    def test_fail_profile(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            c_d = root / "cfg"
            r_d = root / "rich"
            c_d.mkdir(parents=True, exist_ok=True)
            r_d.mkdir(parents=True, exist_ok=True)
            cfg = self._summary(score=50.0, evidence=0.7, conf="low")
            cfg["npu_tpu_readiness"]["capability_profile"] = "bad_profile"
            (c_d / "s.json").write_text(json.dumps(cfg), encoding="utf-8")
            (r_d / "s.json").write_text(json.dumps(self._summary(score=60.0, evidence=0.9, conf="high")), encoding="utf-8")
            (c_d / "effective_config.json").write_text(json.dumps(self._cfg(mesh_size=2)), encoding="utf-8")
            (r_d / "effective_config.json").write_text(json.dumps(self._cfg(mesh_size=4)), encoding="utf-8")

            out = subprocess.run(
                ["python3", str(SCRIPT), "--config-only", str(c_d / "s.json"), "--evidence-rich", str(r_d / "s.json")],
                text=True,
                capture_output=True,
            )
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("capability_profile", out.stderr)


if __name__ == "__main__":
    unittest.main()
