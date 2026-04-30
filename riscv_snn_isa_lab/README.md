# RISC-V SNN ISA Lab

> 路径：`/home/xgy/remote/riscv_snn_isa_lab`
>
> 状态：`riscv_snn runtime-bridge equivalence mainline`
>
> 当前 stable truth：`stable sidecar PASS / required families PASS / full equivalence PASS / compare + reference_compare + reference_program_compare 全部 attached 且 fresh / stable surface audit PASS`
>
> 最后整理：`2026-04-18`

本文只描述这条实验主线的当前最新状态，不描述历史版本演进。

## 1. 这条主线到底是什么

`riscv_snn_isa_lab` 不是默认 `snn` 路径的替代实现，也不是把 RISC-V 塞进现有 compute core 的重命名目录。它是一个严格隔离的实验主线，用来把 `RISC-V` 引入为 `SNN` 芯片的 `ISA-visible control plane`，同时继续复用现有 `SnnWorkload / backend` 作为高频事件执行平面。

当前唯一承认的主线是：

**`riscv_snn runtime-bridge equivalence mainline`**

这条主线的冻结分层如下：

| 平面 | 当前角色 | 不允许发生的误读 |
| --- | --- | --- |
| `control plane` | `RISC-V hart`、CSR、command/completion ring、fault lifecycle、`wfi`/interrupt | 不能把每条 incoming spike 回退成 software handler 主路径 |
| `data plane` | 现有 `SNN backend` 继续负责高频事件执行、神经元更新、突触/路由/本地状态 | 不能把 `riscv_snn` 伪装成新的 compute core |
| `sync plane` | barrier visible boundary、completion visibility、fault commit boundary | 不能让软件自定义 completion/fault 边界 |
| `bridge plane` | `runtime_bridge` 把 control-plane workload 绑定到 shadow `SnnWorkload` 并暴露 runtime surface | 不能引入第二份 metadata authority |

因此，这个目录承担的是：

1. 冻结 `riscv_snn` 的 machine-readable authority。
2. 提供 builder / toolchain / compare / stable surface 的统一 operator 命令面。
3. 把 mainline gate、observer、optional、supplementary surface 都收口到独立路径。
4. 在不污染默认 `snn` 主线的前提下，把这条实验线做成可持续验证的架构研究平台。

## 2. 严格隔离原则

这条实验线当前明确冻结以下隔离规则：

1. 不把 `riscv_snn` 塞回 `CoreShell`。
2. 不把 `riscv_snn` 伪装成新的 `ISnnComputeCore`。
3. 不让默认 `snn` gate 为实验 surface 背书。
4. 不引入第二份 metadata authority；所有 derived surface 只能从 authority + stable reference 派生。
5. 不让 incoming spike 成为软件逐条处理的主执行路径。
6. `architecture_model` 可以定义研究语义，但不能替代 stable mainline gate authority。

## 3. 目录分层

当前目录结构按“authority / model / execution / stable references / operator tooling”分层：

| 目录 | 当前职责 |
| --- | --- |
| `spec_authority/` | 单一真值源。冻结 ABI、mainline gate、runtime gate、supplementary surface、architecture model |
| `architecture_model/` | 程序语义、reference builder、runtime evidence projection 相关代码 |
| `tools/` | `riscv_snn_lab.py` 及其测试，负责生成、验证、compare、nightly、observer、audit |
| `references/` | stable top-level gate、derived surface、observer summary、history、audit、human-readable rollup |
| `specs/` | lab-local JSON spec，供 smoke / regress / matrix / toolchain bridge 使用 |
| `firmware_src/` | bare-metal toolchain bridge 源码入口 |
| `firmware/` | toolchain 构建产物与 ELF 资产 |
| `runs/` | builder / regress 相关 dated run 资产 |
| `runtime_runs/` | runtime bridge 运行产物 |
| `smoke_runs/` | lab 内快速 smoke / fault / overflow / barrier 产物 |
| `family_lanes/` | family 粒度的 lane/preset 定义 |
| `hart_ref/` | hart reference 相关实验入口 |
| `ci/` | 实验主线的持续验证胶水 |
| `notes/` | 非 authority 的研究笔记；不能替代 machine-readable truth |

## 4. 单一 Authority Chain

当前这条主线的 authority 不是一份大而全的文档，而是按职责拆开的单一 authority 链。

### 4.1 ABI / Control Plane Authority

| 文件 | 当前冻结内容 |
| --- | --- |
| `spec_authority/riscv_snn_accel_v1.json` | 当前共享导出 authority，冻结 `CSR` 窗口、event 可见面、ownership/doorbell 基本规则，以及 lab/export 面需要的最小 control-plane surface |
| `tools/export_riscv_snn_abi.py` | 从单一 authority 导出 ABI include / machine-readable projection |
| `tools/export_riscv_snn_control_plane_contract.py` | 导出当前 control-plane contract 的阅读版 |

这里要明确区分两层“当前生效”的 ABI 表面：

1. **共享导出表面**
   - 来源：`spec_authority/riscv_snn_accel_v1.json`
   - 作用：驱动 `.inc` 导出、toolchain bridge 共享 `CSR` 常量、lab 侧 contract 渲染
   - 当前被单元测试直接校验与 runtime header 的共享字段一致性
2. **live packed ABI 表面**
   - 来源：`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnAbi.h`
   - 作用：冻结 in-simulator 的 `CommandDescriptorV1` / `CompletionEntryV1` / `RxDebugEntryV1` 布局、`hdr0` 编码函数、status/fault 打包函数、event mask 语义
   - 当前由 compile-time `static_assert` 和 runtime/sample firmware/toolchain bridge 共同约束

也就是说，当前 README 在讲 “共享字段真值” 时锚定 `riscv_snn_accel_v1.json`，在讲 “真实生效的 packed ABI” 时锚定 `RiscvSnnAbi.h`。这不是引入第二份 metadata authority，而是当前实验线实际运行所依赖的代码级 ABI 固化面。

### 4.2 Mainline Gate Authority

`spec_authority/riscv_snn_mainline_gate_v1.json` 当前冻结：

1. `required_families`
2. `optional_groups`
3. `mainline_defaults.primary_optional_group`
4. `mainline_defaults.mainline_refresh_default_group`
5. `promotion_contract.<group>.multi_date_freshness_mode`

当前 blocking `required_families` 固定为 6 条：

1. `barrier_wfi_order_ref`
2. `external_dyn_desc_bad_policy_ref`
3. `external_dyn_desc_fault_overwrite_chain_ref`
4. `external_dyn_desc_fault_rearm_ref`
5. `external_dyn_desc_fault_ref`
6. `external_dyn_desc_ref`

当前 `optional_groups` 固定为：

| group | families | blocking | promotion_ready |
| --- | --- | --- | --- |
| `completion_overflow_optional` | `completion_queue_overflow_ref` | `false` | `true` |
| `queue_optional` | `queue_backpressure_ref`, `completion_queue_overflow_ref` | `false` | `true` |

当前默认组冻结为：

1. `primary_optional_group = completion_overflow_optional`
2. `mainline_refresh_default_group = completion_overflow_optional`

### 4.3 Runtime Gate Authority

`spec_authority/riscv_snn_runtime_gate_v1.json` 冻结 family 级行为语义，而不是把语义散落在 Python helper 里。每个 family 都固定：

1. `fault_mode`
2. `progress_mode`
3. `fault_lifecycle_mode`
4. `reference_program_profile`
5. `required_checks`
6. `allowed_completion_signature`
7. `allowed_fault_signature`

当前 runtime gate 的 `reason_ids` 固定为：

1. `runtime_bridge_provider_unbound`
2. `runtime_bridge_fused_step_completion_missing`
3. `runtime_bridge_completion_visibility_missing`
4. `runtime_bridge_completion_not_fully_consumed`
5. `runtime_bridge_expected_fault_missing`
6. `runtime_bridge_queue_fault_signature_mismatch`
7. `runtime_bridge_completion_queue_fault_signature_mismatch`
8. `runtime_bridge_fault_snapshot_missing`
9. `runtime_bridge_fault_snapshot_stale`
10. `runtime_bridge_last_completion_nonzero`

当前 runtime gate 的 `check_ids` 固定为：

