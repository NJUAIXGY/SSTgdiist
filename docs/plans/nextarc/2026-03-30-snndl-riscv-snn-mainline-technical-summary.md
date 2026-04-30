# SnnDL `riscv_snn` Mainline Technical Summary

Date: 2026-04-14
Owner: Fufu
Status: Current formal technical summary for the `riscv_snn runtime-bridge equivalence mainline`

## 1. Mainline Statement

当前唯一应该承认的主线是：

**`riscv_snn runtime-bridge equivalence mainline`**

这条主线的正式定义是：

1. `RISC-V` 只定义 workload/control-plane 语义。
2. 现有 SNN backend 继续承担高频 event/data-plane 执行。
3. `runtime_bridge` 负责把 `riscv_snn` control-plane 命令映射到 shadow `SnnWorkload`。
4. 主线是否成立，由 stable sidecar report 作为唯一 top-level gate 判定，而不是由某一条 smoke、某一条 full-equivalence sample 或某一份 observer history 单独判定。

因此，这条主线当前明确排除三种误放置：

1. 不把 `riscv_snn` 塞进 `CoreShell`。
2. 不把 `riscv_snn` 包装成新的 compute core。
3. 不让 incoming spike 回退成逐条 software handler 主路径。

## 2. Plane Split

### 2.1 Control Plane

`riscv_snn` 当前只负责：

1. hart / firmware 执行
2. CSR 访问
3. command ring / completion ring
4. `wfi` / interrupt / pending-event 处理
5. step-level orchestration

当前关键 architectural object 包括：

1. `msnncmdq_*`
2. `msnncmpq_*`
3. `msnneventen`
4. `msnneventpend`
5. `msnnstatus`
6. `msnnfault`
7. `msnnstep`

### 2.2 Data Plane

data plane 继续由现有 SNN backend 承担：

1. gather / apply / scatter
2. spike ingress / egress
3. packet transport
4. local-hot-state 推进
5. shadow `SnnWorkload` 的真实执行

当前默认 backend：

1. `backend_name = runtime_bridge`

### 2.3 Sync Plane

sync plane 当前负责冻结下面几件事：

1. command accepted 边界
2. completion 的软件可见顺序
3. fault snapshot / clear / overwrite 语义
4. barrier / completion / `wfi` 的唤醒关系
5. optional 与 supplementary derived surface 的 freshness 对齐

## 3. Single Authority Chain

### 3.1 Spec Authority

当前 machine-readable authority 共有四层 stable 主链，外加一个下一阶段独立建模域：

1. ABI / control-plane authority
   - `/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_accel_v1.json`
2. mainline gate authority
   - `/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_mainline_gate_v1.json`
3. runtime gate authority
   - `/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_runtime_gate_v1.json`
4. supplementary surface authority
   - `/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_supplementary_surface_v1.json`
5. next-stage architecture model authority domain
   - `/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json`

这四层 authority 的职责分工当前已经固定：

1. ABI authority 冻结 CSR / ring / completion / fault 字段语义。
2. mainline gate authority 冻结 required family、optional group、promotion contract 与默认 refresh group。
3. runtime gate authority 冻结 family-specific progress/fault/check 语义。
4. supplementary authority 冻结 non-blocking supplementary surface 的字段与 history contract。
5. architecture model authority 现在同时冻结 chip abstract machine taxonomy 与 program semantics bridge，但仍然不替代 stable mainline gate authority。

这意味着当前必须显式区分两个 authority 域：

1. `stable mainline authority domain`
   - ABI
   - mainline gate
   - runtime gate
   - supplementary surface
2. `next-stage architecture-model authority domain`
   - entity taxonomy
   - layer taxonomy
   - time taxonomy
   - counter taxonomy
   - fused-step / memory / fabric semantics
   - program control event taxonomy
   - program semantic profiles

第二个域当前已经建起来，但它的角色仍然是：

1. `top_level_gate_role = none`
2. 不参与当前 blocking gate 判定
3. 只为下一阶段 architecture research platform 预留单一真值源

### 3.2 Top-Level Authority

当前唯一 top-level gate 是：

1. `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`

它不是某个“方便阅读的摘要”，而是当前实验主线的唯一 blocking authority。当前 stable state 为：

