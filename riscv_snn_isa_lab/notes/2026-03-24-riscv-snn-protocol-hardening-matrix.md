# 2026-03-24 RISC-V SNN Protocol Hardening Matrix

> Current note (2026-04-09):
> 这份矩阵保留的是 `2026-03-24` 附近的协议收硬语境，适合作为历史覆盖面说明，不应直接当成当前主线状态。
>
> 当前 authoritative 文档请优先看：
> 1. `/home/xgy/remote/riscv_snn_isa_lab/README.md`
> 2. `/home/xgy/remote/docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
> 3. `/home/xgy/remote/riscv_snn_isa_lab/references/current-mainline-status.md`
>
> 当前已经晚于这份矩阵的新增正式面包括：
> 1. `observer-history-refresh`
> 2. `observer-fail-recovery`
> 3. `stable-surface-audit`
> 4. supplementary `compare` attach / history / audit 链

## 1. 这份矩阵回答什么

这份矩阵不是自动评分脚本，而是当前阶段的固定 compare surface。

它回答三件事：

1. 现在有哪些 sample / bridge 已经落地成证据。
2. 每条证据分别覆盖 success、fault、bad-policy 中的哪一类语义。
3. 哪些结论已经足够可信，哪些还只是 reference 级、或者仍未冻结。

---

## 2. 当前矩阵

| family | program | expected behavior | source | unit | validate | smoke | manifest | status |
|---|---|---|---|---|---|---|---|---|
| canonical | `external_p0` | success | sample builder | yes | yes | yes | yes | stable canonical smoke |
| canonical | `external_dyn_desc` | success | sample builder | yes | yes | yes | yes | stable canonical runtime-descriptor smoke |
| additive reference | `external_dyn_desc_ref` | success + queue/completion ordering | sample builder | yes | yes | yes | yes | stable bit-level success reference |
| additive reference | `external_dyn_desc_fault_ref` | fault-after-accept + `msnnfault` alignment | sample builder | yes | yes | yes | yes | stable fault reference |
| additive reference | `external_dyn_desc_bad_policy_ref` | bad-policy + no committed progress | sample builder | yes | yes | yes | yes | stable policy reference |
| additive reference | `external_dyn_desc_fault_rearm_ref` | `msnnfault` clear 后再次 accepted-fault，并检查第二次 fault snapshot 覆盖第一次可见值 | sample builder | yes | yes | yes | yes | stable clear-then-refault reference |
| toolchain bridge | `external_dyn_desc_ref_toolchain` | success + builder-equivalent control-plane path | bare-metal toolchain | build/compare | yes | yes | yes | stable minimal bridge |
| toolchain bridge | `external_dyn_desc_fault_ref_toolchain` | fault-after-accept + builder-equivalent fault payload/`msnnfault` path | bare-metal toolchain | build/compare | yes | yes | yes | stable fault bridge |
| toolchain bridge | `external_dyn_desc_bad_policy_ref_toolchain` | bad-policy + zero-progress + builder-equivalent `msnnfault` path | bare-metal toolchain | build/compare | yes | yes | yes | stable policy bridge |
| toolchain bridge | `external_dyn_desc_fault_rearm_ref_toolchain` | `msnnfault` clear + second fault overwrite，与 builder reference 等价 | bare-metal toolchain | build/compare | yes | yes | yes | stable clear-then-refault bridge |
| toolchain bridge | `external_dyn_desc_fault_overwrite_chain_ref_toolchain` | 两次 `msnnfault` clear 后第三次 accepted fault overwrite，与 builder reference 等价 | bare-metal toolchain | build/compare | yes | yes | yes | stable overwrite-chain bridge |

---

## 3. 已冻结结论

下面这些结论，当前已经有足够证据支撑：

1. `cmdq_tail` 是当前 `riscv_snn` v1.1 control-plane 的唯一 architectural doorbell。
2. success path 至少已有两层独立证据：
   - builder reference
   - toolchain bridge
3. fault / policy path 现在也各自已有两层独立证据：
   - builder reference
   - toolchain bridge
4. `completion.status_code`、`completion.aux0/aux1` 与 `msnnfault` 的参考合同已经被单元测试、reference firmware、toolchain bridge 三层覆盖。
5. `msnnfault` software-clear 的最小合同已经冻结成：
   - `write value[15:0] == 0` -> visible `msnnfault` 清零
   - `EV_FAULT` 仍需单独 ack
   - clear 之后再次 accepted fault 时，新的 visible fault snapshot 可以按真实 slot 覆盖先前值
6. 当前 lab 目录已经不再只是静态资产库，而是具备：
   - sample list
   - generate
   - validate
   - smoke
   - register
   这五类薄编排能力。
7. 旧 `fault_ref_toolchain` / `fault_rearm_ref_toolchain` 的已知 stale 常量已经被移除，并且修正后的 bridge 已重新 smoke + compare。
8. 当前已经有两条 committed 的本地 protocol harness：
   - builder/reference harness：`tests/test_riscv_snn_firmware_protocol.cc`
   - toolchain bridge harness：`tests/test_riscv_snn_toolchain_firmware_protocol.cc`
   两者在文件级隔离下分别验证 builder authority 与五条 toolchain ELF 的 final completion / `msnnfault` / GPR 末态，不再只依赖 mesh smoke compare。

---

## 4. 仅 reference 级成立的结论

下面这些结论目前成立，但仍然只是 reference 级，不应过度外推：

1. `external_dyn_desc_fault_ref` 能说明 reserved flag fault 的可见性合同成立；
   但它不代表所有 fault 类型都已冻结。
2. `external_dyn_desc_bad_policy_ref` 能说明 bad-policy + `msnnstep==0` 的观察面成立；
   但它不代表未来 reject-before-accept 语义已经实现。
3. `external_dyn_desc_fault_rearm_ref` 能说明最小 clear-then-refault overwrite 合同已经被 reference firmware 固化；
   但它不代表更复杂嵌套 fault 或多次覆盖语义已经全部冻结。
4. 这五条 toolchain bridge 能说明最小 bare-metal toolchain 可以对齐 success / fault / bad-policy / clear-then-refault / overwrite-chain 五条 reference；
   但它不代表所有 sample 都已经有 toolchain 等价版本。

---

## 5. 明确尚未冻结的方向

下面这些方向仍然不能写成“已完成”：

1. `Xsnndl1p0` 自定义 opcode 编码
2. fault 全分类与统一辅助字段语义
3. `msnnfault` software-clear 的更复杂嵌套 / 多次覆盖 fault 语义
4. 更复杂 runtime / trap handler / interrupt delivery 机制
5. RX debug ring 的更高层软件接口
6. source -> ELF -> protocol 的自动化 bridge drift 审计

---

## 6. 当前最小 compare 结论

builder reference vs toolchain bridge 当前最稳的一句结论是：

**在 `external_dyn_desc_ref`、`external_dyn_desc_fault_ref`、`external_dyn_desc_bad_policy_ref`、`external_dyn_desc_fault_rearm_ref`、`external_dyn_desc_fault_overwrite_chain_ref` 这五条 reference 上，两条来源不同的 firmware 产物都在现有 smoke compare surface 上等价。**

而对外口径仍应保持保守：

**当前已经证明的是“最小 bare-metal toolchain 能对齐这五条 reference 的 compare surface”，还不是“toolchain 版已经成为新的 authority”。**

这就是下一阶段继续推进时必须保持的真实口径。

---

## 7. 2026-03-25 automation closure update

相较于 2026-03-24 这份矩阵草案，下面两条已经在 2026-03-25 被真正补齐：

1. 显式 experimental regression surface
   - `riscv_snn_isa_lab/tools/riscv_snn_lab.py matrix --group builder --register`
   - `riscv_snn_isa_lab/tools/riscv_snn_lab.py matrix --group toolchain --register`
   - 对应真实摘要：
     - `riscv_snn_isa_lab/references/2026-03-25-builder-regress-matrix.json`
     - `riscv_snn_isa_lab/references/2026-03-25-toolchain-regress-matrix.json`
2. source -> ELF -> manifest 的自动化 bridge drift audit
   - `riscv_snn_isa_lab/tools/riscv_snn_lab.py audit --group toolchain --protocol`
   - 对应真实摘要：
     - `riscv_snn_isa_lab/references/2026-03-25-toolchain-bridge-audit.json`
   - 当前结论：
     - 五条 toolchain bridge 全部 `manifest_match == true`
     - `all_ok == true`

因此，`source -> ELF -> protocol` 自动化 bridge drift 审计，已经不应再写成“尚未冻结”；现在更准确的说法是：

**自动化审计入口已经落地，但更复杂 fault 全分类、runtime/trap delivery 与更高层 RX software interface 仍未冻结。**

再往前一步，2026-03-25 这轮也已经把它们收束成一条显式 nightly gate：

1. `riscv_snn_isa_lab/tools/riscv_snn_lab.py nightly`
2. 顶层索引：
   - `riscv_snn_isa_lab/references/2026-03-25-nightly-index.json`

这份 nightly index 不是新的 authority；它只是把：

1. builder matrix summary
2. toolchain matrix summary
3. toolchain audit summary

合并成同一张 family-level machine-readable 证据表，方便后续独立 gate / sidecar CI 使用。

而在 2026-03-25 当前状态下，这条线又往前收了一步：

1. stable history index
   - `riscv_snn_isa_lab/references/nightly-history-index.json`
2. stable sidecar gate report
   - `riscv_snn_isa_lab/references/nightly-sidecar-report.json`
3. isolated sidecar entrypoint
   - `riscv_snn_isa_lab/ci/nightly_sidecar.py`

这表示现在不仅有 dated nightly snapshot，也已经有适合 automation 长期读取的稳定路径。
