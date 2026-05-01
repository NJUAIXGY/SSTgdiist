# services/（可复用服务/子系统）

本目录存放 **可复用的“事务子系统（subsystems）”**，用于把 `control/` 与 `components/` 中的复杂事务逻辑逐步下沉，并通过 `api/` 中的窄接口与上层交互。

> 目标：`MultiCorePE`/`SnnPESubComponent` 越来越像“装配/调度壳”，而不是承载权重、路由、NoC、Stimulus 等事务细节。

---

## 内存建模口径（默认 cacheline）

在 `services/` 的子系统边界内：

- `services/memory` 只做 `addr + size ↔ bytes`（不携带权重/突触语义），并默认按 memHierarchy 的 cacheline 事务模型理解“系统层流量”。
- 若某子系统（例如 GAS 的内存前端）改变了合并粒度（可能引入 over-fetch），必须通过 `gas_unique_* / avg_granule_bytes` 等指标显式暴露，并在实验输出中标注有效参数（见 mesh 模板的 `effective_config.json`）。
  - 建议最小口径：`unique_reads/unique_bytes` 及其派生指标（例如 `avg_granule_bytes`）。

---

## 子域目录（按边界拆分）

- `services/noc/`：NoC 传输域（send/recv/forward/本地投递），实现 `api/INocTransport.h`  
  - 详见：`services/noc/README.md`
- `services/memory/`：纯内存访问域（地址→字节块），实现 `api/IMemoryAccess.h`  
  - 详见：`services/memory/README.md`
- `services/synapse/`：突触语义域（Synapse 事务闭环：weights/route/gas 的聚合域；阶段机业务动作在 workload=snn）  
  - 详见：`services/synapse/README.md`
- `services/stimulus/`：Stimulus 刺激/注入域（Step 注入/外部刺激）  
  - 详见：`services/stimulus/README.md`
- `services/workload/`：Workload 插件域（`snn`/`stream` 等），承载业务状态机与执行主链路  
  - 详见：`services/workload/README.md`
- `services/legacy/`：历史遗留/参考实现（默认不参与主链路构建）  
  - 详见：`services/legacy/README.md`

---

## 目录根部文件

- `services/SnnProfiler.h`：轻量 profiling（条件编译），供多个域复用。

---

## 依赖边界（强烈建议）

- 允许依赖：`api/`、`events/`、标准库与少量 SST 基础类型（`SST::Output`、`SST::Link`、`SST::Statistics` 等）。
- 避免：services → control 的反向依赖（尤其是窥探 `SnnPESubComponent` 私有成员）。
- 域间边界应保持清晰：
  - NoC 不做 fanout/权重语义；
  - Memory 不出现权重/突触/路由语义；
  - Synapse 不直接操纵 NoC 具体实现（通过 api 交互）；
  - Synapse 内部：Route 不解析权重 bytes，Weights 不做 NIC/NoC 事务。
