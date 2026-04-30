# GAS 访存设计与 4×4 Mesh 实验说明（对外简版）

本文面向协作方，概述当前 GAS（Gather–Apply–Scatter）访存方案的技术要点与实验方法学。内容聚焦语义、关键参数、统计口径与复现实验，不涉及代码符号或文件路径。

---

## 1. 范围与目标
- 场景：单计算单元起步（本地缓存层次+DRAM 模型），逐步外推至 4×4 网格互连；仅突触权重走 DRAM，神经元状态在本地累加与阈值判断。
- 目标：以最小改动验证 GAS 相对基线的 DRAM 事务减少与等待时间收敛；沉淀“可调合并 + 可观测指标 + 可复现实验”的稳定流程。
- 对照：基线按“权重空间分片+粗粒度扫描”发起读；GAS 通过“阶段化+合并+排序+SRAM 回填”降低冗余访问。


## 2. GAS 设计要点（细化，含关键函数/变量）

### 2.1 阶段语义与窗口驱动

GAS 将访存处理划分为三个阶段，通过时间窗口自动推进：

- **Gather 阶段**：收集上游的读请求并缓存到暂存区（staging_reads_），不立即下发到 DRAM。系统通过 onRead() 回调记录每个请求的到达时间（staged_arrival_ns_），并统计上游请求总数（gas_upstream_reads）。当遇到窗口结束标志（end_gather_seen_）或窗口时间到期时，自动进入下一阶段。

- **Apply 阶段**：对收集到的所有请求进行批量优化处理。maybeEnterApply_() 函数负责阶段切换，进入后统一执行"分桶→排序→构段→调度"流程。优化后的访存段通过 issueGranule_() 下发到 DRAM，并受并发上限（max_inflight_reads_）控制。当所有必需的数据就绪（required_set_）或窗口到期时，emitApplyResponses_() 从片上缓冲（sram_blocks_）中读取数据并响应上游请求。

- **Scatter 阶段**：BeginScatter 冻结窗口累加器，按 post 升序将 ΔV 一次性应用至膜电位（本地数组；阈值判定在此，泄露/钳位等在常规状态更新路径执行），逐元执行阈值判定 `checkAndFireSpike()` 并产出 Axon‑out[t]（位图/稀疏）。不对神经元状态做外部存储写回；阶段边界下 SB 由 `flush_after_scatter` + `doFlush_()` 清理，窗口累加器在应用完成后以 `accReset_()` 翻页/清零，确保窗口隔离。当前实现中神经元参数驻留于 PE 内部的连续数组，未涉及 DRAM→SRAM 搬移，状态更新在本地完成。

阶段切换由窗口时钟（window_cycles_*）自动驱动，阶段序号（stage_seq）单调递增。系统还支持"尾等待"机制（tail_wait_timeout_ns），允许在窗口结束后等待一段时间以接收迟到的响应，确保数据完整性。

### 2.2 合并机制（细/粗粒度互补）

合并机制是 GAS 降低访存事务的核心。系统采用两层合并策略：

**细粒度合并（基于空洞阈值）**

当两个访存段之间的空洞较小时，将它们合并为一个更大的突发访问往往更高效。判断逻辑通过 gap_ok_by_k_Lmax() 封装，判断标准有两个：
- 空洞大小不超过阈值 k（gap_merge_k_bytes），该值根据 DRAM 行激活和预充电的固定时延折算
- 合并后的总长度不超过最大突发限制 Lmax（burst_bytes_max），受限于总线带宽和片上缓冲容量

满足条件的空洞通过 extend_segment_mark_gap() 被"吸收"进突发段，系统累计记录吸收的空洞字节数（gas_gap_absorbed_bytes）用于评估合并效果。当 gap_merge_enable=0、k==0 或 Lmax==0 时自动禁用细合并。

**粗粒度合并（基于行窗口）**

针对同一行（或 bank×row）内的多个小访问，系统维护一个累加计数器。当累计的有效读字节达到阈值（row_window_bytes）或等待时间超时（row_window_timeout_ns）时触发分段。这种机制特别适用于数据活跃度较低的场景，避免长时间等待导致的饥饿问题。系统记录触发次数（gas_row_window_triggers）和覆盖字节（gas_row_window_bytes）。

