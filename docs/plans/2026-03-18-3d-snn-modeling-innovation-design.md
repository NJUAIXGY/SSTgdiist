# 3D SNN 建模创新深化设计

Date: 2026-03-18
Owner: Fufu
Status: Draft

## 1. 背景与目标

我们当前已经在隔离的 `snn3dexp/` 预研树中完成了第一阶段的 3D SNN 架构级原型：

- `SnnDL.MulticastRouter3DNative` 已支持 `up/down`、`WxHxZ`、`z-first`
- `SynapseRouteSubsystem3D` 已支持 3D block/ingress 映射与 3D-aware multicast target 组织
- memory side 已支持 `HBM-like shared stack`、`xy_quadrant` homing、`z` 感知 attach latency
- canonical ablation cases 已具备 `baseline_2d / memory_only_3d / noc_only_3d / full_3d`
- `full_3d` 与 `memory_only_3d` 在 `balanced_20us` 下都已完成 smoke，且 stack-level imbalance 已回到 `1.0`

这说明我们已经拥有一个可运行的 3D substrate 原型，但还没有形成“足以支撑论文创新主张”的完整建模框架。

本设计文档的目标不是重复已有实现，而是回答四个更高层的问题：

1. 从论文视角看，我们当前模型处在什么层级
2. 现有 `3D + neuromorphic` 论文为什么大多偏半导体/器件，而不是 architecture
3. 我们最有价值的创新切入点是什么
4. 如何把当前原型升级为一个可持续扩展、可做系统性实验、可形成论文叙事的 3D SNN 建模平台

结论先行：

- 这个方向值得继续做
- 但定位必须明确为 `device-informed architecture-level 3D neuromorphic modeling`
- 我们的主张不应是“做出 monolithic 3D neuromorphic chip”
- 而应是“建立一个面向 3D neuromorphic system co-design 的架构级研究平台，并在其上提出可验证的 3D routing / memory / mapping/runtime 创新”

## 2. 论文脉络与研究空白

### 2.1 经典类脑芯片论文的重心

经典 neuromorphic 芯片工作并不只强调神经元数量，更强调完整系统栈：

- TrueNorth 强调可扩展的 event-driven routing、mapping/tool flow 与系统级 CAD 方法 [1]
- Loihi/Loihi 2 强调可编程神经元、on-chip learning、以及软件框架与部署环境 [2][3]
- SpiNNaker 的代表性贡献不仅是 manycore 硬件，还包括 PyNN-compatible software/runtime 生态 [4]

也就是说，architecture 社区认可的类脑芯片论文，通常至少覆盖：

- communication substrate
- memory / state organization
- mapping/runtime/software
- workload deployment and evaluation

### 2.2 3D 方向论文为什么偏半导体

现有 `3D + neuromorphic` 文献确实更偏器件、工艺、封装和集成：

- monolithic / wafer-bonding / heterogeneous integration [5][6]
- 2D materials、memristor、synaptic device、vertical integration [7]

这类论文的核心问题是：

- 3D 工艺如何实现
- 器件能否稳定工作
- memory window / retention / variability / integration yield 是否可接受

而不是：

- 3D multicast 应如何定义
- 3D stack memory 与 SNN synapse traffic 如何协同
- 3D thermal / routing / mapping 是否需要联合优化

这恰恰暴露了 architecture 层的空白：目前缺少一个足够真实、但又不强依赖具体工艺的 3D SNN 系统建模平台。

### 2.3 与我们最接近的论文方向

和我们最接近的不是纯器件论文，而是三类交叉工作：

1. 经典 neuromorphic architecture
- 提供“系统级类脑芯片应该建模到什么程度”的参考标准 [1][2][3][4]

2. 3D stacked memory / NMC / PIM
- 提供“3D memory system 可以怎样在 architecture 层被合理抽象”的参考 [8][9][10]

3. 3D-NoC-based SNN / hardware-aware SNN mapping
- 提供“3D 拓扑、路由、映射、workload”之间关系的启发 [11][12][13]

