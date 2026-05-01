# GAS（内存侧）优化探索汇总（原理 / 实现位置 / 证据）

> 范围：本文档归档 **基于 GAS 的内存侧探索优化**（段构建合并 + 正确性/可观测性硬化），用于论文级复现实验与讨论。
>
> 更新（2026-02-28）：`cmd_aware_v1 / bank_rr_row_sticky_age / dram_aware_v1 / synapse_sram / step_activation_pre_global_sample` 已按 9.5 结论做代码级物理移除；本文相关内容仅保留为历史实验记录。
>
> 更新（2026-03-02）：`GCSS value-only (dst_core)` 与 `GCSSIDX2 (Row-MPHF + row-major values)` 已完成隔离落地与闭环实验；并新增 `synapse.index_cost` 统计用于量化 “SRAM 常驻索引” 成本（见 §11）。
>
> 重要边界（避免口径漂移）：
> - 默认语义以 **cacheline** 为主（贴近 `memHierarchy`）；row-streaming/DMA 语义只允许显式 opt-in。
> - 本文所有“探索性优化”均需 **严格隔离**：默认关闭，仅通过脚本/配置显式开启（通常需要 `MESH_EXPERIMENTAL_ENABLE=1`）。
> - **内存优化的对比实验统一承载到 `memop/experiments/`**：每个实验必须有 `cases.json` + `snapshot/compare.tsv`（必要时补充其它 snapshot 表），并把 `outputs_large/.../run_dir` 仅作为 `cases.json` 的指针，不直接用 run_dir 路径写论文证据。
> - NoC 多播与 global credit 路线已单独归档：`exp_opt/2026-02-26-noc-multicast-and-global-credit.md`（本文仅做引用与边界说明）。

---

## 0. 速览（机制 → 文件 → 开关 → 证据）

| 机制 | 核心想法 | 关键实现位置 | 关键开关（默认） | 代表性证据 |
| --- | --- | --- | --- | --- |
| **cacheline 分片下发（正确性硬化）** | 避免一次 GetS `size>cacheline` 导致 memHierarchy.Cache 组装 payload 越界/读脏，确保确定性 | `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`（`issueGranuleBufBudget_()`） | 总是启用（主线语义） | dense/bcsr 相关回归中消除“发放归零/非确定性”类问题（见代码注释与 validator） |
| **Apply 发射策略探索（bank_rr/cmd_aware/dram_aware）** | 历史探索分支：通过不同发射顺序提升 row-hit/并行度 | （历史）`GatherBufferIF` 旧分支 | **已物理移除（2026-02-28）** | 保留历史对比结论，不再作为可运行主线 |
| **段构建：粗/细合并（gap merge + row-window）** | 行内（bank,row）分桶后按 addr 扫描：小洞吸收（k/Lmax）；或 row-window 字节阈值触发吸洞 | `GatherBufferIF.cc`（`buildGranulesWithGapMergeBuf_()`） | `gap_merge_k_bytes/row_window_bytes/row_window_timeout_ns`（默认 `k=0,rowwin=0`） | 过大 k/rowwin 会导致 overfetch（见 §2.2） |
| **段构建：DRAM cmd-cost 护栏（deterministic veto）** | 用 `{t_hit,t_miss,line}` 推导“值得吸洞”的最大 gap（k），在段构建时 veto 病态吸洞（行内、不跨 row） | `components/gather/apply/DramCmdCostMergeModel.h` + `GatherBufferIF.cc` | `dram_cmd_cost_merge_enable=0` | dense microbench A/B：`memctrl_bytes 1,886,912→135,040`（§2.4.1）+ bcsr10k（semseal）A/B：`memctrl_bytes 192,534,208→126,830,464` 且 `overfetch 63,037,952→0`（§2.4.2） |
| **Weights-L0：BCSR inflight coalescing（colidx/blockdata）** | 在窗口内把“多 edge → 同一 BCSR 索引/块读”合并为一次真实读，并统一唤醒 waiters（降低真实 DRAM 事务数/字节） | `services/synapse/weights/WeightMemorySubsystem.{h,cc}` | `bcsr_colidx_inflight_coalesce_enable=1` + `bcsr_block_inflight_coalesce_enable=1` | semseal 口径 bcsr10k step1：`memctrl_bytes_est_total≈0.240×`（§4.5） |
| **Weights：BCSR blockdata 行切片读取（row_cacheline）** | 当 `br>1` 时，将一次块读从 `br*bc` 降为 `1*bc`（cacheline 语义下减少 overfetch） | `WeightMemorySubsystem.cc`（`bcsr_block_fetch_mode`） | `bcsr_block_fetch_mode=full_block` | br=1 数据集 no-op；br>1 A/B 见 `TECH_PROGRESS.md` 的 AB isolation matrix（后续将补 semseal/memop 快照） |
| **BCSR 物理布局：rowpack_v1（layout transform）** | 改变 colidx/blockdata 的物理布局与 stride（每 block_row 紧凑/定长），以改善行内局部性与合并友好性 | `services/synapse/common/BcsrMeta.h` + `services/synapse/route/BcsrRouteBuilder.cc` | 由数据集 `.meta.json` 的 `layout_mode=rowpack_v1` 决定 | bcsr10k step1（semseal, br=1）：`memctrl_bytes_est_total≈0.998×`（几乎无主效应；见 §4.6 的 2×2） |
| **Weights 格式：GCSS value-only（dst_core resident）** | 用 values-only stream 替代 BCSR 的 `colidx+blockdata` meta 读，把权重读源从 “meta 主导” 迁移到 “value 主导” | `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore.py` + `services/synapse/weights/WeightMemorySubsystem` | `synapse_weight_mode=gcss_valueonly_dstcore` + `MESH_GCSS_DIR` | bcsr10k step1（semseal）对比：`memctrl_bytes_est_total≈0.616×` 且 `synapse.read_source.meta_bytes_share: 1→0`（§11.3） |
| **Weights 索引：GCSSIDX2（Row-MPHF，index<=values/10）** | 在“不发生集合外 lookup”的系统约束下，用 row-MPHF 把常驻 SRAM 的 GCSS 索引压到 `values/10` 量级（few bits/edge） | `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_idx2_rowmphf.py` + `services/synapse/weights/GcssIndexRowMphf.h` | `synapse_weight_mode=gcss_valueonly_dstcore_idx2` + `MESH_GCSS2_DIR`（需 `MESH_EXPERIMENTAL_ENABLE=1`） | bcsr10k step1（semseal）：`index_to_values_ratio=0.099`（`2.262→0.099`），`index_bits_per_edge=3.18`（§11.3） |
| **dense weights_phys：PhysV1（dense layout）** | 将 dense blob 做 DRAM row-aware 物理布局（避免 straddle 放大/无效读） | `tools/weights_phys/gen_dense_phys_v1.py` + `WeightMemorySubsystem` dense phys 寻址 | `dense_layout_mode=row_major` | 500×500 dense：`memctrl.bytes_est_total -41%`（`TECH_PROGRESS.md`，后续将补 memop 快照） |
| **dense microbench：pre-global 选源（方法学修复）** | dense 默认 pre-local 选源会退化成单 bank；用 pre-global 均匀映射让 Apply 策略“看见多 bank 候选” | `MultiCorePE/StepActivationSubsystem`（入口由脚本注入） | `MESH_STEP_ACTIVATION_PRE_GLOBAL_SAMPLE=0` | `TECH_PROGRESS.md`：credit=1 退化定位与修复（§4.3） |

---

## 1. GAS 内存侧“基线语义”回顾（用于统一口径）

### 1.1 三阶段（Gather / Apply / Scatter）与“内存侧契约”

GAS 在内存侧的核心职责是：把上游产生的权重读（逻辑上可能是许多小读）在 Apply 阶段进行 **构段/去重/限流/调度**，以减少下游 memHierarchy 的事务压力，同时保证功能语义不变。

关键组件（单点入口）：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.{h,cc}`：GAS-aware StandardMem 前端 + SRAM 缓存 + Apply 调度

### 1.2 统计字段的物理含义（避免“上层 bytes vs memctrl bytes”混算）

在 `essential_summary_mesh.json`（由 `sst_dram_si/tools/compute_essential_summary_mesh.py` 生成）中：

- `gas.payload_bytes_total`：上游子请求 payload 的累计（**有效字节**，不含洞）
- `gas.unique_bytes_total`：Apply 构段后，下游真正覆盖的“唯一段字节”（**包含洞/overfetch**）
- `gas.overfetch_bytes_total = unique - payload - net_unique_minus_payload`：洞/补洞带来的额外覆盖（**overfetch**）
- `memhierarchy.memctrl.bytes_est_total`：下游 MemController 收到的 cacheline 事务字节估计（最接近 off-chip traffic 的主口径）
- `memory.memory_requests / memory.memory_bytes`：从 SnnDL 侧统计的“权重域发起的真实读”（更贴近 Weights/WMS 的发起语义，常用于验证 L0 是否真的减少了真实事务）

经验规则：
- 当 merge/构段在 cacheline 语义下工作良好时，`gas.unique_bytes_total` 与 `memctrl.bytes_est_total` 应该同量级；
- 若出现 `payload_bytes_total` 很小但 `memctrl.bytes_est_total` 巨大，优先排查：段构建是否被“吸洞/粗合并”抬升到了大粒度（overfetch）。

### 1.3 关键参数族（把“优化点”与“口径”固定在可复现实参上）

GAS 内存侧主要由两类参数控制：

**(A) 段构建/合并（决定请求覆盖范围 → 决定 memctrl traffic）**
- `merge_policy`：`none|cacheline|row|auto`（主线默认 `cacheline`）
- `gap_merge_enable` + `gap_merge_k_bytes`（细合并阈值 k；0=禁用）
- `burst_bytes_max`（Lmax）
- `row_window_enable` + `row_window_bytes` + `row_window_timeout_ns`（粗合并/超时触发）
- `row_bytes_guess`（决定 `rowIndex(addr)` 的“行内范围”）

**(B) Apply 发射/调度（不改变集合，只改变发射顺序/并发 → 影响 wallclock/尾部）**
- `apply_issue_policy`：`order`
- `apply_frags_per_issue`（每轮最多发多少个 cacheline 分片；0=不限）
- `apply_bank_credit`（每 bank 同时 active granule 上限；0=不限）
- `apply_age_fair_ns`（age-fair 强制发射阈值；0=禁用）

方法学强依赖项（dense microbench/实验隔离常用）：
- `defer_issue_until_apply`（让 staged reads 统一在 Apply 发射，以便 apply scheduler 生效；脚本常用 `MESH_GAS_FORCE_DEFER=1` 注入）
- `MESH_DENSE_STRICT_CACHELINE=0`（dense strict 会绕开 staged-scheduler；做 Apply 调度/合并实验时需显式禁用）

---

## 2. 段构建（buildGranulesWithGapMergeBuf_）探索：粗/细合并与“cmd-cost 护栏”

### 2.1 段构建的事实实现（行内、不跨 row 的 bucketing）

实现位置：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`：`buildGranulesWithGapMergeBuf_()`（约 `#L1917` 起）

事实流程（与论文表述对齐）：
1. 对 staged reads 做 `(bank,rowIndex)` 分组（`key=(bank<<32)|rowIndex(addr)`）
2. 每组内按 `addr` 排序
3. 线性扫描构段：
   - 重叠/相邻：直接扩展
   - **细合并**（gap-merge）：当 `gap<=k` 且 `new_len<=Lmax`（并受 overfetch budget 可选约束）则吸洞扩段
   - **粗合并**（row-window）：当 “当前段 payload_sum + 新读 payload” 未超过 `row_window_bytes` 且 `new_len<=Lmax`，允许吸收更大的 gap（同样可受 budget 约束）
   - timeout：若等待超阈值，提前 flush

关键参数（来自 `effective_config.json:gas.*`）：
- `gap_merge_k_bytes_config`（k）
- `burst_bytes_max_config`（Lmax）
- `row_window_bytes`、`row_window_timeout_ns`
- `row_bytes_guess`（用于 `rowIndex(addr)`；决定“行内”的范围）

### 2.1.1 bank/row 相关的“精确映射”来源（为什么会影响 row-hit/BLP）

段构建与 Apply 发射均可能依赖 `(bank,rowIndex)`：
- `bank_bits/bank_shift`：显式地址映射
- `bank_auto_enable=1`：当 `bank_bits=0` 且 staged reads 足够多时，`GatherBufferIF` 会在段构建前做一次启发式探测，选择一个让“distinct banks”落在 `[min_banks,max_banks]` 的 `(bits,shift)` 组合（用于把 `bank_row` 维度“打开”）

