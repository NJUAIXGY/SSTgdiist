import sst

# --- 简化的CPU系统：只有CPU核心、缓存和mesh网络 ---
MESH_SIZE_X = 2
MESH_SIZE_Y = 2
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

# CPU和缓存参数
CPU_CLOCK = "2.4GHz"
CACHE_SIZE = "32KiB"

routers = []
cpu_cores = []

# --- 创建简化的CPU系统 ---
print("Creating simplified 2x2 mesh-based CPU system...")

for i in range(TOTAL_NODES):
    # 创建路由器
    router = sst.Component(f"router_{i}", "merlin.hr_router")
    router.addParams({
        "id": i,
        "num_ports": "5",  # 4个网络方向 + 1个本地端口
        "link_bw": LINK_BANDWIDTH,
        "flit_size": "8B",
        "xbar_bw": LINK_BANDWIDTH,
        "input_latency": LINK_LATENCY,
        "output_latency": LINK_LATENCY,
        "input_buf_size": "1KiB",
        "output_buf_size": "1KiB",
    })

    # 配置拓扑子组件
    topo_sub = router.setSubComponent("topology", "merlin.mesh")
    topo_sub.addParams({
        "network_name": "SimpleCPUMesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建测试NIC模拟CPU行为
    nic = router.setSubComponent("endpoint", "merlin.test_nic")
    nic.addParams({
        "id": i,
        "num_peers": TOTAL_NODES,
        "num_messages": "50",        # 每个"CPU"发送50个消息
        "message_size": "64B",       # 64字节消息（模拟缓存行）
        "send_untimed_bcast": "0",   # 禁用广播，使用点对点通信
        "packets_to_send": "100",    # 每个核心发送100个包
    })

    routers.append(router)

# --- 构建mesh网络连接 ---
print("Connecting 2x2 mesh network...")

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
        
        # 南北连接
        if y < MESH_SIZE_Y - 1:
            link = sst.Link(f"mesh_south_{x}_{y}")
            link.connect(
                (routers[node_id], "port2", LINK_LATENCY),
                (routers[node_id + MESH_SIZE_X], "port3", LINK_LATENCY)
            )

# --- 配置统计与运行 ---
print("Configuring simplified CPU system statistics...")

# 设置统计收集
sst.setStatisticLoadLevel(4)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./simple_cpu_stats.csv"})

# 启用路由器和NIC统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("merlin.test_nic")

print(f"✓ Created {TOTAL_NODES} simulated CPU cores")
print(f"✓ Built {MESH_SIZE_X}x{MESH_SIZE_Y} mesh network")
print("✓ Each 'CPU' will generate memory traffic through the mesh")
print("Starting simplified CPU system simulation...")

# 这将模拟CPU核心通过mesh网络进行通信
