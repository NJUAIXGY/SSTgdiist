# PE 内部优化现状、怪圈根因与下一阶段路线图（2026-03-24）

> 日期：2026-03-24  
> 状态：state-summary + root-cause report v1  
> 目标：把最近几轮 `PE-internal core-level` 优化的真实结论收敛成一份可执行报告，明确我们是否已经进入重复怪圈、怪圈的结构性根因是什么，以及下一阶段该如何避免继续在错误抽象边界上做局部 patch。

---

## 0. 一句话结论

当前我们确实再次进入了一个真实的怪圈，但它不是“实现不够努力”或“参数还没扫够”的问题，而是一个更底层的架构重复：

- **我们不断发现更早、更强的 PE 内共享信号；**
- **但真正 actual 的机制仍然附着在 `per-core private hot path` 外围；**
- **于是得到的是共享活动、共享计数器、共享 residency，而不是共享请求基数压缩。**

换句话说，最近几轮工作的真实模式是：

- **`observe overlap -> actual activity -> smaller regression -> still no net gain`**

这不是偶然，而是当前代码基线决定的结果。

---

## 1. 当前代码现状：为什么 PE 内优化很容易退化成外围 patch

### 1.1 真实热路径仍是 per-core private execution

结合已有代码审阅，今天 `SnnDL` 在 `PE` 内部的真实主路径仍然是：

- `core -> workload -> WeightMemorySubsystem (WMS) -> StandardMemAccess`

这意味着：

1. 每个 `core` 仍然有自己的 `WMS` 执行壳；
2. 真正的 issue / memory service 仍然从 `per-core` 视角出发；
3. `PE` 级 provider、registry、fabric、local object 目前更多是 helper / observe / registry 层，而不是统一的 shared issue/service plane。

这也是 [2026-03-21-pe-internal-core-architecture-code-state-review.md](./2026-03-21-pe-internal-core-architecture-code-state-review.md) 的核心结论：

- **当前不是没有 `PE` 内共享，而是共享语义已出现，但共享微结构尚未成立。**

### 1.2 今天的共享更多发生在语义层，不在执行边界

今天已经存在的共享，主要以以下形式出现：

- `WMS` 内部 shared-line registry / residency / tracker
- `PE` 级 ingress / frontier observe / harbor / local object naming
- `ring` / `DMA` / `local storage` / `shared fabric` 等 provider skeleton

但这些共享仍然缺少一个统一 contract：

- 谁是真正的 `PE owner`
- 谁负责 owner-first launch
- 谁决定 shared service scope
- 谁只负责 ready / join / commit-safe fanout

因此，系统表面上已经有很多“共享部件”，但真正影响 cardinality 的 hot path 仍是私有的。

---

## 2. 这轮实验到底告诉了我们什么

### 2.1 已经证明 PE 内 overlap 很强

`metadata frontier observe` 的意义非常大，因为它证明“PE 内共享机会不存在”这个假设已经被否掉了。

关键数据见：

- [2026-03-18_pulse_metadata_frontier_observe_ab_v1/snapshot/compare.tsv](../mainexp/experiments/2026-03-18_pulse_metadata_frontier_observe_ab_v1/snapshot/compare.tsv)

代表性指标：

- `pulse_metadata_frontier_base_overlap_ratio = 0.9408203125`
- `pulse_metadata_frontier_band_overlap_ratio = 0.95`

但与此同时：

- `model.sim_time_actual_ns = 224813 -> 224813`
- `memory.memory_requests = 150907 -> 150907`

结论不是“frontier 没价值”，而是：

- **frontier overlap 被观察到了，但没有被接到能改变 request cardinality 的执行边界上。**

### 2.2 metadata seed actual 并不是 early owner，而是 late join-only

关键数据见：

- [2026-03-18_pulse_metadata_seed_actual_ab_v1/snapshot/compare.tsv](../mainexp/experiments/2026-03-18_pulse_metadata_seed_actual_ab_v1/snapshot/compare.tsv)

代表性指标：