实现位置：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`：`buildGranulesWithGapMergeBuf_()`（bank auto 探测 + `bankIndex()/rowIndex()`）

注意：bank-auto 是启发式（deterministic 但依赖样本集合）；论文主结论建议用 **显式 mapping**（固定 `bank_bits/bank_shift + dram_row_bytes`）并把实参写进 `effective_config.json`。

### 2.2 已确认风险：k/row-window 过大时，稀疏访问会被“吸洞”成大段 → overfetch 暴涨

典型诱因（dense 场景最明显）：
- 逻辑 weight row 的跨行步长接近 `~2000B`；
- 如果 `gap_merge_k_bytes` 取 `2048B`（略大于步长），细合并会把跨行洞吸收，形成覆盖多个逻辑行的大段；
- row-window 进一步允许“大洞也吸”，更容易触发病态 overfetch。

这不是“统计脚本算错”，而是段构建粒度被配置抬升后的真实覆盖范围变化。

### 2.2.1 DRAM-aware v1（可选）：窗口级 k/budget 推导（不改语义，属于探索）

`apply_issue_policy=dram_aware_v1` 的“DRAM-aware”当前主要作用在 **段构建参数的窗口级推导**：
- 在进入 `buildGranulesWithGapMergeBuf_()` 时先估计本窗口访问摘要（payload/unique_line_count 等）
- 通过 `DramAwareTuner` 推导本窗口的 `gap_k_bytes_eff` 与 `overfetch_budget_left`

实现位置：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/gather/apply/DramAwareModel.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/gather/apply/DramAwareTuner.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`：`buildGranulesWithGapMergeBuf_()` 的 `dram_aware` 分支

关键参数：
- `dram_aware_k_policy`：`fixed|cost_budgeted|density_budgeted`
- `dram_row_miss_penalty_cycles`、`dram_overfetch_budget_bytes`
- `dram_aware_enable_row_window`（允许 DRAM-aware 自动启用 row-window；默认 0）

备注：该路径包含启发式（依赖窗口摘要），不属于“纯 deterministic（仅由配置+地址集决定）”的论文主张；建议作为消融/附录探索项呈现。

### 2.3 新机制：DRAM cmd-cost 合并护栏（deterministic，行内、不跨 row，默认关闭）

目的：**不改变 GAS 的三阶段语义**，仅在“段构建是否吸洞”这个点上增加一个 deterministic veto，阻止明显不划算的 overfetch。

实现位置：
- 模型：`sst_workspace/sst-elements/src/sst/elements/SnnDL/components/gather/apply/DramCmdCostMergeModel.h`
- 接入：`sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`（`buildGranulesWithGapMergeBuf_()` 内）

模型（纯确定，不自适应/不扫参）：
- 视“吸洞的成本”为额外读 `extra_lines` 个 cacheline（row-hit 服务时间 `t_hit`）
- 视“不吸洞/拆段的收益”为避免一次 row-miss 代价（`t_miss - t_hit`）
- 推导阈值：
  - `k_cmd = floor((t_miss - t_hit)/t_hit) * line_bytes`
  - 若 `gap_bytes > k_cmd` 则 veto 吸洞（对 row-window 的大洞吸收也同样 veto）

参数与默认值：
- `dram_cmd_cost_merge_enable`（默认 `0`）
- `dram_cmd_t_row_hit_ns`（默认 `30`）
- `dram_cmd_t_row_miss_ns`（默认 `120`）

### 2.4 实验结果（已复现：dense microbench + bcsr10k 主链路）

#### 2.4.1 dense microbench（4x4，step=1，L1=0，A/B）

运行入口：
- `sst_dram_si/tools/run_dense_microbench_4x4_exec_mode_compare_with_time.sh`

目录（同 seed / 同 payload；byte-exact PASS）：
- A（护栏 OFF）：`sst_dram_si/outputs_large/paper2/dense_microbench_4x4_dram_cmd_cost_merge_guardrail_ab/gas/l1_0/20260227-015634-467995008/`
- B（护栏 ON）：`sst_dram_si/outputs_large/paper2/dense_microbench_4x4_dram_cmd_cost_merge_guardrail_ab/gas/l1_0/20260227-015656-278058915/`

关键结果（同 `payload_bytes_total=168,960`）：
- A（OFF）：`unique_bytes_total=1,885,888`，`overfetch_bytes_total=1,716,928`，`memctrl.bytes_est_total=1,886,912`，`apply_ns_avg≈3,211.38`，`sim_time_actual_ns=4,689`
- B（ON）：`unique_bytes_total=134,016`，`overfetch_bytes_total=0`，`memctrl.bytes_est_total=135,040`，`apply_ns_avg≈272.56`，`sim_time_actual_ns=1,388`

结论：护栏在段构建阶段直接 veto 病态吸洞，可把 overfetch 压到 0，并显著降低 memctrl traffic 与 Apply 时间。

#### 2.4.2 bcsr10k 主链路（4x4，step=1，L1=0，A/B）

> 重要说明（口径）：本节同时给出 **pre-sealsem（历史对照）** 与 **semseal（论文口径）** 两组结果。
>
> - pre-sealsem：`window_read_budget` 仍会截断窗口覆盖度，容易对“减少真实读数”的优化不公平；
> - semseal：见 §4.4，`window_read_budget` 不再作为 correctness 门槛，A/B 可比性更强；
> - 论文级主结论以 **semseal 复测结果** 为准。

运行入口（严格对齐口径：strict-step + freeze）：
- `sst_dram_si/tools/run_mesh_bcsr10k_freeze_strictstep_exec_mode_l1_sweep_with_time.sh`

semseal（论文口径）目录（A/B）：
- A（OFF）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4_bcsr10k_freeze_step1_dram_cmd_cost_guardrail_ab_semseal_v1/gas/l1_0/frac_0p03/20260228-070612-464221066/`
- B（ON）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4_bcsr10k_freeze_step1_dram_cmd_cost_guardrail_ab_semseal_v1/gas/l1_0/frac_0p03/20260228-071257-370875612/`

semseal 关键结果（同 `gas_payload_bytes_total≈129,495,xxx`）：
- A（OFF）：`memctrl.bytes_est_total=192,534,208`，`overfetch_bytes_total=63,037,952`，`sim_time_actual_ns=1,081,197`
- B（ON）：`memctrl.bytes_est_total=126,830,464 (0.6587×)`，`overfetch_bytes_total=0`，`sim_time_actual_ns=1,022,393 (0.9456×)`

证据（memop 快照）：
- `memop/experiments/2026-02-27_dram_cmd_cost_guardrail_bcsr10k_step1_ab_semseal_v1/snapshot/compare.tsv`

pre-sealsem（历史对照）目录（A/B）：
- A（OFF）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4_bcsr10k_freeze_step1_dram_cmd_cost_guardrail_ab/gas/l1_0/frac_0p03/20260227-020953-259162204/`
- B（ON）：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4_bcsr10k_freeze_step1_dram_cmd_cost_guardrail_ab/gas/l1_0/frac_0p03/20260227-021221-968649040/`

---

## 3. Apply 发射/调度探索：bank_rr 与 cmd_aware_v1（以及 credit 交互）

### 3.1 策略入口与 fail-fast（避免“静默 fallback”导致口径漂移）

实现位置：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`：`parseApplyIssuePolicy()`（约 `#L836`）

可用策略（其它字符串将 `fatal`）：
- `order`
- `bank_rr_row_sticky_age`
- `dram_aware_v1`
- `cmd_aware_v1`

### 3.2 cmd_aware_v1：简化命令代价模型（shadow bank busy / open-row）

实现位置：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.{h,cc}`

核心思想：
- 对每个 bank 的候选 granule 队列，lookahead `probe_depth` 个候选；
- 计算“若现在发它”的预计服务代价（row-hit vs row-miss、bank busy、bank-group busy、age fairness 强制等）；
- 选择最优候选发射，并维护 shadow 状态（open-row / busy-until）。

关键参数（见 `effective_config.json:gas.*`）：
- `apply_cmd_probe_depth`
- `apply_cmd_t_row_hit_ns`、`apply_cmd_t_row_miss_ns`
- `apply_cmd_miss_penalty_ns`
- `apply_cmd_enable_row_locality`
- `apply_cmd_enable_bank_busy`
- `apply_cmd_bank_groups`（若启用 bank-group busy）

### 3.3 实验结果（dense microbench 消融）：credit 限流会“吞掉策略差异”

#### 3.3.1 `apply_bank_credit=1` 时：策略差异不显著（被硬限流主导）

来源：`TECH_PROGRESS.md`（`[2026-02-24 13:44]`）
- 输出：`sst_dram_si/outputs_large/paper2/dense_microbench_4x4_cmd_aware_ablation/ddr5/frac_0p05/npc_1024/`
- 观测：
  - `bank_rr_baseline` 与 `cmd_full` 同 `sim_ns=1030927`（wallclock 层面未体现优势）
  - 但 `cmd_no_row_locality` 的 `apply_cmd_busy_wait_ns` 暴涨，说明机制敏感度正确可观测

解释：当 `apply_bank_credit=1` 时，每 bank 并发被压到近似串行，发射顺序难以改变整体吞吐上界。

#### 3.3.2 `apply_bank_credit=0` 时：cmd_aware_v1 在高并发下有效（2.884×）

来源：`TECH_PROGRESS.md`（`[2026-02-24 14:05]`）
- 输出：`sst_dram_si/outputs_large/paper2/dense_microbench_4x4_cmd_aware_ablation_credit0/ddr5/frac_0p05/npc_1024/ablation_summary.tsv`
- 关键结果：
  - `bank_rr_baseline`: `sim_ns=537836`
  - `cmd_full`: `sim_ns=186459`（相对 bank_rr `2.884×`）
  - `cmd_no_row_locality`: `sim_ns=228235`（验证 row-locality 是主要贡献项）

---

## 4. 方法学/可复现性硬化（与 GAS 优化强相关）

### 4.1 “cacheline 作为默认语义”的模板化落地

mesh_template 默认：
- `sst_dram_si/mesh_template/legacy_defaults.py`
  - `_GAS_MERGE_POLICY="cacheline"`
  - `_GAS_GAP_K_BYTES=0`（默认禁用补洞）
  - `_GAS_ROW_WINDOW_BYTES=0`

这使得“默认 GAS”不会因为不慎开启粗/细合并而引入 overfetch（探索需要显式启用）。

### 4.2 strict-step（禁用步内级联）与公平对比

目的：在 `exec_mode=gas` 与 `exec_mode=naive_raw` 的对比中，强制两者共享“无步内级联”的 step 语义，避免统计口径漂移。

实现位置（脚本侧，仅用于实验）：
- `sst_dram_si/mesh_template/build.py`：当 `MESH_GAS_STEP_SEQ_GATE_ENABLE=1 && exec_mode==gas && max_steps>0` 时，向 PE 注入 `exec_mode="naive_raw"` 以打开 step_seq gating，但仍装配 GAS 核心（见注释块）
- runner：`sst_dram_si/tools/run_mesh_bcsr10k_freeze_strictstep_exec_mode_l1_sweep_with_time.sh`

### 4.3 dense microbench：pre-global 选源（避免“单 bank 退化”误判策略无效）

问题：dense 默认 pre-local 选源导致地址域极窄，在 `bank_shift=12` 的映射下退化为单 bank，使 `apply_bank_credit=1` 近似串行，掩盖调度策略差异。

修复（microbench-only，默认关闭）：
- `MESH_STEP_ACTIVATION_PRE_GLOBAL_SAMPLE=1` 使选源在 `0..max_global` 均匀映射，强制覆盖列域（跨 bank），用于验证 bank-aware/cmd-aware 策略。
- 证据与结果：见 `TECH_PROGRESS.md` 的 `2026-02-26 Dense microbench 4x4：... pre-global ...` 条目。

### 4.4 semseal：window_read_budget “语义封口”（避免 L0/优化造成口径漂移）

背景问题（已踩雷）：
- Weights 子系统内存在两类节流：
  - `max_outstanding_requests`：硬限流（inflight 过高必须 defer），它只影响并发与时序，不应改变“本窗口最终覆盖集合”；
  - `window_read_budget`：历史上既被用于观测（issued 计数），也被用于 **硬门槛**（budget 超限则直接不再发起读）。
- 在引入 L0（inflight coalescing）之后，“edge 数”与“真实读数”不再线性对应：L0 会让更多 edge 共享同一真实读。
- 若 `window_read_budget` 仍是硬门槛，则 L0 on/off 会因为 **真实读发放数不同** 而导致：
  - 本窗口覆盖集合不同（语义漂移）
  - NoC 包量/发放/神经元 firing 统计不同（实验不可比）

修复（semseal 的定义）：
- 将 `window_read_budget` 从 correctness 门槛降级为 **仅用于统计/提示**，只保留 `max_outstanding_requests` 作为硬门槛。
- 关键实现位置：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`：`tryIssueRead_()` 不再因 budget 超限返回 `DeferredBudget`（保留 `DeferredInflight`）
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`：`canIssueMoreReads_()` 不再按 budget 截断发放
- 效果：允许 L0 / 其它“减少真实读数”的优化在 **不改变 GAS 语义** 的前提下被公平评估（见 §4.5）。

### 4.5 semseal 口径：L0（BCSR inflight coalescing）在 bcsr10k step1 的收益

实验基准（固定口径）：
- `4x4 bcsr10k step1`，`exec_mode=gas`，`l1_0`，`frac_0p03`，`max_steps=1`，strict-step + freeze（runner 见 §2.4.2）

结果（semseal，L0 on vs off）：
- `memhierarchy.memctrl.bytes_est_total`：约 `0.240×`
- `memory.memory_bytes`：约 `0.306×`
- `memory.memory_requests`：约 `0.603×`
- 代价：`gas.bursts_total` 小幅上升（约 `1.086×`），这是“更多小 burst/更少 overfetch”与下游拆分的自然副作用

证据（memop 快照）：
- `memop/experiments/2026-02-28_bcsr10k_step1_gas_semseal_defaultbudget_ab_v1/snapshot/compare.tsv`

解释（为什么它是“内存侧结构性优化”）：
- L0 把“edge 维度的重复读”收敛为“block/colidx 维度的真实读”，减少下游事务；
- 它不依赖 DRAM 时序模型，也不依赖 Apply 的调度策略，本质是 **请求集合层面的去重/合并**。

### 4.6 rowpack_v1 / bc sweep / cmd-cost 的“证据状态”说明（避免误用）

同一批探索在仓库里长期存在两种口径：
- pre-sealsem（旧口径）：`window_read_budget` 会截断窗口覆盖度，对“减少真实读数”的优化不公平；
- semseal（新口径）：见 §4.4，budget 不再作为 correctness 门槛，适合作为论文级主口径。

当前 bcsr10k step1（br=1）在 **semseal** 下的复测结论（见 §8 的 memop 快照）：
- cmd-cost 护栏：稳定有效（`memctrl.bytes_est_total≈0.659×`，且 `gas_overfetch_bytes_total→0`）。
- rowpack_v1：在 br=1 主链路几乎无主效应（`memctrl.bytes_est_total≈0.998×`）。
- bc sweep（cmd-cost=1）：`bc` 从 16 降到 8/4 会让 `memctrl.bytes_est_total` 变差（约 `+4.2%` / `+7.0%`），`sim_time_actual_ns` 也小幅变差。

---

## 5. 相关探索（不在本文展开，但属于“GAS 上的体系结构探索”）

- NoC 多播（SpikeKey / SpikeTileKey）与 global credit 路线：
  - 归档：`exp_opt/2026-02-26-noc-multicast-and-global-credit.md`
  - 其中 global credit（p0/p0b/p0c_pred）会改写 `apply_bank_credit` 的 step 级分配，与本章 §3 的“credit 交互”强相关。

---

## 6. 复现清单（最小可复现集）

### 6.1 编译（仅 SnnDL）

```bash
cd "sst_workspace/sst-elements/src/sst/elements/SnnDL"
make -j4 && make install
```

### 6.2 dense microbench：cmd-cost 护栏 A/B

```bash
cd "sst_dram_si"

