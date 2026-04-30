#!/usr/bin/env python3

import argparse
import csv
import datetime as _dt
import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


_ROUTER_PREFIX = "[mcast-router]"
_TRAFFIC_PREFIX = "[traffic]"
_GROUP_PREFIX = "[traffic][sk-group]"
_NOC_LAT_PREFIX = "[noc-lat]"


def _repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


def _parse_time_to_ns(s: str) -> int:
    t = (s or "").strip().lower()
    if not t:
        return 0
    mult = 1
    if t.endswith("ns"):
        mult = 1
        t = t[:-2]
    elif t.endswith("us"):
        mult = 1000
        t = t[:-2]
    elif t.endswith("ms"):
        mult = 1000 * 1000
        t = t[:-2]
    elif t.endswith("s"):
        mult = 1000 * 1000 * 1000
        t = t[:-1]
    try:
        v = float(t)
    except Exception:
        return 0
    return int(v * mult)


def _kv_from_line_tail(tail: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for part in tail.strip().split():
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _int(kv: Dict[str, str], key: str, default: int = 0) -> int:
    if key not in kv:
        return default
    try:
        return int(kv[key], 0)
    except Exception:
        return default


@dataclass(frozen=True)
class RouterRow:
    node: int
    pkts_in: int
    pkts_out: int
    pkts_local: int
    pkts_fwd_xy: int
    spikekey_in: int
    spikekey_stage_inter: int
    spikekey_stage_intra: int
    spikekey_clones: int


@dataclass(frozen=True)
class CoreRow:
    node: int
    core: int
    tx_batches: int
    tx_pre_total: int
    rx_spike: int
    rx_spikekey: int
    rx_spike_hops_sum: int
    rx_spike_hops_max: int
    rx_spikekey_hops_sum: int
    rx_spikekey_hops_max: int
    sk_ok: int
    sk_bad: int
    sk_bad_decode: int
    sk_bad_stage: int
    sk_bad_dst: int
    sk_bad_blockpos: int
    sk_bad_mask: int


@dataclass(frozen=True)
class NocLatRow:
    node: int
    spike_cnt: int
    spike_lat_sum: int
    spike_lat_max: int
    spike_avg: float
    spike_p50: int
    spike_p95: int
    spike_p99: int
    spikekey_cnt: int
    spikekey_lat_sum: int
    spikekey_lat_max: int
    spikekey_avg: float
    spikekey_p50: int
    spikekey_p95: int
    spikekey_p99: int
    hist_max: int
    spike_overflow: int
    spikekey_overflow: int


def _parse_router_rows(log_text: str) -> List[RouterRow]:
    rows: List[RouterRow] = []
    for line in log_text.splitlines():
        idx = line.find(_ROUTER_PREFIX)
        if idx < 0:
            continue
        # 允许 SST Output 前缀（例如 "Comp[fn:ln]: "）
        kv = _kv_from_line_tail(line[idx + len(_ROUTER_PREFIX) :])
        rows.append(
            RouterRow(
                node=_int(kv, "node"),
                pkts_in=_int(kv, "in"),
                pkts_out=_int(kv, "out"),
                pkts_local=_int(kv, "local"),
                pkts_fwd_xy=_int(kv, "fwd_xy"),
                spikekey_in=_int(kv, "spikekey_in"),
                spikekey_stage_inter=_int(kv, "stage_inter"),
                spikekey_stage_intra=_int(kv, "stage_intra"),
                spikekey_clones=_int(kv, "clones"),
            )
        )
    return rows


def _parse_core_rows(log_text: str) -> List[CoreRow]:
    rows: List[CoreRow] = []
    for line in log_text.splitlines():
        idx = line.find(_TRAFFIC_PREFIX)
        if idx < 0:
            continue
        # 仅解析 onFinish 的汇总行：要求 "[traffic] "（后面紧跟空格）
        after = idx + len(_TRAFFIC_PREFIX)
        if after >= len(line) or line[after] != " ":
            continue
        kv = _kv_from_line_tail(line[after:])
        rows.append(
            CoreRow(
                node=_int(kv, "node"),
                core=_int(kv, "core"),
                tx_batches=_int(kv, "tx_batches"),
                tx_pre_total=_int(kv, "tx_pre_total"),
                rx_spike=_int(kv, "rx_spike"),
                rx_spikekey=_int(kv, "rx_spikekey"),
                rx_spike_hops_sum=_int(kv, "rx_spike_hops_sum"),
                rx_spike_hops_max=_int(kv, "rx_spike_hops_max"),
                rx_spikekey_hops_sum=_int(kv, "rx_spikekey_hops_sum"),
                rx_spikekey_hops_max=_int(kv, "rx_spikekey_hops_max"),
                sk_ok=_int(kv, "sk_ok"),
                sk_bad=_int(kv, "sk_bad"),
                sk_bad_decode=_int(kv, "sk_bad_decode"),
                sk_bad_stage=_int(kv, "sk_bad_stage"),
                sk_bad_dst=_int(kv, "sk_bad_dst"),
                sk_bad_blockpos=_int(kv, "sk_bad_blockpos"),
                sk_bad_mask=_int(kv, "sk_bad_mask"),
            )
        )
    return rows


def _parse_group_summary(log_text: str) -> Dict[str, int]:
    def _materialize(kv: Dict[str, str]) -> Dict[str, int]:
        return {
            "groups_total": _int(kv, "groups_total"),
            "ok": _int(kv, "ok"),
            "bad": _int(kv, "bad"),
            "endpoints_expected": _int(kv, "endpoints_expected"),
            "received": _int(kv, "received"),
            "missing": _int(kv, "missing"),
            "extra": _int(kv, "extra"),
            "dup": _int(kv, "dup"),
            "meta_mismatch": _int(kv, "meta_mismatch"),
        }

    # Primary: structured "[traffic][sk-group] ..." summary (may appear in normal or fatal lines)
    for line in log_text.splitlines():
        idx = line.find(_GROUP_PREFIX)
        if idx < 0:
            continue
        kv = _kv_from_line_tail(line[idx + len(_GROUP_PREFIX) :])
        if "groups_total" in kv:
            return _materialize(kv)

    # Fallback: tolerate Output prefix interleaving by scanning for the kv tail itself
    needle = "groups_total="
    idx = log_text.rfind(needle)
    if idx >= 0:
        tail = log_text[idx:]
        tail = tail.splitlines()[0] if tail else ""
        kv = _kv_from_line_tail(tail)
        if "groups_total" in kv:
            return _materialize(kv)

    return {}


def _parse_noc_lat_rows(log_text: str) -> List[NocLatRow]:
    rows: List[NocLatRow] = []
    for line in log_text.splitlines():
        idx = line.find(_NOC_LAT_PREFIX)
        if idx < 0:
            continue
        kv = _kv_from_line_tail(line[idx + len(_NOC_LAT_PREFIX) :])
        try:
            spike_avg = float(kv.get("spike_avg", "0") or "0")
        except Exception:
            spike_avg = 0.0
        try:
            spikekey_avg = float(kv.get("spikekey_avg", "0") or "0")
        except Exception:
            spikekey_avg = 0.0
        rows.append(
            NocLatRow(
                node=_int(kv, "node"),
                spike_cnt=_int(kv, "spike_cnt"),
                spike_lat_sum=_int(kv, "spike_lat_sum"),
                spike_lat_max=_int(kv, "spike_lat_max"),
                spike_avg=spike_avg,
                spike_p50=_int(kv, "spike_p50"),
                spike_p95=_int(kv, "spike_p95"),
                spike_p99=_int(kv, "spike_p99"),
                spikekey_cnt=_int(kv, "spikekey_cnt"),
                spikekey_lat_sum=_int(kv, "spikekey_lat_sum"),
                spikekey_lat_max=_int(kv, "spikekey_lat_max"),
                spikekey_avg=spikekey_avg,
                spikekey_p50=_int(kv, "spikekey_p50"),
                spikekey_p95=_int(kv, "spikekey_p95"),
                spikekey_p99=_int(kv, "spikekey_p99"),
                hist_max=_int(kv, "hist_max"),
                spike_overflow=_int(kv, "spike_overflow"),
                spikekey_overflow=_int(kv, "spikekey_overflow"),
            )
        )
    return rows


def _write_csv(path: str, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _sum_int(rows: List[Any], attr: str) -> int:
    return int(sum(getattr(r, attr) for r in rows))


def _nodes_with_rx_spikekey(core_rows: List[CoreRow]) -> int:
    nodes = {r.node for r in core_rows if r.rx_spikekey > 0}
    return len(nodes)


def _derive_summary(case_cfg: Dict[str, Any], router_rows: List[RouterRow], core_rows: List[CoreRow]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "case": dict(case_cfg),
        "routers": {
            "count": len(router_rows),
            "sum_in": _sum_int(router_rows, "pkts_in"),
            "sum_out": _sum_int(router_rows, "pkts_out"),
            "sum_local": _sum_int(router_rows, "pkts_local"),
            "sum_fwd_xy": _sum_int(router_rows, "pkts_fwd_xy"),
            "sum_spikekey_in": _sum_int(router_rows, "spikekey_in"),
            "sum_stage_inter": _sum_int(router_rows, "spikekey_stage_inter"),
            "sum_stage_intra": _sum_int(router_rows, "spikekey_stage_intra"),
            "sum_clones": _sum_int(router_rows, "spikekey_clones"),
        },
        "cores": {
            "count": len(core_rows),
            "sum_tx_batches": _sum_int(core_rows, "tx_batches"),
            "sum_tx_pre_total": _sum_int(core_rows, "tx_pre_total"),
            "sum_rx_spike": _sum_int(core_rows, "rx_spike"),
            "sum_rx_spikekey": _sum_int(core_rows, "rx_spikekey"),
            "sum_sk_ok": _sum_int(core_rows, "sk_ok"),
            "sum_sk_bad": _sum_int(core_rows, "sk_bad"),
            "sum_sk_bad_decode": _sum_int(core_rows, "sk_bad_decode"),
            "sum_sk_bad_stage": _sum_int(core_rows, "sk_bad_stage"),
            "sum_sk_bad_dst": _sum_int(core_rows, "sk_bad_dst"),
            "sum_sk_bad_blockpos": _sum_int(core_rows, "sk_bad_blockpos"),
            "sum_sk_bad_mask": _sum_int(core_rows, "sk_bad_mask"),
            "nodes_with_rx_spikekey": _nodes_with_rx_spikekey(core_rows),
            "sum_rx_spike_hops_sum": _sum_int(core_rows, "rx_spike_hops_sum"),
            "sum_rx_spike_hops_max": max((r.rx_spike_hops_max for r in core_rows), default=0),
            "sum_rx_spikekey_hops_sum": _sum_int(core_rows, "rx_spikekey_hops_sum"),
            "sum_rx_spikekey_hops_max": max((r.rx_spikekey_hops_max for r in core_rows), default=0),
        },
    }

    # Derived: average hop length for received packets
    rx_spike = summary["cores"]["sum_rx_spike"]
    rx_spikekey = summary["cores"]["sum_rx_spikekey"]
    summary["derived"] = {
        "avg_rx_spike_hops": (summary["cores"]["sum_rx_spike_hops_sum"] / rx_spike) if rx_spike else 0.0,
        "avg_rx_spikekey_hops": (summary["cores"]["sum_rx_spikekey_hops_sum"] / rx_spikekey) if rx_spikekey else 0.0,
    }
    return summary


def _validate_case(summary: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errs: List[str] = []
    case = summary.get("case", {})
    multicast_enable = int(case.get("MULTICAST_ENABLE", 0))

    if summary["cores"]["sum_sk_bad"] != 0:
        errs.append(f"sk_bad!=0 (sum_sk_bad={summary['cores']['sum_sk_bad']})")

    if multicast_enable != 0:
        if summary["cores"]["sum_rx_spikekey"] <= 0:
            errs.append("multicast enabled but rx_spikekey==0")
        if summary["routers"]["sum_clones"] <= 0:
            errs.append("multicast enabled but router clones==0")
        if summary["cores"]["nodes_with_rx_spikekey"] < 2:
            errs.append("multicast enabled but rx_spikekey only on <2 nodes")
        skg = summary.get("sk_group", {})
        if not skg:
            errs.append("multicast enabled but missing sk-group summary")
        else:
            if int(skg.get("bad", 0)) != 0:
                errs.append(f"sk-group bad!=0 (bad={skg.get('bad')})")
            if int(skg.get("missing", 0)) != 0:
                errs.append(f"sk-group missing!=0 (missing={skg.get('missing')})")
            if int(skg.get("extra", 0)) != 0:
                errs.append(f"sk-group extra!=0 (extra={skg.get('extra')})")
            if int(skg.get("dup", 0)) != 0:
                errs.append(f"sk-group dup!=0 (dup={skg.get('dup')})")
            if int(skg.get("meta_mismatch", 0)) != 0:
                errs.append(f"sk-group meta_mismatch!=0 (meta_mismatch={skg.get('meta_mismatch')})")

        nlat = summary.get("noc_lat", {})
        if not nlat:
            errs.append("multicast enabled but missing noc-lat summary")
        else:
            if int(nlat.get("sum_spikekey_cnt", 0)) <= 0:
                errs.append("multicast enabled but noc-lat spikekey_cnt==0")
    else:
        if summary["cores"]["sum_rx_spike"] <= 0:
            errs.append("multicast disabled but rx_spike==0")
        nlat = summary.get("noc_lat", {})
        if not nlat:
            errs.append("multicast disabled but missing noc-lat summary")
        else:
            if int(nlat.get("sum_spike_cnt", 0)) <= 0:
                errs.append("multicast disabled but noc-lat spike_cnt==0")

    return (len(errs) == 0), errs


def _run_one_case(repo_root: str, out_dir: str, case_cfg: Dict[str, Any]) -> Dict[str, Any]:
    sst_bin = os.path.join(repo_root, "sst")
    model = os.path.join(repo_root, "experimental_features", "native_multicast_lab", "test_mesh_4x4_spikekey_multicast.py")

    env = os.environ.copy()
    env.update({k: str(v) for k, v in case_cfg.items()})

    cmd = [sst_bin, model]
    res = subprocess.run(cmd, cwd=repo_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log_text = res.stdout or ""

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "sst.log"), "w") as f:
        f.write(log_text)

    router_rows = _parse_router_rows(log_text)
    core_rows = _parse_core_rows(log_text)
    group_summary = _parse_group_summary(log_text)
    noc_lat_rows = _parse_noc_lat_rows(log_text)

    _write_csv(
        os.path.join(out_dir, "routers.csv"),
        [
            "node",
            "in",
            "out",
            "local",
            "fwd_xy",
            "spikekey_in",
            "stage_inter",
            "stage_intra",
            "clones",
        ],
        [
            {
                "node": r.node,
                "in": r.pkts_in,
                "out": r.pkts_out,
                "local": r.pkts_local,
                "fwd_xy": r.pkts_fwd_xy,
                "spikekey_in": r.spikekey_in,
                "stage_inter": r.spikekey_stage_inter,
                "stage_intra": r.spikekey_stage_intra,
                "clones": r.spikekey_clones,
            }
            for r in sorted(router_rows, key=lambda x: x.node)
        ],
    )

    _write_csv(
        os.path.join(out_dir, "cores.csv"),
        [
            "node",
            "core",
            "tx_batches",
            "tx_pre_total",
            "rx_spike",
            "rx_spikekey",
            "rx_spike_hops_sum",
            "rx_spike_hops_max",
            "rx_spikekey_hops_sum",
            "rx_spikekey_hops_max",
            "sk_ok",
            "sk_bad",
            "sk_bad_decode",
            "sk_bad_stage",
            "sk_bad_dst",
            "sk_bad_blockpos",
            "sk_bad_mask",
        ],
        [
            {
                "node": r.node,
                "core": r.core,
                "tx_batches": r.tx_batches,
                "tx_pre_total": r.tx_pre_total,
                "rx_spike": r.rx_spike,
                "rx_spikekey": r.rx_spikekey,
                "rx_spike_hops_sum": r.rx_spike_hops_sum,
                "rx_spike_hops_max": r.rx_spike_hops_max,
                "rx_spikekey_hops_sum": r.rx_spikekey_hops_sum,
                "rx_spikekey_hops_max": r.rx_spikekey_hops_max,
                "sk_ok": r.sk_ok,
                "sk_bad": r.sk_bad,
                "sk_bad_decode": r.sk_bad_decode,
                "sk_bad_stage": r.sk_bad_stage,
                "sk_bad_dst": r.sk_bad_dst,
                "sk_bad_blockpos": r.sk_bad_blockpos,
                "sk_bad_mask": r.sk_bad_mask,
            }
            for r in sorted(core_rows, key=lambda x: (x.node, x.core))
        ],
    )

    _write_csv(
        os.path.join(out_dir, "noc_lat.csv"),
        [
            "node",
            "spike_cnt",
            "spike_lat_sum",
            "spike_lat_max",
            "spike_avg",
            "spike_p50",
            "spike_p95",
            "spike_p99",
            "spikekey_cnt",
            "spikekey_lat_sum",
            "spikekey_lat_max",
            "spikekey_avg",
            "spikekey_p50",
            "spikekey_p95",
            "spikekey_p99",
            "hist_max",
            "spike_overflow",
            "spikekey_overflow",
        ],
        [
            {
                "node": r.node,
                "spike_cnt": r.spike_cnt,
                "spike_lat_sum": r.spike_lat_sum,
                "spike_lat_max": r.spike_lat_max,
                "spike_avg": "{:.6f}".format(r.spike_avg),
                "spike_p50": r.spike_p50,
                "spike_p95": r.spike_p95,
                "spike_p99": r.spike_p99,
                "spikekey_cnt": r.spikekey_cnt,
                "spikekey_lat_sum": r.spikekey_lat_sum,
                "spikekey_lat_max": r.spikekey_lat_max,
                "spikekey_avg": "{:.6f}".format(r.spikekey_avg),
                "spikekey_p50": r.spikekey_p50,
                "spikekey_p95": r.spikekey_p95,
                "spikekey_p99": r.spikekey_p99,
                "hist_max": r.hist_max,
                "spike_overflow": r.spike_overflow,
                "spikekey_overflow": r.spikekey_overflow,
            }
            for r in sorted(noc_lat_rows, key=lambda x: x.node)
        ],
    )

    summary = _derive_summary(case_cfg, router_rows, core_rows)
    if group_summary:
        summary["sk_group"] = dict(group_summary)
    if noc_lat_rows:
        spike_cnt = sum(r.spike_cnt for r in noc_lat_rows)
        spike_sum = sum(r.spike_lat_sum for r in noc_lat_rows)
        spikekey_cnt = sum(r.spikekey_cnt for r in noc_lat_rows)
        spikekey_sum = sum(r.spikekey_lat_sum for r in noc_lat_rows)
        summary["noc_lat"] = {
            "count": len(noc_lat_rows),
            "sum_spike_cnt": int(spike_cnt),
            "sum_spike_lat_sum": int(spike_sum),
            "max_spike_lat_max": int(max((r.spike_lat_max for r in noc_lat_rows), default=0)),
            "max_spike_p95": int(max((r.spike_p95 for r in noc_lat_rows), default=0)),
            "max_spike_p99": int(max((r.spike_p99 for r in noc_lat_rows), default=0)),
            "avg_spike_lat": (float(spike_sum) / float(spike_cnt)) if spike_cnt else 0.0,
            "sum_spikekey_cnt": int(spikekey_cnt),
            "sum_spikekey_lat_sum": int(spikekey_sum),
            "max_spikekey_lat_max": int(max((r.spikekey_lat_max for r in noc_lat_rows), default=0)),
            "max_spikekey_p95": int(max((r.spikekey_p95 for r in noc_lat_rows), default=0)),
            "max_spikekey_p99": int(max((r.spikekey_p99 for r in noc_lat_rows), default=0)),
            "avg_spikekey_lat": (float(spikekey_sum) / float(spikekey_cnt)) if spikekey_cnt else 0.0,
            "hist_max": int(max((r.hist_max for r in noc_lat_rows), default=0)),
            "sum_spike_overflow": int(sum(r.spike_overflow for r in noc_lat_rows)),
            "sum_spikekey_overflow": int(sum(r.spikekey_overflow for r in noc_lat_rows)),
        }
    ok, errs = _validate_case(summary)
    summary["sst"] = {
        "returncode": res.returncode,
        "ok": bool(ok and res.returncode == 0),
        "validation_errors": errs,
    }
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Run native multicast lab suite and dump CSV/JSON stats.")
    ap.add_argument("--sim-time", type=str, default="20us")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--block-w", type=int, default=2)
    ap.add_argument("--block-h", type=int, default=2)
    ap.add_argument("--traffic-period-cycles", type=int, default=50)
    ap.add_argument("--traffic-batch-size", type=int, default=8)
    ap.add_argument("--traffic-stop-cycle", type=int, default=0, help="Stop traffic injection at given cycle (0=never)")
    ap.add_argument("--traffic-stop-fraction", type=float, default=0.0, help="Stop traffic injection at fraction of sim_time (0=disabled)")
    ap.add_argument("--enable-all", action="store_true", help="Enable traffic injection on all cores")
    ap.add_argument("--src-node", type=int, default=0)
    ap.add_argument("--src-core", type=int, default=0)
    ap.add_argument("--ingress-policy", type=str, default="top_left", choices=["top_left", "top_right", "bottom_left", "bottom_right", "hash4"])
    ap.add_argument("--inter-policy", type=str, default="xy", choices=["xy", "yx", "hash_xy"])
    ap.add_argument("--intra-policy", type=str, default="manhattan_x_first", choices=["manhattan_x_first", "manhattan_y_first"])
    ap.add_argument("--link-latency", type=str, default="5ns")
    ap.add_argument("--router-latency-cycles", type=int, default=0)
    ap.add_argument("--router-serialize-enable", action="store_true")
    ap.add_argument("--router-serialize-service-cycles", type=int, default=1)
    ap.add_argument("--noc-lat-hist-max", type=int, default=131072)
    ap.add_argument("--edges-csv", type=str, default="", help="Override EDGES_CSV used by the model script (optional)")
    ap.add_argument("--tag", type=str, default="")
    args = ap.parse_args()

    stop_cycle = int(args.traffic_stop_cycle)
    if stop_cycle <= 0 and args.traffic_stop_fraction and args.traffic_stop_fraction > 0.0 and args.traffic_stop_fraction < 1.0:
        sim_ns = _parse_time_to_ns(args.sim_time)
        if sim_ns > 0:
            stop_cycle = int(sim_ns * float(args.traffic_stop_fraction))

    repo_root = _repo_root()
    runs_root = os.path.join(repo_root, "experimental_features", "native_multicast_lab", "experiments", "runs")
    os.makedirs(runs_root, exist_ok=True)

    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{ts}_{args.tag}" if args.tag else ts
    out_root = os.path.join(runs_root, run_id)
    os.makedirs(out_root, exist_ok=True)

    suite_cfg = {
        # 固化 M1 口径：4×4 mesh、每 PE 4 核、每核 64 神经元、2×2 block、top-left ingress
        "MESH_W": 4,
        "MESH_H": 4,
        "NUM_CORES_PER_PE": 4,
        "NEURONS_PER_CORE": 64,
        "MULTICAST_BLOCK_W": int(args.block_w),
        "MULTICAST_BLOCK_H": int(args.block_h),
        "MULTICAST_INGRESS_POLICY": args.ingress_policy,
        "MULTICAST_INTER_POLICY": args.inter_policy,
        "MULTICAST_INTRA_POLICY": args.intra_policy,
        # edges_csv 的 dst 为 global neuron id（非 block_id）
        "MAPPING_ASSUME_BLOCK_IDS": 0,
        "LINK_LATENCY": args.link_latency,
        "ROUTER_LATENCY_CYCLES": int(args.router_latency_cycles),
        "ROUTER_SERIALIZE_ENABLE": 1 if args.router_serialize_enable else 0,
        "ROUTER_SERIALIZE_SERVICE_CYCLES": int(args.router_serialize_service_cycles),
        "NOC_LAT_HIST_MAX": int(args.noc_lat_hist_max),
        "SIM_TIME": args.sim_time,
        "TRAFFIC_PERIOD_CYCLES": args.traffic_period_cycles,
        "TRAFFIC_BATCH_SIZE": args.traffic_batch_size,
        "TRAFFIC_STOP_CYCLE": stop_cycle,
        "TRAFFIC_ENABLE_ALL": 1 if args.enable_all else 0,
        "TRAFFIC_SRC_NODE": args.src_node,
        "TRAFFIC_SRC_CORE": args.src_core,
        "SPIKEY_CHECK_ENABLE": 1,
        "SPIKEY_CHECK_FATAL": 1,
    }
    if args.edges_csv.strip():
        suite_cfg["EDGES_CSV"] = os.path.abspath(args.edges_csv.strip())
    with open(os.path.join(out_root, "suite_config.json"), "w") as f:
        json.dump(suite_cfg, f, indent=2, sort_keys=True)

    suite_summary: Dict[str, Any] = {"run_id": run_id, "suite_config": suite_cfg, "cases": []}
    exit_code = 0

    for seed in args.seeds:
        for multicast_enable in (1, 0):
            case_name = f"seed{seed}_{'multicast' if multicast_enable else 'unicast'}"
            case_dir = os.path.join(out_root, case_name)

            case_cfg = dict(suite_cfg)
            case_cfg.update({"TRAFFIC_SEED": seed, "MULTICAST_ENABLE": multicast_enable})

            summary = _run_one_case(repo_root, case_dir, case_cfg)
            nlat = summary.get("noc_lat", {})
            if multicast_enable != 0:
                avg_lat = float(nlat.get("avg_spikekey_lat", 0.0))
                p95_lat = int(nlat.get("max_spikekey_p95", 0))
                p99_lat = int(nlat.get("max_spikekey_p99", 0))
                lat_cnt = int(nlat.get("sum_spikekey_cnt", 0))
                lat_overflow = int(nlat.get("sum_spikekey_overflow", 0))
            else:
                avg_lat = float(nlat.get("avg_spike_lat", 0.0))
                p95_lat = int(nlat.get("max_spike_p95", 0))
                p99_lat = int(nlat.get("max_spike_p99", 0))
                lat_cnt = int(nlat.get("sum_spike_cnt", 0))
                lat_overflow = int(nlat.get("sum_spike_overflow", 0))
            suite_summary["cases"].append(
                {
                    "name": case_name,
                    "dir": os.path.relpath(case_dir, repo_root),
                    "multicast_enable": multicast_enable,
                    "seed": seed,
                    "routers_sum_out": summary["routers"]["sum_out"],
                    "routers_sum_fwd_xy": summary["routers"]["sum_fwd_xy"],
                    "cores_sum_rx_spike": summary["cores"]["sum_rx_spike"],
                    "cores_sum_rx_spikekey": summary["cores"]["sum_rx_spikekey"],
                    "cores_sum_sk_bad": summary["cores"]["sum_sk_bad"],
                    "avg_lat_cycles": avg_lat,
                    "p95_lat_cycles": p95_lat,
                    "p99_lat_cycles": p99_lat,
                    "lat_cnt": lat_cnt,
                    "lat_overflow": lat_overflow,
                    "ok": summary["sst"]["ok"],
                    "returncode": summary["sst"]["returncode"],
                    "validation_errors": summary["sst"]["validation_errors"],
                }
            )
            if not summary["sst"]["ok"]:
                exit_code = 2

    # Derived comparison (unicast/multicast) per seed
    per_seed: Dict[int, Dict[str, Any]] = {}
    for c in suite_summary["cases"]:
        seed = int(c["seed"])
        per_seed.setdefault(seed, {})
        per_seed[seed]["unicast" if c["multicast_enable"] == 0 else "multicast"] = c

    comparisons: List[Dict[str, Any]] = []
    for seed, d in sorted(per_seed.items(), key=lambda x: x[0]):
        u = d.get("unicast")
        m = d.get("multicast")
        if not u or not m:
            continue
        def _ratio(a: int, b: int) -> float:
            return (float(a) / float(b)) if b else 0.0
        def _ratio_f(a: float, b: float) -> float:
            return (float(a) / float(b)) if b else 0.0
        def _frac(a: int, b: int) -> float:
            return (float(a) / float(b)) if b else 0.0
        comparisons.append(
            {
                "seed": seed,
                "out_ratio_unicast_over_multicast": _ratio(int(u["routers_sum_out"]), int(m["routers_sum_out"])),
                "fwd_xy_ratio_unicast_over_multicast": _ratio(int(u["routers_sum_fwd_xy"]), int(m["routers_sum_fwd_xy"])),
                "rx_ratio_spike_over_spikekey": _ratio(int(u["cores_sum_rx_spike"]), int(m["cores_sum_rx_spikekey"])),
                "avg_lat_ratio_unicast_over_multicast": _ratio_f(float(u["avg_lat_cycles"]), float(m["avg_lat_cycles"])),
                "p95_lat_ratio_unicast_over_multicast": _ratio_f(float(u["p95_lat_cycles"]), float(m["p95_lat_cycles"])),
                "p99_lat_ratio_unicast_over_multicast": _ratio_f(float(u["p99_lat_cycles"]), float(m["p99_lat_cycles"])),
                "overflow_cnt_unicast": int(u.get("lat_overflow", 0)),
                "overflow_cnt_multicast": int(m.get("lat_overflow", 0)),
                "overflow_frac_unicast": _frac(int(u.get("lat_overflow", 0)), int(u.get("lat_cnt", 0))),
                "overflow_frac_multicast": _frac(int(m.get("lat_overflow", 0)), int(m.get("lat_cnt", 0))),
                "overflow_frac_delta_unicast_minus_multicast": _frac(int(u.get("lat_overflow", 0)), int(u.get("lat_cnt", 0)))
                - _frac(int(m.get("lat_overflow", 0)), int(m.get("lat_cnt", 0))),
            }
        )
    suite_summary["comparisons"] = comparisons

    with open(os.path.join(out_root, "suite_summary.json"), "w") as f:
        json.dump(suite_summary, f, indent=2, sort_keys=True)

    print(f"[suite] out_dir={os.path.relpath(out_root, repo_root)} cases={len(suite_summary['cases'])} exit={exit_code}")
    if comparisons:
        for c in comparisons:
            print(
                "[suite] seed={seed} out_ratio={out:.3f} fwd_xy_ratio={fwd:.3f} rx_ratio={rx:.3f} p95_ratio={p95:.3f} p99_ratio={p99:.3f} overflow_frac_delta={od:+.6f}".format(
                    seed=c["seed"],
                    out=c["out_ratio_unicast_over_multicast"],
                    fwd=c["fwd_xy_ratio_unicast_over_multicast"],
                    rx=c["rx_ratio_spike_over_spikekey"],
                    p95=c["p95_lat_ratio_unicast_over_multicast"],
                    p99=c["p99_lat_ratio_unicast_over_multicast"],
                    od=c["overflow_frac_delta_unicast_minus_multicast"],
                )
            )

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
