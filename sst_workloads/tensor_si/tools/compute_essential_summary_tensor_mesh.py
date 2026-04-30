#!/usr/bin/env python3
"""Aggregate tensor mesh run artifacts into an essential summary JSON."""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from tensor_readiness import build_readiness_assessment


NUMBER_FIELDS = ("Sum.u64", "Sum.f64", "Count.u64")
PRECISION_PROFILE_IDS = {
    "fp16": 0,
    "bf16": 1,
    "fp32": 2,
    "tf32": 3,
    "int8": 4,
    "fp8": 5,
}


def _parse_number(v: str) -> float:
    if v is None:
        return 0.0
    s = str(v).strip()
    if not s:
        return 0.0
    try:
        if "." in s or "e" in s.lower():
            return float(s)
        return float(int(s))
    except Exception:
        return 0.0


def _load_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        try:
            return list(csv.DictReader(fh))
        except Exception:
            return []


def _sum_stat(rows: List[Dict[str, str]], name: str) -> float:
    total = 0.0
    for r in rows:
        if r.get("StatisticName") != name:
            continue
        for k in NUMBER_FIELDS:
            if k in r:
                total += _parse_number(r.get(k, "0"))
                break
    return total


def _max_stat(rows: List[Dict[str, str]], name: str) -> float:
    m = 0.0
    for r in rows:
        if r.get("StatisticName") != name:
            continue
        for k in NUMBER_FIELDS:
            if k in r:
                v = _parse_number(r.get(k, "0"))
                if v > m:
                    m = v
                break
    return m


def _parse_modules(raw: str) -> List[str]:
    out: List[str] = []
    for part in (raw or "").split(","):
        item = part.strip().lower()
        if item:
            out.append(item)
    return out


def _has_stat_prefix(rows: List[Dict[str, str]], prefix: str) -> bool:
    if not prefix:
        return False
    for r in rows:
        name = str(r.get("StatisticName", "") or "")
        if name.startswith(prefix):
            return True
    return False


def _infer_sim_time_ns(rows: List[Dict[str, str]]) -> int:
    # tensor_template sets timebase=1ps by default
    max_t = 0
    for r in rows:
        try:
            t = int(float(r.get("SimTime", "0") or "0"))
            if t > max_t:
                max_t = t
        except Exception:
            pass
    return int(round(max_t / 1000.0))


def _precision_profile_id_from_name(name: str) -> int:
    key = str(name or "").strip().lower()
    return int(PRECISION_PROFILE_IDS.get(key, 0))


def _load_effective_tensor_cfg(run_dir: Path) -> Dict[str, Any]:
    payload = _load_effective_config(run_dir)
    tensor_cfg = payload.get("tensor_cfg")
    return tensor_cfg if isinstance(tensor_cfg, dict) else {}


