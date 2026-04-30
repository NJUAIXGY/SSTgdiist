#!/usr/bin/env python3

"""
NoC 单步时延（四方案对比）脚本骨架

基于现有 sst_dram_si/test_mesh_4x4.py 的网格/网络搭建方式，提供：
- 参数化 Mesh + Merlin SimpleNetwork(hr_router + mesh)
- 四方案开关（baseline/slice/gas/sram）与映射到 SnnPESubComponent 参数
- 统计采集绑定到 CSV（便于后续 plot_noc_timestep.py 解析）

说明：本脚本首版聚焦“脚本化配置与统计落盘”，端到端 P99 时延将在下一迭代（在 SnnNIC/SnnPESubComponent 中补充时间戳采集）完善。
"""

import os
import sys
import shlex
import json as _json
import sst
import time


# ===== 统计输出配置（先于任何组件创建） =====
_DEFAULT_STATS_LVL = 7
sst.setStatisticLoadLevel(_DEFAULT_STATS_LVL)
sst.setStatisticOutput("sst.statOutputCSV")

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 大规模实验输出根目录（位于 sst_dram_si 下）
_RUN_BASE_DIR = os.path.join(_SCRIPT_DIR, "outputs_large")
os.makedirs(_RUN_BASE_DIR, exist_ok=True)
# 先占位，待解析完 SCENARIO/MESH/SIM_TIME 后再确定具体 run 目录与文件路径
_RUN_DIR = None
_ANALYSIS_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "analysis")
os.makedirs(_ANALYSIS_DIR, exist_ok=True)
_STATS_DIR = os.path.join(_SCRIPT_DIR, "stats")
os.makedirs(_STATS_DIR, exist_ok=True)
# Statistic 输出路径会在解析完参数后重设到 _RUN_DIR 中
_STATS_CSV = None

# 仅设置输出；为本次“必要统计”启用 SnnPESubComponent 的聚合统计（低开销）
sst.enableAllStatisticsForComponentType("SnnDL.SnnPESubComponent", {"type": "sst.AccumulatorStatistic"})


# ===== 默认参数（可被 local_run_config.json 和 CLI 覆盖） =====
# Prefer config next to this script
CFG_PATH = os.path.join(_SCRIPT_DIR, "local_run_config.json")

# Mesh/网络
MESH_SIZE = 4
NOC_LINK_BW = "40GiB/s"              # 链路带宽（可通过 --bw 覆盖）
NOC_FLIT_SIZE = "32B"                # flit 大小（可通过 --flit 覆盖）；统一按 32B/flit 口径
NOC_XBAR_BW = NOC_LINK_BW
NOC_IN_LAT = "10ns"                   # 路由器输入延迟
NOC_OUT_LAT = "10ns"                  # 路由器输出延迟
NOC_BUF_IN = "4KiB"
NOC_BUF_OUT = "4KiB"

# 运行时间
SIM_TIME = "100us"

# 方案：baseline/slice/gas/sram
SCENARIO = os.environ.get("NOC_SCENARIO", "baseline").strip().lower()

# MultiCorePE/核心规模
NUM_CORES_PER_PE = 4
NEURONS_PER_CORE = 4
NEURONS_PER_PE = NUM_CORES_PER_PE * NEURONS_PER_CORE

# L1/L2/总线（轻量，避免干扰 NoC 测试）
L1_SIZE_STR = "16KiB"
L1_ASSOC = 8
LINE_BYTES = 64
L2_SIZE_STR = "256KiB"

# SpikeSource：默认关闭（NoC 单步对比更偏合成流量）
ENABLE_SPIKE_SOURCE = False

# 方案映射默认参数
SCHEME1_SLICES = 8
SCHEME1_GATHER_CYCLES = 200
SCHEME1_GAP_CYCLES = 0
SCHEME1_SCATTER_CYCLES = 1

GAS_WINDOW_MODE = 1   # window_auto
APPLY_ACC_ENABLE = 1  # 打通 GAS 端到端统计


