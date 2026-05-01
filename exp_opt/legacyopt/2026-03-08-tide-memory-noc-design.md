# TIDE：面向 DRAM-based SNN 的 Address-Band Memory × NoC 协同机制设计

日期：2026-03-08  
状态：阶段性验证中（`TIDE-L Phase-1` 已验证有效；`TIDE-BSC/LBM dest-only` 已冻结为 bridge；下一推荐方向为 `TIDE-CAST`）

## 0. 设计结论

在当前稳定主线

- `GAS`
- `GCSS-GLIDE`
- `STORM`

已经分别站住脚的前提下，下一步不应继续沿着“更聪明的 edge 重排 / token 级精确服务 / receiver arrival 驱动的 issue 扰动”这条路线推进。现有证据表明，这类方案很容易打散 `GCSS-GLIDE` 已建立的物理地址局部性，进而让 `memctrl_req_total`、`overfetch` 与 `sim_time_actual_ns` 回退。

因此，本设计提出一个新的协同硬件层：

- **`TIDE`**
- 展开：`Traffic-Integrated DRAM Epochs`

其核心思想是：

- 不再把 memory × NoC 协同建立在 `edge` / `token` / `exact line` 级别；
- 而是在 **`destination block` 级别** 引入一个新的、粗粒度但物理真实的抽象：
  - **`address band epoch`**
- `STORM` 的 block-multicast wave 与 `GCSS-GLIDE` 的 DRAM service wave，都围绕同一个 `band epoch` 协同组织；
- 但 **band 内仍严格保持当前 `GCSS-GLIDE` 的物理地址顺序**，不再像 `CHORD-L` 那样用 arrival/cohort 顺序打乱 issue 队列。

一句话概括：

