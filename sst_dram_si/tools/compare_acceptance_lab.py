#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUTHORITY_PATH = PROJECT_ROOT / "spec_authority" / "compare_acceptance_gate_v1.json"


def _read_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def load_authority(authority_path: Path = DEFAULT_AUTHORITY_PATH) -> Dict[str, Any]:
    authority = _read_json(authority_path)
    if authority.get("schema_version") != 1:
        raise ValueError(f"unsupported compare acceptance authority schema: {authority_path}")
    return authority


def stable_path(*, project_root: Path, authority: Dict[str, Any], key: str) -> Path:
    paths = authority.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("authority.paths must be an object")
    raw = str(paths.get(key) or "").strip()
    if not raw:
        raise ValueError(f"missing authority path for {key}")
    return (project_root / raw).resolve()


def _parse_date_from_run_id(run_id: str) -> str | None:
    raw = str(run_id or "").strip()
    if len(raw) < 8 or not raw[:8].isdigit():
        return None
    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"


def _parse_bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(int(raw))
    if isinstance(raw, str):
        norm = raw.strip().lower()
        if norm in ("1", "true", "yes", "y", "on"):
            return True
        if norm in ("0", "false", "no", "n", "off"):
            return False
    return None


def _latest_recovery_start_date(entries_desc: List[Dict[str, Any]]) -> str | None:
    recovery_start = None
    saw_failure = False
    for entry in entries_desc:
        if bool(entry.get("all_ok")):
            recovery_start = str(entry.get("date") or "") or recovery_start
            continue
        saw_failure = True
        break
    if not saw_failure:
        return None
    return recovery_start


def _days_old(*, latest_date: str | None, now_utc: dt.datetime) -> int | None:
    if not latest_date:
        return None
    try:
        latest = dt.date.fromisoformat(latest_date)
    except ValueError:
        return None
    return (now_utc.date() - latest).days


def _case_ok(case: Dict[str, Any], contract: Dict[str, Any]) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    expected_role = str(contract.get("compare_role") or "").strip()
    if expected_role and str(case.get("compare_role") or "") != expected_role:
        reasons.append("compare_role_mismatch")
    expected_bounded = _parse_bool(contract.get("bounded_validation"))
    if expected_bounded is not None and _parse_bool(case.get("bounded_validation")) is not expected_bounded:
        reasons.append("bounded_validation_mismatch")
    fail_max = int(contract.get("validator_fail_max", 0) or 0)
    validator = case.get("validator")
    fail_count = None
    if isinstance(validator, dict):
        try:
            fail_count = int(validator.get("fail", 0) or 0)
        except Exception:
            fail_count = None
    if fail_count is None or fail_count > fail_max:
        reasons.append("validator_fail_nonzero")
    require_memory_nonzero = _parse_bool(contract.get("memory_nonzero_required"))
    if require_memory_nonzero is True:
        memory = case.get("memory")
        if not isinstance(memory, dict) or not bool(memory.get("nonzero")):
            reasons.append("memory_nonzero_missing")
    return not reasons, reasons


def _normalize_case(*, label: str, raw: Dict[str, Any] | None, contract: Dict[str, Any]) -> Dict[str, Any]:
    if raw is None:
        return {
            "label": label,
            "present": False,
            "ok": False,
            "reasons": ["missing_case"],
        }
    case = {
        "label": label,
        "present": True,
        "run_dir": raw.get("run_dir"),
        "requested_exec_mode": raw.get("requested_exec_mode"),
        "effective_exec_mode": raw.get("effective_exec_mode"),
        "compare_role": raw.get("compare_role"),
        "bounded_validation": _parse_bool(raw.get("bounded_validation")),
        "validator": raw.get("validator") if isinstance(raw.get("validator"), dict) else {},
        "memory": raw.get("memory") if isinstance(raw.get("memory"), dict) else {},
    }
    ok, reasons = _case_ok(case, contract)
    case["ok"] = ok
    case["reasons"] = reasons
    return case


