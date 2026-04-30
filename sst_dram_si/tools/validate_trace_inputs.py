#!/usr/bin/env python3
"""
Validate granules/spikes/gas_stage CSVs for NoC trace driving.
Checks required columns, monotonicity of timestamps, owner!=req share, burst sanity.
Usage:
  python3 sst_dram_si/tools/validate_trace_inputs.py --granules sst_dram_si/analysis/granules.csv [--spikes spikes.csv] [--stages gas_stage.csv]
"""
import argparse, csv, os, sys

def read_rows(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows

def need(cols, req):
    miss = [c for c in req if c not in cols]
    return miss

def as_int(v, default=0):
    try:
        return int(v)
    except Exception:
        return default

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--granules', required=True)
    ap.add_argument('--spikes')
    ap.add_argument('--stages')
    args = ap.parse_args()

    ok = True
    if not os.path.exists(args.granules):
        print(f"[ERR] granules CSV missing: {args.granules}")
        sys.exit(2)
    g = read_rows(args.granules)
    if not g:
        print(f"[ERR] granules CSV empty: {args.granules}")
        ok = False
    else:
        cols = g[0].keys()
        miss = need(cols, ['step','req_tile','owner_tile','burst_bytes','start_ns'])
        if miss:
            print(f"[ERR] granules missing columns: {miss}")
            ok = False
        # monotonic start_ns by step (non-decreasing)
        last = -1
        bad = 0
        for row in g:
            t = as_int(row.get('start_ns'), 0)
            if t < last: bad += 1
            last = max(last, t)
        if bad:
            print(f"[WARN] granules start_ns not monotonic in {bad} rows")
        # owner!=req share
        neq = sum(1 for row in g if as_int(row.get('owner_tile'),0) != as_int(row.get('req_tile'),0))
        share = (neq/len(g))*100.0
        # burst sanity: >=64B
        small = sum(1 for row in g if as_int(row.get('burst_bytes'),0) < 64)
        print(f"[OK] granules: rows={len(g)}, owner!=req={share:.1f}%, burst<64B={small}")

    if args.spikes and os.path.exists(args.spikes):
        s = read_rows(args.spikes)
        if s:
            cols = s[0].keys()
            miss = need(cols, ['step','src_tile','dst_tile'])
            if miss:
                print(f"[ERR] spikes missing columns: {miss}")
                ok = False
            else:
                print(f"[OK] spikes: rows={len(s)}")
    if args.stages and os.path.exists(args.stages):
        t = read_rows(args.stages)
        if t:
            print(f"[OK] gas_stage: rows={len(t)} (format not strictly validated)")

    if not ok:
        sys.exit(1)
    print("Validation passed")

if __name__ == '__main__':
    main()

