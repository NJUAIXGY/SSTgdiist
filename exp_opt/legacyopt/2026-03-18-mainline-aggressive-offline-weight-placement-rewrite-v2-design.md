# 主线激进转向：Offline Community-Macroblock Weight Placement Rewrite V2

> 日期：2026-03-18  
> 状态：design-only  
> 范围：`snndl` 主线，仅限 `offline generator / artifact layout`  
> 目标：在不修改 runtime 主契约、不引入 `step1` closure 风险的前提下，正式从 `rowband`/`selector` 局部修补转向更激进的 offline 权重排布改写。

---

## 0. 一句话结论

`rowband_stripe_v2` 的负结果已经说明：

- 主线问题不是“再给 second-pass 多一点 `16KB-aware` phase”就能打开；
- 也不是“再给 `_order_by_profile_*` 多叠一层 penalty”就能稳定解决；
- 真正需要改的是 **offline layout 的全局排布单位和块级几何**。

因此，下一阶段应正式从：

- `whole-pre order + second-pass stripe`

切换到：

- **`offline_anchor_separator_layout_v2`**
- 或更准确地说：**community-macroblock 级的 offline weight placement rewrite**

它的核心不是“继续调 next-pre scorer”，而是：

1. 先离线识别高风险 target-neighborhood 社区；
2. 再把这些社区映射到明确的 `16KB macroblock / 32KB superblock` 几何；
3. 最后只在块内做保守的 profile-preserving 排列。

---

## 1. 为什么现在必须转向

### 1.1 已确认的事实

当前可信主线已经确认：

- baseline runtime 是稳定可闭环的；
- `materialization / drain / PE_DONE` 闭环是干净的；
- 主损失来自前端 `HOL / younger-ahead burial`，不是 completion。

同时，本轮最新结论进一步收紧了问题边界：

- `rowband_stripe_v1` 已经明显打破 `8KB row` 级 compaction；
- 但对 `16KB window` 的改善仍然很弱；
- `rowband_stripe_v2` 作为 `band_values=4096` 的最小增强，已经在真实 top cores 上证明：
  - **相对 `v1` 没有新增收益**；
  - weighted replay 指标与 `v1` 完全一致。

这意味着：

- 继续在线性 `rowband/band tweak` 上加细节，已经不是高价值路线；
- 继续在 `selector` 层面改一点 greedy score，也大概率只会得到另一种局部重排，而不是根因修复。

### 1.2 根因不再是“谁先被选中”，而是“谁被放进了同一个几何块”

当前主线的真实根因更接近：

- `current formal profile` 会把活跃 pre 压进很紧的物理局部性；
- `v2_1` 虽然放松了 line 级 compaction，但没有真正打散 row-window 级几何；
- `rowband` 只能在最终 order 上做事后条带化，无法改变：
  - 哪些高风险社区共享同一个 `16KB/32KB` 邻域；
  - 哪些 target-neighborhood 在块级已经彼此挤压。

也就是说，问题已经前移到：

- **offline values layout 的块级归属和社区隔离方式。**

---

## 2. 本阶段的硬约束

以下约束继续冻结，不允许为了推进方案而偷偷放松：

### 2.1 runtime 侧

1. 不改 `prepareGcssVlfIssueQueue_()`
2. 不改 `popNextGcssVlfIssueEntry_()`
3. 不改 `tryRetireEdges_()` 的 `global_inorder` 主契约
4. 不改 `hasWork()` / `shouldDeferScatterCommit_()` / step closure 语义
5. 不碰 `bcsr_gas`

### 2.2 数据语义

1. `(pre_global, post_local) -> weight` 完全不变
2. 不允许 duplicate / missing edge
3. 仍保持 strict validation 语义

### 2.3 读取契约

第一阶段仍然保持：

- `lookup(pre) -> (base, len)`
- `widx = base + pre_rank`

也就是说：

- **首版 aggressive rewrite 仍然受 whole-pre contiguous segment contract 约束**
- 不直接进入 split-pre / multi-chunk runtime contract 变更

这是为了保证：

- 这条路线依然是主线可控的 offline 方案；
- 不会再次把问题升级成 runtime 接口演进。

---

## 3. 三个候选方向与选择

### 3.1 方向 A：继续做更强的 second-pass rowband/band tweak

优点：

- 改动很小
- 可快速迭代

缺点：

- `v2` 负结果已经证明收益趋于饱和；
- 只能改最终顺序的局部条带化；
- 改不了社区在 macroblock 级的碰撞关系。

