from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .bcsr import apply_step_activation_bcsr_defaults_from_global_offsets
from .bcsr import resolve_global_bcsr_runtime
from .bcsr import resolve_weight_layout_for_mode
from .config import apply_gas_env_overrides
from .config import apply_global_step_sync_env_override
from .config import apply_local_run_config_overrides
from .config import apply_pulse_env_overrides
from .config import apply_thermal_env_overrides
from .config import load_local_run_config
from .config import maybe_default_gas_merge_policy_for_global_step_sync
from .config import maybe_default_gas_window_cycles_for_global_step_sync
from .config import resolve_input_path_under_project
from .legacy_defaults import DEFAULT_STATS_LEVEL
from .legacy_defaults import make_default_state
from .paths import prepare_run_output_and_stats
from .spec import load_spec
from .spec import resolve_spec
from .stats import enable_default_statistics
from .step import build_step_cfg
from .sram_calib import load_sram_calib_json
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


def _build_sram_cfg(state: Dict[str, Any], *, script_dir: str) -> Dict[str, Any]:
    calib_path = str(state.get("SRAM_CALIB_JSON", "") or "").strip()
    if calib_path and not os.path.isabs(calib_path):
        calib_path = os.path.join(script_dir, calib_path)
    strict = int(state.get("SRAM_CALIB_STRICT", 0) or 0) != 0
    calibrated, calib_meta = load_sram_calib_json(calib_path, strict=strict)

    sram_cfg: Dict[str, Any] = {
        "model_enable": int(state.get("SRAM_MODEL_ENABLE", 0) or 0),
        "calib_json": calib_path,
        "calib_strict": 1 if strict else 0,
        "weight": {
            "idx_enable": int(state.get("SRAM_WEIGHT_IDX_ENABLE", 0) or 0),
            "l0_enable": int(state.get("SRAM_WEIGHT_L0_ENABLE", 0) or 0),
            "idx_capacity_bytes": int(state.get("SRAM_WEIGHT_IDX_CAPACITY_BYTES", 0) or 0),
            "l0_capacity_bytes": int(state.get("SRAM_WEIGHT_L0_CAPACITY_BYTES", 0) or 0),
            "idx_banks": int(state.get("SRAM_WEIGHT_IDX_BANKS", 16) or 16),
            "l0_banks": int(state.get("SRAM_WEIGHT_L0_BANKS", 8) or 8),
            "ports_per_bank": int(state.get("SRAM_WEIGHT_PORTS_PER_BANK", 1) or 1),
            "bank_interleave_bytes": int(state.get("SRAM_WEIGHT_BANK_INTERLEAVE_BYTES", 4) or 4),
            "t_read_cycles": int(state.get("SRAM_WEIGHT_T_READ_CYCLES", 1) or 1),
            "t_write_cycles": int(state.get("SRAM_WEIGHT_T_WRITE_CYCLES", 1) or 1),
            "sample_log2": int(state.get("SRAM_WEIGHT_SAMPLE_LOG2", 0) or 0),
            "idx_base": int(state.get("SRAM_WEIGHT_IDX_BASE", 0x100000000) or 0x100000000),
            "l0_base": int(state.get("SRAM_WEIGHT_L0_BASE", 0x200000000) or 0x200000000),
            "l0_slots": int(state.get("SRAM_WEIGHT_L0_SLOTS", 1 << 20) or (1 << 20)),
        },
        "state": {
            "enable": int(state.get("SRAM_STATE_ENABLE", 0) or 0),
            "capacity_bytes": int(state.get("SRAM_STATE_CAPACITY_BYTES", 0) or 0),
            "banks": int(state.get("SRAM_STATE_BANKS", 16) or 16),
            "ports_per_bank": int(state.get("SRAM_STATE_PORTS_PER_BANK", 1) or 1),
            "bank_interleave_bytes": int(state.get("SRAM_STATE_BANK_INTERLEAVE_BYTES", 4) or 4),
            "t_read_cycles": int(state.get("SRAM_STATE_T_READ_CYCLES", 1) or 1),
            "t_write_cycles": int(state.get("SRAM_STATE_T_WRITE_CYCLES", 1) or 1),
            "sample_log2": int(state.get("SRAM_STATE_SAMPLE_LOG2", 0) or 0),
            "vmem_base": int(state.get("SRAM_STATE_VMEM_BASE", 0x300000000) or 0x300000000),
            "refrac_base": int(state.get("SRAM_STATE_REFRAC_BASE", 0x400000000) or 0x400000000),
            "last_spike_base": int(state.get("SRAM_STATE_LAST_SPIKE_BASE", 0x500000000) or 0x500000000),
        },
        "calib_meta": calib_meta,
    }

    if calibrated:
        widx = (calibrated.get("weight_idx") or {})
        wl0 = (calibrated.get("weight_l0") or {})
        st = (calibrated.get("state") or {})
        lo = (calibrated.get("layout") or {})
        sram_cfg["weight"]["idx_capacity_bytes"] = int(widx.get("capacity_bytes", sram_cfg["weight"]["idx_capacity_bytes"]))
        sram_cfg["weight"]["idx_banks"] = int(widx.get("banks", sram_cfg["weight"]["idx_banks"]))
        sram_cfg["weight"]["ports_per_bank"] = int(widx.get("ports_per_bank", sram_cfg["weight"]["ports_per_bank"]))
        sram_cfg["weight"]["bank_interleave_bytes"] = int(widx.get("bank_interleave_bytes", sram_cfg["weight"]["bank_interleave_bytes"]))
        sram_cfg["weight"]["t_read_cycles"] = int(widx.get("t_read_cycles", sram_cfg["weight"]["t_read_cycles"]))
        sram_cfg["weight"]["t_write_cycles"] = int(widx.get("t_write_cycles", sram_cfg["weight"]["t_write_cycles"]))
        sram_cfg["weight"]["sample_log2"] = int(widx.get("sample_log2", sram_cfg["weight"]["sample_log2"]))

        sram_cfg["weight"]["l0_capacity_bytes"] = int(wl0.get("capacity_bytes", sram_cfg["weight"]["l0_capacity_bytes"]))
        sram_cfg["weight"]["l0_banks"] = int(wl0.get("banks", sram_cfg["weight"]["l0_banks"]))
        sram_cfg["weight"]["ports_per_bank"] = int(wl0.get("ports_per_bank", sram_cfg["weight"]["ports_per_bank"]))
        sram_cfg["weight"]["bank_interleave_bytes"] = int(wl0.get("bank_interleave_bytes", sram_cfg["weight"]["bank_interleave_bytes"]))
        sram_cfg["weight"]["t_read_cycles"] = int(wl0.get("t_read_cycles", sram_cfg["weight"]["t_read_cycles"]))
        sram_cfg["weight"]["t_write_cycles"] = int(wl0.get("t_write_cycles", sram_cfg["weight"]["t_write_cycles"]))
        sram_cfg["weight"]["sample_log2"] = int(wl0.get("sample_log2", sram_cfg["weight"]["sample_log2"]))
        sram_cfg["weight"]["l0_slots"] = int(wl0.get("slots", sram_cfg["weight"]["l0_slots"]))

        sram_cfg["state"]["enable"] = int(st.get("enable", sram_cfg["state"]["enable"]))
        sram_cfg["state"]["capacity_bytes"] = int(st.get("capacity_bytes", sram_cfg["state"]["capacity_bytes"]))
        sram_cfg["state"]["banks"] = int(st.get("banks", sram_cfg["state"]["banks"]))
        sram_cfg["state"]["ports_per_bank"] = int(st.get("ports_per_bank", sram_cfg["state"]["ports_per_bank"]))
        sram_cfg["state"]["bank_interleave_bytes"] = int(st.get("bank_interleave_bytes", sram_cfg["state"]["bank_interleave_bytes"]))
        sram_cfg["state"]["t_read_cycles"] = int(st.get("t_read_cycles", sram_cfg["state"]["t_read_cycles"]))
        sram_cfg["state"]["t_write_cycles"] = int(st.get("t_write_cycles", sram_cfg["state"]["t_write_cycles"]))
        sram_cfg["state"]["sample_log2"] = int(st.get("sample_log2", sram_cfg["state"]["sample_log2"]))

        sram_cfg["weight"]["idx_base"] = int(lo.get("weight_idx_base", sram_cfg["weight"]["idx_base"]))
        sram_cfg["weight"]["l0_base"] = int(lo.get("weight_l0_base", sram_cfg["weight"]["l0_base"]))
        sram_cfg["state"]["vmem_base"] = int(lo.get("state_vmem_base", sram_cfg["state"]["vmem_base"]))
        sram_cfg["state"]["refrac_base"] = int(lo.get("state_refrac_base", sram_cfg["state"]["refrac_base"]))
        sram_cfg["state"]["last_spike_base"] = int(lo.get("state_last_spike_base", sram_cfg["state"]["last_spike_base"]))

    if sram_cfg["model_enable"] == 1:
        if int(sram_cfg["weight"]["idx_enable"]) == 0 and int(sram_cfg["weight"]["l0_enable"]) == 0 and int(sram_cfg["state"]["enable"]) == 0:
            sram_cfg["weight"]["idx_enable"] = 1
            sram_cfg["weight"]["l0_enable"] = 1

    return sram_cfg


