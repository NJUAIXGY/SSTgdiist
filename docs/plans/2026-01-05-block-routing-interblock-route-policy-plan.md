# Block Routing（块内多播/块间单播）InterBlockRoutePolicy 扩展实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不改变“块内多播、块间单播（到 block ingress）”核心语义与 SpikeKey 协议的前提下，仅通过扩展 `InterBlockRoutePolicy`（router 层 INTER 阶段单播走法），支持更多可选路由方式，并提供可复现实验口径评估性能差异。

**Architecture:** 维持 3 个正交策略点的分层：`IngressPolicy`（构建期，产出 `ingress_node`）不动，`IntraBlockTreePolicy`（块内树）不动，仅扩展 `InterBlockRoutePolicy`（块间单播）。所有选择均通过 params/环境变量传入，默认值保持现状行为不变。

**Tech Stack:** SST + SST-elements(SnnDL) C++17，Python SST 配置脚本，现有 `SnnDL.MulticastRouter`/`SnnDL.MulticastNIC`/`TrafficWorkload` + `experiments/run_suite.py` 落盘统计。

---

## Current State（基线）

### 已存在的路由语义（必须保持）
- **块间单播（INTER stage）**：`SpikeCommSubsystem` 为每个目标 block 生成 1 个 `SpikeKey`，其 `dst_node = ingress_node`，router 负责把包送到 ingress。
- **块内多播（INTRA stage）**：包到达 ingress 后 router 将 `stage=INTRA`，在 block 内按树扩散并对本地 `core_mask[cell]` 做精确投递。

### 已存在的策略点与参数（本计划只扩展 inter）
- `multicast_ingress_policy`（构建期）：`top_left/top_right/bottom_left/bottom_right/hash4`
- `multicast_inter_policy`（运行期/router，INTER）：当前支持 `xy/yx`（默认 `xy`）
- `multicast_intra_policy`（运行期/router，INTRA）：`manhattan_x_first/manhattan_y_first`（默认 `manhattan_x_first`）

### 关键文件落点（扩展 inter 只应影响这些）
- Router（INTER 走法）：`sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`
- Router 参数文档/枚举：`sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.h`
- 实验脚本透传：`experimental_features/native_multicast_lab/test_mesh_4x4_spikekey_multicast.py`
- suite 透传与统计：`experimental_features/native_multicast_lab/experiments/run_suite.py`

---

## Design Rules（约束与不变量）

1) **不改协议/不改 payload 长度**：Inter 扩展不得新增 header 字段；允许使用现有字段（`group_id/pre_global/block_id/ingress_node/block_w_h`）做确定性决策。
2) **无环保证**：Inter 走法必须保证在有限步内到达 `ingress_node`，不能产生振荡/回路。
3) **默认行为完全不变**：默认 `multicast_inter_policy=xy` 必须与当前输出一致（至少回归 suite 通过）。
4) **可复现**：相同输入（edges/seed/stop-cycle）下，策略选择应确定（推荐用 `group_id` 做 hash）。
5) **可评估**：新增策略必须能在 `run_suite.py` 中通过参数选择，并落盘 `suite_summary.json` 便于对比。

---

## Task 1: 定义“可扩展但不引入虚函数”的 Inter 策略框架

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`

**Step 1: 扩展 enum + parse**
- 在 `InterBlockRoutePolicy` 增加新值（建议先落地 1 个）：`HASH_XY`（短路径、负载均衡）
- `parseInterPolicy_()` 支持：
  - `xy`（默认）
  - `yx`
  - `hash_xy`（新增）

**Step 2: 抽出“按策略选择 next hop”的单点函数**
- 在 `routeSpikeKey_()` 的 INTER 分支里，把“选择 XY/YX”的逻辑集中到一个小函数中（switch/if），避免未来扩展到处改。

**验收点**
- `multicast_inter_policy=xy/yx` 行为保持一致（suite 通过，且无新增 fatal）。

---

## Task 2: 落地一个新 Inter 策略：`hash_xy`（推荐）

**动机（为什么先做它）**
- 不引入额外 hop（仍是最短路径），但能把“同一时刻大量包都走同一维度顺序”的热点打散。
- 实现极简，只在 INTER 阶段选择 `XY` 或 `YX`。

**算法**
- 每 hop 解码 `WireSpikeKeyV2`，计算：
  - `order = (ws.group_id ^ uint64_t(ws.pre_global) ^ uint64_t(ws.block_id)) & 1`
  - `order==0` → 走 `XY`，`order==1` → 走 `YX`
- 关键：同一个包在整个网络中 `order` 恒定（因为 `ws.*` 恒定），保证无环且收敛。

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`
- Modify: `experimental_features/native_multicast_lab/experiments/run_suite.py`（如需把 choices 扩展到 `hash_xy`）

