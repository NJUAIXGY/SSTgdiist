#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paper-grade correctness gate for the BCSR A/B/AB isolation matrix.

This tool:
1) Locates the latest run dir under each variant root
2) Prints a TSV summary row per variant
3) Applies a semantic gate:
   - Strict equality for structural counters (inj/proc/route/.../steps)
   - Tiered tolerance for neurons_fired_total (PASS/WARN/INCONCLUSIVE)
4) Writes verdict + reasons into target run summaries

Exit code is always 0 (this is a reporting/gating tool; experiments may continue).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def _latest_run(root: Path) -> Optional[Path]:
    if not root.exists():
        return None
    cands = [p for p in root.iterdir() if p.is_dir() and (p / "essential_summary_mesh.json").exists()]
    if not cands:
        return None
    return sorted(cands)[-1]


def _resolve_run(root: Path, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        cand = Path(explicit)
        if not cand.is_absolute():
            cand2 = root / explicit
            if cand2.exists():
                cand = cand2
        if cand.exists() and cand.is_dir() and (cand / "essential_summary_mesh.json").exists():
            return cand
        return None
    return _latest_run(root)


def _get_nested(d: Dict[str, Any], path: List[str]) -> Any:
    cur: Any = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return None
        cur = cur[p]
    return cur


def _as_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return int(s, 0)
        except Exception:
            try:
                return int(float(s))
            except Exception:
                return None
    return None


def _as_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return float(int(v))
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return float(s)
        except Exception:
            return None
    return None


def _basename_or_empty(p: str) -> str:
    try:
        return Path(p).name
    except Exception:
        return ""


_VERDICT_ORDER = {"PASS": 0, "WARN": 1, "INCONCLUSIVE": 2}


def _merge_verdict(old_v: Optional[str], new_v: str) -> str:
    old = str(old_v or "PASS").upper()
    new = str(new_v or "PASS").upper()
    if _VERDICT_ORDER.get(new, 0) >= _VERDICT_ORDER.get(old, 0):
        return new
    return old


def _mark_verdict(run_dir: Path, verdict: str, reason: str) -> None:
    summ = run_dir / "essential_summary_mesh.json"
    if not summ.exists():
        return
    j = _read_json(summ)
    exp = j.get("experiment")
    if not isinstance(exp, dict):
        exp = {}
        j["experiment"] = exp
    exp["profile"] = str(exp.get("profile") or "universal_core_eval")
    exp["verdict"] = _merge_verdict(exp.get("verdict"), verdict)
    rs = exp.get("reasons")
    if not isinstance(rs, list):
        rs = []
    if reason not in rs:
        rs.append(reason)
    exp["reasons"] = rs
    _write_json(summ, j)


def _mark_inconclusive(run_dir: Path, reason: str) -> None:
    _mark_verdict(run_dir, "INCONCLUSIVE", reason)


def _mark_warn(run_dir: Path, reason: str) -> None:
    _mark_verdict(run_dir, "WARN", reason)


def _extract_env(meta: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(meta, dict):
        return {}
    env = meta.get("environment")
    return env if isinstance(env, dict) else {}


def _extract_metrics(summary: Dict[str, Any]) -> Dict[str, Optional[int]]:
    step = summary.get("step") if isinstance(summary.get("step"), dict) else {}
    sa = summary.get("step_activation") if isinstance(summary.get("step_activation"), dict) else {}
    spike = summary.get("spike_activity") if isinstance(summary.get("spike_activity"), dict) else {}
    return {
        "global_steps_done": _as_int(step.get("global_steps_done")),
        "spikes_injected_total": _as_int(sa.get("spikes_injected_total")),
        "pre_selected_total": _as_int(sa.get("pre_selected_total")),
        "spike_attempts_total": _as_int(sa.get("spike_attempts_total")),
        "route_hits_total": _as_int(sa.get("route_hits_total")),
        "route_misses_total": _as_int(sa.get("route_misses_total")),
        "local_drops_total": _as_int(sa.get("local_drops_total")),
        "total_spikes_processed": _as_int(spike.get("total_spikes_processed")),
        "neurons_fired_total": _as_int(spike.get("neurons_fired_total")),
    }


def _get_perf_fields(summary: Dict[str, Any]) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    mem = summary.get("memory") if isinstance(summary.get("memory"), dict) else {}
    mem_bytes = _as_int(mem.get("memory_bytes"))
    memctrl_bytes = None
    mh = summary.get("memhierarchy") if isinstance(summary.get("memhierarchy"), dict) else {}
    memctrl = mh.get("memctrl") if isinstance(mh.get("memctrl"), dict) else {}
    memctrl_bytes = _as_int(memctrl.get("bytes_est_total"))
    model = summary.get("model") if isinstance(summary.get("model"), dict) else {}
    sim_ns = _as_int(model.get("sim_time_actual_ns"))
    return mem_bytes, memctrl_bytes, sim_ns


def _get_gas_fields(summary: Dict[str, Any]) -> Dict[str, Optional[float]]:
    gas = summary.get("gas") if isinstance(summary.get("gas"), dict) else {}
    return {
        "gap_abs": _as_float(gas.get("gap_absorbed_bytes_total")),
        "rowwin_trig": _as_float(gas.get("row_window_triggers_total")),
        "rowwin_bytes": _as_float(gas.get("row_window_bytes_total")),
        "overfetch": _as_float(gas.get("overfetch_bytes_total")),
        "uniq_lines": _as_float(gas.get("unique_line_count_total")),
        "cov_lines": _as_float(gas.get("covered_line_count_total")),
        "rr_turns": _as_float(gas.get("apply_bank_rr_turns_total")),
        "sticky_hits": _as_float(gas.get("apply_row_sticky_hits_total")),
        "age_forced": _as_float(gas.get("apply_age_forced_total")),
        "active_banks_peak_avg": _as_float(gas.get("apply_active_banks_peak_avg")),
    }


def _pct_delta(base: Optional[int], cur: Optional[int]) -> Optional[float]:
    if base is None or cur is None:
        return None
    if base == 0:
        return None
    return (float(cur) - float(base)) / float(base) * 100.0


def _gate_one_variant(label: str,
                      run_dir: Path,
                      cur: Dict[str, Optional[int]],
                      ref: Dict[str, Optional[int]],
                      fired_pass_rel_tol: float,
                      fired_warn_rel_tol: float) -> str:
    status = "PASS"

    strict_keys = (
        "global_steps_done",
        "spikes_injected_total",
        "pre_selected_total",
        "spike_attempts_total",
        "route_hits_total",
        "route_misses_total",
        "local_drops_total",
        "total_spikes_processed",
    )
    for k in strict_keys:
        a = cur.get(k)
        b = ref.get(k)
        if a is None or b is None or int(a) != int(b):
            _mark_inconclusive(run_dir, f"matrix_mismatch:{k}:{a}!={b}")
            status = "INCONCLUSIVE"

    # neurons_fired_total: tiered tolerance
    a = cur.get("neurons_fired_total")
    b = ref.get("neurons_fired_total")
    if a is None or b is None:
        _mark_inconclusive(run_dir, "matrix_mismatch:neurons_fired_total:missing")
        status = "INCONCLUSIVE"
    else:
        abs_diff = abs(int(a) - int(b))
        allow_pass = max(1, int(abs(int(b)) * fired_pass_rel_tol))
        allow_warn = max(allow_pass, int(abs(int(b)) * fired_warn_rel_tol))
        if abs_diff <= allow_pass:
            pass
        elif abs_diff <= allow_warn:
            _mark_warn(
                run_dir,
                f"matrix_warn:neurons_fired_total:{int(a)}!={int(b)} (abs_diff={abs_diff} allow_pass={allow_pass} allow_warn={allow_warn})",
            )
            if status != "INCONCLUSIVE":
                status = "WARN"
        else:
            _mark_inconclusive(
                run_dir,
                f"matrix_mismatch:neurons_fired_total:{int(a)}!={int(b)} (abs_diff={abs_diff} allow_pass={allow_pass} allow_warn={allow_warn})",
            )
            status = "INCONCLUSIVE"

    return status


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline-root", required=True, help="root dir for baseline runs")
    ap.add_argument("--a-root", required=True, help="root dir for A runs")
    ap.add_argument("--b-root", required=True, help="root dir for B runs")
    ap.add_argument("--ab-root", required=True, help="root dir for AB runs")
    ap.add_argument("--baseline-run", default=None, help="explicit run dir (or run_id under baseline-root)")
    ap.add_argument("--a-run", default=None, help="explicit run dir (or run_id under a-root)")
    ap.add_argument("--b-run", default=None, help="explicit run dir (or run_id under b-root)")
    ap.add_argument("--ab-run", default=None, help="explicit run dir (or run_id under ab-root)")
    ap.add_argument("--fired-rel-tol", type=float, default=0.001, help="legacy alias for --fired-pass-rel-tol")
    ap.add_argument("--fired-pass-rel-tol", type=float, default=None, help="PASS tolerance for neurons_fired_total (default: fired-rel-tol)")
    ap.add_argument("--fired-warn-rel-tol", type=float, default=0.01, help="WARN tolerance for neurons_fired_total (>= pass tol)")
    args = ap.parse_args()

    roots = {
        "baseline": Path(args.baseline_root),
        "A_row_cacheline": Path(args.a_root),
        "B_rowpack_v2": Path(args.b_root),
        "AB_rowpack_rowcacheline": Path(args.ab_root),
    }

    latest: Dict[str, Optional[Path]] = {
        "baseline": _resolve_run(roots["baseline"], args.baseline_run),
        "A_row_cacheline": _resolve_run(roots["A_row_cacheline"], args.a_run),
        "B_rowpack_v2": _resolve_run(roots["B_rowpack_v2"], args.b_run),
        "AB_rowpack_rowcacheline": _resolve_run(roots["AB_rowpack_rowcacheline"], args.ab_run),
    }

    # Load summaries/metas.
    summaries: Dict[str, Dict[str, Any]] = {}
    envs: Dict[str, Dict[str, Any]] = {}
    metrics: Dict[str, Dict[str, Optional[int]]] = {}
    perf: Dict[str, Tuple[Optional[int], Optional[int], Optional[int]]] = {}
    gas_fields: Dict[str, Dict[str, Optional[float]]] = {}
    verdicts: Dict[str, str] = {}

    for label, run in latest.items():
        if run is None:
            summaries[label] = {}
            envs[label] = {}
            metrics[label] = {}
            perf[label] = (None, None, None)
            gas_fields[label] = {}
            verdicts[label] = "NA"
            continue
        summ_path = run / "essential_summary_mesh.json"
        meta_path = run / "meta.json"
        try:
            s = _read_json(summ_path)
        except Exception:
            s = {}
        m = {}
        if meta_path.exists():
            try:
                m = _read_json(meta_path)
            except Exception:
                m = {}
        summaries[label] = s
        envs[label] = _extract_env(m)
        metrics[label] = _extract_metrics(s)
        perf[label] = _get_perf_fields(s)
        gas_fields[label] = _get_gas_fields(s)
        verdicts[label] = str(_get_nested(s, ["experiment", "verdict"]) or "")

    # Apply matrix gate.
    base_run = latest.get("baseline")
    if base_run is None:
        print("[ab-isolation] WARN: baseline missing; skip matrix gate")
        return 0

    base_metrics = metrics.get("baseline") or {}
    fired_pass_rel_tol = float(args.fired_pass_rel_tol if args.fired_pass_rel_tol is not None else args.fired_rel_tol)
    fired_warn_rel_tol = float(max(args.fired_warn_rel_tol, fired_pass_rel_tol))

    matrix_status = "PASS"
    per_variant_status: Dict[str, str] = {"baseline": "PASS"}
    for k in ("A_row_cacheline", "B_rowpack_v2", "AB_rowpack_rowcacheline"):
        run = latest.get(k)
        if run is None:
            per_variant_status[k] = "INCONCLUSIVE"
            matrix_status = "INCONCLUSIVE"
            continue
        cur = metrics.get(k) or {}
        st = _gate_one_variant(
            k,
            run,
            cur,
            base_metrics,
            fired_pass_rel_tol=fired_pass_rel_tol,
            fired_warn_rel_tol=fired_warn_rel_tol,
        )
        per_variant_status[k] = st
        if _VERDICT_ORDER[st] > _VERDICT_ORDER[matrix_status]:
            matrix_status = st

    # Print TSV summary (after gate for stable verdict columns).
    print("\n[ab-isolation] latest summary")
    header = [
        "variant",
        "run_id",
        "bcsr_dir",
        "fetch_mode",
        "memory_bytes",
        "memctrl_bytes",
        "sim_time_ns",
        "steps",
        "inj",
        "proc",
        "pre_sel",
        "attempts",
        "route_hit",
        "route_miss",
        "local_drop",
        "fired",
        "gap_abs",
        "rowwin_trig",
        "rr_turns",
        "sticky_hits",
        "age_forced",
        "active_banks_peak_avg",
        "verdict",
    ]
    print("\t".join(header))
    for label in ("baseline", "A_row_cacheline", "B_rowpack_v2", "AB_rowpack_rowcacheline"):
        run = latest.get(label)
        run_id = run.name if run is not None else "NA"
        env = envs.get(label) or {}
        bcsr_dir = _basename_or_empty(str(env.get("MESH_BCSR_DIR", "") or ""))
        fetch_mode = str(env.get("MESH_BCSR_BLOCK_FETCH_MODE", "") or "")
        mem_bytes, memctrl_bytes, sim_ns = perf.get(label) or (None, None, None)
        mm = metrics.get(label) or {}
        gg = gas_fields.get(label) or {}
        row = [
            label,
            run_id,
            bcsr_dir,
            fetch_mode,
            "" if mem_bytes is None else str(mem_bytes),
            "" if memctrl_bytes is None else str(memctrl_bytes),
            "" if sim_ns is None else str(sim_ns),
            "" if mm.get("global_steps_done") is None else str(mm.get("global_steps_done")),
            "" if mm.get("spikes_injected_total") is None else str(mm.get("spikes_injected_total")),
            "" if mm.get("total_spikes_processed") is None else str(mm.get("total_spikes_processed")),
            "" if mm.get("pre_selected_total") is None else str(mm.get("pre_selected_total")),
            "" if mm.get("spike_attempts_total") is None else str(mm.get("spike_attempts_total")),
            "" if mm.get("route_hits_total") is None else str(mm.get("route_hits_total")),
            "" if mm.get("route_misses_total") is None else str(mm.get("route_misses_total")),
            "" if mm.get("local_drops_total") is None else str(mm.get("local_drops_total")),
            "" if mm.get("neurons_fired_total") is None else str(mm.get("neurons_fired_total")),
            "" if gg.get("gap_abs") is None else str(int(gg.get("gap_abs") or 0)),
            "" if gg.get("rowwin_trig") is None else str(int(gg.get("rowwin_trig") or 0)),
            "" if gg.get("rr_turns") is None else str(int(gg.get("rr_turns") or 0)),
            "" if gg.get("sticky_hits") is None else str(int(gg.get("sticky_hits") or 0)),
            "" if gg.get("age_forced") is None else str(int(gg.get("age_forced") or 0)),
            "" if gg.get("active_banks_peak_avg") is None else f"{float(gg.get('active_banks_peak_avg') or 0.0):.3f}",
            per_variant_status.get(label) or verdicts.get(label) or "",
        ]
        print("\t".join(row))

    if matrix_status == "PASS":
        print(
            "[ab-isolation] matrix_gate: PASS "
            f"(strict: steps/inj/proc/route/*; fired_pass_rel_tol={fired_pass_rel_tol} fired_warn_rel_tol={fired_warn_rel_tol})"
        )
    elif matrix_status == "WARN":
        print(
            "[ab-isolation] matrix_gate: WARN "
            f"(strict keys pass; fired drift in WARN band: pass<={fired_pass_rel_tol}, warn<={fired_warn_rel_tol})"
        )
    else:
        print("[ab-isolation] matrix_gate: INCONCLUSIVE (see experiment.reasons=matrix_mismatch:* in summaries)")

    # Perf deltas vs baseline (paper table friendly).
    b_mem, b_memctrl, b_sim = perf.get("baseline") or (None, None, None)
    print("\n[ab-isolation] perf delta vs baseline (%)")
    print("variant\td_mem\td_memctrl\td_sim")
    best_variant = None
    best_score = None
    for k in ("A_row_cacheline", "B_rowpack_v2", "AB_rowpack_rowcacheline"):
        c_mem, c_memctrl, c_sim = perf.get(k) or (None, None, None)
        d_mem = _pct_delta(b_mem, c_mem)
        d_memctrl = _pct_delta(b_memctrl, c_memctrl)
        d_sim = _pct_delta(b_sim, c_sim)
        print(
            f"{k}\t"
            f"{'' if d_mem is None else f'{d_mem:+.3f}'}\t"
            f"{'' if d_memctrl is None else f'{d_memctrl:+.3f}'}\t"
            f"{'' if d_sim is None else f'{d_sim:+.3f}'}"
        )
        # Score: lower memctrl + lower sim is better (equal weight).
        if d_memctrl is not None and d_sim is not None:
            score = d_memctrl + d_sim
            if best_score is None or score < best_score:
                best_score = score
                best_variant = k
    if best_variant is not None:
        print(f"[ab-isolation] best_variant_by(memctrl+sim)={best_variant}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
