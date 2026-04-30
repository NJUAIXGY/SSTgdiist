# Phase C Runtime Equivalence

> Current note (2026-04-09):
> 这份长文档保留了 `Phase C` 运行时等价性的演进轨迹，适合追根溯源，但不适合作为当前主线现状总览。
>
> 当前 authoritative 文档请优先看：
> 1. `/home/xgy/remote/riscv_snn_isa_lab/README.md`
> 2. `/home/xgy/remote/docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
> 3. `/home/xgy/remote/riscv_snn_isa_lab/references/current-mainline-status.md`
> 4. `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
>
> 这份文档里较新的 Phase C 语义仍有参考价值，但下面这些当前已经有更新的正式命令面与稳定面，请以新文档为准：
> 1. `observer-history-refresh`
> 2. `observer-fail-recovery`
> 3. `stable-surface-audit`
> 4. supplementary `compare` 的 attach / history / audit 契约

## 范围

这份记录固定 `Phase C` 的最小 compare surface：

1. `snn` baseline：
   - `riscv_snn_isa_lab/specs/external_dyn_desc_ref_snn_baseline.json`
2. `riscv_snn(runtime_bridge)`：
   - `riscv_snn_isa_lab/specs/external_dyn_desc_ref_runtime_bridge.json`

## 当前比较面

`equiv --family external_dyn_desc_ref` 当前比较：

1. strict：
   - `schema_version`
   - `model.exec_mode`
   - `model.mesh_size`
   - `contracts.gas_semantic_ready_before_commit`
   - `contracts.gas_semantic_drain_before_scatter`
2. trend：
   - `memory.memory_requests`
   - `memory.memory_bytes`
   - `gas.windows`
   - `gas.windows_done`
   - `step.global_steps_done`
   - `snn_tx.spike_packets_total`
   - `snn_rx.spike_packets_total`
   - 每条 row 还会附带：
     - `classification`
     - `gate_level`
     - `delta_ratio`
     - `policy`
     - `note`
   - 同时会额外汇总成 `compare.trend_overview`
3. runtime-bridge only：
   - `riscv_snn_backend_runtime_bridge_provider_bound`
   - `riscv_snn_fused_step_completion_count`
   - `riscv_snn_completion_visible_count`
   - `riscv_snn_completion_consumed_count`
   - `riscv_snn_fault_count`
   - `riscv_snn_last_completion_status`
   - `riscv_snn_last_fault_csr`
   - 并额外收敛成 `runtime_bridge.runtime_gate`
     - `summary`
     - `hard_failures`
     - `warnings`
     - `checks`

## PASS / WARN / FAIL

1. `PASS`
   - baseline 与 runtime_bridge 的 strict 字段全部匹配
   - baseline / runtime_bridge 的 `equiv_validation.ok` 都为真
   - `runtime_bridge.runtime_gate.summary = passed`
   - 对 fault-oriented family，如果 family policy 允许 `accepted-fault completion progress`、`visibility-only progress` 或 queue-overflow completion 例外，则这些 progress 也可以合法满足 completion / consume 相关 gate
2. `WARN`
   - strict 与 validation 仍然成立
   - 但 `runtime_bridge.runtime_gate.summary = passed_with_warning`
     或 `compare.trend_overview.status = passed_with_warning`
   - 当前会把下面这些情况提升成 `WARN`：
     - `riscv_snn_fused_step_completion_count <= 0`
     - `riscv_snn_completion_visible_count <= 0`
     - `completion_consumed_count < completion_visible_count`，且当前 family policy **不**允许 accepted-fault / barrier-visible / queue-overflow 提前退休
     - `last_completion_status != 0`，且当前 family 不是 fault-oriented completion contract
     - `fault_count == 0` 但 `last_fault_csr != 0`
     - `snn_tx / snn_rx` 出现 `visibility_gap`，且该 field 的 compare policy 是 `warn_on_visibility_gap`
3. `FAIL`
   - strict 字段不一致
   - 或任一侧 `equiv_validation.ok = false`
   - 或 smoke 失败
   - 或 `runtime_bridge.runtime_gate.summary = failed`
   - 当前会把下面这些情况提升成 `FAIL`：
     - `riscv_snn_backend_runtime_bridge_provider_bound <= 0`
     - `fault_count > 0` 但 `last_fault_csr <= 0`

## 约束

1. compare harness 只消费已有 spec / run / summary 资产，不引入第二份 metadata authority。
2. `RX debug` 不是当前 PASS 的一部分，只作为后续 `Phase D` 的扩展项。
3. 当前趋势字段是 research-level compare，不要求 bit-identical。

## 2026-03-30 当前 stable 状态（最新）

下面这部分覆盖当前最新状态；后面的 dated 段落保留为时间线记录。

### 当前 stable closure

1. stable top-level gate：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
   - `gate_ok = true`
   - `with_equivalence = true`
   - `with_full_equivalence = true`
2. stable observer surface：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-observer-summary.json`
   - `optional_surfaces.full_equivalence.entry_count = 2`
   - `first_fail_date = 2026-03-30`
   - `latest_recovered_date = 2026-03-30`
3. stable research / validator：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/riscv-snn-research-report.json`
     - `observer_adequacy.status = ready_with_fail_recovery_sample`
   - `/home/xgy/remote/riscv_snn_isa_lab/references/observer-adequacy-validation.json`
     - `status = pass`
     - `mismatch_count = 0`

### 当前真实 observer 样本链

1. 真实 fail sample：
   - `/home/xgy/remote/.observer_fail_lab/references/2026-03-30-equiv-matrix.json`
   - `all_ok = false`
2. 真实 recovery sample：
   - `/home/xgy/remote/.observer_recover_lab/references/2026-03-30-equiv-matrix.json`
   - `all_ok = true`
