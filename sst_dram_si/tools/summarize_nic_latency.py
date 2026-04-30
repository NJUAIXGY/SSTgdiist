#!/usr/bin/env python3
"""
Summarize SnnNIC msg_latency_ns histogram from noc_timestep_stats.csv.
Compute p50/p95/p99 per NIC and overall.
Usage:
  python3 sst_dram_si/tools/summarize_nic_latency.py --csv analysis/noc_timestep_stats.csv --out analysis/noc_latency_summary.csv
"""
import argparse, csv, os, math

def parse_hist_rows(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        r = csv.reader(f)
        header = next(r)
        for row in r:
            if len(row) < 6: continue
            comp, name, subid, typ = row[0], row[1], row[2], row[3]
            # NOTE: ComponentName for SubComponent stats appears as parent component id (e.g., pe_15)
            if name == 'msg_latency_ns' and typ == 'Histogram':
                rows.append((comp, row))
    return rows

def bins_from_header(header):
    bins = []
    for i,h in enumerate(header):
        if h.startswith('Bin') and ':' in h:
            try:
                rng = h.split(':',1)[1]
                lo,hi = rng.split('-')
                lo = int(lo); hi = int(hi.split('.')[0])
                bins.append((i, lo, hi))
            except Exception:
                pass
    return bins

def percentile_from_hist(row, bins, p):
    counts = []
    total = 0
    for idx,lo,hi in bins:
        c = int(row[idx] or 0)
        counts.append((lo,hi,c))
        total += c
    if total == 0: return 0.0
    target = total * p
    acc = 0
    for lo,hi,c in counts:
        acc += c
        if acc >= target:
            return float(hi)
    return float(counts[-1][1])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    with open(args.csv, 'r', encoding='utf-8') as f:
        r = csv.reader(f)
        header = next(r)
        hist_rows = [(comp, row) for comp,row in parse_hist_rows(args.csv)]
        bins = bins_from_header(header)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['nic','count','p50_ns','p95_ns','p99_ns'])
        total_count = 0
        p50s = []; p95s = []; p99s = []
        for comp,row in hist_rows:
            count = int(row[16] or 0)  # NumItemsCollected.u64 index in header
            p50 = percentile_from_hist(row, bins, 0.50)
            p95 = percentile_from_hist(row, bins, 0.95)
            p99 = percentile_from_hist(row, bins, 0.99)
            w.writerow([comp, count, f"{p50:.1f}", f"{p95:.1f}", f"{p99:.1f}"])
            total_count += count
            p50s.append(p50); p95s.append(p95); p99s.append(p99)
        # simple overall (median of medians approximation)
        if hist_rows:
            p50s.sort(); p95s.sort(); p99s.sort()
            w.writerow(['OVERALL', total_count, f"{p50s[len(p50s)//2]:.1f}", f"{p95s[len(p95s)//2]:.1f}", f"{p99s[len(p99s)//2]:.1f}"])
    print(f"Wrote {args.out}")

if __name__ == '__main__':
    main()
