# services/noc/（NoC 传输子系统）

本目录存放 **NoC（Network-on-Chip）传输域** 的实现，目标是把 *send/recv/forward/本地投递* 的事务从 `components/MultiCorePE.*` 中下沉出来，并通过 `api/INocTransport.h` 冻结跨层调用面。

> 边界原则：NoC **只做“传输”**，不做 fanout 选择、不解析权重/BCSR、不构建路由表。

---

## 内存建模口径（默认 cacheline）提示

NoC 域与内存建模正交：默认体系结构语义以 memHierarchy 的 cacheline 事务模型为主；若某实验引入 row-streaming/DMA 等显式搬运假设，必须在上层模板/元数据中标注并单列结果，避免与 cacheline 结论混算。

---

## 目录结构与组件职责

### `NocSubsystem.{h,cc}`
- **定位**：NoC 编排/适配层；实现 `api/INocTransport.h`。
- **解决的问题**：
  - 统一收敛输入侧：NIC 回调、外部端口事件、mesh 方向链路事件；
  - 统一收敛输出侧：core 发出的 spike 的本地投递 / 跨 PE 外发 / 跨 core 转发；
  - 将“如何投递到某个 core”与“如何外发到网络”通过回调绑定（由 `MultiCorePE` 装配）。
- **关键接口**：
  - `sendFromCore(src_core, NocPacketEvent*)`：来自 core 的发送入口（INocTransport）。
  - `injectLocal(dst_core, NocPacketEvent*)`：仅本 PE 内投递（INocTransport）。
  - `sendExternal(NocPacketEvent*)`：外发到网络（INocTransport）。
  - `onNicReceive(...) / onExternalPortEvent(...) / onDirectionalLinkEvent(...)`：输入侧回调入口。
  - `drainIncomingQueue(...) / tickRing(...)`：由 `MultiCorePE` 每拍调度。
- **装配点**：
  - `bindRuntime()`：注入 `deliver_to_endpoint` 回调，绑定 NIC/ring/link 等后端句柄；
  - `bindStats()`：注入统计对象（收发/跨核消息等）。

### `OptimizedInternalRing.{h,cc}`
- **定位**：PE 内部跨 core 的优化 ring（双向/多 VC/信用流控）。
- **用途**：用于跨 core 投递与转发（当前主要承载 spike 投递；其它 message type 作为扩展预留）。
- **注意**：本实现以“性能/可扩展”优先，消息 payload 为指针浅拷贝，生命周期由发送方/上层负责。

### 拓扑适配器（可选/高级，ELI 可加载对象）
- **定位**：通用网络拓扑适配器（Mesh/Torus 等），用于需要 topology 实验的场景。
- **说明**：该能力属于 **SST ELI 可加载子组件**，按项目规则统一放在 `components/`：
  - `components/noc/SnnNetworkAdapter.{h,cc}`
  - `components/noc/SimpleNetworkWrapper.{h,cc}`
  主链路默认仍建议优先使用 `components/SnnNIC.*`（SimpleNetwork/linkcontrol 路径）。

---

## 与其他域的交互（典型数据流）

### Core 发放 → 外发/本地投递
1) `workload=snn` 内部装配的 `compute/ISnnComputeCore` 产出 fire events；
2) `workload=snn` 调用 `services/synapse/route/SpikeCommSubsystem`；
3) `SpikeCommSubsystem` 通过 `api/ISpikeTransport` 发出 spike（常见实现是 `api/NocSpikeTransport`；也可使用 `services/synapse/route/SpikePacketTransport`）；
4) `ISpikeTransport` → `INocTransport::sendFromCore(...)`；
5) `NocSubsystem` 根据 packet 头（`dst_node/dst_endpoint`）做本 PE 内投递或外发：
   - 本 PE：`deliver_to_endpoint(core_id, NocPacketEvent*)`（由 `services/synapse/route/SpikePacketBridge` 解码并递送到 CoreShell/workload；`MultiCorePE` 仅装配回调）
   - 外部：`sendExternal(NocPacketEvent*)`（NIC 后端发送）。

### 网络输入 → 投递到目标 core
1) NIC/Link 将事件回调到 `NocSubsystem::onNicReceive`/`onExternalPortEvent`/`onDirectionalLinkEvent`；
2) `NocSubsystem` 入队 `incoming_queue_`；
3) `MultiCorePE` 每拍调用 `drainIncomingQueue()` 完成解析与投递。

---

## 约束与建议

- **禁止**：在 NoC 域内做 fanout 选择或路由表构建（应由 `services/synapse/route` 负责）。
- **禁止**：在 NoC 域内出现权重/BCSR 语义（应由 `services/synapse/weights` 与 `services/synapse/route` 负责）。
- **允许**：NoC 域依赖 `api/` 与 `events/`，并使用少量 SST 基础类型（`SST::Link`、`SST::Output`、`SST::Statistics`）。