结论：

- **NO-GO**

### 3.2 方向 B：继续给 `_order_by_profile_*greedy()` 叠新的 HOL penalty

优点：

- 复用现有 scorer
- 侵入小

缺点：

- 已经多轮证明 selector 调参的表达力不够；
- 仍然是“谁排在谁后面”的局部问题；
- 不是“哪些社区被放进同一个物理块”的全局问题。

结论：

- **NO-GO**

### 3.3 方向 C：Community-Macroblock Weight Placement Rewrite

优点：

- 直接作用于块级几何；
- 能显式保护高风险社区；
- 不依赖 runtime 行为改动；
- 可以在 whole-pre contract 内先落第一版。

缺点：

- generator 设计复杂度更高；
- 需要更清晰的 planner / shadow / static gate。

结论：

- **本阶段正式选 C**

---

## 4. 新主线：`offline_anchor_separator_layout_v2`

### 4.1 命名与定位

建议新模式命名为：

- `offline_anchor_separator_layout_v2`

它不是简单继承现有 `v1`，而是把 `v1` 的“社区 + 分隔块”骨架升级成真正的 weight placement rewrite。

### 4.2 与现有 `offline_anchor_separator_layout_v1` 的关系

现有代码已经有 `v1` 骨架，优点是：

- 已经具备 target 社区提取；
- 已经具备 block plan / sidecar / meta 输出；
- 已经证明 whole-pre contract 下可以做社区级布局实验。

但它还不够，主要因为：

1. 社区形成仍然偏“弱邻域收集”，缺少更强的共头部几何信号；
2. block emission 仍然太依赖 baseline order walk；
3. 没有显式的 `16KB macroblock / 32KB superblock` 放置代价；
4. 没有把“高风险社区之间必须拉开”写成强约束；
5. 没有建立 canonical static gate 作为 planner 的第一准入门槛。

所以 `v2` 不是推翻 `v1`，而是：

- **保留现有 code skeleton**
- **重做社区形成、macroblock 规划和准入门槛**

---

## 5. 根因模型：主线为什么会把热点压坏

### 5.1 当前主线的真实坏形态

从现有实验和文档看，坏形态不是“target 本身完全丢了”，而是：

1. target 及其关键弱邻域经常仍然都在；
2. 但它们被排进了同一个高 compaction 的物理邻域；
3. 这种邻域经常对应：
   - 同 line
   - 同 `8KB row`
   - 同 `16KB window`
   - 或相邻极近的 line-group

结果就是：

- 老 head 虽然存在，但前面堆了更多更年轻且同样高局部性的 entry；
- runtime 的 `locality_first` 于是顺理成章地先吃掉那些“更容易发”的年轻项；
- 最终形成文档里观测到的 `vlf_younger_ahead`。

### 5.2 为什么 `rowband` 救不了这个根因

`rowband` 做的是：

- 先接受整个 baseline order；
- 再在固定 group 内做条带化重排。

它能拆的是：

- 已经形成的连续 run

它拆不了的是：

- 哪些高风险社区原本就被分进了同一 macroblock；
- 哪些 separator 根本没被放进去；
- 哪些 filler 为了 line fill 把两个高风险社区重新缝回一起。

所以 `rowband` 适合作为 probe，不适合作为终局。

---

## 6. 设计核心：从“pre 顺序”转向“社区块布局”

### 6.1 排布层级

新方案的布局层级从高到低为：

1. `anchor community`
2. `macroblock` (`4096 values ~= 16KB`)
3. `superblock` (`2 macroblocks ~= 32KB`)
4. `block-local bands`
5. `pre order inside band`

当前主线真正要优化的是前 1-3 层；

过去我们主要只是在调第 5 层。

### 6.2 设计目标

新布局必须同时做到：

1. 把高风险 target-neighborhood 社区尽量收拢在块内
2. 不让两个强冲突社区落进同一个 `16KB/32KB` 邻域
3. 用 separator/filler 吸收 line fill 压力，而不是让高风险社区彼此混编
4. 保留足够 profile locality，避免 memory 侧完全塌掉

---

## 7. 输入数据与派生特征

### 7.1 输入

继续只使用可信 baseline 导出的离线信息：

1. `pre_windows.csv`
2. `offline_layout_profile.csv`
3. `pre_to_pairs`
4. 当前 baseline order / baseline rank

### 7.2 每个 pre 的核心特征

建议固定以下特征：

