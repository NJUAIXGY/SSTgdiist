# Retire Contract Task 0-3 执行文档

> 日期：2026-03-14  
> 状态：formal replay verified / Task 0-3 closed / Task 4 pending re-evaluation  
> 范围：只覆盖 `Task 0-3`，不包含正式主实验 rerun 与 Task 4+ 行为改动

---

## 0. 一句话结论

当前主线的正确推进方式不是直接改默认 retire 行为，而是先完成：

1. frozen baseline contract 固化；
2. `GCSS phase breakdown` 观测与验收闭环；
3. `shadow per-post retire` 只观测账本；
4. summary / validator / mesh config / PE 统计链路打通。

本轮已经把 Task 0-3 的代码、测试、编译、smoke 与正式 replay 链路全部跑通，并拿到了 `shadow=0/1` 的正式 mainexp 结果。

---

## 1. 为什么先做 Task 0-3

参考：

- `exp_opt/2026-03-06-system-mainline-dram-snn-gas-storm-gcss-glide.md`
- `exp_opt/2026-03-13-gas-retire-hol-system-treatment-design.md`

当前已经确认：

- 主线真实瓶颈是 `GCSS-GLIDE` 发射重排与 `global_inorder retire` 叠加后的 `retire HOL`；
- 当前问题不是 `bank credit`、不是 `downstream busy`、也不是 `step barrier` 主导；
- 直接把默认 retire 改成 `per_post`，会同时改动语义 contract、strict reproducibility 假设、以及 baseline 对照口径。

因此 Task 0-3 的目标是：

- 先冻结 contract；
- 再增强观测；
- 再提供 shadow attribution；
- 最后再决定是否进入真实行为改动。

---

## 2. Task 0-3 定义

### Task 0：冻结当前 baseline contract

目标：

- 把 `apply_issue_policy`、`experimental_retire_policy`、`experimental_gcss_phase_breakdown_enable`、`experimental_retire_shadow_per_post_enable` 明确写入 summary contract；
- 让后续任何实验都能区分：
  - `GAS semantic contract`
  - `strict reproducibility contract`
  - `current implementation contract`

本轮落地：

- `compute_essential_summary_mesh.py` 输出 `contracts.experimental_gcss_phase_breakdown_enable`
- `compute_essential_summary_mesh.py` 输出 `contracts.experimental_retire_shadow_per_post_enable`
- `validate_essential_summary_mesh.py` 校验 summary contract 与 `effective_config.json` 一致

### Task 1：冻结 RED/GREEN 验收入口

目标：

- 先用测试把预期行为固定住；
- 所有后续修改都围绕测试通过推进。

本轮新增/转绿测试：

- `sst_dram_si/tools/test_compute_essential_summary_mesh_p0_p1.py`
- `sst_dram_si/tools/test_validate_profile_paper.py`
- `sst_dram_si/tools/test_gbi_stepgate_progress_plumbing.py`
- `sst_dram_si/tools/test_run_mesh_with_time_requires_parallel.py`

### Task 2：GCSS phase breakdown + validator 收口

目标：

- 让 `retire_hol_attribution_core` 不只是给出 `head_source_mix`；
- 还要在 phase-breakdown 开启时强制给出：
  - `gcss_phase_mix`
  - `gcss_queued_reason_mix`
- 同时验证：
  - `queued_not_issued` phase 的 hol cycles 与 reason mix 求和一致
  - `queued_not_issued` phase 的 blocked edges 与 reason mix 求和一致

本轮落地：

- `compute_essential_summary_mesh.py` 已输出 `gcss_phase_mix` / `gcss_queued_reason_mix`
- `validate_essential_summary_mesh.py` 在 contract 开启时强制校验上述结构与守恒关系

### Task 3：shadow per-post retire（只观测，不改真实行为）

目标：

- 在 `global_inorder` 真正执行不变的前提下；
- 维护一个 shadow `per-post deterministic retire` 账本；
- 估计“理论上可恢复的 HOL”。

shadow 统计定义：

- `retire_shadow_per_post_recoverable_cycles_total`
- `retire_shadow_per_post_recoverable_edges_total`
- `retire_shadow_per_post_ready_posts_peak`
- `retire_shadow_per_post_committable_edges_peak`

