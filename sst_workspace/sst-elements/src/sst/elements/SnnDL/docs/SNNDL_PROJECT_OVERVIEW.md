# SnnDL 源码总览（层次结构与模块边界）

本文是 **SnnDL 源码目录（`SnnDL/`）** 的总览性文档：将各子目录 `README.md` 的信息做有机整合，形成“层次结构 + 职责边界 + 依赖方向 + 主链路数据流 + 扩展点”的统一视图。细节仍以各子目录 `README.md` 与 `docs/SNNDL_HIERARCHY_AND_WORKFLOW.md` 为准。

---

## 1. 一句话介绍（What / Why）

SnnDL 是 SST（Structural Simulation Toolkit）里的一个 Element：用于在 SST 中模拟多核 Processing Element（PE）上运行的脉冲神经网络（SNN）与相关通信/内存工作负载，强调 **平台核（NoC/Mem/CoreShell）可复用**、**业务语义（SNN/GAS/BCSR/Stream/Traffic）可插拔**、以及 **清晰分层与可回归（fail-fast）**。

---

## 2. 源码目录结构（SnnDL/）

SnnDL 的源码按“稳定接口层 / 事件载体层 / SST 装配层 / 通用控制壳 / 可替换 compute / 可复用 services / 文档与自检”分层：

```
SnnDL/
├── api/            # 跨层稳定接口（窄抽象：CoreShell/Workload/NoC/Mem/Synapse 等）
├── events/         # 事件与 payload（SpikeEvent/NocPacketEvent/GatingDecision...）
├── components/     # SST 组件装配壳（ELI 注册对象：MultiCorePE/SnnNIC/GatherBufferIF...）
├── control/        # CoreShell（平台壳：clock/packet/stat；不含业务状态机）
├── compute/        # 可替换 compute core（动力学/模型/学习；不直接触碰 StandardMem/NoC）
├── services/       # 事务子系统（NoC/Mem/Synapse/Stimulus/Workload/Legacy）
├── docs/           # 设计与路线图（含端到端 workflow 文档）
└── tests/          # 编译/包含路径自检
```

目录边界总原则（来自各 README 的共同约束）：
- `components/`：SST 对接与系统装配壳（端口/Link/Clock/Stat/生命周期），尽量不写算法事务。
- `control/`：CoreShell（通用壳）只做 time/packet/stat；业务状态机在 `services/workload/*`。
- `services/noc`：只做 packet 传输（send/recv/forward/本地投递），不解析 Spike 语义、不做 fanout/route。
- `services/memory`：只做纯内存（`addr↔bytes`），不出现 weight/synapse/bcsr/route 语义。
- `services/synapse`：承载突触语义域（weights/route/gas），并通过 `api/` 与平台域交互。
- `compute/`：可替换计算核心；权重通过 `api/SnnWeightReader.h` 注入；不直接触碰 StandardMem/NoC。

---

## 3. 依赖方向（边界硬化）

SnnDL 推荐的依赖方向是：装配层/控制壳/业务链路依赖接口与子系统，避免 services → control 的反向依赖：

```
components/* (装配壳：端口/clock/stat/生命周期)
  └─ control/* (CoreShell：time/packet/stat)
      └─ services/workload/* (业务主链路：snn/stream/traffic)
          ├─ compute/* (动力学/模型；仅 snn 使用)
          ├─ services/synapse/* (weights/route/gas；仅 snn 使用；traffic 可复用 route)
          ├─ services/stimulus/* (Step/外部输入；仅 snn 使用)
          ├─ services/noc/* (纯传输：packet-first；平台面)
          └─ services/memory/* (纯内存：addr→bytes；平台面)
api/* (窄接口)  ← 以上所有层均可依赖（但 api 不反向依赖实现层）
events/* (payload) ← components/services/control 用于跨层传递数据
```

关键“硬边界”例子：
- `control/*.h/*.cc` 不出现 `StandardMem::`（需要 include `stdMem.h` 的 glue 隔离在 `services/synapse/stdmem/`）。
- `services/noc` 不做路由表构建与 fanout；`services/synapse/route` 负责“从 source neuron 到目的集合”的语义与发送事务。
- `services/memory` 的回包只保证 bytes 正确；权重解析（float/idx/rowptr/blockdata 等）必须在 `services/synapse/weights`。

---

## 4. api/（稳定接口层：跨层最小契约）

`api/` 目标：接口窄、平台语义隔离、可插拔 workload、可替换 compute core。

核心接口按域归类：
- CoreShell / Workload（平台主干）：`CoreShellAPI.h`、`ICoreWorkload.h`、`CoreWorkloadFactory.h`、`WorkloadConfig.h`
- NoC（纯传输：packet-first）：`INocTransport.h`、`ISpikeTransport.h`、`NocSpikeTransport.h`
- Memory（纯内存：addr↔bytes）：`IMemoryAccess.h`、`ICoreMemoryLink.h`
- Synapse（业务语义：weights/route）：`SnnWeightReader.h`、`ISynapseRoute.h`、`SynapseRouteBuildConfig.h`
- GAS/Step 控制面窄接口：`IGasCmdSender.h`、`IGasStageSink.h`、`IGasStepGate.h`、`IGlobalStepHooks.h` 等
- 兼容性（legacy）：`SnnCoreAPI.h`、`SnnInterface.h` 等（新链路优先走 `CoreShellAPI + ICoreWorkload`）

---

## 5. events/（事件与数据类型层）

