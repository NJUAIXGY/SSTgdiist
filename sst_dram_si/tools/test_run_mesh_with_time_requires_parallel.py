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
            max_steps_raw = (os.environ.get("MESH_MAX_STEPS") or "").strip()
            max_steps = None
            if max_steps_raw:
                try:
                    max_steps = int(max_steps_raw)
                except Exception:
                    max_steps = None
            exec_mode = (os.environ.get("MESH_EXEC_MODE") or "").strip().lower() or "gas"
            requested_exec_mode = (os.environ.get("MESH_COMPARE_REQUESTED_EXEC_MODE") or "").strip().lower() or exec_mode
            effective_exec_mode = (os.environ.get("MESH_COMPARE_EFFECTIVE_EXEC_MODE") or "").strip().lower() or exec_mode
            compare_role = (os.environ.get("MESH_COMPARE_ROLE") or "").strip().lower()
            bounded_raw = (os.environ.get("MESH_COMPARE_BOUNDED_VALIDATION") or "").strip().lower()
            bounded_validation = None
            if bounded_raw in ("1", "true", "yes", "y", "on"):
                bounded_validation = 1
            elif bounded_raw in ("0", "false", "no", "n", "off"):
                bounded_validation = 0
            model = {
                "exec_mode": exec_mode,
                "requested_exec_mode": requested_exec_mode,
                "effective_exec_mode": effective_exec_mode,
            }
            if max_steps is not None:
                model["max_steps"] = max_steps
            if compare_role:
                model["compare_role"] = compare_role
            if bounded_validation is not None:
                model["bounded_validation"] = bounded_validation
            Path(args.run_dir, "meta.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sst_bin": args.sst_bin,
                        "sst_nproc": args.sst_nproc,
                        "max_steps": max_steps,
                        "model": model,
                    }
                ),
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
            Path(args.run_dir, "essential_summary_mesh.json").write_text(
                json.dumps({"ok": True}),
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
            ap.add_argument("--output", default=None)
            args = ap.parse_args()
            out = Path(args.output) if args.output else Path(args.run_dir) / "atlas_activation_trace.json"
            out.write_text(json.dumps({"ok": True}), encoding="utf-8")
            """
        ),
    )
    _write_text(
        tools_dir / "validate_essential_summary_mesh.py",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            print("[val] ok")
            """
        ),
    )
    _write_text(
        tools_dir / "thermal_export.py",
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import argparse
            import os
            import sys
            from pathlib import Path

            ap = argparse.ArgumentParser()
            ap.add_argument("--run-dir", required=True)
            args = ap.parse_args()
            marker = os.environ.get("MESH_TEST_THERMAL_EXPORT_MARKER", "").strip()
            if marker:
                Path(marker).write_text(args.run_dir, encoding="utf-8")
            if os.environ.get("MESH_TEST_THERMAL_EXPORT_FAIL", "").strip() == "1":
                print("[thermal_export] synthetic failure", file=sys.stderr)
                raise SystemExit(7)
            Path(args.run_dir, "thermal_export.ok").write_text("ok", encoding="utf-8")
            """
        ),
    )


def _write_fake_weights_tree(repo_root: Path) -> Path:
    weights_dir = repo_root / "sst_dram_si" / "weights"
    _write_text(
        weights_dir / "bcsr_global_16pe_fanout256_10k" / "pe00" / "core00.bcsr.bin.meta.json",
        '{\"rows\": 4}\n',
    )
    return weights_dir


def _meta_field(meta: dict, key: str):
    if key in meta:
        return meta.get(key)
    model = meta.get("model")
    if isinstance(model, dict):
        return model.get(key)
    return None


def _write_fake_sndl_library(repo_root: Path, markers: list[str] | None = None) -> Path:
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
    payload = "\n".join(
        markers
        or [
            "atlas_enable_state_local_storage_effective_total",
            "atlas_control_runtime_all_zero_total",
            "atlas_control_runtime_state_fabric_absent_total",
            "atlas_control_runtime_state_fabric_present_idle_total",
            "atlas_control_runtime_state_produced_without_queue_total",
            "atlas_control_runtime_state_queued_without_consume_total",
            "atlas_control_runtime_state_consumed_active_total",
        ]
    )
    _write_text(lib_path, payload + "\n")
    return lib_path


def _make_fake_sst(path: Path,
                   *,
                   help_rc: int,
                   tag: str,
                   marker: str | None = None,
                   version_rc: int | None = None) -> None:
    marker_line = ""
    if marker is not None:
        marker_line = f'echo "{tag}" >> "{marker}"\n'
    resolved_version_rc = help_rc if version_rc is None else version_rc
    _write_executable(
        path,
        textwrap.dedent(
            f"""#!/usr/bin/env bash
set -euo pipefail
if [ "${{1:-}}" = "--help" ]; then
  exit {help_rc}
fi
if [ "${{1:-}}" = "--version" ]; then
  exit {resolved_version_rc}
fi
if [ -n "${{MESH_TEST_FAKE_THERMAL_ENABLE:-}}" ] && [ -n "${{MESH_RUN_DIR:-}}" ]; then
  python3 - "${{MESH_RUN_DIR}}" "${{MESH_TEST_FAKE_THERMAL_ENABLE}}" <<'PY'
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
thermal_enable = int(sys.argv[2])
payload = {{
    "thermal": {{
        "enable": thermal_enable,
        "backend": "hotspot",
        "window_ns": 1000,
        "out_dir": "thermal",
    }}
}}
Path(run_dir, "effective_config.json").write_text(json.dumps(payload), encoding="utf-8")
PY
fi
{marker_line}echo "{tag} $*" >&2
exit 0
"""
        ),
    )


class RunMeshWithTimeRequiresParallelCLITest(unittest.TestCase):
    @staticmethod
    def _extract_run_dir_from_output(proc: subprocess.CompletedProcess[str]) -> Path:
        text = proc.stdout + "\n" + proc.stderr
        for line in text.splitlines():
            marker = "run complete:"
            if marker not in line:
                continue
            return Path(line.split(marker, 1)[1].strip())
        raise AssertionError(f"unable to parse run directory from output:\n{text}")

    def _prepare_repo(self, script_name: str, model_name: str) -> tuple[Path, Path]:
        with tempfile.TemporaryDirectory() as td:
            raise AssertionError("use _run_script helper only")

    def _run_script_fixture(
        self,
        *,
        source_script_rel: str,
        target_script_rel: str,
        model_rel: str,
        script_args: list[str] | None = None,
        mpi_help_rc: int,
        mpi_version_rc: int | None = None,
        par_help_rc: int | None = None,
        par_version_rc: int | None = None,
        create_serial: bool = True,
        thermal_enable: int | None = None,
        thermal_export_fail: bool = False,
        create_sndl_library: bool = True,
        sndl_library_markers: list[str] | None = None,
        extra_env: dict[str, str] | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(tempdir.cleanup)
        repo_root = Path(tempdir.name) / "repo"
        repo_root.mkdir(parents=True, exist_ok=True)

        source_script = Path(__file__).resolve().parents[2] / source_script_rel
        target_script = repo_root / target_script_rel
        source_script_text = source_script.read_text(encoding="utf-8")
        _write_text(target_script, source_script_text)
        target_script.chmod(target_script.stat().st_mode | stat.S_IXUSR)
        for helper_name in (
            "mesh_library_freshness_preflight.sh",
            "mesh_compare_runner_overlay.sh",
        ):
            if helper_name not in source_script_text:
                continue
            helper_source = source_script.parent / helper_name
            if helper_source.exists():
                _write_text(
                    target_script.parent / helper_name,
                    helper_source.read_text(encoding="utf-8"),
                )
        for sibling_script_name in (
            "run_mesh_exec_mode_compare_with_time.sh",
        ):
            if sibling_script_name not in source_script_text:
                continue
            sibling_source = source_script.parent / sibling_script_name
            if sibling_source.exists():
                sibling_target = target_script.parent / sibling_script_name
                sibling_text = sibling_source.read_text(encoding="utf-8")
                _write_text(
                    sibling_target,
                    sibling_text,
                )
                sibling_target.chmod(sibling_target.stat().st_mode | stat.S_IXUSR)
                for helper_name in (
                    "mesh_library_freshness_preflight.sh",
                    "mesh_compare_runner_overlay.sh",
                ):
                    if helper_name not in sibling_text:
                        continue
                    helper_source = sibling_source.parent / helper_name
                    if helper_source.exists():
                        _write_text(
                            target_script.parent / helper_name,
                            helper_source.read_text(encoding="utf-8"),
                        )

        _write_text(repo_root / model_rel, "# fake model\n")
        _write_fake_weights_tree(repo_root)
        _write_fake_toolchain(repo_root)
        if create_sndl_library:
            _write_fake_sndl_library(repo_root, sndl_library_markers)

        mpi_marker = repo_root / "mpi_called.txt"
        par_marker = repo_root / "par_called.txt"
        serial_marker = repo_root / "serial_called.txt"
        _make_fake_sst(
            repo_root / "sst_install_mpi" / "bin" / "sst",
            help_rc=mpi_help_rc,
            version_rc=mpi_version_rc,
            tag="MPI",
            marker=str(mpi_marker),
        )
        if par_help_rc is not None:
            _make_fake_sst(
                repo_root / "sst_install" / "bin" / "sst",
                help_rc=par_help_rc,
                version_rc=par_version_rc,
                tag="PAR",
                marker=str(par_marker),
            )
        if create_serial:
            _make_fake_sst(
                repo_root / "sst_install_serial" / "bin" / "sst",
                help_rc=0,
                tag="SERIAL",
                marker=str(serial_marker),
            )

        run_root = repo_root / "runs"
        thermal_marker = repo_root / "thermal_export_called.txt"
        env = dict(os.environ)
        env["MESH_RUN_ROOT"] = str(run_root)
        env["MESH_TEST_THERMAL_EXPORT_MARKER"] = str(thermal_marker)
        env["MESH_TEST_THERMAL_EXPORT_FAIL"] = "1" if thermal_export_fail else "0"
        if extra_env:
            env.update(extra_env)
        if thermal_enable is not None:
            env["MESH_TEST_FAKE_THERMAL_ENABLE"] = str(int(thermal_enable))
        proc = subprocess.run(
            ["bash", str(target_script), *(script_args or [])],
            text=True,
            capture_output=True,
            cwd=str(repo_root),
            env=env,
        )
        return proc, repo_root

    def _assert_script_fails_with_stale_library(
        self,
        *,
        source_script_rel: str,
        target_script_rel: str,
        model_rel: str,
        script_args: list[str] | None = None,
    ) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel=source_script_rel,
            target_script_rel=target_script_rel,
            model_rel=model_rel,
            script_args=script_args,
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
            sndl_library_markers=["atlas_enable_state_local_storage_effective_total"],
        )
        self.assertNotEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "mpi_called.txt").exists(), msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "par_called.txt").exists(), msg=proc.stdout + proc.stderr)
        self.assertIn("library freshness", (proc.stdout + proc.stderr).lower())
        self.assertIn("atlas_control_runtime_state_fabric_absent_total", proc.stdout + proc.stderr)

    def _assert_script_can_skip_library_freshness(
        self,
        *,
        source_script_rel: str,
        target_script_rel: str,
        model_rel: str,
        script_args: list[str] | None = None,
    ) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel=source_script_rel,
            target_script_rel=target_script_rel,
            model_rel=model_rel,
            script_args=script_args,
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
            sndl_library_markers=["atlas_enable_state_local_storage_effective_total"],
            extra_env={"MESH_SKIP_LIBRARY_FRESHNESS_PREFLIGHT": "1"},
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertTrue((repo_root / "mpi_called.txt").is_file(), msg=proc.stdout + proc.stderr)
        run_dir = self._extract_run_dir_from_output(proc)
        self.assertTrue((run_dir / "atlas_activation_trace.json").is_file(), msg=proc.stdout + proc.stderr)

    def _assert_script_emits_activation_trace_sidecar(
        self,
        *,
        source_script_rel: str,
        target_script_rel: str,
        model_rel: str,
        script_args: list[str] | None = None,
    ) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel=source_script_rel,
            target_script_rel=target_script_rel,
            model_rel=model_rel,
            script_args=script_args,
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        run_dir = self._extract_run_dir_from_output(proc)
        self.assertTrue((run_dir / "atlas_activation_trace.json").is_file(), msg=proc.stdout + proc.stderr)

    def _assert_script_uses_add_lib_path(
        self,
        *,
        source_script_rel: str,
        target_script_rel: str,
        model_rel: str,
        script_args: list[str] | None = None,
    ) -> None:
        proc, _ = self._run_script_fixture(
            source_script_rel=source_script_rel,
            target_script_rel=target_script_rel,
            model_rel=model_rel,
            script_args=script_args,
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        run_dir = self._extract_run_dir_from_output(proc)
        log_text = (run_dir / "mesh_run.log").read_text(encoding="utf-8")
        self.assertIn("--add-lib-path", log_text, msg=log_text)
        self.assertIn("SnnDL/.libs", log_text, msg=log_text)

    def _assert_compare_script_writes_loader_chunk_overlay(
        self,
        *,
        source_script_rel: str,
        target_script_rel: str,
        model_rel: str,
        script_args: list[str] | None = None,
        expected_max_steps: int | None = None,
    ) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel=source_script_rel,
            target_script_rel=target_script_rel,
            model_rel=model_rel,
            script_args=script_args,
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        run_dir = self._extract_run_dir_from_output(proc)
        cfg_path = run_dir / "local_run_config.json"
        self.assertTrue(cfg_path.is_file(), msg=proc.stdout + proc.stderr)
        import json

        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        self.assertEqual(cfg.get("loader_chunk_bytes"), 65536, msg=cfg_path.read_text(encoding="utf-8"))
        weights_path = run_dir / "weights"
        expected_weights_path = repo_root / "sst_dram_si" / "weights"
        self.assertTrue(weights_path.exists(), msg=proc.stdout + proc.stderr)
        self.assertTrue(weights_path.is_symlink(), msg=str(weights_path))
        self.assertEqual(weights_path.resolve(), expected_weights_path.resolve(), msg=str(weights_path))
        if expected_max_steps is not None:
            meta_path = run_dir / "meta.json"
            self.assertTrue(meta_path.is_file(), msg=proc.stdout + proc.stderr)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertEqual(_meta_field(meta, "max_steps"), expected_max_steps, msg=meta_path.read_text(encoding="utf-8"))

    def _assert_compare_script_writes_meta_authority(
        self,
        *,
        source_script_rel: str,
        target_script_rel: str,
        model_rel: str,
        script_args: list[str] | None = None,
        expected_requested_exec_mode: str,
        expected_effective_exec_mode: str,
        expected_compare_role: str,
        expected_bounded_validation: int,
        expected_max_steps: int,
    ) -> None:
        proc, _ = self._run_script_fixture(
            source_script_rel=source_script_rel,
            target_script_rel=target_script_rel,
            model_rel=model_rel,
            script_args=script_args,
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        run_dir = self._extract_run_dir_from_output(proc)
        meta_path = run_dir / "meta.json"
        self.assertTrue(meta_path.is_file(), msg=proc.stdout + proc.stderr)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        self.assertEqual(_meta_field(meta, "requested_exec_mode"), expected_requested_exec_mode, msg=meta_path.read_text(encoding="utf-8"))
        self.assertEqual(_meta_field(meta, "effective_exec_mode"), expected_effective_exec_mode, msg=meta_path.read_text(encoding="utf-8"))
        self.assertEqual(_meta_field(meta, "compare_role"), expected_compare_role, msg=meta_path.read_text(encoding="utf-8"))
        self.assertEqual(_meta_field(meta, "bounded_validation"), expected_bounded_validation, msg=meta_path.read_text(encoding="utf-8"))
        self.assertEqual(_meta_field(meta, "max_steps"), expected_max_steps, msg=meta_path.read_text(encoding="utf-8"))

    def _assert_prefers_parallel_when_mpi_is_unrunnable_but_parallel_works(
        self,
        *,
        source_script_rel: str,
        target_script_rel: str,
        model_rel: str,
        script_args: list[str] | None = None,
    ) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel=source_script_rel,
            target_script_rel=target_script_rel,
            model_rel=model_rel,
            script_args=script_args,
            mpi_help_rc=0,
            mpi_version_rc=1,
            par_help_rc=0,
            par_version_rc=0,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertTrue((repo_root / "par_called.txt").is_file(), msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "mpi_called.txt").exists(), msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "serial_called.txt").exists(), msg=proc.stdout + proc.stderr)

    def _assert_refuses_serial_when_no_parallel_is_runnable(
        self,
        *,
        source_script_rel: str,
        target_script_rel: str,
        model_rel: str,
        script_args: list[str] | None = None,
    ) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel=source_script_rel,
            target_script_rel=target_script_rel,
            model_rel=model_rel,
            script_args=script_args,
            mpi_help_rc=0,
            mpi_version_rc=1,
            par_help_rc=0,
            par_version_rc=1,
            create_serial=True,
        )
        self.assertNotEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "mpi_called.txt").exists(), msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "par_called.txt").exists(), msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "serial_called.txt").exists(), msg=proc.stdout + proc.stderr)
        msg = (proc.stdout + proc.stderr).lower()
        self.assertIn("serial", msg)
        self.assertTrue("mpi" in msg or "parallel" in msg, msg=msg)

    def _run_script(
        self,
        script_name: str,
        model_name: str,
        *,
        mpi_help_rc: int,
        mpi_version_rc: int | None = None,
        par_help_rc: int | None = None,
        par_version_rc: int | None = None,
        create_serial: bool = True,
        thermal_enable: int | None = None,
        thermal_export_fail: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        proc, _ = self._run_script_fixture(
            source_script_rel=f"sst_dram_si/tools/{script_name}",
            target_script_rel=f"sst_dram_si/tools/{script_name}",
            model_rel=f"sst_dram_si/{model_name}",
            mpi_help_rc=mpi_help_rc,
            mpi_version_rc=mpi_version_rc,
            par_help_rc=par_help_rc,
            par_version_rc=par_version_rc,
            create_serial=create_serial,
            thermal_enable=thermal_enable,
            thermal_export_fail=thermal_export_fail,
            create_sndl_library=True,
            sndl_library_markers=None,
            extra_env=None,
        )
        return proc

    def test_run_mesh_with_time_fails_instead_of_falling_back_to_serial(self) -> None:
        proc = self._run_script(
            "run_mesh_with_time.sh",
            "test_mesh_4x4.py",
            mpi_help_rc=1,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertNotEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        msg = (proc.stdout + proc.stderr).lower()
        self.assertIn("serial", msg)
        self.assertTrue("mpi" in msg or "parallel" in msg, msg=msg)

    def test_run_mesh_with_time_uses_parallel_when_mpi_is_available(self) -> None:
        proc = self._run_script(
            "run_mesh_with_time.sh",
            "test_mesh_4x4.py",
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("[mesh] run complete:", proc.stdout)
        self.assertNotIn("serial", proc.stderr.lower())

    def test_run_mesh_with_time_uses_parallel_when_mpi_help_fails_but_version_succeeds(self) -> None:
        proc = self._run_script(
            "run_mesh_with_time.sh",
            "test_mesh_4x4.py",
            mpi_help_rc=1,
            mpi_version_rc=0,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertIn("[mesh] run complete:", proc.stdout)
        self.assertNotIn("serial", proc.stderr.lower())

    def test_run_mesh_with_time_fails_when_sndl_library_is_stale(self) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel="sst_dram_si/tools/run_mesh_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
            sndl_library_markers=["atlas_enable_state_local_storage_effective_total"],
        )
        self.assertNotEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "mpi_called.txt").exists(), msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "par_called.txt").exists(), msg=proc.stdout + proc.stderr)
        self.assertIn("library freshness", (proc.stdout + proc.stderr).lower())
        self.assertIn("atlas_control_runtime_state_fabric_absent_total", proc.stdout + proc.stderr)

    def test_run_mesh_with_time_can_skip_sndl_library_freshness_preflight(self) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel="sst_dram_si/tools/run_mesh_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
            sndl_library_markers=["atlas_enable_state_local_storage_effective_total"],
            extra_env={"MESH_SKIP_LIBRARY_FRESHNESS_PREFLIGHT": "1"},
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertTrue((repo_root / "mpi_called.txt").is_file(), msg=proc.stdout + proc.stderr)

    def test_run_mesh_with_time_emits_atlas_activation_trace_sidecar(self) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel="sst_dram_si/tools/run_mesh_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        run_dirs = sorted((repo_root / "runs").glob("*"))
        self.assertEqual(len(run_dirs), 1, msg=proc.stdout + proc.stderr)
        self.assertTrue((run_dirs[0] / "atlas_activation_trace.json").is_file(), msg=proc.stdout + proc.stderr)

    def test_run_mesh_with_time_ram2_fails_instead_of_falling_back_to_serial(self) -> None:
        proc = self._run_script(
            "run_mesh_with_time_ram2.sh",
            "test_mesh_4x4_ram2.py",
            mpi_help_rc=1,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertNotEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        msg = (proc.stdout + proc.stderr).lower()
        self.assertIn("serial", msg)
        self.assertTrue("mpi" in msg or "parallel" in msg, msg=msg)

    def test_run_mesh_with_time_ram2_fails_when_sndl_library_is_stale(self) -> None:
        self._assert_script_fails_with_stale_library(
            source_script_rel="sst_dram_si/tools/run_mesh_with_time_ram2.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_with_time_ram2.sh",
            model_rel="sst_dram_si/test_mesh_4x4_ram2.py",
        )

    def test_run_mesh_with_time_ram2_can_skip_sndl_library_freshness_preflight(self) -> None:
        self._assert_script_can_skip_library_freshness(
            source_script_rel="sst_dram_si/tools/run_mesh_with_time_ram2.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_with_time_ram2.sh",
            model_rel="sst_dram_si/test_mesh_4x4_ram2.py",
        )

    def test_run_mesh_with_time_ram2_emits_atlas_activation_trace_sidecar(self) -> None:
        self._assert_script_emits_activation_trace_sidecar(
            source_script_rel="sst_dram_si/tools/run_mesh_with_time_ram2.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_with_time_ram2.sh",
            model_rel="sst_dram_si/test_mesh_4x4_ram2.py",
        )

    def test_run_mesh_with_time_ram2_uses_add_lib_path_for_freshness_matched_library(self) -> None:
        self._assert_script_uses_add_lib_path(
            source_script_rel="sst_dram_si/tools/run_mesh_with_time_ram2.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_with_time_ram2.sh",
            model_rel="sst_dram_si/test_mesh_4x4_ram2.py",
        )

    def test_run_mesh_with_time_invokes_thermal_export_when_enabled_and_keeps_run_alive(self) -> None:
        proc = self._run_script(
            "run_mesh_with_time.sh",
            "test_mesh_4x4.py",
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
            thermal_enable=1,
            thermal_export_fail=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        marker = Path(proc.args[-1]).parent.parent.parent / "thermal_export_called.txt"
        self.assertTrue(marker.is_file(), msg=proc.stdout + proc.stderr)
        self.assertIn("synthetic failure", proc.stdout + proc.stderr)

    def test_run_mesh_with_time_skips_thermal_export_when_disabled(self) -> None:
        proc = self._run_script(
            "run_mesh_with_time.sh",
            "test_mesh_4x4.py",
            mpi_help_rc=0,
            par_help_rc=None,
            create_serial=True,
            thermal_enable=0,
            thermal_export_fail=False,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        marker = Path(proc.args[-1]).parent.parent.parent / "thermal_export_called.txt"
        self.assertFalse(marker.exists(), msg=proc.stdout + proc.stderr)

    def test_run_dense_microbench_1pe_prefers_mpi_when_help_fails_but_version_succeeds(self) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel="sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh",
            model_rel="sst_dram_si/microbench_dense_1pe/test_dense_microbench.py",
            mpi_help_rc=1,
            mpi_version_rc=0,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertTrue((repo_root / "mpi_called.txt").is_file(), msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "serial_called.txt").exists(), msg=proc.stdout + proc.stderr)

    def test_run_dense_microbench_4x4_prefers_mpi_when_help_fails_but_version_succeeds(self) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel="sst_dram_si/tools/run_dense_microbench_4x4_exec_mode_compare_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_dense_microbench_4x4_exec_mode_compare_with_time.sh",
            model_rel="sst_dram_si/microbench_dense_4x4/test_dense_microbench.py",
            mpi_help_rc=1,
            mpi_version_rc=0,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertTrue((repo_root / "mpi_called.txt").is_file(), msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "serial_called.txt").exists(), msg=proc.stdout + proc.stderr)

    def test_run_spiketile_prefers_mpi_when_help_fails_but_version_succeeds(self) -> None:
        proc, repo_root = self._run_script_fixture(
            source_script_rel="sst_dram_si/experiments/spiketile_b_v0/run_spiketile_with_time.sh",
            target_script_rel="sst_dram_si/experiments/spiketile_b_v0/run_spiketile_with_time.sh",
            model_rel="sst_dram_si/experiments/spiketile_b_v0/test_mesh_4x4_spiketile.py",
            mpi_help_rc=1,
            mpi_version_rc=0,
            par_help_rc=None,
            create_serial=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertTrue((repo_root / "mpi_called.txt").is_file(), msg=proc.stdout + proc.stderr)
        self.assertFalse((repo_root / "serial_called.txt").exists(), msg=proc.stdout + proc.stderr)

    def test_run_mesh_exec_mode_compare_uses_parallel_when_mpi_is_unrunnable(self) -> None:
        self._assert_prefers_parallel_when_mpi_is_unrunnable_but_parallel_works(
            source_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_exec_mode_compare_refuses_serial_when_no_parallel_is_runnable(self) -> None:
        self._assert_refuses_serial_when_no_parallel_is_runnable(
            source_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_exec_mode_compare_fails_when_sndl_library_is_stale(self) -> None:
        self._assert_script_fails_with_stale_library(
            source_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_exec_mode_compare_can_skip_sndl_library_freshness_preflight(self) -> None:
        self._assert_script_can_skip_library_freshness(
            source_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_exec_mode_compare_emits_atlas_activation_trace_sidecar(self) -> None:
        self._assert_script_emits_activation_trace_sidecar(
            source_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_exec_mode_compare_uses_add_lib_path_for_freshness_matched_library(self) -> None:
        self._assert_script_uses_add_lib_path(
            source_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_exec_mode_compare_writes_loader_chunk_overlay(self) -> None:
        self._assert_compare_script_writes_loader_chunk_overlay(
            source_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_gas_uses_parallel_when_mpi_is_unrunnable(self) -> None:
        self._assert_prefers_parallel_when_mpi_is_unrunnable_but_parallel_works(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_gas_refuses_serial_when_no_parallel_is_runnable(self) -> None:
        self._assert_refuses_serial_when_no_parallel_is_runnable(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_gas_fails_when_sndl_library_is_stale(self) -> None:
        self._assert_script_fails_with_stale_library(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_gas_can_skip_sndl_library_freshness_preflight(self) -> None:
        self._assert_script_can_skip_library_freshness(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_gas_emits_atlas_activation_trace_sidecar(self) -> None:
        self._assert_script_emits_activation_trace_sidecar(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_gas_uses_add_lib_path_for_freshness_matched_library(self) -> None:
        self._assert_script_uses_add_lib_path(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_gas_writes_loader_chunk_overlay(self) -> None:
        self._assert_compare_script_writes_loader_chunk_overlay(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_gas_smoke_uses_parallel_when_mpi_is_unrunnable(self) -> None:
        self._assert_prefers_parallel_when_mpi_is_unrunnable_but_parallel_works(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas_smoke.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas_smoke.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_gas_smoke_emits_atlas_activation_trace_sidecar(self) -> None:
        self._assert_script_emits_activation_trace_sidecar(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas_smoke.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas_smoke.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_gas_smoke_writes_loader_chunk_overlay_and_smoke_steps(self) -> None:
        self._assert_compare_script_writes_loader_chunk_overlay(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas_smoke.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas_smoke.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
            expected_max_steps=1,
        )

    def test_run_mesh_compare_steps4_naive_raw_uses_parallel_when_mpi_is_unrunnable(self) -> None:
        self._assert_prefers_parallel_when_mpi_is_unrunnable_but_parallel_works(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_raw_refuses_serial_when_no_parallel_is_runnable(self) -> None:
        self._assert_refuses_serial_when_no_parallel_is_runnable(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_raw_fails_when_sndl_library_is_stale(self) -> None:
        self._assert_script_fails_with_stale_library(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_raw_emits_atlas_activation_trace_sidecar(self) -> None:
        self._assert_script_emits_activation_trace_sidecar(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_raw_uses_add_lib_path_for_freshness_matched_library(self) -> None:
        self._assert_script_uses_add_lib_path(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_raw_writes_loader_chunk_overlay(self) -> None:
        self._assert_compare_script_writes_loader_chunk_overlay(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_raw_smoke_uses_parallel_when_mpi_is_unrunnable(self) -> None:
        self._assert_prefers_parallel_when_mpi_is_unrunnable_but_parallel_works(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw_smoke.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw_smoke.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_raw_smoke_emits_atlas_activation_trace_sidecar(self) -> None:
        self._assert_script_emits_activation_trace_sidecar(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw_smoke.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw_smoke.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_raw_smoke_writes_loader_chunk_overlay_and_smoke_steps(self) -> None:
        self._assert_compare_script_writes_loader_chunk_overlay(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw_smoke.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_raw_smoke.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
            expected_max_steps=1,
        )

    def test_run_mesh_compare_steps4_naive_opt_uses_parallel_when_mpi_is_unrunnable(self) -> None:
        self._assert_prefers_parallel_when_mpi_is_unrunnable_but_parallel_works(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_opt_refuses_serial_when_no_parallel_is_runnable(self) -> None:
        self._assert_refuses_serial_when_no_parallel_is_runnable(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_opt_fails_when_sndl_library_is_stale(self) -> None:
        self._assert_script_fails_with_stale_library(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_opt_emits_atlas_activation_trace_sidecar(self) -> None:
        self._assert_script_emits_activation_trace_sidecar(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_opt_uses_add_lib_path_for_freshness_matched_library(self) -> None:
        self._assert_script_uses_add_lib_path(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_compare_steps4_naive_opt_writes_loader_chunk_overlay(self) -> None:
        self._assert_compare_script_writes_loader_chunk_overlay(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_naive_opt.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
        )

    def test_run_mesh_exec_mode_compare_writes_smoke_meta_authority(self) -> None:
        self._assert_compare_script_writes_meta_authority(
            source_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_exec_mode_compare_with_time.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
            script_args=["naive_opt"],
            expected_requested_exec_mode="naive_opt",
            expected_effective_exec_mode="naive_raw",
            expected_compare_role="smoke",
            expected_bounded_validation=1,
            expected_max_steps=1,
        )

    def test_run_mesh_compare_steps4_gas_writes_full_meta_authority(self) -> None:
        self._assert_compare_script_writes_meta_authority(
            source_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            target_script_rel="sst_dram_si/tools/run_mesh_compare_steps4_gas.sh",
            model_rel="sst_dram_si/test_mesh_4x4.py",
            expected_requested_exec_mode="gas",
            expected_effective_exec_mode="gas",
            expected_compare_role="full",
            expected_bounded_validation=0,
            expected_max_steps=4,
        )

    def test_run_singlepe_with_time_uses_parallel_when_mpi_is_unrunnable(self) -> None:
        self._assert_prefers_parallel_when_mpi_is_unrunnable_but_parallel_works(
            source_script_rel="sst_dram_si/tools/run_singlepe_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_singlepe_with_time.sh",
            model_rel="sst_dram_si/test_dram_si_single_pe.py",
            script_args=["/tmp/does-not-need-to-exist-for-selection"],
        )

    def test_run_singlepe_with_time_refuses_serial_when_no_parallel_is_runnable(self) -> None:
        self._assert_refuses_serial_when_no_parallel_is_runnable(
            source_script_rel="sst_dram_si/tools/run_singlepe_with_time.sh",
            target_script_rel="sst_dram_si/tools/run_singlepe_with_time.sh",
            model_rel="sst_dram_si/test_dram_si_single_pe.py",
            script_args=["/tmp/does-not-need-to-exist-for-selection"],
        )


if __name__ == "__main__":
    unittest.main()