1. `gate_ok = true`
2. `with_equivalence = true`
3. `with_full_equivalence = true`
4. `required_families` 固定为 6 条
5. `with_optional_groups = ["completion_overflow_optional", "queue_optional"]`
6. `supplementary_surfaces.compare` 已 attach，且 `blocking = false`
7. `riscv_snn_architecture_model_v1.json` 已作为独立建模 authority 域存在，但不改变当前 top-level gate

### 3.3 Derived Stable Surfaces

下面这些都已经是 stable surface，但都属于 derived，而不是新的 authority root：

1. observer summary
2. research report
3. adequacy validation
4. current-mainline markdown
5. sidecar summary markdown
6. stable-surface-refresh-audit
7. observer full-equivalence history
8. supplementary surface history
9. observer fail/recovery loop summary

它们的存在是为了两个目标：

1. 给人类和工具提供稳定读取面。
2. 让 single-authority chain 的漂移能够被正式审计出来。

## 4. Surface Taxonomy

### 4.1 Required Blocking Families

当前 blocking required family 只有 6 条：

1. `barrier_wfi_order_ref`
2. `external_dyn_desc_bad_policy_ref`
3. `external_dyn_desc_fault_overwrite_chain_ref`
4. `external_dyn_desc_fault_rearm_ref`
5. `external_dyn_desc_fault_ref`
6. `external_dyn_desc_ref`

这一列表的真值只来自 mainline gate authority，不再跟随某个 builder matrix 或 dated index 隐式变化。

### 4.2 Optional Groups

当前 optional group 只有两层，且都明确是 non-blocking：

1. `completion_overflow_optional`
   - family：`completion_queue_overflow_ref`
   - `blocking = false`
   - current `promotion_ready = true`
   - latest date：`2026-04-04`
   - `effective_entry_count = 2`
   - `effective_all_dates_ok = true`
2. `queue_optional`
   - family：`queue_backpressure_ref`、`completion_queue_overflow_ref`
   - `blocking = false`
   - current `promotion_ready = true`
   - latest date：`2026-04-04`
   - `effective_entry_count = 2`
   - `effective_all_dates_ok = true`

optional group 当前不会自动升级为 blocking gate，但它们已经被正式接入 stable derived chain：

1. live attach 在 sidecar `optional_group_surfaces`
2. rollup 出现在 observer summary `optional_group_rollups`
3. current-mainline-status 会直接暴露 freshness 与 admission 状态
4. stable-surface-refresh-audit 会检查 optional rollup 是否与 live surface 一致

### 4.3 Supplementary Surfaces

当前 supplementary surface 只有一条：

1. `compare`

它的当前稳定状态是：

1. `blocking = false`
2. `gate_ok = true`
3. `latest_date = 2026-04-07`
4. `freshness_mode = since_latest_recovery`
5. `effective_all_dates_ok = true`

这条 surface 的定位不是“随手贴一个外部报表链接”，而是：

1. 通过 supplementary authority attach 到 stable sidecar
2. 通过 supplementary history 写回稳定观察面
3. 通过 stable-surface-audit 检查 sidecar、observer、current-mainline、summary-md 的链路一致性

## 5. Control-Plane Semantics

当前 control-plane contract 已经从“设计口径”推进成“authority + exporter + tests + reference programs 共同冻结”的状态。最关键的语义是：

1. `msnncmdq_tail` 是唯一 architectural doorbell。
2. backend 推进 `cmdq_head` 之前，命令不能算 accepted。
3. completion 的软件可见顺序固定为：
   - payload
   - `cmpq_tail`
   - pending event
4. `msnnfault clear` 只清当前可见 snapshot，不顺手清 `EV_FAULT`。
5. 新的 accepted fault 可以覆盖当前可见 `msnnfault`，但不会回写已经退休 completion 的 fault snapshot。
6. RX ring 仍然只是 debug / auxiliary surface。

bit-level contract 的唯一推荐导出入口是：

```bash
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" export-control-plane-contract \
  --output "/tmp/riscv_snn_control_plane_contract.md" \
  --json-output "/tmp/riscv_snn_control_plane_contract.json"
```

