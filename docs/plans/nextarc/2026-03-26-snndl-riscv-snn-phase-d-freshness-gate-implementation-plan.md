# SnnDL `riscv_snn` Phase D Freshness Gate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `riscv_snn` 的 freshness gate 从“只有 `external_dyn_desc_ref` 一条 fresh PASS family”扩展成“success / accepted-fault / bad-policy / clear-then-refault / overwrite-chain 五条 builder reference 都可 fresh 跑通，并把 toolchain bridge freshness 收进同一份派生 gate 证据里”。

**Architecture:** 继续复用现有 `riscv_snn_isa_lab` 资产，不新建第二份 metadata authority。`builder sample`、`toolchain bridge source`、`spec-first JSON`、`mesh smoke artifact` 仍各自保持 source of truth；`riscv_snn_lab.py` 只负责派生 orchestrator、summary 聚合和 gate 解释。所有新能力继续放在实验目录和 lab wrapper 内，不改默认 `snn` 主路径。

**Tech Stack:** Python 3、`unittest`、JSON spec-first config、SST-SnnDL mesh runner、`riscv_snn_lab.py`、`nightly_sidecar.py`

---

## 0. 约束与退出标准

### 必守约束

1. 不把 `riscv_snn` 重新做成 `CoreShell` / compute core 扩展。
2. 不引入第二份 sample metadata authority。
3. 不把 numeric fault payload / descriptor 常量再抄一份到 lab wrapper。
4. 不改默认 `snn` / `stream` / `traffic` 主流程语义。
5. 所有新增 gate 都必须是显式 experimental CLI，不得静默改变默认验证口径。

### Phase D Exit Criteria

1. `EQUIV_FAMILY_SPECS` 覆盖五条 builder reference family。
2. 五条 family 都有明确的 `snn_baseline` / `runtime_bridge` pair spec。
3. `riscv_snn_lab.py equiv --family <family>` 能对五条 family 产出 dated summary。
4. `equiv` summary 对 fault / policy family 的 gate 理由是 family-aware 的，而不是一律套 success path。
5. 顶层 fresh gate 至少能在一个 dated summary/report 中同时指出：
   - builder/runtime equivalence 状态
   - toolchain bridge matrix/audit 状态
   - 哪条 family freshness 失败、为什么失败

## Task 1: 冻结五条 equivalence family surface 与 pair spec

**Files:**
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Create: `riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref_snn_baseline.json`
- Create: `riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref_runtime_bridge.json`
- Create: `riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref_snn_baseline.json`
- Create: `riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref_runtime_bridge.json`
- Create: `riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_snn_baseline.json`
- Create: `riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_runtime_bridge.json`
- Create: `riscv_snn_isa_lab/specs/external_dyn_desc_fault_overwrite_chain_ref_snn_baseline.json`
- Create: `riscv_snn_isa_lab/specs/external_dyn_desc_fault_overwrite_chain_ref_runtime_bridge.json`

**Step 1: 先写失败测试，冻结 family surface**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加一条新测试，先把五条 family 的 surface 写死：

```python
def test_equiv_family_surface_freezes_fault_lifecycle_pairs(self) -> None:
    expected = {
        "external_dyn_desc_ref": {
            "snn_baseline": "external_dyn_desc_ref_snn_baseline.json",
            "runtime_bridge": "external_dyn_desc_ref_runtime_bridge.json",
        },
        "external_dyn_desc_fault_ref": {
            "snn_baseline": "external_dyn_desc_fault_ref_snn_baseline.json",
            "runtime_bridge": "external_dyn_desc_fault_ref_runtime_bridge.json",
        },
        "external_dyn_desc_bad_policy_ref": {
            "snn_baseline": "external_dyn_desc_bad_policy_ref_snn_baseline.json",
            "runtime_bridge": "external_dyn_desc_bad_policy_ref_runtime_bridge.json",
        },
        "external_dyn_desc_fault_rearm_ref": {
            "snn_baseline": "external_dyn_desc_fault_rearm_ref_snn_baseline.json",
            "runtime_bridge": "external_dyn_desc_fault_rearm_ref_runtime_bridge.json",
        },
        "external_dyn_desc_fault_overwrite_chain_ref": {
            "snn_baseline": "external_dyn_desc_fault_overwrite_chain_ref_snn_baseline.json",
            "runtime_bridge": "external_dyn_desc_fault_overwrite_chain_ref_runtime_bridge.json",
        },
    }

    self.assertEqual(riscv_snn_lab.EQUIV_FAMILY_SPECS, expected)
    for pair in expected.values():
        for relpath in pair.values():
            self.assertTrue((riscv_snn_lab.LAB_ROOT / "specs" / relpath).exists(), msg=relpath)
```

