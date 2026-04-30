# 3D Multicast Interface Kernel 深化设计

Date: 2026-03-19
Owner: Fufu
Status: Implemented-mainline, code-aligned addendum on 2026-04-01

## 1. 目标

本设计聚焦一条当前仍带有 2D 遗留语义的关键链路：

- `api/ISynapseRoute.h`
- `services/synapse/route/SpikeCommSubsystem.cc`
- `components/noc3d/MulticastRouter3DNative.cc`

我们的目标不是再增加一个“3D-aware feature”，而是把这条链升级成真正的 `3D-native multicast contract`：

1. `ISynapseRoute` 对外显式暴露 3D block depth，而不再只提供 `W/H`
2. `SpikeCommSubsystem` 发出的 SpikeKey / structured bundle 自身携带显式 3D block 元数据
3. `MulticastRouter3DNative` 依据 packet-level 3D route contract 做转发，而不是再从本地 config 猜测 `block_d`
4. 真实 smoke 继续通过，说明接口升级没有破坏现有 `snn3dexp` 3D 原型闭环

## 2. 当前问题

当前实现已经“功能上支持 3D”，但接口层仍保留明显的 2D 痕迹：

- `ISynapseRoute` 只有 `multicastBlockW()` / `multicastBlockH()`，没有 `multicastBlockD()`
- `BlockTarget` 只有 `block_z`，但缺少显式 `block_d`
- `SpikeCommSubsystem` 只编码 `block_w_h`
- `MulticastRouter3DNative` 在 decode 后仍用本地 `multicast_block_dim_z_` 恢复 `block_d`
- experimental structured bundle 路径仍把 `block_z` 放在 `reserved0` 中传递

这意味着当前 3D 语义并没有在 route interface 和 packet contract 上站稳，仍然依赖“发送端/路由端预先约定同一个配置”的隐含耦合。

## 3. 设计原则

### 3.1 显式优于推断

所有参与 3D multicast 的接口与 payload 都必须显式表达 `block_d`。Router 不应继续依赖本地 config 推断 block depth。

### 3.2 渐进升级而非推翻旧协议

保留旧版 `V1/V2/V3` SpikeKey decode 兼容能力，同时新增显式 3D wire/bundle 版本。2D / legacy case 不应被本轮改动破坏。

### 3.3 只升级主链，不扩大战线

本轮只做：

- SpikeKey 主路径
- structured inter-bundle 主路径
- 关键 workload/self-check decode 兼容

不在本轮主线中重写：

- SpikeTileKey 全量 3D wire contract
- 2D router 语义
- runtime controller 在线热切换

## 4. 方案对比

### 方案 A：继续沿用旧 payload，只在 decode 侧推断 `block_d`

优点：

- 改动最小

缺点：

- 接口层仍不是 3D-native
- packet 仍不自描述
- 无法真正回答“接口上是不是 3D”

结论：不采用。

### 方案 B：直接重写所有 SpikeKey / SpikeTile / bundle 协议

优点：

- 最干净

缺点：

- 改动范围过大
- 容易打碎现有 smoke/workload 验证链

结论：当前阶段不采用。

### 方案 C：新增显式 3D wire contract，并保留旧 decode 兼容

优点：

- 明确把 `block_d` 下沉到 packet contract
- 改动集中在目标链条
- 真实 smoke 风险可控

缺点：

- 一段时间内会同时存在旧版与新版 wire/bundle 版本

结论：采用此方案。

## 5. 目标接口形态

### 5.1 `ISynapseRoute`

新增：

- `virtual uint32_t multicastBlockD() const = 0;`

扩展：

- `BlockTarget` 增加 `block_d`

语义：

- 2D/legacy 实现返回 `1`
- 3D route 实现返回有效的 volumetric block depth

### 5.2 SpikeKey wire contract

新增显式 3D fixed route header（新版本）：

- packet 直接携带 `block_w/block_h/block_d`
- `decodeSpikeKeyAny()` 将 `block_d` 通过 `DecodedSpikeKeyMeta` 暴露给上层

