#!/usr/bin/env python3
"""
汇总本次仿真的核心统计为一个 JSON（analysis/essential_summary.json）。

输入（可通过 CLI 覆盖，均为可选，尽量容错）：
  --stats   : sst_dram_si/analysis/noc_timestep_stats.csv（SST CSV 统计）
  --events  : sst_dram_si/stats/stage_events_db_*.csv（GAS阶段事件）
  --spikes  : sst_dram_si/analysis/spikes.csv（由 SnnNIC 导出的批量脉冲轨迹，可为空）
  --config  : sst_dram_si/local_run_config.json（用于解析每PE/每核规模与mesh）
  --time    : 外部 /usr/bin/time 输出（WALL/USER/SYS/MAXRSS），可为空
  --out     : 输出 JSON 路径（默认：sst_dram_si/analysis/essential_summary.json）

输出字段（示例）：
{
  "model": {
    "mesh": 4,
    "nodes": 16,
    "cores_per_pe": 20,
    "neurons_per_core": 50000,
    "neurons_per_pe": 1000000,
    "neurons_total": 16000000
  },
  "activity": {
    "total_neurons_fired": 1234567,
    "firing_ratio_per_neuron": 0.0123
  },
  "communication": {
    "spikes_total": 9876543,
    "packets_total": 55555,
    "cross_chip_ratio": 0.42
  },
  "memory": {
    "dram_bytes_read": 1234567890,
    "memory_requests": 4567890
  },
  "gas_superstep_cycles": {
    "windows": 7143,
    "gather": {"avg": 200, "p95": 200, "p99": 200},
    "apply":  {"avg":  40, "p95":  40, "p99":  40},
    "scatter":{"avg":  40, "p95":  40, "p99":  40},
    "total":  {"avg": 280, "p95": 280, "p99": 280}
  },
  "wallclock": {
    "wall": "0:04:37",
    "user": 1234.56,
    "sys":  78.9,
    "maxrss_kb": 12345678
  }
}

实现要点：
  - 统计 CSV 的列名在不同版本 SST 可能不同，采用“包含关系”方式鲁棒解析。
  - 优先聚合 MultiCorePE 的统计以避免重复（SnnPESubComponent 在某些场景也会暴露聚合同名指标）。
  - spikes.csv 若不存在，则以 NIC 统计为准，cross_chip_ratio 设置为 null。
  - stage_events 若缺失，gas_superstep_cycles 置为空结构并继续输出其它项。
"""

from __future__ import annotations
import argparse
import csv
import json
import math
import os
import re
from statistics import median


