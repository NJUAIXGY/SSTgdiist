# snn3dexp Phase-2 Stream/Writeback Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `snn3dexp` 第二阶段中仍停留在“地址契约/analysis alias”层的 `stream` 与 `writeback` region，升级为 `TrafficMemWorkload -> StreamWorkload` 路径上的真实 memory request 发流，并将 counters 接通到 parser、analysis 与 `full_3d` smoke。

**Architecture:** 复用已经落地的 `metadata_lookup` / `synapse_gather` semantic substreams，不重写 workload 结构，也不改 `memHierarchy` object graph。核心做法是在 `StreamWorkload` 中补齐 `stream_region` 与 `writeback_region` 两条 semantic substreams，让四类 home-stack regions 都走统一的 read-after-write verify 机制；Python 侧继续把显式 counters 映射到 `sparse_window_streams` / `writeback_region_writes` 语义摘要。

**Tech Stack:** Python 3 `unittest`、SST Python object graph、SnnDL C++17、`memHierarchy`、`snn3dexp`

---

### Task 1: 为 stream/writeback semantic runtime 补失败测试

**Files:**
- Modify: `snn3dexp/tests/test_cpp_traffic_mem_workload_contract.py`
- Modify: `snn3dexp/tests/test_run_case.py`
- Modify: `snn3dexp/tests/test_synapse_memory_semantics.py`
- Modify: `snn3dexp/tests/test_sst_graph_builder.py`

**Step 1: Write the failing test**
- 在 `test_cpp_traffic_mem_workload_contract.py` 锁定：
  - `StreamWorkload` 读取：
    - `stream_region_enable`
    - `writeback_region_enable`
    - `stream_base_addr`
    - `writeback_base_addr`
    - `stream_region_bytes`
    - `writeback_region_bytes`
  - `getStatistics()` 导出：
    - `stream_region_writes_issued_total`
    - `stream_region_reads_issued_total`
    - `writeback_region_writes_issued_total`
    - `writeback_region_reads_issued_total`
- 在 `test_run_case.py` 锁定 `_parse_processing_stats()` 会保留：
  - `stream_region_writes_issued_total`
  - `writeback_region_writes_issued_total`
- 在 `test_synapse_memory_semantics.py` 锁定 analysis 优先使用显式：
  - `stream_region_writes_issued_total`
  - `writeback_region_writes_issued_total`
- 在 `test_sst_graph_builder.py` 锁定 `core0.params` 包含：
  - `stream_region_enable`
  - `writeback_region_enable`

**Step 2: Run test to verify it fails**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_cpp_traffic_mem_workload_contract snn3dexp.tests.test_run_case snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_sst_graph_builder -v`
- Expected: FAIL，当前尚未实现显式 stream/writeback runtime counters 和对应参数

### Task 2: 在 StreamWorkload 中补齐 stream/writeback semantic substreams

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/stream/StreamWorkload.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/stream/StreamWorkload.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/workload_stats/StreamWorkloadStatsModule.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`

**Step 1: Write minimal implementation**
- 在 `SemanticMemoryKind` 中新增：
  - `StreamRegion`
  - `WritebackRegion`
- 在 `Config` 中新增：
  - `stream_region`
  - `writeback_region`
- 在 runtime state 中新增：
  - `stream_region_state_`
  - `writeback_region_state_`
- 让 `configureFromParams()` 读取：
  - `stream_region_enable`
  - `writeback_region_enable`
  - `stream_base_addr`
  - `writeback_base_addr`
  - `stream_region_bytes`
  - `writeback_region_bytes`
- 让 `onClockTick()` 在 semantic 模式下调度四类 substreams：
  - `metadata_lookup`
  - `synapse_gather`
  - `stream_region`
  - `writeback_region`
- 在 `noteMemoryIssue_()` / `getStatistics()` 中新增：
  - `stream_region_*`
  - `writeback_region_*`
- 在 `StreamWorkloadStatsModule` 与 `MultiCorePE` stats docs 中同步注册

**Step 2: Run targeted tests**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_cpp_traffic_mem_workload_contract -v`
- Expected: PASS

### Task 3: 接通 object graph / parser / analysis

**Files:**
- Modify: `snn3dexp/platform/sst_graph.py`
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `snn3dexp/tools/analyze_route_memory_joint.py`

**Step 1: Write minimal implementation**
- 在 `sst_graph.py` 的 `core0_params` 中下沉：
  - `stream_region_enable`
  - `writeback_region_enable`
- 在 `run_case.py` 的 `_parse_processing_stats()` 中加入：
  - `stream_region_writes_issued_total`
  - `stream_region_reads_issued_total`
  - `stream_region_bytes_written_total`
  - `stream_region_bytes_read_total`
  - `writeback_region_writes_issued_total`
  - `writeback_region_reads_issued_total`
  - `writeback_region_bytes_written_total`
  - `writeback_region_bytes_read_total`
- 在 `analyze_route_memory_joint.py` 中：
  - `sparse_window_streams` / `sparse_window_stream_region_writes` 优先读 `stream_region_writes_issued_total`
  - `writeback_region_writes` 优先读 `writeback_region_writes_issued_total`
  - 缺字段时维持 legacy fallback/0，保证兼容

**Step 2: Run targeted tests**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_run_case snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_sst_graph_builder -v`
- Expected: PASS

### Task 4: 跑扩展回归、编译与 real smoke

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Run expanded regression**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_memory_address_layout snn3dexp.tests.test_synapse_home_stack_runtime snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_platform_builder snn3dexp.tests.test_sst_graph_builder snn3dexp.tests.test_nmc_stack_analysis snn3dexp.tests.test_cpp_traffic_mem_workload_contract snn3dexp.tests.test_run_case -v`

**Step 2: Compile SnnDL**
- Run: `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`

**Step 3: Run real smoke**
- Run: `cd "/home/xgy/remote" && python3 -m snn3dexp.tools.run_case full_3d --run-tag task19_phase2_stream_writeback_smoke --sst-smoke --stop-at 250ns`
- Expected:
  - smoke PASS
  - `sst_stats.csv` 中出现显式 `stream_region_*` / `writeback_region_*`
  - `route_memory_joint_summary.json` 中 `writeback_region_writes > 0`

**Step 4: Append progress log**
- 在 `TECH_PROGRESS.md` 末尾追加：
  - 修改内容
  - 验证命令
  - smoke 产物路径
  - 新的 semantic region counters 与 summary 指标