当前不再接受“手写一份 bit-level 文档，再由代码去猜测是否一致”的做法。

## 6. Runtime Gate Semantics

runtime gate authority 当前已经把 family-specific 解释写硬。几个关键例子：

1. `external_dyn_desc_ref`
   - `fault_mode = quiescent`
   - `progress_mode = forward_progress_expected`
   - completion 应该被完整消费，fault 应保持 quiescent
2. `external_dyn_desc_fault_ref`
   - `fault_mode = accepted_fault_required`
   - accepted-fault completion progress 计入 forward progress
3. `barrier_wfi_order_ref`
   - `timing_mode = wfi_barrier_completion_visibility`
   - barrier 可见 completion 本身可以满足 timing contract
4. `completion_queue_overflow_ref`
   - `progress_mode = completion_queue_fault_surface`
   - 一个 software-visible completion 可以在 `cmpq-full` fault 退休时刻意保持未消费
5. `queue_backpressure_ref`
   - `progress_mode = queue_backpressure_fault_surface`
   - command-overdoorbell overflow 可以在 software ack completion 之前 fault

这意味着：

1. 不同 family 的“progress 成立条件”不再共享一条 success-only 解释。
2. optional family 即使是 non-blocking，也必须沿同一 runtime gate taxonomy 被判定。

## 7. Current Next Package: Program Semantics Authority Bridge

按照当前主线状态，下一段任务已经从“继续补 architecture taxonomy”切换到“把 runtime gate family 与 architecture authority 的 program semantics 穿透链写硬”：

**`Program Semantics Authority Bridge Package`**

这段任务包当前收敛成 `WP1-WP5`：

1. `WP1`：在 runtime gate family 下冻结 `reference_program_profile`
2. `WP2`：在 architecture authority 中冻结 `program_control_event_taxonomy` 与 `program_semantic_profiles`
3. `WP3`：让 authority-driven builder 成为 `ReferenceProgramRequest` 的唯一来源
4. `WP4`：让 `reference_program_compare` / `explain-program-semantics` / `explain-runtime-gate` 消费同一条 profile binding
5. `WP5`：增加 profile binding validation，明确所有 required/equiv family 都能稳定落到已声明 profile

这一段的目标不是新增 authority root，而是把下面这条链打通：

1. `runtime_gate family`
2. `reference_program_profile`
3. `architecture authority.program_semantic_profiles`
4. `ReferenceProgramRequest`
5. `runtime_program_summary / ReferenceMachine.execute_program(...)`

下文其余小节保留的是这段桥接所依赖的已落地基础：`fused_step`、memory、fabric、program compare surface、以及已进入 stable derived chain 的 reference program model。当前应该把它们视为 bridge stage 的输入前提，而不是新的并行主线。

### 7.1 Package Scope

这一段任务包建议收成 3 个连续子任务：

1. `Task 2A: FUSED_STEP semantic freeze`
   - 在 `riscv_snn_architecture_model_v1.json` 中补 `fused_step_state_machine`
   - 冻结：
     - `Idle`
     - `Accepted`
     - `Decoded`
     - `ResourcesReserved`
     - `Executing`
     - `OutboundDraining`
     - `BarrierWaiting`
     - `Completed`
     - `Faulted`
   - 为每个状态补：
     - 进入条件
     - completion/fault 边界
     - architecture-visible 与 model-internal 边界
2. `Task 3A: memory hierarchy freeze`
   - 在 authority 中补 `memory_taxonomy`
   - 冻结：
     - `ControlMemory`
     - `LocalStateMemory`
     - `SynapseMemory`
     - `BackingMemory`
     - `TransferPath`
   - 写清 descriptor/completion 与 neuron/synapse 的层次归属
3. `Task 3B: event/fabric freeze`
   - 在 authority 中补 `fabric_taxonomy`
   - 冻结：
     - ingress receive
     - local classify
     - queue merge
     - execution consume
     - spike generate
     - egress enqueue
     - router transit
     - remote ingress commit
   - 写清允许出现差异的位置：
     - queue occupancy
     - backpressure
     - multicast expansion
     - memory service conflict

### 7.2 Package Exit Criteria

这一段任务完成后，应该满足：