# A: OFF
DENSE_MICROBENCH_RUN_GROUP="dense_microbench_4x4_dram_cmd_cost_merge_guardrail_ab" \
MESH_EXPERIMENTAL_ENABLE=1 MESH_MAX_STEPS=1 MESH_EXEC_MODE=gas SST_N=32 \
MESH_L1_ENABLE=0 MESH_STEP_ACTIVATION_FRACTION=0.05 MESH_STEP_ACTIVATION_FANOUT=256 MESH_STEP_ACTIVATION_SEED=314159 \
MESH_DENSE_STRICT_CACHELINE=0 MESH_GAS_MERGE_POLICY=cacheline \
MESH_GAS_GAP_K_BYTES=2048 MESH_GAS_ROW_WINDOW_BYTES=16384 MESH_GAS_LMAX_BYTES=65536 \
MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE=0 \
bash "tools/run_dense_microbench_4x4_exec_mode_compare_with_time.sh" gas

# B: ON
DENSE_MICROBENCH_RUN_GROUP="dense_microbench_4x4_dram_cmd_cost_merge_guardrail_ab" \
MESH_EXPERIMENTAL_ENABLE=1 MESH_MAX_STEPS=1 MESH_EXEC_MODE=gas SST_N=32 \
MESH_L1_ENABLE=0 MESH_STEP_ACTIVATION_FRACTION=0.05 MESH_STEP_ACTIVATION_FANOUT=256 MESH_STEP_ACTIVATION_SEED=314159 \
MESH_DENSE_STRICT_CACHELINE=0 MESH_GAS_MERGE_POLICY=cacheline \
MESH_GAS_GAP_K_BYTES=2048 MESH_GAS_ROW_WINDOW_BYTES=16384 MESH_GAS_LMAX_BYTES=65536 \
MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE=1 MESH_GAS_DRAM_CMD_T_ROW_HIT_NS=30 MESH_GAS_DRAM_CMD_T_ROW_MISS_NS=120 \
bash "tools/run_dense_microbench_4x4_exec_mode_compare_with_time.sh" gas
```

### 6.3 bcsr10k：cmd-cost 护栏 A/B（strict-step + freeze）

```bash
cd "sst_dram_si"

# A: OFF
MESH_BCSR10K_RUN_GROUP="dram_mesh_4x4_bcsr10k_freeze_step1_dram_cmd_cost_guardrail_ab_semseal_v1" \
MESH_EXPERIMENTAL_ENABLE=1 MESH_STEP_ACTIVATION_FRACTION=0.03 MESH_L1_ENABLE=0 \
MESH_GAS_GAP_K_BYTES=2048 MESH_GAS_ROW_WINDOW_BYTES=16384 MESH_GAS_ROW_WINDOW_TIMEOUT_NS=0 \
MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE=0 \
./tools/run_mesh_bcsr10k_freeze_strictstep_exec_mode_l1_sweep_with_time.sh gas

# B: ON
MESH_BCSR10K_RUN_GROUP="dram_mesh_4x4_bcsr10k_freeze_step1_dram_cmd_cost_guardrail_ab_semseal_v1" \
MESH_EXPERIMENTAL_ENABLE=1 MESH_STEP_ACTIVATION_FRACTION=0.03 MESH_L1_ENABLE=0 \
MESH_GAS_GAP_K_BYTES=2048 MESH_GAS_ROW_WINDOW_BYTES=16384 MESH_GAS_ROW_WINDOW_TIMEOUT_NS=0 \
MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE=1 \
./tools/run_mesh_bcsr10k_freeze_strictstep_exec_mode_l1_sweep_with_time.sh gas
```

### 6.4 memop：实验承载与快照生成（强制规范）

约束（所有 memory 优化对比统一适用）：
- 每个对比实验在 `memop/experiments/<exp_id>/` 下建立目录；
- 必须包含 `cases.json`（指向每个 case 的 `run_dir`）；
- 必须生成 `snapshot/compare.tsv`（必要时补充其它快照表，如 `index_cost_compare.tsv`）。

生成快照（示意）：
```bash
cd "memop"
python3 "tools/snapshot_experiment.py" --exp-dir "experiments/<exp_id>"
```

---

## 7. 当前结论与建议（面向下一轮论文级矩阵）

1. **段构建是 “overfetch 的根因点”**：只调 Apply 发射顺序很容易被后端 FRFCFS 吞掉；段构建的“是否吸洞/吸多大洞”直接决定下游事务覆盖范围，是更强的结构性杠杆。
2. **cmd-cost 护栏属于“安全阀”**：在启用 gap-merge/row-window 的探索中，它能 deterministic 地把病态 overfetch 压住；bcsr10k step1 的 semseal 复测已完成并确认有效（§2.4.2 + §8）。
3. **Apply 调度收益强依赖并发上界**：`apply_bank_credit`、`max_inflight_reads` 会决定策略差异能否传导到 wallclock；建议论文主图给出 credit 的消融或固定为 `0`（再解释其物理含义与局限）。
4. **密度效应要显式报告**：在不同发放率下，访问更密可能减少洞（overfetch 降），导致 `memctrl_bytes` 下降并不矛盾；应同时报告 `payload/unique/overfetch` 三者以解释趋势。
5. **权重格式切换会触发“瓶颈迁移”**：GCSS value-only 把读源从 “BCSR meta” 迁移到 “value-only”，显著降低 meta 事务与 bytes；但进一步收益会更受 cacheline overfetch 与 DRAM 行局部性主导（见 §11 的 memop 证据与解读）。

---

## 8. semseal 口径复测（bcsr10k step1，memop 承载，已完成）

目标：
- 用 **semseal**（§4.4）口径，重跑“会改变真实读数/覆盖度”的内存优化对比；
- 统一沉淀到 `memop/experiments/<exp>/cases.json` + `snapshot/compare.tsv`，避免误用 pre-sealsem 数据。

### 8.1 复测共同约束（固定基准）

- workload：`4x4 bcsr10k step1`
- `exec_mode=gas`，`l1_0`，`frac_0p03`，`max_steps=1`
- runner：`sst_dram_si/tools/run_mesh_bcsr10k_freeze_strictstep_exec_mode_l1_sweep_with_time.sh`
- 强制：`MESH_EXPERIMENTAL_ENABLE=1`（仅对显式开启项生效）
- 产物必须 `validation.log: PASS`（否则该对比标记 INCONCLUSIVE，不入主结论）

### 8.2 复测矩阵 1：cmd-cost 护栏（semseal A/B）

状态：DONE（memop 快照已生成）。

目的：验证 cmd-cost 护栏在 semseal 口径下是否仍能把 `gas_overfetch_bytes_total` 压到 0，并显著降低 `memctrl.bytes_est_total`。

建议 run_group（新目录）：
- `dram_mesh_4x4_bcsr10k_freeze_step1_dram_cmd_cost_guardrail_ab_semseal_v1`

运行命令（示意）：
```bash
cd "sst_dram_si"

# A: guardrail OFF
MESH_BCSR10K_RUN_GROUP="dram_mesh_4x4_bcsr10k_freeze_step1_dram_cmd_cost_guardrail_ab_semseal_v1" \
MESH_EXPERIMENTAL_ENABLE=1 MESH_STEP_ACTIVATION_FRACTION=0.03 MESH_L1_ENABLE=0 \
MESH_GAS_GAP_K_BYTES=2048 MESH_GAS_ROW_WINDOW_BYTES=16384 MESH_GAS_ROW_WINDOW_TIMEOUT_NS=0 MESH_GAS_LMAX_BYTES=65536 \
MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE=0 \
./tools/run_mesh_bcsr10k_freeze_strictstep_exec_mode_l1_sweep_with_time.sh gas

