# Tensor M2 设计：Compute-DMA-Collective 统一重叠与带宽约束模型

> 目标读者：项目维护者/后续实现者。本文为 M2 的设计草案（仅设计，不含实现变更）。

## 1. 背景与问题定义

M0 解决了基线冻结与契约门禁，M1 解决了计算真实性（precision profile + math/pipeline 统计 + 趋势校验）。  
当前 `tensor_exec_mode=tile` 已有 tile 级推进与读/算/写分解，但仍存在两个关键缺口：

1. `collective` 的发送目前是“事件触发后尽快发完”，缺少与其他流量共享的 NoC 带宽预算。
2. compute 与 collective 之间缺少可配置的重叠策略，导致“可落地 NPU/TPU”中常见的 pipeline 竞争关系无法表达。

M2 的目标是把 **compute / DRAM-DMA / collective-NoC** 纳入统一周期预算框架，在保持向后兼容的前提下提供可验证、可门禁的时序语义。

---

## 2. 目标与非目标

### 2.1 目标（DoD）

1. 建立统一“按周期预算”模型，至少覆盖 `tensor_exec_mode=tile`。
2. collective 发送进入“可节流”路径，支持 NoC 字节预算与排队推进。
3. 引入 compute 与 collective 的重叠策略开关，并提供对应统计。
4. 提供 M2 gate（spec 场景 + 趋势校验），确保行为可回归。
5. 默认配置保持 M1 行为（不破坏现有 M0/M1 场景与门禁）。

### 2.2 非目标（M2 不做）

1. 不实现 instruction-level tensor core 微架构。
2. 不引入跨核/跨节点的真实 NoC 拥塞反演模型（保持当前抽象层级）。
3. 不重构 DRAM 后端接口（仍用现有 `IMemoryAccess` 请求语义）。
4. 不在 M2 阶段改动 `mesh_template` 主链路。

---

## 3. 现状差距（基于当前代码）

