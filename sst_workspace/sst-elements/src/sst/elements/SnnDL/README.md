# SnnDL（SST Element：Spiking Neural Network / Deep Learning）

本目录是 `sst-elements` 中的 **SnnDL 元素库源码**，用于在 SST 中模拟多核 Processing Element（PE）上的工作负载：默认提供 SNN（Spike/GAS/BCSR/Step）链路，同时也支持以 **packet-first** 方式加载非 SNN workload（例如通信+内存 streaming 校验）。

核心设计目标：**平台核（NoC/Mem/CoreShell）通用可复用；业务语义（SNN/Step/GAS/BCSR/Stream）作为可插拔 workload/子系统加载；边界清晰、可回归、fail-fast。**

推荐总览入口（先看这个更容易读懂整体）：
- `docs/SNNDL_HIERARCHY_AND_WORKFLOW.md`

---

## 快速构建与安装（推荐 install；本地验证可走 --add-lib-path）

> 说明：SnnDL 属于 `sst-elements` 的一部分，通常在已 configure 的工作区内增量编译安装。
> 项目内 runner 默认会 `--add-lib-path "<.../SnnDL/.libs>"` 以优先加载工作区构建产物，因此本地验证不一定需要 install；但对外/系统级使用仍建议 `make install` 固化到 prefix。

```bash
cd "sst_workspace/sst-elements/src/sst/elements/SnnDL"
make -j4
make install
```

兼容入口：`install_basic.sh`（等价执行 `make -j && make install`）。

---

## 快速运行回归（4×4 mesh 模板）

也可走统一 spec-first 入口（对齐对外 schema；stop/max_steps 由 spec 决定）：

```bash
cd "<repo_root>"
python3 "tools/snndl_spec_cli.py" validate "tools/specs/mesh_minimal_v3.json"
bash "tools/run_snndl_with_time.sh" --spec "tools/specs/mesh_minimal_v3.json"
```

推荐使用项目内 mesh 模板驱动（详细见 `sst_dram_si/docs/mesh_template_guide_20251122-000250.md`）：

```bash
cd "sst_dram_si"
export MESH_MAX_STEPS="4"
./tools/run_mesh_with_time.sh
```
如需按时间停止：设置 `MESH_MAX_STEPS<=0` 并指定 `MESH_SIM_TIME="100us"`。

可选：切换到 `workload=stream`（不涉及 Spike/GAS/权重/BCSR，仅做 packet-first 通信 + 内存 read-after-write 校验）：

```bash
cd "sst_dram_si"
export SNNDL_WORKLOAD_IMPL="stream"
export MESH_MAX_STEPS="4"
./tools/run_mesh_with_time.sh
```

可选：切换到 `workload=traffic`（不建模动力学；用于通信/多播（SpikeKey）链路验证）：

```bash
cd "sst_dram_si"
export SNNDL_WORKLOAD_IMPL="traffic"
export MESH_MAX_STEPS="4"
./tools/run_mesh_with_time.sh
```

### Tensor 工作负载（计算范式扩张）

除 SNN/stream/traffic 外，SnnDL 也支持 `workload=tensor`（面向 GEMM/systolic 类 compute+memory+NoC 压力），推荐通过独立 workload 目录运行，避免与主实验目录脚本/输出混淆：

```bash
cd "sst_workloads/tensor_si"
export TENSOR_SI_SIM_TIME="10us"
bash "./tools/run_tensor_mesh_with_time.sh"
```

完整参数与输出口径说明见：`sst_workloads/tensor_si/README.md`。

可选：显式选择聚合统计模块（逗号分隔）：

```bash
cd "sst_workloads/tensor_si"
TENSOR_SI_WORKLOAD_STATS_MODULES="tensor,stream" bash "./tools/run_tensor_mesh_with_time.sh"
```

可选：启用 collective 通信建模（近似 ring/mesh 模式）：

```bash
cd "sst_workloads/tensor_si"
TENSOR_SI_TENSOR_COLLECTIVE_TYPE="allreduce" \
TENSOR_SI_TENSOR_COLLECTIVE_BYTES="1048576" \
TENSOR_SI_TENSOR_COLLECTIVE_PERIOD="100" \
TENSOR_SI_TENSOR_COLLECTIVE_PATTERN="ring" \
TENSOR_SI_TENSOR_COLLECTIVE_PACKET_BYTES="256" \
bash "./tools/run_tensor_mesh_with_time.sh"
```

