import sst

# --- 使用Miranda流量生成器的4x4 mesh系统 ---
# 完全避免test_nic，使用Miranda生成指令级流量

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 构建基于4x4 Mesh的Miranda CPU系统 ===")
print("使用Miranda CPU模拟器生成真实的指令级网络流量")

# --- 创建CPU节点 (使用Miranda) ---
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
        "network_name": "Miranda_CPU_System",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建Miranda CPU核心
    cpu_core = sst.Component(f"cpu_{i}", "miranda.BaseCPU")
    
    # 根据核心位置配置不同的工作负载
    x = i % MESH_SIZE_X
    y = i // MESH_SIZE_X
    
    if x == 0 and y == 0:  # 主控核心 - 随机访问模式
        cpu_core.addParams({
            "verbose": "1",
            "printStats": "1",
        })
        
        # 配置随机读写生成器
        gen = cpu_core.setSubComponent("generator", "miranda.RandomGenerator")
        gen.addParams({
            "seed": "12345",
            "count": "10000",
            "max_address": "65536",
            "verbose": "1",
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 主控核心 - 随机访问模式")
        
    elif x == MESH_SIZE_X-1 and y == MESH_SIZE_Y-1:  # 内存控制器 - 顺序访问
        cpu_core.addParams({
            "verbose": "1",
            "printStats": "1",
        })
        
        # 配置顺序读写生成器
        gen = cpu_core.setSubComponent("generator", "miranda.STREAMBenchGenerator")
        gen.addParams({
            "n": "10000",
            "start_a": "0",
            "start_b": "32768",
            "start_c": "65536",
            "verbose": "1",
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 内存控制器 - 流式访问模式")
        
    elif x == 0 or x == MESH_SIZE_X-1 or y == 0 or y == MESH_SIZE_Y-1:  # 边缘核心 - 步进访问
        cpu_core.addParams({
            "verbose": "1",
            "printStats": "1",
        })
        
        # 配置步进访问生成器
        gen = cpu_core.setSubComponent("generator", "miranda.GUPSGenerator")
        gen.addParams({
            "seed": str(i * 1000),
            "count": "5000",
            "max_address": "32768",
            "verbose": "1",
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): I/O核心 - GUPS访问模式")
        
    else:  # 内部核心 - 单一读写
        cpu_core.addParams({
            "verbose": "1",
            "printStats": "1",
        })
        
        # 配置单一读写生成器
        gen = cpu_core.setSubComponent("generator", "miranda.SingleStreamGenerator")
        gen.addParams({
            "count": "8000",
            "max_address": "16384",
            "start_address": "0",
            "verbose": "1",
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 计算核心 - 单流访问模式")

    # 创建内存接口
    mem_iface = cpu_core.setSubComponent("memory", "memHierarchy.standardInterface")
    
    # 创建L1缓存
    l1_cache = sst.Component(f"l1cache_{i}", "memHierarchy.Cache")
    l1_cache.addParams({
        "cache_frequency": "2.4GHz",
        "cache_size": "32KiB",
        "associativity": "8",
        "access_latency_cycles": "1",
        "L1": "1",
        "verbose": "0",
    })

    # 连接CPU到L1缓存
    cpu_cache_link = sst.Link(f"cpu_cache_link_{i}")
    cpu_cache_link.connect(
        (cpu_core, "cache_link", "50ps"),
        (l1_cache, "high_network_0", "50ps")
    )

    # 连接L1缓存到网络
    cache_net_link = sst.Link(f"cache_net_link_{i}")
    cache_net_link.connect(
        (l1_cache, "low_network_0", "50ps"),
        (router, "port4", "50ps")
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

# --- 创建共享L2缓存和内存 ---
print("\n=== 创建共享内存系统 ===")

# L2缓存
l2_cache = sst.Component("l2cache", "memHierarchy.Cache")
l2_cache.addParams({
    "cache_frequency": "2.4GHz",
    "cache_size": "256KiB",
    "associativity": "16",
    "access_latency_cycles": "6",
    "L1": "0",
    "verbose": "0",
})

# 内存控制器
memory_ctrl = sst.Component("memory", "memHierarchy.MemController")
memory_ctrl.addParams({
    "clock": "1GHz",
    "backing": "none",
    "verbose": "0",
})

# 内存
memory = memory_ctrl.setSubComponent("backend", "memHierarchy.simpleMem")
memory.addParams({
    "access_time": "100ns",
    "mem_size": "512MiB",
})

# L2到内存的连接
l2_mem_link = sst.Link("l2_mem_link")
l2_mem_link.connect(
    (l2_cache, "low_network_0", "50ps"),
    (memory_ctrl, "direct_link", "50ps")
)

# L2到网络的连接 (使用一个专门的路由器端口)
l2_router = sst.Component("l2_router", "merlin.hr_router")
l2_router.addParams({
    "id": TOTAL_NODES,  # 给L2路由器一个唯一ID
    "num_ports": "2",   # 只需要2个端口：连接L2和连接网络
    "link_bw": LINK_BANDWIDTH,
    "flit_size": "8B",
    "xbar_bw": LINK_BANDWIDTH,
    "input_latency": LINK_LATENCY,
    "output_latency": LINK_LATENCY,
    "input_buf_size": "1KiB",
    "output_buf_size": "1KiB",
})

# L2到L2路由器
l2_net_link = sst.Link("l2_net_link")
l2_net_link.connect(
    (l2_cache, "high_network_0", "50ps"),
    (l2_router, "port0", "50ps")
)

# L2路由器到主网络 (连接到节点0)
l2_main_link = sst.Link("l2_main_link")
l2_main_link.connect(
    (l2_router, "port1", "50ps"),
    (routers[0], "port4", "50ps")  # 替换原来的CPU连接
)

# --- 配置系统统计 ---
print("\n=== 配置Miranda系统统计收集 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./miranda_mesh_stats.csv"})

# 启用详细统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("miranda.BaseCPU")
sst.enableAllStatisticsForComponentType("memHierarchy.Cache")

# 启用特定统计项
for i in range(TOTAL_NODES):
    router_name = f"router_{i}"
    sst.enableStatisticForComponentName(router_name, "send_packet_count")
    sst.enableStatisticForComponentName(router_name, "recv_packet_count") 
    sst.enableStatisticForComponentName(router_name, "send_bit_count")
    sst.enableStatisticForComponentName(router_name, "recv_bit_count")

print("✓ 统计收集配置完成")

# --- 系统总结 ---
print(f"\n=== Miranda CPU系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个CPU核心")
print(f"   • CPU模拟器: Miranda (指令级模拟)")
print(f"   • 内存层次: L1缓存 + 共享L2缓存 + 主内存")
print(f"   • 网络拓扑: 2D Mesh (二维网格)")
print(f"   • 链路性能: {LINK_BANDWIDTH} 带宽, {LINK_LATENCY} 延迟")

print(f"\n🧠 工作负载分布:")
print(f"   • 主控核心 (0,0): 随机访问模式")
print(f"   • 内存控制器 (3,3): STREAM流式访问")
print(f"   • I/O核心 (边缘): GUPS随机访问")
print(f"   • 计算核心 (内部): 单流顺序访问")

print(f"\n🚀 开始Miranda CPU系统仿真...")
print("   各核心将根据不同访问模式生成真实网络流量")
