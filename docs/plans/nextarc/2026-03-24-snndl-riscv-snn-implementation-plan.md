# SnnDL `riscv_snn` Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在不破坏现有 `workload_impl=snn` 的前提下，把 `workload_impl=riscv_snn` 落成一条可运行、可验证、可继续演进的 P0/P1 主线。

**Architecture:** 实现分两层推进。第一层先把当前 `SnnWorkload` 内部真正属于 datapath/backend 的部分抽出来，形成共享 `SnnAccelBackend` 合同；第二层新增 `RiscvSnnWorkload`，让它以 `CSR + ring + completion + wfi/trap` 的控制面驱动同一个 backend。`CoreShell` 继续只做平台壳，`mesh_template` 只负责把新 workload 的参数透传到现有建模入口。

**Tech Stack:** C++17、SST `ICoreWorkload` 插件体系、现有 `mesh_template` spec-first 配置链、Python `unittest`、SnnDL compile-check、step-limited mesh regression。

**Repo Policy Note:** 本计划刻意不包含任何 `git commit/push/reset` 步骤；仓库策略要求这类操作必须在主人明确批准后再执行。

---

### Task 1: 冻结代码内 ABI 与 backend 合同

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/common/SnnAccelBackend.h`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnAbi.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.am`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_includes.cc`

**Steps:**
1. 在 `RiscvSnnAbi.h` 中定义与设计稿一致的常量和结构：
   - CSR 编号
   - event bit
   - opcode/status/fault 编码
   - 64B descriptor、16B completion、16B RX debug entry 的 packed layout
2. 在 `SnnAccelBackend.h` 中定义共享 backend 合同：
   - `configure(...)`
   - `tick(...)`
   - `submitDescriptorTicket(...)`
   - `pollCompletion(...)`
   - `injectPacket(...)`
   - `snapshotStats(...)`
   - `readArchitecturalStepState(...)`
3. 把 queue pointer、ticket、completion/status 这些 shared type 放在 backend 合同附近，不要散落在 `RiscvSnnWorkload.cc` 私有实现里。
4. 更新 `Makefile.am` 与 `tests/test_includes.cc`，保证这些头文件进入标准编译面。
5. 运行头文件编译检查：
   - `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile`

### Task 2: 从 `SnnWorkload` 提取共享 `SnnAccelBackend`

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/common/SnnAccelBackend.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/snn/SnnWorkload.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/api/ICoreWorkload.h`

**Steps:**
1. 先识别 `SnnWorkload` 中哪些成员属于 backend 责任：
   - `ISnnComputeCore`
   - `WeightMemorySubsystem`
   - `SpikeCommSubsystem`
   - gather/apply/scatter 阶段状态
   - step/rx/emit/stats 的 datapath 统计
2. 新建 `SnnAccelBackend.cc`，把上述 datapath 资源与 phase 机收敛进一个 concrete backend，而不是继续让 `SnnWorkload` 同时扮演 control plane 和 data plane。
3. 保持 `SnnWorkload` 对外行为不变，只把它改造成“直接控制 backend 的旧式 workload 壳”。
4. 如果 `ICoreWorkload` 需要新增极小的可选 hook，必须保证：
   - 对现有 `stream/tensor/traffic` workload 是纯兼容的
   - 不把 RISC-V 专有语义漏到通用接口层
5. 跑一次 compile-check，确保 `workload_impl=snn` 仍然可编译：
   - `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile`

### Task 3: 新增 `RiscvSnnWorkload` 与最小 hart 运行时

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnWorkload.h`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnWorkload.cc`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnHart.h`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnHart.cc`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_abi.cc`
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_queue_contract.cc`

**Steps:**
1. 先写 ABI/queue 红灯单测，锁定：
   - descriptor header 验证
   - ticket-to-slot 取模规则
   - `cmp payload -> cmpq_tail -> event pending` 的顺序假设
2. 在 `RiscvSnnHart.h/.cc` 中实现最小 hart 状态，而不是一次性接完整 ISS：
   - `PC`
   - `GPR`
   - `CSR bank`
   - `wfi`/pending-event 状态
   - 简单 IMEM/DMEM 装载接口
