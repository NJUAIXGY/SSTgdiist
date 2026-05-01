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
            "usage: check_shared_weight_owner_l0_smoke.py <run_dir>",
            file=sys.stderr,
        )
        return 2

    run_dir = Path(sys.argv[1]).resolve()
    csv_path = run_dir / "mesh_stats.csv"
    if not csv_path.exists():
        print(f"missing mesh_stats.csv: {csv_path}", file=sys.stderr)
        return 2

    stats = collect_stats(csv_path)
    core_l0_lookup = stats["weight_l0_lookup_total"]
    core_l0_fill = stats["weight_l0_fill_total"]
    shared_enabled = stats["pulse_osa_shared_weight_enabled"]
    shared_l0_enabled = stats["pulse_osa_shared_weight_l0_enabled"]
    shared_l0_reads = stats["pulse_osa_shared_weight_l0_reads_total"]
    shared_l0_fill = stats["pulse_osa_shared_weight_l0_fill_total"]

    if core_l0_lookup == 0:
        print(
            "shared owner L0 smoke failed: weight_l0_lookup_total is zero, "
            "value-side idx2 ingress prefetch path did not activate",
            file=sys.stderr,
        )
        return 1

    if core_l0_fill == 0:
        print(
            "shared owner L0 smoke failed: weight_l0_fill_total is zero, "
            "no value lines were inserted into the private/shared L0 plane",
            file=sys.stderr,
        )
        return 1

    if shared_enabled == 0 or shared_l0_enabled == 0:
        print(
            "shared owner L0 smoke failed: shared weight/L0 plane is not enabled",
            file=sys.stderr,
        )
        return 1

    if shared_l0_reads == 0 or shared_l0_fill == 0:
        print(
            "shared owner L0 smoke failed: shared L0 stats stayed at zero, "
            "owner plane did not observe value-side traffic",
            file=sys.stderr,
        )
        return 1

    print("shared owner L0 smoke check passed")
    print(f"core_l0_lookup={core_l0_lookup}")
    print(f"core_l0_fill={core_l0_fill}")
    print(f"shared_l0_reads={shared_l0_reads}")
    print(f"shared_l0_fill={shared_l0_fill}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
