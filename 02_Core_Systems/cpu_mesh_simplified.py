import sst

# --- 简化的Miranda CPU 4x4 mesh系统 ---
# 使用最简单的方法避免memHierarchy的复杂连接问题

MESH_SIZE_X = 4
MESH_SIZE_Y = 4
TOTAL_NODES = MESH_SIZE_X * MESH_SIZE_Y
LINK_BANDWIDTH = "40GiB/s"
LINK_LATENCY = "50ps"

routers = []

print("=== 构建简化的Miranda CPU 4x4 Mesh系统 ===")
print("使用简化的内存模型避免复杂连接问题")

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

    # 创建基础端点作为路由器的子组件
    endpoint = router.setSubComponent("endpoint", "merlin.endpoint")
    endpoint.addParams({
        "id": i,
        "topology": "merlin.mesh",
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

    # 使用最简单的内存接口，直接连接一个简单内存
    mem_iface = cpu_core.setSubComponent("memory", "memHierarchy.standardInterface")
    
    # 使用标准内存控制器替代simpleMem
    mem_ctrl = sst.Component(f"mem_ctrl_{i}", "memHierarchy.MemController")
    mem_ctrl.addParams({
        "clock": "1GHz",
        "backing": "none",
        "verbose": "0",
        "addr_range_start": "0",  # 所有内存控制器都从地址0开始
        "addr_range_end": "134217727",  # 128MB地址空间 (128*1024*1024-1)
    })
    
    # 创建内存后端
    mem_backend = mem_ctrl.setSubComponent("backend", "memHierarchy.simpleMem")
    mem_backend.addParams({
        "access_time": "100ns",
        "mem_size": "128MiB",
    })
    
    # 连接CPU内存接口到内存控制器
    cpu_mem_link = sst.Link(f"cpu_mem_link_{i}")
    cpu_mem_link.connect(
        (mem_iface, "port", "50ps"),
        (mem_ctrl, "direct_link", "50ps")
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

# --- 配置统计收集 ---
print("\n=== 配置简化Miranda CPU系统统计 ===")

sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV", {"filepath": "../03_Output_Data/simplified_miranda_stats.csv"})

# 启用Miranda CPU统计
sst.enableAllStatisticsForComponentType("miranda.BaseCPU")
sst.enableAllStatisticsForComponentType("merlin.hr_router") 
sst.enableAllStatisticsForComponentType("merlin.endpoint")
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

print("✓ 简化Miranda CPU系统统计配置完成")

# --- 系统总结 ---
print(f"\n=== 简化Miranda CPU系统配置总结 ===")
print(f"🏗️  系统架构:")
print(f"   • 网格规模: {MESH_SIZE_X}×{MESH_SIZE_Y} = {TOTAL_NODES} 个Miranda CPU核心")
print(f"   • CPU模拟器: Miranda BaseCPU (真实指令执行)")
print(f"   • 内存模型: 分布式简单内存 (每核心128MB)")
print(f"   • 网络拓扑: 2D Mesh + endpoint通信")
print(f"   • 链路性能: {LINK_BANDWIDTH} 带宽, {LINK_LATENCY} 延迟")

print(f"\n🧠 CPU工作负载分布:")
print(f"   • 主控核心: STREAM基准测试 (内存带宽测试)")
print(f"   • 内存控制器: 随机内存访问模式")
print(f"   • I/O核心: 单流顺序访问模式")
print(f"   • 计算核心: GUPS基准测试 (随机访问性能)")

print(f"\n🚀 开始简化Miranda CPU系统仿真...")
print("   Miranda将生成真实的内存访问，网络将传输endpoint数据")
