# PULSE-FCS：面向 PE 内 core frontier 通信与共享服务的下一阶段设计（v2）

> 日期：2026-03-18  
> 状态：design-only v2  
> 工作名：`PULSE-FCS` = `PE-internal Frontier-Coupled Shared Service`  
> v2 核心收敛：从“frontier observe / metadata seed”推进为一条更硬的主线  
> **`PE-scoped Metadata-Frontier Barrier + Owner-First Shared Metadata Service + Exact Demand Join`**  
> 目标：在当前 `PULSE Stage-A shared-line actual` 已经成立、而 `F2 shared metadata seeding` 仍未进入收益空间的前提下，重新定义下一阶段真正能在 `PE` 内打开收益空间的 `core-level` 主线，并把它收敛成面向 `ISCA/ASPLOS` 叙事也站得住的设计骨架。

## 0. 一句话结论

当前最值得推进的 PE 内优化，已经不是：

- 继续扩大 ingress；
- 继续在当前触发点上调 metadata seed 的预算/阈值；
- 继续做“更早一点的 line seed”这种局部 patch。

fresh 数据已经说明，下一阶段真正该做的是：

- **把多个 core 的 head metadata frontier，在 exact demand issue 之前先汇聚成一个 PE-scoped barrier；**
- **只对更早、更共享、比 exact value line 更轻的 metadata 对象做 owner-first seed；**
- **让 exact demand 只负责 join / consume，不负责决定 seed 是否启动；**
- **architectural commit 仍完全保持原有 exact contract。**

因此，`v2` 把主线正式收敛为：

- **`metadata-frontier barrier -> owner-first metadata seed -> exact demand join -> exact retire`**

这条线的关键创新点不是“又做一层 shared line”，而是：

- **第一次把 PE 内多个 core 的 frontier communication，提升为一个显式的 pre-issue coordination contract。**

---

## 1. v2 为什么必须重写：fresh 数据已经把问题定义得很清楚

### 1.1 已经成立的事实

我们现在有三条已经被 fresh 实验反复确认的事实：

1. `shared ingress actual path` 不会自己赢。  
   它能真实接管 admission，但不会减少真实 memory/service cardinality。

2. `Stage-A shared-line actual` 已经证明：  
   **PE 内共享真正能赢的，是 exact service work compression。**

3. `metadata frontier observe` 已经证明：  
   **跨 core 的更早 metadata overlap 是非常强的。**

代表性数据：

- `pulse_metadata_frontier_base_overlap_ratio = 0.9408203125`
- `pulse_metadata_frontier_base_avg_peer_overlap = 9.08386962839942`
- `pulse_metadata_frontier_band_overlap_ratio = 0.95`
- `pulse_metadata_frontier_band_avg_peer_overlap = 10.0`

这说明：

- PE 内多个 core 的 head 附近，确实不是“彼此完全独立”；
- 真正共享价值出现的位置，比 exact value line demand 更早；
- `idx2 / rowidx / pre-band / pre-base` 这种 metadata frontier，才是应该被消费的共享机会。

### 1.2 F2 actual 进一步把“为什么还没赢”讲明白了

`F2 shared metadata seeding` 的 fresh 闭环结果更关键，因为它把“没有收益”的原因从猜测变成了证据：

- baseline / candidate 都 `fail=0 warn=0 strict=0`
- `model.sim_time_actual_ns: 224813 -> 224813`
- `memory.memory_requests: 150907 -> 150907`
- `memhierarchy.memctrl.req_total: 150907 -> 150907`
- `pulse_shared_service_hits_total: 612972 -> 612972`
- `pulse_metadata_seed_candidates_total: 0 -> 464`
- `pulse_metadata_seed_prefetch_owner_total: 0 -> 0`
- `pulse_metadata_seed_resident_hits_total: 0 -> 0`
- `pulse_metadata_seed_resident_lines_peak: 0 -> 93`
- `pulse_ready_fanout_total: 763879 -> 764343`

这组结果的含义非常直接：

- seed 路径确实被触发了；
- registry / residency 也确实被占用了；
- 但它**没有一次**成为真正的 prefetch owner；
- 它只是在 demand 已经决定 issue 之后，作为一个 late join dummy waiter 搭上了已有 shared-line service。

换句话说，当前 F2 的真实语义不是：

- `early seed`

而是：

- **`late-join residency capture`**

这就是 `v2` 必须改主线的根本原因。

---

## 2. 根因诊断：为什么当前 F2 设计从结构上就很难进入收益空间

### 2.1 触发点太晚：seed 与 exact demand 同周期竞争