# ===== 读取 local_run_config.json 覆盖默认 =====
if os.path.exists(CFG_PATH):
    try:
        with open(CFG_PATH, 'r', encoding='utf-8') as f:
            cfg = _json.load(f)
        MESH_SIZE = int(cfg.get('mesh_size', MESH_SIZE)) if cfg.get('mesh_size') is not None else MESH_SIZE
        NUM_CORES_PER_PE = int(cfg.get('num_cores_per_pe', NUM_CORES_PER_PE)) if cfg.get('num_cores_per_pe') is not None else NUM_CORES_PER_PE
        NEURONS_PER_CORE = int(cfg.get('neurons_per_core', NEURONS_PER_CORE)) if cfg.get('neurons_per_core') is not None else NEURONS_PER_CORE
        NEURONS_PER_PE = NUM_CORES_PER_PE * NEURONS_PER_CORE
        SIM_TIME = str(cfg.get('sim_time', SIM_TIME))
        # 网络参数（若存在）
        NOC_LINK_BW = str(cfg.get('network_bandwidth', NOC_LINK_BW))
        # L2/Bus 覆盖
        L2_SIZE_STR = str(cfg.get('l2_size', L2_SIZE_STR))
        _BUS_FREQ = str(cfg.get('bus_frequency', ''))
        _L2_ASSOC = str(cfg.get('l2_assoc', ''))
        _L2_PREFETCHER = cfg.get('l2_prefetcher', '')
        _L2_PREFETCHER_REACH = str(cfg.get('l2_prefetcher_reach', ''))
        # NIC 批处理与CSV/直方图开关
        _NIC_ENABLE_BATCHING = int(cfg.get('enable_batching', 0)) != 0
        _NIC_BATCH_LOCAL = int(cfg.get('batch_size_local', 16))
        _NIC_BATCH_REMOTE = int(cfg.get('batch_size_remote', 64))
        _NIC_BATCH_WINDOW = str(cfg.get('batch_flush_window', '1000'))
        _NIC_ENABLE_LAT_HIST = int(cfg.get('enable_nic_latency_hist', 0)) != 0
        _NIC_ENABLE_SPIKE_CSV = cfg.get('enable_spike_csv', True)
        # Core 性能参数覆盖
        _CORE_OUTSTANDING = int(cfg.get('max_outstanding_requests', 128))
        _CORE_CACHE_ENTRIES = int(cfg.get('max_cache_entries', 8192))
        _CORE_USE_SOA = int(cfg.get('use_soa_neuron_state', 1)) != 0
        _CORE_USE_AOSOA = int(cfg.get('use_aosoa_neuron_state', 0)) != 0
        _CORE_AOSOA_ROWS = int(cfg.get('aosoa_block_rows', 16))
        # Profiling（默认关闭）
        _CORE_ENABLE_PROF = int(cfg.get('enable_profiler', 0)) != 0
        # Code-level memory optimization switches
        _CORE_CLOCK_WEIGHT_CACHE = int(cfg.get('use_clock_weight_cache', 0)) != 0
        _CORE_APPLY_DENSE_ACC = int(cfg.get('apply_dense_acc_enable', 0)) != 0
        # GatherBufferIF passthrough (optional, best-effort)
        _GB_SRAM_BYTES = cfg.get('gas_sram_bytes', None)
        _GB_MAX_INFL = cfg.get('gas_max_inflight_reads', None)
        _GB_GAP_K = cfg.get('gap_merge_k_bytes', None)
        _GB_BURST_MAX = cfg.get('burst_bytes_max', None)
        _GB_ROWWIN_ENABLE = cfg.get('row_window_enable', None)
        _GB_ROWWIN_BYTES = cfg.get('row_window_bytes', None)
        _GB_ROWWIN_TIMEOUT = cfg.get('row_window_timeout_ns', None)
        _GB_TAIL_WAIT = cfg.get('tail_wait_timeout_ns', None)
        _GB_WINDOW_AUTO = cfg.get('window_auto', None)
        _GB_WIN_CYC_G = cfg.get('window_cycles_gather', None)
        _GB_WIN_CYC_A = cfg.get('window_cycles_apply', None)
        _GB_WIN_CYC_S = cfg.get('window_cycles_scatter', None)
        # Test traffic overrides (optional)
        _TEST_PERIOD = cfg.get('test_period', None)
        _TEST_SPIKES_PER_BURST = cfg.get('test_spikes_per_burst', None)
        _TEST_MAX_SPIKES = cfg.get('test_max_spikes', None)
        # 方案1参数
        SCHEME1_SLICES = int(cfg.get('scheme1_slices', SCHEME1_SLICES))
        SCHEME1_GATHER_CYCLES = int(cfg.get('scheme1_gather_cycles', SCHEME1_GATHER_CYCLES))
        SCHEME1_GAP_CYCLES = int(cfg.get('scheme1_slice_gap_cycles', SCHEME1_GAP_CYCLES))
        SCHEME1_SCATTER_CYCLES = int(cfg.get('scheme1_scatter_cycles', SCHEME1_SCATTER_CYCLES))
        # GAS 端到端（若存在）
        APPLY_ACC_ENABLE = 1 if bool(cfg.get('apply_acc_enable', APPLY_ACC_ENABLE)) else 0
    except Exception as e:
        print(f"[local_run_config] 读取失败，使用默认：{e}")