1. `provider_bound_visible`
2. `fused_step_completion_visible`
3. `completion_visible`
4. `completion_consumed_covers_visible`
5. `fault_observed`
6. `queue_fault_signature`
7. `completion_queue_fault_signature`
8. `fault_snapshot_consistent`
9. `fault_snapshot_quiescent`
10. `last_completion_status_clean`

### 4.4 Supplementary Surface Authority

`spec_authority/riscv_snn_supplementary_surface_v1.json` 当前声明四条 non-blocking supplementary surface：

| surface | surface_kind | blocking | 角色 |
| --- | --- | --- | --- |
| `compare` | `compare_exec_mode_smoke` | `false` | `sst_dram_si` exec-mode smoke compare 的附属说明面 |
| `reference_compare` | `reference_compare_surface` | `false` | 单个 runtime summary 与 architecture reference 的附属对照面 |
| `reference_program_compare` | `reference_program_compare_surface` | `false` | authority-driven program trace 与 runtime/toolchain evidence 的附属对照面 |
| `stat_snapshot_family` | `stat_snapshot_family_surface` | `false` | `StatSnapshot` selector-family 覆盖度、freshness、stable current-state 的附属说明面 |

四条 surface 都要求 stable attach 字段完整存在：

1. `surface_kind`
2. `blocking`
3. `present`
4. `report_path`
5. `summary_md_path`
6. `current_mainline_status_path`
7. `gate_ok`
8. `latest_date`
9. `stale`
10. `freshness_mode`
11. `effective_all_dates_ok`

### 4.5 Architecture Model Authority

`spec_authority/riscv_snn_architecture_model_v1.json` 当前已经是独立的研究 authority，但它的边界也已经冻结：

1. `stage = architecture_research_platform`
2. `authority_domain = architecture_model_only`
3. `top_level_gate_role = none`
4. `does_not_replace_mainline_gate_authority = true`
5. `does_not_replace_runtime_gate_authority = true`
6. `does_not_replace_control_plane_abi_authority = true`

这意味着它可以定义 chip abstract machine、program semantics、runtime evidence projection，但不能取代 stable sidecar 的 blocking truth。

## 5. 当前芯片抽象机与控制面契约

### 5.1 Abstract Machine Taxonomy

`architecture_model` 当前冻结的实体分层包括：

1. `Hart`
2. `ProcessingElement`
3. `Cluster`
4. `DispatchUnit`
5. `EventEngine`
6. `NeuronStateStore`
7. `SynapseStore`
8. `IngressQueue`
9. `EgressQueue`
10. `Router`
11. `BarrierDomain`
12. `MemoryPort`

当前 layer taxonomy 固定为：

1. `isa_visible_control`
2. `dispatch`
3. `execution`
4. `memory`
5. `fabric`

当前 time taxonomy 固定为：

1. `architectural_time`
2. `microarchitectural_time`
3. `simulator_bookkeeping_time`

当前 counter taxonomy 固定为：

1. `correctness`
2. `execution_flow`
3. `memory`
4. `congestion`

### 5.2 FUSED_STEP 是当前唯一架构步原语

`architecture_model` 当前把 `FUSED_STEP` 冻结成研究主线的唯一架构步原语：

> `FUSED_STEP` retires only after architectural state commit, local outbound handover, and barrier visibility are complete.

当前 completion boundary 的四个必要条件是：

1. `architectural_state_committed`
2. `local_outbound_handover_complete`
3. `barrier_release_visible`
4. `no_higher_priority_fault_pending`

当前 fault boundary 的三个必要条件是：

1. `fault_classified`
2. `fault_csr_committed`
3. `completion_suppressed_or_replaced_by_fault`

当前 `fused_step_state_machine` 冻结状态为：

1. `Idle`
2. `Accepted`
3. `Decoded`
4. `ResourcesReserved`
5. `Executing`
6. `OutboundDraining`
7. `BarrierWaiting`
8. `Completed`
9. `Faulted`

### 5.3 当前 control-plane contract 与 live packed ABI

当前控制面需要同时从 `shared export surface` 和 `live packed ABI surface` 两个角度来理解。前者保证工具链共享常量与最小 contract，后者保证真实执行时的内存布局和编码函数。

#### 5.3.1 当前 CSR 窗口

当前 live `CSR` 窗口已经收敛在 12-bit RISC-V CSR window 内，并和 runtime header 对齐：

| CSR | 地址 | 当前角色 |
| --- | --- | --- |
| `CSR_MSNN_CMDQ_BASE` | `0xBC8` | command ring 基址 |
| `CSR_MSNN_CMDQ_SIZE` | `0xBC9` | command ring entry 数 |
| `CSR_MSNN_CMDQ_HEAD` | `0xBCA` | backend 已接受命令 head |
| `CSR_MSNN_CMDQ_TAIL` | `0xBCB` | software 提交 tail，唯一 architectural doorbell |
| `CSR_MSNN_CMPQ_BASE` | `0xBCC` | completion ring 基址 |
| `CSR_MSNN_CMPQ_SIZE` | `0xBCD` | completion ring entry 数 |
| `CSR_MSNN_CMPQ_HEAD` | `0xBCE` | software 已消费 completion head |
| `CSR_MSNN_CMPQ_TAIL` | `0xBCF` | backend 已发布 completion tail |
| `CSR_MSNN_RXQ_BASE` | `0xBD0` | RX debug ring 基址 |
| `CSR_MSNN_RXQ_SIZE` | `0xBD1` | RX debug ring entry 数 |
| `CSR_MSNN_RXQ_HEAD` | `0xBD2` | backend RX head |
| `CSR_MSNN_RXQ_TAIL` | `0xBD3` | software RX ack tail |
| `CSR_MSNN_EVENT_ENABLE` | `0xBD8` | 允许唤醒 `wfi` 的 event mask |
| `CSR_MSNN_EVENT_PENDING` | `0xBD9` | 当前 pending event，`W1C` |
| `CSR_MSNN_STEP` | `0xBDA` | step-visible architectural progress |
| `CSR_MSNN_FAULT` | `0xBDB` | 当前可见 fault snapshot |

当前 lab-side `.inc` 直接导出的就是这组共享 CSR 常量，因此 toolchain bridge 的 `csrr*` 指令与 runtime header 的共享窗口保持一致。

#### 5.3.2 当前 event bit 与 `wfi` 语义

当前 live runtime header 定义的 architectural event bit 是：

| bit | 名称 | 当前语义 |
| --- | --- | --- |
| `0` | `CmdComplete` | command/completion software-visible |
| `1` | `BarrierRelease` | barrier release 对 hart 可见 |
| `2` | `Fault` | fault snapshot 对 hart 可见 |
| `3` | `RxDebug` | RX debug surface 可读 |
| `4` | `PrefetchDone` | prefetch 结束 |
| `5` | `Debug` | debug/内部辅助事件 |

当前 `RiscvSnnHart` 的关键语义是：

1. `EVENT_PENDING` 是 `W1C`：
   - 写入值中的置位 bit 会被清掉
   - live mask 固定为 `0x3F`
2. `EVENT_ENABLE` 与 `EVENT_PENDING` 相与后决定 `wfi` 是否继续睡眠。
3. 若 `EVENT_ENABLE` 更新后已经存在 enabled pending event，hart 会立即退出等待态。
4. toolchain/reference firmware 当前最常见的序列是：
   - `csrrwi x0, CSR_MSNN_EVENT_ENABLE, 7`
   - 也就是启用 bit0/bit1/bit2，对应 `CmdComplete | BarrierRelease | Fault`
5. 软件通常用：
   - `csrrwi x0, CSR_MSNN_EVENT_PENDING, 7`
   统一 ack 这三类当前主线必须观察的事件

#### 5.3.3 当前 command descriptor live packed 布局

当前 live packed descriptor 是 `RiscvSnnAbi.h` 中的 `CommandDescriptorV1`，大小固定为 `64B`：

| offset | bytes | 字段 | 当前角色 |
| --- | --- | --- | --- |
| `0x00` | `8` | `hdr0` | header 位域：version/opcode/flags/completion/error/bytes |
| `0x08` | `8` | `token` | 软件提供的 command token |
| `0x10` | `8` | `arg0` | 操作数 0 |
| `0x18` | `8` | `arg1` | 操作数 1 |
| `0x20` | `8` | `src_addr` | 源地址或源对象 |
| `0x28` | `8` | `dst_addr` | 目标地址或目标对象 |
| `0x30` | `8` | `len_or_count` | 长度/计数/entry 数 |
| `0x38` | `8` | `dep_user` | 依赖链/用户字段 |

