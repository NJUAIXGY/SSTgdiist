#!/usr/bin/env python3
"""
Miranda CPU Mesh System 使用示例

展示如何使用封装的MirandaCPUMeshSystem类来创建和配置系统
"""

from miranda_cpu_mesh_system import MirandaCPUMeshSystem, build_and_configure_system


def example_basic_usage():
    """
    示例1: 基本使用方法
    """
    print("=== 示例1: 基本使用方法 ===")
    
    # 创建系统实例
    mesh_system = MirandaCPUMeshSystem(
        mesh_size_x=4,
        mesh_size_y=4,
        link_bandwidth="40GiB/s",
        output_dir="/home/anarchy/SST/sst_output_data"
    )
    
    # 构建系统
    mesh_system.build_system()
    
    # 配置仿真参数
    mesh_system.configure_simulation(
        simulation_time="100us",
        enable_statistics=True,
        output_filename="example1_stats.csv"
    )
    
    return mesh_system


def example_custom_workload():
    """
    示例2: 自定义工作负载配置
    """
    print("\n=== 示例2: 自定义工作负载配置 ===")
    
    # 创建系统实例
    mesh_system = MirandaCPUMeshSystem(
        mesh_size_x=3,
        mesh_size_y=3,
        link_bandwidth="20GiB/s",
        cpu_clock="3.0GHz",
        cache_size="64KiB",
        verbose=True
    )
    
    # 自定义工作负载配置
    custom_compute_config = {
        "generator": "miranda.GUPSGenerator",
        "max_reqs_cycle": "3",
        "params": {
            "verbose": "1",
            "count": "5000",     # 增加请求数量
            "max_address": "1048576",  # 增加地址空间
            "min_address": "0",
            "iterations": "100"   # 增加迭代次数
        },
        "description": "高性能计算核心 - 增强型GUPS测试"
    }
    
    # 设置自定义工作负载
    mesh_system.set_workload_config("compute_core", custom_compute_config)
    
    # 构建和配置系统
    mesh_system.build_system()
    mesh_system.configure_simulation(
        simulation_time="200us",
        output_filename="example2_custom_stats.csv"
    )
    
    return mesh_system


def example_large_system():
    """
    示例3: 大规模系统配置
    """
    print("\n=== 示例3: 大规模系统配置 ===")
    
    # 创建8x8大规模系统
    mesh_system = MirandaCPUMeshSystem(
        mesh_size_x=8,
        mesh_size_y=8,
        link_bandwidth="100GiB/s",
        link_latency="20ps",
        cpu_clock="4.0GHz",
        cache_size="128KiB",
        memory_size="256MiB",
        verbose=True
    )
    
    # 构建和配置系统
    mesh_system.build_system()
    mesh_system.configure_simulation(
        simulation_time="500us",
        output_filename="example3_large_system_stats.csv"
    )
    
    # 打印系统信息
    system_info = mesh_system.get_system_info()
    print(f"\n系统信息:")
    print(f"  - 总节点数: {system_info['total_nodes']}")
    print(f"  - Mesh规模: {system_info['mesh_size']}")
    print(f"  - CPU时钟: {system_info['cpu_clock']}")
    print(f"  - 缓存大小: {system_info['cache_size']}")
    
    return mesh_system


def example_quick_build():
    """
    示例4: 使用便利函数快速构建
    """
    print("\n=== 示例4: 使用便利函数快速构建 ===")
    
    # 使用便利函数一步构建和配置系统
    mesh_system = build_and_configure_system(
        mesh_size_x=6,
        mesh_size_y=4,
        simulation_time="150us",
        link_bandwidth="60GiB/s",
        cpu_clock="2.8GHz",
        output_dir="/home/anarchy/SST/sst_output_data",
        verbose=True
    )
    
    # 获取组件引用
    components = mesh_system.get_components()
    print(f"\n组件数量:")
    print(f"  - 路由器: {len(components['routers'])}")
    print(f"  - CPU核心: {len(components['cpu_cores'])}")
    print(f"  - L1缓存: {len(components['l1_caches'])}")
    print(f"  - 内存控制器: {len(components['memory_controllers'])}")
    
    return mesh_system


def example_minimal_system():
    """
    示例5: 最小化系统（用于测试）
    """
    print("\n=== 示例5: 最小化系统（用于测试） ===")
    
    # 创建2x2最小系统
    mesh_system = MirandaCPUMeshSystem(
        mesh_size_x=2,
        mesh_size_y=2,
        simulation_time="50us",
        verbose=True
    )
    
    mesh_system.build_system()
    mesh_system.configure_simulation(
        simulation_time="50us",
        output_filename="example5_minimal_stats.csv"
    )
    
    return mesh_system


def main():
    """
    主函数：运行所有示例
    注意：在实际SST环境中，每次只能运行一个系统配置
    """
    print("Miranda CPU Mesh System 使用示例")
    print("=" * 50)
    
    # 在实际使用中，请只选择一个示例运行
    # 因为SST在一个脚本中只能配置一个系统
    
    # 选择要运行的示例（取消注释其中一个）
    system = example_basic_usage()
    # system = example_custom_workload()
    # system = example_large_system()
    # system = example_quick_build()
    # system = example_minimal_system()
    
    print(f"\n✅ 系统配置完成！")
    print("🚀 开始仿真...")


if __name__ == "__main__":
    main()
