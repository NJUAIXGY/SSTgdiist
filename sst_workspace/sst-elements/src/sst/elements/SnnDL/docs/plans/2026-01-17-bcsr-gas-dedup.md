# BCSR 与 GAS 去重：去除重复优化，仅保留 GAS 作为优化引擎（实施方案）

**目标（必须达成）**

- `exec_mode=gas`（window/GAS 路径）下：不再启用任何 “BCSR 级别的优化”（rowIndex cache/prefetch、block cache、populate 等），避免与 GAS/window 的聚合/调度形成双重优化，从而使实验结论可明确归因到 GAS。
- 全局 Step 同步控制器属于 platform/stimulus 域：只负责 step 的开始/结束/停止条件，不属于 GAS/优化链路。

---

## 背景：为何必须去除重复优化

当前实现中，BCSR 与 GAS 之间存在“优化重复”：

- **BCSR 侧**（synapse/weights）：rowIndex cache/prefetch、block cache、populate（dense cache）、以及部分 inflight 合并策略。
- **GAS 侧**（GatherBufferIF/window）：对 StandardMem 读请求做窗口聚合、合并、限流与 SRAM 缓存。

这会导致在 `gas` 路径下同时存在 BCSR 优化与 GAS 优化，使实验数据难以回答“创新点来自 GAS 还是 BCSR 子系统”。

我们的实验也验证了 BCSR 优化本身很强（尤其对 non-window baseline），因此必须在 `gas` 路径中禁用 BCSR 级优化以避免贡献混叠。

---

## 设计原则（边界）

1. **Step 同步/停止条件（platform/stimulus）**
   - 不做任何访存优化；
   - 不关心 BCSR/GAS；只对 step 边界做协调。

2. **GAS/window（synapse/gas + GatherBufferIF）**
   - 唯一“可归因”的优化引擎：窗口聚合、合并、限流、SRAM 暂存、阶段推进等。

3. **BCSR 格式层（synapse/weights）**
   - 在 `exec_mode=gas` 下只保留格式语义（rowptr/colidx/blockdata 的地址/解析）；不做 cache/prefetch/populate。
   - 仍允许在窗口内做必要的 inflight 合并（按“真实读请求”计数）以保证 window-read 的 budget/outstanding 口径正确并确保推进（这是 window-read 的正确性/推进约束，不作为“BCSR 级优化”对外宣称）。

---

## 实施方案（Phase1：先保证结论可归因）

### 变更 1：gas 路径禁用 BCSR 级优化（配置层）

在模板装配时（`sst_dram_si/mesh_template/build.py`）：

- 当 `is_gas==True` 且启用 BCSR（`enable_bcsr`）时，强制：
  - `bcsr_row_index_cache_cap=0`
  - `bcsr_row_index_cache_auto_fit=0`
  - `bcsr_row_index_prefetch_mode="off"`
  - `bcsr_block_cache_cap=0`
  - `bcsr_block_cache_auto_tune=0`
  - `bcsr_populate_weight_cache_enable=0`
  - 并强制保持（window-read 推进所需）：
    - `bcsr_colidx_inflight_coalesce_enable=1`
    - `bcsr_block_inflight_coalesce_enable=1`

**说明**

- 这会让 `bcsr_opt_level` 在 `gas` 路径中不再影响关键指标（允许轻微漂移），从而保证结论只归因于 GAS/window。

### 验收（DoD）

在 `l1_enable=0`、同 seed 下：

1. `exec_mode=gas`：分别设置 `MESH_BCSR_OPT_LEVEL=none/index_only/full` 跑 2 次（`MESH_MAX_STEPS=1`，`fraction=0.01`），对比：
   - `memory_bytes/memory_requests/cycle_cost/wall` 应基本一致（允许轻微漂移）。
2. `exec_mode=naive_raw`：保持 baseline 行为不变（仍可作为 “无 GAS/window” 的对照）。

---

## Phase2（后续可选）：更彻底的“优化归属硬化”

若后续仍认为 “window 内 inflight 合并” 也应完全归入 GAS 域（而不是留在 weights）：

- 引入一个 window 级的通用 Read-Deduper（按 addr/size 去重）作为 synapse/gas 子系统；
- weights 仅表达“需要读哪些地址”；去重/预算/限流全部由 GAS 负责；
- 以此彻底消除任何可能被理解为“BCSR 优化”的逻辑残留。

该阶段属于结构性改动，需在 Phase1 稳定后再推进，并要求 10us/100us 回归与对比实验重新跑齐。