**验收点**
- 正确性：`TrafficWorkload` 的 `sk_group missing/dup/extra/meta_mismatch==0`
- 统计落盘：`suite_summary.json` 中能够区分不同 inter policy（至少通过 tag/配置文件体现）

---

## Task 3（可选，性能对照用）: `valiant_corner` / `valiant_midpoint`（非最短路径）

**说明**
- 用“detour/中继点”刻意拉长部分路径来削峰填谷，适合在强拥塞模型下观察 tail latency 的改善。
- 不新增 header：中继点可由 `group_id` 确定性生成；是否“已到中继点”可由当前坐标判断。

**算法建议（corner 版本）**
- 根据 `h = ws.group_id & 3` 选择中继角：
  - 0:(0,0), 1:(W-1,0), 2:(0,H-1), 3:(W-1,H-1)
- 若当前 node != mid：朝 mid 走（XY 或 YX 固定一种，建议 XY）
- 否则：朝 `ingress_node` 走（XY 或 YX 固定一种）

**风险**
- hop 变长，平均延迟会升；是否收益取决于拥塞模型与 traffic 口径，需要数据判断。

---

## Task 4: 实验口径与评估计划（必须可复现）

**Files:**
- Modify: `experimental_features/native_multicast_lab/experiments/run_suite.py`（CLI choices 扩展到新增 inter policy）
- (Optional) Modify: `experimental_features/native_multicast_lab/experiments/summarize_matrix.py`（若需要把 inter policy 编进 key）

**推荐评估口径（沿用现有）**
- edges：`experimental_features/native_multicast_lab/edges/mesh4x4_c4_n64_edges_spread16.csv`
- 注入窗口：`SIM_TIME=300us`，`TRAFFIC_STOP_CYCLE=20000`（20us 注入 + drain）
- 拥塞模型：`ROUTER_SERIALIZE_ENABLE=1`，扫 `ROUTER_SERIALIZE_SERVICE_CYCLES∈{4,8,16}`
- seeds：至少 `1 2 3`

**对比维度（从 suite_summary.json 直接读）**
- NoC 负载：`routers_sum_out`、`routers_sum_fwd_xy`
- hop/路径代价：`derived.avg_rx_spikekey_hops`
- tail：`noc_lat.max_spikekey_p95/p99`，以及 `overflow_frac_delta_unicast_minus_multicast`

**Run 命令模板**
```bash
python3 "experimental_features/native_multicast_lab/experiments/run_suite.py" \
  --sim-time 300us --seeds 1 2 3 --enable-all \
  --traffic-period-cycles 200 --traffic-batch-size 1 --traffic-stop-cycle 20000 \
  --router-serialize-enable --router-serialize-service-cycles 16 \
  --ingress-policy hash4 --noc-lat-hist-max 262144 \
  --edges-csv "experimental_features/native_multicast_lab/edges/mesh4x4_c4_n64_edges_spread16.csv" \
  --inter-policy hash_xy \
  --tag "matrix_inter_hash_xy_s16"
```

---

## Task 5: 编译/安装与回归（强制）

**Build**
```bash
cd "sst_workspace/sst-elements/src/sst/elements/SnnDL" && make -j4 && make install
```

**Sanity（短口径）**
```bash
python3 "experimental_features/native_multicast_lab/experiments/run_suite.py" --tag "verify_inter_default"
python3 "experimental_features/native_multicast_lab/experiments/run_suite.py" --inter-policy yx --tag "verify_inter_yx"
python3 "experimental_features/native_multicast_lab/experiments/run_suite.py" --inter-policy hash_xy --tag "verify_inter_hash_xy"
```

**验收标准**
- `EXIT=0`
- multicast case：`sk_group missing/dup/extra/meta_mismatch==0`，`sum_sk_bad==0`
- 产物齐全：`routers.csv/cores.csv/noc_lat.csv/summary.json/suite_summary.json/sst.log`

---

## Notes（推进建议）
- 优先落地 `hash_xy`：不引入额外 hop，最容易在不牺牲平均值的情况下改善 tail。
- 若要做 `valiant_*`：建议只在“强拥塞口径”下比较，并同时观察 `avg_rx_spikekey_hops` 的上升幅度是否可接受。

