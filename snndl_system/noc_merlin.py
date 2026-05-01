from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence


AddParamsFn = Callable[..., None]


def _resolve_sst_module(sst_module: Optional[Any]) -> Any:
    if sst_module is not None:
        return sst_module
    import sst  # type: ignore

    return sst


def _add_params(
    obj: Any,
    *,
    role: str,
    component_type: str,
    name: str,
    tags: Dict[str, Any],
    params: Dict[str, Any],
    add_params_fn: Optional[Callable[..., None]],
) -> None:
    if add_params_fn is None:
        obj.addParams(params)
        return
    add_params_fn(
        obj,
        role=role,
        component_type=component_type,
        name=name,
        tags=dict(tags),
        params=dict(params),
    )


def _resolve_topology_type(noc_type: str) -> str:
    noc = str(noc_type or "merlin_mesh").strip().lower()
    if noc in ("merlin_mesh", "mesh", "merlin.mesh"):
        return "merlin.mesh"
    if noc in ("merlin_torus", "torus", "merlin.torus"):
        return "merlin.torus"
    raise RuntimeError(f"invalid noc_type={noc!r} (expected merlin_mesh/merlin_torus)")


def build_merlin_routers(
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
    add_params_fn: Optional[Callable[..., None]] = None,
    sst_module: Optional[Any] = None,
) -> List[Any]:
    """
    Build Merlin NoC routers + topology subcomponents.

    add_params_fn signature:
      fn(obj, *, role, component_type, name, tags, params) -> None
    """
    sst = _resolve_sst_module(sst_module)
    topo_type = _resolve_topology_type(noc_type)
    routers: List[Any] = []
    for node_id in range(int(node_limit)):
        router = sst.Component(f"router_{node_id}", "merlin.hr_router")
        router_params = {
            "id": int(node_id),
            "num_ports": 5,
            "link_bw": network_bandwidth,
            "flit_size": flit_size,
            "xbar_bw": network_bandwidth,
            "input_latency": input_latency,
            "output_latency": output_latency,
            "input_buf_size": input_buf_size,
            "output_buf_size": output_buf_size,
            "num_vns": int(num_vns),
            "xbar_arb": xbar_arb,
            "debug": int(debug),
            "verbose": int(verbose),
            "network_inspectors": network_inspectors,
        }
        _add_params(
            router,
            role="router",
            component_type="merlin.hr_router",
            name=f"router_{node_id}",
            tags={"node": int(node_id)},
            params=router_params,
            add_params_fn=add_params_fn,
        )

        topo = router.setSubComponent("topology", topo_type)
        topo_params = {
            "shape": f"{mesh_size}x{mesh_size}",
            "width": "1x1",
            "local_ports": "1",
        }
        _add_params(
            topo,
            role="router.topology",
            component_type=topo_type,
            name=f"router_{node_id}.topology",
            tags={"node": int(node_id)},
            params=topo_params,
            add_params_fn=add_params_fn,
        )
        routers.append(router)
    return routers


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
    add_params_fn: Optional[Callable[..., None]] = None,
    sst_module: Optional[Any] = None,
) -> List[Any]:
    """
    Compatibility alias for existing templates (`build_mesh_routers`).
    """
    return build_merlin_routers(
        node_limit=node_limit,
        mesh_size=mesh_size,
        network_bandwidth=network_bandwidth,
        noc_type=noc_type,
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
        add_params_fn=add_params_fn,
        sst_module=sst_module,
    )


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


