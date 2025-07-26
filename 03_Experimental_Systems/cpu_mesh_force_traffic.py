import sst

# --- 使用test_nic强制流量生成的4x4 mesh系统 ---
# 采用最激进的参数组合强制生成网络流量

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 构建强制流量生成的4x4 Mesh系统 ===")
print("使用最激进的test_nic参数强制产生网络流量")

# --- 创建强制流量生成的节点 ---
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
        "network_name": "Force_Traffic_Mesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建强制流量生成的test_nic
    traffic_nic = router.setSubComponent("endpoint", "merlin.test_nic")
    
    # 每个节点都使用相同的激进参数，确保生成流量
    traffic_nic.addParams({
        "id": i,
        "num_peers": TOTAL_NODES,
        
        # 强制发送参数
        "packets_to_send": "2000",           # 大量数据包
        "packet_dest": str((i + 1) % TOTAL_NODES),  # 环形发送模式
        "message_size": "128B",              # 大消息
        "num_messages": "500",               # 大量消息
        
        # 激活所有可能的流量生成选项
        "send_untimed_bcast": "1",           # 启用广播
        "recv_untimed_bcast": "1",           # 接收广播
        
        # 时间和速率控制
        "timing_set": "1",                   # 启用时间控制
        "delay_between_packets": "100ns",    # 包间延迟
        
        # 统计和调试
        "verbose": "1",                      # 详细输出
        "print_stats": "1",                  # 打印统计
    })
    
    print(f"  - 强制流量节点 {i}: 向节点 {(i + 1) % TOTAL_NODES} 发送 2000 个包")

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

# --- 强制运行时间设置 ---
# 设置足够长的仿真时间确保流量能够完成
print("\n=== 设置仿真运行时间 ===")
sst.setProgramOption("timebase", "1ps")
sst.setProgramOption("stop-at", "100us")  # 运行100微秒
print("✓ 设置仿真时间为 100 微秒")

# --- 配置统计收集 ---
print("\n=== 配置强制流量统计 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./force_traffic_mesh_stats.csv"})

# 启用所有可能的统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("merlin.test_nic")

# 启用详细统计项
for i in range(TOTAL_NODES):
    router_name = f"router_{i}"
    
    # 路由器流量统计
    sst.enableStatisticForComponentName(router_name, "send_packet_count")
    sst.enableStatisticForComponentName(router_name, "recv_packet_count")
    sst.enableStatisticForComponentName(router_name, "send_bit_count")
    sst.enableStatisticForComponentName(router_name, "recv_bit_count")
    sst.enableStatisticForComponentName(router_name, "packet_latency")
    sst.enableStatisticForComponentName(router_name, "buffer_occupancy")

print("✓ 强制流量统计配置完成")

# --- 系统总结 ---
print(f"\n=== 强制流量系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个强制流量节点")
print(f"   • 流量模式: 环形发送 (每个节点向下一个节点发送)")
print(f"   • 数据包数: 每节点 2000 个包")
print(f"   • 包大小: 128 字节")
print(f"   • 仿真时间: 100 微秒")

print(f"\n🚀 开始强制流量仿真...")
print("   这次应该能看到真实的网络流量！")
