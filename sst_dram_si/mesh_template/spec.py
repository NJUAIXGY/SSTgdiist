from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils import parse_time_to_ns


class SpecError(ValueError):
    pass


try:
    from snndl_spec.component_roles import SUPPORTED_COMPONENT_ROLES as SUPPORTED_COMPONENT_ROLES_V2
except Exception:
    SUPPORTED_COMPONENT_ROLES_V2: set[str] = {
        "router",
        "router.topology",
        "global_step_controller",
        "pe_mem_controller",
        "pe_mem_controller.backend",
        "pe_mem_bus",
        "weight_loader",
        "weight_loader.memory_if",
        "pe",
        "pe.nic",
        "pe.core",
        "pe.core.memory_if",
        "pe.l1_cache",
    }


ROLE_FORBIDDEN_COMPONENT_PARAMS: Dict[str, set[str]] = {
    "pe.core": {
        "local_storage_enable",
        "pe_internal_cpe_enable",
        "pe_internal_pod_enable",
        "pe_internal_pod_count",
        "pe_internal_pod_size",
        "pe_internal_pod_metadata_enable",
        "pe_internal_pod_owner_enable",
        "pe_internal_pod_join_enable",
        "pe_internal_pod_ready_enable",
        "pe_internal_pod_owner_entries",
        "pe_internal_pod_join_entries",
        "pe_internal_pod_ready_entries",
    },
}


PE_COMPONENT_STATE_MIRROR_KEYS: Dict[str, str] = {
    "local_storage_enable": "LOCAL_STORAGE_ENABLE",
    "pe_internal_cpe_enable": "PE_INTERNAL_CPE_ENABLE",
    "pe_internal_pod_enable": "PE_INTERNAL_POD_ENABLE",
    "pe_internal_pod_count": "PE_INTERNAL_POD_COUNT",
    "pe_internal_pod_size": "PE_INTERNAL_POD_SIZE",
    "pe_internal_pod_metadata_enable": "PE_INTERNAL_POD_METADATA_ENABLE",
    "pe_internal_pod_owner_enable": "PE_INTERNAL_POD_OWNER_ENABLE",
    "pe_internal_pod_join_enable": "PE_INTERNAL_POD_JOIN_ENABLE",
    "pe_internal_pod_ready_enable": "PE_INTERNAL_POD_READY_ENABLE",
    "pe_internal_pod_owner_entries": "PE_INTERNAL_POD_OWNER_ENTRIES",
    "pe_internal_pod_join_entries": "PE_INTERNAL_POD_JOIN_ENTRIES",
    "pe_internal_pod_ready_entries": "PE_INTERNAL_POD_READY_ENTRIES",
}


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _as_str(v: Any, default: str = "") -> str:
    s = str(v).strip() if v is not None else ""
    return s if s else default


def _as_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _as_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return bool(default)
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return bool(default)


def _normalize_thermal_backend(raw: Any) -> str:
    backend = str(raw or "").strip().lower()
    if backend in ("hotspot", "hot-spot"):
        return "hotspot"
    if backend in ("3dice", "3d-ice", "3d_ice"):
        return "3dice"
    return ""


def _normalize_thermal_model_type(raw: Any) -> str:
    model_type = str(raw or "").strip().lower()
    if model_type in ("block", "2d", "2d_block"):
        return "block"
    if model_type in ("grid", "3d", "3d_grid"):
        return "grid"
    return ""


def _normalize_grid_map_mode(raw: Any) -> str:
    mode = str(raw or "").strip().lower()
    if mode in ("avg", "min", "max", "center"):
        return mode
    return ""


def _normalize_string_list(raw: Any, *, ctx: str) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = [raw]
    elif isinstance(raw, list):
        items = raw
    else:
        raise SpecError(f"{ctx} must be a string or array of strings")
    out: List[str] = []
    for idx, item in enumerate(items):
        value = _as_str(item, "")
        if not value:
            raise SpecError(f"{ctx}[{idx}] must be non-empty")
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


def _normalize_thermal_power_source(
    raw_source: Any,
    *,
    default_type: str,
    allow_unknown_fields: bool,
    ctx: str,
) -> Dict[str, Any]:
    if raw_source is None:
        raw_source = {}
    if not isinstance(raw_source, dict):
        raise SpecError(f"{ctx} must be an object")
    _reject_unknown_keys(
        obj=raw_source,
        allowed={"type", "component_prefixes", "statistic_prefixes", "csv_path"},
        ctx=ctx,
        allow_unknown_fields=allow_unknown_fields,
    )
    source_type = _normalize_thermal_power_source_type(raw_source.get("type"))
    if not source_type:
        source_type = _normalize_thermal_power_source_type(default_type)
    if not source_type:
        raise SpecError(f"invalid {ctx}.type={raw_source.get('type')!r} (expected mesh_proxy/stats_prefix/csv/none)")
    if source_type == "stats_prefix":
        component_prefixes = _normalize_string_list(
            raw_source.get("component_prefixes"),
            ctx=f"{ctx}.component_prefixes",
        )
        statistic_prefixes = _normalize_string_list(
            raw_source.get("statistic_prefixes"),
            ctx=f"{ctx}.statistic_prefixes",
        )
        if not component_prefixes and not statistic_prefixes:
            raise SpecError(
                f"{ctx} with type='stats_prefix' requires component_prefixes and/or statistic_prefixes"
            )
        return {
            "type": source_type,
            "component_prefixes": component_prefixes,
            "statistic_prefixes": statistic_prefixes,
        }
    if source_type == "csv":
        csv_path = _as_str(raw_source.get("csv_path"), "")
        if not csv_path:
            raise SpecError(f"{ctx}.csv_path must be non-empty when type='csv'")
        return {
            "type": source_type,
            "csv_path": csv_path,
        }
    return {"type": source_type}


def _validate_component_role_params(role: str, params: Dict[str, Any]) -> None:
    forbidden = ROLE_FORBIDDEN_COMPONENT_PARAMS.get(role)
    if not forbidden:
        return
    bad_keys = sorted(k for k in params.keys() if k in forbidden)
    if not bad_keys:
        return
    if role == "pe.core":
        raise SpecError(
            f"components[{role!r}] contains PE-scoped params {bad_keys!r}; "
            "move them to components['pe']"
        )
    raise SpecError(f"components[{role!r}] contains forbidden params {bad_keys!r}")


def _mirror_pe_component_runtime_params_to_state(*, params: Dict[str, Any], state: Dict[str, Any]) -> None:
    for raw_key, state_key in PE_COMPONENT_STATE_MIRROR_KEYS.items():
        if raw_key not in params:
            continue
        state[state_key] = _as_int(params.get(raw_key), state.get(state_key, 0))


