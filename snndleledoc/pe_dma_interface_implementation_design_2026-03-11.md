# SnnDL PE 级 DMA 接口落地方案（实现设计定稿）

Date: 2026-03-11
Owner: Fufu
Status: Finalized Design
Based on: `snndleledoc/pe_dma_model_design_2026-03-10.md`

## 1. 目标与范围

本方案定义一个仅覆盖 `SNN workload` 的 PE 级共享 DMA 读调度模型，用于替代当前运行期权重窗口读取时“每核直接向 `StandardMemAccess` 发读”的无共享瓶颈模型。

Phase 1 目标：
- 建模同一 PE 内多核共享的运行期权重读带宽、引擎并行度、队列深度与阶段门控。
- 保持 `IMemoryAccess` 的纯内存语义边界，不修改 memHierarchy 或 ramulator2。
- `dma_enable=0` 时完全保持旧行为。
- 测试与实验统一落在 `snndl-thing-exp/`。

Phase 1 明确只覆盖：
- `workload_impl=snn`
- `WeightMemorySubsystem` 发起的运行期读路径
- 只建模 `read`

Phase 1 明确不覆盖：
- `stream` / `tensor` / `traffic` workload
- 初始化期 `WeightLoader` 写回
- 新的 SST Component / SubComponent
- write-side DMA、row-streaming 语义、跨 PE 共享 DMA

## 2. 当前工程现状与关键约束

当前运行时读路径为：

`WeightMemorySubsystem -> IMemoryAccess -> StandardMemAccess -> StandardMem`

当前代码中的真实插入点与约束如下：

- `WeightMemorySubsystem::issueRead_()` 是 WMS 统一发起读的收敛点，适合注入 DMA 请求封装。
- `IMemoryAccess` 是纯 `addr + bytes -> callback(bytes)` 接口，不能被扩成权重/突触语义接口。
- `StdMemEndpoint` 当前负责 `StandardMemAccess` 的装配与 GAS 控制面事件分发。
- `SnnPESubComponent::bindWorkloadRuntime_()` 会把 `IMemoryAccess*` 交给 `workload=snn` 与 `WeightMemorySubsystem`。
- `SnnPESubComponent::onGasStageEvent()` 已能稳定接收 `BeginGather / BeginApply / BeginScatter / EndScatter`。

一个必须修正的设计点：

- 不能简单把 DMA 调度放在 `MultiCorePE::clockTick()` 中做每拍 `tick()`。
- 原因是当前工程里每个 `SnnPESubComponent` 自己也注册时钟，而且实际读请求是在 core tick 内提交的。
- 如果 DMA tick 只放在 PE 侧，会天然出现“本拍后半段由其他 core 提交的请求要到下一拍才可见”的时序偏差。
- 因此 Phase 1 采用 `core 末尾 barrier tick`：所有 core 在各自 `clockTick()` 尾部通知调度器；调度器在同一周期内等到本 PE 全部 core 都到达后再统一仲裁一次。

## 3. 总体架构

### 3.1 组件分工

新增 4 个内部类/接口：

- `api/IDmaTaggedAccess.h`
  - 可选扩展接口，不替代 `IMemoryAccess`
  - 允许上层在不破坏内存语义边界的前提下附带 `tag + priority`

- `api/IDmaSchedulerProvider.h`
  - 窄接口
  - 由 `MultiCorePE` 提供 `PeDmaScheduler*`
  - 避免 `SnnPESubComponent` 直接依赖 `MultiCorePE` 具体实现

- `services/memory/PeDmaScheduler.{h,cc}`
  - 每 PE 一个
  - 负责共享队列、预算、仲裁、burst 聚合、阶段门控与 DMA 统计

- `services/memory/DmaMemAccessProxy.{h,cc}`
  - 每 core 一个
  - 对外实现 `IMemoryAccess` 和 `IDmaTaggedAccess`
  - 对内把读请求提交到共享的 `PeDmaScheduler`

### 3.2 对现有链路的挂接

