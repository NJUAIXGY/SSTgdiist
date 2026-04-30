# PULSE-OSA Shared Weight Owner Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `PULSE-OSA` 落地第一实现切片，在严格 feature-flag 隔离下，把 `weight_idx_store / weight_value_store` 从 “PerCore WMS 私有观测器” 升级为 “PerPe shared weight object plane + runtime owner provider”。

**Architecture:** 本阶段只实现 `shared weight object plane` 的窄骨架，不改变 `core-private compute / commit`，也不提前侵入 retire contract。`MultiCorePE` 在显式开关打开时构造一个 `PerPe` 级共享 weight owner，`SnnPESubComponent` 通过新的窄 provider 绑定给 `WeightMemorySubsystem`，后者在开启时改为引用 shared `BankedSramModel / VirtualSramLayout`，否则保持现状。

**Tech Stack:** C++17, SST element `SnnDL`, `BankedSramModel`, `VirtualSramLayout`, local-storage service plane, narrow provider interfaces, lightweight unit tests.

---

### Task 1: 定义 shared weight object plane 与 provider 契约

**Files:**
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/IPeWeightObjectPlaneProvider.h`
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/PeWeightObjectPlane.h`
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/local_storage/PeWeightObjectPlane.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_local_storage_hierarchy.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.am`

**Step 1: Write the failing test**

在 `tests/test_local_storage_hierarchy.cc` 新增纯 C++ 测试，覆盖：

```cpp
static void test_pe_weight_object_plane_tracks_shared_idx_and_l0_pressure() {
    SST::SnnDL::PeWeightObjectPlane::Config cfg{};
    cfg.enable = true;
    cfg.owner_scope_enable = true;
    cfg.idx_enable = true;
    cfg.l0_enable = true;
    cfg.idx_capacity_bytes = 1024;
    cfg.l0_capacity_bytes = 2048;
    cfg.idx_banks = 2;
    cfg.l0_banks = 2;
    cfg.ports_per_bank = 1;
    cfg.bank_interleave_bytes = 4;
    cfg.t_read_cycles = 1;
    cfg.t_write_cycles = 1;

    SST::SnnDL::PeWeightObjectPlane plane(cfg);
    assert(plane.enabled());
    assert(plane.ownerScopeEnabled());

    plane.noteIdxRead(10, 0x100000000ull, 4);
    plane.noteIdxRead(10, 0x100000004ull, 4);
    plane.noteL0Write(10, 1234ull);
    plane.noteResidentIdxBytes(128);
    plane.noteResidentL0Bytes(256);
    plane.onClockTick(10);

    const auto stats = plane.snapshotStats();
    assert(stats.idx_sram.reads_total == 2u);
    assert(stats.l0_sram.writes_total == 1u);
    assert(stats.idx_sram.resident_bytes_last == 128u);
    assert(stats.l0_sram.resident_bytes_last == 256u);
}
```

并追加一个 provider 契约占位断言：

```cpp
SST::SnnDL::IPeWeightObjectPlaneProvider* provider = nullptr;
(void)provider;
```

**Step 2: Run test to verify it fails**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . tests/test_local_storage_hierarchy.cc services/local_storage/LocalStorageHierarchyController.cc -o /tmp/test_local_storage_hierarchy
```

Expected: FAIL，报 `PeWeightObjectPlane` / `IPeWeightObjectPlaneProvider` 未定义。

**Step 3: Write minimal implementation**

实现一个独立的 `PeWeightObjectPlane`：

- 持有一份 `VirtualSramLayout`
- 持有一份共享 `BankedSramModel idx`
- 持有一份共享 `BankedSramModel l0`
- 提供 `noteIdxRead/noteL0Read/noteL0Write/noteResident*Bytes/onClockTick/snapshotStats`
- 保持默认关闭；只有 `enable && owner_scope_enable` 时才真正生效

新增 provider：

```cpp
class IPeWeightObjectPlaneProvider {
public:
    virtual ~IPeWeightObjectPlaneProvider() = default;
    virtual PeWeightObjectPlane* peWeightObjectPlane() = 0;
};
```

**Step 4: Run test to verify it passes**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . \
  tests/test_local_storage_hierarchy.cc \
  services/local_storage/LocalStorageHierarchyController.cc \
  services/local_storage/PeWeightObjectPlane.cc \
  services/memory/sram_sim/model/BankedSramModel.cc \
  -o /tmp/test_local_storage_hierarchy && \
/tmp/test_local_storage_hierarchy
```

Expected: PASS。

**Step 5: Checkpoint**

本仓库禁止未获批准的 git 写操作，本计划不包含 commit。

### Task 2: 在 MultiCorePE 构造并暴露 PE-shared weight owner

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/multicore/MultiCorePEConfig.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/multicore/MultiCorePEConfig.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_includes.cc`

**Step 1: Write the failing test**

在 `tests/test_includes.cc` 加入：

```cpp
#include "api/IPeWeightObjectPlaneProvider.h"
#include "services/local_storage/PeWeightObjectPlane.h"
```

并在 `MultiCorePE.h` 侧预期新增：

```cpp
public IPeWeightObjectPlaneProvider
```

