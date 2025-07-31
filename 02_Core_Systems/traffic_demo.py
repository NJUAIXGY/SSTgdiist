#!/usr/bin/env python3
"""
网络流量统计演示脚本
展示混合Miranda网格系统的网络监控能力 (不依赖SST模块)
"""

# 临时禁用SST导入
import sys
from unittest.mock import MagicMock
sys.modules['sst'] = MagicMock()

from hybrid_miranda_mesh import HybridMirandaMesh

def demo_traffic_analysis():
    """演示网络流量分析功能"""
    print("🚀 启动网络流量统计演示...")
    print("="*60)
    
    # 创建混合系统 (不使用SST统计以避免冲突)
    mesh = HybridMirandaMesh(enable_sst_stats=False, verbose=False)
    
    print("\n📡 生成多样化的网络流量...")
    
    # 1. 高频小数据包通信
    print("  • 高频小数据包通信")
    for i in range(5):
        mesh.send_message(0, 0, 1, 1, f"高频通信 {i}", size_bytes=64)
        mesh.send_message(1, 1, 0, 0, f"响应 {i}", size_bytes=32)
    
    # 2. 大数据传输
    print("  • 大数据传输")
    mesh.send_message(0, 0, 3, 3, "大数据传输", size_bytes=4096)
    mesh.send_message(3, 3, 0, 0, "大数据响应", size_bytes=2048)
    
    # 3. 内存请求流量
    print("  • 内存请求流量")
    mesh.send_message(1, 1, 3, 3, "内存访问请求", memory_request=True, size_bytes=1024)
    mesh.send_message(2, 2, 3, 3, "缓存缺失请求", memory_request=True, size_bytes=512)
    
    # 4. 分散的小数据包
    print("  • 分散的小数据包")
    for x in range(4):
        for y in range(4):
            if (x, y) != (0, 0):  # 不发送给源节点自己
                mesh.send_message(0, 0, x, y, f"广播到({x},{y})", size_bytes=16)
    
    print(f"\n⚙️  运行网络模拟...")
    # 运行模拟
    mesh.simulate(steps=8)
    
    print(f"\n📊 网络流量分析报告:")
    print("="*60)
    
    # 生成完整的流量分析报告
    mesh.print_statistics()
    
    print(f"\n🔍 详细流量矩阵分析:")
    mesh.get_traffic_matrix()
    
    print(f"\n🔥 网络热点分析:")
    mesh.analyze_hotspots()
    
    print(f"\n💾 导出统计数据...")
    mesh.export_sst_statistics()
    
    print(f"\n✅ 网络流量统计演示完成！")
    print("="*60)
    
    return mesh

if __name__ == "__main__":
    demo_traffic_analysis()
