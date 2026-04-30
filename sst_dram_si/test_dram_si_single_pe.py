#!/usr/bin/env python3

import sst
import os
import sys
from datetime import datetime
import json as _json
import re
import shutil


# Single-PE DRAM access focus simulation using the same mem-hierarchy template
# as SnnDL_Basic/scripts/test_classification_4x4.py, but with networking removed.

# === Stats (defaults; allow override via config) ===
_DEFAULT_STATS_LVL = 7
sst.setStatisticLoadLevel(_DEFAULT_STATS_LVL)
sst.setStatisticOutput("sst.statOutputCSV")
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from runtime_paths import (
    parse_byte_size,
    resolve_singlepe_mc_mem_size,
    resolve_singlepe_ramulator2_config,
    resolve_singlepe_spike_dataset,
)

parse_mem_size = parse_byte_size
# Output directories under sst_dram_si
_STATS_DIR = os.path.join(_SCRIPT_DIR, "stats")
_LOGS_DIR = os.path.join(_SCRIPT_DIR, "logs")
_ANALYSIS_DIR = os.path.join(_SCRIPT_DIR, "analysis")
os.makedirs(_STATS_DIR, exist_ok=True)
os.makedirs(_LOGS_DIR, exist_ok=True)
os.makedirs(_ANALYSIS_DIR, exist_ok=True)
_STATS_CSV = os.path.join(_STATS_DIR, "dram_si_stats.csv")
# 初始设置一个占位路径；实际运行路径将根据 RUN_DIR 覆盖
sst.setStatisticOutputOptions({"filepath": _STATS_CSV, "separator": ","})
# Enable key memHierarchy stats
sst.enableAllStatisticsForComponentType("memHierarchy.Cache", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForComponentType("memHierarchy.MemController", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForComponentType("SnnDL.MultiCorePE", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForComponentType("SnnDL.SnnPESubComponent", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForComponentType("SnnDL.WeightLoader", {"type":"sst.AccumulatorStatistic"})
sst.enableAllStatisticsForComponentType("SnnDL.GatherBufferIF", {"type":"sst.AccumulatorStatistic"})
try:
    # Histograms for GAS component
    sst.enableStatisticsForComponentType("SnnDL.GatherBufferIF", [
        "gas_req_coalesce_size_bytes",
        "gas_buffer_occupancy_bytes",
        "gas_stage_cycles_gather",
        "gas_stage_cycles_apply",
        "gas_stage_cycles_scatter",
    ], {
        "type": "sst.HistogramStatistic",
        # coalesce size & buffer occupancy can be large; use coarse bins
        "minvalue": 0,
        "binwidth": 64,
        "numbins": 512,
        "dumpbinsonoutput": 1,
        "includeoutofbounds": 1,
    })
except Exception:
    pass
# Batch-A: Override specific stats to Histogram for selected component types
try:
    # (Snn core histogram stats disabled in SST CSV due to registration-time constraints)
    # Cache MSHR occupancy histogram
    sst.enableStatisticsForComponentType("memHierarchy.Cache", [
        "MSHR_occupancy"
    ], {
        "type": "sst.HistogramStatistic",
        "minvalue": 0,
        "binwidth": 1,
        "numbins": 64,
        "dumpbinsonoutput": 1,
        "includeoutofbounds": 1,
    })
    # MultiCorePE: latency/队列深度 直方图（细粒度）
    sst.enableStatisticsForComponentType("SnnDL.MultiCorePE", [
        "mem_read_latency_cycles",
        "mem_read_latency_cycles_weights",
        "mem_read_latency_cycles_state",
        "mem_outstanding_at_issue",
    ], {
        "type": "sst.HistogramStatistic",
        "minvalue": 0,
        "binwidth": 4,
        "numbins": 128,
        "dumpbinsonoutput": 1,
        "includeoutofbounds": 1,
    })
    # MultiCorePE: 请求字节直方图（64B 粒度，覆盖到 16KiB），用于直接从 Sum.u64 读取总字节
    sst.enableStatisticsForComponentType("SnnDL.MultiCorePE", [
        "mem_req_size_bytes",
    ], {
        "type": "sst.HistogramStatistic",
        "minvalue": 0,
        "binwidth": 64,
        "numbins": 256,
        "dumpbinsonoutput": 1,
        "includeoutofbounds": 1,
    })
except Exception:
    pass

_CONFIG_PATH = os.path.join(_SCRIPT_DIR, 'local_run_config.json')
_CONFIG = {}
try:
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            _CONFIG = _json.load(f) or {}
except Exception as e:
    print(f"[DRAM-SI] WARN: failed to load local_run_config.json: {e}")

# === Config (defaults + local_run_config.json overrides) ===
SIMULATION_TIME = _CONFIG.get('sim_time', "200us")
NETWORK_BW = "10GiB/s"  # not used (no network), placeholder
BUFFER_SIZE = "2KiB"

NUM_CORES_PER_PE = int(_CONFIG.get('num_cores_per_pe', 4) or 4)
NEURONS_PER_CORE = int(_CONFIG.get('neurons_per_core', 4) or 4)

# Cache parameters (reuse template defaults)
L1_SIZE_STR = "16KiB"
L1_ASSOC = 8
L1_LINE_BYTES_STR = "64"
SUBCOMP_LINE_BYTES = 64
L2_SIZE_STR = "128KiB"
L2_ASSOC = 8

# MemCtrl + Loader params
PER_NODE_STRIDE = int(_CONFIG.get('per_node_stride', 0) or 0)
LOADER_CHUNK_BYTES = 128
LOADER_FILL_VALUE = 1.0  # 提高到1.0以验证神经元发放功能
LOADER_FORMAT = "bin"            # bin|raw|csv
LOADER_PER_CORE_FILES = 0        # 1=per-core
LOADER_FILE_TEMPLATE = ""
LOADER_SINGLE_FILE = ""
LOADER_VALIDATE_LENGTH = 1
LOADER_TIMED_SEED_ALLOW_CACHE = 0
MC_ACCESS_TIME = "100ns"
MC_MEM_SIZE = _CONFIG.get('mc_mem_size', _CONFIG.get('mc_mem_size', "64MiB"))

# WeightLoader BCSR defaults (only used when explicitly enabled)
LOADER_BCSR_ENABLE = 0
LOADER_BCSR_BR = 16
LOADER_BCSR_BC = 16
LOADER_BCSR_VAL_BYTES = 4
LOADER_BCSR_IDX_BYTES = 2
LOADER_BCSR_PATTERN = "diag"

# Shared key for WeightLoader↔SnnPESubComponent loader-done handshake (single-PE)
LOADER_DONE_KEY = "snndl_loader_done_singlepe"

# Memory backend (default to ramulator2 as requested)
MEM_BACKEND = "ramulator2"  # options: "ramulator2", "simple"
RAMULATOR2_CONFIG = resolve_singlepe_ramulator2_config(_SCRIPT_DIR)

def _detect_bank_fields_from_cfg(cfg_path: str):
    """Best-effort 解析 ramulator2 配置，推断 bank_bits/bank_shift。
    规则：
      - 若存在 RandomTranslation → 禁用 bank_row（返回 0,0）
      - 常见 DDR4 RoBaRaCoCh：返回 (4, 16) 作为经验位宽/偏移（与现有经验配置一致）
      - 其他情况保守禁用并提示
    注意：这是启动车间的启发式，不保证跨设备精确；若需要严格对齐，请在 cfg 中删除 RandomTranslation 并显式传入 bank_bits/bank_shift。
    """
    try:
        txt = open(cfg_path, 'r', encoding='utf-8').read()
    except Exception:
        return (0, 0)
    if re.search(r"Translation:\s*\n\s*impl:\s*RandomTranslation", txt):
        print(f"[DRAM-SI cfg] bank_row 自动推断禁用：检测到 RandomTranslation ({cfg_path})")
        return (0, 0)
    m = re.search(r"AddrMapper:\s*\n\s*impl:\s*(\w+)", txt)
    mapper = m.group(1) if m else ""
    if mapper.lower() == 'robaracoch'.lower():
        # 经验：DDR4_2400R + DDR4_8Gb_x8 常见 bank 总位宽≈4；shift≈16（列+burst 等合计）
        print(f"[DRAM-SI cfg] bank_row 自动推断: mapper={mapper} → bank_bits=4, bank_shift=16")
        return (4, 16)
    print(f"[DRAM-SI cfg] bank_row 自动推断占位：未知/不支持的映射 {mapper}，保守禁用")
    return (0, 0)

ENABLE_SPIKE_SOURCE = True
DATASET_PATH_OVERRIDE = None
EVENT_WEIGHT = None
START_TIME_US = 2.0
LOOP_DATASET = 0
SPIKE_SEGMENT_ENABLE = 0
SPIKE_SLICES = 8
SPIKE_SLICE_WINDOW_US = 5
SPIKE_SLICE_GAP_US = 5

# Optional verbose knobs
NODE_VERBOSE = 0
CORE_VERBOSE = 0
GAS_IFACE_VERBOSE = 0

# Optional stats path override
STATS_CSV_OVERRIDE = None
WINDOW_STATS_ENABLE = 0
WINDOW_US = 20
WINDOW_CSV_OVERRIDE = None
WINDOW_METRICS_PATH = os.path.join(_ANALYSIS_DIR, "window_metrics.csv")
INDEX_MODE = "post_row_pre_col"
# Routing/mapping overrides (for fixed fanout via edges_csv)
ROUTING_MODE = None          # "weight_driven" to enable fanout via routes
MAPPING_MODE = None          # "edges_csv"
MAPPING_EDGES_FILE = None    # path to edges.csv
BCSR_ROWPTR_OFFSET = None
BCSR_COLIDX_OFFSET = None
BCSR_BLOCKDATA_OFFSET = None
BCSR_BLOCKIDS_OFFSET = None
BCSR_BR = None
BCSR_BC = None
BCSR_VAL_BYTES = None
BCSR_IDX_BYTES = None
BCSR_PREFETCH_ALL = None

# Parallelism (SST threads)
NUM_THREADS = 1
PARTITIONER = "simple"  # simple|self|roundrobin; simple works for single-rank multi-thread

# Profiler (runtime; default off)
CORE_ENABLE_PROF = False

# GAS (GatherBufferIF) parameters
GAS_ENABLE = 0
GAS_MERGE_POLICY = "auto"
GAS_SORT_POLICY = "row"
GAS_ROW_BYTES_GUESS = 8192
GAS_SRAM_BYTES = 256 * 1024
GAS_SRAM_ACCESS_NS = 0
GAS_MAX_INFLIGHT = 128
GAS_TAIL_WAIT_NS = 0
GAS_ALLOW_APPLY_MISS = 0
GAS_FLUSH_AFTER_SCATTER = 1
GAS_STRICT_MODE = 1
GAS_WINDOW_AUTO = 0
GAS_WIN_CYC_G = 0
GAS_WIN_CYC_A = 0
GAS_WIN_CYC_S = 0
GAS_APPLY_AUTO_END_ENABLE = 1
GAS_SCATTER_IMMEDIATE_COMPLETE = 0
GAS_BANK_BITS = 0
GAS_BANK_SHIFT = 0
GAS_ROW_WINDOW_ENABLE = 0
GAS_ROW_WINDOW_BYTES = 0
GAS_ROW_WINDOW_TIMEOUT_NS = 0
GAS_GATHER_AUTO_END_BYTES = 0
GAS_GATHER_AUTO_END_READS = 0
GAS_EMIT_STAGE_EVENTS = None
GAS_EMIT_STAGE_EVENTS_LENIENT = 1
APPLY_ACC_ENABLE = 0
STAGE_EVENTS_CSV = ""
STAGE_CYCLES_CSV = ""
PROBE_GAS_ENABLE = 0
CTRL_ENABLE = 0
CTRL_PROBE_EVERY_N = 4
CTRL_COOLDOWN_N = 4
CTRL_EPS_REQS = 0.02
CTRL_EPS_BURST = 0.05
CTRL_LAT_TOL_NS = 1
CTRL_K_LIST = "512,1024,2048,4096,8192"
CTRL_ROWWIN_LIST = "0,16384,32768,65536"
CTRL_TIMEOUT_LIST = "0,300,600"

# Scheme-1 (slice-ordered execution at PE side)
SCHEME1_ENABLE = 0
SCHEME1_SLICES = 8
SCHEME1_GATHER_CYCLES = 100
SCHEME1_SLICE_GAP_CYCLES = 0
SCHEME1_SCATTER_CYCLES = 1
SCHEME1_PARTITION_MOD = 0

# Step-level random activation defaults
STEP_RANDOM_ACT_ENABLE = 0
STEP_ACTIVATION_FRACTION = 0.03
STEP_ACTIVATION_FANOUT = 256
STEP_ACTIVATION_SEED = 12345
STEP_RESET_MEM_EACH_STEP = 0
STEP_ACTIVATION_EVENT_WEIGHT = 0.0
STEP_ACTIVATION_USE_BCSR_ROUTES = 1
STEP_ACTIVATION_BCSR_WEIGHT_EPS = 0.0
STEP_ACTIVATION_BCSR_TEMPLATE = ""

# Load overrides from local config if present
_CFG_PATH = os.path.join(_SCRIPT_DIR, "local_run_config.json")
if os.path.exists(_CFG_PATH):
    try:
        with open(_CFG_PATH, 'r', encoding='utf-8') as _f:
            _cfg = _json.load(_f)
        _sv = _cfg.get('stats_verbose')
        if _sv is not None:
            try:
                sst.setStatisticLoadLevel(int(_sv))
            except Exception:
                sst.setStatisticLoadLevel(_DEFAULT_STATS_LVL)
        _st = _cfg.get('sim_time')
        if isinstance(_st, str) and _st.strip():
            SIMULATION_TIME = _st.strip()
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
        _l2sz = _cfg.get('l2_size')
        if isinstance(_l2sz, str) and _l2sz.strip():
            L2_SIZE_STR = _l2sz.strip()
        _l2a = _cfg.get('l2_assoc')
        if _l2a is not None:
            try:
                L2_ASSOC = int(_l2a)
            except Exception:
                pass
        _mc_at = _cfg.get('mc_access_time')
        if isinstance(_mc_at, str) and _mc_at.strip():
            MC_ACCESS_TIME = _mc_at.strip()
        _mc_sz = _cfg.get('mc_mem_size')
        if isinstance(_mc_sz, str) and _mc_sz.strip():
            MC_MEM_SIZE = _mc_sz.strip()
        _mb = _cfg.get('mem_backend')
        if isinstance(_mb, str) and _mb.strip():
            MEM_BACKEND = _mb.strip().lower()
        _r2cfg = _cfg.get('ramulator2_config_file')
        if isinstance(_r2cfg, str) and _r2cfg.strip():
            RAMULATOR2_CONFIG = _r2cfg.strip()
        _stride = _cfg.get('per_node_stride')
        if _stride is not None:
            try:
                PER_NODE_STRIDE = int(_stride)
            except Exception:
                pass
        _chunk = _cfg.get('loader_chunk_bytes')
        if _chunk is not None:
            try:
                LOADER_CHUNK_BYTES = int(_chunk)
            except Exception:
                pass
        _fill = _cfg.get('loader_fill_value')
        if _fill is not None:
            try:
                LOADER_FILL_VALUE = float(_fill)
            except Exception:
                pass
        _wfmt = _cfg.get('weight_format')
        if isinstance(_wfmt, str) and _wfmt.strip():
            LOADER_FORMAT = _wfmt.strip()
        _pcf = _cfg.get('per_core_files')
        if _pcf is not None:
            LOADER_PER_CORE_FILES = 1 if bool(_pcf) else 0
        _ftmpl = _cfg.get('file_template')
        if isinstance(_ftmpl, str) and _ftmpl.strip():
            LOADER_FILE_TEMPLATE = _ftmpl.strip()
        _sfile = _cfg.get('single_file')
        if isinstance(_sfile, str) and _sfile.strip():
            LOADER_SINGLE_FILE = _sfile.strip()
        _vlen = _cfg.get('validate_length')
        if _vlen is not None:
            LOADER_VALIDATE_LENGTH = 1 if bool(_vlen) else 0
        _b_en = _cfg.get('bcsr_enable')
        if _b_en is not None:
            LOADER_BCSR_ENABLE = 1 if bool(_b_en) else 0
        _b_br = _cfg.get('bcsr_block_rows')
        if _b_br is not None:
            try: LOADER_BCSR_BR = int(_b_br)
            except Exception: pass
        _b_bc = _cfg.get('bcsr_block_cols')
        if _b_bc is not None:
            try: LOADER_BCSR_BC = int(_b_bc)
            except Exception: pass
        _b_vb = _cfg.get('bcsr_val_bytes')
        if _b_vb is not None:
            try: LOADER_BCSR_VAL_BYTES = int(_b_vb)
            except Exception: pass
        _b_ib = _cfg.get('bcsr_idx_bytes')
        if _b_ib is not None:
            try: LOADER_BCSR_IDX_BYTES = int(_b_ib)
            except Exception: pass
        _b_pat = _cfg.get('bcsr_pattern')
        if isinstance(_b_pat, str) and _b_pat.strip():
            LOADER_BCSR_PATTERN = _b_pat.strip()
        _tsac = _cfg.get('timed_seed_allow_cache')
        if _tsac is not None:
            LOADER_TIMED_SEED_ALLOW_CACHE = 1 if bool(_tsac) else 0
        _ds = _cfg.get('dataset_path')
        if isinstance(_ds, str) and _ds.strip():
            DATASET_PATH_OVERRIDE = _ds.strip()
        _ew = _cfg.get('event_weight')
        if _ew is not None:
            try:
                EVENT_WEIGHT = float(_ew)
            except Exception:
                EVENT_WEIGHT = None
        _start = _cfg.get('start_time_us')
        if _start is not None:
            try:
                START_TIME_US = float(_start)
            except Exception:
                pass
        _loop = _cfg.get('loop_dataset')
        if _loop is not None:
            LOOP_DATASET = 1 if bool(_loop) else 0
        _seg = _cfg.get('spike_segment_enable')
        if _seg is not None:
            SPIKE_SEGMENT_ENABLE = 1 if bool(_seg) else 0
        _ss = _cfg.get('spike_slices')
        if _ss is not None:
            try: SPIKE_SLICES = int(_ss)
            except Exception: pass
        _sw = _cfg.get('spike_slice_window_us')
        if _sw is not None:
            try: SPIKE_SLICE_WINDOW_US = int(_sw)
            except Exception: pass
        _sg = _cfg.get('spike_slice_gap_us')
        if _sg is not None:
            try: SPIKE_SLICE_GAP_US = int(_sg)
            except Exception: pass
        _ess = _cfg.get('enable_spike_source')
        if _ess is not None:
            ENABLE_SPIKE_SOURCE = bool(_ess)
        _node_v = _cfg.get('node_verbose')
        if _node_v is not None:
            try:
                NODE_VERBOSE = int(_node_v)
            except Exception:
                pass
        _core_v = _cfg.get('core_verbose')
        if _core_v is not None:
            try:
                CORE_VERBOSE = int(_core_v)
            except Exception:
                pass
        _gas_if_v = _cfg.get('gas_iface_verbose')
        if _gas_if_v is not None:
            try:
                GAS_IFACE_VERBOSE = int(_gas_if_v)
            except Exception:
                pass
        _stats_csv = _cfg.get('stats_csv')
        if isinstance(_stats_csv, str) and _stats_csv.strip():
            STATS_CSV_OVERRIDE = _stats_csv.strip()
        _prof = _cfg.get('enable_profiler')
        if _prof is not None:
            CORE_ENABLE_PROF = bool(_prof)
        _wse = _cfg.get('window_stats_enable')
        if _wse is not None:
            WINDOW_STATS_ENABLE = 1 if bool(_wse) else 0
        _wus = _cfg.get('window_us')
        if _wus is not None:
            try:
                WINDOW_US = int(_wus)
            except Exception:
                pass
        _wcsv = _cfg.get('window_csv')
        if isinstance(_wcsv, str) and _wcsv.strip():
            WINDOW_CSV_OVERRIDE = _wcsv.strip()
        _idx = _cfg.get('index_mode')
        if isinstance(_idx, str) and _idx.strip():
            INDEX_MODE = _idx.strip()
        _rmode = _cfg.get('routing_mode')
        if isinstance(_rmode, str) and _rmode.strip():
            ROUTING_MODE = _rmode.strip()
        _mmode = _cfg.get('mapping_mode')
        if isinstance(_mmode, str) and _mmode.strip():
            MAPPING_MODE = _mmode.strip()
        _edges = _cfg.get('mapping_edges_file')
        if isinstance(_edges, str) and _edges.strip():
            MAPPING_EDGES_FILE = _edges.strip()
        # GAS params
        _g = _cfg.get('gas_enable');
        if _g is not None: GAS_ENABLE = 1 if bool(_g) else 0
        _g = _cfg.get('gas_merge_policy');
        if isinstance(_g, str) and _g.strip(): GAS_MERGE_POLICY = _g.strip()
        _g = _cfg.get('gas_sort_policy');
        if isinstance(_g, str) and _g.strip(): GAS_SORT_POLICY = _g.strip()
        _g = _cfg.get('gas_row_bytes_guess');
        if _g is not None:
            try: GAS_ROW_BYTES_GUESS = int(_g)
            except Exception: pass
        _g = _cfg.get('gas_sram_bytes');
        if _g is not None:
            try: GAS_SRAM_BYTES = int(_g)
            except Exception: pass
        _g = _cfg.get('gas_sram_access_ns');
        if _g is not None:
            try: GAS_SRAM_ACCESS_NS = int(_g)
            except Exception: pass
        _g = _cfg.get('gas_max_inflight_reads');
        if _g is not None:
            try: GAS_MAX_INFLIGHT = int(_g)
            except Exception: pass
        _g = _cfg.get('gas_tail_wait_timeout_ns');
        if _g is not None:
            try: GAS_TAIL_WAIT_NS = int(_g)
            except Exception: pass
        _g = _cfg.get('gas_allow_apply_miss_read');
        if _g is not None: GAS_ALLOW_APPLY_MISS = 1 if bool(_g) else 0
        _g = _cfg.get('gas_flush_after_scatter');
        if _g is not None: GAS_FLUSH_AFTER_SCATTER = 1 if bool(_g) else 0
        _g = _cfg.get('gas_strict_mode');
        if _g is not None: GAS_STRICT_MODE = 1 if bool(_g) else 0
        _g = _cfg.get('defer_issue_until_apply')
        if _g is not None:
            try: GAS_TAIL_WAIT_NS = GAS_TAIL_WAIT_NS  # no-op anchor
            except Exception: pass
            # 保存配置值以透传到 GatherBufferIF（覆盖之前的自动默认）
            DEFER_ISSUE_UNTIL_APPLY_CFG = 1 if bool(_g) else 0
        else:
            DEFER_ISSUE_UNTIL_APPLY_CFG = None
        _g = _cfg.get('gas_window_auto');
        if _g is not None: GAS_WINDOW_AUTO = 1 if bool(_g) else 0
        _g = _cfg.get('gas_window_cycles_gather');
        if _g is not None:
            try: GAS_WIN_CYC_G = int(_g)
            except Exception: pass
        _g = _cfg.get('gas_window_cycles_apply');
        if _g is not None:
            try: GAS_WIN_CYC_A = int(_g)
            except Exception: pass
        _g = _cfg.get('gas_window_cycles_scatter');
        if _g is not None:
            try: GAS_WIN_CYC_S = int(_g)
            except Exception: pass
        _g = _cfg.get('bank_bits');
        if isinstance(_g, str) and _g.strip().lower() == 'auto':
            bb, bs = _detect_bank_fields_from_cfg(_cfg.get('ramulator2_config_file') or RAMULATOR2_CONFIG)
            GAS_BANK_BITS, GAS_BANK_SHIFT = bb, bs
        elif _g is not None:
            try: GAS_BANK_BITS = int(_g)
            except Exception: pass
        _g = _cfg.get('bank_shift');
        if isinstance(_g, str) and _g.strip().lower() == 'auto':
            bb, bs = _detect_bank_fields_from_cfg(_cfg.get('ramulator2_config_file') or RAMULATOR2_CONFIG)
            GAS_BANK_BITS, GAS_BANK_SHIFT = bb, bs
        elif _g is not None:
            try: GAS_BANK_SHIFT = int(_g)
            except Exception: pass
        _g = _cfg.get('row_window_enable');
        if _g is not None: GAS_ROW_WINDOW_ENABLE = 1 if bool(_g) else 0
        _g = _cfg.get('row_window_bytes');
        if _g is not None:
            try: GAS_ROW_WINDOW_BYTES = int(_g)
            except Exception: pass
        _g = _cfg.get('row_window_timeout_ns');
        if _g is not None:
            try: GAS_ROW_WINDOW_TIMEOUT_NS = int(_g)
            except Exception: pass
        _g = _cfg.get('gather_auto_end_bytes');
        if _g is not None:
            try: GAS_GATHER_AUTO_END_BYTES = int(_g)
            except Exception: pass
        _g = _cfg.get('gather_auto_end_reads');
        if _g is not None:
            try: GAS_GATHER_AUTO_END_READS = int(_g)
            except Exception: pass
        _g = _cfg.get('step_random_activation_enable');
        if _g is not None: STEP_RANDOM_ACT_ENABLE = 1 if bool(_g) else 0
        _g = _cfg.get('step_activation_fraction');
        if _g is not None:
            try: STEP_ACTIVATION_FRACTION = float(_g)
            except Exception: pass
        _g = _cfg.get('step_activation_fanout');
        if _g is not None:
            try: STEP_ACTIVATION_FANOUT = int(_g)
            except Exception: pass
        _g = _cfg.get('step_activation_seed');
        if _g is not None:
            try: STEP_ACTIVATION_SEED = int(_g)
            except Exception: pass
        _g = _cfg.get('step_reset_mem_each_step');
        if _g is not None: STEP_RESET_MEM_EACH_STEP = 1 if bool(_g) else 0
        _g = _cfg.get('step_activation_event_weight');
        if _g is not None:
            try:
                STEP_ACTIVATION_EVENT_WEIGHT = float(_g)
            except Exception:
                pass
        _g = _cfg.get('step_activation_use_bcsr_routes');
        if _g is not None: STEP_ACTIVATION_USE_BCSR_ROUTES = 1 if bool(_g) else 0
        _g = _cfg.get('step_activation_bcsr_weight_epsilon');
        if _g is not None:
            try:
                STEP_ACTIVATION_BCSR_WEIGHT_EPS = float(_g)
            except Exception:
                pass
        _g = _cfg.get('emit_stage_events')
        if _g is not None: GAS_EMIT_STAGE_EVENTS = 1 if bool(_g) else 0
        _g = _cfg.get('emit_stage_events_lenient')
        if _g is not None: GAS_EMIT_STAGE_EVENTS_LENIENT = 1 if bool(_g) else 0
        _g = _cfg.get('apply_acc_enable');
        if _g is not None: APPLY_ACC_ENABLE = 1 if bool(_g) else 0
        _g = _cfg.get('stage_events_csv');
        if isinstance(_g, str) and _g.strip(): STAGE_EVENTS_CSV = _g.strip()
        _g = _cfg.get('stage_cycles_csv');
        if isinstance(_g, str) and _g.strip(): STAGE_CYCLES_CSV = _g.strip()
        _g = _cfg.get('apply_auto_end_enable');
        if _g is not None: GAS_APPLY_AUTO_END_ENABLE = 1 if bool(_g) else 0
        _g = _cfg.get('scatter_immediate_complete');
        if _g is not None: GAS_SCATTER_IMMEDIATE_COMPLETE = 1 if bool(_g) else 0
        _g = _cfg.get('probe_gas_enable')
        if _g is not None: PROBE_GAS_ENABLE = 1 if bool(_g) else 0
        # BCSR overrides (optional)
        _b = _cfg.get('bcsr_block_rows');
        if _b is not None:
            try: BCSR_BR = int(_b)
            except Exception: pass
        _b = _cfg.get('bcsr_block_cols');
        if _b is not None:
            try: BCSR_BC = int(_b)
            except Exception: pass
        _b = _cfg.get('bcsr_val_bytes');
        if _b is not None:
            try: BCSR_VAL_BYTES = int(_b)
            except Exception: pass
        _b = _cfg.get('bcsr_idx_bytes');
        if _b is not None:
            try: BCSR_IDX_BYTES = int(_b)
            except Exception: pass
        _b = _cfg.get('bcsr_rowptr_offset');
        if _b is not None:
            try: BCSR_ROWPTR_OFFSET = int(_b)
            except Exception: pass
        _b = _cfg.get('bcsr_colidx_offset');
        if _b is not None:
            try: BCSR_COLIDX_OFFSET = int(_b)
            except Exception: pass
        _b = _cfg.get('bcsr_blockdata_offset');
        if _b is not None:
            try: BCSR_BLOCKDATA_OFFSET = int(_b)
            except Exception: pass
        _b = _cfg.get('bcsr_blockids_offset')
        if _b is not None:
            try: BCSR_BLOCKIDS_OFFSET = int(_b)
            except Exception: pass
        _b = _cfg.get('bcsr_prefetch_all');
        if _b is not None:
            BCSR_PREFETCH_ALL = 1 if bool(_b) else 0
        _b = _cfg.get('step_activation_bcsr_template')
        if isinstance(_b, str) and _b.strip():
            STEP_ACTIVATION_BCSR_TEMPLATE = _b.strip()
        # Parallelism overrides
        _nt = _cfg.get('num_threads')
        if _nt is not None:
            try: NUM_THREADS = max(1, int(_nt))
            except Exception: pass
        _part = _cfg.get('partitioner')
        if isinstance(_part, str) and _part.strip():
            PARTITIONER = _part.strip()
        # Scheme-1 overrides
        _s = _cfg.get('scheme1_enable');
        if _s is not None: SCHEME1_ENABLE = 1 if bool(_s) else 0
        _s = _cfg.get('scheme1_slices');
        if _s is not None:
            try: SCHEME1_SLICES = int(_s)
            except Exception: pass
        _s = _cfg.get('scheme1_gather_cycles');
        if _s is not None:
            try: SCHEME1_GATHER_CYCLES = int(_s)
            except Exception: pass
        _s = _cfg.get('scheme1_slice_gap_cycles');
        if _s is not None:
            try: SCHEME1_SLICE_GAP_CYCLES = int(_s)
            except Exception: pass
        _s = _cfg.get('scheme1_scatter_cycles');
        if _s is not None:
            try: SCHEME1_SCATTER_CYCLES = int(_s)
            except Exception: pass
        _s = _cfg.get('scheme1_partition_mod');
        if _s is not None: SCHEME1_PARTITION_MOD = 1 if bool(_s) else 0
        # Weight verification settings
        _vw = _cfg.get('verify_weights')
        if _vw is not None:
            VERIFY_WEIGHTS = 1 if bool(_vw) else 0
        _vws = _cfg.get('weight_verify_samples')
        if _vws is not None:
            try: WEIGHT_VERIFY_SAMPLES = int(_vws)
            except Exception: pass
        # Adaptive control knobs (optional)
        _ce = _cfg.get('ctrl_enable');           CTRL_ENABLE = 1 if _ce else 0 if _ce is not None else CTRL_ENABLE
        _cp = _cfg.get('ctrl_probe_every_N');    CTRL_PROBE_EVERY_N = int(_cp) if _cp is not None else CTRL_PROBE_EVERY_N
        _cc = _cfg.get('ctrl_cooldown_N');       CTRL_COOLDOWN_N = int(_cc) if _cc is not None else CTRL_COOLDOWN_N
        _er = _cfg.get('ctrl_eps_reqs');         CTRL_EPS_REQS = float(_er) if _er is not None else CTRL_EPS_REQS
        _eb = _cfg.get('ctrl_eps_burst');        CTRL_EPS_BURST = float(_eb) if _eb is not None else CTRL_EPS_BURST
        _lt = _cfg.get('ctrl_lat_tol_ns');       CTRL_LAT_TOL_NS = int(_lt) if _lt is not None else CTRL_LAT_TOL_NS
        _kl = _cfg.get('ctrl_k_list');           CTRL_K_LIST = _kl if isinstance(_kl,str) else CTRL_K_LIST
        _rl = _cfg.get('ctrl_rowwin_list');      CTRL_ROWWIN_LIST = _rl if isinstance(_rl,str) else CTRL_ROWWIN_LIST
        _tl = _cfg.get('ctrl_timeout_list');     CTRL_TIMEOUT_LIST = _tl if isinstance(_tl,str) else CTRL_TIMEOUT_LIST
        print(f"[DRAM-SI cfg] cores={NUM_CORES_PER_PE}, neurons_per_core={NEURONS_PER_CORE}, L1={L1_SIZE_STR} A{L1_ASSOC} line={SUBCOMP_LINE_BYTES}, L2={L2_SIZE_STR} A{L2_ASSOC}, MC.at={MC_ACCESS_TIME}, MC.size={MC_MEM_SIZE}, loader.chunk={LOADER_CHUNK_BYTES} fill={LOADER_FILL_VALUE}, sim_time={SIMULATION_TIME}")
    except Exception as _e:
        print(f"[DRAM-SI] Failed to load local_run_config.json: {_e}")

if isinstance(LOADER_FORMAT, str) and LOADER_FORMAT.lower() == "bcsr":
    LOADER_FORMAT = "bcsr"
    LOADER_BCSR_ENABLE = 1

def _resolve_template_path(tmpl: str, core_idx: int) -> str:
    if "{core" in tmpl:
        return tmpl.format(core=core_idx)
    return tmpl

def _maybe_abs(path: str) -> str:
    if not path:
        return path
    return path if os.path.isabs(path) else os.path.join(_SCRIPT_DIR, path)

if LOADER_FILE_TEMPLATE:
    LOADER_FILE_TEMPLATE = _maybe_abs(LOADER_FILE_TEMPLATE)
if LOADER_SINGLE_FILE:
    LOADER_SINGLE_FILE = _maybe_abs(LOADER_SINGLE_FILE)

if STEP_ACTIVATION_BCSR_TEMPLATE:
    STEP_ACTIVATION_BCSR_TEMPLATE = _maybe_abs(STEP_ACTIVATION_BCSR_TEMPLATE)
elif LOADER_FILE_TEMPLATE:
    STEP_ACTIVATION_BCSR_TEMPLATE = LOADER_FILE_TEMPLATE

STEP_ACTIVATION_CAN_LOAD_BCSR = bool(
    STEP_ACTIVATION_BCSR_TEMPLATE
    and BCSR_ROWPTR_OFFSET is not None
    and BCSR_COLIDX_OFFSET is not None
    and BCSR_BLOCKDATA_OFFSET is not None
    and BCSR_BLOCKIDS_OFFSET is not None
)
if not STEP_ACTIVATION_CAN_LOAD_BCSR:
    STEP_ACTIVATION_USE_BCSR_ROUTES = 0

LOADER_TEMPLATE_BYTES = None
try:
    if LOADER_PER_CORE_FILES and LOADER_FILE_TEMPLATE:
        sample_path = _resolve_template_path(LOADER_FILE_TEMPLATE, 0)
        if os.path.exists(sample_path):
            LOADER_TEMPLATE_BYTES = os.path.getsize(sample_path)
except Exception:
    LOADER_TEMPLATE_BYTES = None

STATS_FILE_PATH = _STATS_CSV
# === 每次运行创建时间戳子目录，集中落盘 ===
# 基准目录：sst_dram_si/outputs_large/paper2/dram_N1k/<YYYYmmdd-HHMMSS>
base_override = None
if DATASET_PATH_OVERRIDE:
    p = DATASET_PATH_OVERRIDE if os.path.isabs(DATASET_PATH_OVERRIDE) else os.path.join(_SCRIPT_DIR, DATASET_PATH_OVERRIDE)
    base_override = os.path.dirname(os.path.abspath(p))
if base_override is None:
    base_override = os.path.join(_SCRIPT_DIR, "outputs_large", "paper2", "dram_N1k")
RUN_BASE_DIR = os.path.abspath(base_override)
os.makedirs(RUN_BASE_DIR, exist_ok=True)
RUN_TS = datetime.now().strftime("%Y%m%d-%H%M%S")
RUN_DIR = os.path.join(RUN_BASE_DIR, RUN_TS)
os.makedirs(RUN_DIR, exist_ok=True)
try:
    if os.path.exists(_CFG_PATH):
        shutil.copy2(_CFG_PATH, os.path.join(RUN_DIR, "local_run_config.json"))
except Exception:
    pass

if STATS_CSV_OVERRIDE:
    # 将覆盖路径的 basename 放到本次 RUN_DIR 下
    out_name = os.path.basename(STATS_CSV_OVERRIDE.strip())
    if not out_name:
        out_name = "dram_si_stats.csv"
    out_path = os.path.join(RUN_DIR, out_name)
    sst.setStatisticOutputOptions({"filepath": out_path, "separator": ","})
    STATS_FILE_PATH = out_path
else:
    # 默认放到 RUN_DIR/dram_si_stats.csv
    STATS_FILE_PATH = os.path.join(RUN_DIR, "dram_si_stats.csv")
    sst.setStatisticOutputOptions({"filepath": STATS_FILE_PATH, "separator": ","})

# Default stage events CSV next to stats (when GAS is enabled) if not explicitly provided
try:
    # If STAGE_EVENTS_CSV not set by config, derive from stats dir and sim time
    if (not STAGE_EVENTS_CSV) or (not STAGE_EVENTS_CSV.strip()):
        # 默认落在 RUN_DIR
        _stage_file = os.path.join(RUN_DIR, f"stage_events_db_{SIMULATION_TIME}.csv")
        STAGE_EVENTS_CSV = _stage_file
    else:
        # 将用户提供的相对/绝对路径的 basename 放到 RUN_DIR，避免污染其他目录
        _name = os.path.basename(STAGE_EVENTS_CSV.strip())
        STAGE_EVENTS_CSV = os.path.join(RUN_DIR, _name)
except Exception:
    pass

# Stage-cycle CSV path (disabled unless explicitly requested)
STAGE_CYCLES_CSV_PATH = ""
try:
    if STAGE_CYCLES_CSV and STAGE_CYCLES_CSV.strip():
        _cycles_name = os.path.basename(STAGE_CYCLES_CSV.strip())
        if not _cycles_name:
            _cycles_name = "stage_cycles.csv"
        STAGE_CYCLES_CSV_PATH = os.path.join(RUN_DIR, _cycles_name)
    else:
        STAGE_CYCLES_CSV_PATH = ""
except Exception:
    STAGE_CYCLES_CSV_PATH = ""

# Compute window CSV default path if enabled and not explicitly provided
WINDOW_FILE_PATH = None
if WINDOW_STATS_ENABLE:
    if WINDOW_CSV_OVERRIDE and WINDOW_CSV_OVERRIDE.strip():
        WINDOW_FILE_PATH = WINDOW_CSV_OVERRIDE.strip()
        if not os.path.isabs(WINDOW_FILE_PATH):
            WINDOW_FILE_PATH = os.path.join(_SCRIPT_DIR, WINDOW_FILE_PATH)
    else:
        # Default next to stats CSV under windowed/windows_<N>us.csv
        base_dir = os.path.dirname(STATS_FILE_PATH)
        WINDOW_FILE_PATH = os.path.join(base_dir, f"windowed/windows_{WINDOW_US}us.csv")
    # Ensure dir exists
    os.makedirs(os.path.dirname(WINDOW_FILE_PATH), exist_ok=True)

NEURONS_PER_PE = NUM_CORES_PER_PE * NEURONS_PER_CORE

# Determine per-core weight size; prefer actual template bytes when available.
dense_weight_bytes = NEURONS_PER_CORE * NEURONS_PER_PE * 4
if LOADER_TEMPLATE_BYTES:
    WEIGHT_BYTES_PER_CORE = LOADER_TEMPLATE_BYTES
else:
    WEIGHT_BYTES_PER_CORE = dense_weight_bytes

def _align64k(x: int) -> int:
    return ((x + 65535) // 65536) * 65536

min_stride = _align64k(WEIGHT_BYTES_PER_CORE)
if PER_NODE_STRIDE and PER_NODE_STRIDE >= min_stride:
    WEIGHT_STRIDE = PER_NODE_STRIDE
else:
    WEIGHT_STRIDE = min_stride
      # 16
TOTAL_NODES = 1  # single PE

_configured_mc_mem_size = str(MC_MEM_SIZE)
_configured_mc_mem_bytes = parse_mem_size(_configured_mc_mem_size)
MC_MEM_SIZE, EFFECTIVE_MC_MEM_BYTES = resolve_singlepe_mc_mem_size(
    configured_mem_size=_configured_mc_mem_size,
    weight_stride_bytes=WEIGHT_STRIDE,
    num_cores=NUM_CORES_PER_PE,
    base_addr_start=0,
)
if EFFECTIVE_MC_MEM_BYTES != _configured_mc_mem_bytes:
    print(
        "[DRAM-SI] Auto-expand single-PE mc_mem_size: "
        f"configured={_configured_mc_mem_size} -> effective={MC_MEM_SIZE} "
        f"(weight_stride={WEIGHT_STRIDE}B, cores={NUM_CORES_PER_PE})"
    )

print(f"[DRAM-SI] Single-PE setup: cores={NUM_CORES_PER_PE}, neurons/core={NEURONS_PER_CORE}, total_neurons={NEURONS_PER_PE}")
print(f"[DRAM-SI] Cache/L2: L1={L1_SIZE_STR} A{L1_ASSOC} line={SUBCOMP_LINE_BYTES}B; L2={L2_SIZE_STR} A{L2_ASSOC}")
print(f"[DRAM-SI] MC: backend={MEM_BACKEND}, access_time={MC_ACCESS_TIME} size={MC_MEM_SIZE}; loader: chunk={LOADER_CHUNK_BYTES}B fill={LOADER_FILL_VALUE}")

# Apply multithreading options as early as possible to let SST partition the graph
try:
    if NUM_THREADS and int(NUM_THREADS) > 1:
        sst.setProgramOption("num-threads", str(int(NUM_THREADS)))
        if PARTITIONER:
            sst.setProgramOption("partitioner", PARTITIONER)
        print(f"[DRAM-SI] Enable multithreading: num_threads={NUM_THREADS}, partitioner={PARTITIONER}")
except Exception as _e:
    print(f"[DRAM-SI] Failed to set num-threads early: {_e}")

# === Paths ===
SPIKE_FILE = resolve_singlepe_spike_dataset(_SCRIPT_DIR, DATASET_PATH_OVERRIDE)

if not os.path.exists(SPIKE_FILE) and ENABLE_SPIKE_SOURCE:
    print(f"[DRAM-SI] Spike dataset not found: {SPIKE_FILE}")
    print("           Please generate or copy a simple dataset.")

# === Per-PE memory island (MemCtrl + Bus + L2) ===
mem_controller = sst.Component("pe0_memory_controller", "memHierarchy.MemController")
mem_controller.addParams({
    "clock": "1GHz",
    "addr_range_start": 0,
    "addr_range_end": int(parse_mem_size(MC_MEM_SIZE)) - 1,
    "mem_size": MC_MEM_SIZE,
    # TEMP debug: enable detailed logging for mem controller to inspect backend handoff
    "debug": 1,
    "debug_level": 10
})
if MEM_BACKEND == "ramulator2":
    # Provide a host backing store so data values from writes are observable on reads.
    mem_controller.addParams({"backing": "malloc"})
    backend = mem_controller.setSubComponent("backend", "memHierarchy.ramulator2")
    _ramu_params = {
        "mem_size": MC_MEM_SIZE,
        "configFile": RAMULATOR2_CONFIG,
    }
    try:
        _rd = _cfg.get('ramulator2_debug') if '_cfg' in globals() and isinstance(_cfg, dict) else _CONFIG.get('ramulator2_debug')
        if _rd is not None:
            try:
                _ramu_params["debug"] = int(_rd)
            except Exception:
                _ramu_params["debug"] = 1
        _rdl = _cfg.get('ramulator2_debug_level') if '_cfg' in globals() and isinstance(_cfg, dict) else _CONFIG.get('ramulator2_debug_level')
        if _rdl is not None:
            try:
                _ramu_params["debug_level"] = int(_rdl)
            except Exception:
                _ramu_params["debug_level"] = 10
    except Exception:
        pass
    backend.addParams(_ramu_params)
else:
    # Fallback to simpleMem
    mem_controller.addParams({"backing": "malloc"})
    backend = mem_controller.setSubComponent("backend", "memHierarchy.simpleMem")
    backend.addParams({
        "access_time": MC_ACCESS_TIME,
        "mem_size": MC_MEM_SIZE,
        "debug": 1,
        "debug_level": 1,
    })

mem_bus = sst.Component("pe0_memory_bus", "memHierarchy.Bus")
mem_bus.addParams({
    "bus_frequency": "1GHz",
    "debug": "0",
    "verbose": "0"
})

bus_to_mc = sst.Link("pe0_bus_to_mc")
bus_to_mc.connect((mem_bus, "lowlink0", "5ns"), (mem_controller, "highlink", "5ns"))

# L2 已移除，不启用其直方图

# === WeightLoader (configurable: fill/bin/raw) ===
# 允许通过配置禁用 WeightLoader，以避免大规模写入导致的内存和I/O压力
ENABLE_WEIGHT_LOADER = True
LOADER_VERBOSITY = 0
LOADER_TIMED_SEED_ENABLE = 1
LOADER_TIMED_SEED_ALLOW_CACHE = 1
try:
    _ewl = _cfg.get('enable_weight_loader')
    if _ewl is not None:
        ENABLE_WEIGHT_LOADER = bool(_ewl)
    _lv = _cfg.get('loader_verbose')
    if _lv is not None:
        try: LOADER_VERBOSITY = int(_lv)
        except Exception: pass
    _tse = _cfg.get('loader_timed_seed_enable')
    if _tse is not None:
        LOADER_TIMED_SEED_ENABLE = 1 if bool(_tse) else 0
    _tsc = _cfg.get('loader_timed_seed_allow_cache')
    if _tsc is not None:
        LOADER_TIMED_SEED_ALLOW_CACHE = 1 if bool(_tsc) else 0
except Exception:
    pass

if ENABLE_WEIGHT_LOADER:
    weight_loader = sst.Component("pe0_weight_loader", "SnnDL.WeightLoader")
    weight_loader.addParams({
        "verbose": LOADER_VERBOSITY,
        "base_addr_start": 0x0,
        "per_core_stride": WEIGHT_STRIDE,
        "num_cores": NUM_CORES_PER_PE,
        "neurons_per_core": NEURONS_PER_CORE,
        "rows_per_core": NEURONS_PER_CORE,
        "cols_per_core": NEURONS_PER_PE,
        "total_neurons": NEURONS_PER_PE,
        "weight_format": LOADER_FORMAT,
        "per_core_files": LOADER_PER_CORE_FILES,
        "file_template": LOADER_FILE_TEMPLATE,
        "single_file": LOADER_SINGLE_FILE,
        "fill_value": LOADER_FILL_VALUE,
        "validate_length": LOADER_VALIDATE_LENGTH,
        "row_major": 1,
        "chunk_size_bytes": LOADER_CHUNK_BYTES,
        "timed_seed_enable": LOADER_TIMED_SEED_ENABLE,
        "timed_seed_allow_cache": LOADER_TIMED_SEED_ALLOW_CACHE,
        "bcsr_enable": LOADER_BCSR_ENABLE,
        "bcsr_block_rows": LOADER_BCSR_BR,
        "bcsr_block_cols": LOADER_BCSR_BC,
        "bcsr_val_bytes": LOADER_BCSR_VAL_BYTES,
        "bcsr_idx_bytes": LOADER_BCSR_IDX_BYTES,
        "bcsr_pattern": LOADER_BCSR_PATTERN,
        "loader_done_key": LOADER_DONE_KEY,
    })
    wl_mem = weight_loader.setSubComponent("memory", "memHierarchy.standardInterface")
    wl_mem.addParams({"port": "lowlink"})
    wl_to_bus = sst.Link("pe0_weight_loader_to_bus")
    _WL_PORT = f"highlink{NUM_CORES_PER_PE}"
    wl_to_bus.connect((wl_mem, "lowlink", "5ns"), (mem_bus, _WL_PORT, "5ns"))

    try:
        weight_loader.enableStatistics([
            "weight_write_chunk_bytes",
            "weight_write_latency_cycles",
        ], {
            "type": "sst.HistogramStatistic",
            "minvalue": 0,
            "binwidth": 64,
            "numbins": 32,
            "dumpbinsonoutput": 1,
            "includeoutofbounds": 1,
        })
        weight_loader.enableStatistics([
            "weight_bytes_written_total",
            "weight_write_chunks_total",
            "weight_write_total_cycles",
        ], {
            "type": "sst.AccumulatorStatistic"
        })
    except Exception:
        pass

# === Single MultiCorePE node ===
node = sst.Component("multicore_pe_0", "SnnDL.MultiCorePE")
# Optional flags (can be overridden via local_run_config.json)
ENABLE_NODE_SUMMARY = False
ENABLE_HIST = False
ENABLE_CACHE_HIST = False
try:
    _ens = _cfg.get('enable_node_summary')
    if _ens is not None:
        ENABLE_NODE_SUMMARY = bool(_ens)
    _eh = _cfg.get('enable_histograms')
    if _eh is not None:
        ENABLE_HIST = bool(_eh)
    _ech = _cfg.get('enable_cache_histograms')
    if _ech is not None:
        ENABLE_CACHE_HIST = bool(_ech)
except Exception:
    pass

BcsrBrForRoutes = BCSR_BR if BCSR_BR is not None else LOADER_BCSR_BR
BcsrBcForRoutes = BCSR_BC if BCSR_BC is not None else LOADER_BCSR_BC
BcsrValBytesForRoutes = BCSR_VAL_BYTES if BCSR_VAL_BYTES is not None else LOADER_BCSR_VAL_BYTES
BcsrIdxBytesForRoutes = BCSR_IDX_BYTES if BCSR_IDX_BYTES is not None else LOADER_BCSR_IDX_BYTES
BcsrRowptrOffsetForRoutes = BCSR_ROWPTR_OFFSET if BCSR_ROWPTR_OFFSET is not None else 0
BcsrColidxOffsetForRoutes = BCSR_COLIDX_OFFSET if BCSR_COLIDX_OFFSET is not None else 0
# 注意：MultiCorePE 的 BCSR 路由采样目前仅支持“单一偏移值”，无法逐核传参。
# 这里仍维持配置/默认的单值（必要时通过 meta 中的 offsets 做近似），核心权重实际读取的逐核偏移在下方对 SnnPESubComponent 单独设置。
BcsrBlockdataOffsetForRoutes = BCSR_BLOCKDATA_OFFSET if BCSR_BLOCKDATA_OFFSET is not None else 0
BcsrBlockidsOffsetForRoutes = BCSR_BLOCKIDS_OFFSET if BCSR_BLOCKIDS_OFFSET is not None else 0

node_params = {
    "verbose": NODE_VERBOSE,
    "print_node_summary": 1 if ENABLE_NODE_SUMMARY else 0,
    "num_cores": NUM_CORES_PER_PE,
    "neurons_per_core": NEURONS_PER_CORE,
    "total_neurons": TOTAL_NODES * NEURONS_PER_PE,
    "node_id": 0,
    "global_neuron_base": 0,
    # pass stage_events_csv so PE can derive output dir for per-window PE-level outputs
    "stage_events_csv": STAGE_EVENTS_CSV,
    "enable_test_traffic": 0,
    # allow override by config: enable_memory_weights/enable_weight_fetch
    "enable_memory_weights": 1,
    "write_weights_on_init": 0,  # weights provided by WeightLoader
    "v_thresh": 0.00001,  # 降到极小值诊断发放机制
    "v_rest": 0.0,
    "v_reset": 0.0,
    "enable_weight_fetch": 1,
    "memory_warmup_cycles": 100,
    # Windowed stats (optional)
    "window_stats_enable": WINDOW_STATS_ENABLE,
    "window_us": WINDOW_US,
    "window_csv": WINDOW_FILE_PATH or "",
    "window_metrics_csv": WINDOW_METRICS_PATH if WINDOW_STATS_ENABLE else "",
    "step_activation_enable": STEP_RANDOM_ACT_ENABLE,
    "step_activation_fraction": STEP_ACTIVATION_FRACTION,
    "step_activation_fanout": STEP_ACTIVATION_FANOUT,
    "step_activation_seed": STEP_ACTIVATION_SEED,
    "step_activation_event_weight": STEP_ACTIVATION_EVENT_WEIGHT,
    "step_activation_use_bcsr_routes": 1 if (STEP_ACTIVATION_USE_BCSR_ROUTES and STEP_ACTIVATION_CAN_LOAD_BCSR) else 0,
    "step_activation_bcsr_template": STEP_ACTIVATION_BCSR_TEMPLATE or "",
    "step_activation_bcsr_rows_per_core": NEURONS_PER_CORE,
    "step_activation_bcsr_br": BcsrBrForRoutes,
    "step_activation_bcsr_bc": BcsrBcForRoutes,
    "step_activation_bcsr_idx_bytes": BcsrIdxBytesForRoutes,
    "step_activation_bcsr_val_bytes": BcsrValBytesForRoutes,
    "step_activation_bcsr_rowptr_offset": BcsrRowptrOffsetForRoutes,
    "step_activation_bcsr_colidx_offset": BcsrColidxOffsetForRoutes,
    "step_activation_bcsr_blockdata_offset": BcsrBlockdataOffsetForRoutes,
    "step_activation_bcsr_blockids_offset": BcsrBlockidsOffsetForRoutes,
    "step_activation_bcsr_weight_epsilon": STEP_ACTIVATION_BCSR_WEIGHT_EPS,
    "step_reset_mem_each_step": STEP_RESET_MEM_EACH_STEP,
}
node.addParams(node_params)

# Optional overrides from config
try:
    _emw = _cfg.get('enable_memory_weights')
    if _emw is not None:
        node.addParams({"enable_memory_weights": 1 if bool(_emw) else 0})
    _ewf = _cfg.get('enable_weight_fetch')
    if _ewf is not None:
        node.addParams({"enable_weight_fetch": 1 if bool(_ewf) else 0})
    _ett = _cfg.get('enable_test_traffic')
    if _ett is not None:
        node.addParams({"enable_test_traffic": 1 if bool(_ett) else 0})
    _tp = _cfg.get('test_period')
    if _tp is not None:
        node.addParams({"test_period": int(_tp)})
    _tb = _cfg.get('test_spikes_per_burst')
    if _tb is not None:
        node.addParams({"test_spikes_per_burst": int(_tb)})
    _tmax = _cfg.get('test_max_spikes')
    if _tmax is not None:
        node.addParams({"test_max_spikes": int(_tmax)})
except Exception:
    pass

# 为 MultiCorePE 实例设置 mem_req_size_bytes 的直方图参数（用于计算总读字节）
try:
    node.enableStatistics([
        "mem_req_size_bytes",
    ], {
        "type": "sst.HistogramStatistic",
        "minvalue": 0,
        "binwidth": 64,
        "numbins": 256,
        "dumpbinsonoutput": 1,
        "includeoutofbounds": 1,
    })
    # 追加启用 PE 级累计计数（避免类型级遗漏新统计项）
    node.enableStatistics([
        "total_neurons_fired",
        "unique_neurons_fired_total"
    ], {"type": "sst.AccumulatorStatistic"})
except Exception:
    pass

if ENABLE_HIST:
    try:
        node.enableStatistics([
            "mem_read_latency_cycles",
            "mem_read_latency_cycles_weights",
            "mem_read_latency_cycles_state",
        ], {
            "type": "sst.HistogramStatistic",
            "minvalue": 0,
            "binwidth": 4,
            "numbins": 128,
            "dumpbinsonoutput": 1,
            "includeoutofbounds": 1,
        })
        # mem_req_size_bytes 已在上方无条件启用
        node.enableStatistics([
            "mem_outstanding_at_issue",
        ], {
            "type": "sst.HistogramStatistic",
            "minvalue": 0,
            "binwidth": 1,
            "numbins": 64,
            "dumpbinsonoutput": 1,
            "includeoutofbounds": 1,
        })
    except Exception:
        pass

# 解析 BCSR meta（若存在），以便为每个核心设置“逐核偏移”
_bcsr_per_core_offsets = {}
try:
    # 推导 meta 文件路径：沿用 loader 的模板目录，文件名固定为 core{core:02d}.bcsr.bin.meta.json
    if LOADER_FILE_TEMPLATE:
        _tpl_dir = os.path.dirname(LOADER_FILE_TEMPLATE)
        _meta_path = os.path.join(_tpl_dir, 'core{core:02d}.bcsr.bin.meta.json')
        if os.path.exists(_meta_path):
            _meta = _json.load(open(_meta_path, 'r', encoding='utf-8'))
            if isinstance(_meta, dict) and isinstance(_meta.get('files'), list):
                for ent in _meta['files']:
                    try:
                        cid = int(ent.get('core'))
                    except Exception:
                        continue
                    _bcsr_per_core_offsets[cid] = {
                        'rowptr': int(ent.get('rowptr_offset', _meta.get('offsets', {}).get('rowptr_offset', 0) or 0)),
                        'colidx': int(ent.get('colidx_offset', _meta.get('offsets', {}).get('colidx_offset', 0) or 0)),
                        'blockdata': int(ent.get('blockdata_offset', _meta.get('offsets', {}).get('blockdata_offset', 0) or 0)),
                        'blockids': int(ent.get('blockids_offset', _meta.get('offsets', {}).get('blockids_offset', 0) or 0)),
                    }
except Exception as _e:
    print(f"[DRAM-SI] WARN: failed to parse BCSR meta: {_e}")

# Create per-core subcomponents and connect to L1 and bus
for core_idx in range(NUM_CORES_PER_PE):
    core = node.setSubComponent(f"core{core_idx}", "SnnDL.SnnPESubComponent")
    core_params = {
        "core_id": core_idx,
        "total_cores": NUM_CORES_PER_PE,
        # Per-core global base and neuron count should reflect per-core partition,
        # not the total PE neuron count. Use core_idx * NEURONS_PER_CORE as base,
        # and NEURONS_PER_CORE as the per-core neuron count.
        "global_neuron_base": core_idx * NEURONS_PER_CORE,
        "num_neurons": NEURONS_PER_CORE,
        "v_thresh": 0.00001,  # 降到极小值诊断发放机制
        "v_reset": 0.0,
        "v_rest": 0.0,
        "tau_mem": 200.0,  # 增大到200.0以减慢泄漏，验证神经元发放
        "t_ref": 2,
        "base_addr": core_idx * WEIGHT_STRIDE,
        "node_id": 0,
        "verbose": CORE_VERBOSE,
        # Allow override via local_run_config.json; default remains enabled
        "enable_weight_fetch": 1,
        "write_weights_on_init": 0,
        "memory_warmup_cycles": 100,
        "init_default_weight": 0.5,
        "max_outstanding_requests": 64,
        "max_cache_entries": 65536,
        # Allow override via config for event fallback (when memory weights disabled)
        "use_event_weight_fallback": 0,
        "merge_read_cacheline": 1,
        "merge_read_row": 1,
        "gas_enable": GAS_ENABLE,
        # 列宽应为“全局 pre 轴列数”，单 PE=TOTAL_NODES*NEURONS_PER_PE（否则 cache key 与 BCSR 缓存 prime 错位）
        "weights_cols": TOTAL_NODES * NEURONS_PER_PE,
        # single-PE: 提供 BCSR 权重模板，供 weight-driven 路由与调试使用
        "weights_template": LOADER_FILE_TEMPLATE,
        "index_mode": INDEX_MODE,
        "line_size_bytes": SUBCOMP_LINE_BYTES,
        "use_soa_neuron_state": 0,
        "use_aosoa_neuron_state": 0,
        "aosoa_block_rows": 16,
        # routing defaults; can be overridden via config
        "routing_mode": (ROUTING_MODE if ROUTING_MODE else "fixed"),
        # mapping overrides (fixed fanout via edges_csv)
        **({"mapping_mode": MAPPING_MODE} if MAPPING_MODE else {}),
        **({"mapping_edges_file": MAPPING_EDGES_FILE} if MAPPING_EDGES_FILE else {}),
        "total_nodes": TOTAL_NODES,
        "route_exclude_self_pe": 0,
        # 与 WeightLoader 使用相同的 loader_done_key，确保在权重写入完成后再发起 BCSR 读
        "loader_done_key": LOADER_DONE_KEY,
        # 默认安静收尾；当 window_read_debug=1 时自动打开 finish() 摘要，便于单 PE 调试 GAS 统计
        "quiet_finish_logs": (0 if ("_cfg" in globals() and bool(_cfg.get('window_read_debug', 0))) else 1),
        # self-check switch: default off; set to 1 only for quick non-zero weight validation
        "readresp_zero_fallback": 0,
        "stage_events_csv": STAGE_EVENTS_CSV,
        # Debug/diagnostic knobs（按配置驱动；默认关闭以避免性能影响）
        "read_force_single": (1 if ("_cfg" in globals() and bool(_cfg.get('read_force_single', 0))) else 0),
        # 诊断/窗口读控制（显式传入，未配置则为0）
        "disable_weight_cache": (1 if ("_cfg" in globals() and bool(_cfg.get('disable_weight_cache', 0))) else 0),
        "window_read_enable": (1 if ("_cfg" in globals() and bool(_cfg.get('window_read_enable', 0))) else 0),
        "window_read_budget": (int(_cfg.get('window_read_budget', 0)) if "_cfg" in globals() else 0),
        "window_read_debug": (1 if ("_cfg" in globals() and bool(_cfg.get('window_read_debug', 0))) else 0),
        # 细粒度权重/映射/诊断开关：与 mesh 模版保持一致，用于单 PE 调试 ΔV / v_mem
        "log_weight_details": (1 if ("_cfg" in globals() and bool(_cfg.get('log_weight_details', 0))) else 0),
        "enable_detailed_map_log": (1 if ("_cfg" in globals() and bool(_cfg.get('enable_detailed_map_log', 0))) else 0),
        "enable_extended_diagnostics": (1 if ("_cfg" in globals() and bool(_cfg.get('enable_extended_diagnostics', 0))) else 0),
        # profiling (runtime)
        "enable_profiler": 1 if CORE_ENABLE_PROF else 0,
        "profiler_csv_prefix": os.path.join(os.path.dirname(STATS_FILE_PATH), "profile_core"),
    }
    # Per-core overrides from config (if present)
    try:
        _ewf = _cfg.get('enable_weight_fetch')
        if _ewf is not None:
            core_params["enable_weight_fetch"] = 1 if bool(_ewf) else 0
        _uewf = _cfg.get('use_event_weight_fallback')
        if _uewf is not None:
            core_params["use_event_weight_fallback"] = 1 if bool(_uewf) else 0
        _rfs = _cfg.get('read_force_single')
        if _rfs is not None:
            core_params["read_force_single"] = 1 if bool(_rfs) else 0
        # Merge behavior overrides (diagnostic): 0 to disable row/cacheline merge
        _mrr = _cfg.get('merge_read_row')
        if _mrr is not None:
            core_params["merge_read_row"] = 1 if bool(_mrr) else 0
        _mrc = _cfg.get('merge_read_cacheline')
        if _mrc is not None:
            core_params["merge_read_cacheline"] = 1 if bool(_mrc) else 0
        _mor = _cfg.get('max_outstanding_requests')
        if _mor is not None:
            try:
                core_params["max_outstanding_requests"] = int(_mor)
            except Exception:
                pass
    except Exception:
        pass
    # propagate weight verification knobs if enabled
    try:
        if VERIFY_WEIGHTS:
            core_params["verify_weights"] = 1
            core_params["weight_verify_samples"] = WEIGHT_VERIFY_SAMPLES
            # Optional extras from config
            _vles = _cfg.get('verify_log_each_sample')
            if _vles is not None:
                core_params["verify_log_each_sample"] = 1 if bool(_vles) else 0
            _eve = _cfg.get('expected_weight_value')
            if _eve is not None:
                try:
                    core_params["expected_weight_value"] = float(_eve)
                except Exception:
                    pass
    except Exception:
        pass
    if INDEX_MODE == "bcsr_post_row":
        if BCSR_BR is not None: core_params["bcsr_block_rows"] = BCSR_BR
        if BCSR_BC is not None: core_params["bcsr_block_cols"] = BCSR_BC
        if BCSR_VAL_BYTES is not None: core_params["bcsr_val_bytes"] = BCSR_VAL_BYTES
        if BCSR_IDX_BYTES is not None: core_params["bcsr_idx_bytes"] = BCSR_IDX_BYTES
        # 优先使用 meta 中的逐核偏移；若不存在则回退到全局配置（与过去行为一致）
        if core_idx in _bcsr_per_core_offsets:
            _o = _bcsr_per_core_offsets[core_idx]
            core_params["bcsr_rowptr_offset"] = _o.get('rowptr', BCSR_ROWPTR_OFFSET or 0)
            core_params["bcsr_colidx_offset"] = _o.get('colidx', BCSR_COLIDX_OFFSET or 0)
            core_params["bcsr_blockdata_offset"] = _o.get('blockdata', BCSR_BLOCKDATA_OFFSET or 0)
            core_params["bcsr_blockids_offset"] = _o.get('blockids', BCSR_BLOCKIDS_OFFSET or 0)
        else:
            if BCSR_ROWPTR_OFFSET is not None: core_params["bcsr_rowptr_offset"] = BCSR_ROWPTR_OFFSET
            if BCSR_COLIDX_OFFSET is not None: core_params["bcsr_colidx_offset"] = BCSR_COLIDX_OFFSET
            if BCSR_BLOCKDATA_OFFSET is not None: core_params["bcsr_blockdata_offset"] = BCSR_BLOCKDATA_OFFSET
            if BCSR_BLOCKIDS_OFFSET is not None: core_params["bcsr_blockids_offset"] = BCSR_BLOCKIDS_OFFSET
        if BCSR_PREFETCH_ALL is not None: core_params["bcsr_prefetch_all"] = BCSR_PREFETCH_ALL
    core.addParams(core_params)
    # NOTE: Do NOT enable per-instance statistic registration here.
    # Enabling SnnPESubComponent stats (e.g. "scheme1_bytes_read") after component wiring
    # causes SST to fatal: "Cannot be registered for output StatisticOutputCSV after the Components have been wired up".
    # We derive baseline bytes from the parent MultiCorePE histogram `mem_req_size_bytes` instead.
    # If you need SnnPESubComponent-level stats, register them at component creation time only.

    # memory subcomponent for the core
    # Memory subcomponent: switch to GAS GatherBufferIF when enabled
    mem_if_type = "SnnDL.GatherBufferIF" if GAS_ENABLE else "memHierarchy.standardInterface"
    core_mem = core.setSubComponent("memory", mem_if_type)

    # === BYPASS L1: Connect GatherBufferIF directly to bus (like WeightLoader) ===
    # If using GatherBufferIF, supply its parameters
    if GAS_ENABLE:
        emit_stage_events = GAS_EMIT_STAGE_EVENTS if GAS_EMIT_STAGE_EVENTS is not None else (1 if GAS_WINDOW_AUTO else 0)
        emit_stage_events_lenient = GAS_EMIT_STAGE_EVENTS_LENIENT
        core_mem.addParams({
            "verbose": GAS_IFACE_VERBOSE,
            # Diagnostic CSV for GatherBufferIF probe (optional)
            "probe_gas_csv": (os.path.join(_ANALYSIS_DIR, "probe_gas_samples.csv") if PROBE_GAS_ENABLE else ""),
            "merge_policy": GAS_MERGE_POLICY,
            "sort_policy": GAS_SORT_POLICY,
            # 在严格GAS下，可由配置覆盖延迟策略；缺省=不延迟
            "defer_issue_until_apply": (DEFER_ISSUE_UNTIL_APPLY_CFG if ("DEFER_ISSUE_UNTIL_APPLY_CFG" in globals() and DEFER_ISSUE_UNTIL_APPLY_CFG is not None) else 0),
            "row_bytes_guess": GAS_ROW_BYTES_GUESS,
            "sram_bytes": GAS_SRAM_BYTES,
            # Iteration-A: enable fine-grained gap merge and bank_row support
            "gap_merge_enable": 1,
            # k, Lmax：先给安全默认，后续可通过 config 覆盖
            "gap_merge_k_bytes": 2048,
            "burst_bytes_max": 65536,
            # bank 提取位（默认0=禁用 bank_row）
            "bank_bits": GAS_BANK_BITS,
            "bank_shift": GAS_BANK_SHIFT,
            # 行窗口（默认关闭；仅在 enable=1 且 bytes/timeout>0 时触发）
            "row_window_enable": GAS_ROW_WINDOW_ENABLE,
            "row_window_bytes": GAS_ROW_WINDOW_BYTES,
            "row_window_timeout_ns": GAS_ROW_WINDOW_TIMEOUT_NS,
            "gather_auto_end_bytes": GAS_GATHER_AUTO_END_BYTES,
            "gather_auto_end_reads": GAS_GATHER_AUTO_END_READS,
            "sram_access_ns": GAS_SRAM_ACCESS_NS,
            "max_inflight_reads": GAS_MAX_INFLIGHT,
            "tail_wait_timeout_ns": GAS_TAIL_WAIT_NS,
            "allow_apply_miss_read": GAS_ALLOW_APPLY_MISS,
            "flush_after_scatter": GAS_FLUSH_AFTER_SCATTER,
            "strict_mode": GAS_STRICT_MODE,
            "window_auto": GAS_WINDOW_AUTO,
            "window_cycles_gather": GAS_WIN_CYC_G,
            "window_cycles_apply": GAS_WIN_CYC_A,
            "window_cycles_scatter": GAS_WIN_CYC_S,
            "apply_auto_end_enable": 1 if GAS_APPLY_AUTO_END_ENABLE else 0,
            "scatter_immediate_complete": 1 if GAS_SCATTER_IMMEDIATE_COMPLETE else 0,
            "stage_cycles_csv": STAGE_CYCLES_CSV_PATH,
            "emit_stage_events": emit_stage_events,
            "emit_stage_events_lenient": emit_stage_events_lenient,
            # Adaptive control (optional)
            "ctrl_enable": CTRL_ENABLE,
            "ctrl_probe_every_N": CTRL_PROBE_EVERY_N,
            "ctrl_cooldown_N": CTRL_COOLDOWN_N,
            "ctrl_eps_reqs": CTRL_EPS_REQS,
            "ctrl_eps_burst": CTRL_EPS_BURST,
            "ctrl_lat_tol_ns": CTRL_LAT_TOL_NS,
            "ctrl_k_list": CTRL_K_LIST,
            "ctrl_rowwin_list": CTRL_ROWWIN_LIST,
            "ctrl_timeout_list": CTRL_TIMEOUT_LIST,
            # P1-2: export granules for NoC trace driver
            "export_granules_csv": os.path.join(_ANALYSIS_DIR, "granules.csv"),
            "node_id": 0,
            "export_window_metrics_csv": WINDOW_METRICS_PATH,
        })
        # 告知上层核心使用window驱动（避免每周期Begin/End）
        core.addParams({
            "gas_enable": 1,
            "gas_window_mode": 1 if GAS_WINDOW_AUTO else 0,
            "apply_acc_enable": APPLY_ACC_ENABLE,
            # 启用致密累加器以避免旧 map 路径在窗口模式下的零增量问题（统计/输入修复，不改语义）
            "apply_dense_acc_enable": 1,
        })
    # Pass Scheme-1 parameters to the core (no matter which memory frontend)
    if SCHEME1_ENABLE:
        core.addParams({
            "scheme1_enable": 1,
            "scheme1_slices": SCHEME1_SLICES,
            "scheme1_gather_cycles": SCHEME1_GATHER_CYCLES,
            "scheme1_slice_gap_cycles": SCHEME1_SLICE_GAP_CYCLES,
            "scheme1_scatter_cycles": SCHEME1_SCATTER_CYCLES,
            "scheme1_partition_mod": SCHEME1_PARTITION_MOD,
        })

    # BYPASS L1: Connect GatherBufferIF lowlink directly to bus (no L1 cache)
    c_mem_to_bus = sst.Link(f"pe0_core{core_idx}_mem_to_bus")
    c_mem_to_bus.connect((core_mem, "lowlink", "5ns"), (mem_bus, f"highlink{core_idx}", "5ns"))

    # Explicitly enable per-core histograms (safer for some SST versions)
    # (Per-core enabling for Snn core histogram stats intentionally omitted)

    # Enable MSHR occupancy histogram on L1
    try:
        l1.enableStatistics(["MSHR_occupancy"], {
            "type": "sst.HistogramStatistic",
            "minvalue": 0,
            "binwidth": 1,
            "numbins": 64,
            "dumpbinsonoutput": 1,
            "includeoutofbounds": 1,
        })
    except Exception:
        pass

# --- 将本次运行的“有效配置”快照写入 RUN_DIR，确保可复现 ---
try:
    _eff = {}
    # 以原始配置为基底，再覆盖“实际生效”的派生/默认值
    if "_cfg" in globals():
        try:
            _eff = dict(_cfg) if isinstance(_cfg, dict) else {}
        except Exception:
            _eff = {}
    else:
        _eff = dict(_CONFIG) if isinstance(_CONFIG, dict) else {}

    _configured_dataset_path = _eff.get("dataset_path")
    if isinstance(_configured_dataset_path, str):
        _configured_dataset_path = _configured_dataset_path.strip() or None
    else:
        _configured_dataset_path = None

    # 核心/模型参数
    _eff.update({
        "sim_time": SIMULATION_TIME,
        "num_cores_per_pe": NUM_CORES_PER_PE,
        "neurons_per_core": NEURONS_PER_CORE,
        "neurons_total": NUM_CORES_PER_PE * NEURONS_PER_CORE,
        "mem_backend": MEM_BACKEND,
        "ramulator2_config_file": RAMULATOR2_CONFIG,
        "mc_mem_size": str(MC_MEM_SIZE),
        "mc_mem_size_configured": str(_configured_mc_mem_size),
        "mc_mem_size_configured_bytes": int(_configured_mc_mem_bytes),
        "mc_mem_size_effective": str(MC_MEM_SIZE),
        "mc_mem_size_effective_bytes": int(EFFECTIVE_MC_MEM_BYTES),
        "mc_mem_size_auto_expanded": 1 if EFFECTIVE_MC_MEM_BYTES != _configured_mc_mem_bytes else 0,
        "dataset_path": SPIKE_FILE,
        "dataset_path_configured": _configured_dataset_path,
        # 统计/输出路径：统一落在 RUN_DIR
        "stats_csv": STATS_FILE_PATH,
        "stage_events_csv": STAGE_EVENTS_CSV,
        "run_dir": RUN_DIR,
        "run_ts": RUN_TS,
    })

    # GBI（GatherBufferIF）参数（将最终值写入）
    _eff.update({
        "gas_enable": 1 if GAS_ENABLE else 0,
        "gas_merge_policy": GAS_MERGE_POLICY,
        "gas_sort_policy": GAS_SORT_POLICY,
        "gas_row_bytes_guess": int(GAS_ROW_BYTES_GUESS),
        "gas_sram_bytes": int(GAS_SRAM_BYTES),
        "gas_sram_access_ns": int(GAS_SRAM_ACCESS_NS),
        "gas_max_inflight_reads": int(GAS_MAX_INFLIGHT),
        "gas_tail_wait_timeout_ns": int(GAS_TAIL_WAIT_NS),
        "gas_allow_apply_miss_read": 1 if GAS_ALLOW_APPLY_MISS else 0,
        "gas_flush_after_scatter": 1 if GAS_FLUSH_AFTER_SCATTER else 0,
        "gas_strict_mode": 1 if GAS_STRICT_MODE else 0,
        "gas_window_auto": 1 if GAS_WINDOW_AUTO else 0,
        "gas_window_cycles_gather": int(GAS_WIN_CYC_G),
        "gas_window_cycles_apply": int(GAS_WIN_CYC_A),
        "gas_window_cycles_scatter": int(GAS_WIN_CYC_S),
        "bank_bits": int(GAS_BANK_BITS),
        "bank_shift": int(GAS_BANK_SHIFT),
        "row_window_enable": 1 if GAS_ROW_WINDOW_ENABLE else 0,
        "row_window_bytes": int(GAS_ROW_WINDOW_BYTES),
        "row_window_timeout_ns": int(GAS_ROW_WINDOW_TIMEOUT_NS),
        # defer_issue_until_apply 若未在配置中提供，则按脚本默认回落为0
        "defer_issue_until_apply": (
            int(DEFER_ISSUE_UNTIL_APPLY_CFG)
            if ("DEFER_ISSUE_UNTIL_APPLY_CFG" in globals() and DEFER_ISSUE_UNTIL_APPLY_CFG is not None)
            else 0
        ),
        "stage_cycles_csv": STAGE_CYCLES_CSV_PATH,
        "gas_apply_auto_end_enable": 1 if GAS_APPLY_AUTO_END_ENABLE else 0,
        "gas_scatter_immediate_complete": 1 if GAS_SCATTER_IMMEDIATE_COMPLETE else 0,
    })

    # 核心（SubComponent）侧与诊断相关的开关（确保显式记录）
    _rfs = 1 if ("_cfg" in globals() and bool(_cfg.get('read_force_single', 0))) else 0
    _dwc = 1 if ("_cfg" in globals() and bool(_cfg.get('disable_weight_cache', 0))) else 0
    _wre = 1 if ("_cfg" in globals() and bool(_cfg.get('window_read_enable', 0))) else 0
    _wrb = int(_cfg.get('window_read_budget', 0)) if "_cfg" in globals() else 0
    _eff.update({
        "read_force_single": _rfs,
        "disable_weight_cache": _dwc,
        "window_read_enable": _wre,
        "window_read_budget": _wrb,
        "window_read_debug": int(_cfg.get('window_read_debug', 0)) if "_cfg" in globals() else 0,
    })

    with open(os.path.join(RUN_DIR, "local_run_config.effective.json"), "w", encoding="utf-8") as _ef:
        _json.dump(_eff, _ef, ensure_ascii=False, indent=2)
except Exception:
    pass

# === SpikeSource feeding the single PE ===
if ENABLE_SPIKE_SOURCE:
    spike_source = sst.Component("spike_source_0", "SnnDL.SpikeSource")
    spike_source.addParams({
        "verbose": 0,
        "dataset_path": SPIKE_FILE,
        **({"event_weight": EVENT_WEIGHT} if EVENT_WEIGHT is not None else {}),
        "neurons_per_core": NEURONS_PER_CORE,
        "num_cores": NUM_CORES_PER_PE,
        "neurons_per_pe": NEURONS_PER_PE,
        "start_time_us": START_TIME_US,
        "loop_dataset": LOOP_DATASET,
        "source_id": 0,
        # segmented release (strict 8-slice spike emission)
        "segmented_release": SPIKE_SEGMENT_ENABLE,
        "slices_per_superstep": SPIKE_SLICES,
        "slice_window_us": SPIKE_SLICE_WINDOW_US,
        "slice_gap_us": SPIKE_SLICE_GAP_US,
    })
    ss_link = sst.Link("spike_source_0_to_pe0")
    ss_link.connect((spike_source, "spike_output", "5ns"), (node, "external_spike_input", "5ns"))

# === Component stats ===
node.enableStatistics([
    "external_spikes_sent",
    "external_spikes_received",
    "total_spikes_processed",
    "inter_core_messages",
    "memory_requests",
    "avg_core_utilization",
    "total_neurons_fired"
])

# === Simulation options ===
sst.setProgramOption("timebase", "1ps")
sst.setProgramOption("stop-at", SIMULATION_TIME)

print(f"[DRAM-SI] Running single-PE DRAM simulation for {SIMULATION_TIME} ...")
