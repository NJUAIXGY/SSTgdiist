# Local Storage Phase A Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 SnnDL 落地 Phase A 的片上本地存储平台骨架，先打通 `LocalStorageHierarchyController`、`MultiCorePE` 装配与参数/对象注册，保持默认关闭兼容。

**Architecture:** 新增 `services/local_storage/` 平台层，定义统一对象类型与 controller；`MultiCorePE` 在 `local_storage_enable=1` 且 `workload_impl=snn` 时构造 per-PE controller，并基于新参数与旧参数 alias 注册 `state/weight/activation/accumulator/register file` 对象。第一阶段不改变现有 compute/weight/activation/accumulator 行为，只提供稳定的对象注册、统计与后续迁移挂点。

**Tech Stack:** C++17、SST Element、轻量自包含测试（`g++` + `assert`）

---

### Task 1: 新增 local storage 平台类型与控制器骨架

**Files:**
- Create: `services/local_storage/LocalStorageTypes.h`
- Create: `services/local_storage/LocalStorageHierarchyController.h`
- Create: `services/local_storage/LocalStorageHierarchyController.cc`
- Test: `tests/test_local_storage_hierarchy.cc`

**Step 1: Write the failing test**

- 新增 `tests/test_local_storage_hierarchy.cc`，覆盖：
  - controller 可注册对象；
  - 重名对象拒绝注册；
  - 统计快照返回已注册对象数、enabled 对象数、总容量字节数。

**Step 2: Run test to verify it fails**

- Run: `g++ -std=c++17 -I . tests/test_local_storage_hierarchy.cc services/local_storage/LocalStorageHierarchyController.cc -o /tmp/test_local_storage_hierarchy`
- Expected: 编译失败，提示缺少新头/新实现。

**Step 3: Write minimal implementation**

- 定义对象类型、scope、配置结构、快照统计结构；
- 实现 controller 的对象注册、重名检查、基础快照。

**Step 4: Run test to verify it passes**

- Run: `/tmp/test_local_storage_hierarchy`
- Expected: 退出码 0。

### Task 2: 接入头文件编译自检

**Files:**
- Modify: `tests/test_includes.cc`
- Modify: `Makefile.am`

**Step 1: Write the failing compile check**

- 在 `tests/test_includes.cc` 引入新的 local storage public 头。

**Step 2: Run compile check to verify it fails**

- Run: `cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make test-compile`
- Expected: 编译失败，提示 include/Makefile 未覆盖新头。

**Step 3: Write minimal implementation**

- 将新增头/源文件纳入 `Makefile.am` 的 `libSnnDL_la_SOURCES`；
- 保证 `test_includes.cc` 能独立编译。

**Step 4: Run compile check to verify it passes**

- Run: `cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make test-compile`
- Expected: 编译通过。

### Task 3: 为 MultiCorePE 增加 local storage 装配与对象注册

**Files:**
- Create: `api/ILocalStorageProvider.h`
- Modify: `components/multicore/MultiCorePEConfig.h`
- Modify: `components/multicore/MultiCorePEConfig.cc`
- Modify: `components/MultiCorePE.h`
- Modify: `components/MultiCorePE.cc`

**Step 1: Write the failing test**

- 扩展 `tests/test_local_storage_hierarchy.cc`，新增一个“按配置注册默认对象”的纯 C++ 辅助测试，验证：
  - `local_storage_enable=1` 时可创建 controller；
  - `state/weight/activation/accumulator/register file` 对象命名规则与计数正确；
  - 旧参数 alias 可映射出 `state_store` / `weight_idx_store` / `weight_value_store` 容量。

**Step 2: Run test to verify it fails**

- Run: `g++ -std=c++17 -I . tests/test_local_storage_hierarchy.cc services/local_storage/LocalStorageHierarchyController.cc -o /tmp/test_local_storage_hierarchy`
- Expected: 测试失败，提示缺少默认对象注册辅助逻辑。

**Step 3: Write minimal implementation**

- 新增 `ILocalStorageProvider`；
- 在 `MultiCorePEConfig` 解析 `local_storage_enable` 与第一批 `ls_*` 参数；
- 在 `MultiCorePE` 构造时按 `workload_impl=snn` 装配 per-PE controller；
- 注册默认对象：
  - `activation_ingress_store`
  - `weight_idx_store`
  - `weight_value_store`
  - `state_store[c]`
  - `activation_core_queue[c]`
  - `accumulator_store[c]`
  - `register_file[c]`

**Step 4: Run focused compile checks**

- Run: `g++ -std=c++17 -I . -c components/multicore/MultiCorePEConfig.cc -o /tmp/test_multicore_cfg.o`
- Run: `g++ -std=c++17 -I . -c components/MultiCorePE.cc -o /tmp/test_multicore_pe.o`
- Expected: 编译通过。

### Task 4: 增加基础可观测性并更新进展

**Files:**
- Modify: `components/MultiCorePE.h`
- Modify: `components/MultiCorePE.cc`
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Write minimal implementation**

- 为 local storage 增加第一批 PE 聚合统计：
  - `ls_objects_registered_total`
  - `ls_objects_enabled_total`
  - `ls_capacity_bytes_total`
  - `ls_queue_slots_total`
- 在 `finish()` 落盘 snapshot；
- 追加 `TECH_PROGRESS.md` 记录本批实现与验证命令。

**Step 2: Run focused verification**

- Run: `g++ -std=c++17 -I . tests/test_local_storage_hierarchy.cc services/local_storage/LocalStorageHierarchyController.cc -o /tmp/test_local_storage_hierarchy && /tmp/test_local_storage_hierarchy`
- Run: `cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make test-compile`
- Run: `g++ -std=c++17 -I . -c components/multicore/MultiCorePEConfig.cc -o /tmp/test_multicore_cfg.o`
- Run: `g++ -std=c++17 -I . -c components/MultiCorePE.cc -o /tmp/test_multicore_pe.o`
- Expected: 全部通过。

### Task 5: 为后续迁移预留 provider 挂点

**Files:**
- Modify: `tests/test_includes.cc`
- Modify: `components/MultiCorePE.h`

**Step 1: Write minimal implementation**

- `MultiCorePE` 暴露 `ILocalStorageProvider`；
- 仅提供 getter，不在本批强行改 `SnnPESubComponent` / `SnnComputeCore` / `WeightMemorySubsystem`。

**Step 2: Run compile check**

- Run: `cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make test-compile`
- Expected: 编译通过。

### Notes

- 本计划不包含 git 操作；仓库策略要求无明确批准时不执行提交/分支命令。
- 本批目标是“平台骨架 + 装配 + 统计 + 兼容挂点”，不是一次性迁完 `state/weight/activation/accumulator` 的运行时数据通路。
