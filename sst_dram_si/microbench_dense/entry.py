from __future__ import annotations

import json
import os
from typing import Any, Dict

import sst

from mesh_template.build import build_global_gas_step_controller
from mesh_template.build import build_mesh_4x4
from mesh_template.paths import prepare_run_output_and_stats
from mesh_template.task_snn import build_layers_cfg
from mesh_template.utils import align_up


def _load_local_config(script_file: str) -> Dict[str, Any]:
    script_dir = os.path.dirname(os.path.abspath(script_file))
    cfg_path = os.path.join(script_dir, "local_run_config.json")
    if not os.path.exists(cfg_path):
        return {}
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def run_dense_microbench(*, sst_module: Any, script_file: str) -> Dict[str, Any]:
    """
    Dense microbench entry:
    - Always uses dense layout (no global BCSR meta scanning, no BCSR routes).
    - Uses Step random activation (in-core) to generate reads.
    - Supports exec_mode=gas|naive_raw via MESH_EXEC_MODE.
    - Uses GlobalGasStepController(max_steps) to stop.

    Local config: <script_dir>/local_run_config.json
    Env overrides: MESH_EXEC_MODE, MESH_MAX_STEPS, MESH_SIM_TIME,
                   MESH_STEP_ACTIVATION_FRACTION/FANOUT/SEED, MESH_NODE_LIMIT.
    """

    cfg = _load_local_config(script_file)

    overrides = None
    overrides_json = (os.environ.get("MESH_OVERRIDES_JSON") or "").strip()
    if overrides_json:
        try:
            parsed = json.loads(overrides_json)
            overrides = parsed if isinstance(parsed, list) else None
        except Exception:
            overrides = None

    exec_mode = str(os.environ.get("MESH_EXEC_MODE", cfg.get("exec_mode", "gas"))).strip().lower()
    if exec_mode == "naive_opt":
        exec_mode = "naive_raw"
    if exec_mode not in ("gas", "naive_raw"):
        exec_mode = "gas"

    max_steps_env = os.environ.get("MESH_MAX_STEPS", "").strip()
    try:
        max_steps = int(max_steps_env) if max_steps_env else int(cfg.get("max_steps", 1))
    except Exception:
        max_steps = 1
    if max_steps < 0:
        max_steps = 0

    mesh_size = int(cfg.get("mesh_size", 1))
    num_cores_per_pe = int(cfg.get("num_cores_per_pe", 1))
    neurons_per_core = int(cfg.get("neurons_per_core", 500))
    v = os.environ.get("MESH_NEURONS_PER_CORE", "").strip()
    if v:
        try:
            neurons_per_core = int(v, 0)
            cfg["neurons_per_core"] = int(neurons_per_core)
        except Exception:
            pass

    # Dense microbench pattern + byte-exact verifier must agree on row_scale.
    # Allow env override so scaling sweeps do not require editing local_run_config.json.
    v = os.environ.get("MESH_BYTE_EXACT_VERIFY_ROW_SCALE", "").strip()
    if v:
        try:
            cfg["byte_exact_verify_row_scale"] = int(v, 0)
        except Exception:
            pass
    v = os.environ.get("MESH_LOADER_WRITE_PATTERN_ROW_SCALE", "").strip()
    if v:
        try:
            cfg["loader_write_pattern_row_scale"] = int(v, 0)
        except Exception:
            pass

    total_nodes = mesh_size * mesh_size
    node_limit_env = os.environ.get("MESH_NODE_LIMIT", "").strip()
    try:
        node_limit = int(node_limit_env) if node_limit_env else int(cfg.get("node_limit", total_nodes))
    except Exception:
        node_limit = total_nodes
    node_limit = max(1, min(node_limit, total_nodes))

    disable_network = bool(cfg.get("disable_network", True))
    # Allow env override so experiments don't need to edit local_run_config.json.
    l1_enable = bool(cfg.get("l1_enable", False))
    v = os.environ.get("MESH_L1_ENABLE", "").strip()
    if v:
        try:
            l1_enable = bool(int(v))
        except Exception:
            l1_enable = v.lower() in ("1", "true", "yes", "on")

    sim_time_env = os.environ.get("MESH_SIM_TIME", "").strip()
    simulation_time = sim_time_env if sim_time_env else str(cfg.get("sim_time", "100us"))

    frac = cfg.get("step_activation_fraction", 0.01)
    fanout = cfg.get("step_activation_fanout", 256)
    seed = cfg.get("step_activation_seed", 271828)
    v = os.environ.get("MESH_STEP_ACTIVATION_FRACTION", "").strip()
    if v:
        try:
            frac = float(v)
        except Exception:
            pass
    v = os.environ.get("MESH_STEP_ACTIVATION_FANOUT", "").strip()
    if v:
        try:
            fanout = int(v)
        except Exception:
            pass
    v = os.environ.get("MESH_STEP_ACTIVATION_SEED", "").strip()
    if v:
        try:
            seed = int(v)
        except Exception:
            pass

    # Memory backend selection (simple vs Ramulator2).
    mem_backend = str(cfg.get("mem_backend", "simple") or "simple").strip().lower()
    v = os.environ.get("MESH_MEM_BACKEND", "").strip()
    if v:
        mem_backend = v.strip().lower()
    if mem_backend in ("simplemem", "simple_mem"):
        mem_backend = "simple"
    if mem_backend in ("ram2",):
        mem_backend = "ramulator2"
    if mem_backend not in ("simple", "ramulator2"):
        mem_backend = "simple"

    ramulator2_config_file = str(cfg.get("ramulator2_config_file", "") or "").strip()
    v = os.environ.get("MESH_RAMULATOR2_CONFIG_FILE", "").strip()
    if v:
        ramulator2_config_file = v

    # Dense-only memory layout:
    # - rows = neurons_per_core
    # - cols = global neuron count
    neurons_per_pe = num_cores_per_pe * neurons_per_core
    global_weights_cols = total_nodes * neurons_per_pe
    line_size_bytes = int(cfg.get("line_size_bytes", 64) or 64)

    # Dense layout mode (row_major vs phys_v1). Used only for microbench stride sizing;
    # the actual SnnDL core layout is configured via params/overrides.
    def _infer_override_param(key: str):
        if overrides is None:
            return None
        for rule in overrides:
            if not isinstance(rule, dict):
                continue
            params = rule.get("params") or {}
            if not isinstance(params, dict):
                continue
            if key in params:
                return params.get(key)
        return None

    dense_layout_mode = str(cfg.get("dense_layout_mode", "row_major") or "row_major").strip().lower()
    v = os.environ.get("MESH_DENSE_LAYOUT_MODE", "").strip()
    if v:
        dense_layout_mode = v.strip().lower()
    else:
        ov = _infer_override_param("dense_layout_mode")
        if ov is not None:
            dense_layout_mode = str(ov).strip().lower()
    if dense_layout_mode in ("row", "rowmajor", "row-major"):
        dense_layout_mode = "row_major"
    if dense_layout_mode in ("physv1", "phys-v1"):
        dense_layout_mode = "phys_v1"
    if dense_layout_mode not in ("row_major", "phys_v1"):
        dense_layout_mode = "row_major"

    dense_phys_dram_row_bytes = int(cfg.get("dense_phys_dram_row_bytes", 8192) or 8192)
    v = os.environ.get("MESH_DENSE_PHYS_DRAM_ROW_BYTES", "").strip()
    if v:
        try:
            dense_phys_dram_row_bytes = int(v, 0)
        except Exception:
            pass
    else:
        ov = _infer_override_param("dense_phys_dram_row_bytes")
        if ov is not None:
            try:
                dense_phys_dram_row_bytes = int(ov)
            except Exception:
                pass
    if dense_phys_dram_row_bytes <= 0:
        dense_phys_dram_row_bytes = 8192

    # PhysV1 dense layout requires byte-exact verifier to decode the same physical mapping.
    # We keep this injection script-scoped (microbench only) to avoid polluting global configs.
    if dense_layout_mode == "phys_v1":
        if overrides is None:
            overrides = []

        has_gatherbuf_layout = False
        for rule in overrides:
            if not isinstance(rule, dict):
                continue
            match = rule.get("match") or {}
            if not isinstance(match, dict):
                continue
            if str(match.get("role", "")) != "pe.core.memory_if":
                continue
            if str(match.get("type", "")) != "SnnDL.GatherBufferIF":
                continue
            params = rule.get("params") or {}
            if not isinstance(params, dict):
                continue
            if "byte_exact_dense_layout_mode" in params or "byte_exact_dense_phys_dram_row_bytes" in params:
                has_gatherbuf_layout = True
                break

        if not has_gatherbuf_layout:
            overrides.append(
                {
                    "match": {"role": "pe.core.memory_if", "type": "SnnDL.GatherBufferIF"},
                    "params": {
                        "byte_exact_dense_layout_mode": "phys_v1",
                        "byte_exact_dense_phys_dram_row_bytes": int(dense_phys_dram_row_bytes),
                    },
                    # Only strict when GAS path is active (naive_raw has no GatherBufferIF).
                    "strict": bool(exec_mode == "gas"),
                }
            )

    dense_bytes = int(neurons_per_core) * int(global_weights_cols) * 4
    if dense_layout_mode == "phys_v1":
        bytes_per_weight = 4
        logical_row_bytes = int(global_weights_cols) * bytes_per_weight
        row_stride_bytes = align_up(logical_row_bytes, int(line_size_bytes))
        dram_row_bytes = int(dense_phys_dram_row_bytes)
        if row_stride_bytes <= dram_row_bytes:
            rows_per_dram_row = max(1, dram_row_bytes // row_stride_bytes)
            group_stride_bytes = dram_row_bytes
        else:
            rows_per_dram_row = 1
            group_stride_bytes = align_up(row_stride_bytes, dram_row_bytes)
        groups = (int(neurons_per_core) + rows_per_dram_row - 1) // rows_per_dram_row
        total_bytes = groups * group_stride_bytes
        per_core_weight_stride = int(total_bytes)
    else:
        per_core_weight_stride = align_up(dense_bytes, 8192)
    pe_weight_region_stride = per_core_weight_stride * num_cores_per_pe
    base_addr_global_shift = per_core_weight_stride

    # Stats/run dir (must run before creating components)
    _, run_output_dir, artifacts = prepare_run_output_and_stats(
        sst_module=sst_module,
        script_file=script_file,
        default_stats_level=int(cfg.get("stats_verbose", 7)),
    )

    # Persist minimal provenance for post-processing tools.
    # We write an effective `inputs/local_run_config.json` (cfg + env overrides) later, right
    # before instantiating SST components.
    try:
        inputs_dir = os.path.join(run_output_dir, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
    except Exception:
        pass

    # Microbench needs a compact but complete mesh_stats.csv for validation.
    # DO NOT enable all stats globally (would enable GatherBufferIF stats and crash, since it is instantiated in init()).
    try:
        sst_module.enableAllStatisticsForComponentType("SnnDL.MultiCorePE", {"type": "sst.AccumulatorStatistic"})
        sst_module.enableAllStatisticsForComponentType("memHierarchy.MemController", {"type": "sst.AccumulatorStatistic"})
        sst_module.enableAllStatisticsForComponentType("memHierarchy.Cache", {"type": "sst.AccumulatorStatistic"})
        sst_module.enableAllStatisticsForComponentType("SnnDL.WeightLoader", {"type": "sst.AccumulatorStatistic"})
        sst_module.enableAllStatisticsForComponentType("SnnDL.SnnNIC", {"type": "sst.AccumulatorStatistic"})
        sst_module.enableAllStatisticsForComponentType("SnnDL.SnnPESubComponent", {"type": "sst.AccumulatorStatistic"})
    except Exception:
        pass

    global_step_ctrl = build_global_gas_step_controller(
        enabled=True,
        verbose=int(cfg.get("global_step_ctrl_verbose", 0) or 0),
        start_seq=1,
        max_steps=max_steps,
        require_all_ready=1,
        strict_seq_check=1,
    )

    # Minimal layers: only PE0 is considered input for threshold selection.
    layers = build_layers_cfg(
        layers={"input_layer": [0], "hidden_layer_1": [], "hidden_layer_2": [], "output_layer": []},
        thresholds=cfg.get("thresholds"),
        core_tau_mem=float(cfg.get("tau_mem", 20.0)),
    )

    gas_cfg = {
        "window_cycles": {
            "gather": int(cfg.get("gas_window_cycles_gather", 200)),
            "apply": int(cfg.get("gas_window_cycles_apply", 40)),
            "scatter": int(cfg.get("gas_window_cycles_scatter", 40)),
        },
        # Default to cacheline semantics; row-streaming/DMA must be an explicit opt-in.
        "merge_policy": str(cfg.get("gas_merge_policy", "cacheline")),
        "gap_k_bytes": int(cfg.get("gas_gap_k_bytes", 2048)),
        "lmax_bytes": int(cfg.get("gas_lmax_bytes", 65536)),
        "max_inflight": int(cfg.get("gas_max_inflight", 128)),
        "sort_policy": str(cfg.get("gas_sort_policy", "row") or "row"),
        "row_bytes_guess": int(cfg.get("gas_row_bytes_guess", 8192) or 8192),
        "bank_bits": int(cfg.get("gas_bank_bits", 0) or 0),
        "bank_shift": int(cfg.get("gas_bank_shift", 0) or 0),
        "bank_auto_enable": int(cfg.get("gas_bank_auto_enable", 1) or 1),
        "row_window_bytes": int(cfg.get("gas_row_window_bytes", 0)),
        "row_window_timeout_ns": int(cfg.get("gas_row_window_timeout_ns", 0)),
        "apply_issue_policy": str(cfg.get("gas_apply_issue_policy", "order") or "order"),
        "apply_frags_per_issue": int(cfg.get("gas_apply_frags_per_issue", 1) or 1),
        "apply_bank_credit": int(cfg.get("gas_apply_bank_credit", 1) or 1),
        "apply_age_fair_ns": int(cfg.get("gas_apply_age_fair_ns", 2000) or 2000),
        # Experimental: DRAM command-cost guided merge guardrails (segment-build stage; default OFF).
        "dram_cmd_cost_merge_enable": int(cfg.get("gas_dram_cmd_cost_merge_enable", 0) or 0),
        "dram_cmd_t_row_hit_ns": int(cfg.get("gas_dram_cmd_t_row_hit_ns", 30) or 30),
        "dram_cmd_t_row_miss_ns": int(cfg.get("gas_dram_cmd_t_row_miss_ns", 120) or 120),
    }

    # Env overrides for merge-matrix experiments (avoid editing local_run_config.json repeatedly).
    def _env_int(key: str, cur: int) -> int:
        v = (os.environ.get(key) or "").strip()
        if not v:
            return cur
        try:
            return int(v, 0)
        except Exception:
            return cur

    def _env_str(key: str, cur: str) -> str:
        v = (os.environ.get(key) or "").strip()
        return v if v else cur

    gas_cfg["window_cycles"]["gather"] = _env_int("MESH_GAS_WINDOW_CYCLES_GATHER", int(gas_cfg["window_cycles"]["gather"]))
    gas_cfg["window_cycles"]["apply"] = _env_int("MESH_GAS_WINDOW_CYCLES_APPLY", int(gas_cfg["window_cycles"]["apply"]))
    gas_cfg["window_cycles"]["scatter"] = _env_int("MESH_GAS_WINDOW_CYCLES_SCATTER", int(gas_cfg["window_cycles"]["scatter"]))
    gas_cfg["merge_policy"] = _env_str("MESH_GAS_MERGE_POLICY", str(gas_cfg["merge_policy"]))
    gas_cfg["gap_k_bytes"] = _env_int("MESH_GAS_GAP_K_BYTES", int(gas_cfg["gap_k_bytes"]))
    gas_cfg["lmax_bytes"] = _env_int("MESH_GAS_LMAX_BYTES", int(gas_cfg["lmax_bytes"]))
    gas_cfg["sort_policy"] = _env_str("MESH_GAS_SORT_POLICY", str(gas_cfg.get("sort_policy", "row") or "row"))
    gas_cfg["row_bytes_guess"] = _env_int("MESH_GAS_ROW_BYTES_GUESS", int(gas_cfg.get("row_bytes_guess", 8192) or 8192))
    gas_cfg["bank_bits"] = _env_int("MESH_GAS_BANK_BITS", int(gas_cfg.get("bank_bits", 0) or 0))
    gas_cfg["bank_shift"] = _env_int("MESH_GAS_BANK_SHIFT", int(gas_cfg.get("bank_shift", 0) or 0))
    gas_cfg["bank_auto_enable"] = _env_int("MESH_GAS_BANK_AUTO_ENABLE", int(gas_cfg.get("bank_auto_enable", 1) or 1))
    gas_cfg["row_window_bytes"] = _env_int("MESH_GAS_ROW_WINDOW_BYTES", int(gas_cfg["row_window_bytes"]))
    gas_cfg["row_window_timeout_ns"] = _env_int("MESH_GAS_ROW_WINDOW_TIMEOUT_NS", int(gas_cfg["row_window_timeout_ns"]))
    gas_cfg["max_inflight"] = _env_int("MESH_GAS_MAX_INFLIGHT", int(gas_cfg["max_inflight"]))
    gas_cfg["apply_issue_policy"] = _env_str("MESH_GAS_APPLY_ISSUE_POLICY", str(gas_cfg.get("apply_issue_policy", "order")))
    gas_cfg["apply_frags_per_issue"] = _env_int("MESH_GAS_APPLY_FRAGS_PER_ISSUE", int(gas_cfg.get("apply_frags_per_issue", 1) or 1))
    gas_cfg["apply_bank_credit"] = _env_int("MESH_GAS_APPLY_BANK_CREDIT", int(gas_cfg.get("apply_bank_credit", 1) or 1))
    gas_cfg["apply_age_fair_ns"] = _env_int("MESH_GAS_APPLY_AGE_FAIR_NS", int(gas_cfg.get("apply_age_fair_ns", 2000) or 2000))
    gas_cfg["dram_cmd_cost_merge_enable"] = _env_int(
        "MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE",
        int(gas_cfg.get("dram_cmd_cost_merge_enable", 0) or 0),
    )
    gas_cfg["dram_cmd_t_row_hit_ns"] = _env_int(
        "MESH_GAS_DRAM_CMD_T_ROW_HIT_NS",
        int(gas_cfg.get("dram_cmd_t_row_hit_ns", 30) or 30),
    )
    gas_cfg["dram_cmd_t_row_miss_ns"] = _env_int(
        "MESH_GAS_DRAM_CMD_T_ROW_MISS_NS",
        int(gas_cfg.get("dram_cmd_t_row_miss_ns", 120) or 120),
    )

    step_cfg = {
        "random_activation_enable": 1 if bool(cfg.get("step_random_activation_enable", 1)) else 0,
        "activation_period_cycles": int(cfg.get("step_activation_period_cycles", 0)),
        "activation_fraction": float(frac),
        "activation_fanout": int(fanout),
        "activation_seed": int(seed),
        "activation_event_weight": float(cfg.get("step_activation_event_weight", 0.0)),
        "activation_trigger_core": int(cfg.get("step_activation_trigger_core", 0)),
        "activation_use_bcsr_routes": False,
        "activation_template": "",
        "activation_bcsr_rows_per_core": int(neurons_per_core),
        "activation_bcsr_br": 16,
        "activation_bcsr_bc": 16,
        "activation_bcsr_idx_bytes": 2,
        "activation_bcsr_val_bytes": 4,
        "activation_bcsr_rowptr_offset": 0,
        "activation_bcsr_colidx_offset": 0,
        "activation_bcsr_blockdata_offset": 0,
        "activation_bcsr_blockids_offset": 0,
        "activation_bcsr_can_load": False,
        "activation_bcsr_weight_epsilon": 0.0,
        "reset_mem_each_step": int(cfg.get("step_reset_mem_each_step", 0)),
    }

    mesh_cfg = {
        "num_cores_per_pe": int(num_cores_per_pe),
        "neurons_per_core": int(neurons_per_core),
        "neurons_per_pe": int(neurons_per_pe),
        "total_nodes": int(total_nodes),
        "global_weights_cols": int(global_weights_cols),
        "global_bcsr_available": False,
        "global_bcsr_dir": "",
        "global_bcsr_offsets": {},
        "network_bandwidth": str(cfg.get("network_bandwidth", "40GiB/s")),
        "buffer_size": str(cfg.get("buffer_size", "8KiB")),
        "core_memory_warmup_cycles": int(cfg.get("core_memory_warmup_cycles", 200)),
        "core_loader_barrier_cycles": int(cfg.get("core_loader_barrier_cycles", 0)),
        "force_dense": True,
        "verify_routing": 0,
        "bcsr_opt_level": "none",
        # Microbench knobs (optional):
        # - max_outstanding_requests: controls per-core weight-read throttle in WeightMemorySubsystem (NOT memHierarchy inflight).
        # - window_read_budget: per-window issued-read budget; 0 disables budget to avoid truncating Apply.
        "max_outstanding_requests": int(cfg.get("max_outstanding_requests", 0) or 0),
        "window_read_budget": int(cfg.get("window_read_budget", -1)),
        "byte_exact_verify_enable": int(cfg.get("byte_exact_verify_enable", 0)),
        "byte_exact_verify_mode": str(cfg.get("byte_exact_verify_mode", "")),
        "byte_exact_verify_row_scale": int(cfg.get("byte_exact_verify_row_scale", 1024)),
        "byte_exact_verify_max_mismatch": int(cfg.get("byte_exact_verify_max_mismatch", 8)),
    }

    flags_cfg = {
        "disable_network": bool(disable_network),
        "export_spike_csv": False,
        "spikes_mesh_csv": str(artifacts["spikes_mesh_csv"]),
        "enable_node_summary": False,
        "enable_test_traffic": False,
        "event_fallback": False,
        "diag_fire_log": False,
        "global_step_sync_enable": True,
        "exec_mode": str(exec_mode),
        "max_steps": int(max_steps),
        "sim_stop_ns": 0,
        # Dense microbench correctness: byte-exact verification requires real edge recording to
        # exercise the WMS issue/retire path (not just counters).
        "record_edge_apply_enable": 1 if bool(cfg.get("byte_exact_verify_enable", 0)) else 0,
        "record_edge_idle_enable": 1 if bool(cfg.get("byte_exact_verify_enable", 0)) else 0,
        "record_edge_scatter_enable": 0,
        "use_soa_state": int(cfg.get("use_soa", 0) or 0),
        "use_aosoa_state": int(cfg.get("use_aosoa", 0) or 0),
        "aosoa_block_rows": int(cfg.get("aosoa_block_rows", 16) or 16),
        "verify_cluster_enable": 0,
    }

    mem_layout_cfg = {
        "per_core_weight_stride": int(per_core_weight_stride),
        "pe_weight_region_stride": int(pe_weight_region_stride),
        "base_addr_global_shift": int(base_addr_global_shift),
        "mem_backend": str(mem_backend),
        "ramulator2_config_file": str(ramulator2_config_file),
        "l1_enable": bool(l1_enable),
        "l1_size_str": str(cfg.get("l1_size", "16KiB")),
        "l1_assoc": int(cfg.get("l1_assoc", 8)),
        "l1_line_bytes_str": str(cfg.get("line_size_bytes", "64")),
        "subcomp_line_bytes": int(line_size_bytes),
    }

    routing_cfg = {
        "mode": "weight_driven",
        "epsilon": float(cfg.get("routing_epsilon", 0.6)),
        "topk_per_pe": int(cfg.get("routing_topk_per_pe", 2)),
        "topk": int(cfg.get("routing_topk", 12)),
    }

    debug_cfg = {
        "sentinel_enable": False,
        "progress_log_interval_ns": 0,
        "progress_log_node": -1,
        "window_read_debug": False,
        "window_read_debug_all_cores": False,
        "debug_target_pe": 0,
        "debug_target_core": 0,
        "core_verbose": 0,
    }

    loader_cfg = {
        "pe_mem_addr_range": int(pe_weight_region_stride),
        "loader_chunk_bytes": int(cfg.get("loader_chunk_bytes", 64)),
        "loader_timed_seed_enable": bool(cfg.get("loader_timed_seed_enable", 0)),
        "loader_timed_seed_allow_cache": bool(cfg.get("loader_timed_seed_allow_cache", 0)),
        "loader_verify_readback": False,
        "loader_verify_bytes": int(cfg.get("loader_verify_bytes", 64)),
        "loader_verify_mode": str(cfg.get("loader_verify_mode", "")),
        "loader_verify_samples": int(cfg.get("loader_verify_samples", 0)),
        "loader_verify_seed": int(cfg.get("loader_verify_seed", 0)),
        "loader_verify_colidx_start": int(cfg.get("loader_verify_colidx_start", 0)),
        "loader_diag_timed_read": False,
        "loader_diag_timed_read_colidx_start": 0,
        "loader_write_pattern_mode": str(cfg.get("loader_write_pattern_mode", "")),
        "loader_write_pattern_row_scale": int(cfg.get("loader_write_pattern_row_scale", 1024)),
    }

    loader_verify_readback = bool(cfg.get("loader_verify_readback", 0))
    v = os.environ.get("MESH_LOADER_VERIFY_READBACK", "").strip()
    if v:
        try:
            loader_verify_readback = bool(int(v))
        except Exception:
            loader_verify_readback = v.lower() in ("1", "true", "yes", "on")
    loader_cfg["loader_verify_readback"] = bool(loader_verify_readback)

    try:
        inputs_dir = os.path.join(run_output_dir, "inputs")
        os.makedirs(inputs_dir, exist_ok=True)
        effective_cfg = dict(cfg)
        effective_cfg.update({
            "exec_mode": str(exec_mode),
            "max_steps": int(max_steps),
            "sim_time": str(simulation_time),
            "l1_enable": bool(l1_enable),
            "mem_backend": str(mem_backend),
            "ramulator2_config_file": str(ramulator2_config_file),
            "dense_layout_mode": str(dense_layout_mode),
            "dense_phys_dram_row_bytes": int(dense_phys_dram_row_bytes),
            "per_core_weight_stride": int(per_core_weight_stride),
            "step_activation_fraction": float(frac),
            "step_activation_fanout": int(fanout),
            "step_activation_seed": int(seed),
            "loader_verify_readback": bool(loader_verify_readback),
        })
        with open(os.path.join(inputs_dir, "local_run_config.json"), "w", encoding="utf-8") as f:
            json.dump(effective_cfg, f, indent=2, sort_keys=True)
            f.write("\n")
    except Exception:
        pass

    # meta.json: effective run knobs (incl. env overrides). Written after building config dicts but
    # before instantiating SST components.
    try:
        sst_n = 0
        v = (os.environ.get("MESH_SST_N") or "").strip()
        if v:
            try:
                sst_n = int(v)
            except Exception:
                sst_n = 0
        kind = f"dense_microbench_{mesh_size}x{mesh_size}" if int(mesh_size) > 1 else "dense_microbench_1pe"
        meta = {
            "kind": kind,
            "exec_mode": str(exec_mode),
            "max_steps": int(max_steps),
            "sst_n": int(sst_n),
            "timebase": "1ps",
            "mesh_size": int(mesh_size),
            "node_limit": int(node_limit),
            "num_cores_per_pe": int(num_cores_per_pe),
            "neurons_per_core": int(neurons_per_core),
            "disable_network": bool(disable_network),
            "l1_enable": int(bool(l1_enable)),
            "mem_backend": str(mem_backend),
            "ramulator2_config_file": str(ramulator2_config_file),
            "dense_layout_mode": str(dense_layout_mode),
            "dense_phys_dram_row_bytes": int(dense_phys_dram_row_bytes),
            "per_core_weight_stride": int(per_core_weight_stride),
            "sim_time": str(simulation_time),
            "allow_zero_firing_long": bool(cfg.get("allow_zero_firing_long", False)),
            "global_step_sync_enable": True,
            "step_activation_fraction": float(frac),
            "step_activation_fanout": int(fanout),
            "step_activation_seed": int(seed),
            "loader_verify_readback": bool(loader_verify_readback),
            "gas_merge_policy": str(gas_cfg.get("merge_policy", "")),
            "gas_apply_issue_policy": str(gas_cfg.get("apply_issue_policy", "")),
            "gas_gap_k_bytes": int(gas_cfg.get("gap_k_bytes", 0) or 0),
            "gas_lmax_bytes": int(gas_cfg.get("lmax_bytes", 0) or 0),
            "gas_row_window_bytes": int(gas_cfg.get("row_window_bytes", 0) or 0),
            "gas_row_window_timeout_ns": int(gas_cfg.get("row_window_timeout_ns", 0) or 0),
            "gas_max_inflight": int(gas_cfg.get("max_inflight", 0) or 0),
        }
        with open(os.path.join(run_output_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, sort_keys=True)
            f.write("\n")
    except Exception:
        pass

    built = build_mesh_4x4(
        run_output_dir=run_output_dir,
        weights_dir=os.path.dirname(os.path.abspath(script_file)),  # unused for dense microbench
        node_limit=node_limit,
        mesh_size=mesh_size,
        layers=layers,
        mesh=mesh_cfg,
        flags=flags_cfg,
        mem_layout=mem_layout_cfg,
        gas=gas_cfg,
        step=step_cfg,
        routing=routing_cfg,
        debug=debug_cfg,
        loader=loader_cfg,
        global_step_ctrl=global_step_ctrl,
        spike_source_enabled=False,
        spike_data_files=[],
        debug_conn=False,
        overrides=overrides,
    )

    sst_module.setProgramOption("timebase", "1ps")
    if max_steps <= 0:
        sst_module.setProgramOption("stop-at", simulation_time)

    print(
        f"[dense-microbench] exec_mode={exec_mode} mesh_size={mesh_size} node_limit={node_limit} "
        f"cores={num_cores_per_pe} neurons_per_core={neurons_per_core} cols={global_weights_cols} "
        f"dense_bytes_per_core={dense_bytes} stride=0x{per_core_weight_stride:x} max_steps={max_steps}"
    )
    print(f"[dense-microbench] start (simulation_time={simulation_time})")

    return {
        "config": {
            "exec_mode": exec_mode,
            "mesh_size": mesh_size,
            "node_limit": node_limit,
            "num_cores_per_pe": num_cores_per_pe,
            "neurons_per_core": neurons_per_core,
            "global_weights_cols": global_weights_cols,
            "max_steps": max_steps,
            "simulation_time": simulation_time,
            "disable_network": disable_network,
            "l1_enable": l1_enable,
            "step_activation_fraction": frac,
            "step_activation_fanout": fanout,
            "step_activation_seed": seed,
        },
        "run_output_dir": run_output_dir,
        "built": built,
    }
