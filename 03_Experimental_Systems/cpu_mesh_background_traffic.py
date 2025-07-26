import sst

# --- 使用background_traffic组件的4x4 mesh系统 ---
# background_traffic是专门用于生成网络背景流量的组件

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 构建基于background_traffic的4x4 Mesh系统 ===")
print("使用专门的背景流量生成器")

# --- 创建mesh网络 ---
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

    # 配置mesh拓扑
    topo_sub = router.setSubComponent("topology", "merlin.mesh")
    topo_sub.addParams({
        "network_name": "Background_Traffic_Mesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    routers.append(router)

# 创建背景流量生成器
print("\n=== 配置背景流量生成器 ===")
traffic_gen = sst.Component("background_traffic", "merlin.background_traffic")
traffic_gen.addParams({
    "num_nodes": TOTAL_NODES,
    "packets_per_cycle": "4",        # 每周期注入4个包
    "packet_size": "64B",            # 包大小
    "pattern": "uniform",            # 均匀随机流量模式
    "injection_rate": "0.1",         # 注入率 10%
})

print("✓ 配置背景流量: 均匀随机模式, 注入率 10%")

# 连接背景流量生成器到所有路由器
for i in range(TOTAL_NODES):
    traffic_link = sst.Link(f"traffic_to_router_{i}")
    traffic_link.connect(
        (traffic_gen, f"port{i}", LINK_LATENCY),
        (routers[i], "port4", LINK_LATENCY)  # 本地端口
    )

# --- 构建4x4 mesh网络连接 ---
print("\n=== 构建4x4 Mesh网络连接 ===")

link_count = 0
for y in range(MESH_SIZE_Y):
    for x in range(MESH_SIZE_X):
        node_id = y * MESH_SIZE_X + x
        
        # 东西连接
        if x < MESH_SIZE_X - 1:
            link = sst.Link(f"mesh_east_{x}_{y}")
            link.connect(
                (routers[node_id], "port0", LINK_LATENCY),      # 东端口
                (routers[node_id + 1], "port1", LINK_LATENCY)   # 西端口
            )
            link_count += 1
        
        # 南北连接
        if y < MESH_SIZE_Y - 1:
            link = sst.Link(f"mesh_south_{x}_{y}")
            link.connect(
                (routers[node_id], "port2", LINK_LATENCY),              # 南端口
                (routers[node_id + MESH_SIZE_X], "port3", LINK_LATENCY) # 北端口
            )
            link_count += 1

print(f"✓ 创建了 {link_count} 条双向链路")

# --- 设置仿真时间 ---
print("\n=== 设置仿真参数 ===")
sst.setProgramOption("timebase", "1ps")
sst.setProgramOption("stop-at", "10us")  # 运行10微秒
print("✓ 设置仿真时间为 10 微秒")

# --- 配置统计收集 ---
print("\n=== 配置背景流量统计 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./background_traffic_stats.csv"})

# 启用背景流量和路由器统计
sst.enableAllStatisticsForComponentType("merlin.background_traffic")
sst.enableAllStatisticsForComponentType("merlin.hr_router")

# 启用详细统计项
for i in range(TOTAL_NODES):
    router_name = f"router_{i}"
    sst.enableStatisticForComponentName(router_name, "send_packet_count")
    sst.enableStatisticForComponentName(router_name, "recv_packet_count")
    sst.enableStatisticForComponentName(router_name, "send_bit_count")
    sst.enableStatisticForComponentName(router_name, "recv_bit_count")

# 背景流量统计
sst.enableStatisticForComponentName("background_traffic", "packets_generated")
sst.enableStatisticForComponentName("background_traffic", "packets_sent")

print("✓ 背景流量统计配置完成")

# --- 系统总结 ---
print(f"\n=== 背景流量系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个路由器")
print(f"   • 流量生成器: 专用背景流量生成器")
print(f"   • 流量模式: 均匀随机分布")
print(f"   • 注入率: 10% (每周期4个包)")
print(f"   • 仿真时间: 10 微秒")

print(f"\n🚀 开始背景流量仿真...")
print("   这种方式应该能产生真实的网络流量！")
