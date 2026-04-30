#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class RunThermalContractSuiteCLITest(unittest.TestCase):
    def test_canonical_manifest_lists_expected_cases_and_contract_checks(self) -> None:
        manifest_path = Path(__file__).resolve().parents[2] / "tools" / "specs" / "mesh_hotspot_thermal_contract_suite_v1.json"
        self.assertTrue(manifest_path.is_file(), msg=f"missing manifest: {manifest_path}")

        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["suite_contract_version"], "v1")
        cases = list(payload.get("cases") or [])
        self.assertEqual(
            [str(case.get("case_id") or "") for case in cases],
            [
                "thermal_2d_block_base",
                "thermal_3d_grid_base",
                "thermal_3d_grid_csv_source",
                "thermal_3d_grid_stats_prefix",
                "thermal_3d_grid_power_source",
            ],
        )
        for case in cases:
            self.assertTrue(str(case.get("spec_path") or "").strip(), msg=case)
            expectations = dict(case.get("expectations") or {})
            self.assertIn("require_window_power_samples", expectations, msg=case)
            self.assertIn("require_layer_stack_validation", expectations, msg=case)
            self.assertIn("hotspot_model_type", expectations, msg=case)

    def test_runner_executes_case_chain_and_writes_result_manifest(self) -> None:
        script = Path(__file__).with_name("run_thermal_contract_suite.py")
        self.assertTrue(script.exists(), msg=f"missing script: {script}")

        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            spec_path = td_path / "specs" / "mesh_hotspot_thermal_3d_fake.json"
            manifest_path = td_path / "specs" / "suite.json"
            out_dir = td_path / "suite_out"
            fake_runner = td_path / "fake_run_mesh_with_time.sh"

            _write_json(
                spec_path,
                {
                    "schema_version": 3,
                    "model": "mesh",
                    "thermal": {"enable": True, "backend": "hotspot", "model_type": "grid"},
                },
            )
            _write_json(
                manifest_path,
                {
                    "suite_contract_version": "v1",
                    "cases": [
                        {
                            "case_id": "thermal_3d_grid_fake",
                            "spec_path": str(spec_path),
                            "expectations": {
                                "require_window_power_samples": True,
                                "require_layer_stack_validation": True,
                                "hotspot_model_type": "grid",
                            },
                        }
                    ],
                },
            )
            fake_runner.write_text(
                """#!/usr/bin/env bash
set -euo pipefail
SPEC=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --spec)
      SPEC="${2:-}"
      shift 2
      ;;
    *)
      shift
      ;;
  esac
done
if [ -z "${MESH_RUN_ROOT:-}" ]; then
  echo "missing MESH_RUN_ROOT" >&2
  exit 2
fi
RUN_DIR="${MESH_RUN_ROOT}/$(basename "${SPEC%.json}")-run"
SUMMARY_DIR="${RUN_DIR}/thermal/summary"
mkdir -p "$SUMMARY_DIR"
cat > "${SUMMARY_DIR}/tile_temperature_summary.csv" <<'CSV'
layer_name,layer_index,layer_z_um,power_scale,power_source_type,tile_id,block_name,block_type,average_power_w,cycle_model_applicable,model_source,sim_cycles_total,compute_active_cycles_total,activity_fraction,trace_mode,trace_source,window_scaling_mode,temperature_c
compute_top,0,0,1.000000,mesh_proxy,0,L00_compute_top__tile_00_comp,comp,1.000000e-02,1,compute_active_cycles_total,1000,400,0.400000,average,average_power,single_average_row,46.50
tim_mid,1,150,1.000000,none,,L01_tim_mid__spread,tim,0.000000e+00,0,,,,constant,disabled,constant,45.10
CSV
cat > "${SUMMARY_DIR}/layer_stack_validation.json" <<'JSON'
{
  "status": "passed",
  "passed": true,
  "layer_count_checked": 2,
  "mismatch_count": 0,
  "config_matches": true,
  "config_mismatch_reasons": []
}
JSON
cat > "${SUMMARY_DIR}/window_power_samples.jsonl" <<'JSONL'
{"sample_id": 1, "start_cycle": 0, "end_cycle": 999, "duration_ns": 1000, "trace_mode": "average", "blocks": [{"block_name": "L00_compute_top__tile_00_comp", "trace_source": "average_power", "power_w": 0.01}]}
JSONL
cat > "${SUMMARY_DIR}/thermal_summary.json" <<JSON
{
  "thermal_contract_version": "v2",
  "ambient_c": 45.0,
  "artifacts": {
    "tile_temperature_summary_csv": "${SUMMARY_DIR}/tile_temperature_summary.csv",
    "window_power_samples_jsonl": "${SUMMARY_DIR}/window_power_samples.jsonl",
    "layer_stack_validation": "${SUMMARY_DIR}/layer_stack_validation.json"
  },
  "backend": "hotspot",
  "duration_s": 0.000001,
  "hotspot": {"status": "ran", "returncode": 0},
  "hotspot_model_type": "grid",
  "layer_stack_validation": {
    "status": "passed",
    "passed": true,
    "layer_count_checked": 2,
    "mismatch_count": 0,
    "config_matches": true,
    "config_mismatch_reasons": []
  },
  "trace_mode": "average",
  "window_count": 1,
  "window_provenance": {
    "scaling_mode": "single_average_row",
    "metric_priority": []
  },
  "layer_count": 2,
  "layers": [
    {"name": "compute_top", "layer_index": 0, "kind": "mesh_active", "power_dissipating": true},
    {"name": "tim_mid", "layer_index": 1, "kind": "tim", "power_dissipating": false}
  ],
  "mesh_size": 4,
  "temperature_c": {"avg": 45.80, "max": 46.50, "min": 45.10},
  "tile_count": 16,
  "window_ns": 1000,
  "window_power_sample_count": 1,
  "window_power_block_count": 1,
  "window_power_trace_sources": ["average_power"]
}
JSON
echo "[mesh] run complete: ${RUN_DIR}"
""",
                encoding="utf-8",
            )
            fake_runner.chmod(0o755)

            proc = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--manifest",
                    str(manifest_path),
                    "--out-dir",
                    str(out_dir),
                    "--mesh-runner",
                    str(fake_runner),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            payload = json.loads(proc.stdout)
            self.assertEqual(payload["suite_contract_version"], "v1")
            self.assertEqual(payload["case_count"], 1)
            self.assertEqual(payload["passed_case_count"], 1)

            result_json = out_dir / "thermal_contract_suite_result.json"
            self.assertEqual(payload["result_json"], str(result_json.resolve()))
            self.assertTrue(result_json.is_file())

            result = json.loads(result_json.read_text(encoding="utf-8"))
            self.assertEqual(result["suite_contract_version"], "v1")
            self.assertEqual(result["case_count"], 1)
            case = result["cases"][0]
            self.assertEqual(case["case_id"], "thermal_3d_grid_fake")
            self.assertEqual(case["status"], "passed")
            self.assertIn("--spec", " ".join(case["commands"]["run"]))
            self.assertIn("analyze_thermal_runs.py", " ".join(case["commands"]["analyze"]))
            self.assertIn("generate_thermal_sweep_report.py", " ".join(case["commands"]["report"]))

            analysis_json = Path(case["artifacts"]["analysis_json"])
            summary_json = Path(case["artifacts"]["summary_json"])
            report_csv = Path(case["artifacts"]["report_csv"])
            report_md = Path(case["artifacts"]["report_markdown"])
            self.assertTrue(analysis_json.is_file())
            self.assertTrue(summary_json.is_file())
            self.assertTrue(report_csv.is_file())
            self.assertTrue(report_md.is_file())

            summary_payload = json.loads(summary_json.read_text(encoding="utf-8"))
            self.assertEqual(summary_payload["sweep_summary_contract_version"], "v2")
            self.assertEqual(summary_payload["hotspot_model_type_counts"], {"grid": 1})


if __name__ == "__main__":
    unittest.main()