语义：

- `recoverable_cycles_total`：global head 未 ready，但 shadow per-post 本 tick 存在可提交工作
- `recoverable_edges_total`：该 tick shadow 路径可提交的 edge 数
- `ready_posts_peak`：shadow ready-post 集合峰值
- `committable_edges_peak`：shadow 路径连续可 drain edge 峰值

注意：

- 不改真实 `global_inorder` retire；
- 只在 `experimental_retire_shadow_per_post_enable=1` 时启用；
- 真实 acc update / commit 路径仍然完全沿用原实现。

---

## 3. 本轮代码落地点

### Mesh config / runtime / build

- `sst_dram_si/mesh_template/config.py`
- `sst_dram_si/mesh_template/runtime.py`
- `sst_dram_si/mesh_template/spec.py`
- `sst_dram_si/mesh_template/build.py`

作用：

- 暴露 `experimental_retire_shadow_per_post_enable`
- 允许环境变量 `MESH_EXPERIMENTAL_RETIRE_SHADOW_PER_POST_ENABLE`
- 将该开关传入 core params / effective config

### Runtime / control / PE aggregation

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/IPeAggregation.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`

作用：

- `WeightMemorySubsystem` 增加 shadow per-post 账本与 4 个 observability counter
- `onClockTick()` 最终保持 observe-only 顺序：
  - `noteShadowRecoverableOnTick_()`
  - `drainShadowPerPostRetire_()`
  - `updateRetireHolStatsOnTick_()`
- `MultiCorePE` / `IPeAggregation` / `SnnPESubComponent` 打通统计、CSV、PE 级 SST stats

### Summary / validator

- `sst_dram_si/tools/compute_essential_summary_mesh.py`
- `sst_dram_si/tools/validate_essential_summary_mesh.py`

作用：

- gas 顶层汇总 shadow 字段
- `retire_hol_attribution_core.shadow_per_post` 输出 recoverable attribution
- validator 强制 phase-breakdown 的 `reason mix` 验收
- validator 在 shadow 开启时强制 `retire_hol_attribution_core.shadow_per_post` 存在

---

## 4. 验收分层

### L0：plumbing 存在性

要求：

- mesh config 能传开关
- WMS/MPE/PE-subcomponent 接口能看到字段
- PE CSV / SST stat 名称完整

命令：

```bash
cd "/home/xgy/remote"
python3 -m unittest sst_dram_si.tools.test_gbi_stepgate_progress_plumbing
```

### L1：summary 聚合正确

要求：

- `essential_summary_mesh.json` 顶层 gas 能输出 shadow 字段
- `retire_hol_attribution_core.shadow_per_post` 存在
- `top_core_windows_by_crosspost_blocked_edges` 包含 shadow 字段

命令：

```bash
cd "/home/xgy/remote"
python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_p0_p1
```

### L2：validator 契约生效

要求：

- `phase_breakdown_enable=1` 时必须要求：
  - `gcss_phase_mix`
  - `gcss_queued_reason_mix`
- 两者在 `queued_not_issued` 上满足守恒

命令：

```bash
cd "/home/xgy/remote"
python3 -m unittest sst_dram_si.tools.test_validate_profile_paper
```

### L3：编译链路通过

要求：

- SnnDL 编译通过
- 安装通过

命令：

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL"
make -j4 && make install
```

---

## 5. 当前验证结果

本轮已完成：

- `python3 -m unittest sst_dram_si.tools.test_gbi_stepgate_progress_plumbing`
- `python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_p0_p1`
- `python3 -m unittest sst_dram_si.tools.test_validate_profile_paper`
- `python3 -m unittest sst_dram_si.tools.test_run_mesh_with_time_requires_parallel`
- `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j4 && make install`
- `bash mainexp/experiments/2026-03-14_retire_contract_ab_v1/run_case.sh baseline_contract_smoke`
- `bash mainexp/experiments/2026-03-14_retire_contract_ab_v1/run_case.sh shadow_per_post_smoke`
- `env ... MESH_EXPERIMENTAL_RETIRE_SHADOW_PER_POST_ENABLE=0 ... sst_dram_si/tools/run_mesh_with_time.sh`
- `env ... MESH_EXPERIMENTAL_RETIRE_SHADOW_PER_POST_ENABLE=1 ... sst_dram_si/tools/run_mesh_with_time.sh`

