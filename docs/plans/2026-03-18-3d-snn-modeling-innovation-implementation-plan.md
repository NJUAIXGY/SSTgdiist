# 3D SNN Modeling Innovation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在现有 `snn3dexp/` 与隔离的 SnnDL 3D 组件基础上，完成 `3D multicast semantics + real synapse-to-stack datapath + 3D-aware mapping/runtime + thermal proxy` 的第二阶段实现闭环。

**Architecture:** 继续坚持“Python 侧隔离 + SnnDL C++ 平行扩展”的原则。NoC 主线升级为真正的 `3D-native multicast semantics`，memory 主线从 `HBM-like shared stack graph` 升级为真实 synapse 业务流量通路，随后在 `snn3dexp/` 内补齐 3D-aware mapping/runtime 与 thermal proxy，并用统一的 case/baseline/analysis 套件做论文级实验闭环。

**Tech Stack:** Python 3、JSON、`unittest`、SST Python entry、SnnDL C++17、memHierarchy、ramulator2、`snn3dexp/`

---

**Execution rules**
- 所有 Python 侧实验和新 builder 继续限制在 `snn3dexp/` 下。
- 不覆写 legacy `SnnDL.MulticastRouter` 与 legacy `SynapseRouteSubsystem`。
- 继续优先新增隔离实现，而不是污染主线 2D 语义。
- 所有任务默认遵循 TDD：先写 failing test，再写最小实现，再跑 focused verify。
- git 提交步骤按仓库 policy 刻意省略。

### Task 1: 固化 3D volumetric multicast 语义契约

**Files:**
- Create: `snn3dexp/tests/test_multicast_3d_semantics.py`
- Modify: `snn3dexp/mesh3d_template/spec.py`
- Modify: `snn3dexp/mesh3d_template/runtime.py`
- Modify: `snn3dexp/noc/multicast_3d.py`
- Modify: `snn3dexp/platform/build_system.py`
- Modify: `snn3dexp/cases/full_3d/spec.json`
- Modify: `snn3dexp/cases/noc_only_3d/spec.json`

**Step 1: Write the failing test**
- 在 `test_multicast_3d_semantics.py` 锁定：
  - `multicast_block_shape = BxHxZ` 能进入 effective config
  - `4x4x2` 可定义 `2x2x2` volumetric block
  - `4x4x1` 时 3D block 自动退化为 `z=1`
  - `die_local_only=false` 时 contract 不再拒绝 cross-die block

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snn3dexp.tests.test_multicast_3d_semantics -v`
- Expected: FAIL，说明当前 spec/runtime/builder 仍只理解 2D block 语义。

**Step 3: Write minimal implementation**
- 为 spec/runtime 增加：
  - `multicast_block_dim_x`
  - `multicast_block_dim_y`
  - `multicast_block_dim_z`
  - `multicast_die_local_only`
- 在 `multicast_3d.py` 和 `build_system.py` 中把这组字段下沉到 router/route3d params。

**Step 4: Run test to verify it passes**
- Run: `python3 -m unittest snn3dexp.tests.test_multicast_3d_semantics -v`
- Expected: PASS

### Task 2: 升级 Route3D 编码与 block mapper 契约

**Files:**
- Create: `snn3dexp/tests/test_route3d_block_codec.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/Route3DNodeMapper.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`

**Step 1: Write the failing test**
- `test_route3d_block_codec.py` 锁定：
  - volumetric block id 可编码/解码 `(block_x, block_y, block_z)`
  - `4x4x2 + 2x2x2` 只有一个 full-volume block
  - `4x4x4 + 2x2x2` 的 block 编号随 `z` 维递增
  - 旧 `4x4x1` case 仍与 legacy 2D block 编号兼容

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snn3dexp.tests.test_route3d_block_codec -v`
- Expected: FAIL，说明当前 mapper 仍然只支持 layer-local 2D block。

**Step 3: Write minimal implementation**
- 在 `Route3DNodeMapper.h` 增加 volumetric block encode/decode helper。
- 在 `SynapseRouteSubsystem3D` 中保留 legacy 2D fallback，同时引入 3D block path。

