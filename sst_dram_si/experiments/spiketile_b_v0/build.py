from __future__ import annotations

import inspect
import os
import json
from typing import Any, Dict, List, Optional, Tuple

import sst

try:
    import snndl_system
except Exception:
    snndl_system = None

from .bcsr import load_core_bcsr_meta
from .overrides import OverrideEngine
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
) -> None:
    if override_engine is None:
        obj.addParams(params)
        return

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
    noc = str(noc_type or "merlin_mesh").strip().lower()
    if noc in ("merlin_mesh", "mesh", "merlin.mesh"):
        topo_type = "merlin.mesh"
    elif noc in ("merlin_torus", "torus", "merlin.torus"):
        topo_type = "merlin.torus"
    else:
        raise RuntimeError(f"invalid noc_type={noc!r} (expected merlin_mesh/merlin_torus)")
    if snndl_system is None or not hasattr(snndl_system, "noc_merlin"):
        raise RuntimeError("snndl_system.noc_merlin not available (check import path)")

    builder = snndl_system.noc_merlin
    build_fn = getattr(builder, "build_routers", None)
    if not callable(build_fn):
        raise RuntimeError("snndl_system.noc_merlin.build_routers not callable")

    router_params = {
        "num_ports": 5,  # 4个方向端口 + 1个本地端口
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
        "noc_type": str(noc_type),
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
        raise RuntimeError("snndl_system.noc_merlin.build_routers returned no routers")

    if override_engine is not None and not supports_override:
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
    global_bcsr_offsets: Dict[str, Any],
    debug_conn: bool,
    override_engine: Optional[OverrideEngine] = None,
    override_report: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Any], List[Any], List[Any], bool]:
    pe_memory_controllers: List[Any] = []
    pe_memory_buses: List[Any] = []
    pe_weight_loaders: List[Any] = []

    enable_bcsr = bool(global_bcsr_available)

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
            "num_cores": num_cores_per_pe,
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
        if pe_id == 0 and loader_verify_readback and (
            bool(global_bcsr_available) or (str(loader_write_pattern_mode).strip().lower() == "dense_rowcol_v1")
        ):
            weight_loader_params.update({
                "verify_readback_enable": 1,
                "verify_readback_core": 0,
                "verify_readback_bytes": int(loader_verify_bytes),
                "verify_colidx_start_index": int(loader_verify_colidx_start),
            })

        if pe_id == 0 and loader_diag_timed_read and global_bcsr_available:
            idx_bytes = int(global_bcsr_offsets.get("idx_bytes", 2) or 2)
            colidx_off = int(global_bcsr_offsets.get("colidx_offset", 0) or 0)
            start = int(loader_diag_timed_read_colidx_start)
            weight_loader_params.update({
                "diag_runtime_read_enable": 1,
                "diag_runtime_read_core": 0,
                "diag_runtime_read_offset": int(colidx_off + start * idx_bytes),
                "diag_runtime_read_bytes": 64,
            })

        if global_bcsr_available:
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
    global_bcsr_offsets: Dict[str, Any],
    debug_conn: bool,
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

    ports_per_pe = int(num_cores_per_pe) + 1

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

        if pe_id == 0 and loader_verify_readback and (
            bool(global_bcsr_available) or (str(loader_write_pattern_mode).strip().lower() == "dense_rowcol_v1")
        ):
            weight_loader_params.update({
                "verify_readback_enable": 1,
                "verify_readback_core": 0,
                "verify_readback_bytes": int(loader_verify_bytes),
                "verify_colidx_start_index": int(loader_verify_colidx_start),
            })

        if pe_id == 0 and loader_diag_timed_read and global_bcsr_available:
            idx_bytes = int(global_bcsr_offsets.get("idx_bytes", 2) or 2)
            colidx_off = int(global_bcsr_offsets.get("colidx_offset", 0) or 0)
            start = int(loader_diag_timed_read_colidx_start)
            weight_loader_params.update({
                "diag_runtime_read_enable": 1,
                "diag_runtime_read_core": 0,
                "diag_runtime_read_offset": int(colidx_off + start * idx_bytes),
                "diag_runtime_read_bytes": 64,
            })

        if global_bcsr_available:
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
    effective_cfg["memory_system"] = str(mem_layout.get("memory_system", "memhierarchy_per_pe") or "memhierarchy_per_pe")
    effective_cfg["noc_type"] = str(mesh.get("noc_type", "merlin_mesh") or "merlin_mesh")
    effective_cfg["router_buffer_size"] = str(mesh.get("router_buffer_size", "4KiB") or "4KiB")
    effective_cfg["nic_buffer_size"] = str(mesh.get("buffer_size", "8KiB") or "8KiB")

    memory_system = str(mem_layout.get("memory_system", "memhierarchy_per_pe") or "memhierarchy_per_pe").strip().lower()
    shared_memory = memory_system in ("memhierarchy_shared", "shared", "shared_bus", "shared-bus")
    shared_bus = pe_memory_buses[0] if shared_memory else None
    ports_per_pe = int(num_cores_per_pe) + 1

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

    # BCSR optimization level (format stays BCSR; this only gates caching/prefetch/coalesce).
    # Expected values: none/index_only/full. Leave empty to fallback to exec_mode defaults.
    bcsr_opt_level = str(mesh.get("bcsr_opt_level", "") or "").strip().lower()
    if bcsr_opt_level not in ("", "none", "index_only", "full"):
        bcsr_opt_level = ""
    if not bcsr_opt_level:
        bcsr_opt_level = "index_only" if exec_mode == "naive_raw" else "full"

    record_edge_apply_enable = 1 if bool(flags.get("record_edge_apply_enable", 1)) else 0
    record_edge_idle_enable = 1 if bool(flags.get("record_edge_idle_enable", 1)) else 0
    record_edge_scatter_enable = 1 if bool(flags.get("record_edge_scatter_enable", 1)) else 0

    use_soa_state = 1 if bool(flags.get("use_soa_state", 0)) else 0
    use_aosoa_state = 1 if bool(flags.get("use_aosoa_state", 0)) else 0
    aosoa_block_rows = int(flags.get("aosoa_block_rows", 16))
    verify_cluster_enable = 1 if bool(flags.get("verify_cluster_enable", 0)) else 0

    network_bandwidth = str(mesh["network_bandwidth"])
    buffer_size = str(mesh["buffer_size"])

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
    gas_apply_issue_policy = str(gas.get("apply_issue_policy", "order") or "order").strip().lower()
    if gas_apply_issue_policy not in ("order", "bank_rr_row_sticky_age", "dram_aware_v1"):
        gas_apply_issue_policy = "order"
    gas_apply_frags_per_issue = int(gas.get("apply_frags_per_issue", 1))
    if gas_apply_frags_per_issue < 0:
        gas_apply_frags_per_issue = 1
    gas_apply_bank_credit = int(gas.get("apply_bank_credit", 1))
    if gas_apply_bank_credit < 0:
        gas_apply_bank_credit = 1
    gas_apply_age_fair_ns = int(gas.get("apply_age_fair_ns", 2000))
    if gas_apply_age_fair_ns < 0:
        gas_apply_age_fair_ns = 0
    # DRAM-aware Apply knobs (exploration; default OFF)
    gas_dram_row_bytes = int(gas.get("dram_row_bytes", 0) or 0)
    gas_dram_bank_count = int(gas.get("dram_bank_count", 0) or 0)
    gas_dram_read_burst_bytes = int(gas.get("dram_read_burst_bytes", 64) or 64)
    gas_dram_row_miss_penalty_cycles = int(gas.get("dram_row_miss_penalty_cycles", 0) or 0)
    gas_dram_overfetch_budget_bytes = int(gas.get("dram_overfetch_budget_bytes", 0) or 0)
    gas_dram_aware_enable_row_window = 1 if bool(gas.get("dram_aware_enable_row_window", 0)) else 0
    gas_dram_aware_k_policy = str(gas.get("dram_aware_k_policy", "cost_budgeted") or "cost_budgeted").strip().lower()
    if gas_dram_aware_k_policy not in ("fixed", "cost_budgeted", "density_budgeted"):
        gas_dram_aware_k_policy = "cost_budgeted"
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
        "apply_frags_per_issue": int(gas_apply_frags_per_issue),
        "apply_bank_credit": int(gas_apply_bank_credit),
        "apply_age_fair_ns": int(gas_apply_age_fair_ns),
        "dram_row_bytes": int(gas_dram_row_bytes),
        "dram_bank_count": int(gas_dram_bank_count),
        "dram_read_burst_bytes": int(gas_dram_read_burst_bytes),
        "dram_row_miss_penalty_cycles": int(gas_dram_row_miss_penalty_cycles),
        "dram_overfetch_budget_bytes": int(gas_dram_overfetch_budget_bytes),
        "dram_aware_enable_row_window": int(gas_dram_aware_enable_row_window),
        "dram_aware_k_policy": str(gas_dram_aware_k_policy),
    }
    effective_cfg["naive_raw"] = {
        "max_inflight_reads": int(naive_max_inflight_reads),
        "memory_impl": "SnnDL.CachelineFragmentMemIF" if exec_mode == "naive_raw" else "memHierarchy.standardInterface",
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

        if workload_impl:
            node_params["workload_impl"] = workload_impl
        if workload_stats_modules:
            node_params["workload_stats_modules"] = workload_stats_modules

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
            nic = node.setSubComponent("network_interface", "SnnDL.SnnNIC")
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
                component_type="SnnDL.SnnNIC",
                name=f"multicore_pe_{i}.network_interface",
                tags={"pe": int(i), "layer": str(layer_name)},
                params=nic_params,
                override_engine=override_engine,
                override_report=override_report,
            )
            try:
                nic.enableAllStatistics({"type": "sst.AccumulatorStatistic"})
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
                    "diag_fire_log": 1 if diag_fire_log else 0,
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
                    "multicast_enable": 1 if bool(mesh.get("multicast_enable", False)) else 0,
                    "multicast_block_w": int(mesh.get("multicast_block_w", 2) or 2),
                    "multicast_block_h": int(mesh.get("multicast_block_h", 2) or 2),
                    "multicast_ingress_policy": str(mesh.get("multicast_ingress_policy", "top_left") or "top_left"),
                    "multicast_inter_policy": str(mesh.get("multicast_inter_policy", "xy") or "xy"),
                    "multicast_intra_policy": str(mesh.get("multicast_intra_policy", "manhattan_x_first") or "manhattan_x_first"),
                    "experimental_spiketile_enable": 1 if bool(mesh.get("experimental_spiketile_enable", False)) else 0,
                    "experimental_spikekey_fastpath_enable": 1 if bool(mesh.get("experimental_spikekey_fastpath_enable", False)) else 0,
                    "experimental_spiketile_max_pre_bits": int(mesh.get("experimental_spiketile_max_pre_bits", 64) or 64),
                    "experimental_spiketile_block_cols": int(mesh.get("experimental_spiketile_block_cols", 0) or 0),
                    "experimental_compact_mask_enable": 1 if bool(mesh.get("experimental_compact_mask_enable", False)) else 0,
                    "experimental_inter_bundle_enable": 1 if bool(mesh.get("experimental_inter_bundle_enable", False)) else 0,
                    "experimental_inter_bundle_max_entries": int(mesh.get("experimental_inter_bundle_max_entries", 64) or 64),
                    "diag_fire_log": 1 if diag_fire_log else 0,
                }

            core_params["multicast_enable"] = 1 if bool(mesh.get("multicast_enable", False)) else 0
            core_params["multicast_block_w"] = int(mesh.get("multicast_block_w", 2) or 2)
            core_params["multicast_block_h"] = int(mesh.get("multicast_block_h", 2) or 2)
            core_params["multicast_ingress_policy"] = str(mesh.get("multicast_ingress_policy", "top_left") or "top_left")
            core_params["multicast_inter_policy"] = str(mesh.get("multicast_inter_policy", "xy") or "xy")
            core_params["multicast_intra_policy"] = str(mesh.get("multicast_intra_policy", "manhattan_x_first") or "manhattan_x_first")
            core_params["experimental_spiketile_enable"] = 1 if bool(mesh.get("experimental_spiketile_enable", False)) else 0
            core_params["experimental_spikekey_fastpath_enable"] = 1 if bool(mesh.get("experimental_spikekey_fastpath_enable", False)) else 0
            core_params["experimental_spiketile_max_pre_bits"] = int(mesh.get("experimental_spiketile_max_pre_bits", 64) or 64)
            core_params["experimental_spiketile_block_cols"] = int(mesh.get("experimental_spiketile_block_cols", 0) or 0)
            core_params["experimental_compact_mask_enable"] = 1 if bool(mesh.get("experimental_compact_mask_enable", False)) else 0
            core_params["experimental_inter_bundle_enable"] = 1 if bool(mesh.get("experimental_inter_bundle_enable", False)) else 0
            core_params["experimental_inter_bundle_max_entries"] = int(mesh.get("experimental_inter_bundle_max_entries", 64) or 64)

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

            _add_params_with_overrides(
                core_subcomponent,
                role="pe.core",
                component_type="SnnDL.SnnPESubComponent",
                name=f"multicore_pe_{i}.core{core_idx}",
                tags={"pe": int(i), "core": int(core_idx), "layer": str(layer_name)},
                params=core_params,
                override_engine=override_engine,
                override_report=override_report,
            )

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
                    int(gas_gap_k_bytes) > 0 or int(gas_row_window_bytes) > 0 or int(gas_row_window_timeout_ns) > 0
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
                            "k_adapt_enable_effective": int(effective_k_adapt_enable),
                            "defer_issue_until_apply_effective": int(effective_defer_issue_until_apply),
                            "force_defer_effective": int(force_defer),
                            "sort_policy": str(gas_sort_policy),
                            "row_bytes_guess": int(gas_row_bytes_guess),
                            "bank_bits": int(gas_bank_bits),
                            "bank_shift": int(gas_bank_shift),
                            "bank_auto_enable": int(gas_bank_auto_enable),
                            "apply_issue_policy": str(gas_apply_issue_policy),
                            "apply_frags_per_issue": int(gas_apply_frags_per_issue),
                            "apply_bank_credit": int(gas_apply_bank_credit),
                            "apply_age_fair_ns": int(gas_apply_age_fair_ns),
                            "sram_bytes": 256 * 1024,
                        },
                    }
                )

                core_memory_params: Dict[str, Any] = {
                    "verbose": (2 if (window_read_debug_enabled and (window_read_debug_all or (i == debug_target_pe and core_idx == debug_target_core))) else 0),
                    "merge_policy": effective_merge_policy,
                    "sort_policy": str(gas_sort_policy),
                    "defer_issue_until_apply": int(effective_defer_issue_until_apply),
                    "gap_merge_enable": effective_gap_merge_enable,
                    "gap_merge_k_bytes": effective_gap_merge_k_bytes,
                    "burst_bytes_max": effective_lmax_bytes,
                    "k_adapt_enable": effective_k_adapt_enable,
                    "row_bytes_guess": int(gas_row_bytes_guess),
                    "bank_bits": int(gas_bank_bits),
                    "bank_shift": int(gas_bank_shift),
                    "bank_auto_enable": int(gas_bank_auto_enable),
                    "apply_issue_policy": str(gas_apply_issue_policy),
                    "apply_frags_per_issue": int(gas_apply_frags_per_issue),
                    "apply_bank_credit": int(gas_apply_bank_credit),
                    "apply_age_fair_ns": int(gas_apply_age_fair_ns),
                    "dram_row_bytes": int(gas_dram_row_bytes),
                    "dram_bank_count": int(gas_dram_bank_count),
                    "dram_read_burst_bytes": int(gas_dram_read_burst_bytes),
                    "dram_row_miss_penalty_cycles": int(gas_dram_row_miss_penalty_cycles),
                    "dram_overfetch_budget_bytes": int(gas_dram_overfetch_budget_bytes),
                    "dram_aware_enable_row_window": int(gas_dram_aware_enable_row_window),
                    "dram_aware_k_policy": str(gas_dram_aware_k_policy),
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
                    # We disable the heavy per-core exports instead (export_window_metrics_csv="").
                    "emit_stage_events": 1,
                    "emit_stage_events_lenient": 0,
                    "export_granules_csv": "",
                    "export_window_metrics_csv": "",
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
                    bcsr_merge_verify_enable
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
    if snndl_system is None or not hasattr(snndl_system, "noc_merlin"):
        raise RuntimeError("snndl_system.noc_merlin not available (check import path)")
    builder = snndl_system.noc_merlin
    connect_fn = getattr(builder, "connect_mesh_router_links", None)
    if not callable(connect_fn):
        raise RuntimeError("snndl_system.noc_merlin.connect_mesh_router_links not callable")

    result = _call_with_supported_kwargs(
        connect_fn,
        routers=routers,
        mesh_size=int(mesh_size),
        noc_type=str(noc_type),
        link_latency=str(link_latency),
    )
    count = _extract_connection_count(result)
    if count is None:
        count = _estimate_router_connection_count(routers=routers, mesh_size=int(mesh_size), noc_type=str(noc_type))
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
) -> int:
    if disable_network:
        return 0
    if snndl_system is None or not hasattr(snndl_system, "noc_merlin"):
        raise RuntimeError("snndl_system.noc_merlin not available (check import path)")
    builder = snndl_system.noc_merlin
    connect_fn = getattr(builder, "connect_nics_to_routers", None)
    if not callable(connect_fn):
        raise RuntimeError("snndl_system.noc_merlin.connect_nics_to_routers not callable")

    result = _call_with_supported_kwargs(
        connect_fn,
        nics=nics,
        routers=routers,
        link_latency=str(link_latency),
    )
    count = _extract_connection_count(result)
    if count is None:
        count = _estimate_nic_connection_count(nics=nics, routers=routers)
    return int(count)


def enable_mesh_statistics(*, nodes: List[Any], routers: List[Any]) -> None:
    for node in nodes:
        # 以组件端注册表为唯一 source-of-truth：启用该组件已注册的全部统计项（随 workload-stats 模块动态变化）。
        node.enableAllStatistics({"type": "sst.AccumulatorStatistic"})

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
        global_bcsr_offsets=dict(mesh.get("global_bcsr_offsets", {}) or {}),
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