当前状态：

- code path: 通过
- python tests: 通过
- C++ build/install: 通过
- smoke runner/artifacts: 通过
- formal mainexp rerun: 通过

---

## 6. 2026-03-14 晚间补记：formal baseline replay 卡死排障

### 6.1 现象

在完成 `P2` 第一批 front-end ordering observability 之后，重新执行：

```bash
env \
  MESH_EXPERIMENTAL_ENABLE=1 \
  MESH_VALIDATE_PROFILE=paper \
  MESH_EXEC_MODE=gas \
  MESH_MAX_STEPS=2 \
  MESH_STEP_ACTIVATION_FRACTION=0.03 \
  MESH_EXPERIMENTAL_GCSS_PHASE_BREAKDOWN_ENABLE=1 \
  MESH_EXPERIMENTAL_RETIRE_POLICY=global_inorder \
  MESH_EXPERIMENTAL_RETIRE_SHADOW_PER_POST_ENABLE=0 \
  MESH_RUN_ROOT="mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_baseline_replay" \
  MESH_VALIDATE_BASELINE_DIR="mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_baseline_replay/20260314-190546" \
  sst_dram_si/tools/run_mesh_with_time.sh
```

得到的新 run：

- `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_baseline_replay/20260314-225952`

长期停在：

- `seq=1`
- `stage=1`
- `ba=0 / bs=20 / es=0`
- 无 `START_STEP seq=2`

同时 `scatter-defer` 日志中出现异常大的：

- `pending_direct`
- `pending_colidx`

这说明问题不只是“跑得慢”，而是 scatter defer 判定链路读到了错误状态。

### 6.2 根因

根因不是本轮新增的 runtime 观测语义本身，而是：

1. `WeightMemorySubsystem.h` 新增字段后，类布局发生变化；
2. 依赖它的 `SnnWorkload.o` 没有被 `make -j4` 自动重编；
3. `WeightMemorySubsystem::hasDeferredWork()` / `deferredWorkBreakdown()` 是头文件内联函数；
4. 旧对象文件按过期布局读 `WeightMemorySubsystem`，把 scatter defer 状态读坏。

证据：

- `services/workload/snn/.deps/SnnWorkload.Plo` 内容只有 `# dummy`
- `SnnWorkload.o` 时间戳早于 `WeightMemorySubsystem.h`
- formal replay 卡死口径与 probe 重编后的行为完全相反

### 6.3 恢复方法

避免使用会触发顶层 autotools 并发重配的 `make -B -j4`，改用串行强制重编直接依赖：

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL"

touch \
  "control/SnnPEOrchestrators.cc" \
  "control/SnnPESubComponent_spike.cc" \
  "control/SnnPESubComponent_bcsr.cc" \
  "control/SnnPESubComponent.cc" \
  "services/synapse/stdmem/SnnPESubComponent_mem.cc" \
  "services/workload/snn/SnnWorkload.cc" \
  "services/synapse/weights/WeightMemorySubsystem.cc"

make -j1 libSnnDL.la
make -j1 install
```

### 6.4 验证闭环

先做 `1-step probe`：

- run dir:
  - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_baseline_replay_step1_probe/20260314-232804`

关键恢复信号：

- 先回到旧 baseline 一致的 `ba=20`
- 然后正常出现 `BeginScatter -> EndScatter`
- 最终进入 `all_es=1`

再重启正式 replay：