- **`TIDE` 不是“再做一层重排”，而是给 `STORM` 与 `GCSS-GLIDE` 建立一个 block 级、DRAM-truth 的共享控制语言。`**

---

## 1. 为什么现在需要 TIDE

## 1.1 当前稳定主线已经说明了什么

当前完整系统主线已经稳定为：

- memory 主线：`GAS + GCSS-GLIDE`
- NoC 主线：`STORM + MulticastRouter`
- full-system baseline：`STORM MulticastRouter + GAS GCSS-GLIDE`

以 `mainexp/experiments/2026-03-08_full_system_baseline_ab_v1/snapshot/compare.tsv` 为当前主口径：

- `full_system_baseline` 的 `sim_time_actual_ns = 257453`
- 对应 `memctrl_req_total = 150907`
- `gas_memctrl_payload_utilization = 0.31637`
- `gas_payload_bytes_per_memctrl_req_avg = 20.2477`
- `gas_memctrl_traffic_amplification = 3.16086`
- `gas_overfetch_bytes_total = 6602532`

这组数字揭示了当前系统的真实状态：

1. `STORM` 已经把 NoC 侧的大头问题基本解决了。
- 相比 `memory_baseline`，端到端时间已经从 `1086400` 压到 `257453`。
- 这说明“仅靠更强的 NoC 多播”已经证明有效。

2. 但 memory side 仍然不是“干净的最终形态”。
- `payload_utilization` 还只有 `0.316` 左右；
- `traffic_amplification` 仍在 `3.16x`；
- `overfetch` 仍然巨大。

3. 现有 full-system 主线缺少一层“真正把 NoC 波次翻译成 DRAM 服务波次”的协同结构。
- `STORM` 知道“流量去哪个 block”；
- `GCSS-GLIDE` 知道“这个 block 内的权重在 DRAM 哪”；
- 但两者目前没有共享的、可硬件实现的协同控制抽象。

`TIDE` 的任务，就是补上这一层。

## 1.2 现有失败路线说明了什么不能做

### A. `PRISM-RX / PRISM-SEG`

`PRISM` 路线的结构性问题是：

- 试图把 packet / pre token / service token 拉成一个更“精确”的运行时平面；
- 结果状态规模与调度复杂度向 token 粒度膨胀；
- 极易侵入现有 `GAS` 的严格语义路径；
- 很难维持一个既可建模又可流片的硬件故事。

结论：

- `PRISM-RX` 可以作为 bridge，但不是最终性能机制；
- `PRISM-SEG` 这种把执行平面重新细粒度化的路线不应继续推进。

### B. `naive TASS`

朴素 `TASS` 的问题是：

- 它看到了 `2x2 block` 级共享，但没有建立一个足够物理真实的 memory service 粒度；
- 如果只做“block 级同 pre 聚合”或“block 级预取”，边际收益不够稳定；
- 很容易做成另一个偏工程化的 prefetch 方案。

### C. `CHORD-L`

`CHORD-L` 刚刚给出了非常关键的反证：

- 在 `mainexp/experiments/2026-03-08_chord_l_ab_v1/` 中，`CHORD-L` 虽然语义正确、validation 通过；
- 但它把 `sim_time_actual_ns` 拉高到 `262567`（相对 baseline `+1.99%`）；
- `memctrl_req_total` 增到 `154218`（`+2.19%`）；
- `payload_utilization` 降到 `0.30958`（`-2.15%`）；
- `overfetch` 增加 `+3.21%`。

这说明：

- **receiver/cohort/arrival 驱动的 issue 重排，不是当前主线应走的方向。**
- 一旦这种重排打散 `GCSS-GLIDE` 已有的物理地址顺序，系统会立刻回退。

## 1.3 TIDE 的硬约束

基于以上经验，`TIDE` 设计必须满足以下硬约束：

1. 不改变 `GAS` 语义。
- retire 顺序、apply 语义、数值结果、严格验证链路必须保持一致。

2. 不破坏 `GCSS-GLIDE` 的物理地址单调性。
- band 内必须继续按当前地址顺序 issue。

3. 不把状态规模拉回 edge/token 粒度。
- 运行时新增状态应主要与 `active pre` / `band` / `block` 同量级。

4. 必须可在 SST 中建模。
- 需要有清晰的周期模型、状态机与统计链路。

5. 必须有流片 plausibility。
- 应能用“小 SRAM + FIFO + bitmap + credit + FSM”实现，而不是依赖不可控的复杂全局结构。

---

## 2. TIDE 的核心抽象：Address-Band Epoch

## 2.1 什么是 band

对每个 `destination core` 的 `GCSS-GLIDE` values 空间，已有：

- `pre_global -> (base, len)`
- 以及由 `base` 导出的真实物理地址顺序

`TIDE` 不推翻这个布局，而是在其上定义一个更粗粒度的服务单位：

- **`band = floor(addr / band_bytes)`**

其中：

- `addr = base_addr + base * sizeof(float)`
- `band_bytes` 是一个编译期/配置期可选参数，例如 `4KB / 8KB / 16KB`

因此，band 不是抽象的 cohort，也不是启发式 hash 桶，而是：

- **真实 DRAM 地址空间上的一个连续区间**

这点非常关键，因为它保证了 `TIDE` 的控制抽象是“物理真实”的，而不是“到 runtime 再猜一个分组”。

## 2.2 什么是 block-shared band color

`STORM` 的服务域天然是 `2x2 block`。但一个 `pre_global` 在 block 内不同 core 上，可能落在不同的 local band。

因此，`TIDE` 不要求“一个 pre 在 block 内四个 core 上落在同一个 exact band”；这太强，也不必要。相反，`TIDE` 定义：

- **`block-shared band color`**

对 block 内某个 `pre_global`：

1. 收集它在 4 个 core 上所有存在的 `local_band_id`
2. 计算一个 block-shared 的 `band_color`
   - 可用加权中位数 / dominant band / weighted centroid
3. 记录其 `band_span`
   - `span = max(local_band) - min(local_band)`

若 `span <= span_threshold`，则认为该 pre 是：

- **`band-coherent pre`**

否则标记为：

- **`wide pre`**

`wide pre` 在 `TIDE` 中允许 fallback 到 baseline 路径，不强行纳入 band epoch。

这个设计的好处是：

- `TIDE` 不需要让所有 pre 都 obey 同一个 block-level band contract；
- 只需要抓住最值得协同的那部分 `band-coherent pre`；
- 这样更稳，也更有硬件可实现性。

## 2.3 什么是 epoch

`epoch` 是 block 侧当前打开的 band 服务窗口：

- **`epoch = {block_id, epoch_id, band_color, credits}`**

含义是：

- 在当前一小段时间里，这个 `destination block` 更倾向服务 `band_color` 对应的权重工作集；
- `NoC` 侧若能把命中该 band 的 multicast 流量送过来，会更容易被当前 block 接住；
- `memory` 侧会优先 materialize 这一 band 的 pending pre，并在 band 内保持地址顺序 issue。

因此，`TIDE` 的真正共享抽象是：

- **`STORM` 发送的是 block 级 band wave**
- **`GCSS-GLIDE` 服务的是 band 内地址顺序 wave**

---

## 3. TIDE 的新硬件结构

## 3.1 `TIDE-BSC`：Band Service Coordinator

位置建议：

- 每个 `2x2 destination block` 旁边
- 逻辑上靠近 block ingress / `MulticastRouter` / shared block service 入口

职责：

1. 维护当前 block 的 `pending band` 状态
2. 跟踪每个 band 的 pending pre 数、pending payload 估计、age
3. 决定当前激活哪个 `epoch_band`
4. 维护 `band credits`
5. 向 block 内 4 个 core 下发当前 `open band`

推荐最小状态：

- `band_pending_count[B]`
- `band_pending_payload[B]`
- `band_age[B]`
- `band_open_credit[B]`
- `current_epoch_id`
- `current_open_band`

其中 `B` 推荐取 `32/64` 级别。

硬件成本非常低：

- 几十个小计数器
- 一个选择器
- 少量 FSM
- 一个小 bitmap RAM

这是典型可流片控制结构，而不是复杂的全局调度器。

## 3.2 `TIDE-LBM`：Lazy Band Materializer

位置建议：

- 每个 core 的 workload / weight front-end 前
- 逻辑上介于 `deliverPacket()` / `expandPreGlobalToWindowEdgesFast_()` 与 `WeightMemorySubsystem` 之间

职责：

1. incoming packet 到达后，不立即把所有 pre fully materialize 成 edge
2. 先按 `band_color` 放入 block/core 级 pending 结构
3. 只有当 `BSC` 打开对应 epoch 时，才把该 band 的 pre 取出并 materialize 成当前 apply window 所需 edge
4. materialize 后继续走现有 `GCSS-GLIDE + WMS` 路径

关键点：

- `LBM` 控制的是“何时展开 pre”
- 而不是“展开后如何乱排 edge”

这与 `CHORD-L` 完全不同：

- `CHORD-L` 是先有 edge，再按 cohort 改 issue order
- `TIDE-LBM` 是先按 band 控制 pre 的 materialization，再让 band 内 issue 继续按地址顺序进行

## 3.3 `TIDE-BCT`：Band Credit Table

位置建议：

- 每个 block 一份
- 可挂在 `BSC` 旁，或由 `BSC` 直接持有

职责：

- 为每个 band 维护一个粗粒度流量预算
- 防止某个 band 被无限吸入造成 block 内等待堆积
- 给 sender / ingress 一个简单、可缓存的 admission signal

状态示例：

- `credit_free[B]`
- `credit_refill_epoch`
- `credit_stall_total`

`BCT` 不需要像 cache coherence 一样复杂；它更像：

- destination-driven, band-scoped flow control

## 3.4 `TIDE-EB`：Epoch Beacon（可选，但推荐）

这是 `TIDE` 中最值得强调的新硬件小机制。

基本思想：

- 每个 block 在 epoch 切换时，生成一个极小的 beacon：
  - `{block_id, epoch_id, open_band, open_credit_class}`
- 该 beacon 被 source 侧 / send path 缓存
- sender 在有多个待发目标 block 的时候，可优先发“命中 open_band 的流量”

它的意义不是做强一致的全局控制，而是：

- 给 `STORM` 一个**memory-truth、destination-driven** 的轻量提示
- 让 NoC wave 与 memory wave 出现真正的闭环

为什么这点很关键：

- 过去 `global credit` 是全局 / step 级 / 与物理地址弱耦合的；
- `TIDE-EB` 则是 block-local / band-aware / 与真实地址强耦合的。

这就是 `TIDE` 相比历史 global credit 探索更 solid 的地方。

---

## 4. 离线编译与数据格式

## 4.1 设计原则

`TIDE` 必须建立在当前 `GCSS-GLIDE` 上，而不是另起一套数据格式。其编译原则是：

1. `GCSS-GLIDE` 的 values/index 主格式不变
2. `TIDE` 只增加极小的 block-band sidecar
3. 若某 pre 的 block-band coherence 不好，允许 fallback

即：

- **主数据格式继续是 `GCSS-GLIDE`**
- **`TIDE` 是它上面的一层协同 sidecar**

## 4.2 离线编译输出

建议新增离线生成器：

- `sst_dram_si/tools/gcss/gen_gcss_glide_tide_band.py`

输入：

- 现有 `GCSS-GLIDE` 目录
- `BCSR` / route builder 同源输入
- block 形状（默认 `2x2`）
- `band_bytes`
- `span_threshold`

输出：

### A. 每 core 的 local band sidecar

- `peXX/coreYY.gcss_tide_localband.bin`

内容：

- `pre_id -> local_band_id`
- 实际上该值也可由 `base >> band_shift` 推出；
- 因此此文件可选，调试期可显式生成，稳定后可不常驻存储。

### B. 每 block 的 shared band sidecar

- `blockZZ.tide_bandcolor.bin`

内容：

- `pre_global -> band_color`
- `pre_global -> span_class`
- `pre_global -> flags`
  - bit0 = `band_coherent`
  - bit1 = `wide_pre_fallback`

### C. manifest / meta

- `tide.meta.json`

记录：

- `band_bytes`
- `band_count`
- `span_threshold`
- `coherent_pre_ratio`
- `coherent_payload_ratio`
- `avg_pre_span`
- `top1_band_share`
- `top2_band_share`

这组离线指标会成为 `TIDE-P0` 的第一批证据。

## 4.3 为什么 sidecar 成本可控

`TIDE` 不应引入一个比 values 还大的“协同元数据系统”。其成本控制策略如下：

1. local exact band 优先从 `base` 推导，不单独存索引
2. block 共享 band 只存 coarse `band_color`
3. `band_color` 只需 `5~6 bit`
4. `span_class/flags` 也只需数 bit

因此，对每个 `(pre, block)` 目标，额外开销是极小的。

更重要的是：

- `TIDE` 的运行时状态与 `active pre` / `band` 同量级，
- 而不是与全局 synapse / edge 同量级。

这保证了其对于未来 `10M~100M` 神经元系统仍有体系结构可扩展性。

---

## 5. 运行时微结构与数据流

## 5.1 Sender 侧：在 `STORM` 路径上加入 band hint

当前 `STORM` 发送链路位于：

- `services/synapse/route/SynapseRouteSubsystem.cc::computeMulticastTargets()`
- `services/synapse/route/SpikeCommSubsystem.cc::emitCommon_()`

`TIDE` 的 sender 侧设计分两阶段：

### Phase A：dest-only（不改 packet 格式）

- sender 完全不需要知道 band
- 只按现有 `STORM` block multicast 发包
- receiver 自行查表分类到 band

优点：

- 风险最小
- 适合第一阶段闭环

### Phase B：full TIDE（推荐）

- 在 `BlockTarget` 中增加 `band_color`
- 在 `SpikeKey/SpikeTileKey/InterBundle` 头部增加可选 `band_hint`
- sender 根据 `Epoch Beacon` 与 `band_credit`，优先发送与目标 block 当前 `open_band` 更匹配的流量

这样做的价值是：

- `STORM` 从“只知道目标 block”升级到“知道目标 block 当前更适合接什么 band 的工作集”
- 但它知道的仍只是一个非常粗粒度的物理提示，而不是 exact line

## 5.2 Receiver 侧：band queue 化，而不是 edge queue 化

当前 `deliverPacket()` 在：

- `services/workload/snn/SnnWorkload.cc`

`TIDE` 接入后：

1. `SpikeKey/SpikeTileKey` 到达
2. 解码 `pre_global`
3. 先查 `band_color` / `band_coherent flag`
4. 若可纳入 `TIDE`：
   - 放入 `block_pending_band[band]`
   - 同时在对应 core 的 `pending_pre_by_band` 中登记
5. 若为 `wide_pre`：
   - 直接走 baseline `expandPreGlobalToWindowEdgesFast_()` fallback

关键变化：

- 不再“收到一个 pre 就立刻全量展开为 edge”
- 而是“先把 pre 放到对的 band 队列里，等待被 materialize”

## 5.3 Block 侧调度：`BSC` 如何选下一个 epoch

`BSC` 的 band 选择可以从一个最简单、最稳定的 score 开始：

- `score(b) = alpha * pending_payload(b) + beta * age(b) + gamma * beacon_match(b) - delta * recent_service_debt(b)`

第一版建议极简：

- 优先 `pending_payload` 最大的 band
- 相同则选 `age` 更老的 band
- 再相同则选 band id 更小者

并加入两个硬约束：

1. `max_epoch_quota`
- 防止单个 band 长时间霸占 block

2. `age_force_switch`
- 若某 band 等待超过阈值，则强制切换

这样 `TIDE` 可以保证：

- 有局部聚集性
- 但不饿死其它 band

## 5.4 Core 侧 materialization：只展开当前 band

当 `BSC` 打开某个 `epoch_band` 后：

1. 对 block 内每个 core 发出 `open_band` 信号
2. core 内 `LBM` 从 `pending_pre_by_band[open_band]` 取出 pre
3. 对这些 pre 执行现有 `expandPreGlobalToWindowEdgesFast_()` / `recordEdgeWithPreRank()` 路径
4. 交给 `WeightMemorySubsystem`

此时，`WeightMemorySubsystem` 内部：

- 不需要再引入 arrival/cohort 驱动的全局乱排
- 只需继续保持 `addr` 顺序 issue

因此，当前 `GCSS-GLIDE` 的主优势被完整保留。

## 5.5 WMS 侧：band 内保持地址顺序

当前 issue 队列准备逻辑在：

- `services/synapse/weights/WeightMemorySubsystem.cc::prepareGcssVlfIssueQueue_()`

`TIDE` 对 WMS 的要求很明确：

- band 外：通过 `LBM` 延后 materialization
- band 内：**继续按 `addr` 顺序** 组织 issue
- retire：继续按现有 seq / strict 规则

也就是说：

- `TIDE` 不是一个新的 WMS issue policy；
- `TIDE` 是对“进入 WMS 的 pre 工作集”的控制机制。

这点是它不重蹈 `CHORD-L` 覆辙的根本原因。

---

## 6. 语义与正确性约束

## 6.1 不改变 GAS 语义

`TIDE` 只允许改变：

- 一个 pre 何时被 materialize
- 哪个 band 先被服务
- sender 在多个目标 block 之间的发送先后

`TIDE` 不允许改变：

- 哪些 edge 会被处理
- 哪个 edge 最终对哪个 `post_local` 产生什么权重值
- retire 提交顺序
- `orch_.acc_update(post_local, delta)` 的最终数值行为
- strict validation 的结果

## 6.2 允许的“重排边界”

`TIDE` 允许：

- **pre/band 级 admission 重排**

`TIDE` 不允许：

- **band 内地址顺序重排**
- **ready callback 后的乱序 retire**
- **跨 post 语义副作用重排**

## 6.3 fallback 必须始终存在

以下情况必须无条件 fallback 到 baseline：

1. `wide_pre`
2. `band sidecar` 缺失
3. `band hint` 与 local exact band 严重不一致
4. `BSC/LBM` 饱和
5. `MESH_EXPERIMENTAL_ENABLE=0`

也就是说：

- `TIDE` 必须始终是“可旁路”的实验性硬件机制
- 而不能成为一条一旦开启就无法回退的高风险主路径

---

## 7. 为什么 TIDE 比现有思路更有论文价值

## 7.1 与 Loihi2 / Hala Point 的差异

公开资料显示，Loihi 2 / Hala Point 的核心优势仍在：

- 事件驱动
- 本地 memory / compute 共址
- mesh communication
- 扩展成更大系统

但它们的主叙事不是：

- destination-side off-chip DRAM truth service
- multicast wave 与 DRAM service wave 的统一协同

因此，`TIDE` 并不是在复用 Loihi 2 的经典路子，而是在一个 **DRAM-based SNN** 场景下引入新的协同层。

## 7.2 与 SpiNNaker2 的差异

SpiNNaker2 的公开资料明确强调：

- 本地 SRAM / TCM
- LPDDR2 接口
- packet router / multicast

这说明 SpiNNaker2 是一种“本地 memory 优先、off-chip 作为补充”的风格。`TIDE` 的差异在于：

- 它不是围绕本地 synaptic SRAM 设计；
- 它假设**权重主存就在真实 DRAM 后端**；
- 并把这个事实直接提升为 memory × NoC 协同抽象。

## 7.3 与 Darwin3 / 路由优化论文的差异

Darwin3 以及后续 routing/hierarchy 类工作主要聚焦于：

- mesh routing
- packet format
- compression
- on-chip memory save

`TIDE` 的关注点则是：

- 当 NoC 已经能高效把事件送到 block 后，如何让 destination-side 的 DRAM service 也按物理地址真实地协同起来。

因此，`TIDE` 的 novelty 不在“又一个 router trick”，而在：

- **首次在 DRAM-based SNN 中，把 multicast wave 与 DRAM address-band service wave 绑定成同一个 block-local 协同协议。**

---

## 8. 在现有代码中的建议落点

## 8.1 sender / route 侧

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.cc`
  - 扩展 `BlockTarget`：增加 `band_color` / `band_flags`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
  - 在 `SpikeKey/SpikeTileKey/InterBundle` 中可选加入 `band_hint`
  - 加入 `epoch beacon` 匹配优先级

