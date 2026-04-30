# SnnDL `riscv_snn` Phase E Authority Freeze and External Reference Alignment Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 `riscv_snn` 实验主线从“已有 fresh gate 与 multi-family evidence 的实验链”推进成“authority 单一、bit-level ABI 有唯一真值、可与官方 RISC-V 参考模型对齐、扩 family 不分叉”的稳定研究平台。

**Architecture:** 继续坚持实验主线严格隔离。`riscv_snn_isa_lab` 负责 orchestration、summary、gate 解释与外部参考桥接；`services/workload/riscv_snn` 只保留 workload/runtime bridge/protocol 实现；默认 `snn` 主路径不承载这条试验线的额外语义。所有新增能力优先落在实验目录、lab wrapper、单一 authority metadata 与最少量接缝文件中，不引入第二份 metadata authority，不把 custom accelerator 语义硬塞进标准 RISC-V compatibility surface。

**Tech Stack:** Python 3、`unittest`、JSON/YAML authority metadata、SST-SnnDL runtime/toolchain protocol suite、`riscv_snn_lab.py`、`nightly_sidecar.py`、RISC-V Spike、RISC-V Architectural Compatibility Test policy

---

## 0. 约束、目标与阶段出口

### 必守约束

1. 不把 `riscv_snn` 重新做成 `CoreShell` / compute core 扩展。
2. 不引入第二份 metadata authority；所有 schema、ABI、family surface 都必须能指回唯一真值。
3. 不把 custom SNN accelerator CSR/fault 语义强塞进标准 RISC-V arch-test/ACT 口径。
4. 不为了 Phase E 引入对默认 `snn` 主路径的隐式行为改变。
5. 继续保持实验目录隔离，新增代码优先放在 `riscv_snn_isa_lab/` 与最小必要接缝内。
6. 所有新增语义都必须先有失败测试，再有最小实现，再有 dated/stable evidence。
7. 本阶段不做任何 git 写操作；实现后只保留工作树改动，等待后续明确批准。

### Phase E Exit Criteria

1. `nightly-sidecar-report.json`、`YYYY-MM-DD-nightly-index.json`、`nightly-history-index.json`、`YYYY-MM-DD-equiv-matrix.json` 的 authority/role 边界有显式 schema 字段与测试守护。
2. bit-level ABI 至少有一份 machine-readable authority 文件，能够派生：
   - firmware/toolchain include surface
   - lab decoder / report surface
   - runtime/protocol 校验面
3. 存在一个隔离的 `hart-ref`/`isa-ref` 入口，能用 Spike 跑最小 `rv64im_zicsr` 参考检查，并产出 dated summary。
4. 至少新增一条真正正交的新 family，用来冻结 queue/timing/visibility 合约，而不是再重复 success/fault 变体。
5. correctness gate 与 research metrics/report surface 分离，不再把研究型 drift 继续堆进 PASS/FAIL gate。

### 官方外部参考

1. Spike 官方仓库：
   - `https://github.com/riscv-software-src/riscv-isa-sim`
2. RISC-V Architectural Compatibility Test Policy：
   - `https://riscv.org/wp-content/uploads/2025/02/Architectural-Compatibility-Test-4.pdf`
3. RISC-V Arch Test 官方仓库：
   - `https://github.com/riscv-software-src/riscv-arch-test`
4. OpenSBI 官方仓库：
   - `https://github.com/riscv-software-src/opensbi`

其中本阶段真正直接消费的是 Spike 与 ACT/arch-test 的“参考模型 + signature/compatibility 方法”；OpenSBI 只作为明确延后的后续方向，不进入当前实现范围。

## Task 1: 冻结 stable/dated artifact role 与 authority 语义

**Files:**
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/ci/nightly_sidecar.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `riscv_snn_isa_lab/notes/phase-c-runtime-equivalence.md`

**Step 1: 先写失败测试，冻结 artifact role surface**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加一组新测试，明确下面几份 artifact 必须带 role/scope 字段：

```python
def test_nightly_index_carries_artifact_role_and_scope(self) -> None:
    summary = riscv_snn_lab.build_nightly_index(...)
    self.assertEqual(summary["artifact_role"], "dated_nightly_index")
    self.assertEqual(summary["authority_scope"], "builder_toolchain_audit_only")

def test_history_index_carries_artifact_role_and_scope(self) -> None:
    history = riscv_snn_lab.build_history_index(...)
    self.assertEqual(history["artifact_role"], "stable_history_rollup")
    self.assertEqual(history["authority_scope"], "historical_rollup_only")

def test_sidecar_report_carries_artifact_role_and_scope(self) -> None:
    report = riscv_snn_lab.run_ci_sidecar(...)
    self.assertEqual(report["artifact_role"], "stable_top_level_gate")
    self.assertEqual(report["authority_scope"], "experimental_gate_authority")
```

