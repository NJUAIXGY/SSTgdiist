#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI-level tests for write_mesh_meta.py (paper provenance).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


class WriteMeshMetaCLITest(unittest.TestCase):
    def test_writes_schema_v1_with_local_run_config_hash_and_bcsr_meta_archive(self) -> None:
        script = Path(__file__).with_name("write_mesh_meta.py")
        if not script.exists():
            # This is a feature test: failing here means the feature is not implemented yet.
            self.fail(f"missing script: {script}")

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "proj"
            run_dir = Path(td) / "run"
            root.mkdir(parents=True, exist_ok=True)
            run_dir.mkdir(parents=True, exist_ok=True)

            # Minimal local_run_config that enables BCSR route usage.
            _write_json(
                root / "local_run_config.json",
                {
                    "sim_time": "100us",
                    "num_cores_per_pe": 2,
                    "neurons_per_core": 3,  # should be overridden by BCSR rows
                    "step_activation_use_bcsr_routes": 1,
                },
            )

            # Fake BCSR dataset root with meta files only (bins are intentionally omitted for test speed).
            bcsr_root = root / "weights" / "fake_bcsr"
            _write_json(
                bcsr_root / "pe00" / "core00.bcsr.bin.meta.json",
                {"pe": 0, "core": 0, "rows": 5, "cols": 96, "br": 1, "bc": 16, "idx_bytes": 2, "val_bytes": 4},
            )
            _write_json(
                bcsr_root / "pe00" / "core01.bcsr.bin.meta.json",
                {"pe": 0, "core": 1, "rows": 5, "cols": 96, "br": 1, "bc": 16, "idx_bytes": 2, "val_bytes": 4},
            )

            sst_bin = (Path(__file__).resolve().parents[2] / "sst_install" / "bin" / "sst").resolve()
            self.assertTrue(sst_bin.exists(), msg=f"missing sst bin: {sst_bin}")

            env = dict(os.environ)
            env["MESH_BCSR_DIR"] = str(bcsr_root)
            proc = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--run-dir",
                    str(run_dir),
                    "--project-root",
                    str(root),
                    "--sst-bin",
                    str(sst_bin),
                    "--model",
                    str(root / "test_mesh_4x4.py"),
                    "--sst-nproc",
                    "32",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            meta_path = run_dir / "meta.json"
            self.assertTrue(meta_path.exists())
            meta = json.loads(meta_path.read_text(encoding="utf-8"))

            self.assertEqual(meta.get("schema_version"), 1)
            self.assertIn("inputs", meta)
            self.assertIn("local_run_config", meta["inputs"])
            lrc = meta["inputs"]["local_run_config"]
            cfg_path = run_dir / lrc["path"]
            self.assertTrue(cfg_path.exists())
            self.assertEqual(lrc["sha256"], _sha256_file(cfg_path))

            # BCSR meta archive is required when cfg enables BCSR routes.
            bcsr = meta["inputs"].get("bcsr") or {}
            self.assertTrue(bcsr.get("dataset_root"))
            meta_files = bcsr.get("meta_files") or []
            self.assertEqual(len(meta_files), 2)
            for ent in meta_files:
                p = run_dir / ent["path"]
                self.assertTrue(p.exists())
                self.assertEqual(ent["sha256"], _sha256_file(p))

            # Model should use bcsr rows override for neurons_per_core.
            model = meta.get("model") or {}
            self.assertEqual(model.get("neurons_per_core"), 5)
            self.assertEqual(model.get("neurons_per_pe"), 10)  # num_cores_per_pe * neurons_per_core

    def test_spec_first_node_limit_controls_num_pes_in_model_meta(self) -> None:
        script = Path(__file__).with_name("write_mesh_meta.py")
        if not script.exists():
            self.fail(f"missing script: {script}")

        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "run"
            run_dir.mkdir(parents=True, exist_ok=True)
            spec_path = Path(td) / "spec.json"
            _write_json(
                spec_path,
                {
                    "schema_version": 3,
                    "platform": {
                        "mesh_size": 4,
                        "node_limit": 1,
                    },
                },
            )

            project_root = Path(__file__).resolve().parents[1]
            sst_bin = (Path(__file__).resolve().parents[2] / "sst_install" / "bin" / "sst").resolve()
            self.assertTrue(sst_bin.exists(), msg=f"missing sst bin: {sst_bin}")

            env = dict(os.environ)
            env["MESH_SPEC_JSON"] = str(spec_path)
            proc = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--run-dir",
                    str(run_dir),
                    "--project-root",
                    str(project_root),
                    "--sst-bin",
                    str(sst_bin),
                    "--model",
                    str(project_root / "test_mesh_4x4.py"),
                    "--sst-nproc",
                    "1",
                ],
                text=True,
                capture_output=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            model = json.loads((run_dir / "meta.json").read_text(encoding="utf-8")).get("model") or {}
            self.assertEqual(model.get("mesh_size"), 4)
            self.assertEqual(model.get("node_limit"), 1)
            self.assertEqual(model.get("num_pes"), 1)


if __name__ == "__main__":
    unittest.main()
