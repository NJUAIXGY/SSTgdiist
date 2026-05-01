# components/gather/（GatherBufferIF 参数解析模块）

本目录用于承载 **GatherBufferIF 的构造期参数解析**，以降低 `components/GatherBufferIF.cc` 中 `params.find(...)` 的噪音。

## 设计原则

- **不新增运行期组件/装配点**：仅新增解析函数与配置结构体；SST ELI 注册对象仍只有 `GatherBufferIF` 本体。
- **不改变参数面**：所有参数名/默认值保持与 `GatherBufferIF` 现有实现一致（仅搬运解析位置）。

## 文件

- `GatherBufferIFConfig.{h,cc}`
  - `parseGatherBufferIFConfig(const SST::Params&) -> GatherBufferIFConfig`
  - 负责读取 `verbose/merge_policy/sram_bytes/window_auto/...` 等参数并返回结构化配置。

---

## 建模口径提示：merge_policy 会改变“读粒度语义”

`merge_policy/gap_merge/burst_bytes_max/k_adapt` 会影响 GatherBufferIF 最终向下游发起读请求的“合并粒度”，从而改变 memHierarchy 的 cacheline 事务量：

- **默认语义（通用 memHierarchy/DRAM）**：cacheline 粒度（例如 64B）。
- **row-streaming/DMA**：属于显式架构假设，必须单列结果，不与 cacheline 模式混算。

为避免 `local_run_config.json` 写 `auto` 但实际被装配层覆写导致误读，mesh 模板会把最终生效参数写入运行目录的 `effective_config.json`（并汇总到 `essential_summary_mesh.json` 的 `model.effective`）。

---

## Apply 发射策略（DRAM-aware，可选）

GatherBufferIF 在 Apply 阶段向下游发起 granule 读时，可通过 `apply_issue_policy` 选择发射顺序：

- `order`（默认）：按 granule 排序后的顺序依次发射（最稳健、可回归）。
- `bank_rr_row_sticky_age`：按 bank 轮转；同 bank 内优先发射同 row 的 granule；当等待时间超过 `apply_age_fair_ns` 时提升优先级以避免饥饿。
- `dram_aware_v1`：探索性策略（更激进的 DRAM cost/overfetch 约束）；仅建议用于 microbench/sweep。
- `cmd_aware_v1`：实验性命令感知策略（shadow command model）；按 bank busy + 预测 row-hit/row-miss 代价评分发射顺序。

建议配合：
- `sort_policy="bank_row"`：让排序键与 bank-aware 策略一致；
- `apply_bank_credit=0`：禁用 per-bank 并发额度限制，避免 bank_rr 被节流成近似串行。

> 注：这些策略属于 GAS 的“可选性能改进”，默认保持 `order`，避免改变历史实验口径。
>
> `cmd_aware_v1` 属于实验策略，必须与主线口径隔离：
> - 默认不开；
> - 仅在 `MESH_EXPERIMENTAL_ENABLE=1` 时允许脚本层覆盖；
> - 论文主结论需同时给出 `order`/`bank_rr_row_sticky_age` 基线与 `cmd_aware_v1` 消融。

### CMD-aware（实验）参数

- `apply_cmd_probe_depth`：每 bank 候选前探深度（默认 8）
- `apply_cmd_t_row_hit_ns`：预测 row-hit 服务时间（ns）
- `apply_cmd_t_row_miss_ns`：预测 row-miss 服务时间（ns）
- `apply_cmd_miss_penalty_ns`：额外 row-miss 惩罚（ns）
- `apply_cmd_enable_row_locality`：是否启用 row 命中偏好
- `apply_cmd_enable_bank_busy`：是否启用 bank 忙闲等待项

---

## Bank/Row 映射（bank_bits/bank_shift/row_bytes_guess）

这些参数只用于“分桶/排序/调度”与统计解释，不影响功能正确性，但会决定 DRAM-aware 策略是否真的在“真实 bank/row”上工作：

- `row_bytes_guess`：把线性地址空间切成固定大小的“row 区间”，`rowIndex=addr/row_bytes_guess`。
- `bank_bits`/`bank_shift`：从地址中抽取 bank 字段，`bankIndex=(addr>>bank_shift) & ((1<<bank_bits)-1)`。
- `bank_bits=0` 表示禁用 bank 维度（所有请求落在 bank 0），此时 `sort_policy=bank_row` 等价于 `row`，DRAM-aware 发射也会退化为近似 `order`。
- `bank_auto_enable=1` 会尝试基于访问模式做启发式猜测（便于快速跑通），但在 Ramulator2 场景建议显式固定参数以保证可复现（否则“伪 bank/伪 row”会让调度退化）。

### Ramulator2（ChRaBaRoCo）推荐值（与本仓库 configs 对齐）

当后端使用 Ramulator2 且 `AddrMapper=ChRaBaRoCo`（线性切 bit）时，建议显式固定：

- DDR5（`sst_dram_si/configs/ramulator2_ddr5.cfg`，`DDR5_8Gb_x8`）：
  - `row_bytes_guess = 4096`
  - `bank_bits = 4`（bg=3 + ba=1）
  - `bank_shift = 28`（= `log2(tx_bytes=64)` + `col_eff_bits(6)` + `row_bits(16)`）
- HBM2（`sst_dram_si/configs/ramulator2_hbm2.cfg`，`HBM2_4Gb`）：
  - `row_bytes_guess = 512`
  - `bank_bits = 5`（pseudoch=1 + bg=2 + ba=2）
  - `bank_shift = 23`（= `log2(tx_bytes=16)` + `col_eff_bits(5)` + `row_bits(14)`）

对应的 mesh_template 环境变量：
- `MESH_GAS_ROW_BYTES_GUESS`
- `MESH_GAS_BANK_BITS`
- `MESH_GAS_BANK_SHIFT`

快速校准/回归脚本（dense microbench）：
- `sst_dram_si/tools/run_dense_microbench_4x4_npc_sweep_apply_policy_matrix.sh`

验证要点（看趋势，不要求完全一致）：
- 校准后 `apply_issue_policy=bank_rr_row_sticky_age` 通常应不劣于 `order`；若出现明显退化，优先怀疑映射参数不匹配，或被 `apply_bank_credit` 节流。
- 需要解释 DRAM traffic 时，以 `memHierarchy MemController requests_received_*` 为主口径；用 `gas_unique_*` 解释 granule/overfetch 形态（见 `services/synapse/gas/README.md`）。