再加一条 markdown surface 测试，要求 summary 明确打印：

```python
self.assertIn("Authority scope", summary_md)
self.assertIn("dated nightly index is not the equivalence authority", summary_md)
```

**Step 2: 跑 targeted 测试，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_nightly_index_carries_artifact_role_and_scope \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_history_index_carries_artifact_role_and_scope \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_sidecar_report_carries_artifact_role_and_scope \
  -v
```

Expected:

```text
FAIL: artifact_role / authority_scope missing
```

**Step 3: 在 JSON artifact 中加入最小 schema/role 元信息**

在 `riscv_snn_lab.py` 的以下入口中加入统一 envelope 字段：

1. `build_nightly_index()`
2. `build_history_index()`
3. `run_equiv_matrix()`
4. `run_ci_sidecar()`

每份 artifact 至少显式包含：

```python
{
    "schema_version": 2,
    "artifact_role": "...",
    "authority_scope": "...",
    "producer": "...",
    "generated_utc": "...",
}
```

推荐 role/scope 固定为：

1. nightly index：
   - `artifact_role = "dated_nightly_index"`
   - `authority_scope = "builder_toolchain_audit_only"`
2. history index：
   - `artifact_role = "stable_history_rollup"`
   - `authority_scope = "historical_rollup_only"`
3. equiv matrix：
   - `artifact_role = "dated_equivalence_matrix"`
   - `authority_scope = "family_level_equivalence_authority"`
4. sidecar report：
   - `artifact_role = "stable_top_level_gate"`
   - `authority_scope = "experimental_gate_authority"`

**Step 4: 更新 stable markdown，让人类读者不再误读 authority**

在 `build_sidecar_summary_md()` 输出中增加一节：

```markdown
## Authority

- stable top-level gate: `nightly-sidecar-report.json`
- dated family-level equivalence authority: `YYYY-MM-DD-equiv-matrix.json`
- dated nightly index: builder/toolchain/audit-only evidence, not the equivalence authority
```

**Step 5: 重新跑 targeted tests 与 Python 总集**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
```

Expected:

```text
OK
```

## Task 2: 冻结 dated index / stable report / history rollup 的派生关系

**Files:**
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/README.md`

**Step 1: 先写失败测试，明确谁能派生谁**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加：

```python
def test_sidecar_report_declares_derived_from_surfaces(self) -> None:
    report = riscv_snn_lab.run_ci_sidecar(...)
    self.assertEqual(
        report["derived_from"],
        ["dated_nightly_index", "stable_history_rollup", "dated_equivalence_matrix"],
    )

def test_nightly_index_does_not_claim_equivalence_authority(self) -> None:
    nightly = riscv_snn_lab.build_nightly_index(...)
    self.assertNotIn("family_level_equivalence_authority", nightly.get("authority_scope", ""))
```

再加一条 drift/recovery history test，要求 history 只滚 nightly 维度，不直接重写 equivalence 结论。

**Step 2: 跑 targeted tests，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_sidecar_report_declares_derived_from_surfaces \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_nightly_index_does_not_claim_equivalence_authority \
  -v
```

Expected:

```text
FAIL
```

**Step 3: 在 sidecar/report/history 中加入窄的派生元数据**

推荐在 sidecar report 中加入：

```python
"derived_from": [
    "dated_nightly_index",
    "stable_history_rollup",
    "dated_equivalence_matrix",
]
```

而 `build_history_index()` 继续只消费 `*-nightly-index.json`，不要去折叠 `equiv-matrix`。

**Step 4: 新增一条 CLI 只读 explain 入口**

在 `riscv_snn_lab.py` 里增加一个只读小子命令，例如：

```bash
python3 riscv_snn_isa_lab/tools/riscv_snn_lab.py explain-sidecar
```

它只输出：

1. 当前 stable authority 是谁；
2. dated evidence 是谁；
3. history rollup 是谁；
4. 哪些 artifact 不是 authority。

这样后续不必依赖 README 段落来理解 gate 角色。

**Step 5: 重新跑 targeted tests 与 real sidecar**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v && \
python3 "/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py" --with-equivalence
```

Expected:

```text
tests OK
sidecar returns report path with gate_ok unchanged
```

## Task 3: 引入 bit-level ABI authority 的唯一 machine-readable 真值

**Files:**
- Create: `riscv_snn_isa_lab/spec_authority/riscv_snn_accel_v1.json`
- Create: `riscv_snn_isa_lab/tools/export_riscv_snn_abi.py`
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_ref_toolchain/main.S`
- Modify: `riscv_snn_isa_lab/firmware_src/external_dyn_desc_bad_policy_ref_toolchain/main.S`
- Modify: `riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_rearm_ref_toolchain/main.S`
- Modify: `riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_overwrite_chain_ref_toolchain/main.S`
- Modify: `riscv_snn_isa_lab/README.md`

