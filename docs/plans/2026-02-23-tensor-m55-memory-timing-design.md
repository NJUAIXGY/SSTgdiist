# Tensor-SI M55（内存时序细化）深度设计稿

> 说明：本文是 design-only 方案，不包含实现改动。目标是在不破坏现有 M0~M54 兼容性的前提下，把当前 Tensor-SI 内存模型从“带宽/outstanding 代理”推进到“row/bank/queue/service 可解释”的 M55 阶段。

## 0. 设计背景与现状锚点

当前代码基线已经具备：

- 内存相关配置钩子（`mem_req_bytes`、`mem_max_outstanding`、`dma_hbm_channels`、`dma_hbm_channel_bandwidth_bytes_per_cycle`、`dma_hbm_channel_interleave_bytes` 等）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.h:58`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.h:130`
- 内存与 stall 统计已导出（读写延迟、样本数、outstanding stall、HBM channel budget stall、program_mem_stall 等）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.h:545`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.h:564`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.cc:5558`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.cc:5577`
- M49/M54 已形成稳定 gate 模式（多场景 spec + validator + manifest + 顶层 realism 接线）：
  - `tools/run_tensor_m49_gate.sh:1`
  - `tools/run_tensor_m54_gate.sh:1`
  - `tools/run_snndl_regression_gate.sh:159`
  - `tools/run_snndl_regression_gate.sh:185`
- `TECH_PROGRESS.md` 已明确下一阶段优先项含 M55：
  - `TECH_PROGRESS.md:7442`

核心短板是：`issueMemReadTagged_`/`issueMemWriteTagged_` 目前仍以请求发起和总延迟采样为主，缺少 row/bank/service 阶段可观测性与显式排队机理（`TensorWorkload.cc:1500`、`TensorWorkload.cc:1559`、`TensorWorkload.cc:1625`）。

## 1. 与真实 NPU/TPU 内存子系统的差距（M55 关注面）

结合现有实现与公开资料（HBM3 高带宽、TPU 的确定性数据通路目标、现代 DRAM 模拟器对 timing constraint 的建模），当前差距可归纳为：

1. 已覆盖：带宽预算、通道条带化、outstanding 上限、端到端延迟采样。
2. 缺失：row hit/miss/conflict 可见性、bank 级队列等待、服务调度策略（FIFO/FR-FCFS）影响、refresh 阻塞可见性。
3. 风险：readiness 的 memory 维度仍偏“配置存在性评分”，容易被“开开关”而非“真实行为”拉高：
   - `sst_workloads/tensor_si/tools/tensor_readiness.py:159`
   - `sst_workloads/tensor_si/tools/tensor_readiness.py:255`

## 2. M55 目标与非目标

### 2.1 目标（DoD）

- 在 `TensorWorkload` 内新增 **proxy_v2 内存时序层**（默认关闭）：
  - 对每个请求给出 row/bank 分类与队列等待；
  - 让 stall 与 latency 的增长能被“冲突/排队/刷新”解释；
  - 不改现有外部接口，不破坏 legacy/spec 兼容。
- 在统计与 summary 中新增 M55 原生信号，替代纯 proxy 推断。
- 建立 M55 gate：三场景趋势合同 + 单测 + 顶层 realism 接线。
- 与 M52 证据链联动：支持“校准标签 + 趋势一致性”验收。

### 2.2 非目标（M55 不做）

- 不在本阶段重写 memHierarchy / ramulator2 后端接口。
- 不引入完整 DRAM 命令级所有时序参数（如全量 JEDEC 约束组合）。
- 不做跨 rank 全局一致控制器，只做单 workload 可解释近似。

## 3. 总体方案：三阶段落地

### 3.1 M55-P0（gate 先行，无 C++ 改动）

- 复用 M49 模式先建立更强合同，验证“现有计数器在多场景下可分离”。
- 新增：
  - `tools/specs/tensor_m55_mem_timing_locality_v3.json`
  - `tools/specs/tensor_m55_mem_timing_conflict_v3.json`
  - `tools/specs/tensor_m55_mem_timing_parallel_v3.json`
  - `sst_workloads/tensor_si/tools/validate_tensor_m55_mem_timing_contract.py`
  - `tools/run_tensor_m55_gate.sh`
  - `tools/test_run_tensor_m55_gate.py`
  - `sst_workloads/tensor_si/tools/test_validate_tensor_m55_mem_timing_contract.py`

### 3.2 M55-P1（C++ proxy_v2：row/bank/queue/service）

在不改变外部组件接口的条件下，在 `TensorWorkload` 内增加“发起前时序裁决层”：

1. 请求路径
   - `issueMemReadTagged_`/`issueMemWriteTagged_` 先进入本地 `PendingMemReq` 队列；
   - 根据 address map 计算 channel/bank/row；
   - 通过 bank 状态机计算 earliest_service_cycle；
   - 到达可服务周期后再调用现有 `rt_.mem->read/write`。
