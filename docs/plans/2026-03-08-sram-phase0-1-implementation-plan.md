# SRAM Phase 0/1 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成 SRAM 建模 `Phase 0`（provenance + enforced stall observability）与 `Phase 1`（weight 路径最小可回归 case） 的最小闭环实现。

**Architecture:** 保持现有 `BankedSramModel + budget stall` 主体不变，只补配置 provenance、统计上抛与 summary 输出；实验侧继续使用 `snndl-thing-exp/` 隔离目录，以最小新增 case 补齐 `weight_idx` 与 `weight_l0` 的独立验证入口。实现按 TDD 推进：先补 Python summary/build regression，再补 C++/stats plumbing，再补 case/runner regression。

**Tech Stack:** Python 3、`unittest`、C++17、SST SnnDL、spec-first mesh runner、JSON

---

### Task 1: 锁定 Phase 0 的 Python 回归测试

**Files:**
- Create: `sst_dram_si/mesh_template/test_sram_effective_config_provenance.py`
- Create: `sst_dram_si/tools/test_compute_essential_summary_mesh_sram.py`
- Test: `sst_dram_si/mesh_template/test_sram_effective_config_provenance.py`
- Test: `sst_dram_si/tools/test_compute_essential_summary_mesh_sram.py`

**Step 1: Write the failing tests**
- `test_sram_effective_config_provenance.py` 验证 `effective_config` 同时包含：
  - 结构化 `sram`
  - 最终生效的 `pe.core` SRAM 参数快照
  - override 覆盖后快照值优先于原始 `mesh["sram"]`
- `test_compute_essential_summary_mesh_sram.py` 验证 summary 输出：
  - `state.enforced_stall_cycles_total`
  - `weight_idx/weight_l0` 的 `bank_peak_accesses_per_tick`
  - `state/weight_idx/weight_l0` 的 `energy_*_pj_total`
  - `weight.enforced_stall_cycles_total`

**Step 2: Run tests to verify they fail**
- Run: `python3 -m unittest sst_dram_si.mesh_template.test_sram_effective_config_provenance`
- Run: `python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_sram`
- Expected: FAIL，缺少新字段或输出口径不匹配。

### Task 2: 实现 Phase 0 provenance 收口

**Files:**
- Modify: `sst_dram_si/mesh_template/build.py`
- Modify: `sst_dram_si/mesh_template/spec.py`
- Modify: `sst_dram_si/mesh_template/runtime.py`

**Step 1: Write minimal implementation**
- 在不破坏现有 `components.pe.core` 兼容性的前提下，为 `effective_config.json` 增加最终生效 SRAM 快照。
- 若 schema 允许，补一个一等 `sram` 顶层 schema 入口；若当前 schema 已透传，则至少补 provenance 输出，不扩大行为面。

**Step 2: Run provenance test**
- Run: `python3 -m unittest sst_dram_si.mesh_template.test_sram_effective_config_provenance`
- Expected: PASS

### Task 3: 实现 Phase 0 统计上抛与 summary 输出

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/memory/sram_sim/model/BankedSramModel.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/compute/SnnComputeCore.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `sst_dram_si/tools/compute_essential_summary_mesh.py`

**Step 1: Write minimal implementation**
- 将 `state` 与 `weight` 的 enforced stall cycles 正式上抛到 stats 链。
- 将 `bank_peak_accesses_per_tick` 与 `energy_*_pj_total` 从底层模型一路上抛到 `essential_summary_mesh.json`。
- 同步收口 `Observe-only` 描述，至少避免与当前已进入 timing 的行为相矛盾。

**Step 2: Run tests to verify they pass**
- Run: `python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_sram`
- Expected: PASS

**Step 3: Compile-check affected C++**
- Run: `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`
- Expected: 编译通过

### Task 4: 锁定 Phase 1 的 case 回归测试

**Files:**
- Create: `snndl-thing-exp/tests/test_sram_phase1_cases.py`
- Test: `snndl-thing-exp/tests/test_sram_phase1_cases.py`

**Step 1: Write the failing test**
- 验证 `snndl-thing-exp/cases/` 至少存在：
  - `weight_idx_sram_debug`
  - `weight_l0_fill_smoke`
  - `sram_mixed_smoke`
- 验证这些 case 的 `case.json/spec.json` 能被 `run_case.py --dry-run/--validate-only` 正常解析。

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snndl-thing-exp.tests.test_sram_phase1_cases`
- Expected: FAIL，case 尚未创建。

### Task 5: 实现 Phase 1 最小 case 集

**Files:**
- Create: `snndl-thing-exp/cases/weight_idx_sram_debug/case.json`
- Create: `snndl-thing-exp/cases/weight_idx_sram_debug/spec.json`
- Create: `snndl-thing-exp/cases/weight_l0_fill_smoke/case.json`
- Create: `snndl-thing-exp/cases/weight_l0_fill_smoke/spec.json`
- Create: `snndl-thing-exp/cases/sram_mixed_smoke/case.json`
- Create: `snndl-thing-exp/cases/sram_mixed_smoke/spec.json`
- Modify: `snndl-thing-exp/README.md`
- Modify: `docs/plans/2026-03-08-sram-modeling-deep-dive-design.md`

**Step 1: Write minimal implementation**
- 基于现有 `sram_timing_smoke` 复制最小 spec-first 变体，分别偏置到 `weight_idx`、`weight_l0`、mixed 三种路径。
- 不修改主线目录，不把调试垃圾回灌到 `mainexp/` 或 `sst_dram_si/experiments/`。

**Step 2: Run tests to verify they pass**
- Run: `python3 -m unittest snndl-thing-exp.tests.test_sram_phase1_cases`
- Expected: PASS

### Task 6: 运行最小验证并更新进展

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Run targeted verification**
- Run: `python3 -m unittest sst_dram_si.mesh_template.test_sram_effective_config_provenance`
- Run: `python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_sram`
- Run: `python3 -m unittest snndl-thing-exp.tests.test_sram_phase1_cases`
- Run: `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`
- 可选：`python3 snndl-thing-exp/tools/run_case.py weight_idx_sram_debug --validate-only`
- 可选：`python3 snndl-thing-exp/tools/run_case.py weight_l0_fill_smoke --validate-only`
- 可选：`python3 snndl-thing-exp/tools/run_case.py sram_mixed_smoke --validate-only`

**Step 2: Append progress log**
- 在 `TECH_PROGRESS.md` 记录：改动文件、验证命令、summary 新字段、Phase 1 case 新增情况与后续 TODO。
