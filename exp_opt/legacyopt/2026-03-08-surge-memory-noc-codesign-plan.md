# SURGE：面向 full-system baseline 的 memory × NoC 协同主线设计

> 日期：2026-03-08  
> 状态：设计收敛版，等待实现批准  
> 基线：`full_system_baseline = STORM(multicast_mesh) + GCSS-GLIDE`  
> 目标：在不破坏严格 GAS 语义与当前主线验证口径的前提下，提出一个足够 novel、足够 solid、足够可落地的 memory × NoC 协同机制，用于后续 ISCA/ASPLOS 级系统叙事。

## 0. 一句话结论

当前 `full_system_baseline` 已经证明：

- `GCSS-GLIDE` 单独把 memory side 做对了；
- `STORM` 单独把 NoC side 做对了；
- 两者叠加后，系统性能显著优于任何单侧 baseline。

但它仍然不是“真正协同”的终点，因为：

- `full_system_baseline` 的 NoC granule 仍然是 `SpikeKey`；
- `full_system_baseline` 的 DRAM service granule 仍然是“每个 pre 独立触发的 GCSS values line”；
- 两边虽然都优化得不错，但**仍然没有共享同一个数据移动 granule**。

因此，下一步最值得做、也最像体系结构论文主贡献的方向，不是继续做旁路预取，也不是继续堆局部调度，而是：

- **把 STORM 的通信 granule 与 GCSS-GLIDE 的内存 granule 合并成同一个 exact cohort granule。**

浮浮酱建议的新机制名为：

- **`SURGE` = `STORM-Unified Request Granule Engine`**

其核心思想是：

- 在 NoC 上，不再只传“单个 pre 的 `SpikeKey`”；
- 在 DRAM 上，不再只按“单个 pre 段”独立服务；
- 而是引入一个严格确定性的 **cohort granule**，让“一个 NoC 包”天然对应“一个或少数几个 DRAM line group”，从而同时减少：
  - NoC packet replication / bytes
  - DRAM request count / line under-utilization
  - Apply 阶段的 per-pre service overhead

## 1. 为什么现在该做这件事

### 1.1 当前 full-system 已经把系统关系钉死了

`mainexp/experiments/2026-03-08_full_system_baseline_ab_v1` 的三组 baseline 已给出非常清楚的证据：

- `memory_baseline = Merlin + GCSS-GLIDE`
- `noc_baseline = STORM + GCSS-idx2`
- `full_system_baseline = STORM + GCSS-GLIDE`

关键结果：

- `memory_baseline`
  - `sim_time_actual_ns = 1,086,400`
  - `memctrl.req_total = 150,110`
  - `gas.memctrl_payload_utilization = 0.3177`
- `noc_baseline`
  - `sim_time_actual_ns = 1,383,670`
  - `memctrl.req_total = 1,684,046`
  - `gas.memctrl_payload_utilization = 0.02835`
- `full_system_baseline`
  - `sim_time_actual_ns = 257,453`
  - `memctrl.req_total = 150,907`
  - `gas.memctrl_payload_utilization = 0.31637`

这说明：

- `full_system_baseline` 的 memory 形态基本继承了 `memory_baseline`；
- `full_system_baseline` 的 NoC 形态基本继承了 `noc_baseline`；
- 现在的系统收益是“memory 好 + NoC 好”的叠加，而不是“memory 和 NoC 互相提供新的结构收益”。

### 1.2 当前真正剩下的问题是什么

即使在 `full_system_baseline` 中，内存侧仍然有明显剩余浪费：

- `gas.payload_bytes_per_memctrl_req_avg ≈ 20.25B`
- `gas.memctrl_payload_utilization ≈ 0.316`

也就是说，真实 DRAM line 是 `64B`，但当前平均只有 `~20B` 真正承载有效 weight payload。

这说明：

- `GCSS-GLIDE` 已经把事情做得很好；
- 但当前 DRAM service 仍然围绕“单个 pre”来组织；
- 而 `STORM` 已经在 NoC 上把多个目标合并成了 block-aware multicast granule；
- 这两种 granule 目前并没有统一。

**这就是剩余的体系结构机会。**

## 2. 我们不该再走什么路

### 2.1 不该回到纯 metadata prefetch 路线

已有联合探索 `STORM-PIF / STORM-NIP` 已证明：

- 机制可以真实触发；
- 甚至局部请求量、平均读延迟可以改善；
- 但端到端收益并不稳定，且主收益不直接来自 payload plane。

问题本质是：

- `PIF/NIP` 主要优化的是 `rowidx / idx2` 这类旁路元数据；
- 但 `full_system_baseline` 的主剩余浪费已经不在元数据，而在 **value line under-utilization**。

