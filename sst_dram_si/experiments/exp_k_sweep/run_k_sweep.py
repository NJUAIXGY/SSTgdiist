#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
exp_k_sweep: GAP合并阈值k的批量实验脚本

功能
- 对 DRAM 配置网格 × k 值集合 批量运行单PE仿真
- 为每次运行独立指定 stats_csv 与 tee 的 stdout 日志，解析并生成汇总CSV
- 可选调用 MemKCalBench 微基准，输出 bench_results.csv 并汇总（骨架）

用法（示例）
  python3 run_k_sweep.py \
    --cfg sst_dram_si/configs/ramulator2_ddr4_openrow.cfg \
    --cfg sst_dram_si/configs/ramulator2_hbm2.cfg \
    --k_list 512,1024,2048,4096,8192 \
    --dur 100us \
    --rowwin_bytes 0 --rowwin_timeout 0 \
    --out_dir sst_dram_si/experiments/exp_k_sweep/runs

说明
- 该脚本会临时修改 sst_dram_si/local_run_config.json，运行完成后恢复原状。
- 解析项目：
  * Ramulator2日志：num_read_reqs_0, avg_read_latency_0, row_hits/row_misses/row_conflicts
  * Stats CSV：gas_unique_reads_total, gas_unique_bytes_total, gas_total_bursts, gas_total_payload_bytes
  * 派生：reqs_per_mib, avg_burst_bytes
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SDIR = os.path.dirname(os.path.abspath(__file__))
DRAM_SI_DIR = os.path.join(REPO_ROOT, 'sst_dram_si')
CFG_JSON_PATH = os.path.join(DRAM_SI_DIR, 'local_run_config.json')
SST_BIN = os.path.join(REPO_ROOT, 'sst')  # 项目根的 ./sst 包装器
TEST_SCRIPT = os.path.join(DRAM_SI_DIR, 'test_dram_si_single_pe.py')


