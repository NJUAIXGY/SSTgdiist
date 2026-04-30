from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import sst

from snndl_system import mem_memhierarchy
from snndl_system import noc_merlin
from snndl_spec.overrides import OverrideEngine

from .utils import tensor_print


def _record_override_report(
    override_report: List[Dict[str, Any]],
    *,
    role: str,
    component_type: str,
    name: str,
    tags: Dict[str, Any],
    base_params: Dict[str, Any],
    final_params: Dict[str, Any],
    hits: List[Dict[str, Any]],
) -> None:
    changed = {k: v for k, v in final_params.items() if base_params.get(k) != v}
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


def _apply_override_params(
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
        return dict(params)
    final_params, hits = override_engine.apply(
        role=str(role),
        component_type=str(component_type),
        name=str(name),
        tags=dict(tags or {}),
        base_params=dict(params),
    )
    if override_report is not None and hits:
        _record_override_report(
            override_report,
            role=role,
            component_type=component_type,
            name=name,
            tags=tags,
            base_params=params,
            final_params=final_params,
            hits=list(hits or []),
        )
    return dict(final_params)


def build_mesh_routers(
    *,
    node_limit: int,
    mesh_size: int,
    network_bandwidth: str,
    flit_size: str = "32B",
    input_latency: str = "10ns",
    output_latency: str = "10ns",
    input_buf_size: str = "4KiB",
    output_buf_size: str = "4KiB",
    num_vns: int = 2,
    xbar_arb: str = "merlin.xbar_arb_lru",
    debug: int = 0,
    verbose: int = 0,
    network_inspectors: str = "",
) -> List[Any]:
    return noc_merlin.build_mesh_routers(
        node_limit=node_limit,
        mesh_size=mesh_size,
        network_bandwidth=network_bandwidth,
        flit_size=flit_size,
        input_latency=input_latency,
        output_latency=output_latency,
        input_buf_size=input_buf_size,
        output_buf_size=output_buf_size,
        num_vns=num_vns,
        xbar_arb=xbar_arb,
        debug=debug,
        verbose=verbose,
        network_inspectors=network_inspectors,
    )


def connect_mesh_router_links(
    *,
    routers: List[Any],
    mesh_size: int,
    noc_type: str = "merlin_mesh",
    shape: str = "",
    link_latency: str = "5ns",
) -> int:
    return int(
        noc_merlin.connect_mesh_router_links(
            routers=routers,
            mesh_size=mesh_size,
            noc_type=noc_type,
            shape=str(shape or ""),
            link_latency=link_latency,
        )
    )


def connect_nics_to_routers(
    *,
    nics: List[Any],
    routers: List[Any],
    link_latency: str = "5ns",
) -> int:
    return int(
        noc_merlin.connect_nics_to_routers(
            nics=nics,
            routers=routers,
            link_latency=link_latency,
        )
    )


def build_pe_memory_systems(
    *,
    node_limit: int,
    pe_mem_region_bytes: int,
    mem_access_time: str,
    num_mem_channels: int = 1,
    interleave_size_bytes: int = 0,
    drain_bus: bool = False,
    backend: str = "simple",
    backend_params: Optional[Dict[str, Any]] = None,
    override_engine: Optional[OverrideEngine] = None,
    override_report: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Any], List[Any]]:
    result = mem_memhierarchy.build_pe_memory_systems(
        node_limit=node_limit,
        pe_mem_region_bytes=pe_mem_region_bytes,
        mem_access_time=mem_access_time,
        num_mem_channels=num_mem_channels,
        interleave_size_bytes=interleave_size_bytes,
        drain_bus=drain_bus,
        backend=backend,
        backend_params=backend_params,
        override_engine=override_engine,
        override_report=override_report,
    )
    if isinstance(result, tuple) and len(result) >= 2:
        return result[0], result[1]
    raise RuntimeError("mem_memhierarchy.build_pe_memory_systems returned invalid result")


