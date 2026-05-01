#!/usr/bin/env python3
"""Export a compact Stage-B paper figure TSV from compare.tsv."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Tuple


SELECTED_METRICS: Tuple[Tuple[str, str], ...] = (
    ("model.sim_time_actual_ns", "sim_time"),
    ("memory.memory_requests", "runtime_requests"),
    ("memhierarchy.memctrl.req_total", "dram_requests"),
    ("pulse_domain_hol_recoverable_cycles_total", "recoverable_cycles"),
    ("pulse_domain_hol_recoverable_edges_total", "recoverable_edges"),
    ("pulse_domain_ready_domains_peak", "ready_domains_peak"),
    ("pulse_domain_committable_edges_peak", "committable_edges_peak"),
    ("pulse_domain_hol_release_ratio", "hol_release_ratio"),
)


def _read_compare_rows(path: Path) -> Dict[str, List[str]]:
    rows: Dict[str, List[str]] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0] == "metric":
                continue
            if len(parts) != 4:
                raise SystemExit(f"invalid compare.tsv row: {line}")
            rows[parts[0]] = parts[1:]
    return rows


def _safe_pct(baseline: str, delta: str) -> str:
    try:
        base_value = float(baseline)
        delta_value = float(delta)
    except ValueError:
        return "NA"
    if base_value == 0.0:
        return "NA"
    return str((delta_value / base_value) * 100.0)


def _write_stage_b(out_path: Path, compare_rows: Dict[str, List[str]]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# profile\tpulse_domain_retire_shadow_stage_b_main_figure",
        "metric\tbaseline\tcandidate\tdelta_abs\tdelta_pct\tnote",
    ]
    for metric, note in SELECTED_METRICS:
        baseline, candidate, delta_abs = compare_rows.get(metric, ["0", "0", "0"])
        delta_pct = _safe_pct(baseline, delta_abs)
        lines.append("\t".join([metric, baseline, candidate, delta_abs, delta_pct, note]))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--compare", default=str(Path(__file__).resolve().with_name("snapshot") / "compare.tsv"), help="path to compare.tsv")
    ap.add_argument("--out", default=str(Path(__file__).resolve().with_name("snapshot") / "stage_b_main.tsv"), help="output stage_b_main.tsv path")
    args = ap.parse_args()

    compare_rows = _read_compare_rows(Path(args.compare).resolve())
    out_path = Path(args.out).resolve()
    _write_stage_b(out_path, compare_rows)
    print(f"[stage-b] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