**Step 2: 跑测试，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_equiv_family_surface_freezes_fault_lifecycle_pairs \
  -v
```

Expected:

```text
FAIL: only external_dyn_desc_ref exists in EQUIV_FAMILY_SPECS
```

**Step 3: 最小实现 spec pair，不新增生成器 authority**

直接手写八个小 JSON 文件，不新增模板引擎。每个 baseline/runtime pair 都沿用当前 `external_dyn_desc_ref_*` 的壳，只改 family 名和 runtime ELF 路径。

`*_snn_baseline.json` 统一形状：

```json
{
  "schema_version": 3,
  "platform": {
    "mesh_size": 4,
    "exec_mode": "gas",
    "stop": { "mode": "time", "simulation_time": "1us" },
    "flags": { "enable_node_summary": true }
  },
  "workload": {
    "impl": "snn",
    "params": {},
    "spike_source": { "enable": false }
  },
  "control": { "global_step_sync_enable": false },
  "loader": { "chunk_bytes": 65536 }
}
```

`*_runtime_bridge.json` 统一形状：

```json
{
  "schema_version": 3,
  "platform": {
    "mesh_size": 4,
    "exec_mode": "gas",
    "stop": { "mode": "time", "simulation_time": "1us" },
    "flags": { "enable_node_summary": true }
  },
  "workload": {
    "impl": "riscv_snn",
    "params": {
      "hart_isa": "rv64im_zicsr",
      "local_mem_bytes": 65536,
      "cmd_queue_entries": 64,
      "cmp_queue_entries": 64,
      "rx_debug_queue_entries": 16,
      "boot_addr": 0,
      "backend_name": "runtime_bridge",
      "firmware_elf": "/home/xgy/remote/riscv_snn_isa_lab/firmware/<family>.elf"
    },
    "spike_source": { "enable": false }
  },
  "control": { "global_step_sync_enable": false },
  "loader": { "chunk_bytes": 65536 }
}
```

同步把 `riscv_snn_isa_lab/tools/riscv_snn_lab.py` 里的 `EQUIV_FAMILY_SPECS` 扩展成五条 family。

**Step 4: 重新跑目标测试，确认 family registry 与 spec pair 收口**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_equiv_family_surface_freezes_fault_lifecycle_pairs \
  -v
```

Expected:

```text
OK
```

**Step 5: 跑 spec validate，确认没有坏 JSON**

Run:

```bash
cd "/home/xgy/remote" && \
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref_snn_baseline.json" && \
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref_runtime_bridge.json" && \
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref_snn_baseline.json" && \
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref_runtime_bridge.json" && \
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_snn_baseline.json" && \
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_runtime_bridge.json" && \
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_overwrite_chain_ref_snn_baseline.json" && \
python3 "/home/xgy/remote/sst_dram_si/tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_overwrite_chain_ref_runtime_bridge.json"
```

Expected:

```text
每条 spec 都返回 OK
```

**Step 6: 不提交**

仓库策略要求这一阶段不做 `git commit`；实现完成后只保留工作树改动，等待用户明确批准。

## Task 2: 把 fault family 的 gate 语义收成 family-aware policy

