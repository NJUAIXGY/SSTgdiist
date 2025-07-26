import sst

# --- 1. 初始化与参数定义 ---
MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

# --- 2. 创建核心组件并加载子组件 ---
print("Creating 4x4 mesh topology with enhanced test NICs...")

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
        "network_name": "MyEnhancedMesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 添加增强测试NIC作为端点
    nic = router.setSubComponent("endpoint", "merlin.test_nic")
    nic.addParams({
        "id": i,
        "num_peers": TOTAL_NODES,
        "num_messages": "200",           # 增加消息数量
        "message_size": "128B",          # 增大消息大小
        "send_untimed_bcast": "1",       # 启用广播测试
        "packets_to_send": "1000",       # 每个节点发送更多包
        "pattern": "0",                  # 使用默认通信模式
    })

    routers.append(router)

# --- 3. 构建拓扑连接 ---
print("Connecting routers in 4x4 mesh topology...")

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

# --- 4. 配置统计与运行 ---
print("Configuring statistics collection...")

# 启用统计收集
sst.setStatisticLoadLevel(4)  # 使用稳定的统计级别
sst.setStatisticOutput("sst.statOutputCSV", {"filepath" : "./enhanced_mesh_stats.csv"})

# 为主要组件类型启用统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("merlin.test_nic")

print(f"✓ Created {TOTAL_NODES} routers in {MESH_SIZE_X}x{MESH_SIZE_Y} mesh topology")
print(f"✓ Connected {(MESH_SIZE_X-1)*MESH_SIZE_Y + (MESH_SIZE_Y-1)*MESH_SIZE_X} bidirectional links")
print("✓ Statistics collection enabled")
print("Starting enhanced simulation...")
