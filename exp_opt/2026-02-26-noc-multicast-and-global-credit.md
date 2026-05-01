# STORM：NoC 原生多播 × GAS 全局 credit（探索归档）

> **STORM**（Spike-**T**ile **O**ptimized **R**outing & **M**ulticast）是我们对当前 NoC 优化体系的总称：
> - **STORM-DataPlane（NoC 数据面）**：以 `SpikeKey/SpikeTileKey` 为载体，把“复制点后移到 router、树扩散共享路径、端点侧按 mask 精确投递”做成可验证的端到端机制栈。
> - **STORM-Control（控制面/协同）**：以 step/window 为粒度的 `global credit`（p0/p0b/p0c）为底座，后续计划把 NoC 遥测纳入闭环（NoC-aware global credit）。
>
> 本文档用于归档上述两条路线的 **机制、实现位置、实验矩阵与证据链**，并把 NoC 优化叙事尽量收敛成一条“可写论文”的一体化流水线。
>
> 重要边界：
> - “NoC 结构级收益”目前最 solid 的证据来自 `experimental_features/native_multicast_lab/`（专用 `MulticastRouter + MulticastNIC` 后端）。
> - `sst_dram_si/mesh_template/` 主线默认走 Merlin（`SnnDL.SnnNIC`）网络后端；未显式接入 `MulticastRouter` 时，不应把 NoC 多播树的收益直接外推到主线端到端。

---

## 0. 速览（STORM 组成 → 文件 → 证据）

### 0.1 一体化流水线（从注入到投递）

`SpikeCommSubsystem/SynapseRouteSubsystem（聚合/编码）`
→ `WireSpikeKey/TileKey（可变长/compact mask）`
→ `MulticastRouter（INTER→INTRA 阶段切换 + 路由/树复制）`
→ `local-endpoint multicast（同 PE 内 ring 直投，减少再入网）`
→ `SnnWorkload Rx fastpath（端点侧避免慢路径展开，直接 window-touch/recordEdge）`

我们把上面这一条链路统称为 **STORM-DataPlane**；其“可迁移、可写论文”的证据口径以 **byte-hops / bytes_forwarded / tail latency** 为主（见 2.6、7.x、8.x）。

| STORM 子机制 | 核心想法 | 关键实现位置（入口） | 主要实验/结果（摘要） |
| --- | --- | --- | --- |
| Blocked multicast（SpikeKey） | **按 block 聚合** + **两阶段路由（INTER→INTRA）** + **树复制** + **core mask 精确投递** | `services/synapse/route/SynapseRouteSubsystem.cc`、`services/synapse/route/SpikeCommSubsystem.cc`、`components/noc/MulticastRouter.cc` | `experimental_features/native_multicast_lab/`：在拥塞模型下 `routers_sum_out` 削减约 `~5–6×`、`p95/p99` 下降 `~2–15×`（随 service_cycles/ingress 变化） |
| Tile 聚合（SpikeTileKey） | 发送侧进一步聚合：按 `(block,ingress,block_col)` 聚合 pre 集合，发 `pre_mask` | `services/synapse/route/SpikeTileBatchEmitter.h`、`services/synapse/route/SpikeTileNocCodec.h`、`services/synapse/route/SpikeCommSubsystem.cc` | `sst_dram_si/experiments/spiketile_b_v0`：注入数可下降 1 个数量级；NoC 树形收益以 `MulticastRouter` 后端证据为准 |
| InterBundle V2 | **INTER 阶段跨 block 子包合并**，router 按方向分裂，减少重复注入/重复转发 | `services/synapse/route/SpikeInterBundleCodec.h`、`components/noc/MulticastRouter.cc` | `NoCexp`：在同等 workload 下显著压降 `routers_sum_byte_hops` / `nics_sum_tx_bytes`（见 7.7） |
| compact mask + byte-aware | `core_mask/pre_mask` 变短必须在 NoC 模型中“按字节计服务”才会反映到 tail | `components/noc/MulticastRouter.{h,cc}`、`components/noc/MulticastRouterConfig.h` | `NoCexp + 主线口径`：在包数不变时 `payload_bytes_sent/total_bytes_sent` 大幅下降，并带来 `sim_time` 收益（见 2.7） |
| local-endpoint multicast | block 内投递尽量留在芯片内 ring，避免“本地复制再入网” | `services/noc/NocSubsystem.{h,cc}` + ring | `NoCexp`：与 InterBundle/compact 叠加后形成“结构性大收益”证据链（见 7.7、8.8） |
| Rx fastpath | 端点侧避免“Key→大量 SpikeEvent”的慢路径展开，直接 window-touch/recordEdge | `services/workload/snn/SnnWorkload.cc` | `deep_debug_steps2 (n=3)`：host wallclock 明显下降，模型内指标不变 |
| STORM-Control：global credit（p0/p0b/p0c） | step 级全局控制：依据遥测对下一步分配 Apply bank credit（降低 tail / barrier 等待） | `components/gas/GlobalGasStepController.cc` + `components/MultiCorePE.cc` + `components/GatherBufferIF.cc` | dense microbench：当前 **未观察到稳定正收益**（部分 case 退化）；下一步应引入 NoC 遥测做 NoC-aware 闭环（见 §9 设计草案） |

---

## 1. NoC 优化路线：SpikeKey blocked multicast

### 1.1 原理（为什么能在体系结构层面减负载/降尾延迟）

**目标问题**：SNN fanout 大时，unicast(Spike) 会把同一语义（同一 pre spike）复制为大量包，导致：
- 注入包数与 fanout 近似线性；
- 相同路径段被重复占用，链路/路由器队列拥塞；
- tail latency（`p95/p99`）在拥塞下恶化。

**SpikeKey blocked multicast** 的核心是把“复制点后移 + 路径共享”：
- **按 block 聚合**：对每个目标 block，仅注入 1 个 `SpikeKey` 包；
- **两阶段路由**：
  - `INTER`：块间 **单播** 到该 block 的 `ingress_node`；
  - `INTRA`：包到达 ingress 后，在 block 内 **按树扩散复制**，并按 `core_mask[cell]` 精确投递到 cores；
- **复制发生在更靠近目的地的路由器**：减少跨 block 的重复流量，拥塞更不容易被放大。

### 1.2 协议/载体（固定 payload，兼容演进）

- 包类型：`events/NocPacketEvent(kind=SpikeKey)`（或 `SpikeTileKey`）
- 路由头：`services/synapse/route/SpikeNocCodec.h::WireSpikeKeyV2`
  - `stage`：`0=INTER`，`1=INTRA`
  - `block_w_h`：`(w<<8)|h`，并要求 `w*h <= 64`
  - `block_id`：block 索引（按 mesh / block 划分）
  - `ingress_node`：目标 block 的 ingress（构建期决定）
  - `group_id`：一次仿真运行内“每次发射唯一”（用于 traffic 自检/覆盖聚合）
  - `core_mask[64]`：block 内每个 cell（node/PE）的 32-bit core bitmask
- 上限约束集中在：`api/MulticastLimits.h`
  - `kMaxMulticastBlockCells=64`（≤8×8）
  - `kMaxCoresPerPe=32`

### 1.3 构建期：multicast targets（“按 pre_global 构建 block+mask”）

构建期发生在 **Synapse/Route 子系统**（仍保持 fanout 语义不变，仅新增一条可选 fast path）：

- 目标表结构：`SynapseRouteSubsystem::MulticastTargetMap`
  - key：`pre_global`
  - value：`vector<BlockTarget{block_id, ingress_node, core_mask[64]}>`
- 关键代码：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.cc`
    - `initMulticastTargets_()`：由 `routes_shared_`（权重驱动路由表）构建 targets，并走进程级 cache
    - `selectIngressNodeBlocked_()`：`multicast_ingress_policy`（`top_left/.../hash4`）
    - `computeMulticastTargets()`：运行期查询 + gating 过滤（基于 `block_id→base node` 推导，避免 ingress policy 假设）

### 1.4 运行期发送：SpikeCommSubsystem 选择 SpikeKey fast path

- 关键代码：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
    - `emitCommon_()`：
      - `if (sr->multicastEnabled() && computeMulticastTargets(...))`：
        - 为每个 `BlockTarget` 发一个 `NocPacketEvent(kind=SpikeKey)` 到 `ingress_node`
        - `group_id = (emit_seq<<32) | pre_global`（避免 XOR 周期性重复）
      - 否则回退到 unicast `SpikeEvent` fanout

### 1.5 运行期路由：MulticastRouter 两阶段（INTER→INTRA）+ 子树裁剪复制

- 关键代码：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`
    - `handlePacket_()`：`SpikeKey/SpikeTileKey` 走 `routeSpikeKey_()`，其余包走 `routeUnicastXY_()`
    - `routeSpikeKey_()`：
      - `stage=INTER`：到 ingress 前按 `multicast_inter_policy`（`xy/yx/hash_xy`）单播
      - ingress 处切 `stage=INTRA`：在 block 内按 Manhattan 树扩散
      - **子树裁剪**：仅当“子树内存在任一接收者”（扫描 `core_mask[]`）才 clone 转发
      - 本地投递：按 `core_mask[idx_self]` 的 bitset clone 到多个 core endpoint
    - `finish()`：打印 `[mcast-router] ... stage_inter/stage_intra/clones` 等统计（runner 解析落盘）

