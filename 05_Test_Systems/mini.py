# sst_4x4_mesh_final_corrected.py
# Date: 2025-07-25
# This version uses the manual connection logic but with the correct,
# source-code-verified port mapping to satisfy the PortControl initialization protocol.

import sst

# --- 1. 初始化与参数定义 ---
MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GB/s"
LINK_LATENCY = "50ps"

routers = []

# --- 2. 创建核心组件并加载子组件 ---
print("Applying final fix: Using Merlin's internal port mapping for manual linking...")

for i in range(TOTAL_NODES):
    router = sst.Component(f"router_{i}", "merlin.hr_router")
    router.addParams({
        "id": i,
        # 关键修正1: 端口总数必须是5，以匹配Merlin对2D网络+1个本地节点的期望
        # (4个网络方向 + 1个本地端口)
        "num_ports": "5",
        "link_bw": LINK_BANDWIDTH,
        "flit_size": "8B",
        "xbar_bw": LINK_BANDWIDTH,
        "input_latency": LINK_LATENCY,
        "output_latency": LINK_LATENCY,
        "input_buf_size": "1KiB",
        "output_buf_size": "1KiB",
    })

    # 加载拓扑子组件，它会告诉路由器如何进行路由决策
    topo_sub = router.setSubComponent("topology", "merlin.mesh")
    topo_sub.addParams({
        "network_name" : "MySharedMesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1", # 告诉拓扑，每个路由器有1个本地节点
    })

    # 加载NIC子组件。Merlin会自动将其连接到本地端口（Port 4）
    nic = router.setSubComponent("endpoint", "merlin.test_nic")
    nic.addParams({
        "id": i,
        "num_peers": TOTAL_NODES,
        "num_messages": 1000,
        "message_size": "128B"
    })
    
    routers.append(router)

# --- 3. 构建拓扑连接 ---
# 关键修正2: 必须严格按照Merlin的内部端口映射来创建链路
# Port 0: +x (East), Port 1: -x (West), Port 2: +y (South), Port 3: -y (North), Port 4: Local
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

# --- 4. 配置统计与运行 ---
print("Configuration complete. This should now run successfully.")
sst.setStatisticLoadLevel(4)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath" : "./mesh_stats_final.csv"})
sst.enableAllStatisticsForComponentType("merlin.hr_router")