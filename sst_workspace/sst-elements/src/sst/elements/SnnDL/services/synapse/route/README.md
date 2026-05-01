# services/synapse/route/（Synapse/Route 路由与通信事务子系统）

本目录存放 **Synapse/Route 域** 的实现：路由构建（权重驱动或映射文件驱动）、fanout 查询、gating 决策缓存，以及 spike 事件构造与发送事务的封装。

> 边界原则：Route 域负责 “从 source neuron 到目的集合的选择与发送事务”，但不负责“网络传输细节”（NoC）与“权重字节解析”（Weights）。

## 默认内存语义（cacheline）

Route 域本身不发起 DRAM 访问，但与实验结果口径相关的默认体系结构语义应保持一致：平台默认以 **cacheline** 作为对外搬运/统计单位（对齐 `memHierarchy` 的
`GetS/GetX`）。任何 row-streaming/DMA 假设必须由上层 synapse/weights 或 workload 显式启用并单列结果，禁止由路由构建侧隐式引入。

---

## 目录结构与组件职责

### `SynapseRouteSubsystem.{h,cc}`
- **定位**：路由构建与共享缓存子系统；实现 `api/ISynapseRoute.h`。
- **核心职责**：
  - 基于 `api/SynapseRouteBuildConfig.h` 构建 `RouteMap`（支持权重驱动/映射文件/层间 mask 等）；
  - 维护进程级共享缓存（避免每个 core 复制 route table）；
  - 承载 gating（`applyGatingDecision`）与 TTL 失效逻辑；
  - 对外提供 `computeFanout(...)`，内部复用 `SnnRouteProvider` 完成扇出列表生成。
- **输出**：
  - `routesShared()`：共享只读路由表；
  - `routesLocalFallback()`：本地 fallback（无共享或构建失败时保守使用）。
 - **Native multicast（SpikeKey）相关**：
   - 负责在构建期将“目的集合”聚合为 block 级 target：`BlockTarget{block_id, ingress_node, core_mask[cell]}`；
   - `ingress_node` 由 `multicast_ingress_policy` 决定（构建期策略点），并与运行期 router 的 inter/intra 策略解耦；
   - 对外提供 `computeMulticastTargets(...)`，供 `SpikeCommSubsystem` 选择 SpikeKey 发射路径。

### `SnnRouteProvider.{h,cc}`
- **定位**：fanout provider（扇出列表生成器）。
- **核心职责**：
  - 给定 route table + gating cache，计算每个 source 的 fanout 列表；
  - 以 `ISynapseRoute::FanoutEntry` 形式输出（包含目的 PE 等信息）。

### `SpikeCommSubsystem.{h,cc}`
- **定位**：通信事务封装：fanout + SpikeEvent 构造 + 传输调用。
- **核心职责**：
  - 绑定运行时：`ISpikeTransport* transport` 与 `ISynapseRoute* synapse_route`；
  - `emitNeuronFire()`：compute core 报告 neuron_idx 后触发 fanout，并构造 `SpikeEvent` 逐条发送；
  - `applyGatingDecision()`：将 gating 决策转发给 Synapse/Route 子系统（缓存并生效）。
- **说明**：
  - `SpikeCommSubsystem` 通过 `api/ISpikeTransport` 发出事件；常见情况下该 transport 是 `api/NocSpikeTransport`（workload 侧持有并映射为 `INocTransport::sendFromCore`），也可使用 `services/synapse/route/SpikePacketTransport`。
  - 当 `multicast_enable=1` 且 Synapse/Route 已构建 multicast targets 时，`SpikeCommSubsystem` 会优先走 **SpikeKey native multicast**：
    - 通过 `computeMulticastTargets(...)` 得到 per-block 目标集合；
    - 为每个目标 block 构造 `NocPacketEvent(kind=SpikeKey)`，payload 使用 `SpikeNocCodec::WireSpikeKeyV2`（固定大小，带 `block_w_h` 与 `core_mask[64]`）；
    - 通过 `INocTransport::sendFromCore(...)` 将包注入网络，由 router 完成两阶段路由与块内投递。

### `SpikePacketBridge.{h,cc}`
- **定位**：SpikeEvent ↔ NoC packet 的编解码与投递 glue（Phase3-C）。
- **核心职责**：
  - 将 `NocPacketEvent` 解码为 `SpikeEvent` 并以 packet-first 方式递送到目标 CoreShell/workload（对接 `NocSubsystem::deliver_to_endpoint` 回调）；
  - 将 `SpikeEvent` 编码为 `NocPacketEvent` 并通过 `api/INocTransport` 发出（供 MultiCorePE/Stimulus 等装配使用）。
- **边界收益**：`components/MultiCorePE.*` 不直接调用 `SpikeNocCodec`，只做装配与时钟调度。

---

## 与其他域的交互（典型数据流）

1) `workload=snn` 内部装配的 `compute/ISnnComputeCore` 产出 fire events；
2) `workload=snn` 调用 `SpikeCommSubsystem::emitNeuronFire()`；
3) `SpikeCommSubsystem` 调用 `ISynapseRoute::computeFanout()` 得到目的集合；
4) `SpikeCommSubsystem` 构造 `events/SpikeEvent` 并调用 `ISpikeTransport::send(...)`；
5) `ISpikeTransport` 的具体实现（通常由 NoC 域承载）完成实际发送与本地投递。

---

## neuron layout 口径要求（P0：影响路由与投递）

- **dest_node 推导分母必须是 `neurons_per_pe`**：权重驱动路由中 `dest_node = dest_global / neurons_per_pe`，因此 `SynapseRouteSubsystem/SnnRouteProvider` 接收的 `neurons_per_pe_cfg` 必须是 *per-PE* 口径。
- **source_global 推导 base 必须是“本 core base”**：`SpikeCommSubsystem` 使用 `source_global = global_neuron_base + neuron_idx`，因此 `global_neuron_base` 必须是 *per-core* base（不是 node base）。

## Native Multicast（SpikeKey / blocked multicast）要点

### 语义与数据载体
- **语义**：块间单播到 ingress + 块内多播（按 core mask 精确投递）。
- **载体**：`events/NocPacketEvent(kind=SpikeKey)`，payload 由 `SpikeNocCodec` 编解码：
  - 兼容解码：V1/V2；
  - 推荐发射：V2（固定 `core_mask[64]`，由 `block_w_h` 指定实际使用的 cells 数）。

### 配置参数（来自 `SynapseRouteBuildConfig`）
- `multicast_enable`：开关（默认 off，保持兼容）
- `multicast_block_w/multicast_block_h`：block 尺寸（要求 mesh 可整除；且 `block_w*block_h<=64`）
- `multicast_ingress_policy`：构建期选择 ingress（`top_left/top_right/bottom_left/bottom_right/hash4`）
- `multicast_inter_policy`：运行期块间单播走法（router 参数，当前支持 `xy/yx/hash_xy`）
- `multicast_intra_policy`：运行期块内树（router 参数，当前支持 `manhattan_x_first/manhattan_y_first`）

### 统计与正确性自检（实验口径）
- `TrafficWorkload` 在实验中提供：
  - per-packet mask 自检（`sk_bad_*` 计数）
  - group-level 覆盖自检（`[traffic][sk-group] ... missing/dup/extra/meta_mismatch`）
  用于验证“确实发生了多播且投递集合正确”。

---

## 约束与建议

- **禁止**：Route 域内直接依赖 `StandardMem` 或解析权重 bytes（属于 Weights/Mem 域职责）。
- **建议**：路由构建成本高时优先复用 `SynapseRouteSubsystem` 的进程级缓存（避免每核重复构建）。
