# 3D Multicast Interface Kernel Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `ISynapseRoute -> SpikeCommSubsystem -> MulticastRouter3DNative` 升级为显式 3D multicast contract，并用真实 SST smoke 完成闭环验证。

**Architecture:** 本轮采用“接口增量升级 + 新 wire/bundle 版本 + 旧 decode 兼容”的方式推进。`ISynapseRoute` 新增 `multicastBlockD()`，`BlockTarget` 增加 `block_d`；SpikeKey/structured bundle 新增显式 3D 版本，由 `SpikeCommSubsystem` 发射，`MulticastRouter3DNative` 按 packet-level `block_d` 解码和转发；workload/self-check 只补 decode 兼容，不扩大到整条 SpikeTile 路线。

**Tech Stack:** C++17、SST/SnnDL、Python `unittest`、`snn3dexp` smoke harness

---

### Task 1: 先写接口级失败测试

**Files:**
- Modify: `snn3dexp/tests/test_cpp_route_decoupling_contract.py`
- Modify: `snn3dexp/tests/test_route3d_native_fanout_contract.py`
- Modify: `snn3dexp/tests/test_router3d_volumetric_forwarding_contract.py`
- Modify: `snn3dexp/tests/test_route3d_block_codec.py`

**Step 1: Write the failing tests**

- `ISynapseRoute` 必须暴露 `multicastBlockD()`
- `BlockTarget` 必须暴露 `block_d`
- `SpikeCommSubsystem` 必须调用 `synapse_route_->multicastBlockD()`
- codec round-trip 必须能保留显式 `block_d`
- router 必须读取 decode meta 中的 `block_d`，而不是单纯依赖本地 config

**Step 2: Run test to verify it fails**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_cpp_route_decoupling_contract snn3dexp.tests.test_route3d_native_fanout_contract snn3dexp.tests.test_router3d_volumetric_forwarding_contract snn3dexp.tests.test_route3d_block_codec -v`

Expected:
FAIL，显示 `multicastBlockD`、显式 `block_d` wire contract 还不存在。

### Task 2: 升级 `ISynapseRoute` 与 route subsystem

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ISynapseRoute.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`

**Step 1: Write minimal implementation**

- 给 `ISynapseRoute` 增加 `multicastBlockD()`
- 给 `BlockTarget` 增加 `block_d`
- legacy route 返回 `1`
- 3D route 返回有效 volumetric depth，并在 target synthesis 时回填 `block_d`

**Step 2: Run tests to verify partial green**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_cpp_route_decoupling_contract snn3dexp.tests.test_route3d_native_fanout_contract -v`

Expected:
新增接口契约测试通过，codec/router 相关测试仍未全绿。

### Task 3: 新增显式 3D SpikeKey wire contract

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeNocCodec.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`

**Step 1: Write minimal implementation**

- `SpikeNocCodec` 新增显式 3D route version
- `DecodedSpikeKeyMeta` 暴露 `block_w/block_h/block_d`
- `SpikeCommSubsystem` 在 `block_d>1` 时发射显式 3D SpikeKey
- router 依据 decode meta 的 `block_d` 做 volumetric decode/forward
- `TrafficWorkload` / `SnnWorkload` 接受新版本 decode

**Step 2: Run tests to verify green**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_cpp_route_decoupling_contract snn3dexp.tests.test_route3d_native_fanout_contract snn3dexp.tests.test_router3d_volumetric_forwarding_contract snn3dexp.tests.test_route3d_block_codec -v`

Expected:
全部通过。

### Task 4: 升级 structured inter-bundle 3D contract

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeInterBundleCodec.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.cc`

**Step 1: Write minimal implementation**

- structured bundle 新增显式 3D 版本
- prefix 显式携带 `block_w/block_h/block_d`
- entry meta 显式携带 `block_z`
- router 能按新 bundle 版本拆分并重建本地 SpikeKey payload

**Step 2: Run focused tests**

Run:
`cd /home/xgy/remote && python3 -m unittest snn3dexp.tests.test_route3d_block_codec snn3dexp.tests.test_router3d_volumetric_forwarding_contract -v`

Expected:
PASS。

### Task 5: 构建并运行真实 smoke 闭环

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Rebuild**

Run:
`cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`

Expected:
exit code 0

**Step 2: Run closed-loop experiment**

Run:
`cd /home/xgy/remote && python3 -m snn3dexp.tools.run_case full_3d_runtime_adaptive --run-tag task15_3d_multicast_interface_smoke --sst-smoke --stop-at 250ns`

Expected:
- `status=smoke_passed`
- 继续产出 `runtime_summary.json`
- 继续产出 `route_memory_joint_summary.json`

**Step 3: Record progress**

- 追加 `TECH_PROGRESS.md`
- 记录接口升级点、测试命令、真实 smoke 结果与后续 TODO
