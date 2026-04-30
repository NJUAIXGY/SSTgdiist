# `sst_dram_si/test_mesh_4x4.py` 重构计划（Phase-C）

目标：在**不改变行为/默认参数/输出口径**的前提下，让 4×4 mesh 模版脚本从“单文件 1600+ 行杂糅”收敛为“配置/权重/装配”三层结构，便于后续继续迭代 Step/GAS/BCSR 与通用核能力。

> 约束：该脚本是 SST 入口（`sst test_mesh_4x4.py`），因此重构必须保持：
> - 入口文件名不变（仍是 `test_mesh_4x4.py`）
> - `local_run_config.json` 与环境变量覆盖语义不变
> - 运行输出目录与统计字段口径不变（`mesh_stats.csv`/`essential_summary_mesh.json` 等）

---

## 0) 已完成（安全清理）

- 已对 `test_mesh_4x4.py` 做备份：`sst_dram_si/test_mesh_4x4.py.bak.20260108-152308`
- 去重：
  - 移除重复的 `_parse_time_to_ns()` 定义（保留前部版本）
  - 移除重复的 `MESH_WEIGHT_MODE` 禁用检查（保留前部 fail-fast）
- 不改变任何组件参数与连接拓扑，仅做“重复代码移除/语义保持”。
- 已开始模块化拆分（行为保持，100us 回归 OK）：
  - `sst_dram_si/mesh_template/utils.py`：`align_up/parse_time_to_ns`
  - `sst_dram_si/mesh_template/config.py`：`load_local_run_config` + `apply_local_run_config_overrides`（local_run_config.json 映射下沉）+ `apply_gas_env_overrides`（GAS env 解析下沉）
  - `sst_dram_si/mesh_template/bcsr.py`：BCSR 目录解析 + meta 扫描/stride/base 计算 + per-core meta 读取；新增 `resolve_global_bcsr_runtime`（BCSR runtime 组装）与 `apply_step_activation_bcsr_defaults_from_global_offsets`（Step 默认偏移回填）
  - `sst_dram_si/mesh_template/step.py`：Step/BCSR 辅助（template 解析、offsets 就绪判断、int_or_zero）；新增 `build_step_cfg`（Step cfg 拼装下沉）
  - `sst_dram_si/mesh_template/paths.py`：run_dir/输出文件命名规则（mesh_stats.csv 等）；新增 `prepare_run_output_and_stats`（run_dir + stats 输出初始化下沉）
  - `sst_dram_si/mesh_template/stats.py`：新增 `enable_default_statistics`（把 enableAllStatisticsFor* 的全局启用下沉）
  - `sst_dram_si/mesh_template/task_snn.py`：新增 SNN 分类任务“层次划分 + 默认 class freqs + layers_cfg 拼装”下沉（保持 legacy 4x4 固定分层口径）
  - `sst_dram_si/mesh_template/legacy_defaults.py`：新增 `make_default_state()`（默认值唯一来源）
  - `sst_dram_si/mesh_template/runtime.py`：新增 `resolve_runtime(...)`（统一 defaults→env→local→BCSR meta→派生→cfg 冻结；可选 `MESH_DUMP_CONFIG=1` dump/hash）
  - `sst_dram_si/mesh_template/entry.py`：新增 `run_mesh_4x4(...)`（SST 极薄入口：resolve_runtime + build_mesh_4x4 + program options）
  - `sst_dram_si/mesh_template/build.py`：装配层拆分推进（已迁移 per-PE 内存系统+WeightLoader / router mesh / GlobalGasStepController / PE 节点创建 / spike_data 扫描与 SpikeSource 创建 / NIC+router 链接 / 统计 enable）
    - 新增 `build_mesh_4x4(...)`：把“内存系统→路由器→PE/NIC→连接→统计”收敛为单一编排入口，`test_mesh_4x4.py` 进一步薄化。
  - `sst_dram_si/mesh_template/paths.py`：补齐 `spike_data` 目录与 complex 输入文件命名规则

- 追加的“薄入口”收敛点（行为保持）：
  - `test_mesh_4x4.py` 中的 BCSR 运行态组装（catalog/meta/offsets/stride/base）已下沉到 `mesh_template/bcsr.py`。
  - `test_mesh_4x4.py` 中的 GAS env 覆盖解析已下沉到 `mesh_template/config.py`。
  - `test_mesh_4x4.py` 中的 stats 输出初始化（run_dir + mesh_stats.csv）已下沉到 `mesh_template/paths.py`。
  - `test_mesh_4x4.py` 中的 enableAllStatisticsFor* 调用已下沉到 `mesh_template/stats.py`。
  - `test_mesh_4x4.py` 已收敛为极薄脚本：仅调用 `mesh_template.entry.run_mesh_4x4(sst, __file__)`。
  - 100us 对比基线 OK：`compare_essential_summary_mesh.py` 关键字段 Δ=0（含 `gas.*`、`memory.*`、`nic.*`）。