当前 F2 的启动点在：

- `prepareGcssVlfIssueQueue_()`

这一步虽然发生在 `BeginApply` 阶段，但它本质上仍然属于：

- **per-core exact issue 前的一次局部整理**

而不是：

- **PE 级、跨 core、早于 issue 的独立协调阶段**

这意味着：

1. core 自己先构建 exact issue queue；  
2. frontier / metadata seed 只是在这个队列已经形成以后顺手观察；  
3. exact demand 很快就沿原路径发起 `PulseSharedLineService::joinOrRegister(...)`；  
4. 此时 seed 若再试图启动，只会发现 owner 已经存在，于是变成 join。  

因此，当前 F2 即使完全没有实现 bug，也天然倾向于：

- `join-only`

而不是：

- `owner-first`

### 2.2 共享对象仍然太晚：value line 不是最该提前 seed 的对象

`metadata frontier observe` 已经证明强 overlap 出现在：

- `pre_base`
- `pre_band`

这些对象的共同特点是：

- 比 exact value line 更早；
- fanout 更大；
- 跨 core 稳定性更强；
- service 成本通常更轻；
- 能够在 exact demand 真正形成之前，就被多个 core 共同“知道”。

而 exact value line 本身的问题是：

- 它太接近最终消费点；
- 它的 owner 窗口极短；
- 一旦 exact issue path已经开始流动，再去争 owner 基本来不及；
- 轻微 timing 偏差都会把 seed 降格成 dummy join。

因此，下一阶段要优先 seed 的不该是：

- `value line`

而应是：

- `idx2`
- `rowidx`
- `pre-band`
- 必要时才是更下游的 exact line hint / residency handle

### 2.3 当前 F2 缺少一个显式的 pre-issue coordination contract

F2 的根本缺口不是某个 if 条件，也不是 budget 太小，而是：

- **没有一个结构化的“谁先发布 frontier、谁等 barrier、谁被选为 owner”的契约。**

现在的路径更像：

- 每个 core 仍按私有时间推进；
- PE 侧只是观察到一些 overlap；
- 然后试图在既有私有 issue 之间“挤进去”做一点 seed。

这条线的问题是：

- 共享是 opportunistic 的；
- 不是 contract-driven 的；
- 因而很难系统性地产生 owner-first gain。

---

## 3. v2 的核心改写：把主线改成 Metadata-Frontier Barrier

### 3.1 新主线定义

`v2` 推荐的下一阶段主线记为：

- **`PULSE-MFB` = `PE-scoped Metadata-Frontier Barrier`**

它仍属于 `PULSE-FCS`，但把“frontier communication”的结构收紧为：

- **一个显式的、短窗口的、只作用于 service plane 的 barrier**

一句话结构可写成：

- **`per-core frontier export -> PE barrier collect -> owner-first metadata seed -> exact demand join -> exact retire`**

与当前 F2 的本质区别在于：

- 当前 F2：seed 发生在 exact issue 流开始之后；
- `PULSE-MFB`：seed 决策发生在 exact issue 真正起跑之前。

### 3.2 Barrier 的边界

`Metadata-Frontier Barrier` 不是一个新的 global retire，也不是一个 centralized issue scoreboard。

它只做三件事：

1. 收集各 core 的前 `H` 个 metadata frontier 对象；
2. 判断哪些对象值得 owner-first seed；
3. 在 exact demand 起跑前，把少量 seed owner 发出去。

它**不做**：

- commit 顺序改写；
- payload forwarding；
- architectural ownership 转移；
- 无界窗口依赖追踪。

因此它保留了当前方案最重要的安全边界：

- **共享发生在 service plane，不发生在 commit plane。**

---

## 4. PULSE-MFB 的微结构

`PULSE-MFB` 把下一阶段 `PE` 内路径拆成 5 个结构块。

### 4.1 Core Frontier Export Buffer（CFEB）

每个 core 在进入 exact issue 之前，先导出：

- 当前 `window_seq`
- `top-H` 唯一 metadata frontier
- 每个对象的：
  - `kind`
  - `object_id`
  - `top_h_rank`
  - `local_depth`
  - `head_distance`
  - `estimated_service_cost`
  - `post_domain_hint`

`kind` 的第一批只允许：

- `pre_band`
- `idx2`
- `rowidx`

明确**不允许**：

- exact value line

理由很简单：

- 第一批目标是打开 owner-first 机会，不是继续在太晚的对象上碰运气。

### 4.2 PE Metadata Barrier Table（MBT）

