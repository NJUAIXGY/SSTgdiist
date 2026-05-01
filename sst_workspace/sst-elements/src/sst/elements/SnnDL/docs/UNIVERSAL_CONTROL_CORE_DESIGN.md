# 通用控制子核设计：Compute Core 可替换 + 内存/通信子系统化

> 目标：将 `control/SnnPESubComponent` 收敛为**通用控制壳（control plane sub-core）**；将可替换计算范式下沉到 `compute/ISnnComputeCore`；将**内存访问**与**通信/路由**各自收敛为独立且完整的子系统，避免控制层继续膨胀，同时保持现有仿真口径与回归行为不变。

## 1. 范围与约束

### 1.1 目标（What we want）

- `SnnPESubComponent` 成为“通用控制子核”：
  - **不包含**任何 SNN 动力学/神经元状态/阈值判定/不应期等；
  - 仅负责：SST 生命周期对接、GAS/窗口编排、事务调度（内存/通信）、统计汇总与诊断开关。
- Compute Core 可替换：
  - 计算范式仅通过标准 API 与控制层交互；
  - Compute Core 不直接依赖 `StandardMem`、`Link`、路由表、环网等 SST 细节。
- 内存访问子系统独立完整：
  - 标准化后端（StandardMem/未来替换） + 权重语义服务（缓存/合并/BCSR/预算/outstanding）形成闭环；
  - 控制层不再持有内存系统内部容器（pending map、cache 容器等）。
- 通信子系统独立完整：
  - 路由/封包/发送/本地转发形成闭环；
  - 控制层不再包含“如何路由/如何构造并发送 SpikeEvent”的细节。

### 1.2 非目标（What we do NOT do now）

- 不引入新的计算范式实现（先把接口与控制壳稳定下来）。
- 不改变 Python 侧使用方式与关键参数名（保持兼容为第一优先）。
- 不改变 GAS/窗口语义与统计口径（以 `sst_dram_si/tools/run_mesh_with_time.sh` 回归可完成为准）。

### 1.3 必须保持不变的行为（Compatibility contract）

- 现有脚本可不改即可运行：
  - `sst_dram_si/test_mesh_4x4.py`、`SnnDL_Basic/scripts/test_classification_4x4.py`。
- 统计字段名与输出口径保持稳定（供离线汇总脚本使用）。
- 诊断开关与 debug 日志尽量保持（允许位置迁移，但语义不变）。

## 2. 现状（基于当前代码结构）

### 2.1 目录分层（已完成的基础重组）

当前 SnnDL 已按职责拆分为：

- `api/`：对外/跨层接口（例如 `IWeightReader`）。
- `control/`：控制层（`SnnPESubComponent` 及按功能拆分的 `.cc`）。
- `compute/`：计算核心（`ISnnComputeCore` + 默认实现）。
- `services/`：可复用服务（权重地址解析、缓存策略、GAS 辅助等）。
- `components/`：顶层组件（MultiCorePE、NIC、Loader 等）。

### 2.2 已存在的“标准 API 雏形”（可复用）

- `api/IWeightReader`：权重读取语义接口（屏蔽 StandardMem/缓存细节）
  - `requestDense/requestBCSR/tryCache/putCache`
  - 文件：`api/SnnWeightReader.h`
- `compute/ISnnComputeCore + ComputeCoreContext`：
  - 控制层注入 `log`、`weight_reader`、`writeback_fn` 等
  - 文件：`compute/SnnComputeCore.h`
- `api/SnnPEParentInterface`：
  - 父组件承担 `sendSpike()` 与其它系统资源
  - 文件：`api/SnnPEParentInterface.h`

### 2.3 当前仍需进一步收敛的问题

