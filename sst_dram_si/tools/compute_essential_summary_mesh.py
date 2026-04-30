#!/usr/bin/env python3
"""Compute a lightweight essential mesh summary directly from run artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


_ROWIDX_EXTRA_STAT_MAP = {
    "exp_noc_rowidx_ready_signal_rowindex_response_inflight_waiters_total":
        "rowidx_ready_signal_rowindex_response_inflight_waiters_total",
    "exp_noc_rowidx_ready_transition_rowindex_response_inflight_waiters_total":
        "rowidx_ready_transition_rowindex_response_inflight_waiters_total",
    "exp_noc_rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total":
        "rowidx_ready_signal_rowindex_response_inflight_zero_waiters_total",
    "exp_noc_rowidx_ready_transition_rowindex_response_inflight_zero_waiters_total":
        "rowidx_ready_transition_rowindex_response_inflight_zero_waiters_total",
    "exp_noc_rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total":
        "rowidx_ready_signal_rowindex_response_noninflight_prefetch_only_total",
    "exp_noc_rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total":
        "rowidx_ready_transition_rowindex_response_noninflight_prefetch_only_total",
    "exp_noc_rowidx_ready_signal_prefetch_response_inflight_waiters_total":
        "rowidx_ready_signal_prefetch_response_inflight_waiters_total",
    "exp_noc_rowidx_ready_transition_prefetch_response_inflight_waiters_total":
        "rowidx_ready_transition_prefetch_response_inflight_waiters_total",
    "exp_noc_rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total":
        "rowidx_ready_signal_prefetch_response_inflight_zero_waiters_total",
    "exp_noc_rowidx_ready_transition_prefetch_response_inflight_zero_waiters_total":
        "rowidx_ready_transition_prefetch_response_inflight_zero_waiters_total",
    "exp_noc_rowidx_ready_signal_prefetch_response_noninflight_prefetch_only_total":
        "rowidx_ready_signal_prefetch_response_noninflight_prefetch_only_total",
    "exp_noc_rowidx_ready_transition_prefetch_response_noninflight_prefetch_only_total":
        "rowidx_ready_transition_prefetch_response_noninflight_prefetch_only_total",
    "exp_noc_rowidx_prefetch_complete_inflight_miss_total":
        "rowidx_prefetch_complete_inflight_miss_total",
    "exp_noc_rowidx_prefetch_complete_waiters_total":
        "rowidx_prefetch_complete_waiters_total",
    "exp_noc_rowidx_prefetch_complete_zero_waiters_total":
        "rowidx_prefetch_complete_zero_waiters_total",
}

_IDX2_LOG_RE = re.compile(r"\[exp-idx2-prefetch\]\s+(.*)")
_PE_DIR_RE = re.compile(r"^pe(\d+)$")

_ATLAS_ENABLE_STATE_FIELDS = [
    ("local_storage", "atlas_enable_state_local_storage_effective_total"),
    ("pe_internal_cpe", "atlas_enable_state_pe_internal_cpe_effective_total"),
    ("pe_internal_pod", "atlas_enable_state_pe_internal_pod_effective_total"),
    ("pe_internal_pod_metadata", "atlas_enable_state_pe_internal_pod_metadata_effective_total"),
    ("pe_internal_pod_owner", "atlas_enable_state_pe_internal_pod_owner_effective_total"),
    ("pe_local_service_table", "atlas_enable_state_pe_local_service_table_present_total"),
    ("rowindex_effective", "atlas_enable_state_rowindex_effective_total"),
    ("rowindex_gate_pulse_osa", "atlas_enable_state_rowindex_gate_pulse_osa_total"),
    ("rowindex_gate_metadata_txn", "atlas_enable_state_rowindex_gate_metadata_txn_total"),
    ("rowindex_gate_metadata_mask", "atlas_enable_state_rowindex_gate_metadata_mask_total"),
    ("rowindex_gate_pod_enable", "atlas_enable_state_rowindex_gate_pod_enable_total"),
    ("rowindex_gate_pod_metadata_enable", "atlas_enable_state_rowindex_gate_pod_metadata_enable_total"),
    ("rowindex_gate_pod_owner_enable", "atlas_enable_state_rowindex_gate_pod_owner_enable_total"),
    ("rowindex_gate_service_table_present", "atlas_enable_state_rowindex_gate_service_table_present_total"),
    ("pulse_effective", "atlas_enable_state_pulse_effective_total"),
    ("pulse_fabric_present", "atlas_enable_state_pulse_fabric_present_total"),
    ("pulse_observe_only", "atlas_enable_state_pulse_observe_only_total"),
    ("pulse_actual_ingress", "atlas_enable_state_pulse_actual_ingress_effective_total"),
    ("pulse_harbor", "atlas_enable_state_pulse_harbor_effective_total"),
    ("pulse_descriptor", "atlas_enable_state_pulse_descriptor_effective_total"),
    ("pulse_descriptor_actual", "atlas_enable_state_pulse_descriptor_actual_effective_total"),
    ("pulse_osa", "atlas_enable_state_pulse_osa_effective_total"),
    ("pulse_osa_shared_weight_owner", "atlas_enable_state_pulse_osa_shared_weight_owner_effective_total"),
    ("pulse_osa_shared_weight_actual", "atlas_enable_state_pulse_osa_shared_weight_actual_effective_total"),
    ("weight_plane_present", "atlas_enable_state_pe_weight_plane_present_total"),
    ("pulse_osa_metadata_txn", "atlas_enable_state_pulse_osa_metadata_txn_effective_total"),
    ("pulse_osa_metadata_ready_lease", "atlas_enable_state_pulse_osa_metadata_ready_lease_effective_total"),
    ("pulse_osa_metadata_mask_nonzero", "atlas_enable_state_pulse_osa_metadata_mask_nonzero_total"),
    ("control_runtime_produce", "atlas_enable_state_control_runtime_produce_eligible_total"),
    ("control_runtime_end_to_end", "atlas_enable_state_control_runtime_end_to_end_eligible_total"),
]

_ATLAS_ACTIVATION_GATE_FIELDS = [
    ("workload_pure_snn", "atlas_activation_gate_workload_pure_snn_datapath_eligible"),
    ("local_storage_enable", "atlas_activation_gate_local_storage_enable"),
    ("pulse_requested", "atlas_activation_gate_pulse_requested"),
    ("pulse_effective", "atlas_activation_gate_pulse_effective"),
    ("pulse_fabric_constructed", "atlas_activation_gate_pulse_fabric_constructed"),
    ("pulse_observe_only_effective", "atlas_activation_gate_pulse_observe_only_effective"),
    ("pulse_actual_ingress", "atlas_activation_gate_pulse_actual_ingress_eligible"),
    ("pulse_harbor_enable", "atlas_activation_gate_pulse_harbor_enable_effective"),
    ("pulse_descriptor_enable", "atlas_activation_gate_pulse_descriptor_enable_effective"),
    ("pulse_descriptor_actual_requested", "atlas_activation_gate_pulse_descriptor_actual_requested"),
    ("pulse_descriptor_actual_effective", "atlas_activation_gate_pulse_descriptor_actual_effective"),
    ("pulse_osa_requested", "atlas_activation_gate_pulse_osa_requested"),
    ("pulse_osa_effective", "atlas_activation_gate_pulse_osa_effective"),
    ("shared_weight_owner_requested", "atlas_activation_gate_shared_weight_owner_requested"),
    ("shared_weight_owner_effective", "atlas_activation_gate_shared_weight_owner_effective"),
    ("shared_weight_plane_constructed", "atlas_activation_gate_shared_weight_plane_constructed"),
    ("shared_weight_actual_requested", "atlas_activation_gate_shared_weight_actual_owner_requested"),
    ("shared_weight_actual_effective", "atlas_activation_gate_shared_weight_actual_owner_effective"),
    ("pe_internal_pod_requested", "atlas_activation_gate_pe_internal_pod_requested"),
    ("rowindex_requested", "atlas_activation_gate_rowindex_requested"),
    ("pe_internal_pod_metadata_requested", "atlas_activation_gate_pe_internal_pod_metadata_requested"),
    ("pe_internal_pod_owner_requested", "atlas_activation_gate_pe_internal_pod_owner_requested"),
    ("rowindex_constructed", "atlas_activation_gate_rowindex_constructed"),
    ("pod_metadata_plane_constructed", "atlas_activation_gate_pod_metadata_plane_constructed"),
    ("pod_owner_table_constructed", "atlas_activation_gate_pod_owner_table_constructed"),
    ("service_table_constructed", "atlas_activation_gate_service_table_constructed"),
]

_ATLAS_CONTROL_RUNTIME_CLASSIFICATION_FIELDS = [
    ("produced_any_nonzero", "atlas_control_runtime_produced_any_nonzero_total"),
    ("queued_any_nonzero", "atlas_control_runtime_queued_any_nonzero_total"),
    ("consumed_any_nonzero", "atlas_control_runtime_consumed_any_nonzero_total"),
    ("backlog_any_nonzero", "atlas_control_runtime_backlog_any_nonzero_total"),
    ("all_zero", "atlas_control_runtime_all_zero_total"),
]

_ATLAS_CONTROL_RUNTIME_STATE_FIELDS = [
    ("fabric_absent", "atlas_control_runtime_state_fabric_absent_total"),
    ("fabric_present_idle", "atlas_control_runtime_state_fabric_present_idle_total"),
    ("produced_without_queue", "atlas_control_runtime_state_produced_without_queue_total"),
    ("queued_without_consume", "atlas_control_runtime_state_queued_without_consume_total"),
    ("consumed_active", "atlas_control_runtime_state_consumed_active_total"),
]

_ATLAS_SHARED_WEIGHT_CENSUS_STATE_FIELDS = [
    ("absent", "atlas_shared_weight_census_state_absent_total"),
    ("owner_scope_off", "atlas_shared_weight_census_state_owner_scope_off_total"),
    ("mirror_only", "atlas_shared_weight_census_state_mirror_only_total"),
    ("actual_owner", "atlas_shared_weight_census_state_actual_owner_total"),
]

_ATLAS_SHARED_WEIGHT_CENSUS_ABSENT_REASON_FIELDS = [
    ("workload_ineligible", "atlas_shared_weight_census_absent_reason_workload_ineligible_total"),
    ("local_storage_gate", "atlas_shared_weight_census_absent_reason_local_storage_gate_total"),
    ("pulse_osa_gate", "atlas_shared_weight_census_absent_reason_pulse_osa_gate_total"),
    ("owner_request_gate", "atlas_shared_weight_census_absent_reason_owner_request_gate_total"),
]

_SHARED_WEIGHT_FLAGS = {
    "owner_scope_enable": "atlas_storage_map_shared_owner_scope_enable",
    "actual_owner_enable": "atlas_storage_map_shared_actual_owner_enable",
    "idx_shared_enabled": "atlas_storage_map_weight_idx_shared_enabled",
    "value_shared_enabled": "atlas_storage_map_weight_value_shared_enabled",
}

_SHARED_WEIGHT_AUTHORITY_FIELDS = {
    "idx": {
        "private": "atlas_storage_map_weight_idx_private_authority_total",
        "mirror_only": "atlas_storage_map_weight_idx_shared_mirror_only_total",
        "shared_active": "atlas_storage_map_weight_idx_shared_authority_active_total",
    },
    "value": {
        "private": "atlas_storage_map_weight_value_private_authority_total",
        "mirror_only": "atlas_storage_map_weight_value_shared_mirror_only_total",
        "shared_active": "atlas_storage_map_weight_value_shared_authority_active_total",
    },
}

_EFFECTIVE_OVERRIDE_ROLE_KEYS = {
    "local_storage_enable": ("pe", "local_storage_enable"),
    "pe_internal_cpe_enable": ("pe", "pe_internal_cpe_enable"),
    "pe_internal_pod_enable": ("pe", "pe_internal_pod_enable"),
    "pe_internal_pod_metadata_enable": ("pe", "pe_internal_pod_metadata_enable"),
    "pe_internal_pod_owner_enable": ("pe", "pe_internal_pod_owner_enable"),
    "pe_internal_pod_join_enable": ("pe", "pe_internal_pod_join_enable"),
    "pe_internal_pod_ready_enable": ("pe", "pe_internal_pod_ready_enable"),
}

_ATLAS_CONFIG_RESOLUTION_FIELDS = {
    "local_storage": (("local_storage_enable",),),
    "pe_internal_cpe": (("pe_internal_cpe_enable",),),
    "pe_internal_pod": (("pe_internal_pod_enable",),),
    "pe_internal_pod_metadata": (("pe_internal_pod_metadata_enable",),),
    "pe_internal_pod_owner": (("pe_internal_pod_owner_enable",),),
    "pe_internal_pod_join": (("pe_internal_pod_join_enable",),),
    "pe_internal_pod_ready": (("pe_internal_pod_ready_enable",),),
    "pulse": (("pulse", "enable"), ("pulse_enable",)),
    "pulse_osa": (("pulse", "osa_enable"), ("pulse_osa_enable",)),
    "shared_weight_owner": (
        ("pulse", "osa_shared_weight_owner_enable"),
        ("pulse_osa_shared_weight_owner_enable",),
    ),
    "shared_weight_actual_owner": (
        ("pulse", "osa_shared_weight_actual_enable"),
        ("pulse_osa_shared_weight_actual_enable",),
        ("pulse", "osa_shared_weight_owner_actual_enable"),
        ("pulse_osa_shared_weight_owner_actual_enable",),
    ),
}

_ATLAS_SURFACE_PROBE_FIELDS = {
    "local_storage": [
        ("activation_gate.local_storage_enable", "activation_gate", "local_storage_enable"),
        ("enable_state.local_storage", "enable_state", "local_storage"),
    ],
    "pulse": [
        ("activation_gate.pulse_requested", "activation_gate", "pulse_requested"),
        ("enable_state.pulse_effective", "enable_state", "pulse_effective"),
        ("activation_gate.pulse_fabric_constructed", "activation_gate", "pulse_fabric_constructed"),
    ],
    "pulse_osa": [
        ("activation_gate.pulse_osa_requested", "activation_gate", "pulse_osa_requested"),
        ("enable_state.pulse_osa", "enable_state", "pulse_osa"),
    ],
    "pod_service": [
        ("activation_gate.pe_internal_pod_requested", "activation_gate", "pe_internal_pod_requested"),
        (
            "activation_gate.pe_internal_pod_metadata_requested",
            "activation_gate",
            "pe_internal_pod_metadata_requested",
        ),
        (
            "activation_gate.pe_internal_pod_owner_requested",
            "activation_gate",
            "pe_internal_pod_owner_requested",
        ),
        ("enable_state.pe_internal_pod", "enable_state", "pe_internal_pod"),
        (
            "enable_state.pe_internal_pod_metadata",
            "enable_state",
            "pe_internal_pod_metadata",
        ),
        (
            "enable_state.pe_internal_pod_owner",
            "enable_state",
            "pe_internal_pod_owner",
        ),
        ("enable_state.pe_local_service_table", "enable_state", "pe_local_service_table"),
        (
            "activation_gate.pod_metadata_plane_constructed",
            "activation_gate",
            "pod_metadata_plane_constructed",
        ),
        (
            "activation_gate.pod_owner_table_constructed",
            "activation_gate",
            "pod_owner_table_constructed",
        ),
        (
            "activation_gate.service_table_constructed",
            "activation_gate",
            "service_table_constructed",
        ),
    ],
    "rowindex_object": [
        ("activation_gate.rowindex_requested", "activation_gate", "rowindex_requested"),
        ("enable_state.rowindex_effective", "enable_state", "rowindex_effective"),
        ("activation_gate.rowindex_constructed", "activation_gate", "rowindex_constructed"),
        ("enable_state.rowindex_gate_pulse_osa", "enable_state", "rowindex_gate_pulse_osa"),
        ("enable_state.rowindex_gate_metadata_txn", "enable_state", "rowindex_gate_metadata_txn"),
        ("enable_state.rowindex_gate_metadata_mask", "enable_state", "rowindex_gate_metadata_mask"),
        ("enable_state.rowindex_gate_pod_enable", "enable_state", "rowindex_gate_pod_enable"),
        (
            "enable_state.rowindex_gate_pod_metadata_enable",
            "enable_state",
            "rowindex_gate_pod_metadata_enable",
        ),
        (
            "enable_state.rowindex_gate_pod_owner_enable",
            "enable_state",
            "rowindex_gate_pod_owner_enable",
        ),
        (
            "enable_state.rowindex_gate_service_table_present",
            "enable_state",
            "rowindex_gate_service_table_present",
        ),
        ("activation_gate.pe_internal_pod_requested", "activation_gate", "pe_internal_pod_requested"),
        (
            "activation_gate.pod_metadata_plane_constructed",
            "activation_gate",
            "pod_metadata_plane_constructed",
        ),
        (
            "activation_gate.pod_owner_table_constructed",
            "activation_gate",
            "pod_owner_table_constructed",
        ),
        (
            "activation_gate.service_table_constructed",
            "activation_gate",
            "service_table_constructed",
        ),
    ],
    "shared_weight": [
        (
            "activation_gate.shared_weight_owner_requested",
            "activation_gate",
            "shared_weight_owner_requested",
        ),
        (
            "enable_state.pulse_osa_shared_weight_owner",
            "enable_state",
            "pulse_osa_shared_weight_owner",
        ),
        (
            "activation_gate.shared_weight_actual_requested",
            "activation_gate",
            "shared_weight_actual_requested",
        ),
        (
            "enable_state.pulse_osa_shared_weight_actual",
            "enable_state",
            "pulse_osa_shared_weight_actual",
        ),
        (
            "activation_gate.shared_weight_plane_constructed",
            "activation_gate",
            "shared_weight_plane_constructed",
        ),
    ],
}


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: Any) -> int:
    return int(round(_to_float(value)))


def _safe_div(num: float, den: float) -> float:
    if den == 0:
        return 0.0
    return float(num) / float(den)


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _coalesce(*values: Any) -> Any:
    for value in values:
        normalized = _normalize_value(value)
        if normalized is not None:
            return normalized
    return None


def _int_or_none(value: Any) -> Optional[int]:
    normalized = _normalize_value(value)
    if normalized is None:
        return None
    return _to_int(normalized)


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    vals = sorted(float(v) for v in values)
    rank = (len(vals) - 1) * p
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return vals[lo]
    frac = rank - lo
    return vals[lo] + (vals[hi] - vals[lo]) * frac


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")


def _discover_csvs(run_dir: Path, filename: str) -> List[Path]:
    return sorted(run_dir.glob(filename)) + sorted(run_dir.glob(f"pe*/{filename}"))


def _parse_csv_rows(paths: Iterable[Path]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        pe = 0
        parent_match = _PE_DIR_RE.match(path.parent.name)
        if parent_match:
            pe = int(parent_match.group(1))
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                item: Dict[str, Any] = {"__path__": str(path), "__pe__": pe}
                for key, value in row.items():
                    item[key] = value
                out.append(item)
    return out


def _load_mesh_stats(run_dir: Path) -> Tuple[Dict[str, float], Dict[str, Dict[str, float]], float]:
    stats: Dict[str, float] = defaultdict(float)
    by_component: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    max_sim_time = 0.0
    path = run_dir / "mesh_stats.csv"
    if not path.exists():
        return dict(stats), {k: dict(v) for k, v in by_component.items()}, max_sim_time
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            component = str(row.get("ComponentName", "") or "")
            stat = str(row.get("StatisticName", "") or "")
            value = _to_float(row.get("Sum.u64"))
            if value == 0.0 and str(row.get("Sum.f64", "") or "").strip():
                value = _to_float(row.get("Sum.f64"))
            sim_time = _to_float(row.get("SimTime"))
            max_sim_time = max(max_sim_time, sim_time)
            stats[stat] += value
            by_component[component][stat] += value
    return dict(stats), {k: dict(v) for k, v in by_component.items()}, max_sim_time


def _common_gatherbuf_value(effective_cfg: Dict[str, Any], key: str) -> Any:
    per_core = effective_cfg.get("per_core")
    if not isinstance(per_core, list):
        return None
    values: List[Any] = []
    for item in per_core:
        if not isinstance(item, dict):
            continue
        gatherbuf = item.get("gatherbuf")
        if not isinstance(gatherbuf, dict) or key not in gatherbuf:
            continue
        values.append(gatherbuf.get(key))
    if not values:
        return None
    first = values[0]
    for value in values[1:]:
        if value != first:
            return None
    return first


def _load_idx2_log_fallback(run_dir: Path) -> Dict[str, float]:
    path = run_dir / "mesh_run.log"
    out: Dict[str, float] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _IDX2_LOG_RE.search(line)
        if not match:
            continue
        for token in match.group(1).split():
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            out[key] = _to_float(value)
    return out


def _build_model(run_dir: Path, meta: Dict[str, Any], effective_cfg: Dict[str, Any], sim_time_ps: float) -> Dict[str, Any]:
    meta_model = meta.get("model") if isinstance(meta.get("model"), dict) else meta
    if not isinstance(meta_model, dict):
        meta_model = {}
    exec_mode = _coalesce(meta_model.get("exec_mode"), meta.get("exec_mode"), effective_cfg.get("exec_mode"), "unknown")
    workload_impl = _coalesce(
        meta_model.get("workload_impl"),
        meta.get("workload_impl"),
        effective_cfg.get("workload_impl"),
        "unknown",
    )
    mesh_size = _int_or_none(_coalesce(meta_model.get("mesh_size"), meta.get("mesh_size"), effective_cfg.get("mesh_size")))
    num_pes = _int_or_none(_coalesce(meta_model.get("num_pes"), meta.get("num_pes"), effective_cfg.get("num_pes")))
    line_size_bytes = _int_or_none(
        _coalesce(meta_model.get("line_size_bytes"), meta.get("line_size_bytes"), effective_cfg.get("line_size_bytes"))
    )
    model = {
        "exec_mode": exec_mode,
        "workload_impl": workload_impl,
        "mesh_size": mesh_size,
        "num_pes": num_pes,
        "line_size_bytes": line_size_bytes,
        "sim_time_actual_ns": sim_time_ps / 1000.0,
    }
    noc_cfg = effective_cfg.get("noc_multicast")
    if isinstance(noc_cfg, dict):
        model["noc_multicast_enable"] = int(_to_float(noc_cfg.get("enable")))
        model["noc_multicast_block_w"] = int(_to_float(noc_cfg.get("block_w")))
        model["noc_multicast_block_h"] = int(_to_float(noc_cfg.get("block_h")))
        model["noc_multicast_local_endpoint_multicast_enable"] = int(
            _to_float(noc_cfg.get("local_endpoint_multicast_enable"))
        )
    if "noc_type" in effective_cfg:
        model["noc_type"] = effective_cfg.get("noc_type")
    sram_cfg = effective_cfg.get("sram_effective_pe_core")
    if isinstance(sram_cfg, dict):
        model["sram_model_enable"] = int(_to_float(sram_cfg.get("model_enable")))
        model["sram_state_enable"] = int(_to_float(sram_cfg.get("state_enable")))
        model["sram_weight_idx_enable"] = int(_to_float(sram_cfg.get("weight_idx_enable")))
        model["sram_weight_l0_enable"] = int(_to_float(sram_cfg.get("weight_l0_enable")))
        for key in (
            "state_capacity_bytes",
            "state_banks",
            "state_ports_per_bank",
            "state_bank_interleave_bytes",
            "state_t_read_cycles",
            "state_t_write_cycles",
            "state_sample_log2",
            "weight_idx_capacity_bytes",
            "weight_idx_banks",
            "weight_l0_capacity_bytes",
            "weight_l0_banks",
            "weight_ports_per_bank",
            "weight_bank_interleave_bytes",
            "weight_t_read_cycles",
            "weight_t_write_cycles",
            "weight_sample_log2",
        ):
            model[f"sram_{key}"] = int(_to_float(sram_cfg.get(key)))
    return model


def _build_memory_sections(
    stats: Dict[str, float],
    by_component: Dict[str, Dict[str, float]],
    *,
    line_size_bytes: Optional[int] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    memory_requests = 0.0
    memory_bytes = 0.0
    memctrl_req_total = 0.0
    for component, comp_stats in by_component.items():
        if component.startswith("core_"):
            memory_requests += _to_float(comp_stats.get("memory_requests"))
            memory_bytes += _to_float(comp_stats.get("mem_req_size_bytes"))
        if component.endswith("_memory_controller"):
            memctrl_req_total += _to_float(comp_stats.get("requests_received_GetS"))
    if memory_requests <= 0.0 and memctrl_req_total > 0.0:
        memory_requests = memctrl_req_total
    if memory_bytes <= 0.0 and memory_requests > 0.0 and isinstance(line_size_bytes, int) and line_size_bytes > 0:
        memory_bytes = memory_requests * float(line_size_bytes)
    memhierarchy = {"memctrl": {"req_total": memctrl_req_total}}
    if isinstance(line_size_bytes, int) and line_size_bytes > 0:
        memhierarchy["line_size_bytes"] = int(line_size_bytes)
    return (
        {"memory_requests": memory_requests, "memory_bytes": memory_bytes},
        memhierarchy,
    )


def _build_nic_storm(stats: Dict[str, float], by_component: Dict[str, Dict[str, float]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    nic = {"spikes_sent": 0.0, "packets_sent": 0.0, "spikes_recv": 0.0, "packets_recv": 0.0}
    for component, comp_stats in by_component.items():
        if "network_interface" not in component:
            continue
        nic["spikes_sent"] += _to_float(comp_stats.get("spikes_sent"))
        nic["packets_sent"] += _to_float(comp_stats.get("packets_sent"))
        nic["spikes_recv"] += _to_float(comp_stats.get("spikes_received"))
        nic["packets_recv"] += _to_float(comp_stats.get("packets_received"))
    storm = {
        "cohort_packets_total": _to_float(stats.get("snn_tx_cohort_packets_total")),
        "cohort_pres_total": _to_float(stats.get("snn_tx_cohort_pres_total")),
        "cohort_bandcolor_switch_total": _to_float(stats.get("snn_tx_cohort_bandcolor_switch_total")),
    }
    storm["avg_pres_per_cohort_pkt"] = _safe_div(
        storm["cohort_pres_total"], storm["cohort_packets_total"]
    )
    return nic, storm


def _build_snn_tx(stats: Dict[str, float]) -> Dict[str, Any]:
    snn_tx: Dict[str, Any] = {}
    if "snn_tx_spike_packets_total" in stats:
        snn_tx["spike_packets_total"] = _to_float(stats.get("snn_tx_spike_packets_total"))
    if "snn_tx_spikekey_packets_total" in stats:
        snn_tx["spikekey_packets_total"] = _to_float(stats.get("snn_tx_spikekey_packets_total"))
    if "snn_tx_spiketilekey_packets_total" in stats:
        snn_tx["spiketilekey_packets_total"] = _to_float(stats.get("snn_tx_spiketilekey_packets_total"))
    return snn_tx


def _build_sram(stats: Dict[str, float]) -> Dict[str, Any]:
    def bank(prefix: str) -> Dict[str, Any]:
        reads = _to_float(stats.get(f"{prefix}_reads_total"))
        writes = _to_float(stats.get(f"{prefix}_writes_total"))
        conflicts = _to_float(stats.get(f"{prefix}_bank_conflict_ticks_total"))
        extra = _to_float(stats.get(f"{prefix}_predicted_extra_cycles_total"))
        accesses = reads + writes
        out = {
            "reads_total": reads,
            "writes_total": writes,
            "bank_conflict_ticks_total": conflicts,
            "predicted_extra_cycles_total": extra,
            "bank_peak_accesses_per_tick": _to_float(stats.get(f"{prefix}_bank_peak_accesses_per_tick")),
            "energy_read_pj_total": _to_float(stats.get(f"{prefix}_energy_read_pj_total")),
            "energy_write_pj_total": _to_float(stats.get(f"{prefix}_energy_write_pj_total")),
            "accesses_total": accesses,
            "predicted_extra_cycles_per_access": _safe_div(extra, accesses),
            "predicted_extra_cycles_per_conflict_tick": _safe_div(extra, conflicts),
        }
        return out

    weight_idx = bank("weight_idx_sram")
    weight_l0 = bank("weight_l0_sram")
    state = bank("core_state_sram")
    state["enforced_stall_cycles_total"] = _to_float(stats.get("core_state_sram_stall_cycles_total"))
    state["enforced_stall_cycles_per_conflict_tick"] = _safe_div(
        state["enforced_stall_cycles_total"], state["bank_conflict_ticks_total"]
    )
    weight = {
        "enforced_stall_cycles_total": _to_float(stats.get("weight_sram_enforced_stall_cycles_total")),
        "predicted_extra_cycles_total": weight_idx["predicted_extra_cycles_total"] + weight_l0["predicted_extra_cycles_total"],
        "bank_conflict_ticks_total": weight_idx["bank_conflict_ticks_total"] + weight_l0["bank_conflict_ticks_total"],
        "accesses_total": weight_idx["accesses_total"] + weight_l0["accesses_total"],
    }
    weight["predicted_extra_cycles_per_access"] = _safe_div(
        weight["predicted_extra_cycles_total"], weight["accesses_total"]
    )
    weight["enforced_stall_cycles_per_access"] = _safe_div(
        weight["enforced_stall_cycles_total"], weight["accesses_total"]
    )
    return {"weight_idx": weight_idx, "weight_l0": weight_l0, "weight": weight, "state": state}


def _build_contracts(effective_cfg: Dict[str, Any]) -> Dict[str, Any]:
    retire_policy = _common_gatherbuf_value(effective_cfg, "experimental_retire_policy")
    if retire_policy is None:
        retire_policy = "unknown"
    return {
        "apply_issue_policy": _common_gatherbuf_value(effective_cfg, "apply_issue_policy"),
        "experimental_retire_policy": retire_policy,
        "experimental_gcss_phase_breakdown_enable": bool(
            _common_gatherbuf_value(effective_cfg, "experimental_gcss_phase_breakdown_enable")
        ),
        "experimental_gcss_vlf_queue_policy": _common_gatherbuf_value(effective_cfg, "experimental_gcss_vlf_queue_policy"),
        "experimental_gcss_vlf_fair_band_size": _common_gatherbuf_value(effective_cfg, "experimental_gcss_vlf_fair_band_size"),
        "experimental_retire_shadow_per_post_enable": bool(
            _common_gatherbuf_value(effective_cfg, "experimental_retire_shadow_per_post_enable")
        ),
        "retire_policy_scope": "global_total_order" if retire_policy == "global_inorder" else "unknown",
        "strict_repro_same_post_deterministic": True,
        "strict_repro_global_total_order_required": False,
        "gas_semantic_ready_before_commit": True,
        "gas_semantic_drain_before_scatter": True,
        "gas_semantic_exactly_once_commit": True,
    }


def _group_rows(rows: List[Dict[str, Any]], keys: Tuple[str, ...]) -> Dict[Tuple[Any, ...], List[Dict[str, Any]]]:
    grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(k) for k in keys)].append(row)
    return grouped


def _build_step_and_gas(
    stats: Dict[str, float],
    pe_stage_rows: List[Dict[str, Any]],
    pe_step_rows: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    gather_vals = [_to_float(r.get("gather_ns")) for r in pe_stage_rows]
    apply_vals = [_to_float(r.get("apply_ns")) for r in pe_stage_rows]
    scatter_vals = [_to_float(r.get("scatter_ns")) for r in pe_stage_rows]
    gas = {
        "unique_bytes_total": _to_float(stats.get("gas_unique_bytes_total")),
        "payload_bytes_total": _to_float(stats.get("gas_total_payload_bytes")),
        "retire_global_hol_cycles_total": _to_float(stats.get("gas_retire_global_hol_cycles_total")),
        "retire_ready_but_blocked_edges_total": _to_float(stats.get("gas_retire_ready_but_blocked_edges_total")),
        "retire_per_post_progress_total": _to_float(stats.get("gas_retire_per_post_progress_total")),
        "retire_samepost_blocked_edges_total": _to_float(stats.get("gas_retire_samepost_blocked_edges_total")),
        "retire_crosspost_blocked_edges_total": _to_float(stats.get("gas_retire_crosspost_blocked_edges_total")),
        "retire_policy_loss_cycles_total": _to_float(stats.get("gas_retire_policy_loss_cycles_total")),
        "retire_policy_loss_edges_total": _to_float(stats.get("gas_retire_policy_loss_edges_total")),
        "retire_shadow_per_post_recoverable_cycles_total": _to_float(stats.get("gas_retire_shadow_per_post_recoverable_cycles_total")),
        "retire_shadow_per_post_recoverable_edges_total": _to_float(stats.get("gas_retire_shadow_per_post_recoverable_edges_total")),
        "retire_shadow_per_post_ready_posts_peak_max": _to_float(stats.get("gas_retire_shadow_per_post_ready_posts_peak")),
        "retire_shadow_per_post_committable_edges_peak_max": _to_float(stats.get("gas_retire_shadow_per_post_committable_edges_peak")),
        "gather_ns_avg": _safe_div(sum(gather_vals), len(gather_vals)),
        "apply_ns_avg": _safe_div(sum(apply_vals), len(apply_vals)),
        "scatter_ns_avg": _safe_div(sum(scatter_vals), len(scatter_vals)),
        "gather_ns_p95": _percentile(gather_vals, 0.95),
        "apply_ns_p95": _percentile(apply_vals, 0.95),
        "scatter_ns_p95": _percentile(scatter_vals, 0.95),
        "windows": float(len(pe_step_rows)),
        "windows_done": float(len(pe_step_rows)),
        "windows_incomplete": 0.0,
    }
    gas["net_unique_minus_payload_bytes_total"] = gas["unique_bytes_total"] - gas["payload_bytes_total"]
    gas["overfetch_bytes_total"] = max(gas["net_unique_minus_payload_bytes_total"], 0.0)
    gas["payload_reuse_bytes_total"] = max(gas["payload_bytes_total"] - gas["unique_bytes_total"], 0.0)
    for field in (
        "apply_issue_attempt_total",
        "apply_issue_success_total",
        "apply_issue_block_no_ready_total",
        "apply_issue_block_inflight_cap_total",
        "apply_issue_block_bank_credit_total",
        "apply_issue_block_downstream_busy_total",
        "apply_issue_block_retire_guard_total",
        "apply_ready_queue_nonempty_cycles_total",
        "apply_ready_queue_peak",
        "apply_first_issue_delay_ns",
        "apply_first_down_resp_delay_ns",
        "apply_first_granule_done_delay_ns",
        "apply_first_up_resp_delay_ns",
        "apply_down_resp_total",
        "apply_completed_granules_total",
        "apply_emitted_subreads_total",
        "retire_wait_cycles_total",
        "retire_wait_cycles_due_to_hol_total",
        "retire_wait_cycles_due_to_barrier_total",
        "retire_wait_cycles_due_to_not_ready_total",
        "retire_samepost_blocked_edges_total",
        "retire_crosspost_blocked_edges_total",
        "retire_policy_loss_cycles_total",
        "retire_policy_loss_edges_total",
        "retire_ready_queue_peak",
        "retire_unblock_events_total",
        "step_barrier_wait_ns",
        "frontend_staged_reads",
        "frontend_staged_line_touches",
        "frontend_granules_built",
        "unique_line_count",
    ):
        summary_name = field if not field.endswith("_peak") else field + "_max"
        if field == "apply_ready_queue_peak":
            summary_name = "apply_ready_queue_peak_max"
        if field == "retire_ready_queue_peak":
            summary_name = "retire_ready_queue_peak_max"
        if field == "step_barrier_wait_ns":
            summary_name = "step_barrier_wait_ns_total"
        gas[summary_name] = sum(_to_float(r.get(field)) for r in pe_step_rows)
    gas["step_barrier_wait_ns_max"] = max((_to_float(r.get("step_barrier_wait_ns")) for r in pe_step_rows), default=0.0)
    gas["step_barrier_wait_ns_avg"] = _safe_div(gas["step_barrier_wait_ns_total"], len(pe_step_rows))
    nonempty_rows = [r for r in pe_step_rows if _to_float(r.get("frontend_staged_reads")) > 0]
    gas["frontend_nonempty_windows_total"] = float(len(nonempty_rows))
    gas["frontend_empty_windows_total"] = float(len(pe_step_rows) - len(nonempty_rows))
    gas["frontend_reads_per_nonempty_window_avg"] = _safe_div(
        sum(_to_float(r.get("frontend_staged_reads")) for r in nonempty_rows),
        len(nonempty_rows),
    )
    gas["frontend_unique_lines_per_nonempty_window_avg"] = _safe_div(
        sum(_to_float(r.get("unique_line_count")) for r in nonempty_rows), len(nonempty_rows)
    )
    gas["frontend_granules_per_nonempty_window_avg"] = _safe_div(
        sum(_to_float(r.get("frontend_granules_built")) for r in nonempty_rows), len(nonempty_rows)
    )
    reuse_vals = []
    for row in nonempty_rows:
        touches = _to_float(row.get("frontend_staged_line_touches"))
        unique = _to_float(row.get("unique_line_count"))
        reuse_vals.append(_safe_div(max(touches - unique, 0.0), touches))
    gas["frontend_line_touch_reuse_p50"] = _percentile(reuse_vals, 0.50)
    gas["frontend_line_touch_reuse_p95"] = _percentile(reuse_vals, 0.95)
    pipeline = {
        "first_issue_to_first_resp_ratio": _safe_div(
            gas.get("apply_first_down_resp_delay_ns_total", 0.0),
            gas.get("apply_first_issue_delay_ns_total", 0.0),
        )
    }
    critical = {"stage": "barrier_wait" if gas["step_barrier_wait_ns_total"] > 0 else "apply"}
    grouped = _group_rows(pe_step_rows, ("seq",))
    per_step: List[Dict[str, Any]] = []
    for (seq,), rows in sorted(grouped.items(), key=lambda kv: _to_int(kv[0][0])):
        item = {"seq": _to_int(seq)}
        for field in (
            "step_barrier_wait_ns",
            "retire_samepost_blocked_edges_total",
            "retire_crosspost_blocked_edges_total",
            "retire_policy_loss_cycles_total",
            "retire_policy_loss_edges_total",
        ):
            item[field] = sum(_to_float(r.get(field)) for r in rows)
        per_step.append(item)
    step = {"global_steps_done": float(len(grouped)), "per_step": per_step}
    return gas, pipeline, critical, step


def _build_snn_rx(pe_step_rows: List[Dict[str, Any]], stats: Dict[str, float]) -> Dict[str, Any]:
    snn_rx = {
        "packets_during_gather_total": sum(_to_float(r.get("rx_packets_during_gather_total")) for r in pe_step_rows),
        "packets_during_apply_total": sum(_to_float(r.get("rx_packets_during_apply_total")) for r in pe_step_rows),
        "packets_during_scatter_total": sum(_to_float(r.get("rx_packets_during_scatter_total")) for r in pe_step_rows),
        "gate_pending_peak_max": max((_to_float(r.get("rx_gate_pending_peak")) for r in pe_step_rows), default=0.0),
    }
    if "snn_rx_spike_packets_total" in stats:
        snn_rx["spike_packets_total"] = _to_float(stats.get("snn_rx_spike_packets_total"))
    if "snn_rx_spikekey_total" in stats:
        snn_rx["spikekey_packets_total"] = _to_float(stats.get("snn_rx_spikekey_total"))
    if "snn_rx_spiketilekey_total" in stats:
        snn_rx["spiketilekey_packets_total"] = _to_float(stats.get("snn_rx_spiketilekey_total"))
    if "snn_rx_fastpath_packets_total" in stats:
        snn_rx["fastpath_packets_total"] = _to_float(stats.get("snn_rx_fastpath_packets_total"))
    if "snn_rx_fallback_packets_total" in stats:
        snn_rx["fallback_packets_total"] = _to_float(stats.get("snn_rx_fallback_packets_total"))
    if "snn_rx_decode_fail_total" in stats:
        snn_rx["decode_fail_total"] = _to_float(stats.get("snn_rx_decode_fail_total"))
    return snn_rx


def _build_noc_mem_joint(stats: Dict[str, float], run_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    joint: Dict[str, Any] = {}
    rowidx_fields = {
        "touch_rows_total": "exp_noc_rowidx_touch_rows_total",
        "touch_events_total": "exp_noc_rowidx_touch_events_total",
        "rows_filtered_cold_total": "exp_noc_rowidx_rows_filtered_cold_total",
        "prefetch_rows_total": "exp_noc_rowidx_prefetch_rows_total",
        "prefetch_bytes_total": "exp_noc_rowidx_prefetch_bytes_total",
        "prefetch_complete_inflight_miss_total": "exp_noc_rowidx_prefetch_complete_inflight_miss_total",
        "prefetch_complete_zero_waiters_total": "exp_noc_rowidx_prefetch_complete_zero_waiters_total",
        "prefetch_complete_waiters_total": "exp_noc_rowidx_prefetch_complete_waiters_total",
        "prefetch_rows_deferred_total": "exp_noc_rowidx_prefetch_rows_deferred_total",
        "prefetch_rows_failed_total": "exp_noc_rowidx_prefetch_rows_failed_total",
        "budget_ticks_total": "exp_noc_rowidx_budget_ticks_total",
        "budget_effective_total": "exp_noc_rowidx_budget_effective_total",
        "budget_adapt_ticks_total": "exp_noc_rowidx_budget_adapt_ticks_total",
        "cache_hits_total": "exp_noc_rowidx_cache_hits_total",
        "cache_misses_total": "exp_noc_rowidx_cache_misses_total",
        "cache_fills_total": "exp_noc_rowidx_cache_fills_total",
        "cache_full_drop_total": "exp_noc_rowidx_cache_full_drop_total",
        "cache_entries_final": "exp_noc_rowidx_cache_entries_final",
        "ready_transition_apply_promote_cached_total": "exp_noc_rowidx_ready_transition_apply_promote_cached_total",
        "ready_signal_rowindex_response_total": "exp_noc_rowidx_ready_signal_rowindex_response_total",
        "ready_transition_rowindex_response_total": "exp_noc_rowidx_ready_transition_rowindex_response_total",
        "ready_signal_prefetch_response_total": "exp_noc_rowidx_ready_signal_prefetch_response_total",
        "ready_transition_prefetch_response_total": "exp_noc_rowidx_ready_transition_prefetch_response_total",
        "ready_bypass_experimental_cache_hit_total": "exp_noc_rowidx_ready_bypass_experimental_cache_hit_total",
        "ready_bypass_rowindex_get_hit_total": "exp_noc_rowidx_ready_bypass_rowindex_get_hit_total",
        "close_attempt_total": "exp_noc_rowidx_close_attempt_total",
        "close_attempt_active_owner_total": "exp_noc_rowidx_close_attempt_active_owner_total",
        "close_attempt_already_pending_total": "exp_noc_rowidx_close_attempt_already_pending_total",
        "close_attempt_not_active_total": "exp_noc_rowidx_close_attempt_not_active_total",
        "close_attempt_not_owner_total": "exp_noc_rowidx_close_attempt_not_owner_total",
        "bulk_fill_total": "exp_noc_rowidx_bulk_fill_total",
        "bulk_rows_cached_total": "exp_noc_rowidx_bulk_rows_cached_total",
        "bulk_waiters_resolved_total": "exp_noc_rowidx_bulk_waiters_resolved_total",
    }
    for name, stat_name in rowidx_fields.items():
        joint[f"rowidx_{name}"] = _to_float(stats.get(stat_name))
    for raw_name, summary_name in _ROWIDX_EXTRA_STAT_MAP.items():
        joint[summary_name] = _to_float(stats.get(raw_name))
    joint["rowidx_prefetch_coverage"] = _safe_div(joint["rowidx_prefetch_rows_total"], joint["rowidx_touch_rows_total"])
    joint["rowidx_prefetch_bytes_per_row"] = _safe_div(joint["rowidx_prefetch_bytes_total"], joint["rowidx_prefetch_rows_total"])
    joint["rowidx_rows_filtered_cold_rate"] = _safe_div(joint["rowidx_rows_filtered_cold_total"], joint["rowidx_touch_events_total"])
    joint["rowidx_budget_effective_per_tick"] = _safe_div(joint["rowidx_budget_effective_total"], joint["rowidx_budget_ticks_total"])
    joint["rowidx_budget_adapt_tick_rate"] = _safe_div(joint["rowidx_budget_adapt_ticks_total"], joint["rowidx_budget_ticks_total"])
    joint["rowidx_cache_hit_rate"] = _safe_div(joint["rowidx_cache_hits_total"], joint["rowidx_cache_hits_total"] + joint["rowidx_cache_misses_total"])
    joint["rowidx_cache_full_drop_rate"] = _safe_div(joint["rowidx_cache_full_drop_total"], joint["rowidx_cache_fills_total"])

    idx2_fields = [
        "touch_events_total",
        "lookup_miss_total",
        "enqueued_total",
        "dedup_pending_total",
        "dedup_inflight_total",
        "dedup_cache_total",
        "prefetch_issued_total",
        "prefetch_bytes_total",
        "prefetch_deferred_total",
        "prefetch_failed_total",
        "prefetch_resp_ok_total",
        "prefetch_resp_short_total",
        "prefetch_resp_drop_tail_total",
        "prefetch_complete_inflight_miss_total",
        "prefetch_complete_zero_waiters_total",
        "prefetch_complete_waiters_total",
        "owner_useful_total",
        "owner_dead_total",
        "owner_join_before_ready_total",
        "owner_ready_before_demand_total",
        "demand_hit_total",
        "demand_join_total",
        "demand_join_cb_nonnull_total",
        "demand_join_cb_null_total",
        "demand_fallback_total",
        "waiters_served_total",
        "cache_fill_total",
        "cache_evict_total",
        "cache_entries_final",
        "pending_dropped_on_begin_apply_total",
        "pending_dropped_on_begin_apply_frontier_total",
        "frontier_kept_and_later_useful_total",
        "frontier_kept_but_zero_waiter_total",
        "frontier_kept_cross_window_stale_total",
        "budget_ticks_total",
        "budget_effective_total",
        "budget_adapt_ticks_total",
    ]
    for field in idx2_fields:
        joint[f"idx2_{field}"] = _to_float(stats.get(f"exp_noc_idx2_ingress_{field}"))
    fallback = _load_idx2_log_fallback(run_dir)
    for key, value in fallback.items():
        summary_key = {
            "touch_events": "idx2_touch_events_total",
            "lookup_miss": "idx2_lookup_miss_total",
            "enqueued": "idx2_enqueued_total",
            "prefetch_resp_ok": "idx2_prefetch_resp_ok_total",
            "prefetch_resp_short": "idx2_prefetch_resp_short_total",
            "prefetch_resp_drop_tail": "idx2_prefetch_resp_drop_tail_total",
            "prefetch_inflight_miss": "idx2_prefetch_complete_inflight_miss_total",
            "prefetch_zero_waiters": "idx2_prefetch_complete_zero_waiters_total",
            "prefetch_waiters_total": "idx2_prefetch_complete_waiters_total",
            "owner_useful": "idx2_owner_useful_total",
            "owner_dead": "idx2_owner_dead_total",
            "owner_join_before_ready": "idx2_owner_join_before_ready_total",
            "owner_ready_before_demand": "idx2_owner_ready_before_demand_total",
            "demand_hit": "idx2_demand_hit_total",
            "demand_join": "idx2_demand_join_total",
            "demand_join_cb_nonnull": "idx2_demand_join_cb_nonnull_total",
            "demand_join_cb_null": "idx2_demand_join_cb_null_total",
            "budget_ticks": "idx2_budget_ticks_total",
            "budget_eff": "idx2_budget_effective_total",
            "budget_adapt_ticks": "idx2_budget_adapt_ticks_total",
        }.get(key)
        if summary_key and joint.get(summary_key, 0.0) == 0.0:
            joint[summary_key] = value
    joint["idx2_owner_total"] = joint["idx2_owner_useful_total"] + joint["idx2_owner_dead_total"]
    joint["idx2_demand_join_before_ready_total"] = joint["idx2_demand_join_total"]
    joint["idx2_demand_ready_before_demand_total"] = joint["idx2_demand_hit_total"]
    joint["idx2_prefetch_resp_ok_ratio"] = _safe_div(joint["idx2_prefetch_resp_ok_total"], joint["idx2_prefetch_issued_total"])
    joint["idx2_prefetch_tail_drop_ratio"] = _safe_div(joint["idx2_prefetch_resp_drop_tail_total"], joint["idx2_prefetch_resp_ok_total"])
    joint["idx2_owner_useful_ratio"] = _safe_div(joint["idx2_owner_useful_total"], joint["idx2_owner_total"])
    joint["idx2_owner_dead_ratio"] = _safe_div(joint["idx2_owner_dead_total"], joint["idx2_owner_total"])
    joint["idx2_owner_join_before_ready_ratio"] = _safe_div(joint["idx2_owner_join_before_ready_total"], joint["idx2_owner_total"])
    joint["idx2_owner_ready_before_demand_ratio"] = _safe_div(joint["idx2_owner_ready_before_demand_total"], joint["idx2_owner_total"])
    joint["idx2_demand_join_cb_nonnull_ratio"] = _safe_div(joint["idx2_demand_join_cb_nonnull_total"], joint["idx2_demand_join_total"])
    joint["idx2_demand_join_before_ready_ratio"] = _safe_div(joint["idx2_demand_join_before_ready_total"], joint["idx2_demand_join_total"] + joint["idx2_demand_hit_total"])
    joint["idx2_demand_ready_before_demand_ratio"] = _safe_div(joint["idx2_demand_ready_before_demand_total"], joint["idx2_demand_join_total"] + joint["idx2_demand_hit_total"])
    joint["idx2_waiters_per_join_cb_avg"] = _safe_div(joint["idx2_waiters_served_total"], joint["idx2_demand_join_cb_nonnull_total"])
    joint["idx2_budget_effective_per_tick"] = _safe_div(joint["idx2_budget_effective_total"], joint["idx2_budget_ticks_total"])
    joint["idx2_budget_adapt_tick_rate"] = _safe_div(joint["idx2_budget_adapt_ticks_total"], joint["idx2_budget_ticks_total"])

    atlas_shadow = {
        "rowindex": {
            "runtime_touch_rows_total": joint.get("rowidx_touch_rows_total", 0.0),
            "runtime_prefetch_rows_total": joint.get("rowidx_prefetch_rows_total", 0.0),
            "runtime_prefetch_rows_deferred_total": joint.get("rowidx_prefetch_rows_deferred_total", 0.0),
            "runtime_prefetch_rows_failed_total": joint.get("rowidx_prefetch_rows_failed_total", 0.0),
            "runtime_cache_hits_total": joint.get("rowidx_cache_hits_total", 0.0),
            "runtime_cache_misses_total": joint.get("rowidx_cache_misses_total", 0.0),
            "runtime_cache_fills_total": joint.get("rowidx_cache_fills_total", 0.0),
            "runtime_cache_full_drop_total": joint.get("rowidx_cache_full_drop_total", 0.0),
            "runtime_bulk_fill_total": joint.get("rowidx_bulk_fill_total", 0.0),
            "runtime_bulk_rows_cached_total": joint.get("rowidx_bulk_rows_cached_total", 0.0),
            "runtime_bulk_waiters_resolved_total": joint.get("rowidx_bulk_waiters_resolved_total", 0.0),
            "runtime_prefetch_coverage": joint.get("rowidx_prefetch_coverage", 0.0),
            "runtime_cache_hit_rate": joint.get("rowidx_cache_hit_rate", 0.0),
        }
    }
    _patch_rowindex_fields({"noc_mem_joint": joint, "atlas_shadow": atlas_shadow, "run_dir": str(run_dir)})
    return joint, atlas_shadow


def _map_direct_stats(stats: Dict[str, float], prefix: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    plen = len(prefix)
    for stat_name, value in stats.items():
        if stat_name.startswith(prefix):
            out[stat_name[plen:]] = value
    return out


def _build_atlas_sections(stats: Dict[str, float], joint: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    atlas_service = {k: v for k, v in stats.items() if k.startswith("atlas_service_")}
    atlas_service["atlas_service_ready_fanout_avg"] = _safe_div(
        atlas_service.get("atlas_service_ready_fanout_consumers_sum", 0.0),
        atlas_service.get("atlas_service_ready_fanout_total", 0.0),
    )
    atlas_service["atlas_service_private_only_share"] = _safe_div(
        atlas_service.get("atlas_service_atlas_obj_private_only_total", 0.0),
        atlas_service.get("atlas_service_atlas_obj_ready_total", 0.0),
    )
    atlas_proxy = {
        "idx2row": _map_direct_stats(stats, "atlas_proxy_idx2row_"),
        "premphf_base": _map_direct_stats(stats, "atlas_proxy_premphf_base_"),
        "premphf_band": _map_direct_stats(stats, "atlas_proxy_premphf_band_"),
        "rowindex": _map_direct_stats(stats, "atlas_proxy_rowindex_"),
    }
    atlas_lookup = {"premphf_base": {}, "premphf_band": {}}
    atlas_control = {
        "messages_enqueued_total": _to_float(stats.get("pulse_control_messages_enqueued_total")),
        "entries_peak": _to_float(stats.get("pulse_control_entries_peak")),
        "backlog_cycles_total": _to_float(stats.get("pulse_control_backlog_cycles_total")),
        "ready_fanout_total": _to_float(stats.get("pulse_control_ready_fanout_total")),
    }
    atlas_fabric = {
        "ingress_packets_total": _to_float(stats.get("pulse_ingress_packets_total")),
        "control_messages_enqueued_total": _to_float(stats.get("pulse_control_messages_enqueued_total")),
    }
    atlas_storage = {
        "idx_reads_total": _to_float(stats.get("weight_idx_sram_reads_total")),
        "idx_bank_conflict_ticks_total": _to_float(stats.get("weight_idx_sram_bank_conflict_ticks_total")),
        "l0_reads_total": _to_float(stats.get("weight_l0_sram_reads_total")),
        "l0_fill_total": _to_float(stats.get("weight_l0_fill_total")),
        "pod_metadata_observe_total": _to_float(stats.get("atlas_pod_metadata_observe_total")),
        "pod_metadata_overlap_hit_total": _to_float(stats.get("atlas_pod_metadata_overlap_hit_total")),
        "pod_owner_owner_alloc_total": _to_float(stats.get("atlas_pod_owner_owner_alloc_total")),
        "pod_owner_join_grant_total": _to_float(stats.get("atlas_pod_owner_join_grant_total")),
        "pod_metadata": {
            "premphf_base": {"observe_total": _to_float(stats.get("atlas_pod_metadata_premphf_base_observe_total"))},
            "premphf_band": {"observe_total": _to_float(stats.get("atlas_pod_metadata_premphf_band_observe_total"))},
            "rowindex": {"observe_total": _to_float(stats.get("atlas_pod_metadata_rowindex_observe_total"))},
        },
        "pod_owner": {
            "premphf_band": {"owner_alloc_total": _to_float(stats.get("atlas_pod_owner_premphf_band_owner_alloc_total"))},
            "rowindex": {"join_grant_total": _to_float(stats.get("atlas_pod_owner_rowindex_join_grant_total"))},
        },
    }
    atlas_sync = {
        "retire_ready_but_blocked_edges_total": _to_float(stats.get("gas_retire_ready_but_blocked_edges_total")),
        "retire_wait_cycles_total": _to_float(stats.get("retire_wait_cycles_total")),
        "retire_wait_cycles_due_to_barrier_total": _to_float(stats.get("retire_wait_cycles_due_to_barrier_total")),
    }
    derived = {
        "proxy_shadow": {
            "service_materialize_total": atlas_service.get("atlas_service_atlas_obj_materialize_total", 0.0),
            "service_ready_total": atlas_service.get("atlas_service_atlas_obj_ready_total", 0.0),
            "service_release_total": atlas_service.get("atlas_service_atlas_obj_release_total", 0.0),
            "prebase_proxy_activity_total": atlas_proxy["premphf_base"].get("materialize_total", 0.0),
            "descriptor_proxy_activity_total": _to_float(stats.get("pulse_descriptor_total")),
            "rowindex_shadow_activity_total": joint.get("rowidx_touch_rows_total", 0.0),
            "prebase_proxy_to_materialize_gap": atlas_proxy["premphf_base"].get("materialize_total", 0.0) - atlas_service.get("atlas_service_atlas_obj_materialize_total", 0.0),
            "descriptor_proxy_to_materialize_gap": _to_float(stats.get("pulse_descriptor_total")) - atlas_service.get("atlas_service_atlas_obj_materialize_total", 0.0),
            "rowindex_shadow_to_materialize_gap": joint.get("rowidx_touch_rows_total", 0.0) - atlas_service.get("atlas_service_atlas_obj_materialize_total", 0.0),
        },
        "machine": {
            "lookup_activity_total": 0.0,
            "shadow_activity_total": joint.get("rowidx_touch_rows_total", 0.0),
            "control_activity_total": atlas_control["messages_enqueued_total"],
            "proxy_activity_total": atlas_proxy["rowindex"].get("materialize_total", 0.0),
            "activity_plane_gap_total": joint.get("rowidx_touch_rows_total", 0.0) - atlas_control["messages_enqueued_total"],
            "lookup_materialize_gap_total": -atlas_service.get("atlas_service_atlas_obj_materialize_total", 0.0),
            "shadow_materialize_gap_total": atlas_service.get("atlas_service_atlas_obj_materialize_total", 0.0) - joint.get("rowidx_touch_rows_total", 0.0),
            "fabric_control_per_ingress": _safe_div(atlas_control["messages_enqueued_total"], atlas_fabric["ingress_packets_total"]),
            "storage_conflict_per_read": _safe_div(atlas_storage["idx_bank_conflict_ticks_total"], atlas_storage["idx_reads_total"]),
            "sync_barrier_wait_share": 0.0,
        },
    }
    return atlas_service, atlas_proxy, atlas_lookup, atlas_control, atlas_fabric, atlas_storage, atlas_sync, derived, {
        "metadata_unique_object_total": _to_float(stats.get("atlas_pod_metadata_unique_object_total")),
        "owner_alloc_total": _to_float(stats.get("atlas_pod_owner_owner_alloc_total")),
        "service_owner_form_total": atlas_service.get("atlas_service_owner_form_total", 0.0),
        "service_ready_total": atlas_service.get("atlas_service_ready_transition_total", 0.0),
        "service_release_total": atlas_service.get("atlas_service_released_total", 0.0),
        "unique_to_owner_gap_total": _to_float(stats.get("atlas_pod_metadata_unique_object_total")) - _to_float(stats.get("atlas_pod_owner_owner_alloc_total")),
        "owner_to_service_gap_total": _to_float(stats.get("atlas_pod_owner_owner_alloc_total")) - atlas_service.get("atlas_service_owner_form_total", 0.0),
        "service_to_ready_gap_total": atlas_service.get("atlas_service_owner_form_total", 0.0) - atlas_service.get("atlas_service_ready_transition_total", 0.0),
        "ready_to_release_gap_total": atlas_service.get("atlas_service_ready_transition_total", 0.0) - atlas_service.get("atlas_service_released_total", 0.0),
        "rowindex": {
            "metadata_duplicate_consumer_total": _to_float(stats.get("atlas_pod_metadata_rowindex_duplicate_consumer_total")),
            "metadata_active_entries_peak_total": _to_float(stats.get("atlas_pod_metadata_rowindex_active_entries_peak_total")),
            "owner_reject_total": _to_float(stats.get("atlas_pod_owner_rowindex_owner_reject_total")),
            "join_request_total": _to_float(stats.get("atlas_pod_owner_rowindex_join_request_total")),
            "join_grant_total": _to_float(stats.get("atlas_pod_owner_rowindex_join_grant_total")),
            "join_reject_total": _to_float(stats.get("atlas_pod_owner_rowindex_join_reject_total")),
            "owner_active_entries_peak_total": _to_float(stats.get("atlas_pod_owner_rowindex_active_entries_peak_total")),
            "metadata_to_owner_gap_total": _to_float(stats.get("atlas_pod_metadata_rowindex_unique_object_total")) - _to_float(stats.get("atlas_pod_owner_rowindex_owner_alloc_total")),
            "join_request_to_grant_gap_total": _to_float(stats.get("atlas_pod_owner_rowindex_join_request_total")) - _to_float(stats.get("atlas_pod_owner_rowindex_join_grant_total")),
        },
        "premphf_band": {
            "metadata_duplicate_consumer_total": _to_float(stats.get("atlas_pod_metadata_premphf_band_duplicate_consumer_total")),
            "metadata_active_entries_peak_total": _to_float(stats.get("atlas_pod_metadata_premphf_band_active_entries_peak_total")),
            "owner_reject_total": _to_float(stats.get("atlas_pod_owner_premphf_band_owner_reject_total")),
            "join_request_total": _to_float(stats.get("atlas_pod_owner_premphf_band_join_request_total")),
            "join_grant_total": _to_float(stats.get("atlas_pod_owner_premphf_band_join_grant_total")),
            "join_reject_total": _to_float(stats.get("atlas_pod_owner_premphf_band_join_reject_total")),
            "owner_active_entries_peak_total": _to_float(stats.get("atlas_pod_owner_premphf_band_active_entries_peak_total")),
            "metadata_to_owner_gap_total": _to_float(stats.get("atlas_pod_metadata_premphf_band_unique_object_total")) - _to_float(stats.get("atlas_pod_owner_premphf_band_owner_alloc_total")),
            "join_request_to_grant_gap_total": _to_float(stats.get("atlas_pod_owner_premphf_band_join_request_total")) - _to_float(stats.get("atlas_pod_owner_premphf_band_join_grant_total")),
        },
    }


def _build_pulse(stats: Dict[str, float]) -> Dict[str, Any]:
    return {f"pulse_{k}": v for k, v in _map_direct_stats(stats, "pulse_").items()}


def _patch_rowindex_fields(summary: Dict[str, Any]) -> None:
    noc_mem_joint = summary.get("noc_mem_joint")
    if not isinstance(noc_mem_joint, dict):
        return
    run_dir = summary.get("run_dir")
    if isinstance(run_dir, str) and run_dir:
        stats, _, _ = _load_mesh_stats(Path(run_dir))
        for raw_name, summary_name in _ROWIDX_EXTRA_STAT_MAP.items():
            noc_mem_joint.setdefault(summary_name, _to_float(stats.get(raw_name)))
    rowindex_signal = _to_float(noc_mem_joint.get("rowidx_ready_signal_rowindex_response_total"))
    prefetch_signal = _to_float(noc_mem_joint.get("rowidx_ready_signal_prefetch_response_total"))
    rowindex_transition = _to_float(noc_mem_joint.get("rowidx_ready_transition_rowindex_response_total"))
    prefetch_transition = _to_float(noc_mem_joint.get("rowidx_ready_transition_prefetch_response_total"))
    noc_mem_joint["rowidx_ready_signal_generic_coalesced_response_total"] = max(rowindex_signal - prefetch_signal, 0.0)
    noc_mem_joint["rowidx_ready_transition_generic_coalesced_response_total"] = max(rowindex_transition - prefetch_transition, 0.0)
    atlas_shadow = summary.setdefault("atlas_shadow", {})
    if not isinstance(atlas_shadow, dict):
        return
    rowindex_shadow = atlas_shadow.setdefault("rowindex", {})
    if not isinstance(rowindex_shadow, dict):
        return
    rowindex_shadow["runtime_ready_signal_generic_coalesced_response_total"] = noc_mem_joint["rowidx_ready_signal_generic_coalesced_response_total"]
    rowindex_shadow["runtime_ready_transition_generic_coalesced_response_total"] = noc_mem_joint["rowidx_ready_transition_generic_coalesced_response_total"]
    rowindex_shadow["runtime_bulk_fill_total"] = _to_float(noc_mem_joint.get("rowidx_bulk_fill_total"))
    rowindex_shadow["runtime_bulk_rows_cached_total"] = _to_float(noc_mem_joint.get("rowidx_bulk_rows_cached_total"))
    rowindex_shadow["runtime_bulk_waiters_resolved_total"] = _to_float(noc_mem_joint.get("rowidx_bulk_waiters_resolved_total"))
    for summary_name in _ROWIDX_EXTRA_STAT_MAP.values():
        rowindex_shadow[f"runtime_{summary_name}"] = _to_float(noc_mem_joint.get(summary_name))


def _determine_pe_count(model: Dict[str, Any], by_component: Dict[str, Dict[str, float]]) -> int:
    num_pes = model.get("num_pes")
    if isinstance(num_pes, (int, float)) and num_pes > 0:
        return int(num_pes)
    return sum(1 for comp in by_component if comp.startswith("multicore_pe_"))


def _one_hot_summary(stats: Dict[str, float], key: str, pe_count: int) -> Dict[str, Any]:
    total = _to_int(stats.get(key, 0))
    share = float(total) / pe_count if pe_count > 0 else None
    return {"total": total, "share": share}


def _effective_flag(effective: Dict[str, Any], *path: str) -> int:
    override_value = _effective_override_value(effective, *path)
    if override_value is not None:
        return _to_int(override_value)
    return _effective_flag_top_level_only(effective, *path)


def _effective_flag_top_level_only(effective: Dict[str, Any], *path: str) -> int:
    node: Any = effective
    for key in path:
        if not isinstance(node, dict):
            return 0
        node = node.get(key)
    return _to_int(node)


def _effective_top_level_value(effective: Dict[str, Any], *path: str) -> Any:
    node: Any = effective
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _effective_override_params(effective: Dict[str, Any], role: str) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    overrides = effective.get("overrides")
    if isinstance(overrides, list):
        for item in overrides:
            if not isinstance(item, dict):
                continue
            match = item.get("match")
            params = item.get("params")
            if not isinstance(match, dict) or not isinstance(params, dict):
                continue
            if str(match.get("role") or "") != role:
                continue
            merged.update(params)
    overrides_report = effective.get("overrides_report")
    if isinstance(overrides_report, list):
        for item in overrides_report:
            if not isinstance(item, dict):
                continue
            changed = item.get("changed")
            if str(item.get("role") or "") != role or not isinstance(changed, dict):
                continue
            merged.update(changed)
    return merged


def _effective_override_value(effective: Dict[str, Any], *path: str) -> Any:
    if len(path) != 1:
        return None
    role_key = _EFFECTIVE_OVERRIDE_ROLE_KEYS.get(path[0])
    if role_key is None:
        return None
    role, key = role_key
    params = _effective_override_params(effective, role)
    if key not in params:
        return None
    return params.get(key)


def _effective_flag_any(
    effective: Dict[str, Any], primary_path: Tuple[str, ...], *fallback_paths: Tuple[str, ...]
) -> int:
    for path in (primary_path,) + fallback_paths:
        value = _effective_flag(effective, *path)
        if value != 0:
            return value
    return _effective_flag(effective, *primary_path)


def _build_atlas_config_resolution(effective: Dict[str, Any]) -> Dict[str, Any]:
    resolution: Dict[str, Any] = {}
    for label, paths in _ATLAS_CONFIG_RESOLUTION_FIELDS.items():
        top_level_value = None
        override_value = None
        for path in paths:
            candidate = _effective_top_level_value(effective, *path)
            if _normalize_value(candidate) is not None and top_level_value is None:
                top_level_value = candidate
            override_candidate = _effective_override_value(effective, *path)
            if _normalize_value(override_candidate) is not None and override_value is None:
                override_value = override_candidate
        primary_path = paths[0]
        if len(paths) > 1:
            resolved_value = _effective_flag_any(effective, primary_path, *paths[1:])
        else:
            resolved_value = _effective_flag(effective, *primary_path)
        top_level_norm = _normalize_value(top_level_value)
        override_norm = _normalize_value(override_value)
        top_level_int = _int_or_none(top_level_norm)
        override_int = _int_or_none(override_norm)
        conflict = (
            top_level_int is not None
            and override_int is not None
            and top_level_int != override_int
        )
        if override_int is not None:
            source = "override"
        elif top_level_int is not None:
            source = "top_level"
        else:
            source = "default_zero"
        resolution[label] = {
            "path": " | ".join(".".join(path) for path in paths),
            "top_level": top_level_int,
            "override": override_int,
            "resolved": resolved_value,
            "source": source,
            "conflict": conflict,
        }
    return resolution


def _machine_break(
    label: str,
    count: int,
    share: Optional[float],
    stage: str,
    reason: str,
) -> Dict[str, Any]:
    return {
        "label": label,
        "count": count,
        "share": share,
        "stage": stage,
        "reason": reason,
    }


def _counter_total(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    return _to_int(payload.get("total", 0))


def _counter_share(payload: Any) -> Optional[float]:
    if not isinstance(payload, dict):
        return None
    share = payload.get("share")
    if share is None:
        return None
    return float(share)


def _count_gap(upstream: int, downstream: int) -> int:
    return max(upstream - downstream, 0)


def _share_from_count(count: int, pe_count: int) -> Optional[float]:
    if pe_count <= 0:
        return None
    return float(count) / float(pe_count)


def _phase_mismatch_entry(
    state: str,
    *,
    reason: str,
    mismatch_count: int,
    mismatch_share: Optional[float],
    build_effective: Optional[int] = None,
    runtime_requested_total: Optional[int] = None,
    runtime_effective_total: Optional[int] = None,
    runtime_constructed_total: Optional[int] = None,
    gap_requested_to_effective: Optional[int] = None,
    gap_effective_to_constructed: Optional[int] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "state": state,
        "reason": reason,
        "mismatch_count": mismatch_count,
        "mismatch_share": mismatch_share,
    }
    if build_effective is not None:
        entry["build_effective"] = build_effective
    if runtime_requested_total is not None:
        entry["runtime_requested_total"] = runtime_requested_total
    if runtime_effective_total is not None:
        entry["runtime_effective_total"] = runtime_effective_total
    if runtime_constructed_total is not None:
        entry["runtime_constructed_total"] = runtime_constructed_total
    if gap_requested_to_effective is not None:
        entry["gap_requested_to_effective"] = gap_requested_to_effective
    if gap_effective_to_constructed is not None:
        entry["gap_effective_to_constructed"] = gap_effective_to_constructed
    return entry


def _build_atlas_surface_state_view(
    atlas_contract_mismatch: Dict[str, Any],
) -> Dict[str, Any]:
    phase = atlas_contract_mismatch.get("phase", {})
    storage_authority = atlas_contract_mismatch.get("storage_authority", {})
    control_runtime = atlas_contract_mismatch.get("control_runtime", {})
    sync = atlas_contract_mismatch.get("sync", {})
    if not isinstance(phase, dict):
        phase = {}
    if not isinstance(storage_authority, dict):
        storage_authority = {}
    if not isinstance(control_runtime, dict):
        control_runtime = {}
    if not isinstance(sync, dict):
        sync = {}

    def _surface_entry(payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {"machine_state": "unknown", "reason": "surface state unavailable"}
        return {
            "machine_state": str(payload.get("state") or "unknown"),
            "reason": str(payload.get("reason") or "surface state unavailable"),
        }

    return {
        "vocabulary": "atlas_contract_mismatch_v1",
        "surfaces": {
            "local_storage": _surface_entry(phase.get("local_storage")),
            "pulse": _surface_entry(phase.get("pulse")),
            "pulse_osa": _surface_entry(phase.get("pulse_osa")),
            "shared_weight_owner": _surface_entry(phase.get("shared_weight_owner")),
            "pod_service": _surface_entry(phase.get("pod_service")),
            "shared_weight_authority": _surface_entry(
                storage_authority.get("shared_weight")
            ),
            "control_runtime": _surface_entry(control_runtime),
            "sync": _surface_entry(sync),
        },
    }


def _build_atlas_control_commit_view(
    atlas_contract_mismatch: Dict[str, Any],
) -> Dict[str, Any]:
    control_runtime = atlas_contract_mismatch.get("control_runtime", {})
    sync = atlas_contract_mismatch.get("sync", {})
    if not isinstance(control_runtime, dict):
        control_runtime = {}
    if not isinstance(sync, dict):
        sync = {}

    control_state = str(control_runtime.get("state") or "unknown")
    sync_state = str(sync.get("state") or "unknown")
    ready_blocked_total = _to_int(
        sync.get("ready_visible_but_commit_blocked_edges_total")
    )
    barrier_wait_total = _to_int(sync.get("retire_wait_cycles_due_to_barrier_total"))
    retire_wait_total = _to_int(sync.get("retire_wait_cycles_total"))

    control_contract_state = {
        "fabric_absent": "fabric_absent",
        "fabric_present_idle": "fabric_present_idle",
        "produced_without_queue": "produced_without_queue",
        "queued_without_consume": "queued_without_consume",
        "consumed_active": "aligned_active",
    }.get(control_state, control_state)

    sync_contract_state = {
        "ready_visible_but_commit_blocked": "service_ready_commit_blocked",
        "barrier_wait": "service_ready_barrier_wait",
        "clean": "service_commit_aligned",
    }.get(sync_state, "unknown")

    if sync_state == "ready_visible_but_commit_blocked":
        state = "ready_visible_commit_blocked"
        reason = "ready is visible in control/service view, but commit cannot retire yet"
        contract_state = "service_ready_commit_blocked"
        ready_state = "visible"
        commit_state = "blocked"
    elif sync_state == "barrier_wait":
        state = "barrier_wait_after_ready"
        reason = "ready became visible, then commit waited behind a barrier"
        contract_state = "service_ready_barrier_wait"
        ready_state = "visible"
        commit_state = "barrier_wait"
    elif control_state == "fabric_absent":
        state = "fabric_absent"
        reason = "control plane never reached an active shared-service state"
        contract_state = "fabric_absent"
        ready_state = "dark"
        commit_state = "not_applicable"
    elif control_state == "aligned_active" and sync_state == "clean":
        state = "control_active_commit_clean"
        reason = "control plane is active and no commit-side mismatch is visible"
        contract_state = "service_commit_aligned"
        ready_state = "clean"
        commit_state = "clean"
    else:
        state = "control_not_active_commit_clean"
        reason = "control plane is not active, but commit-side mismatch remains clean"
        contract_state = "control_not_active_commit_clean"
        ready_state = "dark" if sync_state == "clean" else "unknown"
        commit_state = "clean" if sync_state == "clean" else "waiting"

    return {
        "version": 1,
        "vocabulary": "atlas_control_commit_view_v1",
        "state": state,
        "reason": reason,
        "contract_state": contract_state,
        "control_state": control_state,
        "control_contract_state": control_contract_state,
        "control_reason": str(
            control_runtime.get("reason") or "control runtime state unavailable"
        ),
        "control_count": _to_int(control_runtime.get("count", 0)),
        "control_share": control_runtime.get("share"),
        "ready_state": ready_state,
        "commit_state": commit_state,
        "sync_state": sync_state,
        "sync_contract_state": sync_contract_state,
        "sync_reason": str(sync.get("reason") or "sync state unavailable"),
        "ready_visible_but_commit_blocked_edges_total": ready_blocked_total,
        "barrier_wait_cycles_total": barrier_wait_total,
        "retire_wait_cycles_total": retire_wait_total,
    }


def _build_atlas_control_binding_map(
    stats: Dict[str, float],
    atlas_object_kind_census: Dict[str, Any],
    atlas_control: Dict[str, Any],
    atlas_fabric: Dict[str, Any],
    atlas_sync: Dict[str, Any],
    atlas_control_commit_view: Dict[str, Any],
) -> Dict[str, Any]:
    object_entries = atlas_object_kind_census.get("objects", {})
    if not isinstance(object_entries, dict):
        object_entries = {}

    def _object_entry(name: str) -> Dict[str, Any]:
        payload = object_entries.get(name, {})
        return payload if isinstance(payload, dict) else {}

    def _entry(
        *,
        plane: str,
        object_role: str,
        runtime_owner: str,
        lifecycle_contract: str,
        ready_visibility: str,
        release_visibility: str,
        commit_relation: str,
        formalization_state: str,
        evidence: Dict[str, Any],
        object_kind_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "plane": plane,
            "object_role": object_role,
            "runtime_owner": runtime_owner,
            "lifecycle_contract": lifecycle_contract,
            "ready_visibility": ready_visibility,
            "release_visibility": release_visibility,
            "commit_relation": commit_relation,
            "formalization_state": formalization_state,
            "evidence": evidence,
        }
        if object_kind_ref is not None:
            object_payload = _object_entry(object_kind_ref)
            payload["object_kind_ref"] = object_kind_ref
            payload["object_kind_state"] = str(object_payload.get("state") or "missing")
        return payload

    rowdescriptor_payload = _object_entry("rowdescriptor")
    rowdescriptor_evidence = _to_float(rowdescriptor_payload.get("evidence_total"))
    descriptor_runtime_total = _to_float(stats.get("pulse_descriptor_total"))
    rowdescriptor_visible = rowdescriptor_evidence > 0.0 or descriptor_runtime_total > 0.0

    ingress_packets_total = _to_float(atlas_fabric.get("ingress_packets_total"))
    control_messages_total = _to_float(atlas_control.get("messages_enqueued_total"))
    control_entries_peak = _to_float(atlas_control.get("entries_peak"))
    control_backlog_cycles_total = _to_float(atlas_control.get("backlog_cycles_total"))
    ingress_visible = (
        ingress_packets_total > 0.0
        or control_messages_total > 0.0
        or control_entries_peak > 0.0
        or control_backlog_cycles_total > 0.0
    )

    ready_blocked_total = _to_float(atlas_sync.get("retire_ready_but_blocked_edges_total"))
    barrier_wait_total = _to_float(atlas_sync.get("retire_wait_cycles_due_to_barrier_total"))
    retire_wait_total = _to_float(atlas_sync.get("retire_wait_cycles_total"))
    sync_contract_state = str(
        atlas_control_commit_view.get("contract_state") or "unknown"
    )
    sync_visible = (
        ready_blocked_total > 0.0
        or barrier_wait_total > 0.0
        or retire_wait_total > 0.0
        or sync_contract_state != "fabric_absent"
    )

    entries = {
        "rowdescriptor": _entry(
            plane="message_plane",
            object_role="proxy_backed_descriptor",
            runtime_owner="PulseDescriptorProxy",
            lifecycle_contract="producer_to_descriptor_proxy",
            ready_visibility=(
                "proxy_runtime_visible" if descriptor_runtime_total > 0.0 else "dark"
            ),
            release_visibility="not_applicable_proxy_path",
            commit_relation="indirect_message_only",
            formalization_state=(
                "proxy_descriptor_visible" if rowdescriptor_visible else "proxy_descriptor_dark"
            ),
            evidence={
                "object_evidence_total": rowdescriptor_evidence,
                "descriptor_runtime_total": descriptor_runtime_total,
                "producer_events_total": _to_float(
                    stats.get("atlas_census_rowdescriptor_producer_events_total")
                ),
            },
            object_kind_ref="rowdescriptor",
        ),
        "activation_ingress_store": _entry(
            plane="message_plane",
            object_role="message_ingress_store",
            runtime_owner="PulseIngressFabric",
            lifecycle_contract="ingress_enqueue_dispatch",
            ready_visibility="not_applicable",
            release_visibility=(
                "drain_visible" if control_messages_total > 0.0 else "dark"
            ),
            commit_relation="feeds_control_runtime",
            formalization_state=(
                "ingress_runtime_visible" if ingress_visible else "ingress_runtime_dark"
            ),
            evidence={
                "ingress_packets_total": ingress_packets_total,
                "control_messages_enqueued_total": control_messages_total,
                "entries_peak": control_entries_peak,
                "backlog_cycles_total": control_backlog_cycles_total,
            },
        ),
        "sync_barrier": _entry(
            plane="sync_plane",
            object_role="sync_gate",
            runtime_owner="RetireSyncPath",
            lifecycle_contract="ready_to_commit_gate",
            ready_visibility=str(
                atlas_control_commit_view.get("ready_state") or "unknown"
            ),
            release_visibility="not_applicable_sync_gate",
            commit_relation=sync_contract_state,
            formalization_state=(
                "sync_gate_visible" if sync_visible else "sync_gate_dark"
            ),
            evidence={
                "ready_visible_but_commit_blocked_edges_total": ready_blocked_total,
                "barrier_wait_cycles_total": barrier_wait_total,
                "retire_wait_cycles_total": retire_wait_total,
            },
        ),
    }

    summary: Dict[str, int] = {}
    for payload in entries.values():
        state = str(payload.get("formalization_state") or "unknown")
        summary[state] = summary.get(state, 0) + 1
    return {
        "version": 1,
        "vocabulary": "atlas_control_binding_map_v1",
        "entries": entries,
        "summary": summary,
    }


def _build_atlas_schema_registry(
    specs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    views: Dict[str, Dict[str, Any]] = {}
    for spec in specs:
        name = str(spec.get("name") or "")
        payload = spec.get("payload", {})
        version_field = str(spec.get("version_field") or "version")
        default_vocabulary = str(spec.get("default_vocabulary") or "")
        authority_source = str(spec.get("authority_source") or "summary_reader")
        artifact_surfaces = spec.get("artifact_surfaces", ["summary", "trace"])
        if not name:
            continue
        if not isinstance(payload, dict):
            payload = {}
        if not isinstance(artifact_surfaces, list):
            artifact_surfaces = ["summary", "trace"]
        version = _to_int(payload.get(version_field, 0))
        vocabulary = str(payload.get("vocabulary") or default_vocabulary)
        views[name] = {
            "version": version,
            "vocabulary": vocabulary,
            "authority_source": authority_source,
            "artifact_surfaces": [str(item) for item in artifact_surfaces],
        }
    return {
        "version": 1,
        "vocabulary": "atlas_schema_registry_v1",
        "views": views,
    }


def _build_atlas_object_kind_census(
    stats: Dict[str, float],
    atlas_service: Dict[str, Any],
    atlas_storage: Dict[str, Any],
    atlas_object_lifecycle: Dict[str, Any],
    atlas_activation_census: Dict[str, Any],
) -> Dict[str, Any]:
    objects: Dict[str, Dict[str, Any]] = {}
    counts = {
        "active": 0,
        "registered-but-proxied": 0,
        "shadow-only": 0,
        "missing": 0,
    }

    def _sum_evidence(evidence: Dict[str, Any]) -> float:
        total = 0.0
        for value in evidence.values():
            total += _to_float(value)
        return total

    def _add_object(
        name: str,
        *,
        scope: str,
        state: str,
        reason: str,
        evidence: Dict[str, Any],
    ) -> None:
        evidence_total = _sum_evidence(evidence)
        objects[name] = {
            "scope": scope,
            "state": state,
            "reason": reason,
            "evidence": evidence,
            "evidence_total": evidence_total,
        }
        counts[state] = counts.get(state, 0) + 1

    family_scopes = {
        "premphf_base": "P-scope",
        "premphf_band": "P-scope",
        "idx2row": "P-scope",
        "rowindex": "P-scope",
        "rowdescriptor": "P-scope",
    }
    for family, scope in family_scopes.items():
        evidence = {
            "frontier_events_total": _to_float(stats.get(f"atlas_census_{family}_frontier_events_total")),
            "producer_events_total": _to_float(stats.get(f"atlas_census_{family}_producer_events_total")),
            "gate_events_total": _to_float(stats.get(f"atlas_census_{family}_gate_events_total")),
            "service_events_total": _to_float(stats.get(f"atlas_census_{family}_service_events_total")),
        }
        evidence_total = _sum_evidence(evidence)
        if evidence_total == 0.0:
            state = "missing"
            reason = "no object-family evidence was observed in current counters"
        elif family == "rowindex":
            state = "shadow-only"
            reason = "rowindex only appears through shadow/frontier/gate evidence, not a formal shared lifecycle"
        else:
            state = "registered-but-proxied"
            reason = "object-family evidence exists, but it still materializes through proxy/gate seams"
        _add_object(family, scope=scope, state=state, reason=reason, evidence=evidence)

    pod_metadata_evidence = {
        "observe_total": _to_float(atlas_storage.get("pod_metadata_observe_total")),
        "unique_object_total": _to_float(atlas_object_lifecycle.get("metadata_unique_object_total")),
        "overlap_hit_total": _to_float(atlas_storage.get("pod_metadata_overlap_hit_total")),
    }
    if _sum_evidence(pod_metadata_evidence) == 0.0:
        pod_metadata_state = "missing"
        pod_metadata_reason = "pod metadata plane emitted no observe/unique evidence in current run"
    else:
        pod_metadata_state = "shadow-only"
        pod_metadata_reason = "pod metadata plane is visible as an observe/store shadow, but has no direct ready/release authority"
    _add_object(
        "pod_metadata_object",
        scope="P-scope",
        state=pod_metadata_state,
        reason=pod_metadata_reason,
        evidence=pod_metadata_evidence,
    )

    pod_owner_evidence = {
        "owner_alloc_total": _to_float(atlas_storage.get("pod_owner_owner_alloc_total")),
        "join_grant_total": _to_float(atlas_storage.get("pod_owner_join_grant_total")),
        "join_request_total": _to_float(atlas_object_lifecycle.get("rowindex", {}).get("join_request_total")),
        "owner_reject_total": _to_float(atlas_object_lifecycle.get("rowindex", {}).get("owner_reject_total")),
    }
    if _sum_evidence(pod_owner_evidence) == 0.0:
        pod_owner_state = "missing"
        pod_owner_reason = "pod owner table showed no allocation/join authority in current counters"
    else:
        pod_owner_state = "active"
        pod_owner_reason = "pod owner table is carrying explicit owner/join authority"
    _add_object(
        "pod_owner_entry",
        scope="P-scope",
        state=pod_owner_state,
        reason=pod_owner_reason,
        evidence=pod_owner_evidence,
    )

    service_evidence = {
        "materialize_total": _to_float(atlas_service.get("atlas_service_atlas_obj_materialize_total")),
        "owner_form_total": _to_float(atlas_service.get("atlas_service_atlas_obj_owner_form_total")),
        "ready_total": _to_float(atlas_service.get("atlas_service_atlas_obj_ready_total")),
        "release_total": _to_float(atlas_service.get("atlas_service_atlas_obj_release_total")),
        "private_only_total": _to_float(atlas_service.get("atlas_service_atlas_obj_private_only_total")),
    }
    if _sum_evidence(service_evidence) == 0.0:
        service_state = "missing"
        service_reason = "service table boundary emitted no object lifecycle evidence in current counters"
    else:
        service_state = "active"
        service_reason = "local service table is carrying materialize/ready/release lifecycle events"
    _add_object(
        "pe_local_service_object",
        scope="P-scope",
        state=service_state,
        reason=service_reason,
        evidence=service_evidence,
    )

    shared_weight = atlas_activation_census.get("shared_weight", {})
    shared_weight_state = shared_weight.get("state", {}) if isinstance(shared_weight, dict) else {}
    shared_weight_flags = shared_weight.get("flags", {}) if isinstance(shared_weight, dict) else {}
    evidence = {
        "mirror_only_total": _to_float(shared_weight_state.get("mirror_only", {}).get("total")),
        "actual_owner_total": _to_float(shared_weight_state.get("actual_owner", {}).get("total")),
        "owner_scope_enable_total": _to_float(shared_weight_flags.get("owner_scope_enable", {}).get("total")),
        "idx_shared_enabled_total": _to_float(shared_weight_flags.get("idx_shared_enabled", {}).get("total")),
        "value_shared_enabled_total": _to_float(shared_weight_flags.get("value_shared_enabled", {}).get("total")),
    }
    active_weight_total = evidence["mirror_only_total"] + evidence["actual_owner_total"]
    enabled_weight_total = (
        evidence["owner_scope_enable_total"]
        + evidence["idx_shared_enabled_total"]
        + evidence["value_shared_enabled_total"]
    )
    dominant_absent_reason = (
        shared_weight.get("dominant_absent_reason", {}).get("label")
        if isinstance(shared_weight.get("dominant_absent_reason"), dict)
        else None
    )
    if active_weight_total > 0.0:
        weight_state = "active"
        weight_reason = "shared-weight residency reached mirror-only or actual-owner runtime state"
    elif enabled_weight_total > 0.0:
        weight_state = "registered-but-proxied"
        weight_reason = "shared-weight enable flags are visible, but residency authority did not materialize"
    else:
        weight_state = "missing"
        if dominant_absent_reason:
            weight_reason = f"shared-weight residency absent in current run ({dominant_absent_reason})"
        else:
            weight_reason = "shared-weight residency emitted no enable or residency evidence"
    _add_object(
        "shared_weight_residency",
        scope="E/P-scope",
        state=weight_state,
        reason=weight_reason,
        evidence=evidence,
    )

    return {
        "matrix_version": 2,
        "state_taxonomy": [
            "active",
            "registered-but-proxied",
            "shadow-only",
            "missing",
        ],
        "objects": objects,
        "summary": {
            "object_count": len(objects),
            "active_count": counts["active"],
            "registered_but_proxied_count": counts["registered-but-proxied"],
            "shadow_only_count": counts["shadow-only"],
            "missing_count": counts["missing"],
            "non_missing_count": len(objects) - counts["missing"],
        },
    }


def _build_atlas_storage_authority_map(
    atlas_activation_census: Dict[str, Any],
    atlas_storage: Dict[str, Any],
    atlas_service: Dict[str, Any],
    atlas_proxy: Dict[str, Any],
    atlas_object_lifecycle: Dict[str, Any],
    atlas_object_kind_census: Dict[str, Any],
) -> Dict[str, Any]:
    shared_weight = atlas_activation_census.get("shared_weight", {})
    if not isinstance(shared_weight, dict):
        shared_weight = {}
    shared_flags = shared_weight.get("flags", {})
    shared_authority = shared_weight.get("authority", {})
    if not isinstance(shared_flags, dict):
        shared_flags = {}
    if not isinstance(shared_authority, dict):
        shared_authority = {}
    objects = atlas_object_kind_census.get("objects", {})
    if not isinstance(objects, dict):
        objects = {}

    def _sum_evidence(evidence: Dict[str, Any]) -> float:
        total = 0.0
        for value in evidence.values():
            if isinstance(value, dict):
                total += _sum_evidence(value)
            else:
                total += _to_float(value)
        return total

    def _object_state(name: str) -> str:
        payload = objects.get(name, {})
        if not isinstance(payload, dict):
            return "missing"
        return str(payload.get("state") or "missing")

    def _dominant_shared_authority(plane: str) -> str:
        payload = shared_authority.get(plane, {})
        if not isinstance(payload, dict) or not payload:
            return "absent"
        best_label = "absent"
        best_total = 0
        for label, stats in payload.items():
            total = _to_int(stats.get("total", 0)) if isinstance(stats, dict) else 0
            if total > best_total:
                best_label = label
                best_total = total
        return best_label if best_total > 0 else "absent"

    def _lifecycle_state(
        *,
        observed_total: Any = 0,
        owner_total: Any = 0,
        join_total: Any = 0,
        ready_total: Any = 0,
        release_total: Any = 0,
    ) -> str:
        if _to_int(release_total) > 0:
            return "release_visible"
        if _to_int(ready_total) > 0:
            return "ready_visible"
        if _to_int(join_total) > 0:
            return "join_visible"
        if _to_int(owner_total) > 0:
            return "owner_visible"
        if _to_int(observed_total) > 0:
            return "observed"
        return "absent"

    def _lifecycle_reason(state: str, label: str) -> str:
        if state == "release_visible":
            return f"{label} already exposes release-stage authority evidence"
        if state == "ready_visible":
            return f"{label} already exposes ready-stage authority evidence"
        if state == "join_visible":
            return f"{label} exposes join/grant-stage authority evidence"
        if state == "owner_visible":
            return f"{label} exposes owner allocation/form authority evidence"
        if state == "observed":
            return f"{label} is observed in storage/object plane but has not reached owner authority"
        return f"{label} emitted no storage authority evidence in current run"

    def _shared_reason(state: str, label: str) -> str:
        if state == "shared_active":
            return f"{label} reached shared active authority"
        if state == "mirror_only":
            return f"{label} reached mirror-only authority"
        if state == "private":
            return f"{label} remains private-resident"
        return f"{label} emitted no shared authority evidence in current run"

    def _lifecycle_stage(state: str) -> str:
        mapping = {
            "release_visible": "release",
            "ready_visible": "ready",
            "join_visible": "join",
            "owner_visible": "owner",
            "observed": "observe",
            "shared_active": "shared_active",
            "mirror_only": "mirror_only",
            "actual_owner": "actual_owner",
            "private": "private",
            "absent": "absent",
        }
        return mapping.get(state, "unknown")

    def _entry(
        name: str,
        *,
        scope: str,
        kind: str,
        authority_state: str,
        authority_reason: str,
        evidence: Dict[str, Any],
        formal_object_ref: Optional[str] = None,
        closure_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "scope": scope,
            "kind": kind,
            "authority_state": authority_state,
            "lifecycle_stage": _lifecycle_stage(authority_state),
            "authority_reason": authority_reason,
            "evidence": evidence,
            "evidence_total": _sum_evidence(evidence),
        }
        if formal_object_ref is not None:
            payload["formal_object_ref"] = formal_object_ref
        if closure_ref is not None:
            payload["closure_ref"] = closure_ref
        return payload

    idx_state = _dominant_shared_authority("idx")
    value_state = _dominant_shared_authority("value")
    entries = {
        "weight_idx_store": _entry(
            "weight_idx_store",
            scope="core-local",
            kind="storage_residency",
            authority_state=idx_state,
            authority_reason=_shared_reason(idx_state, "weight idx store"),
            evidence={
                "reads_total": _to_float(atlas_storage.get("idx_reads_total")),
                "owner_scope_enable_total": _to_float(shared_flags.get("owner_scope_enable", {}).get("total")),
                "shared_enable_total": _to_float(shared_flags.get("idx_shared_enabled", {}).get("total")),
                "private_total": _to_float(shared_authority.get("idx", {}).get("private", {}).get("total")),
                "mirror_only_total": _to_float(shared_authority.get("idx", {}).get("mirror_only", {}).get("total")),
                "shared_active_total": _to_float(shared_authority.get("idx", {}).get("shared_active", {}).get("total")),
            },
        ),
        "weight_value_store": _entry(
            "weight_value_store",
            scope="core-local",
            kind="storage_residency",
            authority_state=value_state,
            authority_reason=_shared_reason(value_state, "weight value store"),
            evidence={
                "reads_total": _to_float(atlas_storage.get("l0_reads_total")),
                "fills_total": _to_float(atlas_storage.get("l0_fill_total")),
                "owner_scope_enable_total": _to_float(shared_flags.get("owner_scope_enable", {}).get("total")),
                "shared_enable_total": _to_float(shared_flags.get("value_shared_enabled", {}).get("total")),
                "private_total": _to_float(shared_authority.get("value", {}).get("private", {}).get("total")),
                "mirror_only_total": _to_float(shared_authority.get("value", {}).get("mirror_only", {}).get("total")),
                "shared_active_total": _to_float(shared_authority.get("value", {}).get("shared_active", {}).get("total")),
            },
        ),
    }

    shared_weight_state = str(
        shared_weight.get("dominant_state", {}).get("label")
        if isinstance(shared_weight.get("dominant_state"), dict)
        else "absent"
    )
    if shared_weight_state == "absent":
        inferred_value_state = _dominant_shared_authority("value")
        if inferred_value_state == "shared_active":
            shared_weight_state = "actual_owner"
        elif inferred_value_state == "mirror_only":
            shared_weight_state = "mirror_only"
    if shared_weight_state not in {"mirror_only", "actual_owner"}:
        shared_weight_state = "absent"
    entries["shared_weight_residency"] = _entry(
        "shared_weight_residency",
        scope="E/P-scope",
        kind="semantic_residency",
        authority_state=shared_weight_state,
        authority_reason=_shared_reason(
            shared_weight_state,
            "shared weight residency",
        ),
        formal_object_ref="shared_weight_residency",
        evidence={
            "mirror_only_total": _to_float(
                shared_weight.get("state", {}).get("mirror_only", {}).get("total")
                if isinstance(shared_weight.get("state"), dict)
                else 0
            ),
            "actual_owner_total": _to_float(
                shared_weight.get("state", {}).get("actual_owner", {}).get("total")
                if isinstance(shared_weight.get("state"), dict)
                else 0
            ),
            "owner_scope_enable_total": _to_float(
                shared_flags.get("owner_scope_enable", {}).get("total")
            ),
            "idx_shared_enabled_total": _to_float(
                shared_flags.get("idx_shared_enabled", {}).get("total")
            ),
            "value_shared_enabled_total": _to_float(
                shared_flags.get("value_shared_enabled", {}).get("total")
            ),
        },
    )

    pod_metadata_state = _lifecycle_state(
        observed_total=_to_float(atlas_storage.get("pod_metadata_observe_total")),
    )
    entries["pod_metadata_plane"] = _entry(
        "pod_metadata_plane",
        scope="P-scope",
        kind="metadata_plane",
        authority_state=pod_metadata_state,
        authority_reason=_lifecycle_reason(pod_metadata_state, "pod metadata plane"),
        evidence={
            "observe_total": _to_float(atlas_storage.get("pod_metadata_observe_total")),
            "unique_object_total": _to_float(atlas_object_lifecycle.get("metadata_unique_object_total")),
            "overlap_hit_total": _to_float(atlas_storage.get("pod_metadata_overlap_hit_total")),
        },
    )

    pod_owner_state = _lifecycle_state(
        observed_total=_to_float(atlas_storage.get("pod_metadata_observe_total")),
        owner_total=_to_float(atlas_storage.get("pod_owner_owner_alloc_total")),
        join_total=_to_float(atlas_storage.get("pod_owner_join_grant_total")),
    )
    entries["pod_owner_table"] = _entry(
        "pod_owner_table",
        scope="P-scope",
        kind="owner_table",
        authority_state=pod_owner_state,
        authority_reason=_lifecycle_reason(pod_owner_state, "pod owner table"),
        evidence={
            "owner_alloc_total": _to_float(atlas_storage.get("pod_owner_owner_alloc_total")),
            "join_grant_total": _to_float(atlas_storage.get("pod_owner_join_grant_total")),
        },
    )

    service_state = _lifecycle_state(
        owner_total=_to_float(atlas_service.get("atlas_service_atlas_obj_owner_form_total")),
        ready_total=_to_float(atlas_service.get("atlas_service_atlas_obj_ready_total")),
        release_total=_to_float(atlas_service.get("atlas_service_atlas_obj_release_total")),
    )
    entries["pe_local_service_table"] = _entry(
        "pe_local_service_table",
        scope="P-scope",
        kind="service_table",
        authority_state=service_state,
        authority_reason=_lifecycle_reason(service_state, "PE local service table"),
        evidence={
            "owner_form_total": _to_float(atlas_service.get("atlas_service_atlas_obj_owner_form_total")),
            "ready_total": _to_float(atlas_service.get("atlas_service_atlas_obj_ready_total")),
            "release_total": _to_float(atlas_service.get("atlas_service_atlas_obj_release_total")),
        },
    )

    idx2_state = _lifecycle_state(
        observed_total=_to_float(objects.get("idx2row", {}).get("evidence_total")),
        owner_total=_to_float(atlas_proxy.get("idx2row", {}).get("owner_form_total")),
        ready_total=_to_float(atlas_proxy.get("idx2row", {}).get("ready_total")),
        release_total=_to_float(atlas_proxy.get("idx2row", {}).get("release_total")),
    )
    entries["idx2_object"] = _entry(
        "idx2_object",
        scope="P-scope",
        kind="object_lane",
        authority_state=idx2_state,
        authority_reason=_lifecycle_reason(idx2_state, "idx2 object"),
        formal_object_ref="idx2row",
        closure_ref="idx2_object",
        evidence={
            "object_state": _object_state("idx2row"),
            "object_evidence_total": _to_float(objects.get("idx2row", {}).get("evidence_total")),
            "owner_form_total": _to_float(atlas_proxy.get("idx2row", {}).get("owner_form_total")),
            "ready_total": _to_float(atlas_proxy.get("idx2row", {}).get("ready_total")),
            "release_total": _to_float(atlas_proxy.get("idx2row", {}).get("release_total")),
        },
    )

    preband_state = _lifecycle_state(
        observed_total=_to_float(atlas_storage.get("pod_metadata", {}).get("premphf_band", {}).get("observe_total")),
        owner_total=_to_float(atlas_storage.get("pod_owner", {}).get("premphf_band", {}).get("owner_alloc_total")),
        join_total=_to_float(atlas_object_lifecycle.get("premphf_band", {}).get("join_grant_total")),
    )
    entries["preband_object"] = _entry(
        "preband_object",
        scope="P-scope",
        kind="object_lane",
        authority_state=preband_state,
        authority_reason=_lifecycle_reason(preband_state, "preband object"),
        formal_object_ref="premphf_band",
        closure_ref="preband_object",
        evidence={
            "object_state": _object_state("premphf_band"),
            "object_evidence_total": _to_float(objects.get("premphf_band", {}).get("evidence_total")),
            "observe_total": _to_float(atlas_storage.get("pod_metadata", {}).get("premphf_band", {}).get("observe_total")),
            "owner_alloc_total": _to_float(atlas_storage.get("pod_owner", {}).get("premphf_band", {}).get("owner_alloc_total")),
            "join_grant_total": _to_float(atlas_object_lifecycle.get("premphf_band", {}).get("join_grant_total")),
        },
    )

    rowindex_state = _lifecycle_state(
        observed_total=_to_float(atlas_storage.get("pod_metadata", {}).get("rowindex", {}).get("observe_total")),
        owner_total=_to_float(atlas_object_lifecycle.get("rowindex", {}).get("join_request_total")),
        join_total=_to_float(atlas_object_lifecycle.get("rowindex", {}).get("join_grant_total")),
        ready_total=_to_float(atlas_proxy.get("rowindex", {}).get("ready_total")),
        release_total=_to_float(atlas_proxy.get("rowindex", {}).get("release_total")),
    )
    entries["rowindex_object"] = _entry(
        "rowindex_object",
        scope="P-scope",
        kind="object_lane",
        authority_state=rowindex_state,
        authority_reason=_lifecycle_reason(rowindex_state, "rowindex object"),
        formal_object_ref="rowindex",
        closure_ref="rowindex_object",
        evidence={
            "object_state": _object_state("rowindex"),
            "object_evidence_total": _to_float(objects.get("rowindex", {}).get("evidence_total")),
            "observe_total": _to_float(atlas_storage.get("pod_metadata", {}).get("rowindex", {}).get("observe_total")),
            "join_request_total": _to_float(atlas_object_lifecycle.get("rowindex", {}).get("join_request_total")),
            "join_grant_total": _to_float(atlas_object_lifecycle.get("rowindex", {}).get("join_grant_total")),
            "ready_total": _to_float(atlas_proxy.get("rowindex", {}).get("ready_total")),
            "release_total": _to_float(atlas_proxy.get("rowindex", {}).get("release_total")),
        },
    )

    summary: Dict[str, int] = {}
    for payload in entries.values():
        state = str(payload.get("authority_state") or "unknown")
        summary[state] = summary.get(state, 0) + 1
    return {
        "version": 1,
        "vocabulary": "atlas_storage_authority_map_v1",
        "entries": entries,
        "summary": summary,
    }


def _build_atlas_wms_storage_binding_map(
    atlas_storage: Dict[str, Any],
    atlas_storage_authority_map: Dict[str, Any],
    atlas_activation_census: Dict[str, Any],
) -> Dict[str, Any]:
    authority_entries = atlas_storage_authority_map.get("entries", {})
    if not isinstance(authority_entries, dict):
        authority_entries = {}
    shared_weight = atlas_activation_census.get("shared_weight", {})
    machine_chain = atlas_activation_census.get("machine_chain", {})
    if not isinstance(shared_weight, dict):
        shared_weight = {}
    if not isinstance(machine_chain, dict):
        machine_chain = {}
    dominant_absent_reason = shared_weight.get("dominant_absent_reason", {})
    runtime_requested = machine_chain.get("runtime_requested", {})
    dominant_break = machine_chain.get("dominant_break", {})
    if not isinstance(dominant_absent_reason, dict):
        dominant_absent_reason = {}
    if not isinstance(runtime_requested, dict):
        runtime_requested = {}
    if not isinstance(dominant_break, dict):
        dominant_break = {}

    def _authority_entry(name: str) -> Dict[str, Any]:
        payload = authority_entries.get(name, {})
        return payload if isinstance(payload, dict) else {}

    def _request_state(name: str) -> str:
        payload = runtime_requested.get(name, {})
        if not isinstance(payload, dict):
            payload = {}
        return "requested" if _to_int(payload.get("total", 0)) > 0 else "not_requested"

    def _entry(
        *,
        name: str,
        runtime_owner: str,
        runtime_instance_scope: str,
        namespace_scope: str,
        physical_model: str,
        physical_scope: str,
        binding_state: str,
        owner_contract_state: str,
        semantic_overlay_owner: str,
        evict_owner: str,
        evict_contract_state: str,
        release_owner: str,
        release_contract_state: str,
        fallback_owner: str,
        formalization_state: str,
        evidence: Dict[str, Any],
        absent_reason: str = "none",
        owner_request_state: str = "not_applicable",
        actual_request_state: str = "not_applicable",
        machine_break_label: str = "none",
        machine_break_stage: str = "none",
    ) -> Dict[str, Any]:
        authority = _authority_entry(name)
        return {
            "runtime_owner": runtime_owner,
            "runtime_instance_scope": runtime_instance_scope,
            "namespace_scope": namespace_scope,
            "physical_model": physical_model,
            "physical_scope": physical_scope,
            "binding_state": binding_state,
            "owner_contract_state": owner_contract_state,
            "semantic_overlay_owner": semantic_overlay_owner,
            "evict_owner": evict_owner,
            "evict_contract_state": evict_contract_state,
            "release_owner": release_owner,
            "release_contract_state": release_contract_state,
            "fallback_owner": fallback_owner,
            "formalization_state": formalization_state,
            "absent_reason": absent_reason,
            "owner_request_state": owner_request_state,
            "actual_request_state": actual_request_state,
            "machine_break_label": machine_break_label,
            "machine_break_stage": machine_break_stage,
            "authority_ref": name,
            "authority_state": str(authority.get("authority_state") or "unknown"),
            "lifecycle_stage": str(authority.get("lifecycle_stage") or "unknown"),
            "evidence": evidence,
        }

    value_authority = _authority_entry("weight_value_store")
    value_authority_state = str(value_authority.get("authority_state") or "absent")
    value_binding_state = (
        "split_binding_object"
        if value_authority_state in {"mirror_only", "shared_active"}
        else "pe_named_per_core_runtime"
    )
    value_semantic_overlay_owner = (
        "PulseSeededLineResidency"
        if value_binding_state == "split_binding_object"
        else "none"
    )
    value_release_owner = (
        "unresolved_split_binding"
        if value_binding_state == "split_binding_object"
        else "WeightMemorySubsystem"
    )
    value_release_contract_state = (
        "split_runtime_unresolved"
        if value_binding_state == "split_binding_object"
        else "runtime_owner_exact"
    )
    value_owner_contract_state = (
        "split_runtime_and_overlay"
        if value_binding_state == "split_binding_object"
        else "runtime_owner_exact"
    )
    value_formalization_state = (
        "split_binding_unresolved"
        if value_binding_state == "split_binding_object"
        else "scope_widened_private_runtime"
    )
    shared_residency_authority = _authority_entry("shared_weight_residency")
    shared_residency_state = str(
        shared_residency_authority.get("authority_state") or "absent"
    )
    shared_residency_binding_state = (
        "semantic_overlay_only"
        if shared_residency_state in {"mirror_only", "actual_owner"}
        else "absent"
    )
    shared_weight_absent_reason = str(
        dominant_absent_reason.get("label")
        or ("none" if shared_residency_binding_state == "semantic_overlay_only" else "unknown")
    )
    shared_weight_owner_request_state = _request_state("shared_weight_owner")
    shared_weight_actual_request_state = _request_state("shared_weight_actual_owner")
    shared_weight_machine_break_label = str(dominant_break.get("label") or "none")
    shared_weight_machine_break_stage = str(dominant_break.get("stage") or "none")

    entries = {
        "weight_idx_store": _entry(
            name="weight_idx_store",
            runtime_owner="WeightMemorySubsystem",
            runtime_instance_scope="per_core",
            namespace_scope="per_pe_object_name",
            physical_model="idx_sram_model",
            physical_scope="per_core_private_sram",
            binding_state="pe_named_per_core_runtime",
            owner_contract_state="runtime_owner_exact",
            semantic_overlay_owner="none",
            evict_owner="not_applicable",
            evict_contract_state="not_applicable_private_runtime",
            release_owner="not_applicable",
            release_contract_state="not_applicable_private_runtime",
            fallback_owner="WeightMemorySubsystem",
            formalization_state="scope_widened_private_runtime",
            evidence={
                "reads_total": _to_float(atlas_storage.get("idx_reads_total")),
                "authority_evidence_total": _to_float(
                    _authority_entry("weight_idx_store").get("evidence_total")
                ),
            },
        ),
        "weight_value_store": _entry(
            name="weight_value_store",
            runtime_owner="WeightMemorySubsystem",
            runtime_instance_scope="per_core",
            namespace_scope="per_pe_object_name",
            physical_model="l0_sram_model",
            physical_scope="per_core_private_sram",
            binding_state=value_binding_state,
            owner_contract_state=value_owner_contract_state,
            semantic_overlay_owner=value_semantic_overlay_owner,
            evict_owner="WeightMemorySubsystem",
            evict_contract_state="runtime_owner_exact",
            release_owner=value_release_owner,
            release_contract_state=value_release_contract_state,
            fallback_owner="WeightMemorySubsystem",
            formalization_state=value_formalization_state,
            evidence={
                "reads_total": _to_float(atlas_storage.get("l0_reads_total")),
                "fills_total": _to_float(atlas_storage.get("l0_fill_total")),
                "authority_evidence_total": _to_float(
                    value_authority.get("evidence_total")
                ),
            },
        ),
        "shared_weight_residency": _entry(
            name="shared_weight_residency",
            runtime_owner=(
                "PulseSeededLineResidency"
                if shared_residency_binding_state == "semantic_overlay_only"
                else "none"
            ),
            runtime_instance_scope="per_pe_semantic_overlay",
            namespace_scope="per_pe_object_name",
            physical_model="semantic_residency_overlay",
            physical_scope="no_formal_local_storage_contract",
            binding_state=shared_residency_binding_state,
            owner_contract_state=(
                "semantic_overlay_non_formal"
                if shared_residency_binding_state == "semantic_overlay_only"
                else "absent"
            ),
            semantic_overlay_owner=(
                "PulseSeededLineResidency"
                if shared_residency_binding_state == "semantic_overlay_only"
                else "none"
            ),
            evict_owner="unresolved_non_formal_owner",
            evict_contract_state=(
                "non_formal_overlay_unresolved"
                if shared_residency_binding_state == "semantic_overlay_only"
                else "absent"
            ),
            release_owner="unresolved_non_formal_owner",
            release_contract_state=(
                "non_formal_overlay_unresolved"
                if shared_residency_binding_state == "semantic_overlay_only"
                else "absent"
            ),
            fallback_owner="WeightMemorySubsystem",
            formalization_state=(
                "semantic_overlay_unresolved"
                if shared_residency_binding_state == "semantic_overlay_only"
                else "absent"
            ),
            absent_reason=shared_weight_absent_reason,
            owner_request_state=shared_weight_owner_request_state,
            actual_request_state=shared_weight_actual_request_state,
            machine_break_label=shared_weight_machine_break_label,
            machine_break_stage=shared_weight_machine_break_stage,
            evidence={
                "authority_evidence_total": _to_float(
                    shared_residency_authority.get("evidence_total")
                ),
                "mirror_only_total": _to_float(
                    shared_residency_authority.get("evidence", {}).get("mirror_only_total")
                    if isinstance(shared_residency_authority.get("evidence"), dict)
                    else 0
                ),
                "actual_owner_total": _to_float(
                    shared_residency_authority.get("evidence", {}).get("actual_owner_total")
                    if isinstance(shared_residency_authority.get("evidence"), dict)
                    else 0
                ),
            },
        ),
    }

    summary: Dict[str, int] = {}
    for payload in entries.values():
        state = str(payload.get("binding_state") or "unknown")
        summary[state] = summary.get(state, 0) + 1
    return {
        "version": 2,
        "vocabulary": "atlas_wms_storage_binding_map_v2",
        "entries": entries,
        "summary": summary,
    }


def _build_atlas_binding_unresolved_ledger(
    atlas_wms_storage_binding_map: Dict[str, Any],
) -> Dict[str, Any]:
    binding_entries = atlas_wms_storage_binding_map.get("entries", {})
    if not isinstance(binding_entries, dict):
        binding_entries = {}

    def _binding_entry(name: str) -> Dict[str, Any]:
        payload = binding_entries.get(name, {})
        return payload if isinstance(payload, dict) else {}

    def _entry(
        *,
        name: str,
        formalization_state: str,
        unresolved_edges: List[str],
        reason: str,
        evidence_refs: List[str],
    ) -> Dict[str, Any]:
        binding = _binding_entry(name)
        payload = {
            "binding_state": str(binding.get("binding_state") or "unknown"),
            "formalization_state": formalization_state,
            "unresolved_edges": [str(item) for item in unresolved_edges],
            "unresolved_edges_count": len(unresolved_edges),
            "runtime_owner": str(binding.get("runtime_owner") or "unknown"),
            "fallback_owner": str(binding.get("fallback_owner") or "unknown"),
            "reason": reason,
            "evidence_refs": [str(item) for item in evidence_refs],
        }
        for key in (
            "absent_reason",
            "owner_request_state",
            "actual_request_state",
            "machine_break_label",
            "machine_break_stage",
        ):
            if key in binding:
                payload[key] = binding.get(key)
        return payload

    idx_binding = _binding_entry("weight_idx_store")
    idx_formalization_state = str(
        idx_binding.get("formalization_state") or "aligned_or_absent"
    )
    idx_edges: List[str] = []
    idx_reason = "weight idx store emitted no unresolved binding edge in current machine-readable contract"
    if idx_formalization_state == "scope_widened_private_runtime":
        idx_edges = ["scope_widening_without_shared_arbitration"]
        idx_reason = (
            "weight idx store keeps a PE-scoped object name, but runtime storage remains "
            "per-core private without shared arbitration"
        )

    value_binding = _binding_entry("weight_value_store")
    value_formalization_state = str(
        value_binding.get("formalization_state") or "aligned_or_absent"
    )
    value_edges: List[str] = []
    value_reason = "weight value store emitted no unresolved binding edge in current machine-readable contract"
    if value_formalization_state == "split_binding_unresolved":
        value_edges = [
            "scope_widening_without_shared_arbitration",
            "split_runtime_binding",
            "release_owner_unresolved",
        ]
        value_reason = (
            "weight value store is still split between per-core WMS runtime storage and "
            "semantic residency overlay ownership"
        )
    elif value_formalization_state == "scope_widened_private_runtime":
        value_edges = ["scope_widening_without_shared_arbitration"]
        value_reason = (
            "weight value store keeps a PE-scoped object name, but runtime storage remains "
            "per-core private without shared arbitration"
        )

    shared_binding = _binding_entry("shared_weight_residency")
    shared_formalization_state = str(
        shared_binding.get("formalization_state") or "absent"
    )
    shared_edges: List[str] = []
    shared_reason = "shared weight residency is absent in current machine-readable binding contract"
    if shared_formalization_state == "semantic_overlay_unresolved":
        shared_edges = [
            "release_owner_unresolved",
            "evict_owner_unresolved",
            "no_formal_local_storage_contract",
        ]
        shared_reason = (
            "shared weight residency exists only as a semantic overlay owner and still lacks "
            "formal local-storage release/evict contract"
        )

    entries = {
        "weight_idx_store": _entry(
            name="weight_idx_store",
            formalization_state=idx_formalization_state,
            unresolved_edges=idx_edges,
            reason=idx_reason,
            evidence_refs=[
                "atlas_wms_storage_binding_map.entries.weight_idx_store",
                "atlas_storage_authority_map.entries.weight_idx_store",
            ],
        ),
        "weight_value_store": _entry(
            name="weight_value_store",
            formalization_state=value_formalization_state,
            unresolved_edges=value_edges,
            reason=value_reason,
            evidence_refs=[
                "atlas_wms_storage_binding_map.entries.weight_value_store",
                "atlas_storage_authority_map.entries.weight_value_store",
            ],
        ),
        "shared_weight_residency": _entry(
            name="shared_weight_residency",
            formalization_state=shared_formalization_state,
            unresolved_edges=shared_edges,
            reason=shared_reason,
            evidence_refs=[
                "atlas_wms_storage_binding_map.entries.shared_weight_residency",
                "atlas_storage_authority_map.entries.shared_weight_residency",
            ],
        ),
    }

    summary: Dict[str, int] = {}
    for payload in entries.values():
        state = str(payload.get("formalization_state") or "unknown")
        summary[state] = summary.get(state, 0) + 1
    return {
        "version": 1,
        "vocabulary": "atlas_binding_unresolved_ledger_v1",
        "entries": entries,
        "summary": summary,
    }


def _build_atlas_cross_plane_visibility(
    atlas_activation_census: Dict[str, Any],
    atlas_contract_mismatch: Dict[str, Any],
    atlas_object_kind_census: Dict[str, Any],
) -> Dict[str, Any]:
    machine_chain = atlas_activation_census.get("machine_chain", {})
    if not isinstance(machine_chain, dict):
        machine_chain = {}
    build_effective = machine_chain.get("build_effective", {})
    runtime_requested = machine_chain.get("runtime_requested", {})
    runtime_effective = machine_chain.get("runtime_effective", {})
    runtime_constructed = machine_chain.get("runtime_constructed", {})
    if not isinstance(build_effective, dict):
        build_effective = {}
    if not isinstance(runtime_requested, dict):
        runtime_requested = {}
    if not isinstance(runtime_effective, dict):
        runtime_effective = {}
    if not isinstance(runtime_constructed, dict):
        runtime_constructed = {}

    phase = atlas_contract_mismatch.get("phase", {})
    if not isinstance(phase, dict):
        phase = {}
    objects = atlas_object_kind_census.get("objects", {})
    if not isinstance(objects, dict):
        objects = {}

    def _runtime_payload(
        requested_payload: Any,
        effective_payload: Any,
        constructed_payloads: Dict[str, Any],
    ) -> Dict[str, Any]:
        constructed_detail = {
            key: _counter_total(value) for key, value in constructed_payloads.items()
        }
        requested_total = _counter_total(requested_payload)
        effective_total = _counter_total(effective_payload)
        constructed_total = max(constructed_detail.values()) if constructed_detail else 0
        return {
            "requested_total": requested_total,
            "effective_total": effective_total,
            "constructed_total": constructed_total,
            "constructed_detail": constructed_detail,
            "signal_total": requested_total + effective_total + constructed_total,
        }

    def _objects_payload(names: List[str]) -> Dict[str, Any]:
        states: Dict[str, str] = {}
        active_count = 0
        registered_count = 0
        shadow_only_count = 0
        missing_count = 0
        evidence_total = 0.0
        for name in names:
            payload = objects.get(name, {})
            if not isinstance(payload, dict):
                payload = {}
            state = str(payload.get("state") or "missing")
            states[name] = state
            evidence_total += _to_float(payload.get("evidence_total"))
            if state == "active":
                active_count += 1
            elif state == "registered-but-proxied":
                registered_count += 1
            elif state == "shadow-only":
                shadow_only_count += 1
            else:
                missing_count += 1
        return {
            "states": states,
            "active_count": active_count,
            "registered_but_proxied_count": registered_count,
            "shadow_only_count": shadow_only_count,
            "missing_count": missing_count,
            "non_missing_count": len(names) - missing_count,
            "evidence_total": evidence_total,
        }

    def _gap_state(
        *,
        build_flag: int,
        runtime_signal_total: int,
        object_non_missing_count: int,
    ) -> str:
        if build_flag > 0 and object_non_missing_count > 0 and runtime_signal_total == 0:
            return "build_on_object_visible_runtime_dark"
        if build_flag > 0 and object_non_missing_count > 0 and runtime_signal_total > 0:
            return "build_on_object_visible_runtime_visible"
        if build_flag > 0 and object_non_missing_count == 0 and runtime_signal_total > 0:
            return "build_on_runtime_visible_object_dark"
        if build_flag > 0:
            return "build_on_both_planes_dark"
        if object_non_missing_count > 0:
            return "build_off_object_visible"
        if runtime_signal_total > 0:
            return "build_off_runtime_visible"
        return "build_off_both_planes_dark"

    def _gap_reason(
        *,
        gap_state: str,
        runtime_label: str,
        object_label: str,
    ) -> str:
        if gap_state == "build_on_object_visible_runtime_dark":
            return f"build-effective is on and {object_label} is visible, but {runtime_label} counters remain zero"
        if gap_state == "build_on_object_visible_runtime_visible":
            return f"{object_label} and {runtime_label} are both visible"
        if gap_state == "build_on_runtime_visible_object_dark":
            return f"{runtime_label} is visible while {object_label} remains dark"
        if gap_state == "build_on_both_planes_dark":
            return f"build-effective is on, but both {object_label} and {runtime_label} remain dark"
        if gap_state == "build_off_object_visible":
            return f"{object_label} is visible even though build-effective is off"
        if gap_state == "build_off_runtime_visible":
            return f"{runtime_label} is visible even though build-effective is off"
        return f"both {object_label} and {runtime_label} remain dark"

    def _entry(
        *,
        build_flag: int,
        requested_payload: Any,
        effective_payload: Any,
        constructed_payloads: Dict[str, Any],
        object_names: List[str],
        contract_phase_payload: Any,
        runtime_label: str,
        object_label: str,
    ) -> Dict[str, Any]:
        runtime_payload = _runtime_payload(
            requested_payload, effective_payload, constructed_payloads
        )
        object_payload = _objects_payload(object_names)
        gap_state = _gap_state(
            build_flag=build_flag,
            runtime_signal_total=runtime_payload["signal_total"],
            object_non_missing_count=object_payload["non_missing_count"],
        )
        contract_state = {}
        if isinstance(contract_phase_payload, dict):
            contract_state = {
                "state": contract_phase_payload.get("state"),
                "reason": contract_phase_payload.get("reason"),
            }
        return {
            "build_effective": build_flag,
            "runtime": runtime_payload,
            "objects": object_payload,
            "contract_phase": contract_state,
            "gap_state": gap_state,
            "reason": _gap_reason(
                gap_state=gap_state,
                runtime_label=runtime_label,
                object_label=object_label,
            ),
        }

    entries = {
        "local_storage_vs_objects": _entry(
            build_flag=_to_int(build_effective.get("local_storage", 0)),
            requested_payload={},
            effective_payload=runtime_effective.get("local_storage"),
            constructed_payloads={},
            object_names=[
                "idx2row",
                "premphf_base",
                "premphf_band",
                "rowdescriptor",
                "rowindex",
                "pod_metadata_object",
                "pod_owner_entry",
                "pe_local_service_object",
            ],
            contract_phase_payload=phase.get("local_storage"),
            runtime_label="local-storage runtime",
            object_label="PE-local object plane",
        ),
        "pod_runtime_vs_objects": _entry(
            build_flag=_to_int(build_effective.get("pe_internal_pod", 0)),
            requested_payload=runtime_requested.get("pe_internal_pod"),
            effective_payload=runtime_effective.get("pe_internal_pod"),
            constructed_payloads={
                "pod_metadata_plane": runtime_constructed.get("pod_metadata_plane"),
                "pod_owner_table": runtime_constructed.get("pod_owner_table"),
                "service_table": runtime_constructed.get("service_table"),
            },
            object_names=[
                "pod_metadata_object",
                "pod_owner_entry",
                "pe_local_service_object",
            ],
            contract_phase_payload=phase.get("pod_service"),
            runtime_label="pod requested/effective/constructed runtime",
            object_label="pod/service object plane",
        ),
        "rowindex_object_vs_pod_runtime": _entry(
            build_flag=_to_int(build_effective.get("pe_internal_pod", 0)),
            requested_payload=runtime_requested.get("pe_internal_pod"),
            effective_payload=runtime_effective.get("pe_internal_pod"),
            constructed_payloads={
                "pod_metadata_plane": runtime_constructed.get("pod_metadata_plane"),
                "pod_owner_table": runtime_constructed.get("pod_owner_table"),
                "service_table": runtime_constructed.get("service_table"),
            },
            object_names=["rowindex"],
            contract_phase_payload=phase.get("pod_service"),
            runtime_label="pod requested/effective/constructed runtime",
            object_label="rowindex object plane",
        ),
        "shared_weight_vs_residency": _entry(
            build_flag=_to_int(build_effective.get("shared_weight_owner", 0)),
            requested_payload=runtime_requested.get("shared_weight_owner"),
            effective_payload=runtime_effective.get("shared_weight_owner"),
            constructed_payloads={
                "shared_weight_plane": runtime_constructed.get("shared_weight_plane"),
            },
            object_names=["shared_weight_residency"],
            contract_phase_payload=phase.get("shared_weight_owner"),
            runtime_label="shared-weight requested/effective/constructed runtime",
            object_label="shared-weight residency plane",
        ),
    }
    summary_counts: Dict[str, int] = {}
    for entry in entries.values():
        gap_state = str(entry.get("gap_state") or "unknown")
        summary_counts[gap_state] = summary_counts.get(gap_state, 0) + 1
    return {
        "version": 1,
        "entries": entries,
        "summary": summary_counts,
    }


def _build_atlas_surface_ledger(
    atlas_config_resolution: Dict[str, Any],
    atlas_activation_census: Dict[str, Any],
    atlas_contract_mismatch: Dict[str, Any],
    atlas_cross_plane_visibility: Dict[str, Any],
    atlas_surface_state: Dict[str, Any],
) -> Dict[str, Any]:
    machine_chain = atlas_activation_census.get("machine_chain", {})
    activation_gate = atlas_activation_census.get("activation_gate", {})
    if not isinstance(machine_chain, dict):
        machine_chain = {}
    if not isinstance(activation_gate, dict):
        activation_gate = {}
    build_effective = machine_chain.get("build_effective", {})
    runtime_requested = machine_chain.get("runtime_requested", {})
    runtime_effective = machine_chain.get("runtime_effective", {})
    runtime_constructed = machine_chain.get("runtime_constructed", {})
    if not isinstance(build_effective, dict):
        build_effective = {}
    if not isinstance(runtime_requested, dict):
        runtime_requested = {}
    if not isinstance(runtime_effective, dict):
        runtime_effective = {}
    if not isinstance(runtime_constructed, dict):
        runtime_constructed = {}

    phase = atlas_contract_mismatch.get("phase", {})
    storage_authority = atlas_contract_mismatch.get("storage_authority", {})
    if not isinstance(phase, dict):
        phase = {}
    if not isinstance(storage_authority, dict):
        storage_authority = {}

    surfaces = atlas_surface_state.get("surfaces", {})
    if not isinstance(surfaces, dict):
        surfaces = {}

    visibility_entries = atlas_cross_plane_visibility.get("entries", {})
    if not isinstance(visibility_entries, dict):
        visibility_entries = {}

    def _config_payload(*keys: str) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for key in keys:
            entry = atlas_config_resolution.get(key)
            if isinstance(entry, dict):
                payload[key] = entry
        return payload

    def _runtime_payload(
        *,
        build_flag: int,
        requested_payload: Any = None,
        effective_payload: Any = None,
        constructed_payloads: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        detail = {}
        if isinstance(constructed_payloads, dict):
            detail = {
                key: _counter_total(value) for key, value in constructed_payloads.items()
            }
        return {
            "build_effective": _to_int(build_flag),
            "requested_total": _counter_total(requested_payload),
            "effective_total": _counter_total(effective_payload),
            "constructed_total": max(detail.values()) if detail else 0,
            "constructed_detail": detail,
        }

    def _surface_state_payload(name: str) -> Dict[str, Any]:
        payload = surfaces.get(name, {})
        return payload if isinstance(payload, dict) else {}

    def _phase_payload(name: str) -> Dict[str, Any]:
        payload = phase.get(name, {})
        return payload if isinstance(payload, dict) else {}

    def _visibility_payload(name: str) -> Dict[str, Any]:
        payload = visibility_entries.get(name, {})
        return payload if isinstance(payload, dict) else {}

    entries = {
        "local_storage": {
            "config_resolution": _config_payload("local_storage"),
            "runtime": _runtime_payload(
                build_flag=_to_int(build_effective.get("local_storage", 0)),
                requested_payload=activation_gate.get("local_storage_enable"),
                effective_payload=runtime_effective.get("local_storage"),
            ),
            "contract_phase": _phase_payload("local_storage"),
            "surface_state": _surface_state_payload("local_storage"),
            "visibility": _visibility_payload("local_storage_vs_objects"),
        },
        "pulse": {
            "config_resolution": _config_payload("pulse"),
            "runtime": _runtime_payload(
                build_flag=_to_int(build_effective.get("pulse", 0)),
                requested_payload=runtime_requested.get("pulse"),
                effective_payload=runtime_effective.get("pulse"),
                constructed_payloads={
                    "pulse_fabric": runtime_constructed.get("pulse_fabric")
                },
            ),
            "contract_phase": _phase_payload("pulse"),
            "surface_state": _surface_state_payload("pulse"),
        },
        "pulse_osa": {
            "config_resolution": _config_payload("pulse_osa"),
            "runtime": _runtime_payload(
                build_flag=_to_int(build_effective.get("pulse_osa", 0)),
                requested_payload=runtime_requested.get("pulse_osa"),
                effective_payload=runtime_effective.get("pulse_osa"),
            ),
            "contract_phase": _phase_payload("pulse_osa"),
            "surface_state": _surface_state_payload("pulse_osa"),
        },
        "shared_weight": {
            "config_resolution": _config_payload(
                "pulse_osa", "shared_weight_owner", "shared_weight_actual_owner"
            ),
            "runtime": _runtime_payload(
                build_flag=_to_int(build_effective.get("shared_weight_owner", 0)),
                requested_payload=runtime_requested.get("shared_weight_owner"),
                effective_payload=runtime_effective.get("shared_weight_owner"),
                constructed_payloads={
                    "shared_weight_plane": runtime_constructed.get("shared_weight_plane")
                },
            ),
            "contract_phase": _phase_payload("shared_weight_owner"),
            "storage_authority": (
                storage_authority.get("shared_weight", {})
                if isinstance(storage_authority.get("shared_weight"), dict)
                else {}
            ),
            "surface_state": _surface_state_payload("shared_weight_authority"),
            "visibility": _visibility_payload("shared_weight_vs_residency"),
        },
        "pod_service": {
            "config_resolution": _config_payload(
                "pe_internal_pod",
                "pe_internal_pod_metadata",
                "pe_internal_pod_owner",
                "pe_internal_pod_join",
                "pe_internal_pod_ready",
            ),
            "runtime": _runtime_payload(
                build_flag=_to_int(build_effective.get("pe_internal_pod", 0)),
                requested_payload=runtime_requested.get("pe_internal_pod"),
                effective_payload=runtime_effective.get("pe_internal_pod"),
                constructed_payloads={
                    "pod_metadata_plane": runtime_constructed.get("pod_metadata_plane"),
                    "pod_owner_table": runtime_constructed.get("pod_owner_table"),
                    "service_table": runtime_constructed.get("service_table"),
                },
            ),
            "contract_phase": _phase_payload("pod_service"),
            "surface_state": _surface_state_payload("pod_service"),
            "visibility": _visibility_payload("pod_runtime_vs_objects"),
        },
        "rowindex_object": {
            "config_resolution": _config_payload(
                "pulse_osa",
                "pe_internal_pod",
                "pe_internal_pod_metadata",
                "pe_internal_pod_owner",
                "pe_internal_pod_join",
                "pe_internal_pod_ready",
            ),
            "runtime": _runtime_payload(
                build_flag=_to_int(build_effective.get("pe_internal_pod", 0)),
                requested_payload=runtime_requested.get("pe_internal_pod"),
                effective_payload=runtime_effective.get("pe_internal_pod"),
                constructed_payloads={
                    "pod_metadata_plane": runtime_constructed.get("pod_metadata_plane"),
                    "pod_owner_table": runtime_constructed.get("pod_owner_table"),
                    "service_table": runtime_constructed.get("service_table"),
                },
            ),
            "contract_phase": _phase_payload("pod_service"),
            "surface_state": _surface_state_payload("pod_service"),
            "visibility": _visibility_payload("rowindex_object_vs_pod_runtime"),
        },
    }
    for entry in entries.values():
        config_payload = entry.get("config_resolution", {})
        if isinstance(config_payload, dict) and len(config_payload) == 1:
            entry["resolution"] = next(iter(config_payload.values()))
        elif isinstance(config_payload, dict):
            entry["resolution"] = config_payload
        else:
            entry["resolution"] = {}
        runtime_payload = entry.get("runtime", {})
        if isinstance(runtime_payload, dict):
            entry["chain"] = {
                "build_effective": _to_int(runtime_payload.get("build_effective", 0)),
                "runtime_requested_total": _to_int(
                    runtime_payload.get("requested_total", 0)
                ),
                "runtime_effective_total": _to_int(
                    runtime_payload.get("effective_total", 0)
                ),
                "runtime_constructed_total": _to_int(
                    runtime_payload.get("constructed_total", 0)
                ),
                "runtime_constructed_detail": (
                    runtime_payload.get("constructed_detail", {})
                    if isinstance(runtime_payload.get("constructed_detail"), dict)
                    else {}
                ),
            }
        else:
            entry["chain"] = {}
        contract_payload = {"phase": entry.get("contract_phase", {})}
        if "storage_authority" in entry:
            contract_payload["storage_authority"] = entry.get("storage_authority", {})
        entry["contract"] = contract_payload
    return {
        "version": 1,
        "vocabulary": "atlas_surface_ledger_v1",
        "surface_vocabulary": "atlas_surface_ledger_v1",
        "entries": entries,
    }


def _build_atlas_surface_coverage(
    atlas_surface_ledger: Dict[str, Any],
) -> Dict[str, Any]:
    entries = atlas_surface_ledger.get("entries", {})
    if not isinstance(entries, dict):
        entries = {}

    def _config_status(payload: Any) -> str:
        if not isinstance(payload, dict) or not payload:
            return "unknown"
        items = [value for value in payload.values() if isinstance(value, dict)]
        if not items:
            items = [payload] if isinstance(payload, dict) else []
        resolved_on = any(_to_int(item.get("resolved", 0)) > 0 for item in items)
        conflict = any(bool(item.get("conflict")) for item in items)
        override = any(str(item.get("source") or "") == "override" for item in items)
        if not resolved_on:
            return "resolved_off"
        if conflict:
            return "resolved_on_conflict"
        if override:
            return "resolved_on_override"
        return "resolved_on"

    def _runtime_status(payload: Any) -> str:
        if not isinstance(payload, dict):
            return "dark"
        total = (
            _to_int(payload.get("requested_total", 0))
            + _to_int(payload.get("effective_total", 0))
            + _to_int(payload.get("constructed_total", 0))
        )
        return "visible" if total > 0 else "dark"

    def _object_status(payload: Any) -> str:
        if not isinstance(payload, dict):
            return "not_applicable"
        objects = payload.get("objects", {})
        if not isinstance(objects, dict):
            return "not_applicable"
        non_missing = _to_int(objects.get("non_missing_count", 0))
        return "visible" if non_missing > 0 else "dark"

    def _storage_authority_status(payload: Any) -> str:
        if not isinstance(payload, dict):
            return "not_applicable"
        state = str(payload.get("state") or "")
        if not state:
            return "not_applicable"
        if state in {"actual_owner", "mirror_only"}:
            return "visible"
        return "dark"

    def _surface_presence(payload: Any, key: str) -> str:
        if not isinstance(payload, dict):
            return "dark"
        value = str(payload.get(key) or "")
        return "visible" if value else "dark"

    def _coverage_status(
        *,
        config: str,
        runtime: str,
        object_state: str,
    ) -> str:
        if config == "resolved_off":
            return "build_off"
        if object_state == "visible" and runtime == "dark":
            return "object_visible_runtime_dark"
        if object_state == "dark" and runtime == "dark":
            return "build_on_both_planes_dark"
        if object_state == "visible" and runtime == "visible":
            return "object_and_runtime_visible"
        if object_state == "dark" and runtime == "visible":
            return "runtime_visible_object_dark"
        if object_state == "not_applicable" and runtime == "dark":
            return "runtime_dark_no_object_plane"
        if object_state == "not_applicable" and runtime == "visible":
            return "runtime_visible_no_object_plane"
        return "unknown"

    def _coverage_reason(entry: Dict[str, Any], coverage_status: str) -> str:
        phase = entry.get("contract", {}).get("phase", {})
        visibility = entry.get("visibility", {})
        if coverage_status == "build_off":
            return str(phase.get("reason") or "surface is resolved off at config plane")
        if isinstance(visibility, dict):
            reason = visibility.get("reason")
            if reason:
                return str(reason)
        if isinstance(phase, dict):
            reason = phase.get("reason")
            if reason:
                return str(reason)
        return "surface coverage derived from surface ledger state"

    coverage_entries: Dict[str, Any] = {}
    summary_counts: Dict[str, int] = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict):
            continue
        plane_status = {
            "config": _config_status(entry.get("config_resolution")),
            "runtime": _runtime_status(entry.get("runtime")),
            "object": _object_status(entry.get("visibility")),
            "storage_authority": _storage_authority_status(
                entry.get("contract", {}).get("storage_authority")
            ),
            "contract": _surface_presence(entry.get("contract", {}).get("phase"), "state"),
            "surface_state": _surface_presence(entry.get("surface_state"), "machine_state"),
        }
        expected_planes = ["config", "runtime", "contract", "surface_state"]
        if plane_status["object"] != "not_applicable":
            expected_planes.append("object")
        if plane_status["storage_authority"] != "not_applicable":
            expected_planes.append("storage_authority")
        visible_planes = [
            plane
            for plane in expected_planes
            if plane_status.get(plane) not in {"dark", "resolved_off", "not_applicable", "unknown"}
        ]
        dark_planes = [
            plane
            for plane in expected_planes
            if plane_status.get(plane) in {"dark", "resolved_off"}
        ]
        coverage_status = _coverage_status(
            config=plane_status["config"],
            runtime=plane_status["runtime"],
            object_state=plane_status["object"],
        )
        summary_counts[coverage_status] = summary_counts.get(coverage_status, 0) + 1
        coverage_entries[name] = {
            "expected_planes": expected_planes,
            "visible_planes": visible_planes,
            "dark_planes": dark_planes,
            "plane_status": plane_status,
            "coverage_status": coverage_status,
            "reason": _coverage_reason(entry, coverage_status),
        }
    return {
        "version": 1,
        "vocabulary": "atlas_surface_coverage_v1",
        "entries": coverage_entries,
        "summary": summary_counts,
    }


def _build_atlas_surface_probe_ledger(
    atlas_surface_coverage: Dict[str, Any],
    atlas_activation_census: Dict[str, Any],
    atlas_surface_ledger: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    coverage_entries = atlas_surface_coverage.get("entries", {})
    if not isinstance(coverage_entries, dict):
        coverage_entries = {}
    ledger_entries: Dict[str, Any] = {}
    if isinstance(atlas_surface_ledger, dict):
        candidate = atlas_surface_ledger.get("entries", {})
        if isinstance(candidate, dict):
            ledger_entries = candidate
    activation_gate = atlas_activation_census.get("activation_gate", {})
    enable_state = atlas_activation_census.get("enable_state", {})
    if not isinstance(activation_gate, dict):
        activation_gate = {}
    if not isinstance(enable_state, dict):
        enable_state = {}

    sections = {
        "activation_gate": activation_gate,
        "enable_state": enable_state,
    }

    def _probe_total(section_name: str, key: str) -> Optional[int]:
        section = sections.get(section_name)
        if not isinstance(section, dict) or key not in section:
            return None
        return _counter_total(section.get(key))

    def _probe_status(
        coverage_status: str,
        missing_probe: List[str],
        observed_nonzero_probe: List[str],
        observed_zero_probe: List[str],
    ) -> str:
        if coverage_status == "build_off":
            return "build_off"
        if missing_probe and observed_nonzero_probe:
            return "missing_probe_with_nonzero"
        if missing_probe and observed_zero_probe:
            return "missing_probe_and_zero"
        if missing_probe:
            return "missing_probe"
        if observed_nonzero_probe:
            return "observed_some_nonzero"
        return "observed_all_zero"

    def _probe_reason(entry: Dict[str, Any], probe_status: str) -> str:
        reason = str(entry.get("reason") or "")
        if probe_status == "build_off":
            return reason or "surface is resolved off, runtime probe activation is not expected"
        if probe_status == "missing_probe_and_zero":
            return reason or "some expected probes are unmapped and the mapped probes remain zero"
        if probe_status == "missing_probe_with_nonzero":
            return reason or "some probes are active, but direct probe coverage is still incomplete"
        if probe_status == "missing_probe":
            return reason or "expected direct probes are not mapped in the current ledger"
        if probe_status == "observed_some_nonzero":
            return reason or "mapped probes show nonzero activity in current run"
        return reason or "all mapped probes are present but remain zero in current run"

    def _contract_phase(ledger_entry: Dict[str, Any]) -> Tuple[str, str]:
        if not isinstance(ledger_entry, dict):
            return "unknown", ""
        contract = ledger_entry.get("contract", {})
        if not isinstance(contract, dict):
            return "unknown", ""
        phase = contract.get("phase", {})
        if not isinstance(phase, dict):
            return "unknown", ""
        state = str(phase.get("state") or "unknown")
        reason = str(phase.get("reason") or "")
        return state, reason

    def _zero_probe_cause(
        probe_status: str,
        coverage_status: str,
        contract_phase_state: str,
    ) -> Optional[str]:
        if probe_status != "observed_all_zero":
            return None
        if contract_phase_state in {
            "build_off",
            "configured_not_effective",
            "runtime_not_requested",
            "requested_not_effective",
            "effective_not_constructed",
            "constructed_without_effective",
            "ready_visible_but_commit_blocked",
        }:
            return contract_phase_state
        if coverage_status == "object_visible_runtime_dark":
            return "runtime_dark_object_visible"
        if coverage_status == "build_on_both_planes_dark":
            return "runtime_dark_object_dark"
        if coverage_status == "build_off":
            return "build_off"
        return "all_zero_unclassified"

    def _probe_total_from_observed(
        observed_probe: Dict[str, Any], probe_id: str
    ) -> int:
        payload = observed_probe.get(probe_id)
        if not isinstance(payload, dict):
            return 0
        return _to_int(payload.get("total", 0))

    def _rowindex_effective_gap_cause(
        observed_probe: Dict[str, Any],
    ) -> Tuple[bool, Optional[str], List[str]]:
        requested_total = _probe_total_from_observed(
            observed_probe, "activation_gate.rowindex_requested"
        )
        constructed_total = _probe_total_from_observed(
            observed_probe, "activation_gate.rowindex_constructed"
        )
        effective_total = _probe_total_from_observed(
            observed_probe, "enable_state.rowindex_effective"
        )
        if requested_total <= 0 or constructed_total <= 0 or effective_total > 0:
            return False, None, []

        gate_probe_ids = [
            "enable_state.rowindex_gate_pulse_osa",
            "enable_state.rowindex_gate_metadata_txn",
            "enable_state.rowindex_gate_metadata_mask",
            "enable_state.rowindex_gate_pod_enable",
            "enable_state.rowindex_gate_pod_metadata_enable",
            "enable_state.rowindex_gate_pod_owner_enable",
            "enable_state.rowindex_gate_service_table_present",
        ]
        failed_gates: List[str] = []
        for probe_id in gate_probe_ids:
            if _probe_total_from_observed(observed_probe, probe_id) <= 0:
                failed_gates.append(probe_id)
        if failed_gates:
            return True, failed_gates[0], failed_gates
        return True, "rowindex_effective_gate_unknown", []

    probe_entries: Dict[str, Any] = {}
    summary_counts: Dict[str, int] = {}
    for surface, specs in _ATLAS_SURFACE_PROBE_FIELDS.items():
        coverage_entry = coverage_entries.get(surface, {})
        if not isinstance(coverage_entry, dict):
            coverage_entry = {}
        ledger_entry = ledger_entries.get(surface, {})
        if not isinstance(ledger_entry, dict):
            ledger_entry = {}
        expected_probe: List[str] = []
        observed_probe: Dict[str, Any] = {}
        observed_nonzero_probe: List[str] = []
        observed_zero_probe: List[str] = []
        missing_probe: List[str] = []
        for probe_id, section_name, key in specs:
            expected_probe.append(probe_id)
            if not section_name or not key:
                missing_probe.append(probe_id)
                continue
            total = _probe_total(section_name, key)
            if total is None:
                missing_probe.append(probe_id)
                continue
            state = "observed_nonzero" if total > 0 else "observed_zero"
            observed_probe[probe_id] = {
                "section": section_name,
                "key": key,
                "total": total,
                "state": state,
            }
            if total > 0:
                observed_nonzero_probe.append(probe_id)
            else:
                observed_zero_probe.append(probe_id)
        coverage_status = str(coverage_entry.get("coverage_status") or "unknown")
        probe_status = _probe_status(
            coverage_status,
            missing_probe,
            observed_nonzero_probe,
            observed_zero_probe,
        )
        contract_phase_state, contract_phase_reason = _contract_phase(ledger_entry)
        zero_probe_cause = _zero_probe_cause(
            probe_status=probe_status,
            coverage_status=coverage_status,
            contract_phase_state=contract_phase_state,
        )
        effective_gap = False
        effective_gap_cause = None
        effective_gap_blocked_gates: List[str] = []
        if surface == "rowindex_object":
            (
                effective_gap,
                effective_gap_cause,
                effective_gap_blocked_gates,
            ) = _rowindex_effective_gap_cause(observed_probe)
        summary_counts[probe_status] = summary_counts.get(probe_status, 0) + 1
        probe_entries[surface] = {
            "coverage_status": coverage_status,
            "contract_phase_state": contract_phase_state,
            "contract_phase_reason": contract_phase_reason,
            "expected_probe": expected_probe,
            "observed_probe": observed_probe,
            "observed_nonzero_probe": observed_nonzero_probe,
            "observed_zero_probe": observed_zero_probe,
            "missing_probe": missing_probe,
            "probe_status": probe_status,
            "zero_probe_cause": zero_probe_cause,
            "effective_gap": effective_gap,
            "effective_gap_cause": effective_gap_cause,
            "effective_gap_blocked_gates": effective_gap_blocked_gates,
            "reason": _probe_reason(coverage_entry, probe_status),
        }
    return {
        "version": 1,
        "vocabulary": "atlas_surface_probe_ledger_v1",
        "entries": probe_entries,
        "summary": summary_counts,
    }


def _build_atlas_surface_probe_backlog(
    atlas_surface_probe_ledger: Dict[str, Any],
) -> Dict[str, Any]:
    entries = atlas_surface_probe_ledger.get("entries", {})
    if not isinstance(entries, dict):
        entries = {}

    def _action_and_priority(surface: str, payload: Dict[str, Any]) -> Tuple[str, str]:
        probe_status = str(payload.get("probe_status") or "unknown")
        if surface == "rowindex_object" and bool(payload.get("effective_gap")):
            return "investigate_effective_gap", "p1"
        if surface == "rowindex_object" and probe_status in {
            "missing_probe",
            "missing_probe_and_zero",
            "missing_probe_with_nonzero",
        }:
            return "add_direct_rowindex_probes", "p0"
        if probe_status == "observed_all_zero":
            return "investigate_zero_probes", "p1"
        if probe_status == "observed_some_nonzero":
            return "monitor_nonzero_probes", "p2"
        if probe_status == "build_off":
            return "defer_build_off", "p3"
        if probe_status in {"missing_probe", "missing_probe_and_zero", "missing_probe_with_nonzero"}:
            return "add_missing_probes", "p2"
        return "monitor", "p3"

    backlog_entries: Dict[str, Any] = {}
    summary: Dict[str, int] = {}
    for surface, payload in entries.items():
        if not isinstance(payload, dict):
            continue
        action, priority = _action_and_priority(surface, payload)
        expected_probe = payload.get("expected_probe", [])
        if not isinstance(expected_probe, list):
            expected_probe = []
        missing_probe = payload.get("missing_probe", [])
        if not isinstance(missing_probe, list):
            missing_probe = []
        observed_zero_probe = payload.get("observed_zero_probe", [])
        if not isinstance(observed_zero_probe, list):
            observed_zero_probe = []
        observed_nonzero_probe = payload.get("observed_nonzero_probe", [])
        if not isinstance(observed_nonzero_probe, list):
            observed_nonzero_probe = []
        if action == "add_direct_rowindex_probes":
            target_probe = missing_probe
        elif action == "investigate_effective_gap":
            blocked = payload.get("effective_gap_blocked_gates", [])
            target_probe = blocked if isinstance(blocked, list) else []
        elif action == "investigate_zero_probes":
            target_probe = observed_zero_probe
        elif action == "monitor_nonzero_probes":
            target_probe = observed_nonzero_probe
        elif action == "add_missing_probes":
            target_probe = missing_probe
        else:
            target_probe = []
        backlog_entries[surface] = {
            "priority": priority,
            "action": action,
            "coverage_status": payload.get("coverage_status"),
            "contract_phase_state": payload.get("contract_phase_state"),
            "contract_phase_reason": payload.get("contract_phase_reason"),
            "probe_status": payload.get("probe_status"),
            "zero_probe_cause": payload.get("zero_probe_cause"),
            "effective_gap": bool(payload.get("effective_gap")),
            "effective_gap_cause": payload.get("effective_gap_cause"),
            "effective_gap_blocked_gates": (
                payload.get("effective_gap_blocked_gates", [])
                if isinstance(payload.get("effective_gap_blocked_gates"), list)
                else []
            ),
            "expected_probe": expected_probe,
            "missing_probe": missing_probe,
            "observed_zero_probe": observed_zero_probe,
            "observed_nonzero_probe": observed_nonzero_probe,
            "target_probe": target_probe,
            "reason": payload.get("reason"),
        }
        summary_key = f"{priority}_{action}"
        summary[summary_key] = summary.get(summary_key, 0) + 1
    return {
        "version": 1,
        "vocabulary": "atlas_surface_probe_backlog_v1",
        "entries": backlog_entries,
        "summary": summary,
    }


def _build_atlas_object_closure(
    atlas_surface_ledger: Dict[str, Any],
    atlas_surface_coverage: Dict[str, Any],
    atlas_surface_probe_ledger: Dict[str, Any],
    atlas_storage_authority_map: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ledger_entries = atlas_surface_ledger.get("entries", {})
    coverage_entries = atlas_surface_coverage.get("entries", {})
    probe_entries = atlas_surface_probe_ledger.get("entries", {})
    authority_entries = (
        atlas_storage_authority_map.get("entries", {})
        if isinstance(atlas_storage_authority_map, dict)
        else {}
    )
    if not isinstance(ledger_entries, dict):
        ledger_entries = {}
    if not isinstance(coverage_entries, dict):
        coverage_entries = {}
    if not isinstance(probe_entries, dict):
        probe_entries = {}
    if not isinstance(authority_entries, dict):
        authority_entries = {}

    def _probe_total(probe_entry: Dict[str, Any], probe_id: str) -> int:
        observed = probe_entry.get("observed_probe", {})
        if not isinstance(observed, dict):
            return 0
        payload = observed.get(probe_id, {})
        if not isinstance(payload, dict):
            return 0
        return _to_int(payload.get("total", 0))

    def _object_visibility_state(ledger_entry: Dict[str, Any], object_name: Optional[str]) -> str:
        if not object_name:
            return "not_applicable"
        visibility = ledger_entry.get("visibility", {})
        if not isinstance(visibility, dict):
            return "dark"
        objects = visibility.get("objects", {})
        if not isinstance(objects, dict):
            return "dark"
        states = objects.get("states", {})
        if not isinstance(states, dict):
            return "dark"
        state = str(states.get(object_name) or "missing")
        return "visible" if state != "missing" else "dark"

    def _closure_coverage_status(
        config_status: str,
        runtime_visible: bool,
        object_state: str,
    ) -> str:
        if config_status == "resolved_off":
            return "build_off"
        if object_state == "visible" and runtime_visible:
            return "object_and_runtime_visible"
        if object_state == "visible" and not runtime_visible:
            return "object_visible_runtime_dark"
        if object_state == "dark" and runtime_visible:
            return "runtime_visible_object_dark"
        if object_state == "dark" and not runtime_visible:
            return "build_on_both_planes_dark"
        if object_state == "not_applicable" and runtime_visible:
            return "runtime_visible_no_object_plane"
        if object_state == "not_applicable" and not runtime_visible:
            return "runtime_dark_no_object_plane"
        return "unknown"

    def _closure_dark_planes(
        coverage_entry: Dict[str, Any],
        object_state: str,
    ) -> List[str]:
        dark_planes = coverage_entry.get("dark_planes", [])
        if not isinstance(dark_planes, list):
            dark_planes = []
        result = [str(item) for item in dark_planes]
        if object_state == "visible":
            return [plane for plane in result if plane != "object"]
        if object_state == "dark" and "object" not in result:
            return result + ["object"]
        return result

    def _entry(
        surface: str,
        *,
        source_surface: str,
        object_name: Optional[str] = None,
        use_rowindex_direct_totals: bool = False,
        authority_ref: Optional[str] = None,
        formal_object_ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        ledger_entry = ledger_entries.get(source_surface, {})
        coverage_entry = coverage_entries.get(source_surface, {})
        probe_entry = probe_entries.get(source_surface, {})
        authority_entry = authority_entries.get(authority_ref or "", {})
        if not isinstance(ledger_entry, dict):
            ledger_entry = {}
        if not isinstance(coverage_entry, dict):
            coverage_entry = {}
        if not isinstance(probe_entry, dict):
            probe_entry = {}
        if not isinstance(authority_entry, dict):
            authority_entry = {}
        runtime = ledger_entry.get("runtime", {})
        if not isinstance(runtime, dict):
            runtime = {}
        blocked_gates = probe_entry.get("effective_gap_blocked_gates", [])
        if not isinstance(blocked_gates, list):
            blocked_gates = []
        requested_total = _to_int(runtime.get("requested_total", 0))
        effective_total = _to_int(runtime.get("effective_total", 0))
        constructed_total = _to_int(runtime.get("constructed_total", 0))
        if use_rowindex_direct_totals:
            requested_total = _probe_total(probe_entry, "activation_gate.rowindex_requested")
            effective_total = _probe_total(probe_entry, "enable_state.rowindex_effective")
            constructed_total = _probe_total(probe_entry, "activation_gate.rowindex_constructed")
        object_state = _object_visibility_state(ledger_entry, object_name)
        coverage_status = _closure_coverage_status(
            str(coverage_entry.get("plane_status", {}).get("config") or "unknown")
            if isinstance(coverage_entry.get("plane_status"), dict)
            else "unknown",
            (requested_total + effective_total + constructed_total) > 0,
            object_state,
        )
        payload = {
            "requested": {
                "total": requested_total,
            },
            "effective": {
                "total": effective_total,
            },
            "constructed": {
                "total": constructed_total,
                "detail": (
                    runtime.get("constructed_detail", {})
                    if isinstance(runtime.get("constructed_detail"), dict)
                    else {}
                ),
            },
            "coverage_status": coverage_status,
            "dark_planes": _closure_dark_planes(coverage_entry, object_state),
            "machine_reason": str(coverage_entry.get("reason") or ""),
            "config_resolution": (
                ledger_entry.get("config_resolution", {})
                if isinstance(ledger_entry.get("config_resolution"), dict)
                else {}
            ),
            "contract_phase_state": str(probe_entry.get("contract_phase_state") or "unknown"),
            "probe_status": str(probe_entry.get("probe_status") or "unknown"),
            "zero_probe_cause": probe_entry.get("zero_probe_cause"),
            "effective_gap": bool(probe_entry.get("effective_gap")) if use_rowindex_direct_totals else False,
            "effective_gap_cause": probe_entry.get("effective_gap_cause") if use_rowindex_direct_totals else None,
            "blocked_gates": blocked_gates if use_rowindex_direct_totals else [],
        }
        if authority_ref is not None:
            payload["authority_ref"] = authority_ref
            payload["authority_state"] = str(
                authority_entry.get("authority_state") or "unknown"
            )
        if formal_object_ref is not None:
            payload["formal_object_ref"] = formal_object_ref
        return payload

    return {
        "version": 1,
        "vocabulary": "atlas_object_closure_v1",
        "entries": {
            "rowindex_object": _entry(
                "rowindex_object",
                source_surface="rowindex_object",
                object_name="rowindex",
                use_rowindex_direct_totals=True,
                authority_ref="rowindex_object",
                formal_object_ref="rowindex",
            ),
            "idx2_object": _entry(
                "idx2_object",
                source_surface="local_storage",
                object_name="idx2row",
                authority_ref="idx2_object",
                formal_object_ref="idx2row",
            ),
            "preband_object": _entry(
                "preband_object",
                source_surface="local_storage",
                object_name="premphf_band",
                authority_ref="preband_object",
                formal_object_ref="premphf_band",
            ),
        },
    }


def _build_atlas_machine_chain(
    effective: Dict[str, Any],
    activation_gate: Dict[str, Dict[str, Any]],
    enable_state: Dict[str, Dict[str, Any]],
    control_state: Dict[str, Dict[str, Any]],
    shared_weight_absent_reason: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    build_effective = {
        "local_storage": _effective_flag_any(
            effective, ("local_storage_enable",)
        ),
        "pe_internal_pod": _effective_flag_any(
            effective, ("pe_internal_pod_enable",)
        ),
        "pulse": _effective_flag_any(
            effective, ("pulse", "enable"), ("pulse_enable",)
        ),
        "pulse_osa": _effective_flag_any(
            effective, ("pulse", "osa_enable"), ("pulse_osa_enable",)
        ),
        "shared_weight_owner": _effective_flag_any(
            effective,
            ("pulse", "osa_shared_weight_owner_enable"),
            ("pulse_osa_shared_weight_owner_enable",),
        ),
        "shared_weight_actual_owner": _effective_flag_any(
            effective,
            ("pulse", "osa_shared_weight_owner_actual_enable"),
            ("pulse_osa_shared_weight_owner_actual_enable",),
        ),
    }
    runtime_requested = {
        "pulse": activation_gate.get("pulse_requested", {"total": 0, "share": None}),
        "pulse_osa": activation_gate.get("pulse_osa_requested", {"total": 0, "share": None}),
        "shared_weight_owner": activation_gate.get(
            "shared_weight_owner_requested", {"total": 0, "share": None}
        ),
        "shared_weight_actual_owner": activation_gate.get(
            "shared_weight_actual_requested", {"total": 0, "share": None}
        ),
        "pe_internal_pod": activation_gate.get(
            "pe_internal_pod_requested", {"total": 0, "share": None}
        ),
    }
    runtime_effective = {
        "local_storage": enable_state.get("local_storage", {"total": 0, "share": None}),
        "pe_internal_pod": enable_state.get("pe_internal_pod", {"total": 0, "share": None}),
        "pulse": enable_state.get("pulse_effective", {"total": 0, "share": None}),
        "pulse_osa": enable_state.get("pulse_osa", {"total": 0, "share": None}),
        "shared_weight_owner": enable_state.get(
            "pulse_osa_shared_weight_owner", {"total": 0, "share": None}
        ),
        "shared_weight_actual_owner": enable_state.get(
            "pulse_osa_shared_weight_actual", {"total": 0, "share": None}
        ),
    }
    runtime_constructed = {
        "pulse_fabric": activation_gate.get(
            "pulse_fabric_constructed", {"total": 0, "share": None}
        ),
        "shared_weight_plane": activation_gate.get(
            "shared_weight_plane_constructed", {"total": 0, "share": None}
        ),
        "pod_metadata_plane": activation_gate.get(
            "pod_metadata_plane_constructed", {"total": 0, "share": None}
        ),
        "pod_owner_table": activation_gate.get(
            "pod_owner_table_constructed", {"total": 0, "share": None}
        ),
        "service_table": activation_gate.get(
            "service_table_constructed", {"total": 0, "share": None}
        ),
    }
    dominant_break = _machine_break(
        "none", 0, None, "runtime", "no dominant break detected"
    )
    if (
        build_effective["local_storage"] == 0
        and shared_weight_absent_reason.get("local_storage_gate", {}).get("total", 0) > 0
    ):
        dominant_break = _machine_break(
            "local_storage",
            _to_int(shared_weight_absent_reason["local_storage_gate"]["total"]),
            shared_weight_absent_reason["local_storage_gate"].get("share"),
            "build_effective",
            "shared_weight absent reason dominated by local_storage_gate",
        )
    elif (
        build_effective["pulse_osa"] == 0
        and shared_weight_absent_reason.get("pulse_osa_gate", {}).get("total", 0) > 0
    ):
        dominant_break = _machine_break(
            "pulse_osa",
            _to_int(shared_weight_absent_reason["pulse_osa_gate"]["total"]),
            shared_weight_absent_reason["pulse_osa_gate"].get("share"),
            "build_effective",
            "shared_weight absent reason dominated by pulse_osa_gate",
        )
    elif (
        build_effective["shared_weight_owner"] == 0
        and shared_weight_absent_reason.get("owner_request_gate", {}).get("total", 0) > 0
    ):
        dominant_break = _machine_break(
            "shared_weight_owner",
            _to_int(shared_weight_absent_reason["owner_request_gate"]["total"]),
            shared_weight_absent_reason["owner_request_gate"].get("share"),
            "runtime_requested",
            "shared_weight absent reason dominated by owner_request_gate",
        )
    elif runtime_constructed["shared_weight_plane"].get("total", 0) == 0 and runtime_effective[
        "shared_weight_owner"
    ].get("total", 0) > 0:
        dominant_break = _machine_break(
            "shared_weight_plane",
            _to_int(runtime_effective["shared_weight_owner"]["total"]),
            runtime_effective["shared_weight_owner"].get("share"),
            "runtime_constructed",
            "shared weight owner effective but shared_weight_plane not constructed",
        )
    elif runtime_constructed["pulse_fabric"].get("total", 0) == 0 and runtime_effective[
        "pulse"
    ].get("total", 0) > 0:
        dominant_break = _machine_break(
            "pulse_fabric",
            _to_int(runtime_effective["pulse"]["total"]),
            runtime_effective["pulse"].get("share"),
            "runtime_constructed",
            "pulse effective but pulse_fabric not constructed",
        )
    elif control_state.get("fabric_absent", {}).get("total", 0) > 0:
        dominant_break = _machine_break(
            "fabric_absent",
            _to_int(control_state["fabric_absent"]["total"]),
            control_state["fabric_absent"].get("share"),
            "control_runtime",
            "control runtime dominated by fabric_absent",
        )
    return {
        "build_effective": build_effective,
        "runtime_requested": runtime_requested,
        "runtime_effective": runtime_effective,
        "runtime_constructed": runtime_constructed,
        "dominant_break": dominant_break,
    }


def _build_atlas_contract_mismatch(
    census: Dict[str, Any],
    atlas_sync: Dict[str, Any],
) -> Dict[str, Any]:
    pe_count = _to_int(census.get("pe_count", 0))
    machine_chain = census.get("machine_chain", {})
    if not isinstance(machine_chain, dict):
        machine_chain = {}
    build_effective = machine_chain.get("build_effective", {})
    runtime_requested = machine_chain.get("runtime_requested", {})
    runtime_effective = machine_chain.get("runtime_effective", {})
    runtime_constructed = machine_chain.get("runtime_constructed", {})
    if not isinstance(build_effective, dict):
        build_effective = {}
    if not isinstance(runtime_requested, dict):
        runtime_requested = {}
    if not isinstance(runtime_effective, dict):
        runtime_effective = {}
    if not isinstance(runtime_constructed, dict):
        runtime_constructed = {}

    shared_weight = census.get("shared_weight", {})
    control_runtime = census.get("control_runtime", {})
    if not isinstance(shared_weight, dict):
        shared_weight = {}
    if not isinstance(control_runtime, dict):
        control_runtime = {}
    shared_weight_absent_reason = shared_weight.get("absent_reason", {})
    dominant_shared_state = shared_weight.get("dominant_state", {})
    dominant_absent_reason = shared_weight.get("dominant_absent_reason", {})
    dominant_control = control_runtime.get("dominant_state", {})
    if not isinstance(shared_weight_absent_reason, dict):
        shared_weight_absent_reason = {}
    if not isinstance(dominant_shared_state, dict):
        dominant_shared_state = {}
    if not isinstance(dominant_absent_reason, dict):
        dominant_absent_reason = {}
    if not isinstance(dominant_control, dict):
        dominant_control = {}

    local_storage_effective_total = _counter_total(runtime_effective.get("local_storage"))
    local_storage_gap = (
        pe_count
        if _to_int(build_effective.get("local_storage", 0)) == 0
        else _count_gap(pe_count, local_storage_effective_total)
    )
    if _to_int(build_effective.get("local_storage", 0)) == 0:
        local_storage_phase = _phase_mismatch_entry(
            "build_off",
            reason="effective_config.local_storage_enable=0",
            mismatch_count=pe_count,
            mismatch_share=_share_from_count(pe_count, pe_count),
            build_effective=0,
            runtime_effective_total=local_storage_effective_total,
        )
    elif local_storage_effective_total == 0:
        local_storage_phase = _phase_mismatch_entry(
            "configured_not_effective",
            reason="local storage configured but no PE reported local_storage effective",
            mismatch_count=local_storage_gap,
            mismatch_share=_share_from_count(local_storage_gap, pe_count),
            build_effective=_to_int(build_effective.get("local_storage", 0)),
            runtime_effective_total=local_storage_effective_total,
        )
    elif local_storage_effective_total < pe_count:
        local_storage_phase = _phase_mismatch_entry(
            "partial_effective_gap",
            reason="only a subset of PEs reported local_storage effective",
            mismatch_count=local_storage_gap,
            mismatch_share=_share_from_count(local_storage_gap, pe_count),
            build_effective=_to_int(build_effective.get("local_storage", 0)),
            runtime_effective_total=local_storage_effective_total,
        )
    else:
        local_storage_phase = _phase_mismatch_entry(
            "aligned_active",
            reason="local storage is effective on all observed PEs",
            mismatch_count=0,
            mismatch_share=_share_from_count(0, pe_count),
            build_effective=_to_int(build_effective.get("local_storage", 0)),
            runtime_effective_total=local_storage_effective_total,
        )

    def _phase_from_chain(
        *,
        surface: str,
        build_flag: int,
        requested_payload: Any,
        effective_payload: Any,
        constructed_payload: Any = None,
        build_reason: str,
        request_reason: str,
        effective_reason: str,
        constructed_reason: str,
        aligned_reason: str,
    ) -> Dict[str, Any]:
        requested_total = _counter_total(requested_payload)
        effective_total = _counter_total(effective_payload)
        constructed_total = _counter_total(constructed_payload)
        gap_requested_to_effective = _count_gap(requested_total, effective_total)
        gap_effective_to_constructed = _count_gap(effective_total, constructed_total)
        if build_flag == 0:
            return _phase_mismatch_entry(
                "build_off",
                reason=build_reason,
                mismatch_count=pe_count,
                mismatch_share=_share_from_count(pe_count, pe_count),
                build_effective=build_flag,
                runtime_requested_total=requested_total,
                runtime_effective_total=effective_total,
                runtime_constructed_total=constructed_total if constructed_payload is not None else None,
                gap_requested_to_effective=gap_requested_to_effective,
                gap_effective_to_constructed=gap_effective_to_constructed if constructed_payload is not None else None,
            )
        if effective_total == 0 and constructed_total > 0:
            return _phase_mismatch_entry(
                "constructed_without_effective",
                reason=constructed_reason,
                mismatch_count=constructed_total,
                mismatch_share=_share_from_count(constructed_total, pe_count),
                build_effective=build_flag,
                runtime_requested_total=requested_total,
                runtime_effective_total=effective_total,
                runtime_constructed_total=constructed_total if constructed_payload is not None else None,
                gap_requested_to_effective=gap_requested_to_effective,
                gap_effective_to_constructed=gap_effective_to_constructed if constructed_payload is not None else None,
            )
        if requested_total == 0:
            return _phase_mismatch_entry(
                "runtime_not_requested",
                reason=request_reason,
                mismatch_count=pe_count,
                mismatch_share=_share_from_count(pe_count, pe_count),
                build_effective=build_flag,
                runtime_requested_total=requested_total,
                runtime_effective_total=effective_total,
                runtime_constructed_total=constructed_total if constructed_payload is not None else None,
                gap_requested_to_effective=gap_requested_to_effective,
                gap_effective_to_constructed=gap_effective_to_constructed if constructed_payload is not None else None,
            )
        if gap_requested_to_effective > 0:
            return _phase_mismatch_entry(
                "requested_not_effective",
                reason=effective_reason,
                mismatch_count=gap_requested_to_effective,
                mismatch_share=_share_from_count(gap_requested_to_effective, pe_count),
                build_effective=build_flag,
                runtime_requested_total=requested_total,
                runtime_effective_total=effective_total,
                runtime_constructed_total=constructed_total if constructed_payload is not None else None,
                gap_requested_to_effective=gap_requested_to_effective,
                gap_effective_to_constructed=gap_effective_to_constructed if constructed_payload is not None else None,
            )
        if constructed_payload is not None and gap_effective_to_constructed > 0:
            return _phase_mismatch_entry(
                "effective_not_constructed",
                reason=constructed_reason,
                mismatch_count=gap_effective_to_constructed,
                mismatch_share=_share_from_count(gap_effective_to_constructed, pe_count),
                build_effective=build_flag,
                runtime_requested_total=requested_total,
                runtime_effective_total=effective_total,
                runtime_constructed_total=constructed_total,
                gap_requested_to_effective=gap_requested_to_effective,
                gap_effective_to_constructed=gap_effective_to_constructed,
            )
        return _phase_mismatch_entry(
            "aligned_active",
            reason=aligned_reason,
            mismatch_count=0,
            mismatch_share=_share_from_count(0, pe_count),
            build_effective=build_flag,
            runtime_requested_total=requested_total,
            runtime_effective_total=effective_total,
            runtime_constructed_total=constructed_total if constructed_payload is not None else None,
            gap_requested_to_effective=gap_requested_to_effective,
            gap_effective_to_constructed=gap_effective_to_constructed if constructed_payload is not None else None,
        )

    pulse_phase = _phase_from_chain(
        surface="pulse",
        build_flag=_to_int(build_effective.get("pulse", 0)),
        requested_payload=runtime_requested.get("pulse"),
        effective_payload=runtime_effective.get("pulse"),
        constructed_payload=runtime_constructed.get("pulse_fabric"),
        build_reason="effective_config.pulse.enable=0",
        request_reason="pulse is build-enabled but no PE requested pulse at runtime",
        effective_reason="pulse was requested but never became effective",
        constructed_reason="pulse became effective or constructed without a matching effective/constructed closure",
        aligned_reason="pulse requested/effective/constructed chain is aligned",
    )
    pulse_osa_phase = _phase_from_chain(
        surface="pulse_osa",
        build_flag=_to_int(build_effective.get("pulse_osa", 0)),
        requested_payload=runtime_requested.get("pulse_osa"),
        effective_payload=runtime_effective.get("pulse_osa"),
        build_reason="effective_config.pulse.osa_enable=0",
        request_reason="pulse OSA is build-enabled but no PE requested pulse_osa at runtime",
        effective_reason="pulse OSA was requested but never became effective",
        constructed_reason="pulse OSA has no separate constructed plane in this ledger",
        aligned_reason="pulse OSA requested/effective chain is aligned",
    )
    shared_weight_owner_phase = _phase_from_chain(
        surface="shared_weight_owner",
        build_flag=_to_int(build_effective.get("shared_weight_owner", 0)),
        requested_payload=runtime_requested.get("shared_weight_owner"),
        effective_payload=runtime_effective.get("shared_weight_owner"),
        constructed_payload=runtime_constructed.get("shared_weight_plane"),
        build_reason="effective_config.pulse.osa_shared_weight_owner_enable=0",
        request_reason="shared weight owner is build-enabled but no PE requested owner scope at runtime",
        effective_reason="shared weight owner was requested but never became effective",
        constructed_reason="shared weight owner became effective without constructing shared_weight_plane",
        aligned_reason="shared weight owner and shared_weight_plane are aligned",
    )

    pod_requested_total = _counter_total(runtime_requested.get("pe_internal_pod"))
    pod_effective_total = _counter_total(runtime_effective.get("pe_internal_pod"))
    pod_constructed_total = max(
        _counter_total(runtime_constructed.get("pod_metadata_plane")),
        _counter_total(runtime_constructed.get("pod_owner_table")),
        _counter_total(runtime_constructed.get("service_table")),
    )
    pod_gap_requested_to_effective = _count_gap(pod_requested_total, pod_effective_total)
    pod_gap_effective_to_constructed = _count_gap(pod_effective_total, pod_constructed_total)
    if _to_int(build_effective.get("pe_internal_pod", 0)) == 0:
        pod_phase = _phase_mismatch_entry(
            "build_off",
            reason="effective_config.pe_internal_pod_enable=0",
            mismatch_count=pe_count,
            mismatch_share=_share_from_count(pe_count, pe_count),
            build_effective=0,
            runtime_requested_total=pod_requested_total,
            runtime_effective_total=pod_effective_total,
            runtime_constructed_total=pod_constructed_total,
            gap_requested_to_effective=pod_gap_requested_to_effective,
            gap_effective_to_constructed=pod_gap_effective_to_constructed,
        )
    elif pod_requested_total == 0:
        pod_phase = _phase_mismatch_entry(
            "runtime_not_requested",
            reason="PE-internal pod is build-enabled but no PE requested the pod path at runtime",
            mismatch_count=pe_count,
            mismatch_share=_share_from_count(pe_count, pe_count),
            build_effective=_to_int(build_effective.get("pe_internal_pod", 0)),
            runtime_requested_total=pod_requested_total,
            runtime_effective_total=pod_effective_total,
            runtime_constructed_total=pod_constructed_total,
            gap_requested_to_effective=pod_gap_requested_to_effective,
            gap_effective_to_constructed=pod_gap_effective_to_constructed,
        )
    elif pod_gap_requested_to_effective > 0:
        pod_phase = _phase_mismatch_entry(
            "requested_not_effective",
            reason="PE-internal pod was requested but never became effective on all requesting PEs",
            mismatch_count=pod_gap_requested_to_effective,
            mismatch_share=_share_from_count(pod_gap_requested_to_effective, pe_count),
            build_effective=_to_int(build_effective.get("pe_internal_pod", 0)),
            runtime_requested_total=pod_requested_total,
            runtime_effective_total=pod_effective_total,
            runtime_constructed_total=pod_constructed_total,
            gap_requested_to_effective=pod_gap_requested_to_effective,
            gap_effective_to_constructed=pod_gap_effective_to_constructed,
        )
    elif pod_gap_effective_to_constructed > 0:
        pod_phase = _phase_mismatch_entry(
            "effective_not_constructed",
            reason="PE-internal pod became effective but metadata/owner/service planes were not all constructed",
            mismatch_count=pod_gap_effective_to_constructed,
            mismatch_share=_share_from_count(pod_gap_effective_to_constructed, pe_count),
            build_effective=_to_int(build_effective.get("pe_internal_pod", 0)),
            runtime_requested_total=pod_requested_total,
            runtime_effective_total=pod_effective_total,
            runtime_constructed_total=pod_constructed_total,
            gap_requested_to_effective=pod_gap_requested_to_effective,
            gap_effective_to_constructed=pod_gap_effective_to_constructed,
        )
    else:
        pod_phase = _phase_mismatch_entry(
            "aligned_active",
            reason="PE-internal pod requested/effective/constructed chain is aligned",
            mismatch_count=0,
            mismatch_share=_share_from_count(0, pe_count),
            build_effective=_to_int(build_effective.get("pe_internal_pod", 0)),
            runtime_requested_total=pod_requested_total,
            runtime_effective_total=pod_effective_total,
            runtime_constructed_total=pod_constructed_total,
            gap_requested_to_effective=pod_gap_requested_to_effective,
            gap_effective_to_constructed=pod_gap_effective_to_constructed,
        )

    dominant_shared_state_label = dominant_shared_state.get("label")
    dominant_shared_state_count = _to_int(dominant_shared_state.get("count", 0))
    dominant_shared_state_share = dominant_shared_state.get("share")
    dominant_absent_reason_label = dominant_absent_reason.get("label")
    dominant_absent_reason_count = _to_int(dominant_absent_reason.get("count", 0))
    dominant_absent_reason_share = dominant_absent_reason.get("share")

    if dominant_absent_reason_label == "local_storage_gate":
        storage_authority = _phase_mismatch_entry(
            "gated_by_local_storage",
            reason="shared weight object is absent because local storage gate dominates",
            mismatch_count=dominant_absent_reason_count,
            mismatch_share=dominant_absent_reason_share,
        )
    elif dominant_absent_reason_label == "pulse_osa_gate":
        storage_authority = _phase_mismatch_entry(
            "gated_by_pulse_osa",
            reason="shared weight object is absent because pulse OSA gate dominates",
            mismatch_count=dominant_absent_reason_count,
            mismatch_share=dominant_absent_reason_share,
        )
    elif dominant_absent_reason_label == "owner_request_gate":
        storage_authority = _phase_mismatch_entry(
            "gated_by_owner_request",
            reason="shared weight object is absent because owner request gate dominates",
            mismatch_count=dominant_absent_reason_count,
            mismatch_share=dominant_absent_reason_share,
        )
    elif dominant_shared_state_label == "mirror_only":
        storage_authority = _phase_mismatch_entry(
            "mirror_only",
            reason="shared weight residency exists only as mirror-only authority",
            mismatch_count=dominant_shared_state_count,
            mismatch_share=dominant_shared_state_share,
        )
    elif dominant_shared_state_label == "actual_owner":
        storage_authority = _phase_mismatch_entry(
            "actual_owner",
            reason="shared weight residency reached actual-owner authority",
            mismatch_count=0,
            mismatch_share=_share_from_count(0, pe_count),
        )
    else:
        storage_authority = _phase_mismatch_entry(
            "absent",
            reason="shared weight object is absent without a stronger authority state",
            mismatch_count=dominant_shared_state_count,
            mismatch_share=dominant_shared_state_share,
        )
    storage_authority["dominant_state_label"] = dominant_shared_state_label
    storage_authority["dominant_absent_reason_label"] = dominant_absent_reason_label

    dominant_control_label = dominant_control.get("label")
    dominant_control_count = _to_int(dominant_control.get("count", 0))
    dominant_control_share = dominant_control.get("share")
    control_state = "aligned_active" if dominant_control_label == "consumed_active" else (
        dominant_control_label or "no_control_runtime_state"
    )
    control_runtime_ledger = {
        "state": control_state,
        "count": dominant_control_count,
        "share": dominant_control_share,
        "reason": control_runtime.get("interpretation", "no control runtime interpretation"),
    }

    ready_blocked_total = _to_int(atlas_sync.get("retire_ready_but_blocked_edges_total"))
    barrier_wait_total = _to_int(atlas_sync.get("retire_wait_cycles_due_to_barrier_total"))
    retire_wait_total = _to_int(atlas_sync.get("retire_wait_cycles_total"))
    if ready_blocked_total > 0:
        sync_state = "ready_visible_but_commit_blocked"
        sync_reason = "ready became visible before commit could retire"
        sync_count = ready_blocked_total
    elif barrier_wait_total > 0:
        sync_state = "barrier_wait"
        sync_reason = "retire waited on barrier after machine activity became visible"
        sync_count = barrier_wait_total
    elif retire_wait_total > 0:
        sync_state = "retire_wait"
        sync_reason = "retire waited without a stronger ready/barrier mismatch"
        sync_count = retire_wait_total
    else:
        sync_state = "clean"
        sync_reason = "no sync-vs-commit mismatch was observed in current counters"
        sync_count = 0

    return {
        "dominant": machine_chain.get("dominant_break", {}),
        "phase": {
            "local_storage": local_storage_phase,
            "pulse": pulse_phase,
            "pulse_osa": pulse_osa_phase,
            "shared_weight_owner": shared_weight_owner_phase,
            "pod_service": pod_phase,
        },
        "storage_authority": {
            "shared_weight": storage_authority,
        },
        "control_runtime": control_runtime_ledger,
        "sync": {
            "state": sync_state,
            "reason": sync_reason,
            "mismatch_count": sync_count,
            "ready_visible_but_commit_blocked_edges_total": ready_blocked_total,
            "retire_wait_cycles_due_to_barrier_total": barrier_wait_total,
            "retire_wait_cycles_total": retire_wait_total,
        },
    }


def _build_atlas_activation_census(
    stats: Dict[str, float],
    model: Dict[str, Any],
    by_component: Dict[str, Dict[str, float]],
    effective: Dict[str, Any],
) -> Dict[str, Any]:
    pe_count = _determine_pe_count(model, by_component)
    enable_state = {
        label: _one_hot_summary(stats, key, pe_count)
        for label, key in _ATLAS_ENABLE_STATE_FIELDS
    }
    activation_gate = {
        label: _one_hot_summary(stats, key, pe_count)
        for label, key in _ATLAS_ACTIVATION_GATE_FIELDS
    }
    classification = {
        label: _one_hot_summary(stats, key, pe_count)
        for label, key in _ATLAS_CONTROL_RUNTIME_CLASSIFICATION_FIELDS
    }
    control_state = {
        label: _one_hot_summary(stats, key, pe_count)
        for label, key in _ATLAS_CONTROL_RUNTIME_STATE_FIELDS
    }
    if control_state:
        dominant_label, dominant_stats = max(
            control_state.items(), key=lambda item: item[1]["total"]
        )
        interpretation = (
            f"{dominant_label} dom on {dominant_stats['total']} of {pe_count} PEs"
            if pe_count > 0
            else f"{dominant_label} dominant"
        )
    else:
        dominant_label = None
        interpretation = "no control runtime state data"
    shared_flags = {
        label: _one_hot_summary(stats, key, pe_count)
        for label, key in _SHARED_WEIGHT_FLAGS.items()
    }
    shared_weight_state = {
        label: _one_hot_summary(stats, key, pe_count)
        for label, key in _ATLAS_SHARED_WEIGHT_CENSUS_STATE_FIELDS
    }
    shared_weight_absent_reason = {
        label: _one_hot_summary(stats, key, pe_count)
        for label, key in _ATLAS_SHARED_WEIGHT_CENSUS_ABSENT_REASON_FIELDS
    }
    shared_authority = {
        plane: {
            label: _one_hot_summary(stats, key, pe_count)
            for label, key in mapping.items()
        }
        for plane, mapping in _SHARED_WEIGHT_AUTHORITY_FIELDS.items()
    }
    machine_chain = _build_atlas_machine_chain(
        effective,
        activation_gate,
        enable_state,
        control_state,
        shared_weight_absent_reason,
    )
    if shared_weight_state:
        dominant_shared_weight_state_label, dominant_shared_weight_state_stats = max(
            shared_weight_state.items(), key=lambda item: item[1]["total"]
        )
    else:
        dominant_shared_weight_state_label = None
        dominant_shared_weight_state_stats = {"total": 0, "share": None}
    if shared_weight_absent_reason:
        dominant_shared_weight_absent_reason_label, dominant_shared_weight_absent_reason_stats = max(
            shared_weight_absent_reason.items(), key=lambda item: item[1]["total"]
        )
    else:
        dominant_shared_weight_absent_reason_label = None
        dominant_shared_weight_absent_reason_stats = {"total": 0, "share": None}
    return {
        "pe_count": pe_count,
        "enable_state": enable_state,
        "activation_gate": activation_gate,
        "machine_chain": machine_chain,
        "control_runtime": {
            "classification": classification,
            "state": control_state,
            "dominant_state": {
                "label": dominant_label,
                "count": dominant_stats["total"] if control_state else 0,
                "share": dominant_stats["share"] if control_state else None,
            },
            "interpretation": interpretation,
        },
        "shared_weight": {
            "state": shared_weight_state,
            "absent_reason": shared_weight_absent_reason,
            "dominant_state": {
                "label": dominant_shared_weight_state_label,
                "count": dominant_shared_weight_state_stats["total"],
                "share": dominant_shared_weight_state_stats["share"],
            },
            "dominant_absent_reason": {
                "label": dominant_shared_weight_absent_reason_label,
                "count": dominant_shared_weight_absent_reason_stats["total"],
                "share": dominant_shared_weight_absent_reason_stats["share"],
            },
            "flags": shared_flags,
            "authority": shared_authority,
        },
    }


def compute_summary(run_dir: Path) -> Dict[str, Any]:
    meta = _read_json(run_dir / "meta.json")
    effective = _read_json(run_dir / "effective_config.json")
    stats, by_component, sim_time_ps = _load_mesh_stats(run_dir)
    pe_stage_rows = _parse_csv_rows(_discover_csvs(run_dir, "pe_stage_events_db.csv"))
    pe_step_rows = _parse_csv_rows(_discover_csvs(run_dir, "pe_step_perf_db.csv"))
    model = _build_model(run_dir, meta, effective, sim_time_ps)
    memory, memhierarchy = _build_memory_sections(
        stats,
        by_component,
        line_size_bytes=_int_or_none(model.get("line_size_bytes")),
    )
    gas, pipeline, critical_path, step = _build_step_and_gas(stats, pe_stage_rows, pe_step_rows)
    contracts = _build_contracts(effective)
    nic, storm = _build_nic_storm(stats, by_component)
    sram = _build_sram(stats)
    snn_tx = _build_snn_tx(stats)
    snn_rx = _build_snn_rx(pe_step_rows, stats)
    noc_mem_joint, atlas_shadow = _build_noc_mem_joint(stats, run_dir)
    atlas_service, atlas_proxy, atlas_lookup, atlas_control, atlas_fabric, atlas_storage, atlas_sync, derived, atlas_object_lifecycle = _build_atlas_sections(stats, noc_mem_joint)
    atlas_activation_census = _build_atlas_activation_census(
        stats, model, by_component, effective
    )
    atlas_config_resolution = _build_atlas_config_resolution(effective)
    atlas_contract_mismatch = _build_atlas_contract_mismatch(
        atlas_activation_census, atlas_sync
    )
    atlas_object_kind_census = _build_atlas_object_kind_census(
        stats,
        atlas_service,
        atlas_storage,
        atlas_object_lifecycle,
        atlas_activation_census,
    )
    atlas_storage_authority_map = _build_atlas_storage_authority_map(
        atlas_activation_census,
        atlas_storage,
        atlas_service,
        atlas_proxy,
        atlas_object_lifecycle,
        atlas_object_kind_census,
    )
    atlas_wms_storage_binding_map = _build_atlas_wms_storage_binding_map(
        atlas_storage,
        atlas_storage_authority_map,
        atlas_activation_census,
    )
    atlas_binding_unresolved_ledger = _build_atlas_binding_unresolved_ledger(
        atlas_wms_storage_binding_map
    )
    atlas_cross_plane_visibility = _build_atlas_cross_plane_visibility(
        atlas_activation_census,
        atlas_contract_mismatch,
        atlas_object_kind_census,
    )
    atlas_control_commit_view = _build_atlas_control_commit_view(
        atlas_contract_mismatch
    )
    atlas_control_binding_map = _build_atlas_control_binding_map(
        stats,
        atlas_object_kind_census,
        atlas_control,
        atlas_fabric,
        atlas_sync,
        atlas_control_commit_view,
    )
    atlas_surface_state = _build_atlas_surface_state_view(atlas_contract_mismatch)
    atlas_surface_ledger = _build_atlas_surface_ledger(
        atlas_config_resolution,
        atlas_activation_census,
        atlas_contract_mismatch,
        atlas_cross_plane_visibility,
        atlas_surface_state,
    )
    atlas_surface_coverage = _build_atlas_surface_coverage(atlas_surface_ledger)
    atlas_surface_probe_ledger = _build_atlas_surface_probe_ledger(
        atlas_surface_coverage,
        atlas_activation_census,
        atlas_surface_ledger,
    )
    atlas_surface_probe_backlog = _build_atlas_surface_probe_backlog(
        atlas_surface_probe_ledger
    )
    atlas_object_closure = _build_atlas_object_closure(
        atlas_surface_ledger,
        atlas_surface_coverage,
        atlas_surface_probe_ledger,
        atlas_storage_authority_map,
    )
    atlas_schema_registry = _build_atlas_schema_registry(
        [
            {
                "name": "atlas_object_kind_census",
                "payload": atlas_object_kind_census,
                "version_field": "matrix_version",
                "default_vocabulary": "atlas_object_kind_census_v2",
                "authority_source": "summary_reader",
                "artifact_surfaces": ["summary", "trace"],
            },
            {
                "name": "atlas_storage_authority_map",
                "payload": atlas_storage_authority_map,
                "default_vocabulary": "atlas_storage_authority_map_v1",
                "authority_source": "summary_reader",
                "artifact_surfaces": ["summary", "trace", "snapshot"],
            },
            {
                "name": "atlas_wms_storage_binding_map",
                "payload": atlas_wms_storage_binding_map,
                "default_vocabulary": "atlas_wms_storage_binding_map_v2",
                "authority_source": "summary_reader",
                "artifact_surfaces": ["summary", "trace", "snapshot"],
            },
            {
                "name": "atlas_binding_unresolved_ledger",
                "payload": atlas_binding_unresolved_ledger,
                "default_vocabulary": "atlas_binding_unresolved_ledger_v1",
                "authority_source": "summary_reader",
                "artifact_surfaces": ["summary", "trace", "snapshot"],
            },
            {
                "name": "atlas_cross_plane_visibility",
                "payload": atlas_cross_plane_visibility,
                "default_vocabulary": "atlas_cross_plane_visibility_v1",
                "authority_source": "summary_reader",
                "artifact_surfaces": ["summary", "trace"],
            },
            {
                "name": "atlas_control_commit_view",
                "payload": atlas_control_commit_view,
                "default_vocabulary": "atlas_control_commit_view_v1",
                "authority_source": "summary_reader",
                "artifact_surfaces": ["summary", "trace"],
            },
            {
                "name": "atlas_control_binding_map",
                "payload": atlas_control_binding_map,
                "default_vocabulary": "atlas_control_binding_map_v1",
                "authority_source": "summary_reader",
                "artifact_surfaces": ["summary", "trace", "snapshot"],
            },
            {
                "name": "atlas_object_closure",
                "payload": atlas_object_closure,
                "default_vocabulary": "atlas_object_closure_v1",
                "authority_source": "summary_reader",
                "artifact_surfaces": ["summary", "trace", "snapshot"],
            },
        ]
    )
    machine_chain = atlas_activation_census.get("machine_chain")
    if isinstance(machine_chain, dict):
        machine_chain["surface_state"] = atlas_surface_state
    pulse = _build_pulse(stats)
    summary: Dict[str, Any] = {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "model": model,
        "memory": memory,
        "memhierarchy": memhierarchy,
        "gas": gas,
        "pipeline": pipeline,
        "critical_path": critical_path,
        "contracts": contracts,
        "step": step,
        "snn_tx": snn_tx,
        "snn_rx": snn_rx,
        "nic": nic,
        "storm": storm,
        "sram": sram,
        "noc_mem_joint": noc_mem_joint,
        "atlas_service": atlas_service,
        "atlas_proxy": atlas_proxy,
        "atlas_lookup": atlas_lookup,
        "atlas_shadow": atlas_shadow,
        "atlas_control": atlas_control,
        "atlas_fabric": atlas_fabric,
        "atlas_storage": atlas_storage,
        "atlas_sync": atlas_sync,
        "atlas_activation_census": atlas_activation_census,
        "atlas_config_resolution": atlas_config_resolution,
        "atlas_contract_mismatch": atlas_contract_mismatch,
        "atlas_object_kind_census": atlas_object_kind_census,
        "atlas_storage_authority_map": atlas_storage_authority_map,
        "atlas_wms_storage_binding_map": atlas_wms_storage_binding_map,
        "atlas_binding_unresolved_ledger": atlas_binding_unresolved_ledger,
        "atlas_cross_plane_visibility": atlas_cross_plane_visibility,
        "atlas_control_commit_view": atlas_control_commit_view,
        "atlas_control_binding_map": atlas_control_binding_map,
        "atlas_schema_registry": atlas_schema_registry,
        "atlas_surface_ledger": atlas_surface_ledger,
        "atlas_surface_coverage": atlas_surface_coverage,
        "atlas_surface_probe_ledger": atlas_surface_probe_ledger,
        "atlas_surface_probe_backlog": atlas_surface_probe_backlog,
        "atlas_object_closure": atlas_object_closure,
        "atlas_object_lifecycle": atlas_object_lifecycle,
        "retire_hol_attribution": {},
        "retire_hol_attribution_core": {},
        "pulse": pulse,
        "derived": derived,
        "refs": {
            "mesh_stats_csv": "mesh_stats.csv",
            "meta_json": "meta.json",
            "effective_config_json": "effective_config.json",
        },
    }
    _patch_rowindex_fields(summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    summary = compute_summary(run_dir)
    _write_json(run_dir / "essential_summary_mesh.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
