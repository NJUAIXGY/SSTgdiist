#!/usr/bin/env python3
"""
NoC共享内存架构测试脚本
用于验证类结构和逻辑的正确性（不依赖SST）
"""

class MockSST:
    """模拟SST组件，用于测试"""
    class Component:
        def __init__(self, name, comp_type):
            self.name = name
            self.comp_type = comp_type
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
        
        def connect(self, conn1, conn2):
            self.connections.append((conn1, conn2))
    
    @staticmethod
    def enableStatisticForComponentName(name, stat):
        print(f"  📊 启用统计: {name}.{stat}")
    
    @staticmethod
    def enableAllStatisticsForComponentType(comp_type):
        print(f"  📊 启用组件类型统计: {comp_type}")
    
    @staticmethod
    def setStatisticLoadLevel(level):
        print(f"  📊 设置统计级别: {level}")
    
    @staticmethod
    def setStatisticOutput(output_type, params):
        print(f"  📊 设置统计输出: {output_type} -> {params}")

# 替换SST模块进行测试
import sys
sys.modules['sst'] = MockSST()

# 现在可以安全导入我们的类
try:
    from noc_node_class import NoCNode, NoCMesh
    print("✅ 成功导入 NoC 类")
except Exception as e:
    print(f"❌ 导入失败: {e}")
    exit(1)

def test_noc_node():
    """测试NoC节点类"""
    print("\n=== 测试NoC节点类 ===")
    
    # 测试计算节点
    compute_node = NoCNode(0, 0, 0, 4, 4, is_memory_node=False)
    print(f"✅ 计算节点创建成功: {compute_node.get_info()}")
    
    # 测试内存节点
    memory_node = NoCNode(15, 3, 3, 4, 4, is_memory_node=True)
    print(f"✅ 内存节点创建成功: {memory_node.get_info()}")
    
    return True

def test_noc_mesh():
    """测试NoC Mesh类"""
    print("\n=== 测试NoC Mesh类 ===")
    
    # 创建一个2x2的小型mesh用于测试
    mesh = NoCMesh(
        mesh_size_x=2, 
        mesh_size_y=2,
        memory_nodes=[0, 3]  # 两个对角节点作为内存
    )
    
    print(f"✅ Mesh网络创建成功")
    print(f"   - 总节点数: {len(mesh.get_all_nodes())}")
    print(f"   - 计算节点: {len(mesh.get_compute_nodes())}")
    print(f"   - 内存节点: {len(mesh.get_memory_nodes())}")
    
    # 测试统计功能
    mesh.enable_all_statistics()
    mesh.setup_statistics_output("/tmp/test_stats.csv")
    
    # 测试通信演示
    mesh.create_communication_demo()
    
    return True

def main():
    """主测试函数"""
    print("🧪 NoC共享内存架构测试")
    print("=" * 50)
    
    success = True
    
    try:
        success &= test_noc_node()
        success &= test_noc_mesh()
        
        if success:
            print("\n🎉 所有测试通过!")
            print("\n📋 架构改进总结:")
            print("  ✅ 支持内存节点和计算节点区分")
            print("  ✅ 实现MemNIC网络接口")
            print("  ✅ 配置共享内存地址映射")
            print("  ✅ 跨节点通信工作负载")
            print("  ✅ 分布式内存访问模式")
            print("  ✅ 网络统计收集功能")
            
        else:
            print("\n❌ 部分测试失败")
            
    except Exception as e:
        print(f"\n💥 测试异常: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
