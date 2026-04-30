#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


class AnalyzeThermalRunsCLITest(unittest.TestCase):
    def _write_run(
        self,
        run_dir: Path,
        *,
        summary: dict,
        tile_rows: list[dict[str, str]],
    ) -> None:
        summary_dir = run_dir / "thermal" / "summary"
        _write_json(summary_dir / "thermal_summary.json", summary)
        _write_csv(summary_dir / "tile_temperature_summary.csv", tile_rows)

    def test_analyze_thermal_runs_exports_run_layer_and_block_tables(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            run_a = td_path / "hotspot_formal_spec_3d_stats_prefix_v1" / "20260319-135209"
            run_b = td_path / "hotspot_formal_spec_3d_csv_v1" / "20260319-135033"
            out_dir = td_path / "thermal_export"

            self._write_run(
                run_a,
                summary={
                    "ambient_c": 45.0,
                    "artifacts": {
                        "layer_stack_validation": str(run_a / "thermal" / "summary" / "layer_stack_validation.json"),
                        "window_power_samples_jsonl": str(run_a / "thermal" / "summary" / "window_power_samples.jsonl"),
                    },
                    "backend": "hotspot",
                    "duration_s": 1e-6,
                    "hotspot": {"status": "ran", "returncode": 0},
                    "hotspot_model_type": "grid",
                    "layer_stack_validation": {
                        "status": "passed",
                        "passed": True,
                        "layer_count_checked": 2,
                        "mismatch_count": 0,
                    },
                    "trace_mode": "windowed",
                    "window_count": 4,
                    "window_provenance": {
                        "scaling_mode": "per_tile_mean_normalized_metric",
                        "metric_priority": ["payload_bytes", "bursts", "inflight_peak", "buffer_max_bytes"],
                    },
                    "layer_count": 2,
                    "layers": [
                        {
                            "name": "compute",
                            "layer_index": 0,
                            "kind": "mesh_active",
                            "power_dissipating": True,
                            "trace_mode": "windowed",
                            "trace_source": "window_metrics",
                            "window_scaling_mode": "per_tile_mean_normalized_metric",
                            "power_scale": 1.0,
                            "power_source": {"type": "mesh_proxy"},
                            "thickness_um": 150,
                            "z_um": 0,
                        },
                        {
                            "name": "csv_bottom",
                            "layer_index": 2,
                            "kind": "mesh_active",
                            "power_dissipating": True,
                            "trace_mode": "constant",
                            "trace_source": "csv_constant",
                            "window_scaling_mode": "constant",
                            "power_scale": 0.5,
                            "power_source": {"type": "csv", "csv_path": "profile.csv"},
                            "thickness_um": 150,
                            "z_um": 350,
                        },
                    ],
                    "mesh_size": 4,
                    "temperature_c": {"avg": 45.5, "max": 46.5, "min": 44.9},
                    "tile_count": 16,
                    "window_ns": 1000,
                },
                tile_rows=[
                    {
                        "layer_name": "compute",
                        "layer_index": "0",
                        "layer_z_um": "0",
                        "power_scale": "1.000000",
                        "power_source_type": "mesh_proxy",
                        "tile_id": "0",
                        "block_name": "L00_compute__tile_00_comp",
                        "block_type": "comp",
                        "average_power_w": "1.000000e-02",
                        "model_source": "compute_active_cycles_total",
                        "trace_mode": "windowed",
                        "trace_source": "window_metrics",
                        "window_scaling_mode": "per_tile_mean_normalized_metric",
                        "sim_cycles_total": "1000",
                        "compute_active_cycles_total": "400",
                        "activity_fraction": "0.400000",
                        "temperature_c": "46.50",
                    },
                    {
                        "layer_name": "compute",
                        "layer_index": "0",
                        "layer_z_um": "0",
                        "power_scale": "1.000000",
                        "power_source_type": "mesh_proxy",
                        "tile_id": "0",
                        "block_name": "L00_compute__tile_00_noc",
                        "block_type": "noc",
                        "average_power_w": "1.000000e-03",
                        "model_source": "",
                        "trace_mode": "windowed",
                        "trace_source": "window_metrics",
                        "window_scaling_mode": "per_tile_mean_normalized_metric",
                        "sim_cycles_total": "",
                        "compute_active_cycles_total": "",
                        "activity_fraction": "",
                        "temperature_c": "45.00",
                    },
                    {
                        "layer_name": "csv_bottom",
                        "layer_index": "2",
                        "layer_z_um": "350",
                        "power_scale": "0.500000",
                        "power_source_type": "csv",
                        "tile_id": "0",
                        "block_name": "L02_csv_bottom__tile_00_comp",
                        "block_type": "comp",
                        "average_power_w": "2.000000e-02",
                        "model_source": "csv",
                        "trace_mode": "constant",
                        "trace_source": "csv_constant",
                        "window_scaling_mode": "constant",
                        "sim_cycles_total": "",
                        "compute_active_cycles_total": "",
                        "activity_fraction": "",
                        "temperature_c": "45.80",
                    },
                    {
                        "layer_name": "csv_bottom",
                        "layer_index": "2",
                        "layer_z_um": "350",
                        "power_scale": "0.500000",
                        "power_source_type": "csv",
                        "tile_id": "0",
                        "block_name": "L02_csv_bottom__tile_00_sram",
                        "block_type": "sram",
                        "average_power_w": "3.000000e-03",
                        "model_source": "",
                        "trace_mode": "constant",
                        "trace_source": "csv_constant",
                        "window_scaling_mode": "constant",
                        "sim_cycles_total": "",
                        "compute_active_cycles_total": "",
                        "activity_fraction": "",
                        "temperature_c": "45.20",
                    },
                ],
            )
            (run_a / "thermal" / "summary" / "window_power_samples.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "sample_id": 1,
                                "trace_mode": "windowed",
                                "blocks": [
                                    {"block_name": "L00_compute__tile_00_comp", "trace_source": "window_metrics"},
                                    {"block_name": "L00_compute__tile_00_noc", "trace_source": "window_metrics"},
                                ],
                            }
                        ),
                        json.dumps(
                            {
                                "sample_id": 2,
                                "trace_mode": "windowed",
                                "blocks": [
                                    {"block_name": "L00_compute__tile_00_comp", "trace_source": "window_metrics"},
                                    {"block_name": "L02_csv_bottom__tile_00_comp", "trace_source": "csv_constant"},
                                ],
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            _write_json(
                run_a / "thermal" / "summary" / "layer_stack_validation.json",
                {
                    "status": "passed",
                    "passed": True,
                    "layer_count_checked": 2,
                    "mismatch_count": 0,
                    "config_matches": True,
                    "config_mismatch_reasons": [],
                    "extra_entry_count": 0,
                    "parse_error": "",
                    "layers": [
                        {"layer_name": "compute", "matches": True, "mismatch_reasons": []},
                        {"layer_name": "csv_bottom", "matches": True, "mismatch_reasons": []},
                    ],
                },
            )

            self._write_run(
                run_b,
                summary={
                    "ambient_c": 45.0,
                    "artifacts": {
                        "layer_stack_validation": str(run_b / "thermal" / "summary" / "layer_stack_validation.json"),
                        "window_power_samples_jsonl": str(run_b / "thermal" / "summary" / "window_power_samples.jsonl"),
                    },
                    "backend": "hotspot",
                    "duration_s": 2e-6,
                    "hotspot": {"status": "ran", "returncode": 0},
                    "hotspot_model_type": "block",
                    "layer_stack_validation": {
                        "status": "failed",
                        "passed": False,
                        "layer_count_checked": 2,
                        "mismatch_count": 1,
                    },
                    "trace_mode": "average",
                    "window_count": 1,
                    "window_provenance": {
                        "scaling_mode": "single_average_row",
                        "metric_priority": [],
                    },
                    "layer_count": 2,
                    "layers": [
                        {
                            "name": "compute",
                            "layer_index": 0,
                            "kind": "mesh_active",
                            "power_dissipating": True,
                            "trace_mode": "average",
                            "trace_source": "average_power",
                            "window_scaling_mode": "single_average_row",
                            "power_scale": 1.0,
                            "power_source": {"type": "mesh_proxy"},
                            "thickness_um": 150,
                            "z_um": 0,
                        },
                        {
                            "name": "csv_bottom",
                            "layer_index": 2,
                            "kind": "mesh_active",
                            "power_dissipating": True,
                            "trace_mode": "constant",
                            "trace_source": "csv_constant",
                            "window_scaling_mode": "constant",
                            "power_scale": 0.5,
                            "power_source": {"type": "csv", "csv_path": "profile.csv"},
                            "thickness_um": 150,
                            "z_um": 350,
                        },
                    ],
                    "mesh_size": 4,
                    "temperature_c": {"avg": 46.4, "max": 47.2, "min": 45.9},
                    "tile_count": 16,
                    "window_ns": 1000,
                },
                tile_rows=[
                    {
                        "layer_name": "compute",
                        "layer_index": "0",
                        "layer_z_um": "0",
                        "power_scale": "1.000000",
                        "power_source_type": "mesh_proxy",
                        "tile_id": "1",
                        "block_name": "L00_compute__tile_01_comp",
                        "block_type": "comp",
                        "average_power_w": "8.000000e-03",
                        "model_source": "compute_active_cycles_total",
                        "trace_mode": "average",
                        "trace_source": "average_power",
                        "window_scaling_mode": "single_average_row",
                        "sim_cycles_total": "1200",
                        "compute_active_cycles_total": "500",
                        "activity_fraction": "0.416667",
                        "temperature_c": "45.90",
                    },
                    {
                        "layer_name": "csv_bottom",
                        "layer_index": "2",
                        "layer_z_um": "350",
                        "power_scale": "0.500000",
                        "power_source_type": "csv",
                        "tile_id": "1",
                        "block_name": "L02_csv_bottom__tile_01_comp",
                        "block_type": "comp",
                        "average_power_w": "3.000000e-02",
                        "model_source": "csv",
                        "trace_mode": "constant",
                        "trace_source": "csv_constant",
                        "window_scaling_mode": "constant",
                        "sim_cycles_total": "",
                        "compute_active_cycles_total": "",
                        "activity_fraction": "",
                        "temperature_c": "47.20",
                    },
                    {
                        "layer_name": "csv_bottom",
                        "layer_index": "2",
                        "layer_z_um": "350",
                        "power_scale": "0.500000",
                        "power_source_type": "csv",
                        "tile_id": "1",
                        "block_name": "L02_csv_bottom__tile_01_sram",
                        "block_type": "sram",
                        "average_power_w": "4.000000e-03",
                        "model_source": "",
                        "trace_mode": "constant",
                        "trace_source": "csv_constant",
                        "window_scaling_mode": "constant",
                        "sim_cycles_total": "",
                        "compute_active_cycles_total": "",
                        "activity_fraction": "",
                        "temperature_c": "46.10",
                    },
                ],
            )
            (run_b / "thermal" / "summary" / "window_power_samples.jsonl").write_text(
                json.dumps(
                    {
                        "sample_id": 1,
                        "trace_mode": "average",
                        "blocks": [
                            {"block_name": "L00_compute__tile_01_comp", "trace_source": "average_power"},
                            {"block_name": "L02_csv_bottom__tile_01_comp", "trace_source": "csv_constant"},
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            _write_json(
                run_b / "thermal" / "summary" / "layer_stack_validation.json",
                {
                    "status": "failed",
                    "passed": False,
                    "layer_count_checked": 2,
                    "mismatch_count": 3,
                    "config_matches": False,
                    "config_mismatch_reasons": ["grid_rows"],
                    "extra_entry_count": 0,
                    "parse_error": "",
                    "layers": [
                        {
                            "layer_name": "compute",
                            "matches": False,
                            "mismatch_reasons": ["thickness", "block_prefix"],
                            "expected_floorplan_file": "/tmp/expected_compute.flp",
                            "lcf_floorplan_file": "/tmp/actual_compute.flp",
                        },
                        {
                            "layer_name": "csv_bottom",
                            "matches": False,
                            "mismatch_reasons": ["thickness"],
                            "expected_floorplan_file": "/tmp/expected_csv_bottom.flp",
                            "lcf_floorplan_file": "/tmp/actual_csv_bottom.flp",
                        },
                    ],
                },
            )

            script = Path(__file__).with_name("analyze_thermal_runs.py")
            proc = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--run-dir",
                    str(run_a),
                    "--run-dir",
                    str(run_b),
                    "--out-dir",
                    str(out_dir),
                    "--top-n",
                    "3",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            run_summary_path = out_dir / "run_summary.csv"
            layer_summary_path = out_dir / "layer_summary.csv"
            top_blocks_path = out_dir / "top_blocks.csv"
            stack_runs_path = out_dir / "layer_stack_validation_runs.csv"
            stack_fail_layers_path = out_dir / "layer_stack_validation_fail_layers.csv"
            analysis_json_path = out_dir / "thermal_analysis.json"
            self.assertTrue(run_summary_path.is_file())
            self.assertTrue(layer_summary_path.is_file())
            self.assertTrue(top_blocks_path.is_file())
            self.assertTrue(stack_runs_path.is_file())
            self.assertTrue(stack_fail_layers_path.is_file())
            self.assertTrue(analysis_json_path.is_file())

            with run_summary_path.open("r", encoding="utf-8", newline="") as f:
                run_rows = list(csv.DictReader(f))
            self.assertEqual(len(run_rows), 2)
            run_by_group = {row["run_group"]: row for row in run_rows}
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["hottest_block_name"], "L00_compute__tile_00_comp")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["total_power_w"], "0.034000")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["trace_mode"], "windowed")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["ambient_c"], "45.000000")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["temp_peak_over_ambient_c"], "1.500000")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["active_layer_count"], "2")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["trace_sources"], "csv_constant,window_metrics")
            self.assertEqual(
                run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["window_scaling_modes"],
                "constant,per_tile_mean_normalized_metric",
            )
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["layer_stack_validation_status"], "passed")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["layer_stack_validation_passed"], "1")
            self.assertEqual(
                run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["layer_stack_validation_config_mismatch_reasons"],
                "",
            )
            self.assertEqual(
                run_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["layer_stack_validation_mismatch_reasons"],
                "",
            )
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_csv_v1"]["hottest_block_name"], "L02_csv_bottom__tile_01_comp")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_csv_v1"]["temp_peak_c"], "47.200000")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_csv_v1"]["trace_mode"], "average")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_csv_v1"]["temp_peak_over_ambient_c"], "2.200000")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_csv_v1"]["layer_stack_validation_status"], "failed")
            self.assertEqual(run_by_group["hotspot_formal_spec_3d_csv_v1"]["layer_stack_validation_mismatch_count"], "1")
            self.assertEqual(
                run_by_group["hotspot_formal_spec_3d_csv_v1"]["layer_stack_validation_config_mismatch_reasons"],
                "grid_rows",
            )
            self.assertEqual(
                run_by_group["hotspot_formal_spec_3d_csv_v1"]["layer_stack_validation_mismatch_reasons"],
                "block_prefix,thickness",
            )

            with layer_summary_path.open("r", encoding="utf-8", newline="") as f:
                layer_rows = list(csv.DictReader(f))
            layer_map = {(row["run_group"], row["layer_name"]): row for row in layer_rows}
            self.assertEqual(layer_map[("hotspot_formal_spec_3d_stats_prefix_v1", "compute")]["total_power_w"], "0.011000")
            self.assertEqual(layer_map[("hotspot_formal_spec_3d_stats_prefix_v1", "compute")]["power_source_type"], "mesh_proxy")
            self.assertEqual(layer_map[("hotspot_formal_spec_3d_stats_prefix_v1", "compute")]["power_share"], "0.323529")
            self.assertEqual(
                layer_map[("hotspot_formal_spec_3d_stats_prefix_v1", "compute")]["trace_sources"],
                "window_metrics",
            )
            self.assertEqual(layer_map[("hotspot_formal_spec_3d_csv_v1", "csv_bottom")]["hottest_block_name"], "L02_csv_bottom__tile_01_comp")
            self.assertEqual(layer_map[("hotspot_formal_spec_3d_csv_v1", "csv_bottom")]["power_share"], "0.809524")

            with top_blocks_path.open("r", encoding="utf-8", newline="") as f:
                top_rows = list(csv.DictReader(f))
            self.assertEqual(len(top_rows), 3)
            self.assertEqual(top_rows[0]["block_name"], "L02_csv_bottom__tile_01_comp")
            self.assertEqual(top_rows[0]["temperature_c"], "47.200000")
            self.assertEqual(top_rows[0]["trace_source"], "csv_constant")
            self.assertEqual(top_rows[1]["block_name"], "L00_compute__tile_00_comp")
            self.assertEqual(top_rows[1]["trace_source"], "window_metrics")

            with stack_runs_path.open("r", encoding="utf-8", newline="") as f:
                stack_run_rows = list(csv.DictReader(f))
            self.assertEqual(len(stack_run_rows), 1)
            self.assertEqual(stack_run_rows[0]["run_group"], "hotspot_formal_spec_3d_csv_v1")
            self.assertEqual(stack_run_rows[0]["status"], "failed")
            self.assertEqual(stack_run_rows[0]["mismatch_count"], "1")
            self.assertEqual(stack_run_rows[0]["failed_layer_count"], "2")
            self.assertEqual(stack_run_rows[0]["mismatch_reasons"], "block_prefix,thickness")
            self.assertEqual(stack_run_rows[0]["config_mismatch_reasons"], "grid_rows")

            with stack_fail_layers_path.open("r", encoding="utf-8", newline="") as f:
                stack_fail_layer_rows = list(csv.DictReader(f))
            self.assertEqual(len(stack_fail_layer_rows), 3)
            self.assertEqual(stack_fail_layer_rows[0]["expected_floorplan_file"], "/tmp/expected_compute.flp")
            self.assertEqual(stack_fail_layer_rows[0]["lcf_floorplan_file"], "/tmp/actual_compute.flp")
            self.assertEqual(
                [
                    (row["run_group"], row["layer_name"], row["reason"])
                    for row in stack_fail_layer_rows
                ],
                [
                    ("hotspot_formal_spec_3d_csv_v1", "compute", "block_prefix"),
                    ("hotspot_formal_spec_3d_csv_v1", "compute", "thickness"),
                    ("hotspot_formal_spec_3d_csv_v1", "csv_bottom", "thickness"),
                ],
            )

            analysis = json.loads(analysis_json_path.read_text(encoding="utf-8"))
            self.assertEqual(analysis["analysis_contract_version"], "v2")
            self.assertEqual(analysis["run_count"], 2)
            self.assertEqual(analysis["top_n"], 3)
            provenance = dict(analysis.get("artifact_provenance") or {})
            self.assertEqual(provenance.get("tool"), "sst_dram_si.tools.analyze_thermal_runs")
            self.assertEqual(provenance.get("artifact_kind"), "thermal_analysis")
            self.assertEqual(provenance.get("contract_version"), "v2")
            self.assertEqual(provenance.get("source_kind"), "run_dir_batch")
            self.assertEqual(provenance.get("analysis_dir"), str(out_dir.resolve()))
            self.assertTrue(str(provenance.get("generated_at_utc") or "").endswith("Z"))
            self.assertEqual(
                sorted(list(provenance.get("source_run_dirs") or [])),
                sorted([str(run_a.resolve()), str(run_b.resolve())]),
            )
            self.assertEqual(
                dict(provenance.get("source_paths") or {}).get("thermal_summary_rel"),
                "thermal/summary/thermal_summary.json",
            )
            self.assertEqual(analysis["artifacts"]["layer_stack_validation_runs_csv"], str(stack_runs_path.resolve()))
            self.assertEqual(
                analysis["artifacts"]["layer_stack_validation_fail_layers_csv"],
                str(stack_fail_layers_path.resolve()),
            )
            self.assertEqual(analysis["provenance_summary"]["trace_source_run_counts"]["window_metrics"], 1)
            self.assertEqual(analysis["provenance_summary"]["trace_source_run_counts"]["csv_constant"], 2)
            self.assertEqual(
                analysis["provenance_summary"]["window_scaling_mode_run_counts"]["per_tile_mean_normalized_metric"],
                1,
            )
            self.assertEqual(analysis["layer_stack_validation_summary"]["run_count_with_validation"], 2)
            self.assertEqual(analysis["layer_stack_validation_summary"]["passed_run_count"], 1)
            self.assertEqual(analysis["layer_stack_validation_summary"]["failed_run_count"], 1)
            self.assertEqual(analysis["layer_stack_validation_summary"]["mismatch_reason_run_counts"]["thickness"], 1)
            self.assertEqual(analysis["layer_stack_validation_summary"]["mismatch_reason_run_counts"]["block_prefix"], 1)
            self.assertEqual(analysis["layer_stack_validation_summary"]["mismatch_reason_layer_counts"]["thickness"], 2)
            self.assertEqual(analysis["layer_stack_validation_summary"]["mismatch_reason_layer_counts"]["block_prefix"], 1)
            self.assertEqual(analysis["layer_stack_validation_summary"]["config_mismatch_reason_run_counts"]["grid_rows"], 1)
            self.assertEqual(
                analysis["layer_stack_validation_summary"]["failed_runs"][0]["run_group"],
                "hotspot_formal_spec_3d_csv_v1",
            )
            self.assertEqual(
                analysis["layer_stack_validation_summary"]["failed_runs"][0]["mismatch_reasons"],
                ["block_prefix", "thickness"],
            )
            self.assertEqual(
                analysis["layer_stack_validation_summary"]["failed_runs"][0]["config_mismatch_reasons"],
                ["grid_rows"],
            )
            self.assertEqual(analysis["provenance_summary"]["window_power_trace_source_counts"]["average_power"], 1)
            self.assertEqual(analysis["provenance_summary"]["window_power_trace_source_counts"]["csv_constant"], 2)
            self.assertEqual(analysis["provenance_summary"]["window_power_trace_source_counts"]["window_metrics"], 1)
            analysis_by_group = {row["run_group"]: row for row in analysis["runs"]}
            self.assertEqual(analysis_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["backend"], "hotspot")
            self.assertEqual(analysis_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["trace_mode"], "windowed")
            self.assertEqual(int(analysis_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["window_count"] or 0), 4)
            self.assertEqual(int(analysis_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["window_power_sample_count"] or 0), 2)
            self.assertEqual(int(analysis_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["window_power_block_count"] or 0), 4)
            self.assertEqual(analysis_by_group["hotspot_formal_spec_3d_stats_prefix_v1"]["layer_stack_validation"]["status"], "passed")
            self.assertEqual(analysis_by_group["hotspot_formal_spec_3d_csv_v1"]["trace_mode"], "average")
            self.assertEqual(int(analysis_by_group["hotspot_formal_spec_3d_csv_v1"]["window_count"] or 0), 1)
            self.assertEqual(int(analysis_by_group["hotspot_formal_spec_3d_csv_v1"]["window_power_sample_count"] or 0), 1)
            self.assertEqual(int(analysis_by_group["hotspot_formal_spec_3d_csv_v1"]["window_power_block_count"] or 0), 2)
            self.assertEqual(analysis_by_group["hotspot_formal_spec_3d_csv_v1"]["layer_stack_validation"]["status"], "failed")

    def test_analyze_thermal_runs_filters_top_blocks_for_nonzero_and_active_layers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            run_dir = td_path / "hotspot_filtered_case" / "20260319-200000"
            out_dir = td_path / "thermal_export_filtered"

            self._write_run(
                run_dir,
                summary={
                    "backend": "hotspot",
                    "duration_s": 1e-6,
                    "hotspot": {"status": "ran", "returncode": 0},
                    "hotspot_model_type": "grid",
                    "trace_mode": "average",
                    "window_count": 1,
                    "layer_count": 3,
                    "layers": [
                        {
                            "name": "compute",
                            "layer_index": 0,
                            "kind": "mesh_active",
                            "power_dissipating": True,
                            "power_scale": 1.0,
                            "power_source": {"type": "mesh_proxy"},
                            "thickness_um": 150,
                            "z_um": 0,
                        },
                        {
                            "name": "tim_mid",
                            "layer_index": 1,
                            "kind": "tim",
                            "power_dissipating": False,
                            "power_scale": 0.0,
                            "power_source": {"type": "none"},
                            "thickness_um": 20,
                            "z_um": 150,
                        },
                        {
                            "name": "csv_bottom",
                            "layer_index": 2,
                            "kind": "mesh_active",
                            "power_dissipating": True,
                            "power_scale": 1.0,
                            "power_source": {"type": "csv", "csv_path": "profile.csv"},
                            "thickness_um": 150,
                            "z_um": 170,
                        },
                    ],
                    "mesh_size": 4,
                    "temperature_c": {"avg": 46.0, "max": 50.0, "min": 44.0},
                    "tile_count": 16,
                    "window_ns": 1000,
                },
                tile_rows=[
                    {
                        "layer_name": "compute",
                        "layer_index": "0",
                        "layer_z_um": "0",
                        "power_scale": "1.000000",
                        "power_source_type": "mesh_proxy",
                        "tile_id": "0",
                        "block_name": "L00_compute__tile_00_comp",
                        "block_type": "comp",
                        "average_power_w": "1.000000e-02",
                        "model_source": "compute_active_cycles_total",
                        "sim_cycles_total": "1000",
                        "compute_active_cycles_total": "400",
                        "activity_fraction": "0.400000",
                        "temperature_c": "44.00",
                    },
                    {
                        "layer_name": "tim_mid",
                        "layer_index": "1",
                        "layer_z_um": "150",
                        "power_scale": "0.000000",
                        "power_source_type": "none",
                        "tile_id": "0",
                        "block_name": "L01_tim_mid__tile_00_comp",
                        "block_type": "comp",
                        "average_power_w": "0.000000e+00",
                        "model_source": "",
                        "sim_cycles_total": "",
                        "compute_active_cycles_total": "",
                        "activity_fraction": "",
                        "temperature_c": "50.00",
                    },
                    {
                        "layer_name": "csv_bottom",
                        "layer_index": "2",
                        "layer_z_um": "170",
                        "power_scale": "1.000000",
                        "power_source_type": "csv",
                        "tile_id": "0",
                        "block_name": "L02_csv_bottom__tile_00_comp",
                        "block_type": "comp",
                        "average_power_w": "2.000000e-02",
                        "model_source": "csv",
                        "sim_cycles_total": "",
                        "compute_active_cycles_total": "",
                        "activity_fraction": "",
                        "temperature_c": "49.00",
                    },
                ],
            )

            script = Path(__file__).with_name("analyze_thermal_runs.py")
            proc = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--run-dir",
                    str(run_dir),
                    "--out-dir",
                    str(out_dir),
                    "--top-n",
                    "5",
                    "--nonzero-power-only",
                    "--active-layers-only",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            with (out_dir / "top_blocks.csv").open("r", encoding="utf-8", newline="") as f:
                top_rows = list(csv.DictReader(f))
            self.assertEqual(len(top_rows), 2)
            self.assertEqual(top_rows[0]["block_name"], "L02_csv_bottom__tile_00_comp")
            self.assertEqual(top_rows[1]["block_name"], "L00_compute__tile_00_comp")
            self.assertTrue(all(row["layer_name"] != "tim_mid" for row in top_rows))
            self.assertTrue(all(float(row["average_power_w"]) > 0.0 for row in top_rows))

            with (out_dir / "run_summary.csv").open("r", encoding="utf-8", newline="") as f:
                run_rows = list(csv.DictReader(f))
            self.assertEqual(len(run_rows), 1)
            self.assertEqual(run_rows[0]["hottest_block_name"], "L02_csv_bottom__tile_00_comp")
            self.assertEqual(run_rows[0]["hottest_layer_name"], "csv_bottom")
            self.assertEqual(run_rows[0]["total_power_w"], "0.030000")

            with (out_dir / "layer_summary.csv").open("r", encoding="utf-8", newline="") as f:
                layer_rows = list(csv.DictReader(f))
            self.assertEqual(len(layer_rows), 2)
            layer_map = {row["layer_name"]: row for row in layer_rows}
            self.assertNotIn("tim_mid", layer_map)
            self.assertEqual(layer_map["compute"]["total_power_w"], "0.010000")
            self.assertEqual(layer_map["csv_bottom"]["total_power_w"], "0.020000")

    def test_analyze_thermal_runs_exports_layer_stack_validation_all_runs_table(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            run_with_validation = td_path / "hotspot_3d_with_validation" / "20260320-120000"
            run_without_validation = td_path / "hotspot_2d_without_validation" / "20260320-120100"
            out_dir = td_path / "thermal_export_all_runs"

            self._write_run(
                run_with_validation,
                summary={
                    "backend": "hotspot",
                    "duration_s": 1e-6,
                    "hotspot": {"status": "ran", "returncode": 0},
                    "hotspot_model_type": "grid",
                    "layer_stack_validation": {
                        "status": "passed",
                        "passed": True,
                        "layer_count_checked": 3,
                        "mismatch_count": 0,
                    },
                    "layers": [
                        {
                            "name": "compute_top",
                            "layer_index": 0,
                            "kind": "mesh_active",
                            "power_dissipating": True,
                            "power_scale": 1.0,
                            "power_source": {"type": "mesh_proxy"},
                            "thickness_um": 150,
                            "z_um": 0,
                        }
                    ],
                    "mesh_size": 4,
                    "temperature_c": {"avg": 45.1, "max": 45.2, "min": 45.0},
                    "tile_count": 16,
                    "window_count": 1,
                    "window_ns": 1000,
                },
                tile_rows=[
                    {
                        "layer_name": "compute_top",
                        "layer_index": "0",
                        "layer_z_um": "0",
                        "power_scale": "1.000000",
                        "power_source_type": "mesh_proxy",
                        "tile_id": "0",
                        "block_name": "L00_compute_top__tile_00_comp",
                        "block_type": "comp",
                        "average_power_w": "1.000000e-02",
                        "model_source": "compute_active_cycles_total",
                        "temperature_c": "45.20",
                    }
                ],
            )
            _write_json(
                run_with_validation / "thermal" / "summary" / "layer_stack_validation.json",
                {
                    "status": "passed",
                    "passed": True,
                    "layer_count_checked": 3,
                    "mismatch_count": 0,
                    "config_matches": True,
                    "config_mismatch_reasons": [],
                    "layers": [
                        {"layer_name": "compute_top", "matches": True, "mismatch_reasons": []},
                    ],
                },
            )

            self._write_run(
                run_without_validation,
                summary={
                    "backend": "hotspot",
                    "duration_s": 1e-6,
                    "hotspot": {"status": "ran", "returncode": 0},
                    "hotspot_model_type": "block",
                    "mesh_size": 4,
                    "temperature_c": {"avg": 45.3, "max": 45.4, "min": 45.1},
                    "tile_count": 16,
                    "window_count": 1,
                    "window_ns": 1000,
                },
                tile_rows=[
                    {
                        "layer_name": "",
                        "layer_index": "",
                        "layer_z_um": "",
                        "power_scale": "1.000000",
                        "power_source_type": "mesh_proxy",
                        "tile_id": "1",
                        "block_name": "tile_01_comp",
                        "block_type": "comp",
                        "average_power_w": "8.000000e-03",
                        "model_source": "compute_active_cycles_total",
                        "temperature_c": "45.40",
                    }
                ],
            )

            script = Path(__file__).with_name("analyze_thermal_runs.py")
            proc = subprocess.run(
                [
                    "python3",
                    str(script),
                    "--run-dir",
                    str(run_with_validation),
                    "--run-dir",
                    str(run_without_validation),
                    "--out-dir",
                    str(out_dir),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            stack_all_runs_path = out_dir / "layer_stack_validation_all_runs.csv"
            self.assertTrue(stack_all_runs_path.is_file())

            with stack_all_runs_path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 2)
            rows_by_group = {row["run_group"]: row for row in rows}
            self.assertEqual(rows_by_group["hotspot_3d_with_validation"]["has_validation"], "1")
            self.assertEqual(rows_by_group["hotspot_3d_with_validation"]["status"], "passed")
            self.assertEqual(rows_by_group["hotspot_3d_with_validation"]["passed"], "1")
            self.assertEqual(rows_by_group["hotspot_3d_with_validation"]["layer_count_checked"], "3")
            self.assertEqual(rows_by_group["hotspot_3d_with_validation"]["config_matches"], "1")
            self.assertEqual(rows_by_group["hotspot_2d_without_validation"]["has_validation"], "0")
            self.assertEqual(rows_by_group["hotspot_2d_without_validation"]["status"], "")
            self.assertEqual(rows_by_group["hotspot_2d_without_validation"]["passed"], "")
            self.assertEqual(rows_by_group["hotspot_2d_without_validation"]["layer_count_checked"], "")
            self.assertEqual(rows_by_group["hotspot_2d_without_validation"]["config_matches"], "")

            analysis = json.loads((out_dir / "thermal_analysis.json").read_text(encoding="utf-8"))
            self.assertEqual(
                analysis["artifacts"]["layer_stack_validation_all_runs_csv"],
                str(stack_all_runs_path.resolve()),
            )


if __name__ == "__main__":
    unittest.main()
