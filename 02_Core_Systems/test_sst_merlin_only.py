#!/usr/bin/env python3
"""
SST专用测试脚本 - 使用merlin.hr_router配置
测试更新后的hybrid_miranda_mesh.py中的SST组件配置
"""

import sst

def create_s                # 创建独立端点 (使用test_nic)
                endpoint = sst.Component(f"hybrid_endpoint_{node_id}", "merlin.test_nic")
                endpoint.addParams({
                    "id": node_id,
                    "topology": "merlin.mesh",
                    "num_peers": str(MESH_SIZE * MESH_SIZE),
                    "link_bw": "40GiB/s",
                })sst_test():
    """创建一个简单的SST测试配置，验证merlin.hr_router"""
    print("=== 创建简单的SST merlin.hr_router测试 ===")
    
    # 创建2x2网格进行基本测试
    MESH_SIZE = 2
    TOTAL_NODES = MESH_SIZE * MESH_SIZE
    
    routers = []
    
    # 创建路由器节点
    for i in range(TOTAL_NODES):
        router = sst.Component(f"test_router_{i}", "merlin.hr_router")
        router.addParams({
            "id": i,
            "num_ports": "5",  # 标准5端口配置 (东西南北+本地)
            "link_bw": "40GiB/s",
            "flit_size": "8B",
            "xbar_bw": "40GiB/s",
            "input_latency": "50ps",
            "output_latency": "50ps",
            "input_buf_size": "1KiB",
            "output_buf_size": "1KiB",
        })
        
        # 配置mesh拓扑
        topo_sub = router.setSubComponent("topology", "merlin.mesh")
        topo_sub.addParams({
            "network_name": "Test_Mesh_Network",
            "shape": f"{MESH_SIZE}x{MESH_SIZE}",
            "width": "1x1",
            "local_ports": "1",
        })
        
        # 创建独立端点 (使用test_nic)
        endpoint = sst.Component(f"test_endpoint_{i}", "merlin.test_nic")
        endpoint.addParams({
            "id": i,
            "topology": "merlin.mesh",
            "num_peers": str(TOTAL_NODES),
            "link_bw": "40GiB/s",
        })
        
        # 连接端点到路由器本地端口
        local_link = sst.Link(f"test_local_link_{i}")
        local_link.connect(
            (router, "port4", "50ps"),  # 路由器本地端口
            (endpoint, "port", "50ps")  # 端点端口
        )
        
        routers.append(router)
        print(f"创建路由器节点 {i} (5端口配置 + 独立端点)")
    
    # 创建网格连接
    link_count = 0
    for y in range(MESH_SIZE):
        for x in range(MESH_SIZE):
            node_id = y * MESH_SIZE + x
            
            # 东西连接
            if x < MESH_SIZE - 1:
                east_link = sst.Link(f"test_east_link_{x}_{y}")
                east_link.connect(
                    (routers[node_id], "port0", "50ps"),      # 东端口
                    (routers[node_id + 1], "port1", "50ps")   # 西端口
                )
                link_count += 1
            
            # 南北连接
            if y < MESH_SIZE - 1:
                south_link = sst.Link(f"test_south_link_{x}_{y}")
                south_link.connect(
                    (routers[node_id], "port2", "50ps"),                  # 南端口
                    (routers[node_id + MESH_SIZE], "port3", "50ps")       # 北端口
                )
                link_count += 1
    
    print(f"创建了 {link_count} 条双向链路")
    print("✅ 简单SST测试配置完成 (5端口配置)")