**Step 4: Run focused verification**
- Run: `python3 -m unittest snn3dexp.tests.test_route3d_block_codec snn3dexp.tests.test_route3d_mapping -v`
- Run: `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
- Expected: PASS

### Task 3: 把 `SynapseRouteSubsystem3D` 升级为 3D-native fanout synthesis

**Files:**
- Create: `snn3dexp/tests/test_route3d_native_fanout_contract.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ISynapseRoute.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`

**Step 1: Write the failing test**
- `test_route3d_native_fanout_contract.py` 锁定：
  - `mesh_shape=4x4x2` 下 route3d 主路径可直接生成 block targets，而不是纯依赖 legacy route map
  - `multicast_enable=true` 时 route3d 输出包含 `block_z`
  - `4x4x1` 仍走兼容路径

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract -v`
- Expected: FAIL，说明当前 route synthesis 仍主要是 legacy 包装层。

**Step 3: Write minimal implementation**
- 在 `ISynapseRoute` 明确 3D target contract。
- 在 `SynapseRouteSubsystem3D` 中分离：
  - legacy fallback fanout path
  - 3D-native block-target synthesis path
- 在 `SnnWorkload.cc` 与 `SpikeCommSubsystem.cc` 中让 route3d path 可被真实 workload 触发。

**Step 4: Run focused verification**
- Run: `python3 -m unittest snn3dexp.tests.test_route3d_native_fanout_contract snn3dexp.tests.test_cpp_route_decoupling_contract -v`
- Run: `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
- Expected: PASS

### Task 4: 完成 `MulticastRouter3DNative` 的 3D volumetric 转发

**Files:**
- Create: `snn3dexp/tests/test_router3d_volumetric_forwarding_contract.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNativeConfig.h`

**Step 1: Write the failing test**
- `test_router3d_volumetric_forwarding_contract.py` 锁定：
  - `2x2x2` block 的 ingress 可以把 packet 向不同 `z` 层复制
  - non-ingress node 不会错误地把 cross-die tree 当成本地 2D tree
  - `vertical_route_order=zxy` 与 `zyx` 都可工作

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snn3dexp.tests.test_router3d_volumetric_forwarding_contract -v`
- Expected: FAIL，说明当前 router intra-stage 仍然是 die-local 2D tree。

**Step 3: Write minimal implementation**
- 在 router 内区分：
  - `INTER_Z`
  - `INTER_XY`
  - `INTRA_3D`
- 增加 vertical subtree replication 与 volumetric child selection。
- 保持 `4x4x1` case 退化为 legacy 兼容行为。

**Step 4: Run focused verification**
- Run: `python3 -m unittest snn3dexp.tests.test_router3d_volumetric_forwarding_contract snn3dexp.tests.test_router3d_component_contract -v`
- Run: `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
- Expected: PASS

### Task 5: 打通真实 synapse-to-stack 内存数据通路

**Files:**
- Create: `snn3dexp/tests/test_synapse_home_stack_runtime.py`
- Modify: `snn3dexp/memory/hbm_stack.py`
- Modify: `snn3dexp/platform/build_system.py`
- Modify: `snn3dexp/platform/sst_graph.py`
- Modify: `snn3dexp/platform/sst_driver.py`
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ISynapseRoute.h`

**Step 1: Write the failing test**
- `test_synapse_home_stack_runtime.py` 锁定：
  - `full_3d` runtime graph 能区分 `home_stack_id`
  - 至少一条真实 synapse memory edge 不再是 probe-only source
  - `memory_summary.json` 中出现 `real_synapse_sources > 0`

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snn3dexp.tests.test_synapse_home_stack_runtime -v`
- Expected: FAIL，说明当前 shared stack 图仍主要依赖 bench/probe traffic。

**Step 3: Write minimal implementation**
- 在 `hbm_stack.py` 中增加真实 synapse request source descriptors。
- 在 `platform/sst_graph.py` 中把这些 source 接到 shared stack bus。
- 在 workload / spike communication path 中透出 node->stack 的真实业务请求。

**Step 4: Run focused verification**
- Run: `python3 -m unittest snn3dexp.tests.test_synapse_home_stack_runtime snn3dexp.tests.test_cpp_traffic_mem_workload_contract -v`
- Run: `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
- Expected: PASS

### Task 6: 建立 route-memory 联合分析与真实 smoke case

**Files:**
- Create: `snn3dexp/tools/analyze_route_memory_joint.py`
- Create: `snn3dexp/tests/test_route_memory_joint_analysis.py`
- Modify: `snn3dexp/tools/analyze_ablation.py`
- Modify: `snn3dexp/tools/analyze_stack_nmc.py`
- Modify: `snn3dexp/cases/full_3d/spec.json`
- Modify: `snn3dexp/cases/memory_only_3d/spec.json`
- Modify: `snn3dexp/cases/noc_only_3d/spec.json`