## 8.2 receiver / workload 侧

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
  - 在 `deliverPacket()` 附近新增 `TIDE` pending path
  - 新增 `TideBlockServiceContext` / `TidePendingBandQueues`
  - 将当前立即 `expandPreGlobalToWindowEdgesFast_()` 的路径改成“band-queue -> materialize”

## 8.3 weight / memory 侧

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
  - 保持 band 内 `addr-order`
  - 不再继续演化 `CHORD-L` 这种跨 band 的 runtime reorder

## 8.4 配置链路

- `sst_dram_si/mesh_template/build.py`
  - 新增 `MESH_TIDE_ENABLE`
  - `MESH_TIDE_MODE=off|dest_only|full`
  - `MESH_TIDE_BAND_BYTES`
  - `MESH_TIDE_SPAN_THRESHOLD`
  - `MESH_TIDE_EPOCH_MAX_QUOTA`
  - `MESH_TIDE_BEACON_ENABLE`

## 8.5 离线工具

- `sst_dram_si/tools/gcss/gen_gcss_glide_tide_band.py`
- `sst_dram_si/tools/gcss/analyze_tide_band_oracle.py`

## 8.6 实验目录

- `mainexp/experiments/2026-03-xx_tide_ab_v1/`
- `mainexp/experiments/2026-03-xx_tide_p0_oracle_v1/`

