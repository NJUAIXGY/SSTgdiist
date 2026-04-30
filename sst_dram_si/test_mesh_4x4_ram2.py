#!/usr/bin/env python3

import sst
import os
import struct
import json as _json
from string import Formatter

# === 4x4分层网络分类任务配置 ===

GLOBAL_BCSR_AVAILABLE = False

# === 提前配置统计输出（必须在创建任何组件之前）===
_DEFAULT_STATS_LVL = 7
sst.setStatisticLoadLevel(_DEFAULT_STATS_LVL)
sst.setStatisticOutput("sst.statOutputCSV")
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ANALYSIS_DIR = os.path.join(os.path.dirname(_SCRIPT_DIR), "analysis")
try:
    os.makedirs(_ANALYSIS_DIR, exist_ok=True)
except Exception:
    pass

_RUN_DIR_ENV = os.environ.get("MESH_RUN_DIR")
if _RUN_DIR_ENV:
    _RUN_OUTPUT_DIR = os.path.abspath(_RUN_DIR_ENV)
else:
    _RUN_OUTPUT_DIR = os.path.join(_ANALYSIS_DIR, "mesh_latest")
os.makedirs(_RUN_OUTPUT_DIR, exist_ok=True)
print(f"[mesh] run output dir: {_RUN_OUTPUT_DIR}")

_STATS_CSV = os.path.join(_RUN_OUTPUT_DIR, "mesh_stats.csv")
sst.setStatisticOutputOptions({
    "filepath": _STATS_CSV,
    "separator": ","
})

_GRANULES_MESH_CSV = os.path.join(_RUN_OUTPUT_DIR, "granules.csv")
_WINDOW_METRICS_MESH_CSV = os.path.join(_RUN_OUTPUT_DIR, "window_metrics.csv")
_SPIKES_MESH_CSV = os.path.join(_RUN_OUTPUT_DIR, "spikes_mesh.csv")

_GAS_GAP_K_BYTES = 2048
_GAS_LMAX_BYTES = 65536
_GAS_MAX_INFLIGHT = 128
_GAS_ROW_WINDOW_BYTES = 0
_GAS_ROW_WINDOW_TIMEOUT_NS = 0
_GAS_WINDOW_CYCLES = {
    "gather": 200,
    "apply": 40,
    "scatter": 40,
}
# 允许通过环境变量覆盖 GAS 窗口周期，格式：gather,apply,scatter 例如 "50,20,20"
_GAS_ENV = os.environ.get("MESH_GAS_CYCLES", "").strip()
if _GAS_ENV:
    try:
        g, a, s = [int(x) for x in _GAS_ENV.split(",")]
        if g > 0 and a >= 0 and s >= 0:
            _GAS_WINDOW_CYCLES["gather"] = g
            _GAS_WINDOW_CYCLES["apply"] = a
            _GAS_WINDOW_CYCLES["scatter"] = s
            print(f"[mesh] override GAS window cycles: gather={g} apply={a} scatter={s}")
    except Exception as _e:
        print(f"[mesh] ignore invalid MESH_GAS_CYCLES={_GAS_ENV}: {_e}")