3. 在 `RiscvSnnWorkload.h/.cc` 中实现 workload 壳：
   - `configureFromParams`
   - `bindRuntime`
   - `onClockTick`
   - `deliverPacket`
   - completion drain / event 触发 / `wfi` 唤醒
4. 保证 incoming packet 只进入 backend ingress ownership domain，绝不让 `RiscvSnnWorkload` 逐条在软件路径处理 spike 主执行。
5. P0 只实现最小命令集：
   - `NOP`
   - `FUSED_STEP`
   - `STAT_SNAPSHOT`
   - 可选 `PREFETCH_W`
6. 重新跑新单测与 compile-check：
   - `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile`

### Task 4: 注册 `riscv_snn` workload、build 与默认统计模块

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/CoreWorkloadFactory.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/Makefile.am`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/components/workload_stats/WorkloadStatsRegistry.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_includes.cc`

**Steps:**
1. 在 `CoreWorkloadFactory.cc` 注册 `riscv_snn -> RiscvSnnWorkload`。
2. 在 `Makefile.am` 中加入：
   - `services/workload/common/SnnAccelBackend.*`
   - `services/workload/riscv_snn/RiscvSnnAbi.h`
   - `services/workload/riscv_snn/RiscvSnnWorkload.*`
   - `services/workload/riscv_snn/RiscvSnnHart.*`
3. 在 `WorkloadStatsRegistry.cc` 中让 `riscv_snn` 默认复用 `snn` 统计模块，这样 P0 不会因为统计注册为空而失去对齐观测。
4. 再跑一次 `make test-compile`，确认注册/build 面没有遗漏。

### Task 5: 打通 `mesh_template` 的 `riscv_snn` 参数透传

**Files:**
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/spec.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/runtime.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/build.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/test_spec_resolver.py`
- Modify: `/home/xgy/remote/sst_dram_si/mesh_template/test_runtime_input_path_resolution.py`
- Create: `/home/xgy/remote/sst_dram_si/configs/spec_riscv_snn_p0.json`

**Steps:**
1. 在 `spec.py` 中把 `workload.params` 从当前 `snn` 专用白名单扩成 workload-aware 解析：
   - `snn` 继续接受现有 `tau_mem/thresholds/t_ref/...`
   - `riscv_snn` 新增最小字段：
     - `firmware_elf`
     - `hart_isa`
     - `local_mem_bytes`
     - `cmd_queue_entries`
     - `cmp_queue_entries`
     - `rx_debug_queue_entries`
     - `boot_addr`
2. 在 `runtime.py` 中把这些字段收敛到 effective mesh config，避免散落的 env override。
3. 在 `build.py` 中把 `riscv_snn` 相关参数传给 PE/core `node_params`，同时保持 `workload_impl=snn` 默认路径完全不变。
4. 扩展 `test_spec_resolver.py` 与 `test_runtime_input_path_resolution.py`，锁定：
   - `SPEC_WORKLOAD_IMPL="riscv_snn"`
   - `firmware_elf` 路径解析
   - queue entries / local mem 参数透传
5. 创建最小 spec-first 冒烟配置 `spec_riscv_snn_p0.json`，它必须仍然以 `/home/xgy/remote/sst_dram_si/test_mesh_4x4.py` 为模型入口。
6. 跑 Python 回归：
   - `cd "/home/xgy/remote" && python -m unittest sst_dram_si.mesh_template.test_spec_resolver -v`
   - `cd "/home/xgy/remote" && python -m unittest sst_dram_si.mesh_template.test_runtime_input_path_resolution -v`

### Task 6: 完成 P0 `FUSED_STEP` 主路径与对齐验证

**Files:**
- Create: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_snn_accel_backend_contract.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_queue_contract.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnWorkload.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/common/SnnAccelBackend.cc`
- Modify: `/home/xgy/remote/sst_dram_si/configs/spec_riscv_snn_p0.json`

**Steps:**
1. 写 backend contract 红灯单测，锁定最关键的 P0 语义：
   - `cmdq_tail` 是唯一 architectural doorbell
   - 命令只有在 `cmdq_head` 越过后才算 `Accepted`
   - completion 对软件的可见顺序严格是 `payload -> cmpq_tail -> event`
