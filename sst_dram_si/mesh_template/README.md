# mesh_template/（Mesh 模板实现：装配 + 统计 + 口径）

本目录存放 **4×4 mesh 模板的 Python 装配代码**（创建组件、连接 Link、下发参数、启用统计），并提供一组“论文级可复现”的运行脚本与口径产物（由 `sst_dram_si/tools/*` 生成）。

权威使用手册：
- `sst_dram_si/docs/mesh_template_guide_20251122-000250.md`

---

## 推荐运行方式（以 step-limited 为准）

统一入口：
- `cd "sst_dram_si" && ./tools/run_mesh_with_time.sh`

常用覆盖（示例）：
```bash
cd "sst_dram_si"
export MESH_MAX_STEPS="4"            # 跑 4 个 global step（论文/回归推荐 >0）
export MESH_VALIDATE_PROFILE="paper" # 论文级验收（默认）
./tools/run_mesh_with_time.sh
```

RAM2（仅在需要 RAMulator2 时使用）：
- `cd "sst_dram_si" && ./tools/run_mesh_with_time_ram2.sh`

说明：
- 当 `MESH_MAX_STEPS>0` 时，停止条件由 `GlobalGasStepController` 的 step-limited 控制，不依赖引擎级 `stop-at`。
- 当 `MESH_MAX_STEPS<=0` 时，才会回退到 `MESH_SIM_TIME` 驱动的 `stop-at`（不建议用于论文口径）。

---

## 核心建模原则：默认采用 cacheline 语义（通用 memHierarchy/DRAM）

在主流通用体系结构（cache/coherence + DRAM）建模中：

- 编程层的 4B load/store ≠ 内存系统对外搬运的最小单位；
- 系统层通常以 **cacheline/segment（例如 64B）** 作为事务与流量的基本单位；
- “row”更多是 DRAM 内部 row-buffer 概念，或显式 DMA/streaming 引擎的搬运单位。

因此，本项目的默认语义是：

- **dense 权重读默认按 cacheline 粒度建模**（避免 over-fetch 把 GAS 优势放大成“行 DMA 模式”的上限）。
- 结论口径优先使用 memHierarchy 的 **MemController 事务统计**（`requests_received_*`）作为 L2 traffic；
  `memory_bytes` 仅作为 L1 logical request 的解释辅助。
- 若需要做 row-streaming/DMA 假设的对照，必须显式开关并在输出中标注，且结果单列（不得与 cacheline 模式混算）。

---

## 实验性：段构建 DRAM 命令代价护栏（默认关闭）

在 GAS 段构建（`GatherBufferIF::buildGranulesWithGapMergeBuf_()`）阶段，可启用一个 deterministic 的“命令代价护栏”，用于抑制细/粗合并吸洞导致的病态 over-fetch（仍按 bank×row 分桶，不跨 row）。

仅当 `MESH_EXPERIMENTAL_ENABLE=1` 时允许覆盖：
- `MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE=1`
- `MESH_GAS_DRAM_CMD_T_ROW_HIT_NS`（默认 30）
- `MESH_GAS_DRAM_CMD_T_ROW_MISS_NS`（默认 120）

---

## 全局 step 同步（可选环境变量）

这些变量用于控制 `GlobalGasStepController` 的兼容/严格行为（运行期读取）：

- `MESH_GLOBAL_STEP_REQUIRE_ALL_READY`
  - `1`（默认）：要求所有 PE 都发送 `PE_READY` 后才开始广播 `START_STEP`
  - `0`：允许任意 PE_READY 触发开始（适合调试端口缺失/不完整拓扑）
- `MESH_GLOBAL_STEP_STRICT_SEQ_CHECK`
  - `0`（默认）：兼容优先；异常序号/缺口仅 `WARN` 并汇总
  - `1`：严格模式；异常直接 `fatal`（用于定位一致性问题）

注意：若同时设置 `MESH_MAX_STEPS>0` 与 `MESH_ALT_STOP=1`，模板会打印警告并忽略 `MESH_ALT_STOP`，避免双 stop 源造成口径不一致。

---

## 关键文件

- `sst_dram_si/mesh_template/build.py`
  - 主装配逻辑（MultiCorePE/SnnPESubComponent/GatherBufferIF/memHierarchy/NoC）
  - 启用统计项（含 `gas_unique_reads_total/gas_unique_bytes_total`）
  - dense 场景下强制 GatherBufferIF 的 strict cacheline 行为（防止回归到 row/granule 粒度）
  - 参数合并使用 `merge_params_checked`：对重复 key 打印 WARN，避免静默覆盖导致口径漂移
  - 运行目录落盘 `effective_config.json`（记录最终生效的参数，防止 `local_run_config.json` 误导）
- `sst_dram_si/mesh_template/paths.py`
  - 统一输出目录与 stats CSV 路径（`mesh_stats.csv` 等）
- `sst_dram_si/mesh_template/entry.py`
  - 传统 mesh 模板入口（4×4 dram mesh）

---

## 输出与口径

一次运行的核心产物通常包括：

- `mesh_stats.csv`：SST 统计 CSV（原始）
- `effective_config.json`：**最终生效的建模参数**（强烈建议阅读）
- `meta.json`：运行元数据（由 runner 写出）
- `essential_summary_mesh.json`：聚合摘要（由 `sst_dram_si/tools/compute_essential_summary_mesh.py` 生成）
- `validation.log`：验收输出（由 `sst_dram_si/tools/validate_essential_summary_mesh.py` 生成）

口径分层建议（论文/讨论默认）：

- L0 demand：`synapse_ops_step_total` / `spike_attempts_total`
- L1 logical request：`memory.memory_requests` / `memory.memory_bytes`
- L2 traffic（主口径）：`memhierarchy.memctrl.req_*` 与 `bytes_est_total`
- GAS granule（解释粒度/overfetch）：`gas.unique_reads_total / gas.unique_bytes_total / gas.avg_granule_bytes`
- init 分账：`memhierarchy.weight_loader.bytes_written_total`
