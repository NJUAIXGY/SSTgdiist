# SnnDL Topology CLI And Frontend Visualization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 为 `snndl_topology` 增加统一 JSON/export CLI，并在现有 `frontend-dashboard` 中落地第一版拓扑可视化页面，直接消费该导出 JSON。

**Architecture:** 后端侧在 `snndl_topology` 内新增一个轻量 CLI，把 `build_topology_summary(...)` 包装成文件/标准输出导出入口，同时生成可供前端自测的 sample JSON。前端侧复用现有 Vite + React 仪表盘，增加 `Topology` 路由、JSON parser、纯函数 view model 和 layered SVG 主视图，先覆盖 `physical main view + logical/memory/multicast overlay summary`。

**Tech Stack:** Python 3、`argparse`、`json`、`unittest`、React 19、TypeScript、Vite、Tailwind、Node built-in test runner、现有 `frontend-dashboard` 路由与文件上传 hook。

---

### Task 1: Add Red Tests For Export CLI

**Files:**
- Create: `/home/xgy/remote/snn3dexp/tests/test_topology_cli.py`
- Test: `/home/xgy/remote/snndl_topology/__init__.py`

**Step 1: Write the failing test**

在 `/home/xgy/remote/snn3dexp/tests/test_topology_cli.py` 写两组红灯测试：

- `test_cli_exports_full_3d_spec_to_json_file`
  - 调用 CLI main
  - 输入 `/home/xgy/remote/snn3dexp/cases/full_3d/spec.json`
  - 输出到临时 JSON
  - 断言：
    - `shape.z == 2`
    - `metadata.extractor == "3d"`
    - `memory.stacks == 4`

- `test_cli_exports_mesh_template_topology`
  - 调用 CLI main
  - 使用 `--source mesh_template --mesh-size 4`
  - 输出到临时 JSON
  - 断言：
    - `shape.z == 1`
    - `metadata.extractor == "2d"`
    - `logical.groups` 非空

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_topology_cli -v
```

Expected:

- FAIL，因为 CLI 模块和 main 入口还不存在。

### Task 2: Add Red Tests For Frontend Parser And View Model

**Files:**
- Create: `/home/xgy/remote/frontend-dashboard/src/utils/parseTopologyExport.ts`
- Create: `/home/xgy/remote/frontend-dashboard/src/utils/buildTopologyViewModel.ts`
- Create: `/home/xgy/remote/frontend-dashboard/src/utils/topologyExport.test.ts`
- Modify: `/home/xgy/remote/frontend-dashboard/package.json`

**Step 1: Write the failing test**

在 `/home/xgy/remote/frontend-dashboard/src/utils/topologyExport.test.ts` 写红灯测试，锁定：

- `parseTopologyExport(rawText)` 能解析导出 JSON，返回：
  - `shape`
  - `physical`
  - `logical`
  - `multicast`
  - `memory`
  - `metadata`
- `buildTopologyViewModel(topology)` 会派生：
  - `layerCount`
  - `layers[]`
  - `nodeCount`
  - `routerCount`
  - `meshLinkCount`
  - `localLinkCount`
  - `logicalGroupMap`
  - `memoryBindingMap`
- `full_3d` sample 会生成两个 layer
- `baseline_2d` sample 会生成一个 layer

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote/frontend-dashboard
node --test src/utils/topologyExport.test.ts
```

Expected:

- FAIL，因为 parser / view model 还不存在。

### Task 3: Implement The Export CLI And Generate Sample JSON

**Files:**
- Create: `/home/xgy/remote/snndl_topology/cli.py`
- Create: `/home/xgy/remote/snndl_topology/__main__.py`
- Modify: `/home/xgy/remote/snndl_topology/__init__.py`
- Test: `/home/xgy/remote/snn3dexp/tests/test_topology_cli.py`
- Create via CLI output:
  - `/home/xgy/remote/frontend-dashboard/public/data/topology_full_3d_sample.json`
  - `/home/xgy/remote/frontend-dashboard/public/data/topology_baseline_2d_sample.json`

**Step 1: Write minimal implementation**

