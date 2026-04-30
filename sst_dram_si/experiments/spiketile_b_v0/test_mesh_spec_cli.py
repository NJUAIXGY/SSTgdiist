#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI tests for mesh_spec_cli.py.

These tests run the CLI as a subprocess to keep the contract stable and avoid
import/path ambiguity.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parents[1]
CLI = REPO_ROOT / "sst_dram_si" / "tools" / "mesh_spec_cli.py"


class MeshSpecCliTest(unittest.TestCase):
    def _write_spec(self, directory: Path, payload: dict) -> Path:
        path = directory / "spec.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, str(CLI), *args]
        return subprocess.run(cmd, text=True, capture_output=True, cwd=str(REPO_ROOT))

    def test_cli_validate_ok(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(Path(td), {"schema_version": 1})
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("OK", out.stdout)

    def test_cli_validate_rejects_invalid_spec(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(Path(td), {"schema_version": 1, "platform": {"exec_mode": "bad"}})
            out = self._run_cli("validate", str(spec_path))
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("invalid platform.exec_mode", out.stderr)

    def test_cli_resolve_prints_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(Path(td), {"schema_version": 1, "platform": {"mesh_size": 4}})
            out = self._run_cli("resolve", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            resolved = json.loads(out.stdout)
            self.assertIn("state", resolved)
            self.assertEqual(int(resolved["state"]["MESH_SIZE"]), 4)

    def test_cli_validate_ok_v2(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(Path(td), {"schema_version": 2})
            out = self._run_cli("validate", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            self.assertIn("OK", out.stdout)

    def test_cli_resolve_includes_components_overrides_v2(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            spec_path = self._write_spec(Path(td), {"schema_version": 2, "components": {"router": {"debug": 1}}})
            out = self._run_cli("resolve", str(spec_path))
            self.assertEqual(out.returncode, 0, msg=out.stderr)
            resolved = json.loads(out.stdout)
            overrides = list(resolved.get("overrides") or [])
            self.assertGreaterEqual(len(overrides), 1)
            self.assertEqual(overrides[0]["match"], {"role": "router"})
            self.assertEqual(overrides[0]["params"], {"debug": 1})

    def test_cli_roles_prints_router(self) -> None:
        out = self._run_cli("roles")
        self.assertEqual(out.returncode, 0, msg=out.stderr)
        self.assertIn("router", out.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
