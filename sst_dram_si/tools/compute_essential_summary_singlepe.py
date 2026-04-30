#!/usr/bin/env python3
"""
汇总单PE运行的核心指标到 essential_summary.json（位于 --run-dir）。
输入：
  --run-dir      运行目录（必须存在），脚本默认读取：
                  - local_run_config.json（模型规模、sim_time）
                  - dram_si_stats.csv（SST统计）
                  - stage_events_db_*.csv（若存在则汇总G/A/S窗口时长）
                  - last_run.time（若存在则读取 WALL/USER/SYS/MAXRSS）
输出：
  --out          输出 JSON 路径（默认：<run-dir>/essential_summary.json）

注意：单PE无网络，communication 字段仅统计 spikes_total=行数近似值时可扩展；当前保留空或None。
"""
from __future__ import annotations
import argparse, os, json, csv, math, re

def estimate_bytes_from_requests(cfg: dict, reqs: int) -> int:
    try:
        ls = int(cfg.get('line_size_bytes', 64) or 64)
    except Exception:
        ls = 64
    return int(reqs) * int(ls)


def read_json(p):
    try:
        return json.load(open(p,'r',encoding='utf-8'))
    except Exception:
        return {}


def parse_mem_size_bytes(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    txt = str(value).strip()
    if not txt:
        return None
    m = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]*)', txt)
    if not m:
        return None
    num = float(m.group(1))
    unit = (m.group(2) or '').lower()
    scale = {
        '': 1,
        'b': 1,
        'k': 1024,
        'kb': 1024,
        'kib': 1024,
        'm': 1024 ** 2,
        'mb': 1024 ** 2,
        'mib': 1024 ** 2,
        'g': 1024 ** 3,
        'gb': 1024 ** 3,
        'gib': 1024 ** 3,
        't': 1024 ** 4,
        'tb': 1024 ** 4,
        'tib': 1024 ** 4,
    }.get(unit)
    if scale is None:
        return None
    return int(num * scale)


def pick_config_value(*values):
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value == '':
            continue
        return value
    return None


def build_runtime_config(raw_cfg, effective_cfg):
    merged_cfg = dict(raw_cfg or {})
    if isinstance(effective_cfg, dict):
        merged_cfg.update(effective_cfg)
    mc_configured = pick_config_value(
        effective_cfg.get('mc_mem_size_configured') if isinstance(effective_cfg, dict) else None,
        raw_cfg.get('mc_mem_size') if isinstance(raw_cfg, dict) else None,
    )
    mc_effective = pick_config_value(
        effective_cfg.get('mc_mem_size_effective') if isinstance(effective_cfg, dict) else None,
        effective_cfg.get('mc_mem_size') if isinstance(effective_cfg, dict) else None,
        merged_cfg.get('mc_mem_size'),
        mc_configured,
    )
    mc_configured_bytes = pick_config_value(
        effective_cfg.get('mc_mem_size_configured_bytes') if isinstance(effective_cfg, dict) else None,
        parse_mem_size_bytes(mc_configured),
    )
    mc_effective_bytes = pick_config_value(
        effective_cfg.get('mc_mem_size_effective_bytes') if isinstance(effective_cfg, dict) else None,
        parse_mem_size_bytes(mc_effective),
        mc_configured_bytes,
    )
    mc_auto_expanded = pick_config_value(
        effective_cfg.get('mc_mem_size_auto_expanded') if isinstance(effective_cfg, dict) else None,
        bool(
            mc_configured is not None
            and mc_effective is not None
            and str(mc_configured) != str(mc_effective)
        ),
    )
    dataset_configured = pick_config_value(
        effective_cfg.get('dataset_path_configured') if isinstance(effective_cfg, dict) else None,
        raw_cfg.get('dataset_path') if isinstance(raw_cfg, dict) else None,
    )
    dataset_effective = pick_config_value(
        effective_cfg.get('dataset_path_effective') if isinstance(effective_cfg, dict) else None,
        effective_cfg.get('dataset_path') if isinstance(effective_cfg, dict) else None,
        merged_cfg.get('dataset_path'),
        dataset_configured,
    )
    return {
        'mem_backend': pick_config_value(
            merged_cfg.get('mem_backend'),
            raw_cfg.get('mem_backend') if isinstance(raw_cfg, dict) else None,
        ),
        'ramulator2_config_file': pick_config_value(
            merged_cfg.get('ramulator2_config_file'),
            raw_cfg.get('ramulator2_config_file') if isinstance(raw_cfg, dict) else None,
        ),
        'mc_mem_size': {
            'configured': mc_configured,
            'effective': mc_effective,
            'configured_bytes': mc_configured_bytes,
            'effective_bytes': mc_effective_bytes,
            'auto_expanded': bool(mc_auto_expanded),
        },
        'dataset_path': {
            'configured': dataset_configured,
            'effective': dataset_effective,
        },
    }

