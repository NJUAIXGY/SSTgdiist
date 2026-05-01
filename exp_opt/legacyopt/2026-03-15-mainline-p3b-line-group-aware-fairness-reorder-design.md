# Mainline P3-B：GCSS/VLF line-group aware fairness reorder 设计

> 日期：2026-03-15
> 状态：design-only
> 范围：主线 `DRAM-based SNN + GAS + GCSS-GLIDE + STORM + MulticastRouter` 的下一阶段前端排序优化
> 前提：`Task 0-3`、`P0/P1`、`P3-A bounded rescue` 最小候选已经完成并有 formal replay 对照

---

## 0. 一句话结论

当前已经不值得继续围绕 `P3-A issue-stage bounded rescue` 做参数扫点；下一步更应该直接进入：

- `P3-B line-group aware fairness reorder`

而且推荐的不是“完全 age-first 排序”，也不是“继续做更复杂的 issue 时 rescue”，而是一个更稳的中间方案：

- **age-banded line-chunk reorder**

它的核心做法是：

1. 保留当前 `GCSS/VLF` 基于地址的 line locality 主框架；
2. 但不再让整条 queue 直接按全局 `addr` 排到底；
3. 而是先按 retire 注册顺序切成有限大小的 `age band`；
4. 再在每个 `age band` 内按 `line group` 做 locality-first 排序；
5. 最终形成：
   - `age_band -> line_group -> addr -> pre_global -> post_local -> retire_seq`

这样做的目标不是“彻底消灭 locality”，而是：

- 让 older head 不再被跨很多个 band 的 younger line-group 长时间埋住；
- 同时尽量保留 band 内的 line clustering；
- 并继续保持：
  - `global_inorder retire`
  - `same-post deterministic`
  - 当前 pending/direct read contract
  - formal baseline 对照口径

---

## 1. 为什么现在应该直接进入 P3-B

## 1.1 baseline 已经证明问题是深队列顺序冲突，不是轻微 front 抖动

formal baseline `20260315-142734` 已确认：

- `queued_not_issued.hol_cycles = 143221487`
- `vlf_younger_ahead.hol_cycles = 142876530`
- `vlf_younger_ahead / queued_not_issued = 99.759%`

更关键的是，现有 `frontend_ordering` 证据已经足够说明这不是“前方只差几个 younger entry”的轻度 unfairness：

- `older_head_wait.wait_cycles_avg = 61101.316979522184`
- `older_head_wait.wait_cycles_max = 296307`
- `younger_ahead_depth.depth_avg = 575.6298694544164`
- `younger_ahead_depth.depth_max = 2532`

这组数据说明：

- 当前 older head 平均不是被压在前方 1~8 个 younger entry 后面；
- 而是长期被埋在一个很深的 VLF locality-first 队列里；
- 因此仅做小范围 front scan rescue，本质上碰到的只是“队列表层”，不是“队列几何形状”。

## 1.2 P3-A 的 formal candidate 已经说明 issue-stage rescue 不足以解决主矛盾

formal candidate `P3-A s8/w64/d3`：

- `queued_not_issued.hol_cycles`：`143221487 -> 142162131`，仅 `-0.740%`
- `vlf_younger_ahead.hol_cycles`：`142876530 -> 142162067`，仅 `-0.500%`
- `issued_wait_resp.hol_cycles`：`26261557 -> 27470589`，`+4.604%`
- `memctrl_req_total`：完全不变
- `payload_utilization / traffic_amplification`：完全不变

同时：

- `younger_ahead_depth.depth_avg`
  - `575.6298694544164 -> 582.4453438412653`
- `depth_max`
  - 仍是 `2532`

这说明：

1. `P3-A` 能轻微改变 issue 时机；
2. 但它没有改掉 queue build 时的深埋结构；
3. 所以它只是把少量 front-level stall 挪到了 `issued_wait_resp`；
4. 没有把 older head 从深队列压制里系统性解出来。

因此，下一步应该改的不是“front 如何在最后一刻救一下”，而是：

- **queue 一开始是怎么排出来的。**

---

## 2. P3-B 的设计目标与边界

## 2.1 目标

P3-B 的目标不是追求一个抽象上“最公平”的调度器，而是在主线约束下做一个：

- 可解释
- 可回退
- 可 formal replay
- 仍然 locality-aware

的 queue-build-time candidate。

它的具体目标是：