因此，继续把主精力放在 prefetch 上，论文贡献会偏“聪明预取”，而不是结构级协同。

### 2.2 不该回到重运行时 join 的共享服务路线

`naive_tass / TASS-LF` 给过我们重要教训：

- 把 block 共享服务完全放到运行时做动态 join、动态 line fusion、动态 response multicast，侵入性很强；
- 即便能降低部分 memory 事务，也很容易把收益吃回到：
  - runtime bookkeeping
  - drain / barrier interaction
  - response fanout complexity
  - long-tail scheduling cost

这类路线不是没有价值，而是：

- 太像“在线复杂机制”；
- 很难作为当前主线最稳的下一步。

### 2.3 不该回到局部 issue/scheduler 调优

历史上 `cmd_aware / bank_rr / dram_aware / per_post_retire` 一类机制已经说明：

- 它们更多是在 issue order / tail latency 上做局部优化；
- 当主瓶颈已经变成 granule mismatch 时，这类机制不是主矛盾。

因此，新主线必须直接攻击：

- **NoC granule 与 DRAM granule 不一致**

而不是继续围绕“同样的 granule 怎么排得更聪明”打转。

## 3. 相关工作边界：为什么这件事有发表空间

### 3.1 现有 neuromorphic chip 的典型分布

从公开系统看，大致可分三类：

- **Loihi 2 类**：计算、存储、通信高度片上集成，神经元和突触主要在本地 memory 内消化，NoC 为片上异步 mesh。Intel 的 Loihi 2 brief 明确强调其 neuron cores 集成 synaptic memory，并通过片上 NoC 和本地 memory 空间完成处理。  
  来源：Intel Loihi 2 Technology Brief  
  https://www.intel.com/content/dam/www/central-libraries/us/en/documents/neuromorphic-computing-loihi-2-brief.pdf

- **SpiNNaker / SpiNNaker2 类**：非常强调 multicast communication，并具备外部 SDRAM，但公开叙事更偏“路由与可扩展通信”，而不是把 multicast packet granule 和 DRAM service granule 做成统一对象。SpiNNaker 系列一直非常强调 multicast traffic 和 scalable communication；SpiNNaker2 文档也明确说明一个 chip/node 配有 off-chip SDRAM，并由 associative multicast router 处理 neural event packets。  
  来源：SpiNNaker communication paper；SpiNNaker2 developer docs  
  https://doi.org/10.1016/j.jpdc.2012.01.016  
  https://spinnaker2.gitlab.io/external/documentation/hardware/2-chip-to-chip-link/

- **近年 bottleneck 分析工作**：开始承认 neuromorphic workloads 存在 memory-bound / traffic-bound / compute-bound 不同状态，但大多数工作仍停在“识别瓶颈”或“做 workload partitioning”，并没有在 DRAM-backed SNN 系统中，把 memory granule 和 communication granule 做成统一协同对象。  
  来源：Modeling and Optimizing Performance Bottlenecks for Neuromorphic Accelerators  
  https://arxiv.org/abs/2511.21549

### 3.2 我们与公开路线的真正差异

我们当前系统的独特起点是：

- **真实 DRAM 后端**
- **严格 GAS 语义主干**
- **GCSS-GLIDE 已经把 values-only / payload utilization 做到可发表口径**
- **STORM 已经把 multicast-aware NoC 做到主线后端**

因此我们最自然、最有发表空间的故事不是：

- 再做一个缓存；
- 再做一个预取；
- 再做一个 heuristic scheduler；

而是：

- **在 DRAM-based SNN 芯片上，第一次把 NoC 的通信 granule 与 memory 的 service granule 统一起来。**

这比“单独的 memory 优化”或“单独的 NoC 优化”更像一篇架构论文的中心命题。

## 4. 候选方向对比

### 4.1 方案 A：SURGE（推荐）

**核心**：统一 STORM packet granule 与 GCSS weight-service granule。

- NoC 侧：从 `SpikeKey` 提升到 `CohortKey` / `SpikeTileKey+cohort_id`
- Memory 侧：从 per-pre `GCSS line` 提升到 exact `CohortLine`
- 运行时：引入一个很小的 `CohortServiceBuffer`
- 稀疏尾部：自动 fallback 到当前 `full_system_baseline`

优点：

- 真正 memory × NoC 协同
- 直接打 payload plane
- exact / deterministic / 可 fallback
- 复用当前 STORM 与 GCSS-GLIDE 主线资产最多

缺点：

