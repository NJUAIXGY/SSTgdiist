# SYNLINE：Synaptic Cacheline Multicast for DRAM-based SNN（设计方案）

日期：2026-03-10  
状态：Design-only（实验性机制，强隔离；不替换当前 full_system_baseline 主线）

## 0) 一句话结论

在 `full_system_baseline = (DRAM-based) GAS + GCSS-GLIDE + STORM + MulticastRouter` 已成立的前提下，**SYNLINE** 提出一个对称的“第二种多播”：

- `STORM` 负责 **spike 的 NoC 多播**（1 个 pre-spike 服务多个目的 block/cores）
- `SYNLINE` 负责 **synapse cacheline 的 memory-side 多播**（1 条 64B synapse line 服务多个目的 cores/edges）

目标是从体系结构层面直接压低 **cacheline overfetch/traffic amplification**，把当前 `~20B/req` 推向更高的 `payload_bytes_per_req`，同时减少 `memctrl.bytes_est_total` 与 tail。

---

## 1) 背景：我们现在卡在哪

### 1.1 当前主线事实（full_system_baseline）

完整系统主线参考：

- `exp_opt/2026-03-06-system-mainline-dram-snn-gas-storm-gcss-glide.md`
- `mainexp/experiments/2026-03-08_full_system_baseline_ab_v1/`
  - `runs/full_system_baseline/20260308-003632/effective_config.json` 显示 `memory_system=memhierarchy_per_pe`

在该口径下，关键 memory 指标（示例引用自 `exp_opt/2026-03-08-tide-memory-noc-design.md` 的 baseline 摘要）：

- `memhierarchy.memctrl.req_total ~ 150k`
- `gas.memctrl_payload_utilization ~ 0.316`
- `gas.payload_bytes_per_memctrl_req_avg ~ 20B`
- `gas.memctrl_traffic_amplification ~ 3.16x`

**含义**：我们已经把 NoC 的“包复制”压住了（STORM），但 memory side 仍然存在结构性浪费：以 64B cacheline 语义服务时，平均每次只消费约 20B 的真实权重 payload。

### 1.2 为什么“再做 edge 重排”不稳

已验证的反证来自 CHORD/PRISM/naive_tass 等路线：当协同机制把 issue 顺序拉回 token/arrival/细粒度重排时，很容易打散 `GCSS-GLIDE` 已建立的物理局部性，导致 `unique_line_count/overfetch/avg_read_latency` 回退，端到端不稳。

因此 SYNLINE 的约束是：

1. 不改 GAS 语义（Gather/Apply/Scatter 与 strict retire 口径不变）。
2. 不做 arrival/token 级“全局重排”。
3. 只改变 **“谁发起 DRAM line、如何共享 DRAM line 的返回数据”** 这一层。

---

## 2) 核心洞察：做“对称多播”

### 2.1 对称性

在 DRAM-based SNN 中，最痛的放大有两类：

1. NoC：同一 pre-spike 的 fanout 导致复制放大（STORM 已解决大头）
2. DRAM：同一 cacheline 中只有少量 4B weight 被用到，且同一 line 可能被多个目的 core 以“不同小读”的形式重复触发

SYNLINE 把 DRAM 侧的服务单位提升为：

- **Cacheline（64B）作为共享资源**

把“共享点”从 core-local（每个 core 各读各的）前移到一个 **共享的 block/cluster 级硬件单元**，用 **line 去重 + 本地 fanout** 来压制放大。

### 2.2 为什么这是硬件点，而不是算法 tweak

SYNLINE 不是“排序一下 edge”、不是“换个 hash”：

- 它引入明确可流片的结构：`MSHR + line buffer SRAM + local fabric + deterministic arbiter`
- 它改变 memory path 的“物理服务粒度”：从 core 私有读，变成 cluster 共享 line 服务

