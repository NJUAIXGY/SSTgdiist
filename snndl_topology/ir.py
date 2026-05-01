#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value)


def _normalize_shape(shape: Dict[str, Any]) -> Dict[str, int]:
    raw_shape = dict(shape or {})
    x = int(raw_shape.get("x", raw_shape.get("dim_x", 0)) or 0)
    y = int(raw_shape.get("y", raw_shape.get("dim_y", 0)) or 0)
    z = int(raw_shape.get("z", raw_shape.get("dim_z", 0)) or 0)
    if x < 1 or y < 1 or z < 1:
        raise ValueError(f"invalid topology shape: {raw_shape!r}")
    return {
        "x": x,
        "y": y,
        "z": z,
        "total_nodes": x * y * z,
    }


def build_topology_ir(
    *,
    shape: Dict[str, Any],
    physical: Dict[str, Any] | None = None,
    logical: Dict[str, Any] | None = None,
    multicast: Dict[str, Any] | None = None,
    memory: Dict[str, Any] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    physical_section = dict(physical or {})
    logical_section = dict(logical or {})
    multicast_section = dict(multicast or {})
    memory_section = dict(memory or {})

    normalized_multicast = {
        **multicast_section,
        "block_shape": {
            "w": int(dict(multicast_section.get("block_shape") or {}).get("w", 0) or 0),
            "h": int(dict(multicast_section.get("block_shape") or {}).get("h", 0) or 0),
            "d": int(dict(multicast_section.get("block_shape") or {}).get("d", 0) or 0),
        },
        "blocks": _as_list(multicast_section.get("blocks")),
    }

    return {
        "shape": _normalize_shape(shape),
        "physical": {
            **physical_section,
            "nodes": _as_list(physical_section.get("nodes")),
            "routers": _as_list(physical_section.get("routers")),
            "links": _as_list(physical_section.get("links")),
        },
        "logical": {
            **logical_section,
            "groups": _as_list(logical_section.get("groups")),
        },
        "multicast": normalized_multicast,
        "memory": {
            **memory_section,
            "kind": str(memory_section.get("kind", "unknown") or "unknown"),
            "stacks": _as_list(memory_section.get("stacks")),
            "bindings": _as_list(memory_section.get("bindings")),
        },
        "metadata": dict(metadata or {}),
    }


__all__ = ["build_topology_ir"]