**Step 1: Write the failing test**
- `test_route_memory_joint_analysis.py` 锁定：
  - 新分析脚本可输出 `vertical_hops_ratio`
  - 新分析脚本可输出 `remote_home_ratio`
  - 新分析脚本可输出 route-memory overlap 指标

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snn3dexp.tests.test_route_memory_joint_analysis -v`
- Expected: FAIL，说明当前 analysis 还没有联合指标。

**Step 3: Write minimal implementation**
- 新增 `analyze_route_memory_joint.py`
- 在 `analyze_ablation.py` 中汇总：
  - route 指标
  - stack 指标
  - route-memory 联合指标
- 让 `full_3d` 默认 case 支持真实 smoke runtime summary。

**Step 4: Run focused verification**
- Run: `python3 -m unittest snn3dexp.tests.test_route_memory_joint_analysis snn3dexp.tests.test_ablation_contract -v`
- Run: `python3 -m snn3dexp.tools.run_case full_3d --run-tag phase2_smoke --validate-only`
- Expected: PASS

### Task 7: 引入 3D-aware mapping/runtime

**Files:**
- Create: `snn3dexp/mapping/__init__.py`
- Create: `snn3dexp/mapping/policy.py`
- Create: `snn3dexp/tests/test_mapping_3d_policy.py`
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `snn3dexp/platform/build_system.py`
- Modify: `snn3dexp/cases/full_3d/spec.json`
- Create: `snn3dexp/cases/full_3d_mapping/case.json`
- Create: `snn3dexp/cases/full_3d_mapping/spec.json`

**Step 1: Write the failing test**
- `test_mapping_3d_policy.py` 锁定：
  - policy score 同时考虑 route cost、stack homing、vertical penalty
  - `z_blind` 与 `3d_aware` policy 能导出不同 placement summary
  - `full_3d_mapping` case 能被 `run_case.py` 正确解析

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snn3dexp.tests.test_mapping_3d_policy snn3dexp.tests.test_case_catalog -v`
- Expected: FAIL，说明 mapping 子系统和新 case 尚未建立。

**Step 3: Write minimal implementation**
- 新增 `mapping/policy.py`
- 在 `build_system.py` 中注入 mapping summary 到 effective config/platform summary
- 新建 `full_3d_mapping` case

**Step 4: Run focused verification**
- Run: `python3 -m unittest snn3dexp.tests.test_mapping_3d_policy snn3dexp.tests.test_case_catalog -v`
- Expected: PASS

### Task 8: 引入 thermal/physical proxy realism

**Files:**
- Create: `snn3dexp/thermal/__init__.py`
- Create: `snn3dexp/thermal/proxy.py`
- Create: `snn3dexp/tests/test_thermal_proxy.py`
- Modify: `snn3dexp/platform/build_system.py`
- Modify: `snn3dexp/tools/analyze_route_memory_joint.py`
- Create: `snn3dexp/cases/full_3d_thermal_guard/case.json`
- Create: `snn3dexp/cases/full_3d_thermal_guard/spec.json`

**Step 1: Write the failing test**
- `test_thermal_proxy.py` 锁定：
  - `thermal_hotspot_score` 会随 tier activity 升高
  - `vertical_link_pressure` 会随跨层 multicast 增加
  - `full_3d_thermal_guard` case 会把 thermal proxy 纳入 summary

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snn3dexp.tests.test_thermal_proxy -v`
- Expected: FAIL，说明 thermal proxy 尚未建立。

**Step 3: Write minimal implementation**
- 新增 `thermal/proxy.py`
- 在 `build_system.py` 与联合分析脚本中增加：
  - `thermal_hotspot_score`
  - `vertical_link_pressure`
  - `stack_hotspot_penalty`
- 新建 `full_3d_thermal_guard` case

**Step 4: Run focused verification**
- Run: `python3 -m unittest snn3dexp.tests.test_thermal_proxy -v`
- Expected: PASS

### Task 9: 固化论文级 baseline suite 与长时实验闭环

**Files:**
- Create: `snn3dexp/tests/test_phase2_baseline_suite.py`
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `snn3dexp/tools/analyze_ablation.py`
- Modify: `snn3dexp/cases/baseline_2d/spec.json`
- Modify: `snn3dexp/cases/memory_only_3d/spec.json`
- Modify: `snn3dexp/cases/noc_only_3d/spec.json`
- Modify: `snn3dexp/cases/full_3d/spec.json`
- Modify: `snn3dexp/cases/full_3d_mapping/spec.json`
- Modify: `snn3dexp/cases/full_3d_thermal_guard/spec.json`

**Step 1: Write the failing test**
- `test_phase2_baseline_suite.py` 锁定：
  - baseline suite 至少包含 6 个 phase-2 cases
  - `analyze_ablation.py` 能汇总 phase-2 联合指标
  - 每个 case 都有统一的 `platform_summary/effective_config/analysis summary`

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snn3dexp.tests.test_phase2_baseline_suite -v`
- Expected: FAIL，说明 phase-2 suite 尚未固定。

