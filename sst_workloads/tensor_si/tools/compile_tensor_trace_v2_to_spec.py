#!/usr/bin/env python3
"""Compile tensor trace-v2 JSON into schema-v3 tensor spec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


class TraceSpecV2Error(RuntimeError):
    pass


ALLOWED_RESOURCES = {"dma", "mxu", "vec", "coll", "ctrl"}


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(default)
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return int(value)
        txt = str(value).strip()
        if not txt:
            return int(default)
        return int(float(txt))
    except Exception:
        return int(default)


def _as_str(value: Any, default: str = "") -> str:
    txt = str(value if value is not None else "").strip()
    return txt if txt else str(default)


def _normalize_ops(raw_ops: List[Any]) -> Tuple[List[Dict[str, Any]], int, int, int]:
    if not raw_ops:
        raise TraceSpecV2Error("trace_v2.program_ops must be a non-empty list")

    out: List[Dict[str, Any]] = []
    dep_edges = 0
    resource_set: Set[str] = set()

    for i, op in enumerate(raw_ops):
        if not isinstance(op, dict):
            raise TraceSpecV2Error(f"trace_v2.program_ops[{i}] must be an object")
        op_type = _as_str(op.get("op_type"), "").lower()
        if op_type not in {"dma_read", "dma_write", "gemm_ub", "allreduce", "fence", "softmax", "gemm"}:
            raise TraceSpecV2Error(
                f"trace_v2.program_ops[{i}].op_type={op_type!r} invalid "
                "(expected dma_read|dma_write|gemm_ub|allreduce|fence|softmax|gemm)"
            )

        deps_raw = op.get("deps", [])
        deps = _as_list(deps_raw)
        dep_norm: List[int] = []
        for d in deps:
            dep_i = _as_int(d, -1)
            if dep_i < 0 or dep_i >= i:
                raise TraceSpecV2Error(f"trace_v2.program_ops[{i}].deps contains invalid index={dep_i}")
            if dep_i not in dep_norm:
                dep_norm.append(dep_i)
        dep_edges += len(dep_norm)

        resource = _as_str(op.get("resource"), "").lower()
        if not resource:
            if op_type in {"dma_read", "dma_write"}:
                resource = "dma"
            elif op_type in {"gemm", "gemm_ub"}:
                resource = "mxu"
            elif op_type == "allreduce":
                resource = "coll"
            elif op_type == "softmax":
                resource = "vec"
            else:
                resource = "ctrl"
        if resource not in ALLOWED_RESOURCES:
            raise TraceSpecV2Error(f"trace_v2.program_ops[{i}].resource={resource!r} invalid")
        resource_set.add(resource)

        norm: Dict[str, Any] = {"op_type": op_type}
        for key in (
            "bytes",
            "cycles",
            "elems",
            "ub_read_bytes",
            "ub_write_bytes",
            "buf",
            "m",
            "n",
            "k",
        ):
            if key in op:
                norm[key] = _as_int(op.get(key), 0)
        if "blocking" in op:
            norm["blocking"] = bool(op.get("blocking"))

        if op_type in {"dma_read", "dma_write", "allreduce"} and _as_int(norm.get("bytes"), 0) <= 0:
            raise TraceSpecV2Error(f"trace_v2.program_ops[{i}].bytes must be > 0 for {op_type}")

        out.append(norm)

    return out, len(out), dep_edges, len(resource_set)


def compile_trace_v2_to_spec(trace: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, int]]:
    platform = _as_dict(trace.get("platform"))
    tensor_params = _as_dict(trace.get("tensor_params"))
    program_ops, op_count, dep_edges, resource_kinds = _normalize_ops(_as_list(trace.get("program_ops")))

    mesh_size = max(1, _as_int(platform.get("mesh_size"), 1))
    sim_time = _as_str(platform.get("simulation_time"), "25us")

    params: Dict[str, Any] = {
        "tensor_capability_profile": "trace_v2_bridge_v1",
        "tensor_scheduler_model": "trace_v2_compiled",
        "tensor_memory_hierarchy_profile": "balanced",
        "tensor_exec_mode": "program",
        "tensor_iterations": 1,
        "tensor_mem_enable": 1,
        "tensor_mem_req_bytes": 64,
        "tensor_mem_max_outstanding": 64,
        "tensor_dma_bandwidth_bytes_per_cycle": 256,
        "tensor_program_issue_width": 4,
        "tensor_trace_v2_version": 2,
        "tensor_trace_v2_op_count": op_count,
        "tensor_trace_v2_dependency_edges": dep_edges,
        "tensor_trace_v2_resource_kinds": resource_kinds,
    }
    params.update(tensor_params)

    spec: Dict[str, Any] = {
        "schema_version": 3,
        "model": "tensor",
        "platform": {
            "mesh_size": mesh_size,
            "stop": {"mode": "time", "simulation_time": sim_time},
        },
        "noc": {
            "type": "merlin_mesh",
            "params": {"link_bw": "40GiB/s", "buffer_size": "8KiB", "num_vns": 2},
        },
        "memory": {
            "type": "shared",
            "backend": {"type": "simple"},
            "params": {"core_mem_region_bytes": 1048576, "mem_access_time": "60ns"},
        },
        "pe": {"cores_per_pe": 1, "neurons_per_core": 1},
        "workload": {
            "type": "tensor",
            "stats_modules": "tensor",
            "params": params,
            "program": {"loop": False, "ops": program_ops},
        },
    }

    meta = {
        "op_count": op_count,
        "dependency_edges": dep_edges,
        "resource_kinds": resource_kinds,
    }
    return spec, meta


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, help="input trace-v2 json")
    ap.add_argument("--out", required=True, help="output tensor schema-v3 spec json")
    args = ap.parse_args(argv)

    trace_p = Path(args.trace).expanduser().resolve()
    out_p = Path(args.out).expanduser().resolve()

    if not trace_p.exists():
        raise SystemExit(f"[m65][P0] trace not found: {trace_p}")

    try:
        payload = json.loads(trace_p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"[m65][P0] invalid trace json: {exc}")
    if not isinstance(payload, dict):
        raise SystemExit("[m65][P0] trace json must be an object")

    try:
        spec, meta = compile_trace_v2_to_spec(payload)
    except TraceSpecV2Error as exc:
        raise SystemExit(f"[m65][P1] {exc}")

    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[m65] compiled_spec: {out_p}")
    print(
        f"[m65] trace_v2_meta op_count={meta['op_count']} "
        f"dependency_edges={meta['dependency_edges']} resource_kinds={meta['resource_kinds']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
