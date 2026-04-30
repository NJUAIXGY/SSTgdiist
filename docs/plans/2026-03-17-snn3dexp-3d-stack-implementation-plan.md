# snn3dexp 3D Stack Prototype Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在完全隔离的 `snn3dexp/` 预研树中，一次性完成 `HBM-like NMC + 3D native MulticastRouter` 的最小可运行原型，包括 Python 实验 harness、3D NoC builder、HBM-like shared stack builder、隔离的 SnnDL 3D Router / RouteService、四组 canonical ablation cases 与验证闭环。

**Architecture:** `snn3dexp/` 继续作为唯一 Python 侧实验入口，自己维护 `shape/spec/runtime/build/cases/tools/tests`，所有输出都限制在 `snn3dexp/` 下。SnnDL C++ 侧采用平行实现而不是直接改主线：新增 `components/noc3d/MulticastRouter3DNative` 与 `services/synapse/route3d/SynapseRouteSubsystem3D`，由 `snn3dexp/platform/build_system.py` 显式选择。memory path 继续走 memHierarchy，但 builder 与 homing policy 完全留在 `snn3dexp/memory/`。

**Tech Stack:** Python 3、JSON、`unittest`、SST Python entry、SnnDL C++17、memHierarchy、ramulator2 HBM2

---

**Current checkpoint**
- 已完成 `snn3dexp/` 隔离骨架
- 已完成 `shape3d.py`
- 已完成最小 `mesh3d_template/spec/runtime/build`
- 已完成基础单元测试：
  - `snn3dexp.tests.test_paths`
  - `snn3dexp.tests.test_shape3d`
  - `snn3dexp.tests.test_mesh3d_template_spec`
  - `snn3dexp.tests.test_mesh3d_template_contract`

**Execution rules**
- 不修改 `sst_dram_si/mesh_template/` 和 `snndl_system/` 主线 Python builder
- 不覆写现有 `SnnDL.MulticastRouter` / `SynapseRouteSubsystem`
- git 提交步骤刻意省略，遵守仓库 git policy

### Task 1: 完成 `snn3dexp` case catalog 与 runner 契约

**Files:**
- Create: `snn3dexp/cases/baseline_2d/case.json`
- Create: `snn3dexp/cases/baseline_2d/spec.json`
- Create: `snn3dexp/cases/memory_only_3d/case.json`
- Create: `snn3dexp/cases/memory_only_3d/spec.json`
- Create: `snn3dexp/cases/noc_only_3d/case.json`
- Create: `snn3dexp/cases/noc_only_3d/spec.json`
- Create: `snn3dexp/cases/full_3d/case.json`
- Create: `snn3dexp/cases/full_3d/spec.json`
- Create: `snn3dexp/tools/run_case.py`
- Create: `snn3dexp/tests/test_run_case.py`
- Create: `snn3dexp/tests/test_case_catalog.py`
- Modify: `snn3dexp/paths.py`
- Modify: `snn3dexp/entry.py`

**Step 1: Write the failing tests**
- `test_run_case.py` 锁定：
  - `resolve_case_context()` 只能解析 `snn3dexp/cases/<case_id>/`
  - `run_root/stats_root/analysis_root` 必须都落在 `snn3dexp/`
  - `--dry-run` 输出最终命令和关键 env
  - `--validate-only` 只校验 spec，不启动 SST
- `test_case_catalog.py` 锁定四个 canonical case 都存在，并且：
  - `baseline_2d` => `4x4x1 + 2D router + legacy memory`
  - `memory_only_3d` => `4x4x2 + 2D router semantics + hbm_like`
  - `noc_only_3d` => `4x4x2 + 3D router + legacy memory`
  - `full_3d` => `4x4x2 + 3D router + hbm_like`

**Step 2: Run tests to verify they fail**
- Run: `python3 -m unittest snn3dexp.tests.test_run_case snn3dexp.tests.test_case_catalog`
- Expected: FAIL，提示 `run_case.py`、case catalog 或 case spec 尚未建立。

**Step 3: Write minimal implementation**
- 新建 `tools/run_case.py`
- 支持：
  - `--dry-run`
  - `--validate-only`
  - `--print-effective-config`