def build_history(*,
                  project_root: Path = PROJECT_ROOT,
                  authority: Dict[str, Any] | None = None,
                  now_utc: dt.datetime | None = None) -> Dict[str, Any]:
    authority = authority or load_authority()
    now_utc = now_utc or _utc_now()
    matrix_root = stable_path(project_root=project_root, authority=authority, key="matrix_root")
    required_cases = [str(item) for item in authority.get("required_cases") or []]
    contract = authority.get("case_contract") if isinstance(authority.get("case_contract"), dict) else {}
    entries: List[Dict[str, Any]] = []
    if matrix_root.exists():
        for run_dir in sorted([p for p in matrix_root.iterdir() if p.is_dir()], reverse=True):
            summary_path = run_dir / "summary.json"
            if not summary_path.exists():
                continue
            summary = _read_json(summary_path)
            cases_raw = summary.get("cases")
            if not isinstance(cases_raw, list):
                continue
            case_map = {
                str(item.get("label") or ""): item
                for item in cases_raw
                if isinstance(item, dict) and str(item.get("label") or "").strip()
            }
            normalized_cases = [
                _normalize_case(label=label, raw=case_map.get(label), contract=contract)
                for label in required_cases
            ]
            missing_cases = [case["label"] for case in normalized_cases if not case.get("present")]
            failing_cases = [case["label"] for case in normalized_cases if not case.get("ok")]
            date_text = _parse_date_from_run_id(str(summary.get("matrix_run_id") or run_dir.name))
            entries.append(
                {
                    "date": date_text,
                    "matrix_run_id": str(summary.get("matrix_run_id") or run_dir.name),
                    "summary_path": str(summary_path.resolve()),
                    "all_ok": not failing_cases and not missing_cases,
                    "missing_cases": missing_cases,
                    "failing_cases": failing_cases,
                    "cases": normalized_cases,
                }
            )

    latest_date = entries[0]["date"] if entries else None
    all_dates_ok = all(bool(entry.get("all_ok")) for entry in entries) if entries else False
    latest_recovered_date = _latest_recovery_start_date(entries)
    freshness = authority.get("freshness") if isinstance(authority.get("freshness"), dict) else {}
    freshness_mode = str(freshness.get("multi_date_freshness_mode") or "all_dates")
    effective_entries = entries
    if freshness_mode == "since_latest_recovery" and latest_recovered_date:
        effective_entries = [
            entry for entry in entries if str(entry.get("date") or "") >= str(latest_recovered_date)
        ]
    effective_all_dates_ok = all(bool(entry.get("all_ok")) for entry in effective_entries) if effective_entries else False
    age_days = _days_old(latest_date=latest_date, now_utc=now_utc)
    max_age_days = int(freshness.get("max_age_days", 0) or 0)
    stale = age_days is None or age_days > max_age_days
    history = {
        "schema_version": 1,
        "artifact_role": "stable_history_rollup",
        "gate_name": str(authority.get("gate_name") or ""),
        "generated_utc": now_utc.isoformat(),
        "matrix_root": str(matrix_root),
        "entry_count": len(entries),
        "required_cases": required_cases,
        "latest_date": latest_date,
        "all_dates_ok": all_dates_ok,
        "latest_recovered_date": latest_recovered_date,
        "freshness_mode": freshness_mode,
        "effective_entry_count": len(effective_entries),
        "effective_all_dates_ok": effective_all_dates_ok,
        "max_age_days": max_age_days,
        "latest_age_days": age_days,
        "stale": stale,
        "entries": entries,
    }
    return history