当前 `hdr0` 的 bit-level 编码固定为：

| bit range | 字段 |
| --- | --- |
| `[7:0]` | `version` |
| `[15:8]` | `opcode` |
| `[23:16]` | `flags` |
| `[31:24]` | `completion_policy` |
| `[39:32]` | `error_policy` |
| `[47:40]` | `desc_bytes` |
| `[63:48]` | reserved header bits |

当前 runtime helper 固定提供：

1. `descriptorVersion(hdr0)`
2. `descriptorOpcodeRaw(hdr0)`
3. `descriptorFlags(hdr0)`
4. `descriptorCompletionPolicy(hdr0)`
5. `descriptorErrorPolicy(hdr0)`
6. `descriptorBytes(hdr0)`
7. `descriptorReservedFlagBits(hdr0) = flags & 0xFC`
8. `descriptorReservedHeaderBits(hdr0) = (hdr0 >> 48) & 0xFFFF`

当前 `opcodeHasStrongCommitBoundary()` 只对 `FusedStep` 返回真，因此 `FUSED_STEP` 仍是当前唯一强提交边界命令。

#### 5.3.3.a 当前 `CommandOpcode` 逐值语义

当前 live ABI header 已冻结以下 opcode 编码面：

| 值 | 名称 | ABI 角色 | 当前 validate/helper 状态 |
| --- | --- | --- | --- |
| `0x00` | `Nop` | 最小空操作 | 当前 `validateSnnAccelCommand()` 接受 |
| `0x01` | `PrefetchW` | 预取/预热类控制命令 | 当前 `validateSnnAccelCommand()` 接受 |
| `0x02` | `StateLoad` | 未来状态载入路径预留 | 当前被判定为 `BadOpcode` |
| `0x03` | `StateStore` | 未来状态回写路径预留 | 当前被判定为 `BadOpcode` |
| `0x10` | `PhaseGather` | 未来 phase-split gather 预留 | 当前被判定为 `BadOpcode` |
| `0x11` | `PhaseApply` | 未来 phase-split apply 预留 | 当前被判定为 `BadOpcode` |
| `0x12` | `PhaseScatter` | 未来 phase-split scatter 预留 | 当前被判定为 `BadOpcode` |
| `0x20` | `FusedStep` | 当前主线唯一强提交边界命令 | 当前接受，且 `opcodeHasStrongCommitBoundary()` 为真 |
| `0x30` | `EgressCtrl` | 未来显式 egress control 预留 | 当前被判定为 `BadOpcode` |
| `0x31` | `RxDebugPop` | 未来 RX debug-only 命令 | `opcodeIsRxDebugOnly()` 为真，但当前 validate 仍拒绝 |
| `0x40` | `BarrierArrive` | 未来显式 barrier-arrive 命令 | 当前被判定为 `BadOpcode` |
| `0x50` | `StatSnapshot` | 统计快照/观测命令 | 当前 `validateSnnAccelCommand()` 接受 |

当前主线必须明确区分：

1. `ABI 已定义`
   - 枚举值已经冻结，便于未来阶段扩展
2. `runtime 当前接受`
   - 目前只接受 `Nop`、`PrefetchW`、`FusedStep`、`StatSnapshot`
3. `主线实际使用`
   - 当前 required/optional family 的成功路径本质上都围绕 `FusedStep`

因此，README 现在不把“ABI 里出现了这个 opcode”误写成“当前 runtime 已经支持了这个 opcode”。

#### 5.3.3.b 当前 `DescriptorFlagBit` 与 flags byte 语义

当前 flags byte 的定义分成“低两位 hint”与“高六位保留位”：

| bit | 名称 | 当前语义 |
| --- | --- | --- |
| `0` | `IrqHint` | 架构上定义为 hint bit；当前主线允许该位存在，但 runtime/backend 不依赖它做 correctness 分支 |
| `1` | `TraceHint` | 架构上定义为 hint bit；当前主线允许该位存在，但 runtime/backend 不依赖它做 correctness 分支 |
| `[7:2]` | reserved | 必须为 0；任意非零都会经 `descriptorReservedFlagBits()` 触发 `BadFlags` |

当前要点是：

1. `flags` byte 已有结构，不是完全空白。
2. 当前真正被 correctness gate 消费的是：
   - `descriptorReservedFlagBits(hdr0) = flags & 0xFC`
3. 也就是说：
   - bit0/bit1 目前只是 tolerated hints
   - bit2-bit7 是严格保留位，不能被 reference/toolchain/sample 擅自使用

#### 5.3.3.c 当前 `completion_policy` byte 语义

当前 `completion_policy` byte 已经进入 live header 和 queue decode surface，但 success path 只接受单一 canonical 值：

| 值 | 当前语义 | runtime 结果 |
| --- | --- | --- |
| `0x00` | canonical v1 completion policy | 当前 success path 唯一接受值 |
| `0x01` | 显式 policy probe / 负例语义 | 当前会触发 `BadPolicy`；`external_dyn_desc_bad_policy_ref` 用它冻结这条 fault 面 |
| `0x02..0xFF` | 预留 | 当前统一触发 `BadPolicy` |

当前 `BadPolicy` 的判定并不是“这个值语义不对”那么宽泛，而是明确体现在 `validateSnnAccelCommand()`：

1. 只要 `completion_policy != 0`
2. 或 `error_policy != 0`
3. 或 `descriptorReservedHeaderBits(hdr0) != 0`

就会直接生成：

1. `CompletionPrimaryStatus::BadPolicy`
2. `CompletionSeverity::FaultAfterAccept`
3. `aux = static_cast<uint32_t>(raw_header >> 32)`

所以 `external_dyn_desc_bad_policy_ref` 当前不是“某种软件策略失败”，而是冻结了“非零 policy byte / reserved high-header bits 直接 fault-after-accept”的最小协议事实。

#### 5.3.3.d 当前 `error_policy` byte 语义

当前 `error_policy` byte 的状态比 `completion_policy` 更保守：

| 值 | 当前语义 | runtime 结果 |
| --- | --- | --- |
| `0x00` | canonical v1 error policy | 当前 success path 唯一接受值 |
| `0x01..0xFF` | 预留 | 当前统一触发 `BadPolicy` |

也就是说：

1. 字段位置和编码已经冻结
2. queue decode / backend contract 已经把它带入 `SnnAccelCommand`
3. 但当前 runtime 还没有对非零 `error_policy` 做 finer-grained 行为分流
4. 在当前主线里，非零 `error_policy` 只是“非法 policy 配置”的一部分

#### 5.3.3.e 当前 `hdr0` canonical / rejected 组合

如果只看当前 success-path validator，那么一条 descriptor header 要被接受，至少必须满足：

1. `version == 1`
2. `desc_bytes == 64`
3. `completion_policy == 0`
4. `error_policy == 0`
5. `descriptorReservedHeaderBits(hdr0) == 0`
6. `descriptorReservedFlagBits(hdr0) == 0`
7. `opcode in { Nop, PrefetchW, FusedStep, StatSnapshot }`

当前所有 reference success/fault family 本质上都是围绕这条 canonical header 约束展开的；`bad_policy` 与 `bad_flags` 之类 family 则是针对其中某一条约束进行显式负例冻结。

#### 5.3.4 当前 completion / status / fault packed 布局

当前 live completion entry 是 `16B`：

| offset | bytes | 字段 | 当前角色 |
| --- | --- | --- | --- |
| `0x00` | `4` | `token` | 对应触发 completion 的 token |
| `0x04` | `4` | `status_code` | primary status + severity |
| `0x08` | `4` | `aux0` | 低 32 位 fault snapshot 或附加信息 |
| `0x0C` | `4` | `aux1` | 高 32 位 fault snapshot 或附加信息 |

当前 `status_code` 的打包规则固定为：

1. `[7:0] = CompletionPrimaryStatus`
2. `[15:8] = CompletionSeverity`
3. `[31:16]` 当前未作为独立主线语义使用