因此，最有研究价值的切入点不是追逐器件 novelty，而是把这三条线真正耦合起来。

## 3. 对当前实现的定位

我们当前更准确的定位是：

`architecture-level 3D neuromorphic substrate prototype`

而不是：

`full-stack 3D neuromorphic chip model`

### 3.1 已经具备的能力

1. 3D native transport substrate
- `MulticastRouter3DNative` 已实现 `WxHxZ`、`up/down`、`z-first`、vertical-aware unicast 与 spike ingress forwarding

2. 3D-aware route organization
- `SynapseRouteSubsystem3D` 已支持 3D block 组织、3D ingress node 选择、3D-aware multicast target 生成

3. HBM-like near-memory hierarchy
- 已支持 `shared stacks + channels + interleave + homing + vertical attach latency`
- 已明确定位为 `HBM-like NMC`，不是 `PIM`

4. 隔离良好的实验平台
- `snn3dexp/` 已形成独立 case catalog、builder、runner、analysis 和 test tree

5. 初步实验闭环
- 2D/3D、NoC-only/Memory-only/full-3D 的消融框架已经存在
- balanced synthetic traffic 下，shared stacks 的压力分布已可控

### 3.2 明确仍未完成的部分

1. route synthesis 仍未完全 3D-native
- `computeFanout()` 与 route map 的核心生成逻辑仍委托 legacy subsystem

2. multicast 仍非真正 3D volumetric
- 当前 block 仍然是 `die-local 2D block`
- router 的 3D 只覆盖 inter-die transport，不覆盖 3D block semantics

3. memory datapath 仍未完全业务化
- 当前主要验证的是 shared stack graph 与 synthetic/probe traffic 的建图与 smoke
- 还不是 “PE/NIC 发真实 synapse traffic 到 home stack”的最终业务通路

4. 没有 thermal / power / physical-3D model
- 无 TSV/MIV、micro-bump、thermal hotspot、yield、clocking、IR drop、vertical bandwidth budget 抽象

5. 没有 3D-aware runtime/software story
- 缺少 mapping、placement、routing、memory homing、thermal budget 的联合优化框架

## 4. 创新主张重构

我们不建议把创新表述为“我们也做一个 3D neuromorphic chip”。

更合理、更有差异化、也更可落地的创新主张应重构为：

### 4.1 主主张

`提出一个面向 3D SNN 的系统级建模与协同优化框架，在统一平台中同时建模 3D native multicast fabric、HBM-like near-memory synapse hierarchy、以及 3D-aware mapping/runtime policies。`

### 4.2 三个可独立成创新点的子主张

#### 创新 A：3D Native Multicast Semantics，而不是仅仅 3D Router

现在我们只有 3D transport，还没有完整 3D multicast semantics。

下一步创新不应只停留在 `up/down` 链路，而应升级为：

- 3D volumetric block
- 3D ingress selection
- vertical subtree-aware multicast replication
- die-local / cross-die multicast cost split

这会把贡献从“支持 3D mesh”升级成“定义 3D SNN multicast primitive”。

#### 创新 B：HBM-like NMC for Synapse-Centric SNN

当前 shared stack 已经证明能建图和跑通，但还缺少真正服务 SNN synapse path 的体系结构叙事。

可升级为：

- 以 synapse gather / metadata lookup / sparse window access 为中心定义 memory flow
- 引入 `home stack hit / remote stack fallback / vertical memory distance` 这些 SNN-specific metrics
- 形成 `HBM-like NMC is sufficient / when PIM becomes necessary` 的量化判断

这能把我们与泛化的 3D memory 论文区分开。

#### 创新 C：3D Route-Memory-Mapping Co-Design

这是最值得押注的一点。

现有文献往往分开讨论 NoC、memory 或 devices；而我们可以把三者放到同一个研究问题中：

- 哪些神经元/群组应共层部署
- 哪些 block 应优先层内扩散，哪些应跨层汇聚
- 哪种 homing policy 最能平衡 stack pressure 与 route cost
- 在 thermal budget 下，是否需要把热点 layer 映射到特定 tier/stack 区域

