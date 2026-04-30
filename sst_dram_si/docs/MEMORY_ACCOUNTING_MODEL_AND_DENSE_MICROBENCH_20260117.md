# Memory 口径统一与 Dense Microbench（cacheline 语义）问题复盘 + 设计方案（2026-01-17）

本文用于和团队讨论：我们在 Dense microbench / GAS vs naive 对比中遇到的“内存口径混淆（memory_bytes 与 memHierarchy GetS 不一致）”问题、根因定位、已落地的修正点，以及一套更贴近主流体系结构建模的 **分层统计口径模型**（demand / request / traffic / time），并给出后续扩展的 DoD 与建议实现路径。

> 约束与目标：
> - 不改动 `sst_dram_si/test_mesh_4x4.py` 的默认行为（避免长期开发模板被污染）。
> - Dense microbench 走独立入口与输出目录，方便做最小可复现实验。
> - 统计口径需要能解释：有无 L1、GAS/naive、BCSR/dense、init vs runtime 等差异。

---

## 1. 背景：我们要解决的“口径问题”是什么

在 memHierarchy（cacheline/事务模型）下，软件层发起的 Read(addr,len) 并不等于“真实 DRAM 流量”：

- 上层可能 **合并/拆分** 请求（len 变化、burst 变化）。
- L1 cache 可能命中导致 **memctrl 侧流量降低**。
- 写入路径可能触发 write-allocate（读-改-写）导致 **memctrl GetS 变大**。
- init 阶段的 untimed 写入（WeightLoader）不计入模拟时间，但会产生大量流量，若与 runtime 混算会直接破坏对比。

因此，必须区分至少两层口径：

- **L1：逻辑请求量（logical request）**：软件/子系统对内存接口发起了多少次、多少字节。
- **L2：cacheline 事务量（traffic / transaction）**：memHierarchy 在某个硬件边界（L1/memctrl）真实搬运了多少 cacheline 事务。

### 1.1 同时要澄清的建模问题：Dense 权重读的最小粒度（row vs cacheline vs scalar）

除 L1/L2 口径分层外，我们还遇到一个更根本的体系结构建模问题：**Dense 权重读的最小粒度到底是什么？**

这是“功能上都能正确，但硬件语义完全不同”的取舍：

1) **row 粒度（row-streaming / DMA 行搬运语义）**

- 软件层一次 Read 就读完整个 post row（dense 下约等于 `cols * 4B`，常见是 2KB/4KB）。
- 优点：实现最简单；窗口内若多次访问同一 post row，复用非常自然；GAS 的收益会被放大到“行搬运模型”的上限。
- 风险：如果目标是表达“通用 DRAM + cacheline + cache/memHierarchy”的结论，row 粒度会系统性 over-fetch，把大量无用数据当成“必须发生的 DRAM 流量”。

2) **cacheline 粒度（更贴近 memHierarchy / 通用 cacheline 事务语义，推荐默认）**

- 软件层把一次访问压到 cacheline（例如 64B）或按需要覆盖的 cacheline 集合读取；底层以 cacheline GetS/GetX 等事务计量。
- 优点：更贴近主流体系结构建模习惯；结论更稳健，不会把 over-fetch 当作 GAS 的“必然收益”。
- 代价：需要明确 `(post, pre)` 到 cacheline 的映射，并保证 GAS/naive 都遵守同一粒度语义。

3) **scalar(4B) 粒度（逻辑最小，但物理上仍会 cacheline 化）**

- 语义最干净，但请求数会暴涨，事件/调度开销可能淹没内存模型；最终 memHierarchy 仍以 cacheline 事务计量。

结论（用于统一团队口径）：

- 若要做“更普遍、对一般 cache/coherence/DRAM 系统成立”的结论，**默认应选 cacheline 粒度**。
- row 粒度应保留为一个“专用 row-streaming/DMA 模式”，在论文/报告里显式声明硬件假设，不应默认冒充通用 DRAM。

我们之前遇到的异常现象是：Dense microbench 的 GAS 模式下，
上层 `memory_bytes` 很小，但 `MemController requests_received_GetS` 却非常大（固定出现 4096 的模式），导致结论无法可信。

---