1. 显著降低 `queued_not_issued -> vlf_younger_ahead`；
2. 显著降低 `frontend_ordering.younger_ahead_depth.depth_avg / depth_max`；
3. 不把问题大面积转移到 `issued_wait_resp`；
4. 不明显恶化：
   - `memctrl.req_total`
   - `payload_utilization`
   - `traffic_amplification`

## 2.2 明确不做什么

P3-B v1 不做以下事情：

1. **不改 retire contract**
   - 继续保持 `experimental_retire_policy = global_inorder`
2. **不改 issue callback / response / pending drain 语义**
   - `issueFromEdgesOnce_()`
   - `handleReadResp_()`
   - `drainPendingDirectReads_()`
   都不做行为性改造
3. **不做 per-tick 动态调度器**
   - 不引入运行期 round-robin line scheduler
   - 不引入 DRAM row-state aware policy
4. **不改权重布局格式**
   - 暂不进入更激进的 `weight layout / rank layout` 重写
5. **首轮不与 P3-A 叠加**
   - 为了 attribution 清晰，首轮 `P3-B` candidate 应关闭 bounded rescue

这样做的原因很直接：

- 当前我们要先验证“queue-level 几何重排”本身是否有效；
- 如果一开始就叠加 `P3-A`、release tuning、layout 改写，后续就无法判断哪个因素在生效。

---

## 3. 候选方案对比

## 3.1 方案 A：entry 级 full age-bucket sort

排序键直接改成：

- `age_bucket -> addr -> pre_global -> post_local -> retire_seq`

优点：

- 最直接地限制 younger 跨 band 压 older；
- 实现简单；
- 对 `younger_ahead_depth` 理论上最有效。

缺点：

- 会把一条原本大的 addr-contiguous locality 队列切得很碎；
- band size 如果偏小，会快速打散 line reuse；
- 很容易在第一轮就把 locality 代价打得太重。

判断：

- 这是一个“可能有效，但太硬”的方案；
- 适合作为 backup，不适合作为 `P3-B v1`。

## 3.2 方案 B：line-group aware 的 age-banded line-chunk reorder

核心不是直接按 entry 排，而是：

1. 先保留 baseline 的 `addr` 排序；
2. 从中识别 `line group`；
3. 再按 `age band` 把 line group 切成更小的 `line chunk`；
4. 最终按：
   - `age_band -> line_id -> chunk_inner_order`
   发射。

优点：

- 保留 line-group 语义；
- 公平性不是“完全 age-first”，而是“band 内 locality-first”；
- 比纯 `P3-A` 更能改 queue 几何；
- 比 full age-bucket sort 更保守。

缺点：

- 实现和解释比 `P3-A` 稍复杂；
- 仍然可能带来一定 locality 损失；
- 需要补少量 queue-shape observability，避免收益不可归因。

判断：

- 这是当前最适合主线的折中方案；
- 也是本设计推荐的 `P3-B v1`。

## 3.3 方案 C：运行期 dynamic line-group scheduler

做法类似：

- queue build 仍然保留 locality-first；
- 但 issue 时维护多个 line-group 子队列，再做 age-aware round-robin。

优点：

- 运行期更灵活；
- 可以继续叠加 admission / inflight 信息。

缺点：

- 侵入点从 queue-build 扩散到 issue loop；
- 与 `P3-A` 的边界变模糊；
- 更容易把问题转成复杂时序耦合；
- formal baseline 对照解释性显著变差。

判断：

- 这更像 `P3-B/P3-C` 混合物；
- 当前不推荐作为第一轮实现。

---

## 4. 推荐方案：age-banded line-chunk reorder

## 4.1 关键设计思想

推荐方案的最核心判断是：

- 当前的 locality-first 问题，不在于“line group 不该存在”；
- 而在于“年轻 line group 可以无限跨 band 地压住 older head”。

所以 `P3-B v1` 的正确方向不是消灭 line group，而是：

- **给 line group 加一个 age-bounded outer order。**

具体做法：

1. 按当前逻辑收集本 window 的所有 `GcssVlfEdgeIssueEntry`
   - `registerEdgeRetire_()` 调用顺序不变
   - `retire_seq` 分配不变
2. 为每条 entry 记录一个本 window 内的 `local_age_rank`
   - 即 entry 在原始 retire 注册顺序中的位置
3. 计算：
   - `line_id = addr / line_size`
   - `age_band = local_age_rank / fair_band_size`
4. 先做一次 baseline 一致的 `addr` 排序
5. 但在 flatten 时，不是把整个排序后的数组直接推入 queue，而是拆成：
   - `(age_band, line_id)` 粒度的 `line chunk`
