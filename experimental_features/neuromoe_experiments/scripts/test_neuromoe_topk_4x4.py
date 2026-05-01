#!/usr/bin/env python3

import sst
import os
import struct
import csv
import os
MODE = os.environ.get("NEUROMOE_MODE", "weight_driven")  # options: weight_driven|edges_csv
CSV_PATH = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "configs", "gating_edges_k4.csv")
TOPK = int(os.environ.get("NEUROMOE_TOPK", "4"))
EPS = float(os.environ.get("NEUROMOE_EPS", "0.6"))
USE_BATCH = os.environ.get("NEUROMOE_BATCH", "0") in ("1","true","True","YES","yes")
VNSEP = os.environ.get("NEUROMOE_VNSEP", "0") in ("1","true","True","YES","yes")
BATCH_LOCAL = int(os.environ.get("NEUROMOE_BATCH_LOCAL", "8"))
BATCH_REMOTE = int(os.environ.get("NEUROMOE_BATCH_REMOTE", "32"))
BATCH_WIN_NS = int(os.environ.get("NEUROMOE_BATCH_WIN_NS", "1000"))
GATING_COMPONENT = os.environ.get("NEUROMOE_GATING_COMPONENT", "0") in ("1","true","True","YES","yes")
GATING_EVENT = os.environ.get("NEUROMOE_GATING_EVENT", "0") in ("1","true","True","YES","yes")

# === 4x4分层网络分类任务配置 ===

# === 提前配置统计输出（必须在创建任何组件之前）===
sst.setStatisticLoadLevel(5)
sst.setStatisticOutput("sst.statOutputCSV")
stats_out_dir = "/home/anarchy/SST/experimental_features/neuromoe_experiments/results"
os.makedirs(stats_out_dir, exist_ok=True)
stats_file = os.path.join(stats_out_dir, f"neuromoe_{MODE}_k{TOPK}.csv")
sst.setStatisticOutputOptions({
    "filepath": stats_file,
    "separator": ","
})
sst.enableAllStatisticsForComponentType("SnnDL.MultiCorePE")
sst.enableAllStatisticsForComponentType("SnnDL.SpikeSource")
sst.enableAllStatisticsForComponentType("merlin.hr_router")
sst.enableAllStatisticsForComponentType("SnnDL.SnnPESubComponent")
sst.enableAllStatisticsForAllComponents()  # 覆盖SubComponent启用，确保统计生效

# === 网络架构配置 ===
MESH_SIZE = 4  # 4x4网格
NUM_CORES_PER_PE = 4  # 每个PE的core数：4
NEURONS_PER_CORE = 4   # 每个core的神经元数：4
NEURONS_PER_PE = NUM_CORES_PER_PE * NEURONS_PER_CORE  # 每个PE的神经元数：16
TOTAL_NODES = MESH_SIZE * MESH_SIZE  # 16个节点
# 当启用在线门控并通过NoC注入时，为GatingPE预留1个逻辑节点ID（作为控制端点）
TOTAL_NODES_NIC = TOTAL_NODES + (1 if GATING_EVENT else 0)
SIMULATION_TIME = "2ms"  # 短仿真以便快速统计

# 网络分层定义
INPUT_LAYER = list(range(0, 4))      # PE 0-3: 输入层
HIDDEN_LAYER_1 = list(range(4, 8))   # PE 4-7: 隐藏层1
HIDDEN_LAYER_2 = list(range(8, 12))  # PE 8-11: 隐藏层2
OUTPUT_LAYER = list(range(12, 16))   # PE 12-15: 输出层

# 复杂分类任务配置
NUM_CLASSES = 4  # 4类分类
CLASS_A_FREQ = 40   # 类别A: 低频规律脉冲 (40Hz)
CLASS_B_FREQ = 80   # 类别B: 中频突发脉冲 (80Hz)
CLASS_C_FREQ = 120  # 类别C: 高频混合模式 (120Hz)
CLASS_D_FREQ = 200  # 类别D: 超高频稀疏脉冲 (200Hz)