## 2. 可复现实验：Dense microbench 套件

### 2.1 入口与配置

- 入口（共享）：`sst_dram_si/microbench_dense/entry.py`
- 1PE 版本：
  - model：`sst_dram_si/microbench_dense_1pe/test_dense_microbench.py`
  - config：`sst_dram_si/microbench_dense_1pe/local_run_config.json`
- 4x4 版本：
  - model：`sst_dram_si/microbench_dense_4x4/test_dense_microbench.py`
  - config：`sst_dram_si/microbench_dense_4x4/local_run_config.json`

关键环境变量（脚本会读取）：

- `MESH_EXEC_MODE=gas|naive_raw`
- `MESH_MAX_STEPS`（默认 1）
- `MESH_SIM_TIME`（可覆盖 json）
- `SST_N`（并行线程数）

### 2.2 一键运行脚本

- 4x4：`sst_dram_si/tools/run_dense_microbench_4x4_exec_mode_compare_with_time.sh`（见 `:1`-`:97`）
- 1PE：`sst_dram_si/tools/run_dense_microbench_1pe_exec_mode_compare_with_time.sh`

脚本会写入：

- `mesh_run.log`
- `/usr/bin/time -v` 输出 `time.txt`
- `meta.json`
- `mesh_stats.csv`
- `essential_summary_mesh.json`（由 `compute_essential_summary_mesh.py` 生成）
- `validation.log`（validator）

输出目录：

`sst_dram_si/outputs_large/paper2/dense_microbench_*_exec_mode_compare/<mode>/<timestamp>/`

---

## 3. 问题现象（历史）与根因定位

### 3.1 现象（问题时）

Dense microbench（4x4，GAS）出现：

- 上层 `memory_bytes` 接近 cacheline 粒度（例如几十 KB）
- 但 memHierarchy `MemController requests_received_GetS` 异常巨大（例如 53248），且很多 PE 呈现固定 4096 的倍数

这意味着：我们希望“按 cacheline 去重”的口径被破坏，GAS 在底层仍可能构造了更大的 burst/段读，导致 memHierarchy 看到大量 cacheline 事务（或包含“补洞读/扩段读”的流量）。

#### 3.1.1 证据链（用统计反推“实际下发读粒度”）

该类异常通常不是“统计脚本算错”，而是 **统计层级/粒度语义未对齐**：

- `memory_bytes` 统计的是 SnnDL 在“发起侧”的逻辑请求字节（L1 logical request）。
- `memHierarchy MemController requests_received_GetS` 统计的是下游最终拆成的 cacheline 事务数（L2 traffic）。

当 GAS 的 GatherBufferIF 处于“大粒度/行粒度”发起读时，两者天然不一致。

一个典型问题态可用以下等式闭环验证（示意）：

- `memctrl.req_GetS * line_size_bytes == memctrl.bytes_est_total`
- 若存在 `gas_unique_bytes_total`（GAS 唯一合并读覆盖的 granule 字节数），则通常有：
  - `gas_unique_bytes_total ≈ memctrl.bytes_est_total`（无 L1 的情况下，二者应同量级）
- 若 granule 固定为 8KB，则：
  - `memctrl.bytes_est_total / 8192B == granule_count`
  - `memctrl.req_GetS == granule_count * (8192B / 64B)`

这类闭环关系可以直接证明：问题态不是 memHierarchy “凭空造流量”，而是 GAS 发起侧确实在按大 granule（例如 8KB）读。

### 3.2 根因（定位结论）

根因不是 `merge_read_row`（已关闭），而是 **GAS 的 GatherBufferIF** 在 dense 场景下仍可能进行：

- gap merge（补洞合并）
- k-adapt（自适应扩大 burst）
- burst_bytes_max 过大（允许形成较大段读）

最终导致：虽然上层统计的 “logical request bytes” 看起来是 cacheline 粒度，但 memHierarchy 仍会把大段读拆成多个 GetS，从而在 memctrl 侧变成“很多 cacheline 事务”，污染结论。

对应代码装配位置：

- `sst_dram_si/mesh_template/build.py:736` 创建 `SnnDL.GatherBufferIF`
- `sst_dram_si/mesh_template/build.py:742` 起引入 dense_strict_cacheline 分支

