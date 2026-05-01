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
_NIC_PREFIX = "[mcast-nic]"
_TRAFFIC_PREFIX = "[traffic]"
_GROUP_PREFIX = "[traffic][sk-group]"
_NOC_LAT_PREFIX = "[noc-lat]"


def _repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", ".."))


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


@dataclass(frozen=True)
class RouterRow:
    node: int
    pkts_in: int
    pkts_out: int
    pkts_local: int
    pkts_fwd_xy: int
    bytes_in: int
    bytes_out: int
    bytes_local: int
    bytes_fwd_xy: int
    byte_hops: int
    spikekey_in: int
    spikekey_stage_inter: int
    spikekey_stage_intra: int
    spikekey_clones: int
    adi_inter_decisions: int
    adi_inter_choose_x: int
    adi_inter_choose_y: int
    adi_inter_tie: int
    adi_inter_cost_x: int
    adi_inter_cost_y: int
    adi_inter_cost_chosen: int
    adi_inter_cost_delta_abs: int
    adi_intra_decisions: int
    adi_intra_choose_x: int
    adi_intra_choose_y: int
    adi_intra_tie: int
    adi_intra_cost_x: int
    adi_intra_cost_y: int
    adi_intra_cost_chosen: int
    adi_intra_cost_delta_abs: int
    adi_intra_pred_bytes_x: int
    adi_intra_pred_bytes_y: int
    adi_intra_pred_bytes_chosen: int
    adi_intra_pred_bytes_delta_abs: int
    adi_intra_queue_x: int
    adi_intra_queue_y: int
    adi_intra_queue_chosen: int


@dataclass(frozen=True)
class NicRow:
    node: int
    tx_pkts: int
    tx_bytes: int
    rx_pkts: int
    rx_bytes: int


@dataclass(frozen=True)
class CoreRow:
    node: int
    core: int
    tx_batches: int
    tx_pre_total: int
    rx_spike: int
    rx_spikekey: int
    rx_spiketilekey: int
    tx_spike_pkts: int
    tx_spikekey_pkts: int
    tx_spiketilekey_pkts: int
    tile_bad_decode: int
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
    spike_p95: int
    spike_p99: int
    spikekey_cnt: int
    spikekey_lat_sum: int
    spikekey_lat_max: int
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
        kv = _kv_from_line_tail(line[idx + len(_ROUTER_PREFIX) :])
        rows.append(
            RouterRow(
                node=_int(kv, "node"),
                pkts_in=_int(kv, "in"),
                pkts_out=_int(kv, "out"),
                pkts_local=_int(kv, "local"),
                pkts_fwd_xy=_int(kv, "fwd_xy"),
                bytes_in=_int(kv, "bytes_in"),
                bytes_out=_int(kv, "bytes_out"),
                bytes_local=_int(kv, "bytes_local"),
                bytes_fwd_xy=_int(kv, "bytes_fwd_xy"),
                byte_hops=_int(kv, "byte_hops"),
                spikekey_in=_int(kv, "spikekey_in"),
                spikekey_stage_inter=_int(kv, "stage_inter"),
                spikekey_stage_intra=_int(kv, "stage_intra"),
                spikekey_clones=_int(kv, "clones"),
                adi_inter_decisions=_int(kv, "adi_inter_decisions"),
                adi_inter_choose_x=_int(kv, "adi_inter_choose_x"),
                adi_inter_choose_y=_int(kv, "adi_inter_choose_y"),
                adi_inter_tie=_int(kv, "adi_inter_tie"),
                adi_inter_cost_x=_int(kv, "adi_inter_cost_x"),
                adi_inter_cost_y=_int(kv, "adi_inter_cost_y"),
                adi_inter_cost_chosen=_int(kv, "adi_inter_cost_chosen"),
                adi_inter_cost_delta_abs=_int(kv, "adi_inter_cost_delta_abs"),
                adi_intra_decisions=_int(kv, "adi_intra_decisions"),
                adi_intra_choose_x=_int(kv, "adi_intra_choose_x"),
                adi_intra_choose_y=_int(kv, "adi_intra_choose_y"),
                adi_intra_tie=_int(kv, "adi_intra_tie"),
                adi_intra_cost_x=_int(kv, "adi_intra_cost_x"),
                adi_intra_cost_y=_int(kv, "adi_intra_cost_y"),
                adi_intra_cost_chosen=_int(kv, "adi_intra_cost_chosen"),
                adi_intra_cost_delta_abs=_int(kv, "adi_intra_cost_delta_abs"),
                adi_intra_pred_bytes_x=_int(kv, "adi_intra_pred_bytes_x"),
                adi_intra_pred_bytes_y=_int(kv, "adi_intra_pred_bytes_y"),
                adi_intra_pred_bytes_chosen=_int(kv, "adi_intra_pred_bytes_chosen"),
                adi_intra_pred_bytes_delta_abs=_int(kv, "adi_intra_pred_bytes_delta_abs"),
                adi_intra_queue_x=_int(kv, "adi_intra_queue_x"),
                adi_intra_queue_y=_int(kv, "adi_intra_queue_y"),
                adi_intra_queue_chosen=_int(kv, "adi_intra_queue_chosen"),
            )
        )
    return rows