# 权重内存布局
BASE_WEIGHT_ADDR = 0x10000000
PER_NODE_STRIDE = 32768  # 内存步长以容纳权重

# 网络参数
NETWORK_BANDWIDTH = "40GiB/s"
BUFFER_SIZE = "8KiB"

print(f"🧠 分层神经网络分类任务(NeuroMoE: {MODE}, TopK={TOPK}, Eps={EPS}): {MESH_SIZE}x{MESH_SIZE} = {TOTAL_NODES}个节点")
print(f"📊 网络架构:")
print(f"  输入层 (PE 0-3): {INPUT_LAYER}")
print(f"  隐藏层1 (PE 4-7): {HIDDEN_LAYER_1}")
print(f"  隐藏层2 (PE 8-11): {HIDDEN_LAYER_2}")
print(f"  输出层 (PE 12-15): {OUTPUT_LAYER}")
print(f"🎯 复杂分类任务: 类别A({CLASS_A_FREQ}Hz) vs 类别B({CLASS_B_FREQ}Hz) vs 类别C({CLASS_C_FREQ}Hz) vs 类别D({CLASS_D_FREQ}Hz)")
print(f"⚙️  权重加载模式: 启用内存权重，使用分层设计的权重文件")

# === 数据文件与门控CSV（可选离线门控） ===
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
baseline_dir = os.path.join(repo_root, "SnnDL_Basic")
weights_dir = os.path.join(baseline_dir, "weights")

# 离线门控生成：在Python层生成edges_csv，避免SST init时序竞态
def generate_gating_csv(csv_path, top_k, rows_per_pe, transitions):
    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    with open(csv_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['src_global','dst_global','weight'])
        for (src_range, dst_range) in transitions:
            src_start, src_end = src_range
            dst_start, dst_end = dst_range
            dst_pes = list(range(dst_start, dst_end+1))
            cnt = len(dst_pes)
            for src_pe in range(src_start, src_end+1):
                # round-robin起始偏移，避免热点
                off = (src_pe - src_start) % max(1,cnt)
                # 选择top-k目的PE
                choose = [dst_pes[(off+i) % cnt] for i in range(min(top_k, cnt))]
                for row in range(rows_per_pe):
                    src_global = src_pe*rows_per_pe + row
                    for dst_pe in choose:
                        dst_global = dst_pe*rows_per_pe + row
                        w.writerow([src_global, dst_global, 1.0])

transitions = [((0,3),(4,7)), ((4,7),(8,11)), ((8,11),(12,15))]
transitions_str = "0-3:4-7,4-7:8-11,8-11:12-15"
if MODE == 'gating_pe_offline':
    generate_gating_csv(CSV_PATH, TOPK, NEURONS_PER_PE, transitions)
    print(f"✅ 生成门控CSV: {CSV_PATH}")

# 可选：实例化 GatingPE 组件（并预生成CSV作为顺序保障）
if GATING_COMPONENT:
    print("🧭 实例化 GatingPE 组件，并预生成CSV防止顺序竞态…")
    gating_comp = sst.Component("gating", "SnnDL.GatingPE")
    gating_comp.addParams({
        "total_nodes": TOTAL_NODES,
        "rows_per_pe": NEURONS_PER_PE,
        "top_k": TOPK,
        "transitions": transitions_str,
        "weight_value": 1.0,
        "edges_output_file": CSV_PATH,
        "csv_header": 1,
        "selection": "round_robin",
        "verbose": 0,
    })
    # 预生成一次，确保SnnPESubComponent在init前即可读取
    try:
        generate_gating_csv(CSV_PATH, TOPK, NEURONS_PER_PE, transitions)
        print(f"✅ 预生成门控CSV: {CSV_PATH}")
    except Exception as e:
        print(f"⚠️ 预生成CSV异常: {e}")

# 脉冲数据文件将从预先生成的文件中加载

# 权重将完全从预先生成的二进制文件中加载