else:
    # 默认值（未提供 local_run_config.json 时）
    _BUS_FREQ = ''
    _NIC_ENABLE_BATCHING = 1
    _NIC_BATCH_LOCAL = 16
    _NIC_BATCH_REMOTE = 64
    _NIC_BATCH_WINDOW = '500'
    _NIC_ENABLE_LAT_HIST = False
    _NIC_ENABLE_SPIKE_CSV = True
    _CORE_OUTSTANDING = 128
    _CORE_CACHE_ENTRIES = 8192
    _CORE_USE_SOA = True
    _CORE_USE_AOSOA = False
    _CORE_AOSOA_ROWS = 16
    _CORE_CLOCK_WEIGHT_CACHE = False
    _CORE_APPLY_DENSE_ACC = False
    _CORE_ENABLE_PROF = False
    _GB_SRAM_BYTES = None
    _GB_MAX_INFL = None
    _GB_GAP_K = None
    _GB_BURST_MAX = None
    _GB_ROWWIN_ENABLE = None
    _GB_ROWWIN_BYTES = None
    _GB_ROWWIN_TIMEOUT = None
    _GB_TAIL_WAIT = None
    _GB_WINDOW_AUTO = None
    _GB_WIN_CYC_G = None
    _GB_WIN_CYC_A = None
    _GB_WIN_CYC_S = None
    _TEST_PERIOD = None
    _TEST_SPIKES_PER_BURST = None
    _TEST_MAX_SPIKES = None


# ===== CLI 覆盖（便于批跑） =====
# 用法示例：
#   sst sst_dram_si/test_noc_timestep.py --scenario gas --mesh 4 --time 100us \
#       --bw 40GiB/s --in-lat 10ns --out-lat 10ns
argv = sys.argv[1:]
def _popopt(flag, hasval=True, default=None):
    if flag in argv:
        idx = argv.index(flag)
        if hasval:
            try:
                val = argv[idx+1]
                del argv[idx:idx+2]
                return val
            except Exception:
                del argv[idx]
                return default
        else:
            del argv[idx]
            return True
    return default

_sc = _popopt('--scenario')
if _sc:
    SCENARIO = _sc.strip().lower()
_ms = _popopt('--mesh')
if _ms: MESH_SIZE = int(_ms)
_tm = _popopt('--time')
if _tm: SIM_TIME = _tm
_bw = _popopt('--bw')
if _bw: NOC_LINK_BW = _bw
_fl = _popopt('--flit')
if _fl: NOC_FLIT_SIZE = _fl
_inlat = _popopt('--in-lat')
if _inlat: NOC_IN_LAT = _inlat
_outlat = _popopt('--out-lat')
if _outlat: NOC_OUT_LAT = _outlat
_fir = _popopt('--firing')
FIRING_RATE = float(_fir) if _fir else 0.0
MULTICAST_MODE = _popopt('--multicast') or 'replicate'
_partitioner = _popopt('--partitioner') or ''
_partition_out = _popopt('--output-partition') or os.path.join(_ANALYSIS_DIR, 'partition_info.txt')

