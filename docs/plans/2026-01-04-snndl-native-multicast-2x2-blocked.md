# SnnDL Native Multicast（2×2 分块路由）Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不修改 SST core / merlin timed 数据面的前提下，为 SnnDL 的 spike 通信落地一个“原生支持多播”的新后端：**2×2 块内多播、块间单播到固定左上角 ingress，并在目的 PE 内按 core mask 精确投递**。

**Architecture:** `services/synapse/route` 预计算 `pre_global -> block_targets(core_masks)`；`SpikeCommSubsystem` 注入 `NocPacketEvent(kind=SpikeKey)`；新 `components/noc/MulticastRouter` 在网络中复制并按 core mask 生成“本地递送包”；目的 core/workload 仅接收自己需要的 SpikeKey，并用本地索引展开 posts 进入既有 window/GAS/权重读路径。

**Tech Stack:** SST（Event/Link + ELI Component/SubComponent + stats），C++17，现有 SnnDL NoC 栈（`INocTransport`/`NocSubsystem`/`NocPacketEvent`），脚本 `SnnDL_Basic/scripts/test_classification_4x4.py`（作为装配与回归基线）。

---

## 0) 仓库约束（必须遵守）

- **不改 SST core / merlin timed 数据面**：本方案完全在 `sst-elements/SnnDL` 内落地；不依赖 `SimpleNetwork::Request` 的 group hack。
- **不做 git 写操作**：本计划文档不包含默认 `git commit/push/...`；如需提交，请主人明确授权后再加到执行步骤中。
- **层次结构与模块化**：
  - `events/`：仅放通用事件类型（payload-agnostic）。
  - `services/synapse/route/`：仅放“路由/突触语义”（fanout、gating、multicast 目标生成），不做 NoC 传输细节。
  - `services/noc/`：只做传输编排（`INocTransport`），不解析权重/BCSR。
  - `components/noc/`：放 ELI 可加载“网络后端组件”（router / nic / adapter），可解析 **SpikeKey 路由头**（属于网络层元数据），但不碰权重值。
  - `services/workload/snn/`：接收侧展开 posts 并进入既有窗口/权重读业务逻辑（保持语义一致性）。

---

## 1) 现状基线（对齐“为什么要改”）

当前发送侧是逐条单播：
- `SpikeCommSubsystem::emitCommon_()`：对 fanout 的每个目的构造 `SpikeEvent` 并 `transport_->send()`（单目的）。
- `SpikeNocCodec::encode()`：把 `SpikeEvent(src,dst)` 编成 `NocPacketEvent(dst_node/dst_endpoint 单一)`。
- `NocSubsystem` → `SnnNIC/merlin`：最终仍是单 dest 的网络数据面。

这会把“多播复制点”放在源端（按边发送），无法体现网络中间共享链路节省，也不利于后续扩展“分块路由”等策略。

---

## 2) 本次落地范围（只做一个可用版本）

### 2.1 必做（MVP）
- **路由策略**：2×2 block routing（块间单播到 ingress；块内树形多播）。
- **Ingress 策略**：固定“块左上角” router 为 ingress。
- **精确投递**：块内每个目的 PE 用 `core_mask` 精确投递到需要的 core（不广播到所有 core）。
- **语义选择**：SpikeKey（pre-only）+ 目的端本地展开 posts；网络内只复制 SpikeKey 包。
- **装配**：新增可选网络后端（router mesh），保持 `test_classification_4x4.py` 原路径不变，新增开关切换。

### 2.2 不做（明确 out-of-scope）
- 不做 merlin/hr_router timed multicast 改造。
- 不做自适应路由/拥塞感知（先 deterministic XY）。
- 不做信用/VC 的精细流控（先固定 hop 延迟 + 有界队列/简单背压，占位接口保留）。
- 不做“任意目的集合”的全局 group registry（本 MVP 直接把 **本 block 的 core_masks** 放在 SpikeKey payload 中，避免跨 rank 的 registry 同步复杂度；后续如需可再引入 group_id→meta 缓存）。

---

## 3) 数据面与包格式（稳定契约）

### 3.1 新增包类型
在 `events/NocPacketEvent.h` 增加：
- `NocPacketKind::SpikeKey`（用于多播数据面）

