# ECHO：面向 `full_system_baseline` 的 Memory × NoC 协同主线设计

## 0. 设计目标与默认假设

本文档给出下一阶段唯一推荐的系统级协同方向，默认建立在当前唯一主基线之上：

- **基线**：`full_system_baseline = STORM(multicast_mesh) + GAS + GCSS-GLIDE`
- **固定实验口径**：`4x4 bcsr10k step1`
- **后端**：`ramulator2_ddr5`
- **语义要求**：不改变 `GAS` 语义、不放松 strict validation、不引入“只在非严格口径成立”的捷径

默认优先级如下：

1. **主线可合入性**：新机制必须能够作为当前 `full_system_baseline` 的增量扩展，而不是推翻现有主线
2. **paper solidity**：收益要能用已有主指标和新增跨层统计形成完整证据链
3. **真实后端一致性**：设计应直接面向 `Ramulator2` 的真实 DRAM 几何/时序，而不是建立在理想 cache 上
4. **实验隔离**：新机制必须支持“按 cohort 选择性启用 + 一键退回当前 baseline”的混合运行

---

## 1. 为什么现在必须做 memory × NoC 协同，而不是单侧继续优化

当前三组系统级 baseline 已经把问题分层钉死：

- `memory_baseline = Merlin + GCSS-GLIDE`
  - `sim_time_actual_ns = 1086400`
  - `memctrl.req_total = 150110`
  - `gas.memctrl_payload_utilization = 0.317663`
  - `gas.payload_bytes_per_memctrl_req_avg = 20.3304`
- `noc_baseline = STORM + GCSS-idx2`
  - `sim_time_actual_ns = 1383670`
  - `memctrl.req_total = 1684046`
  - `gas.memctrl_payload_utilization = 0.0283498`
  - `gas.payload_bytes_per_memctrl_req_avg = 1.81439`
- `full_system_baseline = STORM + GCSS-GLIDE`
  - `sim_time_actual_ns = 257453`
  - `memctrl.req_total = 150907`
  - `gas.memctrl_payload_utilization = 0.316370`
  - `gas.payload_bytes_per_memctrl_req_avg = 20.2477`

这说明：

1. **STORM 已经把 NoC 主路径打通**：`full_system_baseline` 与 `noc_baseline` 的发包形态接近，都进入 `SpikeKey` 主线；`full_system` 的巨大优势并不是因为它“更会发包”，而是因为它没有回退到低效 memory 形态
2. **GCSS-GLIDE 已经把 memory 主路径打通**：`full_system_baseline` 与 `memory_baseline` 的 `payload_utilization / payload_bytes_per_memctrl_req_avg` 非常接近，说明 `GCSS-GLIDE` 已经把单 PE / 单 core 的 payload 效率拉到了当前主线最优
3. **下一瓶颈是“跨层结构错配”**：`STORM` 在前向已经按 `2x2 PE block` 组织事件传播，而 `GCSS-GLIDE` 在回包/读服务侧仍以 `dst-core` 为主服务域。于是系统仍停留在：
   - NoC 先聚（block multicast）
   - 到达各 PE 后再散（每 PE/每 core 各自展开）
   - memory 再按私有地址重新聚（VLF-line）

当前 `full_system_baseline` 已经证明“单侧优化都必要”；下一步若想再显著提升，就必须让 **NoC 的 block/group 语义直接变成 memory 的服务语义**。

---

## 2. 相邻工作边界：我们和公开方案差在哪里

近期与代表性公开系统给出的边界非常清楚：

- **Loihi 2** 强调的是 on-chip 可编程神经元、压缩/graded spike 编码、灵活神经动力学与片上内存组织；它并没有把“真实 DRAM 返回路径上的 synapse line 共享服务”做成主机制。
- **SpiNNaker2** 展示了大规模多核神经形态平台、事件路由与外部 LPDDR4 协同能力，但其公开叙事核心仍是“可扩展事件计算 + 外部存储支撑”，不是把事件 multicast 结构进一步编译进 DRAM 服务单元。
- 更一般的 throughput 架构工作表明两件事是真问题：
  1. **请求级 coalescing** 能显著降低无效 memory 请求
  2. **回复路径/注入路径** 自身会成为 tail bottleneck