3. stable observer history：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/observer-full-equivalence-history.json`
   - `history_contract = observer_sample_sequence_v1`
   - `entry_count = 2`
   - `all_ok_latest = true`

### 当前 runtime gate 的关键语义

1. `accepted_fault_required` family 现在显式允许 `accepted-fault completion progress`
2. 因此 `completion_visible > 0` 且 `fault_count > 0` 时，可以合法满足：
   - `fused_step_completion_visible`
   - `completion_consumed_covers_visible`
3. 这条语义已经固定在 runtime gate 实现、authority 和单测里，不应再按旧的 success-only consume 规则理解 fault family

## 2026-03-26 首份 dated reference（历史 WARN）

这一轮 policy hardening 完成后产出的首份 dated summary：

- `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-26-external-dyn-desc-ref-equiv.json`

当时的真实结果：

1. `status = WARN`
2. strict compare 全部匹配。
3. trend compare 现在已经不只给裸 `delta`，还会给结构化解释：
   - `memory.memory_requests` / `memory.memory_bytes`
     - `classification = traffic_cost_delta`
     - `policy.policy_id = memory_cost_research_surface`
   - `gas.windows` / `gas.windows_done`
     - `classification = window_accounting_delta`
     - `policy.policy_id = gas_window_accounting_surface`
   - `step.global_steps_done`
     - `classification = aligned`
     - `policy.policy_id = step_progress_sanity_surface`
   - `snn_tx.spike_packets_total` / `snn_rx.spike_packets_total`
      - `classification = visibility_gap`
      - `gate_level = warn`
      - `policy.policy_id = transport_visibility_surface`
      - `policy.enforcement = warn_on_visibility_gap`
   - `compare.trend_overview` 当前是：
     - `status = passed_with_warning`
     - `aligned_fields = [step.global_steps_done]`
     - `diverged_fields = [memory.memory_requests, memory.memory_bytes, gas.windows, gas.windows_done]`
     - `visibility_gap_fields = [snn_tx.spike_packets_total, snn_rx.spike_packets_total]`
     - `gate_warnings = [trend_visibility_gap:snn_tx.spike_packets_total, trend_visibility_gap:snn_rx.spike_packets_total]`
     - `policy_ids = [gas_window_accounting_surface, memory_cost_research_surface, step_progress_sanity_surface, transport_visibility_surface]`
4. baseline 侧：
   - `run_dir = /home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260326-141641`
   - `smoke_returncode = 1`
   - `validation = failed`
   - `equiv_validation.summary = passed_with_waiver`
   - waiver 吸收的唯一 fail 条目仍然是：
     - `step_activation.invocations_vs_windows: invocations=51 windows=59`
5. runtime_bridge 侧：
   - `run_dir = /home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260326-141702`
   - `smoke_returncode = 0`
   - `validation = passed_with_warning`
   - `runtime_gate.summary = passed`
   - 关键 gate stats：
     - `riscv_snn_backend_runtime_bridge_provider_bound = 64`
     - `riscv_snn_fused_step_completion_count = 64`
     - `riscv_snn_completion_visible_count = 64`
     - `riscv_snn_completion_consumed_count = 64`
     - `riscv_snn_last_completion_status = 0`
     - `riscv_snn_last_fault_csr = 0`

## 当时结论

这份 dated reference 说明：

1. Phase C compare harness 已经能稳定跑通并落 summary，即使某一侧 smoke/validation 非零，也不会再直接崩掉。
2. trend surface 现在已经从“只有裸 delta”升级成“delta + classification + policy + overview”，所以后续讨论 drift 时不必再完全依赖人工口头解释。
3. runtime bridge stats visibility 这条线也已经从“只在 summary 平铺数字”推进到“provider/completion/fault 有独立 runtime gate”。
4. 当前最新 reference 之所以是 `WARN`，不是 strict 或 runtime gate 失败，而是：
   - `snn_tx/snn_rx` 仍然处于 `transport_visibility_surface` 的 `warn_on_visibility_gap`
5. 因此 `Phase D` 更值得优先推进的，是优先补 transport visibility export，而不是继续扩更多 trend 字段。

## 2026-03-26 transport visibility closure update（当前最新）

后续同一天又完成了一轮 fresh root-cause 修复；这一节覆盖上面“最新仍为 `WARN`”的状态描述。

### 根因

真正的问题不是 compare/alias/export，而是 shadow datapath 在 runtime_bridge run 里从一开始就被饿死了：

1. `MultiCorePE` 装配 `StepActivationSubsystem` 时，对
   - `isNonSnnWorkloadKind(cfg.workload_kind)`
   做了统一禁用。
2. `workload_impl=riscv_snn` 因此被和 `stream/traffic/tensor` 一起当成“通用 non-SNN workload”。
3. runtime_bridge 侧的 step seed 注入被静默关闭。
4. 结果就是 shadow `SnnWorkload` 没有收到驱动 Gather/Apply/Scatter 闭环的 seed packet：
   - `rx_packets_total = 0`
   - `acc_updates = 0`
   - `posts_touched = 0`
   - `scatter_spikes_emitted = 0`
   - 最后 `snn_tx/snn_rx` 在 summary 里也只剩 0

### 修复

这次修复刻意保持实验线最小隔离，不改动 `isNonSnnWorkloadKind()` 的既有主线语义：

1. 新增更窄的 helper：
   - `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api/WorkloadConfig.h`
   - `workloadAllowsSnnStimulus(WorkloadKind)`
2. 仅在一个调用点切换：
   - `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
   - 只让 `StepActivationSubsystem` 对 `riscv_snn` 保持 enable
3. 不触碰：
   - `dma_enable`
   - `local_storage_enable`
   - `pulse_enable`
   - `pulse_osa_enable`
