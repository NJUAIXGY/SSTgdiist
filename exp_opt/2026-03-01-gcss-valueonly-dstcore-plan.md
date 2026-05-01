# GCSS-ValueOnly (dst_core) 落地方案（主体 + A）

备注：若主人后续决定统一命名为 **GSCC**（而非 GCSS），本方案的机制与实现不变，仅需做字符串/文件名的统一替换即可。

作者：浮浮酱（nekomata-engineer）  
日期：2026-03-01  
基线口径：`4x4 bcsr10k step1`（Ramulator2 DDR5，`apply_issue_policy=order`，semseal 严格验证）

---

## 0. 这份方案解决什么（论文视角）

### 0.1 现状痛点（来自我们代码与统计）

在当前 `GAS + BCSR(post=row, pre=col)` 的实现中，**内存瓶颈的根因不是 weight value 本身，而是“定位 weight 所需的索引/块开销 + cacheline 粒度放大”**：

- 运行时定位路径（`WeightMemorySubsystem::requestBCSR_()`）：`rowBounds()` → 读整段 `colidx`（`bcsr_kind=2`）→ 找到 block 后再读 `blockdata`（`bcsr_kind=3`）。
- 在 `bcsr10k`（`br=1, bc=16, idx_bytes=2`）且列坐标随机的情况下：每个有效边大概率“独占一个 block”，导致 `blockdata`/`blockids` 的有效利用率极低，`colidx` 流量在 steady-state 中占据大头。
- semseal baseline（摘要见 `essential_summary_mesh.json`）：
  - `memctrl.bytes_est_total ≈ 128.48MB`
  - `gas.unique_bytes_total ≈ 128.48MB`，平均每条 unique read 粒度约 `140B`
  - 我们对单核 BCSR meta 的估算显示：仅 `colidx` 全扫的量级可达 **~55.9%** 的 bytes（这会随着规模上升更难压）

### 0.2 目标（必须满足）

1. **只优化内存体系结构**：降低 DRAM `req_total/bytes_est_total`，提升 cacheline 有效载荷，改善 `avg_read_latency`/tail。
2. **不改变 GAS 语义**：同一组 spike/edge 产生的 ΔV 累加结果一致；semseal 严格验证必须通过。
3. **不引入过量 NoC 流量**：尤其不能把“权重读”变成跨 PE 的远程内存访问（否则会从 DRAM 瓶颈变成 NoC 瓶颈）。

---

## 1. 关键约束：我们的 DRAM 是“每 PE 本地地址域”

`sst_dram_si/mesh_template/build.py` 为每个 PE 构建独立的 `MemController + Bus`，并设置 `addr_range_start/end` 为该 PE 的权重区间。也就是说：

- **core 的 StandardMem 请求默认只会落到本 PE 的 MemCtrl/Ramulator2**；
- 若我们把权重按“源 pre”放在别的 PE 的地址域，就等价于引入“远程内存”（当前模型没有这条真实路径），会导致语义/性能都不可控。

因此：GCSS-ValueOnly 在本工程的落地必须是 **dst_core 驻留（destination-core resident）** 的值流布局，而不是全局 pre-centric 的单地址域大数组。

---

## 2. 设计总览：GCSS-ValueOnly(dst_core) = “值在 DRAM，元数据在 SRAM(Host)，索引读归零”

### 2.1 核心定义

- `pre_global`：源神经元全局 ID（SpikeEvent 已包含）
- `post_local`：目的 core 的本地神经元索引（现有路径已缓存/可推导）
- `widx`：**该 edge 在“本 dst_core 的 GCSS weight stream”中的索引**（单位：float 元素，而不是字节）
- `addr = base_addr + 4*widx`：本 core 的 DRAM 物理读地址（保持本地 MemCtrl）

### 2.2 DRAM 中存什么

对每个 `(pe, core)` 生成一个文件：

- `coreXX.gcss.bin`：`float32` 数组，长度 = 该 core 的有效 edges 数（典型为 `rows_per_core * fanin`）。
- 写入地址：仍使用该 core 的 `base_addr`（沿用现有 per-core region，保证请求落在本地 MemCtrl）。