sst.enableAllStatisticsForComponentType("SnnDL.MultiCorePE", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForComponentType("SnnDL.SpikeSource", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForComponentType("merlin.hr_router", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForComponentType("SnnDL.SnnPESubComponent", {"type":"sst.AccumulatorStatistic"})
# 启用内存层次关键统计，便于观察L1/L2与DRAM行为
sst.enableAllStatisticsForComponentType("memHierarchy.Cache", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForComponentType("memHierarchy.MemController", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForComponentType("SnnDL.SnnNIC", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForAllComponents({"type":"sst.AccumulatorStatistic"})

# 允许通过环境变量改用“事件权重回退”模式（不依赖权重文件）
EVENT_FALLBACK = os.environ.get("MESH_WEIGHT_MODE", "mem").strip().lower() in ("event", "event_fallback", "fallback")

# === 本地运行配置（可选）：同目录下 local_run_config.json 覆盖默认开关 ===
# 支持键：
#  - use_single_bus: bool（旧脚本始终单总线，仅用于一致的调试输出）
#  - debug_conn: bool（打印每个PE的总线连线方案）
#  - debug_bus/debug_mem: bool（本脚本不直接用到，预留一致性）
#  - use_soa: bool（控制 SnnPESubComponent 的 use_soa_neuron_state）
#  - verify_routing: bool（权重驱动路由构建期验证开关）
#  - stats_verbose: int（覆盖统计级别）
#  - sim_time: str（覆盖仿真结束时间）

SINGLE_BUS_MODE = True
DEBUG_CONN = False
USE_SOA_STATE = 0
USE_AOSOA_STATE = 0
AOSOA_BLOCK_ROWS = 16
CORE_MEMORY_WARMUP_CYCLES = 200
CORE_LOADER_BARRIER_CYCLES = 0  # 取消核心侧屏障，让Gather期即可消费脉冲并记录边
VERIFY_ROUTING = 0
# 静默与导出控制（可被 local_run_config.json 覆盖）
ENABLE_NODE_SUMMARY = False
ENABLE_SPIKE_SOURCE_FLAG = False
ENABLE_TEST_TRAFFIC = False  # 默认关闭NoC测试流量，避免与随机发放/SpikeSource冲突
EXPORT_SPIKE_CSV = False
DISABLE_NETWORK = False  # 诊断：允许完全禁用 NIC/Router
# recordEdge 门控（默认放宽 Apply/Idle 以便严格 GAS 调试）
RECORD_EDGE_APPLY_ENABLE = 1
RECORD_EDGE_IDLE_ENABLE = 1
RECORD_EDGE_SCATTER_ENABLE = 1
# step级随机激活（Strict GAS）默认配置
STEP_RANDOM_ACT_ENABLE = 1
STEP_ACTIVATION_FRACTION = 2e-4
STEP_ACTIVATION_FANOUT = 256
STEP_ACTIVATION_SEED = 271828
STEP_ACTIVATION_EVENT_WEIGHT = 0.0
STEP_ACTIVATION_USE_BCSR_ROUTES = 1  # 如无BCSR可用会在后续降级
STEP_RESET_MEM_EACH_STEP = 0
STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE = ""
STEP_ACTIVATION_BCSR_WEIGHT_EPS = 0.0
STEP_ACTIVATION_BCSR_ROWPTR_OFFSET = None
STEP_ACTIVATION_BCSR_COLIDX_OFFSET = None
STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET = None
STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET = None
STEP_ACTIVATION_BCSR_BR = None
STEP_ACTIVATION_BCSR_BC = None
STEP_ACTIVATION_BCSR_IDX_BYTES = None
STEP_ACTIVATION_BCSR_VAL_BYTES = None
# 突触格式/BCSR自动探测（默认Dense，关闭自动）
SYNAPSE_FORMAT_ENV = ""   # 可选："dense" | "bcsr"
FORCE_DENSE = False        # 为true时强制Dense
AUTO_BCSR_DETECT = False   # 为true时自动读取 bcsr/meta.json 以启用BCSR
ROUT_EPS = 0.6
ROUT_TOPK_PER_PE = 2
ROUT_TOPK = 12

# 新增（可选）：验证读与Loader计时写的本地开关（默认关闭，需在local_run_config.json中开启）
VERIFY_READS_ENABLE = 0
VERIFY_CLUSTER_ENABLE = 0
# 恢复 untimed 预装载（适合10us快测）；读前仍使用 loader_done gate
LOADER_TIMED_SEED_ENABLE = 0
LOADER_TIMED_SEED_ALLOW_CACHE = 0

# 先定义网络与缓存/行大小默认参数，供配置读取与打印使用
NETWORK_BANDWIDTH = "40GiB/s"
BUFFER_SIZE = "8KiB"
L1_SIZE_STR = "16KiB"
L1_ASSOC = 8
L1_LINE_BYTES_STR = "64"
SUBCOMP_LINE_BYTES = 64   # 传递给 SnnPESubComponent 的 line_size_bytes
LOADER_CHUNK_BYTES = 64   # WeightLoader 写入块大小（降低并发）
L2_SIZE_STR = "128KiB"    # 每PE默认L2容量

_CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_run_config.json")
# Ramulator2 配置文件路径（ram2 场景：此处使用 DDR4 open-row 模型实现稳定 DRAM 后端）
_DDR4_CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs", "ramulator2_ddr4_openrow.cfg")
if os.path.exists(_CFG_PATH):
    try:
        with open(_CFG_PATH, 'r', encoding='utf-8') as _f:
            _cfg = _json.load(_f)
        SINGLE_BUS_MODE = bool(_cfg.get('use_single_bus', SINGLE_BUS_MODE))
        DEBUG_CONN = bool(_cfg.get('debug_conn', DEBUG_CONN))
        USE_SOA_STATE = 1 if bool(_cfg.get('use_soa', USE_SOA_STATE)) else 0
        VERIFY_ROUTING = 1 if bool(_cfg.get('verify_routing', VERIFY_ROUTING)) else 0
        # AoSoA
        _ua = _cfg.get('use_aosoa')
        if _ua is not None:
            USE_AOSOA_STATE = 1 if bool(_ua) else 0
        _abr = _cfg.get('aosoa_block_rows')
        if _abr is not None:
            try:
                AOSOA_BLOCK_ROWS = int(_abr)
            except Exception:
                pass
        _syn = _cfg.get('synapse_format')
        if isinstance(_syn, str) and _syn.strip():
            SYNAPSE_FORMAT_ENV = _syn.strip().lower()
        _fd = _cfg.get('force_dense')
        if _fd is not None:
            FORCE_DENSE = bool(_fd)
        _auto = _cfg.get('bcsr_auto_detect')
        if _auto is not None:
            AUTO_BCSR_DETECT = bool(_auto)
        _eps = _cfg.get('routing_epsilon')
        if _eps is not None:
            try:
                ROUT_EPS = float(_eps)
            except Exception:
                pass
        _tkpp = _cfg.get('routing_topk_per_pe')
        if _tkpp is not None:
            try:
                ROUT_TOPK_PER_PE = int(_tkpp)
            except Exception:
                pass
        _tk = _cfg.get('routing_topk')
        if _tk is not None:
            try:
                ROUT_TOPK = int(_tk)
            except Exception:
                pass
        _sv = _cfg.get('stats_verbose')
        if _sv is not None:
            try:
                sst.setStatisticLoadLevel(int(_sv))
            except Exception:
                sst.setStatisticLoadLevel(_DEFAULT_STATS_LVL)
        # 膜时间常数（可配置，默认20.0）
        _tau = _cfg.get('tau_mem')
        CORE_TAU_MEM = 20.0
        if _tau is not None:
            try:
                CORE_TAU_MEM = float(_tau)
            except Exception:
                CORE_TAU_MEM = 20.0
        _ens = _cfg.get('enable_node_summary')
        if _ens is not None:
            ENABLE_NODE_SUMMARY = bool(_ens)
        _ess = _cfg.get('enable_spike_source')
        if _ess is not None:
            ENABLE_SPIKE_SOURCE_FLAG = bool(_ess)
        _ett = _cfg.get('enable_test_traffic')
        if _ett is not None:
            ENABLE_TEST_TRAFFIC = bool(_ett)
        _dn = _cfg.get('disable_network')
        if _dn is not None:
            DISABLE_NETWORK = bool(_dn)
        _exps = _cfg.get('export_spike_csv')
        if _exps is not None:
            EXPORT_SPIKE_CSV = bool(_exps)
        _rea = _cfg.get('record_edge_apply_enable')
        if _rea is not None:
            RECORD_EDGE_APPLY_ENABLE = 1 if bool(_rea) else 0
        _rei = _cfg.get('record_edge_idle_enable')
        if _rei is not None:
            RECORD_EDGE_IDLE_ENABLE = 1 if bool(_rei) else 0
        _res = _cfg.get('record_edge_scatter_enable')
        if _res is not None:
            RECORD_EDGE_SCATTER_ENABLE = 1 if bool(_res) else 0
        _sra = _cfg.get('step_random_activation_enable')
        if _sra is not None:
            STEP_RANDOM_ACT_ENABLE = 1 if bool(_sra) else 0
        _saf = _cfg.get('step_activation_fraction')
        if _saf is not None:
            try:
                STEP_ACTIVATION_FRACTION = float(_saf)
            except Exception:
                pass
        _sfan = _cfg.get('step_activation_fanout')
        if _sfan is not None:
            try:
                STEP_ACTIVATION_FANOUT = int(_sfan)
            except Exception:
                pass
        _sseed = _cfg.get('step_activation_seed')
        if _sseed is not None:
            try:
                STEP_ACTIVATION_SEED = int(_sseed)
            except Exception:
                pass
        _sev = _cfg.get('step_activation_event_weight')
        if _sev is not None:
            try:
                STEP_ACTIVATION_EVENT_WEIGHT = float(_sev)
            except Exception:
                pass
        _suse = _cfg.get('step_activation_use_bcsr_routes')
        if _suse is not None:
            STEP_ACTIVATION_USE_BCSR_ROUTES = 1 if bool(_suse) else 0
        _sreset = _cfg.get('step_reset_mem_each_step')
        if _sreset is not None:
            STEP_RESET_MEM_EACH_STEP = 1 if bool(_sreset) else 0
        _sbcsr_eps = _cfg.get('step_activation_bcsr_weight_epsilon')
        if _sbcsr_eps is not None:
            try:
                STEP_ACTIVATION_BCSR_WEIGHT_EPS = float(_sbcsr_eps)
            except Exception:
                pass
        _tmpl = _cfg.get('step_activation_bcsr_template')
        if isinstance(_tmpl, str) and _tmpl.strip():
            STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE = _tmpl.strip()
            if not os.path.isabs(STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE):
                STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE = os.path.join(_SCRIPT_DIR, STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE)
        # 冲突检测：SpikeSource vs Step Random Activation vs Test Traffic
        _allow_hybrid = bool(_cfg.get('allow_injection_hybrid', False))
        if STEP_RANDOM_ACT_ENABLE and ENABLE_SPIKE_SOURCE_FLAG and not _allow_hybrid:
            print("⚠️ 检测到随机发放(step_random_activation)与SpikeSource同时启用，默认优先随机发放，禁用SpikeSource（可通过 allow_injection_hybrid 开启共存）")
            ENABLE_SPIKE_SOURCE_FLAG = False
        if STEP_RANDOM_ACT_ENABLE and ENABLE_TEST_TRAFFIC and not _allow_hybrid:
            print("⚠️ 检测到随机发放(step_random_activation)与NoC测试流量同时启用，默认禁用测试流量")
            ENABLE_TEST_TRAFFIC = False
        def _maybe_int(val, current):
            if val is None:
                return current
            try:
                return int(val)
            except Exception:
                return current
        STEP_ACTIVATION_BCSR_ROWPTR_OFFSET = _maybe_int(_cfg.get('step_activation_bcsr_rowptr_offset'), STEP_ACTIVATION_BCSR_ROWPTR_OFFSET)
        STEP_ACTIVATION_BCSR_COLIDX_OFFSET = _maybe_int(_cfg.get('step_activation_bcsr_colidx_offset'), STEP_ACTIVATION_BCSR_COLIDX_OFFSET)
        STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET = _maybe_int(_cfg.get('step_activation_bcsr_blockdata_offset'), STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET)
        STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET = _maybe_int(_cfg.get('step_activation_bcsr_blockids_offset'), STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET)
        STEP_ACTIVATION_BCSR_BR = _maybe_int(_cfg.get('step_activation_bcsr_br'), STEP_ACTIVATION_BCSR_BR)
        STEP_ACTIVATION_BCSR_BC = _maybe_int(_cfg.get('step_activation_bcsr_bc'), STEP_ACTIVATION_BCSR_BC)
        STEP_ACTIVATION_BCSR_IDX_BYTES = _maybe_int(_cfg.get('step_activation_bcsr_idx_bytes'), STEP_ACTIVATION_BCSR_IDX_BYTES)
        STEP_ACTIVATION_BCSR_VAL_BYTES = _maybe_int(_cfg.get('step_activation_bcsr_val_bytes'), STEP_ACTIVATION_BCSR_VAL_BYTES)
        # 组件 verbose 映射（若未提供则与统计级别保持一致）
        _core_v = _cfg.get('core_verbose')
        _node_v = _cfg.get('node_verbose')
        CORE_VERBOSE = int(_core_v) if _core_v is not None else (int(_sv) if _sv is not None else 0)
        NODE_VERBOSE = int(_node_v) if _node_v is not None else (int(_sv) if _sv is not None else 0)
        # 路由模式
        ROUTING_MODE = str(_cfg.get('routing_mode', 'weight_driven')).strip().lower()
        if ROUTING_MODE not in ('fixed','weight_driven','hierarchical'):
            ROUTING_MODE = 'weight_driven'
        _st = _cfg.get('sim_time')
        if isinstance(_st, str) and _st.strip():
            SIMULATION_TIME = _st.strip()
        # 缓存与行大小
        _l1sz = _cfg.get('l1_size')
        if isinstance(_l1sz, str) and _l1sz.strip():
            L1_SIZE_STR = _l1sz.strip()
        _l1a = _cfg.get('l1_assoc')
        if _l1a is not None:
            try:
                L1_ASSOC = int(_l1a)
            except Exception:
                pass
        _lsb = _cfg.get('line_size_bytes')
        if _lsb is not None:
            try:
                SUBCOMP_LINE_BYTES = int(_lsb)
                L1_LINE_BYTES_STR = str(int(_lsb))
            except Exception:
                pass
        _lchunk = _cfg.get('loader_chunk_bytes')
        if _lchunk is not None:
            try:
                LOADER_CHUNK_BYTES = int(_lchunk)
            except Exception:
                pass
        _l2sz = _cfg.get('l2_size')
        if isinstance(_l2sz, str) and _l2sz.strip():
            L2_SIZE_STR = _l2sz.strip()
        # 网络与网格/规模参数（可选）
        _nbw = _cfg.get('network_bandwidth')
        if isinstance(_nbw, str) and _nbw.strip():
            NETWORK_BANDWIDTH = _nbw.strip()
        _bufsz = _cfg.get('buffer_size')
        if isinstance(_bufsz, str) and _bufsz.strip():
            BUFFER_SIZE = _bufsz.strip()
        _mesh = _cfg.get('mesh_size')
        if _mesh is not None:
            try:
                MESH_SIZE = int(_mesh)
            except Exception:
                pass
        _ncores = _cfg.get('num_cores_per_pe')
        if _ncores is not None:
            try:
                NUM_CORES_PER_PE = int(_ncores)
            except Exception:
                pass
        _neurpc = _cfg.get('neurons_per_core')
        if _neurpc is not None:
            try:
                NEURONS_PER_CORE = int(_neurpc)
            except Exception:
                pass
        _thr = _cfg.get('thresholds')
        THRESHOLDS = None
        if isinstance(_thr, dict):
            try:
                THRESHOLDS = {
                    'input': float(_thr.get('input', 0.02)),
                    'hidden1': float(_thr.get('hidden1', 0.03)),
                    'hidden2': float(_thr.get('hidden2', 0.03)),
                    'output': float(_thr.get('output', 0.035)),
                }
            except Exception:
                THRESHOLDS = None
        print(f"[local_run_config] 载入: single_bus={SINGLE_BUS_MODE}, use_soa={USE_SOA_STATE}, use_aosoa={USE_AOSOA_STATE}, aosoa_block_rows={AOSOA_BLOCK_ROWS}, synapse_format={SYNAPSE_FORMAT_ENV or 'default'}, force_dense={FORCE_DENSE}, bcsr_auto={AUTO_BCSR_DETECT}, routing_mode={ROUTING_MODE}, verify_routing={VERIFY_ROUTING}, eps={ROUT_EPS}, topk_pe={ROUT_TOPK_PER_PE}, topk={ROUT_TOPK}, stats={_sv if _sv is not None else _DEFAULT_STATS_LVL}, core_verbose={CORE_VERBOSE}, node_verbose={NODE_VERBOSE}, sim_time={SIMULATION_TIME}")
        print(f"[local_run_config] cache: l1_size={L1_SIZE_STR}, l1_assoc={L1_ASSOC}, line_size_bytes={SUBCOMP_LINE_BYTES}, loader_chunk_bytes={LOADER_CHUNK_BYTES}, l2_size={L2_SIZE_STR}")
        # 自定义：验证读与Loader计时写
        _vre = _cfg.get('verify_reads_enable')
        if _vre is not None:
            VERIFY_READS_ENABLE = 1 if bool(_vre) else 0
        _vcl = _cfg.get('verify_cluster_enable')
        if _vcl is not None:
            VERIFY_CLUSTER_ENABLE = 1 if bool(_vcl) else 0
        _lts = _cfg.get('loader_timed_seed_enable')
        if _lts is not None:
            LOADER_TIMED_SEED_ENABLE = 1 if bool(_lts) else 0
        _ltsc = _cfg.get('loader_timed_seed_allow_cache')
        if _ltsc is not None:
            LOADER_TIMED_SEED_ALLOW_CACHE = 1 if bool(_ltsc) else 0
        _wvs = _cfg.get('weight_verify_samples')
        if _wvs is not None:
            try:
                WEIGHT_VERIFY_SAMPLES_OVERRIDE = int(_wvs)
            except Exception:
                WEIGHT_VERIFY_SAMPLES_OVERRIDE = None
        else:
            WEIGHT_VERIFY_SAMPLES_OVERRIDE = None
    except Exception as _e:
        print(f"[local_run_config] 读取失败: {_e}")
else:
    CORE_VERBOSE = globals().get('CORE_VERBOSE', 2)
    NODE_VERBOSE = globals().get('NODE_VERBOSE', 0)
    ROUTING_MODE = globals().get('ROUTING_MODE', 'weight_driven')

if 'ROUTING_MODE' not in globals():
    ROUTING_MODE = 'weight_driven'

# === 网络架构配置（可被配置文件覆盖）===
MESH_SIZE = globals().get('MESH_SIZE', 4)
NUM_CORES_PER_PE = globals().get('NUM_CORES_PER_PE', 4)
NEURONS_PER_CORE = globals().get('NEURONS_PER_CORE', 4)
NEURONS_PER_PE = NUM_CORES_PER_PE * NEURONS_PER_CORE  # 每个PE的神经元数：16
TOTAL_NODES = MESH_SIZE * MESH_SIZE  # 16个节点
# 可选：限制构建的节点数量（用于最小化复现/调试）
_NODE_LIMIT_ENV = os.environ.get("MESH_NODE_LIMIT", "").strip()
try:
    NODE_LIMIT = int(_NODE_LIMIT_ENV) if _NODE_LIMIT_ENV else TOTAL_NODES
except Exception:
    NODE_LIMIT = TOTAL_NODES
NODE_LIMIT = max(1, min(NODE_LIMIT, TOTAL_NODES))
weights_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weights")


def _format_template_with_pe(template: str, pe_id: int) -> str:
    """替换模板中的 {pe}/{pe_id} 等字段，保留 {core...} 交由MultiCorePE处理"""
    if not template:
        return ""
    fmt = Formatter()
    pieces = []
    for literal, field, format_spec, conversion in fmt.parse(template):
        pieces.append(literal)
        if field is None:
            continue
        lowered = field.lower()
        if lowered in ("pe", "pe_id", "node", "node_id"):
            value = pe_id
            try:
                formatted = format(value, format_spec) if format_spec else str(value)
            except Exception:
                formatted = str(value)
            pieces.append(formatted)
            continue
        placeholder = "{" + field
        if conversion:
            placeholder += f"!{conversion}"
        if format_spec:
            placeholder += f":{format_spec}"
        placeholder += "}"
        pieces.append(placeholder)
    return "".join(pieces)


def _resolve_step_activation_template() -> str:
    if STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE:
        # 允许传入包含 {pe} 与 {core} 的模板；不在此处替换 {pe}
        return STEP_ACTIVATION_BCSR_TEMPLATE_OVERRIDE
    if GLOBAL_BCSR_AVAILABLE:
        return os.path.join(GLOBAL_BCSR_DIR, "pe{pe:02d}", "core{core:02d}.bcsr.bin")
    return ""


def _step_bcsr_offsets_ready() -> bool:
    return (
        STEP_ACTIVATION_BCSR_ROWPTR_OFFSET is not None and
        STEP_ACTIVATION_BCSR_COLIDX_OFFSET is not None and
        STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET is not None and
        STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET is not None
    )


def _int_or_zero(val) -> int:
    return int(val) if val is not None else 0


def _align_up(value: int, alignment: int) -> int:
    if alignment <= 0:
        return value
    return ((value + alignment - 1) // alignment) * alignment

# 允许通过环境变量覆盖 BCSR 目录；优先10k目录，其次100k目录
_B_DEFAULT_10K = os.path.join(weights_dir, "bcsr_global_16pe_fanout256_10k")
_B_DEFAULT_100K = os.path.join(weights_dir, "bcsr_global_16pe_fanout256")
_B_ENV = os.environ.get("MESH_BCSR_DIR", "").strip()
if _B_ENV:
    GLOBAL_BCSR_DIR = os.path.abspath(_B_ENV)
elif os.path.exists(os.path.join(_B_DEFAULT_10K, "pe00", "core00.bcsr.bin.meta.json")):
    GLOBAL_BCSR_DIR = _B_DEFAULT_10K
else:
    GLOBAL_BCSR_DIR = _B_DEFAULT_100K
GLOBAL_BCSR_META_PATH = os.path.join(GLOBAL_BCSR_DIR, "pe00", "core00.bcsr.bin.meta.json")
GLOBAL_BCSR_META = {}
GLOBAL_WEIGHTS_COLS = TOTAL_NODES * NEURONS_PER_PE
GLOBAL_BCSR_CORE_FILE_SIZE = 0
GLOBAL_BCSR_OFFSETS = {}
# 收集 pe00 目录下所有 core 的 meta，用于计算 stride 的最大值
PE0_CORES_META = []
if os.path.exists(os.path.join(GLOBAL_BCSR_DIR, "pe00")):
    for core_idx in range(NUM_CORES_PER_PE):
        _meta_path = os.path.join(GLOBAL_BCSR_DIR, "pe00", f"core{core_idx:02d}.bcsr.bin.meta.json")
        if os.path.exists(_meta_path):
            try:
                with open(_meta_path, 'r', encoding='utf-8') as _mf:
                    PE0_CORES_META.append(_json.load(_mf))
            except Exception:
                pass
if os.path.exists(GLOBAL_BCSR_META_PATH):
    GLOBAL_BCSR_AVAILABLE = True
    try:
        with open(GLOBAL_BCSR_META_PATH, 'r', encoding='utf-8') as _meta_f:
            GLOBAL_BCSR_META = _json.load(_meta_f)
        GLOBAL_WEIGHTS_COLS = int(GLOBAL_BCSR_META.get("cols", GLOBAL_WEIGHTS_COLS))
        # 取 pe00 下所有 core 的文件大小最大值，避免 stride 过小导致写越界
        _sizes = [int(GLOBAL_BCSR_META.get("file_size", 0))]
        _sizes += [int(m.get("file_size", 0)) for m in PE0_CORES_META if isinstance(m, dict)]
        GLOBAL_BCSR_CORE_FILE_SIZE = max(_sizes) if _sizes else int(GLOBAL_BCSR_META.get("file_size", 0))
        GLOBAL_BCSR_OFFSETS = {
            "rowptr_offset": int(GLOBAL_BCSR_META.get("rowptr_offset", 0)),
            "colidx_offset": int(GLOBAL_BCSR_META.get("colidx_offset", 0)),
            "blockdata_offset": int(GLOBAL_BCSR_META.get("blockdata_offset", 0)),
            "blockids_offset": int(GLOBAL_BCSR_META.get("blockids_offset", 0)),
            "br": int(GLOBAL_BCSR_META.get("br", 1)),
            "bc": int(GLOBAL_BCSR_META.get("bc", 16)),
            "idx_bytes": int(GLOBAL_BCSR_META.get("idx_bytes", 4)),
            "val_bytes": int(GLOBAL_BCSR_META.get("val_bytes", 4)),
        }
        # 当检测到全局BCSR时，优先用 meta 行数覆盖 NEURONS_PER_CORE，确保与权重文件自洽
        try:
            _rows_meta = int(GLOBAL_BCSR_META.get("rows", 0))
            if _rows_meta > 0:
                NEURONS_PER_CORE = _rows_meta
                NEURONS_PER_PE = NUM_CORES_PER_PE * NEURONS_PER_CORE
        except Exception:
            pass
    except Exception as exc:
        print(f"⚠️ 读取全局BCSR meta失败: {exc}")
        GLOBAL_BCSR_AVAILABLE = False
else:
    GLOBAL_BCSR_AVAILABLE = False
if GLOBAL_BCSR_AVAILABLE:
    if STEP_ACTIVATION_BCSR_ROWPTR_OFFSET is None:
        STEP_ACTIVATION_BCSR_ROWPTR_OFFSET = GLOBAL_BCSR_OFFSETS.get("rowptr_offset", 0)
    if STEP_ACTIVATION_BCSR_COLIDX_OFFSET is None:
        STEP_ACTIVATION_BCSR_COLIDX_OFFSET = GLOBAL_BCSR_OFFSETS.get("colidx_offset", 0)
    if STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET is None:
        STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET = GLOBAL_BCSR_OFFSETS.get("blockdata_offset", 0)
    if STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET is None:
        STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET = GLOBAL_BCSR_OFFSETS.get("blockids_offset", 0)
    if STEP_ACTIVATION_BCSR_BR is None:
        STEP_ACTIVATION_BCSR_BR = GLOBAL_BCSR_OFFSETS.get("br", 16)
    if STEP_ACTIVATION_BCSR_BC is None:
        STEP_ACTIVATION_BCSR_BC = GLOBAL_BCSR_OFFSETS.get("bc", 16)
    if STEP_ACTIVATION_BCSR_IDX_BYTES is None:
        STEP_ACTIVATION_BCSR_IDX_BYTES = GLOBAL_BCSR_OFFSETS.get("idx_bytes", 2)
    if STEP_ACTIVATION_BCSR_VAL_BYTES is None:
        STEP_ACTIVATION_BCSR_VAL_BYTES = GLOBAL_BCSR_OFFSETS.get("val_bytes", 4)
if STEP_ACTIVATION_BCSR_BR is None:
    STEP_ACTIVATION_BCSR_BR = 16
if STEP_ACTIVATION_BCSR_BC is None:
    STEP_ACTIVATION_BCSR_BC = 16
if STEP_ACTIVATION_BCSR_IDX_BYTES is None:
    STEP_ACTIVATION_BCSR_IDX_BYTES = 2
if STEP_ACTIVATION_BCSR_VAL_BYTES is None:
    STEP_ACTIVATION_BCSR_VAL_BYTES = 4
STEP_ACTIVATION_BCSR_CAN_LOAD = _step_bcsr_offsets_ready()
if GLOBAL_BCSR_CORE_FILE_SIZE <= 0:
    GLOBAL_BCSR_CORE_FILE_SIZE = 1 << 20
PER_CORE_WEIGHT_STRIDE = _align_up(GLOBAL_BCSR_CORE_FILE_SIZE, 64)
PE_WEIGHT_REGION_STRIDE = PER_CORE_WEIGHT_STRIDE * NUM_CORES_PER_PE
# 为避免PE0落在0地址，允许整体基址右移；若未设环境变量则默认移一个core步长
try:
    BASE_ADDR_GLOBAL_SHIFT = int(os.environ.get("MESH_BASE_ADDR_SHIFT", str(PER_CORE_WEIGHT_STRIDE)), 0)
except Exception:
    BASE_ADDR_GLOBAL_SHIFT = PER_CORE_WEIGHT_STRIDE
PE_MEM_ADDR_RANGE = PE_WEIGHT_REGION_STRIDE
print(f"📁 权重目录: {weights_dir}")
if GLOBAL_BCSR_AVAILABLE:
    print(f"  ✅ 检测到全局BCSR数据: {GLOBAL_BCSR_DIR}")
else:
    print("  ⚠️ 未检测到全局BCSR数据，仍使用旧的权重文件结构")
_SIM_TIME_OVERRIDE = os.environ.get("MESH_SIM_TIME")
if _SIM_TIME_OVERRIDE:
    SIMULATION_TIME = _SIM_TIME_OVERRIDE
elif 'SIMULATION_TIME' not in globals():
    SIMULATION_TIME = "200us"  # 默认200us，可被配置覆盖
#
# 可选：组件主控结束（避免与引擎 stop-at 冲突），由环境变量 MESH_ALT_STOP 控制
# 在构建任何组件之前就计算好 SIM_STOP_NS 以便节点参数可读取
_ALT_STOP = os.environ.get("MESH_ALT_STOP", "").strip()
def _parse_time_to_ns(_s: str) -> int:
    try:
        s = _s.strip().lower()
        if s.endswith("us"):
            return int(float(s[:-2]) * 1000.0)
        if s.endswith("ns"):
            return int(float(s[:-2]))
        if s.endswith("ms"):
            return int(float(s[:-2]) * 1000_000.0)
        if s.endswith("s"):
            return int(float(s[:-1]) * 1_000_000_000.0)
        return int(float(s))
    except Exception:
        return 0
SIM_STOP_NS = _parse_time_to_ns(SIMULATION_TIME) if _ALT_STOP in ("1","true","True") else 0

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
PER_NODE_STRIDE = PER_CORE_WEIGHT_STRIDE  # 向后兼容引用



print(f"🧠 分层神经网络分类任务: {MESH_SIZE}x{MESH_SIZE} = {TOTAL_NODES}个节点")
print(f"📊 网络架构:")
print(f"  输入层 (PE 0-3): {INPUT_LAYER}")
print(f"  隐藏层1 (PE 4-7): {HIDDEN_LAYER_1}")
print(f"  隐藏层2 (PE 8-11): {HIDDEN_LAYER_2}")
print(f"  输出层 (PE 12-15): {OUTPUT_LAYER}")
print(f"🎯 复杂分类任务: 类别A({CLASS_A_FREQ}Hz) vs 类别B({CLASS_B_FREQ}Hz) vs 类别C({CLASS_C_FREQ}Hz) vs 类别D({CLASS_D_FREQ}Hz)")
print(f"⚙️  权重加载模式: 启用内存权重，使用分层设计的权重文件")

# === 数据文件路径配置 ===

# === 加载预先生成的脉冲数据文件 ===
spike_data_files = []
spike_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "spike_data")

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

for pe_id in range(NODE_LIMIT):
    # 为每个PE创建独立的内存控制器
    mem_controller = sst.Component(f"pe_{pe_id}_memory_controller", "memHierarchy.MemController")
    mem_addr_start = PE_WEIGHT_REGION_STRIDE * pe_id
    mem_addr_end = mem_addr_start + PE_WEIGHT_REGION_STRIDE - 1
    mem_controller.addParams({
        "clock": "1GHz",
        "backing": "malloc",
        "addr_range_start": str(mem_addr_start),
        "addr_range_end": str(mem_addr_end)
    })
    # 使用 Ramulator2 DDR4 作为内存后端（ram2 场景）
    mem_backend = mem_controller.setSubComponent("backend", "memHierarchy.ramulator2")
    mem_backend.addParams({
        "mem_size": f"{PE_MEM_ADDR_RANGE}B",
        "configFile": _DDR4_CFG_PATH,
        "debug": "0",
        "debug_level": "0"
    })
    # 显式启用MemController全部统计（如有）
    try:
        mem_controller.enableAllStatistics({"type":"sst.AccumulatorStatistic"})
    except Exception:
        pass
    pe_memory_controllers.append(mem_controller)
    
    # 为每个PE创建内存总线，支持多个L1缓存连接
    mem_bus = sst.Component(f"pe_{pe_id}_memory_bus", "memHierarchy.Bus")
    mem_bus.addParams({
        "bus_frequency": "1GHz",
        "debug": "0",   # 精简Bus日志
        "verbose": "0"
    })
    pe_memory_buses.append(mem_bus)
    
    # 直接将内存总线连接到内存控制器（仅保留L1缓存）
    bus_to_mem_link = sst.Link(f"pe_{pe_id}_bus_to_mem")
    bus_to_mem_link.connect(
        (mem_bus, "lowlink0", "5ns"),
        (mem_controller, "highlink", "5ns")
    )
    
    # 为每个PE创建独立的WeightLoader (使用本地地址空间)
    pe_weight_base = BASE_ADDR_GLOBAL_SHIFT + PE_WEIGHT_REGION_STRIDE * pe_id
    weight_loader = sst.Component(f"pe_{pe_id}_weight_loader", "SnnDL.WeightLoader")
    weight_loader_params = {
        # 回归口径：关闭WeightLoader冗余日志（ram2 场景使用0完全静默）
        "verbose": 0,
        "base_addr_start": pe_weight_base,
        "per_core_stride": PER_CORE_WEIGHT_STRIDE,
        "num_cores": NUM_CORES_PER_PE,
        "neurons_per_core": NEURONS_PER_CORE,
        "rows_per_core": NEURONS_PER_CORE,
        "cols_per_core": GLOBAL_WEIGHTS_COLS,
        "total_neurons": NEURONS_PER_PE,
        "weight_format": "bin",
        "per_core_files": 0,
        "fill_value": 0.0,
        "validate_length": 1,
        "row_major": 1,
        "chunk_size_bytes": LOADER_CHUNK_BYTES,
        # 回归口径：使用本地配置开关
        "timed_seed_enable": 1 if LOADER_TIMED_SEED_ENABLE else 0,
        "timed_seed_allow_cache": 1 if LOADER_TIMED_SEED_ALLOW_CACHE else 0,
        "loader_done_key": f"snndl_loader_done_pe_{pe_id:02d}"
    }
    ENABLE_BCSR = False
    if GLOBAL_BCSR_AVAILABLE:
        ENABLE_BCSR = True
        tmpl = os.path.join(GLOBAL_BCSR_DIR, f"pe{pe_id:02d}", "core{core:02d}.bcsr.bin")
        weight_loader_params.update({
            "weight_format": "raw",
            "per_core_files": 1,
            "file_template": tmpl,
            "validate_length": 0,
            "bcsr_enable": 1,
            "bcsr_block_rows": GLOBAL_BCSR_OFFSETS.get("br", 1),
            "bcsr_block_cols": GLOBAL_BCSR_OFFSETS.get("bc", 16),
            "bcsr_idx_bytes": GLOBAL_BCSR_OFFSETS.get("idx_bytes", 4),
            "bcsr_val_bytes": GLOBAL_BCSR_OFFSETS.get("val_bytes", 4)
        })
    weight_loader.addParams(weight_loader_params)
    
    # 连接WeightLoader到内存总线（使用一个不与核心 L1 冲突的端口号）
    weight_loader_mem = weight_loader.setSubComponent("memory", "memHierarchy.standardInterface")
    weight_loader_mem.addParams({"port": "lowlink"})
    
    # 连接WeightLoader到内存总线 (使用highlink4，避免与核心L1缓存冲突)
    weight_loader_link = sst.Link(f"pe_{pe_id}_weight_loader_to_bus")
    _wl_port = f"highlink{NUM_CORES_PER_PE}"
    weight_loader_link.connect(
        (weight_loader_mem, "lowlink", "5ns"),
        (mem_bus, _wl_port, "5ns")
    )
    
    pe_weight_loaders.append(weight_loader)

    # 调试：打印单总线连线方案
    if DEBUG_CONN:
        print(f"[BUS-CONN] PE{pe_id} SINGLE-BUS (L1 only)")
        print(f"  mem_bus.highlink0..3 <- L1 cores")
        print(f"  mem_bus.highlink4 <- WeightLoader")
        print(f"  mem_bus.lowlink0 -> MemCtrl.highlink")

print(f"✅ 创建{len(pe_memory_controllers)}个独立PE内存控制器和{len(pe_memory_buses)}个内存总线")

# === 创建网络路由器 ===
routers = []
for i in range(NODE_LIMIT):
    router = sst.Component(f"router_{i}", "merlin.hr_router")
    router.addParams({
        "id": i,
        "num_ports": 5,  # 4个方向端口 + 1个本地端口
        "link_bw": NETWORK_BANDWIDTH,
        # 统一与 NoC 驱动口径：flit=32B
        "flit_size": "32B",
        "xbar_bw": NETWORK_BANDWIDTH,
        "input_latency": "10ns",
        "output_latency": "10ns",
        "input_buf_size": "4KiB",
        "output_buf_size": "4KiB",
        "num_vns": 1,
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

for i in range(NODE_LIMIT):
    node = sst.Component(f"multicore_pe_{i}", "SnnDL.MultiCorePE")
    
    # 根据层类型调整神经元参数
    layer_name = "输入层" if i in INPUT_LAYER else \
                 "隐藏层1" if i in HIDDEN_LAYER_1 else \
                 "隐藏层2" if i in HIDDEN_LAYER_2 else "输出层"
    
    # 神经元阈值：降低阈值增强传播（可由配置 thresholds 覆盖）
    if 'THRESHOLDS' in globals() and THRESHOLDS:
        if i in INPUT_LAYER:
            v_thresh = THRESHOLDS.get('input', 0.02)
        elif i in HIDDEN_LAYER_1:
            v_thresh = THRESHOLDS.get('hidden1', 0.03)
        elif i in HIDDEN_LAYER_2:
            v_thresh = THRESHOLDS.get('hidden2', 0.03)
        else:
            v_thresh = THRESHOLDS.get('output', 0.035)
    else:
        if i in INPUT_LAYER:
            v_thresh = 0.02
        elif i in HIDDEN_LAYER_1:
            v_thresh = 0.03
        elif i in HIDDEN_LAYER_2:
            v_thresh = 0.03
        else:
            v_thresh = 0.035
    
    # 阶段C：仅对输出层节点保留节点汇总行以便观察末端发放（日志极少，4行）
    print_node_summary_val = 1 if ENABLE_NODE_SUMMARY else 0

    pe_output_dir = os.path.join(_RUN_OUTPUT_DIR, f"pe{i:02d}")
    os.makedirs(pe_output_dir, exist_ok=True)
    # 每个PE独立的granules/window_metrics导出文件，避免多实例并发写冲突
    pe_granules_csv = os.path.join(pe_output_dir, "granules.csv")
    # 注意：window_metrics 按核心分别导出，避免 20 core 并发写同一文件
    # granules 导出暂时禁用（高并发下append易出错）
    node_params = {
        "verbose": 0,  # 回归口径：关闭多余诊断日志以提升性能
        # 诊断：强制 primary_keepalive，确保窗口推进
        "primary_keepalive": 1,
        # NOTE: SnnPESubComponent registers its own clock; enabling manual drive here would
        # double-tick cores and break step-gate quiesce semantics (can lead to GAS empty windows).
        "manual_core_drive_enable": 0,
        "print_node_summary": print_node_summary_val,
        "num_cores": NUM_CORES_PER_PE,
        "neurons_per_core": NEURONS_PER_CORE,
        "total_neurons": TOTAL_NODES * NEURONS_PER_PE,
        "total_nodes": TOTAL_NODES,
        "node_id": i,
        "global_neuron_base": i * NEURONS_PER_PE,
        # 启用少量NoC注入以产生NIC统计（严格限制规模，避免干扰）
        "enable_test_traffic": 1 if ENABLE_TEST_TRAFFIC else 0,
        "test_target_node": 15,
        "test_period": 1000,
        "test_spikes_per_burst": 1,
        "test_max_spikes": 8,
        "loop_dataset": 0,  # 禁用数据集循环
        # 权重来源：默认从内存文件；EVENT_FALLBACK 时改为事件回退
        "enable_memory_weights": 0 if EVENT_FALLBACK else 1,
        "write_weights_on_init": 0 if EVENT_FALLBACK else 1,
        "weights_file": os.path.join(weights_dir, f"classification_weights_pe_{i}.bin"),
        "v_thresh": v_thresh,  # 分层调整阈值
        "v_rest": 0.0,
        "v_reset": 0.0,
        "use_event_weight_fallback": 1 if EVENT_FALLBACK else 0,
        "event_weight_fallback": 0.1,
        "verify_weights": 0,
        "weight_verify_samples": 8,      # 增加验证样本数
        "expected_weight_value": 1.0,
        "verify_log_each_sample": 0,
        "memory_warmup_cycles": CORE_MEMORY_WARMUP_CYCLES,     # 增加预热周期
        "enable_weight_fetch": 0 if EVENT_FALLBACK else 1,
        "memory_weight_priority": 1,  # 优先使用内存权重而非事件权重
        "debug_weight_loading": 1,    # 启用权重加载调试信息
        "debug_memory_accesses": 1,   # 启用内存访问调试
        "verbose_weight_fetch": 1,    # 启用权重获取详细调试
        "enable_weight_fetch": 1,     # 确保启用权重获取
        "memory_warmup_cycles": CORE_MEMORY_WARMUP_CYCLES,
        "stage_events_csv": os.path.join(pe_output_dir, "stage_events.csv"),
        "stats_csv": os.path.join(pe_output_dir, "stats.csv")
    }

    if GLOBAL_BCSR_AVAILABLE:
        node_params.update({
            "weight_format": "bcsr",
        })

    step_activation_template = _resolve_step_activation_template()
    step_bcsr_ready = bool(step_activation_template and STEP_ACTIVATION_USE_BCSR_ROUTES and STEP_ACTIVATION_BCSR_CAN_LOAD)
    node_params.update({
        "step_random_activation_enable": STEP_RANDOM_ACT_ENABLE,
        "step_activation_enable": STEP_RANDOM_ACT_ENABLE,
        # 恢复跨 PE 路由，便于验证 NIC/远端流量
        "step_activation_build_local_only": 0,
        "step_activation_fraction": STEP_ACTIVATION_FRACTION,
        "step_activation_fanout": STEP_ACTIVATION_FANOUT,
        "step_activation_seed": STEP_ACTIVATION_SEED,
        "step_activation_event_weight": STEP_ACTIVATION_EVENT_WEIGHT,
        "step_activation_use_bcsr_routes": 1 if step_bcsr_ready else 0,
        "step_activation_bcsr_template": step_activation_template,
        "step_activation_bcsr_rows_per_core": NEURONS_PER_CORE,
        "step_activation_bcsr_br": STEP_ACTIVATION_BCSR_BR,
        "step_activation_bcsr_bc": STEP_ACTIVATION_BCSR_BC,
        "step_activation_bcsr_idx_bytes": STEP_ACTIVATION_BCSR_IDX_BYTES,
        "step_activation_bcsr_val_bytes": STEP_ACTIVATION_BCSR_VAL_BYTES,
        "step_activation_bcsr_rowptr_offset": _int_or_zero(STEP_ACTIVATION_BCSR_ROWPTR_OFFSET),
        "step_activation_bcsr_colidx_offset": _int_or_zero(STEP_ACTIVATION_BCSR_COLIDX_OFFSET),
        "step_activation_bcsr_blockdata_offset": _int_or_zero(STEP_ACTIVATION_BCSR_BLOCKDATA_OFFSET),
        "step_activation_bcsr_blockids_offset": _int_or_zero(STEP_ACTIVATION_BCSR_BLOCKIDS_OFFSET),
        "step_activation_bcsr_weight_epsilon": STEP_ACTIVATION_BCSR_WEIGHT_EPS,
        "step_reset_mem_each_step": STEP_RESET_MEM_EACH_STEP,
    })

    # 每个PE使用本地地址空间（与本PE的 WeightLoader 一致）
    # 注意：上方内存/WeightLoader环节已按 pe_id 计算了 pe_weight_base = PE_WEIGHT_REGION_STRIDE * pe_id
    # 这里在节点环节再次按 i 计算基址，避免任何核心落到 0 基址。
    pe_weight_base_i = BASE_ADDR_GLOBAL_SHIFT + PE_WEIGHT_REGION_STRIDE * i
    node_params["base_addr"] = pe_weight_base_i

    # 为保证长时间运行按目标时间结束，向 MultiCorePE 下发 sim_stop_ns（纳秒）
    if 'SIM_STOP_NS' in globals() and SIM_STOP_NS > 0:
        node_params["sim_stop_ns"] = SIM_STOP_NS
    node.addParams(node_params)

    # 创建SnnNIC网络接口（允许在禁用网络时跳过NIC以隔离不稳定因素）
    nic = None
    if not DISABLE_NETWORK:
        nic = node.setSubComponent("network_interface", "SnnDL.SnnNIC")
        # 统一使用 NoC（稳定基线）；direct_link 注入暂不启用
        _use_direct = False
        nic.addParams({
            "node_id": str(i),
            "link_bw": NETWORK_BANDWIDTH,
            "input_buf_size": BUFFER_SIZE,
            "output_buf_size": BUFFER_SIZE,
            "use_direct_link": ("true" if _use_direct else "false"),
            "port_name": "network",
            "verbose": 0,  # 精简NIC日志
            "total_nodes": TOTAL_NODES,
            "export_spike_csv": (_SPIKES_MESH_CSV if EXPORT_SPIKE_CSV else ""),
        })
        try:
            nic.enableAllStatistics({"type": "sst.AccumulatorStatistic"})
        except Exception:
            pass

    # 为每个核心在MultiCorePE上创建完整的SnnPESubComponent，并为每个配置其own memory子组件
    MIN_PARAMS = os.environ.get("MESH_MINIMAL_CORE_PARAMS", "").strip() not in ("", "0", "false", "False")
    for core_idx in range(NUM_CORES_PER_PE):
        # 为每个核心创建SnnPESubComponent（作为用户配置的子组件）
        core_subcomponent = node.setSubComponent(f"core{core_idx}", "SnnDL.SnnPESubComponent")
        # 与 WeightLoader 的 per-core 写入布局严格一致：
        core_base_addr = pe_weight_base_i + core_idx * PER_CORE_WEIGHT_STRIDE
        # 映射/索引模式：
        #  - 当检测到全局 BCSR 权重时，优先采用严格 GAS 的 BCSR 读取模式：index_mode=bcsr_post_row
        #  - 否则保留旧映射：
        #     M0/post-owned（默认）：index_mode=post_row_pre_col
        #     M1/pre-owned：index_mode=pre_row_post_col
        _map_env = os.environ.get("MESH_MAPPING_MODE", "post").strip().lower()
        if GLOBAL_BCSR_AVAILABLE and not FORCE_DENSE:
            _index_mode = "bcsr_post_row"
        else:
            _index_mode = "post_row_pre_col" if _map_env in ("post", "post_owned", "m0") else "pre_row_post_col"

        if MIN_PARAMS:
            core_params = {
                "core_id": core_idx,
                "total_cores": NUM_CORES_PER_PE,
                "global_neuron_base": i * NEURONS_PER_PE + core_idx * NEURONS_PER_CORE,
                "num_neurons": NEURONS_PER_CORE,
                "neurons_per_pe": NEURONS_PER_PE,
                "base_addr": core_base_addr,
                "node_id": i,
                "verbose": 0,
                "gas_enable": 1,
                "gas_window_mode": 1,
                "window_read_enable": 1,
                "line_size_bytes": SUBCOMP_LINE_BYTES,
                "index_mode": _index_mode,
                "weights_cols": GLOBAL_WEIGHTS_COLS,
            }
        else:
            core_params = {
                "core_id": core_idx,
                "total_cores": NUM_CORES_PER_PE,
                # 每核负责 NEURONS_PER_CORE 行，全局ID区间需加上 core_idx 偏移
                "global_neuron_base": i * NEURONS_PER_PE + core_idx * NEURONS_PER_CORE,
                "num_neurons": NEURONS_PER_CORE,
                "neurons_per_pe": NEURONS_PER_PE,
                "v_thresh": v_thresh,
                "v_reset": 0.0,
                "v_rest": 0.0,
                "tau_mem": globals().get('CORE_TAU_MEM', 20.0),
                "t_ref": 2,
                "base_addr": core_base_addr,
                "node_id": i,
                # 回归口径：按配置设置核心verbose
                "verbose": (CORE_VERBOSE if 'CORE_VERBOSE' in globals() else 0),
                "enable_weight_fetch": 0 if EVENT_FALLBACK else 1,
                "write_weights_on_init": 1,
                "memory_warmup_cycles": CORE_MEMORY_WARMUP_CYCLES,
                "init_default_weight": 0.5,
                "loader_barrier_cycles": CORE_LOADER_BARRIER_CYCLES,
                # 恢复严格语义：读前 gate WeightLoader 完成（与本PE的 WeightLoader 使用相同 key）
                "loader_done_key": f"snndl_loader_done_pe_{i:02d}",
                "max_outstanding_requests": 64,
                "max_cache_entries": 65536,
                "use_event_weight_fallback": 1 if EVENT_FALLBACK else 0,
                "merge_read_cacheline": 1,
                "merge_read_row": 1,
                # 新增：全网读取模式（行=post_local=0..15，列=pre_global=0..255）
                "weights_cols": GLOBAL_WEIGHTS_COLS,
                "index_mode": _index_mode,
                "line_size_bytes": SUBCOMP_LINE_BYTES,
                "enable_detailed_map_log": 0,
                # 严格 GAS 开关：按窗口执行 Gather→Apply→Scatter，启用累加
                # 与单PE脚本保持一致，避免旧路径在窗口模式下导致零增量
                "gas_enable": 1,
                "gas_window_mode": 1,
                "gas_window_cycles_gather": _GAS_WINDOW_CYCLES["gather"],
                "apply_acc_enable": 1,
                # 新增：密集累加器及影子验证（通过环境变量临时门控；默认不影响现有静默行为）
                #   SNNDL_APPLY_DENSE_ACC: 1/0 （默认1）
                #   SNNDL_ACC_SHADOW_VERIFY: 1/0 （默认0；且需 SNNDL_DIAG_ENABLE=1）
                "apply_dense_acc_enable": (0 if str(os.environ.get("SNNDL_APPLY_DENSE_ACC", "1")).lower() in ("0", "false") else 1),
                "acc_shadow_verify_enable": (1 if str(os.environ.get("SNNDL_ACC_SHADOW_VERIFY", "0")).lower() not in ("0", "false") else 0),
                # 严格GAS窗口读：开启窗口读发起路径（BeginApply时按边/集合发起权重读取）
                "window_read_enable": 1,
                # 恢复按配置开关（local_run_config.json 的 window_read_debug）
                "window_read_debug": (1 if ('_cfg' in globals() and bool(_cfg.get('window_read_debug', 0))) else 0),
                # 回归口径：启用rowptr文件回退，小重试次数
                "bcsr_rowptr_retry_max": 8,
                "bcsr_rowptr_file_fallback_enable": 1,
                # 每窗Scatter诊断条数限制，避免日志爆炸
                "scatter_diag_limit": (8 if ('_cfg' in globals() and bool(_cfg.get('window_read_debug', 0))) else 0),
                "record_edge_apply_enable": 1 if RECORD_EDGE_APPLY_ENABLE else 0,
                "record_edge_idle_enable": 1 if RECORD_EDGE_IDLE_ENABLE else 0,
                "record_edge_scatter_enable": 1 if RECORD_EDGE_SCATTER_ENABLE else 0,
                # 新增：SoA/AoS/AoSoA（默认AoS）
                "use_soa_neuron_state": USE_SOA_STATE,
                "use_aosoa_neuron_state": 1 if USE_AOSOA_STATE else 0,
                "aosoa_block_rows": AOSOA_BLOCK_ROWS,
                # 影子验证默认关闭（调试时按需开启，默认使用致密累加器）
                # 轻预热：开启少量验证读，仅用于把热点行读入缓存；不进行文件对比
                "verify_weights": 1 if (i == 0 and core_idx == 0) else 0,  # 仅在 PE0/core0 开启诊断探针
                "verify_against_file": 0,
                "verify_file_template": "",
                "weight_verify_samples": 1,
                "verify_epsilon": 1e-6,
                "verify_log_each_sample": 1 if (i == 0 and core_idx == 0) else 0,
                "verify_log_each_sample": 0,
                "verify_cluster_enable": 1 if VERIFY_CLUSTER_ENABLE else 0,
                # 启用按路由模式（默认weight_driven）
                "routing_mode": ROUTING_MODE if 'ROUTING_MODE' in globals() else "weight_driven",
                "weights_template": os.path.join(GLOBAL_BCSR_DIR, "pe{pe:02d}", "core{core:02d}.bcsr.bin") if GLOBAL_BCSR_AVAILABLE else os.path.join(weights_dir, "classification_weights_pe_{pe}.bin"),
                "total_nodes": TOTAL_NODES,
                "routing_epsilon": ROUT_EPS,             # 可由local_run_config覆盖
                "routing_topk_per_pe": ROUT_TOPK_PER_PE, # 可由local_run_config覆盖
                "routing_topk": ROUT_TOPK,               # 可由local_run_config覆盖
                "route_exclude_self_pe": 0,
                "route_layers_mask": "",          # 不限制层间传播
                "route_filter_warn": 0,
                # 关闭映射CSV，改回按权重矩阵扫描构建路由
                "mapping_mode": "off",
                "mapping_edges_file": "",
                "mapping_csv_has_header": 1,
                "mapping_csv_separator": ",",
                "mapping_assume_block_ids": 1
            }
        if ENABLE_BCSR:
            core_params["index_mode"] = "bcsr_post_row"
            core_params["bcsr_block_rows"] = GLOBAL_BCSR_OFFSETS.get("br", 1)
            core_params["bcsr_block_cols"] = GLOBAL_BCSR_OFFSETS.get("bc", 16)
            core_params["bcsr_val_bytes"] = GLOBAL_BCSR_OFFSETS.get("val_bytes", 4)
            core_params["bcsr_idx_bytes"] = GLOBAL_BCSR_OFFSETS.get("idx_bytes", 4)
            core_params["bcsr_rowptr_offset"] = GLOBAL_BCSR_OFFSETS.get("rowptr_offset", 0)
            core_params["bcsr_colidx_offset"] = GLOBAL_BCSR_OFFSETS.get("colidx_offset", 0)
            core_params["bcsr_blockdata_offset"] = GLOBAL_BCSR_OFFSETS.get("blockdata_offset", 0)
            core_params["bcsr_blockids_offset"] = GLOBAL_BCSR_OFFSETS.get("blockids_offset", 0)
            # 适度的缓存容量（可后续接入配置）
            core_params["bcsr_row_index_cache_cap"] = 64
            core_params["bcsr_block_cache_cap"] = 256
        if VERIFY_ROUTING:
            core_params["verify_routing_weights"] = 1
        # 关闭收尾阶段的控制台摘要日志
        core_params["quiet_finish_logs"] = 1
        # 为 PE0/core0 提升 verbose 以便强制权重探针输出（其他核保持静默）
        if i == 0 and core_idx == 0:
            core_params["verbose"] = 1
        # 为每个核心设置独立基址：pe基址 + core_idx * stride，避免落在 0 地址
        core_params["base_addr"] = pe_weight_base_i + core_idx * PER_CORE_WEIGHT_STRIDE
        # 为每个核心明确设置基址：pe基址 + core_idx*stride，避免任何核心落在0地址
        core_params["base_addr"] = pe_weight_base_i + core_idx * PER_CORE_WEIGHT_STRIDE
        # 回归口径：默认关闭强制文件读取与验证探针
        core_params["bcsr_force_file_read"] = 0
        core_params["verify_weights"] = 0
        core_params["weight_verify_samples"] = 0
        core_params["verify_log_each_sample"] = 0
        core_params["verify_against_file"] = 0
        core_params["verify_file_template"] = ""
        # 回归阶段：取消强制文件对照，完全依赖内存路径
        core_subcomponent.addParams(core_params)
        
        # 为每个SnnPESubComponent配置内存前端（使用 GatherBufferIF 以导出 granule/窗口指标）
        core_memory = core_subcomponent.setSubComponent("memory", "SnnDL.GatherBufferIF")
        core_memory.addParams({
            # 打开组件级 verbose，便于看到 [diag-gbi] / 阶段转换日志
            # 恢复按配置开关：默认低噪声；需要时由 window_read_debug 提升
            "verbose": 2 if ("_cfg" in globals() and bool(_cfg.get('window_read_debug', 0))) else 0,
            "merge_policy": "auto",
            "sort_policy": "row",
            # 重要：禁用在 APPLY 阶段才下发读请求的延迟策略，确保上游 StandardMem 读响应 ID 与发起方一致，避免回调丢失
            # 原为 1，会导致 GatherBufferIF 聚合/改写请求，readResp 回来时 ID 不匹配 pending 映射，accUpdate_ 不触发
            "defer_issue_until_apply": 0,
            "gap_merge_enable": 1,
            "gap_merge_k_bytes": _GAS_GAP_K_BYTES,
            "burst_bytes_max": _GAS_LMAX_BYTES,
            # Enable adaptive metrics accumulation (no behavior change):
            # this turns on per-segment bandwidth/overhead tracking so
            # window payload_bytes/bursts are accumulated for reporting.
            "k_adapt_enable": 1,
            "row_bytes_guess": 8192,
            "sram_bytes": 256 * 1024,
            "row_window_enable": 1 if _GAS_ROW_WINDOW_BYTES > 0 else 0,
            "row_window_bytes": _GAS_ROW_WINDOW_BYTES,
            "row_window_timeout_ns": _GAS_ROW_WINDOW_TIMEOUT_NS,
            "max_inflight_reads": _GAS_MAX_INFLIGHT,
            "flush_after_scatter": 1,
            "strict_mode": 1,
            "window_auto": 1,
            "window_cycles_gather": _GAS_WINDOW_CYCLES["gather"],
            # 回归到配置指定的 Apply 窗口长度，避免额外放大周期影响性能与时序
            "window_cycles_apply": _GAS_WINDOW_CYCLES["apply"],
            "window_cycles_scatter": _GAS_WINDOW_CYCLES["scatter"],
            "emit_stage_events": 1,
            "emit_stage_events_lenient": 0,
            # 禁用 granules 导出；window_metrics 改为每 core 独立文件，避免并发写冲突
            "export_granules_csv": "",
            "export_window_metrics_csv": os.path.join(pe_output_dir, f"core{core_idx:02d}_window_metrics.csv"),
            "node_id": i,
        })
        
        # 创建每个核心的L1缓存
        core_l1_cache = sst.Component(f"pe_{i}_core{core_idx}_l1", "memHierarchy.Cache")
        core_l1_cache.addParams({
            "cache_frequency": "2GHz",
            "cache_size": L1_SIZE_STR,
            "associativity": str(L1_ASSOC),
            "cache_line_size": L1_LINE_BYTES_STR,
            "access_latency_cycles": "2",
            "L1": "1",
            "coherence_protocol": "none",
            "debug": "0",
            "verbose": "0"
        })
        # 显式启用L1统计
        try:
            core_l1_cache.enableAllStatistics({"type":"sst.AccumulatorStatistic"})
        except Exception:
            pass

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
    if nic is not None:
        nics.append(nic)

    print(f"  PE{i} ({layer_name}): 阈值={v_thresh}, 权重地址=0x{node_params['base_addr']:x}")

print(f"✅ 创建{len(nodes)}个分层PE节点完成")

spike_sources = []
if ENABLE_SPIKE_SOURCE_FLAG:
    # === 创建SpikeSource组件（仅连接到输入层：通过 NIC direct_link 注入）===
    for i, pe_id in enumerate(INPUT_LAYER):  # 只为输入层PE创建SpikeSource
        if pe_id >= len(nodes):
            continue
        spike_source = sst.Component(f"spike_source_{pe_id}", "SnnDL.SpikeSource")
        spike_source.addParams({
            "verbose": 1,  # 启用诊断日志
            "dataset_path": spike_data_files[i],
            "neurons_per_core": NEURONS_PER_CORE,
            "num_cores": NUM_CORES_PER_PE,
            # 告知SpikeSource全局映射规模与偏移，确保2列TEXT数据默认dest=src+offset为全局ID
            "neurons_per_pe": NEURONS_PER_PE,
            "neuron_offset": pe_id * NEURONS_PER_PE,
            # 将起始时间对齐到窗口起点附近，便于 Strict GAS 在 Gather 阶段捕获边
            "start_time_us": 0.05 + pe_id * 0.05,
            "loop_dataset": 0,  # 禁用循环播放来调试PE0问题
            "source_id": pe_id
        })
        spike_sources.append((spike_source, pe_id))

    print(f"✅ 创建{len(spike_sources)}个SpikeSource（仅连接输入层PE 0-3）")
else:
    print("⚠️ SpikeSource 已禁用 (ENABLE_SPIKE_SOURCE_FLAG=False)")

# 建立路由器间连接（4x4 mesh），在调试限制节点数时仅连接存在的节点
connection_count = 0
mesh_size = MESH_SIZE

# 水平连接 (East-West)
for y in range(mesh_size):
    for x in range(mesh_size - 1):
        node_id = y * mesh_size + x
        east_node_id = y * mesh_size + (x + 1)
        if node_id < len(routers) and east_node_id < len(routers):
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
        if node_id < len(routers) and south_node_id < len(routers):
            router_south_link = sst.Link(f"router_south_{node_id}_to_{south_node_id}")
            router_south_link.connect(
                (routers[node_id], "port2", "5ns"),
                (routers[south_node_id], "port3", "5ns")
            )
            connection_count += 1

print(f"✅ 完成{len(nics)}个NIC连接和{connection_count}个路由器连接")

if spike_sources:
    # 连接SpikeSource到输入层 PE（不经 NoC，稳定基线用于严格 GAS 诊断）
    for spike_source, pe_id in spike_sources:
        if pe_id < len(nodes):
            spike_link = sst.Link(f"spike_source_{pe_id}_to_pe_{pe_id}")
            spike_link.connect(
                (spike_source, "spike_output", "5ns"),
                (nodes[pe_id], "external_spike_input", "5ns")
            )

    print(f"✅ 完成{len(spike_sources)}个SpikeSource到输入层连接")

# === 统计信息收集 ===
for i, node in enumerate(nodes):
    # 启用与SnnDL库实际注册一致的统计项，确保CSV写入有效
    node.enableStatistics([
        "external_spikes_sent",
        "external_spikes_received",
        "total_spikes_processed",
        "inter_core_messages",
        "memory_requests",
        "mem_req_size_bytes",
        "mem_outstanding_at_issue",
        # GAS相关（父组件聚合自各core）
        "gas_unique_bytes_total",
        "gas_total_payload_bytes",
        "gas_apply_acc_updates_total",
        "gas_acc_posts_touched_total",
        "gas_scatter_spikes_emitted_total",
        "gas_acc_high_watermark_bytes_total",
        "gas_acc_spill_records_total",
        "gas_acc_spilled_bytes_total",
        "gas_total_payload_bytes",
        "gas_unique_bytes_total",
        "avg_core_utilization",
        "total_neurons_fired"
    ])

for i, router in enumerate(routers):
    router.enableStatistics([
        "router.packet_count",
        "router.network_load"
    ])

# 连接 NIC 到路由器（允许整体禁用以隔离网络对稳定性的影响）
connection_count = 0
mesh_size = MESH_SIZE
if not DISABLE_NETWORK:
    for i in range(min(len(nics), len(routers))):
        nic_router_link = sst.Link(f"nic_{i}_to_router_{i}")
        nic_router_link.connect(
            (nics[i], "network", "5ns"),
            (routers[i], "port4", "5ns")
        )
        connection_count += 1

# === 配置仿真 ===
sst.setProgramOption("timebase", "1ps")
# 允许通过环境变量改为“组件主控结束”，以规避 stop-at 与引擎 Exit 冲突
_ALT_STOP = os.environ.get("MESH_ALT_STOP", "").strip()
def _parse_time_to_ns(s: str) -> int:
    try:
        s2 = s.strip().lower()
        if s2.endswith("us"):
            return int(float(s2[:-2]) * 1000.0)
        if s2.endswith("ns"):
            return int(float(s2[:-2]))
        if s2.endswith("ms"):
            return int(float(s2[:-2]) * 1000_000.0)
        if s2.endswith("s"):
            return int(float(s2[:-1]) * 1_000_000_000.0)
        return int(float(s2))
    except Exception:
        return 0
if _ALT_STOP in ("1","true","True"):
    SIM_STOP_NS = _parse_time_to_ns(SIMULATION_TIME)
else:
    SIM_STOP_NS = 0
if SIM_STOP_NS <= 0:
    sst.setProgramOption("stop-at", SIMULATION_TIME)

# 启动提示（简化版）
print(f"\n🚀 启动4x4分层网络仿真（时长: {SIMULATION_TIME}）...")
# 允许通过环境变量改用“事件权重回退”模式（不依赖权重文件）
EVENT_FALLBACK = os.environ.get("MESH_WEIGHT_MODE", "mem").strip().lower() in ("event", "event_fallback", "fallback")