def _build_thermal_cfg(state: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "enable": int(state.get("THERMAL_ENABLE", 0) or 0),
        "backend": str(state.get("THERMAL_BACKEND", "hotspot") or "hotspot").strip().lower(),
        "window_ns": int(state.get("THERMAL_WINDOW_NS", 1000) or 1000),
        "window_trace_enable": int(state.get("THERMAL_WINDOW_TRACE_ENABLE", 0) or 0),
        "window_trace_max_rows": int(state.get("THERMAL_WINDOW_TRACE_MAX_ROWS", 0) or 0),
        "include_memctrl": int(state.get("THERMAL_INCLUDE_MEMCTRL", 0) or 0),
        "out_dir": str(state.get("THERMAL_OUT_DIR", "thermal") or "thermal").strip(),
        "hotspot_bin": str(state.get("THERMAL_HOTSPOT_BIN", "") or "").strip(),
        "generate_floorplan": int(state.get("THERMAL_GENERATE_FLOORPLAN", 1) or 0),
        "model_type": str(state.get("THERMAL_MODEL_TYPE", "block") or "block").strip().lower(),
        "grid_rows": int(state.get("THERMAL_GRID_ROWS", 64) or 64),
        "grid_cols": int(state.get("THERMAL_GRID_COLS", 64) or 64),
        "grid_map_mode": str(state.get("THERMAL_GRID_MAP_MODE", "avg") or "avg").strip().lower(),
        "detailed_3d": int(state.get("THERMAL_DETAILED_3D", 0) or 0),
        "layers": list(state.get("THERMAL_LAYERS", []) or []),
        "tile_width_um": int(state.get("THERMAL_TILE_WIDTH_UM", 1000) or 1000),
        "tile_height_um": int(state.get("THERMAL_TILE_HEIGHT_UM", 1000) or 1000),
        "tile_gap_um": int(state.get("THERMAL_TILE_GAP_UM", 50) or 0),
        "comp_frac": float(state.get("THERMAL_COMP_FRAC", 0.6) or 0.0),
        "sram_frac": float(state.get("THERMAL_SRAM_FRAC", 0.25) or 0.0),
        "noc_frac": float(state.get("THERMAL_NOC_FRAC", 0.15) or 0.0),
    }


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


def _finalize_pulse_state_defaults(*, state: Dict[str, Any]) -> None:
    metadata_txn_enable = int(state.get("PULSE_OSA_METADATA_TXN_ENABLE", 0) or 0) != 0
    mask = str(state.get("PULSE_OSA_METADATA_OBJECT_MASK", "") or "").strip().lower()
    if metadata_txn_enable and not mask:
        state["PULSE_OSA_METADATA_OBJECT_MASK"] = "rowdescriptor"