> 语义护栏：`services/noc/NocSubsystem.cc::sendFromCore()` 强制 `SpikeKey/SpikeTileKey` 必须走外部 NIC/router mesh（否则会被 PE 内 ring 直投绕过 INTRA 复制，产生“看似收到但不是多播”的语义漂移）。

### 1.6 结果（solid）：native_multicast_lab 的 NoC 负载与 tail latency 改善

最关键的“体系结构级证据链”来自 `experimental_features/native_multicast_lab/`：

- 实验后端：`MulticastRouter + MulticastNIC`（非 Merlin）
- 工作负载：`workload_impl="traffic"`（只验证通信/路由闭环，不引入 GAS/memHierarchy）
- 正确性：`sk_group` 覆盖自检（`missing/dup/extra/meta_mismatch==0`）
- 拥塞模型：`router` 输出端口串行化（`router_serialize_enable=1` + `service_cycles` 扫描）

矩阵口径（示例）：
```bash
python3 "experimental_features/native_multicast_lab/experiments/run_suite.py" \
  --sim-time 300us --seeds 1 2 3 --enable-all \
  --traffic-period-cycles 200 --traffic-batch-size 1 --traffic-stop-cycle 20000 \
  --router-serialize-enable --router-serialize-service-cycles 16 \
  --ingress-policy hash4 --noc-lat-hist-max 262144 \
  --edges-csv "experimental_features/native_multicast_lab/edges/mesh4x4_c4_n64_edges_spread16.csv" \
  --tag "matrix_example"
```

已记录的主要观测（均为 `unicast/multicast` 比值；>1 表示多播更优）：
- **NoC 负载削减**：
  - `routers_sum_out` ≈ `~4.98×~5.79×`
  - `routers_sum_fwd_xy` ≈ `~6.46×~7.27×`
- **Tail latency 改善**（强拥塞更显著）：
  - `service_cycles=16`：`p95 ≈ 2.43× (top_left)` / `3.16× (hash4)`；`p99 ≈ 2.36×` / `3.04×`
  - `service_cycles=8`：`p95 ≈ 3.92× (top_left)` / `5.30× (hash4)`
  - `service_cycles=4`：`p95 ≈ 6.43× (top_left)` / `14.84× (hash4)`

---

## 2. NoC 优化路线：SpikeTileKey（发送侧聚合，实验路径）

### 2.1 原理与动机

SpikeKey 已把“一个 pre 的 fanout”压到“触达的 block 数”。SpikeTileKey 进一步试图压缩 **发送端注入事件数**：
- 在一个发射 batch 内，将多个 `pre_global` 聚合到一个包里（以 `pre_mask` 表示），减少发送端构造/注入开销。

### 2.2 协议设计（保持 router 兼容）

- `services/synapse/route/SpikeTileNocCodec.h::WireSpikeTileKeyV1`
  - **前缀保持 `WireSpikeKeyV2` 完整可解码**（router 仍按 SpikeKey 字段路由/复制）
  - tail：`block_col + pre_mask(<=64bit)`
  - `route_mode=2` 区分 SpikeTileKey

### 2.3 关键实现位置