- `entry.py` 接受 `--spec <path>` 并从文件加载 `spec.json`
- 四个 canonical case 先提供 step-limited smoke 级参数，不追求大规模运行

**Step 4: Run tests to verify they pass**
- Run: `python3 -m unittest snn3dexp.tests.test_run_case snn3dexp.tests.test_case_catalog`
- Expected: PASS

### Task 2: 完成 Python 侧 3D NoC builder

**Files:**
- Create: `snn3dexp/noc/__init__.py`
- Create: `snn3dexp/noc/multicast_3d.py`
- Create: `snn3dexp/tests/test_noc_multicast_3d.py`
- Modify: `snn3dexp/mesh3d_template/build.py`
- Modify: `snn3dexp/mesh3d_template/runtime.py`

**Step 1: Write the failing tests**
- `test_noc_multicast_3d.py` 锁定：
  - `4x4x1` 时 link count 与二维 mesh 一致
  - `4x4x2` 时增加 `up/down` 垂直链路
  - builder 对 `shape.total_nodes` 与 router 数量进行一致性检查
  - `vertical_route_order=zxy` 进入 effective config

**Step 2: Run tests to verify they fail**
- Run: `python3 -m unittest snn3dexp.tests.test_noc_multicast_3d`
- Expected: FAIL，说明 `snn3dexp/noc/` 尚未存在或 builder 还不会连 3D 链路。

**Step 3: Write minimal implementation**
- 在 `multicast_3d.py` 中实现：
  - `build_routers_3d(...)`
  - `connect_router_links_3d(...)`
  - `connect_nics_to_routers(...)`
- 先用 fake SST / pure-Python contract 建立 builder 级能力
- 组件类型先显式写成未来目标名：
  - `SnnDL.MulticastRouter3DNative`

**Step 4: Run tests to verify they pass**
- Run: `python3 -m unittest snn3dexp.tests.test_noc_multicast_3d`
- Expected: PASS

### Task 3: 完成 Python 侧 HBM-like shared stack builder

**Files:**
- Create: `snn3dexp/memory/__init__.py`
- Create: `snn3dexp/memory/hbm_stack.py`
- Create: `snn3dexp/tests/test_hbm_stack.py`
- Modify: `snn3dexp/mesh3d_template/spec.py`
- Modify: `snn3dexp/mesh3d_template/runtime.py`
- Modify: `snn3dexp/mesh3d_template/build.py`

**Step 1: Write the failing tests**
- `test_hbm_stack.py` 锁定：
  - `xy_quadrant` home policy
  - `4 stacks + 4 channels + 256B interleave`
  - `z=1` 比 `z=0` 多 `vertical_mem_hop_latency`
  - 对 `2x3x2` 这类非正方形 mesh 也能给出合法 home stack

**Step 2: Run tests to verify they fail**
- Run: `python3 -m unittest snn3dexp.tests.test_hbm_stack`
- Expected: FAIL，说明 shared stack builder 尚不存在。

**Step 3: Write minimal implementation**
- `hbm_stack.py` 至少提供：
  - `build_stack_descriptors(...)`
  - `home_stack_for_node(...)`
  - `attachment_latency_for_node(...)`
- `effective_config` 输出：
  - `num_stacks`
  - `channels_per_stack`
  - `channel_interleave_bytes`
  - `stack_home_policy`
  - `vertical_mem_hop_latency`

**Step 4: Run tests to verify they pass**
- Run: `python3 -m unittest snn3dexp.tests.test_hbm_stack`
- Expected: PASS

### Task 4: 完成 Python 侧平台装配与 SST entry

**Files:**
- Create: `snn3dexp/platform/__init__.py`
- Create: `snn3dexp/platform/build_system.py`
- Create: `snn3dexp/tests/test_platform_builder.py`
- Modify: `snn3dexp/entry.py`
- Modify: `snn3dexp/tools/run_case.py`