- **内存事务仍分散**：`StandardMem` 请求派发、pending 跟踪、合并策略、BCSR 读取路径等仍主要散落在 `control/*_mem.cc`、`control/*_bcsr.cc` 与若干辅助模块中。
- **通信事务仍分散**：路由构建与发送路径仍部分存在于控制层，导致控制层难以保持“通用壳”定位。
- **Compute Core 接口收敛仍需保持一致性**：
  - 已在 Phase5.4 完成主接口收敛：`ISnnComputeCore` 不再包含 `requestWeight/resolveWeightKey/weightCacheTryGet...`；
  - 若某 compute 需要权重/缓存语义，改为实现可选扩展接口 `compute/IWeightAwareComputeCore`；
  - 主链路依赖 `ComputeCoreContext.weight_reader (IWeightReader)` 注入，避免接口层暴露内存语义。

## 3. 目标架构（最终形态）

### 3.1 分层与依赖方向（单向依赖）

```
components/* (PE/NIC/Network/Ring)
        ^
        | (transport/backends)
        |
control/SnnPESubComponent  —— 通用控制子核（control plane）
  | holds: IComputeCore
  | holds: IMemorySubsystem
  | holds: ICommSubsystem
  v
compute/* (IComputeCore impls)      services/* (Memory/Comm subsystems)
```

**依赖规则**

- `compute/` 不依赖 `control/`、`components/`、`StandardMem`。
- `services/` 不依赖 `control/` 私有成员；只依赖 `api/`、`events/`、标准库与少量 SST 基础类型（Output/Params）。
- `control/` 只依赖 `compute/` 与 `services/` 的公开接口，不窥探子系统内部容器。

### 3.2 控制子核（SnnPESubComponent）职责边界

**SnnPESubComponent 负责**

- 生命周期对接：`init/setup/finish`、clock 驱动。
- GAS/窗口编排：Begin/EndGather、Begin/EndApply、Begin/EndScatter。
- 事务编排：
  - 调用 Memory Subsystem 发起/推进内存事务（预算/outstanding/窗口读等）。
  - 调用 Comm Subsystem 将 compute core 的输出事件路由/发送。
- 统计汇总与向父组件汇报（通过控制层内部 hooks：`SnnPESubComponent::Impl::report*`）。

**SnnPESubComponent 不负责**

- 神经元动力学与状态维护（完全在 compute core）。
- StandardMem 请求细节（组包、pending map、回调解码、合并实现）。
- cache 容器与淘汰策略（完全在 Memory Subsystem 内）。
- SpikeEvent 的构造/路由分支/发送细节（完全在 Comm Subsystem 内）。

## 4. 标准 API 设计（建议接口草图）

> 说明：以下接口以“增量迁移、保持兼容”为前提；可先引入接口与适配器，不立即删除旧接口。

### 4.1 Compute Core 契约（IComputeCore）

现阶段继续复用 `compute/ISnnComputeCore`（见 `ISnnComputeCore_SPEC.md`），并明确两类接口：

- **必须接口（稳定核心）**
  - `configure/onInit/onSetup/onFinish`
  - `onClockTick/endCycle/endCycleCandidates`
  - `onSpikeDelivered`
  - `drainOutputs`
  - `onStageBegin*/onStageEnd*`
  - `shouldAcceptSynapticInput`（控制层在“记录边/发起权重读/累加ΔV”前复用核心门控，避免窥探动力学状态）
- **可选扩展接口（仅当 compute 需要权重语义时实现）**
  - `IWeightAwareComputeCore`：`requestWeight/requestWeightBCSR/resolveWeightKey/weightCacheTryGet/weightCacheStore`
  - 推荐：Compute Core 主实现仅依赖 `ComputeCoreContext.weight_reader (IWeightReader)`，扩展接口只用于 legacy/特殊范式兼容。

### 4.2 Memory Subsystem（内存访问完整体系）

#### 4.2.1 IMemoryAccess（后端：可替换 StandardMem）

当前主链路使用 `api/IMemoryAccess`（纯 addr→bytes）作为跨域唯一入口：

- 语义：只做**按地址读写 + 回调**，不关心权重 key/BCSR/cache。
- 典型实现：`services/memory/StandardMemAccess`（内部持有 `SST::Interfaces::StandardMem*` 与 pending 跟踪）。

#### 4.2.2 WeightMemorySubsystem（语义服务：实现 IWeightReader）

