from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from .utils import mesh_print, mesh_quiet


def _normalize_noc_type(raw: Any) -> str:
    noc = str(raw or "").strip().lower()
    if noc in ("merlin_mesh", "mesh", "merlin.mesh"):
        return "merlin_mesh"
    if noc in ("merlin_torus", "torus", "merlin.torus"):
        return "merlin_torus"
    if noc in ("multicast_mesh", "multicast", "storm", "storm_multicast"):
        return "multicast_mesh"
    return ""


def _normalize_thermal_backend(raw: Any) -> str:
    backend = str(raw or "").strip().lower()
    if backend in ("hotspot", "hot-spot"):
        return "hotspot"
    if backend in ("3dice", "3d-ice", "3d_ice"):
        return "3dice"
    return ""


def _normalize_thermal_model_type(raw: Any) -> str:
    model_type = str(raw or "").strip().lower()
    if model_type in ("block", "2d", "2d_block"):
        return "block"
    if model_type in ("grid", "3d", "3d_grid"):
        return "grid"
    return ""


def _normalize_thermal_grid_map_mode(raw: Any) -> str:
    mode = str(raw or "").strip().lower()
    if mode in ("avg", "min", "max", "center"):
        return mode
    return ""


def resolve_input_path_under_project(raw_path: str, *, script_dir: str) -> str:
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
    gas_dram_cmd_offline_model_env_present: bool = False,
    gas_dram_cmd_offline_model_strict_env_present: bool = False,
) -> Optional[int]:
    """
    Apply overrides from local_run_config.json onto `state`.

    Notes:
    - Keeps env priority for GAS merge/inflight (env wins over local_run_config.json).
    - Keeps env priority for GAS sort/row_bytes/bank mapping knobs.
    - Returns an optional stats load level override (int) for caller to apply via SST.
    """

    def _resolve_path_under_project(raw_path: str) -> str:
        return resolve_input_path_under_project(raw_path, script_dir=script_dir)

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
    _swm = cfg.get("synapse_weight_mode")
    if isinstance(_swm, str) and _swm.strip():
        v = _swm.strip().lower()
        if v == "gscc_valueonly_dstcore":
            v = "gcss_valueonly_dstcore"
        if v == "gscc_valueonly_dstcore_vlf_premphf":
            v = "gcss_valueonly_dstcore_vlf_premphf"
        if v == "gscc_valueonly_dstcore_vlf_premphf_plp":
            v = "gcss_valueonly_dstcore_vlf_premphf_plp"
        if v in (
            "bcsr_gas",
            "gcss_valueonly_dstcore",
            "gcss_valueonly_dstcore_idx2",
            "gcss_idx2_rowmphf",
            "gcss_valueonly_dstcore_vlf_premphf",
            "gcss_valueonly_dstcore_vlf_premphf_plp",
        ):
            state["SYNAPSE_WEIGHT_MODE"] = v
        else:
            mesh_print(
                f"[mesh] ignore invalid local_run_config.json synapse_weight_mode={v!r} "
                "(expected bcsr_gas/gcss_valueonly_dstcore/gcss_valueonly_dstcore_idx2/gcss_valueonly_dstcore_vlf_premphf/gcss_valueonly_dstcore_vlf_premphf_plp)"
            )
    _gcss_dir = cfg.get("gcss_dir")
    if isinstance(_gcss_dir, str) and _gcss_dir.strip():
        state["GCSS_DIR"] = _resolve_path_under_project(_gcss_dir.strip())
    _gcss2_dir = cfg.get("gcss2_dir")
    if isinstance(_gcss2_dir, str) and _gcss2_dir.strip():
        state["GCSS2_DIR"] = _resolve_path_under_project(_gcss2_dir.strip())
    _gcssvlf_dir = cfg.get("gcssvlf_dir")
    if isinstance(_gcssvlf_dir, str) and _gcssvlf_dir.strip():
        state["GCSSVLF_DIR"] = _resolve_path_under_project(_gcssvlf_dir.strip())
    _gcssplp_dir = cfg.get("gcssplp_dir")
    if isinstance(_gcssplp_dir, str) and _gcssplp_dir.strip():
        state["GCSSPLP_DIR"] = _resolve_path_under_project(_gcssplp_dir.strip())
    _gcssnt_dir = cfg.get("gcssnt_dir")
    if isinstance(_gcssnt_dir, str) and _gcssnt_dir.strip():
        state["GCSSNT_DIR"] = _resolve_path_under_project(_gcssnt_dir.strip())
    _gcssplp_profile_export_enable = cfg.get("gcssplp_profile_export_enable")
    if _gcssplp_profile_export_enable is not None:
        state["GCSSPLP_PROFILE_EXPORT_ENABLE"] = 1 if bool(_gcssplp_profile_export_enable) else 0
    _gcssplp_profile_export_dir = cfg.get("gcssplp_profile_export_dir")
    if isinstance(_gcssplp_profile_export_dir, str) and _gcssplp_profile_export_dir.strip():
        state["GCSSPLP_PROFILE_EXPORT_DIR"] = _resolve_path_under_project(_gcssplp_profile_export_dir.strip())
    _idx2_ingress_prefetch_enable = cfg.get("experimental_idx2_ingress_prefetch_enable")
    if _idx2_ingress_prefetch_enable is not None:
        state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_ENABLE"] = 1 if bool(_idx2_ingress_prefetch_enable) else 0
    _idx2_ingress_prefetch_budget_per_tick = cfg.get("experimental_idx2_ingress_prefetch_budget_per_tick")
    if _idx2_ingress_prefetch_budget_per_tick is not None:
        try:
            state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_BUDGET_PER_TICK"] = max(
                1, int(_idx2_ingress_prefetch_budget_per_tick)
            )
        except Exception:
            pass
    _idx2_ingress_prefetch_cache_entries = cfg.get("experimental_idx2_ingress_prefetch_cache_entries")
    if _idx2_ingress_prefetch_cache_entries is not None:
        try:
            state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CACHE_ENTRIES"] = max(
                1, int(_idx2_ingress_prefetch_cache_entries)
            )
        except Exception:
            pass
    _idx2_ingress_prefetch_max_inflight = cfg.get("experimental_idx2_ingress_prefetch_max_inflight")
    if _idx2_ingress_prefetch_max_inflight is not None:
        try:
            state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_MAX_INFLIGHT"] = max(
                0, int(_idx2_ingress_prefetch_max_inflight)
            )
        except Exception:
            pass
    _idx2_ingress_prefetch_gather_only = cfg.get("experimental_idx2_ingress_prefetch_gather_only")
    if _idx2_ingress_prefetch_gather_only is not None:
        state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_GATHER_ONLY"] = (
            1 if bool(_idx2_ingress_prefetch_gather_only) else 0
        )
    _idx2_ingress_prefetch_carry_to_apply_enable = cfg.get(
        "experimental_idx2_ingress_prefetch_carry_to_apply_enable"
    )
    if _idx2_ingress_prefetch_carry_to_apply_enable is not None:
        state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CARRY_TO_APPLY_ENABLE"] = (
            1 if bool(_idx2_ingress_prefetch_carry_to_apply_enable) else 0
        )
    _idx2_ingress_prefetch_apply_max_inflight = cfg.get(
        "experimental_idx2_ingress_prefetch_apply_max_inflight"
    )
    if _idx2_ingress_prefetch_apply_max_inflight is not None:
        try:
            state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_MAX_INFLIGHT"] = max(
                0, int(_idx2_ingress_prefetch_apply_max_inflight)
            )
        except Exception:
            pass
    _idx2_ingress_prefetch_apply_outstanding_reserve = cfg.get(
        "experimental_idx2_ingress_prefetch_apply_outstanding_reserve"
    )
    if _idx2_ingress_prefetch_apply_outstanding_reserve is not None:
        try:
            state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_OUTSTANDING_RESERVE"] = max(
                0, int(_idx2_ingress_prefetch_apply_outstanding_reserve)
            )
        except Exception:
            pass
    _idx2_ingress_prefetch_apply_frontier_keep_pending = cfg.get(
        "experimental_idx2_ingress_prefetch_apply_frontier_keep_pending"
    )
    if _idx2_ingress_prefetch_apply_frontier_keep_pending is not None:
        try:
            state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_FRONTIER_KEEP_PENDING"] = max(
                0, int(_idx2_ingress_prefetch_apply_frontier_keep_pending)
            )
        except Exception:
            pass
    _idx2_ingress_tail_guard_enable = cfg.get("experimental_idx2_ingress_tail_guard_enable")
    if _idx2_ingress_tail_guard_enable is not None:
        state["EXPERIMENTAL_IDX2_INGRESS_TAIL_GUARD_ENABLE"] = (
            1 if bool(_idx2_ingress_tail_guard_enable) else 0
        )
    _idx2_ingress_budget_adapt_enable = cfg.get("experimental_idx2_ingress_budget_adapt_enable")
    if _idx2_ingress_budget_adapt_enable is not None:
        state["EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_ENABLE"] = (
            1 if bool(_idx2_ingress_budget_adapt_enable) else 0
        )
    _idx2_ingress_budget_adapt_max_per_tick = cfg.get("experimental_idx2_ingress_budget_adapt_max_per_tick")
    if _idx2_ingress_budget_adapt_max_per_tick is not None:
        try:
            state["EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_MAX_PER_TICK"] = max(
                1, int(_idx2_ingress_budget_adapt_max_per_tick)
            )
        except Exception:
            pass
    _idx2_ingress_budget_adapt_q_depth = cfg.get("experimental_idx2_ingress_budget_adapt_q_depth")
    if _idx2_ingress_budget_adapt_q_depth is not None:
        try:
            state["EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_Q_DEPTH"] = max(
                1, int(_idx2_ingress_budget_adapt_q_depth)
            )
        except Exception:
            pass
    _noc_rowidx_prefetch_enable = cfg.get("experimental_noc_rowidx_prefetch_enable")
    if _noc_rowidx_prefetch_enable is not None:
        state["EXPERIMENTAL_NOC_ROWIDX_PREFETCH_ENABLE"] = (
            1 if bool(_noc_rowidx_prefetch_enable) else 0
        )
    _noc_rowidx_prefetch_budget_per_tick = cfg.get("experimental_noc_rowidx_prefetch_budget_per_tick")
    if _noc_rowidx_prefetch_budget_per_tick is not None:
        try:
            state["EXPERIMENTAL_NOC_ROWIDX_PREFETCH_BUDGET_PER_TICK"] = max(
                1, int(_noc_rowidx_prefetch_budget_per_tick)
            )
        except Exception:
            pass
    _noc_rowidx_cache_rows = cfg.get("experimental_noc_rowidx_cache_rows")
    if _noc_rowidx_cache_rows is not None:
        try:
            state["EXPERIMENTAL_NOC_ROWIDX_CACHE_ROWS"] = max(
                1, int(_noc_rowidx_cache_rows)
            )
        except Exception:
            pass
    _noc_rowidx_prefetch_gather_only = cfg.get("experimental_noc_rowidx_prefetch_gather_only")
    if _noc_rowidx_prefetch_gather_only is not None:
        state["EXPERIMENTAL_NOC_ROWIDX_PREFETCH_GATHER_ONLY"] = (
            1 if bool(_noc_rowidx_prefetch_gather_only) else 0
        )
    _noc_rowidx_prefetch_detached_enable = cfg.get("experimental_noc_rowidx_prefetch_detached_enable")
    if _noc_rowidx_prefetch_detached_enable is not None:
        state["EXPERIMENTAL_NOC_ROWIDX_PREFETCH_DETACHED_ENABLE"] = (
            1 if bool(_noc_rowidx_prefetch_detached_enable) else 0
        )
    _noc_rowidx_prefetch_carry_to_apply_enable = cfg.get("experimental_noc_rowidx_prefetch_carry_to_apply_enable")
    if _noc_rowidx_prefetch_carry_to_apply_enable is not None:
        state["EXPERIMENTAL_NOC_ROWIDX_PREFETCH_CARRY_TO_APPLY_ENABLE"] = (
            1 if bool(_noc_rowidx_prefetch_carry_to_apply_enable) else 0
        )
    _noc_rowidx_hot_touch_min = cfg.get("experimental_noc_rowidx_hot_touch_min")
    if _noc_rowidx_hot_touch_min is not None:
        try:
            state["EXPERIMENTAL_NOC_ROWIDX_HOT_TOUCH_MIN"] = max(
                1, int(_noc_rowidx_hot_touch_min)
            )
        except Exception:
            pass
    _noc_rowidx_budget_adapt_enable = cfg.get("experimental_noc_rowidx_budget_adapt_enable")
    if _noc_rowidx_budget_adapt_enable is not None:
        state["EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_ENABLE"] = (
            1 if bool(_noc_rowidx_budget_adapt_enable) else 0
        )
    _noc_rowidx_budget_adapt_max_per_tick = cfg.get("experimental_noc_rowidx_budget_adapt_max_per_tick")
    if _noc_rowidx_budget_adapt_max_per_tick is not None:
        try:
            state["EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_MAX_PER_TICK"] = max(
                1, int(_noc_rowidx_budget_adapt_max_per_tick)
            )
        except Exception:
            pass
    _noc_rowidx_budget_adapt_q_depth = cfg.get("experimental_noc_rowidx_budget_adapt_q_depth")
    if _noc_rowidx_budget_adapt_q_depth is not None:
        try:
            state["EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_Q_DEPTH"] = max(
                1, int(_noc_rowidx_budget_adapt_q_depth)
            )
        except Exception:
            pass
    _gcss_phase_breakdown_enable = cfg.get("experimental_gcss_phase_breakdown_enable")
    if _gcss_phase_breakdown_enable is not None:
        state["GCSS_PHASE_BREAKDOWN_ENABLE"] = 1 if bool(_gcss_phase_breakdown_enable) else 0
    _retire_shadow_per_post_enable = cfg.get("experimental_retire_shadow_per_post_enable")
    if _retire_shadow_per_post_enable is not None:
        state["RETIRE_SHADOW_PER_POST_ENABLE"] = 1 if bool(_retire_shadow_per_post_enable) else 0
    _gcss_vlf_queue_policy = cfg.get("experimental_gcss_vlf_queue_policy")
    if isinstance(_gcss_vlf_queue_policy, str) and _gcss_vlf_queue_policy.strip():
        state["GCSS_VLF_QUEUE_POLICY"] = _gcss_vlf_queue_policy.strip().lower()
    _gcss_vlf_fair_band_size = cfg.get("experimental_gcss_vlf_fair_band_size")
    if _gcss_vlf_fair_band_size is not None:
        try:
            state["GCSS_VLF_FAIR_BAND_SIZE"] = max(1, int(_gcss_vlf_fair_band_size))
        except Exception:
            pass
    _gcss_vlf_bounded_rescue_enable = cfg.get("experimental_gcss_vlf_bounded_rescue_enable")
    if _gcss_vlf_bounded_rescue_enable is not None:
        state["GCSS_VLF_BOUNDED_RESCUE_ENABLE"] = 1 if bool(_gcss_vlf_bounded_rescue_enable) else 0
    _gcss_vlf_bounded_rescue_scan_limit = cfg.get("experimental_gcss_vlf_bounded_rescue_scan_limit")
    if _gcss_vlf_bounded_rescue_scan_limit is not None:
        try:
            state["GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT"] = max(0, int(_gcss_vlf_bounded_rescue_scan_limit))
        except Exception:
            pass
    _gcss_vlf_bounded_rescue_head_wait_cycles = cfg.get("experimental_gcss_vlf_bounded_rescue_head_wait_cycles")
    if _gcss_vlf_bounded_rescue_head_wait_cycles is not None:
        try:
            state["GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES"] = max(0, int(_gcss_vlf_bounded_rescue_head_wait_cycles))
        except Exception:
            pass
    _gcss_vlf_bounded_rescue_depth_threshold = cfg.get("experimental_gcss_vlf_bounded_rescue_depth_threshold")
    if _gcss_vlf_bounded_rescue_depth_threshold is not None:
        try:
            state["GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD"] = max(0, int(_gcss_vlf_bounded_rescue_depth_threshold))
        except Exception:
            pass
    _pulse_enable = cfg.get("pulse_enable")
    if _pulse_enable is not None:
        state["PULSE_ENABLE"] = 1 if bool(_pulse_enable) else 0
    _pulse_observe_only = cfg.get("pulse_observe_only")
    if _pulse_observe_only is not None:
        state["PULSE_OBSERVE_ONLY"] = 1 if bool(_pulse_observe_only) else 0
    _pulse_ingress_enable = cfg.get("pulse_ingress_enable")
    if _pulse_ingress_enable is not None:
        state["PULSE_INGRESS_ENABLE"] = 1 if bool(_pulse_ingress_enable) else 0
    _pulse_agenda_observe_only = cfg.get("pulse_agenda_observe_only")
    if _pulse_agenda_observe_only is not None:
        state["PULSE_AGENDA_OBSERVE_ONLY"] = 1 if bool(_pulse_agenda_observe_only) else 0
    _pulse_harbor_enable = cfg.get("pulse_harbor_enable")
    if _pulse_harbor_enable is not None:
        state["PULSE_HARBOR_ENABLE"] = 1 if bool(_pulse_harbor_enable) else 0
    _pulse_descriptor_enable = cfg.get("pulse_descriptor_enable")
    if _pulse_descriptor_enable is not None:
        state["PULSE_DESCRIPTOR_ENABLE"] = 1 if bool(_pulse_descriptor_enable) else 0
    _pulse_descriptor_actual_enable = cfg.get("pulse_descriptor_actual_enable")
    if _pulse_descriptor_actual_enable is not None:
        state["PULSE_DESCRIPTOR_ACTUAL_ENABLE"] = 1 if bool(_pulse_descriptor_actual_enable) else 0
    _pulse_experimental_rowdescriptor_ready_join_dedup_enable = cfg.get(
        "pulse_experimental_rowdescriptor_ready_join_dedup_enable",
        cfg.get("pulse", {}).get("experimental_rowdescriptor_ready_join_dedup_enable")
        if isinstance(cfg.get("pulse"), dict)
        else None,
    )
    if _pulse_experimental_rowdescriptor_ready_join_dedup_enable is not None:
        state["PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE"] = (
            1 if bool(_pulse_experimental_rowdescriptor_ready_join_dedup_enable) else 0
        )
    _pulse_domain_retire_enable = cfg.get("pulse_domain_retire_enable")
    if _pulse_domain_retire_enable is not None:
        state["PULSE_DOMAIN_RETIRE_ENABLE"] = 1 if bool(_pulse_domain_retire_enable) else 0
    _pulse_domain_retire_observe_only = cfg.get("pulse_domain_retire_observe_only")
    if _pulse_domain_retire_observe_only is not None:
        state["PULSE_DOMAIN_RETIRE_OBSERVE_ONLY"] = 1 if bool(_pulse_domain_retire_observe_only) else 0
    _pulse_domain_retire_mode = cfg.get("pulse_domain_retire_mode")
    if isinstance(_pulse_domain_retire_mode, str) and _pulse_domain_retire_mode.strip():
        _pulse_domain_retire_mode_norm = _pulse_domain_retire_mode.strip().lower()
        if _pulse_domain_retire_mode_norm in ("per_post", "descriptor_domain"):
            state["PULSE_DOMAIN_RETIRE_MODE"] = _pulse_domain_retire_mode_norm
    _pulse_domain_retire_release_budget = cfg.get("pulse_domain_retire_release_budget")
    if _pulse_domain_retire_release_budget is not None:
        try:
            state["PULSE_DOMAIN_RETIRE_RELEASE_BUDGET"] = max(0, int(_pulse_domain_retire_release_budget))
        except Exception:
            pass
    _pulse_frontier_observe_enable = cfg.get("pulse_frontier_observe_enable")
    if _pulse_frontier_observe_enable is not None:
        state["PULSE_FRONTIER_OBSERVE_ENABLE"] = 1 if bool(_pulse_frontier_observe_enable) else 0
    _pulse_frontier_top_lines = cfg.get("pulse_frontier_top_lines")
    if _pulse_frontier_top_lines is not None:
        try:
            state["PULSE_FRONTIER_TOP_LINES"] = max(1, int(_pulse_frontier_top_lines))
        except Exception:
            pass
    _pulse_metadata_frontier_observe_enable = cfg.get("pulse_metadata_frontier_observe_enable")
    if _pulse_metadata_frontier_observe_enable is not None:
        state["PULSE_METADATA_FRONTIER_OBSERVE_ENABLE"] = (
            1 if bool(_pulse_metadata_frontier_observe_enable) else 0
        )
    _pulse_metadata_frontier_top_items = cfg.get("pulse_metadata_frontier_top_items")
    if _pulse_metadata_frontier_top_items is not None:
        try:
            state["PULSE_METADATA_FRONTIER_TOP_ITEMS"] = max(1, int(_pulse_metadata_frontier_top_items))
        except Exception:
            pass
    _pulse_metadata_frontier_band_slots = cfg.get("pulse_metadata_frontier_band_slots")
    if _pulse_metadata_frontier_band_slots is not None:
        try:
            state["PULSE_METADATA_FRONTIER_BAND_SLOTS"] = max(1, int(_pulse_metadata_frontier_band_slots))
        except Exception:
            pass
    _pulse_metadata_seed_enable = cfg.get("pulse_metadata_seed_enable")
    if _pulse_metadata_seed_enable is not None:
        state["PULSE_METADATA_SEED_ENABLE"] = 1 if bool(_pulse_metadata_seed_enable) else 0
    _pulse_metadata_seed_top_bases = cfg.get("pulse_metadata_seed_top_bases")
    if _pulse_metadata_seed_top_bases is not None:
        try:
            state["PULSE_METADATA_SEED_TOP_BASES"] = max(1, int(_pulse_metadata_seed_top_bases))
        except Exception:
            pass
    _pulse_metadata_seed_window_budget = cfg.get("pulse_metadata_seed_window_budget")
    if _pulse_metadata_seed_window_budget is not None:
        try:
            state["PULSE_METADATA_SEED_WINDOW_BUDGET"] = max(0, int(_pulse_metadata_seed_window_budget))
        except Exception:
            pass
    _pulse_mfb_preband_seed_enable = cfg.get("pulse_mfb_preband_seed_enable")
    if _pulse_mfb_preband_seed_enable is not None:
        state["PULSE_MFB_PREBAND_SEED_ENABLE"] = 1 if bool(_pulse_mfb_preband_seed_enable) else 0
    _pulse_mfb_preband_top_bands = cfg.get("pulse_mfb_preband_top_bands")
    if _pulse_mfb_preband_top_bands is not None:
        try:
            state["PULSE_MFB_PREBAND_TOP_BANDS"] = max(1, int(_pulse_mfb_preband_top_bands))
        except Exception:
            pass
    _pulse_mfb_preband_lines_per_band = cfg.get("pulse_mfb_preband_lines_per_band")
    if _pulse_mfb_preband_lines_per_band is not None:
        try:
            state["PULSE_MFB_PREBAND_LINES_PER_BAND"] = max(1, int(_pulse_mfb_preband_lines_per_band))
        except Exception:
            pass
    _pulse_mfb_preband_band_slots = cfg.get("pulse_mfb_preband_band_slots")
    if _pulse_mfb_preband_band_slots is not None:
        try:
            state["PULSE_MFB_PREBAND_BAND_SLOTS"] = max(1, int(_pulse_mfb_preband_band_slots))
        except Exception:
            pass
    _pulse_mfb_preband_window_budget = cfg.get("pulse_mfb_preband_window_budget")
    if _pulse_mfb_preband_window_budget is not None:
        try:
            state["PULSE_MFB_PREBAND_WINDOW_BUDGET"] = max(0, int(_pulse_mfb_preband_window_budget))
        except Exception:
            pass
    _pulse_mfb_gather_preband_enable = cfg.get("pulse_mfb_gather_preband_enable")
    if _pulse_mfb_gather_preband_enable is not None:
        state["PULSE_MFB_GATHER_PREBAND_ENABLE"] = 1 if bool(_pulse_mfb_gather_preband_enable) else 0
    _pulse_mfb_gather_barrier_enable = cfg.get("pulse_mfb_gather_barrier_enable")
    if _pulse_mfb_gather_barrier_enable is not None:
        state["PULSE_MFB_GATHER_BARRIER_ENABLE"] = 1 if bool(_pulse_mfb_gather_barrier_enable) else 0
    _pulse_mfb_gather_top_bands = cfg.get("pulse_mfb_gather_top_bands")
    if _pulse_mfb_gather_top_bands is not None:
        try:
            state["PULSE_MFB_GATHER_TOP_BANDS"] = max(1, int(_pulse_mfb_gather_top_bands))
        except Exception:
            pass
    _pulse_mfb_gather_lines_per_band = cfg.get("pulse_mfb_gather_lines_per_band")
    if _pulse_mfb_gather_lines_per_band is not None:
        try:
            state["PULSE_MFB_GATHER_LINES_PER_BAND"] = max(1, int(_pulse_mfb_gather_lines_per_band))
        except Exception:
            pass
    _pulse_mfb_gather_min_consumers = cfg.get("pulse_mfb_gather_min_consumers")
    if _pulse_mfb_gather_min_consumers is not None:
        try:
            state["PULSE_MFB_GATHER_MIN_CONSUMERS"] = max(2, int(_pulse_mfb_gather_min_consumers))
        except Exception:
            pass
    _pulse_mfb_gather_window_budget = cfg.get("pulse_mfb_gather_window_budget")
    if _pulse_mfb_gather_window_budget is not None:
        try:
            state["PULSE_MFB_GATHER_WINDOW_BUDGET"] = max(0, int(_pulse_mfb_gather_window_budget))
        except Exception:
            pass
    _pulse_prebase_shared_lookup_enable = cfg.get("pulse_prebase_shared_lookup_enable")
    if _pulse_prebase_shared_lookup_enable is not None:
        state["PULSE_PREBASE_SHARED_LOOKUP_ENABLE"] = 1 if bool(_pulse_prebase_shared_lookup_enable) else 0
    _pulse_osa_enable = cfg.get("pulse_osa_enable")
    if _pulse_osa_enable is not None:
        state["PULSE_OSA_ENABLE"] = 1 if bool(_pulse_osa_enable) else 0
    _pulse_osa_shared_weight_owner_enable = cfg.get("pulse_osa_shared_weight_owner_enable")
    if _pulse_osa_shared_weight_owner_enable is not None:
        state["PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE"] = (
            1 if bool(_pulse_osa_shared_weight_owner_enable) else 0
        )
    _pulse_osa_shared_weight_owner_actual_enable = cfg.get("pulse_osa_shared_weight_owner_actual_enable")
    if _pulse_osa_shared_weight_owner_actual_enable is not None:
        state["PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE"] = (
            1 if bool(_pulse_osa_shared_weight_owner_actual_enable) else 0
        )
    _pulse_osa_metadata_txn_enable = cfg.get("pulse_osa_metadata_txn_enable")
    if _pulse_osa_metadata_txn_enable is not None:
        state["PULSE_OSA_METADATA_TXN_ENABLE"] = (
            1 if bool(_pulse_osa_metadata_txn_enable) else 0
        )
    _pulse_osa_metadata_ready_lease_enable = cfg.get("pulse_osa_metadata_ready_lease_enable")
    if _pulse_osa_metadata_ready_lease_enable is not None:
        state["PULSE_OSA_METADATA_READY_LEASE_ENABLE"] = (
            1 if bool(_pulse_osa_metadata_ready_lease_enable) else 0
        )
    _pulse_osa_metadata_ready_lease_ttl = cfg.get("pulse_osa_metadata_ready_lease_ttl")
    if _pulse_osa_metadata_ready_lease_ttl is not None:
        try:
            state["PULSE_OSA_METADATA_READY_LEASE_TTL"] = max(
                0, int(_pulse_osa_metadata_ready_lease_ttl)
            )
        except Exception:
            pass
    _pulse_osa_metadata_object_mask = cfg.get("pulse_osa_metadata_object_mask")
    if isinstance(_pulse_osa_metadata_object_mask, str) and _pulse_osa_metadata_object_mask.strip():
        state["PULSE_OSA_METADATA_OBJECT_MASK"] = _pulse_osa_metadata_object_mask.strip().lower()
    _pulse_ingress_entries = cfg.get("pulse_ingress_entries")
    if _pulse_ingress_entries is not None:
        try:
            state["PULSE_INGRESS_ENTRIES"] = max(0, int(_pulse_ingress_entries))
        except Exception:
            pass
    _pulse_core_queue_entries = cfg.get("pulse_core_queue_entries")
    if _pulse_core_queue_entries is not None:
        try:
            state["PULSE_CORE_QUEUE_ENTRIES"] = max(0, int(_pulse_core_queue_entries))
        except Exception:
            pass
    _pulse_descriptor_packet_min = cfg.get("pulse_descriptor_packet_min")
    if _pulse_descriptor_packet_min is not None:
        try:
            state["PULSE_DESCRIPTOR_PACKET_MIN"] = max(1, int(_pulse_descriptor_packet_min))
        except Exception:
            pass
    _pulse_bypass_high_watermark_pct = cfg.get("pulse_bypass_high_watermark_pct")
    if _pulse_bypass_high_watermark_pct is not None:
        try:
            state["PULSE_BYPASS_HIGH_WATERMARK_PCT"] = max(1, min(100, int(_pulse_bypass_high_watermark_pct)))
        except Exception:
            pass
    _pulse_bypass_mode = cfg.get("pulse_bypass_mode")
    if isinstance(_pulse_bypass_mode, str) and _pulse_bypass_mode.strip():
        _pulse_bypass_mode_norm = _pulse_bypass_mode.strip().lower()
        if _pulse_bypass_mode_norm in ("disabled", "high_watermark"):
            state["PULSE_BYPASS_MODE"] = _pulse_bypass_mode_norm
    _thermal_enable = cfg.get("thermal_enable")
    if _thermal_enable is not None:
        state["THERMAL_ENABLE"] = 1 if bool(_thermal_enable) else 0
    _thermal_backend = _normalize_thermal_backend(cfg.get("thermal_backend"))
    if _thermal_backend:
        state["THERMAL_BACKEND"] = _thermal_backend
    _thermal_window_ns = cfg.get("thermal_window_ns")
    if _thermal_window_ns is not None:
        try:
            state["THERMAL_WINDOW_NS"] = max(1, int(_thermal_window_ns))
        except Exception:
            pass
    _thermal_window_trace_enable = cfg.get("thermal_window_trace_enable")
    if _thermal_window_trace_enable is not None:
        state["THERMAL_WINDOW_TRACE_ENABLE"] = 1 if bool(_thermal_window_trace_enable) else 0
    _thermal_window_trace_max_rows = cfg.get("thermal_window_trace_max_rows")
    if _thermal_window_trace_max_rows is not None:
        try:
            state["THERMAL_WINDOW_TRACE_MAX_ROWS"] = max(1, int(_thermal_window_trace_max_rows))
        except Exception:
            pass
    _thermal_include_memctrl = cfg.get("thermal_include_memctrl")
    if _thermal_include_memctrl is not None:
        state["THERMAL_INCLUDE_MEMCTRL"] = 1 if bool(_thermal_include_memctrl) else 0
    _thermal_out_dir = cfg.get("thermal_out_dir")
    if isinstance(_thermal_out_dir, str) and _thermal_out_dir.strip():
        state["THERMAL_OUT_DIR"] = _thermal_out_dir.strip()
    _thermal_hotspot_bin = cfg.get("thermal_hotspot_bin")
    if isinstance(_thermal_hotspot_bin, str) and _thermal_hotspot_bin.strip():
        state["THERMAL_HOTSPOT_BIN"] = _thermal_hotspot_bin.strip()
    _thermal_generate_floorplan = cfg.get("thermal_generate_floorplan")
    if _thermal_generate_floorplan is not None:
        state["THERMAL_GENERATE_FLOORPLAN"] = 1 if bool(_thermal_generate_floorplan) else 0
    _thermal_model_type = _normalize_thermal_model_type(cfg.get("thermal_model_type"))
    if _thermal_model_type:
        state["THERMAL_MODEL_TYPE"] = _thermal_model_type
    _thermal_grid_rows = cfg.get("thermal_grid_rows")
    if _thermal_grid_rows is not None:
        try:
            state["THERMAL_GRID_ROWS"] = max(1, int(_thermal_grid_rows))
        except Exception:
            pass
    _thermal_grid_cols = cfg.get("thermal_grid_cols")
    if _thermal_grid_cols is not None:
        try:
            state["THERMAL_GRID_COLS"] = max(1, int(_thermal_grid_cols))
        except Exception:
            pass
    _thermal_grid_map_mode = _normalize_thermal_grid_map_mode(cfg.get("thermal_grid_map_mode"))
    if _thermal_grid_map_mode:
        state["THERMAL_GRID_MAP_MODE"] = _thermal_grid_map_mode
    _thermal_detailed_3d = cfg.get("thermal_detailed_3d")
    if _thermal_detailed_3d is not None:
        state["THERMAL_DETAILED_3D"] = 1 if bool(_thermal_detailed_3d) else 0
    _thermal_layers = cfg.get("thermal_layers")
    if isinstance(_thermal_layers, list):
        state["THERMAL_LAYERS"] = list(_thermal_layers)
    _thermal_tile_width_um = cfg.get("thermal_tile_width_um")
    if _thermal_tile_width_um is not None:
        try:
            state["THERMAL_TILE_WIDTH_UM"] = max(1, int(_thermal_tile_width_um))
        except Exception:
            pass
    _thermal_tile_height_um = cfg.get("thermal_tile_height_um")
    if _thermal_tile_height_um is not None:
        try:
            state["THERMAL_TILE_HEIGHT_UM"] = max(1, int(_thermal_tile_height_um))
        except Exception:
            pass
    _thermal_tile_gap_um = cfg.get("thermal_tile_gap_um")
    if _thermal_tile_gap_um is not None:
        try:
            state["THERMAL_TILE_GAP_UM"] = max(0, int(_thermal_tile_gap_um))
        except Exception:
            pass
    _thermal_comp_frac = cfg.get("thermal_comp_frac")
    if _thermal_comp_frac is not None:
        try:
            state["THERMAL_COMP_FRAC"] = max(0.0, float(_thermal_comp_frac))
        except Exception:
            pass
    _thermal_sram_frac = cfg.get("thermal_sram_frac")
    if _thermal_sram_frac is not None:
        try:
            state["THERMAL_SRAM_FRAC"] = max(0.0, float(_thermal_sram_frac))
        except Exception:
            pass
    _thermal_noc_frac = cfg.get("thermal_noc_frac")
    if _thermal_noc_frac is not None:
        try:
            state["THERMAL_NOC_FRAC"] = max(0.0, float(_thermal_noc_frac))
        except Exception:
            pass
    _sram_model_enable = cfg.get("sram_model_enable")
    if _sram_model_enable is not None:
        state["SRAM_MODEL_ENABLE"] = 1 if bool(_sram_model_enable) else 0
    _local_storage_enable = cfg.get("local_storage_enable")
    if _local_storage_enable is not None:
        state["LOCAL_STORAGE_ENABLE"] = 1 if bool(_local_storage_enable) else 0
    _pe_internal_cpe_enable = cfg.get("pe_internal_cpe_enable")
    if _pe_internal_cpe_enable is not None:
        state["PE_INTERNAL_CPE_ENABLE"] = 1 if bool(_pe_internal_cpe_enable) else 0
    _pe_internal_pod_enable = cfg.get("pe_internal_pod_enable")
    if _pe_internal_pod_enable is not None:
        state["PE_INTERNAL_POD_ENABLE"] = 1 if bool(_pe_internal_pod_enable) else 0
    _pe_internal_pod_count = cfg.get("pe_internal_pod_count")
    if _pe_internal_pod_count is not None:
        try:
            state["PE_INTERNAL_POD_COUNT"] = max(0, int(_pe_internal_pod_count))
        except Exception:
            pass
    _pe_internal_pod_size = cfg.get("pe_internal_pod_size")
    if _pe_internal_pod_size is not None:
        try:
            state["PE_INTERNAL_POD_SIZE"] = max(0, int(_pe_internal_pod_size))
        except Exception:
            pass
    _pe_internal_pod_metadata_enable = cfg.get("pe_internal_pod_metadata_enable")
    if _pe_internal_pod_metadata_enable is not None:
        state["PE_INTERNAL_POD_METADATA_ENABLE"] = 1 if bool(_pe_internal_pod_metadata_enable) else 0
    _pe_internal_pod_owner_enable = cfg.get("pe_internal_pod_owner_enable")
    if _pe_internal_pod_owner_enable is not None:
        state["PE_INTERNAL_POD_OWNER_ENABLE"] = 1 if bool(_pe_internal_pod_owner_enable) else 0
    _pe_internal_pod_join_enable = cfg.get("pe_internal_pod_join_enable")
    if _pe_internal_pod_join_enable is not None:
        state["PE_INTERNAL_POD_JOIN_ENABLE"] = 1 if bool(_pe_internal_pod_join_enable) else 0
    _pe_internal_pod_ready_enable = cfg.get("pe_internal_pod_ready_enable")
    if _pe_internal_pod_ready_enable is not None:
        state["PE_INTERNAL_POD_READY_ENABLE"] = 1 if bool(_pe_internal_pod_ready_enable) else 0
    _pe_internal_pod_owner_entries = cfg.get("pe_internal_pod_owner_entries")
    if _pe_internal_pod_owner_entries is not None:
        try:
            state["PE_INTERNAL_POD_OWNER_ENTRIES"] = max(0, int(_pe_internal_pod_owner_entries))
        except Exception:
            pass
    _pe_internal_pod_join_entries = cfg.get("pe_internal_pod_join_entries")
    if _pe_internal_pod_join_entries is not None:
        try:
            state["PE_INTERNAL_POD_JOIN_ENTRIES"] = max(0, int(_pe_internal_pod_join_entries))
        except Exception:
            pass
    _pe_internal_pod_ready_entries = cfg.get("pe_internal_pod_ready_entries")
    if _pe_internal_pod_ready_entries is not None:
        try:
            state["PE_INTERNAL_POD_READY_ENTRIES"] = max(0, int(_pe_internal_pod_ready_entries))
        except Exception:
            pass
    _sram_calib_json = cfg.get("sram_calib_json")
    if isinstance(_sram_calib_json, str) and _sram_calib_json.strip():
        state["SRAM_CALIB_JSON"] = _resolve_path_under_project(_sram_calib_json.strip())
    _sram_calib_strict = cfg.get("sram_calib_strict")
    if _sram_calib_strict is not None:
        state["SRAM_CALIB_STRICT"] = 1 if bool(_sram_calib_strict) else 0
    _sram_weight_idx_enable = cfg.get("sram_weight_idx_enable")
    if _sram_weight_idx_enable is not None:
        state["SRAM_WEIGHT_IDX_ENABLE"] = 1 if bool(_sram_weight_idx_enable) else 0
    _sram_weight_l0_enable = cfg.get("sram_weight_l0_enable")
    if _sram_weight_l0_enable is not None:
        state["SRAM_WEIGHT_L0_ENABLE"] = 1 if bool(_sram_weight_l0_enable) else 0
    _sram_state_enable = cfg.get("sram_state_enable")
    if _sram_state_enable is not None:
        state["SRAM_STATE_ENABLE"] = 1 if bool(_sram_state_enable) else 0

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
    _sseedonly = cfg.get("step_seed_only_mode")
    if _sseedonly is not None:
        state["STEP_SEED_ONLY_MODE"] = 1 if bool(_sseedonly) else 0
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

    # Apply-stage memory throttles (optional):
    # - max_outstanding_requests: per-core inflight read cap (>0).
    # - window_read_budget: per-window read issue budget (>=0, 0 disables budget).
    _mor = cfg.get("max_outstanding_requests")
    if _mor is not None:
        try:
            v = int(_mor)
            if v > 0:
                state["MAX_OUTSTANDING_REQUESTS_OVERRIDE"] = v
            else:
                mesh_print(
                    f"[mesh] ignore invalid local_run_config.json max_outstanding_requests={_mor!r} "
                    "(expected >0)"
                )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid local_run_config.json max_outstanding_requests={_mor!r} "
                "(expected int)"
            )
    _wrb = cfg.get("window_read_budget")
    if _wrb is not None:
        try:
            v = int(_wrb)
            if v >= 0:
                state["WINDOW_READ_BUDGET_OVERRIDE"] = v
            else:
                mesh_print(
                    f"[mesh] ignore invalid local_run_config.json window_read_budget={_wrb!r} "
                    "(expected >=0)"
                )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid local_run_config.json window_read_budget={_wrb!r} "
                "(expected int)"
            )

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
    _env_seed_only = os.environ.get("MESH_STEP_SEED_ONLY_MODE", "").strip().lower()
    if _env_seed_only:
        if _env_seed_only in ("1", "true", "yes", "y", "on"):
            state["STEP_SEED_ONLY_MODE"] = 1
            mesh_print(f"[mesh] override STEP_SEED_ONLY_MODE=1 via MESH_STEP_SEED_ONLY_MODE={_env_seed_only}")
        elif _env_seed_only in ("0", "false", "no", "n", "off"):
            state["STEP_SEED_ONLY_MODE"] = 0
            mesh_print(f"[mesh] override STEP_SEED_ONLY_MODE=0 via MESH_STEP_SEED_ONLY_MODE={_env_seed_only}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_STEP_SEED_ONLY_MODE={_env_seed_only!r} (expected 0/1/true/false)")
    _env_gsv = os.environ.get("MESH_GLOBAL_STEP_CTRL_VERBOSE", "").strip()
    if _env_gsv:
        try:
            state["GLOBAL_STEP_CTRL_VERBOSE"] = int(_env_gsv)
            mesh_print(f"[mesh] override GLOBAL_STEP_CTRL_VERBOSE={state['GLOBAL_STEP_CTRL_VERBOSE']} via MESH_GLOBAL_STEP_CTRL_VERBOSE={_env_gsv}")
        except Exception:
            pass

    # Apply-stage memory throttles env override (priority: env > local_run_config.json).
    _env_mor = os.environ.get("MESH_MAX_OUTSTANDING_REQUESTS", "").strip()
    if _env_mor:
        try:
            v = int(_env_mor)
            if v > 0:
                state["MAX_OUTSTANDING_REQUESTS_OVERRIDE"] = v
                mesh_print(
                    f"[mesh] override max_outstanding_requests={state['MAX_OUTSTANDING_REQUESTS_OVERRIDE']} "
                    f"via MESH_MAX_OUTSTANDING_REQUESTS={_env_mor}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_MAX_OUTSTANDING_REQUESTS={_env_mor!r} "
                    "(expected >0)"
                )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid MESH_MAX_OUTSTANDING_REQUESTS={_env_mor!r} "
                "(expected int)"
            )

    _env_wrb = os.environ.get("MESH_WINDOW_READ_BUDGET", "").strip()
    if _env_wrb:
        try:
            v = int(_env_wrb)
            if v >= 0:
                state["WINDOW_READ_BUDGET_OVERRIDE"] = v
                mesh_print(
                    f"[mesh] override window_read_budget={state['WINDOW_READ_BUDGET_OVERRIDE']} "
                    f"via MESH_WINDOW_READ_BUDGET={_env_wrb}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_WINDOW_READ_BUDGET={_env_wrb!r} "
                    "(expected >=0)"
                )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid MESH_WINDOW_READ_BUDGET={_env_wrb!r} "
                "(expected int)"
            )

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

    _env_noc = _normalize_noc_type(os.environ.get("MESH_NOC_TYPE", ""))
    if _env_noc:
        state["SPEC_NOC_TYPE"] = _env_noc
        mesh_print(f"[mesh] override SPEC_NOC_TYPE={state['SPEC_NOC_TYPE']} via MESH_NOC_TYPE={os.environ.get('MESH_NOC_TYPE', '').strip()}")

    _env_mcast_enable = os.environ.get("MESH_MULTICAST_ENABLE", "").strip().lower()
    if _env_mcast_enable:
        if _env_mcast_enable in ("1", "true", "yes", "y", "on"):
            state["SPEC_MULTICAST_ENABLE"] = True
            mesh_print("[mesh] override SPEC_MULTICAST_ENABLE=1 via MESH_MULTICAST_ENABLE")
        elif _env_mcast_enable in ("0", "false", "no", "n", "off"):
            state["SPEC_MULTICAST_ENABLE"] = False
            mesh_print("[mesh] override SPEC_MULTICAST_ENABLE=0 via MESH_MULTICAST_ENABLE")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_MULTICAST_ENABLE={_env_mcast_enable!r} (expected 0/1/true/false)")

    _env_mcast_block_w = os.environ.get("MESH_MULTICAST_BLOCK_W", "").strip()
    if _env_mcast_block_w:
        try:
            v = int(_env_mcast_block_w)
            if v >= 1:
                state["SPEC_MULTICAST_BLOCK_W"] = v
                mesh_print(f"[mesh] override SPEC_MULTICAST_BLOCK_W={v} via MESH_MULTICAST_BLOCK_W={_env_mcast_block_w}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_MULTICAST_BLOCK_W={_env_mcast_block_w!r} (expected int >=1)")

    _env_mcast_block_h = os.environ.get("MESH_MULTICAST_BLOCK_H", "").strip()
    if _env_mcast_block_h:
        try:
            v = int(_env_mcast_block_h)
            if v >= 1:
                state["SPEC_MULTICAST_BLOCK_H"] = v
                mesh_print(f"[mesh] override SPEC_MULTICAST_BLOCK_H={v} via MESH_MULTICAST_BLOCK_H={_env_mcast_block_h}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_MULTICAST_BLOCK_H={_env_mcast_block_h!r} (expected int >=1)")

    _env_mcast_ingress = os.environ.get("MESH_MULTICAST_INGRESS_POLICY", "").strip()
    if _env_mcast_ingress:
        state["SPEC_MULTICAST_INGRESS_POLICY"] = _env_mcast_ingress
        mesh_print(f"[mesh] override SPEC_MULTICAST_INGRESS_POLICY={_env_mcast_ingress} via MESH_MULTICAST_INGRESS_POLICY={_env_mcast_ingress}")

    _env_mcast_inter = os.environ.get("MESH_MULTICAST_INTER_POLICY", "").strip()
    if _env_mcast_inter:
        state["SPEC_MULTICAST_INTER_POLICY"] = _env_mcast_inter
        mesh_print(f"[mesh] override SPEC_MULTICAST_INTER_POLICY={_env_mcast_inter} via MESH_MULTICAST_INTER_POLICY={_env_mcast_inter}")

    _env_mcast_intra = os.environ.get("MESH_MULTICAST_INTRA_POLICY", "").strip()
    if _env_mcast_intra:
        state["SPEC_MULTICAST_INTRA_POLICY"] = _env_mcast_intra
        mesh_print(f"[mesh] override SPEC_MULTICAST_INTRA_POLICY={_env_mcast_intra} via MESH_MULTICAST_INTRA_POLICY={_env_mcast_intra}")

    _env_local_mcast = os.environ.get("MESH_LOCAL_ENDPOINT_MULTICAST_ENABLE", "").strip().lower()
    if _env_local_mcast:
        if _env_local_mcast in ("1", "true", "yes", "y", "on"):
            state["SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE"] = True
            mesh_print("[mesh] override SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE=1 via MESH_LOCAL_ENDPOINT_MULTICAST_ENABLE")
        elif _env_local_mcast in ("0", "false", "no", "n", "off"):
            state["SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE"] = False
            mesh_print("[mesh] override SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE=0 via MESH_LOCAL_ENDPOINT_MULTICAST_ENABLE")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_LOCAL_ENDPOINT_MULTICAST_ENABLE={_env_local_mcast!r} (expected 0/1/true/false)")

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

    # Synapse weight path env override (priority: env > local_run_config.json).
    _env_swm = os.environ.get("MESH_SYNAPSE_WEIGHT_MODE", "").strip().lower()
    if _env_swm:
        if _env_swm == "gscc_valueonly_dstcore":
            _env_swm = "gcss_valueonly_dstcore"
        if _env_swm == "gscc_valueonly_dstcore_vlf_premphf":
            _env_swm = "gcss_valueonly_dstcore_vlf_premphf"
        if _env_swm == "gscc_valueonly_dstcore_vlf_premphf_plp":
            _env_swm = "gcss_valueonly_dstcore_vlf_premphf_plp"
        if _env_swm in (
            "bcsr_gas",
            "gcss_valueonly_dstcore",
            "gcss_valueonly_dstcore_idx2",
            "gcss_idx2_rowmphf",
            "gcss_valueonly_dstcore_vlf_premphf",
            "gcss_valueonly_dstcore_vlf_premphf_plp",
        ):
            state["SYNAPSE_WEIGHT_MODE"] = _env_swm
            mesh_print(
                f"[mesh] override SYNAPSE_WEIGHT_MODE={state['SYNAPSE_WEIGHT_MODE']} "
                f"via MESH_SYNAPSE_WEIGHT_MODE={_env_swm}"
            )
        else:
            mesh_print(
                f"[mesh] ignore invalid MESH_SYNAPSE_WEIGHT_MODE={_env_swm!r} "
                "(expected bcsr_gas/gcss_valueonly_dstcore/gcss_valueonly_dstcore_idx2/gcss_valueonly_dstcore_vlf_premphf/gcss_valueonly_dstcore_vlf_premphf_plp)"
            )

    _env_gcss_dir = os.environ.get("MESH_GCSS_DIR", "").strip()
    if _env_gcss_dir:
        state["GCSS_DIR"] = _resolve_path_under_project(_env_gcss_dir)
        mesh_print(f"[mesh] override GCSS_DIR={state['GCSS_DIR']} via MESH_GCSS_DIR={_env_gcss_dir}")
    _env_gcss2_dir = os.environ.get("MESH_GCSS2_DIR", "").strip()
    if _env_gcss2_dir:
        state["GCSS2_DIR"] = _resolve_path_under_project(_env_gcss2_dir)
        mesh_print(f"[mesh] override GCSS2_DIR={state['GCSS2_DIR']} via MESH_GCSS2_DIR={_env_gcss2_dir}")
    _env_gcssvlf_dir = os.environ.get("MESH_GCSSVLF_DIR", "").strip()
    if _env_gcssvlf_dir:
        state["GCSSVLF_DIR"] = _resolve_path_under_project(_env_gcssvlf_dir)
        mesh_print(f"[mesh] override GCSSVLF_DIR={state['GCSSVLF_DIR']} via MESH_GCSSVLF_DIR={_env_gcssvlf_dir}")
    _env_gcssplp_dir = os.environ.get("MESH_GCSSPLP_DIR", "").strip()
    if _env_gcssplp_dir:
        state["GCSSPLP_DIR"] = _resolve_path_under_project(_env_gcssplp_dir)
        mesh_print(f"[mesh] override GCSSPLP_DIR={state['GCSSPLP_DIR']} via MESH_GCSSPLP_DIR={_env_gcssplp_dir}")
    _env_gcssnt_dir = os.environ.get("MESH_GCSSNT_DIR", "").strip()
    if _env_gcssnt_dir:
        state["GCSSNT_DIR"] = _resolve_path_under_project(_env_gcssnt_dir)
        mesh_print(f"[mesh] override GCSSNT_DIR={state['GCSSNT_DIR']} via MESH_GCSSNT_DIR={_env_gcssnt_dir}")
    _env_gcssplp_profile_export_enable = os.environ.get("MESH_GCSSPLP_PROFILE_EXPORT_ENABLE", "").strip().lower()
    if _env_gcssplp_profile_export_enable:
        state["GCSSPLP_PROFILE_EXPORT_ENABLE"] = 1 if _env_gcssplp_profile_export_enable in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override GCSSPLP_PROFILE_EXPORT_ENABLE={state['GCSSPLP_PROFILE_EXPORT_ENABLE']} "
            f"via MESH_GCSSPLP_PROFILE_EXPORT_ENABLE={_env_gcssplp_profile_export_enable}"
        )
    _env_gcssplp_profile_export_dir = os.environ.get("MESH_GCSSPLP_PROFILE_EXPORT_DIR", "").strip()
    if _env_gcssplp_profile_export_dir:
        state["GCSSPLP_PROFILE_EXPORT_DIR"] = _resolve_path_under_project(_env_gcssplp_profile_export_dir)
        mesh_print(
            f"[mesh] override GCSSPLP_PROFILE_EXPORT_DIR={state['GCSSPLP_PROFILE_EXPORT_DIR']} "
            f"via MESH_GCSSPLP_PROFILE_EXPORT_DIR={_env_gcssplp_profile_export_dir}"
        )
    _env_idx2_ingress_prefetch_enable = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_ENABLE", ""
    ).strip().lower()
    if _env_idx2_ingress_prefetch_enable:
        state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_ENABLE"] = (
            1 if _env_idx2_ingress_prefetch_enable in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"EXPERIMENTAL_IDX2_INGRESS_PREFETCH_ENABLE={state['EXPERIMENTAL_IDX2_INGRESS_PREFETCH_ENABLE']} "
            f"via MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_ENABLE={_env_idx2_ingress_prefetch_enable}"
        )
    _env_idx2_ingress_prefetch_budget_per_tick = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_BUDGET_PER_TICK", ""
    ).strip()
    if _env_idx2_ingress_prefetch_budget_per_tick:
        try:
            _v = int(_env_idx2_ingress_prefetch_budget_per_tick)
            if _v >= 1:
                state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_BUDGET_PER_TICK"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_IDX2_INGRESS_PREFETCH_BUDGET_PER_TICK={state['EXPERIMENTAL_IDX2_INGRESS_PREFETCH_BUDGET_PER_TICK']} "
                    f"via MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_BUDGET_PER_TICK={_env_idx2_ingress_prefetch_budget_per_tick}"
                )
        except Exception:
            pass
    _env_idx2_ingress_prefetch_cache_entries = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CACHE_ENTRIES", ""
    ).strip()
    if _env_idx2_ingress_prefetch_cache_entries:
        try:
            _v = int(_env_idx2_ingress_prefetch_cache_entries)
            if _v >= 1:
                state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CACHE_ENTRIES"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CACHE_ENTRIES={state['EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CACHE_ENTRIES']} "
                    f"via MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CACHE_ENTRIES={_env_idx2_ingress_prefetch_cache_entries}"
                )
        except Exception:
            pass
    _env_idx2_ingress_prefetch_max_inflight = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_MAX_INFLIGHT", ""
    ).strip()
    if _env_idx2_ingress_prefetch_max_inflight:
        try:
            _v = int(_env_idx2_ingress_prefetch_max_inflight)
            if _v >= 0:
                state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_MAX_INFLIGHT"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_IDX2_INGRESS_PREFETCH_MAX_INFLIGHT={state['EXPERIMENTAL_IDX2_INGRESS_PREFETCH_MAX_INFLIGHT']} "
                    f"via MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_MAX_INFLIGHT={_env_idx2_ingress_prefetch_max_inflight}"
                )
        except Exception:
            pass
    _env_idx2_ingress_prefetch_gather_only = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_GATHER_ONLY", ""
    ).strip().lower()
    if _env_idx2_ingress_prefetch_gather_only:
        state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_GATHER_ONLY"] = (
            1 if _env_idx2_ingress_prefetch_gather_only in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"EXPERIMENTAL_IDX2_INGRESS_PREFETCH_GATHER_ONLY={state['EXPERIMENTAL_IDX2_INGRESS_PREFETCH_GATHER_ONLY']} "
            f"via MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_GATHER_ONLY={_env_idx2_ingress_prefetch_gather_only}"
        )
    _env_idx2_ingress_prefetch_carry_to_apply_enable = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CARRY_TO_APPLY_ENABLE", ""
    ).strip().lower()
    if _env_idx2_ingress_prefetch_carry_to_apply_enable:
        state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CARRY_TO_APPLY_ENABLE"] = (
            1
            if _env_idx2_ingress_prefetch_carry_to_apply_enable in ("1", "true", "yes", "y", "on")
            else 0
        )
        mesh_print(
            "[mesh] override "
            f"EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CARRY_TO_APPLY_ENABLE={state['EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CARRY_TO_APPLY_ENABLE']} "
            f"via MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CARRY_TO_APPLY_ENABLE={_env_idx2_ingress_prefetch_carry_to_apply_enable}"
        )
    _env_idx2_ingress_prefetch_apply_max_inflight = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_MAX_INFLIGHT", ""
    ).strip()
    if _env_idx2_ingress_prefetch_apply_max_inflight:
        try:
            _v = int(_env_idx2_ingress_prefetch_apply_max_inflight)
            if _v >= 0:
                state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_MAX_INFLIGHT"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_MAX_INFLIGHT={state['EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_MAX_INFLIGHT']} "
                    f"via MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_MAX_INFLIGHT={_env_idx2_ingress_prefetch_apply_max_inflight}"
                )
        except Exception:
            pass
    _env_idx2_ingress_prefetch_apply_outstanding_reserve = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_OUTSTANDING_RESERVE", ""
    ).strip()
    if _env_idx2_ingress_prefetch_apply_outstanding_reserve:
        try:
            _v = int(_env_idx2_ingress_prefetch_apply_outstanding_reserve)
            if _v >= 0:
                state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_OUTSTANDING_RESERVE"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_OUTSTANDING_RESERVE={state['EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_OUTSTANDING_RESERVE']} "
                    f"via MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_OUTSTANDING_RESERVE={_env_idx2_ingress_prefetch_apply_outstanding_reserve}"
                )
        except Exception:
            pass
    _env_idx2_ingress_prefetch_apply_frontier_keep_pending = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_FRONTIER_KEEP_PENDING", ""
    ).strip()
    if _env_idx2_ingress_prefetch_apply_frontier_keep_pending:
        try:
            _v = int(_env_idx2_ingress_prefetch_apply_frontier_keep_pending)
            if _v >= 0:
                state["EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_FRONTIER_KEEP_PENDING"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_FRONTIER_KEEP_PENDING={state['EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_FRONTIER_KEEP_PENDING']} "
                    f"via MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_FRONTIER_KEEP_PENDING={_env_idx2_ingress_prefetch_apply_frontier_keep_pending}"
                )
        except Exception:
            pass
    _env_idx2_ingress_tail_guard_enable = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_TAIL_GUARD_ENABLE", ""
    ).strip().lower()
    if _env_idx2_ingress_tail_guard_enable:
        state["EXPERIMENTAL_IDX2_INGRESS_TAIL_GUARD_ENABLE"] = (
            1 if _env_idx2_ingress_tail_guard_enable in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"EXPERIMENTAL_IDX2_INGRESS_TAIL_GUARD_ENABLE={state['EXPERIMENTAL_IDX2_INGRESS_TAIL_GUARD_ENABLE']} "
            f"via MESH_EXPERIMENTAL_IDX2_INGRESS_TAIL_GUARD_ENABLE={_env_idx2_ingress_tail_guard_enable}"
        )
    _env_idx2_ingress_budget_adapt_enable = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_ENABLE", ""
    ).strip().lower()
    if _env_idx2_ingress_budget_adapt_enable:
        state["EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_ENABLE"] = (
            1 if _env_idx2_ingress_budget_adapt_enable in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_ENABLE={state['EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_ENABLE']} "
            f"via MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_ENABLE={_env_idx2_ingress_budget_adapt_enable}"
        )
    _env_idx2_ingress_budget_adapt_max_per_tick = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_MAX_PER_TICK", ""
    ).strip()
    if _env_idx2_ingress_budget_adapt_max_per_tick:
        try:
            _v = int(_env_idx2_ingress_budget_adapt_max_per_tick)
            if _v >= 1:
                state["EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_MAX_PER_TICK"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_MAX_PER_TICK={state['EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_MAX_PER_TICK']} "
                    f"via MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_MAX_PER_TICK={_env_idx2_ingress_budget_adapt_max_per_tick}"
                )
        except Exception:
            pass
    _env_idx2_ingress_budget_adapt_q_depth = os.environ.get(
        "MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_Q_DEPTH", ""
    ).strip()
    if _env_idx2_ingress_budget_adapt_q_depth:
        try:
            _v = int(_env_idx2_ingress_budget_adapt_q_depth)
            if _v >= 1:
                state["EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_Q_DEPTH"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_Q_DEPTH={state['EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_Q_DEPTH']} "
                    f"via MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_Q_DEPTH={_env_idx2_ingress_budget_adapt_q_depth}"
                )
        except Exception:
            pass
    _env_noc_rowidx_prefetch_enable = os.environ.get(
        "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_ENABLE", ""
    ).strip().lower()
    if _env_noc_rowidx_prefetch_enable:
        state["EXPERIMENTAL_NOC_ROWIDX_PREFETCH_ENABLE"] = (
            1 if _env_noc_rowidx_prefetch_enable in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"EXPERIMENTAL_NOC_ROWIDX_PREFETCH_ENABLE={state['EXPERIMENTAL_NOC_ROWIDX_PREFETCH_ENABLE']} "
            f"via MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_ENABLE={_env_noc_rowidx_prefetch_enable}"
        )
    _env_noc_rowidx_prefetch_budget_per_tick = os.environ.get(
        "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_BUDGET_PER_TICK", ""
    ).strip()
    if _env_noc_rowidx_prefetch_budget_per_tick:
        try:
            _v = int(_env_noc_rowidx_prefetch_budget_per_tick)
            if _v >= 1:
                state["EXPERIMENTAL_NOC_ROWIDX_PREFETCH_BUDGET_PER_TICK"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_NOC_ROWIDX_PREFETCH_BUDGET_PER_TICK={state['EXPERIMENTAL_NOC_ROWIDX_PREFETCH_BUDGET_PER_TICK']} "
                    f"via MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_BUDGET_PER_TICK={_env_noc_rowidx_prefetch_budget_per_tick}"
                )
        except Exception:
            pass
    _env_noc_rowidx_cache_rows = os.environ.get(
        "MESH_EXPERIMENTAL_NOC_ROWIDX_CACHE_ROWS", ""
    ).strip()
    if _env_noc_rowidx_cache_rows:
        try:
            _v = int(_env_noc_rowidx_cache_rows)
            if _v >= 1:
                state["EXPERIMENTAL_NOC_ROWIDX_CACHE_ROWS"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_NOC_ROWIDX_CACHE_ROWS={state['EXPERIMENTAL_NOC_ROWIDX_CACHE_ROWS']} "
                    f"via MESH_EXPERIMENTAL_NOC_ROWIDX_CACHE_ROWS={_env_noc_rowidx_cache_rows}"
                )
        except Exception:
            pass
    _env_noc_rowidx_prefetch_gather_only = os.environ.get(
        "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_GATHER_ONLY", ""
    ).strip().lower()
    if _env_noc_rowidx_prefetch_gather_only:
        state["EXPERIMENTAL_NOC_ROWIDX_PREFETCH_GATHER_ONLY"] = (
            1 if _env_noc_rowidx_prefetch_gather_only in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"EXPERIMENTAL_NOC_ROWIDX_PREFETCH_GATHER_ONLY={state['EXPERIMENTAL_NOC_ROWIDX_PREFETCH_GATHER_ONLY']} "
            f"via MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_GATHER_ONLY={_env_noc_rowidx_prefetch_gather_only}"
        )
    _env_noc_rowidx_prefetch_detached_enable = os.environ.get(
        "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_DETACHED_ENABLE", ""
    ).strip().lower()
    if _env_noc_rowidx_prefetch_detached_enable:
        state["EXPERIMENTAL_NOC_ROWIDX_PREFETCH_DETACHED_ENABLE"] = (
            1 if _env_noc_rowidx_prefetch_detached_enable in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"EXPERIMENTAL_NOC_ROWIDX_PREFETCH_DETACHED_ENABLE={state['EXPERIMENTAL_NOC_ROWIDX_PREFETCH_DETACHED_ENABLE']} "
            f"via MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_DETACHED_ENABLE={_env_noc_rowidx_prefetch_detached_enable}"
        )
    _env_noc_rowidx_hot_touch_min = os.environ.get(
        "MESH_EXPERIMENTAL_NOC_ROWIDX_HOT_TOUCH_MIN", ""
    ).strip()
    if _env_noc_rowidx_hot_touch_min:
        try:
            _v = int(_env_noc_rowidx_hot_touch_min)
            if _v >= 1:
                state["EXPERIMENTAL_NOC_ROWIDX_HOT_TOUCH_MIN"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_NOC_ROWIDX_HOT_TOUCH_MIN={state['EXPERIMENTAL_NOC_ROWIDX_HOT_TOUCH_MIN']} "
                    f"via MESH_EXPERIMENTAL_NOC_ROWIDX_HOT_TOUCH_MIN={_env_noc_rowidx_hot_touch_min}"
                )
        except Exception:
            pass
    _env_noc_rowidx_budget_adapt_enable = os.environ.get(
        "MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_ENABLE", ""
    ).strip().lower()
    if _env_noc_rowidx_budget_adapt_enable:
        state["EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_ENABLE"] = (
            1 if _env_noc_rowidx_budget_adapt_enable in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_ENABLE={state['EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_ENABLE']} "
            f"via MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_ENABLE={_env_noc_rowidx_budget_adapt_enable}"
        )
    _env_noc_rowidx_budget_adapt_max_per_tick = os.environ.get(
        "MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_MAX_PER_TICK", ""
    ).strip()
    if _env_noc_rowidx_budget_adapt_max_per_tick:
        try:
            _v = int(_env_noc_rowidx_budget_adapt_max_per_tick)
            if _v >= 1:
                state["EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_MAX_PER_TICK"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_MAX_PER_TICK={state['EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_MAX_PER_TICK']} "
                    f"via MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_MAX_PER_TICK={_env_noc_rowidx_budget_adapt_max_per_tick}"
                )
        except Exception:
            pass
    _env_noc_rowidx_budget_adapt_q_depth = os.environ.get(
        "MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_Q_DEPTH", ""
    ).strip()
    if _env_noc_rowidx_budget_adapt_q_depth:
        try:
            _v = int(_env_noc_rowidx_budget_adapt_q_depth)
            if _v >= 1:
                state["EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_Q_DEPTH"] = _v
                mesh_print(
                    "[mesh] override "
                    f"EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_Q_DEPTH={state['EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_Q_DEPTH']} "
                    f"via MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_Q_DEPTH={_env_noc_rowidx_budget_adapt_q_depth}"
                )
        except Exception:
            pass
    _env_gcss_phase_breakdown_enable = os.environ.get("MESH_EXPERIMENTAL_GCSS_PHASE_BREAKDOWN_ENABLE", "").strip().lower()
    if _env_gcss_phase_breakdown_enable:
        state["GCSS_PHASE_BREAKDOWN_ENABLE"] = (
            1 if _env_gcss_phase_breakdown_enable in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            f"[mesh] override GCSS_PHASE_BREAKDOWN_ENABLE={state['GCSS_PHASE_BREAKDOWN_ENABLE']} "
            f"via MESH_EXPERIMENTAL_GCSS_PHASE_BREAKDOWN_ENABLE={_env_gcss_phase_breakdown_enable}"
        )
    _env_retire_shadow_per_post_enable = os.environ.get(
        "MESH_EXPERIMENTAL_RETIRE_SHADOW_PER_POST_ENABLE", ""
    ).strip().lower()
    if _env_retire_shadow_per_post_enable:
        state["RETIRE_SHADOW_PER_POST_ENABLE"] = (
            1 if _env_retire_shadow_per_post_enable in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            f"[mesh] override RETIRE_SHADOW_PER_POST_ENABLE={state['RETIRE_SHADOW_PER_POST_ENABLE']} "
            f"via MESH_EXPERIMENTAL_RETIRE_SHADOW_PER_POST_ENABLE={_env_retire_shadow_per_post_enable}"
        )
    _env_gcss_vlf_queue_policy = os.environ.get(
        "MESH_EXPERIMENTAL_GCSS_VLF_QUEUE_POLICY", ""
    ).strip().lower()
    if _env_gcss_vlf_queue_policy:
        if _env_gcss_vlf_queue_policy in ("locality_first", "banded_line_fair"):
            state["GCSS_VLF_QUEUE_POLICY"] = _env_gcss_vlf_queue_policy
            mesh_print(
                f"[mesh] override GCSS_VLF_QUEUE_POLICY={state['GCSS_VLF_QUEUE_POLICY']} "
                f"via MESH_EXPERIMENTAL_GCSS_VLF_QUEUE_POLICY={_env_gcss_vlf_queue_policy}"
            )
    _env_gcss_vlf_fair_band_size = os.environ.get(
        "MESH_EXPERIMENTAL_GCSS_VLF_FAIR_BAND_SIZE", ""
    ).strip()
    if _env_gcss_vlf_fair_band_size:
        try:
            _v = int(_env_gcss_vlf_fair_band_size)
            if _v >= 1:
                state["GCSS_VLF_FAIR_BAND_SIZE"] = _v
                mesh_print(
                    f"[mesh] override GCSS_VLF_FAIR_BAND_SIZE={state['GCSS_VLF_FAIR_BAND_SIZE']} "
                    f"via MESH_EXPERIMENTAL_GCSS_VLF_FAIR_BAND_SIZE={_env_gcss_vlf_fair_band_size}"
                )
        except Exception:
            pass
    _env_gcss_vlf_bounded_rescue_enable = os.environ.get(
        "MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_ENABLE", ""
    ).strip().lower()
    if _env_gcss_vlf_bounded_rescue_enable:
        state["GCSS_VLF_BOUNDED_RESCUE_ENABLE"] = (
            1 if _env_gcss_vlf_bounded_rescue_enable in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            f"[mesh] override GCSS_VLF_BOUNDED_RESCUE_ENABLE={state['GCSS_VLF_BOUNDED_RESCUE_ENABLE']} "
            f"via MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_ENABLE={_env_gcss_vlf_bounded_rescue_enable}"
        )
    _env_gcss_vlf_bounded_rescue_scan_limit = os.environ.get(
        "MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT", ""
    ).strip()
    if _env_gcss_vlf_bounded_rescue_scan_limit:
        try:
            _v = int(_env_gcss_vlf_bounded_rescue_scan_limit)
            if _v >= 0:
                state["GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT"] = _v
                mesh_print(
                    f"[mesh] override GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT={state['GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT']} "
                    f"via MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_SCAN_LIMIT={_env_gcss_vlf_bounded_rescue_scan_limit}"
                )
        except Exception:
            pass
    _env_gcss_vlf_bounded_rescue_head_wait_cycles = os.environ.get(
        "MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES", ""
    ).strip()
    if _env_gcss_vlf_bounded_rescue_head_wait_cycles:
        try:
            _v = int(_env_gcss_vlf_bounded_rescue_head_wait_cycles)
            if _v >= 0:
                state["GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES"] = _v
                mesh_print(
                    f"[mesh] override GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES={state['GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES']} "
                    f"via MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_HEAD_WAIT_CYCLES={_env_gcss_vlf_bounded_rescue_head_wait_cycles}"
                )
        except Exception:
            pass
    _env_gcss_vlf_bounded_rescue_depth_threshold = os.environ.get(
        "MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD", ""
    ).strip()
    if _env_gcss_vlf_bounded_rescue_depth_threshold:
        try:
            _v = int(_env_gcss_vlf_bounded_rescue_depth_threshold)
            if _v >= 0:
                state["GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD"] = _v
                mesh_print(
                    f"[mesh] override GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD={state['GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD']} "
                    f"via MESH_EXPERIMENTAL_GCSS_VLF_BOUNDED_RESCUE_DEPTH_THRESHOLD={_env_gcss_vlf_bounded_rescue_depth_threshold}"
                )
        except Exception:
            pass
    _env_sram = os.environ.get("MESH_SRAM_MODEL_ENABLE", "").strip().lower()
    if _env_sram:
        if _env_sram in ("1", "true", "yes", "y", "on"):
            state["SRAM_MODEL_ENABLE"] = 1
            mesh_print("[mesh] override SRAM_MODEL_ENABLE=1 via MESH_SRAM_MODEL_ENABLE")
        elif _env_sram in ("0", "false", "no", "n", "off"):
            state["SRAM_MODEL_ENABLE"] = 0
            mesh_print("[mesh] override SRAM_MODEL_ENABLE=0 via MESH_SRAM_MODEL_ENABLE")
        else:
            mesh_print(
                f"[mesh] ignore invalid MESH_SRAM_MODEL_ENABLE={_env_sram!r} "
                "(expected 0/1/true/false)"
            )
    _env_sram_calib = os.environ.get("MESH_SRAM_CALIB_JSON", "").strip()
    if _env_sram_calib:
        state["SRAM_CALIB_JSON"] = _resolve_path_under_project(_env_sram_calib)
        mesh_print(f"[mesh] override SRAM_CALIB_JSON={state['SRAM_CALIB_JSON']} via MESH_SRAM_CALIB_JSON={_env_sram_calib}")
    _env_sram_calib_strict = os.environ.get("MESH_SRAM_CALIB_STRICT", "").strip().lower()
    if _env_sram_calib_strict:
        if _env_sram_calib_strict in ("1", "true", "yes", "y", "on"):
            state["SRAM_CALIB_STRICT"] = 1
            mesh_print("[mesh] override SRAM_CALIB_STRICT=1 via MESH_SRAM_CALIB_STRICT")
        elif _env_sram_calib_strict in ("0", "false", "no", "n", "off"):
            state["SRAM_CALIB_STRICT"] = 0
            mesh_print("[mesh] override SRAM_CALIB_STRICT=0 via MESH_SRAM_CALIB_STRICT")
        else:
            mesh_print(
                f"[mesh] ignore invalid MESH_SRAM_CALIB_STRICT={_env_sram_calib_strict!r} "
                "(expected 0/1/true/false)"
            )
    _env_local_storage_enable = os.environ.get("MESH_LOCAL_STORAGE_ENABLE", "").strip().lower()
    if _env_local_storage_enable:
        if _env_local_storage_enable in ("1", "true", "yes", "y", "on"):
            state["LOCAL_STORAGE_ENABLE"] = 1
        elif _env_local_storage_enable in ("0", "false", "no", "n", "off"):
            state["LOCAL_STORAGE_ENABLE"] = 0
    _env_sram_idx_enable = os.environ.get("MESH_SRAM_WEIGHT_IDX_ENABLE", "").strip().lower()
    if _env_sram_idx_enable:
        if _env_sram_idx_enable in ("1", "true", "yes", "y", "on"):
            state["SRAM_WEIGHT_IDX_ENABLE"] = 1
        elif _env_sram_idx_enable in ("0", "false", "no", "n", "off"):
            state["SRAM_WEIGHT_IDX_ENABLE"] = 0
    _env_sram_l0_enable = os.environ.get("MESH_SRAM_WEIGHT_L0_ENABLE", "").strip().lower()
    if _env_sram_l0_enable:
        if _env_sram_l0_enable in ("1", "true", "yes", "y", "on"):
            state["SRAM_WEIGHT_L0_ENABLE"] = 1
        elif _env_sram_l0_enable in ("0", "false", "no", "n", "off"):
            state["SRAM_WEIGHT_L0_ENABLE"] = 0
    _env_sram_state_enable = os.environ.get("MESH_SRAM_STATE_ENABLE", "").strip().lower()
    if _env_sram_state_enable:
        if _env_sram_state_enable in ("1", "true", "yes", "y", "on"):
            state["SRAM_STATE_ENABLE"] = 1
        elif _env_sram_state_enable in ("0", "false", "no", "n", "off"):
            state["SRAM_STATE_ENABLE"] = 0

    _env_ssram = os.environ.get("MESH_SYNAPSE_SRAM_ENABLE", "").strip().lower()
    if _env_ssram:
        if _env_ssram in ("1", "true", "yes", "y", "on"):
            state["SYNAPSE_SRAM_ENABLE"] = 1
            mesh_print("[mesh] override SYNAPSE_SRAM_ENABLE=1 via MESH_SYNAPSE_SRAM_ENABLE")
        elif _env_ssram in ("0", "false", "no", "n", "off"):
            state["SYNAPSE_SRAM_ENABLE"] = 0
            mesh_print("[mesh] override SYNAPSE_SRAM_ENABLE=0 via MESH_SYNAPSE_SRAM_ENABLE")
        else:
            mesh_print(
                f"[mesh] ignore invalid MESH_SYNAPSE_SRAM_ENABLE={_env_ssram!r} "
                "(expected 0/1/true/false)"
            )

    _env_ssram_bpe = os.environ.get("MESH_SYNAPSE_SRAM_BYTES_PER_EDGE", "").strip()
    if _env_ssram_bpe:
        try:
            v = int(_env_ssram_bpe)
            if v > 0:
                state["SYNAPSE_SRAM_BYTES_PER_EDGE"] = v
                mesh_print(
                    f"[mesh] override SYNAPSE_SRAM_BYTES_PER_EDGE={state['SYNAPSE_SRAM_BYTES_PER_EDGE']} "
                    f"via MESH_SYNAPSE_SRAM_BYTES_PER_EDGE={_env_ssram_bpe}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_SYNAPSE_SRAM_BYTES_PER_EDGE={_env_ssram_bpe!r} "
                    "(expected >0)"
                )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid MESH_SYNAPSE_SRAM_BYTES_PER_EDGE={_env_ssram_bpe!r} "
                "(expected int)"
            )

    _env_ssram_lat = os.environ.get("MESH_SYNAPSE_SRAM_LATENCY_CYCLES", "").strip()
    _env_ssram_lat_alias = os.environ.get("MESH_SYNAPSE_SRAM_LATENCY_NS", "").strip()
    if _env_ssram_lat or _env_ssram_lat_alias:
        raw_lat = _env_ssram_lat if _env_ssram_lat else _env_ssram_lat_alias
        try:
            v = int(raw_lat)
            if v > 0:
                state["SYNAPSE_SRAM_LATENCY_CYCLES"] = v
                env_key = "MESH_SYNAPSE_SRAM_LATENCY_CYCLES" if _env_ssram_lat else "MESH_SYNAPSE_SRAM_LATENCY_NS"
                mesh_print(
                    f"[mesh] override SYNAPSE_SRAM_LATENCY_CYCLES={state['SYNAPSE_SRAM_LATENCY_CYCLES']} "
                    f"via {env_key}={raw_lat}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid synapse SRAM latency={raw_lat!r} (expected >0)"
                )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid synapse SRAM latency={raw_lat!r} (expected int)"
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

    # Experimental: VLF knobs (priority: env > local_run_config.json).
    _env_vlf = os.environ.get("MESH_GAS_VLF_ENABLE", "").strip().lower()
    if _env_vlf:
        if _env_vlf in ("1", "true", "yes", "y", "on"):
            state["_GAS_VLF_ENABLE"] = 1
            mesh_print(f"[mesh] override GAS vlf_enable=1 via MESH_GAS_VLF_ENABLE={_env_vlf}")
        elif _env_vlf in ("0", "false", "no", "n", "off"):
            state["_GAS_VLF_ENABLE"] = 0
            mesh_print(f"[mesh] override GAS vlf_enable=0 via MESH_GAS_VLF_ENABLE={_env_vlf}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_VLF_ENABLE={_env_vlf!r} (expected 0/1/true/false)")

    _env_vlf_run = os.environ.get("MESH_GAS_VLF_RUN_ENABLE", "").strip().lower()
    if _env_vlf_run:
        if _env_vlf_run in ("1", "true", "yes", "y", "on"):
            state["_GAS_VLF_RUN_ENABLE"] = 1
            mesh_print(f"[mesh] override GAS vlf_run_enable=1 via MESH_GAS_VLF_RUN_ENABLE={_env_vlf_run}")
        elif _env_vlf_run in ("0", "false", "no", "n", "off"):
            state["_GAS_VLF_RUN_ENABLE"] = 0
            mesh_print(f"[mesh] override GAS vlf_run_enable=0 via MESH_GAS_VLF_RUN_ENABLE={_env_vlf_run}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_GAS_VLF_RUN_ENABLE={_env_vlf_run!r} (expected 0/1/true/false)")

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
            if _v == "order":
                state["_GAS_APPLY_ISSUE_POLICY"] = _v
                mesh_print(
                    f"[mesh] override GAS apply_issue_policy={state['_GAS_APPLY_ISSUE_POLICY']} via local_run_config.json gas_apply_issue_policy={_gaip}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid local_run_config.json gas_apply_issue_policy={_gaip!r} (expected order)"
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

        # Experimental: DRAM command-cost guided merge guardrails (segment-build stage).
        _v = cfg.get("gas_dram_cmd_cost_merge_enable")
        if _v is not None:
            state["_GAS_DRAM_CMD_COST_MERGE_ENABLE"] = 1 if bool(_v) else 0
            mesh_print(
                f"[mesh] override GAS dram_cmd_cost_merge_enable={state['_GAS_DRAM_CMD_COST_MERGE_ENABLE']} via local_run_config.json gas_dram_cmd_cost_merge_enable={_v}"
            )
        _v = cfg.get("gas_dram_cmd_offline_model_enable")
        if (not gas_dram_cmd_offline_model_env_present) and _v is not None:
            state["_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE"] = 1 if bool(_v) else 0
            mesh_print(
                f"[mesh] override GAS dram_cmd_offline_model_enable={state['_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE']} via local_run_config.json gas_dram_cmd_offline_model_enable={_v}"
            )
        _v = cfg.get("gas_dram_cmd_offline_model_strict")
        if (not gas_dram_cmd_offline_model_strict_env_present) and _v is not None:
            state["_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT"] = 1 if bool(_v) else 0
            mesh_print(
                f"[mesh] override GAS dram_cmd_offline_model_strict={state['_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT']} via local_run_config.json gas_dram_cmd_offline_model_strict={_v}"
            )
        _v = cfg.get("gas_dram_cmd_t_row_hit_ns")
        if _v is not None:
            try:
                _iv = int(_v)
                if _iv >= 1:
                    state["_GAS_DRAM_CMD_T_ROW_HIT_NS"] = _iv
                    state["_GAS_DRAM_CMD_T_ROW_HIT_EXPLICIT"] = 1
                    mesh_print(
                        f"[mesh] override GAS dram_cmd_t_row_hit_ns={state['_GAS_DRAM_CMD_T_ROW_HIT_NS']} via local_run_config.json gas_dram_cmd_t_row_hit_ns={_v}"
                    )
            except Exception:
                pass
        _v = cfg.get("gas_dram_cmd_t_row_miss_ns")
        if _v is not None:
            try:
                _iv = int(_v)
                if _iv >= 1:
                    state["_GAS_DRAM_CMD_T_ROW_MISS_NS"] = _iv
                    state["_GAS_DRAM_CMD_T_ROW_MISS_EXPLICIT"] = 1
                    mesh_print(
                        f"[mesh] override GAS dram_cmd_t_row_miss_ns={state['_GAS_DRAM_CMD_T_ROW_MISS_NS']} via local_run_config.json gas_dram_cmd_t_row_miss_ns={_v}"
                    )
            except Exception:
                pass

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
    _noc_type = _normalize_noc_type(cfg.get("noc_type"))
    if _noc_type:
        state["SPEC_NOC_TYPE"] = _noc_type
    _mcast_enable = cfg.get("multicast_enable")
    if _mcast_enable is not None:
        state["SPEC_MULTICAST_ENABLE"] = bool(_mcast_enable)
    _mcast_block_w = cfg.get("multicast_block_w")
    if _mcast_block_w is not None:
        try:
            if int(_mcast_block_w) >= 1:
                state["SPEC_MULTICAST_BLOCK_W"] = int(_mcast_block_w)
        except Exception:
            pass
    _mcast_block_h = cfg.get("multicast_block_h")
    if _mcast_block_h is not None:
        try:
            if int(_mcast_block_h) >= 1:
                state["SPEC_MULTICAST_BLOCK_H"] = int(_mcast_block_h)
        except Exception:
            pass
    _mcast_ingress = cfg.get("multicast_ingress_policy")
    if isinstance(_mcast_ingress, str) and _mcast_ingress.strip():
        state["SPEC_MULTICAST_INGRESS_POLICY"] = _mcast_ingress.strip()
    _mcast_inter = cfg.get("multicast_inter_policy")
    if isinstance(_mcast_inter, str) and _mcast_inter.strip():
        state["SPEC_MULTICAST_INTER_POLICY"] = _mcast_inter.strip()
    _mcast_intra = cfg.get("multicast_intra_policy")
    if isinstance(_mcast_intra, str) and _mcast_intra.strip():
        state["SPEC_MULTICAST_INTRA_POLICY"] = _mcast_intra.strip()
    _local_mcast = cfg.get("local_endpoint_multicast_enable")
    if _local_mcast is not None:
        state["SPEC_LOCAL_ENDPOINT_MULTICAST_ENABLE"] = bool(_local_mcast)
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
    apply_banked_env_present = False
    apply_credit_env_present = False
    apply_age_env_present = False
    dram_cmd_offline_model_env_present = False
    dram_cmd_offline_model_strict_env_present = False

    if experimental_enable:
        apply_policy_raw = os.environ.get("MESH_GAS_APPLY_ISSUE_POLICY", "").strip().lower()
        apply_policy_env_present = bool(apply_policy_raw)
        if apply_policy_raw:
            if apply_policy_raw == "order":
                state["_GAS_APPLY_ISSUE_POLICY"] = apply_policy_raw
                mesh_print(
                    f"[mesh] override GAS apply_issue_policy={state['_GAS_APPLY_ISSUE_POLICY']} via MESH_GAS_APPLY_ISSUE_POLICY={apply_policy_raw}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_GAS_APPLY_ISSUE_POLICY={apply_policy_raw!r} (expected order)"
                )

        # Experimental: DRAM command-cost guided merge guardrails (segment-build stage).
        _env = os.environ.get("MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE", "").strip().lower()
        if _env:
            if _env in ("1", "true", "yes", "y", "on"):
                state["_GAS_DRAM_CMD_COST_MERGE_ENABLE"] = 1
                mesh_print(
                    f"[mesh] override GAS dram_cmd_cost_merge_enable=1 via MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE={_env}"
                )
            elif _env in ("0", "false", "no", "n", "off"):
                state["_GAS_DRAM_CMD_COST_MERGE_ENABLE"] = 0
                mesh_print(
                    f"[mesh] override GAS dram_cmd_cost_merge_enable=0 via MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE={_env}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE={_env!r} (expected 0/1/true/false)"
                )
        _env = os.environ.get("MESH_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE", "").strip().lower()
        dram_cmd_offline_model_env_present = bool(_env)
        if _env:
            if _env in ("1", "true", "yes", "y", "on"):
                state["_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE"] = 1
                mesh_print(
                    f"[mesh] override GAS dram_cmd_offline_model_enable=1 via MESH_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE={_env}"
                )
            elif _env in ("0", "false", "no", "n", "off"):
                state["_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE"] = 0
                mesh_print(
                    f"[mesh] override GAS dram_cmd_offline_model_enable=0 via MESH_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE={_env}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE={_env!r} (expected 0/1/true/false)"
                )
        _env = os.environ.get("MESH_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT", "").strip().lower()
        dram_cmd_offline_model_strict_env_present = bool(_env)
        if _env:
            if _env in ("1", "true", "yes", "y", "on"):
                state["_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT"] = 1
                mesh_print(
                    f"[mesh] override GAS dram_cmd_offline_model_strict=1 via MESH_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT={_env}"
                )
            elif _env in ("0", "false", "no", "n", "off"):
                state["_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT"] = 0
                mesh_print(
                    f"[mesh] override GAS dram_cmd_offline_model_strict=0 via MESH_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT={_env}"
                )
            else:
                mesh_print(
                    f"[mesh] ignore invalid MESH_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT={_env!r} (expected 0/1/true/false)"
                )
        _env = os.environ.get("MESH_GAS_DRAM_CMD_T_ROW_HIT_NS", "").strip()
        if _env:
            try:
                v = int(_env)
                if v >= 1:
                    state["_GAS_DRAM_CMD_T_ROW_HIT_NS"] = v
                    state["_GAS_DRAM_CMD_T_ROW_HIT_EXPLICIT"] = 1
                    mesh_print(
                        f"[mesh] override GAS dram_cmd_t_row_hit_ns={state['_GAS_DRAM_CMD_T_ROW_HIT_NS']} via MESH_GAS_DRAM_CMD_T_ROW_HIT_NS={_env}"
                    )
            except Exception as e:
                mesh_print(f"[mesh] ignore invalid MESH_GAS_DRAM_CMD_T_ROW_HIT_NS={_env}: {e}")
        _env = os.environ.get("MESH_GAS_DRAM_CMD_T_ROW_MISS_NS", "").strip()
        if _env:
            try:
                v = int(_env)
                if v >= 1:
                    state["_GAS_DRAM_CMD_T_ROW_MISS_NS"] = v
                    state["_GAS_DRAM_CMD_T_ROW_MISS_EXPLICIT"] = 1
                    mesh_print(
                        f"[mesh] override GAS dram_cmd_t_row_miss_ns={state['_GAS_DRAM_CMD_T_ROW_MISS_NS']} via MESH_GAS_DRAM_CMD_T_ROW_MISS_NS={_env}"
                    )
            except Exception as e:
                mesh_print(f"[mesh] ignore invalid MESH_GAS_DRAM_CMD_T_ROW_MISS_NS={_env}: {e}")
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
            "MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE",
            "MESH_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE",
            "MESH_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT",
            "MESH_GAS_DRAM_CMD_T_ROW_HIT_NS",
            "MESH_GAS_DRAM_CMD_T_ROW_MISS_NS",
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
        "gas_dram_cmd_offline_model_env_present": dram_cmd_offline_model_env_present,
        "gas_dram_cmd_offline_model_strict_env_present": dram_cmd_offline_model_strict_env_present,
    }


