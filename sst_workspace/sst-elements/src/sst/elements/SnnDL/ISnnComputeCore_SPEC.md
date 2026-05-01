# ISnnComputeCore 接口契约说明（冻结版）

本文档描述 `ISnnComputeCore` 在 SnnDL 中的语义契约，便于后续实现新的计算核心（Compute Core）时做到可替换且行为一致。

当前参考实现：`DefaultSnnComputeCore`（`SnnComputeCore.{h,cc}`）。

---

## 1. 设计目标与分工

### 1.1 目标

- 将“神经动力学 / 计算核心”与“SST/SnnDL 适配层（内存、GAS、路由等）解耦。
- 保证在不修改 `SnnPESubComponent` 的前提下，可以替换不同的 compute core 实现。
- 计算核心对外提供统一的、事件驱动的接口：接受突触输入，输出发放事件。

### 1.2 责任边界

**SnnPESubComponent（适配层）负责：**

- SST 生命周期对接：`init/setup/finish`、clock 驱动；
- StandardMem / DRAM / BCSR 权重读写与缓存；
- GAS 超步（Gather/Apply/Scatter）状态机与统计；
- 基于 `route_provider_` 的 fanout 计算与 SpikeEvent 发送；
- 通过接口将突触输入、时间与阶段信息“喂”给 compute core；
- 通过接口从 compute core 拉取发放事件，再做路由和统计。

**ISnnComputeCore 实现负责：**

- 内部所有神经元状态的存储与更新（膜电位、不应期、最近发放时间等）；
- 突触输入（ΔV/权重作用）如何影响状态；
- 不应期 / 阈值 / 窗口单次发放等发放逻辑；
- 提供只读/写状态视图（用于 debug/学习）；
- 对统计接口（`getStatistics`）的自有内部计数。

---

## 2. 核心数据结构与接口

### 2.1 ComputeCoreContext

```c++
struct ComputeCoreContext {
    uint32_t core_id;
    uint32_t node_id;
    uint32_t num_neurons;
    uint64_t global_neuron_base;
    uint32_t neurons_per_pe_cfg;
    SST::Output* log;          // 可选：日志指针，可为空
    IWeightReader* weight_reader; // 可选：权重访问抽象，可为空
    // 可选：学习写回回调（若 core 实现学习/梯度累加，可在窗口边界调用）
    // 返回 true 表示写回成功，core 可清空本窗梯度
    std::function<bool(const std::unordered_map<uint64_t,float>& grads,
                       float learning_rate,
                       float weight_decay)> writeback_fn;
};
```

- `num_neurons`：核心内本地神经元数，所有 idx 均在 `[0, num_neurons)` 。
- `global_neuron_base`：本 core 对应的全局 neuron 基址，仅供日志 / 诊断参考。
- `weight_reader`：若实现需要自行发起权重访问，可通过该抽象；也可以完全不用。
- `writeback_fn`：学习可选回调；用于让 core 在窗口边界请求控制层执行权重写回。

### 2.2 发放事件与状态快照

```c++
struct FireEvent {
    uint32_t neuron_idx; // 本地 neuron 索引 [0, num_neurons)
    float v_before;      // 发放前膜电位
    float v_after;       // 发放后膜电位
};

struct NeuronStateSnapshot {
    float v_mem;
    uint32_t refractory;
    uint64_t last_spike;
};
```

- `FireEvent` 用于 compute core → 适配层的发放事件传递；
- `NeuronStateSnapshot` 用于 debug / 学习路径的轻量级状态访问。

### 2.3 ISnnComputeCore 接口概览

**生命周期 / 配置：**

```c++
virtual void configure(const ComputeCoreContext&, const SST::Params&) = 0;
virtual void onInit(unsigned phase) = 0;
virtual void onSetup() = 0;
virtual void onFinish() = 0;
```

**时间推进：**

```c++
virtual void onClockTick(uint64_t now_cycle) = 0;
```

**GAS 阶段回调：**

```c++
virtual void onStageBeginGather(uint32_t seq) = 0;
virtual void onStageBeginApply(uint32_t seq) = 0;
virtual void onStageEndApply(uint32_t seq) = 0;
virtual void onStageBeginScatter(uint32_t seq) = 0;
virtual void onStageEndScatter(uint32_t seq, uint64_t spikes_emitted_hint) = 0;
```

**Spike 输入（路由后到达本 core 的 spike）：**

```c++
virtual void onSpikeDelivered(SpikeEvent* spike) = 0;
```

**状态 / 统计：**

```c++
virtual bool hasWork() const = 0;
virtual double getUtilization() const = 0;
virtual void getStatistics(std::map<std::string, uint64_t>& out) const = 0;
virtual void resetMembraneState(float v_rest) = 0;
```

**突触输入与发放管理：**

