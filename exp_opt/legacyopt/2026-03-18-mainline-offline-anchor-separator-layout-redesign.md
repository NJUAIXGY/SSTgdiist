# 主线激进转向：Offline Anchor-Separator Weight Layout Redesign

> 日期：2026-03-18  
> 状态：design-approved  
> 范围：`snndl` 主线，仅限 `offline generator / artifact layout`  
> 目标：在不修改 runtime 主契约的前提下，放弃继续堆叠 online/greedy selector，转为更激进的 offline 权重排布改写，以直接压制 HOL / closure 退化根因。

---

## 0. 一句话结论

当前主线问题的根因已经不再是“selector 打分还不够好”，而是：

- 当前优化单位仍然是单个 `pre segment` 的局部选择；
- 但文档和静态 gate 反复暴露的问题，本质上是 **target-neighborhood geometry** 被切散、漂移、重排；
- 因此继续在 `_order_by_profile_*greedy()` 上叠加 guard 或 numeric penalty，已经不具备主线前进价值。

下一阶段应正式止损：

- `hol_profile_dual_guard_v3`：`NO-GO`
- `hol_profile_dual_guard_v4`：`NO-GO`

并切换到新的主线：

- **`offline_anchor_separator_layout_v1`**

它不是“再换一个 greedy selector”，而是：

- 先离线识别高风险 target 社区；
- 再按社区/分隔子图做分层分块；
- 最后只在块内做 profile-preserving 排列。

---

## 1. 为什么必须从 selector 转到 layout rewrite

### 1.1 本地证据已经说明问题是全局几何，不是局部打分

当前最强的静态证据来自：

- `mainexp/experiments/2026-03-18_dual_guard_v4_static_gate_v1/snapshot/global_meta_summary.json`
- `mainexp/experiments/2026-03-18_dual_guard_v4_static_gate_v1/snapshot/pe00_core00_target_pre3438.json`
- `mainexp/experiments/2026-03-18_dual_guard_v4_static_gate_v1/snapshot/top_abnormal_core_summary.tsv`

关键事实：

1. `v3` hard-lex 失败；
2. `v4` numeric penalty 仍然失败；
3. `pe00/core00 target_pre=3438` 从 baseline `1962` 退化到 `2566`；
4. 全局 `fat_tail_guard_trigger_total` 从 `32659` 暴涨到 `1431264`；
5. top abnormal cores 里存在极端 rank 漂移：
   - `27870 -> 9949`
   - `27483 -> 7407`
   - `7584 -> 27908`

这说明：

- 失败不是某个 penalty 的权重不对；
- 而是当前可行解空间本身允许太多 broad reshape；
- 一旦 target 和关键邻域没有被全局布局保护，局部 selector 无法稳定救回 closure。

### 1.2 当前主线真正缺的是“受保护的几何”，不是“更 aggressive 的 target 前推”

我们目前已经确认：

- baseline runtime 是稳定的；
- 问题集中在 offline values layout 与 `locality_first issue + global_inorder retire` 的结构错配；
- 因此新的主线目标不应是“更积极地把 target 提前”，而应是：
  - 让 target-neighborhood 保持局部凝聚；
  - 让高风险社区之间被 separator 或 filler 隔开；
  - 让 line fill 不再通过跨社区混编来换取。

---

## 2. 外部方法给我们的直接启发

以下资料不是要照搬，而是作为主线转向的理论支持：

### 2.1 Gorder：访问相关节点应该被成组放置，而不是局部逐步贪心

- 论文：`Gorder: An Efficient Method for Graph Ordering to Improve Cache Locality of Graph Processing`
- 链接：<https://static.aminer.org/pdf/20170130/pdfs/sigmod/eaiuksncuwvgkdr693vpelt2talhjoox.pdf>

启发：

- 离线 reorder 的代价可以被多次执行摊销；
- 访问相关节点的成组放置，比纯局部贪心更能稳定提升 locality；
- 对我们而言，对应的是：
  - 不应再把每一步的“next pre”当成主要优化对象；
  - 应把高风险 target-neighborhood 社区作为更高一级的布局单位。

### 2.2 GPOP：partition-centric 比 element-centric 更稳定

- 论文：`GPOP: A scalable cache- and memory-efficient framework for graph processing over partitions`
- 链接：<https://arxiv.org/abs/1806.08092>

启发：

- 当访问模式具有明显社区性或热点结构时，partition-first 往往比纯 vertex/edge-centric 更可控；
- 对我们而言，对应的是：
  - 先 partition / block；
  - 再在块内局部优化；
  - 而不是继续在全局队列里逐 pre 争抢位置。

### 2.3 超图划分/矩阵重排：真正有效的是“切边最小化 + 多级 locality”

- 技术报告：`Hypergraph Partitioning-Based Models and Methods for Exploiting Cache Locality in Sparse Matrix-Vector Multiplication`
- 链接：<https://arxiv.org/abs/1202.3856>

启发：

- 稀疏结构的 locality 优化本质上是：
  - 降低跨分区切边；
  - 控制 temporal locality 被切散；
  - 让分块规模对齐 memory hierarchy。
