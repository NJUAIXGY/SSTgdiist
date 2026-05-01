# docs/（设计与重构文档）

本目录存放 **与 SnnDL 设计、重构、阶段性方案相关的文档**，用于记录关键决策、口径与后续演进路线。

## 默认内存语义（重要：cacheline）

SnnDL 的默认体系结构建模语义是：**cacheline 粒度**作为对外搬运单位，并与 `memHierarchy` 的 `GetS/GetX` 事务统计对齐。若某条路径显式采用
row-streaming/DMA 或更大 granule 读（例如 GAS 合并读导致 overfetch），必须：

- 在 run dir 中落盘 `effective_config.json`（记录 effective 的 granularity/merge_policy/line_size 等关键参数）；
- 同时解读 `gas_unique_bytes_total/gas_unique_reads_total`（或等价指标）与 `memctrl.bytes_est_total`，避免将逻辑请求字节数误当作 off-chip traffic。

## 当前内容

- `SNNDL_HIERARCHY_AND_WORKFLOW.md`
  - SnnDL 总览文档：目录层次（Hierarchy）、跨层接口、以及以 `sst_dram_si/test_mesh_4x4.py` 为例的端到端工作流与回归口径。
- `BCSR_WEIGHT_GENERATION_GUIDE.md`
  - BCSR 权重文件的二进制布局（rowptr/colidx/blockdata/blockids）、常用数据集（10k/100k）生成命令、meta/stride/对齐校验与在 mesh 模板中的加载方式。
- `plans/2026-01-03-universal-core-completion.md`
  - “通用计算核完成态”（packet-first + 可插拔 workload）推进计划与 DoD（最终验收口径的唯一真源）。
- `plans/2026-02-14-gas-ab-weights-phys-layout-v1.md`
  - GAS Apply 侧的可选发射策略（`apply_issue_policy`）与“bank/row 映射口径校准”、dense 权重物理布局（`phys_v1`）的实验记录与结论。
- `UNIVERSAL_CONTROL_CORE_DESIGN.md`
  - 通用控制子核（`control/SnnPESubComponent`）目标形态、分层与迁移路线（Phase A/B/C/D）。
- `SUBSYSTEM_MODULARIZATION_ROADMAP.md`
  - 子系统化终局路线图（Memory / Synapse+Route / Stimulus / NoC / NeuralCompute）与阶段性验收口径。

## 推荐阅读顺序（新人入口）

1. `../README.md`（快速构建/运行 + 目录边界总览）
2. `SNNDL_HIERARCHY_AND_WORKFLOW.md`（从“能跑起来”到“看懂数据流”）
3. 各子域 README：`../api/README.md`、`../components/README.md`、`../control/README.md`、`../compute/README.md`、`../services/README.md`
4. 完成态 DoD 与执行清单：`plans/2026-01-03-universal-core-completion.md`
5. 深入设计与路线图：`SUBSYSTEM_MODULARIZATION_ROADMAP.md` → `UNIVERSAL_CONTROL_CORE_DESIGN.md`

## 约束与建议

- 文档应描述“为什么/做什么/如何验证/风险与回退”，避免重复粘贴代码实现细节。
- 与可替换 compute core 相关的接口契约，优先维护在仓库根部的 `ISnnComputeCore_SPEC.md`，并在此目录做设计补充与案例记录。

## DRAM-aware Apply（可选优化）提示

`components/GatherBufferIF` 支持可选的 Apply 发射策略（`apply_issue_policy=bank_rr_row_sticky_age|dram_aware_v1|cmd_aware_v1`），用于研究 DRAM 行局部性/BLP 对 GAS Apply 阶段的影响。
`cmd_aware_v1` 为实验性策略，必须与主线口径隔离（默认关闭，脚本层需显式开启实验开关）。
这些策略依赖 `bank_bits/bank_shift/row_bytes_guess` 的 bank×row 映射口径；使用 Ramulator2 时建议显式校准并固定（避免“伪 bank/伪 row”导致退化）。

入口与说明：
- `../components/gather/README.md`（参数含义、Ramulator2 推荐值与复现脚本）
- `plans/2026-02-14-gas-ab-weights-phys-layout-v1.md`（实验记录与推导）