主链路实现位于 `services/synapse/weights/WeightMemorySubsystem`：

- 内部组合（现有模块复用）：
  - `WeightAccessor`：key/地址解析、index_mode/weights_cols
  - `WeightCacheOps`：LRU/clock 缓存（已内聚）
  - `SnnBcsrWeightManager`：BCSR rowptr/colidx/block 管理（可选开启）
  - `IMemoryAccess`：纯内存后端（StandardMemAccess）
- 对外提供：
  - `IWeightReader*`：注入 compute core（`ComputeCoreContext.weight_reader`）
  - Control 侧窗口接口（建议）：
    - `beginWindowGather(seq)` / `beginWindowApply(seq)` / `beginWindowScatter(seq)`（窗口边界通知）
    - `recordSynapseEdge(pre_global, post_local, count)`（Gather 期记录边/集合）
    - `issueWindowReads()`（Apply 期按预算/outstanding 发起读）

#### 4.2.3 Hooks 与统计（控制层不窥探内部状态）

建议 Memory Subsystem 提供 hooks，以复用控制层的统计上报接口（`SnnPESubComponent::Impl::report*`）：

- `onIssue(bytes, inflight, is_weight)`
- `onCacheAccess(hit)`
- `onCacheEvict()`
- `onPendingPeak(outstanding)`

控制层只接收事件，不读写 Memory Subsystem 内部容器。

### 4.3 Comm Subsystem（通信/路由完整体系）

#### 4.3.1 ISpikeTransport（后端：发送能力）

- 典型实现：`ParentSpikeTransport`，内部调用 `SnnPEParentInterface::sendSpike()`。
- 若未来需要 NIC/环网/其它路径，可替换 transport 实现，不改控制层与 compute core。

#### 4.3.2 SpikeCommSubsystem（语义服务：路由/封包/发送）

主链路实现位于 `services/synapse/route/SpikeCommSubsystem`：

- 内部组合：
  - `SynapseRouteSubsystem`（route table / fanout / gating）
  - `ISpikeTransport`
  - （可选）门控缓存应用（如果希望“外发过滤”也收敛到通信体系）
- 对外提供：
  - `dispatchFired(core_id, now_cycle, fired_events) -> spikes_emitted`
  - `buildRoutes(params)`（在 setup/首窗前执行，或懒加载）

控制层只负责在合适时机把 `compute_core_->drainOutputs()` 的结果交给通信子系统。

## 5. 关键路径时序（控制壳如何编排子系统）

### 5.1 输入路径（deliverSpike → compute + memory 记录）

1. `deliverSpike(spike)`：控制层接收输入事件（入队/统计/窗口标记）。
2. 在本地处理时：
   - `compute_core->shouldAcceptSynapticInput(post, now)`：决定是否接受（避免控制层读动力学状态）。
   - 若接受：
     - （窗口模式）Memory Subsystem `recordSynapseEdge(pre, post, count)`；必要时做“机会式 issue”（预算允许）。
     - （非窗口模式）按现有策略立即发起权重读或走 cache（仍由 Memory Subsystem 完成）。
   - `compute_core->onSpikeDelivered(spike)`：只做范式相关输入处理（若该范式需要）。

> 注：最终形态建议让“recordEdge/集合管理/窗口读编排”归入 Memory Subsystem，控制层只发出窗口边界与记录请求。

### 5.2 Gather/Apply/Scatter（窗口模式）

- BeginGather：控制层通知 compute core 与 memory/comm 子系统进入 Gather。
- BeginApply：
  - Memory Subsystem 选择数据源（prev/curr window 集合）并发起 reads（预算/outstanding/merge 策略完全在内存子系统）。
  - Apply 期间：内存响应到达后，Memory Subsystem 将结果写入 cache，并通过控制层/回调把 ΔV 应用到 compute core（或提交给 accumulator）。
- BeginScatter：
  - 控制层触发 compute core 的 `endCycleCandidates` 或 scatter 收敛接口；
  - 然后 `compute_core->drainOutputs()`；
  - 交给 Comm Subsystem `dispatchFired()`。

