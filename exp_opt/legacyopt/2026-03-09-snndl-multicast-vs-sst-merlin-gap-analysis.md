# SnnDL multicast 深度审阅：与 SST Merlin 的比较、差距与改进方向

> 本文档用于归档一次面向 `SnnDL multicast` 的源码级审阅：
> - 梳理 `SnnDL` 当前 multicast 的真实实现边界；
> - 与 `SST Merlin` 的网络能力做逐项比较；
> - 识别当前最关键的不足与下一步优先级。

---

## 0. 结论先行

如果只问一个问题：**我们现在的 `SnnDL multicast` 到底比 `Merlin` 强，还是弱？**

答案是：

- 从 **SNN 语义贴合度** 和 **timed data-plane 原生多播能力** 来看，`SnnDL` 已经走在 `Merlin` 前面；
- 从 **网络框架成熟度**、**流控/背压建模**、**拓扑/路由通用性** 和 **统一性** 来看，`Merlin` 仍明显更强。

换句话说：

- `SnnDL` 不是“拿通用 NoC 勉强模拟 multicast”，而是已经落地了一条 **面向 SNN fanout 语义的原生多播数据面**；
- 但这条数据面目前仍更像一个 **高价值、但尚未完全产品化的专用后端**，距离 `Merlin` 那种统一成熟的 NoC 基座还有明显差距。

---

## 1. 本次审阅范围

### 1.1 SnnDL 侧

重点阅读了以下路径：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/noc/`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.*`
- `experimental_features/native_multicast_lab/`

### 1.2 Merlin 侧

重点阅读了以下路径：

- `sst_workspace/sst-elements/src/sst/elements/merlin/hr_router/`
- `sst_workspace/sst-elements/src/sst/elements/merlin/interfaces/`
- `sst_workspace/sst-elements/src/sst/elements/merlin/topology/`
- `sst_workspace/sst-elements/src/sst/elements/merlin/test/`

### 1.3 审阅目标

本次不是只看“有没有 multicast 开关”，而是重点看下面四件事：

1. **语义是否真实成立**：有没有真正的树复制与路径共享；
2. **流控是否可信**：拥塞/背压/排队是否只是近似；
3. **主线是否接通**：能力是在实验后端里，还是已经进入 canonical 主线；
4. **与 Merlin 的差距在哪里**：到底是缺网络基础设施，还是只差工程收口。

---

## 2. SnnDL 当前 multicast 的真实实现口径

## 2.1 它不是“统计意义上的多播”，而是真正的 blocked multicast

`SnnDL` 当前的 multicast 主线可概括为：

1. `SynapseRouteSubsystem` 根据 weight-driven fanout 构建 `pre_global -> block targets`；
2. `SpikeCommSubsystem` 把每个目标 block 编码成一个 `SpikeKey`；
3. `MulticastRouter` 在网络内完成 `INTER -> INTRA` 两阶段路由与复制；
4. 最终按 `core_mask[cell]` 精确投递到目标 core。

这条链路的关键点是：

- **跨 block 只发一个包**；
- **复制点后移到 router**；
- **块内树扩散共享路径**；
- **端点投递仍保持精确语义**。

因此它不是“上层先复制很多单播，再在统计里合并”，而是一条真正的 NoC 数据面多播实现。

---

## 2.2 发送前聚合：fanout 先折叠为 per-block 目标

`SynapseRouteSubsystem::computeMulticastTargets()` 会把 `pre_global -> dest_global[]` 折成 `BlockTarget` 列表，每个 block 维护一份 `core_mask[]`：

- 同一个目标 block 只保留一项；
- block 内每个 cell 对应一个 `uint32_t core_mask`；
- 某个目的 PE 内多个 core 的 fanout 被 OR 到同一 mask word 里；
- 若 gating 开启，会把不允许的 node 对应 mask 清零，并删除空 block。

这一步非常关键，因为它决定了 `SnnDL multicast` 的语义是 **SNN-aware aggregation**，不是通用路由器的纯目的地址复制。

