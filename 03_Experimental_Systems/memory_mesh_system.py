import sst

# --- 使用Memhierarchy + 简单流量生成器的4x4 mesh系统 ---
# 完全避免test_nic，使用内存系统生成真实流量

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 构建基于4x4 Mesh的内存系统架构 ===")
print("使用内存层次结构和流量生成器产生真实网络流量")

# --- 创建网络节点 (使用内存系统) ---
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
        "network_name": "Memory_Mesh_System",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 根据节点位置配置不同的内存组件
    x = i % MESH_SIZE_X
    y = i // MESH_SIZE_X
    
    if i < 12:  # 前12个节点作为缓存节点
        # 创建缓存组件
        cache = sst.Component(f"cache_{i}", "memHierarchy.Cache")
        cache.addParams({
            "cache_frequency": "2.4GHz",
            "cache_size": "64KiB",
            "associativity": "8",
            "access_latency_cycles": "2",
            "L1": "1",
            "verbose": "1",
            "coherence_protocol": "MSI",
        })
        
        # 创建简单的CPU负载生成器
        cpu_gen = sst.Component(f"cpu_{i}", "memHierarchy.streamCPU")
        cpu_gen.addParams({
            "commfreq": "100",
            "rngseed": str(i + 1),
            "verbose": "1",
            "clock": "2.4GHz",
        })
        
        # 连接CPU生成器到缓存
        cpu_cache_link = sst.Link(f"cpu_cache_link_{i}")
        cpu_cache_link.connect(
            (cpu_gen, "mem_link", "50ps"),
            (cache, "high_network_0", "50ps")
        )
        
        # 连接缓存到网络
        cache_net_link = sst.Link(f"cache_net_link_{i}")
        cache_net_link.connect(
            (cache, "low_network_0", "50ps"),
            (router, "port4", "50ps")
        )
        
        print(f"  - 节点 {i} (位置: {x},{y}): 缓存节点 + CPU流量生成器")
        
    else:  # 后4个节点作为内存控制器
        # 创建内存控制器
        memory_ctrl = sst.Component(f"memory_{i}", "memHierarchy.MemController")
        memory_ctrl.addParams({
            "clock": "1GHz",
            "backing": "none",
            "verbose": "1",
            "addr_range_start": f"{(i-12) * 128 * 1024 * 1024}",  # 每个内存控制器管理128MB
            "addr_range_end": f"{(i-11) * 128 * 1024 * 1024 - 1}",
        })
        
        # 创建内存
        memory = memory_ctrl.setSubComponent("backend", "memHierarchy.simpleMem")
        memory.addParams({
            "access_time": "100ns",
            "mem_size": "128MiB",
        })
        
        # 连接内存控制器到网络
        mem_net_link = sst.Link(f"mem_net_link_{i}")
        mem_net_link.connect(
            (memory_ctrl, "direct_link", "50ps"),
            (router, "port4", "50ps")
        )
        
        print(f"  - 节点 {i} (位置: {x},{y}): 内存控制器 (管理 {(i-12)*128}-{(i-11)*128-1}MB)")

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
print("\n=== 配置内存系统统计收集 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./memory_mesh_stats.csv"})

# 启用详细统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("memHierarchy.Cache")
sst.enableAllStatisticsForComponentType("memHierarchy.MemController")
sst.enableAllStatisticsForComponentType("memHierarchy.streamCPU")

# 启用特定统计项
for i in range(TOTAL_NODES):
    router_name = f"router_{i}"
    sst.enableStatisticForComponentName(router_name, "send_packet_count")
    sst.enableStatisticForComponentName(router_name, "recv_packet_count") 
    sst.enableStatisticForComponentName(router_name, "send_bit_count")
    sst.enableStatisticForComponentName(router_name, "recv_bit_count")

print("✓ 统计收集配置完成")

# --- 系统总结 ---
print(f"\n=== 内存系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个节点")
print(f"   • 缓存节点: 12个 (每个64KiB L1缓存)")
print(f"   • 内存节点: 4个 (每个128MiB内存)")
print(f"   • 流量生成: streamCPU (内存访问流量)")
print(f"   • 网络拓扑: 2D Mesh (二维网格)")
print(f"   • 链路性能: {LINK_BANDWIDTH} 带宽, {LINK_LATENCY} 延迟")

print(f"\n🧠 内存系统配置:")
print(f"   • L1缓存: 64KiB, 8路组相联, MSI一致性协议")
print(f"   • 内存控制器: 4个, 总计512MiB内存")
print(f"   • CPU流量: 每个缓存节点100频率的内存访问")

print(f"\n🚀 开始内存系统仿真...")
print("   系统将生成真实的缓存-内存网络流量")
