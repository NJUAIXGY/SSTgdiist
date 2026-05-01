# SNN SRAM Timing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 observe-only SRAM 冲突统计转成真实 stall budget，并接入 `SnnComputeCore` 与 `WeightMemorySubsystem`。

**Architecture:** 保持现有 `BankedSramModel` 为单一真源，新增“上一拍冲突导出”接口；compute/weight 两个消费者分别维护自己的 stall budget，在 clock 驱动路径上延迟状态推进与内存 issue。

**Tech Stack:** C++17、SST Element、轻量自包含测试（`g++` + `assert`）

---

### Task 1: 导出 SRAM 周期冲突预算

**Files:**
- Modify: `services/memory/sram_sim/model/BankedSramModel.h`
- Modify: `services/memory/sram_sim/model/BankedSramModel.cc`
- Test: `tests/test_banked_sram_model.cc`

**Step 1: Write the failing test**

- 增加测试覆盖：同拍同 bank 超过 port 数时，`consumeLastCyclePredictedExtraCycles()` 返回非零；跨 bank 访问时返回 0。

**Step 2: Run test to verify it fails**

- Run: `g++ -std=c++17 -I . tests/test_banked_sram_model.cc services/memory/sram_sim/model/BankedSramModel.cc -o /tmp/test_banked_sram_model`
- Expected: 编译失败，提示缺少新接口。

**Step 3: Write minimal implementation**

- 在 `flushCurrentCycle_()` 保存上一拍新增的冲突 tick / extra cycles；
- 提供 consume 接口，读取后清零。

**Step 4: Run test to verify it passes**

- Run: `/tmp/test_banked_sram_model`
- Expected: 退出码 0。

### Task 2: 接入 compute state SRAM stall budget

**Files:**
- Modify: `compute/SnnComputeCore.h`
- Modify: `compute/SnnComputeCore.cc`

**Step 1: Write the failing test**

- 复用 `test_banked_sram_model.cc` 的导出接口作为依赖保障；compute 本阶段用编译验证。

**Step 2: Write minimal implementation**

- 新增 `state_sram_stall_budget_`；
- 在 `onClockTick()` 消费上一拍冲突预算；
- 在 `endCycle()` / `endCycleCandidates()` / `hasWork()` 中让 stall budget 生效。

**Step 3: Run compile check**

- Run: `g++ -std=c++17 -I . -c compute/SnnComputeCore.cc -o /tmp/test_snn_compute_core.o`
- Expected: 编译通过。

### Task 3: 接入 weight SRAM stall budget

**Files:**
- Modify: `services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `services/synapse/weights/WeightMemorySubsystem.cc`

**Step 1: Write minimal implementation**

- 新增 `weight_sram_stall_budget_cycles_`；
- 在 `onClockTick()` 消费 idx/l0 的上一拍冲突预算；
- stall 时暂停 prefetch / deferred issue / direct drain，但不影响已有异步回包处理。

**Step 2: Run compile check**

- Run: `g++ -std=c++17 -I . -c services/synapse/weights/WeightMemorySubsystem.cc -o /tmp/test_weight_mem.o`
- Expected: 编译通过。

### Task 4: 文档与回归验证

**Files:**
- Modify: `README.md`
- Modify: `TECH_PROGRESS.md`

**Step 1: Update docs**

- 说明 `SRAM_MODEL_ENABLE` 不再只是 observe-only；
- 记录新的 stall-budget 行为与验证命令。

**Step 2: Run focused verification**

- Run: `g++ -std=c++17 -I . tests/test_banked_sram_model.cc services/memory/sram_sim/model/BankedSramModel.cc -o /tmp/test_banked_sram_model && /tmp/test_banked_sram_model`
- Run: `g++ -std=c++17 -I . -c compute/SnnComputeCore.cc -o /tmp/test_snn_compute_core.o`
- Run: `g++ -std=c++17 -I . -c services/synapse/weights/WeightMemorySubsystem.cc -o /tmp/test_weight_mem.o`
- Expected: 全部通过。
