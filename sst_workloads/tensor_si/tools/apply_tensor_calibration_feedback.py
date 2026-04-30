#!/usr/bin/env python3
"""Apply M45 calibration feedback to a tensor spec under whitelist + threshold policy."""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

CONF_RANK = {"unverified": 0, "low": 1, "medium": 2, "high": 3}


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return float(default)
        if isinstance(value, (int, float)):
            f = float(value)
            return f if math.isfinite(f) else float(default)
        txt = str(value).strip()
        if not txt:
            return float(default)
        f = float(txt)
        return f if math.isfinite(f) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(default)
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            if not math.isfinite(value):
                return int(default)
            return int(round(value))
        txt = str(value).strip()
        if not txt:
            return int(default)
        return int(round(float(txt)))
    except Exception:
        return int(default)


def _confidence_rank(value: str) -> int:
    return CONF_RANK.get(str(value or "").strip().lower(), -1)


def _ensure_workload_params(spec: Dict[str, Any]) -> Dict[str, Any]:
    workload = spec.get("workload")
    if not isinstance(workload, dict):
        raise ValueError("spec.workload must be object")
    params = workload.get("params")
    if not isinstance(params, dict):
        raise ValueError("spec.workload.params must be object")
    return params


def _clamp_int(value: int, lo: int | None, hi: int | None) -> int:
    out = int(value)
    if lo is not None and out < lo:
        out = int(lo)
    if hi is not None and out > hi:
        out = int(hi)
    return out


def _ratio_bound(old: int, value: int, max_ratio: float) -> int:
    if old <= 0 or max_ratio <= 1.0:
        return int(value)
    hi = int(math.floor(float(old) * float(max_ratio)))
    lo = int(math.ceil(float(old) / float(max_ratio)))
    return _clamp_int(int(value), lo, hi)