```c++
// 应用一次突触输入 ΔV（或其它权重作用），post_local 为本地 neuron 索引
virtual void applySynapticDelta(uint32_t post_local, float dv) = 0;

// 窗口累加语义下，控制层在记录边/发起权重读/累加前，需先询问核心是否接受该输入（例如不应期过滤）
virtual bool shouldAcceptSynapticInput(uint32_t post_local, uint64_t now_cycle) const = 0;

// 便捷接口：允许核心内部处理带有 pre_global 的完整突触事件（由核心自行决定门控/累加方式）
virtual void onSynapticEvent(const SynapticEvent& ev) = 0;

// 统一的“周期收敛”接口：推进动力学并在内部判定发放，输出事件待 drain
virtual void endCycle(uint64_t now_cycle) = 0;

// 仅对候选集合进行发放判定（window/scatter 可选优化；必须不改变结果）
virtual void endCycleCandidates(uint64_t now_cycle, const std::vector<uint32_t>& candidates) = 0;

// 取出当前尚未消费的输出事件（控制层统一路由）
virtual void drainOutputs(std::vector<FireEvent>& out, bool clear = true) = 0;

// 窗口级发放状态清零（通常在 BeginScatter 调用）
virtual void clearFiredWindow() = 0;

// 兼容接口：旧路径仍可用（推荐使用 drainOutputs）
virtual void getFiredEvents(std::vector<FireEvent>& out, bool clear = true) = 0;
```

**状态快照（只读/写视图）：**

```c++
virtual bool readNeuronState(uint32_t idx, NeuronStateSnapshot& out) const = 0;
virtual void writeNeuronState(uint32_t idx, const NeuronStateSnapshot& st) = 0;
```

**显式发放判定（当前默认实现依然使用）：**

```c++
virtual void updateNeuronStates() = 0;
virtual bool fire(uint32_t idx, uint64_t now_cycles, INeuronModel* model,
                  float& v_before, float& v_after) = 0;
```

> 说明：控制层应优先使用 `endCycle/endCycleCandidates + drainOutputs`；`updateNeuronStates/fire/getFiredEvents`
> 更偏向“兼容/调试接口”，后续可逐步弱化其在适配层中的直接使用。

---

## 3. 关键语义与不变量

### 3.1 索引与范围

- 所有 `idx` / `post_local` 参数必须满足：
  - 有效范围为 `[0, num_neurons)`；
  - 若越界，实现可以安全忽略或返回 `false`，不得崩溃。

### 3.2 配置与生命周期

1. `configure(context, params)`
   - 在构造完成后、init 之前调用一次。
   - 必须使用 `context.num_neurons` 初始化内部 state（包括 AoS/SoA/AoSoA 任意布局）。

2. `onInit(phase)`
   - 与 SST `init` 阶段扣合，可能被多次调用；
   - 可以根据 `phase` 决定何时实际初始化内部结构。

3. `onSetup()` / `onFinish()`
   - 各调用一次，用于仿真开始前 / 结束后做额外操作（预热、统计收尾等）。

### 3.3 时间推进与 GAS 阶段

- `onClockTick(now_cycle)`：
  - 每周期调用一次，与 SST global clock 对齐；
  - 用于 per-cycle bookkeeping（统计、学习/验证 tick、窗口计数等）；
  - **动力学推进与发放判定**由适配层通过 `endCycle/endCycleCandidates` 在收敛点显式触发（以支持 window/scatter 语义）。

- `onStageBeginGather/Apply/Scatter`、`onStageEndApply/Scatter`：
  - 由 SnnPESubComponent 的 GAS 控制路径触发；
  - 一般用于设置内部 `gas_stage_` 状态、清空窗口数据结构等；
  - `onStageBeginScatter` 通常应调用 `clearFiredWindow()` 等价操作。

### 3.4 突触输入：applySynapticDelta

- 语义：向本地 neuron `post_local` 施加一次“突触输入事件”。最常见是 ΔV 叠加，但实现可以采用更一般的动力学（例如电流、门控变量等）。
- 调用特点：
  - 可能在同一周期内多次调用、也可能跨多个周期累积；
  - 常见场景：
    - GAS Scatter 使用累加器（dense / map），遍历 touched posts 后调用；
    - Scheme1 Scatter 中对当前 slice 的所有 post 施加 ΔV。
- 要求：
  - 每次调用必须对内部状态产生一致影响；
  - 不得在此接口中直接向外部暴露发放（发放应统一经 `endCycle/endCycleCandidates + drainOutputs`）。

### 3.4.1 窗口累加输入门控：shouldAcceptSynapticInput

- 背景：在 `apply_acc_enable && gas_window_mode` 下，适配层常见模式是“先收集边/发起权重读，在 Scatter 统一应用 ΔV”。
  此时无法立刻调用 `onSynapticEvent()` 来复用核心侧的输入门控（例如不应期过滤），因此需要该接口做一次一致的 gate 判定。