# Replay mode (P1): reuse external driver to simulate NoC from CSV traces
REPLAY_MODE = bool(_popopt('--replay', hasval=False))
REPLAY_SPIKES = _popopt('--spikes-csv')
REPLAY_GRANULES = _popopt('--granules-csv')
REPLAY_STAGES = _popopt('--stages-csv')
REPLAY_OUT = _popopt('--replay-out') or os.path.join(_ANALYSIS_DIR, 'noc_trace_summary_from_sst.csv')

if REPLAY_MODE:
    # Default inputs if not provided
    if not REPLAY_SPIKES:
        # 若未指定，默认到大规模输出目录（按场景组织）；若目录不存在，回落到工程级 analysis
        _default_run_dir = os.path.join(_SCRIPT_DIR, 'outputs_large', f"{SCENARIO}_m{MESH_SIZE}_{SIM_TIME}")
        REPLAY_SPIKES = os.path.join(_default_run_dir, 'spikes.csv') if os.path.exists(_default_run_dir) else os.path.join(os.path.dirname(_SCRIPT_DIR), 'analysis', 'spikes.csv')
    if not REPLAY_GRANULES:
        REPLAY_GRANULES = os.path.join(os.path.dirname(_SCRIPT_DIR), 'analysis', 'granules.csv')
    if not REPLAY_STAGES:
        REPLAY_STAGES = os.path.join(os.path.dirname(_SCRIPT_DIR), 'stats', 'stage_events_db_100us.csv')
    driver = os.path.join(os.path.dirname(_SCRIPT_DIR), 'tools', 'noc_trace_driver.py')
    cmd = [
        'python3', driver,
        '--granules', REPLAY_GRANULES,
        '--spikes', REPLAY_SPIKES,
        '--stages', REPLAY_STAGES,
        '--bw', NOC_LINK_BW,
        '--size', str(MESH_SIZE),
        '--multicast', MULTICAST_MODE,
        '--out', REPLAY_OUT,
    ]
    print('[Replay] Run:', ' '.join(shlex.quote(x) for x in cmd))
    rc = os.system(' '.join(shlex.quote(x) for x in cmd))
    if rc != 0:
        print('[Replay] driver failed with rc=', rc)
    # Stop here; do not build SST graph for replay mode
    sys.exit(0)

TOTAL_NODES = MESH_SIZE * MESH_SIZE

# 解析完成后，确定本次 run 的输出目录与统计输出文件
_RUN_DIR = os.path.join(_RUN_BASE_DIR, f"{SCENARIO}_m{MESH_SIZE}_{SIM_TIME}")
os.makedirs(_RUN_DIR, exist_ok=True)
_STATS_CSV = os.path.join(_RUN_DIR, "noc_timestep_stats.csv")
sst.setStatisticOutputOptions({"filepath": _STATS_CSV, "separator": ","})

print(f"[D3] NoC 单步脚本 | mesh={MESH_SIZE}x{MESH_SIZE} nodes={TOTAL_NODES} scenario={SCENARIO}")
print(f"[D3] NoC: bw={NOC_LINK_BW} in_lat={NOC_IN_LAT} out_lat={NOC_OUT_LAT} flit={NOC_FLIT_SIZE} buf_in={NOC_BUF_IN} buf_out={NOC_BUF_OUT}")
if FIRING_RATE>0:
    print(f"[D3] traffic: firing={FIRING_RATE*100:.1f}% multicast={MULTICAST_MODE}")
print(f"[D3] Neurons: {NUM_CORES_PER_PE} cores/PE × {NEURONS_PER_CORE} neurons/core = {NEURONS_PER_PE} per-PE, total={TOTAL_NODES*NEURONS_PER_PE}")
print(f"[D3] Output RunDir: {_RUN_DIR}")
if _partitioner:
    sst.setProgramOption('partitioner', _partitioner)
    _partition_out = os.path.join(_RUN_DIR, 'partition_info.txt')
    sst.setProgramOption('output-partition', _partition_out)
    print(f"[D3] Partitioner: {_partitioner}, output: {_partition_out}")


