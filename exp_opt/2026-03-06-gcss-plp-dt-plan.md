# GCSS-PLP-DT: Cross-Pre Line Packing on Ramulator2-Truth DRAM

## 1. 背景与问题重述

当前主线 memory 口径：

- workload：`4x4 bcsr10k step1`
- backend：`ramulator2_ddr5`
- runtime 主线：`gcss_valueonly_dstcore_vlf_premphf + full_vlf(line,no-hole)`
- strict 验收：`validation.log: fail=0 warn=0 strict=0`

当前最好主线已经拿到的收益：

- `PreMPHF(v2, EF-base)` 已把 index 压到 `values` 的 `1/10` 以下。
- `full_vlf(line,no-hole)` 已经显著降低 `memctrl_req_total / memctrl_bytes_est_total`。

但当前主线的剩余问题仍然明显：

- `gas_memctrl_payload_utilization` 仍只有约 `0.196`。
- `gas_payload_bytes_per_memctrl_req_avg` 仍只有约 `12.56B`，远小于一条 `64B` cacheline。
- 当前每 core 平均 `edges_total / pre_count ≈ 4.59`，意味着“单个 pre 段内连续”天然很短；单纯依赖 intra-pre 连续性，理论上线利用率本来就不高。

这说明：

1. `per_post retire`、`cmd-cost`、`bank-table` 这类运行时局部调度，不再是主瓶颈。
2. 当前真正剩下的浪费，来自 **value plane 的物理布局**：短 `pre segment` 被按 `slot order`（近似 hash 顺序）串写到 DRAM，破坏了跨 pre 的 cacheline 共享机会。

## 2. 核心设计：GCSS-PLP-DT

### 2.1 目标

在不改变 GAS 语义、不改变 `pre_rank` 语义、不放宽 strict validation 的前提下，
把现有 `GCSS-VLF` 从“只吃 intra-pre 连续性”升级为“同时吃 cross-pre cacheline 共享”。

目标不是近似压缩 value，也不是改变权重语义；目标是：

- 保持 `lookup(pre) -> (base, len)` API 不变；
- 保持 `widx = base + pre_rank` 不变；
- 仅改变不同 `pre` 段在 `values` 里的**相对物理顺序**；
- 让经常在同一 apply window 中出现的短 `pre segment` 被物理上放到相邻位置，提升同一 cacheline 被多个 active pre 共同消费的概率。

### 2.2 名称

`GCSS-PLP-DT`

- `PLP`：Profile-Guided Cross-Pre Line Packing
- `DT`：DRAM-Truth（后续目标函数与 Ramulator2 的 line/row/bank 几何一致）

## 3. 设计原则

### 3.1 不改变语义

以下语义必须保持严格不变：

- `(pre_global, post_local) -> weight` 的精确映射不变。
- `pre_rank` 语义不变。
- `acc_update(post_local, delta)` 的提交顺序语义不变。
- `validation.log` 必须保持 `fail=0 warn=0 strict=0`。

也就是说，本方案是一个 **exact layout transformation**，不是压缩近似或调度近似。

### 3.2 强隔离

实验实现必须与当前主线强隔离：

- 新 generator 文件。
- 新 weight mode 名字。
- 新目录变量。
- 新文件后缀。

避免污染当前 `gcss_valueonly_dstcore_vlf_premphf` 主线。

## 4. 数据格式设计

### 4.1 新 experimental mode

- `synapse_weight_mode = gcss_valueonly_dstcore_vlf_premphf_plp`
- 环境变量目录：`MESH_GCSSPLP_DIR`

### 4.2 输出文件

每 core 一套：

- `peXX/coreYY.gcssplp.bin`
- `peXX/coreYY.gcssplp.idx.bin`
- `peXX/coreYY.gcssplp.meta.json`
- `manifest.json`

### 4.3 与现有 PreMPHF 的兼容方式

索引 header 接口名仍复用现有 `GCSSVLFP` 体系，但当前实际落地只支持 `v1 slot-array` 版本，不复用主线 `v2 EF-base`。

关键兼容点：

