#!/usr/bin/env python3
"""
Lightweight 4x4 mesh NoC trace driver (P1-2)
Reads granules.csv (and optional spikes.csv, gas_stage.csv) and simulates
XY-routed packets with per-link bandwidth/latency to produce end-to-end latency stats.

CSV expectations (headers; extra columns ignored):
- granules.csv: step,req_tile,owner_tile,burst_bytes[,start_ns]
- spikes.csv (optional): kind,src_tile,dst_tile,start_ns,logical_step,spike_count,payload_bytes

Config via CLI:
- --size 4 (mesh side)
- --dur 100us
- --flit-bytes 32
- --bw 32GiB/s (preferred) 或 --bw-bytes-per-ns 32
- --hop-lat-ns 2           # per-hop pipeline latency (not incl. ser)
- --in-lat-ns 1 --out-lat-ns 1  # enqueue/dequeue
- --vc 1 --buf-flits 8     # placeholders (no detailed buffer model; we serialize per-link)
- --overlap realistic|ideal (ideal allows full overlap, realistic is same in this driver unless gas_stage provided)

Outputs:
- analysis/noc_trace_summary.csv with per-flow class (req/resp/spike) latency stats
"""
import argparse, csv, os, math

def parse_time_ns(s: str) -> int:
    s = s.strip().lower()
    if s.endswith('us'): return int(float(s[:-2]) * 1000.0)
    if s.endswith('ms'): return int(float(s[:-2]) * 1_000_000.0)
    if s.endswith('ns'): return int(float(s[:-2]))
    if s.endswith('s'):  return int(float(s[:-1]) * 1_000_000_000.0)
    return int(float(s))

