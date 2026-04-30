#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SnnDL 性能分析可视化工具

功能：
- 读取profiling CSV数据
- 生成热点函数排行
- 绘制占比饼图和柱状图
- 识别性能瓶颈
- 生成优化建议

使用方法：
    python analyze_profile.py analysis/profile_core0.csv
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib
import sys
import os
from pathlib import Path

# 设置中文字体（可选）
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False


def load_profile_data(csv_path):
    """加载profiling CSV数据"""
    if not os.path.exists(csv_path):
        print(f"Error: File not found: {csv_path}")
        sys.exit(1)

    df = pd.read_csv(csv_path)
    print(f"\n✅ Loaded {len(df)} profile zones from {csv_path}")
    return df


def analyze_hotspots(df, top_n=10):
    """分析热点函数"""
    print("\n" + "=" * 100)
    print(f"  Top {top_n} Hotspots (by Total Time)")
    print("=" * 100)

    # 按总耗时排序
    df_sorted = df.sort_values('total_ms', ascending=False).head(top_n)

    # 计算总耗时（仅顶层zone）
    total_ms = df[df['parent_zone'] == 'ROOT']['total_ms'].sum()
    df_sorted['percent'] = 100.0 * df_sorted['total_ms'] / total_ms

    # 打印表格
    print(f"\n{'Zone Name':<40} {'Calls':>12} {'Total (ms)':>15} {'Avg (us)':>12} {'% Total':>10}")
    print("-" * 100)

    for _, row in df_sorted.iterrows():
        zone_name = row['zone_name']
        if row['parent_zone'] != 'ROOT':
            zone_name = "  └─ " + zone_name

        print(f"{zone_name:<40} {row['call_count']:>12,} "
              f"{row['total_ms']:>15.3f} {row['avg_us']:>12.2f} {row['percent']:>9.1f}%")

    print("-" * 100)
    print(f"Total profiled time: {total_ms:.3f} ms")
    print("=" * 100)

    return df_sorted, total_ms


def plot_pie_chart(df_sorted, output_path, top_n=10):
    """绘制占比饼图"""
    top = df_sorted.head(top_n)

    plt.figure(figsize=(10, 8))
    colors = plt.cm.Set3(range(len(top)))

    # 计算占比
    explode = [0.05 if i == 0 else 0 for i in range(len(top))]  # 突出显示最大瓶颈

    plt.pie(top['total_ms'],
            labels=top['zone_name'],
            autopct='%1.1f%%',
            explode=explode,
            colors=colors,
            startangle=90)

    plt.title(f'Top {top_n} Hotspots by Total Time', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"\n📊 Pie chart saved to: {output_path}")
    plt.close()


def plot_bar_chart(df_sorted, output_path, top_n=10):
    """绘制柱状图"""
    top = df_sorted.head(top_n)

    plt.figure(figsize=(12, 6))
    colors = plt.cm.viridis(top['total_ms'] / top['total_ms'].max())

    plt.barh(range(len(top)), top['total_ms'], color=colors)
    plt.yticks(range(len(top)), top['zone_name'])
    plt.xlabel('Total Time (ms)', fontsize=12)
    plt.title(f'Top {top_n} Functions by Total Time', fontsize=14, fontweight='bold')
    plt.gca().invert_yaxis()  # 最大的在顶部
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"📊 Bar chart saved to: {output_path}")
    plt.close()


def plot_call_count_vs_time(df, output_path):
    """绘制调用次数 vs 总耗时散点图"""
    plt.figure(figsize=(10, 6))

    # 对数坐标（便于查看范围跨度大的数据）
    plt.scatter(df['call_count'], df['total_ms'],
                alpha=0.6, s=100, c=df['avg_us'], cmap='coolwarm')

    plt.xscale('log')
    plt.yscale('log')
    plt.xlabel('Call Count (log scale)', fontsize=12)
    plt.ylabel('Total Time (ms, log scale)', fontsize=12)
    plt.title('Call Count vs Total Time (colored by Avg Time)', fontsize=14, fontweight='bold')
    plt.colorbar(label='Avg Time (us)')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    print(f"📊 Scatter plot saved to: {output_path}")
    plt.close()


