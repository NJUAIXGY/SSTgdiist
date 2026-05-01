# components/noc/（ELI 可加载 NoC/拓扑适配组件）

本目录存放 **与网络拓扑实验相关的 ELI 可加载子组件**。它们属于“组件层装配壳”的范畴，因此放在 `components/` 而不是 `services/`。

> 重要：主链路默认推荐使用 `components/SnnNIC.*`（SimpleNetwork/linkcontrol 路径）。本目录的适配器用于更高级/实验性的“拓扑适配/直连端口”场景。

## 口径说明：NoC payload 与内存粒度

- NoC 子系统以 `events/NocPacketEvent` 为 payload（packet-first），**不解析 SNN/Synapse 语义**。
- SnnDL 的默认内存建模语义为 **cacheline 粒度**（与 `memHierarchy` 的 `GetS/GetX` 事务统计对齐）。NoC 组件本身不应隐式引入 row-streaming/DMA 等更强假设；如需
实验该类假设，应在上层 workload/synapse 域显式配置并在输出中标注。

---

## 主要组件

### `SnnNetworkAdapter.{h,cc}`
- **类型**：`SST::SubComponent`（ELI：`SnnDL.SnnNetworkAdapter`），实现 `api/SnnInterface.h` 的 `SnnInterface`
- **定位**：通用网络拓扑适配器（Mesh/Torus 等），用于把 `SST::Event` 与 `SimpleNetwork::Request` 做转换与路由决策
- **典型用途**：
  - 需要“在适配器层实验拓扑/路由算法”时使用（如 XY/adaptive）
  - 需要把 `NocPacketEvent` 走方向端口（north/south/east/west）或走 merlin router 时使用
- **说明**：该组件以 payload-agnostic 为目标，路由层不应解析突触/权重语义（Spike 语义应停留在 synapse 域）。

### `SimpleNetworkWrapper.{h,cc}`
- **类型**：`SST::SubComponent`（ELI：`SnnDL.SimpleNetworkWrapper`），继承 `SST::Interfaces::SimpleNetwork`
- **定位**：`SnnNetworkAdapter` 的 SimpleNetwork 代理，用于规避多重继承导致的 SST ELI 冲突
- **职责**：
  - 提供 `send/recv/spaceToSend/requestToReceive` 等 SimpleNetwork 接口
  - 将网络请求队列与回调通知（notify-on-receive/send）封装为可复用代理

### `MulticastRouter.{h,cc}` / `MulticastNIC.{h,cc}`（原生多播实验后端）
- **类型**：
  - `SST::Component`（ELI：`SnnDL.MulticastRouter`）
  - `SST::SubComponent`（ELI：`SnnDL.MulticastNIC`，替换 MultiCorePE 的 network_interface）
- **定位**：用于 **SpikeKey native multicast（blocked multicast）** 的轻量 mesh router 后端：
  - INTER：块间单播到 `ingress_node`
  - INTRA：块内按树扩散 + 按 `core_mask[cell]` 精确投递到 cores
- **与边界的关系**：
  - Router **只解析 SpikeKey 路由头**（`version/stage/block_w_h/block_id/ingress_node/group_id/core_mask[]`），不解析权重/BCSR/GAS 语义；
  - 该后端主要用于 `experimental_features/native_multicast_lab/` 的端到端验证与性能画像，属于实验性网络后端。
- **可调策略点（params）**：
  - `multicast_inter_policy`：INTER 阶段单播走法（`xy`/`yx`/`hash_xy`）
  - `multicast_intra_policy`：INTRA 阶段块内扩散树（`manhattan_x_first`/`manhattan_y_first`）
  - 注意：`ingress_node` 的选择属于构建期策略（`multicast_ingress_policy`），由 Synapse/Route 构建 multicast target 时决定。

---

## 与 NoC 子系统的关系

- `services/noc/NocSubsystem` 的主目标是“传输事务下沉 + 冻结接口（`api/INocTransport.h`）”，并以 `events/NocPacketEvent` 作为 payload。
- 本目录组件属于“网络后端/适配层工具”，用于与路由器/链路端口进行对接；是否启用取决于具体实验脚本与装配方式。
