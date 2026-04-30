#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_executable(path: Path, content: str) -> None:
    _write_text(path, content)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _copy_script(source_root: Path, repo_root: Path, rel_path: str) -> None:
    src = source_root / rel_path
    dst = repo_root / rel_path
    _write_text(dst, src.read_text(encoding="utf-8"))
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR)


def _write_fake_toolchain(repo_root: Path) -> None:
    tools_dir = repo_root / "sst_dram_si" / "tools"
    _write_text(
        tools_dir / "write_mesh_meta.py",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import argparse
            import json
            import os
            from pathlib import Path

            ap = argparse.ArgumentParser()
            ap.add_argument("--run-dir", required=True)
            ap.add_argument("--project-root", required=True)
            ap.add_argument("--sst-bin", required=True)
            ap.add_argument("--model", required=True)
            ap.add_argument("--sst-nproc", required=True)
            args = ap.parse_args()

            def _boolish(raw: str):
                raw = (raw or "").strip().lower()
                if raw in ("1", "true", "yes", "y", "on"):
                    return 1
                if raw in ("0", "false", "no", "n", "off"):
                    return 0
                return None

            max_steps = None
            raw_steps = (os.environ.get("MESH_MAX_STEPS") or "").strip()
            if raw_steps:
                try:
                    max_steps = int(raw_steps)
                except Exception:
                    max_steps = None

            exec_mode = (os.environ.get("MESH_EXEC_MODE") or "").strip().lower() or "gas"
            requested_exec_mode = (os.environ.get("MESH_COMPARE_REQUESTED_EXEC_MODE") or "").strip().lower() or exec_mode
            effective_exec_mode = (os.environ.get("MESH_COMPARE_EFFECTIVE_EXEC_MODE") or "").strip().lower() or exec_mode

            payload = {
                "schema_version": 1,
                "model": {
                    "exec_mode": exec_mode,
                    "requested_exec_mode": requested_exec_mode,
                    "effective_exec_mode": effective_exec_mode,
                    "compare_role": (os.environ.get("MESH_COMPARE_ROLE") or "").strip().lower() or None,
                    "bounded_validation": _boolish(os.environ.get("MESH_COMPARE_BOUNDED_VALIDATION") or ""),
                    "max_steps": max_steps,
                },
            }
            Path(args.run_dir, "meta.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            """
        ),
    )
    _write_text(
        tools_dir / "compute_essential_summary_mesh.py",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import argparse
            import json
            from pathlib import Path

            ap = argparse.ArgumentParser()
            ap.add_argument("--run-dir", required=True)
            args = ap.parse_args()
            run_dir = Path(args.run_dir)
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            model = meta.get("model") or {}
            exec_mode = str(model.get("effective_exec_mode") or model.get("exec_mode") or "gas")
            if exec_mode == "gas":
                memory_requests = 5954.0
                memory_bytes = 381056.0
            else:
                memory_requests = 11524.0
                memory_bytes = 737536.0
            payload = {
                "memory": {
                    "memory_requests": memory_requests,
                    "memory_bytes": memory_bytes,
                }
            }
            (run_dir / "essential_summary_mesh.json").write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            """
        ),
    )
    _write_text(
        tools_dir / "summarize_atlas_activation_trace.py",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import argparse
            import json
            from pathlib import Path

            ap = argparse.ArgumentParser()
            ap.add_argument("--run-dir", required=True)
            args = ap.parse_args()
            Path(args.run_dir, "atlas_activation_trace.json").write_text(
                json.dumps({"ok": True}),
                encoding="utf-8",
            )
            """
        ),
    )
    _write_text(
        tools_dir / "validate_essential_summary_mesh.py",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import argparse
            import json
            from pathlib import Path

            ap = argparse.ArgumentParser()
            ap.add_argument("--run-dir", required=True)
            args = ap.parse_args()
            run_dir = Path(args.run_dir)
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            model = meta.get("model") or {}
            exec_mode = str(model.get("effective_exec_mode") or model.get("exec_mode") or "gas")
            warn = 1 if exec_mode == "gas" else 0
            print(f"[val] SUMMARY run_dir={run_dir} fail=0 warn={warn} strict=0")
            """
        ),
    )


def _write_fake_weights_tree(repo_root: Path) -> None:
    weights_dir = repo_root / "sst_dram_si" / "weights"
    _write_text(
        weights_dir / "bcsr_global_16pe_fanout256_10k" / "pe00" / "core00.bcsr.bin.meta.json",
        '{"rows": 4}\n',
    )


def _write_fake_library(repo_root: Path) -> None:
    lib_path = (
        repo_root
        / "sst_workspace"
        / "sst-elements"
        / "src"
        / "sst"
        / "elements"
        / "SnnDL"
        / ".libs"
        / "libSnnDL.so"
    )
    _write_text(
        lib_path,
        "\n".join(
            [
                "atlas_enable_state_local_storage_effective_total",
                "atlas_control_runtime_all_zero_total",
                "atlas_control_runtime_state_fabric_absent_total",
                "atlas_control_runtime_state_fabric_present_idle_total",
                "atlas_control_runtime_state_produced_without_queue_total",
                "atlas_control_runtime_state_queued_without_consume_total",
                "atlas_control_runtime_state_consumed_active_total",
            ]
        )
        + "\n",
    )


def _write_fake_sst(path: Path) -> None:
    _write_executable(
        path,
        textwrap.dedent(
            """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "--version" ]; then
  exit 0
