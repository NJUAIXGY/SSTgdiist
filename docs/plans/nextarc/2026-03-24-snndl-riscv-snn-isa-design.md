# SnnDL `riscv_snn` ISA 级演进设计与 ActiveN 启发整理

Date: 2026-03-24
Owner: Fufu
Status: Review-aligned v1.1 spec draft before implementation

## 1. 文档目的

这份文档回答五个问题：

1. 现有 `SnnDL` 从 cycle-level SNN 仿真走向 ISA-level 建模，最合适的主线是什么。
2. 如果指令集选择 `RISC-V`，应该把它放在当前架构的哪一层。
3. `riscv_snn` 这条线的完整硬件/软件/仿真接口应该怎么定义。
4. 仓库内实际需要修改哪些模块、采用什么阶段化实施路线。
5. 从论文 `ActiveN: A Scalable and Flexibly-Programmable Event-Driven Neuromorphic Processor` 中，我们能吸收哪些设计思想，又有哪些地方不应直接照搬。

本文是设计文档，不是实现记录。目标是把后续实现需要冻结的关键接口先讲清楚，避免一开始就把 `RISC-V` 强行塞进错误的抽象层。

## 2. 当前仓库边界与真实接入点

这条设计必须严格基于当前代码事实，而不是抽象想象。

### 2.1 `CoreShell` 的边界已经很清楚

`CoreShell` 在当前仓库中的定位是平台壳，而不是业务壳。它负责：

- 时钟驱动
- packet 递送
- runtime 绑定
- statistics 汇聚

它不应该承载：

- SNN 业务状态机
- 神经元/突触语义
- 具体 ISA 语义

直接证据见：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/README.md`

因此，把 `RISC-V hart` 直接做进 `CoreShell` 会破坏当前已经建立好的平台/业务分层。

### 2.2 `workload` 是当前系统的正确扩展面

当前 `CoreWorkloadFactory` 已经支持：

- `snn`
- `stream`
- `tensor`
- `traffic`
- `traffic_mem`

直接证据见：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/CoreWorkloadFactory.cc`

这意味着，新增 `workload_impl=riscv_snn` 是最自然的系统演进方式。

### 2.3 `ISnnComputeCore` 不是 CPU 抽象

`ISnnComputeCore` 的接口是：

- `onStageBeginGather`
- `onStageBeginApply`
- `onStageBeginScatter`
- `applySynapticDelta`
- `drainOutputs`
- `readNeuronState`
- `writeNeuronState`

这组接口清楚地说明它是：

`SNN execution datapath abstraction`

而不是：

`general-purpose instruction execution abstraction`

因此，`RISC-V` 不应被实现成新的 `compute_core_impl`，而应该作为工作负载的控制面存在，再去驱动现有或演进后的 SNN 后端。

直接证据见：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/compute/ISnnComputeCore.h`

### 2.4 配置链路已经能透传新的 workload

当前 `mesh_template` 里已有完整的 `workload_impl` 透传链：

- `sst_dram_si/mesh_template/spec.py`
- `sst_dram_si/mesh_template/runtime.py`
- `sst_dram_si/mesh_template/build.py`

这意味着后续只要新增：

- `workload_impl = "riscv_snn"`
- 对应参数集合

就能不破坏当前 `snn` 路径地接入新模式。

### 2.5 当前最佳粒度：每个 `CoreShell` 一个 hart

当前最合适的映射不是“每个神经元一个 hart”，也不是“整片 chip 一个 hart”，而是：

`每个 CoreShell/PE 一个 RISC-V hart`

理由：

- 与当前 `CoreShell -> workload` 结构一致
- 与已有按 core 归一化的 neuron layout 一致
- 最容易复用现有 `weight / spike / step / barrier` 子系统
- 不会把控制面做成新的集中瓶颈

## 3. 方案总览：`riscv_snn` 的目标形态

### 3.1 一句话结论

`riscv_snn` 不是“让 RISC-V 亲自逐条执行神经元动力学”，而是：

`让 RISC-V 成为整颗 SNN core 的软件接口，而现有 SNN 数据通路仍作为可编程加速后端存在`

### 3.2 总体结构

```text
CoreShell
  ├─ clock / packet / runtime / stats
  └─ RiscvSnnWorkload
       ├─ RV64 Hart
       │   ├─ GPR / PC / CSR / trap / wfi
       │   ├─ local IMEM / DMEM / stack
       │   └─ bare-metal firmware
       ├─ CSR bank
       ├─ command ring
       ├─ completion ring
       ├─ rx ring
       ├─ interrupt router
       └─ SnnAccelBackend
           ├─ ISnnComputeCore
           ├─ WeightMemorySubsystem
           ├─ SpikeCommSubsystem
           ├─ GlobalStep / barrier bridge
           └─ stats / perf counters
```

### 3.3 三个平面

为了避免语义混乱，需要把系统分成三层平面：

| 平面 | 主角色 | 责任 |
|---|---|---|
| 控制平面 | RISC-V hart | 配置、提交任务、等待完成、处理中断、采样统计 |
| 数据平面 | `ISnnComputeCore` + weight/spike 子系统 | 真正执行 gather/apply/scatter、处理 spike、访问权重 |
| 同步平面 | global step / barrier / trap | 保证跨 core 的 step 语义、完成语义、故障传播 |

### 3.4 最关键的设计约束

`incoming spike` 不应该逐条进入软件 handler 后再转回硬件执行。

正确的路径应当是：

```text
NoC packet
  -> accelerator ingress
  -> RX queue / local event buffer
  -> compute backend
  -> 可选地生成“软件可见摘要”或 completion/interruption
```

也就是说：

- software 负责 orchestration
- hardware/backend 负责 high-rate event execution

否则 ISA 虽然“形式上”有了，但仿真出来的是一颗被软件中断淹死的芯片。

## 4. 为什么选择 RISC-V

选择 `RISC-V` 做这条线，不是因为它“流行”，而是因为它天然适合研究型 ISA 演进：

- 标准整数控制流足够稳定
- `Zicsr` 能自然承载 accelerator 控制面
- custom opcode 与 custom CSR 都有规范空间
- toolchain、Spike、opcodes、arch-test 生态比较成熟
- `X` 扩展命名规则清晰，适合研究原型到正式扩展的过渡

参考：

- RISC-V naming: `https://docs.riscv.org/reference/isa/unpriv/naming.html`
- RISC-V extending/custom encoding: `https://docs.riscv.org/reference/isa/unpriv/extending.html`
- RV32/64G opcode map: `https://docs.riscv.org/reference/isa/unpriv/rv-32-64g.html`
- privileged custom CSR: `https://docs.riscv.org/reference/isa/priv/priv-csrs.html`
- Zicsr: `https://docs.riscv.org/reference/isa/unpriv/zicsr.html`
- counters: `https://docs.riscv.org/reference/isa/unpriv/counters.html`
- psABI: `https://riscv-non-isa.github.io/riscv-elf-psabi-doc/`

