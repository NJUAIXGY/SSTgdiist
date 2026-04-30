#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List


def _load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _write_csv(path: Path, rows: List[Dict[str, str]], *, fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fmt_bool(raw: Any, *, true_value: str, false_value: str, unknown_value: str) -> str:
    if raw is True:
        return true_value
    if raw is False:
        return false_value
    return unknown_value


def _join_reasons(raw: Any) -> str:
    if isinstance(raw, list):
        items = [str(item or "").strip() for item in raw]
    else:
        items = [part.strip() for part in str(raw or "").split(",")]
    return ",".join(sorted({item for item in items if item}))


def _report_rows(summary: Dict[str, Any]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for item in summary.get("layer_stack_validation_all_runs") if isinstance(summary.get("layer_stack_validation_all_runs"), list) else []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "run_group": str(item.get("run_group") or ""),
                "run_label": str(item.get("run_label") or ""),
                "hotspot_model_type": str(item.get("hotspot_model_type") or ""),
                "has_validation": _fmt_bool(item.get("has_validation"), true_value="1", false_value="0", unknown_value=""),
                "validation_status": str(item.get("status") or ""),
                "validation_passed": _fmt_bool(item.get("passed"), true_value="1", false_value="0", unknown_value=""),
                "layer_count_checked": "" if item.get("layer_count_checked") is None else str(item.get("layer_count_checked")),
                "mismatch_count": "" if item.get("mismatch_count") is None else str(item.get("mismatch_count")),
                "failed_layer_count": "" if item.get("failed_layer_count") is None else str(item.get("failed_layer_count")),
                "config_matches": _fmt_bool(item.get("config_matches"), true_value="1", false_value="0", unknown_value=""),
                "mismatch_reasons": _join_reasons(item.get("mismatch_reasons")),
                "config_mismatch_reasons": _join_reasons(item.get("config_mismatch_reasons")),
                "run_dir": str(item.get("run_dir") or ""),
            }
        )
    return rows


def _markdown_table(rows: List[Dict[str, str]]) -> str:
    lines = [
        "| Run Group | Model | Has Validation | Status | Passed | Layers Checked | Mismatch Count | Config Matches |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    row.get("run_group", ""),
                    row.get("hotspot_model_type", ""),
                    "yes" if row.get("has_validation") == "1" else "no",
                    row.get("validation_status", ""),
                    (
                        "yes"
                        if row.get("validation_passed") == "1"
                        else ("no" if row.get("validation_passed") == "0" else "unknown")
                    ),
                    row.get("layer_count_checked", ""),
                    row.get("mismatch_count", ""),
                    (
                        "yes"
                        if row.get("config_matches") == "1"
                        else ("no" if row.get("config_matches") == "0" else "unknown")
                    ),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _build_markdown(summary: Dict[str, Any], rows: List[Dict[str, str]]) -> str:
    overview = summary.get("layer_stack_validation_overview") if isinstance(summary.get("layer_stack_validation_overview"), dict) else {}
    model_counts = summary.get("hotspot_model_type_counts") if isinstance(summary.get("hotspot_model_type_counts"), dict) else {}
    summary_contract_version = str(summary.get("sweep_summary_contract_version") or "")
    model_counts_text = ", ".join(f"{key}={value}" for key, value in sorted(model_counts.items())) or "none"
    lines = [
        "# Thermal Sweep Report",
        "",
        f"Analysis dir: {summary.get('analysis_dir', '')}",
        f"Summary contract version: {summary_contract_version}",
        f"Run count: {summary.get('run_count', 0)}",
        f"HotSpot model counts: {model_counts_text}",
        f"Layer-stack validation source: {overview.get('source', '')}",
        "",
        "## Validation Overview",
        "",
        f"- Total rows: {overview.get('total_rows', 0)}",
        f"- With validation: {overview.get('with_validation_count', 0)}",
        f"- Without validation: {overview.get('without_validation_count', 0)}",
        f"- Passed: {overview.get('passed_count', 0)}",
        f"- Failed: {overview.get('failed_count', 0)}",
        f"- Unknown: {overview.get('unknown_count', 0)}",
        f"- Config matched: {overview.get('config_matched_count', 0)}",
        f"- Config mismatched: {overview.get('config_mismatched_count', 0)}",
        "",
        "## Run Table",
        "",
        _markdown_table(rows),
        "",
    ]
    return "\n".join(lines)


def export_report(summary_json: Path, out_dir: Path) -> Dict[str, str]:
    summary = _load_json(summary_json)
    rows = _report_rows(summary)
    csv_path = out_dir / "thermal_sweep_report.csv"
    md_path = out_dir / "thermal_sweep_report.md"
    _write_csv(
        csv_path,
        rows,
        fieldnames=[
            "run_group",
            "run_label",
            "hotspot_model_type",
            "has_validation",
            "validation_status",
            "validation_passed",
            "layer_count_checked",
            "mismatch_count",
            "failed_layer_count",
            "config_matches",
            "mismatch_reasons",
            "config_mismatch_reasons",
            "run_dir",
        ],
    )
    _write_text(md_path, _build_markdown(summary, rows))
    return {
        "sweep_summary_contract_version": str(summary.get("sweep_summary_contract_version") or ""),
        "summary_json": str(summary_json.resolve()),
        "csv_path": str(csv_path.resolve()),
        "markdown_path": str(md_path.resolve()),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Export CSV/Markdown thermal sweep reports from summarize_thermal_analysis JSON output.")
    ap.add_argument("--summary-json", required=True, help="summary JSON emitted by summarize_thermal_analysis.py")
    ap.add_argument("--out-dir", default="", help="output directory (default: summary JSON parent)")
    args = ap.parse_args()

    summary_json = Path(args.summary_json).resolve()
    out_dir = Path(args.out_dir).resolve() if str(args.out_dir or "").strip() else summary_json.parent.resolve()
    payload = export_report(summary_json, out_dir)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