`events/` 定义跨链路/跨组件传递的事件载体（尽量只依赖 `sst/core/event.h` + 标准库）：
- `SpikeEvent.h`：SNN 语义载体（源/目的 neuron、目的 node、权重/时间戳等）
- `NocPacketEvent.h`：NoC 传输层通用 packet 载体（payload-agnostic）
- `NocPacketBatchEvent.h`：可选的 packet 批量载体（用于减少事件开销的场景）
- `SpikeEventWrapper.{h,cc}`：与 `SimpleNetwork`/`merlin.linkcontrol` 对接的包装层
- `GatingDecisionEvent.h`：门控决策事件
- `GasStepBarrierEvent.h`：mesh 级 Step/GAS barrier 载体
- `SimpleTestEvent.{h,cc}`：轻量自检事件

语义分层提示：
- `SpikeEvent` 建议只在业务层（`services/synapse` / `services/workload/snn` / `services/stimulus`）出现。
- `NocPacketEvent` 是平台面载体，建议在 `services/noc` 与装配层作为传输单位。

---

## 6. components/（SST 组件集成层：ELI 注册对象）

`components/` 负责与 SST 框架对接（端口、Link、Clock、Stat、init/setup/finish 生命周期），并将下层模块装配成系统：
- `MultiCorePE.{h,cc}`：PE 顶层组件，装配多个 CoreShell，并驱动平台子系统（NoC/Mem/Stimulus）与统计汇聚
- `SnnNIC.{h,cc}`：NIC，对接 `SimpleNetwork`（如 merlin.linkcontrol）收发 packet
- `GatherBufferIF.{h,cc}`：GAS window 驱动的 StandardMem 前端（阶段/统计 + 数据面读写）
- `WeightLoader.{h,cc}`：权重加载组件（预置到 DRAM/缓存可见区域）
- `GatingPE.{h,cc}`：门控组件，传播 `GatingDecisionEvent`
- `stimulus/SpikeSource.{h,cc}`：可选 spike 源组件（部分场景可能禁用）
- `MemKCalBench.{h,cc}`：micro-benchmark
- `SnnPE.{h,cc}`：旧架构兼容（deprecated/compat）

子目录（可选/扩展）：`components/noc`、`components/gas`、`components/stimulus`。

---

## 7. control/（CoreShell：通用子核壳）

`control/` 的定位是“通用控制壳”：每拍驱动 workload、递送 packet、汇聚统计；业务语义不在这里。

职责：
- 入口收敛：`clockTick()`、`deliverPacket()`
- 执行分发：每拍调用 `workload_->onClockTick(now_cycle)`
- packet-first：将 `events/NocPacketEvent` 转交 `workload_->deliverPacket(pkt)`
- 统计汇聚：将 workload 的统计 map 汇总到上层（如 MultiCorePE）

硬边界：
- `control/*` 不出现 `StandardMem::`（glue 必须隔离到 `services/synapse/stdmem/`）。

---

## 8. compute/（可替换计算核心层）

`compute/` 目标是支持“替换核心计算范式”，而无需改动平台壳（CoreShell）：
- `ISnnComputeCore.h`：compute core 主契约与工厂声明
- `SnnComputeCore.{h,cc}`：默认实现 `DefaultSnnComputeCore`（动力学/学习/验证）与 `createComputeCoreByName()` 工厂
- `SnnNeuronModel.h`：神经元模型选择（LIF 等）
- `IWeightAwareComputeCore.h`：可选扩展接口（仅当确需 legacy 权重语义）

约束与建议：
- compute 不直接触碰 StandardMem/NoC；权重访问通过 `ComputeCoreContext.weight_reader`（`api/SnnWeightReader.h`）注入。

---

## 9. services/（可复用服务/子系统）

`services/` 将复杂事务从 `components/` 与 `control/` 下沉为可复用子系统，并通过 `api/` 的窄接口交互。

### 9.1 NoC 域：`services/noc/`

实现 `api/INocTransport.h`，只做“传输”：send/recv/forward/本地投递，不解析 Spike 语义、不构建路由表。

### 9.2 Memory 域：`services/memory/`

实现 `api/IMemoryAccess.h`，只做“`addr+size ↔ bytes`”。典型实现：`StandardMemAccess.{h,cc}`，包含断言式诊断（例如 `resp_bytes < req_bytes` 直接 fail-fast）。

### 9.3 Synapse 域：`services/synapse/`（突触语义闭环）

Synapse 域聚合权重/路由/GAS 窗口辅助，并保持与 NoC/Mem 的边界清晰：
- `services/synapse/weights/`：权重语义与缓存子系统（`WeightMemorySubsystem` 实现 `IWeightReader`）
- `services/synapse/route/`：路由构建与通信事务（`SynapseRouteSubsystem` 实现 `ISynapseRoute`；`SpikeCommSubsystem` 负责 fanout + SpikeEvent 构造与发送）
- `services/synapse/gas/`：GAS 窗口辅助（edge collector、accumulator、custom cmd/统计载体）
- `services/synapse/common/`：BCSR `.meta.json` 解析与校验口径（小而稳定，避免重复实现/口径漂移）
- `services/synapse/stdmem/`：StandardMem 胶水层（隔离 `StandardMem::*`，避免污染 `control/`）

关于 Native Multicast（SpikeKey）在源码内的语义落点：
- 构建期：`services/synapse/route` 可将目的集合聚合为 block target（含 ingress 与 `core_mask[cell]`）
- 运行期：以 `events/NocPacketEvent(kind=SpikeKey)` 作为载体，交给 NoC/router 路径完成两阶段路由与块内投递
- 约束口径：`multicast_block_w * multicast_block_h <= 64`，`cores_per_pe <= 32`

### 9.4 Stimulus 域：`services/stimulus/`

负责“何时注入/注入哪些源”，通过 `api/INocTransport` 完成本地投递/外发，不触碰 NoC 实现细节。