但对于 **DRAM-based SNN + strict GAS + event multicast NoC** 这一组合，公开工作里还缺一个明确的系统级答案：

> 当前向已经用 block multicast 把“谁会一起被激活”表达出来之后，后端 memory 是否能把这些 block-shared events 编译成 **block-shared synapse line service**，并让 DRAM 的返回路径也变成 multicast/shared-service，而不是重新退回每个 PE 的私有读？

这正是我们的空白位。

---

## 3. 候选方向评估

### 3.1 候选 A：NoC-aware issue scheduling（不重排数据，只重排请求）

想法：继续沿用当前 `GCSS-GLIDE` 数据布局，只用 `STORM` 的 ingress/block 活跃信息做更 aggressive 的 issue 排序、bank/row 整形、或 block-aware issue credit。

优点：
- 落地最轻
- 不需要改权重格式

问题：
- 这类路线本质上仍是 **调度层优化**，不能改变“4B/少量 bytes 对 64B line”的根因
- 我们已经有多轮证据显示：单纯 issue/admission/retire 侧优化，在当前主口径下很难再转化成大收益

结论：
- **可作为辅助项，不适合作为下一阶段主创新点**

### 3.2 候选 B：跨 step 热 pre SRAM / line lease

想法：把多步高频 pre 或其共享 line 暂驻片上 SRAM，减少反复 DRAM 访问。

优点：
- 与 DRAM-based SNN 的分层叙事兼容
- 在 multi-step 场景可能有效

问题：
- 对当前 `step1` 主口径说服力有限
- 更像系统补强项，不是最直接回答“为什么 full_system 仍停在 20B/req 左右”的机制

结论：
- **适合作为后续增强项，不适合作为当前主创新点**

### 3.3 候选 C：选择性 block-home shared-line service（推荐）

核心思想：

- 不是把所有 synapse 都改造成 block-shared 格式
- 而是**只选择那些在 `STORM` 的 `2x2 block` 域内确实存在共享收益、并且在真实 DRAM + NoC 代价模型下净收益为正的 cohort**
- 对这些 cohort，把当前“每个 PE 私有读”的行为，升级成：
  - **一个 home PE 发起 DRAM line 读**
  - **block 内多个 PE/cores 共享这条返回 line**
- 对其他 cohort，完全走当前 `full_system_baseline`

结论：
- **这是唯一同时满足“创新性、可工作性、主线兼容性”的方向**

---

## 4. 推荐方案：ECHO

### 4.1 名称

推荐将该机制命名为：

- **ECHO**
- 全称：**Event-Coherent Homed-line Orchestration**

它表达的核心是：

- `STORM` 已经把前向 event 组织成 block-coherent 的传播单元
- `ECHO` 让后向 synapse service 也具有同样的 coherent/shared 结构
- 一次前向 multicast，在后向形成“一次 line 服务、多 PE 回响”的 **echo path**

### 4.2 核心思想

`ECHO` 不是另起炉灶的新 memory 系统，而是建立在当前主线之上的 **选择性第二路径**：

1. **未被选中的 cohort**：继续使用当前 `GCSS-GLIDE`（完全等价于 `full_system_baseline`）
2. **被选中的 cohort**：不再让每个 PE 私有 issue 本地 DRAM 读，而是：
   - 将 `(block_id, pre_global)` 映射到一个 **home PE**
   - 该 home PE 持有该 cohort 的 block-shared values layout 与 line directory
   - block 内其余 PE 只登记等待，不再各自发私有读
   - home PE 完成一次或少数几次 DRAM line 读后，将返回 line 以 block-local multicast / local fanout 的形式交付给等待方