- `MultiCorePE`
  - 负责解析 DMA 参数
  - 负责创建 `PeDmaScheduler`
  - 负责汇总 DMA 统计

- `SnnPESubComponent`
  - 在 `bindWorkloadRuntime_()` 中判断是否启用 DMA 且当前是否 `workload_impl=snn`
  - 若满足条件，则把 `rt.mem` 从原始 `StandardMemAccess` 切换为 `DmaMemAccessProxy`
  - 在 `clockTick()` 尾部调用 scheduler 的 barrier tick
  - 在 `onGasStageEvent()` 中同步 DMA stage

- `WeightMemorySubsystem`
  - 仍只依赖 `IMemoryAccess`
  - 在 `issueRead_()` 内尝试 `dynamic_cast<IDmaTaggedAccess*>`
  - 若成功则走 `readTagged(...)`
  - 若失败则回退到旧的 `read(...)`

## 4. 接口设计

### 4.1 `IDmaTaggedAccess`

`IDmaTaggedAccess` 不应把 `rowptr / colidx / blockdata` 这些业务语义写进 memory 域类型系统，因此 `tag` 使用 opaque 整数，不使用带业务名的枚举。

建议接口如下：

```cpp
class IDmaTaggedAccess {
public:
    using Tag = uint32_t;

    enum class Priority : uint8_t {
        P0 = 0,
        P1 = 1,
        P2 = 2,
        P3 = 3,
    };

    virtual ~IDmaTaggedAccess() = default;

    virtual IMemoryAccess::RequestId readTagged(
        uint64_t addr,
        size_t bytes,
        Tag tag,
        Priority priority,
        IMemoryAccess::ReadCallback cb) = 0;
};
```

约定：
- `tag` 仅用于 DMA 侧 debug/stats，不在 memory 域解释为权重语义
- `priority` 由 WMS 显式给出，调度器不再反向推断语义

### 4.2 WMS 内部 tag 映射

WMS 侧在 `WeightMemorySubsystem.cc` 内部维护本地常量，例如：

- `1`: dense demand
- `2`: rowptr
- `3`: colidx
- `4`: blockdata
- `5`: gcss demand
- `6`: idx2 ingress prefetch
- `7`: diag / verify
- `8`: generic prefetch
- `9`: prism-seg line demand

这些值只在 WMS 与 DMA 侧共享，不进入 `IMemoryAccess`。

### 4.3 `IDmaSchedulerProvider`

```cpp
class PeDmaScheduler;

class IDmaSchedulerProvider {
public:
    virtual ~IDmaSchedulerProvider() = default;
    virtual PeDmaScheduler* dmaScheduler() = 0;
};
```

## 5. 调度器内部模型

### 5.1 请求对象

调度器内部维护 `DmaTxn`：

- `dma_req_id`
- `core_id`
- `addr`
- `bytes_total`
- `bytes_issued`
- `bytes_done`
- `tag`
- `priority`
- `submit_cycle`
- `issue_cycle_first`
- `ready_cycle`
- `callback`
- `buffer`
- `inflight_bursts`
- `overflowed`

代理对上层立即返回 `dma_req_id`，不等待真实底层发出。

### 5.2 队列组织

采用按优先级和 core 分桶的队列结构：

- `queues[P0..P3][core_id] -> deque<dma_req_id>`
- `rr_cursor[P0..P3]`

仲裁顺序：
- 先按优先级 `P0 -> P1 -> P2 -> P3`
- 同一优先级内部按 `core_id` round-robin

这样可以天然满足：
- 高优先级保护
- 同优先级 core 间公平
- 不需要在每拍扫描全队列

### 5.3 阶段状态

调度器维护：

- `stage = Gather | Apply | Scatter | Idle`
- `stage_seq`

由 `SnnPESubComponent::onGasStageEvent()` 更新，映射规则：

- `BeginGather -> Gather`
- `BeginApply` 和 `EndApply -> Apply`
- `BeginScatter -> Scatter`
- `EndScatter -> Idle`

### 5.4 Barrier Tick

新增调度器 API：

- `onCoreTickEnd(uint64_t now_cycle, uint32_t core_id)`

