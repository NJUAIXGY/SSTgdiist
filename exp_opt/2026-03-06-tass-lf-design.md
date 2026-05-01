# TASS-LF：面向 STORM×GAS 的 2x2 Block 对齐突触服务机制设计

日期：2026-03-06
状态：基于离线可行性分析收敛出的主设计方案

## 0. 设计结论

基于 `memop/experiments/2026-03-06_tass_feasibility_v1` 的离线结果，当前最值得推进的新机制不是朴素的 block-level prefetch，也不是更强的 credit，而是：

- **`TASS-LF`**
- 展开：`Tile-Aligned Synapse Service with Line Fusion`

它的目标是：

- 将 `STORM + MulticastRouter` 已经形成的 `2x2 block` 传播粒度，直接升格为 `GAS` 的 memory service 粒度；
- 同时把 block 级 active pre 的 **cross-pre line fusion** 纳入服务路径；
- 最终把 NoC 侧已经存在的 tile/block 相关性，转化成 DRAM 侧可见的 payload 利用率提升与事务数下降。

## 1. 为什么不是朴素 TASS

离线结论非常明确：

1. `PE` 级不够强
- active payload 只有 `8.29B/line`
- 不能成为足够强的体系结构收益点

2. `2x2 block` 级是正确服务域
- active payload 提升到 `25.02B/line`
- active pre 共享比例达到 `98.43%`
- `avg_cores_per_active_pre ≈ 5.77`

3. 但“同 pre 聚合”仍然不够
- 当前主线 runtime 已经达到 `20.33B/request`
- 而离线朴素 block2x2 同 pre packing 只有 `25.02B/line`
- 这说明如果新机制只做“同 pre 聚合”，它可能只有有限边际收益

因此，真正应当推进的是：

- **block-level synapse service**
- 加上
- **block-level cross-pre line fusion**

这就是 `TASS-LF`。

## 2. 核心思想

### 2.1 结构性错配

当前主线存在一个非常明确的结构性错配：

- `STORM` 在 NoC 侧已经把数据组织成 `tile/block` 级传播单元；
- `GAS` memory side 仍然按 `core/edge` 级单元服务；
- `WeightMemorySubsystem` 再靠 `VLF-line` 去做地址级重聚。

也就是：

- NoC 先聚
- GAS 再散
- memory issue 再聚

### 2.2 TASS-LF 要做的事

`TASS-LF` 的目标是打通这条链路：

- `SpikeTileKey` 到达 block ingress 后，不再立即完全打散到每个 core 的 edge queue；
- 而是在 `2x2 block` 域内先形成一个 block-shared synapse service epoch；
- 针对这批 active pre，按 block-shared layout 直接形成 line-oriented 的 DRAM 服务请求；
- DRAM 返回后，在 block 内本地 fanout 给需要的 cores；
- cores 最终仍按 `GAS` 的 seq / retire 规则提交。

因此：

- 变的是“怎么拿到权重”
- 不变的是“权重如何影响语义与 retire”

## 3. 结构设计

### 3.1 新的服务域：2x2 block

本方案固定服务域为 `2x2 PE`，与当前 `STORM` block 默认形状一致。

原因：

- 离线分析显示 `PE` 级共享不足；
- `2x2 block` 级共享非常强；
- 这样能够直接复用 `STORM + MulticastRouter` 的 ingress/block 语义。

### 3.2 新的硬件单元：Tile Synapse Service Engine

建议新增一个实验性硬件单元：

- **Tile Synapse Service Engine (TSSE)**

放置位置：

- `2x2 block ingress` 或 block 内共享服务节点

职责：

1. 接收 `SpikeTileKey` / block-level active pre 集合
2. 暂存一个 block-shared micro-epoch
3. 根据 block-shared synapse descriptor 生成 line-level service 请求
4. 跟踪 line 返回后的本地分发目标
5. 通过 block 内本地通路完成 response fanout

它不直接做最终 neuron update，只负责 block 级 synapse service orchestration。

### 3.3 新的数据格式：GCSS-GLIDE-B2

建议在 `GCSS-GLIDE` 基础上新增一个 block 级变体：

- 暂定名：`GCSS-GLIDE-B2`

核心原则：

1. 仍然 locality-preserving
2. 仍然是 values-only + compact index 思路
3. 但存储服务单位从 `dst-core` 升到 `dst-block`
4. layout 的 profile 输入不再只看单 core，而看 `2x2 block` 的 union activity / transition

格式要表达的信息：

- `pre_global -> block_slot`
- `block_slot -> line directory`
- `line -> [(core_id, post_local, lane_offset), ...]`

也就是说，索引不只回答“这个 pre 的 values 在哪”，还要回答：

- 这一条 line 回来后，该分发给 block 内哪些 core / post。

### 3.4 Line Fusion

这是 `TASS-LF` 与朴素 TASS 的关键区别。