### 5.3 内存响应路径（StandardMem）

- `services/memory/StandardMemAccess` 负责：
  - request-id 分配、pending map、回调分发；
  - 合并读/按行读等“物理策略”（可选上移到 WeightMemorySubsystem，但建议后端至少负责 pending/回调）。
- WeightMemorySubsystem 负责：
  - 从响应中解析 float 权重；
  - 更新 cache；
  - 触发“ΔV 提交/边计数”等语义动作与统计 hooks。

## 6. 迁移计划（增量落地，不破坏回归）

### Phase A：内存子系统对象化（先形成“独立完整体系”）

1. 引入 `IMemoryAccess` 与 `services/memory/StandardMemAccess`：
   - 从控制层搬迁 pending map、req id、回调派发代码到纯内存访问层（addr→bytes）。
2. 引入 `WeightMemorySubsystem`：
   - 组合 `WeightAccessor/WeightCacheOps/BcsrWeightManager/IMemoryAccess`；
   - 对 compute core 暴露 `IWeightReader`；
   - 对 control 暴露窗口边界与窗口读发起入口。
3. 控制层改为持有 `std::unique_ptr<WeightMemorySubsystem>`：
   - `ComputeCoreContext.weight_reader` 指向该子系统；
   - 控制层不再直接触碰 StandardMem 的 request 细节。

### Phase B：通信子系统对象化

1. 引入 `ISpikeTransport`（父组件 sendSpike 适配）。
2. 引入 `SpikeCommSubsystem`（路由/封包/发送闭环）。
3. 控制层收敛到：
   - `compute_core->drainOutputs()` → `comm->dispatchFired()`。

### Phase C：Compute Core 接口收敛为“范式无关”

1. 将 `ISnnComputeCore` 中 weight/cache 相关方法迁出为可选扩展接口（例如 `IWeightAwareComputeCore`），避免 compute 被接口绑架。
2. 控制层与 compute core 统一只通过 `IWeightReader` 与 Memory Subsystem 交互。
3. 最终可引入 `IComputeCore`（保留 `ISnnComputeCore` type alias 兼容）以支持非 SNN 范式命名。

## 7. 验证与回归

- 编译与安装：
  - `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4 && make install`
- 回归（10us）：
  - `MESH_SIM_TIME=10us sst_dram_si/tools/run_mesh_with_time.sh`
- 建议额外跑（100us）：
  - `MESH_SIM_TIME=100us sst_dram_si/tools/run_mesh_with_time.sh`

## 8. 风险与缓解

- 风险：接口迁移导致行为漂移（cache/merge/outstanding/窗口集合选择）
  - 缓解：每个 Phase 都保持“语义不变”，仅做“搬家 + 适配器”；每步后必须跑 10us 回归。
- 风险：控制层继续膨胀
  - 缓解：任何新增复杂逻辑优先放入子系统文件；控制层只保留 orchestration 入口。
- 风险：性能回退（cache miss 率/合并策略差异）
  - 缓解：hooks + 统计对齐；必要时用 `stage_events_csv` 与离线汇总确认趋势一致。

## 9. 下一步行动清单（建议）

- [x] 定义 `IMemoryAccess` 接口与 `services/memory/StandardMemAccess` 位置（纯 addr→bytes）
- [x] 定义并落地 `services/synapse/weights/WeightMemorySubsystem`（实现 `IWeightReader` + 窗口接口）
- [x] 从 control 迁出 StandardMem 回包与 pending/req-id/回调派发到 `StandardMemAccess`/stdmem endpoint
- [ ] 将“窗口读集合/边记录/发起读编排”从 control 迁入 Memory Subsystem（控制层仅发窗口边界与 record 请求）
- [ ] 定义 `ISpikeTransport` 与 `SpikeCommSubsystem`（路由/发送闭环）
- [ ] 将输出路由从 control 迁入 Comm Subsystem
- [ ] Phase-by-phase 编译安装 + 10us/100us 回归验证