## 5. ISA 基线定义

### 5.1 v1 推荐 `march`

推荐 v1 基线：

```text
rv64im_zicsr_zifencei_zicntr_zba_zbb_zbs_xsnndl1p0
```

### 5.2 为什么 v1 参考实现先选 `RV64`

虽然 ActiveN 使用的是 `RV32` 级 core，但对当前 `SnnDL`，v1 的 reference firmware 仍优先采用 `RV64`：

- 当前仿真环境与地址空间建模更自然地贴近 64 位 host/地址
- descriptor/ring/统计寄存器在 bring-up 阶段更容易直接使用 64-bit 地址与 token
- 可减少 host-side glue code 的宽度转换复杂度

但这里必须加一条规范约束：

`hart XLEN` 与 `accelerator ABI` 在规范层面是解耦的。

也就是说：

- 本文中 descriptor/ring/token/counter 的位宽如果需要冻结，必须显式写位宽
- 不能把某字段“因为当前 firmware 是 RV64”就默认成 64 位
- 未来如需研究 `RV32 control hart + same backend contract`，不应推翻这份接口规范

### 5.3 为什么先不带这些扩展

v1 暂不包含：

- `A`: 当前不是共享内存多线程模型，队列 ownership 采用单生产者/单消费者契约；但这不等于不需要顺序规则，ring/CSR 的可见性与提交顺序仍须由规范单独定义
- `F/D`: 如果 v1 仍然让神经元动力学跑在 backend，而不是 hart 上，浮点不应成为先决条件
- `V`: 先不引入向量模型，避免把“控制平面 ISA”误做成“计算核 ISA”
- `C`: 研究原型初期更希望保留充足的固定 32-bit 编码空间与更简单的解码路径

### 5.4 `Xsnndl1p0` 的定位

`Xsnndl1p0` 不是一套“大而全”的自定义算术 ISA，而是：

`一组面向 SNN accelerator orchestration 的控制扩展`

这意味着它主要覆盖：

- command submit
- status / fault / queue CSR
- barrier / completion
- 可选的轻量 fastpath 指令

而不是：

- 大量 neuron arithmetic 指令
- 完整向量神经元执行指令

后者如果需要，应该放到更晚的 P3/P4，而不是 v1。

## 6. v1 编程模型

### 6.1 软件模型

v1 采用：

`bare-metal machine-mode only`

不做：

- Linux
- S-mode/U-mode
- virtual memory
- page table

这样做的理由很直接：

- 当前是架构仿真演进，不是通用 SoC bring-up
- 当前目标是定义控制语义，不是定义操作系统语义
- 会极大降低首轮实现与验证复杂度

### 6.2 软件可见对象

v1.1 把软件可见对象分成两级：

#### 必需对象

1. `CSR`
2. `command ring`
3. `completion ring`
4. `interrupt/trap`

其中：

- CSR 负责配置、状态、fault、perf
- command ring 是软件唯一的命令生产接口
- completion ring 是软件唯一的命令退休观察接口
- trap/interrupt 负责异步完成、barrier、fault

#### 可选对象

1. `RX debug ring`

它的定位是：

- 调试
- 统计
- 摘要观测

而不是：

- v1 主执行闭环的必要推进路径

也就是说，`riscv_snn` 的主路径必须能在“不消费 RX debug ring”的情况下保持正确推进。

### 6.3 推荐的主循环

```text
boot
  -> init csr / queue / trap vector
  -> preload config / local metadata
  -> submit prefetch/state load/step commands
  -> wfi
  -> trap handler:
       - drain completion
       - submit next commands
       - handle barrier/fault
       - optional: service RX debug summary
  -> loop
```

### 6.4 为什么强调 `wfi`

不要发明一套完全新的“等待协议”。

RISC-V 标准的 `wfi` 已经很适合：

- 低复杂度
- 语义直观
- 便于和标准 trap/interrupt 模型对齐

因此 v1 应尽量使用：

- `wfi`
- interrupt cause
- CSR pending bits

而不是堆更多自定义阻塞语义。

## 7. v1.1 Backend Timing Contract 与 CSR 规范

这一节开始使用规范术语：

- `MUST`: 必须满足
- `SHOULD`: 推荐满足，除非有明确理由
- `MAY`: 可选

### 7.1 设计原则

CSR 只承载：

- 配置
- 队列指针
- 状态位
- fault code
- 轻量统计

复杂语义与大参数块仍然进入 descriptor。

### 7.2 Backend Timing Contract

下面这些规则是 `RiscvSnnWorkload <-> SnnAccelBackend` 的最小可冻结时序契约。

#### 7.2.1 命令可见性

软件提交命令的规范步骤是：

1. 写 descriptor payload
2. 写 `msnncmdq_tail`
3. 结束此次提交序列

`msnncmdq_tail` 的写入本身就是 v1.1 的 command doorbell。

规范要求：

- backend `MUST NOT` 在观察到新的 `msnncmdq_tail` 之前消费对应条目
- software `MUST NOT` 在发布新 tail 之后修改该条 descriptor，直到 `msnncmdq_head` 越过该条目
- backend `MUST` 在 tail 变更对其可见后的下一次本地 workload 时钟推进点之前，重新观察命令队列是否非空

#### 7.2.2 Accepted 边界

一条命令在且仅在 backend 将 `msnncmdq_head` 从该条目之前推进到该条目之后时，进入 `Accepted` 状态。

这意味着：

- “software 已写 ring” 不等于 `Accepted`
- “backend 看见了 tail” 也不等于 `Accepted`

只有 head 真正跨过该条目，才表示 backend 接管了该命令的所有权。

#### 7.2.3 completion 可见性

对于会产生 completion 的命令：

- backend `MUST` 先完整写入 completion payload
- 然后 `MUST` 更新 `msnncmpq_tail`
- 之后才 `MAY` 产生 completion 对应的 architectural event / interrupt pending

因此软件可以依赖下面的观察顺序：

`看见新的 cmpq_tail` 之后，对应 completion entry 的内容已经稳定可读

#### 7.2.4 fault 可见性

当 backend 以 fault 方式退休某命令时：

