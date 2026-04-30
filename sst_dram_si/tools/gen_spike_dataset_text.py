#!/usr/bin/env python3
import argparse, os, random, math

"""
生成 SpikeSource(TEXT) 数据集。
两种格式：
- idts   : 每行 "neuron_id timestamp"（默认，与现有实现兼容）
- srcdst : 每行 "src_neuron_id dest_neuron_id timestamp"（用于固定扇出K）

示例：
  # idts（随机选取 3% 神经元各发 1 条事件）
  python3 sst_dram_si/tools/gen_spike_dataset_text.py \
    --neurons 10000 --firing 0.03 --out sst_dram_si/outputs_large/paper2/dram_N10k/spikes.txt \
    --seed 123 --timestamp 0 --format idts

  # srcdst（随机选取 3% 源神经元，每个源 fanout=256 个目的）
  python3 sst_dram_si/tools/gen_spike_dataset_text.py \
    --neurons 10000 --firing 0.03 --out sst_dram_si/outputs_large/paper2/dram_N10k/spikes_srcdst.txt \
    --seed 123 --timestamp 0 --format srcdst --fanout 256
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--neurons', type=int, required=True, help='总神经元数 N')
    ap.add_argument('--firing', type=float, default=0.03, help='发放比例 [0..1]')
    ap.add_argument('--out', required=True, help='输出TEXT路径')
    ap.add_argument('--seed', type=int, default=0, help='随机种子（0表示不设定）')
    ap.add_argument('--timestamp', type=int, default=0, help='脉冲时间戳（us）')
    ap.add_argument('--format', type=str, default='idts', choices=['idts','srcdst'], help='输出格式')
    ap.add_argument('--fanout', type=int, default=256, help='srcdst 模式下每源的扇出K')
    args = ap.parse_args()

    N = int(args.neurons)
    p = float(args.firing)
    T = int(args.timestamp)
    M = max(1, int(math.floor(N * p)))
    rnd = random.Random(args.seed if args.seed else None)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    if args.format == 'idts':
        ids = rnd.sample(range(N), M) if M < N else list(range(N))
        ids.sort()
        with open(args.out, 'w', encoding='utf-8') as f:
            for nid in ids:
                f.write(f"{nid} {T}\n")
        print(f"[OK] spikes(TEXT idts) written: {args.out}  (N={N}, firing={p}, spikes={M}, ts={T})")
    else:
        # srcdst：随机选择 M 个源，每个源 fanout=K（去重）
        K = max(1, int(args.fanout))
        srcs = rnd.sample(range(N), M) if M < N else list(range(N))
        srcs.sort()
        with open(args.out, 'w', encoding='utf-8') as f:
            for src in srcs:
                if K >= N:
                    dsts = list(range(N))
                else:
                    dsts = rnd.sample(range(N), K)
                for dst in dsts:
                    f.write(f"{src} {dst} {T}\n")
        print(f"[OK] spikes(TEXT srcdst) written: {args.out}  (N={N}, firing={p}, sources={M}, fanout={K}, ts={T})")

if __name__ == '__main__':
    main()