合并策略的优先级顺序为：细粒度合并 → 检查超时 → 检查字节阈值，这样的设计既能捕捉紧密相邻的访问，又能在分散访问时及时触发。

### 2.3 分桶、构段与排序

**智能分桶**

系统通过 bucket_by_bank_row() 函数，根据 DRAM 地址映射配置（bank_bits/bank_shift）将请求按 bank×row 分组。如果地址映射不可靠或存在随机扰动，系统会自动退化为仅按 row 分组，并输出提示信息。这种自适应机制保证了在不同配置下的稳健性。

**段构建流程**

在每个桶内，请求首先通过 sort_by_addr() 按地址排序，然后线性扫描构建访存段：
- 如果新请求与当前段重叠或相邻（overlap_or_adjacent()），通过 extend_segment() 直接扩展当前段
- 如果间隙满足细合并条件（gap_ok_by_k_Lmax()），吸收空洞并扩展
- 如果触发行窗口条件（超时或字节阈值），通过 flush_segment() 完成当前段并用 start_segment() 开始新段
- 否则完成当前段，并以新请求开始下一个段

每个构建好的段用 (base_address, size) 表示，并生成唯一键值（key）登记到 granules_ 映射表中，同时加入 required_set_ 以跟踪数据就绪状态。

**访存调度与排序**

所有段构建完成后，通过 sort_granules_by() 按照排序策略（优先 bank×row，退化时用 row）重新排序。系统随后逐个通过 issueGranule_() 下发访存段，受并发上限（max_inflight_reads_）控制。当并发请求数达到上限时，暂停发起，直到 onDownstreamResp_() 回调释放额度。

### 2.4 片上缓存管理与流控

**数据回填与缓存**

当 DRAM 返回数据时，onDownstreamResp_() 回调通过在途映射表（inflight_down_）查找对应的段标识（key），然后调用 ensureCapacity_() 确保片上缓冲空间充足，将数据写入 sram_blocks_ 并标记为就绪（ready）。同时累加统计量（gas_unique_reads、gas_unique_bytes）并更新在途峰值（gas_inflight_peak）。

片上缓冲采用段粒度的 LRU 淘汰策略：当 ensureCapacity_() 检测到空间不足时，按照 lru_list_ 队列（front 是最久未使用）逐段淘汰，并计数淘汰次数（gas_evictions）。系统采样记录片上缓冲占用峰值（gas_buffer_occupancy_bytes）用于容量规划。

**并发控制与背压**

通过在途请求计数器和上限阈值（max_inflight_reads_）实现流控。当达到上限时，不再发起新请求，形成背压信号。每当 onDownstreamResp_() 返回一个响应，释放一个并发额度，允许新请求发起。

**上游响应**

所有必需数据就绪后，emitApplyResponses_() 遍历 granules_ 中的每个段，根据子请求的偏移量（offset）和大小（size）从 sram_blocks_ 中读取相应数据，发送 ReadResp 响应上游。随后清理挂起映射（pending_up_reads_），并在窗口收尾时统一清空 staging_reads_、required_set_、granules_ 和 end_gather_seen_ 标志。

### 2.5 两种构建路径

**延后构建（推荐模式）**

当 `window_auto=1` 时，可启用 `defer_issue_until_apply=1`（实验开关，默认 0）。所有请求在 Gather 阶段仅缓存进 `staging_reads_`，不做任何处理；进入 Apply 阶段后统一执行"分桶→排序→构段→调度"流程，最大化合并机会和排序收益（窗口由 `window_auto/window_cycles_*` 自动推进）。

注意：当 `window_auto=0` 时，Apply 阶段到达的 Read 无法被 `clockTick()` drain（否则有死锁风险），实现会强制走即时构建/下发以保证 forward progress。

**即时构建（兼容模式）**

