#!/usr/bin/env python3
"""
Generate a synthetic granules.csv for 4x4 mesh to exercise P1-2 trace driver.
Output columns: step,req_tile,owner_tile,burst_bytes,start_ns
"""
import argparse, csv, random, os

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--size', type=int, default=4)
    ap.add_argument('--count', type=int, default=64)
    ap.add_argument('--avg-bytes', type=int, default=4096)
    ap.add_argument('--dur-ns', type=int, default=100_000)  # 100us
    ap.add_argument('--out', default='sst_dram_si/analysis/granules.csv')
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    rows = []
    for i in range(args.count):
        req = random.randrange(0, args.size*args.size)
        owner = random.randrange(0, args.size*args.size)
        while owner == req:
            owner = random.randrange(0, args.size*args.size)
        # burst: +-50% around avg
        b = int(max(64, random.gauss(args.avg_bytes, args.avg_bytes*0.25)))
        t = int(i * (args.dur_ns / args.count))
        rows.append({'step': i, 'req_tile': req, 'owner_tile': owner, 'burst_bytes': b, 'start_ns': t})

    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['step','req_tile','owner_tile','burst_bytes','start_ns'])
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {args.out} with {len(rows)} rows")

if __name__ == '__main__':
    main()

