#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

SWEEP_SUMMARY_CONTRACT_VERSION = "v2"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_artifact_provenance(*, analysis_dir: Path, analysis_path: Path, analysis: Dict[str, Any]) -> Dict[str, Any]:
    artifacts = analysis.get("artifacts") if isinstance(analysis.get("artifacts"), dict) else {}
    all_runs_csv_path = _resolve_path(analysis_dir, (artifacts or {}).get("layer_stack_validation_all_runs_csv"))
    source_analysis_provenance = (
        dict(analysis.get("artifact_provenance") or {})
        if isinstance(analysis.get("artifact_provenance"), dict)
        else {}
    )
    return {
        "tool": "sst_dram_si.tools.summarize_thermal_analysis",
        "artifact_kind": "thermal_sweep_summary",
        "contract_version": SWEEP_SUMMARY_CONTRACT_VERSION,
        "generated_at_utc": _utc_now_iso(),
        "source_kind": "analysis_dir",
        "analysis_dir": str(analysis_dir.resolve()),
        "source_analysis_contract_version": str(analysis.get("analysis_contract_version") or ""),
        "source_analysis_generated_at_utc": str(source_analysis_provenance.get("generated_at_utc") or ""),
        "source_paths": {
            "thermal_analysis_json": str(analysis_path.resolve()),
            "layer_stack_validation_all_runs_csv": str(all_runs_csv_path.resolve()) if all_runs_csv_path is not None else "",
        },
    }