1. `seg_len(pre)`
2. `profile_freq(pre)`
3. `head_hits(pre)`
4. `head_depth_sum(pre)`
5. `head_depth_avg(pre)`
6. `target_score(pre)`
7. `cohead_mass(pre)`
8. `baseline_rank(pre)`

### 7.3 每对 pre / 社区的边权

建议构建无向图，边权由以下部分线性组合：

- `transition_weight`
- `cohead_weight`
- `weak_neighbor_weight`
- `shared_window_weight`

首版不搞学习参数，采用静态组合即可：

`edge_weight = trans + cohead + 2 * weak + shared_window`

其中最关键的是：

- `cohead_weight`
- `shared_window_weight`

因为这两项更直接对应“是否容易在 HOL 头部彼此挤压”。

---

## 8. Community Planner V2

### 8.1 Seed 提取

仍然从高 `target_score` 的 pre 中选 seed，但不再只看 top-m 排名本身。

首版建议：

1. 先取 `target_score > 0` 的 pre
2. 再按以下顺序排序：
   - `target_score`
   - `head_hits`
   - `cohead_mass`
   - `seg_len`

### 8.2 Community 扩展

每个 seed 的社区扩展对象不再只是 `weak_neighbors`，而是三层：

1. `anchor members`
   - target 本身
   - 高强度 weak neighbors

2. `near members`
   - 高 `cohead_weight`
   - 高频 shared-window members

3. `filler candidates`
   - 与社区有一定 locality 但 head-risk 很低的 pre

### 8.3 社区合并与唯一归属

继续保留：

- overlap merge
- unique membership

但升级规则：

1. 只允许高 `cohead` / 高 `shared_window` 的社区合并
2. 若两个社区 overlap 高但 head-risk pattern 明显不同，则不合并
3. filler candidates 不参与 anchor merge，只参与后续 block fill

这样做的目的是避免：

- 为了图上看起来“重叠很多”，把两个本应隔开的风险团过早合并。

---

## 9. Macroblock / Superblock 放置器

### 9.1 基本单位

固定：

- `macroblock_values = 4096` (`16KB`)
- `superblock = 2 * macroblock = 8192 values` (`32KB`)

理由：

- 当前主问题已经明确在 `16KB window`；
- 但仅约束单个 `16KB` 还不够，必须同时看相邻一对 block。

### 9.2 放置规则

planner 不再按 baseline 顺序一路 emit，而是做显式 block assignment。

每个社区放置时评估以下代价：

1. `IntraCommunityGain`
   - 社区成员留在同一 macroblock / 相邻 macroblocks 的收益

2. `CrossCommunityPenalty`
   - 强冲突社区被放入同一 macroblock 或同一 superblock 的惩罚

3. `AnchorEscapePenalty`
   - target 与关键 weak-neighbor 落入不同 superblock 的惩罚

4. `WindowSpreadGain`
   - 高风险社区之间拉开至少一个 separator block 的收益

5. `BaselineDisruptionPenalty`
   - 与 baseline rank 偏离过大的惩罚

6. `SlackPenalty`
   - block 容量碎片太多的惩罚

首版目标函数可写成：

`PlacementScore = + intra + spread - cross - escape - slack - disruption`

### 9.3 强约束

以下规则建议写成硬规则，而不是软权重：

1. 两个高冲突 anchor communities 不允许落入同一 macroblock
2. 两个高冲突 anchor communities 尽量不允许落入同一 superblock
3. 每个高风险 community 之间至少插入一个 separator/filler block
4. filler 只能填 separator block，不能反向侵入别的高风险 anchor block

---

## 10. Block-Local Emission

### 10.1 每个 anchor block 的内部带

每个 anchor block 内部按三层 band 组织：

1. `anchor band`
   - target + 最关键弱邻域

2. `near band`
   - cohead/shared-window 强，但 head-risk 略低的成员

3. `filler band`
   - 只用于补齐容量的低风险成员

### 10.2 band 内排序

band 内仍然使用保守稳定排序：

1. `target_score / head_hits`
2. `baseline_rank`
3. `profile_freq`
4. `seg_len`
5. `pre id`

目标不是重新创造一个局部 greedy，而是：

- **在块级几何已经受控后，只做确定性、可解释、低风险的局部排列。**

### 10.3 separator block

separator block 只允许承载：

- 低 head-risk
- 与相邻 anchor 社区冲突低
- 但 profile 活跃度还可以的 filler

separator 的作用不是“塞满所有空间”，而是：

- 给强冲突社区之间提供物理缓冲带。

---

