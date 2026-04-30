# 2026-03-24 Toolchain Bridge Status

> Current note (2026-04-09):
> 这份文档保留的是 toolchain bridge 首次稳定落地时的状态说明，当前仍可用于理解 bridge 的边界与最小资产，但不再代表完整主线现状。
>
> 当前 authoritative 文档请优先看：
> 1. `/home/xgy/remote/riscv_snn_isa_lab/README.md`
> 2. `/home/xgy/remote/docs/plans/nextarc/2026-03-30-snndl-riscv-snn-mainline-technical-summary.md`
> 3. `/home/xgy/remote/riscv_snn_isa_lab/references/current-mainline-status.md`
>
> 需要特别注意：
> 1. toolchain bridge 仍然是主线证据的一部分，但不是新的 top-level authority。
> 2. 当前主线是否成立，要以 stable sidecar 和 stable refresh audit 为准，而不是只看 bridge smoke/compare。

## 1. 目标

这一条记录只回答一个问题：

`external_dyn_desc_ref`、`external_dyn_desc_fault_ref`、`external_dyn_desc_bad_policy_ref`、
`external_dyn_desc_fault_rearm_ref`、`external_dyn_desc_fault_overwrite_chain_ref`
能不能在不改 sample-builder authority 的前提下，用真实 bare-metal toolchain 产出独立 ELF，并跑通同一条 `riscv_snn` control-plane 合约。

当前答案是：

**可以，且本机已经用 `clang 22 + lld 22` 跑通 success / fault / bad-policy / clear-then-refault / overwrite-chain 五条最小桥接版 smoke。**

---

## 2. 环境探测结果

- `riscv64-unknown-elf-gcc`：未发现
- `riscv64-elf-gcc`：未发现
- `clang`：`/usr/bin/clang`
- `clang --version`：`Ubuntu clang version 22.0.0`
- `ld.lld --version`：`Ubuntu LLD 22.0.0`

因此本阶段选择的桥接路径是：

`clang --target=riscv64-unknown-elf -fuse-ld=lld`

这满足“先证明真实 toolchain 可以走同一 contract”的目标，同时没有为了跑通而去改 builder sample authority。

---

## 3. 当前文件落点

- source root：
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_ref_toolchain`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_ref_toolchain`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_bad_policy_ref_toolchain`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_rearm_ref_toolchain`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_overwrite_chain_ref_toolchain`
- output ELF：
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_ref_toolchain.elf`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_fault_ref_toolchain.elf`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_bad_policy_ref_toolchain.elf`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_fault_rearm_ref_toolchain.elf`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_fault_overwrite_chain_ref_toolchain.elf`
- replay spec：
  - `/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_toolchain.json`
  - `/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref_toolchain.json`
  - `/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref_toolchain.json`
  - `/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_toolchain.json`
  - `/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_overwrite_chain_ref_toolchain.json`
- smoke manifest：
  - `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-dyn-desc-ref-toolchain-smoke.md`
  - `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-dyn-desc-fault-ref-toolchain-smoke.md`
  - `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-dyn-desc-bad-policy-ref-toolchain-smoke.md`
  - `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-dyn-desc-fault-rearm-ref-toolchain-smoke.md`
  - `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-dyn-desc-fault-overwrite-chain-ref-toolchain-smoke.md`

源文件保持最小：

- `crt0.S`
- `main.S`
- `linker.ld`
- `Makefile`

没有引入 libc/newlib，也没有新增任何 sample metadata authority。

---

## 4. 语义对齐范围

toolchain bridge 当前对齐下面五条 builder reference：