# ===== 构建 Merlin mesh 网络 =====
routers = []
for i in range(TOTAL_NODES):
    r = sst.Component(f"router_{i}", "merlin.hr_router")
    r.addParams({
        "id": i,
        "num_ports": 5,
        "flit_size": NOC_FLIT_SIZE,
        "link_bw": NOC_LINK_BW,
        "xbar_bw": NOC_XBAR_BW,
        "input_latency": NOC_IN_LAT,
        "output_latency": NOC_OUT_LAT,
        "input_buf_size": NOC_BUF_IN,
        "output_buf_size": NOC_BUF_OUT,
        "num_vns": 1,
        "xbar_arb": "merlin.xbar_arb_lru",
        "debug": 0,
        "verbose": 0,
    })
    topo = r.setSubComponent("topology", "merlin.mesh")
    topo.addParams({
        "shape": f"{MESH_SIZE}x{MESH_SIZE}",
        "width": "1x1",
        "local_ports": "1",
    })
    routers.append(r)

# Mesh 连接：E-W / N-S
conn = 0
for y in range(MESH_SIZE):
    for x in range(MESH_SIZE - 1):
        a = y * MESH_SIZE + x
        b = y * MESH_SIZE + (x + 1)
        l = sst.Link(f"ew_{a}_{b}")
        l.connect((routers[a], "port0", "5ns"), (routers[b], "port1", "5ns"))
        conn += 1
for x in range(MESH_SIZE):
    for y in range(MESH_SIZE - 1):
        a = y * MESH_SIZE + x
        b = (y + 1) * MESH_SIZE + x
        l = sst.Link(f"ns_{a}_{b}")
        l.connect((routers[a], "port2", "5ns"), (routers[b], "port3", "5ns"))
        conn += 1
print(f"[D3] Router ready: {len(routers)} routers, {conn} links")


# ===== PE + NIC + 轻量内存层次 =====
nodes = []
nics = []
pe_buses = []
mem_ctls = []

