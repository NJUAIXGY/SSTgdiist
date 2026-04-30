# SnnDL Topology Visualization Foundation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `SnnDL` 的 2D / 3D 芯片系统落地一套可直接供后续可视化消费的统一拓扑导出底座，先打通 `baseline_2d` 与 `full_3d` 两个 canonical case。

**Architecture:** 新增独立共享包 `snndl_topology/`，不改动现有 `sst_dram_si` 和 `snn3dexp` 的核心 builder，只读取它们已经稳定的几何、NoC、memory 和 workload 约定，再规范化导出成统一 `Topology IR`。第一阶段只强制覆盖 `physical topology` 主图，同时把 `logical workload groups`、`multicast block shape` 和 `memory-home bindings` 作为附加层一起导出。

**Tech Stack:** Python 3、`unittest`、`snn3dexp.shape3d`、`snn3dexp.noc.multicast_3d`、`snn3dexp.memory`、`snn3dexp.mesh3d_template.build`、`sst_dram_si.mesh_template.task_snn`、append-only `TECH_PROGRESS.md`。

---

### Task 1: Define The Unified Topology IR

**Files:**
- Create: `/home/xgy/remote/snndl_topology/ir.py`
- Create: `/home/xgy/remote/snndl_topology/__init__.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_topology_ir.py`

**Step 1: Write the failing test**

在 `/home/xgy/remote/snn3dexp/tests/test_topology_ir.py` 写红灯测试，锁定统一 IR 的最小 contract：

- 顶层必须包含：
  - `shape`
  - `physical`
  - `logical`
  - `multicast`
  - `memory`
  - `metadata`
- `shape` 必须规范化成：
  - `x`
  - `y`
  - `z`
  - `total_nodes`
- `physical` 必须至少包含：
  - `nodes`
  - `routers`
  - `links`
- `build_topology_ir(...)` 会对 `None` 输入做默认展开，避免调用方自己补空字段。

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_topology_ir -v
```

Expected:

- FAIL，因为 `snndl_topology` 包和 `build_topology_ir(...)` 还不存在。

**Step 3: Write minimal implementation**

在 `/home/xgy/remote/snndl_topology/ir.py` 新增最小 IR builder：

- `build_topology_ir(...)`
- `_normalize_shape(...)`
- `_as_list(...)`

要求：

- 只做结构归一化，不做业务推断。
- 输出必须是纯 `dict/list/int/bool/str`，便于后续 JSON 序列化。
- 第一版不要引入 dataclass 序列化层，保持简单直接。

**Step 4: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_topology_ir -v
```

Expected:

- PASS

### Task 2: Add Extractor Red Tests For 2D And 3D Canonical Cases

**Files:**
- Create: `/home/xgy/remote/snn3dexp/tests/test_topology_extractors.py`

**Step 1: Write the failing test**

在 `/home/xgy/remote/snn3dexp/tests/test_topology_extractors.py` 写两组红灯测试：

- `test_extract_2d_topology_for_baseline_case`
  - 使用 `4x4x1`
  - 断言 `physical.nodes == 16`
  - 断言 `physical.routers == 16`
  - 断言 `physical.links` 中：
    - mesh 边数量为 `24`
    - local 边数量为 `16`
  - 断言 `logical.groups` 包含：
    - `input_layer`
    - `hidden_layer_1`
    - `hidden_layer_2`
    - `output_layer`
  - 断言 `multicast.block_shape == {w: 0, h: 0, d: 0}`
  - 断言 `memory.stacks == []`

- `test_extract_3d_topology_for_full_3d_case`
  - 载入 `/home/xgy/remote/snn3dexp/cases/full_3d/spec.json`
  - 断言 `shape.total_nodes == 32`
  - 断言 `physical.nodes == 32`
  - 断言 `physical.routers == 32`
  - 断言 mesh 边数量为 `64`
  - 断言 local 边数量为 `32`
  - 断言 router `component_type == SnnDL.MulticastRouter3DNative`
  - 断言 `multicast.block_shape == {w: 2, h: 2, d: 2}`
  - 断言 `memory.stacks == 4`
  - 断言 `memory.bindings == 32`
  - 断言上层节点的 `attach_latency_ns` 大于底层节点