- `slot -> pre` 映射仍由 MPHF/pilot 决定；
- 但 `slot_base[slot]` 不再按 `slot order` 单调累加构造；
- 而是由新的 `physical_pre_order` 决定：
  - 先按新的物理顺序为每个 `pre` 分配 `base`
  - 再回填到 `slot_base[slot(pre)]`

这带来一个重要实现现实：

- 主线 `v2 EF-base` 依赖 `slot_base[slot]` 在 slot 顺序上的单调性；
- 而 `PLP` 的任意物理重排会破坏这条单调性；
- 因此本轮实验实现退回到 `v1 slot-array` 索引。

因此运行时仍然只需要：

- `lookup(pre) -> (base, len)`
- `widx = base + pre_rank`

不需要改动权重寻址语义。

## 5. 物理布局算法

### 5.1 当前问题的本质

当前 `values` 是按 `slot_keys` 顺序串写。`slot_keys` 来自 MPHF 放置结果，本质上接近 hash 顺序。
这会把运行时经常同窗出现的多个短 `pre segment` 打散到 DRAM 的远处，导致：

- `addr-sort + VLF` 只能吃到“单个 pre 段内”的连续性；
- 很难形成“多个 active pre 共同填满一条 line”的情况。

### 5.2 新的 `physical_pre_order`

本轮落地三种 order mode：

1. `slot_order`
   - 完全复现当前主线布局，仅换新文件名，用作对照。
2. `pre_global_order`
   - 按 `pre_global` 升序布局，去掉 MPHF slot 顺序对物理布局的干扰。
3. `profile_greedy`
   - 使用运行时导出的 per-window `pre` 首触序列，做离线重排。

### 5.3 `profile_greedy` 具体算法

运行时为每个 core 导出每个 window 的 `pre` 首触顺序序列：

- 不是完整边列表
- 不是全对全共现矩阵
- 而是线性长度的 first-touch sequence

离线构造：

- `freq[pre]`：该 `pre` 在多少窗口中被触发
- `trans(pre_i, pre_j)`：在序列中相邻或短 lookahead 内共同出现的转移权重

贪心排布：

- 从最高频 `pre` 开始；
- 每次优先把与当前 `pre` 过渡权重最高的未放置 `pre` 接到后面；
- 如果没有边，则回退到全局最高频未放置 `pre`；
- tie-break：`freq desc -> len(desc) -> pre asc`。

这会把“经常一起出现在窗口里的短 pre 段”物理上排到一起，提升跨 pre line 共享概率。

## 6. DRAM-Truth 目标（文档完整方案）

本轮代码只先落地 `PLP` 本体；`DT` 目标函数先在文档中定义，后续继续扩展。

完整 `DT` 目标应包括：

- `line sharing reward`
- `segment straddle penalty`
- `row cross penalty`
- `bank hotspot penalty`

后续扩展为：

- 读取 Ramulator2 cfg 的 `line/row/bank/ch/rank` 几何；
- 把 `physical_pre_order` 从单纯 profile 聚类，扩展成 `profile + line + row/bank` 联合优化。

## 7. 运行时接入设计

### 7.1 运行时主链路保持不变

沿用现有：

- `SnnWorkload` 记录 `pre_rank`
- `WeightMemorySubsystem::lookupGcssPreBaseLen_(pre)`
- `widx = base + pre_rank`
- `addr-sort`
- `full_vlf(line,no-hole)`

因此运行时主收益来自：

- **更好的物理地址布局**
- 而不是新增 issue/retire 逻辑

### 7.2 本轮新增的运行时辅助能力

新增一个严格隔离的 profile export：

- 参数：`experimental_pre_window_profile_export_dir`
- 默认关闭
- 开启后在 `BeginApply` 导出当前窗口的 `pre` 首触顺序

导出格式（每 core 一份 csv）：

- `window_id`
- `pre_count`
- `pre_touch_order`

这条链路仅用于离线生成 `PLP` 布局，不参与功能语义。

## 8. 统计与证据链

### 8.1 必要主指标

沿用现有 `memop` 主指标：

- `sim_time_actual_ns`
- `memctrl_req_total`
- `memctrl_bytes_est_total`
- `gas_payload_bytes_per_memctrl_req_avg`
- `gas_memctrl_payload_utilization`
- `gas_memctrl_traffic_amplification`
- `gas_apply_ns_avg`