---

## 9. 建模与统计设计

## 9.1 离线 `P0` 统计（必须先做）

目标：验证 `TIDE` 的 block-shared band 假设是否真的成立。

建议统计：

- `tide.coherent_pre_ratio`
- `tide.coherent_payload_ratio`
- `tide.avg_pre_span`
- `tide.band_entropy_avg`
- `tide.band_top1_share_avg`
- `tide.band_top2_share_avg`
- `tide.addr_backtrack_ratio_if_epoched`
- `tide.band_bytes_per_req_oracle`

这些统计应当直接回答两个问题：

1. block 内 active pre 是否真的集中到少数 band？
2. 若按 band epoch 服务，是否比 baseline 更接近“低 backtrack + 高 payload”的方向？

## 9.2 运行时新增统计

建议新增：

### block / band 层

- `tide.band_epochs_total`
- `tide.band_switches_total`
- `tide.band_age_forced_switch_total`
- `tide.band_credit_throttle_total`
- `tide.band_pending_pres_peak`
- `tide.band_pending_payload_peak`
- `tide.band_open_cycles_total[band]`（可聚合）

### materialization 层

- `tide.lbm_materialized_pres_total`
- `tide.lbm_materialized_edges_total`
- `tide.lbm_fallback_wide_pres_total`
- `tide.lbm_deferred_pres_total`
- `tide.band_coherent_hit_total`

