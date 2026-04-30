#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

try:
    from sst_dram_si.tools.export_thermal_sweep_report import export_report
    from sst_dram_si.tools.summarize_thermal_analysis import summarize_analysis_dir
except ImportError:
    from export_thermal_sweep_report import export_report
    from summarize_thermal_analysis import summarize_analysis_dir


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _resolve_out_dir(analysis_dir: Path, raw_out_dir: str) -> Path:
    if str(raw_out_dir or "").strip():
        return Path(raw_out_dir).resolve()
    return analysis_dir.resolve()


def generate_report(analysis_dir: Path, out_dir: Path) -> Dict[str, Any]:
    summary = summarize_analysis_dir(analysis_dir)
    summary_json = out_dir / "thermal_sweep_overview.json"
    _write_json(summary_json, summary)
    export_payload = export_report(summary_json, out_dir)
    return {
        "analysis_dir": str(analysis_dir.resolve()),
        "out_dir": str(out_dir.resolve()),
        "sweep_summary_contract_version": str(summary.get("sweep_summary_contract_version") or ""),
        "summary_json": export_payload["summary_json"],
        "csv_path": export_payload["csv_path"],
        "markdown_path": export_payload["markdown_path"],
        "run_count": int(summary.get("run_count", 0) or 0),
        "hotspot_model_type_counts": summary.get("hotspot_model_type_counts", {}),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate thermal sweep overview JSON plus CSV/Markdown reports in one command."
    )
    ap.add_argument("--analysis-dir", required=True, help="directory containing thermal_analysis.json and related thermal artifacts")
    ap.add_argument("--out-dir", default="", help="output directory for summary/report artifacts (default: analysis dir)")
    args = ap.parse_args()

    analysis_dir = Path(args.analysis_dir).resolve()
    out_dir = _resolve_out_dir(analysis_dir, args.out_dir)
    payload = generate_report(analysis_dir, out_dir)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