禁用延后构建（defer_issue_until_apply=0）时，每个请求到达时通过 build_granule_immediate() 立即按当前策略构段并调用 issueGranule_() 下发。如果同时禁用细粒度和粗粒度合并（gap_merge_enable=0、row_window_enable=0），系统退化为简单的行对齐或缓存行对齐突发访问，牺牲性能换取最大兼容性和正确性保证。

### 2.6 统计指标体系

GAS 提供丰富的统计信息用于性能分析和调优：

**访存事务统计**
- 唯一突发数（gas_unique_reads）和覆盖字节数（gas_unique_bytes）：衡量实际下发的 DRAM 事务
- 总突发数（gas_total_bursts）和有效负载字节（gas_total_payload_bytes）：用于计算平均突发大小和载荷比例
- 上游请求总数（gas_upstream_reads）：原始请求数，用于计算合并比

**合并效果评估**
- 细合并吸收的空洞字节（gas_gap_absorbed_bytes）：量化细粒度合并带来的收益
- 行窗口触发次数（gas_row_window_triggers）和覆盖字节（gas_row_window_bytes）：评估粗粒度合并的贡献

**资源占用监控**
- 在途请求峰值（gas_inflight_peak）：评估并发需求
- 片上缓冲占用峰值（gas_buffer_occupancy_bytes）：容量规划依据
- 累加器相关指标（若启用端到端累加）：高水位线（gas_acc_high_watermark_bytes_total）、溢写次数（gas_acc_spill_records_total）和溢写字节（gas_acc_spilled_bytes_total）

**时序分析**
- 各阶段周期数（gas_stage_cycles_gather/apply/scatter）：了解时间分布
- 尾等待时长（gas_tail_wait_ns）：评估窗口收敛效率
- 事件流（Begin/End{Gather,Apply,Scatter}、stage_seq）：端到端分解的基础，宽松事件落盘开关（emit_stage_events_lenient）确保短跑场景下事件成对

**层级聚合**
每个 DRAM 响应通过 GasStatData 上卷统计。多核场景下，父级组件聚合所有子核的统计量（如 gas_unique_reads_total、gas_unique_bytes_total）。窗口化统计支持派生二级指标，如平均突发大小（avg_burst_bytes）、每 MiB 请求数（reqs_per_mib）、平均读延迟（avg_read_latency_0），以及从窗口采样得到的峰值指标（sb_peak_bytes、inflight_peak）。

---

## 3. 与基线的差异
- 发起策略：基线以“分片+粗扫描”形成规则步进访问；GAS 按行/组局部性聚合，显著减少小粒度读与跨行抖动。
- 典型效应：平均突发字节↑、每 MiB 请求数↓、行命中率↑（在行窗口有效时），端到端读延迟不劣于基线。
- 回退安全：当地址映射不可用或数据活跃度过低时，自动退化到行序与即时突发，保证正确性优先。

---

## 4. 参数与默认建议
- k（空洞阈值）：默认 2KiB，随 DRAM 时序/带宽校准；可通过数据驱动 sweep 与微基准回填。
- Lmax（最大突发）：默认 64KiB；与片上缓冲容量和后端约束共同确定。
- 行窗口（bytes/timeout）：默认关闭或小阈值；推荐在中低活跃度下启用以跨大空洞合并。
- 排序策略：优先 bank×row；当映射不可确定或存在随机地址翻译时使用行序。
- 阶段推进：窗口自动；尾等待开启以确保窗口完整性。
- 端到端累加/发放：默认关闭用于纯访存评估；需要端到端语义时再开启。

---

## 5. 4×4 Mesh 实验方法学（含 DDR4/HBM2 对照）

### 5.1 目标与范围
- 拓扑与对象：16 节点的二维网格；评估两类主流消息——读侧突发与脉冲多播；链路/路由采用统一、对称配置，避免偏置。
- 方法学基线：先在无网络回环中验证窗口/统计口径，再引入网络影响；先做合成步进（P0），再做真实轨迹重放（P1），逐步加复杂度。

