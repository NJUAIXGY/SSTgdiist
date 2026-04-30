#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI-level tests for gate_ab_isolation_matrix.py.

We test the command line entrypoint to ensure:
- latest-run discovery works
- polluted variants are marked INCONCLUSIVE with matrix_mismatch reasons
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _mk_run(root: Path, run_id: str, summary: dict, meta: dict | None = None) -> Path:
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "essential_summary_mesh.json", summary)
    if meta is not None:
        _write_json(run_dir / "meta.json", meta)
    return run_dir


class GateABIsolationMatrixCLITest(unittest.TestCase):
    def _run_gate(
        self,
        baseline_root: Path,
        a_root: Path,
        b_root: Path,
        ab_root: Path,
        fired_rel_tol: float = 0.0,
        fired_pass_rel_tol: float | None = None,
        fired_warn_rel_tol: float | None = None,
        baseline_run: str | None = None,
        a_run: str | None = None,
        b_run: str | None = None,
        ab_run: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("gate_ab_isolation_matrix.py")
        cmd = [
            "python3",
            str(script),
            "--baseline-root",
            str(baseline_root),
            "--a-root",
            str(a_root),
            "--b-root",
            str(b_root),
            "--ab-root",
            str(ab_root),
            "--fired-rel-tol",
            str(fired_rel_tol),
        ]
        if fired_pass_rel_tol is not None:
            cmd.extend(["--fired-pass-rel-tol", str(fired_pass_rel_tol)])
        if fired_warn_rel_tol is not None:
            cmd.extend(["--fired-warn-rel-tol", str(fired_warn_rel_tol)])
        if baseline_run is not None:
            cmd.extend(["--baseline-run", baseline_run])
        if a_run is not None:
            cmd.extend(["--a-run", a_run])
        if b_run is not None:
            cmd.extend(["--b-run", b_run])
        if ab_run is not None:
            cmd.extend(["--ab-run", ab_run])
        return subprocess.run(cmd, text=True, capture_output=True)

    def test_marks_inconclusive_on_inj_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            base_root = td_path / "baseline"
            a_root = td_path / "A"
            b_root = td_path / "B"
            ab_root = td_path / "AB"

            # Minimal baseline summary with all gate keys present.
            baseline = {
                "step": {"global_steps_done": 1},
                "step_activation": {
                    "spikes_injected_total": 100,
                    "pre_selected_total": 10,
                    "spike_attempts_total": 40,
                    "route_hits_total": 39,
                    "route_misses_total": 1,
                    "local_drops_total": 0,
                },
                "spike_activity": {"total_spikes_processed": 1000, "neurons_fired_total": 777},
                "experiment": {"profile": "universal_core_eval"},
            }
            good = json.loads(json.dumps(baseline))
            bad_inj = json.loads(json.dumps(baseline))
            bad_inj["step_activation"]["spikes_injected_total"] = 101

            _mk_run(base_root, "20260101-000000", baseline)
            _mk_run(a_root, "20260101-000000", bad_inj)
            _mk_run(b_root, "20260101-000000", good)
            _mk_run(ab_root, "20260101-000000", good)

            proc = self._run_gate(base_root, a_root, b_root, ab_root, fired_rel_tol=0.0)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            a_summary = _read_json(a_root / "20260101-000000" / "essential_summary_mesh.json")
            self.assertIsInstance(a_summary, dict)
            exp = a_summary.get("experiment")
            self.assertIsInstance(exp, dict)
            self.assertEqual(exp.get("verdict"), "INCONCLUSIVE")
            reasons = exp.get("reasons")
            self.assertIsInstance(reasons, list)
            joined = "\n".join(str(x) for x in reasons)
            self.assertIn("matrix_mismatch:spikes_injected_total", joined)

    def test_allows_small_fired_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            base_root = td_path / "baseline"
            a_root = td_path / "A"
            b_root = td_path / "B"
            ab_root = td_path / "AB"

            baseline = {
                "step": {"global_steps_done": 1},
                "step_activation": {
                    "spikes_injected_total": 100,
                    "pre_selected_total": 10,
                    "spike_attempts_total": 40,
                    "route_hits_total": 39,
                    "route_misses_total": 1,
                    "local_drops_total": 0,
                },
                "spike_activity": {"total_spikes_processed": 1000, "neurons_fired_total": 100000},
                "experiment": {"profile": "universal_core_eval"},
            }
            slight = json.loads(json.dumps(baseline))
            slight["spike_activity"]["neurons_fired_total"] = 99950  # -0.05%

            _mk_run(base_root, "20260101-000000", baseline)
            _mk_run(a_root, "20260101-000000", slight)
            _mk_run(b_root, "20260101-000000", slight)
            _mk_run(ab_root, "20260101-000000", slight)

            proc = self._run_gate(base_root, a_root, b_root, ab_root, fired_rel_tol=0.001)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            # No INCONCLUSIVE should be written for these variants.
            for root in (a_root, b_root, ab_root):
                s = _read_json(root / "20260101-000000" / "essential_summary_mesh.json")
                exp = s.get("experiment") if isinstance(s, dict) else None
                verdict = exp.get("verdict") if isinstance(exp, dict) else ""
                self.assertNotEqual(verdict, "INCONCLUSIVE")

    def test_warn_band_for_medium_fired_drift(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            base_root = td_path / "baseline"
            a_root = td_path / "A"
            b_root = td_path / "B"
            ab_root = td_path / "AB"

            baseline = {
                "step": {"global_steps_done": 1},
                "step_activation": {
                    "spikes_injected_total": 100,
                    "pre_selected_total": 10,
                    "spike_attempts_total": 40,
                    "route_hits_total": 39,
                    "route_misses_total": 1,
                    "local_drops_total": 0,
                },
                "spike_activity": {"total_spikes_processed": 1000, "neurons_fired_total": 100000},
                "experiment": {"profile": "universal_core_eval"},
            }
            medium = json.loads(json.dumps(baseline))
            medium["spike_activity"]["neurons_fired_total"] = 99400  # -0.6%

            _mk_run(base_root, "20260101-000000", baseline)
            _mk_run(a_root, "20260101-000000", medium)
            _mk_run(b_root, "20260101-000000", medium)
            _mk_run(ab_root, "20260101-000000", medium)

            proc = self._run_gate(
                base_root,
                a_root,
                b_root,
                ab_root,
                fired_pass_rel_tol=0.005,
                fired_warn_rel_tol=0.01,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("matrix_gate: WARN", proc.stdout)

            for root in (a_root, b_root, ab_root):
                s = _read_json(root / "20260101-000000" / "essential_summary_mesh.json")
                exp = s.get("experiment") if isinstance(s, dict) else None
                verdict = exp.get("verdict") if isinstance(exp, dict) else ""
                self.assertEqual(verdict, "WARN")
                reasons = exp.get("reasons") if isinstance(exp, dict) else None
                self.assertIsInstance(reasons, list)
                self.assertTrue(any(str(r).startswith("matrix_warn:neurons_fired_total:") for r in reasons))

    def test_explicit_run_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            base_root = td_path / "baseline"
            a_root = td_path / "A"
            b_root = td_path / "B"
            ab_root = td_path / "AB"

            baseline_old = {
                "step": {"global_steps_done": 1},
                "step_activation": {
                    "spikes_injected_total": 100,
                    "pre_selected_total": 10,
                    "spike_attempts_total": 40,
                    "route_hits_total": 39,
                    "route_misses_total": 1,
                    "local_drops_total": 0,
                },
                "spike_activity": {"total_spikes_processed": 1000, "neurons_fired_total": 1000},
                "experiment": {"profile": "universal_core_eval"},
            }
            baseline_new = json.loads(json.dumps(baseline_old))
            baseline_new["step_activation"]["spikes_injected_total"] = 200

            same_as_old = json.loads(json.dumps(baseline_old))
            same_as_new = json.loads(json.dumps(baseline_new))

            _mk_run(base_root, "20260101-000000", baseline_old)
            _mk_run(base_root, "20260102-000000", baseline_new)
            _mk_run(a_root, "20260101-000000", same_as_old)
            _mk_run(a_root, "20260102-000000", same_as_new)
            _mk_run(b_root, "20260101-000000", same_as_old)
            _mk_run(b_root, "20260102-000000", same_as_new)
            _mk_run(ab_root, "20260101-000000", same_as_old)
            _mk_run(ab_root, "20260102-000000", same_as_new)

            # Force gating on the old run ids instead of latest.
            proc = self._run_gate(
                base_root,
                a_root,
                b_root,
                ab_root,
                fired_rel_tol=0.0,
                baseline_run="20260101-000000",
                a_run="20260101-000000",
                b_run="20260101-000000",
                ab_run="20260101-000000",
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
            self.assertIn("20260101-000000", proc.stdout)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