PE 内维护一个小而有界的 barrier table，key 为：

- `(scope_id, window_seq, metadata_kind, object_id)`

每个 entry 保存：

- `consumer_bitmap`
- `consumer_count`
- `earliest_rank`
- `min_head_distance`
- `owner_core_id`
- `owner_launched`
- `ready_state`
- `resident_state`
- `seed_epoch`

它的作用不是做大一统调度，而是回答：

1. 这个 metadata object 是否跨 core 重叠；  
2. 它是否足够靠近 head；  
3. 现在是否值得发一个 owner-first seed；  
4. 后续 exact demand 应该直接命中 resident、join inflight，还是走原路径。  

### 4.3 Owner-First Metadata Seeder（OFMS）

这是 `v2` 真正新增的核心结构。

它不再把“发现 overlap”和“尝试 seed”绑定在 per-core queue prepare 里，而是显式做：

- owner 选举；
- seed admission；
- seed launch。

owner 选举规则建议固定为：

1. `consumer_count >= 2`
2. `min_head_distance >= D_min`
3. `earliest_rank <= R_max`
4. `estimated_service_cost <= C_max`
5. `seed_budget_window` 允许
6. tie-break：`earliest_rank -> lower core_id -> smaller object_id`

这会把现在的 opportunistic seed 改成：

- **contracted owner-first seed**

### 4.4 Metadata Resident / Inflight Store（MRIS）

MRIS 是一个 PE-scoped 的轻量 resident + inflight 存储，负责：

- 记录某个 metadata object 是否：
  - `resident`
  - `inflight`
  - `failed`
- 为 exact demand 提供：
  - `hit resident`
  - `join inflight`
  - `fallback`

第一批 residency 对象建议不是 float line bytes，而是：

- `idx2 decoded span`
- `rowidx span`
- `pre-band -> candidate line set / block set`

这样做的好处是：

- 对象更轻；
- owner 窗口更早；
- 更容易在多个 core demand 真正发起前准备好。

### 4.5 Exact Demand Join Path（EDJ）

exact demand 路径在 `v2` 中仍然是最终真路径，但它不再决定“seed 是否存在”，而只决定：

1. 命中 `resident`：直接消费；  
2. 命中 `inflight`：join 等待；  
3. barrier 没有该对象：走原 exact path；  
4. barrier 有对象但 owner 未启动：按 fallback 原路 issue。  

这让 demand path 重新变得被动且简洁：

- **它只消费 barrier 结果，不主动兼任 barrier。**

---

## 5. 为什么 v2 更可能真正进入收益空间

### 5.1 它第一次把 owner-first 作为显式设计目标

当前 F2 的失败不是“共享不存在”，而是：

- **共享发生得太晚**

`v2` 的不同点在于，它不再用“有没有 overlap”作为唯一目标，而是明确把下面这个指标作为第一 gate：

- **`owner_first_rate`**

只有当一个设计能让：

- seed 真正成为 owner；
- exact demand 后续去 join / hit resident；

它才有资格进入收益空间。

### 5.2 它把共享对象前移到了更轻、更稳定的层次

与 exact value line 相比：

- `pre_band`
- `idx2`
- `rowidx`

具有更高的跨 core 稳定性和更长的 lead time。

这意味着：

- seed 成为 owner 的概率更高；
- resident 更可能在 demand 前 ready；
- 就算性能没立刻提升，也更容易先看到：
  - `resident_hits`
  - `join_before_issue`
  - `metadata_path_duplication` 下降

### 5.3 它不破坏当前最强的 correctness story

`PULSE-MFB` 明确保留三条契约：

1. metadata seed completion 不等于 logical retire；  
2. exact demand consume 顺序仍由原 per-core / per-domain 逻辑决定；  
3. architectural visibility 只由原 commit plane 决定。  

因此它的论文叙事仍然是：

- **更早共享 service**
- **不动 architectural exactness**

这点对顶会叙事非常重要。

---

## 6. Correctness Contract

这是 `v2` 必须单列出来的部分，否则设计会显得像一堆启发式技巧。

### 6.1 Architectural visibility point

对任意一个 metadata seed：

- `seed launched`
- `seed resident`
- `seed inflight complete`

都**不构成** architectural visibility。

它们只表示：

- service plane 的某个对象已准备好供 exact demand 消费。

### 6.2 Exact demand is still the semantic consumer

即使某个 metadata object 已 resident：

- 真正把它绑定到某个 edge / retire_seq 的，仍是 exact demand path；
- barrier / seed 只能改变准备时机，不能改变最终语义归属。

