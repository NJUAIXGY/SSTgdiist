# 100k 基线技术报告（Strict GAS + BCSR）

本报告用于复现与对比 100k 规模下的严格 GAS（Gather→Apply→Scatter）基线结果，并给出 BCSR 权重的生成/使用方法与随机脉冲（Random Activation）的开关说明。所有步骤在 32 线程环境下验证，确保严格 GAS 语义：真实“读→累加→统一发放”。

- 工程根目录：/home/xgy/remote
- 组件源码：sst_workspace/sst-elements/src/sst/elements/SnnDL
- 运行脚本：sst_dram_si/run_singlepe_with_time.sh
- 基线配置：sst_dram_si/local_run_config.json
- 输出目录：sst_dram_si/outputs_large/paper2/dram_N100k/<timestamp>/

---

## 1. 目标与范围
- 规模：100k 神经元（20 cores/PE × 5000 neurons/core），仿真 100us。
- 严格 GAS：事件权重不直接修改 v_mem；ΔV 仅来源于 Apply 阶段的真实权重读取与累加，在 Scatter 统一应用。
- 指标：窗口时序、内存读规模、发放数量级稳定，建立可复现的对比基线。

---

## 2. 构建与安装（必须）
任意 SnnDL 源码改动后，必须重新编译并安装。

```bash
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL
make clean && make -j32 && make install
```

- 安装产物：/home/xgy/remote/sst_install/lib/sst-elements-library/libSnnDL.so

---

## 3. 一条命令运行（32 线程 100k）
脚本封装了 `-n 32`、统计生成、latest 软链。

```bash
( cd /home/xgy/remote/sst_dram_si && ./run_singlepe_with_time.sh )
```

- 默认读取：sst_dram_si/local_run_config.json
- 产出：outputs_large/paper2/dram_N100k/<timestamp>/essential_summary.json

---

## 4. 基线配置要点（local_run_config.json）
与基线相关的关键项（仅摘录）：

```jsonc
{
  "sim_time": "100us",
  "num_cores_per_pe": 20,
  "neurons_per_core": 5000,

  // Strict GAS + 窗口化
  "gas_enable": 1,
  "apply_acc_enable": 1,
  "window_read_enable": 1,
  "gas_window_cycles_gather": 200,
  "gas_window_cycles_apply": 40,
  "gas_window_cycles_scatter": 40,
  "window_read_budget": 4194304,
  "max_outstanding_requests": 32768,
  "read_force_single": 1,
  "merge_read_cacheline": 1,

  // BCSR 权重配置（见 §5）
  "index_mode": "bcsr_post_row",
  "file_template": "weights/bcsr_from_spikes_N100k/core{core:02d}.bcsr.bin",
  "bcsr_block_rows": 16,
  "bcsr_block_cols": 16,
  "bcsr_val_bytes": 4,
  "bcsr_idx_bytes": 2,
  "bcsr_rowptr_offset": 0,
  "bcsr_colidx_offset": 1280,
  "bcsr_blockdata_offset": 76544,
  "bcsr_blockids_offset": 38585088,

  // 随机脉冲（基线关闭；详见 §6）
  "step_random_activation_enable": 0,

  // 诊断（性能测量时建议设 0）
  "window_read_debug": 1
}
```

---

## 5. BCSR 权重：生成与使用
本工程采用 BCSR（Block Compressed Sparse Row）权重；严格 GAS 下，Apply 阶段按上一窗触达边逐边读取权重并累加。

### 5.1 从脉冲对生成（from_spikes）
- 生成脚本：sst_dram_si/tools/spikes_to_bcsr.py
- 输入：`spikessrcdst*.txt`（每行 `src dst [timestamp]`，最少包含 `src dst`）
- 输出：每 core 一份 `.bcsr.bin` + 统一 `.meta.json`（记录 br/bc/offsets 等）

示例命令（100k，20 核 × 每核 5000 行，总列 100000）：
```bash
python3 sst_dram_si/tools/spikes_to_bcsr.py \
  --spike-file sst_dram_si/outputs_large/paper2/dram_N100k/spikessrcdstN100000.txt \
  --cores 20 --rows-per-core 5000 --cols-total 100000 \
  --br 16 --bc 16 --idx-bytes 2 --align 64 \
  --weight-scale 1.0 \
  --out-template sst_dram_si/weights/bcsr_from_spikes_N100k/core{core:02d}.bcsr.bin
```
产物说明：
- 每核文件：`coreXX.bcsr.bin`，包含 4 个段（按对齐写入）：`rowptr / colidx / blockdata / blockids`。
- 元信息：`core{core:02d}.bcsr.bin.meta.json`，关键字段：
  - `rows=5000, cols=100000, br=16, bc=16, idx_bytes=2, val_bytes=4`
  - `offsets.{rowptr_offset=0, colidx_offset=1280, blockdata_offset=76544, blockids_offset=38585088}`（统一模板偏移）
  - `files[i].{path, *_offset, nnz_blocks}`（逐核具体偏移）

