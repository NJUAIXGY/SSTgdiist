# SRAM Phase 1-3 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 完成 SRAM 建模 `Phase 1`（case coverage 补全）、`Phase 2`（`weight_l0` 显式 local cache）、`Phase 3`（state SRAM layout-aware chunk timing） 的最小可验证闭环实现。

**Architecture:** 保持现有 `BankedSramModel + phased closure` 主线不推翻，在最小改动下补三个缺口：先把 `Phase 1` 的 `state_sram_debug` case 补齐；再把当前 `experimental idx2 ingress value cache` 升级成显式 `weight_l0` cache 对象；最后把 state 路径从 `noteBulkUniform()` 粗粒度代理升级成基于 `VirtualSramLayout` 的显式地址访问记账。实现优先复用现有 `WeightCacheOps`、`VirtualSramLayout`、`snndl-thing-exp` runner，不额外引入新的大接口。

**Tech Stack:** Python 3、`unittest`、C++17、SST SnnDL、spec-first mesh runner、JSON

---

### Task 1: 锁定 Phase 1/2/3 的回归契约

**Files:**
- Modify: `snndl-thing-exp/tests/test_sram_phase1_cases.py`
- Modify: `snndl-thing-exp/tests/test_sram_phase1_spec_mode_contract.py`
- Create: `sst_dram_si/tools/test_weight_l0_explicit_cache_plumbing.py`
- Create: `sst_dram_si/tools/test_state_sram_layout_timing_plumbing.py`

**Step 1: Write the failing tests**
- `test_sram_phase1_cases.py` 增加 `state_sram_debug` case 存在性与 `--validate-only` 契约。
- `test_sram_phase1_spec_mode_contract.py` 把 `state_sram_debug` 纳入 spec-first 合约集合。
- `test_weight_l0_explicit_cache_plumbing.py` 锁定 `WeightMemorySubsystem` 使用显式 `weight_l0` cache 对象，而不是裸 `unordered_map + deque` 镜像。
- `test_state_sram_layout_timing_plumbing.py` 锁定 `SnnComputeCore` 在 state 路径使用 `VirtualSramLayout` 的显式地址访问，而不是继续依赖 `noteBulkUniform()` 粗粒度代理。

**Step 2: Run tests to verify they fail**
- Run: `python3 -m unittest snndl-thing-exp.tests.test_sram_phase1_cases`
- Run: `python3 -m unittest snndl-thing-exp.tests.test_sram_phase1_spec_mode_contract`
- Run: `python3 -m unittest sst_dram_si.tools.test_weight_l0_explicit_cache_plumbing`
- Run: `python3 -m unittest sst_dram_si.tools.test_state_sram_layout_timing_plumbing`
- Expected: FAIL，说明 `state_sram_debug` 未补齐、Phase 2/3 代码路径仍停留在旧实现。

### Task 2: 完成 Phase 1 case coverage

**Files:**
- Create: `snndl-thing-exp/cases/state_sram_debug/case.json`
- Create: `snndl-thing-exp/cases/state_sram_debug/spec.json`
- Modify: `snndl-thing-exp/README.md`

**Step 1: Write minimal implementation**
- 增加 `state_sram_debug`：关闭 `weight_idx/weight_l0`，开启 `state SRAM`，保持低 fanout 与稳定随机激活，确保 state 路径独立非零。
- README 补充四条 SRAM case 的用途矩阵。

**Step 2: Run tests to verify they pass**
- Run: `python3 -m unittest snndl-thing-exp.tests.test_sram_phase1_cases`
- Run: `python3 -m unittest snndl-thing-exp.tests.test_sram_phase1_spec_mode_contract`
- Expected: PASS

### Task 3: 实现 Phase 2 `weight_l0` 显式 local cache

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Reference: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightCacheOps.h`
- Reference: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightCacheOps.cc`

**Step 1: Write minimal implementation**
- 用显式 `weight_l0` cache 对象替代当前 `experimental_idx2_ingress_value_cache_ + deque` 镜像实现。
- 统一 `lookup/hit/fill/evict` 与功能状态：lookup 走 cache 对象，fill/evict 由同一对象驱动。
- `resident_bytes_peak` 至少纳入数据 + tag/meta 近似成本，不再仅按 `sizeof(float)` 估算。
- 保持现有 `experimental_idx2_ingress_prefetch_*` 行为兼容，不重写整个 prefetch 状态机。

**Step 2: Run plumbing test**
- Run: `python3 -m unittest sst_dram_si.tools.test_weight_l0_explicit_cache_plumbing`
- Expected: PASS

### Task 4: 实现 Phase 3 state layout-aware timing

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/compute/SnnComputeCore.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/compute/SnnComputeCore.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/memory/sram_sim/layout/VirtualSramLayout.h`

**Step 1: Write minimal implementation**
- 为 state SRAM 增加显式地址访问 helper，至少覆盖：
  - `updateNeuronStates()` 的 `vmem/refrac` sweep
  - `applyPendingDeltas_()` 的 `vmem` read/write
  - `fire()` 成功发放时的 `last_spike` 成本
- 将 `state` 路径从 `noteBulkUniform()` 粗粒度代理升级成基于 `VirtualSramLayout` 的显式 `noteRead()/noteWrite()` 记账。
- 不引入完整 local controller；仍沿用现有 `state_sram_stall_budget_` 消费路径。

**Step 2: Run plumbing test**
- Run: `python3 -m unittest sst_dram_si.tools.test_state_sram_layout_timing_plumbing`
- Expected: PASS

### Task 5: 编译与真实 case 验证

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Run focused regressions**
- Run: `python3 -m unittest sst_dram_si.mesh_template.test_sram_effective_config_provenance`
- Run: `python3 -m unittest sst_dram_si.mesh_template.test_runtime_input_path_resolution`
- Run: `python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_sram`
- Run: `python3 -m unittest sst_dram_si.tools.test_sram_pe_aggregation_plumbing`
- Run: `python3 -m unittest sst_dram_si.tools.test_weight_l0_explicit_cache_plumbing`
- Run: `python3 -m unittest sst_dram_si.tools.test_state_sram_layout_timing_plumbing`
- Run: `python3 -m unittest snndl-thing-exp.tests.test_sram_phase1_cases`
- Run: `python3 -m unittest snndl-thing-exp.tests.test_sram_phase1_spec_mode_contract`

**Step 2: Compile-check affected C++**
- Run: `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`
- Expected: PASS

**Step 3: Run real cases**
- Run: `python3 snndl-thing-exp/tools/run_case.py state_sram_debug`
- Run: `python3 snndl-thing-exp/tools/run_case.py weight_idx_sram_debug`
- Run: `python3 snndl-thing-exp/tools/run_case.py weight_l0_fill_smoke`
- Run: `python3 snndl-thing-exp/tools/run_case.py sram_mixed_smoke`
- Expected:
  - `state_sram_debug`：`sram.state.*` 非零，weight 路径尽量低/零
  - `weight_idx_sram_debug`：`sram.weight_idx.*` 非零
  - `weight_l0_fill_smoke`：`sram.weight_l0.lookup/fill` 非零
  - `sram_mixed_smoke`：`state + weight_idx + weight_l0` 同时非零

**Step 4: Append progress log**
- 在 `TECH_PROGRESS.md` 记录 Phase 1/2/3 的改动、验证命令、真实 run 目录、关键指标与后续 TODO。