逻辑：
- 调度器记录当前 cycle 下哪些 core 已到达
- 当本 PE 全部 core 都到达时，才执行本周期唯一一次 `serviceCycle(now_cycle)`

`serviceCycle(now_cycle)` 做三件事：
- 刷新本周期预算
- 根据优先级、公平、阶段门控进行发射
- 更新 stall 与 queue/inflight 统计

此方案的目的不是模拟片上 pipeline 深度，而是避免当前工程中“PE tick 先于某些 core 请求提交”的假可见性偏差。

## 6. 预算、burst 与阶段门控

### 6.1 基础预算

每 PE 参数：

- `dma_bytes_per_cycle`
- `dma_read_engines`
- `dma_max_inflight`
- `dma_queue_depth`
- `dma_overflow_policy`
- `dma_burst_bytes`
- `dma_setup_cycles`

语义：

- `dma_bytes_per_cycle=0` 表示不限制总 issue 字节
- `dma_read_engines=0` 表示不限制每拍发射 burst 数
- `dma_max_inflight=0` 表示不限制 outstanding burst 数
- `dma_queue_depth=0` 表示 scheduler 主队列不设上限

### 6.2 队列溢出

支持两种策略：

- `block`
  - 请求不丢弃
  - 暂存到 proxy 的本地 `overflow_queue`
  - 待 scheduler 有空间时再转入主队列

- `fail_fast`
  - 调试模式
  - 直接 `fatal`

Phase 1 默认 `block`。

### 6.3 Burst 规则

如果 `dma_burst_bytes > 0`：
- 一个 DMA txn 被切成多个 burst
- 每个 burst 单独占用 `bytes_per_cycle / engine / inflight`
- 原 callback 仅在所有 burst 回包并聚合完成后触发

如果 `dma_burst_bytes == 0`：
- 默认按“单个 DMA txn 视角”发射
- 但为防止 `dma_bytes_per_cycle` 小于请求尺寸时出现永不发射的死锁，实现中应自动启用一个保底 burst：
  - `effective_burst_bytes = min(64, max(1, dma_bytes_per_cycle))`
  - 当 `dma_bytes_per_cycle == 0` 时保持“不限速，不强制切 burst”

### 6.4 Setup 延迟

`dma_setup_cycles > 0` 时：
- 请求首次进入可发射状态前先等待 setup
- 调度器对 txn 记录 `ready_cycle = submit_cycle + dma_setup_cycles`
- 只有 `now_cycle >= ready_cycle` 的请求可参与仲裁

### 6.5 阶段门控

参数形式：

- `dma_stage_budget_scale_{gather,apply,scatter,idle}_{P0..P3}`

默认值建议：

- `P0`: 全阶段 `1.0`
- `P1`: 全阶段 `1.0`
- `P2`: `Gather=1.0`, `Apply=0.0`, `Scatter=0.25`, `Idle=0.25`
- `P3`: 全阶段 `0.2`

实现建议：
- 内部转为定点整数而不是浮点比较，保证回归稳定
- 若 scale 为 `0`，该优先级本拍直接记 `stall_cycles_stage_gate`

## 7. 可选通道预算

可选参数：

- `dma_channels`
- `dma_channel_bytes_per_cycle`
- `dma_channel_interleave_bytes`

仅当满足以下条件时启用：
- `dma_channels > 1`
- `dma_channel_bytes_per_cycle > 0`

通道映射：

- `channel = (addr / dma_channel_interleave_bytes) % dma_channels`

发射规则：
- 请求必须同时满足全局预算和通道预算
- burst 级别扣减预算

## 8. 与现有代码的精确集成点

### 8.1 `components/MultiCorePE.{h,cc}`

改动：
- 新增 DMA 参数解析
- 新增成员：
  - `std::unique_ptr<PeDmaScheduler> dma_scheduler_`
  - `bool dma_enable_`
- 实现 `IDmaSchedulerProvider`
- 在 PE 级 finish / stats 汇总阶段输出 DMA 统计

