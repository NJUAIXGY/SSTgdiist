# ATLAS-LAP / ATLAS-LSS 下一阶段具体任务书

> 日期：2026-03-12  
> 状态：plan-only  
> 基线：`full_system_baseline = DRAM-based SNN + GAS + GCSS-GLIDE + STORM + MulticastRouter`  
> 前置实验：`mainexp/experiments/2026-03-12_atlas_pe_storage_only_ab_v1`

## 0. 一句话结论

`ATLAS-PE storage-only B2` 已经证明两件事：

1. **功能层面是成立的**
   - `gcss_valueonly_dstpe_atlas_v1` 已打通；
   - 严格验证 `fail=0 warn=0`；
   - `atlas_pe.token_to_line_collapse_ratio = 3.15x`，说明 token 侧 collapse 真实存在。
2. **但 storage-only 本身不是正确的收益层**
   - `sim_time_actual_ns +34.44%`
   - `memctrl.req_total +61.61%`
   - `payload_bytes_per_req -38.12%`

因此，下一步不能继续把主任务定义成“优化 storage-only atlas”，而必须分成两段：

- **P0 / ATLAS-LAP**：用最低风险代价验证“values 不按 cacheline 对齐”到底占多大责任
- **P1 / ATLAS-LSS**：把 ATLAS 从“共享存储空间”推进到“共享 line 服务对象”

换句话说：

- `ATLAS-LAP` 是 **止损/证伪层**
- `ATLAS-LSS` 是 **真正有论文价值的主任务**

---

## 1. 当前已知事实与边界

## 1.1 已知正确的东西

当前可以视为已经站住脚的事实：

- `dstcore + GCSS-GLIDE + STORM + MulticastRouter` 是当前完整系统主线
- `ATLAS-PE storage-only` 的语义链已经打通
- baseline 与 atlas storage-only 都通过 paper profile 验证
- `ATLAS` sidecar 统计链已经稳定落到：
  - `atlas_pe.tokens_total`
  - `atlas_pe.unique_pres_total`
  - `atlas_pe.multicore_pres_total`
  - `atlas_pe.lines_planned_total`
  - `atlas_pe.line_consumers_total`
  - `atlas_pe.token_to_line_collapse_ratio`

这意味着：

- 我们已经拥有继续做 ATLAS 的 **观测入口**
- 不需要再回到“纯设计、无统计抓手”的状态

## 1.2 已知失败的东西

`ATLAS-PE storage-only` 的核心失败不是语义错，而是体系结构层次不对：

- 它只做了 `storage domain uplift (dstcore -> dstpe)`
- 但没有做 `service domain uplift (per-core line issue -> PE-shared line service)`

于是出现：

- `frontend_staged_reads_total` 不变
- `frontend_granules_built_total` 上升
- `unique_line_count_total` 上升
- `payload_utilization` 下降

而且有非常直接的证据：

- `320` 个 core slice 中只有 `34` 个 `values_base % 16 == 0`
- 大量 slice 从 cacheline 中间起始

所以当前 ATLAS storage-only 的本质问题是：

> **既没有共享 line 服务，又破坏了原主线 per-core values 的天然 line 对齐。**

## 1.3 下一阶段的硬边界

后续所有任务必须遵守下面四条约束：

1. **不改变 GAS 严格语义**
   - `Gather/Apply/Scatter` 语义不变
   - 退役顺序合同不变
2. **不破坏 paper profile 口径**
   - `validation fail=0 warn=0`
3. **不把 atlas 失败路径误并入主线**
   - 所有新特性都必须实验性强隔离
4. **不再把“共享存储空间”误当作收益**
   - 下一阶段必须围绕 `line service` 展开

---

## 2. 总体路线图

## 2.1 路线分层

下一步任务按两层推进：

### Phase 0：ATLAS-LAP

目标：

- 只验证“cacheline 对齐”是不是当前 storage-only 回退的大头

特点：

- 不改变 runtime 主体语义
- 不引入新的共享 line service
- 只改 generator / metadata / 少量 build 装配

### Phase 1：ATLAS-LSS

目标：

- 把 `token collapse` 变成真实的 `shared line service`

特点：

- 新增 PE-shared line service 对象
- 新增 offline `line descriptor` 数据结构
- 新增 runtime line issue / fanout 路径

## 2.2 优先级结论

推荐的执行顺序是：

1. **先做 LAP**
   - 快速验证 misalignment 责任占比
2. **再做 LSS offline**
   - 证明“共享 line packing”有理论空间
3. **最后做 LSS runtime**
   - 让 line packing 变成真实 memory service

不推荐直接跳过 LAP 的原因是：

- 如果当前性能回退主要来自 misalignment，而不是 service 层设计缺失，
  那么直接进入 LSS runtime 会把两个问题耦合，调试成本极高。

---

