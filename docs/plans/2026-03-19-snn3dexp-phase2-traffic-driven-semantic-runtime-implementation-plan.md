# snn3dexp Phase-2 Traffic-Driven Semantic Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `TrafficMemWorkload` 从“`traffic + periodic semantic stream` 组合”升级为“`TrafficWorkload` 输出 batch-level semantic demand，`StreamWorkload` 按 demand 发起四-region memory requests”的真实业务链。

**Architecture:** 保持 `ICoreWorkload` 不变，不把 memory 请求逻辑直接塞进 `TrafficWorkload`。改为由 `TrafficWorkload` 在每次发 batch 后沉淀 `SemanticMemoryDemand`，`TrafficMemWorkload` 在同一时钟拍取走 demand 并下沉给 `StreamWorkload`；`StreamWorkload` 增加 demand-driven semantic mode，在保留 legacy periodic semantic mode 兼容性的前提下，优先按 pending demand 发流。

**Tech Stack:** Python 3 `unittest`、SnnDL C++17、SST object graph、`memHierarchy`、`snn3dexp`

---

### Task 1: 为 traffic-driven semantic runtime 写失败测试

**Files:**
- Modify: `snn3dexp/tests/test_cpp_traffic_mem_workload_contract.py`
- Modify: `snn3dexp/tests/test_run_case.py`
- Modify: `snn3dexp/tests/test_synapse_memory_semantics.py`
- Modify: `snn3dexp/tests/test_sst_graph_builder.py`
- Modify: `snn3dexp/tests/test_nmc_stack_analysis.py`

**Step 1: Write the failing test**
- 在 `test_cpp_traffic_mem_workload_contract.py` 锁定：
  - `TrafficWorkload` 暴露 `SemanticMemoryDemand` 与 `takeSemanticDemand()`
  - `TrafficMemWorkload::onClockTick()` 先跑 `traffic_`，再 `takeSemanticDemand()`，再 `stream_.enqueueSemanticDemand()`，最后跑 `stream_`
  - `StreamWorkload` 暴露 `enqueueSemanticDemand()` 与 `semantic_memory_demand_driven_enable`
- 在 `test_run_case.py` 锁定 `_parse_processing_stats()` 保留：
  - `traffic_semantic_metadata_lookup_demands_total`
  - `traffic_semantic_synapse_gather_demands_total`
  - `traffic_semantic_stream_region_demands_total`
  - `traffic_semantic_writeback_region_demands_total`
- 在 `test_synapse_memory_semantics.py` 锁定 joint summary 暴露 traffic-driven runtime 的 demand/issued/backlog 关系
- 在 `test_sst_graph_builder.py` 锁定 `core0.params` 下沉：
  - `semantic_memory_demand_driven_enable`
- 在 `test_nmc_stack_analysis.py` 锁定 stack summary 聚合新的 traffic semantic demand totals

**Step 2: Run test to verify it fails**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_cpp_traffic_mem_workload_contract snn3dexp.tests.test_run_case snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_sst_graph_builder snn3dexp.tests.test_nmc_stack_analysis -v`
- Expected: FAIL，因为当前实现还没有 traffic-driven semantic demand 导出 / 下沉 / 汇总链路

### Task 2: 让 TrafficWorkload 成为 semantic demand 源头

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/workload_stats/StreamWorkloadStatsModule.h`

**Step 1: Write minimal implementation**
- 在 `TrafficWorkload` 中新增 `SemanticMemoryDemand`
- 在每次 `emitNeuronFireBatch()` 后根据：
  - `pres.size()`
  - `SpikeCommSubsystem` 的 packet counter 增量
  生成四类 demand：
  - `metadata_lookup`
  - `synapse_gather`
  - `stream_region`
  - `writeback_region`
- 提供 `takeSemanticDemand()`，返回并清空 pending demand
- 导出累计 stats：
  - `traffic_semantic_metadata_lookup_demands_total`
  - `traffic_semantic_synapse_gather_demands_total`
  - `traffic_semantic_stream_region_demands_total`
  - `traffic_semantic_writeback_region_demands_total`
- 在 `StreamWorkloadStatsModule` 里注册这些 traffic semantic counters，保证 SST CSV 可见

**Step 2: Run targeted tests**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_cpp_traffic_mem_workload_contract -v`
- Expected: PASS

### Task 3: 让 TrafficMemWorkload 把 demand 下沉给 StreamWorkload

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic_mem/TrafficMemWorkload.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic_mem/TrafficMemWorkload.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/stream/StreamWorkload.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/stream/StreamWorkload.cc`

**Step 1: Write minimal implementation**
- `TrafficMemWorkload::onClockTick()` 顺序改为：
  1. `traffic_.onClockTick(now_cycle)`
  2. `auto demand = traffic_.takeSemanticDemand()`
  3. `stream_.enqueueSemanticDemand(demand)`
  4. `stream_.onClockTick(now_cycle)`
- `StreamWorkload` 新增：
  - `SemanticMemoryDemand`
  - `enqueueSemanticDemand()`
  - `semantic_memory_demand_driven_enable`
  - per-region pending demand budgets
- `StreamWorkload::onClockTick()` 在 demand-driven 模式下：
  - 优先按 pending demand issue 四类 semantic requests
  - 保留 legacy periodic semantic mode fallback

**Step 2: Run targeted tests**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_cpp_traffic_mem_workload_contract snn3dexp.tests.test_run_case -v`
- Expected: PASS

### Task 4: 接通 object graph / parser / analysis

**Files:**
- Modify: `snn3dexp/platform/sst_graph.py`
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `snn3dexp/tools/analyze_route_memory_joint.py`
- Modify: `snn3dexp/tools/analyze_stack_nmc.py`

**Step 1: Write minimal implementation**
- 在 `sst_graph.py` 的 `core0_params` 中下沉：
  - `semantic_memory_demand_driven_enable`
- 在 `_parse_processing_stats()` 中保留 traffic semantic demand counters
- 在 `build_route_memory_joint_summary()` 中新增 traffic-driven semantic runtime 摘要：
  - demand totals
  - issued totals
  - backlog / gap
- 在 `build_stack_nmc_summary()` 中聚合各 stack 的 traffic semantic demand totals

**Step 2: Run targeted tests**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_sst_graph_builder snn3dexp.tests.test_nmc_stack_analysis -v`
- Expected: PASS

### Task 5: 跑扩展回归、编译与 full_3d smoke

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Run expanded regression**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_memory_address_layout snn3dexp.tests.test_synapse_home_stack_runtime snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_platform_builder snn3dexp.tests.test_sst_graph_builder snn3dexp.tests.test_nmc_stack_analysis snn3dexp.tests.test_cpp_traffic_mem_workload_contract snn3dexp.tests.test_run_case -v`

**Step 2: Compile SnnDL**
- Run: `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`

**Step 3: Run real smoke**
- Run: `cd "/home/xgy/remote" && python3 -m snn3dexp.tools.run_case full_3d --run-tag task19_phase2_traffic_driven_semantic_smoke --sst-smoke --stop-at 250ns`
- Expected:
  - smoke PASS
  - `sst_stats.csv` 中出现新的 `traffic_semantic_*` counters
  - `processing_reports` 同时包含 traffic semantic demand 与 semantic region issued counters
  - `route_memory_joint_summary.json` 暴露 backlog / issued 对照

**Step 4: Append progress log**
- 在 `TECH_PROGRESS.md` 末尾追加：
  - 代码改动与文件路径
  - red/green 测试命令
  - 编译命令
  - smoke 产物路径
  - traffic-driven semantic runtime 的关键结果与 backlog 观察
