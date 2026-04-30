# SnnDL `riscv_snn` Next-Phase Protocol/Lab/Toolchain Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在保持 `riscv_snn` 实验主线严格隔离、避免耦合的前提下，把当前“已冻结 sample + lab-local 资产 + run registry”推进为“协议收口 + 轻量实验编排 + 最小 toolchain 桥接”的稳定架构研究平台。

**Architecture:** 下一阶段不再优先扩张 ISA 面，而是先把 v1.1 control-plane 协议里最容易漂移的 bit-level 语义写硬，再通过 additive reference sample 把 success/fault/policy 三类行为做成可复现证据。与此同时，只在 `/home/xgy/remote/riscv_snn_isa_lab` 下增加薄包装层和 toolchain bridge，不反向耦合主 `snn` datapath，也不新增第二份 sample metadata authority。

**Tech Stack:** C++17、SnnDL workload/test harness、Python 3 `unittest`、`sst_dram_si` spec-first 工具链、`mesh_spec_cli.py`、`run_mesh_with_time.sh`、可选 bare-metal RISC-V toolchain（`riscv64-unknown-elf-gcc` 或 `clang --target=riscv64`）。

**Repo Policy Note:** 本计划刻意不包含任何 `git commit/push/reset` 步骤；仓库策略要求这类操作必须在主人明确批准后再执行。

**Isolation Note:** 真实协议 authority 继续留在：
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnAbi.h`
- `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnSampleFirmware.h`

实验编排、toolchain 桥接、run registry 继续只长在：
- `/home/xgy/remote/riscv_snn_isa_lab`

---

## 0. 当前起点与阶段目标

当前已经具备的地基：

1. `workload_impl=riscv_snn` 已跑通最小 bring-up。
2. canonical sample set 已冻结：
   - `external_p0`
   - `external_dyn_desc`
3. additive reference sample 已存在：
   - `external_dyn_desc_ref`
4. lab-local firmware/spec 已落到：
   - `/home/xgy/remote/riscv_snn_isa_lab/firmware`
   - `/home/xgy/remote/riscv_snn_isa_lab/specs`
5. run registry 已覆盖三条样例：
   - `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-p0-smoke.md`
   - `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-dyn-desc-smoke.md`
   - `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-dyn-desc-ref-smoke.md`

所以下一阶段不该再做的事是：

1. 过早冻结 `Xsnndl1p0` opcode。
2. 过早把真实 toolchain 升格成 canonical baseline。
3. 过早改全局 runner 或主 `snn` 路径。

下一阶段真正要回答的四个问题是：

1. `completion_policy / error_policy / aux0 / aux1 / msnnfault` 的语义能不能被可靠锁住。
2. additive reference sample 能不能把 success/fault/policy 三类协议面都补齐。
3. 实验目录能不能从“静态资产库”前进到“轻量实验编排层”。
4. bare-metal toolchain 产物能不能在不破坏 authority 的前提下，对齐现有 reference sample 的 control-plane 契约。

---

## 1. 分阶段执行顺序

### Phase A: Protocol Hardening

目标：

- 把 bit-level 协议里最容易漂移的字段先写硬。
- 把 success / fault / bad-policy 三类行为都纳入 reference sample 证据面。

退出标准：

1. 至少有三条 additive reference sample：
   - success reference
   - fault reference
   - bad-policy reference
2. 每条 reference 都具备四层证据：
   - C++ protocol test
   - Python tooling test
   - spec validate
   - smoke run manifest

### Phase B: Thin Lab Orchestration

目标：

- 在不改全局 runner 的前提下，把实验目录升级成薄包装编排层。

退出标准：

1. 单条命令可以完成：
   - sample 查询
   - firmware/spec 生成
   - spec validate
   - smoke
   - manifest 草稿生成

### Phase C: Minimal Toolchain Bridge

目标：

- 用一条最小 bare-metal toolchain 程序证明“真实编译链也能走同一 control-plane 契约”。

退出标准：

1. `external_dyn_desc_ref` 的 toolchain 版本能完成 smoke。
2. 它与 builder sample 在协议观察面等价。
3. 它仍然不替代 canonical sample authority。

### Phase D: Research Matrix

目标：

- 把 builder/toolchain、success/fault、canonical/reference 的 compare surface 做成研究入口，而不是聊天结论。

退出标准：

1. 有固定 matrix note。
2. 有固定 compare run manifest。
3. 有固定“哪些结论可信、哪些仍未冻结”的文档口径。

---

## 2. Task 1: 收紧 bit-level 协议与 fault 可见性 contract

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnAbi.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnQueueContract.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_abi.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_queue_contract.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_firmware_protocol.cc`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`

**Step 1: 先写红灯 ABI 断言**

要补的断言最少包括：

1. `completion_policy != 0` 时必须被识别为非法。
2. `error_policy != 0` 时必须被识别为非法。
3. descriptor reserved bits 非零时必须触发 strict fault。
4. completion `status_code / aux0 / aux1` 的可见内容与 `msnnfault` 语义相匹配。

**Step 2: 锁定 success/fault 两种 completion 顺序**

在 `test_riscv_snn_firmware_protocol.cc` 里补两类最小协议面：

1. success retire:
   - `payload`
   - `cmpq_tail`
   - `event`
2. fault retire:
   - `msnnfault`
   - completion payload
   - `cmpq_tail`
   - `event`

**Step 3: 只做最小实现**

只允许在：

1. `RiscvSnnAbi.h`
2. `RiscvSnnQueueContract.h`

里收紧 enum/bit layout/helper，不要顺手扩张新的 runtime/ISS 复杂度。

**Step 4: 回写设计稿**

如果 code-level 收紧导致设计稿措辞不够硬，必须同步回写：

- `7.2.4 fault 可见性`
- `7.8 msnnstep / msnnfault`
- `9 descriptor/completion` 位级定义

**Verification:**

```bash
cd "/home/xgy/remote" && \
g++ -std=c++17 -I "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" \
  -I "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api" \
  -I "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services" \
  "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_queue_contract.cc" \
  -o /tmp/test_riscv_snn_queue_contract && /tmp/test_riscv_snn_queue_contract

cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -DHAVE_CONFIG_H -I. -I../../../../src -I/usr/include/python3.10 \
  -I/home/xgy/remote/sst_install_mpi/include/sst/core -I/home/xgy/remote/sst_install_mpi/include \
  -I../../../../src -I. -I./api -I./events -I./components -I./control -I./compute -I./services \
  -I/home/xgy/remote/sst_install_mpi/include \
  ./tests/test_riscv_snn_firmware_protocol.cc \
  ./services/workload/riscv_snn/RiscvSnnFirmwareLoader.cc \
  ./services/workload/common/SnnAccelBackend.cc \
  ./services/workload/riscv_snn/RiscvSnnIss.cc \
  ./services/workload/riscv_snn/RiscvSnnHart.cc \
  -o /tmp/test_riscv_snn_firmware_protocol.next && /tmp/test_riscv_snn_firmware_protocol.next

cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile
```

Expected:

1. 新增 ABI/queue/protocol 断言在红灯前确实失败。
2. 绿灯后 `/tmp/test_riscv_snn_queue_contract` 和 `/tmp/test_riscv_snn_firmware_protocol.next` 退出码都为 `0`。
3. `make test-compile` 继续通过。

---

## 3. Task 2: 新增 additive reference sample，补齐 fault/policy 证据面

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnSampleFirmware.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tools/riscv_snn_emit_sample_firmware.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_firmware_tools.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_firmware_protocol.cc`
- Modify: `/home/xgy/remote/sst_dram_si/tools/generate_riscv_snn_firmware.py`
- Modify: `/home/xgy/remote/sst_dram_si/tools/test_generate_riscv_snn_firmware.py`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-24-riscv-snn-canonical-firmware-samples.md`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref.json`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref.json`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_fault_ref.elf`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_bad_policy_ref.elf`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-dyn-desc-fault-ref-smoke.md`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-dyn-desc-bad-policy-ref-smoke.md`

**Step 1: 冻结 sample 名称和角色**

推荐新增两条 additive sample，且都不得进入 canonical baseline：

1. `external_dyn_desc_fault_ref`
   - accepted 后 fault
   - completion 与 `msnnfault` 对齐
2. `external_dyn_desc_bad_policy_ref`
   - descriptor policy 非法
   - 用来观察 reject/fault-before-progress 语义

**Step 2: 先写红灯 metadata/tooling 测试**

最少要补：

1. `sampleFirmwareProgramNames()` 长度变化
2. `sampleFirmwareMetadata()` 中新 sample 的 role/notes/descriptor_source
3. Python generator `--list-programs --json` 能看到新增 sample

**Step 3: 只在 private builder/emitter 路径中新增 authority**

新增 sample 的真实 authority 只能长在：

- `RiscvSnnSampleFirmware.h`

禁止把 metadata 重新分叉到 Python 层。

**Step 4: 生成 lab-local 资产**

把两条新 sample 都生成到：

1. `/home/xgy/remote/riscv_snn_isa_lab/firmware`
2. `/home/xgy/remote/riscv_snn_isa_lab/specs`

并保持命名与现有三条样例一致。

**Step 5: 跑 smoke 并登记**

每条新 reference sample 都必须在 `runs/` 下有标准 manifest，不允许只有 `tmp/` 或聊天结论。

**Verification:**

```bash
cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && \
g++ -std=c++17 -DHAVE_CONFIG_H -I. -I../../../../src -I/usr/include/python3.10 \
  -I/home/xgy/remote/sst_install_mpi/include/sst/core -I/home/xgy/remote/sst_install_mpi/include \
  -I../../../../src -I. -I./api -I./events -I./components -I./control -I./compute -I./services \
  -I/home/xgy/remote/sst_install_mpi/include \
  ./tests/test_riscv_snn_firmware_tools.cc \
  ./services/workload/riscv_snn/RiscvSnnFirmwareLoader.cc \
  -o /tmp/test_riscv_snn_firmware_tools.next && /tmp/test_riscv_snn_firmware_tools.next