# === 加载预先生成的脉冲数据文件 ===
spike_data_files = []
spike_dir = os.path.join(baseline_dir, "spike_data")

# 加载输入层(PE 0-3)的4类预生成数据
for pe_id in INPUT_LAYER:
    class_names = ['A', 'B', 'C', 'D']
    class_name = class_names[pe_id]
    
    spike_file = os.path.join(spike_dir, f"complex_input_pe_{pe_id}_class_{class_name}.txt")
    
    # 验证文件存在
    if not os.path.exists(spike_file):
        print(f"❌ 错误: 脉冲数据文件不存在: {spike_file}")
        print(f"请先运行: python3 scripts/generate_spike_data.py")
        exit(1)
    
    spike_data_files.append(spike_file)
    
    # 读取文件统计信息
    with open(spike_file, 'r') as f:
        lines = [line for line in f.readlines() if not line.startswith('#')]
    
    freqs = [CLASS_A_FREQ, CLASS_B_FREQ, CLASS_C_FREQ, CLASS_D_FREQ]
    freq = freqs[pe_id]
    print(f"  ✅ 加载PE{pe_id}: 类别{class_name} ({freq}Hz), {len(lines)}个脉冲事件")

print(f"\n🔗 使用预先生成的权重文件:")
print(f"  权重文件将完全从 {weights_dir} 目录中加载")
print(f"  每个PE有独立的权重文件: classification_weights_pe_{{0-15}}.bin")

# === 为每个PE创建独立的内存系统 ===
pe_memory_controllers = []
pe_weight_loaders = []
pe_memory_buses = []  # 存储内存总线以便后续连接L1缓存