> 这保证 **DRAM 只存 values**；不存 `rowptr/colidx/blockids`。

### 2.3 SRAM(Host) 中存什么（不进入 DRAM 统计）

对每个 `(pe, core)` 生成一个索引文件并在 init 时加载为 host 结构：

- `coreXX.gcss.idx.bin`：用于从 `(pre_global, post_local)` **纯计算/查表**得到 `widx`
- 目标：**运行时完全不发起任何 “元数据 DRAM read”**（colidx 归零）

索引结构推荐（可实现且足够快）：

1. `unordered_map<uint32_t pre_global, PreEntry>`：
   - `base_widx`：该 pre 在此 core 的 weight stream 起始
   - `posts[]`：该 pre 在此 core 连接到哪些 `post_local`（建议 `uint16_t`，因为每 core rows=500）
2. `lookup(pre, post_local)`：在 `posts[]` 中线性查找（长度约 10 量级），返回 `base_widx + pos`。

> 这一步是“论文贡献点”的关键：我们把 BCSR 的 `colidx` 从 DRAM 迁到（可被视为片上 SRAM 的）索引表，且索引表按 dst_core 切分、按 fanin 稀疏度规模化。

### 2.4 文件格式（必须严格一致，避免“idx/values 不一致”踩雷）

#### 2.4.1 `coreXX.gcss.bin`（DRAM values-only stream）

- 内容：连续 `float32`（little-endian），无 header。
- 语义：`widx` 以 **float 元素**为单位计数，地址为 `base_addr + 4*widx`。
- 约束：
  - 每个 `(pe,core)` 单独一个文件，文件大小必须 `<= per_core_weight_stride`（避免跨 core 覆写）。
  - 建议（非必须）：生成时把文件大小 padding 到 64B 对齐，便于 debug 观测（不影响语义）。

#### 2.4.2 `coreXX.gcss.idx.bin`（Host index）

目标：给定 `(pre_global, post_local)`，在 host 侧确定性查表得到 `widx`，运行时不触发任何 meta DRAM read。

建议二进制布局（v1，足够简单且易压缩扩展）：

```
struct GcssIdxHeaderV1 {
  char magic[8];          // "GCSSIDX1"
  uint32_t version;       // 1
  uint32_t rows_per_core; // e.g. 500
  uint32_t edges_total;   // = len(values) = max(widx)+1
  uint32_t pre_entries;   // number of distinct pre_global in this core
  uint32_t posts_total;   // total post_local entries across all pres
  uint32_t flags;         // 0 for now
  uint32_t reserved0;     // 0
};

// Arrays (all little-endian), tightly packed:
uint32_t pre_keys[pre_entries];        // sorted ASC
uint32_t base_widx[pre_entries];       // base index in values stream
uint16_t post_counts[pre_entries];     // count per pre (fanin within this core)
uint32_t post_offsets[pre_entries];    // offset into posts[] (uint16 units)
uint16_t posts[posts_total];           // concatenated post_local lists; each list sorted ASC
```

查找算法（确定性）：

1. `i = lower_bound(pre_keys, pre_global)`，未命中则 miss（视为无边）。
2. `posts_i = posts[post_offsets[i] : post_offsets[i] + post_counts[i]]`，在线性扫描（或二分）中找到 `post_local` 的位置 `j`。
3. 返回 `widx = base_widx[i] + j`。

> 说明：在 `bcsr10k` 的典型 fanin 下，`post_counts[i]` 很小（~O(10)），线性扫的常数更低；未来规模更大时，再把局部 posts 列表升级为二分或小型 perfect hash。

---

## 3. A：dst_core 粒度的“源 pre 聚类”（Destination-Core Pre-Clustered Stream）

### 3.1 为什么 A 是必须的（否则会被 cacheline 放大拖垮）

GCSS-ValueOnly 的单条边只需要 4B，但 memHierarchy/DRAM 以 64B cacheline 运输：

