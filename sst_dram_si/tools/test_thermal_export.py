#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import csv
import json
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError("rows must be non-empty")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class ThermalExportCLITest(unittest.TestCase):
    def _run_export(self, run_dir: Path, *extra_args: str) -> subprocess.CompletedProcess[str]:
        script = Path(__file__).with_name("thermal_export.py")
        return subprocess.run(
            ["python3", str(script), "--run-dir", str(run_dir), *extra_args],
            text=True,
            capture_output=True,
        )

    def _load_ptrace_map(self, ptrace_path: Path) -> dict[str, float]:
        lines = ptrace_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 2)
        headers = lines[0].split("\t")
        values = [float(item) for item in lines[1].split("\t")]
        self.assertEqual(len(headers), len(values))
        return dict(zip(headers, values))

    def _load_ptrace_rows(self, ptrace_path: Path) -> tuple[list[str], list[dict[str, float]]]:
        lines = ptrace_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 2)
        headers = lines[0].split("\t")
        rows: list[dict[str, float]] = []
        for line in lines[1:]:
            values = [float(item) for item in line.split("\t")]
            self.assertEqual(len(headers), len(values))
            rows.append(dict(zip(headers, values)))
        return headers, rows

    def test_export_generates_hotspot_artifacts_without_hotspot_binary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                            {"pe": 2, "core": 0},
                            {"pe": 3, "core": 0},
                        ],
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "window_ns": 1000,
                            "out_dir": "thermal",
                            "tile_width_um": 1000,
                            "tile_height_um": 1000,
                            "tile_gap_um": 50,
                            "comp_frac": 0.6,
                            "sram_frac": 0.25,
                            "noc_frac": 0.15,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "core_state_sram_energy_read_pj_total",
                        "Sum.f64": "1200.0",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "core_state_sram_energy_write_pj_total",
                        "Sum.f64": "300.0",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0:network_interface",
                        "StatisticName": "packets_sent",
                        "Sum.u64": "42",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1:network_interface",
                        "StatisticName": "packets_sent",
                        "Sum.u64": "21",
                        "SimTime": "0",
                    },
                ],
            )

            proc = self._run_export(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            thermal_dir = run_dir / "thermal"
            hotspot_dir = thermal_dir / "hotspot"
            summary_dir = thermal_dir / "summary"
            self.assertTrue((thermal_dir / "effective_thermal_config.json").is_file())
            self.assertTrue((hotspot_dir / "snndl_mesh.flp").is_file())
            self.assertTrue((hotspot_dir / "snndl_mesh.ptrace").is_file())
            self.assertTrue((hotspot_dir / "hotspot.config").is_file())
            self.assertTrue((summary_dir / "thermal_summary.json").is_file())
            self.assertTrue((summary_dir / "tile_temperature_summary.csv").is_file())

            flp_text = (hotspot_dir / "snndl_mesh.flp").read_text(encoding="utf-8")
            self.assertIn("tile_00_comp", flp_text)
            self.assertIn("tile_00_sram", flp_text)
            self.assertIn("tile_00_noc", flp_text)

            ptrace_lines = (hotspot_dir / "snndl_mesh.ptrace").read_text(encoding="utf-8").strip().splitlines()
            self.assertGreaterEqual(len(ptrace_lines), 2)
            self.assertIn("tile_00_comp", ptrace_lines[0])
            self.assertIn("tile_00_sram", ptrace_lines[0])
            self.assertIn("tile_00_noc", ptrace_lines[0])

            summary = json.loads((summary_dir / "thermal_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(str(summary.get("backend") or ""), "hotspot")
            self.assertEqual(int(summary.get("tile_count") or 0), 4)
            self.assertEqual(str(summary.get("thermal_contract_version") or ""), "v2")
            self.assertEqual(str(summary.get("power_source_contract_version") or ""), "v1")
            provenance = dict(summary.get("artifact_provenance") or {})
            self.assertEqual(provenance.get("tool"), "sst_dram_si.tools.thermal_export")
            self.assertEqual(provenance.get("artifact_kind"), "thermal_summary")
            self.assertEqual(provenance.get("contract_version"), "v2")
            self.assertEqual(provenance.get("source_kind"), "run_dir")
            self.assertEqual(provenance.get("run_dir"), str(run_dir.resolve()))
            self.assertTrue(str(provenance.get("generated_at_utc") or "").endswith("Z"))
            self.assertEqual(
                dict(provenance.get("source_paths") or {}).get("effective_config_json"),
                str((run_dir / "effective_config.json").resolve()),
            )
            self.assertEqual(
                dict(provenance.get("source_paths") or {}).get("mesh_stats_csv"),
                str((run_dir / "mesh_stats.csv").resolve()),
            )
            self.assertIsInstance(summary.get("cycle_model_applicable"), bool)
            self.assertEqual(str(summary.get("trace_mode") or ""), "average")
            self.assertEqual(int(summary.get("window_count") or 0), 1)
            self.assertIn("window_power_samples_jsonl", summary.get("artifacts") or {})
            window_samples_path = Path((summary.get("artifacts") or {}).get("window_power_samples_jsonl") or "")
            self.assertTrue(window_samples_path.is_file())
            sample_rows = [json.loads(line) for line in window_samples_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(sample_rows), 1)
            self.assertEqual(sample_rows[0]["sample_id"], 1)
            self.assertEqual(sample_rows[0]["trace_mode"], "average")
            self.assertEqual(len(sample_rows[0]["blocks"]), len(ptrace_lines[0].split("\t")))
            hotspot = summary.get("hotspot") or {}
            self.assertEqual(str(hotspot.get("status") or ""), "skipped_missing_binary")

    def test_export_emits_windowed_ptrace_when_window_metrics_exist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                        ],
                        "sim_time_actual_ns": 2000,
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "window_ns": 1000,
                            "out_dir": "thermal",
                            "tile_width_um": 1000,
                            "tile_height_um": 1000,
                            "tile_gap_um": 50,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "2000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "2000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "500",
                        "SimTime": "0",
                    },
                ],
            )
            _write_csv(
                run_dir / "pe00" / "core00_window_metrics.csv",
                [
                    {
                        "window_id": "1",
                        "payload_bytes": "10",
                        "bursts": "1",
                        "inflight_peak": "1",
                        "buffer_max_bytes": "64",
                    },
                    {
                        "window_id": "2",
                        "payload_bytes": "30",
                        "bursts": "3",
                        "inflight_peak": "2",
                        "buffer_max_bytes": "128",
                    },
                ],
            )
            _write_csv(
                run_dir / "pe01" / "core00_window_metrics.csv",
                [
                    {
                        "window_id": "1",
                        "payload_bytes": "5",
                        "bursts": "1",
                        "inflight_peak": "1",
                        "buffer_max_bytes": "32",
                    },
                    {
                        "window_id": "2",
                        "payload_bytes": "5",
                        "bursts": "1",
                        "inflight_peak": "1",
                        "buffer_max_bytes": "32",
                    },
                ],
            )

            proc = self._run_export(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            _headers, rows = self._load_ptrace_rows(run_dir / "thermal" / "hotspot" / "snndl_mesh.ptrace")
            self.assertEqual(len(rows), 2)
            self.assertGreater(rows[1]["tile_00_comp"], rows[0]["tile_00_comp"])
            self.assertAlmostEqual(rows[0]["tile_01_comp"], rows[1]["tile_01_comp"], places=12)

            summary = json.loads((run_dir / "thermal" / "summary" / "thermal_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(str(summary.get("trace_mode") or ""), "windowed")
            self.assertEqual(int(summary.get("window_count") or 0), 2)
            self.assertEqual(str(summary.get("window_source") or ""), "window_metrics")
            self.assertEqual(int(summary.get("window_duration_ns") or 0), 1000)
            provenance = dict(summary.get("window_provenance") or {})
            self.assertEqual(str(provenance.get("scaling_mode") or ""), "per_tile_mean_normalized_metric")
            self.assertEqual(
                list(provenance.get("metric_priority") or []),
                ["payload_bytes", "bursts", "inflight_peak", "buffer_max_bytes"],
            )
            self.assertEqual(int(provenance.get("scaled_block_count") or 0), 6)
            self.assertEqual(int(provenance.get("constant_block_count") or 0), 0)
            window_samples_path = Path((summary.get("artifacts") or {}).get("window_power_samples_jsonl") or "")
            self.assertTrue(window_samples_path.is_file())
            sample_rows = [json.loads(line) for line in window_samples_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(len(sample_rows), 2)
            self.assertEqual(sample_rows[0]["sample_id"], 1)
            self.assertEqual(sample_rows[1]["sample_id"], 2)
            self.assertEqual(sample_rows[0]["trace_mode"], "windowed")
            self.assertEqual(len(sample_rows[0]["blocks"]), len(_headers))

            with (run_dir / "thermal" / "summary" / "tile_temperature_summary.csv").open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            row_by_block = {str(row.get("block_name") or ""): row for row in rows}
            self.assertEqual(row_by_block["tile_00_comp"]["trace_mode"], "windowed")
            self.assertEqual(row_by_block["tile_00_comp"]["trace_source"], "window_metrics")
            self.assertEqual(row_by_block["tile_00_comp"]["window_scaling_mode"], "per_tile_mean_normalized_metric")
            self.assertEqual(row_by_block["tile_01_comp"]["trace_mode"], "windowed")
            self.assertEqual(row_by_block["tile_01_comp"]["trace_source"], "window_metrics")
            self.assertEqual(row_by_block["tile_01_comp"]["window_scaling_mode"], "per_tile_mean_normalized_metric")

    def test_export_prefers_compute_active_cycles_for_comp_block_power(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                        ],
                        "sim_time_actual_ns": 1000,
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "window_ns": 1000,
                            "out_dir": "thermal",
                            "tile_width_um": 1000,
                            "tile_height_um": 1000,
                            "tile_gap_um": 50,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "800",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "0",
                        "SimTime": "0",
                    },
                ],
            )

            proc = self._run_export(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            ptrace_map = self._load_ptrace_map(run_dir / "thermal" / "hotspot" / "snndl_mesh.ptrace")
            self.assertIn("tile_00_comp", ptrace_map)
            self.assertIn("tile_01_comp", ptrace_map)
            self.assertGreater(
                ptrace_map["tile_00_comp"],
                ptrace_map["tile_01_comp"],
                msg="compute_active_cycles_total should raise tile_00_comp power above an idle tile",
            )

    def test_export_reads_sst_u64_accumulators_even_when_sum_f64_column_is_zero(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                        ],
                        "sim_time_actual_ns": 2065,
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "window_ns": 1000,
                            "out_dir": "thermal",
                            "tile_width_um": 1000,
                            "tile_height_um": 1000,
                            "tile_gap_um": 50,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "sim_cycles_total",
                        "StatisticType": "Accumulator",
                        "SimTime": "2065000",
                        "Rank": "0",
                        "Count.u64": "1",
                        "Sum.u64": "2065",
                        "SumSQ.u64": "4264225",
                        "Min.u64": "2065",
                        "Max.u64": "2065",
                        "Sum.f64": "0",
                        "SumSQ.f64": "0",
                        "Min.f64": "0",
                        "Max.f64": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "compute_active_cycles_total",
                        "StatisticType": "Accumulator",
                        "SimTime": "2065000",
                        "Rank": "0",
                        "Count.u64": "1",
                        "Sum.u64": "17",
                        "SumSQ.u64": "289",
                        "Min.u64": "17",
                        "Max.u64": "17",
                        "Sum.f64": "0",
                        "SumSQ.f64": "0",
                        "Min.f64": "0",
                        "Max.f64": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "sim_cycles_total",
                        "StatisticType": "Accumulator",
                        "SimTime": "2065000",
                        "Rank": "0",
                        "Count.u64": "1",
                        "Sum.u64": "2065",
                        "SumSQ.u64": "4264225",
                        "Min.u64": "2065",
                        "Max.u64": "2065",
                        "Sum.f64": "0",
                        "SumSQ.f64": "0",
                        "Min.f64": "0",
                        "Max.f64": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "compute_active_cycles_total",
                        "StatisticType": "Accumulator",
                        "SimTime": "2065000",
                        "Rank": "0",
                        "Count.u64": "1",
                        "Sum.u64": "0",
                        "SumSQ.u64": "0",
                        "Min.u64": "0",
                        "Max.u64": "0",
                        "Sum.f64": "0",
                        "SumSQ.f64": "0",
                        "Min.f64": "0",
                        "Max.f64": "0",
                    },
                ],
            )

            proc = self._run_export(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary_csv = (run_dir / "thermal" / "summary" / "tile_temperature_summary.csv").read_text(encoding="utf-8")
            self.assertIn("compute_active_cycles_total", summary_csv)
            self.assertIn("tile_00_comp", summary_csv)

            ptrace_map = self._load_ptrace_map(run_dir / "thermal" / "hotspot" / "snndl_mesh.ptrace")
            self.assertGreater(ptrace_map["tile_00_comp"], ptrace_map["tile_01_comp"])

    def test_export_runs_hotspot_and_populates_temperature_summary_for_block_model(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                        ],
                        "sim_time_actual_ns": 1000,
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "window_ns": 1000,
                            "out_dir": "thermal",
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "800",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "0",
                        "SimTime": "0",
                    },
                ],
            )

            fake_hotspot = run_dir / "fake_hotspot.py"
            _write_executable(
                fake_hotspot,
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import sys
                    from pathlib import Path

                    args = sys.argv[1:]
                    def arg_value(flag: str) -> str:
                        idx = args.index(flag)
                        return args[idx + 1]

                    config_path = Path(arg_value("-c"))
                    cfg = config_path.read_text(encoding="utf-8")
                    if "-model_type" not in cfg or "-ambient" not in cfg or "-t_interface" not in cfg:
                        print("bad config", file=sys.stderr)
                        raise SystemExit(9)
                    if "block" in cfg and ("-grid_steady_file" in args or "-grid_transient_file" in args):
                        print("unexpected grid outputs for block model", file=sys.stderr)
                        raise SystemExit(7)

                    steady_path = Path(arg_value("-steady_file"))
                    transient_path = Path(arg_value("-o"))

                    steady_path.write_text(
                        "tile_00_comp\\t350.15\\n"
                        "tile_00_sram\\t349.15\\n"
                        "tile_00_noc\\t348.15\\n"
                        "tile_01_comp\\t330.15\\n"
                        "tile_01_sram\\t329.15\\n"
                        "tile_01_noc\\t328.15\\n",
                        encoding="utf-8",
                    )
                    transient_path.write_text("ok\\n", encoding="utf-8")
                    """
                ),
            )

            proc = self._run_export(run_dir, "--hotspot-bin", str(fake_hotspot))
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "thermal" / "summary" / "thermal_summary.json").read_text(encoding="utf-8"))
            hotspot = summary.get("hotspot") or {}
            self.assertEqual(str(hotspot.get("status") or ""), "ran")

            cfg_text = (run_dir / "thermal" / "hotspot" / "hotspot.config").read_text(encoding="utf-8")
            self.assertIn("-model_type", cfg_text)
            self.assertIn("block", cfg_text)
            self.assertIn("-ambient", cfg_text)
            self.assertIn("-t_interface", cfg_text)

            artifacts = summary.get("artifacts") or {}
            self.assertNotIn("grid_steady", artifacts)
            self.assertNotIn("grid_transient", artifacts)

            with (run_dir / "thermal" / "summary" / "tile_temperature_summary.csv").open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            row_by_block = {str(row.get("block_name") or ""): row for row in rows}
            self.assertEqual(row_by_block["tile_00_comp"]["temperature_c"], "77.00")
            self.assertEqual(row_by_block["tile_01_comp"]["temperature_c"], "57.00")

    def test_export_generates_hotspot_3d_grid_artifacts_from_layers(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                        ],
                        "sim_time_actual_ns": 1000,
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "model_type": "grid",
                            "grid_rows": 64,
                            "grid_cols": 48,
                            "grid_map_mode": "center",
                            "detailed_3d": 1,
                            "window_ns": 1000,
                            "out_dir": "thermal",
                            "layers": [
                                {"name": "compute_top", "kind": "mesh_active", "z_um": 0, "thickness_um": 150},
                                {"name": "tim_mid", "kind": "tim", "z_um": 150, "thickness_um": 20},
                                {
                                    "name": "compute_bottom",
                                    "kind": "mesh_active",
                                    "z_um": 170,
                                    "thickness_um": 150,
                                    "power_scale": 0.5,
                                },
                            ],
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "800",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "0",
                        "SimTime": "0",
                    },
                ],
            )

            fake_hotspot = run_dir / "fake_hotspot_3d.py"
            _write_executable(
                fake_hotspot,
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import sys
                    from pathlib import Path

                    args = sys.argv[1:]
                    def arg_value(flag: str) -> str:
                        idx = args.index(flag)
                        return args[idx + 1]

                    config_path = Path(arg_value("-c"))
                    cfg = config_path.read_text(encoding="utf-8")
                    if "-model_type" not in cfg or "grid" not in cfg:
                        print("grid model config missing", file=sys.stderr)
                        raise SystemExit(9)
                    if "-grid_map_mode" not in cfg or "center" not in cfg:
                        print("grid map mode missing", file=sys.stderr)
                        raise SystemExit(8)
                    if "-detailed_3D" not in cfg or "on" not in cfg:
                        print("detailed_3d missing", file=sys.stderr)
                        raise SystemExit(7)
                    if "-f" in args:
                        print("unexpected floorplan arg for grid LCF model", file=sys.stderr)
                        raise SystemExit(6)

                    lcf_path = Path(arg_value("-grid_layer_file"))
                    grid_steady_path = Path(arg_value("-grid_steady_file"))
                    grid_transient_path = Path(arg_value("-grid_transient_file"))
                    steady_path = Path(arg_value("-steady_file"))
                    transient_path = Path(arg_value("-o"))

                    raw_lines = [line.strip() for line in lcf_path.read_text(encoding="utf-8").splitlines()]
                    lines = [line for line in raw_lines if line and not line.startswith("#")]
                    if len(lines) % 7 != 0:
                        print("bad lcf", file=sys.stderr)
                        raise SystemExit(5)
                    layer_entries = [
                        (int(lines[idx]), Path(lines[idx + 6]))
                        for idx in range(0, len(lines), 7)
                    ]
                    block_names = []
                    for layer_index, flp_path in layer_entries:
                        for raw in flp_path.read_text(encoding="utf-8").splitlines():
                            line = raw.strip()
                            if not line or line.startswith("#"):
                                continue
                            block_names.append(f"layer_{layer_index}_" + line.split()[0])

                    steady_path.write_text(
                        "".join(f"{name}\\t350.15\\n" for name in block_names),
                        encoding="utf-8",
                    )
                    transient_path.write_text("ok\\n", encoding="utf-8")
                    grid_steady_path.write_text("grid steady\\n", encoding="utf-8")
                    grid_transient_path.write_text("grid transient\\n", encoding="utf-8")
                    """
                ),
            )

            proc = self._run_export(run_dir, "--hotspot-bin", str(fake_hotspot))
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            summary = json.loads((run_dir / "thermal" / "summary" / "thermal_summary.json").read_text(encoding="utf-8"))
            hotspot = summary.get("hotspot") or {}
            self.assertEqual(str(hotspot.get("status") or ""), "ran")
            self.assertEqual(str(summary.get("hotspot_model_type") or ""), "grid")
            self.assertEqual(int(summary.get("layer_count") or 0), 3)
            stack_validation = dict(summary.get("layer_stack_validation") or {})
            self.assertEqual(bool(stack_validation.get("passed")), True)
            self.assertEqual(int(stack_validation.get("layer_count_checked") or 0), 3)
            self.assertEqual(int(stack_validation.get("mismatch_count") or 0), 0)

            cfg_text = (run_dir / "thermal" / "hotspot" / "hotspot.config").read_text(encoding="utf-8")
            self.assertIn("-model_type", cfg_text)
            self.assertIn("grid", cfg_text)
            self.assertIn("-grid_map_mode", cfg_text)
            self.assertIn("center", cfg_text)

            artifacts = summary.get("artifacts") or {}
            self.assertIn("lcf", artifacts)
            self.assertIn("layer_floorplans", artifacts)
            self.assertIn("grid_steady", artifacts)
            self.assertIn("grid_transient", artifacts)
            self.assertIn("layer_stack_validation", artifacts)

            lcf_text = (run_dir / "thermal" / "hotspot" / "snndl_mesh.lcf").read_text(encoding="utf-8")
            self.assertIn("compute_top", lcf_text)
            self.assertIn("compute_bottom", lcf_text)

            ptrace_text = (run_dir / "thermal" / "hotspot" / "snndl_mesh.ptrace").read_text(encoding="utf-8")
            self.assertIn("L00_compute_top__tile_00_comp", ptrace_text)
            self.assertIn("L02_compute_bottom__tile_00_comp", ptrace_text)
            self.assertNotIn("L01_tim_mid__tile_00_comp", ptrace_text)

            with (run_dir / "thermal" / "summary" / "tile_temperature_summary.csv").open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertGreater(len(rows), 0)
            row_by_block = {str(row.get("block_name") or ""): row for row in rows}
            target = row_by_block["L00_compute_top__tile_00_comp"]
            self.assertEqual(target["layer_name"], "compute_top")
            self.assertEqual(target["temperature_c"], "77.00")

            validation = json.loads(
                (run_dir / "thermal" / "summary" / "layer_stack_validation.json").read_text(encoding="utf-8")
            )
            self.assertEqual(validation["status"], "passed")
            self.assertEqual(validation["config_matches"], True)
            self.assertEqual(validation["config_mismatch_reasons"], [])
            self.assertEqual(validation["grid_config"]["grid_rows_matches"], True)
            self.assertEqual(validation["grid_config"]["grid_cols_matches"], True)
            self.assertEqual(validation["grid_config"]["grid_map_mode_matches"], True)
            self.assertEqual(validation["package_config"]["ambient_k_matches"], True)
            self.assertEqual(validation["package_config"]["t_interface_matches"], True)
            self.assertEqual(validation["package_config"]["s_spreader_matches"], True)
            self.assertEqual(len(validation["layers"]), 3)
            self.assertEqual(validation["layers"][0]["layer_name"], "compute_top")
            self.assertEqual(validation["layers"][1]["layer_name"], "tim_mid")
            self.assertEqual(validation["layers"][2]["layer_name"], "compute_bottom")
            self.assertTrue(all(layer["matches"] for layer in validation["layers"]))

            stack_validation = dict(summary.get("layer_stack_validation") or {})
            self.assertEqual(stack_validation["config_matches"], True)
            self.assertEqual(stack_validation["config_mismatch_reasons"], [])

    def test_export_routes_power_per_layer_using_power_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                        ],
                        "sim_time_actual_ns": 1000,
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "model_type": "grid",
                            "grid_rows": 64,
                            "grid_cols": 48,
                            "grid_map_mode": "center",
                            "detailed_3d": 1,
                            "window_ns": 1000,
                            "out_dir": "thermal",
                            "layers": [
                                {
                                    "name": "compute_top",
                                    "kind": "mesh_active",
                                    "z_um": 0,
                                    "thickness_um": 150,
                                    "power_source": {"type": "mesh_proxy"},
                                },
                                {
                                    "name": "compute_bottom",
                                    "kind": "mesh_active",
                                    "z_um": 170,
                                    "thickness_um": 150,
                                    "power_source": {"type": "none"},
                                },
                            ],
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "800",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "0",
                        "SimTime": "0",
                    },
                ],
            )

            proc = self._run_export(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            ptrace_map = self._load_ptrace_map(run_dir / "thermal" / "hotspot" / "snndl_mesh.ptrace")
            self.assertGreater(ptrace_map["L00_compute_top__tile_00_comp"], 0.0)
            self.assertEqual(ptrace_map["L01_compute_bottom__tile_00_comp"], 0.0)
            self.assertGreater(ptrace_map["L00_compute_top__tile_01_comp"], 0.0)
            self.assertEqual(ptrace_map["L01_compute_bottom__tile_01_comp"], 0.0)

            with (run_dir / "thermal" / "summary" / "tile_temperature_summary.csv").open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            row_by_block = {str(row.get("block_name") or ""): row for row in rows}
            self.assertEqual(row_by_block["L00_compute_top__tile_00_comp"]["power_source_type"], "mesh_proxy")
            self.assertEqual(row_by_block["L01_compute_bottom__tile_00_comp"]["power_source_type"], "none")
            self.assertNotEqual(row_by_block["L00_compute_top__tile_00_comp"]["average_power_w"], "0.000000e+00")
            self.assertEqual(row_by_block["L01_compute_bottom__tile_00_comp"]["average_power_w"], "0.000000e+00")

            summary = json.loads((run_dir / "thermal" / "summary" / "thermal_summary.json").read_text(encoding="utf-8"))
            layers = list(summary.get("layers") or [])
            self.assertEqual(layers[0]["power_source"]["type"], "mesh_proxy")
            self.assertEqual(layers[1]["power_source"]["type"], "none")

    def test_export_routes_power_with_stats_prefix_filters(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                        ],
                        "sim_time_actual_ns": 1000,
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "model_type": "grid",
                            "grid_rows": 64,
                            "grid_cols": 48,
                            "grid_map_mode": "center",
                            "detailed_3d": 1,
                            "window_ns": 1000,
                            "out_dir": "thermal",
                            "layers": [
                                {
                                    "name": "cycles_top",
                                    "kind": "mesh_active",
                                    "z_um": 0,
                                    "thickness_um": 150,
                                    "power_source": {
                                        "type": "stats_prefix",
                                        "component_prefixes": ["multicore_pe_"],
                                        "statistic_prefixes": ["sim_cycles_total", "compute_active_cycles_total"],
                                    },
                                },
                                {
                                    "name": "noc_bottom",
                                    "kind": "mesh_active",
                                    "z_um": 170,
                                    "thickness_um": 150,
                                    "power_source": {
                                        "type": "stats_prefix",
                                        "component_prefixes": ["multicore_pe_"],
                                        "statistic_prefixes": [
                                            "packets_sent",
                                            "packets_received",
                                            "payload_bytes_sent",
                                            "payload_bytes_received",
                                            "hop_count_sum",
                                        ],
                                    },
                                },
                            ],
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "800",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "0",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0:network_interface",
                        "StatisticName": "packets_sent",
                        "Sum.u64": "42",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0:network_interface",
                        "StatisticName": "payload_bytes_sent",
                        "Sum.u64": "420",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1:network_interface",
                        "StatisticName": "packets_sent",
                        "Sum.u64": "21",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1:network_interface",
                        "StatisticName": "payload_bytes_sent",
                        "Sum.u64": "210",
                        "SimTime": "0",
                    },
                ],
            )

            proc = self._run_export(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            ptrace_map = self._load_ptrace_map(run_dir / "thermal" / "hotspot" / "snndl_mesh.ptrace")
            self.assertGreater(ptrace_map["L00_cycles_top__tile_00_comp"], 0.0)
            self.assertEqual(ptrace_map["L00_cycles_top__tile_00_noc"], 0.0)
            self.assertGreater(ptrace_map["L01_noc_bottom__tile_00_noc"], 0.0)
            self.assertEqual(ptrace_map["L01_noc_bottom__tile_00_sram"], 0.0)

            with (run_dir / "thermal" / "summary" / "tile_temperature_summary.csv").open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            row_by_block = {str(row.get("block_name") or ""): row for row in rows}
            self.assertEqual(row_by_block["L00_cycles_top__tile_00_comp"]["power_source_type"], "stats_prefix")
            self.assertEqual(row_by_block["L01_noc_bottom__tile_00_comp"]["power_source_type"], "stats_prefix")
            self.assertEqual(row_by_block["L00_cycles_top__tile_00_noc"]["average_power_w"], "0.000000e+00")
            self.assertNotEqual(row_by_block["L01_noc_bottom__tile_00_noc"]["average_power_w"], "0.000000e+00")
            self.assertEqual(row_by_block["L00_cycles_top__tile_00_comp"]["cycle_model_applicable"], "1")
            self.assertEqual(row_by_block["L01_noc_bottom__tile_00_noc"]["cycle_model_applicable"], "0")

            summary = json.loads((run_dir / "thermal" / "summary" / "thermal_summary.json").read_text(encoding="utf-8"))
            layers = list(summary.get("layers") or [])
            self.assertEqual(str(summary.get("power_source_contract_version") or ""), "v1")
            self.assertEqual(layers[0]["power_source"]["type"], "stats_prefix")
            self.assertEqual(layers[0]["cycle_model_applicable"], True)
            self.assertEqual(layers[0]["power_source"]["component_prefixes"], ["multicore_pe_"])
            self.assertEqual(layers[1]["cycle_model_applicable"], False)
            self.assertEqual(
                layers[1]["power_source"]["statistic_prefixes"],
                ["packets_sent", "packets_received", "payload_bytes_sent", "payload_bytes_received", "hop_count_sum"],
            )

    def test_export_marks_cycle_model_applicable_false_when_cycle_stats_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                        ],
                        "sim_time_actual_ns": 1000,
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "model_type": "grid",
                            "grid_rows": 64,
                            "grid_cols": 48,
                            "grid_map_mode": "center",
                            "detailed_3d": 1,
                            "window_ns": 1000,
                            "out_dir": "thermal",
                            "layers": [
                                {
                                    "name": "cycles_top",
                                    "kind": "mesh_active",
                                    "z_um": 0,
                                    "thickness_um": 150,
                                    "power_source": {
                                        "type": "stats_prefix",
                                        "component_prefixes": ["multicore_pe_"],
                                        "statistic_prefixes": ["sim_cycles_total", "compute_active_cycles_total"],
                                    },
                                }
                            ],
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                ],
            )

            proc = self._run_export(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            with (run_dir / "thermal" / "summary" / "tile_temperature_summary.csv").open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            row_by_block = {str(row.get("block_name") or ""): row for row in rows}
            self.assertEqual(row_by_block["L00_cycles_top__tile_00_comp"]["model_source"], "proxy_fallback")
            self.assertEqual(row_by_block["L00_cycles_top__tile_00_comp"]["cycle_model_applicable"], "0")
            self.assertEqual(row_by_block["L00_cycles_top__tile_01_comp"]["cycle_model_applicable"], "0")

            summary = json.loads((run_dir / "thermal" / "summary" / "thermal_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary.get("cycle_model_applicable"), False)
            layers = list(summary.get("layers") or [])
            self.assertEqual(len(layers), 1)
            self.assertEqual(layers[0]["cycle_model_applicable"], False)

    def test_export_routes_power_with_csv_source(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            csv_path = run_dir / "layer_power.csv"
            _write_csv(
                csv_path,
                [
                    {"tile_id": "0", "comp_power_w": "0.125", "sram_power_w": "0.050", "noc_power_w": "0.025"},
                    {"tile_id": "1", "comp_power_w": "0.250", "sram_power_w": "0.100", "noc_power_w": "0.050"},
                ],
            )
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                        ],
                        "sim_time_actual_ns": 1000,
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "model_type": "grid",
                            "grid_rows": 64,
                            "grid_cols": 48,
                            "grid_map_mode": "center",
                            "detailed_3d": 1,
                            "window_ns": 1000,
                            "out_dir": "thermal",
                            "layers": [
                                {
                                    "name": "csv_top",
                                    "kind": "mesh_active",
                                    "z_um": 0,
                                    "thickness_um": 150,
                                    "power_scale": 0.5,
                                    "power_source": {
                                        "type": "csv",
                                        "csv_path": str(csv_path),
                                    },
                                }
                            ],
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "sim_cycles_total",
                        "Sum.u64": "1000",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "compute_active_cycles_total",
                        "Sum.u64": "400",
                        "SimTime": "0",
                    }
                ],
            )

            proc = self._run_export(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            ptrace_map = self._load_ptrace_map(run_dir / "thermal" / "hotspot" / "snndl_mesh.ptrace")
            self.assertAlmostEqual(ptrace_map["L00_csv_top__tile_00_comp"], 0.0625, places=9)
            self.assertAlmostEqual(ptrace_map["L00_csv_top__tile_00_sram"], 0.0250, places=9)
            self.assertAlmostEqual(ptrace_map["L00_csv_top__tile_00_noc"], 0.0125, places=9)
            self.assertAlmostEqual(ptrace_map["L00_csv_top__tile_01_comp"], 0.1250, places=9)
            self.assertAlmostEqual(ptrace_map["L00_csv_top__tile_01_sram"], 0.0500, places=9)
            self.assertAlmostEqual(ptrace_map["L00_csv_top__tile_01_noc"], 0.0250, places=9)

            with (run_dir / "thermal" / "summary" / "tile_temperature_summary.csv").open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            row_by_block = {str(row.get("block_name") or ""): row for row in rows}
            self.assertEqual(row_by_block["L00_csv_top__tile_00_comp"]["power_source_type"], "csv")
            self.assertEqual(row_by_block["L00_csv_top__tile_00_comp"]["model_source"], "csv")
            self.assertEqual(row_by_block["L00_csv_top__tile_00_comp"]["average_power_w"], "6.250000e-02")
            self.assertEqual(row_by_block["L00_csv_top__tile_00_comp"]["cycle_model_applicable"], "0")
            self.assertEqual(row_by_block["L00_csv_top__tile_00_comp"]["sim_cycles_total"], "")
            self.assertEqual(row_by_block["L00_csv_top__tile_00_comp"]["compute_active_cycles_total"], "")
            self.assertEqual(row_by_block["L00_csv_top__tile_01_noc"]["average_power_w"], "2.500000e-02")

            summary = json.loads((run_dir / "thermal" / "summary" / "thermal_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(str(summary.get("power_source_contract_version") or ""), "v1")
            self.assertEqual(summary.get("cycle_model_applicable"), False)
            layers = list(summary.get("layers") or [])
            self.assertEqual(layers[0]["power_source"]["type"], "csv")
            self.assertEqual(layers[0]["power_source"]["csv_path"], str(csv_path))
            self.assertEqual(layers[0]["cycle_model_applicable"], False)

    def test_export_includes_memctrl_block_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            (run_dir / "effective_config.json").write_text(
                json.dumps(
                    {
                        "per_core": [
                            {"pe": 0, "core": 0},
                            {"pe": 1, "core": 0},
                        ],
                        "sim_time_actual_ns": 1000,
                        "thermal": {
                            "enable": 1,
                            "backend": "hotspot",
                            "window_ns": 1000,
                            "include_memctrl": 1,
                            "out_dir": "thermal",
                        },
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_csv(
                run_dir / "mesh_stats.csv",
                [
                    {
                        "ComponentName": "multicore_pe_0",
                        "StatisticName": "core_state_sram_energy_read_pj_total",
                        "Sum.f64": "2000.0",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_0:network_interface",
                        "StatisticName": "payload_bytes_sent",
                        "Sum.u64": "512",
                        "SimTime": "0",
                    },
                    {
                        "ComponentName": "multicore_pe_1:network_interface",
                        "StatisticName": "payload_bytes_sent",
                        "Sum.u64": "256",
                        "SimTime": "0",
                    },
                ],
            )

            proc = self._run_export(run_dir)
            self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)

            flp_text = (run_dir / "thermal" / "hotspot" / "snndl_mesh.flp").read_text(encoding="utf-8")
            self.assertIn("mesh_memctrl_east", flp_text)

            ptrace_map = self._load_ptrace_map(run_dir / "thermal" / "hotspot" / "snndl_mesh.ptrace")
            self.assertIn("mesh_memctrl_east", ptrace_map)
            self.assertGreater(ptrace_map["mesh_memctrl_east"], 0.0)

            with (run_dir / "thermal" / "summary" / "tile_temperature_summary.csv").open("r", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            row_by_block = {str(row.get("block_name") or ""): row for row in rows}
            self.assertEqual(row_by_block["mesh_memctrl_east"]["block_type"], "memctrl")
            self.assertEqual(row_by_block["mesh_memctrl_east"]["trace_source"], "memctrl_proxy")
            self.assertEqual(row_by_block["mesh_memctrl_east"]["trace_mode"], "average")
            self.assertGreater(float(row_by_block["mesh_memctrl_east"]["average_power_w"]), 0.0)

            summary = json.loads((run_dir / "thermal" / "summary" / "thermal_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["memctrl"]["enabled"], True)
            self.assertEqual(int(summary["memctrl"]["block_count"] or 0), 1)
            self.assertGreater(float(summary["memctrl"]["total_power_w"] or 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
