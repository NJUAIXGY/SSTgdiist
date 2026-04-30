#!/usr/bin/env python3
import os, sys, csv, json
from collections import defaultdict

# Parse SST CSV stats and summarize key metrics for GAS vs baseline
# Usage: analyze_gas_runs.py <run_dir_or_csv> [more ...]  
# It will scan for dram_si_stats.csv under a dir; or accept a direct CSV file path.

ACC_NAMES = [
    'gas_unique_reads', 'gas_unique_bytes', 'gas_upstream_reads',
    'gas_evictions', 'gas_inflight_peak', 'gas_tail_wait_ns'
]
HIST_NAMES = [
    'gas_req_coalesce_size_bytes', 'gas_buffer_occupancy_bytes',
    'gas_stage_cycles_gather', 'gas_stage_cycles_apply', 'gas_stage_cycles_scatter',
    'mem_read_latency_cycles', 'mem_read_latency_cycles_weights'
]

class StatRow:
    def __init__(self, row, header):
        self.row = row; self.h = {k:i for i,k in enumerate(header)}
    def get(self, name, default=0):
        i = self.h.get(name); return row[i] if i is not None else default


def parse_csv(path):
    out = []
    with open(path, 'r', encoding='utf-8') as f:
        r = csv.reader(f)
        hdr = next(r)
        for row in r:
            out.append((row, hdr))
    return out


def find_csv(p):
    if os.path.isdir(p):
        for name in ('dram_si_stats.csv','hist.csv'):
            c = os.path.join(p, name)
            if os.path.isfile(c): return c
        # try walk
        for root,_,files in os.walk(p):
            for name in ('dram_si_stats.csv','hist.csv'):
                if name in files:
                    return os.path.join(root, name)
        raise FileNotFoundError('no stats csv under ' + p)
    else:
        return p


def summarize_one(csv_path):
    rows = parse_csv(csv_path)
    sums = {}
    counts = {}
    maxv = {}
    mean_latency = None
    mean_latency_w = None

    for row,hdr in rows:
        d = {name:row[i] for i,name in enumerate(hdr)}
        comp = d['ComponentName']; stat = d['StatisticName']; stype = d['StatisticType']
        if comp == 'multicore_pe_0' and stat in ('mem_read_latency_cycles','mem_read_latency_cycles_weights') and stype == 'Histogram':
            # average = Sum.u64 / Count.u64
            try:
                s = int(d.get('Sum.u64','0'))
                c = int(d.get('Count.u64','0'))
                if c>0:
                    if stat == 'mem_read_latency_cycles':
                        mean_latency = s / c
                    else:
                        mean_latency_w = s / c
            except: pass
        if comp == 'pe0_l2' and stat == 'MSHR_occupancy':
            # ignore
            pass
        # GAS stats: 判断依据改为 'stat 名称在 ACC_NAMES'（适配子组件名称不同）
        if stype == 'Accumulator' and d['StatisticName'] in ACC_NAMES:
            try:
                sums[stat] = int(d.get('Sum.u64','0'))
                counts[stat] = int(d.get('Count.u64','0'))
                maxv[stat] = int(d.get('Max.u64','0'))
            except: pass
    # derived
    upstream = sums.get('gas_upstream_reads',0)
    unique = sums.get('gas_unique_reads',0)
    coalesce = (upstream / unique) if unique>0 else 1.0
    tail_avg_ns = (sums.get('gas_tail_wait_ns',0)/counts.get('gas_tail_wait_ns',1)) if counts.get('gas_tail_wait_ns',0)>0 else 0

    return {
        'csv': csv_path,
        'upstream_reads': upstream,
        'unique_reads': unique,
        'coalesce_ratio': coalesce,
        'unique_bytes': sums.get('gas_unique_bytes',0),
        'evictions': sums.get('gas_evictions',0),
        'inflight_peak': maxv.get('gas_inflight_peak',0),
        'tail_wait_avg_ns': tail_avg_ns,
        'mean_latency_cycles': mean_latency,
        'mean_latency_cycles_weights': mean_latency_w,
    }


def main():
    if len(sys.argv) < 2:
        print('Usage: analyze_gas_runs.py <run_dir_or_csv> [more ...]')
        sys.exit(1)
    results = []
    for p in sys.argv[1:]:
        try:
            c = find_csv(p)
            results.append(summarize_one(c))
        except Exception as e:
            print('Skip', p, ':', e)
    # print table
    if not results:
        print('No results')
        return
    cols = ['csv','upstream_reads','unique_reads','coalesce_ratio','unique_bytes','evictions','inflight_peak','tail_wait_avg_ns','mean_latency_cycles','mean_latency_cycles_weights']
    print(','.join(cols))
    for r in results:
        print(','.join(str(r.get(k,'')) for k in cols))

if __name__ == '__main__':
    main()
