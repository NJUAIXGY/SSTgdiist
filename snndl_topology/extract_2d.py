#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, List

from snn3dexp.shape3d import parse_legacy_mesh_size
from sst_dram_si.mesh_template.task_snn import resolve_fixed_4x4_layers

from .ir import build_topology_ir
from .structures import build_multicast_blocks, build_router_structure_by_node_id


def _group_entries_for_fixed_mesh(*, node_limit: int, mesh_size: int) -> List[Dict[str, Any]]:
    if mesh_size != 4:
        return []
    groups: List[Dict[str, Any]] = []
    for name, node_ids in resolve_fixed_4x4_layers().items():
        filtered = [int(node_id) for node_id in node_ids if int(node_id) < node_limit]
        if filtered:
            groups.append({"name": str(name), "node_ids": filtered})
    return groups


def extract_2d_topology(
    *,
    mesh_size: int = 4,
    node_limit: int | None = None,
    num_cores: int = 1,
    vertical_route_order: str = "xy",
    memory_kind: str = "legacy_per_pe",
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    shape = parse_legacy_mesh_size(mesh_size)
    max_nodes = shape.total_nodes
    limit = max_nodes if node_limit is None else int(node_limit)
    if limit < 1 or limit > max_nodes:
        raise ValueError(f"invalid node_limit={node_limit!r} for mesh_size={mesh_size!r}")

    physical_nodes: List[Dict[str, Any]] = []
    physical_routers: List[Dict[str, Any]] = []
    physical_links: List[Dict[str, Any]] = []
    for node_id in range(limit):
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
        physical_routers.append(
            {
                "router_id": int(node_id),
                "node_id": int(node_id),
                "component_type": "SnnDL.MulticastRouter",
                "native_3d_enable": False,
                "vertical_route_order": str(vertical_route_order),
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

    for node_id in range(limit):
        x, y, _ = shape.from_node_id(node_id)
        if x + 1 < mesh_size:
            east = node_id + 1
            if east < limit:
                physical_links.append(
                    {
                        "src": f"router:{node_id}",
                        "dst": f"router:{east}",
                        "kind": "east",
                    }
                )
        if y + 1 < mesh_size:
            south = node_id + mesh_size
            if south < limit:
                physical_links.append(
                    {
                        "src": f"router:{node_id}",
                        "dst": f"router:{south}",
                        "kind": "south",
                    }
                )

    return build_topology_ir(
        shape={"x": mesh_size, "y": mesh_size, "z": 1},
        physical={
            "nodes": physical_nodes,
            "routers": physical_routers,
            "links": physical_links,
        },
        logical={"groups": _group_entries_for_fixed_mesh(node_limit=limit, mesh_size=mesh_size)},
        multicast={
            "block_shape": {"w": 0, "h": 0, "d": 0},
            "blocks": build_multicast_blocks(physical_nodes, block_w=0, block_h=0, block_d=0),
        },
        memory={
            "kind": str(memory_kind or "legacy_per_pe"),
            "stacks": [],
            "bindings": [],
        },
        metadata={
            "extractor": "2d",
            "source": "mesh_template",
            **dict(metadata or {}),
        },
    )


__all__ = ["extract_2d_topology"]