---

## 1) 现状痛点（为什么难维护）

1. **职责混杂**：配置解析 / BCSR meta 扫描 / stride 计算 / 组件装配 / 打印与调试门控交织在一起。
2. **重复逻辑**：时间解析、结束策略、若干 env/local 配置映射在多处出现，易漂移。
3. **隐含依赖多**：大量全局变量在中途被覆盖（如 BCSR meta 覆盖 `NEURONS_PER_CORE`），阅读成本高。
4. **不利于 A/B 实验**：权重目录/Step 路由/窗口参数等实验开关分散，难以保证“只改一处”。

---

## 2) 目标结构（最终形态）

建议新增包目录（Python）：

```
sst_dram_si/mesh_template/
  __init__.py
  legacy_defaults.py  # 唯一默认值来源（避免“默认散落导致搬家漂移”）
  runtime.py       # 统一 runtime 解析：defaults→env→local→BCSR meta→派生→cfg 冻结；可选 dump/hash 护栏
  entry.py         # SST 入口一键装配：resolve_runtime + build_mesh_4x4 + sst program options
  config.py        # 读取 local_run_config.json + env override（只做配置合并/校验）
  bcsr.py          # 权重目录解析、meta 扫描、stride/base 计算、per-core meta 读取
  build.py         # SST 组件装配：mem/bus/loader/router/nic/node/core 连接
  stats.py         # 全局统计启用封装
  task_snn.py      # SNN 分类任务（layers/freqs）封装
  step.py          # Step/BCSR 辅助 + Step cfg 拼装
  paths.py         # 运行目录、输入 spike 数据路径、输出 CSV 路径规则
  utils.py         # parse_time_to_ns / align_up 等纯函数
```

入口文件保持 `sst_dram_si/test_mesh_4x4.py`，但变为“薄入口”：

- 仅做：`from mesh_template.entry import run_mesh_4x4` + `run_mesh_4x4(sst, __file__)`

可选护栏（用于重构期防漂移）：
- `MESH_DUMP_CONFIG=1`：在 run_dir 写出 `runtime_config.json` + `runtime_config.sha256`（稳定序列化 + SHA256）

---

## 3) 推进步骤（每步 100us 回归）

### Step 1：抽取纯工具函数（零风险）
- 抽出到 `mesh_template/utils.py`：
  - `parse_time_to_ns()`
  - `align_up()`
  - 其它无 SST 依赖的 helper
- 验收：`MESH_SIM_TIME=10us/100us` 输出的 `essential_summary_mesh.json` 关键字段一致（允许轻微漂移，但禁止发放归 0/异常大幅偏离）。

### Step 2：抽取配置层（低风险）
- `mesh_template/config.py`：
  - 只负责：读取 `local_run_config.json`、应用 env override、做最基本的类型转换与边界检查
  - 输出：一个 dict 或 dataclass（建议 dict，避免引入过多依赖）
- 验收：同上。

（已落地）将 `local_run_config.json` 的字段映射与冲突检测下沉到 `mesh_template/config.py`，`test_mesh_4x4.py` 仅调用 `apply_local_run_config_overrides(...)`。

### Step 3：抽取权重/BCSR 层（中风险，但收益最大）
- `mesh_template/bcsr.py`：
  - `resolve_bcsr_dir()`（等价于当前 GLOBAL_BCSR_DIR 逻辑）
  - `scan_all_meta()`（等价于 `_scan_all_bcsr_meta_files`）
  - `compute_stride()`（等价于 `GLOBAL_BCSR_CORE_FILE_SIZE` → `PER_CORE_WEIGHT_STRIDE`）
  - `load_core_meta(pe, core)`（等价于 `_load_core_bcsr_meta`）
- 验收：同上，且确保 Step 激活 stats 不变（`mesh_stats.csv` 的 `step_activation_*` 汇总一致）。

### Step 4：抽取装配层（最高风险，拆分需最谨慎）
- `mesh_template/build.py`：
  - 把 “mem/bus/controller/loader” 与 “router mesh” 与 “node/core/nic” 三块各自封装为函数
  - `test_mesh_4x4.py` 仅保留打印与入口调度
- 验收：同上，且验证 `mesh_stats.csv`/`pe_stage_events_db.csv` 文件生成完整。

---

## 4) 回归口径（建议固定脚本）

- 10us：快速 sanity
  - `cd "sst_dram_si" && export MESH_SIM_TIME=10us && ./tools/run_mesh_with_time.sh`
- 100us：稳定性回归
  - `cd "sst_dram_si" && export MESH_SIM_TIME=100us && ./tools/run_mesh_with_time.sh`
- 对比工具：
  - `python3 "sst_dram_si/tools/compare_essential_summary_mesh.py" --a <runA> --b <runB>`

---

（完）
