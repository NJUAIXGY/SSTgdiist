#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
TOOLS_DIR = SCRIPT_PATH.parent
PROJECT_ROOT = TOOLS_DIR.parent
DEFAULT_MATRIX_ROOT = PROJECT_ROOT / "outputs_large" / "paper2" / "dram_mesh_4x4_exec_mode_compare" / "matrix"
DEFAULT_REFERENCES_ROOT = PROJECT_ROOT / "references"

REQUIRED_CASES = {
    "gas": {
        "requested_exec_mode": "gas",
        "effective_exec_mode": "gas",
    },
    "naive_raw": {
        "requested_exec_mode": "naive_raw",
        "effective_exec_mode": "naive_raw",
    },
    "naive_opt": {
        "requested_exec_mode": "naive_opt",
        "effective_exec_mode": "naive_raw",
    },
}

ARTIFACT_ROLE_STABLE_REPORT = "stable_compare_sidecar_report"
ARTIFACT_ROLE_HISTORY = "stable_compare_history"
HISTORY_CONTRACT = "dated_compare_matrix_v1"
FRESHNESS_MODE = "latest_only"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _parse_iso_utc(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _boolish(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    if isinstance(value, str):
        raw = value.strip().lower()
        if raw in ("1", "true", "yes", "y", "on"):
            return True
        if raw in ("0", "false", "no", "n", "off"):
            return False
    return None


def _find_latest_matrix_summary(matrix_root: Path) -> Path:
    candidates = sorted(matrix_root.glob("*/summary.json"))
    if not candidates:
        raise FileNotFoundError(f"no compare matrix summary found under {matrix_root}")
    return candidates[-1].resolve()


def _run_matrix_and_resolve_summary() -> Path:
    script = TOOLS_DIR / "run_mesh_compare_smoke_matrix.sh"
    proc = subprocess.run(
        ["bash", str(script)],
        text=True,
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    if proc.returncode != 0:
        raise RuntimeError(f"compare smoke matrix failed:\n{combined}")
    run_dir = None
    for line in combined.splitlines():
        marker = "[mesh-compare-matrix] run complete:"
        if marker not in line:
            continue
        run_dir = Path(line.split("run complete:", 1)[1].strip()).resolve()
    if run_dir is None:
        raise RuntimeError(f"unable to parse compare matrix run dir:\n{combined}")
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"matrix summary missing: {summary_path}")
    return summary_path


def _normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    label = str(case.get("label") or "").strip()
    validator = case.get("validator") if isinstance(case.get("validator"), dict) else {}
    memory = case.get("memory") if isinstance(case.get("memory"), dict) else {}
    normalized = {
        "label": label,
        "run_dir": str(case.get("run_dir") or ""),
        "requested_exec_mode": str(case.get("requested_exec_mode") or ""),
        "effective_exec_mode": str(case.get("effective_exec_mode") or ""),
        "compare_role": str(case.get("compare_role") or ""),
        "bounded_validation": bool(_boolish(case.get("bounded_validation"))),
        "validator": {
            "fail": int(validator.get("fail") or 0),
            "warn": int(validator.get("warn") or 0),
            "strict": int(validator.get("strict") or 0),
        },
        "memory": {
            "memory_requests": memory.get("memory_requests"),
            "memory_bytes": memory.get("memory_bytes"),
            "nonzero": bool(_boolish(memory.get("nonzero"))),
        },
    }
    expected = REQUIRED_CASES.get(label)
    reasons: list[str] = []
    if expected is None:
        reasons.append("unexpected_case_label")
    else:
        if normalized["requested_exec_mode"] != expected["requested_exec_mode"]:
            reasons.append("requested_exec_mode_mismatch")
        if normalized["effective_exec_mode"] != expected["effective_exec_mode"]:
            reasons.append("effective_exec_mode_mismatch")
    if normalized["compare_role"] != "smoke":
        reasons.append("compare_role_not_smoke")
    if not normalized["bounded_validation"]:
        reasons.append("bounded_validation_not_true")
    if normalized["validator"]["fail"] != 0:
        reasons.append("validator_fail_nonzero")
    if not normalized["memory"]["nonzero"]:
        reasons.append("memory_nonzero_false")
    normalized["gate_ok"] = not reasons
    normalized["gate_reasons"] = reasons
    return normalized


def _build_freshness(summary: dict[str, Any], *, now_utc: dt.datetime, stale_after_hours: float) -> dict[str, Any]:
    generated_utc = _parse_iso_utc(str(summary.get("created_utc") or "")) or now_utc
    age_hours = max(0.0, (now_utc - generated_utc).total_seconds() / 3600.0)
    stale = age_hours > float(stale_after_hours)
    return {
        "freshness_mode": FRESHNESS_MODE,
        "latest_generated_utc": generated_utc.isoformat(),
        "latest_date": generated_utc.date().isoformat(),
        "stale_after_hours": float(stale_after_hours),
        "latest_age_hours": round(age_hours, 6),
        "stale": stale,
    }


def _build_history(
    existing_history: dict[str, Any] | None,
    *,
    summary_path: Path,
    matrix_summary: dict[str, Any],
    freshness: dict[str, Any],
    latest_all_green: bool,
    cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    entries = list((existing_history or {}).get("entries") or [])
    current_entry = {
        "matrix_run_id": str(matrix_summary.get("matrix_run_id") or summary_path.parent.name),
        "date": str(freshness.get("latest_date") or ""),
        "generated_utc": str(freshness.get("latest_generated_utc") or ""),
        "summary_path": str(summary_path),
        "all_green": bool(latest_all_green),
        "stale": bool(freshness.get("stale")),
        "cases": {
            label: {
                "gate_ok": bool(case.get("gate_ok")),
                "requested_exec_mode": case.get("requested_exec_mode"),
                "effective_exec_mode": case.get("effective_exec_mode"),
                "validator_fail": case.get("validator", {}).get("fail"),
                "memory_nonzero": case.get("memory", {}).get("nonzero"),
            }
            for label, case in sorted(cases.items())
        },
    }
    filtered = [entry for entry in entries if str(entry.get("summary_path") or "") != str(summary_path)]
    filtered.append(current_entry)
    filtered.sort(
        key=lambda entry: (
            str(entry.get("date") or ""),
            str(entry.get("generated_utc") or ""),
            str(entry.get("summary_path") or ""),
        ),
        reverse=True,
    )
    return {
        "artifact_role": ARTIFACT_ROLE_HISTORY,
        "authority_scope": "dated_compare_smoke_rollup",
        "history_contract": HISTORY_CONTRACT,
        "freshness_mode": FRESHNESS_MODE,
        "entry_count": len(filtered),
        "latest_date": current_entry["date"],
        "latest_generated_utc": current_entry["generated_utc"],
        "latest_summary_path": current_entry["summary_path"],
        "latest_all_green": bool(current_entry["all_green"]),
        "all_green_history": all(bool(entry.get("all_green")) for entry in filtered),
        "entries": filtered,
    }


def _render_current_status(report: dict[str, Any], *, report_path: Path) -> str:
    freshness = report.get("freshness") or {}
    cases = report.get("cases") or {}
    lines = [
        "# mesh compare current mainline status",
        "",
        f"- Generated UTC: `{report.get('generated_utc')}`",
        "- Role: shared readable current-state surface derived from stable compare smoke references",
        "",
        "## Stable Surfaces",
        f"- stable top-level gate: `{report_path}`",
        f"- stable history path: `{report.get('history_path')}`",
        f"- stable summary markdown: `{report.get('summary_md_path')}`",
        f"- source matrix summary: `{report.get('source_matrix_summary_path')}`",
        "",
        "## Top-Level Gate",
        f"- `gate_ok = {bool(report.get('gate_ok'))}`",
        f"- `latest_all_green = {bool(report.get('latest_all_green'))}`",
        f"- `required_cases = {', '.join(report.get('required_cases') or [])}`",
        f"- `gate_reasons = {', '.join(report.get('gate_reasons') or ['none'])}`",
        "",
        "## Freshness",
        f"- `freshness_mode = {freshness.get('freshness_mode')}`",
        f"- `latest_date = {freshness.get('latest_date')}`",
        f"- `latest_generated_utc = {freshness.get('latest_generated_utc')}`",
        f"- `latest_age_hours = {freshness.get('latest_age_hours')}`",
        f"- `stale_after_hours = {freshness.get('stale_after_hours')}`",
        f"- `stale = {bool(freshness.get('stale'))}`",
        f"- `history_entry_count = {freshness.get('history_entry_count')}`",
        f"- `all_green_history = {bool(freshness.get('all_green_history'))}`",
        "",
        "## Cases",
    ]
    for label in sorted(cases):
        case = cases[label]
        lines.extend(
            [
                f"- `{label}.gate_ok = {bool(case.get('gate_ok'))}`",
                f"- `{label}.requested_exec_mode = {case.get('requested_exec_mode')}`",
                f"- `{label}.effective_exec_mode = {case.get('effective_exec_mode')}`",
                f"- `{label}.compare_role = {case.get('compare_role')}`",
                f"- `{label}.bounded_validation = {bool(case.get('bounded_validation'))}`",
                f"- `{label}.validator_fail = {case.get('validator', {}).get('fail')}`",
                f"- `{label}.memory_nonzero = {bool(case.get('memory', {}).get('nonzero'))}`",
                f"- `{label}.gate_reasons = {', '.join(case.get('gate_reasons') or ['none'])}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Refresh",
            "```bash",
            f"cd \"{PROJECT_ROOT}\"",
            f"python3 \"{TOOLS_DIR / 'refresh_mesh_compare_surfaces.py'}\" --run-matrix",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _render_summary_md(report: dict[str, Any], *, report_path: Path) -> str:
    freshness = report.get("freshness") or {}
    lines = [
        "# mesh compare sidecar summary",
        "",
        f"- Generated UTC: `{report.get('generated_utc')}`",
        f"- stable top-level gate: `{report_path}`",
        f"- current_mainline_status_path: `{report.get('current_mainline_status_path')}`",
        f"- history_path: `{report.get('history_path')}`",
        f"- source matrix summary: `{report.get('source_matrix_summary_path')}`",
        f"- `gate_ok = {bool(report.get('gate_ok'))}`",
        f"- `latest_all_green = {bool(report.get('latest_all_green'))}`",
        f"- `freshness_mode = {freshness.get('freshness_mode')}`",
        f"- `stale = {bool(freshness.get('stale'))}`",
        f"- `latest_date = {freshness.get('latest_date')}`",
        "",
    ]
    return "\n".join(lines)


def refresh_compare_surfaces(
    *,
    summary_path: Path | None,
    matrix_root: Path,
    report_path: Path,
    history_path: Path,
    current_mainline_status_path: Path,
    summary_md_path: Path,
    stale_after_hours: float,
    now_utc: dt.datetime,
    run_matrix: bool,
) -> dict[str, Any]:
    if run_matrix:
        resolved_summary_path = _run_matrix_and_resolve_summary()
    elif summary_path is not None:
        resolved_summary_path = summary_path.resolve()
    else:
        resolved_summary_path = _find_latest_matrix_summary(matrix_root.resolve())

    matrix_summary = _load_json(resolved_summary_path)
    cases_payload = matrix_summary.get("cases")
    if not isinstance(cases_payload, list):
        raise ValueError(f"matrix summary missing cases list: {resolved_summary_path}")

    cases = {
        normalized["label"]: normalized
        for normalized in (_normalize_case(case) for case in cases_payload if isinstance(case, dict))
        if normalized["label"]
    }
    missing_cases = [label for label in REQUIRED_CASES if label not in cases]
    latest_all_green = not missing_cases and all(bool(cases[label]["gate_ok"]) for label in REQUIRED_CASES)
    freshness = _build_freshness(matrix_summary, now_utc=now_utc, stale_after_hours=stale_after_hours)
    existing_history = _load_json(history_path) if history_path.exists() else None
    history = _build_history(
        existing_history,
        summary_path=resolved_summary_path,
        matrix_summary=matrix_summary,
        freshness=freshness,
        latest_all_green=latest_all_green,
        cases=cases,
    )
    freshness["history_entry_count"] = int(history.get("entry_count") or 0)
    freshness["all_green_history"] = bool(history.get("all_green_history"))

    gate_reasons: list[str] = []
    if missing_cases:
        gate_reasons.append("missing_required_cases")
    for label in REQUIRED_CASES:
        case = cases.get(label)
        if case and not case.get("gate_ok"):
            gate_reasons.append(f"{label}_not_green")
    if freshness["stale"]:
        gate_reasons.append("stale_latest_summary")

    generated_utc = now_utc.isoformat()
    report = {
        "schema_version": 1,
        "artifact_role": ARTIFACT_ROLE_STABLE_REPORT,
        "authority_scope": "compare_smoke_gate_authority",
        "producer": "refresh_mesh_compare_surfaces.py",
        "generated_utc": generated_utc,
        "summary_path": str(report_path),
        "source_matrix_summary_path": str(resolved_summary_path),
        "source_matrix_run_id": str(matrix_summary.get("matrix_run_id") or resolved_summary_path.parent.name),
        "required_cases": list(REQUIRED_CASES.keys()),
        "missing_cases": missing_cases,
        "latest_all_green": latest_all_green,
        "gate_ok": bool(latest_all_green and not freshness["stale"]),
        "gate_reasons": gate_reasons,
        "freshness": freshness,
        "history_path": str(history_path),
        "current_mainline_status_path": str(current_mainline_status_path),
        "summary_md_path": str(summary_md_path),
        "cases": cases,
        "stable_surface_refresh": {
            "refreshed_utc": generated_utc,
            "history_path": str(history_path),
            "current_mainline_status_path": str(current_mainline_status_path),
            "summary_md_path": str(summary_md_path),
        },
    }

    history["summary_path"] = str(history_path)
    history["generated_utc"] = generated_utc

    _write_json(history_path, history)
    _write_json(report_path, report)
    current_mainline_status_path.parent.mkdir(parents=True, exist_ok=True)
    current_mainline_status_path.write_text(
        _render_current_status(report, report_path=report_path),
        encoding="utf-8",
    )
    summary_md_path.parent.mkdir(parents=True, exist_ok=True)
    summary_md_path.write_text(
        _render_summary_md(report, report_path=report_path),
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="refresh_mesh_compare_surfaces.py",
        description="Refresh stable current-status/history surfaces for the mesh exec-mode compare smoke gate",
    )
    parser.add_argument("--summary", default="", help="Use an explicit compare matrix summary.json")
    parser.add_argument("--matrix-root", default=str(DEFAULT_MATRIX_ROOT), help="Matrix run root for auto-discovery")
    parser.add_argument("--report", default=str(DEFAULT_REFERENCES_ROOT / "mesh-compare-sidecar-report.json"))
    parser.add_argument("--history", default=str(DEFAULT_REFERENCES_ROOT / "mesh-compare-history.json"))
    parser.add_argument("--status", default=str(DEFAULT_REFERENCES_ROOT / "mesh-compare-current-mainline-status.md"))
    parser.add_argument("--summary-md", default=str(DEFAULT_REFERENCES_ROOT / "mesh-compare-sidecar-summary.md"))
    parser.add_argument("--stale-after-hours", type=float, default=48.0)
    parser.add_argument("--now-utc", default="", help="Override current UTC time for tests")
    parser.add_argument("--run-matrix", action="store_true", help="Run compare smoke matrix before refreshing surfaces")
    args = parser.parse_args(argv)

    now_utc = _parse_iso_utc(args.now_utc) or dt.datetime.now(dt.timezone.utc)
    report = refresh_compare_surfaces(
        summary_path=Path(args.summary) if args.summary else None,
        matrix_root=Path(args.matrix_root),
        report_path=Path(args.report),
        history_path=Path(args.history),
        current_mainline_status_path=Path(args.status),
        summary_md_path=Path(args.summary_md),
        stale_after_hours=float(args.stale_after_hours),
        now_utc=now_utc,
        run_matrix=bool(args.run_matrix),
    )
    print(report["summary_path"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
