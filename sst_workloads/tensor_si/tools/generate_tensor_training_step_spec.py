#!/usr/bin/env python3
"""Generate a schema_v3 tensor spec for a single training step (GEMM + Allreduce).

This is a convenience tool for M11 to quickly produce workload.program specs without
hand-editing JSON.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict


def _as_int(v: str) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def _write(path: str, payload: Dict[str, Any]) -> None:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _apply_profile_defaults(args: argparse.Namespace) -> None:
    """Apply profile defaults conservatively (only override baseline defaults)."""

    profile = str(getattr(args, "profile", "none") or "none").strip().lower()
    if profile in {"", "none"}:
        return
    if profile not in {"tpuv3"}:
        return

    # Baseline defaults (match argparse defaults above).
    if int(args.array_m) == 32 and int(args.array_n) == 32:
        args.array_m = 128
        args.array_n = 128
    if str(args.compute_precision).strip().lower() == "fp16":
        args.compute_precision = "bf16"

    if int(args.ub_bytes) == 32768:
        args.ub_bytes = 256 * 1024
    if int(args.weight_bytes) == 0:
        args.weight_bytes = 0
    if int(args.acc_bytes) == 0:
        args.acc_bytes = 256 * 1024

    if int(args.onchip_model_enable) == 0:
        args.onchip_model_enable = 1

    if int(args.dma_bw_bytes_per_cycle) == 256:
        args.dma_bw_bytes_per_cycle = 1024
    if int(args.mem_req_bytes) == 64:
        args.mem_req_bytes = 256
    if int(args.mem_max_outstanding) == 32:
        args.mem_max_outstanding = 64


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=str, default="", help="output spec path (default: stdout)")

    ap.add_argument(
        "--profile",
        type=str,
        default="none",
        choices=("none", "tpuv3"),
        help="apply a TPU-like default parameter profile (only overrides baseline defaults)",
    )

    ap.add_argument("--mesh-size", type=int, default=2)
    ap.add_argument("--simulation-time", type=str, default="50us")

    ap.add_argument("--noc-type", type=str, default="merlin_mesh", choices=("merlin_mesh", "merlin_torus"))
    ap.add_argument("--noc-shape", type=str, default="", help="for merlin_torus only, e.g. 2x8")

    ap.add_argument("--cores-per-pe", type=int, default=4)
    ap.add_argument("--neurons-per-core", type=int, default=4)

    ap.add_argument("--m", type=int, default=64)
    ap.add_argument("--n", type=int, default=64)
    ap.add_argument("--k", type=int, default=64)
    ap.add_argument("--element-bytes", type=int, default=2)
    ap.add_argument("--tile-m", type=int, default=32)
    ap.add_argument("--tile-n", type=int, default=32)
    ap.add_argument("--tile-k", type=int, default=32)

    ap.add_argument("--array-m", type=int, default=32)
    ap.add_argument("--array-n", type=int, default=32)
    ap.add_argument("--compute-precision", type=str, default="fp16")

    ap.add_argument("--mem-req-bytes", type=int, default=64)
    ap.add_argument("--mem-max-outstanding", type=int, default=32)

    ap.add_argument("--ub-bytes", type=int, default=32768)
    ap.add_argument("--weight-bytes", type=int, default=0)
    ap.add_argument("--acc-bytes", type=int, default=0)
    ap.add_argument("--onchip-model-enable", type=int, default=0, choices=(0, 1))
    ap.add_argument("--onchip-bank-model-enable", type=int, default=0, choices=(0, 1))

    ap.add_argument("--dma-bw-bytes-per-cycle", type=int, default=256)
    ap.add_argument("--noc-bw-bytes-per-cycle", type=int, default=0)

    ap.add_argument("--collective-algo", type=str, default="ring_chunked", choices=("legacy_bytes", "ring_chunked", "torus_2d_rs_ag"))
    ap.add_argument("--collective-scope", type=str, default="per_system", choices=("per_core", "per_pe", "per_system"))
    ap.add_argument("--collective-packet-bytes", type=int, default=256)
    ap.add_argument("--collective-chunk-bytes", type=int, default=4096)
    ap.add_argument("--collective-max-inflight-pkts", type=int, default=4)
    ap.add_argument("--collective-credit-enable", type=int, default=0, choices=(0, 1))
    ap.add_argument("--collective-credit-window-pkts", type=int, default=0)
    ap.add_argument("--allreduce-bytes", type=int, default=0, help="per-core local bytes (default: M*N*element_bytes)")
    ap.add_argument(
        "--explicit-dma",
        action="store_true",
        help="emit an M7-style program with explicit dma_read/dma_write/gemm_ub/fence + allreduce (instead of legacy gemm + allreduce)",
    )

    args = ap.parse_args()
    _apply_profile_defaults(args)

    mesh_size = max(1, int(args.mesh_size))
    m = max(1, int(args.m))
    n = max(1, int(args.n))
    k = max(1, int(args.k))
    element_bytes = max(1, int(args.element_bytes))
    allreduce_bytes = int(args.allreduce_bytes) if int(args.allreduce_bytes) > 0 else int(m * n * element_bytes)
    a_bytes = int(m * k * element_bytes)
    b_bytes = int(k * n * element_bytes)
    c_bytes = int(m * n * element_bytes)

    noc_params: Dict[str, Any] = {"link_bw": "40GiB/s", "buffer_size": "8KiB", "num_vns": 2}
    if str(args.noc_type).strip().lower() == "merlin_torus":
        shape = str(args.noc_shape or "").strip()
        if not shape:
            # Default to square torus consistent with mesh_size^2 nodes.
            shape = f"{mesh_size}x{mesh_size}"
        noc_params["shape"] = shape

    spec: Dict[str, Any] = {
        "schema_version": 3,
        "model": "tensor",
        "platform": {
            "mesh_size": mesh_size,
            "stop": {"mode": "time", "simulation_time": str(args.simulation_time)},
        },
        "noc": {"type": str(args.noc_type), "params": noc_params},
        "memory": {
            "type": "shared",
            "backend": {"type": "simple"},
            "params": {"core_mem_region_bytes": 1048576, "mem_access_time": "100ns"},
        },
        "pe": {"cores_per_pe": max(1, int(args.cores_per_pe)), "neurons_per_core": max(1, int(args.neurons_per_core))},
        "workload": {
            "type": "tensor",
            "stats_modules": "tensor",
            "params": {
                "tensor_m": m,
                "tensor_n": n,
                "tensor_k": k,
                "tensor_element_bytes": element_bytes,
                "tensor_array_m": max(1, int(args.array_m)),
                "tensor_array_n": max(1, int(args.array_n)),
                "tensor_compute_precision": str(args.compute_precision),
                "tensor_iterations": 1,
                "tensor_mem_req_bytes": max(1, int(args.mem_req_bytes)),
                "tensor_mem_max_outstanding": max(1, int(args.mem_max_outstanding)),
                "tensor_tile_m": max(0, int(args.tile_m)),
                "tensor_tile_n": max(0, int(args.tile_n)),
                "tensor_tile_k": max(0, int(args.tile_k)),
                "tensor_ub_bytes": max(0, int(args.ub_bytes)),
                "tensor_weight_bytes": max(0, int(args.weight_bytes)),
                "tensor_acc_bytes": max(0, int(args.acc_bytes)),
                "tensor_onchip_model_enable": int(args.onchip_model_enable),
                "tensor_onchip_bank_model_enable": int(args.onchip_bank_model_enable),
                "tensor_dma_bandwidth_bytes_per_cycle": max(0, int(args.dma_bw_bytes_per_cycle)),
                "tensor_noc_bandwidth_bytes_per_cycle": max(0, int(args.noc_bw_bytes_per_cycle)),
                "tensor_collective_type": "allreduce",
                "tensor_collective_blocking": 1,
                "tensor_collective_scope": str(args.collective_scope),
                "tensor_collective_packet_bytes": max(8, int(args.collective_packet_bytes)),
                "tensor_collective_algo": str(args.collective_algo),
                "tensor_collective_chunk_bytes": max(0, int(args.collective_chunk_bytes)),
                "tensor_collective_reduce_overhead_cycles": 0,
                "tensor_collective_max_inflight_pkts": max(1, int(args.collective_max_inflight_pkts)),
                "tensor_collective_credit_enable": int(args.collective_credit_enable),
                "tensor_collective_credit_window_pkts": max(0, int(args.collective_credit_window_pkts)),
                "tensor_collective_credit_return_mode": "event_on_recv",
            },
            "program": {
                "loop": False,
                "ops": [],
            },
        },
    }

    program_ops = spec["workload"]["program"]["ops"]
    if args.explicit_dma:
        # Match TensorWorkload::resolveComputeProfile_ defaults (subset; override path omitted).
        precision = str(args.compute_precision).strip().lower()
        throughput_scale = 1.0
        if precision == "fp32":
            throughput_scale = 0.5
        elif precision == "tf32":
            throughput_scale = 0.75
        elif precision in ("int8", "fp8"):
            throughput_scale = 2.0
        # bf16/fp16 default to 1.0

        peak = max(1, int(max(1, int(args.array_m)) * max(1, int(args.array_n))))
        eff_peak = max(1.0, float(peak) * float(throughput_scale))
        macs = float(m * n * k)
        mxu_cycles = max(1, int(math.ceil(macs / eff_peak)))

        # A/B reads fill UB, GEMM consumes UB deps and produces C into UB, then write back and fence.
        program_ops.extend(
            [
                {"op_type": "dma_read", "bytes": a_bytes},
                {"op_type": "dma_read", "bytes": b_bytes},
                {
                    "op_type": "gemm_ub",
                    "cycles": mxu_cycles,
                    "ub_read_bytes": a_bytes + b_bytes,
                    "ub_write_bytes": c_bytes,
                },
                {"op_type": "dma_write", "bytes": c_bytes},
                {"op_type": "fence"},
                {"op_type": "allreduce", "bytes": allreduce_bytes, "blocking": True},
            ]
        )
    else:
        # M11 default: legacy GEMM (shape-driven) + allreduce.
        program_ops.extend(
            [
                {"op_type": "gemm"},
                {"op_type": "allreduce", "bytes": allreduce_bytes, "blocking": True},
            ]
        )

    if args.out:
        _write(str(args.out), spec)
    else:
        print(json.dumps(spec, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
