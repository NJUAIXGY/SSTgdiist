#!/usr/bin/env python3
"""
简单的导入和使用演示

展示如何在其他脚本中导入和使用Miranda CPU Mesh系统类
"""

# 导入类和便利函数
from miranda_cpu_mesh_system import MirandaCPUMeshSystem, build_and_configure_system

def demo_basic_import():
    """演示基本导入和使用"""
    print("=== 基本使用演示 ===")
    
    # 方法1: 使用类构造函数
    system1 = MirandaCPUMeshSystem(
        mesh_size_x=2,
        mesh_size_y=2,
        verbose=True
    )
    
    system1.build_system()
    system1.configure_simulation(simulation_time="50us")
    
    print("✅ 方法1完成: 使用类构造函数")
    
    # 方法2: 使用便利函数（注释掉，因为SST只能运行一个系统）
    # system2 = build_and_configure_system(
    #     mesh_size_x=3,
    #     mesh_size_y=3,
    #     simulation_time="75us"
    # )
    # print("✅ 方法2完成: 使用便利函数")

def demo_custom_config():
    """演示自定义配置（注释版本，供参考）"""
    # 注意：在实际SST环境中，每个脚本只能运行一个系统配置
    # 以下代码仅作为参考示例
    
    print("\n=== 自定义配置示例（仅展示代码） ===")
    
    example_code = '''
    # 创建大型高性能系统
    large_system = MirandaCPUMeshSystem(
        mesh_size_x=8,
        mesh_size_y=8,
        link_bandwidth="100GiB/s",
        cpu_clock="4.0GHz",
        cache_size="128KiB",
        memory_size="512MiB"
    )
    
    # 自定义计算核心工作负载
    high_perf_config = {
        "generator": "miranda.GUPSGenerator",
        "max_reqs_cycle": "4",
        "params": {
            "count": "10000",
            "max_address": "4194304",  # 4MB
            "iterations": "200"
        },
        "description": "高性能计算核心"
    }
    
    large_system.set_workload_config("compute_core", high_perf_config)
    large_system.build_system()
    large_system.configure_simulation(simulation_time="1ms")
    '''
    
    print("示例代码:")
    print(example_code)

def main():
    """主函数"""
    print("Miranda CPU Mesh System 导入演示")
    print("=" * 40)
    
    # 运行基本演示
    demo_basic_import()
    
    # 显示自定义配置示例
    demo_custom_config()
    
    print("\n🎉 演示完成！")
    print("📚 更多示例请参考 example_usage.py")
    print("📖 详细文档请参考 README_CLASS_USAGE.md")

if __name__ == "__main__":
    main()