- `msnnfault` `MUST` 在 fault 事件对软件可见前先被写好
- 如果该 fault 命令约定产生 completion，则 completion payload 中的 fault/status 字段 `MUST` 与 `msnnfault` 一致
- v1.1 参考合同进一步冻结为：
  - `completion.status_code` 的 `PRIMARY` 与 `msnnfault.FAULT_CODE` 使用同一编码空间
  - `completion.aux0` = `msnnfault[31:0]`
  - `completion.aux1` = `msnnfault[63:32]`
  - 对软件可见的 fault 顺序为：
    - `msnnfault`
    - fault completion payload
    - `msnncmpq_tail`
    - `EV_FAULT / EV_CMD_COMPLETE`

#### 7.2.5 packet 注入语义

`injectPacket()` 的语义冻结为：

`把 packet 交给 backend ingress ownership domain`

它 `MUST NOT` 直接等价于“当前拍立即修改 architectural neuron state”。

也就是说：

- packet 到达 backend
- 进入 ingress FIFO / event buffer / 等价队列
- 之后再由 backend 在自己的调度点消费

这个顺序是架构语义的一部分。

#### 7.2.6 architectural state 与 internal state

`getStepState()` 和软件可见 CSR/status 只允许暴露：

- 已提交的 architectural state
- 已退休命令的结果

它们 `MUST NOT` 暴露 backend 内部的半完成瞬态状态作为已提交结果。

### 7.3 推荐地址区间

优先使用 machine custom CSR 范围：

```text
0xBC0 - 0xBFF
```

### 7.4 CSR 规范草图

| CSR 名 | 地址 | 含义 |
|---|---:|---|
| `msnncfg` | `0xBC0` | 总配置：enable、mode、architectural event enable、debug bits |
| `msnnstatus` | `0xBC1` | busy、fault、queue full/empty、barrier state、drain state |
| `msnnfeat` | `0xBC2` | feature bitmap：版本、队列数、支持命令、counter 能力 |
| `msnnhartid` | `0xBC3` | 本地 core/hart 标识，与 runtime/core id 对齐 |
| `msnncmdq_base` | `0xBC8` | command ring base |
| `msnncmdq_size` | `0xBC9` | command ring entries |
| `msnncmdq_head` | `0xBCA` | backend consumer head |
| `msnncmdq_tail` | `0xBCB` | software producer tail；也是 command doorbell |
| `msnncmpq_base` | `0xBCC` | completion ring base |
| `msnncmpq_size` | `0xBCD` | completion ring entries |
| `msnncmpq_head` | `0xBCE` | software consumer head |
| `msnncmpq_tail` | `0xBCF` | backend producer tail |
| `msnnrxq_base` | `0xBD0` | RX debug ring base |
| `msnnrxq_size` | `0xBD1` | RX debug ring entries |
| `msnnrxq_head` | `0xBD2` | software RX debug consumer |
| `msnnrxq_tail` | `0xBD3` | backend RX debug producer |
| `msnneventen` | `0xBD8` | architectural event enable |
| `msnneventpend` | `0xBD9` | architectural event pending / clear |
| `msnnstep` | `0xBDA` | 当前 global step / local sequence / step phase |
| `msnnfault` | `0xBDB` | 最近 fault code / aux |
| `msnnperf0-3` | `0xBE0-0xBE3` | 局部性能计数器窗 |

### 7.5 `msnncfg` 位级定义

`msnncfg` 是可读写 CSR，reset 值为 `0x0000_0000`。

| bit | 名称 | 含义 |
|---:|---|---|
| `0` | `ACCEL_EN` | `1` 表示允许 backend 接受新命令；`0` 表示停止接受新命令 |
| `1` | `AUTO_START_EN` | `1` 表示 backend 在看到新 `cmdq_tail` 后自动调度；v1.1 推荐为 `1` |
| `2` | `RXDBG_SUMMARY_EN` | `1` 表示 backend 可以生成 RX debug summary |
| `3` | `STRICT_CFG_EN` | `1` 表示对保留字段/非法组合使用严格 fault；v1.1 推荐为 `1` |
| `4` | `TRACE_EN` | `1` 表示允许 backend 生成额外 trace/debug 元数据 |
| `7:5` | `reserved` | 读为 `0`，写必须为 `0` |
| `15:8` | `EXEC_MODE` | backend 执行模式编码 |
| `31:16` | `reserved` | 读为 `0`，写必须为 `0` |

`EXEC_MODE` 在 v1.1 的编码如下：

| 编码 | 含义 |
|---:|---|
| `0x00` | `FUSED_ONLY`，只保证 `FUSED_STEP` 主路径 |
| `0x01` | `PHASE_EXPLICIT`，允许 phase 级命令 |
| `0x02` | `SERVICE_DEBUG`，保留给 bring-up/debug |
| 其他 | 保留，写入 `MUST` 触发 fault |

规范补充：

- software `SHOULD` 在 `ACCEL_EN=0` 时完成 queue base/size 等初始化
- 从 `ACCEL_EN=0 -> 1` 的跃迁表示 backend 可以开始观察 doorbell
- 从 `ACCEL_EN=1 -> 0` 不要求清空 ring，但 `MUST` 阻止后续新命令进入 `Accepted`

### 7.6 `msnnstatus` 位级定义

`msnnstatus` 是只读 CSR。

| bit | 名称 | 含义 |
|---:|---|---|
| `0` | `BUSY` | backend 当前存在未退休命令 |
| `1` | `CMDQ_FULL` | command ring 满 |
| `2` | `CMPQ_NONEMPTY` | completion ring 非空 |
| `3` | `RXDBG_NONEMPTY` | RX debug ring 非空 |
| `4` | `BARRIER_WAIT` | 当前命令已进入 barrier waiting |
| `5` | `FAULT_VALID` | `msnnfault` 包含尚未被软件确认的新 fault |
| `6` | `STEP_ACTIVE` | 当前存在活动中的 step |
| `7` | `OUTBOUND_DRAIN` | 当前处于 outbound ownership transfer 阶段 |
| `15:8` | `reserved` | 读为 `0` |
| `23:16` | `LAST_ACCEPT_OPCODE` | 最近一次进入 `Accepted` 的 opcode；若无则为 `0` |
| `63:24` | `reserved` | 读为 `0` |

### 7.7 `msnneventen` / `msnneventpend` 位级定义

`msnneventen` 为可读写使能位图，`msnneventpend` 为可读写 pending 位图，其中：

- `msnneventpend` 的 `bit[5:0]` 为 `W1C`
- 对 `msnneventpend` 写 `0` 不产生副作用
- disabled event 即使不触发 trap，也 `MUST` 在 `msnneventpend` 中可见，除非该事件被实现为完全不产生
- `wfi` 的唤醒条件只取决于 `(msnneventpend & msnneventen) != 0`
- 如果某事件已经 pending，而 software 后续才打开对应 enable bit，则 hart `MUST` 立即变成 wake-eligible

