#!/usr/bin/env python3
"""
基于类的Miranda CPU Mesh系统 - 直接替换版本

这个脚本使用封装的MirandaCPUMeshSystem类来替换原始的脚本功能
保持相同的系统配置和行为，但使用面向对象的方式组织代码
"""

from miranda_cpu_mesh_system import MirandaCPUMeshSystem

# 使用类创建与原始脚本相同的4x4 Mesh系统
def main():
    """
    创建与原始cpu_mesh_miranda.py相同配置的系统
    """
    # 创建系统实例，使用与原始脚本相同的参数
    mesh_system = MirandaCPUMeshSystem(
        mesh_size_x=4,
        mesh_size_y=4,
        link_bandwidth="40GiB/s",
        link_latency="50ps",
        cpu_clock="2.4GHz",
        cache_size="32KiB",
        memory_size="128MiB",
        output_dir="/home/anarchy/SST/sst_output_data",
        verbose=True
    )
    
    # 构建系统（包含所有CPU核心、路由器、缓存和内存）
    mesh_system.build_system()
    
    # 配置仿真参数（与原始脚本相同）
    mesh_system.configure_simulation(
        simulation_time="100us",
        enable_statistics=True,
        output_filename="miranda_mesh_stats.csv"
    )

if __name__ == "__main__":
    main()
