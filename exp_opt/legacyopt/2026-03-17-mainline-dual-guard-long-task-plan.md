# Mainline Dual-Guard Offline Scorer Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不修改 runtime 主契约、不回到 online reorder 的前提下，把 `P3-C1` 基线推进到可验证的 `hol_profile_dual_guard_v3` 候选，并完成从 shadow key、静态 gate、最小 runtime gate 到 formal 决策的整条链路。

**Architecture:** 本计划完全围绕 `snndl` 的 offline layout generator 展开。先在 generator 内完成 dual-guard 的 shadow 统计与 shadow key，再在受控新 mode 下启用实际 selector，随后通过静态 diff 工具和最小 runtime gate 逐层筛选，只有所有短门槛都通过后才进入 formal A/B。

**Tech Stack:** Python 3、`unittest`、`py_compile`、`sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`、`mainexp/experiments/2026-03-17_p3c1_p3c2a_static_diff_v1/analyze_static_diff.py`、`sst_dram_si/tools/run_mesh_with_time.sh`

---

## 0. 当前状态与本次长任务终点

### 0.1 当前已完成

- 设计文档已存在：
  - `exp_opt/2026-03-17-mainline-offline-dual-guard-scorer-design.md`
- `Task 0` 已完成：
  - generator 已能输出 `high_risk_target_set / weak_neighborhood_map` 的 shadow 统计
  - 但还没有接入 `hol_profile_dual_guard_v3` 的 shadow key
  - 更没有改变任何 `physical_pre_order`
- Stage A 静态工具已存在：
  - `mainexp/experiments/2026-03-17_p3c1_p3c2a_static_diff_v1/analyze_static_diff.py`
  - 当前只默认比较 `P3-C1` vs `P3-C2a`

### 0.2 本次长任务的终点

本次长任务完成的定义不是“写完一个新 mode”，而是必须同时满足：

1. generator 中存在可测试的 `hol_profile_dual_guard_v3_shadow`
2. generator 中存在可测试的 `hol_profile_dual_guard_v3`
3. 已生成完整 candidate artifact
4. 已通过静态 Stage A gate
5. 已通过最小 runtime gate
6. 若 runtime gate 通过，则完成 formal A/B
7. 最终形成明确结论：
   - candidate 前进
   - 或 candidate 止损

只有上述闭环完成，才算这次长任务真正结束。

---

## 1. 硬边界

以下边界在整个长任务期间都不允许被打破：

1. 只关注 `snndl`
2. 不改 runtime 主逻辑
3. 不改 `prepareGcssVlfIssueQueue_()`、`popNextGcssVlfIssueEntry_()`、`tryRetireEdges_()`
4. 不改 `base + pre_rank` contract
5. 不做 line-chunk / split-pre / online reorder
6. 不动 `bcsr_gas` 相关路径
7. 不允许再次把主线带回 `step1` 卡住而没有 observe 证据的试错状态

本次长任务唯一允许的行为改动范围是：

- `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`
- `sst_dram_si/tools/gcss/test_gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`
- `mainexp/experiments/2026-03-17_p3c1_p3c2a_static_diff_v1/analyze_static_diff.py`
- `mainexp/experiments/2026-03-17_p3c1_p3c2a_static_diff_v1/test_analyze_static_diff.py`
- 新建 dual-guard 对应 experiment/snapshot 输出目录

---

## 2. 一次性执行的总路线

### Batch A：Shadow Key 完整化

目标：

- 接入 `hol_profile_dual_guard_v3_shadow`
- 计算 dual-guard 的 candidate key
- 但严格保持最终 order 与 `hol_profile_constrained_v2_1` 一致

### Batch B：静态分析工具泛化

目标：

- 把当前 Stage A 工具从 `P3-C1 vs P3-C2a` 扩成 `baseline_dir vs candidate_dir`
- 能直接拿来比较 `P3-C1 vs dual_guard_v3`

### Batch C：实际 Selector 启用

目标：

- 在单独新 mode 下启用 dual-guard selector
- 旧 mode 行为完全不变

### Batch D：完整 Artifact 与静态 Gate

目标：

- 生成完整 candidate artifact
- 用泛化后的 Stage A 工具做静态 gate
- 只要静态 gate 不通过，就到此止损

### Batch E：最小 Runtime Gate

目标：

- 在可信短口径下，仅验证：
  - closure 是否稳定
  - `seq1` 头部是否改善或至少不恶化

### Batch F：Formal A/B 与最终决策

目标：

- 只有在前面全部通过后才进入 formal
- 最后形成明确 go/no-go 结论

---

## 3. Batch A：Shadow Key 完整化

### Task A1：新增 shadow order mode 常量与测试

**Files:**
- Modify: `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`
- Modify: `sst_dram_si/tools/gcss/test_gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`

