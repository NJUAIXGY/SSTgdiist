import sst

# --- 1. 系统参数定义 ---
MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

# CPU和内存参数
CPU_CLOCK = "2.4GHz"
CACHE_SIZE = "32KiB"
MEMORY_SIZE = "1GiB"
MEMORY_CLOCK = "1.2GHz"

routers = []
cpu_cores = []
memory_controllers = []

# --- 2. 创建CPU核心和内存控制器 ---
print("Creating 4x4 mesh-based CPU system...")

for i in range(TOTAL_NODES):
    # 创建路由器
    router = sst.Component(f"router_{i}", "merlin.hr_router")
    router.addParams({
        "id": i,
        "num_ports": "6",  # 4个网络方向 + 1个本地端口 + 1个内存端口
        "link_bw": LINK_BANDWIDTH,
        "flit_size": "8B",
        "xbar_bw": LINK_BANDWIDTH,
        "input_latency": LINK_LATENCY,
        "output_latency": LINK_LATENCY,
        "input_buf_size": "1KiB",
        "output_buf_size": "1KiB",
    })

    # 配置拓扑子组件
    topo_sub = router.setSubComponent("topology", "merlin.mesh")
    topo_sub.addParams({
        "network_name": "CPUMesh",
        "shape": f"{MESH_SIZE_X}x{MESH_SIZE_Y}",
        "width": "1x1",
        "local_ports": "1",
    })

    # 创建CPU核心 (使用Miranda CPU模拟器)
    cpu = sst.Component(f"cpu_{i}", "miranda.BaseCPU")
    cpu.addParams({
        "verbose": "0",
        "clock": CPU_CLOCK,
        "printStats": "1",
    })
    
    # 添加CPU指令生成器
    cpu_gen = cpu.setSubComponent("generator", "miranda.SingleStreamGenerator")
    cpu_gen.addParams({
        "verbose": "0",
        "count": "1000",           # 生成1000个内存操作
        "max_address": "0x100000", # 1MB地址空间
        "start_at": f"{i * 0x10000}",  # 每个CPU有不同的起始地址
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

    # 创建内存控制器（每4个核心共享一个）
    if i % 4 == 0:  # 只在某些节点创建内存控制器
        memctrl = sst.Component(f"memory_{i//4}", "memHierarchy.MemController")
        memctrl.addParams({
            "clock": MEMORY_CLOCK,
            "backing": "none",
            "addr_range_start": f"{(i//4) * 0x40000000}",
            "addr_range_end": f"{((i//4) + 1) * 0x40000000 - 1}",
        })
        
        # 创建内存设备
        memory = memctrl.setSubComponent("backend", "memHierarchy.simpleMem")
        memory.addParams({
            "access_time": "100ns",
            "mem_size": MEMORY_SIZE,
        })
        
        memory_controllers.append(memctrl)

    # 创建网络接口连接CPU到路由器 (直接连接，不使用独立的NIC)
    # CPU -> L1 Cache -> Router 的连接方式
    
    # 连接组件
    # CPU -> L1 Cache
    cpu_cache_link = sst.Link(f"cpu_cache_link_{i}")
    cpu_cache_link.connect(
        (cpu, "cache_link", "100ps"),
        (l1_cache, "high_network_0", "100ps")
    )

    # L1 Cache -> Router (直接连接)
    cache_router_link = sst.Link(f"cache_router_link_{i}")
    cache_router_link.connect(
        (l1_cache, "low_network_0", "100ps"),
        (router, "port4", "100ps")
    )

    routers.append(router)
    cpu_cores.append(cpu)

# --- 3. 构建mesh网络连接 ---
print("Connecting mesh network...")

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

# --- 4. 连接内存控制器到网络 ---
print("Connecting memory controllers to mesh...")

for i, memctrl in enumerate(memory_controllers):
    # 连接内存控制器直接到路由器
    mem_router_id = i * 4  # 内存控制器连接到第0, 4, 8, 12号路由器
    mem_ctrl_link = sst.Link(f"mem_ctrl_link_{i}")
    mem_ctrl_link.connect(
        (memctrl, "network", "100ps"),
        (routers[mem_router_id], "port5", "100ps")  # 使用port5避免冲突
    )

# --- 5. 配置统计与运行 ---
print("Configuring CPU system statistics...")

# 设置统计收集
sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "./cpu_mesh_stats.csv"})

# 启用各组件统计
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("memHierarchy.Cache")
sst.enableAllStatisticsForComponentType("memHierarchy.MemController")
sst.enableAllStatisticsForComponentType("miranda.BaseCPU")

# 设置仿真时间
print(f"✓ Created {TOTAL_NODES} CPU cores with L1 caches")
print(f"✓ Created {len(memory_controllers)} memory controllers")
print(f"✓ Built {MESH_SIZE_X}x{MESH_SIZE_Y} mesh network")
print("Starting CPU system simulation...")

# 这将运行直到所有CPU完成其指令流
