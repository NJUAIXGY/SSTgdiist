# control/（CoreShell：通用子核壳）

本目录存放 **SnnPESubComponent（CoreShell）** 及其内部实现。CoreShell 的定位是：**每个 PE 内的“通用控制壳”**，只负责把 SST 的时钟/packet/统计汇聚接到可插拔 workload 上；任何业务语义（SNN/Step/GAS/BCSR 或非 SNN stream）都应落在 `services/workload/*` 中。

> 目标：让 CoreShell/NoC/Memory 能复用为“通用仿真核”，workload 可替换而不影响平台面。

---

## 内存建模口径（默认 cacheline）

CoreShell 只负责“发起/接收内存请求并把 bytes 交给 workload”，不负责定义读粒度语义；默认体系结构语义以 memHierarchy 的 **cacheline** 为主：

- traffic 主口径建议以 MemController 的 `requests_received_*`（L2 traffic）为准；
- `memory_bytes` 仅代表上层 logical request（L1），不等价于 off-chip 流量；
- dense 场景下是否允许 row-streaming/DMA 必须作为显式架构模式单列，避免与 cacheline 模式混算。

---

## 职责（CoreShell 只做平台面）

- SST 子组件生命周期对接：`init/setup/finish`、clock 驱动。
- **执行分发**：每拍调用 `workload_->onClockTick(now_cycle)`。
- **packet 递送**：接收来自 NoC 的 `events/NocPacketEvent` 并转交 `workload_->deliverPacket(pkt)`（packet-first）。
- **最小运行时装配**：为 workload 注入通用 runtime 句柄（日志/节点标识/必要的 sink 回调）。
- **统计汇聚**：把 workload 的统计 map 汇总到上层（MultiCorePE）用于写出 `mesh_stats.csv`。

---

## 不做什么（边界冻结）

- 不持有/实现 SNN 业务状态机（GAS window 阶段机、edge/weights 编排、fanout/route 选择、Spike 语义等）。
- `control/*.h/*.cc` **不出现** `StandardMem::`（包括 include `stdMem.h`）。StandardMem glue 必须隔离在 `services/synapse/stdmem/`。
- 不直接依赖 NoC/Mem 的具体实现细节：通过 `api/*` 的窄接口交互。

---

## 主要文件与职责

- `SnnPESubComponent.{h,cc}`
  - CoreShell 本体：解析最小通用参数（`node_id/core_id/workload_impl/verbose` 等），创建并持有 `std::unique_ptr<ICoreWorkload>`。
  - 入口收敛：`clockTick()` 与 `deliverPacket()`。
- `SnnPESubComponent_impl.h`（internal）
  - PImpl 内部状态：统计、reporter、以及对 workload 的 runtime 绑定等“与接口隔离相关”的实现细节。
  - 仅允许被 `.cc` include；禁止在对外头文件传播依赖。
- （隔离文件）`services/synapse/stdmem/SnnPESubComponent_mem.cc`
  - StandardMem glue 实现文件（刻意不放在 `control/`）。

---

## 与 workload 的关系（推荐理解方式）

- CoreShell（本目录）：**平台面**（time/packet/stat）。
- `services/workload/snn`：SNN 业务主链路（输入队列/weights/route/comm/GAS window），并在内部调用 `services/synapse/*`、`services/stimulus/*`。
- `services/workload/stream`：纯通信/纯内存 streaming（read-after-write verify），不依赖 synapse/stimulus/SpikeEvent。

---

## 扩展指南（新增 workload / compute core）

- 新增 workload：在 `services/workload/` 增加实现并注册到 `api/CoreWorkloadFactory.h`，通过 `workload_impl=<name>`（或环境变量 `SNNDL_WORKLOAD_IMPL`）选择。
- 新增 compute core（SNN 内多模型/多范式）：在 `compute/` 实现新的 `ISnnComputeCore`，并由 `workload=snn` 在其内部按参数选择与装配。