**Step 1: Write the failing test**

新增两个最小测试：

1. `hol_profile_dual_guard_v3_shadow` 返回的 `physical_pre_order` 必须与 `hol_profile_constrained_v2_1` 完全一致
2. `order_stats` 中必须包含 shadow key 相关字段，例如：
   - `hol_dual_guard_shadow_enabled`
   - `hol_dual_guard_shadow_candidate_count`
   - `hol_dual_guard_shadow_best_target_preview`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m unittest sst_dram_si.tools.gcss.test_gen_gcss_valueonly_dstcore_vlf_premphf_plp
```

Expected:

- 新测试失败
- 旧测试仍然不应因为环境问题失败

**Step 3: Write minimal implementation**

最小实现要求：

1. 新增 mode：
   - `ORDER_HOL_DUAL_GUARD_V3_SHADOW = "hol_profile_dual_guard_v3_shadow"`
2. 在 `_choose_physical_order()` 中接入 shadow mode
3. shadow mode 内部：
   - 复用 `hol_profile_constrained_v2_1` 的实际排序
   - 只额外计算 dual-guard key / preview
4. 不允许 shadow mode 改变最终 order

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m unittest sst_dram_si.tools.gcss.test_gen_gcss_valueonly_dstcore_vlf_premphf_plp
python3 -m py_compile /home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py /home/xgy/remote/sst_dram_si/tools/gcss/test_gen_gcss_valueonly_dstcore_vlf_premphf_plp.py
```

Expected:

- 全部通过

### Task A2：把 shadow key 写入 meta / summary

**Files:**
- Modify: `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`
- Modify: `sst_dram_si/tools/gcss/test_gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`

**Step 1: Write the failing test**

补 meta/summary 测试，要求以下字段可见：

- `hol_dual_guard_shadow_enabled`
- `hol_dual_guard_shadow_candidate_count`
- `hol_dual_guard_shadow_best_target_preview`
- `hol_dual_guard_shadow_best_neighbor_preview`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m unittest sst_dram_si.tools.gcss.test_gen_gcss_valueonly_dstcore_vlf_premphf_plp
```

**Step 3: Write minimal implementation**

要求：

- `_write_meta_json()` 写入 shadow key 字段
- per-core summary 返回值也带上同样字段
- 旧字段完全不变

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m unittest sst_dram_si.tools.gcss.test_gen_gcss_valueonly_dstcore_vlf_premphf_plp
python3 -m py_compile /home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py
```

**Batch A exit gate**

必须满足：

1. `dual_guard_v3_shadow` order 与 `v2_1` 完全一致
2. shadow key 字段可写入 meta
3. 所有旧测试不回归

---

## 4. Batch B：静态分析工具泛化

### Task B1：将 `analyze_static_diff.py` 泛化为 baseline/candidate 可配置

**Files:**
- Modify: `mainexp/experiments/2026-03-17_p3c1_p3c2a_static_diff_v1/analyze_static_diff.py`
- Modify: `mainexp/experiments/2026-03-17_p3c1_p3c2a_static_diff_v1/test_analyze_static_diff.py`

**Step 1: Write the failing test**

新增测试，要求：

1. 工具可接收 `--baseline-dir` / `--candidate-dir`
2. 输出文件名不再写死 `p3c1/p3c2a`
3. 可读取新 meta 字段：
   - `hol_high_risk_target_preview`
   - `hol_weak_neighborhood_preview`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m unittest /home/xgy/remote/mainexp/experiments/2026-03-17_p3c1_p3c2a_static_diff_v1/test_analyze_static_diff.py
```

**Step 3: Write minimal implementation**

要求：

1. 脚本参数支持任意 baseline/candidate 目录
2. 输出 summary 中增加：
   - `candidate_target_preview_overlap`
   - `candidate_neighbor_preview_overlap`
3. 保持当前 `P3-C1 vs P3-C2a` 默认路径兼容

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m unittest /home/xgy/remote/mainexp/experiments/2026-03-17_p3c1_p3c2a_static_diff_v1/test_analyze_static_diff.py
python3 /home/xgy/remote/mainexp/experiments/2026-03-17_p3c1_p3c2a_static_diff_v1/analyze_static_diff.py
```

**Batch B exit gate**

必须满足：

1. 工具能直接比较 `P3-C1 vs dual_guard_v3`
2. 当前默认 `P3-C1 vs P3-C2a` 不被破坏

---

## 5. Batch C：实际 Selector 启用

### Task C1：新增真实 mode `hol_profile_dual_guard_v3`

**Files:**
- Modify: `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`
- Modify: `sst_dram_si/tools/gcss/test_gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`

**Step 1: Write the failing test**

增加 3 组最小 toy tests：