同时，这里也暴露出当前实现的硬约束：

- `block_w * block_h <= 64`
- `cores_per_pe <= 32`
- block 必须整除 mesh
- 当前要求 square mesh

这说明当前实现已经非常明确地为“4x4 / 2D mesh / 中小 block / 中等 cores-per-PE”做了针对性优化。

---

## 2.3 包语义：`SpikeKey` 是 multicast 的真正载体

`SpikeCommSubsystem::emitCommon_()` 在 multicast 开启时优先发送 `SpikeKey` 而不是逐条 `SpikeEvent`：

- 一个目标 block 一个 `SpikeKey`；
- `group_id` 按 `(seq << 32) | pre_global` 构造，保证一次运行内的发射唯一性；
- 当实验开关打开时，还可以升级到 `compact v3`、`inter-bundle v1/v2`、`SpikeTileKey`、`TIDE-CAST` 等扩展协议。

这件事说明 `SnnDL` 的 multicast 已不只是“router 支持复制”，而是已经形成了 **上层聚合协议 + 中间路由协议 + 末端投递协议** 的完整栈。

但反过来，也暴露出另一个问题：

- 当前协议族已经开始变多；
- 主协议面还没有完全收敛；
- `SpikeKey` / `compact` / `bundle` / `SpikeTileKey` / `TIDE-CAST` 之间的默认主线仍然偏实验态。

---

## 2.4 Router 数据面：`INTER -> INTRA` 两阶段是真正的核心创新点

`MulticastRouter` 的语义非常清晰：

### INTER 阶段

- 包先按单播方式前往目标 block 的 `ingress_node`；
- 支持 `xy` / `yx` / `hash_xy` / `adaptive_xy_yx`；
- 如果开启 adaptive，代价函数会看端口等待、服务时间和剩余长度偏置。

### INTRA 阶段

- 包到达 ingress 之后切到 block 内树扩散；
- 支持 `manhattan_x_first` / `manhattan_y_first` / `adaptive`；
- 每个 router 只向“其子树下确实存在接收者”的方向复制；
- 本地投递使用 `core_mask[idx_self]` 精确送达目标 core。

这套设计与通用 NoC 的最大不同在于：

- 多播不是由“网络层泛化目的地址集合”驱动；
- 而是由“**block-aware + cell-aware + endpoint-mask-aware**”的专用语义驱动；
- 复制位置、树结构、端点掩码，全都与 SNN fanout 结构强耦合。

这也是我们和 `Merlin` 最大的本质差异之一。

---

## 2.5 本地 endpoint fanout：做了压缩，但没有彻底消灭本地展开

`MulticastRouter` 提供 `local_endpoint_multicast_enable`：

- 若同一 PE 内多个 core 都要收包，router 可先发一个 sentinel endpoint 包；
- `MulticastNIC` 再在本地把 endpoint mask 展开成多个目标 core 的本地递送。

这个设计的优点是：

- 减少 router 到 NIC 之间的包数；
- 避免“每个本地 core 一包”导致的近端复制膨胀。

但缺点也很明显：

- 它只是把展开位置从 router 挪到 NIC；
- 同 PE 内本地 fanout 仍是 clone-based；
- 还没有做到真正的“端点侧零展开”或“共享消费”。

所以它是一个好的局部优化，但还不是终态。

---

## 2.6 流控现实：主问题不在 `SnnNIC`，而在 `MulticastRouter`

`SnnNIC` 本身已经具备比较像样的 credit/backpressure 处理：

- `sendToNode()` 失败会进入 pending 队列；
- credit 回调会 flush pending；
- 还加了周期性刷新，防止丢 wakeup 后永久卡死；
- 还支持 batch 化发送。

但 `MulticastRouter` 不是 `Merlin hr_router` 那种真实 credit-driven router：

- 当前主要依赖 `serialize_output_enable`；
- 以 `port_next_free_cycle_` 做端口占用近似；
- optional byte-aware service 只是在“包长 -> 服务时间”层面做得更细；
- 没有真正的 `per-port queue + per-VC credits + xbar arbitration + remote buffer visibility`。