### 8.2 本轮先复用已有指标

本轮落地先不新增 summary 统计项，先看是否能通过已有主指标观察到收益。

若出现收益，再进入下一轮补 runtime 机理统计，例如：

- `gas_cross_pre_lines_total`
- `gas_distinct_pres_per_covered_line_avg`
- `gas_lines_with_multi_pre_total`

### 8.3 离线 meta 证据

`gcssplp.meta.json / manifest.json` 额外记录：

- `physical_order_mode`
- `profile_windows`
- `profile_unique_pres`
- `global_lines_with_multi_pre`
- `global_avg_pres_per_line`
- `profile_adjacent_pairs_total`
- `profile_adjacent_pairs_same_line_est`

这些指标用于解释布局本身是否真的增强了 cross-pre packing。

## 9. 闭环实验计划（memop 承载）

实验目录：

- `memop/experiments/2026-03-06_gcss_plp_dt_ab_v1/`

### 9.1 Case 矩阵

1. `baseline_vlf_profile`
   - 当前主线：`gcss_valueonly_dstcore_vlf_premphf` + profile export
2. `plp_pre_global`
   - 新 mode：`gcss_valueonly_dstcore_vlf_premphf_plp`
   - `order_mode=pre_global_order`
3. `plp_profile`
   - 新 mode：`gcss_valueonly_dstcore_vlf_premphf_plp`
   - `order_mode=profile_greedy`

### 9.2 闭环步骤

Step A：profile collect

- 基于当前主线跑一次 profiling run
- 导出 per-core `pre touch order`

Step B：生成 PLP weights

- 用 profiling run 导出的 profile 生成 `gcssplp` 目录

Step C：A/B run

- baseline 与两个 PLP case 在同口径下复测

Step D：snapshot

- `python3 memop/tools/snapshot_experiment.py --exp-dir ...`

### 9.3 验收标准

所有 case 必须满足：

- `validation.log: fail=0 strict=0`
- 允许出现当前 step-limited 口径下的已知告警：
  - `paper.step_limited.processed_equals_injected`
  - 含义是 within-step cascade allowed，不代表语义错误

本轮成功判据：

- 至少一个 PLP case 相对 baseline：
  - `gas_memctrl_payload_utilization` 上升
  - `memctrl_req_total` 下降或不升
  - `sim_time_actual_ns` 不劣化，最好下降

## 10. 本轮落地范围

本轮只实现最小可闭环版本：

1. 新文档（本文件）
2. 新 generator：`gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`
3. 新 mode：`gcss_valueonly_dstcore_vlf_premphf_plp`
4. 新目录变量：`MESH_GCSSPLP_DIR`
5. 运行时 profile export
6. `memop` A/B 闭环实验

本轮**不**实现：

- 真正的 row/bank 联合优化目标
- 新 summary proof metric
- 在线动态 remap

## 11. 预期

如果判断正确，则 `PLP` 的收益应该体现为：

- `payload_utilization` 上升
- `payload_bytes_per_memctrl_req_avg` 上升
- `memctrl_req_total / memctrl_bytes_est_total` 下降

若 `pre_global_order` 都能优于 baseline，则说明当前最大问题之一就是“slot order 破坏了物理局部性”；
若 `profile_greedy` 继续优于 `pre_global_order`，则论文主线可以进一步升级为“profile-guided cross-pre packing”。


## 12. 当前实际落地状态（2026-03-06）

### 12.1 已落地代码

Python / runtime plumbing：

- `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`
- `sst_dram_si/mesh_template/config.py`
- `sst_dram_si/mesh_template/runtime.py`
- `sst_dram_si/mesh_template/entry.py`
- `sst_dram_si/mesh_template/build.py`
- `sst_dram_si/tools/compute_essential_summary_mesh.py`
- `memop/tools/snapshot_experiment.py`