**Step 1: 先写失败测试，冻结 authority 文件 surface**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加：

```python
def test_bit_level_abi_authority_exists_and_has_required_sections(self) -> None:
    authority = json.loads(
        (riscv_snn_lab.LAB_ROOT / "spec_authority" / "riscv_snn_accel_v1.json").read_text(encoding="utf-8")
    )
    self.assertEqual(authority["schema_version"], 1)
    self.assertIn("csr_map", authority)
    self.assertIn("event_pending_bits", authority)
    self.assertIn("descriptor_layout", authority)
    self.assertIn("completion_layout", authority)
    self.assertIn("fault_semantics", authority)
```

再加 source contract test，明确 toolchain bridge 程序不应继续保留多份裸常量真值，而应包含 generated include surface 的痕迹。

**Step 2: 跑 targeted tests，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_bit_level_abi_authority_exists_and_has_required_sections \
  -v
```

Expected:

```text
FAIL: missing riscv_snn_accel_v1.json
```

**Step 3: 创建最小 ABI authority 文件**

`riscv_snn_accel_v1.json` 第一版只收已经在实验面稳定存在的字段，不预支未来：

1. `hart_profile`
   - `rv64im_zicsr`
2. `csr_map`
3. `event_pending_bits`
4. `descriptor_layout`
5. `completion_layout`
6. `fault_semantics`
7. `ownership_rules`
8. `doorbell_rules`

文件里的每个 section 都要有：

```json
{
  "version": 1,
  "status": "experimental_frozen_for_phase_e"
}
```

**Step 4: 创建窄导出器，不让 lab wrapper 持有第二份常量**

`export_riscv_snn_abi.py` 只做两件事：

1. 从 authority 文件读取字段；
2. 导出：
   - firmware include 片段
   - Python decoder metadata 片段

不在导出器里手抄第二份协议数值。

**Step 5: 让 fault-family toolchain bridge 切到 authority 导出的 include**

第一版不追求把所有 builder/toolchain 程序都改完，只要求先把 fault family 全部切过去，确认：

1. `fault_ref`
2. `bad_policy_ref`
3. `fault_rearm_ref`
4. `fault_overwrite_chain_ref`

都不再各自维护关键 CSR/fault/event 常量真值。

**Step 6: 跑 targeted tests 与 protocol suite**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

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

## Task 4: 增加隔离的 `hart-ref` 参考模型桥，先对齐标准 RISC-V hart 语义

**Files:**
- Create: `riscv_snn_isa_lab/tools/riscv_hart_ref.py`
- Create: `riscv_snn_isa_lab/hart_ref/programs/rv64im_zicsr_smoke/`
- Create: `riscv_snn_isa_lab/hart_ref/manifest.json`
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `riscv_snn_isa_lab/notes/phase-c-runtime-equivalence.md`

**Step 1: 先写失败测试，冻结 `hart-ref` CLI surface**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加：

```python
def test_main_hart_ref_accepts_profile_and_summary_path(self) -> None:
    expected = {"summary_path": "/tmp/hart-ref.json", "all_ok": True}
    with mock.patch.object(riscv_snn_lab, "run_hart_ref", return_value=expected) as run_hart_ref:
        with mock.patch("builtins.print") as print_mock:
            rc = riscv_snn_lab.main(["hart-ref", "--profile", "rv64im_zicsr_smoke"])
    self.assertEqual(rc, 0)
    self.assertEqual(run_hart_ref.call_args.kwargs["profile"], "rv64im_zicsr_smoke")
    print_mock.assert_called_once_with("/tmp/hart-ref.json")
```

再加一条针对 `riscv_hart_ref.py` 的 fake-run 测试，mock `spike` 调用并校验：

1. 传入 ELF；
2. 产出 signature；
3. 写 dated summary；
4. 环境中没有 `spike` 时返回结构化 `ENV_FAIL`，而不是把错误伪装成 ISA FAIL。

**Step 2: 跑 targeted tests，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_main_hart_ref_accepts_profile_and_summary_path \
  -v
```

Expected:

```text
FAIL: run_hart_ref missing / hart-ref subcommand unknown
```

**Step 3: 实现隔离的参考模型桥**

要求：

1. `riscv_hart_ref.py` 独立实现 Spike bridge；
2. `riscv_snn_lab.py` 只增加一个薄子命令：
   - `hart-ref`
3. 第一版只覆盖：
   - `rv64im_zicsr`
   - 通用寄存器
   - PC
   - 标准 CSR
   - signature memory compare
4. 明确不覆盖：
   - `msnn*` custom CSR
   - SNN backend semantics
   - OpenSBI/S-mode/Linux

**Step 4: 准备最小 smoke profile**

`hart_ref/manifest.json` 第一版只需要 1 到 3 个程序：

