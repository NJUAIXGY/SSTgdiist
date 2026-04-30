# snn3dexp Home-Stack Semantic Address Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不重写现有 `memHierarchy` 拓扑的前提下，把 `snn3dexp/` 的 `HBM-like shared stack` 升级为“语义地址空间型” home-stack 建模，使 `processing node -> home stack` 不再只是单一 `base_addr`，而是显式区分 `metadata_lookup`、`synapse_gather`、`sparse_window_stream`、`state_writeback` 四类地址区域，并把该契约下沉到 Python 平台摘要、SST object graph 参数与最小 C++ workload contract。

**Architecture:** 第一阶段只做最小闭环，不改变 `PE -> standardInterface -> hbm_bus -> memctrl -> backend` 结构，也不立即重写真实业务流量生成器。核心升级点是新增 `stack semantic region layout`，让每个 home stack 按固定比例切成四个语义 region，并在每个 region 内为每个 node 分配稳定 slot；随后把这些地址下沉到 `processing core params`、`synapse source descriptors`、`platform summary` 和分析脚本中。C++ 侧首轮只要求 `TrafficWorkload` 能读到这些新增参数，为后续真实语义请求生成留出接口。

**Tech Stack:** Python 3、`unittest`、SST Python object graph、SnnDL C++17、`memHierarchy`、`snn3dexp/`

---

## Current Alignment

- 已有 `HBM-like shared stack` builder：
  - `snn3dexp/memory/hbm_stack.py`
  - `snn3dexp/platform/sst_graph.py`
- 已有 `monolithic-like` memory proxy，需要跟随接口对齐：
  - `snn3dexp/memory/monolithic_proxy.py`
- 已有 runtime/summary smoke 闭环，但 memory 语义仍然只暴露单一 `base_addr`
- 已有 joint analysis 中的粗粒度语义推断：
  - `metadata_lookup_reads`
  - `synapse_gather_reads`
  - `sparse_window_streams`
- 已有若干 contract tests，可直接扩展，不需要另起一套并行 harness

## Design Decisions

- 采用方案 `B: 语义地址空间型`
- 保持现有总线/控制器/backend 拓扑不变
- 每个 stack 划分四个 region：
  - `metadata`
  - `gather`
  - `stream`
  - `writeback`
- 默认 `1 MiB stack_region_bytes` 按 `1:10:4:1` 比例分配：
  - `64 KiB metadata`
  - `640 KiB gather`
  - `256 KiB stream`
  - `64 KiB writeback`
- 每个 region 内按 `home-slot` 切分 node slot，slot 必须对齐 `channel_interleave_bytes`
- 第一阶段真实启用的语义：
  - `metadata_lookup`
  - `synapse_gather`
- 第一阶段只保留接口和摘要，不强制真实发流：
  - `sparse_window_stream`
  - `state_writeback`

## Non-Goals

- 不重写 `memHierarchy` object graph
- 不在这一轮直接实现真实 `home-stack` 业务流量发射器
- 不改 legacy 2D case 的行为
- 不做 git 提交或分支操作

### Task 1: 建立 stack semantic region layout contract

**Files:**
- Modify: `snn3dexp/memory/hbm_stack.py`
- Modify: `snn3dexp/memory/monolithic_proxy.py`
- Test: `snn3dexp/tests/test_synapse_home_stack_runtime.py`
- Test: `snn3dexp/tests/test_synapse_memory_semantics.py`
- Create: `snn3dexp/tests/test_memory_address_layout.py`

**Step 1: Write the failing test**
- 为 `HBM-like` 和 `monolithic-like` memory bindings 锁定以下字段：
  - `metadata_base_addr`
  - `gather_base_addr`
  - `stream_base_addr`
  - `writeback_base_addr`
  - `slot_id`
  - `slot_bytes`
  - `stack_region_layout`
- 锁定四个 region 起始地址单调递增，且满足对齐约束
- 锁定 `build_synapse_source_descriptors()` 必须把四类 base addr 一并暴露

**Step 2: Run test to verify it fails**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_memory_address_layout snn3dexp.tests.test_synapse_home_stack_runtime -v`
- Expected: FAIL，当前只存在单一 `base_addr`

**Step 3: Write minimal implementation**
- 在 `hbm_stack.py` 中新增：
  - region size/offset 计算 helper
  - slot 对齐 helper
  - semantic binding payload builder
- 在 `monolithic_proxy.py` 中复用同一 contract，先保持 proxy 语义一致

**Step 4: Run tests to verify they pass**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_memory_address_layout snn3dexp.tests.test_synapse_home_stack_runtime -v`
- Expected: PASS