ECHO 的目标不是“让所有权重共享”，而是只在以下条件同时满足时升级为 shared-line service：

- block 内确实有跨 PE / 跨 core 的共享消费
- 共享能减少真实 DRAM line 请求
- 额外的 local reply fanout 开销小于节省的 DRAM + queueing + command 成本

这正是它比 `naive_tass / TASS-LF` 更稳的地方：

- `naive_tass` 过于朴素，容易把“共享不够强”的流量也强行搬到 block 域处理
- `TASS-LF` 过于激进，默认把 block-level service 当成新普遍单位
- `ECHO` 是 **hybrid + selective + cost-driven**，因此更像一条能真正进入主线的系统机制

---

## 5. ECHO 的体系结构设计

### 5.1 离线编译：Shared-Cohort Selection

在当前 `full_system_baseline` 上，我们已经具备两个关键输入：

1. `STORM` 给出的 block/group 活跃结构
2. `GCSS-GLIDE` 给出的当前 values/line 布局与 payload 利用率

ECHO 离线阶段要做的是：

- 从 `baseline` profile 中提取 `(block_id, pre_global)` 的共享统计
- 对每个候选 cohort 计算：
  - `consumers(block, pre)`：这个 pre 在该 block 内被哪些 PE/core/post 消费
  - `private_lines`：若沿用 baseline，需要多少条私有 line / memctrl req
  - `shared_lines`：若改成 block-home layout，需要多少条 shared line
  - `dram_cost_saved`
  - `reply_cost_added`
  - `sram_index_cost_added`
  - `home_queue_risk`
- 只有当净收益显著为正时，才把该 cohort 标记为 **promoted cohort**

推荐的编译期判据形式：

`benefit = DRAM_saved_cost - reply_multicast_cost - extra_index_cost - home_conflict_penalty`

其中 `DRAM_saved_cost` 不应用抽象常数，而应由 **Ramulator2 真实配置** 派生：

- channel/rank/bank/row 几何
- line size
- 关键 timing（如 row hit / miss / conflict 的相对代价）
- 可选叠加 baseline 统计中的 bank/row 压力分布

这会把前面已经做过的“离线 DRAM 代价模型”工作，真正用到一个结构级 co-design 机制里。

### 5.2 数据格式：GCSS-GLIDE-ECHO（双路径混合）

ECHO 不建议替换掉当前 `GCSS-GLIDE` 主格式，而应新增一个 **选择性 side path**：

- **baseline path**：沿用现有 `gcss_valueonly_dstcore_vlf_premphf_plp`
- **echo path**：新增 `gcss_valueonly_blockhome_echo`

每个 block-home cohort 需要描述：

1. `block_id, pre_global -> cohort_id`
2. `cohort_id -> home_pe`
3. `cohort_id -> pre_len / line_count / line_base`
4. `line_id -> [(dst_pe, dst_core, post_local, lane_offset), ...]`

也就是说，ECHO sidecar 回答的不是“单个 core 的 pre 在哪”，而是：

- 这个 block 里、这个 pre 若走 shared service，应由谁服务
- 服务返回的一条 line 应被交付给哪些消费者

关键点：

- 未 promoted 的 flow 不受影响
- promoted cohort 只增加 sidecar，而不破坏 baseline path
- 这让实验能够进行 **逐 cohort fallback**，极大降低回归风险

### 5.3 运行时单元：Home Line Service Engine

建议新增一个实验性硬件单元：

- **Home Line Service Engine (HLSE)**

放置位置：

- 每个 PE 一个轻量实例
- 仅当该 PE 是某些 cohort 的 `home_pe` 时才实际承担共享服务

职责：

1. 接收本地 workload 或对端 PE 发来的 `shared-line service request`
2. 根据 `cohort_id / line directory` 生成 DRAM 读
3. 跟踪等待该 line 的本地与远端 waiters
4. 在 line 返回时，对 block 内 waiters 进行 fanout
5. 将最终 ready 事件交给现有 `WeightMemorySubsystem` / retire 路径

