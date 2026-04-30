# SnnDL `riscv_snn` Phase E Stimulus/Source Taxonomy Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `riscv_snn` 实验主线在 stimulus/source 维度上的边界继续写硬，明确“哪些入口属于 shared stimulus、哪些属于 legacy external egress、哪些属于纯 `snn` synthetic source、哪些未来必须新开 control-plane harness 接口”，避免实验线继续误继承纯 datapath 路径。

**Architecture:** 延续 Phase C 已有的“窄 helper、窄 hook、窄 contract”策略。保留 `workloadAllowsSnnStimulus()` 作为 shared ingress/stimulus helper；新增更窄 helper 收紧 legacy external egress；纯 `snn` synthetic source 继续由 `ISnnSpikeCommWorkload` 边界限定，不把 `WorkloadKind` 横向灌进更多核心类。文档、source-level contract test、最小 C++ helper test 一起收口。

**Tech Stack:** C++17、现有 SnnDL helper/header、source-level Python contract test、现有 `test_riscv_snn_stimulus_gating.cc`

---

## 0. 约束与 Phase E Exit Criteria

### 必守约束

1. `riscv_snn` 可以共享 stimulus，但不能因为这件事自动继承纯 `snn` datapath infrastructure。
2. 不把 `WorkloadKind` 继续穿透进更多无关类，只为冻结 taxonomy 而引入耦合。
3. 不把 `syntheticEmitNeuronFire*()` 直接开放给 `riscv_snn`。
4. 不用“把所有非 stream workload 都放开”这种粗 helper 回退现有边界。
5. 所有边界都必须有代码证据与测试证据，不能只写 README。

### Phase E Exit Criteria

1. `WorkloadConfig.h` 中能明确分辨：
   - shared SNN-style stimulus
   - legacy external spike egress
2. `sendExternalSpike()` 不再是对所有 workload 默认开放的灰色路径。
3. `syntheticEmitNeuronFire*()` 的“纯 `snn` datapath only” contract 在 source 和测试中都明确可见。
4. `services/stimulus/README.md` 与 `riscv_snn_isa_lab/README.md` 都有正式 taxonomy 表。
5. 至少有一组 source-level test 和一组 C++ helper test 同时守住这些边界。

## Task 1: 把 taxonomy 先写成正式 contract，再让测试先失败

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/WorkloadConfig.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_stimulus_gating.cc`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/stimulus/README.md`

**Step 1: 先写失败测试，冻结 helper surface**

在 `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_stimulus_gating.cc` 里增加新的 helper truth table 断言：

```c++
assert(workloadAllowsSnnStimulus(WorkloadKind::Snn));
assert(workloadAllowsSnnStimulus(WorkloadKind::RiscvSnn));

assert(workloadAllowsLegacyExternalSpikeEgress(WorkloadKind::Snn));
assert(!workloadAllowsLegacyExternalSpikeEgress(WorkloadKind::RiscvSnn));
assert(!workloadAllowsLegacyExternalSpikeEgress(WorkloadKind::Stream));
```

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 加 source contract 测试：

```python
def test_source_taxonomy_helpers_are_explicit_and_narrow(self) -> None:
    header = (riscv_snn_lab.REPO_ROOT / "sst_workspace" / "sst-elements" / "src" / "sst" / "elements" / "SnnDL" / "api" / "WorkloadConfig.h").read_text(encoding="utf-8")
    self.assertIn("workloadAllowsSnnStimulus", header)
    self.assertIn("workloadAllowsLegacyExternalSpikeEgress", header)
```

**Step 2: 跑测试，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
make test-riscv-snn-stimulus-gating
```

以及：

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_source_taxonomy_helpers_are_explicit_and_narrow \
  -v
```

Expected:

```text
FAIL: workloadAllowsLegacyExternalSpikeEgress missing
```

**Step 3: 在 `WorkloadConfig.h` 增加窄 egress helper**

推荐只增加一个新的 helper：

```c++
inline bool workloadAllowsLegacyExternalSpikeEgress(WorkloadKind k) {
    return k == WorkloadKind::Snn;
}
```

理由：