def load_cfg():
    with open(CFG_JSON_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_cfg(cfg):
    with open(CFG_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def run_once(dram_cfg_file: str, k_bytes: int, sim_time: str, rowwin_bytes: int, rowwin_timeout_ns: int,
             out_dir: str, tag: str):
    """执行一次仿真，返回统计的字典。"""
    os.makedirs(out_dir, exist_ok=True)
    stats_csv = os.path.join(out_dir, f"stats_{tag}.csv")
    raw_log  = os.path.join(out_dir, f"ramu_{tag}.log")

    # 备份配置并写入临时参数
    orig = load_cfg()
    try:
        cfg = dict(orig)
        # 基本运行参数
        cfg['sim_time'] = sim_time
        # 保证 GAS 开启 + window 模式
        cfg['gas_enable'] = True
        cfg['gas_window_auto'] = True
        # k 与 Lmax
        cfg['gap_merge_k_bytes'] = int(k_bytes)
        cfg['burst_bytes_max'] = int(cfg.get('burst_bytes_max', 65536))
        # 行窗口
        cfg['row_window_enable'] = 1 if rowwin_bytes > 0 or rowwin_timeout_ns > 0 else 0
        cfg['row_window_bytes'] = int(rowwin_bytes)
        cfg['row_window_timeout_ns'] = int(rowwin_timeout_ns)
        # 绑定 DRAM 配置文件
        cfg['ramulator2_config_file'] = dram_cfg_file
        # stats 路径相对/绝对均可，脚本侧有重定向保护
        cfg['stats_csv'] = stats_csv
        # 可选：关掉窗口CSV，避免大量写入
        cfg['window_stats_enable'] = cfg.get('window_stats_enable', False)
        # 阶段事件可按需开启
        cfg['stage_events_csv'] = cfg.get('stage_events_csv', '')

        save_cfg(cfg)

        # 运行 SST，tee 出 stdout 以供 Ramulator2 解析
        cmd = [SST_BIN, TEST_SCRIPT]
        with open(raw_log, 'w', encoding='utf-8') as logf:
            p = subprocess.run(cmd, cwd=REPO_ROOT, stdout=logf, stderr=subprocess.STDOUT, check=False)
            rc = p.returncode
        if rc != 0:
            return {
                'ok': False,
                'reason': f'sst return code={rc}',
                'stats_csv': stats_csv,
                'raw_log': raw_log,
            }
    finally:
        # 恢复配置
        save_cfg(orig)

    stats = parse_stats_csv(stats_csv)
    back = parse_ramulator_log(raw_log)
    # 派生
    unique_bytes = stats.get('gas_unique_bytes_total', 0)
    unique_reads = stats.get('gas_unique_reads_total', 0)
    bursts = stats.get('gas_total_bursts', 0)
    num_read_reqs = back.get('num_read_reqs_0', 0)
    avg_read_latency = back.get('avg_read_latency_0', 0.0)
    mib = unique_bytes / (1024.0 * 1024.0) if unique_bytes else 0.0
    reqs_per_mib = (num_read_reqs / mib) if mib > 0 else 0.0
    avg_burst_bytes = (unique_bytes / unique_reads) if unique_reads else 0.0
    return {
        'ok': True,
        'stats_csv': stats_csv,
        'raw_log': raw_log,
        'unique_bytes': unique_bytes,
        'unique_reads': unique_reads,
        'bursts': bursts,
        'num_read_reqs': num_read_reqs,
        'avg_read_latency_0': avg_read_latency,
        'reqs_per_mib': reqs_per_mib,
        'avg_burst_bytes': avg_burst_bytes,
        'row_hits_0': back.get('row_hits_0', 0),
        'row_misses_0': back.get('row_misses_0', 0),
        'row_conflicts_0': back.get('row_conflicts_0', 0),
    }


def parse_stats_csv(path: str):
    d = {}
    if not os.path.exists(path):
        return d
    try:
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('ComponentName'):
                    continue
                # 目标：匹配 multicore_pe_0,gas_unique_bytes_total 这类行
                parts = line.split(',')
                if len(parts) < 6:
                    continue
                comp = parts[0].strip()
                stat = parts[1].strip()
                # Sum.u64 在第 10 列（依统计类型有差异）；稳妥地正则提取 Sum 值
                # 示例：...,Sum.u64,32787,... 或 ...,Sum.f64,0.000000,...
                m = re.search(r",Sum\.(?:u64|f64),([^,]+)", line)
                if not m:
                    continue
                try:
                    val = float(m.group(1))
                except Exception:
                    continue
                key = f"{comp}:{stat}"
                d[key] = val
                # 也记录简短键
                if comp.startswith('multicore_pe_0'):
                    d[stat] = val
    except Exception:
        pass
    return d


def parse_ramulator_log(path: str):
    d = {}
    if not os.path.exists(path):
        return d
    pat_map = {
        'num_read_reqs_0': r"num_read_reqs_0:\s*(\d+)",
        'avg_read_latency_0': r"avg_read_latency_0:\s*([0-9.]+)",
        'row_hits_0': r"row_hits_0:\s*(\d+)",
        'row_misses_0': r"row_misses_0:\s*(\d+)",
        'row_conflicts_0': r"row_conflicts_0:\s*(\d+)",
    }
    txt = ''
    try:
        with open(path, 'r', encoding='utf-8') as f:
            txt = f.read()
    except Exception:
        return d
    for k, pat in pat_map.items():
        m = re.search(pat, txt)
        if m:
            try:
                d[k] = float(m.group(1)) if 'avg' in k else int(m.group(1))
            except Exception:
                pass
    return d


def write_summary(path: str, rows: list):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = [
        'ts', 'dram_cfg', 'sim_time', 'k_bytes', 'rowwin_bytes', 'rowwin_timeout_ns',
        'unique_reads', 'unique_bytes', 'bursts', 'num_read_reqs', 'avg_burst_bytes', 'reqs_per_mib', 'avg_read_latency_0',
        'row_hits_0', 'row_misses_0', 'row_conflicts_0', 'stats_csv', 'raw_log'
    ]
    with open(path, 'w', encoding='utf-8') as f:
        f.write(','.join(header) + '\n')
        for r in rows:
            vals = [
                r.get('ts',''), r.get('dram_cfg',''), r.get('sim_time',''), r.get('k_bytes',0), r.get('rowwin_bytes',0), r.get('rowwin_timeout_ns',0),
                r.get('unique_reads',0), r.get('unique_bytes',0), r.get('bursts',0), r.get('num_read_reqs',0), r.get('avg_burst_bytes',0.0), r.get('reqs_per_mib',0.0), r.get('avg_read_latency_0',0.0),
                r.get('row_hits_0',0), r.get('row_misses_0',0), r.get('row_conflicts_0',0), r.get('stats_csv',''), r.get('raw_log','')
            ]
            f.write(','.join([str(v) for v in vals]) + '\n')


def run_memkcal_bench(dram_cfg_file: str, sim_time: str, out_dir: str):
    """运行 MemKCalBench 微基准，返回 {ok, bench_csv, fit_json, k_recommended}。"""
    os.makedirs(out_dir, exist_ok=True)
    bench_csv = os.path.join(out_dir, 'bench_results.csv')
    fit_json = os.path.join(out_dir, 'k_fit_summary.json')
    env = os.environ.copy()
    env['KCAL_DUR'] = sim_time
    env['KCAL_RAMU_CFG'] = dram_cfg_file
    env['KCAL_OUT'] = bench_csv
    # 运行 bench
    cmd = [SST_BIN, os.path.join(DRAM_SI_DIR, 'test_kcal_bench.py')]
    p = subprocess.run(cmd, cwd=REPO_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    # 拟合 k_recommended（P75，最小 1024B）
    kfit_py = os.path.join(DRAM_SI_DIR, 'tools/k_from_bench.py')
    cmd2 = [sys.executable, kfit_py, '--csv', bench_csv, '--scene', 'row_hit', '--percentile', '0.75', '--min-bytes', '1024', '--dry-run', '--out', fit_json]
    p2 = subprocess.run(cmd2, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    krec = None
    try:
        import json as _j
        summ = _j.load(open(fit_json, 'r', encoding='utf-8'))
        krec = int(summ.get('k_recommended', 0))
    except Exception:
        krec = 0
    ok = (p.returncode == 0 and os.path.exists(bench_csv))
    return {'ok': ok, 'bench_csv': bench_csv, 'fit_json': fit_json, 'k_recommended': krec}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cfg', action='append', required=True, help='Ramulator2 cfg 文件路径（可多次）')
    ap.add_argument('--k_list', default='512,1024,2048,4096,8192')
    ap.add_argument('--dur', default='100us', help='仿真时间，如 100us/2ms')
    ap.add_argument('--rowwin_bytes', type=int, default=0)
    ap.add_argument('--rowwin_timeout', type=int, default=0)
    ap.add_argument('--out_dir', default=os.path.join(DRAM_SI_DIR, 'experiments/exp_k_sweep/runs'))
    args = ap.parse_args()

    k_vals = [int(x) for x in args.k_list.split(',') if x.strip()]
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    summary_rows = []

    for cfg_path in args.cfg:
        if not os.path.exists(cfg_path):
            print(f'[WARN] cfg not found: {cfg_path}', file=sys.stderr)
            continue
        cfg_name = os.path.splitext(os.path.basename(cfg_path))[0]
        out_root = os.path.join(args.out_dir, f'{cfg_name}_{ts}')
        os.makedirs(out_root, exist_ok=True)
        # 先跑微基准（一次/每个 DRAM cfg），得到 bench k_recommended（P75）
        bench = run_memkcal_bench(cfg_path, args.dur, os.path.join(out_root, 'bench'))
        if not bench.get('ok'):
            print(f"[WARN] bench failed for cfg={cfg_name}")
        for k in k_vals:
            tag = f'k{k}'
            out_dir = os.path.join(out_root, tag)
            res = run_once(
                dram_cfg_file=cfg_path,
                k_bytes=k,
                sim_time=args.dur,
                rowwin_bytes=args.rowwin_bytes,
                rowwin_timeout_ns=args.rowwin_timeout,
                out_dir=out_dir,
                tag=tag,
            )
            row = {
                'ts': ts,
                'dram_cfg': cfg_name,
                'sim_time': args.dur,
                'k_bytes': k,
                'rowwin_bytes': args.rowwin_bytes,
                'rowwin_timeout_ns': args.rowwin_timeout,
                'stats_csv': res.get('stats_csv',''),
                'raw_log': res.get('raw_log',''),
                'bench_csv': bench.get('bench_csv',''),
                'bench_fit_json': bench.get('fit_json',''),
                'bench_k_rec': bench.get('k_recommended',0),
            }
            if res.get('ok'):
                row.update({
                    'unique_reads': int(res.get('unique_reads',0)),
                    'unique_bytes': int(res.get('unique_bytes',0)),
                    'bursts': int(res.get('bursts',0)),
                    'num_read_reqs': int(res.get('num_read_reqs',0)),
                    'avg_burst_bytes': float(res.get('avg_burst_bytes',0.0)),
                    'reqs_per_mib': float(res.get('reqs_per_mib',0.0)),
                    'avg_read_latency_0': float(res.get('avg_read_latency_0',0.0)),
                    'row_hits_0': int(res.get('row_hits_0',0)),
                    'row_misses_0': int(res.get('row_misses_0',0)),
                    'row_conflicts_0': int(res.get('row_conflicts_0',0)),
                })
            summary_rows.append(row)

        # 写一份该 cfg 的汇总
        write_summary(os.path.join(out_root, f'summary_{cfg_name}.csv'), summary_rows)

    # 写总汇总
    write_summary(os.path.join(args.out_dir, f'k_sweep_summary_{ts}.csv'), summary_rows)
    print(f'[OK] sweep done. summary_dir={args.out_dir}, ts={ts}')


if __name__ == '__main__':
    main()
