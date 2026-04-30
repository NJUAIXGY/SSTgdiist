# SnnDL `riscv_snn` Phase C Backend Runtime Integration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在保持 `riscv_snn` 实验主线严格隔离的前提下，把 Phase B 已冻结的 control-plane/runtime contract 接到一个可研究、可验证、可回归的真实 backend runtime bridge 上，让 `workload_impl=riscv_snn` 第一次具备“驱动真实 SNN 数据面并与默认 `snn` 做受控对齐”的能力。

**Architecture:** Phase C 不继续扩张新的 CSR/样例 authority，也不把实验逻辑塞回默认 `snn` 主路径。它的核心是新增一个窄接口 `ISnnAccelRuntimeServices`，由平台/PE 壳以可选方式提供；`riscv_snn` 侧新增 `RiscvSnnRuntimeBridgeBackend`，只通过这层抽象把 `FUSED_STEP`、barrier、fault、ingress packet 和 stats 映射到真实运行时。`RiscvSnnWorkload` 继续只做 control-plane，默认 `snn` 行为保持不变。

**Tech Stack:** C++17 (`SnnDL` workload/runtime/provider/tests)、Python 3 (`riscv_snn_isa_lab` wrapper + `unittest`)、`sst_dram_si` spec-first runner、mesh smoke/equivalence replay、markdown docs under `docs/plans/nextarc/`.

**Repo Policy Note:** 本计划刻意不包含任何 `git commit/push/reset` 步骤；仓库策略要求这类操作必须在主人明确批准后再执行。

**Isolation Note:** Phase C 只允许在下面这些边界内增加实验性代码或可选 hook：
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/common/`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api/`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_*.cc`
- `/home/xgy/remote/riscv_snn_isa_lab/`
- `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`

任何 hook 都必须满足：
1. 默认 `workload_impl=snn` 不改变行为。
2. 未启用 `riscv_snn` bridge 时，新增 provider 指针必须可以为 `nullptr`。
3. 不新增第二份 program/spec metadata authority。

---

## 0. 当前起点与 Phase C 真正要补的缺口

Phase B 已经完成并冻结的面：

1. `msnnfault clear / re-fault / overwrite` 语义。
2. `msnneventen / msnneventpend / wfi` 的 pending、enable、wake 关系。
3. architecture-visible event 与 recommended delivery cause 的分层。
4. `FUSED_STEP` 的强 completion boundary。
5. builder/toolchain bridge/reference/nightly sidecar 的实验编排证据面。

但当前还没有真正进入“ISA 级可研究 runtime”的部分：

1. `SnnAccelBackend` 仍主要是 null/contract backend。
2. `RiscvSnnWorkload` 还没有通过真实 runtime 服务驱动现有 SNN 数据面。
3. `RiscvSnnWorkload <-> backend <-> PE runtime` 的 timing contract 还没有在代码层完全冻结。
4. 还没有一组正式的 `snn` vs `riscv_snn(runtime_bridge)` 等价性 smoke。

因此，Phase C 的重点不是继续扩样例，而是把“已经冻结好的协议”接到“真实 runtime bridge”上。

## 1. Phase C Exit Criteria

1. `ISnnAccelRuntimeServices` 或等价窄接口完成冻结，并且默认路径可选、可为空。
2. `riscv_snn_backend_name=runtime_bridge` 能让 `RiscvSnnWorkload` 提交至少一种真实命令：
   - `FUSED_STEP`
3. command accept、completion publish、fault visible、barrier release、wake 条件在代码和测试里都能对齐到同一状态机。
4. 存在一组固定的实验 compare surface，至少比较：
   - step 完成数
   - completion/status/fault 行为
   - `essential_summary_mesh.json` 的关键 contract 字段
   - 高频统计的高层一致性（而不是逐字段强行 bit-identical）
5. 所有新增实现仍然只落在实验路径或可选 hook，不把默认 `snn` 变成 `riscv_snn` 的隐式依赖。

## 2. 分阶段执行顺序

### Phase C1: Timing Contract Hardening

目标：

- 把 `submit/accept/execute/complete/fault` 的真实运行时边界写成代码内 contract。

退出标准：

1. 有独立 `backend timing` 协议测试。
2. 有正式状态机枚举与相应文档措辞。

### Phase C2: Runtime Service Provider

目标：

- 让 PE/runtime 通过一层窄 provider 暴露实验 bridge 所需的最小服务，而不是让 `riscv_snn` 直接依赖 `SnnPESubComponent` 内部实现。

退出标准：

1. provider 是抽象接口。
2. `Runtime` 上只新增可选、默认空指针的服务入口。

### Phase C3: Real Bridge Backend

目标：

- 用 `RiscvSnnRuntimeBridgeBackend` 把 `FUSED_STEP` 绑定到真实数据面。

退出标准：

1. `null` backend 与 `runtime_bridge` backend 可切换。
2. unsupported command/fault 语义仍然走已冻结的 Phase B contract。

### Phase C4: Equivalence Harness

目标：

- 形成 `snn` 与 `riscv_snn(runtime_bridge)` 的固定 compare surface。

退出标准：

1. 有固定 spec/manifest。
2. 有 wrapper/README/TECH_PROGRESS 能复现该 compare。

---

## 3. Task 1: 冻结 backend timing contract 与状态机

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/common/SnnAccelBackendContract.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/common/SnnAccelBackend.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/common/SnnAccelBackend.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnWorkload.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_queue_contract.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_firmware_protocol.cc`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_backend_timing_contract.cc`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`

