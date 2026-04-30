#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


RUN_DIR_PATTERN = re.compile(r"^\[mesh\] run complete: (?P<run_dir>.+)$", re.MULTILINE)


def _load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_script_path(raw_path: str, *, default_rel: str) -> Path:
    if str(raw_path or "").strip():
        return Path(raw_path).resolve()
    return (_repo_root() / default_rel).resolve()


def _resolve_spec_path(raw_path: str, *, manifest_path: Path) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()
    manifest_relative = (manifest_path.parent / candidate).resolve()
    if manifest_relative.exists():
        return manifest_relative
    repo_relative = (_repo_root() / candidate).resolve()
    return repo_relative


def _run_command(
    cmd: List[str],
    *,
    env: Dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        env=env,
        cwd=str(cwd) if cwd is not None else None,
    )


def _parse_run_dir(output: str) -> str:
    matches = RUN_DIR_PATTERN.findall(output)
    if not matches:
        raise ValueError("cannot find '[mesh] run complete: <run_dir>' marker in runner output")
    return str(matches[-1]).strip()


def _bool_value(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_suite_manifest(manifest_path: Path) -> Dict[str, Any]:
    payload = _load_json(manifest_path)
    if str(payload.get("suite_contract_version") or "").strip() != "v1":
        raise ValueError(f"unsupported suite_contract_version in {manifest_path}")
    cases = list(payload.get("cases") or [])
    if not cases:
        raise ValueError(f"{manifest_path} must contain at least one case")
    return payload


def _build_case_commands(
    *,
    case_id: str,
    spec_path: Path,
    case_root: Path,
    mesh_runner: Path,
    analyzer: Path,
    report_generator: Path,
    python_bin: str,
) -> Dict[str, List[str]]:
    run_root = case_root / "runs"
    analysis_dir = case_root / "analysis"
    report_dir = case_root / "report"
    return {
        "run": ["bash", str(mesh_runner), "--spec", str(spec_path)],
        "analyze": [
            python_bin,
            str(analyzer),
            "--run-dir",
            str(run_root),  # placeholder; replaced after run
            "--out-dir",
            str(analysis_dir),
        ],
        "report": [
            python_bin,
            str(report_generator),
            "--analysis-dir",
            str(analysis_dir),
            "--out-dir",
            str(report_dir),
        ],
    }


def _verify_case_expectations(
    *,
    case_id: str,
    run_dir: Path,
    summary_json: Path,
    expectations: Dict[str, Any],
) -> List[str]:
    errors: List[str] = []
    thermal_summary = _load_json(run_dir / "thermal" / "summary" / "thermal_summary.json")
    sweep_summary = _load_json(summary_json)

    required_window = _bool_value(expectations.get("require_window_power_samples"))
    if required_window:
        if not (run_dir / "thermal" / "summary" / "window_power_samples.jsonl").is_file():
            errors.append(f"{case_id}: missing window_power_samples.jsonl")

    required_validation = _bool_value(expectations.get("require_layer_stack_validation"))
    rows = list(sweep_summary.get("layer_stack_validation_all_runs") or [])
    first_row = dict(rows[0] if rows else {})
    if required_validation and not _bool_value(first_row.get("has_validation")):
        errors.append(f"{case_id}: expected layer stack validation")

    expected_model_type = str(expectations.get("hotspot_model_type") or "").strip()
    actual_model_type = str(thermal_summary.get("hotspot_model_type") or "").strip()
    if expected_model_type and actual_model_type != expected_model_type:
        errors.append(
            f"{case_id}: hotspot_model_type mismatch expected={expected_model_type} actual={actual_model_type}"
        )
    return errors


def run_suite(
    *,
    manifest_path: Path,
    out_dir: Path,
    mesh_runner: Path,
    analyzer: Path,
    report_generator: Path,
    python_bin: str,
    dry_run: bool = False,
) -> Dict[str, Any]:
    manifest = _load_suite_manifest(manifest_path)
    cases_payload = list(manifest.get("cases") or [])
    out_dir.mkdir(parents=True, exist_ok=True)
    case_results: List[Dict[str, Any]] = []

    for raw_case in cases_payload:
        case = dict(raw_case or {})
        case_id = str(case.get("case_id") or "").strip()
        if not case_id:
            raise ValueError(f"manifest case is missing case_id: {raw_case!r}")
        spec_path = _resolve_spec_path(str(case.get("spec_path") or ""), manifest_path=manifest_path)
        case_root = out_dir / case_id
        commands = _build_case_commands(
            case_id=case_id,
            spec_path=spec_path,
            case_root=case_root,
            mesh_runner=mesh_runner,
            analyzer=analyzer,
            report_generator=report_generator,
            python_bin=python_bin,
        )
        case_result: Dict[str, Any] = {
            "case_id": case_id,
            "spec_path": str(spec_path),
            "expectations": dict(case.get("expectations") or {}),
            "commands": commands,
            "status": "planned" if dry_run else "pending",
            "artifacts": {
                "case_root": str(case_root.resolve()),
                "analysis_dir": str((case_root / "analysis").resolve()),
                "report_dir": str((case_root / "report").resolve()),
            },
        }
        if dry_run:
            case_results.append(case_result)
            continue

        run_env = dict(os.environ)
        run_env["MESH_RUN_ROOT"] = str((case_root / "runs").resolve())
        run_proc = _run_command(commands["run"], env=run_env, cwd=_repo_root() / "sst_dram_si")
        combined_run_output = (run_proc.stdout or "") + (run_proc.stderr or "")
        case_result["run_stdout"] = run_proc.stdout
        case_result["run_stderr"] = run_proc.stderr
        if run_proc.returncode != 0:
            case_result["status"] = "failed"
            case_result["error"] = f"run command failed with exit={run_proc.returncode}"
            case_results.append(case_result)
            continue

        run_dir = Path(_parse_run_dir(combined_run_output)).resolve()
        commands["analyze"][3] = str(run_dir)
        analyze_proc = _run_command(commands["analyze"], cwd=_repo_root())
        case_result["analyze_stdout"] = analyze_proc.stdout
        case_result["analyze_stderr"] = analyze_proc.stderr
        if analyze_proc.returncode != 0:
            case_result["status"] = "failed"
            case_result["error"] = f"analyze command failed with exit={analyze_proc.returncode}"
            case_result["artifacts"]["run_dir"] = str(run_dir)
            case_results.append(case_result)
            continue

        report_proc = _run_command(commands["report"], cwd=_repo_root())
        case_result["report_stdout"] = report_proc.stdout
        case_result["report_stderr"] = report_proc.stderr
        if report_proc.returncode != 0:
            case_result["status"] = "failed"
            case_result["error"] = f"report command failed with exit={report_proc.returncode}"
            case_result["artifacts"]["run_dir"] = str(run_dir)
            case_results.append(case_result)
            continue

        report_payload = _load_json(Path(json.loads(report_proc.stdout)["summary_json"]))
        summary_json = Path(json.loads(report_proc.stdout)["summary_json"]).resolve()
        report_csv = Path(json.loads(report_proc.stdout)["csv_path"]).resolve()
        report_markdown = Path(json.loads(report_proc.stdout)["markdown_path"]).resolve()
        analysis_json = (case_root / "analysis" / "thermal_analysis.json").resolve()
        expectation_errors = _verify_case_expectations(
            case_id=case_id,
            run_dir=run_dir,
            summary_json=summary_json,
            expectations=dict(case.get("expectations") or {}),
        )
        case_result["artifacts"].update(
            {
                "run_dir": str(run_dir),
                "analysis_json": str(analysis_json),
                "summary_json": str(summary_json),
                "report_csv": str(report_csv),
                "report_markdown": str(report_markdown),
            }
        )
        case_result["summary"] = {
            "run_count": int(report_payload.get("run_count", 0) or 0),
            "hotspot_model_type_counts": report_payload.get("hotspot_model_type_counts", {}),
        }
        if expectation_errors:
            case_result["status"] = "failed"
            case_result["error"] = "; ".join(expectation_errors)
        else:
            case_result["status"] = "passed"
        case_results.append(case_result)

    passed_case_count = sum(1 for case in case_results if case.get("status") == "passed")
    failed_case_count = sum(1 for case in case_results if case.get("status") == "failed")
    payload = {
        "suite_contract_version": "v1",
        "manifest_path": str(manifest_path.resolve()),
        "out_dir": str(out_dir.resolve()),
        "case_count": len(case_results),
        "passed_case_count": passed_case_count,
        "failed_case_count": failed_case_count,
        "dry_run": bool(dry_run),
        "cases": case_results,
    }
    result_json = out_dir / "thermal_contract_suite_result.json"
    _write_json(result_json, payload)
    return {
        "suite_contract_version": "v1",
        "manifest_path": str(manifest_path.resolve()),
        "out_dir": str(out_dir.resolve()),
        "result_json": str(result_json.resolve()),
        "case_count": len(case_results),
        "passed_case_count": passed_case_count,
        "failed_case_count": failed_case_count,
        "dry_run": bool(dry_run),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Run canonical HotSpot thermal contract suite and export evidence manifests.")
    ap.add_argument("--manifest", required=True, help="suite manifest JSON path")
    ap.add_argument("--out-dir", required=True, help="output directory for suite artifacts")
    ap.add_argument("--mesh-runner", default="", help="override path to run_mesh_with_time.sh compatible runner")
    ap.add_argument("--analyzer", default="", help="override path to analyze_thermal_runs.py")
    ap.add_argument("--report-generator", default="", help="override path to generate_thermal_sweep_report.py")
    ap.add_argument("--python-bin", default=sys.executable, help="python interpreter used for analyzer/report commands")
    ap.add_argument("--dry-run", action="store_true", help="only materialize planned commands without executing them")
    args = ap.parse_args()

    payload = run_suite(
        manifest_path=Path(args.manifest).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        mesh_runner=_resolve_script_path(args.mesh_runner, default_rel="sst_dram_si/tools/run_mesh_with_time.sh"),
        analyzer=_resolve_script_path(args.analyzer, default_rel="sst_dram_si/tools/analyze_thermal_runs.py"),
        report_generator=_resolve_script_path(args.report_generator, default_rel="sst_dram_si/tools/generate_thermal_sweep_report.py"),
        python_bin=str(args.python_bin or sys.executable),
        dry_run=bool(args.dry_run),
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