---

## 4. 已落地的修正（确保 dense=cacheline 语义闭环）

### 4.1 Dense + GAS：强制 “strict cacheline” 的 GatherBufferIF 参数

代码位置：`sst_dram_si/mesh_template/build.py:742`-`789`

当 `force_dense=True`（dense microbench）时：

- `merge_policy="cacheline"`（禁止 row/更大粒度）
- `gap_merge_enable=0`、`gap_merge_k_bytes=0`（禁止补洞合并）
- `burst_bytes_max=line_size_bytes`（限制 burst 为单 cacheline）
- `k_adapt_enable=0`（禁用自适应扩大 burst）

目标：让 GAS 的实际下发读与 memHierarchy 的 cacheline 模型一致，避免 over-fetch 重新出现。

### 4.1.1 设计意图：为什么 dense 默认必须收敛到 cacheline 语义

在 memHierarchy 语义下，系统层真实流量由 cacheline/事务定义；若上层强制 row-sized Read，会把大量 over-fetch 计入“真实 DRAM 流量”，从而系统性放大 GAS 收益并破坏公平对比。

因此，本次 dense microbench 的设计意图是：

- dense 的默认读粒度 = **cacheline**（更贴近通用 DRAM/cacheline 建模）
- GAS 的合并/去重对象也应是 **cacheline**（而不是整行 row）
- 对比实验的主口径以 memHierarchy 的 MemController 事务统计（GetS 等）为准；`memory_bytes` 仅作为“逻辑请求形态”的解释辅助

### 4.1.2 仍需补强的“可重复性/可解释性”工作：把 effective 参数写进输出

一个实际风险是：`local_run_config.json` 里可能写 `gas_merge_policy="auto"`，
但 dense 场景会在 Python 装配层覆写成 `effective_merge_policy="cacheline"`（或在其它模式下变为 row）。
如果不把 **effective 参数**（最终生效的 merge_policy/gap_merge/burst_bytes_max/k_adapt 等）
写入 `meta.json` 或 `essential_summary_mesh.json`，后续读结果的人很容易被配置文件误导。

建议（后续执行项）：

- 运行目录中落盘 `effective_config.json`（由 `sst_dram_si/mesh_template/build.py` 写出），至少包含：
  - `dense_read_granularity`（cacheline|row）
  - `GatherBufferIF.effective_merge_policy`
  - `GatherBufferIF.gap_merge_enable / gap_merge_k_bytes`
  - `GatherBufferIF.burst_bytes_max`
  - `GatherBufferIF.k_adapt_enable`
- `sst_dram_si/tools/compute_essential_summary_mesh.py` 读取该文件并写入 `essential_summary_mesh.json` 的 `model/effective` 字段。

### 4.2 关闭默认 verbose（避免性能被 log 污染）

1) Core 默认 verbose=0（除非显式打开）：

- `sst_dram_si/mesh_template/build.py:724`-`726`
  - `core_params["verbose"] = int(debug.get("core_verbose", 0) or 0)`

2) WeightLoader 默认 verbose=0（除非显式打开）：

- `sst_dram_si/mesh_template/build.py:151`-`156`
  - `weight_loader_params["verbose"] = int(loader_verbose) if pe_id == 0 else 0`

说明：WeightLoader 的 stdout 输出在长时间仿真会污染 `mesh_run.log` 并拖慢 wallclock（尤其在大量 debug 时）。

---

## 5. 统计实现：我们现在的“口径提取”在哪里

### 5.1 L1（逻辑请求）提取

`sst_dram_si/tools/compute_essential_summary_mesh.py:348`-`351`

- `memory_requests = sum_stat(stats, "memory_requests")`
- `memory_bytes = sum_stat(stats, "mem_req_size_bytes")`

定义（建议固定写入文档/DoD）：这是 **上层组件（MultiCorePE/GatherBufferIF/等）对内存接口发起的逻辑请求统计**。

### 5.2 L2（memHierarchy 事务）提取

`sst_dram_si/tools/compute_essential_summary_mesh.py:352`-`419`

按组件名聚合：

