# SnnDL `riscv_snn` 当前现状深度总结与下一阶段建议

Date: 2026-03-26
Owner: Fufu
Status: Historical snapshot after Phase C PASS refresh and external-spike stimulus gate hardening

> 说明：
> 这份文档保留为 `2026-03-26` 的历史快照，不再代表最新现状。
>
> 当前最新主线现状请优先看：
> 1. `/home/xgy/remote/riscv_snn_isa_lab/README.md`
> 2. `/home/xgy/remote/docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
> 3. `/home/xgy/remote/riscv_snn_isa_lab/references/current-mainline-status.md`
> 4. `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
>
> 这份历史稿里的架构判断大体仍有参考价值，但下面这些当前口径已经更新：
> 1. stable derived chain 现在已经包含 `observer-history-refresh`、`observer-fail-recovery` 和 `stable-surface-audit` 的正式命令面。
> 2. optional group 当前不只是 queue line；`completion_overflow_optional` 已成为 authority 指定的 primary/mainline-refresh group。
> 3. supplementary `compare` 已经进入 stable sidecar attach surface 与 audit 链，而不再只是旁路 research surface。

## 1. 一句话结论

`riscv_snn` 这条线已经从“设计正确但实现风险高”的阶段，推进到“架构边界已经基本答对、实验入口已经成型、至少有一条 full-stack family 可以 fresh 跑出 PASS”的阶段。

但它还没有进入“可以不看上下文就大规模扩写”的成熟期。

更准确地说，它现在是：

1. **架构主线正确**
2. **实验承载入口基本稳定**
3. **协议/样例/toolchain bridge 族谱已经形成**
4. **Phase C 的 runtime bridge 已经有真实 PASS 证据**
5. **剩余风险从“方向错了”转成了“边界还要继续收硬、趋势漂移还要继续解释”**

## 2. 现在已经稳定下来的部分

### 2.1 架构层放置已经答对

当前最重要的架构判断已经不再摇摆：

1. `riscv_snn` 明确属于 `workload/control-plane`
2. 它不是新的 `CoreShell`
3. 它也不是新的 `ISnnComputeCore`
4. `CoreShell` 继续只做平台壳
5. 高速 spike/gather/apply/scatter 仍由现有 SNN backend/data plane 执行

这条判断的价值非常大，因为它避免了两种最危险的演进方向：

1. 把 CPU 语义塞回 `CoreShell`
2. 把 `riscv_snn` 假装成另一种 SNN compute core

一旦这两条走错，后续 CSR、queue、runtime bridge、equivalence 全都会变形。

### 2.2 control-plane 协议面已经形成稳定口径

当前最关键的一组协议判断已经在样例、reference、tooling、equivalence harness 里形成了统一口径：

1. `cmdq_tail` 是唯一 architectural doorbell
2. `Accepted` 以 `cmdq_head` 穿过 descriptor 为准
3. completion 对软件的可见顺序是：
   - `payload`
   - `cmpq_tail`
   - `event`

这意味着现在讨论 `FUSED_STEP`、fault、compare surface 时，不再是“只有设计稿里这么说”，而是：

**代码、样例、测试和实验记录都已经围绕同一条 contract 在运转。**

### 2.3 sample/reference/toolchain bridge 族谱已经收口

当前实验面不是零散样例，而是一个比较清晰的族谱：

1. canonical sample
   - `external_p0`
   - `external_dyn_desc`
2. additive reference sample
   - `external_dyn_desc_ref`
   - `external_dyn_desc_fault_ref`
   - `external_dyn_desc_bad_policy_ref`
   - `external_dyn_desc_fault_rearm_ref`
   - `external_dyn_desc_fault_overwrite_chain_ref`
3. 对应 toolchain bridge
   - success path
   - fault path
   - bad policy path
   - clear-then-refault path
   - overwrite-chain path

这说明这条线已经不再只是“做出一个能跑的 demo”，而是开始具备：

1. 协议覆盖面
2. 故障生命周期覆盖面
3. builder 与 toolchain 双资产对照面

### 2.4 lab wrapper 已经成为实验承载入口

`/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py` 现在已经不只是一个薄脚本，而是这条实验线的入口层：

1. `list`
2. `build`
3. `validate`
4. `smoke`
5. `equiv`
6. `regress`
7. `nightly-sidecar`

当前 fresh evidence：

1. `python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v`
   - `Ran 46 tests ... OK`
2. `python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" list --json`
   - canonical sample set 可见
   - additive reference sample 可见

这意味着“实验入口在哪里、怎么跑、怎么注册和比对”这件事，已经不再依赖聊天记录和手工命令串。

## 3. Phase C 现在到底到了哪里

### 3.1 当前最重要的事实：`external_dyn_desc_ref` fresh PASS

截至本次整理时，最强的 full-stack 证据仍然是：

```bash
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family external_dyn_desc_ref
```