可选：启用 Level-2 `tile` 执行语义（compute 受 DMA/memory backpressure 约束 + stall 分解统计）：

```bash
cd "sst_workloads/tensor_si"
TENSOR_SI_TENSOR_EXEC_MODE="tile" \
TENSOR_SI_TENSOR_TILE_SCHEDULE="auto" \
TENSOR_SI_TENSOR_WRITEBACK_POLICY="at_end_of_k" \
bash "./tools/run_tensor_mesh_with_time.sh"
```

可选：将 collective 作为 iteration 间 barrier（等待本 epoch 的 recv bytes 达标后再进入下一次 iteration）：

```bash
cd "sst_workloads/tensor_si"
TENSOR_SI_TENSOR_COLLECTIVE_TYPE="allreduce" \
TENSOR_SI_TENSOR_COLLECTIVE_BYTES="1048576" \
TENSOR_SI_TENSOR_COLLECTIVE_PERIOD="100" \
TENSOR_SI_TENSOR_COLLECTIVE_PATTERN="ring" \
TENSOR_SI_TENSOR_COLLECTIVE_PACKET_BYTES="256" \
TENSOR_SI_TENSOR_COLLECTIVE_BLOCKING="1" \
TENSOR_SI_TENSOR_COLLECTIVE_SCOPE="per_core" \
bash "./tools/run_tensor_mesh_with_time.sh"
```

> `TENSOR_SI_TENSOR_COLLECTIVE_SCOPE` 仅在 `*_COLLECTIVE_BLOCKING=1` 时生效：
> - `per_core`：每个 core 独立等待自身 epoch 完成（默认）
> - `per_pe`：同一 PE 内所有 cores 的 epoch 完成后，PE 内任一 core 才能进入下一 iteration
> - `per_system`：全系统（nodes×cores）epoch 完成后，系统内任一 core 才能进入下一 iteration
>
> 注：`per_pe/per_system` 会注入少量 `Control` 包做 barrier 完成广播（可在 `tensor_pkt_{sent,recv}_total` 里观察到）。

常用参数入口：

- tensor：`TENSOR_SI_TENSOR_M`、`TENSOR_SI_TENSOR_N`、`TENSOR_SI_TENSOR_K`、`TENSOR_SI_TENSOR_ARRAY_M`、`TENSOR_SI_TENSOR_ARRAY_N`
- dataflow/tile：`TENSOR_SI_TENSOR_DATAFLOW`、`TENSOR_SI_TENSOR_TILE_M`、`TENSOR_SI_TENSOR_TILE_N`、`TENSOR_SI_TENSOR_TILE_K`
- exec/schedule：`TENSOR_SI_TENSOR_EXEC_MODE`、`TENSOR_SI_TENSOR_TILE_SCHEDULE`、`TENSOR_SI_TENSOR_WRITEBACK_POLICY`
- on-chip/DMA：`TENSOR_SI_TENSOR_UB_BYTES`、`TENSOR_SI_TENSOR_ACC_BYTES`、`TENSOR_SI_TENSOR_DMA_BW`、`TENSOR_SI_TENSOR_DOUBLE_BUFFER`
- collective：`TENSOR_SI_TENSOR_COLLECTIVE_TYPE`、`TENSOR_SI_TENSOR_COLLECTIVE_BYTES`、`TENSOR_SI_TENSOR_COLLECTIVE_PERIOD`、`TENSOR_SI_TENSOR_COLLECTIVE_PATTERN`、`TENSOR_SI_TENSOR_COLLECTIVE_PACKET_BYTES`、`TENSOR_SI_TENSOR_COLLECTIVE_BLOCKING`、`TENSOR_SI_TENSOR_COLLECTIVE_SCOPE`
- 统计模块：`TENSOR_SI_WORKLOAD_STATS_MODULES="tensor[,stream]"`

### 一键回归门禁（DRAM-SI + tensor_si）

```bash
cd "<repo_root>"
bash "tools/run_snndl_regression_gate.sh"
```