6. 最终按：
   - `age_band`
   - `line_id`
   - `chunk_min_retire_seq`
   稳定输出

这会形成一个新的 queue 语义：

- younger entry 仍然可以在同一个 age band 内凭 locality 排在 older 前面；
- 但它不能跨很多个 band，无限制地把 older head 永久埋住。

## 4.2 为什么要用 line-chunk，而不是 whole-line-group promotion

这里有一个很关键的细节：

如果我们只做：

- `whole_line_group.min_retire_seq -> line_id`

那么只要一个 line group 里混入一个很老的 entry，整组较新的 entry 就可能被一同提前，形成另一种“年轻批量前插”。

因此推荐做的是：

- **line group 先识别**
- **再按 age band 切 chunk**

也就是：

- 同一条 line 上、但属于不同 age band 的 entry，不应该永远绑在一个 group 里一起移动；
- 应该拆成多个 chunk，分别参与各自 band 内的 locality 排序。

这样可以避免：

1. older edge 拖着一大串 much-younger edge 一起前插；
2. 新的排序策略把 unfairness 从“older 被压住”变成“younger 被过度抬升”。

## 4.3 算法骨架

推荐在 `prepareGcssVlfIssueQueue_()` 内把 queue-build 显式拆成三步：

### Step 1：保持当前 entry 收集逻辑不变

保留当前：

- `nextPrevEdge()`
- `registerEdgeRetire_()`
- `lookupGcssPreBaseLen_()`
- `edge_pre_rank_prev_`
- `addr` 计算

只在 `GcssVlfEdgeIssueEntry` 上多记一个：

- `local_age_rank`

它等于该 entry 在 `edges` 向量中的 push 顺序。

### Step 2：先构造 baseline-locality view

对 `edges` 做与当前一致的排序：

- `addr -> pre_global -> post_local -> retire_seq`

这样可以继续把：

- 同 line
- 同 pre
- 临近 addr

的 entry 放在一起，作为“原始 locality 视图”。

### Step 3：在 locality view 上切 line-chunk 并按 age band 输出

对排序后的数组线性扫描：

1. 以 `line_id` 为第一层边界；
2. 以 `age_band` 为第二层边界；
3. 把连续且 `(line_id, age_band)` 相同的 entry 收成一个 chunk。

每个 chunk 记录：

- `age_band`
- `line_id`
- `chunk_min_retire_seq`
- `chunk_max_retire_seq`
- `entries`

最后对 chunk 做稳定排序：

- `age_band`
- `line_id`
- `chunk_min_retire_seq`

再把 chunk flatten 回 `gcss_vlf_issue_queue_`。

这个过程的本质是：

- band 间公平
- band 内 locality

而不是：

- 全局 age-first
或：
- 全局 addr-first

## 4.4 一个直观例子

假设：

- baseline 的全局 addr 排序把 older head 所在 line 放在很后面；
- 它前面跨了很多条 younger line；
- 当前平均 `younger_ahead_depth` 已经是 `575.63`。

如果 `fair_band_size = 256`：

- older head 最多只会被同 band 的 locality 队列压住；
- 但来自更年轻 band 的 line-chunk 不能继续跨 band 抢到它前面；
- 因而 queue burial 的长尾会被硬性截断一大截。

这里的收益不一定表现为：

- mem 请求变少

更可能先表现为：

- `younger_ahead_depth` 明显下降
- `older_head_wait` 明显下降
- `queued_not_issued` 明显下降

然后才看它是否能进一步改善系统总收益。

---

## 5. 代码落点与接口设计

## 5.1 核心行为改动只放在 `prepareGcssVlfIssueQueue_()`

