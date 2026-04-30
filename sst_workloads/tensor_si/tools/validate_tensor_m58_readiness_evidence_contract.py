#!/usr/bin/env python3
"""Validate M58 readiness evidence weighting contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return float(default)
        if isinstance(value, (int, float)):
            return float(value)
        txt = str(value).strip()
        if not txt:
            return float(default)
        return float(txt)
    except Exception:
        return float(default)


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


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config-only", required=True)
    ap.add_argument("--evidence-rich", required=True)
    ap.add_argument("--label", default="")
    args = ap.parse_args(argv)

    cfg_p = Path(args.config_only).expanduser().resolve()
    rich_p = Path(args.evidence_rich).expanduser().resolve()

    if not cfg_p.exists():
        return _fail(2, f"[m58][P0] missing --config-only summary: {cfg_p}")
    if not rich_p.exists():
        return _fail(2, f"[m58][P0] missing --evidence-rich summary: {rich_p}")

    cfg = _load_readiness(cfg_p)
    rich = _load_readiness(rich_p)
    if cfg is None or rich is None:
        return _fail(2, "[m58][P0] invalid summary schema: missing npu_tpu_readiness object")

    cfg_profile = str(cfg.get("capability_profile", "")).strip().lower()
    rich_profile = str(rich.get("capability_profile", "")).strip().lower()
    if cfg_profile != "readiness_evidence_v2" or rich_profile != "readiness_evidence_v2":
        return _fail(
            3,
            "[m58][P1] expected capability_profile=readiness_evidence_v2 for both scenarios "
            f"(config_only={cfg_profile!r}, evidence_rich={rich_profile!r})",
        )

    cfg_score = _to_float(cfg.get("capability_score_total"), 0.0)
    rich_score = _to_float(rich.get("capability_score_total"), 0.0)
    cfg_factor = _to_float(cfg.get("evidence_factor"), 1.0)
    rich_factor = _to_float(rich.get("evidence_factor"), 1.0)

    cfg_conf = str(cfg.get("calibration_confidence", "")).strip().lower() or "unverified"
    rich_conf = str(rich.get("calibration_confidence", "")).strip().lower() or "unverified"

    cfg_flags_raw = cfg.get("regression_drift_flags")
    rich_flags_raw = rich.get("regression_drift_flags")
    cfg_flags = cfg_flags_raw if isinstance(cfg_flags_raw, list) else []
    rich_flags = rich_flags_raw if isinstance(rich_flags_raw, list) else []

    if rich_score <= cfg_score:
        return _fail(3, f"[m58][P1] expected evidence_rich score > config_only (config_only={cfg_score:.3f}, evidence_rich={rich_score:.3f})")
    if rich_factor <= cfg_factor:
        return _fail(3, f"[m58][P1] expected evidence_rich factor > config_only (config_only={cfg_factor:.3f}, evidence_rich={rich_factor:.3f})")
    if cfg_conf not in {"unverified", "low"}:
        return _fail(3, f"[m58][P1] expected config_only calibration_confidence in {{unverified,low}} (got {cfg_conf!r})")
    if not cfg_flags:
        return _fail(3, "[m58][P1] expected config_only drift flags non-empty")
    if rich_conf not in {"medium", "high"}:
        return _fail(3, f"[m58][P1] expected evidence_rich calibration_confidence in {{medium,high}} (got {rich_conf!r})")

    prefix = f"[m58:{args.label}] " if args.label else "[m58] "
    print(f"{prefix}score config_only={cfg_score:.3f} evidence_rich={rich_score:.3f}")
    print(f"{prefix}factor config_only={cfg_factor:.3f} evidence_rich={rich_factor:.3f}")
    print(f"{prefix}confidence config_only={cfg_conf} evidence_rich={rich_conf}")
    print(f"{prefix}flags config_only={len(cfg_flags)} evidence_rich={len(rich_flags)}")
    print(f"{prefix}PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
