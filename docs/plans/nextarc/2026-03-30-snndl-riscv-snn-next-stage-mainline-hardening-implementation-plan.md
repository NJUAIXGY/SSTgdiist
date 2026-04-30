# SnnDL `riscv_snn` Next-Stage Mainline Hardening Implementation Plan

> Current note (2026-04-18):
> 这份文件现在是 `riscv_snn runtime-bridge equivalence mainline` 的**当前 authoritative next-stage planning doc**。
>
> 当前 authoritative 阅读顺序请优先看：
> 1. `/home/xgy/remote/riscv_snn_isa_lab/README.md`
> 2. `/home/xgy/remote/docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
> 3. `/home/xgy/remote/riscv_snn_isa_lab/references/current-mainline-status.md`
> 4. `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
>
> 当前 stable baseline 已经成立：
> 1. required 6 families 继续作为唯一 blocking gate 输入。
> 2. full equivalence 维持 `8` 条，且仍是 research-only non-blocking attachment。
> 3. `reference_program_compare` 已稳定覆盖 `12` 条 family。
> 4. `stat_snapshot_family` 已达到 `3/3` 合法 selector 覆盖。
> 5. `observer-fail-recovery`、`observer-history-compact-refresh` 已进入正式命令面。
> 6. 实验主线与默认 `snn` 主线仍保持严格隔离，没有新增第二份 authority。
>
> 当前执行更新（2026-04-18）：
> 1. `WP1 Observer / Freshness Contract Completion` 已完成第一轮 stable-readable 收口。
> 2. `WP2 Supplementary Surface Frameworkization` 的前两段最小收口已经完成：
>    - `WP2-A: supplementary surface contract helper skeleton`
>    - `WP2-B: summary/current-status markdown framework`
> 3. 下一阶段的**当前执行入口**切到 `WP3-A: control-command family authority/reference-machine semantics`。
> 4. `WP3-A` 的目标是先在 authority / reference-machine 侧冻结 `completion_consume / fault_clear` 语义，再进入 runtime/toolchain/program-compare 闭环。
>
> 本文件前半部分描述**下一阶段应该做什么**；文末 archive 保留旧迭代计划，仅供回溯，不应再直接照着执行。

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把当前 `riscv_snn runtime-bridge equivalence mainline` 从“主线已经成立”推进到“可持续扩展的 ISA 研究平台主线”：observer/freshness 契约写硬、supplementary surface 统一框架化、下一组 ISA-visible control commands 进入 program/runtime/toolchain 三角闭环、family onboarding 不再依赖大面积硬编码。

**Architecture:** 这一阶段继续坚持 `control plane / data plane / sync plane / bridge plane` 分层，不扩默认 `snn` 主线，也不把 supplementary surface 升格成 top-level gate。实现重点从“补更多单点 family”切换到“平台化收口”：先把 observer/freshness/operator surface 契约收硬，再扩 `completion_consume / fault_clear` 这组更像 ISA-visible control commands 的 family，最后把 family onboarding 和 bridge registry 做成严格隔离、单一 authority 驱动的扩展路径。

**Tech Stack:** Python 3、`unittest`、JSON authority metadata、`riscv_snn_isa_lab/tools/riscv_snn_lab.py`、`riscv_snn_isa_lab/architecture_model/*`、`spec_authority/*.json`、`family_lanes/`、`sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/*`、SST runtime smoke/equivalence flow、stable sidecar artifacts。

---

## 0. Stage Statement

当前下一阶段的正式名称定为：

**`Stage-P: Platformization for ISA Research Mainline`**

这不是“继续把现有 family 一条条往上堆”的阶段，而是把当前已经站稳的主线推进成**能继续稳定扩 family、扩 command、扩 surface 的平台阶段**。这一阶段的核心判断有四条：

1. 当前主线已经不缺“是否能跑通”的证明，缺的是“未来如何不分叉地继续扩”。
2. 现在最该收口的不是 datapath，而是 operator surface、observer/freshness、supplementary surface 和 family onboarding。
3. 下一组最值得扩的 ISA-visible 语义，不是更重的 datapath 命令，而是 `completion_consume / fault_clear` 这组控制命令。
4. 所有扩展都必须继续满足：
   - single authority
   - supplementary-only remains supplementary-only
   - strict isolation from default `snn`

## 1. Baseline Snapshot

开始本阶段前，默认以下 stable facts 为真：

1. top-level gate：
   - `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`
   - `gate_ok = true`
2. required blocking families：
   - `barrier_wfi_order_ref`
   - `external_dyn_desc_bad_policy_ref`
   - `external_dyn_desc_fault_overwrite_chain_ref`
   - `external_dyn_desc_fault_rearm_ref`
   - `external_dyn_desc_fault_ref`
   - `external_dyn_desc_ref`
3. full equivalence：
   - `count = 8`
   - role = research-only non-blocking attachment
4. supplementary surfaces：
   - `compare` fresh
   - `reference_compare` fresh
   - `reference_program_compare` fresh with `count = 12`
   - `stat_snapshot_family` fresh with `selector_count = 3` and `covered_selector_count = 3`
5. observer closure：
   - fail/recovery sample 已存在
   - compact refresh 命令面已存在
6. current non-negotiable boundaries：
   - 不把 `riscv_snn` 塞回 `CoreShell`
   - 不把 `riscv_snn` 伪装成新的 compute core
   - 不把 incoming spike 拉回 software handler 主路径
   - 不引入第二份 metadata authority

## 2. Stage Non-Goals

本阶段明确**不做**下面这些事：

1. 不把 `reference_program_compare` 或 `stat_snapshot_family` 升格成 blocking gate。
2. 不急着引入新的 custom opcode、RVV、OS 层或复杂软件栈。
3. 不去修改默认 `snn` 主线接口，除非是 `services/workload/riscv_snn` 已明确依赖的最小 bridge contract。
4. 不把实验性 lane、registry、descriptor 再包装成新的 authority root。
5. 不追求一次性铺很大 command 面；只扩最有价值的一组控制命令族。

## 3. Stage Exit Criteria

只有同时满足下面 6 条，才算这一阶段完成：

1. observer summary、fail/recovery summary、current-mainline status 都能明确暴露 compact/freshness 的有效边界。
2. supplementary surface 的装载、规范化、summary/current-status 输出进入统一框架。
3. 新的一组 ISA-visible control commands 至少覆盖：
   - `completion_consume_ref`
   - `completion_consume_fault_interlock_ref`
   - `fault_clear_ref`
   - `fault_clear_then_refault_ref`
4. 这组新 family 全部进入：
   - authority
   - runtime bridge
   - reference program
   - runtime/toolchain evidence
   - program compare
5. family onboarding 新增路径明显减少 `riscv_snn_lab.py` 中的分支扩散。
6. stable sidecar 仍然是唯一 blocking gate，默认 `snn` 主线零污染。

## 4. Workstream Order and Parallelism

推荐顺序不是平均推进，而是分成 3 个波次：

1. **Wave 1: Contract Hardening**
   - `WP1 Observer / Freshness Contract Completion`
   - `WP2 Supplementary Surface Frameworkization`
2. **Wave 2: ISA Surface Expansion**
   - `WP3 Next ISA-visible Control Command Families`
3. **Wave 3: Scaling Path**
   - `WP4 Family Onboarding Dataization`
   - `WP5 Runtime/Toolchain Bridge Unification`