- 如果同一窗口内，同一 `pre_global` 在同一 `dst_core` 触发的多个边分散在不同 cacheline，**4B 会被放大成多条 64B 读**，收益会被吃掉。

### 3.2 我们的 workload 里 A 有效的原因（local_ratio）

`bcsr10k` meta 显示 `local_ratio ≈ 0.85`：同一 pre 的大部分扇出落在本地 PE，从而在同一 `dst_core` 内，一个 pre 往往有 **多条边**（数量级可到 10+），足以形成 cacheline 合并机会。

### 3.3 A 的具体落盘规则（决定 `widx` 的排列）

对每个 `(pe, core)`：

1. 枚举该 core 的所有有效边 `(pre_global, post_local, weight)`。
2. **按 `(pre_global ASC, post_local ASC)` 排序**（确定性）。
3. 排序后的顺序即 `widx` 增长顺序；`coreXX.gcss.bin[widx]=weight`。
4. 同时为每个 `pre_global` 记录其 `base_widx` 与 `posts[]`（用于 `.idx.bin`）。

性质：

- 对固定 `pre_global`，其所有目的在本 core 的边在 stream 中连续（cacheline 有效载荷高）。
- 对 GAS Apply 的 deterministic retire：我们仍按 `(post_local, pre_global)` 的 key 顺序退役；**A 不改变退役顺序**，只改变“内存地址分布”。

### 3.4 为什么 A 选 “pre 聚类” 而不是 “post 聚类”

GAS 窗口里被激活的 edges 本质上由“spike 的 pre 集合”决定：一个 `pre_global` 在窗口内触发时，会激活它在该 `(pe,core)` 内的全部扇出边；而单个 `post_local` 在稀疏发放下通常只会命中少量 pres。

因此，把同一 `pre_global` 的 `(post_local, weight)` 在 values stream 中打包连续，能把“每条边 4B”的访问压到更少 cacheline granule 上，且由于本项目 `sram_bytes=256KiB/core`，窗口内 granule 基本不会被提前驱逐，哪怕 Apply 发起顺序是 `(post,pre)` 排序，cacheline 复用仍能成立。

---

## 4. 运行时数据流（不改变 GAS 语义）

### 4.1 Spike 到达（Gather）

现状：`SnnPESubComponent_spike.cc` 收到 `SpikeEvent(pre_global, post_global, ...)` 后调用：

- `recordEdge_(post_local, pre_global)` → `WeightMemorySubsystem::recordEdge(post_local, pre_global)`

GCSS 方案：在 `recordEdge_` 内新增一步（纯本地计算）：

1. `widx = weight_mem_subsystem_->lookupGcssWidx(pre_global, post_local)`（命中则返回，否则视为无边/0）
2. `recordEdge(post_local, pre_global, widx)`

### 4.2 BeginApply（Issue）

现状：`WeightMemorySubsystem::issueFromEdgesOnce_()` 迭代 `GasEdgeCollector.prev`（key 为 `(post,pre)` 排序）并对每条边发起 `requestBCSR_()`。

GCSS 方案：对每条边改为 `requestGCSS_(widx)`：

- `addr = base_addr + 4*widx`
- `issueRead_(addr, 4B)`（仍会被 GatherBufferIF/下游按 cacheline 分片与合并）
- 回调返回 `float` 后走既有 `edge_retire_` 逻辑：**退役顺序不变**，ΔV 语义不变。

### 4.3 Scatter

完全不变：仍由既有累加器/Scatter 统一应用。

---

## 5. NoC 流量评估（回答“会不会引入过量 NoC”）

结论：**不会**。原因：

1. 权重读仍发生在目的 core，地址落在目的 PE 的 `addr_range_start/end` 内，走本地 MemCtrl/Ramulator2，不会转化为远程访存。
2. GCSS 主体 + A **不要求在 SpikeEvent/Noc payload 中携带 tag**（widx 在目的端由 `.idx` 查得）。因此 spike payload 不变，NoC bytes 不增加。