参考路径：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.h`

现状要点：
- tile 模式已具备：读请求发射、写回队列、prefetch（`tile_next_`）、stall 分解（budget/outstanding/read/write/collective）。
- `tensor_dma_bandwidth_bytes_per_cycle` 仅约束内存侧请求发射，不约束 collective 发包。
- collective 在触发时按 `collective_bytes/packet_bytes` 直接注入若干包，缺乏“每周期可发送字节上限”。
- compute 对 collective 的依赖仅体现在 blocking barrier 完成条件，缺少“同周期竞争”可观测指标。

结论：M1 的计算真实性成立，但“通信-计算资源竞争”仍是离散的，不足以代表可落地 NPU/TPU 的 pipeline 时序。

---

## 4. 方案选择

### 方案 A：全离散事件多引擎（复杂）
- 为 compute/mem/noc 建立独立事件队列与仲裁器。
- 精细但改动面大，风险高，超出 M2 目标。

### 方案 B：统一周期预算 + 轻量队列（推荐）
- 保持现有 `onClockTickTile_()` 主循环。
- 增加 NoC 预算与 collective pending 队列。
- 在同一 tick 内执行：预算分配 -> 请求发射 -> 计算推进 -> 统计。
- 低侵入、可快速落地并可门禁。

### 方案 C：纯解析模型（无队列）
- 通过公式近似重叠，不逐周期推进。
- 开发快，但与当前 tile 语义耦合弱，难解释调试。

推荐采用方案 B（KISS + 向后兼容 + 可测性最佳）。

---

## 5. 详细设计（推荐方案 B）

### 5.1 新增配置参数（默认兼容）

新增到 `TensorWorkload::Config` / `SnnPESubComponent` / `tensor_template/spec.py/runtime.py`：

1. `tensor_noc_bandwidth_bytes_per_cycle`（uint64，默认 `0`）  
   - `0` 表示沿用旧行为（NoC 发送不做预算限制）。
   - `>0` 时，collective/comm 共享此预算。

2. `tensor_collective_overlap_with_compute`（bool，默认 `1`）  
   - `1`：允许 collective 发送与 compute 同周期并行推进。
   - `0`：存在 collective pending 时阻塞 compute（可用于下界建模）。

3. `tensor_collective_issue_priority`（string，默认 `control_first`）  
   - 预留策略：`control_first` / `payload_first`（M2 初版仅实现 `control_first`，其余值回退默认）。

### 5.2 collective 发射语义改造

将“触发即全发”改为“两阶段”：

1. 触发阶段：生成 epoch 发送计划（pending bytes per destination）。
2. 推进阶段：每个时钟按 `noc_budget` 发射最多 `budget` 字节，按 `packet_bytes` 切包。

关键状态（建议新增）：
- `collective_pending_active_`
- `collective_pending_total_bytes_`
- `collective_pending_sent_bytes_`
- `collective_pending_per_dest_[]`

约束规则：
- 若 `tensor_noc_bandwidth_bytes_per_cycle==0`，保持 M1 快路径（等价“无限预算”）。
- blocking collective 的“完成条件”由“已收到字节”与“发送计划完成”共同决定。

### 5.3 compute/collective 重叠策略

在 tile compute 推进前增加判定：

- `collective_can_overlap = tensor_collective_overlap_with_compute != 0`
- 若 `collective_pending_active_ && !collective_can_overlap`：  
  - 本周期 compute 不推进；
  - 计入 `tensor_stall_collective_cycles_total`（沿用已有口径）。

### 5.4 预算仲裁顺序（M2 初版）

在 `onClockTickTile_()` 每周期处理顺序：

1. DRAM 预算：沿用现有顺序  
   `cur read -> writeback -> next prefetch`
2. NoC 预算：新增顺序  
   `collective control -> collective payload -> optional comm`
3. Compute 推进  
4. 迭代完成判定与 stall 分类

说明：M2 不引入全局公平调度，先确保 deterministic 与可解释。

### 5.5 新增统计项（M2）

建议新增（PE 聚合）：

1. `tensor_collective_pending_cycles_total`  
   - collective pending 非空的周期数。
2. `tensor_collective_issue_cycles_total`  
   - 本周期成功发出至少 1 个 collective 包。
3. `tensor_stall_noc_budget_cycles_total`  
   - 因 NoC 预算不足导致 collective/comm 无法继续发射。
4. `tensor_overlap_compute_collective_cycles_total`  
   - 同周期既有 compute 推进又有 collective 发射。
5. `tensor_overlap_compute_mem_cycles_total`（可选）  
   - 同周期既有 compute 推进又有 mem 请求发射。

同时更新：
- `TensorWorkloadStatsModule.h`
- `MultiCorePE.h`
- `compute_essential_summary_tensor_mesh.py`（派生 overlap ratio）

---

## 6. 验证与门禁设计（M2 Gate）

### 6.1 场景集（建议）

至少 4 个 `schema_version=3` spec（tile）：

1. `m2_tile_baseline_compat`：`noc_bw=0`（兼容快路径）
2. `m2_tile_noc_capped_overlap_on`：`noc_bw>0`，`overlap=1`
3. `m2_tile_noc_capped_overlap_off`：`noc_bw>0`，`overlap=0`
4. `m2_tile_noc_capped_heavy_collective`：更大 collective bytes，用于放大趋势

### 6.2 趋势校验（`validate_tensor_m2_trends.py`）

采用趋势+结构校验（不写死绝对阈值）：

1. `noc_bw=0` 与 M1 兼容：关键统计字段存在，且无负值。
2. `overlap_on` 对比 `overlap_off`：  
   - `tensor_overlap_compute_collective_cycles_total(on) > 0`
   - `tensor_overlap_compute_collective_cycles_total(off) == 0`
3. 在相同 `noc_bw>0` 下：
   - `overlap_off` 的 `tensor_stall_collective_cycles_total` 不低于 `overlap_on`
4. `noc_bw` 受限场景必须出现：
   - `tensor_collective_pending_cycles_total > 0`
   - 或 `tensor_stall_noc_budget_cycles_total > 0`

### 6.3 预期新增文件

- `tools/specs/tensor_m2_*.json`（4+）
- `tools/run_tensor_m2_gate.sh`
- `sst_workloads/tensor_si/tools/validate_tensor_m2_trends.py`
- `tools/test_run_tensor_m2_gate.py`
- `sst_workloads/tensor_si/tools/test_validate_tensor_m2_trends.py`

---

## 7. 影响文件与实现边界

核心实现（M2）：
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/workload_stats/TensorWorkloadStatsModule.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`

