# components/（SST 组件集成层）

本目录存放 **SST 可加载的组件/子组件实现**（ELI 注册对象），它们负责与 SST 框架对接：端口、Link、Clock、Stat、init/setup/finish 生命周期等。

## 职责

- 提供完整可运行的 SST 元素（Components/SubComponents），并将下层模块装配成系统。
- 管理网络互连、内存前端、权重加载、门控组件等系统级职责。

## 主要内容

- `MultiCorePE.{h,cc}`
  - 处理单元（PE）顶层组件：挂接多个 **CoreShell** 子核（接口：`api/CoreShellAPI.h`，默认实现：`control/SnnPESubComponent`）。
  - 负责装配并驱动平台面子系统（NoC/Mem/Stimulus），以及对 PE 内多 core 的统计汇聚（写出到 `mesh_stats.csv`）。
  - 支持可插拔 workload：通过参数 `workload_impl` 或环境变量 `SNNDL_WORKLOAD_IMPL` 选择（默认 `snn`）。
- `multicore/MultiCorePEConfig.{h,cc}`
  - 仅用于 **构造期参数解析收敛**：把 `params.find(...)` 噪音从 `MultiCorePE.cc` 中搬出（不新增运行期组件/装配点）。
- `SnnNIC.{h,cc}`
  - NIC 组件：对接 `SimpleNetwork`（如 merlin.linkcontrol），发送/接收 Spike 与门控事件。
- `WeightLoader.{h,cc}`
  - 权重加载组件：通过内存接口将权重预置到 DRAM/缓存可见区域。
- `GatherBufferIF.{h,cc}`
  - GAS window 驱动的 StandardMem 前端（用于 Gather/Apply/Scatter 的窗口化时序）。
- `gather/GatherBufferIFConfig.{h,cc}`
  - 仅用于 **构造期参数解析收敛**：把 `params.find(...)` 噪音从 `GatherBufferIF.cc` 中搬出（不新增运行期组件/装配点）。
- `GatingPE.{h,cc}`
  - 门控组件：生成/传播 `GatingDecisionEvent`，控制 fanout 目的集合。
- `stimulus/SpikeSource.{h,cc}`
  - 可选 spike 源（在部分实验脚本中可能禁用）。
- `MemKCalBench.{h,cc}`
  - micro-benchmark：用于 K 校准或 memory 访问特征测试。
- `SnnPE.{h,cc}`
  - 旧架构兼容组件（deprecated/compat），新功能优先在 MultiCorePE 体系演进。

---

## 内存建模口径（默认 cacheline）

在 memHierarchy（cacheline 事务）语义下，本项目默认将 **cacheline** 作为系统层搬运/统计粒度：

- **L2 traffic 主口径**：`pe_*_memory_controller.requests_received_*`（GetS/GetX/...）；
- **L1 logical 辅助口径**：`memory_requests/mem_req_size_bytes`（上层发起的逻辑请求形态）；
- `GatherBufferIF` 会改变“请求合并/去重/粒度”（可能引入 over-fetch），因此对照实验必须同时观察：
  - `gas_unique_reads_total/gas_unique_bytes_total`（GAS 唯一合并读覆盖字节/事务）
  - `avg_granule_bytes`（dense+cacheline 模式下应接近 `line_size_bytes`）

mesh 模板会在每次运行目录写出 `effective_config.json`（并汇总进 `essential_summary_mesh.json` 的 `model.effective`），用于记录最终生效的合并/粒度参数，避免配置文件与实际行为不一致导致误读。

此外，`GatherBufferIF` 在 Apply 阶段支持可选的 DRAM-aware 发射策略（`apply_issue_policy=bank_rr_row_sticky_age|dram_aware_v1|cmd_aware_v1`）。其中
`cmd_aware_v1` 为实验性策略，默认关闭，需与主线口径隔离。该策略依赖
`bank_bits/bank_shift/row_bytes_guess` 的 bank×row 映射口径；使用 Ramulator2 时建议显式校准并固定（见 `components/gather/README.md`）。

## 子目录

- `components/stimulus/`：Stimulus 域的注入型组件（例如 `SpikeSource`）。
- `components/mpi/`：MPI 扩展相关组件与类型（可选编译）。
- `components/noc/`：ELI 可加载的 NoC/拓扑适配组件（高级/实验性用途，默认推荐 `SnnNIC`）。
- `components/gas/`：全局 Step/GAS 同步组件（Mesh barrier 控制面）。
- `components/multicore/`：MultiCorePE 参数解析收敛模块（纯编译期组织，不新增 ELI 对象）。
- `components/gather/`：GatherBufferIF 参数解析收敛模块（纯编译期组织，不新增 ELI 对象）。
- `components/workload_stats/`：workload 统计模块注册表与实现（tensor/stream 等）。

## 依赖边界（建议）

- `components/` 可以依赖 `api/`、`events/`、`control/`、`services/`、`compute/`。
- 避免把业务语义写进组件层：
  - 动力学/学习应下沉到 `compute/`；
  - SNN/Step/GAS/BCSR 等事务应下沉到 `services/workload/snn` 与 `services/synapse/*`；
  - NoC/Mem 在组件层只做“装配与调度壳”。

## 扩展指南

- 新增 SST 组件时：
  - 保持 ELI 注册信息（库名/组件名/参数文档）与现有脚本兼容；
  - 业务逻辑尽量委托给 `control/` 或 `compute/`，组件层只做装配与资源管理。