4. 新增回归测试：
   - `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_stimulus_gating.cc`

### fresh 验证

执行：

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL"
make test-riscv-snn-stimulus-gating \
     test-riscv-snn-runtime-service-provider \
     test-riscv-snn-runtime-bridge-backend
make -j4
make install

cd "/home/xgy/remote"
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family external_dyn_desc_ref
```

当前最新 dated summary 仍写入：

- `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-26-external-dyn-desc-ref-equiv.json`

但内容已经变为：

1. `status = PASS`
2. `gate_reasons = []`
3. baseline 侧：
   - `run_dir = /home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260326-155813`
   - `equiv_validation.summary = passed_with_waiver`
   - 既有 waiver 仍只覆盖：
     - `step_activation.invocations_vs_windows`
4. runtime_bridge 侧：
   - `run_dir = /home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260326-155835`
   - `runtime_gate.summary = passed`
   - `riscv_snn_backend_runtime_bridge_provider_bound = 64`
   - `riscv_snn_fused_step_completion_count = 64`
   - `riscv_snn_completion_visible_count = 64`
   - `riscv_snn_completion_consumed_count = 64`
5. transport surface 重新可见：
   - `snn_tx.spike_packets_total = 6093`
   - `snn_rx.spike_packets_total = 2409`
6. trend row 依然允许研究型 drift：
   - `memory.memory_requests: 878 -> 640`
   - `memory.memory_bytes: 304086 -> 322880`
   - `gas.windows: 59 -> 50`
   - `gas.windows_done: 27 -> 18`
   - `snn_tx/snn_rx` 现在虽然仍归在 `transport_visibility_surface` policy 下，但已经不再触发 `visibility_gap`
7. runtime run 的 `pe_step_perf_db.csv` 聚合也证明 shadow datapath 已恢复：
   - `rx_packets_total = 1618`
   - `acc_updates = 117`
   - `posts_touched = 117`
   - `scatter_spikes_emitted = 117`

### 当前结论

`Phase C` 这条线现在更准确的状态是：

1. strict surface 仍稳定；
2. baseline waiver 仍稳定；
3. runtime_gate 仍稳定；
4. transport visibility 的 `WARN` 已经收回；
5. 当前剩下的差异主要是研究型 trend drift，而不是“runtime_bridge 根本没有 shadow datapath 活性”。

## 2026-03-26 external spike stimulus gate follow-up

在 `workloadAllowsSnnStimulus()` / `workloadAllowsPureSnnDatapathFeatures()` 两层 helper 收硬之后，又继续检查了剩余 stimulus 入口，重点看：

1. `services/stimulus/ExternalSpikeInputSubsystem`
2. `components/MultiCorePE::handleExternalSpikeEvent()/handleExternalSpike()`
3. `control/SnnPESubComponent::syntheticEmitNeuronFire*()`

这轮的结论是：

1. `external_spike_input` 语义上属于 **Stimulus 域**，应与 `StepActivationSubsystem` 一样走 `workloadAllowsSnnStimulus()`。
2. 因此新增了 `ExternalSpikeInputSubsystem::Runtime.enabled`，并在 `MultiCorePE` 装配时显式写成：
   - `ex_rt.enabled = workloadAllowsSnnStimulus(cfg.workload_kind)`
3. `onSpike()` 现在会先检查这个 runtime gate；对 `stream/traffic/traffic_mem/tensor` 会直接 drop 输入 spike，不再无条件注入本地 core。
4. `syntheticEmitNeuronFire*()` 这轮 **不改**：
   - 原因不是忘了，而是当前它已经被 `ISnnSpikeCommWorkload` 这层接口契约锁在纯 `snn` datapath 上；
   - `riscv_snn` workload 目前不实现该接口，所以不会意外继承这条 synthetic source 路径。

### 这轮新增的 contract surface

新增/更新文件：

1. `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/stimulus/ExternalSpikeInputSubsystem.h`
2. `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/stimulus/ExternalSpikeInputSubsystem.cc`
3. `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
4. `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_stimulus_gating.cc`
5. `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/stimulus/README.md`

`test-riscv-snn-stimulus-gating` 现在固定三层 contract：

1. helper 语义：
   - `snn/riscv_snn` => stimulus allowed
   - `stream/traffic/traffic_mem/tensor` => stimulus denied
2. `ExternalSpikeInputSubsystem::Runtime` 必须显式暴露 `enabled`
3. callsite/guard 不能被悄悄删掉：
   - `MultiCorePE.cc` 必须把 `ex_rt.enabled` 绑定到 `workloadAllowsSnnStimulus(cfg.workload_kind)`
   - `ExternalSpikeInputSubsystem.cc` 必须存在 `if (!rt_.enabled)` 的早退 gate

### fresh 验证

执行：

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL"
make test-riscv-snn-stimulus-gating
make -j4
make install

cd "/home/xgy/remote"
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family external_dyn_desc_ref
```

结果：

1. `make test-riscv-snn-stimulus-gating`：通过
2. `make -j4`：通过
3. `make install`：通过
4. `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-26-external-dyn-desc-ref-equiv.json`
   - `status = PASS`
   - `gate_reasons = []`
   - baseline run：
     - `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260326-164029`
   - runtime run：
     - `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260326-164052`

### 当前判断

这说明：

1. `riscv_snn` 现在不只保留了 step stimulus，也保留了 external spike stimulus 的正确定义；
2. 同时 `stream/traffic/traffic_mem/tensor` 不会再通过 legacy external port 无条件摸到 SNN 注入路径；
3. 纯 `snn` datapath 路径依然没有被放松，实验主线隔离继续成立。

## 2026-03-26 Phase D Task 1 pair-spec surface freeze

在真正扩 freshness gate 之前，先补了 `equiv` family 的静态 surface：

1. `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
   - `EQUIV_FAMILY_SPECS` 现已覆盖五条 builder reference family：
     - `external_dyn_desc_ref`
     - `external_dyn_desc_fault_ref`
     - `external_dyn_desc_bad_policy_ref`
     - `external_dyn_desc_fault_rearm_ref`
     - `external_dyn_desc_fault_overwrite_chain_ref`
