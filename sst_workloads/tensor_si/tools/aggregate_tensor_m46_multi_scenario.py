#!/usr/bin/env python3
"""Aggregate M46 multi-scenario readiness/drift outputs into one gate report."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


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


def _load_waivers(path: Path) -> Dict[str, Dict[str, Any]]:
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("exceptions root must be object")

    raw = payload.get("waived_scenarios")
    if raw is None:
        return {}
    if not isinstance(raw, list):
        raise ValueError("waived_scenarios must be list")

    today = dt.date.today()
    waivers: Dict[str, Dict[str, Any]] = {}
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"waived_scenarios[{idx}] must be object")
        name = str(item.get("name", "")).strip()
        reason = str(item.get("reason", "")).strip()
        expires_at = str(item.get("expires_at", "")).strip()
        if not name:
            raise ValueError(f"waived_scenarios[{idx}] missing name")
        if not reason:
            raise ValueError(f"waived_scenarios[{idx}] missing reason")
        if not expires_at:
            raise ValueError(f"waived_scenarios[{idx}] missing expires_at")
        try:
            exp_date = dt.date.fromisoformat(expires_at)
        except Exception as exc:
            raise ValueError(f"waived_scenarios[{idx}] invalid expires_at={expires_at!r}") from exc

        waivers[name] = {
            "reason": reason,
            "expires_at": expires_at,
            "active": exp_date >= today,
        }

    return waivers


def _parse_results_file(path: Path) -> List[Tuple[str, Path, Path, Path]]:
    rows: List[Tuple[str, Path, Path, Path]] = []
    for ln_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 4:
            raise ValueError(f"results line {ln_no}: expected 4 tab-separated columns")

        name = str(parts[0]).strip()
        cand = Path(str(parts[1]).strip()).expanduser().resolve()
        drift = Path(str(parts[2]).strip()).expanduser().resolve()
        patch = Path(str(parts[3]).strip()).expanduser().resolve()
        if not name:
            raise ValueError(f"results line {ln_no}: scenario name is empty")
        rows.append((name, cand, drift, patch))

    if not rows:
        raise ValueError("results file has no scenario rows")
    return rows


def _round3(x: float) -> float:
    return float(round(float(x), 3))


def _summary(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "avg": 0.0}
    return {
        "min": _round3(min(values)),
        "max": _round3(max(values)),
        "avg": _round3(sum(values) / float(len(values))),
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-file", required=True, help="tab-separated scenario results file")
    ap.add_argument("--exceptions", required=True, help="M46 gate exception config json")
    ap.add_argument("--out", required=True, help="output M46 report json")
    ap.add_argument("--label", default="", help="optional label")
    args = ap.parse_args(argv)

    results_path = Path(args.results_file).expanduser().resolve()
    exceptions_path = Path(args.exceptions).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    for p, flag in ((results_path, "--results-file"), (exceptions_path, "--exceptions")):
        if not p.exists():
            print(f"[m46][P0] missing {flag}: {p}", file=sys.stderr)
            return 2

    try:
        rows = _parse_results_file(results_path)
    except Exception as exc:
        print(f"[m46][P0] invalid results file: {exc}", file=sys.stderr)
        return 2

    try:
        waivers = _load_waivers(exceptions_path)
    except Exception as exc:
        print(f"[m46][P0] invalid exceptions file: {exc}", file=sys.stderr)
        return 2

    scenario_results: List[Dict[str, Any]] = []
    score_deltas: List[float] = []
    dist_deltas: List[float] = []
    pass_count = 0
    fail_count = 0
    waived_count = 0
    new_flags_total = 0
    failures: List[str] = []
    waivers_used: List[Dict[str, Any]] = []

    for name, candidate_p, drift_p, patch_p in rows:
        for p in (candidate_p, drift_p, patch_p):
            if not p.exists():
                print(f"[m46][P0] scenario={name} missing artifact: {p}", file=sys.stderr)
                return 2

        try:
            candidate = _load_json(candidate_p)
            drift = _load_json(drift_p)
            patch = _load_json(patch_p)
        except Exception as exc:
            print(f"[m46][P0] scenario={name} json parse failed: {exc}", file=sys.stderr)
            return 2

        drift_status = str(drift.get("status", "")).strip().lower()
        if drift_status not in {"pass", "fail"}:
            print(f"[m46][P1] scenario={name} invalid drift status: {drift_status!r}", file=sys.stderr)
            return 3

        waiver = waivers.get(name)
        waiver_active = bool(waiver and waiver.get("active") is True)
        waiver_reason = str(waiver.get("reason", "")).strip() if waiver else ""
        waiver_expires = str(waiver.get("expires_at", "")).strip() if waiver else ""

        if drift_status == "pass":
            status = "pass"
        elif waiver_active:
            status = "waived"
            waivers_used.append(
                {
                    "name": name,
                    "reason": waiver_reason,
                    "expires_at": waiver_expires,
                }
            )
        else:
            status = "fail"

        if status == "pass":
            pass_count += 1
        elif status == "waived":
            waived_count += 1
        else:
            fail_count += 1
            failures.append(name)

        score_delta = _to_float(_load_json(drift_p).get("deltas", {}).get("capability_score_total_avg"), 0.0)
        dist_delta = _to_float(_load_json(drift_p).get("deltas", {}).get("distance_to_target_avg"), 0.0)
        score_deltas.append(score_delta)
        dist_deltas.append(dist_delta)

        new_flags = drift.get("deltas", {}).get("new_regression_drift_flags")
        new_flags_count = len(new_flags) if isinstance(new_flags, list) else 0
        new_flags_total += new_flags_count

        violations = drift.get("violations")
        violations_count = len(violations) if isinstance(violations, list) else 0

        scenario_results.append(
            {
                "name": name,
                "status": status,
                "drift_status": drift_status,
                "waived": status == "waived",
                "waiver_reason": waiver_reason if status == "waived" else "",
                "waiver_expires_at": waiver_expires if status == "waived" else "",
                "candidate_report": str(candidate_p),
                "drift_report": str(drift_p),
                "patch_report": str(patch_p),
                "candidate_score_total_avg": _round3(_to_float(candidate.get("capability_score_total_avg"), 0.0)),
                "candidate_distance_to_target_avg": _round3(_to_float(candidate.get("distance_to_target_avg"), 0.0)),
                "score_delta": _round3(score_delta),
                "distance_delta": _round3(dist_delta),
                "new_drift_flags_count": int(new_flags_count),
                "drift_violations_count": int(violations_count),
                "drift_severity": str(drift.get("severity", "none")).strip().lower() or "none",
                "patch_status": str(patch.get("status", "")).strip().lower() or "unknown",
            }
        )

    report_status = "pass" if fail_count == 0 else "fail"
    report = {
        "schema_version": 1,
        "status": report_status,
        "generated_at_utc": dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "results_file": str(results_path),
        "exceptions_file": str(exceptions_path),
        "scenario_count": len(scenario_results),
        "pass_count": int(pass_count),
        "fail_count": int(fail_count),
        "waived_count": int(waived_count),
        "scenario_results": scenario_results,
        "score_delta_summary": _summary(score_deltas),
        "distance_delta_summary": _summary(dist_deltas),
        "new_drift_flags_total": int(new_flags_total),
        "failures": sorted(failures),
        "waivers": sorted(waivers_used, key=lambda x: str(x.get("name", ""))),
    }

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"[m46][P0] write report failed: {exc}", file=sys.stderr)
        return 2

    prefix = f"[m46:{args.label}] " if args.label else "[m46] "
    print(
        f"{prefix}status={report_status} scenarios={len(scenario_results)} "
        f"pass={pass_count} waived={waived_count} fail={fail_count}"
    )
    print(
        f"{prefix}score_delta[min/max/avg]={report['score_delta_summary']['min']}/"
        f"{report['score_delta_summary']['max']}/{report['score_delta_summary']['avg']}"
    )
    print(f"{prefix}report={out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