for pe_id in range(TOTAL_NODES):
    # 为每个PE创建独立的内存控制器
    mem_controller = sst.Component(f"pe_{pe_id}_memory_controller", "memHierarchy.MemController")
    mem_controller.addParams({
        "clock": "1GHz",
        "backing": "malloc",
        "addr_range_start": "0",
        "addr_range_end": "67108863"  # 64MB地址范围
    })
    # 使用 backend 子组件，消除 legacy 警告
    mem_backend = mem_controller.setSubComponent("backend", "memHierarchy.simpleMem")
    mem_backend.addParams({
        "access_time": "100ns",
        "mem_size": "64MiB"
    })
    pe_memory_controllers.append(mem_controller)
    
    # 为每个PE创建内存总线，支持多个L1缓存连接
    mem_bus = sst.Component(f"pe_{pe_id}_memory_bus", "memHierarchy.Bus")
    mem_bus.addParams({
        "bus_frequency": "1GHz",
        "debug": "0",   # 精简Bus日志
        "verbose": "0"
    })
    pe_memory_buses.append(mem_bus)
    
    # 增加每PE共享L2缓存：位于总线与内存控制器之间
    l2_cache = sst.Component(f"pe_{pe_id}_l2", "memHierarchy.Cache")
    l2_cache.addParams({
        "cache_frequency": "2GHz",
        "cache_size": "128KiB",
        "associativity": "8",
        "cache_line_size": "64",
        "access_latency_cycles": "8",
        "L1": "0",
        "coherence_protocol": "mesi",
        "cache_type": "noninclusive",
        "debug": "0",
        "verbose": "0"
    })

    # 连接：Bus(lowlink0) ↔ L2(highlink) ↔ (mc_bus) ↔ MemController(highlink)
    bus_to_l2_link = sst.Link(f"pe_{pe_id}_bus_to_l2")
    bus_to_l2_link.connect(
        (mem_bus, "lowlink0", "5ns"),
        (l2_cache, "highlink", "5ns")
    )
    # 每个PE新增一个MC侧小总线，汇聚L2与WeightLoader写入
    mc_bus = sst.Component(f"pe_{pe_id}_mc_bus", "memHierarchy.Bus")
    mc_bus.addParams({
        "bus_frequency": "1GHz",
        "debug": "0",
        "verbose": "0"
    })
    # L2 → mc_bus
    l2_to_mc_link = sst.Link(f"pe_{pe_id}_l2_to_mc_bus")
    l2_to_mc_link.connect(
        (l2_cache, "lowlink", "5ns"),
        (mc_bus, "highlink0", "5ns")
    )
    # mc_bus → MemController
    mc_to_mem_link = sst.Link(f"pe_{pe_id}_mc_bus_to_mem")
    mc_to_mem_link.connect(
        (mc_bus, "lowlink0", "5ns"),
        (mem_controller, "highlink", "5ns")
    )
    
    # 为每个PE创建独立的WeightLoader (使用本地地址空间)
    weight_loader = sst.Component(f"pe_{pe_id}_weight_loader", "SnnDL.WeightLoader")
    weight_loader.addParams({
        "verbose": 0,  # 精简WeightLoader日志
        "base_addr_start": 0x0,  # 每个PE从地址0开始
        "per_core_stride": PER_NODE_STRIDE,
        "num_cores": 1,  # 每个WeightLoader只管理一个PE
        "neurons_per_core": NEURONS_PER_CORE,
        # 新增：按行(本地16)×列(全网256)写入
        "rows_per_core": NEURONS_PER_PE,
        "cols_per_core": TOTAL_NODES * NEURONS_PER_PE,
        "total_neurons": NEURONS_PER_PE,  # 只管理当前PE的神经元
        "weight_format": "bin",
        "per_core_files": 1,
        "file_template": os.path.join(weights_dir, f"classification_weights_pe_{pe_id}.bin"),
        "fill_value": 0.0,
        "validate_length": 1,
        "row_major": 1,
        "chunk_size_bytes": 128,
        "timed_seed_enable": 0
    })
    
    # 连接WeightLoader到内存总线 (使用highlink4，避免与核心L1缓存冲突)
    weight_loader_mem = weight_loader.setSubComponent("memory", "memHierarchy.standardInterface")
    weight_loader_mem.addParams({"port": "lowlink"})
    weight_loader_link = sst.Link(f"pe_{pe_id}_weight_loader_to_mc_bus")
    weight_loader_link.connect(
        (weight_loader_mem, "lowlink", "5ns"),
        (mc_bus, "highlink1", "5ns")  # Loader经mc_bus直达MemController，绕开Cache
    )
    
    pe_weight_loaders.append(weight_loader)

print(f"✅ 创建{len(pe_memory_controllers)}个独立PE内存控制器和{len(pe_memory_buses)}个内存总线")

# === 创建网络路由器 ===
routers = []
for i in range(TOTAL_NODES):
    router = sst.Component(f"router_{i}", "merlin.hr_router")
    router.addParams({
        "id": i,
        # 开两路本地端口：port4(PE NIC) + port5(Gating NIC)
        "num_ports": 6 if GATING_EVENT else 5,
        "link_bw": NETWORK_BANDWIDTH,
        "flit_size": "8B",
        "xbar_bw": NETWORK_BANDWIDTH,
        "input_latency": "10ns",
        "output_latency": "10ns",
        "input_buf_size": "4KiB",
        "output_buf_size": "4KiB",
        # 若开启门控事件或多VN分离，则启用2个VN
        "num_vns": 2 if (GATING_EVENT or (USE_BATCH and VNSEP)) else 1,
        "xbar_arb": "merlin.xbar_arb_lru",
        "debug": 0,
        "verbose": 0,
        "network_inspectors": "",
    })

    # 配置mesh拓扑
    topo = router.setSubComponent("topology", "merlin.mesh")
    topo.addParams({
        "shape": f"{MESH_SIZE}x{MESH_SIZE}",
        "width": "1x1",
        "local_ports": "1",
    })

    routers.append(router)

print(f"✅ 创建{len(routers)}个路由器完成")

# === 创建PE节点 ===
nodes = []
nics = []