| bit | 事件名 | 含义 |
|---:|---|---|
| `0` | `EV_CMD_COMPLETE` | completion ring 新增可见条目 |
| `1` | `EV_BARRIER_RELEASE` | 当前 step 的 barrier release 已发生 |
| `2` | `EV_FAULT` | `msnnfault` 已更新 |
| `3` | `EV_RX_DEBUG` | RX debug ring 新增条目 |
| `4` | `EV_PREFETCH_DONE` | 预取类命令完成 |
| `5` | `EV_DEBUG` | debug/watchpoint |
| `31:6` | `reserved` | 读为 `0`，写必须为 `0` |

### 7.8 `msnnstep` 与 `msnnfault` 位级定义

`msnnstep` 为只读 CSR，编码如下：

| bit | 名称 | 含义 |
|---:|---|---|
| `31:0` | `COMMITTED_SEQ` | 最近一个已到达 architectural commit boundary 的 step sequence |
| `47:32` | `INFLIGHT_SEQ` | 当前活动 step sequence；若无活动 step 则为 `0` |
| `55:48` | `PHASE` | 当前活动 step 生命周期编码 |
| `63:56` | `reserved` | 读为 `0` |

`PHASE` 在 v1.1 中冻结为：

| 编码 | 含义 |
|---:|---|
| `0x00` | `IDLE` |
| `0x01` | `ACCEPTED` |
| `0x02` | `PREFETCHING` |
| `0x03` | `EXECUTING` |
| `0x04` | `OUTBOUND_DRAINING` |
| `0x05` | `BARRIER_WAITING` |
| 其他 | 保留 |

`msnnfault` 为读写 CSR，其中软件通过向低 `16` 位写 `0` 的方式确认 fault 已处理；v1.1 参考实现把这条语义进一步冻结为：

- 只要 software write 满足 `value[15:0] == 0`，architectural `msnnfault` 整个 CSR `MUST` 被清为 `0`
- 这次 software ack `MUST NOT` 隐式清除 `msnneventpend.EV_FAULT`
- `EV_FAULT` 仍然需要软件通过 `msnneventpend` 单独 ack
- `msnnstatus.FAULT_VALID` `MUST` 在下一次 workload-visible status 同步点消失
- 这次 clear 只确认当前“可见 fault record”，`MUST NOT` 反向修改已经退休 completion 的 `aux0/aux1`
- 后续新的 accepted fault `MAY` 覆盖当前可见的 `msnnfault`，但先前 completion payload 仍保持退休瞬间的 fault snapshot

backend 写入格式如下：

| bit | 名称 | 含义 |
|---:|---|---|
| `7:0` | `FAULT_CODE` | fault 主编码 |
| `15:8` | `FAULT_SRC` | fault 来源：descriptor/queue/phase/barrier/memory/backend |
| `31:16` | `FAULT_SLOT` | 相关 ring slot 或本地命令槽编号 |
| `63:32` | `FAULT_AUX` | 实现相关辅助信息 |

v1.1 参考实现对 `FAULT_SLOT` 与 `FAULT_AUX` 的约束补充如下：

- 对由 descriptor 校验直接导出的 fault，`FAULT_SLOT` 使用该命令的 `ticket[15:0]`
- 对由 completion publish / queue writeback 导出的本地 fault，`FAULT_SLOT` 使用本地可见 completion slot
- `FAULT_AUX` 对 descriptor fault 记录 offending field 的压缩值：
  - `bad flags` 记录保留 flag bits
  - `bad policy` 记录 `hdr0[63:32]`
  - 其他 fault 允许记录地址、队列深度或实现相关辅助信息

推荐 `FAULT_SRC` 编码：

| 编码 | 含义 |
|---:|---|
| `0` | none |
| `1` | descriptor |
| `2` | queue |
| `3` | phase |
| `4` | barrier |
| `5` | memory |
| `6` | backend internal |
| 其他 | 保留 |

## 8. v1.1 Architectural Events、Interrupt 与 Trap

### 8.1 先冻结“事件语义层”，再冻结“编号映射层”

v1.1 先冻结的软件可见 architectural event 类别是：

| 事件类 | 含义 |
|---|---|
| `EV_CMD_COMPLETE` | completion ring 新增可见条目 |
| `EV_BARRIER_RELEASE` | 当前 step sequence 的 barrier 已 release |
| `EV_FAULT` | `msnnfault` 有新 fault |
| `EV_RX_DEBUG` | RX debug ring 新增条目 |
| `EV_PREFETCH_DONE` | 预取类命令完成，可选 |
| `EV_DEBUG` | debug/watchpoint，可选 |

这里故意把“事件类别”和“具体 `mcause` 编号”拆开。

规范层冻结的是：

- 哪些 architectural event 对软件可见
- 它们与 CSR/ring 的可见性顺序

而不是 P0/P1 就把 delivery 机制完全锁死在某个具体实现细节上。

### 8.2 推荐编号映射

如果采用 custom local interrupt cause 编码，则建议映射为：

| cause | architectural event |
|---:|---|
| `24` | `EV_CMD_COMPLETE` |
| `25` | `EV_RX_DEBUG` |
| `26` | `EV_PREFETCH_DONE` |
| `27` | `EV_BARRIER_RELEASE` |
| `28` | `EV_FAULT` |
| `29` | `EV_DEBUG` |
| `30-31` | reserved |

这一表在 v1.1 中是：

`recommended mapping`

而不是不可修改的实现约束。

参考实现层建议显式区分两层概念：

- `ArchitecturalEvent`
- `RecommendedDeliveryCause`

前者冻结软件可见事件语义，后者只提供默认 delivery 编号建议。

### 8.3 trap 处理原则

trap handler 只做四件事：

1. 读取并确认事件类别或 cause
2. drain completion / fault / debug summary 等已提交对象
3. 提交后续命令或更新软件状态
4. 返回 `mret`

trap handler `MUST NOT` 承担高频 spike 主执行路径。

### 8.4 fault 分类建议

v1.1 参考实现把 `msnnfault.FAULT_CODE` 与 completion `PRIMARY` 直接对齐，因此建议至少支持：

| code | 含义 |
|---:|---|
| `0x01` | bad version |
| `0x02` | bad desc_bytes |
| `0x03` | bad opcode |
| `0x04` | bad flags |
| `0x05` | bad alignment |
| `0x06` | bad policy |
| `0x10` | command queue overflow |
| `0x11` | completion queue overflow |
| `0x20` | illegal phase transition |
| `0x21` | barrier protocol violation |
| `0x30` | memory semantic fault |
| `0x31` | backend internal error |

## 9. v1.1 Descriptor / Ring ABI