### 5.2 前置一致性（Gate‑0）
- 语义：仅突触读访问外部存储；膜电位与阈值在本地完成；短跑验证窗口事件成对（Begin/End）与 GAS 聚合指标存在。
- 地址映射：优先银行×行分组与排序；无法可靠识别或存在随机翻译时退化为行序。DDR4（OpenRow）可自动对齐 `bank_bits/bank_shift`；HBM2 默认 `RandomTranslation` 时自动退化为 row。
- 窗口与定时：采用窗口自动推进；若短跑场景下出现阶段缺失，可启用宽松事件落盘开关，保证成对记录。

### 5.3 数据与轨迹准备
- 窗口事件：导出每个窗口的阶段时间戳与序号；用于后续 NoC 对齐与端到端分解。
- 读突发：导出按窗口切分的突发序列（覆盖字节、时间、目的上下文），用于读侧注入或远程占比调制。
- 脉冲轨迹：导出脉冲时间、目的集合与载荷大小（统一按固定粒度计）；用于多播评估（复制/树型）。
- 远程比例：如需灵敏度分析，可从 100% 远程起生成子集，按目标占比（如 5/20/50%）重排目的集合。

### 5.4 P0：合成步进（读/脉冲）
- 目的：在不引入真实耦合的前提下，校准消息规模与注入节奏，观察链路/端口热点与拥塞阈值。
- 设定：统一最小传输粒度（例如 32B flit）与链路带宽（例如 32GiB/s）；读侧按“平均突发字节×突发数/时间”换算注入；脉冲侧按“消息大小×条数/时间”换算。
- 注入计划：
  - 读侧：以步进或平滑速率注入窗口内的突发等价流量，保持时间分布与窗口占比近似；
  - 脉冲侧：以播散目的集合的等价速率注入，分别评估“复制多播”和“树型多播”。
- 观测：记录每端口注入/转发量与热点；输出均值、峰值与时间曲线；读侧与脉冲侧分别作图，比较 GAS 与基线的注入差异与热点收敛。
- 判定：GAS 相对基线应显著降低读侧注入量与热点峰值；在相同链路预算下，拥塞阈值右移（更高可承载速率）。

### 5.5 P1：真实轨迹重放（读/脉冲）
- 目的：以真实的突发与脉冲队列驱动网络，得到更贴近系统语义的端到端表现。
- 同步：将窗口事件作为主时钟，将突发/脉冲注入对齐到窗口时间轴；必要时在窗口内按原始顺序保持局部时间关系。
- 多播策略：对脉冲评估“复制”和“树型”两种；统一最小传输粒度与路径开销口径；记录 p50/p95/p99 时延与边缘链路流量。
- 远程比例：在固定链路预算下，分别评估不同远程占比（例如 5/20/50%），输出整体吞吐/时延与边缘流量占比曲线。
- 判定：
  - 读侧：平均突发字节上升、每 MiB 请求下降应在网络端转化为更低的注入与更短队列；
  - 脉冲侧：树型多播在目的集合较大时应优于复制；远程占比提升时，p95/p99 上升斜率放缓即为优化有效。

### 5.6A DRAM 后端对照（DDR4 vs HBM2，新增）
- 目的：在相同轨迹与网络配置下比较 `t_total = t_DRAM_wait + t_NoC + t_compute` 的差异。
- 步骤：
  1) 单 PE 生成阶段事件：DDR4 使用 `ramulator2_ddr4_openrow.cfg`；HBM2 使用 `ramulator2_hbm2.cfg`（或去掉 RandomTranslation 的 OpenRow 变体）。
  2) NoC 重放一次（树型多播、flit=32B、32GiB/s）。
  3) 用 `derive_end2end_breakdown.py` 分别生成 `end2end_ddr4.csv` 与 `end2end_hbm2.csv` 并对比。
- 预期：`t_NoC` 基本一致，差异主要体现在 `t_DRAM_wait`；HBM2 若仍含随机翻译，行序退化将影响行命中与突发聚合。

### 5.7 容量与稳定性（跨 Mesh）
- 片上缓冲：跟踪窗口内的片上缓存占用采样峰值与在途峰值，确认在 Mesh 压力下不出现级联淘汰；必要时提高行窗口阈值或收紧并发上限。
- 累加器：记录高水位、溢写次数与字节；若出现频繁溢写，优先调整窗口长度与合并参数，再考虑页化累加或分散发放策略。
- 误差控制：窗口统计的均值用 2ms–5ms 区间更稳；短跑仅用于快速验证，结论需以长跑为准。