### 3.2 Wire 格式（payload bytes）
新增 `WireSpikeKeyV1`（建议放在 `services/synapse/route/SpikeNocCodec.h` 同文件内，避免新增过多头文件；也可新建 `SpikeKeyNocCodec.h`）：

```c++
// Versioned, trivially-copyable payload. No pointers.
struct WireSpikeKeyV1 final {
  uint16_t version;        // =1
  uint16_t route_mode;     // 0=flat(预留), 1=blocked(本次实现)
  uint16_t stage;          // 0=INTER, 1=INTRA
  uint16_t block_w_h;      // packed: (block_w<<8)|block_h, 本次固定 0x0202

  uint32_t mesh_w;         // for validation/debug (optional, can be 0)
  uint32_t mesh_h;         // for validation/debug (optional, can be 0)
  uint32_t block_id;       // (y/block_h)*(mesh_w/block_w) + (x/block_w)
  uint32_t ingress_node;   // fixed top-left node id of the block

  uint32_t pre_global;     // spike key
  uint64_t group_id;       // deterministic: (uint64_t(block_id)<<32) | pre_global

  uint32_t core_mask[4];   // 2×2 block nodes, in fixed order (see below)
};
```

**2×2 节点顺序（core_mask[4]）必须固定且全局一致**：
- idx0：block 左上（ingress） `(bx,by)=(0,0)`
- idx1：右上 `(1,0)`
- idx2：左下 `(0,1)`
- idx3：右下 `(1,1)`

`core_mask[idx]` 的 bit `k` 表示：该 block 内第 idx 个节点的 core `k` 需要接收并展开该 `pre_global` 的 posts。

### 3.3 NocPacketEvent 头字段约定
- `kind = SpikeKey`
- `timestamp = now_cycle`（保持现有“按发放周期排序”的口径；router clone 时保持不变）
- `dst_node`：
  - INTER：写 `ingress_node`（普通单播到 ingress）
  - INTRA：router 内部可将 `dst_node` 改为 `0xffffffff` 作为“多播中间态”（或保持原值但仅靠 payload.stage 判定）
- `dst_endpoint`：
  - INTER/中间态：可为 0
  - 本地投递包：router 将其改写为目标 core id（精确投递）

---

## 4) 路由算法（2×2 blocked）

### 4.1 块间（INTER）单播：deterministic XY 到 ingress
- 以 mesh 的 `(x,y)` 坐标计算下一跳：
  - `x < dest_x` → east
  - `x > dest_x` → west
  - 否则 `y < dest_y` → south
  - 否则 `y > dest_y` → north

### 4.2 块内（INTRA）多播：固定树 + 禁止回送
以 ingress `(0,0)` 为根，采用固定树（避免重复与非确定性）：
- ingress(0,0)：
  - east：当 `core_mask[idx1]!=0 || core_mask[idx3]!=0`
  - south：当 `core_mask[idx2]!=0 || core_mask[idx3]!=0`
  - local：按 `core_mask[idx0]` 投递
- top-right(1,0)：
  - south：当 `core_mask[idx3]!=0`
  - local：按 `core_mask[idx1]` 投递
- bottom-left(0,1)：
  - **不转发 east**（bottom-right 的父节点固定选择 top-right）
  - local：按 `core_mask[idx2]` 投递
- bottom-right(1,1)：
  - local：按 `core_mask[idx3]` 投递

这样保证：
- 若 bottom-right 有目的 core，则 ingress 必然发 east 到 top-right，top-right 再发 south 到 bottom-right；
- bottom-left 永不向 east 转发，避免 bottom-right 重复收包；
- 端口复制顺序固定（例如：E → S → LOCAL），确保确定性。

---

## 5) 模块职责与文件落点（严格分层）

### 5.1 `services/synapse/route`（“路由语义层”）
**新增能力**：基于 `routesShared()` 构建 `pre_global -> block_targets(core_mask[4])`。

