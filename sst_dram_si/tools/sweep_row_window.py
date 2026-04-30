#!/usr/bin/env python3
import os, json, subprocess, argparse, shutil, time

DEF_BYTES = [16*1024, 32*1024, 64*1024]
DEF_TIMEOUT = [0, 300, 600]

def run_one(label, cfg_path, updates, out_stats, out_log):
    cfg = json.load(open(cfg_path,'r'))
    cfg.update(updates)
    # enforce outputs stay under sst_dram_si/stats
    cfg['stats_csv'] = out_stats
    open(cfg_path,'w').write(json.dumps(cfg, indent=2, ensure_ascii=False))
    logf = open(out_log,'w')
    try:
        subprocess.run(['./sst', 'sst_dram_si/test_dram_si_single_pe.py'], stdout=logf, stderr=subprocess.STDOUT, check=True)
    finally:
        logf.close()

def main():
    ap = argparse.ArgumentParser(description='Sweep row_window params and derive metrics')
    ap.add_argument('--cfg', default='sst_dram_si/local_run_config.json')
    ap.add_argument('--bytes', nargs='*', type=int)
    ap.add_argument('--timeouts', nargs='*', type=int)
    ap.add_argument('--dur', default='100us')
    args = ap.parse_args()

    bytes_list = args.bytes or DEF_BYTES
    tout_list = args.timeouts or DEF_TIMEOUT
    # stats path should be relative to sst_dram_si to let script join correctly
    os.makedirs('sst_dram_si/stats/sweeps', exist_ok=True)
    summary = os.path.join('sst_dram_si/stats/sweeps', f'summary_{args.dur}.csv')
    if not os.path.exists(summary):
        open(summary,'w').write('label,stats_csv,unique_reads,unique_bytes,bursts,payload,avg_burst_bytes,req_bytes,total_mib,reqs_per_mib,rowwin_triggers,rowwin_bytes,rowwin_share,avg_read_latency_0\n')

    # base updates for GAS
    base = {
        'sim_time': args.dur,
        'gas_enable': True,
        'scheme1_enable': False,
        'gas_window_auto': True,
        'gas_sort_policy': 'bank_row',
        'apply_acc_enable': 0,
    }

    for b in bytes_list:
        for t in tout_list:
            label = f'rowwin_b{b}_t{t}_{args.dur}'
            # Pass relative path from sst_dram_si/: 'stats/sweeps/...csv'
            stats = f'stats/sweeps/{label}.csv'
            log   = f'sst_output_data/{label}.log'
            updates = dict(base)
            updates.update({
                'row_window_enable': True,
                'row_window_bytes': b,
                'row_window_timeout_ns': t,
            })
            run_one(label, args.cfg, updates, stats, log)
            # derive
            stats_abs = os.path.join('sst_dram_si', stats)
            res = subprocess.run(['python3','sst_dram_si/tools/derive_gas_metrics.py', stats_abs, '--stdout', log], capture_output=True, text=True)
            lines = res.stdout.strip().splitlines()
            if len(lines)>=2:
                open(summary,'a').write(f'{label},'+lines[1]+'\n')

if __name__ == '__main__':
    main()