输出目录通常位于：
- `sst_dram_si/outputs_large/paper2/dram_mesh_4x4/YYYYMMDD-HHMMSS/`
  - `essential_summary_mesh.json`：关键指标摘要（用于 100us 回归判定）。

### 内存建模口径（默认 cacheline 语义）

SnnDL 的默认内存建模语义与 `memHierarchy` 保持一致：**以 cacheline（例如 64B）作为系统层事务/流量的基本单位**。

- 论文/报告中的“DRAM traffic”主口径建议以 `memHierarchy MemController requests_received_*`（L2 traffic）为准；
- `essential_summary_mesh.json` 中的 `memory.memory_requests` / `memory.memory_bytes` 表示上层发起的逻辑请求（L1 logical request），用于解释合并/去重形态，不应直接等价为 off-chip 流量；
  - 其中 `memory_bytes` 为对 core 侧统计 `mem_req_size_bytes` 的汇总派生指标；
- 若切换到 row-streaming/DMA 假设，必须显式标注并单列结果（不得与 cacheline 模式混算）。

### SRAM 建模（SNN 第一阶段：stall budget 闭环）

`SnnDL` 现已支持一版 **SNN 专用 SRAM timing 第一阶段**：当启用 `state_sram_*` / `weight_*_sram_*` 参数时，片上 SRAM 的 bank conflict 不再只是 observe-only 统计，而会转成下一拍的 **stall budget**，反馈到：

- `compute/SnnComputeCore`：阻塞 neuron state sweep / fire 判定；
- `services/synapse/weights/WeightMemorySubsystem`：阻塞新的 prefetch / deferred issue / direct drain。

当前口径仍是**分层代理**，不是逐请求 local SRAM 控制器：

- 保留现有 `BankedSramModel` 的统计字段与 mesh 参数；
- 将 `predicted_extra_cycles_total` 变成真实时序反压；
- 不改变 DRAM / StandardMem 接口边界。

验证命令：

```bash
cd "sst_workspace/sst-elements/src/sst/elements/SnnDL"
g++ -std=c++17 -I . tests/test_banked_sram_model.cc \
  services/memory/sram_sim/model/BankedSramModel.cc \
  -o /tmp/test_banked_sram_model && /tmp/test_banked_sram_model
make -j4
```

### PE 级 DMA 读调度（SNN workload，Phase 1）

`SnnDL` 当前已经落地一版 **PE 级共享 DMA 读调度**，用于给 `workload_impl=snn` 的运行期权重读取路径建模“同一 PE 内多核共享的读带宽/引擎/在途窗口/队列深度/阶段门控”。

这条链路的实现边界是：

- 仅对 `workload_impl=snn` 生效；非 SNN workload 即使配置了 `dma_enable=1` 也会被忽略。
- 仅覆盖 `WeightMemorySubsystem` 发起的**运行期 read path**。
- 当前只建模 **read-side DMA**；不覆盖 write-back DMA、跨 PE 共享 DMA、row-streaming 专用数据面。
- 后端仍保持 `memHierarchy` / cacheline 语义；DMA 调度器不替代内存控制器或 DRAM 地址映射。

当前实现由 3 个内部对象构成：

- `api/IDmaTaggedAccess.h`
  - 在不破坏 `IMemoryAccess` 边界的前提下，为上层读请求附带 `tag + priority`。
- `services/memory/DmaMemAccessProxy.{h,cc}`
  - 每 core 一个代理；对外仍表现为 `IMemoryAccess`，对内把 tagged read 提交到共享调度器。
- `services/memory/PeDmaScheduler.{h,cc}`
  - 每 PE 一个共享 DMA 调度器；维护多优先级队列、按 core 轮转公平、burst 发射、阶段预算和统计。

调度语义（当前口径）：

- 优先级：`P0 -> P1 -> P2 -> P3`，同优先级内部按 core round-robin。
- GAS 阶段门控：`Gather / Apply / Scatter / Idle` 四阶段分别使用不同 budget scale，避免 prefetch/demand 在错误阶段吞掉主路径预算。
- 资源上限：可分别建模 `bytes_per_cycle`、`read_engines`、`max_inflight`、`queue_depth`。
- 可选细化：支持 `dma_burst_bytes`、`dma_setup_cycles`、`dma_channels`、`dma_channel_bytes_per_cycle`、`dma_channel_interleave_bytes`。
- 队列溢出策略：`dma_overflow_policy=block|fail_fast`。
- 稳定性护栏：调度器内部带有 backend reject 重试与 inflight timeout 收敛逻辑，避免长时间卡死。

