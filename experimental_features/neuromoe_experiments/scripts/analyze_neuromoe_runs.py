#!/usr/bin/env python3
import os, csv, sys
from collections import defaultdict

RES_DIR = os.path.join(os.path.dirname(__file__), "..", "results")

files = [
    ("Sparse (edges_csv, k=4)", os.path.join(RES_DIR, "neuromoe_edges_csv_k4.csv")),
    ("Dense (weight_driven, k=0)", os.path.join(RES_DIR, "neuromoe_weight_driven_k0.csv")),
]
logs = [
    ("Sparse (edges_csv, k=4)", os.path.join(RES_DIR, "run_edges_k4.log")),
    ("Dense (weight_driven, k=0)", os.path.join(RES_DIR, "run_weight_dense.log")),
]

def load_stats(path):
    if not os.path.exists(path):
        return None
    agg = defaultdict(float)
    by_stat = defaultdict(list)
    with open(path, newline='') as f:
        r = csv.reader(f)
        header = None
        for row in r:
            if not row: continue
            if row[0].startswith('#'): continue
            if header is None:
                header = row
                # try find Sum.u64 or Sum.double
                sum_idx = None
                for name in ("Sum.u64","Sum.double","Sum"):  # robust across SST versions
                    if name in header:
                        sum_idx = header.index(name)
                        break
                # fallback to last column if not found (but warn via index=-1)
                if sum_idx is None:
                    sum_idx = -1
                continue
            try:
                comp = row[0]
                stat = row[1]
                val = float(row[sum_idx]) if sum_idx != -1 and row[sum_idx] != '' else float(row[-1])
            except Exception:
                continue
            key = f"{comp}:{stat}"
            agg[key] += val
            by_stat[stat].append(val)
    return agg, by_stat

def summarize(tag, data):
    agg, by_stat = data
    # Focus stats
    # Focus on NIC/MultiCore counters that are reliably present in our config
    focus_stats = [
        "packets_sent",
        "packets_received",
        "spikes_sent",
        "spikes_received",
        "external_spikes_sent",
        "external_spikes_received",
        "total_spikes_processed",
        "total_neurons_fired",
        "batches_sent",
    ]
    print(f"\n=== {tag} ===")
    for s in focus_stats:
        # aggregate across all components
        total = 0.0
        for k,v in agg.items():
            if k.endswith(":"+s): total += v
        print(f"{s:32s}: {total}")

def parse_logs(path):
    if not os.path.exists(path):
        return None
    totals = {"send_pkts":0, "recv_pkts":0}
    # Simple Chinese labels as in logs: "发送包:", "接收包:" under SnnNIC final summary
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line=line.strip()
            if line.startswith('SnnNIC[') and '最终统计' in line:
                # next lines have send/recv packets
                pass
            if line.startswith('发送包:'):
                try:
                    totals["send_pkts"] += int(line.split(':',1)[1].strip())
                except: pass
            if line.startswith('接收包:'):
                try:
                    totals["recv_pkts"] += int(line.split(':',1)[1].strip())
                except: pass
    return totals

def main():
    results = []
    for tag, path in files:
        stats = load_stats(path)
        results.append((tag, stats))
    # Fallback to logs if CSV empty
    summaries = []
    for i,(tag, st) in enumerate(results):
        ok = False
        if st is not None:
            agg, _ = st
            ok = any('router.packet_count' in k or 'total_network_spikes_sent' in k for k in agg)
        if not ok:
            log_path = logs[i][1]
            log_s = parse_logs(log_path)
            summaries.append((tag, st, log_s))
        else:
            summaries.append((tag, st, None))
    # Print report
    print("NeuroMoE Sparse vs Dense — Preliminary Compare")
    print(f"Results dir: {RES_DIR}")
    for (tag, stats, log_s) in summaries:
        if stats is None:
            print(f"\n=== {tag} ===\n(no stats file)")
            continue
        summarize(tag, stats)
        if log_s:
            print(f"  (log) send_pkts: {log_s['send_pkts']}, recv_pkts: {log_s['recv_pkts']}")

    # Simple ratio if both present
    if all(stats is not None for _,stats,_ in summaries):
        print("\n=== Ratios (Sparse/Dense) on key counters ===")
        dens = summaries[1][1][0]  # agg map
        spars = summaries[0][1][0]
        def total_of(stat, agg):
            return sum(v for k,v in agg.items() if k.endswith(":"+stat))
        for s in ["packets_sent", "packets_received", "spikes_sent", "external_spikes_sent"]:
            a = total_of(s, spars); b = total_of(s, dens)
            ratio = (a / b) if b > 0 else float('inf')
            print(f"{s:32s}: {ratio:.3f}")

    # Log-level ratio on packets
    if summaries[0][2] and summaries[1][2]:
        a = summaries[0][2]['send_pkts']; b = summaries[1][2]['send_pkts']
        ratio = (a / b) if b>0 else float('inf')
        print(f"\n(Log) send_pkts Sparse/Dense ratio: {ratio:.3f}")

if __name__ == "__main__":
    main()