### 5.8 指标口径与派生
- 网络：消息量、边缘链路流量、端口热点、平均/分位时延；
- 存储：唯一突发/覆盖字节、有效负载字节、吸收空洞字节、行窗口触发；
- 容量：片上占用峰值、在途峰值、累加器高水位/溢写；
- 派生：
  - 平均突发字节 = 覆盖字节 / 突发总数；
  - 请求密度 = DRAM 请求数 / 输入字节（或每 MiB 请求数）；
  - 行窗口占比 = 行窗口覆盖字节 / 覆盖字节；
  - 端到端拆解：总时长 ≈ DRAM 等待 + 网络时延 + 计算。

### 5.9 敏感性与扫参建议
- 排序与映射：银行×行 vs 行序；当映射不确定时优先行序，保证稳定性后再对比银行×行收益。
- 合并参数：k 与 Lmax 以 k_final 为基准微调；行窗口字节阈值与超时采用双参数网格，关注平均突发、请求密度、容量峰值的共同最优区间。
- 远程占比：从低到高（例如 5/20/50%）观察 p95/p99 的斜率与边缘链路堆叠，确定网络瓶颈位置与容忍区间。
- 多播策略：复制在小目的集合简单可靠；树型在大目的集合优于复制但对拓扑更敏感，需配合路径选择与队列深度评估。

### 5.10 常见问题与排查
- 窗口事件缺失：延长运行时间或开启宽松事件落盘；若仍缺失，多为窗口过短或读量过低。
- 端口热点异常：检查注入是否按窗口时间对齐、远程占比是否符合预期、排序策略是否与地址映射一致。
- 容量抖动大：缩短窗口或提高合并强度；必要时降低并发上限以减少在途峰值。
- 时延尾部偏高：优先启用树型多播或提升链路带宽；排查是否出现跨窗迟到（EndApply 需在在途清零后发出）。

【对照实验互链】
- 更完整的“基线（方案1）vs GAS”对照步骤、统一设置与判定口径，参见：`sst_dram_si/EXPERIMENT_4x4_MESH.md` 的“4) 实验四”。

### 5.11 基线方案（方案1：DRAM 切片，8 次轮换）
- 语义与节拍：采用切片轮换的顺序流水。一次窗口（superstep）仅处理权重矩阵的一个列切片，其余脉冲进入延后队列；窗口结束后轮换到下一个切片，直至轮满（默认 8 次）。在处理当前切片时执行粗粒度“行×列段（缓存行步进）”的扫描式预取，不做按需精确加载与细/粗合并。
- 阶段：
  - Gather：收集当前窗口的输入事件，并按切片归队（非目标切片事件保留到后续窗口）。
  - Apply：仅处理当前切片的事件；先对该切片执行预取扫描，再逐条消费事件，期间不进行 GAS 合并与窗口化优化。
  - Scatter：作为阶段推进的轻量收尾（可配置极少的周期），随后切换到下一个切片并进入下一窗口的 Gather。
- 关键参数（基准建议）：切片数 8；Gather/Scatter 周期用于拉开阶段节拍；切片间隔可为 0（连续轮换）。
- 判定与对照口径：
  - DRAM 侧：平均突发字节显著小于 GAS，对应每 MiB 请求数更高；控制器平均读延迟不应优于 GAS；
  - 统计侧：在仅启用基线时，GAS 类计数（如唯一突发、行窗口触发、在途峰值）应为 0 或保持基线水平；可读取“基线字节读量/请求量”等用于对照；
  - NoC 侧（P0/P1）：读侧注入/边缘链路流量高于 GAS，对热点与拥塞阈值形成上界对照。