def build_report(*,
                 project_root: Path = PROJECT_ROOT,
                 authority: Dict[str, Any] | None = None,
                 history: Dict[str, Any] | None = None,
                 now_utc: dt.datetime | None = None) -> Dict[str, Any]:
    authority = authority or load_authority()
    now_utc = now_utc or _utc_now()
    history = history or build_history(project_root=project_root, authority=authority, now_utc=now_utc)
    latest_entry = history["entries"][0] if history.get("entries") else None
    required_cases = [str(item) for item in authority.get("required_cases") or []]
    latest_case_rollups = {}
    if isinstance(latest_entry, dict):
        for case in latest_entry.get("cases") or []:
            if isinstance(case, dict):
                latest_case_rollups[str(case.get("label") or "")] = case
    missing_cases = [label for label in required_cases if label not in latest_case_rollups]
    gate_reasons: List[str] = []
    if not latest_entry:
        gate_reasons.append("missing_history")
    elif missing_cases:
        gate_reasons.append("missing_required_cases")
    if history.get("stale"):
        gate_reasons.append("stale_latest_matrix")
    if latest_entry and not bool(latest_entry.get("all_ok")):
        gate_reasons.append("latest_matrix_failed")
    if not bool(history.get("effective_all_dates_ok")):
        gate_reasons.append("freshness_window_not_all_ok")

    report = {
        "schema_version": 1,
        "artifact_role": str(authority.get("artifact_role") or "stable_top_level_gate"),
        "authority_scope": str(authority.get("authority_scope") or "experimental_gate_authority"),
        "gate_name": str(authority.get("gate_name") or ""),
        "gate_version": str(authority.get("gate_version") or ""),
        "generated_utc": now_utc.isoformat(),
        "required_cases": required_cases,
        "missing_cases": missing_cases,
        "gate_ok": not gate_reasons,
        "gate_reasons": gate_reasons,
        "latest_matrix": {
            "date": latest_entry.get("date") if isinstance(latest_entry, dict) else None,
            "matrix_run_id": latest_entry.get("matrix_run_id") if isinstance(latest_entry, dict) else None,
            "summary_path": latest_entry.get("summary_path") if isinstance(latest_entry, dict) else None,
            "all_ok": bool(latest_entry.get("all_ok")) if isinstance(latest_entry, dict) else False,
        },
        "history": {
            "path": str(stable_path(project_root=project_root, authority=authority, key="history_path")),
            "entry_count": int(history.get("entry_count", 0) or 0),
            "latest_date": history.get("latest_date"),
            "all_dates_ok": bool(history.get("all_dates_ok")),
            "latest_recovered_date": history.get("latest_recovered_date"),
            "freshness_mode": history.get("freshness_mode"),
            "effective_entry_count": int(history.get("effective_entry_count", 0) or 0),
            "effective_all_dates_ok": bool(history.get("effective_all_dates_ok")),
            "max_age_days": int(history.get("max_age_days", 0) or 0),
            "latest_age_days": history.get("latest_age_days"),
            "stale": bool(history.get("stale")),
        },
        "stable_surfaces": {
            "report_path": str(stable_path(project_root=project_root, authority=authority, key="report_path")),
            "observer_summary_path": str(stable_path(project_root=project_root, authority=authority, key="observer_summary_path")),
            "summary_md_path": str(stable_path(project_root=project_root, authority=authority, key="summary_md_path")),
            "current_mainline_status_path": str(stable_path(project_root=project_root, authority=authority, key="current_mainline_status_path")),
        },
        "latest_case_rollups": latest_case_rollups,
    }
    return report


def build_observer_summary(*,
                           project_root: Path = PROJECT_ROOT,
                           authority: Dict[str, Any] | None = None,
                           report: Dict[str, Any] | None = None,
                           history: Dict[str, Any] | None = None,
                           now_utc: dt.datetime | None = None) -> Dict[str, Any]:
    authority = authority or load_authority()
    now_utc = now_utc or _utc_now()
    history = history or build_history(project_root=project_root, authority=authority, now_utc=now_utc)
    report = report or build_report(project_root=project_root, authority=authority, history=history, now_utc=now_utc)
    return {
        "schema_version": 1,
        "artifact_role": "stable_sidecar_observer_summary",
        "authority_entrypoint": {
            "artifact_role": str(authority.get("artifact_role") or "stable_top_level_gate"),
            "authority_scope": str(authority.get("authority_scope") or "experimental_gate_authority"),
            "summary_path": report["stable_surfaces"]["report_path"],
            "policy": "read_compare_report_then_follow_current_status",
        },
        "gate_name": str(authority.get("gate_name") or ""),
        "gate_ok": bool(report.get("gate_ok")),
        "generated_utc": now_utc.isoformat(),
        "latest_history_date": history.get("latest_date"),
        "required_cases": report.get("required_cases"),
        "case_rollups": report.get("latest_case_rollups"),
        "history_rollup": report.get("history"),
        "summary_path": str(stable_path(project_root=project_root, authority=authority, key="observer_summary_path")),
    }


def _fmt(raw: Any) -> str:
    if raw is None:
        return "none"
    return str(raw)