for i in range(TOTAL_NODES):
    node = sst.Component(f"pe_{i}", "SnnDL.MultiCorePE")
    np = {
        "verbose": 0,
        "print_node_summary": 0,
        "num_cores": NUM_CORES_PER_PE,
        "neurons_per_core": NEURONS_PER_CORE,
        "total_neurons": TOTAL_NODES * (NUM_CORES_PER_PE * NEURONS_PER_CORE),
        "node_id": i,
        "global_neuron_base": i * (NUM_CORES_PER_PE * NEURONS_PER_CORE),
        # 关闭权重文件路径依赖，使用 init 默认值
        "enable_memory_weights": 0,
        "use_event_weight_fallback": 1,  # sram 方案需命中；baseline/gas/slice 不依赖权重
        "verify_weights": 0,
        # 合成测试流量（可控）
        "enable_test_traffic": 1 if FIRING_RATE>0 else 0,
        "test_target_node": (TOTAL_NODES - 1),
        # 近似：按 firing 控制周期（更高 firing → 更短周期），默认每burst=1，如配置提供则覆盖；最大脉冲可配置（0 表示不限制）
        "test_period": int(_TEST_PERIOD) if (_TEST_PERIOD is not None) else (max(1, int(1000/max(1e-6,FIRING_RATE*100.0))) if FIRING_RATE>0 else 1000),
        "test_spikes_per_burst": int(_TEST_SPIKES_PER_BURST) if (_TEST_SPIKES_PER_BURST is not None) else 1,
        "test_max_spikes": int(_TEST_MAX_SPIKES) if (_TEST_MAX_SPIKES is not None) else (int(FIRING_RATE * (NUM_CORES_PER_PE * NEURONS_PER_CORE)) if FIRING_RATE>0 else 0),
        # 窗口化统计（按需）
        "window_stats_enable": False,
        "window_us": 20,
        "window_csv": os.path.join(os.path.dirname(_SCRIPT_DIR), "stats", "windowed", "windows_20us.csv"),
    }
    if i == 0:
        np["primary_keepalive"] = 1
    node.addParams(np)

    # NIC（SimpleNetwork 包装）
    nic = node.setSubComponent("network_interface", "SnnDL.SnnNIC")
    nic.addParams({
        "node_id": str(i),
        "link_bw": NOC_LINK_BW,
        "input_buf_size": NOC_BUF_IN,
        "output_buf_size": NOC_BUF_OUT,
        "use_direct_link": "false",
        "port_name": "network",
        "verbose": 0,
        "total_nodes": TOTAL_NODES,
        # CSV 导出到本次 run 目录（可由配置关闭以避免I/O开销）
        "export_spike_csv": (os.path.join(_RUN_DIR, "spikes.csv") if _NIC_ENABLE_SPIKE_CSV else ""),
        # 批处理参数
        "enable_batching": 1 if _NIC_ENABLE_BATCHING else 0,
        "batch_size_local": _NIC_BATCH_LOCAL,
        "batch_size_remote": _NIC_BATCH_REMOTE,
        "batch_flush_window": _NIC_BATCH_WINDOW,
    })

    # 方案映射：传递到核心子组件
    for core_idx in range(NUM_CORES_PER_PE):
        core = node.setSubComponent(f"core{core_idx}", "SnnDL.SnnPESubComponent")
        # Per-core partition: each core owns exactly NEURONS_PER_CORE neurons.
        # Stage events CSV（GAS阶段事件：Begin/End Apply/Scatter），写到本次 run 目录
        stage_csv_path = os.path.join(_RUN_DIR, f"stage_events_db_{SIM_TIME}.csv")
        core_params = {
            "core_id": core_idx,
            "total_cores": NUM_CORES_PER_PE,
            "global_neuron_base": i * (NUM_CORES_PER_PE * NEURONS_PER_CORE) + core_idx * NEURONS_PER_CORE,
            "num_neurons": NEURONS_PER_CORE,
            "v_thresh": 0.03,
            "v_reset": 0.0,
            "v_rest": 0.0,
            "tau_mem": 20.0,
            "t_ref": 2,
            "base_addr": 0x0,
            "node_id": i,
            "verbose": 0,
            # 权重路径：统一采用回退；避免权重/数据依赖
            "enable_weight_fetch": 0,
            "write_weights_on_init": 0,
            "use_event_weight_fallback": 1,
            # 合并默认：cacheline 合并开，行合并关（baseline 下会覆盖为关）
            "merge_read_cacheline": 1,
            "merge_read_row": 0,
            # 性能参数
            "max_outstanding_requests": _CORE_OUTSTANDING,
            "max_cache_entries": _CORE_CACHE_ENTRIES,
            # 状态布局
            "use_soa_neuron_state": 1 if _CORE_USE_SOA else 0,
            "use_aosoa_neuron_state": 1 if _CORE_USE_AOSOA else 0,
            "aosoa_block_rows": _CORE_AOSOA_ROWS,
            # GAS/方案1：按场景覆盖
            "gas_enable": 0,
            "gas_window_mode": GAS_WINDOW_MODE,
            "apply_acc_enable": APPLY_ACC_ENABLE,
            "scheme1_enable": 0,
            "scheme1_slices": SCHEME1_SLICES,
            "scheme1_gather_cycles": SCHEME1_GATHER_CYCLES,
            "scheme1_slice_gap_cycles": SCHEME1_GAP_CYCLES,
            "scheme1_scatter_cycles": SCHEME1_SCATTER_CYCLES,
            # 直方图/端到端统计将由 CSV 收集
            "quiet_finish_logs": 1,
            "stage_events_csv": stage_csv_path,
            # Profiling（可选，默认关闭）；导出到本次 run 目录
            "enable_profiler": 1 if _CORE_ENABLE_PROF else 0,
            "profiler_csv_prefix": os.path.join(_RUN_DIR, "profile_core"),
            # Code-level mem opts
            "use_clock_weight_cache": 1 if _CORE_CLOCK_WEIGHT_CACHE else 0,
            "apply_dense_acc_enable": 1 if _CORE_APPLY_DENSE_ACC else 0,
        }

        if SCENARIO == "baseline":
            core_params.update({
                "gas_enable": 0,
                "merge_read_cacheline": 0,
                "merge_read_row": 0,
                # 非 GAS 场景禁用 apply 累加器路径
                "apply_acc_enable": 0,
            })
        elif SCENARIO == "slice":
            core_params.update({
                "scheme1_enable": 1,
                "gas_enable": 0,
                "apply_acc_enable": 0,
            })
        elif SCENARIO == "gas":
            core_params.update({
                "gas_enable": 1,
                "gas_window_mode": 1,
                # GAS 下可适度开启 cacheline 合并（k/Lmax 由后续工具统一控制）
                "merge_read_cacheline": 1,
                "merge_read_row": 0,
            })
        elif SCENARIO == "sram":
            core_params.update({
                # 纯 SRAM 命中：不走下行读
                "enable_weight_fetch": 0,
                "use_event_weight_fallback": 1,
                "gas_enable": 0,
                "merge_read_cacheline": 0,
                "merge_read_row": 0,
                "apply_acc_enable": 0,
            })
        else:
            print(f"[D3] 未知场景 {SCENARIO}，按 baseline 处理")
            core_params.update({
                "gas_enable": 0,
                "merge_read_cacheline": 0,
                "merge_read_row": 0,
            })

        core.addParams(core_params)
        # Optional: pass GatherBufferIF-related params best-effort to core (if core forwards internally)
        gb_passthrough = {}
        if _GB_SRAM_BYTES is not None: gb_passthrough["sram_bytes"] = str(_GB_SRAM_BYTES)
        if _GB_MAX_INFL is not None: gb_passthrough["max_inflight_reads"] = str(_GB_MAX_INFL)
        if _GB_GAP_K is not None: gb_passthrough["gap_merge_k_bytes"] = str(_GB_GAP_K)
        if _GB_BURST_MAX is not None: gb_passthrough["burst_bytes_max"] = str(_GB_BURST_MAX)
        if _GB_ROWWIN_ENABLE is not None: gb_passthrough["row_window_enable"] = str(int(bool(_GB_ROWWIN_ENABLE)))
        if _GB_ROWWIN_BYTES is not None: gb_passthrough["row_window_bytes"] = str(_GB_ROWWIN_BYTES)
        if _GB_ROWWIN_TIMEOUT is not None: gb_passthrough["row_window_timeout_ns"] = str(_GB_ROWWIN_TIMEOUT)
        if _GB_TAIL_WAIT is not None: gb_passthrough["tail_wait_timeout_ns"] = str(_GB_TAIL_WAIT)
        if _GB_WINDOW_AUTO is not None: gb_passthrough["window_auto"] = str(int(bool(_GB_WINDOW_AUTO)))
        if _GB_WIN_CYC_G is not None: gb_passthrough["window_cycles_gather"] = str(_GB_WIN_CYC_G)
        if _GB_WIN_CYC_A is not None: gb_passthrough["window_cycles_apply"] = str(_GB_WIN_CYC_A)
        if _GB_WIN_CYC_S is not None: gb_passthrough["window_cycles_scatter"] = str(_GB_WIN_CYC_S)
        if gb_passthrough:
            try:
                core.addParams(gb_passthrough)
            except Exception:
                pass
        # 启用少量核心级统计（仅GAS superstep周期），避免全量高开销
        # superstep周期统计改为使用 stage_events_csv + 离线脚本聚合，避免子组件统计注册时机限制

        # 轻量 L1：避免干扰 NoC；仍然保证 StandardMem 接口贯通
        memif = core.setSubComponent("memory", "memHierarchy.standardInterface")
        l1 = sst.Component(f"pe_{i}_c{core_idx}_l1", "memHierarchy.Cache")
        l1.addParams({
            "cache_frequency": "2GHz",
            "cache_size": L1_SIZE_STR,
            "associativity": str(L1_ASSOC),
            "cache_line_size": str(LINE_BYTES),
            "access_latency_cycles": "2",
            "L1": "1",
            "coherence_protocol": "none",
            "debug": "0",
            "verbose": "0",
        })
        sst.Link(f"pe_{i}_c{core_idx}_mem").connect((memif, "lowlink", "1ns"), (l1, "highlink", "1ns"))

        # L1 -> Bus（按 core_idx 绑定高位端口）
        # Bus 在后续第一个核心时创建
        if core_idx == 0:
            bus = sst.Component(f"pe_{i}_bus", "memHierarchy.Bus")
            bus.addParams({"bus_frequency": (_BUS_FREQ if _BUS_FREQ else "2GHz"), "debug": "0", "verbose": "0"})
            pe_buses.append(bus)
            # L2 + MemController（最小化，减少 DRAM 干扰）
            l2 = sst.Component(f"pe_{i}_l2", "memHierarchy.Cache")
            l2_params = {
                "cache_frequency": "1.5GHz",
                "cache_size": L2_SIZE_STR,
                "associativity": (str(_L2_ASSOC) if _L2_ASSOC else "4"),
                "cache_line_size": str(LINE_BYTES),
                "access_latency_cycles": "8",
                "L1": "0",
                "coherence_protocol": "mesi",
                "cache_type": "noninclusive",
                "debug": "0",
                "verbose": "0",
            }
            # 轻量预取器（可选）
            if _L2_PREFETCHER:
                l2_params["prefetcher"] = _L2_PREFETCHER
                if _L2_PREFETCHER_REACH:
                    l2_params["prefetcher.reach"] = _L2_PREFETCHER_REACH
            l2.addParams(l2_params)
            mc = sst.Component(f"pe_{i}_mc", "memHierarchy.MemController")
            mc.addParams({
                "clock": "1GHz",
                "backing": "malloc",
                "addr_range_start": "0",
                "addr_range_end": str(64*1024*1024 - 1),
            })
            be = mc.setSubComponent("backend", "memHierarchy.simpleMem")
            be.addParams({"access_time": "80ns", "mem_size": "64MiB"})

            sst.Link(f"pe_{i}_bus_l2").connect((bus, "lowlink0", "5ns"), (l2, "highlink", "5ns"))
            sst.Link(f"pe_{i}_l2_mc").connect((l2, "lowlink", "5ns"), (mc, "highlink", "5ns"))
            mem_ctls.append(mc)
        # L1 -> Bus per-core 口
        sst.Link(f"pe_{i}_c{core_idx}_l1_bus").connect((l1, "lowlink", "5ns"), (pe_buses[i], f"highlink{core_idx}", "5ns"))

    # NIC ↔ Router(local)
    sst.Link(f"nic_{i}_rtr").connect((nics[i] if i < len(nics) else nic, "network", "5ns"), (routers[i], "port4", "5ns"))
    nodes.append(node)
    nics.append(nic)


