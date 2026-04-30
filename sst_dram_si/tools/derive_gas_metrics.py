#!/usr/bin/env python3
import csv, sys, os, argparse, re

def read_csv_rows(path):
    rows = []
    with open(path, 'r', encoding='utf-8') as f:
        r = csv.reader(f)
        header = next(r)
        for row in r:
            rows.append(row)
    return rows

def pick_sum(rows, name):
    s = 0
    for row in rows:
        if len(row) < 11: continue
        if row[0] == 'multicore_pe_0' and row[1] == name and row[3] in ('Accumulator','accumulator','Sum.u64','Histogram'):
            try:
                s = int(row[10])
            except: pass
    return s

def main():
    ap = argparse.ArgumentParser(description='Derive GAS metrics from stats CSV and optional controller stdout')
    ap.add_argument('stats_csv', help='path to stats csv (e.g., sst_dram_si/stats/gas_*.csv)')
    ap.add_argument('--stdout', help='path to ramulator2 stdout log (optional)')
    args = ap.parse_args()

    rows = read_csv_rows(args.stats_csv)
    unique_reads = pick_sum(rows, 'gas_unique_reads_total')
    unique_bytes = pick_sum(rows, 'gas_unique_bytes_total')
    bursts = pick_sum(rows, 'gas_total_bursts')
    payload = pick_sum(rows, 'gas_total_payload_bytes')
    req_bytes = pick_sum(rows, 'mem_req_size_bytes')

    total_mib = req_bytes / (1024.0*1024.0) if req_bytes else 0.0
    reqs_per_mib = (unique_reads / total_mib) if total_mib>0 else 0.0
    avg_burst_bytes = (payload / bursts) if bursts>0 else 0.0
    rowwin_trig = pick_sum(rows, 'gas_row_window_triggers_total')
    rowwin_bytes = pick_sum(rows, 'gas_row_window_bytes_total')
    rowwin_share = (rowwin_bytes / unique_bytes) if unique_bytes>0 else 0.0

    avg_latency = None
    energy_total = None
    energy_cmd = None
    energy_bg = None
    sim_time_s = None
    if args.stdout and os.path.exists(args.stdout):
        txt = open(args.stdout,'r',encoding='utf-8',errors='ignore').read()
        m = re.search(r'avg_read_latency_0:\s*([0-9\.]+)', txt)
        if m: avg_latency = float(m.group(1))
        # Ramulator2 (drampower_enable=1) energy stats in DRAM section
        m = re.search(r'\btotal_energy:\s*([0-9\.]+)', txt)
        if m: energy_total = float(m.group(1))
        m = re.search(r'\btotal_cmd_energy:\s*([0-9\.]+)', txt)
        if m: energy_cmd = float(m.group(1))
        m = re.search(r'\btotal_background_energy:\s*([0-9\.]+)', txt)
        if m: energy_bg = float(m.group(1))
        # Simulation time (e.g., "Simulation is complete, simulated time: 100 us")
        m = re.search(r'simulated time:\s*([0-9\.]+)\s*(ps|ns|us|ms|s)', txt)
        if m:
            val = float(m.group(1)); unit = m.group(2)
            scale = {'ps':1e-12,'ns':1e-9,'us':1e-6,'ms':1e-3,'s':1.0}[unit]
            sim_time_s = val * scale

    print('stats_csv,unique_reads,unique_bytes,bursts,payload,avg_burst_bytes,req_bytes,total_mib,reqs_per_mib,rowwin_triggers,rowwin_bytes,rowwin_share,avg_read_latency_0,energy_total,energy_cmd,energy_bg,sim_time_s,avg_power')
    print(','.join([
        args.stats_csv,
        str(unique_reads), str(unique_bytes), str(bursts), str(payload), f"{avg_burst_bytes:.2f}",
        str(req_bytes), f"{total_mib:.6f}", f"{reqs_per_mib:.2f}",
        str(rowwin_trig), str(rowwin_bytes), f"{rowwin_share:.4f}",
        (f"{avg_latency:.2f}" if avg_latency is not None else ''),
        (f"{energy_total:.6f}" if energy_total is not None else ''),
        (f"{energy_cmd:.6f}" if energy_cmd is not None else ''),
        (f"{energy_bg:.6f}" if energy_bg is not None else ''),
        (f"{sim_time_s:.9f}" if sim_time_s is not None else ''),
        (f"{(energy_total/sim_time_s):.6f}" if (energy_total is not None and sim_time_s) else '')
    ]))

if __name__ == '__main__':
    main()
