#!/usr/bin/env python3
"""Compile trace-json (M51) to schema-v3 tensor spec."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


ALLOWED_OPS = {"dma_read", "dma_write", "gemm_ub", "allreduce", "softmax", "fence"}


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_int(v: Any, default: int = 0) -> int:
    try:
        if isinstance(v, bool):
            return int(default)
        if isinstance(v, int):
            return int(v)
        if isinstance(v, float):
            return int(v)
        txt = str(v).strip()
        if not txt:
            return int(default)
        return int(float(txt))
    except Exception:
        return int(default)


def _to_str(v: Any, default: str = "") -> str:
    txt = str(v if v is not None else "").strip()
    return txt if txt else str(default)


def _validate_trace(trace: Dict[str, Any], schema: Dict[str, Any] | None = None) -> None:
    if not isinstance(trace, dict):
        raise ValueError("trace root must be object")
    if int(trace.get("schema_version", 0) or 0) != 1:
        raise ValueError("trace schema_version must be 1")
    if not _to_str(trace.get("name")):
        raise ValueError("trace.name is required")

    program = trace.get("program")
    if not isinstance(program, list) or not program:
        raise ValueError("trace.program must be non-empty list")

    allowed = set(ALLOWED_OPS)
    if isinstance(schema, dict):
        raw = schema.get("allowed_ops")
        if isinstance(raw, list) and raw:
            allowed = {str(x).strip().lower() for x in raw if str(x).strip()}

    for i, op in enumerate(program):
        if not isinstance(op, dict):
            raise ValueError(f"trace.program[{i}] must be object")
        name = _to_str(op.get("op")).lower()
        if name not in allowed:
            raise ValueError(f"trace.program[{i}].op={name!r} not in allowed_ops")
        if name in {"dma_read", "dma_write", "allreduce"}:
            b = _to_int(op.get("bytes"), 0)
            if b <= 0:
                raise ValueError(f"trace.program[{i}] {name} requires bytes > 0")
        if name == "softmax":
            elems = _to_int(op.get("elems"), 0)
            if elems <= 0:
                raise ValueError(f"trace.program[{i}] softmax requires elems > 0")


def _map_program(program: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for op in program:
        name = _to_str(op.get("op")).lower()
        if name in {"dma_read", "dma_write"}:
            out.append({"op_type": name, "bytes": max(1, _to_int(op.get("bytes"), 1))})
        elif name == "gemm_ub":
            out.append(
                {
                    "op_type": "gemm_ub",
                    "cycles": max(1, _to_int(op.get("cycles"), 1)),
                    "ub_read_bytes": max(0, _to_int(op.get("ub_read_bytes"), 0)),
                    "ub_write_bytes": max(0, _to_int(op.get("ub_write_bytes"), 0)),
                }
            )
        elif name == "allreduce":
            out.append(
                {
                    "op_type": "allreduce",
                    "bytes": max(1, _to_int(op.get("bytes"), 1)),
                    "blocking": bool(op.get("blocking", True)),
                }
            )
        elif name == "softmax":
            out.append({"op_type": "softmax", "elems": max(1, _to_int(op.get("elems"), 1))})
        else:
            out.append({"op_type": "fence"})
    return out


def compile_trace(trace: Dict[str, Any]) -> Dict[str, Any]:
    platform = trace.get("platform") if isinstance(trace.get("platform"), dict) else {}
    noc = trace.get("noc") if isinstance(trace.get("noc"), dict) else {}
    memory = trace.get("memory") if isinstance(trace.get("memory"), dict) else {}
    tensor_params = trace.get("tensor_params") if isinstance(trace.get("tensor_params"), dict) else {}

    mesh_size = max(1, _to_int(platform.get("mesh_size"), 2))
    sim_time = _to_str(platform.get("simulation_time"), "30us")

    noc_type = _to_str(noc.get("type"), "merlin_mesh").lower()
    if noc_type not in {"merlin_mesh", "merlin_torus"}:
        noc_type = "merlin_mesh"

    noc_params: Dict[str, Any] = {
        "link_bw": _to_str(noc.get("link_bw"), "40GiB/s"),
        "buffer_size": _to_str(noc.get("buffer_size"), "8KiB"),
        "num_vns": max(1, _to_int(noc.get("num_vns"), 2)),
    }
    if noc_type == "merlin_torus":
        noc_params["shape"] = _to_str(noc.get("shape"), f"{mesh_size}x{mesh_size}")

    backend = _to_str(memory.get("backend"), "simple").lower()
    if backend not in {"simple", "ramulator2"}:
        backend = "simple"

    memory_block: Dict[str, Any] = {
        "type": "shared",
        "backend": {"type": backend},
        "params": {
            "core_mem_region_bytes": max(1024, _to_int(memory.get("core_mem_region_bytes"), 1048576)),
            "mem_access_time": _to_str(memory.get("mem_access_time"), "100ns"),
        },
    }
    if backend == "ramulator2":
        cfg = _to_str(memory.get("configFile"), "sst_dram_si/configs/ramulator2_hbm2.cfg")
        memory_block["backend"]["params"] = {"configFile": cfg, "debug": "0", "debug_level": "0"}

    params: Dict[str, Any] = {
        "tensor_capability_profile": _to_str(tensor_params.get("tensor_capability_profile"), "trace_bridge_v1"),
        "tensor_scheduler_model": _to_str(tensor_params.get("tensor_scheduler_model"), "trace_replay"),
        "tensor_memory_hierarchy_profile": _to_str(tensor_params.get("tensor_memory_hierarchy_profile"), "balanced"),
        "tensor_exec_mode": "program",
        "tensor_iterations": max(1, _to_int(tensor_params.get("tensor_iterations"), 1)),
        "tensor_mem_enable": 1,
        "tensor_mem_req_bytes": max(8, _to_int(tensor_params.get("tensor_mem_req_bytes"), 64)),
        "tensor_mem_max_outstanding": max(1, _to_int(tensor_params.get("tensor_mem_max_outstanding"), 64)),
        "tensor_dma_bandwidth_bytes_per_cycle": max(0, _to_int(tensor_params.get("tensor_dma_bandwidth_bytes_per_cycle"), 256)),
        "tensor_program_issue_width": max(1, _to_int(tensor_params.get("tensor_program_issue_width"), 4)),
        "tensor_collective_type": _to_str(tensor_params.get("tensor_collective_type"), "allreduce"),
        "tensor_collective_blocking": max(0, min(1, _to_int(tensor_params.get("tensor_collective_blocking"), 1))),
        "tensor_collective_scope": _to_str(tensor_params.get("tensor_collective_scope"), "per_system"),
        "tensor_collective_packet_bytes": max(8, _to_int(tensor_params.get("tensor_collective_packet_bytes"), 256)),
        "tensor_collective_algo": _to_str(tensor_params.get("tensor_collective_algo"), "ring_chunked"),
        "tensor_collective_chunk_bytes": max(0, _to_int(tensor_params.get("tensor_collective_chunk_bytes"), 4096)),
    }

    for k, v in tensor_params.items():
        key = str(k).strip()
        if key.startswith("tensor_"):
            params[key] = v

    program = trace.get("program") if isinstance(trace.get("program"), list) else []

    spec: Dict[str, Any] = {
        "schema_version": 3,
        "model": "tensor",
        "platform": {
            "mesh_size": mesh_size,
            "stop": {"mode": "time", "simulation_time": sim_time},
        },
        "noc": {
            "type": noc_type,
            "params": noc_params,
        },
        "memory": memory_block,
        "pe": {"cores_per_pe": 1, "neurons_per_core": 1},
        "workload": {
            "type": "tensor",
            "stats_modules": "tensor",
            "params": params,
            "program": {"loop": False, "ops": _map_program(program)},
        },
    }
    return spec


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, help="trace json path")
    ap.add_argument("--schema", default="", help="optional schema json path")
    ap.add_argument("--out", required=True, help="output spec json path")
    args = ap.parse_args(argv)

    trace_p = Path(args.trace).expanduser().resolve()
    out_p = Path(args.out).expanduser().resolve()
    schema_p = Path(args.schema).expanduser().resolve() if str(args.schema).strip() else None

    if not trace_p.exists():
        return _fail(2, f"[m51][P0] missing --trace: {trace_p}")
    if schema_p and not schema_p.exists():
        return _fail(2, f"[m51][P0] missing --schema: {schema_p}")

    try:
        trace = _load_json(trace_p)
    except Exception as exc:
        return _fail(2, f"[m51][P0] cannot parse trace json: {exc}")

    schema: Dict[str, Any] | None = None
    if schema_p:
        try:
            schema = _load_json(schema_p)
        except Exception as exc:
            return _fail(2, f"[m51][P0] cannot parse schema json: {exc}")

    try:
        _validate_trace(trace, schema=schema)
        spec = compile_trace(trace)
    except Exception as exc:
        return _fail(2, f"[m51][P0] invalid trace input: {exc}")

    try:
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        return _fail(2, f"[m51][P0] write output failed: {exc}")

    print(f"[m51] trace={trace_p}")
    print(f"[m51] spec={out_p}")
    print(f"[m51] ops={len(spec['workload']['program']['ops'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