def read_csv(path):
    rows = []
    if not path or not os.path.exists(path):
        return rows
    with open(path, 'r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)
    return rows

def xy_path(src, dst, size):
    sx, sy = src % size, src // size
    dx, dy = dst % size, dst // size
    path = []
    x = sx
    while x != dx:
        nx = x + (1 if dx > x else -1)
        a = sy * size + x
        b = sy * size + nx
        path.append((a,b))
        x = nx
    y = sy
    while y != dy:
        ny = y + (1 if dy > y else -1)
        a = y * size + dx
        b = ny * size + dx
        path.append((a,b))
        y = ny
    return path

def parse_bw_bytes_per_ns(text: str) -> float:
    if not text:
        return None
    t = text.strip().lower().replace(' ', '')
    if t.endswith('/s'):
        t = t[:-2]
    units = [
        ('gib', 1024.0 ** 3),
        ('gb', 1_000_000_000.0),
        ('mib', 1024.0 ** 2),
        ('mb', 1_000_000.0),
        ('kib', 1024.0),
        ('kb', 1_000.0),
        ('b', 1.0),
    ]
    for suffix, factor in units:
        if t.endswith(suffix):
            try:
                value = float(t[:-len(suffix)])
            except ValueError:
                return None
            bytes_per_s = value * factor
            return bytes_per_s / 1_000_000_000.0
    try:
        return float(t)
    except ValueError:
        return None


def percentile(values, p):
    if not values:
        return 0.0
    vs = sorted(values)
    k = int(round((p / 100.0) * (len(vs) - 1)))
    k = max(0, min(k, len(vs) - 1))
    return float(vs[k])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--granules', default='sst_dram_si/analysis/granules.csv')
    ap.add_argument('--spikes', default='')
    ap.add_argument('--stages', default='')
    ap.add_argument('--size', type=int, default=4)
    ap.add_argument('--dur', default='100us')
    ap.add_argument('--flit-bytes', type=int, default=32)
    ap.add_argument('--bw-bytes-per-ns', type=float, default=None)
    ap.add_argument('--bw', default='')
    ap.add_argument('--hop-lat-ns', type=int, default=2)
    ap.add_argument('--in-lat-ns', type=int, default=1)
    ap.add_argument('--out-lat-ns', type=int, default=1)
    ap.add_argument('--overlap', choices=['ideal', 'realistic'], default='ideal')
    ap.add_argument('--multicast', choices=['replicate', 'tree'], default='replicate')
    ap.add_argument('--out', default='sst_dram_si/analysis/noc_trace_summary.csv')
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    dur_ns = parse_time_ns(args.dur)

    bw_bytes_per_ns = None
    if args.bw_bytes_per_ns is not None:
        bw_bytes_per_ns = args.bw_bytes_per_ns
    elif args.bw:
        bw_bytes_per_ns = parse_bw_bytes_per_ns(args.bw)
    if bw_bytes_per_ns is None or bw_bytes_per_ns <= 0:
        bw_bytes_per_ns = 32.0
    flit_t_ns = args.flit_bytes / max(1e-9, bw_bytes_per_ns)

    gran = read_csv(args.granules)
    spikes = read_csv(args.spikes) if args.spikes else []
    stage_rows = read_csv(args.stages) if args.stages else []

    ignore_contention = (args.overlap == 'ideal')
    link_free = {}

    def route_one(src, dst, flits, t_inject):
        t = t_inject
        path = xy_path(src, dst, args.size)
        ser_ns = flits * flit_t_ns
        for (u, v) in path:
            key = (u, v)
            ready = (t + args.in_lat_ns) if ignore_contention else max(link_free.get(key, 0), t + args.in_lat_ns)
            finish = ready + args.hop_lat_ns + ser_ns + args.out_lat_ns
            link_free[key] = finish
            t = finish
        return t

    buckets = {}
    from statistics import mean

    def add_event(cls, latencies, injected_flits, edge_flits, payload_contrib, work_contrib):
        if not latencies:
            return
        b = buckets.setdefault(cls, {'lat': [], 'inj_flits': 0, 'edge_flits': 0, 'payload': 0, 'work': 0, 'messages': 0})
        b['lat'].extend(latencies)
        b['inj_flits'] += injected_flits
        b['edge_flits'] += edge_flits
        b['payload'] += payload_contrib
        b['work'] += work_contrib
        b['messages'] += len(latencies)

    if gran:
        total = max(1, len(gran))
        for i, row in enumerate(gran):
            try:
                req = int(row.get('req_tile') or row.get('req') or row['src'])
                owner = int(row.get('owner_tile') or row.get('owner') or row['dst'])
            except Exception:
                continue
            burst = int(row.get('burst_bytes') or row.get('bytes') or 0)
            t0 = int(row.get('start_ns') or (i * (dur_ns // total)))
            req_flits = 2
            t_req_fin = route_one(req, owner, flits=req_flits, t_inject=t0)
            path_len_req = len(xy_path(req, owner, args.size))
            add_event('read_req', [t_req_fin - t0], req_flits, req_flits * path_len_req, req_flits * args.flit_bytes, req_flits)
            resp_flits = max(1, math.ceil(max(0, burst) / args.flit_bytes)) + 1
            t_resp_fin = route_one(owner, req, flits=resp_flits, t_inject=t_req_fin)
            path_len_resp = len(xy_path(owner, req, args.size))
            add_event('read_resp', [t_resp_fin - t_req_fin], resp_flits, resp_flits * path_len_resp, max(0, burst), resp_flits)

    if args.multicast == 'replicate':
        for i, row in enumerate(spikes):
            try:
                src = int(row.get('src_tile') or row['src'])
                dst = int(row.get('dst_tile') or row['dst'])
            except Exception:
                continue
            payload_bytes = int(row.get('payload_bytes') or args.flit_bytes)
            spike_count = int(row.get('spike_count') or row.get('spikes', 1) or 1)
            start_ns = int(row.get('start_ns') or (i * (dur_ns // max(1, len(spikes)))))
            flits = max(1, math.ceil(max(0, payload_bytes) / args.flit_bytes))
            t_fin = route_one(src, dst, flits=flits, t_inject=start_ns)
            kind = row.get('kind', 'spike')
            path_len = len(xy_path(src, dst, args.size))
            add_event(kind, [t_fin - start_ns], flits, flits * path_len, max(0, payload_bytes), spike_count)
    else:
        from collections import defaultdict, deque
        groups = defaultdict(list)
        for idx, row in enumerate(spikes):
            try:
                src = int(row.get('src_tile') or row['src'])
            except Exception:
                continue
            logical_step = int(row.get('logical_step') or row.get('start_ns') or idx)
            groups[(src, logical_step)].append(row)
        for (src, logical_step), rows in groups.items():
            start_ns = min(int(r.get('start_ns') or logical_step) for r in rows)
            payload_bytes = max(int(r.get('payload_bytes') or args.flit_bytes) for r in rows)
            spike_sum = sum(int(r.get('spike_count') or r.get('spikes', 1) or 1) for r in rows)
            flits = max(1, math.ceil(max(0, payload_bytes) / args.flit_bytes))
            dests = []
            adjacency = defaultdict(set)
            edges = set()
            for r in rows:
                try:
                    dst = int(r.get('dst_tile') or r['dst'])
                except Exception:
                    continue
                dests.append(dst)
                for u, v in xy_path(src, dst, args.size):
                    adjacency[u].add(v)
                    edges.add((u, v))
            if not dests:
                continue
            arrival = {src: start_ns}
            visited_edges = set()
            queue = deque([src])
            while queue:
                u = queue.popleft()
                for v in adjacency.get(u, ()):
                    edge = (u, v)
                    if edge in visited_edges:
                        continue
                    ready = arrival[u] + args.in_lat_ns if ignore_contention else max(link_free.get(edge, 0), arrival[u] + args.in_lat_ns)
                    finish = ready + args.hop_lat_ns + flits * flit_t_ns + args.out_lat_ns
                    link_free[edge] = finish
                    visited_edges.add(edge)
                    if v not in arrival or finish < arrival[v]:
                        arrival[v] = finish
                        queue.append(v)
            latencies = [max(0.0, arrival.get(dst, start_ns) - start_ns) for dst in dests]
            add_event('spike', latencies, flits, len(visited_edges) * flits, max(0, payload_bytes) * len(dests), spike_sum)

    with open(args.out, 'w', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow([
            'class', 'messages', 'injected_flits', 'edge_flits', 'total_payload_bytes', 'total_work_units',
            'avg_ns', 'p50_ns', 'p95_ns', 'p99_ns'
        ])
        for cls, data in sorted(buckets.items()):
            latencies = data['lat']
            w.writerow([
                cls,
                data['messages'],
                data['inj_flits'],
                data['edge_flits'],
                data['payload'],
                data['work'],
                f"{mean(latencies):.2f}",
                f"{percentile(latencies, 50):.2f}",
                f"{percentile(latencies, 95):.2f}",
                f"{percentile(latencies, 99):.2f}",
            ])

    total_msgs = sum(data['messages'] for data in buckets.values())
    print(f"Wrote {args.out} with {total_msgs} messages across {len(buckets)} classes")

    if stage_rows:
        stage_map = {}
        for row in stage_rows:
            try:
                seq = int(row.get('seq'))
                event = row.get('event', '')
                t_ns = int(row.get('sim_time_ns') or row.get('time_ns') or 0)
            except Exception:
                continue
            stage_map.setdefault(seq, {})[event] = t_ns
        gather_dur = []
        apply_dur = []
        scatter_dur = []
        for seq, events in stage_map.items():
            bg = events.get('BeginGather')
            ba = events.get('BeginApply')
            ea = events.get('EndApply')
            bs = events.get('BeginScatter')
            es = events.get('EndScatter')
            if bg is not None and ba is not None:
                gather_dur.append(max(0, ba - bg))
            if ba is not None and ea is not None:
                apply_dur.append(max(0, ea - ba))
            if bs is not None and es is not None:
                scatter_dur.append(max(0, es - bs))
        if gather_dur or apply_dur or scatter_dur:
            avg_g = sum(gather_dur) / len(gather_dur) if gather_dur else 0.0
            avg_a = sum(apply_dur) / len(apply_dur) if apply_dur else 0.0
            avg_s = sum(scatter_dur) / len(scatter_dur) if scatter_dur else 0.0
            print(f"Stage averages (ns): gather={avg_g:.2f}, apply={avg_a:.2f}, scatter={avg_s:.2f}")

if __name__ == '__main__':
    main()