这与主流 neuromorphic 芯片的常见做法（synapse SRAM on-core / tile-local memory / multicast NoC）形成互补：我们的权重常驻 DRAM，必须面对 cacheline 语义；SYNLINE 把这一点变成可以写论文的“结构性机制”。

### 2.3 相关架构借鉴（用于“可流片 plausibility”叙事）

SYNLINE 的设计叙事可以明确对齐两类常见 neuromorphic/MPSoC 选择：

- **事件/多播网络是常态**：大量 SNN 芯片都把 spike 作为 event 在片上网络传播，并对 multicast 友好（这对应我们 STORM 的数据面主线）。SYNLINE 的关键点是把这种“多消费者共享”的理念延伸到 memory-side 的 cacheline 资源上。
- **cluster 共享外部存储接口是常见形态**：不少系统以 cluster/tile 为粒度共享外部存储（例如一个 cluster 共享 SDRAM/DRAM 控制器，core 侧有小 SRAM/TCM）。这为我们在 `SYNLINE-BLOCK` 中采用 “block-shared DRAM slice + cluster-local line service” 提供了自然的硬件落点。
- **与 Loihi/SpiNNaker 等的差异与互补**：它们更常见的做法是把 synapse/state 强依赖片上 SRAM（从而避免 DRAM cacheline overfetch）；而我们的目标规模是 `10M-100M` 神经元级别、权重常驻 DRAM，因此必须显式面对并优化 cacheline 语义下的放大。SYNLINE 正是围绕这一差异点提出的 memory-side 数据面机制。

---

## 3) 机制总览：SynLine Engine（SLE）

### 3.1 新硬件单元：SLE（SynLine Engine）

SLE 建议以 “cluster” 为域实例化（见 4.1），职责是：

1. 接收来自多个 cores 的 **subline 请求**（本质是 “我需要 line 内某个 4B weight”）
2. 将请求归一化为 `line_addr = align_down(addr, 64B)`
3. 以 `line_addr` 为 key 做 **MSHR 去重**（N 个 subline -> 1 个 line 读）
4. DRAM 返回后在 cluster 内 **本地多播/分发**（一条 line fanout 给多个 cores）
5. core 侧仍按原有 **strict retire** 提交，不改变数值语义

### 3.2 与现有严格语义的接口边界

我们严格复用已有的确定性退役护栏（WeightMemorySubsystem 已落地）：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
  - `registerEdgeRetire_()`：为每条 edge 分配 `retire_seq`
  - `setEdgeRetireReady_(seq, weight, src)`：接收 weight
  - `tryRetireEdges_()`：按策略（默认 global in-order）提交 `orch_.acc_update(post_local, delta)`

SLE 只需要把 weight 回填给对应 core 的 `seq`，即可保持严格语义完全一致。

---

## 4) 关键落地点：协同域与 memory 物理前提

### 4.1 Cluster 选择（必须明确）

由于当前 full_system_baseline 使用 `memory_system=memhierarchy_per_pe`（每个 PE 一套 MemController），SYNLINE 有两个可选协同域：

1. **SYNLINE-PE（低风险/起步）**
   - 域：单个 MultiCorePE 内的 `num_cores_per_pe`（例如 20 cores）
   - DRAM：天然同一个 PE MemController
   - 价值：验证 “line 去重 + 本地 fanout + line buffer” 的硬件闭环

2. **SYNLINE-BLOCK（2x2 block，目标域）**
   - 域：与 STORM 对齐的 `2x2 destination block`（4 个 PEs，约 80 cores）
   - 关键挑战：baseline 是 per-PE MemController，跨 PE 没有共享物理 line
   - 解决方式（二选一）：
     - **A) Block-shared DRAM slice（推荐叙事）**：一个 2x2 block 共享一个 DRAM slice（等价于“cluster-level memory”，类似很多 neuromorphic/MPSoC 的 cluster 共享外部存储接口）
     - **B) BlockMemHub（工程可实现）**：保持 4 个 MemController，但引入 block-level hub，SLE 作为代理发起到任意 controller 的 line 读；同时离线把 block weights 以 line 粒度 striping 到 4 个 controller 的地址空间

