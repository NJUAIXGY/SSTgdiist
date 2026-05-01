# GAS Window（Gather/Apply/Scatter）负载驱动阶段控制：实施计划

> 目标：在 **全局 Step/GAS 同步（GlobalGasStepController + step_gate_enable=1）** 场景下，使 GAS 的阶段推进不再依赖固定 `window_cycles_*` 的“强制结束”，而改为 **负载/显式完成驱动**，从而避免：
> - `done=0/16`（100us 内 step 无法完成）
> - 由于 Gather/Scatter 被固定周期截断导致的发放大幅下降/归零

---

## 1. 问题复盘（当前实现的结构性缺陷）

当前 window/GAS 的阶段事件（BeginGather/BeginApply/BeginScatter/EndScatter）主要由 `components/GatherBufferIF` 在 `window_auto=1` 下的内部时钟状态机产生：
- Gather：按 `window_cycles_gather` 或 auto-end（bytes/reads）切换到 Apply
- Apply：按 `window_cycles_apply`（或 allReady）切换到 Scatter
- Scatter：按 `window_cycles_scatter` 或 `scatter_immediate_complete` 结束并发出 EndScatter

在 **全局同步** 模式下，MultiCorePE 用每个 core 的 `EndScatter(seq)` 来判定 `PeDone(seq)` 并推进下一步：
- 若 Scatter 被配置为“周期上限很大”（常见误用：直接取 `step_activation_period_cycles` 或其他大周期），则一个 step 可能在 100us 内都无法完成，表现为 `done=0/16`
- 若 Gather/Scatter 被设置为“很小的固定周期”，会截断该 step 的 spike/edge 收集与发放，导致 `neurons_fired_total` 大幅下降甚至为 0

核心结论：**全局 barrier 的完成语义不应由 GatherBufferIF 的固定周期驱动**。Gather/Scatter 的“结束”应由负载与业务完成来定义。

---

## 2. 方案（推荐）：Step-Gate 模式下引入“显式结束握手”（负载驱动）

仅在 `window_auto=1 && step_gate_enable=1`（全局同步）时启用：

### 2.1 Gather 结束：由 workload 显式触发 EndGather
- GatherBufferIF 不再依赖 `window_cycles_gather` 强制结束 Gather
- workload 在“该 step 的输入已趋于稳定/收敛”时调用 EndGather（通过 StdMemEndpoint → GasOp::EndGather）
- GatherBufferIF 在自己的 clockTick 中观察到 EndGather 标志后进入 Apply（BeginApply 事件仍由 GatherBufferIF 发出）
- `window_cycles_gather` 在该模式下改为 **fail-fast 超时阈值**（超过阈值仍未 EndGather → fatal），用于尽早暴露“握手缺失/卡死”

### 2.2 Apply 结束：严格按“数据就绪”自动结束
- Apply 不应被固定周期“强制结束”
- GatherBufferIF 在 Apply 中以 `allReady(required_set)` 为准，满足则 `finishApplyWindow_()` 进入 Scatter 并发出 BeginScatter
- `window_cycles_apply` 保持兼容：可作为 fail-fast/诊断阈值，但不再作为必须等待的“最短持有时间”

### 2.3 Scatter 结束：由 workload 在完成 Scatter 事务后显式触发 EndScatter
- GatherBufferIF 的 Scatter 不再按 `window_cycles_scatter` 或 `scatter_immediate_complete` 自动结束
- workload 在 BeginScatter 事务完成后，显式请求 EndScatter（StdMemEndpoint → GasOp::EndScatter）
- GatherBufferIF 在 clockTick 中看到 EndScatter 请求后发出 EndScatter 事件
- MultiCorePE 的 global barrier 仍以 EndScatter 作为 `PeDone(seq)` 的依据，但此时 EndScatter **真实代表 scatter 事务完成**（而非“等了 N 个周期”）
- `window_cycles_scatter` 在该模式下改为 **fail-fast 超时阈值**

### 2.4 关键实现约束（避免重入/次序竞态）
- workload 发送 EndGather/EndScatter 的请求只设置“pending 标志”，**由 GatherBufferIF 的 clockTick 统一推进阶段**（避免 BeginScatter 内同步触发 EndScatter 导致递归回调）
- 兼容性：非 step_gate 模式（`step_gate_enable=0`）保持原有窗口自动推进行为（不影响历史实验）

---

## 3. 落地改动点（文件级）

### 3.1 GatherBufferIF：支持 step-gate 显式结束
**修改：**
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`
  - `send(CustomReq)`：在 `window_auto=1 && step_gate_enable=1` 时允许接收 `EndGather/EndScatter`（不再“一律忽略”）
  - `clockTick()`：在 step-gate 模式下
    - Gather：不再按 `win_cyc_gather_` 自动 end；仅响应 EndGather（或 auto-end bytes/reads）
    - Apply：按 allReady 自动结束（不依赖 win_cyc_apply_ > 0）
    - Scatter：不再按 cycle 自动 end；仅响应 EndScatter
    - `win_cyc_*` 作为超时阈值用于 fatal

### 3.2 Workload：在合适时机发起 EndGather/EndScatter
**修改：**
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ICoreWorkload.h`
  - 在 `ICoreWorkload::Reporting` 增加两个可选回调：
    - `request_gas_end_gather(ctx, seq)`
    - `request_gas_end_scatter(ctx, seq)`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
  - 在 bindRuntime 时绑定上述回调，内部实现为 `stdmem_ep_->sendGasCmd(GasOp::EndGather/EndScatter, seq, ...)`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
  - BeginScatter 完成后请求 EndScatter（使 barrier 不再被固定 scatter 周期拖慢）
  - Gather：在 Gather 阶段采用“静默收敛（quiesce）”策略请求 EndGather（默认一个保守阈值；可后续再加参数化）

---

## 4. 验收与回归（强制 100us）

1) 编译安装：
- `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4 && make install`
2) 回归运行：
- `cd sst_dram_si && export MESH_SIM_TIME=100us && ./tools/run_mesh_with_time.sh`
3) 检查：
- `outputs_large/paper2/dram_mesh_4x4/<timestamp>/essential_summary_mesh.json`
  - `global_step`（若有）/ `step_activation.invocations` 随 step 推进增长
  - `gas.*_ns_*` 不再出现“被 window_cycles_scatter 拉到极大导致 step 完成不了”的异常
  - `spike_activity.neurons_fired_total` 量级合理（禁止归 0）

