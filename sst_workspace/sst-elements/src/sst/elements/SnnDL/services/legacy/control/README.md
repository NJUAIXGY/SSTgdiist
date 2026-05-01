# services/legacy/control/（历史控制面参考实现）

本目录存放 **控制面（control plane）相关的历史参考实现**，默认不参与主链路构建，仅用于：

- 对照历史行为/统计口径；
- 帮助重构时定位“口径是否漂移”；
- 临时回溯某段已被主链路吸收的实现。

> 原则：新功能禁止依赖 legacy；若确需启用，必须先做 10us→100us 回归验证，并明确回退策略。

## 默认内存语义（cacheline）

本目录属于历史参考实现，部分旧控制面逻辑可能隐含了更强的访存粒度假设（例如按行/大 granule 搬运）。当前主链路默认以 **cacheline 粒度**作为对外搬运与
`memHierarchy` 统计对齐的语义；任何非 cacheline 的假设应显式标注为“实验/历史假设”，避免与默认结果混算。

---

## 主要内容

### `StageEventHub.{h,cc}`
- **定位**：历史的 GAS 阶段事件调度/汇报助手（BeginGather/BeginApply/BeginScatter/EndScatter）。
- **现状**：主链路已将对应能力吸收进 `control/SnnPESubComponent_impl.h` 的 `Impl`；该文件仅保留用于对照参考。
