#!/usr/bin/env python3
"""Build a compare.tsv snapshot for the atlas_service RowIndex object A/B smoke."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple


VALIDATION_RE = re.compile(r"fail=(\d+)\s+warn=(\d+)(?:\s+strict=(\d+))?")

MAINLINE_METRICS: Tuple[str, ...] = (
    "validation.fail",
    "validation.warn",
    "validation.strict",
    "model.sim_time_actual_ns",
    "memory.memory_requests",
    "memhierarchy.memctrl.req_total",
)

ATLAS_SERVICE_METRICS: Tuple[str, ...] = (
    "atlas_service.atlas_service_enabled",
    "atlas_service.atlas_service_owner_form_total",
    "atlas_service.atlas_service_join_live_total",
    "atlas_service.atlas_service_join_ready_total",
    "atlas_service.atlas_service_late_join_total",
    "atlas_service.atlas_service_duplicate_join_total",
    "atlas_service.atlas_service_ready_transition_total",
    "atlas_service.atlas_service_ready_fanout_total",
    "atlas_service.atlas_service_ready_fanout_consumers_sum",
    "atlas_service.atlas_service_ready_fanout_consumers_peak",
    "atlas_service.atlas_service_ready_fanout_avg",
    "atlas_service.atlas_service_released_total",
    "atlas_service.atlas_service_release_deferred_total",
    "atlas_service.atlas_service_ready_release_total",
    "atlas_service.atlas_service_potential_private_service_elide_total",
    "atlas_service.atlas_service_active_entries_total",
    "atlas_service.atlas_service_release_pending_active_total",
    "atlas_service.atlas_service_atlas_obj_materialize_total",
    "atlas_service.atlas_service_atlas_obj_publicize_total",
    "atlas_service.atlas_service_atlas_obj_owner_form_total",
    "atlas_service.atlas_service_atlas_obj_ready_total",
    "atlas_service.atlas_service_atlas_obj_release_total",
    "atlas_service.atlas_service_atlas_obj_private_only_total",
    "atlas_service.atlas_service_private_only_share",
)

ROWIDX_METRICS: Tuple[str, ...] = (
    "noc_mem_joint.rowidx_touch_rows_total",
    "noc_mem_joint.rowidx_touch_events_total",
    "noc_mem_joint.rowidx_rows_filtered_cold_total",
    "noc_mem_joint.rowidx_rows_filtered_cold_rate",
    "noc_mem_joint.rowidx_prefetch_rows_total",
    "noc_mem_joint.rowidx_prefetch_bytes_total",
    "noc_mem_joint.rowidx_prefetch_complete_inflight_miss_total",
    "noc_mem_joint.rowidx_prefetch_complete_zero_waiters_total",
    "noc_mem_joint.rowidx_prefetch_complete_waiters_total",
    "noc_mem_joint.rowidx_prefetch_rows_deferred_total",
    "noc_mem_joint.rowidx_prefetch_rows_failed_total",
    "noc_mem_joint.rowidx_prefetch_coverage",
    "noc_mem_joint.rowidx_prefetch_bytes_per_row",
    "noc_mem_joint.rowidx_cache_hits_total",
    "noc_mem_joint.rowidx_cache_misses_total",
    "noc_mem_joint.rowidx_cache_hit_rate",
    "noc_mem_joint.rowidx_cache_fills_total",
    "noc_mem_joint.rowidx_cache_full_drop_total",
    "noc_mem_joint.rowidx_cache_entries_final",
    "noc_mem_joint.rowidx_ready_transition_apply_promote_cached_total",
    "noc_mem_joint.rowidx_ready_signal_rowindex_response_total",
    "noc_mem_joint.rowidx_ready_transition_rowindex_response_total",
    "noc_mem_joint.rowidx_ready_signal_prefetch_response_total",
    "noc_mem_joint.rowidx_ready_transition_prefetch_response_total",
    "noc_mem_joint.rowidx_ready_signal_rowindex_response_inflight_waiters_total",
    "noc_mem_joint.rowidx_ready_transition_rowindex_response_inflight_waiters_total",
    "noc_mem_joint.rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total",
    "noc_mem_joint.rowidx_ready_transition_rowindex_response_inflight_zero_waiters_total",
    "noc_mem_joint.rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total",
    "noc_mem_joint.rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total",
    "noc_mem_joint.rowidx_ready_signal_prefetch_response_inflight_waiters_total",
    "noc_mem_joint.rowidx_ready_transition_prefetch_response_inflight_waiters_total",
    "noc_mem_joint.rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total",
    "noc_mem_joint.rowidx_ready_transition_prefetch_response_inflight_zero_waiters_total",
    "noc_mem_joint.rowidx_ready_signal_prefetch_response_noninflight_prefetch_only_total",
    "noc_mem_joint.rowidx_ready_transition_prefetch_response_noninflight_prefetch_only_total",
    "noc_mem_joint.rowidx_ready_signal_generic_coalesced_response_total",
    "noc_mem_joint.rowidx_ready_transition_generic_coalesced_response_total",
    "noc_mem_joint.rowidx_bulk_fill_total",
    "noc_mem_joint.rowidx_bulk_rows_cached_total",
    "noc_mem_joint.rowidx_bulk_waiters_resolved_total",
    "noc_mem_joint.rowidx_ready_bypass_experimental_cache_hit_total",
    "noc_mem_joint.rowidx_ready_bypass_rowindex_get_hit_total",
    "noc_mem_joint.rowidx_close_attempt_total",
    "noc_mem_joint.rowidx_close_attempt_active_owner_total",
    "noc_mem_joint.rowidx_close_attempt_already_pending_total",
    "noc_mem_joint.rowidx_close_attempt_not_active_total",
    "noc_mem_joint.rowidx_close_attempt_not_owner_total",
    "noc_mem_joint.rowidx_budget_ticks_total",
    "noc_mem_joint.rowidx_budget_effective_total",
    "noc_mem_joint.rowidx_budget_effective_per_tick",
    "noc_mem_joint.rowidx_budget_adapt_ticks_total",
    "noc_mem_joint.rowidx_budget_adapt_tick_rate",
)

PULSE_PROXY_METRICS: Tuple[str, ...] = (
    "pulse.pulse_prebase_lookup_owner_fill_total",
    "pulse.pulse_prebase_lookup_shared_hits_total",
    "pulse.pulse_prebase_lookup_hit_ratio",
    "pulse.pulse_descriptor_total",
    "pulse.pulse_shared_service_hits_total",
    "pulse.pulse_shared_service_misses_total",
    "pulse.pulse_shared_service_hit_rate",
)

ATLAS_PROXY_METRICS: Tuple[str, ...] = (
    "atlas_proxy.idx2row.materialize_total",
    "atlas_proxy.idx2row.publicize_total",
    "atlas_proxy.idx2row.owner_form_total",
    "atlas_proxy.idx2row.ready_total",
    "atlas_proxy.idx2row.release_total",
    "atlas_proxy.premphf_base.materialize_total",
    "atlas_proxy.premphf_base.shared_hit_total",
    "atlas_proxy.premphf_base.proxy_only_gap_total",
    "atlas_proxy.premphf_band.materialize_total",
    "atlas_proxy.premphf_band.zero_service_total",
    "atlas_proxy.rowindex.materialize_total",
    "atlas_proxy.rowindex.ready_total",
)

ATLAS_LOOKUP_METRICS: Tuple[str, ...] = (
    "atlas_lookup.premphf_base.runtime_owner_fill_total",
    "atlas_lookup.premphf_base.runtime_shared_hit_total",
    "atlas_lookup.premphf_base.runtime_activity_total",
    "atlas_lookup.premphf_base.runtime_to_lookup_ready_gap_total",
    "atlas_lookup.premphf_base.runtime_to_materialize_gap_total",
)

ATLAS_SHADOW_METRICS: Tuple[str, ...] = (
    "atlas_shadow.rowindex.runtime_touch_rows_total",
    "atlas_shadow.rowindex.runtime_prefetch_rows_total",
    "atlas_shadow.rowindex.runtime_prefetch_rows_deferred_total",
    "atlas_shadow.rowindex.runtime_prefetch_rows_failed_total",
    "atlas_shadow.rowindex.runtime_cache_hits_total",
    "atlas_shadow.rowindex.runtime_cache_misses_total",
    "atlas_shadow.rowindex.runtime_cache_fills_total",
    "atlas_shadow.rowindex.runtime_cache_full_drop_total",
    "atlas_shadow.rowindex.runtime_ready_signal_generic_coalesced_response_total",
    "atlas_shadow.rowindex.runtime_ready_transition_generic_coalesced_response_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_signal_rowindex_response_inflight_waiters_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_transition_rowindex_response_inflight_waiters_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_transition_rowindex_response_inflight_zero_waiters_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_signal_prefetch_response_inflight_waiters_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_transition_prefetch_response_inflight_waiters_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_transition_prefetch_response_inflight_zero_waiters_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_signal_prefetch_response_noninflight_prefetch_only_total",
    "atlas_shadow.rowindex.runtime_rowidx_ready_transition_prefetch_response_noninflight_prefetch_only_total",
    "atlas_shadow.rowindex.runtime_bulk_fill_total",
    "atlas_shadow.rowindex.runtime_bulk_rows_cached_total",
    "atlas_shadow.rowindex.runtime_bulk_waiters_resolved_total",
    "atlas_shadow.rowindex.runtime_shadow_activity_total",
    "atlas_shadow.rowindex.runtime_shadow_to_materialize_gap_total",
    "atlas_shadow.rowindex.runtime_prefetch_coverage",
    "atlas_shadow.rowindex.runtime_cache_hit_rate",
)

ATLAS_CONTROL_METRICS: Tuple[str, ...] = (
    "atlas_control.messages_enqueued_total",
    "atlas_control.entries_peak",
    "atlas_control.backlog_cycles_total",
    "atlas_control.ready_fanout_total",
)

ATLAS_MACHINE_FACET_METRICS: Tuple[str, ...] = (
    "atlas_fabric.ingress_packets_total",
    "atlas_fabric.control_messages_enqueued_total",
    "atlas_storage.idx_reads_total",
    "atlas_storage.idx_bank_conflict_ticks_total",
    "atlas_storage.l0_reads_total",
    "atlas_storage.l0_fill_total",
    "atlas_sync.retire_ready_but_blocked_edges_total",
    "atlas_sync.retire_wait_cycles_total",
    "atlas_sync.retire_wait_cycles_due_to_barrier_total",
)

ATLAS_STORAGE_OBJECT_PLANE_METRICS: Tuple[str, ...] = (
    "atlas_storage.pod_metadata_observe_total",
    "atlas_storage.pod_metadata_overlap_hit_total",
    "atlas_storage.pod_metadata.premphf_base.observe_total",
    "atlas_storage.pod_metadata.premphf_band.observe_total",
    "atlas_storage.pod_metadata.rowindex.observe_total",
    "atlas_storage.pod_owner_owner_alloc_total",
    "atlas_storage.pod_owner_join_grant_total",
    "atlas_storage.pod_owner.premphf_band.owner_alloc_total",
    "atlas_storage.pod_owner.rowindex.join_grant_total",
)

ATLAS_OBJECT_LIFECYCLE_METRICS: Tuple[str, ...] = (
    "atlas_object_lifecycle.metadata_unique_object_total",
    "atlas_object_lifecycle.owner_alloc_total",
    "atlas_object_lifecycle.service_owner_form_total",
    "atlas_object_lifecycle.service_ready_total",
    "atlas_object_lifecycle.service_release_total",
    "atlas_object_lifecycle.unique_to_owner_gap_total",
    "atlas_object_lifecycle.owner_to_service_gap_total",
    "atlas_object_lifecycle.service_to_ready_gap_total",
    "atlas_object_lifecycle.ready_to_release_gap_total",
    "atlas_object_lifecycle.premphf_band.metadata_duplicate_consumer_total",
    "atlas_object_lifecycle.premphf_band.metadata_active_entries_peak_total",
    "atlas_object_lifecycle.premphf_band.owner_reject_total",
    "atlas_object_lifecycle.premphf_band.join_request_total",
    "atlas_object_lifecycle.premphf_band.join_grant_total",
    "atlas_object_lifecycle.premphf_band.join_reject_total",
    "atlas_object_lifecycle.premphf_band.owner_active_entries_peak_total",
    "atlas_object_lifecycle.premphf_band.metadata_to_owner_gap_total",
    "atlas_object_lifecycle.premphf_band.join_request_to_grant_gap_total",
    "atlas_object_lifecycle.rowindex.metadata_duplicate_consumer_total",
    "atlas_object_lifecycle.rowindex.metadata_active_entries_peak_total",
    "atlas_object_lifecycle.rowindex.owner_reject_total",
    "atlas_object_lifecycle.rowindex.join_request_total",
    "atlas_object_lifecycle.rowindex.join_grant_total",
    "atlas_object_lifecycle.rowindex.join_reject_total",
    "atlas_object_lifecycle.rowindex.owner_active_entries_peak_total",
    "atlas_object_lifecycle.rowindex.metadata_to_owner_gap_total",
    "atlas_object_lifecycle.rowindex.join_request_to_grant_gap_total",
)

DERIVED_PROXY_SHADOW_METRICS: Tuple[str, ...] = (
    "derived.proxy_shadow.service_materialize_total",
    "derived.proxy_shadow.service_ready_total",
    "derived.proxy_shadow.service_release_total",
    "derived.proxy_shadow.prebase_proxy_activity_total",
    "derived.proxy_shadow.descriptor_proxy_activity_total",
    "derived.proxy_shadow.rowindex_shadow_activity_total",
    "derived.proxy_shadow.prebase_proxy_to_materialize_gap",
    "derived.proxy_shadow.descriptor_proxy_to_materialize_gap",
    "derived.proxy_shadow.rowindex_shadow_to_materialize_gap",
)

DERIVED_MACHINE_METRICS: Tuple[str, ...] = (
    "derived.machine.lookup_activity_total",
    "derived.machine.shadow_activity_total",
    "derived.machine.control_activity_total",
    "derived.machine.proxy_lifecycle_total",
    "derived.machine.activity_plane_gap_total",
    "derived.machine.lookup_materialize_gap_total",
    "derived.machine.shadow_materialize_gap_total",
    "derived.machine.proxy_activity_total",
    "derived.machine.fabric_control_per_ingress",
    "derived.machine.storage_conflict_per_read",
    "derived.machine.sync_barrier_wait_share",
)

DERIVED_GATE_METRICS: Tuple[str, ...] = (
    "derived.gate.primary_gate",
    "derived.gate.gate_tags",
    "derived.gate.control_state",
    "derived.gate.sync_state",
    "derived.gate.shared_weight_absent_reason",
    "derived.gate.machine_break_label",
    "derived.gate.machine_break_stage",
    "derived.gate.constructed_plane_count",
    "derived.gate.constructed_planes",
    "derived.gate.formalized_non_storage_objects_count",
    "derived.gate.formalized_non_storage_objects",
    "derived.gate.unresolved_binding_objects_count",
    "derived.gate.unresolved_binding_objects",
    "derived.gate.m2c_entry_ready",
    "derived.gate.m2c_blockers_count",
    "derived.gate.m2c_blockers",
)

ROWINDEX_DIAG_METRICS: Tuple[str, ...] = (
    "atlas_activation_census.activation_gate.rowindex_requested.total",
    "atlas_activation_census.enable_state.rowindex_effective.total",
    "atlas_activation_census.activation_gate.rowindex_constructed.total",
    "atlas_activation_census.enable_state.rowindex_gate_pulse_osa.total",
    "atlas_activation_census.enable_state.rowindex_gate_metadata_txn.total",
    "atlas_activation_census.enable_state.rowindex_gate_metadata_mask.total",
    "atlas_activation_census.enable_state.rowindex_gate_pod_enable.total",
    "atlas_activation_census.enable_state.rowindex_gate_pod_metadata_enable.total",
    "atlas_activation_census.enable_state.rowindex_gate_pod_owner_enable.total",
    "atlas_activation_census.enable_state.rowindex_gate_service_table_present.total",
    "atlas_surface_probe_ledger.entries.rowindex_object.effective_gap",
    "atlas_surface_probe_ledger.entries.rowindex_object.effective_gap_cause",
    "atlas_surface_probe_backlog.entries.rowindex_object.action",
    "atlas_surface_probe_backlog.entries.rowindex_object.priority",
    "atlas_surface_probe_ledger.entries.rowindex_object.effective_gap_blocked_gates_count",
    "atlas_surface_probe_backlog.entries.rowindex_object.target_probe_count",
)

ROWINDEX_OBJECT_CLOSURE_METRICS: Tuple[str, ...] = (
    "atlas_object_closure.entries.rowindex_object.requested.total",
    "atlas_object_closure.entries.rowindex_object.constructed.total",
    "atlas_object_closure.entries.rowindex_object.effective.total",
    "atlas_object_closure.entries.rowindex_object.coverage_status",
    "atlas_object_closure.entries.rowindex_object.machine_reason",
    "atlas_object_closure.entries.rowindex_object.contract_phase_state",
    "atlas_object_closure.entries.rowindex_object.probe_status",
    "atlas_object_closure.entries.rowindex_object.zero_probe_cause",
    "atlas_object_closure.entries.rowindex_object.effective_gap",
    "atlas_object_closure.entries.rowindex_object.effective_gap_cause",
    "atlas_object_closure.entries.rowindex_object.blocked_gates_count",
)

IDX2_PREBAND_OBJECT_CLOSURE_METRICS: Tuple[str, ...] = (
    "atlas_object_closure.entries.idx2_object.requested.total",
    "atlas_object_closure.entries.idx2_object.constructed.total",
    "atlas_object_closure.entries.idx2_object.effective.total",
    "atlas_object_closure.entries.idx2_object.coverage_status",
    "atlas_object_closure.entries.idx2_object.machine_reason",
    "atlas_object_closure.entries.idx2_object.contract_phase_state",
    "atlas_object_closure.entries.idx2_object.probe_status",
    "atlas_object_closure.entries.idx2_object.zero_probe_cause",
    "atlas_object_closure.entries.idx2_object.effective_gap",
    "atlas_object_closure.entries.idx2_object.effective_gap_cause",
    "atlas_object_closure.entries.idx2_object.blocked_gates_count",
    "atlas_object_closure.entries.preband_object.requested.total",
    "atlas_object_closure.entries.preband_object.constructed.total",
    "atlas_object_closure.entries.preband_object.effective.total",
    "atlas_object_closure.entries.preband_object.coverage_status",
    "atlas_object_closure.entries.preband_object.machine_reason",
    "atlas_object_closure.entries.preband_object.contract_phase_state",
    "atlas_object_closure.entries.preband_object.probe_status",
    "atlas_object_closure.entries.preband_object.zero_probe_cause",
    "atlas_object_closure.entries.preband_object.effective_gap",
    "atlas_object_closure.entries.preband_object.effective_gap_cause",
    "atlas_object_closure.entries.preband_object.blocked_gates_count",
)

ATLAS_STORAGE_AUTHORITY_METRICS: Tuple[str, ...] = (
    "atlas_storage_authority_map.entries.shared_weight_residency.authority_state",
    "atlas_storage_authority_map.entries.shared_weight_residency.lifecycle_stage",
    "atlas_storage_authority_map.entries.shared_weight_residency.formal_object_ref",
)

ATLAS_WMS_STORAGE_BINDING_METRICS: Tuple[str, ...] = (
    "atlas_wms_storage_binding_map.entries.weight_idx_store.formalization_state",
    "atlas_wms_storage_binding_map.entries.shared_weight_residency.binding_state",
    "atlas_wms_storage_binding_map.entries.shared_weight_residency.runtime_owner",
    "atlas_wms_storage_binding_map.entries.shared_weight_residency.physical_scope",
    "atlas_wms_storage_binding_map.entries.shared_weight_residency.evict_contract_state",
    "atlas_wms_storage_binding_map.entries.weight_value_store.binding_state",
    "atlas_wms_storage_binding_map.entries.weight_value_store.semantic_overlay_owner",
    "atlas_wms_storage_binding_map.entries.weight_value_store.release_contract_state",
)

ATLAS_CONTROL_BINDING_METRICS: Tuple[str, ...] = (
    "atlas_control_binding_map.entries.rowdescriptor.formalization_state",
    "atlas_control_binding_map.entries.rowdescriptor.object_role",
    "atlas_control_binding_map.entries.activation_ingress_store.runtime_owner",
    "atlas_control_binding_map.entries.activation_ingress_store.formalization_state",
    "atlas_control_binding_map.entries.sync_barrier.commit_relation",
    "atlas_control_binding_map.entries.sync_barrier.formalization_state",
)

ATLAS_SCHEMA_REGISTRY_METRICS: Tuple[str, ...] = (
    "atlas_schema_registry.version",
    "atlas_schema_registry.vocabulary",
    "atlas_schema_registry.views.atlas_object_closure.vocabulary",
    "atlas_schema_registry.views.atlas_wms_storage_binding_map.vocabulary",
    "atlas_schema_registry.views.atlas_control_binding_map.vocabulary",
)

ATLAS_BINDING_UNRESOLVED_METRICS: Tuple[str, ...] = (
    "atlas_binding_unresolved_ledger.entries.weight_value_store.formalization_state",
    "atlas_binding_unresolved_ledger.entries.weight_value_store.unresolved_edges_count",
    "atlas_binding_unresolved_ledger.entries.shared_weight_residency.formalization_state",
    "atlas_binding_unresolved_ledger.entries.shared_weight_residency.unresolved_edges_count",
)


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _get_path(data: Dict[str, Any], dotted: str) -> Any:
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _first_present(data: Dict[str, Any], *dotted_paths: str) -> Any:
    for dotted in dotted_paths:
        value = _get_path(data, dotted)
        if value is not None:
            return value
    return None


def _read_validation_counts(run_dir: Path) -> Dict[str, int]:
    fail = 0
    warn = 0
    strict = 0
    log_path = run_dir / "validation.log"
    if not log_path.exists():
        return {"fail": fail, "warn": warn, "strict": strict}
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = VALIDATION_RE.search(line)
        if match:
            fail = int(match.group(1))
            warn = int(match.group(2))
            strict = int(match.group(3) or 0)
    return {"fail": fail, "warn": warn, "strict": strict}


def _load_cases(path: Path) -> Tuple[str, str, List[Dict[str, str]]]:
    payload = _read_json(path)
    return (
        str(payload.get("experiment_id", path.parent.name)),
        str(payload.get("baseline_case", "")),
        list(payload.get("cases", [])),
    )


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_run_dir(cases_path: Path, case: Dict[str, Any]) -> Path:
    return (cases_path.parent / str(case.get("run_dir", ""))).resolve()


def _refresh_run_artifacts(run_dir: Path, project_root: Path) -> None:
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


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _existing_float(data: Dict[str, Any], *dotted_paths: str) -> tuple[bool, float]:
    value = _first_present(data, *dotted_paths)
    if value is None:
        return False, 0.0
    return True, _as_float(value)


def _csv_join(items: Sequence[str]) -> str:
    if not items:
        return "none"
    return ",".join(str(item) for item in items)


def _derive_gate_case(summary: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    gate_tags: List[str] = []
    blockers: List[str] = []

    def _append_tag(tag: str) -> None:
        if tag not in gate_tags:
            gate_tags.append(tag)

    def _append_blocker(blocker: str) -> None:
        if blocker not in blockers:
            blockers.append(blocker)

    required_views = [
        "atlas_object_closure",
        "atlas_storage_authority_map",
        "atlas_wms_storage_binding_map",
        "atlas_binding_unresolved_ledger",
        "atlas_control_binding_map",
    ]
    missing_schema_views = [
        view
        for view in required_views
        if not _get_path(summary, f"atlas_schema_registry.views.{view}.vocabulary")
    ]

    constructed_planes: List[str] = []
    for plane, dotted in (
        ("pulse_fabric", "atlas_activation_census.activation_gate.pulse_fabric_constructed.total"),
        ("service_table", "atlas_activation_census.activation_gate.service_table_constructed.total"),
        ("pod_metadata_plane", "atlas_activation_census.activation_gate.pod_metadata_plane_constructed.total"),
        ("pod_owner_table", "atlas_activation_census.activation_gate.pod_owner_table_constructed.total"),
        ("shared_weight_plane", "atlas_activation_census.activation_gate.shared_weight_plane_constructed.total"),
    ):
        if _as_float(_get_path(summary, dotted)) > 0.0:
            constructed_planes.append(plane)

    contract_state = str(
        _first_present(
            summary,
            "atlas_control_commit_view.contract_state",
            "contract_mismatch.sync.state",
        )
        or "unknown"
    )
    control_contract_state = str(
        _first_present(
            summary,
            "atlas_control_commit_view.control_contract_state",
        )
        or contract_state
    )
    sync_contract_state = str(
        _first_present(
            summary,
            "atlas_control_commit_view.sync_contract_state",
        )
        or contract_state
    )
    control_state = str(
        _first_present(
            summary,
            "atlas_control_commit_view.control_state",
            "contract_mismatch.control_runtime.state",
        )
        or "unknown"
    )
    sync_state = str(
        _first_present(
            summary,
            "atlas_control_commit_view.sync_state",
            "contract_mismatch.sync.state",
        )
        or "unknown"
    )
    if control_state == "fabric_absent" or control_contract_state == "fabric_absent":
        _append_tag("fabric_absent")

    rowindex_coverage = str(
        _get_path(summary, "atlas_object_closure.entries.rowindex_object.coverage_status")
        or "unknown"
    )
    if rowindex_coverage == "object_and_runtime_visible":
        _append_tag("rowindex_object_template_branch")

    shared_weight_binding_state = str(
        _get_path(
            summary,
            "atlas_wms_storage_binding_map.entries.shared_weight_residency.binding_state",
        )
        or "absent"
    )
    shared_weight_absent_reason = str(
        _first_present(
            summary,
            "atlas_activation_census.shared_weight.dominant_absent_reason.label",
        )
        or "none"
    )
    machine_break_label = str(
        _get_path(summary, "atlas_activation_census.machine_chain.dominant_break.label")
        or "none"
    )
    machine_break_stage = str(
        _get_path(summary, "atlas_activation_census.machine_chain.dominant_break.stage")
        or "none"
    )
    if shared_weight_binding_state == "semantic_overlay_only":
        _append_tag("shared_weight_semantic_overlay_only")
    elif shared_weight_binding_state == "absent" and shared_weight_absent_reason not in {
        "",
        "none",
        "unknown",
        "null",
    }:
        _append_tag(f"shared_weight_absent_{shared_weight_absent_reason}")

    unresolved_binding_objects: List[str] = []
    unresolved_entries = _get_path(summary, "atlas_binding_unresolved_ledger.entries")
    if isinstance(unresolved_entries, dict):
        for name, payload in unresolved_entries.items():
            if not isinstance(payload, dict):
                continue
            if int(_as_float(payload.get("unresolved_edges_count"))) > 0:
                unresolved_binding_objects.append(str(name))
    if unresolved_binding_objects:
        _append_tag("binding_unresolved_present")

    formalized_non_storage_objects: List[str] = []
    control_entries = _get_path(summary, "atlas_control_binding_map.entries")
    if isinstance(control_entries, dict):
        for name, payload in control_entries.items():
            if not isinstance(payload, dict):
                continue
            state = str(payload.get("formalization_state") or "unknown")
            if state.endswith("_visible"):
                formalized_non_storage_objects.append(str(name))

    for view in missing_schema_views:
        _append_blocker(f"missing_schema_view:{view}")
    if not gate_tags:
        _append_blocker("canonical_gate_absent")
    if unresolved_binding_objects:
        _append_blocker("binding_unresolved_present")
    if "shared_weight_absent_owner_request_gate" in gate_tags:
        _append_blocker("shared_weight_absent_owner_request_gate")

    if control_state == "fabric_absent" or control_contract_state == "fabric_absent":
        _append_blocker("fabric_absent")
    elif control_state not in {"aligned_active", "unknown", "clean"}:
        _append_blocker(f"control_state_{control_state}")

    if sync_state not in {"clean", "unknown"}:
        _append_blocker(f"sync_state_{sync_state}")

    primary_gate = gate_tags[0] if gate_tags else "unknown"
    return {
        "case_id": case_id,
        "primary_gate": primary_gate,
        "gate_tags": gate_tags,
        "control_state": control_state,
        "sync_state": sync_state,
        "shared_weight_absent_reason": shared_weight_absent_reason,
        "machine_break_label": machine_break_label,
        "machine_break_stage": machine_break_stage,
        "constructed_planes": constructed_planes,
        "formalized_non_storage_objects": formalized_non_storage_objects,
        "unresolved_binding_objects": unresolved_binding_objects,
        "missing_schema_views": missing_schema_views,
        "m2c_entry_ready": len(blockers) == 0,
        "m2c_blockers": blockers,
    }


def _collect_case_metrics(run_dir: Path) -> Dict[str, Any]:
    summary = _read_json(run_dir / "essential_summary_mesh.json")
    validation = _read_validation_counts(run_dir)

    values: Dict[str, Any] = {
        "validation.fail": validation["fail"],
        "validation.warn": validation["warn"],
        "validation.strict": validation["strict"],
    }
    for metric in MAINLINE_METRICS[3:]:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_SERVICE_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ROWIDX_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in PULSE_PROXY_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_PROXY_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_LOOKUP_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_SHADOW_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_CONTROL_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_MACHINE_FACET_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_STORAGE_OBJECT_PLANE_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value

    for metric in ATLAS_OBJECT_LIFECYCLE_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ROWINDEX_DIAG_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ROWINDEX_OBJECT_CLOSURE_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in IDX2_PREBAND_OBJECT_CLOSURE_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_STORAGE_AUTHORITY_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_WMS_STORAGE_BINDING_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_CONTROL_BINDING_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_SCHEMA_REGISTRY_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    for metric in ATLAS_BINDING_UNRESOLVED_METRICS:
        value = _get_path(summary, metric)
        values[metric] = 0 if value is None else value
    blocked_gates = _get_path(
        summary,
        "atlas_surface_probe_ledger.entries.rowindex_object.effective_gap_blocked_gates",
    )
    values["atlas_surface_probe_ledger.entries.rowindex_object.effective_gap_blocked_gates_count"] = (
        len(blocked_gates) if isinstance(blocked_gates, list) else 0
    )
    target_probe = _get_path(
        summary,
        "atlas_surface_probe_backlog.entries.rowindex_object.target_probe",
    )
    values["atlas_surface_probe_backlog.entries.rowindex_object.target_probe_count"] = (
        len(target_probe) if isinstance(target_probe, list) else 0
    )
    closure_blocked_gates = _get_path(
        summary,
        "atlas_object_closure.entries.rowindex_object.blocked_gates",
    )
    values["atlas_object_closure.entries.rowindex_object.blocked_gates_count"] = (
        len(closure_blocked_gates) if isinstance(closure_blocked_gates, list) else 0
    )
    for surface in ("idx2_object", "preband_object"):
        closure_blocked_gates = _get_path(
            summary,
            f"atlas_object_closure.entries.{surface}.blocked_gates",
        )
        values[f"atlas_object_closure.entries.{surface}.blocked_gates_count"] = (
            len(closure_blocked_gates) if isinstance(closure_blocked_gates, list) else 0
        )

    materialize_total = _as_float(
        values.get("atlas_service.atlas_service_atlas_obj_materialize_total", 0)
    )
    ready_total = _as_float(values.get("atlas_service.atlas_service_atlas_obj_ready_total", 0))
    release_total = _as_float(values.get("atlas_service.atlas_service_atlas_obj_release_total", 0))
    prebase_proxy_activity_total = _as_float(
        values.get("pulse.pulse_prebase_lookup_owner_fill_total", 0)
    ) + _as_float(values.get("pulse.pulse_prebase_lookup_shared_hits_total", 0))
    descriptor_proxy_activity_total = _as_float(values.get("pulse.pulse_descriptor_total", 0))
    rowindex_shadow_activity_total = _as_float(
        values.get("noc_mem_joint.rowidx_touch_rows_total", 0)
    )

    values["derived.proxy_shadow.service_materialize_total"] = materialize_total
    values["derived.proxy_shadow.service_ready_total"] = ready_total
    values["derived.proxy_shadow.service_release_total"] = release_total
    values["derived.proxy_shadow.prebase_proxy_activity_total"] = prebase_proxy_activity_total
    values["derived.proxy_shadow.descriptor_proxy_activity_total"] = descriptor_proxy_activity_total
    values["derived.proxy_shadow.rowindex_shadow_activity_total"] = rowindex_shadow_activity_total
    values["derived.proxy_shadow.prebase_proxy_to_materialize_gap"] = (
        prebase_proxy_activity_total - materialize_total
    )
    values["derived.proxy_shadow.descriptor_proxy_to_materialize_gap"] = (
        descriptor_proxy_activity_total - materialize_total
    )
    values["derived.proxy_shadow.rowindex_shadow_to_materialize_gap"] = (
        rowindex_shadow_activity_total - materialize_total
    )

    atlas_lookup_owner_fill_total = _as_float(
        _first_present(
            summary,
            "atlas_lookup.premphf_base.runtime_owner_fill_total",
            "pulse.pulse_prebase_lookup_owner_fill_total",
        )
    )
    atlas_lookup_shared_hit_total = _as_float(
        _first_present(
            summary,
            "atlas_lookup.premphf_base.runtime_shared_hit_total",
            "pulse.pulse_prebase_lookup_shared_hits_total",
        )
    )
    atlas_lookup_activity_total = _as_float(
        _first_present(
            summary,
            "atlas_lookup.premphf_base.runtime_activity_total",
        )
    )
    if atlas_lookup_activity_total <= 0.0:
        atlas_lookup_activity_total = atlas_lookup_owner_fill_total + atlas_lookup_shared_hit_total
    values["atlas_lookup.premphf_base.runtime_owner_fill_total"] = atlas_lookup_owner_fill_total
    values["atlas_lookup.premphf_base.runtime_shared_hit_total"] = atlas_lookup_shared_hit_total
    values["atlas_lookup.premphf_base.runtime_activity_total"] = atlas_lookup_activity_total
    atlas_lookup_ready_total = _as_float(
        _first_present(
            summary,
            "atlas_lookup.premphf_base.lookup_ready_total",
            "atlas_proxy.premphf_base.lookup_ready_total",
        )
    )
    atlas_lookup_materialize_total = _as_float(
        _first_present(
            summary,
            "atlas_lookup.premphf_base.materialize_total",
            "atlas_proxy.premphf_base.materialize_total",
        )
    )
    found_lookup_ready_gap, lookup_ready_gap_value = _existing_float(
        summary,
        "atlas_lookup.premphf_base.runtime_to_lookup_ready_gap_total",
    )
    values["atlas_lookup.premphf_base.runtime_to_lookup_ready_gap_total"] = (
        lookup_ready_gap_value
        if found_lookup_ready_gap
        else (atlas_lookup_activity_total - atlas_lookup_ready_total)
    )
    found_lookup_materialize_gap, lookup_materialize_gap_value = _existing_float(
        summary,
        "atlas_lookup.premphf_base.runtime_to_materialize_gap_total",
    )
    values["atlas_lookup.premphf_base.runtime_to_materialize_gap_total"] = (
        lookup_materialize_gap_value
        if found_lookup_materialize_gap
        else (atlas_lookup_activity_total - atlas_lookup_materialize_total)
    )

    atlas_shadow_touch_total = _as_float(
        _first_present(
            summary,
            "atlas_shadow.rowindex.runtime_touch_rows_total",
            "noc_mem_joint.rowidx_touch_rows_total",
        )
    )
    atlas_shadow_prefetch_total = _as_float(
        _first_present(
            summary,
            "atlas_shadow.rowindex.runtime_prefetch_rows_total",
            "noc_mem_joint.rowidx_prefetch_rows_total",
        )
    )
    atlas_shadow_prefetch_deferred_total = _as_float(
        _first_present(
            summary,
            "atlas_shadow.rowindex.runtime_prefetch_rows_deferred_total",
            "noc_mem_joint.rowidx_prefetch_rows_deferred_total",
        )
    )
    atlas_shadow_prefetch_failed_total = _as_float(
        _first_present(
            summary,
            "atlas_shadow.rowindex.runtime_prefetch_rows_failed_total",
            "noc_mem_joint.rowidx_prefetch_rows_failed_total",
        )
    )
    atlas_shadow_cache_hits_total = _as_float(
        _first_present(
            summary,
            "atlas_shadow.rowindex.runtime_cache_hits_total",
            "noc_mem_joint.rowidx_cache_hits_total",
        )
    )
    atlas_shadow_cache_misses_total = _as_float(
        _first_present(
            summary,
            "atlas_shadow.rowindex.runtime_cache_misses_total",
            "noc_mem_joint.rowidx_cache_misses_total",
        )
    )
    atlas_shadow_cache_fills_total = _as_float(
        _first_present(
            summary,
            "atlas_shadow.rowindex.runtime_cache_fills_total",
            "noc_mem_joint.rowidx_cache_fills_total",
        )
    )
    atlas_shadow_cache_full_drop_total = _as_float(
        _first_present(
            summary,
            "atlas_shadow.rowindex.runtime_cache_full_drop_total",
            "noc_mem_joint.rowidx_cache_full_drop_total",
        )
    )
    atlas_shadow_activity_total = _as_float(
        _first_present(
            summary,
            "atlas_shadow.rowindex.runtime_shadow_activity_total",
        )
    )
    if atlas_shadow_activity_total <= 0.0:
        atlas_shadow_activity_total = atlas_shadow_touch_total
    values["atlas_shadow.rowindex.runtime_touch_rows_total"] = atlas_shadow_touch_total
    values["atlas_shadow.rowindex.runtime_prefetch_rows_total"] = atlas_shadow_prefetch_total
    values["atlas_shadow.rowindex.runtime_prefetch_rows_deferred_total"] = atlas_shadow_prefetch_deferred_total
    values["atlas_shadow.rowindex.runtime_prefetch_rows_failed_total"] = atlas_shadow_prefetch_failed_total
    values["atlas_shadow.rowindex.runtime_cache_hits_total"] = atlas_shadow_cache_hits_total
    values["atlas_shadow.rowindex.runtime_cache_misses_total"] = atlas_shadow_cache_misses_total
    values["atlas_shadow.rowindex.runtime_cache_fills_total"] = atlas_shadow_cache_fills_total
    values["atlas_shadow.rowindex.runtime_cache_full_drop_total"] = atlas_shadow_cache_full_drop_total
    values["atlas_shadow.rowindex.runtime_shadow_activity_total"] = atlas_shadow_activity_total
    atlas_shadow_materialize_total = _as_float(
        _first_present(
            summary,
            "atlas_shadow.rowindex.materialize_total",
            "atlas_proxy.rowindex.materialize_total",
        )
    )
    found_shadow_materialize_gap, shadow_materialize_gap_value = _existing_float(
        summary,
        "atlas_shadow.rowindex.runtime_shadow_to_materialize_gap_total",
    )
    values["atlas_shadow.rowindex.runtime_shadow_to_materialize_gap_total"] = (
        shadow_materialize_gap_value
        if found_shadow_materialize_gap
        else (atlas_shadow_activity_total - atlas_shadow_materialize_total)
    )
    found_shadow_prefetch_coverage, shadow_prefetch_coverage_value = _existing_float(
        summary,
        "atlas_shadow.rowindex.runtime_prefetch_coverage",
    )
    values["atlas_shadow.rowindex.runtime_prefetch_coverage"] = (
        shadow_prefetch_coverage_value
        if found_shadow_prefetch_coverage
        else (
            (atlas_shadow_prefetch_total / atlas_shadow_touch_total)
            if atlas_shadow_touch_total > 0.0
            else 0.0
        )
    )
    found_shadow_cache_hit_rate, shadow_cache_hit_rate_value = _existing_float(
        summary,
        "atlas_shadow.rowindex.runtime_cache_hit_rate",
    )
    values["atlas_shadow.rowindex.runtime_cache_hit_rate"] = (
        shadow_cache_hit_rate_value
        if found_shadow_cache_hit_rate
        else (
            (atlas_shadow_cache_hits_total / (atlas_shadow_cache_hits_total + atlas_shadow_cache_misses_total))
            if (atlas_shadow_cache_hits_total + atlas_shadow_cache_misses_total) > 0.0
            else 0.0
        )
    )

    atlas_control_messages_total = _as_float(
        _first_present(
            summary,
            "atlas_control.messages_enqueued_total",
            "atlas_fabric.control_messages_enqueued_total",
            "pulse.pulse_control_messages_enqueued_total",
        )
    )
    atlas_control_ready_fanout_total = _as_float(
        _first_present(
            summary,
            "atlas_control.ready_fanout_total",
            "atlas_fabric.control_ready_fanout_total",
            "pulse.pulse_control_ready_fanout_total",
        )
    )
    atlas_control_entries_peak = _as_float(
        _first_present(
            summary,
            "atlas_control.entries_peak",
            "pulse.pulse_control_entries_peak",
        )
    )
    atlas_control_backlog_cycles_total = _as_float(
        _first_present(
            summary,
            "atlas_control.backlog_cycles_total",
            "pulse.pulse_control_backlog_cycles_total",
        )
    )
    values["atlas_control.messages_enqueued_total"] = atlas_control_messages_total
    values["atlas_control.entries_peak"] = atlas_control_entries_peak
    values["atlas_control.backlog_cycles_total"] = atlas_control_backlog_cycles_total
    values["atlas_control.ready_fanout_total"] = atlas_control_ready_fanout_total

    proxy_activity_total = (
        _as_float(values.get("atlas_proxy.idx2row.materialize_total", 0)) +
        _as_float(values.get("atlas_proxy.premphf_base.shared_hit_total", 0)) +
        _as_float(values.get("atlas_proxy.rowindex.materialize_total", 0))
    )
    ingress_packets_total = _as_float(
        values.get("atlas_fabric.ingress_packets_total", 0)
    )
    control_messages_total = _as_float(
        values.get("atlas_fabric.control_messages_enqueued_total", 0)
    )
    idx_reads_total = _as_float(values.get("atlas_storage.idx_reads_total", 0))
    idx_conflict_total = _as_float(
        values.get("atlas_storage.idx_bank_conflict_ticks_total", 0)
    )
    l0_reads_total = _as_float(values.get("atlas_storage.l0_reads_total", 0))
    retire_wait_total = _as_float(values.get("atlas_sync.retire_wait_cycles_total", 0))
    barrier_wait_total = _as_float(
        values.get("atlas_sync.retire_wait_cycles_due_to_barrier_total", 0)
    )
    proxy_lifecycle_total = (
        _as_float(values.get("atlas_proxy.idx2row.materialize_total", 0)) +
        _as_float(values.get("atlas_proxy.idx2row.ready_total", 0)) +
        _as_float(values.get("atlas_proxy.idx2row.release_total", 0))
    )

    values["derived.machine.lookup_activity_total"] = atlas_lookup_activity_total
    values["derived.machine.shadow_activity_total"] = atlas_shadow_activity_total
    values["derived.machine.control_activity_total"] = atlas_control_messages_total
    values["derived.machine.proxy_lifecycle_total"] = proxy_lifecycle_total
    values["derived.machine.activity_plane_gap_total"] = (
        atlas_lookup_activity_total + atlas_shadow_activity_total - proxy_lifecycle_total
    )
    found_derived_lookup_gap, derived_lookup_gap_value = _existing_float(
        summary,
        "derived.machine.lookup_materialize_gap_total",
        "atlas_lookup.premphf_base.runtime_to_materialize_gap_total",
    )
    values["derived.machine.lookup_materialize_gap_total"] = (
        derived_lookup_gap_value
        if found_derived_lookup_gap
        else (atlas_lookup_activity_total - atlas_lookup_materialize_total)
    )
    found_derived_shadow_gap, derived_shadow_gap_value = _existing_float(
        summary,
        "derived.machine.shadow_materialize_gap_total",
        "atlas_shadow.rowindex.runtime_shadow_to_materialize_gap_total",
    )
    values["derived.machine.shadow_materialize_gap_total"] = (
        derived_shadow_gap_value
        if found_derived_shadow_gap
        else (atlas_shadow_activity_total - atlas_shadow_materialize_total)
    )
    values["derived.machine.proxy_activity_total"] = proxy_activity_total
    values["derived.machine.fabric_control_per_ingress"] = (
        (atlas_control_messages_total / ingress_packets_total)
        if ingress_packets_total > 0.0
        else 0.0
    )
    values["derived.machine.storage_conflict_per_read"] = (
        (idx_conflict_total / (idx_reads_total + l0_reads_total))
        if (idx_reads_total + l0_reads_total) > 0.0
        else 0.0
    )
    values["derived.machine.sync_barrier_wait_share"] = (
        (barrier_wait_total / retire_wait_total)
        if retire_wait_total > 0.0
        else 0.0
    )
    gate_case = _derive_gate_case(summary, run_dir.name)
    values["derived.gate.primary_gate"] = gate_case["primary_gate"]
    values["derived.gate.gate_tags"] = _csv_join(gate_case["gate_tags"])
    values["derived.gate.control_state"] = gate_case["control_state"]
    values["derived.gate.sync_state"] = gate_case["sync_state"]
    values["derived.gate.shared_weight_absent_reason"] = gate_case[
        "shared_weight_absent_reason"
    ]
    values["derived.gate.machine_break_label"] = gate_case["machine_break_label"]
    values["derived.gate.machine_break_stage"] = gate_case["machine_break_stage"]
    values["derived.gate.constructed_plane_count"] = len(
        gate_case["constructed_planes"]
    )
    values["derived.gate.constructed_planes"] = _csv_join(
        gate_case["constructed_planes"]
    )
    values["derived.gate.formalized_non_storage_objects_count"] = len(
        gate_case["formalized_non_storage_objects"]
    )
    values["derived.gate.formalized_non_storage_objects"] = _csv_join(
        gate_case["formalized_non_storage_objects"]
    )
    values["derived.gate.unresolved_binding_objects_count"] = len(
        gate_case["unresolved_binding_objects"]
    )
    values["derived.gate.unresolved_binding_objects"] = _csv_join(
        gate_case["unresolved_binding_objects"]
    )
    values["derived.gate.m2c_entry_ready"] = 1 if gate_case["m2c_entry_ready"] else 0
    values["derived.gate.m2c_blockers_count"] = len(gate_case["m2c_blockers"])
    values["derived.gate.m2c_blockers"] = _csv_join(gate_case["m2c_blockers"])
    values["__gate_case__"] = gate_case
    return values


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return "0"
    return str(value)


def _delta_value(base: Any, cand: Any) -> Any:
    try:
        if isinstance(base, int) and isinstance(cand, int):
            return cand - base
        return float(cand) - float(base)
    except Exception:
        return "na"


def _write_compare(
    out_path: Path,
    experiment_id: str,
    baseline_label: str,
    baseline_metrics: Dict[str, Any],
    candidate_rows: Sequence[Tuple[str, Dict[str, Any]]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = ["metric", "baseline"]
    for candidate_label, _ in candidate_rows:
        header.append(candidate_label)
        header.append(f"delta_vs_baseline__{candidate_label}")

    lines = [
        f"# experiment_id\t{experiment_id}",
        f"# baseline_case\t{baseline_label}",
        "# profile\tatlas_service_rowindex_object_ab_v1",
        "\t".join(header),
    ]
    ordered_metrics = (
        MAINLINE_METRICS
        + ATLAS_SERVICE_METRICS
        + ROWIDX_METRICS
        + PULSE_PROXY_METRICS
        + ATLAS_PROXY_METRICS
        + ATLAS_LOOKUP_METRICS
        + ATLAS_SHADOW_METRICS
        + ATLAS_CONTROL_METRICS
        + ATLAS_MACHINE_FACET_METRICS
        + ATLAS_STORAGE_OBJECT_PLANE_METRICS
        + ATLAS_OBJECT_LIFECYCLE_METRICS
        + DERIVED_PROXY_SHADOW_METRICS
        + DERIVED_MACHINE_METRICS
        + DERIVED_GATE_METRICS
        + ROWINDEX_DIAG_METRICS
        + ROWINDEX_OBJECT_CLOSURE_METRICS
        + IDX2_PREBAND_OBJECT_CLOSURE_METRICS
        + ATLAS_STORAGE_AUTHORITY_METRICS
        + ATLAS_WMS_STORAGE_BINDING_METRICS
        + ATLAS_CONTROL_BINDING_METRICS
        + ATLAS_SCHEMA_REGISTRY_METRICS
        + ATLAS_BINDING_UNRESOLVED_METRICS
    )
    for metric in ordered_metrics:
        base = baseline_metrics.get(metric, 0)
        row = [metric, _format_value(base)]
        for _, candidate_metrics in candidate_rows:
            cand = candidate_metrics.get(metric, 0)
            row.append(_format_value(cand))
            row.append(_format_value(_delta_value(base, cand)))
        lines.append("\t".join(row))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_gate_summary_tsv(
    out_path: Path,
    experiment_id: str,
    baseline_case: str,
    gate_cases: Sequence[Dict[str, Any]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "case_id",
        "primary_gate",
        "gate_tags",
        "control_state",
        "sync_state",
        "shared_weight_absent_reason",
        "machine_break_label",
        "machine_break_stage",
        "constructed_planes",
        "formalized_non_storage_objects",
        "unresolved_binding_objects",
        "m2c_entry_ready",
        "m2c_blockers",
    ]
    lines = [
        f"# experiment_id\t{experiment_id}",
        f"# baseline_case\t{baseline_case}",
        "# artifact\tcanonical_gate_suite",
        "\t".join(header),
    ]
    for gate_case in gate_cases:
        lines.append(
            "\t".join(
                [
                    str(gate_case.get("case_id", "")),
                    str(gate_case.get("primary_gate", "unknown")),
                    _csv_join(gate_case.get("gate_tags", [])),
                    str(gate_case.get("control_state", "unknown")),
                    str(gate_case.get("sync_state", "unknown")),
                    str(gate_case.get("shared_weight_absent_reason", "none")),
                    str(gate_case.get("machine_break_label", "none")),
                    str(gate_case.get("machine_break_stage", "none")),
                    _csv_join(gate_case.get("constructed_planes", [])),
                    _csv_join(gate_case.get("formalized_non_storage_objects", [])),
                    _csv_join(gate_case.get("unresolved_binding_objects", [])),
                    "1" if gate_case.get("m2c_entry_ready") else "0",
                    _csv_join(gate_case.get("m2c_blockers", [])),
                ]
            )
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_gate_summary_json(
    out_path: Path,
    experiment_id: str,
    baseline_case: str,
    gate_cases: Sequence[Dict[str, Any]],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment_id": experiment_id,
        "baseline_case": baseline_case,
        "artifact": "canonical_gate_suite",
        "cases": list(gate_cases),
    }
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--cases",
        default=str(Path(__file__).resolve().with_name("cases.json")),
        help="path to cases.json",
    )
    ap.add_argument(
        "--out",
        default=str(Path(__file__).resolve().with_name("snapshot") / "compare.tsv"),
        help="output compare.tsv path",
    )
    ap.add_argument(
        "--refresh-runs",
        action="store_true",
        help="rebuild essential summary, atlas activation trace, and validation log before snapshot",
    )
    args = ap.parse_args(argv)

    cases_path = Path(args.cases).resolve()
    out_path = Path(args.out).resolve()
    experiment_id, baseline_case_id, cases = _load_cases(cases_path)
    case_by_id = {str(case.get("id", "")): case for case in cases}
    if baseline_case_id not in case_by_id:
        raise SystemExit(f"baseline case not found: {baseline_case_id}")

    if args.refresh_runs:
        project_root = _project_root()
        for case in cases:
            _refresh_run_artifacts(_resolve_run_dir(cases_path, case), project_root)

    baseline_case = case_by_id[baseline_case_id]
    baseline_metrics = _collect_case_metrics(_resolve_run_dir(cases_path, baseline_case))
    baseline_gate = baseline_metrics.get("__gate_case__", {"case_id": baseline_case_id})
    baseline_gate["case_id"] = baseline_case_id

    candidate_rows: List[Tuple[str, Dict[str, Any]]] = []
    gate_cases: List[Dict[str, Any]] = [baseline_gate]
    for case in cases:
        case_id = str(case.get("id", ""))
        if case_id == baseline_case_id:
            continue
        candidate_metrics = _collect_case_metrics(_resolve_run_dir(cases_path, case))
        candidate_rows.append(
            (
                case_id,
                candidate_metrics,
            )
        )
        gate_case = candidate_metrics.get("__gate_case__", {"case_id": case_id})
        gate_case["case_id"] = case_id
        gate_cases.append(gate_case)

    _write_compare(
        out_path,
        experiment_id,
        baseline_case_id,
        baseline_metrics,
        candidate_rows,
    )
    _write_gate_summary_tsv(
        out_path.with_name("gate_summary.tsv"),
        experiment_id,
        baseline_case_id,
        gate_cases,
    )
    _write_gate_summary_json(
        out_path.with_name("gate_summary.json"),
        experiment_id,
        baseline_case_id,
        gate_cases,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
