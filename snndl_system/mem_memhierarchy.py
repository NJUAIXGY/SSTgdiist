"""memHierarchy memory builder (MemController + backend + Bus).

This module provides small, reusable building blocks for constructing a
memHierarchy-backed memory system. It intentionally does **not** include
cache, NIC, or SnnDL WeightLoader logic.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def _resolve_sst_module(sst_module: Optional[Any]) -> Any:
    if sst_module is not None:
        return sst_module
    import sst  # type: ignore

    return sst


def normalize_mem_backend(backend: str) -> str:
    """Normalize backend name to `simple` or `ramulator2`."""
    if backend is None:
        raise ValueError("backend must be provided")
    key = str(backend).strip().lower()
    if key in {"simple", "simplemem", "simple_mem", "memhierarchy.simplemem"}:
        return "simple"
    if key in {"ramulator2", "ram2", "memhierarchy.ramulator2"}:
        return "ramulator2"
    raise ValueError(f"unsupported memHierarchy backend: {backend}")


def mem_backend_component(backend: str) -> str:
    """Return memHierarchy backend component name."""
    normalized = normalize_mem_backend(backend)
    if normalized == "simple":
        return "memHierarchy.simpleMem"
    return "memHierarchy.ramulator2"


def build_mem_controller_with_backend(
    *,
    name: str,
    controller_params: Dict[str, Any],
    backend_type: str,
    backend_params: Dict[str, Any],
    backend: str = "",
    mem_size: str = "",
    sst_module: Optional[Any] = None,
) -> Tuple[Any, Any]:
    """Create MemController + backend subcomponent and add params."""
    _ = (backend, mem_size)  # reserved for compatibility with callers
    sst = _resolve_sst_module(sst_module)
    controller = sst.Component(str(name), "memHierarchy.MemController")
    if controller_params:
        controller.addParams(dict(controller_params))
    backend_sc = controller.setSubComponent("backend", str(backend_type))
    if backend_params:
        backend_sc.addParams(dict(backend_params))
    return controller, backend_sc


def build_mem_bus(*, name: str, params: Dict[str, Any], sst_module: Optional[Any] = None) -> Any:
    """Create memHierarchy.Bus and add params."""
    sst = _resolve_sst_module(sst_module)
    bus = sst.Component(str(name), "memHierarchy.Bus")
    if params:
        bus.addParams(dict(params))
    return bus


def connect_bus_to_mem_controller(
    *,
    name: str,
    bus: Any,
    mem_controller: Any,
    link_latency: str = "5ns",
    bus_port: str = "lowlink0",
    mem_port: str = "highlink",
    sst_module: Optional[Any] = None,
) -> Any:
    """Create link and connect bus<->controller."""
    sst = _resolve_sst_module(sst_module)
    link = sst.Link(str(name))
    link.connect(
        (bus, str(bus_port), str(link_latency)),
        (mem_controller, str(mem_port), str(link_latency)),
    )
    return link


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
    link_latency: str = "5ns",
    override_engine: Optional[Any] = None,
    override_report: Optional[List[Dict[str, Any]]] = None,
    sst_module: Optional[Any] = None,
) -> Tuple[List[Any], List[Any]]:
    """Compatibility helper used by tensor_template."""
    sst = _resolve_sst_module(sst_module)
    controllers: List[Any] = []
    buses: List[Any] = []

    channels = int(num_mem_channels) if num_mem_channels is not None else 1
    if channels <= 0:
        channels = 1
    il_size = int(interleave_size_bytes) if interleave_size_bytes is not None else 0
    if il_size < 0:
        il_size = 0
    drain = bool(drain_bus)
    backend_key = normalize_mem_backend(backend)
    backend_component = mem_backend_component(backend_key)
    extra_backend_params = dict(backend_params or {})
    if backend_key == "ramulator2" and not str(extra_backend_params.get("configFile") or "").strip():
        raise ValueError("ramulator2 backend requires backend_params['configFile']")

    for pe_id in range(int(node_limit)):
        bus_params_base = {
            "bus_frequency": "1GHz",
            "debug": "0",
            "verbose": "0",
            # memHierarchy.Bus defaults to serializing to 1 event/cycle unless drain_bus=1.
            # For multi-channel memory modeling, callers can enable drain_bus to avoid
            # artificially bottlenecking on the shared bus.
            "drain_bus": 1 if drain else 0,
        }
        bus_tags = {"pe": int(pe_id)}
        bus_params = dict(bus_params_base)
        if override_engine is not None:
            bus_params = _apply_overrides(
                role="pe_mem_bus",
                component_type="memHierarchy.Bus",
                name=f"pe_{pe_id}_memory_bus",
                tags=bus_tags,
                params=bus_params_base,
                override_engine=override_engine,
                override_report=override_report,
            )
        bus = build_mem_bus(name=f"pe_{pe_id}_memory_bus", params=bus_params, sst_module=sst)
        buses.append(bus)

        pe_addr_start = int(pe_id) * int(pe_mem_region_bytes)
        total_bytes = int(pe_mem_region_bytes)

        # Optional interleave mode: each MemController owns interleaved chunks over the PE's address space.
        #
        # Why: to model multi-channel memory behavior (M24 tensor gate) without requiring the workload to
        # swizzle addresses. We only enable this when the caller provides a non-zero interleave size.
        #
        # Note: memHierarchy's MemController supports region interleaving via interleave_size/step params.
        use_interleave = (channels > 1) and (il_size > 0) and (total_bytes > 0)
        if use_interleave and (total_bytes % channels != 0):
            # Keep behavior safe and deterministic: fall back to contiguous slicing when region size
            # cannot be evenly divided across channels.
            use_interleave = False
        il_step = il_size * channels if use_interleave else 0

        base = total_bytes // channels if channels > 0 else total_bytes
        rem = total_bytes % channels if channels > 0 else 0
        ch_start = pe_addr_start
        for ch in range(channels):
            ch_bytes = base + (1 if ch < rem else 0)
            if ch_bytes <= 0:
                continue
            # Address region configuration:
            # - Contiguous slicing (default): each controller handles one continuous range.
            # - Interleaved slicing (optional): each controller handles repeated chunks across the full range.
            if use_interleave:
                mem_addr_start = pe_addr_start + (ch * il_size)
                mem_addr_end = pe_addr_start + total_bytes - 1
                controller_name = f"pe_{pe_id}_memory_controller_ch{ch}"
            else:
                mem_addr_start = ch_start
                mem_addr_end = mem_addr_start + ch_bytes - 1
                ch_start = mem_addr_end + 1
                controller_name = (
                    f"pe_{pe_id}_memory_controller"
                    if channels == 1
                    else f"pe_{pe_id}_memory_controller_ch{ch}"
                )
            controller_params_base = {
                "clock": "1GHz",
                "backing": "malloc",
                "addr_range_start": str(mem_addr_start),
                "addr_range_end": str(mem_addr_end),
                **(
                    {
                        "interleave_size": f"{il_size}B",
                        "interleave_step": f"{il_step}B",
                    }
                    if use_interleave
                    else {}
                ),
            }
            backend_params_base: Dict[str, Any] = {"mem_size": f"{int(ch_bytes)}B"}
            if backend_key == "simple":
                backend_params_base["access_time"] = str(mem_access_time)
            else:
                # ramulator2 backend expects configFile (and optionally debug knobs).
                backend_params_base["configFile"] = str(extra_backend_params.get("configFile"))
                if "debug" in extra_backend_params:
                    backend_params_base["debug"] = str(extra_backend_params.get("debug"))
                if "debug_level" in extra_backend_params:
                    backend_params_base["debug_level"] = str(extra_backend_params.get("debug_level"))
            tags = {"pe": int(pe_id), **({"channel": int(ch)} if channels != 1 else {})}

            controller_params = dict(controller_params_base)
            backend_params = dict(backend_params_base)
            if override_engine is not None:
                controller_params = _apply_overrides(
                    role="pe_mem_controller",
                    component_type="memHierarchy.MemController",
                    name=controller_name,
                    tags=tags,
                    params=controller_params_base,
                    override_engine=override_engine,
                    override_report=override_report,
                )
                backend_params = _apply_overrides(
                    role="pe_mem_controller.backend",
                    component_type=str(backend_component),
                    name=f"{controller_name}.backend",
                    tags=tags,
                    params=backend_params_base,
                    override_engine=override_engine,
                    override_report=override_report,
                )
            controller, _backend_sc = build_mem_controller_with_backend(
                name=controller_name,
                controller_params=controller_params,
                backend_type=str(backend_component),
                backend_params=backend_params,
                sst_module=sst,
            )
            controllers.append(controller)

            bus_port = f"lowlink{ch}" if channels != 1 else "lowlink0"
            link_name = f"pe_{pe_id}_bus_to_mem" if channels == 1 else f"pe_{pe_id}_bus_to_mem_ch{ch}"
            connect_bus_to_mem_controller(
                name=link_name,
                bus=bus,
                mem_controller=controller,
                link_latency=link_latency,
                bus_port=bus_port,
                mem_port="highlink",
                sst_module=sst,
            )

    return controllers, buses


def _append_override_report(
    *,
    override_report: Optional[List[Dict[str, Any]]],
    role: str,
    component_type: str,
    name: str,
    tags: Dict[str, Any],
    base_params: Dict[str, Any],
    final_params: Dict[str, Any],
    hits: List[Dict[str, Any]],
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
        hits=list(hits or []),
    )
    return dict(final_params)


def build_memhierarchy_memory(
    mem_controller_name: str,
    mem_bus_name: str,
    *,
    backend: str = "simple",
    controller_params: Optional[Dict[str, Any]] = None,
    backend_params: Optional[Dict[str, Any]] = None,
    bus_params: Optional[Dict[str, Any]] = None,
    link_latency: str = "5ns",
    link_name: Optional[str] = None,
    sst_module: Optional[Any] = None,
) -> Tuple[Any, Any, Any, Any]:
    """Build MemController + backend + Bus and connect them."""
    backend_type = mem_backend_component(backend)
    controller, backend_sc = build_mem_controller_with_backend(
        name=mem_controller_name,
        controller_params=dict(controller_params or {}),
        backend_type=backend_type,
        backend_params=dict(backend_params or {}),
        backend=str(backend),
        mem_size=str((backend_params or {}).get("mem_size", "")),
        sst_module=sst_module,
    )
    bus = build_mem_bus(
        name=mem_bus_name,
        params=dict(bus_params or {}),
        sst_module=sst_module,
    )
    link = connect_bus_to_mem_controller(
        name=link_name or f"{mem_bus_name}_to_{mem_controller_name}",
        bus=bus,
        mem_controller=controller,
        link_latency=link_latency,
        bus_port="lowlink0",
        mem_port="highlink",
        sst_module=sst_module,
    )
    return controller, backend_sc, bus, link


def _resolve_sst_module(sst_module: Optional[Any]) -> Any:
    if sst_module is not None:
        return sst_module
    import sst  # type: ignore

    return sst


def build_mem_controller_with_backend(
    *,
    name: str,
    controller_params: Optional[Dict[str, Any]] = None,
    backend_type: str = "memHierarchy.simpleMem",
    backend_params: Optional[Dict[str, Any]] = None,
    backend: str = "",
    mem_size: str = "",
    override_engine: Optional[Any] = None,
    override_report: Optional[Any] = None,
    sst_module: Optional[Any] = None,
) -> Tuple[Any, Any]:
    """Build a MemController and attach the backend subcomponent.

    This function matches the interface expected by:
      `sst_dram_si/mesh_template/build.py`

    Notes:
      - Params are accepted and applied, but `mesh_template/build.py` may
        also apply overrides and call `addParams()` again. Re-adding the
        same params is safe in SST.
      - `override_engine/override_report` are accepted for signature
        compatibility; the override logic lives in mesh_template.
    """
    _ = (backend, mem_size, override_engine, override_report)
    sst = _resolve_sst_module(sst_module)
    mem_controller = sst.Component(str(name), "memHierarchy.MemController")
    if controller_params:
        mem_controller.addParams(dict(controller_params))
    mem_backend = mem_controller.setSubComponent("backend", str(backend_type))
    if backend_params:
        mem_backend.addParams(dict(backend_params))
    return mem_controller, mem_backend


def build_mem_bus(
    *,
    name: str,
    params: Optional[Dict[str, Any]] = None,
    override_engine: Optional[Any] = None,
    override_report: Optional[Any] = None,
    sst_module: Optional[Any] = None,
) -> Any:
    """Build a memHierarchy.Bus component (interface expected by mesh_template)."""
    _ = (override_engine, override_report)
    sst = _resolve_sst_module(sst_module)
    bus = sst.Component(str(name), "memHierarchy.Bus")
    if params:
        bus.addParams(dict(params))
    return bus


def connect_bus_to_mem_controller(
    *,
    name: str,
    bus: Any,
    mem_controller: Any,
    link_latency: str = "5ns",
    bus_port: str = "lowlink0",
    mem_port: str = "highlink",
    sst_module: Optional[Any] = None,
) -> Any:
    """Connect bus<->mem_controller and return the SST Link."""
    sst = _resolve_sst_module(sst_module)
    link = sst.Link(str(name))
    link.connect(
        (bus, str(bus_port), str(link_latency)),
        (mem_controller, str(mem_port), str(link_latency)),
    )
    return link
