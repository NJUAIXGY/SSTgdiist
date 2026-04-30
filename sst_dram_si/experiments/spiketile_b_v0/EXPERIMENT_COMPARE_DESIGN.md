# SpikeTile-B 对比实验深度设计（NoC multicast × GAS）

## 0. 设计对象与验证问题

本设计用于验证以下改动是否“真实生效”且“具备体系结构价值”：
- 新包语义：`SpikeTileKey(B)`，即 `block_col + pre_mask`；
- 发送侧批量聚合：按 `(block_id, ingress_node, block_col)` 聚合发包；
- 接收侧展开：按 `pre_mask` 解包后复用本地 route cache；
- 保持主线兼容：默认开关关闭，不影响原路径。

核心验证问题：
1. `SpikeTileKey` 是否真的进入运行路径（不是“开关开了但没走到”）？
2. 在相同负载下，是否降低 NoC/内存开销并缩短总仿真时间？
3. 收益是否稳定（重复实验不抖），并可解释到“通信→内存→整体”的因果链？

---

## 1. 假设（Hypotheses）

### H1（功能假设）
开启 `MESH_EXPERIMENTAL_SPIKETILE_ENABLE=1` 后，运行路径会从 `SpikeKey` 切到 `SpikeTileKey`，且不破坏基本正确性（route miss、local drop 仍在阈值内）。

### H2（通信假设）
与 `SpikeKey` 相比，`SpikeTileKey` 会减少等效发包频率或包头重复开销，从而缓解 NoC 注入压力。

### H3（内存假设）
由于输入 spike 组织更块化，Apply 侧访问模式更规整，`memory_bytes` 与 `memctrl.bytes_est_total` 下降。

### H4（性能假设）
在中高 fanout / 中低稀疏场景，`sim_time_actual_ns` 相比 `SpikeKey` 显著下降。

### H5（边界假设）
在超低活动率下，`SpikeTileKey` 可能收益有限甚至接近平齐（聚合管理成本抵消收益）。

---

## 2. 对比变体与基线

## 2.1 主对比组（V0 可直接运行）
- `A_spike_unicast`：`multicast=0`，逐 spike unicast。
- `B_spikekey_multicast`：`multicast=1`，现有 `SpikeKey` 路径。
- `C_spiketilekey_multicast`：`multicast=1 + experimental_spiketile=1`，新 `SpikeTileKey(B)` 路径。

## 2.2 预留组（V1/V2）
- `D_spiketilekey_tile_apply`：`C` + 接收端 tile-apply（尚未实现，不纳入当前统计显著性判定）。

---

## 3. 公平性约束（必须固定）

- **数据集固定**：同一 BCSR 数据目录（默认 `weights/bcsr_global_16pe_fanout256_10k_rowpack_v1`）。
- **激活源固定**：`MESH_STEP_ACTIVATION_FRACTION`、`MESH_STEP_ACTIVATION_SEED`、`MESH_MAX_STEPS`。
- **GAS 相关固定**：`MESH_EXEC_MODE=gas`、`MESH_BCSR_BLOCK_FETCH_MODE=row_cacheline`。
- **平台固定**：`MESH_SST_NPROC`、NoC 拓扑、验证 profile、内存后端保持一致。
- **仅变更目标开关**：A/B/C 之间只允许改 `multicast_enable` 与 `experimental_spiketile_enable`（及其必要参数）。

---

## 4. 分层实验计划

## 4.1 Phase-0：路径激活与冒烟（必做）
目标：确认“确实走了新路径”。

检查项：
1. `effective_config.json` 中 `multicast_enable/experimental_spiketile_enable` 与预期一致；
2. `validation.log` 无硬失败；
3. `essential_summary_mesh.json` 存在且字段完整。

建议命令：
```bash
cd "sst_dram_si/experiments/spiketile_b_v0"
./run_spiketile_with_time.sh
```

## 4.2 Phase-1：主矩阵 A/B/C（核心结论）
目标：验证“改动生效 + 有收益”。

使用脚本：
```bash
cd "sst_dram_si/experiments/spiketile_b_v0"
./run_spiketile_compare_matrix.sh
```

输出路径：
- `outputs/compare_matrix/A_spike_unicast/*`
- `outputs/compare_matrix/B_spikekey_multicast/*`
- `outputs/compare_matrix/C_spiketilekey_multicast/*`

## 4.3 Phase-2：敏感性扫描（解释收益边界）
目标：构建论文级“何时收益最大/最小”的曲线。

建议扫描维度：
- 活动率：`MESH_STEP_ACTIVATION_FRACTION ∈ {0.0025, 0.005, 0.01, 0.02, 0.05}`
- block 尺寸：`MESH_MULTICAST_BLOCK_W/H ∈ {(2,2), (4,2), (4,4)}`
- tile 宽度：`MESH_EXPERIMENTAL_SPIKETILE_BLOCK_COLS ∈ {8,16,32,64}`

建议先做分层扫描，避免全因子爆炸：
1. 固定 block=2x2、tile=16，扫活动率；
2. 在最有代表性的活动率点扫 block；
3. 固定最优 block 后扫 tile 宽度。