### 9.1 为什么要用 descriptor

这条线的核心思想之一是：

`复杂语义走内存描述符，简单控制走 CSR`

原因：

- 自定义指令编码空间宝贵
- 描述符更容易扩展
- 编译器和固件都更容易演进
- 更适合仿真时增删字段

### 9.2 ring ownership 规则

v1.1 冻结为单生产者/单消费者模式：

| ring | 生产者 | 消费者 |
|---|---|---|
| command ring | software | backend |
| completion ring | backend | software |
| RX debug ring | backend | software |

规范要求：

- 只有生产者可以写 `tail`
- 只有消费者可以写 `head`
- 另一侧只能读自己不拥有的指针
- 未跨 ownership 边界的条目不得被另一侧修改
- `head`/`tail` CSR 保存的是单调递增的 `entry ticket`，不是取模后的物理槽号
- 物理槽号按 `ticket & (size_entries - 1)` 计算，因此 `size_entries` `MUST` 是 2 的幂
- 队列空条件是 `head == tail`
- 队列满条件是 `tail - head == size_entries`
- `msnncmdq_base` `MUST` 按 64B 对齐；`msnncmpq_base` 与 `msnnrxq_base` `MUST` 按 16B 对齐

### 9.3 doorbell 规则

v1.1 不引入单独的 doorbell CSR。

规范定义：

- software 对 `msnncmdq_tail` 的写入，就是 command doorbell
- software 对 `msnncmpq_head` 的写入，表示 completion 已消费释放
- software 对 `msnnrxq_head` 的写入，表示 RX debug entry 已消费释放

后续如实现 `snn.sync`，它只允许作为优化 fastpath，不改变上述 architectural 语义。

### 9.4 command descriptor ABI

v1.1 命令描述符固定为 64B 对齐格式：

| 偏移 | 字段 | 说明 |
|---:|---|---|
| `0x00` | `hdr0` | `version[7:0] / opcode[15:8] / flags[23:16] / completion_policy[31:24] / error_policy[39:32] / desc_bytes[47:40] / reserved[63:48]` |
| `0x08` | `token` | software 提供的 opaque token，completion 原样回显 |
| `0x10` | `arg0` | 命令参数 0 |
| `0x18` | `arg1` | 命令参数 1 |
| `0x20` | `src_addr` | 源地址或主地址 0 |
| `0x28` | `dst_addr` | 目标地址或主地址 1 |
| `0x30` | `len_or_count` | 长度、数量或 tile 大小 |
| `0x38` | `dep_user` | `dep_token[31:0] / user[63:32]` |

v1.1 规范要求：

- `version` `MUST` 为 `1`
- `desc_bytes` `MUST` 为 `64`
- `completion_policy` 在 v1.1 中 `MUST` 为 `0`
- `error_policy` 在 v1.1 中 `MUST` 为 `0`
- `hdr0[63:48]` reserved bits 在 v1.1 中 `MUST` 为 `0`
- 非法 `version`、`desc_bytes`、policy 值以及 reserved header bits `MUST` 触发 strict fault

其中 `flags[23:16]` 在 v1.1 的位分配如下：

| bit | 名称 | 含义 |
|---:|---|---|
| `0` | `IRQ_HINT` | `1` 表示该命令退休后推荐尽快暴露 `EV_CMD_COMPLETE`；`0` 允许实现做 completion event 合并 |
| `1` | `TRACE_HINT` | `1` 表示该命令允许生成额外 debug/trace 信息 |
| `7:2` | `reserved` | v1.1 必须为 `0` |

另外：

- `completion_policy = 0` 表示 `RETIRE_TO_CMPQ`
- `error_policy = 0` 表示 `FAULT_AND_COMPLETE`
- `flags[7:2] != 0` `MUST` 触发 `bad flags`
- `completion_policy != 0`、`error_policy != 0` 或 `hdr0[63:48] != 0` `MUST` 触发 `bad policy`

### 9.5 v1.1 命令集合

| opcode | 命令 | 作用 |
|---:|---|---|
| `0x00` | `NOP` | 占位 |
| `0x01` | `PREFETCH_W` | 预取权重/rowptr/colidx/block data |
| `0x02` | `STATE_LOAD` | 加载神经元状态块 |
| `0x03` | `STATE_STORE` | 写回神经元状态块 |
| `0x10` | `PHASE_GATHER` | 仅执行 gather |
| `0x11` | `PHASE_APPLY` | 仅执行 apply |
| `0x12` | `PHASE_SCATTER` | 仅执行 scatter |
| `0x20` | `FUSED_STEP` | 执行一个完整 step |
| `0x30` | `EGRESS_CTRL` | 发送显式控制/调试事件；不是高频 spike 主路径 |
| `0x31` | `RX_DEBUG_POP` | 消费 RX debug 摘要；不参与主执行闭环 |
| `0x40` | `BARRIER_ARRIVE` | 本地到达 barrier |
| `0x50` | `STAT_SNAPSHOT` | 快照统计到指定缓冲 |
| 其他 | reserved | 非法，`MUST` 触发 fault |

### 9.6 completion entry ABI

completion ring entry 固定为 16B：

| 偏移 | 字段 |
|---:|---|
| `0x00` | `token` |
| `0x04` | `status_code` |
| `0x08` | `aux0` |
| `0x0C` | `aux1` |

规范要求：

- 对于除 `NOP` 之外的 v1.1 命令，每条已接受并退休的命令 `MUST` 产生且仅产生一条 completion
- `token` `MUST` 与 descriptor 中的 `token` 一致
- `status_code = 0` 表示成功；非零表示 fault/拒绝/保留错误

`status_code` 的位级定义如下：

| bit | 名称 | 含义 |
|---:|---|---|
| `7:0` | `PRIMARY` | 主状态码 |
| `15:8` | `SEVERITY` | `0=success`、`1=rejected-before-accept`、`2=fault-after-accept` |
| `31:16` | `reserved` | v1.1 读为 `0` |

`PRIMARY` 推荐编码：

| 编码 | 含义 |
|---:|---|
| `0x00` | success |
| `0x01` | bad version |
| `0x02` | bad desc_bytes |
| `0x03` | bad opcode |
| `0x04` | bad flags |
| `0x05` | bad alignment |
| `0x06` | bad policy |
| `0x10` | command queue overflow |
| `0x11` | completion queue overflow |
| `0x20` | illegal phase transition |
| `0x21` | barrier protocol violation |
| `0x30` | memory semantic fault |
| `0x31` | backend internal error |

当 `status_code != 0` 时，v1.1 参考合同进一步冻结：

