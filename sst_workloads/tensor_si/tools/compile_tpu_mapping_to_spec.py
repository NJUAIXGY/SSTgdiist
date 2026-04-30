#!/usr/bin/env python3
"""Compile a minimal TPU-like mapping description into a schema-v3 tensor spec.

This is intentionally KISS:
- Input mapping JSON describes platform/mesh and a program (ops list).
- Output is a schema-v3 spec consumable by snndl_spec_cli + run_snndl_with_time.sh.

This is NOT an XLA/MLIR frontend; it's a bridge format so architecture work can
iterate on program/spec generation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _as_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


def _as_str(v: Any, default: str) -> str:
    s = str(v).strip() if v is not None else ""
    return s if s else default


def compile_mapping_to_spec(mapping: Dict[str, Any]) -> Dict[str, Any]:
    platform = _as_dict(mapping.get("platform"))
    mesh_size = max(1, _as_int(platform.get("mesh_size"), _as_int(mapping.get("mesh_size"), 2)))
    sim_time = _as_str(platform.get("simulation_time"), _as_str(mapping.get("simulation_time"), "50us"))

    noc = _as_dict(mapping.get("noc"))
    memory = _as_dict(mapping.get("memory"))
    pe = _as_dict(mapping.get("pe"))
    tensor_params = _as_dict(mapping.get("tensor_params"))
    program = _as_dict(mapping.get("program"))
    profile = _as_str(mapping.get("profile"), "")

    # Optional profile defaults (mapping can override any of these explicitly).
    if _as_str(profile, "").strip().lower() in ("tpuv3", "tpu_v3", "tpu-v3"):
        defaults = {
            "tensor_array_m": 128,
            "tensor_array_n": 128,
            "tensor_compute_precision": "bf16",
            "tensor_ub_bytes": 256 * 1024,
            "tensor_acc_bytes": 256 * 1024,
            "tensor_onchip_model_enable": 1,
            "tensor_mem_req_bytes": 256,
            "tensor_mem_max_outstanding": 64,
            "tensor_dma_bandwidth_bytes_per_cycle": 1024,
        }
        for k, v in defaults.items():
            if k not in tensor_params:
                tensor_params[k] = v

    # Defaults match tensor_si typical settings.
    spec: Dict[str, Any] = {
        "schema_version": 3,
        "model": "tensor",
        "platform": {"mesh_size": mesh_size, "stop": {"mode": "time", "simulation_time": sim_time}},
        "noc": noc
        or {
            "type": "merlin_mesh",
            "params": {"link_bw": "40GiB/s", "buffer_size": "8KiB", "num_vns": 2},
        },
        "memory": memory
        or {
            "type": "shared",
            "backend": {"type": "simple"},
            "params": {"core_mem_region_bytes": 1048576, "mem_access_time": "100ns"},
        },
        "pe": pe or {"cores_per_pe": 4, "neurons_per_core": 4},
        "workload": {
            "type": "tensor",
            "stats_modules": "tensor",
            "params": tensor_params,
            "program": program,
        },
    }
    return spec


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mapping", required=True, help="mapping json path")
    ap.add_argument("--out", default="", help="output spec json path (default: stdout)")
    ap.add_argument(
        "--profile",
        default="",
        choices=("", "none", "tpuv3"),
        help="optional parameter profile defaults (overrides mapping.profile)",
    )
    args = ap.parse_args(argv)

    mapping_path = Path(args.mapping).expanduser().resolve()
    if not mapping_path.exists():
        return _fail(2, f"[m17][P0] missing mapping: {mapping_path}")
    try:
        mapping = _load_json(mapping_path)
    except Exception as exc:
        return _fail(2, f"[m17][P0] failed to load mapping json: {exc}")
    if not isinstance(mapping, dict):
        return _fail(2, "[m17][P0] mapping json must be an object")

    profile = str(args.profile or "").strip().lower()
    if profile and profile != "none":
        mapping["profile"] = profile

    spec = compile_mapping_to_spec(mapping)
    out_text = json.dumps(spec, indent=2, sort_keys=False) + "\n"
    out_path = args.out.strip()
    if out_path:
        Path(out_path).expanduser().resolve().write_text(out_text, encoding="utf-8")
        print(out_path)
    else:
        sys.stdout.write(out_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
