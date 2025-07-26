import sst

# --- 使用Miranda CPU模拟器的4x4 mesh系统 ---
# Miranda是SST的CPU模拟器，能够生成真实的内存访问模式

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 构建基于Miranda CPU的4x4 Mesh系统 ===")
print("使用Miranda CPU模拟器生成真实的网络流量")

# --- 创建带有Miranda CPU的节点 ---
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
        "network_name": "Miranda_CPU_Mesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建Miranda CPU核心
    cpu_core = sst.Component(f"cpu_{i}", "miranda.BaseCPU")
    
    # 根据核心位置配置不同的工作负载
    x = i % MESH_SIZE_X
    y = i // MESH_SIZE_X
    
    if x == 0 and y == 0:  # 主控核心 - 执行控制任务
        cpu_core.addParams({
            "verbose": "1",
            "printStats": "1",
            "clock": "2.4GHz",
            "max_reqs_cycle": "2",        # 每周期最大请求数
            "generator": "miranda.STREAMBenchGenerator",  # 流处理基准测试
            "generatorParams.verbose": "1",
            "generatorParams.n": "10000",      # 数组大小
            "generatorParams.operandwidth": "8", # 8字节操作数
            "generatorParams.iterations": "100", # 迭代次数
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 主控核心 - STREAM基准测试")
        
    elif x == MESH_SIZE_X-1 and y == MESH_SIZE_Y-1:  # 内存控制器核心
        cpu_core.addParams({
            "verbose": "1",
            "printStats": "1", 
            "clock": "2.4GHz",
            "max_reqs_cycle": "4",        # 内存控制器处理更多请求
            "generator": "miranda.RandomGenerator",  # 随机内存访问
            "generatorParams.verbose": "1",
            "generatorParams.count": "5000",       # 请求数量
            "generatorParams.max_address": "1048576", # 1MB地址空间
            "generatorParams.min_address": "0",
            "generatorParams.length": "64",        # 64字节请求
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 内存控制器 - 随机访问模式")
        
    elif x == 0 or x == MESH_SIZE_X-1 or y == 0 or y == MESH_SIZE_Y-1:  # I/O核心
        cpu_core.addParams({
            "verbose": "1",
            "printStats": "1",
            "clock": "2.4GHz", 
            "max_reqs_cycle": "1",
            "generator": "miranda.SingleStreamGenerator", # 单流访问
            "generatorParams.verbose": "1",
            "generatorParams.count": "2000",        # 较少的请求
            "generatorParams.start_a": "0",
            "generatorParams.length": "32",         # 32字节I/O操作
            "generatorParams.stride": "32",         # 连续访问
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): I/O核心 - 单流访问模式")
        
    else:  # 计算核心
        cpu_core.addParams({
            "verbose": "1", 
            "printStats": "1",
            "clock": "2.4GHz",
            "max_reqs_cycle": "2",
            "generator": "miranda.GUPSGenerator",    # GUPS基准测试
            "generatorParams.verbose": "1",
            "generatorParams.count": "3000",        # 请求数量
            "generatorParams.max_address": "524288", # 512KB地址空间
            "generatorParams.min_address": "0",
            "generatorParams.iterations": "50",     # 迭代次数
        })
        print(f"  - CPU核心 {i} (位置: {x},{y}): 计算核心 - GUPS基准测试")

    # 创建内存接口
    mem_iface = cpu_core.setSubComponent("memory", "memHierarchy.standardInterface")
    
    # 创建L1缓存（简化设计，只连接到网络）
    l1_cache = sst.Component(f"l1cache_{i}", "memHierarchy.Cache")
    l1_cache.addParams({
        "cache_frequency": "2.4GHz",
        "cache_size": "32KiB",
        "associativity": "8",
        "access_latency_cycles": "1",
        "L1": "1",
        "verbose": "0",
        "coherence_protocol": "none",  # 简化协议
        "replacement_policy": "lru",
    })
    
    # 创建网络端口子组件
    net_iface = l1_cache.setSubComponent("lowlink", "memHierarchy.MemNIC")
    net_iface.addParams({
        "group": "1",
        "destinations": [str(j) for j in range(TOTAL_NODES) if j != i],  # 其他所有节点
    })
    
    # 连接CPU到L1缓存
    cpu_cache_link = sst.Link(f"cpu_cache_link_{i}")
    cpu_cache_link.connect(
        (mem_iface, "port", "50ps"),
        (l1_cache, "high_network_0", "50ps")
    )
    
    # 连接L1缓存到网络路由器
    cache_router_link = sst.Link(f"cache_router_link_{i}")
    cache_router_link.connect(
        (net_iface, "port", LINK_LATENCY),
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

# --- 创建共享内存系统 ---
print("\n=== 创建共享内存系统 ===")

# 创建内存控制器
memory_controller = sst.Component("memory_controller", "memHierarchy.MemController")
memory_controller.addParams({
    "clock": "1GHz",
    "backing": "none",
    "verbose": "0",
    "addr_range_start": "0",
    "addr_range_end": "2147483647",  # 2GB地址空间
})

# 创建共享内存后端
shared_memory = memory_controller.setSubComponent("backend", "memHierarchy.simpleMem")
shared_memory.addParams({
    "access_time": "100ns",
    "mem_size": "2GiB",
})

# 连接内存控制器到网络
# 我们将内存控制器作为一个虚拟节点连接到网络中的一个路由器
memory_router_link = sst.Link("memory_router_link")
memory_router_link.connect(
    (memory_controller, "direct_link", LINK_LATENCY),
    (routers[15], "port4", LINK_LATENCY)  # 连接到角落的路由器
)

print("✓ 共享内存控制器连接到网络节点15")

# --- 配置统计收集 ---
print("\n=== 配置Miranda CPU系统统计 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./miranda_mesh_stats.csv"})

# 启用Miranda CPU统计
sst.enableAllStatisticsForComponentType("miranda.BaseCPU")
sst.enableAllStatisticsForComponentType("merlin.hr_router") 
sst.enableAllStatisticsForComponentType("memHierarchy.standardInterface")
sst.enableAllStatisticsForComponentType("memHierarchy.Cache")
sst.enableAllStatisticsForComponentType("memHierarchy.MemController")

# 启用特定统计项
for i in range(TOTAL_NODES):
    cpu_name = f"cpu_{i}"
    router_name = f"router_{i}"
    
    # CPU统计
    sst.enableStatisticForComponentName(cpu_name, "cycles")
    sst.enableStatisticForComponentName(cpu_name, "reqs_issued")
    sst.enableStatisticForComponentName(cpu_name, "reqs_returned")
    
    # 网络统计
    sst.enableStatisticForComponentName(router_name, "send_packet_count")
    sst.enableStatisticForComponentName(router_name, "recv_packet_count")

print("✓ Miranda CPU系统统计配置完成")

# --- 系统总结 ---
print(f"\n=== Miranda CPU系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个Miranda CPU核心")
print(f"   • CPU模拟器: Miranda BaseCPU (真实指令执行)")
print(f"   • 网络拓扑: 2D Mesh + 内存接口")
print(f"   • 链路性能: {LINK_BANDWIDTH} 带宽, {LINK_LATENCY} 延迟")

print(f"\n🧠 CPU工作负载分布:")
print(f"   • 主控核心: STREAM基准测试 (内存带宽测试)")
print(f"   • 内存控制器: 随机内存访问模式")
print(f"   • I/O核心: 单流顺序访问模式")
print(f"   • 计算核心: GUPS基准测试 (随机访问性能)")

print(f"\n🚀 开始Miranda CPU系统仿真...")
print("   Miranda将生成真实的内存访问和网络流量")