> 如果未来希望进一步减少 NoC：可以在 GCSS 模式下改 WireSpike payload，移除无用的 `double weight` 字段（当前权重并不在网上传递），这是可选工作，不属于本次“主体+A”必需。

---

## 6. 语义与确定性（回答“是否能不改变语义”）

我们确保以下点不变：

1. **同一条边的 weight 值不变**：`.gcss.bin` 与原 BCSR 的有效边一一对应，权重相同（初期可用抽样/全量校验）。
2. **ΔV 累加顺序不变**：
   - `GasEdgeCollector` 的 key 仍为 `(post_local<<32 | pre_global)`，排序规则不变；
   - `WeightMemorySubsystem` 已有 `edge_retire_` 机制抵抗回调乱序；
   - 因此浮点加法的确定性路径与 baseline 对齐。
3. **路由发送顺序不变**：路由仍由现有 weight-driven route 构建；GCSS 不重排 fanout 的发包顺序，因此不会因为 NoC 竞争改变“哪些 spike 落入 gather window”。

---

## 7. 落地任务清单（指导实现，按闭环最短路径排序）

> 注：这里给到“落地到能跑实验”的最短闭环；不包含额外扩展（压缩、量化、写回等）。

### Task 1：新增 GCSS 生成器（离线）

目标：从现有 BCSR 文件生成每核 `coreXX.gcss.bin` 与 `coreXX.gcss.idx.bin`。

建议位置：
- 新增脚本：`sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore.py`

输入：
- `--bcsr-dir`（例如 `sst_dram_si/weights/bcsr_global_16pe_fanout256_10k`）
- `--mesh-w/h --cores-per-pe --rows-per-core --cols-global --routing-epsilon`

输出：
- `.../weights/gcss_valueonly_dstcore/.../pe{pe:02d}/core{core:02d}.gcss.bin`
- `.../pe{pe:02d}/core{core:02d}.gcss.idx.bin`
- sidecar meta JSON（记录 rows/cols/edges/排序规则/hash）

### Task 2：mesh_template 切换 WeightLoader 输入（仅影响 init）

修改：
- `sst_dram_si/mesh_template/build.py` 的 WeightLoader 配置：
  - 当 `synapse_weight_mode == "gcss_valueonly_dstcore"`：
    - `weight_format="raw"`
    - `per_core_files=1`
    - `file_template` 指向 `.gcss.bin`
    - `bcsr_enable=0`（不再写 BCSR 元数据）

保持：
- route 仍使用原 BCSR 文件构建（不动 routing_mode 机制）

注意（必须在方案落地前显式修正的现状问题）：
- 当前 `SnnPESubComponentConfig` 里 `synapse_weight_mode` **是硬编码**为 `"bcsr_gas"`，并不会读取参数；
- `mesh_template/build.py` 里虽然给 core_params 传了 `"synapse_weight_mode"`，但在 C++ 侧目前等价于“未生效”。

因此：落地 GCSS 前必须先把 `synapse_weight_mode` 参数真正接通（见 Task 3/4）。

### Task 3：WeightMemorySubsystem 增加 GCSS 模式

修改：
- `sst_workspace/.../services/synapse/weights/WeightMemorySubsystem.{h,cc}`

要点：
- 扩展 `OrchestratorConfig.synapse_weight_mode` 支持 `gcss_valueonly_dstcore`。
- 增加：
  - `loadGcssIndexOnce()`：加载 `coreXX.gcss.idx.bin`（路径复用 `weights_template` 或新增 `gcss_index_template`）
  - `lookupGcssWidx(pre_global, post_local) -> (bool ok, uint32_t widx)`
  - `requestGCSS_(uint32_t widx, cb)`：发起 `Read(base_addr + 4*widx, 4)`（对齐/分片逻辑可复用 dense 路径）
- 在 `issueFromEdgesOnce_()` 中：
  - 对每条 edge：若 mode=GCSS，则取 `widx` 并走 `requestGCSS_()`；否则沿用旧 BCSR。