for i in range(TOTAL_NODES):
    node = sst.Component(f"multicore_pe_{i}", "SnnDL.MultiCorePE")
    
    # 根据层类型调整神经元参数
    layer_name = "输入层" if i in INPUT_LAYER else \
                 "隐藏层1" if i in HIDDEN_LAYER_1 else \
                 "隐藏层2" if i in HIDDEN_LAYER_2 else "输出层"
    
    # 优化神经元阈值：降低阈值增强传播
    if i in INPUT_LAYER:
        v_thresh = 0.02   # 输入层：保持
    elif i in HIDDEN_LAYER_1:
        v_thresh = 0.03   # 阶段A：提高阈值，抑制二次风暴
    elif i in HIDDEN_LAYER_2:
        v_thresh = 0.03   # 阶段A：提高阈值，抑制二次风暴
    else:  # OUTPUT_LAYER
        v_thresh = 0.035  # 阶段C：输出层阈值上调以抑制末端发放
    
    # 阶段C：仅对输出层节点保留节点汇总行以便观察末端发放（日志极少，4行）
    print_node_summary_val = 1 if i in OUTPUT_LAYER else 0

    node_params = {
        "verbose": 0,
        "print_node_summary": print_node_summary_val,
        "num_cores": NUM_CORES_PER_PE,
        "neurons_per_core": NEURONS_PER_CORE,
        "total_neurons": TOTAL_NODES * NEURONS_PER_PE,
        "node_id": i,
        "global_neuron_base": i * NEURONS_PER_PE,
        "enable_test_traffic": 0,  # 关闭测试流量解决PE0异常接收问题
        "test_target_node": 15,  # 将测试流量重定向到PE15避免干扰PE0
        "test_period": 1000,  # 增大测试流量间隔减少干扰
        "test_spikes_per_burst": 1,  # 每次只发送1个测试脉冲
        "test_max_spikes": 10,  # 限制总测试脉冲数量
        "loop_dataset": 0,  # 禁用数据集循环
        "enable_memory_weights": 1,  # 启用内存权重，使用文件加载的权重
        "write_weights_on_init": 1,  # 启用权重初始化，加载分层权重文件
        "weights_file": os.path.join(weights_dir, f"classification_weights_pe_{i}.bin"),
        "v_thresh": v_thresh,  # 分层调整阈值
        "v_rest": 0.0,
        "v_reset": 0.0,
        "use_event_weight_fallback": 0,  # 严格权重模式：节点层关闭回退（与核心一致）
        "event_weight_fallback": 0.1,
        "verify_weights": 1,
        "weight_verify_samples": 8,      # 增加验证样本数
        "expected_weight_value": 4.0,     # 期望权重值（根据我们的权重强度）
        "verify_log_each_sample": 1,
        "memory_warmup_cycles": 500,     # 增加预热周期，确保写入完成后再开始读取
        "enable_weight_fetch": 1,
        "memory_weight_priority": 1,  # 优先使用内存权重而非事件权重
        "debug_weight_loading": 1,    # 启用权重加载调试信息
        "debug_memory_accesses": 1,   # 启用内存访问调试
        "verbose_weight_fetch": 1,    # 启用权重获取详细调试
        "enable_weight_fetch": 1,     # 确保启用权重获取
        "memory_warmup_cycles": 500   # 预热周期加长，避免读写竞态
    }

    # 每个PE使用本地地址空间(从0开始)
    weight_addr = 0x0  # 每个PE从地址0开始访问其独立内存
    node_params["base_addr"] = weight_addr

    node.addParams(node_params)

    # 创建SnnNIC网络接口
    nic = node.setSubComponent("network_interface", "SnnDL.SnnNIC")
    nic.addParams({
        "node_id": str(i),
        "link_bw": NETWORK_BANDWIDTH,
        "input_buf_size": BUFFER_SIZE,
        "output_buf_size": BUFFER_SIZE,
        "use_direct_link": "false",
        "port_name": "network",
        "verbose": 0,  # 精简NIC日志
        "total_nodes": TOTAL_NODES_NIC,
        # 控制/数据VN设置（门控时启用控制VN=1）
        "virtual_channels": 2 if (GATING_EVENT or (USE_BATCH and VNSEP)) else 1,
        "vn_control": 1 if (GATING_EVENT and VNSEP) else 0,
        # AER近似：多VN + 目的地批处理（可选）
        "virtual_channels": 2 if (USE_BATCH and VNSEP) else 1,
        "vn_spike_data": 0,
        "vn_batch_data": (1 if (USE_BATCH and VNSEP) else 0),
        "enable_batching": 1 if USE_BATCH else 0,
        "batch_size_local": BATCH_LOCAL,
        "batch_size_remote": BATCH_REMOTE,
        "batch_flush_window": BATCH_WIN_NS,
    })

    # 为每个核心在MultiCorePE上创建完整的SnnPESubComponent，并为每个配置其own memory子组件
    for core_idx in range(NUM_CORES_PER_PE):
        # 为每个核心创建SnnPESubComponent（作为用户配置的子组件）
        core_subcomponent = node.setSubComponent(f"core{core_idx}", "SnnDL.SnnPESubComponent")
        core_subcomponent.addParams({
            "core_id": core_idx,
            "total_cores": NUM_CORES_PER_PE,
            "global_neuron_base": i * NEURONS_PER_PE,
            "num_neurons": NUM_CORES_PER_PE * NEURONS_PER_CORE,  # 与MultiCorePE一致
            "v_thresh": v_thresh,
            "v_reset": 0.0,
            "v_rest": 0.0,
            "tau_mem": 20.0,
            "t_ref": 2,
            "base_addr": weight_addr,
            "node_id": i,
            "verbose": 2,
            "enable_weight_fetch": 1,
            "write_weights_on_init": 1,
            "memory_warmup_cycles": 500,
            "init_default_weight": 0.5,
            "max_outstanding_requests": 64,
            "max_cache_entries": 65536,
            "use_event_weight_fallback": 0,  # 阶段1：关闭事件权重回退，纯内存权重
            "merge_read_cacheline": 1,
            "merge_read_row": 1,
            # 新增：全网读取模式（行=post_local=0..15，列=pre_global=0..255）
            "weights_cols": TOTAL_NODES * NEURONS_PER_PE,
            "index_mode": "post_row_pre_col",
            "line_size_bytes": 64,
            "enable_detailed_map_log": 0,
            # 轻预热：开启少量验证读，仅用于把热点行读入缓存；不进行文件对比
            "verify_weights": 1,
            "verify_against_file": 0,
            "verify_file_template": os.path.join(weights_dir, "classification_weights_pe_{pe}.bin"),
            "weight_verify_samples": 2,
            "verify_epsilon": 1e-4,
            "verify_log_each_sample": 0,
            # 启用按权重驱动的NoC扇出
            "routing_mode": "weight_driven",
            "weights_template": os.path.join(weights_dir, "classification_weights_pe_{pe}.bin"),
            "total_nodes": TOTAL_NODES,
            "routing_epsilon": EPS,             # 阶段A：强过滤弱边，先保稳
            "routing_topk_per_pe":   0,           # 稳态：保持每PE目的数
            "routing_topk":   TOPK,                 # 稳态：进一步收紧全局目的数
            "route_exclude_self_pe": 0,        # 允许同PE路由
            "route_layers_mask": "I>H1,H1>H2,H2>O",  # 阶段2：只允许前馈层间方向
            "route_filter_warn": 1,             # 明显提醒：过滤已启用
            # NeuroMoE 门控模式开关：默认权重驱动；可切换到CSV门控驱动（含gating_pe_offline / GATING_COMPONENT）
            "mapping_mode": ("edges_csv" if (MODE in ("edges_csv","gating_pe_offline") or GATING_COMPONENT) else "off"),
            "mapping_edges_file": (CSV_PATH if (MODE in ("edges_csv","gating_pe_offline") or GATING_COMPONENT) else ""),
            "mapping_csv_has_header": 1,
            "mapping_csv_separator": ",",
            "mapping_assume_block_ids": 1,
            # 在线门控：默认仅输入层启用
            "gating_mode": ("event" if GATING_EVENT else "off"),
            "gating_scope": "inputs",
            "gating_ttl_cycles": 1000
        })
        
        # 为每个SnnPESubComponent配置其own memory子组件
        core_memory = core_subcomponent.setSubComponent("memory", "memHierarchy.standardInterface")
        
        # 创建每个核心的L1缓存
        core_l1_cache = sst.Component(f"pe_{i}_core{core_idx}_l1", "memHierarchy.Cache")
        core_l1_cache.addParams({
            "cache_frequency": "2GHz",
            "cache_size": "16KiB",
            "associativity": "8",
            "cache_line_size": "64",
            "access_latency_cycles": "2",
            "L1": "1",
            "coherence_protocol": "mesi",
            "debug": "0",
            "verbose": "0"
        })

        # 连接核心的StandardMem接口到L1缓存 (使用新的端口名称)
        core_mem_link = sst.Link(f"pe_{i}_core{core_idx}_mem")
        core_mem_link.connect(
            (core_memory, "lowlink", "1ns"),  # 使用 lowlink 替代 port
            (core_l1_cache, "highlink", "1ns")
        )

        # 连接核心的L1缓存到当前PE的内存总线（独立权重数据）
        core_l1_to_bus_link = sst.Link(f"pe_{i}_core{core_idx}_l1_to_pe_bus")
        core_l1_to_bus_link.connect(
            (core_l1_cache, "lowlink", "5ns"),
            (pe_memory_buses[i], f"highlink{core_idx}", "5ns")  # 每个核心使用不同的highlink
        )

    nodes.append(node)
    nics.append(nic)

    print(f"  PE{i} ({layer_name}): 阈值={v_thresh}, 权重地址=0x{weight_addr:x}")

