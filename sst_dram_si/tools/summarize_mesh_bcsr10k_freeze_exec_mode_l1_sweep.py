#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Summarize a 10k/PE + BCSR mesh exec_mode/L1/fraction sweep directory.

Expected layout (created by run_mesh_bcsr10k_freeze_exec_mode_l1_sweep_with_time.sh):
  outputs_large/paper2/<group>/<mode>/l1_<0|1>/frac_<tag>/<timestamp>/
    essential_summary_mesh.json
    meta.json
    effective_config.json
    validation.log

Usage:
  python3 tools/summarize_mesh_bcsr10k_freeze_exec_mode_l1_sweep.py --root <group-root>

Output:
  <root>/matrix_summary.tsv
  <root>/matrix_ratios.tsv
  <root>/inconclusive_runs.tsv (optional)
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


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


def _as_int(v: Any) -> Optional[int]:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float) and math.isfinite(v):
        return int(v)
    return None


def _parse_wall_to_seconds(wall: str) -> Optional[float]:
    # time -v uses H:MM:SS or M:SS
    s = str(wall or "").strip()
    if not s:
        return None
    parts = s.split(":")
    try:
        if len(parts) == 2:
            m, sec = int(parts[0]), int(parts[1])
            return float(m * 60 + sec)
        if len(parts) == 3:
            h, m, sec = int(parts[0]), int(parts[1]), int(parts[2])
            return float(h * 3600 + m * 60 + sec)
    except Exception:
        return None
    return None


def _mean_opt(vals: List[Optional[float]]) -> Optional[float]:
    xs = [float(v) for v in vals if isinstance(v, (int, float)) and math.isfinite(float(v))]
    if not xs:
        return None
    return float(sum(xs) / len(xs))


def _fmt_opt(v: Optional[float], *, digits: int = 0) -> str:
    if v is None or not math.isfinite(float(v)):
        return "NA"
    if digits <= 0:
        return f"{float(v):.0f}"
    return f"{float(v):.{digits}f}"


def _ratio_opt(num: Optional[float], den: Optional[float]) -> Optional[float]:
    if num is None or den is None:
        return None
    if not math.isfinite(float(num)) or not math.isfinite(float(den)):
        return None
    if float(num) <= 0.0 or float(den) <= 0.0:
        return None
    return float(num) / float(den)


@dataclass(frozen=True)
class RunRow:
    run_dir: str
    verdict: str
    verdict_reasons: str
    mode: str
    l1: int
    fraction: float
    seed: int
    fanout: int
    max_steps: int
    step_reset_mem_each_step: int
    line_size_bytes: int

    attempts: Optional[float]
    injected: Optional[float]
    route_miss: Optional[float]
    local_drop: Optional[float]

    memctrl_bytes: Optional[float]
    memctrl_gets: Optional[float]
    memctrl_gets_minus_loader: Optional[float]
    l1_bytes: Optional[float]

    gas_payload_bytes: Optional[float]
    gas_unique_bytes: Optional[float]
    gas_overfetch_bytes: Optional[float]
    gas_payload_reuse_bytes: Optional[float]

    sim_ns: Optional[int]
    wall_s: Optional[float]


def _iter_run_dirs(root: Path) -> Iterable[Path]:
    for p in root.rglob("essential_summary_mesh.json"):
        yield p.parent


def _extract_meta_model(meta_raw: Any) -> Dict[str, Any]:
    if isinstance(meta_raw, dict) and isinstance(meta_raw.get("model"), dict):
        return dict(meta_raw.get("model") or {})
    if isinstance(meta_raw, dict):
        return dict(meta_raw)
    return {}