### 6.3 Late split / replay 不影响 commit contract

若某个 barrier object：

- 预测 overlap 成立；
- 但后续 exact demand 并未使用；
- 或 runtime 需要 replay / fallback；

则只允许发生：

- resident drop
- inflight fail
- demand fallback

不允许发生：

- commit order 改写
- retire ownership 改写
- architectural state 直接写回

---

## 7. Offline / Runtime Interface

`v2` 需要把 offline 和 runtime 的职责分得更清楚。

### 7.1 Offline 必须提供的静态字段

第一批建议由 layout / compiler 静态提供：

- `pre_band`
- `idx2 span bound`
- `rowidx span bound`
- `bank_color`
- `segment_safe`
- `shared_eligibility`

这些字段的作用是：

- 让 runtime 不必在热路径里重新推断对象边界；
- 让 barrier 的 object 粒度明确且稳定。

### 7.2 Runtime 动态补全的字段

runtime 只负责窗口内真实观测到的：

- `consumer_bitmap`
- `consumer_count`
- `earliest_rank`
- `head_distance`
- `join_before_issue`
- `resident_hit`
- `fallback`

这条边界非常关键，因为它避免把 barrier 做成一个：

- 无界推断器

而是把它固定成：

- **有静态对象边界、只做动态聚合与仲裁的控制平面。**

---

## 8. 第一批真正值得做的实现切片

`v2` 不建议直接再次进入“metadata line actual seed v2”，而应按下面的顺序切片。

### C0：Barrier Observe

新增 observe-only 指标：

- `pulse_mfb_objects_total`
- `pulse_mfb_overlap_objects_total`
- `pulse_mfb_owner_eligible_total`
- `pulse_mfb_min_head_distance_avg`
- `pulse_mfb_earliest_rank_avg`

目标不是性能，而是回答：

- 当前哪些 metadata object 真有 owner-first 窗口。

### C1：Join-Only / Owner-First 区分

在当前 F2 路径上先补两个必须的诊断量：

- `pulse_metadata_seed_join_only_total`
- `pulse_metadata_seed_owner_already_exists_total`

如果这两个值长期接近 `candidates_total`，就说明：

- 当前触发点结构上太晚，应停止在该点继续 actual patch。

### C2：pre-band Owner-First Seed

第一批 actual 只对：

- `pre_band`

发 owner-first seed。

理由：

- 最轻；
- overlap 最稳定；
- 对后续多个 exact line 可能有扩散收益；
- 更容易先证明 barrier 有真实作用。

### C3：idx2 / rowidx Owner-First Seed

若 `pre_band` 能证明 owner-first 存在，再进入：

- `idx2`
- `rowidx`

这里的目标不是直接减少 float line request，而是减少：

- per-core metadata warmup 重复；
- head-side metadata stall；
- demand side cold-start latency。

### C4：Conditional Value-Line Promotion

只有当前三步都成立，并且：

- `owner_first_rate` 非零；
- `resident_hits_total` 非零；
- `metadata_path_duplication` 真下降；

才允许把 exact value line 重新拉回 actual seed 候选。

---

## 9. 评估指标与正式 gate

下一阶段不能再只看：

- `sim_time_actual_ns`
- `memory_requests`

因为这些已经是太后验的结果。

必须新增以下指标。

### 9.1 Owner-first 必须量化

- `pulse_mfb_owner_eligible_total`
- `pulse_mfb_owner_launched_total`
- `pulse_mfb_owner_first_rate`
- `pulse_metadata_seed_join_only_total`
- `pulse_metadata_seed_owner_already_exists_total`

如果 `owner_first_rate == 0`，就不能宣称进入了真正的 seed phase。

### 9.2 Lead-time 必须量化

- `pulse_mfb_head_distance_avg`
- `pulse_mfb_head_distance_p90`
- `pulse_mfb_seed_to_first_demand_cycles_avg`
- `pulse_mfb_seed_ready_before_demand_total`

这组数据回答的是：

- seed 到底是不是足够早。

### 9.3 Usefulness 必须量化

- `pulse_metadata_seed_resident_hits_total`
- `pulse_metadata_seed_useful_total`
- `pulse_metadata_seed_usefulness_ratio`
- `pulse_metadata_seed_avg_hits_per_useful_seed`

如果 `resident_hits_total == 0`，那就说明：

- residency 只是结构存在，并未进入服务路径。

### 9.4 Correctness overhead 仍必须同步呈现

- `fail`
- `warn`
- `strict`
- `late_split_rate`
- `fallback_rate`
- `barrier_occupancy_peak`