2. `riscv_snn_isa_lab/specs/`
   - 新增 8 个 pair spec：
     - `external_dyn_desc_fault_ref_{snn_baseline,runtime_bridge}.json`
     - `external_dyn_desc_bad_policy_ref_{snn_baseline,runtime_bridge}.json`
     - `external_dyn_desc_fault_rearm_ref_{snn_baseline,runtime_bridge}.json`
     - `external_dyn_desc_fault_overwrite_chain_ref_{snn_baseline,runtime_bridge}.json`

### 当前已验证的事实

执行：

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_equiv_family_surface_freezes_fault_lifecycle_pairs \
  -v

python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref_snn_baseline.json"
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref_runtime_bridge.json"
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref_snn_baseline.json"
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref_runtime_bridge.json"
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_snn_baseline.json"
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_runtime_bridge.json"
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_overwrite_chain_ref_snn_baseline.json"
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_overwrite_chain_ref_runtime_bridge.json"
```

结果：

1. `test_equiv_family_surface_freezes_fault_lifecycle_pairs`：通过
2. `python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v`
   - `Ran 47 tests ... OK`
3. 上述 8 条新 pair spec：全部 `validate -> OK`

### 这一步说明什么

这一步当前只说明：

1. 后续 `Phase D` 不再只有 success path 的 pair-spec surface；
2. 四条 fault/policy/lifecycle family 的 baseline/runtime compare 入口已经正式落盘；
3. 后续继续做 `family-aware gate` 与 `equiv-matrix` 时，不需要再临时发明 spec。

这一步当前还不说明：

1. 这四条新增 family 已经 fresh 跑出 dated `PASS/WARN/FAIL`；
2. `run_equivalence()` 已经具备 family-aware fault gate 语义；
3. 顶层 nightly/sidecar 已经把 equivalence family freshness 合并进去。

## 2026-03-26 Phase D Task 2 family-aware gate policy

在 pair-spec surface 冻住之后，又补了一层更关键的解释层：

1. `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
   - 新增 `EQUIV_FAMILY_POLICIES`
   - `_runtime_bridge_gate()` 现在接收 `family=...`
   - `run_equivalence()` 会把 `family_policy` 写回最终 summary

### 当前 family policy 口径

1. `external_dyn_desc_ref`
   - `fault_mode = quiescent`
   - `progress_mode = forward_progress_expected`
   - `fault_lifecycle_mode = none`
2. `external_dyn_desc_fault_ref`
   - `fault_mode = accepted_fault_required`
   - `progress_mode = forward_progress_expected`
   - `fault_lifecycle_mode = single_fault`
3. `external_dyn_desc_bad_policy_ref`
   - `fault_mode = accepted_fault_required`
   - `progress_mode = no_committed_progress_allowed`
   - `fault_lifecycle_mode = single_fault`
4. `external_dyn_desc_fault_rearm_ref`
   - `fault_mode = accepted_fault_required`
   - `progress_mode = fault_lifecycle_surface`
   - `fault_lifecycle_mode = clear_then_refault`
5. `external_dyn_desc_fault_overwrite_chain_ref`
   - `fault_mode = accepted_fault_required`
   - `progress_mode = fault_lifecycle_surface`
   - `fault_lifecycle_mode = overwrite_chain`

### 这层 policy 现在改变了什么

1. 对 `accepted_fault_required` family：
   - `fault_count > 0` 现在是硬约束；
   - 若 fault 根本没发生，会报：
     - `runtime_bridge_expected_fault_missing`
2. 对 fault-oriented family：
   - `last_completion_status != 0` 不再自动触发 success path 的 warning；
   - `runtime_bridge_last_completion_nonzero` 现在只适用于：
     - `fault_mode = quiescent`

### fresh 验证

执行：

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_equiv_family_policies_freeze_fault_expectations \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_runtime_bridge_gate_requires_fault_for_fault_reference_family \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_runtime_bridge_gate_allows_nonzero_completion_status_for_fault_family \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_run_equivalence_allows_fault_completion_status_for_bad_policy_family \
  -v

python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family external_dyn_desc_ref
```

结果：

1. 新增 4 条 family-aware gate 测试：通过
2. `python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v`
   - `Ran 51 tests ... OK`
3. `external_dyn_desc_ref` real `equiv` 仍然 fresh `PASS`
   - summary：
     - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-26-external-dyn-desc-ref-equiv.json`
   - baseline run：
     - `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260326-182337`
   - runtime run：
     - `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260326-182359`

### 当前判断

这一步更准确的结论是：

**Task 2 已经把 gate 从“success-only 隐式语义”推进到了“family-aware 显式语义”，但 freshness coverage 仍待 Task 3 继续扩大。**

## 2026-03-26 Phase D Task 3 equiv-matrix

在 Task 2 把 family-aware gate 语义写硬之后，这一步开始补 dated freshness aggregation surface：

1. `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
   - 新增 `_resolve_equiv_families()`
   - 新增 `run_equiv_matrix()`
   - CLI 新增：
     - `equiv-matrix --group all`
     - `equiv-matrix --family <family>`
2. `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
   - 新增 `test_run_equiv_matrix_writes_family_summary`
   - 新增：
     - `test_main_equiv_matrix_accepts_group_all`
     - `test_main_equiv_matrix_accepts_explicit_family`

### 这一步收硬的不是 compare 语义，而是 aggregation 语义