- 修改：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.{h,cc}`
    - 在 `initRoutes()` 完成后构建 `multicast_targets_`（只在 multicast_enable=1 且 routing_weight_driven=1 时启用）。
    - 提供一个模块内可用方法（不扩展 `api/ISynapseRoute`）：例如
      - `bool multicastEnabled() const;`
      - `bool computeMulticastTargets(uint32_t pre_global, uint32_t neuron_idx, uint64_t now_cycles, std::vector<BlockTarget>& out, bool& applied_gating) const;`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/SynapseRouteBuildConfig.h`
    - 增加开关字段（默认关闭，保持兼容）：`multicast_enable`、`multicast_block_w`、`multicast_block_h`、`multicast_ingress_policy`（字符串：`"top_left"`）。

### 5.2 `services/synapse/route`（“封包/发送门面”）
- 修改：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.{h,cc}`
    - Runtime 额外注入：`INocTransport* noc` + `int src_core` + `uint32_t node_id`（用于构造/注入 SpikeKey packet）。
    - 当 `multicast_enable=1`：走 `computeMulticastTargets()`，对每个 block target 发 **1 条 SpikeKey** 到 ingress（INTER）。
    - 当 `multicast_enable=0`：保持现有逐条单播 `SpikeEvent` 行为不变。

### 5.3 `events/`（payload-agnostic）
- 修改：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/events/NocPacketEvent.h`
    - 增加 `NocPacketKind::SpikeKey`
    - **新增 `clone()` 支持或提供显式复制辅助**（router 多播需要复制；SST 默认 `Event::clone()` 会 fatal）。

### 5.4 `components/noc/`（网络后端组件）
- 新增：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.{h,cc}`
    - ELI Component：`SnnDL.MulticastRouter`
    - 端口：`local`, `north`, `south`, `east`, `west`（均为 `SnnDL.NocPacketEvent`）
    - INTER：按 `dst_node` 做 XY 单播；INTRA：按 payload 的 `core_mask[4]` 做块内树形多播与本地投递（改写 `dst_endpoint`）。
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastNIC.{h,cc}`
    - ELI SubComponent：`SnnDL.MulticastNIC`，实现 `api/SnnInterface.h`
    - 仅负责“注入到本地 router”：`sendToNode(dest, ev)` → 直接 `link(local)->send(ev)`（dest 参数仅用于保持接口兼容，实际路由由 router 解释 `NocPacketEvent` 头）。
    - 接收侧可先不接管（router→PE 走 `MultiCorePE.handleNetworkLinkEvent` 也能落地）；后续再做“NIC 接收并回调”的清理。

### 5.5 `services/workload/snn/`（目的端展开）
- 修改：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
    - 在 `deliverPacket()` 增加 `NocPacketKind::SpikeKey` 分支：
      - 解码 `WireSpikeKeyV1.pre_global`
      - 通过本地缓存 `pre_global -> posts_local` 展开（仅本 core 的 posts）
      - MVP：为每个 post_local 构造轻量 SpikeEvent 并复用 `deliverSpike()`（保证语义一致）；后续再优化为“无 SpikeEvent 分配”的直接 recordEdge 快路径。

---

## 6) 装配（脚本）与回归基线

目标：不破坏 `SnnDL_Basic/scripts/test_classification_4x4.py` 现有默认路径，仅新增开关。

### 6.1 脚本新增开关（local_run_config.json）
建议新增键：
- `enable_native_multicast_router: bool`（默认 false）
- `multicast_block_w: int`（默认 2）
- `multicast_block_h: int`（默认 2）

### 6.2 当开关开启时的装配逻辑（4×4）
- 为每个 `(x,y)` 实例化一个 `SnnDL.MulticastRouter`，参数 `node_id=x+y*W`、`mesh_shape="4x4"`、`router_latency_cycles=1`（可调）。
- router 之间按 N/S/E/W 连接。
- 每个 `MultiCorePE`：
  - `network_interface` 从 `SnnDL.SnnNIC` 切到 `SnnDL.MulticastNIC`
  - 连接 `MultiCorePE.network` ↔ `router.local`（本地注入/回收）
  - 在每个 core 参数里加：`multicast_enable=1`、`multicast_block_w=2`、`multicast_block_h=2`、`multicast_ingress_policy="top_left"`
- 当开关关闭：保持原 SnnNIC+merlin 路径不变。

---

## 7) 分步推进计划（可执行 TODO）

