# SnnDL `riscv_snn` Phase B Runtime Contract Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在保持 `riscv_snn` 实验主线严格隔离的前提下，把 v1.1 运行时 contract 细化到可直接实现和验证的程度，重点冻结 `msnnfault` 生命周期、`msnneventpend/wfi` 语义、cause 与 delivery 的分层，以及 `FUSED_STEP` completion 的强边界。

**Architecture:** Phase B 不扩新 ISA 面，也不把实验逻辑耦回默认 `snn` 路径；它只收紧 `services/workload/riscv_snn/`、相关协议测试、toolchain bridge reference、以及 `riscv_snn_isa_lab/` 的实验 wrapper/documentation。所有 runtime contract 必须先在协议测试和 lab 参考面冻结，再考虑更深的 backend/runtime 接入。

**Tech Stack:** C++17 (`SnnDL` workload/protocol tests), Python 3 (`riscv_snn_isa_lab` wrapper + unittest), bare-metal RISC-V toolchain bridge, markdown spec docs under `docs/plans/nextarc/`.

---

## Scope Guardrails

- 只修改实验性 `riscv_snn` 路径：
  - `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/`
  - `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_*.cc`
  - `/home/xgy/remote/riscv_snn_isa_lab/`
  - `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`
- 不修改默认 `snn` workload 行为。
- 不把实验 gate 接回 repo-level CI。
- 不引入第二份 sample metadata authority。
- `RX debug` 继续保持 debug-only，不进入主执行闭环。

## Exit Criteria

1. `msnnfault clear -> re-fault -> overwrite` 的 contract 在 builder/toolchain/reference 三层行为一致。
2. `msnneventen/msnneventpend/wfi` 的 enable、pending、W1C、wake 条件有明确协议测试与文档语义。
3. cause 与 delivery 分层成两层 contract：
   - architecture-visible event reasons
   - implementation delivery mechanism
4. `FUSED_STEP completion` 的强 boundary 与 fault/event contract 没有冲突，并有对齐测试。
5. 以上变更都只落在实验路径，不污染默认主线。

### Task 1: Freeze `msnnfault` Lifecycle Contract

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnAbi.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnQueueContract.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_abi.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_queue_contract.cc`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`

**Step 1: Write the failing tests**

新增三类最小失败测试：

- `fault clear only clears VALID and not committed completion payload`
- `new post-clear fault overwrites msnnfault with latest accepted fault`
- `overwrite-chain keeps latest fault architecturally visible while prior completions stay immutable`

**Step 2: Run test to verify it fails**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -DHAVE_CONFIG_H -I. -I../../../../src -I./api -I./events -I./components -I./control -I./compute -I./services \
  ./tests/test_riscv_snn_abi.cc \
  -o /tmp/test_riscv_snn_abi.phaseb.red && /tmp/test_riscv_snn_abi.phaseb.red
```

Expected: FAIL because `msnnfault` clear/overwrite semantics are not yet frozen in code.

**Step 3: Write minimal implementation**

- 在 ABI/queue contract 中明确：
  - `FAULT_VALID` 仅表示“存在未确认的新 fault”
  - `msnnfault` W1C/ack 只清 valid，不回滚历史 completion
  - 新 fault 到达后可以覆盖 `msnnfault` 当前可见值
  - completion `aux0/aux1` 仍绑定 fault 退休瞬间的快照

**Step 4: Run test to verify it passes**

Run the same compile/run command again and confirm exit code `0`.

**Step 5: Update spec wording**

在 ISA 设计文档中增加一句不可歧义的话：

`Clearing msnnfault acknowledges the currently visible fault record only; it does not mutate already-retired completion payloads, and a later accepted fault may overwrite the visible msnnfault state.`

### Task 2: Mirror Fault Lifecycle into Reference and Toolchain Bridge

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_firmware_protocol.cc`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_rearm_ref_toolchain/main.S`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_overwrite_chain_ref_toolchain/main.S`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/README.md`

**Step 1: Write the failing test**

补一条 Python/C++ 双侧红测，要求：

- builder reference 与 toolchain bridge 都显式覆盖
  - clear then re-fault
  - overwrite-chain
- 对齐面至少包含：
  - latest visible `msnnfault`
  - completion `status_code`
  - completion `aux0/aux1`

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
```

Expected: FAIL because bridge side还没有完整表达 nested/overwrite fault freeze 语义。

**Step 3: Write minimal implementation**

- 只调整实验 reference/toolchain bridge 资产，不扩全局 sample authority。
- 把 clear/re-fault/overwrite 的预期值收进已有 lab-local spec/README 证据面。

**Step 4: Run test to verify it passes**

Run the same unittest command again and confirm new tests pass.

**Step 5: Refresh experimental evidence**

Run:

```bash
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" matrix --group toolchain --register
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" audit --group toolchain --protocol
```

Expected: summary 仍只写入 `riscv_snn_isa_lab/references/`，不引入新 authority。

### Task 3: Freeze `msnneventen` / `msnneventpend` / `wfi` Semantics

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnHart.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnHart.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnIss.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_firmware_protocol.cc`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`

**Step 1: Write the failing tests**

新增最小协议红测：

- pending bit set even when event disabled
- `wfi` only wakes when `(pending & enable) != 0`
- W1C clears pending but does not retroactively cancel retired completion/fault artifacts