- `pulse_metadata_seed_candidates_total = 464`
- `pulse_metadata_seed_prefetch_owner_total = 0`
- `pulse_metadata_seed_join_only_total = 464`
- `pulse_metadata_seed_owner_already_exists_total = 464`

这说明这条路径的真实语义并不是：

- `owner-first metadata seed`

而是：

- **demand 已经起跑以后，seed 只是搭上了已有 owner，变成 join-only residency capture。**

也就是说，我们以为自己在做“更早的共享”，但实际结构仍然是“既有私有 issue 之后的旁路加入”。

### 2.3 gather/preband actual 说明“机制真的动了”，但仍然没有压缩基数

关键数据见：

- [2026-03-18_pulse_mfb_gather_preband_actual_ab_v1/snapshot/compare.tsv](../mainexp/experiments/2026-03-18_pulse_mfb_gather_preband_actual_ab_v1/snapshot/compare.tsv)

代表性指标：

- `model.sim_time_actual_ns: 224813 -> 225715`，`+902ns`
- `memory.memory_requests: 150907 -> 151028`，`+121`

这里最重要的认识是：

- **actual 机制已经不再只是 observe-only，它确实在改变行为；**
- **但改变出来的是更多 service traffic / control overhead，而不是 request elision。**

这说明我们终于摸到了“共享机制的成本”，但还没有摸到“共享机制的收益入口”。

### 2.4 tightening 与 barrier 的价值，是帮助我们看清失败形状，而不是已经赢钱

关键数据见：

- [2026-03-21_pulse_mfb_gather_tightening_sweep_v1/snapshot/compare.tsv](../mainexp/experiments/2026-03-21_pulse_mfb_gather_tightening_sweep_v1/snapshot/compare.tsv)
- [2026-03-23_pulse_mfb_gather_barrier_ab_v1/snapshot/compare.tsv](../mainexp/experiments/2026-03-23_pulse_mfb_gather_barrier_ab_v1/snapshot/compare.tsv)

代表性指标：

- tightening 的最好点仍然是：
  - `memory.memory_requests +56`
  - `model.sim_time_actual_ns +294ns`
- barrier 进一步缩小回退为：
  - `memory.memory_requests +39`
  - `model.sim_time_actual_ns +146ns`
- `pulse_mfb_gather_head_distance_avg` 从 `76.88` 降到 `33.47`

这说明 barrier 不是没用，相反它非常重要，因为它证明：

- **更严格的 cohort / window discipline 确实能减少错误 owner 和过远 join；**
- **但它仍然没有让共享发生在真正的 owner-first pre-issue 边界上。**

所以它只是“让错误变小”，还不是“让收益出现”。

### 2.5 idx2 frontier carry 已经基本被证伪

关键数据见：

- [20260323-100906/essential_summary_mesh.json](../mainexp/experiments/2026-03-22_idx2_ingress_frontiercarry_sweep_v3/runs/idx2_ingress_carry_guard_frontier_k32/20260323-100906/essential_summary_mesh.json)

代表性指标：

- `idx2_frontier_kept_but_zero_waiter_total = 10240`
- `idx2_frontier_kept_and_later_useful_total = 0`
- `idx2_frontier_kept_later_useful_after_zero_waiter_ratio = 0.0`

这条证据基本说明：

- **晚期 frontier carry 不是一条能进入收益空间的主线。**

它既没有转成稳定 waiter，也没有转成稳定 owner-first usefulness。

### 2.6 OSA 方向目前仍然是架构骨架，不是已证明收益

关键数据见：

- [2026-03-21-pe-internal-pulse-osa-architecture-design.md](./2026-03-21-pe-internal-pulse-osa-architecture-design.md)
- [pulse_osa_shared_weight_owner_l0_actual/20260322-202136/essential_summary_mesh.json](../mainexp/experiments/2026-03-22_pulse_osa_shared_weight_owner_l0_smoke_v1/runs/pulse_osa_shared_weight_owner_l0_actual/20260322-202136/essential_summary_mesh.json)

代表性指标：

- `pulse_shared_service_hits_total = 0`
- `pulse_shared_service_misses_total = 0`

这说明：