推荐把 `P3-B v1` 的行为改动严格限制在：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`

具体落点：

1. `GcssVlfEdgeIssueEntry`
   - 新增 `local_age_rank`
   - 可选新增 `line_id_cached`
2. `prepareGcssVlfIssueQueue_()`
   - 改为 policy dispatch
3. 新增 helper
   - `buildGcssVlfIssueQueueLocalityFirst_(...)`
   - `buildGcssVlfIssueQueueBandedLineFair_(...)`
4. `issueFromEdgesOnce_()`
   - 不改行为
5. `popNextGcssVlfIssueEntry_()`
   - 第一轮建议不叠加 rescue
   - 即 `P3-B` candidate 运行时应关闭 `bounded_rescue`

这样可以把风险控制在：

- queue formation

而不是扩散到：

- runtime issue loop
- pending drain
- retire logic

## 5.2 参数面建议

推荐新增两个参数就够：

1. `experimental_gcss_vlf_queue_policy`
   - 类型：`string`
   - 取值：
     - `locality_first`（默认）
     - `banded_line_fair`
2. `experimental_gcss_vlf_fair_band_size`
   - 类型：`uint32`
   - 含义：本 window 内按 retire 注册顺序切分 age band 的 entry 数
   - 默认建议：`256`

为什么不继续堆更多参数：

- 当前还在 first candidate 阶段；
- 需要的是一个能明确回答“queue geometry 改了有没有用”的政策；
- 不是一开始就把调参面铺得很宽。

## 5.3 为什么推荐 `band_size = 256` 作为首发口径

当前 baseline：

- `younger_ahead_depth.depth_avg = 575.63`
- `depth_max = 2532`

如果一上来把 band 做到很小，比如 `32` 或 `64`：

- 公平性会更强；
- 但 locality 代价也更可能过猛。

`256` 的意义在于：

- 它足够小，能截掉当前平均 `575` 的跨 band 长尾；
- 又不至于像极小 band 那样立刻把 queue 切得太碎。

因此推荐的正式 sweep 顺序是：

1. `band_size = 256`
2. `band_size = 128`
3. `band_size = 512`

而不是反过来。

---

## 6. P3-B 需要补的最小 observability

## 6.1 为什么 `P3-B` 不能只看旧指标

只看：

- `queued_not_issued`
- `vlf_younger_ahead`
- `issued_wait_resp`

还不够。

因为 `P3-B` 的核心主张是：

- **queue geometry 被改了。**

如果没有 queue-shape 证据，后面即使结果变化，我们也不能确定到底是：

- queue burial 真变浅了；
- 还是 timing 偶然变化了。

## 6.2 推荐新增/补齐的 queue-shape 指标

优先推荐两类：

### A. 直接把已有 internal counter 对外导出

当前 `WeightMemorySubsystem` 已有但尚未进入 summary 的内部量：

- `gcss_vlf_issue_prepare_total_`
- `gcss_vlf_issue_edges_total_`
- `gcss_vlf_issue_reorder_trigger_total_`
- `gcss_vlf_issue_line_groups_total_`

`P3-B` 建议把这些进入：

- PE/core CSV
- `frontend_ordering`

至少能回答：

- queue 一共 build 了多少次
- 每次多少 edges
- 每次多少 line groups
- reorder 是否真的触发

### B. 新增 queue fairness 直接证据

推荐新增：

1. `gcss_vlf_retire_rank_bury_total / samples / max`
   - `bury = max(0, issue_pos - local_age_rank)`
2. `gcss_vlf_retire_rank_promotion_total / samples / max`
   - `promotion = max(0, local_age_rank - issue_pos)`
3. `gcss_vlf_issue_band_chunks_total`
4. `gcss_vlf_issue_bands_total`

这样可以直接回答：

- older edge 平均被埋多深
- 新策略有没有显著减少 bury 长尾
- band/chunk 粒度是否符合预期

## 6.3 summary 侧建议

在 `compute_essential_summary_mesh.py` 中建议新增：

- `frontend_ordering.queue_shape`
  - `vlf_issue_prepare_total`
  - `vlf_issue_edges_total`
  - `vlf_issue_line_groups_total`
  - `vlf_issue_band_chunks_total`
  - `vlf_issue_bands_total`
  - `retire_rank_bury_avg`
  - `retire_rank_bury_max`
  - `retire_rank_promotion_avg`
  - `retire_rank_promotion_max`

注意：

- 这些字段不需要进入 validator 的硬性 contract；
- 但需要在 `P3-B` 对照分析里固定引用。

---

## 7. 成功标准、止损标准与 formal replay 方案

## 7.1 第一轮 formal candidate 推荐口径

第一轮不要叠加其他实验项，直接做：

- `experimental_retire_policy = global_inorder`
- `experimental_gcss_vlf_queue_policy = banded_line_fair`
- `experimental_gcss_vlf_fair_band_size = 256`
- `experimental_gcss_vlf_bounded_rescue_enable = 0`

其他环境保持与 formal baseline 完全一致。

## 7.2 推荐对照矩阵

最小矩阵：

1. baseline
   - `locality_first`
2. candidate-A
   - `banded_line_fair, band=256`
3. candidate-B
   - `banded_line_fair, band=128`
4. candidate-C
   - `banded_line_fair, band=512`

如果第一轮 `256` 已经明显恶化 locality，则暂停，不进入 `128`。

## 7.3 成功标准

`P3-B v1` 的成功不要求一步到位，但至少要满足：

1. `queued_not_issued.hol_cycles` 下降显著
   - 目标：`<= -5%`
2. `vlf_younger_ahead.hol_cycles` 下降显著
   - 目标：`<= -5%`
3. `frontend_ordering.younger_ahead_depth.depth_avg`
   - 目标：`<= -25%`
4. `issued_wait_resp.hol_cycles`
   - 守门：`>= +2%` 就要高度警惕
5. `memctrl_req_total`
   - 守门：相对 baseline 不应明显上升
6. `gas.memctrl_payload_utilization`
   - 不应显著下降

这套门槛的目的不是制造论文式夸张收益，而是确保：

- 它至少比 `P3-A` 那种“QNI 小降、wait_resp 回填”的局面更好。

## 7.4 硬性止损标准

出现以下任一情况就应停止继续 sweep：

1. `issued_wait_resp.hol_cycles` 上升超过 `5%`
2. `memctrl_req_total` 上升超过 `2%`
3. `payload_utilization` 明显下降
4. `gcss_phase_mix` 总 `hol_cycles` 不降反升
5. `younger_ahead_depth.depth_avg` 没降，甚至继续上升

这说明：

- reorder 只是把阻塞位置换了；
- 并没有解决主矛盾。

---

## 8. 实现分阶段建议

## 8.1 Stage 0：参数与 queue-build refactor

目标：

- 先把 queue build 从“单一 locality-first 排序”拆成可切 policy 的 helper；
- 但行为上默认仍是 baseline。

最小改动：

- `WeightMemorySubsystem.h/.cc`
- `SnnPESubComponent.h/.cc`
- `mesh_template/{legacy_defaults.py,spec.py,config.py,runtime.py,build.py}`

## 8.2 Stage 1：落 `banded_line_fair`

目标：

- 只让 `prepareGcssVlfIssueQueue_()` 支持 `banded_line_fair`；
- 不动 issue/retire。

最小行为验证：

- queue build 完成
- compile 通过
- plumbing 测试通过

## 8.3 Stage 2：补 queue-shape observability

目标：

- 把 `P3-B` 的行为变化变成 summary 可见证据；
- 避免只靠最终 HOL 指标猜测。

## 8.4 Stage 3：formal replay

目标：

- 跑 `256`
- 再决定是否继续 `128 / 512`

## 8.5 Stage 4：是否叠加 P3-A

只有在满足以下条件时，才建议做：

- `P3-B` 已经明确降低 `depth_avg`
- 但仍有少量 older-head tail 残留

这时才考虑：

- `P3-B + bounded rescue`

否则不建议叠加。

---

## 9. 为什么这一步仍然优先于“更激进的权重排布重写”

更激进的方向当然存在，比如：

- 直接改 `GCSS/VLF` 的 rank/权重布局
- 让 older-first 与 line locality 在存储布局层面就更一致

但在当前阶段，它还不是第一优先级，原因是：

1. 布局改写会同时改：
   - loader/index 口径
   - offline weight 生成链路
   - formal baseline 比较面
2. 一旦收益出现，很难区分：
   - 是 queue policy 生效
   - 还是数据布局本身变了
3. 当前我们还没有先把“仅改 queue geometry 能不能解决主问题”这个问题回答清楚

因此更合理的推进顺序是：

1. 先做 `P3-B banded_line_fair`
2. 若仍然收益不足，再进入：
   - weight/rank layout redesign

---

## 10. 最终建议

基于目前所有 formal 证据，下一步主线应该这样推进：

1. **停止继续优先做 `P3-A` 参数 sweep**
   - 因为它已经证明自己更像 probe，而不是主收益候选
2. **直接进入 `P3-B`**
   - 但采用保守的 `age-banded line-chunk reorder`
3. **首轮只改 queue-build，不改其他 contract**
4. **首轮先跑 `band_size=256`**
5. **必须把 queue-shape observability 一起补上**

如果这条路有效，后面再决定是：

- 继续压 band size
- 叠加 `P3-A`
- 还是进入更激进的权重排布重写

如果这条路无效，那也能更干净地证明：

- 问题不只是 queue build 排序；
- 届时再转向更激进的 layout 级重写，证据也会更扎实。