建议新增参数（避免复用 weights_template 导致 routing/BCSR 误读）：
- core param: `gcss_index_template=/.../pe{pe:02d}/core{core:02d}.gcss.idx.bin`
- core param: `gcss_mode=1` 或直接复用 `synapse_weight_mode` 字符串判定

### Task 4：GasEdgeCollector 承载 widx（不改变 key）

修改：
- `sst_workspace/.../services/synapse/gas/GasEdgeCollector.{h,cc}`

要点：
- key 仍为 `uint64(post,pre)`，排序不变；
- value 从 `uint32_t count` 扩展为 `struct { uint32_t count; uint32_t widx; }`；
- `nextPrev` 需要返回 `widx`（供 WMS issue 使用）。

### Task 5：SnnPESubComponent 在 recordEdge 时注入 widx

修改：
- `sst_workspace/.../control/SnnPESubComponent.cc`（`recordEdge_()`）

逻辑：
- 若 `synapse_weight_mode == gcss_valueonly_dstcore`：
  - 通过 `weight_mem_subsystem_` 查 `widx`
  - `weight_mem_subsystem_->recordEdge(post_local, pre_global, widx)`
- 否则沿用旧 `recordEdge(post_local, pre_global)`

### Task 6：验证与统计（必须）

新增/复用统计：
- 记录 `gcss.idx` 命中率、miss（miss 视为无边）
- 记录 GCSS read bytes（应接近 `unique_edges * 64B` 的 cacheline 放大下界）

正确性：
- 抽样比对：对随机抽样的若干 `(pre,post)`，用 BCSR file read 解析得到 weight，与 GCSS DRAM read 返回值比对。

建议加一个离线一致性检查（避免跑一次 SST 才发现 idx 错）：
- 在生成器脚本里提供 `--self-check`：
  - 对每个 core，随机抽样 N 条 edges（来自 BCSR 解析结果）
  - 用 idx 查得 `widx` 后，从 values 数组读出 weight
  - 与 BCSR 对应 weight 对比（abs/rel tol），不一致直接 fail-fast

---

## 8. 实验矩阵（memop/semseal 口径）

统一基线：`4x4 bcsr10k step1`

### 8.1 对照组

1. Baseline：`synapse_weight_mode=bcsr_gas`
2. GCSS 主体：`synapse_weight_mode=gcss_valueonly_dstcore`，但 **不启用 A**（生成器按原扫描顺序落盘）
3. GCSS 主体 + A：`synapse_weight_mode=gcss_valueonly_dstcore`，生成器按 `(pre,post)` 排序落盘（A）

### 8.2 观测指标（只看内存）

从 `essential_summary_mesh.json` 提取：
- `memhierarchy.memctrl.req_total`
- `memhierarchy.memctrl.bytes_est_total`
- `gas.unique_reads_total / unique_bytes_total / avg_granule_bytes`
- `ramulator2.row_hit_rate_total / row_conflict_rate_total / avg_read_latency_0_avg`
- `sim_time_actual_ns`（作为最终端到端）

严格验证：
- `validation.log: fail=0 warn=0` 必须成立（semseal）。

### 8.3 实验承载（隔离）

所有对比实验建议落：`memop/experiments/2026-03-01_gcss_valueonly_dstcore_bcsr10k_step1_ab_v1/`  
并用：`memop/tools/snapshot_experiment.py` 固化产物（meta/summary/log/config）。

建议把 `cases.json` 的三组 case 预先规划好（便于一次跑完直接 snapshot）：
- `bcsr_gas_baseline`
- `gcss_valueonly_dstcore_noA`
- `gcss_valueonly_dstcore_A_precluster`

运行命令（示例）：
```bash
cd sst_dram_si
export MESH_BCSR_DIR="$PWD/weights/bcsr_global_16pe_fanout256_10k"
export MESH_GCSS_DIR="$PWD/weights/gcss_valueonly_dstcore_fanout256_10k"   # 计划新增
export MESH_SYNAPSE_WEIGHT_MODE="gcss_valueonly_dstcore"                    # 计划新增
export MESH_RUN_ROOT="$PWD/outputs_large/paper2/<your_run_group>"
./tools/run_mesh_with_time.sh
```

