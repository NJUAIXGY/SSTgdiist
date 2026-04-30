from __future__ import annotations

import inspect
import math
import os
import json
from typing import Any, Dict, List, Optional, Tuple

import sst

try:
    import snndl_system
except Exception:
    snndl_system = None

from .bcsr import load_core_bcsr_meta
from .gas_cmd_cost_offline_model import derive_dram_cmd_cost_from_ramulator2_cfg
from .overrides import OverrideEngine
from .paths import core_window_metrics_csv_path
from .paths import pe_output_dir
from .paths import resolve_complex_spike_file
from .paths import resolve_spike_data_dir
from .utils import mesh_print


def _record_override_report(
    *,
    override_report: List[Dict[str, Any]],
    role: str,
    component_type: str,
    name: str,
    tags: Dict[str, Any],
    base_params: Dict[str, Any],
    final_params: Dict[str, Any],
    hits: List[Dict[str, Any]],
) -> None:
    changed: Dict[str, Any] = {}
    for k, v in final_params.items():
        if base_params.get(k) != v:
            changed[k] = v
    override_report.append(
        {
            "role": str(role),
            "type": str(component_type),
            "name": str(name),
            "tags": dict(tags or {}),
            "hits": list(hits),
            "changed": changed,
        }
    )


def _add_params_with_overrides(
    obj: Any,
    *,
    role: str,
    component_type: str,
    name: str,
    tags: Dict[str, Any],
    params: Dict[str, Any],
    override_engine: Optional[OverrideEngine],
    override_report: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    if override_engine is None:
        final_params = dict(params)
        obj.addParams(final_params)
        return final_params

    final_params, hits = override_engine.apply(
        role=str(role),
        component_type=str(component_type),
        name=str(name),
        tags=dict(tags or {}),
        base_params=dict(params),
    )
    obj.addParams(final_params)

    if override_report is not None and hits:
        _record_override_report(
            override_report=override_report,
            role=role,
            component_type=component_type,
            name=name,
            tags=tags,
            base_params=params,
            final_params=final_params,
            hits=hits,
        )
    return final_params


def merge_params_checked(
    dst: Dict[str, Any],
    src: Dict[str, Any],
    *,
    allow_override: Optional[set[str]] = None,
    ctx: str = "",
    warn: bool = True,
) -> Dict[str, Any]:
    if allow_override is None:
        allow_override = set()
    for k, v in src.items():
        if warn and (k in dst) and (k not in allow_override):
            mesh_print(f"[mesh_template] WARN duplicate param key: {ctx}{k} overwritten")
        dst[k] = v
    return dst


def resolve_sentinel_target_pe(debug: Dict[str, Any]) -> int:
    target_pe = debug.get("sentinel_target_pe", debug.get("debug_target_pe", 0))
    try:
        return int(target_pe)
    except Exception:
        return 0


def _normalize_synapse_weight_mode(mode: Any) -> str:
    value = str(mode or "bcsr_gas").strip().lower()
    aliases = {
        "gscc_valueonly_dstcore": "gcss_valueonly_dstcore",
        "gscc_valueonly_dstcore_vlf_premphf": "gcss_valueonly_dstcore_vlf_premphf",
        "gscc_valueonly_dstcore_vlf_premphf_plp": "gcss_valueonly_dstcore_vlf_premphf_plp",
    }
    value = aliases.get(value, value)
    if value not in (
        "bcsr_gas",
        "gcss_valueonly_dstcore",
        "gcss_valueonly_dstcore_idx2",
        "gcss_idx2_rowmphf",
        "gcss_valueonly_dstcore_vlf_premphf",
        "gcss_valueonly_dstcore_vlf_premphf_plp",
    ):
        return "bcsr_gas"
    return value


def compute_ports_per_pe_for_synapse_mode(num_cores_per_pe: int, synapse_weight_mode: Any) -> int:
    _normalize_synapse_weight_mode(synapse_weight_mode)
    return int(num_cores_per_pe) + 1


def _extract_workload_node_params(mesh: Dict[str, Any]) -> Dict[str, Any]:
    workload_impl = str((mesh or {}).get("workload_impl", "") or "").strip().lower()
    if workload_impl != "riscv_snn":
        return {}

    raw = dict((mesh or {}).get("workload_params", {}) or {})
    params: Dict[str, Any] = {}
    params["riscv_snn_backend_name"] = str(raw.get("backend_name", "null") or "null").strip() or "null"
    firmware_elf = str(raw.get("firmware_elf", "") or "").strip()
    hart_isa = str(raw.get("hart_isa", "rv64im_zicsr") or "rv64im_zicsr").strip()
    if firmware_elf:
        params["riscv_snn_firmware_elf"] = firmware_elf
    params["riscv_snn_hart_isa"] = hart_isa
    params["riscv_snn_local_mem_bytes"] = int(raw.get("local_mem_bytes", 64 * 1024) or 0)
    params["riscv_snn_cmd_queue_entries"] = int(raw.get("cmd_queue_entries", 64) or 0)
    params["riscv_snn_cmp_queue_entries"] = int(raw.get("cmp_queue_entries", 64) or 0)
    params["riscv_snn_rx_debug_queue_entries"] = int(raw.get("rx_debug_queue_entries", 16) or 0)
    params["riscv_snn_boot_addr"] = int(raw.get("boot_addr", 0) or 0)
    return params


def _apply_workload_params_to_component_params(
    component_params: Dict[str, Any],
    *,
    workload_impl: str,
    workload_stats_modules: str,
    workload_node_params: Dict[str, Any],
) -> Dict[str, Any]:
    if workload_impl:
        component_params["workload_impl"] = workload_impl
    if workload_stats_modules:
        component_params["workload_stats_modules"] = workload_stats_modules
    if workload_node_params:
        merge_params_checked(component_params, workload_node_params, ctx="workload.")
    return component_params


def make_effective_sram_provenance(*, mesh: Dict[str, Any], final_pe_core_params: Dict[str, Any]) -> Dict[str, Any]:
    mesh_cfg = dict((mesh or {}).get("sram", {}) or {})
    weight_cfg = dict(mesh_cfg.get("weight", {}) or {})
    state_cfg = dict(mesh_cfg.get("state", {}) or {})
    calib_meta = dict(mesh_cfg.get("calib_meta", {}) or {})
    structured = {
        "model_enable": int(mesh_cfg.get("model_enable", 0) or 0),
        "weight_idx_enable": int(weight_cfg.get("idx_enable", 0) or 0),
        "weight_l0_enable": int(weight_cfg.get("l0_enable", 0) or 0),
        "state_enable": int(state_cfg.get("enable", 0) or 0),
        "weight_idx_capacity_bytes": int(weight_cfg.get("idx_capacity_bytes", 0) or 0),
        "weight_l0_capacity_bytes": int(weight_cfg.get("l0_capacity_bytes", 0) or 0),
        "state_capacity_bytes": int(state_cfg.get("capacity_bytes", 0) or 0),
        "weight_idx_banks": int(weight_cfg.get("idx_banks", 16) or 16),
        "weight_l0_banks": int(weight_cfg.get("l0_banks", 8) or 8),
        "state_banks": int(state_cfg.get("banks", 16) or 16),
        "weight_ports_per_bank": int(weight_cfg.get("ports_per_bank", 1) or 1),
        "state_ports_per_bank": int(state_cfg.get("ports_per_bank", 1) or 1),
        "weight_bank_interleave_bytes": int(weight_cfg.get("bank_interleave_bytes", 4) or 4),
        "state_bank_interleave_bytes": int(state_cfg.get("bank_interleave_bytes", 4) or 4),
        "weight_t_read_cycles": int(weight_cfg.get("t_read_cycles", 1) or 1),
        "weight_t_write_cycles": int(weight_cfg.get("t_write_cycles", 1) or 1),
        "state_t_read_cycles": int(state_cfg.get("t_read_cycles", 1) or 1),
        "state_t_write_cycles": int(state_cfg.get("t_write_cycles", 1) or 1),
        "weight_sample_log2": int(weight_cfg.get("sample_log2", 0) or 0),
        "state_sample_log2": int(state_cfg.get("sample_log2", 0) or 0),
        "weight_idx_base": int(weight_cfg.get("idx_base", 0x100000000) or 0x100000000),
        "weight_l0_base": int(weight_cfg.get("l0_base", 0x200000000) or 0x200000000),
        "weight_l0_slots": int(weight_cfg.get("l0_slots", 1 << 20) or (1 << 20)),
        "state_vmem_base": int(state_cfg.get("vmem_base", 0x300000000) or 0x300000000),
        "state_refrac_base": int(state_cfg.get("refrac_base", 0x400000000) or 0x400000000),
        "state_last_spike_base": int(state_cfg.get("last_spike_base", 0x500000000) or 0x500000000),
    }
    final_params = dict(final_pe_core_params or {})
    effective = {
        "model_enable": int(final_params.get("weight_sram_model_enable", structured["model_enable"]) or 0),
        "weight_idx_enable": int(final_params.get("weight_idx_sram_enable", structured["weight_idx_enable"]) or 0),
        "weight_l0_enable": int(final_params.get("weight_l0_sram_enable", structured["weight_l0_enable"]) or 0),
        "state_enable": int(final_params.get("state_sram_enable", structured["state_enable"]) or 0),
        "weight_idx_capacity_bytes": int(final_params.get("weight_idx_sram_capacity_bytes", structured["weight_idx_capacity_bytes"]) or 0),
        "weight_l0_capacity_bytes": int(final_params.get("weight_l0_sram_capacity_bytes", structured["weight_l0_capacity_bytes"]) or 0),
        "state_capacity_bytes": int(final_params.get("state_sram_capacity_bytes", structured["state_capacity_bytes"]) or 0),
        "weight_idx_banks": int(final_params.get("weight_idx_sram_banks", structured["weight_idx_banks"]) or 0),
        "weight_l0_banks": int(final_params.get("weight_l0_sram_banks", structured["weight_l0_banks"]) or 0),
        "state_banks": int(final_params.get("state_sram_banks", structured["state_banks"]) or 0),
        "weight_ports_per_bank": int(final_params.get("weight_sram_ports_per_bank", structured["weight_ports_per_bank"]) or 0),
        "state_ports_per_bank": int(final_params.get("state_sram_ports_per_bank", structured["state_ports_per_bank"]) or 0),
        "weight_bank_interleave_bytes": int(final_params.get("weight_sram_bank_interleave_bytes", structured["weight_bank_interleave_bytes"]) or 0),
        "state_bank_interleave_bytes": int(final_params.get("state_sram_bank_interleave_bytes", structured["state_bank_interleave_bytes"]) or 0),
        "weight_t_read_cycles": int(final_params.get("weight_sram_t_read_cycles", structured["weight_t_read_cycles"]) or 0),
        "weight_t_write_cycles": int(final_params.get("weight_sram_t_write_cycles", structured["weight_t_write_cycles"]) or 0),
        "state_t_read_cycles": int(final_params.get("state_sram_t_read_cycles", structured["state_t_read_cycles"]) or 0),
        "state_t_write_cycles": int(final_params.get("state_sram_t_write_cycles", structured["state_t_write_cycles"]) or 0),
        "weight_sample_log2": int(final_params.get("weight_sram_sample_log2", structured["weight_sample_log2"]) or 0),
        "state_sample_log2": int(final_params.get("state_sram_sample_log2", structured["state_sample_log2"]) or 0),
        "weight_idx_base": int(final_params.get("weight_idx_sram_base", structured["weight_idx_base"]) or 0),
        "weight_l0_base": int(final_params.get("weight_l0_sram_base", structured["weight_l0_base"]) or 0),
        "weight_l0_slots": int(final_params.get("weight_l0_sram_slots", structured["weight_l0_slots"]) or 0),
        "state_vmem_base": int(final_params.get("state_sram_vmem_base", structured["state_vmem_base"]) or 0),
        "state_refrac_base": int(final_params.get("state_sram_refrac_base", structured["state_refrac_base"]) or 0),
        "state_last_spike_base": int(final_params.get("state_sram_last_spike_base", structured["state_last_spike_base"]) or 0),
    }
    return {"structured": structured, "effective": effective, "calib_meta": calib_meta}


def apply_mainline_pulse_cleanup(pulse_cfg: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(pulse_cfg or {})
    cleaned.update(
        {
            "domain_retire_enable": 0,
            "domain_retire_observe_only": 1,
            "domain_retire_mode": "per_post",
            "domain_retire_release_budget": 0,
            "metadata_frontier_observe_enable": 0,
            "metadata_frontier_top_items": 32,
            "metadata_frontier_band_slots": 128,
            "metadata_seed_enable": 0,
            "metadata_seed_top_bases": 32,
            "metadata_seed_window_budget": 0,
            "mfb_preband_seed_enable": 0,
            "mfb_preband_top_bands": 32,
            "mfb_preband_lines_per_band": 4,
            "mfb_preband_band_slots": 0,
            "mfb_preband_window_budget": 0,
            "mfb_gather_preband_enable": 0,
            "mfb_gather_barrier_enable": 0,
            "mfb_gather_top_bands": 32,
            "mfb_gather_lines_per_band": 4,
            "mfb_gather_min_consumers": 2,
            "mfb_gather_window_budget": 0,
        }
    )
    return cleaned


def make_effective_thermal_config(*, mesh: Dict[str, Any]) -> Dict[str, Any]:
    thermal_cfg = dict((mesh or {}).get("thermal", {}) or {})
    backend = str(thermal_cfg.get("backend", "hotspot") or "hotspot").strip().lower()
    if backend not in ("hotspot", "3dice"):
        backend = "hotspot"
    return {
        "enable": int(thermal_cfg.get("enable", 0) or 0),
        "backend": backend,
        "window_ns": int(thermal_cfg.get("window_ns", 1000) or 1000),
        "window_trace_enable": int(thermal_cfg.get("window_trace_enable", 0) or 0),
        "window_trace_max_rows": int(thermal_cfg.get("window_trace_max_rows", 0) or 0),
        "include_memctrl": int(thermal_cfg.get("include_memctrl", 0) or 0),
        "out_dir": str(thermal_cfg.get("out_dir", "thermal") or "thermal").strip(),
        "hotspot_bin": str(thermal_cfg.get("hotspot_bin", "") or "").strip(),
        "generate_floorplan": int(thermal_cfg.get("generate_floorplan", 1) or 0),
        "model_type": str(thermal_cfg.get("model_type", "block") or "block").strip().lower(),
        "grid_rows": int(thermal_cfg.get("grid_rows", 64) or 64),
        "grid_cols": int(thermal_cfg.get("grid_cols", 64) or 64),
        "grid_map_mode": str(thermal_cfg.get("grid_map_mode", "avg") or "avg").strip().lower(),
        "detailed_3d": int(thermal_cfg.get("detailed_3d", 0) or 0),
        "layers": list(thermal_cfg.get("layers", []) or []),
        "tile_width_um": int(thermal_cfg.get("tile_width_um", 1000) or 1000),
        "tile_height_um": int(thermal_cfg.get("tile_height_um", 1000) or 1000),
        "tile_gap_um": int(thermal_cfg.get("tile_gap_um", 50) or 0),
        "comp_frac": float(thermal_cfg.get("comp_frac", 0.6) or 0.0),
        "sram_frac": float(thermal_cfg.get("sram_frac", 0.25) or 0.0),
        "noc_frac": float(thermal_cfg.get("noc_frac", 0.15) or 0.0),
    }


def resolve_window_metrics_export_path(
    *,
    run_output_dir: str,
    pe_id: int,
    core_id: int,
    mesh: Dict[str, Any],
) -> str:
    thermal_cfg = make_effective_thermal_config(mesh=mesh)
    if int(thermal_cfg.get("enable", 0) or 0) == 0:
        return ""
    if int(thermal_cfg.get("window_trace_enable", 0) or 0) == 0:
        return ""
    return core_window_metrics_csv_path(str(run_output_dir), int(pe_id), int(core_id))


def _normalize_noc_type(noc_type: Any) -> str:
    noc = str(noc_type or "merlin_mesh").strip().lower()
    if noc in ("merlin_mesh", "mesh", "merlin.mesh"):
        return "merlin_mesh"
    if noc in ("merlin_torus", "torus", "merlin.torus"):
        return "merlin_torus"
    if noc in ("multicast_mesh", "multicast", "storm", "storm_multicast"):
        return "multicast_mesh"
    raise RuntimeError(f"invalid noc_type={noc!r} (expected merlin_mesh/merlin_torus/multicast_mesh)")


def _resolve_noc_builder_module(noc_type: Any) -> Any:
    noc = _normalize_noc_type(noc_type)
    if snndl_system is None:
        raise RuntimeError("snndl_system module not available (check import path/root import)")
    if noc == "multicast_mesh":
        builder = getattr(snndl_system, "noc_multicast", None)
        if builder is None:
            raise RuntimeError("snndl_system.noc_multicast not available (check import path)")
        return builder
    builder = getattr(snndl_system, "noc_merlin", None)
    if builder is None:
        raise RuntimeError("snndl_system.noc_merlin not available (check import path)")
    return builder


def _call_with_supported_kwargs(fn: Any, **kwargs: Any) -> Any:
    if fn is None:
        return None
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return fn(**kwargs)
    filtered = {k: v for k, v in kwargs.items() if k in sig.parameters}
    return fn(**filtered)


def _resolve_snndl_builder(
    *,
    kind: str,
    override_engine: Optional[OverrideEngine],
    override_report: Optional[List[Dict[str, Any]]],
) -> Any:
    if snndl_system is None:
        raise RuntimeError("snndl_system module not available (check sys.path/root import)")
    if kind == "noc":
        namespaces = ("noc", "noc_builder", "builders", "builder")
        builder_names = ("NoCBuilder", "NocBuilder", "MeshBuilder", "NoCSystemBuilder")
    else:
        namespaces = ("memory", "mem", "mem_builder", "builders", "builder")
        builder_names = ("MemoryBuilder", "MemBuilder", "MemHierarchyBuilder", "MemorySystemBuilder")

    candidates: List[Any] = [snndl_system]
    for name in namespaces:
        ns = getattr(snndl_system, name, None)
        if ns is not None:
            candidates.append(ns)

    for candidate in candidates:
        for builder_name in builder_names:
            builder_obj = getattr(candidate, builder_name, None)
            if builder_obj is None:
                continue
            if inspect.isclass(builder_obj) or callable(builder_obj):
                return _call_with_supported_kwargs(
                    builder_obj,
                    override_engine=override_engine,
                    override_report=override_report,
                )
            return builder_obj

    return candidates[0]


def _call_snndl_method(builder: Any, method_names: Tuple[str, ...], **kwargs: Any) -> Any:
    for name in method_names:
        fn = getattr(builder, name, None)
        if callable(fn):
            return _call_with_supported_kwargs(fn, **kwargs)
    return None


def _apply_override_params(
    *,
    role: str,
    component_type: str,
    name: str,
    tags: Dict[str, Any],
    params: Dict[str, Any],
    override_engine: Optional[OverrideEngine],
    override_report: Optional[List[Dict[str, Any]]],
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    if override_engine is None:
        return dict(params), []
    final_params, hits = override_engine.apply(
        role=str(role),
        component_type=str(component_type),
        name=str(name),
        tags=dict(tags or {}),
        base_params=dict(params),
    )
    if override_report is not None and hits:
        _record_override_report(
            override_report=override_report,
            role=role,
            component_type=component_type,
            name=name,
            tags=tags,
            base_params=params,
            final_params=final_params,
            hits=hits,
        )
    return final_params, hits


def _snndl_create_component(
    builder: Any,
    *,
    name: str,
    component_type: str,
    role: str,
    tags: Dict[str, Any],
    params: Dict[str, Any],
    override_engine: Optional[OverrideEngine],
    override_report: Optional[List[Dict[str, Any]]],
) -> Any:
    final_params, _ = _apply_override_params(
        role=role,
        component_type=component_type,
        name=name,
        tags=tags,
        params=params,
        override_engine=override_engine,
        override_report=override_report,
    )
    component = _call_snndl_method(
        builder,
        ("create_component", "build_component", "component", "add_component"),
        name=name,
        component_type=component_type,
        params=final_params,
    )
    if component is None:
        component = sst.Component(name, component_type)
    if final_params:
        component.addParams(final_params)
    return component


def _snndl_create_subcomponent(
    builder: Any,
    *,
    parent: Any,
    slot: str,
    component_type: str,
    name: str,
    role: str,
    tags: Dict[str, Any],
    params: Dict[str, Any],
    override_engine: Optional[OverrideEngine],
    override_report: Optional[List[Dict[str, Any]]],
    override_component_type: Optional[str] = None,
) -> Any:
    override_type = override_component_type or component_type
    final_params, _ = _apply_override_params(
        role=role,
        component_type=override_type,
        name=name,
        tags=tags,
        params=params,
        override_engine=override_engine,
        override_report=override_report,
    )
    sub = _call_snndl_method(
        builder,
        ("create_subcomponent", "build_subcomponent", "subcomponent", "add_subcomponent"),
        parent=parent,
        slot=slot,
        component_type=component_type,
        name=name,
        params=final_params,
    )
    if sub is None:
        sub = parent.setSubComponent(slot, component_type)
    if final_params:
        sub.addParams(final_params)
    return sub


def _snndl_create_link(builder: Any, *, name: str) -> Any:
    link = _call_snndl_method(builder, ("create_link", "build_link", "link", "add_link"), name=name)
    if link is None:
        link = sst.Link(name)
    return link


def _extract_routers(result: Any) -> List[Any]:
    if result is None:
        return []
    if isinstance(result, dict):
        routers = result.get("routers") or result.get("components") or result.get("nodes")
        if routers is not None:
            return list(routers)
    if isinstance(result, (list, tuple)):
        return list(result)
    return []


def _supports_override(fn: Any) -> bool:
    if fn is None:
        return False
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    return any(name in sig.parameters for name in ("override_engine", "override_report", "override"))


def _extract_connection_count(result: Any) -> Optional[int]:
    if result is None:
        return None
    if isinstance(result, int):
        return int(result)
    if isinstance(result, dict):
        for key in ("count", "connection_count", "connections"):
            if key in result:
                try:
                    return int(result[key])
                except Exception:
                    return None
    return None


def _estimate_router_connection_count(*, routers: List[Any], mesh_size: int, noc_type: str) -> int:
    count = 0
    torus = str(noc_type or "merlin_mesh").strip().lower() in ("merlin_torus", "torus", "merlin.torus")
    for y in range(mesh_size):
        for x in range(mesh_size if torus else mesh_size - 1):
            node_id = y * mesh_size + x
            east_node_id = y * mesh_size + ((x + 1) % mesh_size if torus else (x + 1))
            if node_id < len(routers) and east_node_id < len(routers):
                count += 1
    for x in range(mesh_size):
        for y in range(mesh_size if torus else mesh_size - 1):
            node_id = y * mesh_size + x
            south_node_id = (((y + 1) % mesh_size) if torus else (y + 1)) * mesh_size + x
            if node_id < len(routers) and south_node_id < len(routers):
                count += 1
    return count


def _estimate_nic_connection_count(*, nics: List[Any], routers: List[Any]) -> int:
    return int(min(len(nics), len(routers)))


def _unpack_mem_controller_result(result: Any) -> Tuple[Optional[Any], Optional[Any]]:
    if result is None:
        return None, None
    if isinstance(result, dict):
        controller = result.get("mem_controller") or result.get("controller") or result.get("mem_ctrl")
        backend = result.get("backend") or result.get("mem_backend")
        return controller, backend
    if isinstance(result, (list, tuple)):
        if not result:
            return None, None
        controller = result[0] if len(result) > 0 else None
        backend = result[1] if len(result) > 1 else None
        return controller, backend
    return result, None


def _unpack_mem_bus_result(result: Any) -> Optional[Any]:
    if result is None:
        return None
    if isinstance(result, dict):
        return result.get("bus") or result.get("mem_bus") or result.get("component")
    if isinstance(result, (list, tuple)):
        return result[0] if result else None
    return result


def build_mesh_routers(
    *,
    node_limit: int,
    mesh_size: int,
    network_bandwidth: str,
    noc_type: str = "merlin_mesh",
    flit_size: str = "32B",
    input_latency: str = "10ns",
    output_latency: str = "10ns",
    input_buf_size: str = "4KiB",
    output_buf_size: str = "4KiB",
    num_vns: int = 1,
    xbar_arb: str = "merlin.xbar_arb_lru",
    debug: int = 0,
    verbose: int = 0,
    network_inspectors: str = "",
    override_engine: Optional[OverrideEngine] = None,
    override_report: Optional[List[Dict[str, Any]]] = None,
) -> List[Any]:
    noc = _normalize_noc_type(noc_type)
    builder = _resolve_noc_builder_module(noc)
    builder_name = "snndl_system.noc_multicast" if noc == "multicast_mesh" else "snndl_system.noc_merlin"

    build_fn = getattr(builder, "build_routers", None)
    if not callable(build_fn):
        raise RuntimeError(f"{builder_name}.build_routers not callable")

    if noc == "multicast_mesh":
        topo_type = "multicast_mesh"
        router_params = {
            "mesh_shape": f"{mesh_size}x{mesh_size}",
            "router_latency_cycles": 0,
            "serialize_output_enable": 0,
            "serialize_service_cycles": 1,
            "serialize_output_byte_enable": 0,
            "serialize_bytes_per_cycle": 16,
            "serialize_header_bytes": 24,
            "local_endpoint_multicast_enable": 0,
            "multicast_inter_policy": "xy",
            "multicast_intra_policy": "manhattan_x_first",
            "verbose": int(verbose),
        }
        topo_params: Dict[str, Any] = {}
    else:
        topo_type = "merlin.mesh" if noc == "merlin_mesh" else "merlin.torus"
        router_params = {
            "num_ports": 5,
            "link_bw": network_bandwidth,
            "flit_size": flit_size,
            "xbar_bw": network_bandwidth,
            "input_latency": input_latency,
            "output_latency": output_latency,
            "input_buf_size": input_buf_size,
            "output_buf_size": output_buf_size,
            "num_vns": num_vns,
            "xbar_arb": xbar_arb,
            "debug": debug,
            "verbose": verbose,
            "network_inspectors": network_inspectors,
        }
        topo_params = {
            "shape": f"{mesh_size}x{mesh_size}",
            "width": "1x1",
            "local_ports": "1",
        }

    supports_override = _supports_override(build_fn)
    build_kwargs = {
        "node_limit": int(node_limit),
        "mesh_size": int(mesh_size),
        "network_bandwidth": str(network_bandwidth),
        "noc_type": str(noc),
        "topo_type": str(topo_type),
        "flit_size": str(flit_size),
        "input_latency": str(input_latency),
        "output_latency": str(output_latency),
        "input_buf_size": str(input_buf_size),
        "output_buf_size": str(output_buf_size),
        "num_vns": int(num_vns),
        "xbar_arb": str(xbar_arb),
        "debug": int(debug),
        "verbose": int(verbose),
        "network_inspectors": str(network_inspectors),
        "router_params": dict(router_params),
        "topology_params": dict(topo_params),
    }
    if supports_override:
        build_kwargs.update({
            "override_engine": override_engine,
            "override_report": override_report,
        })

    result = _call_with_supported_kwargs(build_fn, **build_kwargs)
    routers = _extract_routers(result)
    if not routers:
        raise RuntimeError(f"{builder_name}.build_routers returned no routers")

    if override_engine is not None and not supports_override and noc != "multicast_mesh":
        for i, router in enumerate(routers):
            router_params_with_id = dict(router_params)
            router_params_with_id["id"] = int(i)
            _add_params_with_overrides(
                router,
                role="router",
                component_type="merlin.hr_router",
                name=f"router_{i}",
                tags={"node": int(i)},
                params=router_params_with_id,
                override_engine=override_engine,
                override_report=override_report,
            )
            topo = None
            get_sub = getattr(router, "getSubComponent", None)
            if callable(get_sub):
                try:
                    topo = get_sub("topology")
                except Exception:
                    topo = None
            if topo is None:
                try:
                    topo = router.setSubComponent("topology", topo_type)
                except Exception:
                    topo = None
            if topo is not None:
                _add_params_with_overrides(
                    topo,
                    role="router.topology",
                    component_type="merlin.mesh",
                    name=f"router_{i}.topology",
                    tags={"node": int(i)},
                    params=topo_params,
                    override_engine=override_engine,
                    override_report=override_report,
                )
    return routers


def build_global_gas_step_controller(
    *,
    enabled: bool,
    verbose: int,
    start_seq: int = 1,
    max_steps: int = 0,
    require_all_ready: int = 1,
    strict_seq_check: int = 0,
    override_engine: Optional[OverrideEngine] = None,
    override_report: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Any]:
    if not enabled:
        return None
    ctrl = sst.Component("global_gas_step_controller", "SnnDL.GlobalGasStepController")
    ctrl_params = {
        "verbose": int(verbose),
        "start_seq": int(start_seq),
        "max_steps": int(max_steps),
        "require_all_ready": int(require_all_ready),
        "strict_seq_check": int(strict_seq_check),
    }
    # Experimental: step-level global apply bank credit control (p0).
    # Driven via env so baseline configs remain unchanged unless explicitly enabled.
    try:
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_ENABLE") or "").strip()
        if v:
            ctrl_params["credit_ctrl_enable"] = int(v, 0)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_MODE") or "").strip()
        if v:
            ctrl_params["credit_ctrl_mode"] = int(v, 0)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_CREDIT_MIN") or "").strip()
        if v:
            ctrl_params["credit_ctrl_credit_min"] = int(v, 0)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_CREDIT_MAX") or "").strip()
        if v:
            ctrl_params["credit_ctrl_credit_max"] = int(v, 0)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_TOP_K") or "").strip()
        if v:
            ctrl_params["credit_ctrl_top_k"] = int(v, 0)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_BASE_CREDIT") or "").strip()
        if v:
            ctrl_params["credit_ctrl_base_credit"] = int(v, 0)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_APPLY_RATIO_MIN_PERMILLE") or "").strip()
        if v:
            ctrl_params["credit_ctrl_apply_ratio_min_permille"] = int(v, 0)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_RANK_BY_APPLY") or "").strip()
        if v:
            ctrl_params["credit_ctrl_rank_by_apply"] = int(v, 0)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_PRED_SEED") or "").strip()
        if v:
            ctrl_params["credit_ctrl_pred_seed"] = int(v, 0)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_PRED_FRACTION") or "").strip()
        if v:
            ctrl_params["credit_ctrl_pred_fraction"] = float(v)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_PRED_NEURONS_PER_PE") or "").strip()
        if v:
            ctrl_params["credit_ctrl_pred_neurons_per_pe"] = int(v, 0)
        v = (os.environ.get("MESH_GLOBAL_CREDIT_CTRL_PRED_FANOUT") or "").strip()
        if v:
            ctrl_params["credit_ctrl_pred_fanout"] = int(v, 0)
    except Exception:
        pass
    _add_params_with_overrides(
        ctrl,
        role="global_step_controller",
        component_type="SnnDL.GlobalGasStepController",
        name="global_gas_step_controller",
        tags={},
        params=ctrl_params,
        override_engine=override_engine,
        override_report=override_report,
    )
    # Keep controller stats visible in mesh_stats.csv for step-limited regressions.
    try:
        ctrl.enableAllStatistics({"type": "sst.AccumulatorStatistic"})
    except Exception:
        pass
    return ctrl


def build_pe_memory_systems(
    *,
    node_limit: int,
    num_cores_per_pe: int,
    neurons_per_core: int,
    neurons_per_pe: int,
    global_weights_cols: int,
    per_core_weight_stride: int,
    pe_weight_region_stride: int,
    base_addr_global_shift: int,
    pe_mem_addr_range: int,
    mem_backend: str,
    ramulator2_config_file: str,
    simplemem_access_time: str,
    loader_verbose: int,
    loader_chunk_bytes: int,
    loader_timed_seed_enable: bool,
    loader_timed_seed_allow_cache: bool,
    loader_verify_readback: bool,
    loader_verify_bytes: int,
    loader_verify_mode: str,
    loader_verify_samples: int,
    loader_verify_seed: int,
    loader_verify_colidx_start: int,
    loader_diag_timed_read: bool,
    loader_diag_timed_read_colidx_start: int,
    loader_write_pattern_mode: str,
    loader_write_pattern_row_scale: int,
    global_bcsr_available: bool,
    global_bcsr_dir: str,
    gcss_dir: str,
    gcss2_dir: str,
    gcssvlf_dir: str,
    gcssplp_dir: str,
    gcssnt_dir: str,
    global_bcsr_offsets: Dict[str, Any],
    synapse_weight_mode: str,
    debug_conn: bool,
    ramulator2_admission_queue_size: Optional[int] = None,
    ramulator2_admission_issue_budget_per_cycle: Optional[int] = None,
    ramulator2_max_requests_per_cycle: Optional[int] = None,
    override_engine: Optional[OverrideEngine] = None,
    override_report: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Any], List[Any], List[Any], bool]:
    pe_memory_controllers: List[Any] = []
    pe_memory_buses: List[Any] = []
    pe_weight_loaders: List[Any] = []

    enable_bcsr = bool(global_bcsr_available)
    syn_mode = str(synapse_weight_mode or "bcsr_gas").strip().lower()
    if syn_mode == "gscc_valueonly_dstcore":
        syn_mode = "gcss_valueonly_dstcore"
    if syn_mode == "gscc_valueonly_dstcore_vlf_premphf":
        syn_mode = "gcss_valueonly_dstcore_vlf_premphf"
    if syn_mode == "gscc_valueonly_dstcore_vlf_premphf_plp":
        syn_mode = "gcss_valueonly_dstcore_vlf_premphf_plp"
    gcss_mode = syn_mode in (
        "gcss_valueonly_dstcore",
        "gcss_valueonly_dstcore_idx2",
        "gcss_idx2_rowmphf",
        "gcss_valueonly_dstcore_vlf_premphf",
        "gcss_valueonly_dstcore_vlf_premphf_plp",
    )
    gcss_idx2_mode = syn_mode in ("gcss_valueonly_dstcore_idx2", "gcss_idx2_rowmphf")
    gcss_premphf_mode = syn_mode in ("gcss_valueonly_dstcore_vlf_premphf", "gcss_valueonly_dstcore_vlf_premphf_plp")
    gcss_plp_mode = syn_mode == "gcss_valueonly_dstcore_vlf_premphf_plp"

    backend = str(mem_backend or "simple").strip().lower()
    if backend in ("simplemem", "simple_mem"):
        backend = "simple"
    if backend in ("ram2",):
        backend = "ramulator2"
    if backend not in ("simple", "ramulator2"):
        raise RuntimeError(f"invalid mem_backend={backend!r} (expected simple/ramulator2)")

    if snndl_system is None or not hasattr(snndl_system, "mem_memhierarchy"):
        raise RuntimeError("snndl_system.mem_memhierarchy not available (check import path)")
    mem_builder = snndl_system.mem_memhierarchy
    build_ctrl_fn = getattr(mem_builder, "build_mem_controller_with_backend", None)
    build_bus_fn = getattr(mem_builder, "build_mem_bus", None)
    connect_bus_fn = getattr(mem_builder, "connect_bus_to_mem_controller", None)
    if not callable(build_ctrl_fn):
        raise RuntimeError("snndl_system.mem_memhierarchy.build_mem_controller_with_backend not callable")
    if not callable(build_bus_fn):
        raise RuntimeError("snndl_system.mem_memhierarchy.build_mem_bus not callable")
    if not callable(connect_bus_fn):
        raise RuntimeError("snndl_system.mem_memhierarchy.connect_bus_to_mem_controller not callable")

    for pe_id in range(node_limit):
        mem_addr_start = base_addr_global_shift + pe_weight_region_stride * pe_id
        mem_addr_end = mem_addr_start + pe_weight_region_stride - 1
        mem_ctrl_params = {
            "clock": "1GHz",
            "backing": "malloc",
            "addr_range_start": str(mem_addr_start),
            "addr_range_end": str(mem_addr_end),
        }
        if ramulator2_max_requests_per_cycle is not None:
            mem_ctrl_params["max_requests_per_cycle"] = int(ramulator2_max_requests_per_cycle)

        if backend == "ramulator2":
            cfg_file = str(ramulator2_config_file or "").strip()
            if not cfg_file:
                raise RuntimeError("mem_backend=ramulator2 but ramulator2_config_file is empty")
            if not os.path.exists(cfg_file):
                raise RuntimeError(f"ramulator2_config_file not found: {cfg_file}")
            backend_params = {
                "mem_size": f"{int(pe_mem_addr_range)}B",
                "configFile": cfg_file,
                "debug": "0",
                "debug_level": "0",
            }
            if ramulator2_admission_queue_size is not None:
                backend_params["admission_queue_size"] = int(ramulator2_admission_queue_size)
            if ramulator2_admission_issue_budget_per_cycle is not None:
                backend_params["admission_issue_budget_per_cycle"] = int(ramulator2_admission_issue_budget_per_cycle)
            backend_component = "memHierarchy.ramulator2"
        else:
            backend_params = {
                "access_time": str(simplemem_access_time or "100ns"),
                "mem_size": f"{int(pe_mem_addr_range)}B",
            }
            backend_component = "memHierarchy.simpleMem"

        ctrl_supports_override = _supports_override(build_ctrl_fn)
        if ctrl_supports_override:
            ctrl_result = _call_with_supported_kwargs(
                build_ctrl_fn,
                name=f"pe_{pe_id}_memory_controller",
                controller_params=dict(mem_ctrl_params),
                backend_type=str(backend_component),
                backend_params=dict(backend_params),
                backend=str(backend),
                mem_size=f"{int(pe_mem_addr_range)}B",
                override_engine=override_engine,
                override_report=override_report,
            )
            mem_controller, mem_backend_sc = _unpack_mem_controller_result(ctrl_result)
        else:
            final_ctrl_params, _ = _apply_override_params(
                role="pe_mem_controller",
                component_type="memHierarchy.MemController",
                name=f"pe_{pe_id}_memory_controller",
                tags={"pe": int(pe_id)},
                params=mem_ctrl_params,
                override_engine=override_engine,
                override_report=override_report,
            )
            final_backend_params, _ = _apply_override_params(
                role="pe_mem_controller.backend",
                component_type=str(backend_component),
                name=f"pe_{pe_id}_memory_controller.backend",
                tags={"pe": int(pe_id)},
                params=backend_params,
                override_engine=override_engine,
                override_report=override_report,
            )
            ctrl_result = _call_with_supported_kwargs(
                build_ctrl_fn,
                name=f"pe_{pe_id}_memory_controller",
                controller_params=dict(final_ctrl_params),
                backend_type=str(backend_component),
                backend_params=dict(final_backend_params),
                backend=str(backend),
                mem_size=f"{int(pe_mem_addr_range)}B",
            )
            mem_controller, mem_backend_sc = _unpack_mem_controller_result(ctrl_result)
            if mem_controller is not None and final_ctrl_params:
                mem_controller.addParams(final_ctrl_params)
            if mem_controller is not None and mem_backend_sc is None:
                mem_backend_sc = mem_controller.setSubComponent("backend", str(backend_component))
            if mem_backend_sc is not None and final_backend_params:
                mem_backend_sc.addParams(final_backend_params)

        if mem_controller is None:
            raise RuntimeError("mem controller builder returned None")

        try:
            mem_controller.enableAllStatistics({"type": "sst.AccumulatorStatistic"})
        except Exception:
            pass
        pe_memory_controllers.append(mem_controller)

        mem_bus_params = {
            "bus_frequency": "1GHz",
            "debug": "0",
            "verbose": "0",
        }
        bus_supports_override = _supports_override(build_bus_fn)
        if bus_supports_override:
            bus_result = _call_with_supported_kwargs(
                build_bus_fn,
                name=f"pe_{pe_id}_memory_bus",
                params=dict(mem_bus_params),
                override_engine=override_engine,
                override_report=override_report,
            )
            mem_bus = _unpack_mem_bus_result(bus_result)
        else:
            final_bus_params, _ = _apply_override_params(
                role="pe_mem_bus",
                component_type="memHierarchy.Bus",
                name=f"pe_{pe_id}_memory_bus",
                tags={"pe": int(pe_id)},
                params=mem_bus_params,
                override_engine=override_engine,
                override_report=override_report,
            )
            bus_result = _call_with_supported_kwargs(
                build_bus_fn,
                name=f"pe_{pe_id}_memory_bus",
                params=dict(final_bus_params),
            )
            mem_bus = _unpack_mem_bus_result(bus_result)
            if mem_bus is not None and final_bus_params:
                mem_bus.addParams(final_bus_params)
        if mem_bus is None:
            raise RuntimeError("mem bus builder returned None")
        pe_memory_buses.append(mem_bus)

        bus_to_mem_link = _call_with_supported_kwargs(
            connect_bus_fn,
            name=f"pe_{pe_id}_bus_to_mem",
            bus=mem_bus,
            mem_controller=mem_controller,
            link_latency="5ns",
            bus_port="lowlink0",
            mem_port="highlink",
        )
        if bus_to_mem_link is None:
            bus_to_mem_link = _snndl_create_link(mem_builder, name=f"pe_{pe_id}_bus_to_mem")
            bus_to_mem_link.connect(
                (mem_bus, "lowlink0", "5ns"),
                (mem_controller, "highlink", "5ns"),
            )

        pe_weight_base = mem_addr_start
        weight_loader = sst.Component(f"pe_{pe_id}_weight_loader", "SnnDL.WeightLoader")
        weight_loader_params: Dict[str, Any] = {
            # Keep init quiet by default; opt-in via local_run_config.json (loader_verbose).
            "verbose": int(loader_verbose) if pe_id == 0 else 0,
            "node_id": int(pe_id),
            "base_addr_start": pe_weight_base,
            "per_core_stride": per_core_weight_stride,
            "num_cores": int(num_cores_per_pe),
            "neurons_per_core": neurons_per_core,
            "rows_per_core": neurons_per_core,
            "cols_per_core": global_weights_cols,
            "total_neurons": neurons_per_pe,
            "weight_format": "bin",
            "per_core_files": 0,
            "fill_value": 0.0,
            "validate_length": 1,
            "row_major": 1,
            "chunk_size_bytes": loader_chunk_bytes,
            "timed_seed_enable": 1 if loader_timed_seed_enable else 0,
            "timed_seed_allow_cache": 1 if loader_timed_seed_allow_cache else 0,
            "loader_done_key": f"snndl_loader_done_pe_{pe_id:02d}",
            "verify_readback_mode": str(loader_verify_mode),
            "verify_readback_samples": int(loader_verify_samples),
            "verify_readback_seed": int(loader_verify_seed),
            "write_pattern_mode": str(loader_write_pattern_mode),
            "write_pattern_row_scale": int(loader_write_pattern_row_scale),
        }

        # Enable write-back readback verification only when it's meaningful:
        # - BCSR mesh runs (raw weight files are available and address mapping is exercised)
        # - Dense microbench correctness runs (deterministic write pattern is enabled)
        #
        # This avoids accidental FAILs when users set loader_verify_readback in a non-BCSR,
        # non-microbench configuration where WeightLoader cannot derive expected bytes.
        if pe_id == 0 and (not gcss_mode) and loader_verify_readback and (
            bool(global_bcsr_available) or (str(loader_write_pattern_mode).strip().lower() == "dense_rowcol_v1")
        ):
            weight_loader_params.update({
                "verify_readback_enable": 1,
                "verify_readback_core": 0,
                "verify_readback_bytes": int(loader_verify_bytes),
                "verify_colidx_start_index": int(loader_verify_colidx_start),
            })

        if pe_id == 0 and (not gcss_mode) and loader_diag_timed_read and global_bcsr_available:
            idx_bytes = int(global_bcsr_offsets.get("idx_bytes", 2) or 2)
            colidx_off = int(global_bcsr_offsets.get("colidx_offset", 0) or 0)
            start = int(loader_diag_timed_read_colidx_start)
            weight_loader_params.update({
                "diag_runtime_read_enable": 1,
                "diag_runtime_read_core": 0,
                "diag_runtime_read_offset": int(colidx_off + start * idx_bytes),
                "diag_runtime_read_bytes": 64,
            })

        if gcss_mode:
            if gcss_premphf_mode:
                if gcss_plp_mode:
                    tmpl = os.path.join(gcssplp_dir, f"pe{pe_id:02d}", "core{core:02d}.gcssplp.bin")
                else:
                    tmpl = os.path.join(gcssvlf_dir, f"pe{pe_id:02d}", "core{core:02d}.gcssvlf.bin")
                weight_loader_params.update({
                    "weight_format": "raw",
                    "per_core_files": 1,
                    "file_template": tmpl,
                    "validate_length": 0,
                    "bcsr_enable": 0,
                })
            elif gcss_idx2_mode:
                tmpl = os.path.join(gcss2_dir, f"pe{pe_id:02d}", "core{core:02d}.gcss2.bin")
                weight_loader_params.update({
                    "weight_format": "raw",
                    "per_core_files": 1,
                    "file_template": tmpl,
                    "validate_length": 0,
                    "bcsr_enable": 0,
                })
            else:
                tmpl = os.path.join(gcss_dir, f"pe{pe_id:02d}", "core{core:02d}.gcss.bin")
                weight_loader_params.update({
                    "weight_format": "raw",
                    "per_core_files": 1,
                    "file_template": tmpl,
                    "validate_length": 0,
                    "bcsr_enable": 0,
                })
        elif global_bcsr_available:
            tmpl = os.path.join(global_bcsr_dir, f"pe{pe_id:02d}", "core{core:02d}.bcsr.bin")
            weight_loader_params.update({
                "weight_format": "raw",
                "per_core_files": 1,
                "file_template": tmpl,
                "validate_length": 0,
                "bcsr_enable": 1,
                "bcsr_block_rows": global_bcsr_offsets.get("br", 1),
                "bcsr_block_cols": global_bcsr_offsets.get("bc", 16),
                "bcsr_idx_bytes": global_bcsr_offsets.get("idx_bytes", 4),
                "bcsr_val_bytes": global_bcsr_offsets.get("val_bytes", 4),
            })

        _add_params_with_overrides(
            weight_loader,
            role="weight_loader",
            component_type="SnnDL.WeightLoader",
            name=f"pe_{pe_id}_weight_loader",
            tags={"pe": int(pe_id)},
            params=weight_loader_params,
            override_engine=override_engine,
            override_report=override_report,
        )
        # WeightLoader stats are useful for separating init traffic from steady-state reads
        # when analyzing memHierarchy controller counters.
        try:
            weight_loader.enableAllStatistics({"type": "sst.AccumulatorStatistic"})
        except Exception:
            pass

        weight_loader_mem = weight_loader.setSubComponent("memory", "memHierarchy.standardInterface")
        _add_params_with_overrides(
            weight_loader_mem,
            role="weight_loader.memory_if",
            component_type="memHierarchy.standardInterface",
            name=f"pe_{pe_id}_weight_loader.memory",
            tags={"pe": int(pe_id)},
            params={},
            override_engine=override_engine,
            override_report=override_report,
        )
        weight_loader_link = sst.Link(f"pe_{pe_id}_weight_loader_to_bus")
        wl_port = f"highlink{num_cores_per_pe}"
        weight_loader_link.connect(
            (weight_loader_mem, "lowlink", "5ns"),
            (mem_bus, wl_port, "5ns"),
        )
        pe_weight_loaders.append(weight_loader)

        if debug_conn:
            mesh_print(f"[BUS-CONN] PE{pe_id} SINGLE-BUS (L1 only)")
            mesh_print("  mem_bus.highlink0..3 <- L1 cores")
            mesh_print("  mem_bus.highlink4 <- WeightLoader")
            mesh_print("  mem_bus.lowlink0 -> MemCtrl.highlink")

    return pe_memory_controllers, pe_memory_buses, pe_weight_loaders, enable_bcsr


def build_shared_memory_system(
    *,
    node_limit: int,
    num_cores_per_pe: int,
    neurons_per_core: int,
    neurons_per_pe: int,
    global_weights_cols: int,
    per_core_weight_stride: int,
    pe_weight_region_stride: int,
    base_addr_global_shift: int,
    pe_mem_addr_range: int,
    mem_backend: str,
    ramulator2_config_file: str,
    simplemem_access_time: str,
    loader_verbose: int,
    loader_chunk_bytes: int,
    loader_timed_seed_enable: bool,
    loader_timed_seed_allow_cache: bool,
    loader_verify_readback: bool,
    loader_verify_bytes: int,
    loader_verify_mode: str,
    loader_verify_samples: int,
    loader_verify_seed: int,
    loader_verify_colidx_start: int,
    loader_diag_timed_read: bool,
    loader_diag_timed_read_colidx_start: int,
    loader_write_pattern_mode: str,
    loader_write_pattern_row_scale: int,
    global_bcsr_available: bool,
    global_bcsr_dir: str,
    gcss_dir: str,
    gcss2_dir: str,
    gcssvlf_dir: str,
    gcssplp_dir: str,
    gcssnt_dir: str,
    global_bcsr_offsets: Dict[str, Any],
    synapse_weight_mode: str,
    debug_conn: bool,
    ramulator2_admission_queue_size: Optional[int] = None,
    ramulator2_admission_issue_budget_per_cycle: Optional[int] = None,
    ramulator2_max_requests_per_cycle: Optional[int] = None,
    override_engine: Optional[OverrideEngine] = None,
    override_report: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Any], List[Any], List[Any], bool]:
    """
    Build a shared (single-controller) memory system for all PEs.

    - One MemController + backend, one Bus
    - Each PE still has its own WeightLoader instance (connected to shared bus)
    - PE cores are connected later in build_mesh_pes_and_nics() via computed bus port indices
    """

    pe_memory_controllers: List[Any] = []
    pe_memory_buses: List[Any] = []
    pe_weight_loaders: List[Any] = []

    enable_bcsr = bool(global_bcsr_available)
    syn_mode = str(synapse_weight_mode or "bcsr_gas").strip().lower()
    if syn_mode == "gscc_valueonly_dstcore":
        syn_mode = "gcss_valueonly_dstcore"
    if syn_mode == "gscc_valueonly_dstcore_vlf_premphf":
        syn_mode = "gcss_valueonly_dstcore_vlf_premphf"
    if syn_mode == "gscc_valueonly_dstcore_vlf_premphf_plp":
        syn_mode = "gcss_valueonly_dstcore_vlf_premphf_plp"
    gcss_mode = syn_mode in (
        "gcss_valueonly_dstcore",
        "gcss_valueonly_dstcore_idx2",
        "gcss_idx2_rowmphf",
        "gcss_valueonly_dstcore_vlf_premphf",
        "gcss_valueonly_dstcore_vlf_premphf_plp",
    )
    gcss_idx2_mode = syn_mode in ("gcss_valueonly_dstcore_idx2", "gcss_idx2_rowmphf")
    gcss_premphf_mode = syn_mode in ("gcss_valueonly_dstcore_vlf_premphf", "gcss_valueonly_dstcore_vlf_premphf_plp")
    gcss_plp_mode = syn_mode == "gcss_valueonly_dstcore_vlf_premphf_plp"

    backend = str(mem_backend or "simple").strip().lower()
    if backend in ("simplemem", "simple_mem"):
        backend = "simple"
    if backend in ("ram2",):
        backend = "ramulator2"
    if backend not in ("simple", "ramulator2"):
        raise RuntimeError(f"invalid mem_backend={backend!r} (expected simple/ramulator2)")

    shared_mem_bytes = int(pe_mem_addr_range) * int(node_limit)
    mem_addr_start = int(base_addr_global_shift)
    mem_addr_end = mem_addr_start + int(shared_mem_bytes) - 1
    mem_ctrl_params = {
        "clock": "1GHz",
        "backing": "malloc",
        "addr_range_start": str(mem_addr_start),
        "addr_range_end": str(mem_addr_end),
    }
    if ramulator2_max_requests_per_cycle is not None:
        mem_ctrl_params["max_requests_per_cycle"] = int(ramulator2_max_requests_per_cycle)

    if backend == "ramulator2":
        cfg_file = str(ramulator2_config_file or "").strip()
        if not cfg_file:
            raise RuntimeError("mem_backend=ramulator2 but ramulator2_config_file is empty")
        if not os.path.exists(cfg_file):
            raise RuntimeError(f"ramulator2_config_file not found: {cfg_file}")
        backend_params = {
            "mem_size": f"{int(shared_mem_bytes)}B",
            "configFile": cfg_file,
            "debug": "0",
            "debug_level": "0",
        }
        if ramulator2_admission_queue_size is not None:
            backend_params["admission_queue_size"] = int(ramulator2_admission_queue_size)
        if ramulator2_admission_issue_budget_per_cycle is not None:
            backend_params["admission_issue_budget_per_cycle"] = int(ramulator2_admission_issue_budget_per_cycle)
        backend_component = "memHierarchy.ramulator2"
    else:
        backend_params = {
            "access_time": str(simplemem_access_time or "100ns"),
            "mem_size": f"{int(shared_mem_bytes)}B",
        }
        backend_component = "memHierarchy.simpleMem"

    if snndl_system is None or not hasattr(snndl_system, "mem_memhierarchy"):
        raise RuntimeError("snndl_system.mem_memhierarchy not available (check import path)")
    mem_builder = snndl_system.mem_memhierarchy
    build_ctrl_fn = getattr(mem_builder, "build_mem_controller_with_backend", None)
    build_bus_fn = getattr(mem_builder, "build_mem_bus", None)
    connect_bus_fn = getattr(mem_builder, "connect_bus_to_mem_controller", None)
    if not callable(build_ctrl_fn):
        raise RuntimeError("snndl_system.mem_memhierarchy.build_mem_controller_with_backend not callable")
    if not callable(build_bus_fn):
        raise RuntimeError("snndl_system.mem_memhierarchy.build_mem_bus not callable")
    if not callable(connect_bus_fn):
        raise RuntimeError("snndl_system.mem_memhierarchy.connect_bus_to_mem_controller not callable")

    ctrl_supports_override = _supports_override(build_ctrl_fn)
    if ctrl_supports_override:
        ctrl_result = _call_with_supported_kwargs(
            build_ctrl_fn,
            name="shared_memory_controller",
            controller_params=dict(mem_ctrl_params),
            backend_type=str(backend_component),
            backend_params=dict(backend_params),
            backend=str(backend),
            mem_size=f"{int(shared_mem_bytes)}B",
            override_engine=override_engine,
            override_report=override_report,
        )
        mem_controller, mem_backend_sc = _unpack_mem_controller_result(ctrl_result)
    else:
        final_ctrl_params, _ = _apply_override_params(
            role="pe_mem_controller",
            component_type="memHierarchy.MemController",
            name="shared_memory_controller",
            tags={"pe": -1, "scope": "shared"},
            params=mem_ctrl_params,
            override_engine=override_engine,
            override_report=override_report,
        )
        final_backend_params, _ = _apply_override_params(
            role="pe_mem_controller.backend",
            component_type=str(backend_component),
            name="shared_memory_controller.backend",
            tags={"pe": -1, "scope": "shared"},
            params=backend_params,
            override_engine=override_engine,
            override_report=override_report,
        )
        ctrl_result = _call_with_supported_kwargs(
            build_ctrl_fn,
            name="shared_memory_controller",
            controller_params=dict(final_ctrl_params),
            backend_type=str(backend_component),
            backend_params=dict(final_backend_params),
            backend=str(backend),
            mem_size=f"{int(shared_mem_bytes)}B",
        )
        mem_controller, mem_backend_sc = _unpack_mem_controller_result(ctrl_result)
        if mem_controller is not None and final_ctrl_params:
            mem_controller.addParams(final_ctrl_params)
        if mem_controller is not None and mem_backend_sc is None:
            mem_backend_sc = mem_controller.setSubComponent("backend", str(backend_component))
        if mem_backend_sc is not None and final_backend_params:
            mem_backend_sc.addParams(final_backend_params)

    if mem_controller is None:
        raise RuntimeError("mem controller builder returned None")

    try:
        mem_controller.enableAllStatistics({"type": "sst.AccumulatorStatistic"})
    except Exception:
        pass
    pe_memory_controllers.append(mem_controller)

    mem_bus_params = {
        "bus_frequency": "1GHz",
        "debug": "0",
        "verbose": "0",
    }
    bus_supports_override = _supports_override(build_bus_fn)
    if bus_supports_override:
        bus_result = _call_with_supported_kwargs(
            build_bus_fn,
            name="shared_memory_bus",
            params=dict(mem_bus_params),
            override_engine=override_engine,
            override_report=override_report,
        )
        mem_bus = _unpack_mem_bus_result(bus_result)
    else:
        final_bus_params, _ = _apply_override_params(
            role="pe_mem_bus",
            component_type="memHierarchy.Bus",
            name="shared_memory_bus",
            tags={"pe": -1, "scope": "shared"},
            params=mem_bus_params,
            override_engine=override_engine,
            override_report=override_report,
        )
        bus_result = _call_with_supported_kwargs(
            build_bus_fn,
            name="shared_memory_bus",
            params=dict(final_bus_params),
        )
        mem_bus = _unpack_mem_bus_result(bus_result)
        if mem_bus is not None and final_bus_params:
            mem_bus.addParams(final_bus_params)
    if mem_bus is None:
        raise RuntimeError("mem bus builder returned None")
    pe_memory_buses.append(mem_bus)

    bus_to_mem_link = _call_with_supported_kwargs(
        connect_bus_fn,
        name="shared_bus_to_mem",
        bus=mem_bus,
        mem_controller=mem_controller,
        link_latency="5ns",
        bus_port="lowlink0",
        mem_port="highlink",
    )
    if bus_to_mem_link is None:
        bus_to_mem_link = _snndl_create_link(mem_builder, name="shared_bus_to_mem")
        bus_to_mem_link.connect(
            (mem_bus, "lowlink0", "5ns"),
            (mem_controller, "highlink", "5ns"),
        )

    ports_per_pe = compute_ports_per_pe_for_synapse_mode(num_cores_per_pe, mesh.get("synapse_weight_mode", "bcsr_gas"))

    for pe_id in range(int(node_limit)):
        pe_weight_base = int(base_addr_global_shift) + int(pe_weight_region_stride) * int(pe_id)
        weight_loader = sst.Component(f"pe_{pe_id}_weight_loader", "SnnDL.WeightLoader")
        weight_loader_params: Dict[str, Any] = {
            "verbose": int(loader_verbose) if pe_id == 0 else 0,
            "node_id": int(pe_id),
            "base_addr_start": pe_weight_base,
            "per_core_stride": int(per_core_weight_stride),
            "num_cores": int(num_cores_per_pe),
            "neurons_per_core": int(neurons_per_core),
            "rows_per_core": int(neurons_per_core),
            "cols_per_core": int(global_weights_cols),
            "total_neurons": int(neurons_per_pe),
            "weight_format": "bin",
            "per_core_files": 0,
            "fill_value": 0.0,
            "validate_length": 1,
            "row_major": 1,
            "chunk_size_bytes": int(loader_chunk_bytes),
            "timed_seed_enable": 1 if loader_timed_seed_enable else 0,
            "timed_seed_allow_cache": 1 if loader_timed_seed_allow_cache else 0,
            "loader_done_key": f"snndl_loader_done_pe_{pe_id:02d}",
            "verify_readback_mode": str(loader_verify_mode),
            "verify_readback_samples": int(loader_verify_samples),
            "verify_readback_seed": int(loader_verify_seed),
            "write_pattern_mode": str(loader_write_pattern_mode),
            "write_pattern_row_scale": int(loader_write_pattern_row_scale),
        }

        if pe_id == 0 and (not gcss_mode) and loader_verify_readback and (
            bool(global_bcsr_available) or (str(loader_write_pattern_mode).strip().lower() == "dense_rowcol_v1")
        ):
            weight_loader_params.update({
                "verify_readback_enable": 1,
                "verify_readback_core": 0,
                "verify_readback_bytes": int(loader_verify_bytes),
                "verify_colidx_start_index": int(loader_verify_colidx_start),
            })

        if pe_id == 0 and (not gcss_mode) and loader_diag_timed_read and global_bcsr_available:
            idx_bytes = int(global_bcsr_offsets.get("idx_bytes", 2) or 2)
            colidx_off = int(global_bcsr_offsets.get("colidx_offset", 0) or 0)
            start = int(loader_diag_timed_read_colidx_start)
            weight_loader_params.update({
                "diag_runtime_read_enable": 1,
                "diag_runtime_read_core": 0,
                "diag_runtime_read_offset": int(colidx_off + start * idx_bytes),
                "diag_runtime_read_bytes": 64,
            })

        if gcss_mode:
            if gcss_premphf_mode:
                if gcss_plp_mode:
                    tmpl = os.path.join(gcssplp_dir, f"pe{pe_id:02d}", "core{core:02d}.gcssplp.bin")
                else:
                    tmpl = os.path.join(gcssvlf_dir, f"pe{pe_id:02d}", "core{core:02d}.gcssvlf.bin")
                weight_loader_params.update({
                    "weight_format": "raw",
                    "per_core_files": 1,
                    "file_template": tmpl,
                    "validate_length": 0,
                    "bcsr_enable": 0,
                })
            elif gcss_idx2_mode:
                tmpl = os.path.join(gcss2_dir, f"pe{pe_id:02d}", "core{core:02d}.gcss2.bin")
                weight_loader_params.update({
                    "weight_format": "raw",
                    "per_core_files": 1,
                    "file_template": tmpl,
                    "validate_length": 0,
                    "bcsr_enable": 0,
                })
            else:
                tmpl = os.path.join(gcss_dir, f"pe{pe_id:02d}", "core{core:02d}.gcss.bin")
                weight_loader_params.update({
                    "weight_format": "raw",
                    "per_core_files": 1,
                    "file_template": tmpl,
                    "validate_length": 0,
                    "bcsr_enable": 0,
                })
        elif global_bcsr_available:
            tmpl = os.path.join(global_bcsr_dir, f"pe{pe_id:02d}", "core{core:02d}.bcsr.bin")
            weight_loader_params.update({
                "weight_format": "raw",
                "per_core_files": 1,
                "file_template": tmpl,
                "validate_length": 0,
                "bcsr_enable": 1,
                "bcsr_block_rows": global_bcsr_offsets.get("br", 1),
                "bcsr_block_cols": global_bcsr_offsets.get("bc", 16),
                "bcsr_idx_bytes": global_bcsr_offsets.get("idx_bytes", 4),
                "bcsr_val_bytes": global_bcsr_offsets.get("val_bytes", 4),
            })

        _add_params_with_overrides(
            weight_loader,
            role="weight_loader",
            component_type="SnnDL.WeightLoader",
            name=f"pe_{pe_id}_weight_loader",
            tags={"pe": int(pe_id)},
            params=weight_loader_params,
            override_engine=override_engine,
            override_report=override_report,
        )
        try:
            weight_loader.enableAllStatistics({"type": "sst.AccumulatorStatistic"})
        except Exception:
            pass

        weight_loader_mem = weight_loader.setSubComponent("memory", "memHierarchy.standardInterface")
        _add_params_with_overrides(
            weight_loader_mem,
            role="weight_loader.memory_if",
            component_type="memHierarchy.standardInterface",
            name=f"pe_{pe_id}_weight_loader.memory",
            tags={"pe": int(pe_id)},
            params={},
            override_engine=override_engine,
            override_report=override_report,
        )
        weight_loader_link = sst.Link(f"pe_{pe_id}_weight_loader_to_shared_bus")
        wl_port = f"highlink{pe_id * ports_per_pe + num_cores_per_pe}"
        weight_loader_link.connect(
            (weight_loader_mem, "lowlink", "5ns"),
            (mem_bus, wl_port, "5ns"),
        )
        pe_weight_loaders.append(weight_loader)

    if debug_conn:
        mesh_print(f"[BUS-CONN] shared bus (ports_per_pe={ports_per_pe})")
        mesh_print("  shared_bus.lowlink0 -> MemCtrl.highlink")

    return pe_memory_controllers, pe_memory_buses, pe_weight_loaders, enable_bcsr


def build_mesh_pes_and_nics(
    *,
    node_limit: int,
    run_output_dir: str,
    weights_dir: str,
    pe_memory_buses: List[Any],
    layers: Dict[str, Any],
    mesh: Dict[str, Any],
    flags: Dict[str, Any],
    mem_layout: Dict[str, Any],
    gas: Dict[str, Any],
    step: Dict[str, Any],
    routing: Dict[str, Any],
    debug: Dict[str, Any],
    global_step_ctrl: Optional[Any],
    override_engine: Optional[OverrideEngine] = None,
    override_report: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Any], List[Any]]:
    nodes: List[Any] = []
    nics: List[Any] = []
    # Record "effective" (post-override) modeling parameters for reproducible analysis.
    # This avoids confusion when local_run_config.json says "auto" but dense overrides force cacheline semantics.
    effective_cfg: Dict[str, Any] = {
        "schema_version": 1,
        # Default modeling assumption for memHierarchy-style runs: cacheline is the unit of traffic.
        # Row-streaming is treated as an explicit alternative architecture mode and must be labeled separately.
        "default_read_granularity": "cacheline",
        "per_core": [],
    }
    if override_engine is not None:
        effective_cfg["overrides"] = override_engine.rules()
    if override_report is not None:
        effective_cfg["overrides_report"] = override_report

    num_cores_per_pe = int(mesh["num_cores_per_pe"])
    neurons_per_core = int(mesh["neurons_per_core"])
    neurons_per_pe = int(mesh["neurons_per_pe"])
    total_nodes = int(mesh["total_nodes"])
    global_weights_cols = int(mesh["global_weights_cols"])
    mesh_rows = int(mesh.get("mesh_rows", mesh.get("rows", 0)) or 0)
    mesh_cols = int(mesh.get("mesh_cols", mesh.get("cols", 0)) or 0)
    if mesh_rows <= 0 or mesh_cols <= 0:
        guess = int(round(math.sqrt(total_nodes))) if total_nodes > 0 else 1
        if guess > 0 and guess * guess == total_nodes:
            mesh_rows = guess
            mesh_cols = guess
        else:
            mesh_rows = max(1, total_nodes)
            mesh_cols = 1

    input_layer = set(int(x) for x in layers.get("input_layer", []))
    hidden_layer_1 = set(int(x) for x in layers.get("hidden_layer_1", []))
    hidden_layer_2 = set(int(x) for x in layers.get("hidden_layer_2", []))
    thresholds = layers.get("thresholds")
    core_tau_mem = float(layers.get("core_tau_mem", 20.0))
    core_t_ref = int(layers.get("core_t_ref", 2) or 2)
    init_default_weight = float(layers.get("init_default_weight", 0.5) or 0.5)

    # Experiment-scoped "read-only freeze" mode (scripts only; no SnnDL changes):
    # - Still fetch weights / exercise memory + NoC
    # - Prevent firing by setting v_thresh very high
    # - Suppress accumulation persistence by setting tau_mem extremely small (strong leak each tick)
    if "readonly_freeze_enable" in flags:
        readonly_enable = bool(flags.get("readonly_freeze_enable", False))
        readonly_v_thresh = float(flags.get("readonly_v_thresh", 1000000000.0) or 1000000000.0)
        readonly_tau_mem = float(flags.get("readonly_tau_mem", 0.001) or 0.001)
    else:
        readonly_env = os.environ.get("MESH_FREEZE_READONLY", "").strip().lower()
        readonly_enable = readonly_env in ("1", "true", "yes", "y", "on")
        readonly_v_thresh = float(os.environ.get("MESH_READONLY_V_THRESH", "1000000000.0") or 1000000000.0)
        readonly_tau_mem = float(os.environ.get("MESH_READONLY_TAU_MEM", "0.001") or 0.001)
    if readonly_enable:
        core_tau_mem = readonly_tau_mem
        effective_cfg["readonly_freeze"] = {
            "enable": True,
            "v_thresh": readonly_v_thresh,
            "tau_mem": readonly_tau_mem,
        }

    global_bcsr_available = bool(mesh.get("global_bcsr_available", False))
    global_bcsr_dir = str(mesh.get("global_bcsr_dir", ""))
    gcss_dir = str(mesh.get("gcss_dir", "") or "")
    gcss2_dir = str(mesh.get("gcss2_dir", "") or "")
    gcssvlf_dir = str(mesh.get("gcssvlf_dir", "") or "")
    gcssplp_dir = str(mesh.get("gcssplp_dir", "") or "")
    gcssnt_dir = str(mesh.get("gcssnt_dir", "") or "")
    global_bcsr_offsets = dict(mesh.get("global_bcsr_offsets", {}) or {})
    enable_bcsr = bool(mesh.get("enable_bcsr", False))

    per_core_weight_stride = int(mem_layout["per_core_weight_stride"])
    pe_weight_region_stride = int(mem_layout["pe_weight_region_stride"])
    base_addr_global_shift = int(mem_layout["base_addr_global_shift"])
    l1_enable = bool(mem_layout.get("l1_enable", False))
    l1_size_str = str(mem_layout.get("l1_size_str", "16KiB"))
    l1_assoc = int(mem_layout.get("l1_assoc", 8))
    l1_line_bytes_str = str(mem_layout.get("l1_line_bytes_str", "64"))
    subcomp_line_bytes = int(mem_layout.get("subcomp_line_bytes", 64))
    effective_cfg["line_size_bytes"] = int(subcomp_line_bytes)
    effective_cfg["mem_backend"] = {
        "backend": str(mem_layout.get("mem_backend", "simple") or "simple"),
        "ramulator2_config_file": str(mem_layout.get("ramulator2_config_file", "") or ""),
        "simplemem_access_time": str(mem_layout.get("simplemem_access_time", "100ns") or "100ns"),
    }
    if "ramulator2_admission_queue_size" in mem_layout:
        effective_cfg["mem_backend"]["ramulator2_admission_queue_size"] = int(
            mem_layout.get("ramulator2_admission_queue_size", 0)
        )
    if "ramulator2_admission_issue_budget_per_cycle" in mem_layout:
        effective_cfg["mem_backend"]["ramulator2_admission_issue_budget_per_cycle"] = int(
            mem_layout.get("ramulator2_admission_issue_budget_per_cycle", -1)
        )
    if "ramulator2_max_requests_per_cycle" in mem_layout:
        effective_cfg["mem_backend"]["ramulator2_max_requests_per_cycle"] = int(
            mem_layout.get("ramulator2_max_requests_per_cycle", -1)
        )
    effective_cfg["memory_system"] = str(mem_layout.get("memory_system", "memhierarchy_per_pe") or "memhierarchy_per_pe")
    noc_type_norm = _normalize_noc_type(mesh.get("noc_type", "merlin_mesh"))
    use_multicast_noc = noc_type_norm == "multicast_mesh"
    effective_cfg["noc_type"] = str(noc_type_norm)
    effective_cfg["router_buffer_size"] = str(mesh.get("router_buffer_size", "4KiB") or "4KiB")
    effective_cfg["nic_buffer_size"] = str(mesh.get("buffer_size", "8KiB") or "8KiB")

    memory_system = str(mem_layout.get("memory_system", "memhierarchy_per_pe") or "memhierarchy_per_pe").strip().lower()
    shared_memory = memory_system in ("memhierarchy_shared", "shared", "shared_bus", "shared-bus")
    shared_bus = pe_memory_buses[0] if shared_memory else None
    ports_per_pe = compute_ports_per_pe_for_synapse_mode(num_cores_per_pe, mesh.get("synapse_weight_mode", "bcsr_gas"))

    def _resolve_bus_and_port(pe_id: int, port_idx: int) -> Tuple[Any, str]:
        bus = shared_bus if shared_memory else pe_memory_buses[pe_id]
        if shared_memory:
            return bus, f"highlink{pe_id * ports_per_pe + port_idx}"
        return bus, f"highlink{port_idx}"

    disable_network = bool(flags.get("disable_network", False))
    export_spike_csv = bool(flags.get("export_spike_csv", False))
    spikes_mesh_csv = str(flags.get("spikes_mesh_csv", ""))
    enable_node_summary = bool(flags.get("enable_node_summary", False))
    enable_test_traffic = bool(flags.get("enable_test_traffic", False))
    event_fallback = bool(flags.get("event_fallback", False))
    diag_fire_log = bool(flags.get("diag_fire_log", False))
    global_step_sync_enable = bool(flags.get("global_step_sync_enable", False))
    sim_stop_ns = int(flags.get("sim_stop_ns", 0))

    exec_mode = str(flags.get("exec_mode", "gas")).strip().lower()
    if exec_mode == "naive_opt":
        exec_mode = "naive_raw"
    if exec_mode not in ("gas", "naive_raw"):
        exec_mode = "gas"
    is_naive = exec_mode.startswith("naive")
    is_gas = exec_mode == "gas"
    effective_cfg["exec_mode"] = str(exec_mode)
    max_steps = int(flags.get("max_steps", 0) or 0)

    def _cfg_int(d: Dict[str, Any], key: str, default: int) -> int:
        if key not in d:
            return int(default)
        try:
            return int(d.get(key))
        except Exception:
            return int(default)

    workload_impl = str(mesh.get("workload_impl", "") or "").strip()
    if not workload_impl:
        workload_impl = os.environ.get("MESH_WORKLOAD_IMPL", "").strip()
    workload_stats_modules = str(mesh.get("workload_stats_modules", "") or "").strip()
    if not workload_stats_modules:
        workload_stats_modules = os.environ.get("MESH_WORKLOAD_STATS_MODULES", "").strip()
    workload_node_params = _extract_workload_node_params(mesh)
    effective_cfg["workload_impl"] = workload_impl or None
    effective_cfg["workload_stats_modules"] = workload_stats_modules or None
    if workload_node_params:
        merge_params_checked(effective_cfg, workload_node_params, ctx="effective.workload.", warn=False)
    pulse_cfg = dict(mesh.get("pulse", {}) or {})
    pulse_enable = 1 if bool(pulse_cfg.get("enable", mesh.get("pulse_enable", 0))) else 0
    pulse_observe_only = 1 if bool(pulse_cfg.get("observe_only", mesh.get("pulse_observe_only", 1))) else 0
    pulse_ingress_enable = 1 if bool(pulse_cfg.get("ingress_enable", mesh.get("pulse_ingress_enable", 1))) else 0
    pulse_agenda_observe_only = 1 if bool(
        pulse_cfg.get("agenda_observe_only", mesh.get("pulse_agenda_observe_only", 1))
    ) else 0
    pulse_harbor_enable = 1 if bool(
        pulse_cfg.get("harbor_enable", mesh.get("pulse_harbor_enable", 0))
    ) else 0
    pulse_descriptor_enable = 1 if bool(
        pulse_cfg.get("descriptor_enable", mesh.get("pulse_descriptor_enable", 0))
    ) else 0
    pulse_descriptor_actual_enable = 1 if bool(
        pulse_cfg.get("descriptor_actual_enable", mesh.get("pulse_descriptor_actual_enable", 0))
    ) else 0
    pulse_experimental_rowdescriptor_ready_join_dedup_enable = 1 if bool(
        pulse_cfg.get(
            "experimental_rowdescriptor_ready_join_dedup_enable",
            mesh.get("pulse_experimental_rowdescriptor_ready_join_dedup_enable", 0),
        )
    ) else 0
    pulse_domain_retire_enable = 1 if bool(
        pulse_cfg.get("domain_retire_enable", mesh.get("pulse_domain_retire_enable", 0))
    ) else 0
    pulse_domain_retire_observe_only = 1 if bool(
        pulse_cfg.get("domain_retire_observe_only", mesh.get("pulse_domain_retire_observe_only", 1))
    ) else 0
    pulse_domain_retire_mode = str(
        pulse_cfg.get("domain_retire_mode", mesh.get("pulse_domain_retire_mode", "per_post")) or "per_post"
    ).strip().lower()
    if pulse_domain_retire_mode not in ("per_post", "descriptor_domain"):
        pulse_domain_retire_mode = "per_post"
    pulse_domain_retire_release_budget = int(
        pulse_cfg.get("domain_retire_release_budget", mesh.get("pulse_domain_retire_release_budget", 0)) or 0
    )
    if pulse_domain_retire_release_budget < 0:
        pulse_domain_retire_release_budget = 0
    pulse_frontier_observe_enable = 1 if bool(
        pulse_cfg.get("frontier_observe_enable", mesh.get("pulse_frontier_observe_enable", 0))
    ) else 0
    pulse_frontier_top_lines = int(
        pulse_cfg.get("frontier_top_lines", mesh.get("pulse_frontier_top_lines", 32)) or 32
    )
    if pulse_frontier_top_lines <= 0:
        pulse_frontier_top_lines = 32
    pulse_metadata_frontier_observe_enable = 1 if bool(
        pulse_cfg.get(
            "metadata_frontier_observe_enable",
            mesh.get("pulse_metadata_frontier_observe_enable", 0),
        )
    ) else 0
    pulse_metadata_frontier_top_items = int(
        pulse_cfg.get(
            "metadata_frontier_top_items",
            mesh.get("pulse_metadata_frontier_top_items", 32),
        )
        or 32
    )
    if pulse_metadata_frontier_top_items <= 0:
        pulse_metadata_frontier_top_items = 32
    pulse_metadata_frontier_band_slots = int(
        pulse_cfg.get(
            "metadata_frontier_band_slots",
            mesh.get("pulse_metadata_frontier_band_slots", 128),
        )
        or 128
    )
    if pulse_metadata_frontier_band_slots <= 0:
        pulse_metadata_frontier_band_slots = 128
    pulse_metadata_seed_enable = 1 if bool(
        pulse_cfg.get("metadata_seed_enable", mesh.get("pulse_metadata_seed_enable", 0))
    ) else 0
    pulse_metadata_seed_top_bases = int(
        pulse_cfg.get("metadata_seed_top_bases", mesh.get("pulse_metadata_seed_top_bases", 32)) or 32
    )
    if pulse_metadata_seed_top_bases <= 0:
        pulse_metadata_seed_top_bases = 32
    pulse_metadata_seed_window_budget = int(
        pulse_cfg.get(
            "metadata_seed_window_budget",
            mesh.get("pulse_metadata_seed_window_budget", 0),
        )
        or 0
    )
    if pulse_metadata_seed_window_budget < 0:
        pulse_metadata_seed_window_budget = 0
    pulse_mfb_preband_seed_enable = 1 if bool(
        pulse_cfg.get("mfb_preband_seed_enable", mesh.get("pulse_mfb_preband_seed_enable", 0))
    ) else 0
    pulse_mfb_preband_top_bands = int(
        pulse_cfg.get("mfb_preband_top_bands", mesh.get("pulse_mfb_preband_top_bands", 32)) or 32
    )
    if pulse_mfb_preband_top_bands <= 0:
        pulse_mfb_preband_top_bands = 32
    pulse_mfb_preband_lines_per_band = int(
        pulse_cfg.get(
            "mfb_preband_lines_per_band",
            mesh.get("pulse_mfb_preband_lines_per_band", 4),
        )
        or 4
    )
    if pulse_mfb_preband_lines_per_band <= 0:
        pulse_mfb_preband_lines_per_band = 4
    pulse_mfb_preband_band_slots = int(
        pulse_cfg.get(
            "mfb_preband_band_slots",
            mesh.get("pulse_mfb_preband_band_slots", 0),
        )
        or 0
    )
    if pulse_mfb_preband_band_slots < 0:
        pulse_mfb_preband_band_slots = 0
    pulse_mfb_preband_window_budget = int(
        pulse_cfg.get(
            "mfb_preband_window_budget",
            mesh.get("pulse_mfb_preband_window_budget", 0),
        )
        or 0
    )
    if pulse_mfb_preband_window_budget < 0:
        pulse_mfb_preband_window_budget = 0
    pulse_mfb_gather_preband_enable = 1 if bool(
        pulse_cfg.get(
            "mfb_gather_preband_enable",
            mesh.get("pulse_mfb_gather_preband_enable", 0),
        )
    ) else 0
    pulse_mfb_gather_barrier_enable = 1 if bool(
        pulse_cfg.get(
            "mfb_gather_barrier_enable",
            mesh.get("pulse_mfb_gather_barrier_enable", 0),
        )
    ) else 0
    pulse_mfb_gather_top_bands = int(
        pulse_cfg.get("mfb_gather_top_bands", mesh.get("pulse_mfb_gather_top_bands", 32)) or 32
    )
    if pulse_mfb_gather_top_bands <= 0:
        pulse_mfb_gather_top_bands = 32
    pulse_mfb_gather_lines_per_band = int(
        pulse_cfg.get(
            "mfb_gather_lines_per_band",
            mesh.get("pulse_mfb_gather_lines_per_band", 4),
        )
        or 4
    )
    if pulse_mfb_gather_lines_per_band <= 0:
        pulse_mfb_gather_lines_per_band = 4
    pulse_mfb_gather_min_consumers = int(
        pulse_cfg.get(
            "mfb_gather_min_consumers",
            mesh.get("pulse_mfb_gather_min_consumers", 2),
        )
        or 2
    )
    if pulse_mfb_gather_min_consumers < 2:
        pulse_mfb_gather_min_consumers = 2
    pulse_mfb_gather_window_budget = int(
        pulse_cfg.get(
            "mfb_gather_window_budget",
            mesh.get("pulse_mfb_gather_window_budget", 0),
        )
        or 0
    )
    if pulse_mfb_gather_window_budget < 0:
        pulse_mfb_gather_window_budget = 0
    pulse_prebase_shared_lookup_enable = 1 if bool(
        pulse_cfg.get(
            "prebase_shared_lookup_enable",
            mesh.get("pulse_prebase_shared_lookup_enable", 0),
        )
    ) else 0
    pulse_osa_enable = 1 if bool(
        pulse_cfg.get("osa_enable", mesh.get("pulse_osa_enable", 0))
    ) else 0
    pulse_osa_shared_weight_owner_enable = 1 if bool(
        pulse_cfg.get(
            "osa_shared_weight_owner_enable",
            mesh.get("pulse_osa_shared_weight_owner_enable", 0),
        )
    ) else 0
    pulse_osa_shared_weight_owner_actual_enable = 1 if bool(
        pulse_cfg.get(
            "osa_shared_weight_owner_actual_enable",
            mesh.get("pulse_osa_shared_weight_owner_actual_enable", 0),
        )
    ) else 0
    pulse_osa_metadata_txn_enable = 1 if bool(
        pulse_cfg.get(
            "osa_metadata_txn_enable",
            mesh.get("pulse_osa_metadata_txn_enable", 0),
        )
    ) else 0
    pulse_osa_metadata_ready_lease_enable = 1 if bool(
        pulse_cfg.get(
            "osa_metadata_ready_lease_enable",
            mesh.get("pulse_osa_metadata_ready_lease_enable", 0),
        )
    ) else 0
    pulse_osa_metadata_ready_lease_ttl = int(
        pulse_cfg.get(
            "osa_metadata_ready_lease_ttl",
            mesh.get("pulse_osa_metadata_ready_lease_ttl", 0),
        ) or 0
    )
    if pulse_osa_metadata_ready_lease_ttl < 0:
        pulse_osa_metadata_ready_lease_ttl = 0
    pulse_osa_metadata_object_mask = str(
        pulse_cfg.get(
            "osa_metadata_object_mask",
            mesh.get("pulse_osa_metadata_object_mask", ""),
        ) or ""
    ).strip().lower()
    pulse_ingress_entries = int(pulse_cfg.get("ingress_entries", mesh.get("pulse_ingress_entries", 0)) or 0)
    if pulse_ingress_entries < 0:
        pulse_ingress_entries = 0
    pulse_core_queue_entries = int(
        pulse_cfg.get("core_queue_entries", mesh.get("pulse_core_queue_entries", 0)) or 0
    )
    if pulse_core_queue_entries < 0:
        pulse_core_queue_entries = 0
    pulse_descriptor_packet_min = int(
        pulse_cfg.get("descriptor_packet_min", mesh.get("pulse_descriptor_packet_min", 2)) or 2
    )
    if pulse_descriptor_packet_min <= 0:
        pulse_descriptor_packet_min = 2
    pulse_bypass_high_watermark_pct = int(
        pulse_cfg.get(
            "bypass_high_watermark_pct",
            mesh.get("pulse_bypass_high_watermark_pct", 100),
        ) or 100
    )
    if pulse_bypass_high_watermark_pct <= 0:
        pulse_bypass_high_watermark_pct = 100
    if pulse_bypass_high_watermark_pct > 100:
        pulse_bypass_high_watermark_pct = 100
    pulse_bypass_mode = str(
        pulse_cfg.get("bypass_mode", mesh.get("pulse_bypass_mode", "disabled")) or "disabled"
    ).strip().lower()
    if pulse_bypass_mode not in ("disabled", "high_watermark"):
        pulse_bypass_mode = "disabled"

    # BCSR optimization level (format stays BCSR; this only gates caching/prefetch/coalesce).
    # Expected values: none/index_only/full. Leave empty to fallback to exec_mode defaults.
    bcsr_opt_level = str(mesh.get("bcsr_opt_level", "") or "").strip().lower()
    if bcsr_opt_level not in ("", "none", "index_only", "full"):
        bcsr_opt_level = ""
    if not bcsr_opt_level:
        bcsr_opt_level = "index_only" if exec_mode == "naive_raw" else "full"

    synapse_weight_mode = _normalize_synapse_weight_mode(mesh.get("synapse_weight_mode", "bcsr_gas"))
    gcss_idx2_mode = synapse_weight_mode in ("gcss_valueonly_dstcore_idx2", "gcss_idx2_rowmphf")
    gcss_premphf_mode = synapse_weight_mode in ("gcss_valueonly_dstcore_vlf_premphf", "gcss_valueonly_dstcore_vlf_premphf_plp")
    gcss_plp_mode = synapse_weight_mode == "gcss_valueonly_dstcore_vlf_premphf_plp"
    experimental_enable = (os.environ.get("MESH_EXPERIMENTAL_ENABLE") or "").strip().lower() in (
        "1", "true", "yes", "y", "on"
    )
    if (gcss_idx2_mode or gcss_premphf_mode) and not experimental_enable:
        raise RuntimeError("synapse_weight_mode=gcss_valueonly_dstcore_idx2/gcss_valueonly_dstcore_vlf_premphf/gcss_valueonly_dstcore_vlf_premphf_plp requires MESH_EXPERIMENTAL_ENABLE=1")
    if synapse_weight_mode in (
        "gcss_valueonly_dstcore",
        "gcss_valueonly_dstcore_idx2",
        "gcss_idx2_rowmphf",
        "gcss_valueonly_dstcore_vlf_premphf",
        "gcss_valueonly_dstcore_vlf_premphf_plp",
    ) and not global_bcsr_available:
        raise RuntimeError("synapse_weight_mode=gcss* requires global_bcsr_available=1 for routing")
    if synapse_weight_mode == "gcss_valueonly_dstcore" and not gcss_dir:
        raise RuntimeError("synapse_weight_mode=gcss_valueonly_dstcore requires mesh.gcss_dir (or MESH_GCSS_DIR)")
    if gcss_idx2_mode and not gcss2_dir:
        raise RuntimeError("synapse_weight_mode=gcss_valueonly_dstcore_idx2 requires mesh.gcss2_dir (or MESH_GCSS2_DIR)")
    if synapse_weight_mode == "gcss_valueonly_dstcore_vlf_premphf" and not gcssvlf_dir:
        raise RuntimeError("synapse_weight_mode=gcss_valueonly_dstcore_vlf_premphf requires mesh.gcssvlf_dir (or MESH_GCSSVLF_DIR)")
    if synapse_weight_mode == "gcss_valueonly_dstcore_vlf_premphf_plp" and not gcssplp_dir:
        raise RuntimeError("synapse_weight_mode=gcss_valueonly_dstcore_vlf_premphf_plp requires mesh.gcssplp_dir (or MESH_GCSSPLP_DIR)")
    gcss_index_template = ""
    if synapse_weight_mode == "gcss_valueonly_dstcore":
        gcss_index_template = os.path.join(gcss_dir, "pe{pe:02d}", "core{core:02d}.gcss.idx.bin")
    elif gcss_premphf_mode:
        if gcss_plp_mode:
            gcss_index_template = os.path.join(gcssplp_dir, "pe{pe:02d}", "core{core:02d}.gcssplp.idx.bin")
        else:
            gcss_index_template = os.path.join(gcssvlf_dir, "pe{pe:02d}", "core{core:02d}.gcssvlf.idx.bin")
    elif gcss_idx2_mode:
        gcss_index_template = os.path.join(gcss2_dir, "pe{pe:02d}", "core{core:02d}.gcss2.idx.bin")
    effective_cfg["synapse_weight_mode"] = synapse_weight_mode
    local_storage_enable = int(mesh.get("local_storage_enable", 0) or 0)
    effective_cfg["local_storage_enable"] = int(local_storage_enable)
    pe_internal_cpe_enable = int(mesh.get("pe_internal_cpe_enable", 0) or 0)
    pe_internal_pod_enable = int(mesh.get("pe_internal_pod_enable", 0) or 0)
    pe_internal_pod_count = int(mesh.get("pe_internal_pod_count", 0) or 0)
    pe_internal_pod_size = int(mesh.get("pe_internal_pod_size", 0) or 0)
    pe_internal_pod_metadata_enable = int(mesh.get("pe_internal_pod_metadata_enable", 0) or 0)
    pe_internal_pod_owner_enable = int(mesh.get("pe_internal_pod_owner_enable", 0) or 0)
    pe_internal_pod_join_enable = int(mesh.get("pe_internal_pod_join_enable", 0) or 0)
    pe_internal_pod_ready_enable = int(mesh.get("pe_internal_pod_ready_enable", 0) or 0)
    pe_internal_pod_owner_entries = int(mesh.get("pe_internal_pod_owner_entries", 0) or 0)
    pe_internal_pod_join_entries = int(mesh.get("pe_internal_pod_join_entries", 0) or 0)
    pe_internal_pod_ready_entries = int(mesh.get("pe_internal_pod_ready_entries", 0) or 0)
    effective_cfg["pe_internal_cpe_enable"] = int(pe_internal_cpe_enable)
    effective_cfg["pe_internal_pod_enable"] = int(pe_internal_pod_enable)
    effective_cfg["pe_internal_pod_count"] = int(pe_internal_pod_count)
    effective_cfg["pe_internal_pod_size"] = int(pe_internal_pod_size)
    effective_cfg["pe_internal_pod_metadata_enable"] = int(pe_internal_pod_metadata_enable)
    effective_cfg["pe_internal_pod_owner_enable"] = int(pe_internal_pod_owner_enable)
    effective_cfg["pe_internal_pod_join_enable"] = int(pe_internal_pod_join_enable)
    effective_cfg["pe_internal_pod_ready_enable"] = int(pe_internal_pod_ready_enable)
    effective_cfg["pe_internal_pod_owner_entries"] = int(pe_internal_pod_owner_entries)
    effective_cfg["pe_internal_pod_join_entries"] = int(pe_internal_pod_join_entries)
    effective_cfg["pe_internal_pod_ready_entries"] = int(pe_internal_pod_ready_entries)
    if gcss_dir:
        effective_cfg["gcss_dir"] = gcss_dir
    if gcss2_dir:
        effective_cfg["gcss2_dir"] = gcss2_dir
    if gcssvlf_dir:
        effective_cfg["gcssvlf_dir"] = gcssvlf_dir
    if gcssplp_dir:
        effective_cfg["gcssplp_dir"] = gcssplp_dir
    sram_cfg = dict(mesh.get("sram", {}) or {})
    sram_weight_cfg = dict(sram_cfg.get("weight", {}) or {})
    sram_state_cfg = dict(sram_cfg.get("state", {}) or {})
    sram_calib_meta = dict(sram_cfg.get("calib_meta", {}) or {})
    sram_model_enable = 1 if bool(sram_cfg.get("model_enable", 0)) else 0
    sram_weight_idx_enable = 1 if bool(sram_weight_cfg.get("idx_enable", 0)) else 0
    sram_weight_l0_enable = 1 if bool(sram_weight_cfg.get("l0_enable", 0)) else 0
    sram_state_enable = 1 if bool(sram_state_cfg.get("enable", 0)) else 0
    sram_weight_idx_capacity_bytes = int(sram_weight_cfg.get("idx_capacity_bytes", 0) or 0)
    sram_weight_l0_capacity_bytes = int(sram_weight_cfg.get("l0_capacity_bytes", 0) or 0)
    sram_weight_idx_banks = int(sram_weight_cfg.get("idx_banks", 16) or 16)
    sram_weight_l0_banks = int(sram_weight_cfg.get("l0_banks", 8) or 8)
    sram_weight_ports_per_bank = int(sram_weight_cfg.get("ports_per_bank", 1) or 1)
    sram_weight_bank_interleave_bytes = int(sram_weight_cfg.get("bank_interleave_bytes", 4) or 4)
    sram_weight_t_read_cycles = int(sram_weight_cfg.get("t_read_cycles", 1) or 1)
    sram_weight_t_write_cycles = int(sram_weight_cfg.get("t_write_cycles", 1) or 1)
    sram_weight_sample_log2 = int(sram_weight_cfg.get("sample_log2", 0) or 0)
    sram_weight_idx_base = int(sram_weight_cfg.get("idx_base", 0x100000000) or 0x100000000)
    sram_weight_l0_base = int(sram_weight_cfg.get("l0_base", 0x200000000) or 0x200000000)
    sram_weight_l0_slots = int(sram_weight_cfg.get("l0_slots", 1 << 20) or (1 << 20))
    sram_state_capacity_bytes = int(sram_state_cfg.get("capacity_bytes", 0) or 0)
    sram_state_banks = int(sram_state_cfg.get("banks", 16) or 16)
    sram_state_ports_per_bank = int(sram_state_cfg.get("ports_per_bank", 1) or 1)
    sram_state_bank_interleave_bytes = int(sram_state_cfg.get("bank_interleave_bytes", 4) or 4)
    sram_state_t_read_cycles = int(sram_state_cfg.get("t_read_cycles", 1) or 1)
    sram_state_t_write_cycles = int(sram_state_cfg.get("t_write_cycles", 1) or 1)
    sram_state_sample_log2 = int(sram_state_cfg.get("sample_log2", 0) or 0)
    sram_state_vmem_base = int(sram_state_cfg.get("vmem_base", 0x300000000) or 0x300000000)
    sram_state_refrac_base = int(sram_state_cfg.get("refrac_base", 0x400000000) or 0x400000000)
    sram_state_last_spike_base = int(sram_state_cfg.get("last_spike_base", 0x500000000) or 0x500000000)
    effective_cfg["thermal"] = make_effective_thermal_config(mesh=mesh)
    sram_provenance = make_effective_sram_provenance(mesh=mesh, final_pe_core_params=None)
    effective_cfg["sram"] = dict(sram_provenance["structured"])
    effective_cfg["sram_effective_pe_core"] = dict(sram_provenance["effective"])
    effective_cfg["sram_calib_meta"] = dict(sram_provenance["calib_meta"])

    record_edge_apply_enable = 1 if bool(flags.get("record_edge_apply_enable", 1)) else 0
    record_edge_idle_enable = 1 if bool(flags.get("record_edge_idle_enable", 1)) else 0
    record_edge_scatter_enable = 1 if bool(flags.get("record_edge_scatter_enable", 1)) else 0
    spikekey_fastpath_enable = 1 if bool(flags.get("experimental_spikekey_fastpath_enable", 0)) else 0
    spikekey_fastpath_env = (os.environ.get("MESH_EXPERIMENTAL_SPIKEKEY_FASTPATH_ENABLE") or "").strip().lower()
    if spikekey_fastpath_env:
        spikekey_fastpath_enable = 1 if spikekey_fastpath_env in ("1", "true", "yes", "y", "on") else 0
    # GatherBufferIF step-gate progress watchdog (diagnostic-only; default OFF).
    gbi_stepgate_progress_enable = (os.environ.get("MESH_GBI_STEPGATE_PROGRESS_ENABLE") or "").strip().lower() in (
        "1", "true", "yes", "y", "on"
    )
    try:
        gbi_stepgate_progress_period_cycles = int(os.environ.get("MESH_GBI_STEPGATE_PROGRESS_PERIOD_CYCLES", "0") or 0)
    except Exception:
        gbi_stepgate_progress_period_cycles = 0
    try:
        gbi_stepgate_progress_max_reports = int(os.environ.get("MESH_GBI_STEPGATE_PROGRESS_MAX_REPORTS", "0") or 0)
    except Exception:
        gbi_stepgate_progress_max_reports = 0
    try:
        gbi_stepgate_progress_owner_node = int(os.environ.get("MESH_GBI_STEPGATE_PROGRESS_OWNER_NODE", "-1") or -1)
    except Exception:
        gbi_stepgate_progress_owner_node = -1
    try:
        gbi_stepgate_progress_owner_core = int(os.environ.get("MESH_GBI_STEPGATE_PROGRESS_OWNER_CORE", "-1") or -1)
    except Exception:
        gbi_stepgate_progress_owner_core = -1
    try:
        gbi_stepgate_apply_finish_poll_period_cycles = int(
            os.environ.get("MESH_GBI_STEPGATE_APPLY_FINISH_POLL_PERIOD_CYCLES", "1") or 1
        )
    except Exception:
        gbi_stepgate_apply_finish_poll_period_cycles = 1
    if gbi_stepgate_apply_finish_poll_period_cycles <= 0:
        gbi_stepgate_apply_finish_poll_period_cycles = 1
    gbi_verbose_override: Optional[int] = None
    _gbi_verbose_raw = (os.environ.get("MESH_GBI_VERBOSE") or "").strip()
    if _gbi_verbose_raw:
        try:
            gbi_verbose_override = int(_gbi_verbose_raw)
        except Exception:
            gbi_verbose_override = None
    try:
        gbi_verbose_owner_node = int(os.environ.get("MESH_GBI_VERBOSE_OWNER_NODE", "-1") or -1)
    except Exception:
        gbi_verbose_owner_node = -1
    try:
        gbi_verbose_owner_core = int(os.environ.get("MESH_GBI_VERBOSE_OWNER_CORE", "-1") or -1)
    except Exception:
        gbi_verbose_owner_core = -1

    use_soa_state = 1 if bool(flags.get("use_soa_state", 0)) else 0
    use_aosoa_state = 1 if bool(flags.get("use_aosoa_state", 0)) else 0
    aosoa_block_rows = int(flags.get("aosoa_block_rows", 16))
    verify_cluster_enable = 1 if bool(flags.get("verify_cluster_enable", 0)) else 0

    network_bandwidth = str(mesh["network_bandwidth"])
    buffer_size = str(mesh["buffer_size"])
    multicast_enable = 1 if bool(mesh.get("multicast_enable", False)) else 0
    multicast_block_w = int(mesh.get("multicast_block_w", 2) or 2)
    multicast_block_h = int(mesh.get("multicast_block_h", 2) or 2)
    multicast_ingress_policy = str(mesh.get("multicast_ingress_policy", "top_left") or "top_left")
    multicast_inter_policy = str(mesh.get("multicast_inter_policy", "xy") or "xy")
    multicast_intra_policy = str(mesh.get("multicast_intra_policy", "manhattan_x_first") or "manhattan_x_first")
    local_endpoint_multicast_enable = 1 if bool(mesh.get("local_endpoint_multicast_enable", False)) else 0
    effective_cfg["noc_multicast"] = {
        "enable": int(multicast_enable),
        "block_w": int(multicast_block_w),
        "block_h": int(multicast_block_h),
        "ingress_policy": str(multicast_ingress_policy),
        "inter_policy": str(multicast_inter_policy),
        "intra_policy": str(multicast_intra_policy),
        "local_endpoint_multicast_enable": int(local_endpoint_multicast_enable),
    }

    core_memory_warmup_cycles = int(mesh.get("core_memory_warmup_cycles", 200))
    core_loader_barrier_cycles = int(mesh.get("core_loader_barrier_cycles", 0))
    force_dense = bool(mesh.get("force_dense", False))
    verify_routing = bool(mesh.get("verify_routing", False))
    effective_cfg["force_dense"] = bool(force_dense)

    gas_window_cycles = dict(gas.get("window_cycles", {}) or {})
    gas_merge_policy = str(gas.get("merge_policy", "auto"))
    gas_gap_k_bytes = int(gas.get("gap_k_bytes", 2048))
    gas_lmax_bytes = int(gas.get("lmax_bytes", 65536))
    gas_max_inflight = int(gas.get("max_inflight", 128))
    gas_sort_policy = str(gas.get("sort_policy", "row") or "row").strip().lower()
    if gas_sort_policy not in ("addr", "row", "bank_row"):
        gas_sort_policy = "row"
    gas_row_bytes_guess = _cfg_int(gas, "row_bytes_guess", 8192)
    if gas_row_bytes_guess <= 0:
        gas_row_bytes_guess = 8192
    gas_bank_bits = _cfg_int(gas, "bank_bits", 0)
    if gas_bank_bits < 0:
        gas_bank_bits = 0
    gas_bank_shift = _cfg_int(gas, "bank_shift", 0)
    if gas_bank_shift < 0:
        gas_bank_shift = 0
    gas_bank_auto_enable = 1 if bool(gas.get("bank_auto_enable", 1)) else 0
    # naive_raw baseline uses a cacheline fragmenter memory front-end. A too-low inflight cap (e.g. 128)
    # can artificially serialize the baseline and explode wallclock. Default to a larger cap to mimic
    # memHierarchy.standardInterface behavior (many outstanding reads), while still keeping a hard bound.
    naive_max_inflight_reads = int(mesh.get("naive_max_inflight_reads", 4096))
    gas_row_window_bytes = int(gas.get("row_window_bytes", 0))
    gas_row_window_timeout_ns = int(gas.get("row_window_timeout_ns", 0))
    gas_vlf_enable = 1 if bool(gas.get("vlf_enable", 0)) else 0
    gas_vlf_run_enable = 1 if bool(gas.get("vlf_run_enable", 0)) else 0
    gas_apply_issue_policy = str(gas.get("apply_issue_policy", "order") or "order").strip().lower()
    if gas_apply_issue_policy not in ("order",):
        gas_apply_issue_policy = "order"
    gas_experimental_retire_policy = str(
        os.environ.get(
            "MESH_GAS_EXPERIMENTAL_RETIRE_POLICY",
            str(gas.get("experimental_retire_policy", "global_inorder") or "global_inorder"),
        )
    ).strip().lower()
    if gas_experimental_retire_policy not in ("global_inorder", "per_post"):
        gas_experimental_retire_policy = "global_inorder"
    effective_retire_policy = gas_experimental_retire_policy
    if (
        pulse_domain_retire_enable == 1
        and pulse_domain_retire_observe_only == 0
        and pulse_domain_retire_mode == "per_post"
    ):
        effective_retire_policy = "per_post"
    gas_experimental_gcss_phase_breakdown_enable = (
        1 if bool(gas.get("experimental_gcss_phase_breakdown_enable", 0)) else 0
    )
    gas_experimental_retire_shadow_per_post_enable = (
        1 if bool(gas.get("experimental_retire_shadow_per_post_enable", 0)) else 0
    )
    gas_experimental_gcss_vlf_queue_policy = str(
        gas.get("experimental_gcss_vlf_queue_policy", "locality_first") or "locality_first"
    ).strip().lower()
    if gas_experimental_gcss_vlf_queue_policy not in ("locality_first", "banded_line_fair"):
        gas_experimental_gcss_vlf_queue_policy = "locality_first"
    gas_experimental_gcss_vlf_fair_band_size = int(
        gas.get("experimental_gcss_vlf_fair_band_size", 256) or 256
    )
    if gas_experimental_gcss_vlf_fair_band_size < 1:
        gas_experimental_gcss_vlf_fair_band_size = 1
    gas_experimental_gcss_vlf_bounded_rescue_enable = (
        1 if bool(gas.get("experimental_gcss_vlf_bounded_rescue_enable", 0)) else 0
    )
    gas_experimental_gcss_vlf_bounded_rescue_scan_limit = int(
        gas.get("experimental_gcss_vlf_bounded_rescue_scan_limit", 8) or 8
    )
    if gas_experimental_gcss_vlf_bounded_rescue_scan_limit < 0:
        gas_experimental_gcss_vlf_bounded_rescue_scan_limit = 0
    gas_experimental_gcss_vlf_bounded_rescue_head_wait_cycles = int(
        gas.get("experimental_gcss_vlf_bounded_rescue_head_wait_cycles", 64) or 64
    )
    if gas_experimental_gcss_vlf_bounded_rescue_head_wait_cycles < 0:
        gas_experimental_gcss_vlf_bounded_rescue_head_wait_cycles = 0
    gas_experimental_gcss_vlf_bounded_rescue_depth_threshold = int(
        gas.get("experimental_gcss_vlf_bounded_rescue_depth_threshold", 3) or 3
    )
    if gas_experimental_gcss_vlf_bounded_rescue_depth_threshold < 0:
        gas_experimental_gcss_vlf_bounded_rescue_depth_threshold = 0
    gas_apply_frags_per_issue = int(gas.get("apply_frags_per_issue", 1))
    if gas_apply_frags_per_issue < 0:
        gas_apply_frags_per_issue = 1
    gas_apply_bank_credit = int(gas.get("apply_bank_credit", 1))
    if gas_apply_bank_credit < 0:
        gas_apply_bank_credit = 1
    gas_apply_age_fair_ns = int(gas.get("apply_age_fair_ns", 2000))
    if gas_apply_age_fair_ns < 0:
        gas_apply_age_fair_ns = 0
    # Experimental: DRAM command-cost guided merge guardrails (segment-build stage; default OFF).
    gas_dram_cmd_cost_merge_enable = 1 if bool(gas.get("dram_cmd_cost_merge_enable", 0)) else 0
    gas_dram_cmd_t_row_hit_ns = int(gas.get("dram_cmd_t_row_hit_ns", 30) or 30)
    if gas_dram_cmd_t_row_hit_ns <= 0:
        gas_dram_cmd_t_row_hit_ns = 1
    gas_dram_cmd_t_row_miss_ns = int(gas.get("dram_cmd_t_row_miss_ns", 120) or 120)
    if gas_dram_cmd_t_row_miss_ns < gas_dram_cmd_t_row_hit_ns:
        gas_dram_cmd_t_row_miss_ns = gas_dram_cmd_t_row_hit_ns
    gas_dram_cmd_t_row_hit_explicit = 1 if bool(gas.get("dram_cmd_t_row_hit_explicit", 0)) else 0
    gas_dram_cmd_t_row_miss_explicit = 1 if bool(gas.get("dram_cmd_t_row_miss_explicit", 0)) else 0
    gas_dram_cmd_offline_model_enable = 1 if bool(gas.get("dram_cmd_offline_model_enable", 0)) else 0
    gas_dram_cmd_offline_model_strict = 1 if bool(gas.get("dram_cmd_offline_model_strict", 0)) else 0

    mem_backend_kind = str(mem_layout.get("mem_backend", "simple") or "simple").strip().lower()
    ramulator2_cfg_file = str(mem_layout.get("ramulator2_config_file", "") or "").strip()
    dram_cmd_offline_meta: Dict[str, Any] = {
        "enabled": int(gas_dram_cmd_offline_model_enable),
        "strict": int(gas_dram_cmd_offline_model_strict),
        "applied": 0,
        "reason": "disabled",
    }
    if gas_dram_cmd_offline_model_enable:
        if gas_dram_cmd_cost_merge_enable != 1:
            dram_cmd_offline_meta["reason"] = "cmd_cost_merge_disabled"
        elif mem_backend_kind != "ramulator2":
            dram_cmd_offline_meta["reason"] = f"mem_backend_{mem_backend_kind}_not_ramulator2"
        elif gas_dram_cmd_t_row_hit_explicit or gas_dram_cmd_t_row_miss_explicit:
            dram_cmd_offline_meta["reason"] = "manual_t_row_explicit"
        elif not ramulator2_cfg_file:
            dram_cmd_offline_meta["reason"] = "ramulator2_config_file_empty"
        else:
            try:
                derived = derive_dram_cmd_cost_from_ramulator2_cfg(
                    ramulator2_cfg_file=ramulator2_cfg_file,
                    line_bytes=int(subcomp_line_bytes),
                )
                derived_cmd = dict(derived.get("derived_cmd_cost", {}) or {})
                d_hit = int(derived_cmd.get("t_row_hit_ns", gas_dram_cmd_t_row_hit_ns) or gas_dram_cmd_t_row_hit_ns)
                d_miss = int(derived_cmd.get("t_row_miss_ns", gas_dram_cmd_t_row_miss_ns) or gas_dram_cmd_t_row_miss_ns)
                if d_hit <= 0:
                    d_hit = 1
                if d_miss < d_hit:
                    d_miss = d_hit
                gas_dram_cmd_t_row_hit_ns = int(d_hit)
                gas_dram_cmd_t_row_miss_ns = int(d_miss)
                dram_cmd_offline_meta["applied"] = 1
                dram_cmd_offline_meta["reason"] = "applied"
                dram_cmd_offline_meta["derived"] = derived
            except Exception as e:
                dram_cmd_offline_meta["reason"] = f"derive_failed: {e}"
    if gas_dram_cmd_offline_model_enable and gas_dram_cmd_offline_model_strict and int(dram_cmd_offline_meta.get("applied", 0)) != 1:
        raise RuntimeError(
            "dram cmd offline model strict mode failed: "
            f"{dram_cmd_offline_meta.get('reason', 'unknown')}"
        )
    gcssplp_profile_export_enable = int(mesh.get("gcssplp_profile_export_enable", 0) or 0)
    gcssplp_profile_export_dir = str(mesh.get("gcssplp_profile_export_dir", "") or "")
    if gcssplp_profile_export_enable and not gcssplp_profile_export_dir:
        gcssplp_profile_export_dir = os.path.join(str(run_output_dir), "gcssplp_profiles")
    if gcssplp_profile_export_enable and gcssplp_profile_export_dir:
        os.makedirs(gcssplp_profile_export_dir, exist_ok=True)
        for pe_id in range(int(node_limit)):
            os.makedirs(os.path.join(gcssplp_profile_export_dir, f"pe{pe_id:02d}"), exist_ok=True)
    experimental_idx2_ingress_prefetch_enable = 1 if bool(
        mesh.get("experimental_idx2_ingress_prefetch_enable", 0)
    ) else 0
    experimental_idx2_ingress_prefetch_budget_per_tick = int(
        mesh.get("experimental_idx2_ingress_prefetch_budget_per_tick", 4) or 4
    )
    if experimental_idx2_ingress_prefetch_budget_per_tick < 1:
        experimental_idx2_ingress_prefetch_budget_per_tick = 1
    experimental_idx2_ingress_prefetch_cache_entries = int(
        mesh.get("experimental_idx2_ingress_prefetch_cache_entries", 4096) or 4096
    )
    if experimental_idx2_ingress_prefetch_cache_entries < 1:
        experimental_idx2_ingress_prefetch_cache_entries = 1
    experimental_idx2_ingress_prefetch_max_inflight = int(
        mesh.get("experimental_idx2_ingress_prefetch_max_inflight", 0) or 0
    )
    if experimental_idx2_ingress_prefetch_max_inflight < 0:
        experimental_idx2_ingress_prefetch_max_inflight = 0
    experimental_idx2_ingress_prefetch_gather_only = 1 if bool(
        mesh.get("experimental_idx2_ingress_prefetch_gather_only", 1)
    ) else 0
    experimental_idx2_ingress_prefetch_carry_to_apply_enable = 1 if bool(
        mesh.get("experimental_idx2_ingress_prefetch_carry_to_apply_enable", 0)
    ) else 0
    experimental_idx2_ingress_prefetch_apply_max_inflight = int(
        mesh.get("experimental_idx2_ingress_prefetch_apply_max_inflight", 0) or 0
    )
    if experimental_idx2_ingress_prefetch_apply_max_inflight < 0:
        experimental_idx2_ingress_prefetch_apply_max_inflight = 0
    experimental_idx2_ingress_prefetch_apply_outstanding_reserve = int(
        mesh.get("experimental_idx2_ingress_prefetch_apply_outstanding_reserve", 0) or 0
    )
    if experimental_idx2_ingress_prefetch_apply_outstanding_reserve < 0:
        experimental_idx2_ingress_prefetch_apply_outstanding_reserve = 0
    experimental_idx2_ingress_prefetch_apply_frontier_keep_pending = int(
        mesh.get("experimental_idx2_ingress_prefetch_apply_frontier_keep_pending", 0) or 0
    )
    if experimental_idx2_ingress_prefetch_apply_frontier_keep_pending < 0:
        experimental_idx2_ingress_prefetch_apply_frontier_keep_pending = 0
    experimental_idx2_ingress_tail_guard_enable = 1 if bool(
        mesh.get("experimental_idx2_ingress_tail_guard_enable", 0)
    ) else 0
    experimental_idx2_ingress_budget_adapt_enable = 1 if bool(
        mesh.get("experimental_idx2_ingress_budget_adapt_enable", 0)
    ) else 0
    experimental_idx2_ingress_budget_adapt_max_per_tick = int(
        mesh.get("experimental_idx2_ingress_budget_adapt_max_per_tick", 32) or 32
    )
    if experimental_idx2_ingress_budget_adapt_max_per_tick < 1:
        experimental_idx2_ingress_budget_adapt_max_per_tick = 1
    experimental_idx2_ingress_budget_adapt_q_depth = int(
        mesh.get("experimental_idx2_ingress_budget_adapt_q_depth", 16) or 16
    )
    if experimental_idx2_ingress_budget_adapt_q_depth < 1:
        experimental_idx2_ingress_budget_adapt_q_depth = 1
    experimental_noc_rowidx_prefetch_enable = 1 if bool(
        mesh.get("experimental_noc_rowidx_prefetch_enable", 0)
    ) else 0
    experimental_noc_rowidx_prefetch_budget_per_tick = int(
        mesh.get("experimental_noc_rowidx_prefetch_budget_per_tick", 4) or 4
    )
    if experimental_noc_rowidx_prefetch_budget_per_tick < 1:
        experimental_noc_rowidx_prefetch_budget_per_tick = 1
    experimental_noc_rowidx_cache_rows = int(
        mesh.get("experimental_noc_rowidx_cache_rows", 1024) or 1024
    )
    if experimental_noc_rowidx_cache_rows < 1:
        experimental_noc_rowidx_cache_rows = 1
    experimental_noc_rowidx_prefetch_gather_only = 1 if bool(
        mesh.get("experimental_noc_rowidx_prefetch_gather_only", 1)
    ) else 0
    experimental_noc_rowidx_prefetch_detached_enable = 1 if bool(
        mesh.get("experimental_noc_rowidx_prefetch_detached_enable", 0)
    ) else 0
    experimental_noc_rowidx_prefetch_carry_to_apply_enable = 1 if bool(
        mesh.get("experimental_noc_rowidx_prefetch_carry_to_apply_enable", 0)
    ) else 0
    experimental_noc_rowidx_hot_touch_min = int(
        mesh.get("experimental_noc_rowidx_hot_touch_min", 1) or 1
    )
    if experimental_noc_rowidx_hot_touch_min < 1:
        experimental_noc_rowidx_hot_touch_min = 1
    experimental_noc_rowidx_budget_adapt_enable = 1 if bool(
        mesh.get("experimental_noc_rowidx_budget_adapt_enable", 0)
    ) else 0
    experimental_noc_rowidx_budget_adapt_max_per_tick = int(
        mesh.get("experimental_noc_rowidx_budget_adapt_max_per_tick", 32) or 32
    )
    if experimental_noc_rowidx_budget_adapt_max_per_tick < 1:
        experimental_noc_rowidx_budget_adapt_max_per_tick = 1
    experimental_noc_rowidx_budget_adapt_q_depth = int(
        mesh.get("experimental_noc_rowidx_budget_adapt_q_depth", 16) or 16
    )
    if experimental_noc_rowidx_budget_adapt_q_depth < 1:
        experimental_noc_rowidx_budget_adapt_q_depth = 1

    # Legacyopt cleanup: keep ineffective exploration branches disabled, but
    # preserve the OSA metadata transaction surface when it is explicitly
    # modeled by the mesh spec/runtime chain.
    pulse_cleanup = apply_mainline_pulse_cleanup(
        {
            "domain_retire_enable": pulse_domain_retire_enable,
            "domain_retire_observe_only": pulse_domain_retire_observe_only,
            "domain_retire_mode": pulse_domain_retire_mode,
            "domain_retire_release_budget": pulse_domain_retire_release_budget,
            "metadata_frontier_observe_enable": pulse_metadata_frontier_observe_enable,
            "metadata_frontier_top_items": pulse_metadata_frontier_top_items,
            "metadata_frontier_band_slots": pulse_metadata_frontier_band_slots,
            "metadata_seed_enable": pulse_metadata_seed_enable,
            "metadata_seed_top_bases": pulse_metadata_seed_top_bases,
            "metadata_seed_window_budget": pulse_metadata_seed_window_budget,
            "mfb_preband_seed_enable": pulse_mfb_preband_seed_enable,
            "mfb_preband_top_bands": pulse_mfb_preband_top_bands,
            "mfb_preband_lines_per_band": pulse_mfb_preband_lines_per_band,
            "mfb_preband_band_slots": pulse_mfb_preband_band_slots,
            "mfb_preband_window_budget": pulse_mfb_preband_window_budget,
            "mfb_gather_preband_enable": pulse_mfb_gather_preband_enable,
            "mfb_gather_barrier_enable": pulse_mfb_gather_barrier_enable,
            "mfb_gather_top_bands": pulse_mfb_gather_top_bands,
            "mfb_gather_lines_per_band": pulse_mfb_gather_lines_per_band,
            "mfb_gather_min_consumers": pulse_mfb_gather_min_consumers,
            "mfb_gather_window_budget": pulse_mfb_gather_window_budget,
            "osa_metadata_txn_enable": pulse_osa_metadata_txn_enable,
            "osa_metadata_ready_lease_enable": pulse_osa_metadata_ready_lease_enable,
            "osa_metadata_ready_lease_ttl": pulse_osa_metadata_ready_lease_ttl,
            "osa_metadata_object_mask": pulse_osa_metadata_object_mask,
        }
    )
    pulse_domain_retire_enable = int(pulse_cleanup["domain_retire_enable"])
    pulse_domain_retire_observe_only = int(pulse_cleanup["domain_retire_observe_only"])
    pulse_domain_retire_mode = str(pulse_cleanup["domain_retire_mode"])
    pulse_domain_retire_release_budget = int(pulse_cleanup["domain_retire_release_budget"])
    pulse_metadata_frontier_observe_enable = int(pulse_cleanup["metadata_frontier_observe_enable"])
    pulse_metadata_frontier_top_items = int(pulse_cleanup["metadata_frontier_top_items"])
    pulse_metadata_frontier_band_slots = int(pulse_cleanup["metadata_frontier_band_slots"])
    pulse_metadata_seed_enable = int(pulse_cleanup["metadata_seed_enable"])
    pulse_metadata_seed_top_bases = int(pulse_cleanup["metadata_seed_top_bases"])
    pulse_metadata_seed_window_budget = int(pulse_cleanup["metadata_seed_window_budget"])
    pulse_mfb_preband_seed_enable = int(pulse_cleanup["mfb_preband_seed_enable"])
    pulse_mfb_preband_top_bands = int(pulse_cleanup["mfb_preband_top_bands"])
    pulse_mfb_preband_lines_per_band = int(pulse_cleanup["mfb_preband_lines_per_band"])
    pulse_mfb_preband_band_slots = int(pulse_cleanup["mfb_preband_band_slots"])
    pulse_mfb_preband_window_budget = int(pulse_cleanup["mfb_preband_window_budget"])
    pulse_mfb_gather_preband_enable = int(pulse_cleanup["mfb_gather_preband_enable"])
    pulse_mfb_gather_barrier_enable = int(pulse_cleanup["mfb_gather_barrier_enable"])
    pulse_mfb_gather_top_bands = int(pulse_cleanup["mfb_gather_top_bands"])
    pulse_mfb_gather_lines_per_band = int(pulse_cleanup["mfb_gather_lines_per_band"])
    pulse_mfb_gather_min_consumers = int(pulse_cleanup["mfb_gather_min_consumers"])
    pulse_mfb_gather_window_budget = int(pulse_cleanup["mfb_gather_window_budget"])
    pulse_osa_metadata_txn_enable = int(pulse_cleanup["osa_metadata_txn_enable"])
    pulse_osa_metadata_ready_lease_enable = int(pulse_cleanup["osa_metadata_ready_lease_enable"])
    pulse_osa_metadata_ready_lease_ttl = int(pulse_cleanup["osa_metadata_ready_lease_ttl"])
    pulse_osa_metadata_object_mask = str(pulse_cleanup["osa_metadata_object_mask"])
    gas_experimental_retire_shadow_per_post_enable = 0
    experimental_idx2_ingress_prefetch_enable = 0
    experimental_idx2_ingress_prefetch_budget_per_tick = 0
    experimental_idx2_ingress_prefetch_cache_entries = 0
    experimental_idx2_ingress_prefetch_max_inflight = 0
    experimental_idx2_ingress_prefetch_gather_only = 0
    experimental_idx2_ingress_prefetch_carry_to_apply_enable = 0
    experimental_idx2_ingress_prefetch_apply_max_inflight = 0
    experimental_idx2_ingress_prefetch_apply_outstanding_reserve = 0
    experimental_idx2_ingress_prefetch_apply_frontier_keep_pending = 0
    experimental_idx2_ingress_tail_guard_enable = 0
    experimental_idx2_ingress_budget_adapt_enable = 0
    experimental_idx2_ingress_budget_adapt_max_per_tick = 0
    experimental_idx2_ingress_budget_adapt_q_depth = 0
    effective_retire_policy = gas_experimental_retire_policy

    effective_cfg["gas"] = {
        "merge_policy_config": str(gas_merge_policy),
        "gap_merge_k_bytes_config": int(gas_gap_k_bytes),
        "burst_bytes_max_config": int(gas_lmax_bytes),
        "sort_policy": str(gas_sort_policy),
        "row_bytes_guess": int(gas_row_bytes_guess),
        "bank_bits": int(gas_bank_bits),
        "bank_shift": int(gas_bank_shift),
        "bank_auto_enable": int(gas_bank_auto_enable),
        "row_window_bytes": int(gas_row_window_bytes),
        "row_window_timeout_ns": int(gas_row_window_timeout_ns),
        "max_inflight_reads": int(gas_max_inflight),
        "apply_issue_policy": str(gas_apply_issue_policy),
        "experimental_retire_policy": str(effective_retire_policy),
        "experimental_gcss_phase_breakdown_enable": int(gas_experimental_gcss_phase_breakdown_enable),
        "experimental_retire_shadow_per_post_enable": int(gas_experimental_retire_shadow_per_post_enable),
        "experimental_gcss_vlf_queue_policy": str(gas_experimental_gcss_vlf_queue_policy),
        "experimental_gcss_vlf_fair_band_size": int(gas_experimental_gcss_vlf_fair_band_size),
        "experimental_gcss_vlf_bounded_rescue_enable": int(gas_experimental_gcss_vlf_bounded_rescue_enable),
        "experimental_gcss_vlf_bounded_rescue_scan_limit": int(gas_experimental_gcss_vlf_bounded_rescue_scan_limit),
        "experimental_gcss_vlf_bounded_rescue_head_wait_cycles": int(gas_experimental_gcss_vlf_bounded_rescue_head_wait_cycles),
        "experimental_gcss_vlf_bounded_rescue_depth_threshold": int(gas_experimental_gcss_vlf_bounded_rescue_depth_threshold),
        "apply_frags_per_issue": int(gas_apply_frags_per_issue),
        "apply_bank_credit": int(gas_apply_bank_credit),
        "apply_age_fair_ns": int(gas_apply_age_fair_ns),
        "dram_cmd_cost_merge_enable": int(gas_dram_cmd_cost_merge_enable),
        "dram_cmd_t_row_hit_ns": int(gas_dram_cmd_t_row_hit_ns),
        "dram_cmd_t_row_miss_ns": int(gas_dram_cmd_t_row_miss_ns),
        "dram_cmd_t_row_hit_explicit": int(gas_dram_cmd_t_row_hit_explicit),
        "dram_cmd_t_row_miss_explicit": int(gas_dram_cmd_t_row_miss_explicit),
        "dram_cmd_offline_model_enable": int(gas_dram_cmd_offline_model_enable),
        "dram_cmd_offline_model_strict": int(gas_dram_cmd_offline_model_strict),
        "dram_cmd_offline_model": dict(dram_cmd_offline_meta),
    }
    effective_cfg["gcssplp"] = {
        "profile_export_enable": int(gcssplp_profile_export_enable),
        "profile_export_dir": str(gcssplp_profile_export_dir),
    }
    effective_cfg["experimental_idx2_ingress"] = {
        "prefetch_enable": int(experimental_idx2_ingress_prefetch_enable),
        "prefetch_budget_per_tick": int(experimental_idx2_ingress_prefetch_budget_per_tick),
        "prefetch_cache_entries": int(experimental_idx2_ingress_prefetch_cache_entries),
        "prefetch_max_inflight": int(experimental_idx2_ingress_prefetch_max_inflight),
        "prefetch_gather_only": int(experimental_idx2_ingress_prefetch_gather_only),
        "prefetch_carry_to_apply_enable": int(experimental_idx2_ingress_prefetch_carry_to_apply_enable),
        "prefetch_apply_max_inflight": int(experimental_idx2_ingress_prefetch_apply_max_inflight),
        "prefetch_apply_outstanding_reserve": int(experimental_idx2_ingress_prefetch_apply_outstanding_reserve),
        "prefetch_apply_frontier_keep_pending": int(experimental_idx2_ingress_prefetch_apply_frontier_keep_pending),
        "tail_guard_enable": int(experimental_idx2_ingress_tail_guard_enable),
        "budget_adapt_enable": int(experimental_idx2_ingress_budget_adapt_enable),
        "budget_adapt_max_per_tick": int(experimental_idx2_ingress_budget_adapt_max_per_tick),
        "budget_adapt_q_depth": int(experimental_idx2_ingress_budget_adapt_q_depth),
    }
    effective_cfg["experimental_noc_rowidx"] = {
        "prefetch_enable": int(experimental_noc_rowidx_prefetch_enable),
        "prefetch_budget_per_tick": int(experimental_noc_rowidx_prefetch_budget_per_tick),
        "cache_rows": int(experimental_noc_rowidx_cache_rows),
        "prefetch_gather_only": int(experimental_noc_rowidx_prefetch_gather_only),
        "prefetch_detached_enable": int(experimental_noc_rowidx_prefetch_detached_enable),
        "prefetch_carry_to_apply_enable": int(experimental_noc_rowidx_prefetch_carry_to_apply_enable),
        "hot_touch_min": int(experimental_noc_rowidx_hot_touch_min),
        "budget_adapt_enable": int(experimental_noc_rowidx_budget_adapt_enable),
        "budget_adapt_max_per_tick": int(experimental_noc_rowidx_budget_adapt_max_per_tick),
        "budget_adapt_q_depth": int(experimental_noc_rowidx_budget_adapt_q_depth),
    }
    effective_cfg["pulse"] = {
        "enable": int(pulse_enable),
        "observe_only": int(pulse_observe_only),
        "ingress_enable": int(pulse_ingress_enable),
        "agenda_observe_only": int(pulse_agenda_observe_only),
        "harbor_enable": int(pulse_harbor_enable),
        "descriptor_enable": int(pulse_descriptor_enable),
        "descriptor_actual_enable": int(pulse_descriptor_actual_enable),
        "experimental_rowdescriptor_ready_join_dedup_enable": int(
            pulse_experimental_rowdescriptor_ready_join_dedup_enable
        ),
        "domain_retire_enable": int(pulse_domain_retire_enable),
        "domain_retire_observe_only": int(pulse_domain_retire_observe_only),
        "domain_retire_mode": str(pulse_domain_retire_mode),
        "domain_retire_release_budget": int(pulse_domain_retire_release_budget),
        "frontier_observe_enable": int(pulse_frontier_observe_enable),
        "frontier_top_lines": int(pulse_frontier_top_lines),
        "metadata_frontier_observe_enable": int(pulse_metadata_frontier_observe_enable),
        "metadata_frontier_top_items": int(pulse_metadata_frontier_top_items),
        "metadata_frontier_band_slots": int(pulse_metadata_frontier_band_slots),
        "metadata_seed_enable": int(pulse_metadata_seed_enable),
        "metadata_seed_top_bases": int(pulse_metadata_seed_top_bases),
        "metadata_seed_window_budget": int(pulse_metadata_seed_window_budget),
        "mfb_preband_seed_enable": int(pulse_mfb_preband_seed_enable),
        "mfb_preband_top_bands": int(pulse_mfb_preband_top_bands),
        "mfb_preband_lines_per_band": int(pulse_mfb_preband_lines_per_band),
        "mfb_preband_band_slots": int(pulse_mfb_preband_band_slots),
        "mfb_preband_window_budget": int(pulse_mfb_preband_window_budget),
        "mfb_gather_preband_enable": int(pulse_mfb_gather_preband_enable),
        "mfb_gather_barrier_enable": int(pulse_mfb_gather_barrier_enable),
        "mfb_gather_top_bands": int(pulse_mfb_gather_top_bands),
        "mfb_gather_lines_per_band": int(pulse_mfb_gather_lines_per_band),
        "mfb_gather_min_consumers": int(pulse_mfb_gather_min_consumers),
        "mfb_gather_window_budget": int(pulse_mfb_gather_window_budget),
        "prebase_shared_lookup_enable": int(pulse_prebase_shared_lookup_enable),
        "osa_enable": int(pulse_osa_enable),
        "osa_shared_weight_owner_enable": int(pulse_osa_shared_weight_owner_enable),
        "osa_shared_weight_owner_actual_enable": int(pulse_osa_shared_weight_owner_actual_enable),
        "osa_metadata_txn_enable": int(pulse_osa_metadata_txn_enable),
        "osa_metadata_ready_lease_enable": int(pulse_osa_metadata_ready_lease_enable),
        "osa_metadata_ready_lease_ttl": int(pulse_osa_metadata_ready_lease_ttl),
        "osa_metadata_object_mask": str(pulse_osa_metadata_object_mask),
        "ingress_entries": int(pulse_ingress_entries),
        "core_queue_entries": int(pulse_core_queue_entries),
        "descriptor_packet_min": int(pulse_descriptor_packet_min),
        "bypass_high_watermark_pct": int(pulse_bypass_high_watermark_pct),
        "bypass_mode": str(pulse_bypass_mode),
    }
    effective_cfg["naive_raw"] = {
        "max_inflight_reads": int(naive_max_inflight_reads),
        "memory_impl": "SnnDL.CachelineFragmentMemIF" if exec_mode == "naive_raw" else "memHierarchy.standardInterface",
    }
    effective_cfg["snn_rx"] = {
        "experimental_spikekey_fastpath_enable": int(spikekey_fastpath_enable),
    }

    step_template = str(step.get("activation_template", ""))
    step_use_bcsr_routes = bool(step.get("activation_use_bcsr_routes", False))
    step_bcsr_can_load = bool(step.get("activation_bcsr_can_load", False))
    step_bcsr_ready = bool(step_template and step_use_bcsr_routes and step_bcsr_can_load)

    if "minimal_core_params" in flags:
        min_params = bool(flags.get("minimal_core_params", False))
    else:
        min_params = os.environ.get("MESH_MINIMAL_CORE_PARAMS", "").strip() not in ("", "0", "false", "False")

    mapping_mode = str(mesh.get("mapping_mode", "") or "").strip().lower()
    if not mapping_mode:
        mapping_mode = os.environ.get("MESH_MAPPING_MODE", "post").strip().lower()

    if "apply_dense_acc_enable" in flags:
        apply_dense_acc_enable = 1 if bool(flags.get("apply_dense_acc_enable", True)) else 0
    else:
        apply_dense_acc_enable = 0 if str(os.environ.get("SNNDL_APPLY_DENSE_ACC", "1")).lower() in ("0", "false") else 1

    if "acc_shadow_verify_enable" in flags:
        acc_shadow_verify_enable = 1 if bool(flags.get("acc_shadow_verify_enable", False)) else 0
    else:
        acc_shadow_verify_enable = 1 if str(os.environ.get("SNNDL_ACC_SHADOW_VERIFY", "0")).lower() not in ("0", "false") else 0

    effective_cfg["minimal_core_params"] = bool(min_params)
    effective_cfg["mapping_mode"] = str(mapping_mode)
    effective_cfg["apply_dense_acc_enable"] = int(apply_dense_acc_enable)
    effective_cfg["acc_shadow_verify_enable"] = int(acc_shadow_verify_enable)

    for i in range(node_limit):
        node = sst.Component(f"multicore_pe_{i}", "SnnDL.MultiCorePE")

        layer_name = "输入层" if i in input_layer else "隐藏层1" if i in hidden_layer_1 else "隐藏层2" if i in hidden_layer_2 else "输出层"

        if isinstance(thresholds, dict) and thresholds:
            if i in input_layer:
                v_thresh = float(thresholds.get("input", 0.02))
            elif i in hidden_layer_1:
                v_thresh = float(thresholds.get("hidden1", 0.03))
            elif i in hidden_layer_2:
                v_thresh = float(thresholds.get("hidden2", 0.03))
            else:
                v_thresh = float(thresholds.get("output", 0.035))
        else:
            if i in input_layer:
                v_thresh = 0.02
            elif i in hidden_layer_1:
                v_thresh = 0.03
            elif i in hidden_layer_2:
                v_thresh = 0.03
            else:
                v_thresh = 0.035

        if readonly_enable:
            v_thresh = readonly_v_thresh

        print_node_summary_val = 1 if enable_node_summary else 0

        pe_out_dir = pe_output_dir(run_output_dir, i)
        os.makedirs(pe_out_dir, exist_ok=True)

        node_params = {
            "verbose": int(debug.get("node_verbose", 0) or 0),
            # Experiment observability only (does not change *core* assembly behavior).
            #
            # NOTE (paper strict-step mode):
            # We sometimes need to enforce "no within-step cascading" while keeping GAS enabled.
            # SnnDL implements the step_seq gating at the PE/NoC boundary behind exec_mode=="naive_raw".
            # When MESH_GAS_STEP_SEQ_GATE_ENABLE=1 and exec_mode==gas, we override the PE hint to
            # "naive_raw" to enable step_seq tagging+gating, while still assembling cores/memory as GAS.
            "exec_mode": str(exec_mode),
            # Step-limited runs are ended by GlobalGasStepController(max_steps); avoid PE keepalive blocking termination.
            "primary_keepalive": (0 if max_steps > 0 else 1),
            # NOTE: SnnPESubComponent registers its own clock; enabling manual drive here would
            # double-tick cores and break step-gate quiesce semantics (can lead to GAS empty windows).
            "manual_core_drive_enable": 0,
            "print_node_summary": print_node_summary_val,
            "num_cores": num_cores_per_pe,
            "neurons_per_core": neurons_per_core,
            "total_neurons": total_nodes * neurons_per_pe,
            "total_nodes": total_nodes,
            "node_id": i,
            "global_neuron_base": i * neurons_per_pe,
            "enable_test_traffic": 1 if enable_test_traffic else 0,
            "test_target_node": 15,
            "test_period": 1000,
            "test_spikes_per_burst": 1,
            "test_max_spikes": 8,
            "loop_dataset": 0,
            "enable_memory_weights": 0 if event_fallback else 1,
            "write_weights_on_init": 0 if event_fallback else 1,
            "weights_file": os.path.join(weights_dir, f"classification_weights_pe_{i}.bin"),
            "v_thresh": v_thresh,
            "v_rest": 0.0,
            "v_reset": 0.0,
            "use_event_weight_fallback": 1 if event_fallback else 0,
            "event_weight_fallback": 0.1,
            "verify_weights": 0,
            "weight_verify_samples": 8,
            "expected_weight_value": 1.0,
            "verify_log_each_sample": 0,
            "memory_warmup_cycles": core_memory_warmup_cycles,
            "memory_weight_priority": 1,
            "debug_weight_loading": 1,
            "debug_memory_accesses": 1,
            "verbose_weight_fetch": 1,
            "enable_weight_fetch": 1,
            "stage_events_csv": os.path.join(pe_out_dir, "stage_events.csv"),
            "stats_csv": os.path.join(pe_out_dir, "stats.csv"),
            "diag_fire_log": 1 if diag_fire_log else 0,
            "global_step_sync_enable": 1 if global_step_sync_enable else 0,
            "experimental_spikekey_fastpath_enable": int(spikekey_fastpath_enable),
            "local_storage_enable": int(local_storage_enable),
            "pe_internal_cpe_enable": int(pe_internal_cpe_enable),
            "pe_internal_pod_enable": int(pe_internal_pod_enable),
            "pe_internal_pod_count": int(pe_internal_pod_count),
            "pe_internal_pod_size": int(pe_internal_pod_size),
            "pe_internal_pod_metadata_enable": int(pe_internal_pod_metadata_enable),
            "pe_internal_pod_owner_enable": int(pe_internal_pod_owner_enable),
            "pe_internal_pod_join_enable": int(pe_internal_pod_join_enable),
            "pe_internal_pod_ready_enable": int(pe_internal_pod_ready_enable),
            "pe_internal_pod_owner_entries": int(pe_internal_pod_owner_entries),
            "pe_internal_pod_join_entries": int(pe_internal_pod_join_entries),
            "pe_internal_pod_ready_entries": int(pe_internal_pod_ready_entries),
            "pulse_enable": int(pulse_enable),
            "pulse_observe_only": int(pulse_observe_only),
            "pulse_ingress_enable": int(pulse_ingress_enable),
            "pulse_agenda_observe_only": int(pulse_agenda_observe_only),
            "pulse_harbor_enable": int(pulse_harbor_enable),
            "pulse_descriptor_enable": int(pulse_descriptor_enable),
            "pulse_descriptor_actual_enable": int(pulse_descriptor_actual_enable),
            "experimental_rowdescriptor_ready_join_dedup_enable": int(
                pulse_experimental_rowdescriptor_ready_join_dedup_enable
            ),
            "pulse_domain_retire_enable": int(pulse_domain_retire_enable),
            "pulse_domain_retire_observe_only": int(pulse_domain_retire_observe_only),
            "pulse_domain_retire_mode": str(pulse_domain_retire_mode),
            "pulse_domain_retire_release_budget": int(pulse_domain_retire_release_budget),
            "pulse_frontier_observe_enable": int(pulse_frontier_observe_enable),
            "pulse_frontier_top_lines": int(pulse_frontier_top_lines),
            "pulse_metadata_frontier_observe_enable": int(pulse_metadata_frontier_observe_enable),
            "pulse_metadata_frontier_top_items": int(pulse_metadata_frontier_top_items),
            "pulse_metadata_frontier_band_slots": int(pulse_metadata_frontier_band_slots),
            "pulse_metadata_seed_enable": int(pulse_metadata_seed_enable),
            "pulse_metadata_seed_top_bases": int(pulse_metadata_seed_top_bases),
            "pulse_metadata_seed_window_budget": int(pulse_metadata_seed_window_budget),
            "pulse_mfb_preband_seed_enable": int(pulse_mfb_preband_seed_enable),
            "pulse_mfb_preband_top_bands": int(pulse_mfb_preband_top_bands),
            "pulse_mfb_preband_lines_per_band": int(pulse_mfb_preband_lines_per_band),
            "pulse_mfb_preband_band_slots": int(pulse_mfb_preband_band_slots),
            "pulse_mfb_preband_window_budget": int(pulse_mfb_preband_window_budget),
            "pulse_mfb_gather_preband_enable": int(pulse_mfb_gather_preband_enable),
            "pulse_mfb_gather_barrier_enable": int(pulse_mfb_gather_barrier_enable),
            "pulse_mfb_gather_top_bands": int(pulse_mfb_gather_top_bands),
            "pulse_mfb_gather_lines_per_band": int(pulse_mfb_gather_lines_per_band),
            "pulse_mfb_gather_min_consumers": int(pulse_mfb_gather_min_consumers),
            "pulse_mfb_gather_window_budget": int(pulse_mfb_gather_window_budget),
            "pulse_prebase_shared_lookup_enable": int(pulse_prebase_shared_lookup_enable),
            "pulse_osa_enable": int(pulse_osa_enable),
            "pulse_osa_shared_weight_owner_enable": int(pulse_osa_shared_weight_owner_enable),
            "pulse_osa_shared_weight_owner_actual_enable": int(pulse_osa_shared_weight_owner_actual_enable),
            "pulse_osa_metadata_txn_enable": int(pulse_osa_metadata_txn_enable),
            "pulse_osa_metadata_ready_lease_enable": int(pulse_osa_metadata_ready_lease_enable),
            "pulse_osa_metadata_ready_lease_ttl": int(pulse_osa_metadata_ready_lease_ttl),
            "pulse_osa_metadata_object_mask": str(pulse_osa_metadata_object_mask),
            "pulse_ingress_entries": int(pulse_ingress_entries),
            "pulse_core_queue_entries": int(pulse_core_queue_entries),
            "pulse_descriptor_packet_min": int(pulse_descriptor_packet_min),
            "pulse_bypass_high_watermark_pct": int(pulse_bypass_high_watermark_pct),
            "pulse_bypass_mode": str(pulse_bypass_mode),
            "weight_sram_model_enable": int(sram_model_enable),
            "weight_idx_sram_enable": int(sram_weight_idx_enable),
            "weight_l0_sram_enable": int(sram_weight_l0_enable),
            "weight_idx_sram_capacity_bytes": int(sram_weight_idx_capacity_bytes),
            "weight_l0_sram_capacity_bytes": int(sram_weight_l0_capacity_bytes),
            "weight_idx_sram_banks": int(sram_weight_idx_banks),
            "weight_l0_sram_banks": int(sram_weight_l0_banks),
            "weight_sram_ports_per_bank": int(sram_weight_ports_per_bank),
            "weight_sram_bank_interleave_bytes": int(sram_weight_bank_interleave_bytes),
            "weight_sram_t_read_cycles": int(sram_weight_t_read_cycles),
            "weight_sram_t_write_cycles": int(sram_weight_t_write_cycles),
            "weight_sram_sample_log2": int(sram_weight_sample_log2),
            "weight_idx_sram_base": int(sram_weight_idx_base),
            "weight_l0_sram_base": int(sram_weight_l0_base),
            "weight_l0_sram_slots": int(sram_weight_l0_slots),
            # WeightLoader barrier shared key (used by cores and PE for step-limited readiness gating)
            "loader_done_key": f"snndl_loader_done_pe_{i:02d}",
        }

        gas_step_seq_gate_enable = False
        if "gas_step_seq_gate_enable" in flags:
            gas_step_seq_gate_enable = bool(flags.get("gas_step_seq_gate_enable", False))
        else:
            gas_step_seq_gate_env = os.environ.get("MESH_GAS_STEP_SEQ_GATE_ENABLE", "").strip().lower()
            gas_step_seq_gate_enable = gas_step_seq_gate_env in ("1", "true", "yes", "y", "on")
        if gas_step_seq_gate_enable and exec_mode == "gas" and max_steps > 0:
            # Important: keep `exec_mode` variable unchanged so GAS is still assembled.
            node_params["exec_mode"] = "naive_raw"

        if global_step_sync_enable:
            # 语义等价对比（推荐）：drain-based step done
            # - 要求本 PE 核心/NoC/NIC 进入稳定静默一段周期后才上报 PE_DONE(seq)
            # - 避免 naive_* 在 quiescent/fixed_cycles 下出现“未排空事务就推进 step”的语义漂移
            pol = str(flags.get("global_step_done_policy", "") or "").strip().lower()
            if not pol:
                pol = str(os.environ.get("MESH_GLOBAL_STEP_DONE_POLICY", "drain") or "drain").strip().lower()
            node_params["global_step_done_policy"] = pol
            if pol in ("drain", "drain_based", "drainbased"):
                if "global_step_drain_min_cycles" in flags:
                    node_params["global_step_drain_min_cycles"] = _cfg_int(flags, "global_step_drain_min_cycles", 200)
                else:
                    node_params["global_step_drain_min_cycles"] = int(os.environ.get("MESH_GLOBAL_STEP_DRAIN_MIN_CYCLES", "200") or "200")
            elif pol in ("quiescent", "quiet"):
                if "global_step_quiescent_min_cycles" in flags:
                    node_params["global_step_quiescent_min_cycles"] = _cfg_int(flags, "global_step_quiescent_min_cycles", 1)
                else:
                    node_params["global_step_quiescent_min_cycles"] = int(os.environ.get("MESH_GLOBAL_STEP_QUIESCENT_MIN_CYCLES", "1") or "1")
            elif pol in ("fixed", "fixed_cycles", "timer"):
                if "global_step_fixed_cycles" in flags:
                    node_params["global_step_fixed_cycles"] = _cfg_int(flags, "global_step_fixed_cycles", 100000)
                else:
                    node_params["global_step_fixed_cycles"] = int(os.environ.get("MESH_GLOBAL_STEP_FIXED_CYCLES", "100000") or "100000")
            # Step start gating: delay PE_READY until WeightLoader done, then wait N cycles for rowptr prefetch to settle.
            # Only meaningful for step-limited runs (max_steps>0) where StartStep is barrier-driven.
            if max_steps > 0:
                if "global_step_ready_delay_cycles" in flags:
                    node_params["global_step_ready_delay_cycles"] = _cfg_int(flags, "global_step_ready_delay_cycles", 500)
                else:
                    node_params["global_step_ready_delay_cycles"] = int(os.environ.get("MESH_GLOBAL_STEP_READY_DELAY_CYCLES", "500") or "500")

        if bool(debug.get("sentinel_enable", False)):
            # Limit sentinel diagnostics to a single PE to avoid log floods in 16PE regressions.
            # Default: target PE0 unless explicitly overridden.
            sentinel_target_pe = resolve_sentinel_target_pe(debug)
            if sentinel_target_pe < 0 or i == sentinel_target_pe:
                node_params["sentinel_enable"] = 1
        if int(debug.get("progress_log_interval_ns", 0)) > 0:
            node_params["progress_log_interval_ns"] = int(debug.get("progress_log_interval_ns", 0))
            node_params["progress_log_node"] = int(debug.get("progress_log_node", -1))

        if global_bcsr_available:
            node_params["weight_format"] = "bcsr"

        _apply_workload_params_to_component_params(
            node_params,
            workload_impl=workload_impl,
            workload_stats_modules=workload_stats_modules,
            workload_node_params=workload_node_params,
        )

        merge_params_checked(node_params, {
            "step_random_activation_enable": 1 if bool(step.get("random_activation_enable", 0)) else 0,
            "step_activation_enable": 1 if bool(step.get("random_activation_enable", 0)) else 0,
            # Step-limited runs are driven by the global barrier controller: one injection per step.
            "step_activation_period_cycles": (0 if max_steps > 0 else int(step.get("activation_period_cycles", 0))),
            "step_activation_build_local_only": 0,
            "step_activation_fraction": float(step.get("activation_fraction", 0.0)),
            "step_activation_fanout": int(step.get("activation_fanout", 256)),
            "step_activation_seed": int(step.get("activation_seed", 0)),
            "step_activation_event_weight": float(step.get("activation_event_weight", 0.0)),
            "step_activation_trigger_core": int(step.get("activation_trigger_core", 0)),
            "step_activation_pre_pattern": str(step.get("activation_pre_pattern", "bernoulli") or "bernoulli").strip().lower(),
            "step_activation_pre_cluster_len": int(step.get("activation_pre_cluster_len", 0) or 0),
            "step_activation_use_bcsr_routes": 1 if step_bcsr_ready else 0,
            "step_activation_bcsr_template": step_template,
            "step_activation_bcsr_rows_per_core": int(step.get("activation_bcsr_rows_per_core", neurons_per_core)),
            "step_activation_bcsr_br": int(step.get("activation_bcsr_br", 16)),
            "step_activation_bcsr_bc": int(step.get("activation_bcsr_bc", 16)),
            "step_activation_bcsr_idx_bytes": int(step.get("activation_bcsr_idx_bytes", 2)),
            "step_activation_bcsr_val_bytes": int(step.get("activation_bcsr_val_bytes", 4)),
            "step_activation_bcsr_rowptr_offset": int(step.get("activation_bcsr_rowptr_offset", 0)),
            "step_activation_bcsr_colidx_offset": int(step.get("activation_bcsr_colidx_offset", 0)),
            "step_activation_bcsr_blockdata_offset": int(step.get("activation_bcsr_blockdata_offset", 0)),
            "step_activation_bcsr_blockids_offset": int(step.get("activation_bcsr_blockids_offset", 0)),
            "step_activation_bcsr_weight_epsilon": float(step.get("activation_bcsr_weight_epsilon", 0.0)),
            "step_reset_mem_each_step": int(step.get("reset_mem_each_step", 0)),
            "step_seed_only_mode": int(step.get("seed_only_mode", 0)),
        }, ctx=f"node_params[{i}].")

        pe_weight_base_i = base_addr_global_shift + pe_weight_region_stride * i
        node_params["base_addr"] = pe_weight_base_i
        if sim_stop_ns > 0:
            node_params["sim_stop_ns"] = sim_stop_ns

        _add_params_with_overrides(
            node,
            role="pe",
            component_type="SnnDL.MultiCorePE",
            name=f"multicore_pe_{i}",
            tags={"pe": int(i), "layer": str(layer_name)},
            params=node_params,
            override_engine=override_engine,
            override_report=override_report,
        )

        if global_step_ctrl is not None:
            step_ctrl_link = sst.Link(f"pe_{i}_to_global_step_ctrl")
            step_ctrl_link.connect(
                # NOTE: Cross-thread control-plane link (multi-thread SST).
                # Sub-ps latency can violate thread-sync lookahead and lead to barrier events not being delivered.
                (node, "gas_step_ctrl", "5ns"),
                (global_step_ctrl, f"pe_link{i}", "5ns"),
            )

        nic = None
        if not disable_network:
            nic_component_type = "SnnDL.MulticastNIC" if use_multicast_noc else "SnnDL.SnnNIC"
            nic = node.setSubComponent("network_interface", nic_component_type)
            if use_multicast_noc:
                nic_params = {
                    "node_id": str(i),
                    "port_name": "network",
                    "local_endpoint_multicast_enable": int(local_endpoint_multicast_enable),
                    "verbose": 0,
                }
            else:
                nic_params = {
                    "node_id": str(i),
                    "link_bw": network_bandwidth,
                    "input_buf_size": buffer_size,
                    "output_buf_size": buffer_size,
                    "use_direct_link": "false",
                    "port_name": "network",
                    "verbose": 0,
                    # Merlin: 推荐至少 2 个 VN 以避免高并发 spike 流量下不收敛（credit/backpressure 卡死）。
                    "virtual_channels": int(mesh.get("network_num_vns", 2) or 2),
                    "network_num_vns": int(mesh.get("network_num_vns", 2) or 2),
                    "vn_spike_data": 0,
                    "vn_batch_data": 1,
                    "vn_control": 1,
                    "total_nodes": total_nodes,
                    "export_spike_csv": (spikes_mesh_csv if export_spike_csv else ""),
                }

            # Sentinel/debug: 仅对目标PE启用，避免 16PE 全量日志淹没输出。
            if bool(debug.get("sentinel_enable", False)):
                sentinel_target_pe = resolve_sentinel_target_pe(debug)

                if sentinel_target_pe < 0 or i == sentinel_target_pe:
                    nic_params["sentinel_enable"] = 1
                    nic_params["verbose"] = max(int(debug.get("nic_verbose", 1) or 1), int(nic_params.get("verbose", 0)))

            _add_params_with_overrides(
                nic,
                role="pe.nic",
                component_type=nic_component_type,
                name=f"multicore_pe_{i}.network_interface",
                tags={"pe": int(i), "layer": str(layer_name)},
                params=nic_params,
                override_engine=override_engine,
                override_report=override_report,
            )
            try:
                enable_accumulator_statistics(nic)
            except Exception:
                pass

        for core_idx in range(num_cores_per_pe):
            core_subcomponent = node.setSubComponent(f"core{core_idx}", "SnnDL.SnnPESubComponent")
            core_base_addr = pe_weight_base_i + core_idx * per_core_weight_stride

            if global_bcsr_available and not force_dense:
                index_mode = "bcsr_post_row"
            else:
                index_mode = "post_row_pre_col" if mapping_mode in ("post", "post_owned", "m0") else "pre_row_post_col"

            core_meta = load_core_bcsr_meta(global_bcsr_dir, i, core_idx) if global_bcsr_available else {}

            if min_params:
                core_params = {
                    "core_id": core_idx,
                    "total_cores": num_cores_per_pe,
                    "global_neuron_base": i * neurons_per_pe + core_idx * neurons_per_core,
                    "num_neurons": neurons_per_core,
                    "neurons_per_pe": neurons_per_pe,
                    "base_addr": core_base_addr,
                    "node_id": i,
                    "verbose": 0,
                    "gas_enable": 1,
                    "gas_window_mode": 1,
                    "window_read_enable": 1,
                    "line_size_bytes": subcomp_line_bytes,
                    "index_mode": index_mode,
                    "weights_cols": global_weights_cols,
                    "synapse_weight_mode": synapse_weight_mode,
                    "experimental_retire_policy": str(effective_retire_policy),
                    "experimental_gcss_phase_breakdown_enable": int(gas_experimental_gcss_phase_breakdown_enable),
                    "experimental_retire_shadow_per_post_enable": int(gas_experimental_retire_shadow_per_post_enable),
                    "experimental_gcss_vlf_queue_policy": str(gas_experimental_gcss_vlf_queue_policy),
                    "experimental_gcss_vlf_fair_band_size": int(gas_experimental_gcss_vlf_fair_band_size),
                    "pulse_enable": int(pulse_enable),
                    "pulse_observe_only": int(pulse_observe_only),
                    "pulse_ingress_enable": int(pulse_ingress_enable),
                    "pulse_agenda_observe_only": int(pulse_agenda_observe_only),
                    "pulse_harbor_enable": int(pulse_harbor_enable),
                    "pulse_descriptor_enable": int(pulse_descriptor_enable),
                    "pulse_descriptor_actual_enable": int(pulse_descriptor_actual_enable),
                    "experimental_rowdescriptor_ready_join_dedup_enable": int(
                        pulse_experimental_rowdescriptor_ready_join_dedup_enable
                    ),
                    "pulse_domain_retire_enable": int(pulse_domain_retire_enable),
                    "pulse_domain_retire_observe_only": int(pulse_domain_retire_observe_only),
                    "pulse_domain_retire_mode": str(pulse_domain_retire_mode),
                    "pulse_domain_retire_release_budget": int(pulse_domain_retire_release_budget),
                    "pulse_frontier_observe_enable": int(pulse_frontier_observe_enable),
                    "pulse_frontier_top_lines": int(pulse_frontier_top_lines),
                    "pulse_metadata_frontier_observe_enable": int(pulse_metadata_frontier_observe_enable),
                    "pulse_metadata_frontier_top_items": int(pulse_metadata_frontier_top_items),
                    "pulse_metadata_frontier_band_slots": int(pulse_metadata_frontier_band_slots),
                    "pulse_metadata_seed_enable": int(pulse_metadata_seed_enable),
                    "pulse_metadata_seed_top_bases": int(pulse_metadata_seed_top_bases),
                    "pulse_metadata_seed_window_budget": int(pulse_metadata_seed_window_budget),
                    "pulse_mfb_preband_seed_enable": int(pulse_mfb_preband_seed_enable),
                    "pulse_mfb_preband_top_bands": int(pulse_mfb_preband_top_bands),
                    "pulse_mfb_preband_lines_per_band": int(pulse_mfb_preband_lines_per_band),
                    "pulse_mfb_preband_band_slots": int(pulse_mfb_preband_band_slots),
                    "pulse_mfb_preband_window_budget": int(pulse_mfb_preband_window_budget),
                    "pulse_mfb_gather_preband_enable": int(pulse_mfb_gather_preband_enable),
                    "pulse_mfb_gather_barrier_enable": int(pulse_mfb_gather_barrier_enable),
                    "pulse_mfb_gather_top_bands": int(pulse_mfb_gather_top_bands),
                    "pulse_mfb_gather_lines_per_band": int(pulse_mfb_gather_lines_per_band),
                    "pulse_mfb_gather_min_consumers": int(pulse_mfb_gather_min_consumers),
                    "pulse_mfb_gather_window_budget": int(pulse_mfb_gather_window_budget),
                    "pulse_prebase_shared_lookup_enable": int(pulse_prebase_shared_lookup_enable),
                    "pulse_osa_enable": int(pulse_osa_enable),
                    "pulse_osa_shared_weight_owner_enable": int(pulse_osa_shared_weight_owner_enable),
                    "pulse_osa_shared_weight_owner_actual_enable": int(pulse_osa_shared_weight_owner_actual_enable),
                    "pulse_osa_metadata_txn_enable": int(pulse_osa_metadata_txn_enable),
                    "pulse_osa_metadata_ready_lease_enable": int(pulse_osa_metadata_ready_lease_enable),
                    "pulse_osa_metadata_ready_lease_ttl": int(pulse_osa_metadata_ready_lease_ttl),
                    "pulse_osa_metadata_object_mask": str(pulse_osa_metadata_object_mask),
                    "pulse_ingress_entries": int(pulse_ingress_entries),
                    "pulse_core_queue_entries": int(pulse_core_queue_entries),
                    "pulse_descriptor_packet_min": int(pulse_descriptor_packet_min),
                    "pulse_bypass_high_watermark_pct": int(pulse_bypass_high_watermark_pct),
                    "pulse_bypass_mode": str(pulse_bypass_mode),
                    "experimental_gcss_vlf_bounded_rescue_enable": int(gas_experimental_gcss_vlf_bounded_rescue_enable),
                    "experimental_gcss_vlf_bounded_rescue_scan_limit": int(gas_experimental_gcss_vlf_bounded_rescue_scan_limit),
                    "experimental_gcss_vlf_bounded_rescue_head_wait_cycles": int(gas_experimental_gcss_vlf_bounded_rescue_head_wait_cycles),
                    "experimental_gcss_vlf_bounded_rescue_depth_threshold": int(gas_experimental_gcss_vlf_bounded_rescue_depth_threshold),
                    "experimental_spikekey_fastpath_enable": int(spikekey_fastpath_enable),
                    "gcss_index_template": gcss_index_template,
                    "experimental_pre_window_profile_export_enable": int(gcssplp_profile_export_enable),
                    "experimental_pre_window_profile_export_dir": str(gcssplp_profile_export_dir),
                    "experimental_idx2_ingress_prefetch_enable": int(experimental_idx2_ingress_prefetch_enable),
                    "experimental_idx2_ingress_prefetch_budget_per_tick": int(experimental_idx2_ingress_prefetch_budget_per_tick),
                    "experimental_idx2_ingress_prefetch_cache_entries": int(experimental_idx2_ingress_prefetch_cache_entries),
                    "experimental_idx2_ingress_prefetch_max_inflight": int(experimental_idx2_ingress_prefetch_max_inflight),
                    "experimental_idx2_ingress_prefetch_gather_only": int(experimental_idx2_ingress_prefetch_gather_only),
                    "experimental_idx2_ingress_prefetch_carry_to_apply_enable": int(experimental_idx2_ingress_prefetch_carry_to_apply_enable),
                    "experimental_idx2_ingress_prefetch_apply_max_inflight": int(experimental_idx2_ingress_prefetch_apply_max_inflight),
                    "experimental_idx2_ingress_prefetch_apply_outstanding_reserve": int(experimental_idx2_ingress_prefetch_apply_outstanding_reserve),
                    "experimental_idx2_ingress_prefetch_apply_frontier_keep_pending": int(experimental_idx2_ingress_prefetch_apply_frontier_keep_pending),
                    "experimental_idx2_ingress_tail_guard_enable": int(experimental_idx2_ingress_tail_guard_enable),
                    "experimental_idx2_ingress_budget_adapt_enable": int(experimental_idx2_ingress_budget_adapt_enable),
                    "experimental_idx2_ingress_budget_adapt_max_per_tick": int(experimental_idx2_ingress_budget_adapt_max_per_tick),
                    "experimental_idx2_ingress_budget_adapt_q_depth": int(experimental_idx2_ingress_budget_adapt_q_depth),
                    "experimental_noc_rowidx_prefetch_enable": int(experimental_noc_rowidx_prefetch_enable),
                    "experimental_noc_rowidx_prefetch_budget_per_tick": int(experimental_noc_rowidx_prefetch_budget_per_tick),
                    "experimental_noc_rowidx_cache_rows": int(experimental_noc_rowidx_cache_rows),
                    "experimental_noc_rowidx_prefetch_gather_only": int(experimental_noc_rowidx_prefetch_gather_only),
                    "experimental_noc_rowidx_prefetch_detached_enable": int(experimental_noc_rowidx_prefetch_detached_enable),
                    "experimental_noc_rowidx_prefetch_carry_to_apply_enable": int(experimental_noc_rowidx_prefetch_carry_to_apply_enable),
                    "experimental_noc_rowidx_hot_touch_min": int(experimental_noc_rowidx_hot_touch_min),
                    "experimental_noc_rowidx_budget_adapt_enable": int(experimental_noc_rowidx_budget_adapt_enable),
                    "experimental_noc_rowidx_budget_adapt_max_per_tick": int(experimental_noc_rowidx_budget_adapt_max_per_tick),
                    "experimental_noc_rowidx_budget_adapt_q_depth": int(experimental_noc_rowidx_budget_adapt_q_depth),
                    "weight_sram_model_enable": int(sram_model_enable),
                    "weight_idx_sram_enable": int(sram_weight_idx_enable),
                    "weight_l0_sram_enable": int(sram_weight_l0_enable),
                    "weight_idx_sram_capacity_bytes": int(sram_weight_idx_capacity_bytes),
                    "weight_l0_sram_capacity_bytes": int(sram_weight_l0_capacity_bytes),
                    "weight_idx_sram_banks": int(sram_weight_idx_banks),
                    "weight_l0_sram_banks": int(sram_weight_l0_banks),
                    "weight_sram_ports_per_bank": int(sram_weight_ports_per_bank),
                    "weight_sram_bank_interleave_bytes": int(sram_weight_bank_interleave_bytes),
                    "weight_sram_t_read_cycles": int(sram_weight_t_read_cycles),
                    "weight_sram_t_write_cycles": int(sram_weight_t_write_cycles),
                    "weight_sram_sample_log2": int(sram_weight_sample_log2),
                    "weight_idx_sram_base": int(sram_weight_idx_base),
                    "weight_l0_sram_base": int(sram_weight_l0_base),
                    "weight_l0_sram_slots": int(sram_weight_l0_slots),
                    "state_sram_enable": int(sram_model_enable and sram_state_enable),
                    "state_sram_capacity_bytes": int(sram_state_capacity_bytes),
                    "state_sram_banks": int(sram_state_banks),
                    "state_sram_ports_per_bank": int(sram_state_ports_per_bank),
                    "state_sram_bank_interleave_bytes": int(sram_state_bank_interleave_bytes),
                    "state_sram_t_read_cycles": int(sram_state_t_read_cycles),
                    "state_sram_t_write_cycles": int(sram_state_t_write_cycles),
                    "state_sram_sample_log2": int(sram_state_sample_log2),
                    "state_sram_vmem_base": int(sram_state_vmem_base),
                    "state_sram_refrac_base": int(sram_state_refrac_base),
                    "state_sram_last_spike_base": int(sram_state_last_spike_base),
                    "diag_fire_log": 1 if diag_fire_log else 0,
                    "step_seed_only_mode": int(step.get("seed_only_mode", 0)),
                }
            else:
                debug_target_pe = int(debug.get("debug_target_pe", 0))
                debug_target_core = int(debug.get("debug_target_core", 0))
                window_read_debug_all = bool(debug.get("window_read_debug_all_cores", False))
                window_read_debug_enabled = bool(debug.get("window_read_debug", False))
                core_verbose = int(debug.get("core_verbose", 0))

                core_params = {
                    "core_id": core_idx,
                    "total_cores": num_cores_per_pe,
                    "global_neuron_base": i * neurons_per_pe + core_idx * neurons_per_core,
                    "num_neurons": neurons_per_core,
                    "neurons_per_pe": neurons_per_pe,
                    "v_thresh": v_thresh,
                    "v_reset": 0.0,
                    "v_rest": 0.0,
                    "tau_mem": core_tau_mem,
                    "t_ref": core_t_ref,
                    "base_addr": core_base_addr,
                    "node_id": i,
                    "verbose": (core_verbose if (window_read_debug_all or (i == debug_target_pe and core_idx == debug_target_core)) else 0),
                    "enable_weight_fetch": 0 if event_fallback else 1,
                    "write_weights_on_init": 1,
                    "memory_warmup_cycles": core_memory_warmup_cycles,
                    "init_default_weight": init_default_weight,
                    "loader_barrier_cycles": core_loader_barrier_cycles,
                    "loader_done_key": f"snndl_loader_done_pe_{i:02d}",
                    # Per-core throttle in WeightMemorySubsystem (how many reads can be in-flight from the core's POV).
                    # Microbench may override via mesh.max_outstanding_requests to avoid truncating Apply.
                    "max_outstanding_requests": int(mesh.get("max_outstanding_requests", 64) or 64),
                    "max_cache_entries": 65536,
                    "use_event_weight_fallback": 1 if event_fallback else 0,
                    # Dense read granularity: prefer cacheline-sized reads.
                    # This matches memHierarchy/cacheline semantics and avoids row-sized overfetch.
                    "merge_read_cacheline": 1,
                    "merge_read_row": 0,
                    "merge_read_auto": 0,
                    "byte_exact_verify_enable": int(mesh.get("byte_exact_verify_enable", 0) or 0),
                    "byte_exact_verify_mode": str(mesh.get("byte_exact_verify_mode", "")),
                    "byte_exact_verify_row_scale": int(mesh.get("byte_exact_verify_row_scale", 1024) or 1024),
                    "byte_exact_verify_max_mismatch": int(mesh.get("byte_exact_verify_max_mismatch", 8) or 8),
                    "weights_cols": global_weights_cols,
                    "index_mode": index_mode,
                    "line_size_bytes": subcomp_line_bytes,
                    "enable_detailed_map_log": 0,
                    "gas_enable": 1,
                    "gas_window_mode": 1,
                    "gas_window_cycles_gather": int(gas_window_cycles.get("gather", 200)),
                    # Step-gate (GLOBAL_STEP_SYNC) load-driven Gather end:
                    # - Gather must not end before injected spikes arrive (NoC latency can exceed the old default 32 cycles).
                    # - Use a conservative default only in barrier mode to avoid BeginApply on an empty edge set.
                    "gas_gather_quiesce_cycles": _cfg_int(
                        gas,
                        "gather_quiesce_cycles",
                        (512 if global_step_sync_enable else 32),
                    ),
                    "gas_gather_min_cycles": _cfg_int(gas, "gather_min_cycles", 1),
                    "apply_acc_enable": 1,
                    "apply_dense_acc_enable": int(apply_dense_acc_enable),
                    "acc_shadow_verify_enable": int(acc_shadow_verify_enable),
                    "window_read_enable": 1,
                    "window_read_debug": (1 if (window_read_debug_enabled and (window_read_debug_all or (i == debug_target_pe and core_idx == debug_target_core))) else 0),
                    "bcsr_rowptr_retry_max": 8,
                    "bcsr_rowptr_file_fallback_enable": 1,
                    "scatter_diag_limit": (8 if (window_read_debug_enabled and (window_read_debug_all or (i == debug_target_pe and core_idx == debug_target_core))) else 0),
                    "record_edge_apply_enable": record_edge_apply_enable,
                    "record_edge_idle_enable": record_edge_idle_enable,
                    "record_edge_scatter_enable": record_edge_scatter_enable,
                    "experimental_spikekey_fastpath_enable": int(spikekey_fastpath_enable),
                    "use_soa_neuron_state": use_soa_state,
                    "use_aosoa_neuron_state": use_aosoa_state,
                    "aosoa_block_rows": aosoa_block_rows,
                    "verify_weights": (1 if (i == 0 and core_idx == 0) else 0),
                    "verify_against_file": 0,
                    "verify_file_template": "",
                    "weight_verify_samples": 1,
                    "verify_epsilon": 1e-6,
                    "verify_log_each_sample": 0,
                    "verify_cluster_enable": verify_cluster_enable,
                    "routing_mode": str(routing.get("mode", "weight_driven")),
                    "weights_template": (
                        os.path.join(global_bcsr_dir, "pe{pe:02d}", "core{core:02d}.bcsr.bin")
                        if global_bcsr_available else os.path.join(weights_dir, "classification_weights_pe_{pe}.bin")
                    ),
                    "total_nodes": total_nodes,
                    "routing_epsilon": float(routing.get("epsilon", 0.6)),
                    "routing_topk_per_pe": int(routing.get("topk_per_pe", 2)),
                    "routing_topk": int(routing.get("topk", 12)),
                    "route_exclude_self_pe": 0,
                    "route_layers_mask": "",
                    "route_filter_warn": 0,
                    "mapping_mode": "off",
                    "mapping_edges_file": "",
                    "mapping_csv_has_header": 1,
                    "mapping_csv_separator": ",",
                    "mapping_assume_block_ids": 1,
                    "multicast_enable": int(multicast_enable),
                    "multicast_block_w": int(multicast_block_w),
                    "multicast_block_h": int(multicast_block_h),
                    "multicast_ingress_policy": str(multicast_ingress_policy),
                    "multicast_inter_policy": str(multicast_inter_policy),
                    "multicast_intra_policy": str(multicast_intra_policy),
                    "local_endpoint_multicast_enable": int(local_endpoint_multicast_enable),
                    "synapse_weight_mode": synapse_weight_mode,
                    "experimental_retire_policy": str(effective_retire_policy),
                    "experimental_gcss_phase_breakdown_enable": int(gas_experimental_gcss_phase_breakdown_enable),
                    "experimental_retire_shadow_per_post_enable": int(gas_experimental_retire_shadow_per_post_enable),
                    "experimental_gcss_vlf_queue_policy": str(gas_experimental_gcss_vlf_queue_policy),
                    "experimental_gcss_vlf_fair_band_size": int(gas_experimental_gcss_vlf_fair_band_size),
                    "pulse_enable": int(pulse_enable),
                    "pulse_observe_only": int(pulse_observe_only),
                    "pulse_ingress_enable": int(pulse_ingress_enable),
                    "pulse_agenda_observe_only": int(pulse_agenda_observe_only),
                    "pulse_harbor_enable": int(pulse_harbor_enable),
                    "pulse_descriptor_enable": int(pulse_descriptor_enable),
                    "pulse_descriptor_actual_enable": int(pulse_descriptor_actual_enable),
                    "experimental_rowdescriptor_ready_join_dedup_enable": int(
                        pulse_experimental_rowdescriptor_ready_join_dedup_enable
                    ),
                    "pulse_domain_retire_enable": int(pulse_domain_retire_enable),
                    "pulse_domain_retire_observe_only": int(pulse_domain_retire_observe_only),
                    "pulse_domain_retire_mode": str(pulse_domain_retire_mode),
                    "pulse_domain_retire_release_budget": int(pulse_domain_retire_release_budget),
                    "pulse_frontier_observe_enable": int(pulse_frontier_observe_enable),
                    "pulse_frontier_top_lines": int(pulse_frontier_top_lines),
                    "pulse_metadata_frontier_observe_enable": int(pulse_metadata_frontier_observe_enable),
                    "pulse_metadata_frontier_top_items": int(pulse_metadata_frontier_top_items),
                    "pulse_metadata_frontier_band_slots": int(pulse_metadata_frontier_band_slots),
                    "pulse_metadata_seed_enable": int(pulse_metadata_seed_enable),
                    "pulse_metadata_seed_top_bases": int(pulse_metadata_seed_top_bases),
                    "pulse_metadata_seed_window_budget": int(pulse_metadata_seed_window_budget),
                    "pulse_mfb_preband_seed_enable": int(pulse_mfb_preband_seed_enable),
                    "pulse_mfb_preband_top_bands": int(pulse_mfb_preband_top_bands),
                    "pulse_mfb_preband_lines_per_band": int(pulse_mfb_preband_lines_per_band),
                    "pulse_mfb_preband_band_slots": int(pulse_mfb_preband_band_slots),
                    "pulse_mfb_preband_window_budget": int(pulse_mfb_preband_window_budget),
                    "pulse_mfb_gather_preband_enable": int(pulse_mfb_gather_preband_enable),
                    "pulse_mfb_gather_barrier_enable": int(pulse_mfb_gather_barrier_enable),
                    "pulse_mfb_gather_top_bands": int(pulse_mfb_gather_top_bands),
                    "pulse_mfb_gather_lines_per_band": int(pulse_mfb_gather_lines_per_band),
                    "pulse_mfb_gather_min_consumers": int(pulse_mfb_gather_min_consumers),
                    "pulse_mfb_gather_window_budget": int(pulse_mfb_gather_window_budget),
                    "pulse_prebase_shared_lookup_enable": int(pulse_prebase_shared_lookup_enable),
                    "pulse_osa_enable": int(pulse_osa_enable),
                    "pulse_osa_shared_weight_owner_enable": int(pulse_osa_shared_weight_owner_enable),
                    "pulse_osa_shared_weight_owner_actual_enable": int(pulse_osa_shared_weight_owner_actual_enable),
                    "pulse_osa_metadata_txn_enable": int(pulse_osa_metadata_txn_enable),
                    "pulse_osa_metadata_ready_lease_enable": int(pulse_osa_metadata_ready_lease_enable),
                    "pulse_osa_metadata_ready_lease_ttl": int(pulse_osa_metadata_ready_lease_ttl),
                    "pulse_osa_metadata_object_mask": str(pulse_osa_metadata_object_mask),
                    "pulse_ingress_entries": int(pulse_ingress_entries),
                    "pulse_core_queue_entries": int(pulse_core_queue_entries),
                    "pulse_descriptor_packet_min": int(pulse_descriptor_packet_min),
                    "pulse_bypass_high_watermark_pct": int(pulse_bypass_high_watermark_pct),
                    "pulse_bypass_mode": str(pulse_bypass_mode),
                    "experimental_gcss_vlf_bounded_rescue_enable": int(gas_experimental_gcss_vlf_bounded_rescue_enable),
                    "experimental_gcss_vlf_bounded_rescue_scan_limit": int(gas_experimental_gcss_vlf_bounded_rescue_scan_limit),
                    "experimental_gcss_vlf_bounded_rescue_head_wait_cycles": int(gas_experimental_gcss_vlf_bounded_rescue_head_wait_cycles),
                    "experimental_gcss_vlf_bounded_rescue_depth_threshold": int(gas_experimental_gcss_vlf_bounded_rescue_depth_threshold),
                    "gcss_index_template": gcss_index_template,
                    "experimental_pre_window_profile_export_enable": int(gcssplp_profile_export_enable),
                    "experimental_pre_window_profile_export_dir": str(gcssplp_profile_export_dir),
                    "experimental_idx2_ingress_prefetch_enable": int(experimental_idx2_ingress_prefetch_enable),
                    "experimental_idx2_ingress_prefetch_budget_per_tick": int(experimental_idx2_ingress_prefetch_budget_per_tick),
                    "experimental_idx2_ingress_prefetch_cache_entries": int(experimental_idx2_ingress_prefetch_cache_entries),
                    "experimental_idx2_ingress_prefetch_max_inflight": int(experimental_idx2_ingress_prefetch_max_inflight),
                    "experimental_idx2_ingress_prefetch_gather_only": int(experimental_idx2_ingress_prefetch_gather_only),
                    "experimental_idx2_ingress_prefetch_carry_to_apply_enable": int(experimental_idx2_ingress_prefetch_carry_to_apply_enable),
                    "experimental_idx2_ingress_prefetch_apply_max_inflight": int(experimental_idx2_ingress_prefetch_apply_max_inflight),
                    "experimental_idx2_ingress_prefetch_apply_outstanding_reserve": int(experimental_idx2_ingress_prefetch_apply_outstanding_reserve),
                    "experimental_idx2_ingress_prefetch_apply_frontier_keep_pending": int(experimental_idx2_ingress_prefetch_apply_frontier_keep_pending),
                    "experimental_idx2_ingress_tail_guard_enable": int(experimental_idx2_ingress_tail_guard_enable),
                    "experimental_idx2_ingress_budget_adapt_enable": int(experimental_idx2_ingress_budget_adapt_enable),
                    "experimental_idx2_ingress_budget_adapt_max_per_tick": int(experimental_idx2_ingress_budget_adapt_max_per_tick),
                    "experimental_idx2_ingress_budget_adapt_q_depth": int(experimental_idx2_ingress_budget_adapt_q_depth),
                    "experimental_noc_rowidx_prefetch_enable": int(experimental_noc_rowidx_prefetch_enable),
                    "experimental_noc_rowidx_prefetch_budget_per_tick": int(experimental_noc_rowidx_prefetch_budget_per_tick),
                    "experimental_noc_rowidx_cache_rows": int(experimental_noc_rowidx_cache_rows),
                    "experimental_noc_rowidx_prefetch_gather_only": int(experimental_noc_rowidx_prefetch_gather_only),
                    "experimental_noc_rowidx_prefetch_detached_enable": int(experimental_noc_rowidx_prefetch_detached_enable),
                    "experimental_noc_rowidx_prefetch_carry_to_apply_enable": int(experimental_noc_rowidx_prefetch_carry_to_apply_enable),
                    "experimental_noc_rowidx_hot_touch_min": int(experimental_noc_rowidx_hot_touch_min),
                    "experimental_noc_rowidx_budget_adapt_enable": int(experimental_noc_rowidx_budget_adapt_enable),
                    "experimental_noc_rowidx_budget_adapt_max_per_tick": int(experimental_noc_rowidx_budget_adapt_max_per_tick),
                    "experimental_noc_rowidx_budget_adapt_q_depth": int(experimental_noc_rowidx_budget_adapt_q_depth),
                    "weight_sram_model_enable": int(sram_model_enable),
                    "weight_idx_sram_enable": int(sram_weight_idx_enable),
                    "weight_l0_sram_enable": int(sram_weight_l0_enable),
                    "weight_idx_sram_capacity_bytes": int(sram_weight_idx_capacity_bytes),
                    "weight_l0_sram_capacity_bytes": int(sram_weight_l0_capacity_bytes),
                    "weight_idx_sram_banks": int(sram_weight_idx_banks),
                    "weight_l0_sram_banks": int(sram_weight_l0_banks),
                    "weight_sram_ports_per_bank": int(sram_weight_ports_per_bank),
                    "weight_sram_bank_interleave_bytes": int(sram_weight_bank_interleave_bytes),
                    "weight_sram_t_read_cycles": int(sram_weight_t_read_cycles),
                    "weight_sram_t_write_cycles": int(sram_weight_t_write_cycles),
                    "weight_sram_sample_log2": int(sram_weight_sample_log2),
                    "weight_idx_sram_base": int(sram_weight_idx_base),
                    "weight_l0_sram_base": int(sram_weight_l0_base),
                    "weight_l0_sram_slots": int(sram_weight_l0_slots),
                    "state_sram_enable": int(sram_model_enable and sram_state_enable),
                    "state_sram_capacity_bytes": int(sram_state_capacity_bytes),
                    "state_sram_banks": int(sram_state_banks),
                    "state_sram_ports_per_bank": int(sram_state_ports_per_bank),
                    "state_sram_bank_interleave_bytes": int(sram_state_bank_interleave_bytes),
                    "state_sram_t_read_cycles": int(sram_state_t_read_cycles),
                    "state_sram_t_write_cycles": int(sram_state_t_write_cycles),
                    "state_sram_sample_log2": int(sram_state_sample_log2),
                    "state_sram_vmem_base": int(sram_state_vmem_base),
                    "state_sram_refrac_base": int(sram_state_refrac_base),
                    "state_sram_last_spike_base": int(sram_state_last_spike_base),
                    "diag_fire_log": 1 if diag_fire_log else 0,
                    "step_seed_only_mode": int(step.get("seed_only_mode", 0)),
                }

            _apply_workload_params_to_component_params(
                core_params,
                workload_impl=workload_impl,
                workload_stats_modules=workload_stats_modules,
                workload_node_params=workload_node_params,
            )

            # Optional per-window read budget override:
            # - window_read_budget==0 disables the budget (forces drain-based Apply in microbench).
            # - window_read_budget<0 (or missing) keeps the core default (1024).
            if "window_read_budget" in mesh:
                try:
                    wrb = int(mesh.get("window_read_budget"))
                except Exception:
                    wrb = -1
                if wrb >= 0:
                    core_params["window_read_budget"] = wrb

            if is_naive:
                # Naive baseline: no GAS/window pipeline (no GatherBufferIF; immediate weight read per spike).
                core_params["gas_enable"] = 0
                core_params["gas_window_mode"] = 0
                core_params["window_read_enable"] = 0
                core_params["apply_acc_enable"] = 0
                # Disable within-step cascading for naive_raw only:
                # - emitted spikes are tagged for next step (seq+1)
                # - receiver gates packets by step_seq
                core_params["naive_raw_step_sync_enable"] = (1 if exec_mode == "naive_raw" else 0)

                if exec_mode == "naive_raw":
                    core_params["disable_weight_cache"] = 1
                    core_params["bcsr_populate_weight_cache_enable"] = 0
                    core_params["bcsr_block_inflight_coalesce_enable"] = 0
                    core_params["bcsr_colidx_inflight_coalesce_enable"] = 0

            # BCSR semantic correctness (sampled):
            # Enable only on the same target core as raw BCSR merge-read byte-exact verification,
            # to keep overhead negligible (one core only) while still catching systematic mapping bugs.
            bcsr_merge_verify_enable = int(debug.get("bcsr_merge_read_verify_enable", 0) or 0)
            bcsr_merge_verify_target_pe = int(debug.get("bcsr_merge_read_verify_target_pe", 0) or 0)
            bcsr_merge_verify_target_core = int(debug.get("bcsr_merge_read_verify_target_core", 0) or 0)
            core_params["bcsr_semantic_verify_enable"] = (
                1
                if (
                    (not is_naive)
                    and synapse_weight_mode == "bcsr_gas"
                    and bcsr_merge_verify_enable
                    and global_bcsr_available
                    and (not force_dense)
                    and i == bcsr_merge_verify_target_pe
                    and core_idx == bcsr_merge_verify_target_core
                )
                else 0
            )
            core_params["bcsr_semantic_verify_max_edges"] = 64
            core_params["bcsr_semantic_verify_max_mismatch"] = int(mesh.get("byte_exact_verify_max_mismatch", 8) or 8)

            if enable_bcsr:
                core_params["index_mode"] = "bcsr_post_row"
                core_params["bcsr_block_rows"] = int(core_meta.get("br", global_bcsr_offsets.get("br", 1)))
                core_params["bcsr_block_cols"] = int(core_meta.get("bc", global_bcsr_offsets.get("bc", 16)))
                core_params["bcsr_val_bytes"] = int(core_meta.get("val_bytes", global_bcsr_offsets.get("val_bytes", 4)))
                core_params["bcsr_idx_bytes"] = int(core_meta.get("idx_bytes", global_bcsr_offsets.get("idx_bytes", 4)))
                core_params["bcsr_rowptr_offset"] = int(core_meta.get("rowptr_offset", global_bcsr_offsets.get("rowptr_offset", 0)))
                core_params["bcsr_colidx_offset"] = int(core_meta.get("colidx_offset", global_bcsr_offsets.get("colidx_offset", 0)))
                core_params["bcsr_blockdata_offset"] = int(core_meta.get("blockdata_offset", global_bcsr_offsets.get("blockdata_offset", 0)))
                core_params["bcsr_blockids_offset"] = int(core_meta.get("blockids_offset", global_bcsr_offsets.get("blockids_offset", 0)))
                core_params["bcsr_layout_mode"] = str(
                    core_meta.get("layout_mode", global_bcsr_offsets.get("layout_mode", "flat")) or "flat"
                )
                core_params["bcsr_colidx_row_stride_bytes"] = int(
                    core_meta.get("colidx_row_stride_bytes", global_bcsr_offsets.get("colidx_row_stride_bytes", 0)) or 0
                )
                core_params["bcsr_blockdata_row_stride_bytes"] = int(
                    core_meta.get("blockdata_row_stride_bytes", global_bcsr_offsets.get("blockdata_row_stride_bytes", 0)) or 0
                )
                core_params["bcsr_blockids_row_stride_bytes"] = int(
                    core_meta.get("blockids_row_stride_bytes", global_bcsr_offsets.get("blockids_row_stride_bytes", 0)) or 0
                )
                core_params["bcsr_block_fetch_mode"] = str(mesh.get("bcsr_block_fetch_mode", "full_block") or "full_block")

                # Defaults (full): keep prior behavior unless overridden by bcsr_opt_level.
                core_params["bcsr_row_index_cache_cap"] = 64
                core_params["bcsr_row_index_cache_auto_fit"] = 1
                core_params["bcsr_row_index_prefetch_mode"] = "auto"
                core_params["bcsr_row_index_prefetch_all_rows_threshold"] = 1024
                core_params["bcsr_row_index_prefetch_all_rows_max_bytes"] = 64 * 1024

                core_params["bcsr_block_cache_cap"] = 256
                core_params["bcsr_block_cache_policy"] = "lru"
                core_params["bcsr_block_cache_auto_tune"] = 1
                core_params["bcsr_block_cache_max_bytes"] = 64 * 1024 * 1024
                core_params["bcsr_block_cache_tune_miss_ratio"] = 0.05
                core_params["bcsr_block_cache_tune_min_misses"] = 64

                # Apply opt-level mapping.
                if bcsr_opt_level == "none":
                    # Pure format: no row-index cache/prefetch, no block cache, no inflight coalesce, no populate.
                    core_params["bcsr_row_index_cache_cap"] = 0
                    core_params["bcsr_row_index_cache_auto_fit"] = 0
                    core_params["bcsr_row_index_prefetch_mode"] = "off"
                    core_params["bcsr_block_cache_cap"] = 0
                    core_params["bcsr_block_cache_auto_tune"] = 0
                    core_params["bcsr_populate_weight_cache_enable"] = 0
                    core_params["bcsr_block_inflight_coalesce_enable"] = 0
                    core_params["bcsr_colidx_inflight_coalesce_enable"] = 0
                elif bcsr_opt_level == "index_only":
                    # Index-only: keep colidx resident (row-index cache + one-shot prefetch), but keep blockdata uncached.
                    core_params["bcsr_row_index_prefetch_mode"] = "all_rows"
                    core_params["bcsr_block_cache_cap"] = 0
                    core_params["bcsr_block_cache_auto_tune"] = 0
                    core_params["bcsr_populate_weight_cache_enable"] = 0
                    core_params["bcsr_block_inflight_coalesce_enable"] = 0

                # Naive_raw baseline keeps blockdata uncached and disables coalesce/populate regardless of opt level;
                # only row-index cache/prefetch is controlled by bcsr_opt_level above (none disables it).
                if exec_mode == "naive_raw":
                    core_params["bcsr_block_cache_cap"] = 0
                    core_params["bcsr_block_cache_auto_tune"] = 0
                    core_params["bcsr_populate_weight_cache_enable"] = 0
                    core_params["bcsr_block_inflight_coalesce_enable"] = 0
                    core_params["bcsr_colidx_inflight_coalesce_enable"] = 0
                    if bcsr_opt_level != "none":
                        core_params["bcsr_row_index_prefetch_mode"] = "all_rows"

                if is_gas:
                    # GAS/window is the only optimizer we want to credit:
                    # - Disable BCSR-level cache/prefetch/populate to avoid double-counting with GAS aggregation.
                    # - Keep in-flight coalescing enabled so window-read budget/outstanding accounting stays on
                    #   "real reads" (not per-edge), guaranteeing forward progress.
                    core_params["bcsr_row_index_cache_cap"] = 0
                    core_params["bcsr_row_index_cache_auto_fit"] = 0
                    core_params["bcsr_row_index_prefetch_mode"] = "off"
                    core_params["bcsr_block_cache_cap"] = 0
                    core_params["bcsr_block_cache_auto_tune"] = 0
                    core_params["bcsr_populate_weight_cache_enable"] = 0
                    core_params["bcsr_colidx_inflight_coalesce_enable"] = 1
                    core_params["bcsr_block_inflight_coalesce_enable"] = 1

            if verify_routing:
                core_params["verify_routing_weights"] = 1
            core_params["quiet_finish_logs"] = 1
            # Default to quiet runs; enable explicitly via local_run_config.json debug.core_verbose.
            core_params["verbose"] = int(debug.get("core_verbose", 0) or 0)
            core_params["base_addr"] = pe_weight_base_i + core_idx * per_core_weight_stride
            core_params["bcsr_force_file_read"] = 0
            core_params["verify_weights"] = 0
            core_params["weight_verify_samples"] = 0
            core_params["verify_log_each_sample"] = 0
            core_params["verify_against_file"] = 0
            core_params["verify_file_template"] = ""
            core_params["local_storage_enable"] = int(local_storage_enable)
            core_params["pe_internal_cpe_enable"] = int(pe_internal_cpe_enable)
            core_params["pe_internal_pod_enable"] = int(pe_internal_pod_enable)
            core_params["pe_internal_pod_count"] = int(pe_internal_pod_count)
            core_params["pe_internal_pod_size"] = int(pe_internal_pod_size)
            core_params["pe_internal_pod_metadata_enable"] = int(pe_internal_pod_metadata_enable)
            core_params["pe_internal_pod_owner_enable"] = int(pe_internal_pod_owner_enable)
            core_params["pe_internal_pod_join_enable"] = int(pe_internal_pod_join_enable)
            core_params["pe_internal_pod_ready_enable"] = int(pe_internal_pod_ready_enable)
            core_params["pe_internal_pod_owner_entries"] = int(pe_internal_pod_owner_entries)
            core_params["pe_internal_pod_join_entries"] = int(pe_internal_pod_join_entries)
            core_params["pe_internal_pod_ready_entries"] = int(pe_internal_pod_ready_entries)

            core_final_params = _add_params_with_overrides(
                core_subcomponent,
                role="pe.core",
                component_type="SnnDL.SnnPESubComponent",
                name=f"multicore_pe_{i}.core{core_idx}",
                tags={"pe": int(i), "core": int(core_idx), "layer": str(layer_name)},
                params=core_params,
                override_engine=override_engine,
                override_report=override_report,
            )
            core_sram_effective = dict(
                make_effective_sram_provenance(mesh=mesh, final_pe_core_params=core_final_params)["effective"]
            )
            if core_sram_effective and not effective_cfg.get("sram_effective_pe_core"):
                effective_cfg["sram_effective_pe_core"] = dict(core_sram_effective)

            if is_gas:
                core_memory = core_subcomponent.setSubComponent("memory", "SnnDL.GatherBufferIF")
                window_read_debug_enabled = bool(debug.get("window_read_debug", False))
                window_read_debug_all = bool(debug.get("window_read_debug_all_cores", False))
                debug_target_pe = int(debug.get("debug_target_pe", 0))
                debug_target_core = int(debug.get("debug_target_core", 0))
                # Dense microbench defaults to strict cacheline mode to avoid accidental row-streaming/overfetch,
                # but experiments may intentionally disable it (e.g., to study gap-merge behavior) via env override.
                # NOTE: this only affects force_dense scenarios (microbench_dense); BCSR mesh runs are unaffected.
                dense_strict_cacheline = bool(force_dense)
                if "dense_strict_cacheline" in gas and gas.get("dense_strict_cacheline") is not None:
                    dense_strict_cacheline = bool(gas.get("dense_strict_cacheline"))
                else:
                    v_dense_strict = os.environ.get("MESH_DENSE_STRICT_CACHELINE", "1").strip().lower()
                    if v_dense_strict in ("0", "false", "no", "off"):
                        dense_strict_cacheline = False
                effective_merge_policy = gas_merge_policy
                effective_gap_merge_enable = 1
                effective_gap_merge_k_bytes = gas_gap_k_bytes
                effective_lmax_bytes = gas_lmax_bytes
                effective_k_adapt_enable = 1
                # Gap/row-window merging needs staging (defer issue until Apply) so we can build segments.
                # When disabled, GatherBufferIF issues per-(merge_policy) granule immediately and cannot absorb gaps.
                effective_defer_issue_until_apply = 1 if (
                    int(gas_gap_k_bytes) > 0
                    or int(gas_row_window_bytes) > 0
                    or int(gas_row_window_timeout_ns) > 0
                    or int(gas_vlf_enable) > 0
                ) else 0
                # Script-level override: force staging even when k/rowwin/tmo are zero.
                # This is useful for calibration sweeps where we want a consistent "full GAS" baseline.
                force_defer = False
                if "force_defer" in gas and gas.get("force_defer") is not None:
                    force_defer = bool(gas.get("force_defer"))
                else:
                    v_force_defer = os.environ.get("MESH_GAS_FORCE_DEFER", "0").strip().lower()
                    force_defer = v_force_defer in ("1", "true", "yes", "on")
                if force_defer:
                    effective_defer_issue_until_apply = 1
                if dense_strict_cacheline:
                    effective_merge_policy = "cacheline"
                    effective_gap_merge_enable = 0
                    effective_gap_merge_k_bytes = 0
                    effective_lmax_bytes = int(subcomp_line_bytes)
                    effective_k_adapt_enable = 0
                    effective_defer_issue_until_apply = 0

                # Record effective params for post-run analysis (prevents local_run_config.json from lying by omission).
                effective_cfg["per_core"].append(
                    {
                        "pe": int(i),
                        "core": int(core_idx),
                        "memory_impl": "SnnDL.GatherBufferIF",
                        "dense_read_granularity": ("cacheline" if dense_strict_cacheline else str(effective_merge_policy)),
                        "gatherbuf": {
                            "merge_policy_effective": str(effective_merge_policy),
                            "gap_merge_enable_effective": int(effective_gap_merge_enable),
                            "gap_merge_k_bytes_effective": int(effective_gap_merge_k_bytes),
                            "burst_bytes_max_effective": int(effective_lmax_bytes),
                            "vlf_enable": int(gas_vlf_enable),
                            "vlf_run_enable": int(gas_vlf_run_enable),
                            "k_adapt_enable_effective": int(effective_k_adapt_enable),
                            "defer_issue_until_apply_effective": int(effective_defer_issue_until_apply),
                            "force_defer_effective": int(force_defer),
                            "sort_policy": str(gas_sort_policy),
                            "row_bytes_guess": int(gas_row_bytes_guess),
                            "bank_bits": int(gas_bank_bits),
                            "bank_shift": int(gas_bank_shift),
                            "bank_auto_enable": int(gas_bank_auto_enable),
                            "apply_issue_policy": str(gas_apply_issue_policy),
                            "experimental_retire_policy": str(effective_retire_policy),
                            "experimental_gcss_phase_breakdown_enable": int(gas_experimental_gcss_phase_breakdown_enable),
                            "experimental_retire_shadow_per_post_enable": int(gas_experimental_retire_shadow_per_post_enable),
                            "experimental_gcss_vlf_queue_policy": str(gas_experimental_gcss_vlf_queue_policy),
                            "experimental_gcss_vlf_fair_band_size": int(gas_experimental_gcss_vlf_fair_band_size),
                            "experimental_gcss_vlf_bounded_rescue_enable": int(gas_experimental_gcss_vlf_bounded_rescue_enable),
                            "experimental_gcss_vlf_bounded_rescue_scan_limit": int(gas_experimental_gcss_vlf_bounded_rescue_scan_limit),
                            "experimental_gcss_vlf_bounded_rescue_head_wait_cycles": int(gas_experimental_gcss_vlf_bounded_rescue_head_wait_cycles),
                            "experimental_gcss_vlf_bounded_rescue_depth_threshold": int(gas_experimental_gcss_vlf_bounded_rescue_depth_threshold),
                            "apply_frags_per_issue": int(gas_apply_frags_per_issue),
                            "apply_bank_credit": int(gas_apply_bank_credit),
                            "apply_age_fair_ns": int(gas_apply_age_fair_ns),
                            "dram_cmd_cost_merge_enable": int(gas_dram_cmd_cost_merge_enable),
                            "dram_cmd_t_row_hit_ns": int(gas_dram_cmd_t_row_hit_ns),
                            "dram_cmd_t_row_miss_ns": int(gas_dram_cmd_t_row_miss_ns),
                            "dram_cmd_offline_model_enable": int(gas_dram_cmd_offline_model_enable),
                            "dram_cmd_offline_model_applied": int(dram_cmd_offline_meta.get("applied", 0)),
                            "dram_cmd_offline_model_reason": str(dram_cmd_offline_meta.get("reason", "")),
                            "sram_bytes": 256 * 1024,
                        },
                        "sram": {
                            "model_enable": int(sram_model_enable),
                            "weight_idx_enable": int(sram_weight_idx_enable),
                            "weight_l0_enable": int(sram_weight_l0_enable),
                            "state_enable": int(sram_state_enable),
                            "effective_pe_core": dict(core_sram_effective),
                        },
                        "idx2_ingress": {
                            "prefetch_enable": int(experimental_idx2_ingress_prefetch_enable),
                            "prefetch_budget_per_tick": int(experimental_idx2_ingress_prefetch_budget_per_tick),
                            "prefetch_cache_entries": int(experimental_idx2_ingress_prefetch_cache_entries),
                            "prefetch_max_inflight": int(experimental_idx2_ingress_prefetch_max_inflight),
                            "prefetch_gather_only": int(experimental_idx2_ingress_prefetch_gather_only),
                            "prefetch_carry_to_apply_enable": int(experimental_idx2_ingress_prefetch_carry_to_apply_enable),
                            "prefetch_apply_max_inflight": int(experimental_idx2_ingress_prefetch_apply_max_inflight),
                            "prefetch_apply_outstanding_reserve": int(experimental_idx2_ingress_prefetch_apply_outstanding_reserve),
                            "prefetch_apply_frontier_keep_pending": int(experimental_idx2_ingress_prefetch_apply_frontier_keep_pending),
                            "tail_guard_enable": int(experimental_idx2_ingress_tail_guard_enable),
                            "budget_adapt_enable": int(experimental_idx2_ingress_budget_adapt_enable),
                            "budget_adapt_max_per_tick": int(experimental_idx2_ingress_budget_adapt_max_per_tick),
                            "budget_adapt_q_depth": int(experimental_idx2_ingress_budget_adapt_q_depth),
                        },
                        "noc_rowidx": {
                            "prefetch_enable": int(experimental_noc_rowidx_prefetch_enable),
                            "prefetch_budget_per_tick": int(experimental_noc_rowidx_prefetch_budget_per_tick),
                            "cache_rows": int(experimental_noc_rowidx_cache_rows),
                            "prefetch_gather_only": int(experimental_noc_rowidx_prefetch_gather_only),
                            "prefetch_detached_enable": int(experimental_noc_rowidx_prefetch_detached_enable),
                            "prefetch_carry_to_apply_enable": int(experimental_noc_rowidx_prefetch_carry_to_apply_enable),
                            "hot_touch_min": int(experimental_noc_rowidx_hot_touch_min),
                            "budget_adapt_enable": int(experimental_noc_rowidx_budget_adapt_enable),
                            "budget_adapt_max_per_tick": int(experimental_noc_rowidx_budget_adapt_max_per_tick),
                            "budget_adapt_q_depth": int(experimental_noc_rowidx_budget_adapt_q_depth),
                        },
                    }
                )

                core_mem_verbose = (
                    2 if (window_read_debug_enabled and (window_read_debug_all or (i == debug_target_pe and core_idx == debug_target_core))) else 0
                )
                if gbi_verbose_override is not None:
                    owner_ok = (
                        (gbi_verbose_owner_node < 0 or int(i) == int(gbi_verbose_owner_node))
                        and (gbi_verbose_owner_core < 0 or int(core_idx) == int(gbi_verbose_owner_core))
                    )
                    if owner_ok:
                        core_mem_verbose = int(gbi_verbose_override)

                core_memory_params: Dict[str, Any] = {
                    "verbose": int(core_mem_verbose),
                    "merge_policy": effective_merge_policy,
                    "sort_policy": str(gas_sort_policy),
                    "defer_issue_until_apply": int(effective_defer_issue_until_apply),
                    "gap_merge_enable": effective_gap_merge_enable,
                    "gap_merge_k_bytes": effective_gap_merge_k_bytes,
                    "burst_bytes_max": effective_lmax_bytes,
                    "vlf_enable": int(gas_vlf_enable),
                    "vlf_run_enable": int(gas_vlf_run_enable),
                    "k_adapt_enable": effective_k_adapt_enable,
                    "row_bytes_guess": int(gas_row_bytes_guess),
                    "bank_bits": int(gas_bank_bits),
                    "bank_shift": int(gas_bank_shift),
                    "bank_auto_enable": int(gas_bank_auto_enable),
                    "apply_issue_policy": str(gas_apply_issue_policy),
                    "apply_frags_per_issue": int(gas_apply_frags_per_issue),
                    "apply_bank_credit": int(gas_apply_bank_credit),
                    "apply_age_fair_ns": int(gas_apply_age_fair_ns),
                    "dram_cmd_cost_merge_enable": int(gas_dram_cmd_cost_merge_enable),
                    "dram_cmd_t_row_hit_ns": int(gas_dram_cmd_t_row_hit_ns),
                    "dram_cmd_t_row_miss_ns": int(gas_dram_cmd_t_row_miss_ns),
                    "sram_bytes": 256 * 1024,
                    # Enable coarse row-window if either bytes-threshold or timeout is configured.
                    # Also enable it when forcing staging (MESH_GAS_FORCE_DEFER=1) so we can build segments and
                    # surface payload/burst stats even for the "k=0,rowwin=0" baseline.
                    "row_window_enable": 1 if (
                        gas_row_window_bytes > 0
                        or gas_row_window_timeout_ns > 0
                        or (force_defer and int(effective_defer_issue_until_apply) == 1)
                    ) else 0,
                    "row_window_bytes": gas_row_window_bytes,
                    "row_window_timeout_ns": gas_row_window_timeout_ns,
                    "max_inflight_reads": gas_max_inflight,
                    "flush_after_scatter": 1,
                    "strict_mode": 1,
                    "window_auto": 1,
                    "step_gate_enable": 1 if global_step_sync_enable else 0,
                    "window_cycles_gather": int(gas_window_cycles.get("gather", 200)),
                    "window_cycles_apply": int(gas_window_cycles.get("apply", 40)),
                    "window_cycles_scatter": int(gas_window_cycles.get("scatter", 40)),
                    # Keep enabled: stage events are required to drive/control the GAS stage machine
                    # (BeginApply/EndApply/BeginScatter/EndScatter) via upstream handler callbacks.
                    # Thermal window tracing can opt back into per-core window metric exports.
                    "emit_stage_events": 1,
                    "emit_stage_events_lenient": 0,
                    "experimental_stepgate_progress_enable": 1 if gbi_stepgate_progress_enable else 0,
                    "experimental_stepgate_progress_period_cycles": int(gbi_stepgate_progress_period_cycles),
                    "experimental_stepgate_progress_max_reports": int(gbi_stepgate_progress_max_reports),
                    "experimental_stepgate_progress_owner_node": int(gbi_stepgate_progress_owner_node),
                    "experimental_stepgate_progress_owner_core": int(gbi_stepgate_progress_owner_core),
                    "experimental_stepgate_apply_finish_poll_period_cycles": int(gbi_stepgate_apply_finish_poll_period_cycles),
                    "export_granules_csv": "",
                    "export_window_metrics_csv": resolve_window_metrics_export_path(
                        run_output_dir=str(run_output_dir),
                        pe_id=int(i),
                        core_id=int(core_idx),
                        mesh=mesh,
                    ),
                    "node_id": i,
                    "core_id": core_idx,
                    # Byte-exact correctness validation (optional):
                    # - Dense microbench: dense_rowcol_v1 (synthetic pattern)
                    # - BCSR mesh: raw_bcsr_v1 (compare against raw coreXX.bcsr.bin slice)
                    "byte_exact_verify_enable": 0,
                    "byte_exact_verify_mode": "",
                    "byte_exact_verify_row_scale": int(mesh.get("byte_exact_verify_row_scale", 1024) or 1024),
                    "byte_exact_verify_max_mismatch": int(mesh.get("byte_exact_verify_max_mismatch", 8) or 8),
                    "byte_exact_verify_base_addr": int(core_base_addr),
                    "byte_exact_verify_rows": int(neurons_per_core),
                    "byte_exact_verify_cols": int(global_weights_cols),
                }

                # Dense microbench byte-exact (synthetic row/col pattern).
                dense_byte_exact_enable = int(mesh.get("byte_exact_verify_enable", 0) or 0)
                dense_byte_exact_mode = str(mesh.get("byte_exact_verify_mode", "") or "").strip()
                if dense_byte_exact_enable and dense_byte_exact_mode:
                    core_memory_params.update({
                        "byte_exact_verify_enable": 1,
                        "byte_exact_verify_mode": dense_byte_exact_mode,
                    })

                # BCSR merge-read byte-exact (raw file slice compare).
                bcsr_merge_verify_enable = int(debug.get("bcsr_merge_read_verify_enable", 0) or 0)
                bcsr_merge_verify_sample_bytes = int(debug.get("bcsr_merge_read_verify_sample_bytes", 64) or 64)
                bcsr_merge_verify_max_resps = int(debug.get("bcsr_merge_read_verify_max_resps", 8) or 8)
                bcsr_merge_verify_target_pe = int(debug.get("bcsr_merge_read_verify_target_pe", 0) or 0)
                bcsr_merge_verify_target_core = int(debug.get("bcsr_merge_read_verify_target_core", 0) or 0)
                if (
                    synapse_weight_mode == "bcsr_gas"
                    and bcsr_merge_verify_enable
                    and global_bcsr_available
                    and (not force_dense)
                    and i == bcsr_merge_verify_target_pe
                    and core_idx == bcsr_merge_verify_target_core
                ):
                    bcsr_file_path = os.path.join(global_bcsr_dir, f"pe{i:02d}", f"core{core_idx:02d}.bcsr.bin")
                    core_memory_params.update({
                        "byte_exact_verify_enable": 1,
                        "byte_exact_verify_mode": "raw_bcsr_v1",
                        "byte_exact_verify_file_path": bcsr_file_path,
                        "byte_exact_verify_sample_bytes": bcsr_merge_verify_sample_bytes,
                        "byte_exact_verify_max_resps": bcsr_merge_verify_max_resps,
                        # Segment offsets (file-relative) for coverage-driven verification:
                        # rowptr=[rowptr_offset, colidx_offset), colidx=[colidx_offset, blockdata_offset), blockdata=[blockdata_offset, file_size)
                        "byte_exact_verify_rowptr_offset": int(core_meta.get("rowptr_offset", global_bcsr_offsets.get("rowptr_offset", 0))),
                        "byte_exact_verify_colidx_offset": int(core_meta.get("colidx_offset", global_bcsr_offsets.get("colidx_offset", 0))),
                        "byte_exact_verify_blockdata_offset": int(core_meta.get("blockdata_offset", global_bcsr_offsets.get("blockdata_offset", 0))),
                        # Keep it target-local even if someone later enables globally.
                        "byte_exact_verify_owner_node": int(i),
                        "byte_exact_verify_owner_core": int(core_idx),
                        # Not used by raw_bcsr_v1, but we keep them consistent anyway.
                        "byte_exact_verify_rows": 0,
                        "byte_exact_verify_cols": 0,
                    })

                _add_params_with_overrides(
                    core_memory,
                    role="pe.core.memory_if",
                    component_type="SnnDL.GatherBufferIF",
                    name=f"multicore_pe_{i}.core{core_idx}.memory",
                    tags={"pe": int(i), "core": int(core_idx), "layer": str(layer_name)},
                    params=core_memory_params,
                    override_engine=override_engine,
                    override_report=override_report,
                )
            else:
                # naive_raw baseline:
                # Use a cacheline fragmenter so memHierarchy GetS counters reflect physical cacheline traffic
                # (otherwise variable-size reads would be counted as 1 GetS and bytes_est_total would be meaningless).
                if exec_mode == "naive_raw":
                    core_memory = core_subcomponent.setSubComponent("memory", "SnnDL.CachelineFragmentMemIF")
                    _add_params_with_overrides(
                        core_memory,
                        role="pe.core.memory_if",
                        component_type="SnnDL.CachelineFragmentMemIF",
                        name=f"multicore_pe_{i}.core{core_idx}.memory",
                        tags={"pe": int(i), "core": int(core_idx), "layer": str(layer_name)},
                        params={
                            "verbose": 0,
                            "max_inflight_reads": int(naive_max_inflight_reads),
                        },
                        override_engine=override_engine,
                        override_report=override_report,
                    )
                    effective_cfg["per_core"].append(
                        {
                            "pe": int(i),
                            "core": int(core_idx),
                            "memory_impl": "SnnDL.CachelineFragmentMemIF",
                            "dense_read_granularity": "cacheline",
                        }
                    )
                else:
                    core_memory = core_subcomponent.setSubComponent("memory", "memHierarchy.standardInterface")
                    _add_params_with_overrides(
                        core_memory,
                        role="pe.core.memory_if",
                        component_type="memHierarchy.standardInterface",
                        name=f"multicore_pe_{i}.core{core_idx}.memory",
                        tags={"pe": int(i), "core": int(core_idx), "layer": str(layer_name)},
                        params={},
                        override_engine=override_engine,
                        override_report=override_report,
                    )
                    effective_cfg["per_core"].append(
                        {
                            "pe": int(i),
                            "core": int(core_idx),
                            "memory_impl": "memHierarchy.standardInterface",
                            "dense_read_granularity": ("cacheline" if force_dense else "n/a"),
                        }
                    )

            if l1_enable:
                core_l1_cache = sst.Component(f"pe_{i}_core{core_idx}_l1", "memHierarchy.Cache")
                core_l1_params = {
                    "cache_frequency": "2GHz",
                    "cache_size": l1_size_str,
                    "associativity": str(l1_assoc),
                    "cache_line_size": l1_line_bytes_str,
                    "access_latency_cycles": "2",
                    "L1": "1",
                    "coherence_protocol": "none",
                    "debug": "0",
                    "verbose": "0",
                }
                _add_params_with_overrides(
                    core_l1_cache,
                    role="pe.l1_cache",
                    component_type="memHierarchy.Cache",
                    name=f"pe_{i}_core{core_idx}_l1",
                    tags={"pe": int(i), "core": int(core_idx), "layer": str(layer_name)},
                    params=core_l1_params,
                    override_engine=override_engine,
                    override_report=override_report,
                )
                try:
                    core_l1_cache.enableAllStatistics({"type": "sst.AccumulatorStatistic"})
                except Exception:
                    pass
                core_mem_link = sst.Link(f"pe_{i}_core{core_idx}_mem")
                core_mem_link.connect(
                    (core_memory, "lowlink", "1ns"),
                    (core_l1_cache, "highlink", "1ns"),
                )
                core_l1_to_bus_link = sst.Link(f"pe_{i}_core{core_idx}_l1_to_pe_bus")
                bus, bus_port = _resolve_bus_and_port(int(i), int(core_idx))
                core_l1_to_bus_link.connect(
                    (core_l1_cache, "lowlink", "5ns"),
                    (bus, bus_port, "5ns"),
                )
            else:
                core_mem_link = sst.Link(f"pe_{i}_core{core_idx}_mem_to_pe_bus")
                bus, bus_port = _resolve_bus_and_port(int(i), int(core_idx))
                core_mem_link.connect(
                    (core_memory, "lowlink", "5ns"),
                    (bus, bus_port, "5ns"),
                )

        nodes.append(node)
        if nic is not None:
            nics.append(nic)
        mesh_print(f"  PE{i} ({layer_name}): 阈值={v_thresh}, 权重地址=0x{int(node_params['base_addr']):x}")

    # Persist effective parameters for later analysis/validation.
    # Best-effort: never fail model construction because of IO.
    try:
        out_path = os.path.join(str(run_output_dir), "effective_config.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(effective_cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    mesh_print(f"✅ 创建{len(nodes)}个分层PE节点完成")
    return nodes, nics


def connect_mesh_router_links(*, routers: List[Any], mesh_size: int, noc_type: str = "merlin_mesh", link_latency: str = "5ns") -> int:
    noc = _normalize_noc_type(noc_type)
    builder = _resolve_noc_builder_module(noc)
    builder_name = "snndl_system.noc_multicast" if noc == "multicast_mesh" else "snndl_system.noc_merlin"
    connect_fn = getattr(builder, "connect_mesh_router_links", None)
    if not callable(connect_fn):
        raise RuntimeError(f"{builder_name}.connect_mesh_router_links not callable")

    result = _call_with_supported_kwargs(
        connect_fn,
        routers=routers,
        mesh_size=int(mesh_size),
        noc_type=str(noc),
        link_latency=str(link_latency),
    )
    count = _extract_connection_count(result)
    if count is None:
        count = _estimate_router_connection_count(routers=routers, mesh_size=int(mesh_size), noc_type=str(noc))
    return int(count)


def connect_spike_sources_to_pes(
    *,
    spike_sources: List[Tuple[Any, int]],
    nodes: List[Any],
    link_latency: str = "5ns",
) -> int:
    count = 0
    for spike_source, pe_id in spike_sources:
        if pe_id < len(nodes):
            spike_link = sst.Link(f"spike_source_{pe_id}_to_pe_{pe_id}")
            spike_link.connect(
                (spike_source, "spike_output", link_latency),
                (nodes[pe_id], "external_spike_input", link_latency),
            )
            count += 1
    return count


def connect_nics_to_routers(
    *,
    nics: List[Any],
    routers: List[Any],
    disable_network: bool,
    link_latency: str = "5ns",
    noc_type: str = "merlin_mesh",
) -> int:
    if disable_network:
        return 0
    noc = _normalize_noc_type(noc_type)
    builder = _resolve_noc_builder_module(noc)
    builder_name = "snndl_system.noc_multicast" if noc == "multicast_mesh" else "snndl_system.noc_merlin"
    connect_fn = getattr(builder, "connect_nics_to_routers", None)
    if not callable(connect_fn):
        raise RuntimeError(f"{builder_name}.connect_nics_to_routers not callable")

    result = _call_with_supported_kwargs(
        connect_fn,
        nics=nics,
        routers=routers,
        link_latency=str(link_latency),
        noc_type=str(noc),
        disable_network=bool(disable_network),
    )
    count = _extract_connection_count(result)
    if count is None:
        count = _estimate_nic_connection_count(nics=nics, routers=routers)
    return int(count)


def enable_accumulator_statistics(component: Any) -> None:
    component.enableAllStatistics({"type": "sst.AccumulatorStatistic"})


def enable_mesh_statistics(*, nodes: List[Any], routers: List[Any]) -> None:
    for node in nodes:
        # 以组件端注册表为唯一 source-of-truth：启用该组件已注册的全部统计项（随 workload-stats 模块动态变化）。
        enable_accumulator_statistics(node)

    for router in routers:
        router.enableStatistics(list([
            "router.packet_count",
            "router.network_load",
        ]))


def load_spike_data_files(
    *,
    script_file: str,
    input_layer: List[int],
    class_freqs: List[int],
) -> List[str]:
    spike_data_files: List[str] = []
    spike_dir = resolve_spike_data_dir(script_file)

    # 加载输入层(PE 0-3)的4类预生成数据
    class_names = ["A", "B", "C", "D"]
    for pe_id in input_layer:
        class_name = class_names[int(pe_id)]
        spike_file = resolve_complex_spike_file(spike_dir, int(pe_id), class_name)

        if not os.path.exists(spike_file):
            print(f"❌ 错误: 脉冲数据文件不存在: {spike_file}")
            print("请先运行: python3 scripts/generate_spike_data.py")
            raise SystemExit(1)

        spike_data_files.append(spike_file)

        count = 0
        with open(spike_file, "r") as f:
            for line in f:
                if not line.startswith("#"):
                    count += 1

        freqs = list(class_freqs)
        freq = freqs[int(pe_id)]
        mesh_print(f"  ✅ 加载PE{pe_id}: 类别{class_name} ({freq}Hz), {count}个脉冲事件")

    return spike_data_files




def build_spike_sources(
    *,
    enabled: bool,
    input_layer: List[int],
    nodes: List[Any],
    spike_data_files: List[str],
    neurons_per_core: int,
    num_cores_per_pe: int,
    neurons_per_pe: int,
) -> List[Tuple[Any, int]]:
    spike_sources: List[Tuple[Any, int]] = []
    if not enabled:
        mesh_print("⚠️ SpikeSource 已禁用 (ENABLE_SPIKE_SOURCE_FLAG=False)")
        return spike_sources

    for i, pe_id in enumerate(input_layer):
        if int(pe_id) >= len(nodes):
            continue
        spike_source = sst.Component(f"spike_source_{int(pe_id)}", "SnnDL.SpikeSource")
        spike_source.addParams({
            "verbose": 1,
            "dataset_path": spike_data_files[i],
            "neurons_per_core": int(neurons_per_core),
            "num_cores": int(num_cores_per_pe),
            "neurons_per_pe": int(neurons_per_pe),
            "neuron_offset": int(pe_id) * int(neurons_per_pe),
            "start_time_us": 0.05 + float(pe_id) * 0.05,
            "loop_dataset": 0,
            "source_id": int(pe_id),
        })
        spike_sources.append((spike_source, int(pe_id)))

    mesh_print(f"✅ 创建{len(spike_sources)}个SpikeSource（仅连接输入层PE 0-3）")
    return spike_sources


def build_mesh_4x4(
    *,
    run_output_dir: str,
    weights_dir: str,
    node_limit: int,
    mesh_size: int,
    layers: Dict[str, Any],
    mesh: Dict[str, Any],
    flags: Dict[str, Any],
    mem_layout: Dict[str, Any],
    gas: Dict[str, Any],
    step: Dict[str, Any],
    routing: Dict[str, Any],
    debug: Dict[str, Any],
    loader: Dict[str, Any],
    global_step_ctrl: Optional[Any],
    spike_source_enabled: bool,
    spike_data_files: List[str],
    debug_conn: bool,
    overrides: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    overrides_list: List[Dict[str, Any]] = list(overrides or [])
    override_engine: Optional[OverrideEngine] = None
    override_report: Optional[List[Dict[str, Any]]] = None
    if overrides_list:
        override_engine = OverrideEngine(overrides_list)
        override_report = []

    memory_system = str(mem_layout.get("memory_system", "memhierarchy_per_pe") or "memhierarchy_per_pe").strip().lower()
    if memory_system in ("memhierarchy", "memhierarchy_per_pe", "per_pe", "per-pe"):
        memory_builder = build_pe_memory_systems
    elif memory_system in ("memhierarchy_shared", "shared", "shared_bus", "shared-bus"):
        memory_builder = build_shared_memory_system
    else:
        raise RuntimeError(f"invalid mem_layout.memory_system={memory_system!r} (expected per_pe/shared)")

    # === 内存系统（含 WeightLoader） ===
    pe_memory_controllers, pe_memory_buses, pe_weight_loaders, enable_bcsr = memory_builder(
        node_limit=int(node_limit),
        num_cores_per_pe=int(mesh["num_cores_per_pe"]),
        neurons_per_core=int(mesh["neurons_per_core"]),
        neurons_per_pe=int(mesh["neurons_per_pe"]),
        global_weights_cols=int(mesh["global_weights_cols"]),
        per_core_weight_stride=int(mem_layout["per_core_weight_stride"]),
        pe_weight_region_stride=int(mem_layout["pe_weight_region_stride"]),
        base_addr_global_shift=int(mem_layout["base_addr_global_shift"]),
        pe_mem_addr_range=int(loader["pe_mem_addr_range"]),
        mem_backend=str(mem_layout.get("mem_backend", "simple") or "simple"),
        ramulator2_config_file=str(mem_layout.get("ramulator2_config_file", "") or ""),
        simplemem_access_time=str(mem_layout.get("simplemem_access_time", "100ns") or "100ns"),
        ramulator2_admission_queue_size=(
            int(mem_layout["ramulator2_admission_queue_size"])
            if "ramulator2_admission_queue_size" in mem_layout
            else None
        ),
        ramulator2_admission_issue_budget_per_cycle=(
            int(mem_layout["ramulator2_admission_issue_budget_per_cycle"])
            if "ramulator2_admission_issue_budget_per_cycle" in mem_layout
            else None
        ),
        ramulator2_max_requests_per_cycle=(
            int(mem_layout["ramulator2_max_requests_per_cycle"])
            if "ramulator2_max_requests_per_cycle" in mem_layout
            else None
        ),
        loader_verbose=int(loader.get("loader_verbose", 0) or 0),
        loader_chunk_bytes=int(loader["loader_chunk_bytes"]),
        loader_timed_seed_enable=bool(loader["loader_timed_seed_enable"]),
        loader_timed_seed_allow_cache=bool(loader["loader_timed_seed_allow_cache"]),
        loader_verify_readback=bool(loader["loader_verify_readback"]),
        loader_verify_bytes=int(loader["loader_verify_bytes"]),
        loader_verify_mode=str(loader.get("loader_verify_mode", "")),
        loader_verify_samples=int(loader.get("loader_verify_samples", 0)),
        loader_verify_seed=int(loader.get("loader_verify_seed", 0)),
        loader_verify_colidx_start=int(loader["loader_verify_colidx_start"]),
        loader_diag_timed_read=bool(loader["loader_diag_timed_read"]),
        loader_diag_timed_read_colidx_start=int(loader["loader_diag_timed_read_colidx_start"]),
        loader_write_pattern_mode=str(loader.get("loader_write_pattern_mode", "")),
        loader_write_pattern_row_scale=int(loader.get("loader_write_pattern_row_scale", 1024)),
        global_bcsr_available=bool(mesh.get("global_bcsr_available", False)),
        global_bcsr_dir=str(mesh.get("global_bcsr_dir", "")),
        gcss_dir=str(mesh.get("gcss_dir", "") or ""),
        gcss2_dir=str(mesh.get("gcss2_dir", "") or ""),
        gcssvlf_dir=str(mesh.get("gcssvlf_dir", "") or ""),
        gcssplp_dir=str(mesh.get("gcssplp_dir", "") or ""),
        gcssnt_dir=str(mesh.get("gcssnt_dir", "") or ""),
        global_bcsr_offsets=dict(mesh.get("global_bcsr_offsets", {}) or {}),
        synapse_weight_mode=str(mesh.get("synapse_weight_mode", "bcsr_gas") or "bcsr_gas"),
        debug_conn=bool(debug_conn),
        override_engine=override_engine,
        override_report=override_report,
    )

    # === 创建网络路由器 ===
    routers = build_mesh_routers(
        node_limit=int(node_limit),
        mesh_size=int(mesh_size),
        network_bandwidth=str(mesh["network_bandwidth"]),
        noc_type=str(mesh.get("noc_type", "merlin_mesh") or "merlin_mesh"),
        flit_size="32B",
        input_latency="10ns",
        output_latency="10ns",
        input_buf_size=str(mesh.get("router_buffer_size", "4KiB") or "4KiB"),
        output_buf_size=str(mesh.get("router_buffer_size", "4KiB") or "4KiB"),
        # Merlin hr_router 默认 num_vns=2；强制设为 1 会在高并发 spike 流量下触发 credit/backpressure 不收敛。
        num_vns=int(mesh.get("network_num_vns", 2) or 2),
        xbar_arb="merlin.xbar_arb_lru",
        debug=0,
        verbose=0,
        network_inspectors="",
        override_engine=override_engine,
        override_report=override_report,
    )

    # === 创建PE节点 + NIC ===
    mesh_params = dict(mesh)
    mesh_params["enable_bcsr"] = bool(enable_bcsr)
    nodes, nics = build_mesh_pes_and_nics(
        node_limit=int(node_limit),
        run_output_dir=str(run_output_dir),
        weights_dir=str(weights_dir),
        pe_memory_buses=pe_memory_buses,
        layers=dict(layers),
        mesh=mesh_params,
        flags=dict(flags),
        mem_layout=dict(mem_layout),
        gas=dict(gas),
        step=dict(step),
        routing=dict(routing),
        debug=dict(debug),
        global_step_ctrl=global_step_ctrl,
        override_engine=override_engine,
        override_report=override_report,
    )

    # === Cross-rank bridge: WeightLoader -> MultiCorePE loader_done event ===
    # SharedArray(loader_done_key) is not coherent across MPI ranks at runtime, so we connect an explicit
    # control-plane link to latch readiness on the PE side and mirror it into the local SharedArray instance.
    for pe_id in range(min(int(node_limit), len(nodes), len(pe_weight_loaders))):
        wl = pe_weight_loaders[pe_id]
        pe = nodes[pe_id]
        ld = sst.Link(f"pe_{pe_id}_weight_loader_done")
        ld.connect(
            # NOTE: Cross-thread control-plane link (multi-thread SST).
            # Keep a safe lookahead to avoid silent delivery failures under thread sync.
            (wl, "loader_done", "5ns"),
            (pe, "loader_done", "5ns"),
        )

    # === SpikeSource（可选）===
    input_layer = list(layers.get("input_layer", []) or [])
    spike_sources = build_spike_sources(
        enabled=bool(spike_source_enabled),
        input_layer=[int(x) for x in input_layer],
        nodes=nodes,
        spike_data_files=list(spike_data_files),
        neurons_per_core=int(mesh["neurons_per_core"]),
        num_cores_per_pe=int(mesh["num_cores_per_pe"]),
        neurons_per_pe=int(mesh["neurons_per_pe"]),
    )

    # === 建立连接 ===
    router_connection_count = connect_mesh_router_links(
        routers=routers,
        mesh_size=int(mesh_size),
        noc_type=str(mesh.get("noc_type", "merlin_mesh") or "merlin_mesh"),
        link_latency="5ns",
    )

    spike_connection_count = 0
    if spike_sources:
        spike_connection_count = connect_spike_sources_to_pes(
            spike_sources=spike_sources,
            nodes=nodes,
            link_latency="5ns",
        )

    enable_mesh_statistics(nodes=nodes, routers=routers)

    nic_connection_count = connect_nics_to_routers(
        nics=nics,
        routers=routers,
        disable_network=bool(flags.get("disable_network", False)),
        link_latency="5ns",
        noc_type=str(mesh.get("noc_type", "merlin_mesh") or "merlin_mesh"),
    )

    if override_engine is not None:
        override_engine.finalize()

    return {
        "pe_memory_controllers": pe_memory_controllers,
        "pe_memory_buses": pe_memory_buses,
        "pe_weight_loaders": pe_weight_loaders,
        "routers": routers,
        "nodes": nodes,
        "nics": nics,
        "spike_sources": spike_sources,
        "enable_bcsr": bool(enable_bcsr),
        "router_connection_count": int(router_connection_count),
        "nic_connection_count": int(nic_connection_count),
        "spike_connection_count": int(spike_connection_count),
        "override_report": list(override_report or []),
    }