不做：
- 不在 `MultiCorePE::clockTick()` 中直接驱动 scheduler 的每拍仲裁

### 8.2 `control/SnnPESubComponent.{h,cc}`

新增成员：
- `PeDmaScheduler* dma_scheduler_ = nullptr`
- `std::unique_ptr<DmaMemAccessProxy> dma_mem_proxy_`

改动点：
- `setParentInterface(...)`
  - 若 parent 同时实现 `IDmaSchedulerProvider`，缓存 `dma_scheduler_`
- `bindWorkloadRuntime_()`
  - 仅当 `workload_impl == Snn` 且 `dma_scheduler_ != nullptr` 且 `dma_enable==1` 时，创建 `dma_mem_proxy_`
  - `rt.mem` 绑定到 `dma_mem_proxy_.get()`
  - 非 SNN workload 仍绑定原始 `StandardMemAccess`
- `clockTick(...)`
  - 在 `workload_->onClockTick(...)` 返回后调用 `dma_scheduler_->onCoreTickEnd(total_cycles_, core_id_)`
- `pendingMemSize_()`
  - 启用 DMA 时优先返回代理 `pendingSize()`
  - 保持 global-step drain / outstanding 统计口径正确
- `onGasStageEvent(...)`
  - 把 GAS 阶段同步到 `dma_scheduler_`

### 8.3 `services/synapse/weights/WeightMemorySubsystem.{h,cc}`

不改外部绑定接口：
- 仍然是 `bindMemory(IMemoryAccess*)`

改动：
- `issueRead_(PendingMeta meta)` 内尝试：
  - `auto* dma = dynamic_cast<IDmaTaggedAccess*>(mem_access_)`
  - 若存在则计算 `tag + priority` 并调用 `readTagged(...)`
  - 否则保持旧的 `read(...)`

priority 规则建议：
- `P0`
  - `rowptr`
  - demand `colidx`
- `P1`
  - `blockdata`
  - `dense`
  - demand `gcss`
  - `prism-seg demand`
- `P2`
  - `bcsr_prefetch_all`
  - `scheme1_prefetch`
  - `row_index_prefetch`
  - `idx2 ingress prefetch`
- `P3`
  - diag / verify

关键原则：
- 优先级判断由 WMS 做
- 调度器只消费 priority，不重新理解权重业务语义

### 8.4 `services/memory/DmaMemAccessProxy.{h,cc}`

行为：
- `read(...)`
  - 使用默认 tag `0` 和默认优先级 `P1`
  - 保底兼容 `IMemoryAccess`
- `readTagged(...)`
  - 封装成 `DmaTxn`
  - 提交给共享 scheduler
- `write(...)`
  - Phase 1 直接透传到底层 `IMemoryAccess`
- `pendingSize()`
  - 返回当前 core 的 `queued + inflight + overflow_queue`

### 8.5 `services/memory/PeDmaScheduler.{h,cc}`

负责：
- 请求接收
- 队列深度限制
- barrier tick
- stage gate
- budget / engine / inflight 仲裁
- burst 聚合与回包分发
- stats

## 9. 参数清单

以下参数加到 `MultiCorePE` 级别，建议通过 spec-first 的 `components.pe` 下发：

- `dma_enable`，默认 `0`
- `dma_bytes_per_cycle`，默认 `0`
- `dma_read_engines`，默认 `0`
- `dma_max_inflight`，默认 `0`
- `dma_queue_depth`，默认 `0`
- `dma_overflow_policy`，默认 `block`
- `dma_burst_bytes`，默认 `0`
- `dma_setup_cycles`，默认 `0`
- `dma_channels`，默认 `1`
- `dma_channel_bytes_per_cycle`，默认 `0`
- `dma_channel_interleave_bytes`，默认 `256`
- `dma_stage_budget_scale_*`

推荐最小启用配置：

```json
{
  "components": {
    "pe": {
      "dma_enable": 1,
      "dma_bytes_per_cycle": 256,
      "dma_read_engines": 2,
      "dma_max_inflight": 64,
      "dma_queue_depth": 1024
    }
  }
}
```

