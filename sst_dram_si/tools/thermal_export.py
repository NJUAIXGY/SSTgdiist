#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

THERMAL_CONTRACT_VERSION = "v2"

PE_COMPONENT_RE = re.compile(r"multicore_pe_(\d+)")

NOC_ENERGY_PJ_PER_PACKET = 1.0
NOC_ENERGY_PJ_PER_BYTE = 0.001
NOC_ENERGY_PJ_PER_HOP = 0.5
COMP_IDLE_ENERGY_PJ_PER_CYCLE = 0.01
COMP_ACTIVE_ENERGY_PJ_PER_CYCLE = 0.1
COMP_BASE_ENERGY_PJ = 100.0
COMP_ENERGY_PJ_PER_SPIKE = 2.0
COMP_ENERGY_FROM_SRAM_RATIO = 0.5
COMP_ENERGY_FROM_NOC_RATIO = 0.25
MEMCTRL_ENERGY_FROM_SRAM_RATIO = 0.25
MEMCTRL_ENERGY_PJ_PER_PACKET = 0.5
MEMCTRL_ENERGY_PJ_PER_BYTE = 0.002
MEMCTRL_DIRECT_POWER_RATIO = 0.1
MEMCTRL_MIN_WIDTH_UM = 100

HOTSPOT_PACKAGE_DEFAULTS: Dict[str, float] = {
    "ambient": 318.15,
    "s_sink": 0.06,
    "t_sink": 0.0069,
    "s_spreader": 0.03,
    "t_spreader": 0.001,
    "t_interface": 2.0e-05,
}