print(f"✅ 创建{len(nodes)}个分层PE节点完成")

# === 创建SpikeSource组件（仅连接到输入层）===
spike_sources = []
for i, pe_id in enumerate(INPUT_LAYER):  # 只为输入层PE创建SpikeSource
    spike_source = sst.Component(f"spike_source_{pe_id}", "SnnDL.SpikeSource")
    spike_source.addParams({
        "verbose": 0,  # 精简SpikeSource日志
        "dataset_path": spike_data_files[i],
        "neurons_per_core": NEURONS_PER_CORE,
        "num_cores": NUM_CORES_PER_PE,
        "neurons_per_pe": NEURONS_PER_PE,
        "start_time_us": 2.0 + pe_id * 0.5,  # 错开启动时间
        "loop_dataset": 0,  # 禁用循环播放来调试PE0问题
        "source_id": pe_id
    })
    spike_sources.append((spike_source, pe_id))

print(f"✅ 创建{len(spike_sources)}个SpikeSource（仅连接输入层PE 0-3）")

# === 网络连接 ===
# NIC连接到路由器
for i in range(TOTAL_NODES):
    nic_router_link = sst.Link(f"nic_{i}_to_router_{i}")
    nic_router_link.connect(
        (nics[i], "network", "5ns"),
        (routers[i], "port4", "5ns")
    )