2. 在 `RiscvSnnWorkload.cc` 中实现一个最小 firmware/driver 回路：
   - 初始化 CSR/ring
   - 提交一个 `FUSED_STEP`
   - `wfi`
   - drain completion
   - 结束本次 step-limited run
3. 在 `SnnAccelBackend.cc` 中把 `FUSED_STEP` 与现有 `snn` 路径对接起来，保证强 completion 语义是同一条 commit boundary。
4. 先跑单元编译和 Python 回归，再跑 spec-first 冒烟仿真：
   - `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile`
   - `cd "/home/xgy/remote" && python -m unittest sst_dram_si.mesh_template.test_spec_resolver -v`
   - `cd "/home/xgy/remote/sst_dram_si" && ./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/sst_dram_si/configs/spec_riscv_snn_p0.json"`
5. 用同一输入与同一映射再跑一份 `workload_impl=snn` baseline，比较：
   - step 完成数
   - `essential_summary_mesh.json`
   - per-step spikes
   - key state snapshot / stats

### Task 7: P1 中断/故障语义补齐

**Files:**
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnHart.h`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnHart.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/services/workload/riscv_snn/RiscvSnnWorkload.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_riscv_snn_queue_contract.cc`
- Modify: `/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL/tests/test_snn_accel_backend_contract.cc`

**Steps:**
1. 在 hart 中补齐 `msnneventen/msnneventpend`、trap cause、`mret` 返回路径。
2. 让 `completion / barrier / fault` 走统一 pending-event 语义，而不是 workload 自己维护第二套等待协议。
3. 增加 fault/interrupt 单测，覆盖：
   - bad descriptor
   - bad opcode
   - illegal phase transition
   - `msnnfault` 与 completion `status_code` 一致性
4. 重新跑 compile-check 与定向单测。

### Task 8: 结果固化与进展记录

**Files:**
- Modify: `/home/xgy/remote/TECH_PROGRESS.md`
- Modify: `/home/xgy/remote/docs/plans/nextarc/2026-03-24-snndl-riscv-snn-isa-design.md`

**Steps:**
1. 所有实现和验证结束后，只在 `TECH_PROGRESS.md` 末尾 append：
   - 改了哪些文件
   - 怎么跑
   - 实际结果/日志路径
   - 与 `workload_impl=snn` 的对齐结论
   - 下一步 TODO
2. 若实现过程中发现协议与设计稿不一致，只能回写设计稿澄清；不能把真实代码语义藏在实现里。
3. 最终交付前，再人工检查一次：
   - `riscv_snn` 没有把 spike 主路径搬进 software handler
   - `CoreShell` 没被塞进 ISA 语义
   - `snn` baseline 没退化

### Verification Checklist

**Commands:**
- `cd "/home/xgy/remote/sst_workspace/sst-elements/src/sst/elements/SnnDL" && make test-compile`
- `cd "/home/xgy/remote" && python -m unittest sst_dram_si.mesh_template.test_spec_resolver -v`
- `cd "/home/xgy/remote" && python -m unittest sst_dram_si.mesh_template.test_runtime_input_path_resolution -v`
- `cd "/home/xgy/remote/sst_dram_si" && ./tools/run_mesh_with_time.sh --spec "/home/xgy/remote/sst_dram_si/configs/spec_riscv_snn_p0.json"`
- `cd "/home/xgy/remote/sst_dram_si" && ./tools/run_mesh_with_time.sh`

**Expected evidence:**
- `make test-compile` 通过，说明新增 workload/backend/hart 头文件与源文件至少在编译面闭合。
- `test_spec_resolver` 与 `test_runtime_input_path_resolution` 通过，说明 spec-first 配置链已能表达 `riscv_snn`。
- `run_mesh_with_time.sh --spec ...` 能产出 `meta.json`、`essential_summary_mesh.json`、`validation.log`。
- `riscv_snn` 与 baseline `snn` 在同一 workload/input/mapping 下至少完成第一轮 `FUSED_STEP` 对齐。

