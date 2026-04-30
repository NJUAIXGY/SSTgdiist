# PULSE-OSA Phase-1.5 Metadata Transaction Plane Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在严格 feature-flag 隔离下，为 `PE` 内部落地第一版 `pod-scoped metadata transaction plane`，把 today 的 `metadata frontier + owner-first + rowdescriptor join` 收敛成正式的 shared object transaction path，并用 `ready lease` 打开 `ready_join` 收益空间。

**Architecture:** 本阶段只改 `metadata plane`，不改 `core-private exact retire`，也不直接 actualize whole `value plane`。`MultiCorePE` 构造一个 `P-scope` metadata transaction provider，`SnnPESubComponent` 把它窄绑定到 `WeightMemorySubsystem`，后者在 `idx2 / rowidx / pre-band / rowdescriptor` 热路径上先走 `owner-launch / join-live / join-ready / private-fallback` 决策，再输出 `contracted value envelope` 供现有 exact demand 路径继续消费。

**Tech Stack:** C++17, SST element `SnnDL`, `WeightMemorySubsystem`, `MultiCorePE`, local-storage service plane, Python mesh runtime/config, `unittest`, `mainexp` A/B harness.

---

### Task 1: 锁定 runtime config 与 summary schema

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/build.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/config.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/runtime.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_pulse_config.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/compute_essential_summary_mesh.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/test_compute_essential_summary_mesh_pulse.py`

**Step 1: Write the failing runtime-config test**

新增 runtime config 测试，要求以下字段只在 `MESH_EXPERIMENTAL_ENABLE=1` 时导出：

- `MESH_PULSE_OSA_ENABLE=1`
- `MESH_PULSE_OSA_METADATA_TXN_ENABLE=1`
- `MESH_PULSE_OSA_METADATA_READY_LEASE_ENABLE=1`
- `MESH_PULSE_OSA_METADATA_READY_LEASE_TTL=64`
- `MESH_PULSE_OSA_METADATA_OBJECT_MASK=idx2,rowidx,preband,rowdescriptor`

**Step 2: Run test to verify it fails**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  sst_dram_si.mesh_template.test_runtime_pulse_config.RuntimePulseConfigTests.test_pulse_osa_metadata_txn_env_is_exported_when_experimental_enable_is_on -v
```

Expected: FAIL because the new fields are not exported yet.

**Step 3: Write minimal runtime/config implementation**

把新字段接进 `build.py -> config.py -> runtime.py`，并保持：

- 默认关闭
- 非 experimental 模式下完全不出现

**Step 4: Write the failing summary test**

为 summary 工具增加新字段断言：

- `pulse_metadata_txn_export_total`
- `pulse_metadata_txn_owner_launch_total`
- `pulse_metadata_txn_join_live_total`
- `pulse_metadata_txn_join_ready_total`
- `pulse_metadata_txn_late_join_total`
- `pulse_metadata_txn_ready_lease_hit_total`
- `pulse_metadata_txn_ready_lease_expired_total`
- `pulse_metadata_txn_envelope_size_sum_total`

以及派生字段：

- `pulse_metadata_txn_ready_join_share`
- `pulse_metadata_txn_late_join_share`
- `pulse_metadata_txn_owner_to_elide_ratio`

**Step 5: Run summary test to verify it fails**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  sst_dram_si.tools.test_compute_essential_summary_mesh_pulse.ComputeEssentialSummaryMeshPulseCLITest.test_pulse_osa_metadata_txn_metrics_are_aggregated_and_derived -v
```

Expected: FAIL because the summary tool does not know these fields yet.

**Step 6: Write minimal summary implementation**

在 `compute_essential_summary_mesh.py` 中增加 aggregation/derivation。

**Step 7: Run the tests to verify GREEN**

Run:

```bash
cd "/home/xgy/remote" && python3 -m unittest \
  sst_dram_si.mesh_template.test_runtime_pulse_config \
  sst_dram_si.tools.test_compute_essential_summary_mesh_pulse -v
```

Expected: PASS.

**Step 8: Checkpoint**

本仓库禁止未获批准的 git 写操作，本计划不包含 commit。

### Task 2: 定义 `P-scope` metadata transaction plane 与 provider 契约

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api/IPodMetadataTxnPlaneProvider.h`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/PodMetadataTxnPlane.h`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/PodMetadataTxnPlane.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_local_storage_hierarchy.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.am`

**Step 1: Write the failing C++ test**