> 注：`MESH_SYNAPSE_WEIGHT_MODE/MESH_GCSS_DIR` 目前尚未接入脚本与 C++ 侧，是本方案落地要新增的“胶水”。

---

## 9. 风险与对策

1. **索引表过大**（未来 10M-100M）：  
   - 对策：索引按 dst_core 切分，规模与该 core 的 incoming edges 成正比；可进一步压缩 `posts`（delta/RLE）与 pre 列表（varint）。
2. **idx 生成与 route 不一致导致 miss**：  
   - 对策：生成器与 runtime 共享同一排序与过滤规则（epsilon、blockids 语义）；加入抽样校验。
3. **cacheline 放大仍过大**：  
   - 对策：A 是必要条件；若仍不够，再做“cacheline-aware packing”（属于后续扩展，不在本次主体+A）。

---

## 10. 预期结果（可写进论文的 claims）

在不改变语义与 NoC bytes 的前提下：

- `colidx`/元数据 DRAM read → 近似归零；
- DRAM traffic 更接近 “value-only + cacheline 下界”，`bytes_est_total` 有望显著下降；
- A 使 cacheline 有效载荷提升，降低 `unique_reads_total`（或降低 burst 数），改善 tail latency。

---

## 11. 落地状态（2026-03-01 当日）

### 11.1 已完成（代码）

- GCSS 索引文件加载/查表实现（新文件隔离承载）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/GcssIndexTable.h`
- `WeightMemorySubsystem` 接入 `gcss_valueonly_dstcore`：
  - 支持 `lookup(pre,post)->widx` + `requestGCSS_(base+4*widx, 4B)`
  - `bcsr_kind=4` 响应路径已接通
- `SnnPESubComponent` 参数贯通：
  - `synapse_weight_mode`（`bcsr_gas` / `gcss_valueonly_dstcore`）
  - `gcss_index_template`
- mesh 模板接线完成：
  - 环境变量 `MESH_SYNAPSE_WEIGHT_MODE`、`MESH_GCSS_DIR` 已生效
  - gcss 模式下 WeightLoader 读 `coreXX.gcss.bin`（`weight_format=raw`，`bcsr_enable=0`）
  - route 仍从 BCSR 构建（语义主线不变）

### 11.2 已完成（数据）

- A 版（`pre_post`）目录：
  - `sst_dram_si/weights/gcss_valueonly_dstcore_fanout256_10k_prepost_v1`
- noA 版（`scan`）目录：
  - `sst_dram_si/weights/gcss_valueonly_dstcore_fanout256_10k_scan_v1`
- 两目录均为 `320` 个 `.gcss.bin` + `320` 个 `.gcss.idx.bin`（16PE×20core）。

### 11.3 已完成（验证闭环）

- 实验目录（隔离）：
  - `memop/experiments/2026-03-01_gcss_valueonly_dstcore_bcsr10k_step1_ab_v1/`
- 三组 run：
  - baseline：`.../baseline_bcsr_gas/20260301-195438`
  - noA：`.../gcss_noA_scan/20260301-202903`
  - A：`.../gcss_A_prepost/20260301-204312`
- semseal 验证：三组 `validation.log` 现均为 `fail=0 warn=0`。

### 11.4 与原计划的工程修正

- 计划中“`MESH_SYNAPSE_WEIGHT_MODE/MESH_GCSS_DIR` 尚未接入”已过时：现已接通。
- 为避免 gcss 模式误触 BCSR 专属验证，已做模式感知修正：
  - `mesh_template/build.py`：gcss 下禁用 BCSR-only loader/readback 与 merge-read byte-exact 入口。
  - `tools/validate_essential_summary_mesh.py`：gcss 下将 BCSR-only marker 校验置为 `SKIP`。