def _load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _load_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve_path(base_dir: Path, raw_path: Any) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _as_int(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(str(raw).strip())
    except Exception:
        return None


def _as_bool(raw: Any) -> bool | None:
    if raw is None or raw == "":
        return None
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _split_reasons(raw: Any) -> List[str]:
    if isinstance(raw, list):
        values = [str(item or "").strip() for item in raw]
    else:
        values = [part.strip() for part in str(raw or "").split(",")]
    return sorted({value for value in values if value})


def _run_meta_map(analysis: Dict[str, Any]) -> Dict[tuple[str, str, str], Dict[str, Any]]:
    out: Dict[tuple[str, str, str], Dict[str, Any]] = {}
    for run in analysis.get("runs") if isinstance(analysis.get("runs"), list) else []:
        if not isinstance(run, dict):
            continue
        key = (
            str(run.get("run_dir") or ""),
            str(run.get("run_group") or ""),
            str(run.get("run_label") or ""),
        )
        trace_sources = run.get("window_power_trace_sources") if isinstance(run.get("window_power_trace_sources"), list) else []
        out[key] = {
            "hotspot_model_type": str(run.get("hotspot_model_type") or ""),
            "window_power_sample_count": _as_int(run.get("window_power_sample_count")),
            "window_power_block_count": _as_int(run.get("window_power_block_count")),
            "window_power_trace_sources": [str(item).strip() for item in trace_sources if str(item).strip()],
        }
    return out


def _lookup_run_meta(
    run_meta_map: Dict[tuple[str, str, str], Dict[str, Any]],
    *,
    run_dir: str,
    run_group: str,
    run_label: str,
) -> Dict[str, Any]:
    for key in (
        (run_dir, run_group, run_label),
        ("", run_group, run_label),
        ("", run_group, ""),
    ):
        value = run_meta_map.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _normalize_csv_rows(rows: List[Dict[str, str]], *, run_meta_map: Dict[tuple[str, str, str], Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        run_dir = str(row.get("run_dir") or "")
        run_group = str(row.get("run_group") or "")
        run_label = str(row.get("run_label") or "")
        run_meta = _lookup_run_meta(
            run_meta_map,
            run_dir=run_dir,
            run_group=run_group,
            run_label=run_label,
        )
        row_trace_sources = _split_reasons(row.get("window_power_trace_sources"))
        meta_trace_sources = run_meta.get("window_power_trace_sources") if isinstance(run_meta.get("window_power_trace_sources"), list) else []
        out.append(
            {
                "run_dir": run_dir,
                "run_group": run_group,
                "run_label": run_label,
                "hotspot_model_type": str(run_meta.get("hotspot_model_type") or ""),
                "window_power_sample_count": (
                    _as_int(row.get("window_power_sample_count"))
                    if _as_int(row.get("window_power_sample_count")) is not None
                    else _as_int(run_meta.get("window_power_sample_count"))
                ),
                "window_power_block_count": (
                    _as_int(row.get("window_power_block_count"))
                    if _as_int(row.get("window_power_block_count")) is not None
                    else _as_int(run_meta.get("window_power_block_count"))
                ),
                "window_power_trace_sources": row_trace_sources or [str(item).strip() for item in meta_trace_sources if str(item).strip()],
                "has_validation": bool(_as_bool(row.get("has_validation"))),
                "status": str(row.get("status") or ""),
                "passed": _as_bool(row.get("passed")),
                "layer_count_checked": _as_int(row.get("layer_count_checked")),
                "mismatch_count": _as_int(row.get("mismatch_count")),
                "failed_layer_count": _as_int(row.get("failed_layer_count")),
                "mismatch_reasons": _split_reasons(row.get("mismatch_reasons")),
                "config_matches": _as_bool(row.get("config_matches")),
                "config_mismatch_reasons": _split_reasons(row.get("config_mismatch_reasons")),
            }
        )
    return out


def _reconstruct_rows_from_analysis(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for run in analysis.get("runs") if isinstance(analysis.get("runs"), list) else []:
        if not isinstance(run, dict):
            continue
        validation = run.get("layer_stack_validation")
        has_validation = isinstance(validation, dict) and bool(validation)
        validation_dict = validation if isinstance(validation, dict) else {}
        out.append(
            {
                "run_dir": str(run.get("run_dir") or ""),
                "run_group": str(run.get("run_group") or ""),
                "run_label": str(run.get("run_label") or ""),
                "hotspot_model_type": str(run.get("hotspot_model_type") or ""),
                "window_power_sample_count": _as_int(run.get("window_power_sample_count")),
                "window_power_block_count": _as_int(run.get("window_power_block_count")),
                "window_power_trace_sources": _split_reasons(run.get("window_power_trace_sources")),
                "has_validation": has_validation,
                "status": str(validation_dict.get("status") or ""),
                "passed": validation_dict.get("passed") if isinstance(validation_dict.get("passed"), bool) else None,
                "layer_count_checked": _as_int(validation_dict.get("layer_count_checked")),
                "mismatch_count": _as_int(validation_dict.get("mismatch_count")),
                "failed_layer_count": _as_int(validation_dict.get("failed_layer_count")),
                "mismatch_reasons": _split_reasons(validation_dict.get("mismatch_reasons")),
                "config_matches": (
                    validation_dict.get("config_matches")
                    if isinstance(validation_dict.get("config_matches"), bool)
                    else None
                ),
                "config_mismatch_reasons": _split_reasons(validation_dict.get("config_mismatch_reasons")),
            }
        )
    return out


def _load_all_runs_rows(analysis_dir: Path, analysis: Dict[str, Any]) -> tuple[str, List[Dict[str, Any]]]:
    artifacts = analysis.get("artifacts") if isinstance(analysis.get("artifacts"), dict) else {}
    run_meta_map = _run_meta_map(analysis)
    csv_path = _resolve_path(analysis_dir, (artifacts or {}).get("layer_stack_validation_all_runs_csv"))
    if csv_path is not None and csv_path.is_file():
        return "layer_stack_validation_all_runs_csv", _normalize_csv_rows(_load_csv(csv_path), run_meta_map=run_meta_map)
    return "reconstructed_from_thermal_analysis_runs", _reconstruct_rows_from_analysis(analysis)


def _hotspot_model_type_counts(analysis: Dict[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for run in analysis.get("runs") if isinstance(analysis.get("runs"), list) else []:
        if not isinstance(run, dict):
            continue
        model_type = str(run.get("hotspot_model_type") or "").strip()
        if not model_type:
            continue
        counts[model_type] = counts.get(model_type, 0) + 1
    return dict(sorted(counts.items()))


def _summarize_validation_rows(source: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    rows_sorted = sorted(
        rows,
        key=lambda row: (
            str(row.get("run_group") or ""),
            str(row.get("run_label") or ""),
            str(row.get("run_dir") or ""),
        ),
    )
    with_validation = [row for row in rows_sorted if bool(row.get("has_validation"))]
    without_validation = [row for row in rows_sorted if not bool(row.get("has_validation"))]
    return {
        "source": source,
        "total_rows": len(rows_sorted),
        "with_validation_count": len(with_validation),
        "without_validation_count": len(without_validation),
        "passed_count": sum(1 for row in with_validation if row.get("passed") is True),
        "failed_count": sum(1 for row in with_validation if row.get("passed") is False),
        "unknown_count": sum(1 for row in with_validation if row.get("passed") is None),
        "config_matched_count": sum(1 for row in with_validation if row.get("config_matches") is True),
        "config_mismatched_count": sum(1 for row in with_validation if row.get("config_matches") is False),
        "run_groups_with_validation": [str(row.get("run_group") or "") for row in with_validation],
        "run_groups_without_validation": [str(row.get("run_group") or "") for row in without_validation],
    }


def _window_power_trace_source_counts(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for row in rows:
        trace_sources = row.get("window_power_trace_sources") if isinstance(row.get("window_power_trace_sources"), list) else []
        for trace_source in sorted({str(item).strip() for item in trace_sources if str(item).strip()}):
            counts[trace_source] = counts.get(trace_source, 0) + 1
    return dict(sorted(counts.items()))


def summarize_analysis_dir(analysis_dir: Path) -> Dict[str, Any]:
    analysis_path = analysis_dir / "thermal_analysis.json"
    if not analysis_path.is_file():
        raise FileNotFoundError(f"missing thermal_analysis.json: {analysis_path}")
    analysis = _load_json(analysis_path)
    source, rows = _load_all_runs_rows(analysis_dir, analysis)
    rows_sorted = sorted(
        rows,
        key=lambda row: (
            str(row.get("run_group") or ""),
            str(row.get("run_label") or ""),
            str(row.get("run_dir") or ""),
        ),
    )
    return {
        "sweep_summary_contract_version": SWEEP_SUMMARY_CONTRACT_VERSION,
        "artifact_provenance": _build_artifact_provenance(
            analysis_dir=analysis_dir,
            analysis_path=analysis_path,
            analysis=analysis,
        ),
        "analysis_dir": str(analysis_dir.resolve()),
        "run_count": int(_as_int(analysis.get("run_count")) or len(rows_sorted)),
        "hotspot_model_type_counts": _hotspot_model_type_counts(analysis),
        "window_power_trace_source_counts": _window_power_trace_source_counts(rows_sorted),
        "layer_stack_validation_overview": _summarize_validation_rows(source, rows_sorted),
        "layer_stack_validation_all_runs": rows_sorted,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarize reusable thermal analysis artifacts for higher-level sweep/report scripts.")
    ap.add_argument("--analysis-dir", required=True, help="directory containing thermal_analysis.json and exported thermal CSVs")
    ap.add_argument("--out-json", default="", help="optional path to write the summary JSON")
    args = ap.parse_args()

    analysis_dir = Path(args.analysis_dir).resolve()
    payload = summarize_analysis_dir(analysis_dir)
    if str(args.out_json or "").strip():
        _write_json(Path(args.out_json).resolve(), payload)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