# B: guardrail ON
MESH_BCSR10K_RUN_GROUP="dram_mesh_4x4_bcsr10k_freeze_step1_dram_cmd_cost_guardrail_ab_semseal_v1" \
MESH_EXPERIMENTAL_ENABLE=1 MESH_STEP_ACTIVATION_FRACTION=0.03 MESH_L1_ENABLE=0 \
MESH_GAS_GAP_K_BYTES=2048 MESH_GAS_ROW_WINDOW_BYTES=16384 MESH_GAS_ROW_WINDOW_TIMEOUT_NS=0 MESH_GAS_LMAX_BYTES=65536 \
MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE=1 MESH_GAS_DRAM_CMD_T_ROW_HIT_NS=30 MESH_GAS_DRAM_CMD_T_ROW_MISS_NS=120 \
./tools/run_mesh_bcsr10k_freeze_strictstep_exec_mode_l1_sweep_with_time.sh gas
```

memop（结果与证据）：
- `memop/experiments/2026-02-27_dram_cmd_cost_guardrail_bcsr10k_step1_ab_semseal_v1/snapshot/compare.tsv`

### 8.3 复测矩阵 2：rowpack_v1 × cmd-cost（semseal 2×2）

状态：DONE（memop 快照已生成）。

目的：在 semseal 口径下分离：
- rowpack 的主效应（layout 改变是否减少/重排 memctrl traffic）
- cmd-cost 的主效应（veto overfetch）
- 两者是否可叠加

建议 run_group：
- `dram_mesh_4x4_bcsr10k_freeze_step1_rowpack_cmd_cost_guardrail_semseal_matrix_v1`

cases（4 个）：
- `flat_cmd0`：flat + cmd_cost=0
- `flat_cmd1`：flat + cmd_cost=1
- `rowpack_cmd0`：rowpack_v1 + cmd_cost=0
- `rowpack_cmd1`：rowpack_v1 + cmd_cost=1

memop（结果与证据）：
- `memop/experiments/2026-02-27_memop_bcsr10k_step1_rowpack_cmd_cost_matrix_semseal_v1/snapshot/compare.tsv`

### 8.4 复测矩阵 3：bc sweep（semseal，cmd-cost=1 下复查 tradeoff）

状态：DONE（memop 快照已生成）。

目的：确认 pre-sealsem 中观测到的 tradeoff 在 semseal 下是否仍存在：
- bc 变小：bursts 下降，但 `memctrl.bytes_est_total/sim_time` 反而上升

建议 run_group：
- `dram_mesh_4x4_bcsr10k_freeze_step1_bc_sweep_cmd_cost_on_semseal_v1`

建议对比集：
- bc=16 / 8 / 4（保持 br=1、同 frac/seed）

memop（结果与证据）：
- `memop/experiments/2026-02-27_memop_bcsr10k_step1_bc_sweep_cmd_cost_on_semseal_v1/snapshot/compare.tsv`

### 8.5 复测顺序（优先级）

1. cmd-cost A/B（DONE：护栏在 semseal 下仍是“安全阀”）
2. rowpack×cmd-cost（DONE：br=1 主链路 rowpack 几乎无主效应）
3. bc sweep（DONE：bc 缩小会恶化 bytes 与时延）

---

## 9. 主线可合入项：最终优化清单（只保留 memory-side）

本节给出“可合入主线”的最终清单：要求 **不改变 GAS 语义**（semseal 口径可比）、可默认存在于代码库（默认开/关均可），并能用 `memop` 的 `compare.tsv` 做证据闭环。

### 9.1 主线准入标准（硬门槛）

- **语义不漂移**：在 `validation.log`（paper profile）下 `fail=0`，且关键功能统计（`neurons_fired_total`、`snn_tx`、`nic.packets_sent` 等）不因优化开关变化而分叉。
- **统计口径稳定**：必须基于 §4.4 的 semseal（`window_read_budget` 非 correctness 门槛）；禁止再用 pre-sealsem 结果做论文级结论。
- **可审计**：每个优化必须有 `memop/experiments/<exp>/cases.json` + `snapshot/compare.tsv`，并记录固定基准（4x4 bcsr10k step1 等）。

### 9.2 强主效应（建议保留在主线，并作为论文/主线的核心 memory 优化）

#### A) Weights-L0：BCSR inflight coalescing（colidx + blockdata）

- **定位**：窗口内对 BCSR 的 colidx/blockdata 做 in-flight 合并（多 edge 共享一次真实读），降低真实 DRAM 事务数/字节。
- **实现位置**：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.{h,cc}`
- **关键开关**（主线建议默认启用）：
  - `bcsr_colidx_inflight_coalesce_enable=1`
  - `bcsr_block_inflight_coalesce_enable=1`
- **收益（semseal, bcsr10k step1）**：
  - `memhierarchy.memctrl.bytes_est_total≈0.240×`
  - `memory.memory_bytes≈0.306×`
  - `memory.memory_requests≈0.603×`
  - 代价：`gas.bursts_total≈1.086×`（更多小 burst 的副作用）
- **证据**：
  - `memop/experiments/2026-02-28_bcsr10k_step1_gas_semseal_defaultbudget_ab_v1/snapshot/compare.tsv`

#### B) 段构建护栏：DRAM cmd-cost merge veto（与粗/细合并配套）

- **定位**：当启用 gap-merge/row-window（粗/细合并）时，用 deterministic 规则 veto “不划算的吸洞”，把 overfetch 压到 0。
- **实现位置**：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/gather/apply/DramCmdCostMergeModel.h`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`
- **关键开关**（主线建议“默认存在 + 默认关闭”，但当启用粗/细合并时强烈建议同步开启）：
  - `dram_cmd_cost_merge_enable`
  - `dram_cmd_t_row_hit_ns` / `dram_cmd_t_row_miss_ns`
- **收益（semseal, bcsr10k step1，启用 k/rowwin 的探索配置）**：
  - `memhierarchy.memctrl.bytes_est_total=0.658742×`
  - `gas.overfetch_bytes_total: 63,037,952 → 0`
  - `sim_time_actual_ns=0.945612×`（次要收益）
- **证据**：
  - `memop/experiments/2026-02-27_dram_cmd_cost_guardrail_bcsr10k_step1_ab_semseal_v1/snapshot/compare.tsv`

### 9.3 主线“语义封口/正确性硬化”（必须保留，否则优化对比不可信）

#### C) semseal：window_read_budget 不再截断覆盖度

- **定位**：将 `window_read_budget` 从 correctness 硬门槛降级为“观测/提示”，只保留 `max_outstanding_requests` 作为硬限流。
- **实现位置**：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`（`tryIssueRead_()`）
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`（发放判断）
- **效果**：让 L0 / cmd-cost 等“减少真实读数”的优化在 on/off 时不再改变窗口最终覆盖集合（避免语义漂移）。

#### D) cacheline 分片下发（防 payload 越界/读脏）

