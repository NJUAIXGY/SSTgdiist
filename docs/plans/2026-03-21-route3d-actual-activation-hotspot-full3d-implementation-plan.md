# Route3D Actual Activation + Full3D HotSpot Path Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `route3d` 从“expected trigger”推进到“actual runtime activation evidence”，并让 `full_3d` case 默认进入 HotSpot sidecar 主路径，正式产出 `thermal_sidecar` 产物与 phase2 摘要字段。

**Architecture:** 本轮采用两条最短闭环并行推进的方式。第一条在 `route3d` C++ 内核里增加最小 runtime marker，并由 `run_case.py` 解析 SST stdout，把 native path 的真实激活证据沉淀到 `phase2_case_summary.route_kernel`。第二条不改动主时序，只给 `full_3d` case 打开现有 thermal sidecar 配置，让 `build_platform_summary()` 现有 HotSpot adapter/driver 链路真正落盘到该 case 的默认运行路径。

**Tech Stack:** C++17、Python 3、`unittest`、SST/SnnDL、append-only progress logging

---

### Task 1: 先把 `route_kernel` 的 actual activation 缺口锁成失败测试

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_cpp_route_decoupling_contract.py`

**Step 1: Write the failing tests**

- 在 `test_run_case.py` 中新增针对 `route_kernel` 的测试，要求：
  - 当 SST stdout 含有 `route3d native runtime activation` marker 时，`build_phase2_case_summary(...)` 或相应 helper 能输出：
    - `actual_activation_observed = true`
    - `actual_activation_source = "sst_stdout_route3d_native_runtime"`
    - `runtime_marker_count > 0`
  - 当缺少该 marker 时：
    - `actual_activation_observed = false`
    - `actual_activation_source = ""`
    - 仍保留现有 `expected_active` 语义
- 在 `test_cpp_route_decoupling_contract.py` 中新增 contract，锁定：
  - runtime marker 只存在于 `route3d` 本地实现文件
  - 不要求扩展 `ISynapseRoute` 公共接口

**Step 2: Run test to verify it fails**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_case.RunCaseTests.test_build_phase2_case_summary_reports_route3d_actual_runtime_activation_from_sst_stdout snn3dexp.tests.test_run_case.RunCaseTests.test_build_phase2_case_summary_keeps_expected_route_kernel_when_runtime_marker_missing snn3dexp.tests.test_cpp_route_decoupling_contract.CppRouteDecouplingContractTests.test_route3d_runtime_activation_marker_remains_route3d_local -v`

Expected:
FAIL，明确暴露 `route_kernel` 只有 `expected_active`，还没有 actual runtime activation 字段与解析逻辑。

### Task 2: 最小实现 `route3d` runtime marker 与 Python 解析

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`
- Modify: `/home/xgy/remote/snn3dexp/tools/run_case.py`

**Step 1: Write minimal implementation**

- 在 `SynapseRouteSubsystem3D` 本地增加最小 runtime marker 状态，例如：
  - 是否已打印首次 native runtime activation marker
  - native runtime activation 计数/首次命中条件
- 在 `computeFanoutNative3D_()` 中，当 native path 真实产出 fanout 或 gating fanout 时，输出稳定 marker，例如：
  - 含 `node/core/source/fanout/applied_gating/native_runtime_activation`
  - 文本前缀固定，便于 Python 正则解析
- 在 `run_case.py` 中新增 helper：
  - 从 `sst_smoke.stdout.log` 提取 route3d native runtime marker
  - 把解析结果注入 `route_kernel`：
    - `actual_activation_observed`
    - `actual_activation_source`
    - `runtime_marker_count`
    - `runtime_marker_samples`（可保留少量样本，避免过大）
- 保持边界：
  - 不改 `ISynapseRoute` 公共接口
  - 不改 `SpikeCommSubsystem` 契约
  - `expected_active` 继续保留，作为 artifact-level 先验条件

**Step 2: Run tests to verify green**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_case.RunCaseTests.test_build_phase2_case_summary_reports_route3d_actual_runtime_activation_from_sst_stdout snn3dexp.tests.test_run_case.RunCaseTests.test_build_phase2_case_summary_keeps_expected_route_kernel_when_runtime_marker_missing snn3dexp.tests.test_cpp_route_decoupling_contract.CppRouteDecouplingContractTests.test_route3d_runtime_activation_marker_remains_route3d_local -v`