- run dir:
  - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_baseline_replay/20260314-233509`

截至本文补记时，已经确认：

- `seq=1` 恢复正常 `ba=20 -> es=20`
- 日志已出现 `START_STEP seq=2`

也就是说，formal baseline replay 已经从“step1 scatter defer 卡死”恢复为正常推进。

### 6.5 对主线的意义

这次问题说明：

- 当前主线调 `WeightMemorySubsystem.h` 这类带内联状态访问的头文件时；
- 不能默认相信一次普通 `make -j4` 就足够；
- 至少在这条工程链里，需要显式强制重编直接消费者，或做真正 clean rebuild。

这不是主线优化方向的变化，但它是后续推进 `P2/P3` 时必须记住的工程约束。

### 6.6 2026-03-15 补记：observe-only 语义回归修复

`stale object` 修好之后，`formal_baseline_replay/20260314-233509` 虽然已经能跑完，但很快暴露出第二层、也更关键的问题：

- 它已经不是 observe-only 口径；
- formal baseline 的主统计和旧 baseline `20260314-190546` 出现了大幅漂移。

最关键的漂移证据：

- `critical_path.stage`
  - old: `retire_closure`
  - bad replay (`20260314-233509`): `barrier_wait`
- `critical_path.evidence.memctrl_payload_utilization`
  - old: `0.2449300679494571`
  - bad replay: `0.7280051393059406`
- `critical_path.evidence.memctrl_traffic_amplification`
  - old: `4.082798034442862`
  - bad replay: `1.3736166765984257`
- `retire_hol_attribution_core.policy_loss_cycles_total`
  - old: `169483044.0`
  - bad replay: `79631641.0`
- `retire_hol_attribution_core.gcss_phase_mix.hol_cycles_by_phase.queued_not_issued`
  - old: `143221487`
  - bad replay: `0`
- `retire_hol_attribution_core.head_source_mix.dominant_src_by_hol_cycles`
  - old: `gcss`
  - bad replay: `bcsr`
- `spike_activity.total_spikes_processed`
  - old: `2459904.0`
  - bad replay: `10306297.0`
- `spike_activity.neurons_fired_total`
  - old: `317428.0`
  - bad replay: `160000.0`

根因最终缩到 `WeightMemorySubsystem::onClockTick()`：

- 当时的实现把 `tryRetireEdges_();` 放进了 tick 主循环；
- 这会主动推动真实 retire，而不是只做观测；
- 因而破坏了 Task 0-3 “shadow / phase breakdown 只能 observe-only、不能改变 formal baseline 行为”的约束。

为此补了一个 TDD 回归：

- 文件：
  - `sst_dram_si/tools/test_gbi_stepgate_progress_plumbing.py`
- 测试名：
  - `test_weight_memory_on_clock_tick_keeps_retire_path_observe_only`
- 约束：
  - 允许 `updateRetireHolStatsOnTick_();`
  - 禁止 `onClockTick()` 内出现 `tryRetireEdges_();`

修复动作很小，只做一刀：

- 文件：
  - `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/synapse/weights/WeightMemorySubsystem.cc`
- 修改：
  - 从 `onClockTick()` 中移除 `tryRetireEdges_();`

验证闭环：

1. 单测从 `RED` 变 `GREEN`
   - `python3 -m unittest sst_dram_si.tools.test_gbi_stepgate_progress_plumbing.GbiStepgateProgressPlumbingTest.test_weight_memory_on_clock_tick_keeps_retire_path_observe_only`
2. 相关 Python 测试通过
   - `python3 -m unittest sst_dram_si.tools.test_gbi_stepgate_progress_plumbing`
   - `python3 -m unittest sst_dram_si.tools.test_compute_essential_summary_mesh_p0_p1`
   - `python3 -m unittest sst_dram_si.tools.test_validate_profile_paper`
3. 串行重编 / 安装通过
   - `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j1 libSnnDL.la`
   - `cd sst_workspace/sst-elements/src/sst/elements/SnnDL && make -j1 install`
4. formal baseline replay 重新执行
   - run dir:
     - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_baseline_replay/20260315-142734`
   - 关键日志：
     - `START_STEP seq=2`（`mesh_run.log` 第 `333` 行）
     - `Simulation is complete, simulated time: 581.049 us`（第 `1420` 行）
   - 验收：
     - `validation.log`：`fail=0 warn=0 strict=0`
     - baseline diff 全部通过：
       - `spike_activity.neurons_fired_total: A=317428 B=317428 Δ=0`
       - `spike_activity.total_spikes_processed: A=2459904 B=2459904 Δ=0`
       - `memory.memory_requests: A=1556607 B=1556607 Δ=0`

修复后的关键字段已经完全回到旧 baseline：