def build_tensor_mesh_4x4(
    *,
    run_output_dir: str,
    node_limit: int,
    mesh_size: int,
    mesh_cfg: Dict[str, Any],
    tensor_cfg: Dict[str, Any],
    overrides: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    override_engine = OverrideEngine(list(overrides or [])) if overrides else None
    override_report: Optional[List[Dict[str, Any]]] = [] if override_engine is not None else None

    pe_memory_controllers, pe_memory_buses = build_pe_memory_systems(
        node_limit=int(node_limit),
        pe_mem_region_bytes=int(mesh_cfg["pe_mem_region_bytes"]),
        mem_access_time=str(mesh_cfg.get("mem_access_time", "100ns")),
        num_mem_channels=int(tensor_cfg.get("tensor_dma_hbm_channels", 1) or 1),
        interleave_size_bytes=int(tensor_cfg.get("tensor_dma_hbm_channel_interleave_bytes", 0) or 0),
        drain_bus=int(tensor_cfg.get("tensor_dma_hbm_channels", 1) or 1) > 1,
        backend=str(mesh_cfg.get("mem_backend", "simple") or "simple"),
        backend_params=dict(mesh_cfg.get("mem_backend_params") or {}),
        override_engine=override_engine,
        override_report=override_report,
    )

    routers = noc_merlin.build_routers(
        node_limit=int(node_limit),
        mesh_size=int(mesh_size),
        network_bandwidth=str(mesh_cfg["network_bandwidth"]),
        noc_type=str(mesh_cfg.get("noc_type", "merlin_mesh") or "merlin_mesh"),
        topology_params={
            "shape": str(mesh_cfg.get("noc_shape") or f"{int(mesh_size)}x{int(mesh_size)}"),
            "width": str(mesh_cfg.get("noc_width") or "1x1"),
            "local_ports": str(int(mesh_cfg.get("noc_local_ports") or 1)),
        },
        input_buf_size=str(mesh_cfg.get("buffer_size", "8KiB")),
        output_buf_size=str(mesh_cfg.get("buffer_size", "8KiB")),
        num_vns=int(mesh_cfg.get("network_num_vns", 2) or 2),
        override_engine=override_engine,
        override_report=override_report,
    )

    nodes: List[Any] = []
    nics: List[Any] = []
    num_cores_per_pe = int(mesh_cfg["num_cores_per_pe"])
    neurons_per_core = int(mesh_cfg["neurons_per_core"])
    neurons_per_pe = int(mesh_cfg["neurons_per_pe"])
    total_nodes = int(mesh_cfg["total_nodes"])
    core_mem_region_bytes = int(mesh_cfg["core_mem_region_bytes"])
    workload_stats_modules = str(mesh_cfg.get("workload_stats_modules", "") or "").strip()

    for pe_id in range(node_limit):
        node = sst.Component(f"pe_{pe_id}", "SnnDL.MultiCorePE")
        pe_base_addr = pe_id * int(mesh_cfg["pe_mem_region_bytes"])
        node_params_base = {
            "clock": "1GHz",
            "num_cores": num_cores_per_pe,
            "neurons_per_core": neurons_per_core,
            "neurons_per_pe": neurons_per_pe,
            "node_id": pe_id,
            "total_nodes": total_nodes,
            "global_neuron_base": pe_id * neurons_per_pe,
            "base_addr": pe_base_addr,
            "workload_impl": "tensor",
            **({"workload_stats_modules": workload_stats_modules} if workload_stats_modules else {}),
            "verbose": 0,
        }
        node_params = _apply_override_params(
            role="pe",
            component_type="SnnDL.MultiCorePE",
            name=f"pe_{pe_id}",
            tags={"pe": int(pe_id), "node": int(pe_id)},
            params=node_params_base,
            override_engine=override_engine,
            override_report=override_report,
        )
        node.addParams(node_params)

        nic = node.setSubComponent("network_interface", "SnnDL.SnnNIC")
        nic_params_base = {
            "node_id": str(pe_id),
            "link_bw": str(mesh_cfg["network_bandwidth"]),
            "input_buf_size": str(mesh_cfg.get("buffer_size", "8KiB")),
            "output_buf_size": str(mesh_cfg.get("buffer_size", "8KiB")),
            "use_direct_link": "false",
            "port_name": "network",
            "verbose": 0,
            "virtual_channels": int(mesh_cfg.get("network_num_vns", 2) or 2),
            "network_num_vns": int(mesh_cfg.get("network_num_vns", 2) or 2),
            "vn_spike_data": 0,
            "vn_batch_data": 1,
            "vn_control": 1,
            "total_nodes": total_nodes,
            "export_spike_csv": "",
        }
        nic_params = _apply_override_params(
            role="pe.nic",
            component_type="SnnDL.SnnNIC",
            name=f"pe_{pe_id}.network_interface",
            tags={"pe": int(pe_id), "node": int(pe_id)},
            params=nic_params_base,
            override_engine=override_engine,
            override_report=override_report,
        )
        nic.addParams(nic_params)

        for core_idx in range(num_cores_per_pe):
            core_sub = node.setSubComponent(f"core{core_idx}", "SnnDL.SnnPESubComponent")
            core_base_addr = pe_base_addr + core_idx * core_mem_region_bytes
            core_params_base = {
                "core_id": core_idx,
                "total_cores": num_cores_per_pe,
                "node_id": pe_id,
                "total_nodes": total_nodes,
                "global_neuron_base": pe_id * neurons_per_pe + core_idx * neurons_per_core,
                "num_neurons": neurons_per_core,
                "neurons_per_pe": neurons_per_pe,
                "base_addr": core_base_addr,
                "verbose": 0,
                **tensor_cfg,
            }
            core_params = _apply_override_params(
                role="pe.core",
                component_type="SnnDL.SnnPESubComponent",
                name=f"pe_{pe_id}.core{core_idx}",
                tags={"pe": int(pe_id), "node": int(pe_id), "core": int(core_idx)},
                params=core_params_base,
                override_engine=override_engine,
                override_report=override_report,
            )
            core_sub.addParams(core_params)

            core_mem = core_sub.setSubComponent("memory", "memHierarchy.standardInterface")
            core_mem_params = _apply_override_params(
                role="pe.core.memory_if",
                component_type="memHierarchy.standardInterface",
                name=f"pe_{pe_id}.core{core_idx}.memory",
                tags={"pe": int(pe_id), "node": int(pe_id), "core": int(core_idx)},
                params={},
                override_engine=override_engine,
                override_report=override_report,
            )
            if core_mem_params:
                core_mem.addParams(core_mem_params)
            core_mem_link = sst.Link(f"pe_{pe_id}_core{core_idx}_mem_to_pe_bus")
            core_mem_link.connect(
                (core_mem, "lowlink", "5ns"),
                (pe_memory_buses[pe_id], f"highlink{core_idx}", "5ns"),
            )

        nodes.append(node)
        nics.append(nic)

    router_connection_count = connect_mesh_router_links(
        routers=routers,
        mesh_size=int(mesh_size),
        noc_type=str(mesh_cfg.get("noc_type", "merlin_mesh") or "merlin_mesh"),
        shape=str(mesh_cfg.get("noc_shape") or ""),
        link_latency="5ns",
    )
    nic_connection_count = connect_nics_to_routers(nics=nics, routers=routers, link_latency="5ns")

    # Enable stats on nodes/routers (keep output minimal and stable for summary scripts).
    for node in nodes:
        # 以组件端注册表为唯一 source-of-truth：启用该组件已注册的全部统计项（随 workload-stats 模块动态变化）。
        node.enableAllStatistics({"type": "sst.AccumulatorStatistic"})
    for router in routers:
        router.enableStatistics(list(["router.packet_count", "router.network_load"]))

    if override_engine is not None:
        override_engine.finalize()

    # Persist effective parameters for later analysis/validation.
    # Best-effort: never fail model construction because of IO.
    try:
        os.makedirs(str(run_output_dir), exist_ok=True)
        effective_cfg: Dict[str, Any] = {
            "mesh_size": int(mesh_size),
            "node_limit": int(node_limit),
            "mesh_cfg": dict(mesh_cfg),
            "tensor_cfg": dict(tensor_cfg),
        }
        if override_engine is not None:
            effective_cfg["overrides"] = override_engine.rules()
        if override_report is not None:
            effective_cfg["overrides_report"] = list(override_report)
        out_path = os.path.join(str(run_output_dir), "effective_config.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(effective_cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    tensor_print(
        f"[tensor_mesh] built nodes={len(nodes)} routers={len(routers)} "
        f"router_links={router_connection_count} nic_links={nic_connection_count}"
    )

    return {
        "pe_memory_controllers": pe_memory_controllers,
        "pe_memory_buses": pe_memory_buses,
        "routers": routers,
        "nodes": nodes,
        "nics": nics,
        "router_connection_count": int(router_connection_count),
        "nic_connection_count": int(nic_connection_count),
        "run_output_dir": str(run_output_dir),
        "override_report": list(override_report or []),
    }