**Files:**
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/notes/phase-c-runtime-equivalence.md`

**Step 1: 先写失败测试，冻结 family policy surface**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加一组 family policy 测试。重点不是复制 fault code 常量，而是冻结 gate 行为分层：

```python
def test_equiv_family_policies_freeze_fault_expectations(self) -> None:
    self.assertEqual(
        riscv_snn_lab.EQUIV_FAMILY_POLICIES["external_dyn_desc_ref"]["fault_mode"],
        "quiescent",
    )
    self.assertEqual(
        riscv_snn_lab.EQUIV_FAMILY_POLICIES["external_dyn_desc_fault_ref"]["fault_mode"],
        "accepted_fault_required",
    )
    self.assertEqual(
        riscv_snn_lab.EQUIV_FAMILY_POLICIES["external_dyn_desc_bad_policy_ref"]["progress_mode"],
        "no_committed_progress_allowed",
    )
    self.assertEqual(
        riscv_snn_lab.EQUIV_FAMILY_POLICIES["external_dyn_desc_fault_rearm_ref"]["fault_lifecycle_mode"],
        "clear_then_refault",
    )
    self.assertEqual(
        riscv_snn_lab.EQUIV_FAMILY_POLICIES["external_dyn_desc_fault_overwrite_chain_ref"]["fault_lifecycle_mode"],
        "overwrite_chain",
    )
```

再补一条 data-driven fake-run 测试，确认 bad-policy/fault family 不会被 success path 的“最后 completion status 必须为 0、fault_count 必须为 0”错杀。

**Step 2: 跑测试，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_equiv_family_policies_freeze_fault_expectations \
  -v
```

Expected:

```text
FAIL: EQUIV_FAMILY_POLICIES missing
```

**Step 3: 在 lab wrapper 里实现“高层 policy，而不是第二份协议常量”**

在 `riscv_snn_isa_lab/tools/riscv_snn_lab.py` 增加一个小而窄的 family policy 表，例如：

```python
EQUIV_FAMILY_POLICIES = {
    "external_dyn_desc_ref": {
        "fault_mode": "quiescent",
        "progress_mode": "forward_progress_expected",
        "fault_lifecycle_mode": "none",
    },
    "external_dyn_desc_fault_ref": {
        "fault_mode": "accepted_fault_required",
        "progress_mode": "forward_progress_expected",
        "fault_lifecycle_mode": "single_fault",
    },
    "external_dyn_desc_bad_policy_ref": {
        "fault_mode": "accepted_fault_required",
        "progress_mode": "no_committed_progress_allowed",
        "fault_lifecycle_mode": "single_fault",
    },
    "external_dyn_desc_fault_rearm_ref": {
        "fault_mode": "accepted_fault_required",
        "progress_mode": "fault_lifecycle_surface",
        "fault_lifecycle_mode": "clear_then_refault",
    },
    "external_dyn_desc_fault_overwrite_chain_ref": {
        "fault_mode": "accepted_fault_required",
        "progress_mode": "fault_lifecycle_surface",
        "fault_lifecycle_mode": "overwrite_chain",
    },
}
```

实现要求：

1. 只写 gate 所需的高层类别，不复制 `aux0/aux1`、descriptor flag、fault code 常量。
2. `run_equivalence()` 的 runtime gate 逻辑要按 family policy 解释：
   - success family：fault snapshot 需 quiescent
   - accepted-fault family：`fault_count > 0` 且 `last_fault_csr > 0`
   - bad-policy family：允许 `step.global_steps_done == 0`
   - rearm/overwrite family：允许最终状态不是“零 fault”，但要求 gate 原因能指向 lifecycle contract
3. 对不满足 policy 的情况，summary 必须给出 family-aware `gate_reasons`。

**Step 4: 增加 fake-run regression tests，避免 success policy 误套 fault family**

建议至少补三条测试：

```python
def test_run_equivalence_fault_family_requires_nonzero_fault_snapshot(self) -> None: ...
def test_run_equivalence_bad_policy_family_allows_zero_progress(self) -> None: ...
def test_run_equivalence_fault_rearm_family_surfaces_lifecycle_reason(self) -> None: ...
```

这些测试都复用现有 `run_equivalence()` fake-run 模式，不需要真实跑 SST。

**Step 5: 跑 targeted tests，确认 family-aware gate 真正落地**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_equiv_family_policies_freeze_fault_expectations \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_run_equivalence_fault_family_requires_nonzero_fault_snapshot \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_run_equivalence_bad_policy_family_allows_zero_progress \
  -v