- `aux0` = `msnnfault[31:0]`
- `aux1` = `msnnfault[63:32]`
- 因此 firmware 可以在不额外引入第二份 fault sideband 的前提下，直接对齐：
  - completion payload
  - `msnnfault`
  - fault architectural event

### 9.7 RX debug entry ABI

RX debug ring 不承载高频 spike 主载荷，而只承载摘要与调试观测：

| 偏移 | 字段 |
|---:|---|
| `0x00` | `rx_type` |
| `0x04` | `seq` |
| `0x08` | `count_or_bytes` |
| `0x0C` | `ptr_or_aux` |

如果未来某些模式确实要把更细粒度的事件给软件，也 `SHOULD` 通过 `ptr_or_aux -> payload buffer` 间接引用，而不是把 ring 本身做成重载体。

## 10. 自定义指令策略

### 10.1 核心原则

v1 不追求“指令数量多”，而追求：

- toolchain 早起步
- 语义不早冻死
- 先把 workload 跑通

### 10.2 推荐分阶段策略

#### P0 / P1

先只使用：

- 标准 RISC-V 指令
- `csrrw/csrrs/csrrc`
- 普通 store/load 操作 ring
- `wfi`

必要时用 `.insn` 封装 1-2 条过渡性指令。

#### P2

语义稳定后，再冻结正式自定义指令：

| 指令 | 语义 |
|---|---|
| `snn.issue rd, rs1, rs2` | 提交 `rs1` 指向描述符，可选 `rs2` 带 flags，返回 token/status |
| `snn.sync rd, rs1, x0` | doorbell / barrier fastpath |
| `snn.poll rd, x0, x0` | 快速状态读 |

### 10.3 为什么不复制 ActiveN 的 `queue/send`

ActiveN 的 `queue/send` 指令很适合“软件亲自处理 event handler”的核心设计。

但对 `SnnDL` 来说，v1 不应把控制面做成：

`软件 handler 驱动全部 spike execution`

因此我们只吸收它“轻量消息指令 + event-driven scheduling”的思想，不直接复制它的指令形态。

## 11. 内存与数据放置模型

### 11.1 与 ActiveN 相同的大方向

这点和 ActiveN 高度一致：

- 热状态、本地元数据放本地
- 大量权重/突触数据放 bulk memory
- 尽量把 memory latency 隐藏在异步命令和队列后面

### 11.2 对当前 `SnnDL` 的落地

建议：

- neuron state / local queues / row metadata：放 `CoreShell` 对应的 local semantic region / local storage
- large weight / synapse arrays：继续由 `WeightMemorySubsystem` 管理，允许位于高延迟 memory
- spike route / inter-core transfer：继续走现有 `SpikeCommSubsystem` / NoC 语义

### 11.3 v1 不做的事情

v1 不做：

- 把所有 weights 强行打进 ELF
- 强制统一成 flat addressable SRAM-only 模型
- 把 memory hierarchy 重写成 CPU cache 主导模型

保留现有 `WeightLoader` 和既有数据资产格式，才是最小扰动方案。

## 12. v1.1 运行时执行模型与 `FUSED_STEP` 规范

### 12.1 启动流程

建议的启动流程：

1. `RiscvSnnWorkload` 创建 hart 和 backend。
2. 加载 ELF 到 IMEM/DMEM。
3. 初始化 CSR 默认值。
4. firmware 设置 trap vector、queue base/size、feature probe。
5. firmware 提交预加载命令：
   - metadata prefetch
   - weight prefetch
   - state load
6. firmware 进入主循环。

### 12.2 `FUSED_STEP` 生命周期状态机

`FUSED_STEP` 在 v1.1 中冻结为下列状态机：

```text
Idle
  -> Accepted
  -> Prefetching (optional)
  -> Executing
  -> OutboundDraining
  -> BarrierWaiting
  -> Completed
  or Faulted
```

状态含义：

| 状态 | 含义 |
|---|---|
| `Idle` | backend 尚未接受该命令 |
| `Accepted` | command ownership 已转移到 backend |
| `Prefetching` | 可选预取阶段，尚未进入主执行 |
| `Executing` | gather/apply/scatter 或等价融合执行进行中 |
| `OutboundDraining` | 本 step 生成的 outbound event 正在移交给通信子系统 |
| `BarrierWaiting` | 本地已到达 step 边界，等待全局 barrier release |
| `Completed` | 命令已在架构上提交完成 |
| `Faulted` | 命令以 fault 方式退休 |

### 12.3 `FUSED_STEP` completion 语义

下面这句话在 v1.1 中是冻结语义：

`FUSED_STEP completion` 当且仅当当前 step sequence 已达到 architectural commit boundary。

这个 boundary 需要同时满足：

1. 本地 gather/apply/scatter 已全部完成
2. 本 step 产生的 outbound event 已全部移交给 communication ownership domain，backend 不再持有这些发送项
3. 按当前 step 协议要求必须计入本 step 的 inbound event 已经并入本地 architectural state
4. 当前 step sequence 的 global barrier release 已发生
5. 本 step 对软件可见的本地状态与统计结果已经提交，并可经 completion/CSR/state snapshot 观察

这一定义故意选择强 completion 边界，以保证：

- firmware 不必猜测“本地完成”与“全局完成”的差异
- `riscv_snn` 与现有 `snn` 的 step 对齐验证更直接
- `RX_DEBUG_POP` 与 RX debug ring 不会被误读成主执行闭环的一部分

### 12.4 一个 step 的规范路径

```text
firmware submit FUSED_STEP
  -> backend Accepted
  -> optional Prefetching
  -> Executing
  -> OutboundDraining
  -> BarrierWaiting
  -> completion payload write
  -> cmpq_tail update
  -> barrier/complete event pending
  -> firmware wakeup
```

### 12.5 为什么 v1 推荐 `FUSED_STEP`

虽然从“纯 ISA 美感”看，完全开放 `GATHER/APPLY/SCATTER` 更细粒度；
但从系统 bring-up 角度，`FUSED_STEP` 更适合作为第一个稳定命令：

- 最接近当前 `SnnWorkload` 的自然执行边界
- 最容易与现有 golden 结果对比
- 更不容易在 phase 切换中引入协议 bug

等 `FUSED_STEP` 稳定后，再逐步放开 phase 级指令。

## 13. 与现有 SnnDL 模块的映射

### 13.1 推荐抽象重构

新增：

- `services/workload/riscv_snn/`
- `services/workload/common/SnnAccelBackend` 或等价抽象

目标是：

- `SnnWorkload` 继续复用同一 backend
- `RiscvSnnWorkload` 用另一套控制面驱动同一 backend

### 13.2 后端需要承接的能力

`SnnAccelBackend` 至少需要对外暴露：