def build_routers(
    *,
    node_limit: int,
    mesh_size: int,
    network_bandwidth: str,
    noc_type: str = "merlin_mesh",
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
    """
    Builder entry used by mesh_template (supports override_engine/report).

    Note: For historical compatibility, topology override matching uses
    component_type="merlin.mesh" even when actual topo is torus.
    """
    sst = _resolve_sst_module(sst_module)
    topo_type_actual = str(topo_type).strip() if topo_type else _resolve_topology_type(noc_type)

    routers: List[Any] = []
    for node_id in range(int(node_limit)):
        router = sst.Component(f"router_{node_id}", "merlin.hr_router")
        base_router_params = dict(router_params or {})
        if not base_router_params:
            base_router_params = {
                "num_ports": 5,
                "link_bw": network_bandwidth,
                "flit_size": flit_size,
                "xbar_bw": network_bandwidth,
                "input_latency": input_latency,
                "output_latency": output_latency,
                "input_buf_size": input_buf_size,
                "output_buf_size": output_buf_size,
                "num_vns": int(num_vns),
                "xbar_arb": xbar_arb,
                "debug": int(debug),
                "verbose": int(verbose),
                "network_inspectors": network_inspectors,
            }
        base_router_params.setdefault("id", int(node_id))

        final_router_params = _apply_overrides(
            role="router",
            component_type="merlin.hr_router",
            name=f"router_{node_id}",
            tags={"node": int(node_id)},
            params=base_router_params,
            override_engine=override_engine,
            override_report=override_report,
        )
        router.addParams(final_router_params)

        topo = router.setSubComponent("topology", topo_type_actual)
        base_topo_params = dict(topology_params or {})
        if not base_topo_params:
            base_topo_params = {
                "shape": f"{mesh_size}x{mesh_size}",
                "width": "1x1",
                "local_ports": "1",
            }

        final_topo_params = _apply_overrides(
            role="router.topology",
            component_type="merlin.mesh",
            name=f"router_{node_id}.topology",
            tags={"node": int(node_id)},
            params=base_topo_params,
            override_engine=override_engine,
            override_report=override_report,
        )
        topo.addParams(final_topo_params)
        routers.append(router)

    return routers


def connect_mesh_router_links(
    *,
    routers: List[Any],
    mesh_size: int,
    noc_type: str = "merlin_mesh",
    shape: str = "",
    link_latency: str = "5ns",
    sst_module: Optional[Any] = None,
) -> int:
    sst = _resolve_sst_module(sst_module)
    connection_count = 0
    torus = str(noc_type or "merlin_mesh").strip().lower() in ("merlin_torus", "torus", "merlin.torus")

    dim_x = 0
    dim_y = 0
    s = str(shape or "").strip().lower()
    if s:
        parts = [p.strip() for p in s.split("x") if p.strip()]
        if len(parts) != 2:
            raise RuntimeError(f"invalid shape={shape!r} (expected '<X>x<Y>')")
        try:
            dim_x = int(parts[0])
            dim_y = int(parts[1])
        except Exception as exc:
            raise RuntimeError(f"invalid shape={shape!r} (expected '<X>x<Y>' with integers)") from exc
        if dim_x <= 0 or dim_y <= 0:
            raise RuntimeError(f"invalid shape={shape!r} (expected '<X>x<Y>' with X,Y > 0)")
    if dim_x <= 0 or dim_y <= 0:
        dim_x = int(mesh_size)
        dim_y = int(mesh_size)

    for y in range(int(dim_y)):
        for x in range(int(dim_x if torus else dim_x - 1)):
            node_id = y * dim_x + x
            east_node_id = y * dim_x + ((x + 1) % dim_x if torus else (x + 1))
            if node_id < len(routers) and east_node_id < len(routers):
                link = sst.Link(f"router_east_{node_id}_to_{east_node_id}")
                link.connect(
                    (routers[node_id], "port0", link_latency),
                    (routers[east_node_id], "port1", link_latency),
                )
                connection_count += 1

    for x in range(int(dim_x)):
        for y in range(int(dim_y if torus else dim_y - 1)):
            node_id = y * dim_x + x
            south_node_id = (((y + 1) % dim_y) if torus else (y + 1)) * dim_x + x
            if node_id < len(routers) and south_node_id < len(routers):
                link = sst.Link(f"router_south_{node_id}_to_{south_node_id}")
                link.connect(
                    (routers[node_id], "port2", link_latency),
                    (routers[south_node_id], "port3", link_latency),
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
) -> int:
    if disable_network:
        return 0
    sst = _resolve_sst_module(sst_module)
    connection_count = 0
    for idx in range(min(len(nics), len(routers))):
        link = sst.Link(f"nic_{idx}_to_router_{idx}")
        link.connect(
            (nics[idx], "network", link_latency),
            (routers[idx], "port4", link_latency),
        )
        connection_count += 1
    return connection_count