在 `test_local_storage_hierarchy.cc` 新增测试，覆盖：

- transaction insert
- single owner launch
- live join
- ready transition
- ready-lease hit
- lease expire

最小断言应包括：

- 同一 `object key` 同窗口只能形成一个 active owner transaction
- `join_live_total` 与 `join_ready_total` 能被分开计数
- `lease_hit_total` 在 TTL 内非零

**Step 2: Run test to verify it fails**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . tests/test_local_storage_hierarchy.cc -o /tmp/test_local_storage_hierarchy
```

Expected: FAIL because the plane and provider do not exist.

**Step 3: Write minimal implementation**

实现：

- `PodMetadataTxnPlane::ObjectKey`
- `PodMetadataTxnPlane::TxnState`
- `PodMetadataTxnPlane::QueryResult`
- `launchOrJoin(...)`
- `markReady(...)`
- `tickLease(...)`
- `release(...)`
- `snapshotStats()`

第一版只支持：

- `idx2`
- `rowidx`
- `preband`
- `rowdescriptor`

**Step 4: Run test to verify it passes**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . \
  tests/test_local_storage_hierarchy.cc \
  services/local_storage/PodMetadataTxnPlane.cc \
  -o /tmp/test_local_storage_hierarchy && \
/tmp/test_local_storage_hierarchy
```

Expected: PASS.

### Task 3: 在 MultiCorePE 构造 `P-scope` metadata transaction provider

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/multicore/MultiCorePEConfig.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/multicore/MultiCorePEConfig.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_includes.cc`

**Step 1: Write the failing include/config test**

在 `test_includes.cc` 引入：

```cpp
#include "api/IPodMetadataTxnPlaneProvider.h"
#include "services/local_storage/PodMetadataTxnPlane.h"
```

并在 `MultiCorePE` 侧预期新增：

```cpp
public IPodMetadataTxnPlaneProvider
```

**Step 2: Run test to verify it fails**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . -c tests/test_includes.cc -o /tmp/test_includes.o
```

Expected: FAIL because the new headers and inheritance are missing.

**Step 3: Write minimal implementation**

- 增加配置字段：
  - `pulse_osa_enable`
  - `pulse_osa_metadata_txn_enable`
  - `pulse_osa_metadata_ready_lease_enable`
  - `pulse_osa_metadata_ready_lease_ttl`
  - `pulse_osa_metadata_object_mask`
- `MultiCorePE` 只在显式开关打开时构造 `PodMetadataTxnPlane`
- 以 pod 为粒度持有一组 plane，而不是 whole-PE single global table
- 通过 `podMetadataTxnPlane(pod_id)` 暴露窄 provider

**Step 4: Run test to verify it passes**

Run the same compile command again and expect PASS.

### Task 4: 在 `SnnPESubComponent` / `WMS` 间插入 metadata shim

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`

**Step 1: Write the failing behavior test**

在 `test_local_storage_hierarchy.cc` 或新增轻量 C++ test 中模拟两个 consumer 对同一 metadata object 的访问，要求：

- 第一个 consumer 得到 `owner_launch`
- 第二个在 owner active 时得到 `join_live`
- owner ready 后、lease 内到达的第三个 consumer 得到 `join_ready`

**Step 2: Run test to verify it fails**

使用同类 `g++` 单文件编译命令，预期 FAIL。

**Step 3: Write minimal implementation**

- `SnnPESubComponent` 在创建 `WeightMemorySubsystem` 后，通过 provider 绑定 `PodMetadataTxnPlane`
- `WeightMemorySubsystem` 新增：
  - `bindMetadataTxnPlane(...)`
  - `queryMetadataTxnLaunchOrJoin(...)`
  - `noteMetadataTxnReady(...)`
- 第一版只接在：
  - `prepareGcssVlfIssueQueue_()`
  - `lookupGcssPreBaseLen_()` 之后
  - `rowdescriptor owner-first` 现有 seam

**Step 4: Preserve fallback**

如果 plane 关闭、pod 不存在、对象类型未启用、table 满、lease 过期，都必须：

- 显式记统计
- 并回到 today private path

**Step 5: Run tests to verify GREEN**

重新运行 Task 2/4 的轻量 C++ 测试，预期 PASS。

### Task 5: 落 `ready lease` 与 `contracted value envelope`

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/PodMetadataTxnPlane.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/PodMetadataTxnPlane.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`

**Step 1: Write the failing lease/envelope test**