建议：以 `meta.offsets.*` 作为配置中的偏移来源，确保 `local_run_config.json` 与实际文件一致；否则运行期会出现“无法解析块/索引”的读错误。

### 5.2 在仿真中使用 BCSR
- 关键项：
  - `index_mode: bcsr_post_row`（post 为行，pre 为列）
  - `file_template: weights/.../core{core:02d}.bcsr.bin`
  - `bcsr_block_rows/cols/val_bytes/idx_bytes/offsets` 与 `.meta.json` 保持一致
- 运行时（严格 GAS）：
  1) Gather：记录 (pre_global, post_local) 边；
  2) BeginApply：对“上一窗边集合”逐边读取权重（cache 命中则直用），读回调累加 ΔV；
  3) BeginScatter：统一按 ΔV 更新 v_mem，并进行阈值检查与发放。

---

## 6. 随机脉冲（Random Activation）开关与参数
严格 GAS 下，随机脉冲仅影响“触达边集合”的来源（不直接改 v_mem），用于压力与连通性测试。

- 开关：
  - 关闭（基线）：`"step_random_activation_enable": 0`
  - 开启：`"step_random_activation_enable": 1`
- 关键参数：
  - `step_activation_fraction`：每步注入的源神经元占比（建议从 `1e-5` 起逐步升）
  - `step_activation_fanout`：每个源随机选择的后续目标数量（如 128/256）
  - `step_activation_event_weight`：事件权重（严格 GAS 建议保持 `0.0`，避免事件直加 v_mem）
  - `step_activation_use_bcsr_routes`：1 表示基于 BCSR 可达边进行采样（更贴近真实连通关系）
  - `step_activation_bcsr_template` 与对应 `rows_per_core/br/bc/idx/val/offsets`：与权重 BCSR 保持一致

性能提示：较大的 fraction×fanout 会显著增加读取与累加压力，壁钟时间上升明显。建议从保守值起步，验证逻辑后再逐步拉升，同时可调大 `max_outstanding_requests/window_read_budget`，并适当延长 `gas_window_cycles_apply/scatter`。

---

## 7. 基线参考结果（关闭随机脉冲）
示例目录：sst_dram_si/outputs_large/paper2/dram_N100k/20251108-202130

- 内存：`memory_requests≈724,736`，`dram_bytes_read≈224.85 MiB`
- GAS 窗口：`windows≈358`，`gather/apply/scatter` 平均 ≈ `198/39/39 ns`，总 ≈ `278 ns`
- 脉冲活动：`total_neurons_fired≈916`，`unique≈458 (~0.46%)`

校验要点：
- CSV/日志顺序：BeginGather→BeginApply→BeginScatter→EndScatter 稳定；
- `sim_time_ns_observed≈100,000`；窗口总数≈`100us / 280ns`；
- `avg_req_bytes≈325B` 合理（单值读 + cacheline 合并的混合行为）。

---

## 8. 常见问题与排查
- 随机脉冲导致运行时间过长：
  - 降低 `step_activation_fraction` 或 `fanout`；
  - 增大 `max_outstanding_requests/window_read_budget`，并适度延长 `gas_window_cycles_apply/scatter`；
  - 关闭 `window_read_debug` 以减少日志开销。
- BCSR 偏移不匹配：
  - 对照 `.meta.json` 的 `offsets.*` 与配置保持一致；
  - 若日志出现“读取块/索引失败”，优先核对 `br/bc/idx/val/offsets` 与模板路径是否正确。
- 严格 GAS 核对：
  - 确认 Scatter 之前不会直接修改 v_mem；
  - `BeginApply` 后才能看到 ΔV 的应用（`[GAS][Delta]` 统计与 Scatter 发放数量对应）。

---

## 9. 快速命令小抄
- 重编译安装 + 基线运行（随机发放关闭）：
```bash
cd /home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j32 && make install && \
cd /home/xgy/remote/sst_dram_si && \
python3 - <<'PY'
import json
p='local_run_config.json'
cfg=json.load(open(p)); cfg['step_random_activation_enable']=0
open(p,'w').write(json.dumps(cfg,indent=2))
PY
./run_singlepe_with_time.sh
```
- 开启随机发放（谨慎：壁钟可能显著上升）：
```bash
cd /home/xgy/remote/sst_dram_si && \
python3 - <<'PY'
import json
p='local_run_config.json'
cfg=json.load(open(p)); cfg['step_random_activation_enable']=1
# 建议先用保守参数验证
cfg['step_activation_fraction']=1e-5
cfg['step_activation_fanout']=128
open(p,'w').write(json.dumps(cfg,indent=2))
PY
./run_singlepe_with_time.sh
```

---

如需扩展更大规模（如 N=1M）或切换不同 BCSR 模板，仅需替换 `file_template` 与相应 `bcsr_*` 参数为对应 `.meta.json` 值，并按上面步骤运行即可。