## 11. 为什么这条路线比 `rowband_v2` 更有机会

`rowband_v2` 的失败说明：

- 仅在最终 order 内做 `16KB-aware phase`
- 并不会改变高风险社区的 block ownership

而 `community-macroblock rewrite` 真正改变的是：

1. 哪些 pre 被归成一个风险社区
2. 哪个社区占据哪个 `16KB macroblock`
3. 哪些社区必须被 separator 拉开
4. 哪些 filler 只能在 separator 中吸收 slack

也就是说，这条路线第一次把：

- `same_16KB_window_rate`
- `anchor escape`
- `cross-community collision`

直接作为 planner 一级目标，而不是第二级副作用。

---

## 12. 分阶段任务设计

### Stage 0：Canonical Analyzer 固化

目标：

- 把之前 artifact-decode 的 canonical 静态分析脚本恢复成唯一可信口径

产物：

- 固定输入：artifact + profile source
- 固定输出：
  - `same_line_rate`
  - `same_8KB_row_rate`
  - `same_16KB_window_rate`
  - `avg_*_gap`
  - `anchor escape`
  - `cross-block weak-edge ratio`

退出门槛：

- replay / decode 口径统一
- 后续所有 candidate 只认这套静态 gate

### Stage 1：Planner-Only Shadow

目标：

- 不生成新 artifact
- 只在 generator 中新增 `v2_shadow` planner sidecar

需要新增：

- `community_map`
- `macroblock_assignment`
- `separator_plan`
- `planner summary`

退出门槛：

- sidecar 能解释为什么某些社区被拉开或隔离
- top abnormal cores 的社区碰撞关系可视化清楚

### Stage 2：Real Layout Mode

目标：

- 落 `offline_anchor_separator_layout_v2`

代码落点：

- `/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`
- `/home/xgy/remote/sst_dram_si/tools/gcss/test_gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`

退出门槛：

- 单测通过
- 生成 artifact 无 strict regression

### Stage 3：Static Gate

目标：

- 只做 canonical 静态门槛，不跑 runtime

准入条件：

1. `same_16KB_window_rate` 必须优于 `rowband_v1`
2. `avg_16KB_window_gap` 必须优于 `rowband_v1`
3. `same_line_rate` 不能相对 `v2_1` 大幅塌陷
4. `anchor_escape_count / cross_block_weak_edge_weight_ratio` 要实质改善

### Stage 4：Frozen MPI32 Short Gate

目标：

- 只在通过静态 gate 后，做一次可信 short gate

退出门槛：

1. baseline closure 口径稳定完成
2. candidate 不出现 `step1` 卡死
3. 再看 HOL / memory side 是否正向

---

## 13. 验收标准

### 13.1 必须满足

1. 不碰 runtime
2. 不碰 `bcsr_gas`
3. 不出现 closure regression
4. 单测、语法、artifact 生成链路完整

### 13.2 静态上至少满足

相对 `rowband_v1`：

1. `same_16KB_window_rate` 继续下降
2. `avg_16KB_window_gap` 继续上升
3. `anchor_escape_count` 不高于 `v1`

相对 `v2_1`：

1. `same_line_rate` 不允许显著塌陷
2. `same_8KB_row_rate` 可以回撤，但必须换来明确的 `16KB` 改善

---

## 14. 风险与止损

### 14.1 风险

1. whole-pre contract 仍然表达力不足
2. 社区规划太强，导致 line locality 大幅回撤
3. separator/filler 吸收 slack 不够，block 碎片太多

### 14.2 止损条件

如果 `offline_anchor_separator_layout_v2` 在 canonical static gate 上仍然无法稳定优于 `rowband_v1`，则应作出正式结论：

- 当前 **whole-pre contiguous contract** 对主线 HOL 问题的表达力已经不够；
- 后续若还要继续推进，需要单独立项讨论：
  - split-pre / multi-chunk index
  - 或其他更激进的 layout contract 演进

在那之前，不再继续堆叠：

- rowband 小修饰
- greedy penalty 小修饰
- online reorder 小修饰

---

## 15. 推荐立即开始的第一任务

第一任务不是直接写 `v2 real mode`，而是：

- **先完成 Stage 0：canonical analyzer 固化**

理由：

1. `rowband_v2` 这轮已经再次证明，口径一旦混乱，就会误导判断；
2. aggressive rewrite 的风险更高，必须先把唯一可信静态 gate 固化下来；
3. 只有这样，后续 `v2_shadow -> v2_real` 才不会再次走偏。