def parse_stats_csv(path):
    rows=[]
    if not (path and os.path.exists(path)): return rows
    with open(path,newline='') as f:
        rd=csv.reader(f)
        try: header=next(rd)
        except StopIteration: return rows
        # Map header indices (robust across SST versions)
        def idx(name):
            try:
                return header.index(name)
            except ValueError:
                return -1
        i_comp = idx('ComponentName') if 'ComponentName' in header else 0
        i_stat = idx('StatisticName') if 'StatisticName' in header else 1
        i_sim  = idx('SimTime') if 'SimTime' in header else -1
        i_sum64 = idx('Sum.u64')
        i_sumf  = idx('Sum.f64')
        i_count = idx('Count.u64') if 'Count.u64' in header else idx('Count')
        for r in rd:
            if not r or len(r)<=max(i_comp,i_stat,0):
                continue
            comp = r[i_comp] if i_comp>=0 and i_comp < len(r) else r[0]
            stat = r[i_stat] if i_stat>=0 and i_stat < len(r) else r[1]
            sim  = r[i_sim]  if i_sim>=0 and i_sim  < len(r) else ''
            s = ''
            if i_sum64>=0 and i_sum64 < len(r) and r[i_sum64] != '':
                s = r[i_sum64]
            elif i_sumf>=0 and i_sumf < len(r) and r[i_sumf] != '':
                s = r[i_sumf]
            elif i_count>=0 and i_count < len(r) and r[i_count] != '':
                s = r[i_count]
            rows.append({'component':comp, 'stat':stat, 'sim':sim, 'sum':s})
    return rows

def get_hist_num_items_binned(path, comp_prefixes, stat_name):
    """Return NumItemsBinned.u64 for the first histogram row matching component prefixes and stat name.
    Falls back to NumItemsCollected.u64 when binned not available. Returns 0 when missing.
    """
    if not (path and os.path.exists(path)):
        return 0
    with open(path, newline='') as f:
        rd = csv.reader(f)
        try:
            header = next(rd)
        except StopIteration:
            return 0
        def idx(name):
            try:
                return header.index(name)
            except ValueError:
                return -1
        i_comp = idx('ComponentName')
        i_stat = idx('StatisticName')
        i_binned = idx('NumItemsBinned.u64')
        i_collected = idx('NumItemsCollected.u64')
        for r in rd:
            if not r: continue
            c = r[i_comp] if (i_comp>=0 and i_comp < len(r)) else ''
            s = r[i_stat] if (i_stat>=0 and i_stat < len(r)) else ''
            if not any(c.startswith(p) for p in comp_prefixes):
                continue
            if s != stat_name:
                continue
            # Prefer binned; fallback collected
            try:
                if i_binned>=0 and i_binned < len(r) and r[i_binned] != '':
                    return int(r[i_binned])
                if i_collected>=0 and i_collected < len(r) and r[i_collected] != '':
                    return int(r[i_collected])
            except Exception:
                return 0
    return 0

def sum_stat(rows, comp_prefixes, stat_name):
    total=0
    for rr in rows:
        c=(rr['component'] or '').strip()
        s=(rr['stat'] or '').strip()
        if any(c.startswith(p) for p in comp_prefixes) and s==stat_name:
            try:
                total+=int(rr['sum'])
            except Exception:
                try: total+=int(float(rr['sum']))
                except Exception: pass
    return total

def sum_stat_any(rows, stat_name):
    """Aggregate a statistic across all components (mesh-style source alignment)."""
    total = 0.0
    for rr in rows:
        sname = (rr.get('stat') or '').strip()
        if sname != stat_name:
            continue
        val = (rr.get('sum') or '').strip()
        if not val:
            continue
        try:
            total += int(val)
        except Exception:
            try:
                total += float(val)
            except Exception:
                continue
    return total

