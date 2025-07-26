import sst

# --- 最基本的2x2网格测试 ---
print("Creating basic 2x2 mesh topology test...")

# 基本参数
MESH_SIZE_X = 2
MESH_SIZE_Y = 2
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y  # 4个节点
LINK_BANDWIDTH = "1GiB/s"
LINK_LATENCY = "100ns"

routers = []

# 创建4个路由器
for i in range(TOTAL_NODES):
    router = sst.Component(f"router_{i}", "merlin.hr_router")
    router.addParams({
        "id": i,
        "num_ports": "5",  # 东西南北 + 本地端口
        "link_bw": LINK_BANDWIDTH,
        "flit_size": "8B",
        "xbar_bw": LINK_BANDWIDTH,
        "input_latency": LINK_LATENCY,
        "output_latency": LINK_LATENCY,
        "input_buf_size": "1KiB",
        "output_buf_size": "1KiB",
    })

    # 配置网格拓扑
    topo = router.setSubComponent("topology", "merlin.mesh")
    topo.addParams({
        "shape": "2x2",
        "width": "1x1",
        "local_ports": "1",
    })

    # 添加简单的测试NIC
    nic = router.setSubComponent("endpoint", "merlin.test_nic")
    nic.addParams({
        "id": i,
        "num_peers": TOTAL_NODES,
        "num_messages": "10",       # 只发送10条消息
        "message_size": "32B",      # 32字节消息
        "send_untimed_bcast": "0"   # 关闭广播，使用点对点
    })

    routers.append(router)

# 连接路由器 - 2x2网格布局：
# [0] -- [1]
#  |      |
# [2] -- [3]

print("Connecting routers in 2x2 mesh...")

# 水平连接：0-1, 2-3
link_01 = sst.Link("link_0_1")
link_01.connect(
    (routers[0], "port0", LINK_LATENCY),  # router 0 东端口
    (routers[1], "port1", LINK_LATENCY)   # router 1 西端口
)

link_23 = sst.Link("link_2_3")
link_23.connect(
    (routers[2], "port0", LINK_LATENCY),  # router 2 东端口
    (routers[3], "port1", LINK_LATENCY)   # router 3 西端口
)

# 垂直连接：0-2, 1-3
link_02 = sst.Link("link_0_2")
link_02.connect(
    (routers[0], "port2", LINK_LATENCY),  # router 0 南端口
    (routers[2], "port3", LINK_LATENCY)   # router 2 北端口
)

link_13 = sst.Link("link_1_3")
link_13.connect(
    (routers[1], "port2", LINK_LATENCY),  # router 1 南端口
    (routers[3], "port3", LINK_LATENCY)   # router 3 北端口
)

# 配置基本统计
print("Basic 2x2 mesh configuration complete.")
sst.setStatisticLoadLevel(1)  # 最低统计级别
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./basic_mesh_stats.csv"})
sst.enableAllStatisticsForComponentType("merlin.hr_router")