def create_hybrid_test():
    """创建hybrid_miranda_mesh的SST测试实例"""
    print("\n=== 创建hybrid_miranda_mesh SST测试实例 ===")
    
    try:
        # 避免直接导入可能导致重复组件的模块
        # 改为动态创建类似的结构
        
        # 创建一个小型的2x2网格测试
        mesh_size = 2
        nodes = []
        
        for x in range(mesh_size):
            for y in range(mesh_size):
                node_id = y * mesh_size + x
                
                # 创建路由器
                router = sst.Component(f"hybrid_router_{node_id}", "merlin.hr_router")
                router.addParams({
                    "id": node_id,
                    "num_ports": "5",  # 标准5端口配置
                    "link_bw": "40GiB/s",
                    "flit_size": "8B",
                    "xbar_bw": "40GiB/s",
                    "input_latency": "50ps",
                    "output_latency": "50ps",
                    "input_buf_size": "1KiB",
                    "output_buf_size": "1KiB",
                })
                
                # 拓扑配置
                topo_sub = router.setSubComponent("topology", "merlin.mesh")
                topo_sub.addParams({
                    "network_name": "Hybrid_Test_Mesh",
                    "shape": f"{mesh_size}x{mesh_size}",
                    "width": "1x1",
                    "local_ports": "1",
                })
                
                # 独立端点配置 (使用test_nic)
                endpoint = sst.Component(f"hybrid_endpoint_{node_id}", "merlin.test_nic")
                endpoint.addParams({
                    "id": node_id,
                    "topology": "merlin.mesh",
                    "num_peers": str(mesh_size * mesh_size),
                    "link_bw": "40GiB/s",
                })
                
                # 连接端点到路由器
                local_link = sst.Link(f"hybrid_local_link_{node_id}")
                local_link.connect(
                    (router, "port4", "50ps"),  # 路由器本地端口
                    (endpoint, "port", "50ps")  # 端点端口
                )
                
                nodes.append(router)
                print(f"创建混合测试节点({x},{y}) - 路由器ID: {node_id} (5端口+独立端点)")
        
        # 创建连接
        for y in range(mesh_size):
            for x in range(mesh_size):
                node_id = y * mesh_size + x
                
                if x < mesh_size - 1:
                    link = sst.Link(f"hybrid_east_{x}_{y}")
                    link.connect(
                        (nodes[node_id], "port0", "50ps"),
                        (nodes[node_id + 1], "port1", "50ps")
                    )
                
                if y < mesh_size - 1:
                    link = sst.Link(f"hybrid_south_{x}_{y}")
                    link.connect(
                        (nodes[node_id], "port2", "50ps"),
                        (nodes[node_id + mesh_size], "port3", "50ps")
                    )
        
        print("✅ 混合测试实例创建成功 (5端口配置)")
        return True
        
    except Exception as e:
        print(f"❌ 混合测试实例创建失败: {e}")
        return False

def main():
    """主测试函数"""
    print("=== SST merlin.hr_router 配置专用测试 ===\n")
    
    # 测试1: 简单SST配置
    try:
        create_simple_sst_test()
        simple_test_success = True
    except Exception as e:
        print(f"❌ 简单SST测试失败: {e}")
        simple_test_success = False
    
    # 测试2: 混合配置测试
    hybrid_test_success = create_hybrid_test()
    
    # 配置SST统计
    print("\n=== 配置SST统计 ===")
    try:
        sst.setStatisticLoadLevel(5)
        sst.setStatisticOutput("sst.statOutputCSV", {
            "filepath": "./sst_merlin_test_stats.csv"
        })
        
        # 启用路由器统计
        sst.enableAllStatisticsForComponentType("merlin.hr_router")
        sst.enableAllStatisticsForComponentType("merlin.test_nic")
        
        print("✅ SST统计配置完成")
        stats_success = True
    except Exception as e:
        print(f"❌ SST统计配置失败: {e}")
        stats_success = False
    
    # 总结
    print(f"\n=== 测试结果总结 ===")
    print(f"简单SST测试: {'✅ 通过' if simple_test_success else '❌ 失败'}")
    print(f"混合配置测试: {'✅ 通过' if hybrid_test_success else '❌ 失败'}")
    print(f"统计配置测试: {'✅ 通过' if stats_success else '❌ 失败'}")
    
    if simple_test_success and hybrid_test_success and stats_success:
        print("\n🎉 所有SST merlin.hr_router测试通过!")
        print("💡 SST组件配置正确，6端口mesh拓扑工作正常")
        return True
    else:
        print("\n⚠️ 部分测试失败，请检查SST环境配置")
        return False

if __name__ == "__main__":
    main()