1. 当 `target_penalty` 明显更高时，selector 应避免继续把高风险 target 往坏方向推
2. 当 `neighbor_drift_penalty` 明显更高时，selector 应保留 closure-friendly 邻域
3. 当 dual-guard 信号相同或为空时，新 mode 应退化到接近 `v2_1` 的行为

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m unittest sst_dram_si.tools.gcss.test_gen_gcss_valueonly_dstcore_vlf_premphf_plp
```

**Step 3: Write minimal implementation**

实现要求：

1. 新增：
   - `ORDER_HOL_DUAL_GUARD_V3 = "hol_profile_dual_guard_v3"`
2. 新增 selector，例如：
   - `_order_by_profile_dual_guard_greedy(...)`
3. 只在新 mode 下生效
4. 旧 mode 完全不改
5. 采用严格字典序：
   - `broad_reshape_guard`
   - `target_displacement_penalty`
   - `neighborhood_drift_penalty`
   - `shared_line_head_risk`
   - `cand_risk`
   - locality rank

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m unittest sst_dram_si.tools.gcss.test_gen_gcss_valueonly_dstcore_vlf_premphf_plp
python3 -m py_compile /home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py
```

### Task C2：新增 mode 的 CLI / meta / manifest 路径

**Files:**
- Modify: `sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`
- Modify: `sst_dram_si/tools/gcss/test_gen_gcss_valueonly_dstcore_vlf_premphf_plp.py`

**Step 1: Write the failing test**

要求：

1. CLI `--order-mode hol_profile_dual_guard_v3` 合法
2. meta 中能写出：
   - `hol_objective_version = dual_guard_v3`
   - `hol_dual_guard_enabled = 1`

**Step 2: Run test to verify it fails**

Run:
```bash
python3 -m unittest sst_dram_si.tools.gcss.test_gen_gcss_valueonly_dstcore_vlf_premphf_plp
```

**Step 3: Write minimal implementation**

要求：

- 只新增新 mode 的元数据
- 不改变旧 mode 的输出语义

**Step 4: Run test to verify it passes**

Run:
```bash
python3 -m unittest sst_dram_si.tools.gcss.test_gen_gcss_valueonly_dstcore_vlf_premphf_plp
python3 -m py_compile /home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py
```

**Batch C exit gate**

必须满足：

1. 新 mode 可独立启用
2. 旧 mode 测试全绿
3. dual-guard 行为只在新 mode 下发生

---

## 6. Batch D：完整 Artifact 与静态 Gate

### Task D1：生成 shadow artifact

**Files:**
- No code changes
- Output dir:
  - `/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_hol_dual_guard_v3_shadow_j4`

**Step 1: Run generation**

Run:
```bash
python3 /home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py \
  --bcsr-dir /home/xgy/remote/sst_dram_si/weights/bcsr_global_16pe_fanout256_10k \
  --out-dir /home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_hol_dual_guard_v3_shadow_j4 \
  --bucket-target 3 \
  --max-seed-tries 128 \
  --jobs 4 \
  --self-check \
  --order-mode hol_profile_dual_guard_v3_shadow \
  --profile-dir /home/xgy/remote/mainexp/experiments/2026-03-16_closure_fixed_baseline_observe/runs/baseline_formalenv_drain200_profile/20260316-164913/gcssplp_profiles \
  --index-version 7
```

**Step 2: Verify**

检查：

1. self-check 成功
2. shadow mode order 与 `P3-C1` 不应出现大规模差异
3. meta 中 shadow 字段齐全

### Task D2：生成 actual candidate artifact

**Files:**
- No code changes
- Output dir:
  - `/home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_hol_dual_guard_v3_j4`

**Step 1: Run generation**

Run:
```bash
python3 /home/xgy/remote/sst_dram_si/tools/gcss/gen_gcss_valueonly_dstcore_vlf_premphf_plp.py \
  --bcsr-dir /home/xgy/remote/sst_dram_si/weights/bcsr_global_16pe_fanout256_10k \
  --out-dir /home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_hol_dual_guard_v3_j4 \
  --bucket-target 3 \
  --max-seed-tries 128 \
  --jobs 4 \
  --self-check \
  --order-mode hol_profile_dual_guard_v3 \
  --profile-dir /home/xgy/remote/mainexp/experiments/2026-03-16_closure_fixed_baseline_observe/runs/baseline_formalenv_drain200_profile/20260316-164913/gcssplp_profiles \
  --index-version 7
```

### Task D3：运行静态 Stage A gate

**Files:**
- Output dir:
  - `/home/xgy/remote/mainexp/experiments/2026-03-17_dual_guard_v3_static_gate_v1`

**Step 1: Run static diff**

