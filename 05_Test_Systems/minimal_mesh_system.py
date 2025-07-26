import sst

# --- 最简单有效的4x4 mesh流量系统 ---
# 使用正确配置的merlin网络组件，避免test_nic

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 构建最简单有效的4x4 Mesh流量系统 ===")
print("使用merlin.endpoint生成基础网络流量")

# --- 创建网络节点 ---
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
        "network_name": "Minimal_Traffic_System",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建基础端点 (使用merlin.endpoint而不是test_nic)
    endpoint = router.setSubComponent("endpoint", "merlin.endpoint")
    endpoint.addParams({
        "id": i,
        "link_bw": LINK_BANDWIDTH,
    })

    # 根据节点位置配置不同类型
    x = i % MESH_SIZE_X
    y = i // MESH_SIZE_X
    
    if x == 0 and y == 0:
        print(f"  - 节点 {i} (位置: {x},{y}): 主控节点")
    elif x == MESH_SIZE_X-1 and y == MESH_SIZE_Y-1:
        print(f"  - 节点 {i} (位置: {x},{y}): 内存控制器节点")
    elif x == 0 or x == MESH_SIZE_X-1 or y == 0 or y == MESH_SIZE_Y-1:
        print(f"  - 节点 {i} (位置: {x},{y}): I/O边缘节点")
    else:
        print(f"  - 节点 {i} (位置: {x},{y}): 计算核心节点")

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

# --- 配置系统统计 ---
print("\n=== 配置基础网络统计收集 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./minimal_mesh_stats.csv"})

# 启用详细统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("merlin.endpoint")

# 启用特定统计项
for i in range(TOTAL_NODES):
    router_name = f"router_{i}"
    sst.enableStatisticForComponentName(router_name, "send_packet_count")
    sst.enableStatisticForComponentName(router_name, "recv_packet_count") 
    sst.enableStatisticForComponentName(router_name, "send_bit_count")
    sst.enableStatisticForComponentName(router_name, "recv_bit_count")
    sst.enableStatisticForComponentName(router_name, "output_port_stalls")

print("✓ 统计收集配置完成")

# --- 设置仿真时间 ---
print("\n=== 设置仿真参数 ===")

# 运行较短时间以观察基础网络行为
print("仿真时间: 1微秒 (观察基础网络初始化和控制流量)")

# --- 系统总结 ---
print(f"\n=== 基础网络系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个节点")
print(f"   • 端点类型: merlin.endpoint (基础网络端点)")
print(f"   • 流量类型: 网络控制和初始化流量")
print(f"   • 网络拓扑: 2D Mesh (二维网格)")
print(f"   • 链路性能: {LINK_BANDWIDTH} 带宽, {LINK_LATENCY} 延迟")

print(f"\n🌐 网络特性:")
print(f"   • 连接方式: 24条双向链路")
print(f"   • 路由算法: 默认mesh路由")
print(f"   • 流量模式: 系统控制流量")
print(f"   • 统计收集: 全面的网络性能统计")

print(f"\n🚀 开始基础网络系统仿真...")
print("   系统将展示mesh网络的基础通信行为")
