# TPU-like M15-M17 Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** 在保持既有 M0-M14 回归门禁不破坏的前提下，落地 TPU-like 路线的 M15（驻留/weight pool 真实性）、M16（wavefront fill/drain 可校准 compute）、M17（mapping->program/spec 编译链）并配套 specs/validators/gates。

**Architecture:** 以 `TensorWorkload` 为唯一 C++ 语义承载点（tile/program 两条路径），通过新增参数保持默认兼容；所有行为通过 `tools/specs/*.json` + `tools/run_tensor_m*_gate.sh` + `sst_workloads/tensor_si/tools/validate_tensor_m*_*.py` 做趋势/契约门禁。

**Tech Stack:** C++17 (SST element), Python3 validators/tools, Bash gate scripts.

---

### Task 1: M15 Weight Pool + Residency Semantics (tile)

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.cc`
- Modify: `sst_workloads/tensor_si/tools/compute_essential_summary_tensor_mesh.py`
- Create: `tools/specs/tensor_m15_keep_a_on_tpuv1_v3.json`
- Create: `tools/specs/tensor_m15_keep_a_off_tpuv1_v3.json`
- Create: `tools/specs/tensor_m15_keep_b_on_tpuv1_v3.json`
- Create: `tools/specs/tensor_m15_keep_b_off_tpuv1_v3.json`
- Create: `tools/specs/tensor_m15_keep_a_on_bf16_v3.json`
- Create: `tools/specs/tensor_m15_keep_a_off_bf16_v3.json`
- Create: `tools/specs/tensor_m15_keep_b_on_bf16_v3.json`
- Create: `tools/specs/tensor_m15_keep_b_off_bf16_v3.json`
- Create: `tools/run_tensor_m15_gate.sh`
- Create: `tools/test_run_tensor_m15_gate.py`
- Create: `sst_workloads/tensor_si/tools/validate_tensor_m15_residency_trends.py`
- Create: `sst_workloads/tensor_si/tools/test_validate_tensor_m15_residency_trends.py`

**Step 1: Add weight pool state + stats + reservation helpers**
- Add weight pool occupancy/bank queue state and exported stats:
  - `tensor_onchip_weight_occupancy_bytes_max`
  - `tensor_onchip_weight_bank_occupancy_bytes_max`
- Add resident observability stats:
  - `tensor_onchip_a_resident_tiles_max`
  - `tensor_onchip_b_resident_tiles_max`

**Step 2: Implement ReadB reservation to weight pool when `tensor_weight_bytes>0`**
- When on-chip model enabled and `weight_bytes>0`, ReadB allocations should consume weight pool capacity/banks; fallback to spill or stall per existing spill policy.

**Step 3: Implement keep-a/keep-b residency lifecycle**
- keep-a (IS + schedule mkn): A resident across `ni` sweep; release on last `ni`.
- keep-b (WS + schedule nkm): B resident across `mi` sweep; release on last `mi`.

**Step 4: Gate + validator (dual baseline)**
- Gate runs 8 scenarios (TPUv1-like + bf16-like, keep-a/b on/off).
- Validator checks:
  - keep-on: `*_resident_tiles_max > 0`
  - keep-off: `*_resident_tiles_max == 0`
  - 基本契约：关键字段存在且非负。

**Step 5: Verification**
- Build: `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
- Unit tests: `python3 -m unittest tools/test_run_tensor_m15_gate.py sst_workloads/tensor_si/tools/test_validate_tensor_m15_residency_trends.py -v`
- E2E gate: `bash "tools/run_tensor_m15_gate.sh" --skip-unit`

---

### Task 2: M16 Wavefront (fill/drain) Compute Model (tile)

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.cc`
- Modify: `sst_workloads/tensor_si/tensor_template/spec.py`
- Modify: `sst_workloads/tensor_si/tensor_template/runtime.py`
- Modify: `sst_workloads/tensor_si/tools/compute_essential_summary_tensor_mesh.py`
- Create: `tools/specs/tensor_m16_wavefront_off_tpuv1_v3.json`
- Create: `tools/specs/tensor_m16_wavefront_on_tpuv1_v3.json`
- Create: `tools/specs/tensor_m16_wavefront_off_bf16_v3.json`
- Create: `tools/specs/tensor_m16_wavefront_on_bf16_v3.json`
- Create: `tools/run_tensor_m16_gate.sh`
- Create: `tools/test_run_tensor_m16_gate.py`
- Create: `sst_workloads/tensor_si/tools/validate_tensor_m16_wavefront_trends.py`
- Create: `sst_workloads/tensor_si/tools/test_validate_tensor_m16_wavefront_trends.py`

**Key behavior:**
- Add params:
  - `tensor_mxu_wavefront_enable` (0/1)
  - `tensor_mxu_wavefront_alpha` (float, default 1.0)
- When enabled, per tile-seg add extra cycles captured in:
  - `tensor_mxu_wavefront_cycles_total`

**Verification:**
- On vs off: 在 mem/noC 充分宽时，`tensor_compute_cycles_total(on) > off` 且 `tensor_mxu_wavefront_cycles_total(on) > 0`。

---

### Task 3: M17 Mapping -> program/spec Compiler + Gate

**Files:**
- Create: `sst_workloads/tensor_si/tools/compile_tpu_mapping_to_spec.py`
- Create: `sst_workloads/tensor_si/tools/validate_tensor_m17_mapping_contract.py`
- Create: `sst_workloads/tensor_si/tools/test_validate_tensor_m17_mapping_contract.py`
- Create: `tools/run_tensor_m17_gate.sh`
- Create: `tools/test_run_tensor_m17_gate.py`
- Create: `tools/specs/tensor_m17_mapping_demo_tpuv1.json` (mapping input, not spec)
- Create: `tools/specs/tensor_m17_mapping_demo_bf16.json`

**Key behavior:**
- Compiler reads mapping JSON and emits a valid schema v3 tensor spec with `tensor_exec_mode=program` and `tensor_program_dsl` filled.
- Gate compiles mapping -> temp spec -> runs `tools/run_snndl_with_time.sh --spec ...` -> validates summary.

**Verification:**
- Summary contains `tensor_program_iters_total > 0` and training-step ops counters/epochs done (按 mapping 描述) 非零。

---

### Task 4: Update Progress Log

**Files:**
- Modify: `TECH_PROGRESS.md`

Append one entry summarizing M15-M17 changes, how to run gates, and where outputs go.