### sender/beacon 层

- `tide.beacon_updates_total`
- `tide.beacon_matches_total`
- `tide.beacon_stale_uses_total`
- `tide.sender_band_match_issue_total`

## 9.3 必须继续对比的既有主指标

- `sim_time_actual_ns`
- `memctrl.req_total`
- `memctrl.bytes_est_total`
- `gas.payload_bytes_per_memctrl_req_avg`
- `gas.memctrl_payload_utilization`
- `gas.memctrl_traffic_amplification`
- `gas.overfetch_bytes_total`
- `gas.apply_ns_avg`
- `gas.apply_ns_p95`
- `routers_sum_byte_hops`
- `routers_sum_bytes_fwd_xy`
- `routers_sum_bytes_local`
- `nics_sum_tx_bytes`

`TIDE` 的目标不是只优化其中一个，而是让 memory 和 NoC 两侧的关键指标方向一致。

---

## 10. 分阶段落地计划

## 10.1 `TIDE-P0`：Oracle only

只做离线分析，不改 runtime。

目标：

- 判断 `band-coherent pre` 的比例是否足够高
- 判断 `band epoch` 是否能同时降低 backtrack、提升 payload oracle

若 `P0` 不成立，`TIDE` 不应进入 runtime。

## 10.2 `TIDE-L`：Destination-side only

只在 receiver/block/core 侧加入：

- `BSC`
- `LBM`
- `band queue`

sender / packet 格式完全不改。

目标：

- 单独验证 “band-queue + lazy materialization” 是否能在不扰乱地址顺序的前提下带来 memory 收益；
- 这一步是 `TIDE` 最关键的安全门。

### 10.2.1 当前已验证的 `TIDE-L Phase-1`（2026-03-08 复测）

需要明确区分“设计终版”和“当前仓库里已经通过正式 A/B 的形态”。截至 2026-03-08，仓库中真正已实现并通过主口径验证的，不是完整 `BSC + LBM`，而是一个更收敛的 destination-side local scheduler：

- runtime 位置：`WeightMemorySubsystem` 的 `gcss_vlf_issue_queue_`
- 模式：`experimental_tide_mode=local_band_barrier`
- 行为：按 `band_id=floor(addr/band_bytes)` 维持本地 band barrier；band 内继续保持当前 `addr-order issue`；retire 语义不变
- 这应视为 `TIDE-L` 的 **Phase-1 本地化实现**，其目标不是直接减少 DRAM 后端请求数，而是验证“local band coherence 能否改善 GAS apply 的收敛时序”

正式主口径证据如下：

- baseline：`mainexp/experiments/2026-03-08_tide_l_ab_v1/runs/full_system_baseline/20260308-102807`
- tide：`mainexp/experiments/2026-03-08_tide_l_ab_v1/runs/tide_l_8k/20260308-102807`
- 两边 `validation.log` 均为 `fail=0 warn=1`
- `model.sim_time_actual_ns`：`257453 -> 226960`（`-11.84%`）
- `gas.apply_ns_avg`：`239096 -> 211285.6875`（`-11.63%`）
- `gas.apply_ns_p95`：`253885.5 -> 225151.25`（`-11.32%`）
- `memctrl.req_total`：`150907 -> 150907`（不变）
- `gas.payload_bytes_per_memctrl_req_avg`：`20.2477 -> 20.2477`（不变）
- `gas.memctrl_payload_utilization`：`0.31637 -> 0.31637`（不变）
- `gas.overfetch_bytes_total`：`6602532 -> 6602532`（不变）
- `gas.unique_line_count_total`：`262838 -> 159708`（`-39.24%`）
- `gas.tide_band_epochs_total`：`0 -> 17551`
- `gas.tide_band_switches_total`：`0 -> 17231`
- `gas.tide_band_boundary_stall_total`：`0 -> 645201`