当前 `CompletionSeverity` 固定为：

1. `Success = 0`
2. `RejectedBeforeAccept = 1`
3. `FaultAfterAccept = 2`

当前 `CompletionPrimaryStatus` 固定覆盖：

1. descriptor 类故障：
   - `BadVersion`
   - `BadDescBytes`
   - `BadOpcode`
   - `BadFlags`
   - `BadAlignment`
   - `BadPolicy`
2. queue 类故障：
   - `CommandQueueOverflow`
   - `CompletionQueueOverflow`
3. phase/barrier 类故障：
   - `IllegalPhaseTransition`
   - `BarrierProtocolViolation`
4. 其他：
   - `MemorySemanticFault`
   - `BackendInternalError`

当前 visible `FAULT` CSR 的打包规则固定为：

| bit range | 字段 |
| --- | --- |
| `[7:0]` | `FaultCode` |
| `[15:8]` | `FaultSource` |
| `[31:16]` | `slot` |
| `[63:32]` | `aux` |

当前 `CompletionEntryV1.aux0/aux1` 组合后就是 completion 内携带的 64-bit fault snapshot：

1. `completionFaultSnapshot(aux0, aux1) = (aux1 << 32) | aux0`
2. `makeFaultCsrFromStatus(status_code, slot, aux)` 会把 `status_code` 投影成最终 `FAULT` CSR
3. runtime bridge/backend 退休 fault completion 时，最终 visible `msnnfault` 与 completion snapshot 保持同构

#### 5.3.4.a 当前 `StatSnapshot` selector / result surface

`StatSnapshot` 现在不再只是“validate 接受但没有稳定结果面”的占位 opcode；当前 live ABI 已经冻结了最小 selector/result surface：

1. selector 来源：
   - `command.arg0[31:0]`
   - helper：`makeStatSnapshotSelectorArg0()` / `statSnapshotSelectorRaw()`
2. result 返回：
   - success completion only
   - `aux0 = value[31:0]`
   - `aux1 = value[63:32]`
   - helper：`statSnapshotResultAux0()` / `statSnapshotResultAux1()` / `decodeStatSnapshotResult()`
3. event 约束：
   - 只走 `CmdComplete`
   - 不能冒充 `BarrierRelease`
4. 非法 selector：
   - 当前统一走 `BadPolicy`

当前冻结的 selector 只有 3 个：

| selector | 名称 | 当前语义 |
| --- | --- | --- |
| `0` | `AcceptedCommands` | 返回 backend 当前已接受命令数 |
| `1` | `CompletedCommands` | 返回“在当前 `StatSnapshot` completion 发布之前，已经架构可见退休”的成功完成命令数 |
| `2` | `ProviderBound` | 返回 `runtimeBridgeReady()` 的可见绑定位；`null backend = 0`，`runtime_bridge + ready provider = 1` |

当前这条 result surface 的技术意义是：

1. `StatSnapshot` 成为当前第一条真正落地的非 `FusedStep` 命令。
2. 它不改 `STEP`、不触发 barrier 语义，也不要求 data plane 进入高频事件路径。
3. 它给 sample firmware / bare-metal toolchain / backend 单测提供了一条统一的最小 control-path probe。
4. `CompletedCommands` 读的是 completion payload 内冻结的架构计数，不允许由软件在 poll 之后再拿 backend 内部瞬时计数回填。
5. `ProviderBound` 读的是 control-plane 可见 ready bit，不是“provider 对象存在”或“runtime bridge 已创建”这种更松的宿主侧状态。

#### 5.3.5 当前 queue ownership / ticket / full-empty 规则

当前 queue 不是以“指针物理位置”定义语义，而是以单调 ticket 计数定义：

1. `head == tail` 表示空
2. `tail - head >= entries` 表示满
3. `entries` 必须是 2 的幂
4. `slot = ticket & (entries - 1)`

当前 ownership 规则固定为：

1. command ring
   - software 唯一写 descriptor 与 `CMDQ_TAIL`
   - backend 唯一推进 `CMDQ_HEAD`
2. completion ring
   - backend 唯一写 completion payload 与 `CMPQ_TAIL`
   - software 唯一推进 `CMPQ_HEAD`
3. RX debug ring
   - backend 唯一推进 `RXQ_HEAD`
   - software 唯一推进 `RXQ_TAIL`

当前最关键的时序合同仍然是：

1. `CMDQ_TAIL` 是唯一 architectural doorbell
2. `accepted` 以 backend 推进 `CMDQ_HEAD` 为准
3. completion 可见顺序固定为：
   - completion payload 稳定
   - `CMPQ_TAIL` 推进
   - event pending 变为可见

#### 5.3.6 当前 fault clear / overwrite / rearm 规则

当前 `RiscvSnnHart::writeCsr()` 对 `FAULT` CSR 的语义是：

1. 如果写入值满足 `value[15:0] == 0`，则视为 fault-ack clear
2. clear 动作只清 visible `FAULT` snapshot
3. clear 动作会置位内部 `fault_ack_requested_`
4. `EV_FAULT` 不会因为 clear 自动消失，仍需要对 `EVENT_PENDING` 单独 `W1C`

因此当前 fault 生命周期合同固定为：

1. `msnnfault clear` 只清 visible snapshot，不顺手清 `EV_FAULT`
2. 新 accepted fault 可以覆盖当前 visible snapshot
3. 已退休 completion 里封存的 fault snapshot 不会被后续 clear 回写
4. `fault_rearm` 与 `fault_overwrite_chain` 都依赖这条清除/覆盖合同成立

#### 5.3.7 当前 firmware-observable 指令序列

当前 toolchain bridge 里的真实交互序列已经把上面的 contract 落到了 `csrr* / wfi` 指令流上。

`external_dyn_desc_fault_rearm_ref_toolchain` 当前关键序列是：

1. `csrrwi x0, CSR_MSNN_EVENT_ENABLE, 7`
2. 从 `CMDQ_BASE` / `CMPQ_BASE` 读取 ring 基址
3. 向 `CMDQ[0]` 写入第一条 64B descriptor
4. `csrrw x0, CSR_MSNN_CMDQ_TAIL, x1`
5. `wfi`
6. 读取 `CMDQ_HEAD == 1`、`CMPQ_TAIL == 1`
7. 读取 `CMPQ[0]` 的 `token/status/aux0/aux1`
8. 读取 `CSR_MSNN_FAULT`
9. `csrrw x0, CSR_MSNN_CMPQ_HEAD, x4`
10. `csrrwi x0, CSR_MSNN_EVENT_PENDING, 7`
11. `csrrw x0, CSR_MSNN_FAULT, x0`
12. 验证 `CSR_MSNN_FAULT == 0`
13. 再写第二条 descriptor 到 `CMDQ[1]`
14. 再次 `csrrw CSR_MSNN_CMDQ_TAIL`
15. 再次 `wfi`
16. 验证第二次 refault 的 completion/fault surface

`completion_queue_overflow_ref_toolchain` 当前关键序列是：

1. 连续写入两个 descriptor 到 `CMDQ[0]` 与 `CMDQ[1]`
2. 一次性把 `CMDQ_TAIL` 提到 `2`
3. 第一次 `wfi` 后只看到：
   - `CMPQ_TAIL == 1`
   - 第一条 visible completion 已出现
4. 软件先只 ack `EVENT_PENDING`
5. 第二次 `wfi` 后再看到：
   - `CMDQ_HEAD == 2`
   - `CMDQ_TAIL == 2`
   - `CMPQ_HEAD == 0`
   - `CMPQ_TAIL == 1`
   - `STEP == 2`
   - `FAULT == expected cmpq-full signature`

这条序列直接说明当前主线接受下面这个技术事实：

1. completion queue overflow 可以在一个 visible completion 尚未被软件消费时退休 fault
2. 这并不违反 contract，因为 family policy 明确允许这种 `completion_queue_fault_surface`

`stat_snapshot_ref_toolchain` 当前关键序列是：

