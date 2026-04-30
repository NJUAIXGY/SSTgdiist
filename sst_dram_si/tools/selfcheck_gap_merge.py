#!/usr/bin/env python3
"""
Self-check for GAS fine-grained merge (gap/Lmax) and bank_row grouping.

This script does NOT run SST. It re-implements the core merging logic used in
GatherBufferIF Iter-A to validate correctness on synthetic address sequences.

Rules under test (correctness only; no tuning):
  - Group reads by (bank,row) when bank extraction is configured, otherwise by row only.
  - Sort by address within group; scan to form continuous segments (bursts).
  - If next read starts after current segment end by a GAP (x):
      * If gap_merge_enable and x <= k and new_len <= Lmax: absorb the gap into the burst.
      * Else: flush current burst; start a new burst at the next read.
  - Result bursts are contiguous [base, end) byte ranges; unique_bytes=sum of all burst sizes.

Parameters:
  - row_bytes_guess: used to compute rowIndex = addr // row_bytes_guess
  - bank_bits/bank_shift: used to compute bankIndex = (addr >> bank_shift) & ((1<<bank_bits)-1)

Usage:
  python3 selfcheck_gap_merge.py  # runs built-in testcases and prints results
"""

from dataclasses import dataclass
from typing import List, Tuple, Dict

@dataclass
class Params:
    gap_merge_enable: bool = True
    gap_k_bytes: int = 2048
    burst_bytes_max: int = 64 * 1024
    row_bytes_guess: int = 8192
    bank_bits: int = 0
    bank_shift: int = 0

def row_index(addr: int, p: Params) -> int:
    return addr // max(1, p.row_bytes_guess)

def bank_index(addr: int, p: Params) -> int:
    if p.bank_bits <= 0:
        return 0
    mask = (1 << p.bank_bits) - 1
    return (addr >> p.bank_shift) & mask

def group_key(addr: int, p: Params) -> Tuple[int, int]:
    return (bank_index(addr, p), row_index(addr, p))

def merge_reads(reads: List[Tuple[int,int]], p: Params) -> Tuple[List[Tuple[int,int]], int, int]:
    """Merge (addr,size) reads into contiguous bursts. Returns (bursts, unique_bytes, gap_absorbed)."""
    # Group reads by (bank,row)
    buckets: Dict[Tuple[int,int], List[Tuple[int,int]]] = {}
    for addr,size in reads:
        buckets.setdefault(group_key(addr, p), []).append((addr,size))

    bursts: List[Tuple[int,int]] = []
    gap_abs_sum = 0

    for key, vec in buckets.items():
        vec.sort(key=lambda x: x[0])
        cur_base = None
        cur_end = None
        for addr,size in vec:
            if cur_base is None:
                cur_base, cur_end = addr, addr + size
                continue
            if addr <= cur_end:
                # overlap/adjacent
                if addr + size > cur_end:
                    cur_end = addr + size
                continue
            # gap
            gap = addr - cur_end
            new_len = (addr + size) - cur_base
            if p.gap_merge_enable and p.gap_k_bytes > 0 and gap <= p.gap_k_bytes and new_len <= p.burst_bytes_max:
                cur_end = addr + size
                gap_abs_sum += gap
            else:
                bursts.append((cur_base, cur_end - cur_base))
                cur_base, cur_end = addr, addr + size
        if cur_base is not None:
            bursts.append((cur_base, cur_end - cur_base))

    unique_bytes = sum(sz for _,sz in bursts)
    return bursts, unique_bytes, gap_abs_sum

def fmt(bursts: List[Tuple[int,int]]) -> str:
    return ", ".join(f"[0x{b:08x},{sz}]" for b,sz in bursts)

def run_case(name: str, reads: List[Tuple[int,int]], p: Params):
    bursts, ub, gap = merge_reads(reads, p)
    print(f"\n== {name} ==")
    print(f"reads: {len(reads)}  bursts: {len(bursts)}  unique_bytes: {ub}  gap_absorbed: {gap}")
    print(f"bursts: {fmt(bursts)}")

def main():
    p = Params()

    # Case 1: Same row, small gaps (<k), should merge into one burst
    base = 0x10000
    reads1 = [
        (base + 0, 64),
        (base + 256, 64),    # gap=192 <= 2048, merge
        (base + 4096, 128),  # gap=3840 <= 2048? No -> new burst
    ]
    run_case("same-row small-gaps & one large gap", reads1, p)

    # Case 2: Exceed Lmax -> must split
    p2 = Params(gap_merge_enable=True, gap_k_bytes=2048, burst_bytes_max=1024)
    reads2 = [ (0x20000 + i*64, 64) for i in range(40) ]  # 2560 bytes total
    run_case("exceed Lmax -> split", reads2, p2)

    # Case 3: Cross row boundary -> different bursts (row_bytes_guess=8192)
    reads3 = [ (0x30000 + 8000, 64), (0x30000 + 9000, 64) ]  # cross 8KB boundary
    run_case("cross row boundary", reads3, p)

    # Case 4: bank_row grouping (bank_bits=4, shift=16)
    p4 = Params(gap_merge_enable=True, gap_k_bytes=1024, burst_bytes_max=4096, bank_bits=4, bank_shift=16)
    reads4 = [
        (0x40000 + 0x0000, 64),
        (0x40000 + 0x0100, 64),  # same bank, same row if shift matches
        (0x40000 + (1<<16), 64), # different bank -> separate bucket
    ]
    run_case("bank_row buckets", reads4, p4)

if __name__ == '__main__':
    main()