- 需要新增 weight format + packet format + 一个小服务单元
- 设计与实现量最大

### 4.2 方案 B：NoC-aware NIP 2.0

**核心**：继续做 `idx2/values` selective prefetch，但用 NoC block/tile telemetry 提升有效覆盖率。

优点：

- 实现最轻
- 复用旧代码最多

缺点：

- 太像“预取加强版”
- 很难成为主贡献
- 不直接触碰 payload-underutilization 主矛盾

### 4.3 方案 C：TASS-LF-lite / shared line buffer

**核心**：保留当前 packet 语义，只做 block-local shared service buffer，尝试在线共享 line。

优点：

- 改动 packet format 少
- 硬件直觉强

缺点：

- 很接近我们已经踩雷的 `naive_tass / TASS-LF`
- 运行时 join 和 bookkeeping 风险仍高
- 很容易再次变成“机制有效但收益不稳”

### 4.4 结论

**推荐方案是 A：SURGE。**

因为它是唯一一个同时满足下面四条的方向：

- 直接打主矛盾：payload granule mismatch
- 不是局部 heuristic
- 能自然继承当前 full-system 主线
- 有明确的论文级差异化叙事

## 5. SURGE 的核心思想

### 5.1 一个系统级 granule，而不是两套独立 granule

当前系统中：

- STORM 传的是“按 block 聚合的 neural event”
- GCSS-GLIDE 取的是“按 pre/line 组织的 weight values”

SURGE 做的事情是：

- 把“会一起走网络的 pres”也变成“会一起服务内存的 pres”
- 让一个 NoC packet 对应一个 exact memory cohort
- 让 DRAM line 能够被同一个 cohort 中的多个 pres 共同消费

这本质上是一个 **granule unification** 问题。

### 5.2 不做全量替换，只做热点 cohort 覆盖

SURGE 不应该试图把所有 pres 都强行变成 cohort。

更稳的做法是：

- 只对热点 cohort 建 exact `CohortLine` 格式
- 长尾仍然走当前 `GCSS-GLIDE` 主线

这样可以同时满足：

- 创新性：主路径真的变了
- 工程稳健性：稀疏尾巴不被硬塞进复杂格式
- 索引预算：避免 metadata 爆炸
- 语义安全：任何 cohort 覆盖不到的边都自动回到 baseline exact path

### 5.3 精确定义 cohort

建议 cohort 的基本单位不是任意动态集合，而是**可离线稳定编号**的对象。

推荐定义：

- **source tile**：固定大小 `Tpre` 的 pre group（例如 8 / 16 / 32）
- **target block / target PE**：沿用 STORM 的 block-aware destination grouping
- **target core-local cohort**：落到某个接收 core 后，该 cohort 在本 core 上真实存在的 edge 子集

这样 cohort 的标识就可以是：

- `(source_tile_id, target_block_id, core_id_local)`

这让它：

- 可离线生成
- 可静态编号
- 可在 packet 中以很小代价编码
- 不需要运行时做贵的集合求交

## 6. SURGE 的数据格式

### 6.1 新 experimental mode

建议新增独立 experimental mode：

- `synapse_weight_mode = gcss_surge_cohortline`
- 环境变量目录：`MESH_GCSSSURGE_DIR`

与当前主线强隔离，不污染 `gcss_valueonly_dstcore_vlf_premphf_plp`。

### 6.2 输出文件

每 core 一套：

- `peXX/coreYY.surge.values.bin`
- `peXX/coreYY.surge.idx.bin`
- `peXX/coreYY.surge.cohort.bin`
- `peXX/coreYY.surge.meta.json`
- `manifest.json`

其中：

- `values.bin`：hot cohorts 的 `CohortLine` values
- `idx.bin`：fallback `GCSS-GLIDE` exact index
- `cohort.bin`：`cohort_id -> descriptor` 映射

### 6.3 Cohort descriptor

每个 cohort descriptor 至少包含：

- `cohort_id`
- `source_tile_id`
- `target_block_id`
- `local_core_id`
- `pre_mask` 或 `pre_local_ids`
- `line_base`
- `line_count`
- `fallback_bitmap`
- `post decode template`

作用是让运行时可以做到：

- 收到一个 `CohortKey`
- 直接知道该去取哪些 line
- 返回后如何把 values 精确映射回 `(pre, post_local)`
- 哪些边不在 cohort 覆盖内，需要回退到 baseline path

### 6.4 为什么它是 exact 的

`CohortLine` 不是近似压缩，而是 exact packing：

- 每个 value 仍然对应真实唯一的 `(pre, post_local)`
- 只是这些 values 的物理排布不再按单个 pre 段组织
- 而是按 cohort 中的多个 pre 共同打包