1. `csrrwi x0, CSR_MSNN_EVENT_ENABLE, 7`
2. 从 `CMDQ_BASE` / `CMPQ_BASE` 读取 ring 基址
3. 向 `CMDQ[0]` 写入一条 `StatSnapshot` descriptor
4. `arg0[31:0] = AcceptedCommands selector`
5. `csrrw x0, CSR_MSNN_CMDQ_TAIL, x1`
6. `wfi`
7. 验证：
   - `CMPQ_TAIL == 1`
   - `CMPQ[0].token == 1`
   - `CMPQ[0].status_code == 0`
   - `CMPQ[0].aux0 == 1`
   - `CMPQ[0].aux1 == 0`
8. `csrrw x0, CSR_MSNN_CMPQ_HEAD, x4`
9. `csrrwi x0, CSR_MSNN_EVENT_PENDING, 7`

这条序列冻结了一个很重要的事实：

1. `StatSnapshot` 的 architectural boundary 就是 success completion 可见，不携带 barrier side effect。
2. `AcceptedCommands` selector 在第一条 accepted `StatSnapshot` 上稳定返回 `1`，因此可以作为当前 sample/toolchain/runtime 共用的最小 reference probe。

`stat_snapshot_completed_ref_toolchain` 当前关键序列是：

1. 第一条 descriptor 先发出 `AcceptedCommands`
2. 第二条 descriptor 再发出 `CompletedCommands`
3. 第一条 completion 退休后，第二条 `StatSnapshot` 才允许发布
4. 第二条 completion 返回：
   - `token == 2`
   - `status_code == 0`
   - `aux0 == 1`
   - `aux1 == 0`

这条序列冻结的是：

1. `CompletedCommands` 统计的是“已经在当前 completion 发布之前架构可见”的成功完成数。
2. 因而第二条 snapshot 看到的是第一条 snapshot 自己已经退休后的计数 `1`，而不是 backend poll 之后的更晚瞬时值。

`stat_snapshot_provider_bound_ref_toolchain` 当前关键序列是：

1. `runtime_bridge` backend 在 ready provider 已经绑定后发出一条 `ProviderBound`
2. `wfi` 唤醒后读取第一条 completion
3. 验证：
   - `token == 1`
   - `status_code == 0`
   - `aux0 == 1`
   - `aux1 == 0`

这条序列冻结的是：

1. `ProviderBound` 不是 data-plane 统计量，而是 control-plane ready bit 的可见投影。
2. `null backend` 必须返回 `0`，`runtime_bridge + ready provider` 必须返回 `1`，中间不引入第二份 host-side metadata authority。

## 6. Runtime Gate Family Semantics

当前 family 语义已经不是“文档解释”，而是 machine-readable authority。下面是当前主线最重要的 family 摘要：

| family | fault_mode | progress_mode | fault_lifecycle_mode | reference_program_profile |
| --- | --- | --- | --- | --- |
| `external_dyn_desc_ref` | `quiescent` | `forward_progress_expected` | `none` | `completed_single_step` |
| `external_dyn_desc_fault_ref` | `accepted_fault_required` | `forward_progress_expected` | `single_fault` | `accepted_fault_single_step` |
| `external_dyn_desc_bad_policy_ref` | `accepted_fault_required` | `no_committed_progress_allowed` | `single_fault` | `accepted_fault_single_step` |
| `external_dyn_desc_fault_rearm_ref` | `accepted_fault_required` | `fault_lifecycle_surface` | `clear_then_refault` | `clear_then_refault` |
| `external_dyn_desc_fault_overwrite_chain_ref` | `accepted_fault_required` | `fault_lifecycle_surface` | `overwrite_chain` | `overwrite_chain` |
| `barrier_wfi_order_ref` | `quiescent` | `forward_progress_expected` | `none` | `barrier_wait_then_completion` |
| `queue_backpressure_ref` | `accepted_fault_required` | `queue_backpressure_fault_surface` | `single_fault` | `accepted_fault_single_step` |
| `completion_queue_overflow_ref` | `accepted_fault_required` | `completion_queue_fault_surface` | `single_fault` | `accepted_fault_single_step` |

当前 family 级关键约束包括：

1. `external_dyn_desc_ref`
   - 必须满足 `fault_snapshot_quiescent`
   - 必须满足 `last_completion_status_clean`
   - `fault_count` 应维持为 0
2. `external_dyn_desc_fault_ref`
   - accepted-fault completion progress 计入 forward progress
   - 至少一条 accepted fault 必须保持架构可见
3. `external_dyn_desc_bad_policy_ref`
   - committed progress 可以被策略阻断
   - 但 accepted-fault completion progress 仍然可以满足 runtime bridge progress
4. `external_dyn_desc_fault_rearm_ref`
   - `msnnfault clear` 之后必须再次出现 accepted fault
   - clear-then-refault 生命周期必须架构可见
5. `external_dyn_desc_fault_overwrite_chain_ref`
   - 允许后续 accepted fault 覆盖当前 visible fault snapshot
   - 但每次 fault 都必须维持 fault snapshot 可见
6. `barrier_wfi_order_ref`
   - completion 只有在 barrier release visible 之后才可退休
   - `barrier_wait_visible` 是合法的中间架构状态
7. `queue_backpressure_ref`
   - fault signature 必须匹配冻结值 `fault_count * 0x0000000100000210`
8. `completion_queue_overflow_ref`
   - fault signature 必须匹配冻结值 `fault_count * 0x0000000100000211`
   - 允许存在一个软件可见 completion 尚未消费就被 `cmpq-full` fault 抢占退休

## 7. Program Semantics Bridge

### 7.1 Control Event Taxonomy

`architecture_model` 当前冻结了 6 个 program control event，reference program 只能由这些事件组合，不能再靠 family-local helper 自造语义：

1. `completion_visible`
2. `fault_snapshot_visible`
3. `msnnfault_clear`
4. `fault_snapshot_overwrite_visible`
5. `barrier_wait_visible`
6. `barrier_release_visible`

### 7.2 Program Semantic Profiles

当前 `program_semantic_profiles` 固定为 5 个 profile：

| profile | 当前语义 |
| --- | --- |
| `completed_single_step` | 单步成功完成，终态 `Completed` |
| `accepted_fault_single_step` | 单步 accepted-fault，终态 `Faulted` |
| `barrier_wait_then_completion` | 先显式 `BarrierWaiting`，再在 `barrier_release_visible` 后退休 completion |
| `clear_then_refault` | 先 fault，可见 clear 后再次 fault |
| `overwrite_chain` | 第二次 fault 覆盖前一次 visible fault snapshot |

这些 profile 当前通过 `reference_program_profile` 直接绑定 runtime gate family，不再允许 `riscv_snn_lab.py` 自己手写一套 family 语义。

## 8. Program Runtime Evidence Contract

`program_runtime_evidence_contract` 是当前 README 里最重要的新闭环之一。它规定 `reference_program_compare` 不再凭 request 伪造 runtime summary，而是从真实 `run_dir` 资产抽证据。

### 8.1 当前证据源类型

当前 evidence source kinds 固定为两类：

1. `runtime_bridge_run_dir`
2. `toolchain_run_dir`

### 8.2 每个 evidence source 必须具备的产物

当前要求的 run_dir artifacts 固定为：

1. `essential_summary_mesh.json`
2. `mesh_stats.csv`
3. `validation.log`

### 8.3 每个 evidence source 必须具备的 summary section

当前要求的 summary sections 固定为：

1. `model`
2. `step`
3. `contracts`

### 8.4 每个 evidence source 必须具备的 runtime stats

当前要求的 runtime stats 固定为：

1. `riscv_snn_submitted_commands`
2. `riscv_snn_accepted_commands`
3. `riscv_snn_completion_visible_count`
4. `riscv_snn_completion_consumed_count`
5. `riscv_snn_fused_step_completion_count`
6. `riscv_snn_fault_count`
7. `riscv_snn_last_completion_status`
8. `riscv_snn_last_fault_csr`
9. `riscv_snn_backend_runtime_bridge_provider_bound`

### 8.5 当前 control event projection 规则

当前 control event 到 runtime evidence 的投影规则也已经冻结：

| control_event | evidence_mode | 证据来源 |
| --- | --- | --- |
| `completion_visible` | `runtime_stat_nonzero` | `riscv_snn_completion_visible_count` |
| `fault_snapshot_visible` | `runtime_stat_nonzero` | `riscv_snn_fault_count` |
| `msnnfault_clear` | `profile_control_event` | 由 reference program profile 投影 |
| `fault_snapshot_overwrite_visible` | `profile_control_event` | 由 reference program profile 投影 |
| `barrier_wait_visible` | `profile_control_event` | 由 reference program profile 投影 |
| `barrier_release_visible` | `profile_control_event` | 由 reference program profile 投影 |