def apply_pulse_env_overrides(*, state: Dict[str, Any]) -> None:
    experimental_enable = (os.environ.get("MESH_EXPERIMENTAL_ENABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
    )
    if not experimental_enable:
        ignored = []
        for k in (
            "MESH_PULSE_ENABLE",
            "MESH_PULSE_OBSERVE_ONLY",
            "MESH_PULSE_INGRESS_ENABLE",
            "MESH_PULSE_AGENDA_OBSERVE_ONLY",
            "MESH_PULSE_HARBOR_ENABLE",
            "MESH_PULSE_DESCRIPTOR_ENABLE",
            "MESH_PULSE_DESCRIPTOR_ACTUAL_ENABLE",
            "MESH_PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE",
            "MESH_PULSE_DOMAIN_RETIRE_ENABLE",
            "MESH_PULSE_DOMAIN_RETIRE_OBSERVE_ONLY",
            "MESH_PULSE_DOMAIN_RETIRE_MODE",
            "MESH_PULSE_DOMAIN_RETIRE_RELEASE_BUDGET",
            "MESH_PULSE_FRONTIER_OBSERVE_ENABLE",
            "MESH_PULSE_FRONTIER_TOP_LINES",
            "MESH_PULSE_METADATA_FRONTIER_OBSERVE_ENABLE",
            "MESH_PULSE_METADATA_FRONTIER_TOP_ITEMS",
            "MESH_PULSE_METADATA_FRONTIER_BAND_SLOTS",
            "MESH_PULSE_METADATA_SEED_ENABLE",
            "MESH_PULSE_METADATA_SEED_TOP_BASES",
            "MESH_PULSE_METADATA_SEED_WINDOW_BUDGET",
            "MESH_PULSE_MFB_PREBAND_SEED_ENABLE",
            "MESH_PULSE_MFB_PREBAND_TOP_BANDS",
            "MESH_PULSE_MFB_PREBAND_LINES_PER_BAND",
            "MESH_PULSE_MFB_PREBAND_BAND_SLOTS",
            "MESH_PULSE_MFB_PREBAND_WINDOW_BUDGET",
            "MESH_PULSE_MFB_GATHER_PREBAND_ENABLE",
            "MESH_PULSE_MFB_GATHER_BARRIER_ENABLE",
            "MESH_PULSE_MFB_GATHER_TOP_BANDS",
            "MESH_PULSE_MFB_GATHER_LINES_PER_BAND",
            "MESH_PULSE_MFB_GATHER_MIN_CONSUMERS",
            "MESH_PULSE_MFB_GATHER_WINDOW_BUDGET",
            "MESH_PULSE_PREBASE_SHARED_LOOKUP_ENABLE",
            "MESH_PULSE_OSA_ENABLE",
            "MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE",
            "MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE",
            "MESH_PULSE_OSA_METADATA_TXN_ENABLE",
            "MESH_PULSE_OSA_METADATA_READY_LEASE_ENABLE",
            "MESH_PULSE_OSA_METADATA_READY_LEASE_TTL",
            "MESH_PULSE_OSA_METADATA_OBJECT_MASK",
            "MESH_PULSE_INGRESS_ENTRIES",
            "MESH_PULSE_CORE_QUEUE_ENTRIES",
            "MESH_PULSE_DESCRIPTOR_PACKET_MIN",
            "MESH_PULSE_BYPASS_HIGH_WATERMARK_PCT",
            "MESH_PULSE_BYPASS_MODE",
            "MESH_PE_INTERNAL_CPE_ENABLE",
            "MESH_PE_INTERNAL_POD_ENABLE",
            "MESH_PE_INTERNAL_POD_COUNT",
            "MESH_PE_INTERNAL_POD_SIZE",
            "MESH_PE_INTERNAL_POD_METADATA_ENABLE",
            "MESH_PE_INTERNAL_POD_OWNER_ENABLE",
            "MESH_PE_INTERNAL_POD_JOIN_ENABLE",
            "MESH_PE_INTERNAL_POD_READY_ENABLE",
            "MESH_PE_INTERNAL_POD_OWNER_ENTRIES",
            "MESH_PE_INTERNAL_POD_JOIN_ENTRIES",
            "MESH_PE_INTERNAL_POD_READY_ENTRIES",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_ENABLE",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_BUDGET_PER_TICK",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CACHE_ENTRIES",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_MAX_INFLIGHT",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_GATHER_ONLY",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_CARRY_TO_APPLY_ENABLE",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_MAX_INFLIGHT",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_PREFETCH_APPLY_OUTSTANDING_RESERVE",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_TAIL_GUARD_ENABLE",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_ENABLE",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_MAX_PER_TICK",
            "MESH_EXPERIMENTAL_IDX2_INGRESS_BUDGET_ADAPT_Q_DEPTH",
            "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_ENABLE",
            "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_BUDGET_PER_TICK",
            "MESH_EXPERIMENTAL_NOC_ROWIDX_CACHE_ROWS",
            "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_GATHER_ONLY",
            "MESH_EXPERIMENTAL_NOC_ROWIDX_PREFETCH_DETACHED_ENABLE",
            "MESH_EXPERIMENTAL_NOC_ROWIDX_HOT_TOUCH_MIN",
            "MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_ENABLE",
            "MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_MAX_PER_TICK",
            "MESH_EXPERIMENTAL_NOC_ROWIDX_BUDGET_ADAPT_Q_DEPTH",
        ):
            if (os.environ.get(k) or "").strip():
                ignored.append(k)
        if ignored:
            mesh_print(
                f"[mesh] NOTE: ignore experimental PULSE overrides {ignored} "
                "(set MESH_EXPERIMENTAL_ENABLE=1 to enable)"
            )
        return

    _env = os.environ.get("MESH_PULSE_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(f"[mesh] override PULSE_ENABLE={state['PULSE_ENABLE']} via MESH_PULSE_ENABLE={_env}")
    _env = os.environ.get("MESH_PULSE_OBSERVE_ONLY", "").strip().lower()
    if _env:
        state["PULSE_OBSERVE_ONLY"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PULSE_OBSERVE_ONLY={state['PULSE_OBSERVE_ONLY']} "
            f"via MESH_PULSE_OBSERVE_ONLY={_env}"
        )
    _env = os.environ.get("MESH_PULSE_INGRESS_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_INGRESS_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PULSE_INGRESS_ENABLE={state['PULSE_INGRESS_ENABLE']} "
            f"via MESH_PULSE_INGRESS_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_AGENDA_OBSERVE_ONLY", "").strip().lower()
    if _env:
        state["PULSE_AGENDA_OBSERVE_ONLY"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PULSE_AGENDA_OBSERVE_ONLY={state['PULSE_AGENDA_OBSERVE_ONLY']} "
            f"via MESH_PULSE_AGENDA_OBSERVE_ONLY={_env}"
        )
    _env = os.environ.get("MESH_PULSE_HARBOR_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_HARBOR_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PULSE_HARBOR_ENABLE={state['PULSE_HARBOR_ENABLE']} "
            f"via MESH_PULSE_HARBOR_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_DESCRIPTOR_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_DESCRIPTOR_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PULSE_DESCRIPTOR_ENABLE={state['PULSE_DESCRIPTOR_ENABLE']} "
            f"via MESH_PULSE_DESCRIPTOR_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_DESCRIPTOR_ACTUAL_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_DESCRIPTOR_ACTUAL_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PULSE_DESCRIPTOR_ACTUAL_ENABLE={state['PULSE_DESCRIPTOR_ACTUAL_ENABLE']} "
            f"via MESH_PULSE_DESCRIPTOR_ACTUAL_ENABLE={_env}"
        )
    _env = os.environ.get(
        "MESH_PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE",
        "",
    ).strip().lower()
    if _env:
        state["PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE"] = (
            1 if _env in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            "PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE="
            f"{state['PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE']} "
            "via MESH_PULSE_EXPERIMENTAL_ROWDESCRIPTOR_READY_JOIN_DEDUP_ENABLE="
            f"{_env}"
        )
    _env = os.environ.get("MESH_PULSE_DOMAIN_RETIRE_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_DOMAIN_RETIRE_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PULSE_DOMAIN_RETIRE_ENABLE={state['PULSE_DOMAIN_RETIRE_ENABLE']} "
            f"via MESH_PULSE_DOMAIN_RETIRE_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_DOMAIN_RETIRE_OBSERVE_ONLY", "").strip().lower()
    if _env:
        state["PULSE_DOMAIN_RETIRE_OBSERVE_ONLY"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PULSE_DOMAIN_RETIRE_OBSERVE_ONLY={state['PULSE_DOMAIN_RETIRE_OBSERVE_ONLY']} "
            f"via MESH_PULSE_DOMAIN_RETIRE_OBSERVE_ONLY={_env}"
        )
    _env = os.environ.get("MESH_PULSE_DOMAIN_RETIRE_MODE", "").strip().lower()
    if _env in ("per_post", "descriptor_domain"):
        state["PULSE_DOMAIN_RETIRE_MODE"] = _env
        mesh_print(
            f"[mesh] override PULSE_DOMAIN_RETIRE_MODE={state['PULSE_DOMAIN_RETIRE_MODE']} "
            f"via MESH_PULSE_DOMAIN_RETIRE_MODE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_DOMAIN_RETIRE_RELEASE_BUDGET", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 0:
                state["PULSE_DOMAIN_RETIRE_RELEASE_BUDGET"] = _v
                mesh_print(
                    f"[mesh] override PULSE_DOMAIN_RETIRE_RELEASE_BUDGET={state['PULSE_DOMAIN_RETIRE_RELEASE_BUDGET']} "
                    f"via MESH_PULSE_DOMAIN_RETIRE_RELEASE_BUDGET={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_FRONTIER_OBSERVE_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_FRONTIER_OBSERVE_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PULSE_FRONTIER_OBSERVE_ENABLE={state['PULSE_FRONTIER_OBSERVE_ENABLE']} "
            f"via MESH_PULSE_FRONTIER_OBSERVE_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_FRONTIER_TOP_LINES", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_FRONTIER_TOP_LINES"] = _v
                mesh_print(
                    f"[mesh] override PULSE_FRONTIER_TOP_LINES={state['PULSE_FRONTIER_TOP_LINES']} "
                    f"via MESH_PULSE_FRONTIER_TOP_LINES={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_METADATA_FRONTIER_OBSERVE_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_METADATA_FRONTIER_OBSERVE_ENABLE"] = (
            1 if _env in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"PULSE_METADATA_FRONTIER_OBSERVE_ENABLE={state['PULSE_METADATA_FRONTIER_OBSERVE_ENABLE']} "
            f"via MESH_PULSE_METADATA_FRONTIER_OBSERVE_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_METADATA_FRONTIER_TOP_ITEMS", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_METADATA_FRONTIER_TOP_ITEMS"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_METADATA_FRONTIER_TOP_ITEMS={state['PULSE_METADATA_FRONTIER_TOP_ITEMS']} "
                    f"via MESH_PULSE_METADATA_FRONTIER_TOP_ITEMS={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_METADATA_FRONTIER_BAND_SLOTS", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_METADATA_FRONTIER_BAND_SLOTS"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_METADATA_FRONTIER_BAND_SLOTS={state['PULSE_METADATA_FRONTIER_BAND_SLOTS']} "
                    f"via MESH_PULSE_METADATA_FRONTIER_BAND_SLOTS={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_METADATA_SEED_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_METADATA_SEED_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            "[mesh] override "
            f"PULSE_METADATA_SEED_ENABLE={state['PULSE_METADATA_SEED_ENABLE']} "
            f"via MESH_PULSE_METADATA_SEED_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_METADATA_SEED_TOP_BASES", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_METADATA_SEED_TOP_BASES"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_METADATA_SEED_TOP_BASES={state['PULSE_METADATA_SEED_TOP_BASES']} "
                    f"via MESH_PULSE_METADATA_SEED_TOP_BASES={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_METADATA_SEED_WINDOW_BUDGET", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 0:
                state["PULSE_METADATA_SEED_WINDOW_BUDGET"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_METADATA_SEED_WINDOW_BUDGET={state['PULSE_METADATA_SEED_WINDOW_BUDGET']} "
                    f"via MESH_PULSE_METADATA_SEED_WINDOW_BUDGET={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_MFB_PREBAND_SEED_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_MFB_PREBAND_SEED_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            "[mesh] override "
            f"PULSE_MFB_PREBAND_SEED_ENABLE={state['PULSE_MFB_PREBAND_SEED_ENABLE']} "
            f"via MESH_PULSE_MFB_PREBAND_SEED_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_MFB_PREBAND_TOP_BANDS", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_MFB_PREBAND_TOP_BANDS"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_MFB_PREBAND_TOP_BANDS={state['PULSE_MFB_PREBAND_TOP_BANDS']} "
                    f"via MESH_PULSE_MFB_PREBAND_TOP_BANDS={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_MFB_PREBAND_LINES_PER_BAND", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_MFB_PREBAND_LINES_PER_BAND"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_MFB_PREBAND_LINES_PER_BAND={state['PULSE_MFB_PREBAND_LINES_PER_BAND']} "
                    f"via MESH_PULSE_MFB_PREBAND_LINES_PER_BAND={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_MFB_PREBAND_BAND_SLOTS", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_MFB_PREBAND_BAND_SLOTS"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_MFB_PREBAND_BAND_SLOTS={state['PULSE_MFB_PREBAND_BAND_SLOTS']} "
                    f"via MESH_PULSE_MFB_PREBAND_BAND_SLOTS={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_MFB_PREBAND_WINDOW_BUDGET", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 0:
                state["PULSE_MFB_PREBAND_WINDOW_BUDGET"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_MFB_PREBAND_WINDOW_BUDGET={state['PULSE_MFB_PREBAND_WINDOW_BUDGET']} "
                    f"via MESH_PULSE_MFB_PREBAND_WINDOW_BUDGET={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_MFB_GATHER_PREBAND_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_MFB_GATHER_PREBAND_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            "[mesh] override "
            f"PULSE_MFB_GATHER_PREBAND_ENABLE={state['PULSE_MFB_GATHER_PREBAND_ENABLE']} "
            f"via MESH_PULSE_MFB_GATHER_PREBAND_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_MFB_GATHER_BARRIER_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_MFB_GATHER_BARRIER_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            "[mesh] override "
            f"PULSE_MFB_GATHER_BARRIER_ENABLE={state['PULSE_MFB_GATHER_BARRIER_ENABLE']} "
            f"via MESH_PULSE_MFB_GATHER_BARRIER_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_MFB_GATHER_TOP_BANDS", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_MFB_GATHER_TOP_BANDS"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_MFB_GATHER_TOP_BANDS={state['PULSE_MFB_GATHER_TOP_BANDS']} "
                    f"via MESH_PULSE_MFB_GATHER_TOP_BANDS={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_MFB_GATHER_LINES_PER_BAND", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_MFB_GATHER_LINES_PER_BAND"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_MFB_GATHER_LINES_PER_BAND={state['PULSE_MFB_GATHER_LINES_PER_BAND']} "
                    f"via MESH_PULSE_MFB_GATHER_LINES_PER_BAND={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_MFB_GATHER_MIN_CONSUMERS", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 2:
                state["PULSE_MFB_GATHER_MIN_CONSUMERS"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_MFB_GATHER_MIN_CONSUMERS={state['PULSE_MFB_GATHER_MIN_CONSUMERS']} "
                    f"via MESH_PULSE_MFB_GATHER_MIN_CONSUMERS={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_MFB_GATHER_WINDOW_BUDGET", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 0:
                state["PULSE_MFB_GATHER_WINDOW_BUDGET"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_MFB_GATHER_WINDOW_BUDGET={state['PULSE_MFB_GATHER_WINDOW_BUDGET']} "
                    f"via MESH_PULSE_MFB_GATHER_WINDOW_BUDGET={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_PREBASE_SHARED_LOOKUP_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_PREBASE_SHARED_LOOKUP_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            "[mesh] override "
            f"PULSE_PREBASE_SHARED_LOOKUP_ENABLE={state['PULSE_PREBASE_SHARED_LOOKUP_ENABLE']} "
            f"via MESH_PULSE_PREBASE_SHARED_LOOKUP_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_OSA_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_OSA_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PULSE_OSA_ENABLE={state['PULSE_OSA_ENABLE']} "
            f"via MESH_PULSE_OSA_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            "[mesh] override "
            f"PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE={state['PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE']} "
            f"via MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE"] = (
            1 if _env in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE={state['PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE']} "
            f"via MESH_PULSE_OSA_SHARED_WEIGHT_OWNER_ACTUAL_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_OSA_METADATA_TXN_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_OSA_METADATA_TXN_ENABLE"] = (
            1 if _env in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            f"PULSE_OSA_METADATA_TXN_ENABLE={state['PULSE_OSA_METADATA_TXN_ENABLE']} "
            f"via MESH_PULSE_OSA_METADATA_TXN_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_OSA_METADATA_READY_LEASE_ENABLE", "").strip().lower()
    if _env:
        state["PULSE_OSA_METADATA_READY_LEASE_ENABLE"] = (
            1 if _env in ("1", "true", "yes", "y", "on") else 0
        )
        mesh_print(
            "[mesh] override "
            "PULSE_OSA_METADATA_READY_LEASE_ENABLE="
            f"{state['PULSE_OSA_METADATA_READY_LEASE_ENABLE']} "
            f"via MESH_PULSE_OSA_METADATA_READY_LEASE_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PULSE_OSA_METADATA_READY_LEASE_TTL", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 0:
                state["PULSE_OSA_METADATA_READY_LEASE_TTL"] = _v
                mesh_print(
                    "[mesh] override "
                    f"PULSE_OSA_METADATA_READY_LEASE_TTL={state['PULSE_OSA_METADATA_READY_LEASE_TTL']} "
                    f"via MESH_PULSE_OSA_METADATA_READY_LEASE_TTL={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_OSA_METADATA_OBJECT_MASK", "").strip().lower()
    if _env:
        state["PULSE_OSA_METADATA_OBJECT_MASK"] = _env
        mesh_print(
            "[mesh] override "
            f"PULSE_OSA_METADATA_OBJECT_MASK={state['PULSE_OSA_METADATA_OBJECT_MASK']} "
            f"via MESH_PULSE_OSA_METADATA_OBJECT_MASK={_env}"
        )
    _env = os.environ.get("MESH_PULSE_INGRESS_ENTRIES", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 0:
                state["PULSE_INGRESS_ENTRIES"] = _v
                mesh_print(
                    f"[mesh] override PULSE_INGRESS_ENTRIES={state['PULSE_INGRESS_ENTRIES']} "
                    f"via MESH_PULSE_INGRESS_ENTRIES={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_CORE_QUEUE_ENTRIES", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 0:
                state["PULSE_CORE_QUEUE_ENTRIES"] = _v
                mesh_print(
                    f"[mesh] override PULSE_CORE_QUEUE_ENTRIES={state['PULSE_CORE_QUEUE_ENTRIES']} "
                    f"via MESH_PULSE_CORE_QUEUE_ENTRIES={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_DESCRIPTOR_PACKET_MIN", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_DESCRIPTOR_PACKET_MIN"] = _v
                mesh_print(
                    f"[mesh] override PULSE_DESCRIPTOR_PACKET_MIN={state['PULSE_DESCRIPTOR_PACKET_MIN']} "
                    f"via MESH_PULSE_DESCRIPTOR_PACKET_MIN={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_BYPASS_HIGH_WATERMARK_PCT", "").strip()
    if _env:
        try:
            _v = int(_env)
            if _v >= 1:
                state["PULSE_BYPASS_HIGH_WATERMARK_PCT"] = min(100, _v)
                mesh_print(
                    f"[mesh] override PULSE_BYPASS_HIGH_WATERMARK_PCT={state['PULSE_BYPASS_HIGH_WATERMARK_PCT']} "
                    f"via MESH_PULSE_BYPASS_HIGH_WATERMARK_PCT={_env}"
                )
        except Exception:
            pass
    _env = os.environ.get("MESH_PULSE_BYPASS_MODE", "").strip().lower()
    if _env in ("disabled", "high_watermark"):
        state["PULSE_BYPASS_MODE"] = _env
        mesh_print(
            f"[mesh] override PULSE_BYPASS_MODE={state['PULSE_BYPASS_MODE']} "
            f"via MESH_PULSE_BYPASS_MODE={_env}"
        )
    _env = os.environ.get("MESH_PE_INTERNAL_CPE_ENABLE", "").strip().lower()
    if _env:
        state["PE_INTERNAL_CPE_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PE_INTERNAL_CPE_ENABLE={state['PE_INTERNAL_CPE_ENABLE']} "
            f"via MESH_PE_INTERNAL_CPE_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PE_INTERNAL_POD_ENABLE", "").strip().lower()
    if _env:
        state["PE_INTERNAL_POD_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PE_INTERNAL_POD_ENABLE={state['PE_INTERNAL_POD_ENABLE']} "
            f"via MESH_PE_INTERNAL_POD_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PE_INTERNAL_POD_COUNT", "").strip()
    if _env:
        try:
            state["PE_INTERNAL_POD_COUNT"] = max(0, int(_env))
            mesh_print(
                f"[mesh] override PE_INTERNAL_POD_COUNT={state['PE_INTERNAL_POD_COUNT']} "
                f"via MESH_PE_INTERNAL_POD_COUNT={_env}"
            )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid MESH_PE_INTERNAL_POD_COUNT={_env!r} (expected int >= 0)"
            )
    _env = os.environ.get("MESH_PE_INTERNAL_POD_SIZE", "").strip()
    if _env:
        try:
            state["PE_INTERNAL_POD_SIZE"] = max(0, int(_env))
            mesh_print(
                f"[mesh] override PE_INTERNAL_POD_SIZE={state['PE_INTERNAL_POD_SIZE']} "
                f"via MESH_PE_INTERNAL_POD_SIZE={_env}"
            )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid MESH_PE_INTERNAL_POD_SIZE={_env!r} (expected int >= 0)"
            )
    _env = os.environ.get("MESH_PE_INTERNAL_POD_METADATA_ENABLE", "").strip().lower()
    if _env:
        state["PE_INTERNAL_POD_METADATA_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PE_INTERNAL_POD_METADATA_ENABLE={state['PE_INTERNAL_POD_METADATA_ENABLE']} "
            f"via MESH_PE_INTERNAL_POD_METADATA_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PE_INTERNAL_POD_OWNER_ENABLE", "").strip().lower()
    if _env:
        state["PE_INTERNAL_POD_OWNER_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PE_INTERNAL_POD_OWNER_ENABLE={state['PE_INTERNAL_POD_OWNER_ENABLE']} "
            f"via MESH_PE_INTERNAL_POD_OWNER_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PE_INTERNAL_POD_JOIN_ENABLE", "").strip().lower()
    if _env:
        state["PE_INTERNAL_POD_JOIN_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PE_INTERNAL_POD_JOIN_ENABLE={state['PE_INTERNAL_POD_JOIN_ENABLE']} "
            f"via MESH_PE_INTERNAL_POD_JOIN_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PE_INTERNAL_POD_READY_ENABLE", "").strip().lower()
    if _env:
        state["PE_INTERNAL_POD_READY_ENABLE"] = 1 if _env in ("1", "true", "yes", "y", "on") else 0
        mesh_print(
            f"[mesh] override PE_INTERNAL_POD_READY_ENABLE={state['PE_INTERNAL_POD_READY_ENABLE']} "
            f"via MESH_PE_INTERNAL_POD_READY_ENABLE={_env}"
        )
    _env = os.environ.get("MESH_PE_INTERNAL_POD_OWNER_ENTRIES", "").strip()
    if _env:
        try:
            state["PE_INTERNAL_POD_OWNER_ENTRIES"] = max(0, int(_env))
            mesh_print(
                f"[mesh] override PE_INTERNAL_POD_OWNER_ENTRIES={state['PE_INTERNAL_POD_OWNER_ENTRIES']} "
                f"via MESH_PE_INTERNAL_POD_OWNER_ENTRIES={_env}"
            )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid MESH_PE_INTERNAL_POD_OWNER_ENTRIES={_env!r} (expected int >= 0)"
            )
    _env = os.environ.get("MESH_PE_INTERNAL_POD_JOIN_ENTRIES", "").strip()
    if _env:
        try:
            state["PE_INTERNAL_POD_JOIN_ENTRIES"] = max(0, int(_env))
            mesh_print(
                f"[mesh] override PE_INTERNAL_POD_JOIN_ENTRIES={state['PE_INTERNAL_POD_JOIN_ENTRIES']} "
                f"via MESH_PE_INTERNAL_POD_JOIN_ENTRIES={_env}"
            )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid MESH_PE_INTERNAL_POD_JOIN_ENTRIES={_env!r} (expected int >= 0)"
            )
    _env = os.environ.get("MESH_PE_INTERNAL_POD_READY_ENTRIES", "").strip()
    if _env:
        try:
            state["PE_INTERNAL_POD_READY_ENTRIES"] = max(0, int(_env))
            mesh_print(
                f"[mesh] override PE_INTERNAL_POD_READY_ENTRIES={state['PE_INTERNAL_POD_READY_ENTRIES']} "
                f"via MESH_PE_INTERNAL_POD_READY_ENTRIES={_env}"
            )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid MESH_PE_INTERNAL_POD_READY_ENTRIES={_env!r} (expected int >= 0)"
            )


def apply_thermal_env_overrides(*, state: Dict[str, Any]) -> None:
    _env = os.environ.get("MESH_THERMAL_ENABLE", "").strip().lower()
    if _env:
        if _env in ("1", "true", "yes", "y", "on"):
            state["THERMAL_ENABLE"] = 1
            mesh_print(f"[mesh] override THERMAL_ENABLE=1 via MESH_THERMAL_ENABLE={_env}")
        elif _env in ("0", "false", "no", "n", "off"):
            state["THERMAL_ENABLE"] = 0
            mesh_print(f"[mesh] override THERMAL_ENABLE=0 via MESH_THERMAL_ENABLE={_env}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_ENABLE={_env!r} (expected 0/1/true/false)")

    _env = os.environ.get("MESH_THERMAL_BACKEND", "").strip()
    if _env:
        backend = _normalize_thermal_backend(_env)
        if backend:
            state["THERMAL_BACKEND"] = backend
            mesh_print(f"[mesh] override THERMAL_BACKEND={backend} via MESH_THERMAL_BACKEND={_env}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_BACKEND={_env!r} (expected hotspot/3dice)")

    _env = os.environ.get("MESH_THERMAL_WINDOW_NS", "").strip()
    if _env:
        try:
            value = max(1, int(_env))
            state["THERMAL_WINDOW_NS"] = value
            mesh_print(f"[mesh] override THERMAL_WINDOW_NS={value} via MESH_THERMAL_WINDOW_NS={_env}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_WINDOW_NS={_env!r} (expected int >=1)")

    _env = os.environ.get("MESH_THERMAL_WINDOW_TRACE_ENABLE", "").strip().lower()
    if _env:
        if _env in ("1", "true", "yes", "y", "on"):
            state["THERMAL_WINDOW_TRACE_ENABLE"] = 1
            mesh_print("[mesh] override THERMAL_WINDOW_TRACE_ENABLE=1 via MESH_THERMAL_WINDOW_TRACE_ENABLE")
        elif _env in ("0", "false", "no", "n", "off"):
            state["THERMAL_WINDOW_TRACE_ENABLE"] = 0
            mesh_print("[mesh] override THERMAL_WINDOW_TRACE_ENABLE=0 via MESH_THERMAL_WINDOW_TRACE_ENABLE")
        else:
            mesh_print(
                f"[mesh] ignore invalid MESH_THERMAL_WINDOW_TRACE_ENABLE={_env!r} (expected 0/1/true/false)"
            )

    _env = os.environ.get("MESH_THERMAL_WINDOW_TRACE_MAX_ROWS", "").strip()
    if _env:
        try:
            value = max(1, int(_env))
            state["THERMAL_WINDOW_TRACE_MAX_ROWS"] = value
            mesh_print(
                f"[mesh] override THERMAL_WINDOW_TRACE_MAX_ROWS={value} "
                f"via MESH_THERMAL_WINDOW_TRACE_MAX_ROWS={_env}"
            )
        except Exception:
            mesh_print(
                f"[mesh] ignore invalid MESH_THERMAL_WINDOW_TRACE_MAX_ROWS={_env!r} (expected int >=1)"
            )

    _env = os.environ.get("MESH_THERMAL_INCLUDE_MEMCTRL", "").strip().lower()
    if _env:
        if _env in ("1", "true", "yes", "y", "on"):
            state["THERMAL_INCLUDE_MEMCTRL"] = 1
            mesh_print("[mesh] override THERMAL_INCLUDE_MEMCTRL=1 via MESH_THERMAL_INCLUDE_MEMCTRL")
        elif _env in ("0", "false", "no", "n", "off"):
            state["THERMAL_INCLUDE_MEMCTRL"] = 0
            mesh_print("[mesh] override THERMAL_INCLUDE_MEMCTRL=0 via MESH_THERMAL_INCLUDE_MEMCTRL")
        else:
            mesh_print(
                f"[mesh] ignore invalid MESH_THERMAL_INCLUDE_MEMCTRL={_env!r} (expected 0/1/true/false)"
            )

    _env = os.environ.get("MESH_THERMAL_OUT_DIR", "").strip()
    if _env:
        state["THERMAL_OUT_DIR"] = _env
        mesh_print(f"[mesh] override THERMAL_OUT_DIR={_env} via MESH_THERMAL_OUT_DIR={_env}")

    _env = os.environ.get("MESH_THERMAL_HOTSPOT_BIN", "").strip()
    if _env:
        state["THERMAL_HOTSPOT_BIN"] = _env
        mesh_print(f"[mesh] override THERMAL_HOTSPOT_BIN={_env} via MESH_THERMAL_HOTSPOT_BIN={_env}")

    _env = os.environ.get("MESH_THERMAL_GENERATE_FLOORPLAN", "").strip().lower()
    if _env:
        if _env in ("1", "true", "yes", "y", "on"):
            state["THERMAL_GENERATE_FLOORPLAN"] = 1
            mesh_print("[mesh] override THERMAL_GENERATE_FLOORPLAN=1 via MESH_THERMAL_GENERATE_FLOORPLAN")
        elif _env in ("0", "false", "no", "n", "off"):
            state["THERMAL_GENERATE_FLOORPLAN"] = 0
            mesh_print("[mesh] override THERMAL_GENERATE_FLOORPLAN=0 via MESH_THERMAL_GENERATE_FLOORPLAN")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_GENERATE_FLOORPLAN={_env!r} (expected 0/1/true/false)")

    _env = os.environ.get("MESH_THERMAL_MODEL_TYPE", "").strip()
    if _env:
        model_type = _normalize_thermal_model_type(_env)
        if model_type:
            state["THERMAL_MODEL_TYPE"] = model_type
            mesh_print(f"[mesh] override THERMAL_MODEL_TYPE={model_type} via MESH_THERMAL_MODEL_TYPE={_env}")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_MODEL_TYPE={_env!r} (expected block/grid)")

    _env = os.environ.get("MESH_THERMAL_GRID_ROWS", "").strip()
    if _env:
        try:
            value = max(1, int(_env))
            state["THERMAL_GRID_ROWS"] = value
            mesh_print(f"[mesh] override THERMAL_GRID_ROWS={value} via MESH_THERMAL_GRID_ROWS={_env}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_GRID_ROWS={_env!r} (expected int >=1)")

    _env = os.environ.get("MESH_THERMAL_GRID_COLS", "").strip()
    if _env:
        try:
            value = max(1, int(_env))
            state["THERMAL_GRID_COLS"] = value
            mesh_print(f"[mesh] override THERMAL_GRID_COLS={value} via MESH_THERMAL_GRID_COLS={_env}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_GRID_COLS={_env!r} (expected int >=1)")

    _env = os.environ.get("MESH_THERMAL_GRID_MAP_MODE", "").strip()
    if _env:
        grid_map_mode = _normalize_thermal_grid_map_mode(_env)
        if grid_map_mode:
            state["THERMAL_GRID_MAP_MODE"] = grid_map_mode
            mesh_print(
                f"[mesh] override THERMAL_GRID_MAP_MODE={grid_map_mode} via MESH_THERMAL_GRID_MAP_MODE={_env}"
            )
        else:
            mesh_print(
                f"[mesh] ignore invalid MESH_THERMAL_GRID_MAP_MODE={_env!r} (expected avg/min/max/center)"
            )

    _env = os.environ.get("MESH_THERMAL_DETAILED_3D", "").strip().lower()
    if _env:
        if _env in ("1", "true", "yes", "y", "on"):
            state["THERMAL_DETAILED_3D"] = 1
            mesh_print("[mesh] override THERMAL_DETAILED_3D=1 via MESH_THERMAL_DETAILED_3D")
        elif _env in ("0", "false", "no", "n", "off"):
            state["THERMAL_DETAILED_3D"] = 0
            mesh_print("[mesh] override THERMAL_DETAILED_3D=0 via MESH_THERMAL_DETAILED_3D")
        else:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_DETAILED_3D={_env!r} (expected 0/1/true/false)")

    _env = os.environ.get("MESH_THERMAL_TILE_WIDTH_UM", "").strip()
    if _env:
        try:
            value = max(1, int(_env))
            state["THERMAL_TILE_WIDTH_UM"] = value
            mesh_print(f"[mesh] override THERMAL_TILE_WIDTH_UM={value} via MESH_THERMAL_TILE_WIDTH_UM={_env}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_TILE_WIDTH_UM={_env!r} (expected int >=1)")

    _env = os.environ.get("MESH_THERMAL_TILE_HEIGHT_UM", "").strip()
    if _env:
        try:
            value = max(1, int(_env))
            state["THERMAL_TILE_HEIGHT_UM"] = value
            mesh_print(f"[mesh] override THERMAL_TILE_HEIGHT_UM={value} via MESH_THERMAL_TILE_HEIGHT_UM={_env}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_TILE_HEIGHT_UM={_env!r} (expected int >=1)")

    _env = os.environ.get("MESH_THERMAL_TILE_GAP_UM", "").strip()
    if _env:
        try:
            value = max(0, int(_env))
            state["THERMAL_TILE_GAP_UM"] = value
            mesh_print(f"[mesh] override THERMAL_TILE_GAP_UM={value} via MESH_THERMAL_TILE_GAP_UM={_env}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_TILE_GAP_UM={_env!r} (expected int >=0)")

    _env = os.environ.get("MESH_THERMAL_COMP_FRAC", "").strip()
    if _env:
        try:
            value = max(0.0, float(_env))
            state["THERMAL_COMP_FRAC"] = value
            mesh_print(f"[mesh] override THERMAL_COMP_FRAC={value} via MESH_THERMAL_COMP_FRAC={_env}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_COMP_FRAC={_env!r} (expected float >=0)")

    _env = os.environ.get("MESH_THERMAL_SRAM_FRAC", "").strip()
    if _env:
        try:
            value = max(0.0, float(_env))
            state["THERMAL_SRAM_FRAC"] = value
            mesh_print(f"[mesh] override THERMAL_SRAM_FRAC={value} via MESH_THERMAL_SRAM_FRAC={_env}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_SRAM_FRAC={_env!r} (expected float >=0)")

    _env = os.environ.get("MESH_THERMAL_NOC_FRAC", "").strip()
    if _env:
        try:
            value = max(0.0, float(_env))
            state["THERMAL_NOC_FRAC"] = value
            mesh_print(f"[mesh] override THERMAL_NOC_FRAC={value} via MESH_THERMAL_NOC_FRAC={_env}")
        except Exception:
            mesh_print(f"[mesh] ignore invalid MESH_THERMAL_NOC_FRAC={_env!r} (expected float >=0)")


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