它不直接改变 neuron update，只改变“权重 line 如何被拿到”。

### 5.4 新的 packet / return path

ECHO 需要两类新传输对象：

1. `SynLineReq`
- 从非 home PE 发往 home PE 的紧凑请求
- 只携带：`cohort_id / pre_global / optional line mask / requester bitmap`
- 显著小于原始私有 DRAM 读的隐式成本

2. `SynLineReply`
- 从 home PE 回发给 block 内 waiters 的 reply
- payload 是真实 synapse line（或 line subspan）
- 可通过 block-local multicast / local endpoint multicast 扩展到多个 endpoint

这里的关键不是“又发了一次网络包”，而是：

- **原本要读多次 DRAM line**
- 现在变成 **读一次 DRAM line + 若干条 block-local reply fanout**

在真实 DRAM 成本高于 block-local NoC 成本、且共享度足够时，ECHO 才会选择这条路径。

---

## 6. 与当前主线代码的自然融合点

### 6.1 前向入口：`SnnWorkload` 的 `SpikeKey` fastpath

当前 `SpikeKey/SpikeTileKey` 到达后，会在 `SnnWorkload::deliverPacket()` 中被解析，并进入：

- `expandPreGlobalToWindowEdgesFast_()`
- 或 `expandPreGlobalToLocalSpikes_()`

这意味着：

- 现在 workload 已经在 `pre_global` 这一层面感知到“这个事件会影响哪些 posts”
- ECHO 不必改变前向语义，只需在这里插入一个 **shared-cohort probe**：
  - 若 `(block, pre)` 未 promoted：继续 baseline 路径
  - 若已 promoted：把 edge 记录为 `await shared-line service`，并把请求交给 `HLSE`

### 6.2 memory issue / retire：`WeightMemorySubsystem`

当前 `WeightMemorySubsystem` 已经具备：

- `recordEdgeWithPreRank()`
- `issueFromEdges()`
- `registerEdgeRetire_()`
- `tryRetireEdges_()`
- `VLF-line` issue reorder

这非常关键，因为它说明：

- 我们已经有一个能保证 **issue 可重排、retire 不乱序** 的成熟框架
- ECHO 不需要重写 retire 语义

推荐做法：

- 对 promoted cohort，在 `WeightMemorySubsystem` 中新增一种 edge source：`SharedLine`
- edge 仍然注册 retire seq
- 但 ready 不再由私有 `issueGcssByAddr_()` 的回调触发，而由 `HLSE` 的 `SynLineReply` 触发

这让 `ECHO` 的语义落点非常干净：

- 变的是 ready source
- 不变的是 retire discipline

### 6.3 NoC 数据面：`STORM` / `MulticastRouter` / `MulticastNIC`

当前 `STORM` 已经提供：

- `SpikeKey/SpikeTileKey` block-aware forward multicast
- `MulticastRouter` 的 inter/intra blocked multicast policy
- `MulticastNIC` 的 local endpoint multicast 扩展路径

因此 ECHO 不应该自建一套新 NoC，而应复用现有数据面：

- 前向事件仍然沿 `STORM`
- ECHO 只新增“shared reply”这一类 packet kind / payload codec
- 若 packet 只在 block 内传播，可优先复用 local-endpoint / block-local fanout 机制

这样做的价值在于：

- paper 叙事上形成完整闭环：
  - `STORM` 负责 forward multicast
  - `ECHO` 负责 return multicast
- 工程上避免新建第二套网络语义

---

## 7. 为什么 ECHO 比历史失败路线更 solid

### 7.1 相比 `naive_tass`

`naive_tass` 的问题是：

- 只要进入 block 域就尝试共享
- 但并没有解决“共享是否足够强、值不值得共享”的根问题

ECHO 的改进：

- **选择性 promotion**
- 只有正收益 cohort 才走共享路径
- 不会把低共享流量硬塞进 block service

### 7.2 相比 `TASS-LF`

