# services/memory/（纯内存访问子系统）

本目录存放 **Memory 域（纯地址/字节语义）** 的实现，目标是把 StandardMem 的请求发起、pending 跟踪、回包分发收敛为可复用模块，并避免在内存层引入任何 “突触/权重/路由” 语义。

> 边界原则：Memory 只处理 “`addr + size` ↔ `bytes`”，不解释 payload 不做 BCSR 解析。

---

## 目录结构与组件职责

### `StandardMemAccess.{h,cc}`（推荐主入口）
- **定位**：`api/IMemoryAccess.h` 的 StandardMem 实现，负责：
  - 构造 `StandardMem::Read/Write` 请求并 `send()`；
  - 以 `RequestId` 为 key 维护 pending；
  - 在收到 `ReadResp` 时做 **尺寸断言式检查**（`resp_bytes < req_bytes` 直接 `fatal`），再回调上层。
- **关键 API**：
  - `read(addr, bytes, cb)`：cb 形态为 `cb(req_id, addr, data_bytes)`；
  - `write(addr, data, cb)`：cb 形态为 `cb(req_id, addr)`；
  - `handleMemoryResponse(req*)`：用于把 StandardMem 回包分发到对应回调（并释放请求对象）。
- **注意事项**：
  - `ReadResp` 的 `data.size()` 必须覆盖请求的 `bytes`，否则会触发 `[stdmem-access-assert]` 直接 fail-fast；这用于尽早暴露地址映射/对齐/截断问题。
  - 回包匹配默认以 `RequestId` 为准；若上游/后端导致 `resp_id` 不匹配，允许在 **无歧义** 情况下按 `(addr,size)` 唯一回退匹配（若歧义将 fail-fast）。

### Legacy（已从 Memory 域移出）
- `services/legacy/memory/StandardMemBackend.*`：历史 pending 后端（含权重/BCSR 语义字段），已在 Phase5.5 清理删除；主链路统一使用 `StandardMemAccess`。

---

## 与其他域的交互（典型用法）

- CoreShell（`control/SnnPESubComponent`）在 `setup/init` 时装配：
  - 创建 `StandardMemAccess`（对外提供纯 `IMemoryAccess`）；
  - 旧的 pending/meta 参考实现（`services/legacy/memory/StandardMemBackend.*`）已删除；若需要对照口径，应以 `StandardMemAccess` 的 diag/断言式诊断为准。
- `services/synapse/weights/WeightMemorySubsystem` 推荐只依赖 `api/IMemoryAccess`：
  - Memory 负责返回 bytes；
  - Weights 负责解释 bytes（例如 float 解码、rowptr/colidx/blockdata 解析）。

---

## 约束与建议

- **禁止**：在 `services/memory` 里出现 `weight/synapse/bcsr/route` 的业务语义。
- **建议**：任何回包解析（float/idx 解码）放到 `services/synapse/weights` 的语义层；Memory 只保证“正确的字节块”。

---

## 内存建模口径（默认 cacheline）

Memory 域不负责“粒度语义”，但项目默认的体系结构抽象是 memHierarchy 的 cacheline 事务模型：

- 论文/报告的 traffic 主口径应以 MemController 的 `requests_received_*` 为准（L2 traffic，近似 off-chip）。
- `memory_bytes/memory_requests` 表示上层发起的逻辑请求（L1），用于解释合并/去重形态，不应直接等价为 DRAM 流量。
