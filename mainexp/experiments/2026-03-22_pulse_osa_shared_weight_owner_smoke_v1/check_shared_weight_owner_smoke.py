#!/usr/bin/env python3
import csv
import sys
from collections import defaultdict
from pathlib import Path


def collect_stats(csv_path: Path):
    totals = defaultdict(int)
    with csv_path.open(newline="") as f:
        for row in csv.DictReader(f):
            name = row["StatisticName"]
            max_u64 = int(row["Max.u64"] or 0)
            totals[name] += max_u64
    return totals


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: check_shared_weight_owner_smoke.py <run_dir>",
            file=sys.stderr,
        )
        return 2

    run_dir = Path(sys.argv[1]).resolve()
    csv_path = run_dir / "mesh_stats.csv"
    if not csv_path.exists():
        print(f"missing mesh_stats.csv: {csv_path}", file=sys.stderr)
        return 2

    stats = collect_stats(csv_path)
    core_idx_reads = stats["weight_idx_sram_reads_total"]
    shared_enabled = stats["pulse_osa_shared_weight_enabled"]
    shared_idx_enabled = stats["pulse_osa_shared_weight_idx_enabled"]
    shared_idx_reads = stats["pulse_osa_shared_weight_idx_reads_total"]

    if core_idx_reads == 0:
        print(
            "unexpected smoke state: core weight idx reads are zero, "
            "cannot validate shared owner binding",
            file=sys.stderr,
        )
        return 1

    if shared_enabled == 0 or shared_idx_enabled == 0:
        print(
            "unexpected smoke state: shared plane is not enabled",
            file=sys.stderr,
        )
        return 1

    if shared_idx_reads == 0:
        print(
            "shared owner regression: core idx path is active but "
            "pulse_osa_shared_weight_idx_reads_total is still zero",
            file=sys.stderr,
        )
        return 1

    print("shared owner smoke check passed")
    print(f"core_idx_reads={core_idx_reads}")
    print(f"shared_idx_reads={shared_idx_reads}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
