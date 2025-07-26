import sst

# --- 基于4x4 mesh的真实CPU系统架构 ---
# 使用Ariel CPU模拟器和内存层次结构生成真实的网络流量

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []
cpu_cores = []

print("=== 构建基于4x4 Mesh的真实CPU系统架构 ===")
print("使用Ariel CPU模拟器和内存系统生成真实网络流量")

# --- 创建CPU节点 (使用Ariel CPU模拟器) ---
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

    # 创建Ariel CPU核心
    cpu_core = sst.Component(f"cpu_{i}", "ariel.ariel")
    
    # 根据核心位置配置不同的工作负载
    x = i % MESH_SIZE_X
    y = i // MESH_SIZE_X
    
    if x == 0 and y == 0:  # 主控核心 - 高负载
        cpu_core.addParams({
            "verbose": "1",
            "maxcorequeue": "256",
            "maxissuepercycle": "2",
            "pipetimeout": "0",
            "executable": "/bin/ls",  # 简单的可执行程序
            "arielmode": "1",
            "memorylevels": "1",
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 主控核心 - 高性能配置")
        
    elif x == MESH_SIZE_X-1 and y == MESH_SIZE_Y-1:  # 内存控制器核心
        cpu_core.addParams({
            "verbose": "1",
            "maxcorequeue": "512",
            "maxissuepercycle": "4",
            "pipetimeout": "0",
            "executable": "/bin/ls",
            "arielmode": "1",
            "memorylevels": "1",
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 内存控制器核心")
        
    else:  # 标准计算核心
        cpu_core.addParams({
            "verbose": "1",
            "maxcorequeue": "128",
            "maxissuepercycle": "1",
            "pipetimeout": "0",
            "executable": "/bin/ls",
            "arielmode": "1",
            "memorylevels": "1",
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 标准计算核心")

    # 创建L1缓存
    l1_cache = sst.Component(f"l1cache_{i}", "memHierarchy.Cache")
    l1_cache.addParams({
        "cache_frequency": "2.4GHz",
        "cache_size": "32KiB",
        "associativity": "8",
        "access_latency_cycles": "1",
        "L1": "1",
        "verbose": "1",
    })

    # 创建内存接口
    mem_iface = cpu_core.setSubComponent("memmgr", "ariel.MemoryManagerSimple")
    mem_iface.addParams({
        "pagecount0": "1048576",
        "pagesize0": "4096",
    })

    # 连接CPU和L1缓存
    cpu_cache_link = sst.Link(f"cpu_cache_link_{i}")
    cpu_cache_link.connect(
        (cpu_core, "cache_link_0", "50ps"),
        (l1_cache, "high_network_0", "50ps")
    )

    # 连接L1缓存到网络
    cache_net_link = sst.Link(f"cache_net_link_{i}")
    cache_net_link.connect(
        (l1_cache, "low_network_0", "50ps"),
        (router, "port4", "50ps")  # 本地端口
    )

    routers.append(router)
    cpu_cores.append(cpu_core)

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

# --- 创建共享L2缓存和内存控制器 ---
print("\n=== 创建共享内存系统 ===")

# 创建L2缓存 (在节点15，右下角)
l2_cache = sst.Component("l2cache", "memHierarchy.Cache")
l2_cache.addParams({
    "cache_frequency": "2.4GHz",
    "cache_size": "256KiB",
    "associativity": "16",
    "access_latency_cycles": "6",
    "L1": "0",
    "verbose": "1",
})

# 创建内存控制器
memory_ctrl = sst.Component("memory", "memHierarchy.MemController")
memory_ctrl.addParams({
    "clock": "1GHz",
    "backing": "none",
    "verbose": "1",
})

# 创建内存
memory = memory_ctrl.setSubComponent("backend", "memHierarchy.simpleMem")
memory.addParams({
    "access_time": "100ns",
    "mem_size": "512MiB",
})

# 连接L2缓存到内存控制器
l2_mem_link = sst.Link("l2_mem_link")
l2_mem_link.connect(
    (l2_cache, "low_network_0", "50ps"),
    (memory_ctrl, "direct_link", "50ps")
)

# 连接L2缓存到网络 (通过路由器15)
l2_net_link = sst.Link("l2_net_link")
l2_net_link.connect(
    (l2_cache, "high_network_0", "50ps"),
    (routers[15], "port4", "50ps")  # 使用节点15的本地端口
)

# --- 配置系统统计 ---
print("\n=== 配置CPU系统统计收集 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./cpu_ariel_mesh_stats.csv"})

# 启用详细统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("ariel.ariel")
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
print(f"\n=== 真实CPU系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个CPU核心")
print(f"   • CPU模拟器: Ariel (真实指令级模拟)")
print(f"   • 内存层次: L1缓存 + 共享L2缓存 + 主内存")
print(f"   • 网络拓扑: 2D Mesh (二维网格)")
print(f"   • 链路性能: {LINK_BANDWIDTH} 带宽, {LINK_LATENCY} 延迟")

print(f"\n🧠 内存系统:")
print(f"   • L1缓存: 每核心32KiB, 8路组相联")
print(f"   • L2缓存: 共享256KiB, 16路组相联")
print(f"   • 主内存: 512MiB, 100ns访问延迟")

print(f"\n🚀 开始真实CPU系统仿真...")
print("   CPU将执行真实指令并生成内存访问流量")