本方案文档以 **SYNLINE-BLOCK + A** 为主（最清晰的体系结构故事），并保留 **B** 作为后续增强。

---

## 5) 离线数据格式：GCSS-SYNLINE（dstblock/cluster layout）

### 5.1 新 weight mode（强隔离）

新增实验性 weight mode（命名建议）：

- `synapse_weight_mode=gcss_valueonly_dstblock_synline_v1`

与现有主线完全隔离，不改默认行为；仅当：

- `MESH_EXPERIMENTAL_ENABLE=1`
- 且 `synapse_weight_mode` 显式设置为该值

才启用。

### 5.2 输出文件布局（每个 cluster 一套）

以 `2x2 block` 为例，输出建议（每 block 一套）：

- `block_originXX.synline.bin`：values（float32，DRAM 常驻）
- `block_originXX.synline.idx.bin`：index（SRAM 常驻或可缓存）
- `block_originXX.synline.meta.json`：统计与追溯（values/index bytes、segments 分布、预期 payload 上限）
- `manifest.json`：全局摘要（与现有 gcssplp/idx2 一致）

> 说明：避免 naive_tass 的“为 loader 兼容而在每个 core/PE DRAM 中复制一份 block 文件”的陷阱。SYNLINE 的目标是 **shared line**，复制会把收益直接抹平。

### 5.3 核心索引结构（pre-major + 稀疏 segment descriptor）

运行时查询输入（每条 edge 已有）：

- `(pre_global, pre_rank)`，且 pre_rank 是该 core 内 `post_local` 升序的 rank（见 `SnnWorkload::expandPreGlobalToWindowEdgesFast_()` 已实现）

索引需回答：

- 该 `pre_global` 在 cluster 的 values blob 的 `pre_base`
- 对于当前 `core_id_in_cluster`，该 pre 的 segment 是否存在、segment 起点 `seg_base`、segment 长度 `seg_len`
- 最终 `addr = values_base_addr + 4 * (seg_base + pre_rank)`

**推荐编码**：

1. `pre_id = row_mphf(pre_global)`（复用 GLIDE/idx2 的 bucket+pilot 思路）
2. `pre_base[pre_id]`（uint32，单位：float index）
3. `pre_seg_off[pre_id]`（uint32，指向 `seg_desc` pool 的起始 offset）
4. `seg_desc pool`：可变长数组，每个 pre 一个短 list
   - `nseg`（uint8）
   - `nseg` 个条目：`{core_id_u8, seg_delta_u16_or_u32, seg_len_u16}`

其中：

- `seg_delta` 是相对 `pre_base` 的 delta（单位 float index），由离线 prefix-sum 得到
- 平均 `nseg` 期望很小（参考 `TASS-LF` 可行性分析里 `avg_cores_per_active_pre` 量级），因此线性扫描 `nseg` 是可接受的硬件成本

### 5.4 values 布局（让 line 真正可共享）

对每个 `pre_global`：

1. 收集 cluster 内所有 cores 的 edges（仍以每 core 的 post_local 升序为准）
2. 形成多个 segment（每 segment 对应一个 core，包含该 core 的 weights 列表）
3. 按 `core_id_in_cluster` 升序串接 segment 写入 values

这样，同一个 pre 在 cluster 内多个 core 的 weights 会自然落在同一小段连续地址中，**更容易形成跨 core 的 line 共享**。

---

## 6) 运行时接入：不改语义，只改“谁发起 line”

### 6.1 接入点原则

SYNLINE 不应改动：

- `SnnWorkload` 的 spike 门控语义
- GAS 的窗口推进语义
- `WeightMemorySubsystem` 的 retire 语义

