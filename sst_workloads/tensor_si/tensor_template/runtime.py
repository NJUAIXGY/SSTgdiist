from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict

from .paths import prepare_run_output_and_stats
from .spec import load_spec
from .spec import resolve_spec
from .utils import tensor_print


DEFAULT_STATS_LEVEL = 7


@dataclass(frozen=True)
class TensorMeshRuntime:
    analysis_dir: str
    run_output_dir: str
    artifacts: Dict[str, str]
    script_dir: str

    mesh_size: int
    node_limit: int
    simulation_time: str

    mesh_cfg: Dict[str, Any]
    tensor_cfg: Dict[str, Any]
    overrides: list[Dict[str, Any]]


def enable_default_statistics(sst_module: Any) -> None:
    sst_module.enableAllStatisticsForComponentType("SnnDL.MultiCorePE", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForComponentType("merlin.hr_router", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForComponentType("SnnDL.SnnPESubComponent", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForComponentType("memHierarchy.MemController", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForComponentType("SnnDL.SnnNIC", {"type": "sst.AccumulatorStatistic"})
    sst_module.enableAllStatisticsForAllComponents({"type": "sst.AccumulatorStatistic"})


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name, "").strip()
    return raw if raw else default


def resolve_runtime(*, sst_module: Any, script_file: str) -> TensorMeshRuntime:
    script_dir = os.path.dirname(os.path.abspath(script_file))

    analysis_dir, run_output_dir, artifacts = prepare_run_output_and_stats(
        sst_module=sst_module,
        script_file=script_file,
        default_stats_level=DEFAULT_STATS_LEVEL,
    )
    enable_default_statistics(sst_module)

    spec_path = os.environ.get("TENSOR_SPEC_JSON", "").strip()
    if spec_path:
        resolved = resolve_spec(load_spec(spec_path))
        runtime_cfg = resolved["runtime"]
        mesh_cfg = resolved["mesh_cfg"]
        tensor_cfg = resolved["tensor_cfg"]
        overrides = list(resolved.get("overrides") or [])
        mesh_size = int(runtime_cfg["mesh_size"])
        node_limit = int(runtime_cfg["node_limit"])
        simulation_time = str(runtime_cfg["simulation_time"])
        total_nodes = int(mesh_cfg.get("total_nodes", mesh_size * mesh_size))
        num_cores_per_pe = int(mesh_cfg.get("num_cores_per_pe", 0))
        core_mem_region_bytes = int(mesh_cfg.get("core_mem_region_bytes", 0))

        tensor_print(
            f"[tensor_mesh] mesh={mesh_size}x{mesh_size} nodes={node_limit}/{total_nodes} "
            f"cores_per_pe={num_cores_per_pe} core_mem={core_mem_region_bytes}B sim={simulation_time}"
        )

        return TensorMeshRuntime(
            analysis_dir=analysis_dir,
            run_output_dir=run_output_dir,
            artifacts=artifacts,
            script_dir=script_dir,
            mesh_size=mesh_size,
            node_limit=node_limit,
            simulation_time=simulation_time,
            mesh_cfg=mesh_cfg,
            tensor_cfg=tensor_cfg,
            overrides=overrides,
        )

    mesh_size = _env_int("TENSOR_SI_MESH_SIZE", 4)
    mesh_size = max(1, mesh_size)
    total_nodes = mesh_size * mesh_size
    node_limit = _env_int("TENSOR_SI_NODE_LIMIT", total_nodes)
    node_limit = max(1, min(node_limit, total_nodes))

    simulation_time = _env_str("TENSOR_SI_SIM_TIME", "10us")

    num_cores_per_pe = _env_int("TENSOR_SI_NUM_CORES_PER_PE", 4)
    neurons_per_core = _env_int("TENSOR_SI_NEURONS_PER_CORE", 4)
    neurons_per_pe = num_cores_per_pe * neurons_per_core

    network_bandwidth = _env_str("TENSOR_SI_NETWORK_BW", "40GiB/s")
    buffer_size = _env_str("TENSOR_SI_BUFFER_SIZE", "8KiB")
    network_num_vns = _env_int("TENSOR_SI_NETWORK_NUM_VNS", 2)

    core_mem_region_bytes = _env_int("TENSOR_SI_CORE_MEM_REGION_BYTES", 1 * 1024 * 1024)
    pe_mem_region_bytes = core_mem_region_bytes * num_cores_per_pe
    workload_stats_modules_raw = os.environ.get("TENSOR_SI_WORKLOAD_STATS_MODULES", "").strip()
    if not workload_stats_modules_raw:
        workload_stats_modules_raw = "tensor"

    mesh_cfg: Dict[str, Any] = {
        "mesh_size": mesh_size,
        "total_nodes": total_nodes,
        "node_limit": node_limit,
        "num_cores_per_pe": num_cores_per_pe,
        "neurons_per_core": neurons_per_core,
        "neurons_per_pe": neurons_per_pe,
        "network_bandwidth": network_bandwidth,
        "buffer_size": buffer_size,
        "network_num_vns": network_num_vns,
        "core_mem_region_bytes": core_mem_region_bytes,
        "pe_mem_region_bytes": pe_mem_region_bytes,
        "mem_access_time": _env_str("TENSOR_SI_MEM_ACCESS_TIME", "100ns"),
        "workload_stats_modules": workload_stats_modules_raw,
    }

    tensor_cfg: Dict[str, Any] = {
        "workload_impl": "tensor",
        "tensor_capability_profile": _env_str("TENSOR_SI_TENSOR_CAPABILITY_PROFILE", "baseline_npu_like_v1"),
        "tensor_scheduler_model": _env_str("TENSOR_SI_TENSOR_SCHEDULER_MODEL", "legacy"),
        "tensor_memory_hierarchy_profile": _env_str(
            "TENSOR_SI_TENSOR_MEMORY_HIERARCHY_PROFILE", "baseline"
        ),
        "tensor_calibration_tag": _env_str("TENSOR_SI_TENSOR_CALIBRATION_TAG", ""),
        "tensor_m": _env_int("TENSOR_SI_TENSOR_M", 256),
        "tensor_n": _env_int("TENSOR_SI_TENSOR_N", 256),
        "tensor_k": _env_int("TENSOR_SI_TENSOR_K", 256),
        "tensor_element_bytes": _env_int("TENSOR_SI_TENSOR_ELEMENT_BYTES", 2),
        "tensor_array_m": _env_int("TENSOR_SI_TENSOR_ARRAY_M", 32),
        "tensor_array_n": _env_int("TENSOR_SI_TENSOR_ARRAY_N", 32),
        "tensor_compute_efficiency": float(os.environ.get("TENSOR_SI_TENSOR_EFF", "1.0") or "1.0"),
        "tensor_compute_precision": _env_str("TENSOR_SI_TENSOR_COMPUTE_PRECISION", "fp16"),
        "tensor_compute_profile_override_enable": _env_int("TENSOR_SI_TENSOR_COMPUTE_PROFILE_OVERRIDE", 0),
        "tensor_compute_throughput_scale": float(
            os.environ.get("TENSOR_SI_TENSOR_COMPUTE_THROUGHPUT_SCALE", "1.0") or "1.0"
        ),
        "tensor_compute_pipeline_latency_cycles": _env_int("TENSOR_SI_TENSOR_COMPUTE_PIPELINE_LATENCY", 0),
        "tensor_mxu_wavefront_enable": _env_int("TENSOR_SI_TENSOR_MXU_WAVEFRONT_ENABLE", 0),
        "tensor_mxu_wavefront_alpha": float(os.environ.get("TENSOR_SI_TENSOR_MXU_WAVEFRONT_ALPHA", "1.0") or "1.0"),
        "tensor_overlap_enable": _env_int("TENSOR_SI_TENSOR_OVERLAP", 1),
        "tensor_start_cycle": _env_int("TENSOR_SI_TENSOR_START_CYCLE", 1),
        "tensor_iterations": _env_int("TENSOR_SI_TENSOR_ITERATIONS", 0),
        "tensor_mem_enable": _env_int("TENSOR_SI_TENSOR_MEM_ENABLE", 1),
        "tensor_mem_region_bytes": core_mem_region_bytes,
        "tensor_mem_req_bytes": _env_int("TENSOR_SI_TENSOR_MEM_REQ_BYTES", 64),
        "tensor_mem_max_outstanding": _env_int("TENSOR_SI_TENSOR_MEM_MAX_OUT", 32),
        "tensor_dataflow": _env_str("TENSOR_SI_TENSOR_DATAFLOW", "os"),
        "tensor_tile_m": _env_int("TENSOR_SI_TENSOR_TILE_M", 0),
        "tensor_tile_n": _env_int("TENSOR_SI_TENSOR_TILE_N", 0),
        "tensor_tile_k": _env_int("TENSOR_SI_TENSOR_TILE_K", 0),
        "tensor_exec_mode": _env_str("TENSOR_SI_TENSOR_EXEC_MODE", "bulk"),
        "tensor_tile_schedule": _env_str("TENSOR_SI_TENSOR_TILE_SCHEDULE", "auto"),
        "tensor_writeback_policy": _env_str("TENSOR_SI_TENSOR_WRITEBACK_POLICY", "at_end_of_k"),
        "tensor_ub_bytes": _env_int("TENSOR_SI_TENSOR_UB_BYTES", 0),
        "tensor_weight_bytes": _env_int("TENSOR_SI_TENSOR_WEIGHT_BYTES", 0),
        "tensor_acc_bytes": _env_int("TENSOR_SI_TENSOR_ACC_BYTES", 0),
        "tensor_onchip_model_enable": _env_int("TENSOR_SI_TENSOR_ONCHIP_MODEL_ENABLE", 0),
        "tensor_ub_bank_bytes": _env_int("TENSOR_SI_TENSOR_UB_BANK_BYTES", 0),
        "tensor_ub_read_ports": _env_int("TENSOR_SI_TENSOR_UB_READ_PORTS", 0),
        "tensor_ub_write_ports": _env_int("TENSOR_SI_TENSOR_UB_WRITE_PORTS", 0),
        "tensor_onchip_bank_model_enable": _env_int("TENSOR_SI_TENSOR_ONCHIP_BANK_MODEL_ENABLE", 0),
        "tensor_ub_bank_count": _env_int("TENSOR_SI_TENSOR_UB_BANK_COUNT", 1),
        "tensor_ub_bank_select_policy": _env_str("TENSOR_SI_TENSOR_UB_BANK_SELECT_POLICY", "interleave"),
        "tensor_ub_bank_conflict_mode": _env_str("TENSOR_SI_TENSOR_UB_BANK_CONFLICT_MODE", "queue"),
        "tensor_acc_bank_bytes": _env_int("TENSOR_SI_TENSOR_ACC_BANK_BYTES", 0),
        "tensor_acc_read_ports": _env_int("TENSOR_SI_TENSOR_ACC_READ_PORTS", 0),
        "tensor_acc_write_ports": _env_int("TENSOR_SI_TENSOR_ACC_WRITE_PORTS", 0),
        "tensor_acc_bank_count": _env_int("TENSOR_SI_TENSOR_ACC_BANK_COUNT", 1),
        "tensor_acc_bank_select_policy": _env_str("TENSOR_SI_TENSOR_ACC_BANK_SELECT_POLICY", "interleave"),
        "tensor_acc_bank_conflict_mode": _env_str("TENSOR_SI_TENSOR_ACC_BANK_CONFLICT_MODE", "queue"),
        "tensor_bank_queue_depth": _env_int("TENSOR_SI_TENSOR_BANK_QUEUE_DEPTH", 16),
        "tensor_spill_enable": _env_int("TENSOR_SI_TENSOR_SPILL_ENABLE", 0),
        "tensor_spill_packet_bytes": _env_int("TENSOR_SI_TENSOR_SPILL_PACKET_BYTES", 256),
        "tensor_spill_share_noc_budget": _env_int("TENSOR_SI_TENSOR_SPILL_SHARE_NOC_BUDGET", 1),
        "tensor_dma_bandwidth_bytes_per_cycle": _env_int("TENSOR_SI_TENSOR_DMA_BW", 0),
        "tensor_dma_shared_bandwidth_bytes_per_cycle": _env_int("TENSOR_SI_TENSOR_DMA_BW_SHARED", 0),
        "tensor_dma_hbm_channels": _env_int("TENSOR_SI_TENSOR_DMA_HBM_CHANNELS", 1),
        "tensor_dma_hbm_channel_bandwidth_bytes_per_cycle": _env_int("TENSOR_SI_TENSOR_DMA_HBM_CH_BW", 0),
        "tensor_dma_hbm_channel_interleave_bytes": _env_int("TENSOR_SI_TENSOR_DMA_HBM_CH_INTERLEAVE", 256),
        "tensor_double_buffer": _env_int("TENSOR_SI_TENSOR_DOUBLE_BUFFER", 0),
        "tensor_collective_type": _env_str("TENSOR_SI_TENSOR_COLLECTIVE_TYPE", "none"),
        "tensor_collective_blocking": _env_int("TENSOR_SI_TENSOR_COLLECTIVE_BLOCKING", 0),
        "tensor_collective_scope": _env_str("TENSOR_SI_TENSOR_COLLECTIVE_SCOPE", "per_core"),
        "tensor_collective_bytes": _env_int("TENSOR_SI_TENSOR_COLLECTIVE_BYTES", 0),
        "tensor_collective_period_cycles": _env_int("TENSOR_SI_TENSOR_COLLECTIVE_PERIOD", 0),
        "tensor_collective_pattern": _env_str("TENSOR_SI_TENSOR_COLLECTIVE_PATTERN", "ring"),
        "tensor_collective_packet_bytes": _env_int("TENSOR_SI_TENSOR_COLLECTIVE_PACKET_BYTES", 256),
        "tensor_collective_algo": _env_str("TENSOR_SI_TENSOR_COLLECTIVE_ALGO", "legacy_bytes"),
        "tensor_collective_chunk_bytes": _env_int("TENSOR_SI_TENSOR_COLLECTIVE_CHUNK_BYTES", 0),
        "tensor_collective_reduce_overhead_cycles": _env_int("TENSOR_SI_TENSOR_COLLECTIVE_REDUCE_OVERHEAD_CYCLES", 0),
        "tensor_collective_max_inflight_chunks": _env_int("TENSOR_SI_TENSOR_COLLECTIVE_MAX_INFLIGHT_CHUNKS", 1),
        "tensor_collective_credit_enable": _env_int("TENSOR_SI_TENSOR_COLLECTIVE_CREDIT_ENABLE", 0),
        "tensor_collective_credit_window_chunks": _env_int("TENSOR_SI_TENSOR_COLLECTIVE_CREDIT_WINDOW_CHUNKS", 0),
        "tensor_collective_credit_return_mode": _env_str("TENSOR_SI_TENSOR_COLLECTIVE_CREDIT_RETURN_MODE", "event_on_recv"),
        "tensor_collective_backpressure_mode": _env_str("TENSOR_SI_TENSOR_COLLECTIVE_BACKPRESSURE_MODE", "hard"),
        "tensor_noc_bandwidth_bytes_per_cycle": _env_int("TENSOR_SI_TENSOR_NOC_BW", 0),
        "tensor_collective_overlap_with_compute": _env_int("TENSOR_SI_TENSOR_COLLECTIVE_OVERLAP_WITH_COMPUTE", 1),
        "tensor_collective_issue_priority": _env_str("TENSOR_SI_TENSOR_COLLECTIVE_ISSUE_PRIORITY", "control_first"),
        "tensor_comm_enable": _env_int("TENSOR_SI_TENSOR_COMM_ENABLE", 0),
        "tensor_comm_period_cycles": _env_int("TENSOR_SI_TENSOR_COMM_PERIOD", 0),
        "tensor_comm_payload_bytes": _env_int("TENSOR_SI_TENSOR_COMM_BYTES", 0),
        "tensor_strict": _env_int("TENSOR_SI_TENSOR_STRICT", 1),
        "tensor_seed": int(os.environ.get("TENSOR_SI_TENSOR_SEED", "0") or "0"),
    }

    tensor_print(
        f"[tensor_mesh] mesh={mesh_size}x{mesh_size} nodes={node_limit}/{total_nodes} "
        f"cores_per_pe={num_cores_per_pe} core_mem={core_mem_region_bytes}B sim={simulation_time}"
    )

    return TensorMeshRuntime(
        analysis_dir=analysis_dir,
        run_output_dir=run_output_dir,
        artifacts=artifacts,
        script_dir=script_dir,
        mesh_size=mesh_size,
        node_limit=node_limit,
        simulation_time=simulation_time,
        mesh_cfg=mesh_cfg,
        tensor_cfg=tensor_cfg,
        overrides=[],
    )