def _load_effective_config(run_dir: Path) -> Dict[str, Any]:
    path = run_dir / "effective_config.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def resolve_default_run_dir() -> Path:
    env = os.environ.get("TENSOR_SI_RUN_DIR", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    project_root = here.parents[1]
    return (project_root / "analysis" / "tensor_latest").resolve()


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=str, default="", help="run output dir containing mesh_stats.csv")
    ap.add_argument(
        "--out",
        type=str,
        default="",
        help="output summary json path (default: <run-dir>/essential_summary_tensor_mesh.json)",
    )
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir).expanduser().resolve() if args.run_dir else resolve_default_run_dir()
    stats_csv = run_dir / "mesh_stats.csv"
    rows = _load_csv_rows(stats_csv)

    modules_env = os.environ.get("TENSOR_SI_WORKLOAD_STATS_MODULES", "").strip()
    modules = _parse_modules(modules_env)
    include_stream = ("stream" in modules) if modules else _has_stat_prefix(rows, "stream_")

    tensor_stats = {
        "tensor_mem_reads_issued_total": int(_sum_stat(rows, "tensor_mem_reads_issued_total")),
        "tensor_mem_writes_issued_total": int(_sum_stat(rows, "tensor_mem_writes_issued_total")),
        "tensor_mem_bytes_read_total": int(_sum_stat(rows, "tensor_mem_bytes_read_total")),
        "tensor_mem_bytes_write_total": int(_sum_stat(rows, "tensor_mem_bytes_write_total")),
        "tensor_mem_read_latency_cycles_total": int(_sum_stat(rows, "tensor_mem_read_latency_cycles_total")),
        "tensor_mem_read_latency_cycles_max": int(_max_stat(rows, "tensor_mem_read_latency_cycles_max")),
        "tensor_mem_read_latency_samples_total": int(_sum_stat(rows, "tensor_mem_read_latency_samples_total")),
        "tensor_mem_write_latency_cycles_total": int(_sum_stat(rows, "tensor_mem_write_latency_cycles_total")),
        "tensor_mem_write_latency_cycles_max": int(_max_stat(rows, "tensor_mem_write_latency_cycles_max")),
        "tensor_mem_write_latency_samples_total": int(_sum_stat(rows, "tensor_mem_write_latency_samples_total")),
        "tensor_mem_row_hit_total": int(_sum_stat(rows, "tensor_mem_row_hit_total")),
        "tensor_mem_row_miss_total": int(_sum_stat(rows, "tensor_mem_row_miss_total")),
        "tensor_mem_row_conflict_total": int(_sum_stat(rows, "tensor_mem_row_conflict_total")),
        "tensor_mem_bank_queue_full_total": int(_sum_stat(rows, "tensor_mem_bank_queue_full_total")),
        "tensor_mem_bank_queue_wait_cycles_total": int(_sum_stat(rows, "tensor_mem_bank_queue_wait_cycles_total")),
        "tensor_mem_sched_fifo_pick_total": int(_sum_stat(rows, "tensor_mem_sched_fifo_pick_total")),
        "tensor_mem_sched_frfcfs_pick_total": int(_sum_stat(rows, "tensor_mem_sched_frfcfs_pick_total")),
        "tensor_mem_cmd_act_total": int(_sum_stat(rows, "tensor_mem_cmd_act_total")),
        "tensor_mem_cmd_pre_total": int(_sum_stat(rows, "tensor_mem_cmd_pre_total")),
        "tensor_mem_cmd_rdwr_total": int(_sum_stat(rows, "tensor_mem_cmd_rdwr_total")),
        "tensor_mem_row_service_cycles_total": int(_sum_stat(rows, "tensor_mem_row_service_cycles_total")),
        "tensor_mem_refresh_block_cycles_total": int(_sum_stat(rows, "tensor_mem_refresh_block_cycles_total")),
        "tensor_mem_proxy_delay_cycles_total": int(_sum_stat(rows, "tensor_mem_proxy_delay_cycles_total")),
        "tensor_mem_proxy_delay_cycles_max": int(_max_stat(rows, "tensor_mem_proxy_delay_cycles_max")),
        "tensor_mem_bank_active_cycles_total": int(_sum_stat(rows, "tensor_mem_bank_active_cycles_total")),
        "tensor_mem_cmd_queue_slots_total": int(_sum_stat(rows, "tensor_mem_cmd_queue_slots_total")),
        "tensor_mem_cmd_queue_depth_max": int(_max_stat(rows, "tensor_mem_cmd_queue_depth_max")),
        "tensor_mem_cmd_bus_wait_cycles_total": int(_sum_stat(rows, "tensor_mem_cmd_bus_wait_cycles_total")),
        "tensor_mem_cmd_bus_bg_switch_total": int(_sum_stat(rows, "tensor_mem_cmd_bus_bg_switch_total")),
        "tensor_mem_cmd_issue_total": int(_sum_stat(rows, "tensor_mem_cmd_issue_total")),
        "tensor_compute_cycles_total": int(_sum_stat(rows, "tensor_compute_cycles_total")),
        "tensor_compute_math_cycles_total": int(_sum_stat(rows, "tensor_compute_math_cycles_total")),
        "tensor_compute_pipeline_cycles_total": int(_sum_stat(rows, "tensor_compute_pipeline_cycles_total")),
        "tensor_mxu_wavefront_cycles_total": int(_sum_stat(rows, "tensor_mxu_wavefront_cycles_total")),
        "tensor_mxu_io_busy_cycles_total": int(_sum_stat(rows, "tensor_mxu_io_busy_cycles_total")),
        "tensor_compute_precision_profile_id": int(_sum_stat(rows, "tensor_compute_precision_profile_id")),
        "tensor_mac_ops_total": int(_sum_stat(rows, "tensor_mac_ops_total")),
        "tensor_dma_stall_cycles_total": int(_sum_stat(rows, "tensor_dma_stall_cycles_total")),
        "tensor_iter_cycles_total": int(_sum_stat(rows, "tensor_iter_cycles_total")),
        "tensor_stall_dma_budget_cycles_total": int(_sum_stat(rows, "tensor_stall_dma_budget_cycles_total")),
        "tensor_stall_dma_hbm_channel_budget_cycles_total": int(
            _sum_stat(rows, "tensor_stall_dma_hbm_channel_budget_cycles_total")
        ),
        "tensor_stall_mem_outstanding_cycles_total": int(_sum_stat(rows, "tensor_stall_mem_outstanding_cycles_total")),
        "tensor_stall_wait_read_cycles_total": int(_sum_stat(rows, "tensor_stall_wait_read_cycles_total")),
        "tensor_stall_wait_write_cycles_total": int(_sum_stat(rows, "tensor_stall_wait_write_cycles_total")),
        "tensor_stall_collective_cycles_total": int(_sum_stat(rows, "tensor_stall_collective_cycles_total")),
        "tensor_stall_onchip_capacity_cycles_total": int(_sum_stat(rows, "tensor_stall_onchip_capacity_cycles_total")),
        "tensor_stall_onchip_port_cycles_total": int(_sum_stat(rows, "tensor_stall_onchip_port_cycles_total")),
        "tensor_stall_onchip_bank_conflict_cycles_total": int(_sum_stat(rows, "tensor_stall_onchip_bank_conflict_cycles_total")),
        "tensor_stall_spill_budget_cycles_total": int(_sum_stat(rows, "tensor_stall_spill_budget_cycles_total")),
        "tensor_dma_cycles_total": int(_sum_stat(rows, "tensor_dma_cycles_total")),
        "tensor_dram_bytes_total": int(_sum_stat(rows, "tensor_dram_bytes_total")),
        "tensor_onchip_bytes_total": int(_sum_stat(rows, "tensor_onchip_bytes_total")),
        "tensor_tile_count_total": int(_sum_stat(rows, "tensor_tile_count_total")),
        "tensor_spill_bytes_total": int(_sum_stat(rows, "tensor_spill_bytes_total")),
        "tensor_spill_pkts_total": int(_sum_stat(rows, "tensor_spill_pkts_total")),
        "tensor_collective_bytes_sent_total": int(_sum_stat(rows, "tensor_collective_bytes_sent_total")),
        "tensor_collective_bytes_recv_total": int(_sum_stat(rows, "tensor_collective_bytes_recv_total")),
        "tensor_collective_pkts_sent_total": int(_sum_stat(rows, "tensor_collective_pkts_sent_total")),
        "tensor_collective_pkts_recv_total": int(_sum_stat(rows, "tensor_collective_pkts_recv_total")),
        "tensor_collective_cycles_total": int(_sum_stat(rows, "tensor_collective_cycles_total")),
        "tensor_collective_pending_cycles_total": int(_sum_stat(rows, "tensor_collective_pending_cycles_total")),
        "tensor_collective_issue_cycles_total": int(_sum_stat(rows, "tensor_collective_issue_cycles_total")),
        "tensor_collective_chunk_groups_total": int(_sum_stat(rows, "tensor_collective_chunk_groups_total")),
        "tensor_collective_ring_steps_total": int(_sum_stat(rows, "tensor_collective_ring_steps_total")),
        "tensor_collective_2d_row_rs_steps_total": int(_sum_stat(rows, "tensor_collective_2d_row_rs_steps_total")),
        "tensor_collective_2d_col_rs_steps_total": int(_sum_stat(rows, "tensor_collective_2d_col_rs_steps_total")),
        "tensor_collective_2d_col_ag_steps_total": int(_sum_stat(rows, "tensor_collective_2d_col_ag_steps_total")),
        "tensor_collective_2d_row_ag_steps_total": int(_sum_stat(rows, "tensor_collective_2d_row_ag_steps_total")),
        "tensor_collective_2d_row_rs_bytes_sent_total": int(_sum_stat(rows, "tensor_collective_2d_row_rs_bytes_sent_total")),
        "tensor_collective_2d_col_rs_bytes_sent_total": int(_sum_stat(rows, "tensor_collective_2d_col_rs_bytes_sent_total")),
        "tensor_collective_2d_col_ag_bytes_sent_total": int(_sum_stat(rows, "tensor_collective_2d_col_ag_bytes_sent_total")),
        "tensor_collective_2d_row_ag_bytes_sent_total": int(_sum_stat(rows, "tensor_collective_2d_row_ag_bytes_sent_total")),
        "tensor_collective_reduce_wait_cycles_total": int(_sum_stat(rows, "tensor_collective_reduce_wait_cycles_total")),
        "tensor_collective_2d_reduce_wait_cycles_total": int(_sum_stat(rows, "tensor_collective_2d_reduce_wait_cycles_total")),
        "tensor_collective_epoch_done_total": int(_sum_stat(rows, "tensor_collective_epoch_done_total")),
        "tensor_collective_epoch_latency_cycles_total": int(_sum_stat(rows, "tensor_collective_epoch_latency_cycles_total")),
        "tensor_collective_epoch_latency_cycles_max": int(_sum_stat(rows, "tensor_collective_epoch_latency_cycles_max")),
        "tensor_collective_algo_id": int(_sum_stat(rows, "tensor_collective_algo_id")),
        "tensor_collective_credit_stall_cycles_total": int(_sum_stat(rows, "tensor_collective_credit_stall_cycles_total")),
        "tensor_collective_backpressure_stall_cycles_total": int(_sum_stat(rows, "tensor_collective_backpressure_stall_cycles_total")),
        "tensor_collective_inflight_chunks_max": int(_sum_stat(rows, "tensor_collective_inflight_chunks_max")),
        "tensor_collective_credit_return_pkts_sent_total": int(_sum_stat(rows, "tensor_collective_credit_return_pkts_sent_total")),
        "tensor_collective_credit_return_pkts_recv_total": int(_sum_stat(rows, "tensor_collective_credit_return_pkts_recv_total")),
        "tensor_collective_credit_return_orphan_total": int(_sum_stat(rows, "tensor_collective_credit_return_orphan_total")),
        "tensor_collective_credit_return_dup_total": int(_sum_stat(rows, "tensor_collective_credit_return_dup_total")),
        "tensor_collective_credit_return_latency_cycles_total": int(_sum_stat(rows, "tensor_collective_credit_return_latency_cycles_total")),
        "tensor_collective_credit_return_latency_cycles_max": int(_sum_stat(rows, "tensor_collective_credit_return_latency_cycles_max")),
        "tensor_bank_queue_occupancy_max": int(_sum_stat(rows, "tensor_bank_queue_occupancy_max")),
        "tensor_onchip_weight_occupancy_bytes_max": int(_max_stat(rows, "tensor_onchip_weight_occupancy_bytes_max")),
        "tensor_onchip_weight_bank_occupancy_bytes_max": int(_max_stat(rows, "tensor_onchip_weight_bank_occupancy_bytes_max")),
        "tensor_onchip_a_resident_tiles_max": int(_max_stat(rows, "tensor_onchip_a_resident_tiles_max")),
        "tensor_onchip_b_resident_tiles_max": int(_max_stat(rows, "tensor_onchip_b_resident_tiles_max")),
        "tensor_stall_noc_budget_cycles_total": int(_sum_stat(rows, "tensor_stall_noc_budget_cycles_total")),
        "tensor_overlap_compute_collective_cycles_total": int(_sum_stat(rows, "tensor_overlap_compute_collective_cycles_total")),
        "tensor_overlap_compute_mem_cycles_total": int(_sum_stat(rows, "tensor_overlap_compute_mem_cycles_total")),
        "tensor_pkt_sent_total": int(_sum_stat(rows, "tensor_pkt_sent_total")),
        "tensor_pkt_recv_total": int(_sum_stat(rows, "tensor_pkt_recv_total")),
        "tensor_pkt_bytes_sent_total": int(_sum_stat(rows, "tensor_pkt_bytes_sent_total")),
        "tensor_pkt_bytes_recv_total": int(_sum_stat(rows, "tensor_pkt_bytes_recv_total")),
        "tensor_vector_cycles_total": int(_sum_stat(rows, "tensor_vector_cycles_total")),
        "tensor_program_any_busy_cycles_total": int(_sum_stat(rows, "tensor_program_any_busy_cycles_total")),
        "tensor_program_dma_busy_cycles_total": int(_sum_stat(rows, "tensor_program_dma_busy_cycles_total")),
        "tensor_program_mxu_busy_cycles_total": int(_sum_stat(rows, "tensor_program_mxu_busy_cycles_total")),
        "tensor_program_vec_busy_cycles_total": int(_sum_stat(rows, "tensor_program_vec_busy_cycles_total")),
        "tensor_program_coll_busy_cycles_total": int(_sum_stat(rows, "tensor_program_coll_busy_cycles_total")),
        "tensor_program_ops_total": int(_sum_stat(rows, "tensor_program_ops_total")),
        "tensor_program_iters_total": int(_sum_stat(rows, "tensor_program_iters_total")),
        "tensor_program_fence_count_total": int(_sum_stat(rows, "tensor_program_fence_count_total")),
        "tensor_program_fence_wait_cycles_total": int(_sum_stat(rows, "tensor_program_fence_wait_cycles_total")),
        "tensor_program_ub_stall_cycles_total": int(_sum_stat(rows, "tensor_program_ub_stall_cycles_total")),
        "tensor_program_mem_stall_cycles_total": int(_sum_stat(rows, "tensor_program_mem_stall_cycles_total")),
        "tensor_program_ub_occupancy_bytes_max": int(_max_stat(rows, "tensor_program_ub_occupancy_bytes_max")),
    }

    # Dashboard-friendly derived metrics: keep stable keys even when samples==0.
    mem_r_samples = int(tensor_stats.get("tensor_mem_read_latency_samples_total", 0) or 0)
    mem_r_total = int(tensor_stats.get("tensor_mem_read_latency_cycles_total", 0) or 0)
    tensor_stats["tensor_mem_read_latency_cycles_avg"] = (
        (float(mem_r_total) / float(mem_r_samples)) if mem_r_samples > 0 else 0.0
    )
    mem_w_samples = int(tensor_stats.get("tensor_mem_write_latency_samples_total", 0) or 0)
    mem_w_total = int(tensor_stats.get("tensor_mem_write_latency_cycles_total", 0) or 0)
    tensor_stats["tensor_mem_write_latency_cycles_avg"] = (
        (float(mem_w_total) / float(mem_w_samples)) if mem_w_samples > 0 else 0.0
    )
    row_hit = int(tensor_stats.get("tensor_mem_row_hit_total", 0) or 0)
    row_miss = int(tensor_stats.get("tensor_mem_row_miss_total", 0) or 0)
    row_conflict = int(tensor_stats.get("tensor_mem_row_conflict_total", 0) or 0)
    row_total = row_hit + row_miss + row_conflict
    tensor_stats["tensor_mem_row_hit_ratio"] = (float(row_hit) / float(row_total)) if row_total > 0 else 0.0
    tensor_stats["tensor_mem_row_conflict_ratio"] = (float(row_conflict) / float(row_total)) if row_total > 0 else 0.0
    queue_wait_total = int(tensor_stats.get("tensor_mem_bank_queue_wait_cycles_total", 0) or 0)
    queue_full_total = int(tensor_stats.get("tensor_mem_bank_queue_full_total", 0) or 0)
    tensor_stats["tensor_mem_bank_queue_wait_avg_cycles"] = (
        (float(queue_wait_total) / float(queue_full_total)) if queue_full_total > 0 else 0.0
    )
    proxy_delay_total = int(tensor_stats.get("tensor_mem_proxy_delay_cycles_total", 0) or 0)
    latency_samples_total = mem_r_samples + mem_w_samples
    tensor_stats["tensor_mem_proxy_delay_avg_cycles"] = (
        (float(proxy_delay_total) / float(latency_samples_total)) if latency_samples_total > 0 else 0.0
    )
    row_service_total = int(tensor_stats.get("tensor_mem_row_service_cycles_total", 0) or 0)
    cmd_rdwr = int(tensor_stats.get("tensor_mem_cmd_rdwr_total", 0) or 0)
    tensor_stats["tensor_mem_row_service_avg_cycles"] = (
        (float(row_service_total) / float(cmd_rdwr)) if cmd_rdwr > 0 else 0.0
    )
    cmd_queue_slots_total = int(tensor_stats.get("tensor_mem_cmd_queue_slots_total", 0) or 0)
    cmd_issue_total = int(tensor_stats.get("tensor_mem_cmd_issue_total", 0) or 0)
    cmd_bus_wait_total = int(tensor_stats.get("tensor_mem_cmd_bus_wait_cycles_total", 0) or 0)
    cmd_bg_switch_total = int(tensor_stats.get("tensor_mem_cmd_bus_bg_switch_total", 0) or 0)
    tensor_stats["tensor_mem_cmd_queue_slots_avg"] = (
        (float(cmd_queue_slots_total) / float(latency_samples_total)) if latency_samples_total > 0 else 0.0
    )
    tensor_stats["tensor_mem_cmd_bus_wait_avg_cycles"] = (
        (float(cmd_bus_wait_total) / float(cmd_issue_total)) if cmd_issue_total > 0 else 0.0
    )
    tensor_stats["tensor_mem_cmd_bus_bg_switch_ratio"] = (
        (float(cmd_bg_switch_total) / float(cmd_issue_total)) if cmd_issue_total > 0 else 0.0
    )

    effective_cfg = _load_effective_config(run_dir)
    tensor_cfg = _load_effective_tensor_cfg(run_dir)
    # Expose a few config-side knobs to make trend validators self-contained.
    try:
        tensor_stats["tensor_collective_2d_dim_x"] = int(tensor_cfg.get("tensor_collective_2d_dim_x", 0) or 0)
    except Exception:
        tensor_stats["tensor_collective_2d_dim_x"] = 0
    try:
        tensor_stats["tensor_collective_2d_dim_y"] = int(tensor_cfg.get("tensor_collective_2d_dim_y", 0) or 0)
    except Exception:
        tensor_stats["tensor_collective_2d_dim_y"] = 0
    try:
        tensor_stats["tensor_collective_2d_row_major"] = int(tensor_cfg.get("tensor_collective_2d_row_major", 0) or 0)
    except Exception:
        tensor_stats["tensor_collective_2d_row_major"] = 0
    precision_name = str(tensor_cfg.get("tensor_compute_precision", "fp16") or "fp16").strip().lower()
    if not precision_name:
        precision_name = "fp16"
    tensor_stats["tensor_precision_profile_name"] = precision_name
    tensor_stats["tensor_precision_profile_id"] = _precision_profile_id_from_name(precision_name)

    iter_cycles = int(tensor_stats.get("tensor_iter_cycles_total", 0) or 0)
    if iter_cycles > 0:
        tensor_stats["tensor_effective_mac_per_cycle"] = float(tensor_stats.get("tensor_mac_ops_total", 0) or 0) / float(iter_cycles)
        dram_bytes = int(tensor_stats.get("tensor_mem_bytes_read_total", 0) or 0) + int(tensor_stats.get("tensor_mem_bytes_write_total", 0) or 0)
        tensor_stats["tensor_effective_dram_bytes_per_cycle"] = float(dram_bytes) / float(iter_cycles)
    math_cycles = int(tensor_stats.get("tensor_compute_math_cycles_total", 0) or 0)
    if math_cycles > 0:
        tensor_stats["tensor_effective_mac_per_cycle_math"] = float(tensor_stats.get("tensor_mac_ops_total", 0) or 0) / float(math_cycles)
    if iter_cycles > 0:
        overlap_collective = int(tensor_stats.get("tensor_overlap_compute_collective_cycles_total", 0) or 0)
        overlap_mem = int(tensor_stats.get("tensor_overlap_compute_mem_cycles_total", 0) or 0)
        spill_bytes = int(tensor_stats.get("tensor_spill_bytes_total", 0) or 0)
        bank_conflict_cycles = int(tensor_stats.get("tensor_stall_onchip_bank_conflict_cycles_total", 0) or 0)
        tensor_stats["tensor_overlap_compute_collective_ratio"] = float(overlap_collective) / float(iter_cycles)
        tensor_stats["tensor_overlap_compute_mem_ratio"] = float(overlap_mem) / float(iter_cycles)
        tensor_stats["tensor_spill_bytes_per_iter_cycle"] = float(spill_bytes) / float(iter_cycles)
        tensor_stats["tensor_stall_onchip_bank_conflict_ratio"] = float(bank_conflict_cycles) / float(iter_cycles)
    chunk_groups = int(tensor_stats.get("tensor_collective_chunk_groups_total", 0) or 0)
    ring_steps = int(tensor_stats.get("tensor_collective_ring_steps_total", 0) or 0)
    if chunk_groups > 0:
        tensor_stats["tensor_collective_steps_per_chunk"] = float(ring_steps) / float(chunk_groups)
    pending_cycles = int(tensor_stats.get("tensor_collective_pending_cycles_total", 0) or 0)
    if pending_cycles > 0:
        credit_stall = int(tensor_stats.get("tensor_collective_credit_stall_cycles_total", 0) or 0)
        backpressure_stall = int(tensor_stats.get("tensor_collective_backpressure_stall_cycles_total", 0) or 0)
        tensor_stats["tensor_collective_credit_stall_ratio"] = float(credit_stall) / float(pending_cycles)
        tensor_stats["tensor_collective_backpressure_stall_ratio"] = float(backpressure_stall) / float(pending_cycles)
    credit_return_pkts = int(tensor_stats.get("tensor_collective_credit_return_pkts_recv_total", 0) or 0)
    if credit_return_pkts > 0:
        latency_total = int(tensor_stats.get("tensor_collective_credit_return_latency_cycles_total", 0) or 0)
        tensor_stats["tensor_collective_credit_return_latency_cycles_avg"] = float(latency_total) / float(credit_return_pkts)

    readiness = build_readiness_assessment(tensor_stats, effective_cfg=effective_cfg)
    tensor_stats["tensor_capability_score_total"] = readiness.get("capability_score_total", 0.0)
    tensor_stats["tensor_distance_to_target"] = readiness.get("distance_to_target", 0.0)
    tensor_stats["tensor_calibration_confidence"] = readiness.get("calibration_confidence", "unverified")
    tensor_stats["tensor_gap_rank_topk"] = readiness.get("gap_rank_topk", [])
    tensor_stats["tensor_regression_drift_flags"] = readiness.get("regression_drift_flags", [])
    breakdown = readiness.get("capability_score_breakdown", {})
    if isinstance(breakdown, dict):
        for name, value in breakdown.items():
            tensor_stats[f"tensor_capability_score_{name}"] = value

    payload: Dict[str, Any] = {
        "schema_version": 1,
        "run_dir": str(run_dir),
        "artifacts": {"mesh_stats_csv": str(stats_csv)},
        "sim_time_ns": _infer_sim_time_ns(rows),
        "tensor": tensor_stats,
        "npu_tpu_readiness": readiness,
    }

    if include_stream:
        payload["stream"] = {
            "stream_mem_writes_issued_total": int(_sum_stat(rows, "stream_mem_writes_issued_total")),
            "stream_mem_reads_issued_total": int(_sum_stat(rows, "stream_mem_reads_issued_total")),
            "stream_mem_bytes_written_total": int(_sum_stat(rows, "stream_mem_bytes_written_total")),
            "stream_mem_bytes_read_total": int(_sum_stat(rows, "stream_mem_bytes_read_total")),
            "stream_mem_verify_pass_total": int(_sum_stat(rows, "stream_mem_verify_pass_total")),
            "stream_mem_verify_fail_total": int(_sum_stat(rows, "stream_mem_verify_fail_total")),
            "stream_pkt_sent_total": int(_sum_stat(rows, "stream_pkt_sent_total")),
            "stream_pkt_recv_total": int(_sum_stat(rows, "stream_pkt_recv_total")),
            "stream_pkt_bad_crc_total": int(_sum_stat(rows, "stream_pkt_bad_crc_total")),
            "stream_pkt_bad_magic_total": int(_sum_stat(rows, "stream_pkt_bad_magic_total")),
        }

    out_path = Path(args.out).expanduser().resolve() if args.out else (run_dir / "essential_summary_tensor_mesh.json")
    try:
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:
        print(f"[tensor_mesh] ERROR: write summary failed: {e}")
        return 2

    print(f"[tensor_mesh] summary: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
