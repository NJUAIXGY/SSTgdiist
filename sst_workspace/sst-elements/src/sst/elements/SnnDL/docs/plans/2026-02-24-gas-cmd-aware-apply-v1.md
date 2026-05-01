# 2026-02-24 GAS CMD-aware Apply v1（实验隔离方案）

## 背景与目标

当前 GAS Apply 的主线策略为：
- `order`（默认）
- `bank_rr_row_sticky_age`
- `dram_aware_v1`（探索）

为验证“命令感知发射”是否能在不改变 GAS 语义的前提下改善 Apply 阶段，新增实验策略：
- `apply_issue_policy=cmd_aware_v1`

本策略只改变 **Apply 发射顺序**，不改变 Gather/Apply/Scatter 阶段语义，不改变请求功能正确性口径。

---

## 严格隔离边界

`cmd_aware_v1` 必须满足以下隔离要求：

1. 默认关闭：不修改主线默认行为（`order`）。
2. 只在实验开关下启用：
   - `MESH_EXPERIMENTAL_ENABLE=1`
   - `MESH_GAS_APPLY_ISSUE_POLICY=cmd_aware_v1`
3. 不改 merge 语义：
   - 仍由现有 granule 构建路径（gap/row-window）产生候选；
   - `cmd_aware_v1` 仅在候选队列中做发射次序选择。
4. 回滚简单：将 `apply_issue_policy` 改回 `order` 或 `bank_rr_row_sticky_age` 即可。

---

## v1 机制（Shadow Command Model）

每个 bank 维护轻量影子状态：
- `open_row` / `open_valid`
- `busy_until_ns`

对候选 granule 计算分数：

`score = bank_busy_wait_ns + service_ns(row_hit|row_miss) + miss_penalty_ns`

其中：
- `row_hit` 由 `open_row == rowIndex(addr)` 预测；
- `service_ns` 使用固定参数，不做在线自适应；
- 若达到 `apply_age_fair_ns`，仍按老化优先，避免饥饿。

---

## 参数面（仅 cmd_aware_v1 使用）

- `apply_cmd_probe_depth`（默认 8）
- `apply_cmd_t_row_hit_ns`（默认 30）
- `apply_cmd_t_row_miss_ns`（默认 120）
- `apply_cmd_miss_penalty_ns`（默认 0）
- `apply_cmd_enable_row_locality`（默认 1）
- `apply_cmd_enable_bank_busy`（默认 1）

---

## 统计与可观测性

新增统计：
- `gas_apply_cmd_row_hit_picks`
- `gas_apply_cmd_row_miss_picks`
- `gas_apply_cmd_busy_wait_ns`

`essential_summary_mesh.json` 聚合字段：
- `gas.apply_cmd_row_hit_picks_total`
- `gas.apply_cmd_row_miss_picks_total`
- `gas.apply_cmd_busy_wait_ns_total`
- 派生：`gas.apply_cmd_row_hit_ratio`、`gas.apply_cmd_busy_wait_ns_per_turn`

---

## 对比与消融矩阵

脚本：
- `sst_dram_si/tools/run_dense_microbench_4x4_cmd_aware_ablation.sh`

注意（dense microbench 实验隔离）：
- 需要关闭 `dense_strict_cacheline` 的“强制直通覆盖”分支，否则会把 `defer_issue_until_apply` 置 0，导致 Apply 调度策略不生效。
- 当前脚本已通过 `MESH_DENSE_STRICT_CACHELINE=0` + 显式 `merge_policy=cacheline,k=0,Lmax=64` 保持 cacheline 语义，同时允许 staged Apply 调度执行。

默认变体：
1. `order_baseline`
2. `bank_rr_baseline`
3. `cmd_full`
4. `cmd_no_row_locality`
5. `cmd_no_bank_busy`
6. `cmd_flat_row_cost`

输出：
- `.../ablation_summary.tsv`

---

## 验收口径

1. 正确性：`validate_essential_summary_mesh.py` 通过（fail=0）。
2. 隔离性：默认策略不变，未显式启用时不走 `cmd_aware_v1`。
3. 可解释性：`cmd_full` 与消融变体之间，`sim_time_actual_ns` / `memctrl.bytes_est_total` 与新增 cmd 统计协同变化。