| builder reference | toolchain bridge | 对齐重点 |
|---|---|---|
| `external_dyn_desc_ref` | `external_dyn_desc_ref_toolchain` | success path、`cmdq_head/cmpq_tail`、completion token/status |
| `external_dyn_desc_fault_ref` | `external_dyn_desc_fault_ref_toolchain` | fault-after-accept、completion `aux0/aux1`、`msnnfault` |
| `external_dyn_desc_bad_policy_ref` | `external_dyn_desc_bad_policy_ref_toolchain` | bad-policy、`msnnstep==0`、`msnnfault` |
| `external_dyn_desc_fault_rearm_ref` | `external_dyn_desc_fault_rearm_ref_toolchain` | `msnnfault` clear 之后再次 fault、第二次 fault snapshot 覆盖第一次可见值 |
| `external_dyn_desc_fault_overwrite_chain_ref` | `external_dyn_desc_fault_overwrite_chain_ref_toolchain` | 两次 clear 之后第三次 accepted-fault snapshot 覆盖前一次可见 fault 值 |

五条 bridge 复刻的共同 control-plane 观察面包括：

1. 读取 `cmdq_base/cmpq_base`
2. 在本地 ring 中写入单条 `FUSED_STEP` descriptor
3. 通过 `cmdq_tail` 完成唯一 architectural doorbell
4. `wfi` 等待 completion
5. 在 software ack 前检查对应 reference 的 payload / CSR 可见性
6. `cmpq_head` ack + 清 pending event

所以它们的定位都是：

**builder reference 的 toolchain 同语义复刻版**

而不是新的 canonical sample。

---

## 5. 构建与运行结果

### 5.1 构建

命令：

```bash
cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_ref_toolchain"
make

cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_ref_toolchain"
make

cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_bad_policy_ref_toolchain"
make

cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_rearm_ref_toolchain"
make

cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_fault_overwrite_chain_ref_toolchain"
make
```

结果：

- 成功产出：
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_ref_toolchain.elf`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_fault_ref_toolchain.elf`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_bad_policy_ref_toolchain.elf`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_fault_rearm_ref_toolchain.elf`
  - `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_fault_overwrite_chain_ref_toolchain.elf`
- ELF 大小 / SHA256：
  - `external_dyn_desc_ref_toolchain.elf`
    - `9528` bytes
    - `c0c771d7609e8d608af51950c8214d44c2fc5908a224502d4656a7ff23fea8eb`
  - `external_dyn_desc_fault_ref_toolchain.elf`
    - `9520` bytes
    - `8b492c5aa71b5a9532c659296799c12ecf7e6b5876d3a1bc9e7e56ce3fbc1c8e`
  - `external_dyn_desc_bad_policy_ref_toolchain.elf`
    - `9520` bytes
    - `98ecf6eeec851ffcfc3dbb5d88e8be6c45846652d5c2d4c99acd2b01478db80d`
  - `external_dyn_desc_fault_rearm_ref_toolchain.elf`
    - `9560` bytes
    - `30fc1908a72ab7b73520e9e4b04c90daf5b9265c363ca37ef77acaba7566355d`
  - `external_dyn_desc_fault_overwrite_chain_ref_toolchain.elf`
    - `9600` bytes
    - `39abdeb5331e9437b34fd80ad4c02419009aa1e5013e84b87889f72aa3861921`

### 5.2 replay spec validate

命令：

```bash
cd "/home/xgy/remote/sst_dram_si"
python3 "./tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_toolchain.json"
python3 "./tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref_toolchain.json"
python3 "./tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref_toolchain.json"
python3 "./tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_toolchain.json"
python3 "./tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_overwrite_chain_ref_toolchain.json"
```

结果：

- 五条 spec 都返回 `OK`

### 5.3 smoke

命令：

```bash
cd "/home/xgy/remote/sst_dram_si"
./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_toolchain.json"
./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref_toolchain.json"
./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref_toolchain.json"
./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_rearm_ref_toolchain.json"
./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_overwrite_chain_ref_toolchain.json"
```

结果：