**Step 2: Run test to verify it fails**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -DHAVE_CONFIG_H -I. -I../../../../src -I./api -I./events -I./components -I./control -I./compute -I./services \
  ./tests/test_riscv_snn_firmware_protocol.cc \
  ./services/workload/riscv_snn/RiscvSnnFirmwareLoader.cc \
  ./services/workload/riscv_snn/RiscvSnnIss.cc \
  ./services/workload/riscv_snn/RiscvSnnHart.cc \
  -o /tmp/test_riscv_snn_firmware_protocol.phaseb.red && /tmp/test_riscv_snn_firmware_protocol.phaseb.red
```

Expected: FAIL because event pending and wake semantics are not yet fully encoded.

**Step 3: Write minimal implementation**

- 明确 `pending` 与 `delivery` 是两层概念。
- `disabled event` 仍进入 `msnneventpend`。
- `wfi` 只依赖 `pending & enable` 的 architecture-visible 结果。

**Step 4: Run test to verify it passes**

Run the same command again and confirm exit code `0`.

**Step 5: Update documentation**

在 ISA 设计文档补充：

- pending set order
- W1C order
- wake condition
- `completion payload write -> cmpq_tail update -> event pending -> wakeup` 的先后关系

### Task 4: Separate Architecture Causes from Delivery Mechanism

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnAbi.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_abi.cc`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`

**Step 1: Write the failing test**

新增红测，要求：

- architecture-visible event reason enum 单独存在
- local interrupt / external interrupt / simulator callback 映射是单独层
- cause number 变动不改变 architecture event meaning

**Step 2: Run test to verify it fails**

Run the same `test_riscv_snn_abi.cc` command from Task 1.

Expected: FAIL because cause/delivery 仍然耦在同一层表达里。

**Step 3: Write minimal implementation**

- 在 ABI 中拆成：
  - `RiscvSnnArchEvent`
  - `RiscvSnnDeliveryCause` 或等价局部映射
- 文档里把 cause 编号改成“recommended mapping”，不是首要冻结对象。

**Step 4: Run test to verify it passes**

Re-run the ABI test binary and confirm exit code `0`.

**Step 5: Verify no default-path coupling**

检查只变更 `riscv_snn` 试验路径；不要改默认 `snn` 的 trap/interrupt 行为。

### Task 5: Reconfirm `FUSED_STEP` Strong Completion and RX Debug-Only Boundary

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_queue_contract.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_firmware_protocol.cc`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/README.md`

**Step 1: Write the failing test**

最小红测需要证明：

- `FUSED_STEP completion` 不依赖 RX debug software consumption
- RX debug ring 可以为空/禁用而主路径仍正确退休
- completion 对应的 step boundary 仍然是强 commit boundary

**Step 2: Run test to verify it fails**

Run both targeted binaries:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -DHAVE_CONFIG_H -I. -I../../../../src -I./api -I./events -I./components -I./control -I./compute -I./services \
  ./tests/test_riscv_snn_queue_contract.cc \
  -o /tmp/test_riscv_snn_queue_contract.phaseb.red && /tmp/test_riscv_snn_queue_contract.phaseb.red
```

Expected: FAIL because debug-only and strong completion boundaries are not fully locked together.

**Step 3: Write minimal implementation**

- 继续把 RX ring 限制为 summary/debug sideband。
- completion boundary 只绑定 architectural commit，不绑定 software `RX_DEBUG_POP`。

**Step 4: Run test to verify it passes**

Run the same queue-contract command again and confirm exit code `0`.

**Step 5: Refresh wording in docs**

在 README 和 ISA design 中同时强调：

- `incoming spike` 仍不进入 software handler 主路径
- `RX_DEBUG_POP` 不是主执行闭环的一环

### Task 6: Rebuild Experimental Lab Evidence Without Polluting Global CI

**Files:**
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/README.md`
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: Write the failing test**

新增 lab-level 红测，要求 nightly/history/sidecar 对新的 Phase B contract evidence 有稳定摘要，但不扩成第二 authority。

**Step 2: Run test to verify it fails**

Run:

```bash
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
```

Expected: FAIL because Phase B evidence fields and docs/summary 尚未接线。

**Step 3: Write minimal implementation**

- 只在 `riscv_snn_isa_lab/` 下扩展 wrapper/readme/summary。
- 不新增 repo-level workflow，不改默认 regression 入口。

**Step 4: Run test to verify it passes**

Run the same unittest command again and confirm exit code `0`.

**Step 5: Refresh stable artifacts**

Run:

```bash
python3 "/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py"
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" history
```

Expected:

- `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
- `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-summary.md`
- `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-history-index.json`

都更新成功，且只落在实验目录。

## Verification Checklist

- `python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v`
- `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile V=1`
- targeted protocol binaries for:
  - `test_riscv_snn_abi.cc`
  - `test_riscv_snn_queue_contract.cc`
  - `test_riscv_snn_firmware_protocol.cc`
- `python3 "/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py"`
- `python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" history`

## Risks To Watch

- 把 `pending` 和 trap delivery 混为一谈，导致后面 AIA/local interrupt 映射难以演进。
- 让 `RX_DEBUG_POP` 意外参与主路径，重新把 control plane 做胖。
- 让 `msnnfault clear` 反向影响已退休 completion，破坏调试可追溯性。
- 为了验证方便把实验 contract 蔓延回默认 `snn` 路径。

## Recommended Execution Order

1. Task 1
2. Task 3
3. Task 4
4. Task 5
5. Task 2
6. Task 6

这样先冻结最容易分叉的 runtime contract，再回填 reference/toolchain/lab 证据面。
