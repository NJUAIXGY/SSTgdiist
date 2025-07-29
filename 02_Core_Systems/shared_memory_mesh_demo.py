#!/usr/bin/env python3
"""
共享内存NoC Mesh演示脚本
展示跨节点通信功能的实现
"""

import sst
from noc_node_class import NoCMesh

def main():
    """主演示函数"""
    print("=" * 60)
    print("🚀 共享内存NoC Mesh演示系统")
    print("=" * 60)
    
    # 创建一个4x4的mesh网络，支持共享内存通信
    mesh_system = NoCMesh(
        mesh_size_x=4, 
        mesh_size_y=4,
        link_bandwidth="40GiB/s",
        link_latency="50ps",
        memory_nodes=[0, 3, 12, 15]  # 四个角落作为内存节点
    )
    
    # 配置统计收集
    mesh_system.enable_all_statistics()
    mesh_system.setup_statistics_output("/home/anarchy/SST/sst_output_data/shared_memory_mesh_stats.csv")
    
    # 打印系统配置
    mesh_system.print_summary()
    
    # 创建通信演示
    mesh_system.create_communication_demo()
    
    # 设置仿真参数
    print(f"\n⚙️  仿真配置:")
    print(f"   • 仿真时间: 100μs")
    print(f"   • 统计收集: 全开启")
    print(f"   • 输出格式: CSV")
    
    # SST仿真设置
    sst.setProgramOption("timebase", "1ps")
    sst.setProgramOption("stop-at", "100us")
    
    print(f"\n✅ 系统配置完成，开始仿真...")
    print(f"📊 统计数据将保存到: /home/anarchy/SST/sst_output_data/shared_memory_mesh_stats.csv")

if __name__ == "__main__":
    main()