def parse_stage_events(path):
    if not (path and os.path.exists(path)): return None
    by={}
    first_bg=None; last_es=None
    with open(path,newline='') as f:
        rd=csv.DictReader(f)
        for r in rd:
            try:
                seq=int(r.get('seq','0'))
                evt=(r.get('event','') or '').strip()
                ts=int(r.get('sim_time_ns','0'))
            except Exception:
                continue
            by.setdefault(seq,[]).append((evt,ts))
            if evt=='BeginGather':
                if first_bg is None or ts < first_bg: first_bg = ts
            if evt=='EndScatter':
                if last_es is None or ts > last_es: last_es = ts
    wins=[]
    for seq,evs in by.items():
        evs.sort(key=lambda x:x[1])
        t={'BeginGather':None,'BeginApply':None,'EndApply':None,'BeginScatter':None,'EndScatter':None}
        for e,ts in evs:
            if e in t and t[e] is None: t[e]=ts
        bg=t['BeginGather'] if t['BeginGather'] is not None else (evs[0][1] if evs else None)
        ga=t['BeginApply']; ea=t['EndApply']; bs=t['BeginScatter']; es=t['EndScatter']
        if bg is None or es is None: continue
        g=(ga-bg) if (ga is not None and ga>=bg) else 0
        a=(ea-ga) if (ea is not None and ea>=ga) else 0
        s=(es-bs) if (bs is not None and es>=bs) else 0
        tot=(es-bg) if es>=bg else (g+a+s)
        wins.append({'g':g,'a':a,'s':s,'t':tot})
    if not wins: return None
    def pct(v,p):
        if not v: return 0
        v=sorted(v); k=max(0,min(len(v)-1,math.ceil(p*len(v))-1)); return v[k]
    G=[w['g'] for w in wins]; A=[w['a'] for w in wins]; S=[w['s'] for w in wins]; T=[w['t'] for w in wins]
    return {
        'windows': len(wins),
        'units': 'ns',
        'gather': {'avg': int(sum(G)/len(G)) if G else 0, 'p95': int(pct(G,0.95)), 'p99': int(pct(G,0.99))},
        'apply':  {'avg': int(sum(A)/len(A)) if A else 0, 'p95': int(pct(A,0.95)), 'p99': int(pct(A,0.99))},
        'scatter':{'avg': int(sum(S)/len(S)) if S else 0, 'p95': int(pct(S,0.95)), 'p99': int(pct(S,0.99))},
        'total':  {'avg': int(sum(T)/len(T)) if T else 0, 'p95': int(pct(T,0.95)), 'p99': int(pct(T,0.99))},
        'sim_time_ns_observed': (int(last_es-first_bg) if (first_bg is not None and last_es is not None and last_es>=first_bg) else None)
    }

def parse_pe_stage_events(path):
    """Parse PE-level stage file pe_stage_events_db.csv and compute g/a/s/total distributions.
    Returns (ev_dict, sim_time_ns_observed) or (None, None).
    """
    if not (path and os.path.exists(path)):
        return None, None
    import csv, math
    G=[];A=[];S=[];T=[]
    first_bg=None; last_es=None
    try:
        with open(path, newline='') as f:
            rd=csv.DictReader(f)
            for r in rd:
                try:
                    bg=int(r.get('bg_ns','0') or 0)
                    ga=int(r.get('ga_ns','0') or 0)
                    bs=int(r.get('bs_ns','0') or 0)
                    es=int(r.get('es_ns','0') or 0)
                except Exception:
                    continue
                if first_bg is None or bg<first_bg: first_bg=bg
                if last_es is None or es>last_es: last_es=es
                g = ga-bg if (ga and bg and ga>=bg) else 0
                a = bs-ga if (bs and ga and bs>=ga) else 0
                s = es-bs if (es and bs and es>=bs) else 0
                t = es-bg if (es and bg and es>=bg) else 0
                G.append(g); A.append(a); S.append(s); T.append(t)
        if not G:
            return None, None
        def pct(v,p):
            if not v: return 0
            v=sorted(v); k=max(0,min(len(v)-1,math.ceil(p*len(v))-1)); return v[k]
        ev={'windows': len(G), 'units':'ns',
            'gather': {'avg': int(sum(G)/len(G)), 'p95': int(pct(G,0.95)), 'p99': int(pct(G,0.99))},
            'apply':  {'avg': int(sum(A)/len(A)), 'p95': int(pct(A,0.95)), 'p99': int(pct(A,0.99))},
            'scatter':{'avg': int(sum(S)/len(S)), 'p95': int(pct(S,0.95)), 'p99': int(pct(S,0.99))},
            'total':  {'avg': int(sum(T)/len(T)), 'p95': int(pct(T,0.95)), 'p99': int(pct(T,0.99))}}
        sim_obs = (int(last_es-first_bg) if (first_bg is not None and last_es is not None and last_es>=first_bg) else None)
        return ev, sim_obs
    except Exception:
        return None, None

def sum_stage_spikes_emitted(path):
    if not (path and os.path.exists(path)): return 0
    try:
        with open(path, newline='') as f:
            rd = csv.DictReader(f)
            s=0
            for r in rd:
                if (r.get('event','') or '').strip()=='EndScatter':
                    try:
                        s += int(r.get('spikes_emitted','0') or 0)
                    except Exception:
                        pass
            return s
    except Exception:
        return 0

def parse_pe_window_spikes(path):
    """Parse PE-level per-window spikes CSV: seq,pe_spikes_emitted.
    Returns list of ints (spikes per window in seq order) or None.
    """
    import csv
    if not (path and os.path.exists(path)):
        return None
    rows = []
    try:
        with open(path, newline='') as f:
            rd = csv.DictReader(f)
            buf = []
            for r in rd:
                try:
                    seq = int(r.get('seq','0'))
                    cnt = int(r.get('pe_spikes_emitted','0') or 0)
                except Exception:
                    continue
                buf.append((seq,cnt))
            if not buf:
                return []
            buf.sort(key=lambda x:x[0])
            rows = [c for _,c in buf]
    except Exception:
        return None
    return rows

