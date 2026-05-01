# docs/plans/（阶段计划与设计草案集合）

本目录存放 **SnnDL 模块化/通用核演进**过程中产生的阶段性 plan 文档（按日期或 Phase 编排）。

## 默认内存语义（cacheline）

所有计划文档在讨论“memory_bytes/traffic/带宽/访存优化”时，默认以 **cacheline 粒度**作为体系结构语义（与 `memHierarchy` 的 `GetS/GetX` 事务统计对齐）。若某计划
讨论 row-streaming/DMA 或更大 granule 读，应显式标注该假设，并要求在输出中通过 `effective_config.json` 与 granule 统计闭环验证。

## 约定

- 这些文档用于记录“为什么这么设计/下一步做什么/验收口径是什么”，便于回溯与协作推进。
- 若文档内容与实现发生漂移，应优先更新文档或在文档顶部标注“已过期/需要同步”的说明，避免误导。

## 推荐阅读顺序（新成员）

1) 先读 `sst_workspace/sst-elements/src/sst/elements/SnnDL/docs/README.md`
2) 再按时间从旧到新阅读本目录下的计划文档