def _resolve_runtime_spec_first(*, sst_module: Any, script_file: str, spec_path: str) -> MeshRuntime:
    """
    Spec-first runtime resolver.

    - Spec JSON is the only modeling input (besides built-in defaults).
    - local_run_config.json is ignored.
    - Env-based modeling overrides are ignored, except thermal export controls used to
      drive post-run artifact generation (we also seal known legacy env drift keys).
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
    apply_thermal_env_overrides(state=state)
    _finalize_pulse_state_defaults(state=state)

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
    with _EnvPatch({"MESH_BCSR_DIR": None, "MESH_GCSS_DIR": None, "MESH_GCSS2_DIR": None, "MESH_GCSSVLF_DIR": None, "MESH_GCSSPLP_DIR": None, "MESH_GCSSNT_DIR": None, "MESH_GCSSPLP_PROFILE_EXPORT_ENABLE": None, "MESH_GCSSPLP_PROFILE_EXPORT_DIR": None, "MESH_SYNAPSE_WEIGHT_MODE": None, "MESH_BASE_ADDR_SHIFT": None}):
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

    weight_layout = resolve_weight_layout_for_mode(
        synapse_weight_mode=str(state.get("SYNAPSE_WEIGHT_MODE", "bcsr_gas") or "bcsr_gas"),
        gcssnt_dir=str(state.get("GCSSNT_DIR", "") or ""),
        bcsr_core_file_size=int(bcsr_rt.get("core_file_size", 0) or 0),
        num_cores_per_pe=num_cores_per_pe,
        row_align_bytes=8192,
    )
    per_core_weight_stride = int(weight_layout.get("per_core_weight_stride", 0) or 0)
    pe_weight_region_stride = int(weight_layout.get("pe_weight_region_stride", 0) or 0)
    base_addr_global_shift = int(weight_layout.get("base_addr_global_shift", 0) or 0)
    aligned_from = weight_layout.get("base_addr_aligned_from")
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
        "vlf_enable": int(state.get("_GAS_VLF_ENABLE", 0)),
        "vlf_run_enable": int(state.get("_GAS_VLF_RUN_ENABLE", 0)),
        "sort_policy": str(state.get("_GAS_SORT_POLICY", "row")),
        "row_bytes_guess": int(state.get("_GAS_ROW_BYTES_GUESS", 8192)),
        "bank_bits": int(state.get("_GAS_BANK_BITS", 0)),
        "bank_shift": int(state.get("_GAS_BANK_SHIFT", 0)),
        "bank_auto_enable": int(state.get("_GAS_BANK_AUTO_ENABLE", 1)),
        "apply_issue_policy": str(state.get("_GAS_APPLY_ISSUE_POLICY", "order")),
        "apply_frags_per_issue": int(state.get("_GAS_APPLY_FRAGS_PER_ISSUE", 1)),
        "apply_bank_credit": int(state.get("_GAS_APPLY_BANK_CREDIT", 1)),
        "apply_age_fair_ns": int(state.get("_GAS_APPLY_AGE_FAIR_NS", 2000)),
        "experimental_gcss_phase_breakdown_enable": int(state.get("GCSS_PHASE_BREAKDOWN_ENABLE", 0)),
        "experimental_retire_shadow_per_post_enable": int(state.get("RETIRE_SHADOW_PER_POST_ENABLE", 0)),
        "experimental_gcss_vlf_queue_policy": str(state.get("GCSS_VLF_QUEUE_POLICY", "locality_first")),
        "experimental_gcss_vlf_fair_band_size": int(state.get("GCSS_VLF_FAIR_BAND_SIZE", 256)),
        "experimental_gcss_vlf_bounded_rescue_enable": int(state.get("GCSS_VLF_BOUNDED_RESCUE_ENABLE", 0)),
        "experimental_gcss_vlf_bounded_rescue_scan_limit": int(state.get("GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT", 8)),
        "experimental_gcss_vlf_bounded_rescue_head_wait_cycles": int(state.get("GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES", 64)),
        "experimental_gcss_vlf_bounded_rescue_depth_threshold": int(state.get("GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD", 3)),
        # Experimental: DRAM command-cost guided merge guardrails (segment-build stage; default OFF).
        "dram_cmd_cost_merge_enable": int(state.get("_GAS_DRAM_CMD_COST_MERGE_ENABLE", 0)),
        "dram_cmd_t_row_hit_ns": int(state.get("_GAS_DRAM_CMD_T_ROW_HIT_NS", 30)),
        "dram_cmd_t_row_miss_ns": int(state.get("_GAS_DRAM_CMD_T_ROW_MISS_NS", 120)),
        "dram_cmd_t_row_hit_explicit": int(state.get("_GAS_DRAM_CMD_T_ROW_HIT_EXPLICIT", 0)),
        "dram_cmd_t_row_miss_explicit": int(state.get("_GAS_DRAM_CMD_T_ROW_MISS_EXPLICIT", 0)),
        "dram_cmd_offline_model_enable": int(state.get("_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE", 0)),
        "dram_cmd_offline_model_strict": int(state.get("_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT", 0)),
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
        "gcss_dir": resolve_input_path_under_project(str(state.get("GCSS_DIR", "") or ""), script_dir=script_dir),
        "gcss2_dir": resolve_input_path_under_project(str(state.get("GCSS2_DIR", "") or ""), script_dir=script_dir),
        "gcssvlf_dir": resolve_input_path_under_project(str(state.get("GCSSVLF_DIR", "") or ""), script_dir=script_dir),
        "gcssplp_dir": resolve_input_path_under_project(str(state.get("GCSSPLP_DIR", "") or ""), script_dir=script_dir),
        "gcssnt_dir": resolve_input_path_under_project(str(state.get("GCSSNT_DIR", "") or ""), script_dir=script_dir),
        "gcssplp_profile_export_enable": int(state.get("GCSSPLP_PROFILE_EXPORT_ENABLE", 0) or 0),
        "gcssplp_profile_export_dir": str(state.get("GCSSPLP_PROFILE_EXPORT_DIR", "") or ""),
        "experimental_idx2_ingress_prefetch_enable": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_ENABLE", 0) or 0
        ),
        "experimental_idx2_ingress_prefetch_budget_per_tick": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_BUDGET_PER_TICK", 4) or 4
        ),
        "experimental_idx2_ingress_prefetch_cache_entries": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CACHE_ENTRIES", 4096) or 4096
        ),
        "experimental_idx2_ingress_prefetch_max_inflight": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_MAX_INFLIGHT", 0) or 0
        ),
        "experimental_idx2_ingress_prefetch_gather_only": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_GATHER_ONLY", 1) or 0
        ),
        "experimental_idx2_ingress_prefetch_carry_to_apply_enable": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CARRY_TO_APPLY_ENABLE", 0) or 0
        ),
        "experimental_idx2_ingress_prefetch_apply_max_inflight": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_MAX_INFLIGHT", 0) or 0
        ),
        "experimental_idx2_ingress_prefetch_apply_outstanding_reserve": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_OUTSTANDING_RESERVE", 0) or 0
        ),
        "experimental_idx2_ingress_prefetch_apply_frontier_keep_pending": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_FRONTIER_KEEP_PENDING", 0) or 0
        ),
        "experimental_idx2_ingress_tail_guard_enable": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_TAIL_GUARD_ENABLE", 0) or 0
        ),
        "experimental_idx2_ingress_budget_adapt_enable": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_ENABLE", 0) or 0
        ),
        "experimental_idx2_ingress_budget_adapt_max_per_tick": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_MAX_PER_TICK", 32) or 32
        ),
        "experimental_idx2_ingress_budget_adapt_q_depth": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_Q_DEPTH", 16) or 16
        ),
        "experimental_noc_rowidx_prefetch_enable": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_PREFETCH_ENABLE", 0) or 0
        ),
        "experimental_noc_rowidx_prefetch_budget_per_tick": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_PREFETCH_BUDGET_PER_TICK", 4) or 4
        ),
        "experimental_noc_rowidx_cache_rows": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_CACHE_ROWS", 1024) or 1024
        ),
        "experimental_noc_rowidx_prefetch_gather_only": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_PREFETCH_GATHER_ONLY", 1) or 0
        ),
        "experimental_noc_rowidx_prefetch_detached_enable": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_PREFETCH_DETACHED_ENABLE", 0) or 0
        ),
        "experimental_noc_rowidx_prefetch_carry_to_apply_enable": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_PREFETCH_CARRY_TO_APPLY_ENABLE", 0) or 0
        ),
        "experimental_noc_rowidx_hot_touch_min": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_HOT_TOUCH_MIN", 1) or 1
        ),
        "experimental_noc_rowidx_budget_adapt_enable": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_ENABLE", 0) or 0
        ),
        "experimental_noc_rowidx_budget_adapt_max_per_tick": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_MAX_PER_TICK", 32) or 32
        ),
        "experimental_noc_rowidx_budget_adapt_q_depth": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_Q_DEPTH", 16) or 16
        ),
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
        "multicast_enable": bool(state.get("SPEC_MULTICAST_ENABLE", False)),
        "multicast_block_w": int(state.get("SPEC_MULTICAST_BLOCK_W", 2) or 2),
        "multicast_block_h": int(state.get("SPEC_MULTICAST_BLOCK_H", 2) or 2),
        "multicast_ingress_policy": str(state.get("SPEC_MULTICAST_INGRESS_POLICY", "top_left") or "top_left"),
        "multicast_inter_policy": str(state.get("SPEC_MULTICAST_INTER_POLICY", "xy") or "xy"),
        "multicast_intra_policy": str(state.get("SPEC_MULTICAST_INTRA_POLICY", "manhattan_x_first") or "manhattan_x_first"),
        "local_endpoint_multicast_enable": bool(state.get("SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE", False)),
        "router_latency_cycles": int(state.get("SPEC_ROUTER_LATENCY_CYCLES", 0) or 0),
        "router_serialize_output_enable": bool(state.get("SPEC_ROUTER_SERIALIZE_OUTPUT_ENABLE", False)),
        "router_serialize_service_cycles": int(state.get("SPEC_ROUTER_SERIALIZE_SERVICE_CYCLES", 1) or 1),
        "router_serialize_output_byte_enable": bool(state.get("SPEC_ROUTER_SERIALIZE_OUTPUT_BYTE_ENABLE", False)),
        "router_serialize_bytes_per_cycle": int(state.get("SPEC_ROUTER_SERIALIZE_BYTES_PER_CYCLE", 16) or 16),
        "router_serialize_header_bytes": int(state.get("SPEC_ROUTER_SERIALIZE_HEADER_BYTES", 24) or 24),
        "workload_impl": str(state.get("SPEC_WORKLOAD_IMPL", "snn") or "snn"),
        "workload_stats_modules": str(state.get("SPEC_WORKLOAD_STATS_MODULES", "") or ""),
        "workload_params": {
            "backend_name": str(state.get("SPEC_RISCV_SNN_BACKEND_NAME", "null") or "null"),
            "firmware_elf": resolve_input_path_under_project(
                str(state.get("SPEC_RISCV_SNN_FIRMWARE_ELF", "") or ""),
                script_dir=script_dir,
            ),
            "hart_isa": str(state.get("SPEC_RISCV_SNN_HART_ISA", "rv64im_zicsr") or "rv64im_zicsr"),
            "local_mem_bytes": int(state.get("SPEC_RISCV_SNN_LOCAL_MEM_BYTES", 64 * 1024) or 0),
            "cmd_queue_entries": int(state.get("SPEC_RISCV_SNN_CMD_QUEUE_ENTRIES", 64) or 0),
            "cmp_queue_entries": int(state.get("SPEC_RISCV_SNN_CMP_QUEUE_ENTRIES", 64) or 0),
            "rx_debug_queue_entries": int(state.get("SPEC_RISCV_SNN_RX_DEBUG_QUEUE_ENTRIES", 16) or 0),
            "boot_addr": int(state.get("SPEC_RISCV_SNN_BOOT_ADDR", 0) or 0),
        },
        "synapse_weight_mode": str(state.get("SYNAPSE_WEIGHT_MODE", "bcsr_gas") or "bcsr_gas"),
        "local_storage_enable": int(state.get("LOCAL_STORAGE_ENABLE", 0) or 0),
        "pe_internal_cpe_enable": int(state.get("PE_INTERNAL_CPE_ENABLE", 0) or 0),
        "pe_internal_pod_enable": int(state.get("PE_INTERNAL_POD_ENABLE", 0) or 0),
        "pe_internal_pod_count": int(state.get("PE_INTERNAL_POD_COUNT", 0) or 0),
        "pe_internal_pod_size": int(state.get("PE_INTERNAL_POD_SIZE", 0) or 0),
        "pe_internal_pod_metadata_enable": int(state.get("PE_INTERNAL_POD_METADATA_ENABLE", 0) or 0),
        "pe_internal_pod_owner_enable": int(state.get("PE_INTERNAL_POD_OWNER_ENABLE", 0) or 0),
        "pe_internal_pod_join_enable": int(state.get("PE_INTERNAL_POD_JOIN_ENABLE", 0) or 0),
        "pe_internal_pod_ready_enable": int(state.get("PE_INTERNAL_POD_READY_ENABLE", 0) or 0),
        "pe_internal_pod_owner_entries": int(state.get("PE_INTERNAL_POD_OWNER_ENTRIES", 0) or 0),
        "pe_internal_pod_join_entries": int(state.get("PE_INTERNAL_POD_JOIN_ENTRIES", 0) or 0),
        "pe_internal_pod_ready_entries": int(state.get("PE_INTERNAL_POD_READY_ENTRIES", 0) or 0),
        "pulse_enable": int(state.get("PULSE_ENABLE", 0) or 0),
        "pulse_observe_only": int(state.get("PULSE_OBSERVE_ONLY", 1) or 0),
        "pulse_ingress_enable": int(state.get("PULSE_INGRESS_ENABLE", 1) or 0),
        "pulse_agenda_observe_only": int(state.get("PULSE_AGENDA_OBSERVE_ONLY", 1) or 0),
        "pulse_harbor_enable": int(state.get("PULSE_HARBOR_ENABLE", 0) or 0),
        "pulse_descriptor_enable": int(state.get("PULSE_DESCRIPTOR_ENABLE", 0) or 0),
        "pulse_descriptor_actual_enable": int(state.get("PULSE_DESCRIPTOR_ACTUAL_ENABLE", 0) or 0),
        "pulse_experimental_rowdescriptor_ready_join_dedup_enable": int(
            state.get("PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE", 0) or 0
        ),
        "pulse_domain_retire_enable": int(state.get("PULSE_DOMAIN_RETIRE_ENABLE", 0) or 0),
        "pulse_domain_retire_observe_only": int(state.get("PULSE_DOMAIN_RETIRE_OBSERVE_ONLY", 1) or 0),
        "pulse_domain_retire_mode": str(state.get("PULSE_DOMAIN_RETIRE_MODE", "per_post") or "per_post"),
        "pulse_domain_retire_release_budget": int(state.get("PULSE_DOMAIN_RETIRE_RELEASE_BUDGET", 0) or 0),
        "pulse_frontier_observe_enable": int(state.get("PULSE_FRONTIER_OBSERVE_ENABLE", 0) or 0),
        "pulse_frontier_top_lines": int(state.get("PULSE_FRONTIER_TOP_LINES", 32) or 32),
        "pulse_metadata_frontier_observe_enable": int(
            state.get("PULSE_METADATA_FRONTIER_OBSERVE_ENABLE", 0) or 0
        ),
        "pulse_metadata_frontier_top_items": int(
            state.get("PULSE_METADATA_FRONTIER_TOP_ITEMS", 32) or 32
        ),
        "pulse_metadata_frontier_band_slots": int(
            state.get("PULSE_METADATA_FRONTIER_BAND_SLOTS", 128) or 128
        ),
        "pulse_metadata_seed_enable": int(state.get("PULSE_METADATA_SEED_ENABLE", 0) or 0),
        "pulse_metadata_seed_top_bases": int(state.get("PULSE_METADATA_SEED_TOP_BASES", 32) or 32),
        "pulse_metadata_seed_window_budget": int(
            state.get("PULSE_METADATA_SEED_WINDOW_BUDGET", 0) or 0
        ),
        "pulse_mfb_preband_seed_enable": int(state.get("PULSE_MFB_PREBAND_SEED_ENABLE", 0) or 0),
        "pulse_mfb_preband_top_bands": int(state.get("PULSE_MFB_PREBAND_TOP_BANDS", 32) or 32),
        "pulse_mfb_preband_lines_per_band": int(state.get("PULSE_MFB_PREBAND_LINES_PER_BAND", 4) or 4),
        "pulse_mfb_preband_band_slots": int(state.get("PULSE_MFB_PREBAND_BAND_SLOTS", 0) or 0),
        "pulse_mfb_preband_window_budget": int(
            state.get("PULSE_MFB_PREBAND_WINDOW_BUDGET", 0) or 0
        ),
        "pulse_mfb_gather_preband_enable": int(
            state.get("PULSE_MFB_GATHER_PREBAND_ENABLE", 0) or 0
        ),
        "pulse_mfb_gather_barrier_enable": int(
            state.get("PULSE_MFB_GATHER_BARRIER_ENABLE", 0) or 0
        ),
        "pulse_mfb_gather_top_bands": int(state.get("PULSE_MFB_GATHER_TOP_BANDS", 32) or 32),
        "pulse_mfb_gather_lines_per_band": int(
            state.get("PULSE_MFB_GATHER_LINES_PER_BAND", 4) or 4
        ),
        "pulse_mfb_gather_min_consumers": int(
            state.get("PULSE_MFB_GATHER_MIN_CONSUMERS", 2) or 2
        ),
        "pulse_mfb_gather_window_budget": int(
            state.get("PULSE_MFB_GATHER_WINDOW_BUDGET", 0) or 0
        ),
        "pulse_prebase_shared_lookup_enable": int(
            state.get("PULSE_PREBASE_SHARED_LOOKUP_ENABLE", 0) or 0
        ),
        "pulse_osa_enable": int(state.get("PULSE_OSA_ENABLE", 0) or 0),
        "pulse_osa_shared_weight_owner_enable": int(
            state.get("PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE", 0) or 0
        ),
        "pulse_osa_shared_weight_owner_actual_enable": int(
            state.get("PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE", 0) or 0
        ),
        "pulse_osa_metadata_txn_enable": int(
            state.get("PULSE_OSA_METADATA_TXN_ENABLE", 0) or 0
        ),
        "pulse_osa_metadata_ready_lease_enable": int(
            state.get("PULSE_OSA_METADATA_READY_LEASE_ENABLE", 0) or 0
        ),
        "pulse_osa_metadata_ready_lease_ttl": int(
            state.get("PULSE_OSA_METADATA_READY_LEASE_TTL", 0) or 0
        ),
        "pulse_osa_metadata_object_mask": str(
            state.get("PULSE_OSA_METADATA_OBJECT_MASK", "") or ""
        ),
        "pulse_ingress_entries": int(state.get("PULSE_INGRESS_ENTRIES", 0) or 0),
        "pulse_core_queue_entries": int(state.get("PULSE_CORE_QUEUE_ENTRIES", 0) or 0),
        "pulse_descriptor_packet_min": int(state.get("PULSE_DESCRIPTOR_PACKET_MIN", 2) or 2),
        "pulse_bypass_high_watermark_pct": int(state.get("PULSE_BYPASS_HIGH_WATERMARK_PCT", 100) or 100),
        "pulse_bypass_mode": str(state.get("PULSE_BYPASS_MODE", "disabled") or "disabled"),
        "pulse": {
            "enable": int(state.get("PULSE_ENABLE", 0) or 0),
            "observe_only": int(state.get("PULSE_OBSERVE_ONLY", 1) or 0),
            "ingress_enable": int(state.get("PULSE_INGRESS_ENABLE", 1) or 0),
            "agenda_observe_only": int(state.get("PULSE_AGENDA_OBSERVE_ONLY", 1) or 0),
            "harbor_enable": int(state.get("PULSE_HARBOR_ENABLE", 0) or 0),
            "descriptor_enable": int(state.get("PULSE_DESCRIPTOR_ENABLE", 0) or 0),
            "descriptor_actual_enable": int(state.get("PULSE_DESCRIPTOR_ACTUAL_ENABLE", 0) or 0),
            "experimental_rowdescriptor_ready_join_dedup_enable": int(
                state.get("PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE", 0) or 0
            ),
            "domain_retire_enable": int(state.get("PULSE_DOMAIN_RETIRE_ENABLE", 0) or 0),
            "domain_retire_observe_only": int(state.get("PULSE_DOMAIN_RETIRE_OBSERVE_ONLY", 1) or 0),
            "domain_retire_mode": str(state.get("PULSE_DOMAIN_RETIRE_MODE", "per_post") or "per_post"),
            "domain_retire_release_budget": int(state.get("PULSE_DOMAIN_RETIRE_RELEASE_BUDGET", 0) or 0),
            "frontier_observe_enable": int(state.get("PULSE_FRONTIER_OBSERVE_ENABLE", 0) or 0),
            "frontier_top_lines": int(state.get("PULSE_FRONTIER_TOP_LINES", 32) or 32),
            "metadata_frontier_observe_enable": int(
                state.get("PULSE_METADATA_FRONTIER_OBSERVE_ENABLE", 0) or 0
            ),
            "metadata_frontier_top_items": int(
                state.get("PULSE_METADATA_FRONTIER_TOP_ITEMS", 32) or 32
            ),
            "metadata_frontier_band_slots": int(
                state.get("PULSE_METADATA_FRONTIER_BAND_SLOTS", 128) or 128
            ),
            "metadata_seed_enable": int(state.get("PULSE_METADATA_SEED_ENABLE", 0) or 0),
            "metadata_seed_top_bases": int(state.get("PULSE_METADATA_SEED_TOP_BASES", 32) or 32),
            "metadata_seed_window_budget": int(
                state.get("PULSE_METADATA_SEED_WINDOW_BUDGET", 0) or 0
            ),
            "mfb_preband_seed_enable": int(state.get("PULSE_MFB_PREBAND_SEED_ENABLE", 0) or 0),
            "mfb_preband_top_bands": int(state.get("PULSE_MFB_PREBAND_TOP_BANDS", 32) or 32),
            "mfb_preband_lines_per_band": int(state.get("PULSE_MFB_PREBAND_LINES_PER_BAND", 4) or 4),
            "mfb_preband_band_slots": int(state.get("PULSE_MFB_PREBAND_BAND_SLOTS", 0) or 0),
            "mfb_preband_window_budget": int(
                state.get("PULSE_MFB_PREBAND_WINDOW_BUDGET", 0) or 0
            ),
            "mfb_gather_preband_enable": int(
                state.get("PULSE_MFB_GATHER_PREBAND_ENABLE", 0) or 0
            ),
            "mfb_gather_barrier_enable": int(
                state.get("PULSE_MFB_GATHER_BARRIER_ENABLE", 0) or 0
            ),
            "mfb_gather_top_bands": int(state.get("PULSE_MFB_GATHER_TOP_BANDS", 32) or 32),
            "mfb_gather_lines_per_band": int(
                state.get("PULSE_MFB_GATHER_LINES_PER_BAND", 4) or 4
            ),
            "mfb_gather_min_consumers": int(
                state.get("PULSE_MFB_GATHER_MIN_CONSUMERS", 2) or 2
            ),
            "mfb_gather_window_budget": int(
                state.get("PULSE_MFB_GATHER_WINDOW_BUDGET", 0) or 0
            ),
            "prebase_shared_lookup_enable": int(
                state.get("PULSE_PREBASE_SHARED_LOOKUP_ENABLE", 0) or 0
            ),
            "osa_enable": int(state.get("PULSE_OSA_ENABLE", 0) or 0),
            "osa_shared_weight_owner_enable": int(
                state.get("PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE", 0) or 0
            ),
            "osa_shared_weight_owner_actual_enable": int(
                state.get("PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE", 0) or 0
            ),
            "osa_metadata_txn_enable": int(
                state.get("PULSE_OSA_METADATA_TXN_ENABLE", 0) or 0
            ),
            "osa_metadata_ready_lease_enable": int(
                state.get("PULSE_OSA_METADATA_READY_LEASE_ENABLE", 0) or 0
            ),
            "osa_metadata_ready_lease_ttl": int(
                state.get("PULSE_OSA_METADATA_READY_LEASE_TTL", 0) or 0
            ),
            "osa_metadata_object_mask": str(
                state.get("PULSE_OSA_METADATA_OBJECT_MASK", "") or ""
            ),
            "ingress_entries": int(state.get("PULSE_INGRESS_ENTRIES", 0) or 0),
            "core_queue_entries": int(state.get("PULSE_CORE_QUEUE_ENTRIES", 0) or 0),
            "descriptor_packet_min": int(state.get("PULSE_DESCRIPTOR_PACKET_MIN", 2) or 2),
            "bypass_high_watermark_pct": int(state.get("PULSE_BYPASS_HIGH_WATERMARK_PCT", 100) or 100),
            "bypass_mode": str(state.get("PULSE_BYPASS_MODE", "disabled") or "disabled"),
        },
        "thermal": _build_thermal_cfg(state),
        "sram": _build_sram_cfg(state, script_dir=script_dir),
    }
    if state.get("MAX_OUTSTANDING_REQUESTS_OVERRIDE") is not None:
        mesh_cfg["max_outstanding_requests"] = int(state.get("MAX_OUTSTANDING_REQUESTS_OVERRIDE"))
    if state.get("WINDOW_READ_BUDGET_OVERRIDE") is not None:
        mesh_cfg["window_read_budget"] = int(state.get("WINDOW_READ_BUDGET_OVERRIDE"))

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
    if "RAMULATOR2_ADMISSION_QUEUE_SIZE" in state:
        mem_layout_cfg["ramulator2_admission_queue_size"] = int(state.get("RAMULATOR2_ADMISSION_QUEUE_SIZE", 0))
    if "RAMULATOR2_ADMISSION_ISSUE_BUDGET_PER_CYCLE" in state:
        mem_layout_cfg["ramulator2_admission_issue_budget_per_cycle"] = int(
            state.get("RAMULATOR2_ADMISSION_ISSUE_BUDGET_PER_CYCLE", -1)
        )
    if "RAMULATOR2_MAX_REQUESTS_PER_CYCLE" in state:
        mem_layout_cfg["ramulator2_max_requests_per_cycle"] = int(state.get("RAMULATOR2_MAX_REQUESTS_PER_CYCLE", -1))

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
                gas_dram_cmd_offline_model_env_present=bool(
                    gas_env_flags.get("gas_dram_cmd_offline_model_env_present", False)
                ),
                gas_dram_cmd_offline_model_strict_env_present=bool(
                    gas_env_flags.get("gas_dram_cmd_offline_model_strict_env_present", False)
                ),
            )
            if stats_lvl is not None:
                try:
                    sst_module.setStatisticLoadLevel(int(stats_lvl))
                except Exception:
                    sst_module.setStatisticLoadLevel(DEFAULT_STATS_LEVEL)
        except Exception as e:
            mesh_print(f"[local_run_config] 读取失败: {e}")
            cfg = None

    apply_pulse_env_overrides(state=state)
    apply_thermal_env_overrides(state=state)
    _finalize_pulse_state_defaults(state=state)

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

    weight_layout = resolve_weight_layout_for_mode(
        synapse_weight_mode=str(state.get("SYNAPSE_WEIGHT_MODE", "bcsr_gas") or "bcsr_gas"),
        gcssnt_dir=str(state.get("GCSSNT_DIR", "") or ""),
        bcsr_core_file_size=int(bcsr_rt.get("core_file_size", 0) or 0),
        num_cores_per_pe=num_cores_per_pe,
        row_align_bytes=8192,
    )
    per_core_weight_stride = int(weight_layout.get("per_core_weight_stride", 0) or 0)
    pe_weight_region_stride = int(weight_layout.get("pe_weight_region_stride", 0) or 0)
    base_addr_global_shift = int(weight_layout.get("base_addr_global_shift", 0) or 0)
    aligned_from = weight_layout.get("base_addr_aligned_from")
    if aligned_from is not None:
        mesh_print(f"[mesh] align BASE_ADDR_GLOBAL_SHIFT: 0x{int(aligned_from):x} -> 0x{base_addr_global_shift:x}")

    mesh_print(f"📁 权重目录: {weights_dir}")
    if global_bcsr_available:
        max_file_size = int(weight_layout.get("core_file_size", bcsr_rt.get("core_file_size", 0)) or 0)
        layout_source = str(weight_layout.get("layout_source", bcsr_rt.get("layout_source", "bcsr")) or "bcsr")
        mesh_print(f"  ✅ 检测到全局BCSR数据: {global_bcsr_dir}")
        mesh_print(
            f"  🧮 {layout_source.upper()} stride: metas={len(bcsr_rt.get('all_meta', []) or [])} "
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
        # Experimental: Value-Line Fusion (VLF) controls.
        "vlf_enable": int(state.get("_GAS_VLF_ENABLE", 0)),
        "vlf_run_enable": int(state.get("_GAS_VLF_RUN_ENABLE", 0)),
        "sort_policy": str(state.get("_GAS_SORT_POLICY", "row")),
        "row_bytes_guess": int(state.get("_GAS_ROW_BYTES_GUESS", 8192)),
        "bank_bits": int(state.get("_GAS_BANK_BITS", 0)),
        "bank_shift": int(state.get("_GAS_BANK_SHIFT", 0)),
        "bank_auto_enable": int(state.get("_GAS_BANK_AUTO_ENABLE", 1)),
        "apply_issue_policy": str(state.get("_GAS_APPLY_ISSUE_POLICY", "order")),
        "apply_frags_per_issue": int(state.get("_GAS_APPLY_FRAGS_PER_ISSUE", 1)),
        "apply_bank_credit": int(state.get("_GAS_APPLY_BANK_CREDIT", 1)),
        "apply_age_fair_ns": int(state.get("_GAS_APPLY_AGE_FAIR_NS", 2000)),
        "experimental_gcss_phase_breakdown_enable": int(state.get("GCSS_PHASE_BREAKDOWN_ENABLE", 0)),
        "experimental_retire_shadow_per_post_enable": int(state.get("RETIRE_SHADOW_PER_POST_ENABLE", 0)),
        "experimental_gcss_vlf_queue_policy": str(state.get("GCSS_VLF_QUEUE_POLICY", "locality_first")),
        "experimental_gcss_vlf_fair_band_size": int(state.get("GCSS_VLF_FAIR_BAND_SIZE", 256)),
        "experimental_gcss_vlf_bounded_rescue_enable": int(state.get("GCSS_VLF_BOUNDED_RESCUE_ENABLE", 0)),
        "experimental_gcss_vlf_bounded_rescue_scan_limit": int(state.get("GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT", 8)),
        "experimental_gcss_vlf_bounded_rescue_head_wait_cycles": int(state.get("GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES", 64)),
        "experimental_gcss_vlf_bounded_rescue_depth_threshold": int(state.get("GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD", 3)),
        # Experimental: DRAM command-cost guided merge guardrails (segment-build stage; default OFF).
        "dram_cmd_cost_merge_enable": int(state.get("_GAS_DRAM_CMD_COST_MERGE_ENABLE", 0)),
        "dram_cmd_t_row_hit_ns": int(state.get("_GAS_DRAM_CMD_T_ROW_HIT_NS", 30)),
        "dram_cmd_t_row_miss_ns": int(state.get("_GAS_DRAM_CMD_T_ROW_MISS_NS", 120)),
        "dram_cmd_t_row_hit_explicit": int(state.get("_GAS_DRAM_CMD_T_ROW_HIT_EXPLICIT", 0)),
        "dram_cmd_t_row_miss_explicit": int(state.get("_GAS_DRAM_CMD_T_ROW_MISS_EXPLICIT", 0)),
        "dram_cmd_offline_model_enable": int(state.get("_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE", 0)),
        "dram_cmd_offline_model_strict": int(state.get("_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT", 0)),
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
        "gcss_dir": resolve_input_path_under_project(str(state.get("GCSS_DIR", "") or ""), script_dir=script_dir),
        "gcss2_dir": resolve_input_path_under_project(str(state.get("GCSS2_DIR", "") or ""), script_dir=script_dir),
        "gcssvlf_dir": resolve_input_path_under_project(str(state.get("GCSSVLF_DIR", "") or ""), script_dir=script_dir),
        "gcssplp_dir": resolve_input_path_under_project(str(state.get("GCSSPLP_DIR", "") or ""), script_dir=script_dir),
        "gcssnt_dir": resolve_input_path_under_project(str(state.get("GCSSNT_DIR", "") or ""), script_dir=script_dir),
        "gcssplp_profile_export_enable": int(state.get("GCSSPLP_PROFILE_EXPORT_ENABLE", 0) or 0),
        "gcssplp_profile_export_dir": str(state.get("GCSSPLP_PROFILE_EXPORT_DIR", "") or ""),
        "experimental_idx2_ingress_prefetch_enable": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_ENABLE", 0) or 0
        ),
        "experimental_idx2_ingress_prefetch_budget_per_tick": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_BUDGET_PER_TICK", 4) or 4
        ),
        "experimental_idx2_ingress_prefetch_cache_entries": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CACHE_ENTRIES", 4096) or 4096
        ),
        "experimental_idx2_ingress_prefetch_max_inflight": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_MAX_INFLIGHT", 0) or 0
        ),
        "experimental_idx2_ingress_prefetch_gather_only": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_GATHER_ONLY", 1) or 0
        ),
        "experimental_idx2_ingress_prefetch_carry_to_apply_enable": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CARRY_TO_APPLY_ENABLE", 0) or 0
        ),
        "experimental_idx2_ingress_prefetch_apply_max_inflight": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_MAX_INFLIGHT", 0) or 0
        ),
        "experimental_idx2_ingress_prefetch_apply_outstanding_reserve": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_OUTSTANDING_RESERVE", 0) or 0
        ),
        "experimental_idx2_ingress_prefetch_apply_frontier_keep_pending": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_FRONTIER_KEEP_PENDING", 0) or 0
        ),
        "experimental_idx2_ingress_tail_guard_enable": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_TAIL_GUARD_ENABLE", 0) or 0
        ),
        "experimental_idx2_ingress_budget_adapt_enable": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_ENABLE", 0) or 0
        ),
        "experimental_idx2_ingress_budget_adapt_max_per_tick": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_MAX_PER_TICK", 32) or 32
        ),
        "experimental_idx2_ingress_budget_adapt_q_depth": int(
            state.get("EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_Q_DEPTH", 16) or 16
        ),
        "experimental_noc_rowidx_prefetch_enable": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_PREFETCH_ENABLE", 0) or 0
        ),
        "experimental_noc_rowidx_prefetch_budget_per_tick": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_PREFETCH_BUDGET_PER_TICK", 4) or 4
        ),
        "experimental_noc_rowidx_cache_rows": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_CACHE_ROWS", 1024) or 1024
        ),
        "experimental_noc_rowidx_prefetch_gather_only": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_PREFETCH_GATHER_ONLY", 1) or 0
        ),
        "experimental_noc_rowidx_prefetch_detached_enable": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_PREFETCH_DETACHED_ENABLE", 0) or 0
        ),
        "experimental_noc_rowidx_prefetch_carry_to_apply_enable": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_PREFETCH_CARRY_TO_APPLY_ENABLE", 0) or 0
        ),
        "experimental_noc_rowidx_hot_touch_min": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_HOT_TOUCH_MIN", 1) or 1
        ),
        "experimental_noc_rowidx_budget_adapt_enable": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_ENABLE", 0) or 0
        ),
        "experimental_noc_rowidx_budget_adapt_max_per_tick": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_MAX_PER_TICK", 32) or 32
        ),
        "experimental_noc_rowidx_budget_adapt_q_depth": int(
            state.get("EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_Q_DEPTH", 16) or 16
        ),
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
        "network_num_vns": int(state.get("SPEC_NETWORK_NUM_VNS", 2) or 2),
        "multicast_enable": bool(state.get("SPEC_MULTICAST_ENABLE", False)),
        "multicast_block_w": int(state.get("SPEC_MULTICAST_BLOCK_W", 2) or 2),
        "multicast_block_h": int(state.get("SPEC_MULTICAST_BLOCK_H", 2) or 2),
        "multicast_ingress_policy": str(state.get("SPEC_MULTICAST_INGRESS_POLICY", "top_left") or "top_left"),
        "multicast_inter_policy": str(state.get("SPEC_MULTICAST_INTER_POLICY", "xy") or "xy"),
        "multicast_intra_policy": str(state.get("SPEC_MULTICAST_INTRA_POLICY", "manhattan_x_first") or "manhattan_x_first"),
        "local_endpoint_multicast_enable": bool(state.get("SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE", False)),
        "router_latency_cycles": int(state.get("SPEC_ROUTER_LATENCY_CYCLES", 0) or 0),
        "router_serialize_output_enable": bool(state.get("SPEC_ROUTER_SERIALIZE_OUTPUT_ENABLE", False)),
        "router_serialize_service_cycles": int(state.get("SPEC_ROUTER_SERIALIZE_SERVICE_CYCLES", 1) or 1),
        "router_serialize_output_byte_enable": bool(state.get("SPEC_ROUTER_SERIALIZE_OUTPUT_BYTE_ENABLE", False)),
        "router_serialize_bytes_per_cycle": int(state.get("SPEC_ROUTER_SERIALIZE_BYTES_PER_CYCLE", 16) or 16),
        "router_serialize_header_bytes": int(state.get("SPEC_ROUTER_SERIALIZE_HEADER_BYTES", 24) or 24),
        "synapse_weight_mode": str(state.get("SYNAPSE_WEIGHT_MODE", "bcsr_gas") or "bcsr_gas"),
        "local_storage_enable": int(state.get("LOCAL_STORAGE_ENABLE", 0) or 0),
        "pe_internal_cpe_enable": int(state.get("PE_INTERNAL_CPE_ENABLE", 0) or 0),
        "pe_internal_pod_enable": int(state.get("PE_INTERNAL_POD_ENABLE", 0) or 0),
        "pe_internal_pod_count": int(state.get("PE_INTERNAL_POD_COUNT", 0) or 0),
        "pe_internal_pod_size": int(state.get("PE_INTERNAL_POD_SIZE", 0) or 0),
        "pe_internal_pod_metadata_enable": int(state.get("PE_INTERNAL_POD_METADATA_ENABLE", 0) or 0),
        "pe_internal_pod_owner_enable": int(state.get("PE_INTERNAL_POD_OWNER_ENABLE", 0) or 0),
        "pe_internal_pod_join_enable": int(state.get("PE_INTERNAL_POD_JOIN_ENABLE", 0) or 0),
        "pe_internal_pod_ready_enable": int(state.get("PE_INTERNAL_POD_READY_ENABLE", 0) or 0),
        "pe_internal_pod_owner_entries": int(state.get("PE_INTERNAL_POD_OWNER_ENTRIES", 0) or 0),
        "pe_internal_pod_join_entries": int(state.get("PE_INTERNAL_POD_JOIN_ENTRIES", 0) or 0),
        "pe_internal_pod_ready_entries": int(state.get("PE_INTERNAL_POD_READY_ENTRIES", 0) or 0),
        "pulse_enable": int(state.get("PULSE_ENABLE", 0) or 0),
        "pulse_observe_only": int(state.get("PULSE_OBSERVE_ONLY", 1) or 0),
        "pulse_ingress_enable": int(state.get("PULSE_INGRESS_ENABLE", 1) or 0),
        "pulse_agenda_observe_only": int(state.get("PULSE_AGENDA_OBSERVE_ONLY", 1) or 0),
        "pulse_harbor_enable": int(state.get("PULSE_HARBOR_ENABLE", 0) or 0),
        "pulse_descriptor_enable": int(state.get("PULSE_DESCRIPTOR_ENABLE", 0) or 0),
        "pulse_descriptor_actual_enable": int(state.get("PULSE_DESCRIPTOR_ACTUAL_ENABLE", 0) or 0),
        "pulse_experimental_rowdescriptor_ready_join_dedup_enable": int(
            state.get("PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE", 0) or 0
        ),
        "pulse_domain_retire_enable": int(state.get("PULSE_DOMAIN_RETIRE_ENABLE", 0) or 0),
        "pulse_domain_retire_observe_only": int(state.get("PULSE_DOMAIN_RETIRE_OBSERVE_ONLY", 1) or 0),
        "pulse_domain_retire_mode": str(state.get("PULSE_DOMAIN_RETIRE_MODE", "per_post") or "per_post"),
        "pulse_domain_retire_release_budget": int(state.get("PULSE_DOMAIN_RETIRE_RELEASE_BUDGET", 0) or 0),
        "pulse_frontier_observe_enable": int(state.get("PULSE_FRONTIER_OBSERVE_ENABLE", 0) or 0),
        "pulse_frontier_top_lines": int(state.get("PULSE_FRONTIER_TOP_LINES", 32) or 32),
        "pulse_metadata_frontier_observe_enable": int(
            state.get("PULSE_METADATA_FRONTIER_OBSERVE_ENABLE", 0) or 0
        ),
        "pulse_metadata_frontier_top_items": int(
            state.get("PULSE_METADATA_FRONTIER_TOP_ITEMS", 32) or 32
        ),
        "pulse_metadata_frontier_band_slots": int(
            state.get("PULSE_METADATA_FRONTIER_BAND_SLOTS", 128) or 128
        ),
        "pulse_metadata_seed_enable": int(state.get("PULSE_METADATA_SEED_ENABLE", 0) or 0),
        "pulse_metadata_seed_top_bases": int(state.get("PULSE_METADATA_SEED_TOP_BASES", 32) or 32),
        "pulse_metadata_seed_window_budget": int(
            state.get("PULSE_METADATA_SEED_WINDOW_BUDGET", 0) or 0
        ),
        "pulse_mfb_preband_seed_enable": int(state.get("PULSE_MFB_PREBAND_SEED_ENABLE", 0) or 0),
        "pulse_mfb_preband_top_bands": int(state.get("PULSE_MFB_PREBAND_TOP_BANDS", 32) or 32),
        "pulse_mfb_preband_lines_per_band": int(state.get("PULSE_MFB_PREBAND_LINES_PER_BAND", 4) or 4),
        "pulse_mfb_preband_band_slots": int(state.get("PULSE_MFB_PREBAND_BAND_SLOTS", 0) or 0),
        "pulse_mfb_preband_window_budget": int(
            state.get("PULSE_MFB_PREBAND_WINDOW_BUDGET", 0) or 0
        ),
        "pulse_mfb_gather_preband_enable": int(
            state.get("PULSE_MFB_GATHER_PREBAND_ENABLE", 0) or 0
        ),
        "pulse_mfb_gather_barrier_enable": int(
            state.get("PULSE_MFB_GATHER_BARRIER_ENABLE", 0) or 0
        ),
        "pulse_mfb_gather_top_bands": int(state.get("PULSE_MFB_GATHER_TOP_BANDS", 32) or 32),
        "pulse_mfb_gather_lines_per_band": int(
            state.get("PULSE_MFB_GATHER_LINES_PER_BAND", 4) or 4
        ),
        "pulse_mfb_gather_min_consumers": int(
            state.get("PULSE_MFB_GATHER_MIN_CONSUMERS", 2) or 2
        ),
        "pulse_mfb_gather_window_budget": int(
            state.get("PULSE_MFB_GATHER_WINDOW_BUDGET", 0) or 0
        ),
        "pulse_prebase_shared_lookup_enable": int(
            state.get("PULSE_PREBASE_SHARED_LOOKUP_ENABLE", 0) or 0
        ),
        "pulse_osa_enable": int(state.get("PULSE_OSA_ENABLE", 0) or 0),
        "pulse_osa_shared_weight_owner_enable": int(
            state.get("PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE", 0) or 0
        ),
        "pulse_osa_shared_weight_owner_actual_enable": int(
            state.get("PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE", 0) or 0
        ),
        "pulse_osa_metadata_txn_enable": int(
            state.get("PULSE_OSA_METADATA_TXN_ENABLE", 0) or 0
        ),
        "pulse_osa_metadata_ready_lease_enable": int(
            state.get("PULSE_OSA_METADATA_READY_LEASE_ENABLE", 0) or 0
        ),
        "pulse_osa_metadata_ready_lease_ttl": int(
            state.get("PULSE_OSA_METADATA_READY_LEASE_TTL", 0) or 0
        ),
        "pulse_osa_metadata_object_mask": str(
            state.get("PULSE_OSA_METADATA_OBJECT_MASK", "") or ""
        ),
        "pulse_ingress_entries": int(state.get("PULSE_INGRESS_ENTRIES", 0) or 0),
        "pulse_core_queue_entries": int(state.get("PULSE_CORE_QUEUE_ENTRIES", 0) or 0),
        "pulse_descriptor_packet_min": int(state.get("PULSE_DESCRIPTOR_PACKET_MIN", 2) or 2),
        "pulse_bypass_high_watermark_pct": int(state.get("PULSE_BYPASS_HIGH_WATERMARK_PCT", 100) or 100),
        "pulse_bypass_mode": str(state.get("PULSE_BYPASS_MODE", "disabled") or "disabled"),
        "pulse": {
            "enable": int(state.get("PULSE_ENABLE", 0) or 0),
            "observe_only": int(state.get("PULSE_OBSERVE_ONLY", 1) or 0),
            "ingress_enable": int(state.get("PULSE_INGRESS_ENABLE", 1) or 0),
            "agenda_observe_only": int(state.get("PULSE_AGENDA_OBSERVE_ONLY", 1) or 0),
            "harbor_enable": int(state.get("PULSE_HARBOR_ENABLE", 0) or 0),
            "descriptor_enable": int(state.get("PULSE_DESCRIPTOR_ENABLE", 0) or 0),
            "descriptor_actual_enable": int(state.get("PULSE_DESCRIPTOR_ACTUAL_ENABLE", 0) or 0),
            "experimental_rowdescriptor_ready_join_dedup_enable": int(
                state.get("PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE", 0) or 0
            ),
            "domain_retire_enable": int(state.get("PULSE_DOMAIN_RETIRE_ENABLE", 0) or 0),
            "domain_retire_observe_only": int(state.get("PULSE_DOMAIN_RETIRE_OBSERVE_ONLY", 1) or 0),
            "domain_retire_mode": str(state.get("PULSE_DOMAIN_RETIRE_MODE", "per_post") or "per_post"),
            "domain_retire_release_budget": int(state.get("PULSE_DOMAIN_RETIRE_RELEASE_BUDGET", 0) or 0),
            "frontier_observe_enable": int(state.get("PULSE_FRONTIER_OBSERVE_ENABLE", 0) or 0),
            "frontier_top_lines": int(state.get("PULSE_FRONTIER_TOP_LINES", 32) or 32),
            "metadata_frontier_observe_enable": int(
                state.get("PULSE_METADATA_FRONTIER_OBSERVE_ENABLE", 0) or 0
            ),
            "metadata_frontier_top_items": int(
                state.get("PULSE_METADATA_FRONTIER_TOP_ITEMS", 32) or 32
            ),
            "metadata_frontier_band_slots": int(
                state.get("PULSE_METADATA_FRONTIER_BAND_SLOTS", 128) or 128
            ),
            "metadata_seed_enable": int(state.get("PULSE_METADATA_SEED_ENABLE", 0) or 0),
            "metadata_seed_top_bases": int(state.get("PULSE_METADATA_SEED_TOP_BASES", 32) or 32),
            "metadata_seed_window_budget": int(
                state.get("PULSE_METADATA_SEED_WINDOW_BUDGET", 0) or 0
            ),
            "mfb_preband_seed_enable": int(state.get("PULSE_MFB_PREBAND_SEED_ENABLE", 0) or 0),
            "mfb_preband_top_bands": int(state.get("PULSE_MFB_PREBAND_TOP_BANDS", 32) or 32),
            "mfb_preband_lines_per_band": int(state.get("PULSE_MFB_PREBAND_LINES_PER_BAND", 4) or 4),
            "mfb_preband_band_slots": int(state.get("PULSE_MFB_PREBAND_BAND_SLOTS", 0) or 0),
            "mfb_preband_window_budget": int(
                state.get("PULSE_MFB_PREBAND_WINDOW_BUDGET", 0) or 0
            ),
            "mfb_gather_preband_enable": int(
                state.get("PULSE_MFB_GATHER_PREBAND_ENABLE", 0) or 0
            ),
            "mfb_gather_barrier_enable": int(
                state.get("PULSE_MFB_GATHER_BARRIER_ENABLE", 0) or 0
            ),
            "mfb_gather_top_bands": int(state.get("PULSE_MFB_GATHER_TOP_BANDS", 32) or 32),
            "mfb_gather_lines_per_band": int(
                state.get("PULSE_MFB_GATHER_LINES_PER_BAND", 4) or 4
            ),
            "mfb_gather_min_consumers": int(
                state.get("PULSE_MFB_GATHER_MIN_CONSUMERS", 2) or 2
            ),
            "mfb_gather_window_budget": int(
                state.get("PULSE_MFB_GATHER_WINDOW_BUDGET", 0) or 0
            ),
            "prebase_shared_lookup_enable": int(
                state.get("PULSE_PREBASE_SHARED_LOOKUP_ENABLE", 0) or 0
            ),
            "osa_enable": int(state.get("PULSE_OSA_ENABLE", 0) or 0),
            "osa_shared_weight_owner_enable": int(
                state.get("PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE", 0) or 0
            ),
            "osa_shared_weight_owner_actual_enable": int(
                state.get("PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE", 0) or 0
            ),
            "osa_metadata_txn_enable": int(
                state.get("PULSE_OSA_METADATA_TXN_ENABLE", 0) or 0
            ),
            "osa_metadata_ready_lease_enable": int(
                state.get("PULSE_OSA_METADATA_READY_LEASE_ENABLE", 0) or 0
            ),
            "osa_metadata_ready_lease_ttl": int(
                state.get("PULSE_OSA_METADATA_READY_LEASE_TTL", 0) or 0
            ),
            "osa_metadata_object_mask": str(
                state.get("PULSE_OSA_METADATA_OBJECT_MASK", "") or ""
            ),
            "ingress_entries": int(state.get("PULSE_INGRESS_ENTRIES", 0) or 0),
            "core_queue_entries": int(state.get("PULSE_CORE_QUEUE_ENTRIES", 0) or 0),
            "descriptor_packet_min": int(state.get("PULSE_DESCRIPTOR_PACKET_MIN", 2) or 2),
            "bypass_high_watermark_pct": int(state.get("PULSE_BYPASS_HIGH_WATERMARK_PCT", 100) or 100),
            "bypass_mode": str(state.get("PULSE_BYPASS_MODE", "disabled") or "disabled"),
        },
        "thermal": _build_thermal_cfg(state),
        "sram": _build_sram_cfg(state, script_dir=script_dir),
    }
    if state.get("MAX_OUTSTANDING_REQUESTS_OVERRIDE") is not None:
        mesh_cfg["max_outstanding_requests"] = int(state.get("MAX_OUTSTANDING_REQUESTS_OVERRIDE"))
    if state.get("WINDOW_READ_BUDGET_OVERRIDE") is not None:
        mesh_cfg["window_read_budget"] = int(state.get("WINDOW_READ_BUDGET_OVERRIDE"))
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
    if "RAMULATOR2_ADMISSION_QUEUE_SIZE" in state:
        mem_layout_cfg["ramulator2_admission_queue_size"] = int(state.get("RAMULATOR2_ADMISSION_QUEUE_SIZE", 0))
    if "RAMULATOR2_ADMISSION_ISSUE_BUDGET_PER_CYCLE" in state:
        mem_layout_cfg["ramulator2_admission_issue_budget_per_cycle"] = int(
            state.get("RAMULATOR2_ADMISSION_ISSUE_BUDGET_PER_CYCLE", -1)
        )
    if "RAMULATOR2_MAX_REQUESTS_PER_CYCLE" in state:
        mem_layout_cfg["ramulator2_max_requests_per_cycle"] = int(state.get("RAMULATOR2_MAX_REQUESTS_PER_CYCLE", -1))

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