1. `riscv_snn_architecture_model_v1.json` 不再只是 taxonomy，而是新增：
   - `fused_step_state_machine`
   - `memory_taxonomy`
   - `fabric_taxonomy`
2. 我们能用一句不可歧义的话定义：
   - `FUSED_STEP completion` 当且仅当什么成立
3. 我们能明确区分：
   - architecture-visible state
   - microarchitectural state
   - simulator bookkeeping state
4. 这组定义仍然不改变当前 stable mainline truth：
   - blocking gate 继续只看 `nightly-sidecar-report.json`

### 7.3 Documentation Strategy

这段任务包当前已经明确采用“修订已有文档”的方式推进，而不是继续叠加独立规划稿。

当前建议只修订：

1. `/home/xgy/remote/docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
2. `/home/xgy/remote/docs/plans/nextarc/2026-03-30-snndl-riscv-snn-next-stage-mainline-hardening-implementation-plan.md`
3. `/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json`

### 7.4 Current Code-Landing Mainline

当前语义冻结包的工程主线已经明确，不再是“继续堆更多 family”，而是按下面顺序落地：

1. 在 `riscv_snn_lab.py` 增加 architecture authority 的正式读取入口，让 `riscv_snn_architecture_model_v1.json` 与 mainline/runtime/accel authority 采用同一读取纪律。
2. 在 `test_riscv_snn_lab.py` 追加 targeted tests，先把 `FUSED_STEP` completion 边界、state ordering、visibility domain 冻结成 machine-readable 断言。
3. 再把 `memory_taxonomy` 的五个 domain 和 `fabric_taxonomy` 的八段 event path 与四类 allowed divergence 点固定下来。
4. 上面三步完成前，不创建 `riscv_snn_isa_lab/architecture_model/` 子树；完成后，reference model 只能消费这份 authority，而不能反向发明新的语义。

这条代码落地主线继续遵守实验隔离原则：

1. 不修改默认 `snn` 的行为。
2. 不让 `riscv_snn_architecture_model_v1.json` 取代 `nightly-sidecar-report.json` 的顶层 gate 角色。
3. 不引入第二份 architecture metadata authority。
4. 不让 adapter 或 trace tool 先于 authority 冻结做设计决策。

### 7.5 Task 2A Status

当前已经把 `Task 2A` 的核心语义写进 `riscv_snn_architecture_model_v1.json`：`fused_step_state_machine` 现在包含 `semantic_statement`、`completion_boundary`、`fault_boundary`、`visibility_domains` 以及按顺序固定的九个状态描述（`Idle` 到 `Faulted`）。这些字段已经被机器可读地冻结，completion 当且仅当当前 step 的架构可见状态已提交、本 step 产生的本地 outbound spike 已跨过本地 egress/fabric 交接边界、当前 barrier domain 的 release 条件已满足并可见、且没有更高优先级 fault 抢占当前 completion。`load_architecture_model_authority()` 已经通过与其他 authority 相同的加载套路暴露这些字段，`test_riscv_snn_lab.py` 中的 targeted tests 也已冻结 state ordering、visibility、completion 意图，避免后续 reference model 或 adapter 擅自改写主线语义。

Task 2A 完成后，主线仍严格遵守：

1. `Task 3A`（memory hierarchy freeze）、`Task 3B`（fabric taxonomy freeze）、`architecture_model` 子树引用都还在排队，没有进入实现。
2. 这份 authority 仍然 confined 在 `architecture_model_only`、`top_level_gate_role = none`，没有替代 nightly gate 或控制平面合约。
3. reference model 只能消费这份 machine-readable FUSED_STEP 描述，而不允许先于 authority 独立发明新的 completion 语义。

### 7.6 Task 3A Status

`Task 3A` 已经把 `memory_taxonomy` 写入 `riscv_snn_architecture_model_v1.json`，并把五个 memory domains 机器可读地冻结为：

1. `ControlMemory`
2. `LocalStateMemory`
3. `SynapseMemory`
4. `BackingMemory`
5. `TransferPath`

当前已经写硬的关键归属包括：

1. `descriptor / CSR / completion / fault` 属于 `ControlMemory`
2. `membrane / threshold / refractory / local-hot neuron state` 属于 `LocalStateMemory`
3. `weights / connectivity / fanout metadata` 属于 `SynapseMemory`
4. `DRAM / host-seeded backing arrays / cold snapshots` 属于 `BackingMemory`
5. `prefetch / fill / spill / dma-like transfer records` 属于 `TransferPath`

`test_riscv_snn_lab.py` 中的 targeted tests 现在已经冻结：

1. 五个 domain 的名称与顺序
2. `ControlMemory.architecturally_visible = true`
3. `LocalStateMemory` 与 `SynapseMemory` 默认不对软件可见
4. `TransferPath.contention_scope` 的显式存在与固定语义

### 7.7 Task 3B Status

`Task 3B` 已经把 `fabric_taxonomy` 写入 authority，并把 event/fabric path 冻结为以下八段：

1. `ingress_receive`
2. `local_classify`
3. `queue_merge`
4. `execution_consume`
5. `spike_generate`
6. `egress_enqueue`
7. `router_transit`
8. `remote_ingress_commit`

同时，当前允许保留在 microarchitecture 层的差异点也已经冻结为：

1. `queue_occupancy`
2. `backpressure`
3. `multicast_expansion`
4. `memory_service_conflict`

`test_riscv_snn_lab.py` 中的 targeted tests 现在已经冻结：

1. 八段 stage 的名称与顺序
2. `allowed_divergence_points` 的固定集合
3. `queue_merge` 与 `router_transit` 默认不是 architecture-visible
4. `remote_ingress_commit` 的存在性和建模可见性

### 7.8 Semantic Freeze Package Status

到当前为止，`fused_step_state_machine`、`memory_taxonomy`、`fabric_taxonomy` 三块都已经完成 machine-readable freeze，语义冻结包本身已经闭环。

但主线边界仍然保持不变：

1. 还没有进入 `riscv_snn_isa_lab/architecture_model/` 子树实现。
2. 没有改变 `nightly-sidecar-report.json` 作为 top-level gate authority 的角色。
3. 没有改变默认 `snn` 主线行为。
4. 没有引入第二份 architecture metadata authority。
5. 未来的 reference model 只能消费这份 authority，不能反向发明新的语义。

### 7.9 Next Major Stage

当前下一大阶段已经明确切换为：

**`Architecture Model Reference Mainline`**

这一阶段的目标，不再是继续补 taxonomy，而是把已经冻结好的 architecture authority 落成一个真正可执行、可比较、但仍严格隔离的 reference model 主线。

当前冻结下来的阶段主线是：

1. 先建立 `riscv_snn_isa_lab/architecture_model/` 子树骨架
2. 再实现最小 `FUSED_STEP` reference execution
3. 再补 memory/fabric accounting
4. 再接 reference-vs-runtime comparison adapter
5. 最后把 reference outputs 作为 derived research surface 接回实验主线

这一阶段继续保持五条硬边界：

1. 不改变默认 `snn` 主线行为
2. 不改变 `nightly-sidecar-report.json` 作为 top-level gate authority 的角色
3. 不引入第二份 architecture metadata authority
4. `architecture_model/` 只消费 `riscv_snn_architecture_model_v1.json`
5. 先做 semantic reference model，而不是复杂 timing-heavy 微架构模拟器

当前建议的里程碑是：

1. `M1`: Reference Model Skeleton
2. `M2`: Single-Step Reference Execution
3. `M3`: Memory/Fabric Accounting
4. `M4`: Runtime Comparison Adapter
5. `M5`: Research Surface Integration

### 7.10 Package A Status

`Package A` 已完成：`riscv_snn_isa_lab/architecture_model/` 子树骨架、`ReferenceMachine` skeleton 都已经实现，并能加载 `riscv_snn_architecture_model_v1.json` 组合 `fused_step`、`memory`、`fabric` 模型。
目前只完成 authority consumption 与 model assembly，尚未运行 single-step execution，也没有触及 `Package B` 及以后的 execution/compare 层。
这一工作依旧没改 `nightly-sidecar-report.json`、默认 `snn` 主线或 authority discipline，保持了实验主线的隔离。

### 7.11 Package B Status

`Package B` 已完成最小 single-step reference execution：`ReferenceMachine` 现在已经能够依据已冻结的 `fused_step_state_machine` authority 执行一次抽象 `FUSED_STEP`，并产出 machine-readable step result。

当前已经跑通的三条最小执行路径是：

1. completion boundary 全部满足时，终态为 `Completed`
2. fault boundary 全部满足时，终态为 `Faulted`
3. completion boundary 缺项时，终态保持在 `BarrierWaiting`

当前 step result 已经显式区分：

1. `architectural_state`
2. `microarchitectural_progress`
3. `simulator_bookkeeping`

但主线边界仍然保持不变：

1. `Package C/D/E` 现已全部进入并完成最小闭环
2. `nightly-sidecar-report.json` 仍保持 top-level gate 角色不变
3. 默认 `snn` 主线行为仍不变
4. `reference_compare` 只是 supplementary research surface，不是新的 authority

### 7.12 Package C Status

`Package C` 已完成：reference execution 现在不只给出终态，还会导出结构化 accounting。

当前稳定导出的三类 accounting 是：

1. `memory_events`
2. `fabric_events`
3. `divergence_observations`

这些 accounting 继续只消费 `riscv_snn_architecture_model_v1.json` 中已经冻结的 taxonomy：

1. memory domains 来自 `memory_taxonomy`
2. fabric stages 来自 `fabric_taxonomy.stages`
3. divergence points 来自 `fabric_taxonomy.allowed_divergence_points`

因此这条线的意义不是做 timing-heavy 模拟，而是把 single-step semantic execution 推进到“可对账、可解释、可比较”的 machine-readable reference accounting。

### 7.13 Package D Status

`Package D` 已完成：`runtime_compare.py` 已经建立起最小 `reference -> runtime_bridge` 语义对齐桥。

当前 compare summary 至少冻结了四类对齐项：

1. terminal state alignment
2. memory domain alignment
3. fabric stage alignment
4. divergence classification

当前状态下，reference compare 会把 divergence 区分成：

1. `allowed_divergence`
2. `invalid_divergence_points`

也就是说，主线现在已经能明确地区分“语义一致但存在被允许的微架构漂移”和“真正越过冻结契约的对齐失败”。

### 7.14 Package E Status

`Package E` 已完成：`reference_compare` 现在已经作为 derived research surface 接入实验主线。

它当前挂接到三条稳定可读 surface：

1. `reference-compare-nightly-report.json`
2. `reference-compare-nightly-summary.md`
3. `reference-compare-current-status.md`

同时，这条 supplementary surface 会被继续透传到：

1. `nightly-sidecar-report.json -> supplementary_surfaces.reference_compare`
2. `riscv-snn-research-report.json -> supplementary_surfaces.reference_compare`
3. `current-mainline-status.md` 的 `Supplementary Surfaces` 区块

这条线当前仍严格满足主线边界：

1. non-blocking
2. supplementary only
3. 不改变 top-level gate authority
4. 不改变默认 `snn` 路径
5. 不引入第二份 architecture authority

### 7.15 Operational Follow-On Stage

当前主线下一段已经切换到：

**`Multi-Step Reference Program Model`**

它的目标不是再发明一层新的 gate，而是把现有：

1. single-step reference execution
2. runtime comparison adapter
3. non-blocking `reference_compare` supplementary surface

推进成 program-level trace compare 主线，让 frozen family 能被解释成一段多步语义程序，而不是只停留在单 step 对齐。

这条 follow-on stage 继续保持四条硬边界：

1. `reference_program_compare` 仍然是 supplementary / non-blocking surface
2. 不改变 `nightly-sidecar-report.json` 的 top-level gate authority
3. 不改变默认 `snn` 主线
4. 不引入第二份 architecture metadata authority

### 7.16 Multi-Step Reference Program Model Status

当前 program-level model 已经落成最小闭环，并且完整接入现有 operator / observer / audit 链。

#### Task A: Program Trace Abstract Machine

`architecture_model/` 当前已经不再只有 `execute_fused_step(...)`，而是新增了 program-level trace 对象和执行入口：

1. `ReferenceProgramStep`
2. `ReferenceProgramRequest`
3. `ReferenceProgramTraceEntry`
4. `ReferenceProgramResult`
5. `ReferenceMachine.execute_program(...)`

当前冻结下来的 program-level 可见序列至少覆盖：

1. `Faulted -> clear -> Faulted`
2. `Faulted -> overwrite -> Faulted`
3. `BarrierWaiting -> Completed`
4. `Completed`
5. `Faulted`

也就是说，architecture model 现在已经能描述：

1. completion sequence
2. fault sequence
3. barrier-wait sequence
4. clear / overwrite fault lifecycle
5. per-step memory / fabric / divergence trace

#### Task B: Program-Level Compare Adapter

当前新增了 `compare_reference_program_to_runtime(...)`，它会把 reference program trace 和 runtime program summary 做正式对齐，至少校验：

1. `terminal_state_sequence`
2. `completion_step_indices`
3. `fault_step_indices`
4. `barrier_wait_step_indices`
5. `clear_fault_before_step_indices`
6. `overwrite_fault_step_indices`
7. `fault_snapshot_sequence`
8. per-step memory / fabric / divergence alignment

同时它继续保留和 step-level compare 一样的三态结论：

1. `aligned`
2. `allowed_divergence`
3. `mismatch`

#### Task C: Command Plane

当前正式新增三条 program-level operator 命令：

1. `reference-program-compare`
2. `reference-program-compare-matrix`
3. `reference-program-compare-refresh`

它们分别覆盖：

1. 单 family program compare
2. frozen family program matrix
3. stable `reference_program_compare` surface refresh

#### Task D: Stable Surface / Observer Closure

`reference_program_compare` 当前已经拥有自己的稳定 surface：

1. `reference-program-compare-history.json`
2. `reference-program-compare-nightly-report.json`
3. `reference-program-compare-nightly-summary.md`
4. `reference-program-compare-current-status.md`

同时它已经进入：

1. `nightly-sidecar-report.json -> supplementary_surfaces.reference_program_compare`
2. `nightly-sidecar-observer-summary.json -> supplementary_surface_rollups.reference_program_compare`
3. `current-mainline-status.md -> Supplementary Surfaces`
4. `nightly-sidecar-summary.md -> Supplementary Surfaces`

#### Task E: Contract / Audit Alignment

`reference_program_compare` 现在已经对齐 supplementary surface authority 的同一组 freshness / health 字段：

1. `present`
2. `gate_ok`
3. `latest_date`
4. `stale`
5. `freshness_mode`
6. `effective_all_dates_ok`
7. `history_contract`

并且已经进入 `stable-surface-audit` 的统一链路，不再是独立游离报表。

#### Task F: Current Verification Entry

当前 program-level 主线的最小回归入口是：

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab
```