def _read_json(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _detect_header(cols):
    # 返回通用键映射：component, stat, sub, rank, thread, value
    low = [c.strip().lower() for c in cols]
    m = {
        'component': None,
        'stat': None,
        'sub': None,
        'rank': None,
        'thread': None,
        'value': None,
    }
    for i, c in enumerate(low):
        if m['component'] is None and ('component' in c):
            m['component'] = i
        if m['stat'] is None and ('statistic' in c and 'name' in c):
            m['stat'] = i
        if m['value'] is None and (c in ('count', 'sum', 'value', 'statistic count', 'statistic sum')):
            m['value'] = i
        if m['sub'] is None and ('sub' in c and 'id' in c):
            m['sub'] = i
        if m['rank'] is None and ('rank' == c):
            m['rank'] = i
        if m['thread'] is None and ('thread' in c):
            m['thread'] = i
    return m


def _parse_stats_csv(path: str) -> list[dict]:
    rows = []
    if not path or not os.path.exists(path):
        return rows
    with open(path, newline='') as f:
        r = csv.reader(f)
        try:
            header = next(r)
        except StopIteration:
            return rows
        idx = _detect_header(header)
        for line in r:
            if not line or len(line) < 3:
                continue
            try:
                comp = line[idx['component']] if idx['component'] is not None else line[0]
                stat = line[idx['stat']] if idx['stat'] is not None else line[1]
                val  = line[idx['value']] if idx['value'] is not None else line[-1]
                v = int(val)
            except Exception:
                # 尝试浮点，再舍入
                try:
                    v = int(float(val))
                except Exception:
                    continue
            rows.append({'component': comp, 'stat': stat, 'value': v})
    return rows


def _sum_stats(rows, comp_prefixes, stat_name):
    total = 0
    for rr in rows:
        c = (rr['component'] or '').strip()
        s = (rr['stat'] or '').strip()
        if any(c.startswith(p) for p in comp_prefixes) and s == stat_name:
            total += int(rr['value'])
    return total


def _count_components(rows, comp_prefix):
    s = set()
    for rr in rows:
        c = (rr['component'] or '').strip()
        if c.startswith(comp_prefix):
            s.add(c)
    return len(s)


def _parse_spikes_csv(path: str):
    # spikes.csv: kind,src_tile,dst_tile,start_ns,logical_step,spike_count,payload_bytes
    if not path or not os.path.exists(path):
        return None
    total = 0
    remote = 0
    with open(path, newline='') as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                sc = int(row.get('spike_count', '0'))
                src = int(row.get('src_tile', '-1'))
                dst = int(row.get('dst_tile', '-1'))
            except Exception:
                continue
            total += sc
            if src != dst:
                remote += sc
    if total <= 0:
        return {
            'spikes_total': 0,
            'cross_chip_ratio': None
        }
    return {
        'spikes_total': total,
        'cross_chip_ratio': (remote / total) if total > 0 else None
    }


def _parse_events_csv(path: str):
    # 期望列：seq,event,sim_time_ns,acc_updates,posts_touched,hwm_bytes,spill_records,spilled_bytes,spikes_emitted
    # 输出：每个 seq 的各阶段耗时（ns）与 total
    if not path or not os.path.exists(path):
        return None
    by_seq = {}
    with open(path, newline='') as f:
        r = csv.DictReader(f)
        for row in r:
            try:
                seq = int(row.get('seq', '0'))
                evt = (row.get('event', '') or '').strip()
                ts = int(row.get('sim_time_ns', '0'))
            except Exception:
                continue
            by_seq.setdefault(seq, []).append((evt, ts))
    # 计算每个seq的阶段长度
    windows = []
    for seq, evts in by_seq.items():
        # 按时间排序，保守匹配
        evts.sort(key=lambda x: x[1])
        t = {k: None for k in ('BeginGather','BeginApply','EndApply','BeginScatter','EndScatter')}
        for e, ts in evts:
            if e in t and t[e] is None:
                t[e] = ts
        # 粗鲁但鲁棒：若缺BeginGather，则以最早时间为起点
        bg = t['BeginGather'] if t['BeginGather'] is not None else (evts[0][1] if evts else None)
        ga = t['BeginApply']
        ea = t['EndApply']
        bs = t['BeginScatter']
        es = t['EndScatter']
        if bg is None or es is None:
            continue
        g_len = (ga - bg) if (ga is not None and bg is not None and ga >= bg) else 0
        a_len = (ea - ga) if (ea is not None and ga is not None and ea >= ga) else 0
        s_len = (es - bs) if (es is not None and bs is not None and es >= bs) else 0
        total = (es - bg) if (es is not None and bg is not None and es >= bg) else (g_len + a_len + s_len)
        windows.append({'seq': seq, 'gather': g_len, 'apply': a_len, 'scatter': s_len, 'total': total})
    if not windows:
        return None
    def _pct(vals, p):
        if not vals:
            return 0
        vals = sorted(vals)
        k = max(0, min(len(vals)-1, math.ceil(p*len(vals)) - 1))
        return vals[k]
    g = [w['gather'] for w in windows]
    a = [w['apply'] for w in windows]
    s = [w['scatter'] for w in windows]
    t = [w['total'] for w in windows]
    return {
        'windows': len(windows),
        'gather': {'avg': int(sum(g)/len(g)) if g else 0, 'p95': int(_pct(g, 0.95)), 'p99': int(_pct(g, 0.99))},
        'apply':  {'avg': int(sum(a)/len(a)) if a else 0, 'p95': int(_pct(a, 0.95)), 'p99': int(_pct(a, 0.99))},
        'scatter':{'avg': int(sum(s)/len(s)) if s else 0, 'p95': int(_pct(s, 0.95)), 'p99': int(_pct(s, 0.99))},
        'total':  {'avg': int(sum(t)/len(t)) if t else 0, 'p95': int(_pct(t, 0.95)), 'p99': int(_pct(t, 0.99))},
    }


def _parse_time_file(path: str):
    if not path or not os.path.exists(path):
        return None
    # 期望格式：WALL=H:MM:SS USER=... SYS=... MAXRSS=...
    out = {}
    with open(path, 'r') as f:
        txt = f.read()
    m = re.search(r'WALL=([^\n\s]+)', txt)
    if m:
        out['wall'] = m.group(1)
    m = re.search(r'USER=([0-9]+\.?[0-9]*)', txt)
    if m:
        out['user'] = float(m.group(1))
    m = re.search(r'SYS=([0-9]+\.?[0-9]*)', txt)
    if m:
        out['sys'] = float(m.group(1))
    m = re.search(r'MAXRSS=([0-9]+)', txt)
    if m:
        out['maxrss_kb'] = int(m.group(1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', dest='run_dir', default=None, help='若提供，所有默认输入/输出路径均相对该目录')
    ap.add_argument('--stats', default=None)
    ap.add_argument('--events', default=None)
    ap.add_argument('--spikes', default=None)
    ap.add_argument('--config', default=os.path.join('sst_dram_si', 'local_run_config.json'))
    ap.add_argument('--time', default=None)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    # 基于 run-dir 解析默认路径
    if args.run_dir:
        base = args.run_dir
        stats_path = args.stats or os.path.join(base, 'noc_timestep_stats.csv')
        events_path = args.events or os.path.join(base, 'stage_events_db_100us.csv')
        spikes_path = args.spikes or os.path.join(base, 'spikes.csv')
        time_path = args.time or os.path.join(base, 'last_run.time')
        out_path = args.out or os.path.join(base, 'essential_summary.json')
    else:
        stats_path = args.stats or os.path.join('analysis', 'noc_timestep_stats.csv')
        events_path = args.events or os.path.join('sst_dram_si', 'stats', 'stage_events_db_100us.csv')
        spikes_path = args.spikes or os.path.join('analysis', 'spikes.csv')
        time_path = args.time or os.path.join('sst_output_data', 'last_run.time')
        out_path = args.out or os.path.join('sst_dram_si', 'analysis', 'essential_summary.json')

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    cfg = _read_json(args.config)

    stats_rows = _parse_stats_csv(stats_path)
    events_summary = _parse_events_csv(events_path)
    spikes_summary = _parse_spikes_csv(spikes_path)
    time_summary = _parse_time_file(time_path)

    # 推断 mesh / nodes：从 Router 组件数量推断（merlin.hr_router 前缀）
    router_count = _count_components(stats_rows, 'router_')
    if router_count > 0:
        mesh = int(round(math.sqrt(router_count)))
        nodes = mesh * mesh
    else:
        # 回退：无router统计时，尝试从配置读取
        mesh = int(cfg.get('mesh_size', 0) or 0)
        nodes = mesh * mesh if mesh > 0 else 0

    cores_per_pe = int(cfg.get('num_cores_per_pe', 0) or 0)
    neurons_per_core = int(cfg.get('neurons_per_core', 0) or 0)
    neurons_per_pe = cores_per_pe * neurons_per_core if cores_per_pe and neurons_per_core else 0
    neurons_total = nodes * neurons_per_pe if nodes and neurons_per_pe else 0

    # Activity（优先MultiCorePE聚合，避免重复）
    total_neurons_fired = _sum_stats(stats_rows, ('pe_', 'SnnDL.MultiCorePE'), 'total_neurons_fired')
    # Memory
    memory_requests = _sum_stats(stats_rows, ('pe_', 'SnnDL.MultiCorePE'), 'memory_requests')
    # gas_unique_bytes_total 可来自 MultiCorePE 或 SubComponent；优先聚合 MultiCorePE
    dram_bytes_read = _sum_stats(stats_rows, ('pe_', 'SnnDL.MultiCorePE'), 'gas_unique_bytes_total')
    if dram_bytes_read == 0:
        dram_bytes_read = _sum_stats(stats_rows, ('SnnDL.SnnPESubComponent',), 'gas_unique_bytes_total')

    # Communication：来自 NIC 统计与 spikes.csv
    packets_total = _sum_stats(stats_rows, ('nic_', 'SnnDL.SnnNIC'), 'packets_sent')
    if packets_total == 0:
        packets_total = _sum_stats(stats_rows, ('pe_', 'SnnDL.MultiCorePE'), 'packets_sent')
    # spikes总数优先 spikes.csv；若无，则从 NIC 的 spikes_sent 汇总
    if spikes_summary and spikes_summary.get('spikes_total'):
        spikes_total = spikes_summary['spikes_total']
        cross_chip_ratio = spikes_summary.get('cross_chip_ratio')
    else:
        spikes_total = _sum_stats(stats_rows, ('nic_', 'SnnDL.SnnNIC'), 'spikes_sent')
        if spikes_total == 0:
            spikes_total = _sum_stats(stats_rows, ('pe_', 'SnnDL.MultiCorePE'), 'spikes_sent')
        cross_chip_ratio = None

    firing_ratio = (total_neurons_fired / neurons_total) if (neurons_total > 0) else None

    out = {
        'model': {
            'mesh': mesh,
            'nodes': nodes,
            'cores_per_pe': cores_per_pe,
            'neurons_per_core': neurons_per_core,
            'neurons_per_pe': neurons_per_pe,
            'neurons_total': neurons_total,
        },
        'activity': {
            'total_neurons_fired': total_neurons_fired,
            'firing_ratio_per_neuron': firing_ratio,
        },
        'communication': {
            'spikes_total': spikes_total,
            'packets_total': packets_total,
            'cross_chip_ratio': cross_chip_ratio,
        },
        'memory': {
            'dram_bytes_read': dram_bytes_read,
            'memory_requests': memory_requests,
        },
        'gas_superstep_cycles': (events_summary or {}),
        'wallclock': (time_summary or {}),
    }

    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[OK] essential_summary.json -> {out_path}")


if __name__ == '__main__':
    main()
