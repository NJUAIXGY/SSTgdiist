#!/usr/bin/env python3
"""Validate tensor mesh essential summary (minimal checks)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List


def resolve_default_summary_path() -> Path:
    env = os.environ.get("TENSOR_SI_RUN_DIR", "").strip()
    if env:
        return (Path(env).expanduser().resolve() / "essential_summary_tensor_mesh.json").resolve()
    here = Path(__file__).resolve()
    project_root = here.parents[1]
    return (project_root / "analysis" / "tensor_latest" / "essential_summary_tensor_mesh.json").resolve()


def _get_int(d: Dict[str, Any], key: str) -> int:
    try:
        return int(d.get(key, 0) or 0)
    except Exception:
        return 0


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", type=str, default="", help="summary json path")
    args = ap.parse_args(argv)

    summary_path = Path(args.summary).expanduser().resolve() if args.summary else resolve_default_summary_path()
    if not summary_path.exists():
        print(f"[tensor_mesh] FAIL: missing summary: {summary_path}")
        return 2

    try:
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[tensor_mesh] FAIL: cannot parse summary: {e}")
        return 2

    tensor = payload.get("tensor", {}) if isinstance(payload, dict) else {}
    if not isinstance(tensor, dict):
        print("[tensor_mesh] FAIL: invalid summary schema (tensor section)")
        return 2

    stream = payload.get("stream", None) if isinstance(payload, dict) else None
    if stream is not None and not isinstance(stream, dict):
        print("[tensor_mesh] FAIL: invalid summary schema (stream section)")
        return 2
    stream = stream if isinstance(stream, dict) else {}

    mac_ops = _get_int(tensor, "tensor_mac_ops_total")
    bytes_rd = _get_int(tensor, "tensor_mem_bytes_read_total")
    bytes_wr = _get_int(tensor, "tensor_mem_bytes_write_total")
    pkt_s = _get_int(tensor, "tensor_pkt_sent_total")
    pkt_r = _get_int(tensor, "tensor_pkt_recv_total")

    stream_bytes = _get_int(stream, "stream_mem_bytes_read_total") + _get_int(stream, "stream_mem_bytes_written_total")
    stream_pkts = _get_int(stream, "stream_pkt_sent_total") + _get_int(stream, "stream_pkt_recv_total")
    if mac_ops <= 0 and (bytes_rd + bytes_wr) <= 0 and (pkt_s + pkt_r) <= 0 and stream_bytes <= 0 and stream_pkts <= 0:
        print("[tensor_mesh] FAIL: no activity detected (all key counters are zero)")
        return 1

    print("[tensor_mesh] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