> 注：本仓库偏重集成验证（编译 + 运行脚本）。测试策略以“现有回归脚本 + include/compile check”为主；如需引入单元测试框架需另行评审（YAGNI）。

### Task 1: 引入 SpikeKey 包类型与复制能力

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/events/NocPacketEvent.h`
- Test/Compile: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_includes.cc`

**Step 1: 让现有 include 编译先失败（暴露缺口）**
- 在 `test_includes.cc` 增加对新增头/枚举的引用（先不实现）。

**Step 2: 最小实现**
- 增加 `NocPacketKind::SpikeKey`
- 为 `NocPacketEvent` 增加可用的 `clone()`（或提供 `static NocPacketEvent* cloneOf(const NocPacketEvent&)` 并让 router 使用它）

**Step 3: 编译验证**
- Run: `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`
- Expected: 编译通过

---

### Task 2: 定义 WireSpikeKeyV1 编解码（payload bytes）

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeNocCodec.h`（或新增 `SpikeKeyNocCodec.h`）
- Test/Compile: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_includes.cc`

**Step 1: 先写一个最小 round-trip 自检函数（仅 debug/开发用）**
- 在头文件内提供 `encodeSpikeKey(...)` / `decodeSpikeKey(...)`，确保 `payload.size()==sizeof(WireSpikeKeyV1)`。

**Step 2: 编译验证**
- Run: `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`

---

### Task 3: SynapseRouteSubsystem 预计算 `pre -> block_targets(core_masks)`

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/SynapseRouteBuildConfig.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.{h,cc}`

**Step 1: 增加配置字段（默认关闭）**
- `multicast_enable`（0/1）
- `multicast_block_w`（默认2）
- `multicast_block_h`（默认2）
- `multicast_ingress_policy`（默认 `"top_left"`）

**Step 2: 在 initRoutes() 完成 routes_shared_ 后构建 multicast_targets_**
- 仅在 `routing_weight_driven && multicast_enable` 时启用
- 构建结果数据结构（示例）：
  - `unordered_map<uint32_t /*pre*/, vector<BlockTarget>> multicast_targets_`
  - `BlockTarget` 内含：`block_id/ingress_node/core_mask[4]`

**Step 3: 提供模块内查询方法（供 SpikeCommSubsystem 调用）**
- `computeMulticastTargets(pre_global, neuron_idx, now_cycles, out, applied_gating)`
  - gating 命中时：基于 `dest_pes` 即时合成 core_mask（top-k 小集合）
  - 否则：直接查 `multicast_targets_`

**Step 4: 编译验证**
- Run: `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`

---

### Task 4: SpikeCommSubsystem 在 multicast_enable=1 时发 SpikeKey（按 block）

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.{h,cc}`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`（把 rt_.noc/src_core 传给 SpikeComm）

**Step 1: 扩展 SpikeCommRuntimeConfig（保持默认 nullptr）**
- 新增 `INocTransport* noc = nullptr`
- 新增 `int src_core = 0`
- 新增 `uint32_t node_id = 0`（可选，主要用于调试）

**Step 2: emitCommon_() 增加分支**
- if `multicast_enable`：
  - 调 `computeMulticastTargets()` 得到 block targets
  - 对每个 block target 构造 1 个 `NocPacketEvent(kind=SpikeKey)`，`dst_node=ingress_node`，payload=WireSpikeKeyV1
  - `noc->sendFromCore(src_core, pkt)`
- else：保持原逐条单播 SpikeEvent 行为不变

**Step 3: 编译验证**
- Run: `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`

---

### Task 5: MulticastRouter（2×2 blocked）组件骨架与单播 XY

**Files:**
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.h`
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.am`（加入新源文件）

**Step 1: 实现最小 unicast XY 转发（先不处理 SpikeKey）**
- local/n/s/e/w 端口都能收包并转发到下一跳
- 目的为本 node：转发到 local（交给 PE）

**Step 2: 编译验证**
- Run: `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`

---

### Task 6: MulticastRouter 增加 SpikeKey：INTER→INTRA 与块内多播

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.{h,cc}`

