#!/usr/bin/env python3
"""Derive end-to-end latency breakdown from stage events + NoC summary."""

import argparse
import csv
import os


def read_stage_stats(path: str) -> dict:
    stats = {
        'avg_gather_ns': 0.0,
        'avg_apply_ns': 0.0,
        'avg_scatter_ns': 0.0,
        'windows': 0,
    }
    if not path or not os.path.exists(path):
        return stats
    stage_map = {}
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                seq = int(row.get('seq'))
                event = row.get('event', '')
                t_ns = int(row.get('sim_time_ns') or row.get('time_ns') or 0)
            except Exception:
                continue
            stage_map.setdefault(seq, {})[event] = t_ns
    gather, apply, scatter = [], [], []
    for events in stage_map.values():
        bg = events.get('BeginGather')
        ba = events.get('BeginApply')
        ea = events.get('EndApply')
        bs = events.get('BeginScatter')
        es = events.get('EndScatter')
        if bg is not None and ba is not None and ba >= bg:
            gather.append(ba - bg)
        if ba is not None and ea is not None and ea >= ba:
            apply.append(ea - ba)
        if bs is not None and es is not None and es >= bs:
            scatter.append(es - bs)
    def avg(lst):
        return (sum(lst) / len(lst)) if lst else 0.0
    stats['avg_gather_ns'] = avg(gather)
    stats['avg_apply_ns'] = avg(apply)
    stats['avg_scatter_ns'] = avg(scatter)
    stats['windows'] = len(stage_map)
    return stats


def read_noc_summary(path: str) -> dict:
    summary = {}
    if not path or not os.path.exists(path):
        return summary
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cls = row.get('class')
            if not cls:
                continue
            def to_float(field):
                try:
                    return float(row.get(field, 0.0))
                except Exception:
                    return 0.0
            def to_int(field):
                try:
                    return int(float(row.get(field, 0)))
                except Exception:
                    return 0
            summary[cls] = {
                'messages': to_int('messages'),
                'total_flits': to_int('total_flits'),
                'total_payload_bytes': to_int('total_payload_bytes'),
                'total_work_units': to_int('total_work_units'),
                'avg_ns': to_float('avg_ns'),
                'p95_ns': to_float('p95_ns'),
                'p99_ns': to_float('p99_ns'),
            }
    return summary


def read_granule_stats(path: str) -> dict:
    stats = {'avg_burst_bytes': 0.0, 'total_bursts': 0}
    if not path or not os.path.exists(path):
        return stats
    bursts = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                bursts.append(int(row.get('burst_bytes') or row.get('bytes') or 0))
            except Exception:
                continue
    if bursts:
        stats['avg_burst_bytes'] = sum(bursts) / len(bursts)
        stats['total_bursts'] = len(bursts)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stages', required=True, help='stage_events CSV with sim_time_ns column')
    ap.add_argument('--noc', required=True, help='noc_trace_summary.csv')
    ap.add_argument('--granules', default='', help='granules.csv for burst sizing (optional)')
    ap.add_argument('--out', default='sst_dram_si/analysis/end2end_breakdown.csv')
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    stage_stats = read_stage_stats(args.stages)
    noc_stats = read_noc_summary(args.noc)
    gran_stats = read_granule_stats(args.granules)

    noc_resp = noc_stats.get('read_resp', {})
    t_noc_avg = noc_resp.get('avg_ns', 0.0)
    t_compute = stage_stats.get('avg_apply_ns', 0.0) + stage_stats.get('avg_scatter_ns', 0.0)
    t_dram_wait = max(stage_stats.get('avg_gather_ns', 0.0) - t_noc_avg, 0.0)
    t_total = t_dram_wait + t_noc_avg + t_compute

    fields = [
        'windows',
        'avg_gather_ns',
        'avg_apply_ns',
        'avg_scatter_ns',
        't_dram_wait_ns',
        't_noc_avg_ns',
        't_compute_ns',
        't_total_ns',
        'read_resp_messages',
        'read_resp_total_flits',
        'read_resp_total_payload_bytes',
        'avg_burst_bytes',
        'total_bursts',
    ]
    row = {
        'windows': stage_stats.get('windows', 0),
        'avg_gather_ns': f"{stage_stats.get('avg_gather_ns', 0.0):.2f}",
        'avg_apply_ns': f"{stage_stats.get('avg_apply_ns', 0.0):.2f}",
        'avg_scatter_ns': f"{stage_stats.get('avg_scatter_ns', 0.0):.2f}",
        't_dram_wait_ns': f"{t_dram_wait:.2f}",
        't_noc_avg_ns': f"{t_noc_avg:.2f}",
        't_compute_ns': f"{t_compute:.2f}",
        't_total_ns': f"{t_total:.2f}",
        'read_resp_messages': noc_resp.get('messages', 0),
        'read_resp_total_flits': noc_resp.get('total_flits', 0),
        'read_resp_total_payload_bytes': noc_resp.get('total_payload_bytes', 0),
        'avg_burst_bytes': f"{gran_stats.get('avg_burst_bytes', 0.0):.2f}",
        'total_bursts': gran_stats.get('total_bursts', 0),
    }

    with open(args.out, 'w', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)

    print("End-to-end breakdown saved to", args.out)
    print(f"  t_total_ns={row['t_total_ns']}, t_noc_avg_ns={row['t_noc_avg_ns']}, t_compute_ns={row['t_compute_ns']}, t_dram_wait_ns={row['t_dram_wait_ns']}")


if __name__ == '__main__':
    main()
