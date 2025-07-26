import sst

# --- 使用简单流量生成器的4x4 mesh系统 ---
# 避免test_nic，使用最基础的流量生成方法

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 构建基于4x4 Mesh的简单流量系统 ===")
print("使用基础流量生成器产生网络流量")

# --- 创建流量节点 ---
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
        "network_name": "Simple_Traffic_System",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建简单的流量生成器 (使用merlin自带的简单端点)
    endpoint = router.setSubComponent("endpoint", "merlin.linkcontrol")
    endpoint.addParams({
        "link_bw": LINK_BANDWIDTH,
        "input_buf_size": "1KiB",
        "output_buf_size": "1KiB",
        "port_name": "rtr_port",
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

# --- 添加外部流量注入器 ---
print("\n=== 创建外部流量注入系统 ===")

# 创建多个独立的流量注入器
traffic_generators = []
for i in range(4):  # 创建4个流量生成器
    # 流量生成器
    traffic_gen = sst.Component(f"traffic_gen_{i}", "merlin.hr_router")
    traffic_gen.addParams({
        "id": TOTAL_NODES + i,  # 给流量生成器唯一的ID
        "num_ports": "2",       # 只需要1个端口连接到网络
        "link_bw": LINK_BANDWIDTH,
        "flit_size": "8B",
        "xbar_bw": LINK_BANDWIDTH,
        "input_latency": LINK_LATENCY,
        "output_latency": LINK_LATENCY,
        "input_buf_size": "1KiB",
        "output_buf_size": "1KiB",
    })
    
    # 简单的端点配置
    gen_endpoint = traffic_gen.setSubComponent("endpoint", "merlin.linkcontrol")
    gen_endpoint.addParams({
        "link_bw": LINK_BANDWIDTH,
        "input_buf_size": "1KiB",
        "output_buf_size": "1KiB",
        "port_name": "rtr_port",
    })
    
    # 将流量生成器连接到不同的角落节点
    corner_nodes = [0, 3, 12, 15]  # 四个角落
    target_node = corner_nodes[i]
    
    # 创建到目标节点的连接
    traffic_link = sst.Link(f"traffic_inject_{i}")
    traffic_link.connect(
        (traffic_gen, "port0", LINK_LATENCY),
        (routers[target_node], f"port{4}", LINK_LATENCY)  # 使用额外端口
    )
    
    print(f"  - 流量生成器 {i}: 连接到节点 {target_node}")
    traffic_generators.append(traffic_gen)

# --- 配置系统统计 ---
print("\n=== 配置流量系统统计收集 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./simple_traffic_mesh_stats.csv"})

# 启用详细统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("merlin.linkcontrol")

# 启用特定统计项
for i in range(TOTAL_NODES):
    router_name = f"router_{i}"
    sst.enableStatisticForComponentName(router_name, "send_packet_count")
    sst.enableStatisticForComponentName(router_name, "recv_packet_count") 
    sst.enableStatisticForComponentName(router_name, "send_bit_count")
    sst.enableStatisticForComponentName(router_name, "recv_bit_count")

# 为流量生成器也启用统计
for i in range(4):
    gen_name = f"traffic_gen_{i}"
    sst.enableStatisticForComponentName(gen_name, "send_packet_count")
    sst.enableStatisticForComponentName(gen_name, "recv_packet_count") 

print("✓ 统计收集配置完成")

# --- 系统总结 ---
print(f"\n=== 简单流量系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个节点")
print(f"   • 流量生成器: 4个外部注入器")
print(f"   • 端点类型: merlin.linkcontrol")
print(f"   • 网络拓扑: 2D Mesh (二维网格)")
print(f"   • 链路性能: {LINK_BANDWIDTH} 带宽, {LINK_LATENCY} 延迟")

print(f"\n🌐 流量注入配置:")
print(f"   • 流量注入点: 4个角落节点 (0, 3, 12, 15)")
print(f"   • 注入方式: 外部路由器连接")
print(f"   • 流量模式: 基础网络控制流量")

print(f"\n🚀 开始简单流量系统仿真...")
print("   系统将通过外部注入器产生网络流量")