```

Expected:

```text
OK
```

**Step 6: 更新 phase note，把 success-only 语义升级成 family-aware 语义**

在 `riscv_snn_isa_lab/notes/phase-c-runtime-equivalence.md` 中增加一个新小节，明确：

1. `Phase C` 的 PASS 仍然以 `external_dyn_desc_ref` 为基线；
2. `Phase D` 开始，`equiv` 不再默认只代表 success path；
3. fault / bad-policy / rearm / overwrite-chain 的 gate 解释层由 family policy 决定；
4. 这层 policy 不是新的 sample authority，只是对已有 artifact surface 的 gate 解释。

## Task 3: 增加 `equiv-matrix`，把五条 family 的 freshness 跑成一份 dated summary

**Files:**
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/README.md`

**Step 1: 先写失败测试，冻结顶层 summary 结构**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加：

```python
def test_run_equiv_matrix_writes_family_summary(self) -> None:
    summary = riscv_snn_lab.run_equiv_matrix(...)
    self.assertEqual(summary["gate_name"], "riscv_snn_equiv_matrix")
    self.assertEqual(summary["count"], 2)
    self.assertTrue(summary["all_ok"])
    self.assertEqual(summary["families"][0]["family"], "external_dyn_desc_ref")
```

同时加 CLI parser 测试，冻结子命令：

```python
equiv-matrix --group all
equiv-matrix --family external_dyn_desc_fault_ref
```

**Step 2: 跑测试，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_run_equiv_matrix_writes_family_summary \
  -v
```

Expected:

```text
AttributeError: module 'riscv_snn_lab' has no attribute 'run_equiv_matrix'
```

**Step 3: 最小实现 `run_equiv_matrix()` 与 CLI**

在 `riscv_snn_isa_lab/tools/riscv_snn_lab.py` 里新增一个只做 orchestration 的聚合层：

```python
def run_equiv_matrix(
    families: list[str] | None = None,
    *,
    lab_root: Path = LAB_ROOT,
    runner: Runner = run_command,
    summary_path: Path | None = None,
) -> dict[str, Any]:
    ...
```

输出结构建议固定为：

```json
{
  "schema_version": 1,
  "gate_name": "riscv_snn_equiv_matrix",
  "count": 5,
  "all_ok": false,
  "families": [
    {
      "family": "external_dyn_desc_fault_ref",
      "status": "PASS",
      "summary_path": "...-external-dyn-desc-fault-ref-equiv.json",
      "gate_reasons": []
    }
  ]
}
```

设计要求：

1. 逐个复用现有 `run_equivalence()`，不要复制 compare/gate 逻辑。
2. 默认 family surface 来自 `EQUIV_FAMILY_SPECS`。
3. dated summary 写入 `riscv_snn_isa_lab/references/`。
4. `all_ok` 只由 family summary 派生，不另外创造 authority。

**Step 4: 运行 targeted unit tests**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_run_equiv_matrix_writes_family_summary \
  -v
```

Expected:

```text
OK
```

**Step 5: 用至少两条真实 family 做一次 smoke 级 fresh matrix**

先不要一上来跑满五条。第一轮建议只跑：

1. `external_dyn_desc_ref`
2. `external_dyn_desc_fault_ref`

Run:

```bash
cd "/home/xgy/remote" && \
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" \
  equiv-matrix \
  --family external_dyn_desc_ref \
  --family external_dyn_desc_fault_ref
```

Expected:

```text
输出 dated summary path，且每条 family 都带 status/gate_reasons
```

**Step 6: 在 README 中增加 fresh-matrix 入口**

在 `riscv_snn_isa_lab/README.md` 增加：

1. 新的 CLI 用法；
2. top-level dated summary 产物路径；
3. “equiv-matrix 只聚合 family 结果，不是新的 authority”。

## Task 4: 把 toolchain bridge freshness 挂到同一份顶层 experimental gate

**Files:**
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/ci/nightly_sidecar.py`
- Modify: `riscv_snn_isa_lab/README.md`

**Step 1: 先写失败测试，冻结 sidecar report 的新增字段**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加一条 sidecar report 测试，要求最终 report 同时包含 nightly 与 equivalence：

```python
def test_run_nightly_sidecar_can_attach_equiv_matrix_summary(self) -> None:
    report = riscv_snn_lab.run_nightly_sidecar(...)
    self.assertIn("nightly_index", report)
    self.assertIn("equivalence", report)
    self.assertEqual(report["equivalence"]["gate_name"], "riscv_snn_equiv_matrix")
