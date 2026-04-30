#!/usr/bin/env python3
import argparse, os, random

"""
生成固定扇出K的边列表（edges_csv）用于单PE/多PE映射：
- 输出格式：src_global,dst_global[,weight]
- 单PE：global_id = local_id
- 多PE：需根据 mesh/每PE行数自行换算（本工具仅在单PE下使用即可）

用法示例：
  python3 sst_dram_si/tools/gen_fixed_fanout_edges.py \
      --neurons 10000 --fanout 256 --out sst_dram_si/outputs_large/paper2/dram_N10k/edges.csv \
      --seed 123
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--neurons', type=int, required=True, help='总神经元数（单PE）')
    ap.add_argument('--fanout', type=int, default=256, help='每源神经元扇出K')
    ap.add_argument('--out', required=True, help='输出CSV路径')
    ap.add_argument('--seed', type=int, default=0, help='随机种子（0表示不设定）')
    ap.add_argument('--local-only', action='store_true', help='目的全在本PE（默认）')
    args = ap.parse_args()

    N = int(args.neurons)
    K = int(args.fanout)
    path = args.out
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rnd = random.Random(args.seed if args.seed else None)

    with open(path, 'w', encoding='utf-8') as f:
        f.write('src_global,dst_global\n')
        for src in range(N):
            # 简单地在 [0,N) 里不放回抽取K个目的；当K接近N时退化为全覆盖
            if K >= N:
                dsts = list(range(N))
                if src < N:
                    # 避免自环可按需过滤；本实验不强制
                    pass
            else:
                dsts = rnd.sample(range(N), K)
            for dst in dsts:
                f.write(f"{src},{dst}\n")
    print(f"[OK] edges_csv written: {path}  (N={N}, K={K})")

if __name__ == '__main__':
    main()

