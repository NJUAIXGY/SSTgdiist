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
        # Experimental: Value-Line Fusion (VLF) for staged segment build (default OFF).
        "_GAS_VLF_ENABLE": 0,
        "_GAS_VLF_RUN_ENABLE": 0,
        # GAS ordering/bucketing defaults (mesh_template/build.py consumes via runtime.py gas_cfg).
        # Keep legacy behavior: order by (rowIndex=addr/8192) only; bank_row is opt-in.
        "_GAS_SORT_POLICY": "row",
        "_GAS_ROW_BYTES_GUESS": 8192,
        "_GAS_BANK_BITS": 0,
        "_GAS_BANK_SHIFT": 0,
        "_GAS_BANK_AUTO_ENABLE": 1,
        # Apply-stage issue scheduling (optional; default preserves legacy "order")
        "_GAS_APPLY_ISSUE_POLICY": "order",
        "_GAS_APPLY_FRAGS_PER_ISSUE": 1,  # 0=unlimited
        "_GAS_APPLY_BANK_CREDIT": 1,  # 0=unlimited
        "_GAS_APPLY_AGE_FAIR_NS": 2000,  # 0=disable
        # Experimental: DRAM command-cost model knobs (default OFF for isolation).
        "_GAS_DRAM_CMD_COST_MERGE_ENABLE": 0,
        "_GAS_DRAM_CMD_T_ROW_HIT_NS": 30,
        "_GAS_DRAM_CMD_T_ROW_MISS_NS": 120,
        "_GAS_DRAM_CMD_T_ROW_HIT_EXPLICIT": 0,
        "_GAS_DRAM_CMD_T_ROW_MISS_EXPLICIT": 0,
        "_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE": 0,
        "_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT": 0,
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
        "SPEC_RISCV_SNN_BACKEND_NAME": "null",
        "SPEC_RISCV_SNN_FIRMWARE_ELF": "",
        "SPEC_RISCV_SNN_HART_ISA": "rv64im_zicsr",
        "SPEC_RISCV_SNN_LOCAL_MEM_BYTES": 64 * 1024,
        "SPEC_RISCV_SNN_CMD_QUEUE_ENTRIES": 64,
        "SPEC_RISCV_SNN_CMP_QUEUE_ENTRIES": 64,
        "SPEC_RISCV_SNN_RX_DEBUG_QUEUE_ENTRIES": 16,
        "SPEC_RISCV_SNN_BOOT_ADDR": 0,
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
        "STEP_SEED_ONLY_MODE": 0,
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
        # Synapse weight path mode (pull-only):
        # - bcsr_gas: baseline BCSR pull on Apply
        "SYNAPSE_WEIGHT_MODE": "bcsr_gas",
        "GCSS_DIR": "",
        "GCSS2_DIR": "",
        "GCSSVLF_DIR": "",
        "GCSS_PHASE_BREAKDOWN_ENABLE": 0,
        "GCSS_VLF_QUEUE_POLICY": "locality_first",
        "GCSS_VLF_FAIR_BAND_SIZE": 256,
        "GCSS_VLF_BOUNDED_RESCUE_ENABLE": 0,
        "GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT": 8,
        "GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES": 64,
        "GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD": 3,
        "PULSE_ENABLE": 0,
        "PULSE_OBSERVE_ONLY": 1,
        "PULSE_INGRESS_ENABLE": 1,
        "PULSE_AGENDA_OBSERVE_ONLY": 1,
        "PULSE_INGRESS_ENTRIES": 0,
        "PULSE_CORE_QUEUE_ENTRIES": 0,
        "PULSE_BYPASS_HIGH_WATERMARK_PCT": 100,
        "PULSE_BYPASS_MODE": "disabled",
        # Offline-first thermal export defaults (HotSpot V1).
        "THERMAL_ENABLE": 0,
        "THERMAL_BACKEND": "hotspot",
        "THERMAL_WINDOW_NS": 1000,
        "THERMAL_WINDOW_TRACE_ENABLE": 0,
        "THERMAL_WINDOW_TRACE_MAX_ROWS": 0,
        "THERMAL_INCLUDE_MEMCTRL": 0,
        "THERMAL_OUT_DIR": "thermal",
        "THERMAL_HOTSPOT_BIN": "",
        "THERMAL_GENERATE_FLOORPLAN": 1,
        "THERMAL_MODEL_TYPE": "block",
        "THERMAL_GRID_ROWS": 64,
        "THERMAL_GRID_COLS": 64,
        "THERMAL_GRID_MAP_MODE": "avg",
        "THERMAL_DETAILED_3D": 0,
        "THERMAL_LAYERS": [],
        "THERMAL_TILE_WIDTH_UM": 1000,
        "THERMAL_TILE_HEIGHT_UM": 1000,
        "THERMAL_TILE_GAP_UM": 50,
        "THERMAL_COMP_FRAC": 0.6,
        "THERMAL_SRAM_FRAC": 0.25,
        "THERMAL_NOC_FRAC": 0.15,
        "LOCAL_STORAGE_ENABLE": 0,
        "PE_INTERNAL_CPE_ENABLE": 0,
        "PE_INTERNAL_POD_ENABLE": 0,
        "PE_INTERNAL_POD_COUNT": 0,
        "PE_INTERNAL_POD_SIZE": 0,
        "PE_INTERNAL_POD_METADATA_ENABLE": 0,
        "PE_INTERNAL_POD_OWNER_ENABLE": 0,
        "PE_INTERNAL_POD_JOIN_ENABLE": 0,
        "PE_INTERNAL_POD_READY_ENABLE": 0,
        "PE_INTERNAL_POD_OWNER_ENTRIES": 0,
        "PE_INTERNAL_POD_JOIN_ENTRIES": 0,
        "PE_INTERNAL_POD_READY_ENTRIES": 0,
        # Observe-only SRAM model (default off; no behavior/stall impact).
        "SRAM_MODEL_ENABLE": 0,
        "SRAM_CALIB_JSON": "",
        "SRAM_CALIB_STRICT": 0,
        "SRAM_WEIGHT_IDX_ENABLE": 0,
        "SRAM_WEIGHT_L0_ENABLE": 0,
        "SRAM_STATE_ENABLE": 0,
        "SRAM_WEIGHT_IDX_CAPACITY_BYTES": 0,
        "SRAM_WEIGHT_L0_CAPACITY_BYTES": 0,
        "SRAM_STATE_CAPACITY_BYTES": 0,
        "SRAM_WEIGHT_IDX_BANKS": 16,
        "SRAM_WEIGHT_L0_BANKS": 8,
        "SRAM_STATE_BANKS": 16,
        "SRAM_WEIGHT_PORTS_PER_BANK": 1,
        "SRAM_STATE_PORTS_PER_BANK": 1,
        "SRAM_WEIGHT_BANK_INTERLEAVE_BYTES": 4,
        "SRAM_STATE_BANK_INTERLEAVE_BYTES": 4,
        "SRAM_WEIGHT_T_READ_CYCLES": 1,
        "SRAM_WEIGHT_T_WRITE_CYCLES": 1,
        "SRAM_STATE_T_READ_CYCLES": 1,
        "SRAM_STATE_T_WRITE_CYCLES": 1,
        "SRAM_WEIGHT_SAMPLE_LOG2": 0,
        "SRAM_STATE_SAMPLE_LOG2": 0,
        "SRAM_WEIGHT_IDX_BASE": 0x100000000,
        "SRAM_WEIGHT_L0_BASE": 0x200000000,
        "SRAM_WEIGHT_L0_SLOTS": 1 << 20,
        "SRAM_STATE_VMEM_BASE": 0x300000000,
        "SRAM_STATE_REFRAC_BASE": 0x400000000,
        "SRAM_STATE_LAST_SPIKE_BASE": 0x500000000,
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
