#!/usr/bin/env python3
"""
Miranda CPU Mesh System 测试脚本

用于测试封装类的基本功能（非SST环境下的测试）
"""

import sys
import os

# 模拟SST模块（用于非SST环境测试）
class MockSST:
    class Component:
        def __init__(self, name, component_type):
            self.name = name
            self.type = component_type
            self.params = {}
            self.subcomponents = {}
            
        def addParams(self, params):
            self.params.update(params)
            
        def setSubComponent(self, name, comp_type):
            sub = MockSST.Component(f"{self.name}_{name}", comp_type)
            self.subcomponents[name] = sub
            return sub
    
    class Link:
        def __init__(self, name):
            self.name = name
            self.connections = []
            
        def connect(self, *args):
            self.connections.extend(args)
    
    @staticmethod
    def setStatisticLoadLevel(level):
        print(f"设置统计级别: {level}")
    
    @staticmethod
    def setStatisticOutput(output_type, params):
        print(f"设置统计输出: {output_type}, 参数: {params}")
    
    @staticmethod
    def enableAllStatisticsForComponentType(comp_type):
        print(f"启用组件类型统计: {comp_type}")
    
    @staticmethod
    def enableStatisticForComponentName(comp_name, stat_name):
        pass  # 静默处理以减少输出
    
    @staticmethod
    def setProgramOption(option, value):
        print(f"设置程序选项: {option} = {value}")

# 在非SST环境中使用模拟模块
if 'sst' not in sys.modules:
    sys.modules['sst'] = MockSST()

# 现在可以导入我们的类
try:
    from miranda_cpu_mesh_system import MirandaCPUMeshSystem, build_and_configure_system
    print("✅ 成功导入 MirandaCPUMeshSystem 类")
except ImportError as e:
    print(f"❌ 导入失败: {e}")
    sys.exit(1)


def test_basic_functionality():
    """测试基本功能"""
    print("\n=== 测试基本功能 ===")
    
    try:
        # 创建系统实例
        system = MirandaCPUMeshSystem(
            mesh_size_x=2,
            mesh_size_y=2,
            verbose=True
        )
        print("✅ 成功创建系统实例")
        
        # 获取系统信息
        info = system.get_system_info()
        print(f"✅ 系统信息: 总节点数 = {info['total_nodes']}")
        
        # 构建系统
        system.build_system()
        print("✅ 成功构建系统")
        
        # 配置仿真
        system.configure_simulation()
        print("✅ 成功配置仿真")
        
        # 检查组件数量
        components = system.get_components()
        expected_count = system.total_nodes
        
        assert len(components['routers']) == expected_count, f"路由器数量错误: 期望{expected_count}, 实际{len(components['routers'])}"
        assert len(components['cpu_cores']) == expected_count, f"CPU核心数量错误: 期望{expected_count}, 实际{len(components['cpu_cores'])}"
        assert len(components['l1_caches']) == expected_count, f"L1缓存数量错误: 期望{expected_count}, 实际{len(components['l1_caches'])}"
        assert len(components['memory_controllers']) == expected_count, f"内存控制器数量错误: 期望{expected_count}, 实际{len(components['memory_controllers'])}"
        
        print("✅ 组件数量验证通过")
        
        return True
        
    except Exception as e:
        print(f"❌ 基本功能测试失败: {e}")
        return False


def test_custom_workload():
    """测试自定义工作负载"""
    print("\n=== 测试自定义工作负载 ===")
    
    try:
        system = MirandaCPUMeshSystem(mesh_size_x=2, mesh_size_y=2, verbose=False)
        
        # 设置自定义工作负载
        custom_config = {
            "generator": "miranda.CustomGenerator",
            "max_reqs_cycle": "5",
            "params": {
                "count": "1000",
                "iterations": "10"
            },
            "description": "测试自定义配置"
        }
        
        system.set_workload_config("compute_core", custom_config)
        
        # 验证配置已更新
        config = system.workload_configs["compute_core"]
        assert config["generator"] == "miranda.CustomGenerator", "工作负载配置更新失败"
        assert config["max_reqs_cycle"] == "5", "工作负载参数更新失败"
        
        print("✅ 自定义工作负载配置成功")
        return True
        
    except Exception as e:
        print(f"❌ 自定义工作负载测试失败: {e}")
        return False


def test_different_sizes():
    """测试不同网格大小"""
    print("\n=== 测试不同网格大小 ===")
    
    test_cases = [
        (2, 2, 4),
        (3, 3, 9),
        (4, 4, 16),
        (2, 4, 8),
    ]
    
    for x, y, expected_total in test_cases:
        try:
            system = MirandaCPUMeshSystem(
                mesh_size_x=x,
                mesh_size_y=y,
                verbose=False
            )
            
            assert system.total_nodes == expected_total, f"节点总数计算错误: {x}x{y} 应该是 {expected_total}"
            
            system.build_system()
            components = system.get_components()
            
            assert len(components['routers']) == expected_total, f"路由器数量错误"
            
            print(f"✅ {x}x{y} 网格测试通过 (总节点: {expected_total})")
            
        except Exception as e:
            print(f"❌ {x}x{y} 网格测试失败: {e}")
            return False
    
    return True


def test_convenience_function():
    """测试便利函数"""
    print("\n=== 测试便利函数 ===")
    
    try:
        system = build_and_configure_system(
            mesh_size_x=3,
            mesh_size_y=3,
            simulation_time="50us",
            verbose=False
        )
        
        assert system.system_built, "系统应该已经构建"
        assert system.statistics_configured, "统计应该已经配置"
        
        info = system.get_system_info()
        assert info['total_nodes'] == 9, "便利函数创建的系统节点数错误"
        
        print("✅ 便利函数测试成功")
        return True
        
    except Exception as e:
        print(f"❌ 便利函数测试失败: {e}")
        return False


def test_error_handling():
    """测试错误处理"""
    print("\n=== 测试错误处理 ===")
    
    try:
        system = MirandaCPUMeshSystem(verbose=False)
        
        # 尝试在未构建系统时配置仿真
        try:
            system.configure_simulation(enable_statistics=False)
            system.configure_simulation()  # 应该抛出错误
            print("❌ 应该抛出错误但没有")
            return False
        except RuntimeError:
            print("✅ 正确处理了未构建系统的错误")
        
        # 正常构建后应该成功
        system.build_system()
        system.configure_simulation()
        print("✅ 正常流程工作正常")
        
        return True
        
    except Exception as e:
        print(f"❌ 错误处理测试失败: {e}")
        return False


def main():
    """运行所有测试"""
    print("Miranda CPU Mesh System 类功能测试")
    print("=" * 50)
    
    tests = [
        ("基本功能", test_basic_functionality),
        ("自定义工作负载", test_custom_workload),
        ("不同网格大小", test_different_sizes),
        ("便利函数", test_convenience_function),
        ("错误处理", test_error_handling),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n🧪 运行测试: {test_name}")
        if test_func():
            passed += 1
            print(f"✅ {test_name} 测试通过")
        else:
            print(f"❌ {test_name} 测试失败")
    
    print(f"\n{'='*50}")
    print(f"测试结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！类封装工作正常。")
        return 0
    else:
        print("⚠️ 部分测试失败，请检查实现。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