# 建立路由器间连接（4x4 mesh）
connection_count = 0
mesh_size = MESH_SIZE

# 水平连接 (East-West)
for y in range(mesh_size):
    for x in range(mesh_size - 1):
        node_id = y * mesh_size + x
        east_node_id = y * mesh_size + (x + 1)

        router_east_link = sst.Link(f"router_east_{node_id}_to_{east_node_id}")
        router_east_link.connect(
            (routers[node_id], "port0", "5ns"),
            (routers[east_node_id], "port1", "5ns")
        )
        connection_count += 1

# 垂直连接 (North-South)
for x in range(mesh_size):
    for y in range(mesh_size - 1):
        node_id = y * mesh_size + x
        south_node_id = (y + 1) * mesh_size + x

        router_south_link = sst.Link(f"router_south_{node_id}_to_{south_node_id}")
        router_south_link.connect(
            (routers[node_id], "port2", "5ns"),
            (routers[south_node_id], "port3", "5ns")
        )
        connection_count += 1

print(f"✅ 完成{len(nics)}个NIC连接和{connection_count}个路由器连接")

# 连接SpikeSource到输入层PE
for spike_source, pe_id in spike_sources:
    spike_link = sst.Link(f"spike_source_{pe_id}_to_pe_{pe_id}")
    spike_link.connect(
        (spike_source, "spike_output", "5ns"),
        (nodes[pe_id], "external_spike_input", "5ns")
    )