SYNLINE 只替换 WMS 的 “dense read issue backend”：

- baseline：WMS -> `IMemoryAccess::read(4B)` -> GatherBufferIF(VLF) -> MemController
- SYNLINE：WMS -> SLE(subline) -> SLE(line read 64B) -> MemController -> SLE(fanout) -> WMS(setEdgeRetireReady)

### 6.2 事件接口（SST 可建模，避免事件爆炸）

为避免 MPI 下每条 edge 一个事件导致 wallclock 爆炸，SYNLINE 强制 bundle：

- `SynLineReqBundle`：每 core 每窗口最多发送 1 个（或少量）bundle
  - entries：`{seq, pre_global, pre_rank, count}`（count 通常 1）
- SLE 收到后完成 address translation 与 line 去重
- `SynLineRespBundle`：SLE 按 core 聚合回包
  - entries：`{seq, weight_f32}`

### 6.3 确定性与公平性（硬件仲裁规则）

SLE 的 line issue 必须 deterministic：

- 统一 key：`(bank_id, row_id, line_addr)` 或至少 `(line_addr)`
- 排序：升序 + stable tie-break（例如 arrival order 的自增 ticket）
- 多 bank：可选 `bank_rr`，但 tie-break 固定

注意：即便 SLE 在 line 层面乱序返回，WMS 仍可用 `edge_retire_` 机制保证提交序一致。

---

## 7) 新增硬件结构（在 SYNLINE 下继续“挖潜”）

SYNLINE 的基础版（MSHR+fanout）已经是体系结构贡献；但为了进一步释放潜力，建议在 SLE 内增加两类硬件结构：

### 7.1 Line Buffer SRAM（cluster-local）

作用：

- 把 “短时间内重复触发的 line” 从 DRAM 侧变成 cluster-local hit
- 特别有利于 `seed-only steps>=2` 或真实多步（相同 pre/邻近 pre 在相邻 step 重复活跃）

结构：

- 小容量（例如 64~512 lines）
- 直接映射或 2-way set-assoc
- 以 `line_addr` 为 tag

统计闭环：

- `synline.line_buffer_hits_total` 必须显著非零，并且 `memctrl.bytes_est_total` 下降

### 7.2 Beat-level Local Fabric（16B/beat）

作用：

- DRAM 返回 64B line 后，cluster 内分发不应再复制 64B 多份
- 使用 beat-level demux：每 core 只 latch 自己需要的 4B 或 16B beat

SST 建模建议：

- `local_fabric_bytes_per_cycle`（例如 16B/cycle）
- `local_fabric_header_cycles`（固定 1~2 cycles）

### 7.3 Spike-aware MSHR Prefill（可选，后续）

利用 STORM 的 `SpikeTileKey`（目的 block 已聚合 pre 集合）：

- 在 Apply 前（或 Gather 后半段）提前为这些 pre 建立 MSHR/line 计划
- 不做 speculative DRAM issue（先只占位），等 WMS bundle 来后立即 issue

这是把 STORM “已知的 active-pre 集合”变成 memory-side “更低调度开销”的手段，属于 NoC×Memory 协同加分项。

---

## 8) 统计项（必须补齐论文证据链）

### 8.1 SYNLINE 专属（核心）

建议新增（run totals + per-window samples 可选）：

- `synline.subreq_total`：core->SLE 的 subline 条目数（应与 baseline 边数一致）
- `synline.unique_lines_total`：SLE 实际向 DRAM 发起的 unique line 数
- `synline.mshr_hits_total / synline.mshr_misses_total`
- `synline.line_buffer_hits_total`
- `synline.line_fanout_sum / synline.line_fanout_max`（返回 line 被多少 subreq 共享）
- `synline.local_fabric_bytes_total / synline.local_fabric_cycles_total`

派生指标（summary 里算）：