在 CLI 中最小支持：

- `--spec <path>`
- `--source auto|snn3dexp|mesh_template`
- `--case-name <name>`
- `--mesh-size <n>`
- `--node-limit <n>`
- `--num-cores <n>`
- `--out <path>`
- `--indent <n>`

行为：

- 有 `--spec` 时读取 JSON spec 后走 `build_topology_summary(...)`
- `--source mesh_template` 时走 2D extractor
- 未指定 `--out` 时输出到 stdout
- 指定 `--out` 时写入 JSON 文件

然后用 CLI 生成两个 frontend sample JSON。

**Step 2: Run test to verify it passes**

Run:

```bash
python3 -m unittest snn3dexp.tests.test_topology_cli -v
```

Expected:

- PASS

### Task 4: Implement Frontend Parser, View Model, And Topology Page

**Files:**
- Create: `/home/xgy/remote/frontend-dashboard/src/utils/parseTopologyExport.ts`
- Create: `/home/xgy/remote/frontend-dashboard/src/utils/buildTopologyViewModel.ts`
- Create: `/home/xgy/remote/frontend-dashboard/src/pages/TopologyView.tsx`
- Create: `/home/xgy/remote/frontend-dashboard/src/components/topology/TopologyLayerScene.tsx`
- Create: `/home/xgy/remote/frontend-dashboard/src/components/topology/TopologySummaryCards.tsx`
- Modify: `/home/xgy/remote/frontend-dashboard/src/App.tsx`
- Modify: `/home/xgy/remote/frontend-dashboard/src/components/layout/AppLayout.tsx`
- Modify: `/home/xgy/remote/frontend-dashboard/package.json`
- Test: `/home/xgy/remote/frontend-dashboard/src/utils/topologyExport.test.ts`

**Step 1: Write minimal implementation**

实现内容：

1. `parseTopologyExport.ts`
   - 校验导出 JSON 结构
   - 给出可读错误信息

2. `buildTopologyViewModel.ts`
   - 按 `z` 切 layer
   - 把 node/router/link 转成前端友好的网格模型
   - 派生 logical group 与 memory binding lookup

3. `TopologyView.tsx`
   - 默认加载 `topology_full_3d_sample.json`
   - 支持上传 JSON 文件
   - 支持切换 2D / 3D sample
   - 提供 overlay selector：
     - `physical`
     - `logical`
     - `memory`
     - `multicast`
   - 左侧展示 summary cards，主体展示 layer scene

4. `TopologyLayerScene.tsx`
   - 以 layered SVG/HTML grid 呈现每个 `z` 平面
   - 主图始终突出 physical links 与 node tiles
   - overlay 模式下在 node tile 上叠加：
     - logical group 色块
     - memory stack 色条
     - multicast block 轮廓提示

第一版不做：

- packet path 动画
- ingress tree 明细
- 复杂 3D 相机/真正立体视角

**Step 2: Run test to verify it passes**

Run:

```bash
cd /home/xgy/remote/frontend-dashboard
node --test src/utils/topologyExport.test.ts
```

Expected:

- PASS

### Task 5: Build Verification, README, And Progress Logging

**Files:**
- Modify: `/home/xgy/remote/frontend-dashboard/README.md`
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run focused verification**

Run:

```bash
python3 -m unittest \
  snn3dexp.tests.test_topology_ir \
  snn3dexp.tests.test_topology_extractors \
  snn3dexp.tests.test_topology_cli -v
```

Run:

```bash
cd /home/xgy/remote/frontend-dashboard
node --test src/utils/topologyExport.test.ts
npm run build
```

Expected:

- Python topology tests PASS
- frontend parser/view-model test PASS
- dashboard build PASS

**Step 2: Update docs**

- 在 `/home/xgy/remote/frontend-dashboard/README.md` 中补：
  - topology page
  - sample JSON
  - CLI export 用法
- 在 `/home/xgy/remote/TECH_PROGRESS.md` 末尾 append：
  - 新增 CLI
  - 新增 sample JSON
  - 新增 topology page
  - 验证命令与结果
