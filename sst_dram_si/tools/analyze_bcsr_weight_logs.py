#!/usr/bin/env python3
"""
Cross-check BCSR debug logs with spike-derived weights.

Usage:
  python analyze_bcsr_weight_logs.py \
      --log sst_dram_si/logs/last_run.wrapper.log \
      --spike-file sst_dram_si/outputs_large/paper2/dram_N100k/spikessrcdstN100000.txt \
      --weight-scale 10.0 --tolerance 1e-4
"""

import argparse
import re
from collections import Counter


def build_expected_weights(spike_file: str, scale: float) -> Counter:
    counts: Counter = Counter()
    with open(spike_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                src = int(parts[0])
                dst = int(parts[1])
            except ValueError:
                continue
            counts[(src, dst)] += 1
    for key in list(counts.keys()):
        counts[key] *= scale
    return counts


def analyze(log_path: str,
            expected: Counter,
            tolerance: float) -> None:
    pattern = re.compile(
        r"\[diag-bcsr-weight\]\s+core=(?P<core>\d+)\s+post_local=(?P<post_local>\d+)\s+post_global=(?P<post_global>\d+)\s+pre_global=(?P<pre_global>\d+)\s+weight=(?P<weight>[-+]?\d+\.\d+)"
    )

    total = matched = mismatched = 0
    unexpected_entries = []
    actual_weights: Counter = Counter()

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            m = pattern.search(line)
            if not m:
                continue
            total += 1
            pre = int(m.group("pre_global"))
            post = int(m.group("post_global"))
            weight = float(m.group("weight"))
            key = (pre, post)
            actual_weights[key] = weight  # last occurrence wins
            exp = expected.get(key)
            if exp is None:
                if abs(weight) > tolerance and len(unexpected_entries) < 20:
                    unexpected_entries.append((pre, post, weight))
            else:
                if abs(weight - exp) <= tolerance:
                    matched += 1
                else:
                    mismatched += 1

    missing_entries = []
    for key, exp in expected.items():
        if abs(exp) <= tolerance:
            continue
        if key not in actual_weights:
            if len(missing_entries) < 20:
                missing_entries.append((key[0], key[1], 0.0, exp))
        else:
            act = actual_weights[key]
            if abs(act - exp) > tolerance and len(missing_entries) < 20:
                missing_entries.append((key[0], key[1], act, exp))

    print("=== BCSR Log vs Spike Weights ===")
    print(f"log entries processed : {total}")
    print(f"matched entries       : {matched}")
    print(f"mismatched entries    : {mismatched}")
    print(f"pairs missing/mismatch: {len(missing_entries)}")
    print(f"unexpected pairs (>tol): {len(unexpected_entries)}")
    if mismatched and missing_entries:
        print("\nSample mismatched or missing entries (pre, post, log_weight, expected):")
        for pre, post, act, exp in missing_entries:
            print(f"  ({pre}, {post}) -> log={act:.6f}, expected={exp:.6f}")
    if unexpected_entries:
        print("\nUnexpected non-zero weights (pre, post, weight):")
        for pre, post, w in unexpected_entries:
            print(f"  ({pre}, {post}) -> weight={w:.6f}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Verify BCSR weight logs against spike-derived weights.")
    ap.add_argument("--log", required=True, help="Path to wrapper log containing [diag-bcsr-weight] lines.")
    ap.add_argument("--spike-file", required=True, help="Spike txt file used to build weights.")
    ap.add_argument("--weight-scale", type=float, default=1.0, help="Weight scale used when generating BCSR.")
    ap.add_argument("--tolerance", type=float, default=1e-4, help="Tolerance for weight comparisons.")
    args = ap.parse_args()

    expected = build_expected_weights(args.spike_file, args.weight_scale)
    analyze(args.log, expected, args.tolerance)


if __name__ == "__main__":
    main()
