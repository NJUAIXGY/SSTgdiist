# HBM-like NMC + 3D Native MulticastRouter Upgrade Design

Date: 2026-03-17
Owner: Fufu
Status: Draft

## 1. Background

当前主线已经收敛为：

- 顶层：`DRAM-based SNN chip`
- memory backbone：`GAS`
- memory optimization：`GCSS-GLIDE`
- NoC 主线：`STORM + MulticastRouter`

接下来的升级目标不是再引入一个并列小机制，而是把顶层系统进一步提升为：

- `3D-stacked DRAM-based SNN chip`

在这次升级中，memory 和 NoC 分别采用不同但相互兼容的演进路径：

- memory side 采用 `HBM-like 3D-stacked DRAM`，并将系统定位为 `near-memory computing (NMC)`，而不是一开始就假定 `PIM` 或 `monolithic 3D DRAM`
- NoC side 采用 `3D native MulticastRouter fabric`，把当前只支持 `WxH` 的二维原生多播后端升级到 `WxHxZ`

这两个升级方向的共同原则是：

- 保持 `GAS` 语义不变
- 保持 `GCSS-GLIDE` 的 locality / runtime memory behavior 主线不变
- 优先升级“底层 substrate”，而不是先推倒上层 packet format / workload 语义

## 2. Design Goals

- 在不改写 `GAS + GCSS-GLIDE` 主线语义的前提下，为系统引入真实 3D 结构。
- 将 spike dissemination 的 substrate 从 `2D native multicast mesh` 升级为 `3D native multicast fabric`。
- 将当前 `per-PE isolated DRAM backend` 升级为 `HBM-like stacked memory + shared stack controllers`。
- 用最少的新抽象把现有 `mesh_template`、`snndl_system`、`MulticastRouter`、`ramulator2` 串起来。
- 保持 backward compatibility：默认配置不变；新能力仅在显式启用时生效。

## 3. Non-Goals

- 不在 v1 中引入 `monolithic 3D DRAM` 工艺假设。
- 不在 v1 中把计算单元下沉到 memory bank / base die；本方案是 `NMC`，不是 `PIM`。
- 不在 v1 中把 memory traffic 搬到 `MulticastRouter` 上；router 仍只服务 spike / key-like NoC 数据面。
- 不在 v1 中重写 `SpikeKey / SpikeTileKey / InterBundle` packet format。
- 不在 v1 中改写 `GAS` gather/apply/retire 的控制面语义。

## 4. Target System Architecture

### 4.1 Top-Level View

目标系统由两条主线组成：

1. Compute / spike path
- `WxHxZ` 个 `MultiCorePE`
- `WxHxZ` 个 `SnnDL.MulticastRouter`
- 通过 `north/south/east/west/up/down/local` 连接
- 使用 `3D native multicast` 传播 `SpikeKey / SpikeTileKey`

2. Memory / synapse path
- `S` 个 `HBM-like memory stack`
- 每个 stack 由一个 shared stack bus 和多个 `MemController + ramulator2(HBM2)` 组成
- 各 PE 通过“近存连接”访问所属 stack，而不是继续每个 PE 拥有独立 DRAM backend

### 4.2 Recommended Baseline Configuration

建议 v1 先固化一个论文/实现双方便于验证的 baseline：

- compute shape: `4x4x2`，共 `32` 个 PE
- memory stacks: `4`
- stack placement: `XY quadrant-based`
- channels per stack: `4`
- channel interleave: `256B`
- DRAM backend: `ramulator2_hbm2.cfg`
- NoC route order: `Z -> XY -> INTRA`

这里的 `4` 个 HBM-like stacks 分别服务四个 XY 象限：

- stack0: `(x<2, y<2)`
- stack1: `(x>=2, y<2)`
- stack2: `(x<2, y>=2)`
- stack3: `(x>=2, y>=2)`

两个 compute tiers (`z=0,1`) 共享同一组 stacks。这样：

- memory homing 由 `(x,y)` 决定
- tier `z=1` 的 PE 比 tier `z=0` 多一个 vertical memory distance
- NoC 的三维化与 memory 的近存建模自然耦合，但不会把两条路径强行混成一个 transport

## 5. Why This Is HBM-like NMC, Not PIM

本方案的 memory stack 只提供：

- 高带宽、分 channel 的 3D-stacked DRAM
- stack-shared 控制器与带宽约束
- tier-aware 近存访问距离

但以下功能仍然留在 logic / PE side：

- `GAS` window 组织
- `GCSS-GLIDE` metadata/index layout
- gather/apply 调度
- synapse decode / weight accumulation

