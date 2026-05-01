#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Tuple


_DIRECTION_OFFSETS: Tuple[Tuple[str, int, int, int], ...] = (
    ("east", 1, 0, 0),
    ("west", -1, 0, 0),
    ("south", 0, 1, 0),
    ("north", 0, -1, 0),
    ("up", 0, 0, 1),
    ("down", 0, 0, -1),
)


def build_router_structure_by_node_id(nodes: Iterable[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    node_list = [
        {
            "node_id": int(node["node_id"]),
            "x": int(node["x"]),
            "y": int(node["y"]),
            "z": int(node["z"]),
        }
        for node in nodes
    ]
    node_id_by_coord = {
        (node["x"], node["y"], node["z"]): int(node["node_id"])
        for node in node_list
    }

    structures: Dict[int, Dict[str, Any]] = {}
    for node in sorted(node_list, key=lambda item: int(item["node_id"])):
        coord = {"x": int(node["x"]), "y": int(node["y"]), "z": int(node["z"])}
        ports: List[Dict[str, Any]] = [
            {
                "direction": "local",
                "peer_kind": "node",
                "peer_node_id": int(node["node_id"]),
                "peer_coord": dict(coord),
            }
        ]
        neighbor_node_ids: List[int] = []

        for direction, dx, dy, dz in _DIRECTION_OFFSETS:
            neighbor_coord = (coord["x"] + dx, coord["y"] + dy, coord["z"] + dz)
            neighbor_node_id = node_id_by_coord.get(neighbor_coord)
            if neighbor_node_id is None:
                continue
            neighbor_node_ids.append(int(neighbor_node_id))
            ports.append(
                {
                    "direction": direction,
                    "peer_kind": "router",
                    "peer_router_id": int(neighbor_node_id),
                    "peer_node_id": int(neighbor_node_id),
                    "peer_coord": {
                        "x": int(neighbor_coord[0]),
                        "y": int(neighbor_coord[1]),
                        "z": int(neighbor_coord[2]),
                    },
                }
            )

        structures[int(node["node_id"])] = {
            "ports": ports,
            "neighbor_node_ids": neighbor_node_ids,
        }
    return structures


def build_multicast_blocks(
    nodes: Iterable[Dict[str, Any]],
    *,
    block_w: int,
    block_h: int,
    block_d: int,
) -> List[Dict[str, Any]]:
    if int(block_w) <= 0 or int(block_h) <= 0 or int(block_d) <= 0:
        return []

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for raw_node in nodes:
        node = {
            "node_id": int(raw_node["node_id"]),
            "x": int(raw_node["x"]),
            "y": int(raw_node["y"]),
            "z": int(raw_node["z"]),
        }
        block_key = f"{node['x'] // int(block_w)}:{node['y'] // int(block_h)}:{node['z'] // int(block_d)}"
        grouped.setdefault(block_key, []).append(node)

    blocks: List[Dict[str, Any]] = []
    for block_key, members in sorted(grouped.items(), key=lambda item: item[0]):
        sorted_members = sorted(
            members,
            key=lambda node: (int(node["z"]), int(node["y"]), int(node["x"]), int(node["node_id"])),
        )
        anchor = sorted_members[0]
        layer_ingress_node_ids = [
            int(node["node_id"])
            for node in sorted_members
            if int(node["x"]) == int(anchor["x"]) and int(node["y"]) == int(anchor["y"])
        ]
        blocks.append(
            {
                "block_key": block_key,
                "member_node_ids": [int(node["node_id"]) for node in sorted_members],
                "anchor_node_id": int(anchor["node_id"]),
                "anchor_coord": {
                    "x": int(anchor["x"]),
                    "y": int(anchor["y"]),
                    "z": int(anchor["z"]),
                },
                "layer_ingress_node_ids": layer_ingress_node_ids,
                "bounds": {
                    "min_x": min(int(node["x"]) for node in sorted_members),
                    "max_x": max(int(node["x"]) for node in sorted_members),
                    "min_y": min(int(node["y"]) for node in sorted_members),
                    "max_y": max(int(node["y"]) for node in sorted_members),
                    "min_z": min(int(node["z"]) for node in sorted_members),
                    "max_z": max(int(node["z"]) for node in sorted_members),
                },
            }
        )
    return blocks


__all__ = ["build_router_structure_by_node_id", "build_multicast_blocks"]