print(f"✅ 完成{len(spike_sources)}个SpikeSource到输入层连接")

# === 统计信息收集 ===
for i, node in enumerate(nodes):
    # 使用MultiCorePE中定义的统计名称
    node.enableStatistics([
        "total_spikes_processed",
        "external_spikes_sent",
        "external_spikes_received",
        "memory_requests",
        "total_neurons_fired"
    ])

for i, nic in enumerate(nics):
    # 明确启用NIC统计，确保CSV采集
    nic.enableStatistics([
        "packets_sent",
        "packets_received",
        "spikes_sent",
        "spikes_received",
        "batches_sent"
    ])

for i, router in enumerate(routers):
    router.enableStatistics([
        "router.packet_count",
        "router.network_load"
    ])

# === 在线门控：GatingPE经NoC注入 ===
if GATING_EVENT:
    gating = sst.Component("gating", "SnnDL.GatingPE")
    gating.addParams({
        "total_nodes": TOTAL_NODES_NIC,
        "rows_per_pe": NEURONS_PER_PE,
        "top_k": TOPK,
        "transitions": transitions_str,
        "edges_output_file": CSV_PATH,  # 仍生成CSV用于可视/对照
        "csv_header": 1,
        "selection": "round_robin",
        # NIC参数
        "node_id": TOTAL_NODES,  # 预留的第17个节点ID（0..15为PE）
        "link_bw": NETWORK_BANDWIDTH,
        "input_buf_size": BUFFER_SIZE,
        "output_buf_size": BUFFER_SIZE,
        "virtual_channels": 2 if VNSEP else 1,
        "vn_control": 1 if VNSEP else 0,
        # 发射参数
        "gate_targets": "0-3",
        "emit_period_ns": 1000,
        "emit_count": 0,
        "verbose": 0,
    })
    # 连接GatingPE到router_0的第二本地端口port5
    gp_link = sst.Link("gating_to_router0")
    gp_link.connect(
        (gating, "network", "5ns"),
        (routers[0], "port5", "5ns")
    )

# === 配置仿真 ===
sst.setProgramOption("timebase", "1ps")
sst.setProgramOption("stop-at", SIMULATION_TIME)

print(f"\n🎯 分层分类网络目标:")
print(f"📊 网络架构: 输入层(PE 0-3) -> 隐藏层1(PE 4-7) -> 隐藏层2(PE 8-11) -> 输出层(PE 12-15)")
print(f"🔥 输入模式: PE0(类A,{CLASS_A_FREQ}Hz), PE1(类B,{CLASS_B_FREQ}Hz), PE2(类C,{CLASS_C_FREQ}Hz), PE3(类D,{CLASS_D_FREQ}Hz)")
print(f"🌐 权重连接: 优化分层连接，权重强度平衡(4.0 -> 5.0 -> 8.0)")
print(f"🧠 神经元阈值: 全层低阈值(0.02-0.025)增强传播")
print(f"📈 期望结果: 4个输出层PE分别激活对应4个类别")

print(f"\n🚀 运行分层分类网络...")
print(f"📡 架构: 4个SpikeSource -> 输入层 -> 2个隐藏层 -> 输出层")
print(f"🎯 目标: 验证4x4分层网络的分类能力")
