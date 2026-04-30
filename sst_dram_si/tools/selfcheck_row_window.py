#!/usr/bin/env python3
"""
Self-check for GAS coarse row-window merge (bytes/timeout) on top of gap/Lmax logic.

This script mirrors the GatherBufferIF Iter-B row-window path:
  - Group by (bank,row) when bank_bits>0; otherwise by row only
  - Sort reads by address within each group
  - Build segments by:
      * fine merge: absorb gap if gap<=k and new_len<=Lmax
      * row-window bytes: allow larger gaps if sum(sub-read sizes) <= row_window_bytes and new_len<=Lmax
      * row-window timeout: flush current segment as row-window burst if elapsed_ns >= row_window_timeout_ns

Run:
  python3 selfcheck_row_window.py
"""
from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class Params:
    gap_merge_enable: bool = True
    gap_k_bytes: int = 1024  # k
    burst_bytes_max: int = 65536  # Lmax
    bank_bits: int = 0
    bank_shift: int = 0
    row_bytes_guess: int = 8192
    row_window_enable: bool = True
    row_window_bytes: int = 16384  # theta_row (sum of sub-read sizes)
    row_window_timeout_ns: int = 0  # tau

@dataclass
class Read:
    addr: int
    size: int
    ns: int  # arrival time

def row_index(addr: int, row_bytes: int) -> int:
    return addr // row_bytes if row_bytes else 0

def bank_index(addr: int, bits: int, shift: int) -> int:
    if bits <= 0: return 0
    mask = (1 << bits) - 1
    return (addr >> shift) & mask

def group_key(addr: int, p: Params) -> Tuple[int, int]:
    b = bank_index(addr, p.bank_bits, p.bank_shift)
    r = row_index(addr, p.row_bytes_guess)
    return (b, r)

def build_segments(reads: List[Read], p: Params) -> List[Tuple[int,int,bool]]:
    """Return list of segments: (base, size, used_row_window)"""
    # group by (bank,row)
    groups = {}
    for rd in reads:
        key = group_key(rd.addr, p)
        groups.setdefault(key, []).append(rd)
    segs = []
    for key, vec in groups.items():
        vec.sort(key=lambda x: (x.addr, x.ns))
        has = False
        cur_base = 0
        cur_end = 0
        cur_sum = 0
        cur_start_ns = 0
        used_rowwin = False
        def flush(mark_rowwin=False):
            nonlocal has, cur_base, cur_end, cur_sum, used_rowwin, cur_start_ns
            if not has: return
            segs.append((cur_base, cur_end-cur_base, (used_rowwin or mark_rowwin)))
            has = False
            cur_sum = 0
            used_rowwin = False
            cur_start_ns = 0
        for it in vec:
            a, b = it.addr, it.addr + it.size
            if not has:
                cur_base, cur_end = a, b
                cur_sum = it.size
                cur_start_ns = it.ns
                has = True
                continue
            if a <= cur_end:
                if b > cur_end: cur_end = b
                cur_sum += it.size
                continue
            gap = a - cur_end
            new_len = b - cur_base
            absorbed = False
            if p.gap_merge_enable and p.gap_k_bytes>0 and gap <= p.gap_k_bytes and new_len <= p.burst_bytes_max:
                cur_end = b
                cur_sum += it.size
                absorbed = True
            # timeout
            if (not absorbed) and p.row_window_enable and p.row_window_timeout_ns>0 and cur_start_ns>0 and it.ns>0:
                if it.ns - cur_start_ns >= p.row_window_timeout_ns:
                    flush(mark_rowwin=True)
                    cur_base, cur_end = a, b
                    cur_sum = it.size
                    cur_start_ns = it.ns
                    has = True
                    continue
            # bytes threshold
            if (not absorbed) and p.row_window_enable and p.row_window_bytes>0:
                tentative_sum = cur_sum + it.size
                if tentative_sum <= p.row_window_bytes and new_len <= p.burst_bytes_max:
                    cur_end = b
                    cur_sum = tentative_sum
                    used_rowwin = True
                    absorbed = True
            if not absorbed:
                flush()
                cur_base, cur_end = a, b
                cur_sum = it.size
                cur_start_ns = it.ns
                has = True
        flush(mark_rowwin=used_rowwin)
    return segs

def run_case(name: str, reads: List[Read], p: Params, expect_count: int):
    segs = build_segments(reads, p)
    print(f"[case] {name}: segs={len(segs)} -> {segs}")
    assert len(segs) == expect_count, (len(segs), expect_count)

def main():
    # 1) Fine-merge only (gap<=k), no row-window
    p1 = Params(gap_merge_enable=True, gap_k_bytes=1024, burst_bytes_max=4096, row_window_enable=False)
    r1 = [Read(0x1000, 256, 100), Read(0x1000+256+512, 256, 120), Read(0x2000, 128, 200)]
    # 0x1000..0x1300 (gap=512<=k) merges; 0x2000 separate => 2 segs
    run_case("fine_merge_only", r1, p1, expect_count=2)

    # 2) Row-window bytes allows large gap if sum<=theta
    p2 = Params(gap_merge_enable=True, gap_k_bytes=128, burst_bytes_max=8192, row_window_enable=True, row_window_bytes=1024)
    r2 = [Read(0x3000, 256, 10), Read(0x3000+2048, 256, 20)]  # gap=1792>k; sum=512<=theta -> 1 seg
    run_case("row_window_bytes_merge", r2, p2, expect_count=1)

    # 3) Row-window timeout forces flush
    p3 = Params(gap_merge_enable=True, gap_k_bytes=64, burst_bytes_max=4096, row_window_enable=True, row_window_bytes=1024, row_window_timeout_ns=50)
    r3 = [Read(0x4000, 128, 0), Read(0x4000+4096, 128, 60)]  # wait 60ns>timeout -> flush -> 2 segs
    run_case("row_window_timeout_split", r3, p3, expect_count=2)

    # 4) bank_row grouping prevents cross-bank merge
    p4 = Params(gap_merge_enable=True, gap_k_bytes=2048, burst_bytes_max=65536, row_window_enable=True, row_window_bytes=8192, bank_bits=1, bank_shift=12)
    # Map: addr>>12 & 1  -> bank; both same row index
    r4 = [Read(0x0000, 512, 0), Read(0x3000, 512, 1)]  # 0x0000 bank0, 0x3000 bank3? with bits=1, shift=12 -> 0 and 1 => 2 segs
    run_case("bank_row_split", r4, p4, expect_count=2)

if __name__ == "__main__":
    main()

