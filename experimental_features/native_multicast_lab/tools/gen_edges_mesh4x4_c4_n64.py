#!/usr/bin/env python3

import argparse
import csv
import os


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate deterministic edges CSV for SpikeKey multicast tests.")
    parser.add_argument("--mesh-w", type=int, default=4)
    parser.add_argument("--mesh-h", type=int, default=4)
    parser.add_argument("--cores", type=int, default=4)
    parser.add_argument("--neurons-per-core", type=int, default=64)
    parser.add_argument("--out", type=str, default="")
    parser.add_argument("--edges-per-block", type=int, default=2, help="edges per block per pre (default 2)")
    parser.add_argument(
        "--in-block-mode",
        type=str,
        default="single_pe",
        choices=["single_pe", "spread"],
        help="How to place destinations within each 2x2 block: single_pe (all edges hit 1 PE) or spread (spread across PEs).",
    )
    args = parser.parse_args()

    if args.mesh_w <= 0 or args.mesh_h <= 0:
        raise SystemExit("invalid mesh shape")
    if args.cores <= 0 or args.neurons_per_core <= 0:
        raise SystemExit("invalid core/neuron layout")
    if args.edges_per_block <= 0:
        raise SystemExit("edges-per-block must be > 0")

    total_nodes = args.mesh_w * args.mesh_h
    if total_nodes != 16:
        raise SystemExit("this generator currently targets 4x4 (16 nodes) only")
    neurons_per_pe = args.cores * args.neurons_per_core
    global_neurons = total_nodes * neurons_per_pe

    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_out = os.path.join(os.path.dirname(script_dir), "edges", "mesh4x4_c4_n64_edges.csv")
    out_path = os.path.abspath(args.out) if args.out else default_out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    # 2x2 blocks on 4x4 mesh (top-left, top-right, bottom-left, bottom-right)
    blocks = [
        [0, 1, 4, 5],
        [2, 3, 6, 7],
        [8, 9, 12, 13],
        [10, 11, 14, 15],
    ]

    def pick_pe_single(pre: int, block_id: int) -> int:
        idx = (pre ^ (block_id * 0x9E3779B9)) & 0xFFFFFFFF
        return blocks[block_id][idx % 4]

    def pick_pe_spread(pre: int, block_id: int, k: int) -> int:
        # Spread edges across the 4 PEs of the 2x2 block with a stable per-pre rotation.
        rot = (pre ^ (block_id * 0x9E3779B9)) & 0xFFFFFFFF
        return blocks[block_id][(rot + k) % 4]

    rows_written = 0
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["src", "dst", "w"])
        for pre in range(global_neurons):
            post_base = pre % args.neurons_per_core
            for block_id in range(4):
                for k in range(args.edges_per_block):
                    if args.in_block_mode == "spread":
                        dest_pe = pick_pe_spread(pre, block_id, k)
                    else:
                        dest_pe = pick_pe_single(pre, block_id)
                    dest_core = (pre + dest_pe + k) % args.cores
                    post_local = (post_base + k) % args.neurons_per_core
                    dst = dest_pe * neurons_per_pe + dest_core * args.neurons_per_core + post_local
                    w.writerow([pre, dst, "1.0"])
                    rows_written += 1

    print(
        f"[gen-edges] wrote {rows_written} edges to {out_path} (global_neurons={global_neurons} "
        f"edges_per_block={args.edges_per_block} in_block_mode={args.in_block_mode})"
    )


if __name__ == "__main__":
    main()