因此它和 GCSS-GLIDE 的关系是：

- `GCSS-GLIDE`：exact pre-major / cross-pre packed values
- `SURGE`：exact cohort-major / packet-shaped values

## 7. SURGE 的运行时路径

### 7.1 发送端：从 SpikeKey 到 CohortKey

发送端不再把每个 active pre 都独立发成 `SpikeKey`。

而是：

- 在当前 STORM 路由构建基础上
- 按 `(source_tile_id, target_block_id)` 聚合 active pres
- 形成一个 `CohortKey`

实现上可以有两种策略：

- 复用 `SpikeTileKey` 的 payload 前缀，在尾部追加 `cohort_id`
- 或新增一个独立 `NocPacketKind::CohortKey`

推荐前者，因为：

- 兼容现有 router codec 结构
- 便于实验隔离
- 可逐步从 `SpikeTileKey` 演化

### 7.2 NoC：完全复用 STORM 路由与复制语义

SURGE 不需要重新发明路由器。

它应该直接复用：

- `STORM` 的 blocked multicast
- `MulticastRouter` 的 `INTER -> INTRA` 两阶段传播
- 必要时复用 `InterBundle V2`

这非常重要，因为它让 SURGE 的贡献焦点始终保持在：

- “统一 granule”

而不是跑偏到“又做一个 router 机制”。

### 7.3 接收端：CohortServiceBuffer

每个接收 PE 增加一个很小的 `CohortServiceBuffer`：

- 输入：`CohortKey`
- 查询：`cohort descriptor SRAM`
- 发射：一个或少数几个 `CohortLine` 读请求
- 返回：把 line 内多个 values 解复用为 exact edges
- 输出：送回当前 `WeightMemorySubsystem` / GAS retire queue

这个单元的关键特征是：

- 不做复杂在线集合求交
- 不做近似合并
- 只做 descriptor lookup + exact line demux

这使它比 `naive_tass / TASS-LF` 简洁得多，也更像一个可实现的硬件 front-end。

### 7.4 稀疏尾部 fallback

若当前 packet 对应的 pres：

- 不存在 hot cohort descriptor
- 或 active pre 子集太稀疏
- 或 cohort 覆盖率低于阈值

则直接 fallback 到当前 `full_system_baseline`：

- `SpikeKey` / `GCSS-GLIDE`
- 现有 `SnnWorkload::expandPreGlobalToWindowEdgesFast_()`
- 现有 `WeightMemorySubsystem`

因此，SURGE 的主张不是“取代 baseline”，而是：

- **在 exact baseline 上叠加一个高收益 hot path。**

## 8. 为什么 SURGE 比之前路线更 work

### 8.1 它直接攻击 payload plane

过去的协同尝试，很多仍停留在：

- metadata prefetch
- request timing
- response ordering
- block-local runtime fusion

SURGE 则直接改变：

- “同一次网络传播所对应的 DRAM line consumption shape”

这是当前剩余浪费的最直接来源。

### 8.2 它把复杂度尽量推回离线编译

`naive_tass / TASS-LF` 的问题之一，是把太多选择留在了运行时。

SURGE 的设计原则相反：

- 运行时只做 descriptor-guided exact service
- 真正复杂的 packing 和 cohort selection 都在离线完成

这会让：

- 硬件结构更清晰
- 时序风险更低
- 复现与验证更稳定

### 8.3 它天然保留 strict 语义护栏

当前主线已经有关键护栏：

- GAS gather/apply 语义
- edge retire 的确定性顺序
- step/window 严格验证链路

SURGE 不改这些，只改：

- packet 如何编码
- weight 如何物理排布
- line 返回后如何精确展开

因此它更容易做到：

- `validation.log: fail=0`
- 主统计与 baseline 对齐
- 只在 payload/transport 侧出现正收益

## 9. 预期收益

### 9.1 相对 full_system_baseline 的理论提升点

SURGE 的收益应该体现在三层：

- **NoC层**
  - 包数下降
  - bytes / byte-hops 下降
  - ingress / local replication 下降

- **Memory层**
  - `memctrl.req_total` 下降
  - `payload_bytes_per_memctrl_req_avg` 上升
  - `memctrl_payload_utilization` 上升

- **Execution层**
  - `apply_ns_avg` 下降
  - `sim_time_actual_ns` 下降
  - tail latency 收敛更快

### 9.2 最关键的论文指标

相对 `full_system_baseline`，我们最希望看到：