这样论文才能同时证明：

- 收益是真实的；
- correctness contract 没被偷偷放松。

---

## 10. 论文 novelty carve-out

要面向 `ISCA/ASPLOS`，必须把 novelty 边界讲得更尖锐。

`v2` 的主张不应写成：

- “我们做了 PE 内共享”

而应写成：

- **已有 SNN / neuromorphic 系统大多在 router / core / tile 层消费 locality，或者把内存与事件控制绑定在较粗粒度的 core/tile 单元上；**
- **我们的不同点是：在一个 PE 内，把多个 core 的 metadata frontier 收敛成一个显式 pre-issue barrier，并在 exact commit 不变的前提下，把 owner-first shared service 下推到 metadata object 层。**

更具体地说：

1. 现有系统往往强调：
   - event-driven execution
   - local SRAM / synapse memory
   - NoC / router delivery
   - core/tile 级自治

2. 我们强调的是：
   - **PE 内、跨 core、pre-issue、metadata-first**
   - **owner-first 而非 late-join**
   - **exact service sharing 与 exact commit 分离**

这就是 `v2` 真正的 novelty carve-out。

---

## 11. Research Anchors

下面这些论文不是为了“照着做”，而是为了把 `v2` 的新主线放到更可信的研究脉络里。

### 11.1 Loihi：manycore local memory + event-driven routing

- Mike Davies et al., *Loihi: A Neuromorphic Manycore Processor with On-Chip Learning*, IEEE Micro 2018  
- 链接：https://redwood.berkeley.edu/wp-content/uploads/2021/08/2021-08-30-REDWOOD-Loihi-IEEE-Micro-2018.pdf

启发：

- neuromorphic manycore 的价值来自 local memory 与 event routing 的紧耦合；  
- 但它没有回答 PE 内多个 core 如何在 exact demand 之前做 metadata-frontier barrier。

### 11.2 Tianjic：heterogeneous core array + local communication substrate

- Jing Pei et al., *Towards artificial general intelligence with hybrid Tianjic chip architecture*, Nature 2019  
- 链接：https://www.nature.com/articles/s41586-019-1424-8

启发：

- heterogeneous core array 与局部通信是 SNN/ANN 混合芯片的重要方向；  
- 但它的共享边界仍主要在 core/cluster 粒度，而不是 PE 内 frontier contract。

### 11.3 SpiNNaker2：control/data 分离与大规模 event-based 组合

- Christian M. Mayr et al., *SpiNNaker2: A Large-Scale Neuromorphic System for Event-Based and Asynchronous Machine Learning*, arXiv 2024  
- 链接：https://doi.org/10.48550/arXiv.2401.04491

启发：

- 显式区分控制与计算资源有助于扩展 event-driven 系统；  
- `PULSE-MFB` 在 PE 内做的，正是一个更细粒度的 control-plane / exact-demand plane 分离。

### 11.4 MENAGE：memory-based event control

- Xunzhao Yin et al., *MENAGE: An Efficient Memory-based Control Technique Manages Events in each Layer for Spiking Neural Network Accelerator*, arXiv 2024  
- 链接：https://arxiv.org/abs/2402.15083

启发：

- event sparsity 的价值，很多时候不是算子本身，而是更早的 memory/control handling；  
- 这与 `v2` 从 value line 后退到 `idx2 / rowidx / pre-band` 的方向高度一致。

### 11.5 NeuroScale：local synchronization + deterministic timing

- Juncheng Bian et al., *A deterministic neuromorphic architecture leveraging local synchronization for efficient complex cognitive tasks*, Nature Communications 2025  
- 链接：https://www.nature.com/articles/s41467-025-65268-z

启发：

- 在不放弃确定性的前提下，引入 local synchronization 是成立的；  
- `PULSE-MFB` 则把这种“局部同步”的思想下推到 PE 内 service plane，同时保留 exact commit plane 不变。

---

## 12. 最终收敛

如果用一句话总结 `v2`：

- **当前 F2 失败，不是因为 metadata overlap 不存在，也不是因为实现不够仔细，而是因为我们还没有给“更早共享”一个真正的 pre-issue contract。**

因此，下一阶段最值得推进的设计，不应再写成：

- `shared metadata seeding v2`

而应写成：

- **`PE-scoped Metadata-Frontier Barrier with Owner-First Shared Metadata Service`**

只有先把：

- `owner-first`
- `lead-time`
- `resident-hit`

这三个量真正打出来，我们才算真正进入了下一阶段的收益空间喵～