**Step 1: Write the failing tests**
- `test_platform_builder.py` 锁定：
  - `build_system(...)` 会同时返回 `platform/noc/memory/paths` 摘要
  - `full_3d` case 里 router component type 为 `SnnDL.MulticastRouter3DNative`
  - memory summary 指向 `hbm_like shared stack`
  - `baseline_2d` case 不会误启用 3D-only component type

**Step 2: Run tests to verify they fail**
- Run: `python3 -m unittest snn3dexp.tests.test_platform_builder`
- Expected: FAIL，说明顶层装配层还未建立。

**Step 3: Write minimal implementation**
- `platform/build_system.py` 负责：
  - 调用 `mesh3d_template.resolve_runtime_config`
  - 调用 `noc/memory` builder
  - 组装最终 SST object graph 或其 pure-Python 摘要
- `entry.py` 同时支持：
  - `--validate-only`
  - `--print-effective-config`
  - `--spec <path>`
- `tools/run_case.py` 默认走 `entry.py`

**Step 4: Run tests to verify they pass**
- Run: `python3 -m unittest snn3dexp.tests.test_platform_builder`
- Run: `python3 -m snn3dexp.entry --print-effective-config`
- Expected: PASS，且 entry 打印的不是临时 bootstrap dict，而是平台摘要。

### Task 5: 实现隔离的 SnnDL `MulticastRouter3DNative`

**Files:**
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.h`
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNative.cc`
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc3d/MulticastRouter3DNativeConfig.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.am`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/configure.m4`
- Modify: `snn3dexp/noc/multicast_3d.py`
- Create: `snn3dexp/tests/test_router3d_component_contract.py`

**Step 1: Write the failing tests**
- `test_router3d_component_contract.py` 锁定：
  - builder 必须发出 `SnnDL.MulticastRouter3DNative`
  - params 包含 `mesh_shape`, `vertical_route_order`, `up/down` 端口契约
- 编译验证前先允许 pure-Python contract 失败

**Step 2: Run tests to verify they fail**
- Run: `python3 -m unittest snn3dexp.tests.test_router3d_component_contract`
- Expected: FAIL，说明 C++ component name / params 尚未接通。

**Step 3: Write minimal implementation**
- 以当前 `MulticastRouter` 为模板，复制到 `noc3d/`
- 新增：
  - `mesh_shape = WxHxZ`
  - `up/down` 端口
  - `z-first` `INTER_Z -> INTER_XY -> INTRA`
- 保持：
  - payload format 不变
  - block multicast 仍为 die-local 2D

**Step 4: Run focused verification**
- Run: `python3 -m unittest snn3dexp.tests.test_router3d_component_contract`
- Run: `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`
- Expected: PASS

### Task 6: 实现隔离的 `SynapseRouteSubsystem3D`

