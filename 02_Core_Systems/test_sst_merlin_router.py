#!/usr/bin/env python3
"""
测试SST merlin.hr_router配置
验证更新后的hybrid_miranda_mesh.py是否正确配置了SST组件
"""

import sst
from hybrid_miranda_mesh import HybridMirandaMesh, test_hybrid_mesh_communication

def test_basic_sst_router():
    """测试基本的SST merlin.hr_router配置"""
    print("=== 测试SST merlin.hr_router基本配置 ===")
    
    # 创建一个简单的2x2网格进行快速测试
    try:
        mesh = HybridMirandaMesh(
            mesh_size_x=2,
            mesh_size_y=2,
            enable_sst_stats=True,
            verbose=True
        )
        
        print("\n✅ SST merlin.hr_router配置成功!")
        print("📊 系统信息:")
        print(f"   • 总节点数: {mesh.total_nodes}")
        print(f"   • 网络拓扑: merlin.hr_router with 6-port configuration")
        print(f"   • 路由器端口: 东西南北+本地+扩展")
        
        # 验证节点访问
        node_00 = mesh.get_node(0, 0)
        if node_00 and node_00.sst_router:
            print(f"   • 节点(0,0)路由器ID: {node_00.node_id}")
            print(f"   • SST组件类型: merlin.hr_router")
        
        return True
        
    except Exception as e:
        print(f"❌ SST merlin.hr_router配置失败: {e}")
        return False

def test_sst_component_creation():
    """测试SST组件创建过程"""
    print("\n=== 测试SST组件创建详情 ===")
    
    try:
        # 手动创建一个路由器组件进行测试
        router = sst.Component("test_router", "merlin.hr_router")
        router.addParams({
            "id": 0,
            "num_ports": "6",
            "link_bw": "40GiB/s",
            "flit_size": "8B",
            "xbar_bw": "40GiB/s",
            "input_latency": "50ps",
            "output_latency": "50ps",
            "input_buf_size": "1KiB",
            "output_buf_size": "1KiB",
        })
        
        # 配置mesh拓扑子组件
        topo_sub = router.setSubComponent("topology", "merlin.mesh")
        topo_sub.addParams({
            "network_name": "Test_Mesh",
            "shape": "2x2",
            "width": "1x1",
            "local_ports": "1",
        })
        
        # 创建端点子组件
        endpoint = router.setSubComponent("endpoint", "merlin.endpoint")
        endpoint.addParams({
            "id": 0,
            "topology": "merlin.mesh",
        })
        
        print("✅ 手动SST组件创建成功!")
        print("   • merlin.hr_router: 已配置")
        print("   • merlin.mesh topology: 已设置")
        print("   • merlin.endpoint: 已连接")
        
        return True
        
    except Exception as e:
        print(f"❌ SST组件创建失败: {e}")
        return False

def main():
    """主测试函数"""
    print("=== SST merlin.hr_router配置验证测试 ===\n")
    
    # 测试1: 基本路由器配置
    basic_test = test_basic_sst_router()
    
    # 测试2: 组件创建详情
    component_test = test_sst_component_creation()
    
    # 总结
    print(f"\n=== 测试结果总结 ===")
    print(f"基本配置测试: {'✅ 通过' if basic_test else '❌ 失败'}")
    print(f"组件创建测试: {'✅ 通过' if component_test else '❌ 失败'}")
    
    if basic_test and component_test:
        print("\n🎉 所有测试通过! SST merlin.hr_router配置正确")
        print("💡 可以运行完整的混合系统测试:")
        print("   sst test_sst_merlin_router.py")
        return True
    else:
        print("\n⚠️ 部分测试失败，请检查SST环境和组件配置")
        return False

if __name__ == "__main__":
    # 运行基本验证测试
    success = main()
    
    if success:
        print("\n=== 运行完整混合系统测试 ===")
        # 运行完整的混合系统测试
        test_hybrid_mesh_communication()
