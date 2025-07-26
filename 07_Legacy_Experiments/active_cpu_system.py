import sst

# --- 修复网络流量的CPU系统 ---
MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 创建有实际网络流量的4x4 Mesh CPU系统 ===")

# --- 创建路由器和CPU核心 ---
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
        "network_name": "ActiveCPUMesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建CPU核心，使用更有效的参数配置
    cpu_core = router.setSubComponent("endpoint", "merlin.test_nic")
    
    x = i % MESH_SIZE_X
    y = i // MESH_SIZE_X
    
    # 为每个核心配置不同的通信模式，确保产生流量
    if i == 0:  # 主控核心
        cpu_core.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "50",           # 减少消息数以确保完成
            "message_size": "64B",          # 使用标准缓存行大小
            "send_untimed_bcast": "1",      # 启用广播
            "verbose": "0",
        })
        print(f"  - CPU核心 {i}: 主控核心 (广播模式)")
        
    elif i == 15:  # 内存控制器
        cpu_core.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "30",           # 内存控制器发送较少消息
            "message_size": "64B",
            "send_untimed_bcast": "0",      # 点对点通信
            "verbose": "0",
        })
        print(f"  - CPU核心 {i}: 内存控制器")
        
    else:  # 其他核心
        cpu_core.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "25",           # 标准消息数量
            "message_size": "32B",          # 较小消息确保快速传输
            "send_untimed_bcast": "0",      # 点对点通信
            "verbose": "0",
        })
        core_type = "计算核心" if (x > 0 and x < 3 and y > 0 and y < 3) else "I/O核心"
        print(f"  - CPU核心 {i}: {core_type}")

    routers.append(router)

# --- 构建mesh网络 ---
print(f"\n=== 构建{MESH_SIZE_X}x{MESH_SIZE_Y} Mesh网络 ===")

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

# --- 配置统计收集 ---
print(f"\n=== 配置统计收集 ===")

sst.setStatisticLoadLevel(4)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./active_cpu_stats.csv"})

# 启用组件统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("merlin.test_nic")

print("✓ 统计收集配置完成")

print(f"\n🚀 启动CPU系统仿真...")
print(f"   • {TOTAL_NODES}个CPU核心将开始网络通信")
print(f"   • 主控核心将进行广播通信")
print(f"   • 其他核心将进行点对点通信")
print(f"   • 预期将产生大量网络流量")