def generate_optimization_suggestions(df_sorted, total_ms):
    """生成优化建议"""
    print("\n" + "=" * 100)
    print("  🎯 Optimization Suggestions")
    print("=" * 100)

    top3 = df_sorted.head(3)

    for i, (_, row) in enumerate(top3.iterrows(), 1):
        percent = 100.0 * row['total_ms'] / total_ms
        print(f"\n{i}. {row['zone_name']}")
        print(f"   -占比: {percent:.1f}% ({row['total_ms']:.3f} ms / {total_ms:.3f} ms)")
        print(f"   - 调用次数: {row['call_count']:,}")
        print(f"   - 平均耗时: {row['avg_us']:.2f} us")

        # 根据函数名推荐优化方向
        zone_name = row['zone_name'].lower()

        if 'spike' in zone_name or 'process' in zone_name:
            print(f"   📌 优化方向：脉冲处理路径是核心热点")
            print(f"      - 考虑批量处理脉冲（减少函数调用开销）")
            print(f"      - 优化权重访问模式（缓存预取、批量读取）")

        elif 'weight' in zone_name or 'cache' in zone_name:
            print(f"   📌 优化方向：权重访问/缓存是瓶颈")
            print(f"      - 优化缓存算法（LRU → Clock算法）")
            print(f"      - 增大缓存容量（减少缺失率）")
            print(f"      - 使用GAS窗口模式（批量预取）")

        elif 'neuron' in zone_name or 'update' in zone_name:
            print(f"   📌 优化方向：神经元更新计算密集")
            print(f"      - 使用SIMD指令（AVX2/AVX512）")
            print(f"      - 优化数据布局（SoA而非AoS）")
            print(f"      - 考虑AoSoA分块迭代")

        elif 'memory' in zone_name or 'dram' in zone_name:
            print(f"   📌 优化方向：内存访问延迟高")
            print(f"      - 增加预取深度（提前发起请求）")
            print(f"      - 合并内存请求（减少往返次数）")
            print(f"      - 检查缓存命中率（考虑增大L2）")

        elif 'network' in zone_name or 'batch' in zone_name:
            print(f"   📌 优化方向：网络通信开销大")
            print(f"      - 增大批量大小（减少包数）")
            print(f"      - 使用直接数组索引（避免map查找）")
            print(f"      - 减少序列化开销（float而非double）")

        else:
            print(f"   📌 优化方向：通用建议")
            print(f"      - 分析具体实现，查找瓶颈代码段")
            print(f"      - 添加细粒度profiling（深入代码块级）")

    print("\n" + "=" * 100)


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_profile.py <profile_csv_path>")
        print("Example: python analyze_profile.py analysis/profile_core0.csv")
        sys.exit(1)

    csv_path = sys.argv[1]

    # 输出目录
    output_dir = Path(csv_path).parent
    base_name = Path(csv_path).stem  # 例如：profile_core0

    # 加载数据
    df = load_profile_data(csv_path)

    # 分析热点
    df_sorted, total_ms = analyze_hotspots(df, top_n=15)

    # 绘制图表
    pie_path = output_dir / f"{base_name}_pie.png"
    bar_path = output_dir / f"{base_name}_bar.png"
    scatter_path = output_dir / f"{base_name}_scatter.png"

    plot_pie_chart(df_sorted, pie_path, top_n=10)
    plot_bar_chart(df_sorted, bar_path, top_n=10)
    plot_call_count_vs_time(df, scatter_path)

    # 生成优化建议
    generate_optimization_suggestions(df_sorted, total_ms)

    print("\n✅ Analysis complete!")
    print(f"📂 Results saved to: {output_dir}")


if __name__ == '__main__':
    main()