这意味着：

1. completion / fault 是否真正发生，必须来自真实 runtime stat。
2. clear / overwrite / barrier 这些“控制面可见事件序列”目前由 authority-backed profile 投影。
3. `reference_program_compare` 的 summary 会明确记录哪些事件来自 direct runtime evidence，哪些来自 authority projection。

## 9. Reference Compare 与 Reference Program Compare

### 9.1 `reference_compare`

`reference_compare` 是单个 runtime summary 和 architecture model 的直接对照面。

当前 stable surface：

1. `references/reference-compare-nightly-report.json`
2. `references/reference-compare-nightly-summary.md`
3. `references/reference-compare-current-status.md`

当前 stable truth：

1. `gate_ok = true`
2. `status = allowed_divergence`
3. `latest_date = 2026-04-18`
4. `freshness_mode = reference_compare_latest_only`
5. 当前唯一允许的 divergence point 是 `queue_occupancy`
6. `terminal_state_match = true`
7. `memory_domain_alignment = true`
8. `fabric_stage_alignment = true`

### 9.2 `reference_program_compare`

`reference_program_compare` 是当前主线里更重要的 supplementary surface。它把下面五层内容串成一个闭环：

1. `runtime_gate family`
2. `reference_program_profile`
3. `program_runtime_evidence_contract`
4. `runtime_bridge/toolchain run_dir evidence`
5. `dated family compare + matrix surface`

当前 `run_reference_program_compare_family(...)` 的核心行为是：

1. 从 family 的 `reference_program_profile` 构建 authority-backed reference trace。
2. 从最新 dated equivalence surface 提取 `runtime_bridge_run_dir`。
3. 如果该 family 存在对应的 toolchain program，且它属于 `matrix_programs("toolchain")`，再从最新 toolchain regress matrix 提取 `toolchain_run_dir`。
4. 对每个 source 读取 `essential_summary_mesh.json`、`mesh_stats.csv`、`validation.log`。
5. 依 evidence contract 生成 `runtime_program_summary`。
6. 逐步比较 terminal states、completion step、fault step、barrier wait step、overwrite/clear 生命周期、memory domain、fabric stage、divergence points。
7. 把所有 source 合并成 `evidence_rows`，而不是只留一个“结果”。

当前要特别注意：

1. required 6 条 family 大多已经具备 `runtime_bridge + toolchain` 双证据。
2. `completion_queue_overflow_ref` 与 `queue_backpressure_ref` 当前只有 runtime evidence，这是预期行为，因为它们不属于当前 official `toolchain` surface 的必备 family。
3. 4 条 `StatSnapshot` family 现在都已经具备 `runtime manifest + toolchain manifest` 双证据：
   - `stat_snapshot_ref`
   - `stat_snapshot_completed_ref`
   - `stat_snapshot_provider_bound_ref`
   - `stat_snapshot_bad_selector_ref`
4. `stat_snapshot_bad_selector_ref` 的 runtime-side ELF / smoke manifest 已补齐，所以它不再只是“toolchain/source/spec 就绪”，而是真正进入了 program-level compare evidence 闭环。
5. `reference_program_compare` 仍然是 `supplementary-only`，不会变成 blocking gate。

### 9.3 当前 `reference_program_compare` stable truth

当前 stable surface：

1. `references/reference-program-compare-nightly-report.json`
2. `references/reference-program-compare-nightly-summary.md`
3. `references/reference-program-compare-current-status.md`

当前 stable truth：

1. `status = pass`
2. `gate_ok = true`
3. `count = 12`
4. `group = all`
5. `latest_date = 2026-04-18`
6. `freshness_mode = reference_program_compare_latest_only`
7. `effective_all_dates_ok = true`

当前 12 条 family 的 matrix 状态为：

| family | status |
| --- | --- |
| `barrier_wfi_order_ref` | `allowed_divergence` |
| `completion_queue_overflow_ref` | `aligned` |
| `external_dyn_desc_bad_policy_ref` | `aligned` |
| `external_dyn_desc_fault_overwrite_chain_ref` | `allowed_divergence` |
| `external_dyn_desc_fault_rearm_ref` | `allowed_divergence` |
| `external_dyn_desc_fault_ref` | `aligned` |
| `external_dyn_desc_ref` | `aligned` |
| `queue_backpressure_ref` | `aligned` |
| `stat_snapshot_bad_selector_ref` | `aligned` |
| `stat_snapshot_completed_ref` | `aligned` |
| `stat_snapshot_provider_bound_ref` | `aligned` |
| `stat_snapshot_ref` | `aligned` |

这里的 `allowed_divergence` 不是失败，而是 authority 明确允许的差异点在 gate 内被接受。

## 10. Stable Sidecar / Observer / Audit Chain

### 10.1 唯一 blocking gate

当前唯一 top-level blocking gate 是：

`references/nightly-sidecar-report.json`

它当前冻结的角色是：

1. `artifact_role = stable_top_level_gate`
2. `authority_scope = experimental_gate_authority`
3. `gate_ok = true`
4. `actual_count = 6`
5. `required_families` 就是 mainline gate authority 的 6 条 required family

同一个 sidecar 里当前还挂着：

1. `equivalence.all_ok = true`
2. `equivalence.count = 6`
3. `full_equivalence.all_ok = true`
4. `full_equivalence.count = 8`
5. `drift_families = []`

### 10.2 当前 derived surfaces

下面这些都是真实可读 surface，但都不是新的 top-level gate：

| surface | 路径 | 当前角色 |
| --- | --- | --- |
| observer summary | `references/nightly-sidecar-observer-summary.json` | 汇总 stable gate、optional rollup、supplementary health |
| research report | `references/riscv-snn-research-report.json` | 研究视角摘要 |
| adequacy validation | `references/observer-adequacy-validation.json` | observer coverage / fail-recovery 充分性检查 |
| current status | `references/current-mainline-status.md` | 人类读取入口 |
| sidecar summary | `references/nightly-sidecar-summary.md` | stable sidecar 的 markdown 摘要 |
| stable audit | `references/stable-surface-refresh-audit.json` | 检查 derived surface 是否和 stable sidecar/authority 对齐 |
| supplementary history | `references/supplementary-surface-history.json` | compare / reference_compare / reference_program_compare / stat_snapshot_family 的稳定 history 汇总 |

当前 `supplementary surface` 的第一阶段框架化也已经落地在：

`riscv_snn_isa_lab/tools/supplementary_surface_contract.py`

它当前只统一三段 lab 内部 contract 骨架：

1. latest-only history payload 生成
2. stable report -> normalized surface payload 投影
3. stable sidecar 的 supplementary attach / merge

并且现在已经继续统一了第四段：

4. summary markdown / current status markdown 的渲染骨架

这意味着当前四条 surface 已经开始共用同一套最小 contract helper，但仍然保持：

1. source loader 继续各自独立
2. surface-specific augmentation 继续各自独立
3. 没有新增第二份 authority
4. 也没有把 default `snn` 主线拉进来耦合

### 10.3 当前 observer / audit truth

当前 `nightly-sidecar-observer-summary.json` 明确显示：

1. `gate_ok = true`
2. `required_families` 仍然是 6 条 required family
3. `full_equivalence`
   - `history_contract = observer_sample_sequence_v1`
   - `refresh_mode`、`effective_entry_count`、`effective_all_dates_ok` 现在直接投影 observer history 的有效 freshness 边界
4. `completion_overflow_optional`
   - `all_ok = true`
   - `effective_all_dates_ok = true`
   - `latest_date = 2026-04-04`
   - `promotion_ready = true`
5. `queue_optional`
   - `all_ok = true`
   - `effective_all_dates_ok = true`
   - `latest_date = 2026-04-04`
   - `promotion_ready = true`
6. supplementary surfaces 四条都 present / gate_ok / fresh
7. `stat_snapshot_family`
   - `selector_count = 3`
   - `covered_selector_count = 3`
   - `latest_date = 2026-04-18`
   - `freshness_mode = latest_refresh_only`