### 9.5 Workload 插件域：`services/workload/`

Workload 决定“业务语义与主链路闭环”。选择优先级：组件参数 `workload_impl` → 环境变量 `SNNDL_WORKLOAD_IMPL` → 默认 `snn`。
- `services/workload/snn/`：SNN 主链路（Spike/GAS/BCSR/Step），内部组合 compute + synapse + stimulus
- `services/workload/stream/`：非 SNN streaming workload（packet-first + 内存 read-after-write 校验），不得依赖 `SpikeEvent`/`synapse/*`/`stimulus/*`
- `services/workload/traffic/`：通信/多播验证 workload（不建模动力学；允许复用 `services/synapse/route` 的 fanout/multicast 构建）

### 9.6 Legacy：`services/legacy/`

历史遗留/参考实现（默认不参与主链路构建），用于兼容与对照。

---

## 10. 端到端主链路（packet-first）

推荐用“packet-first + workload 可插拔”理解 SnnDL 的端到端闭环（细节见 `docs/SNNDL_HIERARCHY_AND_WORKFLOW.md`）：
1) `components/MultiCorePE` 装配：core（CoreShell）、NIC、内存前端、必要的子系统与统计。
2) `control/SnnPESubComponent` 每拍驱动 workload，并将 `NocPacketEvent` 递送给 workload（packet-first）。
3) `workload=snn` 内：compute core 产出 fire events → `services/synapse/route/SpikeCommSubsystem` 做 fanout 与 SpikeEvent 构造 → 通过 `ISpikeTransport/INocTransport` 注入 NoC。
4) `services/noc/NocSubsystem` 负责传输：本地投递到目标 core 或外发到网络。
5) 目标侧 packet 解码回业务事件，递送到目标 core 的 workload，进入下一轮闭环。

---

## 11. 扩展指南（最小改动路径）

- 新增 workload：在 `services/workload/` 增加实现，并注册到 `api/CoreWorkloadFactory.h`，通过 `workload_impl=<name>` 选择。
- 新增 compute core：在 `compute/` 实现新的 `ISnnComputeCore`，并在 `createComputeCoreByName()` 注册名称（保持 GAS/Spike/Synapse 语义不变）。
- 新增 neuron model：扩展 `compute/SnnNeuronModel.h` 的 `NeuronModelType` 与 `createNeuronModel()` 分支，保持默认参数有合理兜底。

---

## 12. docs/ 与 tests/（阅读入口与自检）

推荐阅读顺序（只在 SnnDL 内部跳转）：
1) `README.md`
2) `docs/SNNDL_HIERARCHY_AND_WORKFLOW.md`（总览：Hierarchy + 接口 + 数据流）
3) 分层 README：`api/README.md`、`components/README.md`、`control/README.md`、`compute/README.md`、`services/README.md`
4) 设计与路线图：`docs/README.md`、`docs/plans/README.md`（完成态 DoD/清单见对应 plan）

自检：
- `tests/test_includes.cc`：include/依赖路径的编译自检（用于避免重构后隐式依赖问题）

---

## 13. 构建与安装（修改生效必须 install）

```bash
cd "sst_workspace/sst-elements/src/sst/elements/SnnDL"
make -j4
make install
```

---

## 14. 文件级地图（按目录展开，便于快速定位）

这一节的目标很朴素：当你需要“改某个行为/查某条链路”时，能快速知道应该打开哪些文件。

说明：下表中的“主要符号/标题”来自 **文件头部的自动提取**（只扫描文件前几百行）：
- `include:"..."`：该文件开头出现的第一条本地 `#include "..."`（通常能指示 `.cc` 主要实现哪个头文件）
- `types:...`：文件头部出现的 `class/struct/enum` 名称集合（用于快速定位承载类型）
- `ns:...`：文件头部出现的 `namespace` 名称集合
- `ELI:...`：若文件中包含 SST ELI 注册宏，会列出注册名（对组件层尤为有用）

如何把它当作“每个文件的作用”来读：
- `doc`：对应文档说明（以标题为主线入口）
- `header`：主要承载声明/接口（看 `types:` 能快速知道它定义了哪些关键类型）
- `source`：主要承载实现（看 `include:"..."` 通常能快速定位它实现/支撑的头文件入口）
- `build`：构建清单与编译安装相关文件

为保持可读性，按目录拆分到多个可折叠块中。

常见“从需求到文件”的快速跳转（先看这些通常能最快进入代码语境）：
- 想改 `workload_impl` 的选择与装配：`api/ICoreWorkload.h`、`api/CoreWorkloadFactory.h`、`services/workload/CoreWorkloadFactory.cc`、`control/SnnPESubComponent.cc`
- 想改 packet-first 的投递/外发路径：`api/INocTransport.h`、`services/noc/NocSubsystem.{h,cc}`、`components/SnnNIC.{h,cc}`
- 想改 SpikeEvent ↔ packet 的编解码/桥接：`events/NocPacketEvent.h`、`services/synapse/route/SpikeNocCodec.h`、`services/synapse/route/SpikePacketBridge.{h,cc}`
- 想改 fanout/路由构建与 gating：`api/ISynapseRoute.h`、`services/synapse/route/SynapseRouteSubsystem.{h,cc}`、`services/synapse/route/SnnRouteProvider.{h,cc}`
- 想改 native multicast（SpikeKey）载体与约束：`api/MulticastLimits.h`、`api/SynapseRouteBuildConfig.h`、`services/synapse/route/SpikeNocCodec.h`、`components/noc/MulticastRouter.{h,cc}`
- 想改权重读取/BCSR/缓存：`api/SnnWeightReader.h`、`services/synapse/weights/WeightMemorySubsystem.{h,cc}`、`services/synapse/weights/SnnBcsrWeightManager.{h,cc}`、`services/synapse/common/BcsrMeta.h`
- 想改 GAS 窗口的 edge/累加器辅助：`services/synapse/gas/GasEdgeCollector.{h,cc}`、`services/synapse/gas/AccumulatorOps.{h,cc}`、`services/synapse/gas/GasCustomCmd.h`
- 想改 StandardMem glue 与阶段事件分发：`services/synapse/stdmem/StdMemEndpoint.{h,cc}`、`services/memory/StandardMemAccess.{h,cc}`、`components/GatherBufferIF.{h,cc}`