- MemController：`pe_*_memory_controller`
  - `requests_received_GetS/GetX/GetSX/Write/PutM`
  - 并估算：`bytes_est_total = req_total * line_size_bytes`
- L1 cache（如果启用）：`pe_*_l1`
  - 同上，得到 L1 边界事务量

### 5.3 Init（WeightLoader）分账

同文件 `:405`-`419` 聚合：

- `pe_*_weight_loader` 的
  - `weight_bytes_written_total`
  - `weight_write_chunks_total`
  - `lines_est_total`（估算）

注意：WeightLoader 在 init 阶段大量使用 untimed 写入，这不计入模拟时间，但会显著影响 “全流程总流量”；对比实验里必须 **单列 init**，避免与 runtime 混算。

---

## 6. 实验结果（修正后：口径闭环成立）

### 6.1 4x4 dense microbench（同 seed，同 step 注入工作量）

运行目录：

- naive_raw：`sst_dram_si/outputs_large/paper2/dense_microbench_4x4_exec_mode_compare/naive_raw/20260117-184157/`
- gas：`sst_dram_si/outputs_large/paper2/dense_microbench_4x4_exec_mode_compare/gas/20260117-184552/`

工作量（两者一致）：

- `pre_selected_total = 23`
- `spike_attempts_total = 5888`（=23*256）

L2（MemController 口径，cacheline=64B）：

- naive_raw：
  - `memctrl.req_GetS = 5888` → `bytes_est_total = 376,832B`
- gas：
  - `memctrl.req_GetS = 824` → `bytes_est_total = 52,736B`

结论：GAS 将 memctrl 侧读事务/流量降低约 **7.14x（~86%）**，且与上层 `memory_bytes` 同量级一致（口径闭环成立）。

模拟时间（sim_time_actual_ns）：

- naive_raw：1846 ns
- gas：919 ns

wallclock（/usr/bin/time -v）：

- naive_raw：Elapsed 0.28 s（见 `.../time.txt`）
- gas：Elapsed 0.25 s（见 `.../time.txt`）

说明：1-step 场景 wallclock 差异容易被 SST 启动/建图/统计写出/WeightLoader init 淹没；要看 wallclock 的稳定差异，需增大 steady-state 比重（更多 steps 或更大负载）。

### 6.2 GAS 阶段时间统计（解释为何 apply 主导）

gas 结果（从 stage events 聚合）：

- `gather_ns_avg ≈ 31ns`
- `apply_ns_avg ≈ 150ns`（主导）
- `scatter_ns_avg ≈ 1ns`

解释：apply 阶段包含批量下发读 + 等待 ReadResp 的主要成本；在 DRAM 延迟模型下合理。

---

## 7. “最正确、最主流”的内存口径体系（设计方案）

本节是核心讨论材料：我们建议把统计体系固定为 **4 层 + 1 分账**，并明确每层的用途与 DoD。

### 7.1 分层模型（建议写入项目规范）

**L0 Workload‑Demand（语义需求层）**

- 描述：算法需要多少权重参与计算（例如 synapse op 数量）。
- 典型指标：`synapse_ops_step_total`、`spike_attempts_total`、`unique_posts_touched`（若可得）。
- 用途：衡量“工作量/负载变化”，用于解释为什么流量会变。

**L1 Logical‑Request（逻辑请求层 / pre-cache）**

- 描述：软件层发起多少次 `Read(addr,len)` / `Write(addr,len)`，总字节是多少。
- 指标来源：`memory_requests`、`mem_req_size_bytes`（`compute_essential_summary_mesh.py:348`-`351`）
- 用途：衡量“子系统如何改变请求形态”（去重/合并/分批）。不代表真实 off-chip 流量。

**L2 Cacheline‑Traffic（事务流量层 / post-cache）**

- 描述：在某个硬件边界处，cacheline 事务数是多少（GetS/GetX/Write/...），是体系结构语义最强的“流量”口径。
- 指标来源：memHierarchy 的 `requests_received_*`（`compute_essential_summary_mesh.py:352`-`404`）
- 用途：作为论文/结论的主口径（近似 off-chip 带宽压力），尤其当 L1 cache 启用时必须优先看 memctrl。

**L3 Time（时间层：模拟时间/阶段时间/wallclock）**

