#!/usr/bin/env python3
"""
Generate a simple GAS stage schedule CSV with Begin/End Apply/Scatter events and sim_time_ns.
This is useful when SnnDL stage-events CSV is incomplete on short runs.

Output columns: seq,event,sim_time_ns,acc_updates,posts_touched,hwm_bytes,spill_records,spilled_bytes,spikes_emitted

Example:
  python3 sst_dram_si/tools/make_stage_schedule.py \
    --windows 50 --gather-ns 200 --apply-ns 40 --scatter-ns 40 \
    --start-ns 0 --out sst_dram_si/analysis/gas_stage_sched.csv
"""
import argparse, csv, os

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--windows', type=int, default=50)
    ap.add_argument('--gather-ns', type=int, default=200)
    ap.add_argument('--apply-ns', type=int, default=40)
    ap.add_argument('--scatter-ns', type=int, default=40)
    ap.add_argument('--start-ns', type=int, default=0)
    ap.add_argument('--gap-ns', type=int, default=0, help='optional gap between windows')
    ap.add_argument('--out', default='sst_dram_si/analysis/gas_stage_sched.csv')
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    t = args.start_ns
    rows = []
    for w in range(1, args.windows+1):
        # BeginGather at window start
        rows.append({'seq': w, 'event': 'BeginGather', 'sim_time_ns': t,
                     'acc_updates': 0, 'posts_touched': 0, 'hwm_bytes': 0,
                     'spill_records': 0, 'spilled_bytes': 0, 'spikes_emitted': 0})
        # BeginApply at end of Gather
        t += args.gather_ns
        rows.append({'seq': w, 'event': 'BeginApply', 'sim_time_ns': t,
                     'acc_updates': 0, 'posts_touched': 0, 'hwm_bytes': 0,
                     'spill_records': 0, 'spilled_bytes': 0, 'spikes_emitted': 0})
        # EndApply
        t += args.apply_ns
        rows.append({'seq': w, 'event': 'EndApply', 'sim_time_ns': t,
                     'acc_updates': 0, 'posts_touched': 0, 'hwm_bytes': 0,
                     'spill_records': 0, 'spilled_bytes': 0, 'spikes_emitted': 0})
        # BeginScatter
        rows.append({'seq': w, 'event': 'BeginScatter', 'sim_time_ns': t,
                     'acc_updates': 0, 'posts_touched': 0, 'hwm_bytes': 0,
                     'spill_records': 0, 'spilled_bytes': 0, 'spikes_emitted': 0})
        # EndScatter
        t += args.scatter_ns
        rows.append({'seq': w, 'event': 'EndScatter', 'sim_time_ns': t,
                     'acc_updates': 0, 'posts_touched': 0, 'hwm_bytes': 0,
                     'spill_records': 0, 'spilled_bytes': 0, 'spikes_emitted': 0})
        t += args.gap_ns

    fields = ['seq','event','sim_time_ns','acc_updates','posts_touched','hwm_bytes','spill_records','spilled_bytes','spikes_emitted']
    with open(args.out, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows: w.writerow(r)
    print('Wrote', args.out, 'rows=', len(rows))

if __name__ == '__main__':
    main()