- `OSA` 方向在架构上仍值得继续；
- 但它目前还是 smoke / skeleton 阶段，不能被当成“我们已经找到 escape path”的经验事实。

---

## 3. 我们到底在重复什么怪圈

### 3.1 怪圈的固定模式

过去几轮几乎都在重复同一条轨迹：

1. 发现一个更早、更共享的 metadata / frontier 信号；
2. 在现有 per-core 路径旁边加一个 isolated actual 机制；
3. correctness 依然保持干净；
4. overlap、join、head-distance、residency 等计数器开始变化；
5. 但最终只有三种结果：
   - 完全不变；
   - 更活跃但更慢；
   - 回退缩小，但仍未跨过 baseline。

这就是我们现在感受到的“又回来了”。

### 3.2 这个怪圈为什么不是偶然

因为我们每次推进的位置，本质上都还属于：

- **对一个 per-core private issue/service 体系做外围强化。**

于是共享机会只能以三种方式出现：

1. `observe-only`
2. `late join`
3. `owner already exists`

而真正能赢钱的路径应该是：

1. `shared object already exists`
2. `owner-first launch happens before private issue fanout`
3. `later consumers exact-join without issuing duplicate work`

只要没有跨过这个边界，我们就会反复看到“共享行为成立，但共享基数不降”。

---

## 4. 哪些东西是有用的，哪些东西已经应当停止投入

### 4.1 已证实有价值的认识

以下结论值得保留，后面应继续围绕它们设计：

1. **PE 内 overlap 很强，尤其是更早的 metadata frontier。**
2. **真正重要的不是 ingress 更集中，而是 service work 是否被压缩。**
3. **barrier / window discipline 有助于减少错误 owner 和过远 join。**
4. **exact retire contract 是可以守住的，问题不在 correctness，而在收益入口。**
5. **`PE` 内问题必须回到 object owner / service plane / issue plane 的统一设计上。**

### 4.2 已被反复证伪或价值很低的方向

以下方向不应再作为主线投入：

1. **晚期 line/value carry**
2. **在现有 late trigger 上继续做 budget / threshold 微调**
3. **把 residency capture 误当作 early seed**
4. **希望 observe counters 自然转化为 net performance gain**
5. **把“变得没那么差”误判成“已经开始进入收益空间”**

这些方向不是完全没有信息量，而是已经足够证明：

- **它们最多能帮助我们更精细地理解失败，不再值得继续作为主收益路线。**

---

## 5. 真正的结构性瓶颈是什么

### 5.1 瓶颈不在 overlap，不在 correctness，而在 ownership boundary

当前最大的结构性瓶颈可以概括为一句话：

- **共享发生的位置，仍然晚于 owner 决策和私有 issue 起跑的位置。**

于是所有更早的 metadata / frontier 信号，都会在实际落地时被降格成：

- observer
- follower
- joiner

而不是：

- launcher
- owner
- shared execution authority

### 5.2 代码层的真实形式

今天的代码更接近：

- `per-core WMS/private issue` 为主体
- `PE-shared registry/observe/local object` 为附属

而我们真正需要的是：

- **`PE-shared object owner/service plane` 为主体**
- **`per-core compute/commit` 为末端 exact consumer**

只要这个主从关系不翻转，我们后面再加多少 frontier probe、metadata hint、join heuristic，大概率都还会回到同一类结果。

---

## 6. 下一阶段不再重复旧路径的路线图

### 6.1 新阶段的总原则

下一阶段必须明确转向：

- **不再继续优化“共享证据”，而是开始实现“共享执行所有权”。**

也就是从：

- `better metadata hints on private path`

转到：

- **`owner-scoped PE-shared object/service architecture`**

这与 [2026-03-21-pe-internal-pulse-osa-architecture-design.md](./2026-03-21-pe-internal-pulse-osa-architecture-design.md) 的方向一致，但需要更明确地收束成一个工程主线：

- **shared object 先成立，shared owner 再起跑，exact core-private commit 最后保持不变。**

### 6.2 新阶段的推荐主线

推荐把下一阶段正式定义为：

- **`PE-shared metadata/value object owner -> owner-first launch -> exact consumer join -> core-private exact commit`**