当前 `supplementary-surface-history.json` 明确显示：

1. `surface_count = 4`
2. `compare` 已 fresh，`latest_date = 2026-04-07`
3. `reference_compare` 已 fresh，`latest_date = 2026-04-18`
4. `reference_program_compare` 已 fresh，`latest_date = 2026-04-18`
5. `stat_snapshot_family` 已 fresh，`latest_date = 2026-04-18`

当前 `stable-surface-refresh-audit.json` 明确显示：

1. `all_ok = true`
2. `current_mainline_status.ok = true`
3. `observer_summary.ok = true`
4. `observer_adequacy_validation.ok = true`
5. `research_report.ok = true`
6. `supplementary_surfaces.compare.ok = true`
7. `supplementary_surfaces.reference_compare.ok = true`
8. `supplementary_surfaces.reference_program_compare.ok = true`
9. `supplementary_surfaces.reference_program_compare_chain.ok = true`
10. `supplementary_surfaces.stat_snapshot_family.ok = true`
11. `supplementary_surfaces.stat_snapshot_family_chain.ok = true`

## 11. 当前 stable truth 快照

如果只想最快判断“这条主线现在有没有站稳”，当前应读取下面这些稳定事实：

| 项目 | 当前值 |
| --- | --- |
| stable top-level gate | `references/nightly-sidecar-report.json` |
| `gate_ok` | `true` |
| required family count | `6` |
| full equivalence count | `8` |
| `reference_compare.status` | `allowed_divergence` |
| `reference_compare.gate_ok` | `true` |
| `reference_compare.latest_date` | `2026-04-18` |
| `reference_program_compare.status` | `pass` |
| `reference_program_compare.gate_ok` | `true` |
| `reference_program_compare.latest_date` | `2026-04-18` |
| `completion_overflow_optional.promotion_ready` | `true` |
| `queue_optional.promotion_ready` | `true` |
| `stable_surface_refresh_audit.all_ok` | `true` |

## 12. 当前主线的技术全流程

这一节不再按“脚本怎么跑”组织，而是按“技术事实如何一路收口成 stable truth”组织。主线真正的闭环是：

**authority -> control-plane execution -> runtime surface -> evidence projection -> reference compare -> stable sidecar -> observer/audit**

### 12.1 从 family authority 到一条可执行程序语义

一条 family 进入主线时，当前必须先被 authority 明确定义，而不是先写脚本再补解释。完整起点是：

1. `riscv_snn_mainline_gate_v1.json`
   - 决定它是 `required` 还是 `optional`
   - 决定它是否影响 blocking gate
2. `riscv_snn_runtime_gate_v1.json`
   - 决定 `fault_mode`
   - 决定 `progress_mode`
   - 决定 `fault_lifecycle_mode`
   - 决定 `required_checks`
   - 决定 `reference_program_profile`
3. `riscv_snn_architecture_model_v1.json`
   - 决定这条 family 对应哪一个 `program_semantic_profile`
   - 决定 reference trace 允许出现哪些 control event
   - 决定 evidence 应该如何从 runtime artifact 投影出来

因此，family 不是“测试名字”，而是三层 authority 共同定义的一个冻结行为单元。

### 12.2 从软件提交到 backend 接受

当前 control-plane 执行入口严格建立在 `ControlMemory` 上，软件可见对象只有：

1. CSR
2. command ring
3. completion ring
4. visible fault snapshot
5. descriptor header

一次标准提交的当前路径是：

1. 软件按 `64B CommandDescriptorV1` 布局写满一个 slot：
   - `hdr0`
   - `token`
   - `arg0/arg1`
   - `src_addr/dst_addr`
   - `len_or_count`
   - `dep_user`
2. slot 的定位不是“数组指针”而是 `ticket -> slot = ticket & (entries - 1)`。
3. 软件完成 descriptor 写入后，推进 `msnncmdq_tail`；这是唯一 architectural doorbell。
4. backend 观察到 tail 后，先从 `cmd_head` 对应 ticket 解码 `hdr0`，再推进 `cmdq_head` 并宣布这条命令 `accepted`。
5. `runtime_bridge provider bound` 必须在 runtime stat 中可见，否则 family 直接失去 PASS 资格。
6. 一旦命令被 accepted，就进入 `FUSED_STEP` 的状态机边界，而不是进入一个未定义的“软件阶段”。
7. 当前 success-path validator 还会同步检查：
   - `version == 1`
   - `desc_bytes == 64`
   - `completion_policy == 0`
   - `error_policy == 0`
   - `reserved header/flag bits == 0`
   - `opcode` 落在当前允收集合内

这里最关键的冻结点是：

1. 软件写 tail 只代表“命令 eventually visible”。
2. `accepted` 必须以 backend 对 ring 的拥有关系变化为准。
3. 主线不允许软件直接主导 data plane 的 spike 执行。
4. `command queue full` 的判定不是看 slot 内容，而是 `tail - head >= entries`。
5. toolchain/reference firmware 当前真实提交指令就是：
   - `csrrw x0, CSR_MSNN_CMDQ_TAIL, <new_tail>`
   - 然后 `wfi`

### 12.3 从 `FUSED_STEP` 到 completion / fault commit

当前主线里，`FUSED_STEP` 不是一个泛泛的“step 调用”，而是完整的架构步原语。它在技术上把控制面和 backend 绑定到一条统一的退休边界上。

成功退休时，当前完整链路是：

1. family 被 backend 接受
2. 进入 `Accepted -> Decoded -> ResourcesReserved -> Executing`
3. 局部 outbound 进入 `OutboundDraining`
4. 若 barrier 尚未可见，则进入 `BarrierWaiting`
5. 只有当
   - `architectural_state_committed`
   - `local_outbound_handover_complete`
   - `barrier_release_visible`
   - `no_higher_priority_fault_pending`
   同时成立，才允许 completion commit
6. completion 写回顺序固定为
   - `CompletionEntryV1.token/status_code/aux0/aux1` payload 稳定
   - `CMPQ_TAIL` 推进
   - 对应 event bit 进入 `EVENT_PENDING`
7. 一旦 `EVENT_ENABLE & EVENT_PENDING != 0`，正在 `wfi` 的 hart 会被唤醒

fault 退休时，当前完整链路是：

1. fault 被分类
2. `status_code` 被映射成 `FaultCode + FaultSource`
3. `slot` 与 `aux` 被打包成 visible `FAULT` CSR
4. 当前 `FUSED_STEP` completion 被抑制或被 fault 语义取代
5. 如果 family 允许 overwrite/rearm，则 fault lifecycle 必须仍然满足 runtime gate authority 的冻结规则
6. software clear 的两步当前必须分开：
   - `csrrw x0, CSR_MSNN_FAULT, x0`
   - `csrrwi x0, CSR_MSNN_EVENT_PENDING, <mask>`

这部分的本质是：

1. completion boundary 是 architecture authority 定义的。
2. fault boundary 也是 architecture authority 定义的。
3. 软件只消费结果，不重新定义边界。

### 12.4 从 runtime surface 到 dated equivalence

每次真实运行后，主线不会直接看“程序跑没跑完”，而是看 `run_dir` 是否暴露了可审计的 runtime surface。当前一个合格的 evidence source 必须具备：

1. `essential_summary_mesh.json`
2. `mesh_stats.csv`
3. `validation.log`

并且必须包含：

1. `model`
2. `step`
3. `contracts`

以及一组冻结的 runtime stats：

1. `riscv_snn_submitted_commands`
2. `riscv_snn_accepted_commands`
3. `riscv_snn_completion_visible_count`
4. `riscv_snn_completion_consumed_count`
5. `riscv_snn_fused_step_completion_count`
6. `riscv_snn_fault_count`
7. `riscv_snn_last_completion_status`
8. `riscv_snn_last_fault_csr`
9. `riscv_snn_backend_runtime_bridge_provider_bound`

runtime gate 在这一层真正做的事情是：

1. 检查 provider binding 是否出现
2. 检查 fused-step progress 是否出现
3. 检查 completion 是否可见、是否被消费覆盖
4. 检查 `status_code`、`aux0/aux1` 与 visible `FAULT` snapshot 是否形成一致 surface
5. 检查 queue/completion overflow signature 是否匹配冻结值
6. 检查 quiescent family 是否在无 fault、status 0 的条件下退休