因此：

- 这套 router 已足以证明“结构上多播可以降包数/降 byte-hops/降 tail”；
- 但如果要把结论上升到“网络拥塞建模已经与成熟 NoC 框架同等级”，证据仍不够硬。

---

## 2.7 正确性和实验口径：这是 SnnDL 当前最扎实的部分之一

`traffic workload` 做了相当强的 group-level 自检：

- 按 `group_id` 跟踪 expected/received endpoint；
- 检查 `missing` / `extra` / `dup` / `meta_mismatch`；
- 可以配置 fatal；
- `native_multicast_lab` 还能统一落盘 `routers.csv` / `cores.csv` / `noc_lat.csv` / `suite_summary.json`。

也就是说，`SnnDL multicast` 的证据不是“看上去收到了包”，而是：

- correctness 有 group coverage 自检；
- performance 有 router/core/latency 多维统计；
- 单播与多播对照实验已经成体系。

这一点比很多“只改了协议但没自检闭环”的研究原型要成熟不少。

---

## 3. Merlin 的真实 multicast 口径

## 3.1 Merlin 的 timed data plane 本质上仍是单播

这是这次审阅里最重要的一个事实。

`Merlin` 的 timed data plane：

- `internal_router_event` 只有一个 `next_port`；
- `hr_router` 的 crossbar 每次仲裁后把事件发到一个下一跳；
- 拓扑的 `route_packet()` 也都是在“给包选一个下一跳端口”。

这意味着：

- `Merlin` 可以有非常成熟的路由、VC、credit、仲裁、拥塞控制；
- 但它默认并没有“一个 timed packet 在网络内被树形复制成多个子包”的通用数据面语义。

因此，如果把 `Merlin` 当成“已有成熟 timed multicast，只是我们还没调出来”，这次审阅给出的结论是否定的。

---

## 3.2 Merlin 的广播主要在 untimed init/complete 阶段

`Merlin` 里确实有 broadcast / fanout：

- `routeUntimedData()` 返回多个 `outPorts`；
- `hr_router` 会 clone 事件并发往各个端口；
- `mesh` / `torus` / `fattree` / `dragonfly` / `hyperx` 等拓扑都对 untimed broadcast 做了特殊扩散逻辑。

但这套机制的定位很明确：

- 它更多是初始化、配置、建图、控制面广播；
- 不是面向 steady-state timed traffic 的 multicast data plane。

因此从体系结构意义上说：

- `Merlin` 的 broadcast 能力很成熟；
- 但那不是我们这里关心的 “SNN steady-state spike dissemination” 那种 timed multicast。

---

## 3.3 Merlin 真正强的地方：完整网络基础设施

`Merlin` 的强项不在 multicast 语义，而在 **NoC 框架成熟度**：

- 多拓扑：`mesh` / `torus` / `hyperx` / `fattree` / `dragonfly`；
- 多路由策略：deterministic、adaptive、Valiant、UGAL 等；
- `Topology` 决定每个 VN 的 VC 需求；
- `hr_router` 统一维护 `xbar_in_credits`、`output_queue_lengths`、VC heads；
- `PortControl` 实现真实的 credits return、output arbitration、stall accounting；
- NIC 通过 `LinkControl` 与 router 对接，接口统一、装配统一。

这意味着 `Merlin` 更像是：

- 一个成熟、统一、通用的 NoC substrate；
- 即使它没有原生 timed multicast，也非常适合作为“所有常规流量”的强基座。

---

## 4. SnnDL 与 Merlin 的能力矩阵