如果只按同 `pre` 做 block 聚合，收益不足以形成特别强的论文点。

因此必须引入 block-level cross-pre line fusion：

1. 离线布局阶段
- 用 block union profile 做 `pre` 排序
- 尽量让经常共同活跃的 pre 段物理相邻
- 提升“多 pre 共线”的机会

2. 运行时阶段
- block micro-epoch 内不只保留“哪个 pre 活跃”
- 还构造“哪些 line 可以被本轮共享服务”
- issue 以 line 为主，而不是以单个 pre segment 为主

这一步实际上把当前 core-local `VLF-line` 升级为 block-shared `line fusion`。

### 3.5 本地 response multicast

DRAM 返回不再被视作“某一个 core 的私有读响应”，而应被视作：

- **block 内共享的 synapse line resource**

因此需要：

- line 返回后，由 TSSE 查 line directory
- 在 block 内做本地 multicast / fanout
- 交付给对应 cores 的 local GAS consumer

这与 `STORM` 的 forward multicast 在思想上是镜像的：

- 前向：一个 spike 服务多个目的端
- 回包：一条 synapse line 服务多个 cores/posts

## 4. 与 GAS 语义的关系

### 4.1 不变的部分

以下语义必须保持不变：

1. neuron update 语义
2. per-core apply 的结果等价性
3. retire 的确定性与顺序约束
4. strict validation 口径

### 4.2 变化的部分

变化只发生在 memory service 层：

1. edge 不再总是由 core 自己单独触发一条 DRAM 读
2. block 内多个 core 的需求会先在 TSSE 里合并
3. DRAM 请求以 block-shared line 为基本服务单元
4. line 返回后再分发到各自 core 的 retire 队列

因此，从 `GAS` 视角看：

- 它仍然控制什么时候一个 edge ready 可以 retire；
- 只是 edge ready 的来源，从“单核私有回包”变成“block-shared service 回包”。

## 5. 关键统计项

为了证明 `TASS-LF` 真正起效，需要新增一组 block-level 统计：

### 5.1 memory 侧

1. `gas.tass_block_payload_bytes_per_req_avg`
2. `gas.tass_block_payload_utilization`
3. `gas.tass_block_line_share_fanout_avg`
4. `gas.tass_block_line_share_fanout_max`
5. `gas.tass_line_directory_hits_total`
6. `gas.tass_line_directory_miss_total`
7. `gas.tass_block_req_total`
8. `gas.tass_block_resp_multicast_total`

### 5.2 跨层协同侧

1. `gas.tass_active_pres_per_block_avg`
2. `gas.tass_shared_pres_per_block_avg`
3. `gas.tass_cross_core_join_total`
4. `gas.tass_cross_pre_fusion_total`
5. `gas.tass_local_resp_fanout_bytes_total`

### 5.3 端到端主指标

仍然沿用主线指标：

1. `sim_time_actual_ns`
2. `memctrl_req_total`
3. `memctrl_bytes_est_total`
4. `gas_payload_bytes_per_memctrl_req_avg`
5. `gas_memctrl_payload_utilization`
6. `gas_memctrl_traffic_amplification`
7. `validation.log`

## 6. 闭环实验方案

### 6.1 固定口径

- `4x4 bcsr10k step1`
- `ramulator2_ddr5`
- `STORM + MulticastRouter`
- `GAS`
- 当前主线 `GCSS-GLIDE`

### 6.2 A/B/C 三组对比

1. `baseline`
- 当前主线：`GAS + GCSS-GLIDE + STORM + MulticastRouter`

2. `naive_tass`
- 只做 `2x2 block` 同 pre 共享服务
- 不做 cross-pre line fusion

3. `tass_lf`
- 做 `2x2 block` 服务
- 做 block-level cross-pre line fusion
- 做 block 内 response multicast

### 6.3 预期结论

理想证据链应当是：

1. `naive_tass` 只能带来有限改善
- 证明本轮离线分析是对的

2. `tass_lf` 才能明显拉动：
- `gas_payload_bytes_per_memctrl_req_avg`
- `gas_memctrl_payload_utilization`
- `memctrl_req_total`
- `sim_time_actual_ns`

这样可以把论文故事写成：

- 不是“block 共享本身就神奇”
- 而是“block 粒度 + line fusion + local response multicast”三者共同形成体系结构收益

## 7. 当前最终建议

基于现有离线结果，建议后续正式推进的不是：

- 朴素 `TASS`

而是：

- **`TASS-LF`**

一句话定义：

- **`TASS-LF` 将 STORM 的 2x2 block 传播粒度，提升为 GAS 的 block-shared synapse service 粒度，并通过 cross-pre line fusion 与本地 response multicast，将 NoC 相关性转化为 DRAM payload 效率。`**

这比继续做更强的 `credit`、`prefetch` 或 `retire policy`，更像当前系统里那个真正有画龙点睛作用的新体系结构点。
