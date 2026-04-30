# BCSR Rowpack A/B/AB（br=2）+ Paper-Grade Gate Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 A/B/AB（A=row_cacheline，B=rowpack_v1）对比实验在 `br=2` 数据集上做成“语义不漂移 + 自动 gate + 可复现”的 paper‑grade 基建：任何性能对比都必须先过 correctness gate，否则标记 `INCONCLUSIVE` 并给出原因。

**Architecture:** 维持仿真行为不变，仅在 `sst_dram_si/tools/` 增强“对比矩阵 gate”与“离线 byte‑exact 等价校验”两条链路；通过 step_activation/route 统计把 gate 从“动力学结果（fired）”下沉到“结构性指标（inj/proc/route_hits/misses）”，减少噪声；并在 `br=2` 数据集上复跑 A/B/AB 矩阵闭环确认。

**Tech Stack:** Bash runner（`run_mesh_with_time.sh`）+ Python gate/validator（`compute_essential_summary_mesh.py`/`validate_essential_summary_mesh.py`）+ 现有 rowpack‑aware C++ loader（已落地）。

---

### Task 1: 把 A/B/AB matrix gate 抽成可测试的 Python 工具

**Files:**
- Create: `sst_dram_si/tools/gate_ab_isolation_matrix.py`
- Modify: `sst_dram_si/tools/run_mesh_bcsr_ab_isolation_matrix.sh`
- Test: `sst_dram_si/tools/test_gate_ab_isolation_matrix.py`

**Step 1: 写一个会失败的 gate 单测（先定义契约）**

目标：构造一个最小 fake run 目录树，让 gate 能：
- 读取每个 variant 的 “latest run”；
- 在 `spikes_injected_total` 不等时，把该 variant 的 `essential_summary_mesh.json` 写入：
  - `experiment.profile="universal_core_eval"`
  - `experiment.verdict="INCONCLUSIVE"`
  - `experiment.reasons` 追加 `matrix_mismatch:spikes_injected_total:...`

在 `sst_dram_si/tools/test_gate_ab_isolation_matrix.py` 用 `tempfile.TemporaryDirectory()` 创建：
- `baseline/20260101-000000/essential_summary_mesh.json`
- `A/20260101-000000/essential_summary_mesh.json`
- `B/20260101-000000/essential_summary_mesh.json`
- `AB/20260101-000000/essential_summary_mesh.json`

示例（伪代码，不要求覆盖全部字段，仅覆盖 gate 会读取的 key）：

```python
baseline = {
  "model": {"max_steps": 1},
  "step": {"global_steps_done": 1},
  "step_activation": {
    "spikes_injected_total": 100,
    "pre_selected_total": 10,
    "spike_attempts_total": 40,
    "route_hits_total": 39,
    "route_misses_total": 1,
    "local_drops_total": 0
  },
  "spike_activity": {"total_spikes_processed": 1000, "neurons_fired_total": 777},
  "experiment": {"profile": "universal_core_eval"}
}
variant_bad_inj = deep_copy(baseline); variant_bad_inj["step_activation"]["spikes_injected_total"] = 101
```

**Step 2: 运行单测确认它 FAIL（因为工具还没实现）**

Run: `python3 -m unittest -v "sst_dram_si/tools/test_gate_ab_isolation_matrix.py"`

Expected: FAIL（ImportError 或断言失败均可）。

**Step 3: 实现 gate 工具 `gate_ab_isolation_matrix.py`（KISS，先满足单测）**

建议 CLI 形态（便于被 bash 调用、也便于单测）：

```bash
python3 "sst_dram_si/tools/gate_ab_isolation_matrix.py" \
  --baseline-root "…/dram_mesh_4x4_ab_isolation_baseline" \
  --a-root        "…/dram_mesh_4x4_ab_isolation_A_row_cacheline" \
  --b-root        "…/dram_mesh_4x4_ab_isolation_B_rowpack_v2" \
  --ab-root       "…/dram_mesh_4x4_ab_isolation_AB_rowpack_rowcacheline" \
  --fired-rel-tol 0.001
```

核心行为：
- `latest_run(root)`：选择 root 下“字典序最大”的子目录，且必须存在 `essential_summary_mesh.json`。
- `extract_metrics(summary)`：读取：
  - 语义 gate（严格相等）：
    - `step_activation.spikes_injected_total`
    - `spike_activity.total_spikes_processed`
    - `step_activation.pre_selected_total`
    - `step_activation.spike_attempts_total`
    - `step_activation.route_hits_total`
    - `step_activation.route_misses_total`
    - `step_activation.local_drops_total`
    - `step.global_steps_done`（或 `step.steps_done_min`，两者择一；建议优先 `global_steps_done`）
  - 噪声 gate（容忍漂移）：
    - `spike_activity.neurons_fired_total`：允许 `abs_diff <= max(1, ref*fired_rel_tol)`
- 任何 strict mismatch：写回 variant 的 `essential_summary_mesh.json`，标记 `INCONCLUSIVE`，并 append 原因（与现有 matrix 脚本理由前缀保持一致：`matrix_mismatch:*`）。
- 打印一个 TSV 摘要表（variant/run_id/bcsr_dir/fetch/memory_bytes/memctrl_bytes/sim_time + gate counters）。

**Step 4: 重新运行单测，确认 PASS**

Run: `python3 -m unittest -v "sst_dram_si/tools/test_gate_ab_isolation_matrix.py"`