- 发送侧聚合器（核心逻辑）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeTileBatchEmitter.h`
    - 按 `(block_id, ingress_node, block_col)` 聚合：OR `pre_mask` + OR `core_mask[64]`
- 发射入口：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
    - `emitSpikeTileBatchExperimental_()`：在 `experimental_spiketile_enable` 下走 tile emitter
- 接收侧展开（workload）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
    - `deliverPacket()`：解析 tile，`collectPreGlobals()` 得到多个 `pre_global`，逐个走 fastpath/fallback

### 2.4 当前证据与限制

- 机制层“注入包数下降”在探针里可观察（例如 `tx_spikekey` 量级到 `tx_spiketilekey` 量级差一个数量级）。
- 但 **端到端 NoC 树复制收益**需要在 `MulticastRouter` 后端下复验（主线 Merlin 后端未必复现 INTRA 复制语义）。

### 2.5 P0-compact：`core_mask` 变长紧凑编码（V3）

#### 机制
- 问题：`WireSpikeKeyV2` 固定携带 `core_mask[64]`，2x2 block 只用 4 个 cell 仍发送 64 个 mask words（头部浪费大）。
- 做法：
  - 新增 `SpikeKey V3`：`固定前缀 + core_mask[block_cells]`（`block_cells=block_w*block_h`）。
  - `SpikeTileKey` 新增 compact 变体：`V3 route + tile tail`（tail 仍保留 `block_col + pre_mask` 语义）。
  - router ingress `INTER->INTRA` 切换改为 **stage 字段原位 patch**，不再重编码固定 V2 头，避免 tail 丢失与“回胖包”。
- 兼容：
  - `decodeSpikeKeyAny()` 扩展到 V1/V2/V3；
  - `SpikeTileNocCodec::decode()` 同时支持旧定长与新变长；
  - 默认关闭，仅在 `experimental_compact_mask_enable=1` 时发 compact payload。

#### 实现位置
- 编解码：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeNocCodec.h`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeTileNocCodec.h`
- 发送路径（B/C）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.{h,cc}`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeTileBatchEmitter.h`
- 接收/校验路径：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.{h,cc}`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.{h,cc}`
- 配置链路：
  - `sst_dram_si/experiments/spiketile_b_v0/runtime.py`
  - `sst_dram_si/experiments/spiketile_b_v0/build.py`
  - `sst_dram_si/experiments/spiketile_b_v0/run_spiketile_compare_matrix.sh`

### 2.6 Byte-aware 路由序列化（观测 compact 的必要条件）

- 新增 `MulticastRouter` 可选字节序列化：
  - `serialize_output_byte_enable`
  - `serialize_bytes_per_cycle`
  - `serialize_header_bytes`
- 服务时间从常数 `serialize_service_cycles` 扩展为：
  - `ceil((header_bytes + payload_bytes) / bytes_per_cycle)`
- 目的：让 payload 变短能够真实反映到端口排队与 tail latency，而不是“按包等价”被吞没。
- 实现：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.{h,cc}`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouterConfig.h`

### 2.7 实验结论（P0-compact 已工作，且收益明确）

#### A) `MulticastRouter` 后端（NoCexp，3 seeds）
- 路径：`NoCexp/spiketile_router_lab/runs/20260227-024509_compactmask_v3_matrix3/`
- 条件：`router_serialize_enable=1 + router_serialize_byte_enable=1`
- 正确性：全部 case `ok=true`；`tile_bad_decode=0`；`sk_group bad/missing/extra/dup/meta_mismatch=0`。
- 关键结果（均值）：
  - `B -> B_compact`：`p95 108894 -> 12186`（`-88.81%`），`p99 112159 -> 13339`（`-88.11%`）
  - `C -> C_compact`：`p95 115135 -> 19164`（`-83.36%`），`p99 118622 -> 21181`（`-82.14%`）
  - `routers_sum_out` 不变（`243292`）：说明收益来自 **同包数下每包更短**，不是包数变化。

#### B) 反证对照（仅按包序列化）
- 路径：`NoCexp/spiketile_router_lab/runs/20260227-031105_compactmask_v3_packet_only_seed1/`
- 条件：`router_serialize_enable=1`，但 `router_serialize_byte_enable=0`
- 结果：`B/C` 的 compact 与 baseline 在 `p95/p99/routers_sum_out` 完全一致。
- 结论：若 NoC 仅按包建模，compact mask 不会体现在 tail latency；byte-aware 建模是必要观测前提。

#### C) 10k BCSR 标准口径（Merlin + GAS，step=1）
- 路径：
  - `sst_dram_si/experiments/spiketile_b_v0/outputs/compactmask_v3/B_base/20260227-025828/`
  - `sst_dram_si/experiments/spiketile_b_v0/outputs/compactmask_v3/B_compact/20260227-030319/`
  - `sst_dram_si/experiments/spiketile_b_v0/outputs/compactmask_v3/C_base/20260227-030541/`
  - `sst_dram_si/experiments/spiketile_b_v0/outputs/compactmask_v3/C_compact/20260227-030734/`
- 正确性：四组 `validation SUMMARY fail=0`，且 `route_misses_total=0`、`local_drops_total=0`。
- 指标：
  - `B`：`sim_time_actual_ns 763429 -> 289235`（`-62.11%`），`packets_sent` 不变（`378039`），
    `payload_bytes_sent 95,587,160 -> 19,251,080`（`-79.86%`），`total_bytes_sent -72.94%`。
  - `C`：`sim_time_actual_ns 155045 -> 111260`（`-28.24%`），`packets_sent` 不变（`87,176`），
    `payload_bytes_sent 9,926,976 -> 3,398,016`（`-65.77%`），`total_bytes_sent -54.32%`。
- 解释：在主线口径中，compact 不改变语义/包数，但显著降低字节流量并带来端到端时间收益。

### 2.8 P1-inter-bundle：跨 block 目的集多播（B/C 一次性实现）

#### 机制
- 目标：把 `INTER` 阶段从“每个目标 block 一包”改为“一个 bundle 携带多个目标 block 子包”，在路由器内按方向分裂，减少重复注入与重复转发。
- 发送端：
  - B（SpikeKey）与 C（SpikeTileKey）在开启 `experimental_inter_bundle_enable=1` 时，先按原路径生成每个 block 的子 payload，再封装为 `InterBundle`。
  - 通过 `experimental_inter_bundle_max_entries` 控制每个 bundle 的 entry 数（超出则分片发多个 bundle）。
- 路由端：
  - `MulticastRouter` 在 `routeSpikeKey_()` 先识别 bundle payload；
  - 对 bundle 中每个 entry 读取 `ingress_node`，按当前节点坐标做 `XY/YX/hash_xy` 下一跳分组；
  - 对 `N/S/E/W` 方向各发一个“裁剪后的 bundle 子集”；
  - 对 `Local`（到达 ingress）的 entry，将 stage 原位 patch 到 `INTRA` 并复用现有 block 内树扩散逻辑。

#### 实现位置
- 新增编解码：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeInterBundleCodec.h`
- 发送链路（B/C）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.{h,cc}`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeTileBatchEmitter.h`
- 路由链路：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.{h,cc}`
- 参数透传：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.{h,cc}`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.{h,cc}`
  - `NoCexp/spiketile_router_lab/test_mesh_4x4_key_tile_multicast.py`
  - `NoCexp/spiketile_router_lab/experiments/run_suite.py`
  - `sst_dram_si/experiments/spiketile_b_v0/runtime.py`
  - `sst_dram_si/experiments/spiketile_b_v0/build.py`
  - `sst_dram_si/experiments/spiketile_b_v0/run_spiketile_compare_matrix.sh`

#### 实验（NoCexp，3 seeds）
- byte-aware 开启：
  - 路径：`NoCexp/spiketile_router_lab/runs/20260227-035115_interbundle_matrix3/`
  - 命令关键参数：`--inter-bundle-variants --inter-bundle-max-entries 32 --router-serialize-enable --router-serialize-byte-enable`
- packet-only（反向口径）：
  - 路径：`NoCexp/spiketile_router_lab/runs/20260227-040330_interbundle_packetonly_matrix3/`
  - 命令关键参数：`--inter-bundle-variants --inter-bundle-max-entries 32 --router-serialize-enable`（不启用 byte-aware）
- 正确性：两组矩阵全部 case `ok=true`，`validation_errors=0`，`tile_bad_decode=0`。

#### 结果与解读
- B/C 均观察到一致结构性收益：
  - 发送侧 key/tile 包数：`25600 -> 6400`（`-75%`）
  - 网络转发包量：`routers_sum_out 243292 -> 222446`（`-8.57%`）
- 延迟层面（当前参数下）：
  - byte-aware：`p95` 基本持平（约 `-0.03% ~ -0.05%`），`p99` 略有波动（约 `+0.18%`）
  - packet-only：`p95` 小幅下降（约 `-1.2%`），`p99` 基本持平（约 `+0.06%`）
- 结论：
  - `P1-inter-bundle` 在“降注入数/降网络包量”上已明确生效（且 B/C 同时生效）；
  - 但当前参数点上端到端 tail latency 改善有限，下一步需要与 compact/byte-aware 联合调参（如 bundle entry 上限、traffic burst、serialize 参数）进一步放大收益。

### 2.9 `compact × inter-bundle` 联合消融（B/C，3 seeds）

#### 实验设置
- byte-aware：
  - 路径：`NoCexp/spiketile_router_lab/runs/20260227-132308_interbundle_compact_matrix3/`
  - 参数：`--compact-variants --inter-bundle-variants --router-serialize-byte-enable`
- packet-only：
  - 路径：`NoCexp/spiketile_router_lab/runs/20260227-134430_interbundle_compact_packetonly_matrix3/`
  - 参数：`--compact-variants --inter-bundle-variants`（不启用 byte-aware）
- 两组均：`27 cases = 9 variants × 3 seeds`，全部 `ok=true`，`validation_errors=0`，`tile_bad_decode=0`。

#### 结果（关键对比）
- 在 byte-aware 下：
  - `B_base -> B_compact`：`p95 -88.81%`，`p99 -88.11%`
  - `B_base -> B_bundle`：`tx_pkts -75%`，`routers_sum_out -8.57%`，`p95/p99` 近似持平
  - `B_base -> B_bundle_compact`：同时获得
    - `p95 -88.63%`，`p99 -88.23%`
    - `tx_pkts -75%`，`routers_sum_out -8.57%`
  - `C` 路径同趋势：
    - `C_base -> C_compact`：`p95 -83.36%`，`p99 -82.14%`
    - `C_base -> C_bundle`：`tx_pkts -75%`，`routers_sum_out -8.57%`，延迟近似持平
    - `C_base -> C_bundle_compact`：`p95 -83.27%`，`p99 -82.24%`，并保持 `tx_pkts -75%` 与 `routers_sum_out -8.57%`
- 在 packet-only 下：
  - `compact` 与 baseline 的 `p95/p99` 完全一致（B/C 均 0% 变化）；
  - `bundle_compact` 与 `bundle` 的 `p95/p99` 也完全一致；
  - `bundle` 仍保持 `tx_pkts -75%`、`routers_sum_out -8.57%`。

#### 结论
- `compact` 负责“降每包字节”，其尾延迟收益依赖 byte-aware 建模；
- `inter-bundle` 负责“降注入包数/降网络包量”，对是否 byte-aware 不敏感；
- `bundle_compact` 在 byte-aware 下实现了两类收益的叠加：**包量下降 + 尾延迟显著下降**，且 B/C 一致生效。

### 2.10 新增体系结构指标：`bytes_forwarded / byte_hops`（Router）+ `tx/rx_bytes`（NIC）

#### 为什么要补这组指标
- 仅看 `packets` 会把“包大小变化”隐藏掉：例如 `inter-bundle` 会显著减包，但每包可能更大；是否真正降低链路搬运量，需要 `bytes` 口径才能定论。
- 论文叙事需要把 P1 从“注入次数减少”推进到“链路占用/总搬运量变化”。

#### 口径定义（本次实现）
- Router（`[mcast-router]`）新增：
  - `bytes_in / bytes_out / bytes_local / bytes_fwd_xy / byte_hops`
  - 统一按 `packet_bytes = serialize_header_bytes + payload.size()` 计（与 byte-aware 服务时间口径一致）。
  - `byte_hops` 当前定义为“每次路由端口发送累计的 byte-hop”（按 hop 逐跳累加）。
- NIC（`[mcast-nic]`）新增：
  - `tx_pkts / tx_bytes / rx_pkts / rx_bytes`
  - `tx/rx_bytes = stats_header_bytes + payload.size()`（实验中与 router header 字节保持一致）。

#### 实验与数据
- 运行命令（稳定参数）：
```bash
python3 NoCexp/spiketile_router_lab/experiments/run_suite.py \
  --sst-bin /home/xgy/remote/sst_install_mpi/bin/sst \
  --sim-time 300us --seeds 1 --enable-all \
  --traffic-period-cycles 200 --traffic-batch-size 1 --traffic-stop-cycle 20000 \
  --router-serialize-enable --router-serialize-byte-enable \
  --router-serialize-bytes-per-cycle 16 --router-serialize-header-bytes 24 \
  --edges-csv experimental_features/native_multicast_lab/edges/mesh4x4_c4_n64_edges_spread16.csv \
  --compact-variants --inter-bundle-variants --inter-bundle-max-entries 64 \
  --tag bytehops_matrix_stable