- `critical_path.stage = retire_closure`
- `critical_path.evidence.memctrl_payload_utilization = 0.2449300679494571`
- `critical_path.evidence.memctrl_traffic_amplification = 4.082798034442862`
- `retire_hol_attribution_core.policy_loss_cycles_total = 169483044.0`
- `retire_hol_attribution_core.gcss_phase_mix.hol_cycles_by_phase.queued_not_issued = 143221487`
- `retire_hol_attribution_core.head_source_mix.dominant_src_by_hol_cycles = gcss`
- `spike_activity.total_spikes_processed = 2459904.0`
- `spike_activity.neurons_fired_total = 317428.0`

因此到这里可以明确分层结论：

- `20260314-225952` 的卡死问题，本质是 `stale object`；
- `20260314-233509` 的指标漂移问题，本质是 `onClockTick()` 主动 retire 破坏 observe-only；
- `20260315-142734` 才是“既能推进、又恢复 formal baseline 口径”的正确修复结果。

smoke 结果摘要：

- baseline run dir:
  - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/baseline_contract_smoke/20260314-185207`
- shadow run dir:
  - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/shadow_per_post_smoke/20260314-185207`
- 两个 case 共同成立：
  - `validation.log` 均为 `fail=0 warn=1 strict=0`
  - `Simulation is complete, simulated time: 177.047 us`
  - `global_steps_done=1`
  - `contracts.experimental_gcss_phase_breakdown_enable=true`
  - `retire_hol_attribution_core.gcss_phase_mix` / `gcss_queued_reason_mix` 均存在
- baseline case：
  - `contracts.experimental_retire_shadow_per_post_enable=false`
  - shadow 相关指标为 0
- shadow case：
  - `contracts.experimental_retire_shadow_per_post_enable=true`
  - `gas.retire_shadow_per_post_recoverable_cycles_total=18042`
  - `gas.retire_shadow_per_post_recoverable_edges_total=25758`
  - `gas.retire_shadow_per_post_ready_posts_peak_max=3`
  - `gas.retire_shadow_per_post_committable_edges_peak_max=4`
  - `retire_hol_attribution_core.shadow_per_post.recoverable_edges_share_of_policy_loss=0.0003531`
- wall clock：
  - baseline `4:29.35`
  - shadow `4:39.45`

formal replay 结果摘要：

