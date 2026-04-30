#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validate internal consistency ("sanity") of essential_summary_mesh.json.

This script is meant to be the standard acceptance gate for mesh runs:
  1) Semantic invariants within one run (SNN/Step/GAS accounting)
  2) Optional tolerant compare against a baseline run directory

Usage:
  python3 tools/validate_essential_summary_mesh.py --run-dir <RUN_DIR>
  python3 tools/validate_essential_summary_mesh.py --run-dir <RUN_DIR> --baseline <BASELINE_DIR>

Exit codes:
  0: PASS (no FAIL; WARN allowed unless --strict)
  1: FAIL (any FAIL, or WARN when --strict)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # PASS|WARN|FAIL|SKIP
    detail: str


def _get_path(d: Dict[str, Any], dotted: str) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _as_float(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _as_intish(v: Any) -> Optional[int]:
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        if math.isfinite(v) and abs(v - round(v)) < 1e-6:
            return int(round(v))
    return None


def _as_boolish(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        text = v.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
    return None


def _close(a: float, b: float, abs_tol: float, rel_tol: float) -> bool:
    diff = abs(a - b)
    if diff <= abs_tol:
        return True
    denom = max(abs(a), abs(b), 1.0)
    return (diff / denom) <= rel_tol


_TIME_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*(ns|us|ms|s)\s*$", re.IGNORECASE)


def _parse_time_to_ns(s: str) -> Optional[int]:
    m = _TIME_RE.match(str(s or ""))
    if not m:
        return None
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "ns":
        return int(round(val))
    if unit == "us":
        return int(round(val * 1_000.0))
    if unit == "ms":
        return int(round(val * 1_000_000.0))
    if unit == "s":
        return int(round(val * 1_000_000_000.0))
    return None


def _fmt_num(v: Any) -> str:
    if v is None:
        return "None"
    if isinstance(v, float):
        if abs(v - round(v)) < 1e-6:
            return str(int(round(v)))
        return f"{v:.6g}"
    return str(v)


def _normalize_retire_policy(value: Any) -> str:
    policy = str(value or "").strip().lower()
    if policy in ("per_post", "per_post_deterministic"):
        return "per_post"
    if policy in ("global_inorder", "global_total_order"):
        return "global_inorder"
    return policy


def _retire_policy_scope_from_policy(policy: Any) -> str:
    normalized = _normalize_retire_policy(policy)
    if normalized == "global_inorder":
        return "global_total_order"
    if normalized == "per_post":
        return "same_post_deterministic"
    return "unknown"


def _common_effective_gatherbuf_value(effective_cfg: Optional[Dict[str, Any]], key: str) -> Optional[Any]:
    if not isinstance(effective_cfg, dict):
        return None
    per_core = effective_cfg.get("per_core")
    if not isinstance(per_core, list):
        return None
    values: List[Any] = []
    for item in per_core:
        if not isinstance(item, dict):
            continue
        gatherbuf = item.get("gatherbuf")
        if not isinstance(gatherbuf, dict):
            continue
        if key not in gatherbuf:
            continue
        values.append(gatherbuf.get(key))
    if not values:
        return None
    first = values[0]
    for value in values[1:]:
        if value != first:
            return "__mixed__"
    return first


def _infer_step_sync_mode(summary: Dict[str, Any]) -> bool:
    """
    Heuristic: infer global step sync (barrier/step-gate) mode from summary fields.
    """
    # Prefer explicit step section when present (Phase6+).
    step_sync_enable = _get_path(summary, "step.global_step_sync_enable")
    if isinstance(step_sync_enable, bool):
        return bool(step_sync_enable)
    step_gsd = _as_intish(_get_path(summary, "step.global_steps_done")) or 0
    if step_gsd > 0:
        return True

    num_pes = _as_intish(_get_path(summary, "model.num_pes")) or 0
    windows_done = _as_intish(_get_path(summary, "gas.windows_done")) or 0
    gsd = _as_intish(_get_path(summary, "gas.global_steps_done")) or 0
    if num_pes <= 0:
        return False
    if gsd > 0 and windows_done >= gsd * num_pes:
        return True
    # Also treat "scatter_ns_avg <= 2" as a strong indicator for explicit EndScatter step-gate mode.
    scat_avg = _as_float(_get_path(summary, "gas.scatter_ns_avg")) or 0.0
    if scat_avg <= 2.0 and windows_done >= num_pes:
        return True
    return False


def _read_first_existing_text(paths: List[Path]) -> Tuple[Optional[Path], str]:
    for p in paths:
        if p.exists() and p.is_file():
            try:
                return p, p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
    return None, ""


def _load_json_dict(path: Path) -> Optional[Dict[str, Any]]:
    if not (path.exists() and path.is_file()):
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _resolve_ref_path(*, run_dir: Path, summary: Dict[str, Any], ref_key: str, default_name: str) -> Path:
    """
    Resolve a run artifact path with backward compatibility:
      - Prefer summary.refs[ref_key] (relative to run_dir)
      - Fall back to run_dir/<default_name>
    """
    refs = summary.get("refs") if isinstance(summary, dict) else None
    if isinstance(refs, dict):
        p = refs.get(ref_key)
        if isinstance(p, str) and p.strip():
            return (run_dir / p).resolve()
    return (run_dir / default_name).resolve()


def _compare_against_baseline(
    *,
    base: Dict[str, Any],
    cur: Dict[str, Any],
    abs_tol: float,
    rel_tol: float,
) -> Tuple[bool, List[Check]]:
    keys = [
        # "semantic" keys preferred over micro-performance keys
        "gas.global_steps_done",
        "gas.windows",
        "gas.windows_done",
        "gas.windows_incomplete",
        "step_activation.invocations",
        "step_activation.pre_selected_total",
        "step_activation.spikes_injected_total",
        "step_activation.route_misses_total",
        "step_activation.local_drops_total",
        "spike_activity.neurons_fired_total",
        "spike_activity.total_spikes_processed",
        "memory.memory_requests",
        "memory.memory_bytes",
        "nic.packets_sent",
        "nic.packets_recv",
    ]

    out: List[Check] = []
    ok = True

    # Guardrail: compare exec_mode if present (prevents accidental cross-mode baseline compares).
    mode_a = str(_get_path(base, "model.exec_mode") or "").strip().lower()
    mode_b = str(_get_path(cur, "model.exec_mode") or "").strip().lower()
    if mode_a and mode_b:
        passed = (mode_a == mode_b)
        out.append(
            Check(
                name="baseline:model.exec_mode",
                status="PASS" if passed else "FAIL",
                detail=f"A={mode_a!r} B={mode_b!r}",
            )
        )
        if not passed:
            ok = False
    else:
        out.append(
            Check(
                name="baseline:model.exec_mode",
                status="SKIP",
                detail=f"missing (A={mode_a!r} B={mode_b!r})",
            )
        )

    for k in keys:
        a = _as_float(_get_path(base, k))
        b = _as_float(_get_path(cur, k))
        if a is None or b is None:
            out.append(Check(name=f"baseline:{k}", status="SKIP", detail=f"missing/non-numeric (A={_fmt_num(a)} B={_fmt_num(b)})"))
            continue
        passed = _close(a, b, abs_tol=abs_tol, rel_tol=rel_tol)
        out.append(
            Check(
                name=f"baseline:{k}",
                status="PASS" if passed else "FAIL",
                detail=f"A={_fmt_num(a)} B={_fmt_num(b)} Δ={_fmt_num(abs(a - b))} (abs_tol={abs_tol} rel_tol={rel_tol})",
            )
        )
        if not passed:
            ok = False
    return ok, out


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _extract_meta_model(meta_raw: Any) -> Dict[str, Any]:
    """
    meta.json compatibility:
      - v0: model fields at top-level
      - v1+: model fields nested under "model"
    """
    if isinstance(meta_raw, dict) and isinstance(meta_raw.get("model"), dict):
        return dict(meta_raw.get("model") or {})
    if isinstance(meta_raw, dict):
        return dict(meta_raw)
    return {}


def _extract_spec_platform(run_dir: Path) -> Dict[str, Any]:
    spec_raw = _load_json_dict(run_dir / "inputs" / "spec.json")
    if not isinstance(spec_raw, dict):
        return {}
    platform = spec_raw.get("platform")
    if isinstance(platform, dict):
        return dict(platform)
    return {}


def _effective_granularity(summary: Dict[str, Any], effective_cfg: Optional[Dict[str, Any]]) -> str:
    """
    Best-effort granularity inference for dense models:
      - Prefer explicit effective_config.json (run_dir/effective_config.json).
      - Fall back to GAS avg_granule_bytes vs line_size_bytes heuristics.
    """
    if isinstance(effective_cfg, dict):
        per_core = effective_cfg.get("per_core")
        if isinstance(per_core, list) and per_core:
            # If any core explicitly labels cacheline, treat as cacheline-mode run.
            for it in per_core:
                if isinstance(it, dict) and str(it.get("dense_read_granularity", "")).strip().lower() == "cacheline":
                    return "cacheline"
            for it in per_core:
                if isinstance(it, dict) and str(it.get("dense_read_granularity", "")).strip().lower() == "row":
                    return "row"

        g0 = str(effective_cfg.get("default_read_granularity") or "").strip().lower()
        if g0 in ("cacheline", "row"):
            return g0

    line = _as_intish(_get_path(summary, "memhierarchy.line_size_bytes")) or 0
    avg = _as_float(_get_path(summary, "gas.avg_granule_bytes"))
    if line > 0 and avg and avg > 0:
        if avg <= float(line) * 2.0:
            return "cacheline"
        if avg >= float(line) * 32.0:
            return "row"
    return "unknown"

def _infer_dense_strict_cacheline(*, summary: Dict[str, Any], effective_cfg: Optional[Dict[str, Any]]) -> Optional[bool]:
    """
    Infer whether dense microbench is in "strict cacheline" mode.

    Strict cacheline (dense_strict_cacheline=1) is a special safety mode in mesh_template/build.py:
      - forces merge_policy=cacheline and burst_bytes_max=line_size
      - disables staging (defer_issue_until_apply=0)
      - disables gap-merge and k-adapt (gap_merge_enable=0, k_adapt_enable=0)

    Some experiments intentionally disable this mode (e.g. staged Apply policy sweeps).
    Older summaries recorded `model.dense_strict_cacheline_override`; newer runs may omit it.
    In that case, fall back to effective_config.json ("per_core[*].gatherbuf") to infer the mode.
    """
    override = str(_get_path(summary, "model.dense_strict_cacheline_override") or "").strip().lower()
    if override in ("0", "false", "no", "off"):
        return False
    if override in ("1", "true", "yes", "on"):
        return True

    if not isinstance(effective_cfg, dict):
        return None
    per_core = effective_cfg.get("per_core")
    if not isinstance(per_core, list) or not per_core:
        return None

    saw_any = False
    for it in per_core:
        if not isinstance(it, dict):
            continue
        gb = it.get("gatherbuf")
        if not isinstance(gb, dict):
            continue
        saw_any = True

        # Any of these being nonzero strongly implies "non-strict" mode.
        # See mesh_template/build.py: strict forces all these effective flags to 0.
        defer_eff = _as_intish(gb.get("defer_issue_until_apply_effective"))
        gap_eff = _as_intish(gb.get("gap_merge_enable_effective"))
        k_adapt_eff = _as_intish(gb.get("k_adapt_enable_effective"))
        if (defer_eff is not None and defer_eff != 0) or (gap_eff is not None and gap_eff != 0) or (k_adapt_eff is not None and k_adapt_eff != 0):
            return False

    if saw_any:
        return True
    return None


def _find_local_run_config_path(*, run_dir: Path, meta_raw: Optional[Dict[str, Any]]) -> Optional[Path]:
    # Prefer meta-provenance path when available.
    if isinstance(meta_raw, dict):
        p = _get_path(meta_raw, "inputs.local_run_config.path")
        if isinstance(p, str) and p.strip():
            cand = (run_dir / p).resolve()
            if cand.exists():
                return cand
    # Back-compat: runner historically copied into run root.
    cand = run_dir / "local_run_config.json"
    if cand.exists():
        return cand
    # New default: archive into inputs/.
    cand = run_dir / "inputs" / "local_run_config.json"
    if cand.exists():
        return cand
    return None


def _paper_allowed_loss(actual: int, attempts: int, abs_allow: int, frac_allow: float) -> int:
    if attempts < 0:
        attempts = 0
    if frac_allow < 0.0:
        frac_allow = 0.0
    # floor(frac*attempts) + abs_allow
    return int(math.floor(float(frac_allow) * float(attempts))) + int(abs_allow)


def validate_summary(
    *,
    run_dir: Path,
    summary: Dict[str, Any],
    meta_raw: Optional[Dict[str, Any]],
    effective_cfg: Optional[Dict[str, Any]],
    local_run_cfg: Optional[Dict[str, Any]],
    profile: str,
    abs_tol: float,
    rel_tol: float,
    max_route_miss_abs: int,
    max_route_miss_frac: float,
    max_local_drop_abs: int,
    max_local_drop_frac: float,
) -> List[Check]:
    checks: List[Check] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append(Check(name=name, status=status, detail=detail))

    meta_model = _extract_meta_model(meta_raw or {})
    spec_platform = _extract_spec_platform(run_dir)
    exec_mode = str(_get_path(summary, "model.exec_mode") or "").strip().lower()
    contracts = summary.get("contracts")
    if isinstance(contracts, dict):
        add("contracts.present", "PASS", "summary.contracts present")
        apply_issue_policy_summary = str(contracts.get("apply_issue_policy") or "").strip()
        experimental_retire_policy_summary = str(contracts.get("experimental_retire_policy") or "").strip()
        retire_policy_scope_summary = str(contracts.get("retire_policy_scope") or "").strip()
        add(
            "contracts.strict_repro_same_post_deterministic",
            "PASS" if contracts.get("strict_repro_same_post_deterministic") is True else "FAIL",
            f"value={contracts.get('strict_repro_same_post_deterministic')!r}",
        )
        add(
            "contracts.strict_repro_global_total_order_required",
            "PASS" if contracts.get("strict_repro_global_total_order_required") is False else "FAIL",
            f"value={contracts.get('strict_repro_global_total_order_required')!r}",
        )
        add(
            "contracts.gas_semantic_ready_before_commit",
            "PASS" if contracts.get("gas_semantic_ready_before_commit") is True else "FAIL",
            f"value={contracts.get('gas_semantic_ready_before_commit')!r}",
        )
        add(
            "contracts.gas_semantic_drain_before_scatter",
            "PASS" if contracts.get("gas_semantic_drain_before_scatter") is True else "FAIL",
            f"value={contracts.get('gas_semantic_drain_before_scatter')!r}",
        )

        expected_apply_issue_policy = _common_effective_gatherbuf_value(effective_cfg, "apply_issue_policy")
        if expected_apply_issue_policy is None:
            add(
                "contracts.apply_issue_policy_matches_effective_config",
                "SKIP",
                "effective_config.gatherbuf.apply_issue_policy missing",
            )
        else:
            add(
                "contracts.apply_issue_policy_matches_effective_config",
                "PASS" if apply_issue_policy_summary == str(expected_apply_issue_policy) else "FAIL",
                f"summary={apply_issue_policy_summary!r} effective={str(expected_apply_issue_policy)!r}",
            )

        expected_retire_policy = _common_effective_gatherbuf_value(effective_cfg, "experimental_retire_policy")
        if expected_retire_policy is None and exec_mode == "gas":
            expected_retire_policy = "global_inorder"
        if expected_retire_policy is None:
            add(
                "contracts.experimental_retire_policy_matches_effective_config",
                "SKIP",
                f"effective_config.gatherbuf.experimental_retire_policy missing for exec_mode={exec_mode or 'unknown'!r}",
            )
        else:
            add(
                "contracts.experimental_retire_policy_matches_effective_config",
                "PASS" if experimental_retire_policy_summary == str(expected_retire_policy) else "FAIL",
                f"summary={experimental_retire_policy_summary!r} effective={str(expected_retire_policy)!r}",
            )

        expected_scope = _retire_policy_scope_from_policy(
            expected_retire_policy if expected_retire_policy not in (None, "") else experimental_retire_policy_summary
        )
        add(
            "contracts.retire_policy_scope_consistent",
            "PASS" if retire_policy_scope_summary == expected_scope else "FAIL",
            f"summary={retire_policy_scope_summary!r} expected={expected_scope!r}",
        )

        expected_phase_breakdown = _as_boolish(
            _common_effective_gatherbuf_value(effective_cfg, "experimental_gcss_phase_breakdown_enable")
        )
        summary_phase_breakdown = _as_boolish(contracts.get("experimental_gcss_phase_breakdown_enable"))
        if expected_phase_breakdown is None:
            add(
                "contracts.experimental_gcss_phase_breakdown_enable_matches_effective_config",
                "SKIP",
                "effective_config.gatherbuf.experimental_gcss_phase_breakdown_enable missing",
            )
        else:
            add(
                "contracts.experimental_gcss_phase_breakdown_enable_matches_effective_config",
                "PASS" if summary_phase_breakdown == expected_phase_breakdown else "FAIL",
                f"summary={summary_phase_breakdown!r} effective={expected_phase_breakdown!r}",
            )

        expected_shadow_per_post = _as_boolish(
            _common_effective_gatherbuf_value(effective_cfg, "experimental_retire_shadow_per_post_enable")
        )
        summary_shadow_per_post = _as_boolish(contracts.get("experimental_retire_shadow_per_post_enable"))
        if expected_shadow_per_post is None:
            add(
                "contracts.experimental_retire_shadow_per_post_enable_matches_effective_config",
                "SKIP",
                "effective_config.gatherbuf.experimental_retire_shadow_per_post_enable missing",
            )
        else:
            add(
                "contracts.experimental_retire_shadow_per_post_enable_matches_effective_config",
                "PASS" if summary_shadow_per_post == expected_shadow_per_post else "FAIL",
                f"summary={summary_shadow_per_post!r} effective={expected_shadow_per_post!r}",
            )

        expected_queue_policy = _common_effective_gatherbuf_value(
            effective_cfg, "experimental_gcss_vlf_queue_policy"
        )
        if expected_queue_policy in (None, "") and exec_mode == "gas":
            expected_queue_policy = "locality_first"
        summary_queue_policy = str(contracts.get("experimental_gcss_vlf_queue_policy") or "").strip()
        if expected_queue_policy in (None, ""):
            add(
                "contracts.experimental_gcss_vlf_queue_policy_matches_effective_config",
                "SKIP",
                f"effective_config.gatherbuf.experimental_gcss_vlf_queue_policy missing for exec_mode={exec_mode or 'unknown'!r}",
            )
        else:
            add(
                "contracts.experimental_gcss_vlf_queue_policy_matches_effective_config",
                "PASS" if summary_queue_policy == str(expected_queue_policy) else "FAIL",
                f"summary={summary_queue_policy!r} effective={str(expected_queue_policy)!r}",
            )

        expected_fair_band_size = _as_intish(
            _common_effective_gatherbuf_value(effective_cfg, "experimental_gcss_vlf_fair_band_size")
        )
        if expected_fair_band_size in (None, 0) and exec_mode == "gas":
            expected_fair_band_size = 256
        summary_fair_band_size = _as_intish(contracts.get("experimental_gcss_vlf_fair_band_size"))
        if expected_fair_band_size in (None, 0):
            add(
                "contracts.experimental_gcss_vlf_fair_band_size_matches_effective_config",
                "SKIP",
                f"effective_config.gatherbuf.experimental_gcss_vlf_fair_band_size missing for exec_mode={exec_mode or 'unknown'!r}",
            )
        else:
            add(
                "contracts.experimental_gcss_vlf_fair_band_size_matches_effective_config",
                "PASS" if summary_fair_band_size == expected_fair_band_size else "FAIL",
                f"summary={summary_fair_band_size!r} effective={expected_fair_band_size!r}",
            )
    else:
        add(
            "contracts.present",
            "WARN" if isinstance(effective_cfg, dict) else "SKIP",
            "summary.contracts missing",
        )

    retire_hol_attr_core = summary.get("retire_hol_attribution_core")
    if not isinstance(retire_hol_attr_core, dict):
        retire_hol_attr_core = {}

    phase_breakdown_enabled = _as_boolish(_get_path(summary, "contracts.experimental_gcss_phase_breakdown_enable")) is True
    if phase_breakdown_enabled:
        gcss_phase_mix = retire_hol_attr_core.get("gcss_phase_mix")
        gcss_qni_reason_mix = retire_hol_attr_core.get("gcss_queued_reason_mix")
        add(
            "retire_hol_attribution_core.gcss_phase_mix.present",
            "PASS" if isinstance(gcss_phase_mix, dict) else "FAIL",
            f"type={type(gcss_phase_mix).__name__}",
        )
        add(
            "retire_hol_attribution_core.gcss_queued_reason_mix.present",
            "PASS" if isinstance(gcss_qni_reason_mix, dict) else "FAIL",
            f"type={type(gcss_qni_reason_mix).__name__}",
        )
        if isinstance(gcss_phase_mix, dict) and isinstance(gcss_qni_reason_mix, dict):
            phase_hol = _as_float(_get_path(gcss_phase_mix, "hol_cycles_by_phase.queued_not_issued"))
            reason_hol = None
            reason_hol_map = _get_path(gcss_qni_reason_mix, "hol_cycles_by_reason")
            if isinstance(reason_hol_map, dict):
                reason_hol = float(sum(_as_float(v) or 0.0 for v in reason_hol_map.values()))
            add(
                "retire_hol_attribution_core.gcss_queued_reason_mix_hol_consistent",
                "PASS" if phase_hol is not None and reason_hol is not None and _close(phase_hol, reason_hol, abs_tol, rel_tol) else "FAIL",
                f"phase.queued_not_issued={_fmt_num(phase_hol)} reason.sum={_fmt_num(reason_hol)}",
            )

            phase_blocked = _as_float(_get_path(gcss_phase_mix, "blocked_edges_by_phase.queued_not_issued"))
            reason_blocked = None
            reason_blocked_map = _get_path(gcss_qni_reason_mix, "blocked_edges_by_reason")
            if isinstance(reason_blocked_map, dict):
                reason_blocked = float(sum(_as_float(v) or 0.0 for v in reason_blocked_map.values()))
            add(
                "retire_hol_attribution_core.gcss_queued_reason_mix_blocked_edges_consistent",
                "PASS" if phase_blocked is not None and reason_blocked is not None and _close(phase_blocked, reason_blocked, abs_tol, rel_tol) else "FAIL",
                f"phase.queued_not_issued={_fmt_num(phase_blocked)} reason.sum={_fmt_num(reason_blocked)}",
            )

    shadow_per_post_enabled = _as_boolish(_get_path(summary, "contracts.experimental_retire_shadow_per_post_enable")) is True
    if shadow_per_post_enabled:
        shadow_per_post = retire_hol_attr_core.get("shadow_per_post")
        add(
            "retire_hol_attribution_core.shadow_per_post.present",
            "PASS" if isinstance(shadow_per_post, dict) else "FAIL",
            f"type={type(shadow_per_post).__name__}",
        )

    # === Run log presence + emergency shutdown detection ===
    # Paper-grade runs must not silently emergency-exit; this commonly manifests as:
    #   - "EMERGENCY SHUTDOWN" spam
    #   - missing/partial step/global counters
    #   - simulated time effectively ~0
    log_candidates = [
        run_dir / "mesh_run.log",
        run_dir / "mesh.log",
        run_dir / "sst.log",
        run_dir / "run.log",
    ]
    log_path, log_text = _read_first_existing_text(log_candidates)
    if log_path is None:
        add(
            "run.log.exists",
            "FAIL" if profile == "paper" else "SKIP",
            "missing mesh_run.log/mesh.log/sst.log/run.log",
        )
        add("run.no_emergency_shutdown", "SKIP", "no log available")
    else:
        add("run.log.exists", "PASS", f"path={log_path}")
        has_emergency = "EMERGENCY SHUTDOWN" in log_text
        add(
            "run.no_emergency_shutdown",
            "PASS" if not has_emergency else "FAIL",
            f"log={log_path}",
        )

    # === Optional: correctness markers (dense microbench + BCSR loader readback) ===
    # These checks are intentionally log-based:
    # - The runtime path should fatal on mismatch (correctness), but we also need a positive
    #   marker proving the verification logic actually ran (not silently disabled).
    if isinstance(local_run_cfg, dict):
        syn_mode = str((effective_cfg or {}).get("synapse_weight_mode", "") or "").strip().lower()
        if syn_mode == "gscc_valueonly_dstcore":
            syn_mode = "gcss_valueonly_dstcore"
        bcsr_weight_mode = (syn_mode in ("", "bcsr_gas"))

        byte_exact_enable = bool(local_run_cfg.get("byte_exact_verify_enable", False))
        loader_verify_readback = bool(local_run_cfg.get("loader_verify_readback", False))
        bcsr_merge_read_verify_enable = bool(local_run_cfg.get("bcsr_merge_read_verify_enable", False))

        if byte_exact_enable or loader_verify_readback or bcsr_merge_read_verify_enable:
            if byte_exact_enable:
                marker = "BYTE_EXACT_VERIFY: PASS"
                ok = (marker in log_text)
                add(
                    "byte_exact.wms.pass_marker",
                    "PASS" if ok else "FAIL",
                    f"enabled=1 marker={marker!r} log={str(log_path) if log_path else 'None'}",
                )

            if bcsr_merge_read_verify_enable and bcsr_weight_mode:
                bcsr_meta_path = _get_path(summary, "model.bcsr_meta_path")
                if not (isinstance(bcsr_meta_path, str) and bcsr_meta_path.strip()):
                    bcsr_meta_path = meta_model.get("bcsr_meta_path")
                if isinstance(bcsr_meta_path, str) and bcsr_meta_path.strip():
                    # Only require the marker when we actually ran at least one GAS window;
                    # otherwise early-stop debug runs (or misconfigured node_limit with barrier) would false-fail.
                    windows = _as_intish(_get_path(summary, "gas.windows")) or 0
                    windows_done = _as_intish(_get_path(summary, "gas.windows_done")) or 0
                    if windows <= 0 and windows_done <= 0:
                        add(
                            "byte_exact.gas_merge_read.pass_marker",
                            "SKIP",
                            "enabled=1 but no GAS windows observed (gas.windows==0)",
                        )
                    else:
                        marker_pass = "BCSR_MERGE_READ_VERIFY: PASS"
                        marker_inc = "BCSR_MERGE_READ_VERIFY: WARN INCONCLUSIVE"
                        if marker_pass in log_text:
                            add(
                                "byte_exact.gas_merge_read.pass_marker",
                                "PASS",
                                f"enabled=1 marker={marker_pass!r} log={str(log_path) if log_path else 'None'}",
                            )
                        elif marker_inc in log_text:
                            max_steps = _as_intish(meta_model.get("max_steps")) or 0
                            # Step-limited smoke runs can legitimately stop before any relevant reads return;
                            # don't count this as WARN noise in validation (marker still proves logic is wired).
                            if max_steps > 0 and max_steps <= 1:
                                add(
                                    "byte_exact.gas_merge_read.pass_marker",
                                    "SKIP",
                                    f"enabled=1 marker={marker_inc!r} but step-limited (max_steps={max_steps}) log={str(log_path) if log_path else 'None'}",
                                )
                            else:
                                add(
                                    "byte_exact.gas_merge_read.pass_marker",
                                    "WARN",
                                    f"enabled=1 marker={marker_inc!r} log={str(log_path) if log_path else 'None'}",
                                )
                        else:
                            add(
                                "byte_exact.gas_merge_read.pass_marker",
                                "FAIL",
                                f"enabled=1 missing markers (PASS or INCONCLUSIVE) log={str(log_path) if log_path else 'None'}",
                            )

                        # BCSR semantic correctness (sampled): compare runtime weights against file-backed reference.
                        marker_pass = "BCSR_SEMANTIC_VERIFY: PASS"
                        marker_inc = "BCSR_SEMANTIC_VERIFY: WARN INCONCLUSIVE"
                        if marker_pass in log_text:
                            add(
                                "byte_exact.bcsr_semantic.pass_marker",
                                "PASS",
                                f"enabled=1 marker={marker_pass!r} log={str(log_path) if log_path else 'None'}",
                            )
                        elif marker_inc in log_text:
                            add(
                                "byte_exact.bcsr_semantic.pass_marker",
                                "WARN",
                                f"enabled=1 marker={marker_inc!r} log={str(log_path) if log_path else 'None'}",
                            )
                        else:
                            add(
                                "byte_exact.bcsr_semantic.pass_marker",
                                "FAIL",
                                f"enabled=1 missing markers (PASS or INCONCLUSIVE) log={str(log_path) if log_path else 'None'}",
                            )
                else:
                    add(
                        "byte_exact.gas_merge_read.pass_marker",
                        "SKIP",
                        "enabled=1 but unsupported config (no model.bcsr_meta_path)",
                    )
            elif bcsr_merge_read_verify_enable:
                add(
                    "byte_exact.gas_merge_read.pass_marker",
                    "SKIP",
                    f"enabled=1 but synapse_weight_mode={syn_mode or 'unknown'} is not bcsr_gas",
                )
                add(
                    "byte_exact.bcsr_semantic.pass_marker",
                    "SKIP",
                    f"enabled=1 but synapse_weight_mode={syn_mode or 'unknown'} is not bcsr_gas",
                )

            # WeightLoader readback marker is only meaningful for:
            # - BCSR mesh runs (global meta path present -> raw_bcsr verification)
            # - Dense microbench runs (write_pattern_mode/verify_mode dense_rowcol_v1)
            bcsr_meta_path = _get_path(summary, "model.bcsr_meta_path")
            if not (isinstance(bcsr_meta_path, str) and bcsr_meta_path.strip()):
                bcsr_meta_path = meta_model.get("bcsr_meta_path")
            loader_write_pattern_mode = str(local_run_cfg.get("loader_write_pattern_mode", "") or "").strip().lower()
            if (
                loader_verify_readback
                and bcsr_weight_mode
                and (isinstance(bcsr_meta_path, str) and bcsr_meta_path.strip() or loader_write_pattern_mode == "dense_rowcol_v1")
            ):
                marker_pass = "WEIGHT_LOADER_READBACK: PASS"
                marker_inc = "WEIGHT_LOADER_READBACK: WARN INCONCLUSIVE"
                if marker_pass in log_text:
                    add(
                        "byte_exact.loader.readback_marker",
                        "PASS",
                        f"enabled=1 marker={marker_pass!r} log={str(log_path) if log_path else 'None'}",
                    )
                elif marker_inc in log_text:
                    add(
                        "byte_exact.loader.readback_marker",
                        "WARN",
                        f"enabled=1 marker={marker_inc!r} log={str(log_path) if log_path else 'None'}",
                    )
                else:
                    add(
                        "byte_exact.loader.readback_marker",
                        "FAIL",
                        f"enabled=1 missing markers (PASS or INCONCLUSIVE) log={str(log_path) if log_path else 'None'}",
                    )
            elif loader_verify_readback:
                add(
                    "byte_exact.loader.readback_marker",
                    "SKIP",
                    f"enabled=1 but unsupported config (no model.bcsr_meta_path and loader_write_pattern_mode={loader_write_pattern_mode!r})",
                )
            elif loader_verify_readback:
                add(
                    "byte_exact.loader.readback_marker",
                    "SKIP",
                    f"enabled=1 but synapse_weight_mode={syn_mode or 'unknown'} is not bcsr_gas",
                )

    # === Paper profile: provenance and config-vs-summary guardrails ===
    if profile == "paper":
        meta_path = run_dir / "meta.json"
        if not meta_path.exists():
            add("paper.meta.exists", "FAIL", f"missing file: {meta_path}")
        else:
            add("paper.meta.exists", "PASS", f"path={meta_path}")

        schema_v = _as_intish(_get_path(meta_raw or {}, "schema_version")) if isinstance(meta_raw, dict) else None
        if schema_v is None:
            add("paper.meta.schema_version", "FAIL", "missing meta.schema_version (expected 1)")
        else:
            add(
                "paper.meta.schema_version",
                "PASS" if schema_v == 1 else "FAIL",
                f"schema_version={schema_v} expected=1",
            )

        # versions/environment are required for paper-grade reproducibility.
        sst_ver = _get_path(meta_raw or {}, "versions.sst_version")
        py_ver = _get_path(meta_raw or {}, "versions.python_version")
        add(
            "paper.meta.versions",
            "PASS" if (isinstance(sst_ver, str) and sst_ver.strip() and isinstance(py_ver, str) and py_ver.strip()) else "FAIL",
            f"sst_version={sst_ver!r} python_version={py_ver!r}",
        )

        env = _get_path(meta_raw or {}, "environment")
        required_env_keys = [
            "SNNDL_WORKLOAD_IMPL",
            "MESH_EXEC_MODE",
            "MESH_SIM_TIME",
            "MESH_BCSR_DIR",
            "SST_INSTALL_PREFIX",
            "MESH_MAX_STEPS",
        ]
        if isinstance(env, dict):
            missing = [k for k in required_env_keys if k not in env]
            add(
                "paper.meta.environment.keys",
                "PASS" if not missing else "FAIL",
                f"missing={missing}" if missing else "ok",
            )
        else:
            add("paper.meta.environment.keys", "FAIL", f"environment={type(env).__name__} (expected object)")

        # Paper policy: require step-limited runs (no engine stop-at).
        # Rationale: stop-at can truncate in-flight comm/memory activity, making paper plots non-reproducible.
        max_steps_env = None
        if isinstance(env, dict):
            raw = str(env.get("MESH_MAX_STEPS", "") or "").strip()
            if raw:
                try:
                    max_steps_env = int(raw)
                except Exception:
                    max_steps_env = None
        max_steps_meta = _as_intish(_get_path(meta_raw or {}, "model.max_steps"))
        # Accept either source as long as it's positive; require consistency when both exist.
        eff_max_steps: Optional[int] = None
        if (max_steps_env is None and max_steps_meta is None) or ((max_steps_env is not None and max_steps_env <= 0) or (max_steps_meta is not None and max_steps_meta <= 0)):
            add(
                "paper.step_limited.max_steps_positive",
                "FAIL",
                f"MESH_MAX_STEPS={max_steps_env!r} meta.model.max_steps={max_steps_meta!r} (paper requires >0)",
            )
        else:
            if max_steps_env is not None and max_steps_meta is not None and int(max_steps_env) != int(max_steps_meta):
                add(
                    "paper.step_limited.max_steps_positive",
                    "FAIL",
                    f"MESH_MAX_STEPS={max_steps_env} meta.model.max_steps={max_steps_meta} (must match)",
                )
            else:
                # Prefer meta model field for stable provenance, fallback to env.
                eff = max_steps_meta if (max_steps_meta is not None and max_steps_meta > 0) else max_steps_env
                eff_max_steps = int(eff) if eff is not None else None
                add(
                    "paper.step_limited.max_steps_positive",
                    "PASS",
                    f"max_steps={eff}",
                )

        # Paper policy: a run is only acceptable if it actually completes the requested number of global steps.
        if eff_max_steps is not None and eff_max_steps > 0:
            step_gsd = _as_intish(_get_path(summary, "step.global_steps_done"))
            if step_gsd is None:
                add(
                    "paper.step_limited.steps_completed",
                    "FAIL",
                    f"missing step.global_steps_done (expected={eff_max_steps})",
                )
            else:
                add(
                    "paper.step_limited.steps_completed",
                    "PASS" if step_gsd == eff_max_steps else "FAIL",
                    f"global_steps_done={step_gsd} expected={eff_max_steps}",
                    )

            # GAS mode additionally requires gas.global_steps_done to agree (guards against partial-window early exits).
            env_exec_mode = ""
            if isinstance(env, dict):
                env_exec_mode = str(env.get("MESH_EXEC_MODE") or "").strip().lower()
            if env_exec_mode == "gas":
                gas_gsd = _as_intish(_get_path(summary, "gas.global_steps_done"))
                if gas_gsd is None:
                    add(
                        "paper.step_limited.gas_steps_completed",
                        "FAIL",
                        f"missing gas.global_steps_done (expected={eff_max_steps})",
                    )
                else:
                    add(
                        "paper.step_limited.gas_steps_completed",
                        "PASS" if gas_gsd == eff_max_steps else "FAIL",
                        f"gas.global_steps_done={gas_gsd} expected={eff_max_steps}",
                    )

            # Paper policy: step-limited comparisons may optionally require "no within-step cascade" semantics.
            # Under that strict contract, all spikes processed by compute should come from the step injector,
            # so total_spikes_processed must match spikes_injected_total exactly.
            #
            # However, for many SNN experiments (and most non-freeze runs), within-step cascade is expected
            # and can legitimately amplify processed spikes beyond injected spikes. In that case, enforce only
            # the minimal sanity: processed >= injected, and downgrade the equality check to WARN when violated.
            inj = _as_intish(_get_path(summary, "step_activation.spikes_injected_total"))
            proc = _as_intish(_get_path(summary, "spike_activity.total_spikes_processed"))
            if inj is None or proc is None:
                add(
                    "paper.step_limited.processed_equals_injected",
                    "SKIP",
                    f"missing spike counts: injected={inj!r} processed={proc!r}",
                )
            else:
                inj_i = int(inj)
                proc_i = int(proc)

                require_no_cascade = False
                if isinstance(env, dict):
                    v = str(env.get("MESH_VALIDATE_REQUIRE_NO_WITHIN_STEP_CASCADE") or "").strip().lower()
                    if v in ("1", "true", "yes", "y", "on"):
                        require_no_cascade = True
                if isinstance(local_run_cfg, dict):
                    try:
                        require_no_cascade = require_no_cascade or bool(int(local_run_cfg.get("paper_no_within_step_cascade") or 0))
                    except Exception:
                        pass

                if proc_i < inj_i:
                    add(
                        "paper.step_limited.processed_equals_injected",
                        "FAIL",
                        f"processed={proc_i} injected={inj_i} (sanity violated: processed < injected)",
                    )
                elif require_no_cascade:
                    add(
                        "paper.step_limited.processed_equals_injected",
                        "PASS" if proc_i == inj_i else "FAIL",
                        f"processed={proc_i} injected={inj_i} require_no_within_step_cascade=1",
                    )
                else:
                    add(
                        "paper.step_limited.processed_equals_injected",
                        "PASS" if proc_i == inj_i else "WARN",
                        f"processed={proc_i} injected={inj_i} (within-step cascade allowed)",
                    )

        # Input hash: local_run_config must be present + sha256 must match.
        cfg_path = _find_local_run_config_path(run_dir=run_dir, meta_raw=meta_raw)
        lrc = _get_path(meta_raw or {}, "inputs.local_run_config")
        sha_expected = _get_path(meta_raw or {}, "inputs.local_run_config.sha256")
        p_expected = _get_path(meta_raw or {}, "inputs.local_run_config.path")
        if cfg_path is None:
            add("paper.meta.inputs.local_run_config", "FAIL", "missing inputs/local_run_config.json in run dir")
        elif not (isinstance(lrc, dict) and isinstance(sha_expected, str) and sha_expected.strip() and isinstance(p_expected, str) and p_expected.strip()):
            add(
                "paper.meta.inputs.local_run_config",
                "FAIL",
                f"missing meta.inputs.local_run_config.path/sha256 (meta.inputs.local_run_config={lrc!r})",
            )
        else:
            sha_actual = _sha256_path(cfg_path)
            add(
                "paper.meta.inputs.local_run_config",
                "PASS" if sha_actual == sha_expected else "FAIL",
                f"path={p_expected} sha256={sha_actual} expected={sha_expected}",
            )

        # Config vs summary invariants (prevents silent "units/meaning" regressions).
        if isinstance(local_run_cfg, dict):
            cfg_ncores = _as_intish(local_run_cfg.get("num_cores_per_pe"))
            cfg_npc = _as_intish(local_run_cfg.get("neurons_per_core"))
            cfg_sim_time = str(local_run_cfg.get("sim_time") or "").strip()
            cfg_frac = local_run_cfg.get("step_activation_fraction")
            cfg_fanout = _as_intish(local_run_cfg.get("step_activation_fanout"))
            cfg_use_bcsr = bool(_as_intish(local_run_cfg.get("step_activation_use_bcsr_routes")) or 0)

            sum_ncores = _as_intish(_get_path(summary, "model.num_cores_per_pe"))
            if sum_ncores is None:
                sum_ncores = _as_intish(meta_model.get("num_cores_per_pe"))
            sum_npc = _as_intish(_get_path(summary, "model.neurons_per_core"))
            if sum_npc is None:
                sum_npc = _as_intish(meta_model.get("neurons_per_core"))
            sum_npp = _as_intish(_get_path(summary, "model.neurons_per_pe"))
            if sum_npp is None:
                sum_npp = _as_intish(meta_model.get("neurons_per_pe"))

            sum_sim_time = str(
                meta_model.get("sim_time_override")
                or meta_model.get("sim_time")
                or _get_path(summary, "model.sim_time_override")
                or _get_path(summary, "model.sim_time")
                or ""
            ).strip()
            sum_frac = _as_float(meta_model.get("step_activation_fraction"))
            if sum_frac is None:
                sum_frac = _as_float(_get_path(summary, "model.step_activation_fraction"))
            sum_fanout = _as_intish(meta_model.get("step_activation_fanout"))
            if sum_fanout is None:
                sum_fanout = _as_intish(_get_path(summary, "model.step_activation_fanout"))
            meta_env = _get_path(meta_raw or {}, "environment")
            if not isinstance(meta_env, dict):
                meta_env = {}
            env_sim_time = str(meta_env.get("MESH_SIM_TIME") or "").strip()
            env_frac_raw = str(meta_env.get("MESH_STEP_ACTIVATION_FRACTION") or "").strip()
            env_fanout_raw = str(meta_env.get("MESH_STEP_ACTIVATION_FANOUT") or "").strip()

            # Layout: prefer cfg as source of truth (runner archived it explicitly).
            if cfg_ncores is None or cfg_npc is None or sum_npp is None:
                add(
                    "paper.config_vs_summary.layout",
                    "FAIL",
                    f"need cfg(num_cores_per_pe,neurons_per_core) and summary.model.neurons_per_pe "
                    f"(cfg_ncores={cfg_ncores} cfg_npc={cfg_npc} sum_npp={sum_npp})",
                )
            else:
                exp_npp = cfg_ncores * cfg_npc
                add(
                    "paper.config_vs_summary.layout",
                    "PASS" if sum_npp == exp_npp else "FAIL",
                    f"summary.neurons_per_pe={sum_npp} expected={exp_npp} (=cfg.num_cores_per_pe*cfg.neurons_per_core)",
                )
            # Direct echo checks: reduce "wrong file loaded" class of failures.
            if cfg_sim_time and sum_sim_time:
                if cfg_sim_time == sum_sim_time:
                    add(
                        "paper.config_vs_summary.sim_time",
                        "PASS",
                        f"summary.sim_time={sum_sim_time!r} cfg.sim_time={cfg_sim_time!r}",
                    )
                else:
                    # Allow explicit env override (recorded in meta.json) for experiment sweeps.
                    if env_sim_time and env_sim_time == sum_sim_time:
                        add(
                            "paper.config_vs_summary.sim_time",
                            "PASS",
                            f"summary.sim_time={sum_sim_time!r} cfg.sim_time={cfg_sim_time!r} (env_override={env_sim_time!r})",
                        )
                    else:
                        add(
                            "paper.config_vs_summary.sim_time",
                            "FAIL",
                            f"summary.sim_time={sum_sim_time!r} cfg.sim_time={cfg_sim_time!r}",
                        )
            elif cfg_sim_time:
                add("paper.config_vs_summary.sim_time", "FAIL", f"missing summary.sim_time (cfg.sim_time={cfg_sim_time!r})")
            else:
                add("paper.config_vs_summary.sim_time", "FAIL", "missing cfg.sim_time")

            if cfg_frac is not None and sum_frac is not None:
                if _close(float(sum_frac), float(cfg_frac), abs_tol=0.0, rel_tol=0.0):
                    add(
                        "paper.config_vs_summary.step_fraction",
                        "PASS",
                        f"summary.step_activation_fraction={sum_frac} cfg={cfg_frac}",
                    )
                else:
                    # Allow explicit env override for experiment sweeps (recorded in meta.json).
                    env_frac = None
                    if env_frac_raw:
                        try:
                            env_frac = float(env_frac_raw)
                        except Exception:
                            env_frac = None
                    if env_frac is not None and _close(float(sum_frac), float(env_frac), abs_tol=0.0, rel_tol=0.0):
                        add(
                            "paper.config_vs_summary.step_fraction",
                            "PASS",
                            f"summary.step_activation_fraction={sum_frac} cfg={cfg_frac} (env_override={env_frac})",
                        )
                    else:
                        add(
                            "paper.config_vs_summary.step_fraction",
                            "FAIL",
                            f"summary.step_activation_fraction={sum_frac} cfg={cfg_frac}",
                        )
            elif cfg_frac is not None:
                add("paper.config_vs_summary.step_fraction", "FAIL", f"missing summary.model.step_activation_fraction (cfg={cfg_frac})")
            else:
                add("paper.config_vs_summary.step_fraction", "FAIL", "missing cfg.step_activation_fraction")

            if cfg_fanout is not None and sum_fanout is not None:
                if sum_fanout == cfg_fanout:
                    add(
                        "paper.config_vs_summary.step_fanout",
                        "PASS",
                        f"summary.step_activation_fanout={sum_fanout} cfg={cfg_fanout}",
                    )
                else:
                    env_fanout = None
                    if env_fanout_raw:
                        try:
                            env_fanout = int(env_fanout_raw)
                        except Exception:
                            env_fanout = None
                    if env_fanout is not None and sum_fanout == env_fanout:
                        add(
                            "paper.config_vs_summary.step_fanout",
                            "PASS",
                            f"summary.step_activation_fanout={sum_fanout} cfg={cfg_fanout} (env_override={env_fanout})",
                        )
                    else:
                        add(
                            "paper.config_vs_summary.step_fanout",
                            "FAIL",
                            f"summary.step_activation_fanout={sum_fanout} cfg={cfg_fanout}",
                        )
            elif cfg_fanout is not None:
                add("paper.config_vs_summary.step_fanout", "FAIL", f"missing summary.model.step_activation_fanout (cfg={cfg_fanout})")
            else:
                add("paper.config_vs_summary.step_fanout", "FAIL", "missing cfg.step_activation_fanout")

            # BCSR provenance requirement (paper default weights-hash=bcsr-meta):
            # only enforce when the run config explicitly enables BCSR routing.
            if cfg_use_bcsr:
                bcsr = _get_path(meta_raw or {}, "inputs.bcsr")
                meta_files = _get_path(meta_raw or {}, "inputs.bcsr.meta_files")
                if not (isinstance(bcsr, dict) and isinstance(meta_files, list) and len(meta_files) > 0):
                    add("paper.meta.inputs.bcsr_meta", "FAIL", "cfg.step_activation_use_bcsr_routes=1 but meta.inputs.bcsr.meta_files is missing/empty")
                else:
                    # Validate each archived meta file hash.
                    bad = 0
                    for ent in meta_files:
                        p = ent.get("path") if isinstance(ent, dict) else None
                        sha = ent.get("sha256") if isinstance(ent, dict) else None
                        if not (isinstance(p, str) and p.strip() and isinstance(sha, str) and sha.strip()):
                            bad += 1
                            continue
                        fp = (run_dir / p).resolve()
                        if not fp.exists():
                            bad += 1
                            continue
                        if _sha256_path(fp) != sha:
                            bad += 1
                    add(
                        "paper.meta.inputs.bcsr_meta",
                        "PASS" if bad == 0 else "FAIL",
                        f"meta_files={len(meta_files)} bad={bad} (archived under run_dir)",
                    )
        else:
            add("paper.config_vs_summary.layout", "FAIL", "missing local_run_config.json (required in paper profile)")

    # Execution mode hint (GAS vs non-GAS naive baselines).
    # If not recorded, infer from whether stage events exist (gas.windows > 0).
    exec_mode_raw = str(_get_path(summary, "model.exec_mode") or meta_model.get("exec_mode") or "").strip().lower()
    workload_impl = str(_get_path(summary, "model.workload_impl") or meta_model.get("workload_impl") or "").strip().lower() or "snn"
    synapse_weight_mode = str(
        _get_path(summary, "model.synapse_weight_mode")
        or _get_path(summary, "synapse.weight_mode")
        or meta_model.get("synapse_weight_mode")
        or ""
    ).strip().lower()
    model_kind = str(_get_path(summary, "model.kind") or "").strip().lower()

    mesh_size = _as_intish(_get_path(summary, "model.mesh_size"))
    if mesh_size is None:
        mesh_size = _as_intish(meta_model.get("mesh_size"))
    node_limit = _as_intish(_get_path(summary, "model.node_limit"))
    if node_limit is None:
        node_limit = _as_intish(meta_model.get("node_limit"))
    if node_limit is None and isinstance(local_run_cfg, dict):
        node_limit = _as_intish(local_run_cfg.get("node_limit"))
    if node_limit is None:
        node_limit = _as_intish(spec_platform.get("node_limit"))
    num_pes = _as_intish(_get_path(summary, "model.num_pes"))
    if num_pes is None:
        num_pes = _as_intish(meta_model.get("num_pes"))
    if mesh_size is not None and num_pes is not None:
        exp = mesh_size * mesh_size
        if node_limit is not None and node_limit > 0:
            exp = min(exp, node_limit)
        add(
            "model.num_pes",
            "PASS" if num_pes == exp else "FAIL",
            f"mesh_size={mesh_size} node_limit={node_limit} num_pes={num_pes} expected={exp}",
        )
    else:
        add("model.num_pes", "SKIP", "missing model.mesh_size/model.num_pes")

    neurons_total = _as_intish(_get_path(summary, "model.neurons_total"))
    if neurons_total is None:
        neurons_total = _as_intish(meta_model.get("neurons_total"))
    neurons_per_pe = _as_intish(_get_path(summary, "model.neurons_per_pe"))
    if neurons_per_pe is None:
        neurons_per_pe = _as_intish(meta_model.get("neurons_per_pe"))
    if neurons_total is not None and neurons_per_pe is not None and num_pes is not None:
        exp = num_pes * neurons_per_pe
        add(
            "model.neurons_total",
            "PASS" if neurons_total == exp else "FAIL",
            f"neurons_total={neurons_total} expected={exp} (num_pes={num_pes} neurons_per_pe={neurons_per_pe})",
        )
    else:
        add("model.neurons_total", "SKIP", "missing neurons_total/neurons_per_pe/num_pes")

    # Layout sanity: neurons_per_pe should match num_cores_per_pe * neurons_per_core when recorded.
    ncores = _as_intish(_get_path(summary, "model.num_cores_per_pe"))
    if ncores is None:
        ncores = _as_intish(meta_model.get("num_cores_per_pe"))
    npc = _as_intish(_get_path(summary, "model.neurons_per_core"))
    if npc is None:
        npc = _as_intish(meta_model.get("neurons_per_core"))
    if ncores is not None and npc is not None and neurons_per_pe is not None:
        exp = ncores * npc
        add(
            "model.neurons_per_pe_formula",
            "PASS" if neurons_per_pe == exp else "FAIL",
            f"neurons_per_pe={neurons_per_pe} expected={exp} (=num_cores_per_pe*neurons_per_core)",
        )
    else:
        add("model.neurons_per_pe_formula", "SKIP", "missing model.num_cores_per_pe/model.neurons_per_core/model.neurons_per_pe")

    # BCSR meta invariants (when available): rows override should match neurons_per_core.
    bcsr_rows = _as_intish(_get_path(summary, "model.bcsr_rows_override"))
    if bcsr_rows is None:
        bcsr_rows = _as_intish(meta_model.get("bcsr_rows_override"))
    if bcsr_rows is not None and npc is not None:
        add(
            "model.bcsr_rows_match_neurons_per_core",
            "PASS" if bcsr_rows == npc else "FAIL",
            f"bcsr_rows_override={bcsr_rows} neurons_per_core={npc}",
        )
    else:
        add("model.bcsr_rows_match_neurons_per_core", "SKIP", "missing model.bcsr_rows_override/model.neurons_per_core")

    # Optional: ensure referenced BCSR meta file exists (helps catch 'wrong weights dir' regressions).
    bcsr_meta_path = _get_path(summary, "model.bcsr_meta_path")
    if not (isinstance(bcsr_meta_path, str) and bcsr_meta_path.strip()):
        bcsr_meta_path = meta_model.get("bcsr_meta_path")
    if isinstance(bcsr_meta_path, str) and bcsr_meta_path.strip():
        p = Path(bcsr_meta_path)
        add(
            "model.bcsr_meta_path_exists",
            "PASS" if p.exists() else "FAIL",
            f"path={bcsr_meta_path}",
        )
    else:
        add("model.bcsr_meta_path_exists", "SKIP", "missing model.bcsr_meta_path")

    # GAS window accounting
    w = _as_intish(_get_path(summary, "gas.windows"))
    wd = _as_intish(_get_path(summary, "gas.windows_done"))
    wi = _as_intish(_get_path(summary, "gas.windows_incomplete"))
    exec_mode = exec_mode_raw
    if not exec_mode:
        wv = w if w is not None else 0
        invv = _as_intish(_get_path(summary, "step_activation.invocations")) or 0
        if wv > 0:
            exec_mode = "gas"
        elif invv > 0:
            exec_mode = "naive"
        else:
            exec_mode = "unknown"
        add("model.exec_mode_infer", "WARN", f"missing model.exec_mode; inferred={exec_mode!r}")
    else:
        add("model.exec_mode_infer", "PASS", f"exec_mode={exec_mode!r}")

    if w is not None and wd is not None and wi is not None:
        add(
            "gas.windows_accounting",
            "PASS" if (wd + wi) == w else "FAIL",
            f"windows={w} done={wd} incomplete={wi} done+incomplete={wd + wi}",
        )
    else:
        add("gas.windows_accounting", "SKIP", "missing gas.windows/windows_done/windows_incomplete")

    # Paper-only: windows_incomplete must be 0 for publication-grade runs.
    if profile == "paper":
        if wi is None:
            add("paper.gas.windows_incomplete_zero", "FAIL", "missing gas.windows_incomplete")
        else:
            add(
                "paper.gas.windows_incomplete_zero",
                "PASS" if wi == 0 else "FAIL",
                f"windows_incomplete={wi}",
            )

    # Step activation should be invoked once per GAS window (BeginGather) in classic workload=snn gas mode.
    # For non-snn workloads such as riscv_snn, step activation remains a stimulus source rather than the
    # architectural execution boundary, so this equality is not required.
    inv = _as_intish(_get_path(summary, "step_activation.invocations"))
    if inv is not None and w is not None:
        if workload_impl != "snn":
            add(
                "step_activation.invocations_vs_windows",
                "SKIP",
                f"workload_impl={workload_impl!r} (step activation is not the architectural step boundary)",
            )
        elif w == 0:
            if exec_mode == "gas":
                add(
                    "step_activation.invocations_vs_windows",
                    "FAIL",
                    f"exec_mode='gas' but gas.windows=0 (missing stage events?) invocations={inv}",
                )
            else:
                add(
                    "step_activation.invocations_vs_windows",
                    "SKIP",
                    f"exec_mode={exec_mode!r} gas.windows=0 (non-GAS baseline)",
                )
        else:
            add(
                "step_activation.invocations_vs_windows",
                "PASS" if inv == w else "FAIL",
                f"invocations={inv} windows={w}",
            )
    else:
        add("step_activation.invocations_vs_windows", "SKIP", "missing step_activation.invocations or gas.windows")

    # Step activation internal arithmetic checks
    frac = _as_float(_get_path(summary, "model.step_activation_fraction"))
    if frac is None:
        frac = _as_float(meta_model.get("step_activation_fraction"))
    frac = float(frac or 0.0)

    fanout = _as_intish(_get_path(summary, "model.step_activation_fanout"))
    if fanout is None:
        fanout = _as_intish(meta_model.get("step_activation_fanout"))
    fanout = int(fanout or 0)
    pre_sel = _as_intish(_get_path(summary, "step_activation.pre_selected_total"))
    fire_total = _as_intish(_get_path(summary, "step_activation.firing_total"))
    spike_attempts = _as_intish(_get_path(summary, "step_activation.spike_attempts_total"))
    spikes_injected = _as_intish(_get_path(summary, "step_activation.spikes_injected_total"))
    route_hits = _as_intish(_get_path(summary, "step_activation.route_hits_total"))
    route_miss = _as_intish(_get_path(summary, "step_activation.route_misses_total"))
    local_drops = _as_intish(_get_path(summary, "step_activation.local_drops_total"))
    fanout_eff = _as_intish(_get_path(summary, "step_activation.fanout_effective"))
    fanout_cfg = _as_intish(_get_path(summary, "step_activation.fanout_config"))
    if fanout_cfg is None and fanout > 0:
        # schema v2 summary no longer carries fanout_config (provenance belongs to meta.json).
        # Use model/meta fanout as the configured fanout for arithmetic checks.
        fanout_cfg = int(fanout)

    if pre_sel is not None and fire_total is not None:
        add(
            "step_activation.firing_total_eq_pre_selected",
            "PASS" if fire_total == pre_sel else "FAIL",
            f"firing_total={fire_total} pre_selected_total={pre_sel}",
        )
    else:
        add("step_activation.firing_total_eq_pre_selected", "SKIP", "missing firing_total/pre_selected_total")

    if fanout_cfg is not None and fanout_eff is not None and fanout_cfg > 0:
        add(
            "step_activation.fanout_effective_le_config",
            "PASS" if (0 < fanout_eff <= fanout_cfg) else "FAIL",
            f"fanout_effective={fanout_eff} fanout_config={fanout_cfg}",
        )
    else:
        add("step_activation.fanout_effective_le_config", "SKIP", "missing fanout_effective/fanout_config")

    if fanout_cfg is not None and fanout > 0 and fanout_cfg != fanout:
        add(
            "step_activation.fanout_config_matches_model",
            "WARN",
            f"model.fanout={fanout} step_activation.fanout_config={fanout_cfg}",
        )

    if pre_sel is not None and fanout_cfg is not None and spike_attempts is not None:
        exp = pre_sel * fanout_cfg
        add(
            "step_activation.spike_attempts_arith",
            "PASS" if spike_attempts == exp else "FAIL",
            f"spike_attempts_total={spike_attempts} expected={exp} (=pre_selected_total*fanout_config)",
        )
    else:
        add("step_activation.spike_attempts_arith", "SKIP", "missing spike_attempts_total/pre_selected_total/fanout_config")

    if spikes_injected is not None and route_hits is not None and route_miss is not None and local_drops is not None:
        # Dense microbench runs disable BCSR route stats; tolerate missing route accounting.
        if model_kind.startswith("dense_microbench") and route_hits == 0 and route_miss == 0 and local_drops == 0:
            add(
                "step_activation.injection_vs_route_hits",
                "SKIP",
                f"model.kind={model_kind!r} route counters are disabled/unused (spikes_injected_total={spikes_injected})",
            )
            add(
                "step_activation.attempts_eq_hits_miss_drops",
                "SKIP",
                f"model.kind={model_kind!r} route counters are disabled/unused (spike_attempts_total={spike_attempts})",
            )
        else:
            # injected should match hits in the typical fully-resolved route case.
            add(
                "step_activation.injection_vs_route_hits",
                "PASS" if spikes_injected == route_hits else "WARN",
                f"spikes_injected_total={spikes_injected} route_hits_total={route_hits} (route_misses={route_miss} local_drops={local_drops})",
            )
            exp_attempts = route_hits + route_miss + local_drops
            if spike_attempts is not None:
                add(
                    "step_activation.attempts_eq_hits_miss_drops",
                    "PASS" if spike_attempts == exp_attempts else "FAIL",
                    f"spike_attempts_total={spike_attempts} expected={exp_attempts} (=hits+misses+drops)",
                )
    else:
        add("step_activation.attempts_eq_hits_miss_drops", "SKIP", "missing route/injection totals")

    # Paper-only: tolerate tiny drops by threshold; route misses default to 0.
    if profile == "paper":
        if spike_attempts is None or route_miss is None or local_drops is None:
            add(
                "paper.step_activation.loss_thresholds",
                "FAIL",
                f"missing spike_attempts_total/route_misses_total/local_drops_total "
                f"(attempts={spike_attempts} miss={route_miss} drops={local_drops})",
            )
        else:
            allow_miss = _paper_allowed_loss(route_miss, spike_attempts, max_route_miss_abs, max_route_miss_frac)
            allow_drop = _paper_allowed_loss(local_drops, spike_attempts, max_local_drop_abs, max_local_drop_frac)
            miss_ok = route_miss <= allow_miss
            drop_ok = local_drops <= allow_drop
            add(
                "paper.step_activation.loss_thresholds",
                "PASS" if (miss_ok and drop_ok) else "FAIL",
                f"attempts={spike_attempts} route_miss={route_miss} allow_miss={allow_miss} "
                f"local_drop={local_drops} allow_drop={allow_drop} "
                f"(max_miss_abs={max_route_miss_abs} max_miss_frac={max_route_miss_frac} "
                f"max_drop_abs={max_local_drop_abs} max_drop_frac={max_local_drop_frac})",
            )

    # Pre-selection domain inference (helps catch 'wrong population' sampling bugs)
    if inv and inv > 0 and frac > 0.0 and pre_sel is not None:
        pop_est = float(pre_sel) / (float(inv) * frac)

        # In the mesh template, StepActivationSubsystem runs per-PE and samples from a PE-local population.
        # Therefore total pre_selected_total (summed across PEs) should be close to invocations*frac*neurons_per_pe.
        pop_note = ""
        expected_pop = None
        if neurons_per_pe and neurons_per_pe > 0:
            expected_pop = float(neurons_per_pe)
            pop_note = "expect≈neurons_per_pe (PE-local pre sampling)"
        elif neurons_total and neurons_total > 0:
            expected_pop = float(neurons_total)
            pop_note = "expect≈neurons_total (global pre sampling)"

        status = "WARN"
        extra = ""
        if expected_pop is not None:
            mean = float(inv) * frac * expected_pop
            # Binomial approximation: sum over inv independent trials with n=pop, p=frac.
            var = float(inv) * expected_pop * frac * max(0.0, 1.0 - frac)
            sigma = math.sqrt(var) if var > 0.0 else 0.0
            if sigma > 0.0:
                z = (float(pre_sel) - mean) / sigma
                az = abs(z)
                # 6-sigma is already extremely unlikely; beyond that, likely a population/units bug.
                if az <= 6.0:
                    status = "PASS"
                elif az >= 12.0:
                    status = "FAIL"
                extra = f" mean={mean:.2f} sigma≈{sigma:.2f} z≈{z:.2f}"
            else:
                # Degenerate sigma: treat as informational unless values are clearly inconsistent.
                status = "PASS" if float(pre_sel) == mean else "WARN"
                extra = f" mean={mean:.2f} (sigma=0)"

        add(
            "step_activation.pre_population_infer",
            status,
            f"pop≈{pop_est:.1f} ({pop_note}){extra}".strip(),
        )
    else:
        add("step_activation.pre_population_infer", "SKIP", "need invocations>0 and fraction>0 and pre_selected_total")

    # Firing rate formula sanity: firing_total / (neurons_total * sim_time_us)
    fr = _as_float(_get_path(summary, "step_activation.firing_rate_per_neuron_per_us"))
    sim_time = str(
        _get_path(summary, "model.sim_time_override")
        or _get_path(summary, "model.sim_time")
        or meta_model.get("sim_time_override")
        or meta_model.get("sim_time")
        or ""
    )
    sim_ns = _parse_time_to_ns(sim_time)
    sim_ns_actual = _as_intish(_get_path(summary, "model.sim_time_actual_ns"))
    # Step-limited runs may end far earlier/later than model.sim_time (stop-at is disabled);
    # prefer actual sim end time inferred from mesh_stats.csv when available.
    if sim_ns_actual is not None and sim_ns_actual > 0:
        sim_ns = sim_ns_actual
    if fr is not None and fire_total is not None and neurons_total is not None and sim_ns is not None and sim_ns > 0:
        sim_us = sim_ns / 1_000.0
        exp = float(fire_total) / (float(neurons_total) * sim_us) if sim_us > 0 else 0.0
        # 该字段对 sim_time 极敏感（10us/100us 直接差 10×），因此这里默认使用更严格的相对误差门槛；
        # 避免使用大 abs_tol 误放过严重错误。
        formula_abs_tol = 1e-12
        formula_rel_tol = 1e-6
        add(
            "step_activation.firing_rate_formula",
            "PASS" if _close(fr, exp, abs_tol=formula_abs_tol, rel_tol=formula_rel_tol) else "FAIL",
            f"rate={fr:.8g} expected={exp:.8g} (abs_tol={formula_abs_tol} rel_tol={formula_rel_tol}) "
            f"(fire_total={fire_total} neurons_total={neurons_total} sim_time={sim_time} sim_time_actual_ns={_fmt_num(sim_ns_actual)})",
        )
    else:
        add("step_activation.firing_rate_formula", "SKIP", "missing firing_rate/firing_total/neurons_total/sim_time")

    # GAS "global_steps_done" consistency check (barrier mode expectation)
    # NOTE: For naive baselines, stage_events are absent, so windows_done is meaningless here.
    gsd = _as_intish(_get_path(summary, "gas.global_steps_done"))
    if exec_mode != "gas":
        add("gas.global_steps_done_vs_windows_done", "SKIP", f"exec_mode={exec_mode!r} (non-GAS baseline)")
    elif gsd is not None and wd is not None and num_pes is not None and num_pes > 0:
        exp_min = gsd * num_pes
        if wd < exp_min:
            add(
                "gas.global_steps_done_vs_windows_done",
                "FAIL",
                f"windows_done={wd} < global_steps_done*num_pes={exp_min}",
            )
        else:
            # windows_done is aggregated across all PEs; it is valid to have multiple GAS windows per global step.
            # Treat equality as a strong PASS; treat "multiple windows per PE" as PASS as long as it's aligned by num_pes.
            per_pe = (wd // num_pes) if num_pes else 0
            aligned = (wd % num_pes) == 0
            status = "PASS" if aligned else "WARN"
            add(
                "gas.global_steps_done_vs_windows_done",
                status,
                f"windows_done={wd} global_steps_done={gsd} num_pes={num_pes} min={exp_min} windows_per_pe={per_pe}",
            )
    else:
        add("gas.global_steps_done_vs_windows_done", "SKIP", "missing global_steps_done/windows_done/num_pes")

    # gsops_step sanity: synapse_ops_step_total / cycle_cost
    synops = _as_float(_get_path(summary, "gas.synapse_ops_step_total"))
    gsops = _as_float(_get_path(summary, "gas.gsops_step"))
    cycle_cost = _as_float(_get_path(summary, "gas.cycle_cost"))
    if synops is not None and gsops is not None and cycle_cost is not None and cycle_cost > 0:
        exp = synops / cycle_cost
        formula_abs_tol = 1e-9
        formula_rel_tol = 1e-6
        add(
            "gas.gsops_step_formula",
            "PASS" if _close(gsops, exp, abs_tol=formula_abs_tol, rel_tol=formula_rel_tol) else "WARN",
            f"gsops_step={gsops:.8g} expected≈{exp:.8g} (abs_tol={formula_abs_tol} rel_tol={formula_rel_tol}) "
            f"(=synapse_ops_step_total/cycle_cost)",
        )
    else:
        add("gas.gsops_step_formula", "SKIP", "missing synapse_ops_step_total/gsops_step/cycle_cost")

    # Spike activity sanity: forbid 'hard zero' for long runs
    fired = _as_intish(_get_path(summary, "spike_activity.neurons_fired_total"))
    scat_emit = _as_intish(_get_path(summary, "spike_activity.gas_scatter_spikes_emitted_total"))
    allow_zero_long = _as_intish(_get_path(summary, "model.allow_zero_firing_long"))
    if allow_zero_long is None:
        allow_zero_long = _as_intish(meta_model.get("allow_zero_firing_long"))
    allow_zero_long = int(allow_zero_long or 0)
    if fired is not None:
        if workload_impl != "snn":
            add(
                "spike_activity.neurons_fired_total_nonzero",
                "SKIP",
                f"workload_impl={workload_impl!r} (non-SNN workload)",
            )
        elif allow_zero_long:
            add(
                "spike_activity.neurons_fired_total_nonzero",
                "SKIP",
                f"allow_zero_firing_long=1 neurons_fired_total={fired} (sim_time={sim_time})",
            )
        else:
            # 10us may legitimately be 0 in some configs; for 100us acceptance we want non-zero.
            # Prefer actual sim time if present (step-limited runs do not use stop-at).
            actual_ns = _as_intish(_get_path(summary, "model.sim_time_actual_ns"))
            use_ns = actual_ns if (actual_ns is not None and actual_ns > 0) else sim_ns
            strict_long = (use_ns is not None and use_ns >= 100_000)  # >=100us
            if strict_long and fired <= 0:
                add("spike_activity.neurons_fired_total_nonzero", "FAIL", f"neurons_fired_total={fired} (sim_time={sim_time})")
            else:
                add("spike_activity.neurons_fired_total_nonzero", "PASS", f"neurons_fired_total={fired} (sim_time={sim_time})")
    else:
        add("spike_activity.neurons_fired_total_nonzero", "SKIP", "missing spike_activity.neurons_fired_total")

    if fired is not None and scat_emit is not None:
        add(
            "spike_activity.fired_vs_scatter_emitted",
            "PASS" if fired == scat_emit else "WARN",
            f"neurons_fired_total={fired} gas_scatter_spikes_emitted_total={scat_emit}",
        )

    # SNN receive-path evidence for SpikeKey/SpikeTileKey + fastpath.
    snn_rx_spike = _as_intish(_get_path(summary, "snn_rx.spike_packets_total"))
    snn_rx_key = _as_intish(_get_path(summary, "snn_rx.spikekey_packets_total"))
    snn_rx_tile = _as_intish(_get_path(summary, "snn_rx.spiketilekey_packets_total"))
    snn_rx_fast = _as_intish(_get_path(summary, "snn_rx.fastpath_packets_total"))
    snn_rx_fallback = _as_intish(_get_path(summary, "snn_rx.fallback_packets_total"))
    snn_rx_decode_fail = _as_intish(_get_path(summary, "snn_rx.decode_fail_total"))
    model_fastpath_enable = _as_intish(_get_path(summary, "model.experimental_spikekey_fastpath_enable"))

    if any(v is not None for v in (snn_rx_spike, snn_rx_key, snn_rx_tile, snn_rx_fast, snn_rx_fallback, snn_rx_decode_fail)):
        total_key_packets = int(snn_rx_key or 0) + int(snn_rx_tile or 0)
        total_rx_packets = total_key_packets + int(snn_rx_spike or 0)
        if snn_rx_fast is not None and snn_rx_fallback is not None:
            accounted = int(snn_rx_fast) + int(snn_rx_fallback)
            add(
                "snn_rx.packet_accounting",
                "PASS" if accounted == total_key_packets else "WARN",
                f"rx_packets={total_rx_packets} key_packets={total_key_packets} fastpath={_fmt_num(snn_rx_fast)} fallback={_fmt_num(snn_rx_fallback)}",
            )
        else:
            add("snn_rx.packet_accounting", "SKIP", "missing snn_rx.fastpath_packets_total/fallback_packets_total")

        if model_fastpath_enable is not None:
            if model_fastpath_enable != 0 and total_key_packets > 0:
                add(
                    "snn_rx.fastpath_enabled_effective",
                    "PASS" if int(snn_rx_fast or 0) > 0 else "FAIL",
                    f"model.experimental_spikekey_fastpath_enable={model_fastpath_enable} key_packets={total_key_packets} fastpath_packets={_fmt_num(snn_rx_fast)}",
                )
            elif model_fastpath_enable == 0 and total_key_packets > 0:
                add(
                    "snn_rx.fastpath_disabled_zero",
                    "PASS" if int(snn_rx_fast or 0) == 0 else "WARN",
                    f"model.experimental_spikekey_fastpath_enable={model_fastpath_enable} fastpath_packets={_fmt_num(snn_rx_fast)}",
                )
            else:
                add(
                    "snn_rx.fastpath_enabled_effective",
                    "SKIP",
                    f"model.experimental_spikekey_fastpath_enable={model_fastpath_enable} key_packets={total_key_packets}",
                )
        else:
            add("snn_rx.fastpath_enabled_effective", "SKIP", "missing model.experimental_spikekey_fastpath_enable")
    else:
        add("snn_rx.packet_accounting", "SKIP", "missing snn_rx section")
        add("snn_rx.fastpath_enabled_effective", "SKIP", "missing snn_rx section")

    # SNN send-path evidence (tx kind breakdown), used to close tx->rx packet-kind observability loop.
    snn_tx_spike = _as_intish(_get_path(summary, "snn_tx.spike_packets_total"))
    snn_tx_key = _as_intish(_get_path(summary, "snn_tx.spikekey_packets_total"))
    snn_tx_tile = _as_intish(_get_path(summary, "snn_tx.spiketilekey_packets_total"))
    if any(v is not None for v in (snn_tx_spike, snn_tx_key, snn_tx_tile)):
        total_tx_packets = int(snn_tx_spike or 0) + int(snn_tx_key or 0) + int(snn_tx_tile or 0)
        total_tx_key_packets = int(snn_tx_key or 0) + int(snn_tx_tile or 0)
        add(
            "snn_tx.nonzero",
            "PASS" if total_tx_packets > 0 else "WARN",
            f"tx_packets={total_tx_packets} tx_spike={_fmt_num(snn_tx_spike)} tx_spikekey={_fmt_num(snn_tx_key)} tx_spiketilekey={_fmt_num(snn_tx_tile)}",
        )
        if snn_rx_key is not None or snn_rx_tile is not None:
            total_rx_key_packets = int(snn_rx_key or 0) + int(snn_rx_tile or 0)
            if total_tx_key_packets == 0 and total_rx_key_packets == 0:
                status = "PASS"
            elif total_tx_key_packets > 0 and total_rx_key_packets > 0:
                status = "PASS"
            else:
                status = "WARN"
            add(
                "snn_txrx.key_visibility",
                status,
                f"tx_key_packets={total_tx_key_packets} rx_key_packets={total_rx_key_packets}",
            )
            model_max_steps = _as_intish(_get_path(summary, "model.max_steps"))
            gas_steps_done = _as_intish(_get_path(summary, "gas.global_steps_done"))
            if gas_steps_done is None:
                gas_steps_done = _as_intish(_get_path(summary, "step.global_steps_done"))
            if total_tx_key_packets > 0 and total_rx_key_packets == 0:
                # Common in step-limited runs: key packets emitted in step N are tagged
                # with step_seq=N+1, so max_steps=1 cannot observe rx_key yet.
                likely_step_deferral = (
                    model_max_steps is not None and model_max_steps <= 1 and
                    gas_steps_done is not None and gas_steps_done <= 1
                )
                add(
                    "snn_txrx.key_visibility_step_deferral",
                    "WARN" if likely_step_deferral else "FAIL",
                    (
                        f"tx_key_packets={total_tx_key_packets} rx_key_packets={total_rx_key_packets} "
                        f"max_steps={_fmt_num(model_max_steps)} gas_steps_done={_fmt_num(gas_steps_done)}"
                    ),
                )
            elif total_tx_key_packets > total_rx_key_packets and total_rx_key_packets > 0:
                add(
                    "snn_txrx.key_visibility_step_deferral",
                    "PASS",
                    (
                        f"tx_key_packets={total_tx_key_packets} rx_key_packets={total_rx_key_packets} "
                        f"(tail-step deferral may retain tx_key > rx_key in step-limited runs)"
                    ),
                )
            else:
                add(
                    "snn_txrx.key_visibility_step_deferral",
                    "PASS",
                    f"tx_key_packets={total_tx_key_packets} rx_key_packets={total_rx_key_packets}",
                )
        else:
            add("snn_txrx.key_visibility", "SKIP", "missing snn_rx key counters")
            add("snn_txrx.key_visibility_step_deferral", "SKIP", "missing snn_rx key counters")
    else:
        add("snn_tx.nonzero", "SKIP", "missing snn_tx section")
        add("snn_txrx.key_visibility", "SKIP", "missing snn_tx section")
        add("snn_txrx.key_visibility_step_deferral", "SKIP", "missing snn_tx section")

    # Memory sanity (avoid silent 'no mem traffic' regressions)
    mem_reqs = _as_float(_get_path(summary, "memory.memory_requests"))
    mem_bytes = _as_float(_get_path(summary, "memory.memory_bytes"))
    if workload_impl == "traffic":
        add("memory.nonzero", "SKIP", f"workload_impl={workload_impl!r} (comm-only workload)")
    elif mem_reqs is not None and mem_bytes is not None:
        if mem_reqs <= 0 or mem_bytes <= 0:
            add("memory.nonzero", "FAIL", f"memory_requests={_fmt_num(mem_reqs)} memory_bytes={_fmt_num(mem_bytes)}")
        else:
            add("memory.nonzero", "PASS", f"memory_requests={_fmt_num(mem_reqs)} memory_bytes={_fmt_num(mem_bytes)}")
    else:
        add("memory.nonzero", "SKIP", "missing memory.memory_requests/memory.memory_bytes")

    # MemHierarchy traffic invariants (paper-grade "off-chip" traffic metrics).
    # NOTE: This is intentionally best-effort in dev profile; paper profile will
    # tighten these checks via the required-set below.
    mh = summary.get("memhierarchy") if isinstance(summary, dict) else None
    if isinstance(mh, dict):
        line_size = _as_intish(mh.get("line_size_bytes")) or 0
        add(
            "memhierarchy.line_size_bytes_nonzero",
            "PASS" if line_size > 0 else "FAIL",
            f"line_size_bytes={line_size}",
        )

        def _sum_reqs(sec: Dict[str, Any]) -> Optional[float]:
            keys = ("req_GetS", "req_GetX", "req_GetSX", "req_Write", "req_PutM")
            vals: List[float] = []
            for k in keys:
                v = _as_float(sec.get(k))
                if v is not None:
                    vals.append(float(v))
            if not vals:
                return None
            return float(sum(vals))

        for comp in ("memctrl", "l1"):
            sec = mh.get(comp)
            if not isinstance(sec, dict):
                add(f"memhierarchy.{comp}.bytes_est_total_formula", "SKIP", f"missing memhierarchy.{comp} section")
                add(f"memhierarchy.{comp}.req_total_matches_sum", "SKIP", f"missing memhierarchy.{comp} section")
                continue

            req_total = _as_float(sec.get("req_total"))
            req_sum = _sum_reqs(sec)
            if req_total is None or req_sum is None:
                add(
                    f"memhierarchy.{comp}.req_total_matches_sum",
                    "SKIP",
                    f"missing req_total/sum (req_total={_fmt_num(req_total)} sum={_fmt_num(req_sum)})",
                )
            else:
                add(
                    f"memhierarchy.{comp}.req_total_matches_sum",
                    "PASS" if _close(req_total, req_sum, abs_tol=1.0, rel_tol=0.0) else "FAIL",
                    f"req_total={_fmt_num(req_total)} sum(req_*)={_fmt_num(req_sum)}",
                )

            bytes_est = _as_float(sec.get("bytes_est_total"))
            if bytes_est is None or line_size <= 0:
                add(
                    f"memhierarchy.{comp}.bytes_est_total_formula",
                    "SKIP",
                    f"missing bytes_est_total or invalid line_size (bytes_est_total={_fmt_num(bytes_est)} line_size={line_size})",
                )
            else:
                base_reqs = req_total if req_total is not None else req_sum
                if base_reqs is None:
                    add(
                        f"memhierarchy.{comp}.bytes_est_total_formula",
                        "SKIP",
                        f"missing req_total/sum for bytes formula (bytes_est_total={_fmt_num(bytes_est)} line_size={line_size})",
                    )
                else:
                    exp_bytes = float(base_reqs) * float(line_size)
                    add(
                        f"memhierarchy.{comp}.bytes_est_total_formula",
                        "PASS" if _close(bytes_est, exp_bytes, abs_tol=1.0, rel_tol=0.0) else "FAIL",
                        f"bytes_est_total={_fmt_num(bytes_est)} expected={_fmt_num(exp_bytes)} (line_size={line_size} reqs={_fmt_num(base_reqs)})",
                    )

            # Optional sanity: adjusted GetS estimate (minus loader) should be within [0, GetS].
            gets = _as_float(sec.get("req_GetS"))
            gets_minus = _as_float(sec.get("req_GetS_minus_loader_est"))
            if gets is not None and gets_minus is not None:
                ok = (0.0 <= float(gets_minus) <= float(gets))
                add(
                    f"memhierarchy.{comp}.req_GetS_minus_loader_bounds",
                    "PASS" if ok else "WARN",
                    f"req_GetS_minus_loader_est={_fmt_num(gets_minus)} req_GetS={_fmt_num(gets)}",
                )
            else:
                add(
                    f"memhierarchy.{comp}.req_GetS_minus_loader_bounds",
                    "SKIP",
                    "missing req_GetS and/or req_GetS_minus_loader_est",
                )
    else:
        add("memhierarchy.line_size_bytes_nonzero", "SKIP", "missing memhierarchy section")
        add("memhierarchy.memctrl.req_total_matches_sum", "SKIP", "missing memhierarchy section")
        add("memhierarchy.memctrl.bytes_est_total_formula", "SKIP", "missing memhierarchy section")
        add("memhierarchy.l1.req_total_matches_sum", "SKIP", "missing memhierarchy section")
        add("memhierarchy.l1.bytes_est_total_formula", "SKIP", "missing memhierarchy section")
        add("memhierarchy.memctrl.req_GetS_minus_loader_bounds", "SKIP", "missing memhierarchy section")
        add("memhierarchy.l1.req_GetS_minus_loader_bounds", "SKIP", "missing memhierarchy section")

    # Granularity sanity (dense microbench): enforce cacheline default semantics.
    # This prevents accidentally mixing row-streaming/DMA-style runs into cacheline traffic conclusions.
    model_kind = str(_get_path(summary, "model.kind") or "").strip()
    if model_kind.startswith("dense_microbench") and exec_mode == "gas":
        # Dense microbench defaults to strict cacheline mode; some experiments intentionally disable it
        # (e.g., to validate row-window/gap-merge correctness under over-fetch). In that case we should
        # not fail the run solely because avg_granule_bytes > cacheline.
        dense_strict_infer = _infer_dense_strict_cacheline(summary=summary, effective_cfg=effective_cfg)
        dense_strict = True if dense_strict_infer is None else bool(dense_strict_infer)

        g = _effective_granularity(summary, effective_cfg)
        line = _as_intish(_get_path(summary, "memhierarchy.line_size_bytes")) or 0
        avg = _as_float(_get_path(summary, "gas.avg_granule_bytes"))
        if g == "cacheline":
            if not dense_strict:
                add(
                    "granularity.dense.cacheline_avg_granule",
                    "PASS",
                    f"granularity={g} strict_cacheline=0 avg_granule_bytes={_fmt_num(avg)} (allowed to exceed line; strict inferred={_fmt_num(dense_strict_infer)})",
                )
            else:
                # If avg_granule_bytes is present, require it to be close to cacheline.
                if line > 0 and avg is not None and avg > 0:
                    # allow up to 2x to tolerate small variations; anything KB-level is definitely a regression.
                    add(
                        "granularity.dense.cacheline_avg_granule",
                        "PASS" if avg <= float(line) * 2.0 else "FAIL",
                        f"granularity={g} line={line} avg_granule_bytes={_fmt_num(avg)}",
                    )
                else:
                    add(
                        "granularity.dense.cacheline_avg_granule",
                        "WARN",
                        f"granularity={g} missing gas.avg_granule_bytes (consider enabling gas_unique_reads_total)",
                    )
        elif g == "row":
            add(
                "granularity.dense.cacheline_avg_granule",
                "FAIL",
                f"detected row-granularity run in dense_microbench (granularity={g}); do not mix with cacheline results",
            )
        else:
            add(
                "granularity.dense.cacheline_avg_granule",
                "WARN",
                f"granularity={g} (unknown); need effective_config.json and/or gas.avg_granule_bytes to disambiguate",
            )

    # Informational: infer whether we're in global step sync mode
    add(
        "info.infer_global_step_sync",
        "PASS",
        f"infer_global_step_sync={1 if _infer_step_sync_mode(summary) else 0}",
    )

    # GAS feature sanity (BCSR mesh): ensure fine/coarse merge knobs are enabled in 'gas' mode.
    #
    # Rationale: This prevents accidentally reporting "GAS benefits" while actually running
    # with merge features disabled (e.g., cacheline-only per-request reads).
    bcsr_meta_path = _get_path(summary, "model.bcsr_meta_path")
    if not (isinstance(bcsr_meta_path, str) and bcsr_meta_path.strip()):
        bcsr_meta_path = meta_model.get("bcsr_meta_path")
    if exec_mode == "gas" and isinstance(bcsr_meta_path, str) and bcsr_meta_path.strip():
        eg = effective_cfg.get("gas") if isinstance(effective_cfg, dict) else None
        if isinstance(eg, dict):
            gk = _as_intish(eg.get("gap_merge_k_bytes_config"))
            lmax = _as_intish(eg.get("burst_bytes_max_config"))
            rwb = _as_intish(eg.get("row_window_bytes"))
            rwt = _as_intish(eg.get("row_window_timeout_ns"))
            ok_gap = (gk is not None and gk > 0) and (lmax is not None and lmax > 0)
            ok_row = (rwb is not None and rwb > 0) or (rwt is not None and rwt > 0)
            enabled = ok_gap or ok_row
            add(
                "gas.features.merge_enabled_bcsr",
                "PASS" if enabled else "WARN",
                f"gap_k={gk} lmax={lmax} row_window_bytes={rwb} row_window_timeout_ns={rwt}",
            )
        else:
            add(
                "gas.features.merge_enabled_bcsr",
                "WARN",
                "missing effective_config.json gas section (cannot validate merge knobs)",
            )

    return checks


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-dir", required=True, help="run dir containing essential_summary_mesh.json")
    ap.add_argument("--baseline", default="", help="optional baseline run dir for tolerant compare")
    ap.add_argument("--abs-tol", type=float, default=1.0, help="absolute tolerance for formula/compare checks (default: 1)")
    ap.add_argument("--rel-tol", type=float, default=0.01, help="relative tolerance for formula/compare checks (default: 1%%)")
    ap.add_argument("--strict", action="store_true", help="treat WARN as FAIL (exit non-zero)")
    ap.add_argument("--profile", choices=["dev", "paper"], default="dev", help="validation profile (default: dev)")
    ap.add_argument("--max-route-miss-abs", type=int, default=0, help="paper: allowed absolute route misses (default: 0)")
    ap.add_argument("--max-route-miss-frac", type=float, default=0.0, help="paper: allowed route miss fraction of attempts (default: 0.0)")
    ap.add_argument("--max-local-drop-abs", type=int, default=1, help="paper: allowed absolute local drops (default: 1)")
    ap.add_argument("--max-local-drop-frac", type=float, default=1e-6, help="paper: allowed local drop fraction of attempts (default: 1e-6)")
    args = ap.parse_args()

    run_dir = Path(args.run_dir).resolve()
    path = run_dir / "essential_summary_mesh.json"
    if not path.exists():
        print(f"[val] FAIL missing file: {path}")
        return 1
    try:
        summary = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[val] FAIL invalid json: {path}: {e}")
        return 1

    # Load meta.json (optional in dev; required in paper).
    meta_path = _resolve_ref_path(run_dir=run_dir, summary=summary, ref_key="meta", default_name="meta.json")
    meta_raw = _load_json_dict(meta_path)

    # Load effective_config.json (optional; used for merge/granularity sanity).
    eff_path = _resolve_ref_path(run_dir=run_dir, summary=summary, ref_key="effective_config", default_name="effective_config.json")
    effective_cfg = _load_json_dict(eff_path)

    # Load local_run_config.json (optional in dev; required in paper) for config-vs-summary checks.
    local_run_cfg: Optional[Dict[str, Any]] = None
    cfg_path: Optional[Path] = None
    refs = summary.get("refs") if isinstance(summary, dict) else None
    if isinstance(refs, dict):
        p = refs.get("inputs_local_run_config")
        if isinstance(p, str) and p.strip():
            cand = (run_dir / p).resolve()
            if cand.exists():
                cfg_path = cand
    if cfg_path is None:
        cfg_path = _find_local_run_config_path(run_dir=run_dir, meta_raw=meta_raw if isinstance(meta_raw, dict) else None)
    if cfg_path is not None:
        try:
            local_run_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            local_run_cfg = None

    checks = validate_summary(
        run_dir=run_dir,
        summary=summary,
        meta_raw=meta_raw if isinstance(meta_raw, dict) else None,
        effective_cfg=effective_cfg if isinstance(effective_cfg, dict) else None,
        local_run_cfg=local_run_cfg if isinstance(local_run_cfg, dict) else None,
        profile=str(args.profile),
        abs_tol=float(args.abs_tol),
        rel_tol=float(args.rel_tol),
        max_route_miss_abs=int(args.max_route_miss_abs),
        max_route_miss_frac=float(args.max_route_miss_frac),
        max_local_drop_abs=int(args.max_local_drop_abs),
        max_local_drop_frac=float(args.max_local_drop_frac),
    )

    # Paper: tighten a few existing checks without rewriting the whole validator.
    if str(args.profile) == "paper":
        tightened: List[Check] = []
        meta_model = _extract_meta_model(meta_raw or {})
        exec_mode = str(_get_path(summary, "model.exec_mode") or meta_model.get("exec_mode") or "").strip().lower()
        required = {
            "model.num_pes",
            "model.neurons_total",
            "model.neurons_per_pe_formula",
            "model.exec_mode_infer",
            "gas.windows_accounting",
            "step_activation.firing_total_eq_pre_selected",
            "step_activation.spike_attempts_arith",
            "step_activation.attempts_eq_hits_miss_drops",
            "memhierarchy.line_size_bytes_nonzero",
            "memhierarchy.memctrl.req_total_matches_sum",
            "memhierarchy.memctrl.bytes_est_total_formula",
            "gas.gsops_step_formula",
        }
        # L1 checks are only required when L1 is enabled in the model config.
        l1_en = _get_path(summary, "model.l1_enable")
        if l1_en is None:
            l1_en = meta_model.get("l1_enable")
        l1_enabled = bool(int(l1_en or 0))
        if l1_enabled:
            required.add("memhierarchy.l1.req_total_matches_sum")
            required.add("memhierarchy.l1.bytes_est_total_formula")
        # GAS-only invariants: naive_raw is a non-window baseline (gas.windows==0), so these
        # checks must remain optional to support "paper-grade" exec_mode comparisons.
        workload_impl = str(
            _get_path(summary, "model.workload_impl") or meta_model.get("workload_impl") or ""
        ).strip().lower() or "snn"
        if exec_mode == "gas" and workload_impl == "snn":
            required.add("step_activation.invocations_vs_windows")
            required.add("gas.global_steps_done_vs_windows_done")

        warn_to_fail = {
            "model.exec_mode_infer",
        }
        if exec_mode == "gas":
            warn_to_fail.add("gas.global_steps_done_vs_windows_done")
        for c in checks:
            status = c.status
            detail = c.detail
            if c.name in required and status == "SKIP":
                status = "FAIL"
                detail = f"required in paper profile; {detail}"
            if c.name in warn_to_fail and status == "WARN":
                status = "FAIL"
                detail = f"paper requires strict; {detail}"
            tightened.append(Check(name=c.name, status=status, detail=detail))
        checks = tightened

    baseline_checks: List[Check] = []
    baseline_ok = True
    if args.baseline:
        base_dir = Path(args.baseline).resolve()
        base_path = base_dir / "essential_summary_mesh.json"
        if not base_path.exists():
            baseline_checks.append(Check(name="baseline:file", status="FAIL", detail=f"missing baseline summary: {base_path}"))
            baseline_ok = False
        else:
            try:
                base = json.loads(base_path.read_text(encoding="utf-8"))
                baseline_ok, baseline_checks = _compare_against_baseline(
                    base=base, cur=summary, abs_tol=float(args.abs_tol), rel_tol=float(args.rel_tol)
                )
            except Exception as e:
                baseline_checks.append(Check(name="baseline:json", status="FAIL", detail=f"baseline json load failed: {e}"))
                baseline_ok = False

    # Print report
    fail = 0
    warn = 0
    for c in checks + baseline_checks:
        print(f"[val] {c.status} {c.name}: {c.detail}")
        if c.status == "FAIL":
            fail += 1
        elif c.status == "WARN":
            warn += 1

    status = 0
    if fail > 0:
        status = 1
    elif args.strict and warn > 0:
        status = 1
    elif args.baseline and not baseline_ok:
        status = 1

    print(f"[val] SUMMARY run_dir={run_dir} fail={fail} warn={warn} strict={1 if args.strict else 0}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