def _normalize_thermal_layers(raw_layers: Any, *, allow_unknown_fields: bool) -> List[Dict[str, Any]]:
    if raw_layers is None:
        return []
    if not isinstance(raw_layers, list):
        raise SpecError("thermal.layers must be an array")

    kind_defaults = {
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

    layers: List[Dict[str, Any]] = []
    for idx, raw_layer in enumerate(raw_layers):
        if not isinstance(raw_layer, dict):
            raise SpecError(f"thermal.layers[{idx}] must be an object")
        _reject_unknown_keys(
            obj=raw_layer,
            allowed={
                "name",
                "kind",
                "z_um",
                "thickness_um",
                "power_scale",
                "lateral_heat_flow",
                "power_dissipating",
                "volumetric_heat_capacity",
                "resistivity",
                "power_source",
            },
            ctx=f"thermal.layers[{idx}]",
            allow_unknown_fields=allow_unknown_fields,
        )

        name = _as_str(raw_layer.get("name"), "")
        if not name:
            raise SpecError(f"thermal.layers[{idx}].name must be non-empty")

        kind_raw = _as_str(raw_layer.get("kind"), "")
        if kind_raw:
            kind = kind_raw.lower()
        else:
            kind = "mesh_active" if _as_bool(raw_layer.get("power_dissipating"), True) else "tim"
        if kind not in kind_defaults:
            raise SpecError(
                f"invalid thermal.layers[{idx}].kind={kind_raw or kind!r} (expected mesh_active/tim)"
            )
        defaults = kind_defaults[kind]

        z_um = _as_int(raw_layer.get("z_um"), idx)
        if z_um < 0:
            raise SpecError(f"invalid thermal.layers[{idx}].z_um={z_um!r} (expected >=0)")

        thickness_um = _as_int(raw_layer.get("thickness_um"), 0)
        if thickness_um < 1:
            raise SpecError(f"invalid thermal.layers[{idx}].thickness_um={thickness_um!r} (expected >0)")

        power_dissipating = bool(
            _as_bool(raw_layer.get("power_dissipating"), bool(defaults["power_dissipating"]))
        )
        power_source = _normalize_thermal_power_source(
            raw_layer.get("power_source"),
            default_type="mesh_proxy" if power_dissipating else "none",
            allow_unknown_fields=allow_unknown_fields,
            ctx=f"thermal.layers[{idx}].power_source",
        )

        try:
            power_scale = float(raw_layer.get("power_scale", defaults["power_scale"]))
        except Exception as e:
            raise SpecError(
                f"invalid thermal.layers[{idx}].power_scale={raw_layer.get('power_scale')!r} (expected float >=0)"
            ) from e
        if power_scale < 0.0:
            raise SpecError(f"invalid thermal.layers[{idx}].power_scale={power_scale!r} (expected >=0)")

        try:
            volumetric_heat_capacity = float(
                raw_layer.get("volumetric_heat_capacity", defaults["volumetric_heat_capacity"])
            )
        except Exception as e:
            raise SpecError(
                "invalid thermal.layers[{idx}].volumetric_heat_capacity="
                f"{raw_layer.get('volumetric_heat_capacity')!r} (expected float >0)"
            ) from e
        if volumetric_heat_capacity <= 0.0:
            raise SpecError(
                f"invalid thermal.layers[{idx}].volumetric_heat_capacity={volumetric_heat_capacity!r} (expected >0)"
            )

        try:
            resistivity = float(raw_layer.get("resistivity", defaults["resistivity"]))
        except Exception as e:
            raise SpecError(
                f"invalid thermal.layers[{idx}].resistivity={raw_layer.get('resistivity')!r} (expected float >0)"
            ) from e
        if resistivity <= 0.0:
            raise SpecError(f"invalid thermal.layers[{idx}].resistivity={resistivity!r} (expected >0)")

        layers.append(
            {
                "name": name,
                "kind": kind,
                "z_um": int(z_um),
                "thickness_um": int(thickness_um),
                "lateral_heat_flow": bool(
                    _as_bool(raw_layer.get("lateral_heat_flow"), bool(defaults["lateral_heat_flow"]))
                ),
                "power_dissipating": power_dissipating,
                "volumetric_heat_capacity": float(volumetric_heat_capacity),
                "resistivity": float(resistivity),
                "power_scale": float(power_scale),
                "power_source": power_source,
                "_order": idx,
            }
        )

    layers.sort(key=lambda item: (int(item.get("z_um", 0)), int(item.get("_order", 0))))
    for layer in layers:
        layer.pop("_order", None)
    return layers


def _reject_unknown_keys(
    *,
    obj: Dict[str, Any],
    allowed: set[str],
    ctx: str,
    allow_unknown_fields: bool,
) -> None:
    if allow_unknown_fields:
        return
    unknown = sorted(k for k in obj.keys() if k not in allowed)
    if unknown:
        raise SpecError(f"unknown fields in {ctx}: {unknown}")


def _apply_top_level_sram_spec_to_state(
    *,
    raw_sram: Any,
    state: Dict[str, Any],
    allow_unknown_fields: bool,
) -> None:
    if raw_sram is None:
        return
    if not isinstance(raw_sram, dict):
        raise SpecError("sram must be an object")

    _reject_unknown_keys(
        obj=raw_sram,
        allowed={"model_enable", "calib_json", "calib_strict", "weight", "state"},
        ctx="sram",
        allow_unknown_fields=allow_unknown_fields,
    )

    if "model_enable" in raw_sram:
        state["SRAM_MODEL_ENABLE"] = 1 if _as_bool(raw_sram.get("model_enable"), False) else 0
    if "calib_json" in raw_sram:
        state["SRAM_CALIB_JSON"] = _as_str(raw_sram.get("calib_json"), "")
    if "calib_strict" in raw_sram:
        state["SRAM_CALIB_STRICT"] = 1 if _as_bool(raw_sram.get("calib_strict"), False) else 0

    weight = raw_sram.get("weight")
    if weight is not None:
        if not isinstance(weight, dict):
            raise SpecError("sram.weight must be an object")
        _reject_unknown_keys(
            obj=weight,
            allowed={
                "idx_enable",
                "l0_enable",
                "idx_capacity_bytes",
                "l0_capacity_bytes",
                "idx_banks",
                "l0_banks",
                "ports_per_bank",
                "bank_interleave_bytes",
                "t_read_cycles",
                "t_write_cycles",
                "sample_log2",
                "idx_base",
                "l0_base",
                "l0_slots",
            },
            ctx="sram.weight",
            allow_unknown_fields=allow_unknown_fields,
        )
        for raw_key, state_key in {
            "idx_enable": "SRAM_WEIGHT_IDX_ENABLE",
            "l0_enable": "SRAM_WEIGHT_L0_ENABLE",
        }.items():
            if raw_key in weight:
                state[state_key] = 1 if _as_bool(weight.get(raw_key), bool(state.get(state_key, 0))) else 0
        for raw_key, state_key in {
            "idx_capacity_bytes": "SRAM_WEIGHT_IDX_CAPACITY_BYTES",
            "l0_capacity_bytes": "SRAM_WEIGHT_L0_CAPACITY_BYTES",
            "idx_banks": "SRAM_WEIGHT_IDX_BANKS",
            "l0_banks": "SRAM_WEIGHT_L0_BANKS",
            "ports_per_bank": "SRAM_WEIGHT_PORTS_PER_BANK",
            "bank_interleave_bytes": "SRAM_WEIGHT_BANK_INTERLEAVE_BYTES",
            "t_read_cycles": "SRAM_WEIGHT_T_READ_CYCLES",
            "t_write_cycles": "SRAM_WEIGHT_T_WRITE_CYCLES",
            "sample_log2": "SRAM_WEIGHT_SAMPLE_LOG2",
            "idx_base": "SRAM_WEIGHT_IDX_BASE",
            "l0_base": "SRAM_WEIGHT_L0_BASE",
            "l0_slots": "SRAM_WEIGHT_L0_SLOTS",
        }.items():
            if raw_key in weight:
                state[state_key] = _as_int(weight.get(raw_key), state.get(state_key, 0))

    state_cfg = raw_sram.get("state")
    if state_cfg is not None:
        if not isinstance(state_cfg, dict):
            raise SpecError("sram.state must be an object")
        _reject_unknown_keys(
            obj=state_cfg,
            allowed={
                "enable",
                "capacity_bytes",
                "banks",
                "ports_per_bank",
                "bank_interleave_bytes",
                "t_read_cycles",
                "t_write_cycles",
                "sample_log2",
                "vmem_base",
                "refrac_base",
                "last_spike_base",
            },
            ctx="sram.state",
            allow_unknown_fields=allow_unknown_fields,
        )
        if "enable" in state_cfg:
            state["SRAM_STATE_ENABLE"] = 1 if _as_bool(state_cfg.get("enable"), bool(state.get("SRAM_STATE_ENABLE", 0))) else 0
        for raw_key, state_key in {
            "capacity_bytes": "SRAM_STATE_CAPACITY_BYTES",
            "banks": "SRAM_STATE_BANKS",
            "ports_per_bank": "SRAM_STATE_PORTS_PER_BANK",
            "bank_interleave_bytes": "SRAM_STATE_BANK_INTERLEAVE_BYTES",
            "t_read_cycles": "SRAM_STATE_T_READ_CYCLES",
            "t_write_cycles": "SRAM_STATE_T_WRITE_CYCLES",
            "sample_log2": "SRAM_STATE_SAMPLE_LOG2",
            "vmem_base": "SRAM_STATE_VMEM_BASE",
            "refrac_base": "SRAM_STATE_REFRAC_BASE",
            "last_spike_base": "SRAM_STATE_LAST_SPIKE_BASE",
        }.items():
            if raw_key in state_cfg:
                state[state_key] = _as_int(state_cfg.get(raw_key), state.get(state_key, 0))


def _apply_top_level_thermal_spec_to_state(
    *,
    raw_thermal: Any,
    state: Dict[str, Any],
    allow_unknown_fields: bool,
) -> None:
    if raw_thermal is None:
        return
    if not isinstance(raw_thermal, dict):
        raise SpecError("thermal must be an object")

    _reject_unknown_keys(
        obj=raw_thermal,
        allowed={
            "enable",
            "backend",
            "window_ns",
            "window_trace_enable",
            "window_trace_max_rows",
            "include_memctrl",
            "out_dir",
            "hotspot_bin",
            "generate_floorplan",
            "model_type",
            "grid_rows",
            "grid_cols",
            "grid_map_mode",
            "detailed_3d",
            "layers",
            "tile_width_um",
            "tile_height_um",
            "tile_gap_um",
            "comp_frac",
            "sram_frac",
            "noc_frac",
        },
        ctx="thermal",
        allow_unknown_fields=allow_unknown_fields,
    )

    if "enable" in raw_thermal:
        state["THERMAL_ENABLE"] = 1 if _as_bool(raw_thermal.get("enable"), False) else 0

    if "backend" in raw_thermal:
        backend = _normalize_thermal_backend(raw_thermal.get("backend"))
        if not backend:
            raise SpecError(
                f"invalid thermal.backend={raw_thermal.get('backend')!r} (expected hotspot/3dice)"
            )
        state["THERMAL_BACKEND"] = backend

    if "window_ns" in raw_thermal:
        value = _as_int(raw_thermal.get("window_ns"), state.get("THERMAL_WINDOW_NS", 1000))
        if value < 1:
            raise SpecError(f"invalid thermal.window_ns={value!r} (expected >=1)")
        state["THERMAL_WINDOW_NS"] = int(value)

    if "window_trace_enable" in raw_thermal:
        state["THERMAL_WINDOW_TRACE_ENABLE"] = (
            1 if _as_bool(raw_thermal.get("window_trace_enable"), False) else 0
        )

    if "window_trace_max_rows" in raw_thermal:
        value = _as_int(
            raw_thermal.get("window_trace_max_rows"),
            state.get("THERMAL_WINDOW_TRACE_MAX_ROWS", 0),
        )
        if value < 1:
            raise SpecError(f"invalid thermal.window_trace_max_rows={value!r} (expected >=1)")
        state["THERMAL_WINDOW_TRACE_MAX_ROWS"] = int(value)

    if "include_memctrl" in raw_thermal:
        state["THERMAL_INCLUDE_MEMCTRL"] = 1 if _as_bool(raw_thermal.get("include_memctrl"), False) else 0

    if "out_dir" in raw_thermal:
        out_dir = _as_str(raw_thermal.get("out_dir"), "")
        if not out_dir:
            raise SpecError("invalid thermal.out_dir='' (expected non-empty)")
        state["THERMAL_OUT_DIR"] = out_dir

    if "hotspot_bin" in raw_thermal:
        state["THERMAL_HOTSPOT_BIN"] = _as_str(raw_thermal.get("hotspot_bin"), "")

    if "generate_floorplan" in raw_thermal:
        state["THERMAL_GENERATE_FLOORPLAN"] = 1 if _as_bool(raw_thermal.get("generate_floorplan"), True) else 0

    if "model_type" in raw_thermal:
        model_type = _normalize_thermal_model_type(raw_thermal.get("model_type"))
        if not model_type:
            raise SpecError(
                f"invalid thermal.model_type={raw_thermal.get('model_type')!r} (expected block/grid)"
            )
        state["THERMAL_MODEL_TYPE"] = model_type

    for raw_key, state_key in (
        ("grid_rows", "THERMAL_GRID_ROWS"),
        ("grid_cols", "THERMAL_GRID_COLS"),
    ):
        if raw_key not in raw_thermal:
            continue
        value = _as_int(raw_thermal.get(raw_key), state.get(state_key, 64))
        if value < 1:
            raise SpecError(f"invalid thermal.{raw_key}={value!r} (expected >0)")
        state[state_key] = int(value)

    if "grid_map_mode" in raw_thermal:
        grid_map_mode = _normalize_grid_map_mode(raw_thermal.get("grid_map_mode"))
        if not grid_map_mode:
            raise SpecError(
                f"invalid thermal.grid_map_mode={raw_thermal.get('grid_map_mode')!r} (expected avg/min/max/center)"
            )
        state["THERMAL_GRID_MAP_MODE"] = grid_map_mode

    if "detailed_3d" in raw_thermal:
        state["THERMAL_DETAILED_3D"] = 1 if _as_bool(raw_thermal.get("detailed_3d"), False) else 0

    if "layers" in raw_thermal:
        layers = _normalize_thermal_layers(raw_thermal.get("layers"), allow_unknown_fields=allow_unknown_fields)
        state["THERMAL_LAYERS"] = layers
        if layers and "model_type" not in raw_thermal:
            state["THERMAL_MODEL_TYPE"] = "grid"
        if layers and "detailed_3d" not in raw_thermal:
            state["THERMAL_DETAILED_3D"] = 1

    for raw_key, state_key, minimum in (
        ("tile_width_um", "THERMAL_TILE_WIDTH_UM", 1),
        ("tile_height_um", "THERMAL_TILE_HEIGHT_UM", 1),
        ("tile_gap_um", "THERMAL_TILE_GAP_UM", 0),
    ):
        if raw_key not in raw_thermal:
            continue
        value = _as_int(raw_thermal.get(raw_key), state.get(state_key, minimum))
        if value < minimum:
            if minimum == 0:
                raise SpecError(f"invalid thermal.{raw_key}={value!r} (expected >=0)")
            raise SpecError(f"invalid thermal.{raw_key}={value!r} (expected >0)")
        state[state_key] = int(value)

    for raw_key, state_key in (
        ("comp_frac", "THERMAL_COMP_FRAC"),
        ("sram_frac", "THERMAL_SRAM_FRAC"),
        ("noc_frac", "THERMAL_NOC_FRAC"),
    ):
        if raw_key not in raw_thermal:
            continue
        raw_value = raw_thermal.get(raw_key)
        try:
            value = float(raw_value)
        except Exception as e:
            raise SpecError(f"invalid thermal.{raw_key}={raw_value!r} (expected float)") from e
        if value < 0.0:
            raise SpecError(f"invalid thermal.{raw_key}={value!r} (expected >=0)")
        state[state_key] = float(value)


def _apply_top_level_pulse_spec_to_state(
    *,
    raw_pulse: Any,
    state: Dict[str, Any],
    allow_unknown_fields: bool,
) -> None:
    if raw_pulse is None:
        return
    if not isinstance(raw_pulse, dict):
        raise SpecError("pulse must be an object")

    _reject_unknown_keys(
        obj=raw_pulse,
        allowed={
            "enable",
            "observe_only",
            "ingress_enable",
            "agenda_observe_only",
            "harbor_enable",
            "descriptor_enable",
            "descriptor_actual_enable",
            "experimental_rowdescriptor_ready_join_dedup_enable",
            "domain_retire_enable",
            "domain_retire_observe_only",
            "domain_retire_mode",
            "domain_retire_release_budget",
            "frontier_observe_enable",
            "frontier_top_lines",
            "metadata_frontier_observe_enable",
            "metadata_frontier_top_items",
            "metadata_frontier_band_slots",
            "metadata_seed_enable",
            "metadata_seed_top_bases",
            "metadata_seed_window_budget",
            "mfb_preband_seed_enable",
            "mfb_preband_top_bands",
            "mfb_preband_lines_per_band",
            "mfb_preband_band_slots",
            "mfb_preband_window_budget",
            "mfb_gather_preband_enable",
            "mfb_gather_barrier_enable",
            "mfb_gather_top_bands",
            "mfb_gather_lines_per_band",
            "mfb_gather_min_consumers",
            "mfb_gather_window_budget",
            "prebase_shared_lookup_enable",
            "osa_enable",
            "osa_shared_weight_owner_enable",
            "osa_shared_weight_owner_actual_enable",
            "osa_metadata_txn_enable",
            "osa_metadata_ready_lease_enable",
            "osa_metadata_ready_lease_ttl",
            "osa_metadata_object_mask",
            "ingress_entries",
            "core_queue_entries",
            "descriptor_packet_min",
            "bypass_high_watermark_pct",
            "bypass_mode",
        },
        ctx="pulse",
        allow_unknown_fields=allow_unknown_fields,
    )

    for raw_key, state_key in (
        ("enable", "PULSE_ENABLE"),
        ("observe_only", "PULSE_OBSERVE_ONLY"),
        ("ingress_enable", "PULSE_INGRESS_ENABLE"),
        ("agenda_observe_only", "PULSE_AGENDA_OBSERVE_ONLY"),
        ("harbor_enable", "PULSE_HARBOR_ENABLE"),
        ("descriptor_enable", "PULSE_DESCRIPTOR_ENABLE"),
        ("descriptor_actual_enable", "PULSE_DESCRIPTOR_ACTUAL_ENABLE"),
        (
            "experimental_rowdescriptor_ready_join_dedup_enable",
            "PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE",
        ),
        ("domain_retire_enable", "PULSE_DOMAIN_RETIRE_ENABLE"),
        ("domain_retire_observe_only", "PULSE_DOMAIN_RETIRE_OBSERVE_ONLY"),
        ("frontier_observe_enable", "PULSE_FRONTIER_OBSERVE_ENABLE"),
        ("metadata_frontier_observe_enable", "PULSE_METADATA_FRONTIER_OBSERVE_ENABLE"),
        ("metadata_seed_enable", "PULSE_METADATA_SEED_ENABLE"),
        ("mfb_preband_seed_enable", "PULSE_MFB_PREBAND_SEED_ENABLE"),
        ("mfb_gather_preband_enable", "PULSE_MFB_GATHER_PREBAND_ENABLE"),
        ("mfb_gather_barrier_enable", "PULSE_MFB_GATHER_BARRIER_ENABLE"),
        ("prebase_shared_lookup_enable", "PULSE_PREBASE_SHARED_LOOKUP_ENABLE"),
        ("osa_enable", "PULSE_OSA_ENABLE"),
        ("osa_shared_weight_owner_enable", "PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE"),
        ("osa_shared_weight_owner_actual_enable", "PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE"),
        ("osa_metadata_txn_enable", "PULSE_OSA_METADATA_TXN_ENABLE"),
        ("osa_metadata_ready_lease_enable", "PULSE_OSA_METADATA_READY_LEASE_ENABLE"),
    ):
        if raw_key in raw_pulse:
            state[state_key] = 1 if _as_bool(raw_pulse.get(raw_key), bool(state.get(state_key, 0))) else 0

    for raw_key, state_key, minimum in (
        ("domain_retire_release_budget", "PULSE_DOMAIN_RETIRE_RELEASE_BUDGET", 0),
        ("frontier_top_lines", "PULSE_FRONTIER_TOP_LINES", 1),
        ("metadata_frontier_top_items", "PULSE_METADATA_FRONTIER_TOP_ITEMS", 1),
        ("metadata_frontier_band_slots", "PULSE_METADATA_FRONTIER_BAND_SLOTS", 1),
        ("metadata_seed_top_bases", "PULSE_METADATA_SEED_TOP_BASES", 1),
        ("metadata_seed_window_budget", "PULSE_METADATA_SEED_WINDOW_BUDGET", 0),
        ("mfb_preband_top_bands", "PULSE_MFB_PREBAND_TOP_BANDS", 1),
        ("mfb_preband_lines_per_band", "PULSE_MFB_PREBAND_LINES_PER_BAND", 1),
        ("mfb_preband_band_slots", "PULSE_MFB_PREBAND_BAND_SLOTS", 0),
        ("mfb_preband_window_budget", "PULSE_MFB_PREBAND_WINDOW_BUDGET", 0),
        ("mfb_gather_top_bands", "PULSE_MFB_GATHER_TOP_BANDS", 1),
        ("mfb_gather_lines_per_band", "PULSE_MFB_GATHER_LINES_PER_BAND", 1),
        ("mfb_gather_min_consumers", "PULSE_MFB_GATHER_MIN_CONSUMERS", 2),
        ("mfb_gather_window_budget", "PULSE_MFB_GATHER_WINDOW_BUDGET", 0),
        ("osa_metadata_ready_lease_ttl", "PULSE_OSA_METADATA_READY_LEASE_TTL", 0),
        ("ingress_entries", "PULSE_INGRESS_ENTRIES", 0),
        ("core_queue_entries", "PULSE_CORE_QUEUE_ENTRIES", 0),
        ("descriptor_packet_min", "PULSE_DESCRIPTOR_PACKET_MIN", 1),
    ):
        if raw_key not in raw_pulse or raw_pulse.get(raw_key) is None:
            continue
        value = _as_int(raw_pulse.get(raw_key), state.get(state_key, minimum))
        if value < minimum:
            cmp = ">=" if minimum == 0 else f">={minimum}"
            raise SpecError(f"invalid pulse.{raw_key}={value!r} (expected {cmp})")
        state[state_key] = int(value)

    if "bypass_high_watermark_pct" in raw_pulse and raw_pulse.get("bypass_high_watermark_pct") is not None:
        value = _as_int(
            raw_pulse.get("bypass_high_watermark_pct"),
            state.get("PULSE_BYPASS_HIGH_WATERMARK_PCT", 100),
        )
        if value < 1 or value > 100:
            raise SpecError(
                f"invalid pulse.bypass_high_watermark_pct={value!r} (expected 1..100)"
            )
        state["PULSE_BYPASS_HIGH_WATERMARK_PCT"] = int(value)

    if "domain_retire_mode" in raw_pulse:
        mode = _as_str(
            raw_pulse.get("domain_retire_mode"),
            state.get("PULSE_DOMAIN_RETIRE_MODE", "per_post"),
        ).strip().lower()
        if mode not in ("per_post", "descriptor_domain"):
            raise SpecError(
                f"invalid pulse.domain_retire_mode={mode!r} (expected per_post|descriptor_domain)"
            )
        state["PULSE_DOMAIN_RETIRE_MODE"] = mode

    if "bypass_mode" in raw_pulse:
        mode = _as_str(
            raw_pulse.get("bypass_mode"),
            state.get("PULSE_BYPASS_MODE", "disabled"),
        ).strip().lower()
        if mode not in ("disabled", "high_watermark"):
            raise SpecError(
                f"invalid pulse.bypass_mode={mode!r} (expected disabled|high_watermark)"
            )
        state["PULSE_BYPASS_MODE"] = mode

    if "osa_metadata_object_mask" in raw_pulse:
        mask = _as_str(raw_pulse.get("osa_metadata_object_mask"), "").strip().lower()
        if mask:
            state["PULSE_OSA_METADATA_OBJECT_MASK"] = mask


def load_spec(path: str) -> Dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise SpecError(f"spec file not found: {p}")
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise SpecError(f"invalid spec json: {e}") from e
    if not isinstance(obj, dict):
        raise SpecError("spec must be a json object")
    return obj


@dataclass(frozen=True)
class ResolvedSpec:
    raw: Dict[str, Any]
    state: Dict[str, Any]
    overrides: List[Dict[str, Any]]


def resolve_spec(raw: Dict[str, Any], *, defaults_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Resolve a spec-first MeshSystemSpec into legacy `state` overrides consumed by runtime/build.

    This function is pure-Python and must NOT read environment variables.
    """
    if not isinstance(raw, dict):
        raise SpecError("spec must be a dict")

    schema_version = raw.get("schema_version")
    if schema_version not in (1, 2, 3):
        raise SpecError(f"unsupported schema_version={schema_version!r} (expected 1, 2, or 3)")

    state = dict(defaults_state)

    validate = _as_dict(raw.get("validate"))
    allow_unknown_fields = _as_bool(validate.get("allow_unknown_fields"), False)
    allowed_spec_keys = {
        "model",
        "schema_version",
        "platform",
        "noc",
        "memory",
        "pe",
        "workload",
        "control",
        "gas",
        "step",
        "routing",
        "loader",
        "debug",
        "validate",
        "overrides",
        "sram",
        "thermal",
        "pulse",
        "synapse_weight_mode",
        "gcss2_dir",
        "gcssplp_dir",
    }
    if int(schema_version) in (2, 3):
        allowed_spec_keys.add("components")
    _reject_unknown_keys(
        obj=raw,
        allowed=allowed_spec_keys,
        ctx="spec",
        allow_unknown_fields=allow_unknown_fields,
    )

    synapse_weight_mode = _as_str(raw.get("synapse_weight_mode"), "").lower()
    if synapse_weight_mode:
        if synapse_weight_mode not in (
            "bcsr_gas",
            "gcss_valueonly_dstcore",
            "gcss_valueonly_dstcore_idx2",
            "gcss_idx2_rowmphf",
            "gcss_valueonly_dstcore_vlf_premphf",
            "gcss_valueonly_dstcore_vlf_premphf_plp",
        ):
            raise SpecError(
                "invalid synapse_weight_mode="
                f"{synapse_weight_mode!r} "
                "(expected bcsr_gas/gcss_valueonly_dstcore/gcss_valueonly_dstcore_idx2/"
                "gcss_idx2_rowmphf/gcss_valueonly_dstcore_vlf_premphf/gcss_valueonly_dstcore_vlf_premphf_plp)"
            )
        state["SYNAPSE_WEIGHT_MODE"] = synapse_weight_mode

    gcss2_dir = _as_str(raw.get("gcss2_dir"), "")
    if gcss2_dir:
        state["GCSS2_DIR"] = gcss2_dir

    if state.get("SYNAPSE_WEIGHT_MODE") in ("gcss_valueonly_dstcore_idx2", "gcss_idx2_rowmphf") and not _as_str(state.get("GCSS2_DIR"), ""):
        raise SpecError("synapse_weight_mode=gcss_valueonly_dstcore_idx2/gcss_idx2_rowmphf requires gcss2_dir")

    gcssplp_dir = _as_str(raw.get("gcssplp_dir"), "")
    if gcssplp_dir:
        state["GCSSPLP_DIR"] = gcssplp_dir

    if state.get("SYNAPSE_WEIGHT_MODE") in ("gcss_valueonly_dstcore_vlf_premphf_plp",) and not _as_str(state.get("GCSSPLP_DIR"), ""):
        raise SpecError("synapse_weight_mode=gcss_valueonly_dstcore_vlf_premphf_plp requires gcssplp_dir")

    platform = _as_dict(raw.get("platform"))
    allowed_platform_keys = {"mesh_size", "node_limit", "exec_mode", "stop"}
    if int(schema_version) == 3:
        allowed_platform_keys.add("flags")
    _reject_unknown_keys(
        obj=platform,
        allowed=allowed_platform_keys,
        ctx="platform",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "mesh_size" in platform:
        mesh_size = _as_int(platform.get("mesh_size"), state.get("MESH_SIZE", 4))
        if mesh_size < 1:
            raise SpecError(f"invalid platform.mesh_size={mesh_size!r} (expected >=1)")
        state["MESH_SIZE"] = int(mesh_size)
    mesh_size_value = int(state.get("MESH_SIZE", 4) or 4)
    if "node_limit" in platform:
        node_limit = _as_int(platform.get("node_limit"), 0)
        if node_limit != 0:
            total_nodes = int(mesh_size_value) * int(mesh_size_value)
            if node_limit < 1 or node_limit > total_nodes:
                raise SpecError(f"invalid platform.node_limit={node_limit!r} (expected 1..{total_nodes} or 0)")
        state["SPEC_NODE_LIMIT"] = int(node_limit)

    if "exec_mode" in platform:
        exec_mode = _as_str(platform.get("exec_mode"), state.get("SPEC_EXEC_MODE", "gas")).lower()
        if exec_mode not in ("gas", "naive_raw", "naive_opt"):
            raise SpecError(f"invalid platform.exec_mode={exec_mode!r} (expected gas|naive_raw|naive_opt)")
        state["SPEC_EXEC_MODE"] = exec_mode

    stop = _as_dict(platform.get("stop"))
    _reject_unknown_keys(
        obj=stop,
        allowed={"mode", "max_steps", "simulation_time"},
        ctx="platform.stop",
        allow_unknown_fields=allow_unknown_fields,
    )
    stop_mode = _as_str(stop.get("mode"), "").lower()
    if stop_mode == "step_limited":
        max_steps = _as_int(stop.get("max_steps"), 0)
        if max_steps <= 0:
            raise SpecError(f"invalid platform.stop.max_steps={max_steps!r} (expected >0 when mode=step_limited)")
        state["SPEC_MAX_STEPS"] = int(max_steps)
    elif stop_mode == "time":
        state["SPEC_MAX_STEPS"] = 0
    elif stop_mode:
        raise SpecError(f"invalid platform.stop.mode={stop_mode!r} (expected step_limited|time)")
    else:
        # Keep legacy default (0 -> time-based via SIMULATION_TIME).
        state.setdefault("SPEC_MAX_STEPS", 0)

    if "simulation_time" in stop:
        sim_time = _as_str(stop.get("simulation_time"), "")
        if not sim_time:
            raise SpecError("invalid platform.stop.simulation_time='' (expected non-empty)")
        if parse_time_to_ns(sim_time) <= 0:
            raise SpecError(f"invalid platform.stop.simulation_time={sim_time!r} (expected time string like '200us')")
        state["SIMULATION_TIME"] = sim_time

    if int(schema_version) == 3:
        flags = _as_dict(platform.get("flags"))
        _reject_unknown_keys(
            obj=flags,
            allowed={
                "disable_network",
                "export_spike_csv",
                "enable_node_summary",
                "enable_test_traffic",
                "record_edge_apply_enable",
                "record_edge_idle_enable",
                "record_edge_scatter_enable",
            },
            ctx="platform.flags",
            allow_unknown_fields=allow_unknown_fields,
        )
        if "disable_network" in flags:
            state["DISABLE_NETWORK"] = _as_bool(flags.get("disable_network"), bool(state.get("DISABLE_NETWORK", False)))
        if "export_spike_csv" in flags:
            state["EXPORT_SPIKE_CSV"] = _as_bool(flags.get("export_spike_csv"), bool(state.get("EXPORT_SPIKE_CSV", False)))
        if "enable_node_summary" in flags:
            state["ENABLE_NODE_SUMMARY"] = _as_bool(
                flags.get("enable_node_summary"), bool(state.get("ENABLE_NODE_SUMMARY", False))
            )
        if "enable_test_traffic" in flags:
            state["ENABLE_TEST_TRAFFIC"] = _as_bool(flags.get("enable_test_traffic"), bool(state.get("ENABLE_TEST_TRAFFIC", False)))

        if "record_edge_apply_enable" in flags:
            state["RECORD_EDGE_APPLY_ENABLE"] = 1 if _as_bool(flags.get("record_edge_apply_enable"), True) else 0
        if "record_edge_idle_enable" in flags:
            state["RECORD_EDGE_IDLE_ENABLE"] = 1 if _as_bool(flags.get("record_edge_idle_enable"), True) else 0
        if "record_edge_scatter_enable" in flags:
            state["RECORD_EDGE_SCATTER_ENABLE"] = 1 if _as_bool(flags.get("record_edge_scatter_enable"), True) else 0

    noc = _as_dict(raw.get("noc"))
    _reject_unknown_keys(
        obj=noc,
        allowed={"type", "params"},
        ctx="noc",
        allow_unknown_fields=allow_unknown_fields,
    )
    noc_type = _as_str(noc.get("type"), "").strip().lower()
    if noc_type:
        if noc_type in ("merlin_mesh", "mesh", "merlin.mesh"):
            noc_type = "merlin_mesh"
        elif noc_type in ("merlin_torus", "torus", "merlin.torus"):
            noc_type = "merlin_torus"
        elif noc_type in ("multicast_mesh", "multicast", "storm", "storm_multicast"):
            noc_type = "multicast_mesh"
        else:
            raise SpecError(f"invalid noc.type={noc_type!r} (expected merlin_mesh|merlin_torus|multicast_mesh)")
        state["SPEC_NOC_TYPE"] = noc_type
    noc_params = _as_dict(noc.get("params"))
    _reject_unknown_keys(
        obj=noc_params,
        allowed={
            "link_bw",
            "buffer_size",
            "nic_buffer_size",
            "router_buffer_size",
            "num_vns",
            "multicast_enable",
            "multicast_block_w",
            "multicast_block_h",
            "multicast_ingress_policy",
            "multicast_inter_policy",
            "multicast_intra_policy",
            "local_endpoint_multicast_enable",
            "router_latency_cycles",
            "serialize_output_enable",
            "serialize_service_cycles",
            "serialize_output_byte_enable",
            "serialize_bytes_per_cycle",
            "serialize_header_bytes",
        },
        ctx="noc.params",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "link_bw" in noc_params:
        state["NETWORK_BANDWIDTH"] = _as_str(noc_params.get("link_bw"), state.get("NETWORK_BANDWIDTH", "40GiB/s"))
    if "nic_buffer_size" in noc_params:
        state["BUFFER_SIZE"] = _as_str(noc_params.get("nic_buffer_size"), state.get("BUFFER_SIZE", "8KiB"))
    elif "buffer_size" in noc_params:
        # Backward-compatible alias: noc.params.buffer_size controls NIC buffer by default.
        state["BUFFER_SIZE"] = _as_str(noc_params.get("buffer_size"), state.get("BUFFER_SIZE", "8KiB"))
    if "router_buffer_size" in noc_params:
        state["ROUTER_BUFFER_SIZE"] = _as_str(noc_params.get("router_buffer_size"), state.get("ROUTER_BUFFER_SIZE", "4KiB"))
    if "num_vns" in noc_params:
        num_vns = _as_int(noc_params.get("num_vns"), 2)
        if num_vns < 1:
            raise SpecError(f"invalid noc.params.num_vns={num_vns!r} (expected >=1)")
        state["SPEC_NETWORK_NUM_VNS"] = int(num_vns)
    if "multicast_enable" in noc_params:
        state["SPEC_MULTICAST_ENABLE"] = _as_bool(noc_params.get("multicast_enable"), False)
    if "multicast_block_w" in noc_params:
        block_w = _as_int(noc_params.get("multicast_block_w"), 2)
        if block_w < 1:
            raise SpecError(f"invalid noc.params.multicast_block_w={block_w!r} (expected >=1)")
        state["SPEC_MULTICAST_BLOCK_W"] = int(block_w)
    if "multicast_block_h" in noc_params:
        block_h = _as_int(noc_params.get("multicast_block_h"), 2)
        if block_h < 1:
            raise SpecError(f"invalid noc.params.multicast_block_h={block_h!r} (expected >=1)")
        state["SPEC_MULTICAST_BLOCK_H"] = int(block_h)
    if "multicast_ingress_policy" in noc_params:
        state["SPEC_MULTICAST_INGRESS_POLICY"] = _as_str(
            noc_params.get("multicast_ingress_policy"),
            state.get("SPEC_MULTICAST_INGRESS_POLICY", "top_left"),
        )
    if "multicast_inter_policy" in noc_params:
        state["SPEC_MULTICAST_INTER_POLICY"] = _as_str(
            noc_params.get("multicast_inter_policy"),
            state.get("SPEC_MULTICAST_INTER_POLICY", "xy"),
        )
    if "multicast_intra_policy" in noc_params:
        state["SPEC_MULTICAST_INTRA_POLICY"] = _as_str(
            noc_params.get("multicast_intra_policy"),
            state.get("SPEC_MULTICAST_INTRA_POLICY", "manhattan_x_first"),
        )
    if "local_endpoint_multicast_enable" in noc_params:
        state["SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE"] = _as_bool(
            noc_params.get("local_endpoint_multicast_enable"),
            False,
        )
    if "router_latency_cycles" in noc_params:
        cycles = _as_int(noc_params.get("router_latency_cycles"), 0)
        if cycles < 0:
            raise SpecError(f"invalid noc.params.router_latency_cycles={cycles!r} (expected >=0)")
        state["SPEC_ROUTER_LATENCY_CYCLES"] = int(cycles)
    if "serialize_output_enable" in noc_params:
        state["SPEC_ROUTER_SERIALIZE_OUTPUT_ENABLE"] = _as_bool(noc_params.get("serialize_output_enable"), False)
    if "serialize_service_cycles" in noc_params:
        cycles = _as_int(noc_params.get("serialize_service_cycles"), 1)
        if cycles < 1:
            raise SpecError(f"invalid noc.params.serialize_service_cycles={cycles!r} (expected >=1)")
        state["SPEC_ROUTER_SERIALIZE_SERVICE_CYCLES"] = int(cycles)
    if "serialize_output_byte_enable" in noc_params:
        state["SPEC_ROUTER_SERIALIZE_OUTPUT_BYTE_ENABLE"] = _as_bool(
            noc_params.get("serialize_output_byte_enable"),
            False,
        )
    if "serialize_bytes_per_cycle" in noc_params:
        value = _as_int(noc_params.get("serialize_bytes_per_cycle"), 16)
        if value < 1:
            raise SpecError(f"invalid noc.params.serialize_bytes_per_cycle={value!r} (expected >=1)")
        state["SPEC_ROUTER_SERIALIZE_BYTES_PER_CYCLE"] = int(value)
    if "serialize_header_bytes" in noc_params:
        value = _as_int(noc_params.get("serialize_header_bytes"), 24)
        if value < 0:
            raise SpecError(f"invalid noc.params.serialize_header_bytes={value!r} (expected >=0)")
        state["SPEC_ROUTER_SERIALIZE_HEADER_BYTES"] = int(value)

    memory = _as_dict(raw.get("memory"))
    allowed_memory_keys = {"type", "backend"}
    if int(schema_version) == 3:
        allowed_memory_keys.add("params")
    _reject_unknown_keys(
        obj=memory,
        allowed=allowed_memory_keys,
        ctx="memory",
        allow_unknown_fields=allow_unknown_fields,
    )
    mem_system = _as_str(memory.get("type"), "").strip().lower()
    if mem_system:
        if mem_system in ("memhierarchy", "memhierarchy_per_pe", "per_pe", "per-pe"):
            mem_system = "memhierarchy_per_pe"
        elif mem_system in ("memhierarchy_shared", "shared", "shared_bus", "shared-bus"):
            mem_system = "memhierarchy_shared"
        else:
            raise SpecError(f"invalid memory.type={mem_system!r} (expected memHierarchy|per_pe|shared)")
        state["SPEC_MEMORY_SYSTEM"] = mem_system
    backend = _as_dict(memory.get("backend"))
    _reject_unknown_keys(
        obj=backend,
        allowed={
            "type",
            "access_time",
            "config_file",
            "admission_queue_size",
            "admission_issue_budget_per_cycle",
            "max_requests_per_cycle",
        },
        ctx="memory.backend",
        allow_unknown_fields=allow_unknown_fields,
    )
    backend_type = _as_str(backend.get("type"), "").lower()
    mem_params = _as_dict(memory.get("params")) if int(schema_version) == 3 else {}
    if int(schema_version) == 3:
        _reject_unknown_keys(
            obj=mem_params,
            allowed={"mem_access_time", "core_mem_region_bytes"},
            ctx="memory.params",
            allow_unknown_fields=allow_unknown_fields,
        )
    if backend_type:
        if backend_type in ("simplemem", "simple_mem"):
            backend_type = "simple"
        if backend_type in ("ram2",):
            backend_type = "ramulator2"
        if backend_type not in ("simple", "ramulator2"):
            raise SpecError(f"invalid memory.backend.type={backend_type!r} (expected simple|ramulator2)")

        state["MEM_BACKEND"] = backend_type
        if backend_type == "simple":
            if "access_time" in backend:
                state["SIMPLEMEM_ACCESS_TIME"] = _as_str(backend.get("access_time"), state.get("SIMPLEMEM_ACCESS_TIME", "100ns"))
            elif "mem_access_time" in mem_params:
                state["SIMPLEMEM_ACCESS_TIME"] = _as_str(mem_params.get("mem_access_time"), state.get("SIMPLEMEM_ACCESS_TIME", "100ns"))
        else:
            cfg_file = _as_str(backend.get("config_file"), "")
            if not cfg_file:
                raise SpecError("memory.backend.type=ramulator2 requires non-empty backend.config_file")
            state["RAMULATOR2_CONFIG_FILE"] = cfg_file
            if "admission_queue_size" in backend and backend.get("admission_queue_size") is not None:
                try:
                    state["RAMULATOR2_ADMISSION_QUEUE_SIZE"] = int(backend.get("admission_queue_size"))
                except Exception as e:
                    raise SpecError(
                        f"invalid memory.backend.admission_queue_size={backend.get('admission_queue_size')!r} (expected int)"
                    ) from e
            if "admission_issue_budget_per_cycle" in backend and backend.get("admission_issue_budget_per_cycle") is not None:
                try:
                    state["RAMULATOR2_ADMISSION_ISSUE_BUDGET_PER_CYCLE"] = int(
                        backend.get("admission_issue_budget_per_cycle")
                    )
                except Exception as e:
                    raise SpecError(
                        "invalid memory.backend.admission_issue_budget_per_cycle="
                        f"{backend.get('admission_issue_budget_per_cycle')!r} (expected int)"
                    ) from e
            if "max_requests_per_cycle" in backend and backend.get("max_requests_per_cycle") is not None:
                try:
                    state["RAMULATOR2_MAX_REQUESTS_PER_CYCLE"] = int(backend.get("max_requests_per_cycle"))
                except Exception as e:
                    raise SpecError(
                        f"invalid memory.backend.max_requests_per_cycle={backend.get('max_requests_per_cycle')!r} (expected int)"
                    ) from e

    pe = _as_dict(raw.get("pe"))
    allowed_pe_keys = {
        "cores_per_pe",
        "neurons_per_core",
        "l1",
        "subcomp_line_bytes",
        "minimal_core_params",
        "readonly_freeze",
        "core",
    }
    if int(schema_version) == 3:
        allowed_pe_keys.add("num_cores_per_pe")
        allowed_pe_keys.add("state_layout")
    _reject_unknown_keys(
        obj=pe,
        allowed=allowed_pe_keys,
        ctx="pe",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "cores_per_pe" in pe:
        state["NUM_CORES_PER_PE"] = _as_int(pe.get("cores_per_pe"), state.get("NUM_CORES_PER_PE", 4))
    elif int(schema_version) == 3 and "num_cores_per_pe" in pe:
        state["NUM_CORES_PER_PE"] = _as_int(pe.get("num_cores_per_pe"), state.get("NUM_CORES_PER_PE", 4))
    if "neurons_per_core" in pe:
        state["NEURONS_PER_CORE"] = _as_int(pe.get("neurons_per_core"), state.get("NEURONS_PER_CORE", 4))
    if "minimal_core_params" in pe:
        state["SPEC_MINIMAL_CORE_PARAMS"] = _as_bool(pe.get("minimal_core_params"), False)

    l1 = _as_dict(pe.get("l1"))
    _reject_unknown_keys(
        obj=l1,
        allowed={"enable", "size", "assoc", "line_bytes"},
        ctx="pe.l1",
        allow_unknown_fields=allow_unknown_fields,
    )
    l1_line_bytes: Optional[int] = None
    if "enable" in l1:
        state["L1_ENABLE"] = _as_bool(l1.get("enable"), bool(state.get("L1_ENABLE", False)))
    if "size" in l1:
        state["L1_SIZE_STR"] = _as_str(l1.get("size"), state.get("L1_SIZE_STR", "16KiB"))
    if "assoc" in l1:
        state["L1_ASSOC"] = _as_int(l1.get("assoc"), state.get("L1_ASSOC", 8))
    if "line_bytes" in l1:
        lb = _as_int(l1.get("line_bytes"), 64)
        if lb <= 0:
            raise SpecError(f"invalid pe.l1.line_bytes={lb!r} (expected >0)")
        l1_line_bytes = int(lb)
        state["L1_LINE_BYTES_STR"] = str(int(lb))
        state["SUBCOMP_LINE_BYTES"] = int(lb)

    if "subcomp_line_bytes" in pe:
        lb = _as_int(pe.get("subcomp_line_bytes"), state.get("SUBCOMP_LINE_BYTES", 64))
        if lb <= 0:
            raise SpecError(f"invalid pe.subcomp_line_bytes={lb!r} (expected >0)")
        if l1_line_bytes is not None and int(lb) != int(l1_line_bytes):
            raise SpecError(f"pe.subcomp_line_bytes={int(lb)!r} conflicts with pe.l1.line_bytes={int(l1_line_bytes)!r}")
        state["SUBCOMP_LINE_BYTES"] = int(lb)
        state["L1_LINE_BYTES_STR"] = str(int(lb))

    readonly_freeze = _as_dict(pe.get("readonly_freeze"))
    _reject_unknown_keys(
        obj=readonly_freeze,
        allowed={"enable", "v_thresh", "tau_mem"},
        ctx="pe.readonly_freeze",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "enable" in readonly_freeze:
        state["SPEC_READONLY_FREEZE_ENABLE"] = _as_bool(readonly_freeze.get("enable"), False)
    if "v_thresh" in readonly_freeze:
        try:
            state["SPEC_READONLY_V_THRESH"] = float(readonly_freeze.get("v_thresh"))
        except Exception:
            raise SpecError(f"invalid pe.readonly_freeze.v_thresh={readonly_freeze.get('v_thresh')!r} (expected float)")
    if "tau_mem" in readonly_freeze:
        try:
            state["SPEC_READONLY_TAU_MEM"] = float(readonly_freeze.get("tau_mem"))
        except Exception:
            raise SpecError(f"invalid pe.readonly_freeze.tau_mem={readonly_freeze.get('tau_mem')!r} (expected float)")

    if int(schema_version) == 3:
        state_layout = _as_dict(pe.get("state_layout"))
        _reject_unknown_keys(
            obj=state_layout,
            allowed={"use_soa", "use_aosoa", "aosoa_block_rows"},
            ctx="pe.state_layout",
            allow_unknown_fields=allow_unknown_fields,
        )
        if "use_soa" in state_layout:
            state["USE_SOA_STATE"] = 1 if _as_bool(state_layout.get("use_soa"), False) else 0
        if "use_aosoa" in state_layout:
            state["USE_AOSOA_STATE"] = 1 if _as_bool(state_layout.get("use_aosoa"), False) else 0
        if int(state.get("USE_SOA_STATE", 0) or 0) != 0 and int(state.get("USE_AOSOA_STATE", 0) or 0) != 0:
            raise SpecError("pe.state_layout.use_soa and pe.state_layout.use_aosoa are mutually exclusive")
        if "aosoa_block_rows" in state_layout:
            abr = _as_int(state_layout.get("aosoa_block_rows"), state.get("AOSOA_BLOCK_ROWS", 16))
            if abr <= 0:
                raise SpecError(f"invalid pe.state_layout.aosoa_block_rows={abr!r} (expected >0)")
            state["AOSOA_BLOCK_ROWS"] = int(abr)

    pe_core = _as_dict(pe.get("core"))
    pe_core_allowed = {"apply_dense_acc_enable", "acc_shadow_verify_enable"}
    if int(schema_version) == 3:
        pe_core_allowed |= {"memory_warmup_cycles", "loader_barrier_cycles"}
    _reject_unknown_keys(
        obj=pe_core,
        allowed=pe_core_allowed,
        ctx="pe.core",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "apply_dense_acc_enable" in pe_core:
        state["SPEC_APPLY_DENSE_ACC_ENABLE"] = _as_bool(pe_core.get("apply_dense_acc_enable"), True)
    if "acc_shadow_verify_enable" in pe_core:
        state["SPEC_ACC_SHADOW_VERIFY_ENABLE"] = _as_bool(pe_core.get("acc_shadow_verify_enable"), False)
    if int(schema_version) == 3:
        if "memory_warmup_cycles" in pe_core:
            v = _as_int(pe_core.get("memory_warmup_cycles"), state.get("CORE_MEMORY_WARMUP_CYCLES", 200))
            if v < 0:
                raise SpecError(f"invalid pe.core.memory_warmup_cycles={v!r} (expected >=0)")
            state["CORE_MEMORY_WARMUP_CYCLES"] = int(v)
        if "loader_barrier_cycles" in pe_core:
            v = _as_int(pe_core.get("loader_barrier_cycles"), state.get("CORE_LOADER_BARRIER_CYCLES", 0))
            if v < 0:
                raise SpecError(f"invalid pe.core.loader_barrier_cycles={v!r} (expected >=0)")
            state["CORE_LOADER_BARRIER_CYCLES"] = int(v)

    _apply_top_level_thermal_spec_to_state(
        raw_thermal=raw.get("thermal"),
        state=state,
        allow_unknown_fields=allow_unknown_fields,
    )
    _apply_top_level_pulse_spec_to_state(
        raw_pulse=raw.get("pulse"),
        state=state,
        allow_unknown_fields=allow_unknown_fields,
    )

    sram = _as_dict(raw.get("sram"))
    sram_allowed = {"model_enable", "calib_json", "calib_strict", "weight", "state"}
    _reject_unknown_keys(
        obj=sram,
        allowed=sram_allowed,
        ctx="sram",
        allow_unknown_fields=allow_unknown_fields,
    )
    sram_weight = _as_dict(sram.get("weight"))
    _reject_unknown_keys(
        obj=sram_weight,
        allowed={
            "idx_enable", "l0_enable", "idx_capacity_bytes", "l0_capacity_bytes",
            "idx_banks", "l0_banks", "ports_per_bank", "bank_interleave_bytes",
            "t_read_cycles", "t_write_cycles", "sample_log2", "idx_base", "l0_base",
            "l0_slots",
        },
        ctx="sram.weight",
        allow_unknown_fields=allow_unknown_fields,
    )
    sram_state = _as_dict(sram.get("state"))
    _reject_unknown_keys(
        obj=sram_state,
        allowed={
            "enable", "capacity_bytes", "banks", "ports_per_bank",
            "bank_interleave_bytes", "t_read_cycles", "t_write_cycles",
            "sample_log2", "vmem_base", "refrac_base", "last_spike_base",
        },
        ctx="sram.state",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "model_enable" in sram:
        state["SRAM_MODEL_ENABLE"] = 1 if _as_bool(sram.get("model_enable"), False) else 0
    if "calib_json" in sram:
        state["SRAM_CALIB_JSON"] = _as_str(sram.get("calib_json"))
    if "calib_strict" in sram:
        state["SRAM_CALIB_STRICT"] = 1 if _as_bool(sram.get("calib_strict"), False) else 0
    _sram_weight_state_map = {
        "idx_enable": "SRAM_WEIGHT_IDX_ENABLE",
        "l0_enable": "SRAM_WEIGHT_L0_ENABLE",
        "idx_capacity_bytes": "SRAM_WEIGHT_IDX_CAPACITY_BYTES",
        "l0_capacity_bytes": "SRAM_WEIGHT_L0_CAPACITY_BYTES",
        "idx_banks": "SRAM_WEIGHT_IDX_BANKS",
        "l0_banks": "SRAM_WEIGHT_L0_BANKS",
        "ports_per_bank": "SRAM_WEIGHT_PORTS_PER_BANK",
        "bank_interleave_bytes": "SRAM_WEIGHT_BANK_INTERLEAVE_BYTES",
        "t_read_cycles": "SRAM_WEIGHT_T_READ_CYCLES",
        "t_write_cycles": "SRAM_WEIGHT_T_WRITE_CYCLES",
        "sample_log2": "SRAM_WEIGHT_SAMPLE_LOG2",
        "idx_base": "SRAM_WEIGHT_IDX_BASE",
        "l0_base": "SRAM_WEIGHT_L0_BASE",
        "l0_slots": "SRAM_WEIGHT_L0_SLOTS",
    }
    for spec_key, state_key in _sram_weight_state_map.items():
        if spec_key in sram_weight:
            value = sram_weight.get(spec_key)
            if spec_key in ("idx_enable", "l0_enable"):
                state[state_key] = 1 if _as_bool(value, False) else 0
            else:
                state[state_key] = _as_int(value, state.get(state_key, 0))
    _sram_state_state_map = {
        "enable": "SRAM_STATE_ENABLE",
        "capacity_bytes": "SRAM_STATE_CAPACITY_BYTES",
        "banks": "SRAM_STATE_BANKS",
        "ports_per_bank": "SRAM_STATE_PORTS_PER_BANK",
        "bank_interleave_bytes": "SRAM_STATE_BANK_INTERLEAVE_BYTES",
        "t_read_cycles": "SRAM_STATE_T_READ_CYCLES",
        "t_write_cycles": "SRAM_STATE_T_WRITE_CYCLES",
        "sample_log2": "SRAM_STATE_SAMPLE_LOG2",
        "vmem_base": "SRAM_STATE_VMEM_BASE",
        "refrac_base": "SRAM_STATE_REFRAC_BASE",
        "last_spike_base": "SRAM_STATE_LAST_SPIKE_BASE",
    }
    for spec_key, state_key in _sram_state_state_map.items():
        if spec_key in sram_state:
            value = sram_state.get(spec_key)
            if spec_key == "enable":
                state[state_key] = 1 if _as_bool(value, False) else 0
            else:
                state[state_key] = _as_int(value, state.get(state_key, 0))

    workload = _as_dict(raw.get("workload"))
    allowed_workload_keys = {"impl", "stats_modules"}
    if int(schema_version) == 3:
        allowed_workload_keys |= {"type", "params", "spike_source"}
    _reject_unknown_keys(
        obj=workload,
        allowed=allowed_workload_keys,
        ctx="workload",
        allow_unknown_fields=allow_unknown_fields,
    )
    wl_params = _as_dict(workload.get("params")) if int(schema_version) == 3 else {}
    wl_type = _as_str(workload.get("type"), "").lower() if int(schema_version) == 3 else ""
    wl_impl = wl_type or _as_str(workload.get("impl"), "").lower()
    if int(schema_version) == 3:
        snn_workload_param_keys = {"tau_mem", "thresholds", "t_ref", "init_default_weight", "class_freqs"}
        riscv_snn_workload_param_keys = {
            "backend_name",
            "firmware_elf",
            "hart_isa",
            "local_mem_bytes",
            "cmd_queue_entries",
            "cmp_queue_entries",
            "rx_debug_queue_entries",
            "boot_addr",
        }
        allowed_workload_param_keys = (
            riscv_snn_workload_param_keys if wl_impl == "riscv_snn" else snn_workload_param_keys
        )
        _reject_unknown_keys(
            obj=wl_params,
            allowed=allowed_workload_param_keys,
            ctx="workload.params",
            allow_unknown_fields=allow_unknown_fields,
        )
    if wl_impl:
        state["SPEC_WORKLOAD_IMPL"] = wl_impl
    wl_stats = _as_str(workload.get("stats_modules"), "")
    if wl_stats:
        state["SPEC_WORKLOAD_STATS_MODULES"] = wl_stats
    if int(schema_version) == 3 and wl_impl == "riscv_snn":
        if "backend_name" in wl_params:
            backend_name = _as_str(wl_params.get("backend_name"), "").strip()
            if not backend_name:
                raise SpecError("invalid workload.params.backend_name='' (expected non-empty backend name)")
            state["SPEC_RISCV_SNN_BACKEND_NAME"] = backend_name
        if "firmware_elf" in wl_params:
            firmware_elf = _as_str(wl_params.get("firmware_elf"), "")
            if not firmware_elf:
                raise SpecError("invalid workload.params.firmware_elf='' (expected non-empty path)")
            state["SPEC_RISCV_SNN_FIRMWARE_ELF"] = firmware_elf
        if "hart_isa" in wl_params:
            hart_isa = _as_str(wl_params.get("hart_isa"), "")
            if not hart_isa:
                raise SpecError("invalid workload.params.hart_isa='' (expected non-empty ISA string)")
            state["SPEC_RISCV_SNN_HART_ISA"] = hart_isa
        for spec_key, state_key in (
            ("local_mem_bytes", "SPEC_RISCV_SNN_LOCAL_MEM_BYTES"),
            ("cmd_queue_entries", "SPEC_RISCV_SNN_CMD_QUEUE_ENTRIES"),
            ("cmp_queue_entries", "SPEC_RISCV_SNN_CMP_QUEUE_ENTRIES"),
            ("rx_debug_queue_entries", "SPEC_RISCV_SNN_RX_DEBUG_QUEUE_ENTRIES"),
            ("boot_addr", "SPEC_RISCV_SNN_BOOT_ADDR"),
        ):
            if spec_key not in wl_params or wl_params.get(spec_key) is None:
                continue
            value = _as_int(wl_params.get(spec_key), int(state.get(state_key, 0) or 0))
            if value < 0:
                raise SpecError(f"invalid workload.params.{spec_key}={value!r} (expected >=0)")
            if spec_key != "boot_addr" and value == 0:
                raise SpecError(f"invalid workload.params.{spec_key}={value!r} (expected >0)")
            state[state_key] = int(value)

    if int(schema_version) == 3 and wl_impl != "riscv_snn":
        if "tau_mem" in wl_params and wl_params.get("tau_mem") is not None:
            try:
                state["CORE_TAU_MEM"] = float(wl_params.get("tau_mem"))
            except Exception as e:
                raise SpecError(f"invalid workload.params.tau_mem={wl_params.get('tau_mem')!r} (expected float)") from e

        if "thresholds" in wl_params:
            thresholds = wl_params.get("thresholds")
            if thresholds is None:
                state["THRESHOLDS"] = None
            elif isinstance(thresholds, dict):
                _reject_unknown_keys(
                    obj=thresholds,
                    allowed={"input", "hidden1", "hidden2", "output"},
                    ctx="workload.params.thresholds",
                    allow_unknown_fields=allow_unknown_fields,
                )
                parsed: Dict[str, float] = {}
                for key in ("input", "hidden1", "hidden2", "output"):
                    if key not in thresholds:
                        continue
                    raw_val = thresholds.get(key)
                    if raw_val is None:
                        continue
                    try:
                        parsed[key] = float(raw_val)
                    except Exception as e:
                        raise SpecError(
                            f"invalid workload.params.thresholds.{key}={raw_val!r} (expected float)"
                        ) from e
                state["THRESHOLDS"] = parsed
            else:
                raise SpecError(
                    f"invalid workload.params.thresholds={thresholds!r} "
                    "(expected object like {input,hidden1,hidden2,output} or null)"
                )

        if "t_ref" in wl_params and wl_params.get("t_ref") is not None:
            t_ref = _as_int(wl_params.get("t_ref"), int(state.get("CORE_T_REF", 2) or 2))
            if t_ref < 0:
                raise SpecError(f"invalid workload.params.t_ref={t_ref!r} (expected >=0)")
            state["CORE_T_REF"] = int(t_ref)

        if "init_default_weight" in wl_params and wl_params.get("init_default_weight") is not None:
            try:
                state["CORE_INIT_DEFAULT_WEIGHT"] = float(wl_params.get("init_default_weight"))
            except Exception as e:
                raise SpecError(
                    f"invalid workload.params.init_default_weight={wl_params.get('init_default_weight')!r} (expected float)"
                ) from e

        if "class_freqs" in wl_params:
            class_freqs = wl_params.get("class_freqs")
            if class_freqs is None:
                state["SPEC_CLASS_FREQS"] = None
            elif isinstance(class_freqs, list):
                if len(class_freqs) != 4:
                    raise SpecError(
                        f"invalid workload.params.class_freqs={class_freqs!r} (expected list of 4 numbers)"
                    )
                parsed_freqs: List[int] = []
                for idx, raw_val in enumerate(class_freqs):
                    if raw_val is None:
                        raise SpecError(
                            f"invalid workload.params.class_freqs[{idx}]={raw_val!r} (expected number)"
                        )
                    try:
                        parsed_freqs.append(int(raw_val))
                    except Exception as e:
                        raise SpecError(
                            f"invalid workload.params.class_freqs[{idx}]={raw_val!r} (expected number)"
                        ) from e
                state["SPEC_CLASS_FREQS"] = parsed_freqs
            else:
                raise SpecError(
                    f"invalid workload.params.class_freqs={class_freqs!r} (expected list of 4 numbers or null)"
                )

        spike_source = _as_dict(workload.get("spike_source"))
        _reject_unknown_keys(
            obj=spike_source,
            allowed={"enable"},
            ctx="workload.spike_source",
            allow_unknown_fields=allow_unknown_fields,
        )
        if "enable" in spike_source:
            state["ENABLE_SPIKE_SOURCE_FLAG"] = _as_bool(
                spike_source.get("enable"), bool(state.get("ENABLE_SPIKE_SOURCE_FLAG", False))
            )

    control = _as_dict(raw.get("control"))
    _reject_unknown_keys(
        obj=control,
        allowed={
            "global_step_sync_enable",
            "gas_step_seq_gate_enable",
            "global_step_ready_delay_cycles",
            "global_step_done",
            "global_step_ctrl",
        },
        ctx="control",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "global_step_sync_enable" in control:
        state["GLOBAL_STEP_SYNC_ENABLE"] = _as_bool(control.get("global_step_sync_enable"), bool(state.get("GLOBAL_STEP_SYNC_ENABLE", True)))
    if "gas_step_seq_gate_enable" in control:
        state["SPEC_GAS_STEP_SEQ_GATE_ENABLE"] = _as_bool(control.get("gas_step_seq_gate_enable"), False)
    if "global_step_ready_delay_cycles" in control:
        state["SPEC_GLOBAL_STEP_READY_DELAY_CYCLES"] = _as_int(control.get("global_step_ready_delay_cycles"), 0)

    gdone = _as_dict(control.get("global_step_done"))
    _reject_unknown_keys(
        obj=gdone,
        allowed={"policy", "drain_min_cycles", "quiescent_min_cycles", "fixed_cycles"},
        ctx="control.global_step_done",
        allow_unknown_fields=allow_unknown_fields,
    )
    pol = _as_str(gdone.get("policy"), "").strip().lower()
    if pol and pol not in (
        "drain",
        "drain_based",
        "drainbased",
        "quiescent",
        "quiet",
        "fixed",
        "fixed_cycles",
        "timer",
    ):
        raise SpecError(f"invalid control.global_step_done.policy={pol!r}")
    if pol:
        state["SPEC_GLOBAL_STEP_DONE_POLICY"] = pol
    if "drain_min_cycles" in gdone:
        state["SPEC_GLOBAL_STEP_DRAIN_MIN_CYCLES"] = _as_int(gdone.get("drain_min_cycles"), 0)
    if "quiescent_min_cycles" in gdone:
        state["SPEC_GLOBAL_STEP_QUIESCENT_MIN_CYCLES"] = _as_int(gdone.get("quiescent_min_cycles"), 0)
    if "fixed_cycles" in gdone:
        state["SPEC_GLOBAL_STEP_FIXED_CYCLES"] = _as_int(gdone.get("fixed_cycles"), 0)
    gctrl = _as_dict(control.get("global_step_ctrl"))
    _reject_unknown_keys(
        obj=gctrl,
        allowed={"verbose", "require_all_ready", "strict_seq_check"},
        ctx="control.global_step_ctrl",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "verbose" in gctrl:
        state["GLOBAL_STEP_CTRL_VERBOSE"] = _as_int(gctrl.get("verbose"), state.get("GLOBAL_STEP_CTRL_VERBOSE", 0))
    if "require_all_ready" in gctrl:
        state["SPEC_GLOBAL_STEP_REQUIRE_ALL_READY"] = _as_int(gctrl.get("require_all_ready"), 1)
    if "strict_seq_check" in gctrl:
        state["SPEC_GLOBAL_STEP_STRICT_SEQ_CHECK"] = _as_int(gctrl.get("strict_seq_check"), 0)

    gas = _as_dict(raw.get("gas"))
    _reject_unknown_keys(
        obj=gas,
        allowed={
            "merge_policy",
            "gap_k_bytes",
            "lmax_bytes",
            "max_inflight",
            "row_window_bytes",
            "row_window_timeout_ns",
            "vlf_enable",
            "vlf_run_enable",
            "apply_issue_policy",
            "apply_frags_per_issue",
            "apply_bank_credit",
            "apply_age_fair_ns",
            "experimental_gcss_phase_breakdown_enable",
            "experimental_retire_shadow_per_post_enable",
            "experimental_gcss_vlf_queue_policy",
            "experimental_gcss_vlf_fair_band_size",
            "experimental_gcss_vlf_bounded_rescue_enable",
            "experimental_gcss_vlf_bounded_rescue_scan_limit",
            "experimental_gcss_vlf_bounded_rescue_head_wait_cycles",
            "experimental_gcss_vlf_bounded_rescue_depth_threshold",
            "window_cycles",
            "gather_quiesce_cycles",
            "gather_min_cycles",
            "dense_strict_cacheline",
            "force_defer",
        },
        ctx="gas",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "merge_policy" in gas:
        mp = _as_str(gas.get("merge_policy"), "").lower()
        if mp and mp not in ("auto", "row", "cacheline", "none"):
            raise SpecError(f"invalid gas.merge_policy={mp!r} (expected auto|row|cacheline|none)")
        if mp:
            state["_GAS_MERGE_POLICY"] = mp
    if "gap_k_bytes" in gas:
        v = _as_int(gas.get("gap_k_bytes"), state.get("_GAS_GAP_K_BYTES", 2048))
        if v < 0:
            raise SpecError(f"invalid gas.gap_k_bytes={v!r} (expected >=0)")
        state["_GAS_GAP_K_BYTES"] = int(v)
    if "lmax_bytes" in gas:
        v = _as_int(gas.get("lmax_bytes"), state.get("_GAS_LMAX_BYTES", 65536))
        if v <= 0:
            raise SpecError(f"invalid gas.lmax_bytes={v!r} (expected >0)")
        state["_GAS_LMAX_BYTES"] = int(v)
    if "max_inflight" in gas:
        v = _as_int(gas.get("max_inflight"), state.get("_GAS_MAX_INFLIGHT", 128))
        if v <= 0:
            raise SpecError(f"invalid gas.max_inflight={v!r} (expected >0)")
        state["_GAS_MAX_INFLIGHT"] = int(v)
    if "row_window_bytes" in gas:
        v = _as_int(gas.get("row_window_bytes"), state.get("_GAS_ROW_WINDOW_BYTES", 0))
        if v < 0:
            raise SpecError(f"invalid gas.row_window_bytes={v!r} (expected >=0)")
        state["_GAS_ROW_WINDOW_BYTES"] = int(v)
    if "row_window_timeout_ns" in gas:
        v = _as_int(gas.get("row_window_timeout_ns"), state.get("_GAS_ROW_WINDOW_TIMEOUT_NS", 0))
        if v < 0:
            raise SpecError(f"invalid gas.row_window_timeout_ns={v!r} (expected >=0)")
        state["_GAS_ROW_WINDOW_TIMEOUT_NS"] = int(v)
    if "vlf_enable" in gas:
        v = _as_int(gas.get("vlf_enable"), state.get("_GAS_VLF_ENABLE", 0))
        if v not in (0, 1):
            raise SpecError(f"invalid gas.vlf_enable={v!r} (expected 0/1)")
        state["_GAS_VLF_ENABLE"] = int(v)
    if "vlf_run_enable" in gas:
        v = _as_int(gas.get("vlf_run_enable"), state.get("_GAS_VLF_RUN_ENABLE", 0))
        if v not in (0, 1):
            raise SpecError(f"invalid gas.vlf_run_enable={v!r} (expected 0/1)")
        state["_GAS_VLF_RUN_ENABLE"] = int(v)

    if "apply_issue_policy" in gas:
        p = _as_str(gas.get("apply_issue_policy"), "").strip().lower()
        if p and p not in ("order",):
            raise SpecError(
                f"invalid gas.apply_issue_policy={p!r} (expected order)"
            )
        if p:
            state["_GAS_APPLY_ISSUE_POLICY"] = p
    if "apply_frags_per_issue" in gas:
        v = _as_int(gas.get("apply_frags_per_issue"), state.get("_GAS_APPLY_FRAGS_PER_ISSUE", 1))
        if v < 0:
            raise SpecError(f"invalid gas.apply_frags_per_issue={v!r} (expected >=0)")
        state["_GAS_APPLY_FRAGS_PER_ISSUE"] = int(v)
    if "apply_bank_credit" in gas:
        v = _as_int(gas.get("apply_bank_credit"), state.get("_GAS_APPLY_BANK_CREDIT", 1))
        if v < 0:
            raise SpecError(f"invalid gas.apply_bank_credit={v!r} (expected >=0)")
        state["_GAS_APPLY_BANK_CREDIT"] = int(v)
    if "apply_age_fair_ns" in gas:
        v = _as_int(gas.get("apply_age_fair_ns"), state.get("_GAS_APPLY_AGE_FAIR_NS", 2000))
        if v < 0:
            raise SpecError(f"invalid gas.apply_age_fair_ns={v!r} (expected >=0)")
        state["_GAS_APPLY_AGE_FAIR_NS"] = int(v)
    if "experimental_gcss_phase_breakdown_enable" in gas:
        v = _as_int(
            gas.get("experimental_gcss_phase_breakdown_enable"),
            state.get("GCSS_PHASE_BREAKDOWN_ENABLE", 0),
        )
        if v not in (0, 1):
            raise SpecError(
                "invalid gas.experimental_gcss_phase_breakdown_enable="
                f"{v!r} (expected 0/1)"
            )
        state["GCSS_PHASE_BREAKDOWN_ENABLE"] = int(v)
    if "experimental_retire_shadow_per_post_enable" in gas:
        v = _as_int(
            gas.get("experimental_retire_shadow_per_post_enable"),
            state.get("RETIRE_SHADOW_PER_POST_ENABLE", 0),
        )
        if v not in (0, 1):
            raise SpecError(
                "invalid gas.experimental_retire_shadow_per_post_enable="
                f"{v!r} (expected 0/1)"
            )
        state["RETIRE_SHADOW_PER_POST_ENABLE"] = int(v)
    if "experimental_gcss_vlf_queue_policy" in gas:
        v = _as_str(
            gas.get("experimental_gcss_vlf_queue_policy"),
            state.get("GCSS_VLF_QUEUE_POLICY", "locality_first"),
        ).strip().lower()
        if v not in ("locality_first", "banded_line_fair"):
            raise SpecError(
                "invalid gas.experimental_gcss_vlf_queue_policy="
                f"{v!r} (expected locality_first|banded_line_fair)"
            )
        state["GCSS_VLF_QUEUE_POLICY"] = v
    if "experimental_gcss_vlf_fair_band_size" in gas:
        v = _as_int(
            gas.get("experimental_gcss_vlf_fair_band_size"),
            state.get("GCSS_VLF_FAIR_BAND_SIZE", 256),
        )
        if v < 1:
            raise SpecError(
                "invalid gas.experimental_gcss_vlf_fair_band_size="
                f"{v!r} (expected >=1)"
            )
        state["GCSS_VLF_FAIR_BAND_SIZE"] = int(v)
    if "experimental_gcss_vlf_bounded_rescue_enable" in gas:
        v = _as_int(
            gas.get("experimental_gcss_vlf_bounded_rescue_enable"),
            state.get("GCSS_VLF_BOUNDED_RESCUE_ENABLE", 0),
        )
        if v not in (0, 1):
            raise SpecError(
                "invalid gas.experimental_gcss_vlf_bounded_rescue_enable="
                f"{v!r} (expected 0/1)"
            )
        state["GCSS_VLF_BOUNDED_RESCUE_ENABLE"] = int(v)
    if "experimental_gcss_vlf_bounded_rescue_scan_limit" in gas:
        v = _as_int(
            gas.get("experimental_gcss_vlf_bounded_rescue_scan_limit"),
            state.get("GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT", 8),
        )
        if v < 0:
            raise SpecError(
                "invalid gas.experimental_gcss_vlf_bounded_rescue_scan_limit="
                f"{v!r} (expected >=0)"
            )
        state["GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT"] = int(v)
    if "experimental_gcss_vlf_bounded_rescue_head_wait_cycles" in gas:
        v = _as_int(
            gas.get("experimental_gcss_vlf_bounded_rescue_head_wait_cycles"),
            state.get("GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES", 64),
        )
        if v < 0:
            raise SpecError(
                "invalid gas.experimental_gcss_vlf_bounded_rescue_head_wait_cycles="
                f"{v!r} (expected >=0)"
            )
        state["GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES"] = int(v)
    if "experimental_gcss_vlf_bounded_rescue_depth_threshold" in gas:
        v = _as_int(
            gas.get("experimental_gcss_vlf_bounded_rescue_depth_threshold"),
            state.get("GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD", 3),
        )
        if v < 0:
            raise SpecError(
                "invalid gas.experimental_gcss_vlf_bounded_rescue_depth_threshold="
                f"{v!r} (expected >=0)"
            )
        state["GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD"] = int(v)
    window_cycles = _as_dict(gas.get("window_cycles"))
    _reject_unknown_keys(
        obj=window_cycles,
        allowed={"gather", "apply", "scatter"},
        ctx="gas.window_cycles",
        allow_unknown_fields=allow_unknown_fields,
    )
    if window_cycles:
        base_wc = dict(state.get("_GAS_WINDOW_CYCLES", {}) or {})
        for k in ("gather", "apply", "scatter"):
            if k in window_cycles:
                v = _as_int(window_cycles.get(k), base_wc.get(k, 0))
                if v < 0:
                    raise SpecError(f"invalid gas.window_cycles.{k}={v!r} (expected >=0)")
                base_wc[k] = int(v)
        state["_GAS_WINDOW_CYCLES"] = base_wc

    if "gather_quiesce_cycles" in gas:
        v = _as_int(gas.get("gather_quiesce_cycles"), 0)
        if v < 0:
            raise SpecError(f"invalid gas.gather_quiesce_cycles={v!r} (expected >=0)")
        state["SPEC_GAS_GATHER_QUIESCE_CYCLES"] = int(v)
    if "gather_min_cycles" in gas:
        v = _as_int(gas.get("gather_min_cycles"), 0)
        if v < 0:
            raise SpecError(f"invalid gas.gather_min_cycles={v!r} (expected >=0)")
        state["SPEC_GAS_GATHER_MIN_CYCLES"] = int(v)
    if "dense_strict_cacheline" in gas:
        state["SPEC_GAS_DENSE_STRICT_CACHELINE"] = _as_bool(gas.get("dense_strict_cacheline"), False)
    if "force_defer" in gas:
        state["SPEC_GAS_FORCE_DEFER"] = _as_bool(gas.get("force_defer"), False)

    step = _as_dict(raw.get("step"))
    _reject_unknown_keys(
        obj=step,
        allowed={
            "random_activation_enable",
            "activation_period_cycles",
            "activation_fraction",
            "activation_fanout",
            "activation_seed",
            "activation_event_weight",
            "activation_trigger_core",
            "activation_use_bcsr_routes",
            "activation_template",
            "reset_mem_each_step",
            "seed_only_mode",
            "bcsr",
        },
        ctx="step",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "random_activation_enable" in step:
        state["STEP_RANDOM_ACT_ENABLE"] = _as_int(step.get("random_activation_enable"), state.get("STEP_RANDOM_ACT_ENABLE", 0))
    if "activation_period_cycles" in step:
        state["STEP_ACTIVATION_PERIOD_CYCLES"] = _as_int(step.get("activation_period_cycles"), state.get("STEP_ACTIVATION_PERIOD_CYCLES", 0))
    if "activation_fraction" in step:
        try:
            state["STEP_ACTIVATION_FRACTION"] = float(step.get("activation_fraction"))
        except Exception:
            state["STEP_ACTIVATION_FRACTION"] = float(state.get("STEP_ACTIVATION_FRACTION", 0.0))
    if "activation_fanout" in step:
        state["STEP_ACTIVATION_FANOUT"] = _as_int(step.get("activation_fanout"), state.get("STEP_ACTIVATION_FANOUT", 0))
    if "activation_seed" in step:
        state["STEP_ACTIVATION_SEED"] = _as_int(step.get("activation_seed"), state.get("STEP_ACTIVATION_SEED", 0))
    if "activation_event_weight" in step:
        try:
            state["STEP_ACTIVATION_EVENT_WEIGHT"] = float(step.get("activation_event_weight"))
        except Exception:
            state["STEP_ACTIVATION_EVENT_WEIGHT"] = float(state.get("STEP_ACTIVATION_EVENT_WEIGHT", 0.0))
    if "activation_trigger_core" in step:
        state["STEP_ACTIVATION_TRIGGER_CORE"] = _as_int(step.get("activation_trigger_core"), state.get("STEP_ACTIVATION_TRIGGER_CORE", 0))
    if "activation_use_bcsr_routes" in step:
        state["STEP_ACTIVATION_USE_BCSR_ROUTES"] = _as_bool(step.get("activation_use_bcsr_routes"), bool(state.get("STEP_ACTIVATION_USE_BCSR_ROUTES", 0)))
    if "activation_template" in step:
        state["STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE"] = _as_str(step.get("activation_template"), state.get("STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE", ""))
    if "reset_mem_each_step" in step:
        state["STEP_RESET_MEM_EACH_STEP"] = _as_int(step.get("reset_mem_each_step"), state.get("STEP_RESET_MEM_EACH_STEP", 0))
    if "seed_only_mode" in step:
        state["STEP_SEED_ONLY_MODE"] = _as_int(step.get("seed_only_mode"), state.get("STEP_SEED_ONLY_MODE", 0))

    step_bcsr = _as_dict(step.get("bcsr"))
    _reject_unknown_keys(
        obj=step_bcsr,
        allowed={
            "weight_epsilon",
            "rowptr_offset",
            "colidx_offset",
            "blockdata_offset",
            "blockids_offset",
            "br",
            "bc",
            "idx_bytes",
            "val_bytes",
        },
        ctx="step.bcsr",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "weight_epsilon" in step_bcsr:
        try:
            state["STEP_ACTIVATION_BCSR_WEIGHT_EPS"] = float(step_bcsr.get("weight_epsilon"))
        except Exception:
            state["STEP_ACTIVATION_BCSR_WEIGHT_EPS"] = float(state.get("STEP_ACTIVATION_BCSR_WEIGHT_EPS", 0.0))

    offset_values = [
        step_bcsr.get("rowptr_offset"),
        step_bcsr.get("colidx_offset"),
        step_bcsr.get("blockdata_offset"),
        step_bcsr.get("blockids_offset"),
    ]
    if any(v is not None for v in offset_values) and not all(v is not None for v in offset_values):
        raise SpecError("step.bcsr offsets must be all-or-none")

    for key, st_key in (
        ("rowptr_offset", "STEP_ACTIVATION_BCSR_ROWPTR_OFFSET"),
        ("colidx_offset", "STEP_ACTIVATION_BCSR_COLIDX_OFFSET"),
        ("blockdata_offset", "STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET"),
        ("blockids_offset", "STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET"),
        ("br", "STEP_ACTIVATION_BCSR_BR"),
        ("bc", "STEP_ACTIVATION_BCSR_BC"),
        ("idx_bytes", "STEP_ACTIVATION_BCSR_IDX_BYTES"),
        ("val_bytes", "STEP_ACTIVATION_BCSR_VAL_BYTES"),
    ):
        if key in step_bcsr:
            val = step_bcsr.get(key)
            state[st_key] = None if val is None else _as_int(val, state.get(st_key, 0) or 0)

    routing = _as_dict(raw.get("routing"))
    _reject_unknown_keys(
        obj=routing,
        allowed={"mode", "epsilon", "topk_per_pe", "topk", "mapping_mode", "verify_enable"},
        ctx="routing",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "mode" in routing:
        mode = _as_str(routing.get("mode"), "").strip().lower()
        if mode and mode not in ("fixed", "weight_driven", "hierarchical"):
            raise SpecError(f"invalid routing.mode={mode!r} (expected fixed|weight_driven|hierarchical)")
        if mode:
            state["ROUTING_MODE"] = mode
    if "mapping_mode" in routing:
        mm = _as_str(routing.get("mapping_mode"), "").strip().lower()
        if mm and mm not in ("post", "pre"):
            raise SpecError(f"invalid routing.mapping_mode={mm!r} (expected post|pre)")
        if mm:
            state["SPEC_MAPPING_MODE"] = mm
    if "epsilon" in routing:
        try:
            eps = float(routing.get("epsilon"))
        except Exception:
            raise SpecError(f"invalid routing.epsilon={routing.get('epsilon')!r} (expected float)")
        if eps < 0.0 or eps > 1.0:
            raise SpecError(f"invalid routing.epsilon={eps!r} (expected 0<=x<=1)")
        state["ROUT_EPS"] = float(eps)
    if "topk_per_pe" in routing:
        v = _as_int(routing.get("topk_per_pe"), state.get("ROUT_TOPK_PER_PE", 2))
        if v < 1:
            raise SpecError(f"invalid routing.topk_per_pe={v!r} (expected >=1)")
        state["ROUT_TOPK_PER_PE"] = int(v)
    if "topk" in routing:
        v = _as_int(routing.get("topk"), state.get("ROUT_TOPK", 12))
        if v < 1:
            raise SpecError(f"invalid routing.topk={v!r} (expected >=1)")
        state["ROUT_TOPK"] = int(v)
    if "verify_enable" in routing:
        state["VERIFY_ROUTING"] = 1 if _as_bool(routing.get("verify_enable"), False) else 0

    loader = _as_dict(raw.get("loader"))
    _reject_unknown_keys(
        obj=loader,
        allowed={
            "verbose",
            "chunk_bytes",
            "timed_seed_enable",
            "timed_seed_allow_cache",
            "verify_readback",
            "verify_bytes",
            "verify_mode",
            "verify_samples",
            "verify_seed",
            "verify_colidx_start",
            "diag_timed_read",
            "diag_timed_read_colidx_start",
            "write_pattern_mode",
            "write_pattern_row_scale",
        },
        ctx="loader",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "verbose" in loader:
        state["LOADER_VERBOSE"] = _as_int(loader.get("verbose"), state.get("LOADER_VERBOSE", 0))
    if "chunk_bytes" in loader:
        v = _as_int(loader.get("chunk_bytes"), state.get("LOADER_CHUNK_BYTES", 64))
        if v <= 0:
            raise SpecError(f"invalid loader.chunk_bytes={v!r} (expected >0)")
        state["LOADER_CHUNK_BYTES"] = int(v)
    if "timed_seed_enable" in loader:
        state["LOADER_TIMED_SEED_ENABLE"] = 1 if _as_bool(loader.get("timed_seed_enable"), False) else 0
    if "timed_seed_allow_cache" in loader:
        state["LOADER_TIMED_SEED_ALLOW_CACHE"] = 1 if _as_bool(loader.get("timed_seed_allow_cache"), False) else 0
    if "verify_readback" in loader:
        state["LOADER_VERIFY_READBACK"] = 1 if _as_bool(loader.get("verify_readback"), False) else 0
    if "verify_bytes" in loader:
        v = _as_int(loader.get("verify_bytes"), state.get("LOADER_VERIFY_BYTES", 64))
        if v <= 0:
            raise SpecError(f"invalid loader.verify_bytes={v!r} (expected >0)")
        state["LOADER_VERIFY_BYTES"] = int(v)
    if "verify_mode" in loader:
        mode = _as_str(loader.get("verify_mode"), "").strip().lower()
        if mode not in ("", "raw_bcsr", "dense_rowcol_v1"):
            raise SpecError(f"invalid loader.verify_mode={mode!r} (expected ''|raw_bcsr|dense_rowcol_v1)")
        state["LOADER_VERIFY_MODE"] = mode
    if "verify_samples" in loader:
        v = _as_int(loader.get("verify_samples"), 0)
        if v < 0:
            raise SpecError(f"invalid loader.verify_samples={v!r} (expected >=0)")
        state["LOADER_VERIFY_SAMPLES"] = int(v)
    if "verify_seed" in loader:
        v = _as_int(loader.get("verify_seed"), 0)
        if v < 0:
            raise SpecError(f"invalid loader.verify_seed={v!r} (expected >=0)")
        state["LOADER_VERIFY_SEED"] = int(v)
    if "verify_colidx_start" in loader:
        v = _as_int(loader.get("verify_colidx_start"), state.get("LOADER_VERIFY_COLIDX_START", 441))
        if v < 0:
            raise SpecError(f"invalid loader.verify_colidx_start={v!r} (expected >=0)")
        state["LOADER_VERIFY_COLIDX_START"] = int(v)
    if "diag_timed_read" in loader:
        state["LOADER_DIAG_TIMED_READ"] = 1 if _as_bool(loader.get("diag_timed_read"), False) else 0
    if "diag_timed_read_colidx_start" in loader:
        v = _as_int(
            loader.get("diag_timed_read_colidx_start"),
            state.get("LOADER_DIAG_TIMED_READ_COLIDX_START", state.get("LOADER_VERIFY_COLIDX_START", 441)),
        )
        if v < 0:
            raise SpecError(f"invalid loader.diag_timed_read_colidx_start={v!r} (expected >=0)")
        state["LOADER_DIAG_TIMED_READ_COLIDX_START"] = int(v)
    if "write_pattern_mode" in loader:
        mode = _as_str(loader.get("write_pattern_mode"), "").strip().lower()
        if mode not in ("", "const", "dense_rowcol_v1"):
            raise SpecError(f"invalid loader.write_pattern_mode={mode!r} (expected ''|const|dense_rowcol_v1)")
        state["LOADER_WRITE_PATTERN_MODE"] = mode
    if "write_pattern_row_scale" in loader:
        v = _as_int(loader.get("write_pattern_row_scale"), 1024)
        if v < 0:
            raise SpecError(f"invalid loader.write_pattern_row_scale={v!r} (expected >=0)")
        state["LOADER_WRITE_PATTERN_ROW_SCALE"] = int(v)

    debug = _as_dict(raw.get("debug"))
    _reject_unknown_keys(
        obj=debug,
        allowed={
            "sentinel_enable",
            "progress_log_interval_ns",
            "progress_log_node",
            "window_read_debug",
            "window_read_debug_all_cores",
            "debug_target_pe",
            "debug_target_core",
            "node_verbose",
            "core_verbose",
            "diag_fire_log",
            "bcsr_merge_read_verify_enable",
            "bcsr_merge_read_verify_sample_bytes",
            "bcsr_merge_read_verify_max_resps",
            "bcsr_merge_read_verify_target_pe",
            "bcsr_merge_read_verify_target_core",
        },
        ctx="debug",
        allow_unknown_fields=allow_unknown_fields,
    )
    if "sentinel_enable" in debug:
        state["SENTINEL_ENABLE"] = _as_bool(debug.get("sentinel_enable"), bool(state.get("SENTINEL_ENABLE", False)))
    if "progress_log_interval_ns" in debug:
        state["PROGRESS_LOG_INTERVAL_NS"] = _as_int(debug.get("progress_log_interval_ns"), state.get("PROGRESS_LOG_INTERVAL_NS", 0))
    if "progress_log_node" in debug:
        state["PROGRESS_LOG_NODE"] = _as_int(debug.get("progress_log_node"), state.get("PROGRESS_LOG_NODE", -1))
    if "window_read_debug" in debug:
        state["WINDOW_READ_DEBUG"] = _as_bool(debug.get("window_read_debug"), bool(state.get("WINDOW_READ_DEBUG", False)))
    if "window_read_debug_all_cores" in debug:
        state["WINDOW_READ_DEBUG_ALL"] = _as_bool(debug.get("window_read_debug_all_cores"), bool(state.get("WINDOW_READ_DEBUG_ALL", False)))
    if "debug_target_pe" in debug:
        state["DEBUG_TARGET_PE"] = _as_int(debug.get("debug_target_pe"), state.get("DEBUG_TARGET_PE", 0))
    if "debug_target_core" in debug:
        state["DEBUG_TARGET_CORE"] = _as_int(debug.get("debug_target_core"), state.get("DEBUG_TARGET_CORE", 0))
    if "node_verbose" in debug:
        state["NODE_VERBOSE"] = _as_int(debug.get("node_verbose"), state.get("NODE_VERBOSE", 0))
    if "core_verbose" in debug:
        state["CORE_VERBOSE"] = _as_int(debug.get("core_verbose"), state.get("CORE_VERBOSE", 0))
    if "diag_fire_log" in debug:
        state["DIAG_FIRE_LOG"] = _as_bool(debug.get("diag_fire_log"), bool(state.get("DIAG_FIRE_LOG", False)))
    if "bcsr_merge_read_verify_enable" in debug:
        state["BCSR_MERGE_READ_VERIFY_ENABLE"] = _as_bool(debug.get("bcsr_merge_read_verify_enable"), False)
    if "bcsr_merge_read_verify_sample_bytes" in debug:
        state["BCSR_MERGE_READ_VERIFY_SAMPLE_BYTES"] = _as_int(debug.get("bcsr_merge_read_verify_sample_bytes"), 64)
    if "bcsr_merge_read_verify_max_resps" in debug:
        state["BCSR_MERGE_READ_VERIFY_MAX_RESPS"] = _as_int(debug.get("bcsr_merge_read_verify_max_resps"), 8)
    if "bcsr_merge_read_verify_target_pe" in debug:
        state["BCSR_MERGE_READ_VERIFY_TARGET_PE"] = _as_int(debug.get("bcsr_merge_read_verify_target_pe"), 0)
    if "bcsr_merge_read_verify_target_core" in debug:
        state["BCSR_MERGE_READ_VERIFY_TARGET_CORE"] = _as_int(debug.get("bcsr_merge_read_verify_target_core"), 0)

    _reject_unknown_keys(
        obj=validate,
        allowed={"profile", "allow_unknown_fields"},
        ctx="validate",
        allow_unknown_fields=allow_unknown_fields,
    )

    # Fill spec-only keys with deterministic defaults (so downstream code can rely on presence).
    state.setdefault("SPEC_NETWORK_NUM_VNS", 2)
    state.setdefault("SPEC_WORKLOAD_IMPL", "snn")
    state.setdefault("SPEC_WORKLOAD_STATS_MODULES", "")
    state.setdefault("SPEC_GLOBAL_STEP_REQUIRE_ALL_READY", 1)
    state.setdefault("SPEC_GLOBAL_STEP_STRICT_SEQ_CHECK", 0)
    state.setdefault("SPEC_EXEC_MODE", "gas")
    state.setdefault("SPEC_MAX_STEPS", 0)
    state.setdefault("SPEC_NOC_TYPE", "merlin_mesh")
    state.setdefault("SPEC_MULTICAST_ENABLE", False)
    state.setdefault("SPEC_MULTICAST_BLOCK_W", 2)
    state.setdefault("SPEC_MULTICAST_BLOCK_H", 2)
    state.setdefault("SPEC_MULTICAST_INGRESS_POLICY", "top_left")
    state.setdefault("SPEC_MULTICAST_INTER_POLICY", "xy")
    state.setdefault("SPEC_MULTICAST_INTRA_POLICY", "manhattan_x_first")
    state.setdefault("SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE", False)
    state.setdefault("SPEC_ROUTER_LATENCY_CYCLES", 0)
    state.setdefault("SPEC_ROUTER_SERIALIZE_OUTPUT_ENABLE", False)
    state.setdefault("SPEC_ROUTER_SERIALIZE_SERVICE_CYCLES", 1)
    state.setdefault("SPEC_ROUTER_SERIALIZE_OUTPUT_BYTE_ENABLE", False)
    state.setdefault("SPEC_ROUTER_SERIALIZE_BYTES_PER_CYCLE", 16)
    state.setdefault("SPEC_ROUTER_SERIALIZE_HEADER_BYTES", 24)
    state.setdefault("ROUTER_BUFFER_SIZE", "4KiB")
    state.setdefault("SPEC_MEMORY_SYSTEM", "memhierarchy_per_pe")
    state.setdefault("SPEC_MAPPING_MODE", "post")
    state.setdefault("SPEC_MINIMAL_CORE_PARAMS", False)
    state.setdefault("SPEC_READONLY_FREEZE_ENABLE", False)
    state.setdefault("SPEC_READONLY_V_THRESH", 1.0e9)
    state.setdefault("SPEC_READONLY_TAU_MEM", 0.001)
    state.setdefault("SPEC_APPLY_DENSE_ACC_ENABLE", True)
    state.setdefault("SPEC_ACC_SHADOW_VERIFY_ENABLE", False)

    overrides = _as_list(raw.get("overrides"))
    if not all(isinstance(x, dict) for x in overrides):
        raise SpecError("overrides must be a list of objects")

    if int(schema_version) in (2, 3):
        components = raw.get("components")
        if components is None:
            components = {}
        if not isinstance(components, dict):
            raise SpecError("components must be an object (role -> params)")

        component_rules: List[Dict[str, Any]] = []
        for role in sorted(components.keys()):
            params = components.get(role)
            if not isinstance(role, str) or not role.strip():
                raise SpecError(f"invalid components role={role!r} (expected non-empty string)")
            role = role.strip()
            if (role not in SUPPORTED_COMPONENT_ROLES_V2) and (not allow_unknown_fields):
                raise SpecError(f"unknown components role={role!r} (supported: {sorted(SUPPORTED_COMPONENT_ROLES_V2)})")
            if params is None:
                continue
            if not isinstance(params, dict):
                raise SpecError(f"invalid components[{role!r}] (expected params object)")
            if not all(isinstance(k, str) for k in params.keys()):
                raise SpecError(f"invalid components[{role!r}] params keys (expected strings)")
            bad_values = []
            for k, v in params.items():
                if v is None or isinstance(v, (str, int, float, bool)):
                    continue
                bad_values.append(k)
            if bad_values:
                raise SpecError(
                    f"invalid components[{role!r}] param values for keys {sorted(bad_values)!r} "
                    "(expected scalar JSON values: string/number/bool/null)"
                )
            _validate_component_role_params(role, params)
            if role == "pe":
                _mirror_pe_component_runtime_params_to_state(params=params, state=state)
            component_rules.append({"match": {"role": role}, "params": dict(params)})
        overrides = component_rules + overrides

    rs = ResolvedSpec(raw=dict(raw), state=state, overrides=[dict(x) for x in overrides])  # type: ignore[arg-type]
    return {"raw": rs.raw, "state": rs.state, "overrides": rs.overrides}