def parse_time_file(path):
    if not (path and os.path.exists(path)):
        return None
    txt = open(path, 'r').read()
    out = {}
    # Accept legacy format (WALL/USER/SYS/MAXRSS) or POSIX 'time -p' output (real/user/sys)
    m = re.search(r'WALL=([^\n\s]+)', txt)
    if m:
        out['wall'] = m.group(1)
    else:
        m = re.search(r'real\s+([0-9]+\.?[0-9]*)', txt)
        if m:
            out['wall'] = float(m.group(1))
    m = re.search(r'USER=([0-9]+\.?[0-9]*)', txt)
    if m:
        out['user'] = float(m.group(1))
    else:
        m = re.search(r'user\s+([0-9]+\.?[0-9]*)', txt)
        if m:
            out['user'] = float(m.group(1))
    m = re.search(r'SYS=([0-9]+\.?[0-9]*)', txt)
    if m:
        out['sys'] = float(m.group(1))
    else:
        m = re.search(r'sys\s+([0-9]+\.?[0-9]*)', txt)
        if m:
            out['sys'] = float(m.group(1))
    m = re.search(r'MAXRSS=([0-9]+)', txt)
    if m:
        out['maxrss_kb'] = int(m.group(1))
    return out if any(v is not None for v in out.values()) else None

def parse_ramulator2_requests_from_log(path):
    if not (path and os.path.exists(path)): return None
    txt=open(path,'r',encoding='utf-8',errors='ignore').read()
    m=re.search(r'total_num_read_requests:\s*([0-9]+)', txt)
    try:
        return int(m.group(1)) if m else None
    except Exception:
        return None

def parse_simplemem_requests_from_log(path):
    """Count simpleMem backend read issues from wrapper log by matching diagnostic tag.
    Returns count or 0 when not found.
    """
    if not (path and os.path.exists(path)):
        return 0
    try:
        cnt = 0
        with open(path,'r',encoding='utf-8',errors='ignore') as f:
            for line in f:
                if 'diag-simpleMem' in line and ' issue ' in line:
                    # Filter reads: simpleMem diag lines don't distinguish R/W easily; treat all as requests
                    cnt += 1
        return cnt
    except Exception:
        return 0