它不是继续做一条新的 `seed heuristic`，而是改写 hot path 的责任边界：

1. `PerPe` 对象必须由 `PerPe runtime owner` 实际拥有；
2. shared service 必须真的落在 shared object 上；
3. consumer core 不再各自决定是否发起重复 work，而是 join 到已经存在的 owner/service 上；
4. architectural state visibility 仍然只在 per-core exact retire 发生。

### 6.3 具体阶段建议

#### 阶段 A：建立 shared object truth

目标不是提速，而是确认：

- `weight_idx_store`
- `weight_value_store`
- 必要时 `activation_ingress_store`

是否已经从“命名为 `PerPe` 的对象”变成“运行时真正由 `PerPe owner` 服务”的对象。

退出标准：

- 实际 hot path 中能观察到 shared object owner 命中；
- 不再只是 registry 命名或 smoke-level wiring。

#### 阶段 B：把 owner-first launch 前移到 shared object plane

这一步的关键不是 barrier 本身，而是：

- **owner launch 必须发生在 shared object plane，而不是 private issue 后面。**

退出标准：

- `prefetch_owner_total` 或等价的 owner-first 指标必须从 `0` 变成稳定正值；
- `join_only_total / owner_already_exists_total` 不再主导全局。

#### 阶段 C：以 request elision 而不是 overlap/activity 作为唯一收益门槛

从这一阶段开始，任何新机制都必须首先回答：

- 它有没有减少 duplicate request / duplicate service work？

如果不能，就不进入主线。

硬性门槛：

1. `memory.memory_requests` 先下降；
2. 再看 `sim_time_actual_ns` 是否下降；
3. correctness overhead 单独统计，不允许被主指标掩盖。

---

## 7. 下一阶段必须新增的度量面

为了避免再次掉进“计数器很热闹，但收益没有落下来”的怪圈，下一阶段的 probe 必须从一开始就围绕完整漏斗设计。

建议固定记录以下四层：

### 7.1 Opportunity

- 发现了多少共享候选
- 候选来自哪类 metadata object
- 候选是否发生在 owner 决策之前

### 7.2 Ownership

- owner-first launch 总数
- launch 发生在哪个 object plane
- launch 是否在 private issue 之前

### 7.3 Compression

- duplicate request 被消掉多少
- duplicate service work 被消掉多少
- join 是 exact join 还是 late join

### 7.4 Exactness Overhead

- ready-blocked cycles
- owner wait / join wait
- late-split / abort
- head rescue / barrier intervention

只有把这四层一次性拉通，我们才能真正区分：

- “共享成立但无收益”
- “共享有收益但被 exactness overhead 吃掉”
- “共享根本还没进入 owner-first 执行边界”

---

## 8. 这份报告对应的最终判断

### 8.1 为什么我们现在不该继续沿旧路径微调

因为现有实验已经足够说明：

- 问题不是阈值；
- 不是 probe 不够早；
- 也不是 correctness 限制太强；
- **而是共享没有成为 hot path 的执行所有权。**

继续在旧边界上加 patch，大概率只会继续得到：

- 更复杂的 observe
- 更热闹的 actual counters
- 更小的 regression
- 但仍然不会进入真正的收益空间

### 8.2 为什么这反而是一个好消息

因为现在我们已经把问题空间压缩得足够干净了：

1. overlap 真实存在；
2. exact retire contract 可守；
3. barrier discipline 有效但不够；
4. late carry / late join 路线基本证伪；
5. 下一步必须进入 `owner-scoped shared object/service plane`。

这意味着我们不是“完全没方向”，而是：

- **已经把错误主线排得很干净，接下来可以更有把握地进入真正的 PE 内部架构阶段。**

---

## 9. 建议作为后续执行的主判断

从今天开始，PE 内部优化的主判断建议收束为：

- **不要再问“还能不能再早一点看见 overlap”；**
- **而要问“共享机会是否已经变成了 owner-first shared execution” 。**

如果答案是否定的，那么这条路径无论 counters 多漂亮，都不应视为下一阶段主线。
