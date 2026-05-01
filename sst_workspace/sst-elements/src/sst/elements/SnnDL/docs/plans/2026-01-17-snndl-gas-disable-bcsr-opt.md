# SnnDL：gas 路径禁用 BCSR 级优化（在 SnnDL 内部强制，避免模板漂移）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将 “`exec_mode=gas` 下 BCSR 级 cache/prefetch/populate 等优化全部禁用” 的约束从模板层下沉到 SnnDL 代码中，确保结论可归因于 GAS/window，避免外部脚本/模板漂移导致口径不一致。

**Architecture:** 在配置注入点（`workload=snn` 与 legacy `control/SnnPESubComponent` 两条链路）统一做一次 BCSR 配置归一化：当启用 GAS/window 时，强制关闭 rowIndex cache/prefetch、block cache、populate；同时保留 window-read 推进所需的 inflight 合并（按真实读请求计数）。

**Tech Stack:** C++17（SST elements/SnnDL）、现有 params/find 配置注入、`WeightMemorySubsystem::OrchestratorConfig`。

---

## 背景与约束

- 全局 Step 同步控制器属于 platform/stimulus 域（不属于 GAS），本任务不改动 step 控制器语义。
- 目标是消除 “BCSR 优化与 GAS/window 重复优化” 的贡献混叠：
  - 对外宣称：`gas` 路径的优化只归因 GAS/window；
  - BCSR 仅保留格式/地址映射语义（rowptr/colidx/blockdata）。
- `use_event_weight_fallback` 仍绝对禁止（不涉及本任务实现）。

---

## Task 1：梳理并统一 BCSR 配置归一化入口

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`

**Step 1: 添加一个小的本地 helper（避免双处复制规则）**

- 在一个合适的 `.cc` 内部（优先放 `api/` 不现实：这里只是本地配置归一化逻辑），新增静态函数：
  - 输入：`bool gas_window_mode`, `bool window_read_enable`, `WeightMemorySubsystem::OrchestratorConfig& ocfg`, `SST::Output* log`, `bool log_once`
  - 行为：
    - 当 `(gas_window_mode && window_read_enable)` 为真时，强制：
      - `ocfg.bcsr_row_index_prefetch_mode = "off"`
      - `ocfg.bcsr_block_cache_auto_tune = false`
      - `ocfg.bcsr_block_cache_max_bytes = 0`
      - `ocfg.bcsr_populate_weight_cache_enable = false`
      - （如存在 rowIndex cache cap 参数，则也置 0；若该 cap 由别处配置，则仅在 WMS 内部对应字段一并清零）
      - `ocfg.bcsr_colidx_inflight_coalesce_enable = true`
      - `ocfg.bcsr_block_inflight_coalesce_enable = true`
    - 仅在 core0/core0 + verbose>=1 时输出一次提示（避免 log 噪声/性能影响）。

**Step 2: 在 `SnnWorkload::configureWeightSubsystem_` 注入点调用 helper**

- 位置：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`（`ocfg` 填充完成后，`wms->configureOrchestrator(...)` 前）

**Step 3: 在 legacy `SnnPESubComponent` 注入点调用 helper**

- 位置：`sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`（构造 `ocfg` 并 `mem->configureOrchestrator(...)` 前）

**Step 4: 编译验证**

Run:
```bash
cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4
```
Expected: PASS

---

## Task 2：为 “gas 下禁用 BCSR 级优化” 增加可观察性（不增加热路径日志）

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/README.md`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/docs/SUBSYSTEM_MODULARIZATION_ROADMAP.md`（如已有相关小节则补一行即可）

**Step 1: README 说明边界**

- 明确写出：
  - `gas/window` 下 BCSR 仅作为格式，cache/prefetch/populate 由 SnnDL 强制关闭；
  - inflight 合并是 window-read 推进/预算口径所需，不作为对外宣称的 “BCSR 优化”。

**Step 2: 文档添加验收口径**

- 给出最小验证命令（见 Task 3）。

---

## Task 3：回归验证（10us/100us + opt-level 不敏感）

**Files:**
- No code changes required (test only)

**Step 1: 重新安装并跑 gas（确保使用最新 libSnnDL.so）**

Run:
```bash
cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4 && make install
```

**Step 2: 验证 gas 对 opt-level 不敏感**

Run:
```bash
cd "sst_dram_si" && \
MESH_MAX_STEPS=1 MESH_STEP_ACTIVATION_FRACTION=0.01 MESH_STEP_ACTIVATION_FANOUT=256 MESH_STEP_ACTIVATION_SEED=314159 \
MESH_ALLOW_ZERO_FIRING_LONG=1 MESH_GLOBAL_STEP_DONE_POLICY=drain \
for opt in none index_only full; do MESH_BCSR_OPT_LEVEL="$opt" ./tools/run_mesh_exec_mode_compare_with_time.sh gas; done
```

Expected:
- 三次 run `essential_summary_mesh.json` 的 `memory_requests/memory_bytes/cycle_cost` 基本一致（允许轻微漂移）。

**Step 3: 10us/100us 回归**

Run:
```bash
cd "sst_dram_si" && MESH_MAX_STEPS=2 ./tools/run_mesh_with_time.sh
```
Expected: validate PASS

---

## Task 4（可选，需主人确认）：把“禁用规则”从模板层移除，避免双重实现

**Files:**
- Modify: `sst_dram_si/mesh_template/build.py`

**Rationale:**
- 若 SnnDL 内部已强制 `gas/window` 禁用 BCSR 级优化，则模板层重复禁用会造成双实现/双口径维护成本。

**Step 1: 移除模板中的 is_gas 强制覆盖块**
- 删除/缩减 `if is_gas: ...` 对 bcsr 参数的硬覆盖（保留必要的 step 同步与 GatherBufferIF 参数）。

**Step 2: 复跑 Task 3 的 opt-level 不敏感验证**
- 证明 “无需模板也能保证 gas 归因干净”。

---

## Done Definition（完成判定）

- `gas/window` 下：BCSR 级 cache/prefetch/populate 在 SnnDL 内部被强制关闭；`MESH_BCSR_OPT_LEVEL` 不再影响 `gas` 的关键统计（允许轻微漂移）。
- 文档更新到位：weights/README + roadmap 中有明确边界与验收命令。
- 10us/100us 回归通过。

