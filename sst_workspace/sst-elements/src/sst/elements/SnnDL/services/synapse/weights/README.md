# services/synapse/weights/（权重语义与缓存子系统）

本目录存放 **Weights 域** 的实现：权重地址解析、BCSR 元数据与缓存、窗口读编排（budget/outstanding）、以及面向 compute core 的统一 `IWeightReader` 入口。

> 边界原则：Weights 域可以理解 “权重/BCSR/缓存/ΔV 更新” 语义，但不负责 NoC 发送，不构建 fanout 路由表。

## 默认内存语义（cacheline）与显式 overfetch

- 平台默认的体系结构口径是 **cacheline 粒度**（对齐 `memHierarchy GetS/GetX` 事务统计）。
- Weights 域可能在“窗口读合并/补洞/预取”时形成大于 cacheline 的覆盖读（尤其是 BCSR 的索引与块数据路径）；此时必须：
  - 在输出中记录 effective 参数（`effective_config.json`）；
  - 通过 `gas_unique_bytes_total/gas_unique_reads_total`（以及 `gas.avg_granule_bytes`）闭环解释 overfetch；
  - 在 dense microbench 默认语义下，要求 granule 逼近 cacheline（避免把 row-streaming/DMA 假设混入默认结论）。

---

## BCSR “仅格式（format-only）”模式的功能正确性约束（重要）

为了做“只归因 GAS/window”的公平对比，我们有时会在 SnnDL 内部**全局禁用** BCSR 级优化（rowIndex cache/prefetch、block cache、populate、inflight coalescing 等），让 BCSR 只作为：

- **存储格式**（rowptr/colidx/blockdata/blockids 的布局与寻址）；
- **地址映射**（pre/post → block_row/block_col/global_block_index）。

但注意：**“禁用缓存”不等于可以不解析 colidx**。即使 rowIndex cache 关闭，colidx 回包仍必须能定位 `target_block_col`，否则每次 BCSR 权重读会退化为 `0.0f`（功能错误，典型症状是 `spikes_injected_total>0` 但 `neurons_fired_total=0`）。

当前实现保证：

- `WeightMemorySubsystem::handleReadResp_()` 在处理 `bcsr_kind==2`（colidx）时，**始终使用本次回包解析出的 `cols`** 来寻找目标 block；
- 仅当 `BcsrWeightManager::rowIndexCacheCapacity()!=0`（缓存启用）时，才会把 `cols` 写入 rowIndex cache（可选，不影响正确性）。

这条约束的目标是：在“BCSR 优化全部关闭”的实验口径下，依然保持 weight read / ΔV / firing 的功能闭环不被破坏喵。

---

## 目录结构与组件职责

### `WeightMemorySubsystem.{h,cc}`
- **定位**：权重读取与窗口读编排子系统；实现 `api/SnnWeightReader.h` 的 `IWeightReader`。
- **核心职责**：
  - 为 compute core 提供统一入口：`requestDense()` / `requestBCSR()`；
  - 承载 window-read 的集合/预算/并发（issued/outstanding）与发起编排；
  - 维护窗口触达集合（posts/pres）与边集合（通过 `gas/GasEdgeCollector`）；
  - 提供 BCSR 读路径的安全护栏（例如 abs-max guard、rowptr-ready gate、fallback 策略等）。
- **关键装配面**：
  - `bindMemory(IMemoryAccess*)`：绑定纯内存访问（地址→字节）；
  - `configureOrchestrator(OrchestratorConfig)`：由 `workload=snn` 注入“发起读/写、cache、累加、诊断、统计”等回调与配置。
- **典型调用节奏**：
  - BeginGather：`beginGatherWindow(...)` 迁移/清空窗口集合；
  - BeginApply：`beginApplyWindow(...)` + `flipEdgesForApply(...)`，然后 `issueFromEdges()`；
  - ReadResp：由 `workload=snn` 把 bytes 交给 Weights 语义层解析并回调 `acc_update` 等。

### `SnnBcsrWeightManager.{h,cc}`
- **定位**：BCSR 元数据与缓存管理器（`BcsrWeightManager`）。
- **核心职责**：
  - 维护 BCSR 布局参数（block 行列、idx/val 字节数、rowptr/colidx/blockdata/blockids 基址）；
  - 管理 row-index cache 与 block cache（容量可配）；
  - 提供寻址函数：`blockDataAddr()` / `colIndexAddr()` / `rowBounds()` 等；
  - 支持将 rowptr bytes 安装到 host（`installRowptrFromBytes`）并维护 rowptr-ready 状态。

### `WeightAccessor.{h,cc}`
- **定位**：权重寻址/索引解析工具（从控制层抽出的纯 helper）。
- **核心职责**：
  - 将 `(pre_global, post_local)` 映射为请求索引与 cache key；
  - 保持历史 “allow_remap” 的 modulo 兼容语义（用于 pre 不在本 PE 时的保守映射）。

### `WeightCacheOps.{h,cc}`
- **定位**：权重缓存操作封装（自带状态），用于替代控制层散落的 LRU/clock 容器与淘汰逻辑。
- **核心能力**：
  - `configure()` 注入容量、模式（LRU/clock）与淘汰回调；
  - `tryGet()/store()` 提供统一的 cache hit/miss 行为；
  - 支持 `disable_cache` 强制 miss（诊断用）。

---

## 与其他域的交互

- **Memory 域**：
  - Weights 通过 `api/IMemoryAccess` 发起读写；
  - Memory 回包 bytes 由 Weights 解释为 float/idx/rowptr/blockdata 等语义。
- **GAS 域**：
  - `GasEdgeCollector` 负责 per-window edge 集合的 flip/迭代；
  - Weights 在 Apply 阶段基于 edge 集合批量发起读并更新累加器。
- **Compute 域**：
  - Compute core 只依赖 `IWeightReader`；不直接触碰 StandardMem 与 BCSR 缓存细节。
- **Route 域**：
  - Weights 不构建路由表；路由与 fanout 由 `services/synapse/route` 负责。

---

## 约束与建议

- **禁止**：Weights 域内直接发送 NoC 消息或操作 NIC（应由 `services/noc` 与 `services/synapse/route` 负责）。
- **建议**：对外只暴露 `IWeightReader` 等窄接口；其余复杂编排通过 `configureOrchestrator()` 注入，避免 services→control 反向依赖。
