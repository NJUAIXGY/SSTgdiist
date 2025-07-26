import sst

# --- 基于4x4 mesh的CPU系统架构 ---
# 使用test_nic模拟CPU核心，展示CPU系统的网络通信模式

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 构建基于4x4 Mesh的CPU系统架构 ===")
print("每个节点模拟一个CPU核心，通过mesh网络进行通信")

# --- 创建CPU节点 (使用test_nic模拟) ---
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
        "network_name": "CPU_Mesh_System",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建CPU核心 (使用test_nic模拟CPU的网络行为)
    cpu_core = router.setSubComponent("endpoint", "merlin.test_nic")
    
    # 根据核心位置配置不同的通信模式
    x = i % MESH_SIZE_X
    y = i // MESH_SIZE_X
    
    # CPU核心的通信模式
    if x == 0 and y == 0:  # 角落核心 - 模拟主控核心
        cpu_core.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "200",       # 主控核心发送更多消息
            "message_size": "128B",      # 较大的消息 (控制信息)
            "send_untimed_bcast": "1",   # 启用广播 (模拟同步信号)
            "packets_to_send": "500",    # 发送包的总数
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 主控核心 - 负责系统协调")
        
    elif x == MESH_SIZE_X-1 and y == MESH_SIZE_Y-1:  # 对角核心 - 模拟内存控制器
        cpu_core.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "150",       # 中等消息数量
            "message_size": "64B",       # 缓存行大小
            "send_untimed_bcast": "0",   # 点对点通信
            "packets_to_send": "300",    # 发送包的总数
            "packet_dest": "0",          # 主要向主控核心发送
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 内存控制器 - 处理内存请求")
        
    elif x == 0 or x == MESH_SIZE_X-1 or y == 0 or y == MESH_SIZE_Y-1:  # 边缘核心 - 模拟I/O核心
        cpu_core.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "80",        # 较少消息
            "message_size": "32B",       # 小消息 (I/O数据)
            "send_untimed_bcast": "0",
            "packets_to_send": "200",    # 发送包的总数
            "packet_dest": "15",         # 主要向内存控制器发送
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): I/O核心 - 处理输入输出")
        
    else:  # 内部核心 - 模拟计算核心
        cpu_core.addParams({
            "id": i,
            "num_peers": TOTAL_NODES,
            "num_messages": "100",       # 标准消息数量
            "message_size": "64B",       # 标准缓存行
            "send_untimed_bcast": "0",
            "packets_to_send": "250",    # 发送包的总数
            "packet_dest": f"{(i + 8) % TOTAL_NODES}",  # 发送到对称位置的核心
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 计算核心 - 执行并行计算")

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
print("\n=== 配置CPU系统统计收集 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./cpu_mesh_system_stats.csv"})

# 启用详细统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("merlin.test_nic")

# 启用特定统计项
for i in range(TOTAL_NODES):
    router_name = f"router_{i}"
    # 网络流量统计
    sst.enableStatisticForComponentName(router_name, "send_packet_count")
    sst.enableStatisticForComponentName(router_name, "recv_packet_count") 
    sst.enableStatisticForComponentName(router_name, "send_bit_count")
    sst.enableStatisticForComponentName(router_name, "recv_bit_count")
    # 性能统计
    sst.enableStatisticForComponentName(router_name, "output_port_stalls")
    sst.enableStatisticForComponentName(router_name, "idle_time")

print("✓ 统计收集配置完成")

# --- 系统总结 ---
print(f"\n=== CPU系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个CPU核心")
print(f"   • 网络拓扑: 2D Mesh (二维网格)")
print(f"   • 链路性能: {LINK_BANDWIDTH} 带宽, {LINK_LATENCY} 延迟")
print(f"   • 总链路数: {link_count} 条双向链路")

print(f"\n🧠 CPU核心分布:")
print(f"   • 主控核心: 1个 (负责系统协调)")
print(f"   • 内存控制器: 1个 (处理内存访问)")
print(f"   • I/O核心: {2*MESH_SIZE_X + 2*MESH_SIZE_Y - 6}个 (处理输入输出)")
print(f"   • 计算核心: {(MESH_SIZE_X-2)*(MESH_SIZE_Y-2)}个 (执行并行任务)")

print(f"\n🚀 开始CPU系统仿真...")
print("   仿真将展示不同类型CPU核心之间的网络通信模式")
