# SNN SRAM Timing Design

**Goal:** 将现有 observe-only 的 SRAM 统计模型升级为会影响 SNN 执行时序的分层代理模型第一阶段，实现 `state SRAM` 与 `weight SRAM` 的真实 stall 反馈。

## 背景

当前 `services/memory/sram_sim/model/BankedSramModel` 只负责记录 bank conflict、predicted extra cycles 与容量峰值，不会把冲突成本反馈回 `compute/SnnComputeCore` 或 `services/synapse/weights/WeightMemorySubsystem` 的执行路径。

这会导致：

- `core_state_sram_predicted_extra_cycles_total` 只能用于离线解释，不能改变仿真执行时序；
- `weight_idx_sram_*` / `weight_l0_sram_*` 只能用于观测，不能反压权重 issue / refill / callback 路径；
- mesh 配置已经能把 SRAM 参数传入 `SnnDL`，但模型仍停留在“统计器”层。

## 第一阶段目标

第一阶段不直接重写成逐请求、逐 bank 的完整本地 SRAM 请求队列，而是做一个**最小侵入的真实时序闭环**：

1. `BankedSramModel` 在每次 `flushCurrentCycle_()` 后导出“上一拍新增的 predicted extra cycles”；
2. `DefaultSnnComputeCore` 把这部分 extra cycles 变成 `state_sram_stall_budget`，stall 时跳过 `endCycle()` 的状态推进与 fire 判定；
3. `WeightMemorySubsystem` 把 `idx/l0` 的 extra cycles 变成 `weight_sram_stall_budget`，stall 时暂停新的 issue / prefetch / deferred drain；
4. 保留当前统计字段与配置接口，避免破坏现有脚本与统计汇总。

## 设计原则

- **KISS**：先把“统计 -> 时序”闭环打通，不一次性引入新的请求结构体或替换策略框架。
- **兼容优先**：保留 `BankedSramModel` 原有统计语义与 mesh 配置字段；旧实验在关闭 SRAM 模型时行为不变。
- **边界清晰**：不把 SNN 业务语义塞回 `services/memory/`；compute 与 weight 只消费 stall budget。
- **可验证**：先为 `BankedSramModel` 增加独立测试，验证冲突周期导出行为，再接入上层。

## 非目标

- 本阶段不实现完整的本地 SRAM miss/refill 请求队列；
- 本阶段不引入新的替换策略系统；
- 本阶段不新增多时钟域或功耗聚合器；
- 本阶段不改变 DRAM / StandardMem 的接口边界。

## 预计改动点

- `services/memory/sram_sim/model/BankedSramModel.{h,cc}`
- `compute/SnnComputeCore.{h,cc}`
- `services/synapse/weights/WeightMemorySubsystem.{h,cc}`
- `tests/test_banked_sram_model.cc`

## 后续阶段

第二阶段再考虑：

- 将 weight L0 从“实验缓存统计”升级为显式 local cache 结构；
- 将 state SRAM 从“整拍 stall”升级为更细的 phase / vector chunk 粒度；
- 暴露 `*_enforced_stall_cycles_total` 到 PE 聚合统计链。