**Step 1: 先写 timing 红灯测试**

新增最小协议红测，至少覆盖：

1. `submitCommand()` 只表示 command 对 backend eventually visible，而不是立即 completed。
2. `Accepted` 的唯一架构边界仍然是 `cmdq_head` 越过该 command。
3. completion 的发布顺序必须明确为：
   - completion payload
   - `cmpq_tail`
   - `msnnstep/msnnfault` visible update
   - `msnneventpend`
   - `wfi` wake eligibility
4. `FUSED_STEP` 的 runtime state machine 必须可观测：
   - `Idle -> Accepted -> Executing -> OutboundDraining -> BarrierWaiting -> Completed/Faulted`

**Step 2: 把状态机抽成正式 contract**

在 `SnnAccelBackendContract.h` 中集中表达：

1. backend phase enum
2. completion boundary helper
3. doorbell/ownership/order helper
4. `FUSED_STEP` strong boundary 与 `RX debug-only` 辅助判定

**Step 3: 最小实现只收紧 contract，不做 bridge**

此任务不直接接真实数据面，只把 null backend 和 `RiscvSnnWorkload` 的语义表达收紧到 Phase C 需要的粒度。

**Step 4: 回写设计文档**

在 ISA 设计稿中补出一节正式 wording：

- backend timing contract
- completion visibility order
- `FUSED_STEP completion` 的 runtime state meaning

**Verification:**

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -DHAVE_CONFIG_H -I. -I../../../../src -I./api -I./events -I./components -I./control -I./compute -I./services \
  ./tests/test_riscv_snn_backend_timing_contract.cc \
  ./services/workload/common/SnnAccelBackend.cc \
  ./services/workload/riscv_snn/RiscvSnnHart.cc \
  ./services/workload/riscv_snn/RiscvSnnIss.cc \
  -o /tmp/test_riscv_snn_backend_timing_contract && /tmp/test_riscv_snn_backend_timing_contract

cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-riscv-snn-protocols
```

Expected:

1. 新 timing contract 红测在实现前确实失败。
2. 绿灯后 `test-riscv-snn-protocols` 仍通过。

---

## 4. Task 2: 新增实验性 runtime service provider，隔离 `riscv_snn` 对平台壳的依赖

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ISnnAccelRuntimeServices.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ICoreWorkload.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_runtime_service_provider.cc`

**Step 1: 先写 provider 红灯测试**

红测至少覆盖：

1. `Runtime` 新增 provider 入口默认可为空。
2. 默认 `workload_impl=snn` 不需要也不会主动访问该 provider。
3. `riscv_snn` 若请求 `runtime_bridge` backend 而 provider 为空，必须显式 fault 或明确拒绝，而不是静默回退。

