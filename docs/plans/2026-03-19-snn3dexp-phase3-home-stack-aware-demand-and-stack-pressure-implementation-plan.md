# snn3dexp Phase3 Home-Stack-Aware Demand And Stack Pressure Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 `traffic_mem` 闭环从 packet-driven 近似升级为 `home-stack-aware` 的语义需求模型，并把 `HBM-like NMC` 分析升级为可解释 `issue efficiency / backlog ratio / service deficit` 的 stack-pressure 分析器。

**Architecture:** 保持隔离边界不变，不改主线 Python harness，也不扩展公共 C++ 接口。`TrafficWorkload` 直接基于 `ISynapseRoute::computeFanout()` 和本地 HBM-like home-stack 规则生成更精确的 semantic demand；`analyze_stack_nmc.py` 与 `analyze_route_memory_joint.py` 在现有 JSON 合同之上追加 pressure 指标与热点 stack 解释字段。

**Tech Stack:** C++17、SST/SnnDL、Python 3、`unittest`

---

**Execution rules**
- 只在 `snn3dexp/` 与 `SnnDL/services/workload/traffic/`、分析脚本相关文件上做最小修改
- 先红测再实现，严格遵守 TDD
- 不做任何 git 写操作
- 完成后必须追加 `TECH_PROGRESS.md`

### Task 1: 锁定 home-stack-aware semantic demand 合同

**Files:**
- Modify: `snn3dexp/tests/test_cpp_traffic_mem_workload_contract.py`
- Modify: `snn3dexp/tests/test_run_case.py`

**Step 1: Write the failing tests**
- `test_cpp_traffic_mem_workload_contract.py` 锁定：
  - `TrafficWorkload::SemanticMemoryDemand` 出现 home-stack-aware gather/stream 子计数
  - `TrafficWorkload.cc` 显式调用 `computeFanout(...)`
  - `TrafficWorkload.cc` 具备 HBM-like `home_stack_for_node` / cross-tier 分类辅助逻辑
  - `getStatistics()` 导出新增 `traffic_semantic_*` 分类统计
- `test_run_case.py` 锁定：
  - `_parse_processing_stats()` 会保留新增的 `traffic_semantic_same_home_*`、`traffic_semantic_remote_home_*`、`traffic_semantic_cross_tier_*` 统计项

**Step 2: Run tests to verify they fail**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_cpp_traffic_mem_workload_contract snn3dexp.tests.test_run_case -v`
- Expected: FAIL，因为新增合同和统计字段尚不存在。

**Step 3: Write minimal implementation**
- 在 `TrafficWorkload` 中新增最小 helper：
  - mesh shape 解析
  - HBM-like `home_stack_for_node`
  - source/destination `same_home / remote_home / cross_tier`
- 对每个 emitted `pre` 调 `synapse_route_->computeFanout(...)`
- 用 `dest_node` 分布生成更真实的 `gather/stream/writeback` demand 子计数
- 保持原 totals 语义兼容，同时追加更细的统计
- 更新 `run_case.py::_parse_processing_stats()` 的保留字段列表

**Step 4: Run tests to verify they pass**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_cpp_traffic_mem_workload_contract snn3dexp.tests.test_run_case -v`
- Expected: PASS

### Task 2: 锁定 stack-level NMC pressure 分析合同

**Files:**
- Modify: `snn3dexp/tests/test_nmc_stack_analysis.py`
- Modify: `snn3dexp/tests/test_synapse_memory_semantics.py`

**Step 1: Write the failing tests**
- `test_nmc_stack_analysis.py` 锁定：
  - totals/stacks 都包含 `metadata/gather/stream/writeback` 的：
    - `*_issue_efficiency`
    - `*_backlog`
    - `*_backlog_ratio`
    - `*_service_deficit`
  - 总结层出现：
    - `most_pressured_stack_id`
    - `most_pressured_stack_service_deficit`
    - `stack_memory_request_skew`
- `test_synapse_memory_semantics.py` 锁定：
  - `route_memory_joint_summary["memory"]["traffic_driven_runtime"]` 追加 region-level efficiency / deficit 字段
  - joint runtime 能指出 `most_pressured_region`

**Step 2: Run tests to verify they fail**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_nmc_stack_analysis snn3dexp.tests.test_synapse_memory_semantics -v`
- Expected: FAIL，因为 pressure 指标还未输出。

**Step 3: Write minimal implementation**
- 在 `analyze_stack_nmc.py` 中：
  - 统一抽象 per-region demand/issued/backlog/efficiency/deficit 计算
  - 对每个 stack 与 totals 输出上述指标
  - 增加 hottest stack / skew / service deficit 汇总
- 在 `analyze_route_memory_joint.py` 中：
  - 为 `traffic_driven_runtime` 增加 per-region pressure 字段
  - 输出 `most_pressured_region`

**Step 4: Run tests to verify they pass**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_nmc_stack_analysis snn3dexp.tests.test_synapse_memory_semantics -v`
- Expected: PASS

### Task 3: Fresh verification and experiment closure

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Run targeted regression**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_cpp_traffic_mem_workload_contract snn3dexp.tests.test_run_case snn3dexp.tests.test_nmc_stack_analysis snn3dexp.tests.test_synapse_memory_semantics -v`
- Expected: PASS

**Step 2: Run expanded regression**
- Run: `cd "/home/xgy/remote" && python3 -m unittest snn3dexp.tests.test_memory_address_layout snn3dexp.tests.test_synapse_home_stack_runtime snn3dexp.tests.test_synapse_memory_semantics snn3dexp.tests.test_platform_builder snn3dexp.tests.test_sst_graph_builder snn3dexp.tests.test_nmc_stack_analysis snn3dexp.tests.test_cpp_traffic_mem_workload_contract snn3dexp.tests.test_run_case -v`
- Expected: PASS

**Step 3: Compile affected C++**
- Run: `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
- Expected: PASS

**Step 4: Run real smoke**
- Run: `cd "/home/xgy/remote" && python3 -m snn3dexp.tools.run_case full_3d --run-tag task20_phase3_home_stack_pressure_smoke --sst-smoke --stop-at 250ns`
- Expected: PASS，并产出新的 `stack_nmc_summary.json` / `route_memory_joint_summary.json`

**Step 5: Append progress log**
- 只允许在 `TECH_PROGRESS.md` 末尾追加：
  - 变更文件
  - 验证命令
  - 新指标结果
  - 下一步 TODO