如果做出来，这会是“纯器件论文”和“纯 NoC 论文”之间很强的系统创新桥梁。

## 5. 下一阶段的目标平台形态

建议把当前原型升级到一个明确命名的目标形态：

`Snn3DExp Phase-2: 3D Neuromorphic Co-Design Platform`

它应至少包含六个层面。

### 5.1 Layer 1: Full 3D Multicast Kernel

目标：

- 从“3D-aware 包装层”升级为“真正的 3D-native 路由内核”

要求：

- `SynapseRouteSubsystem3D` 不再依赖 legacy 2D fanout synthesis 作为主路径
- block encoding 从 `2D block` 扩展为 `3D volumetric block`
- inter-bundle / ingress selection 的 3D 语义与 router 保持一致

交付物：

- 3D route synthesis API
- 3D block encoder / decoder
- 3D multicast correctness tests

### 5.2 Layer 2: Real Synapse-to-Stack Data Path

目标：

- 从“stack graph/probe 验证”升级为“真实 synapse memory traffic”

要求：

- 把 PE / synapse gather path 与 `home stack` 真正对接
- 区分：
  - local tier-local stack access
  - local XY but upper-tier access
  - remote home access
- 对 shared bus / controller / backend contention 进行真实统计

交付物：

- synapse request source attribution
- per-stack / per-channel traffic stats
- route-memory joined timeline summary

### 5.3 Layer 3: 3D-Aware Mapping and Placement

目标：

- 让 3D 结构不只是“硬件存在”，而是“软件可利用”

要求：

- mapping policy 同时考虑：
  - spike communication locality
  - memory homing locality
  - vertical hop cost
  - tier thermal budget
- 提供至少三类 placement baseline：
  - flat 2D-aware mapping
  - z-blind 3D mapping
  - full 3D-aware co-optimized mapping

交付物：

- 3D placement cost model
- mapping policy interface
- 与 `snn3dexp` case catalog 对接的 mapping ablation cases

### 5.4 Layer 4: Thermal and Physical-3D Proxy Model

目标：

- 在不下沉到工艺仿真的前提下，引入必要的 physical realism

建议采用 proxy model，而不是完整热仿真：

- vertical link energy proxy
- per-tier activity density proxy
- per-stack bandwidth saturation proxy
- thermal hotspot score
- TSV/MIV budget proxy

这一步的价值不在于“精确热结果”，而在于阻止架构研究落入不现实的最优解。

### 5.5 Layer 5: Unified Evaluation Methodology

目标：

- 让 `3D` 不只意味着多一维拓扑，而是带来一套新的可复现实验指标

核心指标建议：

- route metrics
  - average spike hops
  - vertical hops ratio
  - ingress replication cost
  - inter-die multicast fanout
- memory metrics
  - stack hit ratio
  - remote-home ratio
  - per-stack imbalance ratio
  - per-channel utilization
- joint metrics
  - spike-to-synapse service latency
  - route-memory contention overlap
  - vertical locality score
  - thermal-pressure score
- outcome metrics
  - throughput
  - effective work per joule proxy
  - saturation point

### 5.6 Layer 6: Paper-Ready Baseline Suite

建议固定一组 baseline：

1. `baseline_2d`
- 2D router + legacy per-PE memory

2. `memory_only_3d`
- 2D semantics + HBM-like shared stack

3. `noc_only_3d`
- 3D native router + legacy memory

4. `full_3d`
- 3D native router + HBM-like shared stack

5. `full_3d + 3d_mapping`
- full_3d + 3D-aware placement

6. `full_3d + thermal_guard`
- full_3d + thermal-aware mapping/runtime

7. `future_pim_proxy`
- 可选，不作为近期主线

## 6. 建议的创新路线图

### Phase A: 完成 3D NoC 语义闭环

研究问题：

- 我们的 3D router 目前只是“3D transport”还是“3D multicast architecture”

任务：