## 3. Phase 0：ATLAS-LAP

## 3.1 目标定义

`ATLAS-LAP = ATLAS Line-Aligned Packing`

这是一个低风险验证任务，其目标不是获得收益，而是验证：

> 当前 storage-only 的回退，到底有多大比例来自 `PE-shared values` 的非对齐切片。

本阶段不引入任何新的共享 line 服务结构，仍然保持：

- `per-core idx`
- `PE-shared values`
- `runtime bias`
- 当前 atlas runtime/sidecar 统计链

变化只有一个：

- **每个 core slice 的起点必须按 64B 对齐**

即：

- `values_base % 16 == 0` 对所有 core slice 成立

## 3.2 预期机理

如果 misalignment 是当前退化的核心原因，那么在 LAP 后应观察到：

- `payload_bytes_per_memctrl_req_avg` 明显回升
- `unique_line_count_total` 明显下降
- `memctrl.req_total` 明显下降
- `sim_time_actual_ns` 有显著修复

如果这些指标没有明显回升，则说明：

- storage-only 的问题不只是对齐
- 也证明“仅做 values layout 修补，不做 shared line service”不足以形成主线收益

## 3.3 具体实现任务

### Task 0.1：离线 generator 改为 line-aligned slice packing

**目标**

- 对 `peXX/atlas.values.bin` 中每个 core slice 做 16-float 对齐

**修改文件**

- [gen_gcss_valueonly_dstpe_atlas_v1.py](/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstpe_atlas_v1.py)

**做法**

1. 在写每个 core 的 values 之前，计算：
   - `pad = (-len(shared_values)) % 16`
2. 插入 `pad` 个 `0.0f` 作为对齐填充
3. 将 `values_base` 记录为对齐后起点
4. `atlas.meta.json` 中显式记录：
   - `values_pad_before`
   - `values_base`
   - `values_count`

**新增统计**

- `padding_floats_total`
- `padding_bytes_total`
- `aligned_slice_ratio`
- `max_slice_pad_floats`

### Task 0.2：新增 generator 单测

**目标**

- 防止之后再次退化回非对齐切片

**修改文件**

- [test_gen_gcss_valueonly_dstpe_atlas_v1.py](/home/xgy/remote/sst_dram_si/tools/gcss/test_gen_gcss_valueonly_dstpe_atlas_v1.py)

**检查点**

- 所有 `core_entries[*].values_base % 16 == 0`
- `atlas.values.bin` 大小与 `values_count + padding` 一致

### Task 0.3：保持 build/runtime 不变，只复用现有 bias 链

**目标**

- 不额外引入新 runtime 风险

**修改文件**

- 理想情况：不改 runtime
- 如需调试落盘，可只改：
  - [build.py](/home/xgy/remote/sst_dram_si/mesh_template/build.py)

### Task 0.4：LAP A/B 实验

**实验目录**

- `mainexp/experiments/2026-03-xx_atlas_pe_lap_ab_v1`

**case**

1. `baseline_step1_seed_only_frac003`
2. `atlas_storage_only_step1_seed_only_frac003`
3. `atlas_lap_step1_seed_only_frac003`

**必须观察的指标**

- `sim_time_actual_ns`
- `memctrl.req_total`
- `gas.payload_bytes_per_memctrl_req_avg`
- `gas.memctrl_payload_utilization`
- `gas.unique_line_count_total`
- `gas.line_utilization_unique`

## 3.4 LAP 阶段 go/no-go 条件

### Go

如果同时满足：

- `validation fail=0 warn=0`
- `payload_bytes_per_req` 明显回升
- `memctrl.req_total` 明显回落

则说明：

- misalignment 是主要退化源
- 可以进入 LSS 阶段，但仍不能把 LAP 本身当成最终方案

### No-Go

如果：

- 对齐后仍明显差于 baseline

则可下结论：

- `storage-only` 路线本质上不成立
- 直接进入 `ATLAS-LSS`，不再追加 storage-only 变种

---

## 4. Phase 1：ATLAS-LSS（离线格式）

## 4.1 目标定义

`ATLAS-LSS = ATLAS Line-Shared Synapse Service`

这是下一阶段真正的主任务，目标是把：

- `token-level multicore reuse`

变成：

- `line-level shared memory service`

核心思想是：

- 同一个 `pre_global` 在一个 PE 内多个 core 的权重需求，
  不再简单地以“多个 core slice”形式放入 shared values，
  而要组织成 **line descriptor 驱动的共享 line 数据面**。

## 4.2 离线数据格式

推荐新格式（实验性，强隔离）：

- `peXX/atlaslss.values.bin`
- `peXX/atlaslss.pre.idx.bin`
- `peXX/atlaslss.line.desc.bin`
- `peXX/atlaslss.meta.json`
- `manifest.json`

## 4.3 数据结构定义

### A. pre index

回答：