- `synline.payload_utilization = (subreq_total * 4) / (unique_lines_total * 64)`
- `synline.traffic_amplification = (unique_lines_total * 64) / (subreq_total * 4)`

### 8.2 与现有主线指标的对齐

闭环时必须同时报告：

- `memhierarchy.memctrl.req_total / bytes_est_total`
- `gas.memctrl_payload_utilization`
- `gas.memctrl_traffic_amplification`
- `gas.unique_line_count_total / gas.overfetch_bytes_total`
- `ramulator2.avg_read_latency_0_avg`（与 tail 指标）
- `validation.log`（fail=0，warn 口径不新增）

---

## 9) 闭环实验计划（mainexp 承载）

### 9.1 固定口径（不引入额外漂移）

- NoC：`multicast_mesh`（STORM + MulticastRouter）
- Memory：`ramulator2`（DDR5 cfg）
- Apply：`apply_issue_policy=order`
- 数据集：`4x4 bcsr10k step1`；协同验证可用 `seed-only steps=2` 作为实验口径

### 9.2 case 矩阵（至少 4 组）

1. `full_system_baseline`：当前主线
2. `synline_pe_only`：SLE 域=PE（不引入 dstblock layout），验证“纯硬件去重/line buffer”是否已经带来收益
3. `synline_block_layout_only`：引入 dstblock_synline layout，但 SLE 关闭（负对照，证明布局本身不够）
4. `synline_block_full`：dstblock_synline layout + SLE（目标最大收益）

消融（可选）：

- `synline_block_full_nobuf`：关 line buffer，看收益来源
- `synline_block_full_nobeat`：关 beat-level demux，看 local fabric 开销

### 9.3 预期证据链

在 `synline_block_full` 中希望观察到：

- `synline.unique_lines_total` 明显下降（相对 baseline 的 line-level 事务数）
- `memctrl.bytes_est_total` 与 `req_total` 同向下降
- `gas.memctrl_payload_utilization` 上升（或 `traffic_amplification` 下降）
- `sim_time_actual_ns` 下降（且 validation 不变）

若出现“memctrl bytes 降但 sim_time 不降”：

- 用 `synline.local_fabric_cycles_total` + NoC tail 指标证明开销搬家，再迭代 local fabric 模型/带宽

---

## 10) 落地位置建议（代码组织）

建议新增目录（强隔离）：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/synline/`
  - `SynLineEngine.{h,cc}`
  - `SynLineEvents.h`（bundle events）
- `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstblock_synline_v1.py`（离线生成器）

接线点（不改现有默认路径）：

- `MultiCorePE` 装配时可选创建 SLE（按 domain=PE 或 domain=block）
- `WeightMemorySubsystem` 只在 `synapse_weight_mode==...synline...` 时走 SLE backend

---

## 11) 风险与护栏

- **MPI wallclock 风险**：强制 bundle 事件；禁止 per-edge event 洪泛。
- **语义风险**：所有 weight 回填必须走 `setEdgeRetireReady_(seq, weight, src)`；严禁在 SLE 内直接触发 `acc_update`。
- **复制风险（踩雷点）**：禁止像 naive_tass 那样把 block 文件复制到每个 core 的 DRAM region；否则 “shared line” 物理前提不存在。
- **回归风险**：默认关闭；必须 `MESH_EXPERIMENTAL_ENABLE=1` 才能启用 synline mode。

---

## 12) 命名与论文表达（建议）

建议论文中把贡献组织成一个“对称多播 + DRAM 语义”故事线：

- `STORM`：spike multicast（NoC）
- `GCSS-GLIDE`：values-only + locality-preserving index/layout（memory）
- `SYNLINE`：synapse cacheline multicast（memory-side data plane）

SYNLINE 的核心 novelty 可用一句话表达：

> “We treat DRAM cachelines as a first-class, multicastable synaptic resource, enabling symmetric multicast on both the spike (NoC) and synapse (memory) paths without changing GAS semantics.”