def build_superstep_hist(stage_path):
    """Build histogram of superstep total cycles from stage_events_db_*.csv.
    Returns: {'total_cycles': {'<cycles>': count, ...}}
    """
    import csv
    from collections import defaultdict
    if not (stage_path and os.path.exists(stage_path)):
        return {}
    events = {}
    try:
        with open(stage_path, newline='') as f:
            rd = csv.DictReader(f)
            for r in rd:
                try:
                    seq = int(r.get('seq','0'))
                    ev  = (r.get('event','') or '').strip()
                    ts  = int(r.get('sim_time_ns','0'))
                except Exception:
                    continue
                e = events.setdefault(seq, {})
                # only keep first occurrence per event per seq
                if ev and ev not in e:
                    e[ev]=ts
    except Exception:
        return {}
    hist = defaultdict(int)
    for seq, e in events.items():
        bg = e.get('BeginGather'); es = e.get('EndScatter')
        if bg is None or es is None: 
            continue
        total = es - bg
        if total < 0: 
            continue
        hist[str(int(total))] += 1
    if not hist:
        return {}
    return {'total_cycles': dict(hist)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--out', default=None)
    args=ap.parse_args()

    rd_in=os.path.abspath(args.run_dir)
    rd=rd_in
    # If run-dir is a base directory containing timestamped subdirs, pick the latest
    try:
        if os.path.isdir(rd):
            subs=[d for d in os.listdir(rd) if os.path.isdir(os.path.join(rd,d))]
            import re
            subs_ts=[d for d in subs if re.fullmatch(r"\d{8}-\d{6}", d)]
            if subs_ts:
                subs_ts.sort(reverse=True)
                rd=os.path.join(rd, subs_ts[0])
                print(f"[summary] Using latest timestamp run-dir: {rd}")
    except Exception:
        pass
    raw_cfg_path = os.path.join(rd, 'local_run_config.json')
    effective_cfg_path = os.path.join(rd, 'local_run_config.effective.json')
    cfg_raw = read_json(raw_cfg_path)
    cfg_effective = read_json(effective_cfg_path) if os.path.exists(effective_cfg_path) else {}
    cfg = dict(cfg_raw or {})
    if isinstance(cfg_effective, dict):
        cfg.update(cfg_effective)
    # Prefer run-dir stats; fallback to global sst_dram_si/stats
    stats_path=os.path.join(rd,'dram_si_stats.csv')
    if not os.path.exists(stats_path):
        # tools/.. = sst_dram_si
        _tools_dir = os.path.dirname(os.path.abspath(__file__))
        _root = os.path.dirname(_tools_dir)
        _global = os.path.join(_root,'stats','dram_si_stats.csv')
        if os.path.exists(_global):
            stats_path = _global
    # Stage events: prefer PE-level stage file; fallback to config/core stage file
    pe_stage_path=os.path.join(rd,'pe_stage_events_db.csv')
    stage_path=None
    cfg_stage = cfg.get('stage_events_csv')
    if isinstance(cfg_stage,str) and cfg_stage.strip():
        p = cfg_stage.strip()
        if not os.path.isabs(p):
            # interpret relative to sst_dram_si
            _tools_dir = os.path.dirname(os.path.abspath(__file__))
            _root = os.path.dirname(_tools_dir)
            p = os.path.join(_root, p)
        if os.path.exists(p):
            stage_path = p
    if stage_path is None:
        # pick newest stage file in run-dir
        cands=[os.path.join(rd,fn) for fn in os.listdir(rd) if fn.startswith('stage_events_db_') and fn.endswith('.csv')]
        if cands:
            cands.sort(key=lambda x: os.path.getmtime(x), reverse=True)
            stage_path=cands[0]
    time_path=os.path.join(rd,'last_run.time')
    pe_window_path=os.path.join(rd,'pe_window_spikes_db.csv')
    out_path=args.out or os.path.join(rd,'essential_summary.json')

    rows=parse_stats_csv(stats_path)
    mem_bytes = 0
    # Memory（来源对齐 mesh：优先使用任意组件的 CSV 统计，其次单 PE，再退回日志）
    mem_bytes_hist = sum_stat(rows, ('multicore_pe_0','SnnDL.MultiCorePE'), 'mem_req_size_bytes')
    # mesh 风格：不按组件名过滤，先看全局 memory_requests
    mem_reqs = sum_stat_any(rows, 'memory_requests')
    # 若全局为 0，再退回单 PE 组件前缀
    if not mem_reqs:
        mem_reqs = sum_stat(rows, ('multicore_pe_0','SnnDL.MultiCorePE'), 'memory_requests')
    if not mem_reqs:
        # Fallback: use histogram NumItemsBinned from MultiCorePE.mem_req_size_bytes
        mem_reqs = get_hist_num_items_binned(stats_path, ('multicore_pe_0','SnnDL.MultiCorePE'), 'mem_req_size_bytes')
    sim_cycles_total = sum_stat(rows, ('multicore_pe_0','SnnDL.MultiCorePE'), 'sim_cycles_total')
    if not mem_reqs:
        # 尝试从 ramulator2 日志提取总读请求数
        mem_reqs = parse_ramulator2_requests_from_log(os.path.join(rd,'last_run.log')) or 0
    if not mem_reqs:
        # Fallback：simpleMem 后端的诊断日志（wrapper）
        mem_reqs = parse_simplemem_requests_from_log(os.path.join(os.path.dirname(__file__),'..','logs','last_run.wrapper.log')) or 0
    # GAS bytes（若开启）
    gas_bytes=sum_stat(rows, ('multicore_pe_0','SnnDL.MultiCorePE'), 'gas_unique_bytes_total')
    if gas_bytes==0:
        gas_bytes=sum_stat(rows, ('SnnDL.SnnPESubComponent',), 'gas_unique_bytes_total')

    # Spike活动统计
    spikes_processed = sum_stat(rows, ('multicore_pe_0','SnnDL.MultiCorePE'), 'total_spikes_processed')
    neurons_fired = sum_stat(rows, ('multicore_pe_0','SnnDL.MultiCorePE'), 'total_neurons_fired')
    gas_scatter_spikes = sum_stat(rows, ('SnnDL.SnnPESubComponent',), 'gas_scatter_spikes_emitted_total')
    unique_fired = sum_stat(rows, ('multicore_pe_0','SnnDL.MultiCorePE'), 'unique_neurons_fired_total')

    # Prefer PE-level stage distributions
    ev=None
    ev_pe, sim_obs_pe = parse_pe_stage_events(pe_stage_path)
    if ev_pe:
        ev = ev_pe
        if sim_obs_pe:
            ev['sim_time_ns_observed'] = sim_obs_pe
    else:
        ev=parse_stage_events(stage_path)
    hist = build_superstep_hist(stage_path)
    tm=parse_time_file(time_path)

    ncores=int(cfg.get('num_cores_per_pe',0) or 0)
    nper=int(cfg.get('neurons_per_core',0) or 0)
    neurons_total=ncores*nper
    sim_time=str(cfg.get('sim_time',''))

    # 解析仿真时间（us）用于计算firing_rate
    sim_time_us = 0
    try:
        if sim_time.endswith('us'):
            sim_time_us = int(sim_time[:-2])
        elif sim_time.endswith('ms'):
            sim_time_us = int(float(sim_time[:-2]) * 1000)
    except Exception:
        sim_time_us = 0

    # 优先使用 MultiCorePE 直方图字节总和；若为 0，再尝试 mesh 风格的全局 mem_req_size_bytes
    if mem_bytes_hist and mem_bytes_hist>0:
        mem_bytes = mem_bytes_hist
    else:
        mem_bytes_any = sum_stat_any(rows, 'mem_req_size_bytes')
        if mem_bytes_any and mem_bytes_any>0:
            mem_bytes = mem_bytes_any
    # 如果无gas字节统计，且无直方图但有requests，则估算
    if not gas_bytes and (not mem_bytes) and mem_reqs:
        mem_bytes = estimate_bytes_from_requests(cfg, mem_reqs)

    # 构建spike活动统计（仅当有数据时）
    # 计算便捷单位换算
    dram_mib = None
    if mem_bytes and mem_bytes>0:
        dram_mib = round(mem_bytes / (1024.0*1024.0), 3)
    bw_mib_per_s = None
    if dram_mib is not None and sim_time_us>0:
        # MiB/s = bytes/us * (1e6 / 2^20)
        bw_mib_per_s = round((mem_bytes / sim_time_us) * (1e6 / (1024.0*1024.0)), 3)

    spike_activity = None

    # === 每窗口发放口径（严格GAS主口径） ===
    window_firing = None
    pe_total_spikes = None
    try:
        # 优先使用 PE 聚合（权威），失败再回退
        spikes_per_win = None
        pew = parse_pe_window_spikes(pe_window_path)
        if isinstance(pew, list) and pew:
            spikes_per_win = pew
        # 若仍为空，且存在核心级 stage 文件，可取 EndScatter.spikes_emitted（可能偏小/为0，仅次优）
        if not spikes_per_win:
            buf = []
            if stage_path and os.path.exists(stage_path):
                with open(stage_path, newline='') as f:
                    rd = csv.DictReader(f)
                    for r in rd:
                        if (r.get('event','') or '').strip() == 'EndScatter':
                            try:
                                se = int(r.get('spikes_emitted','0') or 0)
                            except Exception:
                                se = 0
                            buf.append(se)
            spikes_per_win = buf
        if spikes_per_win:
            total_windows = len(spikes_per_win)
            active_windows = sum(1 for x in spikes_per_win if x>0)
            spikes_sum = sum(spikes_per_win)
            # 平均每窗发放（所有窗口 vs 仅活跃窗口）
            avg_all = spikes_sum / total_windows if total_windows>0 else 0.0
            avg_active = (spikes_sum / active_windows) if active_windows>0 else 0.0
            # 占比（每窗发放神经元/总神经元）
            frac_all = (avg_all / neurons_total) if neurons_total>0 else 0.0
            frac_active = (avg_active / neurons_total) if neurons_total>0 else 0.0
            # 窗口时长（ns）：优先用已解析的 superstep 平均总时长
            win_ns = 0
            if ev and isinstance(ev, dict):
                try:
                    win_ns = int(ev.get('total',{}).get('avg',0) or 0)
                except Exception:
                    win_ns = 0
            # 无聚合就近似为 280ns（保守）；不强依赖该值
            if win_ns <= 0:
                win_ns = 280
            # 窗口瞬时频率（Hz/每神经元），给出两个口径
            win_sec = win_ns / 1e9
            fr_win_inst_all_hz = (frac_all / win_sec) if win_sec>0 else 0.0
            fr_win_inst_active_hz = (frac_active / win_sec) if win_sec>0 else 0.0
            pe_total_spikes = spikes_sum
            window_firing = {
                'windows_total': total_windows,
                'windows_active': active_windows,
                'windows_active_frac': round(active_windows/total_windows, 6) if total_windows>0 else 0.0,
                'spikes_per_window_avg_all': round(avg_all, 3),
                'spikes_per_window_avg_active': round(avg_active, 3),
                'per_window_fraction_all_avg': round(frac_all, 6),
                'per_window_fraction_active_avg': round(frac_active, 6),
                'window_duration_ns_avg': int(win_ns),
                'fr_window_inst_all_hz_per_neuron': round(fr_win_inst_all_hz, 3),
                'fr_window_inst_active_hz_per_neuron': round(fr_win_inst_active_hz, 3),
                'units': {
                    'windows_total': 'count',
                    'windows_active': 'count',
                    'windows_active_frac': 'fraction',
                    'spikes_per_window_avg_all': 'spikes/window',
                    'spikes_per_window_avg_active': 'spikes/window',
                    'per_window_fraction_all_avg': 'fraction',
                    'per_window_fraction_active_avg': 'fraction',
                    'window_duration_ns_avg': 'ns',
                    'fr_window_inst_all_hz_per_neuron': 'Hz/neur',
                    'fr_window_inst_active_hz_per_neuron': 'Hz/neur'
                }
            }
            # 额外输出：全部窗口总数（便于与 active 窗口对比）
            if ev and isinstance(ev, dict) and isinstance(ev.get('windows'), int):
                window_firing['windows_total_all'] = int(ev['windows'])
        # 若仍没有每窗数据，但有 GAS 分布与总发放（gas_scatter_spikes），构造回退 window_firing
        elif ev and isinstance(ev, dict):
            try:
                total_windows = int(ev.get('windows') or 0)
            except Exception:
                total_windows = 0
            spikes_sum = gas_scatter_spikes if gas_scatter_spikes>0 else 0
            if total_windows > 0:
                avg_all = (spikes_sum / total_windows) if spikes_sum>0 else 0.0
                avg_active = avg_all  # 无法区分活跃窗，保守等同于 all 均值
                frac_all = (avg_all / neurons_total) if neurons_total>0 else 0.0
                frac_active = frac_all
                win_ns = 0
                try:
                    win_ns = int(ev.get('total',{}).get('avg',0) or 0)
                except Exception:
                    win_ns = 0
                if win_ns <= 0:
                    # 回退用配置的 cycles（200/40/40）求 total
                    try:
                        g = int(cfg.get('gas_window_cycles_gather',0) or 0)
                        a = int(cfg.get('gas_window_cycles_apply',0) or 0)
                        s = int(cfg.get('gas_window_cycles_scatter',0) or 0)
                        win_ns = g + a + s
                    except Exception:
                        win_ns = 280
                win_sec = win_ns / 1e9
                fr_win_inst_all_hz = (frac_all / win_sec) if win_sec>0 else 0.0
                fr_win_inst_active_hz = fr_win_inst_all_hz
                pe_total_spikes = spikes_sum
                window_firing = {
                    'windows_total': total_windows,
                    'windows_active': total_windows if spikes_sum>0 else 0,
                    'windows_active_frac': 1.0 if spikes_sum>0 else 0.0,
                    'spikes_per_window_avg_all': round(avg_all, 3),
                    'spikes_per_window_avg_active': round(avg_active, 3),
                    'per_window_fraction_all_avg': round(frac_all, 6),
                    'per_window_fraction_active_avg': round(frac_active, 6),
                    'window_duration_ns_avg': int(win_ns),
                    'fr_window_inst_all_hz_per_neuron': round(fr_win_inst_all_hz, 3),
                    'fr_window_inst_active_hz_per_neuron': round(fr_win_inst_active_hz, 3),
                    'units': {
                        'windows_total': 'count',
                        'windows_active': 'count',
                        'windows_active_frac': 'fraction',
                        'spikes_per_window_avg_all': 'spikes/window',
                        'spikes_per_window_avg_active': 'spikes/window',
                        'per_window_fraction_all_avg': 'fraction',
                        'per_window_fraction_active_avg': 'fraction',
                        'window_duration_ns_avg': 'ns',
                        'fr_window_inst_all_hz_per_neuron': 'Hz/neur',
                        'fr_window_inst_active_hz_per_neuron': 'Hz/neur'
                    }
                }
                if ev and isinstance(ev, dict) and isinstance(ev.get('windows'), int):
                    window_firing['windows_total_all'] = int(ev['windows'])
    except Exception:
        window_firing = None

    # === 仿真时间/周期汇总（初始） ===
    sim = {}
    if ev and isinstance(ev, dict):
        sim['gas_windows_total'] = ev.get('windows')
        if ev.get('sim_time_ns_observed'):
            sim['sim_time_ns_observed'] = ev.get('sim_time_ns_observed')
    if sim_time:
        sim['sim_time_config'] = sim_time
        # 解析为 ns 与 cycles（1GHz≈1ns/周期）
        try:
            st = sim_time.strip().lower()
            ns = None
            if st.endswith('us'):
                ns = int(float(st[:-2]) * 1000.0)
            elif st.endswith('ms'):
                ns = int(float(st[:-2]) * 1_000_000.0)
            elif st.endswith('ns'):
                ns = int(float(st[:-2]))
            if ns is not None:
                sim['sim_time_config_ns'] = ns
                if 'sim_cycles_total' not in sim:
                    sim['sim_cycles_total_config'] = ns
        except Exception:
            pass
    if sim_cycles_total:
        sim['sim_cycles_total'] = sim_cycles_total
    # 配置侧 GAS 窗口周期（如提供）
    gwg = cfg.get('gas_window_cycles_gather'); gwa = cfg.get('gas_window_cycles_apply'); gws = cfg.get('gas_window_cycles_scatter')
    try:
        if gwg is not None and gwa is not None and gws is not None:
            gtot = int(gwg) + int(gwa) + int(gws)
            sim['gas_superstep_cycles_config'] = {
                'units': 'cycles',
                'gather': int(gwg), 'apply': int(gwa), 'scatter': int(gws), 'total': gtot
            }
    except Exception:
        pass

    # === Spike activity section (build before composing out) ===
    # Prefer PE window aggregation for total neurons fired if available.
    spike_activity_from_pe = None
    try:
        pew = parse_pe_window_spikes(pe_window_path)
        if isinstance(pew, list) and pew:
            spike_activity_from_pe = sum(pew)
    except Exception:
        spike_activity_from_pe = None

    # Compose spike_activity (always present; fill zeros when missing)
    spike_activity_obj = {
        'total_spikes_processed': int(spikes_processed or 0),
        'total_neurons_fired': int(neurons_fired or 0),
    }
    # Override by PE aggregation if available
    if isinstance(spike_activity_from_pe, int) and spike_activity_from_pe >= 0:
        spike_activity_obj['total_neurons_fired'] = int(spike_activity_from_pe)
    if unique_fired and unique_fired > 0:
        spike_activity_obj['unique_neurons_fired'] = int(unique_fired)
        if neurons_total>0:
            spike_activity_obj['unique_firing_fraction'] = round(unique_fired/neurons_total, 6)
    if gas_scatter_spikes and gas_scatter_spikes > 0:
        spike_activity_obj['gas_scatter_spikes_emitted'] = int(gas_scatter_spikes)
    # Rates (may be zero)
    total_for_rate = spike_activity_obj.get('total_neurons_fired', 0)
    if neurons_total > 0 and sim_time_us > 0:
        fr = (total_for_rate / (neurons_total * sim_time_us)) if total_for_rate>0 else 0.0
        spike_activity_obj['firing_rate'] = round(fr, 6)
        spike_activity_obj['firing_rate_per_neuron_per_us'] = round(fr, 6)
        spike_activity_obj['run_avg_fr_hz_per_neuron'] = round((total_for_rate / (neurons_total * (sim_time_us/1e6))) if total_for_rate>0 else 0.0, 3)

    # Fallback estimate bytes from requests when direct bytes unknown
    if (not mem_bytes) and mem_reqs:
        mem_bytes = estimate_bytes_from_requests(cfg, mem_reqs)

    out={
        'inputs': {
            'local_run_config': os.path.basename(raw_cfg_path),
            'local_run_config_effective': (
                os.path.basename(effective_cfg_path) if os.path.exists(effective_cfg_path) else None
            ),
        },
        'model':{
            'cores_per_pe': ncores,
            'neurons_per_core': nper,
            'neurons_total': neurons_total,
            'sim_time': sim_time,
        },
        'runtime_config': build_runtime_config(cfg_raw, cfg_effective),
        'memory':{
            'memory_requests': mem_reqs,
            'dram_bytes_read': (gas_bytes if gas_bytes>0 else (mem_bytes if mem_bytes>0 else None)),
            **({'dram_bytes_read_mib': dram_mib} if dram_mib is not None else {}),
            **({'approx_read_bandwidth_mib_per_s': bw_mib_per_s} if bw_mib_per_s is not None else {}),
        },
        'gas_superstep_cycles': (ev or {}),
        'sim': sim,
        'wallclock': (tm or {}),
        'units': {
            'memory_requests': 'count',
            'dram_bytes_read': 'bytes',
            'dram_bytes_read_mib': 'MiB',
            'approx_read_bandwidth_mib_per_s': 'MiB/s',
            'gas_superstep_cycles': 'ns',
            'maxrss_kb': 'kB',
            'user': 'sec',
            'sys': 'sec',
            'firing_rate': 'per_neuron_per_us'
        },
        'spike_activity': spike_activity_obj,
    }
    # Sanity：给出平均请求字节（便于校验请求粒度/合并策略）
    try:
        mb = out['memory'].get('dram_bytes_read') or 0
        mr = out['memory'].get('memory_requests') or 0
        if mb and mr:
            out['sanity'] = {'avg_req_bytes': round(float(mb)/float(mr), 3)}
    except Exception:
        pass
    if hist:
        out['gas_superstep_hist'] = hist
    if window_firing is not None:
        out['window_firing'] = window_firing
        # 若缺少观察到的仿真时长/窗口数，则由 window_firing 补全
        try:
            wf = window_firing
            if 'gas_windows_total' not in sim:
                sim['gas_windows_total'] = wf.get('windows_total')
            if wf.get('window_duration_ns_avg') and wf.get('windows_total'):
                sim_obs = int(wf['window_duration_ns_avg']) * int(wf['windows_total'])
                if 'sim_time_ns_observed' not in sim:
                    sim['sim_time_ns_observed'] = sim_obs
                if 'sim_cycles_total' not in sim:
                    sim['sim_cycles_total'] = sim_obs  # 1GHz 时 1ns ≈ 1cycle
        except Exception:
            pass

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path,'w',encoding='utf-8') as f:
        json.dump(out,f,ensure_ascii=False,indent=2)
    print(f"[OK] essential_summary.json -> {out_path}")

if __name__=='__main__':
    main()