- 用法建议：作为所有 Mesh 评估的对照组，保持输入与时间配置一致，仅切换访存策略（基线 vs GAS）。可在短跑（100us）做快速 sanity，再以 2ms–5ms 输出稳定结论。
## 6. 产出与统计阅读
- 运行日志：可读出 DRAM 模型的平均读延迟/行命中等控制器级摘要。
- 聚合 CSV：包含 GAS 唯一突发/覆盖字节、细/粗合并计数、在途峰值、片上占用、窗口周期等；多核父级提供总量与窗口化统计。
- 衍生指标：
  - 平均突发字节 = 覆盖字节 / 突发总数；
  - 请求密度 = DRAM 请求数 / 输入字节（或每 MiB 请求数）；
  - 有效载荷比例 = 有效负载字节 / 覆盖字节。

---

## 7. 边界与退化策略
- k 或 Lmax 为 0：自动禁用细合并；仅保留行/缓存行对齐突发。
- 行窗口阈值或超时为 0：禁用粗合并；仅依赖细合并。
- 地址映射未知/含随机扰动：退化为行分组与行序排序；统计与功能保持稳定。
- 阶段事件在短跑下缺失：可启用宽松落盘开关，保证 Begin/End 成对以便端到端分解。

---

## 8. 推荐使用流程（实操建议）
1) Gate‑0：短时自检，确认地址映射与 GAS 指标落盘正常。
2) k 定标：完成 sweep 与微基准，形成 k_final；据此固定 Lmax 与排序策略。
3) 容量评估：在目标活跃度下扫行窗口参数，读取片上/在途/累加器峰值并给出安全区间。
4) Mesh 评估：先做 P0 曲线对比，再做 P1 轨迹重放（含远程占比与多播策略），输出 p95/p99 与边缘链路堆叠。
5) 端到端：结合窗口事件与 Mesh 汇总，得到 DRAM 与 NoC 的占比拆解，作为方案取舍与参数固化依据。

---

## 9. 风险与注意事项
- DRAM 地址映射与策略需一致；存在随机翻译时不要强行使用 bank×row 分组。
- 统计量较多时注意 CSV 写入开销；必要时降低粒度或缩短窗口。
- 仅在链路自检时启用“返回零值映射为默认权重”的调试开关，正式评测时必须关闭。

（完）


---


---

## 统计口径（含单位）
- GAS（GatherBufferIF）：`gas_unique_reads/bytes`（reads/bytes）、`gas_row_window_triggers/bytes`（count/bytes）、`gas_req_coalesce_size_bytes`（bytes，直方图）、`gas_buffer_occupancy_bytes`（bytes，直方图）、`gas_stage_cycles_{gather,apply,scatter}`（ns，直方图）。
- 阶段事件（per-window）：`seq`（count）、`event`、`sim_time_ns`（ns）、`acc_updates`（count）、`posts_touched`（count）、`hwm_bytes`（bytes）、`spill_records`（count）、`spilled_bytes`（bytes）、`spikes_emitted`（count）。
- 单PE汇总（essential_summary.json）：`memory_requests`（count）、`dram_bytes_read`（bytes 与 MiB 派生）、`firing_rate`（per_neuron_per_us）、`spikes_per_neuron`（count/nerve）、`gas_superstep_cycles.{avg,p95,p99}`（ns）、`windows`（count）、`wall/user/sys`（sec）、`maxrss_kb`（kB）。
- NoC（test_noc_timestep.py）：`router.packet_count`（count）、`router.network_load`（bytes）、`spikes.csv/granules.csv`（32B/flit 口径）。

附录1：Mesh 参数基线（当前配置）
- 拓扑规模：4×4 网格（16 个节点/PE）。
- 每 PE 规模（大规模配置）：20 核/PE × 50,000 神经元/核 ≈ 1,000,000 神经元/PE；如未覆盖，脚本也支持小规模调试模板（例如 16 核×32 神经元/核）。
- L1 缓存：容量 16KiB，相联度 8，行大小 64B，频率 2GHz。
- L2 缓存：单 PE 模板可关闭（用于最坏延迟评测）；多 PE Mesh 场景默认 128KiB，相联度 8，行大小 64B，频率 2GHz，非包容。
- 片上总线：频率 1GHz（PE 内部 L1/（L2）/MC 互连）。
- 内存控制器（每 PE）：1GHz，访问时延约 100ns，容量 64MiB；DRAM 后端使用 ramulator2（DDR4 基准配置）。
- GAS 前端关键参数：
  - 细合并阈值 k=2048B；最大突发 Lmax=64KiB；最大在途请求 128–256；片上缓冲容量 256KiB–1MiB；
  - 窗口节拍（g/a/s）常见配比：200/40/40（周期）；行窗口常用配置：bytes=4KiB、timeout=50ns（可按实验切换/关闭）。