- `sim_time_actual_ns`：显著下降
- `memctrl.req_total`：下降
- `gas.payload_bytes_per_memctrl_req_avg`：从 `~20B` 进一步提高
- `gas.memctrl_payload_utilization`：从 `~0.316` 进一步提高
- `NoC tx/rx bytes or byte-hops`：继续下降

### 9.3 这会形成什么论文叙事

如果成功，论文的系统叙事会从：

- `GCSS-GLIDE` 解决 memory
- `STORM` 解决 NoC

升级为：

- **SURGE 将 STORM 的传播 granule 与 GCSS-GLIDE 的权重服务 granule 统一，从而把 NoC 相关性直接转化为 DRAM payload efficiency。**

这比“两个好机制叠在一起”更像一个完整的架构贡献。

## 10. 落地计划（强调可执行性）

### 10.1 P0：只做离线上界分析，不改主数据路径

先做最保守的一步：

- 用当前 `full_system_baseline` 的 trace / summary / pre touch order
- 离线构造候选 cohort
- 估算如果采用 `CohortLine`，`payload_bytes_per_memctrl_req_avg` 最多能提高多少

目的：

- 先判断这条路值不值得进 runtime
- 避免一上来做复杂实现

### 10.2 P1：只做 CohortKey NoC path

第二步只改 NoC granule：

- sender 聚合为 `CohortKey`
- receiver 仍然 fallback 到当前 `GCSS-GLIDE`

目的：

- 单独量化 NoC 侧收益
- 验证 packet granule 改变是否稳定

### 10.3 P2：引入 exact CohortLine + CohortServiceBuffer

第三步再真正打 memory side：

- 新 weight mode
- 新 descriptor
- 新 service buffer
- fallback 兜底

目的：

- 验证真正的协同收益

### 10.4 P3：阈值与热度门控

最后再引入：

- hot cohort threshold
- fallback coverage control
- index budget guardrail

确保：

- 不因追求覆盖率而让 metadata 膨胀
- 不因长尾 cohort 而损害系统收益

## 11. 需要新增的统计

建议最少新增以下统计，才能形成完整证据链：

- `gas.cohort_packets_total`
- `gas.cohort_pres_per_packet_avg`
- `gas.cohortline_req_total`
- `gas.cohortline_payload_bytes_total`
- `gas.cohortline_values_served_total`
- `gas.cohortline_payload_bytes_per_req_avg`
- `gas.cohort_fallback_packets_total`
- `gas.cohort_fallback_edges_total`
- `gas.cohort_coverage_ratio`
- `gas.cohort_descriptor_bytes_total`
- `gas.cohort_hotset_ratio`
- `gas.cohort_demux_edges_total`

NoC 侧补：

- `snn_tx_cohortkey_packets_total`
- `snn_rx_cohortkey_packets_total`
- `noc.cohort_bytes_total`
- `noc.cohort_byte_hops_total`

## 12. 风险与缓解

### 12.1 风险：cohort 过稀疏，收益不够

缓解：

- 只做 hot cohort
- 严格 fallback
- 先做 P0 上界分析

### 12.2 风险：descriptor 过大

缓解：

- descriptor 只为热点 cohort 存在
- 长尾仍走 GCSS-GLIDE
- 用 budget 明确约束 `descriptor_bytes <= hot_values_bytes * alpha`

### 12.3 风险：packet 聚合破坏时序或验证

缓解：

- 先在 `max_steps=1`、当前主口径下验证
- 继续使用现有 GAS gather quiesce + deterministic retire
- packet 只做 exact regrouping，不做语义近似

### 12.4 风险：实现跨度太大

缓解：

- 按 `P0 -> P1 -> P2 -> P3` 递进
- 每步都能独立 A/B
- 任何一步不成立都可止损，不拖垮主线

## 13. 最终判断

如果只能从当前 full-system 主线再往前走一大步，浮浮酱认为最值得押注的方向就是：

- **SURGE：用同一个 exact cohort granule 统一 STORM 的 NoC packet 与 GCSS-GLIDE 的 DRAM service。**

它相比以前路线的优势在于：

- 比 `PIF/NIP` 更直接地打中了 payload plane；
- 比 `naive_tass / TASS-LF` 更少运行时复杂 join；
- 比单独继续做 memory 或 NoC tweak，更像一个真正的系统级协同创新；
- 与当前 `full_system_baseline` 天然兼容，可作为一个受控 hot path 增量引入。

如果这条路线做通，我们就不再只是“把 memory 和 NoC 各自做好”，而是在论文层面真正拥有：

- **一个 DRAM-based SNN chip 上，通信 granule 与内存 granule 协同设计的统一体系结构机制。**