这层新 surface 明确只做 4 件事：

1. 逐条调用现有 `run_equivalence()`；
2. 把 family 结果聚合成一份 dated summary；
3. 不复制 gate / compare / validation 逻辑；
4. 不创造新的 authority。

因此 top-level `equiv-matrix` summary 只固定：

1. `schema_version = 1`
2. `gate_name = "riscv_snn_equiv_matrix"`
3. `count`
4. `all_ok`
5. `requested_families`
6. `families[{family,status,summary_path,gate_reasons}]`

### fresh 验证

执行：

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" \
  equiv-matrix \
  --family external_dyn_desc_ref \
  --family external_dyn_desc_fault_ref
```

结果：

1. `python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v`
   - `Ran 54 tests ... OK`
2. fresh top-level matrix summary：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-26-equiv-matrix.json`
   - `all_ok = false`
3. 当前两条 family dated result：
   - `external_dyn_desc_ref`
     - `status = PASS`
     - summary：
       - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-26-external-dyn-desc-ref-equiv.json`
   - `external_dyn_desc_fault_ref`
     - `status = FAIL`
     - summary：
       - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-26-external-dyn-desc-fault-ref-equiv.json`
     - `gate_reasons`：
       - `baseline_validation_failed`
       - `runtime_bridge_fused_step_completion_missing`

### 这一步说明什么

这一步现在说明：

1. `Phase D` 已经有了真正的 multi-family dated freshness 入口；
2. `equiv-matrix` 可以把 success 与 fault family 一起放进同一层实验 summary；
3. 这层入口不会把 family 内部的 blocker 吞掉，反而会把它们显式暴露出来。

这一步现在还不说明：

1. 五条 family 都已经 fresh 跑完；
2. `external_dyn_desc_fault_ref` 的 baseline validation / fused-step completion gap 已解决；
3. nightly / sidecar 已经强制依赖这份 matrix。

## 2026-03-26 Phase D fault_ref blocker closure + full family freshness

在 Task 3 跑出第一版 `equiv-matrix` 之后，这一步继续把当时唯一显式暴露的两类 blocker 收敛掉：

1. `baseline_validation_failed`
2. `runtime_bridge_fused_step_completion_missing`

### 根因

当前根因已经明确：

1. baseline 侧
   - 五条 `*_snn_baseline.json` 当前完全同构；
   - 因此 `step_activation.invocations_vs_windows` 不是 `fault_ref` 专属问题，而是当前这组 baseline 共用的 compare-specific 已知 surface。
2. runtime gate 侧
   - `fault_ref` 真实运行里并不是“没有 completion / 没有 progress”；
   - 它有 accepted fault、visible completion、consumed completion；
   - 问题在于 gate 把 success path 的 `fused_step_completion_count > 0` 当成了 fault family 的必要条件。

### 这一步怎么修

1. `EQUIV_VALIDATION_FAIL_WAIVERS`
   - 从只覆盖 `external_dyn_desc_ref`
   - 扩到当前五条 `snn_baseline` family
2. `_runtime_bridge_gate()`
   - 对 `accepted_fault_required` family
   - 允许：
     - `completion_visible > 0`
     - `fault_count > 0`
     共同构成 accepted-fault progress
   - 因而 fault family 不再被 success fused-step cleanliness 误判

### fresh 验证

执行：

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" \
  equiv --family external_dyn_desc_fault_ref

python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" \
  equiv-matrix --group all
```

结果：

1. `python3 -m unittest ... -v`
   - `Ran 56 tests ... OK`
2. `external_dyn_desc_fault_ref`
   - summary：
     - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-26-external-dyn-desc-fault-ref-equiv.json`
   - `status = PASS`
   - `gate_reasons = []`
   - `baseline_equiv_validation.summary = passed_with_waiver`
   - `runtime_gate.summary = passed`
3. full family matrix：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-26-equiv-matrix.json`
   - `count = 5`
   - `all_ok = true`

### 这一步说明什么

这一步现在说明：

1. `fault_ref` 的两个 blocker 已经不是 open issue；
2. 当前五条 family 都已经进入同一份 dated freshness matrix；
3. 当前 family 结果是：
   - `external_dyn_desc_ref = PASS`
   - `external_dyn_desc_fault_ref = PASS`
   - `external_dyn_desc_bad_policy_ref = PASS`
   - `external_dyn_desc_fault_rearm_ref = PASS`
   - `external_dyn_desc_fault_overwrite_chain_ref = PASS`

这一步当前仍不说明：

1. sidecar / nightly 已经把 full equivalence matrix 接成强制 gate；
2. 后续新增 family 可以自动继承同一套 waiver / progress 语义而不需要重新审视；
3. compare surface 已经永久冻结，不再需要继续清理。 

## 2026-03-27 Task 4 sidecar equivalence integration

这一步把 `equiv-matrix` 真的挂进了 top-level sidecar gate，而不是只停留在单独的 dated artifact：

1. `run_ci_sidecar(..., with_equivalence=True)`
   - 现在会调用：
     - `run_equiv_matrix(families=required_families, ...)`
2. sidecar report
   - 新增：
     - `with_equivalence`
     - `equivalence`
3. sidecar markdown
   - 新增：
     - `## Equivalence`
     - family status table
4. CLI
   - `riscv_snn_isa_lab/ci/nightly_sidecar.py`
   - `riscv_snn_isa_lab/tools/riscv_snn_lab.py sidecar`
   都新增：
   - `--with-equivalence`

### 这一轮遇到的真实 blocker

在做 real sidecar 验证时，先暴露了一个不是 sidecar 代码本身的问题：

1. 当前 regression sample spec 缺：
   - `backend_name = runtime_bridge`
2. 结果是 nightly builder/sample 路径会落到错误的 runtime surface，
   进而触发：
   - `memory.nonzero` fail