- 这与我们当前问题高度一致：
  - target 弱邻域被切散后，即使 target 自身看起来还行，closure 也会变差。

### 2.4 Sloan / Wavefront Reduction：更适合作为块内排序器，而非全局主目标

- 论文：`An Algorithm for Profile and Wavefront Reduction of Sparse Matrices`
- 链接：<https://www.newcastle.edu.au/__data/assets/pdf_file/0020/22484/11_An-algorithm-for-profile-and-wavefront-reduction-of-sparse-matrices.pdf>

启发：

- profile / wavefront reduction 在局部块内很有价值；
- 但它不是拿来解决全局社区几何问题的主工具；
- 对我们而言，应让它成为：
  - anchor block 内部的顺序器；
  - 而不是整个 artifact 的主控布局器。

### 2.5 Memory Hierarchy Sensitive Layout：布局必须分层，不是只盯 cacheline

- 论文：`Memory Hierarchy Sensitive Graph Layout`
- 链接：<https://arxiv.org/abs/1203.5675>

启发：

- 有效布局应该同时考虑 line / page / TLB / row 等多级边界；
- 对我们当前版本，虽然还没有精确 DRAM row 模型接入 generator，但至少要先做：
  - `64B line`
  - `1KB microblock`
  - `4KB mesoblock`
  - `16KB macroblock`
 这样的层次化排布。

---

## 3. 新主线：`offline_anchor_separator_layout_v1`

### 3.1 核心思想

新方案的核心不是“把 target 放前面”，而是：

1. 识别高风险 target；
2. 为每个 target 构建弱邻域社区；
3. 合并重叠社区，形成 anchor communities；
4. 用 separator / filler blocks 把高风险社区隔开；
5. 块内再做轻量 profile-preserving 排序；
6. 禁止为了 line fill 跨社区混编。

### 3.2 不变的硬边界

以下内容继续冻结：

1. 不改 runtime
2. 不改 `prepareGcssVlfIssueQueue_()` / `popNextGcssVlfIssueEntry_()` / `tryRetireEdges_()`
3. 不改 `lookup(pre) -> (base, len)` / `base + pre_rank`
4. 不改 index 语义
5. 不做 online reorder
6. 不回到 `bcsr_gas`

也就是说，这仍然是一个纯 `offline generator / artifact layout` 方案。

---

## 4. 布局对象：从单个 pre 转向社区与块

### 4.1 基本对象仍然是 `pre segment`

首版仍然保持：

- 节点 = `pre segment`
- `seg_len(pre)` = values 段长度

原因：

- 这样不破坏当前 schema；
- 不需要引入 splitting / duplicate storage；
- 能先验证“社区与块”这个更高层布局目标是否成立。

### 4.2 新的优化层级

从高到低，新的布局层级为：

1. `anchor community`
2. `macroblock`
3. `mesoblock`
4. `microblock`
5. `line`
6. `pre order inside line`

主线变化在于：

- 过去主要优化第 6 层；
- 现在要先优化第 1-4 层，再允许第 5-6 层做小幅填充。

---

## 5. 图模型

### 5.1 节点权重

每个 `pre` 节点维护：

- `seg_len`
- `profile_freq`
- `head_hits`
- `head_depth_avg`
- `target_score`
- `weak_neighbor_degree`

用途：

- `target_score` 用于选 anchor；
- `seg_len` 用于 block packing；
- `profile_freq` 用于 filler 稳定排序；
- `head_*` 用于块内 anchor band 保护。

### 5.2 边权重

构建无向 `G_pre`，边权由以下项线性组合：

1. `transition_weight(src, dst)`
   - 来自 `pre_windows.csv`
2. `cohead_weight(src, dst)`
   - 同一 HOL 头部窗口共同出现次数
3. `weak_neighbor_weight(src, dst)`
   - 来自现有 `weak_neighbors`
4. `spill_risk_weight(src, dst)`
   - 若二者组合更容易形成 shared tail / line spill，则加权

首版不做复杂学习参数，建议简单静态组合：

- `edge_weight = trans + 2 * weak + cohead + spill`

目标不是求最优图论结果，而是先构出“社区边强、跨社区边弱”的稳定结构。

---

## 6. Anchor Community 形成

### 6.1 Anchor Seeds

首版仍沿用当前高风险 seed 提取：

- `target_top_m = 32`
- 以 `target_score` 排序

### 6.2 Community Expansion

每个 seed 的初始社区由三部分组成：

1. seed 自身
2. `weak_neighbors(seed)` 的 top-K
3. 在 `G_pre` 上与 seed 边权最高的 top-N 补充节点

建议首版：

- `weak_top_k = 8`
- `trans_expand_top_n = 4`

### 6.3 Community Merge

若两个 seed 社区 overlap 较强，则合并：

- `merge_if_jaccard >= 0.5`

合并后形成最终 `anchor communities`。

### 6.4 Separator Nodes

不在任何 anchor community 中的节点视为：

- `separator/filler pool`

这些节点不是“不重要”，而是：

- 不应允许它们破坏 anchor 社区几何；
- 应承担填充和隔离作用。

---

## 7. 分层分块