通过这些检查后，才形成 dated `equiv` family summary，再进一步形成 dated `equiv-matrix`。

换句话说，当前 dated equivalence 不是“程序最终通过”，而是下面三件事同时成立：

1. queue ownership/head-tail 语义成立
2. completion/fault packed surface 语义成立
3. runtime stats 与 family policy 的进展/故障预期成立

### 12.5 builder 路径与 toolchain 路径如何并存

当前主线不是只看 builder 路径，也不是只看 bare-metal toolchain。它们在技术上承担不同职责：

1. builder/runtime-bridge 路径
   - 负责主线 family 的 runtime equivalence
   - 直接连接 `runtime_bridge_run_dir`
   - 是 mainline gate 的基础来源
2. toolchain bridge 路径
   - 负责用真实 bare-metal 程序重放 control-plane contract
   - 直接连接 `toolchain_run_dir`
   - 当前主要进入 `reference_program_compare` 与 toolchain audit，而不是单独生成第二份 authority

当前一条 family 进入 toolchain evidence 的条件是：

1. 存在对应的 `<family>_toolchain` 程序
2. 它属于 `matrix_programs("toolchain")`
3. 最新 toolchain regress matrix 中存在该 family 的 `run_dir`

否则这条 family 在 `reference_program_compare` 中就只保留 runtime evidence。当前：

1. required 6 条 family 大多已经进入双证据闭环
2. `completion_queue_overflow_ref`
3. `queue_backpressure_ref`

仍然只保留 runtime evidence，这属于当前 surface 设计的一部分，不是数据缺失。

### 12.6 从 runtime evidence 到 authority-driven reference program

`reference_program_compare` 的真正价值，不是再做一次“结果汇总”，而是把 runtime surface 投影到 authority-backed program semantics 上。

当前流程严格是：

1. 读取 family 的 `reference_program_profile`
2. 用 `program_semantic_profiles` 构造 reference trace
3. 从 `runtime_bridge_run_dir` 和可用的 `toolchain_run_dir` 抽取 evidence
4. 按 `program_runtime_evidence_contract` 生成 `runtime_program_summary`
5. 对比：
   - `terminal_states`
   - `completion_step_indices`
   - `fault_step_indices`
   - `barrier_wait_step_indices`
   - `clear_fault_before_step_indices`
   - `overwrite_fault_step_indices`
   - `fault_snapshot_sequence`
   - `memory_domains`
   - `fabric_stages`
   - `divergence_points`
6. 把每个来源都保存在 `evidence_rows` 中
7. family compare surface 再汇总成 matrix surface

这意味着当前主线已经不接受下面这些做法：

1. 用 request 参数临时拼一份 runtime summary
2. 用 family-local Python 逻辑替代 `reference_program_profile`
3. 只记录最终 PASS/FAIL，不记录 evidence source

### 12.7 从 supplementary compare 到 stable sidecar

当 equivalence / reference compare / reference program compare 都已经形成 dated surface 后，主线才会把这些结果汇总到 stable sidecar 体系。

当前收口规则是：

1. `nightly-sidecar-report.json`
   - 唯一 top-level blocking gate
   - 负责 required family pass/fail 与 attach supplementary surface
2. `nightly-sidecar-observer-summary.json`
   - 不产生新真值
   - 只汇总 gate、optional freshness、supplementary freshness、observer history
3. `supplementary-surface-history.json`
   - 只维护四条 supplementary surface 的稳定 history
4. `stable-surface-refresh-audit.json`
   - 检查 stable sidecar、observer、summary markdown、current-mainline-status、supplementary chain 是否全部一致

当前 attach 到 stable sidecar 的四条 supplementary surface 也都有固定边界：

1. `compare`
   - 来自 `sst_dram_si` 的 exec-mode smoke compare
2. `reference_compare`
   - 来自单 runtime summary 与 architecture reference 的对照
3. `reference_program_compare`
   - 来自 authority-driven 程序语义与 runtime/toolchain evidence 的对照
4. `stat_snapshot_family`
   - 来自 `StatSnapshot` selector-family 的覆盖度、freshness 与 stable current-state 对齐

它们都只能是 `non-blocking supplementary surface`，不能越权成为新的 gate。

当前 `observer-fail-recovery` 也已经收成正式闭环，而不再依赖人工先后编排：

1. 先按 authority 导出的 optional freshness mode 刷新目标 optional history。
2. 如果 authority 期望的是 `compact_latest_recovery`，同一轮闭环会把 observer history 也同步压到同一个 recovery 边界。
3. 然后才刷新 observer summary、research/current-mainline、stable-surface audit。
4. fail/recovery summary 会同时写出两组 freshness 结果：
   - `group_history_refresh_mode` / `group_history_effective_entry_count` / `group_history_effective_all_dates_ok`
   - `observer_history_refresh_mode` / `observer_history_effective_entry_count` / `observer_history_effective_all_dates_ok`

也就是说，当前 optional surface freshness 和 observer fail/recovery history 已经共享同一套 compact decision，而不是各自独立漂移。

### 12.8 从 stable truth 到人类可读状态

主线最后一步才是人类可读 surface。当前这些文件都只是 stable truth 的投影：

1. `references/current-mainline-status.md`
2. `references/nightly-sidecar-summary.md`
3. `references/reference-compare-current-status.md`
4. `references/reference-program-compare-current-status.md`
5. `references/stat-snapshot-family-current-status.md`

这些文件的角色是：

1. 帮人快速读取当前状态
2. 帮 operator 快速定位 stable report 路径
3. 帮 observer/audit 检查路径链是否完整

其中 `references/current-mainline-status.md` 的 `## Observer Closure` 当前已经固定投影下面这组 observer history 字段：

1. `entry_count`
2. `first_fail_date`
3. `latest_recovered_date`
4. `all_ok_latest`
5. `history_contract`
6. `refresh_mode`
7. `effective_entry_count`
8. `effective_all_dates_ok`

但它们本身都不是 authority，也不是 gate。

## 13. 命令面速览

命令面只需要记住最少一组入口即可：

| 目标 | 关键子命令 |
| --- | --- |
| 解释 authority | `explain-mainline`、`explain-runtime-gate`、`explain-program-semantics` |
| 生成等价性 | `equiv`、`equiv-matrix` |
| 刷新 compare surface | `reference-compare-refresh`、`reference-program-compare-refresh` |
| 刷新 stable truth | `observer-refresh`、`mainline-refresh`、`observer-history-compact-refresh`、`export-mainline-status` |
| 审计闭环 | `stable-surface-audit`、`observer-adequacy-validate` |

其中：

1. `observer-history-compact-refresh`
   - 是 observer history 的明确 compact 入口
   - 固定执行 `latest recovery boundary` 收口
   - 适合减少同日多样本管理成本
2. `observer-fail-recovery`
   - 会先刷新 optional history
   - 再把同一轮 compact 决策传递到 observer history / mainline surface
   - 输出 summary 现在会同时暴露 optional history 与 observer history 的 effective freshness 标记
   - 最后再跑 stable surface audit

统一入口保持不变：

```bash
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" <subcommand> ...
```

## 14. 当前这份 README 应该如何使用

推荐阅读顺序现在也应该按技术闭环走，而不是按脚本列表走：

1. 先读 `spec_authority/riscv_snn_mainline_gate_v1.json` 与 `spec_authority/riscv_snn_runtime_gate_v1.json`，确认 family 与 gate 语义。
2. 再读 `spec_authority/riscv_snn_architecture_model_v1.json`，确认 `FUSED_STEP`、program profile、evidence contract。
3. 再读 `references/reference-program-compare-nightly-report.json`，确认 authority-driven 程序语义是否真的被 runtime/toolchain evidence 支撑。
4. 再读 `references/nightly-sidecar-report.json`，确认 blocking gate 与 supplementary attach 是否一致。
5. 最后读 `references/stable-surface-refresh-audit.json` 与 `references/current-mainline-status.md`，确认整条 stable chain 没有分叉。

只要这五层仍然一致，这条实验主线就仍然处于“可持续验证、可持续扩展、可持续做架构研究”的稳定状态。