- formal baseline run dir:
  - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_baseline_replay/20260314-190546`
- formal shadow run dir:
  - `mainexp/experiments/2026-03-14_retire_contract_ab_v1/runs/formal_shadow_replay/20260314-190546`
- 两个 case 共同成立：
  - `validation.log` 均为 `fail=0 warn=0 strict=0`
  - `Simulation is complete, simulated time: 581.049 us`
  - `global_steps_done=2`
  - `contracts.experimental_gcss_phase_breakdown_enable=true`
  - `retire_hol_attribution_core.gcss_phase_mix` / `gcss_queued_reason_mix` 均存在且 baseline/shadow 完全一致
  - `head_source_mix` 保持 `gcss` 独占主导
- formal baseline case：
  - `contracts.experimental_retire_shadow_per_post_enable=false`
  - 与 frozen baseline `20260313-164701` 主统计完全一致：
    - `memctrl.req_total=397207`
    - `memctrl.bytes_est_total=25421248`
    - `gas.memctrl_payload_utilization=0.2449300679494571`
    - `gas.payload_bytes_per_memctrl_req_avg=15.675524348765254`
    - `gas.memctrl_traffic_amplification=4.082798034442862`
    - `gas.retire_crosspost_blocked_edges_total=232715266461`
- formal shadow case：
  - `contracts.experimental_retire_shadow_per_post_enable=true`
  - 主统计与 formal baseline 完全一致；
  - 新增 observe-only shadow attribution：
    - `gas.retire_shadow_per_post_recoverable_cycles_total=324108`
    - `gas.retire_shadow_per_post_recoverable_edges_total=1554837`
    - `gas.retire_shadow_per_post_ready_posts_peak_max=16`
    - `gas.retire_shadow_per_post_committable_edges_peak_max=57`
    - `retire_hol_attribution_core.shadow_per_post.recoverable_edges_per_cycle_avg=4.79728053611759`
    - `retire_hol_attribution_core.shadow_per_post.recoverable_edges_share_of_policy_loss=6.681284918024792e-06`
- formal replay 的 queued-not-issued reason mix：
  - `dominant_reason_by_hol_cycles = vlf_younger_ahead`
  - `dominant_reason_by_blocked_edges = vlf_younger_ahead`
- wall clock：
  - formal baseline `10:57.87`
  - formal shadow `11:03.59`

---

## 6. Smoke / 正式 Replay 与当前结论

对应实验目录：

- `mainexp/experiments/2026-03-14_retire_contract_ab_v1`

配套脚本：

- `mainexp/experiments/2026-03-14_retire_contract_ab_v1/run_case.sh`

本轮已执行 smoke case：

1. `baseline_contract_smoke`
   - `experimental_retire_policy=global_inorder`
   - `experimental_gcss_phase_breakdown_enable=1`
   - `experimental_retire_shadow_per_post_enable=0`

2. `shadow_per_post_smoke`
   - `experimental_retire_policy=global_inorder`
   - `experimental_gcss_phase_breakdown_enable=1`
   - `experimental_retire_shadow_per_post_enable=1`

目的：

- baseline case 用来冻结 contract
- shadow case 用来确认观测字段存在且不改变 runtime 主行为

当前可以确认：

- `run_case.sh` 能稳定落出 `meta.json`、`effective_config.json`、`essential_summary_mesh.json`、`validation.log`
- baseline 与 shadow 在 runtime 主行为上保持同一步数完成口径：
  - `gas.global_steps_done=1`
  - `paper.step_limited.steps_completed=1`
- baseline 不启用 shadow contract，但 summary 里会保留零值 shadow attribution 占位块；
- shadow case 会把非零 recoverable attribution 打到 `gas.*` 与 `retire_hol_attribution_core.shadow_per_post`
- 这组 smoke 仍然只是 observability/contract 验证，不构成正式主实验性能结论

正式 replay 进一步确认：

- formal baseline replay 没有污染 frozen baseline：
  - 与 `2026-03-13` 的正式 baseline 参考 run 主统计逐项一致
- formal shadow replay 也没有改动 runtime 主行为：
  - memctrl、payload utilization、traffic amplification、crosspost blocked edges 与 baseline 全部一致
  - phase mix / reason mix / head source mix 也保持一致
- shadow per-post 在这条正式 step2 主线 case 上确实能给出非零 recoverable attribution；
- 但 `recoverable_edges_share_of_policy_loss=6.68e-06` 非常小，说明在当前定义下，单纯依赖这个 shadow `per-post retire` 候选并没有显出足够大的可恢复空间

---

## 7. 非目标

本轮明确不做：

- 不把默认 retire policy 从 `global_inorder` 改成 `per_post`
- 不修改 scatter / barrier 语义
- 不改变 strict reproducibility 默认口径
- 不在本轮给出“shadow 可恢复量 = 可安全合入 per-post retire”的结论
- 不把当前 formal replay 的 shadow attribution 直接等价为“已经证明 Task 4 值得进入”

---

## 8. 下一阶段建议

当前 formal replay 完成后，下一步建议顺序：

1. 先把 formal baseline/shadow 的对照结论整理成固定表格，纳入后续 candidate 审核基线
2. 重点复核为什么 `recoverable_edges_share_of_policy_loss` 只有 `6.68e-06`：
   - 这是否准确反映“retire policy 可恢复空间很小”
   - 还是当前 shadow 账本对可恢复机会仍偏保守
3. 把分析重点继续放在 `queued_not_issued -> vlf_younger_ahead` 这条 front-end / queue ordering 证据链
4. 在没有新的机制证据前，不建议直接进入 Task 4 的真实 `per_post retire` 候选实现

---

## 9. 执行备注

配套的 `P0/P1` 正式分析文档：

- `exp_opt/2026-03-14-retire-p0-p1-formal-compare-qni-analysis.md`

如果后续要把这套观测正式变成论文主线数据，必须补两件事：

1. 正式 mainexp 结果目录与 `essential_summary_mesh.json` 引用
2. `TECH_PROGRESS.md` 与 `exp_opt` 中的 run-id / command / interpretation 同步

当前文档现在可以视为：

- Task 0-3 的工程落地与正式验收文档；
- 但仍不是“默认 retire policy 应该切换”的结论文档。