Expected: PASS（并能验证 `experiment.reasons` 被写入）。

**Step 5: 修改 `run_mesh_bcsr_ab_isolation_matrix.sh`，用新 gate 工具替换 inline python**

要求：
- 保留现有输出表结构（必要时只做追加列，不删列）。
- 透传 `MESH_AB_GATE_FIRED_REL_TOL` 到 `--fired-rel-tol`。
- 行为保持向后兼容：若找不到某个 variant 的 run，输出 WARN 但不中断整个脚本（仍标注该 cell 为 INCONCLUSIVE/NA）。

**Step 6: 复跑 gate 单测 + 脚本 dry sanity**

Run:
- `python3 -m unittest -v "sst_dram_si/tools/test_gate_ab_isolation_matrix.py"`
- `bash -n "sst_dram_si/tools/run_mesh_bcsr_ab_isolation_matrix.sh"`

Expected:
- 单测 PASS
- bash 语法检查无错误（exit 0）

---

### Task 2: 在 `br=2` 数据集上做 rowpack 等价与 A/B/AB 矩阵闭环

**Files:**
- Use: `sst_dram_si/tools/verify_bcsr_rowpack_equivalence.py`
- Use: `sst_dram_si/tools/run_mesh_bcsr_ab_isolation_matrix.sh`

**Step 1: 确认 `br=2` 数据集存在（避免隐式落到默认 br=1）**

Run:
- `test -d "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2"`
- `test -d "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2_rowpack_v1"`

Expected: 两条命令都 exit 0。

**Step 2: 对 `br=2` 做离线 byte‑exact 等价抽样（至少 4 个 (pe,core)）**

Run（示例）：
- `python3 "sst_dram_si/tools/verify_bcsr_rowpack_equivalence.py" --flat "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2" --rowpack "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2_rowpack_v1" --pe 0 --core 0`
- `python3 "sst_dram_si/tools/verify_bcsr_rowpack_equivalence.py" --flat "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2" --rowpack "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2_rowpack_v1" --pe 0 --core 1`
- `python3 "sst_dram_si/tools/verify_bcsr_rowpack_equivalence.py" --flat "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2" --rowpack "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2_rowpack_v1" --pe 7 --core 2`
- `python3 "sst_dram_si/tools/verify_bcsr_rowpack_equivalence.py" --flat "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2" --rowpack "sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2_rowpack_v1" --pe 15 --core 3`

Expected: 每条输出 `PASS`。

**Step 3: 跑 `br=2` 的 A/B/AB matrix（step=1, l1=0，先做 correctness）**

Run:

```bash
cd "sst_dram_si"
MESH_BCSR_DIR_FLAT="sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2" \
MESH_BCSR_DIR_ROWPACK="sst_dram_si/weights/bcsr_global_16pe_fanout256_10k_br2_rowpack_v1" \
MESH_SWEEP_REPEATS=1 \
MESH_MAX_STEPS=1 \
MESH_STEP_ACTIVATION_FRACTION=0.01 \
MESH_STEP_ACTIVATION_SEED=314159 \
MESH_L1_ENABLE=0 \
MESH_SST_NPROC=32 \
./tools/run_mesh_bcsr_ab_isolation_matrix.sh
```

Expected:
- 输出末尾 `matrix_gate: PASS`（或明确列出哪些 cell INCONCLUSIVE 以及原因）。
- 四个 variant 的 `spikes_injected_total/total_spikes_processed/route_hits_total/route_misses_total/global_steps_done` 与 baseline 严格一致。
- `neurons_fired_total` 在容忍内（默认 0.1%）。

**Step 4: 若 PASS，再把 `MESH_MAX_STEPS` 提升到 4 做一次稳健性复验**

Run: 同上，但 `MESH_MAX_STEPS=4`

Expected: gate 仍 PASS（允许 fired 轻微漂移但不允许 inj/proc/route 指标漂移）。

---

### Task 3: 文档化“对比口径/DoD”（让后来者不会再做错对比）

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/docs/BCSR_WEIGHT_GENERATION_GUIDE.md`
- Modify: `TECH_PROGRESS.md`

**Step 1: 更新 BCSR 指南，写清 rowpack_v1 契约与验证方法**

要求补充（要点即可）：
- `layout_mode=rowpack_v1`：`colidx/blockdata` 逐 block_row stride 存储（含 padding），`blockids` 仍保持 flat（generator contract）。
- 离线等价校验命令（引用 `verify_bcsr_rowpack_equivalence.py`）。
- paper‑grade A/B/AB gate 的指标清单（strict vs tolerant）。

**Step 2: 在 `TECH_PROGRESS.md` 追加当日进展**

最少包含：
- What changed：抽出 gate 工具 + br=2 复跑结论
- How to run：关键命令（离线等价 + matrix）
- Results：给出 run_dir（至少 baseline/A/B/AB 各一个）
- Next TODO：进入更大规模 sweep 或引入 ramulator2 后端（如需要）

---

## Definition of Done（DoD）

1. `br=2` 的离线等价抽样全部 `PASS`。
2. `br=2` 的 A/B/AB matrix 在 `step=1` 与 `step=4` 都能 `matrix_gate: PASS`（strict counters 完全对齐，fired 在容忍内）。
3. `run_mesh_bcsr_ab_isolation_matrix.sh` 不再包含 inline python gate（改由独立工具实现），且 gate 工具有单测覆盖。
4. 文档更新到位：BCSR 指南 + `TECH_PROGRESS.md`。