1. `workloadAllowsSnnStimulus()` 已经够用来表达 shared ingress/stimulus。
2. 当前真正灰色的是 `sendExternalSpike()` 这条 legacy egress。
3. 先把最危险的灰色路径写硬，不额外发明未来 helper。

**Step 4: 更新 `services/stimulus/README.md`，把 taxonomy 写明白**

增加一张小表，明确：

| surface | owned by | current allowed workloads | note |
|---|---|---|---|
| `StepActivationSubsystem` | stimulus ingress | `snn`, `riscv_snn` | shared SNN-style stimulus |
| `ExternalSpikeInputSubsystem` | stimulus ingress | `snn`, `riscv_snn` | local-only legacy ingress, no relay |
| `MultiCorePE::sendExternalSpike()` | legacy external egress | `snn` only | keep isolated from `riscv_snn` |
| `syntheticEmitNeuronFire*()` | pure `snn` synthetic source | `snn` only | guarded by `ISnnSpikeCommWorkload` contract |

**Step 5: 重新跑 helper tests**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
make test-riscv-snn-stimulus-gating
```

以及：

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_source_taxonomy_helpers_are_explicit_and_narrow \
  -v
```

Expected:

```text
OK
```

## Task 2: 收硬 `sendExternalSpike()` / legacy external egress 边界

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/components/MultiCorePE.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/api/WorkloadConfig.h`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`

**Step 1: 先写失败测试，固定 call-site contract**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加 source-level 测试，直接守住 `sendExternalSpike()`：

```python
def test_send_external_spike_is_gated_by_legacy_egress_helper(self) -> None:
    source = (
        riscv_snn_lab.REPO_ROOT
        / "sst_workspace"
        / "sst-elements"
        / "src"
        / "sst"
        / "elements"
        / "SnnDL"
        / "components"
        / "MultiCorePE.cc"
    ).read_text(encoding="utf-8")
    self.assertIn("workloadAllowsLegacyExternalSpikeEgress", source)
    self.assertIn("void MultiCorePE::sendExternalSpike", source)
```

**Step 2: 跑测试，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_send_external_spike_is_gated_by_legacy_egress_helper \
  -v
```

Expected:

```text
FAIL
```

**Step 3: 在 `MultiCorePE::sendExternalSpike()` 增加最小 gate**

目标是只收硬 legacy egress，不碰其它 stimulus path。建议最小改法：

```c++
void MultiCorePE::sendExternalSpike(SpikeEvent* spike) {
    if (!spike) return;
    if (!workloadAllowsLegacyExternalSpikeEgress(cfg_.workload_kind)) {
        delete spike;
        return;
    }
    spike_packet_bridge_.sendExternal(spike);
}
```

如果当前函数拿不到 `cfg_.workload_kind`，允许在 `MultiCorePE` 内新增一个只读成员缓存，但不要继续向更深层对象传播。

**Step 4: 检查 test-traffic 分支，避免误把实验流量口子当成 `riscv_snn` 主功能**

重点审视：

- `MultiCorePE.cc` 中调用 `sendExternalSpike(test_spike);` 的测试流量分支

要求：

1. 这条分支在 `riscv_snn` 下默认不要成为新 datapath 能力；
2. 若保留给 `snn` / traffic harness，用注释明确“legacy/test path only”；
3. 不要为兼容它而放宽 `riscv_snn` 边界。

**Step 5: 重新跑 source contract test**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_send_external_spike_is_gated_by_legacy_egress_helper \
  -v
```

Expected:

```text
OK
```

## Task 3: 冻结纯 `snn` synthetic source contract，而不是把它开放给 `riscv_snn`

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.cc`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/control/SnnPESubComponent.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnWorkload.h`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.h`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/README.md`

**Step 1: 先写 source-level contract test**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加：