**Step 1: INTER 到 ingress 的切换**
- 当 `stage==INTER && node_id==ingress_node`：
  - payload.stage 改为 INTRA
  - `dst_node` 可改为 `0xffffffff`（或保持不变但仅以 stage 判定）

**Step 2: INTRA 块内树形转发 + core_mask 本地投递**
- 按第 4 节算法决定 east/south 转发
- 本地投递：对 `core_mask[idx_self]` 每个 bit 生成一个包：
  - `pkt->dst_node = this_node`
  - `pkt->dst_endpoint = core_id`
  - `pkt->kind = SpikeKey`
  - 保持 payload 不变（pre_global 供目的端展开）

**Step 3: 编译验证**
- Run: `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`

---

### Task 7: MulticastNIC（注入到本地 router）

**Files:**
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastNIC.h`
- Create: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastNIC.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.am`

**Step 1: 实现 SnnInterface::sendToNode**
- `sendToNode(dest_node, event)`：直接把 event `send()` 到 `network` 端口（连接到 router.local）
- `setReceiveHandler()` 可先保存但不强制使用（MVP 接收侧由 MultiCorePE 的 `handleNetworkLinkEvent` 进入 NocSubsystem）

**Step 2: 编译验证**
- Run: `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`

---

### Task 8: 目的端展开（workload 处理 SpikeKey）

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`

**Step 1: deliverPacket() 增加 SpikeKey 分支**
- decode pre_global
- 维护一个 `unordered_map<uint32_t, vector<uint32_t>> pre_to_posts_local_`（仅本 core）
  - 首次访问 pre_global：从 `synapse_route_->routesShared()` 取 dest_global 列表并过滤到本 node+本 core，缓存为 `post_local` 列表（排序去重）
- 对每个 `post_local`：
  - MVP 方案：构造 `SpikeEvent(pre_global, global_neuron_base_+post_local, node_id, weight=0.0, pkt.timestamp)` 并调用 `deliverSpike(spike)`

**Step 2: 编译验证**
- Run: `cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4`

---

### Task 9: 脚本装配与回归（保持默认不变）

**Files:**
- Modify: `SnnDL_Basic/scripts/test_classification_4x4.py`
- Modify (optional): `SnnDL_Basic/scripts/local_run_config.json`（由用户侧维护，计划中只描述键）

**Step 1: 新增开关 enable_native_multicast_router**
- 默认 False：保持原 `SnnDL.SnnNIC` + `merlin.hr_router` 配置不变
- True：构建 `SnnDL.MulticastRouter` 网格并连接 `MultiCorePE.network`
- True：`network_interface` 选 `SnnDL.MulticastNIC`
- True：核心参数加 `multicast_enable=1` 等

**Step 2: 运行回归**
- Run: `cd "SnnDL_Basic/scripts" && sst "test_classification_4x4.py"`
- Expected:
  - baseline（关闭开关）输出不变
  - multicast（开启开关）可正常运行，分类结果与关键统计在允许波动范围内（优先对齐功能正确性）

---

### Task 10: 性能与统计（最小可观测性）

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.{h,cc}`
- Modify: `SnnDL_Basic/scripts/test_classification_4x4.py`（启用 router 统计）

**Step 1: Router stats**
- `packets_in/out`（按端口）
- `spikekey_clones_generated`
- `spikekey_local_deliveries`（按 core-mask bit 计数）
- `unicast_hops_sum` / `spikekey_intra_hops_sum`

**Step 2: 用 10us/50us 小运行对比**
- 对比两种模式下：
  - network packets 数量（预期显著下降）
  - router clones 数（反映多播树分叉）
  - wall-clock（至少不应数量级变慢）

---

## 8) 风险清单与规避

- **clone() fatal 风险**：SST `Event::clone()` 默认 fatal；router 必须显式复制 `NocPacketEvent`。
- **语义漂移风险**：目的端展开必须复用现有 `deliverSpike()/window` 链路，MVP 不直接改 compute core。
- **确定性风险**：端口转发顺序固定；`post_local` 列表排序去重；保持现有 `NocSubsystem::drainIncomingQueue` 排序逻辑。
- **规模风险**：`pre->posts_local` 缓存可能大；必要时增加参数开关（lazy cache / prebuild / LRU）并记录内存占用。

