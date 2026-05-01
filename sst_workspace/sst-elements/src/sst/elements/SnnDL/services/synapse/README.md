# services/synapse/（突触语义域：Synapse 事务闭环）

本目录存放 **与“突触语义（synapse semantics）”强相关** 的事务子系统：权重（weights）、路由/可达性（route）、以及 GAS 窗口辅助（gas）。

> 目标：将“fanout/可达性/路由构建、权重读取与缓存、GAS 辅助数据结构”收敛到一个清晰的 Synapse 域；让 NoC 保持纯传输、Memory 保持纯字节访问，Control/Component 只做装配与调度壳。

---

## 内存建模口径（默认 cacheline）与 Synapse 域的职责

Synapse 域会影响“读粒度/合并策略”（例如 GAS 的 granule 合并、权重访问局部性），因此必须把口径说清楚：

- 默认通用体系结构语义：cacheline（memHierarchy）事务是 L2 traffic 的基本单位。
- 若 Synapse 侧策略导致下游按更大 granule（row/块）读，会引入 over-fetch；必须通过 `gas_unique_reads_total/gas_unique_bytes_total/avg_granule_bytes` 显式暴露，并在实验输出中标注有效参数（`effective_config.json`）。

---

## 子域目录

- `services/synapse/weights/`：权重语义与缓存子系统（dense/BCSR/窗口读编排），实现 `api/SnnWeightReader.h`
  - 详见：`services/synapse/weights/README.md`
- `services/synapse/route/`：Synapse/Route 路由与通信事务子系统（路由构建、fanout、gating、SpikeEvent 构造与发送）
  - 详见：`services/synapse/route/README.md`
- `services/synapse/gas/`：GAS 窗口与累加辅助子系统（edge 收集、累加器、CustomCmd/统计载体）
  - 详见：`services/synapse/gas/README.md`
- `services/synapse/common/`：Synapse 域公共工具（BCSR `.meta.json` 解析与校验等口径）
  - 详见：`services/synapse/common/README.md`
- `services/synapse/stdmem/`：StandardMem 胶水层（隔离 `StandardMem::*`，避免污染 `control/`）
  - 详见：`services/synapse/stdmem/README.md`

---

## 依赖边界（建议）

- `synapse/*` **可以依赖**：`api/`、`events/`、少量 SST 基础类型、以及 `services/memory`（通过 `api/IMemoryAccess`）。
- `synapse/*` **不应依赖**：`services/noc` 的具体实现（应通过 `api/ISpikeTransport` / `api/INocTransport` 交互）。
- `services/memory` **不出现**：权重/突触/路由语义；它只负责“地址→字节块”。