- **定位**：下游 StandardMem 读按 cacheline 分片并在 SRAM 拼接，规避 memHierarchy.Cache 对 `size>cacheline` 的已知问题。
- **实现位置**：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`（`issueGranuleBufBudget_()`）
- **主线地位**：属于 correctness/确定性硬化，必须保留。

### 9.4 主线可保留但“非主效应/条件生效”（不作为 bcsr10k step1 主链路核心结论）

#### E) rowpack_v1（BCSR 物理布局）

- **结论（semseal, br=1 的 bcsr10k step1）**：几乎无主效应，`memctrl.bytes_est_total≈0.998×`。
- **主线建议**：保留实现（格式/生态能力），但不要把它当作 br=1 主链路的 memory 优化抓手；更适合在 `br>1` 或其它数据集条件下再评估。
- **证据**：
  - `memop/experiments/2026-02-27_memop_bcsr10k_step1_rowpack_cmd_cost_matrix_semseal_v1/snapshot/compare.tsv`

#### F) BCSR blockdata `row_cacheline` 读取粒度

- **结论**：对 `br=1` 数据集是 no-op；对 `br>1` 才可能显著减少读字节。
- **主线建议**：保留开关与实现，后续把 `br>1` 的 semseal A/B 也纳入 memop 证据闭环。

#### G) bc sweep（bc=16/8/4）

- **结论（semseal, cmd-cost=1）**：`bc` 从 16 降到 8/4 会让流量变差（`+4.2% / +7.0%`），时延也小幅变差。
- **主线建议**：不要把 “减小 bc” 作为当前链路的 memory 优化方向；bc=16 仍是较优默认。
- **证据**：
  - `memop/experiments/2026-02-27_memop_bcsr10k_step1_bc_sweep_cmd_cost_on_semseal_v1/snapshot/compare.tsv`

### 9.5 明确不进入“memory 主线优化清单”的项（原因 + 现状态）

- `Apply issue policy`（`cmd_aware_v1/bank_rr_row_sticky_age`）：主要优化时序/row-hit，并不以降低 bytes 为目标；**已物理移除**（主线仅保留 `order`）。
- `dram_aware_v1`（窗口级启发式 tuner）：含启发式/窗口摘要依赖，不满足“论文口径的纯确定性”主张；**已物理移除**（含 `DramAwareTuner` 源码与构建入口）。
- dense microbench `pre-global` 选源：方法学修复，非架构内存优化；**已移除开关路径**（不再进入模型摘要/配置链）。
- `synapse_sram_enable`：在 `bcsr_gas` 模式下无效（deprecated）；**已物理移除主链路代码与统计项**。

---

## 10. 方案A第一轮落地闭环（2026-02-28，Ramulator2 DDR5 + DDR5_notrans）

目标：
- 按“DRAM-Truth Geometry + Banked Admission（deterministic）”先落地最小可合入实现；
- 保持 `apply_issue_policy=order` 语义不变；
- 在 `4x4 bcsr10k step1` 统一口径下，验证该开关是否带来稳定内存收益。

### 10.1 代码落地点（本轮新增/补齐）

- C++（调度逻辑）：
  - `GatherBufferIF` 增加 `apply_banked_admission_enable`（默认 `0`）；
  - 在 `defer+apply` 路径下启用 banked admission（按 bank RR + per-bank credit）。
- Python 参数链（本轮补齐）：
  - `sst_dram_si/mesh_template/config.py`
    - local：`gas_apply_banked_admission_enable`
    - env：`MESH_GAS_APPLY_BANKED_ADMISSION_ENABLE`
    - 均受 `MESH_EXPERIMENTAL_ENABLE=1` 门控
  - `sst_dram_si/mesh_template/runtime.py`
    - 两处 `gas_cfg` 注入 `apply_banked_admission_enable`
  - `sst_dram_si/mesh_template/build.py`
    - 下发至 `effective_cfg["gas"]`、`per_core.gatherbuf`、`core_memory_params`
  - `sst_dram_si/tools/write_mesh_meta.py`
    - 记录环境与模型有效值（provenance）

### 10.2 实验设计（隔离、可复现）

- 实验目录：
  - `memop/experiments/2026-02-28_bcsr10k_step1_schemeA_banked_admission_ab_v1`
- 统一固定：
  - `exec_mode=gas`，`strict-step`，`L1=0`，`frac=0.03`，`max_steps=1`
  - `MESH_MEM_BACKEND=ramulator2`
  - 几何对齐：`MESH_GAS_SORT_POLICY=bank_row`，`MESH_GAS_ROW_BYTES_GUESS=4096`，
    `MESH_GAS_BANK_BITS=4`，`MESH_GAS_BANK_SHIFT=28`，`MESH_GAS_BANK_AUTO_ENABLE=0`
  - `MESH_GAS_APPLY_ISSUE_POLICY=order`，`MESH_GAS_APPLY_FRAGS_PER_ISSUE=1`，`MESH_GAS_APPLY_BANK_CREDIT=1`
- A/B 维度：
  - `ddr5_off/on`：`ramulator2_ddr5.cfg` + `apply_banked_admission_enable=0/1`
  - `ddr5_notrans_off/on`：`ramulator2_ddr5_notrans.cfg` + `apply_banked_admission_enable=0/1`
- 快照输出：
  - `cases.json` + `snapshot/compare.tsv`

### 10.3 结果（闭环结论）

四组均通过验证：
- `validation.log`：`fail=0 warn=0 strict=0`

关键指标（off→on）：
- `model.sim_time_actual_ns`：无变化（`4352968`）
- `memhierarchy.memctrl.bytes_est_total`：无变化（`128479424`）
- `memhierarchy.memctrl.req_total`：无变化（`2007491`）
- `ramulator2.avg_read_latency_0_avg`：无变化（`33.4041596`）
- `ramulator2.row_hit_rate_total`：
  - ddr5：`+0.117%`
  - ddr5_notrans：`-0.050%`

结论：
- 本轮“banked admission”在该主口径下 **未产生稳定收益**（收益指标不变，row-hit 仅噪声级波动）。
- 但工程落地是有效的：off/on 仅该开关差异，参数链与元数据均正确记录，具备后续复测与扩展基础。

### 10.4 为什么会“几乎不变”（当前最可信解释）

- 当前口径固定 `apply_bank_credit=1`，本质上把每 bank 并发压得很低；
- `strict-step + step1` 进一步收紧了可重排空间；
- 在该组合下，banked admission 对“真实请求集合/总读字节”几乎不施加变化，
  因而 `memctrl.bytes_est_total / avg_read_latency / sim_time` 不动是合理结果。

### 10.5 对主线的影响判断

- 语义安全性：通过（未改变 GAS 语义，验证全部 PASS）。
- 主线价值：当前不能作为“收益型主线优化”直接合入结论；
  仅可作为“已落地、可控开关、待进一步证据”的实验能力保留。

### 10.6 可观测增强复测（ddr5 off/on）后的根因收敛

复测目录：
- `memop/experiments/2026-02-28_bcsr10k_step1_schemeA_banked_trace_probe_v1`

设置：
- 在 10.2 的口径上开启
  - `MESH_GAS_EXPORT_CREDIT_CTRL=1`
  - `MESH_GAS_EXPORT_APPLY_BANK_TRACE=1`

结果：
- A/B 主指标仍完全一致（`sim_time/memctrl_bytes/memctrl_req/gas_apply_ns_avg` 全部 1.000×）。
- `row_hit_rate_total` 只有千分之一量级波动，不形成稳定收益。

关键发现（本轮最重要）：
- `meta.model` 记录为 `bank_row + bank_bits=4 + bank_shift=28`；
- 但 `effective_config.per_core[*].gatherbuf` 实际为 `sort_policy=row`, `bank_bits=0`, `bank_shift=0`, `bank_auto=1`。

这意味着：
- 本轮运行时并未真正进入“DRAM-Truth Geometry”状态；
- banked admission 在执行面退化为单 bank admission，天然难以获得收益。

附加观测：
- run_dir 未生成 `credit_ctrl.csv/apply_bank_trace.csv`；
- `mesh_stats.csv` 中相关统计（如 `gas_apply_bank_rr_turns_total`）也为 0。

结论：
- 这次“无收益”主要不是算法失效，而是“有效配置与预期配置不一致”导致的可操作空间被压平；
- 下一步优先修复配置一致性与 trace 导出链路，再做收益评估更有意义。

---

## 11. GCSS（value-only）与 GCSSIDX2（Row-MPHF）：当前体系现状（2026-03-02）

本节把“权重格式/索引”这一条内存主线的 **现状、实现位置、统计证据与瓶颈迁移** 固化到本文档，作为后续论文级实验的基线背景。

### 11.1 目标与语义边界（不改变 GAS 语义）

- 目标：把权重读从 `BCSR(colidx+blockdata)` 的 meta 读，迁移到 **values-only** 的顺序流。
- 语义边界：不改变 GAS 的窗口覆盖集合与时序语义；semseal 口径下对比必须 `validation.log: fail=0`。
- idx2 的关键假设：**运行时不会对不存在的 `(pre_global, post_local)` 做 lookup**；一旦发生即视为 bug（fail-fast）。因此 idx2 不做 membership check，可用 “纯 MPHF/retrieval” 极致压缩索引。

### 11.2 实现位置与开关（严格隔离）

- 离线生成（基于 per-core BCSR）：
  - GCSSIDX1：`sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore.py`
  - GCSSIDX2（Row-MPHF）：`sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_idx2_rowmphf.py`（支持 `--jobs` 并行）
  - GCSS-VLF-PreMPHF（value-only + 预计算 MPHF / rank，用于 VLF）：`sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf.py`（当前默认 `pilot_bits=16`，支持 `--jobs` 并行）
- 运行时索引加载与 lookup：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/GcssIndexRowMphf.h`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/GcssIndexPreMphf.h`（支持 `pilot_bits=8/16`）
- 模式接入（weights 子系统）：
  - `synapse_weight_mode=bcsr_gas`（默认）
  - `synapse_weight_mode=gcss_valueonly_dstcore`（需要 `MESH_GCSS_DIR`）
  - `synapse_weight_mode=gcss_valueonly_dstcore_idx2`（需要 `MESH_GCSS2_DIR`，且 `MESH_EXPERIMENTAL_ENABLE=1`）
  - `synapse_weight_mode=gcss_valueonly_dstcore_vlf_premphf`（需要 `MESH_GCSSVLF_DIR`，且 `MESH_EXPERIMENTAL_ENABLE=1`）
- 统计口径补齐（用于论文表/快照对比）：
  - `sst_dram_si/tools/compute_essential_summary_mesh.py` 会生成：
    - `synapse.read_source.*`（证明读源从 meta → gcss）
    - `synapse.index_cost.*`（扫描 weights 目录，统计 index_total_bytes / values_total_bytes / bits_per_edge）

### 11.3 memop 证据：bcsr10k step1（semseal，3-way 对比）

实验承载（cases + snapshot）：
- `memop/experiments/2026-03-02_gcss_idx2_rowmphf_bcsr10k_step1_semseal_v1/`
  - `snapshot/compare.tsv`
  - `snapshot/index_cost_compare.tsv`

关键观测（相对 baseline `baseline_bcsr_gas`）：
- 读源迁移证据：
  - baseline：`synapse.read_source.meta_bytes_share=1`（`colidx+blockdata` 主导）
  - GCSS（v1/idx2）：`synapse.read_source.meta_bytes_share=0`，`gcss_bytes_share=1`
- off-chip 事务（memctrl）：
  - `memhierarchy.memctrl.req_total`：`0.616×`（v1/idx2 基本一致）
  - `memhierarchy.memctrl.bytes_est_total`：`0.615×~0.616×`
- wallclock（本口径）：
  - `model.sim_time_actual_ns`：`0.523×`（v1）/ `0.542×`（idx2）
- DRAM 行局部性（Ramulator2）：
  - `ramulator2.row_hit_rate_total`：`0.8002 → 0.8684~0.8709`（约 `1.085×~1.088×`）
  - `ramulator2.avg_read_latency_0_avg`：几乎不变（约 `33.39 ns`）
- SRAM 常驻索引成本（idx2 的核心收益点，不以 step1 wallclock 为主要度量）：
  - v1（IDX1）：`index_to_values_ratio=2.262`，`index_bits_per_edge=72.39`
  - idx2（Row-MPHF）：`index_to_values_ratio=0.09937`，`index_bits_per_edge=3.18`

### 11.4 解读：为什么 idx2 的 step1 性能并不会显著超过 v1

在当前模拟口径下：
- v1 与 idx2 都已把 DRAM 侧读源变成 values-only；两者的 **DRAM 读事务集合** 基本一致，因此 `memctrl.req/bytes` 与 `avg_read_latency` 接近。
- idx2 的主效应是 **把“常驻 SRAM 的索引”压到 values/10**，属于 “DRAM-based 可扩展性使能”：
  - 对 step1 的 wallclock（主要由 DRAM 事务与后端调度决定）提升不一定直接体现；
  - 但对 10M-100M neurons 量级的 on-chip SRAM 预算是决定性的（索引不再反客为主）。

### 11.5 当前瓶颈迁移：从 meta bytes → cacheline overfetch / 物理事务

GCSS value-only 把 meta 事务基本清零后：
- “逻辑有效字节”已接近下限，但 `memhierarchy.memctrl.bytes_est_total` 仍显著大于 `memory.memory_bytes`（cacheline 语义下的放大不可避免）。
- 因此下一阶段的内存体系结构优化，应更聚焦：
  - 减少 cacheline overfetch（请求集合与布局协同）
  - 提升行/银行并行度的可兑现度（在不改变语义的 deterministic 约束下）
  - 用 `synapse.read_source + synapse.index_cost + memctrl bytes/req + row_hit_rate` 形成“证据闭环”

---

## 12. P0 论文证据补齐（主基线口径 + GCSS 下 cmd-cost 验证，2026-03-02）

本节对应当前轮次的两个 P0 目标：
- P0-1：`GCSSIDX2` 在主基线口径（`4x4 bcsr10k step1, frac=0.03`）补齐论文可用证据；
- P0-2：验证 `cmd-cost` 护栏在 GCSS 下是否为关键增益点。

### 12.1 P0-1：主基线三方对比（BCSR / GCSS v1 / GCSSIDX2）

实验承载：
- `memop/experiments/2026-03-02_p0_mainbaseline_gcss_idx2_semseal_fix_v1/`
  - `cases.json`
  - `snapshot/compare.tsv`
  - `snapshot/index_cost_compare.tsv`

三组 run 均 `validation.log: fail=0 warn=0 strict=0`，且 idx2 case 已通过“GCSS 路径有效性”门槛（见 12.3）。

主口径结果（相对 BCSR baseline）：
- `gcss_v1_scan`：
  - `sim_time_actual_ns=0.4318×`
  - `memctrl.bytes_est_total=0.7295×`
  - `memctrl.req_total=0.7295×`
  - `row_hit_rate_total: 0.6902 -> 0.9470`
- `gcss_idx2_rowmphf_fixed`：
  - `sim_time_actual_ns=0.4676×`
  - `memctrl.bytes_est_total=0.8361×`
  - `memctrl.req_total=0.8361×`
  - `synapse` 侧路径有效（`gcss_lookup_hit_total=762,950`，`gcss_bytes_share=1`）

索引成本（与路径有效性无关，来自离线 artifact 扫描）：
- `gcss_v1_scan`: `index_to_values_ratio=2.2623`，`index_bits_per_edge=72.3923`
- `gcss_idx2_rowmphf_fixed`: `index_to_values_ratio=0.09937`，`index_bits_per_edge=3.1799`

### 12.2 P0-2：GCSS 下 cmd-cost 护栏 A/B

实验承载：
- `memop/experiments/2026-03-02_p0_gcss_cmdcost_ab_semseal_fix_v1/`
  - `cases.json`
  - `snapshot/compare.tsv`
  - `snapshot/gcss_path_validity.tsv`（新增：路径有效性门槛）

#### 12.2.1 `gcss_valueonly_dstcore`（有效 GCSS 路径）

`cmd=0 -> cmd=1`：
- `sim_time_actual_ns`: `1,879,501 -> 1,485,732`（`0.7905×`）
- `memctrl.bytes_est_total`: `93,729,344 -> 48,902,144`（`0.5217×`）
- `memctrl.req_total`: `1,464,521 -> 764,096`（`0.5217×`）
- `gas.overfetch_bytes_total`: `70,308,848 -> 2,369,208`

结论：在 `gcss_v1` 且存在高 overfetch 的场景，`cmd-cost` 是显著有效的关键增益点。

#### 12.2.2 `gcss_valueonly_dstcore_idx2`（修复后口径）

`cmd=0 -> cmd=1`：
- `sim_time_actual_ns`: `2,035,318 -> 1,495,932`（`0.7352×`）
- `memctrl.bytes_est_total`: `107,418,944 -> 48,958,208`（`0.4558×`）
- `memctrl.req_total`: `1,678,421 -> 764,972`（`0.4558×`）
- `gas.overfetch_bytes_total`: `76,406,952 -> 1,547,932`

路径有效性（两组均通过）：
- `gcss_lookup_hit_total=762,950`
- `synapse.read_source.gcss_bytes_share=1`
- `synapse.read_source.meta_bytes_share=0`
- `snn_tx_spike_packets_total=40,606,208`，`neurons_fired_total=158,618`

结论：`idx2` 在修复后同样证明 `cmd-cost` 是关键增益点，先前结论 **INCONCLUSIVE** 已失效。

### 12.3 本轮新增“有效性门槛”（避免假阳性）

对所有 `synapse_weight_mode=gcss*` 的 case，若任一条件不满足，直接判为无效样本：
- `synapse.read_source.gcss_bytes_share >= 0.999`
- `synapse.gcss_lookup_hit_total > 0`
- `snn_tx.spike_packets_total` 非空（且应与同口径 baseline 同量级）

对应快照：
- `memop/experiments/2026-03-02_p0_gcss_cmdcost_ab_semseal_fix_v1/snapshot/gcss_path_validity.tsv`

### 12.4 对下一步的直接影响

1. `gcss_v1 + cmd-cost`：可进入论文主图/主结论（收益稳定且路径有效）。
2. `idx2 + cmd-cost`：也可作为“护栏关键增益”证据；但在该 workload 下 `idx2 cmd1` 与 `v1 cmd1` 性能接近，idx2 主价值仍是索引压缩（`index<=values/10`）。
3. 将 12.3 的有效性门槛并入自动验收脚本，作为 `gcss*` case 的硬门槛（不通过即标记 INCONCLUSIVE）。

---

## 13) DRAM 参数自适应的 cmd-cost 离线模型（隔离实现，2026-03-02）

### 13.1 目标

在不改变 GAS 语义、不改 SnnDL GatherBufferIF 既有行为的前提下，把 `cmd-cost` 护栏中 `t_row_hit_ns/t_row_miss_ns` 的来源从“手工常量”扩展为“可选的、基于 Ramulator2 cfg 的离线推导”，避免参数漂移与口径不一致。

### 13.2 落地位置（默认关闭）

- 新增模块：
  - `sst_dram_si/mesh_template/gas_cmd_cost_offline_model.py`
- 接线：
  - `sst_dram_si/mesh_template/config.py`
  - `sst_dram_si/mesh_template/runtime.py`
  - `sst_dram_si/mesh_template/build.py`
  - `sst_dram_si/mesh_template/legacy_defaults.py`

开关（实验隔离）：
- `MESH_GAS_DRAM_CMD_OFFLINE_MODEL_ENABLE`（默认 `0`）
- `MESH_GAS_DRAM_CMD_OFFLINE_MODEL_STRICT`（默认 `0`）

显式覆盖保护（避免混口径）：
- 一旦设置 `MESH_GAS_DRAM_CMD_T_ROW_HIT_NS/MESH_GAS_DRAM_CMD_T_ROW_MISS_NS`，会打显式标记，离线推导自动跳过。

### 13.3 推导口径

基于 Ramulator2 预设（当前支持 DDR5/HBM2 preset）：
- `hit_cycles = nCL + nBL`
- `miss_cycles = hit_cycles + nRCD + nRP + nRAS`
- `t_row_hit_ns = round(hit_cycles * tCK_ps / 1000)`
- `t_row_miss_ns = round(miss_cycles * tCK_ps / 1000)`

并同步输出：`k_lines` / `k_bytes`、geometry、bandwidth 到 `effective_config.gas.dram_cmd_offline_model.derived`。

### 13.4 闭环 A/B（4x4 bcsr10k step1, frac=0.03, L1=0, max_steps=1, gcss_idx2, cmd_cost=1）

- A（manual）：`offline=0`, `t_hit=30`, `t_miss=120`
  - run: `/home/xgy/remote/sst_dram_si/outputs_large/paper2/2026-03-02_p0_gcss_idx2_cmdcost_offline_ab_semseal_fix_v1_manual/gas/l1_0/frac_0p03/20260302-190359-956870359`
- B（offline）：`offline=1, strict=1`, 不设置 `t_row_*`
  - run: `/home/xgy/remote/sst_dram_si/outputs_large/paper2/2026-03-02_p0_gcss_idx2_cmdcost_offline_ab_semseal_fix_v1_offline/gas/l1_0/frac_0p03/20260302-191137-913119401`

两组均通过验证：`fail=0 warn=0 strict=0`。

A/B 关键结果：
- A: `t_hit=30`, `t_miss=120`, `offline.applied=0`, `reason=disabled`
- B: `t_hit=22`, `t_miss=90`, `offline.applied=1`, `reason=applied`
- B 的推导元信息（来自 `ramulator2_ddr5.cfg`）：
  - `dram_impl=DDR5`, `org=DDR5_8Gb_x8`, `timing=DDR5_3200C`
  - `k_lines=3`, `k_bytes=192`

性能统计（`memop snapshot/compare.tsv`）在本口径一致：
- `sim_time_actual_ns`: `1.0000x`
- `memctrl.bytes_est_total`: `1.0000x`
- `memctrl.req_total`: `1.0000x`

实验承载：
- `memop/experiments/2026-03-02_p0_gcss_idx2_cmdcost_offline_ab_semseal_fix_v1/`
  - `cases.json`
  - `snapshot/compare.tsv`

### 13.5 结论

- 该方案已实现“参数来源自适应 + 严格可追踪 + 默认隔离关闭”。
- 在当前主口径下，离线参数替换不会破坏语义，也未引入性能回归或额外收益。
- 当前价值是“口径稳健化（paper reproducibility）”，不是“单点提速”；下一步收益应来自更细粒度 cost table 或与 bank/row 行为耦合的策略优化。

---

## 14) cmd-cost bank-table（v2）：统计链路修复后结论（2026-03-02）

### 14.1 问题定位（为何此前看起来“全 0”）

此前 `cmd_cost_*` 统计注册在 `GatherBufferIF`，但 `mesh_stats.csv` 的主口径来自 `MultiCorePE` 聚合统计。  
因此出现“机理可能执行了，但 summary 看不到”的假象。

### 14.2 修复方案（不改 GAS 语义）

将 `cmd_cost_*` 以窗口统计沿既有主链路上报：

- `GatherBufferIF`：窗口内累计
  - `cmd_cost_veto`
  - `cmd_cost_veto_fine_gap`
  - `cmd_cost_veto_row_window`
  - `cmd_cost_bank_table_use`
- 通过 `GasStatData -> GasStatEvent -> IPeAggregation::accumulateGasStatsExt(...)` 上报
- 在 `MultiCorePE` 注册并输出：
  - `gas_cmd_cost_veto_total`
  - `gas_cmd_cost_veto_fine_gap_total`
  - `gas_cmd_cost_veto_row_window_total`
  - `gas_cmd_cost_bank_table_use_total`

### 14.3 v2 A/B 闭环（gcss_idx2，semseal 主口径）

实验设置（仅 bank-table 开关不同）：
- workload：`4x4 bcsr10k step1`, `frac=0.03`, `L1=0`, `max_steps=1`
- mode：`gas + gcss_valueonly_dstcore_idx2 + cmd_cost=1 + offline strict`
- OFF run：
  - `/home/xgy/remote/sst_dram_si/outputs_large/paper2/2026-03-02_p1_gcss_idx2_cmdcost_banktable_ab_semseal_fix_v2_off/gas/l1_0/frac_0p03/20260302-232106`
- ON run：
  - `/home/xgy/remote/sst_dram_si/outputs_large/paper2/2026-03-02_p1_gcss_idx2_cmdcost_banktable_ab_semseal_fix_v2_on/gas/l1_0/frac_0p03/20260302-232105`
- 两组验证均通过：`fail=0 warn=0 strict=0`

memop 承载：
- `memop/experiments/2026-03-02_p1_gcss_idx2_cmdcost_banktable_ab_semseal_fix_v2/`
  - `cases.json`
  - `snapshot/compare.tsv`

### 14.4 关键结果与机理解释

主性能统计（OFF vs ON）完全一致：
- `sim_time_actual_ns = 1,495,932`
- `memctrl.bytes_est_total = 48,958,208`
- `gas.overfetch_bytes_total = 1,547,932`

新统计（主口径可见）：
- `gas.cmd_cost_veto_total = 17,887`（OFF=ON）
- `gas.cmd_cost_veto_fine_gap_total = 0`（OFF=ON）
- `gas.cmd_cost_veto_row_window_total = 17,887`（OFF=ON）
- `gas.cmd_cost_bank_table_use_total = 0 (OFF) / 35,962 (ON)`

解释：
1. `bank_table_use_total` 明确证明 ON 时 per-bank 表查找路径已被执行，不是“路径未触发”。
2. 但当前离线 bank table 是 uniform（各 bank 命中/失效率代价相同），因此 `allowAbsorbGap` 的决策边界与 OFF 等价。
3. 决策不变 -> 事务集合不变 -> `memctrl req/bytes` 与 `sim_time` 不变。

### 14.5 当前结论（可用于论文方法学说明）

- 结论 A：`cmd-cost bank-table` 的**可观测性问题已修复**，链路可信。
- 结论 B：uniform bank-table 只证明“机制正确”，不带来收益。
- 结论 C：下一步若要收益，必须引入**非均匀 bank 代价模型**（反映真实 bank 冲突/排队差异），否则 bank-table 只是功能等价替换。

---

## 15) 主线清理落地（2026-03-03）：按 1/2/3 执行结果

本节记录“仅保留主线可合入 memory 优化项”的代码级清理落地，目标是防止误用、统一口径。

### 15.1 执行项 1：移除 `apply_credit_auto` 无效链路

已删除：
- mesh 配置透传与 `effective_cfg/per_core/core_memory_params` 注入中的 `apply_credit_auto_*` 全部字段。
- SnnDL 事件/统计链路中的 `apply_credit_auto_raise/drop/hold` 字段与统计注册。
- summary 聚合中的 `apply_credit_auto_*` 统计导出。

影响结论：
- 不改变当前主线语义（`apply_issue_policy=order` 仍唯一有效策略）。
- 去除无效统计噪声，避免后续误判“auto-credit 生效”。

### 15.2 执行项 2：清理 `cmd_v2` 旧入口残留

已确认并处理：
- 代码主执行路径仅允许 `apply_issue_policy=order`，不存在 `cmd_v2` 活跃入口。
- 清理脚本中的旧注释入口描述（`cmd_aware/...`），防止误导为可用主线策略。

影响结论：
- 行为不变；主要是“入口语义去歧义”。

### 15.3 执行项 3：移除 `bank-table` 分支

已删除：
- `mesh_template` 中 `dram_cmd_bank_table_enable` 与 `t_row_*_bank_ns_csv` 的 env/local_run_config/build/runtime 透传。
- `GatherBufferIFConfig` 对 `dram_cmd_cost_bank_table_enable` 与 per-bank CSV 的解析字段。
- `GatherBufferIF` 中 per-bank table 解析/分支逻辑（`cmdCostNsForBank_` 统一回落全局 `t_hit/t_miss`）。
- `gas_cmd_cost_bank_table_use*` 统计链路（Gather/PE/summary/snapshot）。
- offline model 中 uniform bank-table 派生字段（`bank_table_size`, `*_bank_ns_csv`）。

影响结论：
- 去除“机制执行但 uniform 无收益”的分支，避免后续误用该开关造成实验歧义。
- 保留 cmd-cost 主体（`t_row_hit_ns/t_row_miss_ns` 与 offline derive）不变。

### 15.4 闭环验证

编译与测试：
- `SnnDL make -j4 && make install`：通过。
- 单测：
  - `test_gas_cmd_cost_offline_model.py`：通过。
  - `test_compute_essential_summary_mesh_gas_bytes.py` + `test_compute_essential_summary_mesh_nic.py`：通过。

baseline 烟测（`4x4 bcsr10k step1`, GAS）：
- run_dir:
  - `/home/xgy/remote/sst_dram_si/outputs_large/paper2/memop_postremove_cmdcleanup_smoke/gas/l1_0/frac_0p05/20260303-002340-375573734`
- 验证：`validation.log => SUMMARY fail=0 warn=0 strict=0`
- 关键统计：`model.sim_time_actual_ns = 1209597`

### 15.5 最终结论（主线口径）

- 已完成“直接移除代码行”而非仅关入口。
- 当前 memory 主线将不再包含：
  - `apply_credit_auto` 路径
  - `cmd_v2` 旧策略入口语义
  - `bank-table` 分支与对应统计
- 主线验证通过，后续 `memop` 复测可在更干净、不可误触的基线上推进。

---

## 16) SRAM Observe-only（P0-P2）一次性落地状态（2026-03-03）

目标：在不引入真实 stall、不改变 GAS 语义与严格验证结果前提下，把片上 SRAM（state / idx / l0）建模能力接到主统计链路，形成可复现实验口径。

### 16.1 P0：SnnDL 侧建模接线（默认关闭）

已完成：
- 新增 SRAM 承载目录并接入模型：
  - `services/memory/sram_sim/model/BankedSramModel.{h,cc}`
  - `services/memory/sram_sim/layout/VirtualSramLayout.h`
- `WeightMemorySubsystem` 接入两条路径：
  - `idx_sram`：GCSS 索引读取统计
  - `l0_sram`：IDX2 ingress cache 读写/命中/填充/驱逐统计
- `DefaultSnnComputeCore` 接入 `state_sram` 统计：
  - `updateNeuronStates`、`applyPendingDeltas_` 等 bulk 状态访问点

约束保持：
- observe-only（仅累计 predicted cycles / conflicts / bytes），不修改请求调度与完成时序。
- 默认关闭，仅在显式开关时生效。

### 16.2 P1：统计主链路闭环（PE 侧可见）

已完成：
- `WeightMemorySubsystem -> SnnPESubComponent -> MultiCorePE` 聚合链路接线。
- `IPeAggregation::accumulateSynapseReadStats(...)` 已扩展并匹配调用方/实现方签名。
- 新统计项已在主口径可见：
  - weight path：`synapse_sram_weight_idx_*`、`synapse_sram_weight_l0_*`
  - state path：`core_state_sram_*`

### 16.3 P2：mesh_template 参数注入 + summary 聚合

已完成：
- 新增 `sst_dram_si/mesh_template/sram_calib.py`，支持离线 JSON 标定加载与 sanitize。
- `config.py/runtime.py/build.py/legacy_defaults.py` 完成 `MESH_SRAM_*` 开关注入：
  - `MESH_SRAM_MODEL_ENABLE`
  - `MESH_SRAM_CALIB_JSON`
  - `MESH_SRAM_CALIB_STRICT`
  - `MESH_SRAM_WEIGHT_IDX_ENABLE`
  - `MESH_SRAM_WEIGHT_L0_ENABLE`
  - `MESH_SRAM_STATE_ENABLE`
- `compute_essential_summary_mesh.py` 新增 `summary["sram"]`：
  - `weight_idx`
  - `weight_l0`（含 hit_rate）
  - `state`

### 16.4 可复现验证（当前机器状态）

通过项：
- `SnnDL make -j4`：通过
- 单测：
  - `test_gas_cmd_cost_offline_model.py`：通过
  - `test_compute_essential_summary_mesh_gas_bytes.py`：通过
  - `test_compute_essential_summary_mesh_nic.py`：通过

阻塞项（本机运行时，不是代码逻辑）：
- `sst --version` 失败：
  - `GLIBCXX_3.4.32 not found`
  - `GLIBC_2.38 not found`

结论：
- `P0-P2` 的代码与统计接线已完成。
- A/B 仿真闭环需在可运行的 SST 依赖环境执行（建议继续沿用 `memop` 目录承载）。

### 16.5 `memop` 口径建议（恢复运行时后直接执行）

固定 workload：
- `4x4 bcsr10k step1`（后续统一基线）

最小 A/B 设计：
- A（baseline）：`MESH_SRAM_MODEL_ENABLE=0`
- B（observe-only 总开）：`MESH_SRAM_MODEL_ENABLE=1`
- C（idx only）：`MESH_SRAM_WEIGHT_IDX_ENABLE=1, L0/STATE=0`
- D（l0 only）：`MESH_SRAM_WEIGHT_L0_ENABLE=1, IDX/STATE=0`
- E（state only）：`MESH_SRAM_STATE_ENABLE=1, IDX/L0=0`

重点验收统计：
- 语义不变：`validation.log` 严格通过，`neurons_fired_total` / `snn_tx_spike_packets_total` 与 baseline 对齐。
- 可观测性生效：`summary.sram.*` 非零且方向符合预期（`weight_l0.hit_rate`、`state.predicted_extra_cycles_total` 等）。

### 16.6 本轮闭环结果（2026-03-03 晚间复测）

已完成两组闭环（均 `4x4 bcsr10k step1, frac=0.03, L1=0, max_steps=1`）：

1. BCSR 主线（语义守恒验证）  
   - OFF: `.../2026-03-03_p0_p2_sram_observeonly_ab_v2_fix/.../20260303-213434-100580846`
   - ON : `.../2026-03-03_p0_p2_sram_observeonly_ab_v2_fix/.../20260303-214023-727655659`
   - 结果：`sim_time_actual_ns / memctrl.req_total / memctrl.bytes_est_total` 全部 `1.000x`，双侧 `validation fail=0 warn=0 strict=0`。

2. GCSSIDX2 证据组（验证 SRAM 统计触发）  
   - OFF: `.../2026-03-03_p0_p2_sram_observeonly_gcssidx2_ab_v1/.../20260303-214852-691993238`
   - ON : `.../2026-03-03_p0_p2_sram_observeonly_gcssidx2_ab_v1/.../20260303-215441-014737510`
   - 路径有效：`synapse.gcss_lookup_hit_total=762950`，`synapse.read_source.gcss_bytes_share=1.0`
   - ON 侧 `summary.sram.weight_idx`：
     - `reads_total=4577700`
     - `bytes_read_total=12970150`
     - `resident_bytes_peak=16280915`
   - A/B 主性能仍 `1.000x`，符合 observe-only 预期；双侧验证通过。

`memop` 承载：
- `memop/experiments/2026-03-03_p0_p2_sram_observeonly_ab_v2_fix/`
- `memop/experiments/2026-03-03_p0_p2_sram_observeonly_gcssidx2_ab_v1/`

### 16.7 未决项（下一步）

- `state_sram_*` 在当前主 workload 下仍为 `0`（包括 `resident_bytes_peak`），说明 state 路径存在“参数/执行路径未触发”的问题；不影响语义与主线性能，但影响证据完整性。
- 下一步建议：
  - 增加 `state-only` smoke（开 `MESH_SRAM_MODEL_ENABLE=1 + MESH_SRAM_STATE_ENABLE=1`，其余关闭）并启用高 `core_verbose` 快速定位；
  - 补一个 state-heavy 微基准，确保 state SRAM 统计可以稳定触发后再纳入论文图表。

## 17) P0 进展：Cacheline 利用率证据链（2026-03-05）

目标：把“4B 权重在 64B cacheline 语义下的放大效应”转成可直接用于论文图表的稳定指标，并纳入 `memop` 对比输出。

### 17.1 本次新增统计（summary 口径）

在 `sst_dram_si/tools/compute_essential_summary_mesh.py` 的 `gas` 段新增：

- line 基础量：
  - `gas.line_size_bytes`
  - `gas.unique_line_bytes_total`
  - `gas.covered_line_bytes_total`
- 每 line 有效负载：
  - `gas.payload_bytes_per_unique_line_avg`
  - `gas.payload_bytes_per_covered_line_avg`
- line 利用率：
  - `gas.line_utilization_unique`
  - `gas.line_utilization_unique_permille`
  - `gas.line_utilization_covered`
  - `gas.line_utilization_covered_permille`
- 对齐真实 DRAM 后端的利用率：
  - `gas.payload_bytes_per_memctrl_req_avg`
  - `gas.memctrl_payload_utilization`
  - `gas.memctrl_payload_utilization_permille`
  - `gas.memctrl_traffic_amplification`

约束处理：
- 在 `is_gas_mode` 下即使数值为 0 也输出，避免 compare 表出现大量 `NA`。

### 17.2 memop 对比表接线

`memop/tools/snapshot_experiment.py` 已新增上述字段抽取，`snapshot/compare.tsv` 会自动输出：

- 原始值列；
- `*_ratio_vs_base` 比值列。

### 17.3 快速复核（4x4 bcsr10k step1, gcss_idx2 vlf_ab_v1）

样本：`memop/experiments/2026-03-04_gcss_idx2_vlf_ab_v1/snapshot/compare.tsv`

- baseline：
  - `gas_memctrl_payload_utilization=0.0623348`
  - `gas_memctrl_traffic_amplification=16.0424`
  - `gas_payload_bytes_per_memctrl_req_avg=3.98943`
- vlf_line：
  - `gas_memctrl_payload_utilization=0.0716775`（约 `+14.98%`）
  - `gas_memctrl_traffic_amplification=13.9514`（约 `-13.03%`）
  - `gas_payload_bytes_per_memctrl_req_avg=4.58736`（约 `+14.99%`）
- vlf_run：
  - `gas_memctrl_payload_utilization=0.0712082`（约 `+14.23%`）
  - `gas_memctrl_traffic_amplification=14.0433`（约 `-12.46%`）
  - `gas_payload_bytes_per_memctrl_req_avg=4.55733`（约 `+14.23%`）

结论（当前阶段）：
- P0-1 的“cacheline 放大效应可量化证据”已打通；
- 下一步进入 P0-2：在 `GCSSIDX2 + VLF-line` 固定口径下做 `cmd-cost on/off` 消融，判断其是否仍为关键增益点。

### 17.4 P0-2：`GCSSIDX2 + VLF-line` 下 `cmd-cost` 消融（2026-03-05）

固定口径：
- `4x4 bcsr10k step1`
- `gas + gcss_valueonly_dstcore_idx2 + vlf_enable=1 + vlf_run_enable=0`
- `ramulator2_ddr5`
- `max_steps=1, step_activation_fraction=0.03`
- `force_defer=1`
- `dram_cmd_offline_model_enable=1, strict=0`（仅为允许 OFF 组构建；不改变执行语义）

对比项：
- `cmd_off`：`dram_cmd_cost_merge_enable=0`  
  run_dir：`/home/xgy/remote/sst_dram_si/outputs_large/paper2/2026-03-05_p0_gcss_idx2_vlfline_cmdcost_ab_v1/off/20260305-012733`
- `cmd_on`：`dram_cmd_cost_merge_enable=1`  
  run_dir：`/home/xgy/remote/sst_dram_si/outputs_large/paper2/2026-03-05_p0_gcss_idx2_vlfline_cmdcost_ab_v1/on/20260305-013904`

`memop` 沉淀：
- `memop/experiments/2026-03-05_p0_gcss_idx2_vlfline_cmdcost_ab_v1/cases.json`
- `memop/experiments/2026-03-05_p0_gcss_idx2_vlfline_cmdcost_ab_v1/snapshot/compare.tsv`

关键结果（A/B 完全一致）：
- `sim_time_actual_ns`：`1439179` vs `1439179`（`1.000x`）
- `memctrl.req_total`：`665263` vs `665263`（`1.000x`）
- `memctrl.bytes_est_total`：`42576832` vs `42576832`（`1.000x`）
- `gas.memctrl_payload_utilization`：`0.0716775` vs `0.0716775`（`1.000x`）
- `gas.memctrl_traffic_amplification`：`13.9514` vs `13.9514`（`1.000x`）
- `gas.cmd_cost_veto_total`：`0` vs `0`
- `gas.cmd_cost_veto_fine_gap_total`：`0` vs `0`
- `gas.cmd_cost_veto_row_window_total`：`0` vs `0`

机理解释：
- 在 `VLF-line` 路径中，段构建已经退化为“按 cacheline 覆盖、无吸洞”：
  - `gas.unique_line_count_total == gas.covered_line_count_total == 755933`
  - `gas.line_density_unique_over_covered = 1.0`
  - `gas.gap_absorbed_bytes_total = 0`
  - `gas.row_window_triggers_total = 0`
- 因此 `cmd-cost` 护栏没有可 veto 的候选吸洞事件，开关自然不产生性能差异。

结论：
- 在当前主线口径（`GCSSIDX2 + VLF-line`）下，`cmd-cost` 不是关键增益点（边际收益为 0）。
- 后续论文主线可将 `cmd-cost` 定位为“非 VLF 访问形态下的防病态护栏”，而非当前最优路径的核心贡献项。

### 17.5 进展：`GCSS VLF PreMPHF` 在主基线口径闭环（2026-03-05）

目标：
- 在不改变 GAS/SNN 语义与 step-limited 统计一致性的前提下，让 value-only 访问尽可能“按 cacheline 打包”，降低 `memctrl.req/bytes` 并提升 `payload/line` 利用率。

固定口径（与 17.4 一致的主线口径）：
- `4x4 bcsr10k step1`
- `gas`
- `ramulator2_ddr5`
- `max_steps=1, step_activation_fraction=0.03`
- `force_defer=1, step_seq_gate=1`

实验承载（memop）：
- `memop/experiments/2026-03-05_gcss_vlf_premphf_ab_v1/`
  - `cases.json`
  - `snapshot/compare.tsv`

对比项：
- baseline：`synapse_weight_mode=gcss_valueonly_dstcore_idx2`  
  run_dir：`memop/experiments/2026-03-05_gcss_vlf_premphf_ab_v1/runs/baseline/20260305-042012`
- new：`synapse_weight_mode=gcss_valueonly_dstcore_vlf_premphf`（`pilot_bits=16`）  
  run_dir：`memop/experiments/2026-03-05_gcss_vlf_premphf_ab_v1/runs/premphf/20260305-043615`

验证状态（两案一致）：
- `validation.log: fail=0 warn=0 strict=0`
- `processed==injected`，`route_miss=0`，`local_drop=0`

关键收益（new vs baseline）：
- `model.sim_time_actual_ns`：`2035318 -> 1757091`（`0.8633x`，约 `-13.67%`）
- `memhierarchy.memctrl.req_total`：`1678421 -> 1271227`（`0.7574x`，约 `-24.26%`）
- `memhierarchy.memctrl.bytes_est_total`：`107418944 -> 81358528`（`0.7574x`，约 `-24.26%`）
- `gas.payload_bytes_per_memctrl_req_avg`：`1.8183 -> 2.4007`（`1.3203x`，约 `+32.03%`）
- `gas.memctrl_payload_utilization`：`0.02841 -> 0.03751`（`1.3203x`）
- `gas.memctrl_traffic_amplification`：`35.1986 -> 26.6592`（`0.7574x`）
- `gas.apply_ns_avg`：`1213246 -> 929848`（`0.7664x`，约 `-23.36%`）

可解释的结构性变化（cacheline 视角）：
- `gas.covered_line_count_total`：`1678421 -> 1271227`（`0.7574x`）直接对应 memctrl 请求数下降
- `gas.unique_line_count_total`：`740044 -> 498212`（`0.6732x`），表示“需要触碰的独特 line”进一步减少
- `gas.payload_bytes_per_unique_line_avg`：`4.124 -> 6.126`（`1.485x`），说明每个 unique line 承载更多有效权重

机理解释（为什么这条路径能降 memctrl.req/bytes）：
- `PreMPHF` 索引提供 `(pre_global -> (base,len))` 与 `pre_rank`，从而把权重地址变成 `addr = base + pre_rank` 的连续流；
- `VLF` 在 `BeginApply` 前将 window 内的权重读按 `addr` 稳定排序并按 line 聚簇，使更多权重命中同一 cacheline；
- 因此在 `memory.memory_requests` 与 `gas.payload_bytes_total` 不变的前提下，`covered_line_count_total/memctrl.req_total` 显著下降，最终体现为 `memctrl.bytes_est_total` 与 `sim_time_actual_ns` 下降。

附：索引成本（现状，如实记录）：
- 对应离线权重目录：`sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_fanout256_10k_v2_p16_j32/manifest.json`
- 当前该目录的 `index_to_values_ratio≈0.472`，`index_bits_per_edge≈15.10`；相比 IDX2（Row-MPHF）的 `values/10` 目标仍偏大，需要后续继续压缩（但本节的主线收益来自 memctrl 事务减少，而非 SRAM 常驻索引节省）。

### 17.6 进展：方案 A（PreMPHF 索引压缩 v2 / EF-base）已落地并闭环（2026-03-05）

目标：
- 在不改变 GAS 语义、不改变 `full_vlf(line,no-hole)` 主线性能结果前提下，把 `premphf` 常驻索引压到 `values` 的 `1/10` 以内。

本次代码落地：
- 离线生成器：
  - `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf.py`
  - 新增 `--index-version {1,2}` 与 `--ef-select-step`
  - `v2` 使用 `Elias-Fano(slot_base + terminal edges_total)`，`slot_len` 不再显式存储（运行时由 `base[i+1]-base[i]` 推导）
- 运行时加载器：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/GcssIndexPreMphf.h`
  - 支持 `version=1/2` 双格式加载；`lookup(pre)->(base,len)` API 保持不变
  - `v2` 增加 EF decode（`select1 + lowbits`）路径

