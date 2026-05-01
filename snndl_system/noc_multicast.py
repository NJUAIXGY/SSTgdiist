from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def _resolve_sst_module(sst_module: Optional[Any]) -> Any:
    if sst_module is not None:
        return sst_module
    import sst  # type: ignore

    return sst


def _append_override_report(
    *,
    override_report: Optional[List[Dict[str, Any]]],
    role: str,
    component_type: str,
    name: str,
    tags: Dict[str, Any],
    base_params: Dict[str, Any],
    final_params: Dict[str, Any],
    hits: Sequence[Dict[str, Any]],
) -> None:
    if override_report is None or not hits:
        return
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


def _apply_overrides(
    *,
    role: str,
    component_type: str,
    name: str,
    tags: Dict[str, Any],
    params: Dict[str, Any],
    override_engine: Optional[Any],
    override_report: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    if override_engine is None:
        return dict(params)
    apply_fn = getattr(override_engine, "apply", None)
    if not callable(apply_fn):
        return dict(params)
    final_params, hits = apply_fn(
        role=str(role),
        component_type=str(component_type),
        name=str(name),
        tags=dict(tags or {}),
        base_params=dict(params),
    )
    _append_override_report(
        override_report=override_report,
        role=role,
        component_type=component_type,
        name=name,
        tags=tags,
        base_params=params,
        final_params=final_params,
        hits=hits or [],
    )
    return dict(final_params)


def _normalize_noc_type(noc_type: str) -> str:
    noc = str(noc_type or "multicast_mesh").strip().lower()
    if noc in ("multicast_mesh", "multicast", "storm", "storm_multicast"):
        return "multicast_mesh"
    raise RuntimeError(f"invalid noc_type={noc!r} (expected multicast_mesh)")


def build_routers(
    *,
    node_limit: int,
    mesh_size: int,
    network_bandwidth: str,
    noc_type: str = "multicast_mesh",
    topo_type: Optional[str] = None,
    router_params: Optional[Dict[str, Any]] = None,
    topology_params: Optional[Dict[str, Any]] = None,
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
    override_engine: Optional[Any] = None,
    override_report: Optional[List[Dict[str, Any]]] = None,
    sst_module: Optional[Any] = None,
) -> List[Any]:
    del topo_type, topology_params, flit_size, input_latency, output_latency, input_buf_size
    del output_buf_size, num_vns, xbar_arb, debug, network_inspectors, network_bandwidth
    _normalize_noc_type(noc_type)

    sst = _resolve_sst_module(sst_module)
    base_params = dict(router_params or {})
    mesh_shape = str(base_params.pop("mesh_shape", f"{int(mesh_size)}x{int(mesh_size)}"))

    routers: List[Any] = []
    for node_id in range(int(node_limit)):
        router = sst.Component(f"router_{node_id}", "SnnDL.MulticastRouter")
        params = {
            "node_id": int(node_id),
            "mesh_shape": mesh_shape,
            "router_latency_cycles": int(base_params.get("router_latency_cycles", 0) or 0),
            "serialize_output_enable": int(base_params.get("serialize_output_enable", 0) or 0),
            "serialize_service_cycles": int(base_params.get("serialize_service_cycles", 1) or 1),
            "serialize_output_byte_enable": int(base_params.get("serialize_output_byte_enable", 0) or 0),
            "serialize_bytes_per_cycle": int(base_params.get("serialize_bytes_per_cycle", 16) or 16),
            "serialize_header_bytes": int(base_params.get("serialize_header_bytes", 24) or 24),
            "local_endpoint_multicast_enable": int(base_params.get("local_endpoint_multicast_enable", 0) or 0),
            "multicast_inter_policy": str(base_params.get("multicast_inter_policy", "xy") or "xy"),
            "multicast_intra_policy": str(base_params.get("multicast_intra_policy", "manhattan_x_first") or "manhattan_x_first"),
            "adaptive_telemetry_enable": int(base_params.get("adaptive_telemetry_enable", 0) or 0),
            "adaptive_inter_w_wait": int(base_params.get("adaptive_inter_w_wait", 1) or 1),
            "adaptive_inter_w_service": int(base_params.get("adaptive_inter_w_service", 1) or 1),
            "adaptive_inter_w_len": int(base_params.get("adaptive_inter_w_len", 0) or 0),
            "adaptive_intra_w_bytes": int(base_params.get("adaptive_intra_w_bytes", 1) or 1),
            "adaptive_intra_w_queue": int(base_params.get("adaptive_intra_w_queue", 1) or 1),
            "verbose": int(base_params.get("verbose", verbose) or 0),
        }
        final_params = _apply_overrides(
            role="router",
            component_type="SnnDL.MulticastRouter",
            name=f"router_{node_id}",
            tags={"node": int(node_id)},
            params=params,
            override_engine=override_engine,
            override_report=override_report,
        )
        router.addParams(final_params)
        routers.append(router)
    return routers


def build_mesh_routers(**kwargs: Any) -> List[Any]:
    return build_routers(**kwargs)


def connect_mesh_router_links(
    *,
    routers: List[Any],
    mesh_size: int,
    noc_type: str = "multicast_mesh",
    shape: str = "",
    link_latency: str = "5ns",
    sst_module: Optional[Any] = None,
) -> int:
    _normalize_noc_type(noc_type)
    sst = _resolve_sst_module(sst_module)
    connection_count = 0

    dim_x = int(mesh_size)
    dim_y = int(mesh_size)
    if shape:
        sx, sy = str(shape).lower().split("x", 1)
        dim_x = int(sx)
        dim_y = int(sy)

    for y in range(dim_y):
        for x in range(dim_x):
            node_id = y * dim_x + x
            if x + 1 < dim_x:
                east_id = y * dim_x + (x + 1)
                link = sst.Link(f"router_east_{node_id}_to_{east_id}")
                link.connect(
                    (routers[node_id], "east", link_latency),
                    (routers[east_id], "west", link_latency),
                )
                connection_count += 1
            if y + 1 < dim_y:
                south_id = (y + 1) * dim_x + x
                link = sst.Link(f"router_south_{node_id}_to_{south_id}")
                link.connect(
                    (routers[node_id], "south", link_latency),
                    (routers[south_id], "north", link_latency),
                )
                connection_count += 1

    return connection_count


def connect_nics_to_routers(
    *,
    nics: List[Any],
    routers: List[Any],
    link_latency: str = "5ns",
    sst_module: Optional[Any] = None,
    disable_network: bool = False,
    noc_type: str = "multicast_mesh",
) -> int:
    if disable_network:
        return 0
    _normalize_noc_type(noc_type)
    sst = _resolve_sst_module(sst_module)
    connection_count = 0
    for idx in range(min(len(nics), len(routers))):
        link = sst.Link(f"nic_{idx}_to_router_{idx}")
        link.connect(
            (nics[idx], "network", link_latency),
            (routers[idx], "local", link_latency),
        )
        connection_count += 1
    return connection_count