### Task 2: 把 semantic addresses 下沉到 platform summary 与 SST object graph

**Files:**
- Modify: `snn3dexp/platform/sst_graph.py`
- Modify: `snn3dexp/platform/build_system.py`
- Test: `snn3dexp/tests/test_platform_builder.py`
- Create: `snn3dexp/tests/test_sst_graph_semantic_memory.py`

**Step 1: Write the failing test**
- 锁定 `processing_nodes[*].subcomponents.core0.params` 包含：
  - `metadata_base_addr`
  - `gather_base_addr`
  - `stream_base_addr`
  - `writeback_base_addr`
  - `memory_semantic_slot_bytes`
- 锁定 `platform_summary["memory"]` 暴露：
  - `semantic_addressing_enabled`
  - `stack_region_bytes`
  - `region_layout`
  - `semantic_slot_bytes`

**Step 2: Run test to verify it fails**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_platform_builder snn3dexp.tests.test_sst_graph_semantic_memory -v`
- Expected: FAIL，当前摘要和 object graph 尚未下沉这些参数

**Step 3: Write minimal implementation**
- 更新 `sst_graph.py`，把 semantic address params 传到 `core0`
- 更新 `build_system.py`，把 semantic region layout 汇总进 `platform summary`

**Step 4: Run tests to verify they pass**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_platform_builder snn3dexp.tests.test_sst_graph_semantic_memory -v`
- Expected: PASS

### Task 3: 升级 analysis，让 memory summary 读懂语义地址契约

**Files:**
- Modify: `snn3dexp/tools/analyze_route_memory_joint.py`
- Modify: `snn3dexp/tools/analyze_stack_nmc.py`
- Modify: `snn3dexp/tests/test_synapse_memory_semantics.py`
- Modify: `snn3dexp/tests/test_synapse_home_stack_runtime.py`

**Step 1: Write the failing test**
- 锁定 analysis summary 中新增：
  - `memory.semantic_region_layout`
  - `memory.semantic_slot_bytes`
  - `memory.synapse_semantics.metadata_lookup_region_reads`
  - `memory.synapse_semantics.synapse_gather_region_reads`
- 对 legacy case 保持兼容，缺字段时回退到 `0` 或空结构

**Step 2: Run test to verify it fails**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_synapse_home_stack_runtime -v`
- Expected: FAIL，当前 summary 还只基于总请求数推断

**Step 3: Write minimal implementation**
- 在 analysis 中读取 `synapse_sources` / `platform summary` 中的 semantic layout
- 保持现有统计项不删，只新增更显式的 region-level 解释

**Step 4: Run tests to verify they pass**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_synapse_home_stack_runtime -v`
- Expected: PASS

### Task 4: 对齐最小 C++ workload contract

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.cc`
- Test: `snn3dexp/tests/test_cpp_traffic_mem_workload_contract.py`

**Step 1: Write the failing test**
- 锁定 `TrafficWorkload.cc` 会读取：
  - `metadata_base_addr`
  - `gather_base_addr`
  - `stream_base_addr`
  - `writeback_base_addr`
- 锁定缺省回退到已有 `base_addr`

**Step 2: Run test to verify it fails**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_cpp_traffic_mem_workload_contract -v`
- Expected: FAIL，当前实现只读取单一 `base_addr`

**Step 3: Write minimal implementation**
- 在 `TrafficWorkload.cc` 的 config 读取阶段增加四类地址参数
- 第一阶段先只做参数吸收与内部 config 保存，不修改已有请求生成行为

**Step 4: Run tests to verify they pass**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_cpp_traffic_mem_workload_contract -v`
- Expected: PASS

### Task 5: 运行 focused verification，并追加技术进度

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Run focused Python verification**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_memory_address_layout snn3dexp.tests.test_synapse_home_stack_runtime snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_platform_builder snn3dexp.tests.test_sst_graph_semantic_memory snn3dexp.tests.test_cpp_traffic_mem_workload_contract -v`

**Step 2: Run focused C++/manifest verification**
- Run: `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
- Run: `cd "/home/xgy/remote" && python3 -m snn3dexp.tools.run_case full_3d --run-tag taskX_home_stack_semantic_compose --validate-only`
- Expected:
  - Python tests PASS
  - SnnDL compile PASS
  - compose/validate 阶段能生成包含 semantic memory params 的 manifest

**Step 3: Append progress log**
- 在 `TECH_PROGRESS.md` 末尾追加：
  - 修改内容
  - 验证命令
  - 关键产物路径
  - 当前剩余缺口：
    - 真正的 `metadata/gather` 请求发射
    - `stream/writeback` 实流
    - full runtime smoke