# ===== 统计项（仅选择性启用） =====
# 采样少量路由器以降低统计开销
sample_router_ids = []
if TOTAL_NODES > 0:
    sample_router_ids.append(0)
if MESH_SIZE > 1:
    mid = (MESH_SIZE // 2)
    cid = min(TOTAL_NODES - 1, mid * MESH_SIZE + min(mid, MESH_SIZE - 1))
    if cid not in sample_router_ids:
        sample_router_ids.append(cid)
if TOTAL_NODES > 1:
    if (TOTAL_NODES - 1) not in sample_router_ids:
        sample_router_ids.append(TOTAL_NODES - 1)
for rid in sample_router_ids:
    r = routers[rid]
    r.enableStatistics([
        "router.packet_count",
        "router.network_load",
    ])

for i, n in enumerate(nodes):
    n.enableStatistics([
        "external_spikes_sent",
        "external_spikes_received",
        "inter_core_messages",
        "memory_requests",
        "total_spikes_processed",
        "total_neurons_fired",
    ])

for nic in nics:
    # 计数类统计
    nic.enableStatistics([
        "spikes_sent",
        "spikes_received",
        "packets_sent",
        "packets_received",
        "batches_sent",
        "inter_rank_batches_sent",
    ])
    # 可选：高开销直方图，默认关闭
    if _NIC_ENABLE_LAT_HIST:
        try:
            nic.enableStatistics([
                "msg_latency_ns",
            ], {
                "type": "sst.HistogramStatistic",
                "minvalue": 0,
                "binwidth": 50,
                "numbins": 200,
                "dumpbinsonoutput": 1,
                "includeoutofbounds": 1,
            })
        except Exception:
            pass


# ===== 仿真选项 =====
sst.setProgramOption("timebase", "1ps")
sst.setProgramOption("stop-at", SIM_TIME)
print(f"[D3] run stop-at = {SIM_TIME}")
