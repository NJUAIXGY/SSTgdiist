import sst

# --- 1. 初始化与参数定义 ---
MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

# --- 2. 创建核心组件并加载子组件 ---
print("Creating simplified mesh topology with test NICs...")

for i in range(TOTAL_NODES):
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

    # 加载拓扑子组件
    topo_sub = router.setSubComponent("topology", "merlin.mesh")
    topo_sub.addParams({
        "network_name": "MySharedMesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 添加测试NIC作为端点
    nic = router.setSubComponent("endpoint", "merlin.test_nic")
    nic.addParams({
        "id": i,
        "num_peers": TOTAL_NODES,
        "num_messages": "100",      # 减少消息数量
        "message_size": "64B",      # 减小消息大小
        "send_untimed_bcast": "1"   # 启用广播测试
    })

    routers.append(router)

# --- 5. 构建拓扑连接 ---
print("Connecting routers using the correct port mapping...")

for y in range(MESH_SIZE_Y):
    for x in range(MESH_SIZE_X):
        node_id = y * MESH_SIZE_X + x
        
        # 连接东方: 当前路由器的东方(+x)端口连接到右边邻居的西方(-x)端口
        if x < MESH_SIZE_X - 1:
            link = sst.Link(f"link_east_{x}_{y}")
            link.connect(
                (routers[node_id], "port0", LINK_LATENCY),      # My East port
                (routers[node_id + 1], "port1", LINK_LATENCY)  # My neighbor's West port
            )
        
        # 连接南方: 当前路由器的南方(+y)端口连接到下方邻居的北方(-y)端口
        if y < MESH_SIZE_Y - 1:
            link = sst.Link(f"link_south_{x}_{y}")
            link.connect(
                (routers[node_id], "port2", LINK_LATENCY),              # My South port
                (routers[node_id + MESH_SIZE_X], "port3", LINK_LATENCY) # My neighbor's North port
            )

# --- 6. 配置统计与运行 ---
print("Configuration complete. This should now run successfully.")

# 启用统计收集
sst.setStatisticLoadLevel(4)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath" : "./mesh_stats_final.csv"})

# 为路由器组件启用统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")

# 为NIC组件启用统计
sst.enableAllStatisticsForComponentType("merlin.test_nic")

# 为特定的统计启用收集
for i, router in enumerate(routers):
    router_name = f"router_{i}"
    sst.enableStatisticForComponentName(router_name, "send_packet_count")
    sst.enableStatisticForComponentName(router_name, "recv_packet_count")
    sst.enableStatisticForComponentName(router_name, "send_bit_count")
    sst.enableStatisticForComponentName(router_name, "recv_bit_count")

print(f"Created {TOTAL_NODES} routers in {MESH_SIZE_X}x{MESH_SIZE_Y} mesh topology")
print("Starting simulation...")