---

## 5. 指标体系与口径

## 5.1 一级指标（Primary）
- `sim_time_actual_ns`（越小越好）
- `memory_bytes`（越小越好）
- `memctrl.bytes_est_total`（越小越好，主内存流量口径）

## 5.2 二级指标（Correctness / Guardrail）
- `total_spikes_processed`（规模一致性检查）
- `validation.log` 约束（route miss / local drop）
- `effective_config.json`（配置生效检查）

## 5.3 三级指标（建议补充，面向论文）
- NoC 分项：不同 packet kind 的数量与延迟（需要额外统计口）
- GAS 分项：Gather/Apply/Scatter 时间占比
- DRAM 分项：row-hit/miss（若后端可导出）

---

## 6. 统计方法（可发表口径）

## 6.1 重复次数
- 默认每个点 `N=5`；
- 若排序不稳定或波动大，升到 `N=10`。

## 6.2 报告统计量
- 主报告：`median`；
- 稳定性：`p95`、`min/max`；
- 相对收益：以 `B_spikekey_multicast` 为基准，计算 `C vs B` 百分比。

## 6.3 显著性建议
- 使用 bootstrap 95% CI（或 Mann-Whitney U）评估 `C-B` 差异；
- CI 不跨 0 且幅度超过工程阈值时，判定“显著”。

---

## 7. 生效判定门禁（Pass/Fail）

## 7.1 正确性硬门禁（必须满足）
- `validation.log` 不报 fatal；
- `max_route_miss_abs == 0`；
- `max_local_drop_abs <= 1`；
- `total_spikes_processed` 在 A/B/C 间偏差 <= 0.1%（建议阈值）。

## 7.2 性能门禁（V0）
- 在主工作点（默认活动率 0.01）下，`C vs B`：
  - `sim_time_actual_ns` 下降 >= 5%，且
  - `memctrl.bytes_est_total` 下降 >= 3%。
- 若达不到，判定“改动生效但收益不足”，进入参数扫描或机制复盘。

---

## 8. 执行协议（推荐）

## 8.1 编译与脚本校验
```bash
cd "sst_workspace/sst-elements/src/sst/elements/SnnDL"
make -j4
make test-compile

cd "/home/xgy/remote"
bash -n "sst_dram_si/experiments/spiketile_b_v0/run_spiketile_with_time.sh"
bash -n "sst_dram_si/experiments/spiketile_b_v0/run_spiketile_compare_matrix.sh"
python3 -m py_compile \
  "sst_dram_si/experiments/spiketile_b_v0/test_mesh_4x4_spiketile.py" \
  "sst_dram_si/experiments/spiketile_b_v0/runtime.py" \
  "sst_dram_si/experiments/spiketile_b_v0/build.py"
```

## 8.2 主矩阵执行
```bash
cd "sst_dram_si/experiments/spiketile_b_v0"
MESH_MAX_STEPS=2 \
MESH_STEP_ACTIVATION_FRACTION=0.01 \
MESH_STEP_ACTIVATION_SEED=314159 \
./run_spiketile_compare_matrix.sh
```

## 8.3 重复实验（示例）
```bash
cd "sst_dram_si/experiments/spiketile_b_v0"
for i in 1 2 3 4 5; do
  MESH_STEP_ACTIVATION_SEED=$((314159 + i)) ./run_spiketile_compare_matrix.sh
done
```

---

## 9. 数据整理模板

建议统一导出 `results.csv` 字段：
- `phase`
- `variant`（A/B/C）
- `fraction`
- `block_w`
- `block_h`
- `tile_block_cols`
- `seed`
- `run_dir`
- `sim_time_actual_ns`
- `memory_bytes`
- `memctrl.bytes_est_total`
- `total_spikes_processed`
- `validation_pass`

并额外输出：
- `normalized_to_B.csv`（按工作点归一化）
- `significance_report.md`（CI / p-value）

---

## 10. 主要风险与缓解

## 10.1 V0 范围风险
- 当前实验链路在 `mesh_template` 下未显式接入“专用 MulticastRouter 组件链”做完整块内复制语义复现；
- 因此 V0 更适合回答“载体+聚合机制是否有工程收益趋势”，不直接宣称完整 NoC 树优化上限。

## 10.2 缓解策略
- 结论严格标注为 `V0 trend evidence`；
- V1 补 router 链路后复跑同矩阵，做一一对照确认结论可迁移；
- V2 再加入 `tile-apply` 完成端到端联合优化闭环。

---

## 11. 面向 ISCA 叙事的最小证据包

最小建议图表：
1. 图A：`A/B/C` 在主工作点的归一化柱状图（time + memctrl bytes）；
2. 图B：活动率扫描下 `C vs B` 收益曲线；
3. 图C：tile 宽度扫描下收益-开销权衡曲线；
4. 表A：正确性门禁与稳定性统计。

论文措辞边界：
- V0：证明 `SpikeTileKey(B)` 的“可行性 + 趋势收益 + 可解释性”；
- V1/V2：在补齐 router 与 tile-apply 后，再上升到“体系结构级联合优化收益”主结论。