| 维度 | SnnDL multicast | SST Merlin | 当前判断 |
| --- | --- | --- | --- |
| timed data-plane multicast | 已实现，且语义明确 | 默认没有通用 timed multicast | `SnnDL` 领先 |
| SNN fanout 语义贴合 | 强，直接围绕 block/core mask 构造 | 弱，偏通用 packet network | `SnnDL` 领先 |
| 流控/背压真实性 | 中等，router 偏近似 | 强，VC/credit/仲裁完整 | `Merlin` 领先 |
| 拓扑/路由算法广度 | 窄，当前基本锁定 2D mesh | 广，多拓扑多算法 | `Merlin` 领先 |
| 工程统一性 | 双栈并存，实验/主线分裂 | 统一 router/topology/NIC 体系 | `Merlin` 领先 |
| 正确性自检 | 强，group-level 检查扎实 | 常规测试健全，但非 timed multicast 专用 | 各有优势 |
| 性能证据链 | 已有专门 multicast lab 与 CSV/JSON 汇总 | 通用网络测试成熟 | `SnnDL` 在 multicast 方向已具备好基础 |

一句话总结这张表：

- `SnnDL` 是 **专用多播能力强**；
- `Merlin` 是 **通用网络基础设施强**。

---

## 5. SnnDL 当前最主要的不足

## 5.1 不足一：主线与实验线仍然割裂

这可能是当前最现实的问题。

当前 `SnnDL` 里至少存在两层割裂：

- `NocSubsystem + SnnNIC` 是更接近 canonical 主线的网络通道；
- `MulticastRouter + MulticastNIC` 是原生多播实验后端；
- `native_multicast_lab` 的证据很强，但主线 `sst_dram_si/test_mesh_4x4.py` 并没有天然等价接通这套后端。

结果就是：

- 我们可以证明这套 multicast 机制有效；
- 但不能自动说“主线 full-system 已完整吃到这份收益”。

这不是机制错误，而是工程收口还没完成。

---

## 5.2 不足二：router 还不是 Merlin 等级的真实 NoC 模型

`MulticastRouter` 今天更像一个“足够能说明结构性收益”的研究型 router：

- 它能做 block-aware 两阶段复制；
- 它能做简单自适应；
- 它能做 byte-aware serialization。

但它仍缺少：

- 明确的 per-port queues；
- per-VC credits；
- xbar arbitration；
- remote buffer occupancy visibility；
- 更系统的 HOL / fairness / deadlock discipline。

所以和 `Merlin` 相比，它更擅长“表达专用 multicast 语义”，不擅长“做成熟通用 NoC 建模”。

---

## 5.3 不足三：当前实现假设较硬，外推空间有限

当前 multicast 的一些重要前提：

- `block_w * block_h <= 64`
- `cores_per_pe <= 32`
- 2D square mesh
- block 必须整除 mesh

这些约束本身不一定是坏事，因为它们让实现清晰、简单、可验证。

但这也意味着：

- 当前方案对“更大 block / 更异构 PE / 更一般拓扑”不够自然；
- 如果未来要上更大规模、更多拓扑、或更复杂层次结构，协议和路由器都可能要重构。

因此它现在更像“针对当前主问题的 sharp solution”，还不是“普适 NoC multicast substrate”。

---

## 5.4 不足四：协议族开始发散，默认主路径还需收敛

现在我们手里已经有：

- `SpikeKey`
- compact v3
- inter-bundle v1/v2
- `SpikeTileKey`
- `TIDE-CAST`

这说明探索很活跃，但也说明：

- 主协议尚未完全稳定；
- 一些开关更像实验矩阵，而不是产品化选项；
- 如果不尽快收敛默认主路径，后续维护复杂度会快速上升。

这里的关键不是“功能太多”，而是：

- 哪条是主线；
- 哪些只是 side experiment；
- 哪些统计是必须长期保留的；
- 哪些是阶段性调试口径。

---

## 5.5 不足五：本地投递优化还停留在 clone-based 语义

`local_endpoint_multicast_enable` 已经很好地把“router 侧本地多份复制”压成了“router→NIC 一份 + NIC 本地展开”。

但从更高标准看，它仍然是：

- 本地仍需 clone；
- PE 内仍按 endpoint 做多次投递；
- 端点消费端还没有做共享化或真正的 group delivery。

