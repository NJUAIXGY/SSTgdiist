from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from .utils import mesh_print, mesh_quiet


def load_local_run_config(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def apply_local_run_config_overrides(
    cfg: Dict[str, Any],
    *,
    state: Dict[str, Any],
    script_dir: str,
    default_stats_level: int,
    gas_merge_env_present: bool,
    gas_inflight_env_present: bool,
    gas_sort_env_present: bool = False,
    gas_row_bytes_env_present: bool = False,
    gas_bank_env_present: bool = False,
    gas_apply_policy_env_present: bool = False,
    gas_apply_frags_env_present: bool = False,
    gas_apply_credit_env_present: bool = False,
    gas_apply_age_env_present: bool = False,
) -> Optional[int]:
    """
    Apply overrides from local_run_config.json onto `state`.

    Notes:
    - Keeps env priority for GAS merge/inflight (env wins over local_run_config.json).
    - Keeps env priority for GAS sort/row_bytes/bank mapping knobs.
    - Returns an optional stats load level override (int) for caller to apply via SST.
    """

    def _maybe_int(val: Any, current: Any) -> Any:
        if val is None:
            return current
        try:
            return int(val)
        except Exception:
            return current

    stats_level_override: Optional[int] = None

    # Core toggles
    state["SINGLE_BUS_MODE"] = bool(cfg.get("use_single_bus", state.get("SINGLE_BUS_MODE", True)))
    state["DEBUG_CONN"] = bool(cfg.get("debug_conn", state.get("DEBUG_CONN", False)))
    state["USE_SOA_STATE"] = 1 if bool(cfg.get("use_soa", state.get("USE_SOA_STATE", 0))) else 0
    state["VERIFY_ROUTING"] = 1 if bool(cfg.get("verify_routing", state.get("VERIFY_ROUTING", 0))) else 0

    # AoSoA
    _ua = cfg.get("use_aosoa")
    if _ua is not None:
        state["USE_AOSOA_STATE"] = 1 if bool(_ua) else 0
    _abr = cfg.get("aosoa_block_rows")
    if _abr is not None:
        try:
            state["AOSOA_BLOCK_ROWS"] = int(_abr)
        except Exception:
            pass

    # Synapse format / routing knobs
    _syn = cfg.get("synapse_format")
    if isinstance(_syn, str) and _syn.strip():
        state["SYNAPSE_FORMAT_ENV"] = _syn.strip().lower()
    _fd = cfg.get("force_dense")
    if _fd is not None:
        state["FORCE_DENSE"] = bool(_fd)
    _auto = cfg.get("bcsr_auto_detect")
    if _auto is not None:
        state["AUTO_BCSR_DETECT"] = bool(_auto)
    _eps = cfg.get("routing_epsilon")
    if _eps is not None:
        try:
            state["ROUT_EPS"] = float(_eps)
        except Exception:
            pass
    _tkpp = cfg.get("routing_topk_per_pe")
    if _tkpp is not None:
        try:
            state["ROUT_TOPK_PER_PE"] = int(_tkpp)
        except Exception:
            pass
    _tk = cfg.get("routing_topk")
    if _tk is not None:
        try:
            state["ROUT_TOPK"] = int(_tk)
        except Exception:
            pass

    # Statistics level (caller applies via sst.setStatisticLoadLevel)
    _sv = cfg.get("stats_verbose")
    if _sv is not None:
        try:
            stats_level_override = int(_sv)
        except Exception:
            stats_level_override = int(default_stats_level)

    # GAS merge knobs (fine/coarse merge). These map onto the legacy state keys consumed by mesh_template/runtime.py.
    # Note: merge_policy/max_inflight are still env-priority and handled separately.
    _gk = cfg.get("gap_merge_k_bytes")
    if _gk is not None:
        try:
            state["_GAS_GAP_K_BYTES"] = int(_gk)
        except Exception:
            pass

    _lmax = cfg.get("burst_bytes_max")
    if _lmax is not None:
        try:
            state["_GAS_LMAX_BYTES"] = int(_lmax)
        except Exception:
            pass

    _rwb = cfg.get("row_window_bytes")
    if _rwb is not None:
        try:
            state["_GAS_ROW_WINDOW_BYTES"] = int(_rwb)
        except Exception:
            pass

    _rwt = cfg.get("row_window_timeout_ns")
    if _rwt is not None:
        try:
            state["_GAS_ROW_WINDOW_TIMEOUT_NS"] = int(_rwt)
        except Exception:
            pass

    # Membrane tau (default 20.0 when config file exists, to keep legacy semantics)
    _tau = cfg.get("tau_mem")
    state["CORE_TAU_MEM"] = 20.0
    if _tau is not None:
        try:
            state["CORE_TAU_MEM"] = float(_tau)
        except Exception:
            state["CORE_TAU_MEM"] = 20.0

    # Output / injection flags
    _ens = cfg.get("enable_node_summary")
    if _ens is not None:
        state["ENABLE_NODE_SUMMARY"] = bool(_ens)
    _ess = cfg.get("enable_spike_source")
    if _ess is not None:
        state["ENABLE_SPIKE_SOURCE_FLAG"] = bool(_ess)
    _ett = cfg.get("enable_test_traffic")
    if _ett is not None:
        state["ENABLE_TEST_TRAFFIC"] = bool(_ett)
    _dn = cfg.get("disable_network")
    if _dn is not None:
        state["DISABLE_NETWORK"] = bool(_dn)
    _exps = cfg.get("export_spike_csv")
    if _exps is not None:
        state["EXPORT_SPIKE_CSV"] = bool(_exps)
    _dfl = cfg.get("diag_fire_log")
    if _dfl is not None:
        state["DIAG_FIRE_LOG"] = bool(_dfl)

    # recordEdge gates
    _rea = cfg.get("record_edge_apply_enable")
    if _rea is not None:
        state["RECORD_EDGE_APPLY_ENABLE"] = 1 if bool(_rea) else 0
    _rei = cfg.get("record_edge_idle_enable")
    if _rei is not None:
        state["RECORD_EDGE_IDLE_ENABLE"] = 1 if bool(_rei) else 0
    _res = cfg.get("record_edge_scatter_enable")
    if _res is not None:
        state["RECORD_EDGE_SCATTER_ENABLE"] = 1 if bool(_res) else 0

    # Step random activation & BCSR routes
    _sra = cfg.get("step_random_activation_enable")
    if _sra is not None:
        state["STEP_RANDOM_ACT_ENABLE"] = 1 if bool(_sra) else 0
    _saf = cfg.get("step_activation_fraction")
    if _saf is not None:
        try:
            state["STEP_ACTIVATION_FRACTION"] = float(_saf)
        except Exception:
            pass
    _sfan = cfg.get("step_activation_fanout")
    if _sfan is not None:
        try:
            state["STEP_ACTIVATION_FANOUT"] = int(_sfan)
        except Exception:
            pass
    _sseed = cfg.get("step_activation_seed")
    if _sseed is not None:
        try:
            state["STEP_ACTIVATION_SEED"] = int(_sseed)
        except Exception:
            pass
    _spc = cfg.get("step_activation_period_cycles")
    if _spc is not None:
        try:
            state["STEP_ACTIVATION_PERIOD_CYCLES"] = int(_spc)
        except Exception:
            pass
    _satc = cfg.get("step_activation_trigger_core")
    if _satc is not None:
        try:
            state["STEP_ACTIVATION_TRIGGER_CORE"] = int(_satc)
        except Exception:
            pass
    _sev = cfg.get("step_activation_event_weight")
    if _sev is not None:
        try:
            state["STEP_ACTIVATION_EVENT_WEIGHT"] = float(_sev)
        except Exception:
            pass
    _pp = cfg.get("step_activation_pre_pattern")
    if isinstance(_pp, str) and _pp.strip():
        state["STEP_ACTIVATION_PRE_PATTERN"] = _pp.strip().lower()
    _pcl = cfg.get("step_activation_pre_cluster_len")
    if _pcl is not None:
        try:
            state["STEP_ACTIVATION_PRE_CLUSTER_LEN"] = int(_pcl)
        except Exception:
            pass
    _suse = cfg.get("step_activation_use_bcsr_routes")
    if _suse is not None:
        state["STEP_ACTIVATION_USE_BCSR_ROUTES"] = 1 if bool(_suse) else 0
    _sreset = cfg.get("step_reset_mem_each_step")
    if _sreset is not None:
        state["STEP_RESET_MEM_EACH_STEP"] = 1 if bool(_sreset) else 0
    _sbcsr_eps = cfg.get("step_activation_bcsr_weight_epsilon")
    if _sbcsr_eps is not None:
        try:
            state["STEP_ACTIVATION_BCSR_WEIGHT_EPS"] = float(_sbcsr_eps)
        except Exception:
            pass
    _tmpl = cfg.get("step_activation_bcsr_template")
    if isinstance(_tmpl, str) and _tmpl.strip():
        tmpl = _tmpl.strip()
        if not os.path.isabs(tmpl):
            tmpl = os.path.join(script_dir, tmpl)
        state["STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE"] = tmpl

    def _resolve_path_under_project(raw_path: str) -> str:
        p = (raw_path or "").strip()
        if not p:
            return ""
        if os.path.isabs(p):
            return p
        # Prefer relative to script_dir (sst_dram_si/), but tolerate "sst_dram_si/..." repo-relative inputs.
        cand = os.path.join(script_dir, p)
        if os.path.exists(cand):
            return cand
        if p.startswith("sst_dram_si/"):
            cand2 = os.path.join(script_dir, p[len("sst_dram_si/"):])
            if os.path.exists(cand2):
                return cand2
        return cand

    # Memory backend (MemController backend selection).
    _mb = cfg.get("mem_backend")
    if isinstance(_mb, str) and _mb.strip():
        v = _mb.strip().lower()
        if v in ("simple", "simplemem", "simple_mem"):
            v = "simple"
        elif v in ("ramulator2", "ram2"):
            v = "ramulator2"
        else:
            mesh_print(f"[mesh] ignore invalid local_run_config.json mem_backend={v!r} (expected simple/ramulator2)")
            v = ""
        if v:
            state["MEM_BACKEND"] = v

    _r2cfg = cfg.get("ramulator2_config_file")
    if isinstance(_r2cfg, str) and _r2cfg.strip():
        state["RAMULATOR2_CONFIG_FILE"] = _resolve_path_under_project(_r2cfg)

    _smat = cfg.get("simplemem_access_time")
    if isinstance(_smat, str) and _smat.strip():
        state["SIMPLEMEM_ACCESS_TIME"] = _smat.strip()

    _bcsr_fetch_mode = cfg.get("bcsr_block_fetch_mode")
    if isinstance(_bcsr_fetch_mode, str) and _bcsr_fetch_mode.strip():
        v = _bcsr_fetch_mode.strip().lower()
        if v not in ("full_block", "row_cacheline"):
            mesh_print(
                f"[mesh] ignore invalid local_run_config.json bcsr_block_fetch_mode={v!r} "
                "(expected full_block/row_cacheline)"
            )
        else:
            state["BCSR_BLOCK_FETCH_MODE"] = v

    # Env overrides (priority: env > local_run_config.json) for experiment sweeps.
    # We keep them opt-in via MESH_* names to avoid surprising default runs.
    _env_frac = os.environ.get("MESH_STEP_ACTIVATION_FRACTION", "").strip()
    if _env_frac:
        try:
            state["STEP_ACTIVATION_FRACTION"] = float(_env_frac)
            mesh_print(f"[mesh] override STEP_ACTIVATION_FRACTION={state['STEP_ACTIVATION_FRACTION']} via MESH_STEP_ACTIVATION_FRACTION={_env_frac}")
        except Exception:
            pass
    _env_fan = os.environ.get("MESH_STEP_ACTIVATION_FANOUT", "").strip()
    if _env_fan:
        try:
            state["STEP_ACTIVATION_FANOUT"] = int(_env_fan)
            mesh_print(f"[mesh] override STEP_ACTIVATION_FANOUT={state['STEP_ACTIVATION_FANOUT']} via MESH_STEP_ACTIVATION_FANOUT={_env_fan}")
        except Exception:
            pass
    _env_seed = os.environ.get("MESH_STEP_ACTIVATION_SEED", "").strip()
    if _env_seed:
        try:
            state["STEP_ACTIVATION_SEED"] = int(_env_seed)
            mesh_print(f"[mesh] override STEP_ACTIVATION_SEED={state['STEP_ACTIVATION_SEED']} via MESH_STEP_ACTIVATION_SEED={_env_seed}")
        except Exception:
            pass
    _env_ew = os.environ.get("MESH_STEP_ACTIVATION_EVENT_WEIGHT", "").strip()
    if _env_ew:
        try:
            state["STEP_ACTIVATION_EVENT_WEIGHT"] = float(_env_ew)
            mesh_print(f"[mesh] override STEP_ACTIVATION_EVENT_WEIGHT={state['STEP_ACTIVATION_EVENT_WEIGHT']} via MESH_STEP_ACTIVATION_EVENT_WEIGHT={_env_ew}")
        except Exception:
            pass
    _env_pp = os.environ.get("MESH_STEP_ACTIVATION_PRE_PATTERN", "").strip()
    if _env_pp:
        state["STEP_ACTIVATION_PRE_PATTERN"] = _env_pp.strip().lower()
        mesh_print(f"[mesh] override STEP_ACTIVATION_PRE_PATTERN={state['STEP_ACTIVATION_PRE_PATTERN']} via MESH_STEP_ACTIVATION_PRE_PATTERN={_env_pp}")
    _env_pcl = os.environ.get("MESH_STEP_ACTIVATION_PRE_CLUSTER_LEN", "").strip()
    if _env_pcl:
        try:
            state["STEP_ACTIVATION_PRE_CLUSTER_LEN"] = int(_env_pcl)
            mesh_print(f"[mesh] override STEP_ACTIVATION_PRE_CLUSTER_LEN={state['STEP_ACTIVATION_PRE_CLUSTER_LEN']} via MESH_STEP_ACTIVATION_PRE_CLUSTER_LEN={_env_pcl}")
        except Exception:
            pass
    _env_reset = os.environ.get("MESH_STEP_RESET_MEM_EACH_STEP", "").strip().lower()
    if _env_reset:
        if _env_reset in ("1", "true", "yes", "y", "on"):
            state["STEP_RESET_MEM_EACH_STEP"] = 1
            mesh_print(f"[mesh] override STEP_RESET_MEM_EACH_STEP=1 via MESH_STEP_RESET_MEM_EACH_STEP={_env_reset}")
        elif _env_reset in ("0", "false", "no", "n", "off"):
            state["STEP_RESET_MEM_EACH_STEP"] = 0
            mesh_print(f"[mesh] override STEP_RESET_MEM_EACH_STEP=0 via MESH_STEP_RESET_MEM_EACH_STEP={_env_reset}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_STEP_RESET_MEM_EACH_STEP={_env_reset!r} (expected 0/1/true/false)")
    _env_gsv = os.environ.get("MESH_GLOBAL_STEP_CTRL_VERBOSE", "").strip()
    if _env_gsv:
        try:
            state["GLOBAL_STEP_CTRL_VERBOSE"] = int(_env_gsv)
            mesh_print(f"[mesh] override GLOBAL_STEP_CTRL_VERBOSE={state['GLOBAL_STEP_CTRL_VERBOSE']} via MESH_GLOBAL_STEP_CTRL_VERBOSE={_env_gsv}")
        except Exception:
            pass

    # Memory backend env override (priority: env > local_run_config.json).
    _env_mb = os.environ.get("MESH_MEM_BACKEND", "").strip().lower()
    if _env_mb:
        v = _env_mb
        if v in ("simple", "simplemem", "simple_mem"):
            v = "simple"
        elif v in ("ramulator2", "ram2"):
            v = "ramulator2"
        else:
            mesh_print(f"[mesh] ignore invalid MESH_MEM_BACKEND={_env_mb!r} (expected simple/ramulator2)")
            v = ""
        if v:
            state["MEM_BACKEND"] = v
            mesh_print(f"[mesh] override MEM_BACKEND={state['MEM_BACKEND']} via MESH_MEM_BACKEND={_env_mb}")

    _env_r2 = os.environ.get("MESH_RAMULATOR2_CONFIG_FILE", "").strip()
    if _env_r2:
        state["RAMULATOR2_CONFIG_FILE"] = _resolve_path_under_project(_env_r2)
        mesh_print(f"[mesh] override RAMULATOR2_CONFIG_FILE={state['RAMULATOR2_CONFIG_FILE']} via MESH_RAMULATOR2_CONFIG_FILE={_env_r2}")

    _env_smat = os.environ.get("MESH_SIMPLEMEM_ACCESS_TIME", "").strip()
    if _env_smat:
        state["SIMPLEMEM_ACCESS_TIME"] = _env_smat
        mesh_print(f"[mesh] override SIMPLEMEM_ACCESS_TIME={state['SIMPLEMEM_ACCESS_TIME']} via MESH_SIMPLEMEM_ACCESS_TIME={_env_smat}")

    _env_bcsr_fetch_mode = os.environ.get("MESH_BCSR_BLOCK_FETCH_MODE", "").strip().lower()
    if _env_bcsr_fetch_mode:
        if _env_bcsr_fetch_mode in ("full_block", "row_cacheline"):
            state["BCSR_BLOCK_FETCH_MODE"] = _env_bcsr_fetch_mode
            mesh_print(
                f"[mesh] override BCSR_BLOCK_FETCH_MODE={state['BCSR_BLOCK_FETCH_MODE']} "
                f"via MESH_BCSR_BLOCK_FETCH_MODE={_env_bcsr_fetch_mode}"
            )
        else:
            mesh_print(
                f"[mesh] ignore invalid MESH_BCSR_BLOCK_FETCH_MODE={_env_bcsr_fetch_mode!r} "
                "(expected full_block/row_cacheline)"
            )

    _env_loader_chunk = os.environ.get("MESH_LOADER_CHUNK_BYTES", "").strip()
    if _env_loader_chunk:
        try:
            _v = int(_env_loader_chunk)
            if _v > 0:
                state["LOADER_CHUNK_BYTES"] = _v
                mesh_print(
                    f"[mesh] override LOADER_CHUNK_BYTES={state['LOADER_CHUNK_BYTES']} "
                    f"via MESH_LOADER_CHUNK_BYTES={_env_loader_chunk}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_LOADER_CHUNK_BYTES={_env_loader_chunk!r} (expected >0)"
                )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid MESH_LOADER_CHUNK_BYTES={_env_loader_chunk!r} (expected int)"
            )

    # GAS fine/coarse merge knob env overrides (priority: env > local_run_config.json).
    _env_gk = os.environ.get("MESH_GAS_GAP_K_BYTES", "").strip()
    if _env_gk:
        try:
            state["_GAS_GAP_K_BYTES"] = int(_env_gk)
            mesh_print(f"[mesh] override GAS gap_merge_k_bytes={state['_GAS_GAP_K_BYTES']} via MESH_GAS_GAP_K_BYTES={_env_gk}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_GAP_K_BYTES={_env_gk!r} (expected int)")

    _env_lmax = os.environ.get("MESH_GAS_LMAX_BYTES", "").strip()
    if _env_lmax:
        try:
            state["_GAS_LMAX_BYTES"] = int(_env_lmax)
            mesh_print(f"[mesh] override GAS burst_bytes_max={state['_GAS_LMAX_BYTES']} via MESH_GAS_LMAX_BYTES={_env_lmax}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_LMAX_BYTES={_env_lmax!r} (expected int)")

    _env_rwb = os.environ.get("MESH_GAS_ROW_WINDOW_BYTES", "").strip()
    if _env_rwb:
        try:
            state["_GAS_ROW_WINDOW_BYTES"] = int(_env_rwb)
            mesh_print(f"[mesh] override GAS row_window_bytes={state['_GAS_ROW_WINDOW_BYTES']} via MESH_GAS_ROW_WINDOW_BYTES={_env_rwb}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_ROW_WINDOW_BYTES={_env_rwb!r} (expected int)")

    _env_rwt = os.environ.get("MESH_GAS_ROW_WINDOW_TIMEOUT_NS", "").strip()
    if _env_rwt:
        try:
            state["_GAS_ROW_WINDOW_TIMEOUT_NS"] = int(_env_rwt)
            mesh_print(f"[mesh] override GAS row_window_timeout_ns={state['_GAS_ROW_WINDOW_TIMEOUT_NS']} via MESH_GAS_ROW_WINDOW_TIMEOUT_NS={_env_rwt}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_ROW_WINDOW_TIMEOUT_NS={_env_rwt!r} (expected int)")

    # Cache hierarchy env override (priority: env > local_run_config.json).
    # This is useful for experiment matrices where we want to sweep L1 on/off
    # without mutating local_run_config.json between runs.
    _env_l1 = os.environ.get("MESH_L1_ENABLE", "").strip().lower()
    l1_env_applied = False
    if _env_l1:
        if _env_l1 in ("1", "true", "yes", "y", "on"):
            state["L1_ENABLE"] = True
            l1_env_applied = True
            mesh_print(f"[mesh] override L1_ENABLE=1 via MESH_L1_ENABLE={_env_l1}")
        elif _env_l1 in ("0", "false", "no", "n", "off"):
            state["L1_ENABLE"] = False
            l1_env_applied = True
            mesh_print(f"[mesh] override L1_ENABLE=0 via MESH_L1_ENABLE={_env_l1}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_L1_ENABLE={_env_l1!r} (expected 0/1/true/false)")

    # Conflict detection: SpikeSource vs Step Random Activation vs Test Traffic
    _allow_hybrid = bool(cfg.get("allow_injection_hybrid", False))
    if state.get("STEP_RANDOM_ACT_ENABLE", 0) and state.get("ENABLE_SPIKE_SOURCE_FLAG", False) and not _allow_hybrid:
        mesh_print("⚠️ 检测到随机发放(step_random_activation)与SpikeSource同时启用，默认优先随机发放，禁用SpikeSource（可通过 allow_injection_hybrid 开启共存）")
        state["ENABLE_SPIKE_SOURCE_FLAG"] = False
    if state.get("STEP_RANDOM_ACT_ENABLE", 0) and state.get("ENABLE_TEST_TRAFFIC", False) and not _allow_hybrid:
        mesh_print("⚠️ 检测到随机发放(step_random_activation)与NoC测试流量同时启用，默认禁用测试流量")
        state["ENABLE_TEST_TRAFFIC"] = False

    state["STEP_ACTIVATION_BCSR_ROWPTR_OFFSET"] = _maybe_int(
        cfg.get("step_activation_bcsr_rowptr_offset"),
        state.get("STEP_ACTIVATION_BCSR_ROWPTR_OFFSET"),
    )
    state["STEP_ACTIVATION_BCSR_COLIDX_OFFSET"] = _maybe_int(
        cfg.get("step_activation_bcsr_colidx_offset"),
        state.get("STEP_ACTIVATION_BCSR_COLIDX_OFFSET"),
    )
    state["STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET"] = _maybe_int(
        cfg.get("step_activation_bcsr_blockdata_offset"),
        state.get("STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET"),
    )
    state["STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET"] = _maybe_int(
        cfg.get("step_activation_bcsr_blockids_offset"),
        state.get("STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET"),
    )
    state["STEP_ACTIVATION_BCSR_BR"] = _maybe_int(
        cfg.get("step_activation_bcsr_br"),
        state.get("STEP_ACTIVATION_BCSR_BR"),
    )
    state["STEP_ACTIVATION_BCSR_BC"] = _maybe_int(
        cfg.get("step_activation_bcsr_bc"),
        state.get("STEP_ACTIVATION_BCSR_BC"),
    )
    state["STEP_ACTIVATION_BCSR_IDX_BYTES"] = _maybe_int(
        cfg.get("step_activation_bcsr_idx_bytes"),
        state.get("STEP_ACTIVATION_BCSR_IDX_BYTES"),
    )
    state["STEP_ACTIVATION_BCSR_VAL_BYTES"] = _maybe_int(
        cfg.get("step_activation_bcsr_val_bytes"),
        state.get("STEP_ACTIVATION_BCSR_VAL_BYTES"),
    )

    # Component verbose mapping (fallback to stats_verbose if present, else 0)
    _core_v = cfg.get("core_verbose")
    _node_v = cfg.get("node_verbose")
    _loader_v = cfg.get("loader_verbose")
    state["CORE_VERBOSE"] = int(_core_v) if _core_v is not None else (int(_sv) if _sv is not None else 0)
    state["NODE_VERBOSE"] = int(_node_v) if _node_v is not None else (int(_sv) if _sv is not None else 0)
    state["LOADER_VERBOSE"] = int(_loader_v) if _loader_v is not None else 0

    # Debug & progress logging (optional)
    state["SENTINEL_ENABLE"] = bool(cfg.get("sentinel_enable", 0))
    try:
        state["PROGRESS_LOG_INTERVAL_NS"] = int(cfg.get("progress_log_interval_ns", 0) or 0)
    except Exception:
        state["PROGRESS_LOG_INTERVAL_NS"] = 0
    try:
        state["PROGRESS_LOG_NODE"] = int(cfg.get("progress_log_node", -1) if cfg.get("progress_log_node", -1) is not None else -1)
    except Exception:
        state["PROGRESS_LOG_NODE"] = -1

    # Global step sync toggles
    _gss = cfg.get("global_step_sync_enable")
    if _gss is not None:
        state["GLOBAL_STEP_SYNC_ENABLE"] = bool(_gss)
    _gsv = cfg.get("global_step_ctrl_verbose")
    if _gsv is not None:
        try:
            state["GLOBAL_STEP_CTRL_VERBOSE"] = int(_gsv)
        except Exception:
            state["GLOBAL_STEP_CTRL_VERBOSE"] = 0

    # Paper-grade quiet mode: MESH_QUIET=1 should suppress all debug/log spam by default.
    # This must override local_run_config.json debug knobs to keep matrix runs stable and fast.
    if mesh_quiet():
        state["SENTINEL_ENABLE"] = False
        state["PROGRESS_LOG_INTERVAL_NS"] = 0
        state["PROGRESS_LOG_NODE"] = -1
        state["GLOBAL_STEP_CTRL_VERBOSE"] = 0
        state["NODE_VERBOSE"] = 0
        state["CORE_VERBOSE"] = 0
        state["LOADER_VERBOSE"] = 0

    # window_read_debug gating (optional)
    state["WINDOW_READ_DEBUG_ALL"] = bool(cfg.get("window_read_debug_all_cores", 0))
    state["DEBUG_TARGET_PE"] = int(cfg.get("debug_target_pe", 0) if cfg.get("debug_target_pe", 0) is not None else 0)
    state["DEBUG_TARGET_CORE"] = int(cfg.get("debug_target_core", 0) if cfg.get("debug_target_core", 0) is not None else 0)

    # GAS tuning (priority: env > local_run_config.json)
    _gmp = cfg.get("gas_merge_policy")
    if (not gas_merge_env_present) and isinstance(_gmp, str) and _gmp.strip():
        _v = _gmp.strip().lower()
        if _v in ("auto", "row", "cacheline", "none"):
            state["_GAS_MERGE_POLICY"] = _v
            mesh_print(f"[mesh] override GAS merge_policy={state['_GAS_MERGE_POLICY']} via local_run_config.json gas_merge_policy={_gmp}")

    _gmi = cfg.get("gas_max_inflight")
    if (not gas_inflight_env_present) and _gmi is not None:
        try:
            _v = int(_gmi)
            if _v > 0:
                state["_GAS_MAX_INFLIGHT"] = _v
                mesh_print(f"[mesh] override GAS max_inflight_reads={state['_GAS_MAX_INFLIGHT']} via local_run_config.json gas_max_inflight={_gmi}")
        except Exception:
            pass

    _gsp = cfg.get("gas_sort_policy")
    if (not gas_sort_env_present) and isinstance(_gsp, str) and _gsp.strip():
        _v = _gsp.strip().lower()
        if _v in ("addr", "row", "bank_row"):
            state["_GAS_SORT_POLICY"] = _v
            mesh_print(f"[mesh] override GAS sort_policy={state['_GAS_SORT_POLICY']} via local_run_config.json gas_sort_policy={_gsp}")
        else:
            mesh_print(f"[mesh] ignore invalid local_run_config.json gas_sort_policy={_gsp!r} (expected addr/row/bank_row)")

    _grbg = cfg.get("gas_row_bytes_guess")
    if (not gas_row_bytes_env_present) and _grbg is not None:
        try:
            _v = int(_grbg)
            if _v > 0:
                state["_GAS_ROW_BYTES_GUESS"] = _v
                mesh_print(f"[mesh] override GAS row_bytes_guess={state['_GAS_ROW_BYTES_GUESS']} via local_run_config.json gas_row_bytes_guess={_grbg}")
        except Exception:
            pass

    if not gas_bank_env_present:
        _gbb = cfg.get("gas_bank_bits")
        if _gbb is not None:
            try:
                _v = int(_gbb)
                if _v >= 0:
                    state["_GAS_BANK_BITS"] = _v
                    mesh_print(f"[mesh] override GAS bank_bits={state['_GAS_BANK_BITS']} via local_run_config.json gas_bank_bits={_gbb}")
            except Exception:
                pass
        _gbs = cfg.get("gas_bank_shift")
        if _gbs is not None:
            try:
                _v = int(_gbs)
                if _v >= 0:
                    state["_GAS_BANK_SHIFT"] = _v
                    mesh_print(f"[mesh] override GAS bank_shift={state['_GAS_BANK_SHIFT']} via local_run_config.json gas_bank_shift={_gbs}")
            except Exception:
                pass
        _gba = cfg.get("gas_bank_auto_enable")
        if _gba is not None:
            state["_GAS_BANK_AUTO_ENABLE"] = 1 if bool(_gba) else 0
            mesh_print(f"[mesh] override GAS bank_auto_enable={state['_GAS_BANK_AUTO_ENABLE']} via local_run_config.json gas_bank_auto_enable={_gba}")

    # GAS Apply issue scheduling (priority: env > local_run_config.json)
    experimental_enable = (os.environ.get("MESH_EXPERIMENTAL_ENABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
    )
    if experimental_enable:
        _gaip = cfg.get("gas_apply_issue_policy")
        if (not gas_apply_policy_env_present) and isinstance(_gaip, str) and _gaip.strip():
            _v = _gaip.strip().lower()
            if _v in ("order", "bank_rr_row_sticky_age", "dram_aware_v1"):
                state["_GAS_APPLY_ISSUE_POLICY"] = _v
                mesh_print(
                    f"[mesh] override GAS apply_issue_policy={state['_GAS_APPLY_ISSUE_POLICY']} via local_run_config.json gas_apply_issue_policy={_gaip}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid local_run_config.json gas_apply_issue_policy={_gaip!r} (expected order/bank_rr_row_sticky_age/dram_aware_v1)"
                )

        _gafr = cfg.get("gas_apply_frags_per_issue")
        if (not gas_apply_frags_env_present) and _gafr is not None:
            try:
                _v = int(_gafr)
                if _v >= 0:
                    state["_GAS_APPLY_FRAGS_PER_ISSUE"] = _v
                    mesh_print(
                        f"[mesh] override GAS apply_frags_per_issue={state['_GAS_APPLY_FRAGS_PER_ISSUE']} via local_run_config.json gas_apply_frags_per_issue={_gafr}"
                    )
            except Exception:
                pass

        _gabc = cfg.get("gas_apply_bank_credit")
        if (not gas_apply_credit_env_present) and _gabc is not None:
            try:
                _v = int(_gabc)
                if _v >= 0:
                    state["_GAS_APPLY_BANK_CREDIT"] = _v
                    mesh_print(
                        f"[mesh] override GAS apply_bank_credit={state['_GAS_APPLY_BANK_CREDIT']} via local_run_config.json gas_apply_bank_credit={_gabc}"
                    )
            except Exception:
                pass

        _gaaf = cfg.get("gas_apply_age_fair_ns")
        if (not gas_apply_age_env_present) and _gaaf is not None:
            try:
                _v = int(_gaaf)
                if _v >= 0:
                    state["_GAS_APPLY_AGE_FAIR_NS"] = _v
                    mesh_print(
                        f"[mesh] override GAS apply_age_fair_ns={state['_GAS_APPLY_AGE_FAIR_NS']} via local_run_config.json gas_apply_age_fair_ns={_gaaf}"
                    )
            except Exception:
                pass

        # DRAM-aware Apply knobs (optional; only meaningful when apply_issue_policy=dram_aware_v1)
        _v = cfg.get("gas_dram_row_bytes")
        if _v is not None:
            try:
                state["_GAS_DRAM_ROW_BYTES"] = int(_v)
                mesh_print(f"[mesh] override GAS dram_row_bytes={state['_GAS_DRAM_ROW_BYTES']} via local_run_config.json gas_dram_row_bytes={_v}")
            except Exception:
                pass
        _v = cfg.get("gas_dram_bank_count")
        if _v is not None:
            try:
                state["_GAS_DRAM_BANK_COUNT"] = int(_v)
                mesh_print(f"[mesh] override GAS dram_bank_count={state['_GAS_DRAM_BANK_COUNT']} via local_run_config.json gas_dram_bank_count={_v}")
            except Exception:
                pass
        _v = cfg.get("gas_dram_read_burst_bytes")
        if _v is not None:
            try:
                state["_GAS_DRAM_READ_BURST_BYTES"] = int(_v)
                mesh_print(f"[mesh] override GAS dram_read_burst_bytes={state['_GAS_DRAM_READ_BURST_BYTES']} via local_run_config.json gas_dram_read_burst_bytes={_v}")
            except Exception:
                pass
        _v = cfg.get("gas_dram_row_miss_penalty_cycles")
        if _v is not None:
            try:
                state["_GAS_DRAM_ROW_MISS_PENALTY_CYCLES"] = int(_v)
                mesh_print(
                    f"[mesh] override GAS dram_row_miss_penalty_cycles={state['_GAS_DRAM_ROW_MISS_PENALTY_CYCLES']} via local_run_config.json gas_dram_row_miss_penalty_cycles={_v}"
                )
            except Exception:
                pass
        _v = cfg.get("gas_dram_overfetch_budget_bytes")
        if _v is not None:
            try:
                state["_GAS_DRAM_OVERFETCH_BUDGET_BYTES"] = int(_v)
                mesh_print(
                    f"[mesh] override GAS dram_overfetch_budget_bytes={state['_GAS_DRAM_OVERFETCH_BUDGET_BYTES']} via local_run_config.json gas_dram_overfetch_budget_bytes={_v}"
                )
            except Exception:
                pass
        _v = cfg.get("gas_dram_aware_enable_row_window")
        if _v is not None:
            state["_GAS_DRAM_AWARE_ENABLE_ROWWIN"] = 1 if bool(_v) else 0
            mesh_print(
                f"[mesh] override GAS dram_aware_enable_row_window={state['_GAS_DRAM_AWARE_ENABLE_ROWWIN']} via local_run_config.json gas_dram_aware_enable_row_window={_v}"
            )
        _v = cfg.get("gas_dram_aware_k_policy")
        if isinstance(_v, str) and _v.strip():
            _p = _v.strip().lower()
            if _p in ("fixed", "cost_budgeted", "density_budgeted"):
                state["_GAS_DRAM_AWARE_K_POLICY"] = _p
                mesh_print(
                    f"[mesh] override GAS dram_aware_k_policy={state['_GAS_DRAM_AWARE_K_POLICY']} via local_run_config.json gas_dram_aware_k_policy={_v}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid local_run_config.json gas_dram_aware_k_policy={_v!r} (expected fixed/cost_budgeted/density_budgeted)"
                )

    # Routing mode
    state["ROUTING_MODE"] = str(cfg.get("routing_mode", "weight_driven")).strip().lower()
    if state["ROUTING_MODE"] not in ("fixed", "weight_driven", "hierarchical"):
        state["ROUTING_MODE"] = "weight_driven"

    # Sim time
    _st = cfg.get("sim_time")
    if isinstance(_st, str) and _st.strip():
        state["SIMULATION_TIME"] = _st.strip()

    # Cache / line size / memory hierarchy toggles
    _l1sz = cfg.get("l1_size")
    if isinstance(_l1sz, str) and _l1sz.strip():
        state["L1_SIZE_STR"] = _l1sz.strip()
    _l1a = cfg.get("l1_assoc")
    if _l1a is not None:
        try:
            state["L1_ASSOC"] = int(_l1a)
        except Exception:
            pass
    _l1e = cfg.get("l1_enable")
    if (_l1e is not None) and (not l1_env_applied):
        state["L1_ENABLE"] = bool(_l1e)
    _lsb = cfg.get("line_size_bytes")
    if _lsb is not None:
        try:
            state["SUBCOMP_LINE_BYTES"] = int(_lsb)
            state["L1_LINE_BYTES_STR"] = str(int(_lsb))
        except Exception:
            pass
    _lchunk = cfg.get("loader_chunk_bytes")
    if _lchunk is not None:
        try:
            state["LOADER_CHUNK_BYTES"] = int(_lchunk)
        except Exception:
            pass
    _l2sz = cfg.get("l2_size")
    if isinstance(_l2sz, str) and _l2sz.strip():
        state["L2_SIZE_STR"] = _l2sz.strip()

    # Network & mesh size knobs
    _nbw = cfg.get("network_bandwidth")
    if isinstance(_nbw, str) and _nbw.strip():
        state["NETWORK_BANDWIDTH"] = _nbw.strip()
    _bufsz = cfg.get("buffer_size")
    if isinstance(_bufsz, str) and _bufsz.strip():
        state["BUFFER_SIZE"] = _bufsz.strip()
    _mesh = cfg.get("mesh_size")
    if _mesh is not None:
        try:
            state["MESH_SIZE"] = int(_mesh)
        except Exception:
            pass
    _ncores = cfg.get("num_cores_per_pe")
    if _ncores is not None:
        try:
            state["NUM_CORES_PER_PE"] = int(_ncores)
        except Exception:
            pass
    _neurpc = cfg.get("neurons_per_core")
    if _neurpc is not None:
        try:
            state["NEURONS_PER_CORE"] = int(_neurpc)
        except Exception:
            pass

    # Thresholds
    _thr = cfg.get("thresholds")
    state["THRESHOLDS"] = None
    if isinstance(_thr, dict):
        try:
            state["THRESHOLDS"] = {
                "input": float(_thr.get("input", 0.02)),
                "hidden1": float(_thr.get("hidden1", 0.03)),
                "hidden2": float(_thr.get("hidden2", 0.03)),
                "output": float(_thr.get("output", 0.035)),
            }
        except Exception:
            state["THRESHOLDS"] = None

    mesh_print(
        f"[local_run_config] 载入: single_bus={state.get('SINGLE_BUS_MODE')}, use_soa={state.get('USE_SOA_STATE')}, "
        f"use_aosoa={state.get('USE_AOSOA_STATE')}, aosoa_block_rows={state.get('AOSOA_BLOCK_ROWS')}, "
        f"synapse_format={(state.get('SYNAPSE_FORMAT_ENV') or 'default')}, force_dense={state.get('FORCE_DENSE')}, "
        f"bcsr_auto={state.get('AUTO_BCSR_DETECT')}, routing_mode={state.get('ROUTING_MODE')}, "
        f"verify_routing={state.get('VERIFY_ROUTING')}, eps={state.get('ROUT_EPS')}, "
        f"topk_pe={state.get('ROUT_TOPK_PER_PE')}, topk={state.get('ROUT_TOPK')}, "
        f"stats={_sv if _sv is not None else int(default_stats_level)}, core_verbose={state.get('CORE_VERBOSE')}, "
        f"node_verbose={state.get('NODE_VERBOSE')}, sim_time={state.get('SIMULATION_TIME')}"
    )
    mesh_print(
        f"[local_run_config] cache: l1_enable={1 if state.get('L1_ENABLE') else 0}, l1_size={state.get('L1_SIZE_STR')}, "
        f"l1_assoc={state.get('L1_ASSOC')}, line_size_bytes={state.get('SUBCOMP_LINE_BYTES')}, "
        f"loader_chunk_bytes={state.get('LOADER_CHUNK_BYTES')}, l2_size={state.get('L2_SIZE_STR')}"
    )

    # Custom debug knobs: verify reads & loader timed-seed
    _vre = cfg.get("verify_reads_enable")
    if _vre is not None:
        state["VERIFY_READS_ENABLE"] = 1 if bool(_vre) else 0
    _vcl = cfg.get("verify_cluster_enable")
    if _vcl is not None:
        state["VERIFY_CLUSTER_ENABLE"] = 1 if bool(_vcl) else 0
    _lts = cfg.get("loader_timed_seed_enable")
    if _lts is not None:
        state["LOADER_TIMED_SEED_ENABLE"] = 1 if bool(_lts) else 0
    _ltsc = cfg.get("loader_timed_seed_allow_cache")
    if _ltsc is not None:
        state["LOADER_TIMED_SEED_ALLOW_CACHE"] = 1 if bool(_ltsc) else 0

    # WeightLoader verify readback (debug only)
    _lvr = cfg.get("loader_verify_readback")
    if _lvr is not None:
        state["LOADER_VERIFY_READBACK"] = 1 if bool(_lvr) else 0
    _lvb = cfg.get("loader_verify_bytes")
    if _lvb is not None:
        try:
            state["LOADER_VERIFY_BYTES"] = int(_lvb)
        except Exception:
            pass
    _lvs = cfg.get("loader_verify_colidx_start")
    if _lvs is not None:
        try:
            state["LOADER_VERIFY_COLIDX_START"] = int(_lvs)
        except Exception:
            pass

    # WeightLoader runtime single-point readback probe (debug only)
    _ldr = cfg.get("loader_diag_timed_read")
    if _ldr is not None:
        state["LOADER_DIAG_TIMED_READ"] = 1 if bool(_ldr) else 0
    _ldrc = cfg.get("loader_diag_timed_read_colidx_start")
    if _ldrc is not None:
        try:
            state["LOADER_DIAG_TIMED_READ_COLIDX_START"] = int(_ldrc)
        except Exception:
            pass

    _wvs = cfg.get("weight_verify_samples")
    if _wvs is not None:
        try:
            state["WEIGHT_VERIFY_SAMPLES_OVERRIDE"] = int(_wvs)
        except Exception:
            state["WEIGHT_VERIFY_SAMPLES_OVERRIDE"] = None
    else:
        state["WEIGHT_VERIFY_SAMPLES_OVERRIDE"] = None

    return stats_level_override


def apply_gas_env_overrides(
    *,
    state: Dict[str, Any],
    merge_policy_env_key: str = "MESH_GAS_MERGE_POLICY",
    max_inflight_env_key: str = "MESH_GAS_MAX_INFLIGHT",
    window_cycles_env_key: str = "MESH_GAS_CYCLES",
) -> Dict[str, bool]:
    """
    Apply GAS-related overrides from environment variables into `state`.

    Mirrors legacy semantics:
    - Presence of env var blocks local_run_config.json from overriding the same knob,
      even if the env value is invalid (env has priority).
    - Prints the same "[mesh] override/ignore" lines as the legacy script.

    Expected `state` keys (created by caller before invoking):
    - _GAS_MERGE_POLICY (str)
    - _GAS_MAX_INFLIGHT (int)
    - _GAS_WINDOW_CYCLES (dict with gather/apply/scatter)
    - _GAS_SORT_POLICY (str)
    - _GAS_ROW_BYTES_GUESS (int)
    - _GAS_BANK_BITS (int)
    - _GAS_BANK_SHIFT (int)
    - _GAS_BANK_AUTO_ENABLE (int)
    """

    merge_env = os.environ.get(merge_policy_env_key, "").strip().lower()
    merge_env_present = bool(merge_env)
    if merge_env:
        if merge_env in ("auto", "row", "cacheline", "none"):
            state["_GAS_MERGE_POLICY"] = merge_env
            mesh_print(f"[mesh] override GAS merge_policy={state['_GAS_MERGE_POLICY']} via {merge_policy_env_key}={merge_env}")
        else:
            mesh_print(f"[mesh] ignore invalid {merge_policy_env_key}={merge_env} (expected auto/row/cacheline/none)")

    inflight_env_raw = os.environ.get(max_inflight_env_key, "").strip()
    inflight_env_present = bool(inflight_env_raw)
    if inflight_env_raw:
        try:
            v = int(inflight_env_raw)
            if v > 0:
                state["_GAS_MAX_INFLIGHT"] = v
                mesh_print(f"[mesh] override GAS max_inflight_reads={state['_GAS_MAX_INFLIGHT']} via {max_inflight_env_key}={inflight_env_raw}")
        except Exception as e:
            mesh_print(f"[mesh] ignore invalid {max_inflight_env_key}={inflight_env_raw}: {e}")

    cycles_env = os.environ.get(window_cycles_env_key, "").strip()
    if cycles_env:
        try:
            g, a, s = [int(x) for x in cycles_env.split(",")]
            if g > 0 and a >= 0 and s >= 0:
                state["_GAS_WINDOW_CYCLES"]["gather"] = g
                state["_GAS_WINDOW_CYCLES"]["apply"] = a
                state["_GAS_WINDOW_CYCLES"]["scatter"] = s
                mesh_print(f"[mesh] override GAS window cycles: gather={g} apply={a} scatter={s}")
        except Exception as e:
            mesh_print(f"[mesh] ignore invalid {window_cycles_env_key}={cycles_env}: {e}")

    sort_env_raw = os.environ.get("MESH_GAS_SORT_POLICY", "").strip().lower()
    sort_env_present = bool(sort_env_raw)
    if sort_env_raw:
        if sort_env_raw in ("addr", "row", "bank_row"):
            state["_GAS_SORT_POLICY"] = sort_env_raw
            mesh_print(f"[mesh] override GAS sort_policy={state['_GAS_SORT_POLICY']} via MESH_GAS_SORT_POLICY={sort_env_raw}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_SORT_POLICY={sort_env_raw!r} (expected addr/row/bank_row)")

    row_bytes_env_raw = os.environ.get("MESH_GAS_ROW_BYTES_GUESS", "").strip()
    row_bytes_env_present = bool(row_bytes_env_raw)
    if row_bytes_env_raw:
        try:
            v = int(row_bytes_env_raw)
            if v > 0:
                state["_GAS_ROW_BYTES_GUESS"] = v
                mesh_print(f"[mesh] override GAS row_bytes_guess={state['_GAS_ROW_BYTES_GUESS']} via MESH_GAS_ROW_BYTES_GUESS={row_bytes_env_raw}")
        except Exception as e:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_ROW_BYTES_GUESS={row_bytes_env_raw}: {e}")

    bank_bits_raw = os.environ.get("MESH_GAS_BANK_BITS", "").strip()
    bank_shift_raw = os.environ.get("MESH_GAS_BANK_SHIFT", "").strip()
    bank_auto_raw = os.environ.get("MESH_GAS_BANK_AUTO_ENABLE", "").strip().lower()
    bank_env_present = bool(bank_bits_raw or bank_shift_raw or bank_auto_raw)
    if bank_bits_raw:
        try:
            v = int(bank_bits_raw)
            if v >= 0:
                state["_GAS_BANK_BITS"] = v
                mesh_print(f"[mesh] override GAS bank_bits={state['_GAS_BANK_BITS']} via MESH_GAS_BANK_BITS={bank_bits_raw}")
        except Exception as e:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_BANK_BITS={bank_bits_raw}: {e}")
    if bank_shift_raw:
        try:
            v = int(bank_shift_raw)
            if v >= 0:
                state["_GAS_BANK_SHIFT"] = v
                mesh_print(f"[mesh] override GAS bank_shift={state['_GAS_BANK_SHIFT']} via MESH_GAS_BANK_SHIFT={bank_shift_raw}")
        except Exception as e:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_BANK_SHIFT={bank_shift_raw}: {e}")
    if bank_auto_raw:
        if bank_auto_raw in ("1", "true", "yes", "y", "on"):
            state["_GAS_BANK_AUTO_ENABLE"] = 1
            mesh_print(f"[mesh] override GAS bank_auto_enable=1 via MESH_GAS_BANK_AUTO_ENABLE={bank_auto_raw}")
        elif bank_auto_raw in ("0", "false", "no", "n", "off"):
            state["_GAS_BANK_AUTO_ENABLE"] = 0
            mesh_print(f"[mesh] override GAS bank_auto_enable=0 via MESH_GAS_BANK_AUTO_ENABLE={bank_auto_raw}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_BANK_AUTO_ENABLE={bank_auto_raw!r} (expected 0/1/true/false)")

    # Apply-stage issue scheduling overrides (priority: env > local_run_config.json).
    experimental_enable = (os.environ.get("MESH_EXPERIMENTAL_ENABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
    )
    apply_policy_env_present = False
    apply_frags_env_present = False
    apply_credit_env_present = False
    apply_age_env_present = False

    if experimental_enable:
        apply_policy_raw = os.environ.get("MESH_GAS_APPLY_ISSUE_POLICY", "").strip().lower()
        apply_policy_env_present = bool(apply_policy_raw)
        if apply_policy_raw:
            if apply_policy_raw in ("order", "bank_rr_row_sticky_age", "dram_aware_v1"):
                state["_GAS_APPLY_ISSUE_POLICY"] = apply_policy_raw
                mesh_print(
                    f"[mesh] override GAS apply_issue_policy={state['_GAS_APPLY_ISSUE_POLICY']} via MESH_GAS_APPLY_ISSUE_POLICY={apply_policy_raw}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_GAS_APPLY_ISSUE_POLICY={apply_policy_raw!r} (expected order/bank_rr_row_sticky_age/dram_aware_v1)"
                )

        # DRAM-aware Apply knobs (optional; only meaningful when apply_issue_policy=dram_aware_v1)
        _env = os.environ.get("MESH_GAS_DRAM_ROW_BYTES", "").strip()
        if _env:
            try:
                state["_GAS_DRAM_ROW_BYTES"] = int(_env)
                mesh_print(f"[mesh] override GAS dram_row_bytes={state['_GAS_DRAM_ROW_BYTES']} via MESH_GAS_DRAM_ROW_BYTES={_env}")
            except Exception as e:
                mesh_print(f"[mesh] ignore invalid MESH_GAS_DRAM_ROW_BYTES={_env!r}: {e}")
        _env = os.environ.get("MESH_GAS_DRAM_BANK_COUNT", "").strip()
        if _env:
            try:
                state["_GAS_DRAM_BANK_COUNT"] = int(_env)
                mesh_print(f"[mesh] override GAS dram_bank_count={state['_GAS_DRAM_BANK_COUNT']} via MESH_GAS_DRAM_BANK_COUNT={_env}")
            except Exception as e:
                mesh_print(f"[mesh] ignore invalid MESH_GAS_DRAM_BANK_COUNT={_env!r}: {e}")
        _env = os.environ.get("MESH_GAS_DRAM_READ_BURST_BYTES", "").strip()
        if _env:
            try:
                state["_GAS_DRAM_READ_BURST_BYTES"] = int(_env)
                mesh_print(
                    f"[mesh] override GAS dram_read_burst_bytes={state['_GAS_DRAM_READ_BURST_BYTES']} via MESH_GAS_DRAM_READ_BURST_BYTES={_env}"
                )
            except Exception as e:
                mesh_print(f"[mesh] ignore invalid MESH_GAS_DRAM_READ_BURST_BYTES={_env!r}: {e}")
        _env = os.environ.get("MESH_GAS_DRAM_ROW_MISS_PENALTY_CYCLES", "").strip()
        if _env:
            try:
                state["_GAS_DRAM_ROW_MISS_PENALTY_CYCLES"] = int(_env)
                mesh_print(
                    f"[mesh] override GAS dram_row_miss_penalty_cycles={state['_GAS_DRAM_ROW_MISS_PENALTY_CYCLES']} via MESH_GAS_DRAM_ROW_MISS_PENALTY_CYCLES={_env}"
                )
            except Exception as e:
                mesh_print(f"[mesh] ignore invalid MESH_GAS_DRAM_ROW_MISS_PENALTY_CYCLES={_env!r}: {e}")
        _env = os.environ.get("MESH_GAS_DRAM_OVERFETCH_BUDGET_BYTES", "").strip()
        if _env:
            try:
                state["_GAS_DRAM_OVERFETCH_BUDGET_BYTES"] = int(_env)
                mesh_print(
                    f"[mesh] override GAS dram_overfetch_budget_bytes={state['_GAS_DRAM_OVERFETCH_BUDGET_BYTES']} via MESH_GAS_DRAM_OVERFETCH_BUDGET_BYTES={_env}"
                )
            except Exception as e:
                mesh_print(f"[mesh] ignore invalid MESH_GAS_DRAM_OVERFETCH_BUDGET_BYTES={_env!r}: {e}")
        _env = os.environ.get("MESH_GAS_DRAM_AWARE_ENABLE_ROWWIN", "").strip().lower()
        if _env:
            if _env in ("1", "true", "yes", "y", "on"):
                state["_GAS_DRAM_AWARE_ENABLE_ROWWIN"] = 1
                mesh_print(
                    f"[mesh] override GAS dram_aware_enable_row_window=1 via MESH_GAS_DRAM_AWARE_ENABLE_ROWWIN={_env}"
                )
            elif _env in ("0", "false", "no", "n", "off"):
                state["_GAS_DRAM_AWARE_ENABLE_ROWWIN"] = 0
                mesh_print(
                    f"[mesh] override GAS dram_aware_enable_row_window=0 via MESH_GAS_DRAM_AWARE_ENABLE_ROWWIN={_env}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_GAS_DRAM_AWARE_ENABLE_ROWWIN={_env!r} (expected 0/1/true/false)"
                )
        _env = os.environ.get("MESH_GAS_DRAM_AWARE_K_POLICY", "").strip().lower()
        if _env:
            if _env in ("fixed", "cost_budgeted", "density_budgeted"):
                state["_GAS_DRAM_AWARE_K_POLICY"] = _env
                mesh_print(
                    f"[mesh] override GAS dram_aware_k_policy={state['_GAS_DRAM_AWARE_K_POLICY']} via MESH_GAS_DRAM_AWARE_K_POLICY={_env}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_GAS_DRAM_AWARE_K_POLICY={_env!r} (expected fixed/cost_budgeted/density_budgeted)"
                )

        apply_frags_raw = os.environ.get("MESH_GAS_APPLY_FRAGS_PER_ISSUE", "").strip()
        apply_frags_env_present = bool(apply_frags_raw)
        if apply_frags_raw:
            try:
                v = int(apply_frags_raw)
                if v >= 0:
                    state["_GAS_APPLY_FRAGS_PER_ISSUE"] = v
                    mesh_print(
                        f"[mesh] override GAS apply_frags_per_issue={state['_GAS_APPLY_FRAGS_PER_ISSUE']} via MESH_GAS_APPLY_FRAGS_PER_ISSUE={apply_frags_raw}"
                    )
            except Exception as e:
                mesh_print(f"[mesh] ignore invalid MESH_GAS_APPLY_FRAGS_PER_ISSUE={apply_frags_raw}: {e}")

        apply_credit_raw = os.environ.get("MESH_GAS_APPLY_BANK_CREDIT", "").strip()
        apply_credit_env_present = bool(apply_credit_raw)
        if apply_credit_raw:
            try:
                v = int(apply_credit_raw)
                if v >= 0:
                    state["_GAS_APPLY_BANK_CREDIT"] = v
                    mesh_print(
                        f"[mesh] override GAS apply_bank_credit={state['_GAS_APPLY_BANK_CREDIT']} via MESH_GAS_APPLY_BANK_CREDIT={apply_credit_raw}"
                    )
            except Exception as e:
                mesh_print(f"[mesh] ignore invalid MESH_GAS_APPLY_BANK_CREDIT={apply_credit_raw}: {e}")

        apply_age_raw = os.environ.get("MESH_GAS_APPLY_AGE_FAIR_NS", "").strip()
        apply_age_env_present = bool(apply_age_raw)
        if apply_age_raw:
            try:
                v = int(apply_age_raw)
                if v >= 0:
                    state["_GAS_APPLY_AGE_FAIR_NS"] = v
                    mesh_print(
                        f"[mesh] override GAS apply_age_fair_ns={state['_GAS_APPLY_AGE_FAIR_NS']} via MESH_GAS_APPLY_AGE_FAIR_NS={apply_age_raw}"
                    )
            except Exception as e:
                mesh_print(f"[mesh] ignore invalid MESH_GAS_APPLY_AGE_FAIR_NS={apply_age_raw}: {e}")
    else:
        # Strict isolation: ignore exploratory GAS Apply scheduling env overrides unless explicitly enabled.
        ignored = []
        for k in (
            "MESH_GAS_APPLY_ISSUE_POLICY",
            "MESH_GAS_APPLY_FRAGS_PER_ISSUE",
            "MESH_GAS_APPLY_BANK_CREDIT",
            "MESH_GAS_APPLY_AGE_FAIR_NS",
        ):
            if (os.environ.get(k) or "").strip():
                ignored.append(k)
        if ignored:
            mesh_print(
                f"[mesh] NOTE: ignore exploratory GAS Apply scheduling overrides {ignored} (set MESH_EXPERIMENTAL_ENABLE=1 to enable)"
            )

    return {
        "gas_merge_env_present": merge_env_present,
        "gas_inflight_env_present": inflight_env_present,
        "gas_sort_env_present": sort_env_present,
        "gas_row_bytes_env_present": row_bytes_env_present,
        "gas_bank_env_present": bank_env_present,
        "gas_apply_policy_env_present": apply_policy_env_present,
        "gas_apply_frags_env_present": apply_frags_env_present,
        "gas_apply_credit_env_present": apply_credit_env_present,
        "gas_apply_age_env_present": apply_age_env_present,
    }


def maybe_default_gas_merge_policy_for_global_step_sync(
    *,
    state: Dict[str, Any],
    cfg: Optional[Dict[str, Any]],
    gas_env_flags: Dict[str, Any],
) -> None:
    """
    Legacy behavior: when GLOBAL_STEP_SYNC_ENABLE is on, and merge_policy is still "auto"
    (not explicitly set by env or local_run_config.json), default to "cacheline" to avoid
    the 'row(8KiB) amplification' long tail.
    """

    if not bool(state.get("GLOBAL_STEP_SYNC_ENABLE", False)):
        return

    cfg_merge_set = False
    if isinstance(cfg, dict):
        try:
            cfg_merge = cfg.get("gas_merge_policy")
            cfg_merge_set = isinstance(cfg_merge, str) and bool(cfg_merge.strip())
        except Exception:
            cfg_merge_set = False

    if bool(gas_env_flags.get("gas_merge_env_present", False)):
        return
    if cfg_merge_set:
        return

    if str(state.get("_GAS_MERGE_POLICY", "")).strip().lower() == "auto":
        state["_GAS_MERGE_POLICY"] = "cacheline"
        mesh_print("[mesh] GLOBAL_STEP_SYNC_ENABLE=1 -> default GAS merge_policy=cacheline (overrideable)")


def maybe_default_gas_window_cycles_for_global_step_sync(
    *,
    state: Dict[str, Any],
    cfg: Optional[Dict[str, Any]],
    gas_env_flags: Dict[str, Any],
    window_cycles_env_key: str = "MESH_GAS_CYCLES",
) -> None:
    """
    When GLOBAL_STEP_SYNC_ENABLE is on (barrier/step-gate mode), default GAS window cycles
    to load-driven behavior:
      gather/apply/scatter = 0

    Rationale:
    - In global step sync mode, Gather/Scatter should be ended by explicit workload handshake
      (EndGather/EndScatter), and Apply should end on allReady(required_set).
    - Fixed window cycles are kept as opt-in compatibility/diagnostic knobs via env override.

    Override priority:
    - MESH_GAS_CYCLES env (if set) always wins
    - local_run_config.json may override in future (kept for forward-compat)
    """

    if not bool(state.get("GLOBAL_STEP_SYNC_ENABLE", False)):
        return

    # Env always wins (legacy semantics).
    cycles_env = os.environ.get(window_cycles_env_key, "").strip()
    if cycles_env:
        return

    # Forward-compat: if local_run_config.json ever carries explicit window cycles, do not override.
    cfg_cycles_set = False
    if isinstance(cfg, dict):
        for k in ("gas_window_cycles_gather", "gas_window_cycles_apply", "gas_window_cycles_scatter"):
            if cfg.get(k) is not None:
                cfg_cycles_set = True
                break
    if cfg_cycles_set:
        return

    # If already overridden elsewhere, keep it.
    win = state.get("_GAS_WINDOW_CYCLES", None)
    if isinstance(win, dict):
        try:
            g = int(win.get("gather", 0) or 0)
            a = int(win.get("apply", 0) or 0)
            s = int(win.get("scatter", 0) or 0)
            if g == 0 and a == 0 and s == 0:
                return
        except Exception:
            pass

    state["_GAS_WINDOW_CYCLES"] = {"gather": 0, "apply": 0, "scatter": 0}
    mesh_print("[mesh] GLOBAL_STEP_SYNC_ENABLE=1 -> default GAS window_cycles: gather=0 apply=0 scatter=0 (load-driven)")


def apply_global_step_sync_env_override(
    *,
    state: Dict[str, Any],
    env_key: str = "MESH_GLOBAL_STEP_SYNC",
) -> bool:
    """
    Apply GLOBAL_STEP_SYNC_ENABLE override from environment variable.

    Legacy semantics:
    - If env is set (non-empty), it has priority over local_run_config.json.
    - Prints the same override line.

    Returns True if env was present (non-empty), else False.
    """

    raw = os.environ.get(env_key, "").strip().lower()
    if not raw:
        return False
    state["GLOBAL_STEP_SYNC_ENABLE"] = raw in ("1", "true", "yes", "y", "on")
    mesh_print(f"[mesh] override GLOBAL_STEP_SYNC_ENABLE={1 if state['GLOBAL_STEP_SYNC_ENABLE'] else 0} via {env_key}={raw}")
    return True