- 再补一个统一入口测试：
  - `build_topology_summary(raw_spec=full_3d_spec)` 会自动走 3D extractor
  - `build_topology_summary(source="mesh_template", mesh_size=4)` 会走 2D extractor

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_topology_extractors -v
```

Expected:

- FAIL，因为 extractor 和统一入口还不存在。

### Task 3: Implement The 3D Extractor

**Files:**
- Create: `/home/xgy/remote/snndl_topology/extract_3d.py`
- Modify: `/home/xgy/remote/snndl_topology/__init__.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_topology_extractors.py`

**Step 1: Write minimal implementation**

在 `/home/xgy/remote/snndl_topology/extract_3d.py` 最小实现：

- `extract_3d_topology(raw_spec=None, *, case_name="bootstrap_smoke")`

实现路径：

1. 用 `build_effective_config(...)` 解析 spec。
2. 用 `parse_mesh_shape(...)` 解析三维几何。
3. 用 `build_router_descriptors(...)` + `connect_router_links_3d(...)` 抽出 router 与 mesh 边。
4. 为每个 `node_id` 补：
   - `x`
   - `y`
   - `z`
   - `num_cores`
   - `kind="pe"`
5. 额外为每个 node/router 补一条 `local` 边，显式表示 PE 接入 NoC。
6. 用 `build_stack_descriptors(...)`、`home_stack_for_node(...)`、`attachment_latency_for_node(...)` 导出：
   - `memory.stacks`
   - `memory.bindings`
7. 把 `multicast_block_dim_x/y/z` 归一化成：
   - `multicast.block_shape = {"w": ..., "h": ..., "d": ...}`

第一版不做：

- packet-level path
- ingress 传播树
- stack 内 controller/probe 细节

这些保留给下一阶段 overlay。

**Step 2: Run test to verify it passes partially**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_topology_extractors.TopologyExtractorTests.test_extract_3d_topology_for_full_3d_case -v
```

Expected:

- 3D case PASS
- 2D case 仍可能 FAIL

### Task 4: Implement The 2D Extractor And Unified Entry

**Files:**
- Create: `/home/xgy/remote/snndl_topology/extract_2d.py`
- Modify: `/home/xgy/remote/snndl_topology/__init__.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_topology_extractors.py`

**Step 1: Write minimal implementation**

在 `/home/xgy/remote/snndl_topology/extract_2d.py` 最小实现：

- `extract_2d_topology(*, mesh_size=4, node_limit=None, num_cores=1, vertical_route_order="xy")`
- `build_topology_summary(raw_spec=None, *, source="auto", case_name="bootstrap_smoke", mesh_size=4, node_limit=None, num_cores=1)`

实现规则：

1. 2D extractor 使用规则平面 mesh：
   - `x+1` 形成 `east`
   - `y+1` 形成 `south`
2. 每个 PE 生成：
   - 一个 `node`
   - 一个 `router`
   - 一条 `local` 边
3. `logical.groups` 直接复用：
   - `resolve_fixed_4x4_layers()`
4. `memory` 第一版保持：
   - `kind = legacy_per_pe`
   - `stacks = []`
   - `bindings = []`
5. `multicast` 第一版保持禁用态：
   - `block_shape = {"w": 0, "h": 0, "d": 0}`
6. 统一入口分派策略：
   - `source == "mesh_template"` 时强制走 2D extractor
   - `source == "snn3dexp"` 时强制走 3D extractor
   - `source == "auto"` 时：
     - `raw_spec` 存在且 `mesh_shape.z > 1` 走 3D
     - 否则走 2D

**Step 2: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_topology_extractors -v
```

Expected:

- PASS

### Task 5: Focused Verification And Progress Logging

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run focused verification**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_topology_ir \
  snn3dexp.tests.test_topology_extractors \
  snn3dexp.tests.test_platform_builder \
  snn3dexp.tests.test_noc_multicast_3d \
  snn3dexp.tests.test_hbm_stack -v
```

Expected:

- 新增拓扑 IR / extractor 测试 PASS
- 相关既有 3D NoC / memory / platform 测试保持 PASS

**Step 2: Append TECH_PROGRESS.md**

在 `/home/xgy/remote/TECH_PROGRESS.md` 末尾追加：

- 本次新增的 `snndl_topology/` 文件
- 导出的 IR 覆盖范围
- 2D / 3D 验证命令
- 当前未覆盖的下一阶段内容：
  - ingress tree
  - block 内传播树
  - memory controller/probe 细粒度 overlay
  - 前端渲染层