- `sim_time_actual_ns`：从 stats 推断的实际模拟时间（对比吞吐/进度）
- GAS stage events：解释 gather/apply/scatter 的瓶颈来源
- wallclock：系统层真实耗时（需要在 steady-state 足够长时才稳定）

**Init 分账（非计时流量）**

- WeightLoader init：`weight_bytes_written_total`/`write_chunks_total`
- 必须单列，严禁与 runtime L2 混算，否则 microbench 结论会被 init 噪声吞没。

### 7.2 “主流建模”的关键原则（本项目应采纳）

1) **论文主结论必须基于 L2（memctrl traffic）**  
因为主流体系结构研究讨论的是“穿越硬件边界的事务/带宽”，而不是软件 call 了多少次。

2) **带 cache 的对比必须同时报告 L1 与 memctrl**  
否则会把“缓存命中”误当成“算法优化”的贡献。

3) **必须显式声明粒度语义（cacheline vs burst/row）**  
当配置或实现允许 burst>cacheline 时，memHierarchy 的 GetS 会与上层 L1 不一致，这是预期现象；必须在模型里写清楚。

4) **BCSR 与 GAS 的优化贡献要分离**  
BCSR 的 row/colidx/blockdata 访问模式会改变 L0/L1 的 demand；GAS 是调度/去重/合并。做对比时要保证“被归因的优化点”唯一，否则会双重记功。

---

## 8. 下一步建议（可选，供讨论）

1) 对比实验 DoD（建议写入 README/validator）
- DoD‑M1：同 workload（L0）下，L2(memctrl) 流量可复现（同 seed 允许小漂移，统计误差应 <1%）
- DoD‑M2：启用 L1 时必须输出 L1 与 memctrl 两级 traffic
- DoD‑M3：init 与 runtime 分账必出，且文档中明确“结论用哪个口径”

2) 若要更贴近体系结构论文写法，可补充：
- AMAT 分解（L1 hit/miss 推导、memctrl latency 分布）
- bytes/step、bytes/synapse_op（归一化）
- write-allocate 的识别（若引入真实写流量）

3) 读粒度语义的 DoD（避免“无意切回 row 粒度”）
- DoD‑G1：dense 场景下，`memhierarchy.memctrl.bytes_est_total` 与 `memory.memory_bytes` 必须处于同量级（cacheline 语义下通常接近，允许小偏差）。
- DoD‑G2：若启用 row-streaming 模式，必须在 `meta.json`/summary 里显式标注（例如 `dense_read_granularity=row`），并在分析/结论中单独分组，不与 cacheline 模式混算。
- DoD‑G3：对比实验报告必须在“实验设置”里写清楚：dense 的 read granularity（row vs cacheline），以及采用的主口径（memctrl traffic vs logical bytes）。

4) 针对“粒度不对齐回归”的自动验收（建议加到 validator）

- DoD‑V1：dense+GAS+cacheline 语义下，`avg_burst_bytes = gas_unique_bytes_total / gas_unique_reads_total` 必须接近 `line_size_bytes`（允许少量浮动），并且
  `memhierarchy.memctrl.bytes_est_total` 与 `memory.memory_bytes` 必须同量级。
- DoD‑V2：若检测到 `avg_burst_bytes >> line_size_bytes`（例如达到 8KB），则判定为“回归到 row/granule 粒度”，需要在输出中显式标注，并阻止其混入 cacheline 结论。

---

## 9. 附录：相关核心代码位置索引

- GAS memory 组件：`sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`
- WeightLoader：`sst_workspace/sst-elements/src/sst/elements/SnnDL/components/WeightLoader.cc`
- Mesh 装配（GAS 参数/verbose/WeightLoader stats）：`sst_dram_si/mesh_template/build.py`
  - Core verbose：`:724`
  - Dense strict cacheline：`:742`
  - WeightLoader verbose：`:155`
- summary 生成：`sst_dram_si/tools/compute_essential_summary_mesh.py`
  - logical request：`:348`
  - memHierarchy traffic：`:352`
  - WeightLoader 分账：`:405`
- 运行脚本：`sst_dram_si/tools/run_dense_microbench_4x4_exec_mode_compare_with_time.sh`