def build_summary_markdown(*,
                           project_root: Path = PROJECT_ROOT,
                           authority: Dict[str, Any] | None = None,
                           report: Dict[str, Any] | None = None,
                           observer_summary: Dict[str, Any] | None = None,
                           now_utc: dt.datetime | None = None) -> str:
    authority = authority or load_authority()
    now_utc = now_utc or _utc_now()
    report = report or build_report(project_root=project_root, authority=authority, now_utc=now_utc)
    observer_summary = observer_summary or build_observer_summary(
        project_root=project_root,
        authority=authority,
        report=report,
        now_utc=now_utc,
    )
    lines = [
        "# compare experimental nightly sidecar",
        "",
        f"- Generated UTC: `{now_utc.isoformat()}`",
        f"- Gate: `{'PASS' if report.get('gate_ok') else 'FAIL'}`",
        f"- Gate name: `{authority.get('gate_name')}`",
        f"- Gate version: `{authority.get('gate_version')}`",
        f"- Artifact role: `{authority.get('artifact_role')}`",
        f"- Authority scope: `{authority.get('authority_scope')}`",
        f"- Latest nightly date: `{_fmt(report.get('history', {}).get('latest_date'))}`",
        f"- Required cases ({len(report.get('required_cases') or [])}): `{', '.join(report.get('required_cases') or [])}`",
        f"- Missing cases: `{', '.join(report.get('missing_cases') or []) or 'none'}`",
        "",
        "## Authority",
        "",
        f"- stable top-level gate: `{report['stable_surfaces']['report_path']}`",
        f"- stable observer summary: `{report['stable_surfaces']['observer_summary_path']}`",
        f"- shared current-state rollup: `{report['stable_surfaces']['current_mainline_status_path']}`",
        f"- current_mainline_status_path: `{report['stable_surfaces']['current_mainline_status_path']}`",
        f"- stable surface refresh UTC: `{now_utc.isoformat()}`",
        f"- dated history authority: `{report['history']['path']}`",
        "",
        "## Freshness",
        "",
        f"- `latest_date = {_fmt(report['history'].get('latest_date'))}`",
        f"- `stale = {_fmt(report['history'].get('stale'))}`",
        f"- `latest_age_days = {_fmt(report['history'].get('latest_age_days'))}`",
        f"- `max_age_days = {_fmt(report['history'].get('max_age_days'))}`",
        f"- `all_dates_ok = {_fmt(report['history'].get('all_dates_ok'))}`",
        f"- `latest_recovered_date = {_fmt(report['history'].get('latest_recovered_date'))}`",
        f"- `freshness_mode = {_fmt(report['history'].get('freshness_mode'))}`",
        f"- `effective_all_dates_ok = {_fmt(report['history'].get('effective_all_dates_ok'))}`",
        "",
        "## Cases",
        "",
        "| case | requested | effective | role | bounded | fail | warn | strict | memory.nonzero | ok |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for label in report.get("required_cases") or []:
        case = report.get("latest_case_rollups", {}).get(label) or {}
        validator = case.get("validator") if isinstance(case.get("validator"), dict) else {}
        memory = case.get("memory") if isinstance(case.get("memory"), dict) else {}
        lines.append(
            "| "
            + " | ".join(
                [
                    label,
                    _fmt(case.get("requested_exec_mode")),
                    _fmt(case.get("effective_exec_mode")),
                    _fmt(case.get("compare_role")),
                    _fmt(case.get("bounded_validation")),
                    _fmt(validator.get("fail")),
                    _fmt(validator.get("warn")),
                    _fmt(validator.get("strict")),
                    _fmt(memory.get("nonzero")),
                    _fmt(case.get("ok")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Reasons",
            "",
            f"- `{', '.join(report.get('gate_reasons') or []) or 'none'}`",
            "",
        ]
    )
    return "\n".join(lines)


def build_current_status_markdown(*,
                                  project_root: Path = PROJECT_ROOT,
                                  authority: Dict[str, Any] | None = None,
                                  report: Dict[str, Any] | None = None,
                                  observer_summary: Dict[str, Any] | None = None,
                                  now_utc: dt.datetime | None = None) -> str:
    authority = authority or load_authority()
    now_utc = now_utc or _utc_now()
    report = report or build_report(project_root=project_root, authority=authority, now_utc=now_utc)
    observer_summary = observer_summary or build_observer_summary(
        project_root=project_root,
        authority=authority,
        report=report,
        now_utc=now_utc,
    )
    lines = [
        "# compare current mainline status",
        "",
        f"- Generated UTC: `{now_utc.isoformat()}`",
        "- Role: shared readable current-state surface derived from stable compare references",
        "",
        "## Stable Surfaces",
        f"- stable top-level gate: `{report['stable_surfaces']['report_path']}`",
        f"- stable observer summary: `{report['stable_surfaces']['observer_summary_path']}`",
        f"- stable nightly summary: `{report['stable_surfaces']['summary_md_path']}`",
        f"- stable current mainline: `{report['stable_surfaces']['current_mainline_status_path']}`",
        f"- latest history date: `{_fmt(observer_summary.get('latest_history_date'))}`",
        "",
        "## Top-Level Gate",
        f"- `gate_ok = {_fmt(report.get('gate_ok'))}`",
        f"- `required_cases = {', '.join(report.get('required_cases') or [])}`",
        f"- `gate_reasons = {', '.join(report.get('gate_reasons') or []) or 'none'}`",
        "",
        "## Freshness",
        f"- `latest_date = {_fmt(report['history'].get('latest_date'))}`",
        f"- `stale = {_fmt(report['history'].get('stale'))}`",
        f"- `freshness_mode = {_fmt(report['history'].get('freshness_mode'))}`",
        f"- `effective_all_dates_ok = {_fmt(report['history'].get('effective_all_dates_ok'))}`",
        "",
        "## Latest Cases",
    ]
    for label in report.get("required_cases") or []:
        case = report.get("latest_case_rollups", {}).get(label) or {}
        lines.extend(
            [
                f"- `{label}.requested_exec_mode = {_fmt(case.get('requested_exec_mode'))}`",
                f"- `{label}.effective_exec_mode = {_fmt(case.get('effective_exec_mode'))}`",
                f"- `{label}.compare_role = {_fmt(case.get('compare_role'))}`",
                f"- `{label}.bounded_validation = {_fmt(case.get('bounded_validation'))}`",
                f"- `{label}.ok = {_fmt(case.get('ok'))}`",
            ]
        )
    return "\n".join(lines) + "\n"


def refresh(*,
            project_root: Path = PROJECT_ROOT,
            authority_path: Path = DEFAULT_AUTHORITY_PATH,
            now_utc: dt.datetime | None = None) -> Dict[str, Any]:
    now_utc = now_utc or _utc_now()
    authority = load_authority(authority_path)
    history = build_history(project_root=project_root, authority=authority, now_utc=now_utc)
    report = build_report(project_root=project_root, authority=authority, history=history, now_utc=now_utc)
    observer_summary = build_observer_summary(
        project_root=project_root,
        authority=authority,
        report=report,
        history=history,
        now_utc=now_utc,
    )
    summary_md = build_summary_markdown(
        project_root=project_root,
        authority=authority,
        report=report,
        observer_summary=observer_summary,
        now_utc=now_utc,
    )
    current_status_md = build_current_status_markdown(
        project_root=project_root,
        authority=authority,
        report=report,
        observer_summary=observer_summary,
        now_utc=now_utc,
    )

    history_path = stable_path(project_root=project_root, authority=authority, key="history_path")
    report_path = stable_path(project_root=project_root, authority=authority, key="report_path")
    observer_path = stable_path(project_root=project_root, authority=authority, key="observer_summary_path")
    summary_md_path = stable_path(project_root=project_root, authority=authority, key="summary_md_path")
    current_status_path = stable_path(project_root=project_root, authority=authority, key="current_mainline_status_path")

    _write_json(history_path, history)
    _write_json(report_path, report)
    _write_json(observer_path, observer_summary)
    _write_text(summary_md_path, summary_md)
    _write_text(current_status_path, current_status_md)

    return {
        "history_path": str(history_path),
        "report_path": str(report_path),
        "observer_summary_path": str(observer_path),
        "summary_md_path": str(summary_md_path),
        "current_mainline_status_path": str(current_status_path),
        "gate_ok": bool(report.get("gate_ok")),
    }


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build compare-family current status / nightly / freshness surfaces from smoke matrix outputs.")
    sub = ap.add_subparsers(dest="command", required=True)

    refresh_ap = sub.add_parser("refresh", help="refresh stable compare status surfaces")
    refresh_ap.add_argument("--project-root", default=str(PROJECT_ROOT), help="sst_dram_si project root")
    refresh_ap.add_argument("--authority", default=str(DEFAULT_AUTHORITY_PATH), help="compare acceptance authority JSON")

    args = ap.parse_args(argv)
    if args.command == "refresh":
        payload = refresh(project_root=Path(args.project_root).resolve(), authority_path=Path(args.authority).resolve())
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
