# SnnDL `riscv_snn` Phase D Equivalence Closure Plan

Date: 2026-03-25
Owner: Fufu
Status: Draft after Phase C dated reference

## 1. 目标

`Phase D` 的目标不是继续扩 `compare surface`，而是把 `Phase C` 已经跑出来的真实 blocker 收硬，让 `equiv --family external_dyn_desc_ref` 从“能稳定产出 summary”推进到“至少稳定 `WARN`，并为最终 `PASS` 清空主要技术债”。

## 2. 当前已知事实

基于：

- `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-25-external-dyn-desc-ref-equiv.json`

当前事实已经比较清楚：

1. strict compare 全部匹配。
2. trend compare 当前逐项 `delta = 0`。
3. baseline 侧 `validation = failed`，唯一 fail 项是：
   - `step_activation.invocations_vs_windows: invocations=51 windows=59`
4. runtime_bridge 侧 `validation = passed_with_warning`。
5. `runtime_stats` 仍为空，也就是：
   - `riscv_snn_fused_step_completion_count`
   - `riscv_snn_completion_visible_count`
   - `riscv_snn_fault_count`
   - `riscv_snn_last_completion_status`
   - `riscv_snn_last_fault_csr`
   还没有真正进入最终 artifact surface。

因此，Phase D 的问题不是“结果不一致”，而是“gate 还没定义到研究平台可接受的粒度”。

## 3. Phase D Exit Criteria

### D0 最低闭环

1. `equiv --family external_dyn_desc_ref` 始终会输出 dated summary。
2. compare harness 对 smoke 非零有明确 surface：
   - `smoke_returncode`
   - `validation.summary`
3. 默认 `snn` 主路径不因 Phase D 实验逻辑发生语义变化。

### D1 baseline gate 收口

1. `snn` baseline 不再因为与 equivalence 目标无关的 validator 条目直接卡死整个 compare gate。
2. 这种放宽必须是：
   - compare-specific
   - 可审计
   - 不污染默认 `paper` / `dev` 验证语义

### D2 runtime-bridge stats 收口

1. runtime bridge 关键统计进入最终 `mesh_stats.csv`。
2. `riscv_snn_lab.py` 能在 summary 里稳定读到：
   - `riscv_snn_fused_step_completion_count`
   - `riscv_snn_completion_visible_count`
   - `riscv_snn_fault_count`
3. 当 baseline gate 闭环后，当前 family 至少可以稳定得到 `WARN`。

### D3 towards PASS

1. `WARN` 只剩“runtime bridge 计数未满足 PASS 阈值”这类单一、可解释原因。
2. 当 `fused_step_completion_count > 0` 且双方 validation 都可接受时，family 能升到 `PASS`。

## 4. 设计约束

Phase D 继续遵守实验主线隔离原则：

1. 不把 equivalence 特判塞进默认 `snn` 主逻辑。
2. 不新增第二份 metadata authority。
3. 不把 runtime bridge 统计读取路径写成对 `SnnWorkload` 主线的强依赖。
4. compare-specific validator 行为必须通过 lab sidecar 或显式 profile / env / summary gate 表达，而不是静默改变默认验证标准。

## 5. Task D1: Baseline Validation Surface Isolation

### 问题

当前 baseline 的唯一 fail 是：

- `step_activation.invocations_vs_windows`

但对 `Phase C` equivalence 来说，这个条目不是当前 fixed compare surface 的主目标。

### 推荐方向

优先顺序如下：

1. 新增一个 compare-specific validation mode，仅在 `equiv` family 下启用。
2. 如果不引入新 profile，则在 lab wrapper 中把“validator 原始结果”和“equiv gate 结果”显式拆层。
3. 只在 `external_dyn_desc_ref_snn_baseline` 这种固定 family surface 下，针对已知非目标条目做显式 waiver。

### 不推荐

1. 全局放宽 `validate_essential_summary_mesh.py` 对 `workload_impl=snn` 的默认约束。
2. 为了躲过 validator 而把 baseline spec 改成弱活动、零 memory 的 run。

### 退出标准

1. baseline 侧不再因为这条非目标 validator fail 导致整个 family 直接 `FAIL`。
2. waiver/profile 记录在文档与 summary 中可见。

## 6. Task D2: Runtime Bridge Stats Visibility

### 问题

runtime bridge 的关键 completion/fault 统计没有进入最终 `mesh_stats.csv`，导致：

1. `runtime_stats` 在 dated summary 中为空。
2. compare harness 即便 strict/trend 对齐，也无法判断 runtime bridge 是否真的完成过 `FUSED_STEP`。

### 实施方向

1. 确认 `RiscvSnnWorkload` / `RiscvSnnRuntimeBridgeBackend` 当前内部已经维护了哪些计数。
2. 把这些计数接到最终 statistics export surface。
3. 保证：
   - `runtime_bridge` 有统计
   - `null` backend 不会伪造这些统计
4. 为 stats path 加单测与 parser test：
   - SnnDL 侧确认统计产生
   - lab 侧确认 summary 读取

### 退出标准

1. `mesh_stats.csv` 中可见 `riscv_snn_*` completion/fault 统计。
2. `equiv` summary 中 `runtime_bridge.runtime_stats` 不再为空。

## 7. Task D3: Equivalence Gate Refinement

### 目标

在不增加第二份 authority 的前提下，把 `equiv` 的 gate 语义收紧到更可审阅的程度。

### 建议项

1. 在 summary 中保留：
   - `smoke_returncode`
   - `validation.summary`
   - strict rows
   - trend rows
   - runtime-only rows
2. 给 `FAIL` / `WARN` 增加更细的 reason surface，例如：
   - `validation_failed`
   - `runtime_stats_missing`
   - `strict_mismatch`
3. 在 README / note 中固定 CLI 退出码含义。

## 8. 建议执行顺序

1. D1 baseline validation surface isolation
2. D2 runtime bridge stats visibility
3. D3 equivalence gate refinement
4. 复跑 dated reference，并把结果写回 `README` / `notes` / `TECH_PROGRESS`

## 9. 验证命令

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  sst_dram_si.mesh_template.test_spec_resolver \
  sst_dram_si.mesh_template.test_build_synapse_modes \
  sst_dram_si.mesh_template.test_runtime_thermal_config \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

cd "/home/xgy/remote" && \
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate \
  "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_snn_baseline.json"

cd "/home/xgy/remote" && \
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate \
  "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_runtime_bridge.json"

cd "/home/xgy/remote" && \
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" \
  equiv --family external_dyn_desc_ref
```

## 10. 预期交付

1. 一份新的 dated `equiv` summary。
2. baseline validator gate 的明确策略。
3. runtime bridge stats 进入 artifact surface 的证据。
4. 若未到 `PASS`，也必须能把“为何仍是 `WARN/FAIL`”压缩成 1 到 2 个明确原因。