spec/runtime/分析：
- `sst_workloads/tensor_si/tensor_template/spec.py`
- `sst_workloads/tensor_si/tensor_template/runtime.py`
- `sst_workloads/tensor_si/tools/compute_essential_summary_tensor_mesh.py`
- `sst_workloads/tensor_si/README.md`

门禁/测试：
- `tools/run_tensor_m2_gate.sh`
- `sst_workloads/tensor_si/tools/validate_tensor_m2_trends.py`
- `tools/test_run_tensor_m2_gate.py`
- `sst_workloads/tensor_si/tools/test_validate_tensor_m2_trends.py`
- `tools/test_snndl_spec_cli.py`
- `sst_workloads/tensor_si/test_tensor_spec.py`

---

## 8. 风险与缓解

1. 风险：引入 NoC 预算后，collective 完成条件可能与现有 blocking 逻辑冲突。  
   缓解：先在 `per_core` scope 打通，再扩展 `per_pe/per_system`。

2. 风险：统计口径扩展导致 gate 首次波动。  
   缓解：延续 M1 的“结构+趋势”校验，避免首版硬阈值。

3. 风险：默认行为不兼容。  
   缓解：`tensor_noc_bandwidth_bytes_per_cycle=0` 时强制走兼容路径。

---

## 9. 分阶段执行计划（实现前任务拆解）

### 阶段 M2.1：NoC 预算与 collective pending
- 仅引入 `tensor_noc_bandwidth_bytes_per_cycle` + pending 队列。
- 不改 compute 重叠语义。
- 目标：不破坏 M1，新增统计可观测。

### 阶段 M2.2：compute/collective 重叠开关
- 引入 `tensor_collective_overlap_with_compute`。
- 增加 overlap/stall 统计。
- 目标：形成可验证的 on/off 趋势差异。

### 阶段 M2.3：M2 gate 与文档闭环
- 增加 M2 specs、validator、gate、单测。
- 更新 `TECH_PROGRESS.md` 与 `sst_workloads/tensor_si/README.md`。

---

## 10. 验收命令（实现完成后的期望）

1. 编译检查  
   `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile`

2. M1 回归  
   `bash "tools/run_tensor_m1_gate.sh" --skip-unit`

3. M2 gate  
   `bash "tools/run_tensor_m2_gate.sh" --skip-unit`

4. 组合单测  
   `PYTHONPATH="sst_workloads/tensor_si" python3 -m unittest "tools/test_snndl_spec_cli.py" "tools/test_run_tensor_m2_gate.py" "sst_workloads/tensor_si/test_tensor_spec.py" "sst_workloads/tensor_si/tools/test_validate_tensor_m2_trends.py" -v`

---

## 11. 结论

M2 推荐采用“统一周期预算 + 轻量队列”方案：  
在不推翻现有 tile 模型的前提下，引入 collective 可节流与 compute/collective 重叠语义，使 tensor_si 从“计算真实性”迈向“计算-通信联合时序真实性”，为后续 M3（更细粒度数据搬运与片上缓存冲突模型）打基础。

