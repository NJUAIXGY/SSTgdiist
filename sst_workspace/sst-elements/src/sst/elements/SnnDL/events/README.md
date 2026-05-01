# events/（事件与数据类型层）

本目录存放 **跨组件/跨链路传递的事件类型** 与相关的轻量包装类型，原则上不包含任何动力学/控制逻辑。

## 职责

---

## 内存建模口径（默认 cacheline）提示

事件层不应隐含“权重按整行搬运”的假设：默认体系结构建模语义是 cacheline（memHierarchy）事务，row-streaming/DMA 属于显式架构模式，需在上层装配/实验配置中明确标注并单列结果。

- 定义在 SST 链路与队列中传递的数据载体（spike、门控决策、测试事件等）。
- 保持事件类型稳定，避免因实现重构导致网络/组件互连层破坏。

## 主要内容

- `SpikeEvent.h`
  - SnnDL 的核心通信事件：源 neuron、目的 neuron、目的 PE、权重、时间戳等字段。
- `NocPacketEvent.h`
  - NoC 传输层的通用 packet 载体（payload-agnostic）：NoC 域只处理该事件，不直接处理 `SpikeEvent`。
- `SpikePacket.h`
  - 可选的聚合/打包结构（用于 NIC/网络传输层减少开销的场景）。
- `SpikeEventWrapper.{h,cc}`
  - 用于与 `SimpleNetwork` / `merlin.linkcontrol` 对接的包装层。
- `GatingDecisionEvent.h`
  - 门控决策事件（控制哪些目的 PE 允许被 fanout）。
- `GasStepBarrierEvent.h`
  - Mesh 级 Step/GAS 同步的 barrier 事件载体（配合 `components/gas/GlobalGasStepController`）。
- `SimpleTestEvent.{h,cc}`
  - 轻量测试/验证用事件，便于 debug 或最小链路连通性检查。

## 依赖边界（建议）

- 事件类型应尽量 **只依赖** `sst/core/event.h` 与标准库。
- 不应依赖 `control/` 或 `compute/` 的内部状态结构（避免反向耦合）。

## 语义分层提示（避免“类型层面耦合”）

- `SpikeEvent` 属于 SNN 语义载体（包含突触/目的等字段），应仅在 `synapse/workload/stimulus` 等业务层出现。
- `NocPacketEvent` 属于平台面 packet 载体，应在 `services/noc` 与组件装配层作为传输单位使用。

## 扩展指南

- 新增事件字段时：
  - 明确该字段是“网络/控制需要”还是“动力学内部需要”；后者应留在 compute core 内部，不要塞进事件。
  - 若需要序列化/反序列化能力，保持与 SST Event 机制兼容。
