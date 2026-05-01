# api/（稳定接口层：跨层最小契约）

本目录存放 **SnnDL 各层共享的“稳定接口”与最小抽象**，用于：

- 降低编译耦合（避免 `components/control/services/compute` 互相 include 实现头）；
- 固化模块边界（NoC/Mem 平台面不携带 SNN 语义）；
- 支撑可插拔 workload（`snn/stream/...`）与可替换 compute core。

---

## 设计原则（KISS + 边界硬化）

- **接口应窄**：只暴露跨层必须信息；复杂事务留在对应子系统/workload。
- **平台面语义隔离**：Memory 只做 `addr↔bytes`；NoC 只做 `packet` 投递；不要在接口中出现 `weight/bcsr/route` 等业务字段。
- **可选扩展单独承载**：避免“胖接口”绑架所有实现。

---

## 核心接口一览（按域归类）

### CoreShell / Workload（平台面主干）
- `CoreShellAPI.h`
  - CoreShell 暴露给上层（MultiCorePE）的最小能力面：`setParentInterface/deliverPacket/hasWork/getUtilization/getStatistics` 等。
  - **推荐主路径**（packet-first + 可插拔 workload）。
- `ICoreWorkload.h` / `WorkloadConfig.h` / `CoreWorkloadFactory.h`
  - Workload 插件契约与工厂：`workload_impl=snn|stream|...`。
  - CoreShell 只持有 `ICoreWorkload`，不持有业务状态机。
- `ISpikeWorkload.h` / `ISnnSpikeCommWorkload.h`
  - Spike 相关的 workload 可选接口（例如 SNN workload 暴露“本地注入/统计/通信”协作点）。

### Utils（轻量工具，避免重复造轮子）
- `SnnDLStringUtil.h`
  - ASCII 小写归一化：`toLowerCopy()`（保持可复现、无 locale 依赖）。
  - 模板占位符替换：`replaceAll()/replaceAllIndexed()/resolvePeCoreTemplate()`（用于 `{pe}/{core}` 等路径模板）。

---

## 内存建模口径（默认 cacheline）

SnnDL 的“通用 DRAM + memHierarchy”默认建模语义是 **cacheline（例如 64B）**：

- `api/IMemoryAccess.h` 只承诺 `addr + size ↔ bytes`，不承诺“行/矩阵 row”语义。
- 论文/报告的 traffic 主口径建议以 memHierarchy 的 MemController 事务统计（`requests_received_*`）为准；
  上层 `memory_bytes` 仅代表逻辑请求（L1；通常为 core 侧 `mem_req_size_bytes` 的汇总派生），不等价于 off-chip 流量（L2）。
- row-streaming/DMA 属于显式架构假设，必须单列结果，避免与 cacheline 结论混算。

### NoC（纯传输：packet-first）
- `INocTransport.h`
  - NoC 抽象接口：`sendFromCore/injectLocal/sendExternal` 等。
  - payload 为 `events/NocPacketEvent`；NoC 域不解析 SpikeEvent/权重语义。
- `ISpikeTransport.h` / `NocSpikeTransport.h`
  - Spike 发送抽象与 NoC 适配器：上层（synapse/route 或 stimulus）通过 `ISpikeTransport` 发出 spike payload，底层映射为 `INocTransport` 的 packet 发送。

### Memory（纯内存：addr↔bytes）
- `IMemoryAccess.h`
  - 纯内存访问接口：只做 `addr+size ↔ bytes`，不携带 weight/synapse/bcsr/route 语义。
  - 典型实现：`services/memory/StandardMemAccess`。
- `ICoreMemoryLink.h`
  - CoreShell 与“内存端点/胶水层”的窄连接面（用于隔离 StandardMem 类型泄露）。

### Synapse（业务语义：weights/route/gas）
- `SnnWeightReader.h`
  - `IWeightReader` 抽象：为 compute core 提供统一权重读取/缓存入口（实现通常在 synapse/weights）。
- `IWeightReaderAdopter.h`
  - 窄接口：将 `IWeightReader` 所有权从装配方（CoreShell）移交给 workload（避免 control/workload 双实例装配）。
- `ISynapseRoute.h` / `SynapseRouteBuildConfig.h`
  - fanout/route 的窄接口：路由构建与查询（语义集中在 synapse 域，不进入 NoC/Memory）。

### GAS/Step（控制面窄接口）
- `IGasCmdSender.h` / `IGasStageSink.h` / `IGasStepGate.h` / `GasOps.h`
  - 阶段事件/统计/门控的窄接口（用于把 Stage 载体与具体实现隔离）。
- `IGasOrchestrator.h`
  - GAS 阶段编排接口（供 `services/synapse/gas` 控制器调用；services 仅依赖 api/，不 include control 实现）。
- `IGlobalStepHooks.h` / `ICoreControlHooks.h`
  - MultiCorePE → core 的注入接口：全局 step start、NoC 注入/门控决策、以及回退的手动驱动（debug/兜底）。
- `IManualWindowDrive.h`（已弃用，仅兼容保留）
  - 旧的“手动窗口驱动”兼容接口头；主线不再依赖/暴露该能力。

### PE 级聚合
- `IPeAggregation.h`
  - 多 core 统计汇聚的窄接口（MultiCorePE 实现；CoreShell/workload 通过窄面上报）。

---

## 兼容性说明（legacy）

- `SnnCoreAPI.h` / `SnnInterface.h` / `SnnPEParentInterface.h`
  - 为历史装配/脚本兼容保留的接口集合；新链路优先使用 `CoreShellAPI + ICoreWorkload` 的主路径。

---

## 依赖边界（必须遵守）

- `api/*` **不应依赖** `control/`、`components/`、`services/` 的实现细节。
- 允许依赖：`SST core` 基础类型（`sst/core/*`）与 C++ 标准库。
- 推荐依赖方向：`components/control/services/compute` → `api`（单向），避免反向依赖。
