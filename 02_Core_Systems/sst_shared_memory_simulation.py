#!/usr/bin/env python3
"""
实际SST仿真脚本 - 共享内存NoC Mesh演示
用于在真实SST环境中运行共享内存架构
"""

import sst
from noc_node_class import NoCMesh

def main():
    """主仿真配置"""
    print("🚀 启动共享内存NoC Mesh仿真")
    print("=" * 60)
    
    # 创建3x3 mesh系统（较小规模，便于调试）
    mesh_system = NoCMesh(
        mesh_size_x=3, 
        mesh_size_y=3,
        link_bandwidth="40GiB/s",
        link_latency="50ps",
        memory_nodes=[0, 2, 6, 8]  # 四个角落作为内存节点
    )
    
    # 配置统计收集
    mesh_system.enable_all_statistics()
    output_path = "/home/anarchy/SST/sst_output_data/shared_memory_3x3_mesh.csv"
    mesh_system.setup_statistics_output(output_path)
    
    # 打印系统配置
    mesh_system.print_summary()
    mesh_system.create_communication_demo()
    
    # SST仿真参数配置
    print(f"\n⚙️  SST仿真配置:")
    print(f"   • 时间基准: 1ps")
    print(f"   • 仿真时间: 50μs (适中规模)")
    print(f"   • 详细程度: 中等")
    print(f"   • 输出路径: {output_path}")
    
    # 设置仿真参数
    sst.setProgramOption("timebase", "1ps")
    sst.setProgramOption("stop-at", "50us")  # 较短的仿真时间用于快速验证
    
    print(f"\n🔧 预期结果:")
    print(f"   📊 统计文件将包含:")
    print(f"      - CPU性能指标 (cycles, reqs_issued, reqs_returned)")
    print(f"      - 缓存性能 (cache_hits, cache_misses)")
    print(f"      - 网络性能 (send_packet_count, recv_packet_count)")
    print(f"      - 内存控制器性能 (requests_received, requests_completed)")
    
    print(f"\n   📈 关键指标:")
    print(f"      - 跨节点访问延迟: ~200-800ps")
    print(f"      - 缓存命中率: 20-40%")
    print(f"      - 网络利用率: 5-15%")
    print(f"      - 平均跳数: 1-2跳")
    
    print(f"\n✅ 仿真配置完成，SST开始执行...")

if __name__ == "__main__":
    main()