2. 兼容性
   - `tensor_mem_timing_model=off` 时走旧路径（零行为变化）；
   - `tensor_mem_timing_model=proxy_v2` 时启用本地时序延迟注入。
3. 关键点
   - 保留现有 `inflight_` 与 `onMemResponse_`，端到端统计兼容；
   - 新增 delay/queue/row 分类统计，不替换旧计数，只增量扩展。

### 3.3 M55-P2（校准与 readiness 联动）

- 利用 M52 证据路径引入 `tensor_calibration_tag` 与 profile 对齐；
- 把 memory 评分从“是否启用”升级到“行为是否可信”（row-hit、queue-wait、stall attribution 是否一致）；
- 输出可回归的校准报告，纳入 gate。

## 4. M55-P1 详细设计

### 4.1 新增配置参数（默认保持兼容）

建议新增 workload 参数（默认值保证“不开启即无影响”）：

- `tensor_mem_timing_model`: `"off" | "proxy_v2"`（默认 `off`）
- `tensor_mem_bank_groups_per_channel`: `uint32`（默认 `1`）
- `tensor_mem_banks_per_group`: `uint32`（默认 `1`）
- `tensor_mem_row_bytes`: `uint64`（默认 `8192`）
- `tensor_mem_bank_queue_depth`: `uint32`（默认 `16`）
- `tensor_mem_sched_policy`: `"fifo" | "frfcfs"`（默认 `fifo`）
- `tensor_mem_t_rcd_cycles`: `uint32`（默认 `0`）
- `tensor_mem_t_cl_cycles`: `uint32`（默认 `0`）
- `tensor_mem_t_rp_cycles`: `uint32`（默认 `0`）
- `tensor_mem_t_burst_cycles`: `uint32`（默认 `0`）
- `tensor_mem_refresh_interval_cycles`: `uint32`（默认 `0`，关闭）
- `tensor_mem_refresh_block_cycles`: `uint32`（默认 `0`，关闭）

### 4.2 地址映射与 bank 状态机

新增内部结构（示意）：

- `struct MemBankState { open_row, busy_until_cycle, queue_occ, last_refresh_cycle }`
- `struct PendingMemReq { kind, tag, epoch, bytes, ch, bank, row, enqueue_cycle, ready_cycle }`

映射策略（KISS，先可解释后精细）：