THERMAL_LAYER_KIND_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "mesh_active": {
        "lateral_heat_flow": True,
        "power_dissipating": True,
        "volumetric_heat_capacity": 1.75e6,
        "resistivity": 0.01,
        "power_scale": 1.0,
    },
    "tim": {
        "lateral_heat_flow": True,
        "power_dissipating": False,
        "volumetric_heat_capacity": 4.0e6,
        "resistivity": 0.25,
        "power_scale": 0.0,
    },
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_artifact_provenance(run_dir: Path) -> Dict[str, Any]:
    return {
        "tool": "sst_dram_si.tools.thermal_export",
        "artifact_kind": "thermal_summary",
        "contract_version": THERMAL_CONTRACT_VERSION,
        "generated_at_utc": _utc_now_iso(),
        "source_kind": "run_dir",
        "run_dir": str(run_dir.resolve()),
        "source_paths": {
            "effective_config_json": str((run_dir / "effective_config.json").resolve()),
            "mesh_stats_csv": str((run_dir / "mesh_stats.csv").resolve()),
        },
    }


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _load_stats_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    path.write_text(text, encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    rows_list = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows_list:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: List[str] = []
    for row in rows_list:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows_list:
            writer.writerow(row)


def _load_hotspot_block_temperatures_c(path: Path) -> Dict[str, float]:
    if not path.is_file():
        return {}
    temperatures_c: Dict[str, float] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name = str(parts[0]).strip()
        if name.startswith(("iface_", "hsp_", "hsink_", "inode_")):
            continue
        try:
            temp_k = float(parts[1])
        except Exception:
            continue
        temp_c = temp_k - 273.15
        temperatures_c[name] = temp_c
        alias = re.sub(r"^layer_\d+_", "", name)
        if alias and alias not in temperatures_c:
            temperatures_c[alias] = temp_c
    return temperatures_c


def _parse_hotspot_config_entries(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    out: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or not line.startswith("-"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        out[parts[0].lstrip("-")] = parts[1]
    return out


def _resolve_out_dir(run_dir: Path, raw_out_dir: str) -> Path:
    out_dir = Path(raw_out_dir or "thermal")
    if out_dir.is_absolute():
        return out_dir
    return run_dir / out_dir


def _infer_tile_ids(effective_cfg: Dict[str, Any], stats_rows: List[Dict[str, str]]) -> List[int]:
    tile_ids = set()

    per_core = effective_cfg.get("per_core")
    if isinstance(per_core, list):
        for item in per_core:
            if isinstance(item, dict):
                try:
                    tile_ids.add(int(item.get("pe")))
                except Exception:
                    pass

    for row in stats_rows:
        comp_name = str(row.get("ComponentName") or "")
        match = PE_COMPONENT_RE.search(comp_name)
        if match:
            tile_ids.add(int(match.group(1)))

    if not tile_ids:
        tile_ids.add(0)
    return sorted(tile_ids)


def _infer_mesh_size(tile_count: int) -> int:
    side = int(math.isqrt(max(1, tile_count)))
    if side * side < tile_count:
        side += 1
    return max(1, side)


def _tile_name_width(tile_count: int) -> int:
    return max(2, len(str(max(0, tile_count - 1))))


def _tile_block_names(tile_ids: List[int]) -> List[str]:
    width = _tile_name_width(len(tile_ids))
    names: List[str] = []
    for tile_id in tile_ids:
        base = f"tile_{tile_id:0{width}d}"
        names.extend([f"{base}_comp", f"{base}_sram", f"{base}_noc"])
    return names


def _normalize_fractions(thermal_cfg: Dict[str, Any]) -> Dict[str, float]:
    comp_frac = max(0.0, float(thermal_cfg.get("comp_frac", 0.6) or 0.0))
    sram_frac = max(0.0, float(thermal_cfg.get("sram_frac", 0.25) or 0.0))
    noc_frac = max(0.0, float(thermal_cfg.get("noc_frac", 0.15) or 0.0))
    total = comp_frac + sram_frac + noc_frac
    if total <= 0.0:
        return {"comp": 0.6, "sram": 0.25, "noc": 0.15}
    return {
        "comp": comp_frac / total,
        "sram": sram_frac / total,
        "noc": noc_frac / total,
    }


def _normalize_hotspot_model_type(raw: Any) -> str:
    model_type = str(raw or "").strip().lower()
    if model_type == "grid":
        return "grid"
    return "block"


def _normalize_grid_map_mode(raw: Any) -> str:
    mode = str(raw or "").strip().lower()
    if mode in ("avg", "min", "max", "center"):
        return mode
    return "avg"


def _normalize_string_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        return []
    out: List[str] = []
    for item in items:
        value = str(item or "").strip()
        if value:
            out.append(value)
    return out


def _normalize_thermal_power_source_type(raw: Any) -> str:
    source_type = str(raw or "").strip().lower()
    if source_type in ("mesh_proxy", "mesh-proxy", "meshproxy"):
        return "mesh_proxy"
    if source_type in ("stats_prefix", "stats-prefix", "statsprefix"):
        return "stats_prefix"
    if source_type in ("csv", "table"):
        return "csv"
    if source_type in ("none", "off", "disabled"):
        return "none"
    return ""


def _normalize_thermal_power_source(raw_source: Any, *, default_type: str) -> Dict[str, Any]:
    source = raw_source if isinstance(raw_source, dict) else {}
    source_type = _normalize_thermal_power_source_type(source.get("type"))
    if not source_type:
        source_type = _normalize_thermal_power_source_type(default_type)
    if not source_type:
        source_type = "mesh_proxy"
    if source_type == "stats_prefix":
        return {
            "type": source_type,
            "component_prefixes": _normalize_string_list(source.get("component_prefixes")),
            "statistic_prefixes": _normalize_string_list(source.get("statistic_prefixes")),
        }
    if source_type == "csv":
        return {
            "type": source_type,
            "csv_path": str(source.get("csv_path") or "").strip(),
        }
    return {"type": source_type}


def _power_source_cycle_model_applicable(power_source: Dict[str, Any]) -> bool:
    source_type = str((power_source or {}).get("type") or "mesh_proxy").strip().lower()
    if source_type == "mesh_proxy":
        return True
    if source_type != "stats_prefix":
        return False
    statistic_prefixes = _normalize_string_list((power_source or {}).get("statistic_prefixes"))
    if not statistic_prefixes:
        return True
    for prefix in statistic_prefixes:
        if prefix.startswith("sim_cycles_total") or prefix.startswith("compute_active_cycles_total"):
            return True
    return False


def _parse_lcf_entries(lcf_path: Path) -> Dict[str, Any]:
    if not lcf_path.is_file():
        return {"entries": [], "error": f"missing lcf: {lcf_path}"}

    raw_lines = [line.strip() for line in lcf_path.read_text(encoding="utf-8").splitlines()]
    lines = [line for line in raw_lines if line and not line.startswith("#")]
    if len(lines) % 7 != 0:
        return {
            "entries": [],
            "error": f"malformed lcf: expected groups of 7 non-comment lines, got {len(lines)}",
        }

    entries: List[Dict[str, Any]] = []
    for idx in range(0, len(lines), 7):
        try:
            layer_index = int(lines[idx])
            lateral_heat_flow = str(lines[idx + 1]).upper() == "Y"
            power_dissipating = str(lines[idx + 2]).upper() == "Y"
            volumetric_heat_capacity = float(lines[idx + 3])
            resistivity = float(lines[idx + 4])
            thickness_m = float(lines[idx + 5])
            floorplan_file = str(lines[idx + 6]).strip()
        except Exception as exc:
            return {
                "entries": entries,
                "error": f"failed to parse lcf entry at line-group {idx // 7}: {exc}",
            }
        entries.append(
            {
                "layer_index": layer_index,
                "lateral_heat_flow": lateral_heat_flow,
                "power_dissipating": power_dissipating,
                "volumetric_heat_capacity": volumetric_heat_capacity,
                "resistivity": resistivity,
                "thickness_m": thickness_m,
                "floorplan_file": floorplan_file,
            }
        )
    return {"entries": entries, "error": ""}


def _read_floorplan_block_names(path: Path) -> List[str]:
    if not path.is_file():
        return []
    names: List[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if parts:
            names.append(str(parts[0]).strip())
    return names


def _build_layer_cycle_model_map(tile_summary_rows: List[Dict[str, Any]]) -> Dict[tuple[str, int | None], bool]:
    layer_cycle_model: Dict[tuple[str, int | None], bool] = {}
    for row in tile_summary_rows:
        layer_name = str(row.get("layer_name") or "")
        try:
            layer_index = int(row.get("layer_index"))
        except Exception:
            layer_index = None
        key = (layer_name, layer_index)
        current = layer_cycle_model.get(key, False)
        layer_cycle_model[key] = current or str(row.get("cycle_model_applicable") or "") == "1"
    return layer_cycle_model


def _build_layer_stack_validation(
    *,
    lcf_path: Path,
    config_path: Path,
    thermal_cfg: Dict[str, Any],
    layers: List[Dict[str, Any]],
    tile_ids: List[int],
    include_memctrl: bool,
) -> Dict[str, Any]:
    parsed = _parse_lcf_entries(lcf_path)
    entries = list(parsed.get("entries") or [])
    parse_error = str(parsed.get("error") or "")
    expected_block_count = len(tile_ids) * 3 + (1 if include_memctrl else 0)
    results: List[Dict[str, Any]] = []

    config_entries = _parse_hotspot_config_entries(config_path)
    model_type_expected = _normalize_hotspot_model_type(thermal_cfg.get("model_type"))
    model_type_actual = str(config_entries.get("model_type") or "").strip().lower()
    model_type_matches = model_type_actual == model_type_expected
    grid_rows_expected = max(1, int(thermal_cfg.get("grid_rows", 64) or 64))
    grid_cols_expected = max(1, int(thermal_cfg.get("grid_cols", 64) or 64))
    grid_map_mode_expected = _normalize_grid_map_mode(thermal_cfg.get("grid_map_mode", "avg"))
    grid_rows_actual = int(float(config_entries.get("grid_rows", 0) or 0)) if config_entries.get("grid_rows") else 0
    grid_cols_actual = int(float(config_entries.get("grid_cols", 0) or 0)) if config_entries.get("grid_cols") else 0
    grid_map_mode_actual = str(config_entries.get("grid_map_mode") or "").strip().lower()
    grid_rows_matches = model_type_expected != "grid" or grid_rows_actual == grid_rows_expected
    grid_cols_matches = model_type_expected != "grid" or grid_cols_actual == grid_cols_expected
    grid_map_mode_matches = model_type_expected != "grid" or grid_map_mode_actual == grid_map_mode_expected

    package_config: Dict[str, Any] = {}
    config_mismatch_reasons: List[str] = []
    for key, reason in (
        ("ambient", "ambient"),
        ("s_sink", "s_sink"),
        ("t_sink", "t_sink"),
        ("s_spreader", "s_spreader"),
        ("t_spreader", "t_spreader"),
        ("t_interface", "t_interface"),
    ):
        expected_value = float(HOTSPOT_PACKAGE_DEFAULTS[key])
        raw_actual = config_entries.get(key)
        try:
            actual_value = float(raw_actual) if raw_actual is not None else None
        except Exception:
            actual_value = None
        matches = actual_value is not None and abs(actual_value - expected_value) <= max(1e-12, abs(expected_value) * 1e-9)
        field_name = "ambient_k" if key == "ambient" else key
        package_config[f"{field_name}_expected"] = expected_value
        package_config[f"{field_name}_actual"] = actual_value
        package_config[f"{field_name}_matches"] = bool(matches)
        if not matches:
            config_mismatch_reasons.append(reason)

    if not model_type_matches:
        config_mismatch_reasons.append("model_type")
    if not grid_rows_matches:
        config_mismatch_reasons.append("grid_rows")
    if not grid_cols_matches:
        config_mismatch_reasons.append("grid_cols")
    if not grid_map_mode_matches:
        config_mismatch_reasons.append("grid_map_mode")
    config_mismatch_reasons = sorted(set(config_mismatch_reasons))
    config_matches = not config_mismatch_reasons

    for idx, layer in enumerate(layers):
        entry = entries[idx] if idx < len(entries) else {}
        expected_floorplan_path = (lcf_path.parent / f"layer_{int(layer['layer_index']):02d}_{layer['safe_name']}.flp").resolve()
        actual_floorplan_path = Path(str(entry.get("floorplan_file") or expected_floorplan_path)).resolve()
        block_names = _read_floorplan_block_names(actual_floorplan_path)
        mismatch_reasons: List[str] = []

        layer_index_matches = bool(entry) and int(entry.get("layer_index", -1)) == int(layer.get("layer_index", -1))
        if not layer_index_matches:
            mismatch_reasons.append("layer_index")

        floorplan_path_matches = bool(entry) and actual_floorplan_path == expected_floorplan_path
        if not floorplan_path_matches:
            mismatch_reasons.append("floorplan_path")

        floorplan_exists = actual_floorplan_path.is_file()
        if not floorplan_exists:
            mismatch_reasons.append("floorplan_missing")

        lateral_heat_flow_matches = bool(entry) and bool(entry.get("lateral_heat_flow")) == bool(
            layer.get("lateral_heat_flow", True)
        )
        if not lateral_heat_flow_matches:
            mismatch_reasons.append("lateral_heat_flow")

        power_dissipating_matches = bool(entry) and bool(entry.get("power_dissipating")) == bool(
            layer.get("power_dissipating", False)
        )
        if not power_dissipating_matches:
            mismatch_reasons.append("power_dissipating")

        expected_thickness_m = max(1, int(layer.get("thickness_um", 1) or 1)) * 1e-6
        thickness_matches = bool(entry) and abs(float(entry.get("thickness_m", 0.0)) - expected_thickness_m) <= 1e-12
        if not thickness_matches:
            mismatch_reasons.append("thickness")

        block_count_matches = len(block_names) == expected_block_count
        if not block_count_matches:
            mismatch_reasons.append("block_count")

        expected_prefix = str(layer.get("block_prefix") or "")
        block_prefix_matches = bool(block_names) and all(name.startswith(expected_prefix) for name in block_names)
        if not block_prefix_matches:
            mismatch_reasons.append("block_prefix")

        results.append(
            {
                "layer_name": str(layer.get("name") or ""),
                "layer_index": int(layer.get("layer_index", idx) or idx),
                "kind": str(layer.get("kind") or ""),
                "z_um": int(layer.get("z_um", 0) or 0),
                "thickness_um": int(layer.get("thickness_um", 0) or 0),
                "expected_floorplan_file": str(expected_floorplan_path),
                "lcf_floorplan_file": str(actual_floorplan_path),
                "floorplan_exists": floorplan_exists,
                "floorplan_block_count": len(block_names),
                "expected_block_count": expected_block_count,
                "layer_index_matches": layer_index_matches,
                "floorplan_path_matches": floorplan_path_matches,
                "lateral_heat_flow_matches": lateral_heat_flow_matches,
                "power_dissipating_matches": power_dissipating_matches,
                "thickness_matches": thickness_matches,
                "block_prefix": expected_prefix,
                "block_prefix_matches": block_prefix_matches,
                "matches": not mismatch_reasons,
                "mismatch_reasons": mismatch_reasons,
            }
        )

    extra_entry_count = max(0, len(entries) - len(layers))
    mismatch_count = sum(1 for row in results if not row["matches"]) + extra_entry_count + (0 if config_matches else 1)
    passed = (not parse_error) and extra_entry_count == 0 and len(results) == len(layers) and mismatch_count == 0
    status = "passed" if passed else "failed"
    return {
        "status": status,
        "passed": passed,
        "parse_error": parse_error,
        "layer_count_expected": len(layers),
        "layer_count_found": len(entries),
        "layer_count_checked": len(results),
        "extra_entry_count": extra_entry_count,
        "mismatch_count": mismatch_count,
        "config_matches": config_matches,
        "config_mismatch_reasons": config_mismatch_reasons,
        "grid_config": {
            "model_type_expected": model_type_expected,
            "model_type_actual": model_type_actual,
            "model_type_matches": model_type_matches,
            "grid_rows_expected": grid_rows_expected,
            "grid_rows_actual": grid_rows_actual,
            "grid_rows_matches": grid_rows_matches,
            "grid_cols_expected": grid_cols_expected,
            "grid_cols_actual": grid_cols_actual,
            "grid_cols_matches": grid_cols_matches,
            "grid_map_mode_expected": grid_map_mode_expected,
            "grid_map_mode_actual": grid_map_mode_actual,
            "grid_map_mode_matches": grid_map_mode_matches,
        },
        "package_config": package_config,
        "layers": results,
    }


def _sanitize_layer_name(raw: Any, *, idx: int) -> str:
    name = str(raw or "").strip() or f"layer_{idx}"
    safe = re.sub(r"[^0-9A-Za-z_]+", "_", name).strip("_")
    return safe or f"layer_{idx}"


def _normalize_thermal_layers(thermal_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_layers = thermal_cfg.get("layers")
    if not isinstance(raw_layers, list):
        return []

    layers: List[Dict[str, Any]] = []
    for idx, raw_layer in enumerate(raw_layers):
        if not isinstance(raw_layer, dict):
            continue
        kind = str(raw_layer.get("kind", "") or "").strip().lower()
        if kind not in THERMAL_LAYER_KIND_DEFAULTS:
            power_dissipating = bool(raw_layer.get("power_dissipating", True))
            kind = "mesh_active" if power_dissipating else "tim"
        defaults = THERMAL_LAYER_KIND_DEFAULTS[kind]
        name = str(raw_layer.get("name", "") or "").strip() or f"layer_{idx}"
        try:
            z_um = max(0, int(raw_layer.get("z_um", idx) or idx))
        except Exception:
            z_um = idx
        try:
            thickness_um = max(1, int(raw_layer.get("thickness_um", 1) or 1))
        except Exception:
            thickness_um = 1
        power_dissipating = bool(raw_layer.get("power_dissipating", defaults["power_dissipating"]))
        power_source = _normalize_thermal_power_source(
            raw_layer.get("power_source"),
            default_type="mesh_proxy" if power_dissipating else "none",
        )
        try:
            power_scale = max(0.0, float(raw_layer.get("power_scale", defaults["power_scale"]) or 0.0))
        except Exception:
            power_scale = float(defaults["power_scale"])
        try:
            volumetric_heat_capacity = float(
                raw_layer.get("volumetric_heat_capacity", defaults["volumetric_heat_capacity"]) or 0.0
            )
        except Exception:
            volumetric_heat_capacity = float(defaults["volumetric_heat_capacity"])
        if volumetric_heat_capacity <= 0.0:
            volumetric_heat_capacity = float(defaults["volumetric_heat_capacity"])
        try:
            resistivity = float(raw_layer.get("resistivity", defaults["resistivity"]) or 0.0)
        except Exception:
            resistivity = float(defaults["resistivity"])
        if resistivity <= 0.0:
            resistivity = float(defaults["resistivity"])
        layers.append(
            {
                "name": name,
                "safe_name": _sanitize_layer_name(name, idx=idx),
                "kind": kind,
                "z_um": int(z_um),
                "thickness_um": int(thickness_um),
                "lateral_heat_flow": bool(raw_layer.get("lateral_heat_flow", defaults["lateral_heat_flow"])),
                "power_dissipating": power_dissipating,
                "volumetric_heat_capacity": float(volumetric_heat_capacity),
                "resistivity": float(resistivity),
                "power_scale": float(power_scale),
                "power_source": power_source,
                "_order": idx,
            }
        )
    layers.sort(key=lambda item: (int(item["z_um"]), int(item["_order"])))
    for idx, layer in enumerate(layers):
        layer["layer_index"] = idx
        layer["block_prefix"] = f"L{idx:02d}_{layer['safe_name']}__"
        layer.pop("_order", None)
    return layers


def _row_value(row: Dict[str, str]) -> float:
    for key in ("Sum.u64", "Sum.i64", "Sum.f64", "Sum"):
        raw = str(row.get(key) or "").strip()
        if raw:
            try:
                return float(raw)
            except Exception:
                continue
    return 0.0


def _aggregate_tile_metrics(tile_ids: List[int], stats_rows: List[Dict[str, str]]) -> Dict[int, Dict[str, float]]:
    metrics: Dict[int, Dict[str, float]] = {
        tile_id: {
            "sram_energy_pj": 0.0,
            "noc_packets": 0.0,
            "noc_bytes": 0.0,
            "noc_hops": 0.0,
            "comp_spikes": 0.0,
            "sim_cycles_total": 0.0,
            "compute_active_cycles_total": 0.0,
            "has_sim_cycles_total": 0.0,
            "has_compute_active_cycles_total": 0.0,
        }
        for tile_id in tile_ids
    }

    for row in stats_rows:
        comp_name = str(row.get("ComponentName") or "")
        stat_name = str(row.get("StatisticName") or "")
        match = PE_COMPONENT_RE.search(comp_name)
        if not match:
            continue
        tile_id = int(match.group(1))
        tile_metrics = metrics.setdefault(
            tile_id,
            {
                "sram_energy_pj": 0.0,
                "noc_packets": 0.0,
                "noc_bytes": 0.0,
                "noc_hops": 0.0,
                "comp_spikes": 0.0,
                "sim_cycles_total": 0.0,
                "compute_active_cycles_total": 0.0,
                "has_sim_cycles_total": 0.0,
                "has_compute_active_cycles_total": 0.0,
            },
        )
        value = _row_value(row)
        is_pe_root = comp_name == f"multicore_pe_{tile_id}"

        if "sram_energy_" in stat_name:
            tile_metrics["sram_energy_pj"] += value
        elif stat_name == "sim_cycles_total" and is_pe_root:
            tile_metrics["sim_cycles_total"] += value
            tile_metrics["has_sim_cycles_total"] = 1.0
        elif stat_name == "compute_active_cycles_total" and is_pe_root:
            tile_metrics["compute_active_cycles_total"] += value
            tile_metrics["has_compute_active_cycles_total"] = 1.0
        elif stat_name in ("packets_sent", "packets_received"):
            tile_metrics["noc_packets"] += value
        elif stat_name in ("payload_bytes_sent", "payload_bytes_received", "total_bytes_sent", "total_bytes_received"):
            tile_metrics["noc_bytes"] += value
        elif stat_name == "hop_count_sum":
            tile_metrics["noc_hops"] += value
        elif stat_name in ("spikes_sent", "spikes_received", "neurons_fired_total"):
            tile_metrics["comp_spikes"] += value

    return metrics


def _matches_any_prefix(value: str, prefixes: List[str]) -> bool:
    if not prefixes:
        return True
    return any(value.startswith(prefix) for prefix in prefixes)


def _filter_stats_rows_for_power_source(
    stats_rows: List[Dict[str, str]],
    power_source: Dict[str, Any],
) -> List[Dict[str, str]]:
    source_type = str((power_source or {}).get("type") or "mesh_proxy").strip().lower()
    if source_type == "none":
        return []
    if source_type != "stats_prefix":
        return stats_rows

    component_prefixes = list((power_source or {}).get("component_prefixes") or [])
    statistic_prefixes = list((power_source or {}).get("statistic_prefixes") or [])
    if not component_prefixes and not statistic_prefixes:
        return stats_rows

    filtered: List[Dict[str, str]] = []
    for row in stats_rows:
        comp_name = str(row.get("ComponentName") or "")
        stat_name = str(row.get("StatisticName") or "")
        if not _matches_any_prefix(comp_name, component_prefixes):
            continue
        if not _matches_any_prefix(stat_name, statistic_prefixes):
            continue
        filtered.append(row)
    return filtered


def _duration_seconds(effective_cfg: Dict[str, Any], thermal_cfg: Dict[str, Any]) -> float:
    candidates = [
        effective_cfg.get("sim_time_actual_ns"),
        effective_cfg.get("sim_stop_ns"),
        thermal_cfg.get("window_ns"),
    ]
    for value in candidates:
        try:
            ns = float(value)
        except Exception:
            ns = 0.0
        if ns > 0.0:
            return ns * 1e-9
    return 1e-6


def _resolve_support_path(run_dir: Path, raw_path: str) -> Path:
    path = Path(str(raw_path or "").strip())
    if not str(path):
        raise ValueError("power source path must be non-empty")
    if path.is_absolute():
        return path
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        run_dir / path,
        repo_root / path,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _load_tile_block_powers_from_csv(
    *,
    run_dir: Path,
    csv_path_raw: str,
    tile_ids: List[int],
) -> Dict[int, Dict[str, float]]:
    csv_path = _resolve_support_path(run_dir, csv_path_raw)
    if not csv_path.is_file():
        raise ValueError(f"csv power source not found: {csv_path}")
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    powers: Dict[int, Dict[str, float]] = {
        int(tile_id): {
            "comp_power_w": 0.0,
            "sram_power_w": 0.0,
            "noc_power_w": 0.0,
        }
        for tile_id in tile_ids
    }
    for row in rows:
        raw_tile_id = str(row.get("tile_id") or "").strip()
        if not raw_tile_id:
            continue
        try:
            tile_id = int(raw_tile_id)
        except Exception:
            continue
        if tile_id not in powers:
            continue
        for src_key, dst_key in (
            ("comp_power_w", "comp_power_w"),
            ("sram_power_w", "sram_power_w"),
            ("noc_power_w", "noc_power_w"),
        ):
            raw_value = str(row.get(src_key) or "").strip()
            if not raw_value:
                continue
            try:
                powers[tile_id][dst_key] = float(raw_value)
            except Exception:
                continue
    return powers


def _window_metric_paths(run_dir: Path) -> List[Path]:
    paths = sorted(run_dir.glob("pe*/core*_window_metrics.csv"))
    if paths:
        return paths
    return sorted(run_dir.glob("pe*/window_metrics.csv"))


def _path_tile_id(path: Path) -> int | None:
    match = re.search(r"pe(\d+)", str(path.parent.name))
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _window_metric_score(metrics: Dict[str, float]) -> float:
    payload_bytes = max(0.0, float(metrics.get("payload_bytes", 0.0) or 0.0))
    if payload_bytes > 0.0:
        return payload_bytes
    bursts = max(0.0, float(metrics.get("bursts", 0.0) or 0.0))
    if bursts > 0.0:
        return bursts * 64.0
    inflight_peak = max(0.0, float(metrics.get("inflight_peak", 0.0) or 0.0))
    if inflight_peak > 0.0:
        return inflight_peak * 64.0
    return max(0.0, float(metrics.get("buffer_max_bytes", 0.0) or 0.0))


def _load_window_trace(run_dir: Path, tile_ids: List[int]) -> Dict[str, Any]:
    paths = _window_metric_paths(run_dir)
    if not paths:
        return {
            "window_ids": [],
            "tile_window_metrics": {},
            "tile_window_scales": {},
        }

    tile_window_metrics: Dict[int, Dict[int, Dict[str, float]]] = {}
    window_ids: set[int] = set()
    for path in paths:
        tile_id = _path_tile_id(path)
        if tile_id is None:
            continue
        with path.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            raw_window_id = str(row.get("window_id") or "").strip()
            if not raw_window_id:
                continue
            try:
                window_id = int(raw_window_id)
            except Exception:
                continue
            if window_id < 0:
                continue
            metrics = tile_window_metrics.setdefault(tile_id, {}).setdefault(
                window_id,
                {
                    "payload_bytes": 0.0,
                    "bursts": 0.0,
                    "inflight_peak": 0.0,
                    "buffer_max_bytes": 0.0,
                },
            )
            for field in ("payload_bytes", "bursts"):
                raw_value = str(row.get(field) or "").strip()
                if not raw_value:
                    continue
                try:
                    metrics[field] += max(0.0, float(raw_value))
                except Exception:
                    continue
            for field in ("inflight_peak", "buffer_max_bytes"):
                raw_value = str(row.get(field) or "").strip()
                if not raw_value:
                    continue
                try:
                    metrics[field] = max(metrics[field], max(0.0, float(raw_value)))
                except Exception:
                    continue
            window_ids.add(window_id)

    sorted_window_ids = sorted(window_ids)
    if not sorted_window_ids:
        return {
            "window_ids": [],
            "tile_window_metrics": tile_window_metrics,
            "tile_window_scales": {},
        }

    tile_window_scales: Dict[int, Dict[int, float]] = {}
    for tile_id in tile_ids:
        raw_scores = [
            _window_metric_score((tile_window_metrics.get(tile_id) or {}).get(window_id) or {})
            for window_id in sorted_window_ids
        ]
        mean_score = sum(raw_scores) / float(len(sorted_window_ids)) if sorted_window_ids else 0.0
        if mean_score > 0.0:
            tile_window_scales[tile_id] = {
                window_id: raw_score / mean_score
                for window_id, raw_score in zip(sorted_window_ids, raw_scores)
            }
        else:
            tile_window_scales[tile_id] = {
                window_id: 1.0
                for window_id in sorted_window_ids
            }

    return {
        "window_ids": sorted_window_ids,
        "tile_window_metrics": tile_window_metrics,
        "tile_window_scales": tile_window_scales,
    }


def _build_windowed_ptrace_rows(
    *,
    ptrace_header: List[str],
    average_row: List[str],
    tile_summary_rows: List[Dict[str, Any]],
    window_trace: Dict[str, Any],
    block_trace_modes: Dict[str, str],
) -> List[List[str]]:
    window_ids = list(window_trace.get("window_ids") or [])
    if not window_ids:
        return [list(average_row)]

    average_power_map = {
        block_name: float(raw_power)
        for block_name, raw_power in zip(ptrace_header, average_row)
    }
    block_tile_map: Dict[str, int] = {}
    for row in tile_summary_rows:
        block_name = str(row.get("block_name") or "")
        if block_name not in average_power_map:
            continue
        try:
            block_tile_map[block_name] = int(row.get("tile_id"))
        except Exception:
            continue

    tile_window_scales = dict(window_trace.get("tile_window_scales") or {})
    rows: List[List[str]] = []
    for window_id in window_ids:
        row_values: List[str] = []
        for block_name in ptrace_header:
            power_w = float(average_power_map.get(block_name, 0.0) or 0.0)
            if block_trace_modes.get(block_name) == "window_metrics":
                tile_id = block_tile_map.get(block_name)
                scale = 1.0
                if tile_id is not None:
                    scale = float((tile_window_scales.get(tile_id) or {}).get(window_id, 1.0) or 1.0)
                power_w *= scale
            row_values.append(f"{power_w:.6e}")
        rows.append(row_values)
    return rows


def _build_window_power_samples(
    *,
    ptrace_header: List[str],
    ptrace_rows: List[List[str]],
    tile_summary_rows: List[Dict[str, Any]],
    window_trace: Dict[str, Any],
    trace_mode: str,
    window_ns: int,
) -> List[Dict[str, Any]]:
    block_meta_map: Dict[str, Dict[str, Any]] = {}
    total_cycles = 0
    has_total_cycles = False
    for row in tile_summary_rows:
        block_name = str(row.get("block_name") or "")
        if not block_name:
            continue
        layer_index_raw = row.get("layer_index")
        try:
            layer_index = int(layer_index_raw) if layer_index_raw not in ("", None) else None
        except Exception:
            layer_index = None
        block_meta_map[block_name] = {
            "layer_name": str(row.get("layer_name") or ""),
            "layer_index": layer_index,
            "block_type": str(row.get("block_type") or ""),
            "trace_source": str(row.get("trace_source") or ""),
            "window_scaling_mode": str(row.get("window_scaling_mode") or ""),
            "cycle_model_applicable": str(row.get("cycle_model_applicable") or "").strip() == "1",
        }
        try:
            sim_cycles_total = int(float(str(row.get("sim_cycles_total") or "").strip()))
        except Exception:
            sim_cycles_total = 0
        if sim_cycles_total > total_cycles:
            total_cycles = sim_cycles_total
            has_total_cycles = True

    sample_count = len(ptrace_rows)
    if sample_count <= 0:
        return []

    raw_window_ids = list(window_trace.get("window_ids") or [])
    sample_ids = raw_window_ids if len(raw_window_ids) == sample_count else list(range(1, sample_count + 1))

    out: List[Dict[str, Any]] = []
    for idx, (sample_id, row_values) in enumerate(zip(sample_ids, ptrace_rows), start=1):
        if has_total_cycles and total_cycles > 0:
            start_cycle = int(((idx - 1) * total_cycles) / sample_count)
            next_start_cycle = int((idx * total_cycles) / sample_count)
            end_cycle = max(start_cycle, next_start_cycle - 1)
        else:
            start_cycle = idx - 1
            end_cycle = idx - 1

        blocks: List[Dict[str, Any]] = []
        for block_name, raw_power in zip(ptrace_header, row_values):
            meta = block_meta_map.get(block_name) or {}
            try:
                power_w = float(raw_power)
            except Exception:
                power_w = 0.0
            blocks.append(
                {
                    "block_name": block_name,
                    "layer_name": str(meta.get("layer_name") or ""),
                    "layer_index": meta.get("layer_index"),
                    "block_type": str(meta.get("block_type") or ""),
                    "power_w": power_w,
                    "trace_source": str(meta.get("trace_source") or ""),
                    "window_scaling_mode": str(meta.get("window_scaling_mode") or ""),
                    "cycle_model_applicable": bool(meta.get("cycle_model_applicable")),
                }
            )
        out.append(
            {
                "sample_id": int(sample_id),
                "start_cycle": start_cycle,
                "end_cycle": end_cycle,
                "duration_ns": int(window_ns),
                "trace_mode": trace_mode,
                "blocks": blocks,
            }
        )
    return out


def _build_floorplan_lines(
    tile_ids: List[int],
    thermal_cfg: Dict[str, Any],
    mesh_size: int,
    *,
    block_prefix: str = "",
    include_memctrl: bool = False,
) -> List[str]:
    tile_width_m = max(1, int(thermal_cfg.get("tile_width_um", 1000) or 1000)) * 1e-6
    tile_height_m = max(1, int(thermal_cfg.get("tile_height_um", 1000) or 1000)) * 1e-6
    tile_gap_m = max(0, int(thermal_cfg.get("tile_gap_um", 50) or 0)) * 1e-6
    frac = _normalize_fractions(thermal_cfg)
    comp_width = tile_width_m * frac["comp"]
    sram_width = tile_width_m * frac["sram"]
    noc_width = tile_width_m * frac["noc"]
    width = _tile_name_width(len(tile_ids))

    lines: List[str] = []
    for tile_id in tile_ids:
        row = tile_id // mesh_size
        col = tile_id % mesh_size
        x0 = col * (tile_width_m + tile_gap_m)
        y0 = row * (tile_height_m + tile_gap_m)
        base = f"{block_prefix}tile_{tile_id:0{width}d}"
        lines.append(f"{base}_comp\t{comp_width:.9e}\t{tile_height_m:.9e}\t{x0:.9e}\t{y0:.9e}")
        lines.append(f"{base}_sram\t{sram_width:.9e}\t{tile_height_m:.9e}\t{x0 + comp_width:.9e}\t{y0:.9e}")
        lines.append(f"{base}_noc\t{noc_width:.9e}\t{tile_height_m:.9e}\t{x0 + comp_width + sram_width:.9e}\t{y0:.9e}")
    if include_memctrl:
        rows_used = max(1, max((tile_id // mesh_size) for tile_id in tile_ids) + 1) if tile_ids else 1
        total_width = mesh_size * tile_width_m + max(0, mesh_size - 1) * tile_gap_m
        total_height = rows_used * tile_height_m + max(0, rows_used - 1) * tile_gap_m
        memctrl_width = max(tile_width_m * 0.15, MEMCTRL_MIN_WIDTH_UM * 1e-6)
        lines.append(
            f"{block_prefix}mesh_memctrl_east\t{memctrl_width:.9e}\t{total_height:.9e}\t{total_width + tile_gap_m:.9e}\t0.000000000e+00"
        )
    return lines


def _estimate_memctrl_power_w(
    *,
    tile_metrics: Dict[int, Dict[str, float]],
    duration_s: float,
    power_scale: float,
    direct_tile_powers: Dict[int, Dict[str, float]] | None = None,
) -> float:
    if duration_s <= 0.0:
        return 0.0
    if direct_tile_powers is not None:
        total_direct_power = 0.0
        for powers in direct_tile_powers.values():
            total_direct_power += max(0.0, float(powers.get("comp_power_w", 0.0) or 0.0))
            total_direct_power += max(0.0, float(powers.get("sram_power_w", 0.0) or 0.0))
            total_direct_power += max(0.0, float(powers.get("noc_power_w", 0.0) or 0.0))
        return total_direct_power * MEMCTRL_DIRECT_POWER_RATIO * max(0.0, power_scale)

    total_sram_energy_pj = 0.0
    total_noc_packets = 0.0
    total_noc_bytes = 0.0
    for metrics in tile_metrics.values():
        total_sram_energy_pj += max(0.0, float(metrics.get("sram_energy_pj", 0.0) or 0.0))
        total_noc_packets += max(0.0, float(metrics.get("noc_packets", 0.0) or 0.0))
        total_noc_bytes += max(0.0, float(metrics.get("noc_bytes", 0.0) or 0.0))
    memctrl_energy_pj = (
        MEMCTRL_ENERGY_FROM_SRAM_RATIO * total_sram_energy_pj
        + MEMCTRL_ENERGY_PJ_PER_PACKET * total_noc_packets
        + MEMCTRL_ENERGY_PJ_PER_BYTE * total_noc_bytes
    )
    return memctrl_energy_pj * 1e-12 / duration_s * max(0.0, power_scale)


def _build_power_trace(
    tile_ids: List[int],
    thermal_cfg: Dict[str, Any],
    tile_metrics: Dict[int, Dict[str, float]],
    duration_s: float,
    *,
    block_prefix: str = "",
    power_scale: float = 1.0,
    power_enabled: bool = True,
    emit_trace: bool = True,
    layer_name: str = "",
    layer_index: int | None = None,
    layer_z_um: int | None = None,
    power_source_type: str = "mesh_proxy",
    direct_tile_powers: Dict[int, Dict[str, float]] | None = None,
    include_memctrl: bool = False,
) -> tuple[List[str], List[str], List[Dict[str, Any]]]:
    width = _tile_name_width(len(tile_ids))
    header: List[str] = []
    row: List[str] = []
    summary_rows: List[Dict[str, Any]] = []

    for tile_id in tile_ids:
        base = f"tile_{tile_id:0{width}d}"
        metrics = tile_metrics.get(tile_id, {})
        sram_energy_pj = float(metrics.get("sram_energy_pj", 0.0) or 0.0)
        sim_cycles_total = max(0.0, float(metrics.get("sim_cycles_total", 0.0) or 0.0))
        compute_active_cycles_total = max(0.0, float(metrics.get("compute_active_cycles_total", 0.0) or 0.0))
        has_cycle_model = bool(metrics.get("has_sim_cycles_total", 0.0)) and bool(
            metrics.get("has_compute_active_cycles_total", 0.0)
        )
        noc_energy_pj = (
            NOC_ENERGY_PJ_PER_PACKET * float(metrics.get("noc_packets", 0.0) or 0.0)
            + NOC_ENERGY_PJ_PER_BYTE * float(metrics.get("noc_bytes", 0.0) or 0.0)
            + NOC_ENERGY_PJ_PER_HOP * float(metrics.get("noc_hops", 0.0) or 0.0)
        )
        comp_activity_fraction = 0.0
        comp_model_source = "proxy_fallback"
        if not power_enabled:
            comp_energy_pj = 0.0
            sram_energy_pj = 0.0
            noc_energy_pj = 0.0
            comp_model_source = ""
            comp_power_w = 0.0
            sram_power_w = 0.0
            noc_power_w = 0.0
        elif direct_tile_powers is not None:
            direct = dict(direct_tile_powers.get(tile_id) or {})
            comp_power_w = max(0.0, float(direct.get("comp_power_w", 0.0) or 0.0)) * power_scale
            sram_power_w = max(0.0, float(direct.get("sram_power_w", 0.0) or 0.0)) * power_scale
            noc_power_w = max(0.0, float(direct.get("noc_power_w", 0.0) or 0.0)) * power_scale
            has_cycle_model = False
            sim_cycles_total = 0.0
            compute_active_cycles_total = 0.0
            comp_model_source = "csv"
        elif has_cycle_model and sim_cycles_total > 0.0:
            compute_active_cycles_total = min(compute_active_cycles_total, sim_cycles_total)
            comp_activity_fraction = compute_active_cycles_total / sim_cycles_total
            comp_model_source = "compute_active_cycles_total"
            comp_energy_pj = (
                COMP_IDLE_ENERGY_PJ_PER_CYCLE * sim_cycles_total
                + COMP_ACTIVE_ENERGY_PJ_PER_CYCLE * compute_active_cycles_total
                + COMP_ENERGY_PJ_PER_SPIKE * float(metrics.get("comp_spikes", 0.0) or 0.0)
                + COMP_ENERGY_FROM_SRAM_RATIO * sram_energy_pj
                + COMP_ENERGY_FROM_NOC_RATIO * noc_energy_pj
            )
            comp_power_w = comp_energy_pj * 1e-12 / duration_s * power_scale
            sram_power_w = sram_energy_pj * 1e-12 / duration_s * power_scale
            noc_power_w = noc_energy_pj * 1e-12 / duration_s * power_scale
        else:
            comp_energy_pj = (
                COMP_BASE_ENERGY_PJ
                + COMP_ENERGY_PJ_PER_SPIKE * float(metrics.get("comp_spikes", 0.0) or 0.0)
                + COMP_ENERGY_FROM_SRAM_RATIO * sram_energy_pj
                + COMP_ENERGY_FROM_NOC_RATIO * noc_energy_pj
            )
            comp_power_w = comp_energy_pj * 1e-12 / duration_s * power_scale
            sram_power_w = sram_energy_pj * 1e-12 / duration_s * power_scale
            noc_power_w = noc_energy_pj * 1e-12 / duration_s * power_scale

        block_powers = {
            f"{block_prefix}{base}_comp": comp_power_w,
            f"{block_prefix}{base}_sram": sram_power_w,
            f"{block_prefix}{base}_noc": noc_power_w,
        }
        comp_cycle_model_used = power_enabled and comp_model_source == "compute_active_cycles_total"
        for block_name, power_w in block_powers.items():
            if emit_trace:
                header.append(block_name)
                row.append(f"{power_w:.6e}")
            summary_rows.append(
                {
                    "layer_name": layer_name,
                    "layer_index": "" if layer_index is None else int(layer_index),
                    "layer_z_um": "" if layer_z_um is None else int(layer_z_um),
                    "power_scale": f"{power_scale:.6f}" if power_enabled else "0.000000",
                    "power_source_type": power_source_type,
                    "tile_id": tile_id,
                    "block_name": block_name,
                    "block_type": block_name.rsplit("_", 1)[-1],
                    "average_power_w": f"{power_w:.6e}",
                    "cycle_model_applicable": ("1" if block_name.endswith("_comp") and comp_cycle_model_used else "0"),
                    "model_source": comp_model_source if block_name.endswith("_comp") and power_enabled else "",
                    "sim_cycles_total": (
                        f"{sim_cycles_total:.0f}" if block_name.endswith("_comp") and has_cycle_model and power_enabled else ""
                    ),
                    "compute_active_cycles_total": (
                        f"{compute_active_cycles_total:.0f}"
                        if block_name.endswith("_comp") and has_cycle_model and power_enabled
                        else ""
                    ),
                    "activity_fraction": (
                        f"{comp_activity_fraction:.6f}"
                        if block_name.endswith("_comp") and has_cycle_model and power_enabled
                        else ""
                    ),
                    "trace_mode": "",
                    "trace_source": "",
                    "window_scaling_mode": "",
                    "temperature_c": "",
                }
            )

    if include_memctrl:
        memctrl_block_name = f"{block_prefix}mesh_memctrl_east"
        memctrl_power_w = 0.0
        if power_enabled:
            memctrl_power_w = _estimate_memctrl_power_w(
                tile_metrics=tile_metrics,
                duration_s=duration_s,
                power_scale=power_scale,
                direct_tile_powers=direct_tile_powers,
            )
        if emit_trace:
            header.append(memctrl_block_name)
            row.append(f"{memctrl_power_w:.6e}")
        summary_rows.append(
            {
                "layer_name": layer_name,
                "layer_index": "" if layer_index is None else int(layer_index),
                "layer_z_um": "" if layer_z_um is None else int(layer_z_um),
                "power_scale": f"{power_scale:.6f}" if power_enabled else "0.000000",
                "power_source_type": power_source_type,
                "tile_id": "",
                "block_name": memctrl_block_name,
                "block_type": "memctrl",
                "average_power_w": f"{memctrl_power_w:.6e}",
                "cycle_model_applicable": "0",
                "model_source": "memctrl_proxy" if power_enabled else "",
                "sim_cycles_total": "",
                "compute_active_cycles_total": "",
                "activity_fraction": "",
                "trace_mode": "",
                "trace_source": "",
                "window_scaling_mode": "",
                "temperature_c": "",
            }
        )

    return header, row, summary_rows


def _annotate_trace_provenance(
    *,
    tile_summary_rows: List[Dict[str, Any]],
    block_trace_modes: Dict[str, str],
    has_window_trace: bool,
) -> Dict[str, Any]:
    scaled_block_count = 0
    constant_block_count = 0
    constant_trace_sources: set[str] = set()

    for row in tile_summary_rows:
        block_name = str(row.get("block_name") or "")
        block_mode = str(block_trace_modes.get(block_name) or "constant")
        block_type = str(row.get("block_type") or "")
        power_source_type = str(row.get("power_source_type") or "")

        if block_type == "memctrl":
            trace_mode = "constant" if has_window_trace else "average"
            trace_source = "memctrl_proxy"
            window_scaling_mode = "constant" if has_window_trace else "single_average_row"
        elif block_mode == "window_metrics":
            trace_mode = "windowed" if has_window_trace else "average"
            trace_source = "window_metrics" if has_window_trace else "average_power"
            window_scaling_mode = "per_tile_mean_normalized_metric" if has_window_trace else "single_average_row"
        elif power_source_type == "csv":
            trace_mode = "constant" if has_window_trace else "average"
            trace_source = "csv_constant" if has_window_trace else "csv_average"
            window_scaling_mode = "constant" if has_window_trace else "single_average_row"
        elif power_source_type == "none":
            trace_mode = "constant" if has_window_trace else "average"
            trace_source = "disabled"
            window_scaling_mode = "constant" if has_window_trace else "single_average_row"
        else:
            trace_mode = "average"
            trace_source = "average_power"
            window_scaling_mode = "single_average_row"

        row["trace_mode"] = trace_mode
        row["trace_source"] = trace_source
        row["window_scaling_mode"] = window_scaling_mode

        if trace_source == "window_metrics":
            scaled_block_count += 1
        else:
            constant_block_count += 1
            constant_trace_sources.add(trace_source)

    return {
        "scaling_mode": "per_tile_mean_normalized_metric" if has_window_trace else "single_average_row",
        "metric_priority": ["payload_bytes", "bursts", "inflight_peak", "buffer_max_bytes"] if has_window_trace else [],
        "scaled_block_count": scaled_block_count,
        "constant_block_count": constant_block_count,
        "constant_trace_sources": sorted(constant_trace_sources),
    }


def _build_layer_trace_meta_map(tile_summary_rows: List[Dict[str, Any]]) -> Dict[tuple[str, int | None], Dict[str, Any]]:
    out: Dict[tuple[str, int | None], Dict[str, Any]] = {}
    for row in tile_summary_rows:
        layer_name = str(row.get("layer_name") or "")
        layer_index_raw = row.get("layer_index")
        try:
            layer_index = int(layer_index_raw) if layer_index_raw not in ("", None) else None
        except Exception:
            layer_index = None
        key = (layer_name, layer_index)
        meta = out.setdefault(
            key,
            {
                "trace_modes": set(),
                "trace_sources": set(),
                "window_scaling_modes": set(),
                "memctrl_block_count": 0,
            },
        )
        trace_mode = str(row.get("trace_mode") or "").strip()
        if trace_mode:
            meta["trace_modes"].add(trace_mode)
        trace_source = str(row.get("trace_source") or "").strip()
        if trace_source:
            meta["trace_sources"].add(trace_source)
        scaling_mode = str(row.get("window_scaling_mode") or "").strip()
        if scaling_mode:
            meta["window_scaling_modes"].add(scaling_mode)
        if str(row.get("block_type") or "") == "memctrl":
            meta["memctrl_block_count"] = int(meta["memctrl_block_count"]) + 1
    return out


def _build_hotspot_config(
    *,
    model_type: str = "block",
    grid_rows: int = 64,
    grid_cols: int = 64,
    grid_map_mode: str = "avg",
    detailed_3d: bool = False,
) -> str:
    lines = [
        "# Auto-generated HotSpot config for SnnDL Thermal V1",
        f"-model_type\t\t\t{model_type}",
        f"-grid_rows\t\t\t{max(1, int(grid_rows))}",
        f"-grid_cols\t\t\t{max(1, int(grid_cols))}",
        f"-ambient\t\t\t{HOTSPOT_PACKAGE_DEFAULTS['ambient']}",
        f"-s_sink\t\t\t{HOTSPOT_PACKAGE_DEFAULTS['s_sink']}",
        f"-t_sink\t\t\t{HOTSPOT_PACKAGE_DEFAULTS['t_sink']}",
        f"-s_spreader\t\t\t{HOTSPOT_PACKAGE_DEFAULTS['s_spreader']}",
        f"-t_spreader\t\t\t{HOTSPOT_PACKAGE_DEFAULTS['t_spreader']}",
        f"-t_interface\t\t{HOTSPOT_PACKAGE_DEFAULTS['t_interface']}",
    ]
    if model_type == "grid":
        lines.append(f"-grid_map_mode\t\t{_normalize_grid_map_mode(grid_map_mode)}")
        lines.append(f"-detailed_3D\t\t{'on' if detailed_3d else 'off'}")
    lines.append("")
    return "\n".join(lines)


def _resolve_hotspot_bin(cli_value: str, thermal_cfg: Dict[str, Any]) -> str:
    candidates = [
        str(cli_value or "").strip(),
        str(thermal_cfg.get("hotspot_bin", "") or "").strip(),
        shutil.which("hotspot") or "",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        resolved = shutil.which(candidate) or candidate
        if Path(resolved).exists():
            return resolved
    return ""


def _write_lcf_and_layer_floorplans(
    *,
    tile_ids: List[int],
    thermal_cfg: Dict[str, Any],
    mesh_size: int,
    hotspot_dir: Path,
    layers: List[Dict[str, Any]],
    include_memctrl: bool,
) -> tuple[Path, List[str]]:
    lcf_lines: List[str] = [
        "# Auto-generated LCF for SnnDL Thermal V1",
        "# layer_index",
        "# lateral_heat_flow",
        "# power_dissipating",
        "# volumetric_heat_capacity",
        "# resistivity",
        "# thickness_m",
        "# floorplan_file",
        "",
    ]
    floorplan_paths: List[str] = []
    for layer in layers:
        flp_path = hotspot_dir / f"layer_{int(layer['layer_index']):02d}_{layer['safe_name']}.flp"
        flp_path.write_text(
            "\n".join(
                _build_floorplan_lines(
                    tile_ids,
                    thermal_cfg,
                    mesh_size,
                    block_prefix=str(layer.get("block_prefix") or ""),
                    include_memctrl=include_memctrl,
                )
            )
            + "\n",
            encoding="utf-8",
        )
        floorplan_paths.append(str(flp_path))
        lcf_lines.extend(
            [
                f"# Layer {int(layer['layer_index'])}: {layer['name']}",
                str(int(layer["layer_index"])),
                "Y" if bool(layer.get("lateral_heat_flow", True)) else "N",
                "Y" if bool(layer.get("power_dissipating", False)) else "N",
                f"{float(layer.get('volumetric_heat_capacity', 1.75e6)):.6e}",
                f"{float(layer.get('resistivity', 0.01)):.6e}",
                f"{max(1, int(layer.get('thickness_um', 1))) * 1e-6:.9e}",
                str(flp_path),
                "",
            ]
        )
    lcf_path = hotspot_dir / "snndl_mesh.lcf"
    lcf_path.write_text("\n".join(lcf_lines), encoding="utf-8")
    return lcf_path, floorplan_paths


def _run_hotspot(
    hotspot_bin: str,
    flp_path: Path,
    ptrace_path: Path,
    config_path: Path,
    hotspot_dir: Path,
    *,
    model_type: str = "block",
    lcf_path: Path | None = None,
    detailed_3d: bool = False,
) -> Dict[str, Any]:
    if not hotspot_bin:
        return {"status": "skipped_missing_binary", "binary": ""}

    steady_path = hotspot_dir / "steady.temp"
    transient_path = hotspot_dir / "transient.temp"
    cmd = [
        hotspot_bin,
        "-p",
        str(ptrace_path),
        "-c",
        str(config_path),
        "-steady_file",
        str(steady_path),
        "-o",
        str(transient_path),
    ]
    normalized_model_type = _normalize_hotspot_model_type(model_type)
    if normalized_model_type == "grid":
        if lcf_path is None:
            return {
                "status": "failed_missing_lcf",
                "binary": hotspot_bin,
            }
        cmd.extend(["-grid_layer_file", str(lcf_path)])
        if detailed_3d:
            cmd.extend(["-detailed_3D", "on"])
        grid_steady_path = hotspot_dir / "grid.steady"
        grid_transient_path = hotspot_dir / "grid.transient"
        cmd.extend(
            [
                "-grid_steady_file",
                str(grid_steady_path),
                "-grid_transient_file",
                str(grid_transient_path),
            ]
        )
    else:
        cmd.extend(["-f", str(flp_path)])
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    except Exception as exc:
        return {
            "status": "failed_to_launch",
            "binary": hotspot_bin,
            "error": str(exc),
        }
    result = {
        "status": "ran" if proc.returncode == 0 else "failed",
        "binary": hotspot_bin,
        "returncode": int(proc.returncode),
    }
    if proc.stdout.strip():
        result["stdout"] = proc.stdout.strip()
    if proc.stderr.strip():
        result["stderr"] = proc.stderr.strip()
    return result


def export_thermal(*, run_dir: Path, hotspot_bin_override: str = "") -> Dict[str, Any]:
    effective_cfg_path = run_dir / "effective_config.json"
    effective_cfg = _load_json(effective_cfg_path)
    thermal_cfg = dict(effective_cfg.get("thermal", {}) or {})
    if int(thermal_cfg.get("enable", 0) or 0) == 0:
        raise ValueError("thermal export requested but effective_config.json thermal.enable != 1")

    backend = str(thermal_cfg.get("backend", "hotspot") or "hotspot").strip().lower()
    if backend != "hotspot":
        raise ValueError(f"unsupported thermal backend: {backend}")

    stats_rows = _load_stats_rows(run_dir / "mesh_stats.csv")
    tile_ids = _infer_tile_ids(effective_cfg, stats_rows)
    mesh_size = _infer_mesh_size(len(tile_ids))
    duration_s = _duration_seconds(effective_cfg, thermal_cfg)
    tile_metrics = _aggregate_tile_metrics(tile_ids, stats_rows)
    window_trace = _load_window_trace(run_dir, tile_ids)

    thermal_dir = _resolve_out_dir(run_dir, str(thermal_cfg.get("out_dir", "thermal") or "thermal"))
    hotspot_dir = thermal_dir / "hotspot"
    summary_dir = thermal_dir / "summary"
    hotspot_dir.mkdir(parents=True, exist_ok=True)
    summary_dir.mkdir(parents=True, exist_ok=True)

    effective_thermal_cfg = dict(thermal_cfg)
    effective_thermal_cfg["tile_count"] = len(tile_ids)
    effective_thermal_cfg["mesh_size"] = mesh_size
    _write_json(thermal_dir / "effective_thermal_config.json", effective_thermal_cfg)

    hotspot_model_type = _normalize_hotspot_model_type(thermal_cfg.get("model_type"))
    grid_rows = max(1, int(thermal_cfg.get("grid_rows", 64) or 64))
    grid_cols = max(1, int(thermal_cfg.get("grid_cols", 64) or 64))
    grid_map_mode = _normalize_grid_map_mode(thermal_cfg.get("grid_map_mode", "avg"))
    layers = _normalize_thermal_layers(thermal_cfg)
    detailed_3d = bool(int(thermal_cfg.get("detailed_3d", 1 if layers else 0) or 0))
    include_memctrl = bool(int(thermal_cfg.get("include_memctrl", 0) or 0))

    flp_path = hotspot_dir / "snndl_mesh.flp"
    lcf_path: Path | None = None
    layer_floorplans: List[str] = []
    ptrace_header: List[str]
    ptrace_average_row: List[str]
    tile_summary_rows: List[Dict[str, Any]]
    block_trace_modes: Dict[str, str] = {}
    if hotspot_model_type == "grid" and layers:
        lcf_path, layer_floorplans = _write_lcf_and_layer_floorplans(
            tile_ids=tile_ids,
            thermal_cfg=thermal_cfg,
            mesh_size=mesh_size,
            hotspot_dir=hotspot_dir,
            layers=layers,
            include_memctrl=include_memctrl,
        )
        ptrace_header = []
        ptrace_average_row = []
        tile_summary_rows = []
        for layer in layers:
            layer_power_source = dict(layer.get("power_source") or {})
            layer_power_source_type = str(layer_power_source.get("type") or "mesh_proxy").strip().lower()
            layer_stats_rows = _filter_stats_rows_for_power_source(stats_rows, layer_power_source)
            layer_tile_metrics = _aggregate_tile_metrics(tile_ids, layer_stats_rows)
            direct_tile_powers = None
            if layer_power_source_type == "csv":
                direct_tile_powers = _load_tile_block_powers_from_csv(
                    run_dir=run_dir,
                    csv_path_raw=str(layer_power_source.get("csv_path") or ""),
                    tile_ids=tile_ids,
                )
            layer_power_enabled = bool(layer.get("power_dissipating", False)) and layer_power_source_type != "none"
            layer_header, layer_row, layer_rows = _build_power_trace(
                tile_ids,
                thermal_cfg,
                layer_tile_metrics,
                duration_s,
                block_prefix=str(layer.get("block_prefix") or ""),
                power_scale=float(layer.get("power_scale", 1.0) or 0.0),
                power_enabled=layer_power_enabled,
                emit_trace=bool(layer.get("power_dissipating", False)),
                layer_name=str(layer.get("name") or ""),
                layer_index=int(layer.get("layer_index", 0) or 0),
                layer_z_um=int(layer.get("z_um", 0) or 0),
                power_source_type=layer_power_source_type,
                direct_tile_powers=direct_tile_powers,
                include_memctrl=include_memctrl,
            )
            ptrace_header.extend(layer_header)
            ptrace_average_row.extend(layer_row)
            tile_summary_rows.extend(layer_rows)
            trace_mode = (
                "constant"
                if not layer_power_enabled or layer_power_source_type in ("csv", "none")
                else "window_metrics"
            )
            for block_name in layer_header:
                if block_name.endswith("mesh_memctrl_east"):
                    block_trace_modes[block_name] = "memctrl_proxy"
                else:
                    block_trace_modes[block_name] = trace_mode
    else:
        flp_path.write_text(
            "\n".join(_build_floorplan_lines(tile_ids, thermal_cfg, mesh_size, include_memctrl=include_memctrl)) + "\n",
            encoding="utf-8",
        )
        ptrace_header, ptrace_average_row, tile_summary_rows = _build_power_trace(
            tile_ids,
            thermal_cfg,
            tile_metrics,
            duration_s,
            power_source_type="mesh_proxy",
            include_memctrl=include_memctrl,
        )
        for block_name in ptrace_header:
            block_trace_modes[block_name] = "memctrl_proxy" if block_name.endswith("mesh_memctrl_east") else "window_metrics"

    ptrace_rows = _build_windowed_ptrace_rows(
        ptrace_header=ptrace_header,
        average_row=ptrace_average_row,
        tile_summary_rows=tile_summary_rows,
        window_trace=window_trace,
        block_trace_modes=block_trace_modes,
    )
    has_window_trace = bool(window_trace.get("window_ids"))
    trace_mode = "windowed" if has_window_trace else "average"
    window_count = len(ptrace_rows)
    window_source = "window_metrics" if has_window_trace else "average_power"
    window_provenance = _annotate_trace_provenance(
        tile_summary_rows=tile_summary_rows,
        block_trace_modes=block_trace_modes,
        has_window_trace=has_window_trace,
    )
    window_power_samples = _build_window_power_samples(
        ptrace_header=ptrace_header,
        ptrace_rows=ptrace_rows,
        tile_summary_rows=tile_summary_rows,
        window_trace=window_trace,
        trace_mode=trace_mode,
        window_ns=int(thermal_cfg.get("window_ns", 1000) or 1000),
    )
    layer_trace_meta_map = _build_layer_trace_meta_map(tile_summary_rows)

    ptrace_path = hotspot_dir / "snndl_mesh.ptrace"
    ptrace_lines = ["\t".join(ptrace_header)]
    ptrace_lines.extend("\t".join(row) for row in ptrace_rows)
    ptrace_path.write_text("\n".join(ptrace_lines) + "\n", encoding="utf-8")
    window_power_samples_path = summary_dir / "window_power_samples.jsonl"
    _write_jsonl(window_power_samples_path, window_power_samples)

    config_path = hotspot_dir / "hotspot.config"
    config_path.write_text(
        _build_hotspot_config(
            model_type=hotspot_model_type,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            grid_map_mode=grid_map_mode,
            detailed_3d=detailed_3d,
        ),
        encoding="utf-8",
    )

    resolved_hotspot_bin = _resolve_hotspot_bin(hotspot_bin_override, thermal_cfg)
    hotspot_result = _run_hotspot(
        resolved_hotspot_bin,
        flp_path,
        ptrace_path,
        config_path,
        hotspot_dir,
        model_type=hotspot_model_type,
        lcf_path=lcf_path,
        detailed_3d=detailed_3d,
    )
    block_temperatures_c = _load_hotspot_block_temperatures_c(hotspot_dir / "steady.temp")
    if block_temperatures_c:
        for row in tile_summary_rows:
            block_name = str(row.get("block_name") or "")
            if block_name in block_temperatures_c:
                row["temperature_c"] = f"{block_temperatures_c[block_name]:.2f}"

    _write_csv(summary_dir / "tile_temperature_summary.csv", tile_summary_rows)

    temperature_values_c = [
        float(row["temperature_c"])
        for row in tile_summary_rows
        if str(row.get("temperature_c") or "").strip()
    ]
    summary_cycle_model_applicable = any(str(row.get("cycle_model_applicable") or "") == "1" for row in tile_summary_rows)
    layer_cycle_model_map = _build_layer_cycle_model_map(tile_summary_rows)

    summary = {
        "thermal_contract_version": THERMAL_CONTRACT_VERSION,
        "artifact_provenance": _build_artifact_provenance(run_dir),
        "backend": backend,
        "power_source_contract_version": "v1",
        "cycle_model_applicable": bool(summary_cycle_model_applicable),
        "hotspot_model_type": hotspot_model_type,
        "ambient_c": float(HOTSPOT_PACKAGE_DEFAULTS["ambient"] - 273.15),
        "hotspot_package": {
            "ambient_k": float(HOTSPOT_PACKAGE_DEFAULTS["ambient"]),
            "s_sink": float(HOTSPOT_PACKAGE_DEFAULTS["s_sink"]),
            "t_sink": float(HOTSPOT_PACKAGE_DEFAULTS["t_sink"]),
            "s_spreader": float(HOTSPOT_PACKAGE_DEFAULTS["s_spreader"]),
            "t_spreader": float(HOTSPOT_PACKAGE_DEFAULTS["t_spreader"]),
            "t_interface": float(HOTSPOT_PACKAGE_DEFAULTS["t_interface"]),
        },
        "tile_count": len(tile_ids),
        "mesh_size": mesh_size,
        "window_ns": int(thermal_cfg.get("window_ns", 1000) or 1000),
        "window_duration_ns": int(thermal_cfg.get("window_ns", 1000) or 1000),
        "trace_mode": trace_mode,
        "window_count": window_count,
        "window_source": window_source,
        "window_provenance": window_provenance,
        "window_power_sample_count": len(window_power_samples),
        "window_power_block_count": sum(len(list(sample.get("blocks") or [])) for sample in window_power_samples),
        "window_power_trace_sources": sorted(
            {
                str(block.get("trace_source") or "").strip()
                for sample in window_power_samples
                if isinstance(sample, dict)
                for block in list(sample.get("blocks") or [])
                if isinstance(block, dict) and str(block.get("trace_source") or "").strip()
            }
        ),
        "ptrace_row_count": len(ptrace_rows),
        "duration_s": duration_s,
        "artifacts": {
            "effective_thermal_config": str(thermal_dir / "effective_thermal_config.json"),
            "ptrace": str(ptrace_path),
            "window_power_samples_jsonl": str(window_power_samples_path),
            "hotspot_config": str(config_path),
            "steady_temp": str(hotspot_dir / "steady.temp"),
            "transient_temp": str(hotspot_dir / "transient.temp"),
            "tile_temperature_summary_csv": str(summary_dir / "tile_temperature_summary.csv"),
        },
        "hotspot": hotspot_result,
    }
    if hotspot_model_type == "grid":
        layer_stack_validation = _build_layer_stack_validation(
            lcf_path=lcf_path if lcf_path is not None else hotspot_dir / "snndl_mesh.lcf",
            config_path=config_path,
            thermal_cfg=thermal_cfg,
            layers=layers,
            tile_ids=tile_ids,
            include_memctrl=include_memctrl,
        )
        layer_stack_validation_path = summary_dir / "layer_stack_validation.json"
        _write_json(layer_stack_validation_path, layer_stack_validation)
        summary["layer_count"] = len(layers)
        summary["layers"] = [
            {
                "name": str(layer.get("name") or ""),
                "kind": str(layer.get("kind") or ""),
                "layer_index": int(layer.get("layer_index", 0) or 0),
                "z_um": int(layer.get("z_um", 0) or 0),
                "thickness_um": int(layer.get("thickness_um", 0) or 0),
                "power_scale": float(layer.get("power_scale", 0.0) or 0.0),
                "power_dissipating": bool(layer.get("power_dissipating", False)),
                "cycle_model_applicable": bool(
                    layer_cycle_model_map.get(
                        (str(layer.get("name") or ""), int(layer.get("layer_index", 0) or 0)),
                        False,
                    )
                ),
                "trace_mode": (
                    "windowed"
                    if "windowed" in (layer_trace_meta_map.get((str(layer.get("name") or ""), int(layer.get("layer_index", 0) or 0))) or {}).get("trace_modes", set())
                    else (
                        sorted(
                            (layer_trace_meta_map.get((str(layer.get("name") or ""), int(layer.get("layer_index", 0) or 0))) or {}).get("trace_modes", set())
                        )[0]
                        if (layer_trace_meta_map.get((str(layer.get("name") or ""), int(layer.get("layer_index", 0) or 0))) or {}).get("trace_modes")
                        else ""
                    )
                ),
                "trace_sources": sorted(
                    (layer_trace_meta_map.get((str(layer.get("name") or ""), int(layer.get("layer_index", 0) or 0))) or {}).get("trace_sources", set())
                ),
                "window_scaling_modes": sorted(
                    (layer_trace_meta_map.get((str(layer.get("name") or ""), int(layer.get("layer_index", 0) or 0))) or {}).get("window_scaling_modes", set())
                ),
                "memctrl_block_count": int(
                    (layer_trace_meta_map.get((str(layer.get("name") or ""), int(layer.get("layer_index", 0) or 0))) or {}).get(
                        "memctrl_block_count", 0
                    )
                ),
                "power_source": dict(layer.get("power_source") or {}),
            }
            for layer in layers
        ]
        summary["layer_stack_validation"] = {
            "status": str(layer_stack_validation.get("status") or ""),
            "passed": bool(layer_stack_validation.get("passed")),
            "layer_count_checked": int(layer_stack_validation.get("layer_count_checked") or 0),
            "mismatch_count": int(layer_stack_validation.get("mismatch_count") or 0),
            "config_matches": bool(layer_stack_validation.get("config_matches", False)),
            "config_mismatch_reasons": list(layer_stack_validation.get("config_mismatch_reasons") or []),
        }
        if lcf_path is not None:
            summary["artifacts"]["lcf"] = str(lcf_path)
        if layer_floorplans:
            summary["artifacts"]["layer_floorplans"] = list(layer_floorplans)
        summary["artifacts"]["layer_stack_validation"] = str(layer_stack_validation_path)
        summary["artifacts"]["grid_steady"] = str(hotspot_dir / "grid.steady")
        summary["artifacts"]["grid_transient"] = str(hotspot_dir / "grid.transient")
    else:
        summary["artifacts"]["floorplan"] = str(flp_path)
    memctrl_rows = [row for row in tile_summary_rows if str(row.get("block_type") or "") == "memctrl"]
    summary["memctrl"] = {
        "enabled": bool(include_memctrl),
        "block_count": len(memctrl_rows),
        "total_power_w": sum(float(row.get("average_power_w") or 0.0) for row in memctrl_rows),
    }
    if temperature_values_c:
        summary["temperature_c"] = {
            "min": min(temperature_values_c),
            "max": max(temperature_values_c),
            "avg": sum(temperature_values_c) / len(temperature_values_c),
        }
    _write_json(summary_dir / "thermal_summary.json", summary)
    return summary


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export HotSpot thermal artifacts from an SST-SnnDL run directory.")
    ap.add_argument("--run-dir", required=True, help="run dir containing effective_config.json")
    ap.add_argument("--hotspot-bin", default="", help="optional HotSpot binary override")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir).resolve()
    try:
        summary = export_thermal(run_dir=run_dir, hotspot_bin_override=str(args.hotspot_bin or ""))
    except Exception as exc:
        print(f"[thermal_export] ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        "[thermal_export] "
        f"backend={summary['backend']} tile_count={summary['tile_count']} hotspot_status={summary['hotspot']['status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