全量离线生成（320 cores）：
- 输出目录：
  - `sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_fanout256_10k_v3_ef_j32/`
- 关键统计（manifest）：
  - `index_total_bytes=10,734,730`
  - `values_total_bytes=163,840,000`
  - `index_to_values_ratio=0.06552`
  - `index_bits_per_edge=2.0966`

闭环实验（memop）：
- 目录：
  - `memop/experiments/2026-03-05_gcss_vlf_premphf_v2ef_ab_v1/`
  - `cases.json`
  - `snapshot/compare.tsv`
  - `snapshot/evidence_v2ef_index.json`
- Case A（baseline）：`premphf_v1_full_vlf`
  - run_dir：`.../runs/v1_full_vlf/20260305-191024`
- Case B（new）：`premphf_v2ef_full_vlf`
  - run_dir：`.../runs/v2ef_full_vlf/20260305-192039`

闭环结果：
- 语义严格性：两案均 `validation.log: fail=0 warn=0 strict=0`
- 性能与流量指标：两案完全一致（`sim_time_actual_ns`、`memctrl_req_total`、`payload_utilization` 等均 `1.000x`）
- 索引成本（summary `synapse.index_cost`）：
  - `index_to_values_ratio`: `0.47192 -> 0.06552`（下降约 `86.1%`）
  - `index_bits_per_edge`: `15.10 -> 2.10`
  - `index_total_bytes`: `77,319,162 -> 10,734,730`（`0.1388x`）