**Files:**
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.h`
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/SynapseRouteSubsystem3D.cc`
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route3d/Route3DNodeMapper.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.am`
- Modify: `snn3dexp/platform/build_system.py`
- Create: `snn3dexp/tests/test_route3d_mapping.py`

**Step 1: Write the failing tests**
- `test_route3d_mapping.py` 锁定：
  - `mesh_shape=4x4x2` 时 `node_id <-> (x,y,z)` 映射一致
  - `ingress_node` 采用与 `shape3d.py` 相同的映射规则
  - 对 `4x4x1` 仍兼容 legacy z=0 only 行为

**Step 2: Run tests to verify they fail**
- Run: `python3 -m unittest snn3dexp.tests.test_route3d_mapping`
- Expected: FAIL，说明 route3d 子系统尚不存在。

**Step 3: Write minimal implementation**
- `SynapseRouteSubsystem3D` 只负责：
  - 根据 `(x,y,z)` 选择 `ingress_node`
  - 保持现有 `SpikeKey / SpikeTileKey / InterBundle` 语义不变
- 不做：
  - 3D volumetric block 编码
  - packet format 扩展

**Step 4: Run focused verification**
- Run: `python3 -m unittest snn3dexp.tests.test_route3d_mapping`
- Run: `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`
- Expected: PASS

### Task 7: 打通四组 canonical ablation cases

**Files:**
- Modify: `snn3dexp/cases/baseline_2d/spec.json`
- Modify: `snn3dexp/cases/memory_only_3d/spec.json`
- Modify: `snn3dexp/cases/noc_only_3d/spec.json`
- Modify: `snn3dexp/cases/full_3d/spec.json`
- Create: `snn3dexp/tools/analyze_ablation.py`
- Create: `snn3dexp/tests/test_ablation_contract.py`

**Step 1: Write the failing tests**
- `test_ablation_contract.py` 锁定：
  - 四个 case 的差异仅来自预期维度
  - `baseline_2d` 不应带 `3D router` 或 `hbm_like`
  - `memory_only_3d` 只开 memory 侧 3D
  - `noc_only_3d` 只开 NoC 侧 3D
  - `full_3d` 两侧都开

**Step 2: Run tests to verify they fail**
- Run: `python3 -m unittest snn3dexp.tests.test_ablation_contract`
- Expected: FAIL，说明 case 间差异还没标准化。

**Step 3: Write minimal implementation**
- 固化四个 case 的 `spec.json`
- `analyze_ablation.py` 负责读取每个 case 的 summary/meta，输出对照表：
  - latency
  - byte hops
  - per-stack req/bytes
  - z hops
  - vertical link bytes

**Step 4: Run tests to verify they pass**
- Run: `python3 -m unittest snn3dexp.tests.test_ablation_contract`
- Expected: PASS

### Task 8: 完整验证、真实 smoke 与进展记录

**Files:**
- Modify: `TECH_PROGRESS.md`

**Step 1: Run all Python-side isolated tests**
- Run: `python3 -m unittest snn3dexp.tests.test_paths`
- Run: `python3 -m unittest snn3dexp.tests.test_shape3d`
- Run: `python3 -m unittest snn3dexp.tests.test_mesh3d_template_spec`
- Run: `python3 -m unittest snn3dexp.tests.test_mesh3d_template_contract`
- Run: `python3 -m unittest snn3dexp.tests.test_run_case`
- Run: `python3 -m unittest snn3dexp.tests.test_case_catalog`
- Run: `python3 -m unittest snn3dexp.tests.test_noc_multicast_3d`
- Run: `python3 -m unittest snn3dexp.tests.test_hbm_stack`
- Run: `python3 -m unittest snn3dexp.tests.test_platform_builder`
- Run: `python3 -m unittest snn3dexp.tests.test_router3d_component_contract`
- Run: `python3 -m unittest snn3dexp.tests.test_route3d_mapping`
- Run: `python3 -m unittest snn3dexp.tests.test_ablation_contract`

**Step 2: Compile-check isolated C++ additions**
- Run: `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4`
- Expected: PASS

**Step 3: Verify component visibility**
- Run: `sst-info SnnDL | rg "MulticastRouter3DNative|SynapseRouteSubsystem3D"`
- Expected: 输出新组件可见。

**Step 4: Run step-limited smoke cases**
- Run: `python3 snn3dexp/tools/run_case.py baseline_2d --validate-only`
- Run: `python3 snn3exp/tools/run_case.py memory_only_3d --dry-run`
- Run: `python3 snn3dexp/tools/run_case.py noc_only_3d --dry-run`
- Run: `python3 snn3dexp/tools/run_case.py full_3d --dry-run`
- Run: `python3 snn3dexp/tools/run_case.py full_3d`
- Expected:
  - 四个 case 都能解析为 isolated path
  - `full_3d` 真实 run 目录写入 `snn3dexp/runs/full_3d`
  - 生成 `meta.json` / summary / validation log

**Step 5: Run ablation analysis**
- Run: `python3 snn3dexp/tools/analyze_ablation.py --run-root snn3dexp/runs --out snn3dexp/analysis/ablation_summary.json`
- Expected: 输出 `2D baseline / 3D memory-only / 3D NoC-only / full 3D` 对照摘要。

**Step 6: Append progress log**
- 在 `TECH_PROGRESS.md` 末尾追加：
  - 新增 `snn3dexp` 长任务完成情况
  - 关键运行命令与输出目录
  - 真实 smoke 结果
  - 下一阶段 TODO（thermal / vertical fault / adaptive 3D routing）