- `pre_global -> line_desc_base`
- `pre_global -> line_desc_count`

即，一个 pre 对应多少条共享 line descriptor。

### B. line descriptor

每条 descriptor 表示一条 64B line 的服务对象：

- `line_base_float`
- `consumer_count`
- `consumer entries[]`

每个 consumer entry 包含：

- `core_id`
- `pre_rank_base`
- `len`
- `line_word_offset`

这样 DRAM line 返回后，runtime 就能知道：

- 这一条 line 里哪些浮点对应哪个 core 的哪一段 `pre_rank`

### C. values bin

不再按“core slice 顺序串接”，而按：

- **line-first, shared-service-first**

来组织 values。

## 4.4 打包策略

推荐初版先做最简单可控版本：

### 方案 A：Pre-local greedy line packing（推荐）

对每个 `pre_global`：

1. 收集该 PE 内所有 core 的序列
2. 按 `core_id` 排序
3. 按 64B line 依次填充
4. 一条 line 可容纳多个 core 的 consumer slice

优点：

- 实现最直接
- 容易离线统计理论上界
- 最适合第一版闭环

### 方案 B：Consumer-count-aware packing

按：

- 多 consumer 优先
- 短片段优先拼装

做 packing。

优点：

- 可能更省 line

缺点：

- 离线复杂度更高
- 第一版不利于调试

结论：

- **第一版只做方案 A**
- 方案 B 作为第二阶段优化

## 4.5 LSS 离线阶段必须新增的统计

在 `atlaslss.meta.json` 和 manifest 中必须包含：

- `packed_line_count_total`
- `packed_line_payload_floats_total`
- `dead_floats_total`
- `avg_consumers_per_packed_line`
- `multi_consumer_line_ratio`
- `single_consumer_line_ratio`
- `line_payload_utilization_theoretical`
- `theoretical_req_reduction_vs_storage_only`
- `theoretical_req_reduction_vs_baseline`

这些统计的作用是：

- 在 runtime 接入之前，先证明 offline packing 至少在理论上有收益空间

## 4.6 LSS offline 阶段具体任务

### Task 1.1：新 generator 脚本

**建议文件**

- 新增：
  - `/home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstpe_atlas_lss_v1.py`

**原因**

- 避免在现有 storage-only atlas generator 上继续堆逻辑
- 强隔离，防止误用

### Task 1.2：新增 offline 单测

**建议文件**

- 新增：
  - `/home/xgy/remote/sst_dram_si/tools/gcss/test_gen_gcss_valueonly_dstpe_atlas_lss_v1.py`

**检查点**

- descriptor 与 values 一致
- line 范围不越界
- 每个 consumer 的 `(core_id, pre_rank_base, len)` 可逆重构
- 所有 line 起点 64B 对齐

### Task 1.3：offline 理论实验

**实验目录**

- `mainexp/experiments/2026-03-xx_atlas_lss_offline_estimation_v1`

**产出**

- `snapshot/offline_compare.tsv`

比较：

1. baseline per-core values
2. atlas storage-only
3. atlas LAP
4. atlas LSS packed

---

## 5. Phase 2：ATLAS-LSS（runtime 共享 line 服务）

## 5.1 目标定义

这一阶段才真正让：

- `atlas_pe.lines_planned_total`

变成真实的 memory service，而不是统计 sidecar。

runtime 要实现的是：

> 一个 pre 在 PE 内多个 core 的 line 需求，由一个 PE-shared line service 队列统一发射，然后本地 fanout 给多个 core。

## 5.2 推荐运行时结构

推荐新建一个实验性 PE-shared 单元：

- `AtlasPeLineService`

避免直接在 `WeightMemorySubsystem` 里继续堆 atlas storage-only 分支。

### 组成

1. `Token Directory`
   - 按 `pre_global` 收集当前窗口 token
2. `Line Plan Queue`
   - 保存本窗口待服务的 shared line descriptor
3. `Line MSHR / Inflight Table`
   - 去重当前待发射 / 在途 line
4. `Response Fanout`
   - line 返回后按 descriptor 分发给各 core

## 5.3 推荐接入点

### A. Gather 侧

继续复用现有：

- `atlas_pe_enable`
- `atlas_pe` sidecar token 收集链

但不再只做统计，而是产出：

- `pre_global active set`

### B. Apply 前

在 `BeginApply` 时：

1. 由 `AtlasPeLineService` 根据 active pre 集生成 line plan
2. 将 plan 下发到 PE-shared issue queue

### C. Memory issue

由 PE-shared 单元直接发 line 请求，而不是每 core 独立 issue。

### D. Core retire

返回后仍然交给每个 core 当前已有的严格 retire 逻辑：

- 不修改 `acc_update(post_local, delta)` 语义
- 不改最终提交顺序合同

## 5.4 推荐代码承载