def _build_report(
    *,
    source_spec: Path,
    patched_spec: Path,
    profile_path: Path,
    whitelist_path: Path,
    status: str,
    profile_confidence: str,
    confidence_min: str,
    applied_changes: List[Dict[str, Any]],
    skipped_changes: List[Dict[str, Any]],
    violations: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "status": status,
        "source_spec": str(source_spec),
        "patched_spec": str(patched_spec),
        "profile": str(profile_path),
        "whitelist": str(whitelist_path),
        "profile_confidence": profile_confidence,
        "confidence_min": confidence_min,
        "applied_change_count": len(applied_changes),
        "applied_changes": applied_changes,
        "skipped_changes": skipped_changes,
        "violations": violations,
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-spec", required=True, help="input tensor spec json")
    ap.add_argument("--profile", required=True, help="M41 calibration profile json")
    ap.add_argument("--whitelist", required=True, help="M45 feedback whitelist json")
    ap.add_argument("--out", required=True, help="patched spec json output")
    ap.add_argument("--patch-report", default="", help="feedback patch report output")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    source_path = Path(args.source_spec).expanduser().resolve()
    profile_path = Path(args.profile).expanduser().resolve()
    whitelist_path = Path(args.whitelist).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    report_path = Path(args.patch_report).expanduser().resolve() if args.patch_report else out_path.with_suffix(".patch.json")

    for p, flag in ((source_path, "--source-spec"), (profile_path, "--profile"), (whitelist_path, "--whitelist")):
        if not p.exists():
            print(f"[m45][P0] missing {flag}: {p}", file=sys.stderr)
            return 2

    try:
        source_spec = _load_json(source_path)
        profile = _load_json(profile_path)
        whitelist = _load_json(whitelist_path)
    except Exception as exc:
        print(f"[m45][P0] json parse failed: {exc}", file=sys.stderr)
        return 2

    if not isinstance(source_spec, dict) or not isinstance(profile, dict) or not isinstance(whitelist, dict):
        print("[m45][P0] source/profile/whitelist root must be object", file=sys.stderr)
        return 2

    try:
        patched_spec = copy.deepcopy(source_spec)
        params = _ensure_workload_params(patched_spec)
    except Exception as exc:
        print(f"[m45][P0] invalid source spec structure: {exc}", file=sys.stderr)
        return 2

    allowed_paths = {str(x).strip() for x in whitelist.get("allowed_paths", []) if str(x).strip()}
    numeric_limits = whitelist.get("numeric_limits") if isinstance(whitelist.get("numeric_limits"), dict) else {}
    allowed_profiles = {str(x).strip().lower() for x in whitelist.get("allowed_profiles", []) if str(x).strip()}

    if not allowed_paths:
        print("[m45][P0] whitelist.allowed_paths must be non-empty", file=sys.stderr)
        return 2

    factors = profile.get("factors") if isinstance(profile.get("factors"), dict) else {}
    bw_scale = _to_float(factors.get("suggested_mem_bandwidth_scale"), 1.0)
    if bw_scale <= 0.0:
        bw_scale = 1.0

    profile_conf = str(profile.get("confidence", "unverified")).strip().lower() or "unverified"
    conf_min = str(whitelist.get("confidence_min", "low")).strip().lower() or "low"

    applied_changes: List[Dict[str, Any]] = []
    skipped_changes: List[Dict[str, Any]] = []
    violations: List[Dict[str, Any]] = []

    def _apply_change(path: str, new_value: Any, reason: str) -> None:
        if path not in allowed_paths:
            violations.append({"path": path, "reason": "path_not_in_whitelist", "new": new_value})
            return
        key = path.split(".")[-1]
        old_value = params.get(key)
        if old_value == new_value:
            skipped_changes.append({"path": path, "reason": "no_effect", "old": old_value, "new": new_value})
            return
        params[key] = new_value
        applied_changes.append({"path": path, "old": old_value, "new": new_value, "reason": reason})

    if _confidence_rank(profile_conf) < _confidence_rank(conf_min):
        violations.append(
            {
                "path": "confidence_gate",
                "reason": "profile_confidence_below_min",
                "profile_confidence": profile_conf,
                "confidence_min": conf_min,
            }
        )

    suggested_profile = str(profile.get("suggested_profile", "")).strip().lower()
    if suggested_profile:
        path = "workload.params.tensor_memory_hierarchy_profile"
        if allowed_profiles and suggested_profile not in allowed_profiles:
            skipped_changes.append(
                {
                    "path": path,
                    "reason": "profile_not_allowed",
                    "suggested": suggested_profile,
                }
            )
        else:
            _apply_change(path, suggested_profile, "suggested_profile")

    calibration_tag = str(profile.get("calibration_tag", "")).strip()
    if calibration_tag:
        _apply_change("workload.params.tensor_calibration_tag", calibration_tag, "calibration_tag")

    for path in sorted(numeric_limits.keys()):
        if path not in allowed_paths:
            skipped_changes.append({"path": path, "reason": "limit_path_not_whitelisted"})
            continue

        key = path.split(".")[-1]
        old_value = _to_int(params.get(key), 0)
        if old_value <= 0:
            skipped_changes.append({"path": path, "reason": "old_value_non_positive", "old": old_value})
            continue

        rule = numeric_limits.get(path)
        if not isinstance(rule, dict):
            skipped_changes.append({"path": path, "reason": "invalid_limit_rule"})
            continue

        min_v = _to_int(rule.get("min"), old_value)
        max_v = _to_int(rule.get("max"), old_value)
        max_ratio = _to_float(rule.get("max_ratio"), 1.0)

        raw_new = int(round(float(old_value) * bw_scale))
        ratio_new = _ratio_bound(old_value, raw_new, max_ratio)
        bounded_new = _clamp_int(ratio_new, min_v, max_v)

        if bounded_new <= 0:
            skipped_changes.append(
                {
                    "path": path,
                    "reason": "bounded_value_non_positive",
                    "old": old_value,
                    "suggested": raw_new,
                }
            )
            continue

        _apply_change(path, int(bounded_new), "mem_bandwidth_scale")

    status = "pass" if not violations else "fail"

    report = _build_report(
        source_spec=source_path,
        patched_spec=out_path,
        profile_path=profile_path,
        whitelist_path=whitelist_path,
        status=status,
        profile_confidence=profile_conf,
        confidence_min=conf_min,
        applied_changes=applied_changes,
        skipped_changes=skipped_changes,
        violations=violations,
    )

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(patched_spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"[m45][P0] write output failed: {exc}", file=sys.stderr)
        return 2

    prefix = f"[m45:{args.label}] " if args.label else "[m45] "
    print(
        f"{prefix}status={status} applied={len(applied_changes)} "
        f"skipped={len(skipped_changes)} violations={len(violations)}"
    )
    print(f"{prefix}patched_spec={out_path}")
    print(f"{prefix}patch_report={report_path}")

    if status != "pass":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