fi
echo "FAKE_SST $*" >&2
exit 0
"""
        ),
    )


class RunMeshCompareSmokeMatrixCLITest(unittest.TestCase):
    def test_matrix_emits_summary_from_run_authorities(self) -> None:
        source_root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as td:
            repo_root = Path(td) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)

            for rel_path in (
                "sst_dram_si/tools/run_mesh_compare_smoke_matrix.sh",
                "sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
                "sst_dram_si/tools/run_mesh_compare_steps4_gas_smoke.sh",
                "sst_dram_si/tools/run_mesh_compare_steps4_naive_raw_smoke.sh",
                "sst_dram_si/tools/compare_acceptance_lab.py",
                "sst_dram_si/tools/mesh_library_freshness_preflight.sh",
                "sst_dram_si/tools/mesh_compare_runner_overlay.sh",
            ):
                _copy_script(source_root, repo_root, rel_path)
            _copy_script(
                source_root,
                repo_root,
                "sst_dram_si/spec_authority/compare_acceptance_gate_v1.json",
            )

            _write_text(
                repo_root / "sst_dram_si" / "local_run_config.json",
                json.dumps({"mesh_size": 4, "num_cores_per_pe": 20, "neurons_per_core": 500}, indent=2),
            )
            _write_text(repo_root / "sst_dram_si" / "test_mesh_4x4.py", "# fake model\n")
            _write_fake_toolchain(repo_root)
            _write_fake_weights_tree(repo_root)
            _write_fake_library(repo_root)
            _write_fake_sst(repo_root / "sst_install_mpi" / "bin" / "sst")

            proc = subprocess.run(
                ["bash", str(repo_root / "sst_dram_si" / "tools" / "run_mesh_compare_smoke_matrix.sh")],
                text=True,
                capture_output=True,
                cwd=str(repo_root),
                env=dict(os.environ),
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            run_dir = None
            for line in (proc.stdout + "\n" + proc.stderr).splitlines():
                if "[mesh-compare-matrix] run complete:" not in line:
                    continue
                run_dir = Path(line.split("run complete:", 1)[1].strip())
                break
            self.assertIsNotNone(run_dir, msg=proc.stdout + proc.stderr)
            assert run_dir is not None

            summary_path = run_dir / "summary.json"
            self.assertTrue(summary_path.is_file(), msg=proc.stdout + proc.stderr)
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            cases = {entry["label"]: entry for entry in summary.get("cases", [])}
            self.assertEqual(set(cases), {"gas", "naive_raw", "naive_opt"})

            report_path = repo_root / "sst_dram_si" / "references" / "compare-nightly-report.json"
            current_status_path = repo_root / "sst_dram_si" / "references" / "compare-current-status.md"
            self.assertTrue(report_path.is_file(), msg=proc.stdout + proc.stderr)
            self.assertTrue(current_status_path.is_file(), msg=proc.stdout + proc.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(report["gate_ok"])
            self.assertEqual(report["latest_case_rollups"]["naive_opt"]["effective_exec_mode"], "naive_raw")

            gas = cases["gas"]
            self.assertEqual(gas["requested_exec_mode"], "gas")
            self.assertEqual(gas["effective_exec_mode"], "gas")
            self.assertEqual(gas["compare_role"], "smoke")
            self.assertTrue(gas["bounded_validation"])
            self.assertEqual(gas["validator"], {"fail": 0, "warn": 1, "strict": 0})
            self.assertTrue(gas["memory"]["nonzero"])

            naive_raw = cases["naive_raw"]
            self.assertEqual(naive_raw["requested_exec_mode"], "naive_raw")
            self.assertEqual(naive_raw["effective_exec_mode"], "naive_raw")
            self.assertEqual(naive_raw["compare_role"], "smoke")
            self.assertTrue(naive_raw["bounded_validation"])
            self.assertEqual(naive_raw["validator"], {"fail": 0, "warn": 0, "strict": 0})
            self.assertTrue(naive_raw["memory"]["nonzero"])

            naive_opt = cases["naive_opt"]
            self.assertEqual(naive_opt["requested_exec_mode"], "naive_opt")
            self.assertEqual(naive_opt["effective_exec_mode"], "naive_raw")
            self.assertEqual(naive_opt["compare_role"], "smoke")
            self.assertTrue(naive_opt["bounded_validation"])
            self.assertEqual(naive_opt["validator"], {"fail": 0, "warn": 0, "strict": 0})
            self.assertTrue(naive_opt["memory"]["nonzero"])


if __name__ == "__main__":
    unittest.main()