因此，当前应把 `local_band_barrier` 明确定位为：

- **一个已经被正式主口径验证有效的 `TIDE-L Phase-1`**
- 它带来的当前收益主要是 `memory-front scheduling / apply convergence` 收益
- 它还不是完整 `TIDE-BSC/LBM` 版本，因此不应过度表述为“已经实现完整 memory × NoC 协同”

## 10.3 `TIDE-B`：Beacon / band credit

在 `STORM` 路径加入：

- `band_hint`
- `epoch beacon`
- sender 侧 band-aware emission preference

但 destination-side exact service 仍保持 `TIDE-L` 已证明稳定的方式。

目标：

- 验证 memory × NoC 的真正协同增益是否出现

## 10.4 `TIDE-Full`

组合：

- dest-side band epoch service
- sender-side band-aware multicast admission

目标：

- 形成完整论文主图路径

---

## 11. 闭环实验设计

## 11.1 固定主口径

统一使用：

- `4x4`
- `bcsr10k`
- `step1`
- `ramulator2`
- `apply_issue_policy=order`
- `GCSS-GLIDE + STORM MulticastRouter`
- strict validation（`fail=0 warn<=baseline strict=0`）

即一律以当前 `full_system_baseline` 为唯一主基线。

## 11.2 实验矩阵

### P0

- `baseline_oracle`
- `tide_band_oracle`

### P1

- `full_system_baseline`
- `tide_l`

### P2

- `full_system_baseline`
- `tide_l`
- `tide_b`

### P3

- `full_system_baseline`
- `tide_full`

## 11.3 验收门槛

`TIDE` 的验收需要分阶段看，不能把 `Phase-1 local scheduler` 和完整 `memory × NoC` 终版混为一谈。

### `TIDE-L Phase-1`（当前已实现的 `local_band_barrier`）

要被视为有效，至少要满足：

1. 语义不变
- validation 与 baseline 同级通过

2. GAS / apply 完成时序改善
- `gas.apply_ns_avg` 或 `gas.apply_ns_p95` 明显下降
- `sim_time_actual_ns` 明显下降

3. 统计口径自洽
- 允许 `memctrl_req_total / payload_utilization / overfetch_bytes_total` 保持不变
- 但这时必须明确其收益来自 `memory-front scheduling`，而不是 DRAM 后端流量减少

### 完整 `TIDE-BSC/LBM` 或 `TIDE-B/TIDE-Full`

要被视为真正的系统级协同机制，还应额外满足：

1. memory 方向改善
- `memctrl_req_total` 下降
- `payload_utilization` 上升
- `overfetch` 下降

2. NoC 不恶化
- `byte_hops` / `tx_bytes` 不应显著回退

3. 端到端继续改善
- `sim_time_actual_ns` 不能仅靠局部调度收益支撑，而应体现 memory × NoC 联动收益

若只出现“局部指标好看但 `sim_time` 不动/回退”，则不进入主线叙事。

---

## 11.4 为什么 `unique_line_count_total` 会下降，而 `memctrl.req_total` 不变

这是当前 `TIDE-L Phase-1` 最需要讲清楚的机理点。结合代码，两个指标并不处于同一统计层：

1. `gas.unique_line_count_total / gas.covered_line_count_total / gas.overfetch_bytes_stat_total`
- 来源于 `GatherBufferIF::buildGranulesWithGapMergeBuf_()`
- 统计对象是当前一次 build 中收到的 `staged_reads`
- 其本质是 **前端 build / merge 诊断量**，反映“这一批 4B 小读在进入 granule builder 时有多分散”

2. `gas.unique_bytes_total / gas.overfetch_bytes_total / memctrl.req_total`
- `gas.unique_bytes_total` 来自 granule 真正 ready/完成后上报的 `g.size`
- `gas.overfetch_bytes_total` 在 summary 中由 `unique_bytes_total - payload_bytes_total` 推导
- `memctrl.req_total` 则是 memHierarchy / memctrl 的后端真实请求计数
- 这些量反映的是 **真正下沉到 DRAM 路径的请求集合**

因此，`TIDE-L Phase-1` 的正式结果

- `gas.unique_line_count_total: 262838 -> 159708`
- `gas.overfetch_bytes_stat_total: 13766116 -> 7165796`
- 但 `memctrl.req_total: 150907 -> 150907`
- `gas.overfetch_bytes_total: 6602532 -> 6602532`

并不矛盾。它说明的是：

- `local_band_barrier` 改变了前端 issue 的时间分布
- 让更多同 band / 同 line 的 4B 读在同一批次、更紧凑地进入 `GatherBufferIF`
- 从而降低了前端视角下的 line dispersion 与 build-time fragmentation
- 但这些请求在 baseline 中本来就大多会被同一个 granule / resident state 吸收，因此并没有进一步减少 DRAM 后端请求数

换句话说，当前 `TIDE-L Phase-1` 的收益不是“把 DRAM 请求数打下去了”，而是：

- **把相同的后端请求集合组织成了对 apply 更友好的完成时序**
- 最终体现为 `gas.apply_ns_avg / p95` 与 `sim_time_actual_ns` 改善

这个解释与正式实验完全一致，因此后续论文叙事中应把这一版收益明确写成：

- `front-end line clustering / completion-timing improvement`
- 而不是 `backend DRAM traffic reduction`

## 12. 风险点与防雷策略

## 12.1 风险：band 粗了，协同不真实

对策：

- 做 `P0` band sweep（`4KB/8KB/16KB`）
- 以 `coherent_payload_ratio + addr_backtrack_ratio` 决定 band 粒度

## 12.2 风险：block-shared band color 对 local core 不够真实

对策：

