# components/gas/（全局 Step/GAS 同步组件）

本目录存放 **Mesh 级别的 Step/GAS 同步控制组件**，用于把“每个 PE 的 Step 开始/结束”收敛为一个显式的全局 barrier，从而避免各 PE 因窗口节奏抖动导致 Step 触发次数不一致。

> 边界原则：该目录只放 **SST 可加载组件（ELI 注册对象）**；它只做“同步控制面”，不包含任何神经动力学/权重/路由/NoC 事务逻辑。

---

## 主要组件

### `GlobalGasStepController.{h,cc}`
- **类型**：`SST::Component`（ELI：`SnnDL.GlobalGasStepController`）
- **职责**：全局 Step barrier 的控制面状态机
  - 接收来自各 PE 的 barrier 事件：`PeReady` / `PeDone(seq)`（事件类型：`events/GasStepBarrierEvent.h`）
  - 广播 `StartStep(seq)` 到所有已连接的 PE（端口：`pe_link0..pe_linkN`）
  - 语义冻结：
    - 当 `require_all_ready=1`：等待所有 PE 都上报 `PeReady` 后才进入第一个 step
    - 每个 `seq`：等待所有 PE 都上报 `PeDone(seq)` 后才进入 `seq+1`
    - 当 `strict_seq_check=1`：发现乱序/重复/越界的 `seq` 直接 `fatal`（用于尽早暴露同步错误）

---

## 与 “step 完成策略（done policy）” 的关系（容易误解点）

`GlobalGasStepController` 只做 **全局 barrier**：它只关心每个 PE 是否上报了 `PeDone(seq)`。

**每个 PE “什么时候决定自己完成了一个 step”** 属于 PE 侧策略，当前由 `components/MultiCorePE` 实现（参数 `global_step_done_policy`）：

- `endscatter`：GAS/window 路径常用；收到所有 core 的 `EndScatter(seq)` 后上报 `PeDone(seq)`。
- `quiescent`：non-window（naive）路径可用；当 PE 在一段静默周期内无输入/无在途事务时上报 `PeDone(seq)`。
- `fixed_cycles`：用于 step-limited 的 `naive_raw` baseline；每 step 运行固定 cycles 后强制上报 `PeDone(seq)`，避免 quiescent 难以满足导致卡 step。

---

## 参数与端口（与 ELI 文档一致）

- **参数**：
  - `clock`：组件时钟（默认 `1GHz`）
  - `start_seq`：起始 step 序号（默认 `1`）
  - `require_all_ready`：是否要求所有 PE 先 ready（默认 `1`）
  - `strict_seq_check`：是否对 seq 严格检查（默认 `1`）
  - `verbose`：日志等级（默认 `0`）
- **端口**：
  - `pe_link%(pe)d`：与各 PE 相连的 barrier 链路（event 类型：`SnnDL.GasStepBarrierEvent`）

---

## 依赖与交互

- **依赖**：`events/GasStepBarrierEvent.h`（barrier 事件载体）
- **典型装配**：整张 mesh **只创建 1 个** controller，并把每个 PE 的 `pe_linkX` 接到 controller 的 `pe_linkX`（它是全局共享的同步器，而不是 per-node）。

---

## 内存建模口径（默认 cacheline）与本目录关系

本目录的组件只负责 **全局 step 同步控制**，不直接参与内存读写合并；但在做 GAS/naive 的“公平对比”时，建议统一采用 cacheline 语义（memHierarchy 默认）：

- traffic 主口径以 MemController 的 `requests_received_*` 为准（L2 traffic）。
- 粒度/over-fetch 的解释口径看 `gas_unique_*` 与 `avg_granule_bytes`（dense+cacheline 应接近 `line_size_bytes`）。
