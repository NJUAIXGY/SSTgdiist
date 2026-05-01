# services/stimulus/（Stimulus 刺激/注入子系统）

本目录存放 **Stimulus 域** 的实现：提供独立的“注入时基（timebase）+ 选源 + 注入事务”，并通过 NoC/Route 等子系统完成投递与外发。

> 边界原则：Stimulus 负责 *何时注入/注入哪些源*，但不负责 NoC 传输细节，不负责控制层窗口/GAS 的内部实现细节。

---

## 内存建模口径（默认 cacheline）提示

Stimulus 只负责“注入时基/选源”，不定义权重读粒度；默认体系结构语义以 memHierarchy 的 cacheline 事务模型为主。若切换到 row-streaming/DMA 语义，应在模板输出中显式标注并单列结果。

---

## 目录结构与组件职责

### `StepActivationSubsystem.{h,cc}`
- **定位**：Step 级随机激活注入子系统（Step Random Activation）。
- **核心能力**：
  - **选源**：按 `fraction` 对全局 neuron 做伯努利采样得到 pre 集合；
  - **生成 fanout**：对每个 pre 生成 `fanout` 个 spike（可选通过 BCSR reachability 约束 post 选择）；
  - **注入/外发**：以 **packet-first** 方式将 spike 投递到本 PE 的目标 core，或外发到目标 PE（通过 `api/INocTransport`）；
  - **触发方式**：
    - `period_cycles > 0`：固定周期注入（tick 驱动）；
    - `period_cycles == 0`：legacy BeginGather 触发（`onBeginGather`）。
- **运行时绑定**（`Runtime`）：
  - `const GlobalNeuronLayout* layout`：全局 neuron_id 布局的单一真源（fail-fast：不允许为空）；
  - `INocTransport* noc`：本地投递/外发统一走 NoC 抽象接口（Stimulus 不直接操作 NIC/ring）；
  - `reset_membranes`：可选每步清膜电位（`reset_mem_each_step`）。
- **统计**（`Stats`）：
  - `invocations / pre_selected / spike_attempts / spikes_injected`；
  - `route_hits / route_misses`（当启用 BCSR reachability 路由采样时）。
  - `local_drops`：本地注入失败/被丢弃计数（用于诊断布局/范围问题）。

### `ExternalSpikeInputSubsystem.{h,cc}`
- **定位**：外部端口 `external_spike_input` 的 SpikeEvent 注入子系统（兼容 legacy 输入形态，但投递走 packet-first）。
- **语义冻结（必须）**：
  - 仅本地投递到目标 core；**不做 relay/forward**；
  - 若 `dst_node != this.node_id` 或 `dst_neuron` 非本 PE 范围：直接丢弃。
- **运行时绑定**（`Runtime`）：
  - `const GlobalNeuronLayout* layout`：用于把 global neuron_id 映射到本 PE 内 core；
  - `INocTransport* noc`：通过 `injectLocal(dst_core, pkt)` 完成本地投递（接管 spike 生命周期；无法投递直接 delete）。
  - `enabled`：workload-level stimulus gate；当前只允许 `snn` / `riscv_snn` 打开，`stream/traffic/traffic_mem/tensor` 侧会在装配点直接关闭并静默丢弃输入 spike。

---

## 与其他域的交互

- **NoC 域**：Stimulus 仅依赖 `api/INocTransport`，完成本地投递/外发；不触碰 NoC 实现细节。
- **Synapse/Route 域**：当启用 `step_activation_use_bcsr_routes=1` 时，Stimulus 会加载 reachability（仅影响 post 选择），不触碰权重 bytes。
- **Components/CoreShell**：
  - `MultiCorePE` 负责把 tick/阶段事件转发给 Stimulus，并为其注入 `layout/noc` 句柄；
  - CoreShell/workload 不直接持有 Step 注入逻辑（避免业务语义上浮）。