- 引入 `span_threshold`
- `wide_pre` fallback
- 统计 `coherent_payload_ratio`

## 12.3 风险：sender band-aware emission 变成另一个复杂全局调度器

对策：

- `epoch beacon` 只做弱提示，不做强一致
- 缓存陈旧也允许 fallback
- sender 只在“同一时刻存在多个候选发送块”时用作 tie-break

## 12.4 风险：又变成 `CHORD-L`

对策：

- 文档中明确规定：
  - band 内必须保持地址顺序
  - 不允许 arrival order 改写 WMS 的全局 `addr-order`

这是 `TIDE` 最重要的护栏。

---

## 13. 为什么 TIDE 有 ISCA/ASPLOS 潜力

`TIDE` 单独看，不是一个花哨的 codec 小技巧；它是一个把你们现有系统三条主线真正粘起来的协同层：

- `GAS`：执行语义主干
- `GCSS-GLIDE`：DRAM-truth memory layout 主干
- `STORM`：NoC multicast 数据面主干
- `TIDE`：block-local address-band 协同控制层

它的创新性来自：

1. 不是 local SRAM 优先的经典 neuromorphic 叙事
2. 不是“只优化 NoC”或“只优化 memory”的单侧机制
3. 不是 token/line exact service 的高风险重平面
4. 而是一个面向 DRAM-based SNN 的、新的 block-level physical-band protocol

当前已经拿到的证据是：

- `TIDE-L Phase-1(local_band_barrier)` 已能稳定改善 `gas.apply_ns_avg/p95` 与 `sim_time_actual_ns`
- 但其收益仍主要来自 destination-side `memory-front scheduling`，还不是完整的 `memory × NoC` 协同闭环

如果后续实验进一步证明：

- `band-coherent pre` 覆盖率高
- 完整 `TIDE-BSC/LBM` 能把当前 Phase-1 收益推进为真正的 memory 主指标改善
- `TIDE-B` 再把 NoC wave 与 memory wave 对齐

那么 `TIDE` 很有潜力成为整篇论文里“把 full system 串起来”的关键协同创新点。

---

## 14. 当前建议

当前建议明确如下：

1. **不要再推进 `CHORD-L` 这类跨 band runtime reorder 路线**
2. **把当前 `local_band_barrier` 明确收敛为 `TIDE-L Phase-1`，并作为“已验证有效的 destination-side local scheduler”进入主线候选**
3. **下一步优先做两件事：先补机理统计，把 `front-end line clustering` 证据补齐；再推进完整 `TIDE-BSC/LBM` 与 `TIDE-B`**
4. **任何阶段都必须保持 `full_system_baseline` 口径与 strict validation 不变**

截至目前，`TIDE` 是最符合以下四点的候选方案：

- 足够 novel
- 足够 solid
- 足够 work
- 足够贴合当前 `GAS + GCSS-GLIDE + STORM` 主线

---

## 15. 参考资料（外部）

这些资料用于明确当前公开 neuromorphic / SNN 芯片的主流内存层次与通信范式，从而帮助定位 `TIDE` 的差异化空间：

- Intel Loihi 2 Technology Brief  
  https://www.intel.com/content/dam/www/central-libraries/us/en/documents/neuromorphic-computing-loihi-2-brief.pdf

- Intel Hala Point press release（2024-04-17）  
  https://newsroom.intel.com/artificial-intelligence/intel-builds-worlds-largest-neuromorphic-system-to-enable-more-sustainable-ai

- SpiNNaker 2 prototype memory hierarchy / LPDDR2  
  https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2018.00840/full

- Darwin3 paper  
  https://academic.oup.com/nsr/article/doi/10.1093/nsr/nwae102/7631347

- Darwin3 arXiv preprint  
  https://arxiv.org/abs/2312.17582

---

## 16. Post-dest-only：下一条真正主线应为 `TIDE-CAST`

### 16.1 为什么现在要从 `BSC/LBM` 转向新的协同对象

`dest-only TIDE-BSC/LBM` 的正式复测已经给出一个非常明确的边界：

- 纯 receiver-side 的 lazy band materialization 可以把 `TIDE-L` 的收益重新走通；
- 但它没有改变跨 NoC 进入 receiver 的工作 granule；
- 因此它没有继续推进 `memctrl.req_total`，也没有继续推进 `payload_bytes_per_memctrl_req_avg`。

换句话说，当前真正剩下的主矛盾不再是：

- “receiver 该先开哪个 band”

而是：

- **“进入 receiver 的对象，为什么仍然是 per-pre / per-block 的通信 granule，而不是更贴近 DRAM band/locality 的 granule？”**

所以，下一条主线不能继续在 receiver 末端加控制面，而必须把 memory locality 编译进 NoC 粒度本身。

### 16.2 推荐机制：`TIDE-CAST`

推荐把下一条主线机制定义为：

- **`TIDE-CAST`**
- 展开：**`Traffic-Integrated DRAM Epochs with Cohort-Aware Spike Transport`**

它的核心思想是：

- 不再只让 `STORM` 传“一个 pre 对一个 destination block 的 SpikeKey”；
- 而是让发送侧基于 `GCSS-GLIDE` 离线布局导出的 **`band color / service cohort`**，把多个将会命中相近 memory band 的 `pre_global`，在 NoC 上就聚合成一个 **cohort packet**；
- receiver 侧不再对这些 pre 逐个立即展开，而是按 cohort/band 进入 `LBM`；
- 最终仍由当前稳定的 `TIDE-L + GCSS-GLIDE + strict retire` 走 exact value path。

一句话概括：

- **`TIDE-CAST` 不是新增一条 exact value plane，而是把 `STORM` 的 packet 粒度变成 memory-aware，从根源上减少 band 混杂。**

### 16.3 为什么它比继续做 `BSC sender/open-band` 更对路

