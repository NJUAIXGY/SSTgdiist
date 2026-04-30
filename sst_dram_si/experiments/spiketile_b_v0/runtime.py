from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .bcsr import apply_step_activation_bcsr_defaults_from_global_offsets
from .bcsr import resolve_global_bcsr_runtime
from .config import apply_gas_env_overrides
from .config import apply_global_step_sync_env_override
from .config import apply_local_run_config_overrides
from .config import load_local_run_config
from .config import maybe_default_gas_merge_policy_for_global_step_sync
from .config import maybe_default_gas_window_cycles_for_global_step_sync
from .legacy_defaults import DEFAULT_STATS_LEVEL
from .legacy_defaults import make_default_state
from .paths import prepare_run_output_and_stats
from .spec import load_spec
from .spec import resolve_spec
from .stats import enable_default_statistics
from .step import build_step_cfg
from .task_snn import build_layers_cfg
from .task_snn import print_classification_banner
from .task_snn import resolve_default_classification_task
from .task_snn import resolve_fixed_4x4_layers
from .utils import mesh_print
from .utils import parse_time_to_ns

# NOTE: build.py imports sst internally; runtime keeps sst interactions
# limited to statistics setup and program options via sst_module passed in.
from .build import build_global_gas_step_controller
from .build import load_spike_data_files


@dataclass(frozen=True)
class MeshRuntime:
    analysis_dir: str
    run_output_dir: str
    artifacts: Dict[str, str]
    script_dir: str
    weights_dir: str

    mesh_size: int
    node_limit: int

    simulation_time: str
    sim_stop_ns: int

    exec_mode: str
    max_steps: int

    global_step_ctrl: Optional[Any]

    spike_source_enabled: bool
    spike_data_files: List[str]
    debug_conn: bool

    layers_cfg: Dict[str, Any]
    mesh_cfg: Dict[str, Any]
    flags_cfg: Dict[str, Any]
    mem_layout_cfg: Dict[str, Any]
    gas_cfg: Dict[str, Any]
    step_cfg: Dict[str, Any]
    routing_cfg: Dict[str, Any]
    debug_cfg: Dict[str, Any]
    loader_cfg: Dict[str, Any]
    overrides: List[Dict[str, Any]]


def _env_stripped(key: str) -> str:
    return (os.environ.get(key) or "").strip()


def _env_bool(key: str, default: bool) -> bool:
    raw = _env_stripped(key).lower()
    if not raw:
        return bool(default)
    if raw in ("1", "true", "yes", "y", "on"):
        return True
    if raw in ("0", "false", "no", "n", "off"):
        return False
    mesh_print(f"[mesh] ignore invalid {key}={raw!r} (expected 0/1/true/false)")
    return bool(default)


def _env_int_with_default(key: str, default: int) -> int:
    raw = _env_stripped(key)
    if not raw:
        return int(default)
    try:
        return int(raw)
    except Exception:
        mesh_print(f"[mesh] ignore invalid {key}={raw!r} (expected int)")
        return int(default)


