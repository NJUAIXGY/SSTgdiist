import sst

# --- CPU+缓存+内存系统 (使用Miranda CPU模拟器) ---
MESH_SIZE_X = 2
MESH_SIZE_Y = 2
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

# 系统参数
CPU_CLOCK = "2.4GHz"
CACHE_SIZE = "32KiB"
MEMORY_CLOCK = "1.2GHz"

print("Creating CPU system with Miranda cores and mesh interconnect...")

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

# --- 创建CPU核心和缓存系统 ---
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

    # 创建Miranda CPU核心
    cpu = sst.Component(f"cpu_{i}", "miranda.BaseCPU")
    cpu.addParams({
        "verbose": "0",
        "clock": CPU_CLOCK,
        "printStats": "1",
    })
    
    # 添加单流内存访问生成器
    cpu_gen = cpu.setSubComponent("generator", "miranda.SingleStreamGenerator")
    cpu_gen.addParams({
        "verbose": "0",
        "count": "500",                    # 每个CPU生成500个内存访问
        "max_address": "0x100000",         # 1MB地址空间
        "start_at": f"{i * 0x10000}",      # 每个CPU有不同的起始地址
        "stride": "64",                    # 64字节步长（缓存行大小）
        "data_width": "8",                 # 8字节数据宽度
    })

    # 创建L1缓存
    l1_cache = sst.Component(f"l1cache_{i}", "memHierarchy.Cache")
    l1_cache.addParams({
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
    cpu_cache_link = sst.Link(f"cpu_cache_link_{i}")
    cpu_cache_link.connect(
        (cpu, "cache_link", "100ps"),
        (l1_cache, "high_network_0", "100ps")
    )

    # 连接L1缓存到路由器
    cache_router_link = sst.Link(f"cache_router_link_{i}")
    cache_router_link.connect(
        (l1_cache, "low_network_0", "100ps"),
        (router, "port4", "100ps")
    )

    routers.append(router)
    cpu_cores.append(cpu)

# --- 构建mesh网络 ---
print("Building 2x2 mesh interconnect...")

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

# --- 创建共享L2缓存并连接到mesh ---
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

# 创建路由器专门给L2缓存
l2_router = sst.Component("l2_router", "merlin.hr_router")
l2_router.addParams({
    "id": TOTAL_NODES,  # 给L2路由器一个独特的ID
    "num_ports": "2",   # 只需要2个端口：连接L2和连接到mesh
    "link_bw": LINK_BANDWIDTH,
    "flit_size": "8B",
    "xbar_bw": LINK_BANDWIDTH,
    "input_latency": LINK_LATENCY,
    "output_latency": LINK_LATENCY,
    "input_buf_size": "1KiB",
    "output_buf_size": "1KiB",
})

# 配置L2路由器的拓扑
l2_topo_sub = l2_router.setSubComponent("topology", "merlin.singlerouter")
l2_topo_sub.addParams({
    "network_name": "L2Network",
    "local_ports": "1",
})

# 连接L2缓存到其路由器
l2_cache_router_link = sst.Link("l2_cache_router_link")
l2_cache_router_link.connect(
    (l2_cache, "high_network_0", "100ps"),
    (l2_router, "port0", "100ps")
)

# 连接L2路由器到主mesh（使用router_0的一个空闲端口）
l2_mesh_link = sst.Link("l2_mesh_link")
l2_mesh_link.connect(
    (l2_router, "port1", LINK_LATENCY),
    (routers[0], "port3", LINK_LATENCY)  # router_0的北端口在2x2网格中是空闲的
)

# --- 配置统计 ---
print("Configuring system statistics...")

sst.setStatisticLoadLevel(4)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./miranda_cpu_stats.csv"})

# 启用统计
sst.enableAllStatisticsForComponentType("memHierarchy.Cache")
sst.enableAllStatisticsForComponentType("memHierarchy.MemController")
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("miranda.BaseCPU")

print(f"✓ Created {TOTAL_NODES} Miranda CPU cores")
print("✓ Created L1 caches for each core")
print("✓ Created shared L2 cache")
print("✓ Created memory controller with 512MB memory")
print(f"✓ Built {MESH_SIZE_X}x{MESH_SIZE_Y} mesh interconnect")
print("✓ Connected L2 cache to mesh via dedicated router")
print("Starting Miranda CPU system simulation...")
