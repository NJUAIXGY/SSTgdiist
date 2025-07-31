#!/usr/bin/env python3
"""
SST启动脚本 - 混合Miranda Mesh系统
使用SST框架运行真实的merlin.hr_router网络组件
"""

import sst
from hybrid_miranda_mesh import HybridMirandaMesh

def main():
    """SST启动脚本主函数"""
    print("=== SST混合Miranda Mesh系统启动 ===")
    
    # 配置SST运行时参数
    print("配置SST运行时参数...")
    
    # 设置统计输出
    sst.setStatisticLoadLevel(5)
    sst.setStatisticOutput("sst.statOutputCSV", {
        "filepath": "./sst_simulation_stats.csv"
    })
    
    # 启用SST组件统计
    sst.enableAllStatisticsForComponentType("merlin.hr_router")
    sst.enableAllStatisticsForComponentType("merlin.test_nic")
    sst.enableAllStatisticsForComponentType("merlin.linkcontrol")
    
    print("创建混合Miranda Mesh系统...")
    
    # 创建混合系统 (仅构建SST组件，不运行逻辑模拟)
    mesh = HybridMirandaMesh(
        mesh_size_x=4,
        mesh_size_y=4,
        cpu_clock="2.4GHz",
        cache_size="32KiB", 
        memory_size="128MiB",
        link_bandwidth="40GiB/s",
        link_latency="50ps",
        enable_sst_stats=True,
        verbose=True
    )
    
    print("✅ SST混合系统构建完成!")
    print("🚀 系统将由SST核心接管并开始硬件模拟...")
    
    # SST将自动运行硬件模拟
    # 不需要手动调用模拟循环，SST会处理所有时钟推进
    
if __name__ == "__main__":
    main()
