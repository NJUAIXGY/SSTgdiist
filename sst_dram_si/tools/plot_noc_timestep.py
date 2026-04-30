#!/usr/bin/env python3

"""
plot_noc_timestep.py

从 sst_dram_si/analysis/noc_timestep_stats.csv 粗解析 NoC 单步实验的统计，
输出便于报告的聚合表（包数/注入/接收），并留出 P99 延迟后续补位。

使用：
  python3 sst_dram_si/tools/plot_noc_timestep.py \
    --csv sst_dram_si/analysis/noc_timestep_stats.csv --out sst_dram_si/analysis/noc_timestep_summary.csv
"""

import csv
import argparse
from collections import defaultdict


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default='sst_dram_si/analysis/noc_timestep_stats.csv')
    ap.add_argument('--out', default='sst_dram_si/analysis/noc_timestep_summary.csv')
    return ap.parse_args()


def main():
    args = parse_args()

    # 读取 SST CSV，找出关键信息：
    #  - SnnDL.SnnNIC: packets_sent/packets_received/spikes_sent/spikes_received
    #  - merlin.hr_router: router.packet_count/router.network_load
    #  - SnnDL.MultiCorePE: external_spikes_sent/external_spikes_received
    nic_sent = 0
    nic_recv = 0
    spike_sent = 0
    spike_recv = 0

    router_packets = 0
    router_load_sum = 0
    router_load_count = 0

    pe_ext_sent = 0
    pe_ext_recv = 0

    with open(args.csv, 'r', newline='') as f:
        reader = csv.reader(f)
        # 粗口径：按名字匹配（SST CSV 列布局在工程内统一）
        for row in reader:
            if not row: continue
            # 过滤非数据行
            if len(row) < 4: continue
            comp, statname, val = row[0], row[1], row[-1]
            try:
                x = float(val)
            except Exception:
                continue

            if 'SnnNIC' in comp:
                if statname.endswith('packets_sent'):
                    nic_sent += x
                elif statname.endswith('packets_received'):
                    nic_recv += x
                elif statname.endswith('spikes_sent'):
                    spike_sent += x
                elif statname.endswith('spikes_received'):
                    spike_recv += x
            elif 'merlin.hr_router' in comp or 'router_' in comp:
                if 'router.packet_count' in statname:
                    router_packets += x
                elif 'router.network_load' in statname:
                    router_load_sum += x
                    router_load_count += 1
            elif 'MultiCorePE' in comp:
                if statname.endswith('external_spikes_sent'):
                    pe_ext_sent += x
                elif statname.endswith('external_spikes_received'):
                    pe_ext_recv += x

    avg_router_load = (router_load_sum / router_load_count) if router_load_count else 0.0

    with open(args.out, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['metric', 'value'])
        w.writerow(['nic_packets_sent', int(nic_sent)])
        w.writerow(['nic_packets_received', int(nic_recv)])
        w.writerow(['nic_spikes_sent', int(spike_sent)])
        w.writerow(['nic_spikes_received', int(spike_recv)])
        w.writerow(['router_packets_total', int(router_packets)])
        w.writerow(['router_network_load_avg', avg_router_load])
        w.writerow(['pe_external_spikes_sent', int(pe_ext_sent)])
        w.writerow(['pe_external_spikes_received', int(pe_ext_recv)])
        # 占位：P50/P99 时延（需要下一轮在 NIC/核心层面记录时间戳）
        w.writerow(['latency_p50_ns', 'NA'])
        w.writerow(['latency_p99_ns', 'NA'])

    print(f"写入汇总：{args.out}")


if __name__ == '__main__':
    main()

