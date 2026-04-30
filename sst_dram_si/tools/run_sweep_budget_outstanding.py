#!/usr/bin/env python3
import json, os, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = ROOT / 'local_run_config.json'
WRAP = ROOT / 'run_singlepe_with_time.sh'

def load_cfg():
    return json.load(open(CFG,'r',encoding='utf-8'))

def save_cfg(obj):
    json.dump(obj, open(CFG,'w',encoding='utf-8'), ensure_ascii=False, indent=2)

def run_once():
    subprocess.check_call([str(WRAP)])

def latest_run_base(cfg):
    p = cfg.get('dataset_path','outputs_large/paper2/dram_N1k/spikes_srcdst.txt')
    base = (ROOT / p).resolve().parent
    return base

def parse_summary(base: Path):
    latest = base / 'latest' / 'essential_summary.json'
    if not latest.exists():
        return None
    obj = json.load(open(latest,'r'))
    mem = obj.get('memory',{})
    sa = obj.get('spike_activity',{})
    return {
        'memory_requests': mem.get('memory_requests',0),
        'dram_bytes_read': mem.get('dram_bytes_read',0) or 0,
        'unique_neurons_fired': sa.get('unique_neurons_fired',0) or sa.get('unique_firing_fraction',0),
        'total_neurons_fired': sa.get('total_neurons_fired',0)
    }

def main():
    cfg0 = load_cfg()
    base = latest_run_base(cfg0)
    out_csv = base / 'sweep_results.csv'
    budgets = [160,256,512]
    outs = [64,96,128]
    rows = []
    for b in budgets:
        for o in outs:
            cfg = load_cfg()
            cfg['window_read_budget'] = b
            cfg['max_outstanding_requests'] = o
            cfg['window_read_debug'] = 0
            cfg['core_verbose'] = 0
            save_cfg(cfg)
            print(f"[sweep] budget={b} outstanding={o}")
            run_once()
            m = parse_summary(base) or {}
            rows.append((b,o,m.get('memory_requests',0), m.get('dram_bytes_read',0), m.get('unique_neurons_fired',0), m.get('total_neurons_fired',0)))
    # write CSV
    with open(out_csv,'w') as f:
        f.write('budget,max_outstanding,memory_requests,dram_bytes_read,unique_neurons_fired,total_neurons_fired\n')
        for r in rows:
            f.write(','.join(str(x) for x in r)+'\n')
    print(f"[sweep] results -> {out_csv}")

if __name__ == '__main__':
    main()