3. 所以这一步也同步修了两层：
   - `generate_riscv_snn_firmware.py` 的 spec 默认输出
   - 当前 10 条 regression sample spec

### fresh 验证

执行：

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

python3 "/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py" --with-equivalence
```

结果：

1. `python3 -m unittest ... -v`
   - `Ran 60 tests ... OK`
2. fresh sidecar report：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
   - `gate_ok = true`
   - `with_equivalence = true`
3. fresh sidecar markdown：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-summary.md`
   - 已包含 `## Equivalence`
4. fresh dated equivalence matrix：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-27-equiv-matrix.json`
   - `all_ok = true`
   - `count = 5`

### 这一步说明什么

这一步现在说明：

1. full equivalence freshness 已经能进 stable sidecar report；
2. sidecar gate 当前会同时考虑：
   - nightly builder/toolchain/audit
   - equivalence matrix
3. sample runtime spec surface 也已经和 `runtime_bridge` 主线重新对齐，不会再因为 stale sample spec 把 fresh sidecar 先撞坏。

## 2026-03-27 Task 5 full verification + dated evidence closure

### 执行

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL"
make test-riscv-snn-runtime-service-provider \
     test-riscv-snn-runtime-bridge-backend \
     test-riscv-snn-firmware-protocol \
     test-riscv-snn-toolchain-firmware-protocol

cd "/home/xgy/remote"
python3 "/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py" --with-equivalence
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv-matrix --group all
```

### 结果

1. Python regression：
   - `Ran 60 tests ... OK`
2. protocol suite：
   - `make` 命令退出码 `0`
3. fresh sidecar：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
   - `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-summary.md`
   - `gate_ok = true`
   - `reasons = []`
   - `with_equivalence = true`
4. fresh dated equivalence：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-27-equiv-matrix.json`
   - `gate_name = riscv_snn_equiv_matrix`
   - `all_ok = true`
   - `count = 5`
   - family 结果：
     - `external_dyn_desc_bad_policy_ref = PASS`
     - `external_dyn_desc_fault_overwrite_chain_ref = PASS`
     - `external_dyn_desc_fault_rearm_ref = PASS`
     - `external_dyn_desc_fault_ref = PASS`
     - `external_dyn_desc_ref = PASS`

### 冻结下来的解释面

当前可以把 authority 边界明确收成：

1. stable top-level gate：
   - `nightly-sidecar-report.json`
   - `nightly-sidecar-summary.md`
2. dated family-level freshness：
   - `2026-03-27-equiv-matrix.json`
3. dated nightly index：
   - `2026-03-27-nightly-index.json`
   - 仍是 builder/toolchain/audit 视图，不单独承担完整 equivalence authority

### 仍需注意的点

1. 新 family 若继续接入 freshness gate，必须继续走现有 authority surface，不能再引入第二份 metadata authority。
2. 新 sample/spec 默认仍必须显式绑定 `backend_name=runtime_bridge`，否则 nightly/sidecar 很容易再次被 sample drift 撞坏。
3. fault family 的 PASS 不等于可以放松 success path cleanliness；family-aware policy 仍必须保持分族冻结。

## 2026-03-27 Phase E initial parallel implementation

### 这一步实际落了什么

这一轮不是只写 `Phase E` 计划，而是先把第一批骨架落下来了：

1. authority/report/history 语义：
   - `nightly-sidecar-report.json`
   - `nightly-history-index.json`
   - `YYYY-MM-DD-nightly-index.json`
   - `YYYY-MM-DD-equiv-matrix.json`
   现在都带显式：
   - `schema_version`
   - `artifact_role`
   - `authority_scope`
   - `producer`
2. `riscv_snn_lab.py` 新增：
   - `explain-sidecar`
   - `hart-ref`
   - `abi-export`
   - `research-report`
3. ABI authority：
   - `/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_accel_v1.json`
4. fault family toolchain 现在都切到 generated include surface：
   - `.include "abi.inc"`
5. 新的正交 family：
   - `barrier_wfi_order_ref`
6. isolated hart reference bridge：
   - `/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_hart_ref.py`
7. research metrics exporter：
   - `/home/xgy/remote/riscv_snn_isa_lab/tools/export_riscv_snn_research_report.py`

### 验证

执行：

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" explain-sidecar
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" abi-export --output /tmp/riscv_snn_phase_e_abi.inc
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" hart-ref --profile rv64im_zicsr_smoke --summary /tmp/riscv_snn_hart_ref.json
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" research-report --output /tmp/riscv_snn_research_report.json

python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/barrier_wfi_order_ref_snn_baseline.json"
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/barrier_wfi_order_ref_runtime_bridge.json"
```

结果：

1. `python3 -m unittest ... -v`
   - `Ran 71 tests ... OK`
2. `explain-sidecar`
   - 成功输出 authority 角色说明
3. `abi-export`
   - 成功输出 `/tmp/riscv_snn_phase_e_abi.inc`
4. `hart-ref`
   - 成功输出 `/tmp/riscv_snn_hart_ref.json`
   - 当前 `status = program_missing`
5. `research-report`
   - 成功输出 `/tmp/riscv_snn_research_report.json`
6. `barrier_wfi_order_ref` baseline/runtime spec validate
   - 都是 `OK`

### 当前还没完成的点

1. `hart-ref` 还没有真实可运行 ELF，所以目前是结构化 `program_missing`，不是 real Spike PASS。
2. `barrier_wfi_order_ref` 已经进入 family registry 和 spec surface，但还没有跑进真实 dated equivalence 证据。
3. research report 目前已经是独立 artifact，但还没有进一步挂进更高层 explain 面。

## 2026-03-27 Blocker closeout: authority include path + CSR legality

