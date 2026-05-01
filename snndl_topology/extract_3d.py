#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, List

from snn3dexp.memory import attachment_latency_for_node, build_stack_descriptors, home_stack_for_node
from snn3dexp.mesh3d_template.build import build_effective_config
from snn3dexp.noc.multicast_3d import build_router_descriptors, connect_router_links_3d
from snn3dexp.shape3d import parse_mesh_shape

from .ir import build_topology_ir
from .structures import build_multicast_blocks, build_router_structure_by_node_id


def extract_3d_topology(
    raw_spec: Dict[str, Any] | None = None,
    *,
    case_name: str = "bootstrap_smoke",
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    effective_cfg = build_effective_config(raw_spec, case_name=case_name)
    shape = parse_mesh_shape(str(effective_cfg["platform"]["mesh_shape"]))
    noc_cfg = dict(effective_cfg["noc"])
    memory_cfg = dict(effective_cfg["memory"])
    processing_cfg = dict(effective_cfg.get("processing") or {})
    processing_params = dict(processing_cfg.get("params") or {})
    num_cores = int(processing_params.get("num_cores", 1) or 1)

    router_descriptors = build_router_descriptors(shape=shape, noc_params=noc_cfg)
    mesh_links = connect_router_links_3d(routers=router_descriptors, shape=shape)

    physical_nodes: List[Dict[str, Any]] = []
    physical_routers: List[Dict[str, Any]] = []
    physical_links: List[Dict[str, Any]] = []
    for node_id in range(shape.total_nodes):
        x, y, z = shape.from_node_id(node_id)
        physical_nodes.append(
            {
                "node_id": int(node_id),
                "kind": "pe",
                "x": int(x),
                "y": int(y),
                "z": int(z),
                "num_cores": int(num_cores),
            }
        )
        router = dict(router_descriptors[node_id])
        router_params = dict(router.get("params") or {})
        physical_routers.append(
            {
                "router_id": int(node_id),
                "node_id": int(node_id),
                "component_type": str(router.get("component_type", "unknown")),
                "native_3d_enable": bool(noc_cfg.get("native_3d_enable", False)),
                "vertical_route_order": str(router_params.get("vertical_route_order", noc_cfg.get("vertical_route_order", "zxy"))),
            }
        )
        physical_links.append(
            {
                "src": f"node:{node_id}",
                "dst": f"router:{node_id}",
                "kind": "local",
            }
        )

    router_structures = build_router_structure_by_node_id(physical_nodes)
    for router in physical_routers:
        structure = router_structures.get(int(router["node_id"]), {})
        router["ports"] = list(structure.get("ports", []))
        router["neighbor_node_ids"] = list(structure.get("neighbor_node_ids", []))

    for link in mesh_links:
        physical_links.append(
            {
                "src": f"router:{int(link['src'])}",
                "dst": f"router:{int(link['dst'])}",
                "kind": str(link["direction"]),
            }
        )

    stacks = build_stack_descriptors(shape=shape, memory_params=memory_cfg)
    bindings: List[Dict[str, Any]] = []
    if str(memory_cfg.get("kind", "hbm_like") or "hbm_like") != "legacy_per_pe":
        for node_id in range(shape.total_nodes):
            bindings.append(
                {
                    "node_id": int(node_id),
                    "stack_id": int(home_stack_for_node(node_id=node_id, shape=shape, memory_params=memory_cfg)),
                    "attach_latency_ns": int(
                        attachment_latency_for_node(node_id=node_id, shape=shape, memory_params=memory_cfg)
                    ),
                }
            )

    return build_topology_ir(
        shape={"x": shape.dim_x, "y": shape.dim_y, "z": shape.dim_z},
        physical={
            "nodes": physical_nodes,
            "routers": physical_routers,
            "links": physical_links,
        },
        logical={"groups": []},
        multicast={
            "block_shape": {
                "w": int(noc_cfg.get("multicast_block_dim_x", 0) or 0),
                "h": int(noc_cfg.get("multicast_block_dim_y", 0) or 0),
                "d": int(noc_cfg.get("multicast_block_dim_z", 0) or 0),
            },
            "blocks": build_multicast_blocks(
                physical_nodes,
                block_w=int(noc_cfg.get("multicast_block_dim_x", 0) or 0),
                block_h=int(noc_cfg.get("multicast_block_dim_y", 0) or 0),
                block_d=int(noc_cfg.get("multicast_block_dim_z", 0) or 0),
            ),
        },
        memory={
            "kind": str(memory_cfg.get("kind", "unknown") or "unknown"),
            "stacks": list(stacks),
            "bindings": bindings,
        },
        metadata={
            "extractor": "3d",
            "source": "snn3dexp",
            "case_name": str(dict(effective_cfg.get("experiment") or {}).get("case_name", case_name) or case_name),
            **dict(metadata or {}),
        },
    )


__all__ = ["extract_3d_topology"]