因此它的正确定位是：

- `HBM-like NMC`

而不是：

- `PIM`

未来如果要升级到 PIM，必须进一步把下列能力下沉到 memory-side base logic 或 bank-local logic：

- index decode
- gather filter
- partial sum accumulation
- bank-local reduction / prefetch assist

这些都明确属于 v1 的 future work。

## 6. NoC Upgrade: 3D Native MulticastRouter

### 6.1 Core Principle

`MulticastRouter` 先升级为真实 3D substrate，上层 packet format 尽量不动。

也就是说：

- `stage=INTER` 的 payload 仍保持现有定义
- router 内部把 `INTER` 解释成两段：
  - `INTER_Z`
  - `INTER_XY`
- 抵达 `ingress_node` 后再进入原有 `INTRA`

### 6.2 Router Changes

必须修改：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`

关键改动：

- `mesh_shape: "WxH" -> "WxHxZ"`
- 新增端口：
  - `up`
  - `down`
- 新增 send/handle 方法：
  - `sendToUp_()`
  - `sendToDown_()`
  - `handleUpLinkEvent()`
  - `handleDownLinkEvent()`
- `port_next_free_cycle_` 从 5 口扩到 7 口
- 坐标映射从 `(x, y)` 扩展到 `(x, y, z)`

### 6.3 Route Semantics

v1 采用简单且稳定的 `z-first`：

- 若当前 node 的 `z != ingress_z`
  - 优先走 `up/down`
- 若 `z == ingress_z` 且 `node_id != ingress_node`
  - 继续走现有 `XY / YX / adaptive_xy_yx`
- 到达 `ingress_node`
  - payload 从 `INTER` patch 成 `INTRA`
  - 继续执行现有 block-local tree multicast

### 6.4 Important Limitation Kept on Purpose

v1 中 block multicast 仍然是：

- `die-local 2D block`

也就是：

- `block_w_h`
- `block_id`
- `core_mask`

继续只描述单个 die 内的二维 block，而不引入 `3D volumetric block`。这样可以避免同时重写：

- `SpikeNocCodec`
- `SpikeTileBatchEmitter`
- `SpikeInterBundleCodec`
- `SynapseRouteSubsystem` 的 block encoding 契约

## 7. Memory Upgrade: HBM-like Shared Stack Model

### 7.1 Core Principle

把当前 `per-PE local memory controller` 模式，升级成：

- `per-stack shared memory system`

即：

- 一个 stack 服务一组 PE
- stack 内包含多个 interleaved MemController channels
- stack 对该组 PE 暴露为“近存共享 HBM 资源”

### 7.2 Recommended Stack Abstraction

为每个 stack 建立一个抽象：

- `stack_id`
- `home_xy_region`
- `num_channels`
- `channel_interleave_bytes`
- `stack_bus`
- `controllers[channel_id]`
- `backend = ramulator2(HBM2)`

建议在 `snndl_system` 层新增或扩展 builder：

- `build_stack_memory_systems(...)`

而不是继续把 `build_pe_memory_systems(...)` 硬拗成 stack。

### 7.3 Request Path

v1 的 memory path 仍然完全走 memHierarchy：

- `core`
- `GatherBufferIF`
- `L1`
- `stack attachment link`
- `shared stack bus`
- `MemController(channel)`
- `ramulator2_hbm2`

这里不会经过 `MulticastRouter`。

### 7.4 Tier-Aware Near-Memory Distance

为 upper tiers 建模一个最小但真实的近存差异：

- `z=0` PE 到所属 stack 的 attachment latency 为 `base`
- `z=1` PE 在此基础上额外增加 `vertical_mem_hop_latency`

实现上可通过 PE 到 stack bus 的 link latency 编码：

- `latency = base_stack_attach_latency + z * vertical_mem_hop_latency`

这样无需引入新的 memory network 组件，也能显式体现：

- 近层更近
- 远层更远

### 7.5 HBM-like Channel Defaults

优先复用仓库里已经存在的 HBM-like contract：

- `sst_workloads/tensor_si/test_tensor_spec.py`

其中已经有基于 `ramulator2_hbm2.cfg` 的默认推断：

- `tensor_dma_hbm_channels = 4`
- `tensor_dma_hbm_channel_interleave_bytes = 256`

本次 mesh / snn 主线升级建议直接采用相同默认，避免在同一仓库里形成两套 HBM-like 口径。

## 8. Homing and Data Placement Policy

### 8.1 Home Stack Policy

v1 推荐采用：

- `home_stack_policy = xy_quadrant`

原因：

- 简单、稳定、可解释
- 与 `4 stacks + 4x4x2` baseline 自然匹配
- 不要求先做复杂 mapping solver

### 8.2 Weight / Index Placement

建议保持现有主线原则不变：

- `GCSS-GLIDE` 继续以 post-home / locality-preserving 的视角组织 values 和 index
- 只是把“物理承载 backend”从 per-PE DRAM 切到 per-stack HBM-like backend

因此 v1 的 home 规则建议是：

- 某个 post PE 的 weight/index 数据，放到其 `home_stack`
- 两个 compute tiers 中相同 `(x,y)` 象限的 PE 共享该 stack

这样仍能保持：

- post-centric locality
- `GAS + GCSS-GLIDE` runtime 行为可解释

### 8.3 Out-of-Scope Placement Policies

以下不进入 v1：

- inter-stack striping of one PE's weights
- dynamic migration across stacks
- tier-aware remapping that changes semantic home
- monolithic 3D page/row compaction assumptions

## 9. Integration Contract Between Memory and NoC

两条升级主线在 v1 中是“协同而不耦死”的：

- spike / key traffic 走 `3D MulticastRouter`
- memory requests 走 `HBM-like memHierarchy path`

共享的顶层设计变量只有：

- `compute_shape = WxHxZ`
- `home_stack_policy`
- `vertical distance`

这样做的原因是：

- 现有系统本来就把 NoC path 与 memory path 分开
- `STORM` 解决 network-side amplification
- `GAS + GCSS-GLIDE` 解决 memory-side amplification

升级后只是在两个子系统各自提升真实度：

- NoC 更真 3D
- memory 更像 HBM-like NMC

## 10. Config and Spec Proposal

### 10.1 Platform

新增：

- `platform.mesh_shape = "4x4x2"`

兼容规则：

- 若 `mesh_shape` 存在，则优先于 `mesh_size`
- 若只有 `mesh_size`，则视为 `mesh_shape = "{mesh_size}x{mesh_size}x1"`

### 10.2 NoC

新增：

- `noc.params.shape = "4x4x2"`
- `noc.params.vertical_link_latency = "3ns"`
- `noc.params.vertical_route_order = "zxy"`

保留：

- `multicast_block_w`
- `multicast_block_h`
- `multicast_ingress_policy`
- `multicast_inter_policy`
- `multicast_intra_policy`
- `local_endpoint_multicast_enable`

### 10.3 Memory

新增：

- `memory.params.mode = "hbm_like"`
- `memory.params.num_stacks = 4`
- `memory.params.stack_home_policy = "xy_quadrant"`
- `memory.params.channels_per_stack = 4`
- `memory.params.channel_interleave_bytes = 256`
- `memory.params.stack_attach_latency = "2ns"`
- `memory.params.vertical_mem_hop_latency = "2ns"`

保留并复用：

- `memory.backend.type = "ramulator2"`
- `memory.backend.params.configFile = "sst_dram_si/configs/ramulator2_hbm2.cfg"`

## 11. Planned File/Module Changes

### 11.1 Must Change

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/noc/MulticastRouter.cc`
- `snndl_system/noc_multicast.py`
- `sst_dram_si/mesh_template/spec.py`
- `sst_dram_si/mesh_template/runtime.py`
- `sst_dram_si/mesh_template/build.py`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/route/SynapseRouteSubsystem.cc`
- `snndl_system/mem_memhierarchy.py` or a new shared `snndl_system/mem_hbm_stack.py`

### 11.2 Nice to Extract

建议抽一个共享 helper，避免 mesh/tensor 两条线重复发明 HBM config 推断：

- `snndl_system/hbm_config.py` or similar

用来统一：

- channels per stack
- interleave bytes
- backend metadata for reporting

### 11.3 Intentionally Not Changed in v1

- `SpikeNocCodec.h`
- `SpikeTileBatchEmitter.h`
- `SpikeInterBundleCodec.h`
- `GAS` control flow
- `GCSS-GLIDE` codec / locality policy

## 12. Implementation Phases

### Phase A: Config and Substrate Preparation

- 解析 `mesh_shape = WxHxZ`
- builder 支持 `shape`
- `noc_multicast.py` 连 `up/down`
- `mesh_template` runtime/effective_config 输出新字段

### Phase B: 3D Native Router

- `MulticastRouter` 增加 3D shape / up/down
- `z-first` `INTER` 路由
- `Z=1` backward-compatibility regression

### Phase C: HBM-like Shared Stack Memory

- 引入 shared stack memory builder
- 将 per-PE MemController 模式切换为 per-stack shared channels
- 接入 `ramulator2_hbm2.cfg`
- tier-aware attachment latency

### Phase D: SNN Integration

- `SynapseRouteSubsystem` 改成 tier-aware `ingress_node`
- `home_stack_policy` 生效
- `mesh_template` 能装配 `4x4x2 + 4 stacks`

### Phase E: Evaluation and Mainline Closure

- `Z=1` compatibility A/B
- `4x4x2` correctness smoke
- `HBM-like NMC + 3D router` step-limited runtime validation
- summary / paper metrics 收口

## 13. Verification Plan

### 13.1 Static / Unit

- `python3 -m unittest "sst_dram_si.mesh_template.test_spec_resolver"`
- `python3 -m unittest "sst_dram_si.mesh_template.test_multicast_noc"`
- 为 `mesh_shape=WxHxZ`、`memory.mode=hbm_like`、HBM defaults 新增 focused tests
- `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile`

### 13.2 Router Compatibility

- `mesh_shape = 4x4x1`
- 确认现有 `multicast_mesh` 行为不变

关键指标：

- `spikekey_stage_inter`
- `spikekey_stage_intra`
- `pkts_out_total`
- `byte_hops_total`

### 13.3 New 3D Router Metrics

建议新增：

- `pkts_to_up`
- `pkts_to_down`
- `bytes_to_up`
- `bytes_to_down`
- `z_hops_total`
- `adaptive_inter_choose_z_total` (if adaptive later)

### 13.4 Memory Validation

- `channels_per_stack = 4`
- `channel_interleave_bytes = 256`
- HBM backend recorded in `effective_config`

关键指标：

- per-stack `req_total`
- per-stack `bytes_est_total`
- channel balance
- upper-tier vs lower-tier memory latency delta

### 13.5 End-to-End

目标验证 run：

- `4x4x1 + HBM-like off + 2D router`
- `4x4x1 + HBM-like on + 2D router`
- `4x4x2 + HBM-like on + 3D router`

用来逐步确认：

- 兼容性
- memory realism
- 3D routing correctness

## 14. Risks and Mitigations

### Risk 1: 2D assumptions spread across route builder and runtime

现状：

- `mesh_template.spec/runtime`
- `SynapseRouteSubsystem`
- `noc_multicast.py`

都大量假设 `square 2D mesh`。

Mitigation:

- 先统一 `mesh_shape` 契约，再逐层把 `mesh_size^2` 改成 `W*H*Z`
- 保留 `mesh_size -> WxWx1` 兼容分支

### Risk 2: Shared stack bus becomes unrealistic bottleneck

Mitigation:

- v1 允许 `drain_bus=1`
- 后续若必要，引入 `stack gateway scheduler`
- 但不在 v1 中一次性做 full DMA realism

### Risk 3: HBM pseudochannel details and ramulator2 contract mismatch

Mitigation:

- v1 只显式建模 `channels + interleave`
- pseudochannel 先作为 reporting / future realism，不强行暴露成新 hierarchy

### Risk 4: 3D router and memory realism同时推进导致调试面过大

Mitigation:

- 分阶段：
  - 先 router
  - 再 memory
  - 最后 integration

## 15. Final Recommendation

本次升级最合理的正式口径是：

- **A 3D-stacked DRAM-based SNN chip with a GAS memory backbone, GCSS-GLIDE memory optimization, HBM-like near-memory memory stacks, and a 3D-native MulticastRouter fabric**

其中：

- `HBM-like NMC` 是 memory 主线
- `3D native MulticastRouter` 是 NoC 主线
- `GAS + GCSS-GLIDE` 继续保持主线稳定资产
- `STORM` 先运行在更真实的 3D substrate 上，而不是先重写 packet encoding

这条路线最符合当前仓库、当前论文主线、以及当前实现风险控制。

## 16. References

- Samsung HBM3 product page: https://semiconductor.samsung.com/dram/hbm/hbm3/
- SK hynix + TSMC HBM4 / CoWoS statement: https://www.prnewswire.com/news-releases/sk-hynix-partners-with-tsmc-to-strengthen-hbm-technological-leadership-302120755.html
- Samsung HBM-PIM announcement: https://semiconductor.samsung.com/news-events/news/samsung-develops-industrys-first-high-bandwidth-memory-with-ai-processing-power/
- Near-memory computing survey: https://www.sciencedirect.com/science/article/pii/S0141933119300389
- Monolithic 3D DRAM review: https://academic.oup.com/nsr/advance-article-abstract/doi/10.1093/nsr/nwad290/7440015

