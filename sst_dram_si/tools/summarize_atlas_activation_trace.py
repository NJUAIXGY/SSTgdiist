#!/usr/bin/env python3
"""Write a focused atlas activation trace sidecar for mesh runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sst_dram_si.tools import compute_essential_summary_mesh as cesm


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return int(round(float(value)))


def _extract_requested_config(effective_cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "workload_impl": effective_cfg.get("workload_impl"),
        "local_storage_enable": _int_or_none(
            cesm._effective_flag(effective_cfg, "local_storage_enable")
        ),
        "pe_internal_pod_enable": _int_or_none(
            cesm._effective_flag(effective_cfg, "pe_internal_pod_enable")
        ),
        "pe_internal_pod_metadata_enable": _int_or_none(
            cesm._effective_flag(effective_cfg, "pe_internal_pod_metadata_enable")
        ),
        "pe_internal_pod_owner_enable": _int_or_none(
            cesm._effective_flag(effective_cfg, "pe_internal_pod_owner_enable")
        ),
        "pulse": {
            "enable": _int_or_none(cesm._effective_flag(effective_cfg, "pulse", "enable")),
            "observe_only": _int_or_none(
                cesm._effective_flag(effective_cfg, "pulse", "observe_only")
            ),
            "actual_ingress_enable": _int_or_none(
                cesm._effective_flag(effective_cfg, "pulse", "actual_ingress_enable")
            ),
            "harbor_enable": _int_or_none(
                cesm._effective_flag(effective_cfg, "pulse", "harbor_enable")
            ),
            "descriptor_enable": _int_or_none(
                cesm._effective_flag(effective_cfg, "pulse", "descriptor_enable")
            ),
            "descriptor_actual_enable": _int_or_none(
                cesm._effective_flag(effective_cfg, "pulse", "descriptor_actual_enable")
            ),
            "osa_enable": _int_or_none(
                cesm._effective_flag(effective_cfg, "pulse", "osa_enable")
            ),
            "osa_shared_weight_owner_enable": _int_or_none(
                cesm._effective_flag(
                    effective_cfg, "pulse", "osa_shared_weight_owner_enable"
                )
            ),
            "osa_shared_weight_actual_enable": _int_or_none(
                cesm._effective_flag(
                    effective_cfg, "pulse", "osa_shared_weight_actual_enable"
                )
            ),
        },
    }


def _active_labels(
    section: Dict[str, Dict[str, Any]], ordered_fields: Iterable[tuple[str, str]]
) -> List[str]:
    labels: List[str] = []
    for label, _ in ordered_fields:
        payload = section.get(label, {})
        total = int(payload.get("total", 0) or 0)
        if total > 0:
            labels.append(label)
    return labels


def _counter_payload(section: Dict[str, Any], key: str) -> Dict[str, Any]:
    payload = section.get(key, {})
    return {
        "total": int(payload.get("total", 0) or 0),
        "share": payload.get("share"),
    }


def _requested_bool(value: Any) -> int:
    if value is None:
        return 0
    return 1 if int(value) != 0 else 0


def _build_activation_diff(
    census: Dict[str, Any],
    requested_cfg: Dict[str, Any],
    surface_state: Dict[str, Any],
) -> Dict[str, Any]:
    enable_state = census.get("enable_state", {})
    activation_gate = census.get("activation_gate", {})
    shared_flags = census.get("shared_weight", {}).get("flags", {})
    surfaces_state = surface_state.get("surfaces", {})
    if not isinstance(surfaces_state, dict):
        surfaces_state = {}

    def _machine_surface(name: str) -> Dict[str, Any]:
        payload = surfaces_state.get(name, {})
        if not isinstance(payload, dict):
            payload = {}
        return {
            "machine_state": str(payload.get("machine_state") or "unknown"),
            "machine_reason": str(payload.get("reason") or "surface state unavailable"),
        }

    requested_local_storage = _requested_bool(requested_cfg.get("local_storage_enable"))
    requested_pulse = _requested_bool(requested_cfg.get("pulse", {}).get("enable"))
    requested_pulse_osa = _requested_bool(requested_cfg.get("pulse", {}).get("osa_enable"))
    requested_shared_weight_owner = _requested_bool(
        requested_cfg.get("pulse", {}).get("osa_shared_weight_owner_enable")
    )
    requested_pod_enable = _requested_bool(requested_cfg.get("pe_internal_pod_enable"))

    effective_local_storage = _counter_payload(enable_state, "local_storage")
    effective_pulse = _counter_payload(enable_state, "pulse_effective")
    effective_pulse_osa = _counter_payload(enable_state, "pulse_osa")
    effective_shared_weight_owner = _counter_payload(shared_flags, "owner_scope_enable")
    effective_service_table = _counter_payload(enable_state, "pe_local_service_table")

    constructed_pulse_fabric = _counter_payload(activation_gate, "pulse_fabric_constructed")
    constructed_service_table = _counter_payload(activation_gate, "service_table_constructed")
    constructed_shared_weight = _counter_payload(activation_gate, "shared_weight_plane_constructed")
    constructed_pod_metadata = _counter_payload(activation_gate, "pod_metadata_plane_constructed")
    constructed_pod_owner = _counter_payload(activation_gate, "pod_owner_table_constructed")

    local_storage_state = "disabled"
    if requested_local_storage:
        local_storage_state = (
            "active" if effective_local_storage["total"] > 0 else "requested_but_not_effective"
        )

    if not requested_pulse:
        pulse_state = "not_requested"
    elif effective_pulse["total"] > 0:
        pulse_state = "active"
    elif constructed_pulse_fabric["total"] > 0:
        pulse_state = "constructed_without_effective"
    else:
        pulse_state = "requested_but_not_effective"

    if not requested_pulse_osa:
        pulse_osa_state = "not_requested"
    elif effective_pulse_osa["total"] > 0:
        pulse_osa_state = "active"
    else:
        pulse_osa_state = "requested_but_not_effective"

    shared_weight_state = (
        "active" if constructed_shared_weight["total"] > 0 else "not_constructed"
    )
    pod_or_service_constructed = (
        constructed_service_table["total"]
        + constructed_pod_metadata["total"]
        + constructed_pod_owner["total"]
    )
    pod_service_state = "active" if pod_or_service_constructed > 0 else "not_constructed"

    return {
        "state_vocabulary": surface_state.get("vocabulary"),
        "requested": {
            "local_storage": requested_local_storage,
            "pulse": requested_pulse,
            "pulse_osa": requested_pulse_osa,
            "shared_weight_owner": requested_shared_weight_owner,
            "pod_enable": requested_pod_enable,
        },
        "effective": {
            "local_storage": effective_local_storage,
            "pulse": effective_pulse,
            "pulse_osa": effective_pulse_osa,
            "shared_weight_owner": effective_shared_weight_owner,
            "service_table": effective_service_table,
        },
        "constructed": {
            "pulse_fabric": constructed_pulse_fabric,
            "service_table": constructed_service_table,
            "shared_weight_plane": constructed_shared_weight,
            "pod_metadata_plane": constructed_pod_metadata,
            "pod_owner_table": constructed_pod_owner,
        },
        "surfaces": {
            "local_storage": {
                "state": local_storage_state,
                "requested": requested_local_storage,
                "effective_total": effective_local_storage["total"],
                **_machine_surface("local_storage"),
            },
            "pulse": {
                "state": pulse_state,
                "requested": requested_pulse,
                "effective_total": effective_pulse["total"],
                "constructed_total": constructed_pulse_fabric["total"],
                **_machine_surface("pulse"),
            },
            "pulse_osa": {
                "state": pulse_osa_state,
                "requested": requested_pulse_osa,
                "effective_total": effective_pulse_osa["total"],
                **_machine_surface("pulse_osa"),
            },
            "shared_weight": {
                "state": shared_weight_state,
                "requested_owner": requested_shared_weight_owner,
                "effective_owner_total": effective_shared_weight_owner["total"],
                "constructed_total": constructed_shared_weight["total"],
                **_machine_surface("shared_weight_authority"),
            },
            "pod_service": {
                "state": pod_service_state,
                "requested_pod": requested_pod_enable,
                "effective_service_table_total": effective_service_table["total"],
                "constructed_service_table_total": constructed_service_table["total"],
                "constructed_pod_metadata_total": constructed_pod_metadata["total"],
                "constructed_pod_owner_total": constructed_pod_owner["total"],
                **_machine_surface("pod_service"),
            },
        },
    }


def _build_verdict(
    census: Dict[str, Any],
    requested_cfg: Dict[str, Any],
) -> Dict[str, Any]:
    control_runtime = census.get("control_runtime", {})
    control_state = control_runtime.get("state", {})
    dominant = control_runtime.get("dominant_state", {})
    active_labels = _active_labels(control_state, cesm._ATLAS_CONTROL_RUNTIME_STATE_FIELDS)
    pe_count = int(census.get("pe_count", 0) or 0)
    dominant_label = dominant.get("label")
    dominant_count = int(dominant.get("count", 0) or 0)
    is_uniform = pe_count > 0 and len(active_labels) == 1 and dominant_count == pe_count
    if not active_labels:
        branch = "no_control_runtime_state"
    elif is_uniform and dominant_label:
        branch = str(dominant_label)
    else:
        branch = "mixed"
    activation_gate = census.get("activation_gate", {})
    classification = control_runtime.get("classification", {})
    return {
        "branch": branch,
        "is_uniform": is_uniform,
        "active_labels": active_labels,
        "dominant_label": dominant_label,
        "dominant_count": dominant_count,
        "dominant_share": dominant.get("share"),
        "pulse_requested": requested_cfg.get("pulse", {}).get("enable"),
        "pulse_fabric_constructed_total": int(
            activation_gate.get("pulse_fabric_constructed", {}).get("total", 0) or 0
        ),
        "control_runtime_all_zero_total": int(
            classification.get("all_zero", {}).get("total", 0) or 0
        ),
    }


def compute_atlas_activation_trace(run_dir: Path) -> Dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    meta = cesm._read_json(run_dir / "meta.json")
    effective_cfg = cesm._read_json(run_dir / "effective_config.json")
    stats, by_component, sim_time_ps = cesm._load_mesh_stats(run_dir)
    model = cesm._build_model(run_dir, meta, effective_cfg, sim_time_ps)
    census = cesm._build_atlas_activation_census(stats, model, by_component, effective_cfg)
    noc_mem_joint, _ = cesm._build_noc_mem_joint(stats, run_dir)
    (
        atlas_service,
        atlas_proxy,
        _,
        atlas_control,
        atlas_fabric,
        atlas_storage,
        atlas_sync,
        _,
        atlas_object_lifecycle,
    ) = cesm._build_atlas_sections(stats, noc_mem_joint)
    requested_cfg = _extract_requested_config(effective_cfg)
    config_resolution = cesm._build_atlas_config_resolution(effective_cfg)
    contract_mismatch = cesm._build_atlas_contract_mismatch(census, atlas_sync)
    object_kind_census = cesm._build_atlas_object_kind_census(
        stats,
        atlas_service,
        atlas_storage,
        atlas_object_lifecycle,
        census,
    )
    storage_authority_map = cesm._build_atlas_storage_authority_map(
        census,
        atlas_storage,
        atlas_service,
        atlas_proxy,
        atlas_object_lifecycle,
        object_kind_census,
    )
    wms_storage_binding_map = cesm._build_atlas_wms_storage_binding_map(
        atlas_storage,
        storage_authority_map,
        census,
    )
    binding_unresolved_ledger = cesm._build_atlas_binding_unresolved_ledger(
        wms_storage_binding_map
    )
    cross_plane_visibility = cesm._build_atlas_cross_plane_visibility(
        census,
        contract_mismatch,
        object_kind_census,
    )
    control_commit_view = cesm._build_atlas_control_commit_view(contract_mismatch)
    control_binding_map = cesm._build_atlas_control_binding_map(
        stats,
        object_kind_census,
        atlas_control,
        atlas_fabric,
        atlas_sync,
        control_commit_view,
    )
    surface_state = cesm._build_atlas_surface_state_view(contract_mismatch)
    surface_ledger = cesm._build_atlas_surface_ledger(
        config_resolution,
        census,
        contract_mismatch,
        cross_plane_visibility,
        surface_state,
    )
    surface_coverage = cesm._build_atlas_surface_coverage(surface_ledger)
    surface_probe_ledger = cesm._build_atlas_surface_probe_ledger(
        surface_coverage,
        census,
        surface_ledger,
    )
    surface_probe_backlog = cesm._build_atlas_surface_probe_backlog(
        surface_probe_ledger
    )
    object_closure = cesm._build_atlas_object_closure(
        surface_ledger,
        surface_coverage,
        surface_probe_ledger,
        storage_authority_map,
    )
    schema_registry = cesm._build_atlas_schema_registry(
        [
            {
                "name": "object_kind_census",
                "payload": object_kind_census,
                "version_field": "matrix_version",
                "default_vocabulary": "atlas_object_kind_census_v2",
                "authority_source": "trace_reader",
                "artifact_surfaces": ["trace"],
            },
            {
                "name": "storage_authority_map",
                "payload": storage_authority_map,
                "default_vocabulary": "atlas_storage_authority_map_v1",
                "authority_source": "trace_reader",
                "artifact_surfaces": ["trace", "snapshot"],
            },
            {
                "name": "wms_storage_binding_map",
                "payload": wms_storage_binding_map,
                "default_vocabulary": "atlas_wms_storage_binding_map_v2",
                "authority_source": "trace_reader",
                "artifact_surfaces": ["trace", "snapshot"],
            },
            {
                "name": "binding_unresolved_ledger",
                "payload": binding_unresolved_ledger,
                "default_vocabulary": "atlas_binding_unresolved_ledger_v1",
                "authority_source": "trace_reader",
                "artifact_surfaces": ["trace", "snapshot"],
            },
            {
                "name": "cross_plane_visibility",
                "payload": cross_plane_visibility,
                "default_vocabulary": "atlas_cross_plane_visibility_v1",
                "authority_source": "trace_reader",
                "artifact_surfaces": ["trace"],
            },
            {
                "name": "control_commit_view",
                "payload": control_commit_view,
                "default_vocabulary": "atlas_control_commit_view_v1",
                "authority_source": "trace_reader",
                "artifact_surfaces": ["trace"],
            },
            {
                "name": "control_binding_map",
                "payload": control_binding_map,
                "default_vocabulary": "atlas_control_binding_map_v1",
                "authority_source": "trace_reader",
                "artifact_surfaces": ["trace", "snapshot"],
            },
            {
                "name": "object_closure",
                "payload": object_closure,
                "default_vocabulary": "atlas_object_closure_v1",
                "authority_source": "trace_reader",
                "artifact_surfaces": ["trace", "snapshot"],
            },
        ]
    )
    activation_diff = _build_activation_diff(census, requested_cfg, surface_state)
    verdict = _build_verdict(census, requested_cfg)
    return {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "refs": {
            "meta_json": "meta.json",
            "effective_config_json": "effective_config.json",
            "mesh_stats_csv": "mesh_stats.csv",
        },
        "config_requested": requested_cfg,
        "config_resolution": config_resolution,
        "census": census,
        "object_kind_census": object_kind_census,
        "storage_authority_map": storage_authority_map,
        "wms_storage_binding_map": wms_storage_binding_map,
        "binding_unresolved_ledger": binding_unresolved_ledger,
        "cross_plane_visibility": cross_plane_visibility,
        "control_commit_view": control_commit_view,
        "control_binding_map": control_binding_map,
        "schema_registry": schema_registry,
        "surface_ledger": surface_ledger,
        "surface_coverage": surface_coverage,
        "surface_probe_ledger": surface_probe_ledger,
        "surface_probe_backlog": surface_probe_backlog,
        "object_closure": object_closure,
        "activation_diff": activation_diff,
        "contract_mismatch": contract_mismatch,
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)
    run_dir = Path(args.run_dir).resolve()
    output = Path(args.output).resolve() if args.output else run_dir / "atlas_activation_trace.json"
    trace = compute_atlas_activation_trace(run_dir)
    output.write_text(json.dumps(trace, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