基础配置入口（spec-first，位于 `components.pe`）：

```json
{
  "components": {
    "pe": {
      "dma_enable": 1,
      "dma_bytes_per_cycle": 256,
      "dma_read_engines": 2,
      "dma_max_inflight": 64,
      "dma_queue_depth": 1024
    }
  }
}
```

进阶参数（仍位于 `components.pe`）：

- `dma_overflow_policy`
- `dma_burst_bytes`
- `dma_setup_cycles`
- `dma_channels`
- `dma_channel_bytes_per_cycle`
- `dma_channel_interleave_bytes`
- `dma_stage_budget_scale_{gather|apply|scatter|idle}_{p0|p1|p2|p3}`

可观测统计（`MultiCorePE`）：

- `dma_issue_reqs_total`
- `dma_issue_bytes_total`
- `dma_queue_depth_max_p{0,1,2,3}`
- `dma_inflight_max`
- `dma_stall_cycles_{budget,engine,inflight,stage_gate,queue_full}`

推荐验证入口：

- case：
  - `snndl-thing-exp/cases/pe_dma_ab_smoke`
  - `snndl-thing-exp/cases/pe_dma_budget_throttle`
  - `snndl-thing-exp/cases/pe_dma_stage_gate_prefetch`
- tests：
  - `snndl-thing-exp/tests/test_pe_dma_cases.py`
  - `tests/test_pe_dma_scheduler.cc`

### GAS Apply 发射策略（DRAM-aware，可选）

`components/GatherBufferIF` 在 Apply 阶段会把“已构建的 granule 列表”向下游发起读请求。默认策略 `apply_issue_policy=order` 保持确定性与可回归；当需要研究
DRAM 行局部性/BLP（bank-level parallelism）时，可显式开启 DRAM-aware 发射策略（探索性优化，默认关闭）：

- `bank_rr_row_sticky_age`：按 bank 轮转发射；同 bank 内尽量保持 row stickiness，并以 `apply_age_fair_ns` 做老化公平，避免饥饿。
- `dram_aware_v1`：更激进的探索策略（带 cost/overfetch 约束），仅建议在 microbench/sweep 中使用。
- `cmd_aware_v1`：实验性命令感知策略（shadow command model）；根据 bank busy 与预测 row-hit/row-miss 代价选择发射顺序。默认关闭，仅用于实验分支。

重要：上述策略依赖 `bank_bits/bank_shift/row_bytes_guess` 对地址做 bank×row 分桶/排序；若这些参数与后端 DRAM 地址映射不对齐，可能出现明显退化（因为调度器在
“伪 bank/伪 row”上做优化）。使用 Ramulator2（`AddrMapper=ChRaBaRoCo`）时建议显式校准并固定参数：

| backend（Ramulator2 preset） | 推荐 env（mesh_template） |
| --- | --- |
| DDR5（`DDR5_8Gb_x8`，见 `sst_dram_si/configs/ramulator2_ddr5.cfg`） | `MESH_GAS_ROW_BYTES_GUESS=4096` `MESH_GAS_BANK_BITS=4` `MESH_GAS_BANK_SHIFT=28` |
| HBM2（`HBM2_4Gb`，见 `sst_dram_si/configs/ramulator2_hbm2.cfg`） | `MESH_GAS_ROW_BYTES_GUESS=512` `MESH_GAS_BANK_BITS=5` `MESH_GAS_BANK_SHIFT=23` |

配套建议（避免“策略被节流成串行”）：
- `MESH_GAS_SORT_POLICY="bank_row"`（让排序键与调度策略一致）
- `MESH_GAS_APPLY_BANK_CREDIT="0"`（禁用 per-bank credit 限制；否则 bank_rr 可能无法并行）