这一步现在已经覆盖：

1. program dataclasses / execution
2. program compare classification
3. program-level stable surface refresh
4. CLI command plane
5. current-mainline / sidecar-summary integration
6. observer / audit closure

因此 `reference_compare` 现在不只是能生成，还已经进入正式验收链。

## 8. Canonical Operator Flows

### 8.1 Read-Only Explain Flow

当目标是理解当前主线，而不是刷新 stable surface 时，推荐顺序是：

```bash
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" explain-mainline
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" explain-runtime-gate --family external_dyn_desc_fault_ref
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" export-mainline-status
```

这个流程只读取 authority 与 stable references，不重写 derived surface。

### 8.2 Stable Mainline Refresh Flow

`mainline-refresh` 当前是主线级正式 operator 命令：

1. 读取 mainline gate authority，确定 active optional group
2. 刷新该 group 的 admission surfaces
3. 导出 promotion dossier
4. 刷新 observer summary、research report、adequacy validation、current-mainline-status
5. 刷新 supplementary history 与 sidecar summary markdown
6. 自动执行 stable-surface-audit

当前默认 active group 由 authority 冻结为：

1. `completion_overflow_optional`

### 8.3 Observer History Refresh Flow

`observer-history-refresh` 的职责现在已经收成单一语义：

