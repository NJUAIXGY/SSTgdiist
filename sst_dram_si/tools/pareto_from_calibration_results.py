#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compute a 2D Pareto front from calibration_results.tsv.

We treat these as minimization objectives:
  - sim_cycles: modeled time (SST cycles; in our mesh defaults, 1 cycle ~= 1ns)
  - memctrl_bytes: estimated off-chip traffic (memctrl_gets * line_size)

By default, this script prints the Pareto points as TSV to stdout.
Optionally, it can also write a pareto_points.tsv next to the input.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class Row:
    backend: str
    cfg: str
    gap_k: int
    lmax: int
    rowwin: int
    tmo: int
    run_dir: str
    verdict: str
    memctrl_bytes: float
    sim_cycles: float
    row_hit_rate: Optional[float] = None
    avg_read_lat: Optional[float] = None
    wall_s: Optional[float] = None


def _to_float(x: str) -> Optional[float]:
    try:
        if x is None:
            return None
        s = str(x).strip()
        if not s or s.upper() == "NA":
            return None
        return float(s)
    except Exception:
        return None


def _to_int(x: str) -> int:
    try:
        return int(float(str(x).strip()))
    except Exception:
        return 0


def _load_sim_cycles_from_run_dir(run_dir: Path) -> Optional[float]:
    p = run_dir / "essential_summary_mesh.json"
    if not p.exists():
        return None
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(s, dict):
        gas = s.get("gas")
        if isinstance(gas, dict):
            v = gas.get("cycle_cost")
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
        model = s.get("model")
        if isinstance(model, dict):
            v = model.get("sim_time_actual_ns")
            if isinstance(v, (int, float)) and v > 0:
                return float(v)
    return None


def _parse_rows(tsv_path: Path) -> List[Row]:
    raw = tsv_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not raw:
        return []
    header = raw[0].split("\t")
    col: Dict[str, int] = {name.strip(): i for i, name in enumerate(header)}

    def idx(name: str) -> Optional[int]:
        return col.get(name)

    out: List[Row] = []
    reader = csv.reader(raw[1:], delimiter="\t")
    for cols in reader:
        if not cols or len(cols) < 8:
            continue
        verdict = (cols[idx("verdict")] if idx("verdict") is not None and idx("verdict") < len(cols) else "").strip().upper()
        if verdict != "PASS":
            continue

        backend = cols[idx("backend")] if idx("backend") is not None else cols[0]
        cfg = cols[idx("cfg")] if idx("cfg") is not None else cols[1]
        gap_k = _to_int(cols[idx("gap_k")] if idx("gap_k") is not None else cols[2])
        lmax = _to_int(cols[idx("lmax")] if idx("lmax") is not None else cols[3])
        rowwin = _to_int(cols[idx("row_window_bytes")] if idx("row_window_bytes") is not None else cols[4])
        tmo = _to_int(cols[idx("row_window_timeout_ns")] if idx("row_window_timeout_ns") is not None else cols[5])
        run_dir = cols[idx("run_dir")] if idx("run_dir") is not None else cols[6]

        memctrl_bytes = _to_float(cols[idx("memctrl_bytes")] if idx("memctrl_bytes") is not None else cols[8])
        if memctrl_bytes is None:
            continue

        sim_cycles = None
        if idx("sim_cycles") is not None and idx("sim_cycles") < len(cols):
            sim_cycles = _to_float(cols[idx("sim_cycles")])
        if sim_cycles is None:
            sim_cycles = _load_sim_cycles_from_run_dir(Path(run_dir))
        if sim_cycles is None:
            continue

        row_hit_rate = _to_float(cols[idx("row_hit_rate")]) if idx("row_hit_rate") is not None and idx("row_hit_rate") < len(cols) else None
        avg_read_lat = _to_float(cols[idx("avg_read_lat")]) if idx("avg_read_lat") is not None and idx("avg_read_lat") < len(cols) else None
        wall_s = _to_float(cols[idx("wall_s")]) if idx("wall_s") is not None and idx("wall_s") < len(cols) else None

        out.append(
            Row(
                backend=str(backend),
                cfg=str(cfg),
                gap_k=gap_k,
                lmax=lmax,
                rowwin=rowwin,
                tmo=tmo,
                run_dir=str(run_dir),
                verdict="PASS",
                memctrl_bytes=float(memctrl_bytes),
                sim_cycles=float(sim_cycles),
                row_hit_rate=row_hit_rate,
                avg_read_lat=avg_read_lat,
                wall_s=wall_s,
            )
        )
    return out


def _pareto(rows: Iterable[Row]) -> List[Row]:
    # Sort by sim_cycles asc, then memctrl_bytes asc.
    ordered = sorted(rows, key=lambda r: (r.sim_cycles, r.memctrl_bytes))
    pareto: List[Row] = []
    best_bytes = float("inf")
    for r in ordered:
        if r.memctrl_bytes < best_bytes:
            pareto.append(r)
            best_bytes = r.memctrl_bytes
    return pareto


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tsv", required=True, help="path to calibration_results.tsv")
    ap.add_argument("--write", action="store_true", help="also write pareto_points.tsv next to the input")
    args = ap.parse_args()

    tsv_path = Path(args.tsv).resolve()
    rows = _parse_rows(tsv_path)
    p = _pareto(rows)

    header = [
        "backend",
        "cfg",
        "gap_k",
        "lmax",
        "rowwin",
        "tmo",
        "sim_cycles",
        "memctrl_bytes",
        "row_hit_rate",
        "avg_read_lat",
        "wall_s",
        "run_dir",
    ]
    lines: List[str] = ["\t".join(header)]
    for r in p:
        lines.append(
            "\t".join(
                [
                    r.backend,
                    r.cfg,
                    str(r.gap_k),
                    str(r.lmax),
                    str(r.rowwin),
                    str(r.tmo),
                    str(int(r.sim_cycles)),
                    str(int(r.memctrl_bytes)),
                    ("" if r.row_hit_rate is None else f"{r.row_hit_rate}"),
                    ("" if r.avg_read_lat is None else f"{r.avg_read_lat}"),
                    ("" if r.wall_s is None else f"{r.wall_s}"),
                    r.run_dir,
                ]
            )
        )

    out_text = "\n".join(lines)
    print(out_text)
    if args.write:
        out_path = tsv_path.parent / "pareto_points.tsv"
        out_path.write_text(out_text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