当前最新 dated summary：

- `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-26-external-dyn-desc-ref-equiv.json`

当前结果：

1. `status = PASS`
2. `gate_reasons = []`
3. baseline run：
   - `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260326-164029`
4. runtime run：
   - `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260326-164052`
5. runtime gate：
   - `summary = passed`

### 3.2 这个 PASS 具体说明了什么

这个 PASS 不是空泛的“好像跑通了”，它至少说明了下面几件事：

1. strict compare surface 没退化
2. baseline 既有 waiver 仍受控
3. runtime gate 没退化
4. provider/completion/fault snapshot 这层 bring-up 证据是可见的
5. transport visibility 已经不再存在 earlier visibility-gap 式的硬症状

runtime gate 当前能看到的直接证据：

1. `provider_bound_visible = 64`
2. `fused_step_completion_visible = 64`
3. `completion_visible = 64`
4. `completion_consumed_covers_visible = 64`
5. `fault_snapshot_consistent = passed`
6. `fault_snapshot_quiescent = passed`
7. `last_completion_status_clean = 0`

这说明这条链已经不再只是“控制面自己在转”，而是至少证明：

**runtime bridge 这边的 shadow provider、fused-step forward progress、completion visibility、completion consume、fault snapshot 语义都在实际 run 里站住了。**

### 3.3 这个 PASS 不说明什么

同样重要的是，要明确这个 PASS 还**不**代表什么：

1. 它不代表 trend surface 已经 bit-identical
2. 它不代表所有 family 都已经达到同样新鲜度
3. 它不代表 `riscv_snn` 可以随意继承 `snn` 的所有 datapath feature
4. 它不代表所有 legacy stimulus/source 边界都已经完全冻结完毕

当前 `compare.trend_overview` 仍明确告诉我们：

1. `status = passed`
2. `gate_level = info`
3. `aligned_fields = [step.global_steps_done]`
4. `diverged_fields` 仍包括：
   - `memory.memory_requests`
   - `memory.memory_bytes`
   - `gas.windows`
   - `gas.windows_done`
   - `snn_tx.spike_packets_total`
   - `snn_rx.spike_packets_total`
5. `visibility_gap_fields = []`

这说明现在的状态是：

**可见性缺口已经补上了，但研究型 drift 仍然存在，而且仍需要继续解释。**

## 4. 这轮新增收硬的边界：stimulus vs pure datapath

### 4.1 这件事为什么关键

`riscv_snn` 当前最容易走歪的一点，是为了让 runtime bridge 活起来，慢慢被误放大成“继承整个 `snn` workload 能力”。

这轮最重要的新增收硬，就是把下面两件事彻底分开：

1. **谁允许共享 SNN-style stimulus**
2. **谁允许继承纯 SNN datapath infrastructure**

当前冻结的 helper 语义是：

1. `workloadAllowsSnnStimulus()`
   - `snn = true`
   - `riscv_snn = true`
   - `stream/traffic/traffic_mem/tensor = false`
2. `workloadAllowsPureSnnDatapathFeatures()`
   - `snn = true`
   - 其它全部 `false`

### 4.2 已经被收硬的入口

当前已经明确挂到这层 contract 上的有两类 stimulus 入口：

1. `StepActivationSubsystem`
2. `ExternalSpikeInputSubsystem`

其中 `ExternalSpikeInputSubsystem` 这一轮新增了：

1. `ExternalSpikeInputSubsystem::Runtime.enabled`
2. `onSpike()` 中的 `if (!rt_.enabled) return/drop`
3. `MultiCorePE` 装配时：
   - `ex_rt.enabled = workloadAllowsSnnStimulus(cfg.workload_kind)`

这意味着：

1. `snn / riscv_snn`
   - 允许 external spike stimulus
2. `stream / traffic / traffic_mem / tensor`
   - 不再通过 legacy external 口子无条件碰到 SNN 注入路径

### 4.3 这轮刻意没动的入口

`syntheticEmitNeuronFire*()` 这轮没有去改，原因不是遗漏，而是判断上它现在已经被更窄的契约卡住：

1. 它依赖 `ISnnSpikeCommWorkload`
2. 这层接口当前本质上仍是纯 `snn` datapath contract
3. `riscv_snn` workload 目前并不实现它

所以这条链现在不是“riscv_snn 会误吃到的 stimulus 入口”，而更像是：

**还属于 `snn` 纯数据面 synthetic source 的一部分。**

这也正是当前实验线隔离最值得保持的一点：

**不要因为 `riscv_snn` 需要 stimulus，就顺手把所有 SNN source/path 一并开放。**

## 5. 目前仍然存在的真实缺口

### 5.1 full-stack freshness 的覆盖面还不够宽

虽然 `external_dyn_desc_ref` 已经 fresh PASS，但这还主要是一条 family 的强证据。

后续更稳的状态应该是：