cd "/home/xgy/remote" && \
python3 -m unittest sst_dram_si.tools.test_generate_riscv_snn_firmware -v

python3 "/home/xgy/remote/sst_dram_si/tools/generate_riscv_snn_firmware.py" --list-programs --json

cd "/home/xgy/remote/sst_dram_si" && \
python3 "./tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref.json"

cd "/home/xgy/remote/sst_dram_si" && \
python3 "./tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref.json"

cd "/home/xgy/remote/sst_dram_si" && \
./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_fault_ref.json"

cd "/home/xgy/remote/sst_dram_si" && \
./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_bad_policy_ref.json"
```

Expected:

1. 新增 sample 会出现在 manifest JSON 中。
2. 两份新 spec 都 validate 通过。
3. 两份新 run 都产出 `meta.json`、`validation.log`、manifest 记录文件。

---

## 4. Task 3: 把实验目录升级成薄包装 orchestration 层

**Files:**
- Create: `/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/tools/test_riscv_snn_lab.py`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/README.md`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/runs/_run_manifest_template.md`

**Step 1: 先写 wrapper 红灯测试**

`test_riscv_snn_lab.py` 最少覆盖：

1. `list`
2. `generate`
3. `validate`
4. `smoke`
5. `register`

这里的目标不是重做真实执行，而是验证 wrapper 会不会把路径、命令和 manifest 草稿串起来。

**Step 2: wrapper 只做 subprocess 编排**

`riscv_snn_lab.py` 必须只复用现有入口：

1. `generate_riscv_snn_firmware.py`
2. `mesh_spec_cli.py`
3. `run_mesh_with_time.sh`

禁止在 wrapper 里重新实现：

1. sample metadata
2. spec schema
3. run parser

**Step 3: 支持最小 CLI**

推荐子命令：

1. `list`
2. `generate --program ...`
3. `validate --program ...` 或 `--spec ...`
4. `smoke --program ...`
5. `register --program ... --run-dir ...`

**Step 4: README 只补使用入口，不改 authority 定位**

README 里要增加一节“lab wrapper 用法”，但必须继续强调：

1. authority 在主实现目录
2. wrapper 只负责编排

**Verification:**

```bash
cd "/home/xgy/remote" && python3 -m unittest riscv_snn_isa_lab.tools.test_riscv_snn_lab -v

python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" list

python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" \
  generate --program external_dyn_desc_ref

python3 "/home/xgy/remote/riscv_snn_isa_lab/tools/riscv_snn_lab.py" \
  validate --program external_dyn_desc_ref
```

Expected:

1. wrapper 测试通过。
2. `list/generate/validate` 能在 lab-local 目录下工作。
3. 没有新增任何对主 `snn` 路径的耦合。

---

## 5. Task 4: 建立最小 bare-metal toolchain bridge

**Files:**
- Create: `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_ref_toolchain/crt0.S`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_ref_toolchain/main.S`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_ref_toolchain/linker.ld`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_ref_toolchain/Makefile`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/firmware/external_dyn_desc_ref_toolchain.elf`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_toolchain.json`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/runs/2026-03-24-external-dyn-desc-ref-toolchain-smoke.md`
- Create: `/home/xgy/remote/riscv_snn_isa_lab/notes/2026-03-24-toolchain-bridge-status.md`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/README.md`

**Step 1: 先做环境探测，不要假定 toolchain 存在**

优先探测：

1. `riscv64-unknown-elf-gcc`
2. `riscv64-elf-gcc`
3. `clang --target=riscv64`

如果本机缺失，任务只推进到：

1. source skeleton
2. linker script
3. build note

不要为了“跑通”去改 sample authority。

**Step 2: 只桥接一个程序**

v1 只桥接：

`external_dyn_desc_ref`

原因：

1. 它最贴 protocol 面。
2. 它最适合做 builder vs toolchain contract compare。
3. 它不会误伤 canonical baseline 角色。

**Step 3: 工程结构保持最小**

只需要：

1. `crt0.S`
2. `main.S`
3. `linker.ld`
4. `Makefile`

不要在这一步引入 libc、newlib、复杂 runtime。

**Step 4: 用 lab-local spec 接 smoke**

