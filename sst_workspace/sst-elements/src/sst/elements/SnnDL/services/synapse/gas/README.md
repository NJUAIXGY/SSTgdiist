# services/synapse/gas/（GAS 窗口与累加辅助子系统）

本目录存放 **GAS（Gather / Apply / Scatter）窗口相关的辅助模块**，用于把窗口边集合、累加器实现、以及与 GatherBufferIF 交互的 CustomCmd/统计数据结构从控制层抽离出来。

> 边界原则：GAS 域负责“窗口与累加辅助”，不负责神经动力学（compute），也不负责 NoC/路由表构建。

## 默认内存语义（cacheline）与 GAS granule 统计

- 平台默认内存语义：**cacheline 粒度**（对齐 `memHierarchy` 的 `GetS/GetX` 事务统计）。
- GAS 可能在 Apply 阶段进行合并读/补洞，从而形成大于 cacheline 的“granule”读取；这类 overfetch 必须通过 GAS 自身统计闭环解释：
  - `gas_unique_bytes_total / gas_unique_reads_total`（唯一覆盖字节数与唯一读次数）
  - `gas.avg_granule_bytes`（聚合指标，dense microbench 默认应接近 `line_size_bytes`）
- 若实验需要 row-streaming/DMA 假设，应显式开启并单列结果；默认不允许隐式回退到 row/granule 语义。

## Apply 发射顺序（GatherBufferIF 可选优化）

GAS 的“合并/去重/发射 granule”实现位于 `components/GatherBufferIF`。当需要研究 DRAM 行局部性/BLP 时，可在 GatherBufferIF 开启
`apply_issue_policy=bank_rr_row_sticky_age|dram_aware_v1|cmd_aware_v1`（默认 `order`），并显式校准 `bank_bits/bank_shift/row_bytes_guess`，避免调度器在“伪 bank/伪 row”
上做优化导致退化。

详见：`components/gather/README.md`（参数含义、Ramulator2 推荐值与复现脚本）。

---

## 目录结构与组件职责

### `GasCustomCmd.h`
- **定位**：GAS 控制面 CustomCmd 定义（承载在 `StandardMem::CustomReq/Resp` 的 payload 中）。
- **主要内容**：
  - `GasOp / GasOpData`：BeginGather/BeginApply/... 等阶段 opcodes；
  - `GasStatData`：GatherBufferIF → PE 的统计载体（unique reads/bytes、row-window merge、burst/payload、inflight peak、buffer peak 等）。

### `GasEdgeCollector.{h,cc}`
- **定位**：per-window 的 edge 采集与翻转迭代器。
- **核心职责**：
  - `recordEdge(post_local, pre_global)` 记录窗口内边（计数）；
  - `flipForApply(...)`：BeginApply 前将 curr → prev（并准备迭代）；
  - `nextPrev(...)`：Apply 阶段逐条迭代 prev 边集合。

### `AccumulatorOps.{h,cc}`
- **定位**：窗口累加器实现（dense/sparse + spill + 可选 shadow verify）。
- **核心职责**：
  - `update(post, dv)`：累加 ΔV；
  - `collectSortedPairs(...)`：以确定性顺序收集更新对（由控制层决定何时 apply/scatter）；
  - `verifyDense(seq)`：可选影子验证（诊断/一致性检查）。
- **特性**：累加器状态自持（避免控制层持有多个容器导致职责混杂）。

### `GasPhaseController.{h,cc}`
- **定位**：阶段事件镜像/轻量编排器（与 `api/IGasOrchestrator` 对接）。
- **作用**：
  - 记录/镜像 BeginGather/BeginApply/... 等阶段事件日志；
  - 将 BeginApply/BeginScatter/EndScatter 这类“序列动作”委托给 orchestrator。

---

## 与其他域的交互

- `components/GatherBufferIF` 使用 `GasCustomCmd` 发送阶段事件/统计到 PE；
- `workload=snn` 使用 `GasEdgeCollector` 与 `AccumulatorOps` 承载窗口边与累加状态（CoreShell 不应持有业务状态机）；
- `services/synapse/weights/WeightMemorySubsystem` 读取 `GasEdgeCollector` 的 prev 边集合，在 Apply 阶段发起窗口读并更新累加器。