兼容策略：

- `V1/V2/V3` 仍可 decode，默认 `block_d=1`
- 新 3D SpikeKey 发射优先走显式 3D 版本

### 5.3 structured inter-bundle contract

新增显式 3D bundle 版本：

- prefix 显式携带 `block_w/block_h/block_d`
- entry meta 显式携带 `block_z`
- 不再把 3D 元数据塞进 `reserved` 位

## 6. 数据流变化

升级后数据流为：

1. `SynapseRouteSubsystem3D` 产出 `BlockTarget{block_id, ingress_node, block_z, block_d, core_mask}`
2. `SpikeCommSubsystem` 从 `ISynapseRoute` 读取 `W/H/D`
3. 发送端发出显式 3D SpikeKey / bundle
4. `MulticastRouter3DNative` decode 后从 payload meta 读取 `block_d`
5. router 依据 packet-level volumetric contract 执行 `INTER_Z -> INTER_XY -> INTRA_3D`
6. `TrafficWorkload / SnnWorkload` 继续能 decode 并完成自检/消费

## 7. 验证目标

本轮闭环实验至少覆盖三层：

1. 契约测试：
- `ISynapseRoute` 暴露 `multicastBlockD`
- `SpikeCommSubsystem` 使用 3D interface
- router 使用 packet-level `block_d`

2. codec/build 级测试：
- 显式 3D SpikeKey round-trip
- 显式 3D structured bundle round-trip

3. 真实 smoke：
- 重新构建 SnnDL
- 运行 `full_3d_runtime_adaptive` 或 `full_3d` 的 SST smoke
- 确认 `status=smoke_passed`
- 确认 joint/runtime summary 继续成立

## 7.1 2026-04-01 代码对齐补充

截至当前主线代码，这条 `ISynapseRoute -> SpikeCommSubsystem -> MulticastRouter3DNative` 链已经不只完成了 packet-level 3D contract，还向上扩展到了 route authority contract：

1. `ISynapseRoute` 现在不只暴露 `multicastBlockD()` 与 `BlockTarget.block_d`，还暴露 `RouteSemanticDescriptor`
2. `SynapseRouteSubsystem3D::describeRouteSemantics()` 现在会显式区分：
   - `source_semantics_authority`
   - `source_primary_kind`
   - `native_bootstrap_source`
3. 在 `native_3d + edges_csv + real synapse inputs` 的主线 case 下，当前最新语义已经不是简单的 `edges_csv_bootstrap`，而是：
   - `source_semantics_authority = native_3d_route_table`
   - `source_primary_kind = native_3d_route_table_with_real_synapse_inputs`
   - `native_bootstrap_source = edges_csv`

这意味着当前实现已经把：

- source authority
- bootstrap provenance
- 3D packet contract

三者显式分离开，而不是继续把“route table 初始化来源”误写成“当前 source-side fanout 的主语义”。

同时，Python artifact 主链也已经对齐这条 contract：

- `snn3dexp/platform/sst_graph.py`
- `snn3dexp/tools/analyze_route_memory_joint.py`
- `snn3dexp/tools/run_case.py`

真实 `full_3d_runtime_adaptive --run-tag authority_native_source_20260401 --sst-smoke --stop-at 250ns` 已通过，并在 artifact 中稳定落出新的 native-source authority。

## 8. 非目标

本轮不处理：

- SpikeTileKey 全量显式 3D route prefix 重构
- runtime epoch 内在线 remap 执行
- monolithic-like memory 主后端化
- paper artifact 结构再扩展

## 9. 结论

这轮最关键的成果不是“再加一个 3D feature”，而是把 `ISynapseRoute -> SpikeCommSubsystem -> MulticastRouter3DNative` 从“共享隐式配置的 3D prototype”升级成“以接口、packet contract、source authority descriptor 为中心的 3D multicast kernel”。

只有把这一步做完，我们后续的：

- 3D volumetric multicast statistics
- runtime adaptive remap
- route-memory-mapping co-design

才会建立在一个真正 3D-native 的研究基座之上。