### 7.1 Block 尺寸

首版固定单点，不做 sweep：

- `microblock_values = 256` 约 `1KB`
- `mesoblock_values = 1024` 约 `4KB`
- `macroblock_values = 4096` 约 `16KB`

### 7.2 Block Packing

规则：

1. 一个 anchor community 尽量完整落入同一 `macroblock`
2. 若超出 `macroblock_values`，按社区内部顺序切成多个相邻 block
3. filler/separator 只能填充本层 block slack，禁止跨 anchor 混编

这意味着：

- 可以接受少量 fill 损失；
- 但不接受因为 fill 更满而切散 target-neighborhood。

### 7.3 Block Order

块间顺序使用：

- anchor block
- separator block
- filler block

组成交替序列。

原则：

1. 高风险 anchor block 可以进入“早段区”
2. 但不允许所有高风险块被整体 front-load
3. anchor block 之间尽量插入 separator/filler，降低互相干扰

---

## 8. 块内顺序

### 8.1 Anchor Band

块内设置受保护前带：

- `anchor_band_lines = 4`

含义：

- 关键 target 及其最强弱邻域优先进入块内前带；
- 但仅在块内生效，不允许上升为全局极端前推。

### 8.2 Separator Slack

块尾保留：

- `separator_slack_lines = 2`

含义：

- 避免尾部为 line fill 把下一个社区的成员拉进来；
- 把“局部浪费少量容量”当作换取 closure-stability 的必要成本。

### 8.3 Intra-block Orderer

块内采用简化的 profile/wavefront reducer：

- 优先 anchor
- 再按本块局部图的 adjacency/profile 权重
- 再按 `seg_len`
- 再按 baseline rank

首版不强行实现完整 Sloan，只做“Sloan 风格的局部 profile-preserving orderer”即可。

---

## 9. 与当前主线的关键区别

当前失败路线：

- `v3` / `v4`
- 仍在每一步从候选池里选“下一个 pre”
- 问题是局部决策永远可能把社区整体切坏

新路线：

- 先固定社区
- 再固定块
- 最后才做块内排序

本质区别是：

- 旧方案优化的是 local move
- 新方案优化的是 feasible geometry

这是这轮必须激进切换的原因。

---

## 10. 新的静态 gate

旧 gate 主要看：

- target rank
- neighborhood moved count
- fat-tail trigger

新 gate 要新增社区/分块指标：

1. `anchor_escape_count`
   - 弱邻域节点被排到社区外的数量

2. `anchor_local_span_p95`
   - target 到弱邻域的 rank span 的 P95

3. `cross_block_weak_edge_weight_ratio`
   - 弱邻域边权有多少落在跨 block

4. `anchor_block_count`
   - 社区数量是否合理，避免过度碎片化

5. `block_slack_values_total`
   - 为稳定性付出的 slack 成本

6. 继续保留：
   - `fat_tail_guard_trigger_total`
   - `top_abnormal_core_count`
   - `target_pre=3438` 等固定哨兵 case

通过门槛：

- 不能再出现 `v4` 这种 broad reshape；
- `fat_tail_guard_trigger_total` 必须贴近 baseline；
- 固定哨兵 case 不能继续恶化。

---

## 11. 执行路线

### Stage D0：Shadow Graph / Community Dump

目标：

- 不改变任何实际 order；
- 只把以下证据落下来：
  - `anchor_map.json`
  - `block_plan.json`
  - `cut_summary.json`

### Stage D1：`offline_anchor_separator_layout_v1_shadow`

目标：

- 真正跑 community formation + block planning；
- 但最终 `physical_pre_order` 仍回落到 baseline；
- 先验证 shadow 计划是否能解释当前 abnormal cores。

### Stage D2：`offline_anchor_separator_layout_v1`

目标：

- 首次让实际 order 由 anchor-separator layout 产出；
- 不碰 runtime。

### Stage D3：全量 artifact + Stage A static gate

目标：

- 只跑 baseline vs candidate 静态对照；
- 如果不过，立刻止损。

### Stage D4：最小 runtime gate

目标：

- 只有静态 gate 通过时才允许进入。

---

## 12. 首版参数

- `target_top_m = 32`
- `weak_neighbor_top_k = 8`
- `trans_expand_top_n = 4`
- `merge_jaccard = 0.5`
- `microblock_values = 256`
- `mesoblock_values = 1024`
- `macroblock_values = 4096`
- `anchor_band_lines = 4`
- `separator_slack_lines = 2`

首轮固定单点，不做 sweep。

---

## 13. 最终建议

主线下一阶段应正式改为：

- **offline layout rewrite first**
- **runtime changes forbidden**

具体来说：

1. 停止继续扩展 dual-guard selector 路线
2. 把 generator 提升为“社区 + 分块 + 块内顺序”的两阶段/三阶段布局器
3. 先完成 `D0 -> D1` 的 shadow 证据链
4. 只有 shadow 证明社区几何确实可控，才进入真实 candidate

这条路虽然更激进，但比继续叠加局部 selector 更符合我们当前已经观察到的根因，也更符合外部图重排 / 稀疏结构 locality 优化的成熟经验。
