#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
解析 SnnPESubComponent 的 stage_events_csv（Begin/End Apply/Scatter）
计算每个 superstep 的阶段时长与总时长（单位：ns，同时等价于cycles@1GHz）。
输入：stage_events_db_*.csv（seq,event,sim_time_ns,acc_updates,posts_touched,hwm_bytes,spill_records,spilled_bytes,spikes_emitted）
输出：analysis/gas_superstep_summary.csv
"""

import argparse
import csv
import os
from collections import defaultdict

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--events', required=True, help='stage_events_db_*.csv 路径')
    ap.add_argument('--out', default='analysis/gas_superstep_summary.csv')
    return ap.parse_args()

def main():
    args = parse_args()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    # 按 seq 聚合事件时间戳
    events = defaultdict(lambda: defaultdict(list))  # seq -> event -> [ts]
    with open(args.events, newline='') as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                seq = int(row['seq'])
                ev = row['event']
                t = int(row['sim_time_ns'])
            except Exception:
                continue
            events[seq][ev].append(t)

    # 计算每个窗口的时长（取同名事件的首个时间戳）
    rows = []
    for seq, m in sorted(events.items()):
        def first(ev):
            return min(m[ev]) if ev in m and m[ev] else None
        t_bg = first('BeginGather')
        t_ba = first('BeginApply')
        t_ea = first('EndApply')
        t_bs = first('BeginScatter')
        t_es = first('EndScatter')

        gather_ns = (t_ba - t_bg) if (t_bg is not None and t_ba is not None) else None
        apply_ns  = (t_ea - t_ba) if (t_ba is not None and t_ea is not None) else None
        scatter_ns= (t_es - t_bs) if (t_bs is not None and t_es is not None) else None
        total_ns  = (t_es - t_bg) if (t_bg is not None and t_es is not None) else None

        rows.append({
            'seq': seq,
            't_begin_gather': t_bg,
            't_begin_apply': t_ba,
            't_end_apply': t_ea,
            't_begin_scatter': t_bs,
            't_end_scatter': t_es,
            'gather_ns': gather_ns,
            'apply_ns': apply_ns,
            'scatter_ns': scatter_ns,
            'superstep_total_ns': total_ns,
            'gather_cycles': gather_ns if gather_ns is not None else '',
            'apply_cycles': apply_ns if apply_ns is not None else '',
            'scatter_cycles': scatter_ns if scatter_ns is not None else '',
            'superstep_total_cycles': total_ns if total_ns is not None else '',
        })

    # 写出汇总
    with open(args.out, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [
            'seq','t_begin_gather','t_begin_apply','t_end_apply','t_begin_scatter','t_end_scatter',
            'gather_ns','apply_ns','scatter_ns','superstep_total_ns','gather_cycles','apply_cycles','scatter_cycles','superstep_total_cycles'])
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"Wrote summary: {args.out} (rows={len(rows)})")

if __name__ == '__main__':
    main()
