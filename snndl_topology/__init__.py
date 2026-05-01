#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict

from snn3dexp.mesh3d_template.build import build_effective_config
from snn3dexp.shape3d import parse_mesh_shape

from .extract_2d import extract_2d_topology
from .extract_3d import extract_3d_topology
from .ir import build_topology_ir


def build_topology_summary(
    raw_spec: Dict[str, Any] | None = None,
    *,
    source: str = "auto",
    case_name: str = "bootstrap_smoke",
    mesh_size: int = 4,
    node_limit: int | None = None,
    num_cores: int = 1,
) -> Dict[str, Any]:
    normalized_source = str(source or "auto").strip().lower()
    if normalized_source == "mesh_template":
        return extract_2d_topology(mesh_size=mesh_size, node_limit=node_limit, num_cores=num_cores)
    if normalized_source == "snn3dexp":
        return extract_3d_topology(raw_spec, case_name=case_name)
    if normalized_source != "auto":
        raise ValueError(f"unsupported topology source: {source!r}")
    if raw_spec is None:
        return extract_2d_topology(mesh_size=mesh_size, node_limit=node_limit, num_cores=num_cores)

    effective_cfg = build_effective_config(raw_spec, case_name=case_name)
    shape = parse_mesh_shape(str(effective_cfg["platform"]["mesh_shape"]))
    if shape.dim_z > 1:
        return extract_3d_topology(raw_spec, case_name=case_name)
    if shape.dim_x != shape.dim_y:
        raise ValueError(f"mesh_template extractor requires square 2D mesh, got {shape.as_string()}")
    processing_cfg = dict(effective_cfg.get("processing") or {})
    processing_params = dict(processing_cfg.get("params") or {})
    return extract_2d_topology(
        mesh_size=shape.dim_x,
        node_limit=int(effective_cfg["platform"].get("node_limit", shape.total_nodes) or shape.total_nodes),
        num_cores=int(processing_params.get("num_cores", 1) or 1),
        vertical_route_order=str(effective_cfg["noc"].get("vertical_route_order", "xy")),
        memory_kind=str(effective_cfg["memory"].get("kind", "legacy_per_pe") or "legacy_per_pe"),
        metadata={
            "source": "snn3dexp",
            "case_name": str(dict(effective_cfg.get("experiment") or {}).get("case_name", case_name) or case_name),
        },
    )


__all__ = [
    "build_topology_ir",
    "build_topology_summary",
    "extract_2d_topology",
    "extract_3d_topology",
]