Run:
```bash
python3 /home/xgy/remote/mainexp/experiments/2026-03-17_p3c1_p3c2a_static_diff_v1/analyze_static_diff.py \
  --baseline-dir /home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_hol_constrained_v2_1_p3c1_formal_j4 \
  --candidate-dir /home/xgy/remote/sst_dram_si/weights/gcss_valueonly_dstcore_vlf_premphf_plp_fanout256_10k_hol_dual_guard_v3_j4 \
  --output-dir /home/xgy/remote/mainexp/experiments/2026-03-17_dual_guard_v3_static_gate_v1/snapshot
```

**Step 2: Evaluate static gate**

必须明确回答：

1. `target rank` 是否改善或至少不恶化
2. `±256 rank` neighborhood 的 moved-pres 是否受控
3. `|rank_delta| >= 128` 是否受控
4. top abnormal cores 中是否再次出现 `P3-C2a` 式 broad drift

**Batch D exit gate**

仅当以下全部成立时才允许进入 Batch E：

1. self-check 成功
2. candidate 没有出现无法解释的大面积 rank reshuffle
3. static diff 明确优于或不差于 `P3-C1`

只要其中任一项失败，立即止损，本次长任务直接进入“no-go 总结”。

---

## 7. Batch E：最小 Runtime Gate

### Task E1：可信短口径 rerun

**Files:**
- No runtime code changes
- 只复用现有可信入口：
  - `sst_dram_si/test_mesh_4x4.py`
  - `sst_dram_si/tools/run_mesh_with_time.sh`

**Step 1: Prepare candidate config**

要求：

- 仅替换 weight artifact 路径为 `hol_dual_guard_v3_j4`
- 保持其余可信 MPI32 口径与 `P3-C1` baseline 一致

**Step 2: Run short gate**

必须收集：

- `diag-gcss-vlf`
- `diag-gcss-vlf-head`
- `sentinel-step-drain`

**Step 3: Evaluate**

必须明确回答：

1. `step1` 是否稳定结束
2. `send PE_DONE(drain)` 是否出现
3. 是否能进入 `START_STEP seq=2`
4. `head_queue_depth` 是否改善或至少不恶化
5. `next_retire` 是否更快推进

**Batch E exit gate**

只要出现以下任一项，立即止损，不进入 formal：

1. `step1` 卡住
2. closure fail
3. `head_queue_depth` 明显更差
4. `next_retire` 推进更慢

---

## 8. Batch F：Formal A/B 与最终结论

### Task F1：运行 formal A/B

前提：

- Batch D 和 Batch E 全部通过

对照对象：

1. baseline:
   - `P3-C1`
2. candidate:
   - `hol_dual_guard_v3`

必须比较：

1. closure 完整性
2. `seq1` head 行为
3. `queued_not_issued hol_cycles`
4. `vlf_younger_ahead hol_cycles`
5. memory 指标是否明显回归

### Task F2：给出最终 go/no-go

必须只允许三种结论：

1. `GO`
   - candidate 同时通过 closure、head gate、memory gate
2. `NO-GO`
   - 任一 gate 未过
3. `HOLD`
   - 只有在证据不完整且不是候选本身失败时才允许

本次主线默认优先 `GO / NO-GO`，尽量避免无结论拖延。

---

## 9. 执行过程中的强制止损点

以下任何一条命中时，必须停止继续向后批次推进：

1. shadow mode 改变了 `physical_pre_order`
2. 旧 generator 测试回归
3. 新 selector 影响到旧 mode
4. self-check 失败
5. static gate 出现 `P3-C2a` 式 broad drift
6. runtime gate 出现 `step1` 卡住或 closure fail

---

## 10. 任务结束时必须产出的内容

### 10.1 代码与产物

必须存在：

1. `hol_profile_dual_guard_v3_shadow`
2. `hol_profile_dual_guard_v3`
3. candidate artifact
4. static gate snapshot
5. runtime gate run dir
6. formal A/B run dir 或明确 no-go 证据

### 10.2 文档与日志

必须 append 到：

- `TECH_PROGRESS.md`

至少记录：

1. 每一批的变更点
2. 每一批的验证命令
3. 每一批的关键结果
4. 最终结论与下一步建议

---

## 11. 推荐执行顺序总结

真正的一次性推进顺序应严格是：

1. `Task A1`
2. `Task A2`
3. `Task B1`
4. `Task C1`
5. `Task C2`
6. `Task D1`
7. `Task D2`
8. `Task D3`
9. 若静态 gate 通过，再做 `Task E1`
10. 若 runtime gate 通过，再做 `Task F1`
11. 最后做 `Task F2`

这条路径的核心原则是：

- 先证据
- 再行为
- 先静态
- 再 runtime
- 先短 gate
- 再 formal

只要严格沿这条路径推进，就能把这次 dual-guard 主线一次性走到明确结论，而不会再次偏航到错误方向。
