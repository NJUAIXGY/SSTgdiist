#!/usr/bin/env python3
"""
Compare Ramulator2 controller metrics across multiple SST run logs.

Usage:
  python3 compare_ramulator2_logs.py <log1> [<log2> ...]

Outputs a CSV table to stdout with aligned key metrics:
  name, spikes_sent, num_read_reqs_0, avg_read_latency_0, row_hits_0, row_misses_0, row_conflicts_0

Notes:
  - 'name' defaults to basename of the log file (without extension).
  - The parser is tolerant to spaces and prefixes used in our logs.
"""

import os
import re
import sys
import csv

KEYS = [
    (r"avg_read_latency_0:\s*([0-9.]+)", "avg_read_latency_0", float),
    (r"row_hits_0:\s*([0-9]+)", "row_hits_0", int),
    (r"row_misses_0:\s*([0-9]+)", "row_misses_0", int),
    (r"row_conflicts_0:\s*([0-9]+)", "row_conflicts_0", int),
    (r"num_read_reqs_0:\s*([0-9]+)", "num_read_reqs_0", int),
    (r"发送事件数:\s*([0-9]+)", "spikes_sent", int),
]

def parse_one(path: str):
    data = {
        "name": os.path.splitext(os.path.basename(path))[0],
        "spikes_sent": None,
        "num_read_reqs_0": None,
        "avg_read_latency_0": None,
        "row_hits_0": None,
        "row_misses_0": None,
        "row_conflicts_0": None,
    }
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            txt = f.read()
    except Exception as e:
        data["error"] = str(e)
        return data
    for pat, key, typ in KEYS:
        m = re.search(pat, txt)
        if m:
            try:
                data[key] = typ(m.group(1))
            except Exception:
                data[key] = None
    return data

def main():
    if len(sys.argv) < 2:
        print("Usage: compare_ramulator2_logs.py <log1> [<log2> ...]", file=sys.stderr)
        sys.exit(1)
    rows = [parse_one(p) for p in sys.argv[1:]]
    # CSV header
    hdr = ["name", "spikes_sent", "num_read_reqs_0", "avg_read_latency_0", "row_hits_0", "row_misses_0", "row_conflicts_0"]
    w = csv.writer(sys.stdout)
    w.writerow(hdr)
    for r in rows:
        w.writerow([r.get(k, "") for k in hdr])

if __name__ == '__main__':
    main()

