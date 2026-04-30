#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

ANALYSIS_CONTRACT_VERSION = "v2"

THERMAL_SUMMARY_REL = Path("thermal/summary/thermal_summary.json")
TILE_SUMMARY_REL = Path("thermal/summary/tile_temperature_summary.csv")
WINDOW_POWER_SAMPLES_REL = Path("thermal/summary/window_power_samples.jsonl")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_artifact_provenance(*, out_dir: Path, run_dirs: List[Path]) -> Dict[str, Any]:
    return {
        "tool": "sst_dram_si.tools.analyze_thermal_runs",
        "artifact_kind": "thermal_analysis",
        "contract_version": ANALYSIS_CONTRACT_VERSION,
        "generated_at_utc": _utc_now_iso(),
        "source_kind": "run_dir_batch",
        "analysis_dir": str(out_dir.resolve()),
        "source_run_dirs": [str(path.resolve()) for path in run_dirs],
        "source_paths": {
            "thermal_summary_rel": str(THERMAL_SUMMARY_REL.as_posix()),
            "tile_temperature_summary_rel": str(TILE_SUMMARY_REL.as_posix()),
            "window_power_samples_rel": str(WINDOW_POWER_SAMPLES_REL.as_posix()),
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


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _write_csv(path: Path, rows: Iterable[Dict[str, Any]], *, fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_list = list(rows)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows_list:
            writer.writerow(row)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _as_float(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
        return value if math.isfinite(value) else None
    try:
        value = float(str(raw).strip())
    except Exception:
        return None
    return value if math.isfinite(value) else None


def _as_int(raw: Any) -> int | None:
    value = _as_float(raw)
    if value is None:
        return None
    return int(value)


def _fmt_float(raw: float | None) -> str:
    if raw is None or not math.isfinite(float(raw)):
        return ""
    return f"{float(raw):.6f}"


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0.0:
        return None
    return numerator / denominator


def _normalize_run_dirs(run_dirs: List[str]) -> List[Path]:
    seen = set()
    out: List[Path] = []
    for raw in run_dirs:
        run_dir = Path(raw).resolve()
        if run_dir in seen:
            continue
        seen.add(run_dir)
        out.append(run_dir)
    return sorted(out)


def _default_out_dir(run_dirs: List[Path], raw_out_dir: str | None) -> Path:
    if raw_out_dir:
        return Path(raw_out_dir).resolve()
    if len(run_dirs) == 1:
        return (run_dirs[0] / "thermal" / "analysis").resolve()
    return (Path.cwd() / "thermal_analysis_export").resolve()


def _layer_meta_map(summary: Dict[str, Any]) -> Dict[Tuple[str, int | None], Dict[str, Any]]:
    out: Dict[Tuple[str, int | None], Dict[str, Any]] = {}
    raw_layers = summary.get("layers")
    if not isinstance(raw_layers, list):
        return out
    for raw_layer in raw_layers:
        if not isinstance(raw_layer, dict):
            continue
        layer_name = str(raw_layer.get("name") or "").strip()
        layer_index = _as_int(raw_layer.get("layer_index"))
        out[(layer_name, layer_index)] = raw_layer
        if layer_name and (layer_name, None) not in out:
            out[(layer_name, None)] = raw_layer
    return out


def _pick_hottest_block(rows: List[Dict[str, str]]) -> Dict[str, str] | None:
    ranked: List[Tuple[float, float, str, Dict[str, str]]] = []
    for row in rows:
        temperature_c = _as_float(row.get("temperature_c"))
        average_power_w = _as_float(row.get("average_power_w")) or 0.0
        if temperature_c is None:
            continue
        ranked.append(
            (
                float(temperature_c),
                float(average_power_w),
                str(row.get("block_name") or ""),
                row,
            )
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return ranked[0][3]


def _unique_join(values: Iterable[str]) -> str:
    uniq = sorted({str(value).strip() for value in values if str(value).strip()})
    return ",".join(uniq)


def _row_layer_meta(
    row: Dict[str, Any],
    layer_meta: Dict[Tuple[str, int | None], Dict[str, Any]],
) -> Dict[str, Any]:
    layer_name = str(row.get("layer_name") or "")
    layer_index = _as_int(row.get("layer_index"))
    return layer_meta.get((layer_name, layer_index)) or layer_meta.get((layer_name, None)) or {}


def _is_nonzero_power_row(row: Dict[str, Any]) -> bool:
    return (_as_float(row.get("average_power_w")) or 0.0) > 0.0


def _is_active_layer_row(
    row: Dict[str, Any],
    layer_meta: Dict[Tuple[str, int | None], Dict[str, Any]],
) -> bool:
    meta = _row_layer_meta(row, layer_meta)
    if "power_dissipating" in meta:
        return bool(meta.get("power_dissipating"))
    kind = str(meta.get("kind") or "").strip().lower()
    if kind:
        return kind != "tim"
    return True


def _apply_block_filters(
    rows: List[Dict[str, Any]],
    *,
    layer_meta: Dict[Tuple[str, int | None], Dict[str, Any]],
    nonzero_power_only: bool = False,
    active_layers_only: bool = False,
) -> List[Dict[str, Any]]:
    filtered = list(rows)
    if nonzero_power_only:
        filtered = [row for row in filtered if _is_nonzero_power_row(row)]
    if active_layers_only:
        filtered = [row for row in filtered if _is_active_layer_row(row, layer_meta)]
    return filtered


def _infer_trace_source(row: Dict[str, Any], thermal_summary: Dict[str, Any]) -> str:
    existing = str(row.get("trace_source") or "").strip()
    if existing:
        return existing
    block_type = str(row.get("block_type") or "").strip().lower()
    power_source_type = str(row.get("power_source_type") or "").strip().lower()
    trace_mode = str(thermal_summary.get("trace_mode") or "average").strip().lower()
    if block_type == "memctrl":
        return "memctrl_proxy"
    if power_source_type == "csv":
        return "csv_constant" if trace_mode == "windowed" else "csv_average"
    if power_source_type == "none":
        return "disabled"
    if trace_mode == "windowed":
        return "window_metrics"
    return "average_power"


def _infer_window_scaling_mode(row: Dict[str, Any], thermal_summary: Dict[str, Any]) -> str:
    existing = str(row.get("window_scaling_mode") or "").strip()
    if existing:
        return existing
    trace_source = _infer_trace_source(row, thermal_summary)
    if trace_source == "window_metrics":
        return "per_tile_mean_normalized_metric"
    if str(thermal_summary.get("trace_mode") or "average").strip().lower() == "windowed":
        return "constant"
    return "single_average_row"


def _infer_trace_mode(row: Dict[str, Any], thermal_summary: Dict[str, Any]) -> str:
    existing = str(row.get("trace_mode") or "").strip()
    if existing:
        return existing
    trace_source = _infer_trace_source(row, thermal_summary)
    if trace_source == "window_metrics":
        return "windowed"
    if str(thermal_summary.get("trace_mode") or "average").strip().lower() == "windowed":
        return "constant"
    return "average"


def _count_real_tiles(rows: List[Dict[str, Any]]) -> int:
    values = {
        str(row.get("tile_id") or "").strip()
        for row in rows
        if str(row.get("tile_id") or "").strip()
    }
    return len(values)


def _layer_stack_validation_meta(summary: Dict[str, Any]) -> Dict[str, Any]:
    raw = summary.get("layer_stack_validation")
    if not isinstance(raw, dict):
        return {}
    status = str(raw.get("status") or "").strip()
    passed_raw = raw.get("passed")
    passed: bool | None
    if isinstance(passed_raw, bool):
        passed = passed_raw
    else:
        passed = None
    return {
        "status": status,
        "passed": passed,
        "layer_count_checked": _as_int(raw.get("layer_count_checked")),
        "mismatch_count": _as_int(raw.get("mismatch_count")),
    }


def _resolve_artifact_path(run_dir: Path, raw_path: Any) -> Path | None:
    value = str(raw_path or "").strip()
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    return (run_dir / path).resolve()


def _normalize_reason_list(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for item in raw:
        value = str(item or "").strip()
        if value:
            out.append(value)
    return out


def _load_layer_stack_validation_details(run_dir: Path, summary: Dict[str, Any]) -> Dict[str, Any]:
    meta = _layer_stack_validation_meta(summary)
    artifacts = summary.get("artifacts") if isinstance(summary.get("artifacts"), dict) else {}
    artifact_path = _resolve_artifact_path(run_dir, (artifacts or {}).get("layer_stack_validation"))
    if artifact_path is None:
        fallback = run_dir / "thermal" / "summary" / "layer_stack_validation.json"
        artifact_path = fallback if fallback.is_file() else None

    detail: Dict[str, Any] = {}
    if artifact_path is not None and artifact_path.is_file():
        try:
            raw_detail = _load_json(artifact_path)
        except Exception:
            raw_detail = {}
        if isinstance(raw_detail, dict):
            detail = raw_detail

    status = str(meta.get("status") or detail.get("status") or "").strip()
    passed = meta.get("passed")
    if passed is None and isinstance(detail.get("passed"), bool):
        passed = bool(detail.get("passed"))
    layer_count_checked = _as_int(meta.get("layer_count_checked"))
    if layer_count_checked is None:
        layer_count_checked = _as_int(detail.get("layer_count_checked"))
    mismatch_count = _as_int(meta.get("mismatch_count"))
    if mismatch_count is None:
        mismatch_count = _as_int(detail.get("mismatch_count"))

    mismatch_reason_layer_counts: Dict[str, int] = {}
    mismatch_reasons_set = set()
    config_mismatch_reasons = _normalize_reason_list(detail.get("config_mismatch_reasons"))
    failed_layer_count = 0
    for layer in detail.get("layers") if isinstance(detail.get("layers"), list) else []:
        if not isinstance(layer, dict):
            continue
        reasons = _normalize_reason_list(layer.get("mismatch_reasons"))
        matches = layer.get("matches")
        if reasons or matches is False:
            failed_layer_count += 1
        if matches is False and not reasons:
            reasons = ["unknown"]
        for reason in reasons:
            mismatch_reasons_set.add(reason)
            mismatch_reason_layer_counts[reason] = mismatch_reason_layer_counts.get(reason, 0) + 1

    parse_error = str(detail.get("parse_error") or "").strip()
    if parse_error:
        mismatch_reasons_set.add("parse_error")
        mismatch_reason_layer_counts["parse_error"] = mismatch_reason_layer_counts.get("parse_error", 0) + 1

    extra_entry_count = _as_int(detail.get("extra_entry_count")) or 0
    if extra_entry_count > 0:
        mismatch_reasons_set.add("extra_entry")
        mismatch_reason_layer_counts["extra_entry"] = mismatch_reason_layer_counts.get("extra_entry", 0) + extra_entry_count

    if (passed is False or (mismatch_count or 0) > 0) and not mismatch_reason_layer_counts:
        mismatch_reasons_set.add("unknown")
        mismatch_reason_layer_counts["unknown"] = max(1, int(mismatch_count or 1))

    if (
        not status
        and passed is None
        and layer_count_checked is None
        and mismatch_count is None
        and not mismatch_reason_layer_counts
        and not config_mismatch_reasons
    ):
        return {}

    return {
        "status": status,
        "passed": passed,
        "layer_count_checked": layer_count_checked,
        "mismatch_count": mismatch_count,
        "failed_layer_count": failed_layer_count,
        "mismatch_reasons": sorted(mismatch_reasons_set),
        "mismatch_reason_layer_counts": dict(sorted(mismatch_reason_layer_counts.items())),
        "failed_layers": [
            {
                "layer_name": str(layer.get("layer_name") or ""),
                "layer_index": _as_int(layer.get("layer_index")),
                "kind": str(layer.get("kind") or ""),
                "mismatch_reasons": _normalize_reason_list(layer.get("mismatch_reasons")),
                "expected_floorplan_file": str(layer.get("expected_floorplan_file") or ""),
                "lcf_floorplan_file": str(layer.get("lcf_floorplan_file") or ""),
            }
            for layer in (detail.get("layers") if isinstance(detail.get("layers"), list) else [])
            if isinstance(layer, dict) and (_normalize_reason_list(layer.get("mismatch_reasons")) or layer.get("matches") is False)
        ],
        "config_matches": detail.get("config_matches"),
        "config_mismatch_reasons": config_mismatch_reasons,
        "artifact_path": str(artifact_path) if artifact_path is not None else "",
    }


def _load_window_power_samples(run_dir: Path, summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    artifacts = summary.get("artifacts") if isinstance(summary.get("artifacts"), dict) else {}
    artifact_path = _resolve_artifact_path(run_dir, (artifacts or {}).get("window_power_samples_jsonl"))
    if artifact_path is None:
        fallback = run_dir / WINDOW_POWER_SAMPLES_REL
        artifact_path = fallback if fallback.is_file() else None
    if artifact_path is None:
        return []
    return _load_jsonl(artifact_path)


def _window_power_sample_meta(samples: List[Dict[str, Any]], summary: Dict[str, Any]) -> Dict[str, Any]:
    if not samples:
        trace_sources = summary.get("window_power_trace_sources") if isinstance(summary.get("window_power_trace_sources"), list) else []
        return {
            "sample_count": _as_int(summary.get("window_power_sample_count")) or 0,
            "block_count": _as_int(summary.get("window_power_block_count")) or 0,
            "trace_sources": sorted({str(item).strip() for item in trace_sources if str(item).strip()}),
        }

    trace_sources: set[str] = set()
    block_count = 0
    for sample in samples:
        blocks = sample.get("blocks") if isinstance(sample.get("blocks"), list) else []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_count += 1
            source = str(block.get("trace_source") or "").strip()
            if source:
                trace_sources.add(source)
    return {
        "sample_count": len(samples),
        "block_count": block_count,
        "trace_sources": sorted(trace_sources),
    }


def _summarize_layer_stack_validation(run_json_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    with_validation = 0
    passed_run_count = 0
    failed_run_count = 0
    unknown_run_count = 0
    failed_runs: List[Dict[str, Any]] = []
    mismatch_reason_run_counts: Dict[str, int] = {}
    mismatch_reason_layer_counts: Dict[str, int] = {}
    config_mismatch_reason_run_counts: Dict[str, int] = {}
    for row in run_json_rows:
        validation = row.get("layer_stack_validation")
        if not isinstance(validation, dict) or not validation:
            continue
        with_validation += 1
        passed = validation.get("passed")
        if passed is True:
            passed_run_count += 1
        elif passed is False:
            failed_run_count += 1
            reasons = [str(reason) for reason in (validation.get("mismatch_reasons") or []) if str(reason)]
            config_reasons = [str(reason) for reason in (validation.get("config_mismatch_reasons") or []) if str(reason)]
            layer_reason_counts = validation.get("mismatch_reason_layer_counts")
            if isinstance(layer_reason_counts, dict):
                for reason, count in layer_reason_counts.items():
                    reason_key = str(reason or "").strip()
                    if not reason_key:
                        continue
                    mismatch_reason_layer_counts[reason_key] = mismatch_reason_layer_counts.get(reason_key, 0) + max(
                        0, int(_as_int(count) or 0)
                    )
            for reason in reasons:
                mismatch_reason_run_counts[reason] = mismatch_reason_run_counts.get(reason, 0) + 1
            for reason in config_reasons:
                config_mismatch_reason_run_counts[reason] = config_mismatch_reason_run_counts.get(reason, 0) + 1
            failed_runs.append(
                {
                    "run_dir": str(row.get("run_dir") or ""),
                    "run_group": str(row.get("run_group") or ""),
                    "run_label": str(row.get("run_label") or ""),
                    "status": str(validation.get("status") or ""),
                    "mismatch_count": _as_int(validation.get("mismatch_count")),
                    "failed_layer_count": _as_int(validation.get("failed_layer_count")),
                    "mismatch_reasons": reasons,
                    "config_mismatch_reasons": config_reasons,
                }
            )
        else:
            unknown_run_count += 1
    return {
        "run_count_with_validation": with_validation,
        "passed_run_count": passed_run_count,
        "failed_run_count": failed_run_count,
        "unknown_run_count": unknown_run_count,
        "mismatch_reason_run_counts": dict(sorted(mismatch_reason_run_counts.items())),
        "mismatch_reason_layer_counts": dict(sorted(mismatch_reason_layer_counts.items())),
        "config_mismatch_reason_run_counts": dict(sorted(config_mismatch_reason_run_counts.items())),
        "failed_runs": failed_runs,
    }


def _build_layer_stack_validation_runs_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    failed_runs = summary.get("failed_runs") if isinstance(summary.get("failed_runs"), list) else []
    for item in failed_runs:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "run_dir": str(item.get("run_dir") or ""),
                "run_group": str(item.get("run_group") or ""),
                "run_label": str(item.get("run_label") or ""),
                "status": str(item.get("status") or ""),
                "mismatch_count": "" if _as_int(item.get("mismatch_count")) is None else str(_as_int(item.get("mismatch_count"))),
                "failed_layer_count": (
                    "" if _as_int(item.get("failed_layer_count")) is None else str(_as_int(item.get("failed_layer_count")))
                ),
                "mismatch_reasons": _unique_join(item.get("mismatch_reasons") or []),
                "config_mismatch_reasons": _unique_join(item.get("config_mismatch_reasons") or []),
            }
        )
    return rows


def _build_layer_stack_validation_all_runs_rows(run_json_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for run in run_json_rows:
        validation = run.get("layer_stack_validation")
        has_validation = isinstance(validation, dict) and bool(validation)
        rows.append(
            {
                "run_dir": str(run.get("run_dir") or ""),
                "run_group": str(run.get("run_group") or ""),
                "run_label": str(run.get("run_label") or ""),
                "window_power_sample_count": (
                    "" if _as_int(run.get("window_power_sample_count")) is None else str(_as_int(run.get("window_power_sample_count")))
                ),
                "window_power_block_count": (
                    "" if _as_int(run.get("window_power_block_count")) is None else str(_as_int(run.get("window_power_block_count")))
                ),
                "window_power_trace_sources": _unique_join(run.get("window_power_trace_sources") or []),
                "has_validation": "1" if has_validation else "0",
                "status": str((validation or {}).get("status") or ""),
                "passed": (
                    ""
                    if (validation or {}).get("passed") is None
                    else ("1" if bool((validation or {}).get("passed")) else "0")
                ),
                "layer_count_checked": (
                    ""
                    if _as_int((validation or {}).get("layer_count_checked")) is None
                    else str(_as_int((validation or {}).get("layer_count_checked")))
                ),
                "mismatch_count": (
                    ""
                    if _as_int((validation or {}).get("mismatch_count")) is None
                    else str(_as_int((validation or {}).get("mismatch_count")))
                ),
                "failed_layer_count": (
                    ""
                    if _as_int((validation or {}).get("failed_layer_count")) is None
                    else str(_as_int((validation or {}).get("failed_layer_count")))
                ),
                "mismatch_reasons": _unique_join((validation or {}).get("mismatch_reasons") or []),
                "config_matches": (
                    ""
                    if (validation or {}).get("config_matches") is None
                    else ("1" if bool((validation or {}).get("config_matches")) else "0")
                ),
                "config_mismatch_reasons": _unique_join((validation or {}).get("config_mismatch_reasons") or []),
            }
        )
    return rows


def _build_layer_stack_validation_fail_layer_rows(run_json_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for run in run_json_rows:
        validation = run.get("layer_stack_validation")
        if not isinstance(validation, dict) or not validation:
            continue
        failed_layers = validation.get("failed_layers")
        if not isinstance(failed_layers, list):
            continue
        for layer in failed_layers:
            if not isinstance(layer, dict):
                continue
            reasons = _normalize_reason_list(layer.get("mismatch_reasons"))
            if not reasons:
                reasons = ["unknown"]
            for reason in sorted(reasons):
                rows.append(
                    {
                        "run_dir": str(run.get("run_dir") or ""),
                        "run_group": str(run.get("run_group") or ""),
                        "run_label": str(run.get("run_label") or ""),
                        "status": str(validation.get("status") or ""),
                        "layer_name": str(layer.get("layer_name") or ""),
                        "layer_index": (
                            "" if _as_int(layer.get("layer_index")) is None else str(_as_int(layer.get("layer_index")))
                        ),
                        "layer_kind": str(layer.get("kind") or ""),
                        "reason": str(reason),
                        "expected_floorplan_file": str(layer.get("expected_floorplan_file") or ""),
                        "lcf_floorplan_file": str(layer.get("lcf_floorplan_file") or ""),
                    }
                )
    rows.sort(
        key=lambda row: (
            str(row.get("run_group") or ""),
            str(row.get("run_label") or ""),
            _as_int(row.get("layer_index")) if _as_int(row.get("layer_index")) is not None else 10**9,
            str(row.get("layer_name") or ""),
            str(row.get("reason") or ""),
        )
    )
    return rows


def _summarize_provenance(run_json_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    trace_source_run_counts: Dict[str, int] = {}
    window_scaling_mode_run_counts: Dict[str, int] = {}
    window_power_trace_source_counts: Dict[str, int] = {}
    memctrl_run_count = 0
    for row in run_json_rows:
        trace_sources = row.get("trace_sources") if isinstance(row.get("trace_sources"), list) else []
        for trace_source in sorted({str(item).strip() for item in trace_sources if str(item).strip()}):
            trace_source_run_counts[trace_source] = trace_source_run_counts.get(trace_source, 0) + 1
        scaling_modes = row.get("window_scaling_modes") if isinstance(row.get("window_scaling_modes"), list) else []
        for mode in sorted({str(item).strip() for item in scaling_modes if str(item).strip()}):
            window_scaling_mode_run_counts[mode] = window_scaling_mode_run_counts.get(mode, 0) + 1
        window_power_trace_sources = row.get("window_power_trace_sources") if isinstance(row.get("window_power_trace_sources"), list) else []
        for trace_source in sorted({str(item).strip() for item in window_power_trace_sources if str(item).strip()}):
            window_power_trace_source_counts[trace_source] = window_power_trace_source_counts.get(trace_source, 0) + 1
        if "memctrl_proxy" in {str(item).strip() for item in trace_sources if str(item).strip()}:
            memctrl_run_count += 1
    return {
        "trace_source_run_counts": dict(sorted(trace_source_run_counts.items())),
        "window_scaling_mode_run_counts": dict(sorted(window_scaling_mode_run_counts.items())),
        "window_power_trace_source_counts": dict(sorted(window_power_trace_source_counts.items())),
        "memctrl_run_count": memctrl_run_count,
    }


def _analyze_run(
    run_dir: Path,
    *,
    nonzero_power_only: bool = False,
    active_layers_only: bool = False,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
    summary_path = run_dir / THERMAL_SUMMARY_REL
    tile_summary_path = run_dir / TILE_SUMMARY_REL
    if not summary_path.is_file():
        raise FileNotFoundError(f"missing thermal summary: {summary_path}")
    if not tile_summary_path.is_file():
        raise FileNotFoundError(f"missing tile temperature summary: {tile_summary_path}")

    thermal_summary = _load_json(summary_path)
    tile_rows = _load_csv(tile_summary_path)
    layer_meta = _layer_meta_map(thermal_summary)
    analysis_rows = _apply_block_filters(
        tile_rows,
        layer_meta=layer_meta,
        nonzero_power_only=bool(nonzero_power_only),
        active_layers_only=bool(active_layers_only),
    )
    for row in analysis_rows:
        row["trace_source"] = _infer_trace_source(row, thermal_summary)
        row["window_scaling_mode"] = _infer_window_scaling_mode(row, thermal_summary)
        row["trace_mode"] = _infer_trace_mode(row, thermal_summary)

    run_group = run_dir.parent.name
    run_label = run_dir.name
    backend = str(thermal_summary.get("backend") or "")
    hotspot = thermal_summary.get("hotspot") if isinstance(thermal_summary.get("hotspot"), dict) else {}
    stack_validation = _load_layer_stack_validation_details(run_dir, thermal_summary)
    window_power_samples = _load_window_power_samples(run_dir, thermal_summary)
    window_power_meta = _window_power_sample_meta(window_power_samples, thermal_summary)
    thermal_summary_provenance = (
        dict(thermal_summary.get("artifact_provenance") or {})
        if isinstance(thermal_summary.get("artifact_provenance"), dict)
        else {}
    )
    ambient_c = _as_float(thermal_summary.get("ambient_c"))
    if ambient_c is None:
        ambient_k = _as_float(
            ((thermal_summary.get("hotspot_package") or {}).get("ambient_k"))
            if isinstance(thermal_summary.get("hotspot_package"), dict)
            else None
        )
        ambient_c = ambient_k - 273.15 if ambient_k is not None else 45.0
    run_total_power_w = sum(_as_float(row.get("average_power_w")) or 0.0 for row in analysis_rows)
    hottest_block = _pick_hottest_block(analysis_rows)

    layer_groups: Dict[Tuple[str, int | None], List[Dict[str, str]]] = {}
    for row in analysis_rows:
        layer_name = str(row.get("layer_name") or "")
        layer_index = _as_int(row.get("layer_index"))
        layer_groups.setdefault((layer_name, layer_index), []).append(row)

    layer_rows: List[Dict[str, Any]] = []
    for (layer_name, layer_index), rows in sorted(
        layer_groups.items(),
        key=lambda item: (
            item[0][1] if item[0][1] is not None else 10**9,
            item[0][0],
        ),
    ):
        meta = layer_meta.get((layer_name, layer_index)) or layer_meta.get((layer_name, None)) or {}
        total_power_w = sum(_as_float(row.get("average_power_w")) or 0.0 for row in rows)
        temps = [temp for temp in (_as_float(row.get("temperature_c")) for row in rows) if temp is not None]
        hottest = _pick_hottest_block(rows)
        layer_rows.append(
            {
                "run_dir": str(run_dir),
                "run_group": run_group,
                "run_label": run_label,
                "layer_name": layer_name,
                "layer_index": "" if layer_index is None else str(layer_index),
                "layer_kind": str(meta.get("kind") or ""),
                "power_source_type": _unique_join(
                    [str(row.get("power_source_type") or "") for row in rows]
                    or [str(((meta.get("power_source") or {}).get("type")) if isinstance(meta.get("power_source"), dict) else "")]
                ),
                "power_scale": _fmt_float(_as_float(meta.get("power_scale"))),
                "z_um": "" if _as_int(meta.get("z_um")) is None else str(_as_int(meta.get("z_um"))),
                "thickness_um": "" if _as_int(meta.get("thickness_um")) is None else str(_as_int(meta.get("thickness_um"))),
                "block_count": str(len(rows)),
                "tile_count": str(_count_real_tiles(rows)),
                "total_power_w": _fmt_float(total_power_w),
                "avg_power_w": _fmt_float(total_power_w / len(rows) if rows else None),
                "power_share": _fmt_float(_safe_div(total_power_w, run_total_power_w)),
                "ambient_c": _fmt_float(ambient_c),
                "temp_peak_over_ambient_c": _fmt_float((_as_float(max(temps) if temps else None) or 0.0) - ambient_c if temps else None),
                "temp_avg_c": _fmt_float(sum(temps) / len(temps) if temps else None),
                "temp_peak_c": _fmt_float(max(temps) if temps else None),
                "temp_min_c": _fmt_float(min(temps) if temps else None),
                "trace_sources": _unique_join(row.get("trace_source") or "" for row in rows),
                "window_scaling_modes": _unique_join(row.get("window_scaling_mode") or "" for row in rows),
                "hottest_block_name": str((hottest or {}).get("block_name") or ""),
                "hottest_block_temp_c": _fmt_float(_as_float((hottest or {}).get("temperature_c"))),
                "hottest_block_power_w": _fmt_float(_as_float((hottest or {}).get("average_power_w"))),
            }
        )

    hottest_layer = None
    hottest_layer_peak = -math.inf
    for row in layer_rows:
        peak = _as_float(row.get("temp_peak_c"))
        if peak is None:
            continue
        if peak > hottest_layer_peak:
            hottest_layer_peak = peak
            hottest_layer = row

    run_row = {
        "run_dir": str(run_dir),
        "run_group": run_group,
        "run_label": run_label,
        "backend": backend,
        "trace_mode": str(thermal_summary.get("trace_mode") or "average"),
        "window_count": str(_as_int(thermal_summary.get("window_count")) or 1),
        "hotspot_status": str(hotspot.get("status") or ""),
        "hotspot_returncode": "" if _as_int(hotspot.get("returncode")) is None else str(_as_int(hotspot.get("returncode"))),
        "hotspot_model_type": str(thermal_summary.get("hotspot_model_type") or ""),
        "layer_stack_validation_status": str(stack_validation.get("status") or ""),
        "layer_stack_validation_passed": (
            ""
            if stack_validation.get("passed") is None
            else ("1" if bool(stack_validation.get("passed")) else "0")
        ),
        "layer_stack_validation_layer_count_checked": (
            ""
            if _as_int(stack_validation.get("layer_count_checked")) is None
            else str(_as_int(stack_validation.get("layer_count_checked")))
        ),
        "layer_stack_validation_mismatch_count": (
            ""
            if _as_int(stack_validation.get("mismatch_count")) is None
            else str(_as_int(stack_validation.get("mismatch_count")))
        ),
        "layer_stack_validation_mismatch_reasons": _unique_join(stack_validation.get("mismatch_reasons") or []),
        "layer_count": "" if _as_int(thermal_summary.get("layer_count")) is None else str(_as_int(thermal_summary.get("layer_count"))),
        "mesh_size": "" if _as_int(thermal_summary.get("mesh_size")) is None else str(_as_int(thermal_summary.get("mesh_size"))),
        "tile_count": "" if _as_int(thermal_summary.get("tile_count")) is None else str(_as_int(thermal_summary.get("tile_count"))),
        "window_ns": "" if _as_int(thermal_summary.get("window_ns")) is None else str(_as_int(thermal_summary.get("window_ns"))),
        "duration_s": _fmt_float(_as_float(thermal_summary.get("duration_s"))),
        "ambient_c": _fmt_float(ambient_c),
        "temp_avg_c": _fmt_float(_as_float((thermal_summary.get("temperature_c") or {}).get("avg") if isinstance(thermal_summary.get("temperature_c"), dict) else None)),
        "temp_peak_c": _fmt_float(_as_float((thermal_summary.get("temperature_c") or {}).get("max") if isinstance(thermal_summary.get("temperature_c"), dict) else None)),
        "temp_min_c": _fmt_float(_as_float((thermal_summary.get("temperature_c") or {}).get("min") if isinstance(thermal_summary.get("temperature_c"), dict) else None)),
        "temp_peak_over_ambient_c": _fmt_float(
            (_as_float((thermal_summary.get("temperature_c") or {}).get("max") if isinstance(thermal_summary.get("temperature_c"), dict) else None) or 0.0)
            - ambient_c
            if _as_float((thermal_summary.get("temperature_c") or {}).get("max") if isinstance(thermal_summary.get("temperature_c"), dict) else None) is not None
            else None
        ),
        "temp_peak_over_avg_ratio": _fmt_float(
            _safe_div(
                _as_float((thermal_summary.get("temperature_c") or {}).get("max") if isinstance(thermal_summary.get("temperature_c"), dict) else None) or 0.0,
                _as_float((thermal_summary.get("temperature_c") or {}).get("avg") if isinstance(thermal_summary.get("temperature_c"), dict) else None) or 0.0,
            )
        ),
        "active_layer_count": str(len(layer_rows)),
        "trace_sources": _unique_join(row.get("trace_source") or "" for row in analysis_rows),
        "window_scaling_modes": _unique_join(row.get("window_scaling_mode") or "" for row in analysis_rows),
        "window_power_sample_count": str(int(window_power_meta.get("sample_count") or 0)),
        "window_power_block_count": str(int(window_power_meta.get("block_count") or 0)),
        "window_power_trace_sources": _unique_join(window_power_meta.get("trace_sources") or []),
        "total_power_w": _fmt_float(run_total_power_w),
        "hottest_block_name": str((hottest_block or {}).get("block_name") or ""),
        "hottest_block_temp_c": _fmt_float(_as_float((hottest_block or {}).get("temperature_c"))),
        "hottest_block_power_w": _fmt_float(_as_float((hottest_block or {}).get("average_power_w"))),
        "hottest_layer_name": str((hottest_layer or {}).get("layer_name") or ""),
        "hottest_layer_peak_c": _fmt_float(_as_float((hottest_layer or {}).get("temp_peak_c"))),
        "layer_stack_validation_config_mismatch_reasons": _unique_join(stack_validation.get("config_mismatch_reasons") or []),
    }

    top_blocks: List[Dict[str, Any]] = []
    for row in analysis_rows:
        temperature_c = _as_float(row.get("temperature_c"))
        if temperature_c is None:
            continue
        top_blocks.append(
            {
                "run_dir": str(run_dir),
                "run_group": run_group,
                "run_label": run_label,
                "layer_name": str(row.get("layer_name") or ""),
                "layer_index": "" if _as_int(row.get("layer_index")) is None else str(_as_int(row.get("layer_index"))),
                "block_name": str(row.get("block_name") or ""),
                "block_type": str(row.get("block_type") or ""),
                "tile_id": str(row.get("tile_id") or ""),
                "temperature_c": _fmt_float(temperature_c),
                "average_power_w": _fmt_float(_as_float(row.get("average_power_w"))),
                "power_source_type": str(row.get("power_source_type") or ""),
                "model_source": str(row.get("model_source") or ""),
                "trace_source": str(row.get("trace_source") or ""),
                "window_scaling_mode": str(row.get("window_scaling_mode") or ""),
            }
        )

    run_json = {
        "run_dir": str(run_dir),
        "run_group": run_group,
        "run_label": run_label,
        "backend": backend,
        "source_thermal_summary_tool": str(thermal_summary_provenance.get("tool") or ""),
        "source_thermal_summary_contract_version": str(
            thermal_summary_provenance.get("contract_version") or thermal_summary.get("thermal_contract_version") or ""
        ),
        "source_thermal_summary_generated_at_utc": str(thermal_summary_provenance.get("generated_at_utc") or ""),
        "trace_mode": str(thermal_summary.get("trace_mode") or "average"),
        "window_count": int(_as_int(thermal_summary.get("window_count")) or 1),
        "hotspot_status": str(hotspot.get("status") or ""),
        "hotspot_model_type": str(thermal_summary.get("hotspot_model_type") or ""),
        "ambient_c": ambient_c,
        "temp_avg_c": _as_float(run_row.get("temp_avg_c")),
        "temp_peak_c": _as_float(run_row.get("temp_peak_c")),
        "temp_min_c": _as_float(run_row.get("temp_min_c")),
        "temp_peak_over_ambient_c": _as_float(run_row.get("temp_peak_over_ambient_c")),
        "active_layer_count": _as_int(run_row.get("active_layer_count")),
        "trace_sources": [value for value in str(run_row.get("trace_sources") or "").split(",") if value],
        "window_scaling_modes": [value for value in str(run_row.get("window_scaling_modes") or "").split(",") if value],
        "window_power_sample_count": _as_int(run_row.get("window_power_sample_count")),
        "window_power_block_count": _as_int(run_row.get("window_power_block_count")),
        "window_power_trace_sources": [value for value in str(run_row.get("window_power_trace_sources") or "").split(",") if value],
        "total_power_w": _as_float(run_row.get("total_power_w")),
        "hottest_block_name": run_row.get("hottest_block_name"),
        "hottest_layer_name": run_row.get("hottest_layer_name"),
        "layer_stack_validation": {
            "status": str(stack_validation.get("status") or ""),
            "passed": stack_validation.get("passed"),
            "layer_count_checked": _as_int(stack_validation.get("layer_count_checked")),
            "mismatch_count": _as_int(stack_validation.get("mismatch_count")),
            "failed_layer_count": _as_int(stack_validation.get("failed_layer_count")),
            "mismatch_reasons": list(stack_validation.get("mismatch_reasons") or []),
            "config_matches": stack_validation.get("config_matches"),
            "config_mismatch_reasons": list(stack_validation.get("config_mismatch_reasons") or []),
            "mismatch_reason_layer_counts": dict(stack_validation.get("mismatch_reason_layer_counts") or {}),
            "failed_layers": list(stack_validation.get("failed_layers") or []),
        }
        if stack_validation
        else {},
    }
    return run_row, layer_rows, top_blocks, run_json


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze and export reusable summaries from HotSpot thermal run directories.")
    ap.add_argument("--run-dir", action="append", required=True, help="run dir containing thermal/summary artifacts (repeatable)")
    ap.add_argument("--out-dir", default="", help="output directory (default: single-run -> <run>/thermal/analysis, multi-run -> ./thermal_analysis_export)")
    ap.add_argument("--top-n", type=int, default=20, help="number of hottest blocks to export (default: 20)")
    ap.add_argument("--nonzero-power-only", action="store_true", help="exclude zero-power blocks from top_blocks.csv")
    ap.add_argument("--active-layers-only", action="store_true", help="exclude passive/non-power-dissipating layers from top_blocks.csv")
    args = ap.parse_args()

    run_dirs = _normalize_run_dirs(list(args.run_dir or []))
    if not run_dirs:
        raise SystemExit("no run dirs provided")

    out_dir = _default_out_dir(run_dirs, args.out_dir or None)
    run_rows: List[Dict[str, Any]] = []
    layer_rows: List[Dict[str, Any]] = []
    top_blocks: List[Dict[str, Any]] = []
    run_json_rows: List[Dict[str, Any]] = []

    for run_dir in run_dirs:
        run_row, per_layer_rows, per_block_rows, run_json = _analyze_run(
            run_dir,
            nonzero_power_only=bool(args.nonzero_power_only),
            active_layers_only=bool(args.active_layers_only),
        )
        run_rows.append(run_row)
        layer_rows.extend(per_layer_rows)
        top_blocks.extend(per_block_rows)
        run_json_rows.append(run_json)

    run_rows.sort(key=lambda row: (str(row.get("run_group") or ""), str(row.get("run_label") or ""), str(row.get("run_dir") or "")))
    run_json_rows.sort(
        key=lambda row: (
            str(row.get("run_group") or ""),
            str(row.get("run_label") or ""),
            str(row.get("run_dir") or ""),
        )
    )
    layer_rows.sort(
        key=lambda row: (
            str(row.get("run_group") or ""),
            _as_int(row.get("layer_index")) if _as_int(row.get("layer_index")) is not None else 10**9,
            str(row.get("layer_name") or ""),
        )
    )
    top_blocks.sort(
        key=lambda row: (
            -(_as_float(row.get("temperature_c")) or -math.inf),
            -(_as_float(row.get("average_power_w")) or -math.inf),
            str(row.get("block_name") or ""),
        )
    )
    top_blocks = top_blocks[: max(0, int(args.top_n))]
    for idx, row in enumerate(top_blocks, start=1):
        row["rank"] = str(idx)

    run_summary_fields = [
        "run_dir",
        "run_group",
        "run_label",
        "backend",
        "trace_mode",
        "window_count",
        "hotspot_status",
        "hotspot_returncode",
        "hotspot_model_type",
        "layer_stack_validation_status",
        "layer_stack_validation_passed",
        "layer_stack_validation_layer_count_checked",
        "layer_stack_validation_mismatch_count",
        "layer_stack_validation_mismatch_reasons",
        "layer_count",
        "mesh_size",
        "tile_count",
        "window_ns",
        "duration_s",
        "ambient_c",
        "temp_avg_c",
        "temp_peak_c",
        "temp_min_c",
        "temp_peak_over_ambient_c",
        "temp_peak_over_avg_ratio",
        "active_layer_count",
        "trace_sources",
        "window_scaling_modes",
        "window_power_sample_count",
        "window_power_block_count",
        "window_power_trace_sources",
        "total_power_w",
        "hottest_block_name",
        "hottest_block_temp_c",
        "hottest_block_power_w",
        "hottest_layer_name",
        "hottest_layer_peak_c",
        "layer_stack_validation_config_mismatch_reasons",
    ]
    layer_summary_fields = [
        "run_dir",
        "run_group",
        "run_label",
        "layer_name",
        "layer_index",
        "layer_kind",
        "power_source_type",
        "power_scale",
        "z_um",
        "thickness_um",
        "block_count",
        "tile_count",
        "total_power_w",
        "avg_power_w",
        "power_share",
        "ambient_c",
        "temp_peak_over_ambient_c",
        "temp_avg_c",
        "temp_peak_c",
        "temp_min_c",
        "trace_sources",
        "window_scaling_modes",
        "hottest_block_name",
        "hottest_block_temp_c",
        "hottest_block_power_w",
    ]
    top_blocks_fields = [
        "rank",
        "run_dir",
        "run_group",
        "run_label",
        "layer_name",
        "layer_index",
        "block_name",
        "block_type",
        "tile_id",
        "temperature_c",
        "average_power_w",
        "power_source_type",
        "model_source",
        "trace_source",
        "window_scaling_mode",
    ]

    _write_csv(out_dir / "run_summary.csv", run_rows, fieldnames=run_summary_fields)
    _write_csv(out_dir / "layer_summary.csv", layer_rows, fieldnames=layer_summary_fields)
    _write_csv(out_dir / "top_blocks.csv", top_blocks, fieldnames=top_blocks_fields)
    layer_stack_validation_summary = _summarize_layer_stack_validation(run_json_rows)
    _write_csv(
        out_dir / "layer_stack_validation_runs.csv",
        _build_layer_stack_validation_runs_rows(layer_stack_validation_summary),
        fieldnames=[
            "run_dir",
            "run_group",
            "run_label",
            "status",
            "mismatch_count",
            "failed_layer_count",
            "mismatch_reasons",
            "config_mismatch_reasons",
        ],
    )
    _write_csv(
        out_dir / "layer_stack_validation_all_runs.csv",
        _build_layer_stack_validation_all_runs_rows(run_json_rows),
        fieldnames=[
            "run_dir",
            "run_group",
            "run_label",
            "window_power_sample_count",
            "window_power_block_count",
            "window_power_trace_sources",
            "has_validation",
            "status",
            "passed",
            "layer_count_checked",
            "mismatch_count",
            "failed_layer_count",
            "mismatch_reasons",
            "config_matches",
            "config_mismatch_reasons",
        ],
    )
    _write_csv(
        out_dir / "layer_stack_validation_fail_layers.csv",
        _build_layer_stack_validation_fail_layer_rows(run_json_rows),
        fieldnames=[
            "run_dir",
            "run_group",
            "run_label",
            "status",
            "layer_name",
            "layer_index",
            "layer_kind",
            "reason",
            "expected_floorplan_file",
            "lcf_floorplan_file",
        ],
    )
    provenance_summary = _summarize_provenance(run_json_rows)
    _write_json(
        out_dir / "thermal_analysis.json",
        {
            "analysis_contract_version": ANALYSIS_CONTRACT_VERSION,
            "artifact_provenance": _build_artifact_provenance(out_dir=out_dir, run_dirs=run_dirs),
            "run_count": len(run_rows),
            "top_n": max(0, int(args.top_n)),
            "filters": {
                "nonzero_power_only": bool(args.nonzero_power_only),
                "active_layers_only": bool(args.active_layers_only),
            },
            "artifacts": {
                "run_summary_csv": str((out_dir / "run_summary.csv").resolve()),
                "layer_summary_csv": str((out_dir / "layer_summary.csv").resolve()),
                "top_blocks_csv": str((out_dir / "top_blocks.csv").resolve()),
                "layer_stack_validation_runs_csv": str((out_dir / "layer_stack_validation_runs.csv").resolve()),
                "layer_stack_validation_all_runs_csv": str((out_dir / "layer_stack_validation_all_runs.csv").resolve()),
                "layer_stack_validation_fail_layers_csv": str((out_dir / "layer_stack_validation_fail_layers.csv").resolve()),
            },
            "provenance_summary": provenance_summary,
            "layer_stack_validation_summary": layer_stack_validation_summary,
            "runs": run_json_rows,
        },
    )

    print(f"[thermal-analysis] wrote {out_dir / 'run_summary.csv'}")
    print(f"[thermal-analysis] wrote {out_dir / 'layer_summary.csv'}")
    print(f"[thermal-analysis] wrote {out_dir / 'top_blocks.csv'}")
    print(f"[thermal-analysis] wrote {out_dir / 'layer_stack_validation_runs.csv'}")
    print(f"[thermal-analysis] wrote {out_dir / 'layer_stack_validation_all_runs.csv'}")
    print(f"[thermal-analysis] wrote {out_dir / 'layer_stack_validation_fail_layers.csv'}")
    print(f"[thermal-analysis] wrote {out_dir / 'thermal_analysis.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