- NoC（Merlin hr_router）：
  - 链路与交叉带宽：32–40GiB/s；flit 大小 32B；
  - 输入/输出延迟 10ns；输入/输出缓冲 4–8KiB；端口数 5（N/E/S/W+本地）；VN=1。
- NIC：链路带宽与路由器口径一致；默认启用批处理，本地批阈值 16，远端 64（8×8 场景可提高至 96–128）。
- 其他通道口径：权重加载块 128B；膜电位与阈值在 PE 内部连续数组上更新（不做 DRAM 写回）。

说明：以上为当前实验的“默认/常用”口径，可通过运行配置覆盖（如每 PE 核心/神经元、缓存容量、链路带宽等）。为保证对照统一，推荐在 NoC 对比中固定 flit=32B，并在 32GiB/s 与 40GiB/s 两档下各给一组结果。

---

主入口与脚本分工（同步说明）
- 主入口：`sst_dram_si/test_noc_timestep.py`
  - P0：内置 baseline/slice/gas/sram 四方案，在 Merlin mesh（flit=32B）下直接对比；
  - P1：`--replay` 模式，调用 `tools/noc_trace_driver.py` 重放 granules/spikes（`--multicast tree` 统一树型多播），再用 `tools/derive_end2end_breakdown.py` 做端到端分解；
  - 特点：不依赖权重/数据文件，启动快、口径统一，适合扫参与出图。
- CSV 生产者（可选）：`sst_dram_si/test_mesh_4x4.py`
  - 作用：在 `MESH_WEIGHT_MODE=event`（`MESH_MAPPING_MODE=post|pre`）下导出真实 `granules_mesh.csv/spikes_mesh.csv`；
 - 现状：曾遇一次退出冲突，已用合成 granules 兜底 Mesh 对照；后续稳定性裁剪后再作为生产者使用；主跑脚本保持 `test_noc_timestep.py` 不变。

互链参考：更详细的 Mesh 实验步骤与命令，见 `sst_dram_si/EXPERIMENT_4x4_MESH.md` 的“主入口与脚本分工（重要）”与“4) 实验四：基线（方案1）vs GAS 对照”。


附录3：DRAM 切片（8 次轮换）基线定义（方案1）
- 含义：将一次完整的权重空间扫描拆分为 8 个等份，每次从 DRAM 顺序读取 1/8 权重；
- 过程：对每个 1/8 分片，按当前发放列表处理该分片内的全部突触；完成后轮换到下一分片；
- 约束：不做任何合并与排序优化，不利用行窗口；读取顺序仅按“分片→顺序”推进；
- 目标：作为 GAS 的对照基线，衡量细/粗合并带来的 DRAM 事务与等待时间改善；
- 复现：在主入口选择 `slice` 场景，其他参数（Mesh规模、带宽、发放密度）与对照保持一致。


    ## 附录2：术语表
     | 术语 | 英文 | 说明 |
     |------|------|------|
     | GAS | Gather–Apply–Scatter | 三阶段访存优化架构 |
     | Mesh | Mesh Network | 网格互连拓扑 |
     | NoC | Network on Chip | 片上网络 |
     | PE | Processing Element | 处理单元 |
     | LRU | Least Recently Used | 最近最少使用（缓存淘汰策略）|
     | P0/P1 | Phase 0/Phase 1 | 实验阶段编号（合成/真实轨迹）|
     | k | gap_merge_k_bytes | 空洞阈值参数 |
     | Lmax | burst_bytes_max | 最大突发长度参数 |