`cmd_aware_v1` 的实验参数（仅在 `MESH_EXPERIMENTAL_ENABLE=1` + `MESH_GAS_APPLY_ISSUE_POLICY=cmd_aware_v1` 时生效）：
- `MESH_GAS_APPLY_CMD_PROBE_DEPTH`
- `MESH_GAS_APPLY_CMD_T_ROW_HIT_NS`
- `MESH_GAS_APPLY_CMD_T_ROW_MISS_NS`
- `MESH_GAS_APPLY_CMD_MISS_PENALTY_NS`
- `MESH_GAS_APPLY_CMD_ENABLE_ROW_LOCALITY`
- `MESH_GAS_APPLY_CMD_ENABLE_BANK_BUSY`

#### GAS 段构建：DRAM 命令代价护栏（实验，默认关闭）

在 `components/GatherBufferIF` 的段构建阶段（`buildGranulesWithGapMergeBuf_()`），可启用一个 **deterministic** 的“DRAM 命令代价”护栏，用于抑制吸洞/粗合并造成的病态 over-fetch：

- 作用范围：仅影响 **段构建决策**（是否吸洞、row-window 粗合并是否允许吸洞）；**不跨 DRAM row**（仍按 bank×row 分桶，row 由 `row_bytes_guess`/`dram_row_bytes` 定义）。
- 代价模型：把“吸洞的额外 cacheline row-hit 代价”与“避免一次 row-miss 的收益”做比较；由 `{t_row_hit_ns,t_row_miss_ns,line_bytes}` 计算可接受 gap（k）并用于 veto。
- 开关（仅在 `MESH_EXPERIMENTAL_ENABLE=1` 时允许脚本层覆盖）：
  - `MESH_GAS_DRAM_CMD_COST_MERGE_ENABLE=1`
  - `MESH_GAS_DRAM_CMD_T_ROW_HIT_NS`（默认 30）
  - `MESH_GAS_DRAM_CMD_T_ROW_MISS_NS`（默认 120）

复现脚本（dense microbench，快速验证映射/策略是否合理）：
- `sst_dram_si/tools/run_dense_microbench_4x4_exec_mode_compare_with_time.sh`

更多背景与校准说明见：`components/gather/README.md` 与 `docs/plans/2026-02-14-gas-ab-weights-phys-layout-v1.md`。

---

## Native Multicast（SpikeKey / blocked multicast）

SnnDL 支持一条“原生多播（native multicast）”路径：以 `SpikeKey` 包承载“块内多播目标集合（core mask）”，并采用“两阶段路由”：

- **INTER（块间单播）**：每个目标 block 只发一个包，单播到该 block 的 `ingress_node`。
- **INTRA（块内多播）**：包到达 ingress 后在 block 内按树扩散，并按 `core_mask[cell]` 精确投递到目标 core。

关键约束（当前实现口径）：
- `multicast_block_w * multicast_block_h <= 64`（固定 payload 上限）
- `cores_per_pe <= 32`（core mask 使用 32-bit 位图）

推荐入口（端到端验证 + 统计落盘）：
- `experimental_features/native_multicast_lab/`（实验脚本与 runner）

---

## 目录结构（按边界划分）

> 说明：以“源码子目录”为准（忽略 `.deps/.libs` 等构建产物目录）。多数源码子目录都有 README，优先以子目录 README 为准（缺失时以本 README + 代码为准）。

```
SnnDL/
├── api/            # 跨层稳定接口（窄抽象）
├── events/         # 事件与数据载体（Spike/Gating 等）
├── components/     # SST 组件装配壳（ELI 注册对象）
│   ├── gas/            # 全局 Step/GAS 同步控制面（barrier 等）
│   ├── gather/         # GatherBufferIF 构造期参数解析收敛（不新增运行期组件）
│   ├── multicore/      # MultiCorePE 构造期参数解析收敛（不新增运行期组件）
│   ├── noc/            # 可选 NoC/多播相关组件（实验/高级用法）
│   ├── stimulus/       # 可选 Stimulus 注入型组件（如 SpikeSource）
│   ├── mpi/            # MPI 扩展（可选编译）
│   └── workload_stats/ # workload 统计模块注册表与实现（tensor/stream 等）
├── control/        # 通用 CoreShell（平台壳：clock/packet/stat + workload 运行时绑定）
├── compute/        # 可替换 compute core（神经动力学/学习/验证）
├── services/       # 可复用事务子系统（按子域拆分）
│   ├── noc/        # NoC 传输域（send/recv/forward/本地投递）
│   ├── memory/     # 纯内存访问域（地址→字节块）
│   ├── synapse/    # 突触语义域（weights/route/gas 事务闭环）
│   ├── stimulus/   # Stimulus 域（Step 注入/外部刺激）
│   ├── workload/   # Workload 插件域（snn/stream/traffic/tensor）
│   │   ├── snn/    # Spike/GAS/BCSR/Step 主链路
│   │   ├── stream/ # packet-first + mem read-after-write 校验
│   │   ├── traffic/ # 通信/多播验证负载（不建模动力学）
│   │   ├── tensor/ # GEMM/systolic 类 compute+memory+NoC 压力
│   │   └── layout/ # Workload neuron layout 口径归一化（num_neurons/neurons_per_pe/base）
│   └── legacy/     # 历史遗留/参考实现（默认不进主链路）
├── docs/           # 设计与阶段性方案文档
└── tests/          # include 自检等轻量测试
```