class _EnvPatch:
    def __init__(self, patch: Dict[str, Optional[str]]):
        self._patch = dict(patch)
        self._saved: Dict[str, Optional[str]] = {}

    def __enter__(self) -> None:
        for k, v in self._patch.items():
            self._saved[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def __exit__(self, exc_type, exc, tb) -> None:
        for k, old in self._saved.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _dump_runtime_config_if_enabled(*, run_dir: str, payload: Dict[str, Any]) -> None:
    raw = os.environ.get("MESH_DUMP_CONFIG", "").strip().lower()
    if raw not in ("1", "true", "yes", "y", "on"):
        return

    try:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        sha = hashlib.sha256(data.encode("utf-8")).hexdigest()
        cfg_path = os.path.join(run_dir, "runtime_config.json")
        sha_path = os.path.join(run_dir, "runtime_config.sha256")
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(data)
            f.write("\n")
        with open(sha_path, "w", encoding="utf-8") as f:
            f.write(sha)
            f.write("\n")
        mesh_print(f"[mesh] runtime config dumped: {cfg_path}")
        mesh_print(f"[mesh] runtime config sha256: {sha}")
    except Exception as e:
        mesh_print(f"[mesh] runtime config dump failed: {e}")


def _resolve_runtime_spec_first(*, sst_module: Any, script_file: str, spec_path: str) -> MeshRuntime:
    """
    Spec-first runtime resolver.

    - Spec JSON is the only modeling input (besides built-in defaults).
    - local_run_config.json is ignored.
    - Env-based modeling overrides are ignored (we also seal known legacy env drift keys).
    """

    script_dir = os.path.dirname(os.path.abspath(script_file))
    weights_dir = os.path.join(script_dir, "weights")

    analysis_dir, run_output_dir, artifacts = prepare_run_output_and_stats(
        sst_module=sst_module,
        script_file=script_file,
        default_stats_level=DEFAULT_STATS_LEVEL,
    )
    enable_default_statistics(sst_module)

    raw = load_spec(spec_path)
    resolved = resolve_spec(raw, defaults_state=make_default_state())
    state: Dict[str, Any] = dict(resolved.get("state") or {})
    overrides: List[Dict[str, Any]] = list(resolved.get("overrides") or [])

    exec_mode = str(state.get("SPEC_EXEC_MODE", "gas") or "gas").strip().lower()
    if exec_mode == "naive_opt":
        exec_mode = "naive_raw"
    if exec_mode not in ("gas", "naive_raw"):
        mesh_print(f"[mesh] unknown spec exec_mode={exec_mode!r}, fallback to 'gas'")
        exec_mode = "gas"

    try:
        max_steps = int(state.get("SPEC_MAX_STEPS", 0) or 0)
    except Exception:
        max_steps = 0
    if max_steps < 0:
        max_steps = 0

    mesh_size = int(state.get("MESH_SIZE", 4))
    num_cores_per_pe = int(state.get("NUM_CORES_PER_PE", 4))
    neurons_per_core = int(state.get("NEURONS_PER_CORE", 4))
    total_nodes = mesh_size * mesh_size

    node_limit = total_nodes
    try:
        nl = int(state.get("SPEC_NODE_LIMIT", 0) or 0)
        if nl > 0:
            node_limit = nl
    except Exception:
        node_limit = total_nodes
    node_limit = max(1, min(node_limit, total_nodes))

    # Seal legacy env override keys that would otherwise drift modeling.
    # TODO(v2): remove env reads from bcsr/build paths and pass these via ResolvedSpec directly.
    with _EnvPatch({"MESH_BCSR_DIR": None, "MESH_BASE_ADDR_SHIFT": None}):
        bcsr_rt = resolve_global_bcsr_runtime(
            weights_dir=weights_dir,
            total_nodes=total_nodes,
            num_cores_per_pe=num_cores_per_pe,
            neurons_per_core=neurons_per_core,
            row_align_bytes=8192,
        )

    global_bcsr_available = bool(bcsr_rt.get("available", False))
    global_bcsr_dir = str(bcsr_rt.get("bcsr_dir", ""))
    global_bcsr_offsets = dict(bcsr_rt.get("offsets", {}) or {})

    neurons_per_pe = num_cores_per_pe * neurons_per_core
    if global_bcsr_available:
        try:
            neurons_per_core = int(bcsr_rt.get("neurons_per_core_override", neurons_per_core))
            neurons_per_pe = num_cores_per_pe * neurons_per_core
        except Exception:
            pass
        apply_step_activation_bcsr_defaults_from_global_offsets(state=state, global_offsets=global_bcsr_offsets)

    # Step BCSR defaults (legacy fallback values)
    if state.get("STEP_ACTIVATION_BCSR_BR") is None:
        state["STEP_ACTIVATION_BCSR_BR"] = 16
    if state.get("STEP_ACTIVATION_BCSR_BC") is None:
        state["STEP_ACTIVATION_BCSR_BC"] = 16
    if state.get("STEP_ACTIVATION_BCSR_IDX_BYTES") is None:
        state["STEP_ACTIVATION_BCSR_IDX_BYTES"] = 2
    if state.get("STEP_ACTIVATION_BCSR_VAL_BYTES") is None:
        state["STEP_ACTIVATION_BCSR_VAL_BYTES"] = 4

    per_core_weight_stride = int(bcsr_rt.get("per_core_weight_stride", 0) or 0)
    pe_weight_region_stride = int(bcsr_rt.get("pe_weight_region_stride", 0) or 0)
    base_addr_global_shift = int(bcsr_rt.get("base_addr_global_shift", 0) or 0)
    aligned_from = bcsr_rt.get("base_addr_aligned_from")
    if aligned_from is not None:
        mesh_print(f"[mesh] align BASE_ADDR_GLOBAL_SHIFT: 0x{int(aligned_from):x} -> 0x{base_addr_global_shift:x}")

    mesh_print(f"[mesh] spec_first=1 spec_path={spec_path!r}")

    simulation_time = str(state.get("SIMULATION_TIME", "200us"))
    sim_stop_ns = 0  # spec-first v1: no env-driven alt-stop.

    global_step_require_all_ready = 1 if int(state.get("SPEC_GLOBAL_STEP_REQUIRE_ALL_READY", 1) or 1) != 0 else 0
    global_step_strict_seq_check = 1 if int(state.get("SPEC_GLOBAL_STEP_STRICT_SEQ_CHECK", 0) or 0) != 0 else 0

    stop_mode = "steps" if max_steps > 0 else "time"
    mesh_print(f"[mesh] stop_mode={stop_mode} max_steps={max_steps} sim_stop_ns={sim_stop_ns} simulation_time={simulation_time}")

    task_layers = resolve_fixed_4x4_layers()
    task = resolve_default_classification_task()
    spec_class_freqs = state.get("SPEC_CLASS_FREQS")
    if isinstance(spec_class_freqs, list) and spec_class_freqs:
        task["class_freqs"] = list(spec_class_freqs)

    input_layer = list(task_layers["input_layer"])
    class_freqs = list(task.get("class_freqs", [40, 80, 120, 200]))
    spike_source_enabled = bool(state.get("ENABLE_SPIKE_SOURCE_FLAG", False))
    spike_data_files: List[str] = []
    if spike_source_enabled:
        spike_data_files = load_spike_data_files(
            script_file=script_file,
            input_layer=input_layer,
            class_freqs=class_freqs,
        )

    print_classification_banner(
        mesh_size=int(mesh_size),
        total_nodes=int(total_nodes),
        layers=task_layers,
        task=task,
    )

    global_step_ctrl = build_global_gas_step_controller(
        enabled=bool(state.get("GLOBAL_STEP_SYNC_ENABLE", False)),
        verbose=int(state.get("GLOBAL_STEP_CTRL_VERBOSE", 0) or 0),
        start_seq=1,
        max_steps=max_steps,
        require_all_ready=int(global_step_require_all_ready),
        strict_seq_check=int(global_step_strict_seq_check),
    )
    if global_step_ctrl is not None:
        mesh_print("[mesh] GLOBAL_STEP_SYNC_ENABLE=1 (barrier mode)")

    window_read_debug = bool(state.get("WINDOW_READ_DEBUG", False))

    multicast_enable = _env_bool(
        "MESH_MULTICAST_ENABLE",
        bool(state.get("SPEC_MULTICAST_ENABLE", False)),
    )
    multicast_block_w = _env_int_with_default(
        "MESH_MULTICAST_BLOCK_W",
        int(state.get("SPEC_MULTICAST_BLOCK_W", 2) or 2),
    )
    multicast_block_h = _env_int_with_default(
        "MESH_MULTICAST_BLOCK_H",
        int(state.get("SPEC_MULTICAST_BLOCK_H", 2) or 2),
    )
    multicast_ingress_policy = _env_stripped("MESH_MULTICAST_INGRESS_POLICY") or str(
        state.get("SPEC_MULTICAST_INGRESS_POLICY", "top_left") or "top_left"
    )
    multicast_inter_policy = _env_stripped("MESH_MULTICAST_INTER_POLICY") or str(
        state.get("SPEC_MULTICAST_INTER_POLICY", "xy") or "xy"
    )
    multicast_intra_policy = _env_stripped("MESH_MULTICAST_INTRA_POLICY") or str(
        state.get("SPEC_MULTICAST_INTRA_POLICY", "manhattan_x_first") or "manhattan_x_first"
    )
    experimental_spiketile_enable = _env_bool(
        "MESH_EXPERIMENTAL_SPIKETILE_ENABLE",
        bool(state.get("SPEC_EXPERIMENTAL_SPIKETILE_ENABLE", False)),
    )
    experimental_spiketile_max_pre_bits = _env_int_with_default(
        "MESH_EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS",
        int(state.get("SPEC_EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS", 64) or 64),
    )
    experimental_spiketile_block_cols = _env_int_with_default(
        "MESH_EXPERIMENTAL_SPIKETILE_BLOCK_COLS",
        int(state.get("SPEC_EXPERIMENTAL_SPIKETILE_BLOCK_COLS", 0) or 0),
    )
    experimental_compact_mask_enable = _env_bool(
        "MESH_EXPERIMENTAL_COMPACT_MASK_ENABLE",
        bool(state.get("SPEC_EXPERIMENTAL_COMPACT_MASK_ENABLE", False)),
    )
    experimental_inter_bundle_enable = _env_bool(
        "MESH_EXPERIMENTAL_INTER_BUNDLE_ENABLE",
        bool(state.get("SPEC_EXPERIMENTAL_INTER_BUNDLE_ENABLE", False)),
    )
    experimental_inter_bundle_max_entries = _env_int_with_default(
        "MESH_EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES",
        int(state.get("SPEC_EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES", 64) or 64),
    )

    layers_cfg = build_layers_cfg(
        layers=task_layers,
        thresholds=state.get("THRESHOLDS"),
        core_tau_mem=float(state.get("CORE_TAU_MEM", 20.0)),
        core_t_ref=int(state.get("CORE_T_REF", 2) or 2),
        init_default_weight=float(state.get("CORE_INIT_DEFAULT_WEIGHT", 0.5) or 0.5),
    )

    gas_cfg = {
        "window_cycles": dict(state.get("_GAS_WINDOW_CYCLES", {"gather": 200, "apply": 40, "scatter": 40})),
        "merge_policy": str(state.get("_GAS_MERGE_POLICY", "auto")),
        "gap_k_bytes": int(state.get("_GAS_GAP_K_BYTES", 2048)),
        "lmax_bytes": int(state.get("_GAS_LMAX_BYTES", 65536)),
        "max_inflight": int(state.get("_GAS_MAX_INFLIGHT", 128)),
        "row_window_bytes": int(state.get("_GAS_ROW_WINDOW_BYTES", 0)),
        "row_window_timeout_ns": int(state.get("_GAS_ROW_WINDOW_TIMEOUT_NS", 0)),
        "sort_policy": str(state.get("_GAS_SORT_POLICY", "row")),
        "row_bytes_guess": int(state.get("_GAS_ROW_BYTES_GUESS", 8192)),
        "bank_bits": int(state.get("_GAS_BANK_BITS", 0)),
        "bank_shift": int(state.get("_GAS_BANK_SHIFT", 0)),
        "bank_auto_enable": int(state.get("_GAS_BANK_AUTO_ENABLE", 1)),
        "apply_issue_policy": str(state.get("_GAS_APPLY_ISSUE_POLICY", "order")),
        "apply_frags_per_issue": int(state.get("_GAS_APPLY_FRAGS_PER_ISSUE", 1)),
        "apply_bank_credit": int(state.get("_GAS_APPLY_BANK_CREDIT", 1)),
        "apply_age_fair_ns": int(state.get("_GAS_APPLY_AGE_FAIR_NS", 2000)),
        # DRAM-aware Apply (exploration; default OFF)
        "dram_row_bytes": int(state.get("_GAS_DRAM_ROW_BYTES", 0)),
        "dram_bank_count": int(state.get("_GAS_DRAM_BANK_COUNT", 0)),
        "dram_read_burst_bytes": int(state.get("_GAS_DRAM_READ_BURST_BYTES", 64)),
        "dram_row_miss_penalty_cycles": int(state.get("_GAS_DRAM_ROW_MISS_PENALTY_CYCLES", 0)),
        "dram_overfetch_budget_bytes": int(state.get("_GAS_DRAM_OVERFETCH_BUDGET_BYTES", 0)),
        "dram_aware_enable_row_window": int(state.get("_GAS_DRAM_AWARE_ENABLE_ROWWIN", 0)),
        "dram_aware_k_policy": str(state.get("_GAS_DRAM_AWARE_K_POLICY", "cost_budgeted")),
    }
    if "SPEC_GAS_GATHER_QUIESCE_CYCLES" in state:
        gas_cfg["gather_quiesce_cycles"] = int(state.get("SPEC_GAS_GATHER_QUIESCE_CYCLES", 0) or 0)
    if "SPEC_GAS_GATHER_MIN_CYCLES" in state:
        gas_cfg["gather_min_cycles"] = int(state.get("SPEC_GAS_GATHER_MIN_CYCLES", 0) or 0)
    if "SPEC_GAS_DENSE_STRICT_CACHELINE" in state:
        gas_cfg["dense_strict_cacheline"] = bool(state.get("SPEC_GAS_DENSE_STRICT_CACHELINE", False))
    if "SPEC_GAS_FORCE_DEFER" in state:
        gas_cfg["force_defer"] = bool(state.get("SPEC_GAS_FORCE_DEFER", False))

    step_cfg = build_step_cfg(
        state=state,
        global_bcsr_available=global_bcsr_available,
        global_bcsr_dir=global_bcsr_dir,
        neurons_per_core=int(neurons_per_core),
    )

    mesh_cfg = {
        "num_cores_per_pe": int(num_cores_per_pe),
        "neurons_per_core": int(neurons_per_core),
        "neurons_per_pe": int(neurons_per_pe),
        "total_nodes": int(total_nodes),
        "global_weights_cols": int(bcsr_rt.get("global_weights_cols", total_nodes * neurons_per_pe)),
        "global_bcsr_available": bool(global_bcsr_available),
        "global_bcsr_dir": str(global_bcsr_dir),
        "global_bcsr_offsets": dict(global_bcsr_offsets),
        "noc_type": str(state.get("SPEC_NOC_TYPE", "merlin_mesh") or "merlin_mesh"),
        "network_bandwidth": str(state.get("NETWORK_BANDWIDTH", "40GiB/s")),
        "buffer_size": str(state.get("BUFFER_SIZE", "8KiB")),
        "router_buffer_size": str(state.get("ROUTER_BUFFER_SIZE", "4KiB") or "4KiB"),
        "mapping_mode": str(state.get("SPEC_MAPPING_MODE", "post") or "post"),
        "core_memory_warmup_cycles": int(state.get("CORE_MEMORY_WARMUP_CYCLES", 200)),
        "core_loader_barrier_cycles": int(state.get("CORE_LOADER_BARRIER_CYCLES", 0)),
        "force_dense": bool(state.get("FORCE_DENSE", False)),
        "verify_routing": int(state.get("VERIFY_ROUTING", 0)),
        "bcsr_layout_mode": str(global_bcsr_offsets.get("layout_mode", "flat") or "flat"),
        "bcsr_colidx_row_stride_bytes": int(global_bcsr_offsets.get("colidx_row_stride_bytes", 0) or 0),
        "bcsr_blockdata_row_stride_bytes": int(global_bcsr_offsets.get("blockdata_row_stride_bytes", 0) or 0),
        "bcsr_blockids_row_stride_bytes": int(global_bcsr_offsets.get("blockids_row_stride_bytes", 0) or 0),
        "bcsr_block_fetch_mode": str(state.get("BCSR_BLOCK_FETCH_MODE", "full_block") or "full_block"),
        "network_num_vns": int(state.get("SPEC_NETWORK_NUM_VNS", 2) or 2),
        "workload_impl": str(state.get("SPEC_WORKLOAD_IMPL", "snn") or "snn"),
        "workload_stats_modules": str(state.get("SPEC_WORKLOAD_STATS_MODULES", "") or ""),
        "multicast_enable": bool(multicast_enable),
        "multicast_block_w": int(multicast_block_w),
        "multicast_block_h": int(multicast_block_h),
        "multicast_ingress_policy": str(multicast_ingress_policy),
        "multicast_inter_policy": str(multicast_inter_policy),
        "multicast_intra_policy": str(multicast_intra_policy),
        "experimental_spiketile_enable": bool(experimental_spiketile_enable),
        "experimental_spiketile_max_pre_bits": int(experimental_spiketile_max_pre_bits),
        "experimental_spiketile_block_cols": int(experimental_spiketile_block_cols),
        "experimental_compact_mask_enable": bool(experimental_compact_mask_enable),
        "experimental_inter_bundle_enable": bool(experimental_inter_bundle_enable),
        "experimental_inter_bundle_max_entries": int(experimental_inter_bundle_max_entries),
    }

    flags_cfg = {
        "disable_network": bool(state.get("DISABLE_NETWORK", False)),
        "export_spike_csv": bool(state.get("EXPORT_SPIKE_CSV", False)),
        "spikes_mesh_csv": str(artifacts["spikes_mesh_csv"]),
        "enable_node_summary": bool(state.get("ENABLE_NODE_SUMMARY", False)),
        "enable_test_traffic": bool(state.get("ENABLE_TEST_TRAFFIC", False)),
        "event_fallback": False,
        "diag_fire_log": bool(state.get("DIAG_FIRE_LOG", False)),
        "global_step_sync_enable": bool(state.get("GLOBAL_STEP_SYNC_ENABLE", False)),
        "exec_mode": str(exec_mode),
        "max_steps": int(max_steps),
        "sim_stop_ns": int(sim_stop_ns),
        "record_edge_apply_enable": int(state.get("RECORD_EDGE_APPLY_ENABLE", 1)),
        "record_edge_idle_enable": int(state.get("RECORD_EDGE_IDLE_ENABLE", 1)),
        "record_edge_scatter_enable": int(state.get("RECORD_EDGE_SCATTER_ENABLE", 1)),
        "use_soa_state": int(state.get("USE_SOA_STATE", 0)),
        "use_aosoa_state": int(state.get("USE_AOSOA_STATE", 0)),
        "aosoa_block_rows": int(state.get("AOSOA_BLOCK_ROWS", 16)),
        "verify_cluster_enable": int(state.get("VERIFY_CLUSTER_ENABLE", 0)),
    }
    flags_cfg["minimal_core_params"] = bool(state.get("SPEC_MINIMAL_CORE_PARAMS", False))
    flags_cfg["readonly_freeze_enable"] = bool(state.get("SPEC_READONLY_FREEZE_ENABLE", False))
    flags_cfg["readonly_v_thresh"] = float(state.get("SPEC_READONLY_V_THRESH", 1.0e9))
    flags_cfg["readonly_tau_mem"] = float(state.get("SPEC_READONLY_TAU_MEM", 0.001))
    flags_cfg["apply_dense_acc_enable"] = bool(state.get("SPEC_APPLY_DENSE_ACC_ENABLE", True))
    flags_cfg["acc_shadow_verify_enable"] = bool(state.get("SPEC_ACC_SHADOW_VERIFY_ENABLE", False))
    if "SPEC_GAS_STEP_SEQ_GATE_ENABLE" in state:
        flags_cfg["gas_step_seq_gate_enable"] = bool(state.get("SPEC_GAS_STEP_SEQ_GATE_ENABLE", False))
    if "SPEC_GLOBAL_STEP_DONE_POLICY" in state:
        flags_cfg["global_step_done_policy"] = str(state.get("SPEC_GLOBAL_STEP_DONE_POLICY", ""))
    if "SPEC_GLOBAL_STEP_DRAIN_MIN_CYCLES" in state:
        flags_cfg["global_step_drain_min_cycles"] = int(state.get("SPEC_GLOBAL_STEP_DRAIN_MIN_CYCLES", 0) or 0)
    if "SPEC_GLOBAL_STEP_QUIESCENT_MIN_CYCLES" in state:
        flags_cfg["global_step_quiescent_min_cycles"] = int(state.get("SPEC_GLOBAL_STEP_QUIESCENT_MIN_CYCLES", 0) or 0)
    if "SPEC_GLOBAL_STEP_FIXED_CYCLES" in state:
        flags_cfg["global_step_fixed_cycles"] = int(state.get("SPEC_GLOBAL_STEP_FIXED_CYCLES", 0) or 0)
    if "SPEC_GLOBAL_STEP_READY_DELAY_CYCLES" in state:
        flags_cfg["global_step_ready_delay_cycles"] = int(state.get("SPEC_GLOBAL_STEP_READY_DELAY_CYCLES", 0) or 0)

    mem_layout_cfg = {
        "per_core_weight_stride": int(per_core_weight_stride),
        "pe_weight_region_stride": int(pe_weight_region_stride),
        "base_addr_global_shift": int(base_addr_global_shift),
        "l1_enable": bool(state.get("L1_ENABLE", False)),
        "l1_size_str": str(state.get("L1_SIZE_STR", "16KiB")),
        "l1_assoc": int(state.get("L1_ASSOC", 8)),
        "l1_line_bytes_str": str(state.get("L1_LINE_BYTES_STR", "64")),
        "subcomp_line_bytes": int(state.get("SUBCOMP_LINE_BYTES", 64)),
        "memory_system": str(state.get("SPEC_MEMORY_SYSTEM", "memhierarchy_per_pe") or "memhierarchy_per_pe"),
        "mem_backend": str(state.get("MEM_BACKEND", "simple") or "simple"),
        "ramulator2_config_file": str(state.get("RAMULATOR2_CONFIG_FILE", "") or ""),
        "simplemem_access_time": str(state.get("SIMPLEMEM_ACCESS_TIME", "100ns") or "100ns"),
    }

    routing_cfg = {
        "mode": str(state.get("ROUTING_MODE", "weight_driven")),
        "epsilon": float(state.get("ROUT_EPS", 0.6)),
        "topk_per_pe": int(state.get("ROUT_TOPK_PER_PE", 2)),
        "topk": int(state.get("ROUT_TOPK", 12)),
    }

    debug_cfg = {
        "sentinel_enable": bool(state.get("SENTINEL_ENABLE", False)),
        "progress_log_interval_ns": int(state.get("PROGRESS_LOG_INTERVAL_NS", 0) or 0),
        "progress_log_node": int(state.get("PROGRESS_LOG_NODE", -1)),
        "window_read_debug": bool(window_read_debug),
        "window_read_debug_all_cores": bool(state.get("WINDOW_READ_DEBUG_ALL", False)),
        "debug_target_pe": int(state.get("DEBUG_TARGET_PE", 0)),
        "debug_target_core": int(state.get("DEBUG_TARGET_CORE", 0)),
        "node_verbose": int(state.get("NODE_VERBOSE", 0) or 0),
        "core_verbose": int(state.get("CORE_VERBOSE", 0)),
        "bcsr_merge_read_verify_enable": bool(state.get("BCSR_MERGE_READ_VERIFY_ENABLE", False)),
        "bcsr_merge_read_verify_sample_bytes": int(state.get("BCSR_MERGE_READ_VERIFY_SAMPLE_BYTES", 64)),
        "bcsr_merge_read_verify_max_resps": int(state.get("BCSR_MERGE_READ_VERIFY_MAX_RESPS", 8)),
        "bcsr_merge_read_verify_target_pe": int(state.get("BCSR_MERGE_READ_VERIFY_TARGET_PE", 0)),
        "bcsr_merge_read_verify_target_core": int(state.get("BCSR_MERGE_READ_VERIFY_TARGET_CORE", 0)),
    }

    loader_cfg = {
        "pe_mem_addr_range": int(pe_weight_region_stride),
        "loader_verbose": int(state.get("LOADER_VERBOSE", 0) or 0),
        "loader_chunk_bytes": int(state.get("LOADER_CHUNK_BYTES", 64)),
        "loader_timed_seed_enable": bool(state.get("LOADER_TIMED_SEED_ENABLE", 0)),
        "loader_timed_seed_allow_cache": bool(state.get("LOADER_TIMED_SEED_ALLOW_CACHE", 0)),
        "loader_verify_readback": bool(state.get("LOADER_VERIFY_READBACK", 0)),
        "loader_verify_bytes": int(state.get("LOADER_VERIFY_BYTES", 64)),
        "loader_verify_colidx_start": int(state.get("LOADER_VERIFY_COLIDX_START", 441)),
        "loader_diag_timed_read": bool(state.get("LOADER_DIAG_TIMED_READ", 0)),
        "loader_diag_timed_read_colidx_start": int(state.get("LOADER_DIAG_TIMED_READ_COLIDX_START", state.get("LOADER_VERIFY_COLIDX_START", 441))),
        "loader_verify_mode": str(state.get("LOADER_VERIFY_MODE", "")),
        "loader_verify_samples": int(state.get("LOADER_VERIFY_SAMPLES", 0) or 0),
        "loader_verify_seed": int(state.get("LOADER_VERIFY_SEED", 0) or 0),
        "loader_write_pattern_mode": str(state.get("LOADER_WRITE_PATTERN_MODE", "")),
        "loader_write_pattern_row_scale": int(state.get("LOADER_WRITE_PATTERN_ROW_SCALE", 1024) or 1024),
    }

    return MeshRuntime(
        analysis_dir=str(analysis_dir),
        run_output_dir=str(run_output_dir),
        artifacts=dict(artifacts),
        script_dir=str(script_dir),
        weights_dir=str(weights_dir),
        mesh_size=int(mesh_size),
        node_limit=int(node_limit),
        simulation_time=str(simulation_time),
        sim_stop_ns=int(sim_stop_ns),
        exec_mode=str(exec_mode),
        max_steps=int(max_steps),
        global_step_ctrl=global_step_ctrl,
        spike_source_enabled=bool(spike_source_enabled),
        spike_data_files=list(spike_data_files),
        debug_conn=bool(state.get("DEBUG_CONN", False)),
        layers_cfg=dict(layers_cfg),
        mesh_cfg=dict(mesh_cfg),
        flags_cfg=dict(flags_cfg),
        mem_layout_cfg=dict(mem_layout_cfg),
        gas_cfg=dict(gas_cfg),
        step_cfg=dict(step_cfg),
        routing_cfg=dict(routing_cfg),
        debug_cfg=dict(debug_cfg),
        loader_cfg=dict(loader_cfg),
        overrides=list(overrides),
    )


def resolve_runtime(*, sst_module: Any, script_file: str) -> MeshRuntime:
    """
    Resolve the full runtime configuration for the mesh template in a fixed order:

    defaults -> GAS env overrides -> local_run_config.json -> GLOBAL_STEP_SYNC env override
    -> BCSR runtime/meta overrides -> derived values -> cfg dicts (frozen).

    All SST components must be created only after this function sets up statistics output.
    """

    spec_path = _env_stripped("MESH_SPEC_JSON")
    if spec_path:
        return _resolve_runtime_spec_first(sst_module=sst_module, script_file=script_file, spec_path=spec_path)

    script_dir = os.path.dirname(os.path.abspath(script_file))
    weights_dir = os.path.join(script_dir, "weights")

    analysis_dir, run_output_dir, artifacts = prepare_run_output_and_stats(
        sst_module=sst_module,
        script_file=script_file,
        default_stats_level=DEFAULT_STATS_LEVEL,
    )
    enable_default_statistics(sst_module)

    state = make_default_state()

    # Execution mode for experiments:
    # - gas: default window/GAS path (GatherBufferIF)
    # - naive_raw: no GAS, spike-arrival issues reads immediately (still allows BCSR format)
    #   NOTE: naive_opt is deprecated (BCSR optimizations are globally disabled in SnnDL).
    exec_mode_raw = os.environ.get("MESH_EXEC_MODE", "").strip().lower()
    exec_mode = exec_mode_raw if exec_mode_raw else "gas"
    if exec_mode == "naive_opt":
        exec_mode = "naive_raw"
    if exec_mode not in ("gas", "naive_raw"):
        mesh_print(f"[mesh] unknown MESH_EXEC_MODE={exec_mode_raw!r}, fallback to 'gas'")
        exec_mode = "gas"

    max_steps_env = os.environ.get("MESH_MAX_STEPS", "").strip()
    try:
        max_steps = int(max_steps_env) if max_steps_env else 0
    except Exception:
        max_steps = 0
    if max_steps < 0:
        max_steps = 0

    def _env_int(name: str, default: int) -> int:
        raw = os.environ.get(name, "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except Exception:
            mesh_print(f"[mesh] ignore invalid {name}={raw!r} (expected int)")
            return default

    # GAS env overrides are evaluated before local_run_config.json; env has priority.
    gas_env_flags = apply_gas_env_overrides(state=state)

    # Weight mode fail-fast (event fallback is explicitly forbidden).
    event_fallback = (
        os.environ.get("MESH_WEIGHT_MODE", "mem").strip().lower()
        in ("event", "event_fallback", "fallback")
    )
    if event_fallback:
        raise RuntimeError("use_event_weight_fallback 已被明确禁止：请保持 MESH_WEIGHT_MODE=mem")

    cfg_path = os.path.join(script_dir, "local_run_config.json")
    cfg: Optional[Dict[str, Any]] = None
    if os.path.exists(cfg_path):
        try:
            cfg = load_local_run_config(cfg_path)
            stats_lvl = apply_local_run_config_overrides(
                cfg,
                state=state,
                script_dir=script_dir,
                default_stats_level=DEFAULT_STATS_LEVEL,
                gas_merge_env_present=bool(gas_env_flags.get("gas_merge_env_present", False)),
                gas_inflight_env_present=bool(gas_env_flags.get("gas_inflight_env_present", False)),
                gas_sort_env_present=bool(gas_env_flags.get("gas_sort_env_present", False)),
                gas_row_bytes_env_present=bool(gas_env_flags.get("gas_row_bytes_env_present", False)),
                gas_bank_env_present=bool(gas_env_flags.get("gas_bank_env_present", False)),
                gas_apply_policy_env_present=bool(gas_env_flags.get("gas_apply_policy_env_present", False)),
                gas_apply_frags_env_present=bool(gas_env_flags.get("gas_apply_frags_env_present", False)),
                gas_apply_credit_env_present=bool(gas_env_flags.get("gas_apply_credit_env_present", False)),
                gas_apply_age_env_present=bool(gas_env_flags.get("gas_apply_age_env_present", False)),
            )
            if stats_lvl is not None:
                try:
                    sst_module.setStatisticLoadLevel(int(stats_lvl))
                except Exception:
                    sst_module.setStatisticLoadLevel(DEFAULT_STATS_LEVEL)
        except Exception as e:
            mesh_print(f"[local_run_config] 读取失败: {e}")
            cfg = None

    # Env override for global step sync has priority over local_run_config.json.
    apply_global_step_sync_env_override(state=state)
    if max_steps > 0 and not bool(state.get("GLOBAL_STEP_SYNC_ENABLE", False)):
        state["GLOBAL_STEP_SYNC_ENABLE"] = True
        mesh_print("[mesh] MESH_MAX_STEPS>0 forces GLOBAL_STEP_SYNC_ENABLE=1")

    # BCSR optimization level (format is fixed; this only gates caching/prefetch/coalesce knobs).
    # NOTE: bcsr_opt_level is kept for backward compatibility in configs/meta, but BCSR optimizations
    # are globally disabled in SnnDL (including inflight coalescing), so this value does not affect
    # behavior anymore. We keep a stable default for provenance only.
    bcsr_opt_default = "index_only" if exec_mode == "naive_raw" else "full"
    bcsr_opt_level = bcsr_opt_default
    if isinstance(cfg, dict):
        try:
            raw = str(cfg.get("bcsr_opt_level", "") or "").strip().lower()
            if raw:
                if raw in ("none", "index_only", "full"):
                    bcsr_opt_level = raw
                else:
                    print(f"[mesh] ignore invalid local_run_config.json bcsr_opt_level={raw!r} (expected none/index_only/full)")
        except Exception:
            pass
    env_bcsr_opt = os.environ.get("MESH_BCSR_OPT_LEVEL", "").strip().lower()
    if env_bcsr_opt:
        if env_bcsr_opt in ("none", "index_only", "full"):
            bcsr_opt_level = env_bcsr_opt
            mesh_print(f"[mesh] note: BCSR opt_level override recorded (ignored by SnnDL): {bcsr_opt_level}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_BCSR_OPT_LEVEL={env_bcsr_opt!r} (expected none/index_only/full)")
    state["BCSR_OPT_LEVEL"] = bcsr_opt_level

    # Step-sync default merge_policy tightening (only when NOT explicitly overridden).
    maybe_default_gas_merge_policy_for_global_step_sync(state=state, cfg=cfg, gas_env_flags=gas_env_flags)
    # Step-sync default window_cycles (load-driven; only when NOT explicitly overridden).
    maybe_default_gas_window_cycles_for_global_step_sync(state=state, cfg=cfg, gas_env_flags=gas_env_flags)

    mesh_size = int(state.get("MESH_SIZE", 4))
    num_cores_per_pe = int(state.get("NUM_CORES_PER_PE", 4))
    neurons_per_core = int(state.get("NEURONS_PER_CORE", 4))
    total_nodes = mesh_size * mesh_size

    # Optional node limit (for debug/minimal repro).
    node_limit_env = os.environ.get("MESH_NODE_LIMIT", "").strip()
    try:
        node_limit = int(node_limit_env) if node_limit_env else total_nodes
    except Exception:
        node_limit = total_nodes
    node_limit = max(1, min(node_limit, total_nodes))

    # Resolve BCSR runtime contract.
    bcsr_rt = resolve_global_bcsr_runtime(
        weights_dir=weights_dir,
        total_nodes=total_nodes,
        num_cores_per_pe=num_cores_per_pe,
        neurons_per_core=neurons_per_core,
        row_align_bytes=8192,
    )
    global_bcsr_available = bool(bcsr_rt.get("available", False))
    global_bcsr_dir = str(bcsr_rt.get("bcsr_dir", ""))
    global_bcsr_offsets = dict(bcsr_rt.get("offsets", {}) or {})

    neurons_per_pe = num_cores_per_pe * neurons_per_core
    if global_bcsr_available:
        try:
            neurons_per_core = int(bcsr_rt.get("neurons_per_core_override", neurons_per_core))
            neurons_per_pe = num_cores_per_pe * neurons_per_core
        except Exception:
            pass
        apply_step_activation_bcsr_defaults_from_global_offsets(state=state, global_offsets=global_bcsr_offsets)

    # Step BCSR defaults (legacy fallback values)
    if state.get("STEP_ACTIVATION_BCSR_BR") is None:
        state["STEP_ACTIVATION_BCSR_BR"] = 16
    if state.get("STEP_ACTIVATION_BCSR_BC") is None:
        state["STEP_ACTIVATION_BCSR_BC"] = 16
    if state.get("STEP_ACTIVATION_BCSR_IDX_BYTES") is None:
        state["STEP_ACTIVATION_BCSR_IDX_BYTES"] = 2
    if state.get("STEP_ACTIVATION_BCSR_VAL_BYTES") is None:
        state["STEP_ACTIVATION_BCSR_VAL_BYTES"] = 4

    per_core_weight_stride = int(bcsr_rt.get("per_core_weight_stride", 0) or 0)
    pe_weight_region_stride = int(bcsr_rt.get("pe_weight_region_stride", 0) or 0)
    base_addr_global_shift = int(bcsr_rt.get("base_addr_global_shift", 0) or 0)
    aligned_from = bcsr_rt.get("base_addr_aligned_from")
    if aligned_from is not None:
        mesh_print(f"[mesh] align BASE_ADDR_GLOBAL_SHIFT: 0x{int(aligned_from):x} -> 0x{base_addr_global_shift:x}")

    mesh_print(f"📁 权重目录: {weights_dir}")
    if global_bcsr_available:
        max_file_size = int(bcsr_rt.get("core_file_size", 0) or 0)
        mesh_print(f"  ✅ 检测到全局BCSR数据: {global_bcsr_dir}")
        mesh_print(
            f"  🧮 BCSR stride: metas={len(bcsr_rt.get('all_meta', []) or [])} "
            f"max_file_size=0x{max_file_size:x} per_core_stride=0x{per_core_weight_stride:x}"
        )
    else:
        mesh_print("  ⚠️ 未检测到全局BCSR数据，仍使用旧的权重文件结构")

    # Simulation time (env has priority over local_run_config.json).
    sim_time_env = os.environ.get("MESH_SIM_TIME", "").strip()
    simulation_time = sim_time_env if sim_time_env else str(state.get("SIMULATION_TIME", "200us"))

    # Optional component-controlled stop (to avoid engine exit conflicts).
    alt_stop = os.environ.get("MESH_ALT_STOP", "").strip()
    sim_stop_ns = parse_time_to_ns(simulation_time) if alt_stop in ("1", "true", "True") else 0
    if max_steps > 0 and sim_stop_ns > 0:
        # step-limited is ended by GlobalGasStepController(max_steps). Avoid introducing a second stop source.
        mesh_print("[mesh] WARN: MESH_MAX_STEPS>0 with MESH_ALT_STOP=1; ignore MESH_ALT_STOP to avoid stop conflicts")
        sim_stop_ns = 0

    # Global step controller strictness/readiness (compat-first defaults).
    global_step_require_all_ready = 1 if _env_int("MESH_GLOBAL_STEP_REQUIRE_ALL_READY", 1) != 0 else 0
    global_step_strict_seq_check = 1 if _env_int("MESH_GLOBAL_STEP_STRICT_SEQ_CHECK", 0) != 0 else 0

    # Print resolved stop mode early (for provenance).
    stop_mode = "steps" if max_steps > 0 else ("alt-stop" if sim_stop_ns > 0 else "time")
    mesh_print(f"[mesh] stop_mode={stop_mode} max_steps={max_steps} sim_stop_ns={sim_stop_ns} simulation_time={simulation_time}")

    # Task (legacy fixed 4x4 partitioning)
    task_layers = resolve_fixed_4x4_layers()
    task = resolve_default_classification_task()
    spec_class_freqs = state.get("SPEC_CLASS_FREQS")
    if isinstance(spec_class_freqs, list) and spec_class_freqs:
        task["class_freqs"] = list(spec_class_freqs)

    input_layer = list(task_layers["input_layer"])
    class_freqs = list(task.get("class_freqs", [40, 80, 120, 200]))
    spike_source_enabled = bool(state.get("ENABLE_SPIKE_SOURCE_FLAG", False))
    spike_data_files: List[str] = []
    if spike_source_enabled:
        spike_data_files = load_spike_data_files(
            script_file=script_file,
            input_layer=input_layer,
            class_freqs=class_freqs,
        )

    mesh_print()
    mesh_print("🔗 使用预先生成的权重文件:")
    mesh_print(f"  权重文件将完全从 {weights_dir} 目录中加载")
    mesh_print("  每个PE有独立的权重文件: classification_weights_pe_{0-15}.bin")

    print_classification_banner(
        mesh_size=int(mesh_size),
        total_nodes=int(total_nodes),
        layers=task_layers,
        task=task,
    )

    # Global step controller component (optional; created before node build).
    global_step_ctrl = build_global_gas_step_controller(
        enabled=bool(state.get("GLOBAL_STEP_SYNC_ENABLE", False)),
        verbose=int(state.get("GLOBAL_STEP_CTRL_VERBOSE", 0) or 0),
        start_seq=1,
        max_steps=max_steps,
        require_all_ready=int(global_step_require_all_ready),
        strict_seq_check=int(global_step_strict_seq_check),
    )
    if global_step_ctrl is not None:
        mesh_print("[mesh] GLOBAL_STEP_SYNC_ENABLE=1 (barrier mode)")

    # local cfg-only switch for window-read debug
    window_read_debug = bool(cfg.get("window_read_debug", 0)) if isinstance(cfg, dict) else False

    multicast_enable = _env_bool("MESH_MULTICAST_ENABLE", False)
    multicast_block_w = _env_int_with_default("MESH_MULTICAST_BLOCK_W", 2)
    multicast_block_h = _env_int_with_default("MESH_MULTICAST_BLOCK_H", 2)
    multicast_ingress_policy = _env_stripped("MESH_MULTICAST_INGRESS_POLICY") or "top_left"
    multicast_inter_policy = _env_stripped("MESH_MULTICAST_INTER_POLICY") or "xy"
    multicast_intra_policy = _env_stripped("MESH_MULTICAST_INTRA_POLICY") or "manhattan_x_first"
    experimental_spiketile_enable = _env_bool("MESH_EXPERIMENTAL_SPIKETILE_ENABLE", False)
    experimental_spikekey_fastpath_enable = _env_bool("MESH_EXPERIMENTAL_SPIKEKEY_FASTPATH_ENABLE", False)
    experimental_spiketile_max_pre_bits = _env_int_with_default("MESH_EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS", 64)
    experimental_spiketile_block_cols = _env_int_with_default("MESH_EXPERIMENTAL_SPIKETILE_BLOCK_COLS", 0)
    experimental_compact_mask_enable = _env_bool("MESH_EXPERIMENTAL_COMPACT_MASK_ENABLE", False)
    experimental_inter_bundle_enable = _env_bool("MESH_EXPERIMENTAL_INTER_BUNDLE_ENABLE", False)
    experimental_inter_bundle_max_entries = _env_int_with_default("MESH_EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES", 64)

    # Build cfg dicts (final frozen config)
    layers_cfg = build_layers_cfg(
        layers=task_layers,
        thresholds=state.get("THRESHOLDS"),
        core_tau_mem=float(state.get("CORE_TAU_MEM", 20.0)),
        core_t_ref=int(state.get("CORE_T_REF", 2) or 2),
        init_default_weight=float(state.get("CORE_INIT_DEFAULT_WEIGHT", 0.5) or 0.5),
    )

    gas_cfg = {
        "window_cycles": dict(state.get("_GAS_WINDOW_CYCLES", {"gather": 200, "apply": 40, "scatter": 40})),
        "merge_policy": str(state.get("_GAS_MERGE_POLICY", "auto")),
        "gap_k_bytes": int(state.get("_GAS_GAP_K_BYTES", 2048)),
        "lmax_bytes": int(state.get("_GAS_LMAX_BYTES", 65536)),
        "max_inflight": int(state.get("_GAS_MAX_INFLIGHT", 128)),
        "row_window_bytes": int(state.get("_GAS_ROW_WINDOW_BYTES", 0)),
        "row_window_timeout_ns": int(state.get("_GAS_ROW_WINDOW_TIMEOUT_NS", 0)),
        "apply_issue_policy": str(state.get("_GAS_APPLY_ISSUE_POLICY", "order")),
        "apply_frags_per_issue": int(state.get("_GAS_APPLY_FRAGS_PER_ISSUE", 1)),
        "apply_bank_credit": int(state.get("_GAS_APPLY_BANK_CREDIT", 1)),
        "apply_age_fair_ns": int(state.get("_GAS_APPLY_AGE_FAIR_NS", 2000)),
    }

    step_cfg = build_step_cfg(
        state=state,
        global_bcsr_available=global_bcsr_available,
        global_bcsr_dir=global_bcsr_dir,
        neurons_per_core=int(neurons_per_core),
    )

    mesh_cfg = {
        "num_cores_per_pe": int(num_cores_per_pe),
        "neurons_per_core": int(neurons_per_core),
        "neurons_per_pe": int(neurons_per_pe),
        "total_nodes": int(total_nodes),
        "global_weights_cols": int(bcsr_rt.get("global_weights_cols", total_nodes * neurons_per_pe)),
        "global_bcsr_available": bool(global_bcsr_available),
        "global_bcsr_dir": str(global_bcsr_dir),
        "global_bcsr_offsets": dict(global_bcsr_offsets),
        "noc_type": str(state.get("SPEC_NOC_TYPE", "merlin_mesh") or "merlin_mesh"),
        "network_bandwidth": str(state.get("NETWORK_BANDWIDTH", "40GiB/s")),
        "buffer_size": str(state.get("BUFFER_SIZE", "8KiB")),
        "router_buffer_size": str(state.get("ROUTER_BUFFER_SIZE", "4KiB") or "4KiB"),
        "core_memory_warmup_cycles": int(state.get("CORE_MEMORY_WARMUP_CYCLES", 200)),
        "core_loader_barrier_cycles": int(state.get("CORE_LOADER_BARRIER_CYCLES", 0)),
        "force_dense": bool(state.get("FORCE_DENSE", False)),
        "verify_routing": int(state.get("VERIFY_ROUTING", 0)),
        "bcsr_opt_level": str(state.get("BCSR_OPT_LEVEL", bcsr_opt_default)),
        "bcsr_layout_mode": str(global_bcsr_offsets.get("layout_mode", "flat") or "flat"),
        "bcsr_colidx_row_stride_bytes": int(global_bcsr_offsets.get("colidx_row_stride_bytes", 0) or 0),
        "bcsr_blockdata_row_stride_bytes": int(global_bcsr_offsets.get("blockdata_row_stride_bytes", 0) or 0),
        "bcsr_blockids_row_stride_bytes": int(global_bcsr_offsets.get("blockids_row_stride_bytes", 0) or 0),
        "bcsr_block_fetch_mode": str(state.get("BCSR_BLOCK_FETCH_MODE", "full_block") or "full_block"),
        "multicast_enable": bool(multicast_enable),
        "multicast_block_w": int(multicast_block_w),
        "multicast_block_h": int(multicast_block_h),
        "multicast_ingress_policy": str(multicast_ingress_policy),
        "multicast_inter_policy": str(multicast_inter_policy),
        "multicast_intra_policy": str(multicast_intra_policy),
        "experimental_spiketile_enable": bool(experimental_spiketile_enable),
        "experimental_spikekey_fastpath_enable": bool(experimental_spikekey_fastpath_enable),
        "experimental_spiketile_max_pre_bits": int(experimental_spiketile_max_pre_bits),
        "experimental_spiketile_block_cols": int(experimental_spiketile_block_cols),
        "experimental_compact_mask_enable": bool(experimental_compact_mask_enable),
        "experimental_inter_bundle_enable": bool(experimental_inter_bundle_enable),
        "experimental_inter_bundle_max_entries": int(experimental_inter_bundle_max_entries),
    }
    if "SPEC_MAPPING_MODE" in state:
        mesh_cfg["mapping_mode"] = str(state.get("SPEC_MAPPING_MODE", "post") or "post")

    flags_cfg = {
        "disable_network": bool(state.get("DISABLE_NETWORK", False)),
        "export_spike_csv": bool(state.get("EXPORT_SPIKE_CSV", False)),
        "spikes_mesh_csv": str(artifacts["spikes_mesh_csv"]),
        "enable_node_summary": bool(state.get("ENABLE_NODE_SUMMARY", False)),
        "enable_test_traffic": bool(state.get("ENABLE_TEST_TRAFFIC", False)),
        "event_fallback": False,
        "diag_fire_log": bool(state.get("DIAG_FIRE_LOG", False)),
        "global_step_sync_enable": bool(state.get("GLOBAL_STEP_SYNC_ENABLE", False)),
        "exec_mode": str(exec_mode),
        "max_steps": int(max_steps),
        "sim_stop_ns": int(sim_stop_ns),
        "record_edge_apply_enable": int(state.get("RECORD_EDGE_APPLY_ENABLE", 1)),
        "record_edge_idle_enable": int(state.get("RECORD_EDGE_IDLE_ENABLE", 1)),
        "record_edge_scatter_enable": int(state.get("RECORD_EDGE_SCATTER_ENABLE", 1)),
        "use_soa_state": int(state.get("USE_SOA_STATE", 0)),
        "use_aosoa_state": int(state.get("USE_AOSOA_STATE", 0)),
        "aosoa_block_rows": int(state.get("AOSOA_BLOCK_ROWS", 16)),
        "verify_cluster_enable": int(state.get("VERIFY_CLUSTER_ENABLE", 0)),
    }
    if "SPEC_MINIMAL_CORE_PARAMS" in state:
        flags_cfg["minimal_core_params"] = bool(state.get("SPEC_MINIMAL_CORE_PARAMS", False))
    if "SPEC_READONLY_FREEZE_ENABLE" in state:
        flags_cfg["readonly_freeze_enable"] = bool(state.get("SPEC_READONLY_FREEZE_ENABLE", False))
    if "SPEC_READONLY_V_THRESH" in state:
        flags_cfg["readonly_v_thresh"] = float(state.get("SPEC_READONLY_V_THRESH", 1.0e9))
    if "SPEC_READONLY_TAU_MEM" in state:
        flags_cfg["readonly_tau_mem"] = float(state.get("SPEC_READONLY_TAU_MEM", 0.001))
    if "SPEC_APPLY_DENSE_ACC_ENABLE" in state:
        flags_cfg["apply_dense_acc_enable"] = bool(state.get("SPEC_APPLY_DENSE_ACC_ENABLE", True))
    if "SPEC_ACC_SHADOW_VERIFY_ENABLE" in state:
        flags_cfg["acc_shadow_verify_enable"] = bool(state.get("SPEC_ACC_SHADOW_VERIFY_ENABLE", False))

    mem_layout_cfg = {
        "per_core_weight_stride": int(per_core_weight_stride),
        "pe_weight_region_stride": int(pe_weight_region_stride),
        "base_addr_global_shift": int(base_addr_global_shift),
        "l1_enable": bool(state.get("L1_ENABLE", False)),
        "l1_size_str": str(state.get("L1_SIZE_STR", "16KiB")),
        "l1_assoc": int(state.get("L1_ASSOC", 8)),
        "l1_line_bytes_str": str(state.get("L1_LINE_BYTES_STR", "64")),
        "subcomp_line_bytes": int(state.get("SUBCOMP_LINE_BYTES", 64)),
        "memory_system": str(state.get("SPEC_MEMORY_SYSTEM", "memhierarchy_per_pe") or "memhierarchy_per_pe"),
        # MemController backend (simpleMem vs ramulator2)
        "mem_backend": str(state.get("MEM_BACKEND", "simple") or "simple"),
        "ramulator2_config_file": str(state.get("RAMULATOR2_CONFIG_FILE", "") or ""),
        "simplemem_access_time": str(state.get("SIMPLEMEM_ACCESS_TIME", "100ns") or "100ns"),
    }

    routing_cfg = {
        "mode": str(state.get("ROUTING_MODE", "weight_driven")),
        "epsilon": float(state.get("ROUT_EPS", 0.6)),
        "topk_per_pe": int(state.get("ROUT_TOPK_PER_PE", 2)),
        "topk": int(state.get("ROUT_TOPK", 12)),
    }

    debug_cfg = {
        "sentinel_enable": bool(state.get("SENTINEL_ENABLE", False)),
        "progress_log_interval_ns": int(state.get("PROGRESS_LOG_INTERVAL_NS", 0) or 0),
        "progress_log_node": int(state.get("PROGRESS_LOG_NODE", -1)),
        "window_read_debug": bool(window_read_debug),
        "window_read_debug_all_cores": bool(state.get("WINDOW_READ_DEBUG_ALL", False)),
        "debug_target_pe": int(state.get("DEBUG_TARGET_PE", 0)),
        "debug_target_core": int(state.get("DEBUG_TARGET_CORE", 0)),
        "node_verbose": int(state.get("NODE_VERBOSE", 0) or 0),
        "core_verbose": int(state.get("CORE_VERBOSE", 0)),
        # BCSR merge-read byte-exact correctness (GAS merge validation; optional).
        "bcsr_merge_read_verify_enable": bool(cfg.get("bcsr_merge_read_verify_enable", 0)) if isinstance(cfg, dict) else False,
        "bcsr_merge_read_verify_sample_bytes": int(cfg.get("bcsr_merge_read_verify_sample_bytes", 64)) if isinstance(cfg, dict) else 64,
        "bcsr_merge_read_verify_max_resps": int(cfg.get("bcsr_merge_read_verify_max_resps", 8)) if isinstance(cfg, dict) else 8,
        "bcsr_merge_read_verify_target_pe": int(cfg.get("bcsr_merge_read_verify_target_pe", 0)) if isinstance(cfg, dict) else 0,
        "bcsr_merge_read_verify_target_core": int(cfg.get("bcsr_merge_read_verify_target_core", 0)) if isinstance(cfg, dict) else 0,
    }

    loader_cfg = {
        "pe_mem_addr_range": int(pe_weight_region_stride),
        "loader_verbose": int(state.get("LOADER_VERBOSE", 0) or 0),
        "loader_chunk_bytes": int(state.get("LOADER_CHUNK_BYTES", 64)),
        "loader_timed_seed_enable": bool(state.get("LOADER_TIMED_SEED_ENABLE", 0)),
        "loader_timed_seed_allow_cache": bool(state.get("LOADER_TIMED_SEED_ALLOW_CACHE", 0)),
        "loader_verify_readback": bool(state.get("LOADER_VERIFY_READBACK", 0)),
        "loader_verify_bytes": int(state.get("LOADER_VERIFY_BYTES", 64)),
        "loader_verify_colidx_start": int(state.get("LOADER_VERIFY_COLIDX_START", 441)),
        "loader_diag_timed_read": bool(state.get("LOADER_DIAG_TIMED_READ", 0)),
        "loader_diag_timed_read_colidx_start": int(state.get("LOADER_DIAG_TIMED_READ_COLIDX_START", state.get("LOADER_VERIFY_COLIDX_START", 441))),
        "loader_verify_mode": str(state.get("LOADER_VERIFY_MODE", "")),
        "loader_verify_samples": int(state.get("LOADER_VERIFY_SAMPLES", 0) or 0),
        "loader_verify_seed": int(state.get("LOADER_VERIFY_SEED", 0) or 0),
        "loader_write_pattern_mode": str(state.get("LOADER_WRITE_PATTERN_MODE", "")),
        "loader_write_pattern_row_scale": int(state.get("LOADER_WRITE_PATTERN_ROW_SCALE", 1024) or 1024),
    }

    # Optional config snapshot/hash for drift prevention during refactors.
    _dump_runtime_config_if_enabled(
        run_dir=run_output_dir,
        payload={
            "mesh_size": mesh_size,
            "node_limit": node_limit,
            "simulation_time": simulation_time,
            "sim_stop_ns": sim_stop_ns,
            "exec_mode": exec_mode,
            "max_steps": max_steps,
            "weights_dir": weights_dir,
            "global_bcsr_available": global_bcsr_available,
            "global_bcsr_dir": global_bcsr_dir,
            "bcsr_opt_level": str(state.get("BCSR_OPT_LEVEL", bcsr_opt_default)),
            "gas_env_flags": gas_env_flags,
            "local_run_config_present": bool(cfg is not None),
            "local_run_config": (cfg if isinstance(cfg, dict) else None),
            "layers_cfg": layers_cfg,
            "mesh_cfg": mesh_cfg,
            "flags_cfg": flags_cfg,
            "mem_layout_cfg": mem_layout_cfg,
            "gas_cfg": gas_cfg,
            "step_cfg": step_cfg,
            "routing_cfg": routing_cfg,
            "debug_cfg": debug_cfg,
            "loader_cfg": loader_cfg,
        },
    )

    return MeshRuntime(
        analysis_dir=str(analysis_dir),
        run_output_dir=str(run_output_dir),
        artifacts=dict(artifacts),
        script_dir=str(script_dir),
        weights_dir=str(weights_dir),
        mesh_size=int(mesh_size),
        node_limit=int(node_limit),
        simulation_time=str(simulation_time),
        sim_stop_ns=int(sim_stop_ns),
        exec_mode=str(exec_mode),
        max_steps=int(max_steps),
        global_step_ctrl=global_step_ctrl,
        spike_source_enabled=bool(spike_source_enabled),
        spike_data_files=list(spike_data_files),
        debug_conn=bool(state.get("DEBUG_CONN", False)),
        layers_cfg=dict(layers_cfg),
        mesh_cfg=dict(mesh_cfg),
        flags_cfg=dict(flags_cfg),
        mem_layout_cfg=dict(mem_layout_cfg),
        gas_cfg=dict(gas_cfg),
        step_cfg=dict(step_cfg),
        routing_cfg=dict(routing_cfg),
        debug_cfg=dict(debug_cfg),
        loader_cfg=dict(loader_cfg),
        overrides=[],
    )