`TASS-LF` 的问题是：

- 它本质上希望把 block-level service 变成新的普遍 memory 单元
- 布局、运行时、返回路径都较重
- 一旦共享度不足，就容易被 reply fanout 与控制复杂度吞掉收益

ECHO 的改进：

- 不要求“所有 block 流量都共享化”
- 只对高共享 cohort 使用 block-home layout
- 基线格式和基线路径完整保留
- 因此更适合作为主线可合入的“第二路径”

### 7.3 相比纯 scheduling / admission / retire 类优化

这些路线的问题是：

- 只能重排已有请求
- 改不了“请求本体仍然太碎”

ECHO 的本质不同在于：

- 它减少的是**请求实体数量本身**，而不是只改变请求顺序
- 并且同时改变了 **DRAM 端和返回 NoC 端** 的服务单位

这就是它更有机会形成架构级创新点的原因。

---

## 8. 需要新增的统计：论文证据链核心

ECHO 若要形成 solid paper evidence，必须新增跨层统计，而不只看 `sim_time_actual_ns`。

### 8.1 选择性机制本身是否在工作

1. `echo.promoted_cohort_total`
2. `echo.promoted_cohort_hit_total`
3. `echo.fallback_cohort_total`
4. `echo.promoted_edge_coverage`
5. `echo.promoted_payload_coverage`

### 8.2 是否真的减少了 DRAM 实体请求

1. `echo.private_line_req_saved_total`
2. `echo.private_line_req_saved_est_total`
3. `echo.home_line_req_total`
4. `echo.home_line_waiter_fanout_avg`
5. `echo.home_line_waiter_fanout_max`
6. `echo.shared_reply_bytes_total`
7. `echo.shared_reply_packets_total`

### 8.3 代价是否值得

1. `echo.reply_byte_per_saved_req_avg`
2. `echo.reply_hops_total`
3. `echo.home_queue_occupancy_cycles_total`
4. `echo.home_queue_blocked_req_total`
5. `echo.selection_positive_rate`

### 8.4 对当前主指标的传导

仍沿用现有主线指标：

1. `sim_time_actual_ns`
2. `memhierarchy.memctrl.req_total`
3. `memhierarchy.memctrl.bytes_est_total`
4. `gas.payload_bytes_per_memctrl_req_avg`
5. `gas.memctrl_payload_utilization`
6. `gas.memctrl_traffic_amplification`
7. `ramulator2.row_hit_rate_total`
8. `validation.log`

### 8.5 一个关键新增比值

推荐新增一个最重要的跨层归因指标：

- `echo.dram_bytes_saved_per_reply_byte`

如果这个值明显大于 `1`，就能直观证明：

- 增加的 block-local reply traffic 是值得的
- 我们不是在“拿 NoC 流量换 DRAM 流量但总成本不变”，而是在做真实的结构性转移

---

## 9. 闭环实验方案

### 9.1 固定口径

- `4x4 bcsr10k step1`
- `Ramulator2 DDR5`
- `full_system_baseline` 为唯一 baseline
- `validation.log: fail=0 warn=0/1，strict 不退化`

### 9.2 实验矩阵

1. `full_system_baseline`
- 当前主线

2. `echo_selective_off`
- 编译 sidecar 但运行时不走 promoted path
- 证明 sidecar 本身不破坏语义

3. `echo_selective_on`
- 开启完整 ECHO

4. `echo_force_all`
- 强行把所有候选都走共享路径
- 用来证明“为什么 selective 是必要的”

5. `echo_no_reply_multicast`
- 只做 home DRAM 聚合，不做高效 reply fanout
- 用来拆解 return path 的真实贡献

### 9.3 预期结果

理想证据链应是：

1. `echo_selective_off`
- 与 baseline 几乎重合
- 证明 sidecar / 编译期信息没有破坏主线

2. `echo_force_all`
- 可能只带来有限收益甚至回退
- 证明“共享不是越多越好”