**Step 2: Run test to verify it fails**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . -c tests/test_includes.cc -o /tmp/test_includes.o
```

Expected: FAIL，报缺少新头文件。

**Step 3: Write minimal implementation**

- 新增参数：
  - `pulse_osa_enable`
  - `pulse_osa_shared_weight_owner_enable`
- `MultiCorePE` 只在：
  - `workload_impl=snn`
  - `local_storage_enable=1`
  - `pulse_osa_enable=1`
  - `pulse_osa_shared_weight_owner_enable=1`
  时构造 `PeWeightObjectPlane`
- 配置来源优先复用 `ls_weight_idx_* / ls_weight_value_*` 与 legacy `weight_*_sram_*`
- 通过 `peWeightObjectPlane()` 暴露窄接口

**Step 4: Run test to verify it passes**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . -c tests/test_includes.cc -o /tmp/test_includes.o
```

Expected: PASS。

**Step 5: Checkpoint**

仍然不执行 git 写操作。

### Task 3: 让 WeightMemorySubsystem 可选绑定 shared owner

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`

**Step 1: Write the failing test**

在 `tests/test_local_storage_hierarchy.cc` 再追加一个轻量行为测试，验证 shared owner 的 stall / stats 聚合是跨两个逻辑客户端共享的：

```cpp
static void test_pe_weight_object_plane_aggregates_multiple_clients() {
    SST::SnnDL::PeWeightObjectPlane::Config cfg{};
    cfg.enable = true;
    cfg.owner_scope_enable = true;
    cfg.idx_enable = true;
    cfg.idx_banks = 1;
    cfg.ports_per_bank = 1;

    SST::SnnDL::PeWeightObjectPlane plane(cfg);
    plane.noteIdxRead(20, 0x100000000ull, 4);
    plane.noteIdxRead(20, 0x100000008ull, 4);
    plane.onClockTick(20);

    const auto stats = plane.snapshotStats();
    assert(stats.idx_sram.reads_total == 2u);
    assert(stats.idx_sram.bank_conflict_events_total >= 1u);
}
```

**Step 2: Run test to verify it fails if aggregation is broken**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . \
  tests/test_local_storage_hierarchy.cc \
  services/local_storage/LocalStorageHierarchyController.cc \
  services/local_storage/PeWeightObjectPlane.cc \
  services/memory/sram_sim/model/BankedSramModel.cc \
  -o /tmp/test_local_storage_hierarchy && \
/tmp/test_local_storage_hierarchy
```

Expected: 如果 plane 只是空壳，测试 FAIL。

**Step 3: Write minimal implementation**

- `WeightMemorySubsystem` 新增可选绑定：

```cpp
void bindSharedWeightObjectPlane(PeWeightObjectPlane* plane);
```

- 当 plane 有效时：
  - `sram_layout_` 改为引用 shared layout
  - `idx_sram_model_ / l0_sram_model_` 的访问走 shared plane helper
  - `sramObservabilityStats()` 返回 shared plane 当前 stats
- 当 plane 无效时：
  - 保持原 per-core 私有模型
- `SnnPESubComponent` 在构造/装配 `WeightMemorySubsystem` 后，通过 `IPeWeightObjectPlaneProvider` 把 plane 透传进去

**Step 4: Run tests to verify GREEN**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . \
  tests/test_local_storage_hierarchy.cc \
  services/local_storage/LocalStorageHierarchyController.cc \
  services/local_storage/PeWeightObjectPlane.cc \
  services/memory/sram_sim/model/BankedSramModel.cc \
  -o /tmp/test_local_storage_hierarchy && \
/tmp/test_local_storage_hierarchy
```

Expected: PASS。

**Step 5: Checkpoint**

仍然不执行 git 写操作。

### Task 4: 编译回归、最小闭环验证与进展记录

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Build the affected unit tests**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . \
  tests/test_local_storage_hierarchy.cc \
  services/local_storage/LocalStorageHierarchyController.cc \
  services/local_storage/PeWeightObjectPlane.cc \
  services/memory/sram_sim/model/BankedSramModel.cc \
  -o /tmp/test_local_storage_hierarchy && \
/tmp/test_local_storage_hierarchy
```

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . -c tests/test_includes.cc -o /tmp/test_includes.o
```

**Step 2: Compile-check changed production files**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . -c services/local_storage/PeWeightObjectPlane.cc -o /tmp/PeWeightObjectPlane.o
```

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -I . -c services/synapse/weights/WeightMemorySubsystem.cc -o /tmp/WeightMemorySubsystem.o
```

Expected: 全部 PASS；若 `WeightMemorySubsystem.cc` 因 SST 头依赖较重无法单编，则至少完成 `make -j4` 的目标编译验证并记录限制。

**Step 3: Append TECH_PROGRESS.md**

只允许在文件尾部追加：

- 变更内容
- 开关与运行方式
- 验证命令
- 当前结果与下一阶段 TODO

**Step 4: Checkpoint**

本阶段完成后，可继续进入下一切片：
- shared metadata owner
- owner-scoped residency / fill / last-consumer drain
- exact commit 前的 ready fanout / scoreboard contract