并行规则：

1. `WP1` 必须先于 `WP3` 完成，因为新 family 扩进来之前，observer/freshness 的可读与可审计面要先稳定。
2. `WP2` 可以与 `WP1` 部分并行，但必须在 `WP3` 大规模扩 family 前完成基础 helper 收口。
3. `WP4` 与 `WP5` 只建议在 `WP3` 的第一批 family 稳定后并行推进。

## 5. WP1: Observer / Freshness Contract Completion

### Goal

把当前已经能工作的 observer compact/fail-recovery 命令面，推进到“所有稳定 surface 都能显式读出 compact mode、有效 freshness 边界和 recovery 基线”的程度。

### Files

- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_supplementary_surface_v1.json`
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
- Generated: `riscv_snn_isa_lab/references/nightly-sidecar-observer-summary.json`
- Generated: `riscv_snn_isa_lab/references/current-mainline-status.md`
- Generated: `riscv_snn_isa_lab/references/observer-fail-recovery-loop-summary.json`

### Required landing

1. 把 observer summary 中与 compact/freshness 直接相关的字段补齐为 stable output：
   - `observer_history.refresh_mode`
   - `observer_history.latest_recovered_date`
   - `observer_history.effective_entry_count`
   - `observer_history.effective_all_dates_ok`
2. fail/recovery summary 要显式记录：
   - expected compact mode
   - effective compact mode
   - observer side effective freshness boundary
3. current-mainline-status 要能直接暴露 observer compact 视角，而不需要人反查 raw history。

### Step sequence

1. 先在 `test_riscv_snn_lab.py` 写失败测试，钉住 observer summary / current-mainline / fail-recovery summary 的新字段。
2. 运行定向单测，确认失败原因是字段缺失而不是测试本身有误。
3. 在 `riscv_snn_lab.py` 中收拢 observer history rollup helper，避免每个 surface 各自拼装字段。
4. 如果 authority 需要扩字段约束，只在 `riscv_snn_supplementary_surface_v1.json` 增量补 required field，不创建新 authority。
5. 刷新 stable surfaces，确认 sidecar -> observer -> current-mainline -> audit 没有链路分叉。

### Verification

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_main_observer_history_compact_refresh_prints_history_path \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_run_observer_fail_recovery_loop_wires_optional_history_mainline_and_audit
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" observer-refresh
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" export-mainline-status
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" stable-surface-audit
```

### Exit criteria

1. 只看 `nightly-sidecar-observer-summary.json` 和 `current-mainline-status.md`，就能判断 compact mode 和有效 freshness 边界。
2. `observer-fail-recovery` summary 不再需要人工解释“这次 compact 到哪里了”。

## 6. WP2: Supplementary Surface Frameworkization

### Goal

把当前 `compare / reference_compare / reference_program_compare / stat_snapshot_family` 四条 surface 的 refresh、normalize、history、summary/current-status 输出收成统一框架，减少 per-surface 分支。

### Current execution target (2026-04-18)

这一工作包当前拆成两个连续子阶段：

1. `WP2-A helper skeleton`
   - 新建 `riscv_snn_isa_lab/tools/supplementary_surface_contract.py`
   - 先统一 3 段重复 contract：
     - latest-only history payload builder
     - stable report -> normalized surface projection
     - sidecar supplementary attach / merge
   - 第一批迁移对象：
     - `reference_compare`
     - `reference_program_compare`
     - `stat_snapshot_family`
     - `compare` 的 stable report loader
2. `WP2-B markdown/current-status framework`
   - 在 `WP2-A` helper 稳住后，再继续收 summary markdown / current-mainline markdown 的统一骨架
   - 保留每条 surface 的 source loader 和 surface-specific augmentation，不引入新的 authority root

当前状态：

1. `WP2-A` 已完成
2. `WP2-B` 已完成
3. `WP2` 当前不再继续横向扩 helper 范围；下一执行入口改为 `WP3-A`

### Files

- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_supplementary_surface_v1.json`
- Modify: `riscv_snn_isa_lab/README.md`
- Create: `riscv_snn_isa_lab/tools/supplementary_surface_contract.py`

### Required landing

1. 新 helper 要统一处理：
   - authority surface loading
   - stable surface path resolution
   - normalization
   - current-status markdown rendering
   - summary markdown rendering
   - history payload projection
2. 现有四条 surface 的差异只能留在：
   - source loader
   - surface-specific payload augmentation
   - source history contract
3. helper 必须局限在 `riscv_snn_isa_lab/` 子树，不得外溢到默认 `snn` 主线。

### Step sequence

1. 先写失败测试，验证新 helper 接管后四条 surface 仍能产出原有关键字段。
2. 抽出 `supplementary_surface_contract.py`，只承载 lab 内部 surface framework，不承载 authority root。
3. 把 `riscv_snn_lab.py` 中四条 surface 的重复 summary/current-status 构建逻辑迁移到统一 helper。
4. 运行 surface refresh 和 stable audit，确认 sidecar attach 链不变。

### Verification

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_refresh_reference_compare_surface_updates_sidecar_and_runs_derived_refresh \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_refresh_reference_program_compare_surface_updates_sidecar_and_runs_derived_refresh \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_refresh_stat_snapshot_family_surface_updates_sidecar_and_runs_derived_refresh \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_export_mainline_status_includes_stat_snapshot_family_supplementary_surface
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" stable-surface-audit
```

### Exit criteria

1. 四条 supplementary surface 的刷新骨架统一。
2. 新增一条 future surface 时，不再需要复制大块 markdown/history/current-status 逻辑。

## 7. WP3: Next ISA-visible Control Command Families

### Goal

新增一组比 `FUSED_STEP` / `StatSnapshot` 更接近控制面本质的命令族：

1. `completion_consume_ref`
2. `completion_consume_fault_interlock_ref`
3. `fault_clear_ref`
4. `fault_clear_then_refault_ref`

这组 family 的价值是：它们直接锚定 current runtime gate 中已经存在但还未独立提升成程序级 family 的 completion visibility / fault lifecycle 语义。

### Files

- Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json`
- Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_runtime_gate_v1.json`
- Modify: `riscv_snn_isa_lab/architecture_model/model_types.py`
- Modify: `riscv_snn_isa_lab/architecture_model/program_profile_model.py`
- Modify: `riscv_snn_isa_lab/architecture_model/reference_machine.py`
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnSampleFirmware.h`
- Modify: `sst_dram_si/tools/test_generate_riscv_snn_firmware.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_firmware_tools.cc`
- Create: `riscv_snn_isa_lab/firmware_src/completion_consume_ref_toolchain/*`
- Create: `riscv_snn_isa_lab/firmware_src/completion_consume_fault_interlock_ref_toolchain/*`
- Create: `riscv_snn_isa_lab/firmware_src/fault_clear_ref_toolchain/*`
- Create: `riscv_snn_isa_lab/firmware_src/fault_clear_then_refault_ref_toolchain/*`
- Create: `riscv_snn_isa_lab/specs/completion_consume_ref*.json`
- Create: `riscv_snn_isa_lab/specs/completion_consume_fault_interlock_ref*.json`
- Create: `riscv_snn_isa_lab/specs/fault_clear_ref*.json`
- Create: `riscv_snn_isa_lab/specs/fault_clear_then_refault_ref*.json`

### Required landing

1. authority 新增 command-level semantic profile，不再把这些语义继续埋在 generic fault/progress mode 解释里。
2. reference machine 能执行这几类 control command，并给出 machine-readable terminal result。
3. runtime sample firmware 与 toolchain bridge 都能生成对应程序。
4. `reference_program_compare` 能把它们作为正式 family 进入 matrix。

### Step sequence

1. 先写 authority/reference-machine/program-compare 的失败测试。
2. 再补 architecture authority 和 runtime gate authority。
3. 然后扩 `architecture_model/` 的 command profile 与 reference execution。
4. 最后补 runtime sample registry、toolchain bridge 和 manifest evidence。
5. 完成后统一刷新 `reference_program_compare` stable surface。

### Verification

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_runtime_gate_family_policy_requires_declared_family \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_reference_program_compare_family_catalog_adds_snapshot_families_without_expanding_equiv_specs
python3 -m unittest "/home/xgy/remote/sst_dram_si/tools/test_generate_riscv_snn_firmware.py"
g++ -std=c++17 \
  -I "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" \
  -I "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api" \
  -I "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services" \
  -I "/home/xgy/remote/sst_install_mpi/include" \
  -I "/home/xgy/remote/sst_install_mpi/include/sst/core" \
  -c "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_firmware_tools.cc" \
  -o "/tmp/test_riscv_snn_firmware_tools.o"
```

### Exit criteria

1. 至少 4 条新 control-command family 同时具备 authority/runtime/toolchain/reference 三角闭环。
2. 这些 family 被纳入 `reference_program_compare`，但仍保持 supplementary-only。

## 8. WP4: Family Onboarding Dataization

### Goal

把“新增 family”从修改大量 Python 分支，推进成 authority + lane attachment 驱动的稳定接入路径。

### Files

- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/README.md`
- Create: `riscv_snn_isa_lab/family_lanes/reference-program-compare-lanes.json`
- Create: `riscv_snn_isa_lab/family_lanes/runtime-toolchain-bridge-lanes.json`

### Required landing

1. lane 文件只允许定义 attachment/materialization 关系，例如：
   - program profile name
   - expected evidence class
   - toolchain bridge required or optional
   - target supplementary surface
2. lane 文件**不是 authority**，不能重复定义：
   - fault_mode
   - progress_mode
   - required_checks
   - ABI semantics
3. `riscv_snn_lab.py` 只从 lane 中取装配决策，从 authority 中取语义真值。

### Step sequence

1. 先把当前 family 进入 `reference_program_compare` / toolchain bridge / runtime manifest 的装配关系盘点成显式表。
2. 写失败测试，确保缺 lane 或 lane/authority 冲突时能明确报错。
3. 把 family catalog 逻辑迁移成 lane-driven。
4. 保持现有 family 行为不变，先做等价迁移，再允许新 family 复用。

### Verification

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_run_reference_program_compare_matrix_accepts_stat_snapshot_family \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_refresh_reference_program_compare_surface_updates_sidecar_and_runs_derived_refresh
```

### Exit criteria

1. future family 不再需要在 `riscv_snn_lab.py` 里复制多处 `if family == ...` 分支。
2. lane 与 authority 的角色边界对外清晰可讲。

## 9. WP5: Runtime/Toolchain Bridge Unification

### Goal

解决“toolchain 有、runtime sample registry 没有”或“program compare 能看见 family，但 list-programs / matrix 看不见程序”的桥接分叉。

### Files

- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnSampleFirmware.h`
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `sst_dram_si/tools/test_generate_riscv_snn_firmware.py`
- Modify: `sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_firmware_tools.cc`
- Create: `riscv_snn_isa_lab/tools/program_bridge_catalog.py`

### Required landing

1. `list-programs`
2. runtime sample builder
3. toolchain program matrix
4. `reference_program_compare` family catalog
5. firmware metadata export

以上 5 条路径必须共享同一套 program bridge catalog，而不是各自维护“程序是否存在”的事实。

### Step sequence

1. 先把现有 sample/runtime/toolchain/program-compare 的程序存在性来源全部列出。
2. 写失败测试，确保 catalog 缺程序时会在所有入口一致失败，而不是有的能跑有的看不见。
3. 落 `program_bridge_catalog.py`，只作为 derived bridge registry，不作为 authority root。
4. 迁移现有入口并跑全量回归。

### Verification

```bash
cd "/home/xgy/remote"
python3 -m unittest "/home/xgy/remote/sst_dram_si/tools/test_generate_riscv_snn_firmware.py"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_reference_program_compare_family_catalog_adds_snapshot_families_without_expanding_equiv_specs
```

### Exit criteria

1. 不再出现 “toolchain/source/spec 就绪，但 runtime sample registry 缺程序” 这种桥接缝。
2. program existence 的事实来源缩成一处 derived catalog。

## 10. Recommended Sprint Breakdown

### Sprint 1

1. 完成 `WP1`
2. 完成 `WP2-A`，先把 helper skeleton 落地

### Sprint 2

1. 收完 `WP2-B`
2. 开始 `WP3-A` 的 authority/reference-machine 侧

### Sprint 3

1. 完成 `WP3` 的 runtime/toolchain/program-compare 闭环
2. 启动 `WP4`
3. 启动 `WP5`

### Sprint 4

1. 收完 `WP4`
2. 收完 `WP5`
3. 跑一轮完整 stable refresh / audit / research report

## 11. Final Acceptance Matrix

阶段收尾时至少要重新执行：

```bash
cd "/home/xgy/remote"
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" observer-refresh
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" mainline-refresh --group completion_overflow_optional
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" export-mainline-status
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" stable-surface-audit
python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" research-report
```

验收时必须能回答 5 个问题：

1. observer compact / freshness 的有效边界能不能只看 stable surfaces 就读出来？
2. 新 control-command families 有没有同时进入 authority/runtime/toolchain/reference 三角闭环？
3. 新增 family 时，`riscv_snn_lab.py` 是否还需要大面积加分支？
4. runtime sample 和 toolchain bridge 是否还可能出现程序存在性分叉？
5. 整个阶段完成后，stable sidecar 是否仍然是唯一 blocking gate？

## Archive: Previous Iteration Snapshot (Pre-2026-04-18)

以下内容保留为上一轮规划迭代的归档快照，只用于回看当时的阶段判断，不再作为当前执行入口。

### 0. 这阶段要解决什么

当前主线已经能稳定给出：

1. `runtime_bridge` 承载真实执行
2. required 6 family 的 blocking equivalence gate
3. `stable sidecar report` 作为唯一顶层 authority

但下一阶段真正缺的，不是再多加一堆 family，而是下面三类“隐式逻辑”要先转成显式 contract：

1. **required/optional family 的晋升与边界**
   - 现在结果稳定，但晋升准入规则仍主要散在 wrapper 逻辑和文档口径里
2. **family runtime gate 的 reason/check 语义**
   - 现在 `fault_mode/progress_mode` 能工作，但它们还主要是 Python 内部常量
3. **bit-level control-plane contract 的可导出真值**
   - `cmdq_tail`、accepted、completion visibility、fault clear/overwrite 这些语义已经形成口径，但还缺一条“从 authority 自动渲染给人和工具看”的链

因此本阶段的策略是：

1. 不先扩主线覆盖面
2. 先把主线 authority 写硬
3. 再给 future family 扩张准备一条不会分叉的 admission path

## Current Next Package: Architecture Semantic Freeze Package

这一段任务包是当前最合理的下一段工作，目标不是继续补更多 protocol family，也不是直接开写 `architecture_model/`，而是先把下一阶段需要的 architecture semantics 写硬。

### Package Goal

把当前 `riscv_snn_architecture_model_v1.json` 从 taxonomy authority 推进成语义 authority，明确：

1. `FUSED_STEP` 的架构边界
2. memory hierarchy 的结构与归属
3. event / fabric 的正式路径

### Why This Package Comes Next

如果跳过这一步直接进入 `architecture_model/` 代码实现，会出现：

1. reference model 自己发明状态机
2. counters 先于语义被实现
3. adapter 反过来替代设计决策

因此当前正确顺序必须是：

1. 先冻结语义
2. 再写 reference model
3. 再接 adapter

### Package Tasks

1. `Task 2A: FUSED_STEP semantic freeze`
   - Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json`
   - Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
   - Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
   - Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
   - Freeze:
     - `Idle`
     - `Accepted`
     - `Decoded`
     - `ResourcesReserved`
     - `Executing`
     - `OutboundDraining`
     - `BarrierWaiting`
     - `Completed`
     - `Faulted`
2. `Task 3A: memory hierarchy freeze`
   - Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json`
   - Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
   - Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
   - Freeze:
     - `ControlMemory`
     - `LocalStateMemory`
     - `SynapseMemory`
     - `BackingMemory`
     - `TransferPath`
3. `Task 3B: event/fabric taxonomy freeze`
   - Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json`
   - Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
   - Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
   - Freeze:
     - ingress receive
     - local classify
     - queue merge
     - execution consume
     - spike generate
     - egress enqueue
     - router transit
     - remote ingress commit

### Package Exit Criteria

这一段完成后，应该满足：

1. `riscv_snn_architecture_model_v1.json` 新增：
   - `fused_step_state_machine`
   - `memory_taxonomy`
   - `fabric_taxonomy`
2. 主线总结能明确回答：
   - `FUSED_STEP completion` 当且仅当什么成立
3. 可以明确区分：
   - architecture-visible state
   - microarchitectural state
   - simulator bookkeeping state
4. 当前 blocking gate 仍然不变：
   - `nightly-sidecar-report.json` 仍是唯一 top-level authority

### Package Landing Rules

这一段语义冻结包在工程上必须继续遵守四条硬约束：

1. 只允许把 architecture semantics 写进 `riscv_snn_architecture_model_v1.json`，不引入第二份 architecture metadata authority。
2. 只能通过 `riscv_snn_isa_lab/tools/riscv_snn_lab.py` 暴露读取入口，保持与 mainline/runtime/accel authority 同一加载纪律。
3. 新增验证优先写进既有的 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`，不为这段任务再分叉测试框架。
4. 这一包只冻结语义与读取/验证桥，不提前创建 `architecture_model/` reference model 子树，也不改默认 `snn` 主线。

### Current Code Landing Order

当前推荐的代码落地顺序是：

1. 先落 `Task 2A`，把 `FUSED_STEP` 的 completion/fault/state visibility 写成 machine-readable authority。
2. 再落 `Task 3A`，把 memory domain、共享边界、争用范围冻结下来。
3. 最后落 `Task 3B`，把 event/fabric path 与允许分歧点收成正式 taxonomy。
4. 只有三块都稳定后，才允许创建 `riscv_snn_isa_lab/architecture_model/` 的 reference model 子树。

### Task 2A Landing Plan: `FUSED_STEP` Semantic Freeze

**Files**

- Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json`
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Engineering intent**

1. 把 `FUSED_STEP` 从“状态名列表”冻结成正式 authority object。
2. 给后续 reference model 一条不可歧义的 completion 边界：
   - completion 当且仅当当前 step 的架构可见状态已经提交、
   - 本 step 产生的本地 outbound spike 已跨过本地 egress/fabric 交接边界、
   - 当前 barrier domain 的 release 条件已经满足并可见、
   - 且没有更高优先级 fault 抢占当前 completion。
3. 明确区分：
   - `architectural_state`
   - `microarchitectural_progress`
   - `simulator_bookkeeping`

**Concrete landing**

1. 在 `riscv_snn_lab.py` 新增：
   - `ARCHITECTURE_MODEL_AUTHORITY_PATH`
   - `load_architecture_model_authority(*, lab_root=LAB_ROOT)`
2. 在 `riscv_snn_architecture_model_v1.json` 新增 `fused_step_state_machine`：
   - `semantic_statement`
   - `completion_boundary`
   - `fault_boundary`
   - `visibility_domains`
   - `states`
3. `states` 顺序固定为：
   - `Idle`
   - `Accepted`
   - `Decoded`
   - `ResourcesReserved`
   - `Executing`
   - `OutboundDraining`
   - `BarrierWaiting`
   - `Completed`
   - `Faulted`
4. 每个状态最少包含：
   - `name`
   - `entry_condition`
   - `exit_condition`
   - `architecturally_visible`
   - `microarchitectural_only`
   - `simulator_bookkeeping_only`
   - `counter_groups`
5. 在 `test_riscv_snn_lab.py` 新增 targeted tests，至少覆盖：
   - authority 可被 `load_architecture_model_authority()` 正常读取
   - `authority_domain == "architecture_model_only"`
   - `top_level_gate_role == "none"`
   - `fused_step_state_machine.completion_boundary` 存在且非空
   - `states` 名称和顺序固定
   - `Completed` 为 architecture-visible
   - `ResourcesReserved` / `Executing` / `OutboundDraining` 不得标为 simulator-only
6. 运行验证：

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_load_architecture_model_authority_freezes_fused_step_states \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_fused_step_completion_boundary_is_machine_readable
jq '.' "/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json" >/dev/null
```

**Expected result**

1. `riscv_snn_lab.py` 可以像读取其他 authority 一样读取 architecture authority。
2. `FUSED_STEP` completion 语义首次以 machine-readable 形式被冻结。
3. 这一步不改 nightly gate，不改 runtime bridge，不引入新的 top-level artifact。

### Task 3A Landing Plan: Memory Hierarchy Freeze

**Files**

- Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Engineering intent**

1. 把当前 architecture model 中所有 memory-related object 的归属写硬，防止未来 reference model 或 adapter 各自发明“状态放哪一层”。
2. 冻结对后续建模最关键的五个 domain：
   - `ControlMemory`
   - `LocalStateMemory`
   - `SynapseMemory`
   - `BackingMemory`
   - `TransferPath`

**Concrete landing**

1. 在 authority 中新增 `memory_taxonomy`：
   - `semantic_statement`
   - `memory_domains`
2. 每个 memory domain 最少包含：
   - `name`
   - `contains`
   - `architecturally_visible`
   - `shared_with`
   - `contention_scope`
   - `persistence_scope`
   - `notes`
3. 最少冻结以下归属：
   - descriptor / CSR / completion / fault 状态属于 `ControlMemory`
   - neuron membrane / threshold / refractory / local-hot state 属于 `LocalStateMemory`
   - synapse weights / connectivity / fanout metadata 属于 `SynapseMemory`
   - DRAM / host-fed backing arrays 属于 `BackingMemory`
   - DMA-like movement / fill / spill / prefetch 路径属于 `TransferPath`
4. 在 `test_riscv_snn_lab.py` 新增 targeted tests，至少覆盖：
   - `memory_taxonomy` 存在
   - 五个 memory domain 名称完整且顺序稳定
   - `ControlMemory` 必须 architecture-visible
   - `LocalStateMemory` 与 `SynapseMemory` 必须 microarchitecturally modeled 但默认非 architecture-visible
   - `TransferPath` 必须显式带 `contention_scope`
5. 运行验证：

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_architecture_model_memory_taxonomy_freezes_required_domains
jq '.memory_taxonomy' "/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json" >/dev/null
```

**Expected result**

1. 后续 memory model / counter model 不再需要自己解释层次归属。
2. memory hierarchy 的抽象边界与 control-plane ABI authority 清晰解耦。

### Task 3B Landing Plan: Event/Fabric Taxonomy Freeze

**Files**

- Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Engineering intent**

1. 冻结 event 从本地接收到远端提交的正式路径，避免未来 queue/router/reference model 对路径阶段理解不一致。
2. 明确哪些分歧允许存在于 microarchitecture，而不应升级成 architectural mismatch。

**Concrete landing**

1. 在 authority 中新增 `fabric_taxonomy`：
   - `semantic_statement`
   - `stages`
   - `allowed_divergence_points`
2. `stages` 顺序固定为：
   - `ingress_receive`
   - `local_classify`
   - `queue_merge`
   - `execution_consume`
   - `spike_generate`
   - `egress_enqueue`
   - `router_transit`
   - `remote_ingress_commit`
3. 每个 stage 最少包含：
   - `name`
   - `description`
   - `architecturally_visible`
   - `primary_counters`
   - `blocking_sources`
4. `allowed_divergence_points` 至少固定：
   - `queue_occupancy`
   - `backpressure`
   - `multicast_expansion`
   - `memory_service_conflict`
5. 在 `test_riscv_snn_lab.py` 新增 targeted tests，至少覆盖：
   - `fabric_taxonomy.stages` 名称和顺序固定
   - `remote_ingress_commit` 必须存在
   - 所有 `allowed_divergence_points` 都被显式声明
   - `router_transit` / `queue_merge` 默认非 architecture-visible
6. 运行验证：

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_architecture_model_fabric_taxonomy_freezes_stage_order_and_divergence_points
jq '.fabric_taxonomy' "/home/xgy/remote/riscv_snn_isa_lab/spec_authority/riscv_snn_architecture_model_v1.json" >/dev/null
```

**Expected result**

1. 后续 reference model 可以直接据此实现 event/fabric tracing。
2. 可把 queue/backpressure/multicast 的差异明确限制在 microarchitectural divergence，而不是误当成 architecture breakage。

### Next Package After Semantic Freeze

只有 `Task 2A / Task 3A / Task 3B` 都完成并通过 targeted validation 后，才进入下一包：

1. Create: `riscv_snn_isa_lab/architecture_model/__init__.py`
2. Create: `riscv_snn_isa_lab/architecture_model/fused_step_model.py`
3. Create: `riscv_snn_isa_lab/architecture_model/memory_model.py`
4. Create: `riscv_snn_isa_lab/architecture_model/fabric_model.py`
5. Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`

进入这一包前必须再次确认：

1. 仍然不改默认 `snn`
2. 仍然不让 architecture-model authority 取代 nightly gate authority
3. reference model 只消费已冻结 authority，不回写 authority

## Current Next Major Stage: Architecture Model Reference Mainline

语义冻结包完成后，当前主线已经正式进入下一大阶段：

**`Architecture Model Reference Mainline`**

### Stage Goal

把 `riscv_snn_architecture_model_v1.json` 从“machine-readable semantic authority”推进成“machine-executable reference model input”，让 `riscv_snn_isa_lab` 具备：

1. 一个严格消费 authority 的 reference execution path
2. 一个最小但闭环的 `FUSED_STEP` 抽象执行机
3. 一个可导出的 memory/fabric accounting surface
4. 一个可与现有 `runtime_bridge` 做语义对齐比较的 adapter

### Why This Stage Comes Next

如果当前不进入 reference model 主线，而是继续补更多 taxonomy、更多 family、或者直接做复杂微架构探索，会出现三类分叉：

1. authority 已冻结，但没有真正执行者
2. adapter / compare surface 会反向定义语义
3. 新研究变量会建立在不可运行的抽象层之上

因此当前唯一合理顺序是：

1. 先做 authority-consuming reference model
2. 再做 runtime comparison bridge
3. 最后才开放新的研究变量

### Stage Hard Boundaries

这一大阶段必须继续遵守以下边界：

1. 不修改默认 `snn` 主线行为。
2. 不改变 `nightly-sidecar-report.json` 作为 top-level gate authority 的角色。
3. 不引入第二份 architecture metadata authority。
4. `architecture_model/` 子树只能消费 `riscv_snn_architecture_model_v1.json`，不能回写或替代 authority。
5. 本阶段优先构建 semantic reference model，不追求 cycle-accurate microarchitecture simulator。

### Stage Packages

#### Package A: Reference Model Skeleton

**Goal**

建立 `architecture_model/` 子树和最小 authority-consuming 骨架，但暂不运行真实 workload。

**Files**

- Create: `riscv_snn_isa_lab/architecture_model/__init__.py`
- Create: `riscv_snn_isa_lab/architecture_model/model_types.py`
- Create: `riscv_snn_isa_lab/architecture_model/fused_step_model.py`
- Create: `riscv_snn_isa_lab/architecture_model/memory_model.py`
- Create: `riscv_snn_isa_lab/architecture_model/fabric_model.py`
- Create: `riscv_snn_isa_lab/architecture_model/reference_machine.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Concrete landing**

1. 定义最小 dataclass/type surface：
   - fused-step state descriptors
   - memory domains
   - fabric stages
2. `reference_machine.py` 只负责：
   - 加载 authority
   - 校验必需 section 是否存在
   - 组合三块 model
3. 新增 targeted tests，至少覆盖：
   - authority 可被 skeleton 完整消费
   - 缺字段时明确失败
   - model objects 顺序与 authority 顺序一致

**Exit criteria**

1. `ReferenceMachine` 可实例化
2. `fused_step/memory/fabric` 三块模型可通过单一入口组装
3. 尚未执行 step，但 authority consumption 已稳定

#### Package B: Single-Step Reference Execution

**Goal**

让 reference model 跑通一个最小 `FUSED_STEP` 抽象执行闭环。

**Files**

- Modify: `riscv_snn_isa_lab/architecture_model/fused_step_model.py`
- Modify: `riscv_snn_isa_lab/architecture_model/reference_machine.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Concrete landing**

1. 引入最小 step input / step result 数据结构
2. 依据 authority 状态顺序推进：
   - `Accepted -> ... -> Completed/Faulted`
3. 明确区分输出：
   - architectural state
   - microarchitectural progress
   - simulator bookkeeping
4. 新增 targeted tests，至少覆盖：
   - 正常 completion 路径
   - fault 抢占 completion 路径
   - completion boundary 条件不满足时不得退休

**Exit criteria**

1. 至少一个抽象 step 样本可跑通到 `Completed`
2. 至少一个 fault 样本可跑通到 `Faulted`
3. 全部状态推进仍来自 authority，而不是硬编码另一套语义

#### Package C: Memory/Fabric Accounting

**Goal**

为 reference execution 增加可导出的 memory/fabric accounting，而不是只产出最终状态。

**Files**

- Modify: `riscv_snn_isa_lab/architecture_model/memory_model.py`
- Modify: `riscv_snn_isa_lab/architecture_model/fabric_model.py`
- Modify: `riscv_snn_isa_lab/architecture_model/reference_machine.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Concrete landing**

1. 为一次 step 执行记录：
   - `memory_events`
   - `fabric_events`
   - `divergence_observations`
2. 所有 memory/fabric 记录必须只使用 authority 中已经冻结的词表
3. 新增 targeted tests，至少覆盖：
   - memory access 可归类到五个 domains
   - fabric traversal 可归类到八个 stages
   - divergence 只能落在四个 allowed points

**Exit criteria**

1. 一次 reference step 可以导出结构化 accounting
2. accounting 不依赖新的隐式 taxonomy

**Current status**

`Package C` 已完成：`ReferenceStepResult` 现在已经稳定导出 `memory_events`、`fabric_events`、`divergence_observations`，并由 `ReferenceMachine.execute_fused_step(...)` 依据 frozen authority 词表产出 machine-readable accounting。当前这层仍然只是 semantic/reference accounting，不会反向改写 runtime authority，也没有改变默认 `snn` 主线。

#### Package D: Runtime Comparison Adapter

**Goal**

建立 reference model 与 `runtime_bridge` 的最小语义对齐桥。

**Files**

- Create: `riscv_snn_isa_lab/architecture_model/runtime_compare.py`
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Concrete landing**

1. 读取 canonical family 的最小输入/摘要
2. 跑 reference execution
3. 生成 machine-readable compare summary，至少包含：
   - completion/fault semantic alignment
   - memory domain alignment
   - fabric stage alignment
   - divergence classification
4. 新增 targeted tests，至少覆盖：
   - 对齐成功路径
   - 差异落入 allowed divergence points 的路径

**Exit criteria**

1. 至少一个 canonical family 可做 reference-vs-runtime compare
2. compare 结果不会反向改写 authority

**Current status**

`Package D` 已完成最小对接：`riscv_snn_isa_lab/architecture_model/runtime_compare.py` 现已提供 `compare_reference_to_runtime(...)`，能够对齐 terminal state、memory domains、fabric stages，并把 divergence 划分为 allowed / invalid 两类。该 compare adapter 继续只消费 `riscv_snn_architecture_model_v1.json` 中冻结的 divergence 词表，不引入第二份 metadata authority。

#### Package E: Research Surface Integration

**Goal**

把 reference model 以 derived research surface 方式挂入实验主线，但不提升为 blocking gate。

**Files**

- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/export_riscv_snn_research_report.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
- Modify: `TECH_PROGRESS.md`

**Concrete landing**

1. 新增 reference-only derived surface
2. 让 summary/report 能读取 reference compare 结果
3. 明确标注这是 research sidecar，不是 top-level gate
4. 新增 targeted tests，至少覆盖：
   - derived surface 可生成
   - top-level gate authority 未变化
   - default `snn` path 未受影响

**Exit criteria**

1. reference outputs 可读、可导出、可追踪
2. 仍不改变当前 stable gate discipline

**Current status**

`Package E` 已完成最小 research-surface 接入：`reference_compare` 现在已经作为 non-blocking supplementary surface 接入 `riscv_snn_lab.py`、research report、current-mainline-status 渲染链。它会生成稳定 report/summary/current-status surface，并写回 sidecar 的 `supplementary_surfaces.reference_compare`，但不会提升为 top-level gate，也不会改变默认 `snn` 执行路径。

### Stage Completion Criteria

这一大阶段完成后，应该满足：

1. `riscv_snn_isa_lab/architecture_model/` 子树存在且可实例化 reference machine。
2. 至少一个 canonical `FUSED_STEP` 样本可在 reference model 中跑通。
3. memory/fabric accounting 可导出。
4. 至少一个 canonical family 可做 reference-vs-runtime compare。
5. 所有 reference surfaces 仍然是 derived surfaces。
6. 默认 `snn` 主线、nightly gate authority、mainline authority discipline 均保持不变。

## 2. Follow-On Stage: Multi-Step Reference Program Model

当前 follow-on stage 已经不再只是 single-step `reference_compare` 的 operator 化，而是继续向前推进到：

**`Multi-Step Reference Program Model`**

### Stage Goal

把 frozen family 从“一个 step 的 reference/runtime 对齐”推进成“一段 program trace 的 reference/runtime 对齐”，并继续满足：

1. supplementary only
2. non-blocking
3. 不改变 stable sidecar 的 top-level gate authority
4. 不引入第二份 architecture authority

### Current Landing

#### Task A: Program Trace Model

当前 `architecture_model/` 已新增：

1. `ReferenceProgramStep`
2. `ReferenceProgramRequest`
3. `ReferenceProgramTraceEntry`
4. `ReferenceProgramResult`
5. `ReferenceMachine.execute_program(...)`

这让 reference machine 现在可以直接表达：

1. `BarrierWaiting -> Completed`
2. `Faulted -> clear -> Faulted`
3. `Faulted -> overwrite -> Faulted`

#### Task B: Program Compare Adapter

当前已新增 `compare_reference_program_to_runtime(...)`，用于冻结 program-level compare 的最小语义面。

它当前至少对齐：

1. `terminal_state_sequence`
2. `completion_step_indices`
3. `fault_step_indices`
4. `barrier_wait_step_indices`
5. `clear_fault_before_step_indices`
6. `overwrite_fault_step_indices`
7. `fault_snapshot_sequence`
8. per-step memory / fabric / divergence alignment

#### Task C: Command Plane

当前已新增三条正式命令：

1. `reference-program-compare`
2. `reference-program-compare-matrix`
3. `reference-program-compare-refresh`

#### Task D: Stable Surface Closure

当前已新增 program-level stable surface：

1. `reference-program-compare-history.json`
2. `reference-program-compare-nightly-report.json`
3. `reference-program-compare-nightly-summary.md`
4. `reference-program-compare-current-status.md`

并且它已经进入：

1. `nightly-sidecar-report.json -> supplementary_surfaces.reference_program_compare`
2. `nightly-sidecar-observer-summary.json -> supplementary_surface_rollups.reference_program_compare`
3. `current-mainline-status.md`
4. `nightly-sidecar-summary.md`

#### Task E: Stable Refresh / Audit Alignment

当前 `observer-refresh` 会在有输入时刷新 program-level supplementary surface，在没有 dated inputs 的环境里则跳过，不让 non-blocking surface 反向卡住 observer / research / current-mainline 主链。

同时 `stable-surface-audit` 也已经能沿现有 supplementary surface contract 审计 `reference_program_compare`。

### Recommended Next Package

下一段最值得做的不是再加第四条 compare surface，而是继续把 program-level model 做成更正式的“program semantics bridge”：

1. 把 family -> program trace 的映射从 Python helper 收到 machine-readable authority 子面
2. 给 program trace 增加更明确的 per-step control event vocabulary
3. 补 program-level dated freshness coverage 与 observer compact refresh 入口
4. 继续保持它是 supplementary / non-blocking surface，而不是新 gate

## 1. 范围与出口

### In Scope

1. required-family authority 显式化
2. runtime gate / family policy authority 显式化
3. bit-level control-plane contract renderer / validator
4. optional family admission audit
5. stable sidecar 与 research surfaces 的 authority discipline 持续收硬

### Out of Scope

1. 新增大规模 datapath 功能
2. 引入第二份 metadata authority
3. 把 queue optional family 直接升格成 blocking gate
4. 改写 `CoreShell` / compute core 分层
5. 把 observer/research surface 升成新的 top-level gate

### 阶段出口

本阶段完成后，应满足：

1. required family 与 optional group 不再依赖隐式 Python 常量解释
2. runtime gate 的 family policy / reason id / check id 有单一 authority
3. bit-level control-plane contract 可从 authority 自动导出给文档和工具使用
4. optional family 有一条显式 promotion audit 路径，但默认 gate 不变
5. stable sidecar 继续是唯一 top-level authority，observer/research 仍是 derived surface

## Task 1: 把 required gate authority 从隐式常量提炼成 machine-readable 真值

**Files:**
- Create: `riscv_snn_isa_lab/spec_authority/riscv_snn_mainline_gate_v1.json`
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Step 1: 先写失败测试，冻结 required/optional surface 必须来自 authority JSON**

在 `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py` 新增测试，要求：

```python
def test_mainline_gate_authority_file_exists_and_declares_required_families(self) -> None:
    authority = riscv_snn_lab.load_mainline_gate_authority(...)
    self.assertEqual(
        authority["required_families"],
        [
            "barrier_wfi_order_ref",
            "external_dyn_desc_bad_policy_ref",
            "external_dyn_desc_fault_overwrite_chain_ref",
            "external_dyn_desc_fault_rearm_ref",
            "external_dyn_desc_fault_ref",
            "external_dyn_desc_ref",
        ],
    )

def test_authority_required_families_reads_machine_readable_gate_authority(self) -> None:
    self.assertEqual(
        riscv_snn_lab.authority_required_families(),
        riscv_snn_lab.load_mainline_gate_authority(... )["required_families"],
    )

def test_queue_optional_group_is_declared_as_nonblocking_in_gate_authority(self) -> None:
    authority = riscv_snn_lab.load_mainline_gate_authority(...)
    self.assertEqual(authority["optional_groups"]["queue_optional"]["blocking"], False)
```

**Step 2: 跑 targeted tests，确认当前没有这份 authority surface**

Run:

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_mainline_gate_authority_file_exists_and_declares_required_families \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_authority_required_families_reads_machine_readable_gate_authority \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_queue_optional_group_is_declared_as_nonblocking_in_gate_authority \
  -v
```

Expected:

```text
FAIL: missing gate authority loader or file
```

**Step 3: 增加 `riscv_snn_mainline_gate_v1.json`**

推荐最小形状：

```json
{
  "schema_version": 1,
  "producer": "riscv_snn_isa_lab",
  "required_families": [...],
  "optional_groups": {
    "queue_optional": {
      "families": ["queue_backpressure_ref", "completion_queue_overflow_ref"],
      "blocking": false
    }
  },
  "promotion_contract": {
    "queue_optional": {
      "requires_family_equiv_pass": true,
      "requires_multi_date_freshness": true,
      "requires_reason_taxonomy_clean": true,
      "requires_explicit_review": true
    }
  }
}
```

**Step 4: 让 `riscv_snn_lab.py` 只从这份 authority 派生 required family**

至少替换这些逻辑的真值来源：

1. `authority_required_families()`
2. sidecar `required_families`
3. `EQUIV_MATRIX_GROUPS["queue_optional"]`

但要保持：

1. builder/toolchain matrix 程序集可以继续由 `REFERENCE_REGRESSION_PROGRAMS` 驱动
2. blocking gate family 不再隐式跟随 regression program 集合变化

**Step 5: 增加只读 explain 入口，方便操作层查看当前 gate authority**

新增例如：

```bash
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" explain-mainline
```

输出至少包含：

1. authority file path
2. required families
3. optional groups
4. stable top-level authority path

**Step 6: 跑总集回归**

Run:

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
```

Expected:

```text
OK
```

## Task 2: 把 family runtime gate policy 与 reason/check taxonomy 提炼成 authority

**Files:**
- Create: `riscv_snn_isa_lab/spec_authority/riscv_snn_runtime_gate_v1.json`
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Step 1: 先写失败测试，冻结 family policy 必须来自 authority**

新增测试：

```python
def test_runtime_gate_authority_declares_fault_and_progress_modes(self) -> None:
    authority = riscv_snn_lab.load_runtime_gate_authority(...)
    self.assertEqual(authority["families"]["external_dyn_desc_ref"]["fault_mode"], "quiescent")
    self.assertEqual(authority["families"]["external_dyn_desc_fault_ref"]["fault_mode"], "accepted_fault_required")
    self.assertEqual(authority["families"]["barrier_wfi_order_ref"]["timing_mode"], "wfi_barrier_completion_visibility")

def test_runtime_gate_reason_ids_are_declared_in_authority(self) -> None:
    authority = riscv_snn_lab.load_runtime_gate_authority(...)
    self.assertIn("runtime_bridge_expected_fault_missing", authority["reason_ids"])
    self.assertIn("runtime_bridge_completion_visibility_missing", authority["reason_ids"])
```

**Step 2: 跑 targeted tests，确认当前 family policy 仍主要散在 Python 常量**

Run:

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_runtime_gate_authority_declares_fault_and_progress_modes \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_runtime_gate_reason_ids_are_declared_in_authority \
  -v
```

Expected:

```text
FAIL
```

**Step 3: 建立 `riscv_snn_runtime_gate_v1.json`**

推荐最小结构：

```json
{
  "schema_version": 1,
  "producer": "riscv_snn_isa_lab",
  "reason_ids": [...],
  "check_ids": [...],
  "families": {
    "external_dyn_desc_ref": {
      "fault_mode": "quiescent",
      "progress_mode": "forward_progress_expected",
      "fault_lifecycle_mode": "none"
    }
  }
}
```

至少覆盖：

1. required 6 family
2. queue optional 2 family
3. reason id 列表
4. check id 列表

**Step 4: 让 runtime gate 逻辑只从 authority 读 policy，不再直接信任散落常量**

最少替换：

1. `EQUIV_FAMILY_POLICIES`
2. `_runtime_bridge_gate(...)`
3. `run_equivalence()` summary 里的 `family_policy`

要求：

1. artifact 输出的 `family_policy` 来自 authority 原文
2. `gate_reasons` / `checks` 的 id 与 authority 对齐

**Step 5: 增加 explain 入口，帮助开发者理解单条 family 为什么会 PASS/FAIL**

新增例如：

```bash
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" explain-runtime-gate --family external_dyn_desc_fault_ref
```

输出至少包含：

1. family policy
2. required checks
3. allowed completion/fault signature
4. stable reason ids

**Step 6: 跑回归与代表性 family smoke-equivalence**

Run:

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family external_dyn_desc_ref
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family external_dyn_desc_fault_ref
```

Expected:

```text
tests OK
equiv summaries still PASS
```

## Task 3: 把 bit-level control-plane contract 从 authority 自动渲染出来

**Files:**
- Modify: `riscv_snn_isa_lab/spec_authority/riscv_snn_accel_v1.json`
- Create: `riscv_snn_isa_lab/tools/export_riscv_snn_control_plane_contract.py`
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Step 1: 先写失败测试，冻结 control-plane renderer 的最低输出**

新增测试：

```python
def test_control_plane_contract_renderer_exports_doorbell_completion_and_fault_sections(self) -> None:
    text = export_riscv_snn_control_plane_contract.render_markdown(...)
    self.assertIn("Doorbell", text)
    self.assertIn("Accepted", text)
    self.assertIn("Completion Visibility", text)
    self.assertIn("Fault Clear And Overwrite", text)

def test_control_plane_contract_renderer_uses_machine_readable_authority_keys(self) -> None:
    authority = json.loads(...)
    self.assertIn("doorbell_rules", authority)
    self.assertIn("ownership_rules", authority)
    self.assertIn("fault_semantics", authority)
```

**Step 2: 跑 targeted tests，确认当前缺少专门 renderer**

Run:

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_control_plane_contract_renderer_exports_doorbell_completion_and_fault_sections \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_control_plane_contract_renderer_uses_machine_readable_authority_keys \
  -v
```

Expected:

```text
FAIL
```

**Step 3: 只在现有 ABI authority 上补最小必要字段，不新造第二份 bit-level 真值**

要求继续使用：

1. `riscv_snn_accel_v1.json`

需要时补齐或规范化这些字段：

1. `doorbell_rules`
2. `ownership_rules`
3. `completion_layout`
4. `fault_semantics`
5. `event_pending_bits`

避免创建另一份 `control_plane_v1.json`，否则会制造第二份 authority。

**Step 4: 新增 renderer 工具**

建议输出两种形式：

1. machine-readable normalized JSON
2. human-readable Markdown

CLI 可以收在 lab wrapper 下面，例如：

```bash
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" export-control-plane-contract \
  --output "/tmp/riscv_snn_control_plane_contract.md"
```

**Step 5: 让文档不再手写大段 contract 文字，而是明确引用 renderer 产物或 authority key**

更新：

1. `README.md`
2. mainline summary 文档

要求：

1. 文档继续解释语义
2. 但 key 名和顺序必须能指回 authority / renderer，不再成为第二份真值

**Step 6: 跑回归与导出 smoke**

Run:

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" export-control-plane-contract \
  --output "/tmp/riscv_snn_control_plane_contract.md"
```

Expected:

```text
tests OK
markdown file generated
```

## Task 4: 给 optional family 建一条显式 admission audit，而不是直接晋升

**Files:**
- Modify: `riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

**Step 1: 先写失败测试，冻结 queue optional family 目前只能走 admission audit**

新增测试：

```python
def test_family_admission_audit_reports_queue_optional_as_nonblocking(self) -> None:
    summary = riscv_snn_lab.run_family_admission_audit(group="queue_optional", ...)
    self.assertEqual(summary["group"], "queue_optional")
    self.assertEqual(summary["blocking"], False)
    self.assertIn("promotion_ready", summary)

def test_sidecar_does_not_promote_queue_optional_into_required_gate(self) -> None:
    report = riscv_snn_lab.run_ci_sidecar(with_queue_equivalence=True, ...)
    self.assertNotIn("queue_backpressure_ref", report["required_families"])
```

**Step 2: 跑 targeted tests，确认当前没有 admission audit 入口**

Run:

```bash
cd "/home/xgy/remote"
python3 -m unittest \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_family_admission_audit_reports_queue_optional_as_nonblocking \
  riscv_snn_isa_lab.tools.test_riscv_snn_lab.RiscvSnnLabTest.test_sidecar_does_not_promote_queue_optional_into_required_gate \
  -v
```

Expected:

```text
FAIL
```

**Step 3: 实现 `family-admission-audit`**

建议它只做 research-only 判断，输入来自：

1. mainline gate authority
2. runtime gate authority
3. queue optional equivalence matrix
4. stable history / sidecar authority

输出至少包含：

1. `group`
2. `families`
3. `blocking`
4. `promotion_ready`
5. `reasons`
6. `required_contracts`
7. `summary_path`

**Step 4: 明确它是 non-blocking surface**

要求：

1. 不进 `required_families`
2. 不改 `stable sidecar` 的默认 gate 判定
3. 可以在 sidecar / research-report 里挂 research-only compact surface，但不扩权

**Step 5: 跑 queue optional 路径回归**

Run:

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv-matrix --group queue_optional
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" family-admission-audit --group queue_optional
```

Expected:

```text
tests OK
queue optional matrix produced
admission audit produced without altering required gate
```

## Task 5: 做一次 fresh mainline hardening closure，并更新稳定文档

**Files:**
- Modify: `riscv_snn_isa_lab/README.md`
- Modify: `docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
- Modify: `TECH_PROGRESS.md`

**Step 1: 更新主线文档，只描述最新 authority，不描述历史演进**

要求同步更新：

1. `README.md`
2. `2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`

内容重点：

1. mainline gate authority 路径
2. runtime gate authority 路径
3. control-plane contract renderer 路径
4. optional family admission audit 路径
5. stable sidecar 仍是唯一 top-level authority

**Step 2: 跑完整 fresh 验证**

Run:

```bash
cd "/home/xgy/remote"
python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" runtime-bridge-preflight \
  --spec "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_runtime_bridge.json"
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family external_dyn_desc_ref
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" equiv --family external_dyn_desc_fault_ref
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" sidecar --with-equivalence
python3 "riscv_snn_isa_lab/tools/riscv_snn_lab.py" research-report
```

Expected:

```text
tests OK
preflight status = ok
reference family PASS
fault family PASS
stable sidecar gate_ok = true
```

**Step 3: append-only 更新 `TECH_PROGRESS.md`**

必须记录：

1. 新增 authority 文件
2. 新增 renderer / audit 命令
3. fresh artifact 路径
4. required gate 未扩权
5. optional family 仍为 non-blocking

**Step 4: 输出阶段收口结论**

必须能明确说出：

1. 当前 blocking mainline 由哪份 authority file 和哪份 stable report 定义
2. optional family 如何被评估但不升格
3. future family 想进入 required gate 需要满足哪些 admission contract

## 推荐执行顺序

推荐严格按下面顺序推进，不要并行打散：

1. Task 1：mainline gate authority
2. Task 2：runtime gate authority
3. Task 3：control-plane contract renderer
4. Task 4：optional family admission audit
5. Task 5：fresh closure + docs + progress

原因：

1. Task 1 定义了 blocking/optional 的边界
2. Task 2 定义了 family 为什么 PASS/FAIL
3. Task 3 让 bit-level contract 不再靠文档口述
4. Task 4 才能在不扩权的前提下评估 queue optional family
5. Task 5 才能给出可信的 stable artifact closure

## 最终交付物

本阶段完成后，至少应新增或稳定以下产物：

1. `riscv_snn_isa_lab/spec_authority/riscv_snn_mainline_gate_v1.json`
2. `riscv_snn_isa_lab/spec_authority/riscv_snn_runtime_gate_v1.json`
3. `riscv_snn_isa_lab/tools/export_riscv_snn_control_plane_contract.py`
4. `riscv_snn_lab.py explain-mainline`
5. `riscv_snn_lab.py explain-runtime-gate`
6. `riscv_snn_lab.py family-admission-audit`
7. 更新后的 stable docs 与 fresh validation evidence

## 执行提醒

1. 不要在这个阶段顺手扩更多 family 进入 blocking gate。
2. 不要让 observer / research surface 获取新的 authority 身份。
3. 不要为 renderer 再创建第二份 bit-level authority 文件。
4. 不要把 `REFERENCE_REGRESSION_PROGRAMS` 继续混同于 `required_families`。
5. 所有新增 surface 先有失败测试，再有实现，再有 fresh artifact。
