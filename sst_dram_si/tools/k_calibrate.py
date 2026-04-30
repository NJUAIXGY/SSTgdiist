#!/usr/bin/env python3
import os, json, argparse, subprocess
from datetime import datetime

KS_DEFAULT = [0, 512, 1024, 2048, 4096, 8192]

def run_one(cfg_path, updates, stats_rel, log_path):
    cfg = json.load(open(cfg_path,'r'))
    cfg.update(updates)
    cfg['stats_csv'] = stats_rel
    open(cfg_path,'w').write(json.dumps(cfg, indent=2, ensure_ascii=False))
    with open(log_path,'w') as f:
        subprocess.run(['./sst', 'sst_dram_si/test_dram_si_single_pe.py'], stdout=f, stderr=subprocess.STDOUT, check=True)

def derive(stats_abs, log_path):
    p = subprocess.run(['python3','sst_dram_si/tools/derive_gas_metrics.py', stats_abs, '--stdout', log_path], capture_output=True, text=True)
    lines = p.stdout.strip().splitlines()
    if len(lines)>=2:
        header = lines[0].split(',')
        vals = lines[1].split(',')
        return dict(zip(header, vals))
    return {}

def main():
    ap = argparse.ArgumentParser(description='Calibrate k=gap_merge_k_bytes by sweeping candidates')
    ap.add_argument('--cfg', default='sst_dram_si/local_run_config.json')
    ap.add_argument('--dur', default='100us')
    ap.add_argument('--k', nargs='*', type=int, help='candidate k bytes')
    ap.add_argument('--lmax', type=int, default=65536)
    ap.add_argument('--sort', default='bank_row')
    ap.add_argument('--lat_tol', type=float, default=0.5, help='allowed latency increase vs baseline (ns)')
    args = ap.parse_args()

    ks = args.k or KS_DEFAULT
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    os.makedirs('sst_dram_si/stats/kcal', exist_ok=True)
    summary_path = f'sst_dram_si/stats/kcal/summary_k_{args.dur}_{stamp}.csv'
    with open(summary_path,'w') as f:
        f.write('k,stats_csv,unique_reads,unique_bytes,bursts,payload,avg_burst_bytes,req_bytes,total_mib,reqs_per_mib,rowwin_triggers,rowwin_bytes,rowwin_share,avg_read_latency_0\n')

    baseline_lat = None
    best = None
    for k in ks:
        label = f'k{k}_{args.dur}'
        stats_rel = f'stats/kcal/{label}.csv'
        stats_abs = os.path.join('sst_dram_si', stats_rel)
        log_path  = f'sst_output_data/{label}.log'
        updates = {
            'sim_time': args.dur,
            'gas_enable': True,
            'scheme1_enable': False,
            'gas_window_auto': True,
            'row_window_enable': False,
            'gap_merge_k_bytes': k,
            'burst_bytes_max': args.lmax,
            'gas_sort_policy': args.sort,
            'apply_acc_enable': 0,
        }
        run_one(args.cfg, updates, stats_rel, log_path)
        met = derive(stats_abs, log_path)
        with open(summary_path,'a') as f:
            f.write(f"{k},{met.get('stats_csv','')},{met.get('unique_reads','')},{met.get('unique_bytes','')},{met.get('bursts','')},{met.get('payload','')},{met.get('avg_burst_bytes','')},{met.get('req_bytes','')},{met.get('total_mib','')},{met.get('reqs_per_mib','')},{met.get('rowwin_triggers','')},{met.get('rowwin_bytes','')},{met.get('rowwin_share','')},{met.get('avg_read_latency_0','')}\n")
        lat = float(met.get('avg_read_latency_0','0') or 0)
        reqs_mib = float(met.get('reqs_per_mib','0') or 0)
        if baseline_lat is None and k==0:
            baseline_lat = lat
        ok = (baseline_lat is None) or (lat <= baseline_lat + args.lat_tol)
        if ok:
            if best is None or reqs_mib < best[0]:
                best = (reqs_mib, k, lat)

    if best:
        reco = {
            'k_recommended': best[1],
            'reqs_per_mib': best[0],
            'avg_read_latency_0': best[2],
            'baseline_latency_0': baseline_lat,
            'dur': args.dur,
            'candidates': ks,
        }
        outj = summary_path.replace('.csv','.json')
        json.dump(reco, open(outj,'w'), indent=2)
        print(f"Recommended k={best[1]} (reqs/MiB={best[0]:.2f}, lat={best[2]:.2f}ns); baseline_lat={baseline_lat}")
        print(f"Summary: {summary_path}\nReco: {outj}")
    else:
        print(f"No acceptable k found within latency tolerance; see {summary_path}")

if __name__ == '__main__':
    main()