- 3D volumetric block encoding
- 3D-native fanout synthesis
- inter-bundle 3D forwarding 完整化

成功标准：

- `computeFanout()` 不再依赖 legacy 2D 主路径
- cross-die multicast correctness 具备完整 tests
- 可输出真正 3D multicast statistics

### Phase B: 完成 memory 业务路径闭环

研究问题：

- HBM-like NMC 对 SNN 的帮助究竟来自带宽、近存距离，还是共享 stack 资源重组

任务：

- 打通真实 PE/NIC -> home stack 的 synapse request path
- 明确 shared stack 的服务对象、地址空间与统计口径
- 支持 `ramulator2` 作为主验证后端

成功标准：

- 不再主要依赖 `MemKCalBench probe`
- stack/channel/backend 压力来自真实业务流量
- 输出 memory-bound / route-bound 联合瓶颈分析

### Phase C: 引入 3D-aware mapping/runtime

研究问题：

- 单独升级 NoC 或 memory 是否足够，还是必须做联合 co-design

任务：

- 设计 3D placement cost model
- 引入 homing-aware / thermal-aware mapping policy
- 做多 workload 的 design-space sweep

成功标准：

- 至少出现一个稳定场景：`full_3d + 3d_mapping` 优于 `full_3d` 默认配置
- 改善不只体现在单一指标，而是 route + memory 两侧同时受益

### Phase D: 引入 physical realism proxy

研究问题：

- 3D 架构最优解在热/垂直资源约束下是否仍成立

任务：

- thermal proxy
- vertical bandwidth budget
- stack hotspot penalty

成功标准：

- 形成“理想 3D 最优解”和“受 physical budget 约束后的可行解”的对比

## 7. 论文选题建议

### 选题 1：系统架构主线

题目方向：

`A 3D Neuromorphic System Modeling Platform with Native Multicast and HBM-like Near-Memory Synapse Hierarchy`

适用前提：

- Phase A + Phase B 完成

核心卖点：

- 平台
- 完整方法学
- route + memory 双路径建模

### 选题 2：机制创新主线

题目方向：

`3D Native Multicast for Stacked Neuromorphic Fabrics`

适用前提：

- Phase A 完成得足够扎实

核心卖点：

- 3D volumetric multicast
- 3D fanout synthesis
- 与 2D blocked/native multicast 的系统性对比

### 选题 3：联合优化主线

题目方向：

`Co-Design of 3D Routing, Memory Homing, and Mapping for Stacked Spiking Neural Network Systems`

适用前提：

- Phase A + B + C 完成

核心卖点：

- 最有论文差异化
- 与现有偏器件的 3D neuromorphic 文献错位竞争

浮浮酱推荐优先押注选题 3，因为它最能体现我们当前代码基础的独特性。

## 8. 边界与非目标

为了避免研究目标扩散，建议明确以下非目标：

- 不主打 monolithic 3D 工艺创新
- 不主打新型 synaptic device 或 memristor 器件结果
- 不在近期主线中把全部计算下沉到 memory stack，避免过早转向 PIM
- 不追求 cycle-accurate thermal signoff 或 full physical implementation

我们要做的是：

- architecture-realistic
- device-informed
- experimentally reproducible

而不是：

- fabrication-accurate

## 9. 推荐的近期执行顺序

建议严格按以下顺序推进，避免同时打开太多战线：

1. 先做 `3D multicast semantics closure`
- 这是 NoC 主线的内核问题
- 不解决它，3D 仍只是拓扑升级

2. 再做 `real synapse memory datapath`
- 不解决它，HBM-like NMC 仍主要停留在 memory graph 验证

3. 然后做 `3D-aware mapping/runtime`
- 这是从“功能实现”走向“研究创新”的关键跃迁

4. 最后补 `thermal/physical proxy`
- 它是 realism guard，不是第一性创新点

## 10. 立即可执行的 TODO

### TODO-A: 3D 路由内核