1. success reference family
2. accepted fault family
3. bad policy family
4. clear-then-refault family
5. overwrite-chain family
6. 对应 toolchain bridge family

都逐步进入同一套 freshness gate，而不是只有一条线持续保鲜。

### 5.2 trend drift 仍需要继续解释

当前 `memory/gas/snn_txrx` 的 divergence 还没有被消掉。

这不一定表示有 bug，但至少表示：

1. shadow datapath 成本面和 baseline 成本面仍不完全一致
2. window accounting 仍可能存在不同的统计/时序归属口径
3. transport totals 虽然不再 visibility-gap，但仍有明显 delta

所以现在最危险的误判是：

**看到 PASS 就把 trend drift 当成“已经不重要”。**

更正确的说法应该是：

**它们现在不再阻塞 Phase C gate，但仍然是下一阶段的主要研究与收敛面。**

### 5.3 source taxonomy 还没完全写死

Stimulus/source 相关链路现在至少还有两类值得继续冻结：

1. `sendExternalSpike()` / legacy `SpikeEvent` 外发路径
2. `syntheticEmitNeuronFire*()` 与未来 control-plane harness 的边界

也就是说，虽然“能不能进来”已经开始收硬，但“从哪类 source 进来、属于哪一层语义”还没完全写成正式规范。

### 5.4 实验线虽然隔离得更好了，但仍然是实验线

当前所有进展都说明：

1. 这条线已经值得继续推进
2. 但仍然必须保持“窄 helper、窄 hook、窄 compare surface、窄 authority”的策略

尤其不能做的几件事是：

1. 把 `riscv_snn` 改回“更像 `snn`”
2. 把第二份 metadata authority 塞回 lab/tooling
3. 把 protocol drift 藏在 compare harness 例外里
4. 把主线 datapath feature 放松成“只要不是 stream 都能开”

## 6. 下一阶段最值得做什么

### 6.1 第一优先级：扩大 freshness gate 覆盖面

最有价值的不是再发明新 sample，而是把现有 family 更系统地纳入 fresh gate。

建议顺序：

1. `external_dyn_desc_fault_ref`
2. `external_dyn_desc_bad_policy_ref`
3. `external_dyn_desc_fault_rearm_ref`
4. `external_dyn_desc_fault_overwrite_chain_ref`
5. 对应 toolchain bridge

这样能把“成功路径 PASS”推进成“fault lifecycle 也稳定 PASS/受控”。

### 6.2 第二优先级：把 trend drift 解释面写硬

下一阶段不一定要马上把 drift 清零，但至少要把它们分层解释清楚：

1. 哪些属于 shadow datapath 成本差异
2. 哪些属于 accounting 口径差异
3. 哪些可能还是时序/语义问题

否则后面每次看到 delta，都还要重新人工分析一轮。

### 6.3 第三优先级：继续冻结 stimulus/source contract

建议继续沿着“更窄 helper”推进，而不是回退到粗分类：

1. 如需继续管 `sendExternalSpike()`，新增更窄 helper
2. 如需引入 `riscv_snn` synthetic source，新增明确属于 control-plane harness 的接口
3. 不要复用当前纯 `snn` datapath synthetic emit 路径

### 6.4 第四优先级：把“当前现状”变成后续接力入口

现在最怕的不是没有内容，而是内容分散：

1. README 有一部分
2. phase note 有一部分
3. TECH_PROGRESS 有一部分
4. dated reference 又有一部分

所以这份文档本身的作用，就是把当前最可信的状态先收成一个接力入口。

## 7. 给后续实现者的明确约束

后面继续推进时，建议默认遵守下面几条：

1. 如果只是为了让 `riscv_snn` 共享某类 stimulus，不要碰 `workloadAllowsPureSnnDatapathFeatures()`
2. 如果要开放新能力，优先新增更窄 helper，不要回退成 `!isNonSnnWorkloadKind()`
3. 如果要扩 compare surface，先确认不会引入第二份 authority
4. 如果要说“已经稳定”，必须给 fresh evidence：
   - `make ...`
   - `python3 -m unittest ...`
   - `riscv_snn_lab.py equiv ...`
5. 所有关键结论都应同时写回：
   - `riscv_snn_isa_lab/README.md`
   - `riscv_snn_isa_lab/notes/...`
   - `TECH_PROGRESS.md`

## 8. 当前总判断

如果现在要给这条线一句最准确的结论，浮浮酱会写成：

**`riscv_snn` 已经不再是“概念正确但实现未站稳”的状态，而是“control-plane 架构成立、实验入口可用、full-stack 至少有一条 PASS family、但 source/stimulus contract 与 trend drift 仍需继续收硬”的状态。**

这意味着：

1. 可以继续推进
2. 不应该回头推翻当前架构层判断
3. 下一阶段最值得投入的不是更大的功能面，而是更硬的边界与更宽的 freshness gate
