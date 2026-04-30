#!/usr/bin/env python3
"""
Make a new granules.csv with a target remote ratio by toggling owner=req for a subset.
Input CSV columns: step,req_tile,owner_tile,burst_bytes[,start_ns]
Usage:
  python3 sst_dram_si/tools/make_remote_ratio.py \
    --in sst_dram_si/analysis/granules.csv \
    --out sst_dram_si/analysis/granules_remote20.csv \
    --remote 0.20 --size 4
Notes:
  - If input already contains local rows (owner==req)，会优先保留这些本地行；随机挑选远程行降为本地以满足目标占比。
  - 若输入远程比例低于目标，将保留现状（不强制增加远程）。
"""
import argparse, csv, os, random

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--in', dest='inp', required=True)
    ap.add_argument('--out', dest='out', required=True)
    ap.add_argument('--remote', type=float, required=True)
    ap.add_argument('--size', type=int, default=4)
    args = ap.parse_args()

    rows = []
    with open(args.inp, 'r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    if not rows:
        raise SystemExit('empty input')

    # Compute current remote list
    remote_idx = []
    local_idx = []
    for i,row in enumerate(rows):
        try:
            req = int(row.get('req_tile') or row['req'])
            owner = int(row.get('owner_tile') or row['owner'])
        except Exception:
            continue
        if req == owner:
            local_idx.append(i)
        else:
            remote_idx.append(i)
    total = len(local_idx) + len(remote_idx)
    target_remote = int(round(args.remote * total))
    cur_remote = len(remote_idx)

    # If too many remote -> convert some remote to local; if too few, keep as-is.
    delta = cur_remote - target_remote
    if delta > 0:
        # convert delta remote rows to local by setting owner=req
        picks = random.sample(remote_idx, k=delta)
        for i in picks:
            req = int(rows[i]['req_tile'])
            rows[i]['owner_tile'] = str(req)
    # else: do nothing (不强行增加远程)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8', newline='') as g:
        w = csv.DictWriter(g, fieldnames=['step','req_tile','owner_tile','burst_bytes','start_ns'] if 'start_ns' in rows[0] else ['step','req_tile','owner_tile','burst_bytes'])
        w.writeheader()
        w.writerows(rows)
    # print summary
    new_remote = 0
    for row in rows:
        if row['req_tile'] != row['owner_tile']:
            new_remote += 1
    print(f"Wrote {args.out}: remote={new_remote}/{total} ({new_remote/total:.3%})")

if __name__ == '__main__':
    main()