结论：
- 方案 A 已满足“索引压到 values 的 1/10 以下”目标，并且不改变主线 `full_vlf` 的性能与语义结果，可作为主线可合入项。

## 18) 当前内存系统现状总览（2026-03-05）

统一口径：
- `4x4 bcsr10k step1`
- `ramulator2_ddr5`
- `apply_issue_policy=order`
- `validation.log: fail=0 warn=0 strict=0`

已实现内存优化与当前判定：
- `GCSSIDX2(Row-MPHF, row-major values)`：有效，且已证明 `index_to_values_ratio≈0.099`，达到 `values/10` 级别。
- `GCSS-VLF PreMPHF(v1)`：有效，能显著降低 `memctrl_req/bytes` 并提升 `payload_utilization`；但索引开销过大（`~0.472`）。
- `GCSS-VLF PreMPHF(v2, EF-base)`：有效，保持 v1 性能与语义，同时把索引降到 `~0.0655`（优于 `values/10` 目标）。
- `full_vlf(line,no-hole)`：关键增益项，已形成强证据链（`line_density=1.0`，`memctrl_req` 显著下降）。
- `cmd-cost 护栏`：在 `VLF-line` 主线下 `veto=0`，收益归零；当前定位应是“非 VLF 路径防病态护栏”，不属于主线增益来源。
- `SRAM observe-only(state/idx/l0)`：统计链路已打通，主性能不受影响；目前是“可观测基础设施”，不是直接性能优化项。

