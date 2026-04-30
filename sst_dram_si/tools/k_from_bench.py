#!/usr/bin/env python3
import argparse, csv, json, os, sys, time

def read_bench_csv(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                rows.append({
                    'scene': row['scene'],
                    'L': int(row['L']),
                    'gap': int(row['gap']),
                    'split_ns': int(row['split_ns']),
                    'merge_ns': int(row['merge_ns'])
                })
            except Exception:
                continue
    return rows

def fit_k_per_L(rows, scene='row_hit'):
    byL = {}
    for row in rows:
        if row['scene'] != scene:
            continue
        byL.setdefault(row['L'], []).append((row['gap'], row['split_ns'], row['merge_ns']))
    k_per_L = {}
    for L, ents in byL.items():
        ents.sort(key=lambda x: x[0])
        k = None
        for gap, ts, tm in ents:
            if tm <= ts:
                k = gap
                break
        k_per_L[L] = k
    return k_per_L

def percentile_value(values, p=0.75):
    if not values:
        return None
    vs = sorted(values)
    # clamp p into [0,1]
    p = max(0.0, min(1.0, p))
    idx = int(round(p * (len(vs) - 1)))
    return vs[idx]

def main():
    ap = argparse.ArgumentParser(description='Fit k_empirical(L) and k_recommended from bench_results.csv and optionally update config')
    ap.add_argument('--csv', default='sst_dram_si/stats/kcal/bench_results.csv', help='bench CSV path')
    ap.add_argument('--cfg', default='sst_dram_si/local_run_config.json', help='config JSON to update')
    ap.add_argument('--scene', default='row_hit', choices=['row_hit','row_switch'], help='which scene to use for fitting')
    ap.add_argument('--percentile', type=float, default=0.75, help='percentile across L for k_recommended')
    ap.add_argument('--min-bytes', type=int, default=0, help='min clamp for k recommendation')
    ap.add_argument('--max-bytes', type=int, default=1<<20, help='max clamp for k recommendation')
    ap.add_argument('--dry-run', action='store_true', help='do not write config; only print results')
    ap.add_argument('--out', default=None, help='optional JSON summary output')
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f'[k-from-bench] CSV not found: {args.csv}', file=sys.stderr)
        sys.exit(1)

    rows = read_bench_csv(args.csv)
    if not rows:
        print('[k-from-bench] No rows parsed from CSV', file=sys.stderr)
        sys.exit(1)

    k_per_L = fit_k_per_L(rows, scene=args.scene)
    ks = [k for k in k_per_L.values() if k is not None]
    k_rec = percentile_value(ks, args.percentile) if ks else None
    if k_rec is None:
        k_rec = 0
    if args.min_bytes is not None:
        k_rec = max(k_rec, args.min_bytes)
    if args.max_bytes is not None:
        k_rec = min(k_rec, args.max_bytes)

    summary = {
        'csv': os.path.abspath(args.csv),
        'scene': args.scene,
        'percentile': args.percentile,
        'k_per_L': k_per_L,
        'k_recommended': k_rec,
    }

    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if not args.dry_run:
        try:
            cfg = json.load(open(args.cfg, 'r', encoding='utf-8'))
        except Exception as e:
            print(f'[k-from-bench] Failed to read config {args.cfg}: {e}', file=sys.stderr)
            sys.exit(2)
        cfg['gap_merge_k_bytes'] = int(k_rec)
        with open(args.cfg, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        print(f'[k-from-bench] Updated {args.cfg}: gap_merge_k_bytes={k_rec}')

    if args.out:
        try:
            with open(args.out, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)
            print(f'[k-from-bench] Wrote summary {args.out}')
        except Exception as e:
            print(f'[k-from-bench] Failed writing summary {args.out}: {e}', file=sys.stderr)

if __name__ == '__main__':
    main()