<details>
<summary><b>根目录文件（SnnDL/）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `ISnnComputeCore_SPEC.md` | `doc` | ISnnComputeCore 接口契约说明（冻结版） |
| `Makefile.am` | `build` |  |
| `Makefile.in` | `build` |  |
| `README.md` | `doc` | SnnDL（SST Element：Spiking Neural Network / Deep Learning） |

</details>

<details>
<summary><b>api/（跨层接口与窄抽象）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `api/CoreShellAPI.h` | `header` | types:IPeAggregation, NocPacketEvent, CoreShellAPI; ns:SST |
| `api/CoreWorkloadFactory.h` | `header` | types:ICoreWorkload; ns:SST |
| `api/GasOps.h` | `header` | types:GasOp; ns:SST |
| `api/GlobalNeuronLayout.h` | `header` | types:GlobalNeuronLayout; ns:SST |
| `api/ICoreControlHooks.h` | `header` | types:INocTransport, ICoreControlHooks; ns:SST |
| `api/ICoreMemoryLink.h` | `header` | types:ICoreMemoryLink; ns:SST |
| `api/ICoreWorkload.h` | `header` | types:Output, Params, Statistic, IMemoryAccess, INocTransport, NocPacketEvent, ICoreWorkload, Sinks, Reporting, TimeSource, Runtime; ns:SST |
| `api/IGasCmdSender.h` | `header` | include:"GasOps.h"; types:IGasCmdSender; ns:SST |
| `api/IGasOrchestrator.h` | `header` | types:IGasOrchestrator; ns:SST |
| `api/IGasStageSink.h` | `header` | include:"GasOps.h"; types:GasStageEvent, GasStatEvent, IGasStageSink; ns:SST |
| `api/IGasStepGate.h` | `header` | types:IGasStepGate; ns:SST |
| `api/IGlobalStepHooks.h` | `header` | types:IGlobalStepHooks; ns:SST |
| `api/IManualWindowDrive.h` | `header` | types:IManualWindowDrive; ns:SST |
| `api/IMemoryAccess.h` | `header` | types:IMemoryAccess; ns:SST |
| `api/INocTransport.h` | `header` | types:NocPacketEvent, INocTransport; ns:SST |
| `api/IPeAggregation.h` | `header` | types:IPeAggregation; ns:SST |
| `api/ISnnSpikeCommWorkload.h` | `header` | types:ISnnSpikeCommWorkload; ns:SST |
| `api/ISpikeTransport.h` | `header` | include:"SpikeEvent.h"; types:ISpikeTransport; ns:SST |
| `api/ISpikeWorkload.h` | `header` | include:"ICoreWorkload.h"; types:SpikeEvent, ISpikeWorkload; ns:SST |
| `api/ISynapseRoute.h` | `header` | types:ISynapseRoute, FanoutEntry; ns:SST |
| `api/MulticastLimits.h` | `header` | ns:SST |
| `api/NocSpikeTransport.h` | `header` | include:"INocTransport.h"; types:NocSpikeTransport; ns:SST |
| `api/README.md` | `doc` | api/（稳定接口层：跨层最小契约） |
| `api/SnnCoreAPI.h` | `header` | include:"CoreShellAPI.h"; types:SpikeEvent, NocPacketEvent, IPeAggregation, SnnCoreAPI; ns:SST, SnnDL |
| `api/SnnInterface.h` | `header` | types:SnnInterface; ns:SST, SnnDL |
| `api/SnnPEParentInterface.h` | `header` | types:SpikeEvent, SnnPEParentInterface; ns:SST, SnnDL |
| `api/SnnWeightReader.h` | `header` | types:IWeightReader, CallbackWeightReader; ns:SST, SnnDL |
| `api/SynapseRouteBuildConfig.h` | `header` | include:"MulticastLimits.h"; types:SynapseRouteBuildConfig; ns:SST |
| `api/WorkloadConfig.h` | `header` | ns:SST |

</details>

<details>
<summary><b>events/（事件载体与跨层 payload）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `events/GasStepBarrierEvent.h` | `header` | types:GasStepBarrierOp, GasStepBarrierEvent; ns:SST |
| `events/GatingDecisionEvent.h` | `header` | types:GatingDecisionEvent; ns:SST |
| `events/NocPacketBatchEvent.h` | `header` | types:NocPacketBatchEvent, PackedPacket; ns:SST |
| `events/NocPacketEvent.h` | `header` | types:NocPacketKind, NocPacketEvent; ns:SST |
| `events/README.md` | `doc` | events/（事件与数据类型层） |
| `events/SimpleTestEvent.cc` | `source` | include:"SimpleTestEvent.h"; ns:SST, SnnDL |
| `events/SimpleTestEvent.h` | `header` | types:SimpleTestEvent; ns:SST, SnnDL |
| `events/SpikeEvent.h` | `header` | types:SpikeEvent; ns:SST, SnnDL |
| `events/SpikeEventWrapper.cc` | `source` | include:"SpikeEventWrapper.h"; ns:SST, SnnDL |
| `events/SpikeEventWrapper.h` | `header` | include:"SpikeEvent.h"; types:SpikeEventWrapper; ns:SST, SnnDL |
| `events/SpikePacket.h` | `header` | include:"SpikeEvent.h"; types:SpikePacketHeader, SpikePacket; ns:SST |