## 10. 统计与可观测性

建议 DMA 侧至少输出以下统计：

- `dma_issue_reqs_total`
- `dma_issue_bytes_total`
- `dma_queue_depth_cur_p0` ... `dma_queue_depth_cur_p3`
- `dma_queue_depth_max_p0` ... `dma_queue_depth_max_p3`
- `dma_inflight_cur`
- `dma_inflight_max`
- `dma_stall_cycles_budget`
- `dma_stall_cycles_engine`
- `dma_stall_cycles_inflight`
- `dma_stall_cycles_stage_gate`
- `dma_stall_cycles_queue_full`
- `dma_latency_submit_to_done_cycles_p0` ... `p3`

这些统计由 `PeDmaScheduler` 收集，`MultiCorePE` 统一落盘。

## 11. 测试与实验落点

测试统一放在 `snndl-thing-exp/`，不新建散落脚本目录。

建议新增 case：

- `snndl-thing-exp/cases/pe_dma_ab_smoke/`
  - 同一 workload A/B：`dma_enable=0` vs `1`
  - 目标：确认功能正确且开启 DMA 后统计非零

- `snndl-thing-exp/cases/pe_dma_budget_throttle/`
  - 把 `dma_bytes_per_cycle` 压低
  - 目标：看到 stall 与 latency 上升

- `snndl-thing-exp/cases/pe_dma_stage_gate_prefetch/`
  - 开启某种 prefetch，例如 `experimental_idx2_ingress_prefetch_enable=1`
  - 在 Apply 阶段把 `P2=0`
  - 目标：验证 prefetch issue 在 Apply 被抑制

运行方式沿用已有 runner：

```bash
cd "/home/xgy/remote"
python3 "snndl-thing-exp/tools/run_case.py" pe_dma_ab_smoke --validate-only
python3 "snndl-thing-exp/tools/run_case.py" pe_dma_ab_smoke
```

## 12. 风险与缓解

### 12.1 饥饿

风险：
- 长期高压 P0/P1 可能使 P2/P3 长时间推迟

缓解：
- Phase 1 先接受严格优先级
- 仅在同优先级内部做 round-robin
- 后续如有需要再加 aging，不在本阶段引入复杂度

### 12.2 时序偏差

风险：
- 若把 DMA tick 放在错误位置，会人为引入 1-cycle 可见性偏差

缓解：
- 固定采用 `core 末尾 barrier tick`

### 12.3 预算死锁

风险：
- `dma_bytes_per_cycle < req_size` 且不切 burst 时，请求永远无法发出

缓解：
- 实现里必须有保底 burst 逻辑

### 12.4 统计口径漂移

风险：
- `pendingMemSize_()` 若仍看原始 `StandardMemAccess`，会低估在途请求

缓解：
- 启用 DMA 后改为看 proxy 的 pending

## 13. 分阶段实施顺序

建议严格按以下顺序落地：

1. 新增 `IDmaTaggedAccess` / `IDmaSchedulerProvider`
2. 新增 `PeDmaScheduler` / `DmaMemAccessProxy`
3. `MultiCorePE` 创建 scheduler 并暴露 provider
4. `SnnPESubComponent` 注入 proxy，接入 barrier tick 与 stage sync
5. `WeightMemorySubsystem` 改为优先走 `readTagged`
6. 加入基础 stats
7. 在 `snndl-thing-exp/cases/` 落 A/B、throttle、stage-gate 三个 case

## 14. 最终结论

Phase 1 的最佳方案是：

- 只覆盖 `SNN workload`
- 只覆盖 `WeightMemorySubsystem` 运行期读
- 不改 `IMemoryAccess`
- 通过 `IDmaTaggedAccess + DmaMemAccessProxy + PeDmaScheduler` 落地
- 使用 `core 末尾 barrier tick` 解决当前工程中的多核时序可见性问题
- 测试统一放在 `snndl-thing-exp/cases/`

这套方案在工程侵入度、边界清晰度、可解释性和后续实现成本之间最平衡，可直接进入编码阶段。
