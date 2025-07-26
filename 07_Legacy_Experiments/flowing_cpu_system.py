import sst

# --- 确保产生网络流量的CPU系统 ---
MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 创建确保有网络流量的4x4 Mesh CPU系统 ===")

# --- 创建路由器和NIC ---
for i in range(TOTAL_NODES):
    # 创建路由器
    router = sst.Component(f"router_{i}", "merlin.hr_router")
    router.addParams({
        "id": i,
        "num_ports": "5",
        "link_bw": LINK_BANDWIDTH,
        "flit_size": "8B",
        "xbar_bw": LINK_BANDWIDTH,
        "input_latency": LINK_LATENCY,
        "output_latency": LINK_LATENCY,
        "input_buf_size": "1KiB",
        "output_buf_size": "1KiB",
    })

    # 配置mesh拓扑
    topo_sub = router.setSubComponent("topology", "merlin.mesh")
    topo_sub.addParams({
        "network_name": "FlowingCPUMesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 为每个节点创建专门的流量生成器
    nic = router.setSubComponent("endpoint", "merlin.test_nic")
    
    # 使用经过验证的参数组合
    base_params = {
        "id": i,
        "num_peers": TOTAL_NODES,
        "verbose": "1",  # 启用详细输出以调试
    }
    
    # 为不同位置的核心配置不同的流量模式
    if i == 0:  # 主控核心 - 广播流量
        nic.addParams({
            **base_params,
            "num_messages": "100",
            "message_size": "64B",
            "send_untimed_bcast": "1",  # 广播模式
            "packet_dest": "0",
        })
        print(f"  ✓ CPU核心 {i}: 主控核心 (广播模式)")
        
    elif i % 4 == 1:  # 每第二个核心发送到下一个核心
        target = (i + 1) % TOTAL_NODES
        nic.addParams({
            **base_params,
            "num_messages": "50",
            "message_size": "32B",
            "send_untimed_bcast": "0",
            "packet_dest": str(target),
        })
        print(f"  ✓ CPU核心 {i}: 发送到核心 {target}")
        
    elif i % 4 == 2:  # 发送到对角线位置
        target = (TOTAL_NODES - 1 - i) % TOTAL_NODES
        nic.addParams({
            **base_params,
            "num_messages": "30",
            "message_size": "48B",
            "send_untimed_bcast": "0",
            "packet_dest": str(target),
        })
        print(f"  ✓ CPU核心 {i}: 发送到对角核心 {target}")
        
    else:  # 其他核心发送到邻近核心
        target = (i + 4) % TOTAL_NODES
        nic.addParams({
            **base_params,
            "num_messages": "20",
            "message_size": "32B",
            "send_untimed_bcast": "0",
            "packet_dest": str(target),
        })
        print(f"  ✓ CPU核心 {i}: 发送到核心 {target}")

    routers.append(router)

# --- 构建mesh网络连接 ---
print(f"\n=== 构建Mesh网络连接 ===")

link_count = 0
for y in range(MESH_SIZE_Y):
    for x in range(MESH_SIZE_X):
        node_id = y * MESH_SIZE_X + x
        
        # 东西连接
        if x < MESH_SIZE_X - 1:
            link = sst.Link(f"mesh_east_{x}_{y}")
            link.connect(
                (routers[node_id], "port0", LINK_LATENCY),
                (routers[node_id + 1], "port1", LINK_LATENCY)
            )
            link_count += 1
        
        # 南北连接
        if y < MESH_SIZE_Y - 1:
            link = sst.Link(f"mesh_south_{x}_{y}")
            link.connect(
                (routers[node_id], "port2", LINK_LATENCY),
                (routers[node_id + MESH_SIZE_X], "port3", LINK_LATENCY)
            )
            link_count += 1

print(f"✓ 创建了 {link_count} 条双向链路")

# --- 配置统计 ---
print(f"\n=== 配置统计收集 ===")

sst.setStatisticLoadLevel(6)  # 更高的统计级别
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./flowing_cpu_stats.csv"})

# 启用更详细的统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("merlin.test_nic")

# 确保启用关键统计
for i in range(TOTAL_NODES):
    sst.enableStatisticForComponentName(f"router_{i}", "send_packet_count")
    sst.enableStatisticForComponentName(f"router_{i}", "recv_packet_count")

print("✓ 配置完成")

print(f"\n🚀 启动网络流量测试...")
print(f"   • 16个CPU核心配置不同的通信模式")
print(f"   • 核心0: 广播通信")
print(f"   • 其他核心: 点对点通信到特定目标")
print(f"   • 启用详细统计和调试输出")
print(f"   • 应该能看到实际的网络活动")