| program | run id | run dir | summary |
|---|---|---|---|
| `external_dyn_desc_ref_toolchain` | `20260324-182058` | `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260324-182058` | `fail=0 warn=1 strict=0` |
| `external_dyn_desc_fault_ref_toolchain` | `20260324-200005` | `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260324-200005` | `fail=0 warn=1 strict=0` |
| `external_dyn_desc_bad_policy_ref_toolchain` | `20260324-202540` | `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260324-202540` | `fail=0 warn=1 strict=0` |
| `external_dyn_desc_fault_rearm_ref_toolchain` | `20260324-200034` | `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260324-200034` | `fail=0 warn=1 strict=0` |
| `external_dyn_desc_fault_overwrite_chain_ref_toolchain` | `20260324-195040` | `/home/xgy/remote/sst_dram_si/outputs_large/paper2/dram_mesh_4x4/20260324-195040` | `fail=0 warn=1 strict=0` |

五条 smoke 的唯一 warning 都相同：

- `gas.features.merge_enabled_bcsr: gap_k=0 lmax=65536 row_window_bytes=0 row_window_timeout_ns=0`

---

## 6. 与 builder reference 的 compare surface

对比对象与结果：

| family | builder run | toolchain run | compare result |
|---|---|---|---|
| success | `20260324-165933` | `20260324-182058` | all checked metrics `OK` |
| fault | `20260324-181336` | `20260324-200005` | all checked metrics `OK` |
| bad-policy | `20260324-181406` | `20260324-202540` | all checked metrics `OK` |
| fault-rearm | `20260324-191558` | `20260324-200034` | all checked metrics `OK` |
| overwrite-chain | `20260324-195041` | `20260324-195040` | all checked metrics `OK` |

当前已确认五组 compare 都完全一致的关键指标：

- `spike_activity.neurons_fired_total`
- `spike_activity.total_spikes_processed`
- `spike_activity.gas_scatter_spikes_emitted_total`
- `gas.gather_ns_p95`
- `gas.apply_ns_p95`
- `gas.scatter_ns_p95`
- `memory.memory_requests`
- `memory.memory_bytes`
- `nic.packets_sent`
- `nic.packets_recv`

这意味着当前可以保守地说：

**在现有 smoke compare surface 上，五条 toolchain bridge 都与各自 builder reference 等价。**

---

## 7. source / ELF drift audit

这轮 bridge status 还有一条必须单独记住的结论：

1. 旧 `external_dyn_desc_fault_ref_toolchain/main.S`
2. 旧 `external_dyn_desc_bad_policy_ref_toolchain/main.S`
3. 旧 `external_dyn_desc_fault_rearm_ref_toolchain/main.S`

曾经分别残留过早期的：

1. `fault_ref/rearm_ref`：`0x210/0x110`
2. `bad_policy_ref`：`0x211/0x111`

而当前 builder authority 已经分别是：

1. `fault_ref/rearm_ref`：`0x204/0x104`
2. `bad_policy_ref`：`0x206/0x106`

因此这轮又额外补了两层证据：

1. source-level 修正
   - 去掉旧 `0x210/0x110`
   - 去掉旧 `0x211/0x111`
   - 改成与 builder authority 一致的 `0x204/0x104` 与 `0x206/0x106`
2. build 后 `.rodata` 审计
   - `fault_ref_toolchain.elf` / `fault_rearm_ref_toolchain.elf` 的 `.rodata` 已确认落成 `0x204/0x104`
   - `bad_policy_ref_toolchain.elf` 的 `.rodata` 已确认落成 `0x206/0x106`
3. 修正后重新 smoke + compare
   - `fault_ref_toolchain` 重新登记到 `20260324-200005`
   - `bad_policy_ref_toolchain` 重新登记到 `20260324-202540`
   - `fault_rearm_ref_toolchain` 重新登记到 `20260324-200034`