1. 更新 stable observer full-equivalence history
2. 支持显式注入 sample
3. 支持 `--compact-since-latest-recovery`
4. 不改 blocking gate，只改 observer history 本身

截至当前 stable observer history：

1. `entry_count = 4`
2. `all_ok_latest = true`
3. `latest_recovered_date = 2026-04-02`

### 8.4 Formal Observer Fail / Recovery Flow

`observer-fail-recovery` 当前已经是正式命令面，而不是人工 orchestration：

1. 先按 active optional group 刷新 optional history
2. 依据 group authority 的 refresh mode 决定是否采用 latest-recovery compaction
3. 调用 `mainline-refresh`
4. 再执行 `stable-surface-audit`
5. 输出 formal summary

当前 stable summary 表示：

1. `all_ok = true`
2. `group = completion_overflow_optional`
3. `group_history_refresh_mode_expected = compact_latest_recovery`
4. `group_history_effective_all_dates_ok = true`

### 8.5 Why Non-Blocking Surfaces Still Need Freshness Alignment

optional 与 supplementary surface 都不是 blocking gate，但它们仍然必须 freshness 对齐，原因有三条：

1. 它们已经进入 stable sidecar 的 live attach surface，不再是旁路说明文字。
2. observer summary、current-mainline-status、sidecar summary 都会直接暴露这些 surface 的当前状态。
3. 如果这些 non-blocking surface 漂移，主 gate 即使还是 PASS，人类和工具也会读到分叉状态。

