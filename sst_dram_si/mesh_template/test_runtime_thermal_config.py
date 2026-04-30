from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.modules.setdefault("sst", types.SimpleNamespace())

from sst_dram_si.mesh_template import build as build_mod
from sst_dram_si.mesh_template.runtime import _EnvPatch
from sst_dram_si.mesh_template.runtime import resolve_runtime


class _FakeSST:
    def setStatisticLoadLevel(self, _level):
        pass

    def setStatisticOutput(self, _output_type):
        pass

    def setStatisticOutputOptions(self, _opts):
        pass

    def enableAllStatisticsForComponentType(self, *_args, **_kwargs):
        pass

    def enableAllStatisticsForAllComponents(self, *_args, **_kwargs):
        pass


class RuntimeThermalConfigTests(unittest.TestCase):
    def _make_script_file(self, root: Path) -> Path:
        script_dir = root / "sst_dram_si"
        script_dir.mkdir(parents=True, exist_ok=True)
        (script_dir / "weights").mkdir(parents=True, exist_ok=True)
        (script_dir / "fw").mkdir(parents=True, exist_ok=True)
        script_file = script_dir / "test_mesh_4x4.py"
        script_file.write_text("from __future__ import annotations\n", encoding="utf-8")
        return script_file

    def _write_spec_file(self, root: Path, payload: dict) -> Path:
        spec_path = root / "mesh_spec.json"
        spec_path.write_text(json.dumps(payload), encoding="utf-8")
        return spec_path

    def test_thermal_env_is_exported_into_runtime_mesh_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            run_dir = root / "run_thermal"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_GLOBAL_STEP_SYNC": "0",
                    "MESH_THERMAL_ENABLE": "1",
                    "MESH_THERMAL_BACKEND": "hotspot",
                    "MESH_THERMAL_WINDOW_NS": "1000",
                    "MESH_THERMAL_OUT_DIR": "thermal",
                    "MESH_THERMAL_TILE_WIDTH_UM": "1000",
                    "MESH_THERMAL_TILE_HEIGHT_UM": "1000",
                    "MESH_THERMAL_TILE_GAP_UM": "50",
                    "MESH_THERMAL_COMP_FRAC": "0.6",
                    "MESH_THERMAL_SRAM_FRAC": "0.25",
                    "MESH_THERMAL_NOC_FRAC": "0.15",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            thermal = dict(rt.mesh_cfg.get("thermal", {}) or {})
            self.assertEqual(int(thermal.get("enable") or 0), 1)
            self.assertEqual(str(thermal.get("backend") or ""), "hotspot")
            self.assertEqual(int(thermal.get("window_ns") or 0), 1000)
            self.assertEqual(str(thermal.get("out_dir") or ""), "thermal")
            self.assertEqual(int(thermal.get("tile_width_um") or 0), 1000)
            self.assertEqual(int(thermal.get("tile_height_um") or 0), 1000)
            self.assertEqual(int(thermal.get("tile_gap_um") or 0), 50)
            self.assertAlmostEqual(float(thermal.get("comp_frac") or 0.0), 0.6)
            self.assertAlmostEqual(float(thermal.get("sram_frac") or 0.0), 0.25)
            self.assertAlmostEqual(float(thermal.get("noc_frac") or 0.0), 0.15)

    def test_spec_first_preserves_thermal_env_into_runtime_mesh_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            spec_file = self._write_spec_file(
                root,
                {
                    "schema_version": 1,
                    "model": "mesh",
                    "platform": {
                        "mesh_size": 4,
                        "stop": {"mode": "time", "simulation_time": "1us"},
                    },
                    "control": {"global_step_sync_enable": False},
                },
            )
            run_dir = root / "run_spec_thermal"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_SPEC_JSON": str(spec_file),
                    "MESH_THERMAL_ENABLE": "1",
                    "MESH_THERMAL_BACKEND": "hotspot",
                    "MESH_THERMAL_WINDOW_NS": "1000",
                    "MESH_THERMAL_OUT_DIR": "thermal",
                    "MESH_THERMAL_TILE_WIDTH_UM": "1000",
                    "MESH_THERMAL_TILE_HEIGHT_UM": "1000",
                    "MESH_THERMAL_TILE_GAP_UM": "50",
                    "MESH_THERMAL_COMP_FRAC": "0.6",
                    "MESH_THERMAL_SRAM_FRAC": "0.25",
                    "MESH_THERMAL_NOC_FRAC": "0.15",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            thermal = dict(rt.mesh_cfg.get("thermal", {}) or {})
            self.assertEqual(int(thermal.get("enable") or 0), 1)
            self.assertEqual(str(thermal.get("backend") or ""), "hotspot")
            self.assertEqual(int(thermal.get("window_ns") or 0), 1000)
            self.assertEqual(str(thermal.get("out_dir") or ""), "thermal")
            self.assertEqual(int(thermal.get("tile_width_um") or 0), 1000)
            self.assertEqual(int(thermal.get("tile_height_um") or 0), 1000)
            self.assertEqual(int(thermal.get("tile_gap_um") or 0), 50)
            self.assertAlmostEqual(float(thermal.get("comp_frac") or 0.0), 0.6)
            self.assertAlmostEqual(float(thermal.get("sram_frac") or 0.0), 0.25)
            self.assertAlmostEqual(float(thermal.get("noc_frac") or 0.0), 0.15)

    def test_spec_first_uses_thermal_spec_into_runtime_mesh_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            spec_file = self._write_spec_file(
                root,
                {
                    "schema_version": 1,
                    "model": "mesh",
                    "platform": {
                        "mesh_size": 4,
                        "stop": {"mode": "time", "simulation_time": "1us"},
                    },
                    "control": {"global_step_sync_enable": False},
                    "thermal": {
                        "enable": 1,
                        "backend": "hotspot",
                        "window_ns": 2500,
                        "window_trace_enable": 1,
                        "window_trace_max_rows": 32,
                        "include_memctrl": 1,
                        "out_dir": "thermal_spec",
                        "tile_width_um": 2000,
                        "tile_height_um": 1500,
                        "tile_gap_um": 75,
                        "comp_frac": 0.5,
                        "sram_frac": 0.3,
                        "noc_frac": 0.2,
                    },
                },
            )
            run_dir = root / "run_spec_thermal_cfg"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_SPEC_JSON": str(spec_file),
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            thermal = dict(rt.mesh_cfg.get("thermal", {}) or {})
            self.assertEqual(int(thermal.get("enable") or 0), 1)
            self.assertEqual(str(thermal.get("backend") or ""), "hotspot")
            self.assertEqual(int(thermal.get("window_ns") or 0), 2500)
            self.assertEqual(int(thermal.get("window_trace_enable") or 0), 1)
            self.assertEqual(int(thermal.get("window_trace_max_rows") or 0), 32)
            self.assertEqual(int(thermal.get("include_memctrl") or 0), 1)
            self.assertEqual(str(thermal.get("out_dir") or ""), "thermal_spec")
            self.assertEqual(int(thermal.get("tile_width_um") or 0), 2000)
            self.assertEqual(int(thermal.get("tile_height_um") or 0), 1500)
            self.assertEqual(int(thermal.get("tile_gap_um") or 0), 75)
            self.assertAlmostEqual(float(thermal.get("comp_frac") or 0.0), 0.5)
            self.assertAlmostEqual(float(thermal.get("sram_frac") or 0.0), 0.3)
            self.assertAlmostEqual(float(thermal.get("noc_frac") or 0.0), 0.2)

    def test_spec_first_exports_riscv_snn_workload_params_into_runtime_mesh_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            fw = root / "sst_dram_si" / "fw" / "riscv_snn_p0.elf"
            fw.write_bytes(b"\x7fELF")
            spec_file = self._write_spec_file(
                root,
                {
                    "schema_version": 3,
                    "model": "mesh",
                    "platform": {
                        "mesh_size": 4,
                        "stop": {"mode": "time", "simulation_time": "1us"},
                    },
                    "control": {"global_step_sync_enable": False},
                    "workload": {
                        "type": "riscv_snn",
                        "params": {
                            "firmware_elf": "sst_dram_si/fw/riscv_snn_p0.elf",
                            "backend_name": "runtime_bridge",
                            "hart_isa": "rv64im_zicsr",
                            "local_mem_bytes": 131072,
                            "cmd_queue_entries": 64,
                            "cmp_queue_entries": 32,
                            "rx_debug_queue_entries": 8,
                            "boot_addr": 4096,
                        },
                    },
                },
            )
            run_dir = root / "run_spec_riscv_snn"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_SPEC_JSON": str(spec_file),
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            self.assertEqual(rt.mesh_cfg.get("workload_impl"), "riscv_snn")
            wl = dict(rt.mesh_cfg.get("workload_params", {}) or {})
            self.assertEqual(wl.get("backend_name"), "runtime_bridge")
            self.assertEqual(wl.get("hart_isa"), "rv64im_zicsr")
            self.assertEqual(int(wl.get("local_mem_bytes") or 0), 131072)
            self.assertEqual(int(wl.get("cmd_queue_entries") or 0), 64)
            self.assertEqual(int(wl.get("cmp_queue_entries") or 0), 32)
            self.assertEqual(int(wl.get("rx_debug_queue_entries") or 0), 8)
            self.assertEqual(int(wl.get("boot_addr") or 0), 4096)
            self.assertEqual(wl.get("firmware_elf"), str(fw))

    def test_spec_first_thermal_env_overrides_thermal_spec(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            spec_file = self._write_spec_file(
                root,
                {
                    "schema_version": 1,
                    "model": "mesh",
                    "platform": {
                        "mesh_size": 4,
                        "stop": {"mode": "time", "simulation_time": "1us"},
                    },
                    "control": {"global_step_sync_enable": False},
                    "thermal": {
                        "enable": 0,
                        "backend": "hotspot",
                        "window_ns": 2500,
                        "out_dir": "thermal_spec",
                    },
                },
            )
            run_dir = root / "run_spec_thermal_override"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_SPEC_JSON": str(spec_file),
                    "MESH_THERMAL_ENABLE": "1",
                    "MESH_THERMAL_WINDOW_NS": "1000",
                    "MESH_THERMAL_OUT_DIR": "thermal_env",
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            thermal = dict(rt.mesh_cfg.get("thermal", {}) or {})
            self.assertEqual(int(thermal.get("enable") or 0), 1)
            self.assertEqual(int(thermal.get("window_ns") or 0), 1000)
            self.assertEqual(str(thermal.get("out_dir") or ""), "thermal_env")

    def test_spec_first_uses_thermal_3d_spec_into_runtime_mesh_cfg(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            script_file = self._make_script_file(root)
            spec_file = self._write_spec_file(
                root,
                {
                    "schema_version": 1,
                    "platform": {
                        "mesh_size": 4,
                        "stop": {"mode": "time", "simulation_time": "1us"},
                    },
                    "control": {"global_step_sync_enable": False},
                    "thermal": {
                        "enable": 1,
                        "backend": "hotspot",
                        "model_type": "grid",
                        "grid_rows": 64,
                        "grid_cols": 48,
                        "grid_map_mode": "center",
                        "detailed_3d": 1,
                        "layers": [
                            {
                                "name": "compute_top",
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
                                "name": "tim_mid",
                                "kind": "tim",
                                "z_um": 150,
                                "thickness_um": 20,
                                "power_source": {"type": "none"},
                            },
                            {
                                "name": "compute_bottom",
                                "kind": "mesh_active",
                                "z_um": 170,
                                "thickness_um": 150,
                                "power_source": {
                                    "type": "csv",
                                    "csv_path": "tools/specs/thermal_csv_profiles/mesh_hotspot_csv_layer_profile_v1.csv",
                                },
                            },
                        ],
                    },
                },
            )
            run_dir = root / "run_spec_thermal_3d"
            with _EnvPatch(
                {
                    "MESH_RUN_DIR": str(run_dir),
                    "MESH_SPEC_JSON": str(spec_file),
                }
            ):
                rt = resolve_runtime(sst_module=_FakeSST(), script_file=str(script_file))

            thermal = dict(rt.mesh_cfg.get("thermal", {}) or {})
            self.assertEqual(str(thermal.get("model_type") or ""), "grid")
            self.assertEqual(int(thermal.get("grid_rows") or 0), 64)
            self.assertEqual(int(thermal.get("grid_cols") or 0), 48)
            self.assertEqual(str(thermal.get("grid_map_mode") or ""), "center")
            self.assertEqual(int(thermal.get("detailed_3d") or 0), 1)
            layers = list(thermal.get("layers") or [])
            self.assertEqual(len(layers), 3)
            self.assertEqual(layers[0]["name"], "compute_top")
            self.assertEqual(layers[0]["power_source"]["type"], "stats_prefix")
            self.assertEqual(layers[0]["power_source"]["component_prefixes"], ["multicore_pe_"])
            self.assertEqual(
                layers[0]["power_source"]["statistic_prefixes"],
                ["sim_cycles_total", "compute_active_cycles_total"],
            )
            self.assertEqual(int(layers[1]["thickness_um"]), 20)
            self.assertEqual(layers[1]["power_source"]["type"], "none")
            self.assertEqual(layers[2]["power_source"]["type"], "csv")
            self.assertEqual(
                layers[2]["power_source"]["csv_path"],
                "tools/specs/thermal_csv_profiles/mesh_hotspot_csv_layer_profile_v1.csv",
            )

    def test_build_helper_exports_effective_thermal_config(self) -> None:
        helper = getattr(build_mod, "make_effective_thermal_config")
        cfg = helper(
            mesh={
                "thermal": {
                    "enable": 1,
                    "backend": "hotspot",
                    "window_ns": 1000,
                    "window_trace_enable": 1,
                    "window_trace_max_rows": 24,
                    "include_memctrl": 1,
                    "out_dir": "thermal",
                    "tile_width_um": 1000,
                    "tile_height_um": 1000,
                    "tile_gap_um": 50,
                    "comp_frac": 0.6,
                    "sram_frac": 0.25,
                    "noc_frac": 0.15,
                }
            }
        )
        self.assertEqual(int(cfg.get("enable") or 0), 1)
        self.assertEqual(str(cfg.get("backend") or ""), "hotspot")
        self.assertEqual(int(cfg.get("window_ns") or 0), 1000)
        self.assertEqual(int(cfg.get("window_trace_enable") or 0), 1)
        self.assertEqual(int(cfg.get("window_trace_max_rows") or 0), 24)
        self.assertEqual(int(cfg.get("include_memctrl") or 0), 1)
        self.assertEqual(str(cfg.get("out_dir") or ""), "thermal")
        self.assertEqual(int(cfg.get("tile_gap_um") or 0), 50)

    def test_build_helper_resolves_window_metrics_export_path_when_enabled(self) -> None:
        helper = getattr(build_mod, "resolve_window_metrics_export_path")
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            path = helper(
                run_output_dir=str(run_dir),
                pe_id=0,
                core_id=0,
                mesh={
                    "thermal": {
                        "enable": 1,
                        "window_trace_enable": 1,
                    }
                },
            )
        self.assertEqual(path, str(run_dir / "pe00" / "core00_window_metrics.csv"))

    def test_build_helper_disables_window_metrics_export_path_when_trace_disabled(self) -> None:
        helper = getattr(build_mod, "resolve_window_metrics_export_path")
        path = helper(
            run_output_dir="/tmp/mesh_run",
            pe_id=0,
            core_id=0,
            mesh={
                "thermal": {
                    "enable": 1,
                    "window_trace_enable": 0,
                }
            },
        )
        self.assertEqual(path, "")

    def test_build_helper_exports_effective_thermal_3d_config(self) -> None:
        helper = getattr(build_mod, "make_effective_thermal_config")
        cfg = helper(
            mesh={
                "thermal": {
                    "enable": 1,
                    "backend": "hotspot",
                    "model_type": "grid",
                    "grid_rows": 64,
                    "grid_cols": 48,
                    "grid_map_mode": "center",
                    "detailed_3d": 1,
                    "layers": [
                        {
                            "name": "compute_top",
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
                            "name": "tim_mid",
                            "kind": "tim",
                            "z_um": 150,
                            "thickness_um": 20,
                            "power_source": {"type": "none"},
                        },
                    ],
                }
            }
        )
        self.assertEqual(str(cfg.get("model_type") or ""), "grid")
        self.assertEqual(int(cfg.get("grid_rows") or 0), 64)
        self.assertEqual(int(cfg.get("grid_cols") or 0), 48)
        self.assertEqual(str(cfg.get("grid_map_mode") or ""), "center")
        self.assertEqual(int(cfg.get("detailed_3d") or 0), 1)
        layers = list(cfg.get("layers") or [])
        self.assertEqual(len(layers), 2)
        self.assertEqual(layers[1]["name"], "tim_mid")
        self.assertEqual(layers[0]["power_source"]["type"], "stats_prefix")
        self.assertEqual(layers[0]["power_source"]["component_prefixes"], ["multicore_pe_"])
        self.assertEqual(
            layers[0]["power_source"]["statistic_prefixes"],
            ["sim_cycles_total", "compute_active_cycles_total"],
        )
        self.assertEqual(layers[1]["power_source"]["type"], "none")

    def test_build_helper_exports_effective_thermal_csv_power_source_config(self) -> None:
        helper = getattr(build_mod, "make_effective_thermal_config")
        cfg = helper(
            mesh={
                "thermal": {
                    "enable": 1,
                    "backend": "hotspot",
                    "model_type": "grid",
                    "layers": [
                        {
                            "name": "csv_bottom",
                            "kind": "mesh_active",
                            "z_um": 0,
                            "thickness_um": 150,
                            "power_source": {
                                "type": "csv",
                                "csv_path": "tools/specs/thermal_csv_profiles/mesh_hotspot_csv_layer_profile_v1.csv",
                            },
                        }
                    ],
                }
            }
        )
        layers = list(cfg.get("layers") or [])
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0]["power_source"]["type"], "csv")
        self.assertEqual(
            layers[0]["power_source"]["csv_path"],
            "tools/specs/thermal_csv_profiles/mesh_hotspot_csv_layer_profile_v1.csv",
        )


if __name__ == "__main__":
    unittest.main()
