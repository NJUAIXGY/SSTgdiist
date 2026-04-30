#!/usr/bin/env python3
"""Compile a lightweight tensor trace JSON into schema-v3 tensor spec."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


class TraceSpecError(RuntimeError):
    pass


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


def _normalize_ops(raw_ops: List[Any]) -> List[Dict[str, Any]]:
    if not raw_ops:
        raise TraceSpecError("trace.program_ops must be a non-empty list")
    out: List[Dict[str, Any]] = []
    for i, op in enumerate(raw_ops):
        if not isinstance(op, dict):
            raise TraceSpecError(f"trace.program_ops[{i}] must be an object")
        op_type = _as_str(op.get("op_type"), "").lower()
        if not op_type:
            raise TraceSpecError(f"trace.program_ops[{i}].op_type is required")
        if op_type not in {"dma_read", "dma_write", "gemm_ub", "allreduce", "fence", "softmax", "gemm"}:
            raise TraceSpecError(
                f"trace.program_ops[{i}].op_type={op_type!r} invalid "
                "(expected dma_read|dma_write|gemm_ub|allreduce|fence|softmax|gemm)"
            )

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

        if op_type in {"dma_read", "dma_write"} and _as_int(norm.get("bytes"), 0) <= 0:
            raise TraceSpecError(f"trace.program_ops[{i}].bytes must be > 0 for {op_type}")
        if op_type == "gemm_ub":
            cycles = _as_int(norm.get("cycles"), 0)
            if cycles < 0:
                raise TraceSpecError(f"trace.program_ops[{i}].cycles must be >= 0 for gemm_ub")
        if op_type == "allreduce" and _as_int(norm.get("bytes"), 0) <= 0:
            raise TraceSpecError(f"trace.program_ops[{i}].bytes must be > 0 for allreduce")

        out.append(norm)
    return out


def compile_trace_to_spec(trace: Dict[str, Any]) -> Dict[str, Any]:
    platform = _as_dict(trace.get("platform"))
    tensor_params = _as_dict(trace.get("tensor_params"))
    program_ops = _normalize_ops(_as_list(trace.get("program_ops")))

    mesh_size = max(1, _as_int(platform.get("mesh_size"), 1))
    sim_time = _as_str(platform.get("simulation_time"), "25us")

    params: Dict[str, Any] = {
        "tensor_capability_profile": "trace_bridge_v1",
        "tensor_scheduler_model": "trace_compiled",
        "tensor_memory_hierarchy_profile": "balanced",
        "tensor_exec_mode": "program",
        "tensor_iterations": 1,
        "tensor_mem_enable": 1,
        "tensor_mem_req_bytes": 64,
        "tensor_mem_max_outstanding": 64,
        "tensor_dma_bandwidth_bytes_per_cycle": 256,
        "tensor_program_issue_width": 4,
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
    return spec


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, help="input trace json")
    ap.add_argument("--out", required=True, help="output tensor schema-v3 spec json")
    args = ap.parse_args(argv)

    trace_p = Path(args.trace).expanduser().resolve()
    out_p = Path(args.out).expanduser().resolve()

    if not trace_p.exists():
        raise SystemExit(f"[m59][P0] trace not found: {trace_p}")

    try:
        payload = json.loads(trace_p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"[m59][P0] invalid trace json: {exc}")
    if not isinstance(payload, dict):
        raise SystemExit("[m59][P0] trace json must be an object")

    try:
        spec = compile_trace_to_spec(payload)
    except TraceSpecError as exc:
        raise SystemExit(f"[m59][P1] {exc}")

    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[m59] compiled_spec: {out_p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
