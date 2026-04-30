from __future__ import annotations

from typing import Any, Dict


DEFAULT_STATS_LEVEL = 7


def make_default_state() -> Dict[str, Any]:
    """
    Single source of truth for the legacy mesh template defaults.

    Note: This is the *baseline* state before applying env/local_run_config/BCSR meta
    overrides and computing derived values.
    """

    return {
        # GAS defaults (used by apply_gas_env_overrides)
        # Default to strict cacheline semantics (no gap fill) to avoid overfetch.
        "_GAS_GAP_K_BYTES": 0,
        "_GAS_LMAX_BYTES": 65536,
        "_GAS_MAX_INFLIGHT": 128,
        "_GAS_ROW_WINDOW_BYTES": 0,
        "_GAS_ROW_WINDOW_TIMEOUT_NS": 0,
        "_GAS_MERGE_POLICY": "cacheline",
        # GAS ordering/bucketing defaults (mesh_template/build.py consumes via runtime.py gas_cfg).
        # Keep legacy behavior: order by (rowIndex=addr/8192) only; bank_row is opt-in.
        "_GAS_SORT_POLICY": "row",
        "_GAS_ROW_BYTES_GUESS": 8192,
        "_GAS_BANK_BITS": 0,
        "_GAS_BANK_SHIFT": 0,
        "_GAS_BANK_AUTO_ENABLE": 1,
        # Apply-stage issue scheduling (optional; default preserves legacy "order")
        "_GAS_APPLY_ISSUE_POLICY": "order",  # order|bank_rr_row_sticky_age
        "_GAS_APPLY_FRAGS_PER_ISSUE": 1,  # 0=unlimited
        "_GAS_APPLY_BANK_CREDIT": 1,  # 0=unlimited
        "_GAS_APPLY_AGE_FAIR_NS": 2000,  # 0=disable
        # DRAM-aware Apply (exploration; default OFF)
        "_GAS_DRAM_ROW_BYTES": 0,
        "_GAS_DRAM_BANK_COUNT": 0,
        "_GAS_DRAM_READ_BURST_BYTES": 64,
        "_GAS_DRAM_ROW_MISS_PENALTY_CYCLES": 0,
        "_GAS_DRAM_OVERFETCH_BUDGET_BYTES": 0,
        "_GAS_DRAM_AWARE_ENABLE_ROWWIN": 0,
        "_GAS_DRAM_AWARE_K_POLICY": "cost_budgeted",
        "_GAS_WINDOW_CYCLES": {
            "gather": 200,
            "apply": 40,
            "scatter": 40,
        },
        # Local run config / general toggles
        "SINGLE_BUS_MODE": True,
        "DEBUG_CONN": False,
        "USE_SOA_STATE": 0,
        "USE_AOSOA_STATE": 0,
        "AOSOA_BLOCK_ROWS": 16,
        "CORE_MEMORY_WARMUP_CYCLES": 200,
        "CORE_LOADER_BARRIER_CYCLES": 0,
        "VERIFY_ROUTING": 0,
        "ENABLE_NODE_SUMMARY": False,
        "ENABLE_SPIKE_SOURCE_FLAG": False,
        "ENABLE_TEST_TRAFFIC": False,
        "EXPORT_SPIKE_CSV": False,
        "DISABLE_NETWORK": False,
        "RECORD_EDGE_APPLY_ENABLE": 1,
        "RECORD_EDGE_IDLE_ENABLE": 1,
        "RECORD_EDGE_SCATTER_ENABLE": 1,
        # Step activation defaults
        "STEP_RANDOM_ACT_ENABLE": 1,
        "STEP_ACTIVATION_FRACTION": 2e-4,
        "STEP_ACTIVATION_FANOUT": 256,
        "STEP_ACTIVATION_SEED": 271828,
        "STEP_ACTIVATION_EVENT_WEIGHT": 0.0,
        "STEP_ACTIVATION_PERIOD_CYCLES": 0,
        "STEP_ACTIVATION_TRIGGER_CORE": 0,
        "STEP_ACTIVATION_PRE_PATTERN": "bernoulli",
        "STEP_ACTIVATION_PRE_CLUSTER_LEN": 0,
        "STEP_ACTIVATION_USE_BCSR_ROUTES": 1,
        "STEP_RESET_MEM_EACH_STEP": 0,
        "STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE": "",
        "STEP_ACTIVATION_BCSR_WEIGHT_EPS": 0.0,
        "STEP_ACTIVATION_BCSR_ROWPTR_OFFSET": None,
        "STEP_ACTIVATION_BCSR_COLIDX_OFFSET": None,
        "STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET": None,
        "STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET": None,
        "STEP_ACTIVATION_BCSR_BR": None,
        "STEP_ACTIVATION_BCSR_BC": None,
        "STEP_ACTIVATION_BCSR_IDX_BYTES": None,
        "STEP_ACTIVATION_BCSR_VAL_BYTES": None,
        # Global step sync defaults
        # 默认启用全局 Step/GAS 同步：与 Step Random Activation 的“每窗一次”语义对齐，避免多 PE/多 core 下窗口节奏抖动导致的非确定性。
        # 如需关闭，可在 local_run_config.json 或 MESH_GLOBAL_STEP_SYNC 显式覆盖。
        "GLOBAL_STEP_SYNC_ENABLE": True,
        "GLOBAL_STEP_CTRL_VERBOSE": 0,
        # Synapse/route knobs
        "SYNAPSE_FORMAT_ENV": "",
        "FORCE_DENSE": False,
        "AUTO_BCSR_DETECT": False,
        "ROUT_EPS": 0.6,
        "ROUT_TOPK_PER_PE": 2,
        "ROUT_TOPK": 12,
        "ROUTING_MODE": "weight_driven",
        # Diagnostics
        "DIAG_FIRE_LOG": False,
        "SENTINEL_ENABLE": False,
        "PROGRESS_LOG_INTERVAL_NS": 0,
        "PROGRESS_LOG_NODE": -1,
        "WINDOW_READ_DEBUG_ALL": False,
        "DEBUG_TARGET_PE": 0,
        "DEBUG_TARGET_CORE": 0,
        "CORE_VERBOSE": 2,
        "NODE_VERBOSE": 0,
        # Optional verify/read knobs
        "VERIFY_READS_ENABLE": 0,
        "VERIFY_CLUSTER_ENABLE": 0,
        "LOADER_TIMED_SEED_ENABLE": 0,
        "LOADER_TIMED_SEED_ALLOW_CACHE": 0,
        # Network & cache defaults
        "NETWORK_BANDWIDTH": "40GiB/s",
        "BUFFER_SIZE": "8KiB",
        "L1_SIZE_STR": "16KiB",
        "L1_ASSOC": 8,
        "L1_LINE_BYTES_STR": "64",
        "SUBCOMP_LINE_BYTES": 64,
        "LOADER_CHUNK_BYTES": 64,
        "L2_SIZE_STR": "128KiB",
        "L1_ENABLE": False,
        # MemController backend selection (mesh_template/build.py)
        # - "simple": memHierarchy.simpleMem (fixed access_time)
        # - "ramulator2": memHierarchy.ramulator2 (DRAM timing model via configFile)
        "MEM_BACKEND": "simple",
        "RAMULATOR2_CONFIG_FILE": "",
        "SIMPLEMEM_ACCESS_TIME": "100ns",
        # WeightLoader probe defaults
        "LOADER_VERIFY_READBACK": 0,
        "LOADER_VERIFY_BYTES": 64,
        "LOADER_VERIFY_COLIDX_START": 441,
        "LOADER_DIAG_TIMED_READ": 0,
        "LOADER_DIAG_TIMED_READ_COLIDX_START": 441,
        # Mesh dimensions defaults
        "MESH_SIZE": 4,
        "NUM_CORES_PER_PE": 4,
        "NEURONS_PER_CORE": 4,
        # Task defaults
        "THRESHOLDS": None,
        "CORE_TAU_MEM": 20.0,
        "CORE_T_REF": 2,
        "CORE_INIT_DEFAULT_WEIGHT": 0.5,
        # Simulation time defaults (env/local overrides may replace)
        "SIMULATION_TIME": "200us",
    }
