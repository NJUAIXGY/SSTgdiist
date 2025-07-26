import sst

# --- 实际的CPU+内存系统架构 ---
MESH_SIZE_X = 2
MESH_SIZE_Y = 2
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

# 系统参数
CPU_CLOCK = "2.4GHz"
CACHE_SIZE = "32KiB"
MEMORY_CLOCK = "1.2GHz"

print("Creating realistic CPU system with mesh interconnect...")

# --- 创建内存控制器 ---
memctrl = sst.Component("memory_controller", "memHierarchy.MemController")
memctrl.addParams({
    "clock": MEMORY_CLOCK,
    "backing": "none",
    "addr_range_start": "0x0",
    "addr_range_end": "0x1FFFFFFF",  # 512MB内存空间
})

# 创建内存设备
memory = memctrl.setSubComponent("backend", "memHierarchy.simpleMem")
memory.addParams({
    "access_time": "100ns",
    "mem_size": "512MiB",
})

# --- 创建共享L2缓存 ---
l2_cache = sst.Component("l2cache", "memHierarchy.Cache")
l2_cache.addParams({
    "access_latency_cycles": "20",
    "cache_frequency": CPU_CLOCK,
    "replacement_policy": "lru",
    "coherence_protocol": "MSI",
    "associativity": "8",
    "cache_line_size": "64",
    "cache_size": "256KiB",
    "L1": "0",
    "debug": "0"
})

# 连接L2缓存到内存控制器
l2_mem_link = sst.Link("l2_mem_link")
l2_mem_link.connect(
    (l2_cache, "low_network_0", "100ps"),
    (memctrl, "direct_link", "100ps")
)

# --- 创建CPU核心和L1缓存 ---
routers = []
cpu_cores = []

for i in range(TOTAL_NODES):
    # 创建路由器
    router = sst.Component(f"router_{i}", "merlin.hr_router")
    router.addParams({
        "id": i,
        "num_ports": "5",
        "link_bw": LINK_BANDWIDTH,
        "flit_size": "8B",
        "xbar_bw": LINK_BANDWIDTH,
        "input_latency": LINK_LATENCY,
        "output_latency": LINK_LATENCY,
        "input_buf_size": "1KiB",
        "output_buf_size": "1KiB",
    })

    # 配置拓扑
    topo_sub = router.setSubComponent("topology", "merlin.mesh")
    topo_sub.addParams({
        "network_name": "CPUMesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建CPU核心（使用Ariel进行更真实的CPU建模）
    cpu = sst.Component(f"cpu_{i}", "ariel.ariel")
    cpu.addParams({
        "verbose": "0",
        "clock": CPU_CLOCK,
        "maxcorequeue": "256",
        "maxissuepercycle": "2",
        "pipetimeout": "0",
        "executable": "/bin/echo",  # 简单的可执行文件
        "arielmode": "1",
        "corecount": "1",
    })

    # 创建L1数据缓存
    l1d_cache = sst.Component(f"l1dcache_{i}", "memHierarchy.Cache")
    l1d_cache.addParams({
        "access_latency_cycles": "2",
        "cache_frequency": CPU_CLOCK,
        "replacement_policy": "lru",
        "coherence_protocol": "MSI",
        "associativity": "4",
        "cache_line_size": "64",
        "cache_size": CACHE_SIZE,
        "L1": "1",
        "debug": "0"
    })

    # 创建L1指令缓存
    l1i_cache = sst.Component(f"l1icache_{i}", "memHierarchy.Cache")
    l1i_cache.addParams({
        "access_latency_cycles": "2",
        "cache_frequency": CPU_CLOCK,
        "replacement_policy": "lru",
        "coherence_protocol": "MSI",
        "associativity": "4",
        "cache_line_size": "64",
        "cache_size": CACHE_SIZE,
        "L1": "1",
        "debug": "0"
    })

    # 连接CPU到L1缓存
    cpu_l1d_link = sst.Link(f"cpu_l1d_link_{i}")
    cpu_l1d_link.connect(
        (cpu, "cache_link_0", "100ps"),
        (l1d_cache, "high_network_0", "100ps")
    )

    cpu_l1i_link = sst.Link(f"cpu_l1i_link_{i}")
    cpu_l1i_link.connect(
        (cpu, "cache_link_1", "100ps"),
        (l1i_cache, "high_network_0", "100ps")
    )

    # 连接L1缓存到路由器
    l1d_router_link = sst.Link(f"l1d_router_link_{i}")
    l1d_router_link.connect(
        (l1d_cache, "low_network_0", "100ps"),
        (router, "port4", "100ps")
    )

    # 为简化，只连接数据缓存到网络
    # 指令缓存可以连接到同一个L2

    routers.append(router)
    cpu_cores.append(cpu)

# --- 构建mesh网络 ---
print("Building mesh interconnect...")

for y in range(MESH_SIZE_Y):
    for x in range(MESH_SIZE_X):
        node_id = y * MESH_SIZE_X + x
        
        # 东西连接
        if x < MESH_SIZE_X - 1:
            link = sst.Link(f"mesh_east_{x}_{y}")
            link.connect(
                (routers[node_id], "port0", LINK_LATENCY),
                (routers[node_id + 1], "port1", LINK_LATENCY)
            )
        
        # 南北连接
        if y < MESH_SIZE_Y - 1:
            link = sst.Link(f"mesh_south_{x}_{y}")
            link.connect(
                (routers[node_id], "port2", LINK_LATENCY),
                (routers[node_id + MESH_SIZE_X], "port3", LINK_LATENCY)
            )

# --- 连接L2缓存到mesh网络 ---
# 将L2缓存连接到router_1的一个可用端口
l2_router_link = sst.Link("l2_router_link")
l2_router_link.connect(
    (l2_cache, "high_network_0", "100ps"),
    (routers[1], "port3", "100ps")  # 连接到router_1的北端口（2x2网格中router_1没有北邻居）
)

# --- 配置统计 ---
print("Configuring system statistics...")

sst.setStatisticLoadLevel(4)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./realistic_cpu_stats.csv"})

# 启用统计
sst.enableAllStatisticsForComponentType("memHierarchy.Cache")
sst.enableAllStatisticsForComponentType("memHierarchy.MemController")
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("ariel.ariel")

print(f"✓ Created {TOTAL_NODES} CPU cores with L1 caches")
print("✓ Created shared L2 cache")
print("✓ Created memory controller with 512MB memory")
print(f"✓ Built {MESH_SIZE_X}x{MESH_SIZE_Y} mesh interconnect")
print("Starting realistic CPU system simulation...")

# 设置仿真结束条件 - 运行到1毫秒
sst.setStatisticLoadLevel(4)