---

## 关键边界（控制 / 计算 / 路由 / 内存 / 权重）

- `components/`：SST 对接与装配壳（端口、Link、Clock、Stat、生命周期）；尽量不写算法事务。
- `control/`：通用 CoreShell（时钟驱动、packet 递送、统计汇聚）；**不承载 SNN 业务状态机**（但会保留 GAS/Step 控制面事件转发与 legacy 兼容残留，逐步下沉中）。
- `services/workload/`：workload 插件（例如 `snn`/`stream`）；承载业务状态机与事务编排。
- `services/workload/traffic`：通信/多播验证用 workload；不建模动力学，但可复用 `synapse/route` 的 fanout/multicast 事务。
- `compute/`：神经动力学与学习等计算逻辑（`ISnnComputeCore`）；**不直接触碰 StandardMem/NoC**（通过 `IWeightReader`/workload 注入）。
- `services/noc/`：纯传输（send/recv/forward/本地投递）；**不做 fanout/权重语义**。
- `services/memory/`：纯地址/字节访问；**不出现权重/突触/路由语义**。
- `services/synapse/`：权重语义/路由与 fanout/GAS 辅助（weights/route/gas 事务闭环）。
- `services/stimulus/`：注入时基与选源（Step 等刺激）；通过 NoC/Route 完成投递与外发。

---

## 开发提示

- 修改 C++ 后必须执行 `make install` 才会影响实际 `sst` 运行加载的元素库。
  - 若使用 `SST_ADD_LIB_PATH="<.../SnnDL/.libs[:...]>"`
    并配合 `SST_BIN="sst_workspace/sst-core/src/sst/core/sst"` 运行，可在不 install 的情况下验证本地编译产物。
- 若需要调整构建清单：优先改 `Makefile.am`。若需要让改动生效：
  - 推荐：在 `sst_workspace/sst-elements/` 目录运行 `autoreconf -fi` 重生成 `Makefile.in`，再运行 `./config.status` 刷新各子目录 `Makefile`。
  - 若不方便跑 autotools：请同时手动更新 `Makefile.in`，并在 `sst_workspace/sst-elements/` 运行 `./config.status`。
- `configure.m4` 提供 `--with-hdf5`（预留/占位）：当前代码未使用 `HAVE_HDF5`，且 `Makefile.am` 未链接 HDF5；如需启用需补齐实现/链接与验证。
- Tier2-E：若 `workload=snn` 支持 `api/IWeightReaderAdopter.h`，CoreShell 会在 runtime 绑定后把已装配的 `IWeightReader`（通常为 `WeightMemorySubsystem`）**一次性移交所有权**给 workload，避免 control/workload 双实例装配（脚本参数与外部接口不变）。
- 回归建议：每个阶段至少跑一次 `MESH_MAX_STEPS="4"`，并对比 `essential_summary_mesh.json` 的关键字段（避免非确定性回归）。

---

## 对比实验输出（GAS vs naive）

mesh 模板支持 `MESH_EXEC_MODE=gas|naive_raw|naive_opt` 的对比实验（统一 step-limited 口径建议使用 `MESH_MAX_STEPS=4`），输出目录为：

- `sst_dram_si/outputs_large/paper2/dram_mesh_4x4_exec_mode_compare/`

详见该目录的 README：`sst_dram_si/outputs_large/paper2/dram_mesh_4x4_exec_mode_compare/README.md`