```
- 输出目录：`NoCexp/spiketile_router_lab/runs/20260227-143543_bytehops_matrix_stable/`
- 正确性：`9/9 case ok=true`，`validation_errors=0`，`tile_bad_decode=0`，`sk_group bad/missing/extra/dup/meta_mismatch=0`。

#### 关键观测（P1 从“减包”到“减字节”的证据）
1) `inter-bundle`（B/C）：
- **减包成立**：
  - `nics_sum_tx_pkts: 25600 -> 6400`（`-75%`）
  - `routers_sum_out: 243320 -> 222461`（`-8.57%`）
  - `routers_sum_fwd_xy: 140920 -> 120061`（`-14.80%`）
- **但字节不降反升（本参数点）**：
  - B：`routers_sum_bytes_fwd_xy: 45,094,400 -> 45,888,528`（`+1.76%`）
  - C：`routers_sum_bytes_fwd_xy: 47,349,120 -> 48,143,248`（`+1.68%`）
- **延迟几乎持平**：`p95` 约 `-0.05%`，`p99` 约 `+0.12%~+0.17%`。

2) `compact`（B/C）：
- **包数不变**（`routers_sum_out/fwd_xy` 不变）；
- **字节显著下降**：
  - B：`routers_sum_bytes_fwd_xy -75.00%`；
  - C：`routers_sum_bytes_fwd_xy -71.43%`；
- **尾延迟同步大幅下降**：
  - B：`p99 -88.10%`；
  - C：`p99 -82.10%`。

3) `bundle_compact`（B/C）：
- 在 `bundle` 基础上保持减包，并把字节拉低到与 compact 同量级：
  - B：`bundle -> bundle_compact` 的 `routers_sum_bytes_fwd_xy -73.70%`，`p99 -88.22%`
  - C：`bundle -> bundle_compact` 的 `routers_sum_bytes_fwd_xy -70.25%`，`p99 -82.23%`

#### 结论（对 ISCA 叙事的直接价值）
- 新增 `bytes_forwarded/byte_hops` 后，证据链更完整：  
  **P1(inter-bundle) 在当前配置下“减包 ≠ 减字节”**，因此单看 packet 指标会高估网络收益。
- 当前最强的体系结构收益仍来自 **compact/byte-aware**（降低每 hop 字节搬运，直接转化为 queueing/tail 收益）。
- 论文叙事建议：
  - 把 P1 定位为“控制面/注入面减压能力（pkts）”；
  - 把 compact 定位为“链路占用减压能力（bytes/byte-hops）”；
  - 把 `bundle_compact` 定位为两者联合，分别优化“包数维度”和“字节维度”。

---

## 3. Rx fastpath（P0）：Key/Tile 包端点处理加速（仿真执行成本收益）

### 3.1 原理

在 window-read + GAS 的工作模式下，`SpikeKey/SpikeTileKey` 的语义可以在端点侧直接落到：
- `noteWindowTouch(post_local, pre_global, ...)`
- `recordEdge(post_local, pre_global)`

避免创建大量 `SpikeEvent` 并经过慢路径队列/排序，从而降低 host wallclock（不改变模型内时序/统计）。

### 3.2 实现位置与开关

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
  - 参数：`experimental_spikekey_fastpath_enable`（默认 0）
  - 统计：`snn_rx_fastpath_packets_total / snn_rx_fallback_packets_total / snn_rx_fastpath_posts_total / ...`
  - fastpath 核心：`expandPreGlobalToWindowEdgesFast_()`

### 3.3 实验结果（deep_debug_steps2，n=3）

在 `sst_dram_si/experiments/spiketile_b_v0/outputs/deep_debug_steps2/analysis_latest/` 的聚合中：
- 模型内指标（`sim_time_actual_ns/memory_bytes/memctrl_bytes_est_total`）组内 `std=0`（功能等价）
- P0 语义切换稳定：
  - `B: fastpath=0,fallback=318067` → `B+P0: fastpath=318067,fallback=0`
  - `C: fastpath=0,fallback=27204` → `C+P0: fastpath=27204,fallback=0`
- host wallclock（mean, n=3）：
  - `B=453.92s`，`B+P0=329.64s`（`-27.38%`）
  - `C=146.48s`，`C+P0=138.12s`（`-5.71%`）

---

## 4. Credit 路线（GAS Apply bank credit）：local 与 global

### 4.1 背景（credit 的物理含义）

这里的 “credit” 指 `apply_bank_credit`（GatherBufferIF 的 Apply 阶段并发额度）：
- `apply_bank_credit=0`：不限制每 bank 的 active granule 数（更像“只受 inflight/后端限制”）
- `apply_bank_credit>0`：对每个 bank 的并发做硬上限（可能减少 bank thrash，但也可能把吞吐节流成近似串行）

这条路线的初衷是：在 DRAM backend 下，**通过控制 Apply 并发来降低尾部（row-miss/busy-wait）**，进而降低 step barrier 等待。

### 4.2 控制面链路（controller → PE → core → GatherBufferIF）

**(1) 全局控制器产生 per-PE credit target**
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/gas/GlobalGasStepController.cc`
  - 在 `PE_DONE(completed_seq)` 时计算 `next_seq` 的 `pe_next_apply_bank_credit_[i]`
  - 通过 `START_STEP(seq)` 消息携带 `apply_bank_credit_target`

**(2) PE 在 beginGlobalStep 广播到 cores（窄钩子）**
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
  - `beginGlobalStep_()`：若 `global_step_active_apply_bank_credit_target_>0`，调用 core 的 `IGlobalStepCreditHooks`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/IGlobalStepCreditHooks.h`
  - `onGlobalStepApplyBankCredit(seq, credit)`

**(3) core 在 openStep 前下发到 memory（窄接口）**
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
  - `onGlobalStepApplyBankCredit()`：先缓存 `(seq,target)`
  - `onGlobalStepStart()`：调用 `IGasCreditGate::setApplyBankCreditTarget(seq,target)`，再 `gate->openStep(seq)`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/IGasCreditGate.h`