```

**Step 2: 跑测试，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_run_nightly_sidecar_can_attach_equiv_matrix_summary \
  -v
```

Expected:

```text
FAIL: report has no equivalence block
```

**Step 3: 最小实现 sidecar 集成，不拆新 authority**

推荐做法：

1. 保留 `nightly` 现有 builder/toolchain/audit 流水线；
2. 在 sidecar 或 `nightly` 顶层新增一个显式开关，例如：

```bash
python3 "riscv_snn_isa_lab/ci/nightly_sidecar.py" --with-equivalence
```

3. 开关打开时调用 `run_equiv_matrix()`；
4. 最终 report 只把：
   - nightly index
   - equiv matrix
   合并到一份派生 JSON/Markdown 报告中。

禁止做法：

1. 把 toolchain compare 逻辑塞进 `run_equivalence()`；
2. 再发明一份 family metadata JSON；
3. 把 sidecar 变成新的 source of truth。

**Step 4: 跑 sidecar unit tests**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.TestRiscvSnnLab.test_run_nightly_sidecar_can_attach_equiv_matrix_summary \
  -v
```

Expected:

```text
OK
```

**Step 5: 真实跑一次顶层 fresh gate**

Run:

```bash
cd "/home/xgy/remote" && \
python3 "/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py" --with-equivalence
```

Expected:

```text
写出 dated nightly index / stable sidecar report / stable sidecar summary markdown
并包含 equivalence block
```

## Task 5: 全量验证、文档刷新与 dated evidence 落盘

**Files:**
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `riscv_snn_isa_lab/notes/phase-c-runtime-equivalence.md`
- Modify: `TECH_PROGRESS.md`

**Step 1: 跑 Python 单测总集**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
```

Expected:

```text
OK
```

**Step 2: 跑 builder/toolchain 既有 protocol suite，确认没有把旧实验面撞坏**

Run:

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
make test-riscv-snn-runtime-service-provider \
     test-riscv-snn-runtime-bridge-backend \
     test-riscv-snn-firmware-protocol \
     test-riscv-snn-toolchain-firmware-protocol
```

Expected:

```text
全部通过
```

**Step 3: 真实跑满五条 family 的 equivalence**

Run:

```bash
cd "/home/xgy/remote" && \
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv-matrix --group all
```

Expected:

```text
产出一份 dated equiv-matrix summary
```

**Step 4: 真实跑顶层 sidecar**

Run:

```bash
cd "/home/xgy/remote" && \
python3 "/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py" --with-equivalence
```

Expected:

```text
产出 updated nightly-sidecar-report.json / nightly-sidecar-summary.md
```

**Step 5: 刷新文档**

必须同步写回：

1. `riscv_snn_isa_lab/README.md`
2. `riscv_snn_isa_lab/notes/phase-c-runtime-equivalence.md`
3. `TECH_PROGRESS.md`

至少要写清：

1. 五条 family 是否都进入 freshness gate；
2. 哪些 family 是 PASS / WARN / FAIL；
3. toolchain bridge 是否已挂入同一份顶层 gate；
4. 当前仍残留的 drift / fault lifecycle 风险是什么。

## 执行顺序建议

1. Task 1: family/spec surface
2. Task 2: family-aware gate policy
3. Task 3: equiv-matrix
4. Task 4: sidecar freshness integration
5. Task 5: full verification + docs

## 风险提示

1. 不要把 `external_dyn_desc_ref` 的 success-only gate 生搬到其它 fault family。
2. 不要为了让 family 通过而把 policy 写得过宽，尤其不能把 success path 的 cleanliness 要求整体删掉。
3. 不要在 lab wrapper 里复制 builder/toolchain 的 numeric protocol 常量。
4. 如果某条 fault family 缺少足够 runtime stats，不要假装 PASS；应显式写成 `WARN/FAIL + gate_reasons`。