这一轮真实 `nightly_sidecar.py --with-equivalence` 的收口里，先后撞到了两个 blocker，而且它们都不是“临时环境噪声”，而是会导致实验主线分叉的协议层问题：

### blocker 1: fault family `abi.inc` include 路径错误

4 条 fault family toolchain 的 `abi.inc` 一度写成：

```asm
.include "../spec_authority/riscv_snn_accel_v1.inc"
```

但这些目录是以：

```bash
cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/<program>"
make
```

的方式单独编译，所以相对路径必须指回 lab root 下的 `spec_authority/`。最终收硬后的正确契约是：

```asm
.include "../../spec_authority/riscv_snn_accel_v1.inc"
```

并且已经用 source-level test 冻结：

- `test_fault_family_toolchain_abi_bridge_resolves_to_authority_include`

### blocker 2: authority CSR map 越过 RISC-V 12-bit CSR 窗口

`spec_authority/riscv_snn_accel_v1.json` 一度把关键 CSR 写成：

- `0x13A8`
- `0x13AA`
- `0x13D8`
- `0x13DB`

这些值会让 `clang --target=riscv64-unknown-elf` 在 `csrr*` / `csrrwi` 指令位置直接报：

- `operand must be a valid system register name or an integer in the range [0, 4095]`

最终修法不是改 firmware 写法，而是把 authority 真值拉回 runtime 已经冻结的 ABI header：

- `CSR_MSNN_CMDQ_BASE .. CSR_MSNN_CMPQ_TAIL` -> `0xBC8 .. 0xBCF`
- `CSR_MSNN_EVENT_ENABLE .. CSR_MSNN_FAULT` -> `0xBD8 .. 0xBDB`

并新增两条测试：

- `test_bit_level_abi_authority_csr_map_stays_within_12_bit_riscv_window`
- `test_bit_level_abi_authority_csr_map_matches_runtime_header_surface`

这两条测试一起确保：

1. `spec_authority/` 不会再产出非法 CSR 号
2. `spec_authority/` 与 `RiscvSnnAbi.h` 的关键 CSR surface 不会再静默漂移

### 真实验证结果

执行：

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_ref_toolchain" && make
cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_bad_policy_ref_toolchain" && make
cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_rearm_ref_toolchain" && make
cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_overwrite_chain_ref_toolchain" && make

cd "/home/xgy/remote"
python3 "/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py" --with-equivalence
```

结果：

1. `Ran 74 tests ... OK`
2. 4 条 fault family toolchain 全部 `make` 成功
3. `nightly-sidecar-report.json`
   - `gate_ok = true`
4. `2026-03-27-equiv-matrix.json`
   - `all_ok = true`
   - 当前 dated equivalence authority 覆盖 5 条 family

### 仍然刻意保留的边界

1. `barrier_wfi_order_ref` 仍未纳入 stable nightly required families。
2. 这不是遗漏，而是当前 freshness authority 仍只冻结 external dynamic descriptor family surface。
3. barrier family 下一步若要升格进 freshness gate，必须继续沿用现有 authority surface，而不是新增一份 family 名册。

## 2026-03-27 barrier family promoted into stable freshness authority

这一步把上一段里“仍未纳入 stable nightly required families”的 barrier family 真正收口掉了。

### 实际变更

1. `riscv_snn_lab.py`
   - `REFERENCE_REGRESSION_PROGRAMS` 现在把 `barrier_wfi_order_ref` 纳入默认 required surface
   - 因此默认：
     - builder matrix
     - toolchain matrix
     - `authority_required_families()`
     都从 5 条升到 6 条
2. barrier builder sample
   - `RiscvSnnSampleFirmware.h` 新增 `barrier_wfi_order_ref`
   - generator manifest / ELF emit 已能真实列出并生成
3. barrier toolchain bridge
   - `barrier_wfi_order_ref_toolchain/` 现在补齐 `Makefile/crt0.S/linker.ld/abi.inc`
   - `main.S` 切到 `.include "abi.inc"`，不再复制 CSR 数字常量
4. barrier family-aware gate
   - baseline compare-specific waiver 现在也覆盖：
     - `("barrier_wfi_order_ref", "snn_baseline")`
   - `_runtime_bridge_gate()` 现在识别：
     - `timing_mode = wfi_barrier_completion_visibility`
   - 对这类 family，gate 只冻结 visibility-order surface，不再把 success-path 的
     - `fused_step_completion_count > 0`
     - `completion_consumed_count >= completion_visible_count`
     - `last_completion_status == 0`
     当成 PASS 必要条件

### 真实验证

执行：

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

python3 "/home/xgy/remote/sst_dram_si/tools/generate_riscv_snn_firmware.py" \
  --program barrier_wfi_order_ref \
  --elf /tmp/barrier_wfi_order_ref.elf \
  --spec /tmp/barrier_wfi_order_ref.json
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate /tmp/barrier_wfi_order_ref.json

cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/barrier_wfi_order_ref_toolchain" && make

cd "/home/xgy/remote"
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family barrier_wfi_order_ref
python3 "/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py" --with-equivalence
```

结果：

1. `python3 -m unittest ... -v`
   - `Ran 79 tests ... OK`
2. barrier builder sample
   - generator build 成功
   - generated spec validate：`OK`
3. barrier toolchain
   - `make` 成功
4. barrier dated equivalence
   - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-27-barrier-wfi-order-ref-equiv.json`
   - `status = PASS`
   - `baseline.equiv_validation.summary = passed_with_waiver`
   - `runtime_bridge.runtime_gate.summary = passed`
5. stable sidecar
   - `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
   - `gate_ok = true`
   - `required_families = 6`
