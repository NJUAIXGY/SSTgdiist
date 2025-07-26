import sst

# --- 使用TrafficGen流量生成器的4x4 mesh系统 ---
# 使用专门的流量生成器组件替代test_nic

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 构建基于TrafficGen的4x4 Mesh系统 ===")
print("使用专门的流量生成器产生网络流量")

# --- 创建带有流量生成器的节点 ---
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
        "network_name": "TrafficGen_Mesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建流量生成器
    traffic_gen = sst.Component(f"traffic_gen_{i}", "merlin.traffic_generator")
    
    # 根据核心位置配置不同的流量模式
    x = i % MESH_SIZE_X
    y = i // MESH_SIZE_X
    
    if x == 0 and y == 0:  # 主控核心 - 广播流量
        traffic_gen.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "500",           # 大量消息
            "message_size": "128B",          # 大消息
            "pattern": "uniform",            # 均匀分布
            "send_rate": "1000MB/s",         # 发送速率
            "message_rate": "100Hz",         # 消息频率
        })
        print(f"  - 流量生成器 {i} (位置: {x},{y}): 主控核心 - 均匀广播流量")
        
    elif x == MESH_SIZE_X-1 and y == MESH_SIZE_Y-1:  # 内存控制器
        traffic_gen.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "300",           
            "message_size": "64B",           # 缓存行大小
            "pattern": "hotspot",            # 热点模式
            "send_rate": "800MB/s",
            "message_rate": "150Hz",
            "hotspot_probability": "0.8",    # 80%流量集中
        })
        print(f"  - 流量生成器 {i} (位置: {x},{y}): 内存控制器 - 热点流量")
        
    elif x == 0 or x == MESH_SIZE_X-1 or y == 0 or y == MESH_SIZE_Y-1:  # I/O核心
        traffic_gen.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "200",
            "message_size": "32B",           # 小I/O消息
            "pattern": "nearest_neighbor",   # 邻居通信
            "send_rate": "400MB/s",
            "message_rate": "80Hz",
        })
        print(f"  - 流量生成器 {i} (位置: {x},{y}): I/O核心 - 邻居通信流量")
        
    else:  # 计算核心
        traffic_gen.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "250",
            "message_size": "64B",
            "pattern": "transpose",          # 转置模式
            "send_rate": "600MB/s",
            "message_rate": "120Hz",
        })
        print(f"  - 流量生成器 {i} (位置: {x},{y}): 计算核心 - 转置通信流量")

    # 连接流量生成器到路由器
    traffic_link = sst.Link(f"traffic_link_{i}")
    traffic_link.connect(
        (traffic_gen, "network", LINK_LATENCY),
        (router, "port4", LINK_LATENCY)  # 本地端口
    )

    routers.append(router)

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

# --- 配置统计收集 ---
print("\n=== 配置TrafficGen系统统计 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./trafficgen_mesh_stats.csv"})

# 启用流量生成器统计
sst.enableAllStatisticsForComponentType("merlin.traffic_generator")
sst.enableAllStatisticsForComponentType("merlin.hr_router")

# 启用特定统计项
for i in range(TOTAL_NODES):
    traffic_name = f"traffic_gen_{i}"
    router_name = f"router_{i}"
    
    # 流量生成器统计
    sst.enableStatisticForComponentName(traffic_name, "messages_sent")
    sst.enableStatisticForComponentName(traffic_name, "messages_received")
    sst.enableStatisticForComponentName(traffic_name, "bytes_sent")
    sst.enableStatisticForComponentName(traffic_name, "bytes_received")
    
    # 路由器统计
    sst.enableStatisticForComponentName(router_name, "send_packet_count")
    sst.enableStatisticForComponentName(router_name, "recv_packet_count")
    sst.enableStatisticForComponentName(router_name, "send_bit_count")
    sst.enableStatisticForComponentName(router_name, "recv_bit_count")

print("✓ TrafficGen系统统计配置完成")

# --- 系统总结 ---
print(f"\n=== TrafficGen系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个流量生成器")
print(f"   • 流量生成器: 专门的网络流量生成组件")
print(f"   • 网络拓扑: 2D Mesh")
print(f"   • 链路性能: {LINK_BANDWIDTH} 带宽, {LINK_LATENCY} 延迟")

print(f"\n🚀 开始TrafficGen系统仿真...")
print("   将生成多种流量模式测试网络性能")
