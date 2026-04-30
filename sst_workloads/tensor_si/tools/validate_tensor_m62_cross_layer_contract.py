#!/usr/bin/env python3
"""Validate M62 cross-layer bottleneck attribution contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


LAYER_KEYS = ("compute", "memory", "noc")


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any) -> float:
    try:
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        txt = str(value).strip()
        if not txt:
            return 0.0
        return float(txt)
    except Exception:
        return 0.0


def _load_readiness(path: Path) -> Dict[str, Any] | None:
    try:
        payload = _load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    ready = payload.get("npu_tpu_readiness")
    return ready if isinstance(ready, dict) else None


def _fail(code: int, msg: str) -> int:
    print(msg, file=sys.stderr)
    return code


def _extract(name: str, ready: Dict[str, Any]) -> tuple[str, Dict[str, float], List[Any], List[Any]] | None:
    attribution = ready.get("cross_layer_attribution")
    if not isinstance(attribution, dict):
        print(f"[m62][P1] {name}: missing cross_layer_attribution", file=sys.stderr)
        return None
    dominant = str(attribution.get("dominant_layer", "")).strip().lower()
    if dominant not in LAYER_KEYS:
        print(f"[m62][P1] {name}: invalid dominant_layer={dominant!r}", file=sys.stderr)
        return None

    shares_raw = attribution.get("layer_share")
    if not isinstance(shares_raw, dict):
        print(f"[m62][P1] {name}: missing layer_share", file=sys.stderr)
        return None
    shares = {k: _to_float(shares_raw.get(k)) for k in LAYER_KEYS}
    total_share = shares["compute"] + shares["memory"] + shares["noc"]
    if total_share <= 0.0:
        print(f"[m62][P1] {name}: invalid layer_share sum={total_share}", file=sys.stderr)
        return None

    top_bottlenecks = ready.get("top_bottlenecks")
    suggestions = ready.get("suggested_interventions")
    if not isinstance(top_bottlenecks, list) or not top_bottlenecks:
        print(f"[m62][P1] {name}: top_bottlenecks must be non-empty list", file=sys.stderr)
        return None
    if not isinstance(suggestions, list) or not suggestions:
        print(f"[m62][P1] {name}: suggested_interventions must be non-empty list", file=sys.stderr)
        return None

    return dominant, shares, top_bottlenecks, suggestions


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--memory", required=True)
    ap.add_argument("--noc", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    mem_p = Path(args.memory).expanduser().resolve()
    noc_p = Path(args.noc).expanduser().resolve()

    if not mem_p.exists():
        return _fail(2, f"[m62][P0] missing --memory summary: {mem_p}")
    if not noc_p.exists():
        return _fail(2, f"[m62][P0] missing --noc summary: {noc_p}")

    mem_ready = _load_readiness(mem_p)
    noc_ready = _load_readiness(noc_p)
    if mem_ready is None or noc_ready is None:
        return _fail(2, "[m62][P0] invalid summary schema: missing npu_tpu_readiness")

    mem_ex = _extract("memory", mem_ready)
    noc_ex = _extract("noc", noc_ready)
    if mem_ex is None or noc_ex is None:
        return 3

    mem_dom, mem_share, mem_top, _mem_suggest = mem_ex
    noc_dom, noc_share, noc_top, _noc_suggest = noc_ex

    if mem_share["memory"] <= mem_share["noc"]:
        return _fail(
            3,
            "[m62][P1] expected memory scenario memory_share > noc_share "
            f"(memory={mem_share['memory']:.3f}, noc={mem_share['noc']:.3f})",
        )
    if noc_share["noc"] <= 0.0:
        return _fail(
            3,
            "[m62][P1] expected noc scenario noc_share > 0 "
            f"(noc={noc_share['noc']:.3f})",
        )
    if noc_share["noc"] <= mem_share["noc"]:
        return _fail(
            3,
            "[m62][P1] expected noc scenario noc_share uplift over memory scenario "
            f"(memory_scenario_noc={mem_share['noc']:.3f}, noc_scenario_noc={noc_share['noc']:.3f})",
        )
    if noc_share["memory"] >= mem_share["memory"]:
        return _fail(
            3,
            "[m62][P1] expected noc scenario memory_share reduction vs memory scenario "
            f"(memory_scenario_memory={mem_share['memory']:.3f}, noc_scenario_memory={noc_share['memory']:.3f})",
        )

    prefix = f"[m62:{args.label}] " if args.label else "[m62] "
    print(
        f"{prefix}dominant memory={mem_dom} noc={noc_dom} "
        f"memory_share(memory={mem_share['memory']:.3f}, noc={mem_share['noc']:.3f}) "
        f"noc_share(memory={noc_share['memory']:.3f}, noc={noc_share['noc']:.3f})"
    )
    print(f"{prefix}top_bottlenecks memory={mem_top[:2]} noc={noc_top[:2]}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