toolchain 产物必须：

1. 生成单独 ELF
2. 生成单独 spec
3. 生成单独 run manifest

这样后面 compare 时才不会和 builder sample 混在一起。

**Verification:**

```bash
command -v riscv64-unknown-elf-gcc || command -v riscv64-elf-gcc || clang --version

cd "/home/xgy/remote/riscv_snn_isa_lab/firmware_src/external_dyn_desc_ref_toolchain" && make

cd "/home/xgy/remote/sst_dram_si" && \
python3 "./tools/mesh_spec_cli.py" validate "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_toolchain.json"

cd "/home/xgy/remote/sst_dram_si" && \
./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/riscv_snn_isa_lab/specs/external_dyn_desc_ref_toolchain.json"
```

Expected:

1. 如果 toolchain 可用，则成功产出 ELF 并完成 smoke。
2. 如果 toolchain 不可用，则至少保留 source skeleton 和明确环境说明，不篡改现有 builder path。

---

## 6. Task 5: 固定 builder vs toolchain vs fault/policy 的研究矩阵

**Files:**
- Create: `/home/xgy/remote/riscv_snn_isa_lab/notes/2026-03-24-riscv-snn-protocol-hardening-matrix.md`
- Modify: `/home/xgy/remote/riscv_snn_isa_lab/README.md`
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`

**Step 1: 先定义最小矩阵维度**

矩阵最少包含四个轴：

1. sample family
   - canonical
   - additive reference
2. expected behavior
   - success
   - fault-after-accept
   - bad-policy / reject
3. source
   - sample builder
   - toolchain
4. evidence
   - unit
   - validate
   - smoke
   - manifest

**Step 2: 不做复杂自动化 compare**

这一轮只需要先把 compare surface 写清楚，不需要一次性上全自动统计脚本。

**Step 3: 把哪些结论可信写死**

matrix note 里必须明确区分：

1. 已冻结结论
2. 仅 reference 级结论
3. 尚未冻结的方向

**Step 4: 更新进度日志**

只在 `TECH_PROGRESS.md` 末尾 append：

1. 新增了哪些 sample
2. 哪些验证跑了
3. 哪些仍然是 TODO

**Verification:**

```bash
find "/home/xgy/remote/riscv_snn_isa_lab" -maxdepth 2 -type f | sort

tail -n 120 "/home/xgy/remote/TECH_PROGRESS.md"
```

Expected:

1. compare matrix note 存在。
2. README 能把 sample、wrapper、toolchain、matrix 组织成单一路径。
3. `TECH_PROGRESS.md` 只 append，不重写。

---

## 7. 明确不做的事

这一阶段明确不做：

1. 不冻结 `Xsnndl1p0` 指令编码。
2. 不新增第二套 sample metadata authority。
3. 不把 `RX debug ring` 升格成主执行路径。
4. 不修改全局 `run_mesh_with_time.sh` 输出根。
5. 不把 toolchain 版本样例直接升级成 canonical baseline。
6. 不把实验 wrapper 耦回主 `snn` datapath。

---

## 8. 阶段门槛与切换条件

### Gate A: 从当前状态进入 Protocol Hardening

允许开始的前提：

1. lab-local firmware/spec 已存在
2. run registry 已覆盖三条当前样例

当前已满足。

### Gate B: 从 Protocol Hardening 进入 Thin Lab Orchestration

要求：

1. 至少两条新 reference sample 已有 validate + smoke + manifest
2. `test_riscv_snn_firmware_protocol.cc` 已覆盖 success + fault 至少两面

### Gate C: 从 Thin Lab Orchestration 进入 Toolchain Bridge

要求：

1. wrapper 能稳定生成和登记 builder sample
2. README 中的 lab usage 已不再依赖聊天说明

### Gate D: 从 Toolchain Bridge 进入 Research Matrix

要求：

1. toolchain sample 至少一条跑通 smoke
2. builder vs toolchain 至少形成一份固定 compare note

---

## 9. 建议执行顺序

建议严格按下面顺序做：

1. `Task 1`
2. `Task 2`
3. `Task 3`
4. `Task 4`
5. `Task 5`

不要调换成：

1. 先做 toolchain
2. 再回头补协议

因为那样最容易把临时契约过早固化成“真接口”。

---

## 10. 最终交付判断

下一阶段完成时，应该能用一句话准确描述状态：

`riscv_snn` 已经从“有 bring-up 和零散 smoke”前进到“协议面有 success/fault/policy 三类 reference 证据，实验目录具备薄编排能力，且至少有一条 toolchain 程序与 builder reference 在 control-plane 观察面上等价”。`

如果还达不到这句话，就说明：

1. 协议还没真正写硬；
2. 或者实验目录还只是静态资产库；
3. 或者 toolchain 还只是概念，而不是受控证据。