C++ runtime path：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponentConfig.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`

### 12.2 已落地功能

1. 新 experimental mode：`gcss_valueonly_dstcore_vlf_premphf_plp`
2. 新目录变量：`MESH_GCSSPLP_DIR`
3. 新 profile export：
   - `experimental_pre_window_profile_export_enable`
   - `experimental_pre_window_profile_export_dir`
4. 新离线布局模式：
   - `slot_order`
   - `pre_global_order`
   - `profile_greedy`
5. 新文件产物：
   - `coreYY.gcssplp.bin`
   - `coreYY.gcssplp.idx.bin`
   - `coreYY.gcssplp.meta.json`
6. `memop` 闭环目录：
   - `memop/experiments/2026-03-06_gcss_plp_dt_ab_v1/`

### 12.3 实现限制与原因

当前实现最重要的现实限制：

- `PLP` 还没有把主线 `PreMPHF(v2, EF-base)` 带过来；
- 实际索引格式是 `gcss_valueonly_dstcore_vlf_premphf_plp_v1_slotarrays`；
- 原因不是工程偷懒，而是数据结构约束：
  - `EF-base` 依赖 `slot_base[slot]` 单调；
  - `PLP` 会按 `physical_pre_order` 任意重排 pre 段；
  - 导致 `slot_base[slot(pre)]` 在 slot 维度上非单调，现有 EF 编码无法直接承载。

因此本轮 PLP 的价值结论应当表述为：

- `value-plane physical layout` 优化本身已经被验证有效；
- 但 `index-plane` 还没有同步回到主线压缩形态；
- 后续若要主线合入，需要继续设计“支持非单调 base 的压缩索引”。

### 12.4 profile_greedy 生成器的实现现实

首版 `profile_greedy` 生成器曾出现明显过慢问题，原因是近似 `O(pre_count^2)` 的全扫描贪心。
本轮已改成：

- 预构建对称 neighbor preference lists
- lazy neighbor walk
- 全局 fallback order 预排序

这样在 `4x4 bcsr10k step1` 口径下，profile-guided 版本已能闭环生成并进入运行实验。

## 13. 闭环实验结果（memop）

### 13.1 Profiling baseline

- run_dir：`/home/xgy/remote/memop/experiments/2026-03-06_gcss_plp_dt_ab_v1/runs/baseline_vlf_profile/20260306-035702`
- weight mode：`gcss_valueonly_dstcore_vlf_premphf`
- profile 导出目录：`gcssplp_profiles/`
- 导出文件数：`320`
- validation：`fail=0 warn=1 strict=0`
- 已知 warning：`paper.step_limited.processed_equals_injected`（within-step cascade allowed）

baseline 主指标：

- `sim_time_actual_ns = 1,189,140`
- `memctrl.req_total = 243,006`
- `memctrl.bytes_est_total = 15,552,384`
- `gas.payload_bytes_per_memctrl_req_avg = 12.56B`
- `gas.memctrl_payload_utilization = 0.1962`
- `gas.memctrl_traffic_amplification = 5.096`

### 13.2 Offline artifact 结果

`pre_global_order` 目录：

- `/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_preglobal_v1_j8`
- `index_to_values_ratio = 0.4719`
- `index_bits_per_edge = 15.10`
- `avg_pres_per_line_global = 4.266`
- `multi_pre_line_ratio_global = 0.9862`

`profile_greedy` 目录：

- `/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_profile_v2_j8`
- `index_to_values_ratio = 0.4719`
- `index_bits_per_edge = 15.10`
- `profile_adjacent_pairs_total = 323,416`
- `profile_adjacent_pairs_same_line_est = 291,761`
- `avg_pres_per_line_global = 4.263`
- `multi_pre_line_ratio_global = 0.9855`

解释：

- 两个 PLP 版本的 index 成本相同，因为都使用 `v1 slot-array`；
- `profile_greedy` 的核心差别不在 index，而在“把 profile 邻近的 pre 段压到同一批 line 附近”。

### 13.3 A/B/C 运行结果

实验快照：

- `memop/experiments/2026-03-06_gcss_plp_dt_ab_v1/cases.json`
- `memop/experiments/2026-03-06_gcss_plp_dt_ab_v1/snapshot/compare.tsv`

三组 run_dir：

1. baseline：`/home/xgy/remote/memop/experiments/2026-03-06_gcss_plp_dt_ab_v1/runs/baseline_vlf_profile/20260306-035702`
2. pre-global：`/home/xgy/remote/memop/experiments/2026-03-06_gcss_plp_dt_ab_v1/runs/plp_preglobal/20260306-041813`
3. profile：`/home/xgy/remote/memop/experiments/2026-03-06_gcss_plp_dt_ab_v1/runs/plp_profile/20260306-042822`

关键结果：

- `plp_preglobal` 相对 baseline：
  - `sim_time_actual_ns`: `1,189,140 -> 1,170,004`（`-1.61%`）
  - `memctrl_req_total`: `243,006 -> 238,481`（`-1.86%`）
  - `memctrl_bytes_est_total`: `15,552,384 -> 15,262,784`（`-1.86%`）
  - `gas_payload_bytes_per_memctrl_req_avg`: `12.56B -> 12.80B`（`+1.90%`）
  - `gas_memctrl_payload_utilization`: `0.1962 -> 0.2000`（`+1.90%`）
  - `gas_apply_ns_avg`: `319,296 -> 310,004.6`（`-2.91%`）

- `plp_profile` 相对 baseline：
  - `sim_time_actual_ns`: `1,189,140 -> 1,086,400`（`-8.64%`）
  - `memctrl_req_total`: `243,006 -> 150,110`（`-38.23%`）
  - `memctrl_bytes_est_total`: `15,552,384 -> 9,607,040`（`-38.23%`）
  - `gas_payload_bytes_per_memctrl_req_avg`: `12.56B -> 20.33B`（`+61.89%`）
  - `gas_memctrl_payload_utilization`: `0.1962 -> 0.3177`（`+61.89%`）
  - `gas_memctrl_traffic_amplification`: `5.096 -> 3.148`（`-38.23%`）
  - `gas_apply_ns_avg`: `319,296 -> 233,858.9`（`-26.76%`）

### 13.4 机理解读

这个结果非常关键，因为它说明：

- 收益主要来自“每次真正 payload 对应的 DRAM line 请求数变少了”；
- 不是来自更好的 DRAM row-hit；
- 也不是来自改变 GAS 提交语义。

证据是：

- `plp_profile` 的 `gas_memctrl_payload_utilization` 明显上升；
- `payload_bytes_per_memctrl_req_avg` 从 `12.56B` 抬到 `20.33B`；
- 但 `ramulator2.row_hit_rate_total` 从 `0.7839` 下降到 `0.7209`；
- `ramulator2.avg_read_latency_0_avg` 基本不变：`33.48 -> 33.54`。

因此，PLP 当前打中的不是 row-buffer locality，而是：

- 在 cacheline 语义下，减少“为了多个零碎 4B 权重去拉多条 64B line”的浪费；
- 让更多 active pre 的小 segment 共用更少的 line。

### 13.5 当前结论

1. `pre_global_order` 已经优于 baseline，证明当前主线确实存在 `slot_order/hash-order` 破坏 value-plane 物理局部性的现象。
2. `profile_greedy` 明显优于 `pre_global_order`，证明“按运行时窗口邻接关系做 cross-pre line packing”是真正有效的增益来源。
3. 当前方案不改变 `(pre_global, post_local) -> weight` 映射，不改变 `pre_rank`，运行结果保持 `fail=0 strict=0`，因此语义仍然是 exact 的。
4. 当前最主要短板不在收益，而在 index 成本：`index_to_values_ratio = 0.4719`，远高于主线 `PreMPHF(v2, EF-base)` 的水平。

## 14. 下一步

最合理的下一步不是继续“榨更多 PLP 收益”，而是补上主线可合入所需的索引闭环：

1. 设计能承载“非单调 slot_base”的压缩索引，使 `PLP` 回到 `index << values` 的主线目标。
2. 在 summary 中补一两个更直接的机理统计，例如：
   - `gas_distinct_pres_per_covered_line_avg`
   - `gas_lines_with_multi_pre_total`
3. 在 `DT` 方向继续引入 Ramulator2 几何感知目标，看 `profile + row/bank truth` 是否还能进一步降低请求数而不伤害 row-hit。