</details>

<details>
<summary><b>components/（SST ELI 组件装配层）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `components/GatherBufferIF.cc` | `source` | include:"GatherBufferIF.h" |
| `components/GatherBufferIF.h` | `header` | include:"IGasStepGate.h"; types:GatherBufferIF, Stage, Merge, Sort, SubReq, Granule, DownFrag; ns:SST |
| `components/GatingPE.cc` | `source` | include:"GatingPE.h" |
| `components/GatingPE.h` | `header` | types:GatingPE, Range, Transition, SnnInterface; ns:SST |
| `components/MemKCalBench.cc` | `source` | include:"MemKCalBench.h" |
| `components/MemKCalBench.h` | `header` | types:MemKCalBench, Test, Phase; ns:SST |
| `components/MultiCorePE.cc` | `source` | include:"MultiCorePE.h" |
| `components/MultiCorePE.h` | `header` | include:"SpikeEvent.h"; types:MultiCoreController, SnnNetworkAdapter, NocPacketEvent, ProcessingUnitState, MultiCorePE; ns:SST, SnnDL |
| `components/README.md` | `doc` | components/（SST 组件集成层） |
| `components/SnnNIC.cc` | `source` | include:"SnnNIC.h" |
| `components/SnnNIC.h` | `header` | include:"SnnInterface.h"; types:SnnNIC, PendingSend, BatchBucket; ns:SST, SnnDL |
| `components/SnnPE.cc` | `source` | include:"SnnPE.h" |
| `components/SnnPE.h` | `header` | include:"SpikeEvent.h"; types:PendingRequest, NeuronState, SnnPE; ns:SST, SnnDL |
| `components/WeightLoader.cc` | `source` | include:"WeightLoader.h"; types:Sample |
| `components/WeightLoader.h` | `header` | types:WeightLoader, TimedRawJob, VerifyPending; ns:SST, SnnDL |

<details>
<summary><b>components/gas/（全局 Step/GAS 同步）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `components/gas/GlobalGasStepController.cc` | `source` | include:"gas/GlobalGasStepController.h"; ns:SST |
| `components/gas/GlobalGasStepController.h` | `header` | types:GlobalGasStepController; ns:SST |
| `components/gas/README.md` | `doc` | components/gas/（全局 Step/GAS 同步组件） |

</details>

<details>
<summary><b>components/noc/（可加载 NoC/拓扑适配与多播 router）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `components/noc/MulticastNIC.cc` | `source` | include:"MulticastNIC.h"; ns:SST |
| `components/noc/MulticastNIC.h` | `header` | include:"SnnInterface.h"; types:MulticastNIC; ns:SST |
| `components/noc/MulticastRouter.cc` | `source` | include:"MulticastRouter.h"; ns:SST |
| `components/noc/MulticastRouter.h` | `header` | types:NocPacketEvent, MulticastRouter; ns:SST |
| `components/noc/README.md` | `doc` | components/noc/（ELI 可加载 NoC/拓扑适配组件） |
| `components/noc/SimpleNetworkWrapper.cc` | `source` | include:"SimpleNetworkWrapper.h"; ns:SST, SnnDL |
| `components/noc/SimpleNetworkWrapper.h` | `header` | types:SnnNetworkAdapter, NetworkEventConverter, SimpleNetworkWrapper; ns:SST, SnnDL |
| `components/noc/SnnNetworkAdapter.cc` | `source` | include:"SnnNetworkAdapter.h"; ns:SST, SnnDL |
| `components/noc/SnnNetworkAdapter.h` | `header` | include:"SnnInterface.h"; types:TopologyHandler, NetworkEventConverter, SimpleNetworkWrapper, SnnNetworkAdapter; ns:SST, SnnDL |

</details>

<details>
<summary><b>components/stimulus/（注入型组件）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `components/stimulus/README.md` | `doc` | components/stimulus/（Stimulus 注入型组件） |
| `components/stimulus/SpikeSource.cc` | `source` | include:"SpikeSource.h" |
| `components/stimulus/SpikeSource.h` | `header` | include:"SpikeEvent.h"; types:SpikeData, SpikeSource; ns:SST, SnnDL |

</details>

</details>

<details>
<summary><b>control/（CoreShell：通用子核壳）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `control/README.md` | `doc` | control/（CoreShell：通用子核壳） |
| `control/SnnPEApplyScatter.cc` | `source` | include:"SnnPESubComponent.h" |
| `control/SnnPEOrchestrators.cc` | `source` | include:"SnnPESubComponent.h" |
| `control/SnnPESubComponent.cc` | `source` | include:"SnnPESubComponent.h" |
| `control/SnnPESubComponent.h` | `header` | include:"SnnCoreAPI.h"; types:SpikeEvent, NocSpikeTransport, BcsrWeightManager, StdMemEndpoint, ISnnSpikeCommWorkload, IGasStageSink, IWeightReader, IPeAggregation, AccumulatorOps, WeightCacheOps, WeightAccessor; ns:SST |
| `control/SnnPESubComponent_bcsr.cc` | `source` | include:"SnnPESubComponent.h" |
| `control/SnnPESubComponent_impl.h` | `header` | include:"SnnPESubComponent.h"; types:GasPhaseController, SnnPESubComponent; ns:SST |
| `control/SnnPESubComponent_routing.cc` | `source` | include:"SnnPESubComponent.h" |
| `control/SnnPESubComponent_scheme1.cc` | `source` | include:"SnnPESubComponent.h" |
| `control/SnnPESubComponent_spike.cc` | `source` | include:"SnnPESubComponent.h" |