因此当前真正被冻结的是：

1. blocking 与 non-blocking 的角色边界
2. 但不是 freshness discipline 的松绑

## 9. Stable Refresh Audit Contract

`stable-surface-audit` 当前检查的不是“某个 surface 自己是否看起来合理”，而是整条 authority chain 是否还保持单一路径。当前审计重点包括：

1. sidecar refresh metadata 与实际 derived path 是否一致
2. observer summary 是否把 stable sidecar 当作 authority entrypoint
3. research report 是否把 observer summary 当作来源
4. adequacy validation 是否把 research report 当作来源
5. current-mainline-status 和 sidecar summary markdown 是否都包含关键 marker path
6. optional group rollup 是否与 sidecar live attach surface 一致
7. supplementary compare surface 是否与 observer/current-mainline/summary-md 保持链路一致

截至当前 stable audit：

1. `all_ok = true`
2. `optional_group_rollups.completion_overflow_optional.ok = true`
3. `optional_group_rollups.queue_optional.ok = true`
4. `supplementary_surfaces.compare.ok = true`
5. `supplementary_surfaces.compare_chain.ok = true`

## 10. Current Snapshot

截至 `2026-04-14` 这轮整理，当前可直接承认的 stable facts 是：

1. stable sidecar gate：`PASS`
2. required families：6 条，全部 `PASS`
3. observer full-equivalence history：`entry_count = 4`，`latest_recovered_date = 2026-04-02`
4. `completion_overflow_optional`：promotion-ready，freshness 对齐
5. `queue_optional`：promotion-ready，freshness 对齐
6. supplementary `compare`：`gate_ok = true`，latest date `2026-04-07`
7. stable-surface-audit：`all_ok = true`
8. runtime gate family 已冻结 `reference_program_profile`
9. architecture authority 已冻结 `program_control_event_taxonomy` 与 `program_semantic_profiles`
10. `reference_program_compare` 的主执行路径已经切到 authority-driven builder，并新增 `explain-program-semantics`

这组事实共同说明：

1. 主线已经不只是“功能能跑”。
2. 当前已经具备 stable top-level gate、derived surface chain、observer fail/recovery 闭环与 supplementary freshness discipline。
3. 下一阶段工作的第一段，已经从 taxonomy freeze 转到 `Program Semantics Authority Bridge Package`。
4. 后续继续深化时，应该沿 profile binding / explain / validation / supplementary surface 这条桥推进，而不是回退到 family-local helper。

## 11. Reading Order

如果要快速理解当前主线，推荐阅读顺序是：

1. 本文档：理解完整技术主线。
2. `/home/xgy/remote/riscv_snn_isa_lab/README.md`：作为实验目录入口。
3. `/home/xgy/remote/riscv_snn_isa_lab/references/current-mainline-status.md`：读取当前稳定状态。
4. `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`：查看唯一 blocking gate。
5. `/home/xgy/remote/riscv_snn_isa_lab/references/stable-surface-refresh-audit.json`：确认 derived chain 未漂移。