- 语义：`shouldAcceptSynapticInput(post_local, now_cycle)` 返回：
  - `true`：允许该输入进入控制面流程（记录边/发起权重读/累加 ΔV）；
  - `false`：该输入应被丢弃。
- 不变量：
  - 当该接口返回 `false` 时，适配层不得：
    - 记录该边（避免污染 window-read 的 edge 集合）；
    - 发起权重读取请求；
    - 将该输入累加进窗口累加器。

### 3.5 发放判定与窗口门控

当前 Default 实现中，发放判定流程为：

1. 适配层在收敛点调用：

   ```c++
   compute_core_->endCycle(now_cycles);
   std::vector<FireEvent> fired;
   compute_core_->drainOutputs(fired, true);
   ```

2. compute core 在 `endCycle()` 内：
   - 推进动力学（Default: `updateNeuronStates()`）；
   - 对 neuron 集合执行发放判定（Default: 扫描并调用 `fire()`）；
   - 将发放结果追加到内部输出队列（由 `drainOutputs` 拉取）。

3. 适配层对每个 `FireEvent` 执行：
   - 统计更新（`spikes_generated`、`window_spikes_all_` 等）；
   - 基于 `route_provider_` 计算 fanout 并发送 SpikeEvent。

**不变量：**

- **窗口门控：**
  - 当 `apply_acc_enable && gas_window_mode` 为真时：
    - 只有在 Scatter 阶段（`onStageBeginScatter` 与 `onStageEndScatter` 之间）允许产生输出发放事件；
    - 单一窗口内，对给定 `idx`，最多产生一个 `FireEvent`。

- **事件一致性：**
  - 每次发放被判定为成功，都必须在后续某次 `drainOutputs(clear=true)` 中返回对应事件，且只返回一次。

### 3.6 状态快照：readNeuronState/writeNeuronState

- 用途：
  - Scatter 阶段调试：打印 `v_before/v_after/refrac`；
  - 学习路径：计算 surrogate gradient 需要访问 `v_mem` 和 `refractory`。
- 要求：
  - 当 `idx < num_neurons` 时：
    - `readNeuronState(idx, out)` 需返回 `true` 且 `out` 等价于当前内部状态；
    - `writeNeuronState(idx, st)` 需把 `st` 写回内部状态，使下一次 `read` 返回相同值（除非中间有 `onClockTick/applySynapticDelta/fire` 等改变）。

实现可以内部直接使用 `SnnCoreEngine` 的 `getMem/getRefrac/getLastSpike/set*`，但这些不再暴露到接口层。

---

## 4. SnnPESubComponent 使用模式（简要）

适配层典型调用序列（省略非关键细节）：

1. 构造时：

   ```c++
   ComputeCoreContext ctx{...};
   compute_core_->configure(ctx, params);
   ```

2. SST 生命周期：

   ```c++
   compute_core_->onInit(phase);
   compute_core_->onSetup();
   ...
   compute_core_->onFinish();
   ```

3. 每个仿真周期：

   ```c++
   compute_core_->onClockTick(total_cycles_);
   ```

4. GAS 阶段：

   - 控制层在窗口阶段边界调用相应 onStage*（当前由 `SnnPESubComponent::Impl` 统一记录/触发）：

   ```c++
   compute_core_->onStageBeginGather(seq);
   compute_core_->onStageBeginApply(seq);
   compute_core_->onStageBeginScatter(seq);
   ...
   compute_core_->onStageEndScatter(seq, spikes_emitted_hint);
   ```

5. 突触输入与发放：

   - Apply/Scatter 阶段计算出 ΔV 后（适配层只负责喂 ΔV 与触发收敛）：

   ```c++
   applySynapticDelta(post_local, dv);
   std::vector<FireEvent> fired;
   compute_core_->endCycle(now_cycles);
   compute_core_->drainOutputs(fired, true);
   for (auto& ev : fired) {
       handleNeuronFire_(ev.neuron_idx, ev.v_before, ev.v_after);
   }
   ```

6. 状态快照（调试/学习）：

   ```c++
   NeuronStateSnapshot snap{};
   if (compute_core_->readNeuronState(idx, snap)) {
       // 使用 snap.v_mem / snap.refractory / snap.last_spike 做额外处理
   }
   ```

---

## 5. 实现新 Compute Core 的建议

当你实现新的 `ISnnComputeCore` 时：

1. 确保完全遵守本文档中接口语义和不变量；
2. 可以自由选择内部动态方程（LIF、Izhikevich、非脉冲激活单元等）；
3. 只要保留：
   - `applySynapticDelta` 视为“向某 neuron 输入一个事件”；
   - `FireEvent.neuron_idx` 为本地索引；
   - `NeuronStateSnapshot` 提供等价状态视图；
   即可和现有 `SnnPESubComponent` 无缝协作。