</details>

<details>
<summary><b>compute/（可替换计算核心）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `compute/ISnnComputeCore.h` | `header` | types:Output, Params, SpikeEvent, IWeightReader, INeuronModel, ComputeCoreContext, FireEvent, SynapticEvent, NeuronStateSnapshot, LearningEvent, ComputeCoreCapabilities, ISnnComputeCore; ns:SST |
| `compute/IWeightAwareComputeCore.h` | `header` | types:IWeightAwareComputeCore; ns:SST |
| `compute/README.md` | `doc` | compute/（可替换计算核心层） |
| `compute/SnnComputeCore.cc` | `source` | include:"SnnComputeCore.h"; ns:SST |
| `compute/SnnComputeCore.h` | `header` | include:"SpikeEvent.h"; types:DefaultSnnComputeCore, GasStage; ns:SST |
| `compute/SnnCoreEngine.cc` | `source` | include:"SnnCoreEngine.h"; ns:SST, SnnDL |
| `compute/SnnCoreEngine.h` | `header` | include:"SnnNeuronModel.h"; types:SnnCoreNeuronState, SnnCoreConfig, SnnCoreEngine; ns:SST, SnnDL |
| `compute/SnnLearningCore.cc` | `source` | include:"SnnLearningCore.h"; ns:SST |
| `compute/SnnLearningCore.h` | `header` | types:LearningSynapticEvent, ILearningCore, DefaultLearningCore, SpikeRecord; ns:SST |
| `compute/SnnNeuronModel.h` | `header` | types:ModelConfig, NeuronModelType, INeuronModel, LIFModel, IzhikevichModel, AdExModel; ns:SST |
| `compute/SnnWeightDiagnostics.cc` | `source` | include:"SnnWeightDiagnostics.h"; ns:SST |
| `compute/SnnWeightDiagnostics.h` | `header` | include:"synapse/weights/SnnBcsrWeightManager.h"; types:SnnWeightDiagnostics; ns:SST |
| `compute/SynapseManager.h` | `header` | types:SynapseManager; ns:SST |

</details>

<details>
<summary><b>services/（事务子系统集合）</b></summary>

<details>
<summary><b>services/（目录根部）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/README.md` | `doc` | services/（可复用服务/子系统） |
| `services/SnnProfiler.h` | `header` | types:CycleTimer, ProfileZone, Profiler, ZoneStats; ns:SST, SnnDL |

</details>

<details>
<summary><b>services/noc/（NoC 传输域）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/noc/NocSubsystem.cc` | `source` | include:"NocSubsystem.h"; ns:SST |
| `services/noc/NocSubsystem.h` | `header` | include:"INocTransport.h"; types:OptimizedInternalRing, SnnInterface, NocSubsystem, Config, Runtime, Stats; ns:SST |
| `services/noc/OptimizedInternalRing.cc` | `source` | include:"OptimizedInternalRing.h" |
| `services/noc/OptimizedInternalRing.h` | `header` | types:RingMessageType, RingMessage, RouteDirection, VCState, VirtualChannel, RingNode, OptimizedInternalRing; ns:SST |
| `services/noc/README.md` | `doc` | services/noc/（NoC 传输子系统） |

</details>

<details>
<summary><b>services/memory/（纯内存 addr↔bytes）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/memory/README.md` | `doc` | services/memory/（纯内存访问子系统） |
| `services/memory/StandardMemAccess.cc` | `source` | include:"StandardMemAccess.h"; ns:SST |
| `services/memory/StandardMemAccess.h` | `header` | include:"IMemoryAccess.h"; types:StandardMemAccess, PendingEntry; ns:SST |

</details>

<details>
<summary><b>services/stimulus/（注入/刺激域）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/stimulus/ExternalSpikeInputSubsystem.cc` | `source` | include:"ExternalSpikeInputSubsystem.h"; ns:SST |
| `services/stimulus/ExternalSpikeInputSubsystem.h` | `header` | types:GlobalNeuronLayout, INocTransport, SpikeEvent, ExternalSpikeInputSubsystem, Runtime; ns:SST |
| `services/stimulus/README.md` | `doc` | services/stimulus/（Stimulus 刺激/注入子系统） |
| `services/stimulus/StepActivationSubsystem.cc` | `source` | include:"StepActivationSubsystem.h"; ns:SST |
| `services/stimulus/StepActivationSubsystem.h` | `header` | types:SpikeEvent, INocTransport, GlobalNeuronLayout, StepActivationSubsystem, Config, Runtime, Stats; ns:SST |

</details>

<details>
<summary><b>services/synapse/（突触语义域：weights/route/gas/stdmem/common）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/synapse/README.md` | `doc` | services/synapse/（突触语义域：Synapse 事务闭环） |

<details>
<summary><b>services/synapse/common/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/synapse/common/BcsrMeta.h` | `header` | types:BcsrMeta; ns:SST |
| `services/synapse/common/README.md` | `doc` | services/synapse/common/（Synapse 公共工具：BCSR 元信息口径） |

</details>

