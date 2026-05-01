# services/legacy/（历史遗留/参考实现）

本目录存放 **不参与当前主链路（默认不纳入构建）的 legacy/参考实现**。它们用于：
- 对照历史行为；
- 保留曾经的实现思路与调试工具；
- 为后续重构提供回归参考（但不应被新功能继续依赖）。

> 使用原则：如需启用 legacy 文件，应先确认其依赖边界（不得反向依赖 control 私有成员），并在启用前完成 100us 回归验证。

## 默认内存语义（cacheline）

Legacy 目录内容用于“行为对照”，并不代表当前主链路的体系结构口径。当前主链路默认以 **cacheline 粒度**作为对外搬运/统计单位（对齐 `memHierarchy`）。如 legacy 参考中
出现 row-streaming/DMA 或更大 granule 读的假设，应被视为“历史/实验假设”，不能默认混入当前结论。

---

## 目录结构与组件职责

### `control/StageEventHub.{h,cc}`（已迁入 legacy）
- **定位**：历史的 GAS 阶段事件调度与统计汇报助手（BeginGather/BeginApply/BeginScatter/EndScatter）。
- **现状**：已在 Phase5.2-A1 被吸收进 `control/SnnPESubComponent_impl.h` 的 `SnnPESubComponent::Impl`；旧实现迁入 `services/legacy/control/StageEventHub.*` 仅用于对照参考（不参与主链路构建）。

### `ReadOrchestrator.{h,cc}`（已删除）
- **定位**：历史窗口读发起编排器（window-read issue logic）。
- **删除原因**：主链路已由 `services/synapse/weights/WeightMemorySubsystem` 闭环承载窗口读编排；保留会造成重复实现与“可复活依赖”的风险。

### `StandardMemWeightReader.{h,cc}`（已删除）
- **定位**：历史的 StandardMem 权重读取 shim（实现 `IWeightReader`）。
- **删除原因**：主链路已由 `services/memory/StandardMemAccess`（纯内存） + `services/synapse/weights/WeightMemorySubsystem`（权重语义）闭环承载；禁止再走旧权重读路径。

### `memory/StandardMemBackend.{h,cc}`（已删除）
- **定位**：历史的 StandardMem pending 跟踪后端（`sendRead/sendWrite + popPending`）。
- **删除原因**：该实现携带 `MemRequestMeta`（含 BCSR/权重语义字段），与“Memory 绝对去语义化”边界冲突；主链路禁止依赖并已由 `services/memory/StandardMemAccess` 取代。

### `noc/SnnNetworkAdapter.{h,cc}` / `noc/SimpleNetworkWrapper.{h,cc}`
- **定位**：历史遗留的拓扑适配器/包装器（早期含 SST ELI 宏）。
- **现状**：已删除（2025-12-28），ELI 可加载对象的“权威位置”统一收敛在 `components/noc/`；避免 services/legacy 下继续保留“可加载”幻象与重复实现。