因为 `BSC sender/open-band` 本质上仍是在发送或接收侧做“控制谁先走”，但没有改变 packet 里装的是什么。

而 `TIDE-CAST` 直接改变的是：

- 哪些 pre 会一起走网络
- 哪些 pre 会一起进入 receiver 的 pending set
- 哪些 pre 会一起进入 `TIDE-L` 的 local-band issue wave

这带来的潜在收益是双侧的：

1. **NoC 侧**
- 更少的 packet / header / bundle 项
- 更高的 `pres per packet`
- 更低的 block 内混杂

2. **Memory 侧**
- 更低的 `tide_band_boundary_stall_total`
- 更低的 `retire_global_hol_cycles_total`
- 更强的 `frontend_line_touch_reuse_ratio`
- 若 cohort 划分足够纯，还可能继续降低 `covered_line_count_total / memctrl.req_total`

### 16.4 机制分层

`TIDE-CAST` 应分成四层：

#### A. 离线 sidecar：`band_color / cohort_id`

对每个 `(pre_global, dst_block)`，离线从现有 `GCSS-GLIDE` 布局中导出一个小标签：

- `band_color`
- 或更泛化的 `service_cohort_id`

推荐第一版采用非常保守的小标签：

- 基于 block 内 4 个 PE / 多个 core 的 dominant local band
- 再叠加 `span_class`
- 压成一个小 `cohort_id (<=16)`

这样 sidecar 规模非常小，但能把 `NoC granule` 与 `memory band tendency` 连起来。

#### B. 发送侧：`SpikeTileBatchEmitter / SpikeCommSubsystem`

直接复用现有 tile/bundle 路径，而不是新造一整条发送数据面。

发送侧新增的唯一主逻辑是：

- 把原本按 `(dst_block, block_col)` 或 `(dst_block)` 聚合的 packet，改成按
  - `(dst_block, cohort_id)`
  - 或 `(dst_block, cohort_id, block_col)`
 进行 batching

也就是说，当前最自然的代码落点就是：

- `services/synapse/route/SpikeTileBatchEmitter.h`
- `services/synapse/route/SpikeCommSubsystem.cc`
- `services/synapse/route/SynapseRouteSubsystem.{h,cc}`

其中 `SynapseRouteSubsystem::BlockTarget` 非常适合扩展成携带 `cohort_id/band_color` 的静态路由 sidecar。

#### C. 接收侧：`SnnWorkload` 的 cohort pending queue

receiver 不直接逐 pre 展开，而是：

- 先按 `cohort_id` / `band_color` 记入 `pending_pre` 桶
- 每个 pre 仍只保留 `count`，不膨胀到 edge/token 粒度
- 与当前 `dest-only` 修好的 `pre_rank count merge` 语义保持一致

这一层最自然的落点是：

- `services/workload/snn/SnnWorkload.cc`

#### D. 执行侧：`TIDE-L` 继续做 exact local-band stabilizer

`TIDE-CAST` 不替代 `TIDE-L`，而是给它喂更干净的输入。

链路应当是：

- `STORM cohort packet`
- `SnnWorkload pending_pre_by_cohort`
- `LBM materialize-by-band`
- `TIDE-L local-band issue`
- `strict retire`

这样 exact value path 完全不变，语义风险最低。

### 16.5 与当前代码边界的兼容性

这条路线之所以值得优先做，是因为它非常贴当前代码骨架：

1. 发送侧已有 block-aware / tile-aware batching 框架
2. receiver 侧已有 `pre_rank count merge` 与 `dest-only` pending 经验
3. `TIDE-L` 已证明 local-band barrier 有价值
4. `GlobalGasStepController` 已有 per-step control-plane 下发能力；若以后要加 `next-step preferred cohort` hint，可以自然 piggyback 到现有 `GasStepBarrierEvent`

因此它不是“再造系统”，而是：

- **把当前三块已验证资产真正串成一个协同链路**

### 16.6 推荐的闭环判据

`TIDE-CAST` 是否值得继续推进，必须看下面两组证据：

#### 主收益指标

- `model.sim_time_actual_ns`
- `gas.apply_ns_avg`
- `gas.tide_band_boundary_stall_total`
- `gas.retire_global_hol_cycles_total`
- `gas.retire_ready_but_blocked_edges_total`
- `gas.unique_line_count_total`
- `gas.frontend_line_touch_reuse_ratio`
- `memhierarchy.memctrl.req_total`
- `gas.payload_bytes_per_memctrl_req_avg`
- `gas.memctrl_payload_utilization`

#### 新增跨层统计

建议新增：

- `storm.cohort_packets_total`
- `storm.cohort_pres_total`
- `storm.avg_pres_per_cohort_pkt`
- `storm.cohort_bandcolor_switch_total`
- `gas.cohort_pending_peak`
- `gas.cohort_materialized_pres_total`
- `gas.cohort_exact_band_purity_avg`
- `gas.cohort_fallback_total`

如果 `TIDE-CAST` 只能降低 `HOL`，但仍无法推动 `memctrl.req_total / payload_utilization`，那就说明当前 `dst-core private values` 布局已经成为真正的硬下界；再往前就需要进入更激进的、选择性 block-home shared-line 路线。

### 16.7 最终建议

因此，当前 `TIDE` 主线应重新收敛为：

- `TIDE-L`：稳定有效，保留为主线 memory-side local-band stabilizer
- `TIDE-BSC/LBM dest-only`：冻结为 bridge / negative lesson，不再主线化
- **`TIDE-CAST`：下一条真正值得实现的 memory × NoC 协同主线**

它比继续扩展 `dest-only BSC` 更合理，也比重新回到 `PRISM / naive TASS / 纯调度优化` 更贴当前系统主干。
