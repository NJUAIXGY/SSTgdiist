# SnnDL Topology Frontend Phase 2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在现有 topology 页面上继续落地两项增强：先把 `up/down` 跨层连接做成真实 bridge 视图，再补 `multicast / memory` 的更细节 overlay 信息。

**Architecture:** 保持当前 `snndl_topology -> JSON -> parseTopologyExport -> buildTopologyViewModel -> TopologyView` 这条链路不变，只扩展前端 view model 与渲染层。第一步在 view model 中新增 `verticalBridges` 与按层分组的 bridge 数据，再在 `TopologyLayerScene` 中插入真实的 inter-layer bridge section。第二步继续在同一个 view model 上派生 `memoryStackSummaries` 与 `multicastBlocks`，然后在 topology 页面右侧 inspector 与 layer tile 中显示更细粒度的 overlay 细节。

**Tech Stack:** React 19、TypeScript、Node test runner、现有 `frontend-dashboard`、Tailwind、append-only `TECH_PROGRESS.md`。

---

### Task 1: Red Tests For Vertical Bridge And Overlay Summaries

**Files:**
- Modify: `/home/xgy/remote/frontend-dashboard/src/utils/topologyExport.test.ts`
- Test: `/home/xgy/remote/frontend-dashboard/src/utils/buildTopologyViewModel.ts`

**Step 1: Write the failing test**

在现有 `topologyExport.test.ts` 中增加红灯断言：

- `full_3d` sample 会派生：
  - `verticalBridges.length > 0`
  - 每条 bridge 至少包含：
    - `fromZ`
    - `toZ`
    - `x`
    - `y`
    - `srcNodeId`
    - `dstNodeId`
- `memoryStackSummaries` 会聚合：
  - `stackId`
  - `nodeCount`
  - `minAttachLatencyNs`
  - `maxAttachLatencyNs`
  - `layerNodeCounts`
- `multicastBlocks` 会聚合：
  - `blockKey`
  - `nodeIds`
  - `bounds`
  - `layerSpan`

**Step 2: Run test to verify it fails**

Run:

```bash
cd /home/xgy/remote/frontend-dashboard
node --test src/utils/topologyExport.test.ts
```

Expected:

- FAIL，因为 view model 还没有这些派生字段。

### Task 2: Implement View Model Phase 2 Fields

**Files:**
- Modify: `/home/xgy/remote/frontend-dashboard/src/utils/buildTopologyViewModel.ts`
- Modify: `/home/xgy/remote/frontend-dashboard/src/utils/topologyExport.test.ts`

**Step 1: Write minimal implementation**

新增派生结构：

- `verticalBridges[]`
  - 从 `up/down` links 推导
  - 保留坐标、节点、跨层关系
- `bridgesByBetweenLayer`
  - 便于渲染 `Z0 -> Z1` bridge strip
- `memoryStackSummaries[]`
  - 每个 stack 下的 node 数、latency 范围、按 layer 的 node 分布
- `multicastBlocks[]`
  - 依据 `multicastBlockKey` 聚合 node，推导 block bounds 与跨层 span

第一版保持纯函数，不往 parser 加业务逻辑。

**Step 2: Run test to verify it passes**

Run:

```bash
cd /home/xgy/remote/frontend-dashboard
node --test src/utils/topologyExport.test.ts
```

Expected:

- PASS

### Task 3: Render Real Inter-Layer Bridges

**Files:**
- Modify: `/home/xgy/remote/frontend-dashboard/src/components/topology/TopologyLayerScene.tsx`
- Modify: `/home/xgy/remote/frontend-dashboard/src/pages/TopologyView.tsx`

**Step 1: Write minimal implementation**

在 `TopologyLayerScene` 中：

- 在相邻 layer section 之间插入 bridge section
- 用一个规则网格 SVG 表示 `fromZ -> toZ` 的垂直连接
- 每个 bridge 点位按 `(x, y)` 放置
- 选中某 node 时，高亮相关 bridge

要求：

- 不做复杂 3D 透视
- 但必须不再只是文本提示，而是真实的 bridge 可视元素

**Step 2: Verify behavior**

Run:

```bash
cd /home/xgy/remote/frontend-dashboard
npm run build
```

Expected:

- PASS，且页面能渲染 inter-layer bridge section。

### Task 4: Add Memory And Multicast Detail Overlays

**Files:**
- Modify: `/home/xgy/remote/frontend-dashboard/src/pages/TopologyView.tsx`
- Modify: `/home/xgy/remote/frontend-dashboard/src/components/topology/TopologySummaryCards.tsx`
- Modify: `/home/xgy/remote/frontend-dashboard/src/components/topology/TopologyLayerScene.tsx`

**Step 1: Write minimal implementation**

具体增强：

- `memory` overlay
  - 右侧 inspector 显示 stack summaries
  - 选中 node 时显示所属 stack 的 layer 分布与 latency 区间
- `multicast` overlay
  - 右侧 inspector 显示 block summaries
  - tile 中显示 block span / block size
  - 若 block 跨层，突出其 layer span

目标是把这两种 overlay 从“只有颜色”推进到“颜色 + 结构摘要”。

**Step 2: Verify behavior**

Run:

```bash
cd /home/xgy/remote/frontend-dashboard
npm run build
```

Expected:

- PASS

### Task 5: Verification And Progress Logging

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Run focused verification**

Run:

```bash
cd /home/xgy/remote/frontend-dashboard
node --test src/utils/topologyExport.test.ts
npm run build
node ./node_modules/eslint/bin/eslint.js src/pages/TopologyView.tsx src/components/topology/TopologyLayerScene.tsx src/components/topology/TopologySummaryCards.tsx src/utils/buildTopologyViewModel.ts src/utils/topologyExport.test.ts
```

Expected:

- 测试 PASS
- build PASS
- 本次改动文件定向 lint PASS

**Step 2: Append TECH_PROGRESS.md**

在 `/home/xgy/remote/TECH_PROGRESS.md` 末尾追加：

- 真实 layer bridge 视图已落地
- memory / multicast overlay 细节已增强
- 验证命令和结果