- `configure`
- `submitCommand`
- `pollCompletion`
- `injectPacket`
- `getRxSummary`（optional/debug）
- `getStepState`（仅返回已提交的 architectural state）
- `snapshotStats`

并且这些接口的时序与可见性必须服从：

- 第 7 节的 `Backend Timing Contract`
- 第 12 节的 `FUSED_STEP` completion semantics

内部仍然复用：

- `ISnnComputeCore`
- `WeightMemorySubsystem`
- `SpikeCommSubsystem`
- `GlobalGasStepController` 或等价 step 控制

### 13.3 `TensorWorkload` 的借鉴

当前 `TensorWorkload` 已经存在 `exec_mode=program` 与 `program_dsl` 的概念，说明：

- 在 workload 内部引入“程序驱动语义”是被当前仓库接受的
- 先做 runtime 程序模型，再冻结更正式 ISA，是仓库风格上能接受的演进方式

直接证据见：

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.h`

## 14. 实施路线

### 14.1 P0: skeleton bring-up

目标：

- `workload_impl=riscv_snn` 可创建并跑一个最小 bare-metal 程序

范围：

- `RiscvSnnWorkload` skeleton
- 简单 hart 模拟器/解释器或接入现有 RISC-V ISS
- ELF loader
- IMEM/DMEM
- 基础 CSR
- 轮询式 command queue
- 一个最小 `FUSED_STEP` 命令

退出标准：

- 固件能提交一步，并拿到 completion

### 14.2 P1: interrupt + queue 完整化

目标：

- 从“能跑”变成“像一颗可中断 ISA 核”

范围：

- completion/optional-rx/barrier/fault interrupt
- `wfi`
- trap handler
- `PREFETCH_W`
- `STATE_LOAD/STORE`
- `STAT_SNAPSHOT`

退出标准：

- firmware 可以通过中断驱动多个 step

### 14.3 P2: `Xsnndl1p0` 冻结

目标：

- 冻结 CSR map、descriptor 格式、自定义指令编码

范围：

- `riscv-opcodes` 描述
- Spike 扩展支持
- 汇编宏/内建
- 基础 arch-test / compliance 样例

退出标准：

- 可稳定重建二进制并在 ISS/仿真器中一致运行

### 14.4 P3: 架构增强

可选项：

- 更细粒度的 phase commands
- richer debug/trace
- 更多 custom counters
- optional tensor/vector 协同
- 可选 dual-thread/control acceleration

## 15. 验证计划

### 15.1 功能验证矩阵

| 层级 | 验证内容 |
|---|---|
| 标准 ISA | `rv64im_zicsr_zifencei_zicntr_zba_zbb_zbs` 指令正确性 |
| CSR | 读写、副作用、非法访问、reset 值 |
| timing contract | tail/head/completion/fault 的可见性顺序 |
| ring | full/empty、ownership、doorbell、token 一致性 |
| interrupt | architectural event -> pending -> trap 的顺序 |
| descriptor | version/size/opcode/非法 policy/error 路径 |
| backend mapping | `FUSED_STEP` 与现有 `snn` workload 结果对齐 |
| regression | 现有 `workload_impl=snn` 不能退化 |

### 15.2 对齐验证

最重要的不是“能跑”，而是：

`同一网络、同一输入、同一映射，在 riscv_snn 与 snn 模式下给出一致的 step/spike/stat 结果`

建议第一批对齐检查：

- step 完成数
- per-step emitted spikes
- barrier 次数
- weight read bytes
- key neuron state snapshots

### 15.3 工具链验证

建议并行维护三类验证：

1. `SnnDL` 内仿真
2. Spike / 轻量 ISS
3. unit test for CSR + queue + trap

其中：

- 标准 RISC-V ISA 正确性主要靠 Spike / `riscv-arch-test`
- 自定义扩展语义主要靠本仓库单测和 golden workload

## 16. ActiveN 论文能给我们的真正启发

研究对象：

- `artcile/ActiveN_A_Scalable_and_Flexibly-Programmable_Event-Driven_Neuromorphic_Processor(1).pdf`
- MICRO 2024
- DOI: `10.1109/MICRO61859.2024.00085`

### 16.1 ActiveN 的核心思想

ActiveN 最值得注意的不是“它也用了 RISC-V”，而是它做了三件相互耦合的事情：

1. 用 `active-message-enabled` 微架构支持事件驱动执行。
2. 用 `CSR-like sparse synapse layout + memory-side forwarding` 隐藏权重访问延迟。
3. 把大量 synapse 数据放到高延迟 bulk memory，同时把热状态放本地 scratchpad。

论文反复强调一个判断：

`SNN 的瓶颈主要是数据访问，而不是把神经元算子做成多么夸张的专用电路。`

这和我们当前 `SnnDL` 的现实非常契合，因为现有系统本身已经围绕：

- weight memory
- NoC packet
- GAS / gather-apply-scatter

这些 memory/communication heavy 路径建立起来了。

### 16.2 我们应该直接吸收的灵感

#### 灵感 1：控制面与数据面分离，但控制面必须是事件驱动的

ActiveN 中，一个 handler 只处理很短的过程，靠 message queue 与优先级调度驱动。

对应到我们这里，可以转化为：

- hart 不需要长时间 busy-spin
- completion / rx / barrier / fault 都应优先由 trap 驱动
- `wfi + interrupt` 是正确的一等公民

#### 灵感 2：大容量突触数据不应强求 on-chip 常驻

ActiveN 明确把 synapse 数据放在高延迟 bulk memory，并通过 memory-side 机制减少代价。

对应到 `SnnDL`：

- 不应为了做 ISA 级而把所有权重塞回本地 SRAM/ELF
- 应继续复用 `WeightMemorySubsystem`
- 应逐步把 descriptor-aware prefetch / sparse-aware fetch 做起来

#### 灵感 3：本地只保留热状态和元数据

ActiveN 把：

- neuron states
- input/update queue
- row metadata

放到 local scratchpad。

对应到我们这里，最值得借鉴的是：

- local semantic region
- per-core queue
- row/block 元数据 cache

而不是复制它的 scratchpad 实现细节。

#### 灵感 4：memory-side sparse-aware forwarding 非常值得借鉴

ActiveN 的 memory controller 不是只读字节，而是能理解 CSR 行布局并直接把目标数据转发给下游 PU。

这对我们是非常重要的启发：

- 后续 `WeightMemorySubsystem` 不应永远停留在“纯 byte-serving”层
- 可以逐步演进出“descriptor-aware”甚至“synapse-format-aware”的 memory service
- 这比一开始增加很多 fancy custom opcodes 更有价值

#### 灵感 5：事件优先级与死锁规避不能晚做

ActiveN 明确讨论了：

- event priority allocation
- queue saturation
- deadlock avoidance

这对我们尤其重要，因为：

- 我们的系统有 NoC
- 有 packet
- 有 barrier
- 有 completion
- 未来还会有 RX software-visible queue

因此 `riscv_snn` 从第一版开始就应该显式区分：

- completion
- RX
- barrier
- fault

的优先级，而不是后期再救火。

### 16.3 我们不应该直接照搬的部分

#### 不照搬 1：让软件直接执行完整 neuron update

ActiveN 是“通用核心 + 事件 handler + 神经元更新软件化”的路线。

而当前 `SnnDL` 已经有成熟的 `ISnnComputeCore` 语义和现成的 gather/apply/scatter 组织方式。

因此我们不应回退成：

`hart 逐条执行 neuron dynamics`

否则会丢失当前平台最有价值的 cycle-level substrate。

#### 不照搬 2：一开始就大做定制浮点/神经元算术指令

ActiveN 为适配多种 neuron model，扩展了紧凑的 fixed/floating-point 指令集合。

这在它的路线里是合理的，因为它的 core 亲自执行神经元更新。

但对我们当前路线，v1 的优先级不是：

- “把 neuron arithmetic 指令做漂亮”

而是：

- “把控制面 ISA、descriptor、queue、interrupt 做对”

算术扩展如果未来确实有价值，也应当放到更晚阶段。

#### 不照搬 3：直接复制它的 `queue/send` 形式

ActiveN 的 `queue/send` 很贴合它的 active message core。

但我们的系统更接近：

- CSR + descriptor ring orchestration
- backend autonomous execution

因此更适合吸收它的“轻量消息提交”思想，而不是原样复刻它的编码方式。

### 16.4 ActiveN 给我们的最重要结论

如果把论文内容压缩成一句最有价值的话，那就是：

`在 SNN 芯片里，先把 memory/queue/event 路径做对，往往比先把算术 datapath 做得更花更重要。`

这与我们当前决定“v1 优先做 workload-level RISC-V control-plane，而不是 neuron arithmetic ISA”是高度一致的。

## 17. 风险与开放问题

### 17.1 最大风险

最大风险不是工具链，而是抽象层选错：

- 如果把 `RISC-V` 做进 `CoreShell`，会污染平台边界
- 如果把 `RISC-V` 做进 `ISnnComputeCore`，会污染 SNN 执行语义
- 如果让 software 逐条处理 spike，会在性能和模型上同时失败

### 17.2 需要尽早冻结的接口

后续最早需要冻结的是：

1. `RiscvSnnWorkload <-> SnnAccelBackend` timing contract
2. `FUSED_STEP` 的 completion semantics
3. ring ownership + doorbell semantics
4. CSR map
5. interrupt architectural event classes
6. recommended cause mapping

### 17.3 当前暂不冻结的东西

可以晚一点再冻结：

- custom opcode 精确编码
- richer phase-level command set
- 是否引入向量/浮点扩展
- debug trace 格式

## 18. 推荐的下一步

建议后续按如下顺序继续：

1. 先把 `timing contract + FUSED_STEP completion + ring ownership/doorbell` 细化到位级规范。
2. 明确 `SnnAccelBackend` 最小接口，把当前 `SnnWorkload` 的共性逻辑抽出来。
3. 在此基础上细化 `CSR map + architectural event classes + descriptor bitfield`。
4. 实现 `P0 skeleton`：
   - `workload_impl=riscv_snn`
   - ELF loader
   - CSR
   - command ring
   - 最小 `FUSED_STEP`
4. 用一个最小 mesh regression 对比 `snn` 与 `riscv_snn` 的 step/spike/stat 一致性。

### 18.1 2026-03-25 Phase C 现实校验

截至 `2026-03-25`，Phase C 的 dated reference 已经表明：

1. `equiv` compare harness 已经能稳定输出 summary，即使单侧 smoke/validation 非零，也不会再直接丢失结果。
2. `snn` baseline 与 `riscv_snn(runtime_bridge)` 在当前 fixed compare surface 上，strict/trend 字段已经对齐。
3. 当前 `FAIL` 的来源不是 strict/trend drift，而是 baseline validator 里的：
   - `step_activation.invocations_vs_windows`
4. runtime bridge 侧的 `riscv_snn_fused_step_completion_count` 等统计还没有进入最终 `mesh_stats.csv` / summary surface，所以即便 baseline validator 收口，下一步也只会先到 `WARN`。

因此，推荐的下一步已经从“继续扩 compare surface”切换为：

1. 为 equivalence baseline 收紧一个独立、可解释、且不污染默认 `snn` 主线的 validation surface。
2. 把 runtime bridge completion/fault 统计打通到最终 stats artifact。

## 19. 参考资料

### 19.1 本仓库代码与文档

- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/CoreWorkloadFactory.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/README.md`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/compute/ISnnComputeCore.h`
- `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/tensor/TensorWorkload.h`
- `sst_dram_si/mesh_template/spec.py`
- `sst_dram_si/mesh_template/runtime.py`
- `sst_dram_si/mesh_template/build.py`

### 19.2 论文

- `artcile/ActiveN_A_Scalable_and_Flexibly-Programmable_Event-Driven_Neuromorphic_Processor(1).pdf`
- Xiaoyi Liu, Zhongzhu Pu, Peng Qu, Weimin Zheng, Youhui Zhang, “ActiveN: A Scalable and Flexibly-Programmable Event-Driven Neuromorphic Processor”, MICRO 2024, DOI `10.1109/MICRO61859.2024.00085`

### 19.3 RISC-V 官方资料

- `https://docs.riscv.org/reference/isa/unpriv/naming.html`
- `https://docs.riscv.org/reference/isa/unpriv/extending.html`
- `https://docs.riscv.org/reference/isa/unpriv/rv-32-64g.html`
- `https://docs.riscv.org/reference/isa/priv/priv-csrs.html`
- `https://docs.riscv.org/reference/isa/unpriv/zicsr.html`
- `https://docs.riscv.org/reference/isa/unpriv/counters.html`
- `https://docs.riscv.org/reference/isa/unpriv/b-st-ext.html`
- `https://docs.riscv.org/reference/isa/unpriv/v-st-ext.html`
- `https://riscv-non-isa.github.io/riscv-elf-psabi-doc/`
- `https://docs.riscv.org/reference/hardware/aia/_attachments/riscv-interrupts.pdf`
- `https://github.com/riscv-software-src/riscv-isa-sim`
- `https://github.com/riscv/riscv-opcodes`
- `https://github.com/riscv-non-isa/riscv-arch-test`