4. committed 本地 protocol harness
   - `tests/test_riscv_snn_toolchain_firmware_protocol.cc` 现在独立加载 lab-local toolchain ELF
   - `tests/test_riscv_snn_firmware_protocol.cc` 收回 builder/reference-only，不再混跑 toolchain bridge
   - 五条 toolchain bridge 的 final completion / `msnnfault` / GPR 末态，已经落到独立的 toolchain protocol harness 中

这说明：

**toolchain bridge 的验证以后不能只看 smoke compare，还必须同时看 builder authority、bridge source 与最终 ELF payload。**

再往前一步，这条实验性主线现在也已经做到最小文件级隔离：

1. builder authority 的 protocol harness 与 toolchain bridge 的 protocol harness 分离到两个测试文件
2. toolchain bridge 继续复用同一份 sample metadata / manifest authority，而不是派生第二份 spec authority
3. 因此后续继续扩展 toolchain runtime harness 时，不需要再回头修改 builder reference 测试本体

---

## 8. 仍未冻结的部分

当前还不能宣称：

1. toolchain 版与 builder 版 ELF 二进制结构等价
2. `msnnfault` software-clear 的更复杂场景（超出当前 clear-then-refault overwrite reference 的覆盖、嵌套 fault）已经完全冻结
3. toolchain 版已经形成新的 canonical baseline
4. `Xsnndl1p0` 指令或真正的 custom opcode 已进入稳定实现

所以这一条 bridge 的真实状态应该被表述为：

**成功覆盖 success / fault / bad-policy / clear-then-refault / overwrite-chain 五面的 bridge 组，但仍然不是新的 authority，也不是新的 baseline。**

---

## 9. 2026-03-25 explicit matrix + audit closure

这条 bridge status 在 2026-03-25 又补齐了两层真正可复跑的自动化入口：

1. toolchain real regress/register matrix
   - 命令：
     - `python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" matrix --group toolchain --register`
   - 摘要：
     - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-25-toolchain-regress-matrix.json`
   - 真实 run：
     - `external_dyn_desc_ref_toolchain` -> `20260325-100854`
     - `external_dyn_desc_fault_ref_toolchain` -> `20260325-100917`
     - `external_dyn_desc_bad_policy_ref_toolchain` -> `20260325-100941`
     - `external_dyn_desc_fault_rearm_ref_toolchain` -> `20260325-101005`
     - `external_dyn_desc_fault_overwrite_chain_ref_toolchain` -> `20260325-101029`
2. toolchain bridge drift audit
   - 命令：
     - `python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" audit --group toolchain --protocol`
   - 摘要：
     - `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-25-toolchain-bridge-audit.json`
   - 当前结论：
     - 五条 bridge 全部 `manifest_match == true`
     - 五条 bridge 全部 `source_file_count == 5`
     - `all_ok == true`

这意味着现在对 toolchain bridge 的最小稳定口径可以再前进一步：

**它仍然不是 authority，但它已经不再只是“几条零散 smoke + 手工对照”，而是拥有显式 protocol、显式 regress/register matrix、显式 drift audit 三层实验入口的隔离型 bridge 轨道。**

如果把 builder 侧也一起算进来，那么 2026-03-25 现在还多了一份顶层对照索引：

1. `/home/xgy/remote/riscv_snn_isa_lab/references/2026-03-25-nightly-index.json`

它把每条 builder reference family 对应的：

1. builder run id / manifest
2. toolchain run id / manifest
3. toolchain audit 状态

折成一条 family row。这样后续如果要做独立 nightly gate，就不需要分别再扫三份 JSON 才能对齐两侧状态。

当前还新增了两条稳定 automation 读取面：

1. `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-history-index.json`
2. `/home/xgy/remote/riscv_snn_isa_lab/references/nightly-sidecar-report.json`

再配合：

1. `/home/xgy/remote/riscv_snn_isa_lab/ci/nightly_sidecar.py`

就意味着 toolchain bridge 现在已经不仅能“被手工验证”，还可以“被独立 sidecar gate 长期盯住”。