def _parse_nic_rows(log_text: str) -> List[NicRow]:
    rows: List[NicRow] = []
    for line in log_text.splitlines():
        idx = line.find(_NIC_PREFIX)
        if idx < 0:
            continue
        kv = _kv_from_line_tail(line[idx + len(_NIC_PREFIX) :])
        rows.append(
            NicRow(
                node=_int(kv, "node"),
                tx_pkts=_int(kv, "tx_pkts"),
                tx_bytes=_int(kv, "tx_bytes"),
                rx_pkts=_int(kv, "rx_pkts"),
                rx_bytes=_int(kv, "rx_bytes"),
            )
        )
    return rows


def _parse_core_rows(log_text: str) -> List[CoreRow]:
    rows: List[CoreRow] = []
    for line in log_text.splitlines():
        idx = line.find(_TRAFFIC_PREFIX)
        if idx < 0:
            continue
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
                rx_spiketilekey=_int(kv, "rx_spiketilekey"),
                tx_spike_pkts=_int(kv, "tx_spike_pkts"),
                tx_spikekey_pkts=_int(kv, "tx_spikekey_pkts"),
                tx_spiketilekey_pkts=_int(kv, "tx_spiketilekey_pkts"),
                tile_bad_decode=_int(kv, "tile_bad_decode"),
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

    for line in log_text.splitlines():
        idx = line.find(_GROUP_PREFIX)
        if idx < 0:
            continue
        kv = _kv_from_line_tail(line[idx + len(_GROUP_PREFIX) :])
        if "groups_total" in kv:
            return _materialize(kv)

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
        rows.append(
            NocLatRow(
                node=_int(kv, "node"),
                spike_cnt=_int(kv, "spike_cnt"),
                spike_lat_sum=_int(kv, "spike_lat_sum"),
                spike_lat_max=_int(kv, "spike_lat_max"),
                spike_p95=_int(kv, "spike_p95"),
                spike_p99=_int(kv, "spike_p99"),
                spikekey_cnt=_int(kv, "spikekey_cnt"),
                spikekey_lat_sum=_int(kv, "spikekey_lat_sum"),
                spikekey_lat_max=_int(kv, "spikekey_lat_max"),
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


def _nodes_with_rx_key(core_rows: List[CoreRow]) -> int:
    nodes = {r.node for r in core_rows if r.rx_spikekey > 0}
    return len(nodes)


def _derive_summary(
    case_cfg: Dict[str, Any],
    router_rows: List[RouterRow],
    nic_rows: List[NicRow],
    core_rows: List[CoreRow],
) -> Dict[str, Any]:
    return {
        "case": dict(case_cfg),
        "routers": {
            "count": len(router_rows),
            "sum_in": _sum_int(router_rows, "pkts_in"),
            "sum_out": _sum_int(router_rows, "pkts_out"),
            "sum_local": _sum_int(router_rows, "pkts_local"),
            "sum_fwd_xy": _sum_int(router_rows, "pkts_fwd_xy"),
            "sum_bytes_in": _sum_int(router_rows, "bytes_in"),
            "sum_bytes_out": _sum_int(router_rows, "bytes_out"),
            "sum_bytes_local": _sum_int(router_rows, "bytes_local"),
            "sum_bytes_fwd_xy": _sum_int(router_rows, "bytes_fwd_xy"),
            "sum_byte_hops": _sum_int(router_rows, "byte_hops"),
            "sum_spikekey_in": _sum_int(router_rows, "spikekey_in"),
            "sum_stage_inter": _sum_int(router_rows, "spikekey_stage_inter"),
            "sum_stage_intra": _sum_int(router_rows, "spikekey_stage_intra"),
            "sum_clones": _sum_int(router_rows, "spikekey_clones"),
            "sum_adi_inter_decisions": _sum_int(router_rows, "adi_inter_decisions"),
            "sum_adi_inter_choose_x": _sum_int(router_rows, "adi_inter_choose_x"),
            "sum_adi_inter_choose_y": _sum_int(router_rows, "adi_inter_choose_y"),
            "sum_adi_inter_tie": _sum_int(router_rows, "adi_inter_tie"),
            "sum_adi_inter_cost_x": _sum_int(router_rows, "adi_inter_cost_x"),
            "sum_adi_inter_cost_y": _sum_int(router_rows, "adi_inter_cost_y"),
            "sum_adi_inter_cost_chosen": _sum_int(router_rows, "adi_inter_cost_chosen"),
            "sum_adi_inter_cost_delta_abs": _sum_int(router_rows, "adi_inter_cost_delta_abs"),
            "sum_adi_intra_decisions": _sum_int(router_rows, "adi_intra_decisions"),
            "sum_adi_intra_choose_x": _sum_int(router_rows, "adi_intra_choose_x"),
            "sum_adi_intra_choose_y": _sum_int(router_rows, "adi_intra_choose_y"),
            "sum_adi_intra_tie": _sum_int(router_rows, "adi_intra_tie"),
            "sum_adi_intra_cost_x": _sum_int(router_rows, "adi_intra_cost_x"),
            "sum_adi_intra_cost_y": _sum_int(router_rows, "adi_intra_cost_y"),
            "sum_adi_intra_cost_chosen": _sum_int(router_rows, "adi_intra_cost_chosen"),
            "sum_adi_intra_cost_delta_abs": _sum_int(router_rows, "adi_intra_cost_delta_abs"),
            "sum_adi_intra_pred_bytes_x": _sum_int(router_rows, "adi_intra_pred_bytes_x"),
            "sum_adi_intra_pred_bytes_y": _sum_int(router_rows, "adi_intra_pred_bytes_y"),
            "sum_adi_intra_pred_bytes_chosen": _sum_int(router_rows, "adi_intra_pred_bytes_chosen"),
            "sum_adi_intra_pred_bytes_delta_abs": _sum_int(router_rows, "adi_intra_pred_bytes_delta_abs"),
            "sum_adi_intra_queue_x": _sum_int(router_rows, "adi_intra_queue_x"),
            "sum_adi_intra_queue_y": _sum_int(router_rows, "adi_intra_queue_y"),
            "sum_adi_intra_queue_chosen": _sum_int(router_rows, "adi_intra_queue_chosen"),
        },
        "nics": {
            "count": len(nic_rows),
            "sum_tx_pkts": _sum_int(nic_rows, "tx_pkts"),
            "sum_tx_bytes": _sum_int(nic_rows, "tx_bytes"),
            "sum_rx_pkts": _sum_int(nic_rows, "rx_pkts"),
            "sum_rx_bytes": _sum_int(nic_rows, "rx_bytes"),
        },
        "cores": {
            "count": len(core_rows),
            "sum_tx_batches": _sum_int(core_rows, "tx_batches"),
            "sum_tx_pre_total": _sum_int(core_rows, "tx_pre_total"),
            "sum_rx_spike": _sum_int(core_rows, "rx_spike"),
            "sum_rx_spikekey": _sum_int(core_rows, "rx_spikekey"),
            "sum_rx_spiketilekey": _sum_int(core_rows, "rx_spiketilekey"),
            "sum_tx_spike_pkts": _sum_int(core_rows, "tx_spike_pkts"),
            "sum_tx_spikekey_pkts": _sum_int(core_rows, "tx_spikekey_pkts"),
            "sum_tx_spiketilekey_pkts": _sum_int(core_rows, "tx_spiketilekey_pkts"),
            "sum_tile_bad_decode": _sum_int(core_rows, "tile_bad_decode"),
            "sum_sk_ok": _sum_int(core_rows, "sk_ok"),
            "sum_sk_bad": _sum_int(core_rows, "sk_bad"),
            "nodes_with_rx_key": _nodes_with_rx_key(core_rows),
        },
    }


def _validate_case(summary: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errs: List[str] = []
    case = summary.get("case", {})
    multicast_enable = int(case.get("MULTICAST_ENABLE", 0))
    spiketile_enable = int(case.get("EXPERIMENTAL_SPIKETILE_ENABLE", 0))

    if summary["cores"]["sum_sk_bad"] != 0:
        errs.append(f"sk_bad!=0 (sum_sk_bad={summary['cores']['sum_sk_bad']})")

    if multicast_enable != 0:
        if summary["cores"]["sum_rx_spikekey"] <= 0:
            errs.append("multicast enabled but rx_spikekey==0")
        if summary["routers"]["sum_clones"] <= 0:
            errs.append("multicast enabled but router clones==0")
        if summary["cores"]["nodes_with_rx_key"] < 2:
            errs.append("multicast enabled but rx_key only on <2 nodes")
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

        if spiketile_enable != 0:
            if summary["cores"]["sum_rx_spiketilekey"] <= 0:
                errs.append("spiketile enabled but rx_spiketilekey==0")
            if summary["cores"]["sum_tile_bad_decode"] != 0:
                errs.append(f"spiketile enabled but tile_bad_decode!=0 (tile_bad_decode={summary['cores']['sum_tile_bad_decode']})")
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


def _run_one_case(repo_root: str, out_dir: str, case_cfg: Dict[str, Any], sst_bin: str) -> Dict[str, Any]:
    model = os.path.join("NoCexp", "spiketile_router_lab", "test_mesh_4x4_key_tile_multicast.py")
    env = os.environ.copy()
    env.update({k: str(v) for k, v in case_cfg.items()})

    cmd = [sst_bin, model]
    res = subprocess.run(cmd, cwd=repo_root, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log_text = res.stdout or ""

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "sst.log"), "w") as f:
        f.write(log_text)

    router_rows = _parse_router_rows(log_text)
    nic_rows = _parse_nic_rows(log_text)
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
            "bytes_in",
            "bytes_out",
            "bytes_local",
            "bytes_fwd_xy",
            "byte_hops",
            "spikekey_in",
            "stage_inter",
            "stage_intra",
            "clones",
            "adi_inter_decisions",
            "adi_inter_choose_x",
            "adi_inter_choose_y",
            "adi_inter_tie",
            "adi_inter_cost_x",
            "adi_inter_cost_y",
            "adi_inter_cost_chosen",
            "adi_inter_cost_delta_abs",
            "adi_intra_decisions",
            "adi_intra_choose_x",
            "adi_intra_choose_y",
            "adi_intra_tie",
            "adi_intra_cost_x",
            "adi_intra_cost_y",
            "adi_intra_cost_chosen",
            "adi_intra_cost_delta_abs",
            "adi_intra_pred_bytes_x",
            "adi_intra_pred_bytes_y",
            "adi_intra_pred_bytes_chosen",
            "adi_intra_pred_bytes_delta_abs",
            "adi_intra_queue_x",
            "adi_intra_queue_y",
            "adi_intra_queue_chosen",
        ],
        [
            {
                "node": r.node,
                "in": r.pkts_in,
                "out": r.pkts_out,
                "local": r.pkts_local,
                "fwd_xy": r.pkts_fwd_xy,
                "bytes_in": r.bytes_in,
                "bytes_out": r.bytes_out,
                "bytes_local": r.bytes_local,
                "bytes_fwd_xy": r.bytes_fwd_xy,
                "byte_hops": r.byte_hops,
                "spikekey_in": r.spikekey_in,
                "stage_inter": r.spikekey_stage_inter,
                "stage_intra": r.spikekey_stage_intra,
                "clones": r.spikekey_clones,
                "adi_inter_decisions": r.adi_inter_decisions,
                "adi_inter_choose_x": r.adi_inter_choose_x,
                "adi_inter_choose_y": r.adi_inter_choose_y,
                "adi_inter_tie": r.adi_inter_tie,
                "adi_inter_cost_x": r.adi_inter_cost_x,
                "adi_inter_cost_y": r.adi_inter_cost_y,
                "adi_inter_cost_chosen": r.adi_inter_cost_chosen,
                "adi_inter_cost_delta_abs": r.adi_inter_cost_delta_abs,
                "adi_intra_decisions": r.adi_intra_decisions,
                "adi_intra_choose_x": r.adi_intra_choose_x,
                "adi_intra_choose_y": r.adi_intra_choose_y,
                "adi_intra_tie": r.adi_intra_tie,
                "adi_intra_cost_x": r.adi_intra_cost_x,
                "adi_intra_cost_y": r.adi_intra_cost_y,
                "adi_intra_cost_chosen": r.adi_intra_cost_chosen,
                "adi_intra_cost_delta_abs": r.adi_intra_cost_delta_abs,
                "adi_intra_pred_bytes_x": r.adi_intra_pred_bytes_x,
                "adi_intra_pred_bytes_y": r.adi_intra_pred_bytes_y,
                "adi_intra_pred_bytes_chosen": r.adi_intra_pred_bytes_chosen,
                "adi_intra_pred_bytes_delta_abs": r.adi_intra_pred_bytes_delta_abs,
                "adi_intra_queue_x": r.adi_intra_queue_x,
                "adi_intra_queue_y": r.adi_intra_queue_y,
                "adi_intra_queue_chosen": r.adi_intra_queue_chosen,
            }
            for r in sorted(router_rows, key=lambda x: x.node)
        ],
    )
    _write_csv(
        os.path.join(out_dir, "nics.csv"),
        ["node", "tx_pkts", "tx_bytes", "rx_pkts", "rx_bytes"],
        [
            {
                "node": r.node,
                "tx_pkts": r.tx_pkts,
                "tx_bytes": r.tx_bytes,
                "rx_pkts": r.rx_pkts,
                "rx_bytes": r.rx_bytes,
            }
            for r in sorted(nic_rows, key=lambda x: x.node)
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
            "rx_spiketilekey",
            "tx_spike_pkts",
            "tx_spikekey_pkts",
            "tx_spiketilekey_pkts",
            "tile_bad_decode",
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
                "rx_spiketilekey": r.rx_spiketilekey,
                "tx_spike_pkts": r.tx_spike_pkts,
                "tx_spikekey_pkts": r.tx_spikekey_pkts,
                "tx_spiketilekey_pkts": r.tx_spiketilekey_pkts,
                "tile_bad_decode": r.tile_bad_decode,
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
            "spike_p95",
            "spike_p99",
            "spikekey_cnt",
            "spikekey_lat_sum",
            "spikekey_lat_max",
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
                "spike_p95": r.spike_p95,
                "spike_p99": r.spike_p99,
                "spikekey_cnt": r.spikekey_cnt,
                "spikekey_lat_sum": r.spikekey_lat_sum,
                "spikekey_lat_max": r.spikekey_lat_max,
                "spikekey_p95": r.spikekey_p95,
                "spikekey_p99": r.spikekey_p99,
                "hist_max": r.hist_max,
                "spike_overflow": r.spike_overflow,
                "spikekey_overflow": r.spikekey_overflow,
            }
            for r in sorted(noc_lat_rows, key=lambda x: x.node)
        ],
    )

    summary = _derive_summary(case_cfg, router_rows, nic_rows, core_rows)
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
    summary["sst"] = {"returncode": res.returncode, "ok": bool(ok and res.returncode == 0), "validation_errors": errs}
    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Run SpikeKey vs SpikeTileKey under MulticastRouter backend (A/B/C).")
    ap.add_argument("--sim-time", type=str, default="300us")
    ap.add_argument("--seeds", type=int, nargs="+", default=[1])
    ap.add_argument("--block-w", type=int, default=2)
    ap.add_argument("--block-h", type=int, default=2)
    ap.add_argument("--traffic-period-cycles", type=int, default=200)
    ap.add_argument("--traffic-batch-size", type=int, default=8)
    ap.add_argument("--traffic-stop-cycle", type=int, default=20000, help="Stop traffic injection at given cycle (0=never)")
    ap.add_argument("--traffic-stop-fraction", type=float, default=0.0, help="Stop traffic injection at fraction of sim_time (0=disabled)")
    ap.add_argument("--enable-all", action="store_true", help="Enable traffic injection on all cores")
    ap.add_argument("--src-node", type=int, default=0)
    ap.add_argument("--src-core", type=int, default=0)
    ap.add_argument("--ingress-policy", type=str, default="hash4", choices=["top_left", "top_right", "bottom_left", "bottom_right", "hash4"])
    ap.add_argument("--inter-policy", type=str, default="xy", choices=["xy", "yx", "hash_xy", "adaptive_xy_yx"])
    ap.add_argument("--intra-policy", type=str, default="manhattan_x_first", choices=["manhattan_x_first", "manhattan_y_first", "adaptive"])
    ap.add_argument("--adaptive-telemetry-enable", action="store_true")
    ap.add_argument("--adaptive-inter-w-wait", type=int, default=1)
    ap.add_argument("--adaptive-inter-w-service", type=int, default=1)
    ap.add_argument("--adaptive-inter-w-len", type=int, default=0)
    ap.add_argument("--adaptive-intra-w-bytes", type=int, default=1)
    ap.add_argument("--adaptive-intra-w-queue", type=int, default=1)
    ap.add_argument("--link-latency", type=str, default="5ns")
    ap.add_argument("--router-latency-cycles", type=int, default=0)
    ap.add_argument("--router-serialize-enable", action="store_true")
    ap.add_argument("--router-serialize-service-cycles", type=int, default=16)
    ap.add_argument("--router-serialize-byte-enable", action="store_true")
    ap.add_argument("--router-serialize-bytes-per-cycle", type=int, default=16)
    ap.add_argument("--router-serialize-header-bytes", type=int, default=24)
    ap.add_argument("--noc-lat-hist-max", type=int, default=262144)
    ap.add_argument("--edges-csv", type=str, default="", help="Override EDGES_CSV used by the model script (optional)")
    ap.add_argument("--spiketile-block-cols", type=int, default=64)
    ap.add_argument("--spiketile-max-pre-bits", type=int, default=64)
    ap.add_argument("--compact-variants", action="store_true", help="Also run compact-mask variants (B/C with EXPERIMENTAL_COMPACT_MASK_ENABLE=1)")
    ap.add_argument("--inter-bundle-variants", action="store_true", help="Also run inter-block bundle variants (B/C with EXPERIMENTAL_INTER_BUNDLE_ENABLE=1)")
    ap.add_argument("--inter-bundle-v2-enable", action="store_true", help="Enable EXPERIMENTAL_INTER_BUNDLE_V2_ENABLE for all cases")
    ap.add_argument("--inter-bundle-max-entries", type=int, default=64)
    ap.add_argument("--local-endpoint-multicast-enable", action="store_true", help="Enable LOCAL_ENDPOINT_MULTICAST_ENABLE for router->NIC local fanout")
    ap.add_argument("--sst-bin", type=str, default="", help="Path to sst executable (default: repo_root/sst)")
    ap.add_argument("--tag", type=str, default="")
    args = ap.parse_args()

    stop_cycle = int(args.traffic_stop_cycle)
    if stop_cycle <= 0 and args.traffic_stop_fraction and args.traffic_stop_fraction > 0.0 and args.traffic_stop_fraction < 1.0:
        sim_ns = _parse_time_to_ns(args.sim_time)
        if sim_ns > 0:
            stop_cycle = int(sim_ns * float(args.traffic_stop_fraction))

    repo_root = _repo_root()
    sst_bin = os.path.abspath(args.sst_bin) if args.sst_bin else os.path.join(repo_root, "sst")
    if not os.path.isfile(sst_bin) or not os.access(sst_bin, os.X_OK):
        raise RuntimeError(f"invalid sst binary: {sst_bin}")

    runs_root = os.path.join(repo_root, "NoCexp", "spiketile_router_lab", "runs")
    os.makedirs(runs_root, exist_ok=True)

    ts = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"{ts}_{args.tag}" if args.tag else ts
    out_root = os.path.join(runs_root, run_id)
    os.makedirs(out_root, exist_ok=True)

    suite_cfg = {
        "MESH_W": 4,
        "MESH_H": 4,
        "NUM_CORES_PER_PE": 4,
        "NEURONS_PER_CORE": 64,
        "MULTICAST_BLOCK_W": int(args.block_w),
        "MULTICAST_BLOCK_H": int(args.block_h),
        "MULTICAST_INGRESS_POLICY": args.ingress_policy,
        "MULTICAST_INTER_POLICY": args.inter_policy,
        "MULTICAST_INTRA_POLICY": args.intra_policy,
        "ADAPTIVE_TELEMETRY_ENABLE": 1 if args.adaptive_telemetry_enable else 0,
        "ADAPTIVE_INTER_W_WAIT": int(args.adaptive_inter_w_wait),
        "ADAPTIVE_INTER_W_SERVICE": int(args.adaptive_inter_w_service),
        "ADAPTIVE_INTER_W_LEN": int(args.adaptive_inter_w_len),
        "ADAPTIVE_INTRA_W_BYTES": int(args.adaptive_intra_w_bytes),
        "ADAPTIVE_INTRA_W_QUEUE": int(args.adaptive_intra_w_queue),
        "MAPPING_ASSUME_BLOCK_IDS": 0,
        "LINK_LATENCY": args.link_latency,
        "ROUTER_LATENCY_CYCLES": int(args.router_latency_cycles),
        "ROUTER_SERIALIZE_ENABLE": 1 if args.router_serialize_enable else 0,
        "ROUTER_SERIALIZE_SERVICE_CYCLES": int(args.router_serialize_service_cycles),
        "ROUTER_SERIALIZE_BYTE_ENABLE": 1 if args.router_serialize_byte_enable else 0,
        "ROUTER_SERIALIZE_BYTES_PER_CYCLE": int(args.router_serialize_bytes_per_cycle),
        "ROUTER_SERIALIZE_HEADER_BYTES": int(args.router_serialize_header_bytes),
        "LOCAL_ENDPOINT_MULTICAST_ENABLE": 1 if args.local_endpoint_multicast_enable else 0,
        "NIC_VERBOSE": 1,
        "NOC_LAT_HIST_MAX": int(args.noc_lat_hist_max),
        "SIM_TIME": args.sim_time,
        "TRAFFIC_PERIOD_CYCLES": int(args.traffic_period_cycles),
        "TRAFFIC_BATCH_SIZE": int(args.traffic_batch_size),
        "TRAFFIC_STOP_CYCLE": int(stop_cycle),
        "TRAFFIC_SRC_NODE": int(args.src_node),
        "TRAFFIC_SRC_CORE": int(args.src_core),
        "TRAFFIC_ENABLE_ALL": 1 if args.enable_all else 0,
        "SPIKEY_CHECK_ENABLE": 1,
        "SPIKEY_CHECK_FATAL": 1,
        "SPIKEY_CHECK_LOG_CAP": 8,
        "SPIKEY_GROUP_LOG_CAP": 8,
        "EXPERIMENTAL_INTER_BUNDLE_V2_ENABLE": 1 if args.inter_bundle_v2_enable else 0,
    }
    if args.edges_csv:
        suite_cfg["EDGES_CSV"] = os.path.abspath(args.edges_csv)

    suite_summary: Dict[str, Any] = {"run_id": run_id, "out_root": os.path.relpath(out_root, repo_root), "cases": []}
    exit_code = 0

    variants = [
        ("A_unicast_spike", {"MULTICAST_ENABLE": 0, "EXPERIMENTAL_SPIKETILE_ENABLE": 0}),
        ("B_spikekey_multicast", {"MULTICAST_ENABLE": 1, "EXPERIMENTAL_SPIKETILE_ENABLE": 0}),
        (
            "C_spiketilekey_multicast",
            {
                "MULTICAST_ENABLE": 1,
                "EXPERIMENTAL_SPIKETILE_ENABLE": 1,
                "EXPERIMENTAL_SPIKETILE_BLOCK_COLS": int(args.spiketile_block_cols),
                "EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS": int(args.spiketile_max_pre_bits),
            },
        ),
    ]
    if args.compact_variants:
        variants.extend(
            [
                (
                    "B_spikekey_multicast_compact",
                    {
                        "MULTICAST_ENABLE": 1,
                        "EXPERIMENTAL_SPIKETILE_ENABLE": 0,
                        "EXPERIMENTAL_COMPACT_MASK_ENABLE": 1,
                    },
                ),
                (
                    "C_spiketilekey_multicast_compact",
                    {
                        "MULTICAST_ENABLE": 1,
                        "EXPERIMENTAL_SPIKETILE_ENABLE": 1,
                        "EXPERIMENTAL_SPIKETILE_BLOCK_COLS": int(args.spiketile_block_cols),
                        "EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS": int(args.spiketile_max_pre_bits),
                        "EXPERIMENTAL_COMPACT_MASK_ENABLE": 1,
                    },
                ),
            ]
        )
    if args.inter_bundle_variants:
        variants.extend(
            [
                (
                    "B_spikekey_multicast_bundle",
                    {
                        "MULTICAST_ENABLE": 1,
                        "EXPERIMENTAL_SPIKETILE_ENABLE": 0,
                        "EXPERIMENTAL_INTER_BUNDLE_ENABLE": 1,
                        "EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES": int(args.inter_bundle_max_entries),
                    },
                ),
                (
                    "C_spiketilekey_multicast_bundle",
                    {
                        "MULTICAST_ENABLE": 1,
                        "EXPERIMENTAL_SPIKETILE_ENABLE": 1,
                        "EXPERIMENTAL_SPIKETILE_BLOCK_COLS": int(args.spiketile_block_cols),
                        "EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS": int(args.spiketile_max_pre_bits),
                        "EXPERIMENTAL_INTER_BUNDLE_ENABLE": 1,
                        "EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES": int(args.inter_bundle_max_entries),
                    },
                ),
            ]
        )
    if args.compact_variants and args.inter_bundle_variants:
        variants.extend(
            [
                (
                    "B_spikekey_multicast_bundle_compact",
                    {
                        "MULTICAST_ENABLE": 1,
                        "EXPERIMENTAL_SPIKETILE_ENABLE": 0,
                        "EXPERIMENTAL_COMPACT_MASK_ENABLE": 1,
                        "EXPERIMENTAL_INTER_BUNDLE_ENABLE": 1,
                        "EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES": int(args.inter_bundle_max_entries),
                    },
                ),
                (
                    "C_spiketilekey_multicast_bundle_compact",
                    {
                        "MULTICAST_ENABLE": 1,
                        "EXPERIMENTAL_SPIKETILE_ENABLE": 1,
                        "EXPERIMENTAL_SPIKETILE_BLOCK_COLS": int(args.spiketile_block_cols),
                        "EXPERIMENTAL_SPIKETILE_MAX_PRE_BITS": int(args.spiketile_max_pre_bits),
                        "EXPERIMENTAL_COMPACT_MASK_ENABLE": 1,
                        "EXPERIMENTAL_INTER_BUNDLE_ENABLE": 1,
                        "EXPERIMENTAL_INTER_BUNDLE_MAX_ENTRIES": int(args.inter_bundle_max_entries),
                    },
                ),
            ]
        )

    for seed in args.seeds:
        for case_name, extra in variants:
            case_dir = os.path.join(out_root, f"{case_name}_seed{seed}")
            case_cfg = dict(suite_cfg)
            case_cfg.update({"TRAFFIC_SEED": int(seed)})
            case_cfg.update(extra)

            summary = _run_one_case(repo_root, case_dir, case_cfg, sst_bin)
            suite_summary["cases"].append(
                {
                    "name": case_name,
                    "seed": int(seed),
                    "dir": os.path.relpath(case_dir, repo_root),
                    "ok": bool(summary["sst"]["ok"]),
                    "routers_sum_out": int(summary["routers"]["sum_out"]),
                    "routers_sum_fwd_xy": int(summary["routers"]["sum_fwd_xy"]),
                    "routers_sum_local": int(summary["routers"]["sum_local"]),
                    "routers_sum_bytes_out": int(summary["routers"]["sum_bytes_out"]),
                    "routers_sum_bytes_fwd_xy": int(summary["routers"]["sum_bytes_fwd_xy"]),
                    "routers_sum_bytes_local": int(summary["routers"]["sum_bytes_local"]),
                    "routers_sum_byte_hops": int(summary["routers"]["sum_byte_hops"]),
                    "routers_sum_clones": int(summary["routers"]["sum_clones"]),
                    "routers_sum_adi_inter_decisions": int(summary["routers"]["sum_adi_inter_decisions"]),
                    "routers_sum_adi_inter_choose_x": int(summary["routers"]["sum_adi_inter_choose_x"]),
                    "routers_sum_adi_inter_choose_y": int(summary["routers"]["sum_adi_inter_choose_y"]),
                    "routers_sum_adi_inter_tie": int(summary["routers"]["sum_adi_inter_tie"]),
                    "routers_sum_adi_inter_cost_chosen": int(summary["routers"]["sum_adi_inter_cost_chosen"]),
                    "routers_sum_adi_inter_cost_delta_abs": int(summary["routers"]["sum_adi_inter_cost_delta_abs"]),
                    "routers_sum_adi_intra_decisions": int(summary["routers"]["sum_adi_intra_decisions"]),
                    "routers_sum_adi_intra_choose_x": int(summary["routers"]["sum_adi_intra_choose_x"]),
                    "routers_sum_adi_intra_choose_y": int(summary["routers"]["sum_adi_intra_choose_y"]),
                    "routers_sum_adi_intra_tie": int(summary["routers"]["sum_adi_intra_tie"]),
                    "routers_sum_adi_intra_cost_chosen": int(summary["routers"]["sum_adi_intra_cost_chosen"]),
                    "routers_sum_adi_intra_cost_delta_abs": int(summary["routers"]["sum_adi_intra_cost_delta_abs"]),
                    "routers_sum_adi_intra_pred_bytes_chosen": int(summary["routers"]["sum_adi_intra_pred_bytes_chosen"]),
                    "routers_sum_adi_intra_pred_bytes_delta_abs": int(summary["routers"]["sum_adi_intra_pred_bytes_delta_abs"]),
                    "routers_sum_adi_intra_queue_chosen": int(summary["routers"]["sum_adi_intra_queue_chosen"]),
                    "nics_sum_tx_pkts": int(summary["nics"]["sum_tx_pkts"]),
                    "nics_sum_tx_bytes": int(summary["nics"]["sum_tx_bytes"]),
                    "nics_sum_rx_pkts": int(summary["nics"]["sum_rx_pkts"]),
                    "nics_sum_rx_bytes": int(summary["nics"]["sum_rx_bytes"]),
                    "cores_sum_tx_pre": int(summary["cores"]["sum_tx_pre_total"]),
                    "cores_sum_rx_spike": int(summary["cores"]["sum_rx_spike"]),
                    "cores_sum_rx_spikekey": int(summary["cores"]["sum_rx_spikekey"]),
                    "cores_sum_rx_spiketilekey": int(summary["cores"]["sum_rx_spiketilekey"]),
                    "cores_sum_tx_spike_pkts": int(summary["cores"]["sum_tx_spike_pkts"]),
                    "cores_sum_tx_spikekey_pkts": int(summary["cores"]["sum_tx_spikekey_pkts"]),
                    "cores_sum_tx_spiketilekey_pkts": int(summary["cores"]["sum_tx_spiketilekey_pkts"]),
                    "tile_bad_decode": int(summary["cores"]["sum_tile_bad_decode"]),
                    "p95": int(summary.get("noc_lat", {}).get("max_spikekey_p95" if case_cfg["MULTICAST_ENABLE"] else "max_spike_p95", 0)),
                    "p99": int(summary.get("noc_lat", {}).get("max_spikekey_p99" if case_cfg["MULTICAST_ENABLE"] else "max_spike_p99", 0)),
                    "validation_errors": list(summary["sst"]["validation_errors"]),
                }
            )
            if not summary["sst"]["ok"]:
                exit_code = 2

    with open(os.path.join(out_root, "suite_summary.json"), "w") as f:
        json.dump(suite_summary, f, indent=2, sort_keys=True)

    print(f"[suite] out_dir={os.path.relpath(out_root, repo_root)} cases={len(suite_summary['cases'])} exit={exit_code}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