1. 算术/分支
2. trap/csr
3. 最小内存访问

并在 dated summary 中显式记录：

```json
{
  "artifact_role": "dated_hart_reference_summary",
  "authority_scope": "standard_riscv_hart_semantics_only"
}
```

**Step 5: 跑 mock tests；若本地有 Spike 再补 real smoke**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
```

如果环境有 `spike`，再执行：

```bash
cd "/home/xgy/remote" && \
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" hart-ref --profile rv64im_zicsr_smoke
```

Expected:

```text
无 Spike: 结构化 ENV_FAIL summary
有 Spike: dated hart-ref summary
```

## Task 5: 扩一个真正正交的新 family，并把 research metrics/report 从 correctness gate 分离

**Files:**
- Create: `riscv_snn_isa_lab/specs/barrier_wfi_order_ref_snn_baseline.json`
- Create: `riscv_snn_isa_lab/specs/barrier_wfi_order_ref_runtime_bridge.json`
- Create: `riscv_snn_isa_lab/firmware_src/barrier_wfi_order_ref_toolchain/`
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Create: `riscv_snn_isa_lab/tools/export_riscv_snn_research_report.py`
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `TECH_PROGRESS.md`

**Step 1: 先写失败测试，冻结新 family 是 timing/visibility 维度，不是 success/fault 复刻**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 增加：

```python
def test_barrier_wfi_order_family_is_registered_with_timing_policy(self) -> None:
    self.assertEqual(
        riscv_snn_lab.EQUIV_FAMILY_POLICIES["barrier_wfi_order_ref"]["timing_mode"],
        "wfi_barrier_completion_visibility",
    )
```

再加一条 research report surface 测试，要求 queue latency / completion visibility 指标进入独立 report，而不是 gate reasons。

**Step 2: 跑 targeted tests，确认当前会失败**

Run:

```bash
cd "/home/xgy/remote" && \
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_barrier_wfi_order_family_is_registered_with_timing_policy \
  -v
```

Expected:

```text
FAIL
```

**Step 3: 只新增一条正交 family**

第一版只做：

1. `barrier_wfi_order_ref`

它专门冻结：

1. `submit -> wfi -> wakeup -> completion_visible`
2. barrier release 与 completion 可见顺序
3. `event_pending` 清理后再次等待的行为

不要在同一轮再同时做 `queue_backpressure_ref` 与 `descriptor_chain_ref`；那两条放到 Phase E 后半或 Phase F。

**Step 4: 创建独立 research report exporter**

`export_riscv_snn_research_report.py` 只消费已有 run/equiv sidecar artifact，导出：

1. queue occupancy / latency
2. completion visible-to-consumed gap
3. barrier wait duration
4. tx/rx visibility gap
5. memory / gas trend drift

并明确：

1. correctness gate 只看 `PASS/FAIL/WARN`
2. report 负责研究解释

**Step 5: 跑新 family、equiv-matrix、sidecar**

Run:

```bash
cd "/home/xgy/remote" && \
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family barrier_wfi_order_ref && \
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv-matrix --group all && \
python3 "/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py" --with-equivalence
```

Expected:

```text
产生新的 family summary
equiv-matrix 与 sidecar 继续可解释，不因 report surface 扩展而改 gate authority
```

## 建议执行顺序

1. Task 1：artifact role/schema freeze
2. Task 2：derived-from / explain / history boundary
3. Task 3：bit-level ABI authority
4. Task 4：isolated Spike hart reference bridge
5. Task 5：orthogonal family + research report split

## 风险提示

1. 不要把 `nightly-index.json` 继续做胖，直到它看起来像第二份 sidecar report。
2. 不要让 ABI authority 演变成“设计愿景大表”；只收当前已经稳定存在的字段。
3. 不要把 `msnn*` custom CSR 拿去和标准 hart compatibility 混做一份 PASS/FAIL。
4. 不要同时新增多条新 family；先用一条正交 family 验证 Phase E 骨架。
5. 不要把 research metrics exporter 反向耦回 gate 判定。

## 完成后交付物

1. 一份新的 stable sidecar report，具有显式 authority/role/schema 字段。
2. 一份 machine-readable ABI authority 文件。
3. 一份 dated hart reference summary。
4. 一份新的正交 family dated summary。
5. 一份独立的 research report exporter 及其 dated report。

## 这一阶段之后最自然的下一步

如果 Phase E 全部完成，Phase F 最自然的主线会是：

1. 把 `queue_backpressure_ref` 与 `descriptor_chain_ref` 加入 family surface；
2. 再决定是否需要把 `hart-ref` 结果挂进 sidecar 的非阻塞 explain 面；
3. 只有在标准 hart 语义稳定后，才讨论更高层的 OpenSBI / S-mode / multi-hart orchestration 研究。