### 新增文件（推荐）

- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/atlas/AtlasPeLineService.h`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/atlas/AtlasPeLineService.cc`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/atlas/AtlasLssIndex.h`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/atlas/AtlasLssIndex.cc`

### 只做接线/最小改动的文件

- [MultiCorePE.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc)
- [SnnPESubComponent.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc)
- [SnnWorkload.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc)
- [WeightMemorySubsystem.cc](/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc)

原则是：

- **新能力尽量放新文件**
- 旧文件只做 gate / ownership / callback 接线

## 5.5 runtime 必须新增的统计

### PE-shared service 统计

- `atlas_lss_active_pres_total`
- `atlas_lss_planned_lines_total`
- `atlas_lss_issued_lines_total`
- `atlas_lss_reused_consumers_total`
- `atlas_lss_fanout_responses_total`
- `atlas_lss_inflight_peak`

### line 服务收益统计

- `atlas_lss_line_dedup_total`
- `atlas_lss_line_fanout_avg`
- `atlas_lss_payload_bytes_total`
- `atlas_lss_dead_bytes_total`
- `atlas_lss_payload_utilization`

### 与主线 A/B 关键对照

- `memctrl.req_total`
- `payload_bytes_per_memctrl_req_avg`
- `memctrl_payload_utilization`
- `traffic_amplification`
- `apply_ns_avg`

## 5.6 runtime 阶段实验矩阵

**实验目录**

- `mainexp/experiments/2026-03-xx_atlas_lss_runtime_ab_v1`

**建议 case**

1. `baseline_step1_seed_only_frac003`
2. `atlas_storage_only_step1_seed_only_frac003`
3. `atlas_lap_step1_seed_only_frac003`
4. `atlas_lss_offline_only_step1_seed_only_frac003`
   - 新格式，旧 runtime
5. `atlas_lss_full_step1_seed_only_frac003`
   - 新格式 + 新 runtime

---

## 6. 每个阶段的明确验收标准

## 6.1 ATLAS-LAP 验收

必须满足：

- `validation fail=0 warn=0`
- `aligned_slice_ratio = 100%`

观察项：

- `payload_bytes_per_req`
- `memctrl.req_total`
- `unique_line_count_total`

结论标准：

- 若改善明显：说明 misalignment 是主要止损点
- 若改善不明显：说明 storage-only 本质无望

## 6.2 ATLAS-LSS offline 验收

必须满足：

- 所有 descriptor 可逆重构
- line packing 完全 64B 对齐

理论收益门槛：

- `avg_consumers_per_packed_line > 1.5`
- `line_payload_utilization_theoretical > atlas_storage_only`
- `theoretical_req_reduction_vs_storage_only > 0`

如果达不到这些门槛，则不进入 runtime 阶段。

## 6.3 ATLAS-LSS runtime 验收

必须满足：

- `validation fail=0 warn=0`
- `memctrl.req_total <= baseline`
- `payload_utilization >= baseline`

更理想目标：

- `sim_time_actual_ns <= baseline`

如果 runtime LSS 依然明显差于 baseline，则应直接判定：

- `ATLAS-LSS` 不适合作为近期主线论文点

---

## 7. 推荐执行顺序（最小风险版本）

## Stage A：ATLAS-LAP

1. 改 generator 对齐逻辑
2. 补 generator 单测
3. 生成新 atlas 数据
4. 跑 `baseline / storage_only / lap` 三组实验
5. 判断 storage-only 是否仍值得保留

## Stage B：ATLAS-LSS offline

1. 新建 `atlas_lss_v1` generator
2. 做 descriptor + values + meta 格式
3. 做离线单测
4. 跑 offline 理论对比
5. 只有理论收益足够，才继续 runtime

## Stage C：ATLAS-LSS runtime

1. 新建 `AtlasPeLineService`
2. 做最小接线
3. 补 runtime 统计
4. 跑完整 A/B
5. 根据结果决定是否继续深入

---

## 8. 明确不做的事

下一阶段明确不做：

1. 不继续追加 `ATLAS storage-only` 的参数扫点
2. 不把更多 global 偏移信息塞回 idx 文件
3. 不在 `WeightMemorySubsystem` 里堆大量 atlas 特判逻辑
4. 不在没有 offline 理论收益证据前直接写大段 runtime 代码

---

## 9. 最终推荐

如果只选一个“下一步主任务”，推荐是：

- **主任务：ATLAS-LSS**
- **前置短任务：ATLAS-LAP**

其逻辑关系是：

- `ATLAS-LAP` 用来回答：
  - “当前回退是不是主要由 non-aligned shared values 引起？”
- `ATLAS-LSS` 用来回答：
  - “能否把 token collapse 真正转化为 line-level shared memory service？”

这两者合起来，才是当前 ATLAS 路线最稳、最清晰、也最有论文价值的下一步。