<details>
<summary><b>services/synapse/gas/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/synapse/gas/AccumulatorOps.cc` | `source` | include:"AccumulatorOps.h"; ns:SST |
| `services/synapse/gas/AccumulatorOps.h` | `header` | types:Output, AccumulatorOpsConfig, AccumulatorOps; ns:SST |
| `services/synapse/gas/GasCustomCmd.h` | `header` | include:"GasOps.h"; types:GasOpData, GasStatData; ns:SST |
| `services/synapse/gas/GasEdgeCollector.cc` | `source` | include:"GasEdgeCollector.h"; ns:SST |
| `services/synapse/gas/GasEdgeCollector.h` | `header` | types:GasEdgeCollector; ns:SST |
| `services/synapse/gas/GasPhaseController.cc` | `source` | include:"GasPhaseController.h" |
| `services/synapse/gas/GasPhaseController.h` | `header` | types:IGasOrchestrator, GasPhaseController; ns:SST |
| `services/synapse/gas/README.md` | `doc` | services/synapse/gas/（GAS 窗口与累加辅助子系统） |

</details>

<details>
<summary><b>services/synapse/route/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/synapse/route/BcsrRouteBuilder.cc` | `source` | include:"synapse/route/BcsrRouteBuilder.h"; ns:SST |
| `services/synapse/route/BcsrRouteBuilder.h` | `header` | include:"ISynapseRoute.h"; types:BcsrAppendOptions; ns:SST |
| `services/synapse/route/README.md` | `doc` | services/synapse/route/（Synapse/Route 路由与通信事务子系统） |
| `services/synapse/route/SnnRouteProvider.cc` | `source` | include:"SnnRouteProvider.h"; ns:SST |
| `services/synapse/route/SnnRouteProvider.h` | `header` | include:"ISynapseRoute.h"; types:GatingEntry, SnnRouteProvider, Config; ns:SST, Statistics |
| `services/synapse/route/SpikeCommSubsystem.cc` | `source` | include:"SpikeCommSubsystem.h"; ns:SST |
| `services/synapse/route/SpikeCommSubsystem.h` | `header` | include:"ISpikeTransport.h"; types:SpikeEvent, INocTransport, SpikeCommRuntimeConfig, SpikeCommSubsystem; ns:SST |
| `services/synapse/route/SpikeNocCodec.h` | `header` | include:"api/MulticastLimits.h"; types:SpikeNocCodec, WireSpike, WireSpikeKeyV1, WireSpikeKeyV2; ns:SST |
| `services/synapse/route/SpikePacketBridge.cc` | `source` | include:"SpikePacketBridge.h"; ns:SST |
| `services/synapse/route/SpikePacketBridge.h` | `header` | types:GlobalNeuronLayout, INocTransport, NocPacketEvent, SpikeEvent, SpikePacketBridge, Runtime; ns:SST |
| `services/synapse/route/SpikePacketTransport.h` | `header` | include:"ISpikeTransport.h"; types:SpikePacketTransport; ns:SST |
| `services/synapse/route/StepBcsrReachability.cc` | `source` | include:"synapse/route/StepBcsrReachability.h"; ns:SST |
| `services/synapse/route/StepBcsrReachability.h` | `header` | include:"ISynapseRoute.h"; types:StepBcsrReachabilityConfig, StepBcsrReachabilityRuntime; ns:SST |
| `services/synapse/route/SynapseRouteSubsystem.cc` | `source` | include:"SynapseRouteSubsystem.h"; types:IngressPolicy; ns:SST |
| `services/synapse/route/SynapseRouteSubsystem.h` | `header` | include:"ISynapseRoute.h"; types:SynapseRouteSubsystem, BlockTarget; ns:SST |

</details>

<details>
<summary><b>services/synapse/stdmem/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/synapse/stdmem/README.md` | `doc` | services/synapse/stdmem/（StandardMem 胶水层：隔离 StandardMem 类型） |
| `services/synapse/stdmem/SnnPESubComponent_mem.cc` | `source` | include:"SnnPESubComponent.h" |
| `services/synapse/stdmem/StdMemEndpoint.cc` | `source` | include:"synapse/stdmem/StdMemEndpoint.h"; types:StdMemEndpoint; ns:SST |
| `services/synapse/stdmem/StdMemEndpoint.h` | `header` | include:"IGasCmdSender.h"; types:IGasStageSink, IGasStepGate, IMemoryAccess, StdMemEndpoint, Config, Runtime, Impl; ns:SST |

</details>

<details>
<summary><b>services/synapse/weights/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/synapse/weights/README.md` | `doc` | services/synapse/weights/（权重语义与缓存子系统） |
| `services/synapse/weights/SnnBcsrWeightManager.cc` | `source` | include:"SnnBcsrWeightManager.h" |
| `services/synapse/weights/SnnBcsrWeightManager.h` | `header` | types:BcsrWeightManager, BlockCachePolicy, BlockCacheEntry; ns:SST, SnnDL |
| `services/synapse/weights/SnnWeightDiagnostics.cc` | `source` | include:"synapse/weights/SnnWeightDiagnostics.h"; ns:SST |
| `services/synapse/weights/SnnWeightDiagnostics.h` | `header` | include:"synapse/weights/SnnBcsrWeightManager.h"; types:SnnWeightDiagnostics; ns:SST |
| `services/synapse/weights/WeightAccessor.cc` | `source` | include:"WeightAccessor.h"; ns:SST |
| `services/synapse/weights/WeightAccessor.h` | `header` | types:WeightAccessorConfig, WeightAccessor; ns:SST |
| `services/synapse/weights/WeightCacheOps.cc` | `source` | include:"WeightCacheOps.h"; ns:SST |
| `services/synapse/weights/WeightCacheOps.h` | `header` | types:WeightCacheOps, Config, CacheEntry; ns:SST |
| `services/synapse/weights/WeightMemorySubsystem.cc` | `source` | include:"WeightMemorySubsystem.h" |
| `services/synapse/weights/WeightMemorySubsystem.h` | `header` | include:"synapse/gas/GasEdgeCollector.h"; types:BcsrWeightManager, WeightMemorySubsystem, WindowCounters, OrchestratorConfig; ns:SST |

