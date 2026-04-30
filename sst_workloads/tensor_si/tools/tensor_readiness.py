#!/usr/bin/env python3
"""Readiness scoring helpers for Tensor Core / NPU / TPU capability assessment."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


DEFAULT_MATRIX: Dict[str, Any] = {
    "schema_version": 1,
    "version": "m37_default_v1",
    "dimensions": [
        {"name": "scheduler", "weight": 0.25, "target": 85.0},
        {"name": "dataflow", "weight": 0.2, "target": 85.0},
        {"name": "memory", "weight": 0.25, "target": 85.0},
        {"name": "parallelism", "weight": 0.15, "target": 85.0},
        {"name": "scalability", "weight": 0.15, "target": 85.0},
    ],
}


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if isinstance(value, bool):
            return int(default)
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return int(value)
        txt = str(value).strip()
        if not txt:
            return int(default)
        return int(float(txt))
    except Exception:
        return int(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, bool):
            return float(default)
        if isinstance(value, (int, float)):
            return float(value)
        txt = str(value).strip()
        if not txt:
            return float(default)
        return float(txt)
    except Exception:
        return float(default)


def _as_str(value: Any, default: str = "") -> str:
    txt = str(value if value is not None else "").strip()
    return txt if txt else str(default)


def _clamp01(x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return float(x)


def _clamp100(x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 100.0:
        return 100.0
    return float(x)


def _round3(x: float) -> float:
    return float(round(float(x), 3))


def _parse_matrix(matrix: Dict[str, Any] | None) -> Tuple[Dict[str, float], Dict[str, float]]:
    payload = matrix if isinstance(matrix, dict) else DEFAULT_MATRIX
    dims = payload.get("dimensions")
    if not isinstance(dims, list) or not dims:
        payload = DEFAULT_MATRIX
        dims = payload["dimensions"]

    weights: Dict[str, float] = {}
    targets: Dict[str, float] = {}
    for item in dims:
        if not isinstance(item, dict):
            continue
        name = _as_str(item.get("name"), "").strip().lower()
        if not name:
            continue
        w = _to_float(item.get("weight"), 0.0)
        t = _to_float(item.get("target"), 85.0)
        if w <= 0.0:
            continue
        weights[name] = float(w)
        targets[name] = _clamp100(float(t))

    if not weights:
        return _parse_matrix(DEFAULT_MATRIX)
    return weights, targets


def _score_scheduler(tensor: Dict[str, Any], tensor_cfg: Dict[str, Any]) -> float:
    issue_width = max(1, _to_int(tensor_cfg.get("tensor_program_issue_width"), 1))
    exec_mode = _as_str(tensor_cfg.get("tensor_exec_mode"), "bulk").lower()
    dual_dma = max(0, _to_int(tensor_cfg.get("tensor_program_dma_dual_enable"), 0))
    priority = _as_str(tensor_cfg.get("tensor_program_engine_priority"), "").lower()

    any_busy = max(0, _to_int(tensor.get("tensor_program_any_busy_cycles_total"), 0))
    fence_wait = max(0, _to_int(tensor.get("tensor_program_fence_wait_cycles_total"), 0))
    ub_stall = max(0, _to_int(tensor.get("tensor_program_ub_stall_cycles_total"), 0))
    mem_stall = max(0, _to_int(tensor.get("tensor_program_mem_stall_cycles_total"), 0))

    score = 10.0
    if exec_mode == "program":
        score += 30.0
    score += min(issue_width, 8) * 5.0
    if dual_dma > 0:
        score += 8.0
    if "dma>mxu" in priority or "mxu>dma" in priority:
        score += 4.0

    if any_busy > 0:
        stall_ratio = _clamp01(float(fence_wait + ub_stall + mem_stall) / float(any_busy))
        score += (1.0 - stall_ratio) * 8.0
    return _clamp100(score)


def _score_dataflow(tensor: Dict[str, Any], tensor_cfg: Dict[str, Any]) -> float:
    dataflow = _as_str(tensor_cfg.get("tensor_dataflow"), "").lower()
    tile_m = max(0, _to_int(tensor_cfg.get("tensor_tile_m"), 0))
    tile_n = max(0, _to_int(tensor_cfg.get("tensor_tile_n"), 0))
    tile_k = max(0, _to_int(tensor_cfg.get("tensor_tile_k"), 0))
    onchip_enable = max(0, _to_int(tensor_cfg.get("tensor_onchip_model_enable"), 0))
    spill_enable = max(0, _to_int(tensor_cfg.get("tensor_spill_enable"), 0))
    collective_algo = _as_str(tensor_cfg.get("tensor_collective_algo"), "legacy_bytes").lower()
    mxu_io_busy = max(0, _to_int(tensor.get("tensor_mxu_io_busy_cycles_total"), 0))

    score = 15.0
    if dataflow in {"os", "ws", "is"}:
        score += 25.0
    if tile_m > 0 and tile_n > 0 and tile_k > 0:
        score += 15.0
    if onchip_enable > 0:
        score += 20.0
    if spill_enable > 0:
        score += 8.0
    if collective_algo not in {"none", "legacy_bytes"}:
        score += 10.0
    if mxu_io_busy > 0:
        score += 10.0
    # Presence of explicit conflict visibility counters is also useful for realism.
    if "tensor_stall_onchip_bank_conflict_cycles_total" in tensor:
        score += 5.0
    return _clamp100(score)


def _score_memory(tensor: Dict[str, Any], tensor_cfg: Dict[str, Any], mesh_cfg: Dict[str, Any]) -> float:
    mem_enable = max(0, _to_int(tensor_cfg.get("tensor_mem_enable"), 0))
    backend = _as_str(mesh_cfg.get("mem_backend"), "simple").lower()
    channels = max(1, _to_int(tensor_cfg.get("tensor_dma_hbm_channels"), 1))
    interleave = max(0, _to_int(tensor_cfg.get("tensor_dma_hbm_channel_interleave_bytes"), 0))
    max_outstanding = max(0, _to_int(tensor_cfg.get("tensor_mem_max_outstanding"), 0))
    read_samples = max(0, _to_int(tensor.get("tensor_mem_read_latency_samples_total"), 0))
    write_samples = max(0, _to_int(tensor.get("tensor_mem_write_latency_samples_total"), 0))
    profile = _as_str(tensor_cfg.get("tensor_memory_hierarchy_profile"), "baseline").lower()
    row_hit = max(0, _to_int(tensor.get("tensor_mem_row_hit_total"), 0))
    row_miss = max(0, _to_int(tensor.get("tensor_mem_row_miss_total"), 0))
    row_conflict = max(0, _to_int(tensor.get("tensor_mem_row_conflict_total"), 0))
    cmd_act = max(0, _to_int(tensor.get("tensor_mem_cmd_act_total"), 0))
    cmd_pre = max(0, _to_int(tensor.get("tensor_mem_cmd_pre_total"), 0))
    cmd_rdwr = max(0, _to_int(tensor.get("tensor_mem_cmd_rdwr_total"), 0))
    queue_wait = max(0, _to_int(tensor.get("tensor_mem_bank_queue_wait_cycles_total"), 0))
    proxy_delay = max(0, _to_int(tensor.get("tensor_mem_proxy_delay_cycles_total"), 0))
    cmd_queue_depth_max = max(0, _to_int(tensor.get("tensor_mem_cmd_queue_depth_max"), 0))
    cmd_bus_wait = max(0, _to_int(tensor.get("tensor_mem_cmd_bus_wait_cycles_total"), 0))
    cmd_issue_total = max(0, _to_int(tensor.get("tensor_mem_cmd_issue_total"), 0))
    timing_model = _as_str(tensor_cfg.get("tensor_mem_timing_model"), "off").lower()
    row_total = row_hit + row_miss + row_conflict

    score = 5.0
    if mem_enable > 0:
        score += 20.0
    if backend == "ramulator2":
        score += 25.0
    else:
        score += 12.0
    score += _clamp01(float(min(channels, 8)) / 8.0) * 20.0
    if interleave in {64, 128, 256, 512, 1024, 2048, 4096}:
        score += 8.0
    if (read_samples + write_samples) > 0:
        score += 12.0
    if max_outstanding >= 64:
        score += 10.0
    elif max_outstanding > 0:
        score += 6.0
    if profile in {"baseline", "balanced", "edge", "server", "hbm_like"}:
        score += 5.0
    if timing_model == "proxy_v3":
        score += 8.0
    elif timing_model == "proxy_v2":
        score += 5.0
    if row_total > 0:
        score += 5.0
    if row_conflict > 0:
        score += 2.0
    if cmd_rdwr > 0:
        score += 3.0
    if cmd_act > 0 or cmd_pre > 0:
        score += 2.0
    if queue_wait > 0:
        score += 4.0
    if proxy_delay > 0:
        score += 4.0
    if timing_model == "proxy_v3" and cmd_issue_total > 0:
        score += 4.0
    if cmd_queue_depth_max > 0:
        score += 2.0
    if cmd_bus_wait > 0:
        score += 2.0
    return _clamp100(score)


def _score_parallelism(tensor: Dict[str, Any], tensor_cfg: Dict[str, Any], mesh_cfg: Dict[str, Any]) -> float:
    array_m = max(1, _to_int(tensor_cfg.get("tensor_array_m"), 1))
    array_n = max(1, _to_int(tensor_cfg.get("tensor_array_n"), 1))
    collective_algo = _as_str(tensor_cfg.get("tensor_collective_algo"), "legacy_bytes").lower()
    overlap = max(0, _to_int(tensor_cfg.get("tensor_collective_overlap_with_compute"), 1))
    vector_elems = max(0, _to_int(tensor_cfg.get("tensor_vector_elems_per_cycle"), 0))
    mesh_size = max(1, _to_int(mesh_cfg.get("mesh_size"), 1))
    num_vns = max(1, _to_int(mesh_cfg.get("network_num_vns"), 1))

    score = 10.0
    score += _clamp01(float(min(array_m, 128)) / 128.0) * 20.0
    score += _clamp01(float(min(array_n, 128)) / 128.0) * 20.0
    if collective_algo not in {"none", "legacy_bytes"}:
        score += 15.0
    if overlap > 0:
        score += 10.0
    if vector_elems > 0:
        score += 10.0
    if mesh_size > 1:
        score += 10.0
    if num_vns > 1:
        score += 5.0
    return _clamp100(score)


def _score_scalability(tensor_cfg: Dict[str, Any], mesh_cfg: Dict[str, Any]) -> float:
    mesh_size = max(1, _to_int(mesh_cfg.get("mesh_size"), 1))
    node_limit = max(1, _to_int(mesh_cfg.get("node_limit"), 1))
    total_nodes = max(1, _to_int(mesh_cfg.get("total_nodes"), mesh_size * mesh_size))
    noc_type = _as_str(mesh_cfg.get("noc_type"), "merlin_mesh").lower()
    channels = max(1, _to_int(tensor_cfg.get("tensor_dma_hbm_channels"), 1))
    backend = _as_str(mesh_cfg.get("mem_backend"), "simple").lower()
    collective_algo = _as_str(tensor_cfg.get("tensor_collective_algo"), "legacy_bytes").lower()

    score = 8.0
    score += _clamp01(float(min(mesh_size, 8)) / 8.0) * 25.0
    score += _clamp01(float(node_limit) / float(total_nodes)) * 10.0
    if noc_type == "merlin_torus":
        score += 15.0
    elif noc_type == "merlin_mesh":
        score += 10.0
    score += _clamp01(float(min(channels, 8)) / 8.0) * 15.0
    if backend == "ramulator2":
        score += 12.0
    if collective_algo == "torus_2d_rs_ag":
        score += 10.0
    if mesh_size >= 4 and channels >= 4:
        score += 5.0
    return _clamp100(score)


def _calibration_confidence(tensor: Dict[str, Any], tensor_cfg: Dict[str, Any]) -> str:
    tag = _as_str(tensor_cfg.get("tensor_calibration_tag"), "")
    if not tag:
        return "unverified"
    samples = max(0, _to_int(tensor.get("tensor_mem_read_latency_samples_total"), 0)) + max(
        0, _to_int(tensor.get("tensor_mem_write_latency_samples_total"), 0)
    )
    if samples >= 128:
        return "high"
    if samples >= 32:
        return "medium"
    return "low"


def _drift_flags(tensor: Dict[str, Any], tensor_cfg: Dict[str, Any], mesh_cfg: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    mem_enable = max(0, _to_int(tensor_cfg.get("tensor_mem_enable"), 0))
    read_samples = max(0, _to_int(tensor.get("tensor_mem_read_latency_samples_total"), 0))
    any_busy = max(0, _to_int(tensor.get("tensor_program_any_busy_cycles_total"), 0))
    mem_stall = max(0, _to_int(tensor.get("tensor_program_mem_stall_cycles_total"), 0))
    compute_cycles = max(0, _to_int(tensor.get("tensor_compute_cycles_total"), 0))
    bank_conflict = max(0, _to_int(tensor.get("tensor_stall_onchip_bank_conflict_cycles_total"), 0))
    dma_cycles = max(0, _to_int(tensor.get("tensor_dma_cycles_total"), 0))
    dma_stall = max(0, _to_int(tensor.get("tensor_dma_stall_cycles_total"), 0))
    row_hit = max(0, _to_int(tensor.get("tensor_mem_row_hit_total"), 0))
    row_miss = max(0, _to_int(tensor.get("tensor_mem_row_miss_total"), 0))
    row_conflict = max(0, _to_int(tensor.get("tensor_mem_row_conflict_total"), 0))
    cmd_rdwr = max(0, _to_int(tensor.get("tensor_mem_cmd_rdwr_total"), 0))
    queue_wait = max(0, _to_int(tensor.get("tensor_mem_bank_queue_wait_cycles_total"), 0))
    cmd_issue_total = max(0, _to_int(tensor.get("tensor_mem_cmd_issue_total"), 0))
    cmd_queue_depth_max = max(0, _to_int(tensor.get("tensor_mem_cmd_queue_depth_max"), 0))
    cmd_bus_wait = max(0, _to_int(tensor.get("tensor_mem_cmd_bus_wait_cycles_total"), 0))
    timing_model = _as_str(tensor_cfg.get("tensor_mem_timing_model"), "off").lower()
    channels = max(1, _to_int(tensor_cfg.get("tensor_dma_hbm_channels"), 1))
    mesh_size = max(1, _to_int(mesh_cfg.get("mesh_size"), 1))

    if mem_enable > 0 and read_samples == 0:
        flags.append("missing_mem_read_latency_samples")
    if any_busy > 0 and float(mem_stall) > 0.6 * float(any_busy):
        flags.append("memory_stall_dominant")
    if compute_cycles > 0 and float(bank_conflict) > 0.3 * float(compute_cycles):
        flags.append("onchip_bank_conflict_hotspot")
    if dma_cycles > 0 and float(dma_stall) > 0.5 * float(dma_cycles):
        flags.append("dma_stall_dominant")
    if mesh_size <= 1 and channels <= 1:
        flags.append("single_node_bandwidth_limited_proxy")
    row_total = row_hit + row_miss + row_conflict
    if timing_model in {"proxy_v2", "proxy_v3"} and row_total == 0:
        flags.append("missing_mem_rowbank_observability")
    if timing_model in {"proxy_v2", "proxy_v3"} and cmd_rdwr == 0:
        flags.append("missing_mem_cmd_observability")
    if timing_model == "proxy_v3" and cmd_issue_total == 0:
        flags.append("missing_mem_cmd_bus_observability")
    if timing_model == "proxy_v3" and queue_wait > 0 and cmd_queue_depth_max == 0:
        flags.append("missing_mem_cmd_queue_depth_observability")
    if row_total > 0 and float(row_conflict) > 0.5 * float(row_total):
        flags.append("row_conflict_dominant")
    if queue_wait > 0 and any_busy > 0 and float(queue_wait) > 0.8 * float(any_busy):
        flags.append("bank_queue_pressure_hotspot")
    if cmd_bus_wait > 0 and any_busy > 0 and float(cmd_bus_wait) > 0.3 * float(any_busy):
        flags.append("cmd_bus_pressure_hotspot")

    deduped = sorted(set(flags))
    return deduped


def _cross_layer_attribution(tensor: Dict[str, Any]) -> Dict[str, Any]:
    compute_cycles = max(0, _to_int(tensor.get("tensor_compute_cycles_total"), 0)) + max(
        0, _to_int(tensor.get("tensor_compute_pipeline_cycles_total"), 0)
    )
    memory_cycles = (
        max(0, _to_int(tensor.get("tensor_stall_mem_outstanding_cycles_total"), 0))
        + max(0, _to_int(tensor.get("tensor_program_mem_stall_cycles_total"), 0))
        + max(0, _to_int(tensor.get("tensor_mem_bank_queue_wait_cycles_total"), 0))
        + max(0, _to_int(tensor.get("tensor_mem_cmd_bus_wait_cycles_total"), 0))
    )
    noc_cycles = (
        max(0, _to_int(tensor.get("tensor_stall_noc_budget_cycles_total"), 0))
        + max(0, _to_int(tensor.get("tensor_collective_credit_stall_cycles_total"), 0))
        + max(0, _to_int(tensor.get("tensor_collective_backpressure_stall_cycles_total"), 0))
        + max(0, _to_int(tensor.get("tensor_stall_collective_cycles_total"), 0))
    )

    layer_cycles = {
        "compute": float(max(1, compute_cycles)),
        "memory": float(max(0, memory_cycles)),
        "noc": float(max(0, noc_cycles)),
    }
    total = max(1.0, layer_cycles["compute"] + layer_cycles["memory"] + layer_cycles["noc"])
    layer_share = {
        "compute": _round3(layer_cycles["compute"] / total),
        "memory": _round3(layer_cycles["memory"] / total),
        "noc": _round3(layer_cycles["noc"] / total),
    }

    dominant_layer = "compute"
    dominant_value = layer_share["compute"]
    for layer in ("memory", "noc"):
        if layer_share[layer] > dominant_value:
            dominant_layer = layer
            dominant_value = layer_share[layer]

    return {
        "dominant_layer": dominant_layer,
        "layer_cycles": {k: int(v) for k, v in layer_cycles.items()},
        "layer_share": layer_share,
        "signals": {
            "tensor_mem_cmd_bus_wait_cycles_total": max(0, _to_int(tensor.get("tensor_mem_cmd_bus_wait_cycles_total"), 0)),
            "tensor_mem_bank_queue_wait_cycles_total": max(0, _to_int(tensor.get("tensor_mem_bank_queue_wait_cycles_total"), 0)),
            "tensor_stall_noc_budget_cycles_total": max(0, _to_int(tensor.get("tensor_stall_noc_budget_cycles_total"), 0)),
            "tensor_collective_credit_stall_cycles_total": max(
                0, _to_int(tensor.get("tensor_collective_credit_stall_cycles_total"), 0)
            ),
            "tensor_collective_backpressure_stall_cycles_total": max(
                0, _to_int(tensor.get("tensor_collective_backpressure_stall_cycles_total"), 0)
            ),
        },
    }


def _suggest_interventions(dominant_layer: str, drift_flags: List[str]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []

    if dominant_layer == "memory":
        out.append(
            {
                "parameter": "tensor_dma_hbm_channels",
                "direction": "increase",
                "expected_effect": "reduce memory contention",
            }
        )
        out.append(
            {
                "parameter": "tensor_mem_bank_queue_depth",
                "direction": "increase",
                "expected_effect": "absorb bank queue bursts",
            }
        )
    elif dominant_layer == "noc":
        out.append(
            {
                "parameter": "tensor_noc_bandwidth_bytes_per_cycle",
                "direction": "increase",
                "expected_effect": "relieve collective/noс pressure",
            }
        )
        out.append(
            {
                "parameter": "tensor_collective_chunk_bytes",
                "direction": "decrease",
                "expected_effect": "reduce burstiness and backpressure",
            }
        )
    else:
        out.append(
            {
                "parameter": "tensor_program_issue_width",
                "direction": "increase",
                "expected_effect": "improve front-end throughput",
            }
        )
        out.append(
            {
                "parameter": "tensor_compute_pipeline_latency_cycles",
                "direction": "decrease",
                "expected_effect": "reduce compute pipeline bubbles",
            }
        )

    if "cmd_bus_pressure_hotspot" in drift_flags:
        out.append(
            {
                "parameter": "tensor_mem_t_ccd_s_cycles/tensor_mem_t_ccd_l_cycles",
                "direction": "recalibrate",
                "expected_effect": "lower command bus serialization penalties",
            }
        )
    if "bank_queue_pressure_hotspot" in drift_flags:
        out.append(
            {
                "parameter": "tensor_mem_sched_policy",
                "direction": "frfcfs",
                "expected_effect": "increase row-hit preference under contention",
            }
        )
    return out[:4]


def build_readiness_assessment(
    tensor_stats: Dict[str, Any],
    effective_cfg: Dict[str, Any] | None = None,
    matrix: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build a stable, machine-readable readiness assessment."""

    tensor = tensor_stats if isinstance(tensor_stats, dict) else {}
    cfg = effective_cfg if isinstance(effective_cfg, dict) else {}
    tensor_cfg = cfg.get("tensor_cfg") if isinstance(cfg.get("tensor_cfg"), dict) else {}
    mesh_cfg = cfg.get("mesh_cfg") if isinstance(cfg.get("mesh_cfg"), dict) else {}

    profile_name = _as_str(tensor_cfg.get("tensor_capability_profile"), "baseline_npu_like_v1")
    scores: Dict[str, float] = {
        "scheduler": _score_scheduler(tensor, tensor_cfg),
        "dataflow": _score_dataflow(tensor, tensor_cfg),
        "memory": _score_memory(tensor, tensor_cfg, mesh_cfg),
        "parallelism": _score_parallelism(tensor, tensor_cfg, mesh_cfg),
        "scalability": _score_scalability(tensor_cfg, mesh_cfg),
    }

    weights, targets = _parse_matrix(matrix)
    weighted_sum = 0.0
    weight_total = 0.0
    target_weighted_sum = 0.0
    gaps: List[Dict[str, Any]] = []
    for name, weight in weights.items():
        actual = _clamp100(scores.get(name, 0.0))
        target = _clamp100(targets.get(name, 85.0))
        weighted_sum += actual * weight
        target_weighted_sum += target * weight
        weight_total += weight
        gaps.append(
            {
                "dimension": name,
                "target": _round3(target),
                "actual": _round3(actual),
                "gap": _round3(max(0.0, target - actual)),
            }
        )

    total_score = _clamp100(weighted_sum / weight_total) if weight_total > 0.0 else 0.0
    target_score = _clamp100(target_weighted_sum / weight_total) if weight_total > 0.0 else 85.0

    gap_sorted = sorted(gaps, key=lambda x: (float(x.get("gap", 0.0)), str(x.get("dimension", ""))), reverse=True)
    confidence = _calibration_confidence(tensor, tensor_cfg)
    drift_flags = _drift_flags(tensor, tensor_cfg, mesh_cfg)
    evidence_mode = profile_name in {
        "readiness_evidence_v2",
        "realism_evidence_v2",
        "readiness_v3",
        "readiness_evidence_v3",
        "realism_evidence_v3",
    }
    evidence_factor = 1.0
    if evidence_mode:
        confidence_factor = {
            "high": 1.00,
            "medium": 0.96,
            "low": 0.90,
            "unverified": 0.85,
        }
        evidence_factor = confidence_factor.get(str(confidence).strip().lower(), 0.85)
        evidence_factor -= min(0.15, 0.03 * float(len(drift_flags)))
        read_samples = max(0, _to_int(tensor.get("tensor_mem_read_latency_samples_total"), 0))
        write_samples = max(0, _to_int(tensor.get("tensor_mem_write_latency_samples_total"), 0))
        mem_enable = max(0, _to_int(tensor_cfg.get("tensor_mem_enable"), 0))
        timing_model = _as_str(tensor_cfg.get("tensor_mem_timing_model"), "off").lower()
        if mem_enable > 0 and (read_samples + write_samples) <= 0:
            evidence_factor -= 0.08
        if mem_enable > 0 and timing_model not in {"proxy_v2", "proxy_v3"}:
            evidence_factor -= 0.05
        evidence_factor = max(0.60, min(1.0, float(evidence_factor)))
        total_score = _clamp100(total_score * evidence_factor)

    attribution = _cross_layer_attribution(tensor)
    top_bottlenecks: List[str] = [str(attribution.get("dominant_layer", "compute"))]
    for item in gap_sorted:
        dim = str(item.get("dimension", "")).strip().lower()
        if dim and dim not in top_bottlenecks:
            top_bottlenecks.append(dim)
        if len(top_bottlenecks) >= 3:
            break
    interventions = _suggest_interventions(top_bottlenecks[0], drift_flags)

    evidence_mode_id = "off"
    if evidence_mode:
        evidence_mode_id = "v3" if "v3" in profile_name else "v2"

    return {
        "capability_profile": profile_name,
        "scheduler_model": _as_str(tensor_cfg.get("tensor_scheduler_model"), "legacy"),
        "memory_hierarchy_profile": _as_str(tensor_cfg.get("tensor_memory_hierarchy_profile"), "baseline"),
        "calibration_tag": _as_str(tensor_cfg.get("tensor_calibration_tag"), ""),
        "capability_score_total": _round3(total_score),
        "capability_score_breakdown": {k: _round3(v) for k, v in scores.items()},
        "distance_to_target": _round3(max(0.0, float(target_score) - float(total_score))),
        "target_score": _round3(target_score),
        "gap_rank_topk": gap_sorted[:3],
        "calibration_confidence": confidence,
        "evidence_mode": evidence_mode_id,
        "evidence_factor": _round3(evidence_factor),
        "regression_drift_flags": drift_flags,
        "cross_layer_attribution": attribution,
        "top_bottlenecks": top_bottlenecks,
        "suggested_interventions": interventions,
    }