3. `echo_selective_on`
- `memctrl.req_total` 明显下降
- `payload_bytes_per_memctrl_req_avg` 上升
- `payload_utilization` 上升
- `reply_byte_per_saved_req` 保持在合理区间
- `sim_time_actual_ns` 随之下降

这会形成一个非常干净的论文故事：

- `STORM` 让前向 event 共享成为可能
- `ECHO` 让返回 synapse line 共享只在“值得共享”的 cohort 上发生
- 编译器 + 真实 DRAM cost model 负责决定共享边界

---

## 10. 落地计划（仅设计，不进入实现）

### P0：证据补全

1. 用当前 `full_system_baseline` profile 提取 `(block, pre)` 共享度分布
2. 统计“若 block-home，同 pre 能减少多少 private line req”的上界
3. 建立 `reply_byte_per_saved_req` 的离线估计

### P1：离线 artifact

1. 新 generator：`gen_gcss_glide_echo_selective.py`
2. 输出：
   - baseline GLIDE artifact
   - promoted cohort sidecar
   - home mapping / line directory / manifest

### P2：运行时最小闭环

1. 新 experimental mode：`gcss_valueonly_blockhome_echo`
2. 新 `HLSE`
3. 新 packet：`SynLineReq / SynLineReply`
4. 只实现“promoted cohort + fallback baseline”双路径，不做额外 fancy 优化

### P3：统计闭环

1. 新增上文 `echo.*` 统计
2. 接到 `essential_summary_mesh.json`
3. 接到 `mainexp` snapshot 对比

---

## 11. 为什么这条路线有 ISCA / ASPLOS 潜力

ECHO 的价值不在于单一技巧，而在于它把我们系统里三个已经成立、但彼此还未真正耦合的事实统一起来：

1. **`STORM` 已经证明前向 event multicast 是系统级正确且有效的**
2. **`GCSS-GLIDE` 已经证明在真实 DRAM 下，payload 利用率是核心 memory 指标**
3. **`full_system_baseline` 已经证明 memory 和 NoC 两边必须同时正确，单侧最优不是系统最优**

ECHO 正好处在三者交叉点：

- 它不是泛泛的“做个 buffer/cache”
- 也不是单纯的“调度更聪明”
- 而是把 **forward multicast 的 group semantics** 编译成 **return-path shared-line service semantics**，并且让这一决定由 **真实 DRAM + NoC cost model** 驱动

从论文角度看，这给出的不是“一个工程 patch”，而是一条清晰的架构命题：

> 当事件前向传播已经是 group-aware 的时候，后向 synapse service 也必须变成 group-aware；否则系统会长期停留在“前向聚、后向散、memory 再聚”的结构性低效状态。

这条命题既足够新，也足够 anchored 到现有主线，适合作为下一阶段的主论文创新点之一。

---

## 12. 参考边界（用于后续论文 related work）

- Intel Loihi 2：强调片上可编程神经动力学、压缩/graded spike 等能力，但不是面向真实 DRAM 返回路径共享服务的架构设计
- SpiNNaker2：强调可扩展事件路由与外部 LPDDR4 支撑，但未将 event multicast 与 block-shared DRAM line service 编译成统一机制
- 通用 throughput 架构工作已经证明：请求 coalescing 与 reply path 都是系统瓶颈；ECHO 的区别在于把这两件事放进 `DRAM-based SNN + strict GAS + multicast NoC` 的统一框架里

### 外部参考（后续写 related work 时可直接回看）

- Loihi 2 论文：`https://arxiv.org/abs/2103.12894`
- SpiNNaker2 系统论文（Frontiers, 2024）：`https://www.frontiersin.org/journals/neuroscience/articles/10.3389/fnins.2024.1390008/full`
- 一般体系结构中“回复路径是系统瓶颈”的代表性工作（ARI, ISCA 2021）：`https://people.inf.ethz.ch/omutlu/pub/accelerating-CPU-GPU-interconnects_ARI_ISCA21.pdf`