```python
def test_synthetic_source_contract_stays_on_snn_workload_only(self) -> None:
    riscv_header = (
        riscv_snn_lab.REPO_ROOT
        / "sst_workspace"
        / "sst-elements"
        / "src"
        / "sst"
        / "elements"
        / "SnnDL"
        / "services"
        / "workload"
        / "riscv_snn"
        / "RiscvSnnWorkload.h"
    ).read_text(encoding="utf-8")
    snn_header = (
        riscv_snn_lab.REPO_ROOT
        / "sst_workspace"
        / "sst-elements"
        / "src"
        / "sst"
        / "elements"
        / "SnnDL"
        / "services"
        / "workload"
        / "snn"
        / "SnnWorkload.h"
    ).read_text(encoding="utf-8")
    pe_source = (
        riscv_snn_lab.REPO_ROOT
        / "sst_workspace"
        / "sst-elements"
        / "src"
        / "sst"
        / "elements"
        / "SnnDL"
        / "control"
        / "SnnPESubComponent.cc"
    ).read_text(encoding="utf-8")

    self.assertNotIn("ISnnSpikeCommWorkload", riscv_header)
    self.assertIn("public ISnnSpikeCommWorkload", snn_header)
    self.assertIn("if (!snn_comm_workload_ || !snn_comm_workload_->ready()) return false;", pe_source)
```

这条测试现在大概率已经部分为绿，但先把它正式纳入回归面。

**Step 2: 补显式注释，让“当前故意不开放”变成可读 contract**

在以下位置加简洁注释：

1. `SnnPESubComponent::syntheticEmitNeuronFire()`
2. `SnnPESubComponent::syntheticEmitNeuronFireBatch()`
3. `RiscvSnnWorkload.h`

注释要明确表达：

1. `syntheticEmitNeuronFire*()` 属于纯 `snn` spike-comm datapath contract；
2. `riscv_snn` 当前不实现 `ISnnSpikeCommWorkload`；
3. 若未来需要 control-plane synthetic source，必须新增专用 harness/interface，而不是复用这里。

**Step 3: 在 lab README 里增加“未来不该怎么做”**

在 `riscv_snn_isa_lab/README.md` 增加一段明确口径：

1. 不要让 `riscv_snn` 通过实现 `ISnnSpikeCommWorkload` 来偷吃纯 `snn` synthetic source；
2. 如果后续实验真的需要 synthetic source，新增 `riscv_snn` 专属 harness API；
3. 该 API 必须留在实验目录或 `services/workload/riscv_snn` 边界里，不能污染 `snn` 主线。

**Step 4: 跑 source contract test**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_synthetic_source_contract_stays_on_snn_workload_only \
  -v
```

Expected:

```text
OK
```

## Task 4: 把 taxonomy 变成“代码 + 文档 + regression”三层闭环

**Files:**
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_stimulus_gating.cc`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/stimulus/README.md`
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `TECH_PROGRESS.md`

**Step 1: 补一个 lab-side taxonomy regression group**

把前面三条 source contract test 归在一个清晰的小组名下，至少包含：

1. helper surface
2. legacy external egress helper usage
3. synthetic source ownership

**Step 2: 跑 Python regression**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
```

Expected:

```text
OK
```

**Step 3: 跑 C++ helper regression**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
make test-riscv-snn-stimulus-gating
```

Expected:

```text
通过
```

**Step 4: 做一次完整编译，防止 helper 改动破坏 SnnDL**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
make -j4 && \
make install
```

Expected:

```text
编译和安装通过
```

**Step 5: 刷新文档**

必须同步写回：

1. `services/stimulus/README.md`
2. `riscv_snn_isa_lab/README.md`
3. `TECH_PROGRESS.md`

文档里要明确写出：

1. `riscv_snn` 允许哪些 stimulus ingress；
2. `riscv_snn` 不允许哪些 legacy external egress/source；
3. 未来若要扩 synthetic source，应该加在哪一层。

## 执行顺序建议

1. Task 1: taxonomy helper surface
2. Task 2: `sendExternalSpike()` egress gate
3. Task 3: pure `snn` synthetic source contract
4. Task 4: full regression + docs

## 风险提示

1. 不要为了测试流量或 legacy path 把 `riscv_snn` 放进 `sendExternalSpike()` 的 allowlist。
2. 不要因为想“以后可能有用”就先把 `riscv_snn` 接到 `ISnnSpikeCommWorkload`。
3. 不要把 taxonomy 写成过粗的 “SNN-like workload” 分类；Phase E 反而要更窄。
4. 如果发现某条路径既像 stimulus 又像 datapath，优先先写文档/测试冻结语义，再决定是否开 helper。