Expected:
PASS

### Task 3: 先把 `full_3d` case 默认切到 HotSpot sidecar 主路径

**Files:**
- Modify: `/home/xgy/remote/snn3dexp/cases/full_3d/spec.json`
- Modify: `/home/xgy/remote/snn3dexp/tests/test_run_case.py`

**Step 1: Write the failing test**

- 在 `test_run_case.py` 中新增测试，要求执行 `full_3d` case 的 compose 路径后：
  - `effective_config["thermal"]["enabled"] == true`
  - `platform_summary["thermal_hotspot_adapter"]["driver"]["enabled"] == true`
  - `platform_summary["thermal_hotspot_adapter"]["driver"]["status"]` 为：
    - `skipped_missing_binary`，或
    - 真实 HotSpot 运行状态
  - `driver.artifacts["thermal_summary_json"]`、`driver.artifacts["window_power_samples_jsonl"]` 存在
  - `phase2_case_summary["thermal_input"]["input_source_kind"] == "local_hotspot_sidecar"`

**Step 2: Run test to verify it fails**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_run_case.RunCaseTests.test_execute_case_full_3d_enables_hotspot_sidecar_by_default -v`

Expected:
FAIL，因为当前 `full_3d/spec.json` 默认 `thermal.enabled=false`。

**Step 3: Write minimal implementation**

- 在 `full_3d/spec.json` 中增加 `thermal` 段，最小建议值：
  - `"enabled": true`
  - `"mode": "proxy_only"`
  - `"out_dir": "thermal_sidecar"`
  - `"model_type": "grid"`
  - 维持 `hotspot_bin` 为空，使无二进制时仍能产出 sidecar artifacts
- 不改变当前 runtime/NoC/memory 行为，只启用现有 sidecar 导出链

**Step 4: Run test to verify it passes**

Run the same unittest command again and expect PASS.

### Task 4: 回归验证、必要编译与真实 smoke

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run focused Python regression**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract snn3dexp.tests.test_cpp_route_decoupling_contract snn3dexp.tests.test_run_case -v`

Expected:
PASS

**Step 2: Run C++ build verification**

Run:
`cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`

Expected:
exit code `0`

**Step 3: Run one real `full_3d` smoke**

Run:
`cd /home/xgy/remote && python3 -m snn3dexp.tools.run_case full_3d --run-tag task_route3d_actual_activation_hotspot_full3d --sst-smoke --stop-at 250ns`

Expected:
- `phase2_case_summary.route_kernel.actual_activation_observed == true`（若 marker 出现）
- `phase2_case_summary.thermal.hotspot_driver_status != "disabled"`
- `thermal_sidecar/summary/thermal_summary.json` 落盘

**Step 4: Append progress**

- 只追加 `TECH_PROGRESS.md`
- 记录：
  - route3d actual runtime activation 证据口径
  - full_3d HotSpot sidecar 默认开启
  - 真实 smoke 与产物路径
  - 下一步是否进入真实 HotSpot binary/温度场校验

## Out of Scope For This Batch

- 不把 HotSpot 嵌入 SST 主循环
- 不实现真正的 runtime execute-loop
- 不重构 `ISynapseRoute` 公共接口
- 不扩展 3D stack layer-aware 热控制策略
- 不进入完整 `synapse-semantic memory path` 的下一批大改

## Done Definition

当以下条件同时满足时，可以认为这一步完成：

1. `phase2_case_summary.route_kernel` 同时具有 `expected_active` 与 `actual_activation_observed` 两层语义
2. actual runtime activation 证据来自真实 SST stdout 的 `route3d` runtime marker，而不是纯推断
3. `full_3d` case 默认启用 HotSpot sidecar，且能在无 HotSpot 二进制时稳定落出 sidecar artifacts
4. Python 回归通过
5. `SnnDL` 编译通过
6. `TECH_PROGRESS.md` 已 append 记录