**(4) GatherBufferIF 在 step 边界生效**
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/GatherBufferIF.cc`
  - `setApplyBankCreditTarget()`：记录 pending
  - `openStep()`：在窗口边界将 external target 应用到 `apply_bank_credit_dyn_`

### 4.3 策略版本（p0 / p0b / p0c）

> 统一原则：均保持主线默认关闭，仅通过 env 显式开启（便于回归与隔离）。

- **p0（naive top-k→credit_max）**：对 top-k “关键 PE”上调到 `credit_max`，其余维持 `credit_min`（不做预算守恒）
  - runner：`sst_dram_si/tools/isolated_noc_gas_global_credit_p0/run_dense_microbench_4x4_cmd_aware_ablation_global_credit_p0.sh`
- **p0b（预算守恒）**：以 `base_credit` 为基线，对 top-k raise 到 `credit_hi`，并对非关键 PE drop 到 `credit_lo`，严格保持 `sum(credit)=N*base_credit`
  - policy helper：`components/gas/experimental/P0BCreditPolicy.h`
  - runner：`sst_dram_si/tools/isolated_noc_gas_global_credit_p0b/run_dense_microbench_4x4_cmd_aware_ablation_global_credit_p0b.sh`
- **p0c（预测驱动的 p0b）**：用 next-step activation predictor 预测下一步负载，减少“追噪声/振荡”
  - predictor：`components/gas/experimental/StepActivationPredictor.h`
  - runner：`sst_dram_si/tools/isolated_noc_gas_global_credit_p0c_pred/run_dense_microbench_4x4_cmd_aware_ablation_global_credit_p0c_pred.sh`

### 4.4 开关与注入位置（mesh_template）

全局控制器的 credit 参数通过 `sst_dram_si/mesh_template/build.py::build_global_gas_step_controller()` 从 env 注入：
- `MESH_GLOBAL_CREDIT_CTRL_ENABLE`
- `MESH_GLOBAL_CREDIT_CTRL_MODE`（`0=p0`/`1=p0b`/`2=p0c_pred`）
- `MESH_GLOBAL_CREDIT_CTRL_CREDIT_MIN / _CREDIT_MAX / _TOP_K`
- p0b：`MESH_GLOBAL_CREDIT_CTRL_BASE_CREDIT / _APPLY_RATIO_MIN_PERMILLE / _RANK_BY_APPLY`
- p0c_pred：`MESH_GLOBAL_CREDIT_CTRL_PRED_SEED / _PRED_FRACTION / _PRED_NEURONS_PER_PE / _PRED_FANOUT`

### 4.5 实验结果（dense microbench，当前结论：未见稳定正收益）

**p0（naive top-k）**：参数极敏感且未带来收益
- r4（过低 credit，灾难性退化）：
  - `sim_ns`: `531690 -> 1871812`（`+252.0%`）
  - `apply_ns_avg`: `75442.9 -> 274185.2`（`+263.4%`）
  - `apply_credit_eff_avg`: `0.0 -> 1.1875`（把并发压到近似 1）
- r5（调高 credit，退化收敛但仍无收益）：
  - `sim_ns`: `+4.83%`
  - `barrier_wait_proxy_total_ns`: `+4.71%`

**p0b（预算守恒）**：摆幅大时明显退化；摆幅小时接近 baseline，但仍未见正收益
- Case1：`frac=0.05 base=8 lo/hi=4/12`
  - `sim_ns`: `+11.66%`
  - `apply_p99_ns`: `+14.79%`
  - `barrier_wait_proxy_total_ns`: `+14.50%`
- Case2：`frac=0.005 base=4 lo/hi=1/8`
  - `sim_ns`: `+57.60%`
  - `barrier_wait_proxy_total_ns`: `+98.76%`（振荡/追噪声显著）
- Case3（tune）：`frac=0.05 base=8 lo/hi=7/9`
  - `sim_ns`: `+0.32%`（几乎持平）
  - `barrier_wait_proxy_total_ns`: `+0.44%`

**p0c_pred（预测驱动）**：显著抑制 p0b 的极端退化，但仍无稳定正收益
- Case1：`frac=0.05 base=8 lo/hi=4/12`
  - `sim_ns`: `+8.75%`
  - `barrier_wait_proxy_total_ns`: `+11.76%`
  - `apply_p99_ns`: `-10.57%`（Apply tail 变好，但 barrier 变差抵消）
- Case2：`frac=0.005 base=4 lo/hi=1/8`
  - `sim_ns`: `+7.87%`
  - `barrier_wait_proxy_total_ns`: `+5.97%`

### 4.6 现阶段解释（为什么“看起来合理”但收益难拿）

- `apply_bank_credit` 同时影响 **吞吐** 与 **bank 冲突/尾部**：盲目 raise/ drop 可能把某些 PE 变成下一步 straggler，放大 step-level spread。
- 对称/近似 i.i.d 的 microbench 上，“重新分配 credit 的可用增益窗口很窄”：摆幅稍大就进入振荡/退化区。
- p0c 仅预测“哪个 PE 更忙”（sources_selected）仍不足：是否 raise/clamp 更取决于 bank/row 冲突结构与 busy-wait 贡献。

---

## 5. 联合优化（NoC multicast × global credit）：面向下一步的闭环方向

当前已具备两块积木：
1) **NoC 多播数据面**（SpikeKey blocked multicast 的 router 树复制能力）
2) **GAS credit 控制面**（GlobalGasStepController 能算出 per-PE target，并通过 step hooks 送到 GatherBufferIF）

下一步体系结构创新点（已在 `TECH_PROGRESS.md` 记录的 p1/p2 方向）可按以下收敛：

- **p1：把 credit update/permit 作为 NoC multicast 控制面下发**
  - 定义一种轻量 `ControlKey` payload（或复用 `NocPacketKind::Control`）
  - 目标集合按 block 编码为 mask，通过 `MulticastRouter` 的 blocked multicast 快速下发
  - 评估：控制面 packet/byte/hop 开销 vs unicast 下发；以及对 step tail 的净收益

- **p2：将 credit 与注入节奏联动（phase co-scheduling）**
  - 以 memory pressure / busy-wait 遥测反馈来调节 spike multicast 注入节奏或阶段对齐
  - 目标：减少“网络拥塞×内存拥塞”叠加导致的尾部抖动（min max / min barrier 而非 min mean）

---

## 6. 复现入口清单（最常用）

- NoC 多播（solid 证据链）：`experimental_features/native_multicast_lab/`
  - 最小跑通：`test_mesh_4x4_spikekey_multicast.py`
  - 矩阵与落盘：`experiments/run_suite.py`、`experiments/summarize_matrix.py`
- SpikeTileKey + Rx fastpath：`sst_dram_si/experiments/spiketile_b_v0/`
- 全局 credit（p0/p0b/p0c_pred）隔离 runner：
  - `sst_dram_si/tools/isolated_noc_gas_global_credit_p0/`
  - `sst_dram_si/tools/isolated_noc_gas_global_credit_p0b/`
  - `sst_dram_si/tools/isolated_noc_gas_global_credit_p0c_pred/`

---

## 7. 2026-02-27 落地结果：InterBundle V2 × Local Endpoint Multicast

本节记录“推荐方案”完整落地后的实现与对比结论（3 seeds，全矩阵 27 cases × 2 组）。

### 7.1 实现点（默认关闭，显式开关）

1) **InterBundle V2（P1 从减包推进到减字节）**
- 编解码：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeInterBundleCodec.h`
- 发送侧：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeTileBatchEmitter.h`
- 路由器侧（V1+V2 双栈）：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`
  - `routeSpikeInterBundle_()` 支持 `decodeVersion -> V1/V2 分支`、按方向分组重打包、本地 entry 重建后复用 `routeSpikeKey_()`

2) **Router->NIC 本地端点多播（减少本地 clone）**
- 协议 tail：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/LocalEndpointMulticastCodec.h`
- Router 端单包下发 endpoint mask：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`
- NIC 端展开为 endpoint 单播：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastNIC.cc`
- 参数：
  - `local_endpoint_multicast_enable`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouterConfig.h`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastNICConfig.h`

3) **实验开关链路**
- `experimental_inter_bundle_v2_enable`：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.{h,cc}`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/traffic/TrafficWorkload.{h,cc}`
- 环境变量透传：
  - `NoCexp/spiketile_router_lab/test_mesh_4x4_key_tile_multicast.py`
  - `NoCexp/spiketile_router_lab/experiments/run_suite.py`
- 新汇总字段：
  - `routers_sum_local`
  - `routers_sum_bytes_local`

### 7.2 对比实验配置

- baseline（off）：
  - `python3 NoCexp/spiketile_router_lab/experiments/run_suite.py --sst-bin /home/xgy/remote/sst_install_mpi/bin/sst --sim-time 300us --seeds 1 2 3 --compact-variants --inter-bundle-variants --tag v2_localoff_matrix`
  - 输出：`NoCexp/spiketile_router_lab/runs/20260227-154846_v2_localoff_matrix/`
- new（on）：
  - `python3 NoCexp/spiketile_router_lab/experiments/run_suite.py --sst-bin /home/xgy/remote/sst_install_mpi/bin/sst --sim-time 300us --seeds 1 2 3 --compact-variants --inter-bundle-variants --inter-bundle-v2-enable --local-endpoint-multicast-enable --tag v2_localon_matrix_rerun`
  - 输出：`NoCexp/spiketile_router_lab/runs/20260228-035338_v2_localon_matrix_rerun/`
- 正确性：
  - 两组均 `27/27` case 通过，`validation_errors=0`

### 7.3 关键结论（体系结构口径）

**A. 全矩阵总量（27 cases 汇总）**
- `routers_sum_bytes_fwd_xy`: `36,332,448 -> 26,217,168`（`-27.84%`）
- `routers_sum_bytes_local`: `22,987,584 -> 12,341,312`（`-46.31%`）
- `routers_sum_byte_hops`: `59,320,032 -> 38,558,480`（`-35.00%`）
- `nics_sum_tx_bytes`: `11,618,720 -> 8,173,744`（`-29.65%`）
- `routers_sum_local`: `125,340 -> 71,324`（`-43.10%`）
- `p95/p99`: 本参数点持平（`41 -> 41`）

**B. 机制拆解**
- `local_endpoint_multicast` 的直接效果（无 bundle 的 B/C）：
  - `routers_sum_local` 均 `-50%`
  - `routers_sum_bytes_local` 约 `-48.8%`
  - `routers_sum_byte_hops` 约 `-19.5%`
- `InterBundle V2` 的核心效果（bundle 的 B/C）：
  - `B_spikekey_multicast_bundle`：
    - `bytes_fwd_xy -72.45%`
    - `byte_hops -63.14%`
    - `nics_sum_tx_bytes -77.56%`
  - `C_spiketilekey_multicast_bundle`：
    - `bytes_fwd_xy -77.49%`
    - `byte_hops -65.94%`
    - `nics_sum_tx_bytes -81.24%`

**C. 反例与边界**
- `B_spikekey_multicast_bundle_compact` 的历史反例（本地重建回胖包）已修复；当前基线对比结果为：
  - `bytes_local -45.00%`
  - `byte_hops -16.07%`
  - 细节见 7.5/7.7。

### 7.4 对 ISCA 叙事的价值

- 本轮结果已把 P1 证据从“packet count”推进到“**bytes + byte-hops**”层面，且在 B/C bundle 上收益显著、跨 seed 稳定。
- 正确性链路完整（`validation_errors=0`），说明机制收益不是以语义破坏换来的。
- `B_bundle_compact` 的反例已消除：可以形成更干净的“二维优化（packets × bytes）”叙事（注入包数维度 + 链路字节维度同时优化）。

### 7.5 回归修复（已完成）：`B_bundle_compact` 本地重建保留 compact

为消除 `B_spikekey_multicast_bundle_compact` 的反例回退，已完成如下修补：

1) **V2 entry 增加 compact 偏好标记**
- `SpikeInterBundleCodec::kEntryFlagCompactRouteV3`
- 文件：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeInterBundleCodec.h`