当前主线推荐组合（memory）：
- 运行时主线：
  - `gcss_valueonly_dstcore_vlf_premphf`
  - `MESH_GAS_VLF_ENABLE=1`
  - `MESH_GAS_VLF_RUN_ENABLE=0`
  - `apply_issue_policy=order`
- 数据格式主线：
  - `premphf index v2(EF-base)`（目录：`..._v3_ef_j32`）
- 非主线项：
  - `cmd-cost` 作为 guardrail 保留，但不计入主线收益构成。

## 19) 已移除路径归档（2026-03-05）

本节记录主线清理动作：`GCSS-PRE Cacheline-Fit (v3)` 已从代码中物理移除，避免后续误用。

已移除内容：
- 生成器侧：`sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf.py`
  - 移除 `index_version=3`、`--cacheline-fit`、`--line-bytes` 及其数据布局实现。
- 运行时侧：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/GcssIndexPreMphf.h`
  - 移除 `GCSSVLFP version=3` 解析分支与 `pad_after/true_len` 解码逻辑。

归档说明：
- 历史 CLFIT 对比实验与数据目录仍保留在 `memop/experiments` 与 `sst_dram_si/weights/*clfit*`，仅用于历史复盘，不再作为主线可运行路径。

## 20) 当前稳定主线（2026-03-06 定版）

### 20.1 正式命名

当前 memory 主线正式命名为：
- `GCSS-GLIDE`

建议论文口径展开：
- `GLIDE: Graph-Locality-preserving Index for DRAM-Efficient SNN Execution`

含义：
- `GCSS`：我们现有的 values-only synapse storage 主路径；
- `GLIDE`：强调这条索引路径的核心不是“更激进地改 values 布局”，而是
  **在保持 graph/profile locality 不变的前提下，压缩索引并守住 DRAM 行为**。

如果以后写系统名，推荐使用：
- `GAS + GCSS-GLIDE`

其中：
- `GAS` 是你们更大的系统/执行语义主线；
- `GCSS-GLIDE` 是当前 memory hierarchy 中最稳定、最可归纳的一个关键子机制。

### 20.2 主线构成（唯一推荐口径）

当前唯一稳定、可合入、可用于论文主图的 memory 主线为：
- `physical_order_mode=profile_greedy`
- `index_version=7`
- format：`gcss_valueonly_dstcore_vlf_premphf_plp_v7_lpbl`
- artifact：
  - `sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_v7_lpblp_j8/`
- A/B 闭环：
  - `memop/experiments/2026-03-06_gcss_plp_v7_lpbl_ab_v1/`

主线机理：
- 保持 `profile_greedy` 的 physical pre order 不变；
- 保持 values layout 不变；
- 保持 `pre_global -> sid -> rank` 的 `v6 OKSR` 路径不变；
- 只把 `rank -> (base,len)` 从 `base_by_rank Elias-Fano` 替换成 `GLIDE` 的 locality-preserving block codec。

更直白地说：
- `GCSS-GLIDE` 的核心创新不是“重排更多值数据”，
- 而是“证明在 DRAM/cacheline locality 已由 `profile_greedy` 定好后，索引层仍可继续显著压缩，且不破坏 runtime memory behavior”。

### 20.3 主线证据链

统一口径：
- `4x4 bcsr10k step1`
- `ramulator2_ddr5`
- `apply_issue_policy=order`
- `MESH_GAS_VLF_ENABLE=1`
- `MESH_GAS_VLF_RUN_ENABLE=0`

静态结果（manifest）：
- `index_total_bytes = 15,986,156`
- `values_total_bytes = 163,840,000`
- `index_to_values_ratio = 0.09757175`
- `index_bits_per_edge = 3.12229609`

对比 `v6 OKSR`：
- `index_to_values_ratio: 0.11285300 -> 0.09757175`
- `index_bits_per_edge: 3.61129609 -> 3.12229609`

runtime 闭环（对比 `v6 OKSR`）：
- `sim_time_actual_ns = 1086400 -> 1086400`
- `memctrl_req_total = 150110 -> 150110`
- `memctrl_bytes_est_total = 9607040 -> 9607040`
- `gas_payload_bytes_per_memctrl_req_avg = 20.3304 -> 20.3304`
- `gas_memctrl_payload_utilization = 0.317663 -> 0.317663`
- `gas_memctrl_traffic_amplification = 3.14799 -> 3.14799`
- `gas_apply_ns_avg = 233858.875 -> 233858.875`
- `validation.log`: `fail=0 warn=1 strict=0`

结论：
- `GCSS-GLIDE` 已经满足当前主线要求：
  - `index_to_values_ratio <= 0.1`
  - runtime 关键 memory 指标不回退
  - 不改变 GAS 语义
  - 不破坏严格验证口径

### 20.4 归档项（不再作为主线叙事）

下面这些版本保留为历史探索证据，但不再作为当前主线叙事的一部分：

- `v4 bucket-block local-MPHF`
  - 问题：结构更复杂，但主线价值不足；不是最终稳定口径。
- `v5 layout-preserving block permutation codec`
  - 价值：证明“保 values 布局是必要条件”；
  - 结论：本身 codec 收益不足，不作为最终主线。
- `v6 OKSR`
  - 价值：提供了从 `slot` 坐标切到 `ordered key sid` 的关键中间台阶；
  - 结论：现在保留为稳定前代 baseline，不再是最终主线。
- `v6_sr_block2`
  - 价值：证明索引可以进一步压到 `<=0.1`；
  - 问题：打散 `profile_greedy` locality，导致 `memctrl_req/overfetch/payload_utilization` 回退；
  - 结论：明确归档，不能进入主线。

因此，文档与论文中不应再把这些版本并列描述为“当前可选方案”，而应统一口径为：
- 只有 `GCSS-GLIDE` 是当前 memory 主线；
- 其余均为发展路径上的论证节点或归档实验。

### 20.5 论文视角下的定位

从体系结构论文角度，`GCSS-GLIDE` 的价值不在于“孤立地看像一个通用压缩算法”，而在于它恰好补上了你们 DRAM-based SNN 主线里一个非常关键的空缺：
- 你们已经有 `GAS` 语义与 `profile_greedy` 所建立的 values/cacheline locality；
- 但如果索引过大，就会削弱“DRAM-based、大权重集、片上只放必要元数据”的系统叙事；
- `GCSS-GLIDE` 证明：
  - 在不扰动 locality 的前提下，索引仍可压到 `values` 的 `1/10` 以下；
  - 同时完全守住端到端 DRAM 行为与严格语义结果。

这使它更像是：
- 一个**面向 DRAM-based SNN accelerator 的 locality-preserving index co-design**，
- 而不是纯软件后处理或离线工程微调。

### 20.6 当前最终结论

截至 2026-03-06，memory 主线应固定为：
- `GAS + GCSS-GLIDE`

其中：
- `GAS` 承担系统语义与执行主线；
- `GCSS-GLIDE` 承担 DRAM-friendly synapse storage/index 主线。

后续若继续写文档、做图、写论文，推荐统一采用这一口径：
- 当前唯一主线：`GCSS-GLIDE`
- 历史归档项：`v4 / v5 / v6 OKSR / v6_sr_block2`
- 后续优化原则：
  - 只压 index codec；
  - 不再扰动 `profile_greedy` values locality。
