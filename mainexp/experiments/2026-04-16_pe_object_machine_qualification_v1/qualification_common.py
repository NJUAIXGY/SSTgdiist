#!/usr/bin/env python3
"""Common helpers for PE object-machine qualification artifacts."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple


VALIDATION_RE = re.compile(r"fail=(\d+)\s+warn=(\d+)(?:\s+strict=(\d+))?")

CANONICAL_VIEWS: Dict[str, Tuple[str, ...]] = {
    "object_kind_census": ("object_kind_census", "atlas_object_kind_census"),
    "wms_storage_binding_map": (
        "wms_storage_binding_map",
        "atlas_wms_storage_binding_map",
    ),
    "binding_unresolved_ledger": (
        "binding_unresolved_ledger",
        "atlas_binding_unresolved_ledger",
    ),
    "control_binding_map": ("control_binding_map", "atlas_control_binding_map"),
    "object_closure": ("object_closure", "atlas_object_closure"),
    "schema_registry": ("schema_registry", "atlas_schema_registry"),
    "contract_mismatch": ("contract_mismatch", "atlas_contract_mismatch"),
}

COMPACT_OBJECT_SPECS: Dict[str, Tuple[str, str]] = {
    "idx2_object": ("object_closure", "idx2_object"),
    "rowindex_object": ("object_closure", "rowindex_object"),
    "preband_object": ("object_closure", "preband_object"),
    "shared_weight_residency": ("wms_storage_binding_map", "shared_weight_residency"),
    "weight_idx_store": ("wms_storage_binding_map", "weight_idx_store"),
    "weight_value_store": ("wms_storage_binding_map", "weight_value_store"),
    "activation_ingress_store": ("control_binding_map", "activation_ingress_store"),
    "rowdescriptor": ("control_binding_map", "rowdescriptor"),
    "sync_barrier": ("control_binding_map", "sync_barrier"),
}


def read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def load_cases(cases_path: Path) -> Dict[str, Any]:
    payload = read_json(cases_path)
    if not payload:
        raise SystemExit(f"missing or invalid cases file: {cases_path}")
    return payload


def find_case(cases_payload: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    for case in cases_payload.get("cases", []):
        if str(case.get("id")) == case_id:
            return case
    raise SystemExit(f"case_id not found in cases.json: {case_id}")


def resolve_run_dir(cases_path: Path, case: Dict[str, Any]) -> Tuple[Path, Path]:
    raw_run_dir = Path(str(case.get("run_dir", "")))
    requested_run_dir = (
        raw_run_dir if raw_run_dir.is_absolute() else (cases_path.parent / raw_run_dir)
    )
    requested_run_dir = requested_run_dir.resolve()
    return requested_run_dir, requested_run_dir.resolve()


def refresh_run_artifacts(run_dir: Path, project_root: Path) -> None:
    tools_dir = project_root / "sst_dram_si" / "tools"
    subprocess.run(
        [
            "python3",
            str(tools_dir / "compute_essential_summary_mesh.py"),
            "--run-dir",
            str(run_dir),
        ],
        check=True,
    )
    subprocess.run(
        [
            "python3",
            str(tools_dir / "summarize_atlas_activation_trace.py"),
            "--run-dir",
            str(run_dir),
        ],
        check=True,
    )
    validation_cmd = [
        "python3",
        str(tools_dir / "validate_essential_summary_mesh.py"),
        "--run-dir",
        str(run_dir),
    ]
    validation_proc = subprocess.run(
        validation_cmd,
        check=False,
        capture_output=True,
        text=True,
    )
    validation_text = validation_proc.stdout
    if validation_proc.stderr:
        validation_text += validation_proc.stderr
    (run_dir / "validation.log").write_text(validation_text, encoding="utf-8")
    if validation_proc.returncode != 0:
        raise subprocess.CalledProcessError(
            validation_proc.returncode,
            validation_cmd,
            output=validation_proc.stdout,
            stderr=validation_proc.stderr,
        )


def parse_validation_log(run_dir: Path) -> Dict[str, Any]:
    validation_path = run_dir / "validation.log"
    if not validation_path.exists():
        return {
            "fail": None,
            "warn": None,
            "strict": None,
            "summary_line": None,
            "status": "missing",
        }

    summary_line = None
    fail = warn = strict = None
    for raw_line in validation_path.read_text(encoding="utf-8").splitlines():
        match = VALIDATION_RE.search(raw_line)
        if not match:
            continue
        summary_line = raw_line
        fail = int(match.group(1))
        warn = int(match.group(2))
        strict = int(match.group(3) or 0)
    return {
        "fail": fail,
        "warn": warn,
        "strict": strict,
        "summary_line": summary_line,
        "status": "parsed" if summary_line else "present_without_summary",
    }


def _select_view(
    trace_payload: Dict[str, Any],
    summary_payload: Dict[str, Any],
    canonical_name: str,
) -> Tuple[Dict[str, Any], str]:
    aliases = CANONICAL_VIEWS[canonical_name]
    for alias in aliases:
        candidate = trace_payload.get(alias)
        if isinstance(candidate, dict) and candidate:
            return candidate, "trace"
    for alias in aliases:
        candidate = summary_payload.get(alias)
        if isinstance(candidate, dict) and candidate:
            return candidate, "summary"
    return {}, "absent"


def _config_value(config: Dict[str, Any], *path: str) -> Any:
    cursor: Any = config
    for part in path:
        if not isinstance(cursor, dict):
            return None
        cursor = cursor.get(part)
    return cursor


def build_config_summary(effective_config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "noc_type": effective_config.get("noc_type"),
        "local_storage_enable": int(bool(effective_config.get("local_storage_enable", 0))),
        "pe_internal_pod_enable": int(
            bool(effective_config.get("pe_internal_pod_enable", 0))
        ),
        "pe_internal_pod_metadata_enable": int(
            bool(effective_config.get("pe_internal_pod_metadata_enable", 0))
        ),
        "pe_internal_pod_owner_enable": int(
            bool(effective_config.get("pe_internal_pod_owner_enable", 0))
        ),
        "pulse": {
            "enable": int(bool(_config_value(effective_config, "pulse", "enable") or 0)),
            "osa_enable": int(
                bool(_config_value(effective_config, "pulse", "osa_enable") or 0)
            ),
            "osa_shared_weight_owner_enable": int(
                bool(
                    _config_value(
                        effective_config,
                        "pulse",
                        "osa_shared_weight_owner_enable",
                    )
                    or 0
                )
            ),
            "osa_shared_weight_owner_actual_enable": int(
                bool(
                    _config_value(
                        effective_config,
                        "pulse",
                        "osa_shared_weight_owner_actual_enable",
                    )
                    or 0
                )
            ),
        },
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _compact_entry(
    compact_name: str,
    view_name: str,
    entry: Dict[str, Any],
    view_source: str,
    binding_unresolved_ledger: Dict[str, Any],
) -> Dict[str, Any]:
    compact: Dict[str, Any] = {
        "name": compact_name,
        "view": view_name,
        "source_artifact": view_source,
    }
    if view_name == "object_closure":
        compact.update(
            {
                "authority_state": entry.get("authority_state"),
                "coverage_status": entry.get("coverage_status"),
                "contract_phase_state": entry.get("contract_phase_state"),
                "machine_reason": entry.get("machine_reason"),
                "formal_object_ref": entry.get("formal_object_ref"),
                "blocked_gates": _safe_list(entry.get("blocked_gates")),
                "dark_planes": _safe_list(entry.get("dark_planes")),
                "probe_status": entry.get("probe_status"),
                "requested_total": _safe_int(
                    entry.get("requested", {}).get("total")
                    if isinstance(entry.get("requested"), dict)
                    else None
                ),
                "effective_total": _safe_int(
                    entry.get("effective", {}).get("total")
                    if isinstance(entry.get("effective"), dict)
                    else None
                ),
                "constructed_total": _safe_int(
                    entry.get("constructed", {}).get("total")
                    if isinstance(entry.get("constructed"), dict)
                    else None
                ),
            }
        )
        return compact

    if view_name == "wms_storage_binding_map":
        ledger_entry = (
            binding_unresolved_ledger.get("entries", {}).get(compact_name, {})
            if isinstance(binding_unresolved_ledger, dict)
            else {}
        )
        compact.update(
            {
                "authority_state": entry.get("authority_state"),
                "binding_state": entry.get("binding_state"),
                "formalization_state": entry.get("formalization_state"),
                "machine_break_stage": entry.get("machine_break_stage"),
                "machine_break_label": entry.get("machine_break_label"),
                "runtime_owner": entry.get("runtime_owner"),
                "physical_scope": entry.get("physical_scope"),
                "owner_request_state": entry.get("owner_request_state"),
                "actual_request_state": entry.get("actual_request_state"),
                "unresolved_edges_count": _safe_int(
                    ledger_entry.get("unresolved_edges_count")
                ),
            }
        )
        return compact

    if view_name == "control_binding_map":
        compact.update(
            {
                "formalization_state": entry.get("formalization_state"),
                "lifecycle_contract": entry.get("lifecycle_contract"),
                "commit_relation": entry.get("commit_relation"),
                "runtime_owner": entry.get("runtime_owner"),
                "ready_visibility": entry.get("ready_visibility"),
                "release_visibility": entry.get("release_visibility"),
            }
        )
        return compact

    compact.update(entry)
    return compact


def _derive_schema_vocabularies(
    schema_registry: Dict[str, Any],
    views: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    registry_views = schema_registry.get("views", {}) if isinstance(schema_registry, dict) else {}
    for canonical_name, registry_entry in registry_views.items():
        if isinstance(registry_entry, dict):
            result[canonical_name] = registry_entry.get("vocabulary")
    for canonical_name, payload in views.items():
        if canonical_name == "source_map":
            continue
        if canonical_name in result:
            continue
        if canonical_name == "object_kind_census":
            version = payload.get("matrix_version")
            result[canonical_name] = (
                f"atlas_object_kind_census_v{version}" if version is not None else None
            )
        else:
            result[canonical_name] = payload.get("vocabulary")
    return result


def _collect_machine_blockers(binding_unresolved_ledger: Dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    for entry in binding_unresolved_ledger.get("entries", {}).values():
        if not isinstance(entry, dict):
            continue
        reason = str(entry.get("reason") or "").strip()
        if not reason or reason == "none" or reason in blockers:
            continue
        blockers.append(reason)
    return blockers


def build_case_snapshot(
    cases_path: Path,
    experiment_id: str,
    case: Dict[str, Any],
) -> Dict[str, Any]:
    requested_run_dir, resolved_run_dir = resolve_run_dir(cases_path, case)
    effective_config = read_json(resolved_run_dir / "effective_config.json")
    summary_payload = read_json(resolved_run_dir / "essential_summary_mesh.json")
    trace_payload = read_json(resolved_run_dir / "atlas_activation_trace.json")

    views: Dict[str, Dict[str, Any]] = {}
    source_map: Dict[str, str] = {}
    for canonical_name in CANONICAL_VIEWS:
        payload, source_name = _select_view(trace_payload, summary_payload, canonical_name)
        if canonical_name == "contract_mismatch":
            views[canonical_name] = payload
        else:
            views[canonical_name] = payload
        source_map[canonical_name] = source_name
    views["source_map"] = source_map

    binding_unresolved_ledger = views["binding_unresolved_ledger"]
    compact_objects: Dict[str, Any] = {}
    for compact_name, (view_name, entry_name) in COMPACT_OBJECT_SPECS.items():
        entries = views.get(view_name, {}).get("entries", {})
        entry = entries.get(entry_name) if isinstance(entries, dict) else None
        if not isinstance(entry, dict):
            continue
        compact_objects[compact_name] = _compact_entry(
            compact_name,
            view_name,
            entry,
            source_map.get(view_name, "absent"),
            binding_unresolved_ledger,
        )

    unresolved_entries = binding_unresolved_ledger.get("entries", {})
    unresolved_binding_entries = 0
    unresolved_binding_edges_total = 0
    if isinstance(unresolved_entries, dict):
        unresolved_binding_entries = len(unresolved_entries)
        for entry in unresolved_entries.values():
            if not isinstance(entry, dict):
                continue
            unresolved_binding_edges_total += _safe_int(
                entry.get("unresolved_edges_count", len(_safe_list(entry.get("unresolved_edges"))))
            )

    schema_registry = views["schema_registry"]
    snapshot = {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "case": {
            "id": str(case.get("id")),
            "label": case.get("label"),
            "requested_run_dir": str(requested_run_dir),
            "resolved_run_dir": str(resolved_run_dir),
        },
        "artifacts": {
            "effective_config_json": str(resolved_run_dir / "effective_config.json"),
            "essential_summary_mesh_json": str(
                resolved_run_dir / "essential_summary_mesh.json"
            ),
            "atlas_activation_trace_json": str(
                resolved_run_dir / "atlas_activation_trace.json"
            ),
            "validation_log": str(resolved_run_dir / "validation.log"),
        },
        "validation": parse_validation_log(resolved_run_dir),
        "config": build_config_summary(effective_config),
        "views": views,
        "compact_objects": compact_objects,
        "derived": {
            "unresolved_binding_entries": unresolved_binding_entries,
            "unresolved_binding_edges_total": unresolved_binding_edges_total,
            "schema_vocabularies": _derive_schema_vocabularies(schema_registry, views),
            "machine_blockers": _collect_machine_blockers(binding_unresolved_ledger),
        },
    }
    return snapshot


def gate_status_for_snapshot(snapshot: Dict[str, Any]) -> str:
    validation = snapshot.get("validation", {})
    fail = validation.get("fail")
    warn = validation.get("warn")
    unresolved_edges_total = snapshot.get("derived", {}).get(
        "unresolved_binding_edges_total",
        0,
    )
    if isinstance(fail, int) and fail > 0:
        return "fail"
    if (isinstance(warn, int) and warn > 0) or int(unresolved_edges_total or 0) > 0:
        return "warn"
    return "clean"


def count_by(items: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts
