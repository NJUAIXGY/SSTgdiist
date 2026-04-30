#!/usr/bin/env python3
"""Validate M49 memory timing proxy trends."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_int(value: Any) -> int:
    try:
        if isinstance(value, bool):
            return 0
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return int(value)
        txt = str(value).strip()
        if not txt:
            return 0
        return int(float(txt))
    except Exception:
        return 0


def _avg(total: int, samples: int) -> float:
    if samples <= 0:
        return 0.0
    return float(total) / float(samples)


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _load_tensor(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tensor = payload.get("tensor")
    return tensor if isinstance(tensor, dict) else None


def _load_cfg(summary_path: Path) -> Dict[str, Any]:
    path = summary_path.parent / "effective_config.json"
    if not path.exists():
        return {}
    try:
        payload = _load_json(path)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    cfg = payload.get("tensor_cfg")
    return cfg if isinstance(cfg, dict) else {}


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--edge", required=True, help="edge profile summary json")
    ap.add_argument("--server", required=True, help="server profile summary json")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    edge_p = Path(args.edge).expanduser().resolve()
    server_p = Path(args.server).expanduser().resolve()

    if not edge_p.exists():
        return _fail(2, f"[m49][P0] missing --edge summary: {edge_p}")
    if not server_p.exists():
        return _fail(2, f"[m49][P0] missing --server summary: {server_p}")

    edge = _load_tensor(edge_p)
    server = _load_tensor(server_p)
    if edge is None or server is None:
        return _fail(2, "[m49][P0] invalid summary schema: missing tensor object")

    edge_bytes = _to_int(edge.get("tensor_mem_bytes_read_total"))
    server_bytes = _to_int(server.get("tensor_mem_bytes_read_total"))
    if edge_bytes <= 0 or server_bytes <= 0:
        return _fail(3, f"[m49][P1] expected mem_bytes_read_total > 0 (edge={edge_bytes}, server={server_bytes})")
    if edge_bytes != server_bytes:
        return _fail(3, f"[m49][P1] expected mem_bytes_read_total match (edge={edge_bytes}, server={server_bytes})")

    edge_samples = _to_int(edge.get("tensor_mem_read_latency_samples_total"))
    server_samples = _to_int(server.get("tensor_mem_read_latency_samples_total"))
    edge_total = _to_int(edge.get("tensor_mem_read_latency_cycles_total"))
    server_total = _to_int(server.get("tensor_mem_read_latency_cycles_total"))

    if edge_samples > 0 and server_samples > 0:
        edge_avg = _avg(edge_total, edge_samples)
        server_avg = _avg(server_total, server_samples)
        if edge_avg <= server_avg:
            return _fail(3, f"[m49][P1] expected edge avg read latency > server (edge={edge_avg:.3f}, server={server_avg:.3f})")
    else:
        edge_avg = 0.0
        server_avg = 0.0

    edge_queue = _to_int(edge.get("tensor_stall_mem_outstanding_cycles_total"))
    server_queue = _to_int(server.get("tensor_stall_mem_outstanding_cycles_total"))
    if edge_queue < server_queue:
        return _fail(3, f"[m49][P1] expected edge queue pressure >= server (edge={edge_queue}, server={server_queue})")

    edge_cfg = _load_cfg(edge_p)
    server_cfg = _load_cfg(server_p)
    edge_profile = str(edge_cfg.get("tensor_memory_hierarchy_profile", "")).strip().lower()
    server_profile = str(server_cfg.get("tensor_memory_hierarchy_profile", "")).strip().lower()
    if edge_profile != "edge" or server_profile != "server":
        return _fail(3, f"[m49][P1] expected edge/server profiles (edge={edge_profile!r}, server={server_profile!r})")

    edge_req = _to_int(edge_cfg.get("tensor_mem_req_bytes"))
    server_req = _to_int(server_cfg.get("tensor_mem_req_bytes"))
    if edge_req >= server_req:
        return _fail(3, f"[m49][P1] expected edge mem_req_bytes < server (edge={edge_req}, server={server_req})")

    prefix = f"[m49:{args.label}] " if args.label else "[m49] "
    print(f"{prefix}mem_bytes_read_total={edge_bytes}")
    if edge_samples > 0 and server_samples > 0:
        print(f"{prefix}mem_read_latency_avg_cycles edge={edge_avg:.3f} server={server_avg:.3f}")
    print(f"{prefix}queue_pressure edge={edge_queue} server={server_queue}")
    print(f"{prefix}mem_req_bytes edge={edge_req} server={server_req}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