- 仍基于现有 `memOffsetToPhysicalAddr_` / interleave 映射 channel：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.cc:690`
- 在 channel 内按 `(row_bytes, banks_per_channel)` 切分 row 与 bank。

服务分类逻辑：

1. `row_hit`: open_row 相同，服务延迟 `t_cl + t_burst`
2. `row_miss`: open_row 无效，服务延迟 `t_rcd + t_cl + t_burst`
3. `row_conflict`: open_row 不同，服务延迟 `t_rp + t_rcd + t_cl + t_burst`

### 4.3 队列与调度策略

- 每 bank 独立队列，超过 `tensor_mem_bank_queue_depth` 时：
  - 请求不入队；
  - 增加 queue_full/drop 或 stall 计数；
  - 回退到上层 stall 归因（不 silent fail）。
- 调度策略：
  - `fifo`: 先来先服务；
  - `frfcfs`: 先选 row-hit，再按到达顺序。

### 4.4 refresh 近似

- 每 `refresh_interval` 周期对 bank 注入 `refresh_block_cycles` 的 busy 窗口；
- 在窗口内的请求计入 refresh stall；
- 默认关闭，避免影响旧回归。

### 4.5 统计扩展（新增，不替换旧字段）

建议新增统计键：

- `tensor_mem_row_hit_total`
- `tensor_mem_row_miss_total`
- `tensor_mem_row_conflict_total`
- `tensor_mem_bank_queue_full_total`
- `tensor_mem_bank_queue_wait_cycles_total`
- `tensor_mem_sched_fifo_pick_total`
- `tensor_mem_sched_frfcfs_pick_total`
- `tensor_mem_refresh_block_cycles_total`
- `tensor_mem_proxy_delay_cycles_total`
- `tensor_mem_proxy_delay_cycles_max`
- `tensor_mem_bank_active_cycles_total`

并在 summary 端新增派生指标：

- `tensor_mem_row_hit_ratio`
- `tensor_mem_row_conflict_ratio`
- `tensor_mem_bank_queue_wait_avg_cycles`
- `tensor_mem_proxy_delay_avg_cycles`

## 5. M55 gate 与验证合同设计

### 5.1 三场景定义

1. `locality`：顺序访问、较高 row locality，预期 row-hit 更高、平均延迟更低。
2. `conflict`：同一 bank 热点/低队列深度，预期 row-conflict 与 queue-wait 上升。
3. `parallel`：多 channel + 多 bank 并行，预期在等字节下平均延迟优于 conflict。

### 5.2 validator 约束（建议）

- P0 基础约束
  - 三场景 `tensor_mem_bytes_read_total` > 0 且在同 workload 下保持同量级；
  - `tensor_program_issue_width` 一致（控制变量）。
- P1 行为约束
  - `row_hit_ratio(locality) > row_hit_ratio(conflict)`
  - `row_conflict_total(conflict) > row_conflict_total(locality)`
  - `bank_queue_wait_cycles(conflict) > bank_queue_wait_cycles(locality)`
  - `avg_read_latency(parallel) < avg_read_latency(conflict)`（同字节量约束下）
- P2 校准约束
  - `calibration_confidence` 不低于 `medium`；
  - 与 M52 基线 profile 的趋势方向一致（允许误差带，不做绝对数值锁死）。

### 5.3 顶层接线

- 在 `tools/run_snndl_regression_gate.sh` realism/full 轨道中增加 `m55`：
  - 新增 `m55_report_dir` 变量；
  - 调用 `run_tensor_m55_gate.sh`；
  - 输出 `[gate] tensor_m55_report_dir=...`。

## 6. 与真实系统对齐策略（证据链）

M55 不是复刻硬件 RTL，而是构建“可解释 + 可校准”的中间层。对齐策略：

- 用公开模型确认方向：
  - 现代 HBM 系统强调超高带宽（例如 H100 公开规格给出 HBM3 带宽级别）；
  - TPU 架构强调确定性、高吞吐的数据通路；
  - DRAM 模拟研究普遍将 row-hit/row-conflict 与调度策略作为关键延迟来源。
- 对齐方法：
  - 以趋势对齐优先于绝对值对齐；
  - 校准目标先锁定“排序一致 + 量级可解释”；
  - 等 M56/M57 再引入更细命令级约束（避免 M55 过度设计）。

## 7. 一次性执行清单（可直接进入实现）

1. 新增 `docs/plans` 设计稿（本文件）。
2. 实现 M55 gate 脚手架（spec + validator + run script + tests）。
3. 在顶层 regression gate 接入 `m55` report_dir。
4. 在 `TensorWorkload` 增加 `proxy_v2` 参数解析与默认兼容路径。
5. 增加 bank/row 状态机与 pending 队列。
6. 在请求发起路径注入时序延迟并保持旧统计兼容。
7. 导出新增 M55 counters。
8. 扩展 `compute_essential_summary_tensor_mesh.py` 派生字段。
9. 增加 readiness memory 评分“行为可信度”项，避免仅靠开关得分。
10. 跑 `run_tensor_m55_gate.sh` + 顶层 realism gate 验收，并更新 `TECH_PROGRESS.md`。

## 8. 验收标准（M55 Done）

- 功能
  - `tensor_mem_timing_model=off` 时，M0~M54 关键趋势与输出格式不回归；
  - `proxy_v2` 场景下 row/bank/queue 信号可见、趋势符合合同。
- 工程
  - 新增脚本具备 `--skip-unit`、manifest、validation.log；
  - 新增 validator 与 gate 具备单测。
- 联调
  - `SNNDL_GATE_TENSOR_TRACK=realism` 跑通并输出 `tensor_m55_report_dir`；
  - `SNNDL_GATE_TENSOR_TRACK=full` 不破坏现有 m47~m54 结果。

## 9. 风险与回滚

- 风险 1：M55 新参数误触发导致历史 case 漂移。
  - 缓解：默认 `tensor_mem_timing_model=off`，新增逻辑全开关隔离。
- 风险 2：validator 过严导致环境噪声误报。
  - 缓解：采用趋势窗口与比例阈值，不锁死绝对值。
- 风险 3：readiness 被新计数“刷分”。
  - 缓解：引入交叉一致性检查（stall/latency/queue 三信号同向变化）。

## 10. 落地后对“离真实 NPU/TPU 还有多远”的预估

按 memory 子系统维度粗分（仅针对 Tensor-SI）：

- 当前（M54 后）：约 `2.5 / 5`（有带宽/并发代理，缺 row/bank/service 归因）。
- M55 完成后：约 `3.5 / 5`（具备 row/bank/queue/refresh 的可解释代理层）。
- 仍待后续阶段（M56+）：
  - 更细 NoC pipeline/VC 对 memory backpressure 的反压路径；
  - 更完整 DRAM command-level 时序与仲裁策略；
  - 功耗/热约束与 QoS/fairness 联动建模。

---

## 参考资料（用于 M55 设计边界）

- Ramulator 2.0（论文，arXiv）  
  https://arxiv.org/abs/2308.11030
- Ramulator2 官方仓库（支持多标准 + timing constraint 检查）  
  https://github.com/CMU-SAFARI/ramulator2
- NVIDIA H100 官方页面（HBM3 带宽/容量公开规格）  
  https://www.nvidia.com/en-us/data-center/h100/
- TPU v1 论文（ISCA 2017，确定性执行与架构目标）  
  https://arxiv.org/abs/1704.04760
- DRAM row-buffer / FR-FCFS 背景（ATLAS，USENIX）  
  https://www.usenix.org/system/files/conference/hotstorage16/hotstorage16_shang.pdf