新增测试要求：

- owner ready 后，lease 窗口内新 consumer 命中 `join_ready`
- 返回的 envelope 至少包含：
  - `candidate_kind`
  - `candidate_begin`
  - `candidate_count`
  - `owner_txn_id`

**Step 2: Run test to verify it fails**

使用同类 `g++` compile+run，预期 FAIL。

**Step 3: Write minimal implementation**

- 在 `TxnRecord` 中增加：
  - `ready_cycle`
  - `lease_expire_cycle`
  - `ready_lease_budget`
- 定义 `ContractedValueEnvelope`
- `WeightMemorySubsystem` 从 transaction plane 拿 envelope，但本阶段只做：
  - bounded candidate narrowing
  - 不直接替代 final exact value validation

**Step 4: Run test to verify it passes**

重复 Step 2 命令，预期 PASS。

### Task 6: 暴露新的 pulse 统计

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`

**Step 1: Add counters**

新增并导出：

- `pulse_metadata_txn_export_total`
- `pulse_metadata_txn_owner_launch_total`
- `pulse_metadata_txn_join_live_total`
- `pulse_metadata_txn_join_ready_total`
- `pulse_metadata_txn_late_join_total`
- `pulse_metadata_txn_reject_total`
- `pulse_metadata_txn_ready_lease_hit_total`
- `pulse_metadata_txn_ready_lease_expired_total`
- `pulse_metadata_txn_envelope_size_sum_total`
- `pulse_metadata_txn_table_occupancy_peak`
- `pulse_metadata_txn_ready_lease_occupancy_peak`
- `pulse_metadata_txn_private_fallback_due_to_pressure_total`

**Step 2: Compile-check**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4
```

Expected: exit `0`.

**Step 3: Install**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make install
```

Expected: exit `0`.

### Task 7: 建立闭环 `mainexp` 实验

**Files:**
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-30_pulse_osa_metadata_txn_ab_v1/cases.json`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-30_pulse_osa_metadata_txn_ab_v1/run_case.sh`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-30_pulse_osa_metadata_txn_ab_v1/make_snapshot.py`
- Create: `/home/xgy/remote/mainexp/experiments/2026-03-30_pulse_osa_metadata_txn_ab_v1/test_make_snapshot.py`

**Step 1: Baseline case**

使用：

- `pulse_shared_line_actual_mfb_gather_preband_dedup_off`

保持所有新开关关闭。

**Step 2: Candidate case**

开启：

- `MESH_PULSE_OSA_ENABLE=1`
- `MESH_PULSE_OSA_METADATA_TXN_ENABLE=1`
- `MESH_PULSE_OSA_METADATA_READY_LEASE_ENABLE=1`

并固定：

- `top32`
- `observe_band128`
- `preband_band96`
- `budget6`

**Step 3: Fresh A/B**

Run:

```bash
cd "/home/xgy/remote/mainexp/experiments/2026-03-30_pulse_osa_metadata_txn_ab_v1" && ./run_case.sh <baseline_case>
cd "/home/xgy/remote/mainexp/experiments/2026-03-30_pulse_osa_metadata_txn_ab_v1" && ./run_case.sh <candidate_case>
```

Expected: both runs finish with `validation fail=0 warn=0 strict=0`.

**Step 4: Generate compare snapshot**

输出必须包含：

- cycle cost
- memory requests
- txn funnel metrics
- `ready_join_share`
- `late_join_share`
- `owner_to_elide_ratio`

### Task 8: 判定 gate 并记录进度

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Append-only progress entry**

追加：

- 设计目标
- 实际改动文件
- 编译与实验命令
- fresh run 路径
- funnel 结果
- 是否进入下一阶段

**Step 2: State the go/no-go rule**

只有当以下条件成立时，才进入下一阶段 `Phase-V1 shared value plane shadow`：

- `pulse_metadata_txn_join_ready_total > 0`
- `late_join_share` 显著低于当前基线
- `owner_to_elide_ratio` 高于 today owner-first patch
- correctness 不恶化

否则：

- 停在 metadata plane
- 继续调生命周期与 lease，而不是贸然进入 value plane

---

Plan complete and saved to `/home/xgy/remote/docs/plans/2026-03-30-pulse-osa-phase15-metadata-transaction-plane-implementation-plan.md`.

本仓库当前处于并行开发约束下，后续执行建议直接在当前工作区按任务顺序推进，不做任何 git 写操作。
