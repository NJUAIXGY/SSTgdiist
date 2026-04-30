# TPU-like Tensor 仿真下一大阶段（M15-M17）设计稿

> 说明：本文为设计稿（design-only），不包含实现变更。目标是把 `tensor_si` 从“可趋势门禁的压力模型”推进到“可校准、可解释、可与编译映射对接”的 TPU-like 体系结构仿真子系统。

## 0. 背景与现状锚点

当前仓库已具备：
- 运行模板：`sst_workloads/tensor_si/`（spec/env 驱动，独立输出与校验口径）
- C++ 核心：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.{h,cc}`
  - `exec_mode=bulk|tile|program(M7+)`：从迭代级到 tile 级背压，再到多引擎 program DSL（DMA/MXU/VEC/COLL + fence + issue_width）。
  - NoC/collective：`noc_bandwidth_bytes_per_cycle`、ring_chunked、2D torus staged、credit/backpressure、blocking barrier scope（per_core/per_pe/per_system）。
  - 片上（on-chip）：UB/ACC 容量 + 端口 + bank 冲突队列 + spill（可与 NoC 预算耦合）。
  - DMA：per-core budget + per-PE shared budget（M12）。
- 门禁体系：`tools/run_tensor_m*_gate.sh` + `sst_workloads/tensor_si/tools/validate_tensor_m*_*.py`（趋势/契约校验为主）。

TPU-like 的目标不是指令级 GPU/TensorCore 模拟，而是：
1) 更严格的 scratchpad/驻留语义（避免低估片上压力）。
2) 更可解释的 systolic 阵列时序（fill/drain、利用率损失）。
3) 与“编译映射（mapping）结果”对接，把真实工作负载转为 program/spec 输入。

---

## 1. 目标（M15-M17 总体 DoD）

完成后应满足：
- 给定一份 mapping/工作负载描述，我们能生成可跑的 `tensor_program_dsl` 或 v3 spec。
- 在 `essential_summary_tensor_mesh.json` 中，能观测并归因：
  - UB/weight/acc 各自的容量压力（驻留与峰值占用）
  - bank 冲突与端口瓶颈（stall 分解趋势稳定）
  - systolic 阵列 fill/drain 与利用率损失（可校准）
  - compute/DMA/collective 的 overlap 关系（已有 M2+ 体系延续）
- 默认配置保持向后兼容（M0-M14 specs/gates 行为不破坏；新增特性默认为关闭或兼容路径）。

非目标（M15-M17 不做）：
- 不做 instruction-level（WMMA/MMA）模拟。
- 不引入完整 XLA/MLIR/TVM 前端（先做最小 mapping 输入）。
- 不重构 SST/merlin/memHierarchy 的核心接口。

---

## 2. M15：驻留语义 + 权重池（Weight Pool）真实性闭环

### 2.1 问题定义

当前 tile 模式能表达 dataflow（OS/WS/IS）与 `keep-a/keep-b` 的“减少 DRAM 读”效果，但对 TPU-like 的 scratchpad 来说还不够：
- A/B tile 的 **驻留周期** 没有被严格建模：tile-seg 完成会释放本 seg 的 UB 预留，导致 keep-a/keep-b 的容量压力被低估。
- `tensor_weight_bytes` 的语义需要从“影响 keep-b 判定”升级为真正的 **weight SRAM 池**（并可 bank-aware）。
- on-chip 读端口统计当前以 `need_*_bytes>0` 近似，keep-a/keep-b 时容易失真（该点已在 `TECH_PROGRESS.md` 的 TODO 中出现）。

### 2.2 设计目标（M15 DoD）

- 引入显式的 **驻留对象（resident alloc）**：
  - keep-b（WS + schedule=nkm）：对每个 `(ni, ki)` 的 B tile 建立常驻分配，贯穿 `mi=0..mt-1` 的内层 sweep；只在 sweep 结束时释放。
  - keep-a（IS + schedule=mkn）：对每个 `(mi, ki)` 的 A tile 建立常驻分配，贯穿 `ni=0..nt-1` 的内层 sweep；只在 sweep 结束时释放。
- `tensor_weight_bytes > 0` 时，ReadB 的常驻与 bank/冲突计数优先走 weight pool；否则回退 UB（保持兼容）。
- 新增并导出峰值统计（leader-only 或 per-core 均可，但 summary 要可用）：
  - `tensor_onchip_ub_occupancy_bytes_max`（已存在的话确保准确）
  - `tensor_onchip_weight_occupancy_bytes_max`（新增/修正）
  - `tensor_onchip_acc_occupancy_bytes_max`（已存在的话确保准确）
- 端口计数语义修正：将 tile compute 阶段的 on-chip 读端口需求改为“实际使用的 A/B tile”（考虑 keep-a/keep-b 使 need=0 的 seg 仍然会读片上数据）。

### 2.3 实现切入点（建议，不写代码）

核心文件：
- `.../TensorWorkload.h`：补齐 resident state（例如 `AResidentAlloc`、`BResidentAlloc` map）与 weight pool 分配器接口。
- `.../TensorWorkload.cc`：
  - 在 “ReadA/ReadB 发射前” 做驻留分配/占用更新（UB/weight pool 二选一）。
  - 在 “tile-seg complete -> advance” 阶段 **不再无条件释放** A/B 的 reserved bytes；改为依据驻留生命周期释放。
  - 在 sweep end 位置释放对应 resident alloc（对 nkm/mkn 可由 `mi==mt-1` 或 `ni==nt-1` 等条件判定）。
  - bank-aware：为 weight pool 复用 UB 的 bank 参数或独立参数（推荐复用，KISS）。

门禁与工具：
- 新增 spec（v3）：
  - `tools/specs/tensor_m15_keep_residency_ws_on_v3.json`
  - `tools/specs/tensor_m15_keep_residency_ws_off_v3.json`
  - `tools/specs/tensor_m15_keep_residency_is_on_v3.json`
  - `tools/specs/tensor_m15_keep_residency_is_off_v3.json`
- 新增 gate：
  - `tools/run_tensor_m15_gate.sh`
  - `tools/test_run_tensor_m15_gate.py`
- 新增 validator：
  - `sst_workloads/tensor_si/tools/validate_tensor_m15_residency_trends.py`
  - `sst_workloads/tensor_si/tools/test_validate_tensor_m15_residency_trends.py`

趋势校验建议（只写方向）：
- keep-on 相比 keep-off：
  - DRAM Read bytes 下降（已具备）
  - 但 weight/UB occupancy 峰值上升或不下降（体现驻留压力）
  - bank/port stall 的走势与配置一致（例如 bank_queue_depth 降低时 stall 增长）

---

## 3. M16：Systolic 阵列 fill/drain + 利用率损失（可校准 compute 时序）

### 3.1 问题定义

目前 compute cycles 主要由 `mac_ops / (array_m*array_n*eff)` 推导，再加 pipeline latency。这对趋势有用，但对 TPU-like 体系结构归因不够：
- tile 形状与阵列形状不匹配时的利用率损失难以解释。
- fill/drain（wavefront）开销缺少观测口径，导致“compute 变慢”无法归因到阵列时序 vs memory/NoC。

### 3.2 设计目标（M16 DoD）

在保持模型简洁的前提下，引入可开关、可校准的 wavefront 近似：
- 新增参数（默认关闭，保持兼容）：
  - `tensor_mxu_wavefront_enable`（0/1）
  - `tensor_mxu_wavefront_alpha`（>=0，默认 1.0，校准系数）
  - `tensor_mxu_fill_drain_mode`（`tile_mnk`，默认）
- 当 enable=1 时，对每个 tile-seg 的 compute cycles 采用：
  - `cycles = max(ceil(macs/peak_eff), ceil(alpha * (tm + tn + tk - 2 + pipeline)))`
  - 其中 `tm/tn/tk` 为当前 tile 的有效尺寸（边界 tile 要用实际尺寸）。
- 新增统计（用于 summary/gate）：
  - `tensor_mxu_wavefront_cycles_total`
  - `tensor_mxu_wavefront_cycles_max`（可选）
  - `tensor_mxu_wavefront_util_est_avg`（可选：macs / (cycles * peak)）

### 3.3 门禁建议

- `tools/specs/tensor_m16_wavefront_off_v3.json`
- `tools/specs/tensor_m16_wavefront_on_v3.json`
- 在固定 mem/noC 足够高时：
  - on 的 compute_cycles 上升且可被 wavefront 统计解释
  - off/on 的 DRAM/NoC 指标应基本一致（避免混杂因素）

---

## 4. M17：Mapping -> program/spec（最小软件栈对接）

### 4.1 问题定义

TPU-like “能落地” 的关键分水岭在于：输入不应只是一堆手写 env，而是来自编译/映射（mapping）的结构化结果。

### 4.2 设计目标（M17 DoD）

实现一个最小 mapping 输入格式（JSON/YAML 皆可，推荐 JSON）并提供编译器：
- 输入：描述一个或多个 compute+DMA+collective 的阶段（类似你们 M14 的 training step，但由 mapping 生成）。
- 输出：v3 spec（含 `tensor_program_dsl`）或直接输出 DSL 字符串供注入。
- 支持的最小 primitive：
  - `dma_read(A/B)`、`gemm_ub(tile)`、`dma_write(C)`、`fence`、`allreduce(bytes, blocking)`
- 必须能把 mapping 中的关键决策落到现有参数：
  - tile 形状、dataflow、keep-a/keep-b、UB/weight/acc 容量、double-buffer、DMA bw、NoC bw、collective overlap 策略。

### 4.3 工具与门禁建议

新增工具：
- `sst_workloads/tensor_si/tools/compile_tpu_mapping_to_spec.py`
  - 读取 `mapping.json` → 生成 `tensor_program_dsl` + spec JSON

新增示例/门禁：
- `tools/specs/tensor_m17_mapping_compiled_demo_v3.json`（或在 gate 中动态生成）
- `tools/run_tensor_m17_gate.sh`
- `sst_workloads/tensor_si/tools/validate_tensor_m17_mapping_contract.py`
  - 校验：生成 spec 可跑、program iters 完成、关键统计非零且趋势合理（例如 dma_busy/mxu_busy/epochs_done）。

---

## 5. 风险与缓解

- 风险：M15 改驻留会改变既有 spec 的数值趋势。
  - 缓解：默认路径不变；仅在显式打开 keep/residency 或 weight_bytes>0 且新语义开启时生效；gate 用趋势校验而非绝对值。
- 风险：wavefront 模型引入后 compute 与 memory 的瓶颈归因会迁移。
  - 缓解：M16 gate 要在“mem/noC 足够宽”的控制变量下比较；并用新增统计解释变化。
- 风险：mapping 编译器格式一开始不稳定。
  - 缓解：M17 先只支持一个最小 schema；后续扩展必须保持 backward compatible（schema_version 字段）。

---

## 6. 里程碑交付顺序（建议）

1) M15（驻留 + weight pool + 端口语义修正）先落地并 gate\n
2) M16（wavefront compute 时序）再落地并 gate\n
3) M17（mapping -> program/spec 编译链）最后落地并 gate\n