**Step 3: Write minimal implementation**
- 固化 phase-2 baseline 套件：
  - `baseline_2d`
  - `memory_only_3d`
  - `noc_only_3d`
  - `full_3d`
  - `full_3d_mapping`
  - `full_3d_thermal_guard`
- 让 `run_case.py` 支持统一 sweep/tag 运行入口。

**Step 4: Run focused verification**
- Run: `python3 -m unittest snn3dexp.tests.test_phase2_baseline_suite -v`
- Run: `python3 -m unittest discover -s "/home/xgy/remote/snn3dexp/tests" -v`
- Expected: PASS

### Task 10: 真实 SST smoke 与最小论文 artifact 固化

**Files:**
- Modify: `snn3dexp/tools/run_case.py`
- Modify: `snn3dexp/platform/sst_driver.py`
- Modify: `snn3dexp/tools/analyze_route_memory_joint.py`
- Modify: `snn3dexp/tools/analyze_ablation.py`
- Create: `snn3dexp/tests/test_phase2_smoke_manifest.py`

**Step 1: Write the failing test**
- `test_phase2_smoke_manifest.py` 锁定：
  - `full_3d`、`full_3d_mapping`、`full_3d_thermal_guard` 都能导出统一 smoke manifest
  - manifest 包含：
    - route metrics
    - memory metrics
    - joint metrics
    - thermal proxy metrics

**Step 2: Run test to verify it fails**
- Run: `python3 -m unittest snn3dexp.tests.test_phase2_smoke_manifest -v`
- Expected: FAIL，说明论文 artifact 口径尚未统一。

**Step 3: Write minimal implementation**
- 在 `sst_driver.py` 中统一 smoke output schema
- 在分析脚本中统一 JSON artifact schema
- 为 `phase2_smoke` 生成稳定输出目录约定

**Step 4: Run final verification**
- Run: `python3 -m unittest discover -s "/home/xgy/remote/snn3dexp/tests" -v`
- Run: `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
- Run: `python3 -m snn3dexp.tools.run_case full_3d --run-tag phase2_smoke`
- Run: `python3 -m snn3dexp.tools.run_case full_3d_mapping --run-tag phase2_smoke`
- Run: `python3 -m snn3dexp.tools.run_case full_3d_thermal_guard --run-tag phase2_smoke`
- Expected:
  - Python tests PASS
  - SnnDL compile PASS
  - 三个 phase-2 核心 case 至少完成 step-limited smoke，并产出统一 analysis artifact

## Suggested execution order

1. `Task 1-4`
- 先收敛 3D multicast semantics 与 route kernel

2. `Task 5-6`
- 再打通真实 synapse memory path 与联合分析

3. `Task 7-8`
- 然后引入 mapping/runtime 与 thermal proxy

4. `Task 9-10`
- 最后固定 baseline suite 与 paper artifact

## Phase exit criteria

- Phase-2 NoC closure：
  - 3D volumetric block + 3D-native fanout + router volumetric forwarding 全部通过 focused tests

- Phase-2 memory closure：
  - `full_3d` 在真实 synapse traffic 下完成 smoke
  - stack/channel stats 不再主要来自 probe-only traffic

- Phase-2 co-design closure：
  - 至少一个 `full_3d_mapping` 场景在 route + memory 联合指标上优于 `full_3d`

- Phase-2 realism closure：
  - `full_3d_thermal_guard` 能给出与 `full_3d` 不同的 thermal-aware 结果，并纳入统一 artifact

## Notes

- 这份计划刻意没有加入 git 操作步骤，遵守仓库 git policy。
- 若执行过程中发现 `ISynapseRoute` 需要更大范围 API 改动，必须先停下来重新校准接口边界。
- 若真实 synapse-to-stack datapath 需要新增专用 SST component，优先放在隔离的 `noc3d/` 或新隔离目录，不要回写 legacy 主线组件语义。