2) **发送侧写入偏好**
- SpikeKey 的 V2 entry 在 `experimental_compact_mask_enable=1` 时写入该标记
- 文件：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SpikeCommSubsystem.cc`

3) **Router 本地重建按偏好回写**
- `packet_kind=SpikeKey` 的 local entry：优先 `encodeSpikeKeyCompactV3`，失败回退 fixed V2
- 文件：`sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`

> 说明：forward bundle 的 V2 entry 仍保持统一结构；仅 local rebuild 路径恢复 compact 编码，避免 local bytes 放大。

### 7.6 阻塞性实验修补（独立问题）

复验阶段发现一个与 NoC 改动无关但会导致实验直接失败的问题：
- `SnnPESubComponent` 注册了 `synapse_sram_*` 5 个统计项，但 ELI 统计清单未声明，重编译后报：
  - `attempting to register unknown statistic 'synapse_sram_served_bytes_total'`

已做最小修补（仅补声明，不改行为）：
- 文件：`sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`

### 7.7 修复后复验结果（最终）

- seed3 快速复检（此前失败集）：
  - `python3 NoCexp/spiketile_router_lab/experiments/run_suite.py --sst-bin /home/xgy/remote/sst_install_mpi/bin/sst --sim-time 300us --seeds 3 --compact-variants --inter-bundle-variants --inter-bundle-v2-enable --local-endpoint-multicast-enable --tag v2_localon_seed3_recheck_afterfix`
  - 输出：`NoCexp/spiketile_router_lab/runs/20260227-172527_v2_localon_seed3_recheck_afterfix/`
  - 结果：`9/9` 通过

- 全矩阵复验（3 seeds）：
  - `python3 NoCexp/spiketile_router_lab/experiments/run_suite.py --sst-bin /home/xgy/remote/sst_install_mpi/bin/sst --sim-time 300us --seeds 1 2 3 --compact-variants --inter-bundle-variants --inter-bundle-v2-enable --local-endpoint-multicast-enable --tag v2_localon_matrix_fixcompact_final`
  - 输出：`NoCexp/spiketile_router_lab/runs/20260227-173337_v2_localon_matrix_fixcompact_final/`
  - 结果：`27/27` 通过，`validation_errors=0`

- 全矩阵复验（3 seeds，重跑确认一致性）：
  - `python3 NoCexp/spiketile_router_lab/experiments/run_suite.py --sst-bin /home/xgy/remote/sst_install_mpi/bin/sst --sim-time 300us --seeds 1 2 3 --compact-variants --inter-bundle-variants --inter-bundle-v2-enable --local-endpoint-multicast-enable --tag v2_localon_matrix_rerun`
  - 输出：`NoCexp/spiketile_router_lab/runs/20260228-035338_v2_localon_matrix_rerun/`
  - 结果：`27/27` 通过，`validation_errors=0`（关键指标与 `v2_localon_matrix_fixcompact_final` 完全一致）

**与 baseline (`20260227-154846_v2_localoff_matrix`) 的最终汇总：**
- `routers_sum_bytes_fwd_xy`: `-27.84%`
- `routers_sum_bytes_local`: `-46.31%`
- `routers_sum_byte_hops`: `-35.00%`
- `nics_sum_tx_bytes`: `-29.65%`
- `routers_sum_local`: `-43.10%`
- `p95/p99`: 持平

**目标反例项修复确认：**
- `B_spikekey_multicast_bundle_compact`（base -> new）：
  - `bytes_local`: `-45.00%`（由此前 `+105.00%` 反转）
  - `byte_hops`: `-16.07%`（由此前 `+39.78%` 反转）
  - `nics_sum_tx_bytes`: `-2.78%`
  - `bytes_fwd_xy`: `+1.10%`（轻微开销，来自 V2 meta）

---

## 8. 下一步 NoC 体系结构优化（最佳方案）：byte-hop 感知的自适应路由与树选择

### 8.1 背景：我们已经“减包/减字节”，但 tail 仍受路由与争用支配

当前 NoC 数据面已经具备一套可组合的优化栈：
- **减包**：SpikeTileKey sender aggregation、InterBundle（注入侧与网络侧分裂）
- **减字节**：compact route（V3）、InterBundle V2（shared prefix + entry meta）
- **减本地复制**：Router->NIC local endpoint multicast

但在一些参数点上（例如未开启 byte-aware/未进入拥塞区），`p95/p99` 仍可能持平。下一步要“体系结构级提升 tail”，需要让路由器在出现端口争用时能**自适应选择更不拥塞的最短路径与更低复制代价的树形扩散方式**。

### 8.2 核心想法：以 `byte_hops`/端口队列作为 cost，做 minimal adaptive（可落地、可验证）

提出一个统一的 cost 目标函数（论文叙事也更直观）：
- **目标**：在保持最短路径（minimal）与语义不变的前提下，降低拥塞下的 `byte_hops` 与尾部排队时间。
- **可观测输入**：`MulticastRouter` 已有 `port_next_free_cycle_`（端口繁忙度 proxy）与 byte-aware 服务时间模型；同时我们已有 `byte_hops/bytes_fwd_xy/bytes_local` 统计做闭环验证。

### 8.3 设计方案（推荐）：`AdaptiveXY/YX + Adaptive Intra Tree` 两段式

1) **INTER：自适应选择 XY/YX（minimal adaptive）**
- 新增策略（示例名）：`multicast_inter_policy=adaptive_xy_yx`
- 对每个 entry（或每个 SpikeKey）在每跳做选择：
  - 若 `dest_x != self_x` 且 `dest_y != self_y`，存在两条 minimal 方向候选（先 X 或先 Y）
  - 用 `cost = predicted_port_wait + service_cycles(payload_bytes)` 估算下一跳代价
  - 选择 cost 更小的方向；若相等，用 `group_id` 哈希打破平局，避免路径抖动
- 对 InterBundle V2：仍按方向分组重打包，只是“分组规则”由固定 XY/YX 变成自适应决策

2) **INTRA：在 ingress 处自适应选择 block 内树（X-first vs Y-first）**
- 目前我们提供 `manhattan_x_first / manhattan_y_first` 两种确定性树。
- 在 ingress 节点（`stage=INTRA`）可用 `core_mask` 快速估算两棵树的代价：
  - 估算每条边是否会承载至少一个 recipient（类似现有 subtree 判断）
  - 以 `byte_hops` 为权重（考虑 payload bytes、local-endpoint、compact 等会改变 bytes）
  - 选代价更小的树形策略执行扩散

3) **与现有优化的融合点（关键）**
- InterBundle V2 已在 entry meta 中携带 compact 偏好（`kEntryFlagCompactRouteV3`）与 tile compact 版本号；
  - 使得 “本地重建 + INTRA 扩散” 时 payload bytes 可控，cost 估算不会失真。
- local-endpoint multicast 把 “endpoint fanout” 变成 NIC 展开；
  - cost 估算中可以把 endpoint clone 的代价视为常数（或直接用 `bytes_local` 统计验证）。

### 8.4 工程落地（强调隔离主线）

为保持主线稳定，推荐将该自适应策略落在**独立 router 组件**，例如：
- 新增 `SnnDL.MulticastRouterAdaptive`（文件独立，默认实验脚本不启用）
- `NoCexp/spiketile_router_lab/test_mesh_4x4_key_tile_multicast.py` 增加 env 开关选择 router 类型

这样能做到：
- 主线 `SnnDL.MulticastRouter` 完全不变（回归风险最小）
- 实验可在 NoCexp 下快速迭代策略（便于写论文时“机制/实现/消融”叙事）

### 8.5 对比实验设计（solid、可写入论文）

建议构建 2 组基准（都跑 `seeds=1,2,3`）：
1) **拥塞区**（让路由策略差异可显著放大）
   - `--router-serialize-enable --router-serialize-byte-enable`
   - 提高注入强度（减小 `TRAFFIC_PERIOD_CYCLES` 或增大 `TRAFFIC_BATCH_SIZE`）
2) **非拥塞区**（验证无副作用）

每组做 2x2x2 消融：
- routing：`xy/yx/hash_xy/adaptive_xy_yx`
- encoding：`InterBundle V2 on/off`、`compact on/off`
- delivery：`local-endpoint on/off`

证据链建议以三类指标闭环：
- **结构**：`routers_sum_byte_hops / bytes_fwd_xy / bytes_local / clones`
- **性能**：`p95/p99`（noc_lat）与 `sim_time_actual_ns`（若接入主线）
- **正确性**：`validation_errors=0`、`sk_group meta_mismatch=0`、`tile_bad_decode=0`

### 8.6 首轮落地与复验结果（2026-02-28）

> 工程取舍说明：为快速验证机制有效性，首轮未新建独立 router 组件，而是在现有 `MulticastRouter` 上新增可选策略开关（默认行为保持不变）。

1) **代码落地点**
- `MulticastRouter` 新增：
  - `multicast_inter_policy=adaptive_xy_yx`
  - `multicast_intra_policy=adaptive`
- 关键文件：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.h`
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`
  - `NoCexp/spiketile_router_lab/experiments/run_suite.py`

2) **实验配置与产物**
- baseline（固定策略）：
  - run_id: `20260228-043657_adaptive_base_matrix`
  - 参数：`--inter-policy xy --intra-policy manhattan_x_first`
- adaptive（新策略）：
  - run_id: `20260228-050102_adaptive_new_matrix`
  - 参数：`--inter-policy adaptive_xy_yx --intra-policy adaptive`
- 共同参数：
  - `--sim-time 300us --seeds 1 2 3 --enable-all`
  - `--traffic-period-cycles 50 --traffic-batch-size 8`
  - `--router-serialize-enable --router-serialize-byte-enable --router-serialize-bytes-per-cycle 8`
  - `--compact-variants --inter-bundle-variants --inter-bundle-v2-enable --local-endpoint-multicast-enable`
- 两组均为 `27/27` 通过，`validation_errors=[]`

3) **关键结果（27-case 汇总，base -> adaptive）**
- `routers_sum_byte_hops`: `5,622,688,520 -> 5,617,657,904`（`-0.09%`）
- `routers_sum_bytes_fwd_xy`: `3,825,754,432 -> 3,994,529,888`（`+4.41%`）
- `routers_sum_bytes_local`: `1,796,934,088 -> 1,623,128,016`（`-9.67%`）
- `routers_sum_clones`: `16,879,051 -> 16,660,048`（`-1.30%`）
- `nics_sum_tx_bytes`: 持平（`0.00%`）
- `p95/p99`: 持平（`0.00%`）

4) **多播子集（B+C）观察（排除 A/unicast 噪声）**
- `routers_sum_byte_hops`: `-0.10%`
- `routers_sum_bytes_fwd_xy`: `+4.96%`
- `routers_sum_bytes_local`: `-10.38%`
- `p95/p99`: 持平

5) **解读**
- 首轮 adaptive 的主要效果是把一部分流量从 `bytes_local` 迁移到 `bytes_fwd_xy`，但**总 byte-hops 基本不变**，所以 tail 未改善。
- 正确性未破坏：`validation_errors=0`、`tile_bad_decode=0`、`nics_sum_tx_bytes` 不变。
- 该结果说明“仅基于本跳端口 wait+service 的 minimal adaptive”还不足以形成稳定端到端收益，但机制链路与统计链路已经打通。

6) **下一步修订（面向论文可证据化）**
- 增加决策遥测：记录 `adaptive_xy_yx` 选 X/Y 次数、`adaptive` 选 x-first/y-first 次数、平局比例、端口代价分布。
- 升级 cost：在本跳 cost 上加入轻量 lookahead（剩余 Manhattan 距离权重 + INTRA 子树规模权重）。
- 重新组织矩阵：优先 B/C 多播强相关 case，并分“拥塞区/非拥塞区”两档运行，避免 A/unicast 稀释结论。

### 8.7 二次落地（遥测 + lookahead 叠加）与对比结果（2026-02-28）

1) **实现范围**
- Router 新增参数与统计：
  - 参数：`adaptive_telemetry_enable`、`adaptive_inter_w_wait/service/len`、`adaptive_intra_w_bytes/queue`
  - 统计：`adi_inter_*`、`adi_intra_*`（决策次数、X/Y 选择、tie、chosen cost、delta、预测 bytes）
- `run_suite.py` 与 `test_mesh_4x4_key_tile_multicast.py` 已打通这些参数与汇总字段。

2) **lookahead/cost 形态**
- INTER（`adaptive_xy_yx`）：
  - `cost = w_wait * wait + w_service * service + w_len * len_bias`
  - 其中 `len_bias` 使用正交方向剩余曼哈顿距离（X-first 用 `dy`，Y-first 用 `dx`）。
- INTRA（`adaptive`）：
  - 对 x-first/y-first 两棵树估算 `pred_bytes_out = payload_bytes * (unique_edges + local_delivery_units)`；
  - 并叠加 immediate queue term：`cost = w_bytes * pred_bytes_out + w_queue * queue_cost`。

3) **实验设置**
- baseline（固定策略）：
  - run_id: `20260228-054438_adaptive_lh_base_matrix`
  - 参数：`--inter-policy xy --intra-policy manhattan_x_first`
- adaptive+lookahead：
  - run_id: `20260228-060941_adaptive_lh_new_matrix`
  - 参数：`--inter-policy adaptive_xy_yx --intra-policy adaptive`
- 两组共同参数：
  - `--sim-time 300us --seeds 1 2 3 --enable-all`
  - `--traffic-period-cycles 50 --traffic-batch-size 8`
  - `--router-serialize-enable --router-serialize-byte-enable --router-serialize-bytes-per-cycle 8`
  - `--compact-variants --inter-bundle-variants --inter-bundle-v2-enable --local-endpoint-multicast-enable`
  - `--adaptive-telemetry-enable --adaptive-inter-w-wait 1 --adaptive-inter-w-service 1 --adaptive-inter-w-len 1 --adaptive-intra-w-bytes 1 --adaptive-intra-w-queue 1`
- 正确性：两组均 `27/27` 通过。

4) **关键结果（27-case 汇总，base -> adaptive+lookahead）**
- `routers_sum_byte_hops`: `5,622,688,520 -> 5,617,702,320`（`-0.09%`）
- `routers_sum_bytes_fwd_xy`: `3,825,754,432 -> 4,000,760,128`（`+4.57%`）
- `routers_sum_bytes_local`: `1,796,934,088 -> 1,616,942,192`（`-10.02%`）
- `routers_sum_clones`: `16,879,051 -> 16,628,934`（`-1.48%`）
- `p95/p99`: 持平。

5) **新增遥测观察（adaptive 侧）**
- INTER 决策有效触发：
  - `decisions=11,785,120`，`choose_x=49.88%`，`choose_y=50.12%`，`tie=6.04%`
  - `avg_chosen_cost=120,066.67`，`avg_abs_delta=16,905.27`
- INTRA 当前无区分度：
  - `decisions=7,987,894`，`tie=100%`，`choose_x=100%`
  - `pred_bytes_delta_abs=0`，`queue_chosen=0`

6) **解读**
- 叠加后的遥测链路已经完整：我们可以明确看到 INTER 的自适应确实在做非平凡选择。
- 但总体现象仍与上一轮一致：`bytes_local` 下降、`bytes_fwd_xy` 上升，`byte_hops` 与 tail 基本不变。
- 从遥测看，当前 workload 下 INTRA 两棵树代价长期相等（`tie=100%`），因此该轮“INTRA lookahead”未形成有效决策杠杆。

7) **下一步（针对本轮瓶颈）**
- 优先构造/筛选真正触发 INTRA 分歧的 case（更大 block 或更偏置的 recipient mask），验证 `pred_bytes_delta_abs` 能否拉开。
- 在 B/C 子集上增加“只看多播”矩阵，减少 A/unicast 稀释。
- 若 INTRA 仍长期 tie，则将论文重点转为：INTER 自适应 + sender/encoding 机制的协同，并把 INTRA 定位为“依赖流量形态”的条件机制。

### 8.8 阶段性结论：NoC-only 优化进入瓶颈（建议转向 NoC×GAS/内存联合）

结合 7.x（注入/编码/本地投递）与 8.6/8.7（路由/树选择）两条证据链，可以给出一个清晰的阶段性判断：

1) **我们已拿到“结构性大收益”的 NoC 机制**
- `InterBundle V2 + compact + local-endpoint` 这类机制改变了“注入次数/注入字节/本地复制形态”，因此能显著压降 `byte_hops/bytes_*`（属于可迁移、可写论文的硬证据）。

2) **仅靠 Router 侧“最短路内做选择”（XY/YX + x-first/y-first）很难稳定再挤出收益**
- 两轮矩阵（8.6 与 8.7）都显示 `routers_sum_byte_hops` 近乎不变，`p95/p99` 也无变化。
- 8.7 的遥测证明这不是“没触发”：INTER 发生了大量非平凡决策；但它仍然没有带来端到端结构收益。

3) **本轮关键新发现：INTRA lookahead 在当前 workload 下没有决策杠杆**
- `adi_intra_tie=100%`、`pred_bytes_delta_abs=0` 说明当前流量形态下，block 内两棵树长期等价。
- 这意味着继续在“INTRA 树形策略”上做 NoC-only 微调，可能只能在少数特定流量上有效，很难作为普适贡献。

4) **下一步推荐：把优化目标从“路由选择”提升到“发放形态/注入结构”**
- 更像瓶颈的部分已经转移到系统层：上游（GAS/内存请求与回包、burst 粒度、注入节奏）决定了网络是否进入可优化的拥塞区。
- 因此建议把后续创新点落在 NoC×内存/GAS 的联合闭环上，例如：
  - 用 `global credit` 或“端口/MC 队列 credit”对 GAS 的请求发放做节流与整形（避免 burst 化导致 tail 钉死）。
  - 做“同一 BCSR block 的多发起者合并 + 响应多播回传”，把 NoC 的 multicast 能力用于 memory-side 的去重回包，而非仅用于 spike 路由。

---

## 9. STORM-Control：NoC-aware Global Credit（设计草案，准备落地）

### 9.1 动机（为什么要把 NoC 证据纳入 global credit）

现有 `global credit`（p0/p0b/p0c）主要依据 PE 侧 step 遥测（`step_total_ns/step_apply_ns`）来分配下一步的 `apply_bank_credit_target`。这在 **纯 DRAM-bound** 的“慢节点”场景下可能有效，但在 STORM-DataPlane 已经显著降低注入/转发成本之后，我们观察到：
- 仍存在一些 step 的尾部来自 **NoC drain/背压等待**（而不是 Apply 本身慢）。
- 对这种 **NoC-bound** 的 PE 单纯加大 Apply 并发（credit）往往不会缩短 step，反而可能加重 burst 形态或扩大不必要的资源差异（导致退化/不稳定）。

因此需要一个更“体系结构闭环”的版本：**NoC-aware global credit** —— 用 NoC 的证据（至少是 PE 本地的 NoC 背压/排队/排空时间）把慢节点分成：
- **DRAM-bound**：Apply 主导 → 值得加 credit；
- **NoC-bound**：drain/背压主导 → 不该盲目加 credit（甚至应该降 credit 或改注入节奏）。

### 9.2 遥测口径（优先选“PE 本地可得”的 NoC 指标）

为了保持改动小、可复现实验，我们优先不依赖“全网 router 级统计”来做闭环控制，而用每个 PE 在 `PeDone(seq)` 时上报的本地观测（controller 只做全局决策与下发）：

1) **step_drain_after_scatter_ns（建议新增）**
- 定义：`PeDone_send_time_ns - EndScatter_time_ns`（若无 `EndScatter`，回退为 `PeDone_send_time_ns - BeginScatter_time_ns`）。
- 意义：这是 step 末尾为达到 barrier 所必需的“排空等待”近似量，能捕捉 NIC pending / ring pending / NoC 仍在途导致的尾部。

2) **step_noc_pending_peak（建议新增）**
- 定义：在 `global_step_active_seq_` 期间周期性采样 `noc_subsys_.nicPendingSendCount()` 与 `noc_subsys_.ringPendingMessageCount()` 的最大值（或二者加和）。
- 意义：比 drain 时间更“结构级”，能表达某步是否形成显著背压/排队峰值。

3) **step_injected（已有）**
- `MultiCorePE` 的 done 判定已显式等待 `step_activation_subsys_.injectedForSeq(seq)`（避免“未注入就完成”的误判）。
- 意义：可作为排除项，避免把“没发生有效工作”的 step 纳入 credit 学习。

备注：
- 如果后续需要更强证据，再考虑把 `SnnNIC` 的 `total_bytes_sent`（或 per-step delta）做成轻量 runtime 计数并上报；但第一版优先用 drain/pending 这类不依赖细粒度统计的指标。

### 9.3 控制策略（p0d：NoC-aware budgeted credit，最小可行闭环）

目标：保持 p0b 的“预算守恒（raise+drop）”优点，但把“raise 的候选集合”限制在 **DRAM-bound** 的 PE 上。

记：
- `T = step_total_ns`
- `A = step_apply_ns`
- `D = step_drain_after_scatter_ns`（新增）
- `r_apply = A/T`（Apply 主导程度）
- `r_drain = D/T`（NoC drain 主导程度）

建议的最小规则（直观且可解释）：
1) **NoC-bound 屏蔽**：若 `r_drain >= theta_drain` 或 `pending_peak >= theta_pending`，则该 PE 本步不进入 raise 候选（最多给 base credit）。
2) **DRAM-bound 优先**：在剩余集合里按 `A`（或 `A` 的 EWMA）排序取 top-k raise 到 `credit_hi`。
3) **预算守恒**：参照 p0b 的 drop 逻辑，从 `r_apply` 低/`A` 小的 PE 降到 `credit_lo`（不低于 floor），以抵消 raise 的预算。
4) **抑振**：引入简单滞回（例如：连续 N 步触发才切换 raise/drop），避免一两次偶然拥塞导致 credit 抖动。

这套策略有三个论文友好点：
- 解释清晰：把慢节点拆成两类；
- 风险可控：只影响 Apply 并发（调度），不改语义；
- 能用现有 step barrier 直接量化 end-to-end：`step_total_ns` 的 tail 是否下降。

### 9.4 实现落点（代码改动闭环，最短路径）

1) **上报（PE → controller）**
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/events/GasStepBarrierEvent.h`：新增 `step_drain_after_scatter_ns`、`step_noc_pending_peak` 字段（序列化）。
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`：在发送 `PeDone(seq)` 时填充上述字段（`stage_marks_[seq].es` 已存在；`noc_subsys_.*Pending*` 可直接查询/采样）。

2) **决策（controller）**
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/gas/GlobalGasStepController.{h,cc}`：
  - 增加 `credit_ctrl_mode=3`（p0d-noc-aware）；
  - 维护 per-PE 的 `D`/`pending_peak` 遥测数组；
  - 在 `computeNextCredits_()` 内实现“屏蔽 NoC-bound + DRAM-bound top-k raise + 预算 drop + 滞回”。

3) **下发（controller → PE → core → GatherBufferIF）**
- 现有链路已经通：`apply_bank_credit_target` → `IGlobalStepCreditHooks` → `GatherBufferIF::setApplyBankCreditTarget(seq, credit)`。

### 9.5 实验设计（如何证明“闭环真的起效”）

最小对比矩阵（保持 STORM-DataPlane 固定，只比较控制面策略）：
- baseline：`credit_ctrl_enable=1, credit_ctrl_mode=1(p0b)`（或 mode=0）  
- new：`credit_ctrl_enable=1, credit_ctrl_mode=3(p0d-noc-aware)`  
- 其余 NoC 参数保持一致（InterBundle V2 + compact + local-endpoint + byte-aware）。

关键证据：
- end-to-end：`step_total_ns` 的 mean/p95/p99（每步/每 PE 汇总 + 全局 barrier）
- 分解：`step_apply_ns` 与 `step_drain_after_scatter_ns` 的分布是否“尾部被切掉”
- NoC 结构指标：`routers_sum_byte_hops`、`nics_sum_tx_bytes`（应不显著变差；理想情况下降低 tail 而不增 byte-hops）