def _load_run(run_dir: Path) -> Optional[RunRow]:
    try:
        summary = json.loads((run_dir / "essential_summary_mesh.json").read_text(encoding="utf-8"))
    except Exception:
        return None

    refs = summary.get("refs") if isinstance(summary, dict) else None
    meta_path = run_dir / "meta.json"
    if isinstance(refs, dict):
        mp = refs.get("meta")
        if isinstance(mp, str) and mp.strip():
            meta_path = (run_dir / mp).resolve()
    meta_raw: Dict[str, Any] = {}
    if meta_path.exists():
        try:
            meta_raw = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            meta_raw = {}
    meta_model = _extract_meta_model(meta_raw)

    eff_path = run_dir / "effective_config.json"
    if isinstance(refs, dict):
        ep = refs.get("effective_config")
        if isinstance(ep, str) and ep.strip():
            eff_path = (run_dir / ep).resolve()
    effective_cfg: Dict[str, Any] = {}
    if eff_path.exists():
        try:
            ec = json.loads(eff_path.read_text(encoding="utf-8"))
            effective_cfg = ec if isinstance(ec, dict) else {}
        except Exception:
            effective_cfg = {}

    exp = summary.get("experiment") if isinstance(summary, dict) else None
    verdict = "PASS"
    verdict_reasons = ""
    if isinstance(exp, dict):
        verdict = str(exp.get("verdict", "PASS") or "PASS").strip().upper() or "PASS"
        rr = exp.get("reasons")
        if isinstance(rr, list):
            verdict_reasons = ",".join(str(x) for x in rr if str(x).strip())
        elif isinstance(rr, str):
            verdict_reasons = rr.strip()

    # Paper-grade summaries should be filtered by the *current* validator, not only by the embedded experiment verdict.
    # Rationale: experiment.verdict is a best-effort tag and may lag behind validation rules (e.g., new invariants).
    validator = (Path(__file__).resolve().parent / "validate_essential_summary_mesh.py").resolve()
    if validator.exists():
        proc = subprocess.run(
            [sys.executable, str(validator), "--run-dir", str(run_dir), "--profile", "paper"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if proc.returncode != 0:
            verdict = "FAIL"
            fails: List[str] = []
            for line in (proc.stdout or "").splitlines():
                s = line.strip()
                if s.startswith("[val] FAIL "):
                    name = s[len("[val] FAIL ") :].split(":", 1)[0].strip()
                    if name:
                        fails.append(name)
            # Keep reasons short to avoid TSV bloat.
            verdict_reasons = ",".join(fails[:6]) if fails else "validator_fail"
        else:
            verdict = "PASS"
            verdict_reasons = ""

    mode = str(_get_path(summary, "model.exec_mode") or meta_model.get("exec_mode") or effective_cfg.get("exec_mode") or "").strip().lower() or "unknown"
    l1 = _as_int(_get_path(summary, "model.l1_enable"))
    if l1 is None:
        l1 = _as_int(meta_model.get("l1_enable"))
    l1 = int(l1 or 0)

    frac = _as_float(_get_path(summary, "model.step_activation_fraction"))
    if frac is None:
        frac = _as_float(meta_model.get("step_activation_fraction"))
    frac = float(frac or 0.0)

    seed = _as_int(_get_path(summary, "model.step_activation_seed"))
    if seed is None:
        seed = _as_int(meta_model.get("step_activation_seed"))
    seed = int(seed or 0)
    fanout = _as_int(_get_path(summary, "model.step_activation_fanout"))
    if fanout is None:
        fanout = _as_int(meta_model.get("step_activation_fanout"))
    fanout = int(fanout or 0)
    max_steps = _as_int(_get_path(summary, "model.max_steps"))
    if max_steps is None:
        max_steps = _as_int(meta_model.get("max_steps"))
    max_steps = int(max_steps or 0)

    step_reset = _as_int(_get_path(summary, "model.step_reset_mem_each_step"))
    if step_reset is None:
        step_reset = _as_int(meta_model.get("step_reset_mem_each_step"))
    step_reset = int(step_reset or 0)

    line_size = _as_int(_get_path(summary, "memhierarchy.line_size_bytes"))
    line_size = int(line_size or 0)

    attempts = _as_float(_get_path(summary, "step_activation.spike_attempts_total"))
    injected = _as_float(_get_path(summary, "step_activation.spikes_injected_total"))
    route_miss = _as_float(_get_path(summary, "step_activation.route_misses_total"))
    local_drop = _as_float(_get_path(summary, "step_activation.local_drops_total"))

    memctrl_bytes = _as_float(_get_path(summary, "memhierarchy.memctrl.bytes_est_total"))
    memctrl_gets = _as_float(_get_path(summary, "memhierarchy.memctrl.req_GetS"))
    memctrl_gets_minus_loader = _as_float(_get_path(summary, "memhierarchy.memctrl.req_GetS_minus_loader_est"))
    l1_bytes = _as_float(_get_path(summary, "memhierarchy.l1.bytes_est_total"))

    gas_payload_bytes = _as_float(_get_path(summary, "gas.payload_bytes_total"))
    gas_unique_bytes = _as_float(_get_path(summary, "gas.unique_bytes_total"))
    gas_overfetch_bytes = _as_float(_get_path(summary, "gas.overfetch_bytes_total"))
    gas_payload_reuse_bytes = _as_float(_get_path(summary, "gas.payload_reuse_bytes_total"))

    sim_ns = _as_int(_get_path(summary, "model.sim_time_actual_ns"))
    wall = _get_path(summary, "wallclock.wall")
    wall_s = _parse_wall_to_seconds(str(wall or ""))

    return RunRow(
        run_dir=str(run_dir),
        verdict=str(verdict),
        verdict_reasons=str(verdict_reasons),
        mode=mode,
        l1=int(l1),
        fraction=float(frac),
        seed=int(seed),
        fanout=int(fanout),
        max_steps=int(max_steps),
        step_reset_mem_each_step=int(step_reset),
        line_size_bytes=int(line_size),
        attempts=float(attempts) if attempts is not None else None,
        injected=float(injected) if injected is not None else None,
        route_miss=float(route_miss) if route_miss is not None else None,
        local_drop=float(local_drop) if local_drop is not None else None,
        memctrl_bytes=float(memctrl_bytes) if memctrl_bytes is not None else None,
        memctrl_gets=float(memctrl_gets) if memctrl_gets is not None else None,
        memctrl_gets_minus_loader=float(memctrl_gets_minus_loader) if memctrl_gets_minus_loader is not None else None,
        l1_bytes=float(l1_bytes) if l1_bytes is not None else None,
        gas_payload_bytes=float(gas_payload_bytes) if gas_payload_bytes is not None else None,
        gas_unique_bytes=float(gas_unique_bytes) if gas_unique_bytes is not None else None,
        gas_overfetch_bytes=float(gas_overfetch_bytes) if gas_overfetch_bytes is not None else None,
        gas_payload_reuse_bytes=float(gas_payload_reuse_bytes) if gas_payload_reuse_bytes is not None else None,
        sim_ns=int(sim_ns) if sim_ns is not None else None,
        wall_s=float(wall_s) if wall_s is not None else None,
    )


def _cfg_key(r: RunRow) -> Tuple[int, float, int, int, int, int]:
    # Keep seed/fanout/max_steps/step_reset in the key so ratios never mix
    # different RNG streams or step semantics.
    return (r.l1, r.fraction, r.seed, r.fanout, r.max_steps, r.step_reset_mem_each_step)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, help="group root directory under outputs_large/paper2/<group>/")
    ap.add_argument(
        "--take-last",
        type=int,
        default=0,
        help=(
            "if >0, keep only the last N runs per (mode,l1,fraction,seed) "
            "based on run_dir name ordering; useful when manual retries exist"
        ),
    )
    args = ap.parse_args()

    root = Path(args.root).resolve()
    if not root.exists():
        raise SystemExit(f"root not found: {root}")

    rows_all: List[RunRow] = []
    inconclusive_all: List[RunRow] = []
    for run_dir in sorted(_iter_run_dirs(root)):
        rr = _load_run(run_dir)
        if rr is not None:
            # Only filter when a verdict exists and is non-PASS.
            # Old runs without experiment section should remain analyzable.
            if rr.verdict and rr.verdict != "PASS":
                inconclusive_all.append(rr)
            else:
                rows_all.append(rr)

    if not rows_all:
        if inconclusive_all:
            out_inc = root / "inconclusive_runs.tsv"
            with out_inc.open("w", encoding="utf-8") as f:
                f.write("\t".join(["verdict", "reasons", "mode", "l1", "fraction", "seed", "fanout", "max_steps", "run_dir"]) + "\n")
                for r in sorted(inconclusive_all, key=lambda x: x.run_dir):
                    f.write(
                        "\t".join(
                            [
                                r.verdict,
                                r.verdict_reasons,
                                r.mode,
                                str(r.l1),
                                f"{r.fraction:.12g}",
                                str(r.seed),
                                str(r.fanout),
                                str(r.max_steps),
                                r.run_dir,
                            ]
                        )
                        + "\n"
                    )
            print(f"[summary] no PASS runs; wrote inconclusive list: {out_inc}")
        else:
            print(f"[summary] no runs found under: {root}")
        return 2

    rows = rows_all
    take_last = int(args.take_last or 0)
    if take_last > 0:
        by_cfg: Dict[Tuple[str, Tuple[int, float, int, int, int, int]], List[RunRow]] = {}
        for r in rows_all:
            by_cfg.setdefault((r.mode, _cfg_key(r)), []).append(r)
        rows = []
        for rs in by_cfg.values():
            # run_dir embeds timestamp as the final path component; lexicographic
            # sort is sufficient and avoids parsing.
            rs_sorted = sorted(rs, key=lambda x: x.run_dir)
            rows.extend(rs_sorted[-take_last:])
        rows = sorted(rows, key=lambda x: (x.mode, *_cfg_key(x), x.run_dir))

    # Per-run dump
    out_tsv = root / "matrix_summary.tsv"
    hdr = [
        "verdict",
        "verdict_reasons",
        "mode",
        "l1",
        "fraction",
        "seed",
        "fanout",
        "max_steps",
        "step_reset_mem_each_step",
        "line_size_bytes",
        "attempts",
        "injected",
        "route_miss",
        "local_drop",
        "memctrl_bytes",
        "memctrl_gets",
        "memctrl_gets_minus_loader",
        "l1_bytes",
        "memctrl_bytes_per_attempt",
        "memctrl_gets_per_attempt",
        "gas_payload_bytes",
        "gas_unique_bytes",
        "gas_overfetch_bytes",
        "gas_payload_reuse_bytes",
        "gas_overfetch_over_unique",
        "gas_payload_over_unique",
        "gas_reuse_over_payload",
        "sim_ns",
        "wall_s",
        "run_dir",
    ]
    with out_tsv.open("w", encoding="utf-8") as f:
        f.write("\t".join(hdr) + "\n")
        for r in rows:
            bytes_per_attempt = _ratio_opt(r.memctrl_bytes, r.attempts)
            gets_per_attempt = _ratio_opt(r.memctrl_gets, r.attempts)
            overfetch_over_unique = _ratio_opt(r.gas_overfetch_bytes, r.gas_unique_bytes)
            payload_over_unique = _ratio_opt(r.gas_payload_bytes, r.gas_unique_bytes)
            reuse_over_payload = _ratio_opt(r.gas_payload_reuse_bytes, r.gas_payload_bytes)
            f.write(
                "\t".join(
                    [
                        r.verdict,
                        r.verdict_reasons,
                        r.mode,
                        str(r.l1),
                        f"{r.fraction:.12g}",
                        str(r.seed),
                        str(r.fanout),
                        str(r.max_steps),
                        str(r.step_reset_mem_each_step),
                        str(r.line_size_bytes),
                        _fmt_opt(r.attempts, digits=0),
                        _fmt_opt(r.injected, digits=0),
                        _fmt_opt(r.route_miss, digits=0),
                        _fmt_opt(r.local_drop, digits=0),
                        _fmt_opt(r.memctrl_bytes, digits=0),
                        _fmt_opt(r.memctrl_gets, digits=0),
                        _fmt_opt(r.memctrl_gets_minus_loader, digits=0),
                        _fmt_opt(r.l1_bytes, digits=0),
                        _fmt_opt(bytes_per_attempt, digits=6),
                        _fmt_opt(gets_per_attempt, digits=6),
                        _fmt_opt(r.gas_payload_bytes, digits=0),
                        _fmt_opt(r.gas_unique_bytes, digits=0),
                        _fmt_opt(r.gas_overfetch_bytes, digits=0),
                        _fmt_opt(r.gas_payload_reuse_bytes, digits=0),
                        _fmt_opt(overfetch_over_unique, digits=6),
                        _fmt_opt(payload_over_unique, digits=6),
                        _fmt_opt(reuse_over_payload, digits=6),
                        str(r.sim_ns) if r.sim_ns is not None else "NA",
                        _fmt_opt(r.wall_s, digits=0),
                        r.run_dir,
                    ]
                )
                + "\n"
            )

    # Cell aggregates + naive/gas ratios (by full cfg key: l1,frac,seed,fanout,max_steps,step_reset)
    cells: Dict[Tuple[int, float, int, int, int, int], Dict[str, List[RunRow]]] = {}
    for r in rows:
        cells.setdefault(_cfg_key(r), {}).setdefault(r.mode, []).append(r)

    out_ratio = root / "matrix_ratios.tsv"
    with out_ratio.open("w", encoding="utf-8") as f:
        f.write(
            "\t".join(
                [
                    "l1",
                    "fraction",
                    "seed",
                    "fanout",
                    "max_steps",
                    "step_reset_mem_each_step",
                    "gas_runs",
                    "naive_runs",
                    "gas_memctrl_bytes_avg",
                    "naive_memctrl_bytes_avg",
                    "naive_over_gas_memctrl_bytes",
                    "gas_memctrl_gets_avg",
                    "naive_memctrl_gets_avg",
                    "naive_over_gas_memctrl_gets",
                    "gas_sim_ns_avg",
                    "naive_sim_ns_avg",
                    "naive_over_gas_sim_ns",
                    "gas_wall_s_avg",
                    "naive_wall_s_avg",
                    "naive_over_gas_wall_s",
                    "gas_injected_avg",
                    "naive_injected_avg",
                    "gas_unique_bytes_avg",
                    "gas_overfetch_over_unique_avg",
                    "gas_payload_over_unique_avg",
                    "gas_reuse_over_payload_avg",
                ]
            )
            + "\n"
        )

        for cfg_key, by_mode in sorted(cells.items(), key=lambda x: x[0]):
            l1, frac, seed, fanout, max_steps, step_reset = cfg_key
            gas_rs = by_mode.get("gas", [])
            naive_rs = by_mode.get("naive_raw", [])

            gas_mem = _mean_opt([x.memctrl_bytes for x in gas_rs])
            naive_mem = _mean_opt([x.memctrl_bytes for x in naive_rs])
            gas_gets = _mean_opt([x.memctrl_gets for x in gas_rs])
            naive_gets = _mean_opt([x.memctrl_gets for x in naive_rs])
            gas_sim = _mean_opt([float(x.sim_ns) if x.sim_ns is not None else None for x in gas_rs])
            naive_sim = _mean_opt([float(x.sim_ns) if x.sim_ns is not None else None for x in naive_rs])
            gas_wall = _mean_opt([x.wall_s for x in gas_rs])
            naive_wall = _mean_opt([x.wall_s for x in naive_rs])
            gas_inj = _mean_opt([x.injected for x in gas_rs])
            naive_inj = _mean_opt([x.injected for x in naive_rs])

            gas_unique = _mean_opt([x.gas_unique_bytes for x in gas_rs])
            gas_overfetch_ratio = _mean_opt([_ratio_opt(x.gas_overfetch_bytes, x.gas_unique_bytes) for x in gas_rs])
            gas_payload_ratio = _mean_opt([_ratio_opt(x.gas_payload_bytes, x.gas_unique_bytes) for x in gas_rs])
            gas_reuse_ratio = _mean_opt([_ratio_opt(x.gas_payload_reuse_bytes, x.gas_payload_bytes) for x in gas_rs])

            mem_ratio = _ratio_opt(naive_mem, gas_mem)
            gets_ratio = _ratio_opt(naive_gets, gas_gets)
            sim_ratio = _ratio_opt(naive_sim, gas_sim)
            wall_ratio = _ratio_opt(naive_wall, gas_wall)

            f.write(
                "\t".join(
                    [
                        str(l1),
                        f"{frac:.12g}",
                        str(int(seed)),
                        str(int(fanout)),
                        str(int(max_steps)),
                        str(int(step_reset)),
                        str(len(gas_rs)),
                        str(len(naive_rs)),
                        _fmt_opt(gas_mem, digits=0),
                        _fmt_opt(naive_mem, digits=0),
                        _fmt_opt(mem_ratio, digits=6),
                        _fmt_opt(gas_gets, digits=0),
                        _fmt_opt(naive_gets, digits=0),
                        _fmt_opt(gets_ratio, digits=6),
                        _fmt_opt(gas_sim, digits=3),
                        _fmt_opt(naive_sim, digits=3),
                        _fmt_opt(sim_ratio, digits=6),
                        _fmt_opt(gas_wall, digits=3),
                        _fmt_opt(naive_wall, digits=3),
                        _fmt_opt(wall_ratio, digits=6),
                        _fmt_opt(gas_inj, digits=0),
                        _fmt_opt(naive_inj, digits=0),
                        _fmt_opt(gas_unique, digits=0),
                        _fmt_opt(gas_overfetch_ratio, digits=6),
                        _fmt_opt(gas_payload_ratio, digits=6),
                        _fmt_opt(gas_reuse_ratio, digits=6),
                    ]
                )
                + "\n"
            )

    print(f"[summary] wrote: {out_tsv}")
    print(f"[summary] wrote: {out_ratio}")
    if inconclusive_all:
        out_inc = root / "inconclusive_runs.tsv"
        with out_inc.open("w", encoding="utf-8") as f:
            f.write("\t".join(["verdict", "reasons", "mode", "l1", "fraction", "seed", "fanout", "max_steps", "run_dir"]) + "\n")
            for r in sorted(inconclusive_all, key=lambda x: x.run_dir):
                f.write(
                    "\t".join(
                        [
                            r.verdict,
                            r.verdict_reasons,
                            r.mode,
                            str(r.l1),
                            f"{r.fraction:.12g}",
                            str(r.seed),
                            str(r.fanout),
                            str(r.max_steps),
                            r.run_dir,
                        ]
                    )
                    + "\n"
                )
        print(f"[summary] wrote: {out_inc}")
    print(f"[summary] runs={len(rows)} cells={len(cells)} root={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