**Step 2: 设计 provider 的最小职责**

建议 provider 只暴露 Phase C 真正需要的最小面：

1. `submitFusedStep(...)`
2. `pollFusedStep(...)`
3. `injectIngressPacket(...)`
4. `snapshotRuntimeStats(...)`
5. 可选 `currentGlobalStepSeq()` / `barrierState()`

不要让 provider 直接暴露：

1. 具体 `SnnPESubComponent` 私有成员
2. 任意 compute core 裸指针
3. 过宽的“万能调试”接口

**Step 3: 把 provider 作为可选 runtime hook 接入**

在 `ICoreWorkload::Runtime` 上新增一个可选指针或等价 handle，默认值必须是 `nullptr`。

**Step 4: 在平台壳中只做装配，不做语义扩张**

`SnnPESubComponent` 只负责把自己的实验服务面装配进 runtime，不在这一步引入 `riscv_snn` 语义分支。

**Verification:**

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -DHAVE_CONFIG_H -I. -I../../../../src -I./api -I./events -I./components -I./control -I./compute -I./services \
  ./tests/test_riscv_snn_runtime_service_provider.cc \
  ./control/SnnPESubComponent.cc \
  -o /tmp/test_riscv_snn_runtime_service_provider && /tmp/test_riscv_snn_runtime_service_provider

cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile
```

Expected:

1. provider 可选性有单测保护。
2. `make test-compile` 继续通过。

---

## 5. Task 3: 实现 `RiscvSnnRuntimeBridgeBackend`

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.h`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/common/SnnAccelBackend.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnWorkload.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnWorkload.cc`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_runtime_bridge_backend.cc`

**Step 1: 先写 bridge backend 红灯测试**

至少覆盖：

1. `backend_name=null` 与 `backend_name=runtime_bridge` 的选择逻辑。
2. `runtime_bridge` 依赖 provider 存在。
3. `submitCommand(FUSED_STEP)` 进入 accepted/runtime phase，而不是立即本地完成。
4. unsupported opcode 仍按 Phase B fault 语义返回。

**Step 2: 只把 `runtime_bridge` 做成实验性 backend**

bridge backend 必须放在 `services/workload/riscv_snn/` 目录下，避免让默认 `snn` 反向依赖实验实现。

**Step 3: 保持 `RiscvSnnWorkload` 只做 control-plane**

`RiscvSnnWorkload` 只负责：

1. 读取 ring/CSR
2. 调 `submitCommand`
3. drain completion
4. raise event / wake firmware

不要把真实 gather/apply/scatter 再搬回 workload 本体。

**Step 4: 补齐 stats/fault 透传**

bridge backend 需要把 provider/runtime 层的关键状态投影回：

1. `readArchitecturalStepState()`
2. `snapshotStats()`
3. completion `status_code / aux0 / aux1`

**Verification:**

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -DHAVE_CONFIG_H -I. -I../../../../src -I./api -I./events -I./components -I./control -I./compute -I./services \
  ./tests/test_riscv_snn_runtime_bridge_backend.cc \
  ./services/workload/common/SnnAccelBackend.cc \
  ./services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.cc \
  ./services/workload/riscv_snn/RiscvSnnHart.cc \
  ./services/workload/riscv_snn/RiscvSnnIss.cc \
  -o /tmp/test_riscv_snn_runtime_bridge_backend && /tmp/test_riscv_snn_runtime_bridge_backend

cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-riscv-snn-protocols
```

Expected:

1. `runtime_bridge` backend 行为被独立单测锁住。
2. 原有协议测试仍通过。

---

## 6. Task 4: 把 `FUSED_STEP` 映射到真实数据面 micro-protocol

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ISnnAccelRuntimeServices.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnRuntimeBridgeBackend.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_backend_timing_contract.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_runtime_bridge_backend.cc`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`

**Step 1: 明确 real runtime 的最小命令映射**

Phase C 只要求一条稳定命令真正落地：

1. `FUSED_STEP`

并冻结它的真实 runtime 语义：

1. provider 接收 step 请求
2. 数据面执行 gather/apply/scatter
3. outbound drain 与 barrier wait 按 contract 可观测
4. 完成后返回 completion/fault snapshot

**Step 2: 不让 RX debug 污染主路径**

即使 runtime bridge 接上真实数据面，也必须继续保持：

1. RX software-visible ring 是 debug-only
2. `FUSED_STEP` completion 不依赖软件消费 RX debug

**Step 3: 明确 fault 传播边界**

至少区分：

1. submit 前本地 reject
2. accepted 后 runtime fault
3. barrier/release 前失败

并统一映射回已冻结的 Phase B `msnnfault/completion` 语义。

**Step 4: 回写正式 wording**

在设计稿补上：

`FUSED_STEP completion occurs iff the runtime bridge has committed the architectural step boundary defined by the provider contract; RX debug visibility is not part of this boundary.`

**Verification:**

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-riscv-snn-protocols
```

Expected:

1. `FUSED_STEP` 与 real runtime 的关系有正式测试。
2. Phase B 已有 fault/wfi/cause 测试不回退。

---

## 7. Task 5: 新增实验 compare harness，固定 `snn` vs `riscv_snn(runtime_bridge)` 对齐面

**Files:**
- Create: `/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_runtime_bridge.json`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_snn_baseline.json`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/README.md`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/notes/phase-c-runtime-equivalence.md`

**Step 1: 先定义 compare surface**

Phase C 不追求 bit-identical 全字段比较，先固定下面这层：

1. step 完成数 / completion 个数
2. `msnnfault` 与 completion status
3. `essential_summary_mesh.json` 中的 contract 字段
4. `memory_requests / memory_bytes / tx/rx packets` 这类高层统计

**Step 2: wrapper 新增一条 compare 命令**

建议新增：

1. `equiv --family external_dyn_desc_ref`

它做的事应当是：

1. 生成或读取固定 pair spec
2. 分别跑 `snn` baseline 与 `riscv_snn(runtime_bridge)`
3. 输出 dated compare summary，不新增第二份 authority

**Step 3: 生成可登记的 compare note**

`notes/phase-c-runtime-equivalence.md` 只记录：

1. compare scope
2. 当前允许的偏差
3. 何时算 PASS / WARN / FAIL

**Verification:**

```bash
cd "/home/xgy/remote" && python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

cd "/home/xgy/remote" && python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family external_dyn_desc_ref
```

Expected:

1. wrapper 单测通过。
2. compare summary 有固定输出路径。

---

## 8. Task 6: 收口文档、实验记录与 next gate

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/README.md`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`

**Step 1: append 进度，不重写历史**

必须记录：

1. 哪个 backend 在跑
2. compare scope 是什么
3. 哪些字段是 strict、哪些只是 research-level trend

**Step 2: README 增加 runtime bridge 导航**

至少补：

1. null backend vs runtime bridge 区别
2. provider/runtime hook 是可选的
3. compare harness 怎么跑

**Step 3: 只把 gate 放在实验 sidecar**

如果 runtime bridge 稳定，再考虑把 compare harness 增补到：

1. `riscv_snn_isa_lab/ci/nightly_sidecar.py`

但这一步只能作为 Phase C 尾声或 D 的入口，不能先改 repo-level CI。

---

## 9. Verification Checklist

**Commands:**
- `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-riscv-snn-protocols`
- `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile`
- `cd "/home/xgy/remote" && python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v`
- `cd "/home/xgy/remote" && python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" validate --program external_dyn_desc_ref_toolchain`
- `cd "/home/xgy/remote" && python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family external_dyn_desc_ref`

**Expected evidence:**
- protocol/compile 测试持续通过，说明 Phase B 语义没有在 bridge 接入时回退。
- `runtime_bridge` backend 能在 provider 存在时运行，在 provider 缺失时显式拒绝。
- compare harness 能生成固定 summary，并把 `snn` 与 `riscv_snn(runtime_bridge)` 的对齐范围写清楚。
- 所有新增文档与实验记录仍然只长在实验主线，不污染默认主路径。