</details>

</details>

<details>
<summary><b>services/workload/（可插拔 workload 域）</b></summary>

<details>
<summary><b>services/workload/（目录根部）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/workload/CoreWorkloadFactory.cc` | `source` | include:"CoreWorkloadFactory.h"; ns:SST |
| `services/workload/README.md` | `doc` | services/workload/（Workload 插件域） |

</details>

<details>
<summary><b>services/workload/snn/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/workload/snn/README.md` | `doc` | services/workload/snn/（SNN Workload：Spike/GAS/BCSR/Step 主链路） |
| `services/workload/snn/SnnWorkload.cc` | `source` | include:"workload/snn/SnnWorkload.h"; ns:SST |
| `services/workload/snn/SnnWorkload.h` | `header` | include:"IGasStageSink.h"; types:SpikeEvent, NocPacketEvent, ISnnComputeCore, IWeightReader, WeightMemorySubsystem, WeightCacheOps, BcsrWeightManager, WeightAccessor, AccumulatorOps, SynapseRouteSubsystem, SpikeCommSubsystem, NocSpikeTransport, SynapseRouteBuildConfig, SnnWorkload; ns:SST |

</details>

<details>
<summary><b>services/workload/stream/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/workload/stream/README.md` | `doc` | services/workload/stream/（Stream Workload：packet-first 通信 + 内存校验） |
| `services/workload/stream/StreamWorkload.cc` | `source` | include:"workload/stream/StreamWorkload.h"; types:StreamMsgType; ns:SST |
| `services/workload/stream/StreamWorkload.h` | `header` | include:"ICoreWorkload.h"; types:IMemoryAccess, INocTransport, NocPacketEvent, StreamWorkload, Config, MemReq; ns:SST |

</details>

<details>
<summary><b>services/workload/traffic/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/workload/traffic/README.md` | `doc` | services/workload/traffic/（Traffic Workload：通信/多播验证专用负载） |
| `services/workload/traffic/TrafficWorkload.cc` | `source` | include:"workload/traffic/TrafficWorkload.h"; types:SpikeKeyGroupState, SpikeKeyGroupSummary, SpikeKeyGroupBadDetail, SpikeKeyGroupTracker; ns:SST |
| `services/workload/traffic/TrafficWorkload.h` | `header` | include:"api/ICoreWorkload.h"; types:NocSpikeTransport, SpikeCommSubsystem, SynapseRouteSubsystem, TrafficWorkload; ns:SST |

</details>

</details>

<details>
<summary><b>services/legacy/（历史遗留/参考实现）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/legacy/README.md` | `doc` | services/legacy/（历史遗留/参考实现） |

<details>
<summary><b>services/legacy/control/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/legacy/control/README.md` | `doc` | services/legacy/control/（历史控制面参考实现） |
| `services/legacy/control/StageEventHub.cc` | `source` | include:"StageEventHub.h"; ns:SST |
| `services/legacy/control/StageEventHub.h` | `header` | types:SnnPESubComponent, StageEventHub; ns:SST |

</details>

<details>
<summary><b>services/legacy/memory/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/legacy/memory/README.md` | `doc` | services/legacy/memory/（历史内存参考目录：已清空） |

</details>

<details>
<summary><b>services/legacy/noc/</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `services/legacy/noc/README.md` | `doc` | services/legacy/noc/（历史 NoC 参考目录：已清空） |

</details>

</details>

</details>

<details>
<summary><b>docs/ 与 docs/plans/（设计文档与阶段计划）</b></summary>

| 文件 | 类型 | 标题（从文件头提取） |
|---|---|---|
| `docs/BCSR_WEIGHT_GENERATION_GUIDE.md` | `doc` | BCSR 权重文件：生成 / 校验 / 加载指南 |
| `docs/README.md` | `doc` | docs/（设计与重构文档） |
| `docs/SNNDL_HIERARCHY_AND_WORKFLOW.md` | `doc` | SnnDL 层次结构与工作流（以 4×4 Mesh 模板为例） |
| `docs/SNNDL_PROJECT_OVERVIEW.md` | `doc` | SnnDL 源码总览（层次结构与模块边界） |
| `docs/SUBSYSTEM_MODULARIZATION_ROADMAP.md` | `doc` | SnnDL 子系统化终局路线图（Memory / Synapse+Route / Stimulus / NoC / NeuralCompute） |
| `docs/UNIVERSAL_CONTROL_CORE_DESIGN.md` | `doc` | 通用控制子核设计：Compute Core 可替换 + 内存/通信子系统化 |

| 文件 | 类型 | 标题（从文件头提取） |
|---|---|---|
| `docs/plans/2026-01-03-universal-core-completion.md` | `doc` | 通用计算核“完成态”（packet-first + 可插拔 workload）验收口径 |
| `docs/plans/2026-01-10-gas-window-load-driven.md` | `doc` | GAS Window（Gather/Apply/Scatter）负载驱动阶段控制：实施计划 |
| `docs/plans/README.md` | `doc` | docs/plans/（阶段计划与设计草案集合） |

</details>

<details>
<summary><b>tests/（编译/包含路径自检）</b></summary>

| 文件 | 类型 | 主要符号/标题（从文件头提取） |
|---|---|---|
| `tests/README.md` | `doc` | tests/（测试与编译自检） |
| `tests/test_includes.cc` | `source` | include:"control/SnnPESubComponent.h" |

</details>