6. dated equivalence matrix
   - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-27-equiv-matrix.json`
   - `count = 6`
   - `all_ok = true`

### 当前结论

现在 `barrier_wfi_order_ref` 不再只是“已实现但未接门”的 family，而是：

1. 真正进入了 stable freshness authority；
2. 拥有自己的 builder/toolchain/equivalence 真实 dated evidence；
3. 也证明了 `equiv` gate 已经能承载第三种 family 语义：
   - 既不是 success-only；
   - 也不是 accepted-fault-only；
   - 而是 `visibility-order / timing-oriented` family。

## 2026-04-01 optional-group stable attach exposes fresh non-blocking failures

这一步不是再扩一层 wrapper 入口，而是把 generic optional-group attach 真正跑进 stable sidecar，然后接受 stable artifact 给出的最新 truth。

### 实际变更

1. `nightly-sidecar-report.json`
   - 现在真实带出：
     - `with_optional_groups = ["completion_overflow_optional", "queue_optional"]`
     - `optional_group_surfaces`
2. `riscv-snn-research-report.json`
   - 不再是空的 `optional_group_surfaces`
   - 现在会把：
     - `completion_overflow_optional`
     - `queue_optional`
     的 dated matrix surface 直接导出
3. `family-admission-audit`
   - 现在显式冻结：
     - `contract_primary = group_optional_admission_v1`
     - `primary_contract_fields = group_*`
   - `queue_*` 只作为 `queue_optional` compatibility alias 保留
4. `optional-promotion-dossier`
   - 现在显式冻结：
     - `contract_primary = group_optional_promotion_dossier_v1`
   - 并把 admission 的主 contract 一并写进 dossier

### 真实 stable 状态

这次 refresh 后，blocking mainline 仍然是 green：

1. `nightly-sidecar-report.json`
   - `gate_ok = true`
2. blocking required family 仍为 6 条
3. `equiv-matrix` 的 required-family subset 仍然 `all_ok = true`

但 optional line 已经不再是“历史看起来绿”，而是变成了“真实 fresh non-blocking surface”，并暴露出当前失败面：

1. `queue_optional`
   - `all_ok = false`
   - 当前直接失败来源：
     - `queue_backpressure_ref`
       - `baseline_smoke_failed`
2. `completion_overflow_optional`
   - `all_ok = false`
   - 当前直接失败来源：
     - `completion_queue_overflow_ref`
       - `baseline_smoke_failed`
       - `runtime_bridge_smoke_failed`

### 当前新的技术判断

这一步最重要的结论不是“optional surface 接上了”，而是：

1. optional line 的平台化已经完成；
2. 当前真正的 blocker 已经从“surface/contract 缺失”切换为“fresh family stability 没收敛”；
3. promotion readiness 不应该继续从历史绿灯或单条 compact rollup 反推，而要直接服从：
   - `family-admission-audit`
   - `current-mainline-status.md`

另外，这次 fresh dated artifacts 还暴露了一个值得继续深挖的现象：

1. `completion_queue_overflow_ref` 在 `queue_optional` 与 `completion_overflow_optional` 的同日 group matrix 之间出现了结果不一致；
2. 这说明当前 optional family 还存在 group-sensitive / rerun-sensitive 漂移；
3. 因此下一阶段最值当的工作不是再补 metadata，而是把：
   - `queue_backpressure_ref`
   - `completion_queue_overflow_ref`
   的 smoke/runtime 行为重新压回 deterministic green。

## 2026-04-02 optional-family compact-history closure reached raw green

这一步的价值不在于再新增 surface，而在于把前一天暴露出来的两个真实 blocker 压回稳定状态，并把 queue optional 的 stable history 真正收成可重复的 compact green surface。

### 实际进展

1. `queue_backpressure_ref`
   - fresh family rerun 已恢复为 `PASS`
   - 证明先前 `baseline_smoke_failed` 不是当前语义回归，而是环境 / 陈旧 surface 假红
2. `completion_queue_overflow_ref`
   - fresh family rerun 仍为 `PASS`
   - `completion_overflow_optional` fresh group matrix 现也已恢复为 `all_ok = true`
3. singleton optional group freshness
   - 现在同日会优先使用更新的 singleton family surface，而不是被旧 group matrix 继续压住
4. `optional-history-refresh`
   - queue optional 现在有了显式 stable-history compact 入口
   - 可以用 curated dated sample 重建同一份 `queue-optional-equivalence-history.json`
5. `mainline-refresh`
   - observer summary 已改成先看 fresh dossier / admission，再做 compact refresh
   - `observer -> admission -> current-mainline` 的 promotion truth 重新对齐
6. `observer-refresh` / `mainline-refresh`
   - stable sidecar report 里的 `optional_group_surfaces` 现在也会在 compact refresh 前回刷水合到最新 dated refs
   - `nightly-sidecar-summary.md` 不再落后于 observer / current-mainline

### 当前 stable truth

1. `completion_overflow_optional`
   - `group_equivalence_all_ok = true`
   - `group_history_all_dates_ok = true`
   - `promotion_ready = true`
2. `queue_optional`
   - `group_equivalence_all_ok = true`
   - `promotion_ready = true`
   - `group_history_entry_count = 2`
   - `group_history_all_dates_ok = true`
   - `reasons = []`

### 新的阶段判断

现在 optional line 的主问题已经不再是：

1. family rerun 不稳定；
2. 同日 group matrix 分叉；
3. observer / admission promotion truth 错位。

而是已经进一步收敛成：

1. 如何持续维持 queue optional 这条 curated compact history，不让后续 dated scan 把旧 fail 样本重新膨胀回 stable history；
2. full-all non-blocking research 面与 top-level sidecar optional attachments 的回刷节奏是否还需要继续收口；
3. 是否要再跑一次完整 sidecar，把 `generated_utc / latest nightly date / runtime cost` 也整体刷新到下一次全量快照。