- 将 `SynapseRouteSubsystem3D` 从 legacy fanout 包装层升级为 3D-native synthesis
- 定义 `3D volumetric block` 编码格式
- 明确 `INTER_Z / INTER_XY / INTRA_3D` 的包级语义

### TODO-B: 真实 memory 数据通路

- 明确 `PE -> GatherBufferIF/L1 -> stack bus -> channel controller -> backend` 的业务路径
- 将真实 synapse traffic 接入 `home stack`
- 建立 stack/channel 级联合统计

### TODO-C: 3D-aware mapping

- 设计 3D placement objective
- 把 `route cost + memory homing cost + thermal proxy` 统一进一个打分函数
- 增加 `mapping_only` / `mapping+thermal` case

### TODO-D: 论文实验框架

- 固定 workload 组与输入规模
- 固定 baseline suite
- 固定主图指标和附录指标

## 11. 设计结论

现有 `3D + neuromorphic` 论文偏半导体，不是坏事，反而给了我们 architecture 路线的机会窗口。

我们的最佳策略不是和器件论文比“谁更像真实芯片工艺”，而是：

- 以当前 `HBM-like NMC + 3D native multicast` 原型为起点
- 把 3D router、3D memory、3D mapping/runtime 真正耦合起来
- 形成一个有明确边界、能持续扩展、且能稳定做消融对比的架构级平台

如果这个路线执行到位，我们最有机会做出的，不是一篇泛泛的“3D SNN survey-like work”，而是一篇真正有系统创新抓手的 architecture 论文。

## 12. References

[1] TrueNorth: Design and Tool Flow of a 65 mW 1 Million Neuron Programmable Neurosynaptic Chip  
https://research.ibm.com/publications/truenorth-design-and-tool-flow-of-a-65-mw-1-million-neuron-programmable-neurosynaptic-chip

[2] Loihi: A Neuromorphic Manycore Processor with On-Chip Learning  
https://www.researchgate.net/publication/322548911_Loihi_A_Neuromorphic_Manycore_Processor_with_On-Chip_Learning

[3] Taking Neuromorphic Computing to the Next Level with Loihi 2 Technology Brief  
https://www.intel.com/content/dam/www/central-libraries/us/en/documents/neuromorphic-computing-loihi-2-brief.pdf

[4] sPyNNaker: A Software Package for Running PyNN Simulations on SpiNNaker  
https://pmc.ncbi.nlm.nih.gov/articles/PMC6257411/

[5] Three-dimensional monolithic integrated neuromorphic hardware system after wafer bonding  
https://pubmed.ncbi.nlm.nih.gov/38884186/

[6] The 3D Monolithically Integrated Hardware Based Neural System with Enhanced Memory Window of the Volatile and Non-Volatile Devices  
https://pmc.ncbi.nlm.nih.gov/articles/PMC11336934/

[7] 2D materials-based 3D integration for neuromorphic hardware  
https://www.nature.com/articles/s41699-024-00509-1

[8] NeuroStream: Scalable and Energy Efficient Deep Learning with Smart Memory Cubes  
https://arxiv.org/abs/1701.06420

[9] A Modern Primer on Processing in Memory  
https://arxiv.org/abs/2012.03112

[10] Near-Memory Computing: Past, Present, and Future  
https://sstuijk.estue.nl/publications/micpro19.pdf

[11] Light-weight Spiking Neuron Processing Core for Large-scale 3D-NoC based Spiking Neural Network Processing Systems  
https://eprints.uet.vnu.edu.vn/eprints/id/eprint/3907/1/Light-weight%20Spiking%20Neuron%20Processing%20Core%20for%20Large-scale%203D-NoC%20based%20Spiking%20Neural%20Network%20Processing%20Systems.pdf

[12] Hardware-aware liquid state machine generation for 2D/3D Network-on-Chip platforms  
https://www.sciencedirect.com/science/article/abs/pii/S1383762122000297

[13] Neuromorphic computing at scale  
https://labs.dese.iisc.ac.in/neuronics/wp-content/uploads/sites/16/2025/01/s41586-024-08253-8.pdf
