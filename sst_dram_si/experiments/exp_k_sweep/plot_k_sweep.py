#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
plot_k_sweep: 从汇总CSV绘制 k-sweep 曲线（骨架）

用法：
  python3 plot_k_sweep.py --summary sst_dram_si/experiments/exp_k_sweep/runs/k_sweep_summary_*.csv \
                          --out sst_dram_si/experiments/exp_k_sweep/runs/plots

说明：
- 依赖 matplotlib；若环境缺失则仅打印数值摘要。
"""

import argparse
import csv
import os
from collections import defaultdict


def load_summary(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows


def try_plot(groups, out_dir):
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        print('[WARN] matplotlib 不可用，仅打印摘要');
        for cfg, items in groups.items():
            print('==', cfg)
            for k, r in sorted(items.items(), key=lambda x: int(x[0])):
                print(f"  k={k:>6}: reqs_per_mib={r.get('reqs_per_mib')} avg_burst_bytes={r.get('avg_burst_bytes')} avg_lat={r.get('avg_read_latency_0')}")
        return

    os.makedirs(out_dir, exist_ok=True)
    # 绘制 reqs_per_mib vs k 与 avg_burst_bytes vs k
    for cfg, items in groups.items():
        ks = sorted([int(k) for k in items.keys()])
        rpm = [float(items[str(k)].get('reqs_per_mib', 0.0)) for k in ks]
        abb = [float(items[str(k)].get('avg_burst_bytes', 0.0)) for k in ks]

        plt.figure(figsize=(6,4))
        plt.plot(ks, rpm, marker='o')
        plt.xlabel('k (bytes)')
        plt.ylabel('reqs_per_MiB (backend)')
        plt.title(f'k-sweep reqs_per_MiB ({cfg})')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, f'{cfg}_reqs_per_mib.png'), dpi=150)
        plt.close()

        plt.figure(figsize=(6,4))
        plt.plot(ks, abb, marker='o')
        plt.xlabel('k (bytes)')
        plt.ylabel('avg_burst_bytes (GAS unique)')
        plt.title(f'k-sweep avg_burst_bytes ({cfg})')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(out_dir, f'{cfg}_avg_burst_bytes.png'), dpi=150)
        plt.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--summary', required=True)
    ap.add_argument('--out', default='plots')
    args = ap.parse_args()

    rows = load_summary(args.summary)
    groups = defaultdict(dict)  # cfg -> {k: row}
    for r in rows:
        cfg = r.get('dram_cfg','cfg')
        k = r.get('k_bytes','0')
        groups[cfg][k] = r

    try_plot(groups, args.out)
    print('[OK] plot done ->', args.out)


if __name__ == '__main__':
    main()