因此这部分更适合作为 **第二阶段优化点**，而不是当前方案的完成态。

---

## 6. 这次比较后，最重要的判断

## 6.1 哪些地方我们已经领先

当前最值得确认的一件事是：

**我们在“面向 SNN fanout 的原生 timed multicast 数据面”上，已经不是落后状态，而是领先 `Merlin` 的。**

具体说：

- `Merlin` 并没有现成的通用 timed multicast data plane；
- 而 `SnnDL` 已经把 SNN 语义、路径共享、router 复制、endpoint mask 精确投递串成了一条闭环。

这个领先点必须保留，而且应该成为后续体系叙事里的核心资产。

---

## 6.2 哪些地方我们还明显落后

同样也必须承认：

**如果比较的是“一个成熟通用 NoC 框架应有的基础设施能力”，我们离 `Merlin` 还有明显距离。**

尤其是：

- credits / VCs / router arbitration / congestion management；
- 多拓扑多算法支持；
- 主线统一装配；
- 框架级一致性和可复用性。

所以正确叙事不是“我们已经整体超越 Merlin”，而是：

- 我们在 **专用 multicast 语义** 上有了独到优势；
- 但还需要向 `Merlin` 学习 **网络基础设施成熟度**。

---

## 7. 建议的优先级路线图

## 7.1 P0：先把 multicast 从“强实验能力”收口到“主线可稳定启用能力”

第一优先级不是继续加新协议，而是先解决：

- canonical 主线是否能稳定接入；
- 主线配置、统计、验证口径是否统一；
- 单播/多播切换是否是体系内一等公民，而不是实验脚本特例。

如果这一步不做，后续所有性能叙事都容易变成“实验后端才成立”。

---

## 7.2 P1：给 `MulticastRouter` 补一层真正的网络模型骨架

建议的方向不是照搬 `Merlin` 全部复杂性，而是最小化补强：

- per-port queues
- INTER / INTRA / local 至少分成逻辑 VC classes
- 基于 credits 的发送许可
- 更真实的 output arbitration
- 对 adaptive policy 提供真实 queue visibility

目标不是马上做成通用 `Merlin`，而是把当前“结构正确但流控近似”的 router，升级成“结构正确且拥塞可信”的 router。

---

## 7.3 P1：收敛协议主路径，避免继续横向发散

建议尽快明确：

- `SpikeKey` 是否仍是默认主协议；
- compact 是否应成为默认编码；
- bundle / tile / tide-cast 各自处于什么层级；
- 哪些统计必须长期保留。

简单说，就是把“实验森林”收成“主干 + 少数分支”。

---

## 7.4 P2：把本地 endpoint fanout 从 clone-based 继续往共享消费推进

这不是当前最阻塞的问题，但它是自然下一步：

- 当前 block 内复制已后移到 router；
- 下一步可以继续把 PE 内投递开销收掉；
- 目标是把本地多 endpoint 投递尽量变成“共享消费 + 少展开”。

如果后续要进一步优化 tail 和 host wallclock，这部分会很重要。

---

## 8. 最终结论

这次对比之后，比较准确的一句话是：

> `SnnDL` 已经拥有一条真正面向 SNN fanout 的原生 timed multicast 数据面；
> 但它仍缺少 `Merlin` 那种成熟统一的网络基础设施与主线收口。

因此我们不该把自己定位成：

- “还只是普通单播 NoC，multicast 只是想法”；

也不该误判成：

- “已经整体超越 Merlin 的通用网络框架”。

更准确的定位是：

- **语义层面**：我们已经有非常强的专用 multicast 优势；
- **工程层面**：还需要完成主线统一、流控补强、协议收敛。

如果下一步路线正确，最值得押注的方向不是“回退到纯 Merlin 思维”，而是：

- 保留 `SnnDL` 的 SNN-aware multicast 语义优势；
- 同时逐步吸收 `Merlin` 的 router/flow-control/统一装配长处；
- 最终把专用语义优势和成熟网络基础设施结合起来。

这才是当前最有价值的演进路径。
